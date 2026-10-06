/* Shared translation layer for Notki: dictionaries, language persistence and DOM translation. */
(() => {
  const STORAGE_KEY = 'notki.lang.v1';
  const FALLBACK_LANGUAGE = 'en';
  const SUPPORTED_LANGUAGES = ['pl', 'en'];
  const HTML_LANGUAGES = { pl: 'pl', en: 'en' };

  const DICTIONARIES = window.notkiTranslations || {};

  const listeners = new Set();

  function normalizeLanguage(value) {
    const tag = String(value || '').trim().toLowerCase().split('-')[0];
    return SUPPORTED_LANGUAGES.includes(tag) ? tag : '';
  }

  function detectLanguage() {
    const stored = normalizeLanguage(window.localStorage?.getItem(STORAGE_KEY));
    if (stored) return stored;
    return normalizeLanguage(window.navigator?.language) || FALLBACK_LANGUAGE;
  }

  let language = detectLanguage();

  function dictionary(lang = language) {
    return DICTIONARIES[lang] || DICTIONARIES[FALLBACK_LANGUAGE] || {};
  }

  function lookup(key, lang) {
    const active = dictionary(lang);
    if (key in active) return active[key];
    const fallback = dictionary(FALLBACK_LANGUAGE);
    return key in fallback ? fallback[key] : key;
  }

  function interpolate(template, params) {
    if (!params) return template;
    return template.replace(/\{(\w+)\}/g, (match, name) => (
      Object.prototype.hasOwnProperty.call(params, name) ? String(params[name]) : match
    ));
  }

  function t(key, params) {
    return interpolate(lookup(key), params);
  }

  function pluralKey(key, count) {
    const category = new Intl.PluralRules(language).select(count);
    for (const candidate of [`${key}.${category}`, `${key}.other`, `${key}.many`, `${key}.few`, `${key}.one`]) {
      if (lookup(candidate, language) !== candidate) return candidate;
    }
    return key;
  }

  function plural(key, count, params) {
    return t(pluralKey(key, count), { count, ...params });
  }

  function formatDate(value) {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return '';
    const today = new Date();
    if (date.toDateString() === today.toDateString()) {
      return t('date.today', { time: new Intl.DateTimeFormat(HTML_LANGUAGES[language], { hour: '2-digit', minute: '2-digit' }).format(date) });
    }
    return new Intl.DateTimeFormat(HTML_LANGUAGES[language], { day: 'numeric', month: 'short' }).format(date);
  }

  function formatFullDate(value) {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return '';
    return new Intl.DateTimeFormat(HTML_LANGUAGES[language], { day: 'numeric', month: 'long', year: 'numeric' }).format(date);
  }

  function formatDateTime(value) {
    if (!value) return '—';
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return '—';
    return new Intl.DateTimeFormat(HTML_LANGUAGES[language], { dateStyle: 'medium', timeStyle: 'short' }).format(date);
  }

  function formatNumber(value, options) {
    return new Intl.NumberFormat(HTML_LANGUAGES[language], options).format(value);
  }

  function getLanguage() {
    return language;
  }

  function setLanguage(next, { persist = true } = {}) {
    const resolved = normalizeLanguage(next) || FALLBACK_LANGUAGE;
    if (persist) window.localStorage?.setItem(STORAGE_KEY, resolved);
    const changed = resolved !== language;
    language = resolved;
    document.documentElement.lang = HTML_LANGUAGES[language];
    document.documentElement.dataset.lang = language;
    syncLanguageControls();
    applyTranslations();
    if (changed) listeners.forEach(listener => listener(language));
  }

  function applyAttribute(root, selector, attribute, key) {
    root.querySelectorAll(selector).forEach(element => {
      element.setAttribute(attribute, t(key ?? element.getAttribute(`data-i18n-${attribute}`)));
    });
  }

  function applyTranslations(root = document) {
    root.querySelectorAll('[data-i18n]').forEach(element => {
      element.textContent = t(element.dataset.i18n);
    });
    root.querySelectorAll('[data-i18n-placeholder]').forEach(element => {
      element.setAttribute('placeholder', t(element.dataset.i18nPlaceholder));
    });
    root.querySelectorAll('[data-i18n-data-placeholder]').forEach(element => {
      element.setAttribute('data-placeholder', t(element.dataset.i18nDataPlaceholder));
    });
    root.querySelectorAll('[data-i18n-aria-label]').forEach(element => {
      element.setAttribute('aria-label', t(element.dataset.i18nAriaLabel));
    });
    root.querySelectorAll('[data-i18n-title]').forEach(element => {
      element.setAttribute('title', t(element.dataset.i18nTitle));
    });
    root.querySelectorAll('[data-i18n-content]').forEach(element => {
      element.setAttribute('content', t(element.dataset.i18nContent));
    });
  }

  function syncLanguageControls() {
    document.querySelectorAll('[data-language-select]').forEach(select => {
      select.value = language;
      select.setAttribute('aria-label', t('language.switch'));
      select.title = t('language.switch');
    });
  }

  function onChange(listener) {
    listeners.add(listener);
    return () => listeners.delete(listener);
  }

  document.addEventListener('DOMContentLoaded', () => {
    setLanguage(language, { persist: false });
    document.querySelectorAll('[data-language-select]').forEach(select => {
      select.addEventListener('change', () => setLanguage(select.value));
    });
  });

  document.documentElement.lang = HTML_LANGUAGES[language];
  document.documentElement.dataset.lang = language;

  window.i18n = {
    t, plural, formatDate, formatFullDate, formatDateTime, formatNumber,
    getLanguage, setLanguage, applyTranslations, onChange,
    supportedLanguages: [...SUPPORTED_LANGUAGES],
  };
})();
