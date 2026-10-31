/* ==========================================================================
   Vita Ratio · мини-приложение
   Классический (не модульный) скрипт: работает и в Telegram WebView, и в
   обычном браузере через telegram-shim.js. Без сборки и внешних библиотек.

   Все данные — только из REST API по контракту (envelope {ok, data|error}).
   Экранные id берутся из index.html; динамические списки рендерятся строками.
   ========================================================================== */
(function () {
  'use strict';

  /* ======================= константы ======================= */

  var WEEKDAYS_SHORT = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс'];
  var WEEKDAYS_FULL = [
    'Понедельник', 'Вторник', 'Среда', 'Четверг', 'Пятница', 'Суббота', 'Воскресенье'
  ];
  var MONTHS = [
    'января', 'февраля', 'марта', 'апреля', 'мая', 'июня',
    'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря'
  ];
  var ACTIVITY_LABELS = {
    sedentary: 'Сидячий (офис, без спорта)',
    light: 'Лёгкая активность (1–2 тренировки)',
    moderate: 'Средняя (3–4 тренировки)',
    high: 'Высокая (5–6 тренировок)',
    athlete: 'Очень высокая (спорт, физический труд)'
  };
  var KIND_LABELS = { gym: 'Тренировка', study: 'Учёба', other: 'Другое' };
  var DAY_KIND_LABELS = { meal: 'Еда', gym: 'Тренировка', study: 'Учёба', sleep: 'Сон', work: 'Дела', other: 'Другое' };
  var QUALITY_LABELS = ['', 'очень плохо', 'плохо', 'нормально', 'хорошо', 'отлично'];
  var DEFAULT_THEME = { accent: '#B7F75C', bg: '#0E1116', card: '#151A21' };
  /* Пресеты палитры из CONTRACT §11 (локальный фолбэк, если /api/theme ещё нет). */
  var PALETTE_PRESETS = [
    { id: 'lime', title: 'Лайм', accent: '#B7F75C', bg: '#0E1116', card: '#151A21' },
    { id: 'violet', title: 'Фиолетовый', accent: '#C4B5FD', bg: '#0F0B1A', card: '#1A1426' },
    { id: 'cyan', title: 'Бирюзовый', accent: '#67E8F9', bg: '#071318', card: '#102028' },
    { id: 'pink', title: 'Розовый', accent: '#F9A8D4', bg: '#160B12', card: '#221018' },
    { id: 'orange', title: 'Оранжевый', accent: '#FDBA74', bg: '#160F08', card: '#241709' },
    { id: 'mint', title: 'Мята', accent: '#6EE7B7', bg: '#081513', card: '#0F211E' },
    { id: 'blue', title: 'Синий', accent: '#93C5FD', bg: '#0A1018', card: '#131C27' },
    { id: 'graphite', title: 'Графит', accent: '#E5E7EB', bg: '#0D0D0F', card: '#18181B' }
  ];
  /* Популярные продукты с граммовками: пресет сразу заполняет название и граммы. */
  var PRODUCT_PRESETS = [
    { title: 'куриная грудка', grams: 200, label: 'Куриная грудка · 200 г' },
    { title: 'овсянка', grams: 80, label: 'Овсянка · 80 г' },
    { title: 'творог', grams: 150, label: 'Творог · 150 г' },
    { title: 'банан', grams: 120, label: 'Банан · 120 г' },
    { title: 'рис', grams: 200, label: 'Рис · 200 г' },
    { title: 'протеин', grams: 30, label: 'Протеин · 30 г' }
  ];
  var ERROR_TEXT = {
    unauthorized: 'Нет доступа к данным. Открой приложение через Telegram.',
    not_found: 'Запись не найдена — обнови экран.',
    bad_request: 'Проверь введённые данные и попробуй ещё раз.',
    invalid_json: 'Сервер не понял запрос. Попробуй ещё раз.',
    network: 'Нет связи с сервером. Проверь, что он запущен.',
    bad_response: 'Сервер ответил неожиданно. Попробуй ещё раз.',
    subscription_required: 'Нужна подписка Vita Ratio — 250 ₽/мес.',
    ai_subscription_required: 'ИИ-разбор — отдельный аддон +100 ₽/мес.',
    base_required: 'Сначала оформи подписку Vita Ratio.',
    invoice_failed: 'Не удалось создать счёт в Telegram. Попробуй позже.'
  };

  /* ======================= состояние ======================= */

  var state = {
    tg: null,
    initData: '',
    demo: false,
    tab: 'today',
    bootstrap: null,
    bootstrapLoading: false,
    bootstrapReload: false,
    todayDate: todayIso(),
    nextClass: null,
    food: {
      date: todayIso(),
      data: null,
      loading: false,
      manual: false,
      rowSeq: 0,
      items: [],
      notFound: []
    },
    weekly: {
      shown: false,
      busy: false,
      saved: false
    },
    sleep: { quality: 3, data: null, plan: null, meals: null, loading: false },
    schedule: {
      weekStart: '',
      weekEnd: '',
      data: null,
      classes: [],
      weekLoad: 0,
      selected: null,
      loading: false,
      segment: 'day',
      day: null,
      dayDate: todayIso(),
      dayLoading: false,
      daySuggestions: []
    },
    progress: { weights: null, stats: null, loading: false },
    /* Чат ИИ (v8): отдельная загрузка, не блокирует остальные экраны. */
    aiChat: {
      items: [], active: null, loading: false, loaded: false, reload: false,
      sending: false, pending: null, forcePaywall: false
    },
    /* Подписка (CONTRACT §22–25): GET /api/subscription + bootstrap.subscription. */
    subscription: { data: null, loading: false, loaded: false, reload: false, missing: false },
    pay: { baseBusy: false, aiBusy: false, forcePaywall: false },
    theme: {
      accent: DEFAULT_THEME.accent,
      bg: DEFAULT_THEME.bg,
      card: DEFAULT_THEME.card,
      presets: PALETTE_PRESETS.slice(),
      loading: false,
      pending: false,
      synced: false
    },
    onb: { step: 1, busy: false, opened: false, data: {} }
  };

  /* ======================= утилиты ======================= */

  function byId(id) {
    return document.getElementById(id);
  }

  function qsa(selector, root) {
    return Array.prototype.slice.call((root || document).querySelectorAll(selector));
  }

  function esc(value) {
    return String(value == null ? '' : value).replace(/[&<>"']/g, function (ch) {
      if (ch === '&') { return '&amp;'; }
      if (ch === '<') { return '&lt;'; }
      if (ch === '>') { return '&gt;'; }
      if (ch === '"') { return '&quot;'; }
      return '&#39;';
    });
  }

  function num(value, fallback) {
    var parsed = parseFloat(value);
    return isFinite(parsed) ? parsed : (fallback == null ? 0 : fallback);
  }

  function int(value, fallback) {
    var parsed = Math.round(num(value, fallback == null ? 0 : fallback));
    return isFinite(parsed) ? parsed : 0;
  }

  function clamp(value, min, max) {
    return Math.min(max, Math.max(min, value));
  }

  function pad2(value) {
    return (value < 10 ? '0' : '') + value;
  }

  function fmtNumber(value, digits) {
    var places = digits == null ? 0 : digits;
    var factor = Math.pow(10, places);
    var rounded = Math.round(num(value) * factor) / factor;
    var parts = String(rounded).split('.');
    parts[0] = parts[0].replace(/\B(?=(\d{3})+(?!\d))/g, ' ');
    return parts.join(',');
  }

  function fmtInt(value) {
    return fmtNumber(value, 0);
  }

  function fmtHours(hours) {
    return fmtNumber(num(hours), 1);
  }

  function fmtDuration(totalMinutes) {
    var minutes = Math.max(0, Math.round(num(totalMinutes)));
    var hh = Math.floor(minutes / 60);
    var mm = minutes % 60;
    if (hh <= 0) { return mm + ' мин'; }
    if (mm === 0) { return hh + ' ч'; }
    return hh + ' ч ' + mm + ' мин';
  }

  function plural(count, one, few, many) {
    var value = Math.abs(Math.round(num(count)));
    var mod10 = value % 10;
    var mod100 = value % 100;
    if (mod10 === 1 && mod100 !== 11) { return one; }
    if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) { return few; }
    return many;
  }

  function isoDate(dateObj) {
    return dateObj.getFullYear() + '-' + pad2(dateObj.getMonth() + 1) + '-' + pad2(dateObj.getDate());
  }

  function todayIso() {
    return isoDate(new Date());
  }

  function parseIso(value) {
    var match = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(value == null ? '' : value));
    if (!match) { return new Date(); }
    return new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]));
  }

  function addDays(dateObj, days) {
    var copy = new Date(dateObj.getFullYear(), dateObj.getMonth(), dateObj.getDate());
    copy.setDate(copy.getDate() + days);
    return copy;
  }

  function mondayIndex(dateObj) {
    return (dateObj.getDay() + 6) % 7; // 0 = понедельник
  }

  function mondayOf(dateObj) {
    return addDays(dateObj, -mondayIndex(dateObj));
  }

  function nowMinutes() {
    var now = new Date();
    return now.getHours() * 60 + now.getMinutes();
  }

  function nowHm() {
    var now = new Date();
    return pad2(now.getHours()) + ':' + pad2(now.getMinutes());
  }

  function hmToMin(value) {
    var parts = String(value == null ? '' : value).split(':');
    if (parts.length < 2) { return 0; }
    return clamp(int(parts[0]), 0, 23) * 60 + clamp(int(parts[1]), 0, 59);
  }

  function minToHm(minutes) {
    var value = ((Math.round(num(minutes)) % 1440) + 1440) % 1440;
    return pad2(Math.floor(value / 60)) + ':' + pad2(value % 60);
  }

  function durationBetween(bed, wake) {
    var diff = (hmToMin(wake) - hmToMin(bed) + 1440) % 1440;
    if (diff === 0) { diff = 1440; }
    return diff / 60; // часы с точностью до минуты (7.87 = 7 ч 52 мин)
  }

  function sleepHours(entry) {
    if (!entry) { return 0; }
    if (entry.duration_h != null) { return num(entry.duration_h); }
    if (entry.duration != null) { return num(entry.duration); }
    if (entry.bed_time && entry.wake_time) { return durationBetween(entry.bed_time, entry.wake_time); }
    return 0;
  }

  function dateShort(value) {
    var dateObj = parseIso(value);
    return dateObj.getDate() + ' ' + MONTHS[dateObj.getMonth()];
  }

  function dateNumeric(value) {
    var dateObj = parseIso(value);
    return pad2(dateObj.getDate()) + '.' + pad2(dateObj.getMonth() + 1);
  }

  function dayLabel(value) {
    var iso = String(value || '').slice(0, 10);
    var today = todayIso();
    if (iso === today) { return 'Сегодня, ' + dateShort(iso); }
    if (iso === isoDate(addDays(new Date(), -1))) { return 'Вчера, ' + dateShort(iso); }
    if (iso === isoDate(addDays(new Date(), 1))) { return 'Завтра, ' + dateShort(iso); }
    return WEEKDAYS_FULL[mondayIndex(parseIso(iso))] + ', ' + dateShort(iso);
  }

  function fullDateLabel(value) {
    var iso = String(value || '').slice(0, 10);
    return WEEKDAYS_FULL[mondayIndex(parseIso(iso))] + ', ' + dateShort(iso);
  }

  function greeting() {
    var hour = new Date().getHours();
    if (hour >= 5 && hour < 12) { return 'Доброе утро'; }
    if (hour >= 12 && hour < 18) { return 'Добрый день'; }
    if (hour >= 18 && hour < 23) { return 'Добрый вечер'; }
    return 'Доброй ночи';
  }

  function starString(value) {
    var filled = clamp(int(value), 0, 5);
    var result = '';
    for (var i = 1; i <= 5; i += 1) {
      result += i <= filled ? '★' : '☆';
    }
    return result;
  }

  function detectTimezone() {
    try {
      var timezone = Intl.DateTimeFormat().resolvedOptions().timeZone;
      if (timezone) { return timezone; }
    } catch (error) { /* noop */ }
    return 'Europe/Moscow';
  }

  function errorText(code) {
    if (!code) { return 'Что-то пошло не так. Попробуй ещё раз.'; }
    if (ERROR_TEXT[code]) { return ERROR_TEXT[code]; }
    if (String(code).indexOf('http_5') === 0) { return 'Сервер приболел. Попробуй чуть позже.'; }
    if (String(code).indexOf('http_4') === 0) { return 'Запрос отклонён. Обнови экран и попробуй снова.'; }
    return 'Ошибка: ' + code;
  }

  /* ======================= API ======================= */

  function makeError(code) {
    var error = new Error(String(code));
    error.code = String(code);
    return error;
  }

  function apiRequest(method, path, body) {
    var headers = { Accept: 'application/json' };
    if (state.initData) {
      headers['X-Init-Data'] = state.initData;
    } else {
      headers['X-Dev-User'] = '1'; // демо-режим (APP_ENV=dev)
    }
    var options = { method: method, headers: headers, cache: 'no-store' };
    if (body !== undefined) {
      headers['Content-Type'] = 'application/json';
      options.body = JSON.stringify(body);
    }
    return fetch(path, options).then(function (response) {
      return response.text().then(function (text) {
        var payload = null;
        if (text) {
          try {
            payload = JSON.parse(text);
          } catch (error) {
            throw makeError('bad_response');
          }
        }
        if (!response.ok || !payload || payload.ok !== true) {
          throw makeError((payload && payload.error) || ('http_' + response.status));
        }
        return payload.data;
      });
    }, function () {
      throw makeError('network');
    });
  }

  /* ======================= UI-помощники ======================= */

  var toastTimer = null;

  function toast(message, kind) {
    var container = byId('toast-container');
    if (!container) { return; }
    var node = document.createElement('div');
    node.className = 'toast toast--' + (kind === 'error' ? 'error' : 'ok');
    node.setAttribute('role', 'status');
    node.textContent = String(message || '');
    container.appendChild(node);
    window.setTimeout(function () {
      node.classList.add('toast--out');
      window.setTimeout(function () {
        if (node.parentNode) { node.parentNode.removeChild(node); }
      }, 260);
    }, 3400);
    if (toastTimer) { window.clearTimeout(toastTimer); }
    toastTimer = window.setTimeout(function () { toastTimer = null; }, 100);
  }

  /* Сравнение версий Telegram WebApp: старые клиенты не поддерживают часть API
     и пишут предупреждения в консоль — вызываем только то, что умеют. */
  function telegramVersionAtLeast(required) {
    var tg = state.tg;
    if (!tg || typeof tg.version !== 'string') { return false; }
    var actual = tg.version.split('.');
    var need = String(required).split('.');
    var length = Math.max(actual.length, need.length);
    for (var index = 0; index < length; index += 1) {
      var actualPart = parseInt(actual[index], 10) || 0;
      var needPart = parseInt(need[index], 10) || 0;
      if (actualPart > needPart) { return true; }
      if (actualPart < needPart) { return false; }
    }
    return true;
  }

  function haptic(type) {
    var tg = state.tg;
    if (!tg || !tg.HapticFeedback || !telegramVersionAtLeast('6.1')) { return; }
    try {
      if (type === 'success' || type === 'error' || type === 'warning') {
        tg.HapticFeedback.notificationOccurred(type === 'success' ? 'success' : type);
      } else if (type === 'select') {
        tg.HapticFeedback.selectionChanged();
      } else {
        tg.HapticFeedback.impactOccurred(type || 'light');
      }
    } catch (error) { /* noop */ }
  }

  function setBusy(button, busy) {
    if (!button) { return; }
    button.disabled = !!busy;
    button.classList.toggle('is-busy', !!busy);
  }

  function setScreenLoading(name, loading) {
    var skeleton = byId(name + '-skeleton');
    var content = byId(name + '-content');
    if (!skeleton || !content) { return; }
    skeleton.hidden = !loading;
    content.hidden = !!loading;
  }

  function askConfirm(message, onConfirm) {
    var tg = state.tg;
    if (tg && typeof tg.showConfirm === 'function') {
      try {
        tg.showConfirm(message, function (confirmed) {
          if (confirmed) { onConfirm(); }
        });
        return;
      } catch (error) { /* падаем в window.confirm */ }
    }
    if (window.confirm) {
      if (window.confirm(message)) { onConfirm(); }
      return;
    }
    onConfirm();
  }

  /* ======================= тема и палитра ======================= */

  /* Тема: приложение всегда тёмное (требование контракта).
     Палитру пользователя (--accent/--bg/--bg-2/--card + производные) задаёт
     applyPalette() — она важнее themeParams Telegram. Из themeParams берём
     только текстовые цвета и лишь при тёмной схеме, чтобы светлая тема ОС
     не «просвечивала». */
  function applyTheme() {
    var tg = state.tg;
    var root = document.documentElement;
    var params = (tg && tg.themeParams) || {};
    var isTelegram = !!state.initData;
    var scheme = (tg && tg.colorScheme) || 'dark';
    var useTelegramDark = isTelegram && scheme === 'dark';

    root.classList.remove('theme-light');
    root.classList.add('theme-dark');

    var mapping = {
      text_color: '--text',
      hint_color: '--muted'
    };
    Object.keys(mapping).forEach(function (key) {
      if (useTelegramDark && typeof params[key] === 'string' && params[key]) {
        root.style.setProperty(mapping[key], params[key]);
      } else {
        root.style.removeProperty(mapping[key]);
      }
    });

    applyPalette(currentPalette(), { cache: false });
  }

  function currentPalette() {
    return { accent: state.theme.accent, bg: state.theme.bg, card: state.theme.card };
  }

  function readLocalTheme() {
    try {
      var raw = window.localStorage.getItem('vita-theme');
      if (!raw) { return null; }
      var parsed = JSON.parse(raw);
      return parsed && typeof parsed === 'object' ? parsed : null;
    } catch (error) {
      return null; /* приватный режим / нет localStorage */
    }
  }

  function writeLocalTheme(theme) {
    try {
      window.localStorage.setItem('vita-theme', JSON.stringify({
        accent: theme.accent,
        bg: theme.bg,
        card: theme.card
      }));
    } catch (error) { /* кэш не критичен */ }
  }

  function normalizeThemeColor(value, fallback) {
    var hex = /^#([0-9a-f]{6})$/i;
    var text = String(value || '').trim().toUpperCase();
    return hex.test(text) ? text : fallback;
  }

  function normalizePalette(palette) {
    var source = palette || {};
    return {
      accent: normalizeThemeColor(source.accent, DEFAULT_THEME.accent),
      bg: normalizeThemeColor(source.bg, DEFAULT_THEME.bg),
      card: normalizeThemeColor(source.card, DEFAULT_THEME.card)
    };
  }

  function applyPalette(palette, options) {
    var opts = options || {};
    var theme = normalizePalette(palette);
    var helper = window.__vitaTheme;
    if (helper && typeof helper.apply === 'function') {
      helper.apply(theme); /* те же правила, что у inline-скрипта в index.html */
    }
    state.theme.accent = theme.accent;
    state.theme.bg = theme.bg;
    state.theme.card = theme.card;
    if (opts.cache !== false) { writeLocalTheme(theme); }

    var meta = document.querySelector('meta[name="theme-color"]');
    if (meta) { meta.setAttribute('content', theme.bg); }
    var tg = state.tg;
    if (tg && telegramVersionAtLeast('6.1')) {
      try {
        if (typeof tg.setBackgroundColor === 'function') { tg.setBackgroundColor(theme.bg); }
        if (typeof tg.setHeaderColor === 'function') { tg.setHeaderColor(theme.bg); }
      } catch (error) { /* noop */ }
    }

    syncPaletteInputs();
    syncPaletteActive();
    if (opts.save) { scheduleThemeSave(); }
    return theme;
  }

  function findPalettePreset(presetId) {
    var found = null;
    (state.theme.presets || []).forEach(function (preset) {
      if (String(preset.id) === String(presetId)) { found = preset; }
    });
    return found;
  }

  function syncPaletteInputs() {
    var accent = byId('color-accent');
    var bg = byId('color-bg');
    var card = byId('color-card');
    if (accent) { accent.value = state.theme.accent; }
    if (bg) { bg.value = state.theme.bg; }
    if (card) { card.value = state.theme.card; }
  }

  function syncPaletteActive() {
    var activePreset = null;
    (state.theme.presets || []).forEach(function (preset) {
      var same = normalizeThemeColor(preset.accent, '') === state.theme.accent &&
        normalizeThemeColor(preset.bg, '') === state.theme.bg &&
        normalizeThemeColor(preset.card, '') === state.theme.card;
      if (same) { activePreset = preset; }
    });
    qsa('[data-preset-id]').forEach(function (button) {
      var active = !!activePreset && String(activePreset.id) === String(button.getAttribute('data-preset-id'));
      button.classList.toggle('is-active', active);
      button.setAttribute('aria-pressed', active ? 'true' : 'false');
    });
    var label = byId('theme-status');
    if (label) {
      label.textContent = 'палитра · ' + (activePreset ? activePreset.title.toLowerCase() : 'своя');
    }
  }

  function renderPalette() {
    var box = byId('palette-presets');
    if (!box) { return; }
    box.innerHTML = (state.theme.presets || []).map(function (preset) {
      return '<button type="button" class="palette-swatch" data-preset-id="' + esc(preset.id) + '" ' +
        'aria-label="Палитра ' + esc(preset.title) + '" aria-pressed="false">' +
        '<span class="palette-swatch__dot" style="background:' + esc(preset.accent) +
          ';box-shadow:inset 0 0 0 3px ' + esc(preset.bg) + '"></span>' +
        '<span>' + esc(preset.title) + '</span>' +
      '</button>';
    }).join('');
    syncPaletteInputs();
    syncPaletteActive();
  }

  var themeSaveTimer = null;

  function scheduleThemeSave() {
    if (themeSaveTimer) { window.clearTimeout(themeSaveTimer); }
    themeSaveTimer = window.setTimeout(function () {
      themeSaveTimer = null;
      saveTheme();
    }, 450);
  }

  function saveTheme() {
    var palette = currentPalette();
    apiRequest('PUT', '/api/theme', palette).then(function (data) {
      state.theme.pending = false;
      if (data && data.accent) {
        var saved = normalizePalette(data);
        state.theme.accent = saved.accent;
        state.theme.bg = saved.bg;
        state.theme.card = saved.card;
        writeLocalTheme(saved);
        syncPaletteInputs();
        syncPaletteActive();
      }
    }).catch(function (error) {
      state.theme.pending = true;
      /* API v2 может быть ещё не готов: палитра уже применена и закэширована */
      if (error && error.code && error.code !== 'network' && error.code !== 'http_404') {
        toast(errorText(error.code), 'error');
      }
    });
  }

  function loadTheme() {
    if (state.theme.loading) { return; }
    state.theme.loading = true;
    apiRequest('GET', '/api/theme').then(function (data) {
      state.theme.loading = false;
      if (data && Array.isArray(data.presets) && data.presets.length) {
        state.theme.presets = data.presets.map(function (preset) {
          var normalized = normalizePalette(preset);
          return {
            id: String(preset.id || normalized.accent),
            title: String(preset.title || normalized.accent),
            accent: normalized.accent,
            bg: normalized.bg,
            card: normalized.card
          };
        });
        renderPalette();
      }
      if (data && data.accent && !state.theme.pending && !state.theme.synced) {
        applyPalette(data, { cache: true });
        state.theme.synced = true;
      }
    }).catch(function () {
      state.theme.loading = false; /* остаёмся на локальных пресетах */
    });
  }

  function applyThemeFromInputs() {
    haptic('select');
    applyPalette({
      accent: byId('color-accent').value,
      bg: byId('color-bg').value,
      card: byId('color-card').value
    }, { save: true, cache: true });
  }

  function resetTheme() {
    haptic('select');
    applyPalette(DEFAULT_THEME, { save: true, cache: true });
    toast('Палитра сброшена к lime');
  }

  function updateBackButton(visible) {
    var tg = state.tg;
    if (!tg || !tg.BackButton || !state.initData || !telegramVersionAtLeast('6.1')) { return; }
    try {
      if (visible) {
        tg.BackButton.show();
        if (!state.backBound) {
          state.backBound = true;
          tg.BackButton.onClick(function () {
            if (!byId('onboarding').hidden && state.onb.step > 1) {
              goOnbStep(-1);
            }
          });
        }
      } else {
        tg.BackButton.hide();
      }
    } catch (error) { /* noop */ }
  }

  function switchTab(tab, options) {
    var opts = options || {};
    if (!document.querySelector('.screen[data-screen="' + tab + '"]')) { return; }
    state.tab = tab;
    qsa('.screen').forEach(function (section) {
      var active = section.getAttribute('data-screen') === tab;
      section.classList.toggle('is-active', active);
      if (active) {
        section.removeAttribute('aria-hidden');
      } else {
        section.setAttribute('aria-hidden', 'true');
      }
    });
    qsa('.tab').forEach(function (button) {
      var active = button.getAttribute('data-screen') === tab;
      button.classList.toggle('is-active', active);
      if (active) {
        button.setAttribute('aria-current', 'page');
      } else {
        button.removeAttribute('aria-current');
      }
    });
    if (window.scrollTo) {
      window.scrollTo(0, 0);
    }
    if (tab === 'today') { loadBootstrap(); }
    if (tab === 'food' && !opts.noLoad) { loadFood(); }
    if (tab === 'sleep' && !opts.noLoad) { loadSleep(); }
    if (tab === 'schedule' && !opts.noLoad) {
      setScheduleSegment(state.schedule.segment || 'day');
    }
    if (tab === 'progress' && !opts.noLoad) {
      loadProgress();
    }
    if (tab === 'ai' && !opts.noLoad) {
      /* Экран ИИ: история чата и актуальный статус подписки/аддона. */
      renderAiScreen();
      loadAiHistory();
      loadSubscription();
    }
  }

  /* ======================= bootstrap и профиль ======================= */

  function loadBootstrap(options) {
    var opts = options || {};
    if (state.bootstrapLoading) {
      /* Форс-перезагрузка (после сохранения цели/чек-ина): если запрос уже
         летит, повторим его по завершении, иначе карточка останется старой. */
      if (opts.force) { state.bootstrapReload = true; }
      return;
    }
    var firstLoad = !state.bootstrap;
    if (firstLoad) {
      setScreenLoading('today', true);
      byId('today-content').classList.remove('is-error');
    }
    state.bootstrapLoading = true;
    apiRequest('GET', '/api/bootstrap').then(function (data) {
      state.bootstrapLoading = false;
      state.bootstrap = data || {};
      state.todayDate = (data && data.today && data.today.date) || todayIso();
      if (data && data.profile) {
        hideOnboarding();
      } else {
        showOnboarding();
      }
      /* Палитра из профиля — источник правды при первой загрузке.
         Дальше bootstrap не перебивает только что выбранную пользователем тему. */
      if (!state.theme.synced && data && data.theme && data.theme.accent) {
        applyPalette(data.theme, { cache: true });
        state.theme.synced = true;
      }
      setScreenLoading('today', false);
      byId('today-content').classList.remove('is-error');
      renderToday();
      refreshAuxScreens();
      handleWeeklyDue(state.bootstrap);
      /* Подписка приходит с bootstrap и/или отдельным GET /api/subscription.
         Bootstrap-срез применяем сразу, затем обновляем отдельным запросом. */
      var bootSubscription = normalizeSubscription(data && data.subscription);
      if (bootSubscription) { state.subscription.data = bootSubscription; }
      renderSubscription();
      loadSubscription();
      if (state.bootstrapReload) {
        state.bootstrapReload = false;
        loadBootstrap();
      }
    }).catch(function (error) {
      state.bootstrapLoading = false;
      setScreenLoading('today', false);
      byId('today-content').classList.add('is-error');
      byId('today-error').hidden = false;
      toast(errorText(error.code), 'error');
      /* Даже если bootstrap не загрузился (402/сеть), проверяем подписку:
         иначе paywall не покажется, а экраны останутся пустыми. */
      loadSubscription();
      if (state.bootstrapReload) {
        state.bootstrapReload = false;
        loadBootstrap();
      }
    });
  }

  function refreshAuxScreens() {
    if (!state.bootstrap) { return; }
    if (state.tab === 'food' && state.food.data) { renderFood(); }
    if (state.tab === 'sleep') {
      if (state.sleep.data) { renderSleep(); }
      renderSleepSync();
    }
    if (state.tab === 'progress') {
      renderProfileForm();
      renderPalette();
      if (state.progress.stats) { renderStats(); }
    }
    if (state.tab === 'ai') { renderAiScreen(); }
    if (state.tab === 'schedule' && state.schedule.day) { renderDayPlan(); }
  }

  function currentTargets() {
    return (state.bootstrap && state.bootstrap.targets) || null;
  }

  function currentProfile() {
    return (state.bootstrap && state.bootstrap.profile) || null;
  }

  /* ======================= подписка и paywall (v5) ======================= */

  /* Значения по умолчанию — из CONTRACT §22/§23. Если API ещё не готов
     (404) или поле не пришло, работает фолбэк: остальные экраны не ломаются. */
  var SUBSCRIPTION_DEFAULTS = {
    active: false,
    until: null,
    ai_active: false,
    ai_until: null,
    ai_enabled: false,
    base_price_rub: 250,
    base_price_stars: 150,
    ai_price_rub: 100,
    ai_price_stars: 60,
    period_days: 30,
    trial_days: 7,
    enforced: false
  };

  function normalizeSubscription(raw) {
    if (!raw || typeof raw !== 'object') { return null; }
    var out = {};
    Object.keys(SUBSCRIPTION_DEFAULTS).forEach(function (key) {
      out[key] = raw[key] == null ? SUBSCRIPTION_DEFAULTS[key] : raw[key];
    });
    out.active = flagOn(raw.active);
    out.ai_active = flagOn(raw.ai_active);
    out.ai_enabled = flagOn(raw.ai_enabled);
    out.enforced = flagOn(raw.enforced);
    out.base_price_rub = Math.max(1, int(raw.base_price_rub, 250));
    out.base_price_stars = Math.max(1, int(raw.base_price_stars, 150));
    out.ai_price_rub = Math.max(1, int(raw.ai_price_rub, 100));
    out.ai_price_stars = Math.max(1, int(raw.ai_price_stars, 60));
    out.period_days = Math.max(1, int(raw.period_days, 30));
    out.trial_days = Math.max(0, int(raw.trial_days, 7));
    /* Триал может прийти флагом/датой — используем для подписи статуса. */
    out.trial = flagOn(raw.trial) || flagOn(raw.is_trial) || !!raw.trial_until;
    return out;
  }

  /* Источник правды: GET /api/subscription, иначе срез из bootstrap. */
  function subscriptionPayload() {
    if (state.subscription.data) { return state.subscription.data; }
    var boot = state.bootstrap || {};
    var raw = boot.subscription;
    /* На случай, если bootstrap отдаёт короткий объект sub (CONTRACT §23). */
    if (!raw && boot.sub && typeof boot.sub === 'object') { raw = boot.sub; }
    return normalizeSubscription(raw);
  }

  function subscriptionIsTrial(sub) {
    if (!sub) { return false; }
    if (sub.trial === true || sub.trial_until) { return true; }
    var profile = currentProfile();
    return !!(profile && (flagOn(profile.sub_trial) || flagOn(profile.trial)));
  }

  function subscriptionStatusText(sub) {
    if (!sub) { return ''; }
    var until = sub.trial_until || sub.until;
    if (sub.active) {
      if (!until) { return subscriptionIsTrial(sub) ? 'Пробный период активен' : 'Подписка активна'; }
      return (subscriptionIsTrial(sub) ? 'Пробный период до ' : 'Подписка активна до ') + dateShort(until);
    }
    return 'Подписка не активна';
  }

  function subscriptionPaywallVisible() {
    if (state.pay.forcePaywall) { return true; }
    var sub = subscriptionPayload();
    /* Блокируем доступ только когда подписка не активна и режим включён. */
    return !!(sub && sub.active !== true && sub.enforced === true);
  }

  function setPaywallVisible(visible) {
    var node = byId('sub-paywall');
    if (!node) { return; }
    node.hidden = !visible;
    document.body.classList.toggle('paywall-open', !!visible);
  }

  function renderPaywall(sub) {
    var rub = sub ? sub.base_price_rub : SUBSCRIPTION_DEFAULTS.base_price_rub;
    var stars = sub ? sub.base_price_stars : SUBSCRIPTION_DEFAULTS.base_price_stars;
    var trialDays = sub ? sub.trial_days : SUBSCRIPTION_DEFAULTS.trial_days;
    var title = byId('sub-paywall-title');
    var rubNode = byId('sub-price-rub');
    var starsNode = byId('sub-price-stars');
    var trialNode = byId('sub-trial');
    var button = byId('sub-pay-btn');
    if (title) { title.textContent = 'Vita Ratio — ' + fmtInt(rub) + ' ₽/мес'; }
    if (rubNode) { rubNode.textContent = fmtInt(rub); }
    if (starsNode) { starsNode.textContent = fmtInt(stars); }
    if (button) { button.textContent = 'Оплатить ' + fmtInt(rub) + ' ₽'; }
    if (trialNode) {
      if (trialDays > 0) {
        trialNode.textContent = 'Пробный период: ' + trialDays + ' ' +
          plural(trialDays, 'день', 'дня', 'дней');
        trialNode.hidden = false;
      } else {
        trialNode.textContent = '';
        trialNode.hidden = true;
      }
    }
    setPaywallVisible(subscriptionPaywallVisible());
  }

  function renderSubscriptionStatus(sub) {
    var node = byId('subscription-status');
    if (!node) { return; }
    if (!sub) {
      node.textContent = '';
      node.hidden = true;
      node.classList.remove('subscription-status--trial');
      return;
    }
    node.textContent = subscriptionStatusText(sub);
    node.hidden = false;
    node.classList.toggle('subscription-status--trial', sub.active && subscriptionIsTrial(sub));
  }

  function renderSubscription() {
    var sub = subscriptionPayload();
    if (sub && sub.active === true) { state.pay.forcePaywall = false; }
    if (!sub && state.pay.forcePaywall) {
      sub = normalizeSubscription({}); // значения по умолчанию для paywall
    }
    renderPaywall(sub);
    renderSubscriptionStatus(sub);
    /* Экран ИИ сам решает, показать поле ввода или плашку +100 ₽/мес. */
    renderAiScreen();
  }

  function loadSubscription(options) {
    var opts = options || {};
    if (state.subscription.loading) {
      if (opts.force) { state.subscription.reload = true; }
      return;
    }
    state.subscription.loading = true;
    apiRequest('GET', '/api/subscription').then(function (data) {
      state.subscription.loading = false;
      state.subscription.loaded = true;
      state.subscription.missing = false;
      var normalized = normalizeSubscription(data);
      state.subscription.data = normalized;
      /* Оплатили/получили аддон — снимаем принудительный paywall экрана ИИ. */
      if (normalized && normalized.ai_active === true) {
        state.aiChat.forcePaywall = false;
        state.aiChat.active = true;
      }
      renderSubscription();
      if (state.subscription.reload) {
        state.subscription.reload = false;
        loadSubscription();
      }
    }).catch(function (error) {
      state.subscription.loading = false;
      var code = error && error.code;
      /* 404 — API подписки ещё не готов: молча живём на bootstrap-фолбэке. */
      if (code === 'not_found' || code === 'http_404') {
        state.subscription.missing = true;
      }
      renderSubscription();
      if (state.subscription.reload) {
        state.subscription.reload = false;
        loadSubscription();
      }
    });
  }

  function invoiceErrorText(code) {
    if (code === 'not_found' || code === 'http_404') {
      return 'Оплата пока недоступна — попробуй позже.';
    }
    if (code === 'invoice_failed') {
      return 'Не удалось создать счёт в Telegram. Попробуй ещё раз.';
    }
    if (code === 'base_required') {
      return 'Сначала оформи подписку Vita Ratio.';
    }
    if (code === 'subscription_required' || code === 'http_402') {
      return 'Нужна активная подписка Vita Ratio.';
    }
    if (code === 'ai_subscription_required') {
      return 'ИИ-разбор — отдельный аддон +100 ₽/мес.';
    }
    return errorText(code);
  }

  function requestInvoice(kind) {
    return apiRequest('POST', '/api/pay/invoice', { kind: kind }).then(function (data) {
      var url = data && data.invoice_url;
      if (!url) { throw makeError('invoice_failed'); }
      return data;
    });
  }

  /* openInvoice есть только в Telegram (SDK >= 6.1); в браузере — false. */
  function openInvoice(url, onStatus) {
    var tg = state.tg || (window.Telegram && window.Telegram.WebApp);
    if (tg && typeof tg.openInvoice === 'function') {
      try {
        tg.openInvoice(url, function (status) { onStatus(status || 'unknown'); });
        return true;
      } catch (error) { /* ниже покажем подсказку со ссылкой */ }
    }
    return false;
  }

  /* Рублёвый эквайринг (ЮKassa/Robokassa): ссылка открывается в браузере,
     оплату подтверждает вебхук провайдера (см. ?paid= при возврате). */
  function openExternalInvoice(url) {
    var tg = state.tg || (window.Telegram && window.Telegram.WebApp);
    if (tg && typeof tg.openLink === 'function') {
      try { tg.openLink(url); return true; } catch (error) { /* fallback ниже */ }
    }
    try {
      window.location.href = url;
      return true;
    } catch (error) {
      return false;
    }
  }

  /* Возврат со страницы оплаты (?paid=base|ai): досрочно проверяем счёт
     (у ЮKassa вебхук может запаздывать) и перечитываем bootstrap. */
  function refreshPaidInvoice(kind) {
    apiRequest('POST', '/api/pay/refresh', { kind: kind }).catch(function () {
      /* ошибку не показываем — статус всё равно перечитаем ниже */
    }).then(function () {
      afterPaymentRefresh();
    });
  }

  function showInvoiceHint(kind, url) {
    var node = kind === 'ai' ? byId('ai-paywall-note') : byId('sub-pay-note');
    if (!node) { return; }
    var prefix = kind === 'ai' ? 'Подключить ИИ можно в Telegram:' : 'Оплатить можно в Telegram:';
    node.innerHTML = esc(prefix) + ' <a href="' + esc(url) +
      '" target="_blank" rel="noopener noreferrer">открыть счёт</a>';
    node.hidden = false;
  }

  function hideInvoiceHint(kind) {
    var node = kind === 'ai' ? byId('ai-paywall-note') : byId('sub-pay-note');
    if (node) {
      node.textContent = '';
      node.hidden = true;
    }
  }

  function afterPaymentRefresh() {
    loadBootstrap({ force: true });
    loadSubscription({ force: true });
  }

  function handleInvoiceStatus(kind, status) {
    if (status === 'paid') {
      haptic('success');
      if (kind === 'ai') {
        /* Оплатили аддон — сразу открываем чат, дальше подписка/история уточнят статус. */
        state.aiChat.forcePaywall = false;
        state.aiChat.active = true;
        renderAiScreen();
        toast('ИИ-ассистент подключён');
        afterPaymentRefresh();
        loadAiHistory();
        return;
      }
      /* Базовая подписка: скрываем paywall и перечитываем bootstrap. */
      toast('Подписка оплачена — обновляю данные');
      state.pay.forcePaywall = false;
      setPaywallVisible(false);
      afterPaymentRefresh();
      return;
    }
    if (status === 'cancelled') {
      haptic('select');
      toast('Оплата отменена');
      return;
    }
    if (status === 'failed') {
      haptic('error');
      toast('Оплата не прошла — попробуй ещё раз.', 'error');
      return;
    }
    if (status === 'pending') {
      toast('Платёж обрабатывается — загляни чуть позже');
    }
  }

  function payBase() {
    if (state.pay.baseBusy) { return; }
    var button = byId('sub-pay-btn');
    var sub = subscriptionPayload();
    var rub = sub ? sub.base_price_rub : SUBSCRIPTION_DEFAULTS.base_price_rub;
    state.pay.baseBusy = true;
    setBusy(button, true);
    hideInvoiceHint('base');
    haptic('select');
    requestInvoice('base').then(function (data) {
      state.pay.baseBusy = false;
      setBusy(button, false);
      if (data.provider && data.provider !== 'stars') {
        /* Карта/СБП: ссылка ЮKassa/Robokassa открывается в браузере. */
        openExternalInvoice(data.invoice_url);
        toast('Открой оплату и вернись в приложение');
        return;
      }
      var opened = openInvoice(data.invoice_url, function (status) {
        handleInvoiceStatus('base', status);
      });
      if (!opened) {
        showInvoiceHint('base', data.invoice_url);
        toast('Готово: оплати ' + fmtInt(rub) + ' ₽ в Telegram');
      }
    }).catch(function (error) {
      state.pay.baseBusy = false;
      setBusy(button, false);
      haptic('error');
      var code = error && error.code;
      if (code === 'subscription_required' || code === 'http_402') { loadSubscription(); }
      toast(invoiceErrorText(code), 'error');
    });
  }

  function payAi() {
    if (state.pay.aiBusy) { return; }
    var button = byId('ai-subscribe-btn');
    state.pay.aiBusy = true;
    setBusy(button, true);
    hideInvoiceHint('ai');
    haptic('select');
    requestInvoice('ai').then(function (data) {
      state.pay.aiBusy = false;
      setBusy(button, false);
      if (data.provider && data.provider !== 'stars') {
        /* Карта/СБП: ссылка ЮKassa/Robokassa открывается в браузере. */
        openExternalInvoice(data.invoice_url);
        toast('Открой оплату и вернись в приложение');
        return;
      }
      var opened = openInvoice(data.invoice_url, function (status) {
        handleInvoiceStatus('ai', status);
      });
      if (!opened) {
        showInvoiceHint('ai', data.invoice_url);
        toast('Готово: подключи ИИ в Telegram');
      }
    }).catch(function (error) {
      state.pay.aiBusy = false;
      setBusy(button, false);
      haptic('error');
      var code = error && error.code;
      if (code === 'base_required') {
        /* Аддон без base: показываем paywall базовой подписки. */
        state.pay.forcePaywall = true;
        renderSubscription();
        toast('Сначала оформи подписку Vita Ratio — 250 ₽/мес.', 'error');
        return;
      }
      if (code === 'subscription_required' || code === 'http_402') { loadSubscription(); }
      toast(invoiceErrorText(code), 'error');
    });
  }

  /* ======================= экран «Сегодня» ======================= */

  function renderToday() {
    var bootstrap = state.bootstrap;
    if (!bootstrap || !bootstrap.profile) { return; }
    var targets = bootstrap.targets || {};
    var today = bootstrap.today || {};
    var user = bootstrap.user || {};

    byId('today-greeting').textContent = greeting();
    var name = user.first_name || user.username || 'друг';
    byId('today-user').textContent = 'Привет, ' + name + '!';
    byId('today-date').textContent = fullDateLabel(state.todayDate);

    var goal = num(targets.kcal) || num(today.goal_kcal);
    var eaten = num(today.kcal);
    renderCalories(eaten, goal);

    renderMacro(byId('macro-protein-val'), byId('macro-protein-bar'), num(today.protein), num(targets.protein), 'г');
    renderMacro(byId('macro-fat-val'), byId('macro-fat-bar'), num(today.fat), num(targets.fat), 'г');
    renderMacro(byId('macro-carbs-val'), byId('macro-carbs-bar'), num(today.carbs), num(targets.carbs), 'г');
    renderWater(num(targets.water_ml));

    renderTodaySleep(bootstrap.sleep);
    var nextClass = (bootstrap.next_classes && bootstrap.next_classes.length) ? bootstrap.next_classes[0] : null;
    renderTodayClass(nextClass);
    renderNextMeal(bootstrap.plan || []);
    renderInsights(bootstrap.insights || []);
    renderTodayGoal(bootstrap.goal);
    renderTodayDay(bootstrap.day);
  }

  function renderCalories(eaten, goal) {
    var ratio = goal > 0 ? clamp(eaten / goal, 0, 1) : 0;
    var radius = 58;
    var circumference = 2 * Math.PI * radius;
    var circle = byId('cal-ring-value');
    if (circle) {
      circle.setAttribute('stroke-dasharray', circumference.toFixed(1) + ' ' + circumference.toFixed(1));
      circle.setAttribute('stroke-dashoffset', (circumference * (1 - ratio)).toFixed(1));
    }
    byId('cal-eaten').textContent = fmtInt(eaten);
    byId('cal-goal').textContent = fmtInt(goal);
    var left = Math.round(goal - eaten);
    if (goal <= 0) {
      byId('cal-left').textContent = 'цель не задана';
    } else if (left >= 0) {
      byId('cal-left').textContent = 'осталось ' + fmtInt(left) + ' ккал';
    } else {
      byId('cal-left').textContent = 'перебор ' + fmtInt(-left) + ' ккал';
    }
  }

  function renderMacro(valueNode, barNode, value, target, unit) {
    if (valueNode) {
      valueNode.textContent = target > 0
        ? fmtNumber(value, 0) + ' / ' + fmtNumber(target, 0) + ' ' + unit
        : fmtNumber(value, 0) + ' ' + unit;
    }
    if (barNode) {
      var percent = target > 0 ? clamp((value / target) * 100, 0, 100) : 0;
      barNode.style.width = percent.toFixed(1) + '%';
      barNode.classList.toggle('is-over', target > 0 && value > target);
    }
  }

  function renderWater(target) {
    var valueNode = byId('macro-water-val');
    var barNode = byId('macro-water-bar');
    if (!valueNode || !barNode) { return; }
    if (target > 0) {
      valueNode.textContent = 'норма ' + fmtInt(target) + ' мл';
      barNode.style.width = '100%';
    } else {
      valueNode.textContent = '—';
      barNode.style.width = '0%';
    }
  }

  function renderTodaySleep(sleep) {
    var dataBox = byId('today-sleep-data');
    var emptyBox = byId('today-sleep-empty');
    if (!sleep) {
      dataBox.hidden = true;
      emptyBox.hidden = false;
      return;
    }
    dataBox.hidden = false;
    emptyBox.hidden = true;
    var hours = sleepHours(sleep);
    byId('today-sleep-hours').textContent = fmtHours(hours) + ' ч';
    byId('today-sleep-times').textContent = (sleep.bed_time || '—') + ' – ' + (sleep.wake_time || '—');
    var quality = int(sleep.quality);
    byId('today-sleep-quality').textContent = 'Качество ' + quality + '/5 ' + starString(quality);
  }

  function classWhenText(item) {
    var iso = String(item.date || '').slice(0, 10);
    var time = String(item.start_time || '').slice(0, 5);
    var today = todayIso();
    if (iso === today) { return 'Сегодня в ' + time; }
    if (iso === isoDate(addDays(new Date(), 1))) { return 'Завтра в ' + time; }
    return dateShort(iso) + ', ' + time;
  }

  function minutesUntil(item) {
    if (!item || !item.date || !item.start_time) { return null; }
    var start = parseIso(item.date);
    var startMinutes = hmToMin(item.start_time);
    start.setHours(Math.floor(startMinutes / 60), startMinutes % 60, 0, 0);
    return Math.round((start.getTime() - Date.now()) / 60000);
  }

  function updateClassCountdown() {
    var item = state.nextClass;
    var node = byId('today-class-count');
    if (!node) { return; }
    if (!item) { node.textContent = '—'; return; }
    var minutes = minutesUntil(item);
    if (minutes == null) { node.textContent = '—'; return; }
    var duration = num(item.duration_min, 60);
    if (minutes >= 0) {
      node.textContent = 'До старта ' + fmtDuration(minutes);
    } else if (minutes > -duration) {
      node.textContent = 'Уже идёт';
    } else {
      node.textContent = 'Старт прошёл';
    }
  }

  function renderTodayClass(item) {
    var dataBox = byId('today-class-data');
    var emptyBox = byId('today-class-empty');
    state.nextClass = item || null;
    if (!item) {
      dataBox.hidden = true;
      emptyBox.hidden = false;
      return;
    }
    dataBox.hidden = false;
    emptyBox.hidden = true;
    byId('today-class-title').textContent = item.title || 'Занятие';
    var meta = [classWhenText(item)];
    if (item.place) { meta.push(item.place); }
    meta.push(int(item.duration_min, 60) + ' мин');
    byId('today-class-meta').textContent = meta.join(' · ');
    updateClassCountdown();
  }

  function renderNextMeal(plan) {
    var body = byId('next-meal-body');
    var empty = byId('next-meal-empty');
    if (!plan.length) {
      body.hidden = true;
      empty.hidden = false;
      empty.innerHTML = '<p class="muted">Плана на день пока нет — добавь приёмы в разделе «Еда».</p>';
      return;
    }
    var current = nowMinutes();
    var next = null;
    plan.forEach(function (slot) {
      if (!next && hmToMin(slot.time) >= current) { next = slot; }
    });
    if (!next) {
      body.hidden = true;
      empty.hidden = false;
      empty.innerHTML = '<p class="muted">Все приёмы по плану на сегодня прошли. Осталось выспаться 😴</p>';
      return;
    }
    body.hidden = false;
    empty.hidden = true;
    byId('next-meal-title').textContent = next.title || 'Приём пищи';
    byId('next-meal-meta').textContent = next.time || '';
    byId('next-meal-kcal').textContent = next.kcal
      ? '≈ ' + fmtInt(next.kcal) + ' ккал'
      : 'Калории по плану не рассчитаны';
  }

  function renderInsights(insights) {
    var list = byId('today-insights');
    if (!insights.length) {
      list.innerHTML = '<li>Пока нет подсказок — заполни день, и советы появятся.</li>';
      return;
    }
    list.innerHTML = insights.map(function (tip) {
      return '<li>' + esc(tip) + '</li>';
    }).join('');
  }

  /* ======================= цель и план дня (общие рендеры) ======================= */

  /* ---------- цель: статус, тон шкалы и inline-редактор ---------- */

  var GOAL_TONES = { good: true, warn: true, bad: true, muted: true };

  function goalTone(goal) {
    if (!goal || !goal.enabled) { return 'muted'; }
    var status = goal.status;
    if (status && GOAL_TONES[status.tone]) { return status.tone; }
    return 'muted';
  }

  function goalEditorOpen() {
    var editor = byId('today-goal-editor');
    return !!(editor && !editor.hidden);
  }

  function goalEditorVisible(visible, goal) {
    var editor = byId('today-goal-editor');
    var body = byId('today-goal-body');
    var empty = byId('today-goal-empty');
    if (!editor || !body || !empty) { return; }
    var enabled = !!(goal && goal.enabled);
    if (visible) {
      editor.hidden = false;
      body.hidden = true;
      empty.hidden = true;
      return;
    }
    editor.hidden = true;
    body.hidden = !enabled;
    empty.hidden = enabled;
  }

  function renderGoalStatus(goal) {
    var enabled = !!(goal && goal.enabled);
    var status = goal && goal.status ? goal.status : null;
    var tone = goalTone(goal);
    var label = '';
    var hint = '';
    if (status) {
      label = status.label || '';
      hint = status.hint || '';
      if (status.code === 'no_data') { label = label || 'Нужны взвешивания'; }
    } else if (enabled) {
      label = 'Цель активна';
    }
    var statusNode = byId('today-goal-status');
    if (statusNode) {
      statusNode.textContent = enabled ? (label || '—') : '';
      statusNode.hidden = !enabled;
      statusNode.className = 'goal-status goal-status--' + (enabled ? tone : 'muted');
    }
    var hintNode = byId('today-goal-hint');
    if (hintNode) {
      hintNode.textContent = hint;
      hintNode.hidden = !(enabled && hint);
    }
  }

  function renderTodayGoal(goal) {
    var card = byId('today-goal-card');
    var body = byId('today-goal-body');
    var empty = byId('today-goal-empty');
    var pctNode = byId('today-goal-pct');
    if (!body || !empty) { return; }
    if (card) { card.setAttribute('data-tone', goalTone(goal)); }
    renderGoalStatus(goal);

    var editorOpen = goalEditorOpen();
    var enabled = !!(goal && goal.enabled);
    if (editorOpen) {
      body.hidden = true;
      empty.hidden = true;
    } else {
      body.hidden = !enabled;
      empty.hidden = enabled;
    }

    if (!enabled) {
      if (pctNode) { pctNode.textContent = '—'; }
      return;
    }
    if (editorOpen) { return; }

    var pct = clamp(int(goal.pct), 0, 100);
    byId('today-goal-value').textContent = fmtNumber(goal.goal_weight_kg, 1);
    var sub;
    if (goal.reached) {
      sub = 'Цель достигнута — закрепи результат';
    } else if (goal.direction === 'lose') {
      sub = 'Цель: снизить вес';
    } else {
      sub = 'Цель: набрать массу';
    }
    byId('today-goal-sub').textContent = sub;
    var bar = byId('today-goal-bar');
    bar.style.width = pct + '%';
    if (pctNode) { pctNode.textContent = pct + '%'; }

    if (goal.reached) {
      byId('today-goal-left').textContent = 'Цель достигнута';
    } else if (goal.kg_left != null) {
      byId('today-goal-left').textContent = 'осталось ' + fmtNumber(Math.abs(num(goal.kg_left)), 1) + ' кг';
    } else {
      byId('today-goal-left').textContent = 'нет данных о весе';
    }

    var daysNode = byId('today-goal-days');
    if (goal.days_left != null && goal.goal_date) {
      var days = int(goal.days_left);
      daysNode.textContent = days + ' ' + plural(days, 'день', 'дня', 'дней') + ' до ' + dateShort(goal.goal_date);
    } else if (goal.goal_date) {
      daysNode.textContent = 'до ' + dateShort(goal.goal_date);
    } else {
      daysNode.textContent = 'дата не задана';
    }
  }

  function goalInputDate(goal, profile) {
    if (goal && goal.goal_date) { return String(goal.goal_date).slice(0, 10); }
    if (profile && profile.goal_date) { return String(profile.goal_date).slice(0, 10); }
    return '';
  }

  function goalInputWeight(goal, profile) {
    if (goal && goal.enabled && goal.goal_weight_kg != null) { return goal.goal_weight_kg; }
    if (profile && profile.goal_weight_kg != null) { return profile.goal_weight_kg; }
    return null;
  }

  function openGoalEditor(event) {
    if (event && event.preventDefault) { event.preventDefault(); }
    var editor = byId('today-goal-editor');
    if (!editor) { return; }
    var goal = (state.bootstrap && state.bootstrap.goal) || null;
    var profile = currentProfile() || {};
    var weight = byId('today-goal-input-weight');
    var date = byId('today-goal-input-date');
    var weightValue = goalInputWeight(goal, profile);
    if (weight) {
      weight.value = weightValue != null ? fmtNumber(weightValue, 1).replace(',', '.') : '';
    }
    if (date) { date.value = goalInputDate(goal, profile); }
    var error = byId('today-goal-error');
    if (error) {
      error.textContent = '';
      error.hidden = true;
    }
    goalEditorVisible(true, goal);
    haptic('select');
    try { editor.scrollIntoView({ behavior: 'smooth', block: 'center' }); } catch (errorObj) { /* noop */ }
    window.setTimeout(function () {
      if (weight) { try { weight.focus(); } catch (errorObj) { /* noop */ } }
    }, 60);
  }

  function closeGoalEditor() {
    if (!goalEditorOpen()) { return; }
    goalEditorVisible(false, state.bootstrap && state.bootstrap.goal);
    renderTodayGoal(state.bootstrap && state.bootstrap.goal);
  }

  function showGoalEditorError(message) {
    var error = byId('today-goal-error');
    if (!error) { return; }
    error.textContent = message;
    error.hidden = false;
  }

  /* Локальная перерисовка карточки сразу после PUT — не ждём bootstrap.
     Авторитетные pct/status придут со следующим /api/bootstrap. */
  function applyGoalLocally(goalWeight, goalDate, profile) {
    if (!state.bootstrap) { return; }
    if (profile) { state.bootstrap.profile = profile; }
    var previous = state.bootstrap.goal || {};
    var enabled = goalWeight != null;
    var next = {
      enabled: enabled,
      goal_weight_kg: goalWeight,
      goal_date: goalDate,
      status: previous.status || null
    };
    if (enabled) {
      var start = previous.start_weight_kg != null
        ? num(previous.start_weight_kg)
        : num((profile || {}).weight_kg, goalWeight);
      var current = previous.current_weight_kg != null
        ? num(previous.current_weight_kg)
        : num((profile || {}).weight_kg, start);
      var direction = goalWeight >= current ? 'gain' : 'lose';
      var total = Math.abs(goalWeight - start);
      var done = Math.abs(current - start);
      var reached = direction === 'gain' ? current >= goalWeight : current <= goalWeight;
      next.start_weight_kg = start;
      next.current_weight_kg = current;
      next.direction = direction;
      next.pct = total > 0 ? clamp(Math.round(done / total * 100), 0, 100) : 0;
      next.kg_left = reached ? 0 : Math.abs(goalWeight - current);
      next.kg_done = Math.abs(current - start);
      next.reached = reached;
      if (goalDate) {
        var milliseconds = parseIso(goalDate).getTime() - parseIso(todayIso()).getTime();
        next.days_left = Math.max(0, Math.ceil(milliseconds / 86400000));
      } else {
        next.days_left = null;
      }
      if (next.status && next.status.code === 'no_data' && next.current_weight_kg != null) {
        next.status = null; /* новые данные — статус обновит bootstrap */
      }
    }
    state.bootstrap.goal = next;
    renderTodayGoal(next);
  }

  function submitGoalEditor(event) {
    event.preventDefault();
    var weightRaw = byId('today-goal-input-weight').value.trim();
    var goalDate = byId('today-goal-input-date').value || '';
    var goalWeight = weightRaw ? num(weightRaw) : null;
    if (goalWeight != null && (goalWeight < 30 || goalWeight > 300)) {
      showGoalEditorError('Цель по весу — от 30 до 300 кг');
      toast('Цель по весу — от 30 до 300 кг', 'error');
      haptic('error');
      return;
    }
    if (goalWeight == null && goalDate) {
      showGoalEditorError('Сначала укажи цель по весу');
      toast('Сначала укажи цель по весу', 'error');
      haptic('error');
      return;
    }
    var payload = {
      goal_weight_kg: goalWeight,
      goal_date: goalWeight != null && goalDate ? goalDate : null
    };
    var error = byId('today-goal-error');
    if (error) {
      error.textContent = '';
      error.hidden = true;
    }
    var button = byId('today-goal-save');
    setBusy(button, true);
    apiRequest('PUT', '/api/profile', payload).then(function (data) {
      setBusy(button, false);
      haptic('success');
      var profile = (data && data.profile) || null;
      goalEditorVisible(false, null);
      applyGoalLocally(payload.goal_weight_kg, payload.goal_date, profile);
      if (payload.goal_weight_kg == null) {
        toast('Цель по весу убрана');
      } else {
        toast('Цель сохранена: ' + fmtNumber(payload.goal_weight_kg, 1) + ' кг');
      }
      loadBootstrap({ force: true });
    }).catch(function (errorObj) {
      setBusy(button, false);
      haptic('error');
      showGoalEditorError(errorText(errorObj.code));
      toast(errorText(errorObj.code), 'error'); /* поля не сбрасываем */
    });
  }

  /* ---------- обязательный недельный чек-ин ---------- */

  function weeklyFeeling() {
    var checked = document.querySelector('input[name="weekly-feel"]:checked');
    var value = checked ? String(checked.value) : 'ok';
    return (value === 'good' || value === 'bad') ? value : 'ok';
  }

  function setWeeklyFeeling(value) {
    var normalized = (value === 'good' || value === 'bad') ? value : 'ok';
    qsa('input[name="weekly-feel"]').forEach(function (input) {
      input.checked = input.value === normalized;
    });
  }

  function renderWeeklyModal(weekly) {
    var lastNode = byId('weekly-last');
    if (lastNode) {
      var last = weekly && weekly.last;
      if (last) {
        lastNode.hidden = false;
        lastNode.textContent = 'Прошлый чек-ин: ' +
          fmtNumber(last.weight_kg, 1) + ' кг · ' +
          (last.week_start ? dateShort(last.week_start) : '—');
      } else {
        lastNode.hidden = true;
        lastNode.textContent = '';
      }
    }
    var weight = byId('weekly-weight');
    if (weight) {
      var current = weekly && weekly.current_weight_kg != null
        ? num(weekly.current_weight_kg)
        : num((currentProfile() || {}).weight_kg);
      weight.value = current > 0 ? fmtNumber(current, 1).replace(',', '.') : '';
    }
    var recalc = byId('weekly-recalc');
    if (recalc && recalc.checked !== true) { recalc.checked = true; }
    setWeeklyFeeling('ok');
    var error = byId('weekly-error');
    if (error) {
      error.textContent = '';
      error.hidden = true;
    }
  }

  function showWeeklyModal() {
    var node = byId('weekly-modal');
    if (!node) { return; }
    state.weekly.shown = true;
    node.hidden = false;
    document.body.classList.add('modal-open');
    window.setTimeout(function () {
      var input = byId('weekly-weight');
      if (input) { try { input.focus(); } catch (error) { /* noop */ } }
    }, 80);
  }

  function hideWeeklyModal() {
    var node = byId('weekly-modal');
    if (!node) { return; }
    node.hidden = true;
    document.body.classList.remove('modal-open');
  }

  function handleWeeklyDue(bootstrap) {
    var weekly = bootstrap && bootstrap.weekly ? bootstrap.weekly : null;
    if (!weekly || !weekly.due) {
      if (state.weekly.shown && !state.weekly.busy) { hideWeeklyModal(); }
      return;
    }
    if (state.weekly.shown) { return; }
    renderWeeklyModal(weekly);
    showWeeklyModal();
  }

  function showWeeklyError(message) {
    var error = byId('weekly-error');
    if (!error) { return; }
    error.textContent = message;
    error.hidden = false;
  }

  function submitWeekly(event) {
    event.preventDefault();
    if (state.weekly.busy) { return; }
    var weightInput = byId('weekly-weight');
    var weightRaw = weightInput ? weightInput.value.trim() : '';
    var weight = weightRaw ? num(weightRaw) : 0;
    if (!weightRaw || weight < 30 || weight > 300) {
      showWeeklyError('Укажи вес от 30 до 300 кг');
      toast('Вес — от 30 до 300 кг', 'error');
      haptic('error');
      if (weightInput) { weightInput.focus(); }
      return;
    }
    var recalc = byId('weekly-recalc');
    var payload = {
      weight_kg: weight,
      feeling: weeklyFeeling(),
      note: byId('weekly-note') ? byId('weekly-note').value.trim() : '',
      recalc: !!(recalc && recalc.checked)
    };
    var button = byId('weekly-save');
    state.weekly.busy = true;
    setBusy(button, true);
    apiRequest('POST', '/api/weekly', payload).then(function (data) {
      state.weekly.busy = false;
      state.weekly.saved = true;
      setBusy(button, false);
      haptic('success');
      if (state.bootstrap) {
        if (data && data.profile) { state.bootstrap.profile = data.profile; }
        if (data && data.targets) { state.bootstrap.targets = data.targets; }
        if (data && data.goal) {
          state.bootstrap.goal = data.goal;
          renderTodayGoal(data.goal);
        }
      }
      hideWeeklyModal();
      var targets = data && data.targets;
      if (payload.recalc && targets && num(targets.kcal) > 0) {
        toast('КБЖУ пересчитаны: ' + fmtInt(targets.kcal) + ' ккал / белок ' +
          fmtInt(targets.protein) + ' г');
      } else {
        toast('Прогресс сохранён');
      }
      loadBootstrap({ force: true });
    }).catch(function (errorObj) {
      state.weekly.busy = false;
      setBusy(button, false);
      haptic('error');
      showWeeklyError(errorText(errorObj.code));
      toast(errorText(errorObj.code), 'error'); /* модалка остаётся, поля не теряем */
    });
  }

  function isDayDone(item) {
    return !!(item && (item.done === true || int(item.done) === 1));
  }

  function sortedDayItems(day) {
    var items = (day && day.items) || [];
    return items.slice().sort(function (a, b) {
      return hmToMin(a.time) - hmToMin(b.time);
    });
  }

  function upcomingDayItems(items, limit) {
    var current = nowMinutes();
    var upcoming = items.filter(function (item) {
      return !isDayDone(item) && hmToMin(item.time) >= current;
    });
    var result = upcoming.slice(0, limit);
    if (result.length < limit) {
      var extras = items.filter(function (item) { return result.indexOf(item) === -1; });
      result = result.concat(extras.slice(0, limit - result.length));
    }
    result.sort(function (a, b) { return hmToMin(a.time) - hmToMin(b.time); });
    return result;
  }

  function dayRowHtml(item, options) {
    var opts = options || {};
    var done = isDayDone(item);
    var kind = DAY_KIND_LABELS[item.kind] ? item.kind : 'other';
    var meta = '<span class="day-kind day-kind--' + kind + '">' + esc(DAY_KIND_LABELS[kind]) + '</span>' +
      '<span>' + esc(fmtDuration(item.duration_min || 0)) + '</span>';
    var note = item.note ? '<p class="day-row__note">' + esc(item.note) + '</p>' : '';
    var actions = opts.editable
      ? '<div class="day-row__actions">' +
          '<button type="button" class="mini-btn mini-btn--edit" data-edit-day="' + esc(item.id) + '" ' +
            'aria-label="Изменить блок ' + esc(item.title || '') + '">Изменить</button>' +
        '</div>'
      : '';
    return '<li class="day-row' + (done ? ' is-done' : '') + '">' +
      '<button type="button" class="day-check" data-day-toggle="' + esc(item.id) + '" ' +
        'data-day-done="' + (done ? '1' : '0') + '" aria-pressed="' + (done ? 'true' : 'false') + '" ' +
        'aria-label="' + (done ? 'Снять отметку о выполнении' : 'Отметить выполненным') + '">' +
        (done ? '✓' : '') + '</button>' +
      '<span class="day-row__time">' + esc(String(item.time || '').slice(0, 5)) + '</span>' +
      '<div class="day-row__main">' +
        '<p class="day-row__title">' + esc(item.title || 'Блок дня') + '</p>' +
        '<p class="day-row__meta">' + meta + '</p>' +
        note +
      '</div>' +
      actions +
    '</li>';
  }

  function daySummaryText(day) {
    var items = (day && day.items) || [];
    var summary = (day && day.summary) || null;
    var total = summary && summary.total != null ? int(summary.total) : items.length;
    var done = summary && summary.done != null
      ? int(summary.done)
      : items.filter(isDayDone).length;
    if (!total) { return '—'; }
    var minutes = 0;
    if (summary && (summary.done_minutes != null || summary.planned_minutes != null)) {
      minutes = int(summary.done_minutes || summary.planned_minutes);
    } else {
      items.forEach(function (item) { if (isDayDone(item)) { minutes += int(item.duration_min); } });
    }
    return done + ' из ' + total + (minutes > 0 ? ' · ' + fmtDuration(minutes) : '');
  }

  function renderTodayDay(day) {
    var list = byId('today-day-list');
    var empty = byId('today-day-empty');
    var summaryNode = byId('today-day-summary');
    if (!list || !empty) { return; }
    if (summaryNode) { summaryNode.textContent = daySummaryText(day); }
    var items = sortedDayItems(day);
    if (!items.length) {
      list.innerHTML = '';
      empty.hidden = false;
      empty.textContent = 'На сегодня блоков нет. Составь план в «Расписании».';
      return;
    }
    var shown = upcomingDayItems(items, 5);
    if (!shown.length) {
      list.innerHTML = '';
      empty.hidden = false;
      empty.textContent = 'На сегодня всё выполнено — так держать!';
      return;
    }
    empty.hidden = true;
    list.innerHTML = shown.map(function (item) {
      return dayRowHtml(item, { editable: false });
    }).join('');
  }

  /* ======================= экран «Еда» ======================= */

  function loadFood(options) {
    var opts = options || {};
    if (state.food.loading) { return; }
    if (!state.food.data && !opts.silent) { setScreenLoading('food', true); }
    state.food.loading = true;
    var date = state.food.date;
    apiRequest('GET', '/api/meals?date=' + encodeURIComponent(date)).then(function (data) {
      state.food.loading = false;
      state.food.data = data || { meals: [], totals: {} };
      setScreenLoading('food', false);
      renderFood();
    }).catch(function (error) {
      state.food.loading = false;
      setScreenLoading('food', false);
      toast(errorText(error.code), 'error');
    });
  }

  function updateFoodDateUi() {
    byId('food-date-label').textContent = dayLabel(state.food.date);
    byId('food-next').disabled = state.food.date >= todayIso();
  }

  function shiftFoodDate(delta) {
    var next = isoDate(addDays(parseIso(state.food.date), delta));
    if (next > todayIso()) { return; }
    state.food.date = next;
    haptic('select');
    updateFoodDateUi();
    loadFood();
  }

  function renderFood() {
    var data = state.food.data || { meals: [], totals: {} };
    var totals = data.totals || {};
    var targets = currentTargets() || {};
    var goal = num(targets.kcal);
    var eaten = num(totals.kcal);

    updateFoodDateUi();
    byId('food-eaten').textContent = fmtInt(eaten);
    byId('food-goal').textContent = goal > 0 ? fmtInt(goal) : '—';

    var left = Math.round(goal - eaten);
    var leftNode = byId('food-left');
    if (goal <= 0) {
      leftNode.textContent = 'цель не задана';
    } else if (left >= 0) {
      leftNode.textContent = 'осталось ' + fmtInt(left) + ' ккал';
    } else {
      leftNode.textContent = 'перебор ' + fmtInt(-left) + ' ккал';
    }
    leftNode.classList.toggle('is-over', goal > 0 && left < 0);

    var bar = byId('food-progress-bar');
    bar.style.width = goal > 0 ? clamp((eaten / goal) * 100, 0, 100).toFixed(1) + '%' : '0%';
    bar.classList.toggle('is-over', goal > 0 && eaten > goal);

    byId('food-total-protein').textContent = fmtNumber(totals.protein, 1);
    byId('food-total-fat').textContent = fmtNumber(totals.fat, 1);
    byId('food-total-carbs').textContent = fmtNumber(totals.carbs, 1);

    renderMealList(data.meals || []);
  }

  function renderMealList(meals) {
    var list = byId('food-list');
    var empty = byId('food-empty');
    if (!meals.length) {
      list.innerHTML = '';
      empty.hidden = false;
      return;
    }
    empty.hidden = true;
    var sorted = meals.slice().sort(function (a, b) {
      return hmToMin(a.time) - hmToMin(b.time);
    });
    list.innerHTML = sorted.map(function (meal) {
      var note = meal.note ? '<p class="meal-item__note">' + esc(meal.note) + '</p>' : '';
      var grams = num(meal.grams) > 0 ? fmtNumber(meal.grams, 0) + ' г' : '';
      var amount = grams ? grams + ' · ' + fmtInt(meal.kcal) + ' ккал' : fmtInt(meal.kcal) + ' ккал';
      var macros = 'Б ' + fmtNumber(meal.protein, 1) +
        ' · Ж ' + fmtNumber(meal.fat, 1) +
        ' · У ' + fmtNumber(meal.carbs, 1) + ' г';
      var ingredients = mealIngredientsText(meal);
      return '<li class="meal-item">' +
        '<div class="meal-item__main">' +
          '<div class="meal-item__head">' +
            '<span class="meal-item__time">' + esc(meal.time || '') + '</span>' +
            '<span class="meal-item__title">' + esc(meal.title || 'Приём пищи') + '</span>' +
            '<span class="meal-item__kcal">' + esc(amount) + '</span>' +
          '</div>' +
          (ingredients ? '<p class="meal-item__ingredients">' + ingredients + '</p>' : '') +
          '<p class="meal-item__macros">' + macros + '</p>' +
          note +
        '</div>' +
        '<button type="button" class="meal-item__delete" data-delete-meal="' + esc(meal.id) + '" ' +
          'aria-label="Удалить приём ' + esc(meal.title || '') + '">×</button>' +
      '</li>';
    }).join('');
  }

  /* Компактный перечень ингредиентов приёма: «куриная грудка 200 г · яйцо 100 г». */
  function mealIngredientsText(meal) {
    var items = meal && Array.isArray(meal.items) ? meal.items : [];
    var parts = [];
    items.forEach(function (item) {
      if (!item || typeof item !== 'object') { return; }
      var title = String(item.title || '').trim();
      if (!title) { return; }
      var portion = num(item.grams) > 0 ? ' ' + fmtNumber(item.grams, 0) + ' г' : '';
      parts.push(esc(title + portion));
    });
    return parts.length >= 2 ? parts.join(' · ') : '';
  }

  /* ======================= еда: мультиингредиенты, подсказки, граммы ======================= */

  function renderPresets() {
    var box = byId('meal-presets');
    if (!box) { return; }
    box.innerHTML = PRODUCT_PRESETS.map(function (preset, index) {
      return '<button type="button" class="preset" data-product-preset="' + index + '">' +
        esc(preset.label) + '</button>';
    }).join('');
  }

  function mealMacros(food, grams) {
    var factor = num(grams) / 100;
    return {
      kcal: Math.round(num(food.kcal) * factor),
      protein: Math.round(num(food.protein) * factor * 10) / 10,
      fat: Math.round(num(food.fat) * factor * 10) / 10,
      carbs: Math.round(num(food.carbs) * factor * 10) / 10
    };
  }

  /* ---------- строки ингредиентов ---------- */

  function newMealItem(preset) {
    state.food.rowSeq = (state.food.rowSeq || 0) + 1;
    return {
      key: 'meal-row-' + state.food.rowSeq,
      title: preset && preset.title ? String(preset.title) : '',
      grams: preset && num(preset.grams, 0) > 0 ? clamp(int(preset.grams, 100), 1, 3000) : 100,
      food: null,
      suggest: { items: [], active: -1, loading: false, timer: null, seq: 0 }
    };
  }

  function mealItemByKey(key) {
    var found = null;
    (state.food.items || []).forEach(function (item) {
      if (String(item.key) === String(key)) { found = item; }
    });
    return found;
  }

  function mealItemRow(item) {
    return document.querySelector('[data-meal-row="' + String(item.key) + '"]');
  }

  function mealRowPreviewText(item) {
    if (!item.food) {
      return 'Выбери продукт из подсказок — КБЖУ посчитается сам';
    }
    var macros = mealMacros(item.food, item.grams);
    return '≈ ' + fmtInt(macros.kcal) + ' ккал · Б ' + fmtNumber(macros.protein, 1) +
      ' · Ж ' + fmtNumber(macros.fat, 1) + ' · У ' + fmtNumber(macros.carbs, 1);
  }

  function mealRowPer100Text(item) {
    if (!item.food) { return ''; }
    return 'на 100 г: ' + fmtInt(item.food.kcal) + ' ккал · Б ' + fmtNumber(item.food.protein, 1) +
      ' · Ж ' + fmtNumber(item.food.fat, 1) + ' · У ' + fmtNumber(item.food.carbs, 1);
  }

  function mealRowHtml(item, index) {
    var removable = (state.food.items || []).length > 1;
    var removeButton = removable
      ? '<button type="button" class="meal-item__remove" data-meal-row-remove="' + esc(item.key) + '" ' +
          'aria-label="Удалить ингредиент ' + (index + 1) + '">×</button>'
      : '';
    return '<div class="meal-item-row" data-meal-row="' + esc(item.key) + '">' +
      '<div class="meal-item-row__head">' +
        '<input class="meal-item__title" type="text" maxlength="120" value="' + esc(item.title) + '" ' +
          'placeholder="Продукт" autocomplete="off" role="combobox" aria-autocomplete="list" ' +
          'aria-expanded="false" data-meal-title="' + esc(item.key) + '" ' +
          'aria-label="Продукт, ингредиент ' + (index + 1) + '">' +
        '<input class="meal-item__grams" type="number" inputmode="numeric" min="5" max="3000" step="10" ' +
          'value="' + esc(String(item.grams)) + '" placeholder="г" data-meal-grams="' + esc(item.key) + '" ' +
          'aria-label="Граммы, ингредиент ' + (index + 1) + '">' +
        removeButton +
      '</div>' +
      '<div class="food-suggest meal-item__suggest" data-meal-suggest="' + esc(item.key) + '" hidden></div>' +
      '<p class="meal-item__per100" data-meal-per100="' + esc(item.key) + '"' +
        (item.food ? '' : ' hidden') + '>' + esc(mealRowPer100Text(item)) + '</p>' +
      '<p class="meal-preview meal-item__preview" data-meal-preview="' + esc(item.key) + '">' +
        esc(mealRowPreviewText(item)) + '</p>' +
    '</div>';
  }

  function renderMealItems() {
    var box = byId('meal-items');
    if (!box) { return; }
    if (!state.food.items.length) { state.food.items.push(newMealItem(null)); }
    box.innerHTML = state.food.items.map(mealRowHtml).join('');
    updateMealTotal();
  }

  function updateMealRow(item) {
    var row = mealItemRow(item);
    if (!row) { return; }
    var preview = row.querySelector('[data-meal-preview]');
    if (preview) { preview.textContent = mealRowPreviewText(item); }
    var per100 = row.querySelector('[data-meal-per100]');
    if (per100) {
      per100.textContent = mealRowPer100Text(item);
      per100.hidden = !item.food;
    }
  }

  function updateMealTotal() {
    var node = byId('meal-total');
    if (!node) { return; }
    var totals = { kcal: 0, protein: 0, fat: 0, carbs: 0 };
    (state.food.items || []).forEach(function (item) {
      if (!item.food) { return; }
      var macros = mealMacros(item.food, item.grams);
      totals.kcal += macros.kcal;
      totals.protein += macros.protein;
      totals.fat += macros.fat;
      totals.carbs += macros.carbs;
    });
    node.textContent = 'Итого: ' + fmtInt(totals.kcal) + ' ккал · Б ' + fmtNumber(totals.protein, 1) +
      ' · Ж ' + fmtNumber(totals.fat, 1) + ' · У ' + fmtNumber(totals.carbs, 1);
  }

  function markMealRowsInvalid(items) {
    var keys = {};
    (items || []).forEach(function (item) { keys[item.key] = true; });
    qsa('[data-meal-row]').forEach(function (row) {
      row.classList.toggle('is-invalid', !!keys[row.getAttribute('data-meal-row')]);
    });
  }

  /* ---------- live-подсказки в строке ---------- */

  function hideMealSuggestions(exceptKey) {
    qsa('[data-meal-suggest]').forEach(function (box) {
      if (exceptKey && String(box.getAttribute('data-meal-suggest')) === String(exceptKey)) { return; }
      box.hidden = true;
      box.innerHTML = '';
    });
    qsa('.meal-item__title').forEach(function (input) {
      if (exceptKey && String(input.getAttribute('data-meal-title')) === String(exceptKey)) { return; }
      input.setAttribute('aria-expanded', 'false');
    });
  }

  function renderRowSuggestions(item) {
    var box = document.querySelector('[data-meal-suggest="' + String(item.key) + '"]');
    var input = document.querySelector('[data-meal-title="' + String(item.key) + '"]');
    if (!box) { return; }
    var items = (item.suggest && item.suggest.items) || [];
    if (!items.length) {
      box.hidden = true;
      box.innerHTML = '';
      if (input) { input.setAttribute('aria-expanded', 'false'); }
      return;
    }
    box.hidden = false;
    if (input) { input.setAttribute('aria-expanded', 'true'); }
    box.innerHTML = items.map(function (food, index) {
      var active = index === item.suggest.active;
      return '<button type="button" class="food-suggest__item' + (active ? ' is-active' : '') + '" ' +
        'role="option" data-food-id="' + esc(food.id) + '" data-row-key="' + esc(item.key) + '" ' +
        'aria-selected="' + (active ? 'true' : 'false') + '">' +
        '<span class="food-suggest__name">' + esc(food.name) + '</span>' +
        '<span class="food-suggest__kcal">' + fmtInt(food.kcal) + ' ккал / 100 г</span>' +
      '</button>';
    }).join('');
  }

  function requestRowSuggestions(item, query) {
    var seq = ++item.suggest.seq;
    item.suggest.loading = true;
    apiRequest('GET', '/api/foods?q=' + encodeURIComponent(query) + '&limit=8').then(function (data) {
      if (seq !== item.suggest.seq) { return; }
      item.suggest.loading = false;
      item.suggest.items = ((data && data.items) || []).slice(0, 8);
      item.suggest.active = -1;
      renderRowSuggestions(item);
    }).catch(function () {
      if (seq !== item.suggest.seq) { return; }
      item.suggest.loading = false;
      item.suggest.items = [];
      renderRowSuggestions(item); /* API может быть ещё не готов — не мешаем вводу */
    });
  }

  function scheduleRowSearch(item, query) {
    var suggest = item.suggest;
    if (suggest.timer) { window.clearTimeout(suggest.timer); suggest.timer = null; }
    if (!query) {
      suggest.items = [];
      renderRowSuggestions(item);
      return;
    }
    suggest.timer = window.setTimeout(function () {
      suggest.timer = null;
      requestRowSuggestions(item, query);
    }, 200);
  }

  function setRowFood(item, food) {
    item.food = food || null;
    item.suggest.seq += 1;
    item.suggest.items = [];
    item.suggest.active = -1;
    if (food) {
      item.title = food.name || item.title;
      var input = document.querySelector('[data-meal-title="' + String(item.key) + '"]');
      if (input) { input.value = item.title; }
    }
    renderRowSuggestions(item);
    updateMealRow(item);
    updateMealTotal();
    clearMealFormError();
  }

  /* ---------- обработчики строк ---------- */

  function onMealItemsInput(event) {
    var target = event.target;
    if (!target || !target.closest) { return; }
    var titleInput = target.closest('.meal-item__title');
    if (titleInput) {
      var item = mealItemByKey(titleInput.getAttribute('data-meal-title'));
      if (!item) { return; }
      item.title = titleInput.value;
      if (item.food && String(item.food.name || '').toLowerCase() !== item.title.trim().toLowerCase()) {
        item.food = null;
        updateMealTotal();
      }
      var row = titleInput.closest('.meal-item-row');
      if (row) { row.classList.remove('is-invalid'); }
      clearMealFormError();
      scheduleRowSearch(item, item.title.trim());
      updateMealRow(item);
      return;
    }
    var gramsInput = target.closest('.meal-item__grams');
    if (gramsInput) {
      var gramsItem = mealItemByKey(gramsInput.getAttribute('data-meal-grams'));
      if (!gramsItem) { return; }
      gramsItem.grams = clamp(int(gramsInput.value, 100), 1, 3000);
      updateMealRow(gramsItem);
      updateMealTotal();
    }
  }

  function onMealItemsFocus(event) {
    var target = event.target;
    if (!target || !target.closest) { return; }
    var input = target.closest('.meal-item__title');
    if (!input) { return; }
    var item = mealItemByKey(input.getAttribute('data-meal-title'));
    if (!item) { return; }
    hideMealSuggestions(item.key);
    var query = input.value.trim();
    if (!query && !(item.suggest.items || []).length) {
      requestRowSuggestions(item, ''); /* пустой q — популярные продукты */
      return;
    }
    if ((item.suggest.items || []).length) {
      renderRowSuggestions(item);
    }
  }

  function onMealItemsKeydown(event) {
    var target = event.target;
    if (!target || !target.closest) { return; }
    var input = target.closest('.meal-item__title');
    if (!input) { return; }
    var item = mealItemByKey(input.getAttribute('data-meal-title'));
    if (!item) { return; }
    var suggest = item.suggest;
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      if (!suggest.items.length) { return; }
      event.preventDefault();
      var delta = event.key === 'ArrowDown' ? 1 : -1;
      suggest.active = suggest.active < 0
        ? 0
        : clamp(suggest.active + delta, 0, suggest.items.length - 1);
      renderRowSuggestions(item);
      return;
    }
    if (event.key === 'Enter') {
      if (suggest.items.length) {
        event.preventDefault();
        var index = suggest.active >= 0 ? suggest.active : 0;
        setRowFood(item, suggest.items[index]);
        haptic('select');
      }
      return;
    }
    if (event.key === 'Escape') {
      suggest.items = [];
      renderRowSuggestions(item);
    }
  }

  function onMealItemsClick(event) {
    var target = event.target;
    if (!target || !target.closest) { return; }
    var removeButton = target.closest('[data-meal-row-remove]');
    if (removeButton) {
      removeMealItem(removeButton.getAttribute('data-meal-row-remove'));
      return;
    }
    var foodButton = target.closest('[data-food-id]');
    if (!foodButton) { return; }
    var item = mealItemByKey(foodButton.getAttribute('data-row-key'));
    if (!item) { return; }
    var food = null;
    (item.suggest.items || []).forEach(function (candidate) {
      if (String(candidate.id) === String(foodButton.getAttribute('data-food-id'))) { food = candidate; }
    });
    if (!food) { return; }
    setRowFood(item, food);
    haptic('select');
  }

  function addMealItem(preset) {
    if (state.food.manual) { toggleManualMode(); }
    var item = null;
    /* Пресет заполняет единственную пустую строку, если она ещё нетронута,
       иначе добавляет новую — «пресеты добавляют строку» без пустых остатков. */
    if (preset && state.food.items.length === 1) {
      var candidate = state.food.items[0];
      if (!String(candidate.title || '').trim() && !candidate.food && int(candidate.grams, 100) === 100) {
        item = candidate;
        item.title = String(preset.title);
        item.grams = clamp(int(preset.grams, 100), 1, 3000);
        item.suggest.items = [];
        item.suggest.active = -1;
      }
    }
    if (item) {
      renderMealItems();
    } else {
      item = newMealItem(preset);
      state.food.items.push(item);
      renderMealItems();
    }
    clearMealFormError();
    var input = document.querySelector('[data-meal-title="' + String(item.key) + '"]');
    if (input) {
      try { input.scrollIntoView({ behavior: 'smooth', block: 'center' }); } catch (error) { /* noop */ }
      try { input.focus(); } catch (error) { /* noop */ }
    }
    haptic('select');
    if (preset && preset.title) {
      /* Пресет сразу даёт продукт и граммы; точное имя/КБЖУ подтягиваем с сервера. */
      var seq = ++item.suggest.seq;
      apiRequest('GET', '/api/foods?q=' + encodeURIComponent(preset.title) + '&limit=1').then(function (data) {
        if (seq !== item.suggest.seq) { return; }
        var items = (data && data.items) || [];
        if (items.length && !item.food) { setRowFood(item, items[0]); }
      }).catch(function () { /* подсказки недоступны — отправим текст как есть */ });
    }
    return item;
  }

  function removeMealItem(key) {
    if ((state.food.items || []).length <= 1) { return; }
    state.food.items = state.food.items.filter(function (item) {
      return String(item.key) !== String(key);
    });
    renderMealItems();
    clearMealFormError();
    haptic('select');
  }

  function applyProductPreset(index) {
    var preset = PRODUCT_PRESETS[index];
    if (!preset) { return; }
    addMealItem(preset);
  }

  function applyFoodSuggestion(foodId) {
    var food = null;
    (state.food.notFound || []).forEach(function (candidate) {
      if (String(candidate.id) === String(foodId)) { food = candidate; }
    });
    if (!food) { return; }
    var target = null;
    (state.food.items || []).forEach(function (item) {
      if (!target && !item.food) { target = item; }
    });
    if (!target) { target = addMealItem(null); }
    setRowFood(target, food);
    var box = byId('food-notfound-suggest');
    if (box) {
      box.hidden = true;
      box.innerHTML = '';
    }
  }

  function syncMealMode() {
    var manual = state.food.manual;
    var itemsBox = byId('meal-items');
    var addButton = byId('meal-add-item');
    var total = byId('meal-total');
    if (itemsBox) { itemsBox.hidden = manual; }
    if (addButton) { addButton.hidden = manual; }
    if (total) { total.hidden = manual; }
    var manualBox = byId('meal-manual');
    if (manualBox) { manualBox.hidden = !manual; }
    var submit = byId('meal-submit');
    if (submit) { submit.textContent = manual ? 'Добавить вручную' : 'Добавить'; }
    var toggle = byId('btn-meal-manual');
    if (toggle) {
      toggle.setAttribute('aria-expanded', manual ? 'true' : 'false');
      toggle.textContent = manual ? 'вернуться к автоКБЖУ' : 'ввести вручную';
    }
    if (manual) { hideMealSuggestions(); }
  }

  function toggleManualMode() {
    state.food.manual = !state.food.manual;
    syncMealMode();
    clearMealFormError();
    haptic('select');
  }

  function clearMealFormError() {
    var error = byId('meal-form-error');
    if (error) {
      error.hidden = true;
      error.textContent = '';
    }
    var suggest = byId('food-notfound-suggest');
    if (suggest) {
      suggest.hidden = true;
      suggest.innerHTML = '';
    }
  }

  function showMealFormError(message) {
    var error = byId('meal-form-error');
    if (!error) { return; }
    error.textContent = message;
    error.hidden = false;
  }

  function showFoodNotFound(query) {
    var error = byId('meal-form-error');
    if (error) {
      error.textContent = 'Не нашёл продукт «' + query + '» — уточни название.';
      error.hidden = false;
    }
    var box = byId('food-notfound-suggest');
    if (!box) { return; }
    box.hidden = true;
    box.innerHTML = '';
    apiRequest('GET', '/api/foods?q=' + encodeURIComponent(query) + '&limit=3').then(function (data) {
      var items = (data && data.items) || [];
      if (!items.length) { return; }
      state.food.notFound = items.slice();
      box.innerHTML = items.map(function (food) {
        return '<button type="button" class="preset" data-suggest-food="' + esc(food.id) + '">' +
          esc(food.name) + ' · ' + fmtInt(food.kcal) + ' ккал</button>';
      }).join('');
      box.hidden = false;
    }).catch(function () { /* сервер подсказок недоступен */ });
  }

  function openMealForm() {
    var form = byId('meal-form');
    form.hidden = false;
    byId('btn-open-meal-form').hidden = true;
    if (!byId('meal-time').value) { byId('meal-time').value = nowHm(); }
    if (!state.food.items.length) { state.food.items.push(newMealItem(null)); }
    renderMealItems();
    syncMealMode();
    try { form.scrollIntoView({ behavior: 'smooth', block: 'center' }); } catch (error) { /* noop */ }
    window.setTimeout(function () {
      var input = document.querySelector('.meal-item__title');
      if (input) { try { input.focus(); } catch (error) { /* noop */ } }
    }, 60);
  }

  function closeMealForm() {
    byId('meal-form').hidden = true;
    byId('btn-open-meal-form').hidden = false;
  }

  function resetMealForm() {
    state.food.items = [newMealItem(null)];
    state.food.notFound = [];
    state.food.manual = false;
    byId('meal-title').value = '';
    byId('meal-kcal').value = '';
    byId('meal-protein').value = '';
    byId('meal-fat').value = '';
    byId('meal-carbs').value = '';
    byId('meal-note').value = '';
    byId('meal-time').value = nowHm();
    renderMealItems();
    syncMealMode();
    clearMealFormError();
  }

  function submitMeal(event) {
    event.preventDefault();
    var timeValue = byId('meal-time').value || nowHm();
    var note = byId('meal-note').value.trim();
    var payload;
    var successText;

    if (state.food.manual) {
      var title = byId('meal-title').value.trim();
      if (!title) {
        toast('Что съел? Добавь название продукта', 'error');
        byId('meal-title').focus();
        return;
      }
      var kcal = num(byId('meal-kcal').value);
      if (kcal <= 0) {
        toast('Укажи калорийность вручную', 'error');
        byId('meal-kcal').focus();
        return;
      }
      payload = {
        date: state.food.date,
        time: timeValue,
        title: title,
        kcal: kcal,
        protein: num(byId('meal-protein').value),
        fat: num(byId('meal-fat').value),
        carbs: num(byId('meal-carbs').value),
        note: note
      };
      successText = 'Записано: ' + title;
    } else {
      var items = [];
      (state.food.items || []).forEach(function (item) {
        var itemTitle = String(item.title || '').trim();
        if (!itemTitle) { return; } /* пустые строки не отправляем */
        var portion = { grams: clamp(int(item.grams, 100), 1, 3000) };
        if (item.food && item.food.id != null) {
          portion.food_id = item.food.id;
        } else {
          portion.title = itemTitle;
        }
        items.push(portion);
      });
      if (!items.length) {
        markMealRowsInvalid(state.food.items);
        toast('Выбери продукт во всех строках', 'error');
        haptic('error');
        return;
      }
      markMealRowsInvalid([]);
      payload = { date: state.food.date, time: timeValue, note: note, items: items };
      successText = 'Записано: ' + items.length + ' ' +
        plural(items.length, 'ингредиент', 'ингредиента', 'ингредиентов');
    }

    clearMealFormError();
    var button = byId('meal-submit');
    setBusy(button, true);
    apiRequest('POST', '/api/meals', payload).then(function (data) {
      setBusy(button, false);
      haptic('success');
      var meal = data && data.meal;
      if (!state.food.manual && meal && num(meal.kcal) > 0) {
        successText += ' · ' + fmtInt(meal.kcal) + ' ккал';
      }
      toast(successText);
      resetMealForm();
      closeMealForm();
      state.food.data = null;
      loadFood({ silent: true });
      if (state.food.date === todayIso()) { loadBootstrap(); }
    }).catch(function (error) {
      setBusy(button, false);
      haptic('error');
      if (error.code === 'food_not_found') {
        var missing = [];
        (state.food.items || []).forEach(function (item) {
          if (String(item.title || '').trim() && !item.food) { missing.push(item); }
        });
        markMealRowsInvalid(missing);
        showMealFormError('Не нашёл один из ингредиентов — уточни название.');
        if (missing.length) { showFoodNotFound(String(missing[0].title || '').trim()); }
        return; /* строки не очищаем — пусть пользователь уточнит */
      }
      if (error.code === 'bad_request') {
        showMealFormError(errorText(error.code));
      } else {
        toast(errorText(error.code), 'error');
      }
    });
  }

  function deleteMeal(mealId) {
    askConfirm('Удалить этот приём пищи?', function () {
      apiRequest('DELETE', '/api/meals/' + encodeURIComponent(mealId)).then(function () {
        haptic('warning');
        toast('Приём удалён');
        state.food.data = null;
        loadFood({ silent: true });
        if (state.food.date === todayIso()) { loadBootstrap(); }
      }).catch(function (error) {
        haptic('error');
        toast(errorText(error.code), 'error');
      });
    });
  }

  /* ======================= экран «Сон» ======================= */

  function loadSleep(options) {
    var opts = options || {};
    if (state.sleep.loading) { return; }
    if (!state.sleep.data && !opts.silent) { setScreenLoading('sleep', true); }
    state.sleep.loading = true;
    var today = todayIso();
    Promise.all([
      apiRequest('GET', '/api/sleep?date=' + encodeURIComponent(today)),
      apiRequest('GET', '/api/plan?date=' + encodeURIComponent(today)).catch(function () { return null; }),
      apiRequest('GET', '/api/meals?date=' + encodeURIComponent(today)).catch(function () { return null; })
    ]).then(function (results) {
      state.sleep.loading = false;
      state.sleep.data = results[0] || { sleep: null, week: [], avg_h: null, debt_h: null };
      state.sleep.plan = results[1] || null;
      state.sleep.meals = results[2] || null;
      setScreenLoading('sleep', false);
      renderSleep();
      renderSleepSync();
    }).catch(function (error) {
      state.sleep.loading = false;
      setScreenLoading('sleep', false);
      toast(errorText(error.code), 'error');
    });
  }

  function renderSleep() {
    var data = state.sleep.data || {};
    var profile = currentProfile() || {};
    var sleep = data.sleep || null;
    byId('sleep-date-label').textContent = 'Сон · ' + dateShort(todayIso());

    var bed = sleep && sleep.bed_time ? sleep.bed_time : (profile.sleep_bed || '23:00');
    var wake = sleep && sleep.wake_time ? sleep.wake_time : (profile.sleep_wake || '07:00');
    byId('sleep-bed').value = String(bed).slice(0, 5);
    byId('sleep-wake').value = String(wake).slice(0, 5);
    byId('sleep-note').value = sleep && sleep.note ? sleep.note : '';
    setQuality(sleep ? int(sleep.quality, 3) : 3);
    updateSleepDuration();

    renderSleepWeek(data.week || [], data.avg_h, data.debt_h);
  }

  function setQuality(value) {
    state.sleep.quality = clamp(int(value, 3), 1, 5);
    qsa('#sleep-quality .star').forEach(function (star) {
      var pressed = int(star.getAttribute('data-q')) <= state.sleep.quality;
      star.setAttribute('aria-pressed', pressed ? 'true' : 'false');
    });
    byId('sleep-quality-label').textContent =
      'Качество: ' + state.sleep.quality + ' из 5 — ' + QUALITY_LABELS[state.sleep.quality];
  }

  function updateSleepDuration() {
    var bed = byId('sleep-bed').value;
    var wake = byId('sleep-wake').value;
    if (!bed || !wake) {
      byId('sleep-duration').textContent = '—';
      return;
    }
    if (bed === wake) {
      byId('sleep-duration').textContent = 'укажи разные время';
      return;
    }
    byId('sleep-duration').textContent = fmtDuration(durationBetween(bed, wake) * 60);
  }

  function submitSleep() {
    var bed = byId('sleep-bed').value;
    var wake = byId('sleep-wake').value;
    if (!bed || !wake) {
      toast('Укажи время отбоя и подъёма', 'error');
      return;
    }
    if (bed === wake) {
      toast('Отбой и подъём не могут совпадать', 'error');
      return;
    }
    var button = byId('sleep-submit');
    setBusy(button, true);
    var payload = {
      date: todayIso(),
      bed_time: bed,
      wake_time: wake,
      quality: state.sleep.quality,
      note: byId('sleep-note').value.trim()
    };
    apiRequest('POST', '/api/sleep', payload).then(function () {
      setBusy(button, false);
      haptic('success');
      toast('Сон записан: ' + fmtDuration(durationBetween(bed, wake) * 60));
      state.sleep.data = null;
      loadSleep({ silent: true });
      loadBootstrap();
    }).catch(function (error) {
      setBusy(button, false);
      haptic('error');
      toast(errorText(error.code), 'error');
    });
  }

  function renderSleepSync() {
    var profile = currentProfile() || {};
    var plan = state.sleep.plan;
    var bed = byId('sleep-bed').value || profile.sleep_bed || '23:00';
    var wake = byId('sleep-wake').value || profile.sleep_wake || '07:00';

    var windowData = plan && plan.sleep_window ? plan.sleep_window : null;
    var start;
    var end;
    if (windowData && windowData.eating_window) {
      start = windowData.eating_window.start;
      end = windowData.eating_window.end;
    } else {
      start = minToHm(hmToMin(wake) + 30);
      end = minToHm(hmToMin(bed) - 120);
    }
    byId('sleep-sync-window').textContent = 'Окно питания: ' + start + ' – ' + end;

    var meals = (state.sleep.meals && state.sleep.meals.meals) || [];
    var last = null;
    meals.forEach(function (meal) {
      if (!last || hmToMin(meal.time) > hmToMin(last.time)) { last = meal; }
    });
    var lastNode = byId('sleep-sync-last');
    var ruleNode = byId('sleep-sync-rule');

    if (!last) {
      lastNode.textContent = 'Последний приём: сегодня пока не записан';
      ruleNode.className = 'sync-line';
      ruleNode.textContent = 'Правило: последний приём — минимум за 2 ч до сна.';
      return;
    }
    lastNode.textContent = 'Последний приём: ' + String(last.time || '').slice(0, 5) + ' · ' + (last.title || '');
    var bedMinutes = hmToMin(bed);
    if (bedMinutes < 12 * 60) { bedMinutes += 1440; } // отбой после полуночи
    var diff = bedMinutes - hmToMin(last.time);
    if (diff >= 120) {
      ruleNode.className = 'sync-line sync-line--ok';
      ruleNode.textContent = '✓ До сна ' + fmtDuration(diff) + ' — правило 2 ч соблюдено.';
    } else {
      ruleNode.className = 'sync-line sync-line--warn';
      ruleNode.textContent = '⚠ До сна ' + fmtDuration(Math.max(0, diff)) + ' — ужин лучше закончить до ' + end + '.';
    }
  }

  function renderSleepWeek(week, avgH, debtH) {
    var container = byId('sleep-week-chart');
    var empty = byId('sleep-week-empty');
    var avgNode = byId('sleep-avg');
    var debtNode = byId('sleep-debt');
    var items = (week || []).slice(-7);

    avgNode.textContent = avgH != null ? 'средний ' + fmtHours(avgH) + ' ч' : 'средний —';
    if (debtH != null && num(debtH) > 0.05) {
      debtNode.textContent = 'долг ' + fmtHours(debtH) + ' ч';
    } else {
      debtNode.textContent = debtH != null ? 'без долга' : '';
    }

    if (!items.length) {
      container.innerHTML = '';
      empty.hidden = false;
      return;
    }
    empty.hidden = true;

    var maxHours = 9;
    items.forEach(function (item) {
      maxHours = Math.max(maxHours, sleepHours(item));
    });

    var width = 340;
    var height = 168;
    var base = 138;
    var top = 22;
    var gap = 6;
    var barWidth = (width - gap * (items.length - 1)) / items.length;
    var parts = ['<svg class="chart__svg" viewBox="0 0 340 168" role="img" aria-label="Сон за последние 7 дней">'];
    var y8 = base - (8 / maxHours) * (base - top);
    parts.push('<line class="chart__goal" x1="0" y1="' + y8.toFixed(1) + '" x2="340" y2="' + y8.toFixed(1) + '"></line>');
    parts.push('<g class="chart__bars chart__bars--sleep">');

    items.forEach(function (item, index) {
      var hours = sleepHours(item);
      var hasData = hours > 0;
      var barHeight = hasData ? Math.max(3, (hours / maxHours) * (base - top)) : 3;
      var x = index * (barWidth + gap);
      var y = base - barHeight;
      var label = item.date ? dateNumeric(item.date) : String(index + 1);
      var title = (item.date ? dateShort(item.date) : '') + ' · ' + fmtHours(hours) + ' ч';
      parts.push('<rect x="' + x.toFixed(1) + '" y="' + y.toFixed(1) + '" width="' + barWidth.toFixed(1) +
        '" height="' + barHeight.toFixed(1) + '" rx="4"' + (hasData ? '' : ' class="is-empty"') + '>' +
        '<title>' + esc(title) + '</title></rect>');
      if (hasData) {
        parts.push('<text class="chart__label" x="' + (x + barWidth / 2).toFixed(1) + '" y="' + (y - 5).toFixed(1) +
          '" text-anchor="middle">' + esc(fmtHours(hours)) + '</text>');
      }
      var weekday = item.date ? WEEKDAYS_SHORT[mondayIndex(parseIso(item.date))] : label;
      parts.push('<text class="chart__label" x="' + (x + barWidth / 2).toFixed(1) + '" y="158" text-anchor="middle">' +
        esc(weekday) + '</text>');
    });

    parts.push('</g></svg>');
    container.innerHTML = parts.join('');
  }

  /* ======================= экран «Расписание» ======================= */

  function loadSchedule(options) {
    var opts = options || {};
    if (state.schedule.loading) { return; }
    var monday = mondayOf(new Date());
    state.schedule.weekStart = isoDate(monday);
    state.schedule.weekEnd = isoDate(addDays(monday, 6));
    if (state.schedule.selected === null || state.schedule.selected === undefined) {
      state.schedule.selected = mondayIndex(new Date()); // по умолчанию — сегодня
    }
    state.schedule.selected = clamp(state.schedule.selected, 0, 6);
    if (!state.schedule.data && !opts.silent) { setScreenLoading('schedule', true); }
    state.schedule.loading = true;
    var from = state.schedule.weekStart;
    var to = state.schedule.weekEnd;
    Promise.all([
      apiRequest('GET', '/api/classes'),
      apiRequest('GET', '/api/schedule?from=' + encodeURIComponent(from) + '&to=' + encodeURIComponent(to))
    ]).then(function (results) {
      state.schedule.loading = false;
      var classesData = results[0] || {};
      state.schedule.classes = classesData.classes || [];
      state.schedule.weekLoad = classesData.week_load_min || 0;
      state.schedule.data = results[1] || { occurrences: [], summary: {} };
      setScreenLoading('schedule', false);
      renderSchedule();
    }).catch(function (error) {
      state.schedule.loading = false;
      setScreenLoading('schedule', false);
      toast(errorText(error.code), 'error');
    });
  }

  /* ---------- сегменты «День | Неделя» и таймлайн дня ---------- */

  function setScheduleSegment(segment) {
    var value = segment === 'week' ? 'week' : 'day';
    state.schedule.segment = value;
    var dayPanel = byId('schedule-day-panel');
    var weekPanel = byId('schedule-week-panel');
    if (dayPanel) { dayPanel.hidden = value !== 'day'; }
    if (weekPanel) { weekPanel.hidden = value !== 'week'; }
    qsa('#schedule-segments [data-segment]').forEach(function (button) {
      var active = button.getAttribute('data-segment') === value;
      button.classList.toggle('is-active', active);
      button.setAttribute('aria-selected', active ? 'true' : 'false');
    });
    var addButton = byId('btn-add-class');
    if (addButton) {
      addButton.setAttribute('aria-label', value === 'day' ? 'Добавить блок дня' : 'Добавить занятие');
    }
    if (value === 'day') {
      loadDay();
    } else {
      loadSchedule();
    }
  }

  function loadDay(options) {
    var opts = options || {};
    if (state.schedule.dayLoading) { return; }
    var date = todayIso();
    state.schedule.dayDate = date;
    state.schedule.dayLoading = true;
    apiRequest('GET', '/api/day?date=' + encodeURIComponent(date)).then(function (data) {
      state.schedule.dayLoading = false;
      state.schedule.day = data || { date: date, items: [], suggestions: [], summary: {} };
      renderDayPlan();
    }).catch(function (error) {
      state.schedule.dayLoading = false;
      state.schedule.day = state.schedule.day || { date: date, items: [], suggestions: [], summary: {} };
      renderDayPlan();
      if (!opts.silent && error.code !== 'http_404') {
        toast(errorText(error.code), 'error');
      }
    });
  }

  function renderDayPlan() {
    setScreenLoading('schedule', false);
    var day = state.schedule.day || { date: todayIso(), items: [], suggestions: [], summary: {} };
    var label = byId('day-plan-label');
    if (label) { label.textContent = dayLabel(day.date || todayIso()); }
    var summary = byId('day-plan-summary');
    if (summary) { summary.textContent = daySummaryText(day); }

    var list = byId('day-timeline');
    var empty = byId('day-timeline-empty');
    if (!list || !empty) { return; }
    var items = sortedDayItems(day);
    if (!items.length) {
      list.innerHTML = '';
      empty.hidden = false;
    } else {
      empty.hidden = true;
      list.innerHTML = items.map(function (item) {
        return dayRowHtml(item, { editable: true });
      }).join('');
    }
    renderDaySuggestions(day);
  }

  function renderDaySuggestions(day) {
    var box = byId('day-suggestions');
    var empty = byId('day-suggestions-empty');
    if (!box || !empty) { return; }
    var existing = {};
    sortedDayItems(day).forEach(function (item) {
      existing[hmToMin(item.time) + '|' + String(item.title || '').trim().toLowerCase()] = true;
    });
    var suggestions = ((day && day.suggestions) || []).filter(function (item) {
      var key = hmToMin(item.time) + '|' + String(item.title || '').trim().toLowerCase();
      return !existing[key];
    });
    state.schedule.daySuggestions = suggestions;
    if (!suggestions.length) {
      box.innerHTML = '';
      empty.hidden = false;
      return;
    }
    empty.hidden = true;
    box.innerHTML = suggestions.map(function (item, index) {
      var kind = DAY_KIND_LABELS[item.kind] ? item.kind : 'other';
      var meta = '<span class="day-kind day-kind--' + kind + '">' + esc(DAY_KIND_LABELS[kind]) + '</span>' +
        '<span>' + esc(fmtDuration(item.duration_min || 0)) + '</span>' +
        (item.note ? '<span>' + esc(item.note) + '</span>' : '');
      return '<li class="suggest-row">' +
        '<span class="suggest-row__time">' + esc(String(item.time || '').slice(0, 5)) + '</span>' +
        '<div class="suggest-row__main">' +
          '<p class="suggest-row__title">' + esc(item.title || 'Блок') + '</p>' +
          '<p class="suggest-row__meta">' + meta + '</p>' +
        '</div>' +
        '<button type="button" class="suggest-row__add" data-suggest-add="' + index + '" ' +
          'aria-label="Добавить блок ' + esc(item.title || '') + '">+</button>' +
      '</li>';
    }).join('');
  }

  function addDaySuggestion(index) {
    var item = (state.schedule.daySuggestions || [])[index];
    if (!item) { return; }
    var payload = {
      date: state.schedule.dayDate || todayIso(),
      time: item.time || '12:00',
      title: item.title || 'Блок дня',
      kind: DAY_KIND_LABELS[item.kind] ? item.kind : 'other',
      duration_min: int(item.duration_min, 30),
      note: item.note || ''
    };
    haptic('select');
    apiRequest('POST', '/api/day', payload).then(function () {
      haptic('success');
      toast('Добавлено: ' + payload.title);
      state.schedule.day = null;
      loadDay({ silent: true });
      loadBootstrap();
    }).catch(function (error) {
      haptic('error');
      toast(errorText(error.code), 'error');
    });
  }

  function toggleDayDone(itemId, wantDone) {
    haptic('select');
    apiRequest('POST', '/api/day/' + encodeURIComponent(itemId) + '/done', { done: !!wantDone }).then(function (data) {
      haptic('success');
      applyDayItemUpdate((data && data.item) || { id: itemId, done: wantDone ? 1 : 0 });
      loadBootstrap();
    }).catch(function (error) {
      haptic('error');
      toast(errorText(error.code), 'error');
    });
  }

  function applyDayItemUpdate(patch) {
    if (!patch || patch.id == null) { return; }
    var lists = [];
    if (state.bootstrap && state.bootstrap.day) { lists.push(state.bootstrap.day); }
    if (state.schedule.day) { lists.push(state.schedule.day); }
    lists.forEach(function (day) {
      (day.items || []).forEach(function (item) {
        if (String(item.id) === String(patch.id)) {
          Object.keys(patch).forEach(function (key) { item[key] = patch[key]; });
        }
      });
    });
    renderTodayDay(state.bootstrap && state.bootstrap.day);
    if (state.schedule.day) { renderDayPlan(); }
  }

  function openDayItemForm(item) {
    var form = byId('day-item-form');
    if (!form) { return; }
    var edit = !!item;
    form.hidden = false;
    byId('day-item-heading').textContent = edit ? 'Редактировать блок' : 'Новый блок дня';
    byId('day-item-id').value = edit ? String(item.id) : '';
    byId('day-item-title').value = edit ? (item.title || '') : '';
    byId('day-item-time').value = edit ? String(item.time || '12:00').slice(0, 5) : nowHm();
    byId('day-item-kind').value = edit && DAY_KIND_LABELS[item.kind] ? item.kind : 'other';
    byId('day-item-duration').value = edit ? int(item.duration_min, 30) : 30;
    byId('day-item-note').value = edit ? (item.note || '') : '';
    byId('day-item-delete').hidden = !edit;
    try { form.scrollIntoView({ behavior: 'smooth', block: 'center' }); } catch (error) { /* noop */ }
    window.setTimeout(function () { byId('day-item-title').focus(); }, 60);
  }

  function closeDayItemForm() {
    var form = byId('day-item-form');
    if (form) { form.hidden = true; }
  }

  function editDayItem(itemId) {
    var found = null;
    ((state.schedule.day && state.schedule.day.items) || []).forEach(function (item) {
      if (String(item.id) === String(itemId)) { found = item; }
    });
    if (found) { openDayItemForm(found); }
  }

  function submitDayItem(event) {
    event.preventDefault();
    var title = byId('day-item-title').value.trim();
    if (!title) {
      toast('Добавь название блока', 'error');
      byId('day-item-title').focus();
      return;
    }
    var duration = int(byId('day-item-duration').value);
    if (duration < 5 || duration > 720) {
      toast('Длительность — от 5 до 720 минут', 'error');
      byId('day-item-duration').focus();
      return;
    }
    var payload = {
      date: state.schedule.dayDate || todayIso(),
      time: byId('day-item-time').value || '12:00',
      title: title,
      kind: byId('day-item-kind').value,
      duration_min: duration,
      note: byId('day-item-note').value.trim()
    };
    var itemId = byId('day-item-id').value;
    var button = byId('day-item-submit');
    setBusy(button, true);
    var request = itemId
      ? apiRequest('PUT', '/api/day/' + encodeURIComponent(itemId), payload)
      : apiRequest('POST', '/api/day', payload);
    request.then(function () {
      setBusy(button, false);
      haptic('success');
      toast(itemId ? 'Блок обновлён' : 'Блок добавлен');
      closeDayItemForm();
      state.schedule.day = null;
      loadDay({ silent: true });
      loadBootstrap();
    }).catch(function (error) {
      setBusy(button, false);
      haptic('error');
      toast(errorText(error.code), 'error');
    });
  }

  function deleteDayItem() {
    var itemId = byId('day-item-id').value;
    if (!itemId) { return; }
    askConfirm('Удалить блок дня?', function () {
      apiRequest('DELETE', '/api/day/' + encodeURIComponent(itemId)).then(function () {
        haptic('warning');
        toast('Блок удалён');
        closeDayItemForm();
        state.schedule.day = null;
        loadDay({ silent: true });
        loadBootstrap();
      }).catch(function (error) {
        haptic('error');
        toast(errorText(error.code), 'error');
      });
    });
  }

  function occurrencesByDate() {
    var map = {};
    var occurrences = (state.schedule.data && state.schedule.data.occurrences) || [];
    occurrences.forEach(function (item) {
      var key = String(item.date || '').slice(0, 10);
      if (!map[key]) { map[key] = []; }
      map[key].push(item);
    });
    Object.keys(map).forEach(function (key) {
      map[key].sort(function (a, b) { return hmToMin(a.start_time) - hmToMin(b.start_time); });
    });
    return map;
  }

  function renderSchedule() {
    setScreenLoading('schedule', false);
    var monday = parseIso(state.schedule.weekStart || todayIso());
    var byDate = occurrencesByDate();
    var today = todayIso();
    var html = '';

    for (var index = 0; index < 7; index += 1) {
      var date = isoDate(addDays(monday, index));
      var items = byDate[date] || [];
      var classes = ['week-col'];
      if (date === today) { classes.push('is-today'); }
      if (index === state.schedule.selected) { classes.push('is-selected'); }
      html += '<div class="' + classes.join(' ') + '">';
      html += '<button type="button" class="week-col__head" data-day="' + index + '" aria-label="' +
        esc(WEEKDAYS_FULL[index] + ', ' + dateShort(date)) + '">';
      html += '<span class="week-col__day">' + WEEKDAYS_SHORT[index] + '</span>';
      html += '<span class="week-col__date">' + parseIso(date).getDate() + '</span>';
      html += '</button>';
      html += '<div class="week-col__chips">';
      items.forEach(function (item) {
        html += '<button type="button" class="week-chip week-chip--' + esc(item.kind || 'other') +
          '" data-class-id="' + esc(item.class_id) + '" data-date="' + esc(date) + '" ' +
          'title="' + esc(String(item.start_time || '').slice(0, 5) + ' · ' + (item.title || '')) + '" ' +
          'aria-label="' + esc((item.title || 'Занятие') + ', ' + String(item.start_time || '')) + '">' +
          esc(String(item.start_time || '').slice(0, 5)) +
          '</button>';
      });
      html += '</div></div>';
    }
    byId('schedule-grid').innerHTML = html;

    byId('week-load').textContent = fmtDuration(state.schedule.weekLoad);
    var summary = (state.schedule.data && state.schedule.data.summary) || {};
    byId('week-done').textContent = int(summary.done) + ' из ' + int(summary.total);
    byId('week-missed').textContent = fmtInt(int(summary.missed));
    renderKindStats(summary.by_kind || {});
    renderDayList();
    byId('schedule-week-label').textContent = 'Расписание';
  }

  function renderKindStats(byKind) {
    var list = byId('week-by-kind');
    var keys = ['gym', 'study', 'other'];
    var rows = [];
    keys.forEach(function (key) {
      var bucket = byKind[key];
      if (!bucket) { return; }
      var total = int(bucket.total);
      var done = int(bucket.done);
      var minutes = int(bucket.minutes);
      rows.push(
        '<li>' +
          '<span class="kind-dot kind-dot--' + key + '"></span>' +
          '<b>' + esc(KIND_LABELS[key]) + '</b>' +
          '<span>' + fmtDuration(minutes) + ' · посещено ' + done + ' из ' + total + '</span>' +
        '</li>'
      );
    });
    list.innerHTML = rows.join('');
    if (!rows.length) {
      list.innerHTML = '<li>Пока нет занятий на неделе.</li>';
    }
  }

  function renderDayList() {
    var monday = parseIso(state.schedule.weekStart || todayIso());
    var date = isoDate(addDays(monday, state.schedule.selected));
    var today = todayIso();
    var byDate = occurrencesByDate();
    var items = byDate[date] || [];
    byId('day-label').textContent = dayLabel(date);

    var list = byId('day-classes');
    var empty = byId('day-empty');
    if (!items.length) {
      list.innerHTML = '';
      empty.hidden = false;
      return;
    }
    empty.hidden = true;

    list.innerHTML = items.map(function (item) {
      var status = item.status || '';
      var isToday = date === today;
      var actions = '<button type="button" class="mini-btn mini-btn--edit" data-edit-class="' +
        esc(item.class_id) + '" aria-label="Изменить занятие ' + esc(item.title || '') + '">Изменить</button>';
      if (isToday) {
        actions += '<button type="button" class="mini-btn' + (status === 'present' ? ' is-active' : '') +
          '" data-status="present" data-class-id="' + esc(item.class_id) + '" data-date="' + esc(date) +
          '" aria-pressed="' + (status === 'present' ? 'true' : 'false') + '">Пришёл</button>';
        actions += '<button type="button" class="mini-btn' + (status === 'absent' ? ' is-active' : '') +
          '" data-status="absent" data-class-id="' + esc(item.class_id) + '" data-date="' + esc(date) +
          '" aria-pressed="' + (status === 'absent' ? 'true' : 'false') + '">Пропустил</button>';
      }
      var statusText = '';
      if (status === 'present') { statusText = 'Посещено'; }
      if (status === 'absent') { statusText = 'Пропущено'; }
      if (status === 'moved') { statusText = 'Перенесено'; }

      var meta = int(item.duration_min, 60) + ' мин';
      if (item.place) { meta += ' · ' + item.place; }
      if (item.note) { meta += ' · ' + item.note; }

      return '<li class="class-item">' +
        '<div class="class-item__head">' +
          '<span class="class-item__time">' + esc(String(item.start_time || '').slice(0, 5)) + '</span>' +
          '<span class="class-item__title">' + esc(item.title || 'Занятие') + '</span>' +
          '<span class="class-item__badge badge--' + esc(item.kind || 'other') + '">' +
            esc(KIND_LABELS[item.kind] || 'Другое') + '</span>' +
        '</div>' +
        '<p class="class-item__meta">' + esc(meta) + '</p>' +
        '<div class="class-item__actions">' +
          (statusText ? '<span class="class-item__status class-item__status--' + esc(status) + '">' +
            esc(statusText) + '</span>' : '') +
          actions +
        '</div>' +
      '</li>';
    }).join('');
  }

  function selectDay(index) {
    state.schedule.selected = clamp(int(index), 0, 6);
    renderSchedule();
  }

  function openClassForm(classData) {
    var form = byId('class-form');
    form.hidden = false;
    var edit = !!classData;
    byId('class-form-heading').textContent = edit ? 'Редактировать занятие' : 'Новое занятие';
    byId('class-id').value = edit ? String(classData.id) : '';
    byId('class-title').value = edit ? (classData.title || '') : '';
    byId('class-kind').value = edit && KIND_LABELS[classData.kind] ? classData.kind : 'gym';
    byId('class-weekday').value = String(edit ? int(classData.weekday) : state.schedule.selected);
    byId('class-start').value = edit ? String(classData.start_time || '18:00').slice(0, 5) : '18:00';
    byId('class-duration').value = edit ? int(classData.duration_min, 60) : 60;
    byId('class-place').value = edit ? (classData.place || '') : '';
    byId('class-note').value = edit ? (classData.note || '') : '';
    byId('class-delete').hidden = !edit;
    try { form.scrollIntoView({ behavior: 'smooth', block: 'center' }); } catch (error) { /* noop */ }
    window.setTimeout(function () { byId('class-title').focus(); }, 60);
  }

  function closeClassForm() {
    byId('class-form').hidden = true;
  }

  function submitClass(event) {
    event.preventDefault();
    var title = byId('class-title').value.trim();
    if (!title) {
      toast('Добавь название занятия', 'error');
      byId('class-title').focus();
      return;
    }
    var duration = int(byId('class-duration').value);
    if (duration < 15 || duration > 480) {
      toast('Длительность — от 15 до 480 минут', 'error');
      byId('class-duration').focus();
      return;
    }
    var payload = {
      title: title,
      kind: byId('class-kind').value,
      weekday: int(byId('class-weekday').value),
      start_time: byId('class-start').value || '18:00',
      duration_min: duration,
      place: byId('class-place').value.trim(),
      note: byId('class-note').value.trim()
    };
    var classId = byId('class-id').value;
    var button = byId('class-submit');
    setBusy(button, true);
    var request = classId
      ? apiRequest('PUT', '/api/classes/' + encodeURIComponent(classId), payload)
      : apiRequest('POST', '/api/classes', payload);
    request.then(function () {
      setBusy(button, false);
      haptic('success');
      toast(classId ? 'Занятие обновлено' : 'Занятие добавлено');
      closeClassForm();
      state.schedule.selected = payload.weekday;
      state.schedule.data = null;
      loadSchedule({ silent: true });
      loadBootstrap();
    }).catch(function (error) {
      setBusy(button, false);
      haptic('error');
      toast(errorText(error.code), 'error');
    });
  }

  function deleteClass() {
    var classId = byId('class-id').value;
    if (!classId) { return; }
    askConfirm('Удалить занятие из расписания?', function () {
      apiRequest('DELETE', '/api/classes/' + encodeURIComponent(classId)).then(function () {
        haptic('warning');
        toast('Занятие удалено');
        closeClassForm();
        state.schedule.data = null;
        loadSchedule({ silent: true });
        loadBootstrap();
      }).catch(function (error) {
        haptic('error');
        toast(errorText(error.code), 'error');
      });
    });
  }

  function editClass(classId) {
    var found = null;
    state.schedule.classes.forEach(function (item) {
      if (int(item.id) === int(classId)) { found = item; }
    });
    if (found) { openClassForm(found); }
  }

  function markDone(classId, date, status) {
    apiRequest('POST', '/api/classes/' + encodeURIComponent(classId) + '/done', {
      date: date,
      status: status,
      note: ''
    }).then(function () {
      haptic('success');
      toast(status === 'present' ? 'Отмечено: пришёл' : 'Отмечено: пропустил');
      state.schedule.data = null;
      loadSchedule({ silent: true });
      loadBootstrap();
    }).catch(function (error) {
      haptic('error');
      toast(errorText(error.code), 'error');
    });
  }

  /* ======================= экран «Прогресс» ======================= */

  function loadProgress(options) {
    var opts = options || {};
    if (state.progress.loading) { return; }
    if (!state.progress.stats && !opts.silent) { setScreenLoading('progress', true); }
    state.progress.loading = true;
    Promise.all([
      apiRequest('GET', '/api/weights?days=60'),
      apiRequest('GET', '/api/stats?days=14')
    ]).then(function (results) {
      state.progress.loading = false;
      state.progress.weights = results[0] || { weights: [] };
      state.progress.stats = results[1] || { days: [], avg: {} };
      setScreenLoading('progress', false);
      renderWeights();
      renderStats();
      renderProfileForm();
      renderPalette();
      loadTheme();
      if (!byId('weight-date').value) { byId('weight-date').value = todayIso(); }
    }).catch(function (error) {
      state.progress.loading = false;
      setScreenLoading('progress', false);
      toast(errorText(error.code), 'error');
    });
  }

  function renderWeights() {
    var data = state.progress.weights || { weights: [] };
    var points = (data.weights || []).slice().sort(function (a, b) {
      return String(a.date) < String(b.date) ? -1 : 1;
    });
    var empty = byId('weight-empty');
    var wrap = byId('weight-chart-wrap');
    var trendNode = byId('weight-trend');
    var current = points.length ? points[points.length - 1] : null;

    byId('weight-current').textContent = current ? fmtNumber(current.kg, 1) + ' кг' : '—';
    if (data.trend_kg_per_week == null) {
      trendNode.textContent = '—';
    } else {
      var trend = num(data.trend_kg_per_week);
      trendNode.textContent = (trend > 0 ? '+' : '') + fmtNumber(trend, 2) + ' кг/нед';
    }

    if (!points.length) {
      wrap.hidden = true;
      empty.hidden = false;
      return;
    }
    wrap.hidden = false;
    empty.hidden = true;

    var width = 340;
    var top = 14;
    var bottom = 124;
    var left = 8;
    var right = 332;
    var values = points.map(function (point) { return num(point.kg); });
    var min = Math.min.apply(null, values);
    var max = Math.max.apply(null, values);
    var span = max - min;
    if (span < 0.8) {
      min -= 0.4;
      max += 0.4;
    } else {
      min -= span * 0.15;
      max += span * 0.15;
    }
    span = max - min;

    function xFor(index) {
      if (points.length === 1) { return (left + right) / 2; }
      return left + index * (right - left) / (points.length - 1);
    }

    function yFor(kg) {
      return bottom - ((kg - min) / span) * (bottom - top);
    }

    var polyline = points.map(function (point, index) {
      return xFor(index).toFixed(1) + ',' + yFor(num(point.kg)).toFixed(1);
    }).join(' ');

    var line = byId('weight-line');
    if (line) { line.setAttribute('points', polyline); }

    var grid = byId('weight-grid');
    var gridParts = [];
    for (var g = 1; g <= 3; g += 1) {
      var gridY = top + (bottom - top) * g / 4;
      gridParts.push('<line x1="0" y1="' + gridY.toFixed(1) + '" x2="340" y2="' + gridY.toFixed(1) + '"></line>');
    }
    gridParts.push('<text class="chart__label" x="2" y="' + (top - 3) + '">' + esc(fmtNumber(max, 1)) + ' кг</text>');
    gridParts.push('<text class="chart__label" x="2" y="' + (bottom + 14) + '">' + esc(fmtNumber(min, 1)) + ' кг</text>');
    gridParts.push('<text class="chart__label" x="2" y="' + (bottom + 28) + '">' + esc(dateNumeric(points[0].date)) + '</text>');
    if (points.length > 1) {
      gridParts.push('<text class="chart__label" x="338" y="' + (bottom + 28) +
        '" text-anchor="end">' + esc(dateNumeric(points[points.length - 1].date)) + '</text>');
    }
    if (grid) { grid.innerHTML = gridParts.join(''); }

    var dots = byId('weight-dots');
    if (dots) {
      dots.innerHTML = points.map(function (point, index) {
        var last = index === points.length - 1;
        return '<circle cx="' + xFor(index).toFixed(1) + '" cy="' + yFor(num(point.kg)).toFixed(1) +
          '" r="' + (last ? 4 : 2.8) + '"' + (last ? ' class="is-last"' : '') + '>' +
          '<title>' + esc(dateShort(point.date) + ' · ' + fmtNumber(point.kg, 1) + ' кг') + '</title></circle>';
      }).join('');
    }
  }

  function buildBarsSvg(items, options) {
    var opts = options || {};
    var width = 340;
    var height = 158;
    var base = 126;
    var top = 14;
    var gap = 3;
    var count = items.length;
    var barWidth = (width - gap * (count - 1)) / count;
    var maxValue = Math.max(opts.maxValue || 1, 1);
    var parts = ['<svg class="chart__svg" viewBox="0 0 340 158" preserveAspectRatio="none" role="img" aria-label="' +
      esc(opts.ariaLabel || 'График') + '">'];

    if (opts.goal > 0 && opts.goal <= maxValue) {
      var goalY = base - (opts.goal / maxValue) * (base - top);
      parts.push('<line class="chart__goal" x1="0" y1="' + goalY.toFixed(1) +
        '" x2="340" y2="' + goalY.toFixed(1) + '"></line>');
    }

    parts.push('<g class="chart__bars ' + (opts.barClass || '') + '">');
    items.forEach(function (item, index) {
      var value = num(item.value);
      var ratio = maxValue > 0 ? clamp(value / maxValue, 0, 1) : 0;
      var barHeight = item.hasData ? Math.max(2, ratio * (base - top)) : 2;
      var x = index * (barWidth + gap);
      var y = base - barHeight;
      var className = '';
      if (!item.hasData) {
        className = ' class="is-empty"';
      } else if (opts.overValue > 0 && value > opts.overValue) {
        className = ' class="is-over"';
      }
      parts.push('<rect x="' + x.toFixed(1) + '" y="' + y.toFixed(1) + '" width="' + barWidth.toFixed(1) +
        '" height="' + barHeight.toFixed(1) + '" rx="3"' + className +
        '><title>' + esc(item.title || '') + '</title></rect>');
    });
    parts.push('</g>');

    if (count) {
      var labelIndexes = [0];
      if (count > 2) { labelIndexes.push(Math.floor((count - 1) / 2)); }
      if (count > 1) { labelIndexes.push(count - 1); }
      labelIndexes.forEach(function (index) {
        var item = items[index];
        var center = index * (barWidth + gap) + barWidth / 2;
        var anchor = 'middle';
        if (index === 0) { anchor = 'start'; }
        if (index === count - 1 && count > 1) { anchor = 'end'; }
        parts.push('<text class="chart__label" x="' + center.toFixed(1) + '" y="150" text-anchor="' +
          anchor + '">' + esc(item.label || '') + '</text>');
      });
    }
    parts.push('</svg>');
    return parts.join('');
  }

  function renderCalBars(days, goal) {
    var container = byId('cal-bars');
    var items = days.map(function (day) {
      var value = num(day.kcal);
      return {
        value: value,
        hasData: value > 0,
        label: String(parseIso(day.date).getDate()),
        title: dateShort(day.date) + ' · ' + fmtInt(value) + ' ккал'
      };
    });
    var maxValue = Math.max(goal || 0, 1);
    items.forEach(function (item) { maxValue = Math.max(maxValue, item.value); });
    container.innerHTML = buildBarsSvg(items, {
      maxValue: maxValue,
      goal: goal,
      overValue: goal > 0 ? goal * 1.15 : 0,
      ariaLabel: 'Калории за последние 14 дней'
    });
  }

  function renderSleepBars(days) {
    var container = byId('sleep-bars');
    var items = days.map(function (day) {
      var value = sleepHours(day);
      return {
        value: value,
        hasData: value > 0,
        label: String(parseIso(day.date).getDate()),
        title: dateShort(day.date) + ' · ' + fmtHours(value) + ' ч'
      };
    });
    var maxValue = 9;
    items.forEach(function (item) { maxValue = Math.max(maxValue, item.value); });
    container.innerHTML = buildBarsSvg(items, {
      maxValue: maxValue,
      goal: 8,
      ariaLabel: 'Сон за последние 14 дней',
      barClass: 'chart__bars--sleep'
    });
  }

  function renderStats() {
    var data = state.progress.stats || {};
    var days = (data.days || []).slice(-14);
    var avg = data.avg || {};
    var targets = currentTargets() || {};
    var goalKcal = num(avg.goal_kcal) || num(targets.kcal);

    byId('stats-avg-kcal').textContent = avg.kcal != null ? fmtInt(avg.kcal) : '—';
    byId('stats-avg-protein').textContent = avg.protein != null ? fmtNumber(avg.protein, 0) : '—';
    byId('stats-avg-sleep').textContent = avg.sleep_h != null ? fmtHours(avg.sleep_h) + ' ч' : '—';
    byId('stats-days-count').textContent = days.length
      ? days.length + ' ' + plural(days.length, 'день', 'дня', 'дней') + ' с данными'
      : '';
    byId('cal-goal-line-label').textContent = goalKcal > 0 ? fmtInt(goalKcal) + ' ккал' : '—';

    renderCalBars(days, goalKcal);
    renderSleepBars(days);

    var warmDays = days.filter(function (day) {
      return num(day.kcal) > 0;
    });
    var inGoal = warmDays.filter(function (day) {
      return goalKcal > 0 && num(day.kcal) >= goalKcal * 0.85 && num(day.kcal) <= goalKcal * 1.15;
    }).length;
    byId('stats-adherence').textContent = warmDays.length
      ? inGoal + ' из ' + warmDays.length
      : '—';

    var kcalPct = goalKcal > 0 && avg.kcal != null
      ? Math.round(num(avg.kcal) / goalKcal * 100)
      : 0;
    byId('stats-kcal-pct').textContent = kcalPct > 0 ? kcalPct + '%' : '—';
    var kcalBar = byId('bar-kcal-adherence');
    kcalBar.style.width = clamp(kcalPct, 0, 100) + '%';
    kcalBar.classList.toggle('is-over', kcalPct > 115);

    var sleepDays = days.filter(function (day) { return num(day.sleep_h) > 0; });
    var sleepSum = 0;
    sleepDays.forEach(function (day) { sleepSum += num(day.sleep_h); });
    var sleepPct = sleepDays.length ? Math.round((sleepSum / sleepDays.length) / 8 * 100) : 0;
    byId('stats-sleep-pct').textContent = sleepPct > 0 ? sleepPct + '%' : '—';
    byId('bar-sleep-adherence').style.width = clamp(sleepPct, 0, 100) + '%';
  }

  function renderProfileSummary() {
    var profile = currentProfile();
    if (!profile) { return; }
    var targets = currentTargets() || {};
    var sex = profile.sex === 'female' ? 'Женщина' : 'Мужчина';
    var age = int(profile.age);
    var activity = ACTIVITY_LABELS[profile.activity] || profile.activity || '';

    var summary = sex + ' · ' + age + ' ' + plural(age, 'год', 'года', 'лет') +
      ' · ' + fmtNumber(profile.height_cm, 0) + ' см' +
      ' · ' + fmtNumber(profile.weight_kg, 1) + ' кг';
    if (activity) { summary += '\n' + activity; }
    summary += '\nТемп набора: ' + fmtNumber(profile.goal_rate, 2) + ' кг/нед' +
      ' · сон ' + (profile.sleep_bed || '—') + '–' + (profile.sleep_wake || '—');
    if (targets.kcal) {
      summary += '\nЦели: ' + fmtInt(targets.kcal) + ' ккал · Б ' + fmtInt(targets.protein) +
        ' / Ж ' + fmtInt(targets.fat) + ' / У ' + fmtInt(targets.carbs) +
        ' г · вода ' + fmtInt(targets.water_ml) + ' мл';
    }
    byId('prof-summary').textContent = summary;
  }

  function renderProfileForm() {
    var profile = currentProfile();
    if (!profile) { return; }
    byId('prof-sex').value = profile.sex === 'female' ? 'female' : 'male';
    byId('prof-age').value = int(profile.age, 25);
    byId('prof-height').value = fmtNumber(profile.height_cm, 1).replace(',', '.');
    byId('prof-weight').value = fmtNumber(profile.weight_kg, 1).replace(',', '.');
    byId('prof-activity').value = ACTIVITY_LABELS[profile.activity] ? profile.activity : 'moderate';
    byId('prof-rate').value = num(profile.goal_rate, 0.35);
    byId('prof-goal-weight').value = profile.goal_weight_kg != null
      ? fmtNumber(profile.goal_weight_kg, 1).replace(',', '.')
      : '';
    byId('prof-goal-date').value = profile.goal_date ? String(profile.goal_date).slice(0, 10) : '';
    updateRateLabel('prof-rate', 'prof-rate-label');
    renderProfileSummary();
  }

  /* Светлый трек range: --range-fill задаёт accent-заливку в styles.css. */
  function syncRangeFill(input) {
    if (!input) { return; }
    var min = num(input.min, 0);
    var max = num(input.max, 100);
    var value = num(input.value, min);
    var percent = max > min ? ((value - min) / (max - min)) * 100 : 0;
    input.style.setProperty('--range-fill', clamp(percent, 0, 100).toFixed(2) + '%');
  }

  function syncRangeFills() {
    syncRangeFill(byId('onb-rate'));
    syncRangeFill(byId('prof-rate'));
  }

  function updateRateLabel(inputId, labelId) {
    var input = byId(inputId);
    if (!input || !byId(labelId)) { return; }
    var value = num(input.value, 0.35);
    byId(labelId).textContent = fmtNumber(value, 2) + ' кг/нед';
    syncRangeFill(input);
  }

  function submitWeight(event) {
    event.preventDefault();
    var kg = num(byId('weight-kg').value);
    if (kg < 25 || kg > 400) {
      toast('Вес — от 25 до 400 кг', 'error');
      byId('weight-kg').focus();
      return;
    }
    var date = byId('weight-date').value || todayIso();
    var button = byId('weight-submit');
    setBusy(button, true);
    apiRequest('POST', '/api/weights', { date: date, kg: kg, note: '' }).then(function () {
      setBusy(button, false);
      haptic('success');
      toast('Вес записан: ' + fmtNumber(kg, 1) + ' кг');
      byId('weight-kg').value = '';
      state.progress.weights = null;
      loadProgress({ silent: true });
      loadBootstrap({ force: true }); /* тренд веса меняет goal.status */
    }).catch(function (error) {
      setBusy(button, false);
      haptic('error');
      toast(errorText(error.code), 'error');
    });
  }

  function submitProfile(event) {
    event.preventDefault();
    var age = int(byId('prof-age').value);
    var height = num(byId('prof-height').value);
    var weight = num(byId('prof-weight').value);
    if (age < 10 || age > 100) {
      toast('Возраст — от 10 до 100 лет', 'error');
      return;
    }
    if (height < 100 || height > 250) {
      toast('Рост — от 100 до 250 см', 'error');
      return;
    }
    if (weight < 25 || weight > 400) {
      toast('Вес — от 25 до 400 кг', 'error');
      return;
    }
    var goalWeightRaw = byId('prof-goal-weight').value.trim();
    var goalWeight = goalWeightRaw ? num(goalWeightRaw) : null;
    if (goalWeight !== null && (goalWeight < 30 || goalWeight > 300)) {
      toast('Цель по весу — от 30 до 300 кг', 'error');
      byId('prof-goal-weight').focus();
      return;
    }
    var goalDate = byId('prof-goal-date').value || null;
    var payload = {
      sex: byId('prof-sex').value,
      age: age,
      height_cm: height,
      weight_kg: weight,
      activity: byId('prof-activity').value,
      goal_rate: num(byId('prof-rate').value, 0.35),
      goal_weight_kg: goalWeight,
      goal_date: goalDate
    };
    var button = byId('prof-submit');
    setBusy(button, true);
    apiRequest('PUT', '/api/profile', payload).then(function (data) {
      setBusy(button, false);
      haptic('success');
      var targets = (data && data.targets) || null;
      var profile = (data && data.profile) || (state.bootstrap && state.bootstrap.profile) || null;
      if (state.bootstrap) {
        state.bootstrap.profile = profile || state.bootstrap.profile;
        if (targets) { state.bootstrap.targets = targets; }
      }
      /* Цель могла измениться в профиле — карточка «Цель» обновляется сразу,
         bootstrap принесёт авторитетные pct/status (loadBootstrap force). */
      if (state.bootstrap) { applyGoalLocally(goalWeight, goalDate, profile); }
      renderProfileForm();
      renderToday();
      if (targets && targets.kcal) {
        toast('Сохранено. Цель: ' + fmtInt(targets.kcal) + ' ккал, белок ' + fmtInt(targets.protein) + ' г');
      } else {
        toast('Профиль сохранён');
      }
      loadBootstrap({ force: true });
    }).catch(function (error) {
      setBusy(button, false);
      haptic('error');
      toast(errorText(error.code), 'error');
    });
  }

  /* ======================= экран «ИИ»: ассистент (v8) ======================= */

  var AI_MESSAGE_MAX_LENGTH = 2000;
  var AI_EMPTY_TEXT = 'Задай любой вопрос — я помогу: учёба, тренировки, еда, код, что угодно.';

  function flagOn(value) {
    return value === true || value === 1 || value === '1' || value === 'true';
  }

  /* Доступ к чату: GET /api/ai/chat отдаёт ai_active; при 402 показываем paywall. */
  function aiChatActive(sub) {
    if (state.aiChat.forcePaywall) { return false; }
    if (state.aiChat.active === true || state.aiChat.active === false) {
      return state.aiChat.active;
    }
    return aiSubActive(sub);
  }

  function showAiPaywall() {
    state.aiChat.forcePaywall = true;
    state.aiChat.active = false;
    renderAiScreen();
    loadSubscription({ force: true });
  }

  function aiSubActive(sub) {
    return !!(sub && sub.ai_active === true);
  }

  function aiPriceLabel(sub) {
    var rub = sub ? sub.ai_price_rub : SUBSCRIPTION_DEFAULTS.ai_price_rub;
    return '+' + fmtInt(rub) + ' ₽/мес';
  }

  function aiStatusText(sub) {
    if (!sub) { return 'ИИ ' + aiPriceLabel(null); }
    if (sub.ai_active === true) {
      return sub.ai_until ? 'ИИ включён до ' + dateShort(sub.ai_until) : 'ИИ включён';
    }
    if (subscriptionIsTrial(sub)) {
      var until = sub.trial_until || sub.until;
      return until ? 'Пробный период до ' + dateShort(until) : 'Пробный период';
    }
    return 'ИИ ' + aiPriceLabel(sub);
  }

  /* Единый рендер экрана ИИ: статус подписки, paywall аддона, поле ввода
     и история чата с ассистентом. */
  function renderAiScreen() {
    var sub = subscriptionPayload();
    var active = aiChatActive(sub);

    var status = byId('ai-screen-status');
    if (status) {
      status.textContent = aiStatusText(sub);
      status.classList.toggle('is-active', active);
      status.classList.toggle('is-trial', !active && subscriptionIsTrial(sub));
    }

    /* Нет активного аддона — вместо поля ввода показываем paywall (CONTRACT §25). */
    var composer = byId('ai-composer');
    if (composer) { composer.hidden = !active; }

    var paywall = byId('ai-paywall');
    if (paywall) { paywall.hidden = active; }
    var price = byId('ai-paywall-price');
    if (price) { price.textContent = aiPriceLabel(sub); }
    var payText = byId('ai-paywall-text');
    if (payText) {
      if (!sub) {
        payText.textContent = 'Не удалось проверить подписку — обнови экран.';
      } else if (sub.active !== true) {
        payText.textContent = 'Сначала оформи подписку Vita Ratio — ' +
          fmtInt(sub.base_price_rub) + ' ₽/мес.';
      } else {
        payText.textContent = 'ИИ-ассистент отвечает на любые вопросы: учёба, тренировки, еда, код, что угодно.';
      }
    }
    var subscribeBtn = byId('ai-subscribe-btn');
    if (subscribeBtn) {
      subscribeBtn.textContent = 'Подключить ИИ · ' + aiPriceLabel(sub);
      setBusy(subscribeBtn, !!state.pay.aiBusy);
    }

    var send = byId('ai-send');
    if (send) { setBusy(send, !!state.aiChat.sending); }

    renderAiChat();
  }

  function aiMessageHtml(message) {
    var role = message && message.role === 'assistant' ? 'assistant' : 'user';
    var modifier = role === 'assistant' ? 'ai-msg--assistant' : 'ai-msg--user';
    var html = '<li class="ai-msg ' + modifier + '">';
    if (role === 'assistant') {
      html += '<span class="ai-msg__meta">🤖 ИИ</span>';
    }
    html += '<p class="ai-msg__text">' + esc((message && message.text) || '') + '</p></li>';
    return html;
  }

  function renderAiChat() {
    var list = byId('ai-chat-list');
    var empty = byId('ai-chat-empty');
    var typing = byId('ai-typing');
    if (!list || !empty) { return; }
    /* API отдаёт историю в хронологическом порядке: старые сверху, новые снизу. */
    var items = state.aiChat.items || [];
    var html = items.map(aiMessageHtml).join('');
    if (state.aiChat.pending) {
      html += '<li class="ai-msg ai-msg--user ai-msg--pending">' +
        '<p class="ai-msg__text">' + esc(state.aiChat.pending.text) + '</p>' +
      '</li>';
    }
    list.innerHTML = html;
    /* Индикатор «ИИ печатает…» (#ai-typing) виден, пока ждём POST /api/ai/chat. */
    if (typing) { typing.hidden = !state.aiChat.sending; }
    var hasMessages = items.length > 0 || !!state.aiChat.pending;
    empty.hidden = hasMessages;
    if (!hasMessages) {
      if (state.aiChat.loading) {
        empty.textContent = 'Загружаю историю…';
      } else if (state.aiChat.loaded) {
        empty.textContent = AI_EMPTY_TEXT;
      } else {
        empty.textContent = 'История не загрузилась — попробуй позже.';
      }
    }
  }

  function scrollAiToBottom() {
    window.setTimeout(function () {
      try {
        window.scrollTo(0, document.body.scrollHeight);
      } catch (error) { /* noop */ }
    }, 40);
  }

  /* История грузится отдельным запросом: медленный /api/ai/chat не блокирует
     остальные экраны, а ошибка остаётся тихой (без тоста). */
  function loadAiHistory() {
    if (state.aiChat.loading) {
      state.aiChat.reload = true;
      return;
    }
    state.aiChat.loading = true;
    renderAiChat();
    apiRequest('GET', '/api/ai/chat?limit=30').then(function (data) {
      state.aiChat.loading = false;
      state.aiChat.loaded = true;
      state.aiChat.items = ((data && data.messages) || []).filter(function (message) {
        return message && (message.role === 'user' || message.role === 'assistant') &&
          String(message.text || '').trim();
      }).slice(0, 30);
      if (data && typeof data.ai_active === 'boolean') {
        state.aiChat.active = data.ai_active;
        if (data.ai_active) { state.aiChat.forcePaywall = false; }
      }
      renderAiScreen();
      if (state.aiChat.reload) {
        state.aiChat.reload = false;
        loadAiHistory();
      }
    }).catch(function (error) {
      state.aiChat.loading = false;
      if (!state.aiChat.loaded) { state.aiChat.items = []; }
      var code = error && error.code;
      if (code === 'ai_subscription_required' || code === 'http_402') {
        state.aiChat.active = false;
        state.aiChat.forcePaywall = true;
      }
      renderAiScreen();
      if (state.aiChat.reload) {
        state.aiChat.reload = false;
        loadAiHistory();
      }
    });
  }

  function syncAiInputHeight() {
    var input = byId('ai-input');
    if (!input) { return; }
    input.style.height = 'auto';
    input.style.height = Math.min(Math.max(input.scrollHeight, 44), 120) + 'px';
  }

  function onAiInputKeydown(event) {
    if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
      event.preventDefault();
      submitAiMessage(event);
    }
  }

  function submitAiMessage(event) {
    if (event && typeof event.preventDefault === 'function') { event.preventDefault(); }
    if (state.aiChat.sending) { return; }
    var input = byId('ai-input');
    var text = String(input ? input.value : '').trim();
    if (!text) {
      toast('Напиши сообщение', 'error');
      haptic('error');
      if (input) { try { input.focus(); } catch (error) { /* noop */ } }
      return;
    }
    if (text.length > AI_MESSAGE_MAX_LENGTH) {
      toast('Сообщение — до ' + AI_MESSAGE_MAX_LENGTH + ' символов', 'error');
      haptic('error');
      return;
    }
    if (!aiChatActive(subscriptionPayload())) {
      toast('ИИ не подключён — подключи +100 ₽/мес', 'error');
      renderAiScreen();
      return;
    }
    var send = byId('ai-send');
    var now = new Date().toISOString();
    state.aiChat.sending = true;
    state.aiChat.pending = { role: 'user', text: text, created_at: now };
    if (input) { input.value = ''; syncAiInputHeight(); }
    setBusy(send, true);
    renderAiChat();
    scrollAiToBottom();
    haptic('select');
    apiRequest('POST', '/api/ai/chat', { text: text }).then(function (data) {
      state.aiChat.sending = false;
      state.aiChat.pending = null;
      var reply = String((data && data.reply) || '').trim();
      if (!reply) { throw makeError('bad_response'); }
      var stamp = new Date().toISOString();
      state.aiChat.items = (state.aiChat.items || []).concat([
        { id: 'local-user-' + stamp, role: 'user', text: text, created_at: stamp },
        { id: 'local-ai-' + stamp, role: 'assistant', text: reply, created_at: stamp }
      ]);
      if (data && typeof data.ai_active === 'boolean') {
        state.aiChat.active = data.ai_active;
        if (data.ai_active) { state.aiChat.forcePaywall = false; }
      }
      state.aiChat.loaded = true;
      setBusy(send, false);
      renderAiScreen();
      haptic('success');
      scrollAiToBottom();
      loadAiHistory(); // сверяем локальную запись с сервером
    }).catch(function (error) {
      state.aiChat.sending = false;
      state.aiChat.pending = null;
      setBusy(send, false);
      /* Текст не теряем: возвращаем его в поле, если пользователь ещё не начал новое. */
      if (input && !input.value) { input.value = text; syncAiInputHeight(); }
      renderAiChat();
      haptic('error');
      var code = error && error.code;
      if (code === 'ai_subscription_required' || code === 'http_402') {
        /* Нет оплаченного/триального ИИ — показываем paywall аддона. */
        showAiPaywall();
        return;
      }
      toast('Не получилось, попробуй ещё раз', 'error');
    });
  }

  /* ======================= онбординг ======================= */

  function showOnboarding() {
    var node = byId('onboarding');
    if (!node.hidden) { renderOnbStep(); return; }
    node.hidden = false;
    if (!state.onb.opened) {
      state.onb.opened = true;
      state.onb.step = 1;
      syncOnbInputs(state.onb.data);
    }
    renderOnbStep();
  }

  function hideOnboarding() {
    byId('onboarding').hidden = true;
    updateBackButton(false);
  }

  function syncOnbInputs(data) {
    var source = data || {};
    byId('onb-sex-male').checked = source.sex !== 'female';
    byId('onb-sex-female').checked = source.sex === 'female';
    if (source.age) { byId('onb-age').value = source.age; }
    if (source.height_cm) { byId('onb-height').value = source.height_cm; }
    if (source.weight_kg) { byId('onb-weight').value = source.weight_kg; }
    if (source.activity) { byId('onb-activity').value = source.activity; }
    if (source.goal_rate) {
      byId('onb-rate').value = source.goal_rate;
      updateRateLabel('onb-rate', 'onb-rate-label');
    }
    if (source.sleep_bed) { byId('onb-bed').value = source.sleep_bed; }
    if (source.sleep_wake) { byId('onb-wake').value = source.sleep_wake; }
    if (typeof source.reminders === 'boolean') { byId('onb-reminders').checked = source.reminders; }
  }

  function collectOnb() {
    return {
      sex: byId('onb-sex-female').checked ? 'female' : 'male',
      age: int(byId('onb-age').value),
      height_cm: num(byId('onb-height').value),
      weight_kg: num(byId('onb-weight').value),
      activity: byId('onb-activity').value,
      goal_rate: num(byId('onb-rate').value, 0.35),
      sleep_bed: byId('onb-bed').value || '23:00',
      sleep_wake: byId('onb-wake').value || '07:00',
      reminders: byId('onb-reminders').checked
    };
  }

  function validateOnbStep(step, data) {
    if (step === 1) {
      if (data.age < 10 || data.age > 100) { return 'Возраст — от 10 до 100 лет.'; }
      if (data.height_cm < 100 || data.height_cm > 250) { return 'Рост — от 100 до 250 см.'; }
      if (data.weight_kg < 25 || data.weight_kg > 400) { return 'Вес — от 25 до 400 кг.'; }
    }
    if (step === 2) {
      if (!ACTIVITY_LABELS[data.activity]) { return 'Выбери уровень активности.'; }
      if (data.goal_rate < 0.1 || data.goal_rate > 1) { return 'Темп набора — от 0,1 до 1 кг в неделю.'; }
    }
    if (step === 3) {
      if (!data.sleep_bed || !data.sleep_wake) { return 'Укажи время отбоя и подъёма.'; }
      if (data.sleep_bed === data.sleep_wake) { return 'Отбой и подъём не могут совпадать.'; }
    }
    return '';
  }

  function showOnbError(message) {
    var node = byId('onb-error');
    node.textContent = message;
    node.hidden = false;
  }

  function clearOnbError() {
    byId('onb-error').hidden = true;
  }

  function goOnbStep(delta) {
    clearOnbError();
    if (delta > 0) {
      var data = collectOnb();
      var error = validateOnbStep(state.onb.step, data);
      if (error) {
        showOnbError(error);
        haptic('error');
        return;
      }
      state.onb.data = data;
      if (state.onb.step < 4) { state.onb.step += 1; }
    } else if (state.onb.step > 1) {
      state.onb.step -= 1;
    }
    haptic('select');
    renderOnbStep();
  }

  function renderOnbStep() {
    var step = state.onb.step;
    byId('onb-step-1').hidden = step !== 1;
    byId('onb-step-2').hidden = step !== 2;
    byId('onb-step-3').hidden = step !== 3;
    byId('onb-step-4').hidden = step !== 4;
    byId('onb-step-label').textContent = 'Шаг ' + step + ' из 4';

    var dots = '';
    for (var index = 1; index <= 4; index += 1) {
      dots += '<span class="onb__dot' + (index <= step ? ' is-active' : '') + '"></span>';
    }
    byId('onb-dots').innerHTML = dots;

    byId('onb-back').hidden = step === 1;
    byId('onb-next').hidden = step === 4;
    byId('onb-submit').hidden = step !== 4;
    if (step === 4) { renderOnbSummary(); }
    updateBackButton(true);
  }

  function renderOnbSummary() {
    var data = collectOnb();
    state.onb.data = data;
    var rows = [
      ['Пол', data.sex === 'female' ? 'Женский' : 'Мужской'],
      ['Возраст', data.age + ' ' + plural(data.age, 'год', 'года', 'лет')],
      ['Рост и вес', fmtNumber(data.height_cm, 0) + ' см · ' + fmtNumber(data.weight_kg, 1) + ' кг'],
      ['Активность', ACTIVITY_LABELS[data.activity] || data.activity],
      ['Темп набора', fmtNumber(data.goal_rate, 2) + ' кг/нед'],
      ['Сон', data.sleep_bed + ' – ' + data.sleep_wake + ' · ' +
        fmtDuration(durationBetween(data.sleep_bed, data.sleep_wake) * 60)],
      ['Напоминания', data.reminders ? 'включены в боте' : 'выключены']
    ];
    byId('onb-summary').innerHTML = rows.map(function (row) {
      return '<div class="summary__row"><span>' + esc(row[0]) + '</span><b>' + esc(row[1]) + '</b></div>';
    }).join('');
  }

  function submitOnboarding() {
    if (state.onb.busy) { return; }
    var data = collectOnb();
    var error = validateOnbStep(1, data) || validateOnbStep(3, data);
    if (error) {
      showOnbError(error);
      haptic('error');
      return;
    }
    state.onb.data = data;
    state.onb.busy = true;
    var button = byId('onb-submit');
    setBusy(button, true);
    clearOnbError();

    var payload = {
      sex: data.sex,
      age: data.age,
      height_cm: data.height_cm,
      weight_kg: data.weight_kg,
      activity: data.activity,
      goal_rate: data.goal_rate,
      protein_per_kg: 2.0,
      sleep_bed: data.sleep_bed,
      sleep_wake: data.sleep_wake,
      reminders: data.reminders,
      timezone: detectTimezone()
    };
    apiRequest('PUT', '/api/profile', payload).then(function () {
      state.onb.busy = false;
      setBusy(button, false);
      haptic('success');
      toast('Профиль сохранён. Считаем цели!');
      hideOnboarding();
      state.bootstrap = null;
      switchTab('today', { force: true });
      loadBootstrap();
    }).catch(function (errorObj) {
      state.onb.busy = false;
      setBusy(button, false);
      haptic('error');
      showOnbError(errorText(errorObj.code));
    });
  }

  /* ======================= обработчики ======================= */

  function onFoodListClick(event) {
    var target = event.target;
    var button = target && target.closest ? target.closest('[data-delete-meal]') : null;
    if (button) {
      deleteMeal(button.getAttribute('data-delete-meal'));
    }
  }

  function onPresetClick(event) {
    var target = event.target;
    if (!target || !target.closest) { return; }
    var product = target.closest('[data-product-preset]');
    if (product) {
      applyProductPreset(int(product.getAttribute('data-product-preset')));
      return;
    }
    var suggest = target.closest('[data-suggest-food]');
    if (suggest) {
      applyFoodSuggestion(suggest.getAttribute('data-suggest-food'));
    }
  }

  function onDayToggleClick(event) {
    var target = event.target;
    var button = target && target.closest ? target.closest('[data-day-toggle]') : null;
    if (!button) { return; }
    var done = button.getAttribute('data-day-done') === '1';
    toggleDayDone(button.getAttribute('data-day-toggle'), !done);
  }

  function onDayTimelineClick(event) {
    var target = event.target;
    if (!target || !target.closest) { return; }
    var toggle = target.closest('[data-day-toggle]');
    if (toggle) {
      toggleDayDone(toggle.getAttribute('data-day-toggle'),
        toggle.getAttribute('data-day-done') !== '1');
      return;
    }
    var edit = target.closest('[data-edit-day]');
    if (edit) {
      editDayItem(edit.getAttribute('data-edit-day'));
    }
  }

  function onSuggestionsClick(event) {
    var target = event.target;
    var button = target && target.closest ? target.closest('[data-suggest-add]') : null;
    if (button) {
      addDaySuggestion(int(button.getAttribute('data-suggest-add')));
    }
  }

  function onSegmentsClick(event) {
    var target = event.target;
    var button = target && target.closest ? target.closest('[data-segment]') : null;
    if (button) {
      setScheduleSegment(button.getAttribute('data-segment'));
    }
  }

  function onPaletteClick(event) {
    var target = event.target;
    var button = target && target.closest ? target.closest('[data-preset-id]') : null;
    if (!button) { return; }
    var preset = findPalettePreset(button.getAttribute('data-preset-id'));
    if (!preset) { return; }
    haptic('select');
    applyPalette(preset, { save: true, cache: true });
  }

  function onQualityClick(event) {
    var target = event.target;
    var button = target && target.closest ? target.closest('[data-q]') : null;
    if (!button) { return; }
    setQuality(int(button.getAttribute('data-q')));
    haptic('select');
  }

  function onGridClick(event) {
    var target = event.target;
    var chip = target && target.closest ? target.closest('[data-class-id]') : null;
    if (chip) {
      editClass(chip.getAttribute('data-class-id'));
      return;
    }
    var dayButton = target && target.closest ? target.closest('[data-day]') : null;
    if (dayButton) {
      selectDay(dayButton.getAttribute('data-day'));
      haptic('select');
    }
  }

  function onDayListClick(event) {
    var target = event.target;
    if (!target || !target.closest) { return; }
    var statusButton = target.closest('[data-status]');
    if (statusButton) {
      markDone(
        statusButton.getAttribute('data-class-id'),
        statusButton.getAttribute('data-date'),
        statusButton.getAttribute('data-status')
      );
      return;
    }
    var editButton = target.closest('[data-edit-class]');
    if (editButton) {
      editClass(editButton.getAttribute('data-edit-class'));
    }
  }

  function bindEvents() {
    qsa('.tab').forEach(function (button) {
      button.addEventListener('click', function () {
        switchTab(button.getAttribute('data-screen'));
      });
    });

    qsa('[data-goto]').forEach(function (button) {
      button.addEventListener('click', function () {
        switchTab(button.getAttribute('data-goto'));
      });
    });

    // Сегодня
    byId('btn-add-meal').addEventListener('click', function () {
      switchTab('food');
      openMealForm();
    });
    byId('btn-log-sleep').addEventListener('click', function () {
      switchTab('sleep');
      haptic('select');
    });
    byId('btn-retry-today').addEventListener('click', function () {
      state.bootstrap = null;
      loadBootstrap();
    });
    // Цель: inline-редактор прямо в карточке
    byId('btn-set-goal').addEventListener('click', openGoalEditor);
    byId('btn-edit-goal').addEventListener('click', openGoalEditor);
    byId('today-goal-editor').addEventListener('submit', submitGoalEditor);
    byId('today-goal-cancel').addEventListener('click', closeGoalEditor);
    byId('today-day-list').addEventListener('click', onDayToggleClick);

    // Обязательный недельный чек-ин (закрыть нельзя — только сохранить)
    byId('weekly-form').addEventListener('submit', submitWeekly);

    byId('btn-day-plan').addEventListener('click', function () {
      state.schedule.segment = 'day';
      switchTab('schedule');
    });

    // Еда: мультиингредиенты + ручной режим
    byId('food-prev').addEventListener('click', function () { shiftFoodDate(-1); });
    byId('food-next').addEventListener('click', function () { shiftFoodDate(1); });
    byId('btn-open-meal-form').addEventListener('click', openMealForm);
    byId('meal-cancel').addEventListener('click', closeMealForm);
    byId('meal-form').addEventListener('submit', submitMeal);
    byId('food-list').addEventListener('click', onFoodListClick);
    byId('meal-presets').addEventListener('click', onPresetClick);
    byId('food-notfound-suggest').addEventListener('click', onPresetClick);
    byId('meal-add-item').addEventListener('click', function () { addMealItem(null); });
    byId('meal-items').addEventListener('input', onMealItemsInput);
    byId('meal-items').addEventListener('focusin', onMealItemsFocus);
    byId('meal-items').addEventListener('keydown', onMealItemsKeydown);
    byId('meal-items').addEventListener('click', onMealItemsClick);
    byId('btn-meal-manual').addEventListener('click', toggleManualMode);
    ['meal-title', 'meal-kcal', 'meal-protein', 'meal-fat', 'meal-carbs'].forEach(function (id) {
      byId(id).addEventListener('input', clearMealFormError);
    });

    // Сон
    byId('sleep-quality').addEventListener('click', onQualityClick);
    byId('sleep-bed').addEventListener('input', updateSleepDuration);
    byId('sleep-wake').addEventListener('input', updateSleepDuration);
    byId('sleep-submit').addEventListener('click', submitSleep);

    // Расписание: сегменты «День | Неделя»
    byId('schedule-segments').addEventListener('click', onSegmentsClick);
    byId('btn-add-class').addEventListener('click', function () {
      if (state.schedule.segment === 'day') {
        openDayItemForm(null);
      } else {
        openClassForm(null);
      }
    });
    byId('btn-add-class-day').addEventListener('click', function () { openClassForm(null); });
    byId('btn-add-day-item').addEventListener('click', function () { openDayItemForm(null); });
    byId('day-timeline').addEventListener('click', onDayTimelineClick);
    byId('day-suggestions').addEventListener('click', onSuggestionsClick);
    byId('day-item-form').addEventListener('submit', submitDayItem);
    byId('day-item-cancel').addEventListener('click', closeDayItemForm);
    byId('day-item-delete').addEventListener('click', deleteDayItem);
    byId('class-cancel').addEventListener('click', closeClassForm);
    byId('class-delete').addEventListener('click', deleteClass);
    byId('class-form').addEventListener('submit', submitClass);
    byId('schedule-grid').addEventListener('click', onGridClick);
    byId('day-classes').addEventListener('click', onDayListClick);

    // Прогресс
    byId('weight-form').addEventListener('submit', submitWeight);
    byId('profile-form').addEventListener('submit', submitProfile);
    byId('prof-rate').addEventListener('input', function () {
      updateRateLabel('prof-rate', 'prof-rate-label');
    });
    byId('palette-presets').addEventListener('click', onPaletteClick);
    ['color-accent', 'color-bg', 'color-card'].forEach(function (id) {
      byId(id).addEventListener('input', applyThemeFromInputs);
    });
    byId('btn-theme-reset').addEventListener('click', resetTheme);

    // Экран «ИИ»: чат-ассистент и аддон ИИ (v8)
    byId('ai-composer').addEventListener('submit', submitAiMessage);
    byId('ai-input').addEventListener('input', syncAiInputHeight);
    byId('ai-input').addEventListener('keydown', onAiInputKeydown);

    // Подписка (v5): блокирующий paywall и аддон ИИ
    byId('sub-pay-btn').addEventListener('click', payBase);
    byId('ai-subscribe-btn').addEventListener('click', payAi);

    // Онбординг
    byId('onb-next').addEventListener('click', function () { goOnbStep(1); });
    byId('onb-back').addEventListener('click', function () { goOnbStep(-1); });
    byId('onb-submit').addEventListener('click', submitOnboarding);
    byId('onb-rate').addEventListener('input', function () {
      updateRateLabel('onb-rate', 'onb-rate-label');
    });
  }

  /* ======================= запуск ======================= */

  function init() {
    state.tg = (window.Telegram && window.Telegram.WebApp) || null;
    state.initData = state.tg && typeof state.tg.initData === 'string' ? state.tg.initData : '';
    var params = null;
    try { params = new URLSearchParams(window.location.search); } catch (error) { params = null; }
    state.demo = !state.initData || !!(params && params.get('demo') === '1');
    byId('demo-banner').hidden = !state.demo;

    /* Палитра: inline-скрипт в index.html уже применил кэш до первой отрисовки,
       здесь синхронизируем состояние и подстраховываемся на случай его отсутствия. */
    applyPalette(readLocalTheme() || DEFAULT_THEME, { cache: false });
    renderPalette();

    applyTheme();
    if (state.tg) {
      try { state.tg.ready(); } catch (error) { /* noop */ }
      try { state.tg.expand(); } catch (error) { /* noop */ }
      try {
        if (typeof state.tg.onEvent === 'function') { state.tg.onEvent('themeChanged', applyTheme); }
      } catch (error) { /* noop */ }
      try {
        if (telegramVersionAtLeast('6.1') && typeof state.tg.disableVerticalSwipes === 'function') {
          state.tg.disableVerticalSwipes();
        }
      } catch (error) { /* noop */ }
    }

    renderPresets();
    byId('weight-date').value = todayIso();
    byId('meal-time').value = nowHm();
    setQuality(3);
    updateFoodDateUi();
    resetMealForm(); /* одна пустая строка ингредиента + ручной режим выключен */
    syncRangeFills();
    bindEvents();
    switchTab('today', { force: true });
    loadBootstrap(); // цели нужны любому экрану, даже если стартовая вкладка не «Сегодня»

    /* Возврат со страницы рублёвой оплаты: ?paid=base|ai -> refresh + bootstrap. */
    var paid = params && params.get('paid');
    if (paid === 'base' || paid === 'ai') {
      refreshPaidInvoice(paid);
      try {
        params.delete('paid');
        window.history.replaceState(
          null,
          '',
          window.location.pathname + (params.toString() ? '?' + params.toString() : '')
        );
      } catch (error) { /* noop — старые WebView могут запрещать history API */ }
    }

    window.setInterval(updateClassCountdown, 30000);
    document.addEventListener('visibilitychange', function () {
      if (!document.hidden && state.tab === 'today') { updateClassCountdown(); }
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
