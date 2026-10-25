(() => {
  const t = (key, params) => window.i18n.t(key, params);
  const form = document.querySelector('#setup-form');
  const message = document.querySelector('#setup-message');

  const setupToken = () => (document.querySelector('#setup-token')?.value || '').trim();

  async function api(path, options = {}) {
    const headers = new Headers(options.headers || {});
    if (options.body && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json');
    headers.set('Accept-Language', window.i18n.getLanguage());
    if (setupToken()) headers.set('X-Setup-Token', setupToken());
    const response = await fetch(path, { ...options, headers, credentials: 'same-origin' });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.error || t('setup.connectionFailed'));
    return data;
  }

  async function checkSetup() {
    try {
      const { needsSetup } = await api('/api/setup/status');
      if (!needsSetup) window.location.replace('/');
    } catch (error) {
      message.textContent = error.message;
      message.dataset.kind = 'connection';
      message.hidden = false;
    }
  }

  form.addEventListener('submit', async event => {
    event.preventDefault();
    const password = document.querySelector('#setup-password').value;
    if (!setupToken()) {
      message.textContent = t('setup.tokenRequired');
      message.hidden = false;
      return;
    }
    if (password !== document.querySelector('#setup-confirm').value) {
      message.textContent = t('setup.passwordMismatch');
      message.hidden = false;
      return;
    }
    const button = form.querySelector('button[type="submit"]');
    button.disabled = true;
    message.hidden = true;
    try {
      await api('/api/setup/admin', {
        method: 'POST',
        body: JSON.stringify({ email: document.querySelector('#setup-email').value, password }),
      });
      window.location.replace('/');
    } catch (error) {
      message.textContent = error.message;
      message.hidden = false;
      button.disabled = false;
    }
  });

  checkSetup();

  window.i18n.onChange(() => {
    if (!message.hidden && message.dataset.kind === 'connection') checkSetup();
  });
})();