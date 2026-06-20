"""
Geocoding Service for InBack.ru
Provides address parsing and geocoding using Yandex Maps API
Following best practices from Domclick and Yandex Realty
"""

import os
import time
import logging
import requests
from typing import Dict, List, Optional, Tuple, Any, Union
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


class GeocodingCache:
    """Simple in-memory cache with TTL for geocoding results"""
    
    def __init__(self, ttl_hours: int = 24):
        self.cache = {}
        self.ttl_seconds = ttl_hours * 3600
    
    def get(self, key: str) -> Optional[Any]:
        """Get cached value if not expired"""
        if key in self.cache:
            value, timestamp = self.cache[key]
            if time.time() - timestamp < self.ttl_seconds:
                return value
            else:
                del self.cache[key]
        return None
    
    def set(self, key: str, value: Any):
        """Set value in cache with current timestamp"""
        self.cache[key] = (value, time.time())
    
    def clear(self):
        """Clear all cached values"""
        self.cache.clear()


class DistrictPIPCache:
    """
    Loads district polygons from DB once per process and provides
    point-in-polygon matching without any external API calls.

    Uses psycopg2 directly to avoid circular imports with models.py.
    Polygons are stored as a list of (lat, lon) tuples.
    Districts are sorted smallest-polygon-first so the most specific
    match (microrayon) wins over a larger okrug.
    """

    # Module-level singleton — shared across all YandexGeocodingService instances
    _instance = None

    def __init__(self):
        self._loaded = False
        self._districts = []   # all districts sorted smallest→largest
        self._okrugs = []      # only okrug-type districts

    # ── geometry helpers ────────────────────────────────────────────────────

    @staticmethod
    def _parse_polygon(geom_str: str) -> List[Tuple[float, float]]:
        """Parse 'lat,lon;lat,lon;…' geometry string into list of (lat, lon)."""
        pairs = []
        for part in geom_str.split(';'):
            part = part.strip()
            if ',' in part:
                try:
                    lat, lon = part.split(',', 1)
                    pairs.append((float(lat), float(lon)))
                except ValueError:
                    pass
        return pairs

    @staticmethod
    def _bbox(polygon: List[Tuple[float, float]]) -> Tuple[float, float, float, float]:
        lats = [p[0] for p in polygon]
        lons = [p[1] for p in polygon]
        return min(lats), max(lats), min(lons), max(lons)

    @staticmethod
    def _point_in_polygon(lat: float, lon: float,
                          polygon: List[Tuple[float, float]]) -> bool:
        """Ray-casting algorithm."""
        n = len(polygon)
        if n < 3:
            return False
        inside = False
        j = n - 1
        for i in range(n):
            xi, yi = polygon[i]
            xj, yj = polygon[j]
            if ((yi > lon) != (yj > lon)) and (lat < (xj - xi) * (lon - yi) / (yj - yi) + xi):
                inside = not inside
            j = i
        return inside

    # ── loading ─────────────────────────────────────────────────────────────

    def load(self, db_url: Optional[str] = None) -> None:
        """Load district polygons from PostgreSQL. Safe to call multiple times."""
        if self._loaded:
            return
        url = db_url or os.environ.get('DATABASE_URL')
        if not url:
            logger.warning("DistrictPIPCache: no DATABASE_URL, PIP disabled")
            self._loaded = True
            return
        try:
            import psycopg2
            conn = psycopg2.connect(url)
            cur = conn.cursor()
            cur.execute("""
                SELECT id, name, district_type, city_id, slug, geometry
                FROM districts
                WHERE geometry IS NOT NULL
                  AND char_length(geometry) > 200
                  AND COALESCE(CAST(osm_id AS TEXT), '') NOT IN ('7373058')
                  AND name NOT ILIKE '%краснодарский край%'
                  AND name NOT ILIKE '%краснодарский%'
            """)
            raw = cur.fetchall()
            cur.close()
            conn.close()

            districts = []
            for row in raw:
                poly = self._parse_polygon(row[5])
                if len(poly) < 3:
                    continue
                districts.append({
                    'id':   row[0],
                    'name': row[1],
                    'type': row[2],
                    'city_id': row[3],
                    'slug': row[4],
                    'poly': poly,
                    'bb':   self._bbox(poly),
                    'size': len(poly),
                })

            # Sort smallest→largest so the most specific district wins first
            self._districts = sorted(districts, key=lambda d: d['size'])
            self._okrugs    = [d for d in self._districts
                               if d['type'] in ('okrug', 'admin')]
            self._loaded = True
            logger.info(f"DistrictPIPCache: loaded {len(self._districts)} districts "
                        f"({len(self._okrugs)} okrugs)")
        except Exception as e:
            logger.warning(f"DistrictPIPCache.load() failed: {e}")
            self._loaded = True  # mark as loaded so we don't retry endlessly

    def reload(self) -> None:
        """Force reload from DB (e.g. after district geometry updates)."""
        self._loaded = False
        self._districts = []
        self._okrugs = []
        self.load()

    # ── lookup ───────────────────────────────────────────────────────────────

    def find_district_by_name(self, name: str,
                               city_id: Optional[int] = None) -> Optional[Dict]:
        """
        Fuzzy-match a district name string against loaded districts.
        Returns the first district whose name contains `name` (case-insensitive)
        or whose name is contained in `name`, filtered by city_id if given.
        Used to map Nominatim/Yandex text results → district_id FK.
        """
        self.load()
        if not name:
            return None
        name_lower = name.lower().strip()
        best = None
        best_len = 0
        for d in self._districts:
            if city_id is not None and d['city_id'] != city_id:
                continue
            d_name = d['name'].lower()
            # Check if district name appears in the search string or vice-versa
            if d_name in name_lower or name_lower in d_name:
                # Prefer longer (more specific) match
                if len(d_name) > best_len:
                    best = d
                    best_len = len(d_name)
        return best

    def find_district(self, lat: float, lon: float
                      ) -> Tuple[Optional[Dict], Optional[Dict]]:
        """
        Return (most_specific_district, containing_okrug) for (lat, lon).
        Both may be None if the point is outside all known polygons.
        The most_specific_district is the smallest polygon that contains the point.
        """
        self.load()

        micro = None
        for d in self._districts:
            bb = d['bb']
            if bb[0] <= lat <= bb[1] and bb[2] <= lon <= bb[3]:
                if self._point_in_polygon(lat, lon, d['poly']):
                    micro = d
                    break

        okrug = None
        # If the matched district is already an okrug, it IS the okrug
        if micro and micro['type'] in ('okrug', 'admin'):
            okrug = micro
            micro = None
        else:
            # Find the containing okrug (larger polygon)
            for d in self._okrugs:
                bb = d['bb']
                if bb[0] <= lat <= bb[1] and bb[2] <= lon <= bb[3]:
                    if self._point_in_polygon(lat, lon, d['poly']):
                        okrug = d
                        break

        return micro, okrug


# Module-level singleton shared across service instances
_pip_cache = DistrictPIPCache()


class YandexGeocodingService:
    """
    Yandex Maps Geocoding Service
    Handles reverse geocoding, forward geocoding, and autocomplete.
    Also provides district enrichment via PIP + Yandex + Nominatim fallback.
    """
    
    BASE_URL = "https://geocode-maps.yandex.ru/1.x/"
    SUGGEST_URL = "https://suggest-maps.yandex.ru/v1/suggest"
    NOMINATIM_URL = "https://nominatim.openstreetmap.org/reverse"
    NOMINATIM_HEADERS = {"User-Agent": "InBack-RealEstate-Enricher/1.0"}
    
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.environ.get('YANDEX_MAPS_API_KEY')
        if not self.api_key:
            logger.warning("YANDEX_MAPS_API_KEY not found in environment")
        
        self.cache = GeocodingCache(ttl_hours=24)
        self.request_count = 0
        self.cache_hits = 0
    
    def _make_request(self, url: str, params: Dict) -> Optional[Dict]:
        """Make HTTP request with error handling and retry logic"""
        try:
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            self.request_count += 1
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"Geocoding API error: {e}")
            return None
    
    def reverse_geocode(self, latitude: float, longitude: float, kind: Optional[str] = None) -> Optional[Dict]:
        """
        Convert coordinates to address (reverse geocoding)
        
        Args:
            latitude: Latitude coordinate
            longitude: Longitude coordinate
            kind: Filter by type (house, street, district, locality)
        
        Returns:
            Dict with address components or None if error
        """
        cache_key = f"reverse:{latitude},{longitude}:{kind or 'all'}"
        cached = self.cache.get(cache_key)
        if cached:
            self.cache_hits += 1
            logger.debug(f"Cache hit for reverse geocoding: {cache_key}")
            return cached
        
        params = {
            'apikey': self.api_key,
            'geocode': f"{longitude},{latitude}",  # Yandex uses lon,lat order
            'format': 'json',
            'lang': 'ru-RU',
            'results': 1
        }
        
        if kind:
            params['kind'] = kind
        
        data = self._make_request(self.BASE_URL, params)
        if not data:
            return None
        
        result = self._parse_geocode_response(data)
        if result:
            self.cache.set(cache_key, result)
        
        return result
    
    def forward_geocode(self, address: str) -> Optional[Dict]:
        """
        Convert address to coordinates (forward geocoding)
        
        Args:
            address: Address string
        
        Returns:
            Dict with coordinates and parsed address components
        """
        cache_key = f"forward:{address.lower().strip()}"
        cached = self.cache.get(cache_key)
        if cached:
            self.cache_hits += 1
            logger.debug(f"Cache hit for forward geocoding: {cache_key}")
            return cached
        
        params = {
            'apikey': self.api_key,
            'geocode': address,
            'format': 'json',
            'lang': 'ru-RU',
            'results': 1
        }
        
        data = self._make_request(self.BASE_URL, params)
        if not data:
            return None
        
        result = self._parse_geocode_response(data)
        if result:
            self.cache.set(cache_key, result)
        
        return result
    
    def autocomplete(self, query: str, latitude: Optional[float] = None, 
                    longitude: Optional[float] = None, results: int = 7) -> List[Dict]:
        """
        Get address autocomplete suggestions using Geocoder API
        
        Args:
            query: Search query
            latitude: Optional latitude for geolocation bias
            longitude: Optional longitude for geolocation bias
            results: Max number of results (default 7)
        
        Returns:
            List of suggestion dictionaries
        """
        if not query or len(query) < 2:
            return []
        
        cache_key = f"autocomplete:{query.lower().strip()}:{latitude},{longitude}"
        cached = self.cache.get(cache_key)
        if cached:
            self.cache_hits += 1
            logger.debug(f"Cache hit for autocomplete: {cache_key}")
            return cached
        
        # Add Krasnodar context if not already in query
        search_query = query
        if 'краснодар' not in query.lower() and latitude and longitude:
            # Bias towards Krasnodar region
            search_query = f"Краснодар, {query}"
        
        params = {
            'apikey': self.api_key,
            'geocode': search_query,
            'format': 'json',
            'lang': 'ru-RU',
            'results': min(results, 10)
        }
        
        data = self._make_request(self.BASE_URL, params)
        if not data:
            return []
        
        try:
            feature_members = data['response']['GeoObjectCollection']['featureMember']
            suggestions = []
            
            for member in feature_members:
                geo_object = member['GeoObject']
                metadata = geo_object['metaDataProperty']['GeocoderMetaData']
                
                # Extract coordinates
                pos = geo_object['Point']['pos'].split()
                lon, lat = float(pos[0]), float(pos[1])
                
                suggestion = {
                    'text': metadata.get('text', ''),
                    'title': metadata.get('text', '').split(', ')[-1] if ',' in metadata.get('text', '') else metadata.get('text', ''),
                    'subtitle': metadata.get('Address', {}).get('formatted', ''),
                    'type': metadata.get('kind', 'unknown'),
                    'latitude': lat,
                    'longitude': lon
                }
                
                suggestions.append(suggestion)
            
            self.cache.set(cache_key, suggestions)
            return suggestions
            
        except (KeyError, IndexError, ValueError) as e:
            logger.error(f"Error parsing autocomplete response: {e}")
            return []
    
    def _parse_geocode_response(self, data: Dict) -> Optional[Dict]:
        """
        Parse Yandex Geocoder API response and extract address components
        
        Returns:
            Dict with structured address data:
            {
                'formatted_address': str,
                'country': str,
                'region': str,
                'city': str,
                'district': str,
                'city_district': str,  # okrug
                'settlement': str,     # microrayon
                'street': str,
                'house': str,
                'postal_code': str,
                'latitude': float,
                'longitude': float,
                'precision': str
            }
        """
        try:
            feature_member = data['response']['GeoObjectCollection']['featureMember']
            if not feature_member:
                return None
            
            geo_object = feature_member[0]['GeoObject']
            metadata = geo_object['metaDataProperty']['GeocoderMetaData']
            
            # Extract coordinates
            pos = geo_object['Point']['pos'].split()
            longitude, latitude = float(pos[0]), float(pos[1])
            
            # Extract address components
            address_details = metadata['Address']
            components = address_details.get('Components', [])
            
            result = {
                'formatted_address': metadata.get('text', ''),
                'country': '',
                'region': '',
                'city': '',
                'district': '',       # legacy: last district component
                'city_district': '',  # okrug (e.g. «Центральный», «Прикубанский»)
                'settlement': '',     # microrayon (e.g. «Черемушки», «Самолёт»)
                'street': '',
                'house': '',
                'postal_code': address_details.get('postal_code', ''),
                'latitude': latitude,
                'longitude': longitude,
                'precision': metadata.get('precision', 'unknown'),
                'kind': metadata.get('kind', 'unknown')
            }
            
            # Yandex may return multiple district-kind components:
            # first = administrative okrug, subsequent = microrayon/settlement
            district_components = []
            
            # Parse components hierarchically
            for component in components:
                kind = component.get('kind', '')
                name = component.get('name', '')
                
                if kind == 'country':
                    result['country'] = name
                elif kind == 'province':
                    if not result['region']:
                        result['region'] = name
                elif kind == 'locality':
                    result['city'] = name
                elif kind == 'district':
                    district_components.append(name)
                elif kind == 'street':
                    result['street'] = name
                elif kind == 'house':
                    result['house'] = name
            
            # Assign district components:
            # 1st = city okrug (Центральный, Прикубанский…)
            # 2nd+ = settlement/microrayon (Черемушки, Самолёт…)
            if district_components:
                result['city_district'] = district_components[0]
                if len(district_components) > 1:
                    result['settlement'] = district_components[-1]
                # legacy field = most specific district
                result['district'] = district_components[-1]
            
            return result
            
        except (KeyError, IndexError, ValueError) as e:
            logger.error(f"Error parsing geocode response: {e}")
            return None

    def _nominatim_reverse(self, latitude: float, longitude: float) -> Dict:
        """
        Fallback reverse geocoding via Nominatim (OpenStreetMap).
        Rate-limited to 1 req/sec by caller; no internal caching here
        since this is only used when Yandex and PIP both fail.
        Returns raw address dict or {}.
        """
        try:
            resp = requests.get(
                self.NOMINATIM_URL,
                params={
                    "lat": latitude, "lon": longitude,
                    "format": "json", "accept-language": "ru",
                    "addressdetails": 1,
                },
                headers=self.NOMINATIM_HEADERS,
                timeout=10,
            )
            resp.raise_for_status()
            self.request_count += 1
            return resp.json().get("address", {})
        except Exception as e:
            logger.warning(f"Nominatim error ({latitude},{longitude}): {e}")
            return {}

    def enrich_property_address(self, latitude: float, longitude: float) -> Optional[Dict]:
        """
        Enrich property with parsed address components from coordinates.
        Returns structured CIAN-style address: region → city → district → street → house
        
        Returns:
            Dict with parsed_city, parsed_district, parsed_street, parsed_house,
            region_name, full_address
        """
        result = self.reverse_geocode(latitude, longitude, kind='house')
        
        if not result:
            return None
        
        city_district = result.get('city_district', '')  # okrug (Центральный)
        settlement    = result.get('settlement', '')      # microrayon (Черемушки)
        street        = result.get('street', '')
        house         = result.get('house', '')
        
        # Build CIAN-style breadcrumb: Край → Город → Округ → Микрорайон → Улица
        parts = []
        if result.get('region'):
            parts.append(result['region'])
        if result.get('city'):
            parts.append(result['city'])
        if city_district:
            parts.append(city_district)
        if settlement:
            parts.append(settlement)
        if street:
            addr_part = f'ул. {street}'
            if house:
                addr_part += f', {house}'
            parts.append(addr_part)

        # PIP district assignment (no API call — uses cached polygons)
        micro, okrug = _pip_cache.find_district(latitude, longitude)
        district_id = None
        if micro:
            district_id = micro['id']
        elif okrug:
            district_id = okrug['id']
        
        return {
            'parsed_city':       result.get('city', ''),
            'parsed_area':       city_district,            # округ (Центральный, Прикубанский)
            'parsed_settlement': settlement,                # микрорайон (Черемушки, Самолёт)
            'parsed_district':   settlement or city_district,  # legacy
            'parsed_street':     street,
            'parsed_house':      house,
            'parsed_block':      '',
            'district_id':       district_id,              # FK → districts.id (from PIP)
            'region_name':   result.get('region', ''),
            'full_address':  result.get('formatted_address', ''),
            'cian_address':  ' → '.join(parts) if parts else '',
            'postal_code':   result.get('postal_code', ''),
            'latitude':      result.get('latitude'),
            'longitude':     result.get('longitude'),
        }

    def enrich_complex_address(self, latitude: float, longitude: float,
                               nominatim_delay: float = 0.0) -> Dict:
        """
        Enrich a ResidentialComplex with full district hierarchy.

        Strategy (fastest to slowest, stops when enough data found):
          1. PIP  — instant, no network, uses cached district polygons
          2. Yandex reverse geocoding — fast, gives city_district + settlement strings
          3. Nominatim reverse geocoding — slow (1 req/sec policy), last resort

        Returns dict with keys:
          address_city_district  — okrug name  (e.g. «Центральный»)
          address_quarter        — microrayon  (e.g. «Самолёт»)
          district_id            — FK to districts.id (most specific polygon match)
          city                   — city name from Yandex
          region                 — region name from Yandex
          street                 — street from Yandex
          house                  — house number from Yandex
          full_address           — formatted address string from Yandex
        """
        out: Dict[str, Any] = {
            'address_city_district': '',
            'address_quarter':       '',
            'district_id':           None,
            'city':                  '',
            'region':                '',
            'street':                '',
            'house':                 '',
            'full_address':          '',
        }

        # ── Step 1: PIP ──────────────────────────────────────────────────────
        micro, okrug = _pip_cache.find_district(latitude, longitude)
        if micro:
            out['district_id']     = micro['id']
            out['address_quarter'] = micro['name']
            if okrug:
                out['address_city_district'] = okrug['name']
        elif okrug:
            out['district_id']            = okrug['id']
            out['address_city_district']  = okrug['name']

        # ── Step 2: Yandex (always run — best address strings, cached) ───────
        yandex = self.reverse_geocode(latitude, longitude, kind='house')
        if yandex:
            out['city']         = yandex.get('city', '')
            out['region']       = yandex.get('region', '')
            out['street']       = yandex.get('street', '')
            out['house']        = yandex.get('house', '')
            out['full_address'] = yandex.get('formatted_address', '')
            # Fill district strings if PIP didn't provide them
            if not out['address_city_district'] and yandex.get('city_district'):
                out['address_city_district'] = yandex['city_district']
            if not out['address_quarter'] and yandex.get('settlement'):
                out['address_quarter'] = yandex['settlement']

        # ── Step 3: Nominatim (only if still no district info) ────────────────
        if not out['address_city_district'] and not out['address_quarter']:
            if nominatim_delay > 0:
                time.sleep(nominatim_delay)
            nom = self._nominatim_reverse(latitude, longitude)
            if nom:
                cd = (nom.get('city_district') or nom.get('state_district') or '')
                q  = (nom.get('quarter')       or nom.get('suburb')         or '')
                # Skip quarters that are just digits or too short
                if q and (len(q) < 3 or q.isdigit()):
                    q = ''
                if cd:
                    out['address_city_district'] = cd
                if q:
                    out['address_quarter'] = q

        # ── Step 4: resolve district_id from name if PIP didn't find it ──────
        if not out['district_id']:
            # Try to match the quarter (microrayon) first, then okrug
            for name_to_try in filter(None, [out['address_quarter'],
                                             out['address_city_district']]):
                matched = _pip_cache.find_district_by_name(name_to_try)
                if matched:
                    out['district_id'] = matched['id']
                    # Backfill district strings from the matched record if empty
                    if matched['type'] in ('okrug', 'admin'):
                        if not out['address_city_district']:
                            out['address_city_district'] = matched['name']
                    else:
                        if not out['address_quarter']:
                            out['address_quarter'] = matched['name']
                    break

        return out

    def preload_pip(self) -> None:
        """Explicitly preload PIP district polygons (optional; auto-loads on first use)."""
        _pip_cache.load()

    def reload_pip(self) -> None:
        """Force reload of PIP district polygons from DB."""
        _pip_cache.reload()

    def get_stats(self) -> Dict:
        """Get service statistics"""
        cache_size = len(self.cache.cache)
        return {
            'api_requests': self.request_count,
            'cache_hits': self.cache_hits,
            'cache_size': cache_size,
            'cache_hit_rate': f"{(self.cache_hits / max(1, self.request_count + self.cache_hits) * 100):.1f}%",
            'pip_districts': len(_pip_cache._districts),
        }


# Global service instance
_geocoding_service = None

def get_geocoding_service() -> YandexGeocodingService:
    """Get or create global geocoding service instance"""
    global _geocoding_service
    if _geocoding_service is None:
        _geocoding_service = YandexGeocodingService()
    return _geocoding_service
