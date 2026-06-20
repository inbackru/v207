/* ════════════════════════════════════════════════════════════════
   InBack PWA Gamification
   - Dynamic Island (iPhone 14 Pro+): cashback pill + money rain
   - Android: Material You pulse, rich haptics, XP orb
   - Universal: streak, achievements, XP, cashback progress ring
   ════════════════════════════════════════════════════════════════ */

(function () {
  'use strict';

  /* ── Device Detection ──────────────────────────────────────── */
  var UA = navigator.userAgent || '';
  var isIOS = /iPhone|iPad|iPod/.test(UA) && !window.MSStream;
  var isAndroid = /Android/.test(UA);
  /* Also treat narrow viewports (phones opening desktop site) as mobile */
  var isMobile = isIOS || isAndroid || window.innerWidth < 768;
  var isStandalone = window.matchMedia('(display-mode: standalone)').matches
    || navigator.standalone === true;
  var hasVibration = 'vibrate' in navigator;

  /* ── Staff-page guard ─────────────────────────────────────── */
  /* No XP events on manager/admin/partner back-office pages or user dashboard. */
  var staffPagePattern = /^\/(manager|admin|partner|dashboard)(\/|$)/;
  var isStaffPage = staffPagePattern.test(window.location.pathname);
  /* Hide mascot on mobile for property/complex search and detail pages — it overlaps UI */
  var searchPagePattern = /\/(properties|novostrojki|complexes|zhilye-kompleksy|zk\/|object\/)/;
  var isSearchPageMobile = isMobile && searchPagePattern.test(window.location.pathname);

  /* Mobile bottom nav height — actual rendered height is 56px */
  var BOTTOM_NAV_H = isMobile ? 56 : 0;

  /* HUD bottom/side: desktop → bottom-left; mobile → bottom-right with enough clearance */
  function hudBottom() {
    if (!isMobile) return '90px'; /* desktop: above chat FAB */
    /* 56px nav + 28px clearance = 84px — well above the nav */
    return isStandalone ? '88px' : (BOTTOM_NAV_H + 28) + 'px';
  }
  function hudSide() {
    /* Always right — keeps mascot away from left-side call button on property pages */
    return null;
  }
  function toastBottom() {
    return isStandalone ? '100px' : (isMobile ? (BOTTOM_NAV_H + 16) + 'px' : '100px');
  }
  function statsPanelBottom() {
    return isStandalone ? '160px' : (isMobile ? (BOTTOM_NAV_H + 78) + 'px' : '160px');
  }

  /* ── Dynamic Island Detection ─────────────────────────────── */
  /* DI phones: iPhone 14 Pro / 14 Pro Max / 15 / 15 Plus / 15 Pro / 15 Pro Max
     Logical screen widths: 393 (Pro) or 430 (Pro Max / Plus)
     Safe-area-inset-top on DI phones: 59px in standalone, ~47-59 in browser */
  var DI_TOP = 0;
  var hasDynamicIsland = false;

  function detectSAI() {
    /* Method 1: safe-area env() measurement */
    var el = document.createElement('div');
    el.style.cssText = 'position:fixed;top:env(safe-area-inset-top,0px);left:0;height:1px;pointer-events:none;visibility:hidden;z-index:-1';
    document.body.appendChild(el);
    DI_TOP = el.getBoundingClientRect().top;
    document.body.removeChild(el);

    /* Method 2: screen dimension fingerprint (DI models only) */
    var sw = screen.width, sh = screen.height;
    var isDIBySize = (
      (sw === 393 && sh >= 852) ||  /* iPhone 14 Pro / 15 Pro / 16 */
      (sw === 430 && sh >= 932) ||  /* iPhone 14 Pro Max / 15 Pro Max / 15 Plus / 16 Plus */
      (sw === 402 && sh >= 874) ||  /* iPhone 16 Pro */
      (sw === 440 && sh >= 956) ||  /* iPhone 16 Pro Max */
      (sw === 390 && sh >= 844) ||  /* iPhone 16 (base) — has DI */
      /* landscape mirrors */
      (sw === 852 && sh === 393) ||
      (sw === 932 && sh === 430) ||
      (sw === 874 && sh === 402) ||
      (sw === 956 && sh === 440) ||
      (sw === 844 && sh === 390)
    );

    /* Use ONLY exact screen dimensions — safe-area-inset-top >= 47 fires on
       regular notch iPhones too, causing false positives in PWA mode. */
    hasDynamicIsland = isIOS && isDIBySize;

    /* Ensure DI_TOP has the right value for actual DI phones */
    if (isDIBySize && DI_TOP < 47) DI_TOP = 59;
  }

  /* ── Persistent Store ─────────────────────────────────────── */
  var STORE_KEY = 'inback_game_v2';
  function loadStore() {
    try { return JSON.parse(localStorage.getItem(STORE_KEY) || '{}'); } catch (e) { return {}; }
  }
  function saveStore(s) {
    try { localStorage.setItem(STORE_KEY, JSON.stringify(s)); } catch (e) {}
  }

  var store = loadStore();
  store.xp            = store.xp            || 0;
  store.streak        = store.streak        || 0;
  store.lastVisit     = store.lastVisit     || null;
  store.achievements  = store.achievements  || [];
  store.cashbackGoal  = store.cashbackGoal  || 150000; /* ₽ */
  store.cashbackEarned= store.cashbackEarned|| 0;
  store.totalViews    = store.totalViews    || 0;
  store.totalFavs     = store.totalFavs     || 0;

  /* ── Daily XP dedup helpers ───────────────────────────────── */
  /* viewedToday: Set of page paths that already gave XP today   */
  var todayStr = new Date().toDateString();
  if (store.viewedTodayDate !== todayStr) {
    /* New day — reset the visited-pages set */
    store.viewedTodayDate = todayStr;
    store.viewedToday = [];
    saveStore(store);
  }
  store.viewedToday = store.viewedToday || [];

  function pageXPKey() {
    /* Use the path without trailing slash as a dedup key */
    return window.location.pathname.replace(/\/$/, '') || '/';
  }
  function canGainPageXP() {
    var key = pageXPKey();
    if (store.viewedToday.indexOf(key) !== -1) return false; /* already gave XP today */
    store.viewedToday.push(key);
    saveStore(store);
    return true;
  }

  /* ── XP / Levels ──────────────────────────────────────────── */
  var LEVELS = [
    { min: 0,    label: 'Новичок',    icon: '🏠' },
    { min: 100,  label: 'Искатель',   icon: '🔍' },
    { min: 300,  label: 'Охотник',    icon: '🎯' },
    { min: 600,  label: 'Эксперт',    icon: '⭐' },
    { min: 1000, label: 'Профи',      icon: '🏆' },
    { min: 2000, label: 'Инвестор',   icon: '💎' },
  ];
  function getLevel(xp) {
    for (var i = LEVELS.length - 1; i >= 0; i--) {
      if (xp >= LEVELS[i].min) return LEVELS[i];
    }
    return LEVELS[0];
  }
  function getNextLevel(xp) {
    for (var i = 0; i < LEVELS.length; i++) {
      if (xp < LEVELS[i].min) return LEVELS[i];
    }
    return null;
  }

  function gainXP(amount, reason) {
    var prev = store.xp;
    store.xp += amount;
    var prevLevel = getLevel(prev);
    var newLevel  = getLevel(store.xp);
    saveStore(store);
    showXPToast('+' + amount + ' XP' + (reason ? ' · ' + reason : ''));
    if (prevLevel.label !== newLevel.label) {
      setTimeout(function () { showAchievementToast(newLevel.icon, 'Новый уровень: ' + newLevel.label, 'Уровень повышен!'); }, 800);
      if (hasVibration) {
        if (isAndroid) navigator.vibrate([30, 30, 60, 30, 100]);
        else navigator.vibrate([20, 40, 80]);
      }
    }
    updateGameHUD();
    diUpdateAmbient();
    if (isAndroid) androidRippleXP();
  }

  /* ── Streak ───────────────────────────────────────────────── */
  (function checkStreak() {
    /* No streak XP on staff back-office pages */
    if (isStaffPage) return;
    var today = new Date().toDateString();
    var last  = store.lastVisit;
    if (last === today) return;
    var yesterday = new Date(Date.now() - 86400000).toDateString();
    if (last === yesterday) {
      store.streak += 1;
    } else if (last && last !== today) {
      store.streak = 1;
    } else {
      store.streak = 1;
    }
    store.lastVisit = today;
    saveStore(store);
    setTimeout(function () {
      gainXP(10, 'Ежедневный визит');
      if (store.streak > 1) {
        showAchievementToast('🔥', store.streak + '-дневная серия!', 'Заходите каждый день');
        if (hasDynamicIsland) diFlash('🔥 × ' + store.streak, '#f97316');
      }
    }, 2000);
  })();

  /* ── Achievements ─────────────────────────────────────────── */
  var ACHIEVEMENTS = [
    { id: 'first_view',   icon: '👀', title: 'Первый взгляд',    desc: 'Открыли первую квартиру',  xp: 20,   check: function(s){ return s.totalViews >= 1; } },
    { id: 'explorer',     icon: '🗺️', title: 'Исследователь',    desc: 'Просмотрели 10 объектов',  xp: 50,   check: function(s){ return s.totalViews >= 10; } },
    { id: 'first_fav',    icon: '❤️', title: 'Первое избранное',  desc: 'Добавили объект в избранное', xp: 30, check: function(s){ return s.totalFavs >= 1; } },
    { id: 'streak3',      icon: '🔥', title: 'На волне',          desc: '3 дня подряд',             xp: 60,   check: function(s){ return s.streak >= 3; } },
    { id: 'streak7',      icon: '⚡', title: 'Недельный марафон', desc: '7 дней подряд',            xp: 150,  check: function(s){ return s.streak >= 7; } },
    { id: 'cashback10k',  icon: '💰', title: 'Первый кэшбек',     desc: 'Накоплено 10 000 ₽',       xp: 100,  check: function(s){ return s.cashbackEarned >= 10000; } },
    { id: 'pro',          icon: '🏆', title: 'Профессионал',      desc: 'Достигли уровня Профи',    xp: 200,  check: function(s){ return s.xp >= 1000; } },
  ];

  function checkAchievements() {
    ACHIEVEMENTS.forEach(function (a) {
      if (store.achievements.indexOf(a.id) !== -1) return;
      if (a.check(store)) {
        store.achievements.push(a.id);
        saveStore(store);
        setTimeout(function () {
          showAchievementToast(a.icon, a.title, a.desc);
          gainXP(a.xp, 'Ачивка: ' + a.title);
          if (hasDynamicIsland) diFlash(a.icon + ' ' + a.title, '#0088CC');
        }, 1500);
      }
    });
  }

  /* ── Dynamic Island ──────────────────────────────────────── */
  var diPill = null;

  function createDIPill() {
    /* Disabled: conflicts with real Dynamic Island hardware in PWA/standalone mode.
       The system Dynamic Island is managed by iOS itself — our black pill is redundant. */
    return;
    diPill = document.createElement('div');
    diPill.id = 'di-pill';

    /* DI_TOP is the screen y-position of safe-area-inset-top.
       The real DI cutout sits at about DI_TOP - 37px (overlap into status bar).
       We position our pill just below the DI cutout so it frames it. */
    var pillTop = Math.max(0, DI_TOP - 40);

    diPill.style.cssText = [
      'position:fixed',
      'top:' + pillTop + 'px',
      'left:50%',
      'transform:translateX(-50%)',
      'width:126px',
      'height:37px',
      'background:#000',
      'border-radius:20px',
      'z-index:8999',
      'display:flex',
      'align-items:center',
      'justify-content:center',
      'overflow:hidden',
      'transition:all 0.45s cubic-bezier(0.32,0,0,1)',
      'cursor:pointer',
      'pointer-events:auto',
      'box-shadow:0 0 0 1px rgba(255,255,255,0.08)',
    ].join(';');

    /* Ambient content: tiny brand dot + XP */
    var lvl = getLevel(store.xp);
    diPill.innerHTML = [
      '<div id="di-content" style="transition:opacity 0.2s;display:flex;align-items:center;gap:6px;padding:0 12px;white-space:nowrap;font-size:13px;font-weight:700;color:#fff;font-family:-apple-system,sans-serif">',
        '<span style="width:8px;height:8px;border-radius:50%;background:#0088CC;display:inline-block;flex-shrink:0"></span>',
        '<span id="di-ambient-text" style="font-size:12px;color:rgba(255,255,255,0.85)">' + lvl.icon + ' ' + store.xp + ' XP</span>',
      '</div>',
    ].join('');
    document.body.appendChild(diPill);

    diPill.addEventListener('click', function () {
      showStatsPanel();
      spawnMoneyRain(8);
      if (hasVibration) navigator.vibrate(10);
    });
  }

  /* Refresh ambient text after XP changes */
  function diUpdateAmbient() {
    if (!diPill) return;
    var txt = diPill.querySelector('#di-ambient-text');
    if (!txt) return;
    var lvl = getLevel(store.xp);
    if (store.cashbackEarned > 0) {
      var fmtC = store.cashbackEarned >= 1000
        ? Math.round(store.cashbackEarned / 1000) + 'K'
        : store.cashbackEarned;
      txt.textContent = '💰 ' + fmtC + ' ₽';
      txt.style.color = '#4ade80';
    } else {
      txt.textContent = lvl.icon + ' ' + store.xp + ' XP';
      txt.style.color = 'rgba(255,255,255,0.85)';
    }
  }

  var diTimer = null;
  function diExpand(contentHTML, bgColor, duration) {
    if (!diPill) createDIPill();
    if (!diPill) return;
    clearTimeout(diTimer);
    var content = diPill.querySelector('#di-content');
    content.style.opacity = '0';

    diPill.style.width = '220px';
    diPill.style.height = '50px';
    diPill.style.borderRadius = '26px';
    diPill.style.background = bgColor || '#000';
    setTimeout(function () {
      content.innerHTML = contentHTML;
      content.style.opacity = '1';
    }, 120);

    diTimer = setTimeout(diCollapse, duration || 3500);
  }

  function diCollapse() {
    if (!diPill) return;
    var content = diPill.querySelector('#di-content');
    if (content) content.style.opacity = '0';
    setTimeout(function () {
      diPill.style.width = '126px';
      diPill.style.height = '37px';
      diPill.style.borderRadius = '20px';
      diPill.style.background = '#000';
      /* Restore ambient content after collapse */
      setTimeout(function() {
        diUpdateAmbient();
        if (content) content.style.opacity = '1';
      }, 200);
    }, 150);
  }

  function diFlash(text, color) {
    if (!hasDynamicIsland) return;
    createDIPill();
    diExpand('<span>' + text + '</span>', color || '#0088CC', 3000);
  }

  /* ── Universal Cashback Flash (for all non-DI devices) ────── */
  /* Shows a sleek cashback pill at the top of screen + money rain */
  function showCashbackFlash(amount) {
    var formatted = amount >= 1000000
      ? (amount / 1000000).toFixed(1) + 'M'
      : amount >= 1000 ? Math.round(amount / 1000) + 'K' : amount;

    var pill = document.createElement('div');
    /* On mobile browser: show at bottom to avoid header overlap */
    var cashbackPos = (isMobile && !isStandalone)
      ? ('bottom:' + (BOTTOM_NAV_H + 16) + 'px')
      : 'top:env(safe-area-inset-top,70px)';
    pill.style.cssText = [
      'position:fixed',
      cashbackPos,
      'left:50%',
      'transform:translateX(-50%) scale(0.85)',
      'background:linear-gradient(135deg,#0f172a,#064e3b)',
      'border:1px solid rgba(74,222,128,0.3)',
      'border-radius:24px',
      'padding:10px 20px',
      'z-index:8997',
      'display:flex',
      'align-items:center',
      'gap:10px',
      'opacity:0',
      'transition:all 0.4s cubic-bezier(0.34,1.56,0.64,1)',
      'pointer-events:none',
      'box-shadow:0 8px 32px rgba(0,0,0,0.4)',
      'backdrop-filter:blur(20px)',
    ].join(';');

    pill.innerHTML = [
      '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#4ade80" stroke-width="2.5">',
        '<circle cx="12" cy="12" r="10"/>',
        '<path stroke-linecap="round" d="M12 6v12M9 9h4.5a1.5 1.5 0 010 3h-3a1.5 1.5 0 000 3H15"/>',
      '</svg>',
      '<span style="color:#4ade80;font-weight:800;font-size:16px;font-family:-apple-system,system-ui,sans-serif">',
        '+' + formatted + ' ₽ кэшбек',
      '</span>',
      '<span style="font-size:14px">💰</span>',
    ].join('');

    document.body.appendChild(pill);
    requestAnimationFrame(function() {
      pill.style.opacity = '1';
      pill.style.transform = 'translateX(-50%) scale(1)';
    });

    /* Trigger money rain for everyone */
    setTimeout(function() { spawnMoneyRain(6); }, 300);
    if (hasVibration) navigator.vibrate([10, 20, 40]);

    /* Collapse after 3.5s */
    setTimeout(function() {
      pill.style.opacity = '0';
      pill.style.transform = 'translateX(-50%) scale(0.85)';
      setTimeout(function() { if (pill.parentNode) pill.parentNode.removeChild(pill); }, 400);
    }, 3500);
  }

  function diShowCashback(amount) {
    if (!hasDynamicIsland) return;
    createDIPill();
    var formatted = amount >= 1000000
      ? (amount / 1000000).toFixed(1) + 'M'
      : amount >= 1000 ? Math.round(amount / 1000) + 'K' : amount;
    diExpand(
      '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#4ade80" stroke-width="2.5"><circle cx="12" cy="12" r="10"/><path stroke-linecap="round" d="M12 6v12M9 9h4.5a1.5 1.5 0 010 3h-3a1.5 1.5 0 000 3H15"/></svg>' +
      '<span style="color:#4ade80">+' + formatted + ' ₽</span>',
      'linear-gradient(135deg,#0f172a,#064e3b)',
      4000
    );
    spawnMoneyRain(8);
    if (hasVibration) navigator.vibrate([10, 20, 40]);
  }

  /* ── Money Rain ───────────────────────────────────────────── */
  function spawnMoneyRain(count) {
    var symbols = ['₽', '💰', '💸', '🪙', '₽', '₽'];
    var container = document.createElement('div');
    container.style.cssText = 'position:fixed;top:0;left:0;right:0;bottom:0;pointer-events:none;z-index:8998;overflow:hidden';
    document.body.appendChild(container);

    var startY = hasDynamicIsland ? (DI_TOP + 10) : 60;

    for (var i = 0; i < count; i++) {
      (function (i) {
        setTimeout(function () {
          var coin = document.createElement('div');
          var symbol = symbols[Math.floor(Math.random() * symbols.length)];
          var x = 20 + Math.random() * 60; /* % from left */
          var rot = -20 + Math.random() * 40;
          var size = 14 + Math.random() * 12;
          coin.textContent = symbol;
          coin.style.cssText = [
            'position:absolute',
            'left:' + x + '%',
            'top:' + startY + 'px',
            'font-size:' + size + 'px',
            'opacity:1',
            'transform:rotate(' + rot + 'deg)',
            'animation:moneyFall ' + (1.2 + Math.random() * 0.8) + 's ease-in forwards',
            'will-change:transform,opacity',
          ].join(';');
          container.appendChild(coin);
        }, i * 80);
      })(i);
    }

    setTimeout(function () {
      if (container.parentNode) container.parentNode.removeChild(container);
    }, 4000);
  }

  /* Inject keyframes once */
  var styleTag = document.getElementById('pwa-game-styles');
  if (!styleTag) {
    styleTag = document.createElement('style');
    styleTag.id = 'pwa-game-styles';
    styleTag.textContent = [
      '@keyframes moneyFall{0%{transform:translateY(0) rotate(var(--r,0deg));opacity:1}80%{opacity:1}100%{transform:translateY(60vh) rotate(calc(var(--r,0deg) + 180deg));opacity:0}}',
      '@keyframes xpPop{0%{transform:scale(0.5) translateY(0);opacity:1}60%{transform:scale(1.2) translateY(-30px);opacity:1}100%{transform:scale(1) translateY(-60px);opacity:0}}',
      '@keyframes achieveSlide{0%{transform:translateX(110%);opacity:0}15%{transform:translateX(0);opacity:1}80%{transform:translateX(0);opacity:1}100%{transform:translateX(110%);opacity:0}}',
      '@keyframes orb-pulse{0%,100%{box-shadow:0 0 0 0 rgba(0,136,204,0.4)}50%{box-shadow:0 0 0 12px rgba(0,136,204,0)}}',
      '@keyframes ring-fill{from{stroke-dashoffset:var(--dash-max)}to{stroke-dashoffset:var(--dash-val)}}',
      '@keyframes android-ripple{0%{transform:scale(0);opacity:0.6}100%{transform:scale(4);opacity:0}}',
      '@keyframes coinSpin{0%{transform:rotateY(0deg)}100%{transform:rotateY(360deg)}}',
      '@keyframes hudSlide{0%{opacity:0;transform:translateY(20px)}100%{opacity:1;transform:translateY(0)}}',
      '@keyframes hudArmWave{0%,100%{transform:rotate(-25deg)}50%{transform:rotate(25deg)}}',
      /* ── Mascot animations ── */
      '@keyframes mascotBob{0%,100%{transform:translateY(0)}50%{transform:translateY(-6px)}}',
      '@keyframes mascotArmWave{0%{transform:rotate(0deg)}30%{transform:rotate(-40deg)}55%{transform:rotate(5deg)}75%{transform:rotate(-25deg)}100%{transform:rotate(0deg)}}',
      '@keyframes mascotLegL{0%,100%{transform:rotate(-20deg)}50%{transform:rotate(20deg)}}',
      '@keyframes mascotLegR{0%,100%{transform:rotate(20deg)}50%{transform:rotate(-20deg)}}',
      '@keyframes mascotJump{0%{transform:translateY(0) scale(1)}25%{transform:translateY(-22px) scale(1.05) rotate(-4deg)}55%{transform:translateY(-10px) scale(0.97) rotate(3deg)}100%{transform:translateY(0) scale(1) rotate(0)}}',
      '@keyframes mascotBlink{0%,90%,100%{transform:scaleY(1)}95%{transform:scaleY(0.08)}}',
      '@keyframes mascotShadowPulse{0%,100%{transform:scaleX(1);opacity:0.2}50%{transform:scaleX(0.75);opacity:0.1}}',
      '@keyframes mascotXpFloat{0%,100%{transform:translateY(0)}50%{transform:translateY(-3px)}}',
      '@keyframes mascotPeekRaise{0%{transform:translateY(0)}100%{transform:translateY(-8px)}}',
      '@keyframes mascotTailWag{0%,100%{transform:rotate(-12deg)}50%{transform:rotate(18deg)}}',
    ].join('');
    document.head.appendChild(styleTag);
  }

  /* ── XP Toast ─────────────────────────────────────────────── */
  function showXPToast(text) {
    // Suppress XP toast when any fullscreen map is open
    var fscMap = document.getElementById('fullscreenComplexesMapModal');
    if (fscMap && !fscMap.classList.contains('hidden')) return;
    var fscPropMap = document.getElementById('fullscreenMapModal');
    if (fscPropMap && !fscPropMap.classList.contains('hidden')) return;
    var t = document.createElement('div');
    t.textContent = text;
    t.style.cssText = [
      'position:fixed',
      'bottom:' + toastBottom(),
      'left:50%',
      'transform:translateX(-50%)',
      'background:rgba(0,136,204,0.92)',
      'color:#fff',
      'font-size:13px',
      'font-weight:700',
      'padding:7px 16px',
      'border-radius:20px',
      'z-index:8997',
      'pointer-events:none',
      'animation:xpPop 1.6s ease forwards',
      'white-space:nowrap',
      'backdrop-filter:blur(8px)',
    ].join(';');
    document.body.appendChild(t);
    setTimeout(function () { if (t.parentNode) t.parentNode.removeChild(t); }, 1700);
  }

  /* ── Achievement Toast ────────────────────────────────────── */
  function showAchievementToast(icon, title, desc) {
    var t = document.createElement('div');
    /* On mobile browser: show at bottom above nav (avoids sticky header overlap).
       On standalone or desktop: show at top. */
    var useBottom = isMobile && !isStandalone;
    t.style.cssText = [
      'position:fixed',
      useBottom
        ? ('bottom:' + (BOTTOM_NAV_H + 16) + 'px')
        : ('top:' + (hasDynamicIsland && isStandalone ? (DI_TOP + 55) : isIOS ? '70px' : '70px')),
      'right:16px',
      'background:rgba(15,23,42,0.96)',
      'color:#fff',
      'border-radius:16px',
      'padding:12px 16px',
      'z-index:8995',
      'display:flex',
      'align-items:center',
      'gap:12px',
      'min-width:240px',
      'max-width:calc(100vw - 32px)',
      'animation:achieveSlide 4s ease forwards',
      'pointer-events:none',
      'backdrop-filter:blur(12px)',
      'border:1px solid rgba(255,255,255,0.1)',
      'box-shadow:0 8px 32px rgba(0,0,0,0.4)',
    ].join(';');
    t.innerHTML = [
      '<div style="font-size:28px;line-height:1">' + icon + '</div>',
      '<div>',
      '  <div style="font-size:11px;text-transform:uppercase;letter-spacing:0.05em;color:#0088CC;font-weight:700;margin-bottom:2px">Достижение</div>',
      '  <div style="font-size:14px;font-weight:700">' + title + '</div>',
      '  <div style="font-size:12px;color:rgba(255,255,255,0.6);margin-top:1px">' + desc + '</div>',
      '</div>',
    ].join('');
    document.body.appendChild(t);
    setTimeout(function () { if (t.parentNode) t.parentNode.removeChild(t); }, 4100);
  }

  /* ══════════════════════════════════════════════════════════════
     QUEST SYSTEM — mascot thinks and gives context-aware tasks
     ══════════════════════════════════════════════════════════════ */

  /* Detect current city slug from URL path (e.g. /krasnodar/...) */
  var _citySlugMatch = window.location.pathname.match(/^\/(krasnodar|sochi|anapa|gelendzhik|novorossiysk|armavir|tuapse|maikop)(\/|$)/);
  var _city = _citySlugMatch ? _citySlugMatch[1] : 'krasnodar';

  var QUESTS = [
    { id:'q_search',   icon:'🔍', text:'Найдите квартиру по фильтрам',   cta:'Открыть поиск',   url:'/' + _city + '/novostrojki',          xp:30 },
    { id:'q_complex',  icon:'🏙️', text:'Посмотрите жилые комплексы',      cta:'Смотреть ЖК',     url:'/' + _city + '/zhilye-kompleksy',     xp:25 },
    { id:'q_cashback', icon:'💰', text:'Узнайте размер своего кэшбека',   cta:'Рассчитать',      url:'/kak-eto-rabotaet',                   xp:20 },
    { id:'q_map',      icon:'🗺️', text:'Найдите квартиру на карте',       cta:'Открыть карту',   url:'/' + _city + '/novostrojki?view=map', xp:35 },
    { id:'q_consult',  icon:'💬', text:'Напишите менеджеру — бесплатно', cta:'Написать нам',    action:'chat',                             xp:40 },
    { id:'q_fav',      icon:'❤️', text:'Добавьте объект в избранное',     cta:'К недвижимости',  url:'/' + _city + '/novostrojki',          xp:25 },
    { id:'q_blog',     icon:'📰', text:'Читайте советы по покупке жилья', cta:'В блог',          url:'/blog',                               xp:15 },
    { id:'q_calc',     icon:'🧮', text:'Рассчитайте ипотеку онлайн',      cta:'Калькулятор',     url:'/' + _city + '/ipoteka',              xp:20 },
  ];

  var _questEl    = null;
  var _thinkingEl = null;
  var _activeQuestId = null;

  function _getNextQuest() {
    var done = store.completedQuests || [];
    /* Filter out done quests; if all done — reset cycle */
    var available = QUESTS.filter(function(q) { return done.indexOf(q.id) === -1; });
    if (!available.length) {
      store.completedQuests = [];
      saveStore(store);
      available = QUESTS.slice();
    }
    /* Pick one matching current page context first, else random */
    var path = window.location.pathname;
    var contextual = available.filter(function(q) {
      if (!q.url) return false;
      /* Don't suggest what we're already on */
      return !path.includes(q.url.split('?')[0].replace('/krasnodar','').replace('/',''));
    });
    var pool = contextual.length ? contextual : available;
    return pool[Math.floor(Math.random() * pool.length)];
  }

  function _showQuestBubble() {
    if (!_hudWalkedIn || !hudEl || isStaffPage) return;
    /* Don't stack quests */
    if (_questEl && document.body.contains(_questEl)) return;

    var quest = _getNextQuest();
    if (!quest) return;
    _activeQuestId = quest.id;

    /* Phase 1: mascot thinking animation (eyes look up, thought bubble) */
    _showThinkingBubble();

    /* Phase 2: after 2s thinking, hide bubble and show quest card */
    setTimeout(function() {
      _hideThinkingBubble();
      _renderQuestCard(quest);
    }, 2100);
  }

  function _showThinkingBubble() {
    if (_thinkingEl && document.body.contains(_thinkingEl)) return;
    var hb = parseInt(hudEl ? hudEl.style.bottom : '90') || 90;

    _thinkingEl = document.createElement('div');
    _thinkingEl.style.cssText = [
      'position:fixed', 'left:82px', 'bottom:' + (hb + 52) + 'px',
      'z-index:9001', 'pointer-events:none',
      'opacity:0', 'transition:opacity 0.25s ease',
    ].join(';');
    _thinkingEl.innerHTML = [
      '<div style="background:rgba(255,255,255,0.96);border-radius:14px 14px 4px 14px;',
        'padding:8px 14px;box-shadow:0 6px 24px rgba(0,0,0,0.13);',
        'border:1px solid rgba(0,136,204,0.12);display:flex;gap:5px;align-items:center">',
        '<span style="font-size:17px">🤔</span>',
        '<span class="chat-typing-dot" style="width:6px;height:6px;background:#9ca3af;border-radius:50%;display:inline-block;animation:chatTypingDot 1.2s ease-in-out infinite"></span>',
        '<span class="chat-typing-dot" style="width:6px;height:6px;background:#9ca3af;border-radius:50%;display:inline-block;animation:chatTypingDot 1.2s ease-in-out 0.15s infinite"></span>',
        '<span class="chat-typing-dot" style="width:6px;height:6px;background:#9ca3af;border-radius:50%;display:inline-block;animation:chatTypingDot 1.2s ease-in-out 0.3s infinite"></span>',
      '</div>',
    ].join('');
    document.body.appendChild(_thinkingEl);
    var _capturedThinkingEl = _thinkingEl;
    requestAnimationFrame(function() { if (_capturedThinkingEl) _capturedThinkingEl.style.opacity = '1'; });

    /* Raise mascot eyebrows — slight jump */
    if (hudEl) {
      var bodyG = hudEl.querySelector('#mascot-body-group');
      if (bodyG) {
        bodyG.style.animation = 'mascotPeekRaise 0.6s ease-in-out 3 alternate';
        setTimeout(function() {
          bodyG.style.animation = 'mascotBob 2.4s ease-in-out infinite';
        }, 2000);
      }
    }
  }

  function _hideThinkingBubble() {
    if (!_thinkingEl) return;
    _thinkingEl.style.opacity = '0';
    var el = _thinkingEl;
    setTimeout(function() { if (el.parentNode) el.parentNode.removeChild(el); }, 280);
    _thinkingEl = null;
  }

  function _renderQuestCard(quest) {
    if (_questEl && document.body.contains(_questEl)) return;
    var hb = parseInt(hudEl ? hudEl.style.bottom : '90') || 90;

    _questEl = document.createElement('div');
    _questEl.style.cssText = [
      'position:fixed', 'left:82px', 'bottom:' + hb + 'px',
      'z-index:9001', 'width:210px',
      'transform:translateX(-16px) scale(0.95)', 'opacity:0',
      'transition:transform 0.3s cubic-bezier(0.34,1.56,0.64,1),opacity 0.25s ease',
    ].join(';');

    var actionBtn = quest.action === 'chat'
      ? '<button onclick="window._acceptQuest(\'' + quest.id + '\',\'chat\')" style="flex:1;background:linear-gradient(135deg,#0088CC,#006699);color:#fff;border:none;border-radius:10px;padding:7px 0;font-size:12px;font-weight:600;cursor:pointer">' + quest.cta + '</button>'
      : '<a href="' + quest.url + '" onclick="window._acceptQuest(\'' + quest.id + '\',\'link\')" style="flex:1;display:block;background:linear-gradient(135deg,#0088CC,#006699);color:#fff;border-radius:10px;padding:7px 0;font-size:12px;font-weight:600;text-align:center;text-decoration:none">' + quest.cta + '</a>';

    _questEl.innerHTML = [
      '<div style="background:rgba(10,20,40,0.96);border-radius:16px;padding:14px 15px;',
        'box-shadow:0 8px 32px rgba(0,0,0,0.4);border:1px solid rgba(0,136,204,0.3);',
        'backdrop-filter:blur(16px);color:#fff;font-family:-apple-system,system-ui,sans-serif;position:relative">',
        '<div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:8px">',
          '<div style="font-size:10px;color:#0088CC;font-weight:700;text-transform:uppercase;letter-spacing:0.05em">⚡ Задание</div>',
          '<button onclick="window._dismissQuest()" style="background:rgba(255,255,255,0.08);border:none;border-radius:7px;color:rgba(255,255,255,0.35);width:22px;height:22px;cursor:pointer;font-size:13px;display:flex;align-items:center;justify-content:center;flex-shrink:0">✕</button>',
        '</div>',
        '<div style="font-size:13px;font-weight:600;line-height:1.4;margin-bottom:11px">',
          quest.icon + ' ' + quest.text,
        '</div>',
        '<div style="display:flex;gap:8px;align-items:center">',
          actionBtn,
          '<div style="font-size:10px;color:rgba(255,255,255,0.4);white-space:nowrap;flex-shrink:0">+' + quest.xp + ' XP</div>',
        '</div>',
        /* Arrow pointing left toward mascot */
        '<div style="position:absolute;left:-5px;top:50%;margin-top:-5px;width:10px;height:10px;',
          'background:rgba(10,20,40,0.96);border-left:1px solid rgba(0,136,204,0.25);',
          'border-bottom:1px solid rgba(0,136,204,0.25);transform:rotate(45deg)"></div>',
      '</div>',
    ].join('');

    document.body.appendChild(_questEl);
    requestAnimationFrame(function() {
      _questEl.style.transform = 'translateX(0) scale(1)';
      _questEl.style.opacity   = '1';
    });

    /* Auto-dismiss after 14s */
    var _autoTimer = setTimeout(function() { window._dismissQuest(); }, 14000);
    _questEl._autoTimer = _autoTimer;
  }

  window._dismissQuest = function() {
    if (!_questEl) return;
    if (_questEl._autoTimer) clearTimeout(_questEl._autoTimer);
    _questEl.style.transform = 'translateX(-16px) scale(0.95)';
    _questEl.style.opacity   = '0';
    var el = _questEl;
    setTimeout(function() { if (el && el.parentNode) el.parentNode.removeChild(el); }, 280);
    _questEl = null;
    _activeQuestId = null;
  };

  window._acceptQuest = function(questId, type) {
    var quest = QUESTS.filter(function(q){ return q.id === questId; })[0];
    if (!quest) return;
    /* Mark as completed */
    var done = store.completedQuests || [];
    if (done.indexOf(questId) === -1) {
      done.push(questId);
      store.completedQuests = done;
      saveStore(store);
    }
    window._dismissQuest();
    if (type === 'chat') {
      if (typeof window.openInBackChat === 'function') window.openInBackChat();
    }
    /* XP reward fires on next page load via localStorage */
    setTimeout(function() { gainXP(quest.xp, quest.icon + ' ' + quest.text); }, 300);
  };

  /* ── Game HUD: Creative Mascot (peeks from right edge → walks in) ── */
  var hudEl = null;
  var _hudWalkedIn = false;
  var _hudBlinkTimer = null;

  function _mascotSVG(level, pct) {
    /* Clean circle logo mascot — minimal and professional */
    return [
      '<svg id="mascot-char-svg" width="58" height="68" viewBox="0 0 58 68"',
      ' style="overflow:visible;display:block;filter:drop-shadow(0 4px 14px rgba(0,136,204,0.40))">',

        /* ── Shadow ── */
        '<ellipse cx="29" cy="67" rx="13" ry="3.5"',
        ' fill="rgba(0,0,0,0.14)"',
        ' style="transform-origin:29px 67px;animation:mascotShadowPulse 2s ease-in-out infinite"/>',

        /* ── Hidden stubs so existing walk/leg JS finds the IDs ── */
        '<g id="mascot-leg-l" style="display:none;transform-origin:23px 51px;animation:mascotLegL 0.38s ease-in-out infinite;animation-play-state:paused"/>',
        '<g id="mascot-leg-r" style="display:none;transform-origin:31px 51px;animation:mascotLegR 0.38s ease-in-out infinite;animation-play-state:paused"/>',
        '<g id="mascot-tail" style="display:none"/>',

        /* ── Main circle (bobs on idle) ── */
        '<g id="mascot-body-group"',
        ' style="transform-origin:29px 29px;animation:mascotBob 2.4s ease-in-out infinite">',

          /* Soft outer ring */
          '<circle cx="29" cy="29" r="27" fill="rgba(0,136,204,0.10)"/>',
          /* Background circle */
          '<circle cx="29" cy="29" r="23" fill="#0088CC"/>',
          /* Top-left shine */
          '<circle cx="20" cy="20" r="7" fill="rgba(255,255,255,0.14)"/>',

          /* "in" brand text */
          '<text x="29" y="37"',
          ' text-anchor="middle"',
          ' font-size="22"',
          ' fill="white"',
          ' font-weight="900"',
          ' font-family="-apple-system,BlinkMacSystemFont,Helvetica Neue,sans-serif"',
          ' letter-spacing="-1">in</text>',

          /* Hidden stubs for animation targeting */
          '<g id="mascot-eyes-wrap" style="display:none"/>',
          '<g id="mascot-arm-r" style="display:none;transform-origin:29px 29px;animation:mascotArmWave 1.8s ease-in-out infinite"/>',

        '</g>',

      '</svg>',
    ].join('');
  }

  function createGameHUD() {
    /* Mascot is desktop-only — on mobile it conflicts with bottom nav + chat FAB */
    if (isMobile || window.innerWidth < 768) return;
    if (hudEl) return;
    hudEl = document.createElement('div');
    hudEl.id = 'game-hud';
    /* Start fully off-screen to the right */
    hudEl.style.cssText = [
      'position:fixed',
      'left:-82px',            /* off-screen left — head peeks from left edge */
      'bottom:' + hudBottom(),
      'z-index:8999',
      'display:flex',
      'flex-direction:column',
      'align-items:flex-start',
      'gap:6px',
      'pointer-events:auto',
      'cursor:pointer',
      'transition:left 0.65s cubic-bezier(0.34,1.56,0.64,1)',
      'will-change:left',
    ].join(';');

    document.body.appendChild(hudEl);
    updateGameHUD();

    /* ── Phase 1 (1.2s): PEEK — slide right so head is visible ── */
    setTimeout(function () {
      hudEl.style.left = '-34px';  /* ~head-width peeking from left */
    }, 1200);

    /* ── Phase 2 (2.5s): WALK IN — slide fully into view ── */
    setTimeout(function () {
      /* Start leg walking animation */
      var legL = hudEl.querySelector('#mascot-leg-l');
      var legR = hudEl.querySelector('#mascot-leg-r');
      if (legL) legL.style.animationPlayState = 'running';
      if (legR) legR.style.animationPlayState = 'running';

      hudEl.style.transition = 'left 0.72s cubic-bezier(0.25,0.46,0.45,0.94)';
      hudEl.style.left = '8px';
    }, 2500);

    /* ── Phase 3 (3.3s): ARRIVED — stop walking, show XP badge + tooltip ── */
    setTimeout(function () {
      _hudWalkedIn = true;
      var legL = hudEl.querySelector('#mascot-leg-l');
      var legR = hudEl.querySelector('#mascot-leg-r');
      if (legL) legL.style.animationPlayState = 'paused';
      if (legR) legR.style.animationPlayState = 'paused';
      /* Reveal the XP badge chip */
      var chip = document.getElementById('hud-xp-chip');
      if (chip) {
        chip.style.opacity = '0';
        chip.style.display = 'block';
        chip.style.transition = 'opacity 0.4s ease';
        setTimeout(function(){ chip.style.opacity = '1'; }, 50);
      }
      /* Jump to celebrate arrival */
      var bodyG = hudEl.querySelector('#mascot-body-group');
      if (bodyG) {
        bodyG.style.animation = 'mascotJump 0.55s ease forwards';
        setTimeout(function(){
          bodyG.style.animation = 'mascotBob 2.4s ease-in-out infinite';
        }, 600);
      }
      /* Mascot is now on the left — no need to shift chat FAB on the right */
      /* Show intro tooltip callout (desktop only, disappears after 5s) */
      if (!isMobile) {
        _showMascotTooltip('Мой прогресс', '🎮 Нажмите, чтобы\nувидеть статистику', true);
      }
    }, 3300);

    /* ── Quest cycle: mascot "thinks" then presents a task ── */
    setTimeout(function() {
      _showQuestBubble();
      /* Repeat every 4 minutes if page is visible */
      setInterval(function() {
        if (!document.hidden && _hudWalkedIn) _showQuestBubble();
      }, 4 * 60 * 1000);
    }, 9000);

    /* Hover tooltip on desktop */
    if (!isMobile) {
      var _hoverTooltipTimer = null;
      hudEl.addEventListener('mouseenter', function () {
        if (!_hudWalkedIn) return;
        _hoverTooltipTimer = setTimeout(function () {
          _showMascotTooltip(getLevel(store.xp).label, store.xp + ' XP · Нажмите', false);
        }, 600);
      });
      hudEl.addEventListener('mouseleave', function () {
        clearTimeout(_hoverTooltipTimer);
        var t = document.getElementById('mascot-tooltip');
        if (t) { t.style.opacity = '0'; setTimeout(function(){ if(t.parentNode) t.parentNode.removeChild(t); }, 250); }
      });
    }

    /* Tap anywhere on HUD → stats */
    hudEl.addEventListener('click', function () {
      /* Remove tooltip on click */
      var t = document.getElementById('mascot-tooltip');
      if (t && t.parentNode) t.parentNode.removeChild(t);
      showStatsPanel();
      if (hasVibration) navigator.vibrate(10);
      /* Little jump on tap */
      var bodyG = hudEl.querySelector('#mascot-body-group');
      if (bodyG && _hudWalkedIn) {
        bodyG.style.animation = 'mascotJump 0.45s ease forwards';
        setTimeout(function(){ bodyG.style.animation = 'mascotBob 2.4s ease-in-out infinite'; }, 500);
      }
    });
  }

  /* ── Mascot tooltip callout (speech bubble to the left) ── */
  function _showMascotTooltip(title, body, autoHide) {
    /* Remove existing */
    var old = document.getElementById('mascot-tooltip');
    if (old && old.parentNode) old.parentNode.removeChild(old);

    var tip = document.createElement('div');
    tip.id = 'mascot-tooltip';
    var hudBottom = hudEl ? parseInt(hudEl.style.bottom || '90') : 90;
    tip.style.cssText = [
      'position:fixed',
      'left:86px',              /* to the right of the 58px mascot + 16px gap */
      'bottom:' + (typeof hudBottom === 'number' ? hudBottom + 8 : '98') + 'px',
      'background:rgba(10,20,40,0.95)',
      'color:#fff',
      'font-size:12px',
      'font-family:-apple-system,system-ui,sans-serif',
      'border-radius:12px',
      'padding:10px 14px',
      'max-width:160px',
      'min-width:130px',
      'pointer-events:none',
      'z-index:9000',
      'opacity:0',
      'transition:opacity 0.3s ease',
      'box-shadow:0 4px 20px rgba(0,0,0,0.45)',
      'border:1px solid rgba(0,136,204,0.25)',
      'backdrop-filter:blur(12px)',
      'white-space:pre-line',
      'line-height:1.5',
    ].join(';');
    /* Small arrow pointing right toward mascot */
    var lines = body.split('\n');
    tip.innerHTML = [
      '<div style="font-size:11px;font-weight:700;color:#0088CC;text-transform:uppercase;letter-spacing:0.04em;margin-bottom:4px">' + title + '</div>',
      '<div style="font-size:12px;color:rgba(255,255,255,0.82)">' + lines.join('<br>') + '</div>',
      /* Arrow pointing left toward mascot */
      '<div style="position:absolute;left:-6px;top:50%;margin-top:-6px;width:12px;height:12px;background:rgba(10,20,40,0.95);border-left:1px solid rgba(0,136,204,0.25);border-bottom:1px solid rgba(0,136,204,0.25);transform:rotate(45deg)"></div>',
    ].join('');

    document.body.appendChild(tip);
    requestAnimationFrame(function(){ tip.style.opacity = '1'; });

    if (autoHide) {
      setTimeout(function () {
        if (tip.parentNode) {
          tip.style.opacity = '0';
          setTimeout(function(){ if(tip.parentNode) tip.parentNode.removeChild(tip); }, 300);
        }
      }, 5000);
    }
  }

  function updateGameHUD() {
    if (!hudEl) return;
    var level = getLevel(store.xp);
    var next  = getNextLevel(store.xp);
    var pct   = next ? Math.round(((store.xp - level.min) / (next.min - level.min)) * 100) : 100;

    /* XP badge chip (hidden until walk-in completes) */
    var chipHtml = [
      '<div id="hud-xp-chip" style="display:none;background:rgba(0,0,0,0.75);',
      'color:#fff;font-size:11px;font-weight:700;padding:4px 10px;border-radius:12px;',
      'backdrop-filter:blur(10px);white-space:nowrap;pointer-events:none;',
      'border:1px solid rgba(0,136,204,0.4);text-align:center;',
      'animation:mascotXpFloat 3s ease-in-out infinite">',
        level.icon + ' ' + level.label,
      '</div>',
    ].join('');

    /* Cashback chip */
    var cashHtml = '';
    if (store.cashbackEarned > 0) {
      var fmtCash = store.cashbackEarned >= 1000
        ? Math.round(store.cashbackEarned / 1000) + 'K ₽'
        : store.cashbackEarned + ' ₽';
      cashHtml = [
        '<div style="background:linear-gradient(135deg,rgba(5,150,105,0.88),rgba(6,78,59,0.88));',
        'color:#4ade80;font-size:10px;font-weight:800;padding:3px 9px;border-radius:10px;',
        'pointer-events:none;backdrop-filter:blur(8px);white-space:nowrap;',
        'border:1px solid rgba(74,222,128,0.3)">💰 ' + fmtCash + '</div>',
      ].join('');
    }

    /* Streak chip */
    var streakHtml = '';
    if (store.streak > 1) {
      streakHtml = [
        '<div style="background:rgba(249,115,22,0.85);color:#fff;font-size:10px;',
        'font-weight:700;padding:3px 8px;border-radius:10px;pointer-events:none;',
        'backdrop-filter:blur(8px);white-space:nowrap">🔥 ' + store.streak + ' дней</div>',
      ].join('');
    }

    hudEl.innerHTML = [
      chipHtml,
      cashHtml,
      streakHtml,
      /* Mascot character */
      '<div id="hud-mascot" title="Уровень: ' + level.label + ' · ' + store.xp + ' XP · Нажмите для статистики">',
        _mascotSVG(level, pct),
      '</div>',
    ].join('');

    /* Re-attach leg state after innerHTML replace */
    if (_hudWalkedIn) {
      var chip = document.getElementById('hud-xp-chip');
      if (chip) chip.style.display = 'block';
    }
  }

  /* ── Stats Panel ──────────────────────────────────────────── */
  function showStatsPanel() {
    var existing = document.getElementById('game-stats-panel');
    if (existing) { existing.parentNode.removeChild(existing); return; }

    var level = getLevel(store.xp);
    var next  = getNextLevel(store.xp);
    var xpToNext = next ? (next.min - store.xp) : 0;
    var pct   = next ? Math.round(((store.xp - level.min) / (next.min - level.min)) * 100) : 100;

    var unlockedCount = store.achievements.length;
    var totalCount    = ACHIEVEMENTS.length;

    var panel = document.createElement('div');
    panel.id  = 'game-stats-panel';
    /* Panel always opens to the RIGHT of the mascot (mascot anchored left:8px, ~74px wide) */
    var mascotRight = 8 + 74 + 8; /* 90px from left edge */
    panel.style.cssText = [
      'position:fixed',
      'left:' + mascotRight + 'px',
      'bottom:' + statsPanelBottom(),
      'width:min(240px,calc(100vw - ' + (mascotRight + 16) + 'px))',
      'background:rgba(10,20,40,0.96)',
      'border:1px solid rgba(0,136,204,0.3)',
      'border-radius:20px',
      'padding:16px',
      'z-index:8995',
      'color:#fff',
      'font-family:-apple-system,system-ui,sans-serif',
      'animation:hudSlide 0.3s ease',
      'backdrop-filter:blur(20px)',
    ].join(';');

    panel.innerHTML = [
      '<div style="display:flex;align-items:center;gap:10px;margin-bottom:14px">',
        '<div style="font-size:32px">' + level.icon + '</div>',
        '<div>',
          '<div style="font-size:12px;color:#0088CC;font-weight:700;text-transform:uppercase;letter-spacing:0.05em">' + level.label + '</div>',
          '<div style="font-size:20px;font-weight:800">' + store.xp + ' XP</div>',
        '</div>',
      '</div>',
      next ? [
        '<div style="margin-bottom:12px">',
          '<div style="display:flex;justify-content:space-between;font-size:11px;color:rgba(255,255,255,0.5);margin-bottom:4px">',
            '<span>До уровня ' + next.label + '</span>',
            '<span>' + xpToNext + ' XP</span>',
          '</div>',
          '<div style="height:5px;background:rgba(255,255,255,0.1);border-radius:3px;overflow:hidden">',
            '<div style="height:100%;width:' + pct + '%;background:linear-gradient(90deg,#0088CC,#00bcd4);border-radius:3px;transition:width 0.6s ease"></div>',
          '</div>',
        '</div>',
      ].join('') : '',
      '<div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:12px">',
        statCard('🔥', 'Серия', store.streak + ' д.'),
        statCard('👀', 'Просмотров', store.totalViews),
        statCard('❤️', 'Избранных', store.totalFavs),
        statCard('🏅', 'Ачивки', unlockedCount + '/' + totalCount),
      '</div>',
      store.cashbackEarned > 0 ? [
        '<div style="background:rgba(0,136,204,0.15);border:1px solid rgba(0,136,204,0.3);border-radius:12px;padding:10px;text-align:center">',
          '<div style="font-size:10px;color:rgba(255,255,255,0.5);text-transform:uppercase;letter-spacing:0.05em">Кэшбек</div>',
          '<div style="font-size:18px;font-weight:800;color:#4ade80">+' + store.cashbackEarned.toLocaleString('ru') + ' ₽</div>',
        '</div>',
      ].join('') : '',
    ].join('');

    document.body.appendChild(panel);

    /* Close on outside tap */
    setTimeout(function () {
      document.addEventListener('click', function close(e) {
        if (!panel.contains(e.target) && e.target !== hudEl) {
          if (panel.parentNode) panel.parentNode.removeChild(panel);
          document.removeEventListener('click', close);
        }
      });
    }, 100);
  }

  function statCard(icon, label, val) {
    return [
      '<div style="background:rgba(255,255,255,0.06);border-radius:10px;padding:8px;text-align:center">',
        '<div style="font-size:18px">' + icon + '</div>',
        '<div style="font-size:10px;color:rgba(255,255,255,0.5);margin-top:1px">' + label + '</div>',
        '<div style="font-size:14px;font-weight:700">' + val + '</div>',
      '</div>',
    ].join('');
  }

  /* ── Android: Material Ripple XP ─────────────────────────── */
  function androidRippleXP() {
    if (!isAndroid || !hudEl) return;
    var ring = document.createElement('div');
    ring.style.cssText = [
      'position:fixed',
      'right:16px',
      'bottom:' + hudBottom(),
      'width:52px',
      'height:52px',
      'border-radius:50%',
      'background:rgba(0,136,204,0.4)',
      'pointer-events:none',
      'z-index:8998',
      'animation:android-ripple 0.8s ease-out forwards',
    ].join(';');
    document.body.appendChild(ring);
    setTimeout(function () { if (ring.parentNode) ring.parentNode.removeChild(ring); }, 850);
  }

  /* ── Android: Rich Haptics ───────────────────────────────── */
  window.pwaAndroidHaptic = function (type) {
    if (!isAndroid || !hasVibration) return;
    var patterns = {
      success:     [30, 20, 60],
      reward:      [20, 15, 20, 15, 80],
      achievement: [50, 30, 50, 30, 100],
      levelup:     [30, 20, 30, 20, 30, 60, 100],
      cashback:    [15, 10, 15, 10, 60, 10, 100],
    };
    navigator.vibrate(patterns[type] || [30]);
  };

  /* ── Page-level XP events ─────────────────────────────────── */
  /* Skip all page XP on staff back-office pages */

  /* Property detail page view — XP only once per unique URL per day */
  if (!isStaffPage && window.location.pathname.match(/\/property\/\d+|\/object\//)) {
    var isNewPropView = canGainPageXP();
    if (isNewPropView) {
      store.totalViews += 1;
      saveStore(store);
    }
    setTimeout(function () {
      if (isNewPropView) {
        gainXP(5, 'Просмотр квартиры');
        checkAchievements();
      }
    }, 1200);
  }

  /* Complex detail page — XP only once per unique URL per day */
  if (!isStaffPage && window.location.pathname.match(/\/complex\/\d+|\/residential[_-]complex\//)) {
    var isNewComplexView = canGainPageXP();
    setTimeout(function () {
      if (isNewComplexView) {
        gainXP(3, 'Просмотр ЖК');
        checkAchievements();
      }
    }, 1500);
  }

  /* Main page — greet returning user */
  if (window.location.pathname === '/' || window.location.pathname.match(/^\/(sochi|krasnodar|anapa|gelendzhik|novorossiysk|tuapse)\/?$/)) {
    setTimeout(function () {
      if (hasDynamicIsland && store.xp > 0) {
        var lvl = getLevel(store.xp);
        diFlash(lvl.icon + ' ' + store.xp + ' XP', '#0f172a');
      }
    }, 3000);
  }

  /* Favorite add — triggered exclusively by the custom event that
     favorites.js dispatches only when action === 'added'.
     A 3-second lock prevents any double-fire (e.g. badge API round-trip
     completing after the debounce has already resolved). */
  var favXPLockUntil = 0;

  function onFavAdded() {
    if (isStaffPage) return;
    var now = Date.now();
    if (now < favXPLockUntil) return;   /* already awarded in this gesture */
    favXPLockUntil = now + 3000;        /* lock for 3 s */
    store.totalFavs = (store.totalFavs || 0) + 1;
    saveStore(store);
    gainXP(10, 'В избранное');
    checkAchievements();
    if (hasDynamicIsland) diFlash('❤️ Добавлено', '#e11d48');
    if (isAndroid) pwaAndroidHaptic('success');
  }

  /* Single listener — no MutationObserver fallback (causes double XP) */
  document.addEventListener('inback:fav:added', onFavAdded);

  /* Deal submit / form submit reward — consumer pages only */
  document.addEventListener('submit', function (e) {
    if (isStaffPage) return;
    var form = e.target;
    if (form.matches('#deal-form, .viewing-request-form, [data-reward-form]')) {
      setTimeout(function () {
        gainXP(50, 'Заявка отправлена');
        checkAchievements();
        if (hasDynamicIsland) diFlash('📋 Заявка принята!', '#059669');
        if (isAndroid) pwaAndroidHaptic('achievement');
        spawnMoneyRain(6);
      }, 500);
    }
  });

  /* Search submit reward — consumer pages only */
  document.addEventListener('submit', function (e) {
    if (isStaffPage) return;
    var form = e.target;
    if (form.matches('#main-search-form, #hero-search-form, [data-search-form]')) {
      gainXP(2, 'Поиск');
    }
  });

  /* ── Init HUD ─────────────────────────────────────────────── */
  document.addEventListener('DOMContentLoaded', function () {
    detectSAI();
    /* Update BOTTOM_NAV_H from actual nav if available */
    var nav = document.getElementById('mobileBottomNav');
    if (nav && nav.offsetHeight > 0) BOTTOM_NAV_H = nav.offsetHeight;
    if (!isStaffPage) createGameHUD();
    /* Expose public API */
    window.pwaGame = {
      gainXP: gainXP,
      diShowCashback: diShowCashback,
      diFlash: diFlash,
      spawnMoneyRain: spawnMoneyRain,
      showAchievementToast: showAchievementToast,
      showStatsPanel: showStatsPanel,
      store: store,
      getLevel: getLevel,
    };
  });

  /* ── iOS status bar fix for DI devices ───────────────────── */
  if (hasDynamicIsland && isStandalone) {
    var metaBar = document.querySelector('meta[name="apple-mobile-web-app-status-bar-style"]');
    if (metaBar) metaBar.setAttribute('content', 'black-translucent');
  }

})();
