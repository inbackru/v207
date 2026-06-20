// ✅ ФИЛЬТРЫ ДЛЯ СТРАНИЦЫ СВОЙСТВ - AJAX MODE
console.log('🔥 property-filters.js загружается - AJAX MODE...');

// ⚡ Функции открытия/закрытия модального окна фильтров
window.toggleFiltersModal = function() {
    console.log('🔄 toggleFiltersModal called');
    const modal = document.getElementById('filters-modal');
    if (modal) {
        modal.classList.toggle('hidden');
        if (!modal.classList.contains('hidden')) {
            document.body.style.overflow = 'hidden';
            window.updateFilteredCount();
        } else {
            document.body.style.overflow = '';
        }
    }
};

window.openFiltersModal = window.toggleFiltersModal;
window.closeFiltersModal = window.toggleFiltersModal;

// ✅ Получить текущее состояние фильтров
window.getFiltersState = function() {
    const state = {};
    
    // Вспомогательная функция для получения значения из инпутов (приоритет модальным окнам)
    const getValue = (ids) => {
        if (!Array.isArray(ids)) ids = [ids];
        for (const id of ids) {
            const el = document.getElementById(id);
            if (el && el.value && el.value.trim() !== '') {
                console.log(`🎯 getValue found value for ${id}:`, el.value.trim());
                return el.value.trim();
            }
        }
        return null;
    };

    // Text search
    const searchValue = getValue(['modal-search-input', 'property-search', 'property-search-desktop']);
    if (searchValue) state.search = searchValue;
    
    // Property Type
    const propertyTypeRadio = document.querySelector('input[name="property_type"]:checked');
    if (propertyTypeRadio && propertyTypeRadio.value !== 'all') {
        state.property_type = propertyTypeRadio.value;
    }
    
    const getCheckedValues = (selector) => {
        return Array.from(document.querySelectorAll(selector + ':checked')).map(cb => cb.value);
    };

    // Rooms
    const rooms = getCheckedValues('input[data-filter-type="rooms"]');
    if (rooms.length > 0) state.rooms = [...new Set(rooms)];
    
    // Price
    const pMin = getValue(['priceFromModalInput', 'priceFromInput', 'priceFrom']);
    const pMax = getValue(['priceToModalInput', 'priceToInput', 'priceTo']);
    if (pMin) state.price_min = parseFloat(pMin) < 1000 ? Math.round(parseFloat(pMin) * 1000000) : pMin;
    if (pMax) state.price_max = parseFloat(pMax) < 1000 ? Math.round(parseFloat(pMax) * 1000000) : pMax;
    
    // Area
    const aMin = getValue(['areaFromModal', 'quickAreaFrom', 'areaFrom', 'mapAreaFrom']);
    const aMax = getValue(['areaToModal', 'quickAreaTo', 'areaTo', 'mapAreaTo']);
    
    console.log('📐 Area Extraction:', { aMin, aMax });
    
    if (aMin) state.area_min = aMin;
    if (aMax) state.area_max = aMax;
    
    // Floor
    const fMin = getValue(['floorFromModal', 'quickFloorFrom', 'floorFrom']);
    const fMax = getValue(['floorToModal', 'quickFloorTo', 'floorTo']);
    if (fMin) state.floor_min = fMin;
    if (fMax) state.floor_max = fMax;
    
    // Max Floor (building floors)
    const mfMin = getValue(['maxFloorFromModal', 'maxFloorFromDesktop', 'maxFloorFrom']);
    const mfMax = getValue(['maxFloorToModal', 'maxFloorToDesktop', 'maxFloorTo']);
    if (mfMin) state.building_floors_min = mfMin;
    if (mfMax) state.building_floors_max = mfMax;

    // Multi-select
    ['districts', 'developers', 'floor_options', 'completion', 'object_classes', 'renovation', 'features', 'building_types', 'building_released'].forEach(type => {
        const values = getCheckedValues(`input[data-filter-type="${type}"]`);
        if (values.length > 0) state[type] = [...new Set(values)];
    });

    const urlParams = new URLSearchParams(window.location.search);
    const residentialComplex = urlParams.get('residential_complex');
    if (residentialComplex) state.residential_complex = residentialComplex;
    
    const developerName = urlParams.get('developer');
    if (developerName) state.developer = developerName;

    const quarterFilter = urlParams.get('quarter');
    if (quarterFilter) state.quarter = quarterFilter;

    const streetFilter = urlParams.get('street');
    if (streetFilter) state.street = streetFilter;

    // Читаем districts из URL (например ?districts=gorkhutor) — аналогично quarter/street
    const districtFromUrl = urlParams.getAll('districts').filter(Boolean);
    if (districtFromUrl.length) {
        if (state.districts && state.districts.length) {
            state.districts = [...new Set([...state.districts, ...districtFromUrl])];
        } else {
            state.districts = districtFromUrl;
        }
    }
    // Fallback: если districts не нашли — берём из lockedDistrictSlug (SEO-страница)
    if ((!state.districts || !state.districts.length) && window.lockedDistrictSlug) {
        state.districts = [window.lockedDistrictSlug];
    }

    // Также читаем из window.activeFilters (устанавливается при выборе из дропдауна)
    if (window.activeFilters) {
        if (window.activeFilters.residential_complex && !state.residential_complex) {
            state.residential_complex = window.activeFilters.residential_complex;
        }
        if (window.activeFilters.developer && !state.developer) {
            state.developer = window.activeFilters.developer;
        }
    }

    const cityIdMeta = document.querySelector('meta[name="city-id"]');
    if (cityIdMeta) state.city_id = cityIdMeta.content;
    
    return state;
};

// Сильный метод сбора и применения фильтров
window.applyFiltersManual = function() {
    console.log('🚀 Final Filter Application (applyFiltersManual)');
    const filters = window.getFiltersState();
    const params = new URLSearchParams();
    
    Object.entries(filters).forEach(([k, v]) => {
        if (Array.isArray(v)) {
            v.forEach(val => {
                const paramName = k.endsWith('[]') ? k : k + '[]';
                params.append(paramName, val);
            });
        } else if (v !== null && v !== undefined && v !== '') {
            params.append(k, v);
        }
    });

    const finalUrl = `${window.location.pathname}?${params.toString()}`;
    console.log('🚀 Redirecting to:', finalUrl);
    window.location.href = finalUrl;
};

// Основной метод теперь ссылается на усиленный
window.applyFilters = window.applyFiltersManual;

// ═══════════════════════════════════════════════════════════════════
// АКТИВНЫЕ ФИЛЬТРЫ (ЧИПСЫ) — единственный источник истины: URL-параметры
// Метки совпадают с серверным Jinja-рендером один в один
// ═══════════════════════════════════════════════════════════════════
window.updateActiveFiltersDisplay = function() {
    var list = document.getElementById('active-filters-list');
    var container = document.getElementById('active-filters-container');
    var chipRow = document.getElementById('chip-row-desktop');
    if (!list) return;

    var CHIP_S = 'display:inline-flex;align-items:center;gap:4px;padding:5px 12px;' +
                 'background:rgba(0,136,204,0.1);color:#0088CC;font-size:14px;' +
                 'border-radius:999px;font-weight:500;white-space:nowrap;line-height:1.4;' +
                 'vertical-align:middle;margin:2px;';
    var BTN_S  = 'background:none;border:none;cursor:pointer;color:inherit;' +
                 'padding:0;margin-left:4px;display:inline-flex;align-items:center;line-height:1;';
    var X_SVG  = '<svg style="width:14px;height:14px;" fill="none" viewBox="0 0 24 24" ' +
                 'stroke="currentColor" stroke-width="2.5">' +
                 '<path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12"/></svg>';

    function escQ(s) { return String(s).replace(/\\/g,'\\\\').replace(/'/g,"\\'"); }
    function escH(s) { return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;'); }
    function chip(label, key, val) {
        var v = (val !== null && val !== undefined) ? "'"+escQ(val)+"'" : 'null';
        var onclick = "window.removeFilter('"+escQ(key)+"',"+v+")";
        return '<span style="'+CHIP_S+'">'+escH(label)+
               '<button style="'+BTN_S+'" onclick="'+escH(onclick)+'">'+
               X_SVG+'</button></span>';
    }
    function fmt(n) { return n.toFixed(1).replace(/\.0$/, ''); }

    // ── Читаем из URL + DOM (двойной источник истины для live-режима) ─
    var p = new URLSearchParams(window.location.search);

    // URL-геттер (с поддержкой key[] вариантов)
    function fromURL(key) {
        return p.getAll(key).concat(p.getAll(key+'[]')).filter(Boolean);
    }
    // DOM-геттер для checkbox-фильтров
    function fromDOM(type) {
        return Array.from(document.querySelectorAll('input[data-filter-type="'+type+'"]:checked'))
                    .map(function(el){ return el.value; });
    }
    // Приоритет DOM-состоянию: если DOM-элементы есть — верим только им (игнорируем URL)
    // URL-резерв только когда DOM-элементов для этого типа нет вообще
    // Set() убирает дубли от одинаковых чекбоксов в десктопе и мобильном модале
    function getAll(key) {
        var allEls = document.querySelectorAll('input[data-filter-type="'+key+'"]');
        if (allEls.length > 0) {
            return [...new Set(
                Array.from(allEls).filter(function(el){ return el.checked; }).map(function(el){ return el.value; })
            )];
        }
        return fromURL(key);
    }
    // Читаем числовой DOM-инпут (в рублях).
    // DOM-приоритет: если элемент есть в DOM но пуст — возвращаем null (уважаем очистку).
    // URL-резерв только если ни один из DOM-элементов не существует на странице.
    function priceFromInput(ids, urlKey) {
        var hasDomEl = false;
        for (var i=0; i<ids.length; i++) {
            var el = document.getElementById(ids[i]);
            if (el) {
                hasDomEl = true;
                if (el.value && el.value.trim()) {
                    var n = parseFloat(el.value);
                    if (!isNaN(n) && n > 0) return n < 1000 ? String(Math.round(n*1000000)) : String(Math.round(n));
                }
            }
        }
        return hasDomEl ? null : (p.get(urlKey) || null);
    }
    function numFromInput(ids, urlKey) {
        var hasDomEl = false;
        for (var i=0; i<ids.length; i++) {
            var el = document.getElementById(ids[i]);
            if (el) {
                hasDomEl = true;
                if (el.value && el.value.trim() && parseFloat(el.value) > 0) return el.value.trim();
            }
        }
        return hasDomEl ? null : (p.get(urlKey) || null);
    }

    var html = '';

    // ── Комнатность (URL + DOM чекбоксы) ─────────────────────────────
    getAll('rooms').forEach(function(r) {
        html += chip(r === '0' ? 'Студия' : r+'-комн.', 'rooms', r);
    });

    // ── Цена (URL приоритет, затем DOM-инпуты) ────────────────────────
    var sqmMinUrl = p.get('price_sqm_min');
    var sqmMaxUrl = p.get('price_sqm_max');
    if (sqmMinUrl || sqmMaxUrl) {
        var lbl = 'Цена/м²:';
        if (sqmMinUrl) { var sm=parseFloat(sqmMinUrl)/1000; lbl+=' от '+fmt(Math.round(sm))+' тыс/м²'; }
        if (sqmMaxUrl) { var sm2=parseFloat(sqmMaxUrl)/1000; lbl+=' до '+fmt(Math.round(sm2))+' тыс/м²'; }
        html += chip(lbl, 'price', null);
    } else {
        var pMin = priceFromInput(['priceFromInput','priceFromModalInput','priceFrom'], 'price_min');
        var pMax = priceFromInput(['priceToInput','priceToModalInput','priceTo'], 'price_max');
        if (pMin || pMax) {
            var lbl = 'Цена:';
            if (pMin) { var m=parseFloat(pMin); if(m>=1000) m=m/1e6; lbl+=' от '+fmt(m)+' млн'; }
            if (pMax) { var m2=parseFloat(pMax); if(m2>=1000) m2=m2/1e6; lbl+=' до '+fmt(m2)+' млн'; }
            html += chip(lbl, 'price', null);
        }
    }

    // ── Тип объекта (URL + DOM radio) ────────────────────────────────
    var PT = {'apartments':'Квартиры','houses':'Дома','townhouses':'Таунхаусы',
              'penthouses':'Пентхаусы','apartments_commercial':'Апартаменты'};
    var pt = p.get('property_type');
    if (!pt) { var ptEl=document.querySelector('input[name="property_type"]:checked'); if(ptEl&&ptEl.value!=='all') pt=ptEl.value; }
    if (pt && pt !== 'all') html += chip(PT[pt] || pt, 'property_type', null);

    // ── Площадь (URL + DOM) ───────────────────────────────────────────
    var aMin = numFromInput(['areaFrom','quickAreaFrom','areaFromModal'], 'area_min');
    var aMax = numFromInput(['areaTo','quickAreaTo','areaToModal'], 'area_max');
    if (aMin||aMax) {
        var al='Площадь:';
        if(aMin) al+=' от '+aMin+' м²';
        if(aMax) al+=' до '+aMax+' м²';
        html += chip(al, 'area', null);
    }

    // ── Этаж (URL + DOM) ──────────────────────────────────────────────
    var fMin = numFromInput(['floorFrom','floorFromModal'], 'floor_min');
    var fMax = numFromInput(['floorTo','floorToModal'], 'floor_max');
    if (fMin||fMax) {
        var fl='Этаж:';
        if(fMin) fl+=' от '+fMin;
        if(fMax) fl+=' до '+fMax;
        html += chip(fl, 'floor', null);
    }

    // ── Этажей в доме (URL + DOM) ─────────────────────────────────────
    var bMin = numFromInput(['maxFloorFromModal','maxFloorFromDesktop'], 'building_floors_min');
    var bMax = numFromInput(['maxFloorToModal','maxFloorToDesktop'], 'building_floors_max');
    if (bMin||bMax) {
        var bl='Этажей в доме:';
        if(bMin) bl+=' от '+bMin;
        if(bMax) bl+=' до '+bMax;
        html += chip(bl, 'building_floors', null);
    }

    // ── Застройщики (URL + DOM) ───────────────────────────────────────
    getAll('developers').forEach(function(d) {
        html += chip((window.developersMap&&window.developersMap[d])||d, 'developers', d);
    });

    // Застройщик (одиночный)
    var dev=p.get('developer');
    if (dev) html += chip('Застройщик: '+dev, 'developer', null);

    // ЖК
    var rc=p.get('residential_complex');
    if (rc) html += chip('ЖК: '+rc, 'residential_complex', null);

    // ── Отделка (URL + DOM) ───────────────────────────────────────────
    var RN={'no_renovation':'Без отделки','fine_finish':'Чистовая','rough_finish':'Предчистовая',
            'white_box':'White Box','turnkey':'Под ключ','pre_finish':'Предчистовая'};
    getAll('renovation').forEach(function(v){ html += chip(RN[v]||v,'renovation',v); });

    // Срок сдачи (completion)
    getAll('completion').forEach(function(v){ html += chip('Сдача '+v+' г.','completion',v); });

    // Год сдачи (delivery_years)
    [...new Set(fromURL('delivery_years'))].forEach(function(v){ html += chip('Сдача '+v+' г.','delivery_years',v); });

    // ── Вариант этажа (URL + DOM) ─────────────────────────────────────
    var FO={'not_first':'Не первый этаж','not_last':'Не последний этаж',
            'last_only':'Последний этаж','ground_floor':'Первый этаж',
            'last':'Последний этаж','first':'Первый этаж'};
    getAll('floor_options').forEach(function(v){ html += chip(FO[v]||v,'floor_options',v); });

    // ── Класс объекта (URL + DOM) ─────────────────────────────────────
    var OC={'econom':'Эконом','comfort':'Комфорт','comfort_plus':'Комфорт+',
            'business':'Бизнес','elite':'Элит','premium':'Премиум'};
    getAll('object_classes').forEach(function(v){ html += chip(OC[v]||v,'object_classes',v); });

    // ── Статус дома (URL + DOM чекбоксы, value-aware) ──────────────────
    var BR={'true':'Дом сдан','false':'Строится'};
    getAll('building_released').forEach(function(v){ html += chip(BR[v]||v,'building_released',v); });

    // ── Материал стен (building_types) ───────────────────────────────
    var BMAT={'monolith':'Монолит','brick':'Кирпич','panel':'Панель','monolith_brick':'Монолит-кирпич','block':'Блочный','wood':'Деревянный'};
    getAll('building_types').forEach(function(v){ html += chip(BMAT[v]||v,'building_types',v); });

    // ── Особенности (URL + DOM) ───────────────────────────────────────
    var FEAT={'has_parking':'Парковка','has_playground':'Детская площадка',
              'has_gym':'Фитнес','has_pool':'Бассейн',
              'closed_territory':'Закрытая территория','concierge':'Консьерж'};
    getAll('features').forEach(function(v){ html += chip(FEAT[v]||v,'features',v); });

    // ── Санузел (bathroom_type) ───────────────────────────────────────
    var BT = {'combined':'Санузел совмещённый','separate':'Санузел раздельный'};
    getAll('bathroom_type').forEach(function(v){ html += chip(BT[v]||v,'bathroom_type',v); });

    // ── Балкон ────────────────────────────────────────────────────────
    var hasBalcony = getAll('has_balcony');
    if (hasBalcony.indexOf('true') !== -1) html += chip('Есть балкон','has_balcony','true');

    // ── Высота потолков ───────────────────────────────────────────────
    var _chRadio = document.querySelector('input[name="ceiling_height_modal"]:checked');
    var chMin = (_chRadio && _chRadio.value) ? _chRadio.value : (p.get('ceiling_height_min') || null);
    if (chMin) html += chip('Потолки от '+chMin+' м', 'ceiling_height_min', null);

    // ── Площадь кухни ─────────────────────────────────────────────────
    var kMin = numFromInput(['kitchenAreaFromModal'], 'kitchen_area_min');
    var kMax = numFromInput(['kitchenAreaToModal'],   'kitchen_area_max');
    if (kMin||kMax) {
        var kl='Кухня:';
        if(kMin) kl+=' от '+kMin+' м²';
        if(kMax) kl+=' до '+kMax+' м²';
        html += chip(kl, 'kitchen_area', null);
    }

    // Поиск
    var srch=p.get('search');
    if (!srch) { var srchEl=document.getElementById('modal-search-input')||document.getElementById('property-search'); if(srchEl&&srchEl.value.trim()) srch=srchEl.value.trim(); }
    if (srch) html += chip('«'+srch+'»','search',null);

    // ── Районы (URL + DOM + SEO locked) ──────────────────────────────
    var _urlDistsList = [...new Set(fromURL('districts').concat(fromDOM('districts')))];
    // SEO-страница: lockedDistrictSlug — добавляем как нессбрасываемый контекст
    if (window.lockedDistrictSlug && !_urlDistsList.includes(window.lockedDistrictSlug)) {
        _urlDistsList.unshift(window.lockedDistrictSlug);
    }
    _urlDistsList.forEach(function(d) {
        var el=document.querySelector('input[data-filter-type="districts"][value="'+CSS.escape(d)+'"]');
        var name=(el&&(el.getAttribute('data-district-name')||el.getAttribute('data-name')))||(window.districtNamesMap&&window.districtNamesMap[d])||d.replace(/-/g,' ');
        // Locked SEO-район (не в URL) — показываем без кнопки ×
        if (d === window.lockedDistrictSlug && !fromURL('districts').includes(d)) {
            html += '<span style="'+CHIP_S+'">📍 '+escH(name)+'</span>';
        } else {
            html += chip('📍 '+name,'districts',d);
        }
    });
    // ?district= (singular, из строки поиска) — показываем с кнопкой ×
    var _singDistrict = p.get('district');
    if (_singDistrict && !_urlDistsList.some(function(d){ return d.replace(/-/g,' ').toLowerCase()===_singDistrict.toLowerCase(); })) {
        html += chip('📍 '+_singDistrict,'district',null);
    }

    // ── Округ / микрорайон (?quarter=) ────────────────────────────────
    var qrt = p.get('quarter');
    if (qrt) html += chip('📍 ' + qrt, 'quarter', null);

    // ── Рендерим ──────────────────────────────────────────────────────
    list.innerHTML = html;
    var hasChips = list.querySelector('span') !== null;
    var ROW = 'display:flex;flex-wrap:wrap;align-items:center;justify-content:space-between;gap:0.75rem;margin-top:0.5rem;';
    if (chipRow)   chipRow.setAttribute('style', hasChips ? ROW : 'display:none');
    if (container) container.style.display = hasChips ? 'block' : 'none';

    var cnt = list.querySelectorAll('span').length;
    var mobCount = document.getElementById('mob-active-filters-count');
    if (mobCount) mobCount.textContent = cnt;

    var modalChips = document.getElementById('modal-active-chips');
    var modalCount = document.getElementById('modal-selected-count');
    if (modalChips) { modalChips.innerHTML = html; modalChips.style.display = hasChips ? 'flex' : 'none'; }
    if (modalCount) { modalCount.textContent = cnt; modalCount.classList.toggle('hidden', !hasChips); }
};

// ═══════════════════════════════════════════════════════════════════
// removeFilter — обновляет URL, DOM и перезапускает поиск
// ═══════════════════════════════════════════════════════════════════
window.removeFilter = function(key, value) {
    var url = new URL(window.location.href);
    var base = key.replace(/\[\]$/, '');

    // Singular ?district= (Russian name from search bar) — remove it + district_id
    if (base === 'district') {
        url.searchParams.delete('district');
        url.searchParams.delete('district_id');
        history.replaceState({}, '', url.toString());
        window.updateActiveFiltersDisplay();
        if (typeof window.triggerLiveSearch === 'function') window.triggerLiveSearch(0);
        return;
    }

    // Группы: одним кликом убираем min+max
    var GROUPS = {
        price:           ['price_min','price_max','price_sqm_min','price_sqm_max'],
        area:            ['area_min','area_max'],
        floor:           ['floor_min','floor_max'],
        building_floors: ['building_floors_min','building_floors_max'],
        kitchen_area:    ['kitchen_area_min','kitchen_area_max'],
        ceiling_height_min: ['ceiling_height_min']
    };
    if (GROUPS[base]) {
        GROUPS[base].forEach(function(k) {
            url.searchParams.delete(k);
            url.searchParams.delete(k+'[]');
            // Очищаем DOM-инпуты
            var domMap = {
                price_min: ['priceFromInput','priceFromModalInput','priceFromModal','priceFrom'],
                price_max: ['priceToInput','priceToModalInput','priceToModal','priceTo'],
                area_min:  ['areaFromModal','quickAreaFrom','areaFrom'],
                area_max:  ['areaToModal','quickAreaTo','areaTo'],
                floor_min: ['floorFromModal','quickFloorFrom','floorFrom'],
                floor_max: ['floorToModal','quickFloorTo','floorTo'],
                building_floors_min: ['maxFloorFromModal','maxFloorFromDesktop','maxFloorFrom'],
                building_floors_max: ['maxFloorToModal','maxFloorToDesktop','maxFloorTo'],
                kitchen_area_min: ['kitchenAreaFromModal'],
                kitchen_area_max: ['kitchenAreaToModal'],
                ceiling_height_min: ['ceilingHeightModal']
            };
            (domMap[k]||[]).forEach(function(id){ var el=document.getElementById(id); if(el) el.value=''; });
        });
        // Also deactivate ceiling-height fchips
        if (base === 'ceiling_height_min') {
            document.querySelectorAll('#filters-modal .fchip input[name="ceiling_height_modal"]').forEach(function(r){
                r.checked = false;
                var fc = r.closest('.fchip'); if(fc) fc.classList.remove('fchip-active');
            });
        }
        history.replaceState({}, '', url.toString());
        window.updateActiveFiltersDisplay();
        if (typeof window.triggerLiveSearch === 'function') window.triggerLiveSearch(0);
        return;
    }

    if (value !== undefined && value !== null && String(value) !== 'null') {
        // Мульти-значение: убираем конкретный value
        var sv = String(value);
        var existing = url.searchParams.getAll(base).concat(url.searchParams.getAll(base+'[]'));
        url.searchParams.delete(base);
        url.searchParams.delete(base+'[]');
        existing.filter(function(v){ return v !== sv; }).forEach(function(v){ url.searchParams.append(base, v); });
        // Снимаем галочку в DOM и визуальное активное состояние frow/fchip
        document.querySelectorAll('input[data-filter-type="'+base+'"][value="'+CSS.escape(sv)+'"]')
            .forEach(function(el){
                el.checked = false;
                var frow = el.closest('.frow'); if(frow) frow.classList.remove('frow-active');
                var fchip = el.closest('.fchip'); if(fchip) fchip.classList.remove('fchip-active');
            });
    } else {
        // Одиночный: убираем полностью
        url.searchParams.delete(base);
        url.searchParams.delete(base+'[]');
        // Очищаем DOM-инпуты (явные ID для известных одиночных фильтров)
        var SINGLE_DOM = {
            search:              ['modal-search-input','property-search','property-search-desktop'],
            developer:           ['developerInput','developerModal'],
            residential_complex: ['residentialComplexInput','rcInput']
        };
        var ids = SINGLE_DOM[base] || [base, base+'Input', base+'Modal', base+'ModalInput'];
        ids.forEach(function(id){
            var el=document.getElementById(id);
            if (el && !/radio|checkbox/.test(el.type)) el.value='';
        });
        // developer/residential_complex берутся из window.activeFilters в buildLiveParams — чистим, иначе вернутся
        if (window.activeFilters) { try { delete window.activeFilters[base]; } catch(e){} }
        // Сбрасываем radio-кнопки
        document.querySelectorAll('input[name="'+base+'"][value="all"]').forEach(function(el){ el.checked=true; });
        document.querySelectorAll('input[name="'+base+'"]:not([value="all"])').forEach(function(el){ el.checked=false; });
    }

    history.replaceState({}, '', url.toString());
    window.updateActiveFiltersDisplay();
    if (typeof window.triggerLiveSearch === 'function') window.triggerLiveSearch(0);
};


window.updateFilteredCount = function() {
    const filters = window.getFiltersState();
    const params = new URLSearchParams();
    Object.entries(filters).forEach(([k, v]) => {
        if (Array.isArray(v)) v.forEach(val => params.append(k.endsWith('[]') ? k : k+'[]', val));
        else params.append(k, v);
    });

    console.log('📡 Updating count with:', params.toString());
    fetch(`/api/properties/list?${params.toString()}`)
        .then(r => r.json())
        .then(d => {
            const count = d.pagination?.total || 0;
            console.log('✅ Real-time Count:', count);
            
            const countIDs = ['priceFilteredCountDisplay', 'modal-filtered-count', 'roomsFilteredCount', 'filteredResultsCount', 'priceFilteredCount'];
            countIDs.forEach(id => {
                const el = document.getElementById(id);
                if (el) el.textContent = count;
            });
            
            const buttonIDs = ['apply-filters-modal-btn-id', 'apply-advanced-filters-id'];
            buttonIDs.forEach(id => {
                const el = document.getElementById(id);
                if (el) {
                    const span = el.querySelector('span[id]');
                    if (span) span.textContent = count;
                    else el.textContent = `Показать ${count} объектов`;
                }
            });

            document.querySelectorAll('.properties-count-display, .properties-found-count').forEach(el => {
                el.textContent = el.classList.contains('properties-found-count') ? count : `${count} объектов`;
            });
        });
};

// Shortcuts for backward compatibility
window.applyPriceFilterModal = window.applyFilters;
window.applyPriceFilter = window.applyFilters;
window.applyModalFilters = window.applyFilters;
window.applyRoomsFilter = window.applyFilters;
window.updateAdvancedFiltersCounter = window.updateFilteredCount;
window.updateModalFilterCount = window.updateFilteredCount;

window.loadDevelopers = function() {
    const cityMeta = document.querySelector('meta[name="city-id"]');
    const cityId = cityMeta ? cityMeta.content : '1';
    
    fetch(`/api/developers?city_id=${cityId}`)
        .then(r => r.json())
        .then(data => {
            if (!data.developers || !data.developers.length) return;
            
            const urlParams = new URLSearchParams(window.location.search);
            const selectedDevs = urlParams.getAll('developers[]').concat(urlParams.getAll('developers'));
            
            const filterContainerIds = ['developers-advanced-filters', 'developers-mobile-modal', 'developers-modal-panel'];
            window.developersMap = {};
            data.developers.forEach(d => { window.developersMap[String(d.id)] = d.name; });
            
            filterContainerIds.forEach(id => {
                const container = document.getElementById(id);
                if (!container) return;
                container.innerHTML = data.developers.map(d => `
                    <label class="flex items-center hover:bg-gray-50 p-1.5 rounded-lg cursor-pointer">
                        <input type="checkbox" value="${d.id}" data-filter-type="developers" 
                               class="text-[#0088CC] focus:ring-[#0088CC] border-gray-300 rounded"
                               onchange="window.updateFilteredCount();"
                               ${selectedDevs.includes(String(d.id)) ? 'checked' : ''}>
                        <span class="ml-2 text-sm text-gray-700">${d.name}</span>
                    </label>
                `).join('');
            });
            
            const mapContainer = document.getElementById('mapDevelopersList');
            if (mapContainer) {
                mapContainer.innerHTML = data.developers.map(d => `
                    <label class="flex items-center hover:bg-gray-50 p-2 rounded-lg cursor-pointer">
                        <input type="checkbox" value="${d.id}" data-map-filter="developer" 
                               class="text-blue-600 focus:ring-blue-500 border-gray-300 rounded">
                        <span class="ml-2 text-sm text-gray-700">${d.name}</span>
                    </label>
                `).join('');
            }
        })
        .catch(e => console.error('Failed to load developers:', e));
};

document.addEventListener('DOMContentLoaded', () => {
    window.loadDevelopers();
    
    // Initial restoration
    const params = new URLSearchParams(window.location.search);
    params.forEach((v, k) => {
        const clean = k.replace(/\[\]$/, '');
        document.querySelectorAll(`input[data-filter-type="${clean}"][value="${v}"], input[name="${clean}"][value="${v}"]`).forEach(el => el.checked = true);
        
        const ids = [
            clean, clean+'Input', clean+'ModalInput', 
            clean.replace('_min', 'From')+'Input', clean.replace('_max', 'To')+'Input', 
            clean.replace('_min', 'From')+'Modal', clean.replace('_max', 'To')+'Modal',
            clean.replace('building_floors_min', 'maxFloorFromModal'), clean.replace('building_floors_max', 'maxFloorToModal'),
            clean.replace('building_floors_min', 'maxFloorFromDesktop'), clean.replace('building_floors_max', 'maxFloorToDesktop'),
            clean.replace('area_min', 'areaFromModal'), clean.replace('area_max', 'areaToModal'),
            clean.replace('floor_min', 'floorFromModal'), clean.replace('floor_max', 'floorToModal'),
            clean.replace('price_min', 'priceFromInput'), clean.replace('price_max', 'priceToInput')
        ];
        
        ids.forEach(id => {
            const el = document.getElementById(id);
            if (el && !el.type.match(/radio|checkbox/)) {
                el.value = (clean.includes('price') && parseFloat(v) >= 1000) ? (parseFloat(v)/1000000).toFixed(1).replace('.0', '') : v;
            }
        });
    });
    
    setTimeout(() => { window.updateActiveFiltersDisplay(); window.updateFilteredCount(); }, 300);
    
    document.addEventListener('change', (e) => {
        if (e.target.closest('input')) {
            window.updateActiveFiltersDisplay();
            window.updateFilteredCount();
        }
    });
    
    document.addEventListener('input', (e) => {
        if (e.target.closest('input[type="number"], input[type="text"]')) {
            if (window._filterTimer) clearTimeout(window._filterTimer);
            window._filterTimer = setTimeout(function() {
                window.updateActiveFiltersDisplay();
                window.updateFilteredCount();
            }, 400);
        }
    });
});
