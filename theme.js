/* Shared theme handling for Notki: system preference, stored choice, and toggle buttons. */
(() => {
  const STORAGE_KEY = 'notki.theme.v1';
  const LIGHT = 'light';
  const DARK = 'dark';
  const SYSTEM = 'system';
  const systemColorScheme = window.matchMedia('(prefers-color-scheme: dark)');
  const listeners = new Set();

  function storedTheme() {
    const value = window.localStorage?.getItem(STORAGE_KEY);
    return [DARK, LIGHT, SYSTEM].includes(value) ? value : SYSTEM;
  }

  function getTheme() {
    return document.documentElement.dataset.theme === DARK ? DARK : LIGHT;
  }

  function syncControls() {
    const preference = storedTheme();
    document.querySelectorAll('[data-theme-select]').forEach(select => {
      select.value = preference;
    });
  }

  function setTheme(theme, { persist = false } = {}) {
    let resolved = theme;
    if (theme === SYSTEM) {
      resolved = systemColorScheme.matches ? DARK : LIGHT;
    }

    document.documentElement.dataset.theme = resolved;

    if (persist) {
      if (theme === SYSTEM) {
        window.localStorage?.removeItem(STORAGE_KEY); // Store nothing or 'system' as default
      } else {
        window.localStorage?.setItem(STORAGE_KEY, theme);
      }
    }
    syncControls();
    listeners.forEach(listener => listener(resolved));
    return resolved;
  }

  function onChange(listener) {
    listeners.add(listener);
    return () => listeners.delete(listener);
  }

  function initialize() {
    setTheme(storedTheme());

    document.querySelectorAll('[data-theme-select]').forEach(select => {
      select.addEventListener('change', event => {
        setTheme(event.target.value, { persist: true });
      });
    });

    systemColorScheme.addEventListener('change', event => {
      if (storedTheme() === SYSTEM) setTheme(SYSTEM);
    });
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', initialize);
  else initialize();

  window.notkiTheme = { get: getTheme, set: setTheme, onChange, sync: syncControls };
})();
