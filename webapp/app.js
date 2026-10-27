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
    bad_response: 'Сервер ответил неожиданно. Попробуй ещё раз.'
  };

  /* ======================= состояние ======================= */

  var state = {
    tg: null,
    initData: '',
    demo: false,
    tab: 'today',
    bootstrap: null,
    bootstrapLoading: false,
    todayDate: todayIso(),
    nextClass: null,
    food: {
      date: todayIso(),
      data: null,
      loading: false,
      search: { query: '', items: [], loading: false, timer: null, active: -1 },
      selected: null,
      grams: 100,
      manual: false
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
    if (tab === 'progress' && !opts.noLoad) { loadProgress(); }
  }

  /* ======================= bootstrap и профиль ======================= */

  function loadBootstrap() {
    if (state.bootstrapLoading) { return; }
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
    }).catch(function (error) {
      state.bootstrapLoading = false;
      setScreenLoading('today', false);
      byId('today-content').classList.add('is-error');
      byId('today-error').hidden = false;
      toast(errorText(error.code), 'error');
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
    if (state.tab === 'schedule' && state.schedule.day) { renderDayPlan(); }
  }

  function currentTargets() {
    return (state.bootstrap && state.bootstrap.targets) || null;
  }

  function currentProfile() {
    return (state.bootstrap && state.bootstrap.profile) || null;
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

  function renderTodayGoal(goal) {
    var body = byId('today-goal-body');
    var empty = byId('today-goal-empty');
    var pctNode = byId('today-goal-pct');
    if (!body || !empty) { return; }
    if (!goal || !goal.enabled) {
      body.hidden = true;
      empty.hidden = false;
      if (pctNode) { pctNode.textContent = '—'; }
      return;
    }
    body.hidden = false;
    empty.hidden = true;

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
      return '<li class="meal-item">' +
        '<div class="meal-item__main">' +
          '<div class="meal-item__head">' +
            '<span class="meal-item__time">' + esc(meal.time || '') + '</span>' +
            '<span class="meal-item__title">' + esc(meal.title || 'Приём пищи') + '</span>' +
            '<span class="meal-item__kcal">' + esc(amount) + '</span>' +
          '</div>' +
          '<p class="meal-item__macros">' + macros + '</p>' +
          note +
        '</div>' +
        '<button type="button" class="meal-item__delete" data-delete-meal="' + esc(meal.id) + '" ' +
          'aria-label="Удалить приём ' + esc(meal.title || '') + '">×</button>' +
      '</li>';
    }).join('');
  }

  /* ======================= еда: автоКБЖУ, подсказки, граммы ======================= */

  var foodSearchSeq = 0;

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

  function currentGrams() {
    var input = byId('meal-grams');
    return clamp(int(input ? input.value : 100, 100), 1, 3000);
  }

  function updateMealPreview() {
    var preview = byId('meal-preview');
    if (!preview) { return; }
    if (state.food.manual) {
      preview.hidden = true;
      return;
    }
    preview.hidden = false;
    var food = state.food.selected;
    if (!food) {
      preview.textContent = 'Выбери продукт из подсказок — КБЖУ посчитается сам';
      return;
    }
    var grams = currentGrams();
    var macros = mealMacros(food, grams);
    preview.textContent = '≈ ' + fmtInt(macros.kcal) + ' ккал · Б ' + fmtNumber(macros.protein, 1) +
      ' · Ж ' + fmtNumber(macros.fat, 1) + ' · У ' + fmtNumber(macros.carbs, 1);
  }

  function syncSelectedFood() {
    var box = byId('food-selected');
    if (!box) { return; }
    var food = state.food.selected;
    if (!food || state.food.manual) {
      box.hidden = true;
      return;
    }
    box.hidden = false;
    byId('food-selected-name').textContent = food.name || '—';
    byId('food-selected-per100').textContent = 'на 100 г: ' +
      fmtInt(food.kcal) + ' ккал · Б ' + fmtNumber(food.protein, 1) +
      ' · Ж ' + fmtNumber(food.fat, 1) + ' · У ' + fmtNumber(food.carbs, 1);
  }

  function setSelectedFood(food) {
    state.food.selected = food || null;
    syncSelectedFood();
    updateMealPreview();
  }

  function renderFoodSuggest() {
    var box = byId('food-suggest');
    if (!box) { return; }
    var items = state.food.search.items;
    var input = byId('meal-title');
    if (!items.length) {
      box.hidden = true;
      box.innerHTML = '';
      if (input) { input.setAttribute('aria-expanded', 'false'); }
      return;
    }
    box.hidden = false;
    if (input) { input.setAttribute('aria-expanded', 'true'); }
    box.innerHTML = items.map(function (food, index) {
      var active = index === state.food.search.active;
      return '<button type="button" class="food-suggest__item' + (active ? ' is-active' : '') + '" ' +
        'role="option" data-food-id="' + esc(food.id) + '" aria-selected="' + (active ? 'true' : 'false') + '">' +
        '<span class="food-suggest__name">' + esc(food.name) + '</span>' +
        '<span class="food-suggest__kcal">' + fmtInt(food.kcal) + ' ккал / 100 г</span>' +
      '</button>';
    }).join('');
  }

  function requestFoodSuggestions(query) {
    var seq = ++foodSearchSeq;
    state.food.search.loading = true;
    apiRequest('GET', '/api/foods?q=' + encodeURIComponent(query) + '&limit=8').then(function (data) {
      if (seq !== foodSearchSeq) { return; }
      state.food.search.loading = false;
      state.food.search.items = ((data && data.items) || []).slice(0, 8);
      state.food.search.active = -1;
      renderFoodSuggest();
    }).catch(function () {
      if (seq !== foodSearchSeq) { return; }
      state.food.search.loading = false;
      state.food.search.items = [];
      renderFoodSuggest(); /* API v2 может быть не готов — не мешаем ручному вводу */
    });
  }

  function scheduleFoodSearch(query) {
    var search = state.food.search;
    if (search.timer) { window.clearTimeout(search.timer); search.timer = null; }
    search.query = query;
    if (!query) {
      search.items = [];
      renderFoodSuggest();
      return;
    }
    search.timer = window.setTimeout(function () {
      search.timer = null;
      requestFoodSuggestions(query);
    }, 200);
  }

  function findSuggestFood(foodId) {
    var found = null;
    state.food.search.items.forEach(function (item) {
      if (String(item.id) === String(foodId)) { found = item; }
    });
    return found;
  }

  function selectFoodById(foodId) {
    var food = findSuggestFood(foodId);
    if (!food) { return; }
    setSelectedFood(food);
    byId('meal-title').value = food.name || '';
    state.food.search.items = [];
    state.food.search.query = food.name || '';
    state.food.search.active = -1;
    renderFoodSuggest();
    clearMealFormError();
    updateMealPreview();
    haptic('select');
  }

  function onMealTitleInput() {
    var value = byId('meal-title').value.trim();
    var selected = state.food.selected;
    if (selected && String(selected.name || '').toLowerCase() !== value.toLowerCase()) {
      setSelectedFood(null);
    }
    clearMealFormError();
    scheduleFoodSearch(value);
    updateMealPreview();
  }

  function onMealTitleFocus() {
    if (byId('meal-title').value.trim()) {
      if (state.food.search.items.length) { renderFoodSuggest(); }
      return;
    }
    if (!state.food.search.items.length) {
      requestFoodSuggestions(''); /* пустой q — популярные продукты */
    } else {
      renderFoodSuggest();
    }
  }

  function onMealTitleKeydown(event) {
    var search = state.food.search;
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      if (!search.items.length) { return; }
      event.preventDefault();
      var delta = event.key === 'ArrowDown' ? 1 : -1;
      search.active = search.active < 0
        ? 0
        : clamp(search.active + delta, 0, search.items.length - 1);
      renderFoodSuggest();
      return;
    }
    if (event.key === 'Enter') {
      if (search.items.length) {
        event.preventDefault();
        var index = search.active >= 0 ? search.active : 0;
        selectFoodById(search.items[index].id);
      }
      return;
    }
    if (event.key === 'Escape') {
      search.items = [];
      renderFoodSuggest();
    }
  }

  var productMatchSeq = 0;

  function applyProductPreset(index) {
    var preset = PRODUCT_PRESETS[index];
    if (!preset) { return; }
    if (state.food.manual) { toggleManualMode(); } /* пресет — всегда автоКБЖУ */
    byId('meal-title').value = preset.title;
    byId('meal-grams').value = String(preset.grams);
    setSelectedFood(null);
    state.food.search.items = [];
    renderFoodSuggest();
    updateMealPreview();
    haptic('select');
    byId('meal-grams').focus();
    /* Подтягиваем точное имя и КБЖУ с сервера. */
    var seq = ++productMatchSeq;
    apiRequest('GET', '/api/foods?q=' + encodeURIComponent(preset.title) + '&limit=1').then(function (data) {
      if (seq !== productMatchSeq) { return; }
      var items = (data && data.items) || [];
      if (items.length && !state.food.search.items.length) {
        state.food.search.items = items;
        selectFoodById(items[0].id);
        byId('meal-title').value = preset.title;
      }
    }).catch(function () { /* подсказки недоступны — отправим текст как есть */ });
  }

  function applyGramsStep(delta) {
    var input = byId('meal-grams');
    if (!input) { return; }
    input.value = String(clamp(int(input.value, 100) + delta, 1, 3000));
    haptic('select');
    updateMealPreview();
  }

  function toggleManualMode() {
    state.food.manual = !state.food.manual;
    var manual = state.food.manual;
    byId('meal-manual').hidden = !manual;
    byId('meal-grams-field').hidden = manual;
    byId('meal-submit').textContent = manual ? 'Добавить вручную' : 'Добавить';
    var toggle = byId('btn-meal-manual');
    toggle.setAttribute('aria-expanded', manual ? 'true' : 'false');
    toggle.textContent = manual ? 'вернуться к автоКБЖУ' : 'ввести вручную';
    if (manual) {
      byId('meal-preview').hidden = true;
      byId('food-selected').hidden = true;
      byId('food-suggest').hidden = true;
    } else {
      syncSelectedFood();
      updateMealPreview();
    }
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
      error.textContent = 'Не нашёл продукт «' + query + '» — уточни название или введи КБЖУ вручную.';
      error.hidden = false;
    }
    var box = byId('food-notfound-suggest');
    if (!box) { return; }
    box.hidden = true;
    box.innerHTML = '';
    apiRequest('GET', '/api/foods?q=' + encodeURIComponent(query) + '&limit=3').then(function (data) {
      var items = (data && data.items) || [];
      if (!items.length) { return; }
      state.food.search.items = items.slice();
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
    if (!byId('meal-grams').value) { byId('meal-grams').value = '100'; }
    updateMealPreview();
    try { form.scrollIntoView({ behavior: 'smooth', block: 'center' }); } catch (error) { /* noop */ }
    window.setTimeout(function () { byId('meal-title').focus(); }, 60);
  }

  function closeMealForm() {
    byId('meal-form').hidden = true;
    byId('btn-open-meal-form').hidden = false;
  }

  function resetMealForm() {
    byId('meal-title').value = '';
    byId('meal-grams').value = '100';
    byId('meal-kcal').value = '';
    byId('meal-protein').value = '';
    byId('meal-fat').value = '';
    byId('meal-carbs').value = '';
    byId('meal-note').value = '';
    byId('meal-time').value = nowHm();
    state.food.search.items = [];
    state.food.search.query = '';
    state.food.search.active = -1;
    setSelectedFood(null);
    renderFoodSuggest();
    if (state.food.manual) { toggleManualMode(); }
    clearMealFormError();
    updateMealPreview();
  }

  function submitMeal(event) {
    event.preventDefault();
    var title = byId('meal-title').value.trim();
    if (!title) {
      toast('Что съел? Добавь название продукта', 'error');
      byId('meal-title').focus();
      return;
    }
    var payload;
    if (state.food.manual) {
      var kcal = num(byId('meal-kcal').value);
      if (kcal <= 0) {
        toast('Укажи калорийность вручную', 'error');
        byId('meal-kcal').focus();
        return;
      }
      payload = {
        date: state.food.date,
        time: byId('meal-time').value || nowHm(),
        title: title,
        kcal: kcal,
        protein: num(byId('meal-protein').value),
        fat: num(byId('meal-fat').value),
        carbs: num(byId('meal-carbs').value),
        note: byId('meal-note').value.trim()
      };
    } else {
      payload = {
        date: state.food.date,
        time: byId('meal-time').value || nowHm(),
        title: state.food.selected ? state.food.selected.name : title,
        grams: currentGrams(),
        note: byId('meal-note').value.trim()
      };
      if (state.food.selected) { payload.food_id = state.food.selected.id; }
    }
    var gramsLabel = state.food.manual ? '' : ' · ' + currentGrams() + ' г';
    clearMealFormError();
    var button = byId('meal-submit');
    setBusy(button, true);
    apiRequest('POST', '/api/meals', payload).then(function () {
      setBusy(button, false);
      haptic('success');
      toast('Записано: ' + title + gramsLabel);
      resetMealForm();
      closeMealForm();
      state.food.data = null;
      loadFood({ silent: true });
      if (state.food.date === todayIso()) { loadBootstrap(); }
    }).catch(function (error) {
      setBusy(button, false);
      haptic('error');
      if (error.code === 'food_not_found') {
        showFoodNotFound(title);
        requestFoodSuggestions(title);
        return; /* поле не очищаем — пусть пользователь уточнит */
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

  function updateRateLabel(inputId, labelId) {
    var value = num(byId(inputId).value, 0.35);
    byId(labelId).textContent = fmtNumber(value, 2) + ' кг/нед';
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
      loadBootstrap();
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
      if (state.bootstrap) {
        state.bootstrap.profile = (data && data.profile) || state.bootstrap.profile;
        if (targets) { state.bootstrap.targets = targets; }
      }
      renderProfileForm();
      renderToday();
      if (targets && targets.kcal) {
        toast('Сохранено. Цель: ' + fmtInt(targets.kcal) + ' ккал, белок ' + fmtInt(targets.protein) + ' г');
      } else {
        toast('Профиль сохранён');
      }
      loadBootstrap();
    }).catch(function (error) {
      setBusy(button, false);
      haptic('error');
      toast(errorText(error.code), 'error');
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
      selectFoodById(suggest.getAttribute('data-suggest-food'));
    }
  }

  function onFoodSuggestClick(event) {
    var target = event.target;
    var button = target && target.closest ? target.closest('[data-food-id]') : null;
    if (button) {
      selectFoodById(button.getAttribute('data-food-id'));
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
    byId('btn-set-goal').addEventListener('click', function () {
      switchTab('progress');
      haptic('select');
      window.setTimeout(function () {
        var input = byId('prof-goal-weight');
        if (!input) { return; }
        try { input.focus(); } catch (error) { /* noop */ }
      }, 320);
    });
    byId('btn-day-plan').addEventListener('click', function () {
      state.schedule.segment = 'day';
      switchTab('schedule');
    });
    byId('today-day-list').addEventListener('click', onDayToggleClick);

    // Еда: автоКБЖУ + ручной режим
    byId('food-prev').addEventListener('click', function () { shiftFoodDate(-1); });
    byId('food-next').addEventListener('click', function () { shiftFoodDate(1); });
    byId('btn-open-meal-form').addEventListener('click', openMealForm);
    byId('meal-cancel').addEventListener('click', closeMealForm);
    byId('meal-form').addEventListener('submit', submitMeal);
    byId('food-list').addEventListener('click', onFoodListClick);
    byId('meal-presets').addEventListener('click', onPresetClick);
    byId('food-notfound-suggest').addEventListener('click', onPresetClick);
    byId('food-suggest').addEventListener('click', onFoodSuggestClick);
    byId('meal-title').addEventListener('input', onMealTitleInput);
    byId('meal-title').addEventListener('focus', onMealTitleFocus);
    byId('meal-title').addEventListener('keydown', onMealTitleKeydown);
    byId('meal-grams').addEventListener('input', updateMealPreview);
    byId('meal-grams').addEventListener('change', updateMealPreview);
    byId('meal-grams-minus').addEventListener('click', function () { applyGramsStep(-10); });
    byId('meal-grams-plus').addEventListener('click', function () { applyGramsStep(10); });
    byId('food-selected-clear').addEventListener('click', function () {
      setSelectedFood(null);
      byId('meal-title').value = '';
      clearMealFormError();
      updateMealPreview();
      haptic('select');
    });
    byId('btn-meal-manual').addEventListener('click', toggleManualMode);
    ['meal-kcal', 'meal-protein', 'meal-fat', 'meal-carbs'].forEach(function (id) {
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
    bindEvents();
    switchTab('today', { force: true });
    loadBootstrap(); // цели нужны любому экрану, даже если стартовая вкладка не «Сегодня»

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
