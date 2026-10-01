(() => {
  const THEME_STORAGE_KEY = 'notki.theme.v1';
  const themeToggle = document.querySelector('#theme-toggle');
  const systemColorScheme = window.matchMedia('(prefers-color-scheme: dark)');

  function applyTheme(theme) {
    document.documentElement.dataset.theme = theme;
    const nextTheme = theme === 'dark' ? 'jasny' : 'ciemny';
    themeToggle.querySelector('span').textContent = theme === 'dark' ? '☀︎' : '☾︎';
    themeToggle.setAttribute('aria-label', `Włącz ${nextTheme} motyw`);
    themeToggle.title = `Włącz ${nextTheme} motyw`;
    themeToggle.setAttribute('aria-pressed', String(theme === 'dark'));
  }

  const savedTheme = localStorage.getItem(THEME_STORAGE_KEY);
  applyTheme(savedTheme === 'dark' || savedTheme === 'light' ? savedTheme : systemColorScheme.matches ? 'dark' : 'light');
  systemColorScheme.addEventListener('change', event => {
    if (!localStorage.getItem(THEME_STORAGE_KEY)) applyTheme(event.matches ? 'dark' : 'light');
  });
  themeToggle.addEventListener('click', () => {
    const theme = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
    localStorage.setItem(THEME_STORAGE_KEY, theme);
    applyTheme(theme);
  });

  async function api(path, options = {}) {
    const headers = new Headers(options.headers || {});
    if (options.body && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json');
    const response = await fetch(path, { ...options, headers, credentials: 'same-origin' });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw Object.assign(new Error(data.error || 'Błąd serwera.'), { status: response.status });
    return data;
  }

  function formatDate(value) {
    if (!value) return '—';
    return new Intl.DateTimeFormat('pl-PL', { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value));
  }

  function tableCell(value) {
    const cell = document.createElement('td');
    cell.textContent = value;
    return cell;
  }

  function renderStats(stats) {
    const items = [
      ['Użytkownicy', stats.users], ['Notatki razem', stats.notes], ['Aktywne', stats.active],
      ['Archiwum', stats.archived], ['Kosz', stats.trash], ['Oczekujące zaproszenia', stats.pendingInvites],
    ];
    document.querySelector('#admin-stats').replaceChildren(...items.map(([label, value]) => {
      const item = document.createElement('div');
      item.className = 'admin-stat';
      const name = document.createElement('span');
      name.textContent = label;
      const count = document.createElement('strong');
      count.textContent = String(value ?? 0);
      item.append(name, count);
      return item;
    }));
  }

  function renderUsers(users) {
    const rows = users.map(user => {
      const row = document.createElement('tr');
      row.append(
        tableCell(user.email),
        tableCell(user.role === 'admin' ? 'Administrator' : 'Użytkownik'),
        tableCell(formatDate(user.createdAt)),
        tableCell(String(user.notes)),
      );
      return row;
    });
    document.querySelector('#admin-users').replaceChildren(...rows);
  }

  function renderInvites(invites) {
    const rows = invites.map(invite => {
      const row = document.createElement('tr');
      const expired = new Date(invite.expiresAt) <= new Date();
      row.append(
        tableCell(formatDate(invite.createdAt)),
        tableCell(formatDate(invite.expiresAt)),
        tableCell(invite.usedAt ? 'Wykorzystane' : expired ? 'Wygasłe' : 'Oczekujące'),
      );
      return row;
    });
    document.querySelector('#admin-invites').replaceChildren(...rows);
  }

  function backupAction(label, title, handler) {
    const button = document.createElement('button');
    button.className = 'button-secondary backup-action';
    button.type = 'button';
    button.textContent = label;
    button.title = title;
    button.setAttribute('aria-label', title);
    button.addEventListener('click', handler);
    return button;
  }

  function renderBackups(backups) {
    const body = document.querySelector('#server-backups');
    if (!backups.length) {
      const row = document.createElement('tr');
      const empty = tableCell('Brak zapisanych backupów.');
      empty.colSpan = 4;
      empty.className = 'admin-empty-cell';
      row.append(empty);
      body.replaceChildren(row);
      return;
    }
    const rows = backups.map(backup => {
      const row = document.createElement('tr');
      const filename = tableCell(backup.filename);
      filename.className = 'backup-filename';
      const size = `${(backup.sizeBytes / 1024 / 1024).toLocaleString('pl-PL', { maximumFractionDigits: 2 })} MB`;
      const actions = document.createElement('td');
      actions.className = 'backup-actions';
      actions.append(
        backupAction('↓', 'Pobierz ten backup', () => downloadBackup(backup.filename)),
        backupAction('↻', 'Przywróć ten backup', () => restoreBackup(backup.filename)),
        backupAction('×', 'Usuń ten backup', () => deleteBackup(backup.filename)),
      );
      row.append(filename, tableCell(formatDate(backup.createdAt)), tableCell(size), actions);
      return row;
    });
    body.replaceChildren(...rows);
  }

  async function refresh() {
    const [summary, backupList] = await Promise.all([
      api('/api/admin/summary'),
      api('/api/admin/backups'),
    ]);
    renderStats(summary.stats);
    renderUsers(summary.users);
    renderInvites(summary.invites);
    renderBackups(backupList.backups);
  }

  function setBackupMessage(message, isError = false) {
    const element = document.querySelector('#backup-message');
    element.textContent = message;
    element.classList.toggle('is-error', isError);
    element.hidden = !message;
  }

  async function downloadBackup(filename) {
    try {
      const response = await fetch(`/api/admin/backups/${encodeURIComponent(filename)}`, { credentials: 'same-origin' });
      if (!response.ok) {
        const result = await response.json().catch(() => ({}));
        throw new Error(result.error || 'Nie udało się pobrać backupu.');
      }
      const url = URL.createObjectURL(await response.blob());
      const link = document.createElement('a');
      link.href = url;
      link.download = filename;
      document.body.append(link);
      link.click();
      link.remove();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (error) {
      setBackupMessage(error.message, true);
    }
  }

  async function restoreBackup(filename) {
    const confirmed = window.confirm(`Przywrócić ${filename}? Zastąpi to wszystkie konta, notatki i zaproszenia. Wszyscy użytkownicy zostaną wylogowani.`);
    if (!confirmed) return;
    try {
      await api(`/api/admin/backups/${encodeURIComponent(filename)}/restore`, { method: 'POST', body: '{}' });
      window.location.replace('/');
    } catch (error) {
      setBackupMessage(error.message, true);
    }
  }

  async function deleteBackup(filename) {
    if (!window.confirm(`Usunąć backup ${filename}? Tej operacji nie można cofnąć.`)) return;
    try {
      await api(`/api/admin/backups/${encodeURIComponent(filename)}`, { method: 'DELETE' });
      setBackupMessage(`Usunięto ${filename}.`);
      await refresh();
    } catch (error) {
      setBackupMessage(error.message, true);
    }
  }

  async function start() {
    try {
      const { user } = await api('/api/session');
      if (!user?.isAdmin) {
        window.location.replace('/');
        return;
      }
      document.querySelector('#admin-account').textContent = user.email;
      await refresh();
    } catch (error) {
      document.querySelector('#admin-message').textContent = error.message;
      if (error.status === 401 || error.status === 403) window.location.replace('/');
    }
  }

  document.querySelector('#create-invite').addEventListener('click', async () => {
    const message = document.querySelector('#invite-message');
    message.hidden = true;
    try {
      const invite = await api('/api/admin/invites', { method: 'POST', body: '{}' });
      document.querySelector('#invite-url').value = invite.url;
      document.querySelector('#invite-expiry').textContent = `Link jest ważny do ${formatDate(invite.expiresAt)}.`;
      document.querySelector('#invite-result').hidden = false;
      await refresh();
    } catch (error) {
      message.textContent = error.message;
      message.classList.add('is-error');
      message.hidden = false;
    }
  });

  document.querySelector('#copy-invite').addEventListener('click', async event => {
    const button = event.currentTarget;
    try {
      await navigator.clipboard.writeText(document.querySelector('#invite-url').value);
      button.textContent = 'Skopiowano';
      window.setTimeout(() => { button.textContent = 'Kopiuj link'; }, 1600);
    } catch {
      const input = document.querySelector('#invite-url');
      input.select();
      document.execCommand('copy');
    }
  });

  document.querySelector('#create-backup').addEventListener('click', async event => {
    const button = event.currentTarget;
    button.disabled = true;
    setBackupMessage('Tworzenie backupu serwera...');
    try {
      const backup = await api('/api/admin/backups', { method: 'POST', body: '{}' });
      setBackupMessage(`Zapisano backup ${backup.filename} na serwerze. Archiwum zawiera hashe haseł; ogranicz do niego dostęp.`);
      await refresh();
    } catch (error) {
      setBackupMessage(error.message, true);
    } finally {
      button.disabled = false;
    }
  });

  document.querySelector('#admin-logout').addEventListener('click', async () => {
    try {
      await api('/api/logout', { method: 'POST', body: '{}' });
      window.location.replace('/');
    } catch (error) {
      document.querySelector('#admin-message').textContent = error.message;
    }
  });

  start();
})();