// ОКОНЧАТЕЛЬНОЕ РЕШЕНИЕ для кнопок сравнения с PostgreSQL
console.log('🚀 ЗАГРУЖАЕТСЯ PostgreSQL РЕШЕНИЕ - ВЕРСИЯ с ЖК поддержкой');

// Создаем менеджер сравнения с поддержкой PostgreSQL
class SimpleComparisonManager {
    constructor() {
        this.isManager = this.checkIsManager();
        
        // ✅ ЗАЩИТА ОТ ПОВТОРНЫХ КЛИКОВ
        this.processingProperty = false;
        this.processingComplex = false;
        
        // Для менеджеров НЕ загружаем из localStorage
        if (this.isManager) {
            this.comparisons = [];
            this.complexComparisons = [];
            console.log('Manager detected: Skipping localStorage, will load from API');
        } else {
            this.loadFromStorage();
        }
        
        console.log('📦 PostgreSQL Comparison Manager инициализирован. Менеджер:', this.isManager);
        // ✅ FIX: НЕ вызываем loadFromDatabase() в конструкторе - будет вызван в actualInit()
    }
    
    checkIsManager() {
        // ✅ ИСПРАВЛЕНО: Используем только официальную переменную
        // Убираем проверку несуществующей window.isManager
        const result = Boolean(window.manager_authenticated);
        console.log('🔍 Manager status check (FIXED):', {
            manager_authenticated: window.manager_authenticated,
            result: result
        });
        return result;
    }
    
    // Helper function to get CSRF token from meta tag
    getCSRFToken() {
        const csrfMeta = document.querySelector('meta[name="csrf-token"]');
        if (csrfMeta) {
            return csrfMeta.getAttribute('content');
        }
        
        // Fallback check for other possible CSRF token locations
        const csrfInput = document.querySelector('input[name="csrf_token"]');
        if (csrfInput) {
            return csrfInput.value;
        }
        
        console.warn('CSRF token not found in page');
        return null;
    }
    
    // ✅ НОВЫЙ МЕТОД: Попробовать БД сначала, независимо от isManager флага
    async tryDatabaseFirst() {
        try {
            // Use appropriate endpoint based on user type
            const endpoint = this.isManager ? '/api/manager/comparison/load' : '/api/user/comparison/load';
            const testResponse = await fetch(endpoint);
            if (testResponse.ok) {
                const data = await testResponse.json();
                if (data.success) {
                    console.log('✅ БД доступна для пользователя');
                    return true;
                }
            }
        } catch (error) {
            console.log('ℹ️ БД недоступна, используем localStorage');
        }
        return false;
    }
    
    async loadFromDatabase(updateUI = true) {
        // ⚡ PERFORMANCE: Check if bootstrap data is available (avoids redundant API call)
        if (!this.isManager && window.dashboardBootstrapData && window.dashboardBootstrapLoaded) {
            console.log('⚡ Using bootstrap data for comparisons (skipping API call)');
            const bootstrapComparison = window.dashboardBootstrapData.comparisons;
            this.propertiesIds = bootstrapComparison.properties.map(p => p.id);
            this.complexesIds = bootstrapComparison.complexes.map(c => c.id);
            this.saveToBothStorages();
            console.log(`📦 Loaded from bootstrap: ${this.propertiesIds.length} properties, ${this.complexesIds.length} complexes`);
            if (updateUI) this.updateComparisonButtons();
            this.updateCounter();
            return true;
        }
        
        try {
            console.log('🔍 Загружаем сравнение из PostgreSQL...');
            // Use appropriate endpoint based on user type
            const endpoint = this.isManager ? '/api/manager/comparison/load' : '/api/user/comparison/load';
            console.log('📡 Endpoint:', endpoint, 'isManager:', this.isManager);
            const response = await fetch(endpoint);
            const data = await response.json();
            
            console.log('📦 API Response:', data);
            
            if (data.success) {
                // ✅ ИСПРАВЛЕНО: API возвращает объекты с property_id или простые ID
                const apiProperties = (data.properties || []).map(p => p.property_id || String(p));
                const apiComplexes = (data.complexes || []).map(c => (typeof c === 'object' ? c.complex_id : String(c)));
                
                console.log('✅ Загружено из API - квартиры:', apiProperties.length, 'ЖК:', apiComplexes.length);
                console.log('📋 Property IDs:', apiProperties);
                console.log('📋 Complex IDs:', apiComplexes);
                
                // ✅ НОВОЕ: Проверяем конфликт с localStorage и очищаем при необходимости
                await this.syncWithLocalStorage(apiProperties, apiComplexes);
                
                // Устанавливаем данные API как приоритетные
                this.comparisons = apiProperties;
                this.complexComparisons = apiComplexes;
                
            } else {
                console.log('ℹ️ БД недоступна, используем localStorage fallback');
                this.loadFromStorage();
            }
        } catch (error) {
            console.error('❌ Ошибка загрузки из БД:', error);
            console.log('🔄 Fallback на localStorage');
            this.loadFromStorage(); // Fallback на localStorage
        }
        this.updateCounter();
        // ✅ ИСПРАВЛЕНО: Обновляем UI кнопок после загрузки данных из БД (опционально)
        if (updateUI) {
            this.updateComparisonUI();
        }
    }
    
    // ✅ НОВЫЙ МЕТОД: Синхронизация API данных с localStorage
    async syncWithLocalStorage(apiProperties, apiComplexes) {
        try {
            // Загружаем текущие данные localStorage
            const localProperties = JSON.parse(localStorage.getItem('comparisons') || '[]');
            const localComplexes = JSON.parse(localStorage.getItem('comparison_complexes') || '[]');
            
            // Проверяем конфликты
            const propertiesConflict = JSON.stringify(localProperties.sort()) !== JSON.stringify(apiProperties.sort());
            const complexesConflict = JSON.stringify(localComplexes.sort()) !== JSON.stringify(apiComplexes.sort());
            
            if (propertiesConflict || complexesConflict) {
                console.log('🔄 КОНФЛИКТ ОБНАРУЖЕН! API имеет приоритет над localStorage');
                console.log('📊 localStorage квартиры:', localProperties.length, '→ API квартиры:', apiProperties.length);
                console.log('📊 localStorage ЖК:', localComplexes.length, '→ API ЖК:', apiComplexes.length);
                
                // ✅ ИСПРАВЛЕНИЕ: Принудительно обновляем localStorage данными API
                localStorage.setItem('comparisons', JSON.stringify(apiProperties));
                localStorage.setItem('comparison_complexes', JSON.stringify(apiComplexes));
                
                // Очищаем старые ключи
                localStorage.removeItem('comparison_properties');
                localStorage.removeItem('comparison-data');
                
                console.log('✅ localStorage синхронизирован с API данными');
            } else {
                console.log('✅ localStorage и API данные синхронизированы');
            }
        } catch (error) {
            console.error('❌ Ошибка синхронизации localStorage:', error);
        }
    }
    
    loadFromStorage() {
        try {
            const saved = localStorage.getItem('comparisons');
            this.comparisons = saved ? JSON.parse(saved) : [];
            
            const savedComplexes = localStorage.getItem('comparison_complexes');
            this.complexComparisons = savedComplexes ? JSON.parse(savedComplexes) : [];
            
            console.log('📦 Загружено из localStorage - квартиры:', this.comparisons.length, 'ЖК:', this.complexComparisons.length);
        } catch (e) {
            this.comparisons = [];
            this.complexComparisons = [];
        }
    }
    
    saveToStorage() {
        // Только для обычных пользователей
        if (!this.isManager) {
            try {
                localStorage.setItem('comparisons', JSON.stringify(this.comparisons));
                localStorage.setItem('comparison_complexes', JSON.stringify(this.complexComparisons));
            } catch (e) {
                console.error('Ошибка сохранения в localStorage:', e);
            }
        }
    }
    
    async toggleComparison(propertyId, button) {
        const id = String(propertyId);
        
        // ✅ ЗАЩИТА: Если уже обрабатывается - игнорируем
        if (this.processingProperty) {
            console.log('⚠️ Квартира', id, 'уже обрабатывается, пропускаем клик');
            return;
        }
        
        this.processingProperty = true;
        
        try {
            // ✅ ИСПРАВЛЕНИЕ: Сначала обновляем данные из БД для менеджеров БЕЗ обновления UI
            if (this.isManager) {
                try {
                    await this.loadFromDatabase(false); // false = не обновлять UI
                    console.log('🔄 Данные обновлены из БД перед toggle (без UI)');
                } catch (error) {
                    console.log('⚠️ Не удалось обновить из БД, используем кэш:', error.message);
                }
            }
            
            const index = this.comparisons.indexOf(id);
            console.log('🔍 Проверка квартиры', id, '- найдена в массиве:', index > -1, 'массив:', this.comparisons);
            
            if (index > -1) {
                // Удаляем из сравнения
                let dbSuccess = false;
                try {
                    await this.removePropertyFromDatabase(id);
                    dbSuccess = true;
                    console.log('✅ Квартира удалена из PostgreSQL БД:', id);
                } catch (dbError) {
                    console.log('ℹ️ БД недоступна для удаления, используем localStorage:', dbError.message);
                }
                
                this.comparisons.splice(index, 1);
                console.log('➖ Удален из сравнения:', id);
                this.showNotification('Объект удален из сравнения');
                this.updateButtonState(button, false);
            } else {
                // Добавляем в сравнение
                try {
                    await this.addPropertyToDatabase(id);
                    // ✅ Добавляем только при успешном добавлении в БД
                    this.comparisons.push(id);
                    console.log('✅ Квартира добавлена в PostgreSQL БД:', id);
                    this.showNotification('Объект добавлен в сравнение');
                    this.updateButtonState(button, true);
                } catch (dbError) {
                    // ❌ НЕ добавляем в localStorage при ошибке
                    console.error('❌ Не удалось добавить в сравнение:', dbError.message);
                    this.showNotification(dbError.message || 'Ошибка добавления');
                    return; // Прерываем выполнение
                }
            }
        } catch (error) {
            console.error('❌ Критическая ошибка операции:', error);
            this.showNotification('Ошибка! Попробуйте позже');
        } finally {
            // ✅ ВСЕГДА снимаем флаг блокировки
            this.processingProperty = false;
        }
        
        // ✅ ИСПРАВЛЕНИЕ: НЕ перезагружаем из БД после toggle - локальный массив уже обновлен!
        // Для пользователей - сохранить в localStorage
        if (!this.isManager) {
            this.saveToStorage();
        }
        this.updateCounter();
    }
    
    async addPropertyToDatabase(propertyId) {
        // Use appropriate endpoint based on user type
        const endpoint = this.isManager ? '/api/manager/comparison/property/add' : '/api/user/comparison/property/add';
        const response = await fetch(endpoint, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': this.getCSRFToken()
            },
            body: JSON.stringify({
                property_id: propertyId
            })
        });
        
        const data = await response.json();
        
        if (!response.ok || !data.success) {
            // ✅ Извлекаем понятное сообщение от сервера
            throw new Error(data.message || data.error || `Ошибка ${response.status}`);
        }
        
        console.log('✅ Квартира добавлена в БД:', propertyId);
    }
    
    async removePropertyFromDatabase(propertyId) {
        // Use appropriate endpoint based on user type
        const endpoint = this.isManager ? '/api/manager/comparison/property/remove' : '/api/user/comparison/property/remove';
        const response = await fetch(endpoint, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': this.getCSRFToken()
            },
            body: JSON.stringify({
                property_id: propertyId
            })
        });
        
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }
        
        const data = await response.json();
        if (!data.success) {
            throw new Error(data.error || 'Database error');
        }
        
        console.log('✅ Квартира удалена из БД:', propertyId);
    }
    
    getCSRFToken() {
        // Пытаемся найти CSRF токен на странице
        const csrfMeta = document.querySelector('meta[name="csrf-token"]');
        if (csrfMeta) {
            return csrfMeta.getAttribute('content');
        }
        
        const csrfInput = document.querySelector('input[name="csrf_token"]');
        if (csrfInput) {
            return csrfInput.value;
        }
        
        // Генерируем простой токен если не найден (для compatibility)
        return 'simple-token-' + Date.now();
    }
    
    updateButtonState(button, isActive) {
        if (!button) return;
        
        button.classList.remove('manager-comparison-active', 'user-comparison-active');
        
        button.style.backgroundColor = '';
        button.style.borderColor = '';
        button.style.color = '';
        button.style.boxShadow = '';
        button.style.background = '';
        
        const icon = button.querySelector('i');
        if (icon) {
            icon.style.color = '';
            icon.style.animation = '';
        }
        
        if (isActive) {
            button.classList.remove('bg-white', 'bg-blue-600', 'bg-blue-500');
            button.classList.remove('bg-[#0088CC]/10');
            
            if (icon) {
                icon.classList.remove('text-gray-600', 'text-[#0088CC]');
                icon.classList.add('text-white');
                icon.style.color = '';
            }
            
            const activeClass = this.isManager ? 'manager-comparison-active' : 'user-comparison-active';
            button.classList.add(activeClass);
            
        } else {
            button.classList.remove('bg-blue-600', 'bg-blue-500', 'bg-white');
            button.classList.add('bg-[#0088CC]/10');
            button.style.color = '';
            
            if (icon) {
                icon.classList.remove('text-white', 'text-gray-600');
                icon.className = icon.className.replace(/text-\[.*?\]/g, '');
                icon.style.color = '#0088CC';
            }
        }
    }
    
    async toggleComplexComparison(complexId, button) {
        const id = String(complexId);
        
        // ✅ ЗАЩИТА: Если уже обрабатывается - игнорируем
        if (this.processingComplex) {
            console.log('⚠️ ЖК', id, 'уже обрабатывается, пропускаем клик');
            return;
        }
        
        this.processingComplex = true;
        
        try {
            // ✅ ИСПРАВЛЕНИЕ: Сначала обновляем данные из БД для менеджеров БЕЗ обновления UI
            if (this.isManager) {
                try {
                    await this.loadFromDatabase(false); // false = не обновлять UI
                    console.log('🔄 Данные обновлены из БД перед toggle (без UI)');
                } catch (error) {
                    console.log('⚠️ Не удалось обновить из БД, используем кэш:', error.message);
                }
            }
            
            const index = this.complexComparisons.indexOf(id);
            console.log('🔍 Проверка ЖК', id, '- найден в массиве:', index > -1, 'массив:', this.complexComparisons);
            
            if (index > -1) {
                // Удаляем ЖК из сравнения
                let dbSuccess = false;
                try {
                    await this.removeComplexFromDatabase(id);
                    dbSuccess = true;
                    console.log('✅ ЖК удален из PostgreSQL БД:', id);
                } catch (dbError) {
                    console.log('ℹ️ БД недоступна для удаления, используем localStorage:', dbError.message);
                }
                
                this.complexComparisons.splice(index, 1);
                console.log('➖ ЖК удален из сравнения:', id);
                this.showNotification('ЖК удален из сравнения');
                // ✅ ЗАЩИТА: Обновляем кнопку только если она существует
                if (button) {
                    this.updateButtonState(button, false);
                } else {
                    console.log('ℹ️ Кнопка не найдена, обновление визуального состояния пропущено');
                }
            } else {
                // Добавляем ЖК в сравнение
                try {
                    await this.addComplexToDatabase(id);
                    // ✅ Добавляем только при успешном добавлении в БД
                    this.complexComparisons.push(id);
                    console.log('✅ ЖК добавлен в PostgreSQL БД:', id);
                    this.showNotification('ЖК добавлен в сравнение');
                    // ✅ ЗАЩИТА: Обновляем кнопку только если она существует
                    if (button) {
                        this.updateButtonState(button, true);
                    } else {
                        console.log('ℹ️ Кнопка не найдена, обновление визуального состояния пропущено');
                    }
                } catch (dbError) {
                    // ❌ НЕ добавляем в localStorage при ошибке
                    console.error('❌ Не удалось добавить ЖК в сравнение:', dbError.message);
                    this.showNotification(dbError.message || 'Ошибка добавления');
                    return; // Прерываем выполнение
                }
            }
        } catch (error) {
            console.error('❌ Критическая ошибка операции с ЖК:', error);
            this.showNotification('Ошибка! Попробуйте позже');
        } finally {
            // ✅ ВСЕГДА снимаем флаг блокировки
            this.processingComplex = false;
        }
        
        // ✅ ИСПРАВЛЕНИЕ: НЕ перезагружаем из БД после toggle - локальный массив уже обновлен!
        // Для пользователей - сохранить в localStorage
        if (!this.isManager) {
            this.saveToStorage();
        }
        this.updateCounter();
    }
    
    async addComplexToDatabase(complexId) {
        // ✅ ПОЛУЧАЕМ ПОЛНЫЕ ДАННЫЕ ЖК ИЗ DOM
        const complexData = this.getComplexDataFromDOM(complexId);
        
        // Use appropriate endpoint based on user type
        const endpoint = this.isManager ? '/api/manager/comparison/complex/add' : '/api/user/comparison/complex/add';
        const response = await fetch(endpoint, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': this.getCSRFToken()
            },
            body: JSON.stringify({
                complex_id: complexId,
                complex_name: complexData.name || '',
                developer_name: complexData.developer_name || '',
                district: complexData.district || '',
                min_price: complexData.min_price || 0,
                max_price: complexData.max_price || 0,
                photo: complexData.photo || '',
                buildings_count: complexData.buildings_count || 0,
                apartments_count: complexData.apartments_count || 0,
                completion_date: complexData.completion_date || '',
                status: complexData.status || '',
                complex_class: complexData.complex_class || ''
            })
        });
        
        const data = await response.json();
        
        if (!response.ok || !data.success) {
            // ✅ Извлекаем понятное сообщение от сервера
            throw new Error(data.message || data.error || `Ошибка ${response.status}`);
        }
        
        console.log('✅ ЖК добавлен в БД с данными:', complexId, complexData);
    }
    
    // ✅ ИСПРАВЛЕННЫЙ МЕТОД: Извлекает данные ЖК из DOM элемента
    getComplexDataFromDOM(complexId) {
        console.log('🔍 === ВХОД В getComplexDataFromDOM ===', complexId);
        try {
            // Робастный поиск карточки ЖК
            let complexCard = document.querySelector(`[data-complex-id="${complexId}"]`) || 
                             document.querySelector(`[data-id="${complexId}"]`);
            
            if (!complexCard) {
                console.log('⚠️ Карточка ЖК не найдена для ID:', complexId);
                console.log('🔍 Попробуем поиск по всем карточкам...');
                // Поиск среди всех комплексных карточек
                const allCards = document.querySelectorAll('.complex-card, [class*="complex"]');
                console.log('📦 Найдено карточек:', allCards.length);
                return {};
            }
            
            // Поднимаемся к корневой карточке ЖК
            const card = complexCard.closest('.bg-white') || complexCard.closest('.shadow-lg') || 
                        complexCard.closest('div[class*="rounded"]') || complexCard.parentElement?.parentElement;
            
            if (!card) {
                console.log('⚠️ Корневая карточка не найдена для ID:', complexId);
                return {};
            }
            
            console.log('🔍 Найдена карточка ЖК для анализа:', complexId);
            
            const extractText = (selector) => {
                const element = card.querySelector(selector);
                const text = element ? element.textContent.trim() : '';
                console.log(`📝 Селектор "${selector}": "${text}"`);
                return text;
            };
            
            // ✅ ИСПРАВЛЕННЫЕ СЕЛЕКТОРЫ ПО РЕКОМЕНДАЦИЯМ АРХИТЕКТОРА
            
            // Название ЖК: <h3 class="text-lg font-bold text-gray-900 mb-1">
            const name = extractText('h3.text-lg.font-bold') || 
                         extractText('h3') || 
                         extractText('.text-lg.font-bold') || '';
                         
            // Застройщик: ИСПРАВЛЕНО - сначала по href, потом по цвету
            const developer = extractText('a[href*="/developer/"]') || 
                             extractText('p.text-gray-500.text-sm') || 
                             extractText('a[class*="text-[#0088CC]"]') || '';
                            
            // Район: ИСПРАВЛЕНО - робастные fallbacks для разных HTML структур
            const locationSelectors = [
                'i.fa-map-marker-alt', 'i.fa-location-dot', 
                'i[class*="map"]', 'i[class*="location"]',
                '[class*="location"]', '[class*="map"]'
            ];
            let district = '';
            for (const selector of locationSelectors) {
                const element = card.querySelector(selector);
                if (element) {
                    // Множественные fallback стратегии:
                    // 1. Текст из соседнего span
                    const siblingSpan = element.parentElement?.querySelector('span');
                    if (siblingSpan) district = siblingSpan.textContent.trim();
                    
                    // 2. Текст из родительского элемента (убираем иконку)
                    if (!district && element.parentElement) {
                        const parentText = element.parentElement.textContent.trim();
                        const iconText = element.textContent.trim();
                        district = parentText.replace(iconText, '').trim();
                    }
                    
                    // 3. Следующий текстовый узел
                    if (!district && element.nextSibling) {
                        district = element.nextSibling.textContent?.trim() || '';
                    }
                    
                    if (district) {
                        console.log(`🏠 Найден район с селектором "${selector}": "${district}"`);
                        break;
                    }
                }
            }
            
            // Цены: ИСПРАВЛЕНО - более надежный парсинг
            let min_price = 0, max_price = 0;
            const allPrices = [];
            
            // 1. Основная цена из ценника
            const mainPriceText = extractText('.bg-orange-50') || extractText('[class*="bg-orange"]') || '';
            console.log('💰 Основная цена:', mainPriceText);
            
            // 2. Цены из кнопок квартир
            const roomButtons = card.querySelectorAll('button[data-room-type]');
            roomButtons.forEach(button => {
                const priceText = button.querySelector('.text-\\[\\#0088CC\\]')?.textContent || 
                                 button.querySelector('[class*="text-blue"]')?.textContent || '';
                if (priceText) console.log('💰 Текст кнопки:', priceText);
            });
            
            // 3. ИСПРАВЛЕНО - корректная нормализация цен
            
            // Помощник для нормализации цен
            const normalizePrice = (text, unit) => {
                if (!text) return 0;
                
                // Убираем все кроме цифр, коммы и точек
                let cleanText = text.replace(/[^\d.,]/g, '');
                
                // Если есть единица (млн/тыс), обрабатываем как десятичное число
                if (unit) {
                    // Заменяем комму на точку для десятичного числа
                    cleanText = cleanText.replace(',', '.');
                    let price = parseFloat(cleanText);
                    
                    if (unit === 'млн') price *= 1000000;
                    else if (unit === 'тыс') price *= 1000;
                    
                    return price || 0;
                } else {
                    // Нет единицы - считаем что это рубли, убираем все кроме цифр
                    cleanText = cleanText.replace(/[^\d]/g, '');
                    return parseInt(cleanText) || 0;
                }
            };
            
            // Парсим основную цену
            const mainPriceMatch = mainPriceText.match(/от\s*([\d.,\s]+)\s*(млн|тыс)?/i);
            if (mainPriceMatch) {
                const price = normalizePrice(mainPriceMatch[1], mainPriceMatch[2]);
                if (price > 0) {
                    allPrices.push(price);
                    console.log('💰 Основная цена:', price);
                }
            }
            
            // Парсим цены из кнопок
            roomButtons.forEach(button => {
                const priceText = button.querySelector('.text-\\[\\#0088CC\\]')?.textContent || 
                                 button.querySelector('[class*="text-blue"]')?.textContent || '';
                const priceMatch = priceText.match(/от\s*([\d.,\s]+)\s*(млн|тыс)?/i);
                if (priceMatch) {
                    const price = normalizePrice(priceMatch[1], priceMatch[2]);
                    if (price > 0) {
                        allPrices.push(price);
                        console.log('💰 Цена из кнопки:', price);
                    }
                }
            });
            
            // Fallback: поиск по всему тексту только если ничего не нашли
            if (allPrices.length === 0) {
                const fullCardText = card.textContent || '';
                const priceMatches = fullCardText.match(/от\s*([\d\s]+)\s*(млн|тыс|₽)?/gi) || [];
                
                priceMatches.forEach(match => {
                    const numMatch = match.match(/от\s*([\d\s]+)\s*(млн|тыс|₽)?/i);
                    if (numMatch) {
                        const price = normalizePrice(numMatch[1], numMatch[2]);
                        if (price > 0) {
                            allPrices.push(price);
                            console.log('💰 Fallback цена:', price, 'из', match);
                        }
                    }
                });
            }
            
            if (allPrices.length > 0) {
                min_price = Math.min(...allPrices);
                max_price = Math.max(...allPrices);
            }
            
            // ✅ ДОБАВЛЕНО: Извлечение дополнительных полей ЖК
            
            // Фото: первое изображение из слайдера
            const photoElement = card.querySelector('.complex-slider img') || card.querySelector('img');
            const photo = photoElement ? photoElement.src : '';
            
            // Количество корпусов: из сетки статистики
            let buildings_count = 0;
            const buildingsText = extractText('.grid .font-medium') || card.textContent;
            const buildingsMatch = buildingsText.match(/корпусов?[^\d]*(\d+)/i);
            if (buildingsMatch) {
                buildings_count = parseInt(buildingsMatch[1]) || 0;
            }
            
            // Количество квартир: из сетки статистики  
            let apartments_count = 0;
            const apartmentsText = extractText('.grid .font-medium') || card.textContent;
            const apartmentsMatch = apartmentsText.match(/квартир?[^\d]*(\d+)/i);
            if (apartmentsMatch) {
                apartments_count = parseInt(apartmentsMatch[1]) || 0;
            }
            
            // Срок сдачи: ищем элемент с календарем
            let completion_date = '';
            const calendarSelectors = [
                'i.fa-calendar', 
                'i[class*="calendar"]', 
                '[class*="completion"]'
            ];
            for (const selector of calendarSelectors) {
                const element = card.querySelector(selector);
                if (element) {
                    const parentText = element.parentElement?.textContent.trim() || '';
                    const iconText = element.textContent.trim();
                    completion_date = parentText.replace(iconText, '').trim();
                    if (completion_date) break;
                }
            }
            
            // Статус: из цветных span элементов
            let status = '';
            const statusElement = card.querySelector('.bg-green-50') || 
                                 card.querySelector('.bg-orange-50') ||
                                 card.querySelector('[class*="bg-green"]') ||
                                 card.querySelector('[class*="bg-orange"]');
            if (statusElement) {
                status = statusElement.textContent.trim();
                // Нормализация статуса
                if (status.includes('Готов') || status.includes('Сдан')) {
                    status = 'Сдан';
                } else {
                    status = 'Строится';
                }
            }
            
            // Класс ЖК: из текста карточки
            let complex_class = '';
            // Поиск класса в тексте карточки
            const cardText = card.textContent.toLowerCase();
            if (cardText.includes('бизнес')) {
                complex_class = 'Бизнес';
            } else if (cardText.includes('эконом')) {
                complex_class = 'Эконом';
            } else {
                complex_class = 'Комфорт';  // По умолчанию
            }
            
            // ✅ ИСПРАВЛЕНО: поле developer_name вместо developer для совместимости с ComparisonComplex API
            const result = {
                name: name,
                developer_name: developer,
                district: district,
                min_price: min_price,
                max_price: max_price,
                photo: photo,
                buildings_count: buildings_count,
                apartments_count: apartments_count,
                completion_date: completion_date,
                status: status,
                complex_class: complex_class
            };
            
            console.log('✅ ФИНАЛЬНЫЕ данные ЖК (РАСШИРЕННЫЕ):', complexId, result);
            return result;
            
        } catch (error) {
            console.error('❌ Ошибка извлечения данных ЖК:', error);
            return {};
        }
    }
    
    async removeComplexFromDatabase(complexId) {
        // Use appropriate endpoint based on user type
        const endpoint = this.isManager ? '/api/manager/comparison/complex/remove' : '/api/user/comparison/complex/remove';
        const response = await fetch(endpoint, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': this.getCSRFToken()
            },
            body: JSON.stringify({
                complex_id: complexId
            })
        });
        
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }
        
        const data = await response.json();
        if (!data.success) {
            throw new Error(data.error || 'Database error');
        }
        
        console.log('✅ ЖК удален из БД:', complexId);
    }
    
    updateCounter() {
        // Обновляем счетчик в верхнем меню
        const counter = document.querySelector('#comparison-counter');
        const totalCount = this.comparisons.length + this.complexComparisons.length;
        if (counter) {
            counter.textContent = totalCount;
            counter.style.display = totalCount > 0 ? 'inline' : 'none';
        }
        console.log('🔢 Счетчик обновлен:', totalCount, '(квартиры:', this.comparisons.length, 'ЖК:', this.complexComparisons.length, ')');
    }
    
    showNotification(message) {
        if (typeof window.showToast === 'function') {
            window.showToast(message, 'success');
        } else if (typeof window.toastSuccess === 'function') {
            window.toastSuccess(message);
        }
    }
}

// Инициализация НЕМЕДЛЕННО при загрузке скрипта
console.log('🔧 НЕМЕДЛЕННАЯ инициализация кнопок сравнения');

// Функция безопасной инициализации
function safeInit() {
    if (document.readyState === 'loading') {
        // DOM еще загружается
        document.addEventListener('DOMContentLoaded', actualInit);
    } else {
        // DOM уже загружен
        actualInit();
    }
}

async function actualInit() {
    console.log('🔧 Инициализируем кнопки сравнения...');
    
    // Создаем простой менеджер
    window.simpleComparisonManager = new SimpleComparisonManager();
    
    // ⚡ PERFORMANCE: На дашборде ждём bootstrap вместо отдельного API
    if (window.location.pathname === '/dashboard' && !window.dashboardBootstrapLoaded) {
        console.log('⏳ Comparison: Waiting for bootstrap on dashboard...');
        // Bootstrap сам обновит данные через loadFromDatabase с проверкой кэша
        return;
    }
    
    // ✅ FIX: Ждем загрузки из БД ПЕРЕД инициализацией кнопок
    console.log('⏳ Ожидаем загрузку данных из базы данных...');
    await window.simpleComparisonManager.loadFromDatabase();
    console.log('✅ Данные из БД загружены, инициализируем кнопки...');
    
    // ✅ FIX: Небольшая задержка для обеспечения готовности DOM
    await new Promise(resolve => setTimeout(resolve, 50));
    
    // Инициализируем кнопки ПОСЛЕ загрузки из БД
    initAllComparisonButtons();
    
    // ✅ FIX: Обновляем UI после инициализации кнопок
    window.simpleComparisonManager.updateComparisonUI();
    console.log('✅ Система сравнения полностью готова к работе');
}

window.initializeComparisonButtons = function() {
    console.log('🔄 initializeComparisonButtons called (after AJAX)');
    if (window.simpleComparisonManager) {
        window.simpleComparisonManager.updateComparisonUI();
    }
};

// Запускаем инициализацию
safeInit();

function initAllComparisonButtons() {
    // ОЧИЩАЕМ ВСЕ СТАРЫЕ ОБРАБОТЧИКИ (property buttons)
    document.querySelectorAll('.compare-btn').forEach(btn => {
        const newBtn = btn.cloneNode(true);
        btn.parentNode.replaceChild(newBtn, btn);
    });
    
    // ОЧИЩАЕМ ВСЕ СТАРЫЕ ОБРАБОТЧИКИ (complex buttons)
    document.querySelectorAll('.compare-btn[data-complex-id]').forEach(btn => {
        const newBtn = btn.cloneNode(true);
        btn.parentNode.replaceChild(newBtn, btn);
    });
    
    // ДОБАВЛЯЕМ НОВЫЕ ЧИСТЫЕ ОБРАБОТЧИКИ ДЛЯ КВАРТИР
    const propertyButtons = document.querySelectorAll('.compare-btn');
    console.log(`🏠 Инициализируем ${propertyButtons.length} кнопок сравнения квартир`);
    
    propertyButtons.forEach((btn, index) => {
        const propertyId = btn.getAttribute('data-property-id');
        
        if (propertyId) {
            btn.addEventListener('click', function(e) {
                e.preventDefault();
                
                e.stopPropagation();  // ✅ Останавливаем всплытие к родительской карточке
                console.log(`🚀 КЛИК по кнопке квартиры: ${propertyId}`);
                
                if (window.simpleComparisonManager) {
                    window.simpleComparisonManager.toggleComparison(propertyId, btn);
                }
            });
            
            // Проверяем состояние кнопки
            const isInComparison = window.simpleComparisonManager?.comparisons.includes(String(propertyId));
            if (isInComparison) {
                window.simpleComparisonManager.updateButtonState(btn, true);
            }
            
            console.log(`✅ Кнопка квартиры ${index + 1} готова: ${propertyId}`);
        }
    });
    
    // ДОБАВЛЯЕМ НОВЫЕ ЧИСТЫЕ ОБРАБОТЧИКИ ДЛЯ ЖК
    const complexButtons = document.querySelectorAll('.compare-btn[data-complex-id]');
    console.log(`🏢 Инициализируем ${complexButtons.length} кнопок сравнения ЖК`);
    
    complexButtons.forEach((btn, index) => {
        const complexId = btn.getAttribute('data-complex-id');
        
        if (complexId) {
            btn.addEventListener('click', function(e) {
                e.stopPropagation();  // ✅ Останавливаем всплытие к родительской карточке
                e.preventDefault();
                
                console.log(`🚀 КЛИК по кнопке ЖК: ${complexId}`);
                
                if (window.simpleComparisonManager) {
                    window.simpleComparisonManager.toggleComplexComparison(complexId, btn);
                }
            });
            
            // Проверяем состояние кнопки ЖК
            const isInComparison = window.simpleComparisonManager?.complexComparisons.includes(String(complexId));
            if (isInComparison) {
                window.simpleComparisonManager.updateButtonState(btn, true);
            }
            
            console.log(`✅ Кнопка ЖК ${index + 1} готова: ${complexId}`);
        }
    });
}

// Функция для реинициализации после пагинации  
window.reinitComparisonButtons = function() {
    console.log('🔄 Переинициализация после пагинации');
    setTimeout(() => {
        initAllComparisonButtons();
        // ✅ FIX: Обновляем UI после пагинации
        if (window.simpleComparisonManager) {
            window.simpleComparisonManager.updateComparisonUI();
        }
    }, 200);
};

// ФУНКЦИЯ ДЛЯ ЖК КНОПОК (используется в onclick="addToComplexCompare(id)")
window.addToComplexCompare = function(complexId, button = null) {
    console.log('🏢 ЖК кнопка нажата:', complexId, 'button:', !!button);
    if (!window.simpleComparisonManager) {
        console.error('❌ Менеджер сравнения не готов');
        return;
    }
    
    // ✅ ЗАЩИТА: Ищем кнопку если не передана или undefined
    if (!button) {
        console.log('🔍 Ищем кнопку через querySelector для ID:', complexId);
        button = document.querySelector(`[data-complex-id="${complexId}"]`);
    }
    
    if (button) {
        console.log('🚀 Вызываем PostgreSQL функцию для ЖК:', complexId);
        window.simpleComparisonManager.toggleComplexComparison(complexId, button);
    } else {
        console.error('❌ Кнопка ЖК не найдена для ID:', complexId);
        // ✅ FALLBACK: Попробуем без кнопки
        window.simpleComparisonManager.toggleComplexComparison(complexId, null);
    }
};

// АЛЬТЕРНАТИВНОЕ ИМЯ ДЛЯ СОВМЕСТИМОСТИ
window.addToComplexComparison = window.addToComplexCompare;

// ✅ КРИТИЧНО: Delegated click handler для КВАРТИР (работает после AJAX-загрузки)
document.addEventListener('click', (e) => {
    const btn = e.target.closest('.compare-btn[data-property-id]');
    if (!btn) return;
    
    const propertyId = btn.getAttribute('data-property-id');
    if (propertyId && window.simpleComparisonManager) {
        console.log('🏠 DELEGATED PROPERTY CLICK:', propertyId);
        e.preventDefault();
        e.stopPropagation();
        window.simpleComparisonManager.toggleComparison(propertyId, btn);
    }
});

// ✅ КРИТИЧНО: Добавляем delegated click handler для ЖК
document.addEventListener('click', (e) => {
    const btn = e.target.closest('[data-complex-id][class*="compare"], .complex-compare-btn, .compare-btn[data-complex-id]');
    if (!btn) return;
    
    console.log('🎯 DELEGATED COMPLEX CLICK перехвачен:', btn);
    
    const complexId = btn.dataset.complexId || btn.getAttribute('data-complex-id') || btn.getAttribute('data-id');
    if (complexId && window.simpleComparisonManager) {
        console.log('🚀 Перенаправляем на PostgreSQL систему:', complexId);
        e.preventDefault();
        e.stopPropagation();
        
        window.simpleComparisonManager.toggleComplexComparison(complexId, btn);
    }
});

// ✅ Убедимся что глобальные функции правильно привязаны
window.addToComplexCompare = function(complexId, button = null) {
    console.log('🏢 ГЛОБАЛЬНАЯ ФУНКЦИЯ вызвана:', complexId);
    if (window.simpleComparisonManager) {
        return window.simpleComparisonManager.toggleComplexComparison(complexId, button);
    }
};

window.addToComplexComparison = window.addToComplexCompare;

// ✅ КРИТИЧНО: Добавляем ГЛОБАЛЬНУЮ ФУНКЦИЮ addToComparison для КВАРТИР
window.addToComparison = function(type, id) {
    console.log('🚀 ГЛОБАЛЬНАЯ addToComparison вызвана:', type, id);
    if (!window.simpleComparisonManager) {
        console.error('❌ Менеджер сравнения не готов');
        return;
    }
    
    if (type === 'property') {
        console.log('🏠 Добавляем квартиру в PostgreSQL сравнение:', id);
        return window.simpleComparisonManager.toggleComparison(id, null);
    } else if (type === 'complex') {
        console.log('🏢 Добавляем ЖК в PostgreSQL сравнение:', id);
        return window.simpleComparisonManager.toggleComplexComparison(id, null);
    } else {
        console.error('❌ Неизвестный тип сравнения:', type);
    }
};

// ✅ НОВАЯ ФУНКЦИЯ: Обновляем визуальное состояние кнопок сравнения
SimpleComparisonManager.prototype.updateComparisonUI = function() {
    console.log('🔄 Обновляем UI кнопок сравнения...');
    console.log('📋 Comparison IDs:', this.comparisons);
    console.log('📋 Complex IDs:', this.complexComparisons);
    
    // Обновляем кнопки квартир
    const propertyButtons = document.querySelectorAll('.compare-btn[data-property-id], [data-property-id][class*="compare"]');
    console.log(`🔍 Found ${propertyButtons.length} property comparison buttons on page`);
    
    propertyButtons.forEach((btn, index) => {
        const propertyId = btn.dataset.propertyId || btn.getAttribute('data-property-id');
        if (propertyId) {
            const isInComparison = this.comparisons.includes(String(propertyId));
            console.log(`  Button ${index + 1}: ID=${propertyId}, inComparison=${isInComparison}`);
            this.updateButtonState(btn, isInComparison);
        }
    });
    
    // Обновляем кнопки ЖК 
    const complexButtons = document.querySelectorAll('.compare-btn[data-complex-id], [data-complex-id][class*="compare"]');
    console.log(`🔍 Found ${complexButtons.length} complex comparison buttons on page`);
    
    complexButtons.forEach((btn, index) => {
        const complexId = btn.dataset.complexId || btn.getAttribute('data-complex-id');
        if (complexId) {
            const isInComparison = this.complexComparisons.includes(String(complexId));
            console.log(`  Complex button ${index + 1}: ID=${complexId}, inComparison=${isInComparison}`);
            this.updateButtonState(btn, isInComparison);
        }
    });
    
    console.log('✅ UI кнопок обновлено:', this.comparisons.length, 'квартир +', this.complexComparisons.length, 'ЖК');
};

console.log('🎉 ПРОСТОЕ РЕШЕНИЕ + ГЛОБАЛЬНАЯ addToComparison ЗАГРУЖЕНО УСПЕШНО');