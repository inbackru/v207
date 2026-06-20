console.log('🔍 index-search.js loading...');

document.addEventListener('DOMContentLoaded', function() {
    const heroSearchInput = document.getElementById('hero-search');
    const heroSearchBtn = document.getElementById('hero-search-btn');
    const heroSearchForm = document.getElementById('hero-search-form');

    if (!heroSearchInput || !heroSearchBtn) {
        console.warn('⚠️ Hero search elements not found');
        return;
    }

    // If the form already has its own submit handler (defined inline in the template),
    // don't add duplicate click/keypress handlers — they would fire BEFORE form.submit
    // and bypass smart city detection.
    if (heroSearchForm) {
        // The template's DOMContentLoaded handler manages this form.
        // index-search.js only acts as a safety fallback if no inline handler is added.
        console.log('ℹ️ index-search.js: form found, deferring to template handler');
        return;
    }

    async function performHeroSearch() {
        const query = heroSearchInput.value.trim();
        if (!query) return;

        console.log('🔍 Hero search:', query);

        // Try smart-search to detect city from query text
        try {
            const response = await fetch(`/api/smart-search?q=${encodeURIComponent(query)}`);
            if (response.ok) {
                const data = await response.json();
                if (data.detected_city && data.detected_city.city_slug) {
                    const citySlug = data.detected_city.city_slug;
                    window.location.href = `/${citySlug}/novostrojki?search=${encodeURIComponent(query)}`;
                    return;
                }
            }
        } catch (e) {
            console.warn('Smart search error:', e);
        }

        // Fallback: use current city from window or session redirect
        const citySlug = window.currentCitySlug;
        const url = citySlug
            ? `/${citySlug}/novostrojki?search=${encodeURIComponent(query)}`
            : `/properties?search=${encodeURIComponent(query)}`;
        window.location.href = url;
    }

    heroSearchBtn.addEventListener('click', function(e) {
        e.preventDefault();
        performHeroSearch();
    });

    heroSearchInput.addEventListener('keypress', function(e) {
        if (e.key === 'Enter') {
            e.preventDefault();
            performHeroSearch();
        }
    });

    console.log('✅ Hero search fallback handlers initialized');
});
