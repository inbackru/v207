/**
 * SuperSearch v2.0 — Portal-based dropdown, city-aware, FA icons
 */

class SuperSearch {
    constructor() {
        this.config = {
            DEBOUNCE_DELAY: 200,
            CACHE_TTL: 300000,
            MAX_CACHE_SIZE: 100,
            MIN_QUERY_LENGTH: 2,
            MAX_SUGGESTIONS: 8,
            PRELOAD_POPULAR: false
        };

        this.cache = { suggestions: new Map() };

        this.state = {
            currentQuery: '',
            isLoading: false,
            abortController: null
        };

        this.metrics = { searchCount: 0, cacheHits: 0, avgResponseTime: 0, totalResponseTime: 0 };

        this.elements = {};

        this.init();
    }

    async init() {
        console.log('🚀 SuperSearch v2.0 - Initializing...');
        this.findSearchElements();
        this.setupEventListeners();
        this.injectStyles();
        window.addEventListener('resize', () => this.repositionAllDropdowns());
        window.addEventListener('scroll', () => this.repositionAllDropdowns(), { passive: true });
        console.log('✅ SuperSearch initialized successfully');
    }

    findSearchElements() {
        console.log('🔍 findSearchElements: Searching for inputs...');
        const hero = document.getElementById('hero-search');
        const property = document.getElementById('property-search');
        const desktop = document.getElementById('property-search-desktop');
        const modal = document.getElementById('modal-search-input');
        const custom = document.querySelector('[data-search-input]');

        console.log('🔍 Elements found:', { hero: !!hero, property: !!property, desktop: !!desktop, modal: !!modal, custom: !!custom });

        const searchInputs = [hero, property, desktop, modal, custom].filter(Boolean);

        searchInputs.forEach((input, index) => {
            const key = input.id || `search-${index}`;
            this.elements[key] = {
                input: input,
                dropdown: this.createPortalDropdown(input, key),
                debounceTimer: null,
                onSelectCallback: input.dataset.onSelect || null
            };
            input.dataset.superSearchInitialized = 'true';
            console.log(`✅ Initialized search input: ${key}`);
        });

        console.log(`Found ${searchInputs.length} search inputs`);
    }

    createPortalDropdown(input, key) {
        const id = `super-search-portal-${key}`;
        const existing = document.getElementById(id);
        if (existing) return existing;

        const dropdown = document.createElement('div');
        dropdown.id = id;
        dropdown.className = 'super-search-dropdown';
        dropdown.style.cssText = [
            'position:fixed',
            'z-index:99999',
            'background:#fff',
            'border-radius:12px',
            'box-shadow:0 8px 40px rgba(0,0,0,0.16)',
            'border:1px solid #e5e7eb',
            'display:none',
            'max-height:440px',
            'overflow-y:auto',
            'min-width:280px'
        ].join(';');

        dropdown.addEventListener('mousedown', (e) => e.preventDefault());

        dropdown.addEventListener('click', (e) => {
            e.preventDefault();
            e.stopPropagation();

            const item = e.target.closest('.suggestion-item');
            if (!item) return;

            const index = parseInt(item.dataset.suggestionIndex);
            const url = item.dataset.url;
            const suggestions = JSON.parse(dropdown.dataset.suggestions || '[]');
            const suggestion = suggestions[index];

            if (!suggestion) return;

            // ЖК/застройщик → фильтр на странице новостроек, а НЕ переход на страницу ЖК
            if (suggestion.type === 'complex' || suggestion.type === 'residential_complex') {
                this.hideDropdown(key);
                const el = this.elements[key];
                if (el && el.input) el.input.value = '';
                // Если мы уже на странице новостроек — применяем фильтр in-page
                const onListingPage = typeof window.handlePropertySuggestionSelect === 'function' &&
                    (window.location.pathname.includes('novostrojki') || window.location.pathname.includes('properties'));
                if (onListingPage) {
                    window.handlePropertySuggestionSelect(suggestion);
                } else {
                    // Иначе — строим URL новостроек для текущего города и добавляем фильтр
                    const cityMatch = window.location.pathname.match(/^\/([^\/]+)\//);
                    const citySlug = (cityMatch && cityMatch[1] && cityMatch[1] !== 'properties') ? cityMatch[1] : 'krasnodar';
                    const filterUrl = new URL(`/${citySlug}/novostrojki`, window.location.origin);
                    filterUrl.searchParams.set('residential_complex', suggestion.text || suggestion.title || '');
                    window.location.href = filterUrl.toString();
                }
                return;
            }

            if (url) {
                window.location.href = url;
            } else {
                this.performSearch(item.dataset.text || '', key);
            }
        });

        document.body.appendChild(dropdown);
        return dropdown;
    }

    positionDropdown(elementKey) {
        const element = this.elements[elementKey];
        if (!element) return;
        const input = element.input;
        const dropdown = element.dropdown;
        const rect = input.getBoundingClientRect();
        dropdown.style.top = (rect.bottom + 4) + 'px';
        dropdown.style.left = rect.left + 'px';
        dropdown.style.width = rect.width + 'px';
    }

    repositionAllDropdowns() {
        Object.keys(this.elements).forEach(key => {
            const el = this.elements[key];
            if (el && el.dropdown && el.dropdown.style.display !== 'none') {
                this.positionDropdown(key);
            }
        });
    }

    injectStyles() {
        if (document.getElementById('super-search-styles')) return;
        const styles = document.createElement('style');
        styles.id = 'super-search-styles';
        styles.textContent = `
            .super-search-dropdown { animation: ssDropIn 0.15s ease-out; }
            @keyframes ssDropIn {
                from { opacity: 0; transform: translateY(-6px); }
                to { opacity: 1; transform: translateY(0); }
            }
            .suggestion-item { transition: background 0.1s; }
            .suggestion-item:hover { background: #f8fafc; }
            .suggestion-item.active { background: #eff6ff; }
        `;
        document.head.appendChild(styles);
    }

    setupEventListeners() {
        Object.entries(this.elements).forEach(([key, element]) => {
            const { input, dropdown } = element;

            input.addEventListener('input', (e) => this.handleInput(e, key));
            input.addEventListener('focus', (e) => this.handleFocus(e, key));
            input.addEventListener('blur', () => {
                setTimeout(() => {
                    if (!dropdown.contains(document.activeElement)) {
                        this.hideDropdown(key);
                    }
                }, 200);
            });
            input.addEventListener('keydown', (e) => this.handleKeyDown(e, key));
            input.addEventListener('keypress', (e) => {
                if (e.key === 'Enter') {
                    e.preventDefault();
                    const active = dropdown.querySelector('.suggestion-item.active');
                    if (active) {
                        active.click();
                    } else {
                        this.performSearch(input.value, key);
                    }
                }
            });
        });

        document.addEventListener('click', (e) => this.handleGlobalClick(e));
    }

    handleInput(event, elementKey) {
        const query = event.target.value.trim();
        const element = this.elements[elementKey];

        if (this.state.abortController) this.state.abortController.abort();
        if (element.debounceTimer) clearTimeout(element.debounceTimer);

        if (query.length < this.config.MIN_QUERY_LENGTH) {
            // Show recommendations instead of hiding when field is empty/short
            if (query.length === 0) {
                this.fetchRecommendations(elementKey);
            } else {
                this.hideDropdown(elementKey);
            }
            return;
        }

        const cacheKey = `suggestions_${query.toLowerCase()}`;
        if (this.cache.suggestions.has(cacheKey)) {
            const cached = this.cache.suggestions.get(cacheKey);
            if (Date.now() - cached.timestamp < this.config.CACHE_TTL) {
                this.metrics.cacheHits++;
                this.renderSuggestions(cached.data, elementKey);
                this.showDropdown(elementKey);
                return;
            }
        }

        element.debounceTimer = setTimeout(() => {
            this.fetchSuggestions(query, elementKey);
        }, this.config.DEBOUNCE_DELAY);
    }

    handleFocus(event, elementKey) {
        const query = event.target.value.trim();
        if (query.length >= this.config.MIN_QUERY_LENGTH) {
            const cacheKey = `suggestions_${query.toLowerCase()}`;
            if (this.cache.suggestions.has(cacheKey)) {
                const cached = this.cache.suggestions.get(cacheKey);
                if (Date.now() - cached.timestamp < this.config.CACHE_TTL) {
                    this.renderSuggestions(cached.data, elementKey);
                    this.showDropdown(elementKey);
                    return;
                }
            }
            // Re-fetch if not cached
            this.fetchSuggestions(query, elementKey);
        } else {
            // Empty field on focus — show popular recommendations
            this.fetchRecommendations(elementKey);
        }
    }

    async fetchRecommendations(elementKey) {
        const RKEY = `__recs_${window.currentCityId || 0}`;
        const cached = this.cache.suggestions.get(RKEY);
        if (cached && (Date.now() - cached.timestamp < this.config.CACHE_TTL)) {
            this._renderRecommendations(cached.data, elementKey);
            return;
        }

        try {
            const cityId = window.currentCityId || '';
            const url = `/api/search/suggestions?q=&city_id=${encodeURIComponent(cityId)}`;
            const response = await fetch(url, { headers: { 'Accept': 'application/json' } });
            if (!response.ok) return;
            const data = await response.json();
            const items = Array.isArray(data) ? data : (data.suggestions || []);
            // Store in cache directly with our key
            this.cache.suggestions.set(RKEY, { data: items, timestamp: Date.now() });
            this._renderRecommendations(items, elementKey);
        } catch (e) {
            // silent fail — recommendations are non-critical
        }
    }

    _renderRecommendations(items, elementKey) {
        if (!items || items.length === 0) return;
        // Split into room-types and complexes for a nicer header layout
        const rooms = items.filter(s => s.type === 'rooms');
        const complexes = items.filter(s => s.type !== 'rooms');

        let html = '';

        if (rooms.length) {
            html += `<div style="padding:8px 14px 4px;font-size:11px;font-weight:600;color:#9ca3af;letter-spacing:.5px;text-transform:uppercase;">Популярные типы</div>`;
            html += `<div style="display:flex;flex-wrap:wrap;gap:6px;padding:4px 14px 8px;">`;
            rooms.forEach((s, i) => {
                const text = (s.text || '').replace(/</g,'&lt;');
                const sub  = (s.subtitle || '').replace(/</g,'&lt;');
                const url  = (s.url || '').replace(/"/g,'&quot;');
                html += `<div class="suggestion-item" data-url="${url}" data-text="${text}" data-suggestion-index="${i}"
                    style="display:inline-flex;align-items:center;gap:5px;background:#eff6ff;border:1px solid #dbeafe;border-radius:20px;padding:5px 11px;cursor:pointer;font-size:13px;font-weight:500;color:#1d4ed8;">
                    <i class="fas fa-home" style="font-size:11px;"></i> ${text}
                    ${sub ? `<span style="color:#6b7280;font-weight:400;font-size:11px;">(${sub})</span>` : ''}
                </div>`;
            });
            html += `</div>`;
        }

        if (complexes.length) {
            html += `<div style="padding:8px 14px 4px;font-size:11px;font-weight:600;color:#9ca3af;letter-spacing:.5px;text-transform:uppercase;">Популярные ЖК</div>`;
            complexes.forEach((s, i) => {
                const idx  = rooms.length + i;
                const text = (s.text || '').replace(/</g,'&lt;');
                const sub  = (s.subtitle || '').replace(/</g,'&lt;');
                const url  = (s.url || '').replace(/"/g,'&quot;');
                const leftIcon = s.image_url
                    ? `<div style="width:36px;height:36px;border-radius:8px;flex-shrink:0;background:#e0f0fa;position:relative;overflow:hidden;display:flex;align-items:center;justify-content:center;">
                           <i class="fas fa-building" style="font-size:12px;color:#0088CC;"></i>
                           <img src="${s.image_url}" referrerpolicy="no-referrer" style="position:absolute;inset:0;width:100%;height:100%;object-fit:cover;" onerror="this.remove()">
                       </div>`
                    : `<div style="width:36px;height:36px;border-radius:50%;background:#eff6ff;display:flex;align-items:center;justify-content:center;flex-shrink:0;">
                           <i class="fas fa-building" style="color:#0088CC;font-size:12px;"></i>
                       </div>`;
                html += `<div class="suggestion-item" data-url="${url}" data-text="${text}" data-suggestion-index="${idx}"
                    style="display:flex;align-items:center;gap:10px;padding:9px 14px;cursor:pointer;border-top:1px solid #f3f4f6;">
                    ${leftIcon}
                    <div style="flex:1;min-width:0;">
                        <div style="font-size:14px;font-weight:500;color:#111827;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">${text}</div>
                        ${sub ? `<div style="font-size:11px;color:#6b7280;margin-top:1px;">${sub}</div>` : ''}
                    </div>
                    <span style="font-size:11px;font-weight:500;color:#6b7280;background:#f3f4f6;padding:2px 7px;border-radius:20px;flex-shrink:0;">ЖК</span>
                </div>`;
            });
        }

        const dropdown = this.elements[elementKey].dropdown;
        dropdown.innerHTML = `<div style="padding:4px 0 6px;">${html}</div>`;
        dropdown.dataset.elementKey = elementKey;
        dropdown.dataset.suggestions = JSON.stringify(items);
        this.showDropdown(elementKey);
    }

    handleKeyDown(event, elementKey) {
        const dropdown = this.elements[elementKey].dropdown;
        const suggestions = dropdown.querySelectorAll('.suggestion-item');
        const active = dropdown.querySelector('.suggestion-item.active');

        if (event.key === 'ArrowDown') {
            event.preventDefault();
            this.navigateSuggestions(suggestions, active, 'down');
        } else if (event.key === 'ArrowUp') {
            event.preventDefault();
            this.navigateSuggestions(suggestions, active, 'up');
        } else if (event.key === 'Escape') {
            this.hideDropdown(elementKey);
        }
    }

    navigateSuggestions(suggestions, active, direction) {
        if (!suggestions.length) return;
        if (active) active.classList.remove('active');
        let newIndex = 0;
        if (active) {
            const ci = Array.from(suggestions).indexOf(active);
            newIndex = direction === 'down'
                ? (ci + 1) % suggestions.length
                : ci === 0 ? suggestions.length - 1 : ci - 1;
        }
        suggestions[newIndex].classList.add('active');
        suggestions[newIndex].scrollIntoView({ block: 'nearest' });
    }

    async fetchSuggestions(query, elementKey) {
        const startTime = performance.now();
        this.state.isLoading = true;

        try {
            this.state.abortController = new AbortController();
            const cityId = window.currentCityId || '';
            const url = `/api/search/suggestions?q=${encodeURIComponent(query)}&city_id=${encodeURIComponent(cityId)}`;

            const response = await fetch(url, {
                signal: this.state.abortController.signal,
                headers: { 'Accept': 'application/json' }
            });

            if (!response.ok) throw new Error(`HTTP ${response.status}`);

            const data = await response.json();
            const suggestions = Array.isArray(data) ? data : (data.suggestions || []);

            this.cacheResult('suggestions', query, suggestions);
            this.renderSuggestions(suggestions, elementKey);
            this.showDropdown(elementKey);

            const responseTime = performance.now() - startTime;
            this.updateMetrics(responseTime);

        } catch (error) {
            if (error.name !== 'AbortError') {
                console.warn('Search suggestions error:', error);
            }
        } finally {
            this.state.isLoading = false;
        }
    }

    renderSuggestions(suggestions, elementKey) {
        const dropdown = this.elements[elementKey].dropdown;

        if (!suggestions || suggestions.length === 0) {
            dropdown.innerHTML = '<div style="padding:16px;text-align:center;color:#6b7280;font-size:14px;">Ничего не найдено</div>';
            return;
        }

        const faIconMap = {
            'complex': 'fas fa-building',
            'residential_complex': 'fas fa-building',
            'developer': 'fas fa-user-tie',
            'district': 'fas fa-map-marker-alt',
            'street': 'fas fa-road',
            'address': 'fas fa-map-marker-alt',
            'city': 'fas fa-city',
            'settlement': 'fas fa-map-pin',
            'region': 'fas fa-globe-europe',
            'rooms': 'fas fa-home',
            'room_type': 'fas fa-home'
        };

        const typeNames = {
            'complex': 'ЖК',
            'residential_complex': 'ЖК',
            'developer': 'Застройщик',
            'district': 'Район',
            'street': 'Улица',
            'address': 'Адрес',
            'city': 'Город',
            'settlement': 'Населённый пункт',
            'rooms': 'Тип квартиры',
            'room_type': 'Тип квартиры'
        };
        const districtTypeNames = {
            'okrug': 'Округ',
            'microrayon': 'Микрорайон',
            'settlement': 'Поселение',
            'admin': 'Район',
        };

        const html = suggestions.map((s, index) => {
            const iconClass = s.icon || faIconMap[s.type] || 'fas fa-search';
            const typeName = (s.type === 'district' && s.district_type)
                ? (districtTypeNames[s.district_type] || 'Район')
                : (typeNames[s.type] || '');
            const text = (s.text || s.title || '').replace(/</g, '&lt;').replace(/>/g, '&gt;');
            const subtitle = (s.subtitle || '').replace(/</g, '&lt;').replace(/>/g, '&gt;');
            const safeUrl = (s.url || '').replace(/"/g, '&quot;');

            const leftIcon = s.image_url
                ? `<div style="width:38px;height:38px;border-radius:8px;flex-shrink:0;background:#e0f0fa;position:relative;overflow:hidden;display:flex;align-items:center;justify-content:center;">
                       <i class="fas fa-building" style="font-size:13px;color:#0088CC;"></i>
                       <img src="${s.image_url}" referrerpolicy="no-referrer" style="position:absolute;inset:0;width:100%;height:100%;object-fit:cover;" onerror="this.remove()">
                   </div>`
                : `<div style="width:36px;height:36px;border-radius:50%;background:#eff6ff;display:flex;align-items:center;justify-content:center;flex-shrink:0;">
                       <i class="${iconClass}" style="color:#0088CC;font-size:13px;"></i>
                   </div>`;

            return `<div class="suggestion-item" data-url="${safeUrl}" data-text="${text}" data-suggestion-index="${index}"
                style="display:flex;align-items:center;gap:10px;padding:9px 14px;cursor:pointer;border-bottom:1px solid #f3f4f6;">
                ${leftIcon}
                <div style="flex:1;min-width:0;">
                    <div style="font-size:14px;font-weight:500;color:#111827;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">${text}</div>
                    ${subtitle ? `<div style="font-size:11px;color:#6b7280;margin-top:1px;">${subtitle}</div>` : ''}
                </div>
                ${typeName ? `<span style="font-size:11px;font-weight:500;color:#6b7280;background:#f3f4f6;padding:2px 7px;border-radius:20px;flex-shrink:0;">${typeName}</span>` : ''}
            </div>`;
        }).join('');

        dropdown.innerHTML = `<div style="padding:6px 0;">${html}</div>`;
        dropdown.dataset.elementKey = elementKey;
        dropdown.dataset.suggestions = JSON.stringify(suggestions);
    }

    showDropdown(elementKey) {
        const element = this.elements[elementKey];
        if (!element) return;
        // Skip if input is not visible (e.g., hidden hero-search on properties page)
        const rect = element.input.getBoundingClientRect();
        if (rect.width < 10 || rect.bottom < 10) return;
        this.positionDropdown(elementKey);
        element.dropdown.style.display = 'block';
    }

    hideDropdown(elementKey) {
        const element = this.elements[elementKey];
        if (!element) return;
        element.dropdown.style.display = 'none';
    }

    hideAllDropdowns() {
        Object.keys(this.elements).forEach(key => this.hideDropdown(key));
    }

    handleGlobalClick(event) {
        const isSearchClick = Object.values(this.elements).some(element =>
            element.input.contains(event.target) || element.dropdown.contains(event.target)
        );
        if (!isSearchClick) this.hideAllDropdowns();
    }

    cacheResult(type, query, data) {
        const cache = this.cache[type] || this.cache.suggestions;
        const key = `${type}_${query.toLowerCase()}`;
        if (cache.size >= this.config.MAX_CACHE_SIZE) {
            cache.delete(cache.keys().next().value);
        }
        cache.set(key, { data, timestamp: Date.now() });
    }

    updateMetrics(responseTime) {
        this.metrics.searchCount++;
        this.metrics.totalResponseTime += responseTime;
        this.metrics.avgResponseTime = this.metrics.totalResponseTime / this.metrics.searchCount;
    }

    performSearch(query, elementKey) {
        if (!query.trim()) return;
        this.hideDropdown(elementKey);
        const citySlug = window.currentCitySlug || 'krasnodar';
        window.location.href = '/' + citySlug + '/novostrojki?search=' + encodeURIComponent(query);
    }

    getMetrics() { return { ...this.metrics }; }
    clearCache() { Object.values(this.cache).forEach(c => c.clear()); }
    destroy() {
        Object.values(this.elements).forEach(el => {
            if (el.debounceTimer) clearTimeout(el.debounceTimer);
        });
        if (this.state.abortController) this.state.abortController.abort();
    }
}

let superSearchInstance;

document.addEventListener('DOMContentLoaded', () => {
    superSearchInstance = new SuperSearch();
    window.superSearch = superSearchInstance;
});

if (typeof module !== 'undefined' && module.exports) {
    module.exports = SuperSearch;
}
