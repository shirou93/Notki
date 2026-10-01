(() => {
  const form = document.querySelector('#setup-form');
  const message = document.querySelector('#setup-message');

  async function api(path, options = {}) {
    const headers = new Headers(options.headers || {});
    if (options.body && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json');
    const response = await fetch(path, { ...options, headers, credentials: 'same-origin' });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.error || 'Nie udało się połączyć z serwerem.');
    return data;
  }

  async function checkSetup() {
    try {
      const { needsSetup } = await api('/api/setup/status');
      if (!needsSetup) window.location.replace('/');
    } catch (error) {
      message.textContent = error.message;
      message.hidden = false;
    }
  }

  form.addEventListener('submit', async event => {
    event.preventDefault();
    const password = document.querySelector('#setup-password').value;
    if (password !== document.querySelector('#setup-confirm').value) {
      message.textContent = 'Hasła nie są takie same.';
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
      snapshotMessage.textContent = 'Snapshot przekracza limit 100 MB.';
      snapshotMessage.hidden = false;
      return;
    }
    importButton.disabled = true;
    snapshotMessage.hidden = true;
    try {
      if (file.name.toLowerCase().endsWith('.tgz')) {
        const response = await fetch('/api/setup/import-backup', {
          method: 'POST',
          headers: { 'Content-Type': 'application/gzip' },
          body: file,
          credentials: 'same-origin',
        });
        const result = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(result.error || 'Nie udało się przywrócić backupu.');
      } else {
        const snapshot = JSON.parse(await file.text());
        await api('/api/setup/import', { method: 'POST', body: JSON.stringify({ snapshot }) });
      }
      snapshotMessage.textContent = 'Backup przywrócony. Przekierowuję do logowania.';
      snapshotMessage.hidden = false;
      window.location.replace('/');
    } catch (error) {
      snapshotMessage.textContent = error instanceof SyntaxError ? 'Plik nie zawiera poprawnego JSON-u.' : error.message;
      snapshotMessage.hidden = false;
      importButton.disabled = false;
    }
  });

  checkSetup();
})();