(() => {
  const t = (key, params) => window.i18n.t(key, params);
  const form = document.querySelector('#setup-form');
  const message = document.querySelector('#setup-message');

  async function api(path, options = {}) {
    const headers = new Headers(options.headers || {});
    if (options.body && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json');
    headers.set('Accept-Language', window.i18n.getLanguage());
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

  const snapshotFile = document.querySelector('#snapshot-file');
  const importButton = document.querySelector('#import-snapshot');
  const snapshotMessage = document.querySelector('#snapshot-message');

  snapshotFile.addEventListener('change', () => {
    importButton.disabled = !snapshotFile.files.length;
    snapshotMessage.hidden = true;
  });
  importButton.addEventListener('click', async () => {
    const file = snapshotFile.files[0];
    if (!file) return;
    if (file.size > 100 * 1024 * 1024) {
      snapshotMessage.textContent = t('setup.importTooLarge');
      snapshotMessage.hidden = false;
      return;
    }
    importButton.disabled = true;
    snapshotMessage.hidden = true;
    try {
      if (file.name.toLowerCase().endsWith('.tgz')) {
        const formData = new FormData();
        formData.append('archive', file);
        const password = document.querySelector('#restore-password')?.value || '';
        if (password) formData.append('password', password);
        const response = await fetch('/api/setup/import-backup', {
          method: 'POST',
          headers: { 'Accept-Language': window.i18n.getLanguage() },
          body: formData,
          credentials: 'same-origin',
        });
        const result = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(result.error || t('setup.importFailed'));
      } else {
        const snapshot = JSON.parse(await file.text());
        await api('/api/setup/import', { method: 'POST', body: JSON.stringify({ snapshot }) });
      }
      snapshotMessage.textContent = t('setup.importRestored');
      snapshotMessage.hidden = false;
      window.location.replace('/');
    } catch (error) {
      snapshotMessage.textContent = error instanceof SyntaxError ? t('setup.importInvalidJson') : error.message;
      snapshotMessage.hidden = false;
      importButton.disabled = false;
    }
  });

  checkSetup();

  window.i18n.onChange(() => {
    if (!message.hidden && message.dataset.kind === 'connection') checkSetup();
  });
})();