"""
SEO URL Redirects and City-Based Routing
Handles 301 permanent redirects from legacy URLs to city-based URLs
"""
from flask import request, redirect, url_for, session
from functools import wraps


def get_redirect_city_slug():
    """
    Determine which city slug to use for redirects.
    Priority:
    1. Session city_slug (most recent user selection)
    2. Query parameter ?city=
    3. Default city (Krasnodar)
    """
    # Try session first
    city_slug = session.get('city_slug') or session.get('current_city_slug')
    
    # Fall back to query parameter
    if not city_slug:
        city_slug = request.args.get('city')
    
    # Default to Krasnodar
    if not city_slug:
        city_slug = 'krasnodar'
    
    return city_slug


def get_city_slug_for_resource(resource_type, resource_id=None, slug=None):
    """
    Get the correct city slug for a given resource (property or complex).
    
    Args:
        resource_type: 'property' or 'complex'
        resource_id: The ID of the resource (for property or complex by ID)
        slug: The slug of the resource (for complex by slug)
    
    Returns:
        City slug string or None if not found
    """
    from models import Property, ResidentialComplex
    
    if resource_type == 'property' and resource_id:
        prop = Property.query.get(resource_id)
        if prop:
            # Try residential_complex.city first (most accurate)
            if prop.residential_complex and prop.residential_complex.city:
                return prop.residential_complex.city.slug
            # Fallback to direct property.city relationship
            if prop.city:
                return prop.city.slug
    
    elif resource_type == 'complex':
        complex_obj = None
        
        # Look up by ID
        if resource_id:
            complex_obj = ResidentialComplex.query.get(resource_id)
        # Look up by slug
        elif slug:
            complex_obj = ResidentialComplex.query.filter_by(slug=slug).first()
        
        if complex_obj and complex_obj.city:
            return complex_obj.city.slug
    
    return None


def redirect_to_city_based(endpoint_name, **kwargs):
    """
    Create a 301 redirect to the city-based version of a URL.
    
    Args:
        endpoint_name: Flask endpoint name (e.g., 'properties_city')
        **kwargs: Additional URL parameters to pass (e.g., property_id=123)
    
    Returns:
        Flask redirect response with 301 status
    """
    city_slug = get_redirect_city_slug()
    
    # Build URL parameters
    url_params = {'city_slug': city_slug}
    url_params.update(kwargs)
    
    # Preserve query string parameters (except city)
    query_params = {k: v for k, v in request.args.items() if k != 'city'}
    
    # Blueprint prefix map — bare endpoint names to blueprint-prefixed versions
    _BLUEPRINT_MAP = {
        'about_city': 'city_pages.about_city',
        'appraisal_city': 'city_pages.appraisal_city',
        'blog_city': 'blog.blog_city',
        'cashback_kvartiry_city': 'city_pages.cashback_kvartiry_city',
        'cashback_terms_city': 'city_pages.cashback_terms_city',
        'comparison_city': 'city_pages.comparison_city',
        'contacts_city': 'city_pages.contacts_city',
        'developer_mortgage_city': 'city_pages.developer_mortgage_city',
        'developers_city': 'devs.developers_city',
        'family_mortgage_city': 'city_pages.family_mortgage_city',
        'favorites_city': 'city_pages.favorites_city',
        'how_it_works_city': 'city_pages.how_it_works_city',
        'insurance_city': 'city_pages.insurance_city',
        'ipoteka_city': 'city_pages.ipoteka_city',
        'it_mortgage_city': 'city_pages.it_mortgage_city',
        'map_city': 'city_pages.map_city',
        'maternal_capital_city': 'city_pages.maternal_capital_city',
        'military_mortgage_city': 'city_pages.military_mortgage_city',
        'properties_city': 'props.properties_city',
        'property_detail_city': 'props.property_detail_city',
        'residential_complex_by_slug_city': 'complexes.residential_complex_by_slug_city',
        'residential_complexes_city': 'complexes.residential_complexes_city',
        'reviews_city': 'city_pages.reviews_city',
        'security_city': 'city_pages.security_city',
        'streets_city': 'city_pages.streets_city',
        'tax_deduction_city': 'city_pages.tax_deduction_city',
    }
    resolved_endpoint = _BLUEPRINT_MAP.get(endpoint_name, endpoint_name)

    # Build the URL
    url = url_for(resolved_endpoint, **url_params)
    
    # Add query parameters if any
    if query_params:
        from urllib.parse import urlencode
        url = f"{url}?{urlencode(query_params, doseq=True)}"
    
    return redirect(url, code=301)  # Permanent redirect for SEO


# Helper functions for SEO-friendly city-based URLs
