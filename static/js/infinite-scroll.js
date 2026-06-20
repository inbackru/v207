// ✅ INFINITE SCROLL FOR PROPERTIES - SIMPLIFIED VERSION
console.log('♾️ INFINITE-SCROLL.JS LOADED');

(function() {
    'use strict';
    
    let isLoading = false;
    let hasMorePages = true;
    let currentPage = 1;
    let observer = null;
    let sentinel = null;
    let currentAbortController = null;
    let initialContentReady = false;
    
    // Initialize on DOM ready
    function init() {
        console.log('🚀 Initializing Infinite Scroll...');
        
        // Get initial pagination state
        if (typeof window.currentServerPage !== 'undefined') {
            currentPage = window.currentServerPage;
        }
        
        if (typeof window.totalPages !== 'undefined') {
            hasMorePages = currentPage < window.totalPages;
        }
        
        console.log('📄 Initial state:', {
            currentPage: currentPage,
            totalPages: window.totalPages,
            hasMorePages: hasMorePages
        });
        
        // Create sentinel
        createSentinel();
        
        // Setup observer
        setupObserver();
        
        console.log('✅ Infinite Scroll initialized');
    }
    
    function createSentinel() {
        // Remove existing
        const existing = document.getElementById('infinite-scroll-sentinel');
        if (existing) existing.remove();
        
        // Create new
        sentinel = document.createElement('div');
        sentinel.id = 'infinite-scroll-sentinel';
        sentinel.className = 'w-full py-8 flex justify-center items-center';
        sentinel.style.minHeight = '100px';
        
        const container = document.getElementById('properties-container');
        if (container && container.parentElement) {
            container.parentElement.appendChild(sentinel);
            console.log('✅ Sentinel created');
        }
    }
    
    function setupObserver() {
        const options = {
            root: null,
            rootMargin: '200px',
            threshold: 0.1
        };
        
        observer = new IntersectionObserver(function(entries) {
            entries.forEach(function(entry) {
                if (entry.isIntersecting && !isLoading && hasMorePages && initialContentReady) {
                    console.log('👁️ Sentinel visible - loading next page');
                    loadNextPage();
                }
            });
        }, options);
        
        if (sentinel) {
            observer.observe(sentinel);
            console.log('✅ Observer attached');
        }
    }
    
    function loadNextPage() {
        if (isLoading || !hasMorePages) return;
        
        isLoading = true;
        const nextPage = currentPage + 1;
        
        console.log('📥 Loading page ' + nextPage);
        
        showLoading();
        
        // Create new AbortController for this request
        currentAbortController = new AbortController();
        const signal = currentAbortController.signal;
        
        const currentUrl = new URLSearchParams(window.location.search);
        currentUrl.set('page', nextPage);
        if (window.currentCityId && !currentUrl.has('city_id')) {
            currentUrl.set('city_id', window.currentCityId);
        }
        if (window.lockedDistrictId && !currentUrl.has('district_id')) {
            currentUrl.set('district_id', window.lockedDistrictId);
        }
        if (window.lockedDistrictSlug && !currentUrl.has('districts') && !window.lockedDistrictId) {
            currentUrl.append('districts', window.lockedDistrictSlug);
        }
        
        const apiUrl = '/api/properties/list?' + currentUrl.toString();
        console.log('📡 Fetching:', apiUrl);
        
        fetch(apiUrl, { signal: signal })
            .then(function(response) {
                if (!response.ok) throw new Error('HTTP ' + response.status);
                return response.json();
            })
            .then(function(data) {
                console.log('✅ Loaded page data:', data);
                
                if (data.success && data.properties && data.properties.length > 0) {
                    appendProperties(data.properties);
                    currentPage = nextPage;
                    hasMorePages = data.pagination.has_next;
                    
                    if (typeof window.currentServerPage !== 'undefined') {
                        window.currentServerPage = nextPage;
                    }
                    
                    console.log('✅ Appended ' + data.properties.length + ' properties. Page ' + currentPage);
                    
                    if (!hasMorePages) showEndMessage();
                } else {
                    hasMorePages = false;
                    showEndMessage();
                }
            })
            .catch(function(error) {
                // Ignore aborted requests (expected when sorting/filtering)
                if (error.name === 'AbortError') {
                    console.log('⚠️ Infinite scroll request aborted (expected during reset)');
                    return;
                }
                console.error('❌ Error:', error);
                showErrorMessage();
            })
            .finally(function() {
                isLoading = false;
                hideLoading();
                currentAbortController = null;
            });
    }
    
    function appendProperties(properties) {
        console.log('🔄 Appending ' + properties.length + ' properties');
        
        const container = document.getElementById('properties-container');
        if (!container) {
            console.error('❌ Container not found');
            return;
        }
        
        properties.forEach(function(property, index) {
            const card = renderCard(property, index);
            container.appendChild(card);
        });
        
        if (window.favoritesManager && typeof window.favoritesManager.updateFavoritesUI === 'function') {
            window.favoritesManager.updateFavoritesUI();
            window.favoritesManager.updateComplexFavoritesUI();
        }
        
        if (typeof window.initializeComparisonButtons === 'function') {
            window.initializeComparisonButtons();
        }
        if (window.comparisonManager && typeof window.comparisonManager.updateComparisonUI === 'function') {
            window.comparisonManager.updateComparisonUI();
        }
        if (window.simpleComparisonManager && typeof window.simpleComparisonManager.updateComparisonUI === 'function') {
            window.simpleComparisonManager.updateComparisonUI();
        }
        
        if (typeof window.initCarouselSwipeHandlers === 'function') {
            window.initCarouselSwipeHandlers();
        }
        
        // Apply current view mode
        if (typeof window.currentViewMode !== 'undefined') {
            if (window.currentViewMode === 'grid' && typeof window.switchToGridView === 'function') {
                window.switchToGridView();
            } else if (typeof window.switchToListView === 'function') {
                window.switchToListView();
            }
        }
        
        console.log('✅ Properties appended');
    }
    
    function renderCard(property, index) {
        if (typeof window.renderPropertyCard === 'function') {
            return window.renderPropertyCard(property, index);
        }
        
        // Fallback
        const card = document.createElement('div');
        card.className = 'property-card bg-white p-4';
        card.innerHTML = '<div>Property ' + property.id + '</div>';
        return card;
    }
    
    function showLoading() {
        if (!sentinel) return;
        sentinel.innerHTML = '<div class="flex flex-col items-center gap-3"><div class="animate-spin rounded-full h-10 w-10 border-b-4 border-blue-600"></div><p class="text-gray-600 text-sm font-medium">Загрузка объектов...</p></div>';
    }
    
    function hideLoading() {
        if (!sentinel) return;
        sentinel.innerHTML = '';
    }
    
    function showEndMessage() {
        if (!sentinel) return;
        sentinel.innerHTML = '<div class="flex flex-col items-center gap-2 py-4"><svg class="w-8 h-8 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"/></svg><p class="text-gray-500 text-sm">Все объекты загружены</p></div>';
        console.log('✅ All properties loaded');
    }
    
    function showErrorMessage() {
        if (!sentinel) return;
        sentinel.innerHTML = '<div class="flex flex-col items-center gap-2 py-4"><svg class="w-8 h-8 text-red-500" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/></svg><p class="text-gray-500 text-sm">Ошибка загрузки</p></div>';
    }
    
    function reset(newPage, hasMore) {
        console.log('🔄 Resetting infinite scroll:', { newPage: newPage, hasMore: hasMore });
        
        // Abort any pending fetch request to prevent race condition
        if (currentAbortController) {
            currentAbortController.abort();
            currentAbortController = null;
            console.log('🚫 Aborted pending infinite scroll request');
        }
        
        // Reset state variables
        currentPage = newPage || 1;
        hasMorePages = hasMore !== undefined ? hasMore : true;
        isLoading = false;
        initialContentReady = true;
        
        // Disconnect and cleanup old observer
        if (observer) {
            if (sentinel) {
                observer.unobserve(sentinel);
            }
            observer.disconnect();
            observer = null;
            console.log('🗑️ Old observer disconnected');
        }
        
        // Remove old sentinel
        if (sentinel) {
            sentinel.remove();
            sentinel = null;
            console.log('🗑️ Old sentinel removed');
        }
        
        // Create new sentinel
        createSentinel();
        
        // Setup new observer
        setupObserver();
        
        console.log('✅ Infinite scroll reset complete - ready to load from page ' + (currentPage + 1));
    }
    
    function markReady() {
        initialContentReady = true;
        console.log('✅ Infinite scroll: initial content ready, scroll enabled');
    }
    
    // Export functions
    window.infiniteScrollManager = {
        reset: reset,
        init: init,
        markReady: markReady
    };
    
    // Auto-initialize
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
    
    console.log('✅ infinite-scroll.js initialization complete');
})();
