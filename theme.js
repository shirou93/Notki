/* Shared theme handling for Notki: system preference, stored choice, and toggle buttons. */
(() => {
  const STORAGE_KEY = 'notki.theme.v1';
  const LIGHT = 'light';
  const DARK = 'dark';
  const systemColorScheme = window.matchMedia('(prefers-color-scheme: dark)');
  const listeners = new Set();

  const translate = (key, fallback) => (window.i18n ? window.i18n.t(key) : fallback);

  function storedTheme() {
    const value = window.localStorage?.getItem(STORAGE_KEY);
    return value === DARK || value === LIGHT ? value : '';
  }

  function getTheme() {
    return document.documentElement.dataset.theme === DARK ? DARK : LIGHT;
  }

  function syncControls() {
    const theme = getTheme();
    const label = translate(
      theme === DARK ? 'topbar.theme.enableLight' : 'topbar.theme.enableDark',
      theme === DARK ? 'Enable light theme' : 'Enable dark theme',
    );
    document.querySelectorAll('[data-theme-toggle]').forEach(button => {
      const icon = button.querySelector('span');
      const iconValue = theme === DARK ? button.dataset.themeIconDark : button.dataset.themeIconLight;
      if (icon && iconValue) icon.textContent = iconValue;
      button.setAttribute('aria-label', label);
      button.setAttribute('title', label);
      button.setAttribute('aria-pressed', String(theme === DARK));
    });
  }

  function setTheme(theme, { persist = false } = {}) {
    const resolved = theme === DARK ? DARK : LIGHT;
    document.documentElement.dataset.theme = resolved;
    if (persist) window.localStorage?.setItem(STORAGE_KEY, resolved);
    syncControls();
    listeners.forEach(listener => listener(resolved));
    return resolved;
  }

  function toggleTheme() {
    return setTheme(getTheme() === DARK ? LIGHT : DARK, { persist: true });
  }

  function onChange(listener) {
    listeners.add(listener);
    return () => listeners.delete(listener);
  }

  function initialize() {
    setTheme(storedTheme() || (systemColorScheme.matches ? DARK : LIGHT));
    document.querySelectorAll('[data-theme-toggle]').forEach(button => {
      button.addEventListener('click', toggleTheme);
    });
    systemColorScheme.addEventListener('change', event => {
      if (!storedTheme()) setTheme(event.matches ? DARK : LIGHT);
    });
    if (window.i18n) window.i18n.onChange(syncControls);
  }

  // Deferred scripts run after parsing, so this keeps the stored theme from flashing.
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', initialize);
  else initialize();

  window.notkiTheme = { get: getTheme, set: setTheme, toggle: toggleTheme, onChange, sync: syncControls };
})();
