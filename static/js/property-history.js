(function() {
    var STORAGE_KEY = 'inback_viewed_props';
    var MAX_HISTORY = 40;

    function _load() {
        try {
            var raw = localStorage.getItem(STORAGE_KEY);
            return raw ? JSON.parse(raw) : [];
        } catch(e) { return []; }
    }

    function _save(arr) {
        try { localStorage.setItem(STORAGE_KEY, JSON.stringify(arr)); } catch(e) {}
    }

    window.propertyHistory = {
        add: function(prop) {
            if (!prop || !prop.id) return;
            var arr = _load();
            arr = arr.filter(function(x) { return x.id !== prop.id; });
            arr.unshift({
                id: prop.id,
                cityId: prop.city_id || window.currentCityId || 1,
                rooms: prop.rooms != null ? parseInt(prop.rooms, 10) : null,
                price: parseInt(prop.price, 10) || null,
                districtId: prop.district_id || null,
                area: parseFloat(prop.area) || null,
                ts: Date.now()
            });
            if (arr.length > MAX_HISTORY) arr = arr.slice(0, MAX_HISTORY);
            _save(arr);
        },

        get: function(cityId) {
            var arr = _load();
            if (cityId) arr = arr.filter(function(x) { return x.cityId === cityId; });
            return arr;
        },

        getPrefs: function(cityId) {
            var arr = this.get(cityId).slice(0, 20);
            if (!arr.length) return { hasHistory: false };

            var prices = arr.filter(function(x) { return x.price && x.price > 0; })
                            .map(function(x) { return x.price; });
            prices.sort(function(a, b) { return a - b; });

            var priceMin = null, priceMax = null;
            if (prices.length) {
                var med = prices[Math.floor(prices.length / 2)];
                priceMin = Math.floor(med * 0.55);
                priceMax = Math.ceil(med * 1.6);
            }

            var roomCounts = {};
            arr.forEach(function(x) {
                if (x.rooms != null) {
                    var k = String(x.rooms);
                    roomCounts[k] = (roomCounts[k] || 0) + 1;
                }
            });
            var rooms = Object.keys(roomCounts)
                .sort(function(a, b) { return roomCounts[b] - roomCounts[a]; })
                .slice(0, 2);

            return {
                hasHistory: true,
                priceMin: priceMin,
                priceMax: priceMax,
                rooms: rooms,
                count: arr.length
            };
        },

        getAll: function() { return _load(); },
        clear: function() { try { localStorage.removeItem(STORAGE_KEY); } catch(e) {} }
    };

    console.log('📚 property-history.js loaded, entries:', _load().length);
})();
