// Manager Comparison Page JavaScript
// External file to bypass CSP inline script restrictions

let comparisonData = [];
let complexComparisonData = [];
let currentTab = 'properties';

// Get CSRF token for API requests
function getCSRFToken() {
    const csrfInput = document.querySelector('input[name="csrf_token"]');
    const csrfMeta = document.querySelector('meta[name="csrf-token"]');
    return (csrfInput && csrfInput.value) || (csrfMeta && csrfMeta.content) || '';
}

// Normalize property data from API to expected comparison table schema
function normalizeProperty(p) {
    if (!p) return null;
    
    return {
        // Property identification
        property_id: p.id || p.inner_id || p.property_id || '',
        
        // Basic property info
        property_name: p.title || p.name || `${(p.rooms == 0 || p.rooms === '0') ? 'Студия' : p.rooms + '-комн'}, ${p.area || ''} м²`,
        property_price: p.price || p.property_price || p.object_price || 0,
        property_type: p.property_type || ((p.rooms == 0 || p.rooms === '0') ? 'Студия' : 'Квартира'),
        
        // Room and area details
        rooms: p.rooms !== undefined ? p.rooms : p.object_rooms || '',
        property_size: p.area !== undefined ? p.area : (p.property_size || p.object_area || 0),
        living_area: p.living_area || p.living_space || '',
        kitchen_area: p.kitchen_area || p.kitchen_space || '',
        
        // Pricing
        price_per_sqm: p.price_per_sqm || (p.property_price && p.property_size && p.property_size > 0 ? Math.round(p.property_price / p.property_size) : (p.price && p.area && p.area > 0 ? Math.round(p.price / p.area) : 0)),
        
        // Location and building info
        complex_name: p.complex_name || p.residential_complex || p.residential_complex_name || '',
        developer_name: p.developer || p.developer_name || 'Не указан',
        floor: p.floor || p.object_min_floor || '',
        total_floors: p.total_floors || p.object_max_floor || '',
        floors_total: p.total_floors || p.object_max_floor || '', // Fixed architect feedback
        district: p.district || p.parsed_district || '',
        address: p.address || p.address_display_name || p.parsed_address || '',
        
        // Additional details
        building_type: p.building_type || p.complex_class || '',
        condition: p.condition || p.finishing || '',
        decoration: p.decoration || p.renovation_type || '',
        balcony: p.balcony || '',
        furniture: p.furniture || '',
        parking: p.parking || '',
        view_from_windows: p.view_from_windows || '',
        ceiling_height: p.ceiling_height || '',
        year_built: p.year_built || p.complex_building_end_build_year || '',
        mortgage_available: p.mortgage_available || (p.green_mortgage_available ? 'Да' : 'Нет'),
        metro_distance: p.metro_distance || p.nearest_metro || '',
        
        // Media and links - handle JSON strings, arrays, and simple URLs  
        property_image: parseImageValue(p.main_image) || parseImageValue(p.photos) || parseImageValue(p.property_image) || 
                       (Array.isArray(p.photos) ? p.photos[0] : null) || '/static/images/no-photo.svg',
        property_url: p.url || p.property_url,
        
        // Metadata
        deal_type: p.deal_type || 'sale',
        added_at: p.added_at || 'Загружено из базы',
        
        // Cashback info
        cashback_rate: p.cashback_rate || 5.0,
        cashback: p.cashback || (p.price ? Math.round(p.price * (p.cashback_rate || 5.0) / 100) : 0)
    };
}

// Normalize comparison property data from database API response
// (ComparisonProperty.to_dict() format)
function normalizeComparisonProperty(p) {
    if (!p) return null;
    
    // Get property price
    const price = p.property_price || p.current_price || 0;
    const area = p.area || p.property_size || 0;
    
    return {
        // Property identification
        property_id: p.property_id || p.id || '',
        
        // Basic property info
        property_name: p.property_name || `${(p.rooms == 0 || p.rooms === '0') ? 'Студия' : p.rooms + '-комн'}, ${area} м²`,
        property_price: price,
        property_type: p.property_type || 'Квартира',
        
        // Room and area details
        rooms: p.rooms !== undefined ? p.rooms : '',
        property_size: area,
        living_area: p.living_area || '',
        kitchen_area: p.kitchen_area || '',
        
        // Pricing
        price_per_sqm: price && area > 0 ? Math.round(price / area) : 0,
        
        // Location and building info
        complex_name: p.complex_name || '',
        developer_name: p.developer_name || 'Не указан',
        floor: p.floor || '',
        total_floors: p.total_floors || '',
        floors_total: p.total_floors || '',
        district: p.district || '',
        address: p.address || '',
        
        // Additional details
        building_type: p.building_type || '',
        building_number: p.building_number || '',
        housing_class: p.housing_class || '',
        condition: p.condition || '',
        decoration: p.decoration || '',
        
        // Media and links
        property_image: p.property_image || '/static/images/no-photo.svg',
        property_url: p.property_url || `/property/${p.property_id}`,
        
        // Metadata
        deal_type: 'sale',
        added_at: p.added_at || 'Загружено из базы',
        
        // Cashback info
        cashback_rate: p.cashback_rate || 5.0,
        cashback: p.cashback || (price ? Math.round(price * (p.cashback_rate || 5.0) / 100) : 0),
        
        // Status flags from live data
        is_sold: p.is_sold || false,
        status_label: p.status_label || ''
    };
}

// Helper function to parse image values (JSON strings, arrays, or simple URLs)
function parseImageValue(value) {
    if (!value) return null;
    
    // If it's already an array, return first element
    if (Array.isArray(value)) return value[0] || null;
    
    // If it's a string that looks like JSON array, try to parse
    if (typeof value === 'string' && value.startsWith('[')) {
        try {
            const parsed = JSON.parse(value);
            return Array.isArray(parsed) && parsed.length > 0 ? parsed[0] : null;
        } catch (e) {
            // If parsing fails, treat as regular URL
            return value !== '/static/images/no-photo.svg' ? value : null;
        }
    }
    
    // Simple URL string
    return value !== '/static/images/no-photo.svg' ? value : null;
}

// Normalize complex data from API to expected comparison table schema
function normalizeComplex(c) {
    if (!c) return null;
    
    return {
        // Complex identification  
        id: c.id || c.complex_id || '',
        
        // Basic complex info
        name: c.name || c.complex_name || c.title || 'ЖК Без названия',
        developer: c.developer || c.developer_name || 'Не указан',
        
        // Location info
        address: c.address || c.full_address || c.location || 'Адрес не указан',
        district: c.district || c.district_name || c.location || 'Район не указан',
        
        // Pricing
        min_price: c.min_price || c.price_from || 0,
        max_price: c.max_price || c.price_to || 0,
        
        // Building details
        buildings_count: c.buildings_count || c.buildings || c.korpus_count || 0,
        apartments_count: c.apartments_count || c.flats_count || c.units_count || 0,
        
        // Construction info
        delivery_date: c.delivery_date || c.completion_date || c.ready_date || 'Не указано',
        status: c.status || c.construction_status || 'Не указано',
        year_built: c.year_built || c.end_build_year || '',
        
        // Additional info
        object_class: c.object_class || c.complex_class || c.class || '',
        housing_class: c.housing_class || c.object_class_display_name || c.object_class || c.complex_class || c.class || 'Не указан',
        cashback_rate: c.cashback_rate || 5.0,
        
        // Media - handle JSON strings, arrays, and simple URLs
        image: parseImageValue(c.image) || parseImageValue(c.main_image) || parseImageValue(c.photo) || 
               (Array.isArray(c.images) ? c.images[0] : null) || '/static/images/no-photo.svg',
        url: c.url || c.link || '',
        
        // Metadata
        notes: c.notes || '',
        recommended_for: c.recommended_for || '',
        created_at: c.created_at || 'Загружено из базы'
    };
}

// Initialize page when DOM is loaded
document.addEventListener('DOMContentLoaded', async function() {
    console.log('🚀 Manager Comparison Page - Initializing from external JS...');
    
    // Load comparison data from database
    await loadComparisonFromStorage();
    
    // Update statistics AFTER data is loaded
    updateStats();
    
    // Attach event listeners to replace onclick handlers
    attachEventListeners();
    
    console.log('✅ Manager Comparison Page - Ready!');
    console.log('📊 Current data:', {
        properties: comparisonData.length,
        complexes: complexComparisonData.length
    });
});

// Attach event listeners to replace inline onclick handlers
function attachEventListeners() {
    // Tab switching
    const propertiesTab = document.getElementById('properties-tab');
    const complexesTab = document.getElementById('complexes-tab');
    
    if (propertiesTab) {
        propertiesTab.addEventListener('click', () => switchTab('properties'));
    }
    if (complexesTab) {
        complexesTab.addEventListener('click', () => switchTab('complexes'));
    }
    
    // Action buttons
    const clearBtn = document.getElementById('clear-comparison-btn');
    const exportBtn = document.getElementById('export-comparison-btn');
    const sendBtn = document.getElementById('send-comparison-btn');
    const saveBtn = document.getElementById('save-template-btn');
    
    if (clearBtn) {
        clearBtn.addEventListener('click', clearComparison);
    }
    if (exportBtn) {
        exportBtn.addEventListener('click', exportComparison);
    }
    if (sendBtn) {
        sendBtn.addEventListener('click', sendComparisonToClient);
    }
    if (saveBtn) {
        saveBtn.addEventListener('click', saveComparisonTemplate);
    }

    // Send Client Form Event Listener
    const sendForm = document.getElementById('sendClientForm');
    if (sendForm) {
        sendForm.addEventListener('submit', function(e) {
            e.preventDefault();
            handleSendClientForm();
        });
        console.log('✅ Send client form event listener attached');
    }

    // Modal close buttons event listeners
    const closeModalBtn = document.getElementById('closeSendClientModalBtn');
    if (closeModalBtn) {
        closeModalBtn.addEventListener('click', closeSendClientModal);
        console.log('✅ Close modal button event listener attached');
    }
    
    const cancelBtn = document.getElementById('cancelSendClientBtn');
    if (cancelBtn) {
        cancelBtn.addEventListener('click', closeSendClientModal);
        console.log('✅ Cancel button event listener attached');
    }

    const mobileClearBtn = document.getElementById('mobile-clear-btn');
    if (mobileClearBtn) {
        mobileClearBtn.addEventListener('click', clearComparison);
    }
    const mobileExportBtn = document.getElementById('mobile-export-btn');
    if (mobileExportBtn) {
        mobileExportBtn.addEventListener('click', exportComparison);
    }
    
    console.log('✅ Event listeners attached to buttons');
}

// Missing functions implementation
function exportComparison() {
    if (comparisonData.length === 0 && complexComparisonData.length === 0) {
        alert('Добавьте объекты для сравнения');
        return;
    }
    window.print();
}

function sendComparisonToClient() {
    if (comparisonData.length === 0 && complexComparisonData.length === 0) {
        console.warn('⚠️ No objects selected for comparison');
        alert('Добавьте объекты для сравнения');
        return;
    }
    
    console.log('📧 Opening send to client modal:', { properties: comparisonData.length, complexes: complexComparisonData.length });
    openSendClientModal();
}

function saveComparisonTemplate() {
    if (comparisonData.length === 0 && complexComparisonData.length === 0) {
        alert('Добавьте объекты для сравнения');
        return;
    }
    
    const templateName = prompt('Введите название шаблона:');
    if (templateName) {
        console.log('💾 Saving template:', templateName, { properties: comparisonData, complexes: complexComparisonData });
        alert('Шаблон сохранен');
    }
}

async function loadComparisonFromStorage() {
    // Load comparison data from database instead of localStorage
    try {
        console.log('🔍 Loading comparison from database...');
        
        const response = await fetch('/api/manager/comparison/load', {
            method: 'GET',
            headers: {
                'Content-Type': 'application/json'
            }
        });
        
        console.log('📡 Response status:', response.status);
        
        if (response.ok) {
            const data = await response.json();
            console.log('📦 Raw API response:', data);
            
            if (data.success) {
                // Clear existing data
                comparisonData = [];
                complexComparisonData = [];
                
                // Load properties from database
                if (data.properties && data.properties.length > 0) {
                    console.log('📋 Found', data.properties.length, 'properties in database');
                    
                    // API returns full property objects, not just IDs
                    // Check if the data is an array of objects or IDs
                    const firstItem = data.properties[0];
                    if (typeof firstItem === 'object' && firstItem !== null) {
                        // Full objects - use directly
                        console.log('🏠 Using full property objects from API');
                        comparisonData = data.properties.map(p => normalizeComparisonProperty(p)).filter(p => p !== null);
                        console.log('✅ Loaded', comparisonData.length, 'properties directly from API response');
                    } else {
                        // Just IDs - need to load full data
                        console.log('🔍 Property IDs to load:', data.properties);
                        await loadPropertiesByIds(data.properties);
                    }
                    console.log('🏠 After loading properties, comparisonData.length:', comparisonData.length);
                } else {
                    console.log('📋 No properties found in database comparison');
                }
                
                // Load complexes from database  
                if (data.complexes && data.complexes.length > 0) {
                    console.log('📋 Found', data.complexes.length, 'complexes in database');
                    console.log('🔍 Complex IDs to load:', data.complexes);
                    
                    // API returns simple array of IDs, not objects
                    await loadComplexesByIds(data.complexes);
                    console.log('🏢 After loading complexes, complexComparisonData.length:', complexComparisonData.length);
                } else {
                    console.log('📋 No complexes found in database comparison');
                }
                
                console.log('✅ Database comparison loaded successfully');
                console.log('📊 Final data count - Properties:', comparisonData.length, 'Complexes:', complexComparisonData.length);
            } else {
                console.error('Failed to load comparison from database:', data.error);
                // Fallback to localStorage migration
                await loadFromLocalStorageAsFallback();
            }
        } else {
            console.error('Failed to load comparison from database, HTTP status:', response.status);
            // Fallback to localStorage migration
            await loadFromLocalStorageAsFallback();
        }
    } catch (error) {
        console.error('Error loading comparison from database:', error);
        // Fallback to localStorage migration
        await loadFromLocalStorageAsFallback();
    }
    
    console.log('🎨 About to render comparison with data:', {
        properties: comparisonData.length,
        complexes: complexComparisonData.length
    });
    renderComparison();
}

// Fallback function to migrate from localStorage to database
async function loadFromLocalStorageAsFallback() {
    console.log('🔄 Falling back to localStorage migration...');
    
    // Read comparison data from localStorage as before
    const storedComparisons = localStorage.getItem('comparisons') || localStorage.getItem('comparison_properties');
    const storedComplexes = localStorage.getItem('comparison_complexes');
    
    console.log('🔍 Migrating from localStorage:', {
        comparisons: storedComparisons,
        complexes: storedComplexes
    });
    
    // Migrate property comparison data
    if (storedComparisons) {
        try {
            const parsed = JSON.parse(storedComparisons);
            if (Array.isArray(parsed) && parsed.length > 0) {
                if (typeof parsed[0] === 'string' || typeof parsed[0] === 'number') {
                    console.log('📋 Found property IDs in localStorage, loading and migrating...');
                    await loadPropertiesByIds(parsed);
                    // Save to database for future use
                    for (const property of comparisonData) {
                        await savePropertyToDatabase(property);
                    }
                }
            }
        } catch (error) {
            console.error('Error migrating properties from localStorage:', error);
            comparisonData = [];
        }
    }
    
    // Migrate complex comparison data
    if (storedComplexes) {
        try {
            const parsed = JSON.parse(storedComplexes);
            if (Array.isArray(parsed) && parsed.length > 0) {
                if (typeof parsed[0] === 'string' || typeof parsed[0] === 'number') {
                    console.log('📋 Found complex IDs in localStorage, loading and migrating...');
                    await loadComplexesByIds(parsed);
                    // Save to database for future use
                    for (const complex of complexComparisonData) {
                        await saveComplexToDatabase(complex);
                    }
                }
            }
        } catch (error) {
            console.error('Error migrating complexes from localStorage:', error);
            complexComparisonData = [];
        }
    }
    
    console.log('🔄 localStorage migration completed');
}

// Function to save property to database
async function savePropertyToDatabase(property) {
    try {
        const response = await fetch('/api/manager/comparison/property/add', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                property_id: property.property_id
            })
        });
        
        if (response.ok) {
            const data = await response.json();
            if (data.success) {
                console.log('✅ Property saved to database:', property.property_id);
            } else {
                console.error('Failed to save property to database:', data.error);
            }
        } else {
            console.error('HTTP error saving property to database:', response.status);
        }
    } catch (error) {
        console.error('Error saving property to database:', error);
    }
}

// Function to save complex to database
async function saveComplexToDatabase(complex) {
    try {
        const response = await fetch('/api/manager/comparison/complex/add', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                complex_id: complex.id,
                complex_name: complex.name,
                developer_name: complex.developer,
                min_price: complex.min_price,
                max_price: complex.max_price,
                district: complex.district,
                photo: complex.photo,
                buildings_count: complex.buildings_count,
                apartments_count: complex.apartments_count,
                completion_date: complex.completion_date,
                status: complex.status,
                complex_class: complex.complex_class
            })
        });
        
        if (response.ok) {
            const data = await response.json();
            if (data.success) {
                console.log('✅ Complex saved to database:', complex.id);
            } else {
                console.error('Failed to save complex to database:', data.error);
            }
        } else {
            console.error('HTTP error saving complex to database:', response.status);
        }
    } catch (error) {
        console.error('Error saving complex to database:', error);
    }
}

async function loadPropertiesByIds(propertyIds) {
    try {
        console.log('📡 Loading properties by IDs:', propertyIds);
        const idsParam = propertyIds.join(',');
        const url = `/api/manager/favorites-properties?ids=${idsParam}`;
        console.log('📡 Request URL:', url);
        
        const response = await fetch(url, {
            credentials: 'same-origin'
        });
        console.log('📡 Properties API Response status:', response.status);
        
        if (response.ok) {
            const data = await response.json();
            console.log('📦 Raw properties response:', data);
            
            const rawProperties = data.properties || [];
            console.log('🏠 Raw properties count:', rawProperties.length);
            
            if (rawProperties.length > 0) {
                console.log('🔍 Sample raw property:', rawProperties[0]);
            }
            
            // Apply normalizeProperty to fix field mapping for comparison table
            comparisonData = rawProperties.map(p => normalizeProperty(p)).filter(p => p !== null);
            console.log('✅ Loaded', comparisonData.length, 'normalized properties from API');
            
            if (comparisonData.length > 0) {
                console.log('🔧 Sample normalized property:', comparisonData[0]);
            }
        } else {
            const errorText = await response.text();
            console.error('Failed to load properties from API. Status:', response.status, 'Error:', errorText);
            comparisonData = [];
        }
    } catch (error) {
        console.error('Error loading properties:', error);
        comparisonData = [];
    }
}

async function loadComplexesByIds(complexIds) {
    try {
        console.log('🏢 Loading complexes by IDs:', complexIds);
        
        // Load each complex data from API endpoint
        const complexPromises = complexIds.map(id => 
            fetch(`/api/complex/${id}`)
                .then(res => res.ok ? res.json() : null)
                .catch(() => null)
        );
        
        const complexesData = await Promise.all(complexPromises);
        const validComplexes = complexesData.filter(c => c !== null);
        
        console.log('✅ Loaded', validComplexes.length, 'complexes from API');
        
        // Convert to normalized format with ALL fields from API
        const normalizedComplexes = validComplexes.map(complex => ({
            id: complex.id,
            name: complex.name,
            developer: complex.developer_name || complex.developer,
            district: complex.district,
            address: complex.address,
            min_price: complex.min_price || complex.price_from,
            max_price: complex.max_price || complex.price_to,
            photo: complex.image,
            buildings_count: complex.buildings_count,
            apartments_count: complex.apartments_count || complex.properties_count,
            completion_date: complex.completion_date,
            status: complex.status,
            object_class: complex.object_class || complex.housing_class || 'Комфорт',
            housing_class: complex.housing_class || complex.object_class || 'Комфорт',
            cashback_rate: complex.cashback_rate || complex.cashback_percent,
            floors_min: complex.floors_min,
            floors_max: complex.floors_max
        }));
        
        complexComparisonData = normalizedComplexes.slice(0, 4); // UI cap
        
        console.log('🔍 Complex data:', complexComparisonData);
        
    } catch (error) {
        console.error('Error loading complexes:', error);
        complexComparisonData = [];
    }
}

function updateComparisonCounter() {
    // ✅ Count from localStorage to reflect ALL saved selections (not display-limited arrays)
    const storedProperties = localStorage.getItem('comparisons') || localStorage.getItem('comparison_properties');
    const storedComplexes = localStorage.getItem('comparison_complexes');
    
    let propertyCount = 0;
    let complexCount = 0;
    
    try {
        if (storedProperties) {
            const parsedProps = JSON.parse(storedProperties);
            propertyCount = Array.isArray(parsedProps) ? parsedProps.length : 0;
        }
        if (storedComplexes) {
            const parsedComplexes = JSON.parse(storedComplexes);
            complexCount = Array.isArray(parsedComplexes) ? parsedComplexes.length : 0;
        }
    } catch (error) {
        console.error('Error parsing localStorage for counter:', error);
    }
    
    const totalItems = propertyCount + complexCount;
    const counterElement = document.getElementById('comparison-count');
    
    if (counterElement) {
        counterElement.textContent = totalItems;
        console.log('🔢 Updated comparison counter from localStorage:', totalItems, `(${propertyCount} properties + ${complexCount} complexes)`);
    }
    
    // Also notify parent window if comparison opened from dashboard
    try {
        if (window.parent && window.parent !== window) {
            window.parent.postMessage({
                type: 'comparison-count-update',
                count: totalItems
            }, '*');
        }
    } catch (e) {
        // Ignore cross-origin errors
    }
}

function updateStats() {
    const countEl = document.getElementById('comparison-count');
    const globalCounterEl = document.getElementById('comparison-counter');
    const avgPriceEl = document.getElementById('average-price');
    const avgAreaEl = document.getElementById('average-area');
    
    // ✅ ИСПОЛЬЗУЕМ ТОЛЬКО ДАННЫЕ ИЗ POSTGRESQL БД
    const totalProperties = comparisonData.length;
    const totalComplexes = complexComparisonData.length;
    const totalItems = totalProperties + totalComplexes;
    
    // ✅ ОТОБРАЖАЕМ СЧЕТЧИК ТЕКУЩЕГО ТАБА (НЕ ОБЩИЙ СЧЕТЧИК)
    if (countEl) {
        if (currentTab === 'properties') {
            countEl.textContent = totalProperties;
        } else {
            countEl.textContent = totalComplexes;
        }
    }
    
    // ✅ ОБНОВЛЯЕМ ГЛОБАЛЬНЫЙ СЧЕТЧИК НАВИГАЦИИ
    if (globalCounterEl) {
        globalCounterEl.textContent = totalItems;
    }
    
    console.log('🔢 Счетчик обновлен:', totalItems, `(квартиры:${totalProperties}, ЖК:${totalComplexes})`);
    
    if (comparisonData.length > 0) {
        // Calculate average price
        const prices = comparisonData.filter(p => p.property_price).map(p => p.property_price);
        const avgPrice = prices.length > 0 ? prices.reduce((a, b) => a + b, 0) / prices.length : 0;
        avgPriceEl.textContent = avgPrice > 0 ? formatPrice(avgPrice) : '-';
        
        // Calculate average area
        const areas = comparisonData.filter(p => p.property_size).map(p => p.property_size);
        const avgArea = areas.length > 0 ? areas.reduce((a, b) => a + b, 0) / areas.length : 0;
        avgAreaEl.textContent = avgArea > 0 ? `${Math.round(avgArea)} м²` : '-';
    } else {
        avgPriceEl.textContent = '-';
        avgAreaEl.textContent = '-';
    }
}

function renderComparison() {
    console.log('🖼️ Rendering comparison tables...');
    console.log('Properties to render:', comparisonData.length);
    
    const emptyDiv = document.getElementById('empty-comparison');
    const tableDiv = document.getElementById('comparison-table');
    
    if (comparisonData.length === 0) {
        if (emptyDiv) emptyDiv.style.display = 'block';
        if (tableDiv) tableDiv.style.display = 'none';
        return;
    }
    
    if (emptyDiv) emptyDiv.style.display = 'none';
    if (tableDiv) tableDiv.style.display = 'block';
    
    // Build comparison table
    const tableBody = document.getElementById('comparison-body');
    if (!tableBody) {
        console.error('❌ Table body not found');
        return;
    }
    
    tableBody.innerHTML = '';
    
    // Define row structure for properties
    const rows = [
        { key: 'property_image', label: 'Фото квартиры', isImage: true },
        { key: 'property_name', label: 'Название', className: 'font-semibold' },
        { key: 'property_price', label: 'Цена', formatter: formatPrice, className: 'text-lg font-bold text-[#0088CC]' },
        { key: 'property_type', label: 'Тип' },
        { key: 'rooms', label: 'Комнат', formatter: (val) => (val == 0 || val === '0') ? 'Студия' : (val || '-') },
        { key: 'property_size', label: 'Общая площадь', formatter: (val) => val && val > 0 ? `${val} м²` : '-' },
        { key: 'building_type', label: 'Класс жилья', formatter: (val) => val || '-' },
        { key: 'price_per_sqm', label: 'Цена за м²', formatter: formatPrice },
        { key: 'complex_name', label: 'ЖК' },
        { key: 'developer_name', label: 'Застройщик' },
        { key: 'floor', label: 'Этаж' },
        { key: 'floors_total', label: 'Этажей в доме' },
        { key: 'address', label: 'Адрес' },
        { key: 'cashback', label: 'Кешбек', formatter: formatPrice, className: 'text-green-600 font-semibold' }
    ];
    
    const maxCashback = Math.max(...comparisonData.slice(0, 4).map(p => p.cashback || 0));
    
    // Create table rows
    rows.forEach(row => {
        const tr = document.createElement('tr');
        tr.className = 'border-b border-gray-200';
        
        // Label column
        const labelTd = document.createElement('td');
        labelTd.className = 'mgr-cmp-label-col px-6 py-4 text-sm font-medium text-gray-900 bg-gray-50';
        labelTd.textContent = row.label;
        tr.appendChild(labelTd);
        
        // Property columns
        comparisonData.slice(0, 4).forEach(property => {
            const td = document.createElement('td');
            td.className = `px-6 py-4 text-sm text-gray-900 ${row.className || ''}`;
            
            if (row.key === 'cashback' && property.cashback && property.cashback === maxCashback && comparisonData.length > 1) {
                td.className += ' bg-green-50';
                td.style.border = '2px solid #10b981';
            }
            
            let value = property[row.key];
            if (row.formatter && value != null) {
                value = row.formatter(value);
            }
            
            // Handle image display for property photos
            const mobLabel = document.createElement('span');
            mobLabel.className = 'mob-label';
            mobLabel.textContent = row.label;
            td.appendChild(mobLabel);

            if (row.isImage && value && value !== '-' && value !== '/static/images/no-photo.svg') {
                const img = document.createElement('img');
                img.src = value;
                img.alt = `Фото ${property.property_name || 'квартиры'}`;
                img.className = 'w-24 h-24 object-cover rounded-lg border border-gray-200 shadow-sm';
                img.loading = 'lazy';
                img.onerror = function() {
                    this.style.display = 'none';
                    const span = document.createElement('span');
                    span.textContent = 'Фото недоступно';
                    span.className = 'text-gray-400 text-xs italic';
                    this.parentNode.appendChild(span);
                };
                td.appendChild(img);
            } else {
                const valSpan = document.createElement('span');
                valSpan.textContent = value == null ? '-' : value;
                td.appendChild(valSpan);
            }
            tr.appendChild(td);
        });
        
        tableBody.appendChild(tr);
    });
    
    // Add remove buttons row
    const removeRow = document.createElement('tr');
    removeRow.className = 'border-b border-gray-200';
    
    const removeLabelTd = document.createElement('td');
    removeLabelTd.className = 'mgr-cmp-label-col px-6 py-4 text-sm font-medium text-gray-900 bg-gray-50';
    removeLabelTd.textContent = 'Действия';
    removeRow.appendChild(removeLabelTd);
    
    comparisonData.slice(0, 4).forEach(property => {
        const td = document.createElement('td');
        td.className = 'px-6 py-4 text-sm text-gray-900';
        
        const removeBtn = document.createElement('button');
        removeBtn.className = 'text-red-600 hover:text-red-900 text-sm';
        removeBtn.textContent = 'Удалить';
        console.log('🔧 Creating delete button for property:', property.property_id);
        removeBtn.onclick = () => {
            console.log('🖱️ Delete button clicked for property:', property.property_id);
            removeFromComparison(property.property_id);
        };
        
        td.appendChild(removeBtn);
        removeRow.appendChild(td);
    });
    
    tableBody.appendChild(removeRow);
    
    console.log('✅ Comparison table rendered successfully');
    updateStats();
}

function formatPrice(price) {
    const formatted = new Intl.NumberFormat('ru-RU', {
        minimumFractionDigits: 0,
        maximumFractionDigits: 0
    }).format(price);
    return `${formatted} ₽`;
}

// Export functions for global access
window.loadComparisonFromStorage = loadComparisonFromStorage;
window.updateComparisonCounter = updateComparisonCounter;
window.updateStats = updateStats;
window.renderComparison = renderComparison;
window.switchTab = switchTab;
window.clearComparison = clearComparison;
window.removeFromComparison = removeFromComparison;

// Global functions for tab switching  
function switchTab(tab) {
    currentTab = tab;
    console.log('🔄 Switching to tab:', tab);
    
    // Update tab buttons
    const propertiesTab = document.getElementById('properties-tab');
    const complexesTab = document.getElementById('complexes-tab');
    
    if (tab === 'properties') {
        if (propertiesTab) propertiesTab.className = 'px-6 py-3 text-sm font-medium text-white bg-[#0088CC] rounded-l-lg';
        if (complexesTab) complexesTab.className = 'px-6 py-3 text-sm font-medium text-gray-700 bg-gray-100 rounded-r-lg hover:bg-gray-200';
        renderComparison();
    } else {
        if (propertiesTab) propertiesTab.className = 'px-6 py-3 text-sm font-medium text-gray-700 bg-gray-100 rounded-l-lg hover:bg-gray-200';
        if (complexesTab) complexesTab.className = 'px-6 py-3 text-sm font-medium text-white bg-[#0088CC] rounded-r-lg';
        renderComplexComparison();
    }
}

async function clearComparison() {
    // Clear ALL comparison data regardless of current tab
    comparisonData = [];
    complexComparisonData = [];
    
    // Clear ALL comparison-specific localStorage keys from all parts of the site
    const comparisonKeys = [
        'comparisons', 
        'comparison_properties', 
        'comparison_complexes',
        'comparison-data',  // Used by complex_functions.js on /properties page
        'complexes'         // Legacy fallback key used by comparison.js
    ];
    
    comparisonKeys.forEach(key => {
        localStorage.removeItem(key);
        localStorage.setItem(key, JSON.stringify([]));
    });
    
    // ✅ CLEAR DATABASE: Clear comparison data from PostgreSQL database
    try {
        console.log('🗑️ Clearing comparison data from database...');
        const response = await fetch('/api/manager/comparison/clear', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            }
        });
        
        if (response.ok) {
            const data = await response.json();
            if (data.success) {
                console.log('✅ Database comparison cleared successfully');
            } else {
                console.error('Failed to clear database comparison:', data.error);
            }
        } else {
            console.error('Failed to clear database comparison, HTTP status:', response.status);
        }
    } catch (error) {
        console.error('Error clearing database comparison:', error);
    }
    
    // Re-render current tab
    if (currentTab === 'properties') {
        renderComparison();
    } else {
        renderComplexComparison();
    }
    
    updateStats();
    console.log('🗑️ FULL CLEAR: All comparison data cleared from memory, localStorage, and database');
    console.log('Cleared keys:', comparisonKeys);
    
    // Show lightweight confirmation (no page refresh needed)
    const clearBtn = document.getElementById('clear-comparison-btn');
    if (clearBtn) {
        const originalText = clearBtn.textContent;
        clearBtn.textContent = '✅ Очищено!';
        clearBtn.disabled = true;
        
        setTimeout(() => {
            clearBtn.textContent = originalText;
            clearBtn.disabled = false;
        }, 2000);
    }
}

async function removeFromComparison(itemId) {
    console.log('🗑️ removeFromComparison called with itemId:', itemId, 'currentTab:', currentTab);
    if (currentTab === 'properties') {
        comparisonData = comparisonData.filter(p => p.property_id !== itemId);
        const ids = comparisonData.map(p => p.property_id);
        localStorage.setItem('comparisons', JSON.stringify(ids));
        localStorage.setItem('comparison_properties', JSON.stringify(ids));
        
        // Sync with database
        try {
            console.log('🔄 Syncing property removal to database:', itemId);
            const response = await fetch('/api/manager/comparison/property/remove', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': getCSRFToken()
                },
                body: JSON.stringify({ property_id: itemId })
            });
            
            if (response.ok) {
                const data = await response.json();
                if (data.success) {
                    console.log('✅ Property removed from database:', itemId);
                } else {
                    console.error('Failed to remove property from database:', data.error);
                }
            } else {
                console.error('HTTP error removing property from database:', response.status);
            }
        } catch (error) {
            console.error('Error removing property from database:', error);
        }
        
        renderComparison();
    } else {
        complexComparisonData = complexComparisonData.filter(c => c.id !== itemId);
        const ids = complexComparisonData.map(c => c.id);
        localStorage.setItem('comparison_complexes', JSON.stringify(ids));
        
        // Sync with database
        try {
            console.log('🔄 Syncing complex removal to database:', itemId);
            const response = await fetch('/api/manager/comparison/complex/remove', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': getCSRFToken()
                },
                body: JSON.stringify({ complex_id: itemId })
            });
            
            if (response.ok) {
                const data = await response.json();
                if (data.success) {
                    console.log('✅ Complex removed from database:', itemId);
                } else {
                    console.error('Failed to remove complex from database:', data.error);
                }
            } else {
                console.error('HTTP error removing complex from database:', response.status);
            }
        } catch (error) {
            console.error('Error removing complex from database:', error);
        }
        
        renderComplexComparison();
    }
    updateStats();
    console.log('🗑️ Removed item:', itemId);
}

function renderComplexComparison() {
    console.log('🏢 Rendering complex comparison...');
    console.log('Complexes to render:', complexComparisonData.length);
    
    const emptyDiv = document.getElementById('empty-comparison');
    const tableDiv = document.getElementById('comparison-table');
    
    if (complexComparisonData.length === 0) {
        if (emptyDiv) emptyDiv.style.display = 'block';
        if (tableDiv) tableDiv.style.display = 'none';
        return;
    }
    
    if (emptyDiv) emptyDiv.style.display = 'none';
    if (tableDiv) tableDiv.style.display = 'block';
    
    // Build comparison table for complexes
    const tableBody = document.getElementById('comparison-body');
    if (!tableBody) {
        console.error('❌ Table body not found');
        return;
    }
    
    tableBody.innerHTML = '';
    
    // Define row structure for complexes
    const complexRows = [
        { key: 'photo', label: 'Фото ЖК', isImage: true },
        { key: 'name', label: 'Название ЖК', className: 'font-semibold' },
        { key: 'developer', label: 'Застройщик' },
        { key: 'address', label: 'Адрес' },
        { key: 'min_price', label: 'Цена от', formatter: formatPrice, className: 'text-lg font-bold text-[#0088CC]' },
        { key: 'max_price', label: 'Цена до', formatter: formatPrice, className: 'text-lg font-bold text-[#0088CC]' },
        { key: 'buildings_count', label: 'Корпусов' },
        { key: 'apartments_count', label: 'Квартир' },
        { key: 'completion_date', label: 'Срок сдачи' },
        { key: 'status', label: 'Статус' },
        { key: 'housing_class', label: 'Класс жилья' },
        { key: 'cashback_rate', label: 'Кешбек', formatter: (val) => val ? `${val}%` : '-' }
    ];
    
    // Create table rows
    complexRows.forEach(row => {
        const tr = document.createElement('tr');
        tr.className = 'border-b border-gray-200';
        
        // Label column
        const labelTd = document.createElement('td');
        labelTd.className = 'mgr-cmp-label-col px-6 py-4 text-sm font-medium text-gray-900 bg-gray-50';
        labelTd.textContent = row.label;
        tr.appendChild(labelTd);
        
        // Complex columns
        complexComparisonData.slice(0, 4).forEach(complex => {
            const td = document.createElement('td');
            td.className = `px-6 py-4 text-sm text-gray-900 ${row.className || ''}`;
            
            const cMobLabel = document.createElement('span');
            cMobLabel.className = 'mob-label';
            cMobLabel.textContent = row.label;
            td.appendChild(cMobLabel);

            if (row.isImage) {
                const img = document.createElement('img');
                const imageUrl = complex[row.key] || '/static/images/no-photo.svg';
                img.src = imageUrl;
                img.alt = `Фото ${complex.name || 'ЖК'}`;
                img.className = 'w-32 h-24 object-cover rounded-lg shadow-sm';
                img.loading = 'lazy';
                img.width = 128;
                img.height = 96;
                img.onerror = function() {
                    this.src = '/static/images/no-photo.svg';
                };
                td.appendChild(img);
            } else {
                let value = complex[row.key];
                if (row.formatter && value != null) {
                    value = row.formatter(value);
                }
                const cValSpan = document.createElement('span');
                cValSpan.textContent = value == null ? '-' : value;
                td.appendChild(cValSpan);
            }
            
            tr.appendChild(td);
        });
        
        tableBody.appendChild(tr);
    });
    
    // Add remove buttons row
    const removeRow = document.createElement('tr');
    removeRow.className = 'border-b border-gray-200';
    
    const removeLabelTd = document.createElement('td');
    removeLabelTd.className = 'mgr-cmp-label-col px-6 py-4 text-sm font-medium text-gray-900 bg-gray-50';
    removeLabelTd.textContent = 'Действия';
    removeRow.appendChild(removeLabelTd);
    
    complexComparisonData.slice(0, 4).forEach(complex => {
        const td = document.createElement('td');
        td.className = 'px-6 py-4 text-sm text-gray-900';
        
        const removeBtn = document.createElement('button');
        removeBtn.className = 'text-red-600 hover:text-red-900 text-sm';
        removeBtn.textContent = 'Удалить';
        console.log('🔧 Creating delete button for complex:', complex.id);
        removeBtn.onclick = () => {
            console.log('🖱️ Delete button clicked for complex:', complex.id);
            removeFromComparison(complex.id);
        };
        
        td.appendChild(removeBtn);
        removeRow.appendChild(td);
    });
    
    tableBody.appendChild(removeRow);
    
    console.log('✅ Complex comparison table rendered successfully');
    updateStats();
}

// Send to Client Modal Functions
function openSendClientModal() {
    const modal = document.getElementById('sendClientModal');
    if (modal) {
        modal.classList.remove('hidden');
        // Focus on recipient name input
        const recipientInput = document.getElementById('recipientName');
        if (recipientInput) {
            setTimeout(() => recipientInput.focus(), 100);
        }
        console.log('📧 Send to client modal opened');
    }
}

function closeSendClientModal() {
    const modal = document.getElementById('sendClientModal');
    if (modal) {
        modal.classList.add('hidden');
        // Reset form
        const form = document.getElementById('sendClientForm');
        if (form) {
            form.reset();
        }
        console.log('📧 Send to client modal closed');
    }
}

function handleSendClientForm() {
    const recipientName = document.getElementById('recipientName').value.trim();
    const messageNotes = document.getElementById('messageNotes').value.trim();
    const hideComplexNames = document.getElementById('hideComplexNames').checked;
    const hideDeveloperNames = document.getElementById('hideDeveloperNames').checked;
    const hideAddresses = document.getElementById('hideAddresses').checked;
    
    if (!recipientName) {
        console.error('❌ Recipient name is required');
        alert('Введите имя получателя');
        return;
    }
    
    console.log('📄 Generating PDF with parameters:', {
        recipient: recipientName,
        notes: messageNotes,
        hideComplex: hideComplexNames,
        hideDeveloper: hideDeveloperNames,
        hideAddress: hideAddresses,
        propertiesCount: comparisonData.length,
        complexesCount: complexComparisonData.length
    });
    
    // Prepare data for PDF generation
    const pdfData = {
        recipient_name: recipientName,
        message_notes: messageNotes,
        hide_complex_names: hideComplexNames,
        hide_developer_names: hideDeveloperNames,
        hide_addresses: hideAddresses,
        properties: comparisonData,
        complexes: complexComparisonData,
        timestamp: new Date().toISOString()
    };
    
    // Send to backend for PDF generation
    generateComparisonPDF(pdfData);
}

async function generateComparisonPDF(pdfData) {
    try {
        console.log('📤 Sending PDF generation request to backend...');
        
        const response = await fetch('/api/manager/generate-comparison-pdf', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Accept': 'text/html, application/pdf'
            },
            credentials: 'same-origin',
            body: JSON.stringify(pdfData)
        });
        
        if (response.ok) {
            // Handle HTML/PDF response (new HTML approach)
            const contentType = response.headers.get('content-type') || '';
            if (contentType.includes('text/html')) {
                // Handle HTML document response
                const htmlContent = await response.text();
                const blob = new Blob([htmlContent], { type: 'text/html;charset=utf-8' });
                const url = window.URL.createObjectURL(blob);
                const link = document.createElement('a');
                link.href = url;
                link.download = `Sravnenie_${pdfData.recipient_name}_${new Date().toISOString().slice(0,10)}.html`;
                document.body.appendChild(link);
                link.click();
                document.body.removeChild(link);
                window.URL.revokeObjectURL(url);
                
                closeSendClientModal();
                console.log('✅ HTML comparison document generated and downloaded successfully');
                alert('✅ Документ сравнения создан и скачан! Откройте HTML файл в браузере.');
            } else if (contentType.includes('application/pdf')) {
                // Legacy PDF support
                const blob = await response.blob();
                const url = window.URL.createObjectURL(blob);
                const link = document.createElement('a');
                link.href = url;
                link.download = `Sravnenie_${pdfData.recipient_name}_${new Date().toISOString().slice(0,10)}.pdf`;
                document.body.appendChild(link);
                link.click();
                document.body.removeChild(link);
                window.URL.revokeObjectURL(url);
                
                closeSendClientModal();
                console.log('✅ PDF generated and downloaded successfully');
                alert('PDF uspeshno sozdan i skachan!');
            } else {
                console.error('❌ Expected HTML/PDF but got:', contentType);
                alert('Ошибка: Неверный формат ответа сервера');
            }
        } else {
            // Handle error response
            const contentType = response.headers.get('content-type') || '';
            if (contentType.includes('application/json')) {
                const errorData = await response.json();
                console.error('❌ PDF generation failed:', errorData);
                alert(`Oshibka sozdaniya PDF: ${errorData.error || 'Neizvestnaya oshibka'}`);
            } else {
                console.error('❌ Server error, non-JSON response');
                alert('Oshibka servera pri sozdanii PDF');
            }
        }
    } catch (error) {
        console.error('❌ Error generating PDF:', error);
        alert('Ошибка при создании PDF документа');
    }
}

// Make modal functions globally available
window.openSendClientModal = openSendClientModal;
window.closeSendClientModal = closeSendClientModal;
window.handleSendClientForm = handleSendClientForm;