// Properties Mini Map (Yandex Maps - Avito-style)
console.log('🗺️ properties_mini_map.js загружен');

// Global mouse position tracker (used by hover tooltip positioning)
document.addEventListener('mousemove', function(e) { window._lastMouseEvt = e; }, { passive: true });

// Helper: proxy external CIAN image URLs through /api/image-proxy
// Respects the admin setting: window.imageProxyEnabled (set in properties.html)
function _proxyImg(url) {
    if (!url || url.startsWith('/') || url.startsWith('data:') || url.startsWith('blob:')) return url;
    if (!window.imageProxyEnabled) return url;
    return '/api/image-proxy?url=' + encodeURIComponent(url) + '&crop=8';
}

// CHECK META TAGS AT PAGE LOAD
const chkLat = document.querySelector('meta[name="city-lat"]');
const chkLon = document.querySelector('meta[name="city-lon"]');
if (chkLat && chkLon) {
    console.log(`✅ LOADED: city-lat=${chkLat.getAttribute('content')}, city-lon=${chkLon.getAttribute('content')}`);
} else {
    console.warn(`⚠️ META TAGS NOT FOUND at page load`);
}

// ✅ Helper function to get current filter parameters for mini-map API
function getMiniMapFilterParams() {
    const urlParams = new URLSearchParams(window.location.search);
    const params = new URLSearchParams();
    
    // City ID
    const cityId = window.currentCityId || urlParams.get('city_id');
    if (cityId) params.set('city_id', cityId);

    // Locked district (SEO pages) — numeric id
    const lockedDist = window.lockedDistrictId || urlParams.get('district_id');
    if (lockedDist) params.set('district_id', lockedDist);

    // Locked district slug (SEO pages like /sochi/kvartiry?districts=krasnaya-polyana)
    const lockedSlug = window.lockedDistrictSlug;
    const _urlSlugs = urlParams.getAll('districts').concat(urlParams.getAll('districts[]'));
    if (lockedSlug && !_urlSlugs.includes(lockedSlug)) {
        params.append('districts', lockedSlug);
    }
    
    // Key filters that affect map display
    if (urlParams.get('residential_complex')) params.set('residential_complex', urlParams.get('residential_complex'));
    urlParams.getAll('developer').concat(urlParams.getAll('developer[]')).forEach(d => { if (d) params.append('developer', d); });
    
    function getAll(key) {
        return urlParams.getAll(key).concat(urlParams.getAll(key + '[]'));
    }
    
    getAll('rooms').forEach(r => params.append('rooms', r));
    
    if (urlParams.get('property_type') && urlParams.get('property_type') !== 'all') params.set('property_type', urlParams.get('property_type'));
    if (urlParams.get('price_min')) params.set('price_min', urlParams.get('price_min'));
    if (urlParams.get('price_max')) params.set('price_max', urlParams.get('price_max'));
    if (urlParams.get('area_min')) params.set('area_min', urlParams.get('area_min'));
    if (urlParams.get('area_max')) params.set('area_max', urlParams.get('area_max'));
    
    getAll('developers').forEach(d => params.append('developers', d));
    getAll('districts').forEach(d => params.append('districts', d));
    getAll('completion').forEach(v => params.append('completion', v));
    getAll('object_classes').forEach(v => params.append('object_classes', v));
    getAll('renovation').forEach(v => params.append('renovation', v));
    getAll('features').forEach(v => params.append('features', v));
    getAll('building_released').forEach(v => params.append('building_released', v));
    getAll('floor_options').forEach(v => params.append('floor_options', v));
    getAll('building_types').forEach(v => params.append('building_types', v));
    getAll('delivery_years').forEach(v => params.append('delivery_years', v));
    
    // Numeric range filters
    if (urlParams.get('floor_min')) params.set('floor_min', urlParams.get('floor_min'));
    if (urlParams.get('floor_max')) params.set('floor_max', urlParams.get('floor_max'));
    if (urlParams.get('building_floors_min')) params.set('building_floors_min', urlParams.get('building_floors_min'));
    if (urlParams.get('building_floors_max')) params.set('building_floors_max', urlParams.get('building_floors_max'));
    if (urlParams.get('build_year_min')) params.set('build_year_min', urlParams.get('build_year_min'));
    if (urlParams.get('build_year_max')) params.set('build_year_max', urlParams.get('build_year_max'));
    if (urlParams.get('cashback_only')) params.set('cashback_only', urlParams.get('cashback_only'));
    
    // Search filter from mapFilters (set by search input on map)
    if (window.mapFilters?.search) {
        params.set('search', window.mapFilters.search);
    } else if (urlParams.get('search')) {
        params.set('search', urlParams.get('search'));
    }

    // Quarter / city-district filter (e.g. ?quarter=Прикубанский)
    const qrtVal = (window.mapFilters?.quarter) || urlParams.get('quarter') || '';
    if (qrtVal) params.set('quarter', qrtVal);

    const queryString = params.toString();
    console.log('🗺️ Mini-map filter params:', queryString || '(none)');
    return queryString;
}

// Make function globally available
window.getMiniMapFilterParams = getMiniMapFilterParams;

/**
 * Sync current URL filter params → window.mapFilters
 * Called when opening the fullscreen map so map inherits list-view filters
 */
function syncUrlFiltersToMapFilters() {
    const url = new URLSearchParams(window.location.search);
    if (!window.mapFilters) return;

    // Helper: get all values for key (supports both ?k=a&k=b and ?k=a,b)
    function getMulti(key) {
        const vals = [];
        url.getAll(key).forEach(v => v.split(',').forEach(s => { if (s.trim()) vals.push(s.trim()); }));
        url.getAll(key + '[]').forEach(v => v.split(',').forEach(s => { if (s.trim()) vals.push(s.trim()); }));
        return vals;
    }

    // Rooms → array of ints
    const rooms = getMulti('rooms').map(Number).filter(n => !isNaN(n));
    window.mapFilters.rooms = rooms;

    // Price: URL stores rubles, mapFilters stores millions
    const pMin = url.get('price_min');
    const pMax = url.get('price_max');
    window.mapFilters.price_min = pMin ? (parseFloat(pMin) >= 1000 ? parseFloat(pMin) / 1000000 : parseFloat(pMin)) : '';
    window.mapFilters.price_max = pMax ? (parseFloat(pMax) >= 1000 ? parseFloat(pMax) / 1000000 : parseFloat(pMax)) : '';

    // Area / floor — copy as-is
    ['area_min','area_max','floor_min','floor_max',
     'building_floors_min','building_floors_max',
     'build_year_min','build_year_max'].forEach(k => {
        const v = url.get(k);
        window.mapFilters[k] = v || '';
    });

    // Multi-select arrays (stored as comma-separated or repeated params)
    const arrFields = ['districts','developers','completion','object_classes','building_status','renovation','features','floor_options','building_released'];
    arrFields.forEach(k => {
        window.mapFilters[k] = getMulti(k);
    });

    // Handle all singular 'developer' params (list view uses repeated ?developer=X&developer=Y)
    const allDevParams = url.getAll('developer').concat(url.getAll('developer[]'));
    allDevParams.forEach(function(d) {
        if (d && d.trim()) {
            if (!window.mapFilters.developers) window.mapFilters.developers = [];
            if (!window.mapFilters.developers.includes(d.trim())) {
                window.mapFilters.developers.push(d.trim());
            }
        }
    });
    // ✅ Singular 'district' alias (list view writes singular; map expects plural array)
    const singleDistrict = url.get('district');
    if (singleDistrict) {
        if (!window.mapFilters.districts) window.mapFilters.districts = [];
        if (!window.mapFilters.districts.includes(singleDistrict)) {
            window.mapFilters.districts.push(singleDistrict);
        }
    }

    // Search text
    const q = url.get('search') || url.get('q');
    if (q) window.mapFilters.search = q;

    // Quarter / city-district
    window.mapFilters.quarter = url.get('quarter') || '';

    // Cashback only
    const co = url.get('cashback_only');
    if (co) window.mapFilters.cashback_only = co;

    console.log('🔄 syncUrlFiltersToMapFilters: synced', JSON.stringify(window.mapFilters));
}
window.syncUrlFiltersToMapFilters = syncUrlFiltersToMapFilters;

/**
 * Persist current window.mapFilters → URL via history.replaceState.
 * Called from every filter mutation pipeline (updateMapWithFilters, mobile
 * search, etc.) so navigating to /object/<id> and pressing "back" restores
 * the full filter set including the open fullscreen-map state.
 */
function persistMapFiltersToUrl() {
    try {
        const mf = window.mapFilters || {};
        const u = new URL(window.location.href);
        const sp = u.searchParams;

        const clearKeys = [
            'rooms','price_min','price_max','area_min','area_max',
            'floor_min','floor_max','building_floors_min','building_floors_max',
            'build_year_min','build_year_max',
            'districts','developers','developer','district',
            'completion','object_classes','object_class','building_status',
            'renovation','features','floor_options','building_released',
            'search','cashback_only','quarter'
        ];
        clearKeys.forEach(k => { sp.delete(k); sp.delete(k + '[]'); });

        // Rooms (repeated)
        (mf.rooms || []).forEach(r => sp.append('rooms', String(r)));

        // Price: mapFilters stores millions, URL stores rubles (only when >= some threshold)
        const _setRange = (key, val) => {
            if (val === '' || val == null) return;
            sp.set(key, String(val));
        };
        if (mf.price_min !== '' && mf.price_min != null) {
            const v = parseFloat(mf.price_min);
            if (!isNaN(v)) sp.set('price_min', String(v < 1000 ? Math.round(v * 1000000) : v));
        }
        if (mf.price_max !== '' && mf.price_max != null) {
            const v = parseFloat(mf.price_max);
            if (!isNaN(v)) sp.set('price_max', String(v < 1000 ? Math.round(v * 1000000) : v));
        }
        _setRange('area_min', mf.area_min);
        _setRange('area_max', mf.area_max);
        _setRange('floor_min', mf.floor_min);
        _setRange('floor_max', mf.floor_max);
        _setRange('building_floors_min', mf.building_floors_min);
        _setRange('building_floors_max', mf.building_floors_max);
        _setRange('build_year_min', mf.build_year_min);
        _setRange('build_year_max', mf.build_year_max);

        // Multi-select arrays (repeated)
        const arrFields = ['districts','developers','completion','object_classes',
                           'building_status','renovation','features',
                           'floor_options','building_released'];
        arrFields.forEach(k => {
            const vals = mf[k];
            if (Array.isArray(vals)) {
                vals.forEach(v => { if (v !== '' && v != null) sp.append(k, String(v)); });
            }
        });

        if (mf.search) sp.set('search', String(mf.search));
        if (mf.quarter) sp.set('quarter', String(mf.quarter));
        if (mf.cashback_only) sp.set('cashback_only', String(mf.cashback_only));

        // Flag: fullscreen map is currently open — used on page (re)load to auto-open
        if (window._fullscreenMapOpen) {
            sp.set('map', '1');
        } else {
            sp.delete('map');
        }

        sp.delete('page');
        window.history.replaceState(null, '', u.toString());
    } catch (e) {
        console.warn('persistMapFiltersToUrl failed', e);
    }
}
window.persistMapFiltersToUrl = persistMapFiltersToUrl;

/**
 * Persist current map center/zoom to URL (map_center=lat,lng & map_zoom=N)
 * so that returning from /object/<id> via back-nav restores the exact viewport
 * the user had — not an auto-fit over filtered bounds.
 * Called from the boundschange handler (debounced) while the fullscreen map
 * is open.
 */
function persistMapViewportToUrl(center, zoom) {
    try {
        if (!window._fullscreenMapOpen) return;
        if (!Array.isArray(center) || center.length < 2) return;
        const u = new URL(window.location.href);
        u.searchParams.set('map_center', center[0].toFixed(5) + ',' + center[1].toFixed(5));
        u.searchParams.set('map_zoom', String(Math.round(zoom * 100) / 100));
        window.history.replaceState(null, '', u.toString());
    } catch (e) {
        console.warn('persistMapViewportToUrl failed', e);
    }
}
window.persistMapViewportToUrl = persistMapViewportToUrl;

/**
 * Read map_center/map_zoom from URL. Returns {center:[lat,lng], zoom:Number}
 * or null when missing/invalid.
 */
function readMapViewportFromUrl() {
    try {
        const sp = new URLSearchParams(window.location.search);
        const c = sp.get('map_center');
        const z = sp.get('map_zoom');
        if (!c || !z) return null;
        const parts = c.split(',');
        if (parts.length !== 2) return null;
        const lat = parseFloat(parts[0]);
        const lng = parseFloat(parts[1]);
        const zoom = parseFloat(z);
        if (isNaN(lat) || isNaN(lng) || isNaN(zoom)) return null;
        return { center: [lat, lng], zoom: zoom };
    } catch (e) {
        return null;
    }
}
window.readMapViewportFromUrl = readMapViewportFromUrl;

/**
 * Drop map_center/map_zoom from URL — used when user changes filters and the
 * stored viewport is no longer compatible (e.g. no results within bounds), or
 * when the fullscreen map is closed.
 */
function clearMapViewportFromUrl() {
    try {
        const u = new URL(window.location.href);
        let changed = false;
        if (u.searchParams.has('map_center')) { u.searchParams.delete('map_center'); changed = true; }
        if (u.searchParams.has('map_zoom'))   { u.searchParams.delete('map_zoom');   changed = true; }
        if (changed) window.history.replaceState(null, '', u.toString());
    } catch (e) {}
}
window.clearMapViewportFromUrl = clearMapViewportFromUrl;

/**
 * Repaint all map filter widgets (chips, inputs, search) from window.mapFilters.
 * Called after syncUrlFiltersToMapFilters so the modal/toolbar/quick-sheet
 * reflect inherited filter state on open & on page restore.
 */
// window.syncMapFiltersToUi — canonical implementation now lives in
// templates/properties.html (@~10436). Template-override побеждал в runtime
// и эта JS-копия превращалась в мёртвый код. Удалена чтобы убрать
// shadow-дубль (см. Task #7 round 3).

let miniPropertiesMapInstance = null;
let fullscreenMapInstance = null;
let mapInitTimeout = null;
let ymapsRetryTimeout = null;
let propertyIdToMarkerMap = {};  // ✅ Track markers by property ID for hover highlighting

// ✅ NEW: Variables for infinite scroll and viewport filtering
let currentDisplayOffset = 0;  // Offset for infinite scroll (how many cards loaded)
const CARDS_PER_PAGE = 20;     // Load 20 cards at a time
let isLoadingMoreCards = false; // Prevent multiple simultaneous loads
// Pagination state for server-side infinite scroll
window._mapCardsFetchPage    = 1;   // Last API page already fetched
window._mapCardsTotalPages   = 1;   // Total pages on server
window._mapCardsIsFetching   = false; // Guard against parallel API fetches
window._mapCardsTotalFromServer = 0; // True total (for header display)
let currentViewportProperties = []; // Properties visible in current map viewport

// Check if device is mobile
function isMobileDevice() {
    return window.innerWidth <= 1024;
}

function clusterCoordinates(coordinates, radius) {
    const clusters = [];
    const used = new Set();
    
    coordinates.forEach((coord, i) => {
        if (used.has(i)) return;
        
        const cluster = {
            lat: coord.lat,
            lng: coord.lng,
            count: 1
        };
        
        coordinates.forEach((other, j) => {
            if (i !== j && !used.has(j)) {
                const distance = Math.sqrt(
                    Math.pow(coord.lat - other.lat, 2) + 
                    Math.pow(coord.lng - other.lng, 2)
                );
                
                if (distance < radius) {
                    cluster.count++;
                    used.add(j);
                }
            }
        });
        
        used.add(i);
        clusters.push(cluster);
    });
    
    return clusters;
}

function initMiniPropertiesMap() {
    const mapElement = document.getElementById('miniPropertiesMap');
    if (!mapElement || miniPropertiesMapInstance) return;
    
    if (typeof ymaps === 'undefined') {
        console.warn('ymaps not loaded yet, retrying in 500ms');
        setTimeout(initMiniPropertiesMap, 500);
        return;
    }
    
    ymaps.ready(function() {
        try {
            // Начальный центр — берём из глобального cityCoordinates (установлен в шаблоне), fallback Краснодар
            const _miniInitCenter = window.cityCoordinates || [45.0355, 38.9753];
            const _miniInitZoom = window.cityZoom || 11;
            miniPropertiesMapInstance = new ymaps.Map('miniPropertiesMap', {
                center: _miniInitCenter,
                zoom: _miniInitZoom,
                controls: []
            }, {
                suppressMapOpenBlock: true,
                yandexMapDisablePoiInteractivity: true
            });
            
            miniPropertiesMapInstance.behaviors.disable(['drag', 'scrollZoom', 'dblClickZoom', 'multiTouch']);
            
            const miniMapParams = getMiniMapFilterParams();
            const isMobLimit = isMobileDevice() ? '&limit=300' : '';
            fetch('/api/mini-map/properties' + (miniMapParams ? '?' + miniMapParams + isMobLimit : '?limit=300'), {
                credentials: 'same-origin'
            })
                .then(response => response.json())
                .then(data => {
                    if (data.success && data.coordinates && data.coordinates.length > 0) {
                        console.log(`✅ Loaded ${data.count} property coordinates`);
                        
                        // On mobile, limit markers to 300 for better performance
                        const isMob = isMobileDevice();
                        const coordsToRender = isMob ? data.coordinates.slice(0, 300) : data.coordinates;
                        if (isMob && data.coordinates.length > 300) {
                            console.log(`📱 Mobile: rendering ${coordsToRender.length} of ${data.coordinates.length} markers for performance`);
                        }
                        
                        // Кластеризация через ymaps.Clusterer
                        const clusterLayout = ymaps.templateLayoutFactory.createClass(
                            '<div style="background:#0088CC;color:#fff;border-radius:50%;width:28px;height:28px;display:flex;align-items:center;justify-content:center;font-weight:700;font-size:11px;border:2px solid #fff;box-shadow:0 2px 8px rgba(0,136,204,0.4);">{{ properties.geoObjects.length }}</div>'
                        );
                        const dotLayout = ymaps.templateLayoutFactory.createClass(
                            '<div style="width:9px;height:9px;background:#0088CC;border-radius:50%;border:2px solid #fff;box-shadow:0 1px 4px rgba(0,136,204,0.4);"></div>'
                        );
                        const miniClusterer = new ymaps.Clusterer({
                            clusterIconLayout: clusterLayout,
                            clusterIconShape: { type: 'Circle', coordinates: [14, 14], radius: 14 },
                            gridSize: isMob ? 80 : 50,
                            groupByCoordinates: false
                        });
                        const miniPlacemarks = coordsToRender.map(c => {
                            const pm = new ymaps.Placemark([c.lat, c.lng], {}, {
                                iconLayout: dotLayout,
                                iconShape: { type: 'Circle', coordinates: [4, 4], radius: 4 }
                            });
                            pm.events.add('click', function(e) { e.stopPropagation(); handleMapClick(); });
                            return pm;
                        });
                        miniClusterer.add(miniPlacemarks);
                        miniPropertiesMapInstance.geoObjects.add(miniClusterer);
                        miniClusterer.events.add('click', function() { handleMapClick(); });
                        
                        console.log(`✅ Created ${miniPlacemarks.length} markers in mini-map clusterer`);
                        
                        // 🎯 АВТОМАТИЧЕСКОЕ ЦЕНТРИРОВАНИЕ ПО ОБЪЕКТАМ
                        // Вычисляем границы по всем (не обрезанным) координатам для правильного центра
                        const bounds = data.coordinates.reduce((acc, coord) => {
                            if (acc.minLat === undefined || coord.lat < acc.minLat) acc.minLat = coord.lat;
                            if (acc.maxLat === undefined || coord.lat > acc.maxLat) acc.maxLat = coord.lat;
                            if (acc.minLng === undefined || coord.lng < acc.minLng) acc.minLng = coord.lng;
                            if (acc.maxLng === undefined || coord.lng > acc.maxLng) acc.maxLng = coord.lng;
                            return acc;
                        }, {});
                        
                        // Устанавливаем карту по границам объектов с небольшим отступом
                        miniPropertiesMapInstance.setBounds([
                            [bounds.minLat, bounds.minLng],
                            [bounds.maxLat, bounds.maxLng]
                        ], {
                            checkZoomRange: true,
                            zoomMargin: 20
                        });
                        
                        console.log(`🎯 Auto-centered map: [${bounds.minLat.toFixed(4)}, ${bounds.minLng.toFixed(4)}] - [${bounds.maxLat.toFixed(4)}, ${bounds.maxLng.toFixed(4)}]`);
                    }
                    // Hide loading skeleton
                    const skeleton = document.getElementById('miniPropertiesMapSkeleton');
                    if (skeleton) { skeleton.style.opacity = '0'; setTimeout(() => skeleton.remove(), 500); }
                })
                .catch(error => {
                    console.error('❌ Error loading property coordinates:', error);
                    const skeleton = document.getElementById('miniPropertiesMapSkeleton');
                    if (skeleton) skeleton.remove();
                });
            
            console.log('✅ Yandex mini map initialized for properties');
        } catch (error) {
            console.error('❌ Error initializing Yandex mini map:', error);
        }
    });
}

// Open fullscreen map modal (Mobile + Desktop responsive)
function openFullscreenMap() {
    console.log('🔥🔥🔥 FULLSCREEN MAP OPENING - START');
    const modal = document.getElementById('fullscreenMapModal');
    if (!modal) { console.error('❌ Modal not found'); return; }
    
    const isMobile = window.innerWidth <= 1024;
    console.log(`🗺️ Opening fullscreen map modal (${isMobile ? 'mobile' : 'desktop'})`)
    console.log(`📊 ymaps exists: ${typeof ymaps !== 'undefined'}`)
    console.log(`📊 fullscreenMapInstance: ${typeof window.fullscreenMapInstance}`)
    console.log(`📊 mapAllProperties: ${Array.isArray(window.mapAllProperties) ? window.mapAllProperties.length + ' items' : 'NOT FOUND'};`);
    
    modal.classList.remove('hidden');
    document.body.style.overflow = 'hidden';
    
    const siteHeader = document.querySelector('header.sticky');
    if (siteHeader) {
        siteHeader.style.display = 'none';
    }
    const mobileNav = document.getElementById('mobileBottomNav');
    if (mobileNav) {
        mobileNav.style.display = 'none';
    }

    // Hide Chaport chat widget — it overlaps map controls on mobile
    // Use body class so it also catches Chaport that loads lazily after map open
    document.body.classList.add('fullscreen-map-open');
    const chaport = document.getElementById('chaport-container');
    if (chaport) chaport.style.setProperty('display', 'none', 'important');
    // Explicitly hide InBack chat FAB elements (CSS class alone isn't reliable on all devices)
    ['chatFab', 'chatFabRing', 'inbackChatPanel'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.style.setProperty('display', 'none', 'important');
    });
    
    // ✅ Inherit filters from list view (URL params → window.mapFilters)
    syncUrlFiltersToMapFilters();
    // ✅ Reflect synced filters in the UI: pre-check chips & fill modal inputs
    if (typeof window.syncMapFiltersToUi === 'function') {
        try { window.syncMapFiltersToUi(); } catch(e) { console.warn('syncMapFiltersToUi failed', e); }
    }
    // ✅ Mark map as open + persist `map=1` in URL so back navigation restores it
    window._fullscreenMapOpen = true;
    if (typeof persistMapFiltersToUrl === 'function') persistMapFiltersToUrl();
    // Show reset button if any filters active from URL
    setTimeout(() => {
        updateMapFiltersBadge();
        updateFiltersCount();
        if (typeof displayMapActiveFilters === 'function') displayMapActiveFilters();
    }, 200);
    // ✅ If filters were inherited from URL, run the unified pipeline once the
    // map is ready so markers/cards/counter reflect them from the very first
    // paint (instead of waiting for user interaction or boundschange).
    if (typeof window._isFilterActive === 'function' && window._isFilterActive()) {
        var _retries = 0;
        var _kickoff = setInterval(function() {
            _retries++;
            if (typeof window.updateMapWithFilters === 'function' && fullscreenMapInstance) {
                console.log('🚀 Initial filter pre-apply from URL (retries=' + _retries + ')');
                window.updateMapWithFilters();
                clearInterval(_kickoff);
            } else if (_retries > 30) {
                clearInterval(_kickoff);
            }
        }, 200);
    }

    // Load desktop filters if not mobile
    if (!isMobile) {
        setTimeout(() => {
            console.log('📋 Loading desktop filters...');
            loadMapDesktopDistricts();
            loadMapDevelopers();
        }, 50);
    }
    
    // Initialize map after modal is visible, store timeout to cancel if needed
    mapInitTimeout = setTimeout(() => {
        // Double-check modal is still open before initializing
        if (!modal.classList.contains('hidden')) {
            initFullscreenMap();
        }
        mapInitTimeout = null;
    }, 100);
}

// Group properties by coordinates
function groupPropertiesByCoords(properties) {
    const groups = {};
    
    properties.forEach(property => {
        // Check both formats: direct latitude/longitude and coordinates object
        const lat = property.latitude || (property.coordinates && property.coordinates.lat);
        const lng = property.longitude || (property.coordinates && property.coordinates.lng);
        
        if (lat && lng) {
            const key = `${lat.toFixed(5)}_${lng.toFixed(5)}`;
            if (!groups[key]) {
                groups[key] = {
                    lat: lat,
                    lng: lng,
                    properties: []
                };
            }
            // Ensure property has coordinates in expected format for marker creation
            if (!property.coordinates) {
                property.coordinates = { lat: lat, lng: lng };
            }
            groups[key].properties.push(property);
        }
    });
    
    return Object.values(groups);
}

// Format price for display
function formatPrice(price) {
    if (!price) return 'По запросу';
    return new Intl.NumberFormat('ru-RU').format(price) + ' ₽';
}

// Get completion status and color for marker - based on COMPLETION DATE and DEAL TYPE
function getPropertyStatusColor(properties) {
    const statuses = properties.map(p => {
        // Log first property for debugging
        if (properties.indexOf(p) === 0) {
            console.log('🟡 STATUS DEBUG:', {
                id: p.id,
                completion_date: p.completion_date,
                completion_year: p.completion_year,
                deal_type: p.deal_type,
                complex_building_status: p.complex_building_status,
                complex_building_end_build_year: p.complex_building_end_build_year
            });
        }
        
        // 1. Check deal_type first (presale = RED)
        if (p.deal_type) {
            const dealType = String(p.deal_type).toLowerCase();
            if (dealType === 'presale' || dealType === 'первичка') return 'Старт продаж';
        }
        
        // 2. Check completion_date (quarter like "4 кв. 2025")
        if (p.completion_date) {
            const dateStr = String(p.completion_date).toLowerCase();
            const now = new Date();
            const currentYear = now.getFullYear();
            
            // Parse quarter: "4 кв. 2025" -> year 2025
            const yearMatch = dateStr.match(/\d{4}/);
            if (yearMatch) {
                const complYear = parseInt(yearMatch[0]);
                if (complYear < currentYear) {
                    return 'Сдан'; // GREEN - already completed
                } else if (complYear === currentYear) {
                    return 'Строится'; // YELLOW - completing this year
                } else {
                    return 'Старт продаж'; // RED - future completion
                }
            }
        }
        
        // 3. Check completion_year
        if (p.completion_year) {
            const complYear = parseInt(p.completion_year);
            if (!isNaN(complYear)) {
                const now = new Date().getFullYear();
                if (complYear < now) return 'Сдан';
                if (complYear === now) return 'Строится';
                return 'Старт продаж';
            }
        }
        
        // 4. Check complex building status
        if (p.complex_building_status) {
            const status = String(p.complex_building_status).toLowerCase();
            if (status.includes('сдан')) return 'Сдан';
            if (status.includes('строит')) return 'Строится';
            if (status.includes('старт') || status.includes('presale')) return 'Старт продаж';
        }
        
        // 5. Check complex end year
        if (p.complex_building_end_build_year) {
            const year = parseInt(p.complex_building_end_build_year);
            if (!isNaN(year)) {
                const now = new Date().getFullYear();
                if (year < now) return 'Сдан';
                if (year === now) return 'Строится';
                return 'Старт продаж';
            }
        }
        
        // Default
        return 'Строится';
    });
    
    const hasDelivered = statuses.includes('Сдан');
    const hasUnderConstruction = statuses.includes('Строится');
    const hasPresale = statuses.includes('Старт продаж');
    
    // Priority: Delivered (green) > Under construction (yellow) > Presale (red)
    if (hasDelivered) return { color: '#22c55e', status: 'Сдан' }; // green
    if (hasUnderConstruction) return { color: '#eab308', status: 'Строится' }; // yellow
    if (hasPresale) return { color: '#ef4444', status: 'Старт продаж' }; // red
    return { color: '#eab308', status: 'Строится' }; // default yellow
}

// Create enhanced Yandex Maps marker with status colors and price
function createEnhancedYandexMarker(properties) {
    if (!properties || !properties.length || !properties[0].coordinates) {
        return null;
    }
    
    const count = properties.length;
    const lat = properties[0].coordinates.lat;
    const lng = properties[0].coordinates.lng;
    const minPrice = Math.min(...properties.map(p => p.price || Infinity).filter(p => p !== Infinity));
    const priceText = minPrice !== Infinity ? Math.round(minPrice / 1000000 * 10) / 10 + 'М' : '?';
    const statusInfo = getPropertyStatusColor(properties) || { color: '#0088CC', status: 'Строится' };
    
    // Create custom HTML marker with count, price, and status color
    const markerHTML = `
        <div style="
            background: ${statusInfo.color};
            color: white;
            padding: 6px 12px;
            border-radius: 20px;
            border: 2px solid white;
            font-size: 12px;
            font-weight: bold;
            white-space: nowrap;
            font-family: Inter, system-ui, sans-serif;
            display: inline-flex;
            align-items: center;
            gap: 6px;
            box-shadow: 0 3px 10px ${statusInfo.color}80;
        ">
            <span style="background: rgba(255,255,255,0.25); border-radius: 50%; min-width: 20px; height: 20px; display: inline-flex; align-items: center; justify-content: center; font-size: 11px; padding: 0 4px;">
                ${count}
            </span>
            <span>от ${priceText}₽</span>
        </div>
    `;
    
    // Use custom layout to render HTML
    const iconLayout = ymaps.templateLayoutFactory.createClass(markerHTML);
    
    // Create marker
    const marker = new ymaps.Placemark(
        [lat, lng],
        { hintContent: statusInfo.status },
        {
            iconLayout: iconLayout,
            iconShape: { type: 'Rectangle', coordinates: [[-80, -25], [80, 25]] },
            openBalloonOnClick: false
        }
    );
    
    // Store properties
    marker._markerProperties = properties;
    marker._originalIconLayout = iconLayout;  // 🎯 Save original for restore on hover leave
    marker.originalPreset = 'islands#' + (statusInfo.color === '#22c55e' ? 'greenCircleIcon' : statusInfo.color === '#eab308' ? 'yellowCircleIcon' : 'redCircleIcon');
    marker.statusColor = statusInfo.color;
    
    // ✅ ИСПРАВЛЕНИЕ #1: Регистрируем маркер для КАЖДОГО свойства (для hover sync)
    properties.forEach(prop => {
        if (!window.propertyIdToMarkerMap) window.propertyIdToMarkerMap = {};
        if (!window.propertyIdToMarkerMap[prop.id]) {
            window.propertyIdToMarkerMap[prop.id] = [];
        }
        window.propertyIdToMarkerMap[prop.id].push(marker);
    });
    console.log(`✅ Registered marker for ${properties.length} properties`);
    
    // Click handler
    marker.events.add('click', function() {
        if (isMobileDevice()) {
            openPropertyBottomSheet(properties);
        } else {
            updateDesktopPropertiesPanel(properties, properties[0].complex_name || 'Объект');
        }
    });
    
    return marker;
}

// ✅ NEW: Create marker from aggregated building-point data (CIAN-style)
// One marker per building coordinate; apartments are loaded on click.
function createAggregatedYandexMarker(point) {
    if (!point || point.lat == null || point.lng == null) return null;

    const count = point.count || 0;
    const minPrice = point.min_price;
    const priceText = minPrice ? (Math.round(minPrice / 1000000 * 10) / 10) + 'М' : '?';
    // Color by delivery status (matches legend: green=сдан, orange=строится, red=старт продаж/presale)
    const currentYear = new Date().getFullYear();
    let color;
    if (point.has_presale) {
        color = '#ef4444'; // красный — старт продаж
    } else if (point.end_build_year && point.end_build_year < currentYear) {
        color = '#22c55e'; // зелёный — сдан
    } else if (point.end_build_year && point.end_build_year <= currentYear + 1) {
        color = '#f97316'; // оранжевый — сдаётся в этом/следующем году
    } else {
        color = '#f59e0b'; // жёлтый — строится
    }

    const markerHTML = `
        <div style="
            background: ${color};
            color: white;
            padding: 6px 12px;
            border-radius: 20px;
            border: 2px solid white;
            font-size: 12px;
            font-weight: bold;
            white-space: nowrap;
            font-family: Inter, system-ui, sans-serif;
            display: inline-flex;
            align-items: center;
            gap: 6px;
            box-shadow: 0 3px 10px ${color}80;
        ">
            <span style="background: rgba(255,255,255,0.25); border-radius: 50%; min-width: 20px; height: 20px; display: inline-flex; align-items: center; justify-content: center; font-size: 11px; padding: 0 4px;">
                ${count}
            </span>
            <span>от ${priceText}₽</span>
        </div>
    `;

    const iconLayout = ymaps.templateLayoutFactory.createClass(markerHTML);
    const marker = new ymaps.Placemark(
        [point.lat, point.lng],
        { hintContent: point.complex_name || '' },
        {
            iconLayout: iconLayout,
            iconShape: { type: 'Rectangle', coordinates: [[-80, -25], [80, 25]] },
            openBalloonOnClick: false
        }
    );
    marker._pointData = point;

    // ── Hover popup card (desktop only, CIAN-style) ──────────────────
    if (!isMobileDevice()) {
        const _pt = point;
        const _ptImg = _pt.main_image || '/static/images/no-photo.svg';
        const _ptPrice = _pt.min_price
            ? 'от ' + (Math.round(_pt.min_price / 100000) / 10).toFixed(1) + ' млн ₽'
            : 'По запросу';
        const _ptName = _pt.complex_name || 'Жилой комплекс';
        const _ptBuilding = _pt.building_name ? ' — ' + _pt.building_name : '';
        const _ptCount = _pt.count || count;
        const _ptDate = _pt.end_build_year
            ? (_pt.end_build_quarter ? _pt.end_build_quarter + ' кв. ' + _pt.end_build_year : String(_pt.end_build_year))
            : '';
        const cSlug = window.CURRENT_CITY_SLUG || 'krasnodar';
        const _ptUrl = _pt.complex_slug ? `/${cSlug}/zk/${_pt.complex_slug}` : '#';

        const _proxyImg = (u) => {
            if (!u || u.startsWith('/')) return u || '/static/images/no-photo.svg';
            if (!window.imageProxyEnabled) return u;
            return `/api/image-proxy?url=${encodeURIComponent(u)}`;
        };

        marker.events.add('mouseenter', function(e) {
            clearTimeout(window._propHoverTimer);
            let tip = document.getElementById('ymap-prop-hover-tip');
            if (!tip) {
                tip = document.createElement('div');
                tip.id = 'ymap-prop-hover-tip';
                tip.style.cssText = 'position:fixed;z-index:99999;pointer-events:auto;transition:opacity 0.18s ease;display:none;opacity:0;';
                tip.addEventListener('mouseenter', () => clearTimeout(window._propHoverTimer));
                tip.addEventListener('mouseleave', () => {
                    window._propHoverTimer = setTimeout(() => {
                        const t = document.getElementById('ymap-prop-hover-tip');
                        if (t) { t.style.opacity = '0'; setTimeout(() => { if (t.style.opacity === '0') t.style.display = 'none'; }, 200); }
                    }, 200);
                });
                document.body.appendChild(tip);
            }
            tip.innerHTML = `
                <div style="width:316px;background:#fff;border-radius:12px;box-shadow:0 8px 32px rgba(0,0,0,0.18),0 2px 8px rgba(0,0,0,0.07);overflow:hidden;font-family:Inter,system-ui,sans-serif;border:1px solid rgba(0,0,0,0.06);">
                    <div style="display:flex;align-items:flex-start;padding:13px 13px 12px;gap:12px;">
                        <div style="flex:1;min-width:0;">
                            <div style="font-size:19px;font-weight:800;color:#111827;line-height:1.1;margin-bottom:5px;">${_ptPrice}</div>
                            <div style="font-size:12px;font-weight:600;color:#374151;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;margin-bottom:3px;">${_ptName}${_ptBuilding}</div>
                            <div style="font-size:11px;color:#6b7280;margin-bottom:2px;">${_ptCount} квартир в продаже</div>
                            ${_ptDate ? `<div style="font-size:11px;color:#9ca3af;">Сдача: ${_ptDate}</div>` : ''}
                        </div>
                        <div style="flex-shrink:0;width:84px;height:84px;border-radius:8px;overflow:hidden;background:#f3f4f6;">
                            <img src="${_proxyImg(_ptImg)}" style="width:100%;height:100%;object-fit:cover;" onerror="this.src='/static/images/no-photo.svg'">
                        </div>
                    </div>
                    <div style="display:flex;gap:7px;padding:0 13px 13px;">
                        <a href="tel:+78622666216" style="flex:1;background:#f3f4f6;color:#374151;text-align:center;padding:7px 4px;border-radius:7px;font-size:11px;font-weight:600;text-decoration:none;letter-spacing:0.1px;" onclick="event.stopPropagation();">Позвонить</a>
                        <a href="${_ptUrl}" style="flex:2;background:#0088CC;color:#fff;text-align:center;padding:7px 8px;border-radius:7px;font-size:11px;font-weight:600;text-decoration:none;letter-spacing:0.1px;">О ЖК</a>
                    </div>
                </div>`;
            tip.style.display = 'block';
            const domEvt = e.get('domEvent') && e.get('domEvent').originalEvent
                ? e.get('domEvent').originalEvent
                : (window._lastMouseEvt || null);
            if (domEvt) {
                const x = domEvt.clientX, y = domEvt.clientY;
                const tipW = 316, tipH = 200;
                const margin = 12;
                const left = (x + margin + tipW > window.innerWidth) ? x - tipW - margin : x + margin;
                const top  = (y - 16 + tipH > window.innerHeight) ? y - tipH + 16 : y - 16;
                tip.style.left = left + 'px';
                tip.style.top  = top + 'px';
            }
            requestAnimationFrame(() => { tip.style.opacity = '1'; });
        });
        marker.events.add('mouseleave', function() {
            clearTimeout(window._propHoverTimer);
            window._propHoverTimer = setTimeout(() => {
                const tip = document.getElementById('ymap-prop-hover-tip');
                if (tip) { tip.style.opacity = '0'; setTimeout(() => { if (tip.style.opacity === '0') tip.style.display = 'none'; }, 200); }
            }, 350);
        });
    }

    // Per-marker click debounce + AbortController to cancel concurrent at-point fetches
    let _markerAbortCtrl = null;
    let _markerLastClick = 0;

    marker.events.add('click', function() {
        // Debounce: ignore clicks within 400ms of previous (prevents rapid-click blue-screen)
        const now = Date.now();
        if (now - _markerLastClick < 400) return;
        _markerLastClick = now;

        // Abort any previous in-flight at-point fetch for this marker
        if (_markerAbortCtrl) {
            try { _markerAbortCtrl.abort(); } catch(e) {}
        }
        _markerAbortCtrl = new AbortController();
        const _signal = _markerAbortCtrl.signal;

        // Close any open balloon immediately on mobile (balloon opens automatically without this)
        if (isMobileDevice()) {
            try { marker.balloon.close(); } catch(e) {}
        }
        // 🛡️ Suppress viewport reload for 1.5s so boundschange from setCenter
        // doesn't re-render markers and destroy this marker + its balloon.
        window._suppressViewportLoad = Date.now() + 1500;

        // Pan to the clicked building point so it's centred on screen
        if (fullscreenMapInstance) {
            const currentZoom = fullscreenMapInstance.getZoom();
            fullscreenMapInstance.setCenter([point.lat, point.lng], Math.max(currentZoom, 15), { duration: 400, checkZoomRange: true });
        }

        // Lazy-load apartments at this exact building point.
        // Use the original (un-jittered) coords + complex_id + building_name
        // for exact match against the aggregated bucket.
        const urlFilters = new URLSearchParams(window.location.search);
        urlFilters.set('lat', point.orig_lat != null ? point.orig_lat : point.lat);
        urlFilters.set('lng', point.orig_lng != null ? point.orig_lng : point.lng);
        if (point.complex_id) urlFilters.set('complex_id', point.complex_id);
        if (point.building_name) {
            urlFilters.set('building_name', point.building_name);
        } else {
            urlFilters.set('building_name', '__none__');
        }
        // Don't send city_id — let bbox/coordinate matching work for any city (Sochi panning)
        urlFilters.delete('city_id');
        // Inject active map filters so bottom sheet respects current filter state
        // NOTE: injectMapFilters is scoped inside initFullscreenMap — inline here
        if (window.mapFilters) {
            const _mf = window.mapFilters;
            const _toRaw = v => { const n = parseFloat(v); return n > 0 ? (n < 1000 ? n * 1000000 : n) : null; };
            if (Array.isArray(_mf.rooms) && _mf.rooms.length > 0) {
                urlFilters.delete('rooms');
                _mf.rooms.forEach(r => urlFilters.append('rooms', r));
            }
            if (_mf.price_min) { const v = _toRaw(_mf.price_min); if (v) urlFilters.set('price_min', v); }
            if (_mf.price_max) { const v = _toRaw(_mf.price_max); if (v) urlFilters.set('price_max', v); }
            if (_mf.area_min) urlFilters.set('area_min', _mf.area_min);
            if (_mf.area_max) urlFilters.set('area_max', _mf.area_max);
            if (_mf.floor_min) urlFilters.set('floor_min', _mf.floor_min);
            if (_mf.floor_max) urlFilters.set('floor_max', _mf.floor_max);
            if (Array.isArray(_mf.completion) && _mf.completion.length > 0)
                urlFilters.set('completion', _mf.completion.join(','));
            if (Array.isArray(_mf.building_status) && _mf.building_status.length > 0)
                urlFilters.set('building_status', _mf.building_status.join(','));
            if (Array.isArray(_mf.object_classes) && _mf.object_classes.length > 0)
                urlFilters.set('object_classes', _mf.object_classes.join(','));
            // ✅ Developers filter — sync from list view
            if (Array.isArray(_mf.developers) && _mf.developers.length > 0) {
                urlFilters.delete('developer');
                urlFilters.delete('developers');
                _mf.developers.forEach(function(d){ urlFilters.append('developers', d); });
            }
            // ✅ Districts filter
            if (Array.isArray(_mf.districts) && _mf.districts.length > 0) {
                urlFilters.delete('districts');
                _mf.districts.forEach(function(d){ urlFilters.append('districts', d); });
            }
            // ✅ Renovation, features, floor_options, building_released
            ['renovation','features','floor_options','building_released'].forEach(function(fk){
                if (Array.isArray(_mf[fk]) && _mf[fk].length > 0)
                    urlFilters.set(fk, _mf[fk].join(','));
            });
        }

        fetch(`/api/map-properties/at-point?${urlFilters.toString()}`, { credentials: 'same-origin', signal: _signal })
            .then(r => r.json())
            .then(data => {
                if (!data.success || !data.properties || data.properties.length === 0) {
                    console.warn('⚠️ No apartments at point', point);
                    return;
                }
                // Show balloon with photo card ON the map (desktop only)
                // Suppress only 1.5s so map panning updates sidebar promptly after
                window._suppressViewportLoad = Date.now() + 1500;
                if (!isMobileDevice()) {
                    try {
                        const balloonHTML = createYandexBalloonContent(data.properties);
                        marker.properties.set('balloonContent', balloonHTML);
                        marker.balloon.open();
                    } catch(e) { console.warn('⚠️ Balloon open error:', e); }
                }

                if (isMobileDevice()) {
                    openPropertyBottomSheet(data.properties);
                } else {
                    const total = data.total || data.properties.length;
                    const panelTitle = point.building_name
                        ? (point.complex_name || 'Объект') + ' — ' + point.building_name
                        : (point.complex_name || 'Объект');
                    updateDesktopPropertiesPanel(data.properties, panelTitle, total);
                }
            })
            .catch(err => {
                if (err && err.name === 'AbortError') return; // cancelled by next click — ignore
                console.error('❌ at-point fetch error:', err);
            });
    });

    return marker;
}

// Create balloon content for Yandex Maps (Desktop only - no onerror to avoid warnings)
function createYandexBalloonContent(properties) {
    if (properties.length === 1) {
        const property = properties[0];
        const price = formatPrice(property.price);
        const rooms = property.rooms !== undefined && property.rooms !== null ? property.rooms : '?';
        const area = property.area || '?';
        const complex = property.residential_complex || property.complex_name || 'Жилой комплекс';
        let image = '/static/images/no-photo.svg';
        if (property.main_image && property.main_image !== '/static/images/no-photo.svg') {
            image = property.main_image;
        } else if (property.gallery_images) {
            try {
                const imgs = Array.isArray(property.gallery_images) ? property.gallery_images : JSON.parse(property.gallery_images);
                if (imgs.length > 1) image = imgs[1];
                else if (imgs.length > 0) image = imgs[0];
            } catch(e) {}
        } else if (property.image) {
            image = property.image;
        }
        const cashback = property.cashback_rate || 0;
        
        return `
            <div style="min-width: 280px; max-width: 320px; font-family: Inter, sans-serif;">
                <div style="position: relative; height: 120px; overflow: hidden; border-radius: 8px 8px 0 0;">
                    <img src="${image}" style="width: 100%; height: 100%; object-fit: cover;" alt="${complex}">
                    ${cashback > 0 ? `<div style="position: absolute; top: 8px; right: 8px; background: linear-gradient(135deg, #FFB800, #FF8C00); color: white; padding: 4px 12px; border-radius: 12px; font-size: 11px; font-weight: bold; box-shadow: 0 2px 8px rgba(255,184,0,0.4);">Кешбек ${cashback}%</div>` : ''}
                </div>
                <div style="padding: 12px;">
                    <div style="font-weight: bold; font-size: 18px; color: #0088CC; margin-bottom: 8px;">${price}</div>
                    <div style="font-size: 13px; color: #64748b; margin-bottom: 4px;">${rooms === 0 ? 'Студия' : rooms + '-комн.'}, ${area} м²</div>
                    <div style="font-size: 12px; color: #94a3b8; margin-bottom: 12px;">${complex}</div>
                    <a href="${property.url || '/object/' + property.id}" style="display: block; background: linear-gradient(135deg, #0088CC, #006699); color: white; text-align: center; padding: 10px; border-radius: 6px; text-decoration: none; font-weight: 500; font-size: 13px;">Подробнее</a>
                </div>
            </div>
        `;
    } else {
        const complex = properties[0].residential_complex || properties[0].complex_name || 'Жилой комплекс';
        const image = properties[0].main_image || properties[0].image || '/static/images/no-photo.svg';
        const minPrice = Math.min(...properties.map(p => p.price || Infinity).filter(p => p !== Infinity));
        const maxPrice = Math.max(...properties.map(p => p.price || 0));
        const priceRange = minPrice !== Infinity ? formatPrice(minPrice) : 'По запросу';
        
        // Create scrollable property list
        let propertyList = '';
        properties.slice(0, 10).forEach(prop => {
            const price = formatPrice(prop.price);
            const rooms = (prop.rooms !== undefined && prop.rooms !== null) ? prop.rooms : '?';
            const area = prop.area || '?';
            
            // Floor info
            const floor = prop.floor || null;
            const totalFloors = prop.total_floors || null;
            let floorText = '? этаж';
            if (floor && totalFloors) {
                floorText = `${floor}/${totalFloors} эт.`;
            } else if (floor) {
                floorText = `${floor} эт.`;
            }
            
            propertyList += `
                <div style="padding: 8px; border-bottom: 1px solid #e2e8f0; display: flex; justify-content: space-between; align-items: center;">
                    <div>
                        <div style="font-weight: 500; font-size: 12px; color: #1e293b;">${rooms === 0 ? 'Студия' : rooms + '-комн.'}, ${area} м²</div>
                        <div style="font-size: 11px; color: #64748b;">${floorText}</div>
                    </div>
                    <div>
                        <div style="font-weight: bold; color: #0088CC; font-size: 12px;">${price}</div>
                        <a href="${prop.url || '/object/' + prop.id}" style="font-size: 10px; color: #0088CC; text-decoration: none;">Подробнее →</a>
                    </div>
                </div>
            `;
        });
        
        return `
            <div style="min-width: 300px; max-width: 350px; font-family: Inter, sans-serif;">
                <div style="position: relative; height: 120px; overflow: hidden;">
                    <img src="${image}" style="width: 100%; height: 100%; object-fit: cover;" alt="${complex}">
                    <div style="position: absolute; top: 8px; right: 8px; background: linear-gradient(135deg, #FFB800, #FF8C00); color: white; padding: 4px 12px; border-radius: 12px; font-size: 11px; font-weight: bold; box-shadow: 0 2px 8px rgba(255,184,0,0.4);">${properties.length} квартир</div>
                    <div style="position: absolute; bottom: 0; left: 0; right: 0; background: linear-gradient(to top, rgba(0,0,0,0.6), transparent); height: 50px;"></div>
                    <h3 style="position: absolute; bottom: 8px; left: 8px; color: white; font-weight: bold; font-size: 14px; margin: 0; text-shadow: 0 2px 4px rgba(0,0,0,0.3);">${complex}</h3>
                </div>
                <div style="padding: 12px;">
                    <div style="font-weight: bold; font-size: 18px; color: #0088CC; margin-bottom: 8px;">от ${priceRange}</div>
                    <div style="font-size: 12px; color: #64748b; margin-bottom: 12px;">Разные планировки и этажи</div>
                    <div style="max-height: 250px; overflow-y: auto; border: 1px solid #e2e8f0; border-radius: 6px; margin-bottom: 12px;">
                        ${propertyList}
                    </div>
                    ${properties.length > 10 ? `<div style="text-align: center; font-size: 11px; color: #64748b;">Показано 10 из ${properties.length} квартир</div>` : ''}
                </div>
            </div>
        `;
    }
}

// Sync map filters to URL params before closing
function syncMapFiltersToUrl() {
    const params = new URLSearchParams();
    let hasFilters = false;
    
    console.log('🔍 Syncing ALL map filters to URL:', window.mapFilters);
    
    if (window.mapFilters) {
        // ✅ QUICK FILTERS
        // Rooms
        if (Array.isArray(window.mapFilters.rooms) && window.mapFilters.rooms.length > 0) {
            params.set('rooms', window.mapFilters.rooms.join(','));
            hasFilters = true;
            console.log('✅ Added rooms:', window.mapFilters.rooms);
        }
        
        // ✅ PRICE RANGE (convert from millions to rubles)
        if (window.mapFilters.price_min && window.mapFilters.price_min !== '' && window.mapFilters.price_min !== 0) {
            const priceMinVal = parseFloat(window.mapFilters.price_min);
            // Convert millions to rubles if value is small (< 1000)
            const priceMinRubles = priceMinVal < 1000 ? priceMinVal * 1000000 : priceMinVal;
            params.set('price_min', priceMinRubles);
            hasFilters = true;
            console.log('✅ Added price_min:', priceMinRubles, '(input:', window.mapFilters.price_min, 'млн)');
        }
        if (window.mapFilters.price_max && window.mapFilters.price_max !== '' && window.mapFilters.price_max !== 0) {
            const priceMaxVal = parseFloat(window.mapFilters.price_max);
            // Convert millions to rubles if value is small (< 1000)
            const priceMaxRubles = priceMaxVal < 1000 ? priceMaxVal * 1000000 : priceMaxVal;
            params.set('price_max', priceMaxRubles);
            hasFilters = true;
            console.log('✅ Added price_max:', priceMaxRubles, '(input:', window.mapFilters.price_max, 'млн)');
        }
        
        // ✅ PRICE PER SQM RANGE (тыс. руб/м²)
        if (window.mapFilters.price_sqm_min && window.mapFilters.price_sqm_min !== '' && window.mapFilters.price_sqm_min !== 0) {
            params.set('price_sqm_min', parseFloat(window.mapFilters.price_sqm_min) * 1000);
            hasFilters = true;
        }
        if (window.mapFilters.price_sqm_max && window.mapFilters.price_sqm_max !== '' && window.mapFilters.price_sqm_max !== 0) {
            params.set('price_sqm_max', parseFloat(window.mapFilters.price_sqm_max) * 1000);
            hasFilters = true;
        }
        
        // ✅ AREA RANGE
        if (window.mapFilters.area_min && window.mapFilters.area_min !== '') {
            params.set('area_min', window.mapFilters.area_min);
            hasFilters = true;
            console.log('✅ Added area_min:', window.mapFilters.area_min);
        }
        if (window.mapFilters.area_max && window.mapFilters.area_max !== '') {
            params.set('area_max', window.mapFilters.area_max);
            hasFilters = true;
            console.log('✅ Added area_max:', window.mapFilters.area_max);
        }
        
        // ✅ FLOOR RANGE
        if (window.mapFilters.floor_min && window.mapFilters.floor_min !== '') {
            params.set('floor_min', window.mapFilters.floor_min);
            hasFilters = true;
            console.log('✅ Added floor_min:', window.mapFilters.floor_min);
        }
        if (window.mapFilters.floor_max && window.mapFilters.floor_max !== '') {
            params.set('floor_max', window.mapFilters.floor_max);
            hasFilters = true;
            console.log('✅ Added floor_max:', window.mapFilters.floor_max);
        }
        
        // ✅ BUILDING FLOORS RANGE
        if (window.mapFilters.building_floors_min && window.mapFilters.building_floors_min !== '') {
            params.set('building_floors_min', window.mapFilters.building_floors_min);
            hasFilters = true;
            console.log('✅ Added building_floors_min:', window.mapFilters.building_floors_min);
        }
        if (window.mapFilters.building_floors_max && window.mapFilters.building_floors_max !== '') {
            params.set('building_floors_max', window.mapFilters.building_floors_max);
            hasFilters = true;
            console.log('✅ Added building_floors_max:', window.mapFilters.building_floors_max);
        }
        
        // ✅ BUILD YEAR RANGE
        if (window.mapFilters.build_year_min && window.mapFilters.build_year_min !== '') {
            params.set('build_year_min', window.mapFilters.build_year_min);
            hasFilters = true;
            console.log('✅ Added build_year_min:', window.mapFilters.build_year_min);
        }
        if (window.mapFilters.build_year_max && window.mapFilters.build_year_max !== '') {
            params.set('build_year_max', window.mapFilters.build_year_max);
            hasFilters = true;
            console.log('✅ Added build_year_max:', window.mapFilters.build_year_max);
        }
        
        // ✅ MULTI-SELECT FILTERS
        // Districts
        if (Array.isArray(window.mapFilters.districts) && window.mapFilters.districts.length > 0) {
            params.set('districts', window.mapFilters.districts.join(','));
            hasFilters = true;
            console.log('✅ Added districts:', window.mapFilters.districts);
        }
        
        // Developers
        if (Array.isArray(window.mapFilters.developers) && window.mapFilters.developers.length > 0) {
            params.set('developers', window.mapFilters.developers.join(','));
            hasFilters = true;
            console.log('✅ Added developers:', window.mapFilters.developers);
        }
        
        // Completion status
        if (Array.isArray(window.mapFilters.completion) && window.mapFilters.completion.length > 0) {
            params.set('completion', window.mapFilters.completion.join(','));
            hasFilters = true;
            console.log('✅ Added completion:', window.mapFilters.completion);
        }
        
        // Object classes
        if (Array.isArray(window.mapFilters.object_classes) && window.mapFilters.object_classes.length > 0) {
            params.set('object_classes', window.mapFilters.object_classes.join(','));
            hasFilters = true;
            console.log('✅ Added object_classes:', window.mapFilters.object_classes);
        }
        
        // Building status
        if (Array.isArray(window.mapFilters.building_status) && window.mapFilters.building_status.length > 0) {
            params.set('building_status', window.mapFilters.building_status.join(','));
            hasFilters = true;
            console.log('✅ Added building_status:', window.mapFilters.building_status);
        }
        
        // Features
        if (Array.isArray(window.mapFilters.features) && window.mapFilters.features.length > 0) {
            params.set('features', window.mapFilters.features.join(','));
            hasFilters = true;
            console.log('✅ Added features:', window.mapFilters.features);
        }
        
        // Building released
        if (Array.isArray(window.mapFilters.building_released) && window.mapFilters.building_released.length > 0) {
            params.set('building_released', window.mapFilters.building_released.join(','));
            hasFilters = true;
            console.log('✅ Added building_released:', window.mapFilters.building_released);
        }
        
        // Floor options
        if (Array.isArray(window.mapFilters.floor_options) && window.mapFilters.floor_options.length > 0) {
            params.set('floor_options', window.mapFilters.floor_options.join(','));
            hasFilters = true;
            console.log('✅ Added floor_options:', window.mapFilters.floor_options);
        }
        
        // Renovation
        if (Array.isArray(window.mapFilters.renovation) && window.mapFilters.renovation.length > 0) {
            params.set('renovation', window.mapFilters.renovation.join(','));
            hasFilters = true;
            console.log('✅ Added renovation:', window.mapFilters.renovation);
        }
    }
    
    // If we have filters, reload page with new params
    if (hasFilters && params.toString()) {
        const newUrl = `${window.location.pathname}?${params.toString()}`;
        console.log('✅ ALL map filters synced to URL, reloading page:', newUrl);
        // Reload page to apply filters via endpoints
        window.location.href = newUrl;
        return true;
    }
    
    console.log('ℹ️ No map filters to sync - mapFilters state:', window.mapFilters);
    return false;
}

// Export to window for external access
window.syncMapFiltersToUrl = syncMapFiltersToUrl;

// Close map and sync filters to URL (for "Список" button click)
window.closeMapAndSyncFilters = function() {
    console.log('🗺️ closeMapAndSyncFilters() called - syncing before close');

    // Ensure URL reflects the latest mapFilters state before we inspect it
    persistMapFiltersToUrl();

    // 🔄 Try to sync filters first (reads window.mapFilters, builds clean URL without map=1)
    const hadFilters = syncMapFiltersToUrl();

    // If no filters in mapFilters object, check if the URL already has filter params
    // (e.g. user came from list with ?rooms=2 and opened the map without changing anything)
    if (!hadFilters) {
        const urlParams = new URLSearchParams(window.location.search);
        const filterKeys = ['rooms','price_min','price_max','area_min','area_max',
            'floor_min','floor_max','completion','building_status','object_classes',
            'object_class','developers','developer','districts','search','cashback_only'];
        const hasUrlFilters = filterKeys.some(k => urlParams.has(k));
        if (hasUrlFilters) {
            // Strip map viewport params and reload list view with existing filter params
            urlParams.delete('map');
            urlParams.delete('map_center');
            urlParams.delete('map_zoom');
            urlParams.delete('page');
            const newUrl = urlParams.toString()
                ? `${window.location.pathname}?${urlParams.toString()}`
                : window.location.pathname;
            console.log('↩️ Preserving URL filters on list open:', newUrl);
            window.location.href = newUrl;
            return;
        }
        console.log('ℹ️ No filters to sync, closing normally');
        closeFullscreenMap();
    }
    // If filters were synced, page will reload via window.location.href
};

// Close fullscreen map modal
function closeFullscreenMap() {
    const modal = document.getElementById('fullscreenMapModal');
    if (!modal) return;
    
    console.log('🗺️ Closing fullscreen map modal');

    // ✅ Drop the `map=1` flag + saved viewport from URL so reload/back doesn't
    // reopen the modal and the viewport doesn't leak into the next session.
    window._fullscreenMapOpen = false;
    clearTimeout(window._mapViewportPersistTimer);
    try {
        const _u = new URL(window.location.href);
        let _changed = false;
        ['map', 'map_center', 'map_zoom'].forEach(function(k) {
            if (_u.searchParams.has(k)) { _u.searchParams.delete(k); _changed = true; }
        });
        if (_changed) window.history.replaceState(null, '', _u.toString());
    } catch (e) {}

    modal.classList.add('hidden');
    document.body.style.overflow = '';
    document.body.style.pointerEvents = '';
    
    const siteHeader = document.querySelector('header.sticky');
    if (siteHeader) {
        siteHeader.style.display = '';
        siteHeader.style.pointerEvents = '';
        siteHeader.style.zIndex = '';
    }
    const mobileNav = document.getElementById('mobileBottomNav');
    if (mobileNav) {
        mobileNav.style.display = '';
    }

    // Close bottom sheet if open — its backdrop would block taps after map closes
    const bottomSheet = document.getElementById('propertyBottomSheet');
    const bottomBackdrop = document.getElementById('bottomSheetBackdrop');
    if (bottomSheet) {
        bottomSheet.classList.add('hidden');
        bottomSheet.classList.remove('active');
    }
    if (bottomBackdrop) {
        bottomBackdrop.classList.add('hidden');
        bottomBackdrop.classList.remove('active');
    }

    // Show Chaport chat widget again
    document.body.classList.remove('fullscreen-map-open');
    const chaport = document.getElementById('chaport-container');
    if (chaport) chaport.style.setProperty('display', '', 'important');
    // Restore InBack chat FAB elements
    ['chatFab', 'chatFabRing', 'inbackChatPanel'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.style.removeProperty('display');
    });
    
    // Cancel pending map initialization to prevent race condition
    if (mapInitTimeout) {
        clearTimeout(mapInitTimeout);
        mapInitTimeout = null;
    }
    
    // Cancel ymaps retry timeout
    if (ymapsRetryTimeout) {
        clearTimeout(ymapsRetryTimeout);
        ymapsRetryTimeout = null;
    }
    
    // Destroy map instance to free memory
    if (fullscreenMapInstance) {
        fullscreenMapInstance.destroy();
        fullscreenMapInstance = null;
    }
}

// Initialize fullscreen map with properties for CURRENT CITY
function initFullscreenMap() {
    const modal = document.getElementById('fullscreenMapModal');
    const isMobile = window.innerWidth <= 1024;
    const mapContainerId = isMobile ? 'fullscreenMapContainer' : 'fullscreenMapContainerDesktop';
    const mapContainer = document.getElementById(mapContainerId);
    const currentCityId = window.currentCityId || 1;
    
    // Bail out if modal is closed or map already exists
    if (!modal || modal.classList.contains('hidden') || !mapContainer || fullscreenMapInstance) {
        console.log('🗺️ Skipping map init - modal closed or map exists');
        return;
    }
    
    if (typeof ymaps === 'undefined') {
        console.warn('ymaps not loaded yet, retrying in 500ms');
        ymapsRetryTimeout = setTimeout(initFullscreenMap, 500);
        return;
    }
    
    ymaps.ready(function() {
        try {
            console.log(`🗺️ Initializing fullscreen Yandex Map for city ${currentCityId} (${isMobile ? 'mobile' : 'desktop'})`);
            
            // 🎯 STEP 0: Get current city coordinates from GLOBAL variables (set in template)
            let cityCoordinates = window.cityCoordinates || [45.0355, 38.9753]; // Default Krasnodar
            let cityZoom = window.cityZoom || 12;

            // ✅ If URL carries map_center/map_zoom (back-nav from /object/<id>),
            // honor the user's last viewport instead of resetting to city default.
            let _restoredViewport = null;
            try {
                _restoredViewport = (typeof readMapViewportFromUrl === 'function') ? readMapViewportFromUrl() : null;
            } catch (e) { _restoredViewport = null; }
            if (_restoredViewport) {
                cityCoordinates = _restoredViewport.center;
                cityZoom = _restoredViewport.zoom;
                console.log(`🔁 Restoring map viewport from URL: [${cityCoordinates[0]}, ${cityCoordinates[1]}], zoom: ${cityZoom}`);
            } else {
                console.log(`✅ Using GLOBAL city coordinates: [${cityCoordinates[0]}, ${cityCoordinates[1]}], zoom: ${cityZoom}, city: ${window.currentCityName || 'Unknown'}`);
            }
            
            // Also try meta tags as fallback
            const cityLatMeta = document.querySelector('meta[name="city-lat"]');
            const cityLonMeta = document.querySelector('meta[name="city-lon"]');
            if (cityLatMeta && cityLonMeta) {
                const lat = parseFloat(cityLatMeta.getAttribute('content'));
                const lon = parseFloat(cityLonMeta.getAttribute('content'));
                if (!isNaN(lat) && !isNaN(lon)) {
                    console.log(`📋 Meta tags: [${lat}, ${lon}] (fallback)`);
                }
            }
            
            // Create map with controls, centered on current city
            window.fullscreenMapInstance = fullscreenMapInstance = new ymaps.Map(mapContainerId, {
                center: cityCoordinates,
                zoom: cityZoom,
                controls: ['zoomControl', 'geolocationControl']
            });
            
            // 🎨 Add click handler for drawing feature (Yandex Maps API 2.1)
            fullscreenMapInstance.events.add('click', function(e) {
                if (!isMapDrawing) return;
                
                try {
                    // Yandex Maps API 2.1: Use e.get('coords') to get [lat, lon]
                    let coords = e.get('coords');
                    
                    if (!coords || !Array.isArray(coords) || coords.length < 2) {
                        console.warn('⚠️ Could not get coordinates from event');
                        return;
                    }
                    
                    console.log(`🎨 ✅ CLICK at [${coords[0].toFixed(4)}, ${coords[1].toFixed(4)}]`);
                    
                    const clickPoint = coords;
                    
                    // Check if closing polygon (при клике рядом с первой точкой)
                    // Allow closing polygon with any number of points >= 3
                    if (drawingPoints.length >= 3) {
                        const firstPoint = drawingPoints[0];
                        // Distance in degrees: ~0.0005 degrees = ~50 meters
                        const dist = Math.sqrt(Math.pow(coords[0] - firstPoint[0], 2) + Math.pow(coords[1] - firstPoint[1], 2));
                        // 🎯 ИСПРАВЛЕНИЕ 1: Close polygon if clicking on 1st point OR within 50m
                        if (dist < 0.0005) { // ~50 meters for closing
                            console.log(`🎨 ✅ CLOSING POLYGON - distance: ${(dist * 111000).toFixed(0)} meters (clicked on/near first point)`);
                            finishMapDrawing();
                            return;
                        }
                        // 🎯 Also allow closing by clicking DIRECTLY on first point (pixel-level)
                        if (drawingPoints.length >= 3 && dist < 0.00001) { // Very close (< 1m)
                            console.log(`🎨 ✅ CLOSING POLYGON - clicked directly on first point!`);
                            finishMapDrawing();
                            return;
                        }
                    }
                    
                    drawingPoints.push(clickPoint);
                    console.log(`🎨 Point ${drawingPoints.length} added`);

                    // Update drawing hint text dynamically
                    (function() {
                        const hintText = document.getElementById('drawingHintText');
                        const hintStep = document.getElementById('drawingHintStep');
                        const n = drawingPoints.length;
                        if (hintText && hintStep) {
                            if (n === 1) {
                                hintStep.textContent = '2';
                                hintText.textContent = 'Продолжайте добавлять точки…';
                            } else if (n === 2) {
                                hintStep.textContent = '3';
                                hintText.textContent = 'Ещё одна точка — и можно замкнуть';
                            } else {
                                hintStep.style.background = '#22c55e';
                                hintStep.textContent = '✓';
                                hintText.innerHTML = 'Кликните на <b style="color:#4ade80">зелёную точку</b> чтобы завершить';
                            }
                        }
                    })();
                    
                    // Add marker
                    const marker = new ymaps.Placemark(clickPoint, {}, {
                        preset: drawingPoints.length === 1 ? 'islands#greenCircleDotIcon' : 'islands#orangeCircleDotIcon'
                    });
                    fullscreenMapInstance.geoObjects.add(marker);
                    drawingMarkers.push(marker);
                    
                    // 🎯 ИСПРАВЛЕНИЕ: Add click handler to first marker (green circle) to close polygon
                    if (drawingPoints.length === 1) {
                        marker.events.add('click', function(e) {
                            // Stop propagation so map click handler doesn't add another point
                            if (e && e.stopPropagation) {
                                e.stopPropagation();
                            }
                            console.log('🎯 GREEN MARKER CLICKED - closing polygon');
                            if (drawingPoints.length >= 3) {
                                console.log('✅ Closing polygon by clicking green marker');
                                finishMapDrawing();
                            } else {
                                console.warn('⚠️ Need at least 3 points, currently have:', drawingPoints.length);
                            }
                        });
                    }
                    
                    // Update polyline
                    if (drawingPolyline) {
                        fullscreenMapInstance.geoObjects.remove(drawingPolyline);
                    }
                    if (drawingPoints.length >= 2) {
                        drawingPolyline = new ymaps.Polyline(drawingPoints, {}, {
                            strokeColor: '#ff6b35',
                            strokeWidth: 3,
                            strokeOpacity: 0.8
                        });
                        fullscreenMapInstance.geoObjects.add(drawingPolyline);
                    }
                } catch (err) {
                    console.error('❌ Drawing error:', err?.message || err?.toString() || err);
                }
            });
            
            // 🎯 STEP 1: Load coordinates for current city only (with ALL URL filters)
            const urlParams = new URLSearchParams(window.location.search);
            const urlFilters = new URLSearchParams();
            urlFilters.set('city_id', currentCityId);
            
            function getUrlList(key) {
                const plain = urlParams.getAll(key);
                const bracket = urlParams.getAll(key + '[]');
                return plain.concat(bracket);
            }
            
            const developerFilter = urlParams.get('developer');
            if (developerFilter) urlFilters.set('developer', developerFilter);
            getUrlList('developers').forEach(d => urlFilters.append('developers', d));
            
            const districtFilter = urlParams.get('district');
            if (districtFilter) urlFilters.set('district', districtFilter);
            getUrlList('districts').forEach(d => urlFilters.append('districts', d));
            
            getUrlList('rooms').forEach(r => urlFilters.append('rooms', r));
            
            const priceMin = urlParams.get('price_min');
            const priceMax = urlParams.get('price_max');
            if (priceMin) {
                const val = parseFloat(priceMin);
                urlFilters.set('price_min', val < 1000 ? val * 1000000 : val);
            }
            if (priceMax) {
                const val = parseFloat(priceMax);
                urlFilters.set('price_max', val < 1000 ? val * 1000000 : val);
            }
            
            if (urlParams.get('area_min')) urlFilters.set('area_min', urlParams.get('area_min'));
            if (urlParams.get('area_max')) urlFilters.set('area_max', urlParams.get('area_max'));
            
            if (urlParams.get('floor_min')) urlFilters.set('floor_min', urlParams.get('floor_min'));
            if (urlParams.get('floor_max')) urlFilters.set('floor_max', urlParams.get('floor_max'));
            
            getUrlList('completion').forEach(c => urlFilters.append('completion', c));
            getUrlList('building_status').forEach(s => urlFilters.append('building_status', s));
            getUrlList('object_classes').forEach(c => urlFilters.append('object_classes', c));
            getUrlList('renovation').forEach(r => urlFilters.append('renovation', r));
            getUrlList('features').forEach(f => urlFilters.append('features', f));
            getUrlList('building_released').forEach(b => urlFilters.append('building_released', b));
            getUrlList('floor_options').forEach(f => urlFilters.append('floor_options', f));
            getUrlList('building_types').forEach(b => urlFilters.append('building_types', b));
            getUrlList('delivery_years').forEach(y => urlFilters.append('delivery_years', y));
            
            const ptFilter = urlParams.get('property_type');
            if (ptFilter && ptFilter !== 'all') urlFilters.set('property_type', ptFilter);
            
            const rcFilter = urlParams.get('residential_complex');
            if (rcFilter) urlFilters.set('residential_complex', rcFilter);
            
            const searchQuery = urlParams.get('search');
            if (searchQuery) urlFilters.set('search', searchQuery);
            
            // ✅ Singular 'developer' param (from hero search → map)
            const devParam = urlParams.get('developer');
            if (devParam) urlFilters.set('developer', devParam);
            
            if (urlParams.get('building_floors_min')) urlFilters.set('building_floors_min', urlParams.get('building_floors_min'));
            if (urlParams.get('building_floors_max')) urlFilters.set('building_floors_max', urlParams.get('building_floors_max'));
            
            const cashbackOnly = urlParams.get('cashback_only');
            if (cashbackOnly === 'true' || cashbackOnly === '1') urlFilters.set('cashback_only', 'true');
            
            console.log('🔍 Fullscreen map URL filters:', urlFilters.toString());
            
            if (typeof mapFilters !== 'undefined') {
                getUrlList('rooms').forEach(r => { const n = parseInt(r); if (!isNaN(n) && !mapFilters.rooms.includes(n)) mapFilters.rooms.push(n); });
                if (priceMin) { const _v = parseFloat(priceMin); mapFilters.price_min = _v >= 10000 ? String(_v / 1000000) : String(_v); }
                if (priceMax) { const _v = parseFloat(priceMax); mapFilters.price_max = _v >= 10000 ? String(_v / 1000000) : String(_v); }
                if (urlParams.get('area_min')) mapFilters.area_min = urlParams.get('area_min');
                if (urlParams.get('area_max')) mapFilters.area_max = urlParams.get('area_max');
                if (urlParams.get('floor_min')) mapFilters.floor_min = urlParams.get('floor_min');
                if (urlParams.get('floor_max')) mapFilters.floor_max = urlParams.get('floor_max');
                getUrlList('developers').forEach(d => { if (!mapFilters.developers.includes(d)) mapFilters.developers.push(d); });
                // ✅ Also sync singular 'developer' param → mapFilters.developers
                if (devParam && !mapFilters.developers.includes(devParam)) mapFilters.developers.push(devParam);
                getUrlList('completion').forEach(c => { if (!mapFilters.completion.includes(c)) mapFilters.completion.push(c); });
                getUrlList('object_classes').forEach(c => { if (!mapFilters.object_classes.includes(c)) mapFilters.object_classes.push(c); });
                getUrlList('building_status').forEach(s => { if (!mapFilters.building_status) mapFilters.building_status = []; if (!mapFilters.building_status.includes(s)) mapFilters.building_status.push(s); });
                getUrlList('renovation').forEach(r => { if (!mapFilters.renovation) mapFilters.renovation = []; if (!mapFilters.renovation.includes(r)) mapFilters.renovation.push(r); });
                getUrlList('features').forEach(f => { if (!mapFilters.features) mapFilters.features = []; if (!mapFilters.features.includes(f)) mapFilters.features.push(f); });
                getUrlList('building_released').forEach(b => { if (!mapFilters.building_released) mapFilters.building_released = []; if (!mapFilters.building_released.includes(b)) mapFilters.building_released.push(b); });
                getUrlList('floor_options').forEach(f => { if (!mapFilters.floor_options) mapFilters.floor_options = []; if (!mapFilters.floor_options.includes(f)) mapFilters.floor_options.push(f); });
                getUrlList('building_types').forEach(b => { if (!mapFilters.building_types) mapFilters.building_types = []; if (!mapFilters.building_types.includes(b)) mapFilters.building_types.push(b); });
                getUrlList('delivery_years').forEach(y => { if (!mapFilters.delivery_years) mapFilters.delivery_years = []; if (!mapFilters.delivery_years.includes(y)) mapFilters.delivery_years.push(y); });
                if (urlParams.get('building_floors_min')) mapFilters.building_floors_min = urlParams.get('building_floors_min');
                if (urlParams.get('building_floors_max')) mapFilters.building_floors_max = urlParams.get('building_floors_max');
                if (cashbackOnly === 'true' || cashbackOnly === '1') mapFilters.cashback_only = true;
                if (ptFilter && ptFilter !== 'all') mapFilters.property_type = ptFilter;
            }
            
            // ✅ NEW (CIAN-style): one fast request returning aggregated points (one per building)
            const renderAggregatedPoints = (points, label) => {
                if (!fullscreenMapInstance) {
                    console.warn('⚠️ renderAggregatedPoints: map instance gone (modal was closed), skipping');
                    return 0;
                }
                fullscreenMapInstance.geoObjects.removeAll();
                // Re-add active infra layers so they survive map reloads
                if (typeof infraLayers !== 'undefined') {
                    Object.keys(infraLayers).forEach(function(cat) {
                        try { if (infraLayers[cat]) fullscreenMapInstance.geoObjects.add(infraLayers[cat]); } catch(e) {}
                    });
                }

                const fsClusterLayout = ymaps.templateLayoutFactory.createClass(
                    '<div style="background:#0088CC;color:#fff;border-radius:50%;width:38px;height:38px;display:flex;align-items:center;justify-content:center;font-weight:800;font-size:13px;border:3px solid #fff;box-shadow:0 3px 10px rgba(0,136,204,0.5);">{{ properties.geoObjects.length }}</div>'
                );
                const clusterer = new ymaps.Clusterer({
                    clusterIconLayout: fsClusterLayout,
                    clusterIconShape: { type: 'Circle', coordinates: [19, 19], radius: 19 },
                    gridSize: 80,
                    groupByCoordinates: false,
                    clusterDisableClickZoom: true,
                });

                // Explicit cluster click → zoom in
                clusterer.events.add('click', function(e) {
                    try {
                        const target = e.get('target');
                        const coords = target.geometry.getCoordinates();
                        const currentZoom = fullscreenMapInstance.getZoom();
                        fullscreenMapInstance.setCenter(coords, currentZoom + 2, { duration: 400, checkZoomRange: true });
                    } catch (err) {
                        console.warn('Cluster click zoom error:', err);
                    }
                });

                const placemarks = [];
                let totalApts = 0;
                points.forEach(pt => {
                    try {
                        const m = createAggregatedYandexMarker(pt);
                        if (m) {
                            placemarks.push(m);
                            totalApts += pt.count || 0;
                        }
                    } catch (e) {
                        console.error('❌ Error creating aggregated marker:', e, pt);
                    }
                });
                clusterer.add(placemarks);
                fullscreenMapInstance.geoObjects.add(clusterer);

                // Update on-map counters — but DON'T overwrite the filtered total
                // written by updateMapWithFilters. When filters are active, the
                // authoritative count comes from /api/map-properties (server-side
                // ORM filter), not from clustering the visible viewport.
                // ⚠️ label === 'filtered' means THIS render IS the filtered call from
                // updateMapWithFilters which already wrote the authoritative totalCount
                // to the counters → MUST NOT overwrite with viewport apt-sum (totalApts).
                const _isFiltered = (typeof window._isFilterActive === 'function') && window._isFilterActive();
                const _hasFresh = typeof window._lastFilteredTotal === 'number'
                    && window._lastFilteredGen === window._mapFilterGen;
                const _skipOverwrite = (label === 'filtered') || (_isFiltered && _hasFresh);
                if (!_skipOverwrite) {
                    const counter = document.getElementById('mapObjectsCount');
                    const desktopCounter = document.getElementById('mapObjectsCountDesktop');
                    if (counter) counter.textContent = totalApts;
                    if (desktopCounter) desktopCounter.textContent = totalApts;
                }

                console.log(`✅ ${label}: ${placemarks.length} building points, ${totalApts} apartments (filtered=${_isFiltered}, hasFresh=${_hasFresh})`);
                window.mapAggregatedPoints = points;
                return placemarks.length;
            };

            // Expose for boundschange handler
            window.fullscreenRenderAggregated = renderAggregatedPoints;

            // Initial load (current city)
            // Snapshot gen so a filter click that arrives while the request is
            // in flight causes this stale response to be silently dropped.
            const _initAggGen = window._mapFilterGen || 0;
            fetch(`/api/map-properties/aggregated?${urlFilters.toString()}`, { credentials: 'same-origin' })
                .then(r => r.json())
                .then(data => {
                    if (!data.success || !data.points || data.points.length === 0) {
                        console.warn('⚠️ No aggregated map points for current city');
                        return;
                    }
                    // 🛡️ Drop stale initial response — user applied a filter
                    // while this fetch was in flight. Without this check the
                    // unfiltered 500+ markers overwrite the freshly-filtered set
                    // and the left panel gets wiped (renderAggregatedPoints calls
                    // geoObjects.removeAll() which destroys the filtered markers).
                    if ((window._mapFilterGen || 0) !== _initAggGen) {
                        console.log(`⏭️ initial agg fetch: stale (gen ${_initAggGen} → ${window._mapFilterGen}) — skip`);
                        return;
                    }
                    renderAggregatedPoints(data.points, `City ${currentCityId}`);
                    window.mapInitialAggregated = data.points;

                    // ✅ Auto-fit: if active search/district filter → zoom to markers
                    const _hasFilter = window.mapFilters && (
                        window.mapFilters.search ||
                        (window.mapFilters.districts && window.mapFilters.districts.length > 0)
                    );
                    // ✅ Skip auto-fit when user already chose a viewport (back-nav restore via URL)
                    const _urlViewport = (typeof readMapViewportFromUrl === 'function') ? readMapViewportFromUrl() : null;
                    if ((_hasFilter || data.points.length <= 30) && !_urlViewport) {
                        setTimeout(() => {
                            try {
                                const _b = fullscreenMapInstance.geoObjects.getBounds();
                                if (_b) {
                                    const _margin = isMobile ? [60, 60, 60, 60] : [60, 60, 60, 340];
                                    fullscreenMapInstance.setBounds(_b, { checkZoomRange: true, duration: 600, zoomMargin: _margin });
                                }
                            } catch(e) { console.warn('Auto-fit error:', e); }
                        }, 500);
                    } else if (_urlViewport) {
                        console.log('🔁 Initial load: skipping auto-fit — restored viewport from URL');
                    }

                    // Desktop side-panel: header + preview cards (loaded in parallel with markers)
                    if (!isMobile) {
                        const propsContainer = document.getElementById('mapDesktopPropertiesContainer');
                        if (propsContainer) {
                            // ✅ RACE GUARD: snapshot filter-gen at request time; if user
                            // applies/resets a filter while this initial fetch is in
                            // flight, gen will have advanced and we MUST NOT touch the
                            // container (otherwise we wipe the freshly-rendered filtered
                            // cards, which was the "cards disappear" bug).
                            const _initGen = window._mapFilterGen || 0;
                            propsContainer.innerHTML = '';
                            const totalApts = data.points.reduce((s, p) => s + (p.count || 0), 0);
                            propsContainer.style.display = 'grid';
                            propsContainer.style.gridTemplateColumns = '1fr 1fr';
                            propsContainer.style.gap = '12px';
                            // Update external panel header count
                            const panelCountEl = document.getElementById('mapDesktopPanelCount');
                            if (panelCountEl) panelCountEl.textContent = `${data.points.length} корпусов · ${totalApts} кв.`;

                            // Loading skeletons
                            for (let i = 0; i < 6; i++) {
                                const s = document.createElement('div');
                                s.className = 'animate-pulse bg-gray-100 rounded-lg h-56';
                                s.dataset.skeleton = '1';
                                propsContainer.appendChild(s);
                            }

                            // Fetch first page of apartments for preview cards
                            const cardParams = new URLSearchParams(urlFilters.toString());
                            cardParams.set('per_page', '20');
                            cardParams.set('page', '1');
                            fetch(`/api/map-properties?${cardParams.toString()}`, { credentials: 'same-origin' })
                                .then(r => r.json())
                                .then(d => {
                                    // ✅ STALE RACE CHECK: if a filter action ran after we
                                    // started, the panel now belongs to that filter — drop
                                    // this response entirely (no skeleton-remove, no count
                                    // overwrite, no card append).
                                    if ((window._mapFilterGen || 0) !== _initGen) {
                                        console.log(`⏭️ initial cards fetch: stale (gen ${_initGen} → ${window._mapFilterGen}) — skip render`);
                                        return;
                                    }
                                    propsContainer.querySelectorAll('[data-skeleton]').forEach(el => el.remove());
                                    if (!d.success || !d.properties) return;
                                    window.initialMapProperties = d.properties;
                                    const sorted = sortMapPropertiesArray(d.properties);
                                    sorted.forEach(p => {
                                        const card = createDesktopPropertyCard(p);
                                        propsContainer.appendChild(card);
                                    });
                                    currentDisplayOffset = d.properties.length;
                                    // Update panel count header
                                    const panelCount = document.getElementById('mapDesktopPanelCount');
                                    if (panelCount) panelCount.textContent = `${d.total || d.properties.length} объектов`;
                                    setTimeout(() => { initInfiniteScroll && initInfiniteScroll(); }, 100);
                                })
                                .catch(err => {
                                    if ((window._mapFilterGen || 0) !== _initGen) return;
                                    propsContainer.querySelectorAll('[data-skeleton]').forEach(el => el.remove());
                                    console.error('❌ Side panel cards fetch error:', err);
                                });
                        }
                    }

                    // Viewport-based loading: fetch markers for visible area (CIAN-style)
                    let viewportTimeout;
                    let isLoading = false;
                    let lastBoundsKey = null;

                    // Helper: inject active mapFilters into URLSearchParams for API calls
                    function injectMapFilters(p) {
                        // ✅ Clear stale mutable filter params from the URL snapshot
                        // before re-injecting from current mapFilters — otherwise
                        // dropping a filter still leaks the old value on pan/zoom.
                        ['search', 'districts', 'district', 'rooms', 'price_min', 'price_max',
                         'area_min', 'area_max', 'floor_min', 'floor_max',
                         'completion', 'building_status', 'object_classes', 'developers']
                            .forEach(k => p.delete(k));
                        if (window.mapFilters) {
                            if (Array.isArray(window.mapFilters.rooms) && window.mapFilters.rooms.length > 0) {
                                p.delete('rooms');
                                window.mapFilters.rooms.forEach(r => p.append('rooms', r));
                            }
                            if (window.mapFilters.price_min) {
                                const v = parseFloat(window.mapFilters.price_min);
                                if (v > 0) p.set('price_min', v < 1000 ? v * 1000000 : v);
                            }
                            if (window.mapFilters.price_max) {
                                const v = parseFloat(window.mapFilters.price_max);
                                if (v > 0) p.set('price_max', v < 1000 ? v * 1000000 : v);
                            }
                            if (window.mapFilters.area_min) p.set('area_min', window.mapFilters.area_min);
                            if (window.mapFilters.area_max) p.set('area_max', window.mapFilters.area_max);
                            if (window.mapFilters.floor_min) p.set('floor_min', window.mapFilters.floor_min);
                            if (window.mapFilters.floor_max) p.set('floor_max', window.mapFilters.floor_max);
                            if (Array.isArray(window.mapFilters.completion) && window.mapFilters.completion.length > 0)
                                p.set('completion', window.mapFilters.completion.join(','));
                            if (Array.isArray(window.mapFilters.building_status) && window.mapFilters.building_status.length > 0)
                                p.set('building_status', window.mapFilters.building_status.join(','));
                            if (Array.isArray(window.mapFilters.object_classes) && window.mapFilters.object_classes.length > 0)
                                p.set('object_classes', window.mapFilters.object_classes.join(','));
                            if (window.mapFilters.search) p.set('search', window.mapFilters.search);
                            if (Array.isArray(window.mapFilters.districts) && window.mapFilters.districts.length > 0)
                                window.mapFilters.districts.forEach(d => p.append('districts', d));
                        }
                    }

                    // Get a filter suffix for boundsKey cache invalidation when filters change
                    function getFilterSuffix() {
                        if (!window.mapFilters) return '';
                        const rooms = (window.mapFilters.rooms || []).join(',');
                        const pm = window.mapFilters.price_min || '';
                        const px = window.mapFilters.price_max || '';
                        const am = window.mapFilters.area_min || '';
                        const ax = window.mapFilters.area_max || '';
                        const fm = window.mapFilters.floor_min || '';
                        const fx = window.mapFilters.floor_max || '';
                        const cp = (window.mapFilters.completion || []).join(',');
                        const bs = (window.mapFilters.building_status || []).join(',');
                        const oc = (window.mapFilters.object_classes || []).join(',');
                        const sq = window.mapFilters.search || '';
                        const ds = (window.mapFilters.districts || []).join(',');
                        return `|r${rooms}|p${pm}-${px}|a${am}-${ax}|f${fm}-${fx}|c${cp}|s${bs}|o${oc}|q${sq}|d${ds}`;
                    }

                    function loadByViewport() {
                        if (isLoading || !fullscreenMapInstance) return;
                        // Don't reload while polygon filter is active — it would wipe results
                        if (window.polygonFilterActive) return;
                        // 🛡️ Don't reload right after updateMapWithFilters ran its auto-fit setBounds —
                        // otherwise this would clobber the freshly-rendered filtered markers/cards.
                        if (window._suppressViewportLoad && Date.now() < window._suppressViewportLoad) {
                            console.log('⏭️ loadByViewport: suppressed (filter just applied)');
                            return;
                        }
                        const z = fullscreenMapInstance.getZoom();
                        const bounds = fullscreenMapInstance.getBounds();
                        if (!bounds) return;

                        const [[latMin, lngMin], [latMax, lngMax]] = bounds;
                        const filterSuffix = getFilterSuffix();

                        // Zoom <= 6: show entire country overview without bbox limit
                        if (z <= 6) {
                            const boundsKey = 'all' + filterSuffix;
                            if (boundsKey === lastBoundsKey) return;
                            lastBoundsKey = boundsKey;
                            isLoading = true;
                            const p = new URLSearchParams(urlFilters.toString());
                            p.delete('city_id'); p.set('scope', 'all');
                            injectMapFilters(p);
                            fetch(`/api/map-properties/aggregated?${p.toString()}`, { credentials: 'same-origin' })
                                .then(r => r.json())
                                .then(d => { if (d.success && d.points) renderAggregatedPoints(d.points, 'ALL'); isLoading = false; })
                                .catch(() => { isLoading = false; });
                            return;
                        }

                        // Zoom > 6: load by viewport bbox (no city limit — user can pan to other cities)
                        const boundsKey = `${latMin.toFixed(3)},${lngMin.toFixed(3)},${latMax.toFixed(3)},${lngMax.toFixed(3)}` + filterSuffix;
                        if (boundsKey === lastBoundsKey) return;
                        lastBoundsKey = boundsKey;
                        isLoading = true;
                        const p = new URLSearchParams(urlFilters.toString());
                        p.delete('city_id'); // no city filter — let bbox do the scoping
                        p.set('lat_min', latMin.toFixed(5));
                        p.set('lat_max', latMax.toFixed(5));
                        p.set('lng_min', lngMin.toFixed(5));
                        p.set('lng_max', lngMax.toFixed(5));
                        injectMapFilters(p);
                        fetch(`/api/map-properties/aggregated?${p.toString()}`, { credentials: 'same-origin' })
                            .then(r => r.json())
                            .then(d => {
                                if (d.success && d.points) renderAggregatedPoints(d.points, 'viewport');
                                isLoading = false;
                                // ✅ Update desktop sidebar with cards visible in current viewport
                                // Always update on zoom/pan — reloadMapSidePanelByViewport handles dedup
                                if (!isMobile) {
                                    const cardP = new URLSearchParams(p.toString());
                                    cardP.set('per_page', '20');
                                    cardP.set('page', '1');
                                    // Inject sort if user selected one
                                    if (window.mapFilters && window.mapFilters.sort) {
                                        cardP.set('sort', window.mapFilters.sort);
                                    }
                                    fetch(`/api/map-properties?${cardP.toString()}`, { credentials: 'same-origin' })
                                        .then(r2 => r2.json())
                                        .then(d2 => {
                                            if (!d2.success || !d2.properties || d2.properties.length === 0) return;
                                            // Don't overwrite the panel if user has a specific cluster open
                                            if (window._mapClusterPanelSelected) return;
                                            const total = (d2.pagination && d2.pagination.total) || d2.properties.length;
                                            const panelCount = document.getElementById('mapDesktopPanelCount');
                                            if (panelCount) panelCount.textContent = `${total} объектов`;
                                            if (typeof updateDesktopPropertiesPanel === 'function') {
                                                updateDesktopPropertiesPanel(d2.properties, 'Объекты в области', total);
                                            }
                                        })
                                        .catch(() => {});
                                }
                            })
                            .catch(() => { isLoading = false; });
                    }

                    // Seed lastBoundsKey with the current viewport so the first boundschange
                    // (fired by Yandex Maps on init) doesn't trigger an immediate reload.
                    (function seedInitialBoundsKey() {
                        try {
                            const z = fullscreenMapInstance.getZoom();
                            const b = fullscreenMapInstance.getBounds();
                            if (!b) return;
                            if (z <= 6) {
                                lastBoundsKey = 'all';
                            } else {
                                const [[la, lo], [la2, lo2]] = b;
                                lastBoundsKey = `${la.toFixed(3)},${lo.toFixed(3)},${la2.toFixed(3)},${lo2.toFixed(3)}`;
                            }
                        } catch(e) {}
                    })();

                    fullscreenMapInstance.events.add('boundschange', function() {
                        clearTimeout(viewportTimeout);
                        viewportTimeout = setTimeout(loadByViewport, 700);
                        // ✅ Reload left side-panel cards to match current viewport
                        clearTimeout(window._sidePanelViewportTimer);
                        window._sidePanelViewportTimer = setTimeout(function() {
                            if (typeof window.reloadMapSidePanelByViewport === 'function') {
                                window.reloadMapSidePanelByViewport();
                            }
                        }, 600);
                        // ✅ Persist current center/zoom to URL (debounced) so that
                        // navigating to /object/<id> and pressing "back" restores
                        // the exact viewport instead of an auto-fit over filtered bounds.
                        clearTimeout(window._mapViewportPersistTimer);
                        window._mapViewportPersistTimer = setTimeout(function() {
                            try {
                                if (!fullscreenMapInstance) return;
                                const c = fullscreenMapInstance.getCenter();
                                const z = fullscreenMapInstance.getZoom();
                                if (typeof persistMapViewportToUrl === 'function') {
                                    persistMapViewportToUrl(c, z);
                                }
                            } catch (e) {}
                        }, 500);
                    });

                    // Note: don't override window.triggerMapReload here — the
                    // unified pipeline wrapper (templates/properties.html) routes
                    // all reloads through updateMapWithFilters, which keeps the
                    // side panel + bottom sheet + counters in sync.

                    setTimeout(() => { initMapViewportListener && initMapViewportListener(); }, 100);
                })
                .catch(err => console.error('❌ Aggregated map fetch error:', err));
            
            console.log('✅ Fullscreen Yandex Map initialized');
        } catch (error) {
            console.error('❌ Error initializing fullscreen map:', error);
        }
    });
}

// Open property bottom sheet (Mobile)
// ✅ Helper: keep the bottom sheet header counter in sync from anywhere
function _syncBottomSheetCount(total) {
    const bsCount = document.getElementById('bottomSheetCount');
    if (!bsCount) return;
    const n = (typeof total === 'number' && total >= 0) ? total : 0;
    if (n === 0)      bsCount.textContent = '0 объектов';
    else if (n === 1) bsCount.textContent = '1 объект';
    else              bsCount.textContent = `${n} объектов`;
}

function openPropertyBottomSheet(properties) {
    const bottomSheet = document.getElementById('propertyBottomSheet');
    const backdrop = document.getElementById('bottomSheetBackdrop');
    const container = document.getElementById('bottomSheetPropertiesContainer');
    const countEl = document.getElementById('bottomSheetCount');

    if (!bottomSheet || !backdrop || !container) {
        console.warn('⚠️ Bottom sheet elements not found');
        return;
    }

    console.log(`🗺️ Opening bottom sheet with ${properties.length} properties`);

    // Store all properties for filtering
    const allProperties = properties;
    let activeFilter = 'all';

    function updateCount(list) {
        if (!countEl) return;
        const n = list.length;
        if (n === 0)      countEl.textContent = '0 объектов';
        else if (n === 1) countEl.textContent = '1 объект';
        else              countEl.textContent = `${n} объектов`;
    }

    function renderProperties(list) {
        container.innerHTML = '';
        const BATCH = 20;
        let rendered = 0;
        const total = list.length;

        if (total === 0) {
            container.innerHTML = '<div style="text-align:center;padding:24px;color:#9ca3af;font-size:14px;">Нет квартир с выбранной комнатностью</div>';
            return;
        }

        function renderBatch() {
            const end = Math.min(rendered + BATCH, total);
            for (let i = rendered; i < end; i++) {
                try {
                    const card = createPropertyCard(list[i], i);
                    if (card) container.appendChild(card);
                } catch(e) {
                    console.error('❌ Card creation error', list[i] && list[i].id, e);
                }
            }
            rendered = end;

            const oldSentinel = container.querySelector('.bs-load-more');
            if (oldSentinel) oldSentinel.remove();

            if (rendered < total) {
                const sentinel = document.createElement('div');
                sentinel.className = 'bs-load-more py-2';
                container.appendChild(sentinel);
                const observer = new IntersectionObserver((entries) => {
                    if (entries[0].isIntersecting) {
                        observer.disconnect();
                        renderBatch();
                    }
                }, { root: container, threshold: 0.1 });
                observer.observe(sentinel);
            }
        }

        renderBatch();
        container.scrollTop = 0;
    }

    function applyFilter(roomsValue) {
        activeFilter = roomsValue;
        let filtered;
        if (roomsValue === 'all') {
            filtered = allProperties;
        } else if (roomsValue === '4+') {
            filtered = allProperties.filter(p => {
                const r = p.rooms !== undefined && p.rooms !== null ? parseInt(p.rooms) : (p.room_count !== undefined ? parseInt(p.room_count) : -1);
                return r >= 4;
            });
        } else {
            const target = parseInt(roomsValue);
            filtered = allProperties.filter(p => {
                const r = p.rooms !== undefined && p.rooms !== null ? parseInt(p.rooms) : (p.room_count !== undefined ? parseInt(p.room_count) : -1);
                return r === target;
            });
        }
        updateCount(filtered);
        renderProperties(filtered);
    }

    // Wire up filter chips — event delegation so closures always stay fresh
    const filtersEl = document.getElementById('bsRoomFilters');
    if (filtersEl) {
        // Reset active state via CSS class
        filtersEl.querySelectorAll('.bs-room-chip').forEach(b => b.classList.remove('active'));
        const allChip = filtersEl.querySelector('[data-rooms="all"]');
        if (allChip) allChip.classList.add('active');

        // Store current applyFilter on element — updated every open
        filtersEl._applyFilter = applyFilter;

        // Attach event delegation once (survives repeated opens)
        if (!filtersEl._bsChipHandler) {
            filtersEl._bsChipHandler = function(e) {
                const chip = e.target.closest('.bs-room-chip');
                if (!chip) return;
                filtersEl.querySelectorAll('.bs-room-chip').forEach(b => b.classList.remove('active'));
                chip.classList.add('active');
                if (filtersEl._applyFilter) filtersEl._applyFilter(chip.dataset.rooms);
            };
            filtersEl.addEventListener('click', filtersEl._bsChipHandler);
            // Explicit touchend for iOS/Android reliability
            filtersEl.addEventListener('touchend', function(e) {
                const chip = e.target.closest('.bs-room-chip');
                if (!chip) return;
                e.preventDefault();
                filtersEl._bsChipHandler(e);
            }, { passive: false });
        }
    }

    // Initial render
    updateCount(allProperties);
    renderProperties(allProperties);

    bottomSheet.classList.remove('fullscreen');
    const total = allProperties.length;
    const sheetH = total === 1 ? '40vh' : total <= 3 ? '45vh' : '65vh';
    bottomSheet.style.maxHeight = sheetH;
    container.style.maxHeight = `calc(${sheetH} - 100px)`;

    backdrop.classList.remove('hidden');
    bottomSheet.classList.remove('hidden');

    setTimeout(() => {
        backdrop.classList.add('active');
        bottomSheet.classList.add('active');
    }, 10);

    initBottomSheetDrag(bottomSheet, total);
}

function initBottomSheetDrag(bottomSheet, propertyCount) {
    const handle = document.getElementById('bottomSheetHandle');
    if (!handle) return;
    
    let startY = 0;
    let startMaxHeight = 0;
    let isDragging = false;
    
    function onStart(e) {
        isDragging = true;
        startY = e.touches ? e.touches[0].clientY : e.clientY;
        startMaxHeight = bottomSheet.offsetHeight;
        bottomSheet.style.transition = 'none';
        handle.style.cursor = 'grabbing';
    }
    
    function onMove(e) {
        if (!isDragging) return;
        e.preventDefault();
        const currentY = e.touches ? e.touches[0].clientY : e.clientY;
        const delta = startY - currentY;
        const windowH = window.innerHeight;
        const newHeight = Math.min(windowH, Math.max(150, startMaxHeight + delta));
        bottomSheet.style.maxHeight = newHeight + 'px';
        const container = document.getElementById('bottomSheetPropertiesContainer');
        if (container) container.style.maxHeight = (newHeight - 60) + 'px';
    }
    
    function onEnd() {
        if (!isDragging) return;
        isDragging = false;
        handle.style.cursor = '';
        bottomSheet.style.transition = '';
        
        const currentH = bottomSheet.offsetHeight;
        const windowH = window.innerHeight;
        const ratio = currentH / windowH;
        
        if (ratio > 0.7) {
            bottomSheet.classList.add('fullscreen');
            bottomSheet.style.maxHeight = '100vh';
            const container = document.getElementById('bottomSheetPropertiesContainer');
            if (container) container.style.maxHeight = 'calc(100vh - 60px)';
        } else if (ratio < 0.25) {
            closePropertyBottomSheet();
        } else {
            const snapH = propertyCount === 1 ? '35vh' : '50vh';
            const snapContH = propertyCount === 1 ? 'calc(35vh - 60px)' : 'calc(50vh - 60px)';
            bottomSheet.classList.remove('fullscreen');
            bottomSheet.style.maxHeight = snapH;
            const container = document.getElementById('bottomSheetPropertiesContainer');
            if (container) container.style.maxHeight = snapContH;
        }
    }
    
    handle.removeEventListener('touchstart', handle._onStart);
    handle.removeEventListener('mousedown', handle._onStart);
    
    handle._onStart = onStart;
    handle.addEventListener('touchstart', onStart, {passive: true});
    handle.addEventListener('mousedown', onStart);
    document.addEventListener('touchmove', onMove, {passive: false});
    document.addEventListener('mousemove', onMove);
    document.addEventListener('touchend', onEnd);
    document.addEventListener('mouseup', onEnd);
}

function closePropertyBottomSheet() {
    const bottomSheet = document.getElementById('propertyBottomSheet');
    const backdrop = document.getElementById('bottomSheetBackdrop');
    
    if (!bottomSheet || !backdrop) return;
    
    backdrop.classList.remove('active');
    bottomSheet.classList.remove('active');
    bottomSheet.classList.remove('fullscreen');
    
    setTimeout(() => {
        backdrop.classList.add('hidden');
        bottomSheet.classList.add('hidden');
        bottomSheet.style.maxHeight = '';
    }, 300);
}

function createPropertyCard(property, index) {
    const card = document.createElement('div');
    card.style.cssText = 'background:#fff;border-radius:14px;border:1px solid #f0f0f0;margin-bottom:8px;box-shadow:0 1px 4px rgba(0,0,0,0.07);display:block;width:100%;flex-shrink:0;min-height:96px;';

    const price = formatPrice(property.price);
    const rooms = property.rooms !== undefined && property.rooms !== null ? property.rooms : (property.room_count !== undefined && property.room_count !== null ? property.room_count : null);
    const area = property.area || property.total_area || '?';
    const complex = property.residential_complex || property.complex_name || '';
    const propertyUrl = property.url || (window.CURRENT_CITY_SLUG ? `/${window.CURRENT_CITY_SLUG}/object/${property.id}` : `/object/${property.id}`);

    // Pick best image: own image first, then gallery, then complex image
    let image = '/static/images/no-photo.svg';
    if (property.main_image && property.main_image !== '/static/images/no-photo.svg') {
        image = property.main_image;
    } else if (property.gallery_images) {
        try {
            const imgs = Array.isArray(property.gallery_images) ? property.gallery_images : JSON.parse(property.gallery_images);
            if (imgs && imgs.length > 0) image = imgs[0];
        } catch(e) {}
    } else if (property.complex_main_image) {
        image = property.complex_main_image;
    } else if (property.image) {
        image = property.image;
    }

    let roomsText = '?-комн.';
    if (rooms === 0 || rooms === '0') {
        roomsText = 'Студия';
    } else if (rooms !== null && rooms !== '?' && rooms !== '') {
        roomsText = rooms + '-комн.';
    }

    // Renovation badge
    const renovationMap = {
        'fine_finish': 'Чистовая', 'чистовая': 'Чистовая', 'чистов': 'Чистовая',
        'rough_finish': 'Черновая', 'черновая': 'Черновая', 'чернов': 'Черновая',
        'turnkey': 'Под ключ', 'ключ': 'Под ключ',
        'pre_finish': 'Предчистовая', 'предчистовая': 'Предчистовая',
        'no_renovation': 'Без отделки', 'без': 'Без отделки'
    };
    const rawReno = (property.renovation_type || '').toLowerCase();
    let renoLabel = '';
    if (rawReno) {
        for (const [key, label] of Object.entries(renovationMap)) {
            if (rawReno.includes(key)) { renoLabel = label; break; }
        }
        if (!renoLabel && property.renovation_type && property.renovation_type.toLowerCase() !== 'none') renoLabel = property.renovation_type;
    }

    const cashbackHtml = property.cashback
        ? `<div style="font-size:11px;color:#16a34a;font-weight:600;margin-top:2px;">Кэшбек до ${Number(property.cashback).toLocaleString('ru-RU')} ₽</div>`
        : '';

    const floorText = property.floor
        ? ` · ${property.floor}${property.total_floors ? '/' + property.total_floors : ''} эт.`
        : '';

    const renoHtml = renoLabel
        ? `<div style="font-size:10px;color:#6b7280;margin-top:2px;">${renoLabel}</div>`
        : '';

    card.innerHTML = `
        <a href="${propertyUrl}" style="display:flex;flex-direction:row;text-decoration:none;color:inherit;align-items:stretch;min-height:88px;">
            <div style="position:relative;width:96px;min-width:96px;height:96px;overflow:hidden;flex-shrink:0;background:#f3f4f6;">
                <img src="${image}" alt="${complex}" referrerpolicy="no-referrer"
                    style="width:100%;height:100%;object-fit:cover;display:block;"
                    onerror="this.src='/static/images/no-photo.svg'">
                ${renoLabel ? `<div style="position:absolute;top:5px;left:5px;background:rgba(0,0,0,0.55);color:#fff;font-size:10px;padding:2px 6px;border-radius:5px;font-weight:500;">${renoLabel}</div>` : ''}
            </div>
            <div style="flex:1;padding:10px 12px;display:flex;flex-direction:column;justify-content:center;min-width:0;overflow:hidden;">
                <div style="font-size:16px;font-weight:700;color:#111827;line-height:1.2;">${price}</div>
                ${cashbackHtml}
                <div style="font-size:12px;color:#374151;margin-top:4px;font-weight:500;">${roomsText}, ${area} м²${floorText}</div>
                ${complex ? `<div style="font-size:11px;color:#6b7280;margin-top:3px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">${complex}</div>` : ''}
            </div>
            <div style="display:flex;align-items:center;padding-right:10px;flex-shrink:0;">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#9ca3af" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="9 18 15 12 9 6"/></svg>
            </div>
        </a>
    `;
    
    return card;
}

// Global map for property ID to marker placemark
window.propertyIdToMarker = {};

// Create desktop property card for 2-column modal (beautiful like /map page)
function createDesktopPropertyCard(property) {
    const card = document.createElement('div');
    card.className = 'bg-white rounded-xl shadow-md transition-all duration-300 border border-gray-200 cursor-pointer flex flex-col';
    card.setAttribute('data-property-card-id', property.id);
    card.setAttribute('data-property-id', property.id);
    
    // Add hover to highlight marker on map + VISUAL FEEDBACK
    card.addEventListener('mouseenter', () => {
        // 🎨 VISUAL FEEDBACK: Highlight the card itself
        card.style.backgroundColor = '#f0f9ff';  // Light blue background
        card.style.borderColor = '#0088CC';      // Brand blue border
        card.style.borderWidth = '2px';
        card.style.boxShadow = '0 10px 25px -5px rgba(0, 136, 204, 0.2)';
        
        // 🎯 Highlight marker on map using propertyIdToMarkerMap
        // 🎨 КРАСИВЫЙ ЭФФЕКТ: Показываем красивую карточку с фотографией на маркере
        if (window.propertyIdToMarkerMap && window.propertyIdToMarkerMap[property.id]) {
            const markers = window.propertyIdToMarkerMap[property.id];
            console.log(`🎯 Card hover: Found ${markers.length} marker(s) for property ${property.id}`);
            markers.forEach((marker, idx) => {
                if (marker.geometry) {
                    const rooms = property.rooms !== undefined && property.rooms !== null ? property.rooms : '?';
                    const price = formatPrice(property.price);
                    
                    // Получить изображение безопасно
                    let image = '/static/images/no-photo.svg';
                    if (property.main_image && property.main_image !== '/static/images/no-photo.svg') {
                        image = property.main_image;
                    } else if (property.gallery_images) {
                        try {
                            const imgs = Array.isArray(property.gallery_images) ? property.gallery_images : JSON.parse(property.gallery_images);
                            if (imgs.length > 1) image = imgs[1];  // 2-е фото (1-е всегда планировка)
                            else if (imgs.length > 0) image = imgs[0];
                        } catch(e) {}
                    }
                    
                    // 🎨 Создаем красивую карточку с фотографией
                    const hoverCardHTML = `
                        <div style="
                            background: white;
                            border-radius: 8px;
                            overflow: hidden;
                            box-shadow: 0 8px 16px rgba(0,0,0,0.2);
                            width: 160px;
                            font-family: Inter, sans-serif;
                            border: 2px solid #0088CC;
                        ">
                            <div style="position: relative; height: 80px; overflow: hidden;">
                                <img src="${image}" style="width: 100%; height: 100%; object-fit: cover;" alt="property">
                            </div>
                            <div style="padding: 8px 10px;">
                                <div style="font-weight: bold; font-size: 14px; color: #0088CC; margin-bottom: 2px;">${price}</div>
                                <div style="font-size: 12px; color: #64748b;">${rooms === 0 ? 'Студия' : rooms + '-комн.'}</div>
                            </div>
                        </div>
                    `;
                    
                    // Меняем iconLayout на карточку
                    const hoverLayout = ymaps.templateLayoutFactory.createClass(hoverCardHTML);
                    marker.options.set('iconLayout', hoverLayout);
                    
                    // Сохраняем информацию что это highlighted
                    marker._isHighlighted = true;
                    
                    console.log(`🎯 Marker ${idx + 1} highlighted (BEAUTIFUL PHOTO CARD ✨)`);
                }
            });
        } else {
            console.warn(`⚠️ No marker found for property ${property.id}`);
        }
    });
    
    card.addEventListener('mouseleave', () => {
        // 🎨 RESET: Remove highlight from card
        card.style.backgroundColor = '';
        card.style.borderColor = '';
        card.style.borderWidth = '';
        card.style.boxShadow = '';
        
        // 🎯 Reset marker highlight using propertyIdToMarkerMap
        if (window.propertyIdToMarkerMap && window.propertyIdToMarkerMap[property.id]) {
            const markers = window.propertyIdToMarkerMap[property.id];
            markers.forEach(marker => {
                // 🎨 Восстанавливаем оригинальный layout
                if (marker._originalIconLayout) {
                    marker.options.set('iconLayout', marker._originalIconLayout);
                    marker._isHighlighted = false;
                    console.log(`🎯 Marker reset to original layout`);
                }
            });
        }
    });
    
    // Price
    const price = formatPrice(property.price);
    
    // Rooms handling
    const rooms = property.rooms !== undefined && property.rooms !== null ? property.rooms : (property.room_count !== undefined && property.room_count !== null ? property.room_count : null);
    let roomText = '?-комн.';
    if (rooms === 0 || rooms === '0') {
        roomText = 'Студия';
    } else if (rooms !== null && rooms !== '?' && rooms !== '') {
        roomText = rooms + ' комнаты';
    }
    
    // Area
    const area = property.area || property.total_area || '?';
    
    // Floor info
    const apartmentFloor = property.floor || 0;
    const buildingFloors = property.total_floors || 0;
    let floorText = '';
    if (apartmentFloor > 0 && buildingFloors > 0) {
        floorText = `${apartmentFloor}/${buildingFloors} эт.`;
    } else if (apartmentFloor > 0) {
        floorText = `${apartmentFloor} эт.`;
    }
    
    // Developer
    const developer = property.developer_name || property.developer || '';
    
    // Parse gallery images
    let firstImage = '/static/images/no-photo.svg';
    let imageCount = 0;
    let allImages = [];
    
    if (property.gallery_images || property.gallery) {
        const galleryData = property.gallery_images || property.gallery;
        try {
            if (Array.isArray(galleryData)) {
                allImages = galleryData;
            } else {
                allImages = JSON.parse(galleryData);
            }
            if (allImages.length > 0) {
                allImages = allImages.map(_proxyImg);
                firstImage = allImages[0];
                imageCount = allImages.length;
            }
        } catch(e) {
            allImages = [_proxyImg(galleryData)];
            firstImage = allImages[0];
            imageCount = 1;
        }
    }
    
    if (imageCount === 0 && property.main_image && property.main_image !== '/static/images/no-photo.svg') {
        try {
            const images = JSON.parse(property.main_image);
            if (Array.isArray(images) && images.length > 0) {
                allImages = images.map(_proxyImg);
                firstImage = allImages[0];
                imageCount = allImages.length;
            }
        } catch(e) {
            allImages = [_proxyImg(property.main_image)];
            firstImage = allImages[0];
            imageCount = 1;
        }
    }
    
    if (imageCount === 0 && property.image) {
        allImages = [_proxyImg(property.image)];
        firstImage = allImages[0];
        imageCount = 1;
    }
    
    // Cashback - use direct amount from API or calculate from rate
    const cashbackRate = property.cashback_rate || 0;
    const cashbackAmount = property.cashback || (property.price && cashbackRate > 0 ? Math.round(property.price * cashbackRate / 100) : 0);
    const cashbackFormatted = cashbackAmount > 0 ? cashbackAmount.toLocaleString('ru-RU') : '';

    // Renovation/finishing label
    const renovationMap = {
        'fine_finish': 'Чистовая', 'чистовая': 'Чистовая', 'чистов': 'Чистовая',
        'rough_finish': 'Черновая', 'черновая': 'Черновая', 'чернов': 'Черновая',
        'turnkey': 'Под ключ', 'ключ': 'Под ключ',
        'pre_finish': 'Предчистовая', 'предчистовая': 'Предчистовая',
        'no_renovation': 'Без отделки', 'без': 'Без отделки'
    };
    const rawReno = (property.renovation_type || '').toLowerCase();
    let renovationLabel = '';
    if (rawReno) {
        for (const [key, label] of Object.entries(renovationMap)) {
            if (rawReno.includes(key)) { renovationLabel = label; break; }
        }
        if (!renovationLabel && property.renovation_type && property.renovation_type.toLowerCase() !== 'none') renovationLabel = property.renovation_type;
    }
    
    // Store images for slider
    card.imageData = allImages;
    
    const propertyUrl = property.url || (window.CURRENT_CITY_SLUG ? `/${window.CURRENT_CITY_SLUG}/object/${property.id}` : `/object/${property.id}`);
    const _cSlug = window.CURRENT_CITY_SLUG || 'krasnodar';
    const _complexUrl = property.complex_slug ? `/${_cSlug}/zk/${property.complex_slug}` : '';
    const _complexNameText = property.residential_complex || property.complex_name || 'Жилой комплекс';
    const _buildingNameHtml = property.building_name ? ` <span class="font-normal text-gray-500">— ${property.building_name}</span>` : '';
    const _complexNameHtml = _complexUrl
        ? `<span class="text-[#0088CC] hover:underline cursor-pointer" onclick="event.preventDefault();event.stopPropagation();window.location.href='${_complexUrl}'">${_complexNameText}</span>${_buildingNameHtml}`
        : `${_complexNameText}${_buildingNameHtml}`;

    const _sliderDataAttr = allImages.length > 1 ? `data-images='${JSON.stringify(allImages).replace(/'/g, '&#39;')}'` : '';
    card.innerHTML = `
        <a href="${propertyUrl}" style="display: block; text-decoration: none; color: inherit; height: 100%;" class="flex flex-col h-full">
        <div class="relative image-slider-container bg-gray-200 overflow-hidden" style="height: 180px; max-height: 180px;" ${_sliderDataAttr} onmouseenter="startImageSlider(this)" onmouseleave="stopImageSlider(this)" onclick="event.preventDefault();nextSliderImage(this)">
            <img alt="${property.residential_complex}" class="w-full h-full object-cover object-center main-image cursor-pointer" src="${firstImage}" style="height: 180px; max-height: 180px;" onerror="this.src='/static/images/no-photo.svg';"/>
            ${renovationLabel ? `<div class="absolute top-2 left-2 bg-black/60 text-white px-2 py-1 rounded-full text-xs font-medium pointer-events-none">${renovationLabel}</div>` : ''}
            ${imageCount > 1 ? `<div class="absolute bottom-2 left-2 bg-black/60 text-white text-xs px-2 py-1 rounded-full pointer-events-none font-medium">${imageCount} фото</div>` : ''}
            ${imageCount > 1 ? `<div class="absolute bottom-2 right-2 bg-black/50 text-white text-xs px-2 py-1 rounded hidden slider-indicator pointer-events-none">1/${imageCount}</div>` : ''}
            ${imageCount > 1 ? `<div class="absolute top-1/2 left-1/2 transform -translate-x-1/2 -translate-y-1/2 bg-black/40 hover:bg-black/60 text-white w-8 h-8 rounded-full flex items-center justify-center cursor-pointer pointer-events-none transition-colors">
                <svg width="16" height="16" fill="currentColor" viewBox="0 0 16 16">
                    <path d="m12.14 8.753-5.482 4.796c-.646.566-1.658.106-1.658-.753V3.204a1 1 0 0 1 1.659-.753l5.48 4.796a1 1 0 0 1 0 1.506z"/>
                </svg>
            </div>` : ''}
        </div>
        <div class="p-3 flex-1 flex flex-col">
            <div class="mb-2">
                <div class="text-lg font-bold text-[#0088CC]">${price}</div>
                ${cashbackAmount > 0 ? `<div class="flex items-center gap-1 mt-1">
                    <span class="inline-flex items-center bg-gradient-to-r from-green-500 to-emerald-600 text-white text-xs font-semibold px-2 py-0.5 rounded-full shadow-sm">
                        <svg class="w-3 h-3 mr-1" fill="currentColor" viewBox="0 0 20 20"><path d="M4 4a2 2 0 00-2 2v4a2 2 0 002 2V6h10a2 2 0 00-2-2H4zm2 6a2 2 0 012-2h8a2 2 0 012 2v4a2 2 0 01-2 2H8a2 2 0 01-2-2v-4zm6 4a2 2 0 100-4 2 2 0 000 4z"></path></svg>
                        Кэшбек до ${cashbackFormatted} ₽
                    </span>
                </div>` : ''}
                <div class="text-xs text-gray-500 mt-1">${roomText}${area ? ', ' + area + ' м²' : ''}${floorText ? ', ' + floorText : ''}</div>
            </div>
            <div class="flex-1">
                <p class="text-sm font-semibold text-gray-800 line-clamp-1">${_complexNameHtml}</p>
                ${(function(){
                    var dist = property.parsed_district || '';
                    var q = property.parsed_settlement || '';
                    if (dist || q) {
                        var parts = [];
                        if (dist) parts.push(dist);
                        if (q && q !== dist) parts.push(q);
                        return `<p class="text-xs text-gray-400 mt-0.5 line-clamp-1">📍 ${parts.join(', ')}</p>`;
                    }
                    return property.address ? `<p class="text-xs text-gray-400 mt-0.5 line-clamp-1">📍 ${property.address}</p>` : (developer ? `<p class="text-xs text-gray-500 mt-0.5">${developer}</p>` : '');
                })()}
            </div>
        </div>
    `;
    
    // Add hover handler to highlight card AND marker on map
    card.addEventListener('mouseenter', function() {
        // Highlight this card with visual feedback
        card.classList.add('highlighted-card');
        card.style.boxShadow = '0 8px 16px rgba(0, 136, 204, 0.3)';
        card.style.transform = 'scale(1.02)';
        
        // 🗺️ ALSO HIGHLIGHT MARKER ON MAP - for custom HTML markers
        if (window.propertyIdToMarkerMap) {
            const markers = window.propertyIdToMarkerMap[property.id];
            if (markers && markers.length > 0) {
                markers.forEach(marker => {
                    try {
                        // For Yandex custom layouts, getOverlay() returns the DOM element directly
                        const overlay = marker.getOverlay();
                        if (overlay && overlay.style) {
                            overlay.style.zIndex = '1000';
                            overlay.style.filter = 'drop-shadow(0 0 8px rgba(255, 50, 50, 0.8)) brightness(1.3)';
                            overlay.style.transform = 'scale(1.2)';
                            overlay.style.transition = 'all 0.2s ease';
                        }
                    } catch (e) {
                        // Silently continue - marker might not be accessible
                    }
                });
            }
        }
    });
    
    card.addEventListener('mouseleave', function() {
        // Remove highlight from card
        card.classList.remove('highlighted-card');
        card.style.boxShadow = '';
        card.style.transform = '';
        
        // 🗺️ REMOVE MARKER HIGHLIGHT
        if (window.propertyIdToMarkerMap) {
            const markers = window.propertyIdToMarkerMap[property.id];
            if (markers && markers.length > 0) {
                markers.forEach(marker => {
                    try {
                        const overlay = marker.getOverlay();
                        if (overlay && overlay.style) {
                            overlay.style.zIndex = '100';
                            overlay.style.filter = '';
                            overlay.style.transform = '';
                            overlay.style.transition = '';
                        }
                    } catch (e) {
                        // Silently continue - marker might not be accessible
                    }
                });
            }
        }
    });
    
    return card;
}

// Handle map click - always opens fullscreen modal map
function handleMapClick(event) {
    if (event) event.stopPropagation();
    openFullscreenMap();
}

// ESC key handler for modal
function handleEscKey(event) {
    if (event.key === 'Escape' || event.keyCode === 27) {
        const modal = document.getElementById('fullscreenMapModal');
        if (modal && !modal.classList.contains('hidden')) {
            closeFullscreenMap();
        }
    }
}

// Add ESC key listener on load
document.addEventListener('keydown', handleEscKey);

// Desktop filter functions (main toggleQuickRoomFilter defined below at ~line 2800)

function updateQuickRoomChips() {
    document.querySelectorAll('[data-quick-room]').forEach(chip => {
        const room = parseInt(chip.dataset.quickRoom);
        if (mapFilters.rooms.includes(room)) {
            chip.classList.add('map-chip-active');
            chip.classList.remove('border-gray-300');
        } else {
            chip.classList.remove('map-chip-active');
            chip.classList.add('border-gray-300');
        }
    });
}

function applyMapDesktopFilters() {
    mapFilters.price_min = document.getElementById('mapDesktopPriceFrom')?.value || '';
    mapFilters.price_max = document.getElementById('mapDesktopPriceTo')?.value || '';
    console.log('🗺️ Desktop filters applied:', mapFilters);
}

// resetMapAdvancedFilters — каноническая реализация теперь в
// templates/properties.html (window.resetMapAdvancedFilters @~10531).
// Это сделано чтобы избежать дубликатов: template-override побеждал JS
// (script tag загружается раньше template's bottom-of-file overrides) и
// JS-копия становилась мёртвым кодом, источником рассинхрона.

// Load districts into desktop filter panel
function loadMapDesktopDistricts() {
    const container = document.getElementById('mapDesktopDistrictsContainer');
    if (!container) return;
    
    fetch(`/api/districts/1`)
        .then(r => r.json())
        .then(data => {
            if (data.success && data.districts) {
                container.innerHTML = data.districts.map(d => `
                    <label class="flex items-center hover:bg-gray-50 p-2 rounded-lg cursor-pointer">
                        <input type="checkbox" value="${d.id}" data-map-filter="district" 
                               class="text-blue-600 focus:ring-blue-500 border-gray-300 rounded">
                        <span class="ml-2 text-sm text-gray-700">${d.name}</span>
                    </label>
                `).join('');
                console.log(`✅ Loaded ${data.districts.length} districts for map filters`);
            }
        })
        .catch(e => console.warn('⚠️ Failed to load map districts:', e));
}

// Load developers into the advanced-filters modal (and legacy desktop panel if present)
function loadMapDevelopers() {
    // Support both the new modal container (#mapDevelopersList) and the legacy desktop one
    const containers = [
        document.getElementById('mapDevelopersList'),
        document.getElementById('mapDesktopDevelopersContainer')
    ].filter(Boolean);
    if (containers.length === 0) return;

    fetch(`/api/developers?city_id=${window.currentCityId || 1}`)
        .then(r => r.json())
        .then(data => {
            if (data.success && data.developers) {
                const checkedSet = new Set((window.mapFilters && Array.isArray(window.mapFilters.developers))
                    ? window.mapFilters.developers.map(String) : []);
                const html = data.developers.map(d => `
                    <label class="flex items-center hover:bg-gray-50 p-2 rounded-lg cursor-pointer">
                        <input type="checkbox" value="${d.id}" data-map-filter="developer"
                               class="text-blue-600 focus:ring-blue-500 border-gray-300 rounded"
                               ${checkedSet.has(String(d.id)) ? 'checked' : ''}
                               onchange="if(typeof fetchAndUpdateFilteredCount==='function')fetchAndUpdateFilteredCount();">
                        <span class="ml-2 text-sm text-gray-700">${d.name}</span>
                    </label>
                `).join('');
                containers.forEach(c => { c.innerHTML = html; });
                console.log(`✅ Loaded ${data.developers.length} developers for map filters into ${containers.length} container(s)`);
                // Re-sync UI now that developer checkboxes exist in the DOM —
                // syncMapFiltersToUi only touches already-rendered nodes, so
                // selected developers inherited from URL (?map=1&developer=…)
                // wouldn't appear checked on first paint without this pass.
                if (typeof window.syncMapFiltersToUi === 'function') {
                    try { window.syncMapFiltersToUi(); } catch (e) { /* noop */ }
                }
                if (typeof window._paintAllMapChips === 'function') {
                    try { window._paintAllMapChips(); } catch (e) { /* noop */ }
                }
            }
        })
        .catch(e => console.warn('⚠️ Failed to load map developers:', e));
}
window.loadMapDevelopers = loadMapDevelopers;

// NOTE: openMapAdvancedFiltersFromQuick + applyMapAdvancedFilters definitions
// live below (single source of truth). Duplicate stubs that used to live here
// were removed to avoid hoisting confusion.

// Make functions globally available
window.openFullscreenMap = openFullscreenMap;
window.closeFullscreenMap = closeFullscreenMap;
window.handleMapClick = handleMapClick;
window.closePropertyBottomSheet = closePropertyBottomSheet;
window.toggleQuickRoomFilter = toggleQuickRoomFilter;
window.applyMapDesktopFilters = applyMapDesktopFilters;
// window.resetMapAdvancedFilters — defined in templates/properties.html (canonical)
window.createDesktopPropertyCard = createDesktopPropertyCard;
window.loadMapDesktopDistricts = loadMapDesktopDistricts;
window.loadMapDevelopers = loadMapDevelopers;
window.openMapAdvancedFiltersFromQuick = openMapAdvancedFiltersFromQuick;
window.closeMapAdvancedFilters = closeMapAdvancedFilters;
// window.applyMapAdvancedFilters — defined in templates/properties.html (canonical)
window.openMapQuickFilters = openMapQuickFilters;
window.closeMapQuickFilters = closeMapQuickFilters;
window.toggleToolbarRoomFilter = toggleToolbarRoomFilter;
window.applyQuickFilters = applyQuickFilters;
window.resetQuickFilters = resetQuickFilters;
window.syncQuickFiltersFromState = syncQuickFiltersFromState;
window.syncAdvancedFiltersFromState = syncAdvancedFiltersFromState;
// window.fetchAndUpdateFilteredCount — defined in templates/properties.html (canonical)
window.updateResultsButtonText = updateResultsButtonText;
window.toggleMapDevelopersList = toggleMapDevelopersList;

// ─── Map Left Panel Sort ───────────────────────────────────────────────────
function sortMapPropertiesArray(arr) {
    if (!arr || !arr.length) return arr;
    const s = (window.mapFilters && window.mapFilters.sort) || '';
    if (!s) return arr;
    return [...arr].sort((a, b) => {
        if (s === 'price-asc')  return (a.price || 0) - (b.price || 0);
        if (s === 'price-desc') return (b.price || 0) - (a.price || 0);
        if (s === 'area-asc')   return (a.area || 0) - (b.area || 0);
        if (s === 'area-desc')  return (b.area || 0) - (a.area || 0);
        return 0;
    });
}

function toggleMapSortDropdown(event) {
    if (event) event.stopPropagation();
    const dd = document.getElementById('mapSortDropdown');
    if (!dd) return;
    dd.classList.toggle('hidden');
    if (!dd.classList.contains('hidden')) {
        // Close on outside click
        const close = (e) => {
            if (!dd.contains(e.target)) { dd.classList.add('hidden'); document.removeEventListener('click', close); }
        };
        setTimeout(() => document.addEventListener('click', close), 0);
    }
}

function selectMapSort(btn) {
    const dd = document.getElementById('mapSortDropdown');
    if (dd) dd.classList.add('hidden');
    const val = btn.dataset.sort || '';
    if (!window.mapFilters) window.mapFilters = {};
    window.mapFilters.sort = val;
    const label = document.getElementById('mapSortLabel');
    if (label) label.textContent = btn.textContent.trim();
    document.querySelectorAll('.map-sort-opt').forEach(b => {
        b.classList.toggle('font-medium', b === btn);
        b.classList.toggle('text-[#0088CC]', b === btn);
    });
    // ✅ Unified pipeline: route sort through updateMapWithFilters so
    // markers + cards + counter all stay in sync with current filters.
    if (typeof window.updateMapWithFilters === 'function') {
        console.log('↕️ Sort → updateMapWithFilters (sort=' + val + ')');
        window.updateMapWithFilters();
        return;
    }
    // Fallback (should not trigger in normal flow)
    const container = document.getElementById('mapDesktopPropertiesContainer');
    if (!container) return;

    // Show loading skeletons while fetching
    const cards = container.querySelectorAll('[data-property-id]');
    cards.forEach(c => c.remove());
    for (let i = 0; i < 4; i++) {
        const s = document.createElement('div');
        s.className = 'animate-pulse bg-gray-100 rounded-lg h-56';
        s.dataset.skeleton = '1';
        container.appendChild(s);
    }

    // Build params with current filters + sort
    const params = new URLSearchParams();
    if (window.currentCityId) params.append('city_id', window.currentCityId);
    if (window.mapFilters) {
        if (window.mapFilters.rooms && window.mapFilters.rooms.length > 0)
            window.mapFilters.rooms.forEach(r => params.append('rooms', r));
        if (window.mapFilters.price_min) {
            const v = parseFloat(window.mapFilters.price_min);
            params.append('price_min', v < 1000 ? v * 1000000 : v);
        }
        if (window.mapFilters.price_max) {
            const v = parseFloat(window.mapFilters.price_max);
            params.append('price_max', v < 1000 ? v * 1000000 : v);
        }
        if (window.mapFilters.area_min) params.append('area_min', window.mapFilters.area_min);
        if (window.mapFilters.area_max) params.append('area_max', window.mapFilters.area_max);
        if (window.mapFilters.floor_min) params.append('floor_min', window.mapFilters.floor_min);
        if (window.mapFilters.floor_max) params.append('floor_max', window.mapFilters.floor_max);
    }
    if (val) params.append('sort', val);
    params.append('per_page', '100');
    params.append('page', '1');

    fetch(`/api/map-properties?${params.toString()}`)
        .then(r => r.json())
        .then(d => {
            container.querySelectorAll('[data-skeleton]').forEach(el => el.remove());
            if (!d.success || !d.properties) return;
            const props = d.properties;
            window.initialMapProperties = props;
            // Client-side sort as fallback (API may not honour sort param yet)
            const sorted = sortMapPropertiesArray(props);
            sorted.forEach(p => {
                try { container.appendChild(createDesktopPropertyCard(p)); } catch(e) {}
            });
            const total = d.pagination ? d.pagination.total : props.length;
            const panelCountEl = document.getElementById('mapDesktopPanelCount');
            if (panelCountEl) panelCountEl.textContent = `${total} объектов`;
        })
        .catch(() => {
            container.querySelectorAll('[data-skeleton]').forEach(el => el.remove());
            // Fallback: sort existing cached data
            const _src = window.initialMapProperties || window.mapAllProperties || [];
            const sorted = sortMapPropertiesArray(_src);
            sorted.forEach(p => {
                try { container.appendChild(createDesktopPropertyCard(p)); } catch(e) {}
            });
        });
}
window.toggleMapSortDropdown = toggleMapSortDropdown;
window.selectMapSort = selectMapSort;
window.sortMapPropertiesArray = sortMapPropertiesArray;

// Initialize mini map lazily — only when the map container enters the viewport
(function() {
    function doInit() {
        console.log('🗺️ Properties mini map - viewport trigger');
        setTimeout(initMiniPropertiesMap, 100);
    }

    function attachObserver() {
        var mapEl = document.getElementById('miniPropertiesMap');
        // On mobile the map div is hidden (md:block) — skip entirely
        if (!mapEl || window.innerWidth < 768) {
            console.log('🗺️ Mini map: skipping init on mobile or element missing');
            return;
        }

        if (typeof IntersectionObserver !== 'undefined') {
            var obs = new IntersectionObserver(function(entries) {
                entries.forEach(function(entry) {
                    if (entry.isIntersecting) {
                        obs.disconnect();
                        doInit();
                    }
                });
            }, { rootMargin: '200px', threshold: 0 });
            obs.observe(mapEl);
            console.log('🗺️ Mini map: IntersectionObserver attached (lazy init)');
        } else {
            // Fallback for old browsers
            doInit();
        }
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', attachObserver);
    } else {
        attachObserver();
    }
}());

// ==================== MAP FILTERS FUNCTIONALITY ====================

// Filter state management - ГЛОБАЛЬНАЯ переменная для доступа из других скриптов
window.mapFilters = {
    // Quick filters
    rooms: [],
    
    // Price range
    price_min: '',
    price_max: '',
    
    // Area range
    area_min: '',
    area_max: '',
    
    // Floor range
    floor_min: '',
    floor_max: '',
    
    // Building floors range
    building_floors_min: '',
    building_floors_max: '',
    
    // Build year range
    build_year_min: '',
    build_year_max: '',
    
    // Multi-select filters
    developers: [],
    districts: [],
    completion: [],
    object_classes: [],
    building_status: [],
    features: [],
    building_released: [],
    floor_options: [],
    renovation: []
};
const mapFilters = window.mapFilters;

// Debounce helper
function debounce(func, wait) {
    let timeout;
    return function executedFunction(...args) {
        const later = () => {
            clearTimeout(timeout);
            func(...args);
        };
        clearTimeout(timeout);
        timeout = setTimeout(later, wait);
    };
}

// Toggle room filter chip
function toggleMapRoomFilter(room) {
    const index = mapFilters.rooms.indexOf(room);
    const chip = document.querySelector(`button[data-map-room-filter="${room}"]`);
    
    if (index > -1) {
        // Remove filter
        mapFilters.rooms.splice(index, 1);
        if (chip) {
            chip.classList.remove('map-chip-active');
            chip.classList.add('border-gray-300');
        }
    } else {
        // Add filter
        mapFilters.rooms.push(room);
        if (chip) {
            chip.classList.add('map-chip-active');
            chip.classList.remove('border-gray-300');
        }
    }
    
    // ✅ Unified pipeline: refresh markers + left cards + counter
    // ✅ Persist rooms to URL so navigation back from /object/X retains state
    try {
        var _u = new URL(window.location.href);
        _u.searchParams.delete('rooms');
        (mapFilters.rooms || []).forEach(function(r){ _u.searchParams.append('rooms', r); });
        _u.searchParams.delete('page');
        window.history.replaceState(null, '', _u.toString());
    } catch(e) {}
    console.log('🗺️ Room filter applied, updating map with rooms:', mapFilters.rooms);
    if (typeof updateMapWithFilters === 'function') {
        updateMapWithFilters();
    }
}

// Open advanced filters modal
function openMapAdvancedFilters() {
    const modal = document.getElementById('mapAdvancedFiltersModal');
    if (modal) {
        modal.classList.remove('hidden');
        modal.style.zIndex = '10005';
        // Block body scroll only on mobile — desktop side panel doesn't need it
        if (window.innerWidth < 1024) document.body.style.overflow = 'hidden';
        if (typeof syncAdvancedFiltersFromState === 'function') syncAdvancedFiltersFromState();
        if (typeof window.fetchAndUpdateFilteredCount === 'function') window.fetchAndUpdateFilteredCount();
    }
}

// Close advanced filters modal
function closeMapAdvancedFilters() {
    const modal = document.getElementById('mapAdvancedFiltersModal');
    if (modal) {
        modal.classList.add('hidden');
        document.body.style.overflow = '';
    }
}

// Toggle developers list (collapsible)
function toggleMapDevelopersList() {
    const list = document.getElementById('mapDevelopersList');
    const chevron = document.getElementById('mapDevelopersChevron');
    if (list && chevron) {
        list.classList.toggle('hidden');
        chevron.classList.toggle('rotate-180');
    }
}

// === TOOLBAR QUICK FILTERS ===

// Toggle room filter on toolbar
function toggleToolbarRoomFilter(room) {
    const index = mapFilters.rooms.indexOf(room);
    
    if (index > -1) {
        mapFilters.rooms.splice(index, 1);
    } else {
        mapFilters.rooms.push(room);
    }
    
    // Sync ALL chips with this room value (toolbar + quick-room + mobile sheet)
    document.querySelectorAll(`[data-quick-room="${room}"], [data-toolbar-room="${room}"]`).forEach(c => {
        if (mapFilters.rooms.includes(room)) {
            c.classList.add('map-chip-active');
            c.classList.remove('border-gray-300');
        } else {
            c.classList.remove('map-chip-active');
            c.classList.add('border-gray-300');
        }
    });
    
    console.log('🗺️ Toolbar room filter toggled:', room, 'Current rooms:', mapFilters.rooms);
    
    // Sync with bottom sheet chips
    syncToolbarFiltersWithBottomSheet();
    
    // Update map badge counter
    updateMapFiltersBadge();
    
    // ✅ Unified pipeline: refresh BOTH markers and left cards
    // ✅ Persist rooms to URL so navigation back from /object/X retains state
    try {
        var _u = new URL(window.location.href);
        _u.searchParams.delete('rooms');
        (mapFilters.rooms || []).forEach(function(r){ _u.searchParams.append('rooms', r); });
        _u.searchParams.delete('page');
        window.history.replaceState(null, '', _u.toString());
    } catch(e) {}
    if (typeof updateMapWithFilters === 'function') {
        updateMapWithFilters();
    }
}

// Sync toolbar filters with bottom sheet
function syncToolbarFiltersWithBottomSheet() {
    // Sync room chips in bottom sheet
    document.querySelectorAll('[data-quick-room]').forEach(chip => {
        const room = parseInt(chip.dataset.quickRoom);
        const toolbarChip = document.querySelector(`button[data-toolbar-room="${room}"]`);
        
        if (mapFilters.rooms.includes(room)) {
            chip.classList.add('map-chip-active');
            chip.classList.remove('border-gray-300');
            if (toolbarChip) {
                toolbarChip.classList.add('map-chip-active');
                toolbarChip.classList.remove('border-gray-300');
            }
        } else {
            chip.classList.remove('map-chip-active');
            chip.classList.add('border-gray-300');
            if (toolbarChip) {
                toolbarChip.classList.remove('map-chip-active');
                toolbarChip.classList.add('border-gray-300');
            }
        }
    });
}

// === RESULTS COUNT (async, debounced) ===

let _countFetchTimer = null;

function updateResultsButtonText(count) {
    const safeCount = (typeof count === 'number' && count >= 0) ? count : 0;
    const text = safeCount > 0
        ? `Показать ${safeCount.toLocaleString('ru-RU')} объектов`
        : 'Показать результаты';
    document.querySelectorAll('.js-map-show-results').forEach(btn => {
        btn.textContent = text;
    });
    // ✅ Also keep the "Подходит объектов" live count inside the advanced
    // filters modal in sync — same source of truth as the button text.
    const liveCount = document.getElementById('mapModalLiveCount');
    if (liveCount) liveCount.textContent = safeCount.toLocaleString('ru-RU');
    const advBadge = document.getElementById('advancedFiltersCounterMap');
    // (Badge counts active filters, not results — leave it alone here.)
}

// fetchAndUpdateFilteredCount — каноническая реализация теперь в
// templates/properties.html (window.fetchAndUpdateFilteredCount @~10701):
// сначала синхронизирует DOM модалки → window.mapFilters, потом зовёт
// единый pipeline window.updateMapWithFilters (debounced 150ms).
// JS-копия удалена чтобы устранить дубликат-определения.

// Sync advanced filter modal inputs from current mapFilters state
function syncAdvancedFiltersFromState() {
    const _toMln = v => { if (!v) return ''; const n = parseFloat(v); if (isNaN(n)) return ''; return n >= 10000 ? parseFloat((n / 1000000).toFixed(2)) : n; };
    const pf = document.getElementById('mapPriceFrom'); if (pf) pf.value = _toMln(mapFilters.price_min);
    const pt = document.getElementById('mapPriceTo'); if (pt) pt.value = _toMln(mapFilters.price_max);
    const af = document.getElementById('mapAreaFrom'); if (af) af.value = mapFilters.area_min || '';
    const at = document.getElementById('mapAreaTo'); if (at) at.value = mapFilters.area_max || '';
    const ff = document.getElementById('mapFloorFrom'); if (ff) ff.value = mapFilters.floor_min || '';
    const ft = document.getElementById('mapFloorTo'); if (ft) ft.value = mapFilters.floor_max || '';
    // Sync checkboxes
    document.querySelectorAll('[data-map-filter="completion"]').forEach(cb => {
        cb.checked = mapFilters.completion && mapFilters.completion.includes(cb.value);
    });
    document.querySelectorAll('[data-map-filter="building_status"]').forEach(cb => {
        cb.checked = mapFilters.building_status && mapFilters.building_status.includes(cb.value);
    });
    document.querySelectorAll('[data-map-filter="object_class"]').forEach(cb => {
        cb.checked = mapFilters.object_classes && mapFilters.object_classes.includes(cb.value);
    });
    // ✅ Sync new room chips inside the advanced modal
    document.querySelectorAll('#mapAdvancedFiltersModal [data-map-filter="rooms"]').forEach(cb => {
        var v = parseInt(cb.value, 10);
        cb.checked = Array.isArray(mapFilters.rooms) && mapFilters.rooms.includes(v);
    });
    // ✅ Sync developer checkboxes inside the modal
    document.querySelectorAll('#mapDevelopersList input[type=checkbox]').forEach(cb => {
        cb.checked = Array.isArray(mapFilters.developers) && mapFilters.developers.includes(cb.value);
    });
}

// === QUICK FILTERS BOTTOM SHEET ===

// Open quick filters bottom sheet
function openMapQuickFilters() {
    const backdrop = document.getElementById('mapQuickFiltersBackdrop');
    const sheet = document.getElementById('mapQuickFiltersSheet');
    
    if (backdrop && sheet) {
        backdrop.classList.remove('hidden');
        sheet.classList.remove('hidden');
        sheet.style.display = 'flex';
        
        setTimeout(() => {
            backdrop.style.opacity = '1';
            sheet.style.transform = 'translateY(0)';
        }, 10);
        
        // Sync values from mapFilters to quick filters UI
        syncQuickFiltersFromState();
        
        // Show current results count
        if (typeof window.fetchAndUpdateFilteredCount === 'function') window.fetchAndUpdateFilteredCount();
        
        console.log('🗺️ Quick filters bottom sheet opened');
    }
}

// Close quick filters bottom sheet
function closeMapQuickFilters() {
    const backdrop = document.getElementById('mapQuickFiltersBackdrop');
    const sheet = document.getElementById('mapQuickFiltersSheet');
    
    if (backdrop && sheet) {
        backdrop.style.opacity = '0';
        sheet.style.transform = 'translateY(100%)';
        
        setTimeout(() => {
            backdrop.classList.add('hidden');
            sheet.classList.add('hidden');
            sheet.style.display = '';
        }, 300);
        
        console.log('🗺️ Quick filters bottom sheet closed');
    }
}

// Toggle room filter in quick filters
function toggleQuickRoomFilter(room) {
    const index = mapFilters.rooms.indexOf(room);
    
    if (index > -1) {
        // Remove filter
        mapFilters.rooms.splice(index, 1);
    } else {
        // Add filter
        mapFilters.rooms.push(room);
    }

    // Update ALL chips with this room value (desktop toolbar + mobile sheet + top toolbar)
    document.querySelectorAll(`[data-quick-room="${room}"], [data-toolbar-room="${room}"]`).forEach(chip => {
        if (mapFilters.rooms.includes(room)) {
            chip.classList.add('map-chip-active');
            chip.classList.remove('border-gray-300');
        } else {
            chip.classList.remove('map-chip-active');
            chip.classList.add('border-gray-300');
        }
    });

    console.log('🗺️ Quick room filter toggled:', room, 'Current rooms:', mapFilters.rooms);
    // Update map: use updateMapWithFilters to refresh BOTH markers AND left panel
    updateMapWithFilters();
    updateMapFiltersBadge();
    if (typeof displayMapActiveFilters === 'function') displayMapActiveFilters();
}

// Sync quick filters UI from current filter state
function syncQuickFiltersFromState() {
    // Sync room chips in bottom sheet AND toolbar
    document.querySelectorAll('[data-quick-room], [data-toolbar-room]').forEach(chip => {
        const room = parseInt(chip.dataset.quickRoom || chip.dataset.toolbarRoom);
        if (mapFilters.rooms.includes(room)) {
            chip.classList.add('map-chip-active');
            chip.classList.remove('border-gray-300');
        } else {
            chip.classList.remove('map-chip-active');
            chip.classList.add('border-gray-300');
        }
    });
    
    // Sync price inputs (mapFilters stores in millions; convert if value looks like raw rubles)
    const _toMln = v => { if (!v || v === '') return ''; const n = parseFloat(v); if (isNaN(n)) return ''; return n >= 10000 ? parseFloat((n / 1000000).toFixed(2)) : n; };
    const quickPriceFrom = document.getElementById('quickPriceFrom');
    const quickPriceTo = document.getElementById('quickPriceTo');
    if (quickPriceFrom) quickPriceFrom.value = _toMln(mapFilters.price_min);
    if (quickPriceTo) quickPriceTo.value = _toMln(mapFilters.price_max);
    
    // Sync area inputs
    const quickAreaFrom = document.getElementById('quickAreaFrom');
    const quickAreaTo = document.getElementById('quickAreaTo');
    if (quickAreaFrom) quickAreaFrom.value = mapFilters.area_min || '';
    if (quickAreaTo) quickAreaTo.value = mapFilters.area_max || '';
}

// Apply quick filters
function applyQuickFilters() {
    // Collect values from quick filter inputs
    mapFilters.price_min = document.getElementById('quickPriceFrom').value;
    mapFilters.price_max = document.getElementById('quickPriceTo').value;
    mapFilters.area_min = document.getElementById('quickAreaFrom').value;
    mapFilters.area_max = document.getElementById('quickAreaTo').value;
    
    console.log('🗺️ Applying quick filters:', mapFilters);
    
    // Update filters summary
    updateFiltersCount();
    
    // Update map badge counter
    updateMapFiltersBadge();
    
    // Close bottom sheet
    closeMapQuickFilters();
    
    // ✅ Unified pipeline: refresh markers + left cards + counter together
    if (typeof updateMapWithFilters === 'function') {
        updateMapWithFilters();
    }
}

// Reset quick filters
function resetQuickFilters() {
    // Clear rooms
    mapFilters.rooms = [];
    document.querySelectorAll('[data-quick-room], [data-toolbar-room]').forEach(chip => {
        chip.classList.remove('map-chip-active');
        chip.classList.add('border-gray-300');
    });
    
    // Clear price
    mapFilters.price_min = '';
    mapFilters.price_max = '';
    const quickPriceFrom = document.getElementById('quickPriceFrom');
    const quickPriceTo = document.getElementById('quickPriceTo');
    if (quickPriceFrom) quickPriceFrom.value = '';
    if (quickPriceTo) quickPriceTo.value = '';
    
    // Clear area
    mapFilters.area_min = '';
    mapFilters.area_max = '';
    const quickAreaFrom = document.getElementById('quickAreaFrom');
    const quickAreaTo = document.getElementById('quickAreaTo');
    if (quickAreaFrom) quickAreaFrom.value = '';
    if (quickAreaTo) quickAreaTo.value = '';
    
    console.log('🗺️ Quick filters reset');
    
    // ✅ Unified pipeline: refresh markers + left cards + counter together
    if (typeof updateMapWithFilters === 'function') {
        updateMapWithFilters();
    }
}

// Open advanced filters from quick filters bottom sheet
function openMapAdvancedFiltersFromQuick() {
    // Close quick filters
    closeMapQuickFilters();
    
    // Wait for animation, then open advanced
    setTimeout(() => {
        openMapAdvancedFilters();
    }, 350);
}

// Update active filters count display
function updateFiltersCount() {
    let count = 0;
    
    // Count active filters
    if (mapFilters.rooms.length > 0) count++;
    if (mapFilters.price_min || mapFilters.price_max) count++;
    if (mapFilters.area_min || mapFilters.area_max) count++;
    if (mapFilters.floor_min || mapFilters.floor_max) count++;
    if (mapFilters.developers.length > 0) count++;
    if (mapFilters.completion.length > 0) count++;
    if (mapFilters.object_classes.length > 0) count++;
    if (mapFilters.search) count++;
    if (mapFilters.cashback_only) count++;
    
    const summaryEl = document.getElementById('mapActiveFiltersSummary');
    const countEl = document.getElementById('mapActiveFiltersCount');
    
    const resetBtn = document.getElementById('mapResetFiltersBtn');
    if (count > 0) {
        if (summaryEl) summaryEl.classList.remove('hidden');
        if (countEl) countEl.textContent = `${count} ${count === 1 ? 'фильтр' : count < 5 ? 'фильтра' : 'фильтров'}`;
        if (resetBtn) resetBtn.classList.remove('hidden');
    } else {
        if (summaryEl) summaryEl.classList.add('hidden');
        if (resetBtn) resetBtn.classList.add('hidden');
    }
}

// resetMapAdvancedFilters + applyMapAdvancedFilters — канонические
// реализации теперь в templates/properties.html (@~10481 / @~10531).
// Template-overrides побеждают JS из-за порядка загрузки (template's
// нижние inline-script'ы выполняются после <script src="...js">), и эти
// JS-копии стали мёртвым кодом. Удалены чтобы устранить дубликат-
// определения и shadow-баги (см. round 5 fix задачи #6).

// Reset all filters
function resetMapFilters() {
    // Reset filter state
    Object.keys(mapFilters).forEach(key => {
        if (Array.isArray(mapFilters[key])) {
            mapFilters[key] = [];
        } else {
            mapFilters[key] = '';
        }
    });

    // Also remove singular 'developer' from URL without page reload
    try {
        const _u = new URL(window.location.href);
        let changed = false;
        if (_u.searchParams.has('developer')) { _u.searchParams.delete('developer'); changed = true; }
        if (_u.searchParams.has('search')) { _u.searchParams.delete('search'); changed = true; }
        if (changed) history.replaceState(null, '', _u.toString());
    } catch(e) {}
    
    // Reset quick filters UI
    document.querySelectorAll('[data-quick-room]').forEach(chip => {
        chip.classList.remove('map-chip-active');
        chip.classList.add('border-gray-300');
    });
    
    const quickPriceFrom = document.getElementById('quickPriceFrom');
    const quickPriceTo = document.getElementById('quickPriceTo');
    const quickAreaFrom = document.getElementById('quickAreaFrom');
    const quickAreaTo = document.getElementById('quickAreaTo');
    
    if (quickPriceFrom) quickPriceFrom.value = '';
    if (quickPriceTo) quickPriceTo.value = '';
    if (quickAreaFrom) quickAreaFrom.value = '';
    if (quickAreaTo) quickAreaTo.value = '';
    
    // Reset advanced filters UI
    const mapPriceFrom = document.getElementById('mapPriceFrom');
    const mapPriceTo = document.getElementById('mapPriceTo');
    const mapAreaFrom = document.getElementById('mapAreaFrom');
    const mapAreaTo = document.getElementById('mapAreaTo');
    const mapFloorFrom = document.getElementById('mapFloorFrom');
    const mapFloorTo = document.getElementById('mapFloorTo');
    
    if (mapPriceFrom) mapPriceFrom.value = '';
    if (mapPriceTo) mapPriceTo.value = '';
    if (mapAreaFrom) mapAreaFrom.value = '';
    if (mapAreaTo) mapAreaTo.value = '';
    if (mapFloorFrom) mapFloorFrom.value = '';
    if (mapFloorTo) mapFloorTo.value = '';
    
    document.querySelectorAll('[data-map-filter="developer"]').forEach(cb => cb.checked = false);
    document.querySelectorAll('[data-map-filter="completion"]').forEach(cb => cb.checked = false);
    document.querySelectorAll('[data-map-filter="object_class"]').forEach(cb => cb.checked = false);
    document.querySelectorAll('[data-map-filter="building_status"]').forEach(cb => cb.checked = false);
    
    // Update filters count
    updateFiltersCount();
    
    // Update map badge counter (reset to 0)
    updateMapFiltersBadge();
    
    console.log('🗺️ All filters reset');
    updateMapWithFilters();
}

// Update map with current filters
// ✅ Request generation token: prevents stale async responses from
// overwriting newer filter results. Every user filter action increments
// window._mapFilterGen; every async response captures gen at start and
// checks before any DOM write.
if (typeof window._mapFilterGen === 'undefined') window._mapFilterGen = 0;
window._isFilterActive = function() {
    var f = window.mapFilters || {};
    return (Array.isArray(f.rooms) && f.rooms.length > 0)
        || f.price_min || f.price_max || f.area_min || f.area_max
        || f.floor_min || f.floor_max
        || (Array.isArray(f.completion) && f.completion.length > 0)
        || (Array.isArray(f.building_status) && f.building_status.length > 0)
        || (Array.isArray(f.object_classes) && f.object_classes.length > 0)
        || (Array.isArray(f.developers) && f.developers.length > 0)
        || (Array.isArray(f.districts) && f.districts.length > 0)
        || f.search;
};

const updateMapWithFilters = debounce(async function() {
    if (!fullscreenMapInstance) {
        console.warn('⚠️ Map not initialized yet');
        return;
    }
    // Increment generation BEFORE await so stale responses self-cancel.
    window._mapFilterGen = (window._mapFilterGen || 0) + 1;
    const myGen = window._mapFilterGen;

    // ✅ Persist full filter set to URL so /object/<id> → back restores them
    if (typeof persistMapFiltersToUrl === 'function') persistMapFiltersToUrl();
    
    // ✅ ИСПРАВЛЕНИЕ #3: Очищаем все старые маркеры перед пересройкой
    fullscreenMapInstance.geoObjects.removeAll();
    console.log(`🗺️ Cleared old markers - ready for filter update (gen=${myGen})`);
    
    // Show loading indicator
    const loadingEl = document.getElementById('mapFilterLoading');
    if (loadingEl) loadingEl.classList.remove('hidden');
    
    try {
        // Build query params from filters
        const params = new URLSearchParams();
        
        // CRITICAL: Add city_id to filter by current city!
        if (window.currentCityId) {
            params.append('city_id', window.currentCityId);
        }
        
        if (mapFilters.rooms.length > 0) {
            mapFilters.rooms.forEach(room => params.append('rooms', room));
        }
        // Convert price from millions to rubles
        if (mapFilters.price_min) {
            const val = parseFloat(mapFilters.price_min);
            params.append('price_min', val < 1000 ? val * 1000000 : val);
        }
        if (mapFilters.price_max) {
            const val = parseFloat(mapFilters.price_max);
            params.append('price_max', val < 1000 ? val * 1000000 : val);
        }
        if (mapFilters.area_min) params.append('area_min', mapFilters.area_min);
        if (mapFilters.area_max) params.append('area_max', mapFilters.area_max);
        if (mapFilters.floor_min) params.append('floor_min', mapFilters.floor_min);
        if (mapFilters.floor_max) params.append('floor_max', mapFilters.floor_max);
        
        if (mapFilters.developers.length > 0) {
            mapFilters.developers.forEach(dev => params.append('developers', dev));
        }
        if (mapFilters.completion.length > 0) {
            mapFilters.completion.forEach(year => params.append('completion', year));
        }
        if (mapFilters.object_classes.length > 0) {
            mapFilters.object_classes.forEach(cls => params.append('object_classes', cls));
        }
        if (mapFilters.building_status.length > 0) {
            mapFilters.building_status.forEach(status => params.append('building_status', status));
        }
        
        const urlPT = new URLSearchParams(window.location.search).get('property_type');
        if (urlPT && urlPT !== 'all') {
            params.append('property_type', urlPT);
        }
        // ✅ Sort param (drives left-panel card order)
        if (mapFilters.sort) {
            params.append('sort', mapFilters.sort);
        }
        // ✅ Districts / developers / search (from list view via syncUrlFiltersToMapFilters)
        if (Array.isArray(mapFilters.districts) && mapFilters.districts.length > 0) {
            mapFilters.districts.forEach(d => params.append('districts', d));
        }
        if (mapFilters.search) params.append('search', mapFilters.search);
        
        console.log('🗺️ Fetching filtered properties with city_id:', window.currentCityId, params.toString());

        // ✅ FAST APPROACH: Two parallel calls instead of paginated loop
        // 1. Aggregated clusters for the map (fast pre-computed)
        // 2. First 100 individual properties for the left panel cards
        const isMobileView = window.innerWidth <= 1024;
        const cardPerPage = isMobileView ? 50 : 100;

        const aggParams = new URLSearchParams(params);
        const cardParams = new URLSearchParams(params);
        cardParams.append('per_page', String(cardPerPage));
        cardParams.append('page', '1');

        const [aggResp, cardResp] = await Promise.all([
            fetch(`/api/map-properties/aggregated?${aggParams.toString()}`),
            fetch(`/api/map-properties?${cardParams.toString()}`)
        ]);
        const [aggData, cardData] = await Promise.all([aggResp.json(), cardResp.json()]);

        // ✅ Stale response check — newer filter action has superseded us
        if (myGen !== window._mapFilterGen) {
            console.log(`⏭️ updateMapWithFilters: stale response (gen=${myGen}, current=${window._mapFilterGen}) — skip`);
            return;
        }

        const allProperties = (cardData.success && cardData.properties) ? cardData.properties : [];
        const totalCount = (cardData.success && cardData.pagination) ? cardData.pagination.total : allProperties.length;

        console.log(`✅ Loaded ${allProperties.length} card properties (total: ${totalCount}, gen=${myGen})`);
        window.mapAllProperties = allProperties;
        window.initialMapProperties = allProperties;
        // Remember the authoritative filtered count so boundschange handlers
        // can avoid overwriting it with a viewport-based count.
        window._lastFilteredTotal = totalCount;
        window._lastFilteredGen = myGen;
        // ✅ Pagination state for infinite scroll
        window._mapCardsFetchPage  = 1;
        window._mapCardsIsFetching = false;
        window._mapCardsTotalFromServer = totalCount;
        const _paginationPages = (cardData.pagination && cardData.pagination.pages) ? cardData.pagination.pages : 1;
        window._mapCardsTotalPages = _paginationPages;
        // Save filter params (without per_page/page) for subsequent API fetches
        window._mapCardsFilterParams = new URLSearchParams(params);

        // Clear existing markers
        fullscreenMapInstance.geoObjects.removeAll();

        // Update ALL counters (mobile toolbar + desktop toolbar + desktop panel +
        // advanced modal live count + "Показать N объектов" button text).
        const counter = document.getElementById('mapObjectsCount');
        const desktopCounter = document.getElementById('mapObjectsCountDesktop');
        if (counter) counter.textContent = totalCount;
        if (desktopCounter) desktopCounter.textContent = totalCount;
        const panelCountEl = document.getElementById('mapDesktopPanelCount');
        if (panelCountEl) panelCountEl.textContent = `${totalCount} объектов`;
        // ✅ Sync the advanced-filters modal live count + "Показать N" button
        if (typeof updateResultsButtonText === 'function') {
            updateResultsButtonText(totalCount);
        }

        // Render aggregated cluster markers (fast)
        if (aggData.success && aggData.points && aggData.points.length > 0) {
            // 🛡️ Suppress boundschange-triggered viewport reloads for ~2.5s while
            // we render + auto-fit. Without this, the setBounds animation fires
            // boundschange → loadByViewport → renderAggregatedPoints, which calls
            // geoObjects.removeAll() and wipes the freshly-rendered filtered markers.
            window._suppressViewportLoad = Date.now() + 2500;
            // renderAggregatedPoints is defined inside initFullscreenMap (closure) and
            // is not accessible at this top-level scope. Calling it directly would
            // throw a ReferenceError caught silently — markers never appear, panel
            // never updates. Use the exported window reference instead.
            const _renderFn = window.fullscreenRenderAggregated;
            if (typeof _renderFn === 'function') {
                _renderFn(aggData.points, 'filtered');
            } else {
                console.warn('⚠️ fullscreenRenderAggregated not ready — map not yet initialized');
            }
            // Force immediate repaint so markers appear right away without waiting
            // for user drag/zoom (Yandex Maps won't redraw tiles automatically).
            try { fullscreenMapInstance.container.fitToViewport(); } catch(e) {}
            try { fullscreenMapInstance.setCenter(fullscreenMapInstance.getCenter()); } catch(e) {}
            console.log(`✅ Rendered ${aggData.points.length} filtered cluster markers`);
            // Auto-fit map to filtered clusters — but only when URL has no
            // user-chosen viewport (map_center/map_zoom), OR that viewport is
            // incompatible with the new results (none of the filtered points
            // fall within the saved bounds).
            setTimeout(() => {
                try {
                    const _b = fullscreenMapInstance.geoObjects.getBounds();
                    if (!_b) return;

                    const _urlViewport = (typeof readMapViewportFromUrl === 'function') ? readMapViewportFromUrl() : null;
                    let _skipAutoFit = false;
                    if (_urlViewport) {
                        // Compatibility check: does the saved viewport contain at
                        // least one filtered point? If yes, keep the user's view.
                        let _viewBounds = null;
                        try { _viewBounds = fullscreenMapInstance.getBounds(); } catch(e) {}
                        if (_viewBounds) {
                            const [[vLatMin, vLngMin], [vLatMax, vLngMax]] = _viewBounds;
                            const _hit = (aggData.points || []).some(p => {
                                const lat = p.lat || (p.coordinates && p.coordinates.lat) || (Array.isArray(p.coords) ? p.coords[0] : null);
                                const lng = p.lng || (p.coordinates && p.coordinates.lng) || (Array.isArray(p.coords) ? p.coords[1] : null);
                                return lat != null && lng != null
                                    && lat >= vLatMin && lat <= vLatMax
                                    && lng >= vLngMin && lng <= vLngMax;
                            });
                            if (_hit) {
                                _skipAutoFit = true;
                                console.log('🔁 updateMapWithFilters: keeping saved viewport (compatible)');
                            } else {
                                console.log('🔁 updateMapWithFilters: saved viewport incompatible — auto-fit + clearing URL');
                                if (typeof clearMapViewportFromUrl === 'function') clearMapViewportFromUrl();
                            }
                        }
                    }
                    if (!_skipAutoFit) {
                        const _margin = isMobileView ? [60, 60, 60, 60] : [60, 60, 60, 340];
                        fullscreenMapInstance.setBounds(_b, { checkZoomRange: true, duration: 600, zoomMargin: _margin });
                    } else {
                        // Viewport сохранён — принудительно перерисовываем карту,
                        // иначе новые маркеры появляются только после drag/zoom.
                        try { fullscreenMapInstance.container.fitToViewport(); } catch(e) {}
                    }
                } catch(e) { console.warn('Auto-fit error:', e); }
            }, 300);
        }

        console.log(`🧪 [updateMapWithFilters] allProperties.length=${allProperties.length} totalCount=${totalCount} cardData.success=${cardData.success}`);
        if (allProperties.length > 0) {
            // Update left panel with filtered properties (desktop side panel)
            console.log(`🧪 [updateMapWithFilters] -> calling updateDesktopPropertiesPanel`);
            try {
                updateDesktopPropertiesPanel(allProperties, 'Отфильтрованные объекты');
                console.log(`🧪 [updateMapWithFilters] -> updateDesktopPropertiesPanel returned OK`);
                const _c = document.getElementById('mapDesktopPropertiesContainer');
                console.log(`🧪 [updateMapWithFilters] container children=${_c ? _c.children.length : 'NULL'} html.length=${_c ? _c.innerHTML.length : 0}`);
            } catch(e) {
                console.error(`🔴 [updateMapWithFilters] updateDesktopPropertiesPanel THREW`, e);
            }
            // ✅ Mobile bottom sheet refresh — repaint cards in-place if open
            try {
                const bs = document.getElementById('propertyBottomSheet');
                if (isMobileView && bs && !bs.classList.contains('hidden') && bs.classList.contains('active')
                    && typeof openPropertyBottomSheet === 'function') {
                    openPropertyBottomSheet(allProperties);
                }
                _syncBottomSheetCount(totalCount);
            } catch(e) {
                console.warn('⚠️ bottom sheet refresh skipped:', e);
            }
        } else {
            console.log('⚠️ No properties match current filters - clearing sidebar');
            // ✅ Mobile zero-state: clear cards in open bottom sheet + sync counter
            try {
                const bs = document.getElementById('propertyBottomSheet');
                if (isMobileView && bs && !bs.classList.contains('hidden') && bs.classList.contains('active')
                    && typeof openPropertyBottomSheet === 'function') {
                    openPropertyBottomSheet([]);
                }
                _syncBottomSheetCount(0);
            } catch(e) {
                console.warn('⚠️ bottom sheet zero-state skipped:', e);
            }
            const container = document.getElementById('mapDesktopPropertiesContainer');
            if (container) {
                container.innerHTML = '';
                container.scrollTop = 0;
                container.style.display = 'grid';
                container.style.gridTemplateColumns = '1fr 1fr';
                
                const header = document.createElement('div');
                header.className = 'col-span-2 sticky top-0 bg-white z-10 pb-3 border-b border-gray-300 mb-4';
                header.innerHTML = `
                    <div class="flex items-center justify-between">
                        <div>
                            <h3 class="font-bold text-lg text-gray-800">Отфильтрованные объекты</h3>
                            <p class="text-sm text-gray-500">0 объектов</p>
                        </div>
                    </div>
                `;
                container.appendChild(header);
                
                const emptyMsg = document.createElement('div');
                emptyMsg.className = 'col-span-2 text-center py-16';
                emptyMsg.innerHTML = `
                    <svg class="w-16 h-16 mx-auto text-gray-300 mb-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"/>
                    </svg>
                    <p class="text-gray-500 font-medium mb-1">Объектов не найдено</p>
                    <p class="text-gray-400 text-sm">Попробуйте изменить параметры фильтра</p>
                `;
                container.appendChild(emptyMsg);
            }
        }
        
        // Update active filters display
        displayMapActiveFilters();
        
        // Show/hide reset button — use unified _isFilterActive so that
        // developers / building_status / districts also count (раньше
        // кнопка «Сбросить» не показывалась при только-developers и т.п.)
        const hasFilters = (typeof window._isFilterActive === 'function')
            ? window._isFilterActive()
            : (mapFilters.rooms.length > 0 ||
               mapFilters.price_min || mapFilters.price_max ||
               mapFilters.area_min || mapFilters.area_max ||
               mapFilters.floor_min || mapFilters.floor_max ||
               mapFilters.developers.length > 0 ||
               mapFilters.completion.length > 0 ||
               mapFilters.object_classes.length > 0);

        const resetBtn = document.getElementById('mapResetFiltersBtn');
        if (resetBtn) {
            if (hasFilters) {
                resetBtn.classList.remove('hidden');
            } else {
                resetBtn.classList.add('hidden');
            }
        }
        
    } catch (error) {
        console.error('❌ Error updating map with filters:', error);
    } finally {
        // Hide loading indicator
        if (loadingEl) loadingEl.classList.add('hidden');
    }
}, 150); // 150ms debounce (was 500ms — felt sluggish)

// Update active filters display (for MAP panel only — does NOT touch main #active-filters-list)
function _updateMapActiveFiltersDisplay() {
    const container = document.getElementById('mapActiveFilters');
    if (!container) return;
    
    const pills = [];
    
    // Room filters
    if (mapFilters.rooms.length > 0) {
        const roomLabels = mapFilters.rooms.map(r => {
            if (r === 0) return 'Студия';
            if (r === 4) return '4+комн';
            return `${r}-комн`;
        });
        pills.push(`<span class="px-2 py-1 bg-blue-100 text-blue-800 rounded-full text-xs font-medium">
            Комнат: ${roomLabels.join(', ')}
        </span>`);
    }
    
    // Price filter
    if (mapFilters.price_min || mapFilters.price_max) {
        const priceText = [];
        if (mapFilters.price_min) priceText.push(`от ${mapFilters.price_min}М`);
        if (mapFilters.price_max) priceText.push(`до ${mapFilters.price_max}М`);
        pills.push(`<span class="px-2 py-1 bg-blue-100 text-blue-800 rounded-full text-xs font-medium">
            ${priceText.join(' ')}
        </span>`);
    }
    
    // Area filter
    if (mapFilters.area_min || mapFilters.area_max) {
        const areaText = [];
        if (mapFilters.area_min) areaText.push(`от ${mapFilters.area_min}м²`);
        if (mapFilters.area_max) areaText.push(`до ${mapFilters.area_max}м²`);
        pills.push(`<span class="px-2 py-1 bg-blue-100 text-blue-800 rounded-full text-xs font-medium">
            ${areaText.join(' ')}
        </span>`);
    }
    
    // Developers filter
    if (mapFilters.developers.length > 0) {
        pills.push(`<span class="px-2 py-1 bg-blue-100 text-blue-800 rounded-full text-xs font-medium">
            Застройщиков: ${mapFilters.developers.length}
        </span>`);
    }
    
    // Completion filter
    if (mapFilters.completion.length > 0) {
        pills.push(`<span class="px-2 py-1 bg-blue-100 text-blue-800 rounded-full text-xs font-medium">
            Сдача: ${mapFilters.completion.join(', ')}
        </span>`);
    }

    // Building status filter
    if (Array.isArray(mapFilters.building_status) && mapFilters.building_status.length > 0) {
        const statusLabels = { 'completed': 'Сдан', 'under_construction': 'Строится', 'presale': 'Старт продаж' };
        const labels = mapFilters.building_status.map(s => statusLabels[s] || s);
        pills.push(`<span class="px-2 py-1 bg-blue-100 text-blue-800 rounded-full text-xs font-medium">
            Статус: ${labels.join(', ')}
        </span>`);
    }

    // Object class filter
    if (Array.isArray(mapFilters.object_classes) && mapFilters.object_classes.length > 0) {
        const classLabels = { 'comfort': 'Комфорт', 'business': 'Бизнес', 'premium': 'Премиум', 'economy': 'Эконом' };
        const labels = mapFilters.object_classes.map(c => classLabels[c] || c);
        pills.push(`<span class="px-2 py-1 bg-blue-100 text-blue-800 rounded-full text-xs font-medium">
            Класс: ${labels.join(', ')}
        </span>`);
    }

    // Floor range
    if (mapFilters.floor_min || mapFilters.floor_max) {
        const floorText = [];
        if (mapFilters.floor_min) floorText.push(`от ${mapFilters.floor_min}`);
        if (mapFilters.floor_max) floorText.push(`до ${mapFilters.floor_max}`);
        pills.push(`<span class="px-2 py-1 bg-blue-100 text-blue-800 rounded-full text-xs font-medium">
            Этаж: ${floorText.join(' ')}
        </span>`);
    }

    // Districts — individual dismissable chips
    if (Array.isArray(mapFilters.districts) && mapFilters.districts.length > 0) {
        mapFilters.districts.forEach(function(slug) {
            const name = (window.districtNamesMap && window.districtNamesMap[slug]) || slug.replace(/-/g, ' ');
            pills.push(`<span class="px-2 py-1 bg-blue-100 text-blue-800 rounded-full text-xs font-medium inline-flex items-center gap-1">📍 ${name}<button onclick="clearMapFilter('district_slug','${slug.replace(/'/g,"\\'")}')" class="ml-1 hover:text-blue-600 leading-none">×</button></span>`);
        });
    }
    
    if (pills.length > 0) {
        container.innerHTML = pills.join('');
        container.classList.remove('hidden');
    } else {
        container.classList.add('hidden');
    }
}
// Note: window.displayMapActiveFilters is exported below (line ~4932) as the canonical implementation

// Update map filters badge counter
function updateMapFiltersBadge() {
    const counterMap = document.getElementById('advancedFiltersCounterMap');
    
    let count = 0;
    
    // Count selected rooms
    count += mapFilters.rooms.length;
    
    // Count price filter (if either min or max is set)
    if (mapFilters.price_min || mapFilters.price_max) {
        count++;
    }
    
    // Count area filter (if either min or max is set)
    if (mapFilters.area_min || mapFilters.area_max) {
        count++;
    }
    
    // Count developers
    count += mapFilters.developers.length;
    
    // Count completion filters
    count += mapFilters.completion.length;

    // Count building_status filters
    if (Array.isArray(mapFilters.building_status)) count += mapFilters.building_status.length;

    // Count object_classes filters
    if (Array.isArray(mapFilters.object_classes)) count += mapFilters.object_classes.length;

    // Count floor range
    if (mapFilters.floor_min || mapFilters.floor_max) count++;

    // Count districts
    if (Array.isArray(mapFilters.districts)) count += mapFilters.districts.length;

    // Count search/cashback filters
    if (mapFilters.search) count++;
    if (mapFilters.cashback_only) count++;
    
    // Update badge
    if (counterMap) {
        if (count > 0) {
            counterMap.textContent = count;
            counterMap.classList.remove('hidden');
        } else {
            counterMap.classList.add('hidden');
        }
    }

    // Show/hide toolbar reset button
    const resetBtn = document.getElementById('mapResetFiltersBtn');
    if (resetBtn) {
        if (count > 0) resetBtn.classList.remove('hidden');
        else resetBtn.classList.add('hidden');
    }
    
    console.log(`📊 Map filters count: ${count} (rooms: ${mapFilters.rooms.length}, price: ${mapFilters.price_min || mapFilters.price_max ? 1 : 0}, developers: ${mapFilters.developers.length})`);
}

// ✅ NEW: Load more cards for infinite scroll
// ✅ Fetch next page from API and append to window.mapAllProperties
async function loadMoreCardsFromApi() {
    if (window._mapCardsIsFetching) return;
    const fetchPage  = (window._mapCardsFetchPage  || 1);
    const totalPages = (window._mapCardsTotalPages || 1);
    if (fetchPage >= totalPages) return; // Nothing left on server

    window._mapCardsIsFetching = true;
    const nextPage = fetchPage + 1;
    console.log(`📡 Fetching map cards page ${nextPage} of ${totalPages}…`);

    const container = document.getElementById('mapDesktopPropertiesContainer');
    // Show spinner at bottom
    let spinner = document.getElementById('mapInfiniteScrollSpinner');
    if (!spinner && container) {
        spinner = document.createElement('div');
        spinner.id = 'mapInfiniteScrollSpinner';
        spinner.className = 'col-span-2 flex justify-center py-6';
        spinner.innerHTML = '<div class="w-6 h-6 border-2 border-[#0088CC] border-t-transparent rounded-full animate-spin"></div>';
        container.appendChild(spinner);
    }

    try {
        const params = new URLSearchParams(window._mapCardsFilterParams || '');
        params.set('per_page', '100');
        params.set('page', String(nextPage));
        const resp = await fetch(`/api/map-properties?${params.toString()}`);
        const data = await resp.json();
        if (data.success && data.properties && data.properties.length > 0) {
            window.mapAllProperties = [...(window.mapAllProperties || []), ...data.properties];
            window._mapCardsFetchPage = nextPage;
            console.log(`✅ Fetched page ${nextPage}: +${data.properties.length} cards (total local: ${window.mapAllProperties.length})`);
            // Remove spinner before rendering new batch
            const sp = document.getElementById('mapInfiniteScrollSpinner');
            if (sp) sp.remove();
            isLoadingMoreCards = false;
            loadMoreDesktopCards();
        } else {
            // No more pages available
            window._mapCardsTotalPages = nextPage - 1;
            console.log('📋 Server returned no more cards');
        }
    } catch(e) {
        console.warn('❌ loadMoreCardsFromApi error:', e);
    } finally {
        const sp = document.getElementById('mapInfiniteScrollSpinner');
        if (sp) sp.remove();
        window._mapCardsIsFetching = false;
    }
}

function loadMoreDesktopCards() {
    if (isLoadingMoreCards) return;
    
    const container = document.getElementById('mapDesktopPropertiesContainer');
    if (!container) return;
    
    // Use mapAllProperties or initialMapProperties as source
    const sourceProperties = window.mapAllProperties || window.initialMapProperties || [];
    if (sourceProperties.length === 0) return;
    
    const startIndex = currentDisplayOffset;
    const endIndex = Math.min(startIndex + CARDS_PER_PAGE, sourceProperties.length);
    
    if (startIndex >= sourceProperties.length) {
        // Local data exhausted — check if server has more pages
        if ((window._mapCardsFetchPage || 1) < (window._mapCardsTotalPages || 1)) {
            loadMoreCardsFromApi();
        } else {
            console.log('📋 All cards loaded (server exhausted)');
        }
        return;
    }
    
    isLoadingMoreCards = true;
    console.log(`📥 Loading cards ${startIndex + 1}-${endIndex} of ${sourceProperties.length}`);
    
    // Add next batch of cards
    sourceProperties.slice(startIndex, endIndex).forEach(property => {
        const card = createDesktopPropertyCard(property);
        container.appendChild(card);
    });
    
    currentDisplayOffset = endIndex;
    isLoadingMoreCards = false;
    console.log(`✅ Loaded cards up to ${endIndex}`);
    // If we just loaded the last of local data but server has more, pre-fetch
    if (endIndex >= sourceProperties.length
        && (window._mapCardsFetchPage || 1) < (window._mapCardsTotalPages || 1)
        && !window._mapCardsIsFetching) {
        loadMoreCardsFromApi();
    }
}

// ✅ NEW: Filter properties by map viewport and update left panel
function updateDesktopPanelByViewport() {
    if (!fullscreenMapInstance) return;
    
    // ✅ HARD GUARD: when filters are active and we have fresh authoritative cards
    // from /api/map-properties (set by updateMapWithFilters), DO NOT trim the
    // left panel by viewport. Viewport-trim is destructive (overwrites
    // window.mapAllProperties), which made filtered cards "disappear" on any
    // map pan after filter apply. The viewport-trim is only useful for the
    // initial unfiltered exploration mode.
    if (typeof window._isFilterActive === 'function' && window._isFilterActive()
        && window._lastFilteredGen === window._mapFilterGen) {
        console.log('🛑 updateDesktopPanelByViewport: filter active + fresh data — skip viewport trim');
        return;
    }
    
    const container = document.getElementById('mapDesktopPropertiesContainer');
    if (!container) return;
    
    // Get map bounds
    const bounds = fullscreenMapInstance.getBounds();
    if (!bounds) return;
    
    const [[minLat, minLng], [maxLat, maxLng]] = bounds;
    
    // Get all properties from all sources
    const allProperties = window.mapAllProperties || window.initialMapProperties || window.mapInitialProperties || [];
    
    // Filter properties that are visible in current viewport
    const visibleProperties = allProperties.filter(prop => {
        if (!prop.coordinates || !prop.coordinates.lat || !prop.coordinates.lng) return false;
        
        const lat = parseFloat(prop.coordinates.lat);
        const lng = parseFloat(prop.coordinates.lng);
        
        return lat >= minLat && lat <= maxLat && lng >= minLng && lng <= maxLng;
    });
    
    // If very few or no properties, don't disrupt user - keep current view
    if (visibleProperties.length < 2) {
        console.log('📍 Less than 2 properties in viewport - keeping current view');
        return;
    }
    
    console.log(`🗺️ VIEWPORT UPDATE: ${visibleProperties.length} of ${allProperties.length} properties visible`);
    
    // Update the global properties list with filtered results
    window.mapAllProperties = visibleProperties;
    currentViewportProperties = visibleProperties;
    
    // Clear container and reset infinite scroll position
    container.innerHTML = '';
    container.scrollTop = 0;
    currentDisplayOffset = 0;
    isLoadingMoreCards = false;
    
    // Load first batch of viewport-filtered properties
    console.log('📦 Loading first batch of viewport-filtered properties...');
    loadMoreDesktopCards();
}

// Update desktop properties panel with complex header and property cards
function updateDesktopPropertiesPanel(properties, complexName, totalOverride) {
    const container = document.getElementById('mapDesktopPropertiesContainer');
    if (!container) {
        console.warn('⚠️ Desktop properties container not found');
        return;
    }
    
    console.log(`🏢 Updating desktop panel: ${complexName} (${properties.length} properties)`);

    // Track whether a specific cluster/ЖК is selected so boundschange doesn't clobber it
    const isAreaView = (complexName === 'Объекты в области' || complexName === 'Отфильтрованные объекты' || complexName === 'Свойства в области');
    window._mapClusterPanelSelected = !isAreaView;
    
    // 🎯 КРИТИЧНО: Убедимся что контейнер ВИДИМ (не скрыт)
    container.style.display = 'grid';
    container.style.visibility = 'visible';
    container.style.opacity = '1';
    
    // Clear previous content
    container.innerHTML = '';
    container.scrollTop = 0;
    currentDisplayOffset = 0; // Reset scroll offset
    
    // ✅ ИСПРАВЛЕНО: Keep 2-column grid layout even when showing selected group
    container.style.gridTemplateColumns = '1fr 1fr';
    container.style.gap = '12px';
    
    // Add complex header with close button and complex image
    const header = document.createElement('div');
    // -mx-4 -mt-4 px-4 pt-4 cancels the container's p-4 padding so header is flush with the sort bar above
    header.className = 'mb-4 pb-3 border-b border-gray-300 sticky top-0 bg-white z-10 col-span-2 -mx-4 -mt-4 px-4 pt-4';
    
    // Get complex image from first property (use 2nd image from gallery - 1st is always floor plan)
    let complexImage = '/static/images/no-photo.svg';
    if (properties.length > 0) {
        const firstProp = properties[0];
        // Try to get 2nd image (1st is always floor plan)
        if (firstProp.gallery_images) {
            try {
                const imgs = Array.isArray(firstProp.gallery_images) ? firstProp.gallery_images : JSON.parse(firstProp.gallery_images);
                if (imgs.length > 1) complexImage = imgs[1];  // 2nd image
                else if (imgs.length > 0) complexImage = imgs[0];  // fallback to 1st
            } catch(e) {}
        } else if (firstProp.main_image) complexImage = firstProp.main_image;
    }
    
    // ✅ ИСПРАВЛЕНО: Show complex photo only for specific cases (not for filtered results)
    const showComplexPhoto = complexName !== 'Отфильтрованные объекты' && complexName !== 'Свойства в области';
    const photoHTML = showComplexPhoto ? `
        <div class="rounded-lg overflow-hidden -mx-4 -mb-4">
            <img src="${complexImage}" alt="${complexName}" class="w-full h-24 object-cover" 
                 onerror="this.src='/static/images/no-photo.svg'">
        </div>
    ` : '';
    
    // Build ЖК link from first property's complex_slug
    const firstPropSlug = properties.length > 0 ? (properties[0].complex_slug || '') : '';
    const citySlugForLink = window.CURRENT_CITY_SLUG || 'krasnodar';
    const complexPageUrl = firstPropSlug ? `/${citySlugForLink}/zk/${firstPropSlug}` : '';

    header.innerHTML = `
        <div class="flex items-center justify-between mb-3">
            <div>
                ${complexPageUrl
                    ? `<a href="${complexPageUrl}" class="font-bold text-lg text-[#0088CC] hover:underline">${complexName}</a>`
                    : `<h3 class="font-bold text-lg text-gray-800">${complexName}</h3>`
                }
                <p class="text-sm text-gray-500" id="mapDesktopPanelHeaderCount">${
                    (complexName === 'Отфильтрованные объекты' || complexName === 'Свойства в области')
                        ? `${(window._mapCardsTotalFromServer || properties.length).toLocaleString('ru-RU')} объектов`
                        : (() => {
                            const shown = properties.length;
                            const total = totalOverride || shown;
                            if (total > shown) {
                                return `Показано ${shown} из ${total.toLocaleString('ru-RU')} объектов`;
                            }
                            return `${total} ${total === 1 ? 'объект' : total < 5 ? 'объекта' : 'объектов'}`;
                          })()
                }${complexPageUrl ? ` · <a href="${complexPageUrl}" class="text-[#0088CC] hover:underline text-xs">Перейти к ЖК →</a>` : ''}</p>
            </div>
            <button onclick="${(complexName === 'Отфильтрованные объекты' || complexName === 'Свойства в области') ? 'if(typeof resetMapFilters===\'function\')resetMapFilters();else closeMapPanelSelection()' : 'closeMapPanelSelection()'}" class="text-gray-400 hover:text-gray-600 transition" title="${(complexName === 'Отфильтрованные объекты' || complexName === 'Свойства в области') ? 'Сбросить фильтры' : 'Закрыть'}">
                <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path>
                </svg>
            </button>
        </div>
        ${photoHTML}
    `;
    container.appendChild(header);
    
    // ✅ For filtered results use lazy infinite scroll; for ЖК clusters render first batch then lazy-load more
    if (complexName === 'Отфильтрованные объекты' || complexName === 'Свойства в области') {
        // Lazy rendering — loadMoreDesktopCards reads from window.mapAllProperties
        currentDisplayOffset = 0;
        isLoadingMoreCards = false;
        loadMoreDesktopCards();
    } else {
        // Specific ЖК cluster — render first 20 immediately, then load more on scroll
        const BATCH = 20;
        let offset = 0;

        function appendClusterBatch() {
            const slice = properties.slice(offset, offset + BATCH);
            slice.forEach(property => {
                const card = createDesktopPropertyCard(property);
                container.appendChild(card);
            });
            offset += slice.length;

            // If more remain, add a sentinel for intersection observer
            if (offset < properties.length) {
                const sentinel = document.createElement('div');
                sentinel.id = 'clusterScrollSentinel';
                sentinel.style.height = '1px';
                sentinel.className = 'col-span-2';
                container.appendChild(sentinel);

                const obs = new IntersectionObserver(entries => {
                    if (entries[0].isIntersecting) {
                        obs.disconnect();
                        sentinel.remove();
                        appendClusterBatch();
                    }
                }, { root: container.closest('[id]'), threshold: 0.1 });
                obs.observe(sentinel);
            }
        }

        appendClusterBatch();
    }
    
    console.log(`✅ Desktop panel updated with ${properties.length} cards`);
}

// Close panel selection (return to initial aggregated view)
function closeMapPanelSelection() {
    console.log('🗺️ Closing panel selection - returning to aggregated view');
    // Clear cluster-selected flag so boundschange can update the panel again
    window._mapClusterPanelSelected = false;
    // Close any open balloon
    if (fullscreenMapInstance) {
        try { fullscreenMapInstance.balloon && fullscreenMapInstance.balloon.close(); } catch(e) {}
    }
    // Use unified pipeline to rebuild aggregated markers + full cards list
    if (typeof updateMapWithFilters === 'function') {
        updateMapWithFilters();
    }
}

// Image slider functionality for property cards
let imageSliders = new Map();

function _getSliderImages(container) {
    try {
        const raw = container.dataset.images;
        if (!raw) return null;
        return JSON.parse(raw);
    } catch(e) { return null; }
}

// Preload image and return a Promise that resolves when ready (or after timeout)
function _preloadImg(src, timeoutMs) {
    return new Promise(resolve => {
        const p = new Image();
        const done = () => resolve(p);
        if (p.complete && p.naturalWidth > 0) { resolve(p); return; }
        p.onload = done;
        p.onerror = done; // resolve even on error so slider doesn't hang
        p.src = src;
        if (timeoutMs) setTimeout(done, timeoutMs);
    });
}

function startImageSlider(container) {
    const images = _getSliderImages(container);
    if (!images || images.length <= 1) return;
    if (imageSliders.has(container)) return;

    const img = container.querySelector('.main-image');
    const indicator = container.querySelector('.slider-indicator');
    if (!img) return;

    if (indicator) indicator.classList.remove('hidden');

    // Kick off preloading all images simultaneously right away
    const preloadCache = images.map((src, i) => _preloadImg(src, i === 0 ? 500 : 8000));

    let currentIndex = 0;
    let advancing = false;
    let cancelled = false;

    const interval = setInterval(async () => {
        if (cancelled || advancing) return;
        advancing = true;
        const nextIndex = (currentIndex + 1) % images.length;
        // Wait for the next image to be ready, max 3s
        await Promise.race([preloadCache[nextIndex], new Promise(r => setTimeout(r, 3000))]);
        if (!cancelled && imageSliders.has(container)) {
            currentIndex = nextIndex;
            img.src = images[currentIndex];
            if (indicator) indicator.textContent = `${currentIndex + 1}/${images.length}`;
        }
        advancing = false;
    }, 1400);

    imageSliders.set(container, { interval, images, originalImage: images[0], cancel() { cancelled = true; } });
}

function stopImageSlider(container) {
    const sliderData = imageSliders.get(container);
    if (sliderData) {
        clearInterval(sliderData.interval);
        if (sliderData.cancel) sliderData.cancel();
        const img = container.querySelector('.main-image');
        const indicator = container.querySelector('.slider-indicator');
        if (img) img.src = sliderData.originalImage;
        if (indicator) indicator.classList.add('hidden');
        imageSliders.delete(container);
    }
}

function nextSliderImage(container) {
    const images = _getSliderImages(container);
    if (!images || images.length <= 1) return;

    const img = container.querySelector('.main-image');
    const indicator = container.querySelector('.slider-indicator');
    if (!img) return;

    // Find current index by token match
    const currentSrc = img.src;
    let currentIndex = images.findIndex(url => {
        const token = url.split('=').pop();
        return token && currentSrc.includes(token);
    });
    if (currentIndex === -1) currentIndex = 0;

    const nextIndex = (currentIndex + 1) % images.length;
    const nextSrc = images[nextIndex];

    // Show immediately if cached, otherwise wait
    _preloadImg(nextSrc, 4000).then(() => {
        img.src = nextSrc;
        if (indicator) {
            indicator.textContent = `${nextIndex + 1}/${images.length}`;
            indicator.classList.remove('hidden');
        }
    });
    // Preload the one after
    _preloadImg(images[(nextIndex + 1) % images.length], 8000);
}

// ✅ NEW: Set up Intersection Observer for infinite scroll
function initInfiniteScroll() {
    const container = document.getElementById('mapDesktopPropertiesContainer');
    if (!container) return;
    
    // Create sentinel element for scroll detection
    const sentinel = document.createElement('div');
    sentinel.id = 'map-scroll-sentinel';
    sentinel.style.height = '20px';
    sentinel.style.visibility = 'hidden';
    
    const observer = new IntersectionObserver((entries) => {
        if (entries[0].isIntersecting) {
            console.log('📍 Sentinel visible - loading more cards...');
            loadMoreDesktopCards();
            // Re-add sentinel to detect next scroll
            if (container.lastChild && container.lastChild.id !== 'map-scroll-sentinel') {
                container.appendChild(sentinel);
            }
        }
    }, { threshold: 0.1 });
    
    container.appendChild(sentinel);
    observer.observe(sentinel);
    
    console.log('✅ Infinite scroll initialized');
}

// ✅ DISABLED: Map viewport change listener was causing filtered results to disappear
// Only use explicit filters from user, not automatic viewport filtering
function initMapViewportListener() {
    console.log('⚠️ Viewport listener DISABLED - filtered results stay visible until user changes filter');
    // Do nothing - viewport filtering was causing issues
}

// Make filter functions globally available
window.toggleMapRoomFilter = toggleMapRoomFilter;
window.openMapAdvancedFilters = openMapAdvancedFilters;
window.closeMapAdvancedFilters = closeMapAdvancedFilters;
// window.resetMapAdvancedFilters / window.applyMapAdvancedFilters —
// canonical implementations live in templates/properties.html
window.resetMapFilters = resetMapFilters;
window.toggleToolbarRoomFilter = toggleToolbarRoomFilter;
window.updateMapFiltersBadge = updateMapFiltersBadge;
window.startImageSlider = startImageSlider;
window.stopImageSlider = stopImageSlider;
window.nextSliderImage = nextSliderImage;
window.updateDesktopPropertiesPanel = updateDesktopPropertiesPanel;

// ============================================
// 🎯 DRAWING FUNCTIONALITY FOR YANDEX MAPS
// ============================================

let isMapDrawing = false;
let drawnPolygonYandex = null;
let drawingPoints = [];
let drawingMarkers = [];
let drawingPolyline = null;

function enableMapDrawingCIAN() {
    enableMapDrawing();
    const hint = document.getElementById('drawingHintOverlay');
    const drawBtn = document.getElementById('cianDrawBtn');
    const clearBtn = document.getElementById('cianClearBtn');
    if (hint) { hint.style.display = 'flex'; }
    if (drawBtn) { drawBtn.style.background = '#0088CC'; drawBtn.style.borderColor = '#006699'; const svg = drawBtn.querySelector('svg'); if (svg) svg.style.color = 'white'; }
    if (clearBtn) { clearBtn.style.display = 'flex'; }
}

function toggleInfraDropdown(e) {
    if (e) e.stopPropagation();
    const panel = document.getElementById('infraDropdownPanel');
    const chevron = document.getElementById('infraChevron');
    const btn = document.getElementById('infraToggleBtn');
    const isOpen = panel && panel.style.display !== 'none';
    if (isOpen) {
        if (panel) panel.style.display = 'none';
        if (chevron) chevron.style.transform = '';
        if (btn) { btn.style.borderColor = '#e5e7eb'; btn.style.background = '#fff'; }
    } else {
        if (panel) panel.style.display = 'block';
        if (chevron) chevron.style.transform = 'rotate(180deg)';
        if (btn) { btn.style.borderColor = '#0088CC'; btn.style.background = '#f0f9ff'; }
    }
}

document.addEventListener('click', function(e) {
    const wrapper = document.getElementById('infraWrapper');
    if (wrapper && !wrapper.contains(e.target)) {
        const panel = document.getElementById('infraDropdownPanel');
        const chevron = document.getElementById('infraChevron');
        const btn = document.getElementById('infraToggleBtn');
        if (panel && panel.style.display !== 'none') {
            panel.style.display = 'none';
            if (chevron) chevron.style.transform = '';
            if (btn) { btn.style.borderColor = '#e5e7eb'; btn.style.background = '#fff'; }
        }
    }
});

// Export real updateMapWithFilters to window (replaces old client-side stub)
window.updateMapWithFilters = updateMapWithFilters;

var infraActive = {};
var infraLayers = {};
var infraCfg = {
    shops:         { tag: '"shop"',                                   label: 'Магазин',     emoji: '🛒', color: '#f97316' },
    schools:       { tag: '"amenity"="school"',                       label: 'Школа',       emoji: '🏫', color: '#22c55e' },
    kindergartens: { tag: '"amenity"="kindergarten"',                  label: 'Детский сад', emoji: '🧒', color: '#3b82f6' },
    clinics:       { tag: '"amenity"~"clinic|hospital|doctors"',       label: 'Поликлиника', emoji: '🏥', color: '#ef4444' },
    pharmacies:    { tag: '"amenity"="pharmacy"',                      label: 'Аптека',      emoji: '💊', color: '#a855f7' },
    parks:         { tag: '"leisure"="park"',                          label: 'Парк',        emoji: '🌳', color: '#16a34a' },
    fitness:       { tag: '"leisure"~"fitness_centre|sports_centre"',  label: 'Фитнес',      emoji: '🏋️', color: '#1d4ed8' },
    transport:     { tag: '"highway"="bus_stop"',                      label: 'Остановки',   emoji: '🚌', color: '#6b7280' }
};

function createInfraIconLayout(emoji, color) {
    var html = '<div style="width:30px;height:30px;background:' + color + ';border-radius:50%;' +
        'border:2.5px solid white;box-shadow:0 2px 8px rgba(0,0,0,0.35);' +
        'display:flex;align-items:center;justify-content:center;font-size:15px;' +
        'cursor:pointer;transform:translate(-50%,-100%) translateY(-4px);">' + emoji + '</div>';
    return ymaps.templateLayoutFactory.createClass(html);
}

function toggleInfraCategory(category) {
    const btn = document.querySelector(`[data-infra="${category}"]`);
    if (!btn) return;
    if (infraActive[category]) {
        if (infraLayers[category] && fullscreenMapInstance) {
            fullscreenMapInstance.geoObjects.remove(infraLayers[category]);
        }
        delete infraLayers[category];
        delete infraActive[category];
        btn.style.borderColor = '#e5e7eb';
        btn.style.background = '#fff';
        btn.style.color = '#374151';
    } else {
        infraActive[category] = true;
        btn.style.borderColor = '#0088CC';
        btn.style.background = '#e0f2fe';
        btn.style.color = '#0088CC';
        loadInfraLayer(category);
    }
}

function loadInfraLayer(category, mapInstance, layersStore, activeStore, btnSelector) {
    const map = mapInstance || fullscreenMapInstance;
    const layers = layersStore || infraLayers;
    const active = activeStore || infraActive;
    if (!map || typeof ymaps === 'undefined') return;
    const cfg = infraCfg[category];
    const bounds = map.getBounds();
    const [minLat, minLng] = bounds[0];
    const [maxLat, maxLng] = bounds[1];
    const selector = btnSelector || `[data-infra="${category}"]`;
    const btn = document.querySelector(selector);
    if (btn) btn.style.opacity = '0.5';
    const query = `[out:json][timeout:25][bbox:${minLat},${minLng},${maxLat},${maxLng}];(node[${cfg.tag}];way[${cfg.tag}];);out center 100;`;
    const url = `https://overpass-api.de/api/interpreter?data=${encodeURIComponent(query)}`;
    fetch(url)
        .then(r => r.json())
        .then(function(data) {
            const col = new ymaps.GeoObjectCollection();
            const iconLayout = cfg.emoji ? createInfraIconLayout(cfg.emoji, cfg.color) : null;
            (data.elements || []).forEach(function(el) {
                const lat = el.lat || (el.center && el.center.lat);
                const lon = el.lon || (el.center && el.center.lon);
                if (!lat || !lon) return;
                const name = (el.tags && (el.tags.name || el.tags['name:ru'])) || cfg.label;
                const opts = iconLayout
                    ? { iconLayout: iconLayout, iconShape: { type: 'Circle', coordinates: [0, 0], radius: 16 } }
                    : { preset: cfg.preset || 'islands#orangeCircleDotIcon' };
                col.add(new ymaps.Placemark([lat, lon], { hintContent: name }, opts));
            });
            if (layers[category]) { try { map.geoObjects.remove(layers[category]); } catch(e){} }
            layers[category] = col;
            map.geoObjects.add(col);
            if (btn) btn.style.opacity = '1';
            console.log(`✅ Overpass: ${(data.elements||[]).length} ${category} markers`);
        })
        .catch(function(e) {
            console.warn('Overpass API error:', e);
            if (btn) btn.style.opacity = '1';
        });
}

function enableMapDrawing() {
    if (!fullscreenMapInstance) {
        console.warn('⚠️ Map not initialized');
        return;
    }
    
    isMapDrawing = true;
    console.log('🎨 Drawing mode enabled');
    
    // DISABLE map dragging so clicks work for drawing
    fullscreenMapInstance.container.getElement().style.cursor = 'crosshair';
    
    // Try to disable dragging behavior
    try {
        // In Yandex Maps 3.x, dragging is controlled through behaviors
        const behaviors = fullscreenMapInstance.behaviors.get('drag');
        if (behaviors) {
            behaviors.disable();
        }
    } catch (e) {
        console.log('ℹ️ Could not disable drag behavior (expected)');
    }
    
    // Update button state
    const drawBtn = document.getElementById('mapDrawAreaBtn');
    const clearBtn = document.getElementById('mapClearAreaBtn');
    if (drawBtn) {
        drawBtn.classList.add('bg-orange-500', 'text-white', '!border-orange-500');
        drawBtn.classList.remove('border-gray-300', 'hover:border-blue-600');
        drawBtn.innerHTML = '<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4"></path></svg>Кликните точки на карте';
    }
    if (clearBtn) {
        clearBtn.classList.remove('hidden');
    }
    
    // Clear previous drawing
    drawingPoints = [];
    drawingMarkers = [];
    if (drawingPolyline) {
        fullscreenMapInstance.geoObjects.remove(drawingPolyline);
    }
    
    // Drawing event handler is already added in openFullscreenMap() when map is initialized

    // Also activate CIAN hint overlay if it exists (for desktop map)
    const hintEl = document.getElementById('drawingHintOverlay');
    const cianDraw = document.getElementById('cianDrawBtn');
    const cianClear = document.getElementById('cianClearBtn');
    if (hintEl) hintEl.style.display = 'flex';
    if (cianDraw) { cianDraw.style.background = '#0088CC'; cianDraw.style.borderColor = '#006699'; const svg = cianDraw.querySelector('svg'); if (svg) svg.style.color = 'white'; }
    if (cianClear) cianClear.style.display = 'flex';
    // Reset hint to step 1
    const hintStep = document.getElementById('drawingHintStep');
    const hintText = document.getElementById('drawingHintText');
    if (hintStep) { hintStep.textContent = '1'; hintStep.style.background = '#0088CC'; }
    if (hintText) hintText.textContent = 'Кликните на карту — поставьте первую точку';
}

function finishMapDrawing() {
    if (drawingPoints.length < 3) {
        console.warn('⚠️ Need at least 3 points to create polygon');
        return;
    }
    
    console.log('🎨 Finishing drawing with', drawingPoints.length, 'points');
    
    // Remove temporary markers and polyline
    drawingMarkers.forEach(marker => {
        fullscreenMapInstance.geoObjects.remove(marker);
    });
    drawingMarkers = [];
    if (drawingPolyline) {
        fullscreenMapInstance.geoObjects.remove(drawingPolyline);
        drawingPolyline = null;
    }
    
    // Create final polygon
    if (drawnPolygonYandex) {
        fullscreenMapInstance.geoObjects.remove(drawnPolygonYandex);
    }
    
    // Close the polygon by adding first point at end
    const closedPoints = [...drawingPoints];
    if (closedPoints[0] !== closedPoints[closedPoints.length - 1]) {
        closedPoints.push(closedPoints[0]);
    }
    
    drawnPolygonYandex = new ymaps.Polygon([closedPoints], {}, {
        fillColor: '#ff6b3540',
        strokeColor: '#ff6b35',
        strokeWidth: 3,
        strokeOpacity: 0.8
    });
    
    fullscreenMapInstance.geoObjects.add(drawnPolygonYandex);
    
    // Reset drawing state
    isMapDrawing = false;
    
    // RE-ENABLE map dragging
    fullscreenMapInstance.container.getElement().style.cursor = 'grab';
    try {
        const behaviors = fullscreenMapInstance.behaviors.get('drag');
        if (behaviors) {
            behaviors.enable();
        }
    } catch (e) {
        console.log('ℹ️ Could not re-enable drag behavior');
    }
    
    // 🎯 Update buttons to show "Clear" instead of "Draw"
    const drawBtn = document.getElementById('mapDrawAreaBtn');
    const clearBtn = document.getElementById('mapClearAreaBtn');
    if (drawBtn) {
        drawBtn.classList.remove('bg-orange-500', 'text-white', '!border-orange-500');
        drawBtn.classList.add('border-gray-300', 'hover:border-blue-600');
        drawBtn.innerHTML = '<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4"></path></svg>Выделить область';
        drawBtn.onclick = function() {
            enableMapDrawing();
        };
    }
    if (clearBtn) {
        clearBtn.classList.remove('hidden');
        clearBtn.innerHTML = '<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path></svg>Очистить';
        clearBtn.onclick = function() {
            clearMapDrawnArea();
        };
    }
    
    // Hide drawing hint overlay
    const hint = document.getElementById('drawingHintOverlay');
    if (hint) hint.style.display = 'none';
    
    // Mark polygon filter as active — prevents boundschange from wiping results
    window.polygonFilterActive = true;
    
    // Filter properties by polygon — backend first, fallback to client-side
    filterPropertiesByPolygonBackend(drawingPoints).catch(() => {
        filterPropertiesByPolygonYandex();
    });
    console.log('✅ Polygon completed and properties filtered');
}

function clearMapDrawnArea() {
    console.log('🗑️ Clearing drawn area');
    
    // Remove polygon
    if (drawnPolygonYandex) {
        fullscreenMapInstance.geoObjects.remove(drawnPolygonYandex);
        drawnPolygonYandex = null;
    }
    
    // Reset drawing state
    isMapDrawing = false;
    drawingPoints = [];
    drawingMarkers = [];
    if (drawingPolyline) {
        fullscreenMapInstance.geoObjects.remove(drawingPolyline);
        drawingPolyline = null;
    }
    
    // RE-ENABLE map dragging
    fullscreenMapInstance.container.getElement().style.cursor = 'grab';
    try {
        const behaviors = fullscreenMapInstance.behaviors.get('drag');
        if (behaviors) {
            behaviors.enable();
        }
    } catch (e) {
        console.log('ℹ️ Could not re-enable drag behavior');
    }
    
    // 🎯 Update buttons - HIDE clear button and SHOW draw button
    const drawBtn = document.getElementById('mapDrawAreaBtn');
    const clearBtn = document.getElementById('mapClearAreaBtn');
    if (drawBtn) {
        drawBtn.classList.remove('bg-orange-500', 'text-white', '!border-orange-500');
        drawBtn.classList.add('border-gray-300', 'hover:border-blue-600');
        drawBtn.innerHTML = '<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4"></path></svg>Выделить область';
    }
    if (clearBtn) {
        clearBtn.classList.add('hidden');
    }
    // Reset CIAN overlay buttons
    const hint = document.getElementById('drawingHintOverlay');
    const cianDraw = document.getElementById('cianDrawBtn');
    const cianClear = document.getElementById('cianClearBtn');
    if (hint) hint.style.display = 'none';
    if (cianDraw) { cianDraw.style.background = ''; cianDraw.style.borderColor = ''; const svg = cianDraw.querySelector('svg'); if (svg) svg.style.color = ''; }
    if (cianClear) cianClear.style.display = 'none';
    
    // Clear polygon filter flag so boundschange reloads work again
    window.polygonFilterActive = false;
    
    // Return to all properties — restore aggregated view (same as initial load)
    if (window.fullscreenRenderAggregated) {
        // Re-fetch aggregated data with current filters so we get fresh data
        const params = new URLSearchParams();
        const cityId = window.currentCityId;
        if (cityId) params.set('city_id', cityId);
        if (window.mapFilters) {
            if (window.mapFilters.rooms && window.mapFilters.rooms.length) window.mapFilters.rooms.forEach(r => params.append('rooms', r));
            if (window.mapFilters.price_min) params.set('price_min', window.mapFilters.price_min);
            if (window.mapFilters.price_max) params.set('price_max', window.mapFilters.price_max);
            if (window.mapFilters.area_min) params.set('area_min', window.mapFilters.area_min);
            if (window.mapFilters.area_max) params.set('area_max', window.mapFilters.area_max);
        }
        fetch(`/api/map-properties/aggregated?${params.toString()}`, { credentials: 'same-origin' })
            .then(r => r.json())
            .then(d => {
                if (d.success && d.points && d.points.length > 0) {
                    window.fullscreenRenderAggregated(d.points, 'reset');
                } else if (window.mapInitialAggregated && window.mapInitialAggregated.length > 0) {
                    window.fullscreenRenderAggregated(window.mapInitialAggregated, 'reset-cached');
                }
                _restoreLeftPanel();
            })
            .catch(() => {
                if (window.mapInitialAggregated && window.mapInitialAggregated.length > 0) {
                    window.fullscreenRenderAggregated(window.mapInitialAggregated, 'reset-cached');
                }
                _restoreLeftPanel();
            });
    } else {
        updateMapWithFilters();
    }
}

function _restoreLeftPanel() {
    const propsContainer = document.getElementById('mapDesktopPropertiesContainer');
    if (!propsContainer) return;
    const cityId = window.currentCityId;
    const params = new URLSearchParams();
    if (cityId) params.set('city_id', cityId);
    params.set('per_page', '20');
    params.set('page', '1');
    propsContainer.innerHTML = '';
    for (let i = 0; i < 4; i++) {
        const s = document.createElement('div');
        s.className = 'animate-pulse bg-gray-100 rounded-lg h-56';
        propsContainer.appendChild(s);
    }
    fetch(`/api/map-properties?${params.toString()}`, { credentials: 'same-origin' })
        .then(r => r.json())
        .then(d => {
            propsContainer.innerHTML = '';
            if (!d.success || !d.properties) return;
            window.initialMapProperties = d.properties;
            const sorted = sortMapPropertiesArray(d.properties);
            sorted.forEach(p => {
                try { propsContainer.appendChild(createDesktopPropertyCard(p)); } catch(e) {}
            });
            const panelCountEl = document.getElementById('mapDesktopPanelCount');
            if (panelCountEl) panelCountEl.textContent = `${d.total || d.properties.length} объектов`;
        })
        .catch(() => { propsContainer.innerHTML = ''; });
}

async function filterPropertiesByPolygonBackend(polygon) {
    const cityId = window.currentCityId || null;
    const _csrfToken = document.querySelector('meta[name="csrf-token"]')?.content || '';
    const resp = await fetch('/api/properties/polygon', {
        method: 'POST',
        headers: {'Content-Type': 'application/json', 'X-CSRFToken': _csrfToken},
        credentials: 'same-origin',
        body: JSON.stringify({ polygon: polygon, city_id: cityId })
    });
    if (!resp.ok) throw new Error(`Backend polygon error: ${resp.status}`);
    const data = await resp.json();
    console.log(`🎯 Backend polygon: ${data.count} properties found`);

    // Update counter
    const counter = document.getElementById('mapObjectsCount');
    const desktopCounter = document.getElementById('mapObjectsCountDesktop');
    if (counter) counter.textContent = data.count;
    if (desktopCounter) desktopCounter.textContent = data.count;

    // Map image field (backend returns 'image', panel expects 'main_image')
    data.properties = data.properties.map(p => ({ ...p, main_image: p.image || p.main_image }));

    const container = document.getElementById('mapDesktopPropertiesContainer');

    // Helper: clear map but keep infra layers on top
    function _clearKeepInfra() {
        fullscreenMapInstance.geoObjects.removeAll();
        if (typeof infraLayers !== 'undefined') {
            Object.keys(infraLayers).forEach(function(cat) {
                try { if (infraLayers[cat]) fullscreenMapInstance.geoObjects.add(infraLayers[cat]); } catch(e) {}
            });
        }
    }

    if (data.properties.length > 0) {
        // Backend found results — clear map and show only polygon results
        _clearKeepInfra();
        if (container) container.innerHTML = '';
        updateDesktopPropertiesPanel(data.properties, 'Объекты в области');
        const grouped = groupPropertiesByCoords(data.properties);
        grouped.forEach(group => {
            try {
                fullscreenMapInstance.geoObjects.add(createEnhancedYandexMarker(group.properties));
            } catch(e) { console.error('Marker error:', e); }
        });
        // Re-draw polygon outline on top
        if (drawnPolygonYandex) fullscreenMapInstance.geoObjects.add(drawnPolygonYandex);
    } else {
        // Backend found 0 individual properties — ask backend for aggregated building points in polygon
        // (server-side ray-casting on grouped data = consistent with what's visible on map)
        console.log('⚡ Backend returned 0 properties, querying aggregated polygon endpoint...');

        let aggInArea = [];
        try {
            const aggResp = await fetch('/api/properties/polygon-aggregated', {
                method: 'POST',
                headers: {'Content-Type': 'application/json', 'X-CSRFToken': _csrfToken},
                credentials: 'same-origin',
                body: JSON.stringify({ polygon: polygon, city_id: window.currentCityId || null })
            });
            const aggData = await aggResp.json();
            aggInArea = (aggData.success && aggData.points && aggData.points.length > 0) ? aggData.points : [];
            console.log(`📍 Aggregated polygon: ${aggInArea.length} building points inside polygon`);
        } catch(fetchErr) {
            console.warn('⚠️ Aggregated polygon fetch failed', fetchErr);
            aggInArea = [];
        }

        if (aggInArea.length > 0) {
            // Show only matched buildings on map
            if (window.fullscreenRenderAggregated) {
                window.fullscreenRenderAggregated(aggInArea, 'polygon-filtered');
            }
            // Re-draw polygon outline (renderAggregatedPoints clears the map)
            if (drawnPolygonYandex) {
                try { fullscreenMapInstance.geoObjects.add(drawnPolygonYandex); } catch(e) {}
            }
            // Populate left panel with building summary cards
            const totalApts = aggInArea.reduce(function(s, pt) { return s + (pt.count || 0); }, 0);
            const cnt = document.getElementById('mapObjectsCount');
            const cntD = document.getElementById('mapObjectsCountDesktop');
            if (cnt) cnt.textContent = totalApts;
            if (cntD) cntD.textContent = totalApts;
            if (container) {
                container.innerHTML = '';
                const hdr = document.createElement('div');
                hdr.style.cssText = 'margin-bottom:12px;padding-bottom:12px;border-bottom:1px solid #e5e7eb;position:sticky;top:0;background:#fff;z-index:10;grid-column:1/-1';
                hdr.innerHTML = `<h3 style="font-weight:700;font-size:1.1rem;color:#1f2937">Объекты в области</h3>
                    <p style="font-size:.8rem;color:#6b7280">${totalApts} квартир в ${aggInArea.length} домах</p>`;
                container.appendChild(hdr);
                aggInArea.forEach(function(pt) {
                    const priceStr = pt.min_price
                        ? 'от ' + (Math.round(pt.min_price / 100000) / 10).toFixed(1) + ' млн ₽'
                        : 'Цена не указана';
                    const card = document.createElement('div');
                    card.style.cssText = 'background:#fff;border:1px solid #e5e7eb;border-radius:12px;padding:14px;cursor:pointer;transition:border-color .15s,box-shadow .15s';
                    card.onmouseenter = function() { this.style.borderColor = '#0088CC'; this.style.boxShadow = '0 2px 8px rgba(0,136,204,.15)'; };
                    card.onmouseleave = function() { this.style.borderColor = '#e5e7eb'; this.style.boxShadow = ''; };
                    card.innerHTML = `<div style="font-weight:600;font-size:.9rem;color:#1f2937;margin-bottom:4px">${pt.complex_name || 'ЖК'}</div>
                        <div style="font-size:.75rem;color:#9ca3af;margin-bottom:10px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${pt.address || ''}</div>
                        <div style="display:flex;align-items:center;justify-content:space-between">
                            <span style="color:#0088CC;font-weight:700;font-size:.9rem">${priceStr}</span>
                            <span style="font-size:.75rem;background:#eff6ff;color:#1d4ed8;padding:3px 10px;border-radius:99px">${pt.count} кв.</span>
                        </div>`;
                    if (pt.lat && pt.lng) {
                        card.onclick = function() {
                            try { fullscreenMapInstance.panTo([pt.lat, pt.lng]); } catch(e) {}
                        };
                    }
                    container.appendChild(card);
                });
            }
        } else {
            // Truly no objects in this area — keep existing markers, just show message in panel
            console.log('ℹ️ No objects in drawn area — keeping existing map markers');
            if (container) {
                container.innerHTML = `<div style="display:flex;flex-direction:column;align-items:center;justify-content:center;height:100%;padding:32px;text-align:center;color:#6b7280;">
                    <svg style="width:48px;height:48px;margin-bottom:16px;color:#d1d5db;" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M9 20l-5.447-2.724A1 1 0 013 16.382V5.618a1 1 0 011.447-.894L9 7m0 13l6-3m-6 3V7m6 10l4.553 2.276A1 1 0 0021 18.382V7.618a1 1 0 00-.553-.894L15 4m0 13V4m0 0L9 7"/>
                    </svg>
                    <p style="font-size:15px;font-weight:600;margin-bottom:6px;">В этой области нет объектов</p>
                    <p style="font-size:13px;">Попробуйте выделить другую область или <a onclick="clearMapDrawnArea()" style="color:#0088CC;cursor:pointer;text-decoration:underline;">сбросить</a></p>
                </div>`;
            }
        }
        // Re-draw polygon outline (on top of existing/new markers)
        if (drawnPolygonYandex) fullscreenMapInstance.geoObjects.add(drawnPolygonYandex);
    }
}

function filterPropertiesByPolygonYandex() {
    if (!drawnPolygonYandex || !window.initialMapProperties) {
        console.warn('⚠️ No polygon or properties');
        return;
    }
    
    console.log(`🔍🔍🔍 POLYGON FILTERING START`);
    console.log(`📊 Total properties: ${window.initialMapProperties.length}`);
    console.log(`📍 Drawing points (${drawingPoints.length}):`, drawingPoints.slice(0, 3), '...');
    
    // Get polygon bounds
    const bounds = drawnPolygonYandex.geometry.getBounds();
    console.log(`📦 Polygon bounds: SW[${bounds[0][0].toFixed(4)}, ${bounds[0][1].toFixed(4)}] to NE[${bounds[1][0].toFixed(4)}, ${bounds[1][1].toFixed(4)}]`);
    
    // Filter properties inside polygon
    let totalChecked = 0;
    let totalInBounds = 0;
    const propertiesInsidePolygon = window.initialMapProperties.filter(prop => {
        totalChecked++;
        
        if (!prop.coordinates) {
            return false;
        }
        
        const lat = prop.coordinates.lat;
        const lng = prop.coordinates.lng;
        
        // Check if inside polygon bounds (simple check)
        if (lat < bounds[0][0] || lat > bounds[1][0] ||
            lng < bounds[0][1] || lng > bounds[1][1]) {
            return false;
        }
        
        totalInBounds++;
        
        // Point-in-polygon test
        const inside = isPointInPolygon([lat, lng], drawingPoints);
        if (inside) {
            console.log(`✅ ID:${prop.id} INSIDE at [${lat.toFixed(4)}, ${lng.toFixed(4)}]`);
        } else {
            // Log first few failures for debugging
            if (totalInBounds <= 3) {
                console.log(`❌ ID:${prop.id} OUTSIDE at [${lat.toFixed(4)}, ${lng.toFixed(4)}]`);
            }
        }
        return inside;
    });
    
    console.log(`🔍🔍🔍 FILTERING COMPLETE: Found ${propertiesInsidePolygon.length}/${totalChecked} properties (${totalInBounds} in bounds)`);
    
    const container = document.getElementById('mapDesktopPropertiesContainer');
    const counter = document.getElementById('mapObjectsCount');
    const desktopCounter = document.getElementById('mapObjectsCountDesktop');
    if (counter) counter.textContent = propertiesInsidePolygon.length;
    if (desktopCounter) desktopCounter.textContent = propertiesInsidePolygon.length;

    if (propertiesInsidePolygon.length === 0) {
        // No results — keep existing markers on map, just show empty state in panel
        console.warn('⚠️ No properties found inside polygon — keeping existing map markers');
        if (container) {
            container.innerHTML = `<div style="display:flex;flex-direction:column;align-items:center;justify-content:center;height:100%;padding:32px;text-align:center;color:#6b7280;">
                <svg style="width:48px;height:48px;margin-bottom:16px;color:#d1d5db;" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M9 20l-5.447-2.724A1 1 0 013 16.382V5.618a1 1 0 011.447-.894L9 7m0 13l6-3m-6 3V7m6 10l4.553 2.276A1 1 0 0021 18.382V7.618a1 1 0 00-.553-.894L15 4m0 13V4m0 0L9 7"/>
                </svg>
                <p style="font-size:15px;font-weight:600;margin-bottom:6px;">В этой области нет объектов</p>
                <p style="font-size:13px;">Попробуйте выделить другую область или <a onclick="clearMapDrawnArea()" style="color:#0088CC;cursor:pointer;text-decoration:underline;">сбросить</a></p>
            </div>`;
        }
        // Re-add polygon outline on top of existing markers
        if (drawnPolygonYandex) fullscreenMapInstance.geoObjects.add(drawnPolygonYandex);
        return;
    }

    // Results found — clear map and show polygon-filtered markers
    if (container) container.innerHTML = '';
    fullscreenMapInstance.geoObjects.removeAll();
    // Re-add infra layers after clearing
    if (typeof infraLayers !== 'undefined') {
        Object.keys(infraLayers).forEach(function(cat) {
            try { if (infraLayers[cat]) fullscreenMapInstance.geoObjects.add(infraLayers[cat]); } catch(e) {}
        });
    }
    updateDesktopPropertiesPanel(propertiesInsidePolygon, 'Свойства в области');
    // Polygon outline first
    if (drawnPolygonYandex) fullscreenMapInstance.geoObjects.add(drawnPolygonYandex);
    // Add markers for filtered properties
    const grouped = groupPropertiesByCoords(propertiesInsidePolygon);
    grouped.forEach(group => {
        try {
            fullscreenMapInstance.geoObjects.add(createEnhancedYandexMarker(group.properties));
        } catch (error) {
            console.error('❌ Error creating marker:', error);
        }
    });
}

function isPointInPolygon(point, polygonPoints) {
    const [lat, lng] = point;  // [latitude, longitude]
    let inside = false;
    
    // 🎯 Ray casting algorithm for point-in-polygon
    for (let i = 0, j = polygonPoints.length - 1; i < polygonPoints.length; j = i++) {
        const [lat1, lng1] = polygonPoints[i];
        const [lat2, lng2] = polygonPoints[j];
        
        // Check if ray crosses polygon edge
        const intersect = ((lng1 > lng) !== (lng2 > lng)) &&
            (lat < (lat2 - lat1) * (lng - lng1) / (lng2 - lng1) + lat1);
        if (intersect) inside = !inside;
    }
    
    return inside;
}

// Make functions globally available
window.enableMapDrawing = enableMapDrawing;
window.clearMapDrawnArea = clearMapDrawnArea;
window.closeMapPanelSelection = closeMapPanelSelection;
window.loadMoreDesktopCards = loadMoreDesktopCards;
window.updateDesktopPanelByViewport = updateDesktopPanelByViewport;
window.initInfiniteScroll = initInfiniteScroll;
window.initMapViewportListener = initMapViewportListener;

// Add CSS for highlighted cards and slider animations
const styleSheet = document.createElement('style');
styleSheet.textContent = `
    .highlighted-card {
        background-color: #f0f7ff !important;
        border-color: #0088CC !important;
        box-shadow: 0 0 12px rgba(0, 136, 204, 0.3) !important;
        transform: translateY(-2px);
        transition: all 0.2s ease;
    }
    
    .image-slider-container {
        position: relative;
        width: 100%;
        overflow: hidden;
    }
    
    .image-slider-container img {
        width: 100%;
        height: auto;
        display: block;
    }
    
    .slider-indicator {
        position: absolute;
        bottom: 8px;
        right: 8px;
        background: rgba(0, 0, 0, 0.6);
        color: white;
        padding: 4px 8px;
        border-radius: 4px;
        font-size: 11px;
        font-weight: bold;
    }
`;
document.head.appendChild(styleSheet);

console.log('✅ Map filters module loaded');



// ✅ Display active filters on the map
function displayMapActiveFilters() {
    const container = document.getElementById('mapActiveFiltersContainer');
    const filtersList = document.getElementById('mapActiveFiltersList');
    
    if (!container || !filtersList) return;
    
    const filters = [];
    
    // Collect quick room filters
    const quickRooms = document.querySelectorAll('button.quick-room-chip.active');
    quickRooms.forEach(btn => {
        const label = btn.textContent.trim();
        filters.push({ text: `Комнаты: ${label}`, type: 'room' });
    });
    
    // Collect advanced filters
    if (window.mapFilters) {
        // Object class filter
        if (window.mapFilters.object_classes && window.mapFilters.object_classes.length > 0) {
            filters.push({ text: `Класс: ${window.mapFilters.object_classes.join(', ')}`, type: 'class' });
        }
        
        // Completion year filter
        if (window.mapFilters.completion && window.mapFilters.completion.length > 0) {
            filters.push({ text: `Год: ${window.mapFilters.completion.join(', ')}`, type: 'year' });
        }
        
        // Building status filter
        if (window.mapFilters.building_status && window.mapFilters.building_status.length > 0) {
            const statusLabels = window.mapFilters.building_status.map(s => 
                s === 'delivered' ? 'Сдан' : s === 'under_construction' ? 'Строится' : s
            );
            filters.push({ text: `Статус: ${statusLabels.join(', ')}`, type: 'status' });
        }
        
        // Price filter
        if ((window.mapFilters.price_min || window.mapFilters.price_max) && 
            (window.mapFilters.price_min || window.mapFilters.price_max)) {
            let priceText = 'Цена: ';
            if (window.mapFilters.price_min) priceText += `от ${window.mapFilters.price_min}`;
            if (window.mapFilters.price_max) priceText += ` до ${window.mapFilters.price_max}`;
            filters.push({ text: priceText, type: 'price' });
        }

        // Rooms filter
        if (window.mapFilters.rooms && window.mapFilters.rooms.length > 0) {
            const roomLabels = window.mapFilters.rooms.map(r => r === 0 ? 'Студия' : `${r}к`);
            filters.push({ text: `Комнат: ${roomLabels.join(', ')}`, type: 'rooms' });
        }

        // Developers filter
        if (window.mapFilters.developers && window.mapFilters.developers.length > 0) {
            filters.push({ text: `Застройщик: ${window.mapFilters.developers.join(', ')}`, type: 'developer' });
        }

        // Districts — individual dismissable chips per slug
        if (window.mapFilters.districts && window.mapFilters.districts.length > 0) {
            window.mapFilters.districts.forEach(function(slug) {
                const name = (window.districtNamesMap && window.districtNamesMap[slug]) || slug.replace(/-/g, ' ');
                filters.push({ text: `📍 ${name}`, type: 'district_slug', _slug: slug });
            });
        }

        // Search text filter
        if (window.mapFilters.search) {
            const sText = window.mapFilters.search.length > 25
                ? window.mapFilters.search.slice(0, 25) + '…'
                : window.mapFilters.search;
            filters.push({ text: `Поиск: ${sText}`, type: 'search' });
        }
    }
    
    // Update display
    if (filters.length === 0) {
        container.classList.add('hidden');
        filtersList.innerHTML = '';
        // Hide counter
        const counter = document.getElementById('mapActiveFiltersCount');
        if (counter) counter.classList.add('hidden');
    } else {
        container.classList.remove('hidden');
        filtersList.innerHTML = filters.map(function(f) {
            const onclickStr = f.type === 'district_slug'
                ? `clearMapFilter('district_slug','${(f._slug||'').replace(/'/g,"\\'")}')` 
                : `clearMapFilter('${f.type}')`;
            return `<span class="bg-white border border-blue-300 text-blue-700 px-2 py-1 rounded-full flex items-center gap-1 text-xs font-medium">
                ${f.text}
                <button onclick="${onclickStr}" class="ml-1 text-blue-400 hover:text-blue-600 hover:bg-blue-100 rounded-full w-4 h-4 flex items-center justify-center leading-none">×</button>
            </span>`;
        }).join('');
        
        // Show counter with count
        const counter = document.getElementById('mapActiveFiltersCount');
        if (counter) {
            counter.textContent = filters.length;
            counter.classList.remove('hidden');
        }
    }
}

// ✅ Clear specific filter — clears in-memory state, DOM widgets, AND URL
function clearMapFilter(type) {
    const _url = new URL(window.location.href);
    const _delAll = function(keys) {
        keys.forEach(function(k){ _url.searchParams.delete(k); });
    };

    if (!window.mapFilters) window.mapFilters = {};

    if (type === 'room' || type === 'rooms') {
        window.mapFilters.rooms = [];
        document.querySelectorAll('[data-quick-room],[data-toolbar-room],[data-map-room-filter],button.quick-room-chip,button.toolbar-room-chip').forEach(el => {
            el.classList.remove('map-chip-active', 'active', 'bg-[#0088CC]', 'text-white', 'border-[#0088CC]');
            el.classList.add('border-gray-300');
        });
        // ✅ Also uncheck modal chips and repaint them
        document.querySelectorAll('#mapAdvancedFiltersModal [data-map-filter="rooms"]').forEach(cb => {
            cb.checked = false;
            if (typeof window._paintMapChip === 'function') window._paintMapChip(cb);
        });
        _delAll(['rooms']);
    }
    if (type === 'class') {
        window.mapFilters.object_classes = [];
        document.querySelectorAll('[data-map-filter="object_class"]').forEach(cb => cb.checked = false);
        _delAll(['object_class', 'object_classes']);
    }
    if (type === 'year') {
        window.mapFilters.completion = [];
        document.querySelectorAll('[data-map-filter="completion"]').forEach(cb => cb.checked = false);
        _delAll(['completion']);
    }
    if (type === 'status') {
        window.mapFilters.building_status = [];
        document.querySelectorAll('[data-map-filter="building_status"]').forEach(cb => cb.checked = false);
        _delAll(['building_status']);
    }
    if (type === 'price') {
        window.mapFilters.price_min = '';
        window.mapFilters.price_max = '';
        ['mapPriceFrom','mapPriceTo','quickPriceFrom','quickPriceTo','priceFrom','priceTo'].forEach(function(id){
            var el = document.getElementById(id);
            if (el) el.value = '';
        });
        _delAll(['price_min','price_max']);
    }
    if (type === 'area') {
        window.mapFilters.area_min = '';
        window.mapFilters.area_max = '';
        ['mapAreaFrom','mapAreaTo','quickAreaFrom','quickAreaTo','areaFrom','areaTo'].forEach(function(id){
            var el = document.getElementById(id);
            if (el) el.value = '';
        });
        _delAll(['area_min','area_max']);
    }
    if (type === 'floor') {
        window.mapFilters.floor_min = '';
        window.mapFilters.floor_max = '';
        ['mapFloorFrom','mapFloorTo','floorFrom','floorTo'].forEach(function(id){
            var el = document.getElementById(id);
            if (el) el.value = '';
        });
        _delAll(['floor_min','floor_max']);
    }
    if (type === 'developer') {
        window.mapFilters.developers = [];
        document.querySelectorAll('[data-map-filter="developer"]').forEach(cb => cb.checked = false);
        _delAll(['developer','developers']);
    }
    if (type === 'search') {
        window.mapFilters.search = '';
        const mapSearchInput = document.getElementById('mapSearchInput');
        if (mapSearchInput) mapSearchInput.value = '';
        _delAll(['search']);
    }
    if (type === 'district_slug' && value) {
        if (window.mapFilters.districts) {
            window.mapFilters.districts = window.mapFilters.districts.filter(function(d){ return d !== value; });
        }
        _delAll(['districts', 'districts[]']);
        (window.mapFilters.districts || []).forEach(function(d){ _url.searchParams.append('districts', d); });
    }

    // Always strip page (results reset to first page)
    _url.searchParams.delete('page');
    try { history.replaceState(null, '', _url.toString()); } catch(e) {}

    if (typeof updateMapWithFilters === 'function') {
        updateMapWithFilters();
    }
    updateMapFiltersBadge();
    if (typeof displayMapActiveFilters === 'function') displayMapActiveFilters();
    if (typeof updateFiltersCount === 'function') updateFiltersCount();
}

// Export function
window.displayMapActiveFilters = displayMapActiveFilters;
window.clearMapFilter = clearMapFilter;

// ✅ Function to reload mini-map with current URL filters
window.reloadMiniMapWithFilters = function() {
    if (!miniPropertiesMapInstance) {
        console.log('🗺️ Mini-map not initialized yet, skipping reload');
        return;
    }
    
    // Clear existing markers
    miniPropertiesMapInstance.geoObjects.removeAll();
    
    // Get current filter params from URL
    const miniMapParams = getMiniMapFilterParams();
    console.log('🔄 Reloading mini-map with filters:', miniMapParams || '(none)');
    
    fetch('/api/mini-map/properties' + (miniMapParams ? '?' + miniMapParams : ''), {
        credentials: 'same-origin'
    })
        .then(response => response.json())
        .then(data => {
            if (data.success && data.coordinates && data.coordinates.length > 0) {
                console.log(`✅ Reloaded ${data.count} property coordinates for mini-map`);
                
                const isMob = isMobileDevice();
                const coordsToRender = isMob ? data.coordinates.slice(0, 300) : data.coordinates;

                // Используем те же стили кластера и точки, что и при первоначальной загрузке
                const clusterLayout = ymaps.templateLayoutFactory.createClass(
                    '<div style="background:#0088CC;color:#fff;border-radius:50%;width:28px;height:28px;display:flex;align-items:center;justify-content:center;font-weight:700;font-size:11px;border:2px solid #fff;box-shadow:0 2px 8px rgba(0,136,204,0.4);">{{ properties.geoObjects.length }}</div>'
                );
                const dotLayout = ymaps.templateLayoutFactory.createClass(
                    '<div style="width:9px;height:9px;background:#0088CC;border-radius:50%;border:2px solid #fff;box-shadow:0 1px 4px rgba(0,136,204,0.4);"></div>'
                );
                const reloadClusterer = new ymaps.Clusterer({
                    clusterIconLayout: clusterLayout,
                    clusterIconShape: { type: 'Circle', coordinates: [14, 14], radius: 14 },
                    gridSize: isMob ? 80 : 50,
                    groupByCoordinates: false
                });
                const placemarks = coordsToRender.map(c => {
                    const pm = new ymaps.Placemark([c.lat, c.lng], {}, {
                        iconLayout: dotLayout,
                        iconShape: { type: 'Circle', coordinates: [4, 4], radius: 4 }
                    });
                    pm.events.add('click', function(e) {
                        e.stopPropagation();
                        if (typeof handleMapClick === 'function') handleMapClick();
                    });
                    return pm;
                });
                reloadClusterer.add(placemarks);
                miniPropertiesMapInstance.geoObjects.add(reloadClusterer);
                reloadClusterer.events.add('click', function() { if (typeof handleMapClick === 'function') handleMapClick(); });
                
                console.log(`✅ Created ${placemarks.length} markers after filter reload`);
                
                // Auto-center map on new bounds
                if (data.coordinates.length > 0) {
                    const bounds = data.coordinates.reduce((acc, coord) => {
                        if (!acc.minLat || coord.lat < acc.minLat) acc.minLat = coord.lat;
                        if (!acc.maxLat || coord.lat > acc.maxLat) acc.maxLat = coord.lat;
                        if (!acc.minLng || coord.lng < acc.minLng) acc.minLng = coord.lng;
                        if (!acc.maxLng || coord.lng > acc.maxLng) acc.maxLng = coord.lng;
                        return acc;
                    }, {});
                    
                    miniPropertiesMapInstance.setBounds([
                        [bounds.minLat, bounds.minLng],
                        [bounds.maxLat, bounds.maxLng]
                    ], {
                        checkZoomRange: true,
                        zoomMargin: 20
                    });
                    
                    console.log(`🎯 Mini-map re-centered after filter reload`);
                }
            } else {
                console.log('⚠️ No coordinates returned after filter reload');
            }
        })
        .catch(error => {
            console.error('❌ Error reloading mini-map:', error);
        });
};

console.log('✅ reloadMiniMapWithFilters function registered');

// ✅ Reload desktop sidebar property cards based on current fullscreen map viewport
// Called on every boundschange (scroll/zoom) of the fullscreen map
window.reloadMapSidePanelByViewport = function() {
    if (!window.fullscreenMapInstance) return;
    if (window._mapClusterPanelSelected) return;
    if (window.polygonFilterActive) return;
    try {
        const bounds = window.fullscreenMapInstance.getBounds();
        if (!bounds) return;
        const [[latMin, lngMin], [latMax, lngMax]] = bounds;
        const p = new URLSearchParams();
        p.set('lat_min', latMin.toFixed(5));
        p.set('lat_max', latMax.toFixed(5));
        p.set('lng_min', lngMin.toFixed(5));
        p.set('lng_max', lngMax.toFixed(5));
        p.set('per_page', '20');
        p.set('page', '1');
        // Pass active filters from URL
        const urlP = new URLSearchParams(window.location.search);
        ['city_id','districts','developers','rooms','price_min','price_max',
         'area_min','area_max','completion','object_classes','renovation','features'].forEach(function(k) {
            urlP.getAll(k).forEach(function(v) { if (v) p.append(k, v); });
            urlP.getAll(k + '[]').forEach(function(v) { if (v) p.append(k, v); });
        });
        // Also inject window.mapFilters districts
        if (window.mapFilters && Array.isArray(window.mapFilters.districts) && window.mapFilters.districts.length) {
            window.mapFilters.districts.forEach(function(d) { p.append('districts', d); });
        }
        fetch('/api/map-properties?' + p.toString(), { credentials: 'same-origin' })
            .then(function(r) { return r.json(); })
            .then(function(d2) {
                if (!d2.success || !d2.properties || d2.properties.length === 0) return;
                const total = (d2.pagination && d2.pagination.total) || d2.properties.length;
                const panelCount = document.getElementById('mapDesktopPanelCount');
                if (panelCount) panelCount.textContent = total + ' объектов';
                if (typeof updateDesktopPropertiesPanel === 'function') {
                    updateDesktopPropertiesPanel(d2.properties, 'Объекты в области', total);
                }
            })
            .catch(function() {});
    } catch(e) {}
};

// ✅ Mobile map search (Avito-style header input)
/* ── Overlay search bar (desktop fullscreen map, Fix 8) ── */
// ─── Map Search Autocomplete ─────────────────────────────────────────────────
var _mapSearchTimer = null;
function _fetchMapSuggestions(query, dropdownEl) {
    if (!dropdownEl) return;
    if (!query || query.length < 2) { dropdownEl.style.display = 'none'; return; }
    clearTimeout(_mapSearchTimer);
    _mapSearchTimer = setTimeout(function() {
        var cityId = window.currentCityId || window.CURRENT_CITY_ID || '';
        fetch('/api/search/suggestions?q=' + encodeURIComponent(query) + (cityId ? '&city_id=' + cityId : ''), {credentials:'same-origin'})
            .then(function(r){ return r.json(); })
            .then(function(data) {
                if (!data.success || !data.suggestions || !data.suggestions.length) {
                    dropdownEl.style.display = 'none';
                    return;
                }
                dropdownEl.innerHTML = '';
                data.suggestions.slice(0, 8).forEach(function(s) {
                    var item = document.createElement('div');
                    item.style.cssText = 'padding:10px 14px;cursor:pointer;font-size:13px;color:#1f2937;border-bottom:1px solid #f3f4f6;display:flex;align-items:center;gap:8px;';
                    item.onmouseenter = function(){ this.style.background='#f0f9ff'; };
                    item.onmouseleave = function(){ this.style.background=''; };
                    var icon = s.type === 'complex' ? '🏢' : s.type === 'developer' ? '👔' : s.type === 'district' ? '📍' : '🔍';
                    item.innerHTML = '<span style="font-size:15px;flex-shrink:0;">' + icon + '</span><span>' + (s.text || s.value || '') + '</span>';
                    item.onclick = function() {
                        var val = s.text || s.value || '';
                        // Apply to all search inputs
                        ['mapSearchInput','mapOverlaySearchInput','mobileMapSearchInput'].forEach(function(id){
                            var el = document.getElementById(id);
                            if (el) el.value = val;
                        });
                        dropdownEl.style.display = 'none';
                        if (typeof window.handleMobileMapSearch === 'function') window.handleMobileMapSearch(val);
                    };
                    dropdownEl.appendChild(item);
                });
                dropdownEl.style.display = 'block';
            })
            .catch(function(){ dropdownEl.style.display = 'none'; });
    }, 280);
}

// Wire up mapSearchInput (desktop filter bar)
document.addEventListener('DOMContentLoaded', function() {
    var msInput = document.getElementById('mapSearchInput');
    var msDropdown = document.getElementById('mapSearchDropdown');
    if (msInput && msDropdown) {
        msInput.addEventListener('input', function() {
            var q = this.value.trim();
            _fetchMapSuggestions(q, msDropdown);
            if (typeof window.handleMobileMapSearch === 'function') window.handleMobileMapSearch(q);
        });
        msInput.addEventListener('keydown', function(e) {
            if (e.key === 'Escape') { this.value = ''; msDropdown.style.display='none'; window.handleMobileMapSearch && window.handleMobileMapSearch(''); }
            if (e.key === 'Enter') { msDropdown.style.display='none'; window.handleMobileMapSearch && window.handleMobileMapSearch(this.value.trim()); }
        });
        // Position dropdown under input on input event
        msInput.addEventListener('focus', function() {
            if (this.value.length >= 2) _fetchMapSuggestions(this.value, msDropdown);
            var rect = msInput.getBoundingClientRect();
            msDropdown.style.top = (rect.bottom + window.scrollY + 4) + 'px';
            msDropdown.style.left = (rect.left + window.scrollX) + 'px';
            msDropdown.style.width = Math.max(280, rect.width) + 'px';
        });
        document.addEventListener('click', function(e) {
            if (!msInput.contains(e.target) && !msDropdown.contains(e.target)) msDropdown.style.display='none';
        });
    }
    // Wire up mapOverlaySearchSuggestions 
    var overlayInput = document.getElementById('mapOverlaySearchInput');
    var overlaySugg = document.getElementById('mapOverlaySearchSuggestions');
    if (overlayInput && overlaySugg) {
        overlayInput.addEventListener('input', function() {
            var q = this.value.trim();
            _fetchMapSuggestions(q, overlaySugg);
        });
        overlayInput.addEventListener('keydown', function(e) {
            if (e.key === 'Enter') overlaySugg.style.display = 'none';
        });
        document.addEventListener('click', function(e) {
            if (!overlayInput.contains(e.target) && !overlaySugg.contains(e.target)) overlaySugg.style.display='none';
        });
    }
});

window.handleMapOverlaySearch = function(query) {
    // Sync value with mobile input and reuse the same pipeline
    var mobileInput = document.getElementById('mobileMapSearchInput');
    if (mobileInput && mobileInput.value !== query) mobileInput.value = query;
    // Show/hide clear button
    var clearBtn = document.getElementById('mapOverlaySearchClear');
    if (clearBtn) clearBtn.style.display = query ? 'block' : 'none';
    // Delegate to mobile handler
    if (typeof window.handleMobileMapSearch === 'function') {
        window.handleMobileMapSearch(query);
    }
};

/* Hide/show overlay search bar when drawing mode activates */
(function patchDrawModeForOverlaySearch() {
    var _origEnable = window.enableMapDrawingCIAN;
    var _origClear  = window.clearMapDrawnArea;
    function _hideOverlaySearch() {
        var el = document.getElementById('mapOverlaySearchWrapper');
        if (el) el.style.display = 'none';
    }
    function _showOverlaySearch() {
        var el = document.getElementById('mapOverlaySearchWrapper');
        if (el) el.style.display = '';
    }
    if (typeof _origEnable === 'function') {
        window.enableMapDrawingCIAN = function() { _hideOverlaySearch(); _origEnable.apply(this, arguments); };
    }
    if (typeof _origClear === 'function') {
        window.clearMapDrawnArea = function() { _showOverlaySearch(); _origClear.apply(this, arguments); };
    }
    // Also patch on DOMContentLoaded in case functions register later
    document.addEventListener('DOMContentLoaded', function() {
        setTimeout(function() {
            if (!window._overlaySearchPatched) {
                window._overlaySearchPatched = true;
                var e2 = window.enableMapDrawingCIAN;
                var c2 = window.clearMapDrawnArea;
                if (typeof e2 === 'function' && !e2._overlayPatched) {
                    e2._overlayPatched = true;
                    window.enableMapDrawingCIAN = function() { _hideOverlaySearch(); e2.apply(this, arguments); };
                }
                if (typeof c2 === 'function' && !c2._overlayPatched) {
                    c2._overlayPatched = true;
                    window.clearMapDrawnArea = function() { _showOverlaySearch(); c2.apply(this, arguments); };
                }
            }
        }, 500);
    });
})();

window.handleMobileMapSearch = function(query) {
    clearTimeout(window._mobileMapSearchTimer);
    window._mobileMapSearchTimer = setTimeout(function() {
        query = (query || '').trim();
        if (!window.mapFilters) window.mapFilters = {};
        if (query.length >= 2) {
            window.mapFilters.search = query;
        } else {
            delete window.mapFilters.search;
            window.mapFilters.search = '';
        }
        // ✅ Persist search query in URL (updateMapWithFilters also does this, but
        // mirror immediately for parity even if the map isn't initialized yet)
        if (typeof persistMapFiltersToUrl === 'function') persistMapFiltersToUrl();
        // ✅ Unified pipeline: refresh markers + cards (desktop panel & mobile sheet)
        // + counters via updateMapWithFilters.
        if (typeof window.updateMapWithFilters === 'function') {
            window.updateMapWithFilters();
        }
    }, 450);
};

// ✅ Auto-open fullscreen map if URL carries `map=1` (e.g. after back-navigation
// from /object/<id>). Runs once on DOM ready.
(function autoOpenFullscreenMapFromUrl() {
    function _maybeOpen() {
        try {
            const sp = new URLSearchParams(window.location.search);
            if (sp.get('map') !== '1') return;
            if (typeof window.openFullscreenMap !== 'function') return;
            const modal = document.getElementById('fullscreenMapModal');
            if (!modal || !modal.classList.contains('hidden')) return;
            console.log('🔁 Restoring fullscreen map from URL flag map=1');
            window.openFullscreenMap();
        } catch (e) {
            console.warn('autoOpenFullscreenMapFromUrl failed', e);
        }
    }
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', () => setTimeout(_maybeOpen, 200));
    } else {
        setTimeout(_maybeOpen, 200);
    }
    // Also re-open when the page comes back from bfcache (mobile Safari/Chrome back nav)
    window.addEventListener('pageshow', function(ev) {
        if (ev.persisted) setTimeout(_maybeOpen, 50);
    });
})();

// ✅ Infinite scroll: attach scroll listener to desktop properties panel
// Retries until the container appears in DOM (it lives inside hidden modal).
(function attachDesktopPanelInfiniteScroll() {
    function _attach() {
        const container = document.getElementById('mapDesktopPropertiesContainer');
        if (!container) {
            setTimeout(_attach, 600);
            return;
        }
        container.addEventListener('scroll', function() {
            const { scrollTop, scrollHeight, clientHeight } = container;
            // Trigger when within 300px of bottom
            if (scrollHeight - scrollTop - clientHeight < 300) {
                if (typeof loadMoreDesktopCards === 'function') {
                    loadMoreDesktopCards();
                }
            }
        }, { passive: true });
        console.log('✅ Desktop panel infinite scroll listener attached');
    }
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', _attach);
    } else {
        _attach();
    }
})();
