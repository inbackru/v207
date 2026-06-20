/**
 * Saved Searches Manager
 * Handles saving, loading, and applying search parameters
 */

class SavedSearchesManager {
    constructor() {
        this.init();
    }

    init() {
        try {
            this.bindEvents();
            this.loadSavedSearches();
        } catch (error) {
            console.error('Error initializing saved searches:', error);
        }
    }

    getCSRFToken() {
        const csrfInput = document.querySelector('input[name="csrf_token"]');
        console.log('CSRF input element:', csrfInput);
        if (csrfInput) {
            console.log('CSRF token from input:', csrfInput.value);
            return csrfInput.value;
        }
        const csrfMeta = document.querySelector('meta[name="csrf-token"]');
        console.log('CSRF meta element:', csrfMeta);
        if (csrfMeta) {
            console.log('CSRF token from meta:', csrfMeta.content);
            return csrfMeta.content;
        }
        console.log('NO CSRF TOKEN FOUND!');
        return '';
    }

    bindEvents() {
        // Save search button
        document.addEventListener('click', (e) => {
            if (e.target && e.target.classList.contains('save-search-btn')) {
                this.openSaveSearchModal();
                e.preventDefault();
            }
        });

        // Apply saved search
        document.addEventListener('click', (e) => {
            if (e.target && e.target.classList.contains('apply-search-btn')) {
                const searchId = e.target.dataset.searchId;
                this.applySavedSearch(searchId);
                e.preventDefault();
            }
        });

        // Delete saved search
        document.addEventListener('click', (e) => {
            if (e.target && e.target.classList.contains('delete-search-btn')) {
                const searchId = e.target.dataset.searchId;
                this.deleteSavedSearch(searchId);
                e.preventDefault();
            }
        });
    }

    getCurrentSearchParams() {
        let params = {};

        // Get parameters from URL first - this is most reliable source
        const urlParams = new URLSearchParams(window.location.search);
        urlParams.forEach((value, key) => {
            if (value && value.trim() !== '') {
                // Handle multiple values for same parameter (e.g., rooms)
                if (params[key]) {
                    if (Array.isArray(params[key])) {
                        params[key].push(value.trim());
                    } else {
                        params[key] = [params[key], value.trim()];
                    }
                } else {
                    params[key] = value.trim();
                }
            }
        });

        // If no URL params, try to extract from form and active UI elements
        if (Object.keys(params).length === 0) {
            // Check active filter buttons on properties page  
            try {
                const activeFilters = document.querySelectorAll('.active-filter-btn, .filter-btn.active, input[type="checkbox"]:checked');
                activeFilters.forEach(element => {
                    const filterType = element.dataset.filter || element.name;
                    const filterValue = element.dataset.value || element.value;
                    
                    if (filterType && filterValue) {
                        if (!params[filterType]) {
                            params[filterType] = [];
                        }
                    if (Array.isArray(params[filterType])) {
                        params[filterType].push(filterValue);
                    } else {
                        params[filterType] = [params[filterType], filterValue];
                    }
                }
                });
            } catch (error) {
                console.error('Error reading active filters:', error);
            }

            // Check price range inputs with error handling
            try {
            const priceFromInput = document.querySelector('#priceFrom, input[name="priceFrom"]');
            const priceToInput = document.querySelector('#priceTo, input[name="priceTo"]');
            if (priceFromInput && priceFromInput.value && priceFromInput.value !== '0') {
                params.priceFrom = priceFromInput.value;
            }
            if (priceToInput && priceToInput.value && priceToInput.value !== '0') {
                params.priceTo = priceToInput.value;
            }

            // Check area range inputs
            const areaFromInput = document.querySelector('#areaFrom, input[name="areaFrom"]');
            const areaToInput = document.querySelector('#areaTo, input[name="areaTo"]');
            if (areaFromInput && areaFromInput.value && areaFromInput.value !== '0') {
                params.areaFrom = areaFromInput.value;
            }
            if (areaToInput && areaToInput.value && areaToInput.value !== '0') {
                params.areaTo = areaToInput.value;
            }
            } catch (error) {
                console.error('Error reading input values:', error);
            }
        }

        // Clean up params - convert single-item arrays to strings
        for (const [key, value] of Object.entries(params)) {
            if (Array.isArray(value) && value.length === 1) {
                params[key] = value[0];
            }
        }
        
        const normalized = {};
        for (const [key, value] of Object.entries(params)) {
            let normalizedKey = key.replace(/\[\]$/, '');
            
            // Normalize legacy or alternative naming conventions
            if (normalizedKey === 'priceFrom' || normalizedKey === 'price_from') {
                normalizedKey = 'price_min';
            } else if (normalizedKey === 'priceTo' || normalizedKey === 'price_to') {
                normalizedKey = 'price_max';
            } else if (normalizedKey === 'areaFrom' || normalizedKey === 'area_from') {
                normalizedKey = 'area_min';
            } else if (normalizedKey === 'areaTo' || normalizedKey === 'area_to') {
                normalizedKey = 'area_max';
            } else if (normalizedKey === 'floorFrom' || normalizedKey === 'floor_from') {
                normalizedKey = 'floor_min';
            } else if (normalizedKey === 'floorTo' || normalizedKey === 'floor_to') {
                normalizedKey = 'floor_max';
            } else if (normalizedKey === 'object_class') {
                normalizedKey = 'object_classes';
            } else if (normalizedKey === 'type') {
                normalizedKey = 'property_type';
            }
            
            if (normalized[normalizedKey] !== undefined) {
                if (Array.isArray(normalized[normalizedKey])) {
                    if (Array.isArray(value)) {
                        normalized[normalizedKey] = normalized[normalizedKey].concat(value);
                    } else {
                        normalized[normalizedKey].push(value);
                    }
                } else {
                    normalized[normalizedKey] = [normalized[normalizedKey]].concat(Array.isArray(value) ? value : [value]);
                }
            } else {
                normalized[normalizedKey] = value;
            }
        }

        console.log('Final search params (normalized):', normalized);
        return normalized;
    }

    generateSearchName(params) {
        let parts = [];

        // Add room types
        if (params.rooms && params.rooms.length > 0) {
            const roomTypes = Array.isArray(params.rooms) ? params.rooms : [params.rooms];
            const roomNames = roomTypes.map(room => {
                if (room.includes('студия')) return 'Студия';
                if (room.includes('комн')) return room;
                return room + '-комн';
            });
            parts.push(roomNames.join(', '));
        }

        // Add districts
        if (params.districts && params.districts.length > 0) {
            const districts = Array.isArray(params.districts) ? params.districts : [params.districts];
            parts.push('р-н ' + districts.join(', '));
        }

        // Add developers
        if (params.developers && params.developers.length > 0) {
            const developers = Array.isArray(params.developers) ? params.developers : [params.developers];
            parts.push('от ' + developers.join(', '));
        }

        // Add price range (supports both normalized and original keys)
        const priceMin = params.price_min || params.priceFrom;
        const priceMax = params.price_max || params.priceTo;
        if (priceMin || priceMax) {
            let priceText = '';
            const fmtMin = priceMin && priceMin >= 1000000 ? (priceMin / 1000000).toFixed(1) : priceMin;
            const fmtMax = priceMax && priceMax >= 1000000 ? (priceMax / 1000000).toFixed(1) : priceMax;
            if (fmtMin && fmtMax) {
                priceText = `${fmtMin}-${fmtMax} млн`;
            } else if (fmtMin) {
                priceText = `от ${fmtMin} млн`;
            } else if (fmtMax) {
                priceText = `до ${fmtMax} млн`;
            }
            parts.push(priceText);
        }

        // Add area range (supports both normalized and original keys)
        const areaMin = params.area_min || params.areaFrom;
        const areaMax = params.area_max || params.areaTo;
        if (areaMin || areaMax) {
            let areaText = '';
            if (areaMin && areaMax) {
                areaText = `${areaMin}-${areaMax} м²`;
            } else if (areaMin) {
                areaText = `от ${areaMin} м²`;
            } else if (areaMax) {
                areaText = `до ${areaMax} м²`;
            }
            parts.push(areaText);
        }

        if (params.property_type && params.property_type !== 'all') {
            const typeNames = {
                'apartments': 'Квартиры',
                'houses': 'Дома',
                'townhouses': 'Таунхаусы',
                'penthouses': 'Пентхаусы',
                'apartments_commercial': 'Апартаменты'
            };
            parts.push(typeNames[params.property_type] || params.property_type);
        }

        if (params.object_classes) {
            const classes = Array.isArray(params.object_classes) ? params.object_classes : [params.object_classes];
            parts.push(classes.join(', '));
        }

        return parts.length > 0 ? parts.join(', ') : 'Поиск недвижимости';
    }

    openSaveSearchModal() {
        const params = this.getCurrentSearchParams();
        
        // Check if user is authenticated (support both users and managers)
        const userAuthElement = document.querySelector('a[href*="dashboard"]') || document.querySelector('.user-authenticated');
        const managerAuthElement = document.querySelector('a[href*="manager/dashboard"]') || document.querySelector('.manager-authenticated');
        const isAuthenticated = userAuthElement !== null || managerAuthElement !== null || 
                              document.querySelector('a[href*="logout"]') !== null ||
                              window.user_authenticated === true || window.manager_authenticated === true;
        
        if (!isAuthenticated) {
            this.showNotification('Войдите в аккаунт для сохранения поисков', 'warning');
            return;
        }

        if (Object.keys(params).length === 0) {
            this.showNotification('Задайте параметры поиска для сохранения', 'warning');
            return;
        }

        // Generate suggested search name based on current filters
        const suggestedName = this.generateSearchName(params);

        // Create modal HTML
        const modalHTML = `
            <div id="save-search-modal" class="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
                <div class="bg-white rounded-lg p-6 w-full max-w-md mx-4">
                    <h3 class="text-lg font-semibold mb-4">Сохранить поиск</h3>
                    <form id="save-search-form">
                        <div class="mb-4">
                            <label class="block text-sm font-medium text-gray-700 mb-2">
                                Название поиска
                            </label>
                            <input type="text" id="search-name" name="name" required
                                   class="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                                   placeholder="Например: 2-комн в центре до 10млн"
                                   value="${suggestedName}">
                        </div>
                        <div class="mb-4">
                            <label class="block text-sm font-medium text-gray-700 mb-2">
                                Описание (необязательно)
                            </label>
                            <textarea id="search-description" name="description" rows="2"
                                      class="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                                      placeholder="Дополнительные заметки о поиске"></textarea>
                        </div>
                        <div class="mb-4">
                            <label class="flex items-center">
                                <input type="checkbox" id="notify-matches" name="notify_new_matches" checked
                                       class="mr-2 rounded">
                                <span class="text-sm text-gray-700">Уведомлять о новых подходящих объектах</span>
                            </label>
                        </div>
                        <div class="flex justify-end space-x-3">
                            <button type="button" class="cancel-save-search px-4 py-2 text-gray-600 border border-gray-300 rounded-md hover:bg-gray-50">
                                Отмена
                            </button>
                            <button type="submit" class="px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700">
                                Сохранить
                            </button>
                        </div>
                    </form>
                </div>
            </div>
        `;

        // Add modal to page
        document.body.insertAdjacentHTML('beforeend', modalHTML);

        // Bind modal events
        document.querySelector('.cancel-save-search').addEventListener('click', () => {
            this.closeSaveSearchModal();
        });

        document.querySelector('#save-search-modal').addEventListener('click', (e) => {
            if (e.target.id === 'save-search-modal') {
                this.closeSaveSearchModal();
            }
        });

        document.querySelector('#save-search-form').addEventListener('submit', (e) => {
            e.preventDefault();
            this.submitSaveSearch();
        });
    }

    formatPrice(price) {
        if (price >= 1000000) {
            return (price / 1000000).toFixed(1) + 'млн';
        }
        return price.toLocaleString() + 'р';
    }

    closeSaveSearchModal() {
        const modal = document.querySelector('#save-search-modal');
        if (modal) {
            modal.remove();
        }
    }

    async submitSaveSearch() {
        const form = document.querySelector('#save-search-form');
        const formData = new FormData(form);
        const params = this.getCurrentSearchParams();

        // Determine if user is a manager - ENHANCED DEBUGGING
        console.log('🔍 SAVE SEARCH - Full window debug:', {
            window_manager_authenticated: window.manager_authenticated,
            window_user_authenticated: window.user_authenticated,
            window_isManager: window.isManager,
            window_current_manager: window.current_manager,
            typeof_manager_auth: typeof window.manager_authenticated
        });
        
        const isManager = Boolean(window.manager_authenticated);
        
        console.log('🎯 SAVE SEARCH - Manager decision:', {
            isManager: isManager,
            willUseEndpoint: isManager ? '/api/manager/saved-searches' : '/api/user/saved-searches'
        });
        
        // Choose appropriate endpoint and data format
        let endpoint, requestData;
        
        if (isManager) {
            // Manager endpoint expects filters object
            endpoint = '/api/manager/saved-searches';
            requestData = {
                name: formData.get('name'),
                filters: params
            };
        } else {
            // User endpoint expects flat data structure
            endpoint = '/api/user/saved-searches';
            requestData = {
                name: formData.get('name'),
                description: formData.get('description'),
                notify_new_matches: formData.has('notify_new_matches'),
                search_type: 'properties',
                ...params
            };
        }

        console.log('Saving search with data:', requestData);
        console.log('Request data:', { name: requestData.name, filters: requestData.filters || requestData });

        try {
            const response = await fetch(endpoint, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-Requested-With': 'XMLHttpRequest',
                    'X-CSRFToken': this.getCSRFToken()
                },
                credentials: 'same-origin',
                body: JSON.stringify(requestData)
            });

            const result = await response.json();

            if (result.success) {
                this.showNotification('Поиск сохранен успешно', 'success');
                this.closeSaveSearchModal();
                this.loadSavedSearches(); // Refresh saved searches list
            } else {
                this.showNotification('Ошибка при сохранении поиска: ' + result.error, 'error');
            }
        } catch (error) {
            console.error('Error saving search:', error);
            this.showNotification('Ошибка при сохранении поиска', 'error');
        }
    }

    async loadSavedSearches() {
        try {
            const response = await fetch('/api/searches', {
                method: 'GET',
                headers: {
                    'Content-Type': 'application/json',
                    'X-Requested-With': 'XMLHttpRequest'
                },
                credentials: 'same-origin'
            });
            
            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }
            
            const result = await response.json();

            if (result.success) {
                this.displaySavedSearches(result.searches);
            } else {
                console.error('Server error loading saved searches:', result.error);
            }
        } catch (error) {
            console.error('Error loading saved searches:', error);
        }
    }

    displaySavedSearches(searches) {
        const container = window.safeQuery ? window.safeQuery('#saved-searches-container') : document.querySelector('#saved-searches-container');
        if (!container) return;

        if (searches.length === 0) {
            container.innerHTML = '<p class="text-gray-500 text-center py-4">Сохраненных поисков нет</p>';
            return;
        }

        const searchesHTML = searches.map(search => `
            <div class="saved-search-item border rounded-lg p-4 mb-3 bg-white">
                <div class="flex justify-between items-start">
                    <div class="flex-1">
                        <h4 class="font-semibold text-lg">${search.name}</h4>
                        ${search.description ? `<p class="text-gray-600 text-sm mt-1">${search.description}</p>` : ''}
                        <div class="mt-2 text-xs text-gray-500">
                            Создан: ${new Date(search.created_at).toLocaleDateString('ru-RU')}
                            ${search.last_used ? ` • Использован: ${new Date(search.last_used).toLocaleDateString('ru-RU')}` : ''}
                        </div>
                        ${this.getSearchSummary(search)}
                    </div>
                    <div class="flex space-x-2 ml-4">
                        <button class="apply-search-btn px-3 py-1 bg-gradient-to-r from-[#0088CC] to-[#006699] text-white text-sm rounded hover:from-[#006699] hover:to-[#0088CC] transition-all" 
                                data-search-id="${search.id}">
                            Применить
                        </button>
                        <button class="delete-search-btn px-3 py-1 bg-red-600 text-white text-sm rounded hover:bg-red-700" 
                                data-search-id="${search.id}">
                            Удалить
                        </button>
                    </div>
                </div>
            </div>
        `).join('');

        container.innerHTML = searchesHTML;
    }

    getSearchSummary(search) {
        const parts = [];
        
        if (search.property_type) parts.push(search.property_type);
        if (search.location) parts.push('в ' + search.location);
        if (search.price_min || search.price_max) {
            let priceRange = '';
            if (search.price_min) priceRange += `от ${this.formatPrice(search.price_min)}`;
            if (search.price_max) priceRange += ` до ${this.formatPrice(search.price_max)}`;
            parts.push(priceRange);
        }
        if (search.developer) parts.push('от ' + search.developer);
        if (search.complex_name) parts.push('ЖК ' + search.complex_name);

        if (parts.length === 0) return '';

        return `<div class="mt-2 text-sm text-gray-600">${parts.join(', ')}</div>`;
    }

    async applySavedSearch(searchId) {
        try {
            console.log('Applying saved search:', searchId);
            
            // Determine the correct API endpoint based on search type
            let apiUrl;
            if (searchId.startsWith('sent-')) {
                // Manager search - remove 'sent-' prefix and use recommendations API
                const realSearchId = searchId.replace('sent-', '');
                apiUrl = `/api/recommendations/search_${realSearchId}/apply`;
                console.log('Applying manager search via recommendations API:', apiUrl);
            } else if (searchId.startsWith('manager-')) {
                // Manager search template - remove 'manager-' prefix
                const realSearchId = searchId.replace('manager-', '');
                apiUrl = `/api/manager/saved-searches/${realSearchId}/apply`;
                console.log('Applying manager search template:', apiUrl);
            } else {
                // Regular user search
                apiUrl = `/api/searches/${searchId}/apply`;
                console.log('Applying user search via searches API:', apiUrl);
            }
            
            const response = await fetch(apiUrl, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-Requested-With': 'XMLHttpRequest'
                },
                credentials: 'same-origin'
            });

            console.log('Response status:', response.status);
            
            // Check if response is HTML (error page) instead of JSON
            const contentType = response.headers.get('content-type');
            console.log('Response content-type:', contentType);

            if (!response.ok) {
                const errorText = await response.text();
                console.error('Error response:', errorText);
                throw new Error(`HTTP error! status: ${response.status}`);
            }

            const result = await response.json();
            console.log('Apply result:', result);

            if (result.success) {
                console.log('Applying search with result:', result);
                
                const searchUrl = result.search_url || (result.filters && result.filters.search_url);
                if (searchUrl) {
                    console.log('Redirecting to saved search_url:', searchUrl);
                    window.location.href = searchUrl;
                } else {
                    const filters = result.filters || {};
                    console.log('Filters to apply (legacy):', filters);
                    
                    const params = new URLSearchParams();
                    
                    for (const [key, value] of Object.entries(filters)) {
                        if (key === 'search_url') continue;
                        if (value && value !== '' && value !== '0') {
                            if (Array.isArray(value) && value.length > 0) {
                                value.forEach(v => {
                                    if (v && v !== '' && v !== '0') {
                                        // Handle parameter naming consistency for array parameters
                                        let paramKey = key;
                                        const arrayParams = [
                                            'rooms', 'districts', 'developers', 'object_classes', 
                                            'completion', 'building_types', 'renovation', 
                                            'features', 'building_released', 'floor_options'
                                        ];
                                        if (arrayParams.includes(key)) {
                                            if (!paramKey.endsWith('[]')) {
                                                paramKey = paramKey + '[]';
                                            }
                                        }
                                        params.append(paramKey, v);
                                    }
                                });
                            } else if (!Array.isArray(value)) {
                                params.set(key, value);
                            }
                        }
                    }

                    let citySlug = result.city || 'sochi';
                    if (filters.city) {
                        if (typeof filters.city === 'object' && filters.city.slug) {
                            citySlug = filters.city.slug;
                        } else if (typeof filters.city === 'string') {
                            citySlug = filters.city;
                        }
                    }
                    const url = `/${citySlug}/properties${params.toString() ? '?' + params.toString() : ''}`;
                    console.log('Redirecting to URL:', url);
                    window.location.href = url;
                }
            } else {
                console.error('Server error:', result.error);
                this.showNotification('Ошибка при применении поиска: ' + (result.error || 'Unknown error'), 'error');
            }
        } catch (error) {
            console.error('Error applying search:', error);
            this.showNotification('Ошибка при применении поиска', 'error');
        }
    }

    applySearchParams(search) {
        // Apply search parameters to current form
        const form = document.querySelector('#property-search-form') || document.querySelector('.search-form');
        if (!form) {
            // Redirect to search page with parameters
            const params = new URLSearchParams();
            Object.keys(search).forEach(key => {
                const value = search[key];
                if (value && key !== 'id' && key !== 'name' && key !== 'description' && value !== '0') {
                    if (Array.isArray(value)) {
                        value.forEach(v => {
                            let k = key;
                            // Ensure array parameters have [] suffix for backend consistency
                            const arrayParams = ['rooms', 'districts', 'developers', 'object_classes', 'completion', 'building_types', 'renovation', 'features', 'building_released', 'floor_options', 'object_class'];
                            if (arrayParams.includes(key) && !k.endsWith('[]')) k += '[]';
                            params.append(k, v);
                        });
                    } else {
                        let k = key;
                        // For non-array values that are expected to be arrays on backend
                        const arrayParams = ['rooms', 'districts', 'developers', 'object_classes', 'completion', 'building_types', 'renovation', 'features', 'building_released', 'floor_options', 'object_class'];
                        if (arrayParams.includes(key) && !k.endsWith('[]')) k += '[]';
                        params.set(k, value);
                    }
                }
            });
            
            // Add property_type specifically if it exists in search
            if (search.property_type && !params.has('property_type')) {
                params.set('property_type', search.property_type);
            }
            
            // Use city from search if available, otherwise default to 'sochi' (handle legacy nested objects)
            let citySlug = 'sochi';
            if (search.city) {
                if (typeof search.city === 'object' && search.city.slug) {
                    citySlug = search.city.slug;
                } else if (typeof search.city === 'string') {
                    citySlug = search.city;
                }
            }
            window.location.href = `/${citySlug}/properties?` + params.toString();
            return;
        }

        // Fill form fields
        Object.keys(search).forEach(key => {
            const field = form.querySelector(`[name="${key}"]`);
            if (field && search[key]) {
                field.value = search[key];
            }
        });

        // Trigger search
        if (typeof window.searchProperties === 'function') {
            window.searchProperties();
        } else {
            form.submit();
        }
    }

    applyFilters(filters) {
        console.log('Applying filters:', filters);
        
        // Check if we're on properties page
        if (window.location.pathname === '/properties') {
            // Apply filters directly to the properties page
            if (typeof window.applySearchFilters === 'function') {
                window.applySearchFilters(filters);
            } else {
                console.warn('applySearchFilters function not found, redirecting...');
                this.redirectWithFilters(filters);
            }
        } else {
            // Redirect to properties page with filters
            this.redirectWithFilters(filters);
        }
    }

    redirectWithFilters(filters) {
        const params = new URLSearchParams();
        
        // Convert filters to URL parameters
        Object.keys(filters).forEach(key => {
            const value = filters[key];
            if (value && value !== '' && !(Array.isArray(value) && value.length === 0)) {
                if (Array.isArray(value)) {
                    value.forEach(item => {
                        if (item && item !== '') {
                            params.append(key, item);
                        }
                    });
                } else {
                    params.set(key, value);
                }
            }
        });
        
        console.log('Redirecting to:', '/properties?' + params.toString());
        window.location.href = '/properties?' + params.toString();
    }

    async deleteSavedSearch(searchId) {
        if (!confirm('Удалить сохраненный поиск?')) {
            return;
        }

        try {
            const response = await fetch(`/api/searches/${searchId}`, {
                method: 'DELETE',
            });

            const result = await response.json();

            if (result.success) {
                this.showNotification('Поиск удален', 'success');
                
                // Immediately remove the card from DOM for instant feedback
                const searchCard = document.querySelector(`[data-search-id="${searchId}"]`)?.closest('.saved-search-item');
                if (searchCard) {
                    searchCard.style.transition = 'all 0.3s ease-out';
                    searchCard.style.opacity = '0';
                    searchCard.style.transform = 'translateX(20px)';
                    setTimeout(() => {
                        searchCard.remove();
                        
                        // Check if no searches left, show empty message
                        const container = document.querySelector('#saved-searches-container');
                        if (container && container.children.length === 0) {
                            container.innerHTML = '<p class="text-gray-500 text-center py-4">Сохраненных поисков нет</p>';
                        }
                    }, 300);
                }
                
                // Still refresh list to ensure sync with server
                this.loadSavedSearches();
            } else {
                this.showNotification('Ошибка при удалении поиска', 'error');
            }
        } catch (error) {
            console.error('Error deleting search:', error);
            this.showNotification('Ошибка при удалении поиска', 'error');
        }
    }

    showNotification(message, type = 'info') {
        if (typeof window.showToast === 'function') {
            window.showToast(message, type);
        }
    }
}

// ============================================
// СТАРЫЕ ФУНКЦИИ DROPDOWN УДАЛЕНЫ
// Теперь используется SavedSearchManager.openSaveSearchModal()
// ============================================

function generateSearchName() {
    const searchData = getCurrentSearchData();
    let searchName = 'Поиск ';
    
    if (searchData.rooms.length > 0) {
        searchName += searchData.rooms.join(', ') + ' ';
    }
    if (searchData.districts.length > 0) {
        searchName += 'в ' + searchData.districts.slice(0, 2).join(', ');
        if (searchData.districts.length > 2) {
            searchName += ` и ещё ${searchData.districts.length - 2}`;
        }
    }
    if (searchData.propertyClass && searchData.propertyClass.length > 0) {
        searchName += `, ${searchData.propertyClass.join(', ')}`;
    }
    if (searchData.wallMaterial && searchData.wallMaterial.length > 0) {
        searchName += `, ${searchData.wallMaterial.join(', ')}`;
    }
    if (searchData.floorsTotal && searchData.floorsTotal.length > 0) {
        searchName += `, ${searchData.floorsTotal.join(', ')}`;
    }
    if (searchData.priceFrom || searchData.priceTo) {
        searchName += `, ${searchData.priceFrom || '0'}-${searchData.priceTo || '∞'} млн`;
    }
    
    return searchName.trim() || `Поиск ${new Date().toLocaleDateString()}`;
}

function getCurrentSearchData() {
    // Get current active filters from the global activeFilters object if available
    if (typeof activeFilters !== 'undefined' && Object.keys(activeFilters).length > 0) {
        const data = {
            districts: activeFilters.districts || [],
            developers: activeFilters.developers || [],
            rooms: activeFilters.rooms || [],
            completion: activeFilters.completion || [],
            propertyClass: activeFilters.propertyClass || [],
            wallMaterial: activeFilters.wallMaterial || [],
            floorsTotal: activeFilters.floorsTotal || [],
            priceFrom: activeFilters.priceFrom || '',
            priceTo: activeFilters.priceTo || '',
            areaFrom: activeFilters.areaFrom || '',
            areaTo: activeFilters.areaTo || ''
        };
        return data;
    }
    
    // Collect from quick filters and advanced filters (no duplicates)
    const data = {
        districts: [
            ...Array.from(document.querySelectorAll('input[data-filter-type="district"]:checked')).map(el => el.value)
        ],
        developers: [
            ...Array.from(document.querySelectorAll('input[data-filter-type="developer"]:checked')).map(el => el.value),
            ...Array.from(document.querySelectorAll('input[data-filter="developer"]:checked')).map(el => el.value)
        ],
        rooms: [
            ...Array.from(document.querySelectorAll('input[data-filter-type="rooms"]:checked')).map(el => el.value)
        ],
        completion: [
            ...Array.from(document.querySelectorAll('input[data-filter-type="completion"]:checked')).map(el => el.value)
        ],
        propertyClass: Array.from(document.querySelectorAll('input[data-filter="property_class"]:checked')).map(el => el.value),
        wallMaterial: Array.from(document.querySelectorAll('input[data-filter="wall_material"]:checked')).map(el => el.value),
        floorsTotal: Array.from(document.querySelectorAll('input[data-filter="floors_total"]:checked')).map(el => el.value),
        priceFrom: document.getElementById('priceFrom')?.value || '',
        priceTo: document.getElementById('priceTo')?.value || '',
        areaFrom: document.getElementById('areaFrom')?.value || '',
        areaTo: document.getElementById('areaTo')?.value || ''
    };
    return data;
}

async function saveSearchWithOptions() {
    const searchName = document.getElementById('searchNameInput').value;
    const filterData = getCurrentSearchData();
    
    if (!searchName.trim()) {
        alert('Пожалуйста, введите название поиска');
        return;
    }
    
    // 🔥 CRITICAL FIX: Determine correct endpoint based on manager status
    const isManager = window.manager_authenticated === true;
    const endpoint = isManager ? '/api/manager/saved-searches' : '/api/user/saved-searches';
    
    console.log('🔍 SAVE SEARCH STANDALONE FUNCTION:', {
        isManager,
        endpoint,
        window_manager_authenticated: window.manager_authenticated,
        searchName,
        filterData
    });
    
    try {
        const response = await fetch(endpoint, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                name: searchName,
                filters: filterData,
                city_id: window.currentCityId || null  // Include city from global context
            })
        });
        
        if (!response.ok) {
            throw new Error('Failed to save search');
        }
        
        const data = await response.json();
        
        if (data.success) {
            alert('✅ Поиск сохранён!');
            closeSaveSearchDropdown();
            
            // Reload saved searches if manager exists
            if (window.savedSearchesManager) {
                window.savedSearchesManager.loadSavedSearches();
            }
        } else {
            alert('❌ Ошибка при сохранении поиска');
        }
    } catch (error) {
        console.error('Save search error:', error);
        alert('❌ Ошибка при сохранении поиска');
    }
}

// Export to window for backward compatibility
// toggleSaveSearchDropdown and closeSaveSearchDropdown removed - functions don't exist
window.saveSearchWithOptions = saveSearchWithOptions;
window.generateSearchName = generateSearchName;
window.getCurrentSearchData = getCurrentSearchData;

// ============================================
// INITIALIZATION
// ============================================

// Attach event listeners to save search button
// Initialize when DOM is ready with safety checks
function initSavedSearches() {
    try {
        // Check if DOM helpers are available
        if (typeof window.safeQuery === 'undefined') {
            setTimeout(function() {
                window.savedSearchesManager = new SavedSearchesManager();
                console.log('✅ SavedSearchesManager initialized');
            }, 100);
            return;
        }
        
        window.savedSearchesManager = new SavedSearchesManager();
        console.log('✅ SavedSearchesManager initialized');
    } catch (error) {
        console.error('Error loading saved searches:', error);
    }
}

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initSavedSearches);
} else {
    initSavedSearches();
}