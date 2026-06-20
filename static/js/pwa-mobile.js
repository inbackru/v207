/* ════════════════════════════════════════════════════════════════
   InBack PWA Mobile Capabilities
   – Geolocation permission (proactive city detection)
   – Camera / Gallery avatar bottom sheet
   – Pull-to-Refresh with brand animation
   – Web Share API for properties & complexes
   – Visual Viewport keyboard avoidance
   – Add-to-Home-Screen nudge (iOS + Android)
   ════════════════════════════════════════════════════════════════ */

(function () {
  'use strict';

  var UA = navigator.userAgent || '';
  var isIOS     = /iPhone|iPad|iPod/.test(UA) && !window.MSStream;
  var isAndroid = /Android/.test(UA);
  var isMobile  = isIOS || isAndroid;
  var isStandalone = window.matchMedia('(display-mode: standalone)').matches
    || navigator.standalone === true;

  /* ── Helpers ────────────────────────────────────────────────── */
  function ls(key, val) {
    try {
      if (val === undefined) return localStorage.getItem(key);
      if (val === null) localStorage.removeItem(key);
      else localStorage.setItem(key, val);
    } catch(e) {}
  }
  function haptic(type) {
    if (!('vibrate' in navigator)) return;
    var p = { light:[8], medium:[20], heavy:[40], success:[10,20,40], error:[30,20,30] };
    navigator.vibrate(p[type] || [15]);
  }
  function citySlug() {
    return window.currentCitySlug || 'krasnodar';
  }

  /* ══════════════════════════════════════════════════════════════
     1. GEOLOCATION — proactive city auto-detection
     Shows a beautiful bottom banner on first visit if not yet chosen
     ══════════════════════════════════════════════════════════════ */
  var GEO_KEY  = 'inback_geo_asked';
  var GEO_CITY = 'inback_geo_city';

  var CITIES = [
    { name:'Краснодар',    slug:'krasnodar',    lat:45.0448, lon:38.9760 },
    { name:'Сочи',         slug:'sochi',         lat:43.5855, lon:39.7231 },
    { name:'Анапа',        slug:'anapa',         lat:44.8940, lon:37.3152 },
    { name:'Геленджик',    slug:'gelendzhik',    lat:44.5606, lon:38.0737 },
    { name:'Новороссийск', slug:'novorossiysk',  lat:44.7234, lon:37.7695 },
    { name:'Туапсе',       slug:'tuapse',        lat:44.1000, lon:39.0791 },
    { name:'Майкоп',       slug:'maykop',        lat:44.6090, lon:40.1029 },
    { name:'Армавир',      slug:'armavir',       lat:44.9894, lon:41.1248 }
  ];

  function haversine(lat1,lon1,lat2,lon2) {
    var R=6371, dLat=(lat2-lat1)*Math.PI/180, dLon=(lon2-lon1)*Math.PI/180;
    var a=Math.sin(dLat/2)*Math.sin(dLat/2)+
          Math.cos(lat1*Math.PI/180)*Math.cos(lat2*Math.PI/180)*
          Math.sin(dLon/2)*Math.sin(dLon/2);
    return R*2*Math.atan2(Math.sqrt(a),Math.sqrt(1-a));
  }

  function findNearestCity(lat, lon) {
    return CITIES.reduce(function(best, c) {
      var d = haversine(lat, lon, c.lat, c.lon);
      return d < best.dist ? { city: c, dist: d } : best;
    }, { city: CITIES[0], dist: Infinity }).city;
  }

  function showGeoSuccessBanner(cityName) {
    var b = document.createElement('div');
    b.id = 'geo-success-banner';
    b.style.cssText = [
      'position:fixed','bottom:' + (isMobile ? '80px' : '24px'),
      'left:50%','transform:translateX(-50%) translateY(20px)',
      'background:rgba(5,150,105,0.95)',
      'color:#fff','border-radius:16px','padding:12px 20px',
      'z-index:99996','display:flex','align-items:center','gap:10px',
      'font-size:14px','font-weight:600','white-space:nowrap',
      'box-shadow:0 8px 24px rgba(0,0,0,0.25)',
      'backdrop-filter:blur(10px)',
      'transition:all 0.35s cubic-bezier(0.34,1.56,0.64,1)',
      'pointer-events:none'
    ].join(';');
    b.innerHTML = '<svg width="18" height="18" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2.5"><path stroke-linecap="round" stroke-linejoin="round" d="M17.657 16.657L13.414 20.9a1.998 1.998 0 01-2.827 0l-4.244-4.243a8 8 0 1111.314 0z"/><path stroke-linecap="round" stroke-linejoin="round" d="M15 11a3 3 0 11-6 0 3 3 0 016 0z"/></svg>' +
      '<span>📍 Определён город: <strong>' + cityName + '</strong></span>';
    document.body.appendChild(b);
    requestAnimationFrame(function() {
      b.style.transform = 'translateX(-50%) translateY(0)';
      b.style.opacity = '1';
    });
    setTimeout(function() {
      b.style.transform = 'translateX(-50%) translateY(20px)';
      b.style.opacity = '0';
      setTimeout(function() { if (b.parentNode) b.parentNode.removeChild(b); }, 400);
    }, 3500);
  }

  function requestGeoPermission() {
    if (!navigator.geolocation) { window._notifBusy = false; return; }
    if (ls(GEO_KEY)) { window._notifBusy = false; return; }
    /* Don't ask if city-confirm modal is already visible */
    var cm = document.getElementById('cityConfirmModal');
    if (cm && !cm.classList.contains('hidden')) {
      ls(GEO_KEY, '1');
      window._notifBusy = false;
      return;
    }
    ls(GEO_KEY, '1');

    /* Signal to header.js that geo is in progress — city confirm should wait */
    window._geoInProgress = true;

    /* Trigger the NATIVE system geo dialog directly (no custom pre-banner).
       The browser shows its own permission dialog — clean and minimal.    */
    navigator.geolocation.getCurrentPosition(
      function(pos) {
        window._geoInProgress = false;
        var city = findNearestCity(pos.coords.latitude, pos.coords.longitude);
        ls(GEO_CITY, city.slug);
        haptic('success');
        if (citySlug() !== city.slug) {
          showGeoSuccessBanner(city.name);
          setTimeout(function() {
            window.location.href = '/' + city.slug + '/';
          }, 2000);
        }
        /* Release so city confirm can appear (if user stays on same city) */
        window._notifBusy = false;
      },
      function() {
        /* Denied or timed out — release so city confirm can appear */
        window._geoInProgress = false;
        window._notifBusy = false;
      },
      { enableHighAccuracy: false, timeout: 15000, maximumAge: 3600000 }
    );
  }

  /* ══════════════════════════════════════════════════════════════
     2. CAMERA / GALLERY AVATAR BOTTOM SHEET
     Intercepts avatar input clicks on mobile to show native-style picker
     ══════════════════════════════════════════════════════════════ */

  function createAvatarSheet(uploadInputId, uploadUrl, onSuccess) {
    var existing = document.getElementById('avatar-mobile-sheet');
    if (existing) { existing.parentNode.removeChild(existing); return; }

    haptic('medium');

    var sheet = document.createElement('div');
    sheet.id = 'avatar-mobile-sheet';

    var overlay = document.createElement('div');
    overlay.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.5);z-index:100000;backdrop-filter:blur(4px);opacity:0;transition:opacity 0.25s';
    document.body.appendChild(overlay);

    sheet.style.cssText = [
      'position:fixed','left:0','right:0','bottom:0',
      'background:#fff','border-radius:24px 24px 0 0',
      'z-index:100001','padding:0 0 env(safe-area-inset-bottom,16px) 0',
      'transform:translateY(100%)','transition:transform 0.35s cubic-bezier(0.32,0,0,1)',
      'overflow:hidden',
    ].join(';');

    sheet.innerHTML = [
      '<div style="width:36px;height:4px;background:#e5e7eb;border-radius:2px;margin:12px auto 4px"></div>',
      '<div style="padding:8px 16px 4px;font-size:12px;font-weight:600;color:#9ca3af;text-transform:uppercase;letter-spacing:0.06em">Фото профиля</div>',

      /* Camera */
      '<button id="avatar-btn-camera" style="width:100%;display:flex;align-items:center;gap:16px;padding:16px 20px;border:none;background:transparent;cursor:pointer;text-align:left;font-size:16px;color:#111827;font-weight:500;transition:background 0.15s" onmousedown="this.style.background=\'#f3f4f6\'" onmouseup="this.style.background=\'transparent\'" ontouchstart="this.style.background=\'#f3f4f6\'" ontouchend="this.style.background=\'transparent\'">'+
        '<div style="width:44px;height:44px;border-radius:14px;background:#eff6ff;display:flex;align-items:center;justify-content:center;flex-shrink:0">'+
          '<svg width="22" height="22" fill="none" stroke="#0088CC" viewBox="0 0 24 24" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M3 9a2 2 0 012-2h.93a2 2 0 001.664-.89l.812-1.22A2 2 0 0110.07 4h3.86a2 2 0 011.664.89l.812 1.22A2 2 0 0018.07 7H19a2 2 0 012 2v9a2 2 0 01-2 2H5a2 2 0 01-2-2V9z"/><circle cx="12" cy="13" r="3"/></svg>'+
        '</div>'+
        '<div><div style="font-weight:600">Сфотографировать</div><div style="font-size:13px;color:#6b7280;margin-top:1px">Использовать камеру</div></div>'+
      '</button>',

      /* Gallery */
      '<button id="avatar-btn-gallery" style="width:100%;display:flex;align-items:center;gap:16px;padding:16px 20px;border:none;background:transparent;cursor:pointer;text-align:left;font-size:16px;color:#111827;font-weight:500;transition:background 0.15s" onmousedown="this.style.background=\'#f3f4f6\'" onmouseup="this.style.background=\'transparent\'" ontouchstart="this.style.background=\'#f3f4f6\'" ontouchend="this.style.background=\'transparent\'">'+
        '<div style="width:44px;height:44px;border-radius:14px;background:#f0fdf4;display:flex;align-items:center;justify-content:center;flex-shrink:0">'+
          '<svg width="22" height="22" fill="none" stroke="#16a34a" viewBox="0 0 24 24" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/></svg>'+
        '</div>'+
        '<div><div style="font-weight:600">Выбрать из галереи</div><div style="font-size:13px;color:#6b7280;margin-top:1px">Загрузить фото с устройства</div></div>'+
      '</button>',

      /* Divider */
      '<div style="height:1px;background:#f3f4f6;margin:4px 0"></div>',

      /* Remove (shown only if has avatar) */
      '<button id="avatar-btn-remove" style="width:100%;display:flex;align-items:center;gap:16px;padding:16px 20px;border:none;background:transparent;cursor:pointer;text-align:left;font-size:16px;color:#ef4444;font-weight:500;transition:background 0.15s" onmousedown="this.style.background=\'#fff5f5\'" onmouseup="this.style.background=\'transparent\'" ontouchstart="this.style.background=\'#fff5f5\'" ontouchend="this.style.background=\'transparent\'">'+
        '<div style="width:44px;height:44px;border-radius:14px;background:#fff1f2;display:flex;align-items:center;justify-content:center;flex-shrink:0">'+
          '<svg width="22" height="22" fill="none" stroke="#ef4444" viewBox="0 0 24 24" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14H6L5 6"/><path stroke-linecap="round" d="M10 11v6M14 11v6"/><path d="M9 6V4h6v2"/></svg>'+
        '</div>'+
        '<div style="font-weight:600">Удалить фото</div>'+
      '</button>',

      /* Cancel */
      '<div style="padding:8px 16px 8px">',
        '<button id="avatar-btn-cancel" style="width:100%;padding:15px;border-radius:16px;background:#f3f4f6;border:none;color:#374151;font-size:16px;font-weight:600;cursor:pointer;transition:background 0.15s" onmousedown="this.style.background=\'#e5e7eb\'" onmouseup="this.style.background=\'#f3f4f6\'" ontouchstart="this.style.background=\'#e5e7eb\'" ontouchend="this.style.background=\'#f3f4f6\'">Отмена</button>',
      '</div>',
    ].join('');

    document.body.appendChild(sheet);

    /* Hidden file inputs */
    var cameraInput  = document.createElement('input');
    cameraInput.type = 'file'; cameraInput.accept = 'image/*'; cameraInput.capture = 'user';
    cameraInput.style.cssText = 'position:absolute;opacity:0;pointer-events:none;width:0;height:0';

    var galleryInput  = document.createElement('input');
    galleryInput.type = 'file'; galleryInput.accept = 'image/*';
    galleryInput.style.cssText = 'position:absolute;opacity:0;pointer-events:none;width:0;height:0';

    document.body.appendChild(cameraInput);
    document.body.appendChild(galleryInput);

    function closeSheet() {
      sheet.style.transform = 'translateY(100%)';
      overlay.style.opacity = '0';
      setTimeout(function() {
        if (sheet.parentNode) sheet.parentNode.removeChild(sheet);
        if (overlay.parentNode) overlay.parentNode.removeChild(overlay);
        if (cameraInput.parentNode) cameraInput.parentNode.removeChild(cameraInput);
        if (galleryInput.parentNode) galleryInput.parentNode.removeChild(galleryInput);
      }, 350);
    }

    function uploadFile(file) {
      if (!file) return;
      var formData = new FormData();
      formData.append('avatar', file);
      var csrfToken = (document.querySelector('meta[name="csrf-token"]') || {}).content || '';

      /* Show progress spinner on avatar */
      var avatarImg = document.getElementById('profile-avatar');
      if (avatarImg) avatarImg.style.opacity = '0.5';

      fetch(uploadUrl, {
        method: 'POST',
        body: formData,
        headers: csrfToken ? { 'X-CSRFToken': csrfToken } : {}
      })
      .then(function(r) { return r.json(); })
      .then(function(data) {
        if (avatarImg) avatarImg.style.opacity = '1';
        if (data.success) {
          haptic('success');
          if (avatarImg && avatarImg.tagName === 'IMG') {
            avatarImg.src = data.avatar_url + '?t=' + Date.now();
          } else if (avatarImg) {
            var img = document.createElement('img');
            img.src = data.avatar_url + '?t=' + Date.now();
            img.className = avatarImg.className;
            img.id = 'profile-avatar';
            img.style.cssText = avatarImg.style.cssText;
            avatarImg.parentNode.replaceChild(img, avatarImg);
          }
          if (typeof onSuccess === 'function') onSuccess(data.avatar_url);
          showAvatarToast('✅ Фото обновлено');
        } else {
          haptic('error');
          showAvatarToast('❌ ' + (data.error || 'Ошибка загрузки'), true);
        }
      })
      .catch(function() {
        if (avatarImg) avatarImg.style.opacity = '1';
        haptic('error');
        showAvatarToast('❌ Ошибка сети', true);
      });
    }

    cameraInput.addEventListener('change', function() { closeSheet(); uploadFile(this.files[0]); });
    galleryInput.addEventListener('change', function() { closeSheet(); uploadFile(this.files[0]); });

    sheet.querySelector('#avatar-btn-camera').addEventListener('click', function() {
      haptic('light'); closeSheet();
      setTimeout(function() { cameraInput.click(); }, 400);
    });
    sheet.querySelector('#avatar-btn-gallery').addEventListener('click', function() {
      haptic('light'); closeSheet();
      setTimeout(function() { galleryInput.click(); }, 400);
    });
    sheet.querySelector('#avatar-btn-remove').addEventListener('click', function() {
      haptic('medium');
      if (!confirm('Удалить фото профиля?')) return;
      closeSheet();
      var csrfToken = (document.querySelector('meta[name="csrf-token"]') || {}).content || '';
      fetch('/api/profile/remove-avatar', {
        method: 'POST',
        headers: Object.assign({ 'Content-Type': 'application/json' }, csrfToken ? { 'X-CSRFToken': csrfToken } : {})
      })
      .then(function(r) { return r.json(); })
      .then(function(d) {
        if (d.success) {
          haptic('success');
          var av = document.getElementById('profile-avatar');
          if (av) { av.src = ''; av.style.display = 'none'; }
          showAvatarToast('Фото удалено');
        }
      }).catch(function(){});
    });
    sheet.querySelector('#avatar-btn-cancel').addEventListener('click', function() {
      haptic('light'); closeSheet();
    });
    overlay.addEventListener('click', closeSheet);

    requestAnimationFrame(function() {
      overlay.style.opacity = '1';
      sheet.style.transform = 'translateY(0)';
    });
  }

  function showAvatarToast(text, isError) {
    var t = document.createElement('div');
    t.style.cssText = [
      'position:fixed','top:env(safe-area-inset-top,20px)','left:50%',
      'transform:translateX(-50%) translateY(-20px)',
      'background:' + (isError ? 'rgba(220,38,38,0.95)' : 'rgba(5,150,105,0.95)'),
      'color:#fff','border-radius:14px','padding:10px 18px',
      'z-index:100002','font-size:13px','font-weight:600',
      'white-space:nowrap','pointer-events:none',
      'box-shadow:0 4px 16px rgba(0,0,0,0.25)',
      'transition:all 0.35s cubic-bezier(0.34,1.56,0.64,1)',
      'opacity:0',
    ].join(';');
    t.textContent = text;
    document.body.appendChild(t);
    requestAnimationFrame(function() {
      t.style.transform = 'translateX(-50%) translateY(0)';
      t.style.opacity = '1';
    });
    setTimeout(function() {
      t.style.opacity = '0';
      t.style.transform = 'translateX(-50%) translateY(-20px)';
      setTimeout(function() { if (t.parentNode) t.parentNode.removeChild(t); }, 400);
    }, 2500);
  }

  /* Register avatar sheet trigger on any avatar-upload label */
  function bindAvatarTriggers() {
    var triggers = document.querySelectorAll('[data-avatar-sheet], label[for="avatar-upload"], #avatar-upload-label');
    triggers.forEach(function(el) {
      if (el._avatarBound) return;
      el._avatarBound = true;
      el.addEventListener('click', function(e) {
        if (!isMobile) return; /* desktop: use native file input normally */
        e.preventDefault();
        var uploadUrl = el.getAttribute('data-upload-url') || '/profile/upload-avatar';
        createAvatarSheet('avatar-upload', uploadUrl);
      });
    });

    /* Also bind the file input label in manager profile */
    var mgr = document.querySelector('label[for="manager-avatar-upload"], label[for="avatar_file"]');
    if (mgr && !mgr._avatarBound) {
      mgr._avatarBound = true;
      mgr.addEventListener('click', function(e) {
        if (!isMobile) return;
        e.preventDefault();
        var uploadUrl = mgr.getAttribute('data-upload-url') || '/manager/api/upload-avatar';
        createAvatarSheet('manager-avatar-upload', uploadUrl);
      });
    }
  }

  /* ══════════════════════════════════════════════════════════════
     3. PULL TO REFRESH
     ══════════════════════════════════════════════════════════════ */
  function initPullToRefresh() {
    if (!isMobile || isStandalone === false) return; /* only in PWA standalone */
    var PTR_THRESHOLD = 72;
    var startY = 0, pulling = false, ptr = null;

    function createPTR() {
      if (ptr) return;
      ptr = document.createElement('div');
      ptr.id = 'ptr-indicator';
      ptr.style.cssText = [
        'position:fixed','top:env(safe-area-inset-top,0px)',
        'left:50%','transform:translateX(-50%) translateY(-60px)',
        'width:44px','height:44px','border-radius:50%',
        'background:#fff','box-shadow:0 4px 16px rgba(0,0,0,0.15)',
        'display:flex','align-items:center','justify-content:center',
        'z-index:99990','transition:transform 0.2s ease',
        'pointer-events:none',
      ].join(';');
      ptr.innerHTML = '<svg id="ptr-svg" width="22" height="22" fill="none" stroke="#0088CC" viewBox="0 0 24 24" stroke-width="2" style="transition:transform 0.2s"><path stroke-linecap="round" stroke-linejoin="round" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"/></svg>';
      document.body.appendChild(ptr);
    }

    document.addEventListener('touchstart', function(e) {
      if (window.scrollY > 2) return;
      startY = e.touches[0].clientY;
      pulling = true;
      createPTR();
    }, { passive: true });

    document.addEventListener('touchmove', function(e) {
      if (!pulling || !ptr) return;
      var delta = Math.min(e.touches[0].clientY - startY, PTR_THRESHOLD * 1.5);
      if (delta < 0) return;
      var progress = Math.min(delta / PTR_THRESHOLD, 1);
      var translateY = -60 + delta * 0.6;
      ptr.style.transform = 'translateX(-50%) translateY(' + translateY + 'px)';
      ptr.querySelector('#ptr-svg').style.transform = 'rotate(' + (progress * 300) + 'deg)';
      ptr.style.background = progress >= 1 ? '#0088CC' : '#fff';
      ptr.querySelector('#ptr-svg').style.stroke = progress >= 1 ? '#fff' : '#0088CC';
    }, { passive: true });

    document.addEventListener('touchend', function(e) {
      if (!pulling || !ptr) return;
      var delta = e.changedTouches[0].clientY - startY;
      pulling = false;
      if (delta >= PTR_THRESHOLD) {
        haptic('medium');
        ptr.querySelector('#ptr-svg').style.animation = 'ptr-spin 0.8s linear infinite';
        var style = document.getElementById('ptr-spin-style');
        if (!style) {
          style = document.createElement('style');
          style.id = 'ptr-spin-style';
          style.textContent = '@keyframes ptr-spin{from{transform:rotate(0)}to{transform:rotate(360deg)}}';
          document.head.appendChild(style);
        }
        setTimeout(function() { window.location.reload(); }, 600);
      } else {
        ptr.style.transform = 'translateX(-50%) translateY(-60px)';
        setTimeout(function() {
          if (ptr && ptr.parentNode) ptr.parentNode.removeChild(ptr);
          ptr = null;
        }, 300);
      }
    }, { passive: true });
  }

  /* ══════════════════════════════════════════════════════════════
     4. WEB SHARE API — share properties & complexes
     ══════════════════════════════════════════════════════════════ */
  window.pwaShare = function(opts) {
    var title = opts.title || 'InBack — кэшбек за квартиру';
    var text  = opts.text  || 'Посмотрите это предложение на InBack.ru';
    var url   = opts.url   || window.location.href;
    if (navigator.share) {
      navigator.share({ title: title, text: text, url: url })
        .then(function() { haptic('success'); })
        .catch(function() {});
    } else {
      /* Fallback: copy to clipboard */
      navigator.clipboard && navigator.clipboard.writeText(url).then(function() {
        showAvatarToast('🔗 Ссылка скопирована');
      });
    }
  };

  window.shareProperty = function(innerIdOrEl) {
    var el = typeof innerIdOrEl === 'string'
      ? document.querySelector('[data-property-id="' + innerIdOrEl + '"]')
      : innerIdOrEl;
    var title = (el && el.getAttribute('data-property-title')) || 'Квартира в новостройке';
    var price = (el && el.getAttribute('data-property-price')) || '';
    pwaShare({
      title: title + (price ? ' — ' + price + ' ₽' : ''),
      text: 'Смотрите: ' + title + ' с кэшбеком на InBack.ru',
      url: window.location.href
    });
  };

  window.shareComplex = function(name) {
    pwaShare({
      title: (name || 'Жилой комплекс') + ' на InBack.ru',
      text: 'Купите квартиру в ' + (name || 'этом ЖК') + ' с кэшбеком до 500 000 ₽',
      url: window.location.href
    });
  };

  /* ══════════════════════════════════════════════════════════════
     5. VISUAL VIEWPORT — keyboard avoidance
     Push content up when virtual keyboard opens
     ══════════════════════════════════════════════════════════════ */
  function initKeyboardAvoidance() {
    if (!window.visualViewport || !isMobile) return;
    var lastH = window.visualViewport.height;
    window.visualViewport.addEventListener('resize', function() {
      var currentH = window.visualViewport.height;
      var diff = lastH - currentH;
      lastH = currentH;
      if (diff > 100) {
        /* Keyboard opened */
        var focused = document.activeElement;
        if (focused && focused.tagName !== 'BODY') {
          setTimeout(function() {
            focused.scrollIntoView({ behavior: 'smooth', block: 'center' });
          }, 150);
        }
      }
    });
  }

  /* ══════════════════════════════════════════════════════════════
     6. ADD-TO-HOME-SCREEN nudge (iOS Safari)
     ══════════════════════════════════════════════════════════════ */
  function initA2HSNudge() {
    if (!isIOS || isStandalone) return;
    var visits = parseInt(ls('inback_visits') || '0') + 1;
    ls('inback_visits', String(visits));
    /* Show on 5th and 12th visit — user must be genuinely engaged first */
    if (visits !== 5 && visits !== 12) return;
    if (ls('inback_a2hs_dismissed')) return;

    /* Go through the popup queue so it never overlaps geo/city/push */
    _withQueue(function() {
      var nudge = document.createElement('div');
      nudge.style.cssText = [
        'position:fixed','bottom:' + (isMobile ? '88px' : '24px'),
        'left:16px','right:16px',
        'background:rgba(10,20,40,0.97)',
        'color:#fff','border-radius:20px','padding:16px 18px',
        'z-index:99994',
        'display:flex','align-items:center','gap:14px',
        'box-shadow:0 16px 40px rgba(0,0,0,0.4)',
        'backdrop-filter:blur(16px)',
        'border:1px solid rgba(255,255,255,0.08)',
        'opacity:0','transform:translateY(20px)',
        'transition:all 0.4s cubic-bezier(0.34,1.56,0.64,1)',
      ].join(';');
      nudge.innerHTML = [
        '<div style="width:48px;height:48px;border-radius:14px;background:linear-gradient(135deg,#0088CC,#005f8e);display:flex;align-items:center;justify-content:center;flex-shrink:0">',
          '<img src="/static/images/logo.svg" width="32" height="32" onerror="this.style.display=\'none\'">',
        '</div>',
        '<div style="flex:1">',
          '<div style="font-size:13px;font-weight:700;margin-bottom:2px">Добавить InBack на экран</div>',
          '<div style="font-size:11px;color:rgba(255,255,255,0.5);line-height:1.4">Нажмите <strong style="color:rgba(255,255,255,0.8)">Поделиться</strong> → <strong style="color:rgba(255,255,255,0.8)">На экран «Домой»</strong></div>',
        '</div>',
        '<button id="a2hs-close" style="background:none;border:none;color:rgba(255,255,255,0.4);font-size:20px;cursor:pointer;padding:4px;line-height:1">✕</button>',
      ].join('');
      document.body.appendChild(nudge);
      requestAnimationFrame(function() {
        nudge.style.opacity = '1';
        nudge.style.transform = 'translateY(0)';
      });
      function _hideA2HS() {
        nudge.style.opacity = '0';
        nudge.style.transform = 'translateY(20px)';
        window._notifBusy = false;
        setTimeout(function() { if (nudge.parentNode) nudge.parentNode.removeChild(nudge); }, 400);
      }
      document.getElementById('a2hs-close').addEventListener('click', function() {
        ls('inback_a2hs_dismissed', '1');
        _hideA2HS();
      });
      /* Auto-dismiss after 10s and release the queue */
      setTimeout(_hideA2HS, 10000);
    }, 90000); /* 90s delay in queue */
  }

  /* ══════════════════════════════════════════════════════════════
     5b. BADGING API — set/clear app icon badge (unread count)
     ══════════════════════════════════════════════════════════════ */
  window.pwaBadge = {
    set: function(count) {
      if ('setAppBadge' in navigator) {
        navigator.setAppBadge(count || 0).catch(function() {});
      }
    },
    clear: function() {
      if ('clearAppBadge' in navigator) {
        navigator.clearAppBadge().catch(function() {});
      }
    }
  };

  /* ══════════════════════════════════════════════════════════════
     6b. SMART PUSH NOTIFICATION permission request
     — never ask immediately on load
     — show a branded pre-permission card after 45 s engagement
       OR after the user views 3+ property/complex pages
     — only on mobile & only once per install
     ══════════════════════════════════════════════════════════════ */
  var PUSH_ASKED_KEY = 'inback_push_asked';
  var _pushViews = 0;

  function _canAskPush() {
    return 'Notification' in window
      && Notification.permission === 'default'
      && !ls(PUSH_ASKED_KEY)
      && 'serviceWorker' in navigator
      && isMobile;
  }

  function _showPushCard() {
    if (!_canAskPush()) return;
    /* Wait if another banner is currently visible */
    if (window._notifBusy) {
      setTimeout(_showPushCard, 9000);
      return;
    }
    window._notifBusy = true;
    ls(PUSH_ASKED_KEY, '1');

    var card = document.createElement('div');
    card.id = 'push-permission-card';
    card.setAttribute('role', 'dialog');
    card.setAttribute('aria-label', 'Разрешить уведомления');
    card.style.cssText = [
      'position:fixed', 'bottom:' + (isMobile ? '88px' : '24px'), 'left:50%',
      'transform:translateX(-50%) translateY(20px)',
      'background:#fff', 'border-radius:20px',
      'box-shadow:0 12px 48px rgba(0,0,0,0.18),0 0 0 1px rgba(0,0,0,0.06)',
      'padding:20px', 'z-index:99997', 'width:min(340px,calc(100vw - 32px))',
      'opacity:0', 'transition:opacity 0.3s ease,transform 0.35s cubic-bezier(0.34,1.56,0.64,1)'
    ].join(';');

    card.innerHTML = [
      '<div style="display:flex;align-items:flex-start;gap:12px;margin-bottom:14px">',
        '<div style="width:44px;height:44px;border-radius:12px;background:linear-gradient(135deg,#0088CC,#005f8e);',
          'display:flex;align-items:center;justify-content:center;flex-shrink:0">',
          '<svg width="22" height="22" fill="none" stroke="#fff" viewBox="0 0 24 24" stroke-width="2">',
            '<path stroke-linecap="round" stroke-linejoin="round" d="M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6.002 6.002 0 00-4-5.659V5a2 2 0 10-4 0v.341C7.67 6.165 6 8.388 6 11v3.159c0 .538-.214 1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9"/>',
          '</svg>',
        '</div>',
        '<div style="flex:1;min-width:0">',
          '<div style="font-size:14px;font-weight:700;color:#111;margin-bottom:3px">Уведомления о новых объектах</div>',
          '<div style="font-size:12px;color:#6b7280;line-height:1.45">Сообщим, когда появятся квартиры по вашим критериям или изменится цена на избранные</div>',
        '</div>',
        '<button id="push-card-close" aria-label="Закрыть" style="background:none;border:none;color:#9ca3af;font-size:18px;cursor:pointer;padding:2px;line-height:1;flex-shrink:0">✕</button>',
      '</div>',
      '<div style="display:flex;gap:8px">',
        '<button id="push-card-allow" style="flex:1;background:linear-gradient(135deg,#0088CC,#006699);color:#fff;',
          'border:none;border-radius:12px;padding:10px 0;font-size:13px;font-weight:600;cursor:pointer">',
          'Включить',
        '</button>',
        '<button id="push-card-deny" style="flex:1;background:#f3f4f6;color:#374151;',
          'border:none;border-radius:12px;padding:10px 0;font-size:13px;font-weight:500;cursor:pointer">',
          'Не сейчас',
        '</button>',
      '</div>'
    ].join('');

    document.body.appendChild(card);
    requestAnimationFrame(function() {
      card.style.opacity = '1';
      card.style.transform = 'translateX(-50%) translateY(0)';
    });

    function _hideCard() {
      card.style.opacity = '0';
      card.style.transform = 'translateX(-50%) translateY(20px)';
      setTimeout(function() {
        if (card.parentNode) card.parentNode.removeChild(card);
        window._notifBusy = false;
      }, 350);
    }

    document.getElementById('push-card-close').addEventListener('click', _hideCard);
    document.getElementById('push-card-deny').addEventListener('click', _hideCard);
    document.getElementById('push-card-allow').addEventListener('click', function() {
      _hideCard();
      Notification.requestPermission().then(function(perm) {
        if (perm === 'granted') {
          haptic('success');
          /* Register push subscription via SW */
          navigator.serviceWorker.ready.then(function(reg) {
            if (reg.pushManager) {
              reg.pushManager.subscribe({
                userVisibleOnly: true,
                applicationServerKey: window.VAPID_PUBLIC_KEY || undefined
              }).catch(function() {});
            }
          });
        }
      });
    });

    /* Auto-dismiss after 18 s */
    setTimeout(_hideCard, 18000);
  }

  /* Track property/complex views to trigger push card after 3 */
  function _trackPageEngagement() {
    var isPropertyPage = /\/(kvartira|zhiloy-kompleks|properties|complexes)\//.test(window.location.pathname)
      || document.querySelector('[data-property-id],[data-complex-id]');
    if (isPropertyPage) {
      var views = parseInt(ls('inback_pv_count') || '0') + 1;
      ls('inback_pv_count', String(views));
      _pushViews = views;
      /* Delay push card via queue so it never overlaps geo or city banner */
      if (views >= 2 && _canAskPush()) _withQueue(function() { _showPushCard(); }, 60000);
    }
  }

  /* _initPushTimer is replaced by _withQueue at bottom of init block */
  function _initPushTimer() { /* noop — kept for safety */ }

  /* ══════════════════════════════════════════════════════════════
     7. SHARE BUTTONS on property cards — inject on mobile
     ══════════════════════════════════════════════════════════════ */
  function injectShareButtons() {
    if (!navigator.share && !navigator.clipboard) return;
    /* Property detail page */
    var shareHook = document.querySelector('[data-share-hook]');
    if (!shareHook) return;
    var btn = document.createElement('button');
    btn.className = 'flex items-center gap-2 text-gray-500 hover:text-[#0088CC] transition-colors text-sm font-medium';
    btn.innerHTML = '<svg width="18" height="18" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M8.684 13.342C8.886 12.938 9 12.482 9 12c0-.482-.114-.938-.316-1.342m0 2.684a3 3 0 110-2.684m0 2.684l6.632 3.316m-6.632-6l6.632-3.316m0 0a3 3 0 105.367-2.684 3 3 0 00-5.367 2.684zm0 9.316a3 3 0 105.368 2.684 3 3 0 00-5.368-2.684z"/></svg> Поделиться';
    btn.addEventListener('click', function() {
      pwaShare({ title: document.title, url: window.location.href });
    });
    shareHook.appendChild(btn);
  }

  /* ══════════════════════════════════════════════════════════════
     INIT
     ══════════════════════════════════════════════════════════════ */
  document.addEventListener('DOMContentLoaded', function() {
    bindAvatarTriggers();
    initKeyboardAvoidance();
    injectShareButtons();
    /* NOTE: initA2HSNudge() is called AFTER _withQueue is defined below */

    /* ── Sequential notification queue ────────────────────────────
       Single-lane queue: only one popup shows at a time.
       Sequence: Geo (2.5s) → City confirm (auto, header.js) →
                 Push (60s, 2+ property views) → A2HS (visit 5+, 90s) →
                 Chat bubble (2min, base.html).
       All banners must call window._notifBusy = false when dismissed.    */
    window._notifBusy = false;      /* shared with chat widget in base.html */
    window._notifQueueTimer = null;

    function _withQueue(fn, delay) {
      setTimeout(function() {
        if (window._notifBusy) {
          /* Retry every 10s until the lane is free */
          window._notifQueueTimer = setTimeout(function() { _withQueue(fn, 0); }, 10000);
        } else {
          window._notifBusy = true;
          fn();
          /* Safety auto-clear after 30s in case a banner forgets to release */
          setTimeout(function() { if (window._notifBusy) window._notifBusy = false; }, 30000);
        }
      }, delay);
    }
    /* Expose so initA2HSNudge (and base.html chat bubble) can use it */
    window._withQueue = _withQueue;

    /* Geo: НЕ запрашиваем автоматически — только по явному клику пользователя.
       Функция requestGeoPermission() доступна через window.pwaMobile.requestGeo()
       и вызывается кнопкой "Определить местоположение" в выборе города. */
    window._geoInProgress = false;

    /* PWA standalone: init pull-to-refresh */
    if (isStandalone) initPullToRefresh();

    /* Smart push permission — только после реального вовлечения (3 мин + 3 просмотра) */
    _trackPageEngagement();
    var _pushVisits = parseInt(ls('inback_pv_count') || '0');
    if (_canAskPush() && _pushVisits >= 3) {
      _withQueue(function() { _showPushCard(); }, 180000);
    }

    /* A2HS — called here so _withQueue is in scope */
    initA2HSNudge();

    /* Restore badge from server on launch */
    if ('setAppBadge' in navigator) {
      fetch('/api/user/unread-count', { credentials: 'same-origin' })
        .then(function(r) { return r.ok ? r.json() : null; })
        .then(function(d) { if (d && d.count > 0) window.pwaBadge.set(d.count); })
        .catch(function() {});
    }

    /* Expose public API */
    window.pwaMobile = {
      showAvatarSheet: createAvatarSheet,
      requestGeo: requestGeoPermission,
      share: window.pwaShare,
      badge: window.pwaBadge,
      requestPushPermission: _showPushCard,
    };
  });

  /* ══════════════════════════════════════════════════════════════
     8. OFFLINE FORM QUEUE — save failed submissions to SW IndexedDB
        Usage: pwaQueueRequest({ url, method, body, headers })
        The SW replays them via background sync when back online.
     ══════════════════════════════════════════════════════════════ */
  window.pwaQueueRequest = function(request) {
    if (!('serviceWorker' in navigator) || !navigator.serviceWorker.controller) return;
    navigator.serviceWorker.controller.postMessage({
      type: 'QUEUE_REQUEST',
      request: {
        url:     request.url,
        method:  request.method  || 'POST',
        headers: request.headers || { 'Content-Type': 'application/json' },
        body:    request.body
      }
    });
    /* Attempt to register background sync tag */
    navigator.serviceWorker.ready.then(function(reg) {
      if (reg.sync) reg.sync.register('inback-forms').catch(function() {});
    });
  };

  /* Notify gamification of property views via share/visit */
  window.addEventListener('pwa:propertyView', function(e) {
    if (window.pwaGame) window.pwaGame.gainXP(5, 'Просмотр квартиры');
  });

})();
