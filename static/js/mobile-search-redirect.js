// ✅ MOBILE SEARCH REDIRECT - Smart room query detection
console.log('📱 Mobile Search Redirect loaded');

window.performSearchFromModal = function(query) {
    if (!query || query.trim() === '') return;
    
    // Сохраняем текущий поисковый запрос для последующего трекинга с результатами
    window.currentSearchQuery = query;
    
    // Закрываем modal
    closeSearchModal();
    
    // 🎯 SMART DETECTION: Распознаем room queries и используем правильные параметры фильтра
    const queryLower = query.toLowerCase().trim();
    let redirectUrl = null;
    
    // Студия
    if (/\bстуди[яюи]\b/.test(queryLower)) {
        redirectUrl = '/properties?rooms=0';
    }
    // 1 комната
    else if (/\b1[\s\-]?к(омн(атная|ат)?)?\b|\bодно[\s\-]?комн/.test(queryLower)) {
        redirectUrl = '/properties?rooms=1';
    }
    // 2 комнаты
    else if (/\b2[\s\-]?к(омн(атная|ат)?)?\b|\bдвух[\s\-]?комн/.test(queryLower)) {
        redirectUrl = '/properties?rooms=2';
    }
    // 3 комнаты
    else if (/\b3[\s\-]?к(омн(атная|ат)?)?\b|\bтр[её]х[\s\-]?комн/.test(queryLower)) {
        redirectUrl = '/properties?rooms=3';
    }
    // 4 комнаты
    else if (/\b4[\s\-]?к(омн(атная|ат)?)?\b|\bчетыр[её]х[\s\-]?комн/.test(queryLower)) {
        redirectUrl = '/properties?rooms=4';
    }
    
    // Если распознали room query - делаем прямой редирект с правильными параметрами
    if (redirectUrl) {
        console.log(`✅ Room query detected: "${query}" → ${redirectUrl}`);
        window.location.href = redirectUrl;
        return;
    }
    
    // Для остальных запросов используем стандартную логику
    // Попытка 1: Ищем поле property-search (страница /properties)
    let mainSearch = document.getElementById('property-search');
    
    // Попытка 2: Если не нашли, ищем hero-search (главная страница)
    if (!mainSearch) {
        mainSearch = document.getElementById('hero-search');
    }
    
    if (mainSearch) {
        // Заполняем найденное поле поиска
        mainSearch.value = query;
        
        // Триггерим событие input для SuperSearch
        const event = new Event('input', { bubbles: true });
        mainSearch.dispatchEvent(event);
        
        // Триггерим Enter для выполнения поиска
        setTimeout(() => {
            const enterEvent = new KeyboardEvent('keypress', {
                key: 'Enter',
                code: 'Enter',
                keyCode: 13,
                which: 13,
                bubbles: true
            });
            mainSearch.dispatchEvent(enterEvent);
        }, 300);
    } else {
        // Для текстовых запросов (названия ЖК, адреса и т.д.) используем параметр q
        window.location.href = `/properties?q=${encodeURIComponent(query)}`;
    }
};

console.log('✅ performSearchFromModal() function registered globally');
