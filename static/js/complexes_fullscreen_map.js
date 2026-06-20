// Complexes Fullscreen Map (Yandex Maps - Residential Complexes)
console.log('🏢 complexes_fullscreen_map.js загружен');

// Global mouse position tracker (used by hover tooltip positioning)
document.addEventListener('mousemove', function(e) { window._lastMouseEvt = e; }, { passive: true });
let fullscreenComplexesMapInstance = null;
let mapInitTimeout = null;
let ymapsRetryTimeout = null;
let allComplexMarkers = []; // Store all markers for filtering
let allComplexesData = []; // Store all complexes data

// Check if device is mobile
function isMobileDevice() {
    return window.innerWidth <= 768;
}

// Get marker color based on complex status
function getComplexMarkerColor(status) {
    const statusLower = (status || '').toLowerCase();
    console.log('🎨 Status for color:', statusLower);
    
    // Green - already delivered
    if (statusLower.includes('сдан') || statusLower.includes('готов')) {
        return '#22c55e';
    }
    
    // Blue - under construction (includes "кв." dates like "2 кв. 2026")
    if (statusLower.includes('строит') || statusLower.includes('стро') || statusLower.includes('кв.') || statusLower.includes('кв ')) {
        return '#3b82f6';
    }
    
    // Orange - planned/project stage
    if (statusLower.includes('план') || statusLower.includes('проект')) {
        return '#f97316';
    }
    
    // Default to blue for any future date (under construction)
    return '#3b82f6';
}

// Get status display text
function getStatusDisplayText(status, completionYear, completionQuarter) {
    const today = new Date('2026-02-04');
    const currentYear = today.getFullYear();
    const currentQuarter = Math.floor((today.getMonth() + 3) / 3);
    
    if (!completionYear) {
        const s = (status || '').toLowerCase();
        if (s.includes('сдан') || s.includes('готов')) return 'Сдан';
        if (s.includes('стро') || s.includes('кв')) return status;
        return 'Сдан';
    }
    
    if (completionYear < currentYear || (completionYear === currentYear && completionQuarter <= currentQuarter)) {
        return 'Сдан';
    }
    
    return `${completionQuarter} кв. ${completionYear}`;
}

// Open fullscreen complexes map modal
function openFullscreenComplexesMap() {
    const modal = document.getElementById('fullscreenComplexesMapModal');
    if (!modal) {
        console.warn('🏢 Modal element not found');
        return;
    }
    
    console.log('🏢 Opening fullscreen complexes map modal');
    modal.classList.remove('hidden');
    document.body.style.overflow = 'hidden';
    const siteHeader = document.querySelector('header.sticky');
    if (siteHeader) siteHeader.style.display = 'none';
    const mobileNav = document.getElementById('mobileBottomNav');
    if (mobileNav) mobileNav.style.display = 'none';
    // Hide Chaport chat widget — use body class so lazy-loaded Chaport is also hidden
    document.body.classList.add('fullscreen-map-open');
    const chaport = document.getElementById('chaport-container');
    if (chaport) chaport.style.setProperty('display', 'none', 'important');
    // Explicitly hide InBack chat FAB elements
    ['chatFab', 'chatFabRing', 'inbackChatPanel'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.style.setProperty('display', 'none', 'important');
    });
    // Hide pwa-gamification HUD mascot widget
    const hudMascot = document.getElementById('hud-mascot');
    if (hudMascot) hudMascot.style.setProperty('display', 'none', 'important');
    
    // Initialize map after modal is visible
    mapInitTimeout = setTimeout(() => {
        if (!modal.classList.contains('hidden')) {
            initFullscreenComplexesMap();
        }
        mapInitTimeout = null;
    }, 100);
}

// Close fullscreen complexes map modal
function closeFullscreenComplexesMap() {
    const modal = document.getElementById('fullscreenComplexesMapModal');
    if (!modal) return;
    
    console.log('🏢 Closing fullscreen complexes map modal');
    modal.classList.add('hidden');
    document.body.style.overflow = '';
    document.body.style.pointerEvents = '';
    const siteHeader = document.querySelector('header.sticky');
    if (siteHeader) { siteHeader.style.display = ''; siteHeader.style.pointerEvents = ''; siteHeader.style.zIndex = ''; }
    const mobileNav = document.getElementById('mobileBottomNav');
    if (mobileNav) mobileNav.style.display = '';
    // Show Chaport chat widget again
    document.body.classList.remove('fullscreen-map-open');
    const chaport = document.getElementById('chaport-container');
    if (chaport) chaport.style.setProperty('display', '', 'important');
    // Restore InBack chat FAB elements
    ['chatFab', 'chatFabRing', 'inbackChatPanel'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.style.removeProperty('display');
    });
    // Restore pwa-gamification HUD mascot widget
    const hudMascotRestore = document.getElementById('hud-mascot');
    if (hudMascotRestore) hudMascotRestore.style.removeProperty('display');
    
    // Cancel pending map initialization
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
    if (fullscreenComplexesMapInstance) {
        fullscreenComplexesMapInstance.destroy();
        fullscreenComplexesMapInstance = null;
    }
}

// Group complexes by location (same coordinates)
function groupComplexesByLocation(complexes) {
    const groups = {};
    
    complexes.forEach(complex => {
        const lat = complex.latitude || (complex.coordinates && complex.coordinates.lat);
        const lng = complex.longitude || (complex.coordinates && complex.coordinates.lng);
        
        if (lat && lng) {
            const key = `${lat.toFixed(5)}_${lng.toFixed(5)}`;
            if (!groups[key]) {
                groups[key] = {
                    lat: lat,
                    lng: lng,
                    complexes: []
                };
            }
            // Ensure complex has coordinates in expected format
            if (!complex.coordinates) {
                complex.coordinates = { lat: lat, lng: lng };
            }
            groups[key].complexes.push(complex);
        }
    });
    
    return Object.values(groups);
}

// Format price for display
function formatPrice(price) {
    if (!price) return 'По запросу';
    return new Intl.NumberFormat('ru-RU').format(price) + ' ₽';
}

// Store current status filters globally (can be multiple)
let activeStatusFilters = [];

function filterByStatus(status, buttonElement) {
    if (!allComplexesData) return;
    
    console.log('🏢 Toggle filter status:', status);
    
    // "Все" button resets all filters
    if (status === '') {
        activeStatusFilters = [];
        // Reset all buttons
        const allChips = document.querySelectorAll('.fullscreen-status-chip');
        allChips.forEach(chip => {
            chip.classList.remove('active', 'bg-[#0088CC]', 'text-white', 'border-[#0088CC]');
            chip.classList.add('border-gray-200');
        });
        // Activate "Все" button
        if (buttonElement) {
            buttonElement.classList.add('active', 'bg-[#0088CC]', 'text-white', 'border-[#0088CC]');
            buttonElement.classList.remove('border-gray-200');
        }
    } else {
        // Toggle the status in the array
        const index = activeStatusFilters.indexOf(status);
        if (index > -1) {
            activeStatusFilters.splice(index, 1);
            if (buttonElement) {
                buttonElement.classList.remove('active', 'bg-[#0088CC]', 'text-white', 'border-[#0088CC]');
                buttonElement.classList.add('border-gray-200');
            }
        } else {
            activeStatusFilters.push(status);
            if (buttonElement) {
                buttonElement.classList.add('active', 'bg-[#0088CC]', 'text-white', 'border-[#0088CC]');
                buttonElement.classList.remove('border-gray-200');
            }
        }
        
        // Deactivate "Все" button when specific filters are selected
        const allButton = document.querySelector('.fullscreen-status-chip[data-status=""]');
        if (allButton) {
            if (activeStatusFilters.length > 0) {
                allButton.classList.remove('active', 'bg-[#0088CC]', 'text-white', 'border-[#0088CC]');
                allButton.classList.add('border-gray-200');
            } else {
                allButton.classList.add('active', 'bg-[#0088CC]', 'text-white', 'border-[#0088CC]');
                allButton.classList.remove('border-gray-200');
            }
        }
    }
    
    console.log('🏢 Active status filters:', activeStatusFilters);
    
    // Apply all filters
    applyAllFiltersToMap();
}

// Reset all map filters
function resetAllMapFilters() {
    console.log('🏢 Resetting all map filters');
    
    // Reset status filters
    activeStatusFilters = [];
    document.querySelectorAll('.fullscreen-status-chip').forEach(chip => {
        chip.classList.remove('active', 'bg-[#0088CC]', 'text-white', 'border-[#0088CC]');
        chip.classList.add('border-gray-200');
    });
    const allButton = document.querySelector('.fullscreen-status-chip[data-status=""]');
    if (allButton) {
        allButton.classList.add('active', 'bg-[#0088CC]', 'text-white', 'border-[#0088CC]');
        allButton.classList.remove('border-gray-200');
    }
    
    // Reset room filters
    document.querySelectorAll('.complex-room-chip').forEach(chip => {
        chip.classList.remove('active', 'bg-[#0088CC]', 'text-white');
    });
    document.querySelectorAll('.mobile-map-room-chip').forEach(chip => {
        chip.classList.remove('active', 'bg-[#0088CC]', 'text-white', 'border-[#0088CC]');
        chip.classList.add('border-gray-200');
    });
    
    // Reset developer checkboxes
    document.querySelectorAll('.complex-developer-filter').forEach(cb => cb.checked = false);
    
    // Reset class checkboxes
    document.querySelectorAll('.complex-class-filter').forEach(cb => cb.checked = false);
    
    // Reset price inputs
    const priceFromInputs = [document.getElementById('desktopComplexPriceFrom'), document.getElementById('complexPriceFrom')];
    const priceToInputs = [document.getElementById('desktopComplexPriceTo'), document.getElementById('complexPriceTo')];
    priceFromInputs.forEach(input => { if (input) input.value = ''; });
    priceToInputs.forEach(input => { if (input) input.value = ''; });
    
    // Apply filters (will show all)
    applyAllFiltersToMap();
}

// Make it globally available
window.resetAllMapFilters = resetAllMapFilters;

function toggleComplexMapRoomFilter(rooms, btn) {
    if (!btn) return;
    const isActive = btn.classList.contains('active');
    if (isActive) {
        btn.classList.remove('active', 'bg-[#0088CC]', 'text-white', 'border-[#0088CC]');
        btn.classList.add('border-gray-200');
    } else {
        btn.classList.add('active', 'bg-[#0088CC]', 'text-white', 'border-[#0088CC]');
        btn.classList.remove('border-gray-200');
    }

    const correspondingChip = document.querySelector(`.complex-room-chip[data-rooms="${rooms}"]`);
    if (correspondingChip) {
        if (isActive) {
            correspondingChip.classList.remove('active', 'bg-blue-600', 'text-white', 'border-blue-600');
            correspondingChip.classList.add('border-gray-300');
        } else {
            correspondingChip.classList.add('active', 'bg-blue-600', 'text-white', 'border-blue-600');
            correspondingChip.classList.remove('border-gray-300');
        }
    }

    applyAllFiltersToMap();
}
window.toggleComplexMapRoomFilter = toggleComplexMapRoomFilter;

// Apply all active filters and update map + sidebar
function applyAllFiltersToMap() {
    const filtered = filterComplexesByCurrentFilters();
    
    if (fullscreenComplexesMapInstance && window._complexesClusterer) {
        // Remove all from clusterer and re-add filtered
        window._complexesClusterer.removeAll();
        allComplexMarkers = [];
        
        const placemarks = [];
        filtered.forEach(complex => {
            if (!complex.coordinates) return;
            try {
                const placemark = createEnhancedComplexMarker([complex]);
                if (placemark) {
                    placemarks.push(placemark);
                    allComplexMarkers.push({ marker: placemark, complexes: [complex] });
                }
            } catch (err) {
                console.warn('marker error:', err);
            }
        });
        
        window._complexesClusterer.add(placemarks);
    }
    
    // Update sidebar
    updateSidebar(filtered);
    
    // Update counters
    document.querySelectorAll('.map-complexes-count').forEach(el => el.textContent = filtered.length);

    // Update filter button count and active filter pills
    updateComplexFilterButton(filtered.length);
    if (typeof updateComplexActiveFiltersDisplay === 'function') updateComplexActiveFiltersDisplay();
}

// Helper to filter complexes by all active filters
function filterComplexesByCurrentFilters() {
    const today = new Date('2026-02-04');
    const currentYear = today.getFullYear();
    const currentQuarter = Math.floor((today.getMonth() + 3) / 3);
    
    // Get room filters (from both desktop and mobile map chips)
    const activeRoomChips = document.querySelectorAll('.complex-room-chip.active, .mobile-map-room-chip.active');
    const activeRooms = [...new Set(Array.from(activeRoomChips).map(chip => chip.getAttribute('data-rooms')))];
    
    // Get developer filters
    const developers = Array.from(document.querySelectorAll('.complex-developer-filter:checked')).map(cb => parseInt(cb.value));
    
    // Get class filters
    const classes = Array.from(document.querySelectorAll('.complex-class-filter:checked')).map(cb => cb.value);
    
    // Get price filters
    const priceFrom = parseFloat(
        document.getElementById('desktopComplexPriceFrom')?.value || 
        document.getElementById('complexPriceFrom')?.value || ''
    ) || null;
    const priceTo = parseFloat(
        document.getElementById('desktopComplexPriceTo')?.value || 
        document.getElementById('complexPriceTo')?.value || ''
    ) || null;
    
    console.log('🏢 Filtering with:', { activeStatusFilters, activeRooms, developers, classes, priceFrom, priceTo });
    
    return allComplexesData.filter(c => {
        // Status filter (multiple can be selected)
        if (activeStatusFilters.length > 0) {
            const isDelivered = !c.completion_year || 
                               (c.completion_year < currentYear) || 
                               (c.completion_year === currentYear && (c.completion_quarter || 1) <= currentQuarter);
            
            let matchesStatus = false;
            for (const statusFilter of activeStatusFilters) {
                if (statusFilter.toLowerCase().includes('сдан') && isDelivered) {
                    matchesStatus = true;
                    break;
                }
                if (statusFilter.toLowerCase().includes('стро') && !isDelivered) {
                    matchesStatus = true;
                    break;
                }
            }
            if (!matchesStatus) return false;
        }
        
        // Class filter (multiple can be selected)
        if (classes.length > 0) {
            const complexClass = c.object_class || c.class || c.housing_class;
            if (!complexClass || !classes.includes(complexClass)) return false;
        }
        
        // Room filter
        if (activeRooms.length > 0) {
            if (c.room_details) {
                const hasMatchingRoom = activeRooms.some(roomFilter => {
                    let roomKey;
                    if (roomFilter === 'студия') {
                        roomKey = 'Студия';
                    } else if (roomFilter === '4+-комн') {
                        return Object.keys(c.room_details).some(key => {
                            const match = key.match(/^(\d+)-комн$/);
                            if (match && parseInt(match[1]) >= 4) {
                                return c.room_details[key] && c.room_details[key].count > 0;
                            }
                            return false;
                        });
                    } else {
                        roomKey = roomFilter;
                    }
                    return c.room_details[roomKey] && c.room_details[roomKey].count > 0;
                });
                if (!hasMatchingRoom) return false;
            } else {
                return false;
            }
        }
        
        // Developer filter
        if (developers.length > 0) {
            const devId = c.developer_id || c.developerId;
            if (!devId || !developers.includes(devId)) return false;
        }
        
        // Price filter
        if (priceFrom) {
            const price = c.price_from || c.min_price;
            if (!price || price < priceFrom * 1000000) return false;
        }
        if (priceTo) {
            const price = c.price_from || c.min_price;
            if (!price || price > priceTo * 1000000) return false;
        }
        
        return true;
    });
}

function updateSidebar(complexes) {
    const sidebarContent = document.getElementById('map-sidebar-content');
    if (!sidebarContent) return;
    
    sidebarContent.innerHTML = '';
    
    // Show empty state if no complexes
    if (!complexes || complexes.length === 0) {
        sidebarContent.innerHTML = `
            <div class="flex flex-col items-center justify-center py-16 px-6 text-center">
                <div class="w-20 h-20 mb-6 rounded-full bg-gradient-to-br from-blue-50 to-blue-100 flex items-center justify-center">
                    <svg class="w-10 h-10 text-[#0088CC]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M19 21V5a2 2 0 00-2-2H7a2 2 0 00-2 2v16m14 0h2m-2 0h-5m-9 0H3m2 0h5M9 7h1m-1 4h1m4-4h1m-1 4h1m-5 10v-5a1 1 0 011-1h2a1 1 0 011 1v5m-4 0h4"/>
                    </svg>
                </div>
                <h3 class="text-lg font-bold text-gray-800 mb-2">Объекты не найдены</h3>
                <p class="text-sm text-gray-500 mb-6 max-w-xs">По выбранным фильтрам нет жилых комплексов. Попробуйте изменить параметры поиска</p>
                <button onclick="resetAllMapFilters()" class="px-5 py-2.5 bg-[#0088CC] text-white text-sm font-semibold rounded-xl hover:bg-[#006699] transition-all shadow-md hover:shadow-lg">
                    <i class="fas fa-undo mr-2"></i>Сбросить фильтры
                </button>
            </div>
        `;
        return;
    }
    
    complexes.forEach((complex, index) => {
        const card = document.createElement('div');
        card.className = 'sidebar-complex-card cursor-pointer group';
        card.dataset.id = complex.id;
        
        const statusText = getStatusDisplayText(complex.status, complex.completion_year, complex.completion_quarter);
        const markerColor = getComplexMarkerColor(statusText);
        
        // Match properties card price logic
        const price = complex.price_from ? 
            `от ${Math.round(complex.price_from / 100000) / 10} млн ₽` : 
            'Цена по запросу';
        
        // Parse gallery images for slider
        let images = [complex.main_image || '/static/images/no-photo.svg'];
        if (complex.gallery_images) {
            try {
                let parsed = complex.gallery_images;
                if (typeof parsed === 'string') {
                    parsed = JSON.parse(parsed);
                }
                if (Array.isArray(parsed) && parsed.length > 0) {
                    images = parsed.slice(0, 5);
                }
            } catch(e) {}
        }
        
        // Carousel HTML - using same approach as properties.html
        const carouselId = `sidebar-carousel-${complex.id || index}`;
        
        // Build slides HTML - first slide visible, rest hidden
        // Route CIAN images through img-proxy only when proxy is enabled
        const _proxyImg = (u) => { if (!u) return '/static/images/no-photo.svg'; if (u.startsWith('/')) return u; return window.imageProxyEnabled ? `/api/img-proxy?url=${encodeURIComponent(u)}` : u; };
        let slidesHtml = '';
        images.forEach((img, i) => {
            const isFirst = i === 0;
            const proxied = _proxyImg(img);
            slidesHtml += `<div class="carousel-slide absolute inset-0 w-full h-full transition-opacity duration-300 ${isFirst ? 'opacity-100 z-10' : 'opacity-0 z-0'}" data-slide="${i}">
                <img src="${proxied}" referrerpolicy="no-referrer" class="w-full h-full object-cover bg-gray-200" alt="${complex.name}" loading="lazy" onerror="this.src='/static/images/no-photo.svg'">
            </div>`;
        });
        
        // Navigation arrows
        const sliderArrows = images.length > 1 ? `
            <button class="slider-prev-btn absolute left-2 top-1/2 -translate-y-1/2 w-8 h-8 bg-white/90 rounded-full flex items-center justify-center text-gray-700 hover:bg-white z-20 shadow-md transition-all" onclick="event.stopPropagation(); prevComplexSlide(this);">
                <i class="fas fa-chevron-left text-sm"></i>
            </button>
            <button class="slider-next-btn absolute right-2 top-1/2 -translate-y-1/2 w-8 h-8 bg-white/90 rounded-full flex items-center justify-center text-gray-700 hover:bg-white z-20 shadow-md transition-all" onclick="event.stopPropagation(); nextComplexSlide(this);">
                <i class="fas fa-chevron-right text-sm"></i>
            </button>` : '';
        
        // Dots
        const sliderDots = images.length > 1 ? `
            <div class="absolute bottom-2 left-1/2 -translate-x-1/2 flex gap-1.5 z-20">
                ${images.map((_, i) => `<button class="slider-dot-btn w-2 h-2 rounded-full ${i === 0 ? 'bg-white' : 'bg-white/50'} transition-all" data-slide="${i}" onclick="event.stopPropagation(); goToComplexSlide(this, ${i});"></button>`).join('')}
            </div>` : '';
        
        // Cashback badge
        const cashbackRate = complex.cashback_rate || 0;
        const cashbackBadge = cashbackRate > 0 ? `
            <div class="absolute top-2 right-2 px-2 py-1 rounded text-[10px] font-bold text-white bg-green-500 shadow-sm z-10">
                ${cashbackRate}% кешбек
            </div>` : '';
            
        card.innerHTML = `
            <div class="carousel-container relative w-full bg-gray-100 overflow-hidden rounded-t-lg" style="aspect-ratio: 4/3; min-height: 150px;" id="${carouselId}">
                ${slidesHtml}
                <div class="absolute top-2 left-2 px-2 py-1 rounded text-[10px] font-bold text-white shadow-sm z-10" style="background: ${markerColor}">
                    ${statusText}
                </div>
                ${cashbackBadge}
                ${sliderArrows}
                ${sliderDots}
            </div>
            <div class="p-3 flex-1 flex flex-col">
                <h4 class="font-bold text-sm text-gray-900 mb-0.5 group-hover:text-[#0088CC] transition-colors line-clamp-2 min-h-[40px]">${complex.name}</h4>
                <p class="text-sm font-bold text-[#0088CC] mb-2">${price}</p>
                
                <div class="space-y-1 mt-auto">
                    <div class="flex items-start text-[11px] text-gray-500">
                        <i class="fas fa-map-marker-alt mt-0.5 mr-1.5 w-3 text-gray-400"></i>
                        <span class="line-clamp-2">${complex.address || complex.district || 'Адрес не указан'}</span>
                    </div>
                    <div class="flex items-center text-[11px] text-gray-500">
                        <i class="fas fa-building mr-1.5 w-3 text-gray-400"></i>
                        <span class="truncate">${complex.developer_name || complex.developer || 'Застройщик не указан'}</span>
                    </div>
                </div>
                
                <button class="show-phone-btn w-full mt-3 py-2 bg-[#0088CC] text-white text-xs font-bold rounded-lg hover:bg-[#006699] transition-colors flex items-center justify-center gap-1" onclick="event.stopPropagation(); showSidebarPhone(this);">
                    <i class="fas fa-phone text-[10px]"></i>
                    <span class="phone-text">Показать телефон</span>
                </button>
            </div>
        `;
        
        // Navigate to complex detail page on card click
        card.onclick = () => {
            // Get city slug from current URL path (e.g., /sochi/residential-complexes -> sochi)
            const pathParts = window.location.pathname.split('/').filter(p => p);
            const citySlug = pathParts[0] || 'sochi';
            
            // Construct proper URL: /{city_slug}/zk/{slug}
            let complexUrl;
            if (complex.url && (complex.url.includes('/zk/') || complex.url.includes('/residential-complex/'))) {
                complexUrl = complex.url;
            } else if (complex.slug) {
                complexUrl = `/${citySlug}/zk/${complex.slug}`;
            } else {
                complexUrl = `/zk/${complex.id}`;
            }
            window.location.href = complexUrl;
        };
        
        // Card hover → lift corresponding map marker
        card.addEventListener('mouseenter', () => {
            card.style.boxShadow = '0 8px 24px rgba(0,136,204,0.18)';
            card.style.transform = 'translateY(-2px)';
            card.style.transition = 'box-shadow 0.18s ease, transform 0.18s ease';
            const markerEl = document.querySelector(`.ymap-complex-marker[data-complex-id="${complex.id}"]`);
            if (markerEl) {
                markerEl.style.transform = 'scale(1.18) translateY(-6px)';
                markerEl.style.filter = 'drop-shadow(0 6px 14px rgba(0,0,0,0.35))';
                markerEl.style.zIndex = '9999';
                markerEl.style.transition = 'transform 0.18s cubic-bezier(0.34,1.56,0.64,1), filter 0.18s ease';
            }
        });
        card.addEventListener('mouseleave', () => {
            card.style.boxShadow = '';
            card.style.transform = '';
            const markerEl = document.querySelector(`.ymap-complex-marker[data-complex-id="${complex.id}"]`);
            if (markerEl) {
                markerEl.style.transform = '';
                markerEl.style.filter = '';
                markerEl.style.zIndex = '';
            }
        });
        
        sidebarContent.appendChild(card);
    });
}

// Carousel slider functions for complex cards
function nextComplexSlide(button) {
    const carousel = button.closest('.carousel-container');
    if (!carousel) return;
    
    const slides = carousel.querySelectorAll('.carousel-slide');
    const dots = carousel.querySelectorAll('.slider-dot-btn');
    if (slides.length <= 1) return;
    
    let currentSlide = 0;
    slides.forEach((slide, index) => {
        if (slide.classList.contains('opacity-100')) {
            currentSlide = index;
        }
    });
    
    const nextIdx = (currentSlide + 1) % slides.length;
    
    // Hide current slide
    slides[currentSlide].classList.remove('opacity-100', 'z-10');
    slides[currentSlide].classList.add('opacity-0', 'z-0');
    // Show next slide
    slides[nextIdx].classList.remove('opacity-0', 'z-0');
    slides[nextIdx].classList.add('opacity-100', 'z-10');
    
    // Update dots
    if (dots.length > 0) {
        dots[currentSlide].classList.remove('bg-white');
        dots[currentSlide].classList.add('bg-white/50');
        dots[nextIdx].classList.remove('bg-white/50');
        dots[nextIdx].classList.add('bg-white');
    }
}

function prevComplexSlide(button) {
    const carousel = button.closest('.carousel-container');
    if (!carousel) return;
    
    const slides = carousel.querySelectorAll('.carousel-slide');
    const dots = carousel.querySelectorAll('.slider-dot-btn');
    if (slides.length <= 1) return;
    
    let currentSlide = 0;
    slides.forEach((slide, index) => {
        if (slide.classList.contains('opacity-100')) {
            currentSlide = index;
        }
    });
    
    const prevIdx = currentSlide === 0 ? slides.length - 1 : currentSlide - 1;
    
    // Hide current slide
    slides[currentSlide].classList.remove('opacity-100', 'z-10');
    slides[currentSlide].classList.add('opacity-0', 'z-0');
    // Show previous slide
    slides[prevIdx].classList.remove('opacity-0', 'z-0');
    slides[prevIdx].classList.add('opacity-100', 'z-10');
    
    // Update dots
    if (dots.length > 0) {
        dots[currentSlide].classList.remove('bg-white');
        dots[currentSlide].classList.add('bg-white/50');
        dots[prevIdx].classList.remove('bg-white/50');
        dots[prevIdx].classList.add('bg-white');
    }
}

function goToComplexSlide(button, slideIndex) {
    const carousel = button.closest('.carousel-container');
    if (!carousel) return;
    
    const slides = carousel.querySelectorAll('.carousel-slide');
    const dots = carousel.querySelectorAll('.slider-dot-btn');
    
    slides.forEach((slide, index) => {
        if (index === slideIndex) {
            slide.classList.remove('opacity-0', 'z-0');
            slide.classList.add('opacity-100', 'z-10');
        } else {
            slide.classList.remove('opacity-100', 'z-10');
            slide.classList.add('opacity-0', 'z-0');
        }
    });
    
    dots.forEach((dot, index) => {
        if (index === slideIndex) {
            dot.classList.remove('bg-white/50');
            dot.classList.add('bg-white');
        } else {
            dot.classList.remove('bg-white');
            dot.classList.add('bg-white/50');
        }
    });
}

// Show phone button handler
function showSidebarPhone(button) {
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
        window.location.href = 'tel:+78622666216';
    }
}

// Make functions globally available
window.nextComplexSlide = nextComplexSlide;
window.prevComplexSlide = prevComplexSlide;
window.goToComplexSlide = goToComplexSlide;
window.showSidebarPhone = showSidebarPhone;


// Update map markers based on filtered data
function updateMapMarkers(filteredComplexes) {
    if (!fullscreenComplexesMapInstance) return;
    console.log('🔄 Updating map with', filteredComplexes.length, 'complexes');
    
    if (window._complexesClusterer) {
        window._complexesClusterer.removeAll();
        allComplexMarkers = [];
        const placemarks = [];
        filteredComplexes.forEach(complex => {
            if (!complex.coordinates) return;
            try {
                const placemark = createEnhancedComplexMarker([complex]);
                if (placemark) {
                    placemarks.push(placemark);
                    allComplexMarkers.push({ marker: placemark, complexes: [complex] });
                }
            } catch(e) {}
        });
        window._complexesClusterer.add(placemarks);
        console.log('✅ Clusterer updated:', placemarks.length, 'markers');
    }
}

// Create enhanced Yandex Maps marker for complexes
function createEnhancedComplexMarker(complexes) {
    const count = complexes.length;
    const coords = [complexes[0].coordinates.lat, complexes[0].coordinates.lng];
    
    // Determine marker color based on first complex's status
    const markerColor = getComplexMarkerColor(complexes[0].status);
    
    // Get price info (API returns price_from, not min_price)
    const minPrice = Math.min(...complexes.map(c => c.price_from || c.min_price || Infinity).filter(p => p !== Infinity && p > 0));
    const priceText = minPrice !== Infinity ? (minPrice >= 1000000 ? Math.round(minPrice / 1000000 * 10) / 10 + 'М' : Math.round(minPrice / 1000) + 'К') : null;
    
    const complexDisplayName = complexes[0].name || 'ЖК';
    const shortName = complexDisplayName.length > 20 ? complexDisplayName.substring(0, 18) + '...' : complexDisplayName;
    
    const priceLabel = priceText ? `от ${priceText}` : 'по запросу';
    const iconLayout = ymaps.templateLayoutFactory.createClass(
        '<div class="ymap-complex-marker" data-complex-id="$[properties.complexId]" style="position: relative; cursor: pointer; pointer-events: all; display: flex; justify-content: center; transition: transform 0.18s ease, filter 0.18s ease;">' +
            '<div class="marker-inner" style="background: $[properties.markerColor]; color: white; padding: 4px 8px; border-radius: 14px; box-shadow: 0 2px 8px rgba(0,0,0,0.25); border: 2px solid white; font-size: 10px; font-weight: 700; white-space: nowrap; font-family: Inter, system-ui, sans-serif; display: flex; flex-direction: column; align-items: center; gap: 1px; cursor: pointer; pointer-events: all; line-height: 1.2; max-width: 160px;">' +
                '<span style="font-size: 9px; opacity: 0.95; overflow: hidden; text-overflow: ellipsis; max-width: 140px;">$[properties.shortName]</span>' +
                '<span style="font-size: 11px;">$[properties.priceLabel]</span>' +
            '</div>' +
            '<div style="width: 0; height: 0; border-left: 6px solid transparent; border-right: 6px solid transparent; border-top: 8px solid $[properties.markerColor]; position: absolute; bottom: -7px; left: 50%; transform: translateX(-50%);"></div>' +
        '</div>'
    );
    
    const apartmentCount = complexes.reduce((s, c) => s + (c.available_apartments || 0), 0);
    const aptLabel = apartmentCount > 0 ? `${apartmentCount} кв.` : 'квартиры уточняйте';
    const placemark = new ymaps.Placemark(coords, {
        complexes: complexes,
        complexId: complexes[0].id,
        complexName: complexes[0].name,
        shortName: shortName,
        priceText: priceText,
        priceLabel: priceLabel,
        apartmentCount: aptLabel,
        markerColor: markerColor,
        hintContent: `${count} ${count === 1 ? 'жилой комплекс' : 'жилых комплекса'}: ${complexes[0].name}`
    }, {
        iconLayout: iconLayout,
        balloonShadow: false,
        balloonLayout: ymaps.templateLayoutFactory.createClass(
            '<div class="sidebar-complex-card w-72 shadow-2xl border-0 overflow-hidden bg-white rounded-xl cursor-pointer hover:shadow-3xl transition-shadow" onclick="window.location.href=\'$[properties.complexUrl]\'">' +
                '<div class="relative aspect-[4/3]">' +
                    '<img src="$[properties.image]" class="w-full h-full object-cover">' +
                    '<div class="absolute top-2 left-2 px-2 py-1 rounded text-[10px] font-bold text-white shadow-sm z-10" style="background: $[properties.markerColor]">$[properties.statusText]</div>' +
                    '$[properties.cashbackBadge]' +
                '</div>' +
                '<div class="p-3">' +
                    '<h4 class="font-bold text-gray-900 text-sm mb-1 leading-tight hover:text-[#0088CC] transition-colors">$[properties.complexName]</h4>' +
                    '<div class="flex items-start text-[11px] text-gray-500 mb-1">' +
                        '<i class="fas fa-map-marker-alt mt-0.5 mr-1.5 w-3 text-gray-400"></i>' +
                        '<span class="line-clamp-1">$[properties.address]</span>' +
                    '</div>' +
                    '<div class="flex items-center justify-between">' +
                        '<p class="text-[11px] font-bold text-[#0088CC]">$[properties.priceDisplay]</p>' +
                        '<span class="text-[10px] text-gray-500 bg-gray-100 rounded px-1.5 py-0.5">$[properties.apartmentCount]</span>' +
                    '</div>' +
                '</div>' +
                '<div class="close-btn absolute top-1 right-1 bg-white/80 rounded-full p-1.5 cursor-pointer hover:bg-white transition-colors z-20" onclick="event.stopPropagation(); fullscreenComplexesMapInstance.balloon.close()">' +
                    '<svg class="w-4 h-4 text-gray-600" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path></svg>' +
                '</div>' +
            '</div>'
        ),
        balloonPanelMaxMapArea: 0,
        hideIconOnBalloonOpen: false,
        iconShape: {
            type: 'Rectangle',
            coordinates: [[-80, -40], [80, 15]]
        },
        iconImageOffset: [-70, -35],
        cursor: 'pointer'
    });

    // Build complex URL
    const pathParts = window.location.pathname.split('/').filter(p => p);
    const citySlug = pathParts[0] || 'sochi';
    let complexUrl = complexes[0].url || (complexes[0].slug ? `/${citySlug}/zk/${complexes[0].slug}` : `/zk/${complexes[0].id}`);
    
    // Cashback badge
    const cashbackRate = complexes[0].cashback_rate || 0;
    const cashbackBadge = cashbackRate > 0 ? 
        `<div class="absolute top-2 right-2 px-2 py-1 rounded text-[10px] font-bold text-white bg-green-500 shadow-sm z-10">${cashbackRate}% кешбек</div>` : '';
    
    // Set properties for balloon
    const _proxyBalloonImg = (u) => { if (!u) return '/static/images/no-photo.svg'; if (u.startsWith('/')) return u; return window.imageProxyEnabled ? `/api/img-proxy?url=${encodeURIComponent(u)}` : u; };
    placemark.properties.set({
        image: _proxyBalloonImg(complexes[0].main_image),
        statusText: getStatusDisplayText(complexes[0].status),
        address: complexes[0].address || complexes[0].district || 'Адрес не указан',
        priceDisplay: complexes[0].price_from ? ('от ' + Math.round(complexes[0].price_from / 1000000 * 10) / 10 + ' млн ₽') : 'цена по запросу',
        complexUrl: complexUrl,
        cashbackBadge: cashbackBadge,
        apartmentCount: aptLabel
    });
    
    // Per-marker click debounce — prevents rapid clicks from triggering blue-screen
    let _complexLastClick = 0;

    // Bind click event - mobile shows bottom sheet, desktop toggles balloon
    placemark.events.add('click', function(e) {
        const now = Date.now();
        if (now - _complexLastClick < 400) return; // ignore rapid double-clicks
        _complexLastClick = now;

        e.stopPropagation();
        e.preventDefault();
        try {
            // Pan/zoom only if not already at target to avoid conflicting animations
            if (fullscreenComplexesMapInstance) {
                const currentZoom = fullscreenComplexesMapInstance.getZoom();
                const targetZoom = Math.max(currentZoom, 14);
                const currentCenter = fullscreenComplexesMapInstance.getCenter();
                const dist = Math.abs(currentCenter[0] - coords[0]) + Math.abs(currentCenter[1] - coords[1]);
                if (dist > 0.0001 || currentZoom < targetZoom) {
                    fullscreenComplexesMapInstance.setCenter(coords, targetZoom, { duration: 300, checkZoomRange: true });
                }
            }
            if (isMobileDevice()) {
                // Mobile: show bottom sheet with complex info (no balloon)
                openComplexBottomSheet(complexes);
                // Ensure balloon stays closed on mobile
                const target = e.get('target');
                if (target && target.balloon && target.balloon.isOpen()) {
                    target.balloon.close();
                }
            } else {
                // Desktop: toggle balloon
                const target = e.get('target');
                if (target && target.balloon) {
                    if (target.balloon.isOpen()) {
                        target.balloon.close();
                    } else {
                        target.balloon.open();
                    }
                }
                highlightSidebarCard(complexes[0].id);
            }
        } catch (err) {
            console.warn('Marker click error:', err);
        }
    });
    
    // Disable balloon auto-open on mobile
    if (isMobileDevice()) {
        placemark.options.set('openBalloonOnClick', false);
    }

    // ── Hover popup card (desktop only, CIAN-style) ──────────────────
    if (!isMobileDevice()) {
        const _complex = complexes[0];
        // Resolve best photo: main_image → first gallery image → placeholder
        const _galleryArr = (() => {
            try { return JSON.parse(_complex.gallery_images || '[]'); } catch(e) { return []; }
        })();
        const _img = _complex.main_image || _galleryArr[0] || '/static/images/no-photo.svg';
        const _price = _complex.price_from
            ? 'от ' + (Math.round(_complex.price_from / 100000) / 10).toFixed(1) + ' млн ₽'
            : 'По запросу';
        const _addr = _complex.district
            ? (_complex.district + (_complex.address ? ', ' + _complex.address : ''))
            : (_complex.address || '');
        const _date = _complex.completion_date || '';
        const _cb = _complex.cashback_rate || 0;
        const _apt = aptLabel;
        const _status = getStatusDisplayText(_complex.status);
        const _statusColor = getComplexMarkerColor(_complex.status);

        placemark.events.add('mouseenter', function(e) {
            clearTimeout(window._complexHoverTimer);

            let tip = document.getElementById('ymap-complex-hover-tip');
            if (!tip) {
                tip = document.createElement('div');
                tip.id = 'ymap-complex-hover-tip';
                tip.style.cssText = 'position:fixed;z-index:99999;pointer-events:auto;transition:opacity 0.18s ease;display:none;opacity:0;';
                tip.addEventListener('mouseenter', () => clearTimeout(window._complexHoverTimer));
                tip.addEventListener('mouseleave', () => {
                    window._complexHoverTimer = setTimeout(() => {
                        const t = document.getElementById('ymap-complex-hover-tip');
                        if (t) { t.style.opacity = '0'; setTimeout(() => { if (t.style.opacity === '0') t.style.display = 'none'; }, 200); }
                    }, 200);
                });
                document.body.appendChild(tip);
            }

            const proxyImg = (u) => { if (!u) return '/static/images/no-photo.svg'; if (u.startsWith('/')) return u; return window.imageProxyEnabled ? `/api/img-proxy?url=${encodeURIComponent(u)}` : u; };

            tip.innerHTML = `
                <div style="width:272px;background:#fff;border-radius:12px;box-shadow:0 8px 32px rgba(0,0,0,0.18),0 2px 8px rgba(0,0,0,0.08);overflow:hidden;font-family:Inter,system-ui,sans-serif;border:1px solid rgba(0,0,0,0.06);">
                    <div style="position:relative;height:148px;overflow:hidden;background:#f3f4f6;">
                        <img src="${proxyImg(_img)}" style="width:100%;height:100%;object-fit:cover;" onerror="this.src='/static/images/no-photo.svg'">
                        <div style="position:absolute;inset:0;background:linear-gradient(to top,rgba(0,0,0,0.38) 0%,transparent 55%);"></div>
                        <div style="position:absolute;top:8px;left:8px;background:${_statusColor};color:#fff;padding:2px 8px;border-radius:4px;font-size:10px;font-weight:600;letter-spacing:0.3px;">${_status}</div>
                        ${_cb > 0 ? `<div style="position:absolute;top:8px;right:8px;background:#16a34a;color:#fff;padding:2px 8px;border-radius:4px;font-size:10px;font-weight:600;">Кешбек ${_cb}%</div>` : ''}
                        ${_date ? `<div style="position:absolute;bottom:8px;left:8px;color:rgba(255,255,255,0.92);font-size:10px;font-weight:500;">Сдача: ${_date}</div>` : ''}
                    </div>
                    <div style="padding:12px 14px 14px;">
                        <div style="font-size:13px;font-weight:700;color:#111827;margin-bottom:2px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;line-height:1.3;">${_complex.name}</div>
                        <div style="font-size:17px;font-weight:800;color:#0088CC;margin-bottom:8px;line-height:1.2;">${_price}</div>
                        ${_addr ? `<div style="font-size:11px;color:#6b7280;margin-bottom:3px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">${_addr}</div>` : ''}
                        <div style="font-size:11px;color:#9ca3af;margin-bottom:12px;">${_apt}</div>
                        <div style="display:flex;gap:7px;">
                            <a href="tel:+78622666216" style="flex:1;background:#f3f4f6;color:#374151;text-align:center;padding:7px 4px;border-radius:7px;font-size:11px;font-weight:600;text-decoration:none;letter-spacing:0.1px;" onclick="event.stopPropagation();">Позвонить</a>
                            <a href="${complexUrl}" style="flex:2;background:#0088CC;color:#fff;text-align:center;padding:7px 8px;border-radius:7px;font-size:11px;font-weight:600;text-decoration:none;letter-spacing:0.1px;">Подробнее</a>
                        </div>
                    </div>
                </div>`;

            const domEvt = e.get('domEvent') && e.get('domEvent').originalEvent
                ? e.get('domEvent').originalEvent
                : (window._lastMouseEvt || null);
            if (domEvt) {
                const x = domEvt.clientX, y = domEvt.clientY;
                const tipW = 272, tipH = 320;
                const margin = 12;
                const left = (x + margin + tipW > window.innerWidth) ? x - tipW - margin : x + margin;
                const top  = (y - 16 + tipH > window.innerHeight) ? y - tipH + 16 : y - 16;
                tip.style.left = left + 'px';
                tip.style.top  = top + 'px';
            }
            tip.style.display = 'block';
            requestAnimationFrame(() => { tip.style.opacity = '1'; });
        });

        placemark.events.add('mouseleave', function() {
            clearTimeout(window._complexHoverTimer);
            window._complexHoverTimer = setTimeout(() => {
                const tip = document.getElementById('ymap-complex-hover-tip');
                if (tip) {
                    tip.style.opacity = '0';
                    setTimeout(() => { if (tip.style.opacity === '0') tip.style.display = 'none'; }, 200);
                }
            }, 350);
        });
    }
    
    return placemark;
}

function highlightSidebarCard(id) {
    const card = document.querySelector(`.sidebar-complex-card[data-id="${id}"]`);
    if (card) {
        card.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        card.classList.add('ring-2', 'ring-[#0088CC]', 'scale-[1.02]');
        setTimeout(() => card.classList.remove('ring-2', 'ring-[#0088CC]', 'scale-[1.02]'), 2000);
    }
}

// Show complex bottom sheet with cards
function showComplexBottomSheet(complexes) {
    const bottomSheet = document.getElementById('complexBottomSheet');
    const backdrop = document.getElementById('complexBottomSheetBackdrop');
    const container = document.getElementById('bottomSheetComplexesContainer');
    
    if (!bottomSheet || !backdrop || !container) {
        console.warn('🏢 Bottom sheet elements not found');
        console.warn('bottomSheet:', !!bottomSheet, 'backdrop:', !!backdrop, 'container:', !!container);
        return;
    }
    
    console.log(`🏢 Opening bottom sheet with ${complexes.length} complexes`);
    
    // Clear previous content
    container.innerHTML = '';
    
    // Create complex cards
    complexes.forEach((complex, index) => {
        const card = createComplexCard(complex, index);
        container.appendChild(card);
    });
    
    // Show bottom sheet with animation
    backdrop.classList.remove('hidden');
    bottomSheet.classList.remove('hidden');
    
    // Trigger animation by removing translate-y-full
    setTimeout(() => {
        backdrop.style.opacity = '1';
        bottomSheet.style.transform = 'translateY(0)';
    }, 10);
}

// Close complex bottom sheet
// Open complex bottom sheet (Mobile - when marker is clicked)
function openComplexBottomSheet(complexes) {
    const bottomSheet = document.getElementById('complexBottomSheet');
    const backdrop = document.getElementById('complexBottomSheetBackdrop');
    const container = document.getElementById('bottomSheetComplexesContainer');
    const title = document.getElementById('complexBottomSheetTitle');
    
    if (!bottomSheet || !backdrop || !container) {
        console.warn('⚠️ Complex bottom sheet elements not found');
        return;
    }
    
    console.log(`🏢 Opening complex bottom sheet with ${complexes.length} complexes`);
    
    // Set title based on count
    if (title) {
        title.textContent = complexes.length === 1 ? complexes[0].name : `${complexes.length} ЖК на этой локации`;
    }
    
    // Clear existing content
    container.innerHTML = '';
    
    // Add complex cards
    complexes.forEach((complex, index) => {
        const card = createComplexCard(complex, index);
        container.appendChild(card);
    });
    
    // Show bottom sheet with animation
    backdrop.classList.remove('hidden');
    bottomSheet.classList.remove('hidden');
    
    requestAnimationFrame(() => {
        backdrop.style.opacity = '1';
        bottomSheet.style.transform = 'translateY(0)';
    });
}

function closeComplexBottomSheet() {
    const bottomSheet = document.getElementById('complexBottomSheet');
    const backdrop = document.getElementById('complexBottomSheetBackdrop');
    
    if (!bottomSheet || !backdrop) return;
    
    console.log('🏢 Closing complex bottom sheet');
    
    // Trigger close animation
    backdrop.style.opacity = '0';
    bottomSheet.style.transform = 'translateY(100%)';
    
    // Hide elements after animation completes
    setTimeout(() => {
        backdrop.classList.add('hidden');
        bottomSheet.classList.add('hidden');
    }, 300);
}

// Create complex card for bottom sheet
function createComplexCard(complex, index) {
    const card = document.createElement('div');
    card.className = 'bottom-sheet-complex-card';
    card.style.cssText = 'background:#fff;border-radius:10px;border:1px solid #f0f0f0;overflow:hidden;';
    
    const name = complex.name || 'Жилой комплекс';
    const developer = complex.developer_name || complex.developer || 'Не указан';
    const address = complex.address || complex.district || '';
    const status = getStatusDisplayText(complex.status);
    const statusColor = getComplexMarkerColor(complex.status);
    const mainImage = complex.main_image || complex.image || '/static/images/no-photo.svg';
    
    // Parse gallery images
    let images = [mainImage];
    if (complex.gallery_images) {
        try {
            let parsed = complex.gallery_images;
            if (typeof parsed === 'string') {
                parsed = JSON.parse(parsed);
            }
            if (Array.isArray(parsed) && parsed.length > 0) {
                images = parsed.slice(0, 5);
            }
        } catch(e) {}
    }
    
    // Get city slug from current URL path
    const pathParts = window.location.pathname.split('/').filter(p => p);
    const citySlug = pathParts[0] || 'sochi';
    const complexUrl = complex.url || (complex.slug ? `/${citySlug}/zk/${complex.slug}` : `/zk/${complex.id}`);
    
    // Price range
    let priceRange = 'По запросу';
    const minPrice = complex.price_from || complex.min_price;
    const maxPrice = complex.price_to || complex.max_price;
    
    if (minPrice && maxPrice && minPrice !== maxPrice) {
        const minPriceFormatted = Math.round(minPrice / 1000000 * 10) / 10;
        const maxPriceFormatted = Math.round(maxPrice / 1000000 * 10) / 10;
        priceRange = `${minPriceFormatted} - ${maxPriceFormatted} млн ₽`;
    } else if (minPrice) {
        const minPriceFormatted = Math.round(minPrice / 1000000 * 10) / 10;
        priceRange = `от ${minPriceFormatted} млн ₽`;
    }
    
    // Cashback badge
    const cashbackRate = complex.cashback_rate || 0;
    const cashbackBadge = cashbackRate > 0 ? `
        <div class="absolute top-1 right-1 px-2 py-0.5 rounded text-xs font-bold shadow bg-green-500 text-white">
            ${cashbackRate}%
        </div>` : '';
    
    // Apartments count
    const apartmentsCount = complex.available_apartments || complex.available_apartments_count || complex.total_apartments || 0;
    const apartmentsText = apartmentsCount > 0 ? `${apartmentsCount} квартир` : '';
    
    // Create slider HTML
    const sliderId = `complex-slider-${complex.id || index}`;
    const sliderDotsHtml = images.length > 1 ? `
        <div class="absolute bottom-1 left-1/2 transform -translate-x-1/2 flex gap-1">
            ${images.map((_, i) => `<span class="slider-dot w-1.5 h-1.5 rounded-full ${i === 0 ? 'bg-white' : 'bg-white/50'}" data-index="${i}"></span>`).join('')}
        </div>` : '';
    
    const sliderArrows = images.length > 1 ? `
        <button class="slider-arrow slider-prev absolute left-0.5 top-1/2 -translate-y-1/2 w-5 h-5 bg-white/80 rounded-full flex items-center justify-center text-gray-600 hover:bg-white" onclick="event.preventDefault(); slideComplexImage('${sliderId}', -1);">
            <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 19l-7-7 7-7"/></svg>
        </button>
        <button class="slider-arrow slider-next absolute right-0.5 top-1/2 -translate-y-1/2 w-5 h-5 bg-white/80 rounded-full flex items-center justify-center text-gray-600 hover:bg-white" onclick="event.preventDefault(); slideComplexImage('${sliderId}', 1);">
            <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7"/></svg>
        </button>` : '';
    
    card.innerHTML = `
        <a href="${complexUrl}" style="display:flex;gap:0;text-decoration:none;color:inherit;align-items:stretch;">
            <div style="width:90px;height:90px;flex-shrink:0;overflow:hidden;position:relative;" id="${sliderId}" data-current="0" data-images='${JSON.stringify(images)}'>
                <img src="${images[0]}" referrerpolicy="no-referrer" alt="${name}" style="width:100%;height:100%;object-fit:cover;" class="slider-image" onerror="this.src='/static/images/no-photo.svg'">
                <div style="position:absolute;top:4px;left:4px;padding:1px 6px;border-radius:4px;font-size:10px;font-weight:700;color:white;background:${statusColor};">
                    ${status}
                </div>
                ${cashbackRate > 0 ? `<div style="position:absolute;bottom:4px;left:4px;padding:1px 5px;border-radius:4px;font-size:10px;font-weight:700;color:white;background:#16a34a;">${cashbackRate}%</div>` : ''}
                ${images.length > 1 ? sliderArrows : ''}
            </div>
            <div style="flex:1;padding:8px 10px;display:flex;flex-direction:column;justify-content:center;min-width:0;gap:2px;">
                <div style="font-size:13px;font-weight:700;color:#111827;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">${name}</div>
                <div style="font-size:12px;font-weight:600;color:#0088CC;">${priceRange}</div>
                ${address ? `<div style="font-size:11px;color:#9ca3af;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">${address}</div>` : ''}
                ${apartmentsText ? `<div style="font-size:11px;color:#6b7280;">${apartmentsText}</div>` : ''}
            </div>
        </a>
    `;
    
    return card;
}

// Slider function for complex cards
function slideComplexImage(sliderId, direction) {
    const slider = document.getElementById(sliderId);
    if (!slider) return;
    
    const images = JSON.parse(slider.dataset.images || '[]');
    if (images.length <= 1) return;
    
    let current = parseInt(slider.dataset.current || 0);
    current = (current + direction + images.length) % images.length;
    slider.dataset.current = current;
    
    const img = slider.querySelector('.slider-image');
    if (img) {
        img.src = images[current];
    }
    
    // Update dots
    slider.querySelectorAll('.slider-dot').forEach((dot, i) => {
        dot.className = `slider-dot w-1.5 h-1.5 rounded-full ${i === current ? 'bg-white' : 'bg-white/50'}`;
    });
}

window.slideComplexImage = slideComplexImage;

// Initialize fullscreen complexes map
function initFullscreenComplexesMap() {
    const modal = document.getElementById('fullscreenComplexesMapModal');
    const mapContainer = document.getElementById('fullscreenComplexesMap');
    const sidebarContent = document.getElementById('map-sidebar-content');
    
    // Bail out if modal is closed or map already exists
    if (!modal || modal.classList.contains('hidden') || !mapContainer || fullscreenComplexesMapInstance) {
        console.log('🏢 Skipping map init - modal closed or map exists');
        return;
    }
    
    if (typeof ymaps === 'undefined') {
        console.warn('🏢 ymaps not loaded yet, retrying in 500ms');
        ymapsRetryTimeout = setTimeout(initFullscreenComplexesMap, 500);
        return;
    }
    
    ymaps.ready(function() {
        try {
            console.log('🏢 Initializing fullscreen Yandex Map for complexes');
            
            // Create map with controls (use correct ID!)
            const _initLat = window.currentCityLat || 45.0355;
            const _initLng = window.currentCityLng || 38.9753;
            const _initZoom = window.currentCityZoom || 11;
            fullscreenComplexesMapInstance = new ymaps.Map('fullscreenComplexesMap', {
                center: [_initLat, _initLng],
                zoom: _initZoom,
                controls: ['zoomControl', 'geolocationControl']
            });
            
            // Load complexes for ALL cities so user can pan to other cities (e.g. Sochi)
            fetch('/api/residential-complexes-map?city_id=' + (window.currentCityId || ''))
                .then(response => response.json())
                .then(data => {
                    if (!data || !data.complexes || data.complexes.length === 0) {
                        console.warn('🏢 No complexes loaded');
                        return;
                    }
                    
                    const allComplexes = data.complexes;
                    console.log(`🏢 Loaded ${allComplexes.length} complexes`);
                    
                    // Populate sidebar using shared updateSidebar function with carousels
                    updateSidebar(allComplexes);
                    
                    // Update counters (full list count in sidebar)
                    document.querySelectorAll('.map-complexes-count').forEach(el => el.textContent = allComplexes.length);
                    updateComplexFilterButton(allComplexes.length);
                    
                    // Only put complexes with real apartments on the map (no "от ?" markers).
                    // Persist this filter as the source of truth for subsequent filter/rebuild flows.
                    const mapComplexes = allComplexes.filter(c =>
                        c.coordinates && c.coordinates.lat && c.coordinates.lng &&
                        ((c.available_apartments || 0) > 0 || (c.price_from || 0) > 0)
                    );
                    // Store map-eligible complexes globally so filter/reset flows don't reintroduce empty ones
                    allComplexesData = mapComplexes;
                    console.log(`🏢 ${mapComplexes.length}/${allComplexes.length} complexes have apartments → shown on map`);
                    
                    // Создаём кластеризатор с кастомными иконками
                    const clusterLayout = ymaps.templateLayoutFactory.createClass(
                        '<div style="background:#0088CC;color:#fff;border-radius:50%;' +
                        'width:44px;height:44px;display:flex;align-items:center;justify-content:center;' +
                        'font-weight:800;font-size:14px;box-shadow:0 3px 10px rgba(0,136,204,0.55);' +
                        'border:3px solid #fff;cursor:pointer;">{{ properties.geoObjects.length }}</div>'
                    );
                    
                    window._complexesClusterer = new ymaps.Clusterer({
                        clusterIconLayout: clusterLayout,
                        clusterIconShape: { type: 'Circle', coordinates: [22, 22], radius: 22 },
                        gridSize: 80,
                        minClusterSize: 2,
                        groupByCoordinates: false,
                        clusterDisableClickZoom: true,
                        hasBalloon: false,
                        clusterOpenBalloonOnClick: false
                    });

                    // Explicit cluster click → zoom in (clusterDisableClickZoom: true lets us handle it ourselves)
                    window._complexesClusterer.events.add('click', function(e) {
                        try {
                            const target = e.get('target');
                            const coords = target.geometry.getCoordinates();
                            const currentZoom = fullscreenComplexesMapInstance.getZoom();
                            fullscreenComplexesMapInstance.setCenter(coords, currentZoom + 2, { duration: 400, checkZoomRange: true });
                        } catch (err) {
                            console.warn('Cluster click zoom error:', err);
                        }
                    });
                    
                    // Clear previous markers
                    allComplexMarkers = [];
                    
                    // Create individual markers (Clusterer handles grouping by zoom)
                    const placemarks = [];
                    mapComplexes.forEach(complex => {
                        try {
                            const placemark = createEnhancedComplexMarker([complex]);
                            if (placemark) {
                                placemarks.push(placemark);
                                allComplexMarkers.push({ marker: placemark, complexes: [complex] });
                            }
                        } catch (error) {
                            console.error('🏢 Error creating marker:', error, complex);
                        }
                    });
                    
                    window._complexesClusterer.add(placemarks);
                    fullscreenComplexesMapInstance.geoObjects.add(window._complexesClusterer);
                    
                    console.log(`🏢 Created ${placemarks.length} markers in clusterer`);
                    
                    // Center on current city (not fitBounds over all cities — would zoom out too far)
                    const cityLat = window.currentCityLat || 45.0355;
                    const cityLng = window.currentCityLng || 38.9753;
                    fullscreenComplexesMapInstance.setCenter([cityLat, cityLng], 11, { checkZoomRange: true });
                    console.log(`🏢 Map centered on city [${cityLat}, ${cityLng}], total ${allComplexes.length} complexes loaded`);
                    
                    // Add boundschange event listener to filter sidebar by visible area (with debouncing)
                    let boundsChangeTimeout = null;
                    fullscreenComplexesMapInstance.events.add('boundschange', function() {
                        // Debounce to prevent too many calls during panning/zooming
                        if (boundsChangeTimeout) clearTimeout(boundsChangeTimeout);
                        boundsChangeTimeout = setTimeout(() => {
                            filterSidebarByBounds();
                        }, 300);
                    });
                    console.log('🏢 Added boundschange event listener');
                })
                .catch(error => {
                    console.error('🏢 Error loading complexes for fullscreen map:', error);
                });
            
            console.log('🏢 Fullscreen Yandex Map initialized for complexes');
        } catch (error) {
            console.error('🏢 Error initializing fullscreen complexes map:', error);
        }
    });
}

// Return to list view
function returnToComplexesList() {
    console.log('🏢 Returning to complexes list');
    closeFullscreenComplexesMap();
    // Optionally redirect to list page
    // window.location.href = '/residential-complexes';
}

// ESC key handler for modal
function handleComplexMapEscKey(event) {
    if (event.key === 'Escape' || event.keyCode === 27) {
        const modal = document.getElementById('fullscreenComplexesMapModal');
        if (modal && !modal.classList.contains('hidden')) {
            closeFullscreenComplexesMap();
        }
    }
}

// Add ESC key listener
document.addEventListener('keydown', handleComplexMapEscKey);

// Initialize filter chip handlers when DOM is ready
document.addEventListener('DOMContentLoaded', function() {
    console.log('🏢 Initializing fullscreen complex map filter handlers');
    
    // Handle status filter chips
    const filterChips = document.querySelectorAll('.fullscreen-status-chip');
    filterChips.forEach(chip => {
        chip.addEventListener('click', function(e) {
            e.stopPropagation();
            const status = this.getAttribute('data-status');
            toggleStatusFilter(this, status);
        });
    });
    
    // Handle room filter chips
    const roomChips = document.querySelectorAll('.complex-room-chip');
    roomChips.forEach(chip => {
        chip.addEventListener('click', function(e) {
            e.stopPropagation();
            toggleRoomChip(this);
        });
    });
    
    // Debounce timer for input fields
    let filterCountDebounce = null;
    
    // Handle price and year input fields
    const priceFromInput = document.getElementById('complexPriceFrom');
    const priceToInput = document.getElementById('complexPriceTo');
    const yearFromInput = document.getElementById('complexYearFrom');
    const yearToInput = document.getElementById('complexYearTo');
    
    [priceFromInput, priceToInput, yearFromInput, yearToInput].forEach(input => {
        if (input) {
            input.addEventListener('input', function() {
                // Clear previous timeout
                if (filterCountDebounce) {
                    clearTimeout(filterCountDebounce);
                }
                
                // Update count after 500ms of no typing
                filterCountDebounce = setTimeout(() => {
                    updateComplexFilterCount();
                }, 500);
            });
        }
    });
});

// Toggle status filter
function toggleStatusFilter(chipElement, status) {
    const isActive = chipElement.classList.contains('active');
    
    if (isActive) {
        // Deactivate
        chipElement.classList.remove('active');
        chipElement.style.backgroundColor = '';
        chipElement.style.color = '';
        chipElement.style.borderColor = '';
    } else {
        // Activate
        chipElement.classList.add('active');
        const color = getComplexMarkerColor(status);
        chipElement.style.backgroundColor = color;
        chipElement.style.color = 'white';
        chipElement.style.borderColor = color;
    }
    
    // Update count immediately when status chip is toggled
    updateComplexFilterCount();
    
    // Trigger map refresh with filters
    applyFullscreenFilters();
}

// Apply filters to fullscreen map
function applyFullscreenFilters() {
    if (!fullscreenComplexesMapInstance) {
        console.warn('🏢 Map instance not initialized');
        return;
    }
    
    // Get active status filters
    const activeChips = document.querySelectorAll('.fullscreen-status-chip.active');
    const activeStatuses = Array.from(activeChips).map(chip => chip.getAttribute('data-status'));
    
    console.log('🏢 Applying fullscreen filters:', activeStatuses);
    
    // If no filters active, show all markers
    if (activeStatuses.length === 0) {
        console.log('🏢 No filters active - showing all complexes');
        if (window._complexesClusterer) {
            window._complexesClusterer.removeAll();
            window._complexesClusterer.add(allComplexMarkers.map(m => m.marker));
        }
        return;
    }
    
    // Filter markers based on complex statuses
    let visibleCount = 0;
    const visibleMarkers = [];
    allComplexMarkers.forEach(markerData => {
        const hasMatchingStatus = markerData.complexes.some(complex => {
            const complexStatus = getStatusDisplayText(complex.status);
            return activeStatuses.includes(complexStatus);
        });
        if (hasMatchingStatus) {
            visibleMarkers.push(markerData.marker);
            visibleCount++;
        }
    });

    if (window._complexesClusterer) {
        window._complexesClusterer.removeAll();
        if (visibleMarkers.length > 0) {
            window._complexesClusterer.add(visibleMarkers);
        }
    }
    
    console.log(`🏢 Filtered: ${visibleCount}/${allComplexMarkers.length} marker groups visible`);
}

// ==================== FILTER FUNCTIONS ====================

// Open complex filters sheet
function openComplexFiltersSheet() {
    const sheet = document.getElementById('complexFiltersSheet');
    const backdrop = document.getElementById('complexFiltersBackdrop');
    
    if (!sheet || !backdrop) return;
    
    console.log('🏢 Opening complex filters sheet');
    
    backdrop.classList.remove('hidden');
    sheet.classList.remove('hidden');
    
    setTimeout(() => {
        backdrop.style.opacity = '1';
        sheet.style.transform = 'translateY(0)';
    }, 10);

    // Обновляем счётчик через client-side фильтрацию по window.allComplexes
    // (счёт видимых маркеров ненадёжен — карта может ещё не загрузиться)
    if (typeof updateMapSheetCount === 'function') {
        updateMapSheetCount();
    } else if (allComplexMarkers.length > 0) {
        let visibleCount = 0;
        allComplexMarkers.forEach(markerData => {
            const isVisible = markerData.marker.options.get('visible');
            if (isVisible === undefined || isVisible === true) visibleCount++;
        });
        updateComplexFilterButton(visibleCount);
    }
}

// Close complex filters sheet
function closeComplexFiltersSheet() {
    const sheet = document.getElementById('complexFiltersSheet');
    const backdrop = document.getElementById('complexFiltersBackdrop');
    
    if (!sheet || !backdrop) return;
    
    console.log('🏢 Closing complex filters sheet');
    
    backdrop.style.opacity = '0';
    sheet.style.transform = 'translateY(100%)';
    
    setTimeout(() => {
        backdrop.classList.add('hidden');
        sheet.classList.add('hidden');
    }, 300);
}

// Toggle room chip selection
function toggleRoomChip(chipElement) {
    const isActive = chipElement.classList.contains('active');
    
    if (isActive) {
        chipElement.classList.remove('active', 'bg-blue-600', 'text-white', 'border-blue-600');
        chipElement.classList.add('border-gray-300');
    } else {
        chipElement.classList.add('active', 'bg-blue-600', 'text-white', 'border-blue-600');
        chipElement.classList.remove('border-gray-300');
    }
    
    // Update count immediately when room chip is toggled
    updateComplexFilterCount();
}

// Pluralize "ЖК" correctly in Russian
function pluralizeZhk(count) {
    if (count % 10 === 1 && count % 100 !== 11) {
        return `${count} ЖК`;
    } else if ([2, 3, 4].includes(count % 10) && ![12, 13, 14].includes(count % 100)) {
        return `${count} ЖК`;
    } else {
        return `${count} ЖК`;
    }
}

// Update filter button text with count
function updateComplexFilterButton(count) {
    const buttonText = `Показать ${pluralizeZhk(count)}`;
    
    // Update quick filters button — update span if exists, otherwise set innerHTML
    const quickButton = document.getElementById('complexFiltersApplyBtn');
    if (quickButton) {
        const span = document.getElementById('mapSheetCount');
        if (span) {
            span.textContent = count;
        } else {
            quickButton.innerHTML = `Показать <span id="mapSheetCount">${count}</span> ЖК`;
        }
    }
    
    // Update advanced filters button
    const advancedButton = document.getElementById('complexAdvancedFiltersApplyBtn');
    if (advancedButton) {
        advancedButton.textContent = buttonText;
    }
    
    console.log(`🏢 Updated filter buttons: "${buttonText}"`);
}

// Reset complex filters
function resetComplexFilters() {
    // Clear mobile sheet inputs
    ['complexPriceFrom','complexPriceTo','complexYearFrom','complexYearTo'].forEach(id => {
        const el = document.getElementById(id); if (el) el.value = '';
    });
    // Clear desktop panel inputs
    ['desktopComplexPriceFrom','desktopComplexPriceTo','desktopComplexYearFrom','desktopComplexYearTo'].forEach(id => {
        const el = document.getElementById(id); if (el) el.value = '';
    });
    // Reset room chips (desktop + mobile)
    document.querySelectorAll('.complex-room-chip').forEach(chip => {
        chip.classList.remove('active', 'bg-[#0088CC]', 'text-white', 'border-[#0088CC]', 'bg-blue-600', 'border-blue-600');
        chip.classList.add('border-gray-300');
        chip.style.cssText = '';
    });
    // Reset class checkboxes
    document.querySelectorAll('.complex-class-filter,.complex-developer-filter,.complex-district-filter').forEach(cb => { cb.checked = false; });
    // Reset status chips: reactivate "Все", deactivate others
    const allStatusBtn = document.querySelector('.fullscreen-status-chip[data-status=""]');
    if (allStatusBtn) filterByStatus('', allStatusBtn);
    if (typeof updateComplexActiveFiltersDisplay === 'function') updateComplexActiveFiltersDisplay();
    if (allComplexesData.length > 0) updateComplexFilterButton(allComplexesData.length);
    console.log('🏢 Reset all desktop+mobile filters');
}

// Toggle a desktop room chip (active ↔ inactive)
function toggleComplexDesktopRoom(btn) {
    const isActive = btn.classList.contains('active');
    if (isActive) {
        btn.classList.remove('active', 'bg-[#0088CC]', 'text-white', 'border-[#0088CC]');
        btn.classList.add('border-gray-300');
        btn.style.cssText = '';
    } else {
        btn.classList.add('active', 'bg-[#0088CC]', 'text-white', 'border-[#0088CC]');
        btn.classList.remove('border-gray-300');
        btn.style.cssText = 'background:#0088CC;border-color:#0088CC;color:#fff;';
    }
}

// Apply complex filters
function applyComplexMapFilters() {
    console.log('🏢 Applying complex MAP filters');

    // === Читаем из чипов bottom-sheet (complexFiltersSheet) ===
    const activeSheetStatusChip = document.querySelector('.map-status-chip[data-active="true"]');
    const sheetStatus = activeSheetStatusChip ? (activeSheetStatusChip.dataset.statusValue || '') : null;

    const activeSheetYearChip = document.querySelector('.map-year-chip[data-active="true"]');
    const sheetYearRaw = activeSheetYearChip ? parseInt(activeSheetYearChip.dataset.yearValue || '') : null;
    const sheetYear = (sheetYearRaw && !isNaN(sheetYearRaw)) ? sheetYearRaw : null;

    const activeSheetClassChip = document.querySelector('.map-class-chip[data-active="true"]');
    const sheetClass = activeSheetClassChip ? (activeSheetClassChip.dataset.classValue || '') : '';

    const sheetRoomChips = Array.from(document.querySelectorAll('.map-room-chip[data-active="true"]'));
    const sheetRooms = sheetRoomChips.map(b => b.dataset.rooms || '');

    // === Статус: чипы sheet имеют приоритет над fullscreen-status-chip ===
    let activeStatuses = [];
    if (sheetStatus !== null) {
        if (sheetStatus) activeStatuses = [sheetStatus];
    } else {
        const activeChips = document.querySelectorAll('.fullscreen-status-chip.active');
        activeStatuses = Array.from(activeChips).map(chip => chip.getAttribute('data-status'));
    }

    // === Цена: sheet inputs или desktop inputs ===
    const priceFrom = parseFloat(
        document.getElementById('complexPriceFrom')?.value ||
        document.getElementById('desktopComplexPriceFrom')?.value || ''
    ) || null;
    const priceTo = parseFloat(
        document.getElementById('complexPriceTo')?.value ||
        document.getElementById('desktopComplexPriceTo')?.value || ''
    ) || null;

    // === Год: chip из sheet имеет приоритет, иначе desktop range ===
    const yearFrom = sheetYear || parseInt(
        document.getElementById('desktopComplexYearFrom')?.value ||
        document.getElementById('complexYearFrom')?.value || ''
    ) || null;
    const yearTo = sheetYear || parseInt(
        document.getElementById('desktopComplexYearTo')?.value ||
        document.getElementById('complexYearTo')?.value || ''
    ) || null;

    // === Комнаты: sheet чипы имеют приоритет ===
    const activeRooms = sheetRooms.length > 0 ? sheetRooms : Array.from(
        document.querySelectorAll('.complex-room-chip.active, .mobile-map-room-chip.active')
    ).map(chip => chip.getAttribute('data-rooms'));

    // === Класс: sheet chip имеет приоритет над чекбоксами ===
    const classes = sheetClass
        ? [sheetClass]
        : Array.from(document.querySelectorAll('.complex-class-filter:checked')).map(cb => cb.value);

    const developers = Array.from(document.querySelectorAll('.complex-developer-filter:checked')).map(cb => parseInt(cb.value));
    const districts = Array.from(document.querySelectorAll('.complex-district-filter:checked')).map(cb => parseInt(cb.value));

    console.log('🏢 Filter values:', { activeStatuses, priceFrom, priceTo, yearFrom, yearTo, activeRooms, classes });

    const visibleCount = filterComplexMarkers({
        priceFrom,
        priceTo,
        yearFrom,
        yearTo,
        statuses: activeStatuses,
        rooms: activeRooms,
        developers,
        districts,
        classes
    });

    updateComplexFilterButton(visibleCount);
    if (typeof updateComplexActiveFiltersDisplay === 'function') updateComplexActiveFiltersDisplay();
    closeComplexFiltersSheet();
}

// Open advanced filters modal
function openComplexAdvancedFilters() {
    const modal = document.getElementById('complexAdvancedFiltersModal');
    if (!modal) return;
    
    console.log('🏢 Opening advanced filters modal');
    modal.classList.remove('hidden');
    document.body.style.overflow = 'hidden';
}

// Close advanced filters modal
function closeComplexAdvancedFilters() {
    const modal = document.getElementById('complexAdvancedFiltersModal');
    if (!modal) return;
    
    console.log('🏢 Closing advanced filters modal');
    modal.classList.add('hidden');
    document.body.style.overflow = '';
}

// Reset advanced filters
function resetComplexAdvancedFilters() {
    document.querySelectorAll('.complex-developer-filter').forEach(cb => cb.checked = false);
    document.querySelectorAll('.complex-district-filter').forEach(cb => cb.checked = false);
    document.querySelectorAll('.complex-class-filter').forEach(cb => cb.checked = false);
    console.log('🏢 Reset advanced filters');
}

// Apply advanced filters
function applyComplexAdvancedFilters() {
    console.log('🏢 Applying advanced filters');
    
    const priceFrom = parseFloat(document.getElementById('complexPriceFrom').value) || null;
    const priceTo = parseFloat(document.getElementById('complexPriceTo').value) || null;
    const yearFrom = parseInt(document.getElementById('complexYearFrom').value) || null;
    const yearTo = parseInt(document.getElementById('complexYearTo').value) || null;
    
    const developers = Array.from(document.querySelectorAll('.complex-developer-filter:checked')).map(cb => parseInt(cb.value));
    const districts = Array.from(document.querySelectorAll('.complex-district-filter:checked')).map(cb => parseInt(cb.value));
    const classes = Array.from(document.querySelectorAll('.complex-class-filter:checked')).map(cb => cb.value);
    
    const activeChips = document.querySelectorAll('.fullscreen-status-chip.active');
    const activeStatuses = Array.from(activeChips).map(chip => chip.getAttribute('data-status'));
    
    const activeRoomChips = document.querySelectorAll('.complex-room-chip.active, .mobile-map-room-chip.active');
    const activeRooms = Array.from(activeRoomChips).map(chip => chip.getAttribute('data-rooms'));
    
    // Filter markers and get visible count
    const visibleCount = filterComplexMarkers({
        priceFrom,
        priceTo,
        yearFrom,
        yearTo,
        developers,
        districts,
        classes,
        statuses: activeStatuses,
        rooms: activeRooms
    });
    
    // Update button text with count
    updateComplexFilterButton(visibleCount);
    
    closeComplexAdvancedFilters();
    closeComplexFiltersSheet();
}

// Toggle developers filter section
function toggleComplexDevelopersFilter() {
    // Toggle mobile version
    const content = document.getElementById('complexDevelopersContent');
    const arrow = document.getElementById('complexDevelopersArrow');
    // Toggle desktop version
    const desktopContent = document.getElementById('desktopDevelopersContent');
    const desktopArrow = document.getElementById('desktopDevelopersArrow');
    
    // Toggle mobile
    if (content && arrow) {
        if (content.classList.contains('hidden')) {
            content.classList.remove('hidden');
            arrow.style.transform = 'rotate(180deg)';
        } else {
            content.classList.add('hidden');
            arrow.style.transform = 'rotate(0deg)';
        }
    }
    
    // Toggle desktop
    if (desktopContent && desktopArrow) {
        if (desktopContent.classList.contains('hidden')) {
            desktopContent.classList.remove('hidden');
            desktopArrow.style.transform = 'rotate(180deg)';
        } else {
            desktopContent.classList.add('hidden');
            desktopArrow.style.transform = 'rotate(0deg)';
        }
    }
}

// Toggle districts filter section
function toggleComplexDistrictsFilter() {
    // Toggle mobile version
    const content = document.getElementById('complexDistrictsContent');
    const arrow = document.getElementById('complexDistrictsArrow');
    // Toggle desktop version
    const desktopContent = document.getElementById('desktopDistrictsContent');
    const desktopArrow = document.getElementById('desktopDistrictsArrow');
    
    // Toggle mobile
    if (content && arrow) {
        if (content.classList.contains('hidden')) {
            content.classList.remove('hidden');
            arrow.style.transform = 'rotate(180deg)';
        } else {
            content.classList.add('hidden');
            arrow.style.transform = 'rotate(0deg)';
        }
    }
    
    // Toggle desktop
    if (desktopContent && desktopArrow) {
        if (desktopContent.classList.contains('hidden')) {
            desktopContent.classList.remove('hidden');
            desktopArrow.style.transform = 'rotate(180deg)';
        } else {
            desktopContent.classList.add('hidden');
            desktopArrow.style.transform = 'rotate(0deg)';
        }
    }
}

// Count matching complexes without applying filters to map
function countMatchingComplexes(filters) {
    if (!fullscreenComplexesMapInstance || !allComplexMarkers) {
        return 0;
    }
    
    let count = 0;
    
    allComplexMarkers.forEach(markerData => {
        const matchingComplexes = markerData.complexes.filter(complex => {
            // Status filter
            if (filters.statuses && filters.statuses.length > 0) {
                const complexStatus = getStatusDisplayText(complex.status);
                if (!filters.statuses.includes(complexStatus)) {
                    return false;
                }
            }
            
            // Price filter - check all possible field names
            const complexPrice = complex.price_from || complex.min_price;
            if (filters.priceFrom && complexPrice) {
                if (complexPrice < filters.priceFrom * 1000000) return false;
            }
            if (filters.priceTo && complexPrice) {
                if (complexPrice > filters.priceTo * 1000000) return false;
            }
            
            // Year filter - check all possible field names
            const complexYear = complex.end_build_year || complex.completion_year || complex.build_year;
            if (filters.yearFrom && complexYear) {
                if (complexYear < filters.yearFrom) return false;
            }
            if (filters.yearTo && complexYear) {
                if (complexYear > filters.yearTo) return false;
            }
            
            // Rooms filter - check all possible field names
            if (filters.rooms && filters.rooms.length > 0) {
                const roomTypes = complex.room_types || complex.available_rooms;
                if (roomTypes && Array.isArray(roomTypes)) {
                    const hasMatchingRoom = filters.rooms.some(room => roomTypes.includes(parseInt(room)) || roomTypes.includes(room));
                    if (!hasMatchingRoom) return false;
                } else {
                    // No room data - allow through if rooms filter is active
                }
            }
            
            return true;
        });
        
        count += matchingComplexes.length;
    });
    
    return count;
}

// Update filter count display without applying to map
function updateComplexFilterCount() {
    const priceFrom = parseFloat(document.getElementById('complexPriceFrom').value) || null;
    const priceTo = parseFloat(document.getElementById('complexPriceTo').value) || null;
    const yearFrom = parseInt(document.getElementById('complexYearFrom').value) || null;
    const yearTo = parseInt(document.getElementById('complexYearTo').value) || null;
    
    // Get active status filters
    const activeChips = document.querySelectorAll('.fullscreen-status-chip.active');
    const activeStatuses = Array.from(activeChips).map(chip => chip.getAttribute('data-status'));
    
    // Get active room filters
    const activeRoomChips = document.querySelectorAll('.complex-room-chip.active, .mobile-map-room-chip.active');
    const activeRooms = Array.from(activeRoomChips).map(chip => chip.getAttribute('data-rooms'));
    
    // Count matching complexes
    const count = countMatchingComplexes({
        priceFrom,
        priceTo,
        yearFrom,
        yearTo,
        statuses: activeStatuses,
        rooms: activeRooms
    });
    
    // Update button text
    updateComplexFilterButton(count);
    
    console.log(`🏢 Filter count updated: ${count} complexes match current filters`);
}

// Main filter function for complex markers
function filterComplexMarkers(filters) {
    if (!fullscreenComplexesMapInstance) {
        console.warn('🏢 Map instance not initialized');
        return 0;
    }
    
    console.log('🏢 Filtering markers with:', filters);
    
    let visibleComplexCount = 0;
    const visibleMarkers = [];
    
    allComplexMarkers.forEach(markerData => {
        // Filter complexes in this marker group
        const matchingComplexes = markerData.complexes.filter(complex => {
            // Status filter
            if (filters.statuses && filters.statuses.length > 0) {
                const complexStatus = getStatusDisplayText(complex.status);
                if (!filters.statuses.includes(complexStatus)) {
                    return false;
                }
            }
            
            // Price filter (convert to rubles for comparison) - check all possible field names
            const complexPrice = complex.price_from || complex.min_price;
            if (filters.priceFrom && complexPrice) {
                if (complexPrice < filters.priceFrom * 1000000) return false;
            }
            if (filters.priceTo && complexPrice) {
                if (complexPrice > filters.priceTo * 1000000) return false;
            }
            
            // Year filter - check all possible field names
            const complexYear = complex.end_build_year || complex.completion_year || complex.build_year;
            if (filters.yearFrom && complexYear) {
                if (complexYear < filters.yearFrom) return false;
            }
            if (filters.yearTo && complexYear) {
                if (complexYear > filters.yearTo) return false;
            }
            
            // Developer filter - check both developer_id and developer name
            if (filters.developers && filters.developers.length > 0) {
                const matchesDeveloper = filters.developers.some(devFilter => {
                    // Support both ID (number/string) and name matching
                    const devFilterStr = String(devFilter);
                    const complexDevId = complex.developer_id ? String(complex.developer_id) : null;
                    const complexDevName = complex.developer || complex.developer_name;
                    
                    return (complexDevId && complexDevId === devFilterStr) || 
                           (complexDevName && complexDevName === devFilter);
                });
                if (!matchesDeveloper) return false;
            }
            
            // District filter - check both district_id and district name
            if (filters.districts && filters.districts.length > 0) {
                const matchesDistrict = filters.districts.some(distFilter => {
                    // Support both ID (number/string) and name matching
                    const distFilterStr = String(distFilter);
                    const complexDistId = complex.district_id ? String(complex.district_id) : null;
                    const complexDistName = complex.district;
                    
                    return (complexDistId && complexDistId === distFilterStr) || 
                           (complexDistName && complexDistName === distFilter);
                });
                if (!matchesDistrict) return false;
            }
            
            // Class filter - check object_class field
            if (filters.classes && filters.classes.length > 0) {
                const complexClass = complex.object_class || complex.class || complex.housing_class;
                if (!complexClass || !filters.classes.includes(complexClass)) return false;
            }
            
            // Rooms filter - check if complex has properties with selected room types
            if (filters.rooms && filters.rooms.length > 0) {
                // Use room_details object (preferred) or room_types array
                if (complex.room_details) {
                    // room_details is an object like {"Студия": {count: 5}, "1-комн": {count: 10}}
                    const hasMatchingRoom = filters.rooms.some(roomFilter => {
                        // Map filter value to room_details key format
                        let roomKey;
                        if (roomFilter === 'студия') {
                            roomKey = 'Студия';
                        } else if (roomFilter === '4+-комн') {
                            // Check for 4-комн, 5-комн, 6-комн, etc.
                            return Object.keys(complex.room_details).some(key => {
                                const match = key.match(/^(\d+)-комн$/);
                                if (match && parseInt(match[1]) >= 4) {
                                    return complex.room_details[key] && complex.room_details[key].count > 0;
                                }
                                return false;
                            });
                        } else {
                            roomKey = roomFilter; // "1-комн", "2-комн", "3-комн"
                        }
                        return complex.room_details[roomKey] && complex.room_details[roomKey].count > 0;
                    });
                    if (!hasMatchingRoom) return false;
                } else {
                    // Fallback: check room_types array
                    const roomTypes = complex.room_types || complex.available_rooms;
                    if (roomTypes && Array.isArray(roomTypes)) {
                        const hasMatchingRoom = filters.rooms.some(room => {
                            const roomNum = parseInt(room);
                            return roomTypes.includes(roomNum) || roomTypes.includes(room);
                        });
                        if (!hasMatchingRoom) return false;
                    }
                    // If no room data available, filter out to be safe
                    else return false;
                }
            }
            
            return true;
        });
        
        // Collect visible markers (clusterer requires remove+add, not options.set visible)
        if (matchingComplexes.length > 0) {
            visibleMarkers.push(markerData.marker);
            visibleComplexCount += matchingComplexes.length;
        }
    });

    // Update clusterer: remove all, re-add only visible
    if (window._complexesClusterer) {
        window._complexesClusterer.removeAll();
        if (visibleMarkers.length > 0) {
            window._complexesClusterer.add(visibleMarkers);
        }
    }
    
    // Also update sidebar to show only filtered complexes
    const filteredComplexes = allComplexesData.filter(complex => {
        // Apply same filters to allComplexesData
        if (filters.statuses && filters.statuses.length > 0) {
            const complexStatus = getStatusDisplayText(complex.status);
            if (!filters.statuses.includes(complexStatus)) return false;
        }
        if (filters.priceFrom && (complex.price_from || complex.min_price)) {
            const price = complex.price_from || complex.min_price;
            if (price < filters.priceFrom * 1000000) return false;
        }
        if (filters.priceTo && (complex.price_from || complex.min_price)) {
            const price = complex.price_from || complex.min_price;
            if (price > filters.priceTo * 1000000) return false;
        }
        if (filters.yearFrom && complex.completion_year) {
            if (complex.completion_year < filters.yearFrom) return false;
        }
        if (filters.yearTo && complex.completion_year) {
            if (complex.completion_year > filters.yearTo) return false;
        }
        if (filters.developers && filters.developers.length > 0) {
            const complexDevId = complex.developer_id ? String(complex.developer_id) : null;
            if (!filters.developers.some(d => String(d) === complexDevId)) return false;
        }
        if (filters.districts && filters.districts.length > 0) {
            const complexDistId = complex.district_id ? String(complex.district_id) : null;
            if (!filters.districts.some(d => String(d) === complexDistId)) return false;
        }
        if (filters.classes && filters.classes.length > 0) {
            const complexClass = complex.object_class || complex.class || complex.housing_class;
            if (!complexClass || !filters.classes.includes(complexClass)) return false;
        }
        if (filters.rooms && filters.rooms.length > 0) {
            // Use room_details object (preferred) or room_types array
            if (complex.room_details) {
                const hasMatchingRoom = filters.rooms.some(roomFilter => {
                    let roomKey;
                    if (roomFilter === 'студия') {
                        roomKey = 'Студия';
                    } else if (roomFilter === '4+-комн') {
                        return Object.keys(complex.room_details).some(key => {
                            const match = key.match(/^(\d+)-комн$/);
                            if (match && parseInt(match[1]) >= 4) {
                                return complex.room_details[key] && complex.room_details[key].count > 0;
                            }
                            return false;
                        });
                    } else {
                        roomKey = roomFilter;
                    }
                    return complex.room_details[roomKey] && complex.room_details[roomKey].count > 0;
                });
                if (!hasMatchingRoom) return false;
            } else {
                const roomTypes = complex.room_types || complex.available_rooms;
                if (roomTypes && Array.isArray(roomTypes)) {
                    if (!filters.rooms.some(r => roomTypes.includes(r))) return false;
                } else {
                    return false;
                }
            }
        }
        return true;
    });
    
    updateSidebar(filteredComplexes);
    
    console.log(`🏢 Filtered: ${visibleComplexCount} complexes, ${visibleMarkers.length} marker groups visible of ${allComplexMarkers.length} total`);
    return visibleComplexCount;
}

// Make functions globally available
window.openFullscreenComplexesMap = openFullscreenComplexesMap;
window.closeFullscreenComplexesMap = closeFullscreenComplexesMap;
window.openComplexBottomSheet = openComplexBottomSheet;
window.closeComplexBottomSheet = closeComplexBottomSheet;
window.returnToComplexesList = returnToComplexesList;
window.openComplexFiltersSheet = openComplexFiltersSheet;
window.closeComplexFiltersSheet = closeComplexFiltersSheet;
window.resetComplexFilters = resetComplexFilters;
window.applyComplexMapFilters = applyComplexMapFilters;
window.openComplexAdvancedFilters = openComplexAdvancedFilters;
window.closeComplexAdvancedFilters = closeComplexAdvancedFilters;
window.resetComplexAdvancedFilters = resetComplexAdvancedFilters;
window.applyComplexAdvancedFilters = applyComplexAdvancedFilters;
window.toggleComplexDevelopersFilter = toggleComplexDevelopersFilter;
window.toggleComplexDistrictsFilter = toggleComplexDistrictsFilter;
window.applyAllFiltersToMap = applyAllFiltersToMap;

// ─── Active filter pills for ЖК map ─────────────────────────────────────────
function updateComplexActiveFiltersDisplay() {
    const bar  = document.getElementById('complexActiveFiltersBar');
    const list = document.getElementById('complexActiveFiltersList');
    if (!bar || !list) return;

    const pills = [];

    // Status
    if (activeStatusFilters.length > 0) {
        pills.push({ text: 'Статус: ' + activeStatusFilters.join(', '), key: 'status' });
    }

    // Rooms (desktop chips)
    const activeRooms = Array.from(document.querySelectorAll('.complex-room-chip.active'))
        .map(c => c.textContent.trim());
    if (activeRooms.length > 0) {
        pills.push({ text: 'Комнаты: ' + activeRooms.join(', '), key: 'rooms' });
    }

    // Price
    const pFrom = document.getElementById('desktopComplexPriceFrom')?.value || document.getElementById('complexPriceFrom')?.value || '';
    const pTo   = document.getElementById('desktopComplexPriceTo')?.value  || document.getElementById('complexPriceTo')?.value  || '';
    if (pFrom || pTo) {
        let t = 'Цена: ';
        if (pFrom) t += 'от ' + pFrom + ' млн';
        if (pTo)   t += (pFrom ? ' ' : '') + 'до ' + pTo + ' млн';
        pills.push({ text: t, key: 'price' });
    }

    // Year
    const yFrom = document.getElementById('desktopComplexYearFrom')?.value || document.getElementById('complexYearFrom')?.value || '';
    const yTo   = document.getElementById('desktopComplexYearTo')?.value   || document.getElementById('complexYearTo')?.value   || '';
    if (yFrom || yTo) {
        let t = 'Год сдачи: ';
        if (yFrom) t += 'от ' + yFrom;
        if (yTo)   t += (yFrom ? ' ' : '') + 'до ' + yTo;
        pills.push({ text: t, key: 'year' });
    }

    // Class
    const classes = Array.from(document.querySelectorAll('.complex-class-filter:checked')).map(c => c.value);
    if (classes.length > 0) {
        pills.push({ text: 'Класс: ' + classes.join(', '), key: 'class' });
    }

    // Developers
    const devs = Array.from(document.querySelectorAll('.complex-developer-filter:checked'))
        .map(c => c.closest('label')?.querySelector('span')?.textContent?.trim() || c.value);
    if (devs.length > 0) {
        const t = devs.length > 2 ? devs.length + ' застройщика' : devs.join(', ');
        pills.push({ text: 'Застройщик: ' + t, key: 'developer' });
    }

    // Districts
    const dists = Array.from(document.querySelectorAll('.complex-district-filter:checked'))
        .map(c => c.closest('label')?.querySelector('span')?.textContent?.trim() || c.value);
    if (dists.length > 0) {
        const t = dists.length > 2 ? dists.length + ' района' : dists.join(', ');
        pills.push({ text: 'Район: ' + t, key: 'district' });
    }

    // Badge on Фильтры button
    const badge = document.getElementById('complexFiltersCountBadge');
    if (badge) {
        if (pills.length > 0) { badge.textContent = pills.length; badge.classList.remove('hidden'); }
        else { badge.classList.add('hidden'); }
    }

    if (pills.length === 0) {
        bar.classList.add('hidden');
        list.innerHTML = '';
        return;
    }

    bar.classList.remove('hidden');
    list.innerHTML = pills.map(p =>
        `<span class="bg-white border border-blue-300 text-blue-700 px-2 py-1 rounded-full flex items-center gap-1 whitespace-nowrap">
            ${p.text}
            <button onclick="clearComplexFilter('${p.key}')" class="ml-1 text-blue-400 hover:text-blue-600 rounded-full w-4 h-4 flex items-center justify-center text-xs leading-none">×</button>
        </span>`
    ).join('');
}

function clearComplexFilter(key) {
    if (key === 'status') {
        const allBtn = document.querySelector('.fullscreen-status-chip[data-status=""]');
        if (allBtn) filterByStatus('', allBtn);
        return; // filterByStatus calls applyAllFiltersToMap
    }
    if (key === 'rooms') {
        document.querySelectorAll('.complex-room-chip.active').forEach(c => {
            c.classList.remove('active', 'bg-[#0088CC]', 'text-white', 'border-[#0088CC]');
            c.classList.add('border-gray-300');
            c.style.cssText = '';
        });
    } else if (key === 'price') {
        ['desktopComplexPriceFrom','desktopComplexPriceTo','complexPriceFrom','complexPriceTo'].forEach(id => {
            const el = document.getElementById(id); if (el) el.value = '';
        });
    } else if (key === 'year') {
        ['desktopComplexYearFrom','desktopComplexYearTo','complexYearFrom','complexYearTo'].forEach(id => {
            const el = document.getElementById(id); if (el) el.value = '';
        });
    } else if (key === 'class') {
        document.querySelectorAll('.complex-class-filter:checked').forEach(c => { c.checked = false; });
    } else if (key === 'developer') {
        document.querySelectorAll('.complex-developer-filter:checked').forEach(c => { c.checked = false; });
    } else if (key === 'district') {
        document.querySelectorAll('.complex-district-filter:checked').forEach(c => { c.checked = false; });
    }
    applyAllFiltersToMap();
}
window.updateComplexActiveFiltersDisplay = updateComplexActiveFiltersDisplay;
window.clearComplexFilter = clearComplexFilter;
// ─────────────────────────────────────────────────────────────────────────────

console.log('🏢 Complexes fullscreen map module loaded successfully');

function toggleDesktopFilters() {
    // For mobile, use bottom sheet
    if (window.innerWidth <= 768) {
        openComplexFiltersSheet();
        return;
    }
    
    // For desktop, use right-side modal
    const modal = document.getElementById('desktopFilterModal');
    const overlay = document.getElementById('desktopFilterOverlay');
    if (modal && overlay) {
        modal.classList.toggle('open');
        overlay.classList.toggle('open');
    }
}

// Filter developers list by search query
function filterDevelopersList(query) {
    const searchLower = query.toLowerCase().trim();
    const developerItems = document.querySelectorAll('.developer-item');
    
    developerItems.forEach(item => {
        const name = item.getAttribute('data-name') || '';
        if (!searchLower || name.includes(searchLower)) {
            item.style.display = '';
        } else {
            item.style.display = 'none';
        }
    });
}

window.filterDevelopersList = filterDevelopersList;

// Search autocomplete functionality
let searchDebounceTimer = null;

function initSearchAutocomplete() {
    const searchInput = document.getElementById('map-complex-search');
    const dropdown = document.getElementById('map-complex-search-dropdown');
    
    if (!searchInput || !dropdown) return;
    
    searchInput.addEventListener('input', (e) => {
        const query = e.target.value.toLowerCase().trim();
        
        clearTimeout(searchDebounceTimer);
        searchDebounceTimer = setTimeout(() => {
            if (query.length < 2) {
                dropdown.classList.add('hidden');
                dropdown.innerHTML = '';
                // Reset to show all if query cleared
                if (query.length === 0 && allComplexesData.length > 0) {
                    updateMapMarkers(allComplexesData);
                    updateSidebar(allComplexesData);
                }
                return;
            }
            
            // Find matching complexes
            const complexMatches = allComplexesData.filter(c => 
                c.name.toLowerCase().includes(query) || 
                (c.address || '').toLowerCase().includes(query)
            ).slice(0, 5);
            
            // Find matching developers (unique)
            const developerMap = new Map();
            allComplexesData.forEach(c => {
                const devName = c.developer_name || c.developer;
                const devId = c.developer_id;
                if (devName && devName.toLowerCase().includes(query) && !developerMap.has(devId)) {
                    const devComplexes = allComplexesData.filter(x => 
                        (x.developer_id === devId) || (x.developer_name === devName || x.developer === devName)
                    );
                    developerMap.set(devId || devName, { name: devName, id: devId, count: devComplexes.length });
                }
            });
            const developerMatches = Array.from(developerMap.values()).slice(0, 3);
            
            if (complexMatches.length === 0 && developerMatches.length === 0) {
                dropdown.innerHTML = '<div class="p-4 text-sm text-gray-500 text-center">Ничего не найдено</div>';
                dropdown.classList.remove('hidden');
                return;
            }
            
            let html = '';
            
            // Developer suggestions first
            if (developerMatches.length > 0) {
                html += '<div class="px-3 py-1.5 text-xs text-gray-400 uppercase font-semibold bg-gray-50">Застройщики</div>';
                html += developerMatches.map(d => `
                    <div class="autocomplete-item autocomplete-developer" data-developer-id="${d.id || ''}" data-developer-name="${d.name}">
                        <div class="font-medium text-gray-900 text-sm">👷 ${highlightMatch(d.name, query)}</div>
                        <div class="text-xs text-gray-500 mt-0.5">${d.count} ЖК</div>
                    </div>
                `).join('');
            }
            
            // Complex suggestions
            if (complexMatches.length > 0) {
                if (developerMatches.length > 0) {
                    html += '<div class="px-3 py-1.5 text-xs text-gray-400 uppercase font-semibold bg-gray-50 border-t">Жилые комплексы</div>';
                }
                html += complexMatches.map(c => `
                    <div class="autocomplete-item autocomplete-complex" data-id="${c.id}">
                        <div class="font-medium text-gray-900 text-sm">${highlightMatch(c.name, query)}</div>
                        <div class="text-xs text-gray-500 mt-0.5">${c.address || c.district || ''} • ${c.developer_name || c.developer || ''}</div>
                    </div>
                `).join('');
            }
            
            dropdown.innerHTML = html;
            dropdown.classList.remove('hidden');
            
            // Add click handlers for developers
            dropdown.querySelectorAll('.autocomplete-developer').forEach(item => {
                item.addEventListener('click', () => {
                    const devId = item.dataset.developerId;
                    const devName = item.dataset.developerName;
                    searchInput.value = devName;
                    dropdown.classList.add('hidden');
                    
                    // Filter to show all complexes by this developer
                    const devComplexes = allComplexesData.filter(c => 
                        (devId && String(c.developer_id) === devId) || 
                        (c.developer_name === devName || c.developer === devName)
                    );
                    updateMapMarkers(devComplexes);
                    updateSidebar(devComplexes);
                    
                    // Fit map to show all developer's complexes
                    if (devComplexes.length > 0 && fullscreenComplexesMapInstance) {
                        const bounds = devComplexes.reduce((acc, c) => {
                            const lat = c.latitude || (c.coordinates && c.coordinates.lat);
                            const lng = c.longitude || (c.coordinates && c.coordinates.lng);
                            if (lat && lng) {
                                acc.push([lat, lng]);
                            }
                            return acc;
                        }, []);
                        if (bounds.length > 0) {
                            fullscreenComplexesMapInstance.setBounds(ymaps.util.bounds.fromPoints(bounds), { 
                                checkZoomRange: true, 
                                duration: 500,
                                zoomMargin: 50
                            });
                        }
                    }
                });
            });
            
            // Add click handlers for complexes
            dropdown.querySelectorAll('.autocomplete-complex').forEach(item => {
                item.addEventListener('click', () => {
                    const id = parseInt(item.dataset.id);
                    const complex = allComplexesData.find(c => c.id === id);
                    if (complex) {
                        searchInput.value = complex.name;
                        dropdown.classList.add('hidden');
                        
                        // Filter to show only this complex
                        updateMapMarkers([complex]);
                        updateSidebar([complex]);
                        
                        // Lock sidebar so boundschange doesn't immediately overwrite search result
                        window._complexMapSearchLock = true;
                        clearTimeout(window._complexMapSearchLockTimer);
                        window._complexMapSearchLockTimer = setTimeout(function() {
                            window._complexMapSearchLock = false;
                        }, 1500);
                        
                        // Center map on this complex
                        const lat = (complex.coordinates && complex.coordinates.lat) || complex.latitude;
                        const lng = (complex.coordinates && complex.coordinates.lng) || complex.longitude;
                        if (lat && lng && fullscreenComplexesMapInstance) {
                            fullscreenComplexesMapInstance.setCenter([lat, lng], 15, { duration: 500 });
                        }
                    }
                });
            });
        }, 200);
    });
    
    // Close dropdown when clicking outside
    document.addEventListener('click', (e) => {
        if (!searchInput.contains(e.target) && !dropdown.contains(e.target)) {
            dropdown.classList.add('hidden');
        }
    });
    
    // Handle Enter key
    searchInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
            const query = searchInput.value.toLowerCase().trim();
            const filtered = allComplexesData.filter(c => 
                c.name.toLowerCase().includes(query) || 
                (c.address || '').toLowerCase().includes(query) ||
                (c.developer_name || '').toLowerCase().includes(query)
            );
            dropdown.classList.add('hidden');
            updateMapMarkers(filtered);
            updateSidebar(filtered);
            // Lock sidebar briefly so boundschange doesn't immediately overwrite
            window._complexMapSearchLock = true;
            clearTimeout(window._complexMapSearchLockTimer);
            window._complexMapSearchLockTimer = setTimeout(function() {
                window._complexMapSearchLock = false;
            }, 1500);
        }
    });
}

function highlightMatch(text, query) {
    const regex = new RegExp(`(${query.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')})`, 'gi');
    return text.replace(regex, '<span class="text-[#0088CC] font-bold">$1</span>');
}

// Filter sidebar by visible map bounds AND active filters
function filterSidebarByBounds() {
    // If a polygon is drawn, re-apply polygon filter instead of overriding with bounds
    if (modalDrawnPolygon) {
        filterModalComplexesByPolygon();
        return;
    }
    // If a search result was just selected, don't override the sidebar yet
    if (window._complexMapSearchLock) return;

    if (!fullscreenComplexesMapInstance || !allComplexesData.length) return;
    
    try {
        const bounds = fullscreenComplexesMapInstance.getBounds();
        if (!bounds || !bounds[0] || !bounds[1]) return;
        
        // Yandex Maps returns bounds as [[sw_lat, sw_lng], [ne_lat, ne_lng]]
        const [[swLat, swLng], [neLat, neLng]] = bounds;
        
        // Get filtered complexes by current filters first
        const filteredByFilters = filterComplexesByCurrentFilters();
        
        // Then filter by bounds — use coordinates.lat/lng ONLY (same as map marker position)
        const filtered = filteredByFilters.filter(c => {
            const lat = c.coordinates && c.coordinates.lat;
            const lng = c.coordinates && c.coordinates.lng;
            if (!lat || !lng) return false;
            
            // Check if point is within bounds
            return lat >= swLat && lat <= neLat && lng >= swLng && lng <= neLng;
        });
        
        console.log(`🏢 Filtered ${filtered.length}/${allComplexesData.length} complexes by bounds + filters (statuses: ${activeStatusFilters.join(', ') || 'all'})`);
        updateSidebar(filtered);
        
        // Update counters
        document.querySelectorAll('.map-complexes-count').forEach(el => el.textContent = filtered.length);
    } catch (err) {
        console.warn('🏢 Error filtering by bounds:', err);
    }
}

// Initialize search when DOM ready
document.addEventListener('DOMContentLoaded', initSearchAutocomplete);

// ✅ Mobile complex map search (Avito-style header input)
window.handleMobileComplexSearch = function(query) {
    clearTimeout(window._mobileComplexSearchTimer);
    window._mobileComplexSearchTimer = setTimeout(function() {
        query = (query || '').trim().toLowerCase();
        window._mobileComplexSearchQuery = query;
        
        if (!allComplexesData || allComplexesData.length === 0) return;
        
        let results;
        if (query.length < 2) {
            // Show all filtered by current filters
            results = filterComplexesByCurrentFilters();
        } else {
            // Filter by name, developer, district
            results = filterComplexesByCurrentFilters().filter(function(c) {
                const name = (c.name || '').toLowerCase();
                const dev = (c.developer_name || c.developer || '').toLowerCase();
                const addr = (c.address || c.district || '').toLowerCase();
                return name.includes(query) || dev.includes(query) || addr.includes(query);
            });
        }
        
        updateSidebar(results);
        document.querySelectorAll('.map-complexes-count').forEach(function(el) {
            el.textContent = results.length;
        });
        
        console.log('🔍 Mobile complex search:', query, '→', results.length, 'results');
    }, 350);
};

// ========== CIAN Infrastructure for Fullscreen Modal (Yandex Maps + Overpass) ==========
var modalInfraActive = {};
var modalInfraLayers = {};
var modalInfraCfg = {
    shops:         { tag: '"shop"',                                   label: 'Магазин',     emoji: '🛒', color: '#f97316' },
    schools:       { tag: '"amenity"="school"',                       label: 'Школа',       emoji: '🏫', color: '#22c55e' },
    kindergartens: { tag: '"amenity"="kindergarten"',                  label: 'Детский сад', emoji: '🧒', color: '#3b82f6' },
    clinics:       { tag: '"amenity"~"clinic|hospital|doctors"',       label: 'Поликлиника', emoji: '🏥', color: '#ef4444' },
    pharmacies:    { tag: '"amenity"="pharmacy"',                      label: 'Аптека',      emoji: '💊', color: '#a855f7' },
    parks:         { tag: '"leisure"="park"',                          label: 'Парк',        emoji: '🌳', color: '#16a34a' },
    fitness:       { tag: '"leisure"~"fitness_centre|sports_centre"',  label: 'Фитнес',      emoji: '🏋️', color: '#1d4ed8' },
    transport:     { tag: '"highway"="bus_stop"',                      label: 'Остановки',   emoji: '🚌', color: '#6b7280' }
};

function createModalInfraIconLayout(emoji, color) {
    var html = '<div style="width:30px;height:30px;background:' + color + ';border-radius:50%;' +
        'border:2.5px solid white;box-shadow:0 2px 8px rgba(0,0,0,0.35);' +
        'display:flex;align-items:center;justify-content:center;font-size:15px;' +
        'cursor:pointer;transform:translate(-50%,-100%) translateY(-4px);">' + emoji + '</div>';
    return ymaps.templateLayoutFactory.createClass(html);
}

function toggleModalInfraDropdown(e) {
    if (e) e.stopPropagation();
    var panel = document.getElementById('modalInfraDropdownPanel');
    var chevron = document.getElementById('modalInfraChevron');
    var btn = document.getElementById('modalInfraToggleBtn');
    var isOpen = panel && panel.style.display !== 'none';
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
    var wrapper = document.getElementById('modalInfraWrapper');
    if (wrapper && !wrapper.contains(e.target)) {
        var panel = document.getElementById('modalInfraDropdownPanel');
        if (panel && panel.style.display !== 'none') {
            panel.style.display = 'none';
            var chevron = document.getElementById('modalInfraChevron');
            var btn = document.getElementById('modalInfraToggleBtn');
            if (chevron) chevron.style.transform = '';
            if (btn) { btn.style.borderColor = '#e5e7eb'; btn.style.background = '#fff'; }
        }
    }
});

function toggleModalInfraCategory(category) {
    var btn = document.querySelector('[data-modal-infra="' + category + '"]');
    if (!btn) return;
    if (modalInfraActive[category]) {
        if (modalInfraLayers[category] && fullscreenComplexesMapInstance) {
            try { fullscreenComplexesMapInstance.geoObjects.remove(modalInfraLayers[category]); } catch(e) {}
        }
        delete modalInfraLayers[category];
        delete modalInfraActive[category];
        btn.style.borderColor = '#e5e7eb'; btn.style.background = '#fff'; btn.style.color = '#374151';
    } else {
        modalInfraActive[category] = true;
        btn.style.borderColor = '#0088CC'; btn.style.background = '#e0f2fe'; btn.style.color = '#0088CC';
        loadModalInfraLayer(category);
    }
}

function loadModalInfraLayer(category) {
    if (!fullscreenComplexesMapInstance || typeof ymaps === 'undefined') return;
    var cfg = modalInfraCfg[category];
    var bounds = fullscreenComplexesMapInstance.getBounds();
    var btn = document.querySelector('[data-modal-infra="' + category + '"]');
    if (btn) btn.style.opacity = '0.5';
    var query = '[out:json][timeout:25][bbox:' + bounds[0][0] + ',' + bounds[0][1] + ',' + bounds[1][0] + ',' + bounds[1][1] + '];(node[' + cfg.tag + '];way[' + cfg.tag + '];);out center 100;';
    var url = 'https://overpass-api.de/api/interpreter?data=' + encodeURIComponent(query);
    fetch(url)
        .then(function(r) { return r.json(); })
        .then(function(data) {
            var col = new ymaps.GeoObjectCollection();
            var iconLayout = cfg.emoji ? createModalInfraIconLayout(cfg.emoji, cfg.color) : null;
            (data.elements || []).forEach(function(el) {
                var lat = el.lat || (el.center && el.center.lat);
                var lon = el.lon || (el.center && el.center.lon);
                if (!lat || !lon) return;
                var name = (el.tags && (el.tags.name || el.tags['name:ru'])) || cfg.label;
                var opts = iconLayout
                    ? { iconLayout: iconLayout, iconShape: { type: 'Circle', coordinates: [0, 0], radius: 16 } }
                    : { preset: 'islands#orangeCircleDotIcon' };
                col.add(new ymaps.Placemark([lat, lon], { hintContent: name }, opts));
            });
            if (modalInfraLayers[category]) { try { fullscreenComplexesMapInstance.geoObjects.remove(modalInfraLayers[category]); } catch(e) {} }
            modalInfraLayers[category] = col;
            fullscreenComplexesMapInstance.geoObjects.add(col);
            if (btn) btn.style.opacity = '1';
            console.log('✅ Modal Overpass: ' + (data.elements||[]).length + ' ' + category);
        })
        .catch(function(e) { console.warn('Modal Overpass error:', e); if (btn) btn.style.opacity = '1'; });
}

// ========== Drawing for Fullscreen Modal (Yandex Maps) ==========
var modalIsDrawing = false;
var modalDrawingPoints = [];
var modalDrawingMarkers = [];
var modalDrawingPolyline = null;
var modalDrawnPolygon = null;
var modalPolygonPoints = null; // stores closed polygon coords after finishModalDrawing

function enableModalDrawing() {
    if (!fullscreenComplexesMapInstance) return;
    modalIsDrawing = true;
    modalDrawingPoints = [];
    modalDrawingMarkers = [];
    if (modalDrawingPolyline) { try { fullscreenComplexesMapInstance.geoObjects.remove(modalDrawingPolyline); } catch(e) {} }
    modalDrawingPolyline = null;

    fullscreenComplexesMapInstance.container.getElement().style.cursor = 'crosshair';
    try { fullscreenComplexesMapInstance.behaviors.get('drag').disable(); } catch(e) {}

    var hint = document.getElementById('modalDrawingHintOverlay');
    var drawBtn = document.getElementById('modalCianDrawBtn');
    var clearBtn = document.getElementById('modalCianClearBtn');
    if (hint) hint.style.display = 'flex';
    if (drawBtn) { drawBtn.style.background = '#0088CC'; drawBtn.style.borderColor = '#006699'; }
    if (clearBtn) clearBtn.style.display = 'flex';

    fullscreenComplexesMapInstance.events.add('click', modalMapClickHandler);
    // Reset hint to step 1
    var hintStep2 = document.getElementById('modalDrawingHintStep');
    var hintText2 = document.getElementById('modalDrawingHintText');
    if (hintStep2) { hintStep2.textContent = '1'; hintStep2.style.background = '#0088CC'; }
    if (hintText2) hintText2.textContent = 'Кликните на карту — поставьте первую точку';
    console.log('🎨 Modal drawing enabled');
}

function modalMapClickHandler(e) {
    if (!modalIsDrawing) return;
    var coords = e.get('coords');

    // Check if closing polygon BEFORE adding the point (matches properties map behaviour)
    if (modalDrawingPoints.length >= 3) {
        var first = modalDrawingPoints[0];
        var dist = Math.sqrt(Math.pow(coords[0]-first[0],2)+Math.pow(coords[1]-first[1],2));
        if (dist < 0.0005) { // ~50m — same threshold as properties map
            finishModalDrawing();
            return;
        }
    }

    modalDrawingPoints.push(coords);

    // Update drawing hint text dynamically
    (function() {
        var hintText = document.getElementById('modalDrawingHintText');
        var hintStep = document.getElementById('modalDrawingHintStep');
        var n = modalDrawingPoints.length;
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

    var isFirst = modalDrawingPoints.length === 1;
    var marker = new ymaps.Placemark(coords, {}, {
        preset: isFirst ? 'islands#greenCircleDotIcon' : 'islands#orangeCircleDotIcon'
    });
    fullscreenComplexesMapInstance.geoObjects.add(marker);
    modalDrawingMarkers.push(marker);

    // Add click handler on the FIRST (green) marker to close the polygon — same as properties map
    if (isFirst) {
        marker.events.add('click', function(ev) {
            if (ev && ev.stopPropagation) ev.stopPropagation();
            if (modalDrawingPoints.length >= 3) {
                finishModalDrawing();
            }
        });
    }

    if (modalDrawingPolyline) { try { fullscreenComplexesMapInstance.geoObjects.remove(modalDrawingPolyline); } catch(e) {} }
    if (modalDrawingPoints.length >= 2) {
        modalDrawingPolyline = new ymaps.Polyline(modalDrawingPoints, {}, { strokeColor: '#ff6b35', strokeWidth: 2, strokeStyle: 'dash' });
        fullscreenComplexesMapInstance.geoObjects.add(modalDrawingPolyline);
    }
}

function finishModalDrawing() {
    if (modalDrawingPoints.length < 3) return;
    modalIsDrawing = false;
    fullscreenComplexesMapInstance.events.remove('click', modalMapClickHandler);
    fullscreenComplexesMapInstance.container.getElement().style.cursor = 'grab';
    try { fullscreenComplexesMapInstance.behaviors.get('drag').enable(); } catch(e) {}

    modalDrawingMarkers.forEach(function(m) { try { fullscreenComplexesMapInstance.geoObjects.remove(m); } catch(e) {} });
    modalDrawingMarkers = [];
    if (modalDrawingPolyline) { try { fullscreenComplexesMapInstance.geoObjects.remove(modalDrawingPolyline); } catch(e) {} modalDrawingPolyline = null; }

    if (modalDrawnPolygon) { try { fullscreenComplexesMapInstance.geoObjects.remove(modalDrawnPolygon); } catch(e) {} }
    var closed = modalDrawingPoints.slice();
    if (closed[0] !== closed[closed.length-1]) closed.push(closed[0]);
    modalDrawnPolygon = new ymaps.Polygon([closed], {}, { fillColor: '#0088CC30', strokeColor: '#0088CC', strokeWidth: 3 });
    fullscreenComplexesMapInstance.geoObjects.add(modalDrawnPolygon);
    modalPolygonPoints = closed; // save for re-filtering on boundschange

    // Filter sidebar complexes by polygon
    filterModalComplexesByPolygon();
}

function clearModalDrawing() {
    modalIsDrawing = false;
    if (fullscreenComplexesMapInstance) {
        fullscreenComplexesMapInstance.events.remove('click', modalMapClickHandler);
        fullscreenComplexesMapInstance.container.getElement().style.cursor = 'grab';
        try { fullscreenComplexesMapInstance.behaviors.get('drag').enable(); } catch(e) {}
    }
    modalDrawingMarkers.forEach(function(m) { try { fullscreenComplexesMapInstance.geoObjects.remove(m); } catch(e) {} });
    modalDrawingMarkers = []; modalDrawingPoints = [];
    if (modalDrawingPolyline) { try { fullscreenComplexesMapInstance.geoObjects.remove(modalDrawingPolyline); } catch(e) {} modalDrawingPolyline = null; }
    if (modalDrawnPolygon) { try { fullscreenComplexesMapInstance.geoObjects.remove(modalDrawnPolygon); } catch(e) {} modalDrawnPolygon = null; }
    modalPolygonPoints = null;

    var hint = document.getElementById('modalDrawingHintOverlay');
    var drawBtn = document.getElementById('modalCianDrawBtn');
    var clearBtn = document.getElementById('modalCianClearBtn');
    if (hint) hint.style.display = 'none';
    if (drawBtn) { drawBtn.style.background = '#fff'; drawBtn.style.borderColor = '#e5e7eb'; }
    if (clearBtn) clearBtn.style.display = 'none';

    // Restore sidebar: show all complexes visible in current bounds
    // Use a short delay so the polygon removal settles before re-filtering
    setTimeout(function() {
        if (!modalDrawnPolygon) { // only if user hasn't immediately redrawn
            if (typeof filterSidebarByBounds === 'function') {
                filterSidebarByBounds();
            } else if (allComplexesData && allComplexesData.length > 0) {
                updateSidebar(allComplexesData);
            }
        }
    }, 50);
}

function _modalPointInPolygon(lat, lng, poly) {
    var inside = false;
    for (var i = 0, j = poly.length - 1; i < poly.length; j = i++) {
        var lat1 = poly[i][0], lng1 = poly[i][1];
        var lat2 = poly[j][0], lng2 = poly[j][1];
        var cross = ((lng1 > lng) !== (lng2 > lng)) &&
            (lat < (lat2 - lat1) * (lng - lng1) / (lng2 - lng1) + lat1);
        if (cross) inside = !inside;
    }
    return inside;
}

function filterModalComplexesByPolygon() {
    if (!modalDrawnPolygon || !allComplexesData) return;
    var poly = modalPolygonPoints || modalDrawingPoints;
    if (!poly || poly.length < 3) return;
    var filtered = allComplexesData.filter(function(c) {
        var lat = c.latitude || (c.coordinates && (c.coordinates.lat || c.coordinates[0]));
        var lng = c.longitude || (c.coordinates && (c.coordinates.lng || c.coordinates.lon || c.coordinates[1]));
        if (!lat || !lng) return false;
        return _modalPointInPolygon(lat, lng, poly);
    });
    updateSidebar(filtered);
    document.querySelectorAll('.map-complexes-count').forEach(function(el) { el.textContent = filtered.length; });
    console.log('🎯 Modal polygon (ray-cast): ' + filtered.length + ' complexes in area');
}
