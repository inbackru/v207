#!/usr/bin/env python3
"""
Test script for Geocoding Service
Demonstrates all geocoding features
"""

from services.geocoding import get_geocoding_service
import json


def test_geocoding():
    """Test all geocoding service features"""
    
    service = get_geocoding_service()
    print("=" * 60)
    print("GEOCODING SERVICE TEST")
    print("=" * 60)
    
    # Test 1: Reverse Geocoding (coordinates → address)
    print("\n1. REVERSE GEOCODING (Coordinates → Address)")
    print("-" * 60)
    lat, lon = 45.0355, 38.9753  # Krasnodar center
    print(f"Input: lat={lat}, lon={lon}")
    
    result = service.reverse_geocode(lat, lon)
    if result:
        print(f"✅ Success!")
        print(f"   City: {result.get('city')}")
        print(f"   Street: {result.get('street')}")
        print(f"   Full address: {result.get('formatted_address')}")
    else:
        print("❌ Failed")
    
    # Test 2: Forward Geocoding (address → coordinates)
    print("\n2. FORWARD GEOCODING (Address → Coordinates)")
    print("-" * 60)
    address = "Краснодар, улица Красная, 170"
    print(f"Input: {address}")
    
    result = service.forward_geocode(address)
    if result:
        print(f"✅ Success!")
        print(f"   Coordinates: {result.get('latitude')}, {result.get('longitude')}")
        print(f"   Precision: {result.get('precision')}")
        print(f"   City: {result.get('city')}")
        print(f"   Street: {result.get('street')}")
    else:
        print("❌ Failed")
    
    # Test 3: Autocomplete
    print("\n3. AUTOCOMPLETE (Address Search)")
    print("-" * 60)
    query = "улица Красная"
    print(f"Input: {query}")
    
    suggestions = service.autocomplete(query, latitude=45.0355, longitude=38.9753)
    if suggestions:
        print(f"✅ Found {len(suggestions)} suggestions:")
        for i, sug in enumerate(suggestions[:3], 1):
            print(f"   {i}. {sug.get('title')} - {sug.get('subtitle')}")
    else:
        print("❌ No suggestions found")
    
    # Test 4: Property Address Enrichment
    print("\n4. PROPERTY ADDRESS ENRICHMENT")
    print("-" * 60)
    lat, lon = 45.042496, 38.977559  # Krasnaya 170
    print(f"Input: lat={lat}, lon={lon}")
    
    enriched = service.enrich_property_address(lat, lon)
    if enriched:
        print(f"✅ Success!")
        print(f"   parsed_city: {enriched.get('parsed_city')}")
        print(f"   parsed_district: {enriched.get('parsed_district')}")
        print(f"   parsed_street: {enriched.get('parsed_street')}")
        print(f"   full_address: {enriched.get('full_address')}")
    else:
        print("❌ Failed")
    
    # Statistics
    print("\n5. SERVICE STATISTICS")
    print("-" * 60)
    stats = service.get_stats()
    print(f"   API Requests: {stats['api_requests']}")
    print(f"   Cache Hits: {stats['cache_hits']}")
    print(f"   Cache Size: {stats['cache_size']}")
    print(f"   Cache Hit Rate: {stats['cache_hit_rate']}")
    
    print("\n" + "=" * 60)
    print("ALL TESTS COMPLETED")
    print("=" * 60)


if __name__ == "__main__":
    test_geocoding()
