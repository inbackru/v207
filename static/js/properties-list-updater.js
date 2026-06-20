// ✅ PROPERTIES LIST DYNAMIC UPDATER - VERSION 1761859200
console.log('📋 PROPERTIES-LIST-UPDATER.JS LOADED');

// ── Контекст города (источники вне «мёртвого» инлайн-блока) ─────────────
// window.currentCityId/citySlug изначально присваиваются внутри большого
// инлайн-скрипта, который не парсится из-за синтаксических ошибок. Берём
// надёжные значения из <meta name="city-id"> и window.citySlug (строка 1587).
(function() {
    if (!window.currentCityId) {
        var _m = document.querySelector('meta[name="city-id"]');
        window.currentCityId = (_m && parseInt(_m.content, 10)) || 1;
    }
})();

// ── Сброс всех фильтров через ЖИВОЙ ПОИСК (без перезагрузки страницы) ────
// Как в ЦИАН/Авито/Яндексе/Zillow: очищаем DOM-инпуты, JS-состояние и URL,
// затем перезапускаем live-search — все объекты города появляются без reload.
// Раньше делали жёсткий редирект, т.к. AJAX-сброс давал 0 результатов из-за
// остаточных значений в URL/DOM; теперь чистим ВСЕ источники состояния.
window.resetAllFilters = function() {
    try {
        // 1) Снимаем все чекбоксы/радио фильтров (rooms, object_classes, renovation, districts, …)
        document.querySelectorAll('input[data-filter-type]').forEach(function(el) {
            if (el.type === 'checkbox' || el.type === 'radio') el.checked = false;
        });
        // Тип объекта → «все»
        var ptAll = document.querySelector('input[name="property_type"][value="all"]');
        if (ptAll) ptAll.checked = true;
        else document.querySelectorAll('input[name="property_type"]').forEach(function(el) { el.checked = false; });
        // Мобильные чипы доп.фильтров — снимаем активную подсветку
        document.querySelectorAll('[data-mob-filter]').forEach(function(el) {
            el.classList.remove('!border-[#0088CC]', '!bg-[#0088CC]', '!text-white');
        });

        // 2) Очищаем текстовые/числовые инпуты (цена, площадь, этаж, поиск)
        ['priceFromInput', 'priceToInput', 'priceFromModalInput', 'priceToModalInput', 'priceFrom', 'priceTo',
         'areaFrom', 'areaTo', 'quickAreaFrom', 'quickAreaTo', 'areaFromModal', 'areaToModal',
         'floorFrom', 'floorTo', 'floorFromModal', 'floorToModal', 'floorFromInput', 'floorToInput',
         'maxFloorFromModal', 'maxFloorToModal', 'maxFloorFromDesktop', 'maxFloorToDesktop', 'maxFloorFrom', 'maxFloorTo',
         'modal-search-input', 'property-search', 'property-search-desktop'
        ].forEach(function(id) { var el = document.getElementById(id); if (el) el.value = ''; });

        // 2.5) Сбрасываем текстовые метки кнопок-дропдаунов в шапке фильтров
        var _priceLabel = document.getElementById('priceFilterText');
        if (_priceLabel) _priceLabel.textContent = 'Цена';
        var _roomsLabel = document.getElementById('roomsFilterText');
        if (_roomsLabel) _roomsLabel.textContent = 'Комнат';
        var _typeLabel = document.getElementById('property-type-label');
        if (_typeLabel) _typeLabel.textContent = 'Все типы';

        // 3) Сбрасываем JS-состояние фильтров
        window.activeFilters = {};
        window.seoPageFilters = {};
        window.lockedDistrictSlug = null;
        window.lockedDistrictId = null;
        window._похожиеLoaded = false;

        // 4) Чистим URL: убираем query И SEO-слаг фильтра, оставляя базовый путь города
        var path = window.location.pathname || '/';
        var parts = path.split('/').filter(Boolean);
        var citySlug = window.citySlug || parts[0] || 'krasnodar';
        var seg = parts[1] || '';
        var basePath = path;
        if (seg.indexOf('novostrojki') === 0) basePath = '/' + citySlug + '/novostrojki';
        else if (seg.indexOf('kvartiry') === 0) basePath = '/' + citySlug + '/kvartiry';
        else if (seg.indexOf('properties') === 0) basePath = '/' + citySlug + '/properties';
        var cityMeta = document.querySelector('meta[name="city-id"]');
        var cid = cityMeta ? cityMeta.content : (new URLSearchParams(window.location.search).get('city_id') || '');
        window.history.replaceState({}, '', basePath + (cid ? '?city_id=' + encodeURIComponent(cid) : ''));

        // 5) Перерисовываем чипы и запускаем живой поиск → все объекты города
        if (typeof window.updateActiveFiltersDisplay === 'function') window.updateActiveFiltersDisplay();
        if (typeof window.applyFilters === 'function') { window.applyFilters(); return; }
        if (typeof window.triggerLiveSearch === 'function') { window.triggerLiveSearch(0); return; }
    } catch (e) {
        console.error('[resetAllFilters] live-сброс не удался, делаем редирект:', e);
    }
    // Фолбэк: если live-search недоступен — жёсткий редирект на чистую страницу
    var p2 = (window.location.pathname || '/').split('/').filter(Boolean);
    var cs = window.citySlug || p2[0] || 'krasnodar';
    var s2 = p2[1] || '';
    window.location.href = s2.indexOf('novostrojki') === 0 ? '/' + cs + '/novostrojki'
        : s2.indexOf('kvartiry') === 0 ? '/' + cs + '/kvartiry'
        : (window.location.pathname || '/');
};

// ── Похожие объекты при пустом результате ───────────────────────────────
// Монотонный счётчик-«поколение» для отмены устаревших запросов (latest-wins).
window._похожиеGen = window._похожиеGen || 0;

window._loadSimilarProps = function(citySlug, force) {
    // Если уже загружено и не форсировано — пропускаем
    if (window._похожиеLoaded && !force) return;
    // Генерируем новый токен — любой старый callback проигнорирует результат
    var myGen = ++window._похожиеGen;

    // Прерываем предыдущий in-flight запрос
    if (window._simPropsCtrl) {
        try { window._simPropsCtrl.abort(); } catch (e) {}
        window._simPropsCtrl = null;
    }

    var outer = document.getElementById('похожие-outer');
    var grid  = document.getElementById('похожие-grid');
    if (!outer || !grid) return;

    // Показываем блок + скелетоны (в стиле основных карточек) на время загрузки
    outer.style.display = 'block';
    grid.className = 'grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3';
    grid.innerHTML = [1, 2, 3, 4, 5, 6, 7, 8].map(function() {
        return '<div class="bg-white rounded-lg overflow-hidden border border-gray-200 shadow-sm animate-pulse">'
            + '<div class="w-full h-[160px] bg-gray-200"></div>'
            + '<div class="p-3 space-y-2">'
            + '<div class="h-3 bg-gray-200 rounded w-1/2"></div>'
            + '<div class="h-4 bg-gray-200 rounded w-3/4"></div>'
            + '<div class="h-5 bg-gray-200 rounded w-1/3 mt-3"></div>'
            + '</div></div>';
    }).join('');

    var cid = window.currentCityId || 1;
    var urlp = new URLSearchParams(window.location.search);
    var sf = window.seoPageFilters || {};
    function _arr(v) { return v == null ? [] : (Array.isArray(v) ? v.map(String) : [String(v)]); }
    function _getAll(k) { return urlp.getAll(k).filter(function(x) { return x !== '' && x != null; }); }

    // ── Параметры активного поиска: URL → SEO-фильтры страницы ───────────
    var fRooms = _getAll('rooms');          if (!fRooms.length) fRooms = _arr(sf.rooms);
    var fReno  = _getAll('renovation');     if (!fReno.length)  fReno  = _arr(sf.renovation);
    var fClass = _getAll('object_classes'); if (!fClass.length) fClass = _arr(sf.object_classes);
    var fDistr = _getAll('districts');
    if (!fDistr.length && window.lockedDistrictSlug) fDistr = [window.lockedDistrictSlug];
    var fDistrId = urlp.get('district_id') || window.lockedDistrictId || '';
    var pMin = parseInt(urlp.get('price_min') || sf.price_min || '', 10); if (isNaN(pMin)) pMin = 0;
    var pMax = parseInt(urlp.get('price_max') || sf.price_max || '', 10); if (isNaN(pMax)) pMax = 0;
    var hasDistrict = !!(fDistr.length || fDistrId);
    var hasPrice = pMin > 0 || pMax > 0;

    // ── История просмотров: персонализируем похожие ───────────────────────
    var _histPrefs = (window.propertyHistory && typeof window.propertyHistory.getPrefs === 'function')
        ? window.propertyHistory.getPrefs(cid) : { hasHistory: false };

    function _build(o) {
        var p = new URLSearchParams();
        p.set('page', '1');
        p.set('per_page', String(o.per_page || 24));
        p.set('sort', o.sort || 'price-asc');
        p.set('city_id', cid);
        (o.rooms || []).forEach(function(r) { p.append('rooms', r); });
        (o.renovation || []).forEach(function(r) { p.append('renovation', r); });
        (o.classes || []).forEach(function(c) { p.append('object_classes', c); });
        (o.districts || []).forEach(function(d) { p.append('districts', d); });
        if (o.districtId) p.set('district_id', o.districtId);
        if (o.price_min) p.set('price_min', String(Math.round(o.price_min)));
        if (o.price_max) p.set('price_max', String(Math.round(o.price_max)));
        return p;
    }

    // ── Целевой ценовой УРОВЕНЬ запроса ──────────────────────────────────
    // «от X» → ориентир чуть ВЫШЕ X (премиум/элит), «до X» → чуть ниже X,
    // диапазон [min,max] → середина. По этому уровню подбираем похожие, не
    // скатываясь к самым дешёвым объектам (главная причина прежней ошибки).
    var target = 0;
    if (pMin > 0 && pMax > 0) target = Math.round((pMin + pMax) / 2);
    else if (pMin > 0) target = Math.round(pMin * 1.1);
    else if (pMax > 0) target = Math.round(pMax * 0.9);

    // Класс объекта по уровню цены, если пользователь не выбрал класс явно.
    // Рыночные медианы: Премиум ~50М, Бизнес ~13М, Комфорт ~8М, Эконом ~7.5М.
    function _inferClasses(t) {
        if (t >= 30000000) return ['Премиум', 'Бизнес'];
        if (t >= 13000000) return ['Бизнес', 'Премиум'];
        if (t >= 9500000)  return ['Бизнес', 'Комфорт'];
        return [];
    }
    var levelClasses = fClass.length ? fClass : _inferClasses(target);

    // Ценовой диапазон с центром в target и допуском tol (доля).
    function _lo(tol) { return target > 0 ? target * (1 - tol) : 0; }
    function _hi(tol) { return target > 0 ? target * (1 + tol) : 0; }

    // ── Умный подбор: от точного совпадения к общему (прогрессивное ослабление) ──
    var attempts = [];
    function _push(params, label, isBare) { attempts.push({ params: params, label: label, isBare: !!isBare }); }

    // Персональный attempt (история просмотров) — только если нет активной цены в фильтре
    if (_histPrefs.hasHistory && !hasPrice && _histPrefs.priceMin && _histPrefs.priceMax) {
        var _hRooms = (_histPrefs.rooms && _histPrefs.rooms.length) ? _histPrefs.rooms : fRooms;
        _push(_build({ rooms: _hRooms, price_min: _histPrefs.priceMin, price_max: _histPrefs.priceMax }),
              'Подобрано на основе ваших просмотров');
    }

    if (hasPrice) {
        // Запрос С ЦЕНОЙ: держимся ценового уровня; пол цены НИКОГДА не опускаем до 0.
        if (fRooms.length && hasDistrict && levelClasses.length) {
            _push(_build({ rooms: fRooms, districts: fDistr, districtId: fDistrId, renovation: fReno,
                           classes: levelClasses, price_min: _lo(0.25), price_max: _hi(0.25) }),
                  'Похожие по параметрам вашего поиска');
        }
        if (fRooms.length && hasDistrict) {
            _push(_build({ rooms: fRooms, districts: fDistr, districtId: fDistrId,
                           price_min: _lo(0.4), price_max: _hi(0.4) }),
                  'Похожие в том же районе и ценовом уровне');
        }
        if (fRooms.length && levelClasses.length) {
            _push(_build({ rooms: fRooms, classes: levelClasses, price_min: _lo(0.5), price_max: _hi(0.5) }),
                  'Похожие по комнатности и классу');
        }
        if (fRooms.length) {
            _push(_build({ rooms: fRooms, price_min: _lo(0.5), price_max: _hi(0.5) }),
                  'Похожие по комнатности и цене');
        }
        if (levelClasses.length) {
            _push(_build({ classes: levelClasses, price_min: _lo(0.6), price_max: _hi(0.6) }),
                  'Объекты того же класса и цены');
        }
        _push(_build({ price_min: _lo(0.6), price_max: _hi(0.6) }),
              'Объекты в близком ценовом уровне');
        // Широкий резерв: высокий пол + сортировка по убыванию — остаёмся в премиум-уровне.
        if (fRooms.length) {
            _push(_build({ rooms: fRooms, price_min: target * 0.4, sort: 'price-desc' }),
                  'Похожие по комнатности');
        }
        // Финальная подстраховка для экстремально дорогого запроса: без пола, по
        // убыванию цены → показываем самые дорогие доступные объекты (элит/бизнес),
        // ближайшие к уровню запроса. Никогда не прячем блок и не падаем к дешёвым.
        _push(_build({ sort: 'price-desc' }),
              'Самые премиальные предложения города', true);
    } else {
        // Запрос БЕЗ ЦЕНЫ: ослабляем по комнатности / району / классу / отделке.
        if (fRooms.length || hasDistrict || fReno.length || fClass.length) {
            _push(_build({ rooms: fRooms, districts: fDistr, districtId: fDistrId, renovation: fReno, classes: fClass }),
                  'Похожие по параметрам вашего поиска');
        }
        if (fRooms.length && hasDistrict) {
            _push(_build({ rooms: fRooms, districts: fDistr, districtId: fDistrId }),
                  'Похожие по комнатности и району');
        }
        if (fRooms.length && fClass.length) {
            _push(_build({ rooms: fRooms, classes: fClass }), 'Похожие по комнатности и классу');
        }
        if (fRooms.length && fReno.length) {
            _push(_build({ rooms: fRooms, renovation: fReno }), 'Похожие по комнатности и отделке');
        }
        if (fRooms.length) {
            _push(_build({ rooms: fRooms }), 'Квартиры с такой же комнатностью');
        }
        if (hasDistrict) {
            _push(_build({ districts: fDistr, districtId: fDistrId }), 'Квартиры в том же районе');
        }
        if (fClass.length) {
            _push(_build({ classes: fClass }), 'Объекты того же класса');
        }
        _push(_build({}), 'Популярные новостройки города', true);
    }

    var myCtrl = (typeof AbortController !== 'undefined') ? new AbortController() : null;
    window._simPropsCtrl = myCtrl;
    var signal = myCtrl ? myCtrl.signal : undefined;

    var MIN_RESULTS = 4;
    var backup = null; // первый осмысленный непустой результат (резерв, если ни один не наберёт MIN_RESULTS)

    // Разнообразие: не более 2 квартир из одного ЖК, чтобы не показывать «6 студий из 1 ЖК»
    function _diversify(props, limit) {
        var seen = {}, out = [], overflow = [];
        for (var i = 0; i < props.length; i++) {
            var p = props[i];
            var key = String(p.residential_complex || p.complex_name || ('id' + p.id)).toLowerCase();
            var n = seen[key] || 0;
            if (n < 2) { seen[key] = n + 1; out.push(p); } else { overflow.push(p); }
            if (out.length >= limit) break;
        }
        for (var j = 0; out.length < limit && j < overflow.length; j++) out.push(overflow[j]);
        return out.slice(0, limit);
    }

    function _hide() {
        if (window._simPropsCtrl === myCtrl) window._simPropsCtrl = null;
        var ow = document.getElementById('похожие-outer'); if (ow) ow.style.display = 'none';
    }

    // Компактная карточка для блока похожих (не использует полный renderPropertyCard,
    // чтобы цена и ипотека не ломали верстку в узкой 4-col сетке)
    function _renderPohozhieCard(p) {
        var price = p.price ? p.price : 0;
        var priceMln = price >= 1000000
            ? (price / 1000000).toLocaleString('ru-RU', { minimumFractionDigits: 1, maximumFractionDigits: 1 }) + '\u00a0млн\u00a0₽'
            : (price > 0 ? Math.round(price / 1000).toLocaleString('ru-RU') + '\u00a0тыс\u00a0₽' : '');

        var mort = p.mortgage_payment ? parseInt(p.mortgage_payment, 10) : 0;
        var mortStr = mort > 0
            ? 'от\u00a0' + Math.round(mort / 1000).toLocaleString('ru-RU') + '\u00a0тыс/мес'
            : '';

        var rooms = p.rooms == 0 ? 'Студия' : (p.rooms ? p.rooms + '-комн.' : '');
        var area  = p.area ? p.area + '\u00a0м²' : '';
        var floor = (p.floor && p.total_floors) ? p.floor + '/' + p.total_floors + '\u00a0эт.' : '';
        var info  = [rooms, area, floor].filter(Boolean).join(', ');

        var complexName = p.complex_name || p.residential_complex || '';
        var imgUrl = (p.gallery && p.gallery.length > 0) ? p.gallery[0] : (p.main_image || p.image || '');
        var cashback = p.cashback ? parseInt(p.cashback, 10) : 0;

        var cs = p.city_slug || window.citySlug || 'krasnodar';
        var href = '/' + cs + '/object/' + p.id;

        var el = document.createElement('a');
        el.href = href;
        el.className = 'block bg-white rounded-xl overflow-hidden border border-gray-100 shadow-sm hover:shadow-md transition-shadow group';
        el.innerHTML =
            '<div class="relative overflow-hidden">' +
                (imgUrl
                    ? '<img src="' + imgUrl + '" alt="' + (complexName || '').replace(/"/g, "'") + '" class="w-full h-36 object-cover group-hover:scale-105 transition-transform duration-300" loading="lazy" onerror="this.style.display=\'none\';this.nextElementSibling.style.display=\'flex\'">'
                      + '<div class="w-full h-36 bg-gray-100 items-center justify-center text-gray-300 hidden"><svg class="w-8 h-8" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z"/></svg></div>'
                    : '<div class="w-full h-36 bg-gray-100 flex items-center justify-center text-gray-300"><svg class="w-8 h-8" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z"/></svg></div>') +
                (cashback > 0
                    ? '<div class="absolute top-2 left-2 bg-white/90 backdrop-blur text-[10px] font-semibold text-gray-700 px-2 py-0.5 rounded-full shadow-sm border border-gray-200/80 truncate max-w-[90%]"><i class="fas fa-tag text-[#0088CC]" style="font-size:8px"></i> Кэшбек до\u00a0' + Math.round(cashback / 1000) + '\u00a0тыс\u00a0₽</div>'
                    : '') +
            '</div>' +
            '<div class="p-3">' +
                (info ? '<p class="text-xs text-gray-500 mb-0.5 truncate">' + info + '</p>' : '') +
                (complexName ? '<p class="text-sm font-semibold text-gray-800 mb-1 line-clamp-1 group-hover:text-[#0088CC] transition-colors">' + complexName + '</p>' : '') +
                (priceMln ? '<p class="text-[#0088CC] font-bold text-sm leading-tight whitespace-nowrap">от\u00a0' + priceMln + '</p>' : '') +
                (mortStr ? '<p class="text-gray-400 text-[11px] mt-0.5 whitespace-nowrap">' + mortStr + '</p>' : '') +
            '</div>';

        // Трекинг истории просмотров
        el.addEventListener('click', function() {
            if (window.propertyHistory && typeof window.propertyHistory.add === 'function') {
                window.propertyHistory.add(p);
            }
        });

        return el;
    }

    function _finish(props, label) {
        if (myGen !== window._похожиеGen) return;
        if (window._simPropsCtrl === myCtrl) window._simPropsCtrl = null;
        var gr2 = document.getElementById('похожие-grid');
        var ow2 = document.getElementById('похожие-outer');
        if (!gr2 || !ow2) return;
        if (!props || !props.length) { ow2.style.display = 'none'; return; }

        // Компактный рендер — специальные карточки для похожих
        gr2.innerHTML = '';
        gr2.className = 'grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3';
        props.forEach(function(p) {
            gr2.appendChild(_renderPohozhieCard(p));
        });

        // Подзаголовок отражает реальную логику подбора
        var sub = document.getElementById('похожие-subtitle');
        if (!sub) sub = ow2.querySelector('p');
        if (sub && label) sub.textContent = label;

        ow2.style.display = 'block';
        window._похожиеLoaded = true;

        // Учитываем текущий режим отображения (сетка/список) — как у основного списка
        try { _applyPohozhieViewMode(window.currentViewMode || 'grid'); } catch (e) {}
    }

    function _tryAttempt(i) {
        if (myGen !== window._похожиеGen) return; // отменено более новым запросом
        if (i >= attempts.length) { if (backup) _finish(backup.props, backup.label); else _hide(); return; }
        var a = attempts[i];
        var url = '/api/properties/list?' + a.params.toString();
        fetch(url, signal ? { signal: signal } : {})
            .then(function(r) { return r.json(); })
            .then(function(data) {
                if (myGen !== window._похожиеGen) return;
                var pool = data.properties || [];
                // Сортируем по близости к целевому ценовому уровню запроса
                // («приближенные объекты»), затем разнообразим по ЖК.
                if (target > 0) {
                    pool = pool.slice().sort(function(x, y) {
                        var px = parseInt(x.price, 10) || 0, py = parseInt(y.price, 10) || 0;
                        return Math.abs(px - target) - Math.abs(py - target);
                    });
                }
                var picked = _diversify(pool, 8);
                if (a.isBare) {
                    // Самый общий запрос — используем только если нет более релевантного резерва
                    if (backup) _finish(backup.props, backup.label);
                    else if (picked.length) _finish(picked, a.label);
                    else _hide();
                    return;
                }
                if (picked.length >= MIN_RESULTS) { _finish(picked, a.label); return; }
                if (picked.length && !backup) backup = { props: picked, label: a.label };
                _tryAttempt(i + 1);
            })
            .catch(function(err) {
                if (err && err.name === 'AbortError') return;
                if (myGen !== window._похожиеGen) return;
                _tryAttempt(i + 1);
            });
    }

    _tryAttempt(0);
};

// ── Режим отображения (сетка/список) для блока «Похожие предложения» ─────
// Зеркалит логику switchToGridView/switchToListView (templates/properties.html),
// но применяется к #похожие-grid, чтобы переключение вида работало и здесь.
function _applyPohozhieViewMode(mode) {
    var grid = document.getElementById('похожие-grid');
    if (!grid) return;
    var cards = grid.querySelectorAll('.property-card');
    if (mode === 'list') {
        grid.className = 'flex flex-col gap-4';
        cards.forEach(function(card) {
            card.className = 'property-card bg-white rounded-lg shadow-sm border border-gray-200 w-full flex flex-row cursor-pointer overflow-hidden';
            var carousel = card.querySelector('.carousel-container');
            var imageSection = carousel ? carousel.parentElement : null;
            if (imageSection) { imageSection.className = 'relative w-80 flex-shrink-0 group'; imageSection.style.width = '320px'; imageSection.style.height = '240px'; }
            if (carousel) { carousel.style.height = '240px'; }
            var children = Array.prototype.slice.call(card.children);
            var content = children.length > 1 ? children[1] : null;
            if (content && content.querySelector('h2')) {
                content.className = 'flex-1 p-5 flex flex-col';
                var h2 = content.querySelector('h2'); if (h2) h2.className = 'text-lg font-semibold text-gray-900 mb-2';
            }
            card.querySelectorAll('.hidden.sm\\:block, .hidden.sm\\:flex').forEach(function(el) { el.style.display = ''; });
        });
    } else {
        grid.className = 'grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3';
        cards.forEach(function(card) {
            card.className = 'property-card bg-white rounded-lg shadow-sm border border-gray-200 overflow-hidden w-full cursor-pointer';
            var carousel = card.querySelector('.carousel-container');
            var imageSection = carousel ? carousel.parentElement : null;
            if (imageSection) { imageSection.className = 'relative w-full h-[200px] flex-shrink-0 group'; imageSection.style.width = ''; imageSection.style.height = ''; }
            if (carousel) { carousel.style.height = ''; }
            var children = Array.prototype.slice.call(card.children);
            var content = children.length > 1 ? children[1] : null;
            if (content && content.querySelector('h2')) {
                content.className = 'flex-1 p-4 sm:p-6 flex flex-col';
                var h2 = content.querySelector('h2'); if (h2) h2.className = 'text-lg sm:text-xl font-semibold text-gray-900 mb-2 sm:mb-3';
            }
            card.querySelectorAll('.hidden.sm\\:block, .hidden.sm\\:flex').forEach(function(el) { el.style.display = ''; });
        });
    }
}
window._applyPohozhieViewMode = _applyPohozhieViewMode;

// Оборачиваем переключатели вида так, чтобы они применялись и к блоку «Похожие»
(function() {
    function _wrap(name, mode) {
        var orig = window[name];
        var wrapped = function() {
            var r = (typeof orig === 'function') ? orig.apply(this, arguments) : undefined;
            try { _applyPohozhieViewMode(mode); } catch (e) {}
            return r;
        };
        wrapped._pohozhieWrapped = true;
        window[name] = wrapped;
    }
    function _doWrap() {
        if (typeof window.switchToListView === 'function' && !window.switchToListView._pohozhieWrapped) _wrap('switchToListView', 'list');
        if (typeof window.switchToGridView === 'function' && !window.switchToGridView._pohozhieWrapped) _wrap('switchToGridView', 'grid');
    }
    _doWrap();
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', _doWrap);
    window.addEventListener('load', _doWrap);
})();

// Функция для обновления списка объектов
window.updatePropertiesList = function(properties) {
    console.log('🔄 updatePropertiesList called with', properties.length, 'properties');
    
    const container = document.getElementById('properties-container');
    if (!container) {
        console.error('❌ properties-container not found!');
        return;
    }

    // ── Пустой результат: показываем заглушку + похожие ──────────────────
    if (!properties || properties.length === 0) {
        window._похожиеLoaded = false;
        container.innerHTML =
            '<div class="col-span-3 w-full">' +
            '<div class="flex flex-col items-center justify-center py-16 px-6 text-center">' +
            '<div class="w-20 h-20 bg-gray-100 rounded-full flex items-center justify-center mb-6">' +
            '<svg class="w-10 h-10 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">' +
            '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"/>' +
            '</svg></div>' +
            '<h3 class="text-2xl font-bold text-gray-700 mb-2">Объекты не найдены</h3>' +
            '<p class="text-gray-500 mb-6 max-w-md">По вашему запросу ничего не найдено. Попробуйте изменить параметры поиска.</p>' +
            '<button onclick="(function(){if(typeof resetAllFilters===\'function\')resetAllFilters();else window.location.href=window.location.pathname;})()" ' +
            'class="inline-flex items-center gap-2 px-6 py-3 bg-blue-600 text-white rounded-xl font-medium hover:bg-blue-700 transition-colors">' +
            '<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">' +
            '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"/>' +
            '</svg>Сбросить фильтры</button>' +
            '</div></div>';
        // Захватываем поколение похожих. Если позже придёт состояние С результатами,
        // оно увеличит _похожиеGen и этот отложенный вызов будет отменён (latest-wins).
        var _g = (window._похожиеGen = (window._похожиеGen || 0) + 1);
        setTimeout(function() {
            if (_g === window._похожиеGen && typeof window._loadSimilarProps === 'function') {
                window._loadSimilarProps(window.citySlug || 'krasnodar', true);
            }
        }, 500);
        console.log('✅ Empty state shown, похожие will trigger shortly');
        return;
    }

    // ── Есть результаты: для ≤5 показываем похожие ниже карточек ──────────
    window._похожиеLoaded = false;
    if (window._simPropsCtrl) { try { window._simPropsCtrl.abort(); } catch(e) {} window._simPropsCtrl = null; }
    var _fewResults = properties.length <= 5;
    var похожиеOuter = document.getElementById('похожие-outer');
    if (!_fewResults) {
        window._похожиеGen = (window._похожиеGen || 0) + 1;
        if (похожиеOuter) похожиеOuter.style.display = 'none';
    }

    // Очищаем контейнер (только для AJAX обновлений)
    console.log('🔄 Clearing container for AJAX update');
    container.innerHTML = '';
    
    // Рендерим каждую карточку
    const currentPage = window.currentPage || 1;
    let listingBannerInserted = false;
    properties.forEach((property, index) => {
        if (index === 3 && !listingBannerInserted && window.listingBanners && window.listingBanners.length > 0 && currentPage === 1) {
            const bannerEl = buildListingBannerElement(window.listingBanners[0]);
            if (bannerEl) container.appendChild(bannerEl);
            listingBannerInserted = true;
        }
        const card = renderPropertyCard(property, index);
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
    
    if (typeof window.initializeImageCarousels === 'function') {
        window.initializeImageCarousels();
    }
    
    initCarouselSwipeHandlers();
    
    // PDF кнопки и Presentation модал работают через onclick атрибуты - не требуют реинициализации
    // Клики на карточки уже добавлены в renderPropertyCard() выше
    
    // ✅ ИСПРАВЛЕНИЕ: Применяем текущий режим отображения (list/grid)
    if (typeof window.currentViewMode !== 'undefined') {
        if (window.currentViewMode === 'list' && typeof window.switchToListView === 'function') {
            console.log('🔄 Applying LIST view after AJAX update');
            window.switchToListView();
        } else if (window.currentViewMode === 'grid' && typeof window.switchToGridView === 'function') {
            console.log('🔄 Applying GRID view after AJAX update');
            window.switchToGridView();
        }
    }
    
    // Мало результатов (1–5) → тоже показываем похожие под карточками
    if (_fewResults && properties.length > 0) {
        var _fewGen = (window._похожиеGen = (window._похожиеGen || 0) + 1);
        var _pohT = document.getElementById('похожие-title');
        var _pohS = document.getElementById('похожие-subtitle');
        if (_pohT) _pohT.textContent = 'Другие предложения города';
        if (_pohS) _pohS.textContent = 'Похожие варианты по близким параметрам';
        setTimeout(function() {
            if (_fewGen === window._похожиеGen && typeof window._loadSimilarProps === 'function') {
                window._loadSimilarProps(window.citySlug || 'krasnodar', true);
            }
        }, 600);
    }

    console.log('✅ List updated with', properties.length, 'properties');
};

function buildListingBannerElement(b) {
    if (!b) return null;
    const wrapper = document.createElement('div');
    wrapper.className = 'listing-promo-banner rounded-2xl overflow-hidden relative w-full';
    wrapper.style.cssText = `background:${b.bg_color || '#1a1a2e'};min-height:160px;`;
    
    const inner = `
        ${b.image_url ? `<img src="${b.image_url}" alt="" style="position:absolute;inset:0;width:100%;height:100%;object-fit:cover;opacity:0.6;mix-blend-mode:luminosity;">` : ''}
        ${b.link_url ? `<a href="${b.link_url}" class="block" style="position:relative;z-index:1;">` : '<div style="position:relative;z-index:1;">'}
        <div style="display:flex;align-items:center;justify-content:space-between;padding:24px 32px;min-height:160px;">
            <div style="flex:1;">
                <h3 style="font-size:1.5rem;font-weight:700;color:white;line-height:1.2;margin:0 0 4px 0;">${b.title}</h3>
                ${b.subtitle ? `<p style="color:rgba(255,255,255,0.7);font-size:0.95rem;margin:0 0 12px 0;">${b.subtitle}</p>` : ''}
                ${b.deadline_text ? `<span style="display:inline-flex;align-items:center;gap:6px;background:rgba(255,255,255,0.15);color:white;font-size:0.75rem;font-weight:500;padding:6px 12px;border-radius:999px;backdrop-filter:blur(4px);"><svg width="14" height="14" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z"/></svg>${b.deadline_text}</span>` : ''}
            </div>
            ${b.large_text ? `<div style="font-size:4rem;font-weight:900;color:rgba(255,255,255,0.9);margin-left:24px;flex-shrink:0;text-shadow:0 4px 20px rgba(0,0,0,0.3);">${b.large_text}</div>` : ''}
        </div>
        ${b.link_url ? '</a>' : '</div>'}
    `;
    wrapper.innerHTML = inner;
    return wrapper;
}

function renderPropertyCard(property, index) {
    const card = document.createElement('div');
    card.className = 'property-card bg-white rounded-lg shadow-sm border border-gray-200 overflow-hidden w-full cursor-pointer';
    
    // Все data-атрибуты ИДЕНТИЧНО оригиналу
    card.setAttribute('data-property-url', `/object/${property.id}`);
    card.setAttribute('data-type', property.type || 'apartment');
    card.setAttribute('data-rooms', property.rooms || 0);
    card.setAttribute('data-price', property.price || 0);
    card.setAttribute('data-district', property.district || '');
    card.setAttribute('data-developer', property.developer || '');
    card.setAttribute('data-complex', property.residential_complex || property.complex_name || 'Не указан');
    card.setAttribute('data-property-type', property.property_type || property.type || 'apartment');
    card.setAttribute('data-completion', property.completion_date || '2024');
    card.setAttribute('data-area', property.area || 0);
    card.setAttribute('data-floor', property.floor || 0);
    card.setAttribute('data-mortgage', property.mortgage_available !== undefined ? property.mortgage_available : 'true');
    card.setAttribute('data-installment', property.installment_available !== undefined ? property.installment_available : 'false');
    card.setAttribute('data-maternal-capital', property.maternal_capital !== undefined ? property.maternal_capital : 'false');
    card.setAttribute('data-trade-in', property.trade_in !== undefined ? property.trade_in : 'false');
    card.setAttribute('data-cashback', property.cashback_available !== undefined ? property.cashback_available : 'true');
    
    // Подготовка данных для галереи (максимум 4 изображения)
    const gallery = property.gallery && property.gallery.length > 0 ? property.gallery.slice(0, 4) : [property.image || 'https://via.placeholder.com/320x280/f3f4f6/9ca3af?text=Фото+недоступно'];
    const hasMultipleImages = gallery.length > 1;
    
    // Формируем описание комнат
    const roomDescription = property.rooms == 0 ? 'Студия' : `${property.rooms}-комн`;
    
    // === Carousel slides - translateX-based sliding ===
    const carouselSlidesHTML = `
        <div class="carousel-track" style="display:flex;height:100%;width:${gallery.length * 100}%;transform:translateX(0);will-change:transform;" data-index="0" data-count="${gallery.length}">
            ${gallery.map((image, idx) => `
                <div class="carousel-slide" style="width:${100/gallery.length}%;flex-shrink:0;height:100%;" data-slide="${idx}">
                    <img src="${escapeHtml(image)}" 
                         alt="${roomDescription} ${property.area} м² - фото ${idx + 1}" 
                         class="w-full h-full object-cover" 
                         draggable="false"
                         style="user-select:none;-webkit-user-drag:none;-webkit-touch-callout:none;pointer-events:none;"
                         loading="lazy">
                </div>
            `).join('')}
        </div>
    `;
    
    // Dots - always visible on mobile, hover on desktop
    const dotsHTML = hasMultipleImages ? `
        <div class="carousel-dots absolute bottom-3 left-1/2 -translate-x-1/2 flex gap-1.5 opacity-100 sm:opacity-0 sm:group-hover:opacity-100 transition-opacity z-10">
            ${gallery.map((_, idx) => `
                <button onclick="event.stopPropagation(); event.preventDefault(); window.carouselGoTo(this.closest('.carousel-container'), ${idx});" 
                        class="carousel-dot w-2.5 h-2.5 rounded-full ${idx === 0 ? 'bg-white' : 'bg-white/50'} hover:bg-white transition-colors" 
                        data-slide="${idx}"></button>
            `).join('')}
        </div>
    ` : '';
    
    // Navigation arrows (desktop only - hidden on mobile)
    const navigationHTML = hasMultipleImages ? `
        <button onclick="event.stopPropagation(); event.preventDefault(); window.carouselPrev(this.closest('.carousel-container'));" 
                class="hidden sm:flex absolute left-2 top-1/2 -translate-y-1/2 w-8 h-8 bg-black/50 hover:bg-black/70 text-white rounded-full items-center justify-center transition-all opacity-0 group-hover:opacity-100 z-10">
            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 19l-7-7 7-7"/>
            </svg>
        </button>
        <button onclick="event.stopPropagation(); event.preventDefault(); window.carouselNext(this.closest('.carousel-container'));" 
                class="hidden sm:flex absolute right-2 top-1/2 -translate-y-1/2 w-8 h-8 bg-black/50 hover:bg-black/70 text-white rounded-full items-center justify-center transition-all opacity-0 group-hover:opacity-100 z-10">
            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7"/>
            </svg>
        </button>
    ` : '';
    
    // Определяем, является ли пользователь менеджером
    const isManager = Boolean(window.manager_authenticated);
    
    // Формируем цену и ипотеку
    const _ppsm = property.price_per_sqm && property.price_per_sqm > 0
        ? property.price_per_sqm
        : (property.price && property.area && property.area > 0 ? Math.round(property.price / property.area) : 0);
    const priceHTML = property.price && property.price > 0 ? `
        <div class="flex items-baseline gap-2">
            <div class="text-2xl font-bold text-gray-900 whitespace-nowrap">
                ${formatNumber(property.price)}&nbsp;₽
            </div>
            ${_ppsm > 0 ? `<div class="text-xs text-gray-400 font-medium whitespace-nowrap">${formatNumber(_ppsm)}&nbsp;₽/м²</div>` : ''}
        </div>
        <div class="flex items-center gap-2 flex-wrap">
            <div class="bg-green-50 text-green-700 text-xs font-medium px-2.5 py-0.5 rounded-full border border-green-200">
                от ${formatNumber(Math.floor((property.price * 0.05) / 12))} ₽/мес ипотека
            </div>
        </div>
    ` : `
        <div class="text-2xl font-bold text-gray-900">
            Цена по запросу
        </div>
    `;
    
    // Кнопка презентации (только для менеджеров)
    const presentationButtonHTML = isManager ? `
        <button class="presentation-btn w-10 h-10 bg-white border border-[#0088CC] rounded-full flex items-center justify-center text-[#0088CC] hover:bg-blue-50 hover:border-blue-600 hover:text-blue-700 hover:scale-105 transition-all duration-200 shadow-sm" 
                data-property-id="${property.id}" 
                title="Добавить в презентацию" 
                onclick="window.openPresentationModal('${property.id}'); event.stopPropagation();">
            <i class="fas fa-plus"></i>
        </button>
    ` : '';
    const mobilePresentationButtonHTML = isManager ? `
        <button class="presentation-btn w-9 h-9 bg-[#0088CC]/10 rounded-full flex items-center justify-center text-[#0088CC] text-sm"
                data-property-id="${property.id}"
                title="В презентацию" style="touch-action:manipulation;"
                onclick="event.stopPropagation();event.stopImmediatePropagation();window.openPresentationModal('${property.id}');">
            <i class="fas fa-plus"></i>
        </button>
    ` : '';

    // Кнопка «В подборку» (для всех, кто не менеджер)
    const collectionButtonHTML = !isManager ? `
        <button class="collection-btn w-10 h-10 bg-[#0088CC]/10 hover:bg-[#0088CC] rounded-full flex items-center justify-center text-[#0088CC] hover:text-white hover:scale-105 transition-all duration-200 shadow-sm"
                data-property-id="${property.id}"
                title="В подборку"
                onclick="event.stopPropagation();if(typeof openAddToCollectionModal==='function'){openAddToCollectionModal('${property.id}');}">
            <i class="fas fa-folder-plus"></i>
        </button>
    ` : '';
    const mobileCollectionButtonHTML = !isManager ? `
        <button class="collection-btn w-9 h-9 bg-[#0088CC]/10 rounded-full flex items-center justify-center text-[#0088CC] text-sm"
                data-property-id="${property.id}"
                title="В подборку" style="touch-action:manipulation;"
                onclick="event.stopPropagation();event.stopImmediatePropagation();if(typeof openAddToCollectionModal==='function'){openAddToCollectionModal('${property.id}');}">
            <i class="fas fa-folder-plus"></i>
        </button>
    ` : '';
    
    // Dynamic phone for mobile action bar
    const phoneNumber = property.manager_phone || property.phone || '+78622666216';
    
    // Формируем HTML карточки - mobile-responsive version
    card.innerHTML = `
        <!-- Image Section -->
        <div class="relative w-full h-[200px] flex-shrink-0 group">
            <!-- Unified carousel for mobile + desktop -->
            <div class="carousel-container w-full h-full relative overflow-hidden bg-gray-100 sm:rounded-lg" 
                 data-property-id="${property.id}"
                 style="touch-action:pan-y;cursor:grab;user-select:none;">
                ${carouselSlidesHTML}
                ${navigationHTML}
                ${dotsHTML}
            </div>
            
            <!-- Cashback Badge (hidden on mobile, hidden when cashback=0) -->
            ${property.cashback && property.cashback > 0 ? `<div class="hidden sm:flex items-center gap-1.5 absolute top-3 left-3 text-[11px] font-semibold px-2.5 py-1 rounded-full shadow-sm z-20" style="background:rgba(255,255,255,0.94);backdrop-filter:blur(4px);-webkit-backdrop-filter:blur(4px);border:1px solid rgba(209,213,219,0.85);color:#374151;"><i class="fas fa-tag" style="color:#0088CC;font-size:9px;"></i>Кэшбек до ${formatNumber(property.cashback)} ₽</div>` : ''}
            
            <!-- Favorite Icons Container -->
            <div class="absolute top-3 right-3 flex gap-2 z-20">
                <div class="w-8 h-8 bg-white/90 hover:bg-white rounded-full flex items-center justify-center shadow cursor-pointer favorite-heart z-20" 
                     data-property-id="${property.id}" 
                     title="Добавить в избранное" 
                     onclick="if(window.favoritesManager) { window.favoritesManager.toggleFavorite('${property.id}', this); event.stopPropagation(); }">
                    <i class="fas fa-heart text-gray-400 hover:text-red-500 text-sm transition-colors"></i>
                </div>
            </div>
        </div>
        
        <!-- Content Section -->
        <div class="flex-1 p-4 sm:p-6 flex flex-col">
            <!-- Title -->
            <h2 class="text-lg sm:text-xl font-semibold text-gray-900 mb-2 sm:mb-3">
                ${roomDescription}, ${property.area} м², ${property.floor}/${property.total_floors} эт.
            </h2>
            
            <!-- Complex and Location -->
            <div class="mb-1 sm:mb-2">
                ${property.residential_complex || property.complex_name ? `
                    <a href="/residential-complex/${escapeHtml(property.residential_complex || property.complex_name)}" 
                       class="text-blue-600 hover:text-blue-700 hover:underline text-sm font-medium" 
                       onclick="event.stopPropagation();">
                        ${escapeHtml(property.residential_complex || property.complex_name)}
                    </a>
                ` : `
                    <span class="text-gray-700 text-sm font-medium">
                        ЖК не указан
                    </span>
                `}
            </div>
            
            <!-- CIAN address breadcrumb -->
            <div class="flex flex-wrap items-center gap-x-1 gap-y-0.5 text-xs text-gray-500 mb-2">
                ${property.region_name ? `<span>${escapeHtml(property.region_name)}</span><span class="text-gray-300">›</span>` : ''}
                <span class="font-medium text-gray-700">${escapeHtml(property.city_name || 'Краснодар')}</span>
                ${property.district && property.district !== property.city_name ? `<span class="text-gray-300">›</span><span class="font-semibold text-gray-800">${escapeHtml(property.district)}</span>` : ''}
                ${property.address ? `<span class="text-gray-300">›</span><span>${escapeHtml(property.address)}</span>` : ''}
            </div>
            
            <!-- Developer (hidden on mobile) -->
            <div class="hidden sm:block text-gray-700 text-sm mb-4">
                <span class="font-medium">Застройщик:</span> ${escapeHtml(property.developer || property.developer_name || '')}
            </div>
            
            <!-- Tags (hidden on mobile) -->
            <div class="hidden sm:flex flex-wrap gap-1.5 mb-4">
                <span style="background:rgba(0,136,204,0.08);border:1px solid rgba(0,136,204,0.22);color:#0369a1;" class="inline-flex items-center text-[11px] font-semibold px-2.5 py-0.5 rounded-full shadow-sm whitespace-nowrap">${property.floor}-й этаж</span>
                <span style="background:rgba(0,136,204,0.08);border:1px solid rgba(0,136,204,0.22);color:#0369a1;" class="inline-flex items-center text-[11px] font-semibold px-2.5 py-0.5 rounded-full shadow-sm whitespace-nowrap">${escapeHtml(property.renovation_display_name || 'Без отделки')}</span>
                <span style="background:rgba(0,136,204,0.08);border:1px solid rgba(0,136,204,0.22);color:#0369a1;" class="inline-flex items-center text-[11px] font-semibold px-2.5 py-0.5 rounded-full shadow-sm whitespace-nowrap">${escapeHtml(property.complex_object_class_display_name || 'Комфорт')}</span>
            </div>
            
            <div class="flex-1"></div>
            
            <!-- Price + Desktop Action Buttons -->
            <div class="flex flex-col sm:flex-row sm:items-end sm:justify-between gap-2 sm:gap-4">
                <div class="flex flex-col gap-1 sm:gap-2">
                    ${priceHTML}
                </div>
                <div class="hidden sm:flex items-center gap-2 flex-shrink-0">
                <button class="map-btn w-10 h-10 bg-[#0088CC]/10 hover:bg-[#0088CC] rounded-full flex items-center justify-center text-[#0088CC] hover:text-white hover:scale-105 transition-all duration-200 shadow-sm" 
                        data-property-id="${property.id}" 
                        data-lat="${property.latitude || 45.0355}" 
                        data-lon="${property.longitude || 38.9753}" 
                        data-name="${escapeHtml(property.complex_name || property.residential_complex || '')}" 
                        title="Показать на карте">
                    <i class="fas fa-map-marker-alt"></i>
                </button>
                <a href="/object/${property.id}/pdf" target="_blank" 
                   class="w-10 h-10 bg-[#0088CC]/10 hover:bg-[#0088CC] rounded-full flex items-center justify-center text-[#0088CC] hover:text-white hover:scale-105 transition-all duration-200 shadow-sm" 
                   title="Скачать PDF" 
                   onclick="event.stopPropagation();">
                    <i class="fas fa-file-pdf"></i>
                </a>
                <button class="compare-btn w-10 h-10 bg-[#0088CC]/10 rounded-full flex items-center justify-center shadow-sm" 
                        data-property-id="${property.id}" 
                        title="Добавить к сравнению"
                        style="color:#0088CC;transition:background 0.2s,color 0.2s,transform 0.2s;"
                        onmouseenter="this.style.background='#0088CC';this.style.color='white';this.style.transform='scale(1.05)';"
                        onmouseleave="this.style.background='rgba(0,136,204,0.1)';this.style.color='#0088CC';this.style.transform='scale(1)';">
                    <i class="fas fa-balance-scale" style="pointer-events:none;"></i>
                </button>
                ${collectionButtonHTML}
                ${presentationButtonHTML}
                </div>
            </div>
            
            <!-- Mobile Action Bar -->
            <div class="mobile-action-bar flex sm:hidden items-center justify-between mt-2 pt-2 border-t border-gray-100 relative z-20" style="pointer-events:auto;">
                <button class="mobile-call-btn flex items-center gap-1.5 px-4 py-2 bg-green-500 text-white rounded-full text-sm font-medium shadow-sm"
                   style="touch-action:manipulation;pointer-events:auto;"
                   data-phone="${escapeHtml(phoneNumber)}"
                   data-property-id="${property.id}"
                   data-complex-name="${escapeHtml(property.complex_name || property.residential_complex || '')}"
                   onclick="event.stopPropagation();event.stopImmediatePropagation();openPhoneModal(this.dataset.propertyId, this.dataset.complexName);">
                    <i class="fas fa-phone text-xs"></i> Позвонить
                </button>
                <div class="flex gap-2" style="pointer-events:auto;">
                    <button class="map-btn w-9 h-9 bg-[#0088CC]/10 rounded-full flex items-center justify-center text-[#0088CC] text-sm"
                            data-property-id="${property.id}" 
                            data-lat="${property.latitude || 45.0355}" 
                            data-lon="${property.longitude || 38.9753}"
                            data-name="${escapeHtml(property.complex_name || property.residential_complex || '')}"
                            title="Карта" style="touch-action:manipulation;" 
                            onclick="event.stopPropagation();event.stopImmediatePropagation();openMapModal(parseFloat(this.dataset.lat), parseFloat(this.dataset.lon), this.dataset.name || 'Расположение');">
                        <i class="fas fa-map-marker-alt"></i>
                    </button>
                    <a href="/object/${property.id}/pdf" target="_blank" 
                       class="w-9 h-9 bg-[#0088CC]/10 rounded-full flex items-center justify-center text-[#0088CC] text-sm"
                       title="PDF" style="touch-action:manipulation;" onclick="event.stopPropagation();event.stopImmediatePropagation();">
                        <i class="fas fa-file-pdf"></i>
                    </a>
                    <button class="compare-btn w-9 h-9 bg-[#0088CC]/10 rounded-full flex items-center justify-center text-[#0088CC] text-sm"
                            data-property-id="${property.id}"
                            title="Сравнить" style="touch-action:manipulation;">
                        <i class="fas fa-balance-scale"></i>
                    </button>
                    ${mobileCollectionButtonHTML}
                    ${mobilePresentationButtonHTML}
                </div>
            </div>
        </div>
    `;
    
    card.addEventListener('click', function(e) {
        if (e.target.closest('.mobile-action-bar') || e.target.closest('button') || e.target.closest('a') || e.target.closest('.carousel-container')) return;
        if (e.defaultPrevented) return;
        // Трекинг истории просмотров
        if (window.propertyHistory && typeof window.propertyHistory.add === 'function') {
            window.propertyHistory.add(property);
        }
        window.location.href = `/object/${property.id}`;
    });
    
    return card;
}

// Вспомогательная функция для экранирования HTML
function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// Функция для обновления пагинации
window.updatePagination = function(pagination) {
    console.log('📄 updatePagination called:', pagination);
    
    // Обновляем счетчик "Найдено X объектов"
    const resultsCount = document.getElementById('results-count');
    if (resultsCount) {
        resultsCount.textContent = pagination.total;
        console.log('✅ Updated results-count to', pagination.total);
    }
    
    // Обновляем счетчик resultsCounter (статичный счётчик в filter chips)
    const resultsCounter = document.getElementById('resultsCounter');
    if (resultsCounter) {
        // Функция склонения слова "объект"
        const getObjectWord = (count) => {
            if (count % 100 >= 11 && count % 100 <= 14) return "объектов";
            switch (count % 10) {
                case 1: return "объект";
                case 2: case 3: case 4: return "объекта";
                default: return "объектов";
            }
        };
        resultsCounter.textContent = `${pagination.total} ${getObjectWord(pagination.total)}`;
        console.log('✅ Updated resultsCounter to', pagination.total);
    }
    
    // Обновляем счетчик на кнопке "Показать на карте" (если есть)
    const counters = document.querySelectorAll('.properties-count');
    counters.forEach(counter => {
        counter.textContent = pagination.total;
    });
    
    // Обновляем пагинацию
    const paginationContainer = document.querySelector('.pagination');
    if (!paginationContainer) {
        console.warn('⚠️ Pagination container not found');
        return;
    }
    
    if (pagination.total_pages <= 1) {
        paginationContainer.innerHTML = '';
        return;
    }
    
    let html = '<div class="flex justify-center items-center gap-2 mt-8">';
    
    // Previous button
    if (pagination.has_prev) {
        html += `<a href="?page=${pagination.page - 1}" class="pagination-link px-4 py-2 rounded bg-white border border-gray-300 hover:bg-gray-50" data-page="${pagination.page - 1}">Назад</a>`;
    }
    
    // Page numbers
    const maxPages = 7;
    let startPage = Math.max(1, pagination.page - Math.floor(maxPages / 2));
    let endPage = Math.min(pagination.total_pages, startPage + maxPages - 1);
    
    if (endPage - startPage < maxPages - 1) {
        startPage = Math.max(1, endPage - maxPages + 1);
    }
    
    for (let i = startPage; i <= endPage; i++) {
        if (i === pagination.page) {
            html += `<span class="px-4 py-2 rounded bg-blue-600 text-white font-semibold">${i}</span>`;
        } else {
            html += `<a href="?page=${i}" class="pagination-link px-4 py-2 rounded bg-white border border-gray-300 hover:bg-gray-50" data-page="${i}">${i}</a>`;
        }
    }
    
    // Next button
    if (pagination.has_next) {
        html += `<a href="?page=${pagination.page + 1}" class="pagination-link px-4 py-2 rounded bg-white border border-gray-300 hover:bg-gray-50" data-page="${pagination.page + 1}">Вперёд</a>`;
    }
    
    html += '</div>';
    paginationContainer.innerHTML = html;
    
    // Добавляем обработчики клика на ссылки пагинации
    attachPaginationHandlers();
    
    console.log('✅ Pagination updated');
};

// Функция для прикрепления обработчиков к ссылкам пагинации
function attachPaginationHandlers() {
    const links = document.querySelectorAll('.pagination-link');
    links.forEach(link => {
        link.addEventListener('click', function(e) {
            e.preventDefault();
            const page = this.getAttribute('data-page');
            loadPage(page);
        });
    });
}

// Функция для загрузки конкретной страницы
function loadPage(page) {
    console.log('📄 Loading page:', page);
    
    showLoadingIndicator();
    
    const currentUrl = new URLSearchParams(window.location.search);
    currentUrl.set('page', page);
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
    
    fetch(apiUrl)
        .then(response => response.json())
        .then(data => {
            if (data.success && data.properties) {
                updatePropertiesList(data.properties);
                updatePagination(data.pagination);
                
                const newUrl = window.location.pathname + '?' + currentUrl.toString();
                window.history.pushState({}, '', newUrl);
                
                const _hasNext = data.pagination ? !!data.pagination.has_next : false;
                const _curPage = (data.pagination && data.pagination.page) ? data.pagination.page : page;
                if (window.infiniteScrollManager && window.infiniteScrollManager.reset) {
                    window.infiniteScrollManager.reset(_curPage, _hasNext);
                }
                
                scrollToPropertiesList();
            }
            hideLoadingIndicator();
        })
        .catch(error => {
            console.error('❌ Error loading page:', error);
            hideLoadingIndicator();
        });
}

// Вспомогательная функция для форматирования чисел
function formatNumber(num) {
    if (!num) return '0';
    return num.toString().replace(/\B(?=(\d{3})+(?!\d))/g, ' ');
}

// Вспомогательные функции для индикатора загрузки и скролла
// (определены в properties-sorting.js, но добавляем проверку на существование)
function showLoadingIndicator() {
    if (typeof window.showLoadingIndicator === 'undefined') {
        const container = document.getElementById('properties-container');
        if (container) {
            container.style.opacity = '0.5';
            container.style.pointerEvents = 'none';
        }
    }
}

function hideLoadingIndicator() {
    if (typeof window.hideLoadingIndicator === 'undefined') {
        const container = document.getElementById('properties-container');
        if (container) {
            container.style.opacity = '1';
            container.style.pointerEvents = 'auto';
        }
    }
}

function scrollToPropertiesList() {
    const container = document.getElementById('properties-container');
    if (container) {
        const offset = 100;
        const top = container.getBoundingClientRect().top + window.pageYOffset - offset;
        window.scrollTo({ top: top, behavior: 'smooth' });
    }
}

// Функция для переинициализации функционала карточек без изменения DOM
function reinitializeCardFeatures() {
    console.log('🔄 Reinitializing card features without DOM changes');
    
    if (window.favoritesManager && typeof window.favoritesManager.updateFavoritesUI === 'function') {
        window.favoritesManager.updateFavoritesUI();
        window.favoritesManager.updateComplexFavoritesUI();
    }
    
    if (typeof window.initializeComparisonButtons === 'function') {
        console.log('🔄 Reinitializing comparison buttons...');
        window.initializeComparisonButtons();
    }
    if (window.simpleComparisonManager && typeof window.simpleComparisonManager.updateComparisonUI === 'function') {
        console.log('🔄 Reinitializing simple comparison UI...');
        window.simpleComparisonManager.updateComparisonUI();
    }
    
    // Инициализация image carousel для SSR карточек
    if (typeof window.initializeImageCarousels === 'function') {
        console.log('🔄 Initializing image carousels for SSR cards...');
        window.initializeImageCarousels();
    }
    
    console.log('✅ Card features reinitialized');
}


// === Transform-based carousel: smooth sliding that follows finger ===

function carouselUpdateDots(container, index) {
    var dots = container.querySelectorAll('.carousel-dot');
    dots.forEach(function(dot, i) {
        if (i === index) { dot.classList.remove('bg-white/50'); dot.classList.add('bg-white'); }
        else { dot.classList.remove('bg-white'); dot.classList.add('bg-white/50'); }
    });
}

function carouselGoTo(container, index) {
    var track = container.querySelector('.carousel-track');
    if (!track) return;
    var count = parseInt(track.dataset.count) || 1;
    if (index < 0) index = 0;
    if (index >= count) index = count - 1;
    track.dataset.index = index;
    track.style.transition = 'transform 0.3s ease';
    track.style.transform = 'translateX(-' + (index * (100 / count)) + '%)';
    carouselUpdateDots(container, index);
}
window.carouselGoTo = carouselGoTo;

window.carouselNext = function(container) {
    var track = container.querySelector('.carousel-track');
    if (!track) return;
    var idx = parseInt(track.dataset.index) || 0;
    var count = parseInt(track.dataset.count) || 1;
    carouselGoTo(container, (idx + 1) % count);
};

window.carouselPrev = function(container) {
    var track = container.querySelector('.carousel-track');
    if (!track) return;
    var idx = parseInt(track.dataset.index) || 0;
    var count = parseInt(track.dataset.count) || 1;
    carouselGoTo(container, (idx - 1 + count) % count);
};

function initCarouselSwipeHandlers() {
    var containers = document.querySelectorAll('.carousel-container');
    containers.forEach(function(container) {
        if (container._swipeReady) return;
        container._swipeReady = true;
        var track = container.querySelector('.carousel-track');
        if (!track) return;
        
        var startX = 0, startY = 0, currentDelta = 0, isSwiping = false, isDragging = false;
        var count = parseInt(track.dataset.count) || 1;
        var slideWidthPercent = 100 / count;

        container.addEventListener('touchstart', function(e) {
            track.style.transition = 'none';
            startX = e.touches[0].clientX;
            startY = e.touches[0].clientY;
            currentDelta = 0;
            isSwiping = false;
            isDragging = false;
        }, {passive: true});
        
        container.addEventListener('touchmove', function(e) {
            var dx = e.touches[0].clientX - startX;
            var dy = e.touches[0].clientY - startY;
            if (!isDragging && Math.abs(dy) > Math.abs(dx) && Math.abs(dy) > 10) {
                return;
            }
            if (Math.abs(dx) > 8) {
                isDragging = true;
                isSwiping = true;
                e.preventDefault();
            }
            if (isDragging) {
                currentDelta = dx;
                var idx = parseInt(track.dataset.index) || 0;
                var baseOffset = -(idx * slideWidthPercent);
                var dragPercent = (dx / container.offsetWidth) * slideWidthPercent;
                track.style.transform = 'translateX(' + (baseOffset + dragPercent) + '%)';
            }
        }, {passive: false});
        
        container.addEventListener('touchend', function(e) {
            if (!isDragging) return;
            var idx = parseInt(track.dataset.index) || 0;
            var threshold = container.offsetWidth * 0.2;
            if (currentDelta < -threshold && idx < count - 1) {
                carouselGoTo(container, idx + 1);
            } else if (currentDelta > threshold && idx > 0) {
                carouselGoTo(container, idx - 1);
            } else {
                carouselGoTo(container, idx);
            }
        }, {passive: true});
        
        container.addEventListener('touchcancel', function() {
            var idx = parseInt(track.dataset.index) || 0;
            carouselGoTo(container, idx);
        }, {passive: true});

        var mouseDown = false, mouseStartX = 0;
        container.addEventListener('mousedown', function(e) {
            e.preventDefault();
            mouseDown = true;
            isSwiping = false;
            mouseStartX = e.clientX;
            currentDelta = 0;
            track.style.transition = 'none';
            container.style.cursor = 'grabbing';
        });
        container.addEventListener('mousemove', function(e) {
            if (!mouseDown) return;
            var dx = e.clientX - mouseStartX;
            currentDelta = dx;
            if (Math.abs(dx) > 8) isSwiping = true;
            if (isSwiping) {
                var idx = parseInt(track.dataset.index) || 0;
                var baseOffset = -(idx * slideWidthPercent);
                var dragPercent = (dx / container.offsetWidth) * slideWidthPercent;
                track.style.transform = 'translateX(' + (baseOffset + dragPercent) + '%)';
            }
        });
        container.addEventListener('mouseup', function(e) {
            if (!mouseDown) return;
            mouseDown = false;
            container.style.cursor = '';
            if (!isSwiping) return;
            var idx = parseInt(track.dataset.index) || 0;
            var threshold = container.offsetWidth * 0.2;
            if (currentDelta < -threshold && idx < count - 1) {
                carouselGoTo(container, idx + 1);
            } else if (currentDelta > threshold && idx > 0) {
                carouselGoTo(container, idx - 1);
            } else {
                carouselGoTo(container, idx);
            }
        });
        container.addEventListener('mouseleave', function() {
            if (mouseDown) {
                mouseDown = false;
                container.style.cursor = '';
                var idx = parseInt(track.dataset.index) || 0;
                carouselGoTo(container, idx);
            }
        });
        
        container.addEventListener('click', function(e) {
            if (isSwiping) {
                e.preventDefault();
                e.stopPropagation();
                setTimeout(function() { isSwiping = false; }, 100);
            }
        }, true);
    });
    console.log('📱 Carousel swipe handlers initialized for', containers.length, 'containers');
}
window.initCarouselSwipeHandlers = initCarouselSwipeHandlers;

// Export renderPropertyCard for use in infinite-scroll.js
window.renderPropertyCard = renderPropertyCard;

console.log('✅ properties-list-updater.js loaded');
