(() => {
  const t = (key, params) => window.i18n.t(key, params);

  async function api(path, options = {}) {
    const headers = new Headers(options.headers || {});
    if (options.body && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json');
    headers.set('Accept-Language', window.i18n.getLanguage());
    const response = await fetch(path, { ...options, headers, credentials: 'same-origin' });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw Object.assign(new Error(data.error || t('admin.error.server')), { status: response.status });
    return data;
  }

  function formatDate(value) {
    return window.i18n.formatDateTime(value);
  }

  function tableCell(value) {
    const cell = document.createElement('td');
    cell.textContent = value;
    return cell;
  }

  function renderStats(stats) {
    const items = [
      ['admin.stats.users', stats.users], ['admin.stats.notes', stats.notes], ['admin.stats.active', stats.active],
      ['admin.stats.archived', stats.archived], ['admin.stats.trash', stats.trash], ['admin.stats.pendingInvites', stats.pendingInvites],
    ];
    document.querySelector('#admin-stats').replaceChildren(...items.map(([labelKey, value]) => {
      const item = document.createElement('div');
      item.className = 'admin-stat';
      const name = document.createElement('span');
      name.textContent = t(labelKey);
      const count = document.createElement('strong');
      count.textContent = String(value ?? 0);
      item.append(name, count);
      return item;
    }));
  }

  async function deleteUser(userId) {
    if (!confirm(t('admin.users.confirmDelete'))) return;
    try {
      await api(`/api/admin/users/${userId}`, { method: 'DELETE' });
      await refresh();
    } catch (error) {
      alert(error.message);
    }
  }

  function renderUsers(users) {
    const rows = users.map(user => {
      const row = document.createElement('tr');
      const actions = document.createElement('td');
      actions.className = 'admin-table-actions';
      if (user.role !== 'admin') {
        const delBtn = document.createElement('button');
        delBtn.type = 'button';
        delBtn.className = 'action-icon';
        delBtn.textContent = '×';
        delBtn.title = t('admin.users.delete');
        delBtn.addEventListener('click', () => deleteUser(user.id));
        actions.append(delBtn);
      }
      row.append(
        tableCell(user.email),
        tableCell(t(user.role === 'admin' ? 'admin.role.admin' : 'admin.role.user')),
        tableCell(formatDate(user.createdAt)),
        tableCell(String(user.notes)),
        actions
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
        tableCell(t(invite.usedAt ? 'admin.invites.used' : expired ? 'admin.invites.expired' : 'admin.invites.pending')),
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
      const empty = tableCell(t('admin.backups.empty'));
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
      const size = `${window.i18n.formatNumber(backup.sizeBytes / 1024 / 1024, { maximumFractionDigits: 2 })} MB`;
      const actions = document.createElement('td');
      actions.className = 'backup-actions';
      actions.append(
        backupAction('↓', t('admin.backups.download'), () => downloadBackup(backup.filename)),
        backupAction('↻', t('admin.backups.restore'), () => restoreBackup(backup.filename)),
        backupAction('×', t('admin.backups.delete'), () => deleteBackup(backup.filename)),
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
        throw new Error(result.error || t('admin.backups.downloadFailed'));
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
    const confirmed = window.confirm(t('admin.backups.confirmRestore', { filename }));
    if (!confirmed) return;
    try {
      await api(`/api/admin/backups/${encodeURIComponent(filename)}/restore`, { method: 'POST', body: '{}' });
      window.location.replace('/');
    } catch (error) {
      setBackupMessage(error.message, true);
    }
  }

  async function deleteBackup(filename) {
    if (!window.confirm(t('admin.backups.confirmDelete', { filename }))) return;
    try {
      await api(`/api/admin/backups/${encodeURIComponent(filename)}`, { method: 'DELETE' });
      setBackupMessage(t('admin.backups.deleted', { filename }));
      await refresh();
    } catch (error) {
      setBackupMessage(error.message, true);
    }
  }

  let currentUser = null;
  let toastTimeout;

  function showToast(message) {
    const toast = document.querySelector('#toast');
    if (!toast) return;
    toast.textContent = message;
    toast.classList.add('is-visible');
    window.clearTimeout(toastTimeout);
    toastTimeout = window.setTimeout(() => toast.classList.remove('is-visible'), 3200);
  }

  function renderAvatar(user) {
    if (!user) return;
    const initial = (user.email || '?').slice(0, 1).toUpperCase();
    const avatarUrl = user.avatar || '';
    const avatarNode = document.querySelector('#avatar');
    const avatarPreviewNode = document.querySelector('#profile-avatar-preview');

    for (const node of [avatarNode, avatarPreviewNode]) {
      if (!node) continue;
      node.textContent = avatarUrl ? '' : initial;
      node.style.backgroundImage = avatarUrl ? `url("${avatarUrl}")` : '';
      node.classList.toggle('has-image', Boolean(avatarUrl));
    }
    if (avatarNode) {
      avatarNode.title = user.email;
      avatarNode.setAttribute('aria-label', t('topbar.accountAria', { email: user.email }));
    }
    if (avatarPreviewNode) {
      avatarPreviewNode.title = user.email;
    }
  }

  function openProfile() {
    const profileMessage = document.querySelector('#profile-message');
    const avatarMessage = document.querySelector('#avatar-message');
    const passwordForm = document.querySelector('#password-form');
    const profilePanel = document.querySelector('#profile-panel');
    const profileBackdrop = document.querySelector('#profile-backdrop');

    if (profileMessage) {
      profileMessage.hidden = true;
      profileMessage.classList.remove('is-error');
    }
    if (avatarMessage) {
      avatarMessage.hidden = true;
      avatarMessage.classList.remove('is-error');
    }
    if (passwordForm) passwordForm.reset();
    if (profilePanel && profileBackdrop) {
      profilePanel.hidden = false;
      profilePanel.classList.add('is-open');
      profilePanel.setAttribute('aria-hidden', 'false');
      profileBackdrop.hidden = false;
      document.body.style.overflow = 'hidden';
      window.setTimeout(() => document.querySelector('#current-password')?.focus(), 180);
    }
  }

  function closeProfile() {
    const profilePanel = document.querySelector('#profile-panel');
    const profileBackdrop = document.querySelector('#profile-backdrop');
    if (profilePanel && profileBackdrop) {
      profilePanel.classList.remove('is-open');
      profilePanel.setAttribute('aria-hidden', 'true');
      profilePanel.hidden = true;
      profileBackdrop.hidden = true;
      document.body.style.overflow = '';
    }
  }

  const MAX_AVATAR_BYTES = 2 * 1024 * 1024;

  function showAvatarMessage(message, isError) {
    const element = document.querySelector('#avatar-message');
    if (!element) return;
    element.textContent = message;
    element.classList.toggle('is-error', Boolean(isError));
    element.hidden = !message;
  }

  async function saveAvatar(avatar) {
    try {
      const result = await api('/api/account/avatar', {
        method: 'POST',
        body: JSON.stringify({ avatar }),
      });
      if (currentUser) {
        currentUser.avatar = result.avatar;
        renderAvatar(currentUser);
      }
      showAvatarMessage(t(result.avatar ? 'topbar.avatarSaved' : 'topbar.avatarRemoved'), false);
    } catch (error) {
      showAvatarMessage(t('topbar.avatarFailed', { message: error.message }), true);
    }
  }

  async function start() {
    try {
      const { user } = await api('/api/session');
      if (!user?.isAdmin) {
        window.location.replace('/');
        return;
      }
      currentUser = user;
      document.querySelector('#admin-account').textContent = user.email;
      const profileAccount = document.querySelector('#profile-account');
      if (profileAccount) profileAccount.textContent = user.email;

      renderAvatar(user);
      await refresh();
    } catch (error) {
      document.querySelector('#admin-message').textContent = error.message;
      if (error.status === 401 || error.status === 403) window.location.replace('/');
    }
  }

  let currentTarballUrl = null;

  document.querySelector('#check-update').addEventListener('click', async event => {
    const button = event.currentTarget;
    const message = document.querySelector('#update-message');
    const resultDiv = document.querySelector('#update-result');

    button.disabled = true;
    message.hidden = true;
    resultDiv.hidden = true;

    try {
      const result = await api('/api/admin/update/check');
      if (result.updateAvailable) {
        document.querySelector('#update-latest-version').textContent = result.latestVersion;
        currentTarballUrl = result.tarballUrl;
        resultDiv.hidden = false;
      } else {
        message.textContent = t('admin.update.upToDate');
        message.classList.remove('is-error');
        message.hidden = false;
      }
    } catch (error) {
      message.textContent = error.message;
      message.classList.add('is-error');
      message.hidden = false;
    } finally {
      button.disabled = false;
    }
  });

  document.querySelector('#perform-update').addEventListener('click', async event => {
    const button = event.currentTarget;
    const message = document.querySelector('#update-message');

    if (!currentTarballUrl) return;

    button.disabled = true;
    message.hidden = true;
    message.classList.remove('is-error');
    message.textContent = t('admin.update.updating');
    message.hidden = false;

    try {
      await api('/api/admin/update/perform', {
        method: 'POST',
        body: JSON.stringify({ tarballUrl: currentTarballUrl })
      });
      message.textContent = t('admin.update.success');
      // Reload after short delay to show success message
      setTimeout(() => window.location.reload(), 2000);
    } catch (error) {
      message.textContent = error.message;
      message.classList.add('is-error');
      button.disabled = false;
    }
  });

  document.querySelector('#create-invite').addEventListener('click', async () => {
    const message = document.querySelector('#invite-message');
    message.hidden = true;
    try {
      const invite = await api('/api/admin/invites', { method: 'POST', body: '{}' });
      document.querySelector('#invite-url').value = invite.url;
      document.querySelector('#invite-expiry').textContent = t('admin.invites.expiry', { date: formatDate(invite.expiresAt) });
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
      button.textContent = t('admin.invites.copied');
      window.setTimeout(() => { button.textContent = t('admin.invites.copy'); }, 1600);
    } catch {
      const input = document.querySelector('#invite-url');
      input.select();
      document.execCommand('copy');
    }
  });

  document.querySelector('#create-backup').addEventListener('click', async event => {
    const button = event.currentTarget;
    button.disabled = true;
    setBackupMessage(t('admin.backups.creating'));
    try {
      const backup = await api('/api/admin/backups', { method: 'POST', body: '{}' });
      setBackupMessage(t('admin.backups.created', { filename: backup.filename }));
      await refresh();
    } catch (error) {
      setBackupMessage(error.message, true);
    } finally {
      button.disabled = false;
    }
  });

  document.querySelector('#profile-button')?.addEventListener('click', () => {
    const menu = document.querySelector('#settings-menu');
    if (menu) menu.open = false;
    openProfile();
  });
  document.querySelector('#close-profile')?.addEventListener('click', closeProfile);
  document.querySelector('#profile-backdrop')?.addEventListener('click', closeProfile);

  document.querySelector('#password-form')?.addEventListener('submit', async event => {
    event.preventDefault();
    const current = document.querySelector('#current-password').value;
    const next = document.querySelector('#new-password').value;
    const confirmation = document.querySelector('#confirm-password').value;
    const showProfileMessage = (message, isError) => {
      const element = document.querySelector('#profile-message');
      if (!element) return;
      element.textContent = message;
      element.classList.toggle('is-error', Boolean(isError));
      element.hidden = false;
    };
    if (next !== confirmation) {
      showProfileMessage(t('topbar.passwordMismatch'), true);
      return;
    }
    try {
      await api('/api/account/password', {
        method: 'POST',
        body: JSON.stringify({ currentPassword: current, newPassword: next }),
      });
      document.querySelector('#password-form').reset();
      showProfileMessage(t('topbar.passwordChanged'), false);
      showToast(t('topbar.passwordChanged'));
    } catch (error) {
      showProfileMessage(t('topbar.passwordChangeFailed', { message: error.message }), true);
    }
  });

  document.querySelector('#avatar-upload')?.addEventListener('click', () => {
    document.querySelector('#avatar-input')?.click();
  });

  document.querySelector('#avatar-input')?.addEventListener('change', () => {
    const input = document.querySelector('#avatar-input');
    const file = input?.files?.[0];
    if (input) input.value = '';
    if (!file) return;
    if (!file.type.startsWith('image/')) {
      showAvatarMessage(t('topbar.avatarInvalidType'), true);
      return;
    }
    if (file.size > MAX_AVATAR_BYTES) {
      showAvatarMessage(t('topbar.avatarTooLarge'), true);
      return;
    }
    const reader = new FileReader();
    reader.addEventListener('load', () => saveAvatar(reader.result));
    reader.addEventListener('error', () => showAvatarMessage(t('topbar.avatarReadFailed'), true));
    reader.readAsDataURL(file);
  });

  document.querySelector('#avatar-remove')?.addEventListener('click', () => saveAvatar(null));

  document.querySelector('#logout-button').addEventListener('click', async () => {
    try {
      await api('/api/logout', { method: 'POST', body: '{}' });
      window.location.replace('/');
    } catch (error) {
      document.querySelector('#admin-message').textContent = error.message;
    }
  });

  document.addEventListener('click', event => {
    const menu = document.querySelector('#settings-menu');
    if (menu && menu.open && !menu.contains(event.target)) {
      menu.open = false;
    }
  });

  document.addEventListener('keydown', event => {
    if (event.key === 'Escape') {
      const profilePanel = document.querySelector('#profile-panel');
      if (profilePanel && !profilePanel.hidden && profilePanel.classList.contains('is-open')) {
        closeProfile();
        return;
      }
      const menu = document.querySelector('#settings-menu');
      if (menu && menu.open) {
        menu.open = false;
        return;
      }
    }
  });

  window.i18n.onChange(() => {
    renderAvatar(currentUser);
    if (document.querySelector('#admin-account').textContent) refresh().catch(() => {});
  });

  start();
})();