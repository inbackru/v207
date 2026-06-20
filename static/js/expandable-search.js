// Expandable Search - Beautiful smooth animations like Yandex
(function() {
    let isSearchExpanded = false;
    
    function expandSearch() {
        if (isSearchExpanded) return;
        
        console.log('🔍 Expanding search with smooth animation...');
        isSearchExpanded = true;
        
        // Use requestAnimationFrame for smoother animations
        requestAnimationFrame(() => {
            // Hide filter buttons with staggered animation (слева направо)
            const filterButtons = document.querySelectorAll('.search-filter-btn');
            filterButtons.forEach((btn, index) => {
                // Staggered delay for wave effect
                setTimeout(() => {
                    btn.classList.add('search-expanded');
                }, index * 50); // 50ms delay between each button
            });
            
            // Show close button after buttons start hiding
            const closeBtn = document.getElementById('search-close-btn');
            if (closeBtn) {
                setTimeout(() => {
                    closeBtn.classList.remove('hidden');
                    requestAnimationFrame(() => {
                        closeBtn.classList.add('show');
                    });
                }, 100);
            }
            
            // Focus search input after animation starts
            const searchInput = document.getElementById('property-search-desktop');
            if (searchInput) {
                setTimeout(() => {
                    searchInput.focus();
                }, 200);
            }
        });
    }
    
    function closeExpandedSearch() {
        if (!isSearchExpanded) return;
        
        console.log('❌ Closing search with smooth animation...');
        isSearchExpanded = false;
        
        // Hide close button first
        const closeBtn = document.getElementById('search-close-btn');
        if (closeBtn) {
            closeBtn.classList.remove('show');
            setTimeout(() => {
                closeBtn.classList.add('hidden');
            }, 350);
        }
        
        // Use requestAnimationFrame for smoother animations
        requestAnimationFrame(() => {
            // Show filter buttons with staggered animation (справа налево)
            const filterButtons = document.querySelectorAll('.search-filter-btn');
            const buttonsArray = Array.from(filterButtons).reverse();
            
            buttonsArray.forEach((btn, index) => {
                // Staggered delay for wave effect (reverse)
                setTimeout(() => {
                    btn.classList.remove('search-expanded');
                }, index * 50); // 50ms delay between each button
            });
        });
    }
    
    // Initialize on DOM ready
    document.addEventListener('DOMContentLoaded', function() {
        const searchInput = document.getElementById('property-search-desktop');
        if (!searchInput) return;
        
        // Expand on focus
        searchInput.addEventListener('focus', function(e) {
            expandSearch();
        });
        
        // Close on click outside
        document.addEventListener('click', function(e) {
            if (!isSearchExpanded) return;
            
            const container = document.getElementById('search-input-container');
            if (container && !container.contains(e.target)) {
                closeExpandedSearch();
            }
        });
        
        // Close on Escape key
        document.addEventListener('keydown', function(e) {
            if (e.key === 'Escape' && isSearchExpanded) {
                closeExpandedSearch();
                searchInput.blur();
            }
        });
        
        console.log('✅ Expandable search initialized');
    });
    
    // Make closeExpandedSearch available globally for onclick handler
    window.closeExpandedSearch = closeExpandedSearch;
})();
