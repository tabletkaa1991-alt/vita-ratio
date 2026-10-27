/* Vita Ratio · локальный фолбэк Telegram.WebApp.
 *
 * Подключается после официального SDK. Если SDK загрузился (есть интернет и
 * window.Telegram.WebApp с ready()), шим молча выходит. Иначе создаёт
 * минимально совместимый объект, чтобы приложение работало в демо-режиме
 * в обычном браузере.
 *
 * initData намеренно пустой: по контракту пустой initData = демо-режим
 * (заголовок X-Dev-User: 1 на стороне API).
 */
(function (window, document) {
  'use strict';

  var existing = window.Telegram && window.Telegram.WebApp;
  if (existing && typeof existing.ready === 'function') {
    return; // официальный SDK на месте — шim не нужен
  }

  function noop() {}

  function createEventBus() {
    var listeners = {};
    return {
      on: function (event, handler) {
        if (typeof handler !== 'function' || typeof event !== 'string') { return; }
        if (!listeners[event]) { listeners[event] = []; }
        listeners[event].push(handler);
      },
      off: function (event, handler) {
        var list = listeners[event] || [];
        var index = list.indexOf(handler);
        if (index >= 0) { list.splice(index, 1); }
      },
      emit: function (event, payload) {
        var list = (listeners[event] || []).slice();
        for (var i = 0; i < list.length; i += 1) {
          try { list[i](payload); } catch (error) { /* не ломаем UI из-за подписчика */ }
        }
      }
    };
  }

  var bus = createEventBus();

  function vibrate(pattern) {
    try {
      if (navigator && typeof navigator.vibrate === 'function') {
        navigator.vibrate(pattern);
      }
    } catch (error) { /* вибрация не критична */ }
  }

  var backButton = {
    isVisible: false,
    _handlers: [],
    show: function () { backButton.isVisible = true; bus.emit('backButtonShown', {}); },
    hide: function () { backButton.isVisible = false; },
    onClick: function (handler) {
      if (typeof handler === 'function') { backButton._handlers.push(handler); }
    },
    offClick: function (handler) {
      var index = backButton._handlers.indexOf(handler);
      if (index >= 0) { backButton._handlers.splice(index, 1); }
    },
    _press: function () {
      var list = backButton._handlers.slice();
      for (var i = 0; i < list.length; i += 1) {
        try { list[i](); } catch (error) { /* noop */ }
      }
    }
  };

  var settingsButton = {
    isVisible: false,
    show: noop,
    hide: noop,
    onClick: noop,
    offClick: noop
  };

  var mainButton = {
    text: 'Продолжить',
    color: '#B7F75C',
    textColor: '#10240A',
    isVisible: false,
    isActive: true,
    isProgressVisible: false,
    setText: function (text) { mainButton.text = String(text || ''); },
    show: function () { mainButton.isVisible = true; },
    hide: function () { mainButton.isVisible = false; },
    enable: function () { mainButton.isActive = true; },
    disable: function () { mainButton.isActive = false; },
    showProgress: function (leaveActive) {
      mainButton.isProgressVisible = true;
      mainButton.isActive = !!leaveActive;
    },
    hideProgress: function () {
      mainButton.isProgressVisible = false;
      mainButton.isActive = true;
    },
    onClick: noop,
    offClick: noop
  };

  var viewportHeight = window.innerHeight || 844;

  var webApp = {
    // --- окружение ---
    initData: '',
    initDataUnsafe: {},
    version: '6.9',
    platform: 'web',
    colorScheme: 'dark',
    themeParams: {
      bg_color: '#0E1116',
      secondary_bg_color: '#151A21',
      section_bg_color: '#151A21',
      header_bg_color: '#0E1116',
      text_color: '#F2F6EF',
      hint_color: '#9AA6A0',
      subtitle_text_color: '#9AA6A0',
      link_color: '#B7F75C',
      accent_text_color: '#B7F75C',
      button_color: '#B7F75C',
      button_text_color: '#10240A',
      destructive_text_color: '#FF6B6B'
    },
    isExpanded: true,
    viewportHeight: viewportHeight,
    viewportStableHeight: viewportHeight,
    headerColor: '#0E1116',
    backgroundColor: '#0E1116',
    isClosingConfirmationEnabled: false,
    isVerticalSwipesEnabled: true,

    // --- жизненный цикл ---
    ready: function () {
      setTimeout(function () { bus.emit('viewportChanged', { isStateStable: true }); }, 0);
    },
    expand: function () { webApp.isExpanded = true; },
    close: noop,
    sendData: noop,
    openLink: function (url) {
      try { window.open(url, '_blank', 'noopener'); } catch (error) { /* noop */ }
    },
    openTelegramLink: function (url) {
      try { window.open(url, '_blank', 'noopener'); } catch (error) { /* noop */ }
    },
    setHeaderColor: function (color) { webApp.headerColor = color; },
    setBackgroundColor: function (color) { webApp.backgroundColor = color; },
    setBottomBarColor: noop,
    disableVerticalSwipes: function () { webApp.isVerticalSwipesEnabled = false; },
    enableVerticalSwipes: function () { webApp.isVerticalSwipesEnabled = true; },
    disableClosingConfirmation: function () { webApp.isClosingConfirmationEnabled = false; },
    enableClosingConfirmation: function () { webApp.isClosingConfirmationEnabled = true; },

    // --- события ---
    onEvent: bus.on,
    offEvent: bus.off,

    // --- диалоги ---
    showAlert: function (message, callback) {
      try { window.alert(String(message || '')); } catch (error) { /* noop */ }
      if (typeof callback === 'function') { callback(); }
    },
    showConfirm: function (message, callback) {
      var confirmed = false;
      try { confirmed = window.confirm(String(message || '')); } catch (error) { confirmed = false; }
      if (typeof callback === 'function') { callback(confirmed); }
    },
    showPopup: function (params, callback) {
      var text = params && (params.message || params.title) ? String(params.message || params.title) : '';
      try { window.alert(text); } catch (error) { /* noop */ }
      if (typeof callback === 'function') { callback('ok'); }
    },
    requestContact: noop,

    // --- элементы управления ---
    BackButton: backButton,
    SettingsButton: settingsButton,
    MainButton: mainButton,

    // --- тактильный отклик ---
    HapticFeedback: {
      impactOccurred: function (style) {
        vibrate(style === 'heavy' ? 24 : style === 'medium' ? 16 : 10);
      },
      notificationOccurred: function (type) {
        vibrate(type === 'error' ? 30 : type === 'warning' ? 20 : 14);
      },
      selectionChanged: function () { vibrate(6); }
    }
  };

  window.Telegram = window.Telegram || {};
  window.Telegram.WebApp = webApp;
  window.__VITA_TG_SHIM__ = true;

  window.addEventListener('resize', function () {
    try {
      webApp.viewportHeight = window.innerHeight || viewportHeight;
      webApp.viewportStableHeight = webApp.viewportHeight;
      bus.emit('viewportChanged', { isStateStable: true });
    } catch (error) { /* noop */ }
  });
})(window, document);
