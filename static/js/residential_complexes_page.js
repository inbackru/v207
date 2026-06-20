// Search functionality
function setupComplexSearch() {
    const searchInput = document.getElementById('complex-search');
    const suggestionsContainer = document.getElementById('complex-searchSuggestions');
    
    // Create search suggestions
    const suggestions = [];
    allComplexes.forEach(complex => {
        suggestions.push(complex.name);
        suggestions.push(complex.developer);
        suggestions.push(complex.district);
        // Strip house number from location to get street-level suggestion
        if (complex.location) {
            const streetOnly = complex.location.replace(/,\s*\d[\d/]*[а-яА-Яa-zA-Z]*\s*$/, '').trim();
            suggestions.push(streetOnly || complex.location);
        }
    });
    
    const uniqueSuggestions = [...new Set(suggestions)].filter(Boolean);
    
    let isInitialLoad = true;
    
    searchInput.addEventListener('input', function() {
        const query = this.value.toLowerCase().trim();
        
        // Live filter on every keystroke (300ms debounce)
        clearTimeout(searchInput._debTimer);
        searchInput._debTimer = setTimeout(function() { applyComplexFilters(); }, 300);
        
        if (query.length < 2) {
            suggestionsContainer.classList.add('hidden');
            isInitialLoad = false;
            return;
        }
        
        isInitialLoad = false;
        
        // Local matches (ЖК names, developers, districts)
        const matchedLocal = uniqueSuggestions
            .filter(suggestion => suggestion.toLowerCase().includes(query))
            .slice(0, 4);

        // Fetch API suggestions (streets, addresses, districts) in parallel
        const cityId = window.currentCityId || '';
        fetch(`/api/search/suggestions?q=${encodeURIComponent(query)}&city_id=${cityId}`)
            .then(r => r.ok ? r.json() : [])
            .then(apiItems => {
                // Combine: local first, then API address/street/district results
                const apiFiltered = (apiItems || [])
                    .filter(s => s.type === 'address' || s.type === 'street' || s.type === 'district')
                    .slice(0, 4);

                const allSuggestions = [];
                matchedLocal.forEach(s => allSuggestions.push({ text: s, type: 'local' }));
                apiFiltered.forEach(s => allSuggestions.push(s));

                if (allSuggestions.length > 0) {
                    const suggestionHTML = allSuggestions.map(item => {
                        const label = item.type === 'local'
                            ? `<i class="fas fa-building mr-2 text-gray-400"></i>${item.text.replace(/"/g, '&quot;')}`
                            : `<i class="fas fa-map-marker-alt mr-2 text-[#0088CC]"></i><span class="font-medium">${item.text.replace(/"/g, '&quot;')}</span><span class="ml-2 text-xs text-gray-400">${item.subtitle || ''}</span>`;
                        const val = item.text.replace(/'/g, "\\'").replace(/"/g, '&quot;');
                        const url = item.url || null;
                        const clickAction = url
                            ? `window.location.href='${url}'`
                            : `selectComplexSuggestion('${val}')`;
                        return `<div class="px-4 py-2 hover:bg-gray-50 cursor-pointer text-sm" onclick="${clickAction}">${label}</div>`;
                    }).join('');
                    suggestionsContainer.innerHTML = suggestionHTML;
                    suggestionsContainer.classList.remove('hidden');
                } else {
                    suggestionsContainer.classList.add('hidden');
                }
            })
            .catch(() => {
                // Fallback to local only
                if (matchedLocal.length > 0) {
                    suggestionsContainer.innerHTML = matchedLocal.map(s =>
                        `<div class="px-4 py-2 hover:bg-gray-100 cursor-pointer text-sm" onclick="selectComplexSuggestion('${s.replace(/'/g, "\\'").replace(/"/g, "&quot;")}')"><i class="fas fa-search mr-2 text-gray-400"></i>${s.replace(/"/g, '&quot;')}</div>`
                    ).join('');
                    suggestionsContainer.classList.remove('hidden');
                } else {
                    suggestionsContainer.classList.add('hidden');
                }
            });
    });
    
    // Hide suggestions when clicking outside
    document.addEventListener('click', function(e) {
        if (!searchInput.contains(e.target) && !suggestionsContainer.contains(e.target)) {
            suggestionsContainer.classList.add('hidden');
        }
    });
}

function selectComplexSuggestion(suggestion) {
    document.getElementById('complex-search').value = suggestion;
    document.getElementById('complex-searchSuggestions').classList.add('hidden');
    applyComplexFilters();
}

// Helper function to parse completion dates for sorting
function parseCompletionDate(dateString) {
    if (!dateString) return new Date('2030-12-31'); // Future date for unknown dates
    
    // Handle different date formats
    const str = dateString.toLowerCase().trim();
    
    // Extract year and quarter
    const yearMatch = str.match(/(\d{4})/);
    const quarterMatch = str.match(/(\d)\s*кв/);
    
    if (yearMatch) {
        const year = parseInt(yearMatch[1]);
        let month = 12; // Default to end of year
        
        if (quarterMatch) {
            const quarter = parseInt(quarterMatch[1]);
            // Convert quarter to month (end of quarter)
            month = quarter * 3;
        }
        
        return new Date(year, month - 1, 1); // month is 0-indexed
    }
    
    // Try to parse as regular date
    const parsed = new Date(dateString);
    return isNaN(parsed.getTime()) ? new Date('2030-12-31') : parsed;
}

// ── Mobile filter chip helpers ──────────────────────────────────────────────
function toggleMobileRoomChip(btn) {
    btn.classList.toggle('active-room');
    if (btn.classList.contains('active-room')) {
        btn.classList.add('border-[#0088CC]', 'bg-[#0088CC]', 'text-white');
        btn.classList.remove('border-gray-200', 'text-gray-700', 'bg-white');
    } else {
        btn.classList.remove('border-[#0088CC]', 'bg-[#0088CC]', 'text-white');
        btn.classList.add('border-gray-200', 'text-gray-700', 'bg-white');
    }
    updateMobileFilterCount();
}

// ===== Фильтры карты (complexFiltersSheet) =====
function _mapChipActivate(btn) {
    btn.dataset.active = 'true';
    btn.style.cssText = 'border-color:#0088CC !important;background:#0088CC !important;color:white !important;';
}
function _mapChipDeactivate(btn) {
    btn.dataset.active = 'false';
    btn.style.cssText = '';
}

function toggleMapRoomChip(btn) {
    const isActive = btn.dataset.active === 'true';
    if (isActive) { _mapChipDeactivate(btn); }
    else { _mapChipActivate(btn); }
    updateMapSheetCount();
}

function toggleMapStatusChip(btn) {
    document.querySelectorAll('.map-status-chip').forEach(c => _mapChipDeactivate(c));
    _mapChipActivate(btn);
    const sel = document.getElementById('map-sheet-status-filter');
    if (sel) sel.value = btn.dataset.statusValue || '';
    updateMapSheetCount();
}

function toggleMapYearChip(btn) {
    document.querySelectorAll('.map-year-chip').forEach(c => _mapChipDeactivate(c));
    _mapChipActivate(btn);
    const sel = document.getElementById('map-sheet-year-filter');
    if (sel) sel.value = btn.dataset.yearValue || '';
    updateMapSheetCount();
}

function toggleMapClassChip(btn) {
    document.querySelectorAll('.map-class-chip').forEach(c => _mapChipDeactivate(c));
    _mapChipActivate(btn);
    const sel = document.getElementById('map-sheet-class-filter');
    if (sel) sel.value = btn.dataset.classValue || '';
    updateMapSheetCount();
}

function updateMapSheetCount() {
    if (!window.allComplexes || !window.allComplexes.length) return;
    // Читаем значения прямо с активных чипов
    const activeStatusChip = document.querySelector('.map-status-chip[data-active="true"]');
    const status = activeStatusChip ? (activeStatusChip.dataset.statusValue || '') : '';
    const activeClassChip = document.querySelector('.map-class-chip[data-active="true"]');
    const objectClass = activeClassChip ? (activeClassChip.dataset.classValue || '') : '';
    const activeYearChip = document.querySelector('.map-year-chip[data-active="true"]');
    const year = activeYearChip ? (activeYearChip.dataset.yearValue || '') : '';
    const priceFrom = parseFloat(document.getElementById('complexPriceFrom')?.value);
    const priceTo = parseFloat(document.getElementById('complexPriceTo')?.value);
    const activeRooms = Array.from(document.querySelectorAll('.map-room-chip')).filter(b =>
        b.dataset.active === 'true'
    ).map(b => b.dataset.rooms || '');

    let count = window.allComplexes.filter(complex => {
        // Статус: фильтруем только по полю status, без требования наличия квартир
        if (status === 'Сдан') {
            if (complex.status !== 'Сдан') return false;
        } else if (status === 'Строится') {
            if (complex.status === 'Сдан') return false;
        } else if (status === 'Скоро') {
            if (complex.status !== 'Скоро') return false;
        }
        // Класс жилья
        if (objectClass && complex.object_class !== objectClass && complex.housing_class !== objectClass) return false;
        // Год сдачи
        if (year) {
            const y = complex.build_year;
            if (!y || String(y) !== year) return false;
        }
        // Цена
        if (!isNaN(priceFrom) || !isNaN(priceTo)) {
            const price = (complex.real_price_from || complex.price_from || 0) / 1000000;
            if (!isNaN(priceFrom) && price < priceFrom) return false;
            if (!isNaN(priceTo) && price > priceTo) return false;
        }
        // Комнатность
        if (activeRooms.length > 0) {
            if (!complex.room_details) return false;
            const _matchesRoom = (rv, roomDetails) => {
                if (rv === 'студия') return roomDetails['Студия'] && roomDetails['Студия'].count > 0;
                if (rv === '4+-комн') {
                    return Object.keys(roomDetails).some(k => {
                        const m = k.match(/^(\d+)-комн$/);
                        return m && parseInt(m[1]) >= 4 && roomDetails[k].count > 0;
                    });
                }
                return roomDetails[rv] && roomDetails[rv].count > 0;
            };
            if (!activeRooms.some(rv => _matchesRoom(rv, complex.room_details))) return false;
        }
        return true;
    }).length;

    const span = document.getElementById('mapSheetCount');
    if (span) span.textContent = count;
}

function resetMapSheetFilters() {
    document.querySelectorAll('.map-room-chip').forEach(c => _mapChipDeactivate(c));
    const anyStatus = document.querySelector('.map-status-chip[data-status-value=""]');
    if (anyStatus) toggleMapStatusChip(anyStatus);
    const anyYear = document.querySelector('.map-year-chip[data-year-value=""]');
    if (anyYear) toggleMapYearChip(anyYear);
    const anyClass = document.querySelector('.map-class-chip[data-class-value=""]');
    if (anyClass) toggleMapClassChip(anyClass);
    const pf = document.getElementById('complexPriceFrom');
    const pt = document.getElementById('complexPriceTo');
    if (pf) pf.value = '';
    if (pt) pt.value = '';
    updateMapSheetCount();
}

function applyComplexMapFilters() {
    // Читаем значения из активных чипов (не из <select> — они пустые)
    const activeStatusChip = document.querySelector('.map-status-chip[data-active="true"]');
    const status = activeStatusChip ? (activeStatusChip.dataset.statusValue || '') : '';

    const activeYearChip = document.querySelector('.map-year-chip[data-active="true"]');
    const yearVal = activeYearChip ? parseInt(activeYearChip.dataset.yearValue || '') : null;
    const year = (!isNaN(yearVal) && yearVal) ? yearVal : null;

    const activeClassChip = document.querySelector('.map-class-chip[data-active="true"]');
    const objectClass = activeClassChip ? (activeClassChip.dataset.classValue || '') : '';

    const priceFrom = parseFloat(document.getElementById('complexPriceFrom')?.value) || null;
    const priceTo = parseFloat(document.getElementById('complexPriceTo')?.value) || null;

    const activeRooms = Array.from(document.querySelectorAll('.map-room-chip[data-active="true"]'))
        .map(b => b.dataset.rooms || '');

    const filters = {
        statuses: status ? [status] : [],
        yearFrom: year,
        yearTo: year,
        classes: objectClass ? [objectClass] : [],
        priceFrom,
        priceTo,
        rooms: activeRooms,
        developers: [],
        districts: []
    };

    if (typeof filterComplexMarkers === 'function') {
        const count = filterComplexMarkers(filters);
        updateComplexFilterButton(count);
    }
}

// ===== Конец фильтров карты =====

function toggleMobileStatusChip(btn) {
    document.querySelectorAll('.mobile-status-chip').forEach(c => {
        c.style.cssText = '';
        c.classList.remove('active-status', 'border-[#0088CC]', 'bg-[#0088CC]', 'text-white');
        c.classList.add('border-gray-200', 'text-gray-700', 'bg-white');
    });
    btn.style.cssText = 'border-color:#0088CC;background:#0088CC;color:white;';
    btn.classList.add('active-status');
    btn.classList.remove('border-gray-200', 'text-gray-700', 'bg-white');
    const sel = document.getElementById('status-filter-mobile');
    if (sel) sel.value = btn.dataset.statusValue || '';
    updateMobileFilterCount();
}

function toggleMobileYearChip(btn) {
    document.querySelectorAll('.mobile-year-chip').forEach(c => {
        c.style.cssText = '';
        c.classList.remove('active-year', 'border-[#0088CC]', 'bg-[#0088CC]', 'text-white');
        c.classList.add('border-gray-200', 'text-gray-700', 'bg-white');
    });
    btn.style.cssText = 'border-color:#0088CC;background:#0088CC;color:white;';
    btn.classList.add('active-year');
    btn.classList.remove('border-gray-200', 'text-gray-700', 'bg-white');
    const sel = document.getElementById('completion-year-filter-mobile');
    if (sel) sel.value = btn.dataset.yearValue || '';
    updateMobileFilterCount();
}

function toggleMobileFloorsChip(btn) {
    document.querySelectorAll('.mobile-floors-chip').forEach(c => {
        c.classList.remove('active-floors', 'border-[#0088CC]', 'bg-[#0088CC]', 'text-white');
        c.classList.add('border-gray-200', 'text-gray-700', 'bg-white');
    });
    btn.classList.add('active-floors', 'border-[#0088CC]', 'bg-[#0088CC]', 'text-white');
    btn.classList.remove('border-gray-200', 'text-gray-700', 'bg-white');
    const sel = document.getElementById('floors-filter-mobile');
    if (sel) sel.value = btn.dataset.floorsValue || '';
    updateMobileFilterCount();
}

function toggleMobileClassOption(label, value) {
    document.querySelectorAll('.mobile-class-option').forEach(l => {
        l.classList.remove('border-[#0088CC]', 'bg-blue-50');
        l.querySelector('.mobile-radio-circle').classList.remove('border-[#0088CC]', 'bg-[#0088CC]');
        l.querySelector('.mobile-radio-circle').classList.add('border-gray-300');
    });
    label.classList.add('border-[#0088CC]', 'bg-blue-50');
    const circle = label.querySelector('.mobile-radio-circle');
    circle.classList.remove('border-gray-300');
    circle.classList.add('border-[#0088CC]', 'bg-[#0088CC]');
    const sel = document.getElementById('object-class-filter-mobile');
    if (sel) sel.value = value;
    updateMobileFilterCount();
}

function updateMobileFilterCount() {
    if (!window.allComplexes) {
        // allComplexes ещё не загружен — оставляем серверное значение как есть
        return;
    }
    // Quick dry-run filter to count
    const roomBtns = Array.from(document.querySelectorAll('.mobile-room-chip.active-room'));
    const selectedRooms = roomBtns.map(b => b.dataset.roomValue || '');
    const status = document.getElementById('status-filter-mobile')?.value || '';
    const objectClass = document.getElementById('object-class-filter-mobile')?.value || '';
    const year = document.getElementById('completion-year-filter-mobile')?.value || '';
    const floors = document.getElementById('floors-filter-mobile')?.value || '';
    const priceFrom = parseFloat(document.getElementById('price-range-from-mobile')?.value || '');
    const priceTo   = parseFloat(document.getElementById('price-range-to-mobile')?.value   || '');

    let count = window.allComplexes.filter(complex => {
        const hasApts = (complex.available_apartments || complex.apartments_count || 0) > 0;
        if (status === 'Проданы') { if (hasApts) return false; }
        else if (status === 'Сдан') { if (!(complex.status === 'Сдан' && hasApts)) return false; }
        else if (status === 'Строится') { if (!(complex.status !== 'Сдан' && hasApts)) return false; }
        else { if (!hasApts) return false; }

        if (objectClass && complex.object_class !== objectClass && complex.housing_class !== objectClass) return false;

        if (year) {
            const y = complex.completion_year || complex.build_year;
            if (!y || y.toString() !== year) return false;
        }
        if (floors) {
            const f = complex.max_floors || 0;
            if (floors === 'low' && !(f >= 1 && f <= 5)) return false;
            if (floors === 'medium' && !(f >= 6 && f <= 10)) return false;
            if (floors === 'high' && !(f > 10)) return false;
        }
        if (selectedRooms.length > 0) {
            function __nr(v) {
                const s = String(v).toLowerCase().trim();
                if (s === '0' || s.includes('студ')) return 0;
                const n = parseInt(s);
                if (!isNaN(n)) return n >= 4 ? 4 : n;
                if (s.includes('4+') || (s.startsWith('4') && !s.startsWith('40'))) return 4;
                if (s.startsWith('1')) return 1;
                if (s.startsWith('2')) return 2;
                if (s.startsWith('3')) return 3;
                return -1;
            }
            const selNums = [...new Set(selectedRooms.map(__nr).filter(n => n >= 0))];
            if (selNums.length > 0) {
                const roomList = (complex.available_rooms && complex.available_rooms.length > 0)
                    ? complex.available_rooms : Object.keys(complex.real_room_distribution || {});
                // Если у ЖК нет данных о комнатах — не исключаем его
                if (roomList.length > 0) {
                    const roomNums = roomList.map(__nr).filter(n => n >= 0);
                    if (!selNums.some(sel => roomNums.some(r => sel === 4 ? r >= 4 : r === sel))) return false;
                }
            }
        }
        if (!isNaN(priceFrom) || !isNaN(priceTo)) {
            const price = (complex.real_price_from || complex.price_from || 0) / 1000000;
            if (!isNaN(priceFrom) && price < priceFrom) return false;
            if (!isNaN(priceTo) && price > priceTo) return false;
        }
        return true;
    }).length;

    const applyBtn = document.getElementById('mobile-apply-count');
    if (applyBtn) applyBtn.textContent = count;
    const label = document.getElementById('mobile-filter-count-label');
    const ending = count === 1 ? ' жилой комплекс' : count >= 2 && count <= 4 ? ' жилых комплекса' : ' жилых комплексов';
    if (label) label.textContent = count + ending;
}

function resetMobileFilters() {
    document.querySelectorAll('.mobile-room-chip.active-room').forEach(b => toggleMobileRoomChip(b));
    const anyStatus = document.querySelector('.mobile-status-chip[data-status-value=""]');
    if (anyStatus) toggleMobileStatusChip(anyStatus);
    const anyYear = document.querySelector('.mobile-year-chip[data-year-value=""]');
    if (anyYear) toggleMobileYearChip(anyYear);
    const anyFloors = document.querySelector('.mobile-floors-chip[data-floors-value=""]');
    if (anyFloors) toggleMobileFloorsChip(anyFloors);
    const anyClass = document.querySelector('.mobile-class-option');
    if (anyClass) toggleMobileClassOption(anyClass, '');
    const pf = document.getElementById('price-range-from-mobile');
    const pt = document.getElementById('price-range-to-mobile');
    if (pf) pf.value = '';
    if (pt) pt.value = '';
    const dm = document.getElementById('district-filter-mobile');
    if (dm) dm.value = '';
    const dvm = document.getElementById('developer-filter-mobile');
    if (dvm) dvm.value = '';
    updateMobileFilterCount();
}

function syncMobileDistrictFilter() {
    updateMobileFilterCount();
}

function syncMobileDeveloperFilter() {
    updateMobileFilterCount();
}
// ── End mobile filter chip helpers ──────────────────────────────────────────

// Apply filters (make it globally accessible)
window.applyComplexFilters = function() {
    console.log('🔍 applyComplexFilters called, total complexes:', allComplexes.length);
    
    // Start with all complexes, not just displayed ones
    let filtered = [...allComplexes];
    
    // Search filter - check both mobile and desktop inputs
    const desktopSearch = document.getElementById('complex-search');
    const mobileSearch = document.getElementById('complex-search-mobile');
    const searchQuery = (desktopSearch?.value || mobileSearch?.value || '').toLowerCase().trim();
    if (searchQuery) {
        filtered = filtered.filter(complex => {
            return complex.name.toLowerCase().includes(searchQuery) ||
                   complex.developer.toLowerCase().includes(searchQuery) ||
                   complex.district.toLowerCase().includes(searchQuery) ||
                   complex.location.toLowerCase().includes(searchQuery);
        });
    }
    
    // Complex Type filter (residential vs cottage)
    const complexTypeRadio = document.querySelector('[data-filter-type="complex-type"]:checked');
    if (complexTypeRadio && complexTypeRadio.value) {
        const selectedType = complexTypeRadio.value;
        filtered = filtered.filter(complex => {
            return complex.complex_type === selectedType;
        });
    }
    
    // Status filter — по умолчанию скрываем ЖК без квартир
    const status = document.getElementById('status-filter')?.value
                || document.getElementById('status-filter-mobile')?.value;
    filtered = filtered.filter(complex => {
        const hasApts = (complex.available_apartments || complex.apartments_count || 0) > 0;
        if (status === 'Проданы') return !hasApts;
        if (status === 'Сдан') return complex.status === 'Сдан' && hasApts;
        if (status === 'Строится') return complex.status !== 'Сдан' && hasApts;
        return hasApts; // по умолчанию — только с квартирами
    });
    
    // Object Class filter — read desktop or mobile
    const objectClass = (document.getElementById('object-class-filter')?.value || '')
                     || (document.getElementById('object-class-filter-mobile')?.value || '');
    if (objectClass) {
        filtered = filtered.filter(complex =>
            complex.object_class === objectClass ||
            complex.housing_class === objectClass ||
            complex.class === objectClass
        );
    }

    // Completion Year filter — read desktop or mobile
    const completionYear = (document.getElementById('completion-year-filter')?.value || '')
                        || (document.getElementById('completion-year-filter-mobile')?.value || '');
    if (completionYear) {
        filtered = filtered.filter(complex => {
            const year = complex.completion_year || complex.construction_end_year || complex.build_year;
            return year && year.toString() === completionYear;
        });
    }

    // Floors filter — read desktop or mobile
    const floors = (document.getElementById('floors-filter')?.value || '')
                || (document.getElementById('floors-filter-mobile')?.value || '');
    if (floors) {
        filtered = filtered.filter(complex => {
            const floorCount = complex.max_floors || complex.floors || complex.floors_count || 0;
            if (floors === 'low') return floorCount >= 1 && floorCount <= 5;
            if (floors === 'medium') return floorCount >= 6 && floorCount <= 10;
            if (floors === 'high') return floorCount > 10;
            return true;
        });
    }

    // Rooms filter — pill chips (mobile) + checkboxes (desktop/panel)
    const selectedRooms = Array.from(document.querySelectorAll(
        '[data-filter-type="rooms"].active-room, ' +
        '[data-filter-type="rooms"].active, ' +
        '.mobile-room-chip.active-room, ' +
        'input[data-filter-type="rooms"]:checked, ' +
        'input[data-filter-type="complex-rooms"]:checked, ' +
        'input[data-filter-type="complex-rooms-panel"]:checked'
    )).map(el => el.dataset.roomValue || el.value);
    if (selectedRooms.length > 0) {
        // Normalize any room string/value → canonical number (0=studio,1,2,3,4=4+)
        function _normalizeRoom(v) {
            const s = String(v).toLowerCase().trim();
            if (s === '0' || s.includes('студ')) return 0;
            const n = parseInt(s);
            if (!isNaN(n)) return n >= 4 ? 4 : n;
            if (s.includes('4+') || (s.startsWith('4') && !s.startsWith('40'))) return 4;
            if (s.startsWith('1')) return 1;
            if (s.startsWith('2')) return 2;
            if (s.startsWith('3')) return 3;
            return -1;
        }
        const selectedNums = [...new Set(selectedRooms.map(_normalizeRoom).filter(n => n >= 0))];
        if (selectedNums.length > 0) {
            filtered = filtered.filter(complex => {
                const roomList = (complex.available_rooms && complex.available_rooms.length > 0)
                    ? complex.available_rooms
                    : Object.keys(complex.real_room_distribution || {});
                if (roomList.length === 0) return false;
                const roomNums = roomList.map(_normalizeRoom).filter(n => n >= 0);
                return selectedNums.some(sel => roomNums.some(r => sel === 4 ? r >= 4 : r === sel));
            });
        }
    }

    // Price range filter — read desktop or mobile
    const priceFrom = parseFloat((document.getElementById('price-range-from')?.value || '') || (document.getElementById('price-range-from-mobile')?.value || ''));
    const priceTo   = parseFloat((document.getElementById('price-range-to')?.value   || '') || (document.getElementById('price-range-to-mobile')?.value   || ''));
    if (!isNaN(priceFrom) || !isNaN(priceTo)) {
        filtered = filtered.filter(complex => {
            const price = (complex.real_price_from || complex.price_from || 0) / 1000000;
            let matches = true;
            if (!isNaN(priceFrom)) matches = matches && price >= priceFrom;
            if (!isNaN(priceTo)) matches = matches && price <= priceTo;
            return matches;
        });
    }
    
    // Sort
    const sortType = document.getElementById('sort-select').value;
    switch (sortType) {
        case 'name-asc':
            filtered.sort((a, b) => a.name.localeCompare(b.name));
            break;
        case 'name-desc':
            filtered.sort((a, b) => b.name.localeCompare(a.name));
            break;
        case 'price-asc':
            filtered.sort((a, b) => {
                const priceA = a.real_price_from || a.price_from || 0;
                const priceB = b.real_price_from || b.price_from || 0;
                return priceA - priceB;
            });
            break;
        case 'price-desc':
            filtered.sort((a, b) => {
                const priceA = a.real_price_from || a.price_from || 0;
                const priceB = b.real_price_from || b.price_from || 0;
                return priceB - priceA;
            });
            break;
        case 'completion-asc':
            filtered.sort((a, b) => {
                const dateA = parseCompletionDate(a.completion_date);
                const dateB = parseCompletionDate(b.completion_date);
                return dateA - dateB;
            });
            break;
        case 'completion-desc':
            filtered.sort((a, b) => {
                const dateA = parseCompletionDate(a.completion_date);
                const dateB = parseCompletionDate(b.completion_date);
                return dateB - dateA;
            });
            break;
        case 'apartments-desc':
            filtered.sort((a, b) => b.apartments_count - a.apartments_count);
            break;
        case 'apartments-asc':
            filtered.sort((a, b) => a.apartments_count - b.apartments_count);
            break;
    }
    
    console.log('✅ Filtering complete:', filtered.length, 'complexes after filters');
    
    filteredComplexes = filtered;
    updateComplexesList(filtered);
    updateResultsCount(filtered.length);
    
    // Update mini-map markers to match current filter
    updateMiniMapMarkers(filtered);

    // Filter sidebar objects by visible map bounds (only if map is loaded)
    if (typeof filterObjectsByMapBounds === 'function') {
        filterObjectsByMapBounds(true);
    }
};

// Update complexes list display (make it globally accessible)
window.updateComplexesList = function(complexes) {
    const container = document.getElementById('complexes-container');
    const noResults = document.getElementById('no-results');
    
    if (complexes.length === 0) {
        container.querySelectorAll('.complex-card').forEach(card => card.style.display = 'none');
        noResults.classList.remove('hidden');
        return;
    }
    
    noResults.classList.add('hidden');
    const complexIds = complexes.map(c => c.id);
    
    // Build map of existing DOM cards
    const existingCards = {};
    container.querySelectorAll('.complex-card').forEach(card => {
        const id = parseInt(card.getAttribute('data-complex-id'));
        existingCards[id] = card;
        card.style.display = 'none'; // hide all first
    });
    
    // Show or create cards in filtered order
    complexes.forEach(function(complex) {
        let card = existingCards[complex.id];
        if (!card) {
            // Card not pre-rendered — create dynamically
            const tmp = document.createElement('div');
            tmp.innerHTML = createComplexCardHTML(complex, 0);
            card = tmp.firstElementChild;
            container.appendChild(card);
            existingCards[complex.id] = card;
            // Init slider for new card
            if (typeof initSlider === 'function') initSlider(complex.id);
            // Init favorites
            if (window.favoritesManager) {
                try { window.favoritesManager.updateComplexFavoritesUI(); } catch(e) {}
            }
        }
        card.style.display = 'block';
        container.appendChild(card); // re-append to maintain sort order
    });
}

// Helper function to create SEO-friendly slug
function createSlug(name) {
    if (!name) return "unknown";
    return name
        .replace(/["\'"]/g, '')  // Remove quotes
        .replace(/[^\w\s-]/g, '') // Remove special chars except spaces and hyphens
        .replace(/[-\s]+/g, '-')  // Replace spaces/multiple hyphens with single hyphen
        .toLowerCase()
        .replace(/^-+|-+$/g, '');  // Trim hyphens
}

// Create HTML for a complex card
function createComplexCardHTML(complex, index) {
    const _aptCount = complex.available_apartments || complex.apartments_count || 0;

    // Build real image slides from images array
    const imgs = (complex.images && complex.images.length > 0) ? complex.images : (complex.image ? [complex.image] : ['/static/images/no-photo.svg']);
    const slidesHtml = imgs.map((src, i) =>
        `<div class="slider-slide min-w-full"><img src="${src}" alt="ЖК ${complex.name} фото ${i+1}" class="w-full h-56 object-cover" loading="lazy" onerror="this.src='/static/images/no-photo.svg'"></div>`
    ).join('');
    const dotsHtml = imgs.map((_, i) =>
        `<div class="slider-dot w-2 h-2 bg-white/60 rounded-full cursor-pointer hover:bg-white transition-colors ${i===0?'active bg-white':''}" onclick="event.stopPropagation(); goToSlide('${complex.id}', ${i})"></div>`
    ).join('');

    // Status badge — solid colored like server template
    const completedBadge = (complex.completed_buildings > 0 && complex.status !== 'Сдан')
        ? '<span class="bg-emerald-600/90 text-white px-2.5 py-0.5 rounded-full text-[10px] font-semibold shadow backdrop-blur-sm whitespace-nowrap">✓ Есть сданные</span>'
        : '';
    const statusBadge = complex.status === 'Сдан'
        ? '<span class="bg-green-500 text-white px-3 py-1 rounded-full text-xs font-bold shadow">Сдан</span>'
        : `<span class="bg-blue-500 text-white px-3 py-1 rounded-full text-xs font-bold shadow">${complex.status || 'Строится'}</span>`;

    // Cashback badge (top right) — like server template
    const cashbackBadge = (complex.cashback_rate && complex.cashback_rate > 0)
        ? `<div class="absolute top-3 right-3 bg-green-500 text-white px-3 py-1 rounded-full text-xs font-bold z-10 shadow">${complex.cashback_rate}% кэшбек</div>`
        : '';

    // Developer — blue link with logo like server template
    const devName = complex.developer || complex.developer_name || '';
    const devLogoHtml = complex.developer_logo
        ? `<img src="${complex.developer_logo}" alt="${devName}" class="w-5 h-5 object-contain rounded flex-shrink-0" onerror="this.style.display='none'">`
        : '';
    const devHtml = devName
        ? `<a href="/developer/${devName.toLowerCase().replace(/[^a-zа-яё0-9]+/gi,'-').replace(/^-+|-+$/g,'')}"
              class="inline-flex items-center gap-1.5 text-[#0088CC] hover:text-[#006699] text-sm hover:underline transition-colors"
              onclick="event.stopPropagation()">${devLogoHtml}${devName}</a>`
        : '';

    // Room type buttons with area + price + count (like server template)
    const rd = complex.real_room_distribution;
    const roomDetails = complex.room_details || {};
    let roomsHtml;
    if (rd && typeof rd === 'object' && Object.keys(rd).length > 0) {
        roomsHtml = Object.entries(rd).map(([roomType, cnt]) => {
            const det = roomDetails[roomType] || {};
            let areaHtml = '';
            if (det.area_from && det.area_to) {
                areaHtml = det.area_from !== det.area_to
                    ? `<div class="text-xs text-gray-500">${det.area_from}-${det.area_to} м²</div>`
                    : `<div class="text-xs text-gray-500">${det.area_from} м²</div>`;
            }
            let priceHtml = '';
            if (det.price_from && det.price_to) {
                priceHtml = `<div class="text-xs font-medium text-[#0088CC]">от ${(det.price_from/1000000).toFixed(1)} до ${(det.price_to/1000000).toFixed(1)} млн</div>`;
            } else if (det.price_from) {
                priceHtml = `<div class="text-xs font-medium text-[#0088CC]">от ${(det.price_from/1000000).toFixed(1)} млн</div>`;
            }
            return `<button class="cc-room-btn">
                        <div class="cc-room-type">${roomType}</div>
                        ${areaHtml ? areaHtml.replace('text-xs text-gray-500', 'cc-room-area') : ''}
                        ${priceHtml ? priceHtml.replace('text-xs font-medium text-[#0088CC]', 'cc-room-price') : ''}
                        <div class="cc-room-cnt">${cnt} шт</div>
                    </button>`;
        }).join('');
    } else {
        roomsHtml = '<div class="col-span-2 text-center py-3 text-gray-500 text-sm">Информация о квартирах будет доступна позже</div>';
    }

    // Date + status row — like server template
    const statusRowBadge = complex.status === 'Сдан'
        ? '<span class="bg-green-50 text-gray-600 px-2 py-1 rounded-full text-xs font-medium">Сдан</span>'
        : `<span class="bg-orange-50 text-gray-600 px-2 py-1 rounded-full text-xs font-medium">${complex.status || 'Строится'}</span>`;

    const descHtml = complex.description
        ? `<p class="text-gray-600 text-sm mb-4 line-clamp-2">${complex.description}</p>` : '';

    return `
        <div class="complex-card mobile-optimized group cursor-pointer"
             data-complex-id="${complex.id}"
             data-cashback-rate="${complex.cashback_rate || 5.0}"
             data-has-apartments="${_aptCount > 0 ? 'true' : 'false'}"
             onclick="handleCardClick(event, '${complex.url}')">

            <!-- ── Slider ── -->
            <div class="complex-slider" data-complex-id="${complex.id}" style="position:relative;">
                <div class="slider-container" style="width:100%;height:100%;overflow:hidden;">
                    <div class="slider-track" style="display:flex;height:100%;transform:translateX(0);">
                        ${slidesHtml}
                    </div>
                </div>
                <!-- Arrows -->
                <button class="slider-prev absolute left-3 top-1/2" onclick="event.stopPropagation();prevSlide('${complex.id}')">
                    <svg width="16" height="16" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" d="M15 19l-7-7 7-7"/></svg>
                </button>
                <button class="slider-next absolute right-3 top-1/2" onclick="event.stopPropagation();nextSlide('${complex.id}')">
                    <svg width="16" height="16" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" d="M9 5l7 7-7 7"/></svg>
                </button>
                <!-- Bottom gradient -->
                <div class="cc-img-gradient absolute inset-x-0 bottom-0 h-28 pointer-events-none" style="z-index:4;"></div>
                <!-- Dots -->
                ${imgs.length > 1 ? `
                <div class="absolute bottom-3 left-1/2 -translate-x-1/2 flex gap-1.5" style="z-index:6;">
                    ${dotsHtml}
                </div>` : ''}
                <!-- Top-left: status + completed -->
                <div class="absolute top-3 left-3 flex flex-col gap-1" style="z-index:6;">${statusBadge}${completedBadge}</div>
                <!-- Top-right: cashback -->
                ${complex.cashback_rate && complex.cashback_rate > 0 ? `
                <div class="absolute top-3 right-3 flex items-center gap-1 bg-emerald-500 text-white text-[11px] font-semibold px-2.5 py-1 rounded-full shadow-md" style="z-index:6;">
                    <i class="fas fa-percent text-[9px]"></i> ${complex.cashback_rate}% кэшбек
                </div>` : ''}
                <!-- Bottom-left: fav + compare -->
                <div class="absolute bottom-3 left-3 flex gap-2" style="z-index:8;">
                    <div class="favorite-heart w-9 h-9 bg-white/90 backdrop-blur-sm rounded-full flex items-center justify-center cursor-pointer hover:bg-white transition-all duration-200 shadow-md hover:scale-110"
                         data-property-id="${complex.id}" data-complex-id="${complex.id}" title="В избранное"
                         onclick="var icon=this.querySelector('i');if(icon.classList.contains('text-red-500')){icon.classList.remove('text-red-500');icon.classList.add('text-gray-400');}else{icon.classList.remove('text-gray-400');icon.classList.add('text-red-500');}if(window.favoritesManager){window.favoritesManager.toggleComplexFavorite('${complex.id}',this);}event.stopPropagation();">
                        <i class="fas fa-heart text-gray-400 transition-colors duration-200 text-sm"></i>
                    </div>
                    <div class="compare-btn w-9 h-9 bg-white/90 backdrop-blur-sm rounded-full flex items-center justify-center cursor-pointer hover:bg-white hover:scale-110 transition-all duration-200 shadow-md"
                         data-complex-id="${complex.id}" title="Сравнить"
                         onclick="addToComplexCompare(${complex.id});event.stopPropagation();">
                        <i class="fas fa-scale-balanced text-gray-500 text-sm transition-colors hover:text-[#0088CC]"></i>
                    </div>
                </div>
                <!-- Bottom-right: photo count -->
                ${imgs.length > 1 ? `<div class="absolute bottom-3 right-3 bg-black/40 backdrop-blur-sm text-white text-[10px] px-2 py-0.5 rounded-full" style="z-index:6;">${imgs.length} фото</div>` : ''}
            </div>

            <!-- ── Content ── -->
            <div class="cc-body flex-1 flex flex-col">
                <!-- Title + developer -->
                <div class="flex items-start justify-between gap-2 mb-2">
                    <div class="min-w-0">
                        <h3 class="cc-title truncate">${complex.name}</h3>
                        ${devHtml}
                    </div>
                    ${complex.housing_class ? `<span class="flex-shrink-0 text-[10px] font-semibold px-2 py-0.5 rounded-full border border-gray-200 text-gray-500 mt-0.5">${complex.housing_class}</span>` : ''}
                </div>

                <!-- Location row -->
                <div class="flex items-center gap-1.5 cc-meta mb-1.5">
                    <i class="fas fa-location-dot text-[#0088CC] text-[11px] flex-shrink-0"></i>
                    <span class="truncate">${complex.district ? complex.district + (complex.location || complex.address ? ', ' : '') : ''}${complex.location || complex.address || 'Краснодар'}</span>
                    ${complex.distance_to_center ? `<span class="flex-shrink-0 ml-auto bg-gray-100 text-gray-500 text-[10px] px-1.5 py-0.5 rounded-full whitespace-nowrap">${Math.round(complex.distance_to_center * 10) / 10} км</span>` : ''}
                </div>

                <!-- Completion date -->
                ${complex.completion_date ? `
                <div class="flex items-center gap-1.5 cc-meta mb-2">
                    <i class="fas fa-calendar text-[11px] flex-shrink-0 opacity-60"></i>
                    <span>Сдача: ${complex.completion_date}${(complex.completed_buildings > 0 && complex.status !== 'Сдан') ? '<span class="ml-1.5 text-emerald-600 font-semibold">· есть сданные</span>' : ''}</span>
                </div>` : ''}

                <!-- Amenity badges -->
                ${(function() {
                    const nb = complex.nearby_badges;
                    const rest = complex.nearby_badges_rest || 0;
                    if (nb && nb.length > 0) {
                        let html = '<div class="flex flex-wrap gap-1 mb-3">';
                        html += nb.map(b =>
                            '<span class="inline-flex items-center gap-0.5 bg-gray-100 text-gray-600 px-2 py-0.5 rounded-full text-[10px]" title="' + (b.dist || '') + '">'
                            + '<span>' + b.icon + '</span>' + b.label + '</span>'
                        ).join('');
                        if (rest > 0) html += '<span class="bg-[#0088CC]/10 text-[#0088CC] px-2 py-0.5 rounded-full text-[10px] font-medium">+' + rest + '</span>';
                        html += '</div>';
                        return html;
                    }
                    return '';
                })()}

                <!-- Room type buttons -->
                <div class="border-t border-gray-100 pt-3 mb-3">
                    <div class="cc-meta mb-2 font-medium text-gray-400">Квартиры в продаже</div>
                    <div class="grid grid-cols-2 gap-1.5">${roomsHtml}</div>
                </div>

                <!-- Stats row -->
                <div class="flex items-center gap-3 cc-meta mb-3">
                    <span><i class="fas fa-building mr-1 opacity-60"></i>${complex.buildings_count || 1} корп.</span>
                    <span><i class="fas fa-home mr-1 opacity-60"></i>${_aptCount > 0 ? _aptCount + ' кв.' : 'Нет кв.'}</span>
                </div>

                <div class="flex-1"></div>

                <!-- CTA button (desktop) -->
                <button class="cc-phone-btn show-phone-btn hidden sm:flex mt-1" onclick="event.stopPropagation();showCompanyPhone(this);">
                    <i class="fas fa-phone text-sm"></i>
                    <span class="phone-text">Показать телефон</span>
                </button>

                <!-- Mobile action bar -->
                <div class="mobile-action-bar flex sm:hidden items-center gap-2 mt-2 pt-3 border-t border-gray-100">
                    <button class="mobile-call-btn flex-1 flex items-center justify-center gap-2 bg-[#0088CC] text-white rounded-2xl py-2.5 text-sm font-semibold"
                            onclick="event.stopPropagation();openPhoneModal('${complex.id}', '${complex.name.replace(/'/g,"\\'")}');">
                        <i class="fas fa-phone text-xs"></i><span>Позвонить</span>
                    </button>
                    ${(complex.latitude && complex.longitude) ? `
                    <button class="map-btn w-10 h-10 bg-[#0088CC]/10 rounded-full flex items-center justify-center hover:bg-[#0088CC] hover:text-white transition-all"
                            onclick="event.stopPropagation();openMapModal(${complex.latitude},${complex.longitude},'${complex.name.replace(/'/g,"\\'")}');" title="На карте">
                        <i class="fas fa-map-marker-alt text-[#0088CC] text-sm"></i>
                    </button>` : ''}
                    <button class="compare-btn w-10 h-10 bg-white border border-gray-200 rounded-full flex items-center justify-center hover:bg-[#0088CC] hover:border-[#0088CC] hover:text-white transition-all"
                            data-complex-id="${complex.id}" onclick="event.stopPropagation();addToComplexCompare(${complex.id});" title="Сравнить">
                        <i class="fas fa-scale-balanced text-[#0088CC] text-sm"></i>
                    </button>
                </div>

                ${window.isManagerAuthenticated ? `
                <button onclick="openRecommendModal('complex',${complex.id},'${complex.name.replace(/'/g,"\\'")}');event.stopPropagation();"
                        class="recommend-btn mt-2 w-full px-4 py-2 bg-orange-500 text-white rounded-xl hover:bg-orange-600 transition-colors text-sm"
                        data-item-type="complex" data-item-id="${complex.id}" data-item-name="${complex.name}">
                    <i class="fas fa-paper-plane mr-2"></i>Рекомендовать
                </button>` : ''}
            </div>
        </div>
    `;
}

// Helper function to get proper word form for apartments count
function getApartmentWordForm(count) {
    if (count % 10 === 1 && count % 100 !== 11) {
        return 'квартира';
    } else if ([2, 3, 4].includes(count % 10) && ![12, 13, 14].includes(count % 100)) {
        return 'квартиры';
    } else {
        return 'квартир';
    }
}

// Initialize event listeners for complex cards
function initializeComplexCardListeners() {
    // Re-initialize sliders and other functionality
    setTimeout(() => {
        initAllSliders();
        if (typeof favoritesManager !== 'undefined') {
            favoritesManager.updateFavoritesUI();
            favoritesManager.updateComplexFavoritesUI();
            favoritesManager.updateFavoritesCounter();
        }
        if (typeof updateComplexCompareButtons === 'function') {
            updateComplexCompareButtons();
        }
    }, 100);
}

// Update results count
function updateResultsCount(count) {
    const countElement = document.getElementById('results-count');
    if (countElement) {
        countElement.textContent = count.toLocaleString('ru-RU');
    }

    // Счётчик «На карте» под мини-картой
    const miniMapCount = document.getElementById('mini-map-complex-count');
    if (miniMapCount) {
        miniMapCount.textContent = count.toLocaleString('ru-RU');
    }

    // Обновляем счетчики в панелях фильтров
    const roomsCount = document.getElementById('roomsFilteredCount');
    const priceCount = document.getElementById('priceFilteredCount');
    if (roomsCount) roomsCount.textContent = count;
    if (priceCount) priceCount.textContent = count;
}

// Toggle filters panel
window.toggleFilters = function() {
    const panel = document.getElementById('filtersPanel');
    const backdrop = document.getElementById('filterBackdrop');
    if (panel.classList.contains('hidden')) {
        panel.classList.remove('hidden');
        panel.classList.add('flex');
        if (backdrop) backdrop.classList.remove('hidden');
        document.body.style.overflow = 'hidden';
        if (window.innerWidth < 768) {
            panel.classList.add('mobile-fullscreen');
        }
        setTimeout(updateMobileFilterCount, 50);
    } else {
        panel.classList.add('hidden');
        panel.classList.remove('flex');
        panel.classList.remove('mobile-fullscreen');
        if (backdrop) backdrop.classList.add('hidden');
        document.body.style.overflow = '';
    }
}

document.addEventListener('DOMContentLoaded', function() {
    var desktopSelects = ['district-filter', 'developer-filter', 'status-filter', 'object-class-filter', 'completion-year-filter', 'floors-filter'];
    desktopSelects.forEach(function(id) {
        var el = document.getElementById(id);
        if (el) {
            el.addEventListener('change', function() {
                applyComplexFilters();
                updateDesktopFilterBadge();
            });
        }
    });
});

window.updateDesktopFilterBadge = function() {
    var count = 0;
    var panel = document.getElementById('filtersPanel');
    if (!panel) return;
    var desktopBox = panel.querySelector('.hidden.md\\:block, [class*="md:block"]');
    if (!desktopBox) return;
    desktopBox.querySelectorAll('select').forEach(function(sel) {
        if (sel.value) count++;
    });
    desktopBox.querySelectorAll('input[type="checkbox"]:checked').forEach(function() { count++; });
    var priceFrom = document.getElementById('price-range-from');
    var priceTo = document.getElementById('price-range-to');
    if (priceFrom && priceFrom.value) count++;
    if (priceTo && priceTo.value) count++;
    var badge = document.getElementById('desktopFilterCountBadge');
    if (badge) {
        if (count > 0) {
            badge.textContent = count;
            badge.classList.remove('hidden');
        } else {
            badge.classList.add('hidden');
        }
    }
}

window.resetDesktopFilters = function() {
    var panel = document.getElementById('filtersPanel');
    if (!panel) return;
    panel.querySelectorAll('select').forEach(function(sel) { sel.value = ''; });
    panel.querySelectorAll('input[type="checkbox"]').forEach(function(cb) { cb.checked = false; });
    panel.querySelectorAll('input[type="number"]').forEach(function(inp) { inp.value = ''; });
    // Reset pill buttons
    panel.querySelectorAll('.cfilter-pill').forEach(function(btn) {
        if (btn.dataset.value === '') {
            btn.classList.add('active', 'bg-[#0088CC]', 'text-white', 'border-[#0088CC]');
            btn.classList.remove('bg-white', 'text-gray-700', 'border-gray-200');
        } else {
            btn.classList.remove('active', 'bg-[#0088CC]', 'text-white', 'border-[#0088CC]');
            btn.classList.add('text-gray-700', 'border-gray-200');
        }
    });
    updateDesktopFilterBadge();
    // Sync quick-filter chip visuals after panel reset
    if (typeof syncCqfChipsUI === 'function') syncCqfChipsUI();
    applyComplexFilters();
}

// Set filter value from pill button
window.setComplexFilterPill = function(btn) {
    var targetId = btn.dataset.target;
    var value = btn.dataset.value;
    // Deactivate siblings in the same group
    var group = btn.closest('.flex');
    if (group) {
        group.querySelectorAll('.cfilter-pill').forEach(function(b) {
            b.classList.remove('active', 'bg-[#0088CC]', 'text-white', 'border-[#0088CC]');
            b.classList.add('text-gray-700', 'border-gray-200');
        });
    }
    // Activate this button
    btn.classList.add('active', 'bg-[#0088CC]', 'text-white', 'border-[#0088CC]');
    btn.classList.remove('text-gray-700', 'border-gray-200');
    // Update hidden select
    var sel = document.getElementById(targetId);
    if (sel) {
        sel.value = value;
        sel.dispatchEvent(new Event('change'));
    }
    applyComplexFilters();
    updateDesktopFilterBadge();
    if (typeof syncCqfChipsUI === 'function') syncCqfChipsUI();
}

// Quick filter stats (ЦИАН-style)
function updateQuickFilterStats() {
    var container = document.getElementById('quickFilterChips');
    var wrapper = document.getElementById('quickFilterStats');
    if (!container || !wrapper || !window.allComplexes || !allComplexes.length) return;
    var stats = [
        { label: 'Строящиеся', count: allComplexes.filter(function(c){ return c.status !== 'Сдан' && (c.available_apartments||c.apartments_count||0)>0; }).length, filter: function(){ setQuickStat('status', 'Строится'); } },
        { label: 'Сданные', count: allComplexes.filter(function(c){ return c.status === 'Сдан'; }).length, filter: function(){ setQuickStat('status', 'Сдан'); } },
        { label: 'Бизнес-класс', count: allComplexes.filter(function(c){ return (c.housing_class||'').toLowerCase().includes('бизнес'); }).length, filter: function(){ setQuickStat('class', 'Бизнес'); } },
        { label: 'Комфорт-класс', count: allComplexes.filter(function(c){ return (c.housing_class||'').toLowerCase().includes('комфорт'); }).length, filter: function(){ setQuickStat('class', 'Комфорт'); } },
        { label: 'Премиум-класс', count: allComplexes.filter(function(c){ return (c.housing_class||'').toLowerCase().includes('премиум'); }).length, filter: function(){ setQuickStat('class', 'Премиум'); } },
        { label: 'Сдача 2026', count: allComplexes.filter(function(c){ return c.completion_date && String(c.completion_date).includes('2026'); }).length, filter: function(){ setQuickStat('year', '2026'); } },
        { label: 'Сдача 2027', count: allComplexes.filter(function(c){ return c.completion_date && String(c.completion_date).includes('2027'); }).length, filter: function(){ setQuickStat('year', '2027'); } },
    ];
    container.innerHTML = '';
    stats.forEach(function(s) {
        if (s.count > 0) {
            var btn = document.createElement('button');
            btn.className = 'quick-stat-chip flex-shrink-0 flex items-center gap-1.5 px-3.5 py-2 rounded-full border border-gray-200 text-sm text-gray-700 hover:border-[#0088CC] hover:text-[#0088CC] hover:bg-blue-50 transition-all whitespace-nowrap';
            btn.innerHTML = s.label + ' <span class="font-bold text-[#0088CC]">' + s.count + '</span>';
            btn.onclick = s.filter;
            container.appendChild(btn);
        }
    });
    wrapper.classList.remove('hidden');
}

function setQuickStat(type, value) {
    var idMap = { status: 'status-filter', class: 'object-class-filter', year: 'completion-year-filter' };
    var id = idMap[type];
    var sel = document.getElementById(id);
    if (sel) {
        sel.value = value;
        // Sync pill buttons
        var pill = document.querySelector('.cfilter-pill[data-target="' + id + '"][data-value="' + value + '"]');
        if (pill) setComplexFilterPill(pill);
        else { sel.dispatchEvent(new Event('change')); applyComplexFilters(); }
    }
}

function searchComplexes() {
    applyComplexFilters();
}

// Map functionality
let complexesMap;
let complexMarkers = [];
let isMapView = false;

function toggleMapView() {
    const mapSection = document.getElementById('mapSection');
    const gridSection = document.getElementById('gridSection');
    
    if (isMapView) {
        // Switch to grid view
        mapSection.classList.add('hidden');
        gridSection.classList.remove('hidden');
        isMapView = false;
    } else {
        // Switch to map view
        mapSection.classList.remove('hidden');
        gridSection.classList.add('hidden');
        isMapView = true;
        
        // Initialize map if not already initialized
        if (!complexesMap) {
            initializeComplexesMap();
        }
    }
}

function initializeComplexesMap() {
    // Initialize Leaflet map centered on Krasnodar
    complexesMap = L.map('complexesMap').setView([45.0355, 38.9753], 11);
    
    // Add tile layer
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        attribution: '© OpenStreetMap contributors'
    }).addTo(complexesMap);
    
    // По умолчанию — только ЖК с квартирами (скрываем проданные/без лотов)
    const complexesWithCoords = allComplexes.filter(c => c.coordinates && (c.available_apartments || c.apartments_count || 0) > 0);
    addComplexMarkersToMap(complexesWithCoords);
    updateMapSidebar(complexesWithCoords);
    
    // Add zoom event listener to update markers
    complexesMap.on('zoomend', function() {
        // When polygon is active, don't re-add all markers (would override polygon filter)
        if (!drawnComplexPolygon) {
            // Use filteredComplexes (respects current search/filter), not raw complexesWithCoords
            const currentFiltered = filteredComplexes.filter(c => c.coordinates && c.coordinates.length === 2);
            addComplexMarkersToMap(currentFiltered);
            filterObjectsByMapBounds(false);
        } else {
            filterComplexesByPolygon();
        }
    });
    
    // Add move end handler to filter objects by visible area
    complexesMap.on('moveend', function() {
        // Only filter by bounds if no polygon is drawn
        if (!drawnComplexPolygon) {
            filterObjectsByMapBounds(false);
        } else {
            filterComplexesByPolygon();
        }
    });
    
    // Set up drawing buttons
    document.getElementById('drawComplexAreaBtn').addEventListener('click', function(e) {
        e.preventDefault();
        if (!isComplexDrawing) {
            enableComplexDrawing();
        }
    });
    
    document.getElementById('clearComplexAreaBtn').addEventListener('click', function(e) {
        e.preventDefault();
        clearComplexDrawnArea();
    });
}

function addComplexMarkersToMap(complexes) {
    // Clear existing markers
    complexMarkers.forEach(marker => complexesMap.removeLayer(marker));
    complexMarkers = [];
    
    complexes.forEach(complex => {
        if (complex.coordinates && complex.coordinates.length === 2) {
            const [lat, lng] = complex.coordinates;
            
            // Get current zoom level to determine marker style
            const zoom = complexesMap.getZoom();
            let markerHtml;
            
            if (zoom < 13) {
                // Simple dot marker for distant view
                markerHtml = `
                    <div class="w-3 h-3 bg-gradient-to-r from-[#006699] to-[#0088CC] rounded-full border-2 border-white shadow-lg"></div>
                `;
            } else {
                // Detailed marker for close view
                markerHtml = `
                    <div class="bg-gradient-to-r from-[#006699] to-[#0088CC] text-white px-2 py-1 rounded-lg shadow-lg border border-white">
                        <div class="text-center text-xs font-medium whitespace-nowrap">
                            <div class="font-bold">${complex.apartments_count > 0 ? complex.apartments_count + ' кв.' : 'Нет кв.'}</div>
                            <div class="opacity-90">${complex.name.slice(3, 10)}...</div>
                        </div>
                    </div>
                `;
            }
            
            const iconSize = complexesMap.getZoom() < 13 ? [12, 12] : [70, 30];
            const iconAnchor = complexesMap.getZoom() < 13 ? [6, 6] : [35, 30];
            
            const marker = L.marker([lat, lng], {
                icon: L.divIcon({
                    html: markerHtml,
                    className: 'custom-complex-marker',
                    iconSize: iconSize,
                    iconAnchor: iconAnchor
                })
            }).addTo(complexesMap);
            
            // Add popup with complex info (improved design)
            const popupContent = `
                <div class="w-80 bg-white rounded-lg overflow-hidden">
                    <div class="relative h-40">
                        <img src="${complex.image}" alt="${complex.name}" class="w-full h-full object-cover">
                        <div class="absolute top-2 right-2 bg-orange-50 text-gray-600 px-2 py-1 rounded-full text-xs font-bold">
                            от ${((complex.real_price_from || 0) / 1000000).toFixed(1)} млн ₽
                        </div>
                        <div class="absolute top-2 left-2 bg-green-500 text-white px-2 py-1 rounded-full text-xs font-medium">
                            Кэшбэк ${complex.cashback_percent}%
                        </div>
                    </div>
                    <div class="p-4">
                        <h3 class="font-bold text-gray-900 text-lg mb-1">${complex.name}</h3>
                        <p class="text-[#0088CC] text-sm mb-2 font-medium">${complex.developer}</p>
                        <div class="flex items-center text-sm text-gray-600 mb-3">
                            <i class="fas fa-map-marker-alt mr-2 text-[#0088CC]"></i>
                            <span>${complex.district}, ${complex.location}</span>
                        </div>
                        <div class="grid grid-cols-2 gap-4 mb-3 text-sm">
                            <div class="flex items-center">
                                <i class="fas fa-home mr-2 text-gray-400"></i>
                                <div>
                                    <span class="text-gray-500">Квартир</span>
                                    <div class="font-medium">${complex.apartments_count > 0 ? complex.apartments_count : 'Квартир нет'}</div>
                                </div>
                            </div>
                            <div class="flex items-center">
                                <i class="fas fa-calendar mr-2 text-gray-400"></i>
                                <div>
                                    <span class="text-gray-500">Сдача</span>
                                    <div class="font-medium ${complex.status === 'Сдан' ? 'text-green-600' : 'text-[#0088CC]'}">${complex.completion_date}</div>
                                </div>
                            </div>
                        </div>
                        <div class="pt-3 border-t border-gray-100">
                            <button class="w-full bg-gradient-to-r from-[#006699] to-[#0088CC] text-white py-2 px-4 rounded-lg font-medium hover:opacity-90 transition">
                                Подробнее о ЖК
                            </button>
                        </div>
                    </div>
                </div>
            `;
            
            marker.bindPopup(popupContent, {
                maxWidth: 320,
                className: 'custom-complex-popup',
                closeButton: true,
                autoPan: true
            });
            
            complexMarkers.push(marker);
        }
    });
}

function searchComplexesOnMap() {
    const searchQuery = document.getElementById('map-search').value.toLowerCase().trim();
    let filteredComplexes = [...allComplexes.filter(c => c.coordinates)];
    
    if (searchQuery) {
        filteredComplexes = filteredComplexes.filter(complex => {
            return complex.name.toLowerCase().includes(searchQuery) ||
                   complex.developer.toLowerCase().includes(searchQuery) ||
                   complex.district.toLowerCase().includes(searchQuery) ||
                   complex.location.toLowerCase().includes(searchQuery);
        });
    }
    
    // Update markers on map
    addComplexMarkersToMap(filteredComplexes);
    
    // Update sidebar with complex cards
    updateMapSidebar(filteredComplexes);
    
    // Fit map to show all results
    if (filteredComplexes.length > 1 && complexMarkers.length > 1) {
        const group = new L.featureGroup(complexMarkers);
        complexesMap.fitBounds(group.getBounds().pad(0.1));
    } else if (filteredComplexes.length === 1 && filteredComplexes[0].coordinates) {
        complexesMap.setView(filteredComplexes[0].coordinates, 15);
    }
}

function updateMapSidebar(complexes) {
    const complexesList = document.getElementById('mapComplexesList');
    const resultsCount = document.getElementById('mapResultsCount');
    
    resultsCount.textContent = `Найдено ${complexes.length} комплексов`;
    
    if (complexes.length > 0) {
        const complexesHtml = complexes.map(complex => `
            <div class="p-4 border-b border-gray-100 hover:bg-gray-50 cursor-pointer transition-colors" onclick="focusOnComplex([${complex.coordinates}])">
                <div class="flex space-x-3">
                    <div class="w-16 h-16 rounded-lg overflow-hidden flex-shrink-0">
                        <img src="${complex.image}" alt="${complex.name}" class="w-full h-full object-cover">
                    </div>
                    <div class="flex-1 min-w-0">
                        <h4 class="font-semibold text-gray-900 text-sm mb-1 truncate">${complex.name}</h4>
                        <p class="text-xs text-gray-600 mb-2">${complex.developer}</p>
                        <div class="flex items-center text-xs text-gray-600 mb-2">
                            <i class="fas fa-map-marker-alt mr-1 text-[#0088CC]"></i>
                            <span class="truncate">${complex.district}</span>
                        </div>
                        <div class="flex justify-between items-center">
                            <div class="flex flex-col">
                                <span class="text-[#0088CC] font-bold text-sm">от ${((complex.real_price_from || 0) / 1000000).toFixed(1)} млн ₽</span>
                                <span class="text-xs text-gray-500">${complex.apartments_count > 0 ? complex.apartments_count + ' квартир' : 'Квартир нет'}</span>
                            </div>
                            <div class="text-right">
                                <span class="text-green-600 font-medium text-xs">кэшбэк ${complex.cashback_percent}%</span>
                                <div class="text-xs ${complex.status === 'Сдан' ? 'text-green-600' : 'text-[#0088CC]'}">${complex.completion_date}</div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        `).join('');
        
        complexesList.innerHTML = complexesHtml;
    } else {
        complexesList.innerHTML = '<div class="p-4 text-center text-gray-500">ЖК не найдены</div>';
    }
}

function focusOnComplex(coordinates) {
    if (coordinates && coordinates.length === 2) {
        complexesMap.setView(coordinates, 16);
    }
}

// Filter objects by visible map bounds
// fromFilter=true: called after search/filter change → update markers + optionally fit bounds
// fromFilter=false: called from map pan/zoom → only update sidebar (markers already redrawn by event)
function filterObjectsByMapBounds(fromFilter) {
    if (!complexesMap || !isMapView) {
        return;
    }
    
    try {
        if (fromFilter !== false) {
            // Filter triggered by user search/filter — update markers to match filter
            const withCoords = filteredComplexes.filter(c => c.coordinates && c.coordinates.length === 2);
            addComplexMarkersToMap(withCoords);

            // Fit map view to the filtered results (only when results narrowed down)
            if (withCoords.length > 0 && withCoords.length < allComplexes.length) {
                if (withCoords.length === 1) {
                    complexesMap.setView(withCoords[0].coordinates, 15);
                } else if (withCoords.length <= 50) {
                    try {
                        const group = new L.featureGroup(complexMarkers);
                        if (group.getBounds().isValid()) {
                            complexesMap.fitBounds(group.getBounds().pad(0.15));
                        }
                    } catch(e) {}
                }
            }
        }

        // Sidebar: show complexes visible in current map bounds
        const bounds = complexesMap.getBounds();
        const visibleComplexes = filteredComplexes.filter(complex => {
            if (!complex.coordinates || complex.coordinates.length !== 2) {
                return false;
            }
            const [lat, lng] = complex.coordinates;
            return bounds.contains([lat, lng]);
        });
        
        updateMapSidebar(visibleComplexes);
        console.log(`Map updated: ${visibleComplexes.length} in bounds`);
    } catch(e) {
        console.warn('Error filtering objects by map bounds:', e);
    }
}

// Drawing functionality for complexes
let isComplexDrawing = false;
let drawnComplexPolygon = null;
let complexDrawingHandler = null;

function enableComplexDrawingCIAN() {
    const hint = document.getElementById('complexDrawingHintOverlay');
    const drawBtn = document.getElementById('complexCianDrawBtn');
    const clearBtn = document.getElementById('complexCianClearBtn');
    if (hint) hint.style.display = 'flex';
    if (drawBtn) { drawBtn.style.background = '#0088CC'; drawBtn.style.borderColor = '#006699'; const svg = drawBtn.querySelector('svg'); if (svg) svg.style.color = 'white'; }
    if (clearBtn) clearBtn.style.display = 'flex';
    enableComplexDrawing();
}

function enableComplexDrawing() {
    if (!complexesMap) return;
    
    isComplexDrawing = true;
    // Show CIAN hint overlay
    const hint = document.getElementById('complexDrawingHintOverlay');
    const drawBtn = document.getElementById('complexCianDrawBtn');
    const clearBtn = document.getElementById('complexCianClearBtn');
    if (hint) hint.style.display = 'flex';
    if (drawBtn) { drawBtn.style.background = '#0088CC'; drawBtn.style.borderColor = '#006699'; }
    if (clearBtn) clearBtn.style.display = 'flex';
    // Legacy btn (hidden, kept for compat)
    const btn = document.getElementById('drawComplexAreaBtn');
    if (btn) btn.innerHTML = '';
    
    complexesMap.getContainer().style.cursor = 'crosshair';
    
    // Create temporary polygon for drawing
    const drawingPoints = [];
    const drawingMarkers = [];
    let tempPolygon = null;
    let previewLine = null;
    
    complexDrawingHandler = {
        click: function(e) {
            const clickPoint = [e.latlng.lat, e.latlng.lng];
            
            // Check if clicking on first point to close polygon (if we have at least 3 points)
            if (drawingPoints.length >= 3) {
                const firstPoint = drawingPoints[0];
                const distance = Math.sqrt(
                    Math.pow(e.latlng.lat - firstPoint[0], 2) + 
                    Math.pow(e.latlng.lng - firstPoint[1], 2)
                );
                
                // If clicking close to first point (within reasonable distance), close polygon
                if (distance < 0.005) { // ~500m threshold
                    finishComplexDrawing(drawingPoints, drawingMarkers, tempPolygon, previewLine);
                    return;
                }
            }
            
            drawingPoints.push(clickPoint);
            
            // Add visible point marker with special styling for first point
            const isFirstPoint = drawingPoints.length === 1;
            const pointMarker = L.circleMarker([e.latlng.lat, e.latlng.lng], {
                color: isFirstPoint ? '#00aa44' : '#ff6b35',
                fillColor: isFirstPoint ? '#00aa44' : '#ff6b35',
                fillOpacity: 1,
                radius: isFirstPoint ? 8 : 6,
                weight: isFirstPoint ? 3 : 2
            }).addTo(complexesMap);
            
            // Add tooltip for first point
            if (isFirstPoint) {
                pointMarker.bindTooltip('Начальная точка<br>Кликните сюда для завершения', {
                    permanent: false,
                    direction: 'top'
                });
            }
            
            drawingMarkers.push(pointMarker);
            
            // Update temporary polygon
            if (tempPolygon) {
                complexesMap.removeLayer(tempPolygon);
            }
            
            if (drawingPoints.length >= 3) {
                // Show polygon preview but don't auto-complete
                tempPolygon = L.polygon(drawingPoints, {
                    color: '#ff6b35',
                    fillColor: '#ff6b35',
                    fillOpacity: 0.2,
                    weight: 2,
                    dashArray: '5, 5'
                }).addTo(complexesMap);
            } else if (drawingPoints.length === 2) {
                // Show line between first two points
                tempPolygon = L.polyline(drawingPoints, {
                    color: '#ff6b35',
                    weight: 2,
                    dashArray: '5, 5'
                }).addTo(complexesMap);
            }
        },
        dblclick: function(e) {
            // Prevent default double-click behavior
            e.originalEvent.preventDefault();
            // Double-click only finishes if we have enough points, but doesn't auto-complete
            if (drawingPoints.length >= 3) {
                finishComplexDrawing(drawingPoints, drawingMarkers, tempPolygon, previewLine);
            }
        },
        mousemove: function(e) {
            if (drawingPoints.length > 0) {
                // Remove previous preview line
                if (previewLine) {
                    complexesMap.removeLayer(previewLine);
                }
                
                const lastPoint = drawingPoints[drawingPoints.length - 1];
                const currentPoint = [e.latlng.lat, e.latlng.lng];
                
                // If we have 3+ points, check if cursor is near first point
                if (drawingPoints.length >= 3) {
                    const firstPoint = drawingPoints[0];
                    const distanceToFirst = Math.sqrt(
                        Math.pow(e.latlng.lat - firstPoint[0], 2) + 
                        Math.pow(e.latlng.lng - firstPoint[1], 2)
                    );
                    
                    // If close to first point, show preview to close polygon
                    if (distanceToFirst < 0.005) {
                        previewLine = L.polyline([lastPoint, firstPoint], {
                            color: '#00aa44',
                            weight: 3,
                            dashArray: '8, 8',
                            opacity: 0.8
                        }).addTo(complexesMap);
                        
                        // Change cursor style
                        complexesMap.getContainer().style.cursor = 'pointer';
                        return;
                    }
                }
                
                // Default preview line to cursor
                previewLine = L.polyline([lastPoint, currentPoint], {
                    color: '#ff6b35',
                    weight: 2,
                    dashArray: '8, 8',
                    opacity: 0.7
                }).addTo(complexesMap);
                
                // Reset cursor
                complexesMap.getContainer().style.cursor = 'crosshair';
            }
        }
    };
    
    complexesMap.on('click', complexDrawingHandler.click);
    complexesMap.on('dblclick', complexDrawingHandler.dblclick);
    complexesMap.on('mousemove', complexDrawingHandler.mousemove);
}

function finishComplexDrawing(points, markers, tempPoly, previewLine) {
    if (!complexesMap || points.length < 3) return;
    
    // Remove temporary polygon, markers and preview line
    if (tempPoly) {
        complexesMap.removeLayer(tempPoly);
    }
    if (previewLine) {
        complexesMap.removeLayer(previewLine);
    }
    markers.forEach(marker => complexesMap.removeLayer(marker));
    
    // Remove event handlers
    complexesMap.off('click', complexDrawingHandler.click);
    complexesMap.off('dblclick', complexDrawingHandler.dblclick);
    complexesMap.off('mousemove', complexDrawingHandler.mousemove);
    
    // Create final polygon
    if (drawnComplexPolygon) {
        complexesMap.removeLayer(drawnComplexPolygon);
    }
    
    drawnComplexPolygon = L.polygon(points, {
        color: '#ff6b35',
        fillColor: '#ff6b35',
        fillOpacity: 0.15,
        weight: 3
    }).addTo(complexesMap);
    
    // Reset drawing state
    isComplexDrawing = false;
    complexesMap.getContainer().style.cursor = '';
    
    // Update buttons
    const btn = document.getElementById('drawComplexAreaBtn');
    btn.classList.remove('bg-orange-500', 'text-white', 'shadow-xl');
    btn.classList.add('text-gray-700', 'hover:text-[#0088CC]');
    btn.innerHTML = '<i class="fas fa-draw-polygon mr-2"></i>Выделить область';
    document.getElementById('clearComplexAreaBtn').classList.remove('hidden');
    
    // Filter complexes by drawn polygon
    filterComplexesByPolygon();
    
    console.log('Complex drawing completed with', points.length, 'points');
}

function clearComplexDrawnArea() {
    if (drawnComplexPolygon) {
        complexesMap.removeLayer(drawnComplexPolygon);
        drawnComplexPolygon = null;
    }
    
    // Hide CIAN overlay elements
    const hint = document.getElementById('complexDrawingHintOverlay');
    const drawBtn = document.getElementById('complexCianDrawBtn');
    const clearBtn = document.getElementById('complexCianClearBtn');
    if (hint) hint.style.display = 'none';
    if (drawBtn) { drawBtn.style.background = '#fff'; drawBtn.style.borderColor = '#e5e7eb'; const svg = drawBtn.querySelector('svg'); if (svg) svg.style.color = '#374151'; }
    if (clearBtn) clearBtn.style.display = 'none';

    // Legacy hidden button
    const legacyClear = document.getElementById('clearComplexAreaBtn');
    if (legacyClear) legacyClear.classList.add('hidden');
    
    // Restore ALL valid markers (same set as initial load: apartments > 0 + has coords)
    const withCoords = allComplexes.filter(c =>
        c.coordinates && c.coordinates.length === 2 &&
        ((c.available_apartments || c.apartments_count || 0) > 0)
    );
    addComplexMarkersToMap(withCoords);
    filterObjectsByMapBounds(false);
    
    console.log('Complex drawn area cleared');
}

function _pointInLeafletPolygon(lat, lng, polygon) {
    // Ray-casting point-in-polygon for Leaflet L.polygon
    try {
        const pts = polygon.getLatLngs()[0];
        if (!pts || pts.length < 3) return false;
        let inside = false;
        for (let i = 0, j = pts.length - 1; i < pts.length; j = i++) {
            const xi = pts[i].lat, yi = pts[i].lng;
            const xj = pts[j].lat, yj = pts[j].lng;
            const intersect = ((yi > lng) !== (yj > lng)) &&
                (lat < (xj - xi) * (lng - yi) / (yj - yi) + xi);
            if (intersect) inside = !inside;
        }
        return inside;
    } catch(e) { return false; }
}

function filterComplexesByPolygon() {
    if (!drawnComplexPolygon || !filteredComplexes) return;
    
    try {
        const complexesInPolygon = filteredComplexes.filter(complex => {
            if (!complex.coordinates || complex.coordinates.length !== 2) return false;
            const [lat, lng] = complex.coordinates;
            return _pointInLeafletPolygon(lat, lng, drawnComplexPolygon);
        });
        
        // Update sidebar with only complexes in polygon
        updateMapSidebar(complexesInPolygon);
        
        console.log(`Filtered to ${complexesInPolygon.length} complexes in drawn polygon`);
    } catch(e) {
        console.warn('Error filtering complexes by polygon:', e);
    }
}

// ========== CIAN Infrastructure for Complexes Map (Overpass API) ==========
var complexInfraActive = {};
var complexInfraLayers = {};
var complexInfraCfg = {
    shops:         { tag: '"shop"',                              label: 'Магазин',     color: '#f97316' },
    schools:       { tag: '"amenity"="school"',                  label: 'Школа',       color: '#22c55e' },
    kindergartens: { tag: '"amenity"="kindergarten"',            label: 'Детский сад', color: '#0088CC' },
    clinics:       { tag: '"amenity"~"clinic|hospital|doctors"', label: 'Поликлиника', color: '#ef4444' }
};

function toggleComplexInfraDropdown(e) {
    if (e) e.stopPropagation();
    const panel = document.getElementById('complexInfraDropdownPanel');
    const chevron = document.getElementById('complexInfraChevron');
    const btn = document.getElementById('complexInfraToggleBtn');
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
    const wrapper = document.getElementById('complexInfraWrapper');
    if (wrapper && !wrapper.contains(e.target)) {
        const panel = document.getElementById('complexInfraDropdownPanel');
        if (panel && panel.style.display !== 'none') {
            panel.style.display = 'none';
            const chevron = document.getElementById('complexInfraChevron');
            const btn = document.getElementById('complexInfraToggleBtn');
            if (chevron) chevron.style.transform = '';
            if (btn) { btn.style.borderColor = '#e5e7eb'; btn.style.background = '#fff'; }
        }
    }
});

function toggleComplexInfraCategory(category) {
    const btn = document.querySelector(`[data-complex-infra="${category}"]`);
    if (!btn) return;
    if (complexInfraActive[category]) {
        if (complexInfraLayers[category] && complexesMap) {
            complexesMap.removeLayer(complexInfraLayers[category]);
        }
        delete complexInfraLayers[category];
        delete complexInfraActive[category];
        btn.style.borderColor = '#e5e7eb';
        btn.style.background = '#fff';
        btn.style.color = '#374151';
    } else {
        complexInfraActive[category] = true;
        btn.style.borderColor = '#0088CC';
        btn.style.background = '#e0f2fe';
        btn.style.color = '#0088CC';
        loadComplexInfraLayer(category);
    }
}

function loadComplexInfraLayer(category) {
    if (!complexesMap) return;
    const cfg = complexInfraCfg[category];
    const bounds = complexesMap.getBounds();
    const btn = document.querySelector(`[data-complex-infra="${category}"]`);
    if (btn) btn.style.opacity = '0.5';
    const query = `[out:json][timeout:25][bbox:${bounds.getSouth()},${bounds.getWest()},${bounds.getNorth()},${bounds.getEast()}];(node[${cfg.tag}];way[${cfg.tag}];);out center 100;`;
    const url = `https://overpass-api.de/api/interpreter?data=${encodeURIComponent(query)}`;
    fetch(url)
        .then(r => r.json())
        .then(function(data) {
            if (complexInfraLayers[category]) complexesMap.removeLayer(complexInfraLayers[category]);
            const group = L.layerGroup();
            (data.elements || []).forEach(function(el) {
                const lat = el.lat || (el.center && el.center.lat);
                const lon = el.lon || (el.center && el.center.lon);
                if (!lat || !lon) return;
                const name = (el.tags && (el.tags.name || el.tags['name:ru'])) || cfg.label;
                L.circleMarker([lat, lon], {
                    radius: 7, color: cfg.color, fillColor: cfg.color, fillOpacity: 0.8, weight: 2
                }).bindTooltip(name).addTo(group);
            });
            complexInfraLayers[category] = group;
            group.addTo(complexesMap);
            if (btn) btn.style.opacity = '1';
            console.log(`✅ Overpass complexes: ${(data.elements||[]).length} ${category}`);
        })
        .catch(function(e) { console.warn('Overpass error:', e); if (btn) btn.style.opacity = '1'; });
}

// Slider functionality
let sliders = {};

function nextSlide(complexId) {
    if (!sliders[complexId]) initSlider(complexId);
    const slider = sliders[complexId];
    slider.currentSlide = (slider.currentSlide + 1) % slider.totalSlides;
    updateSlider(complexId);
}

function prevSlide(complexId) {
    if (!sliders[complexId]) initSlider(complexId);
    const slider = sliders[complexId];
    slider.currentSlide = (slider.currentSlide - 1 + slider.totalSlides) % slider.totalSlides;
    updateSlider(complexId);
}

function goToSlide(complexId, slideIndex) {
    if (!sliders[complexId]) initSlider(complexId);
    sliders[complexId].currentSlide = slideIndex;
    updateSlider(complexId);
}

// Show company phone function
function showCompanyPhone(button) {
    const phoneText = button.querySelector('.phone-text');
    const icon = button.querySelector('i');
    const companyPhone = '+7 (862) 266-62-16';
    
    if (phoneText.textContent === 'Показать телефон') {
        phoneText.textContent = companyPhone;
        icon.classList.remove('fa-phone');
        icon.classList.add('fa-phone-alt');
        button.classList.remove('bg-[#0088CC]', 'hover:bg-[#006699]');
        button.classList.add('bg-green-500', 'hover:bg-green-600');
    } else {
        // If already showing, make call
        window.location.href = 'tel:+78622666216';
    }
}

// Make slider functions globally available for inline handlers
window.nextSlide = nextSlide;
window.prevSlide = prevSlide;
window.goToSlide = goToSlide;
window.showCompanyPhone = showCompanyPhone;

function initSlider(complexId) {
    const sliderContainer = document.querySelector(`.complex-slider[data-complex-id="${complexId}"]`);
    if (!sliderContainer) return;
    
    const slides = sliderContainer.querySelectorAll('.slider-slide');
    
    sliders[complexId] = {
        currentSlide: 0,
        totalSlides: slides.length
    };
    
    let touchStartX = 0;
    let touchEndX = 0;
    sliderContainer.addEventListener('touchstart', function(e) {
        touchStartX = e.changedTouches[0].screenX;
    }, {passive: true});
    sliderContainer.addEventListener('touchend', function(e) {
        touchEndX = e.changedTouches[0].screenX;
        const diff = touchStartX - touchEndX;
        if (Math.abs(diff) > 40) {
            if (diff > 0) {
                nextSlide(complexId);
            } else {
                prevSlide(complexId);
            }
        }
    }, {passive: true});
}

function updateSlider(complexId) {
    const slider = sliders[complexId];
    if (!slider) return;
    const sliderContainer = document.querySelector(`.complex-slider[data-complex-id="${complexId}"]`);
    if (!sliderContainer) return;
    const sliderElement = sliderContainer.querySelector('.slider-track');
    const dots = sliderContainer.querySelectorAll('.slider-dot');
    if (sliderElement) {
        sliderElement.style.transform = `translateX(-${slider.currentSlide * 100}%)`;
    }
    
    // Update dots
    dots.forEach((dot, index) => {
        if (index === slider.currentSlide) {
            dot.classList.add('active');
        } else {
            dot.classList.remove('active');
        }
    });
}

// Initialize sliders for existing cards
function initAllSliders() {
    document.querySelectorAll('.complex-slider').forEach(function(slider) {
        const complexId = slider.getAttribute('data-complex-id');
        if (complexId && !sliders[complexId]) {
            initSlider(complexId);
        }
    });
}

// Initialize when page loads
document.addEventListener('DOMContentLoaded', function() {
    setupComplexSearch();
    
    // Sync search fields between mobile and desktop
    const complexSearchDesktop = document.getElementById('complex-search');
    const complexSearchMobile = document.getElementById('complex-search-mobile');
    
    if (complexSearchDesktop && complexSearchMobile) {
        complexSearchDesktop.addEventListener('input', function() {
            complexSearchMobile.value = this.value;
            applyComplexFilters();
        });
        
        complexSearchMobile.addEventListener('input', function() {
            complexSearchDesktop.value = this.value;
            applyComplexFilters();
        });
    }
    
    // Set up filter event listeners - auto-apply filters on any change
    document.getElementById('district-filter')?.addEventListener('change', applyComplexFilters);
    document.getElementById('developer-filter')?.addEventListener('change', applyComplexFilters);
    document.getElementById('status-filter')?.addEventListener('change', applyComplexFilters);
    document.getElementById('sort-select')?.addEventListener('change', applyComplexFilters);
    
    // Add event listeners for new filters
    document.getElementById('object-class-filter')?.addEventListener('change', applyComplexFilters);
    document.getElementById('completion-year-filter')?.addEventListener('change', applyComplexFilters);
    document.getElementById('floors-filter')?.addEventListener('change', applyComplexFilters);
    document.getElementById('price-range-from')?.addEventListener('input', applyComplexFilters);
    document.getElementById('price-range-to')?.addEventListener('input', applyComplexFilters);
    
    // Setup global variables for filtering but DON'T apply filters initially
    // Variables already initialized above
    
    // Don't auto-filter on load — show all complexes; user filters manually
    // setTimeout(function() { applyComplexFilters(); }, 50);
    
    // Initialize sliders and favorites
    console.log('🚨 DOMContentLoaded: About to call initAllSliders() in 100ms');
    setTimeout(() => {
        console.log('⏰ setTimeout fired! Calling initAllSliders() now...');
        initAllSliders();
        if (typeof favoritesManager !== 'undefined') {
            favoritesManager.updateFavoritesUI();
            favoritesManager.updateComplexFavoritesUI();
            favoritesManager.updateFavoritesCounter();
        }
    }, 100);
});

// Apartments Modal Functions
let currentComplexData = null;
let currentApartmentType = null;
let selectedLiters = [];

function showApartments(complexId, apartmentType) {
    // Find complex data
    currentComplexData = allComplexes.find(c => c.id === complexId);
    currentApartmentType = apartmentType;
    
    if (!currentComplexData || !currentComplexData.apartment_types) {
        alert('Информация о квартирах недоступна');
        return;
    }
    
    // Find apartment type data
    const typeData = currentComplexData.apartment_types.find(t => t.type === apartmentType);
    if (!typeData) {
        alert('Данный тип квартир не найден');
        return;
    }
    
    // Update modal header
    document.getElementById('modalComplexName').textContent = currentComplexData.name;
    document.getElementById('modalApartmentType').textContent = `${apartmentType} • ${typeData.area_from}-${typeData.area_to} м² • от ${(typeData.price_from / 1000000).toFixed(1)} млн ₽`;
    
    // Show modal
    document.getElementById('apartmentsModal').classList.remove('hidden');
    
    // Initialize filters and apartments
    initializeLiterFilters();
    updateApartmentsDisplay();
    
    // Prevent body scroll using our system
    if (typeof window.lockBodyScroll === 'function') {
        window.lockBodyScroll();
    }
}

function closeApartmentsModal() {
    document.getElementById('apartmentsModal').classList.add('hidden');
    // Restore scroll using our system
    if (typeof window.unlockBodyScroll === 'function') {
        window.unlockBodyScroll();
    }
    currentComplexData = null;
    currentApartmentType = null;
    selectedLiters = [];
}

function initializeLiterFilters() {
    const filtersContainer = document.getElementById('literFilters');
    
    if (!currentComplexData.liters) {
        filtersContainer.innerHTML = '<div class="text-gray-500 text-sm">Информация о литерах недоступна</div>';
        return;
    }
    
    // Get all available liters for current apartment type
    const typeData = currentComplexData.apartment_types.find(t => t.type === currentApartmentType);
    const availableLifters = [];
    
    typeData.layouts.forEach(layout => {
        layout.available_liters.forEach(liter => {
            if (!availableLifters.includes(liter)) {
                availableLifters.push(liter);
            }
        });
    });
    
    // Create filter buttons
    let filtersHTML = `
        <button onclick="toggleLiterFilter('all')" 
                class="liter-filter px-3 py-2 border rounded-lg text-sm transition-colors bg-[#0088CC] text-white border-[#0088CC]" 
                data-liter="all">
            Все литеры
        </button>
    `;
    
    availableLifters.forEach(liter => {
        const literData = currentComplexData.liters.find(l => l.id === liter);
        const literName = literData ? literData.name : `Литер ${liter}`;
        
        filtersHTML += `
            <button onclick="toggleLiterFilter('${liter}')" 
                    class="liter-filter px-3 py-2 border border-gray-300 rounded-lg text-sm hover:border-[#0088CC] hover:bg-blue-50 transition-colors" 
                    data-liter="${liter}">
                ${literName}
            </button>
        `;
    });
    
    filtersContainer.innerHTML = filtersHTML;
    selectedLiters = ['all'];
}

function toggleLiterFilter(liter) {
    if (liter === 'all') {
        selectedLiters = ['all'];
    } else {
        if (selectedLiters.includes('all')) {
            selectedLiters = [liter];
        } else {
            const index = selectedLiters.indexOf(liter);
            if (index > -1) {
                selectedLiters.splice(index, 1);
                if (selectedLiters.length === 0) {
                    selectedLiters = ['all'];
                }
            } else {
                selectedLiters.push(liter);
            }
        }
    }
    
    // Update button states
    document.querySelectorAll('.liter-filter').forEach(btn => {
        const btnLiter = btn.getAttribute('data-liter');
        if (selectedLiters.includes(btnLiter)) {
            btn.className = 'liter-filter px-3 py-2 border rounded-lg text-sm transition-colors bg-[#0088CC] text-white border-[#0088CC]';
        } else {
            btn.className = 'liter-filter px-3 py-2 border border-gray-300 rounded-lg text-sm hover:border-[#0088CC] hover:bg-blue-50 transition-colors';
        }
    });
    
    updateApartmentsDisplay();
}

function updateApartmentsDisplay() {
    const apartmentsGrid = document.getElementById('apartmentsGrid');
    const noApartments = document.getElementById('noApartments');
    
    const typeData = currentComplexData.apartment_types.find(t => t.type === currentApartmentType);
    if (!typeData) return;
    
    // Filter layouts based on selected liters
    let filteredLayouts = typeData.layouts;
    if (!selectedLiters.includes('all')) {
        filteredLayouts = typeData.layouts.filter(layout => 
            layout.available_liters.some(liter => selectedLiters.includes(liter))
        );
    }
    
    if (filteredLayouts.length === 0) {
        apartmentsGrid.innerHTML = '';
        noApartments.classList.remove('hidden');
        return;
    }
    
    noApartments.classList.add('hidden');
    
    // Generate apartments grid
    let apartmentsHTML = '';
    filteredLayouts.forEach((layout, index) => {
        const availableInSelectedLiters = selectedLiters.includes('all') 
            ? layout.available_liters 
            : layout.available_liters.filter(liter => selectedLiters.includes(liter));
            
        const cashback = layout.price * 0.05;
        
        apartmentsHTML += `
            <div class="border border-gray-200 rounded-lg p-4 hover:border-[#0088CC] hover:shadow-md transition-all">
                <!-- Area and Price -->
                <div class="flex justify-between items-start mb-3">
                    <div>
                        <div class="text-lg font-bold text-gray-900">${layout.area} м²</div>
                        <div class="text-sm text-gray-500">${layout.floor_range} этаж</div>
                    </div>
                    <div class="text-right">
                        <div class="text-lg font-bold text-[#0088CC]">${(layout.price / 1000000).toFixed(1)} млн ₽</div>
                        <div class="text-xs text-gray-500">${Math.round(layout.price / layout.area).toLocaleString()} ₽/м²</div>
                    </div>
                </div>
                
                <!-- Available Liters -->
                <div class="mb-3">
                    <div class="text-xs text-gray-500 mb-1">Доступно в литерах:</div>
                    <div class="flex flex-wrap gap-1">
                        ${availableInSelectedLiters.map(liter => {
                            const literData = currentComplexData.liters.find(l => l.id === liter);
                            const literName = literData ? literData.name : `Литер ${liter}`;
                            return `<span class="px-2 py-1 bg-gray-100 text-gray-700 text-xs rounded">${literName}</span>`;
                        }).join('')}
                    </div>
                </div>
                
                <!-- Cashback -->
                <div class="bg-orange-50 border border-orange-200 rounded-lg p-2 mb-3">
                    <div class="text-xs text-orange-700 font-medium">Кэшбек ${currentComplexData.cashback_percent}%</div>
                    <div class="text-sm font-bold text-orange-800">до ${Math.round(cashback).toLocaleString()} ₽</div>
                </div>
                
                <!-- Availability -->
                <div class="flex justify-between items-center mb-3">
                    <div class="text-xs text-gray-500">Доступно квартир:</div>
                    <div class="text-sm font-medium text-green-600">${layout.available_count} шт</div>
                </div>
                
                <!-- Action Button -->
                <button onclick="selectApartment(${index})" 
                        class="w-full bg-[#0088CC] text-white py-2 px-4 rounded-lg text-sm font-medium hover:bg-[#006699] transition-colors">
                    Выбрать квартиру
                </button>
            </div>
        `;
    });
    
    apartmentsGrid.innerHTML = apartmentsHTML;
}

function selectApartment(layoutIndex) {
    const typeData = currentComplexData.apartment_types.find(t => t.type === currentApartmentType);
    const layout = typeData.layouts[layoutIndex];
    
    // Here you can add logic to handle apartment selection
    // For now, just show an alert
    alert(`Выбрана квартира:\n${currentApartmentType}, ${layout.area} м²\nЦена: ${(layout.price / 1000000).toFixed(1)} млн ₽\nЭтажи: ${layout.floor_range}\nКэшбек: до ${Math.round(layout.price * 0.05).toLocaleString()} ₽`);
    
    // You could redirect to a detailed apartment page or open a contact form
    // window.location.href = `/apartment/${currentComplexData.id}/${layoutIndex}`;
}

// Close modal when clicking outside
document.addEventListener('click', function(e) {
    if (e.target.id === 'apartmentsModal') {
        closeApartmentsModal();
    }
});

// Authentication status for manager features (безопасно)

console.log('Manager authenticated for complex recommendations:', window.isManagerAuthenticated);

// Initialize recommendation system for complexes
document.addEventListener('DOMContentLoaded', function() {
    if (window.isManagerAuthenticated) {
        console.log('Initializing complex recommendation buttons');
        initComplexRecommendationButtons();
    }
});

function initComplexRecommendationButtons() {
    // Count existing complex recommendation buttons
    const complexButtons = document.querySelectorAll('.recommend-btn[data-item-type="complex"]');
    console.log('Complex recommendation buttons initialized for', complexButtons.length, 'complexes');
}

// Recommendation modal functions (shared with properties.html)
function openRecommendModal(itemType, itemId, itemName) {
    // Check if modal already exists
    let modal = document.getElementById('recommendModal');
    if (!modal) {
        modal = createRecommendModal();
    }
    
    // Fill form with item data
    document.getElementById('recommendType').value = itemType;
    document.getElementById('recommendItemId').value = itemId;
    document.getElementById('recommendItemName').value = itemName;
    
    // Set default title based on type
    const titleInput = document.getElementById('recommendTitle');
    if (itemType === 'complex') {
        titleInput.value = `Рекомендую ЖК "${itemName}"`;
    } else {
        titleInput.value = `Рекомендую объект "${itemName}"`;
    }
    
    // Show modal
    modal.classList.remove('hidden');
    modal.classList.add('flex');
    
    // Load clients list
    loadClientsForRecommendation();
}

function createRecommendModal() {
    const modal = document.createElement('div');
    modal.id = 'recommendModal';
    modal.className = 'fixed inset-0 bg-black bg-opacity-50 z-50 hidden items-center justify-center';
    
    modal.innerHTML = `
        <div class="bg-white rounded-xl p-6 w-full max-w-lg mx-4 max-h-[90vh] overflow-y-auto">
            <div class="flex justify-between items-center mb-6">
                <h3 class="text-xl font-bold">Отправить рекомендацию</h3>
                <button onclick="closeRecommendModal()" class="text-gray-500 hover:text-gray-700">
                    <i class="fas fa-times text-xl"></i>
                </button>
            </div>
            
            <form id="recommendForm" class="space-y-4">
                <input type="hidden" id="recommendType" value="">
                <input type="hidden" id="recommendItemId" value="">
                <input type="hidden" id="recommendItemName" value="">
                
                <div>
                    <label class="block text-sm font-medium text-gray-700 mb-2">Выберите клиента *</label>
                    <select id="recommendClientSelect" class="w-full border border-gray-300 rounded-lg px-3 py-2 focus:ring-2 focus:ring-[#0088CC] focus:border-blue-500" required>
                        <option value="">Загрузка клиентов...</option>
                    </select>
                </div>
                
                <div>
                    <label class="block text-sm font-medium text-gray-700 mb-2">Email клиента</label>
                    <input type="email" id="recommendClientEmail" class="w-full border border-gray-300 rounded-lg px-3 py-2 bg-gray-100" readonly>
                </div>
                
                <div id="categorySection" class="hidden">
                    <label class="block text-sm font-medium text-gray-700 mb-2">Категория рекомендации</label>
                    <div class="space-y-2">
                        <select id="recommendCategorySelect" class="w-full border border-gray-300 rounded-lg px-3 py-2 focus:ring-2 focus:ring-[#0088CC] focus:border-blue-500">
                            <option value="">Без категории</option>
                            <option value="new">+ Создать новую категорию</option>
                        </select>
                        <div id="newCategoryInput" class="hidden">
                            <input type="text" id="recommendCategoryName" class="w-full border border-gray-300 rounded-lg px-3 py-2 focus:ring-2 focus:ring-[#0088CC] focus:border-blue-500" placeholder="Например: ЖК с детскими садами, Центральный район">
                        </div>
                    </div>
                </div>
                
                <div>
                    <label class="block text-sm font-medium text-gray-700 mb-2">Заголовок рекомендации *</label>
                    <input type="text" id="recommendTitle" class="w-full border border-gray-300 rounded-lg px-3 py-2 focus:ring-2 focus:ring-[#0088CC] focus:border-blue-500" required>
                </div>
                
                <div>
                    <label class="block text-sm font-medium text-gray-700 mb-2">Описание</label>
                    <textarea id="recommendDescription" rows="3" class="w-full border border-gray-300 rounded-lg px-3 py-2 focus:ring-2 focus:ring-[#0088CC] focus:border-blue-500" placeholder="Почему этот объект подходит клиенту..."></textarea>
                </div>
                
                <div>
                    <label class="block text-sm font-medium text-gray-700 mb-2">Заметки менеджера</label>
                    <textarea id="recommendNotes" rows="2" class="w-full border border-gray-300 rounded-lg px-3 py-2 focus:ring-2 focus:ring-[#0088CC] focus:border-blue-500" placeholder="Внутренние заметки..."></textarea>
                </div>
                
                <div>
                    <label class="block text-sm font-medium text-gray-700 mb-2">Приоритет</label>
                    <select id="recommendPriority" class="w-full border border-gray-300 rounded-lg px-3 py-2 focus:ring-2 focus:ring-[#0088CC] focus:border-blue-500">
                        <option value="medium">Обычный</option>
                        <option value="high">Высокий</option>
                        <option value="low">Низкий</option>
                    </select>
                </div>
                
                <div class="flex gap-3 pt-4">
                    <button type="submit" id="submitRecommendBtn" class="flex-1 bg-orange-500 text-white py-2 px-4 rounded-lg hover:bg-orange-600 transition-colors disabled:bg-gray-400 disabled:cursor-not-allowed">
                        <i class="fas fa-paper-plane mr-2" id="submitIcon"></i>
                        <span class="loading-spinner hidden mr-2">
                            <svg class="animate-spin h-4 w-4 text-white" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                                <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                                <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                            </svg>
                        </span>
                        <span id="submitText">Отправить рекомендацию</span>
                    </button>
                    <button type="button" onclick="closeRecommendModal()" class="px-4 py-2 border border-gray-300 text-gray-700 rounded-lg hover:bg-gray-50 transition-colors">
                        Отмена
                    </button>
                </div>
            </form>
        </div>
    `;
    
    document.body.appendChild(modal);
    
    // Add form submit handler
    document.getElementById('recommendForm').addEventListener('submit', handleRecommendSubmit);
    
    return modal;
}

// Load clients for recommendation dropdown
async function loadClientsForRecommendation() {
    try {
        const response = await fetch('/api/manager/clients');
        const data = await response.json();
        
        const select = document.getElementById('recommendClientSelect');
        select.innerHTML = '<option value="">Выберите клиента...</option>';
        
        if (data.success && data.clients) {
            data.clients.forEach(client => {
                const option = document.createElement('option');
                option.value = client.id;
                option.textContent = `${client.full_name} (${client.email})`;
                option.dataset.email = client.email;
                select.appendChild(option);
            });
            
            // Add change handler
            select.addEventListener('change', function() {
                const selectedOption = this.options[this.selectedIndex];
                const emailInput = document.getElementById('recommendClientEmail');
                const categorySection = document.getElementById('categorySection');
                
                if (selectedOption.dataset.email) {
                    emailInput.value = selectedOption.dataset.email;
                    categorySection.classList.remove('hidden');
                    loadRecommendationCategories(this.value);
                } else {
                    emailInput.value = '';
                    categorySection.classList.add('hidden');
                }
            });
        }
    } catch (error) {
        console.error('Error loading clients:', error);
    }
}

// Load recommendation categories for selected client
async function loadRecommendationCategories(clientId) {
    try {
        const response = await fetch(`/api/manager/recommendation-categories/${clientId}`);
        const data = await response.json();
        
        const select = document.getElementById('recommendCategorySelect');
        select.innerHTML = '<option value="">Без категории</option><option value="new">+ Создать новую категорию</option>';
        
        if (data.success && data.categories) {
            data.categories.forEach(category => {
                const option = document.createElement('option');
                option.value = category.id;
                option.textContent = `${category.name} (${category.recommendations_count})`;
                select.appendChild(option);
            });
        }
        
        // Add change handler for category selection
        select.addEventListener('change', function() {
            const newCategoryInput = document.getElementById('newCategoryInput');
            if (this.value === 'new') {
                newCategoryInput.classList.remove('hidden');
            } else {
                newCategoryInput.classList.add('hidden');
            }
        });
        
    } catch (error) {
        console.error('Error loading categories:', error);
    }
}

function closeRecommendModal() {
    const modal = document.getElementById('recommendModal');
    if (modal) {
        modal.classList.add('hidden');
        modal.classList.remove('flex');
        document.getElementById('recommendForm').reset();
        
        // Reset button state
        const submitBtn = document.getElementById('submitRecommendBtn');
        const submitIcon = document.getElementById('submitIcon');
        const submitText = document.getElementById('submitText');
        const spinner = submitBtn.querySelector('.loading-spinner');
        
        submitBtn.disabled = false;
        submitBtn.classList.remove('bg-green-500');
        submitBtn.classList.add('bg-orange-500', 'hover:bg-orange-600');
        spinner.classList.add('hidden');
        submitIcon.classList.remove('hidden');
        submitIcon.className = 'fas fa-paper-plane mr-2';
        submitText.textContent = 'Отправить рекомендацию';
    }
}

async function handleRecommendSubmit(e) {
    e.preventDefault();
    
    const clientSelect = document.getElementById('recommendClientSelect');
    const selectedClientId = clientSelect.value;
    
    if (!selectedClientId) {
        alert('Выберите клиента для отправки рекомендации');
        return;
    }
    
    const categorySelect = document.getElementById('recommendCategorySelect');
    const categoryValue = categorySelect ? categorySelect.value : '';
    const categoryName = categoryValue === 'new' ? document.getElementById('recommendCategoryName').value.trim() : '';
    
    const formData = {
        recommendation_type: document.getElementById('recommendType').value,
        item_id: document.getElementById('recommendItemId').value,
        item_name: document.getElementById('recommendItemName').value,
        title: document.getElementById('recommendTitle').value.trim(),
        client_id: selectedClientId,
        client_email: document.getElementById('recommendClientEmail').value.trim(),
        description: document.getElementById('recommendDescription').value.trim(),
        manager_notes: document.getElementById('recommendNotes').value.trim(),
        priority_level: document.getElementById('recommendPriority').value,
        category_id: categoryValue,
        category_name: categoryName,
        highlighted_features: [], 
        item_data: {}
    };
    
    if (!formData.title) {
        alert('Введите заголовок рекомендации');
        return;
    }
    
    // Show loading state
    showRecommendationLoading();
    
    try {
        const response = await fetch('/api/manager/send_recommendation', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(formData)
        });
        
        const result = await response.json();
        
        if (result.success) {
            showRecommendationSuccess();
            setTimeout(() => {
                closeRecommendModal();
            }, 1500);
        } else {
            showRecommendationError('Ошибка: ' + result.error);
        }
    } catch (error) {
        showRecommendationError('Ошибка отправки рекомендации: ' + error.message);
    }
}

function showRecommendationLoading() {
    const submitBtn = document.getElementById('submitRecommendBtn');
    const submitIcon = document.getElementById('submitIcon');
    const submitText = document.getElementById('submitText');
    const spinner = submitBtn.querySelector('.loading-spinner');
    
    submitBtn.disabled = true;
    submitIcon.classList.add('hidden');
    spinner.classList.remove('hidden');
    submitText.textContent = 'Отправка...';
}

function showRecommendationSuccess() {
    const submitBtn = document.getElementById('submitRecommendBtn');
    const submitIcon = document.getElementById('submitIcon');
    const submitText = document.getElementById('submitText');
    const spinner = submitBtn.querySelector('.loading-spinner');
    
    spinner.classList.add('hidden');
    submitIcon.classList.remove('hidden');
    submitIcon.className = 'fas fa-check mr-2';
    submitText.textContent = 'Отправлено!';
    submitBtn.classList.remove('bg-orange-500', 'hover:bg-orange-600');
    submitBtn.classList.add('bg-green-500');
}

function showRecommendationError(message) {
    const submitBtn = document.getElementById('submitRecommendBtn');
    const submitIcon = document.getElementById('submitIcon');
    const submitText = document.getElementById('submitText');
    const spinner = submitBtn.querySelector('.loading-spinner');
    
    submitBtn.disabled = false;
    spinner.classList.add('hidden');
    submitIcon.classList.remove('hidden');
    submitIcon.className = 'fas fa-paper-plane mr-2';
    submitText.textContent = 'Отправить рекомендацию';
    
    alert(message);
}

// ✅ ИСПРАВЛЕНО: Добавление в сравнение через базу данных
async function addToComparison(type, id) {
    const idStr = id.toString();
    
    try {
        if (type === 'complex') {
            // ✅ КРИТИЧНО: Проверяем роль пользователя для выбора правильного endpoint  
            const isManager = Boolean(window.manager_authenticated);
            const endpoint = isManager ? '/api/manager/comparison/complex/add' : '/api/user/comparison/complex/add';
            
            console.log(`🏢 Adding complex to comparison for ${isManager ? 'manager' : 'user'} via ${endpoint}`);
            
            // ✅ Используем API endpoint для сохранения в БД
            const complexCard = document.querySelector(`[data-complex-id="${idStr}"]`);
            const complexData = {
                complex_id: idStr,
                complex_name: complexCard?.querySelector('h3')?.textContent || `ЖК ${idStr}`,
                developer: complexCard?.querySelector('.developer')?.textContent || '',
                district: complexCard?.querySelector('.district')?.textContent || '',
                min_price: null,
                max_price: null,
                photo: complexCard?.querySelector('img')?.src || '',
                buildings_count: null,
                apartments_count: null,
                completion_date: '',
                cashback_rate: parseFloat(complexCard?.dataset.cashbackRate || '5.0')  // Реальный кэшбек из админ панели
            };
            
            const response = await fetch(endpoint, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': document.querySelector('meta[name="csrf-token"]')?.content || ''
                },
                credentials: 'same-origin',
                body: JSON.stringify(complexData)
            });
            
            const result = await response.json();
            
            if (result.success) {
                showNotification('ЖК добавлен в сравнение', 'success');
                console.log('✅ Complex saved to database:', id);
            } else {
                showNotification(result.error || 'Ошибка при добавлении ЖК', 'error');
            }
            
        } else if (type === 'property') {
            // ✅ КРИТИЧНО: Проверяем роль пользователя для выбора правильного endpoint
            const isManager = Boolean(window.manager_authenticated);
            const endpoint = isManager ? '/api/manager/comparison/property/add' : '/api/comparison/property/add';
            
            console.log(`🏠 Adding property to comparison for ${isManager ? 'manager' : 'user'} via ${endpoint}`);
            
            // ✅ Используем API endpoint для сохранения квартир в БД
            // ✅ ИСПРАВЛЕНО: Убрал несуществующие поля из модели ComparisonProperty
            const propertyData = {
                property_id: idStr,
                property_name: document.querySelector(`[data-property-id="${idStr}"] .title`)?.textContent || `Квартира ${idStr}`,
                property_price: null,
                property_address: '',
                property_image: document.querySelector(`[data-property-id="${idStr}"] img`)?.src || ''
            };
            
            const response = await fetch(endpoint, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': document.querySelector('meta[name="csrf-token"]')?.content || ''
                },
                credentials: 'same-origin',
                body: JSON.stringify(propertyData)
            });
            
            const result = await response.json();
            
            if (result.success) {
                showNotification('Квартира добавлена в сравнение', 'success');
                console.log('✅ Property saved to database:', id);
            } else {
                showNotification(result.error || 'Ошибка при добавлении квартиры', 'error');
            }
        }
        
        // Update UI if comparison counter exists
        updateComparisonCounter();
        
    } catch (error) {
        console.error('Error adding to comparison:', error);
        showNotification('Ошибка подключения к серверу', 'error');
        
        // ✅ ИСПРАВЛЕНО: Используем PostgreSQL менеджер вместо прямого localStorage
        console.log('API недоступен, используем PostgreSQL менеджер fallback');
        
        // Делегируем к PostgreSQL менеджеру из properties-comparison-fix.js
        if (window.simpleComparisonManager) {
            if (type === 'complex') {
                await window.simpleComparisonManager.toggleComplexComparison(idStr, null);
            } else if (type === 'property') {
                await window.simpleComparisonManager.toggleComparison(idStr, null);
            }
        } else {
            // Запасной fallback если менеджер не загружен
            console.warn('PostgreSQL менеджер не найден, используем minimal localStorage');
            showNotification('Данные сохранены локально - обновите страницу', 'warning');
        }
    }
}

// Simple notification function
function showNotification(message, type = 'info') {
    // Create notification element
    const notification = document.createElement('div');
    notification.className = `fixed top-4 right-4 px-4 py-2 rounded-lg text-white z-50 transition-all duration-300 ${
        type === 'success' ? 'bg-green-500' : 
        type === 'warning' ? 'bg-yellow-500' : 
        type === 'error' ? 'bg-red-500' : 'bg-blue-500'
    }`;
    notification.textContent = message;
    
    document.body.appendChild(notification);
    
    // Remove after 3 seconds
    setTimeout(() => {
        notification.remove();
    }, 3000);
}

// ✅ ИСПРАВЛЕНО: Делегируем счетчики к PostgreSQL менеджеру  
function updateComparisonCounter() {
    // Приоритет: PostgreSQL менеджер из properties-comparison-fix.js
    if (window.simpleComparisonManager) {
        // Используем данные из PostgreSQL менеджера
        const totalCount = window.simpleComparisonManager.comparisons.length + 
                          window.simpleComparisonManager.complexComparisons.length;
        
        console.log('✅ Счетчики обновлены из PostgreSQL менеджера:', totalCount);
        
        // Update any comparison counters on the page
        const counters = document.querySelectorAll('[data-comparison-counter]');
        counters.forEach(counter => {
            counter.textContent = totalCount;
            counter.style.display = totalCount > 0 ? 'inline' : 'none';
        });
    } else {
        // Fallback: попробуем позже когда менеджер загрузится
        console.log('🔄 PostgreSQL менеджер еще не загружен, попробуем позже...');
        setTimeout(updateComparisonCounter, 1000);
    }
}

// Initialize comparison counter on page load
document.addEventListener('DOMContentLoaded', function() {
    updateComparisonCounter();
});

// View mode switching
let currentViewMode = 'grid'; // Default to grid

function switchToGridView() {
    currentViewMode = 'grid';
    const container = document.getElementById('complexes-container');
    const gridBtn = document.getElementById('grid-view-btn');
    const listBtn = document.getElementById('list-view-btn');
    
    // Update container classes
    container.className = 'grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4 sm:gap-6';
    
    // Update button states
    gridBtn.className = 'flex items-center px-3 py-2 rounded-md text-sm font-medium transition-colors bg-white text-gray-900 shadow-sm';
    listBtn.className = 'flex items-center px-3 py-2 rounded-md text-sm font-medium transition-colors text-gray-600 hover:text-gray-900';
    
    // Restore original card structure and styles
    const cards = container.querySelectorAll('.complex-card');
    cards.forEach(card => {
        // Restore original structure if it was saved
        if (card.dataset.originalStructure) {
            card.innerHTML = card.dataset.originalStructure;
            delete card.dataset.originalStructure;
        }
        card.className = 'complex-card bg-white rounded-2xl shadow-lg overflow-hidden border border-gray-100 hover:shadow-xl transition-all duration-300 mobile-optimized';
    });
    
    console.log('Switched to grid view');
}

function switchToListView() {
    currentViewMode = 'list';
    const container = document.getElementById('complexes-container');
    const gridBtn = document.getElementById('grid-view-btn');
    const listBtn = document.getElementById('list-view-btn');
    
    // Update container classes
    container.className = 'space-y-6';
    
    // Update button states
    gridBtn.className = 'flex items-center px-3 py-2 rounded-md text-sm font-medium transition-colors text-gray-600 hover:text-gray-900';
    listBtn.className = 'flex items-center px-3 py-2 rounded-md text-sm font-medium transition-colors bg-white text-gray-900 shadow-sm';
    
    // Update card styles for list view
    const cards = container.querySelectorAll('.complex-card');
    cards.forEach(card => {
        card.className = 'complex-card bg-white rounded-xl shadow-sm border border-gray-200 hover:shadow-md transition-all duration-300 list-view-card';
        // Restructure card layout for list view
        restructureCardForList(card);
    });
    
    console.log('Switched to list view');
}

function restructureCardForList(card) {
    // Check if already restructured for list view
    if (card.querySelector('.list-layout')) return;
    
    // Get data from card
    const complexId = card.dataset.complexId;
    const imageSlider = card.querySelector('.complex-slider');
    const nameElement = card.querySelector('h3');
    const developerElement = card.querySelector('a[href*="developer"], p.text-gray-500');
    const descriptionElement = card.querySelector('p.text-gray-600.line-clamp-2');
    const locationElement = card.querySelector('.fa-map-marker-alt').parentElement;
    const completionElement = card.querySelector('.fa-calendar').parentElement;
    const statusElement = card.querySelector('.bg-green-100, .bg-orange-100');
    const statsGrid = card.querySelector('.grid.grid-cols-2');
    const apartmentTypes = card.querySelector('.border-t');
    const buttons = card.querySelector('.flex.gap-2');
    
    if (!imageSlider || !nameElement) return;
    
    // Save original structure for potential switch back
    if (!card.dataset.originalStructure) {
        card.dataset.originalStructure = card.innerHTML;
    }
    
    // Create horizontal layout
    const newLayout = document.createElement('div');
    newLayout.className = 'list-layout flex gap-6 p-6';
    
    // Left side - Image (much larger to match content properly)
    const imageContainer = document.createElement('div');
    imageContainer.className = 'flex-shrink-0 w-96';
    const clonedSlider = imageSlider.cloneNode(true);
    clonedSlider.style.height = '320px';
    clonedSlider.style.width = '100%';
    clonedSlider.style.borderRadius = '12px';
    clonedSlider.style.overflow = 'hidden';
    clonedSlider.style.position = 'relative';
    
    // Force all images to fill the container
    const images = clonedSlider.querySelectorAll('img');
    images.forEach(img => {
        img.style.width = '100%';
        img.style.height = '320px';
        img.style.objectFit = 'cover';
        img.style.display = 'block';
    });
    
    // Completion date will be added to content block instead of slider
    
    imageContainer.appendChild(clonedSlider);
    
    // Right side - All content with relative positioning for completion date
    const contentContainer = document.createElement('div');
    contentContainer.className = 'flex-1 space-y-4 relative';
    
    // Header with name, developer and location (completion date moved to slider)
    const header = document.createElement('div');
    const developerText = developerElement ? developerElement.textContent : '';
    const locationText = locationElement ? locationElement.textContent.replace(/^\s*/, '') : '';
    const descriptionText = descriptionElement ? descriptionElement.textContent : '';
    
    header.innerHTML = `
        <h3 class="text-xl font-bold text-gray-900 mb-1">${nameElement.textContent}</h3>
        ${developerText ? `<div class="text-sm text-[#0088CC] mb-2">${developerText}</div>` : ''}
        <div class="flex items-center text-gray-600 mb-2">
            <i class="fas fa-map-marker-alt mr-2"></i>
            <span>${locationText}</span>
        </div>
        ${descriptionText ? `<p class="text-sm text-gray-600 mb-3" style="overflow:hidden;display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;max-height:4.5em;">${descriptionText}</p>` : ''}
    `;
    
    // Stats in horizontal layout
    const statsContainer = document.createElement('div');
    statsContainer.className = 'flex flex-wrap gap-6 text-sm';
    if (statsGrid) {
        const statItems = statsGrid.querySelectorAll('.flex.items-center');
        statItems.forEach(item => {
            const cloned = item.cloneNode(true);
            statsContainer.appendChild(cloned);
        });
    }
    
    // Apartment types with prices in horizontal layout
    const apartmentContainer = document.createElement('div');
    if (apartmentTypes) {
        const roomButtons = apartmentTypes.querySelectorAll('button');
        if (roomButtons.length > 0) {
            apartmentContainer.innerHTML = '<div class="text-sm text-gray-600 mb-3">Квартиры:</div>';
            const roomsContainer = document.createElement('div');
            roomsContainer.className = 'flex flex-wrap gap-3';
            
            roomButtons.forEach(btn => {
                const roomType = btn.querySelector('.font-medium')?.textContent || '';
                const area = btn.querySelector('.text-xs.text-gray-500')?.textContent || '';
                const price = btn.querySelector('.text-xs.font-medium.text-\\[\\#0088CC\\]')?.textContent || '';
                const count = btn.querySelector('.text-xs.text-green-600')?.textContent || '';
                
                const roomCard = document.createElement('div');
                roomCard.className = 'flex items-center justify-between bg-gray-50 rounded-lg p-3 min-w-[200px] cursor-pointer hover:bg-gray-100 transition-colors';
                roomCard.onclick = () => btn.click(); // Preserve original functionality
                
                roomCard.innerHTML = `
                    <div>
                        <div class="font-medium text-gray-900">${roomType}</div>
                        ${area ? `<div class="text-xs text-gray-500">${area}</div>` : ''}
                        ${count ? `<div class="text-xs text-green-600">${count}</div>` : ''}
                    </div>
                    ${price ? `<div class="text-sm font-bold text-[#0088CC]">${price}</div>` : ''}
                `;
                
                roomsContainer.appendChild(roomCard);
            });
            apartmentContainer.appendChild(roomsContainer);
        }
    }
    
    // Action buttons (only manager recommendation button)
    const actionsContainer = document.createElement('div');
    const managerButtons = card.querySelector('.recommend-btn');
    if (managerButtons) {
        const clonedManagerButtons = managerButtons.cloneNode(true);
        actionsContainer.appendChild(clonedManagerButtons);
    }
    
    // Add completion date badge in top right of content area (minimalist style)
    const completionText = completionElement ? completionElement.textContent.replace(/^\s*/, '') : '';
    const statusText = statusElement ? statusElement.textContent.trim() : '';
    if (completionText) {
        const dateBadge = document.createElement('div');
        dateBadge.className = `absolute top-0 right-0 ${statusText === 'Сдан' ? 'bg-gray-100 text-gray-700' : 'bg-gray-100 text-gray-700'} px-3 py-1 rounded-bl text-xs font-medium`;
        dateBadge.textContent = completionText;
        contentContainer.appendChild(dateBadge);
    }
    
    // Assemble content
    contentContainer.appendChild(header);
    contentContainer.appendChild(statsContainer);
    contentContainer.appendChild(apartmentContainer);
    contentContainer.appendChild(actionsContainer);
    
    // Replace card content
    card.innerHTML = '';
    newLayout.appendChild(imageContainer);
    newLayout.appendChild(contentContainer);
    card.appendChild(newLayout);
    
    // JavaScript version of create_slug function
    function createSlug(name) {
        if (!name) return "unknown";
        
        // Transliteration map
        const translitMap = {
            'а': 'a', 'б': 'b', 'в': 'v', 'г': 'g', 'д': 'd', 'е': 'e', 'ё': 'yo',
            'ж': 'zh', 'з': 'z', 'и': 'i', 'й': 'y', 'к': 'k', 'л': 'l', 'м': 'm',
            'н': 'n', 'о': 'o', 'п': 'p', 'р': 'r', 'с': 's', 'т': 't', 'у': 'u',
            'ф': 'f', 'х': 'h', 'ц': 'ts', 'ч': 'ch', 'ш': 'sh', 'щ': 'sch', 'ъ': '',
            'ы': 'y', 'ь': '', 'э': 'e', 'ю': 'yu', 'я': 'ya',
            'А': 'A', 'Б': 'B', 'В': 'V', 'Г': 'G', 'Д': 'D', 'Е': 'E', 'Ё': 'Yo',
            'Ж': 'Zh', 'З': 'Z', 'И': 'I', 'Й': 'Y', 'К': 'K', 'Л': 'L', 'М': 'M',
            'Н': 'N', 'О': 'O', 'П': 'P', 'Р': 'R', 'С': 'S', 'Т': 'T', 'У': 'U',
            'Ф': 'F', 'Х': 'H', 'Ц': 'Ts', 'Ч': 'Ch', 'Ш': 'Sh', 'Щ': 'Sch', 'Ъ': '',
            'Ы': 'Y', 'Ь': '', 'Э': 'E', 'Ю': 'Yu', 'Я': 'Ya'
        };
        
        // Remove ЖК prefix and quotes
        name = name.replace(/^ЖК\s*["']?/i, '').replace(/["']/g, '');
        
        // Transliterate
        let slug = '';
        for (let char of name) {
            slug += translitMap[char] || char;
        }
        
        // Clean up
        slug = slug.replace(/[^\w\s-]/g, '').replace(/[-\s]+/g, '-').toLowerCase().replace(/^-+|-+$/g, '');
        
        return slug;
    }

    // Add click handler for card navigation
    // Use complex.url if available (already includes city_slug), otherwise construct URL
    const complexUrl = card.getAttribute('onclick')?.match(/'([^']+)'/)?.[1];
    if (complexUrl) {
        card.style.cursor = 'pointer';
        card.onclick = (event) => handleCardClick(event, complexUrl);
    }
    
    // Reinitialize sliders for the cloned elements
    reinitializeSlider(clonedSlider);
}

function reinitializeSlider(sliderElement) {
    // Find slider controls and re-attach event listeners
    const complexId = sliderElement.dataset.complexId;
    if (complexId) {
        const prevBtn = sliderElement.querySelector('.slider-prev');
        const nextBtn = sliderElement.querySelector('.slider-next');
        
        if (prevBtn) prevBtn.onclick = () => prevSlide(complexId);
        if (nextBtn) nextBtn.onclick = () => nextSlide(complexId);
    }
}

// Handle card clicks for navigation while preserving button functionality
function handleCardClick(event, url) {
    // Check if click was on a button or interactive element
    const target = event.target;
    const isButton = target.tagName === 'BUTTON' || target.closest('button');
    const isLink = target.tagName === 'A' || target.closest('a');
    const isInteractive = target.closest('.apartment-types') || target.closest('.favorites-btn') || target.closest('.compare-btn') || target.closest('.favorite-heart');
    
    // If click was on interactive element, don't navigate
    if (isButton || isLink || isInteractive) {
        console.log('⏸️ handleCardClick: Ignoring click on interactive element');
        return;
    }
    
    // Navigate to complex detail page
    console.log('🔗 handleCardClick: Navigating to:', url);
    window.location.href = url;
}


</script>
