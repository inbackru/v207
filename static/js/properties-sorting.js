// ✅ PROPERTIES AJAX SORTING - VERSION 1761505200
console.log('🔥🔥🔥 PROPERTIES-SORTING.JS LOADED - AJAX VERSION 🔥🔥🔥');

// Глобальная функция для AJAX-сортировки
window.sortProperties = function() {
    console.log('🚀 sortProperties() ВЫЗВАН - AJAX MODE');
    
    const sortSelect = document.getElementById('sort-select');
    if (!sortSelect) {
        console.error('❌ #sort-select element not found!');
        return;
    }
    
    const sortBy = sortSelect.value;
    console.log('📊 Sort type selected:', sortBy);
    
    // Показываем индикатор загрузки
    showLoadingIndicator();
    
    // Формируем URL с текущими параметрами фильтров и новой сортировкой
    const currentUrl = new URLSearchParams(window.location.search);
    if (sortBy) {
        currentUrl.set('sort', sortBy);
    } else {
        currentUrl.delete('sort');
    }
    
    // Сбрасываем на первую страницу при изменении сортировки
    currentUrl.set('page', '1');
    if (window.currentCityId && !currentUrl.has('city_id')) {
        currentUrl.set('city_id', window.currentCityId);
    }
    if (window.lockedDistrictId && !currentUrl.has('district_id')) {
        currentUrl.set('district_id', window.lockedDistrictId);
    }
    if (window.lockedDistrictSlug && !currentUrl.has('districts') && !window.lockedDistrictId) {
        currentUrl.append('districts', window.lockedDistrictSlug);
    }
    if (window.seoPageFilters && window.seoPageFilters.delivery_years && !currentUrl.has('delivery_years')) {
        var _dys = Array.isArray(window.seoPageFilters.delivery_years) ? window.seoPageFilters.delivery_years : [window.seoPageFilters.delivery_years];
        _dys.forEach(function(y) { currentUrl.append('delivery_years', y); });
    }
    
    const apiUrl = '/api/properties/list?' + currentUrl.toString();
    console.log('📡 Fetching:', apiUrl);
    
    // AJAX запрос
    fetch(apiUrl)
        .then(response => {
            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }
            return response.json();
        })
        .then(data => {
            console.log('✅ API Response:', data);
            
            if (data.success && data.properties) {
                // Обновляем список объектов
                updatePropertiesList(data.properties);
                
                // Обновляем пагинацию
                updatePagination(data.pagination);
                
                // ✅ КРИТИЧНО: Сбрасываем infinite scroll ДО применения view mode
                if (window.infiniteScrollManager && data.pagination) {
                    window.infiniteScrollManager.reset(data.pagination.page, data.pagination.has_next);
                    console.log('♾️ Infinite scroll reset after sorting to page', data.pagination.page);
                }
                
                // Применяем текущий режим отображения после AJAX обновления
                if (typeof window.currentViewMode !== 'undefined' && window.currentViewMode) {
                    if (window.currentViewMode === 'grid' && typeof window.switchToGridView === 'function') {
                        console.log('🔄 Applying GRID view after AJAX sort');
                        window.switchToGridView();
                    } else if (typeof window.switchToListView === 'function') {
                        console.log('🔄 Applying LIST view after AJAX sort');
                        window.switchToListView();
                    }
                } else {
                    // Default to list view if currentViewMode is not set
                    if (typeof window.switchToListView === 'function') {
                        console.log('🔄 Applying default LIST view after AJAX sort');
                        window.switchToListView();
                    }
                }
                
                // Обновляем URL без перезагрузки
                const newUrl = window.location.pathname + '?' + currentUrl.toString();
                window.history.pushState({}, '', newUrl);
                
                // Скроллим наверх списка
                scrollToPropertiesList();
                
                console.log(`✅ Sorted ${data.properties.length} properties by ${sortBy}`);
            } else{
                console.error('❌ API returned error:', data);
                alert('Ошибка при сортировке. Пожалуйста, попробуйте еще раз.');
            }
            
            hideLoadingIndicator();
        })
        .catch(error => {
            console.error('❌ Fetch error:', error);
            alert('Ошибка загрузки данных. Пожалуйста, перезагрузите страницу.');
            hideLoadingIndicator();
        });
};

// Функция для показа индикатора загрузки
function showLoadingIndicator() {
    const listContainer = document.getElementById('properties-list');
    if (listContainer) {
        listContainer.style.opacity = '0.5';
        listContainer.style.pointerEvents = 'none';
    }
    
    // Добавляем спиннер если его еще нет
    if (!document.getElementById('loading-spinner')) {
        const spinner = document.createElement('div');
        spinner.id = 'loading-spinner';
        spinner.className = 'fixed top-1/2 left-1/2 transform -translate-x-1/2 -translate-y-1/2 z-50';
        spinner.innerHTML = `
            <div class="animate-spin rounded-full h-16 w-16 border-b-4 border-blue-600"></div>
        `;
        document.body.appendChild(spinner);
    }
}

// Функция для скрытия индикатора загрузки
function hideLoadingIndicator() {
    const listContainer = document.getElementById('properties-list');
    if (listContainer) {
        listContainer.style.opacity = '1';
        listContainer.style.pointerEvents = 'auto';
    }
    
    const spinner = document.getElementById('loading-spinner');
    if (spinner) {
        spinner.remove();
    }
}

// Функция для скролла к списку объектов
function scrollToPropertiesList() {
    const listContainer = document.getElementById('properties-list');
    if (listContainer) {
        const offset = 100; // Отступ сверху
        const top = listContainer.getBoundingClientRect().top + window.pageYOffset - offset;
        window.scrollTo({ top: top, behavior: 'smooth' });
    }
}

// Прикрепляем event listener при загрузке
document.addEventListener('DOMContentLoaded', function() {
    console.log('📌 DOMContentLoaded - attaching AJAX sort listener');
    
    const sortSelect = document.getElementById('sort-select');
    if (sortSelect) {
        sortSelect.addEventListener('change', function() {
            console.log('🔄 Sort dropdown changed, calling sortProperties() via AJAX');
            window.sortProperties();
        });
        console.log('✅ AJAX sortProperties event listener attached to #sort-select');
    } else {
        console.error('❌ #sort-select element not found during DOMContentLoaded!');
    }
});

console.log('✅ properties-sorting.js AJAX initialization complete');
