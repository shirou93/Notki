(() => {
  const STORAGE_KEY = 'notki.notes.v1';
  const MIGRATION_KEY = 'notki.server-migrated.v1';
  const COLORS = ['default', 'mint', 'lemon', 'peach', 'lilac', 'sky'];
  const t = (key, params) => window.i18n.t(key, params);
  const pluralText = (key, count) => window.i18n.plural(key, count);
  const VIEW_KEYS = { all: 'view.all', pinned: 'view.pinned', archive: 'view.archive', trash: 'view.trash', shared: 'view.shared' };
  const NAV_KEYS = { all: 'nav.all', pinned: 'nav.pinned', archive: 'nav.archive', trash: 'nav.trash', shared: 'nav.shared' };
  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
  const elements = {
    allCount: $('#count-all'), pinnedCount: $('#count-pinned'), archiveCount: $('#count-archive'), trashCount: $('#count-trash'),
    nav: $$('.nav-item'), breadcrumb: $('#breadcrumb-view'), title: $('#page-title'), countLabel: $('#note-count-label'),
    pinnedLabel: $('#pinned-label'), pinnedGrid: $('#pinned-grid'), otherLabel: $('#other-label'), otherLabelText: $('#other-label-text'),
    grid: $('#notes-grid'), empty: $('#empty-state'), emptyTitle: $('#empty-title'), emptyCopy: $('#empty-copy'),
    footerCount: $('#footer-count'), search: $('#search-input'), panel: $('#editor-panel'), backdrop: $('#editor-backdrop'),
    noteTitle: $('#note-title'), noteBody: $('#note-body'), tags: $('#note-tags'), saveState: $('#save-state'), date: $('#editor-date'),
    words: $('#editor-words'), pin: $('#pin-note'), archive: $('#archive-note'), delete: $('#delete-note'), toast: $('#toast'), themeToggle: $('#theme-toggle'),
    appShell: $('#app-shell'), authView: $('#auth-view'), authHeading: $('#auth-heading'), authDescription: $('#auth-description'), authMessage: $('#auth-message'),
    loginForm: $('#login-form'), registerForm: $('#register-form'), authSwitch: $('#auth-switch'), adminLink: $('#admin-link'), navAdmin: $('#nav-admin'), adminArea: $('#admin-area'), pageHeading: $('.page-heading'), captureWrap: $('.capture-wrap'), notesArea: $('.notes-area'), topbarSearch: $('.search-box'),
    sharedBanner: $('#shared-banner'), sharedTitle: $('#shared-title'), sharedPreview: $('#shared-preview'),
    avatar: $('#avatar'), profilePanel: $('#profile-panel'), profileBackdrop: $('#profile-backdrop'), profileAccount: $('#profile-account'),
    profileMessage: $('#profile-message'), passwordForm: $('#password-form'),
    avatarPreview: $('#profile-avatar-preview'), avatarInput: $('#avatar-input'), avatarMessage: $('#avatar-message'),
    sharedCount: $('#count-shared'), sharePanel: $('#share-panel'), shareBackdrop: $('#share-backdrop'),
    shareForm: $('#share-form'), shareEmail: $('#share-email'), sharePermission: $('#share-permission'),
    shareMessage: $('#share-message'), shareList: $('#share-list'), shareEmpty: $('#share-empty'),
    shareNoteName: $('#share-note-name'), shareDirectory: $('#share-directory'),
  };

  let notes = [];
  let sharedNotes = [];
  const legacyNotes = loadNotes();
  const inviteToken = new URLSearchParams(window.location.search).get('invite');
  let currentUser = null;
  let saveQueue = Promise.resolve();
  let view = 'all';
  let query = '';
  let activeId = null;
  let activeIsNew = false;
  let activeColor = 'default';
  let toastTimeout;
  let saveTimeout;
  let pendingSharedNote = null;
  let returnFocus = null;
  let dragState = null;
  let dragFrame = null;
  let dragPoint = null;
  let skipCardAnimation = false;
  let editorRange = null;
  let shareNoteId = null;
  let shareReturnFocus = null;

  // Aborting every card tween leaves the grid at its settled geometry, so measurements stay stable.
  function settleCards() {
    for (const animation of document.getAnimations()) {
      if (animation.effect?.target?.classList?.contains('note-card')) animation.cancel();
    }
  }

  // Slides the cards between their old and new slots so the reorder reads as motion, not a jump.
  function tweenCards(previousRects, nodes) {
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
    settleCards();
    for (const node of nodes) {
      const before = previousRects.get(node);
      const after = node.getBoundingClientRect();
      if (!before) continue;
      const deltaX = before.left - after.left;
      const deltaY = before.top - after.top;
      if (Math.abs(deltaX) < 0.5 && Math.abs(deltaY) < 0.5) continue;
      node.animate(
        [{ transform: `translate(${deltaX}px, ${deltaY}px)` }, { transform: 'none' }],
        { duration: 220, easing: 'cubic-bezier(.2,.8,.3,1)' },
      );
    }
  }

  // The set of other cards and the dragged card's starting index are captured once, when the drag
  // starts. Re-deriving them from the grid mid-drag would feed the running reorder back into the
  // hit test, so the placeholder would chase its own layout and flip between two slots.
  function captureSlots() {
    const cards = [...dragState.grid.querySelectorAll('.note-card')];
    dragState.others = cards.filter(card => card !== dragState.card);
    dragState.startIndex = cards.indexOf(dragState.card);
    dragState.gapIndex = dragState.startIndex;
  }

  // Maps the pointer to the slot the dragged card should occupy. Slot centres are read from the
  // settled layout, so the placeholder always lands under the pointer; the margin stops it from
  // flipping back and forth while the pointer rests on the seam between two cards.
  function dropSlot(clientX, clientY) {
    const grid = dragState.grid;
    const cards = [...grid.querySelectorAll('.note-card')];
    const singleColumn = getComputedStyle(grid).gridTemplateColumns.trim().split(/\s+/).length === 1;
    const along = singleColumn ? clientY : clientX;
    const cross = singleColumn ? clientX : clientY;
    const centres = cards.map(card => {
      const bounds = card.getBoundingClientRect();
      return {
        along: singleColumn ? bounds.top + bounds.height / 2 : bounds.left + bounds.width / 2,
        cross: singleColumn ? bounds.left + bounds.width / 2 : bounds.top + bounds.height / 2,
      };
    });
    let best = 0;
    let bestDistance = Infinity;
    for (let index = 0; index < centres.length; index += 1) {
      const distance = Math.hypot(along - centres[index].along, cross - centres[index].cross);
      if (distance < bestDistance) {
        bestDistance = distance;
        best = index;
      }
    }
    const current = dragState.gapIndex;
    if (current === null || best === current) return best;
    const currentDistance = Math.hypot(along - centres[current].along, cross - centres[current].cross);
    const margin = 12; // The pointer must clearly favour the new slot before the layout moves.
    return bestDistance + margin < currentDistance ? best : current;
  }

  // Moves the dragged card (now a dashed placeholder) to the slot under the pointer and tweens the rest.
  function updateDropGap(clientX, clientY) {
    settleCards(); // Measure the settled layout, never a tween mid-flight.
    const index = dropSlot(clientX, clientY);
    if (index === dragState.gapIndex) return;
    const nodes = [...dragState.others, dragState.card];
    const previousRects = new Map(nodes.map(node => [node, node.getBoundingClientRect()]));
    dragState.gapIndex = index;
    const order = [...dragState.others];
    order.splice(index, 0, dragState.card); // Keeping the card in the flow keeps the slot at full size.
    dragState.grid.replaceChildren(...order);
    tweenCards(previousRects, order);
  }

  function applyTheme(theme) {
    document.documentElement.dataset.theme = theme === 'dark' ? 'dark' : 'light';
    elements.themeToggle.querySelector('span').textContent = theme === 'dark' ? '☀' : '☾';
    window.notkiTheme.sync();
  }

  async function apiRequest(path, options = {}) {
    const headers = new Headers(options.headers || {});
    if (options.body && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json');
    headers.set('Accept-Language', window.i18n.getLanguage());
    const response = await fetch(path, { cache: 'no-store', ...options, headers, credentials: 'same-origin' });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.error || t('error.server'));
    return payload;
  }

  function showAuth(mode, message = '') {
    elements.authView.hidden = false;
    elements.appShell.hidden = true;
    elements.panel.hidden = true;
    elements.backdrop.hidden = true;
    elements.loginForm.hidden = mode !== 'login';
    elements.registerForm.hidden = mode !== 'register';
    elements.authHeading.firstChild.dataset.i18n = mode === 'register' ? 'auth.heading.register' : 'auth.heading.login';
    elements.authDescription.dataset.i18n = mode === 'register' ? 'auth.description.register' : 'auth.description.login';
    window.i18n.applyTranslations(elements.authView);
    elements.authMessage.textContent = message;
    elements.authMessage.hidden = !message;
    elements.authSwitch.hidden = !inviteToken;
    elements.authSwitch.textContent = t(mode === 'register' ? 'auth.switch.register' : 'auth.switch.login');
    document.body.classList.add('is-auth');
  }

  async function showApp(user) {
    currentUser = user;
    const [response, shared] = await Promise.all([apiRequest('/api/notes'), apiRequest('/api/shared')]);
    notes = response.notes;
    sharedNotes = shared.notes;
    const migratedKey = `${MIGRATION_KEY}.${user.id}`;
    if (!notes.length && legacyNotes.length && !localStorage.getItem(migratedKey)) {
      if (window.confirm(t('auth.migrateConfirm', { count: legacyNotes.length, email: user.email }))) {
        notes = legacyNotes;
        await apiRequest('/api/notes', { method: 'PUT', body: JSON.stringify({ notes }) });
      }
      localStorage.setItem(migratedKey, '1');
    }
    elements.authView.hidden = true;
    elements.appShell.hidden = false;
    elements.panel.hidden = false;
    elements.adminLink.hidden = !user.isAdmin;
    elements.navAdmin.hidden = !user.isAdmin;
    if (user.isAdmin) { document.querySelector('#admin-account').textContent = user.email; }
    elements.avatar.title = user.email;
    elements.avatar.setAttribute('aria-label', t('topbar.accountAria', { email: user.email }));
    elements.profileAccount.textContent = user.email;
    renderAvatar(user);
    document.body.classList.remove('is-auth');
    render();
    readSharedNote();
    applyHashIntent();
  }

    function applyHashIntent() {
    let intent = window.location.pathname === '/admin' ? 'admin' : window.location.hash.replace(/^#/, '');
    if (!intent || intent.startsWith('share=')) return;
    if (intent !== 'admin') window.history.replaceState(null, '', `${window.location.pathname}${window.location.search}`);
    if (intent === 'new') {
      openEditor();
      return;
    }
    if (intent === 'admin' && currentUser && !currentUser.isAdmin) {
      window.history.replaceState(null, '', '/');
      intent = 'all';
    }
    if (VIEW_KEYS[intent] || intent === 'admin') {
      view = intent;
      render();
    }
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
      await apiRequest(`/api/admin/users/${userId}`, { method: 'DELETE' });
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
      empty.style.textAlign = 'center';
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

  async function refreshAdmin() {
    const [summary, backupList] = await Promise.all([
      apiRequest('/api/admin/summary'),
      apiRequest('/api/admin/backups'),
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
      await apiRequest(`/api/admin/backups/${encodeURIComponent(filename)}/restore`, { method: 'POST', body: '{}' });
      window.location.replace('/');
    } catch (error) {
      setBackupMessage(error.message, true);
    }
  }

  async function deleteBackup(filename) {
    if (!window.confirm(t('admin.backups.confirmDelete', { filename }))) return;
    try {
      await apiRequest(`/api/admin/backups/${encodeURIComponent(filename)}`, { method: 'DELETE' });
      setBackupMessage(t('admin.backups.deleted', { filename }));
      await refresh();
    } catch (error) {
      setBackupMessage(error.message, true);
    }
  }

  async function initializeApp() {
    try {
      const { needsSetup } = await apiRequest('/api/setup/status');
      if (needsSetup) {
        window.location.replace('/setup');
        return;
      }
      const { user } = await apiRequest('/api/session');
      if (user) {
        await showApp(user);
        return;
      }
      showAuth(inviteToken ? 'register' : 'login');
    } catch (error) {
      showAuth(inviteToken ? 'register' : 'login', t('auth.connectionFailed', { message: error.message }));
    }
  }

  elements.authSwitch.addEventListener('click', () => {
    showAuth(elements.registerForm.hidden ? 'register' : 'login');
  });
  elements.loginForm.addEventListener('submit', async event => {
    event.preventDefault();
    try {
      const { user } = await apiRequest('/api/login', {
        method: 'POST',
        body: JSON.stringify({ email: $('#login-email').value, password: $('#login-password').value }),
      });
      await showApp(user);
    } catch (error) {
      $('#login-password').value = '';
      showAuth('login', error.message);
    }
  });
  elements.registerForm.addEventListener('submit', async event => {
    event.preventDefault();
    const password = $('#register-password').value;
    if (password !== $('#register-confirm').value) {
      showAuth('register', t('auth.passwordMismatch'));
      return;
    }
    try {
      const { user } = await apiRequest('/api/register', {
        method: 'POST',
        body: JSON.stringify({ email: $('#register-email').value, password, invite: inviteToken }),
      });
      await showApp(user);
    } catch (error) {
      showAuth('register', error.message);
    }
  });
  $('#logout-button').addEventListener('click', async () => {
    try {
      await apiRequest('/api/logout', { method: 'POST', body: '{}' });
      window.location.assign('/');
    } catch (error) {
      showToast(error.message);
    }
  });

  function renderAvatar(user) {
    const initial = user.email.slice(0, 1).toLocaleUpperCase();
    const avatar = user.avatar || '';
    for (const node of [elements.avatar, elements.avatarPreview]) {
      node.textContent = avatar ? '' : initial;
      node.style.backgroundImage = avatar ? `url("${avatar}")` : '';
      node.classList.toggle('has-image', Boolean(avatar));
    }
    elements.avatarPreview.title = user.email;
  }

  function openProfile() {
    elements.profileMessage.hidden = true;
    elements.profileMessage.classList.remove('is-error');
    elements.avatarMessage.hidden = true;
    elements.avatarMessage.classList.remove('is-error');
    elements.passwordForm.reset();
    elements.profilePanel.hidden = false;
    elements.profilePanel.classList.add('is-open');
    elements.profilePanel.setAttribute('aria-hidden', 'false');
    elements.profileBackdrop.hidden = false;
    document.body.style.overflow = 'hidden';
    window.setTimeout(() => $('#current-password').focus(), 180);
  }

  function closeProfile() {
    elements.profilePanel.classList.remove('is-open');
    elements.profilePanel.setAttribute('aria-hidden', 'true');
    elements.profilePanel.hidden = true;
    elements.profileBackdrop.hidden = true;
    document.body.style.overflow = '';
  }

  function showShareMessage(message, isError) {
    elements.shareMessage.textContent = message;
    elements.shareMessage.hidden = !message;
    elements.shareMessage.classList.toggle('is-error', Boolean(isError));
  }

  function renderShareList(shares) {
    elements.shareList.replaceChildren(...shares.map(share => {
      const item = document.createElement('li');
      item.className = 'share-item';
      const avatar = document.createElement('span');
      avatar.className = 'share-avatar';
      avatar.textContent = (share.email || '?').slice(0, 1).toUpperCase();
      if (share.avatar) {
        avatar.style.backgroundImage = `url("${share.avatar}")`;
        avatar.classList.add('has-image');
      }
      const label = document.createElement('span');
      label.className = 'share-email';
      label.textContent = share.email;
      const badge = document.createElement('span');
      badge.className = `share-badge${share.permission === 'write' ? ' is-write' : ''}`;
      badge.textContent = t(share.permission === 'write' ? 'share.writeBadge' : 'share.readOnlyBadge');
      const revoke = document.createElement('button');
      revoke.className = 'share-revoke';
      revoke.type = 'button';
      revoke.textContent = t('share.revoke');
      revoke.addEventListener('click', () => revokeShare(share.userId));
      item.append(avatar, label, badge, revoke);
      return item;
    }));
    elements.shareEmpty.hidden = shares.length !== 0;
  }

  async function loadShares() {
    try {
      const { shares } = await apiRequest(`/api/notes/${encodeURIComponent(shareNoteId)}/shares`);
      renderShareList(shares);
    } catch (error) {
      showShareMessage(t('share.loadFailed'), true);
    }
  }

  async function loadDirectory() {
    try {
      const { users } = await apiRequest('/api/users');
      elements.shareDirectory.replaceChildren(...users.map(user => {
        const option = document.createElement('option');
        option.value = user.email;
        return option;
      }));
    } catch {
      // The directory is only a convenience; typing an address still works.
    }
  }

  async function openShare(noteId) {
    const note = notes.find(item => item.id === noteId);
    if (!note) return;
    shareNoteId = noteId;
    shareReturnFocus = document.activeElement;
    elements.shareNoteName.textContent = note.title || t('editor.untitled');
    elements.shareEmail.value = '';
    elements.sharePermission.value = 'read';
    showShareMessage('');
    renderShareList([]);
    elements.sharePanel.hidden = false;
    elements.sharePanel.classList.add('is-open');
    elements.sharePanel.setAttribute('aria-hidden', 'false');
    elements.shareBackdrop.hidden = false;
    document.body.style.overflow = 'hidden';
    window.setTimeout(() => elements.shareEmail.focus(), 180);
    await Promise.all([loadShares(), loadDirectory()]);
  }

  function closeShare() {
    shareNoteId = null;
    elements.sharePanel.classList.remove('is-open');
    elements.sharePanel.setAttribute('aria-hidden', 'true');
    elements.sharePanel.hidden = true;
    elements.shareBackdrop.hidden = true;
    document.body.style.overflow = '';
    if (shareReturnFocus && typeof shareReturnFocus.focus === 'function') shareReturnFocus.focus();
    shareReturnFocus = null;
  }

  async function submitShare(event) {
    event.preventDefault();
    if (!shareNoteId) return;
    const email = elements.shareEmail.value.trim();
    if (!email) return;
    try {
      const { shares } = await apiRequest(`/api/notes/${encodeURIComponent(shareNoteId)}/shares`, {
        method: 'POST',
        body: JSON.stringify({ email, permission: elements.sharePermission.value }),
      });
      renderShareList(shares);
      elements.shareEmail.value = '';
      showShareMessage(t('share.granted'));
    } catch (error) {
      showShareMessage(t('share.failed', { message: error.message }), true);
    }
  }

  async function revokeShare(userId) {
    if (!shareNoteId) return;
    try {
      const { shares } = await apiRequest(`/api/notes/${encodeURIComponent(shareNoteId)}/shares/${userId}`, { method: 'DELETE' });
      renderShareList(shares);
      showShareMessage(t('share.revoked'));
    } catch (error) {
      showShareMessage(t('share.revokeFailed', { message: error.message }), true);
    }
  }

  $('#profile-button').addEventListener('click', () => {
    $('#settings-menu').open = false;
    openProfile();
  });
  $('#close-profile').addEventListener('click', closeProfile);
  elements.profileBackdrop.addEventListener('click', closeProfile);

  elements.passwordForm.addEventListener('submit', async event => {
    event.preventDefault();
    const current = $('#current-password').value;
    const next = $('#new-password').value;
    const confirmation = $('#confirm-password').value;
    const showProfileMessage = (message, isError) => {
      elements.profileMessage.textContent = message;
      elements.profileMessage.classList.toggle('is-error', isError);
      elements.profileMessage.hidden = false;
    };
    if (next !== confirmation) {
      showProfileMessage(t('topbar.passwordMismatch'), true);
      return;
    }
    try {
      await apiRequest('/api/account/password', {
        method: 'POST',
        body: JSON.stringify({ currentPassword: current, newPassword: next }),
      });
      elements.passwordForm.reset();
      showProfileMessage(t('topbar.passwordChanged'), false);
      showToast(t('topbar.passwordChanged'));
    } catch (error) {
      showProfileMessage(t('topbar.passwordChangeFailed', { message: error.message }), true);
    }
  });

  const MAX_AVATAR_BYTES = 2 * 1024 * 1024;

  function showAvatarMessage(message, isError) {
    elements.avatarMessage.textContent = message;
    elements.avatarMessage.classList.toggle('is-error', isError);
    elements.avatarMessage.hidden = false;
  }

  async function saveAvatar(avatar) {
    try {
      const result = await apiRequest('/api/account/avatar', {
        method: 'POST',
        body: JSON.stringify({ avatar }),
      });
      currentUser.avatar = result.avatar;
      renderAvatar(currentUser);
      showAvatarMessage(t(result.avatar ? 'topbar.avatarSaved' : 'topbar.avatarRemoved'), false);
    } catch (error) {
      showAvatarMessage(t('topbar.avatarFailed', { message: error.message }), true);
    }
  }

  $('#avatar-upload').addEventListener('click', () => elements.avatarInput.click());

  elements.avatarInput.addEventListener('change', () => {
    const file = elements.avatarInput.files[0];
    elements.avatarInput.value = '';
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

  $('#avatar-remove').addEventListener('click', () => saveAvatar(null));

  function moveToFront(note) {
    const index = notes.indexOf(note);
    if (index > 0) {
      notes.splice(index, 1);
      notes.unshift(note);
    }
      // Update order to maintain manual sort
      note.order = Date.now();
    }

  function sanitizeRichHtml(html) {
    const template = document.createElement('template');
    template.innerHTML = String(html || '');
    const allowedTags = new Set(['A', 'B', 'BLOCKQUOTE', 'BR', 'DIV', 'EM', 'H2', 'H3', 'I', 'INPUT', 'LI', 'OL', 'P', 'S', 'SPAN', 'STRONG', 'U', 'UL']);
    const output = document.createElement('div');
    const copySafeNode = (parent, node) => {
      if (node.nodeType === Node.TEXT_NODE) {
        parent.append(document.createTextNode(node.nodeValue || ''));
        return;
      }
      if (node.nodeType !== Node.ELEMENT_NODE) return;
      if (!allowedTags.has(node.tagName)) {
        [...node.childNodes].forEach(child => copySafeNode(parent, child));
        return;
      }
      if (node.tagName === 'INPUT') {
        if (node.type !== 'checkbox') return;
        const checkbox = document.createElement('input');
        checkbox.type = 'checkbox';
        checkbox.className = 'task-checkbox';
        if (node.checked || node.hasAttribute('checked')) checkbox.setAttribute('checked', '');
        checkbox.contentEditable = 'false';
        checkbox.setAttribute('aria-label', t('editor.checkboxAria'));
        parent.append(checkbox);
        return;
      }
      const safeNode = document.createElement(node.tagName.toLowerCase());
      if (node.tagName === 'UL' && node.classList.contains('task-list')) {
        safeNode.className = node.classList.contains('task-list-completed') ? 'task-list task-list-completed' : 'task-list';
      }
      if (node.tagName === 'P' && node.classList.contains('task-group-label')) {
        safeNode.className = 'task-group-label';
        safeNode.contentEditable = 'false';
      }
      if (node.tagName === 'SPAN' && (node.classList.contains('task-text')
          || (node.parentElement?.matches('li') && node.parentElement.querySelector('input[type="checkbox"]')))) {
        safeNode.className = 'task-text';
        safeNode.tabIndex = 0;
      }
      if (node.tagName === 'A') {
        try {
          const url = new URL(node.getAttribute('href'), window.location.href);
          if (['http:', 'https:', 'mailto:'].includes(url.protocol)) safeNode.setAttribute('href', url.href);
        } catch {
          safeNode.removeAttribute('href');
        }
      }
      [...node.childNodes].forEach(child => copySafeNode(safeNode, child));
      parent.append(safeNode);
    };
    [...template.content.childNodes].forEach(child => copySafeNode(output, child));
    return output.innerHTML;
  }

  function plainTextToHtml(text) {
    const output = document.createElement('div');
    String(text || '').split(/\r\n|\r|\n/).forEach((line) => {
      const div = document.createElement('div');
      if (line) {
        div.append(document.createTextNode(line));
      } else {
        div.append(document.createElement('br'));
      }
      output.append(div);
    });
    return output.innerHTML;
  }

  function noteText(note) {
    if (note.bodyFormat !== 1) return note.body || '';
    const output = document.createElement('div');
    output.innerHTML = sanitizeRichHtml(note.body);
    return (output.innerText || output.textContent || '').replace(/\n{3,}/g, '\n\n');
  }

  function serializedEditorBody() {
    const checkedState = [...elements.noteBody.querySelectorAll('input[type="checkbox"]')].map(input => input.checked);
    const clone = elements.noteBody.cloneNode(true);
    [...clone.querySelectorAll('input[type="checkbox"]')].forEach((input, index) => {
      if (checkedState[index]) input.setAttribute('checked', '');
      else input.removeAttribute('checked');
    });
    return sanitizeRichHtml(clone.innerHTML);
  }

  function normalizeTaskText(value) {
    return String(value || '').replace(/[\u200b\u00a0]/g, ' ').replace(/\s+/g, ' ').trim().toLocaleLowerCase(window.i18n.getLanguage());
  }

  function normalizeChecklistItemMarkup(root = elements.noteBody) {
    root.querySelectorAll('ul.task-list > li').forEach(item => {
      const checkbox = item.querySelector(':scope > input.task-checkbox');
      if (!checkbox) return;
      let text = item.querySelector(':scope > .task-text');
      const strayNodes = [...item.childNodes].filter(node => node !== checkbox && node !== text);
      if (!strayNodes.length && text) return;
      const strayText = strayNodes.map(node => node.textContent.trim()).filter(Boolean).join(' ');
      if (!text) {
        text = document.createElement('span');
        text.className = 'task-text';
      }
      if (strayText) text.textContent = [strayText, text.textContent.trim()].filter(Boolean).join(' ');
      strayNodes.forEach(node => node.remove());
      checkbox.after(text);
      text.tabIndex = 0;
    });
  }

  function taskTextAtSelection() {
    const selection = window.getSelection();
    const node = selection?.focusNode || selection?.anchorNode;
    const element = node?.nodeType === Node.ELEMENT_NODE ? node : node?.parentElement;
    return element?.closest('.task-text') || null;
  }

  function placeTaskCaretFromPointer(event) {
    let range = document.caretRangeFromPoint?.(event.clientX, event.clientY);
    if (!range && document.caretPositionFromPoint) {
      const position = document.caretPositionFromPoint(event.clientX, event.clientY);
      if (position) {
        range = document.createRange();
        range.setStart(position.offsetNode, position.offset);
        range.collapse(true);
      }
    }
    if (!range) return;
    const node = range.startContainer;
    const element = node?.nodeType === Node.ELEMENT_NODE ? node : node?.parentElement;
    if (event.target.closest?.('input.task-checkbox')) return;
    const taskText = event.target.closest?.('.task-text')
      || element?.closest('.task-text')
      || (event.target.closest?.('li') || element?.closest('li'))?.querySelector(':scope > .task-text');
    if (!taskText) return;
    if (!taskText.contains(range.startContainer)) {
      const bounds = taskText.getBoundingClientRect();
      range = document.createRange();
      range.selectNodeContents(taskText);
      range.collapse(event.clientX < bounds.left + bounds.width / 2);
    }
    event.preventDefault();
    elements.noteBody.focus();
    const selection = window.getSelection();
    selection.removeAllRanges();
    selection.addRange(range);
    rememberEditorRange();
  }

  function normalizeChecklistGroups(root = elements.noteBody) {
    normalizeChecklistItemMarkup(root);
    root.querySelectorAll('ul.task-list:not(.task-list-completed)').forEach(activeList => {
      const oldLabel = activeList.nextElementSibling?.matches('p.task-group-label') ? activeList.nextElementSibling : null;
      const oldCompletedList = oldLabel?.nextElementSibling?.matches('ul.task-list.task-list-completed')
        ? oldLabel.nextElementSibling
        : null;
      const allItems = [
        ...activeList.querySelectorAll(':scope > li'),
        ...(oldCompletedList ? oldCompletedList.querySelectorAll(':scope > li') : []),
      ].filter(item => item.querySelector('input.task-checkbox'));
      const activeItems = allItems.filter(item => !item.querySelector('input.task-checkbox').checked);
      const completedItems = allItems.filter(item => item.querySelector('input.task-checkbox').checked);
      const currentActiveItems = [...activeList.querySelectorAll(':scope > li')];
      if (currentActiveItems.length !== activeItems.length
          || currentActiveItems.some((item, index) => item !== activeItems[index])) {
        activeList.replaceChildren(...activeItems);
      }

      if (!completedItems.length) {
        oldLabel?.remove();
        oldCompletedList?.remove();
        return;
      }

      const label = oldLabel || document.createElement('p');
      label.className = 'task-group-label';
      label.contentEditable = 'false';
      label.textContent = t('editor.taskGroup');
      const completedList = oldCompletedList || document.createElement('ul');
      completedList.className = 'task-list task-list-completed';
      const currentCompletedItems = [...completedList.querySelectorAll(':scope > li')];
      if (currentCompletedItems.length !== completedItems.length
          || currentCompletedItems.some((item, index) => item !== completedItems[index])) {
        completedList.replaceChildren(...completedItems);
      }
      if (activeList.nextElementSibling !== label) activeList.after(label);
      if (label.nextElementSibling !== completedList) label.after(completedList);
    });
  }

  function updateCompletedTaskSuggestions(taskText) {
    const suggestions = $('#task-restore-suggestions');
    suggestions.replaceChildren();
    if (!taskText || taskText.closest('.task-list-completed')) {
      suggestions.hidden = true;
      return;
    }
    const query = normalizeTaskText(taskText.textContent);
    if (query.length < 2) {
      suggestions.hidden = true;
      return;
    }
    const matches = [...elements.noteBody.querySelectorAll('.task-list-completed > li')]
      .map(item => ({ item, text: item.querySelector('.task-text') }))
      .filter(({ text }) => text && normalizeTaskText(text.textContent).startsWith(query));
    if (!matches.length) {
      suggestions.hidden = true;
      return;
    }

    const message = document.createElement('span');
    message.className = 'task-restore-message';
    message.textContent = t('editor.taskAlreadyDone');
    suggestions.append(message);
    matches.forEach(({ item, text }) => {
      const button = document.createElement('button');
      button.className = 'task-restore-option';
      button.type = 'button';
      button.textContent = t('editor.taskRestore', { title: text.textContent.trim() });
      button.addEventListener('click', () => {
        const currentItem = taskText.closest('li');
        if (currentItem && currentItem !== item) currentItem.remove();
        item.querySelector('input.task-checkbox').checked = false;
        normalizeChecklistGroups();
        suggestions.hidden = true;
        placeEditorCaret(item.querySelector('.task-text'));
        updateWordCount();
        scheduleSave();
      });
      suggestions.append(button);
    });
    suggestions.hidden = false;
  }

  function rememberEditorRange() {
    const selection = window.getSelection();
    if (!selection?.rangeCount || !elements.noteBody.contains(selection.anchorNode) || !elements.noteBody.contains(selection.focusNode)) return;
    editorRange = selection.getRangeAt(0).cloneRange();
    updateFormatToolbar();
    updateCompletedTaskSuggestions(taskTextAtSelection());
  }

  function restoreEditorRange() {
    elements.noteBody.focus();
    if (!editorRange || !elements.noteBody.contains(editorRange.commonAncestorContainer)) return;
    const selection = window.getSelection();
    selection.removeAllRanges();
    selection.addRange(editorRange);
  }

  function updateFormatToolbar() {
    const selection = window.getSelection();
    if (!selection?.anchorNode || !elements.noteBody.contains(selection.anchorNode)) return;
    $$('#format-toolbar [data-command]').forEach(button => {
      const command = button.dataset.command;
      const active = ['bold', 'italic', 'underline', 'insertUnorderedList', 'insertOrderedList'].includes(command) && document.queryCommandState(command);
      button.classList.toggle('is-active', active);
      button.setAttribute('aria-pressed', String(active));
    });
  }

  function createChecklistItem() {
    const item = document.createElement('li');
    const checkbox = document.createElement('input');
    checkbox.type = 'checkbox';
    checkbox.className = 'task-checkbox';
    checkbox.contentEditable = 'false';
    checkbox.setAttribute('aria-label', t('editor.checkboxAria'));

    const content = document.createElement('span');
    content.className = 'task-text';
    content.tabIndex = 0;
    content.textContent = '\u00A0';
    item.append(checkbox, content);
    return item;
  }

  function removeChecklistItem(item) {
    const list = item.closest('ul.task-list');
    const previousText = item.previousElementSibling?.querySelector('.task-text');
    const nextText = item.nextElementSibling?.querySelector('.task-text');
    const wasCompleted = list.classList.contains('task-list-completed');
    const parent = list.parentElement;
    const afterList = list.nextSibling;
    item.remove();
    normalizeChecklistGroups();

    if (previousText?.isConnected) {
      placeEditorCaret(previousText, true);
      return;
    }
    if (nextText?.isConnected) {
      placeEditorCaret(nextText);
      return;
    }

    const activeList = elements.noteBody.querySelector('ul.task-list:not(.task-list-completed)');
    const completedList = elements.noteBody.querySelector('ul.task-list-completed');
    if (activeList && !activeList.children.length && !completedList) activeList.remove();
    const paragraph = document.createElement('div');
    paragraph.append(document.createElement('br'));
    if (activeList?.isConnected && completedList) activeList.after(paragraph);
    else if (parent === elements.noteBody) elements.noteBody.insertBefore(paragraph, afterList?.isConnected ? afterList : null);
    else parent.after(paragraph);
    if (wasCompleted) normalizeChecklistGroups();
    placeEditorCaret(paragraph);
  }

  function placeEditorCaret(container, atEnd = false) {
    if (!container || !container.nodeType) return;

    const selection = window.getSelection();
    if (!selection) return;

    let target = container;
    if (container.nodeType === Node.ELEMENT_NODE) {
      if (container.tagName === 'DIV' && !container.firstChild) {
        container.append(document.createElement('br'));
      }

      if (container.tagName === 'SPAN' && !container.textContent.trim()) {
        container.textContent = '\u00A0';
      }

      if (container.firstChild && container.firstChild.nodeName === 'BR') {
        const emptyText = document.createTextNode('\u00A0');
        container.firstChild.replaceWith(emptyText);
        target = emptyText;
      } else if (container.firstChild && container.firstChild.nodeType === Node.TEXT_NODE) {
        target = container.firstChild;
      } else if (!container.childNodes.length) {
        const emptyText = document.createTextNode('\u00A0');
        container.appendChild(emptyText);
        target = emptyText;
      }

      (container.matches?.('.task-text') ? elements.noteBody : container).focus();
    }

    const range = document.createRange();
    if (target.nodeType === Node.TEXT_NODE) {
      range.setStart(target, atEnd ? target.length : 0);
      range.collapse(true);
    } else {
      range.selectNodeContents(target);
      range.collapse(!atEnd);
    }

    selection.removeAllRanges();
    selection.addRange(range);
    rememberEditorRange();
  }

  function clearDragMarkers() {
    if (!dragState) return;
    dragState.card.classList.remove('is-dragging');
    dragState.preview?.remove();
    document.body.classList.remove('is-dragging-note');
    if (dragFrame) {
      cancelAnimationFrame(dragFrame);
      dragFrame = null;
    }
    dragPoint = null;
  }

  function finishNoteDrag(event, commit) {
    if (!dragState || event.pointerId !== dragState.pointerId) return;
    const { active, noteId, gapIndex, startIndex } = dragState;
    const moved = active && gapIndex !== startIndex;
    const neighbour = moved ? dropNeighbour(gapIndex) : null;
    // The grid is still showing the placeholder layout, so any drop needs a repaint.
    const reorderPending = active && gapIndex !== null;
    clearDragMarkers();
    dragState = null;
    if (commit && neighbour) {
      skipCardAnimation = true; // The cards are already on screen; only the drop should animate.
      moveNote(noteId, neighbour.targetId, neighbour.after);
      skipCardAnimation = false;
    } else if (reorderPending) {
      render();
    }
  }

  // Translates the placeholder index into the neighbour the note should be placed against.
  function dropNeighbour(gapIndex) {
    const others = dragState.others;
    const before = others[gapIndex - 1];
    const after = others[gapIndex];
    if (after) return { targetId: after.dataset.id, after: false };
    if (before) return { targetId: before.dataset.id, after: true };
    return null;
  }

  function trackNoteDrag(event) {
    if (!dragState || event.pointerId !== dragState.pointerId) return;
    if (!dragState.active) {
      if (Math.hypot(event.clientX - dragState.startX, event.clientY - dragState.startY) < 6) return;
      event.preventDefault();
      dragState.active = true;
      dragState.card.classList.add('is-dragging');
      document.body.classList.add('is-dragging-note');
      const note = notes.find(item => item.id === dragState.noteId);
      const preview = document.createElement('div');
      preview.className = 'note-drag-preview';
      if (note && COLORS.includes(note.color)) preview.classList.add(`color-${note.color}`);
      else preview.classList.add('color-default');
      preview.setAttribute('aria-hidden', 'true');
      const title = document.createElement('strong');
      title.textContent = note?.title || t('editor.untitled');
      const body = document.createElement('span');
      body.className = 'card-body';

      if (note && note.bodyFormat === 1 && note.body) {
        body.innerHTML = sanitizeRichHtml(note.body);
      } else {
        body.textContent = (note ? noteText(note) : '') || t('editor.emptyNote');
      }
      preview.append(title, body);
      document.body.append(preview);
      dragState.preview = preview;
      captureSlots();
    }
    event.preventDefault();
    dragPoint = { x: event.clientX, y: event.clientY };
    if (dragFrame) return;
    dragFrame = requestAnimationFrame(() => {
      dragFrame = null;
      if (!dragState || !dragPoint) return;
      const { x, y } = dragPoint;
      const previewOffset = y > 115 ? -100 : 16;
      dragState.preview.style.transform = `translate3d(${x + 16}px, ${y + previewOffset}px, 0)`;
      updateDropGap(x, y);
    });
  }

  document.addEventListener('pointermove', trackNoteDrag);
  document.addEventListener('pointerup', event => finishNoteDrag(event, true));
  document.addEventListener('pointercancel', event => finishNoteDrag(event, false));

  function loadNotes() {
    try {
      const stored = JSON.parse(localStorage.getItem(STORAGE_KEY) || '[]');
      if (!Array.isArray(stored)) return [];
      const valid = stored.filter(note => note && typeof note.id === 'string');
        // Ensure all notes have an order property for consistent sorting
        valid.forEach(note => {
          if (!Number.isFinite(note.order)) {
            note.order = Date.parse(note.updatedAt) || Date.now();
          }
        });
        return valid.sort((a, b) => b.order - a.order);
      } catch {
        return [];
      }
    }

  function persist() {
    notes.forEach((note, index) => { note.order = notes.length - index; });
    if (!currentUser) return;
    const snapshot = JSON.stringify({ notes });
    saveQueue = saveQueue.catch(() => {}).then(() => apiRequest('/api/notes', { method: 'PUT', body: snapshot }));
    saveQueue.catch(error => showToast(t('editor.saveFailed', { message: error.message })));
  }

  function moveNote(noteId, targetId, after = false) {
    if (noteId === targetId) return;
    const sourceIndex = notes.findIndex(note => note.id === noteId);
    const target = notes.find(note => note.id === targetId);
    if (sourceIndex < 0 || !target) return;
    const [source] = notes.splice(sourceIndex, 1);
      // Preserve pinned status when moving in 'all' view
      if (view === 'all' && !query) source.pinned = target.pinned;
      const targetIndex = notes.findIndex(note => note.id === targetId);
      notes.splice(targetIndex + Number(after), 0, source);
      persist();
      render();
    }

  function createNote(data = {}) {
    const now = new Date().toISOString();
    return {
      id: crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random().toString(36).slice(2)}`,
      title: data.title || '',
      body: data.body || '',
      bodyFormat: data.bodyFormat === 1 ? 1 : 0,
      color: COLORS.includes(data.color) ? data.color : 'default',
      tags: Array.isArray(data.tags) ? [...new Set(data.tags.map(tag => String(tag).trim().toLowerCase()).filter(Boolean))] : [],
      pinned: false,
      archived: false,
      deleted: false,
      createdAt: now,
      updatedAt: now,
        order: Date.now(),
      };
    }

  function isActive(note) {
    return !note.archived && !note.deleted;
  }

  function filteredNotes() {
    if (view === 'shared') {
      const matches = sharedNotes.filter(note => {
        if (!query) return true;
        const searchable = `${note.title} ${noteText(note)} ${(note.tags || []).join(' ')} ${note.ownerEmail || ''}`.toLocaleLowerCase();
        return searchable.includes(query.toLocaleLowerCase());
      });
      return matches.sort((a, b) => Date.parse(b.updatedAt) - Date.parse(a.updatedAt));
    }
    return notes.filter(note => {
      if (view === 'all' && !isActive(note)) return false;
      if (view === 'pinned' && (!isActive(note) || !note.pinned)) return false;
      if (view === 'archive' && (!note.archived || note.deleted)) return false;
      if (view === 'trash' && !note.deleted) return false;
      if (!query) return true;
      const searchable = `${note.title} ${noteText(note)} ${(note.tags || []).join(' ')}`.toLocaleLowerCase();
      return searchable.includes(query.toLocaleLowerCase());
      }).sort((a, b) => {
        // In 'all' view without search, sort by pinned first, then by manual order
        if (view === 'all' && !query) {
          if (a.pinned !== b.pinned) return Number(b.pinned) - Number(a.pinned);
          return b.order - a.order;
        }
        // In other views or with search, maintain manual order
        return b.order - a.order;
      });
    }

  function render() {
    const active = notes.filter(isActive);
    const pinned = active.filter(note => note.pinned).length;
    elements.allCount.textContent = String(active.length);
    elements.pinnedCount.textContent = String(pinned);
    elements.archiveCount.textContent = String(notes.filter(note => note.archived && !note.deleted).length);
    elements.trashCount.textContent = String(notes.filter(note => note.deleted).length);
    elements.sharedCount.textContent = String(sharedNotes.length);
    elements.nav.forEach(button => button.classList.toggle('is-active', button.dataset.view === view));
    elements.navAdmin.classList.toggle('is-active', view === 'admin');

    if (view === 'admin') {
      elements.pageHeading.hidden = true;
      elements.captureWrap.hidden = true;
      elements.notesArea.hidden = true;
      elements.topbarSearch.hidden = true;
      elements.adminArea.hidden = false;
      elements.breadcrumb.textContent = t('nav.adminPanel');
      refreshAdmin().catch(() => {});
      window.history.pushState(null, '', '/admin');
    } else {
      elements.pageHeading.hidden = false;
      elements.captureWrap.hidden = false;
      elements.notesArea.hidden = false;
      elements.topbarSearch.hidden = false;
      elements.adminArea.hidden = true;
      elements.breadcrumb.textContent = t(NAV_KEYS[view]);
      if (window.location.pathname === '/admin') {
         window.history.pushState(null, '', '/');
      }
      elements.title.replaceChildren(
        document.createTextNode(t(VIEW_KEYS[view])),
        Object.assign(document.createElement('span'), { className: 'heading-period', textContent: '.' }),
      );

      const visible = filteredNotes();
      const splitPinned = view === 'all' && !query;
      const pinnedItems = splitPinned ? visible.filter(note => note.pinned) : [];
      const regularItems = splitPinned ? visible.filter(note => !note.pinned) : visible;
      elements.pinnedGrid.replaceChildren(...pinnedItems.map(makeCard));
      elements.grid.replaceChildren(...regularItems.map(makeCard));
      elements.pinnedLabel.hidden = pinnedItems.length === 0;
      elements.otherLabel.hidden = pinnedItems.length === 0 || regularItems.length === 0;
      elements.otherLabelText.textContent = t('section.other');
      elements.empty.hidden = visible.length !== 0;
      elements.countLabel.textContent = query
        ? t('count.searchResults', { count: visible.length })
        : `${visible.length} ${pluralText(view === 'shared' ? 'count.sharedLabel' : 'count.notesLabel', visible.length)}`;
      elements.footerCount.textContent = `${visible.length} ${pluralText('footer.count', visible.length)}`;
      updateEmptyState();
      if (activeId) {
        const current = notes.find(note => note.id === activeId) || sharedNotes.find(note => note.id === activeId);
        if (current) updateEditorActions(current);
      }
    }
  }

  function makeCard(note) {
    const card = $('#note-template').content.firstElementChild.cloneNode(true);
    card.dataset.id = note.id;
    card.classList.add(`color-${COLORS.includes(note.color) ? note.color : 'default'}`);
    if (skipCardAnimation) card.style.animation = 'none';
    const shared = Boolean(note.ownerEmail);
    const readOnly = shared && note.permission !== 'write';
    if (shared) card.classList.add('is-shared');
    if (readOnly) card.classList.add('is-read-only');
    $('.card-date', card).textContent = window.i18n.formatDate(note.updatedAt);
    $('.card-title', card).textContent = note.title || t('editor.untitled');
    const cardBody = $('.card-body', card);
    if (note.bodyFormat === 1 && note.body) {
      cardBody.innerHTML = sanitizeRichHtml(note.body);
    } else {
      cardBody.textContent = noteText(note) || t('editor.emptyNote');
    }
    const pin = $('.card-pin', card);
    pin.classList.toggle('is-pinned', note.pinned);
    pin.setAttribute('aria-label', t(note.pinned ? 'editor.unpin' : 'editor.pin'));
    pin.title = t(note.pinned ? 'editor.unpinTitle' : 'editor.pinTitle');
    pin.addEventListener('click', event => {
      event.stopPropagation();
      note.pinned = !note.pinned;
      note.updatedAt = new Date().toISOString();
      moveToFront(note);
      persist();
      render();
    });
    const dragHandle = $('.card-drag', card);
    dragHandle.setAttribute('aria-label', t('card.drag'));
    dragHandle.title = t('card.dragTitle');
    dragHandle.addEventListener('click', event => event.stopPropagation());
    dragHandle.addEventListener('pointerdown', event => {
      if (event.button !== 0) return;
      event.preventDefault();
      dragState = { noteId: note.id, card, grid: card.parentElement, pointerId: event.pointerId, startX: event.clientX, startY: event.clientY, active: false, gapIndex: null, others: [], startIndex: 0 };
    });
    dragHandle.addEventListener('keydown', event => {
      const step = ['ArrowUp', 'ArrowLeft'].includes(event.key) ? -1 : ['ArrowDown', 'ArrowRight'].includes(event.key) ? 1 : 0;
      if (!step) return;
      event.preventDefault();
      event.stopPropagation();
      const cards = [...card.parentElement.querySelectorAll('.note-card')];
      const target = cards[cards.indexOf(card) + step];
      if (target) {
        moveNote(note.id, target.dataset.id, step > 0);
        const nextHandle = [...document.querySelectorAll('.card-drag')].find(button => button.closest('.note-card')?.dataset.id === note.id);
        nextHandle?.focus();
      }
    });
    if (shared) {
      // A recipient cannot re-share or reorder someone else's note.
      dragHandle.hidden = true;
      pin.hidden = true;
      const badge = document.createElement('span');
      badge.className = `card-owner${readOnly ? ' is-read-only' : ''}`;
      badge.textContent = readOnly ? t('share.readOnlyBadge') : t('share.writeBadge');
      badge.title = t('share.ownerLabel', { email: note.ownerEmail });
      $('.card-tags', card).append(badge);
    }
    const tags = $('.card-tags', card);
    (note.tags || []).slice(0, 3).forEach(tag => {
      const label = document.createElement('span');
      label.className = 'card-tag';
      label.textContent = tag;
      tags.append(label);
    });
    card.addEventListener('click', event => {
      const clickedCheckbox = event.target.closest('input[type="checkbox"], .task-checkbox');
      if (clickedCheckbox) return;
      if (event.target.closest('button')) return;
      if (event.target.closest('.card-drag, .card-pin')) return;
      openEditor(note.id);
    });

    card.addEventListener('change', event => {
      if (event.target.matches('input[type="checkbox"]')) {
        event.stopPropagation();
        const wrapper = document.createElement('div');
        wrapper.innerHTML = sanitizeRichHtml(note.body);
        const checkboxes = [...wrapper.querySelectorAll('input[type="checkbox"]')];
        const cardCheckboxes = [...card.querySelectorAll('input[type="checkbox"]')];
        const index = cardCheckboxes.indexOf(event.target);
        if (index > -1 && checkboxes[index]) {
          if (event.target.checked) checkboxes[index].setAttribute('checked', '');
          else checkboxes[index].removeAttribute('checked');
          normalizeChecklistGroups(wrapper);
          note.body = sanitizeRichHtml(wrapper.innerHTML);
          note.updatedAt = new Date().toISOString();
          if (shared && !readOnly) {
            persistShared(note);
          } else {
            persist();
          }
          // Do not re-render immediately to avoid losing focus/layout jumps while clicking,
          // except if we want the group to re-order instantly on the card.
          // For now, re-render to reflect the completed state visually exactly.
          render();
        }
      }
    });
    return card;
  }

  function updateEmptyState() {
    const prefix = query ? 'search' : view;
    elements.emptyTitle.textContent = t(`empty.${prefix}.title`);
    elements.emptyCopy.textContent = t(`empty.${prefix}.copy`);
    $('#empty-create').hidden = view !== 'all' || Boolean(query);
  }

  function openEditor(id = null) {
    if (!currentUser) return;
    const existing = notes.find(note => note.id === id) || sharedNotes.find(note => note.id === id);
    if (!existing && view === 'trash') return;
    const note = existing || createNote();
    activeIsNew = !existing;
    if (!existing) {
      notes.unshift(note);
    }
    activeId = note.id;
    activeColor = note.color;
    returnFocus = document.activeElement;
    elements.noteTitle.value = note.title;
    editorRange = null;
    elements.noteBody.innerHTML = note.bodyFormat === 1 ? sanitizeRichHtml(note.body) : plainTextToHtml(note.body);
    normalizeChecklistGroups();
    $('#task-restore-suggestions').replaceChildren();
    $('#task-restore-suggestions').hidden = true;
    elements.tags.value = (note.tags || []).join(', ');
    elements.date.textContent = t('editor.created', { date: window.i18n.formatFullDate(note.createdAt) });
    updateWordCount();
    updateEditorActions(note);
    setColor(note.color);
    elements.panel.classList.add('is-open');
    elements.panel.setAttribute('aria-hidden', 'false');
    elements.backdrop.hidden = false;
    document.body.style.overflow = 'hidden';
    window.setTimeout(() => elements.noteTitle.focus(), 180);
    render();
  }

  function closeEditor() {
    if (!activeId) return;
    window.clearTimeout(saveTimeout);
    if (activeIsNew && !hasEditorContent()) {
      notes = notes.filter(note => note.id !== activeId);
      persist();
    } else {
      saveEditor();
    }
    activeId = null;
    activeIsNew = false;
    elements.panel.classList.remove('is-open');
    elements.panel.setAttribute('aria-hidden', 'true');
    elements.backdrop.hidden = true;
    document.body.style.overflow = '';
    if (returnFocus && typeof returnFocus.focus === 'function') returnFocus.focus();
    render();
  }

  function hasEditorContent() {
    return Boolean(
      elements.noteTitle.value.trim()
      || elements.tags.value.split(',').some(tag => tag.trim())
      || normalizeTaskText(elements.noteBody.textContent),
    );
  }

  function saveEditor() {
    const note = notes.find(item => item.id === activeId) || sharedNotes.find(item => item.id === activeId);
    if (!note) return;
    const shared = Boolean(note.ownerEmail);
    if (shared && note.permission !== 'write') {
      elements.saveState.classList.remove('is-saving');
      elements.saveState.innerHTML = `<span class="save-dot"></span><span>${t('share.readOnlyBadge')}</span>`;
      showToast(t('share.readOnlySaveFailed'));
      return;
    }
    normalizeChecklistGroups();
    note.title = elements.noteTitle.value.trim();
    note.body = serializedEditorBody();
    note.bodyFormat = 1;
    note.tags = [...new Set(elements.tags.value.split(',').map(tag => tag.trim().toLocaleLowerCase()).filter(Boolean))];
    note.color = activeColor;
    note.updatedAt = new Date().toISOString();
    if (shared) {
      persistShared(note);
    } else {
      moveToFront(note);
      persist();
    }
    elements.saveState.classList.remove('is-saving');
    elements.saveState.innerHTML = `<span class="save-dot"></span><span>${t('editor.saved')}</span>`;
    elements.date.textContent = t('editor.created', { date: window.i18n.formatFullDate(note.createdAt) });
    updateWordCount();
    render();
  }

  function persistShared(note) {
    const payload = JSON.stringify({
      title: note.title, body: note.body, bodyFormat: note.bodyFormat, color: note.color, tags: note.tags,
    });
    saveQueue = saveQueue.catch(() => {}).then(() => apiRequest(`/api/shared/${encodeURIComponent(note.id)}`, { method: 'PUT', body: payload }));
    saveQueue.catch(error => showToast(t('editor.saveFailed', { message: error.message })));
  }

  function scheduleSave() {
    elements.saveState.classList.add('is-saving');
    elements.saveState.innerHTML = `<span class="save-dot"></span><span>${t('editor.saving')}</span>`;
    window.clearTimeout(saveTimeout);
    saveTimeout = window.setTimeout(saveEditor, 180);
  }

  function updateWordCount() {
    const body = elements.noteBody.cloneNode(true);
    body.querySelectorAll('.task-group-label').forEach(label => label.remove());
    const text = body.innerText || body.textContent || '';
    const count = text.trim().split(/\s+/).filter(Boolean).length;
    elements.words.textContent = `${count} ${pluralText('editor.words', count)}`;
  }

  function updateEditorActions(note) {
    const shared = Boolean(note.ownerEmail);
    const readOnly = shared && note.permission !== 'write';
    elements.pin.classList.toggle('is-pinned', note.pinned);
    elements.pin.setAttribute('aria-label', t(note.pinned ? 'editor.unpin' : 'editor.pin'));
    elements.pin.title = t(note.pinned ? 'editor.unpinTitle' : 'editor.pinTitle');
    elements.archive.textContent = note.deleted ? '↶' : '▣';
    elements.archive.setAttribute('aria-label', t(note.deleted ? 'editor.restoreTrash' : note.archived ? 'editor.unarchive' : 'editor.archive'));
    elements.archive.title = t(note.deleted || note.archived ? 'editor.unarchiveTitle' : 'editor.archiveTitle');
    elements.delete.setAttribute('aria-label', t(note.deleted ? 'editor.deleteForever' : 'editor.delete'));
    elements.delete.title = t(note.deleted ? 'editor.deleteForever' : 'editor.delete');
    // A recipient never gets the owner's pin, archive, delete or re-share controls.
    elements.pin.hidden = note.deleted || shared;
    elements.archive.hidden = shared;
    elements.delete.hidden = shared;
    $('#share-note').hidden = note.deleted || shared;
    elements.noteTitle.readOnly = readOnly;
    elements.tags.readOnly = readOnly;
    elements.noteBody.contentEditable = readOnly ? 'false' : 'true';
    elements.panel.classList.toggle('is-read-only', readOnly);
    $('#format-toolbar').hidden = readOnly;
    $('#editor-share-notice').hidden = !shared;
    $('#editor-share-notice').textContent = readOnly
      ? t('share.readOnlyNotice')
      : t('share.ownerLabel', { email: note.ownerEmail });
  }

  function setColor(color) {
    activeColor = COLORS.includes(color) ? color : 'default';
    $$('.color-swatch').forEach(swatch => swatch.classList.toggle('is-selected', swatch.dataset.color === activeColor));
  }

  async function shareNote(note) {
    const copy = { title: note.title, body: note.body, bodyFormat: note.bodyFormat === 1 ? 1 : 0, color: note.color, tags: note.tags || [] };
    const encoded = encodeBase64Url(JSON.stringify(copy));
    const url = new URL(window.location.href);
    url.hash = `share=${encoded}`;
    try {
      await navigator.clipboard.writeText(url.toString());
      showToast(t('shared.copied'));
    } catch {
      showToast(t('shared.copyFailed'));
    }
  }

  function readSharedNote() {
    const match = window.location.hash.match(/^#share=([A-Za-z0-9_-]+)$/);
    if (!match) return;
    try {
      const data = JSON.parse(decodeBase64Url(match[1]));
      if (!data || typeof data !== 'object' || typeof data.body !== 'string' || (data.title && typeof data.title !== 'string')) throw new Error('Invalid note');
      pendingSharedNote = {
        title: String(data.title || '').slice(0, 160),
        body: data.body.slice(0, 100000),
        bodyFormat: data.bodyFormat === 1 ? 1 : 0,
        color: COLORS.includes(data.color) ? data.color : 'default',
        tags: Array.isArray(data.tags) ? data.tags.map(String).slice(0, 20) : [],
      };
      elements.sharedTitle.textContent = pendingSharedNote.title || t('editor.untitled');
      elements.sharedPreview.textContent = noteText(pendingSharedNote) || t('editor.emptyNote');
      elements.sharedBanner.hidden = false;
      elements.sharedBanner.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    } catch {
      showToast(t('shared.invalid'));
      window.history.replaceState(null, '', `${window.location.pathname}${window.location.search}`);
    }
  }

  function encodeBase64Url(value) {
    const bytes = new TextEncoder().encode(value);
    let binary = '';
    bytes.forEach(byte => { binary += String.fromCharCode(byte); });
    return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/g, '');
  }

  function decodeBase64Url(value) {
    const base64 = value.replace(/-/g, '+').replace(/_/g, '/');
    const binary = atob(base64 + '='.repeat((4 - base64.length % 4) % 4));
    const bytes = Uint8Array.from(binary, char => char.charCodeAt(0));
    return new TextDecoder().decode(bytes);
  }

  function showToast(message) {
    elements.toast.textContent = message;
    elements.toast.classList.add('is-visible');
    window.clearTimeout(toastTimeout);
    toastTimeout = window.setTimeout(() => elements.toast.classList.remove('is-visible'), 3200);
  }

  document.addEventListener('selectionchange', event => {
    const selection = window.getSelection();
    if (selection?.anchorNode && elements.noteBody.contains(selection.anchorNode)) {
      rememberEditorRange();
    }
  });
  $$('#format-toolbar button').forEach(button => {
    button.addEventListener('click', () => {
      restoreEditorRange();
      const previousRange = editorRange?.cloneRange();
      if (button.hasAttribute('data-insert-checklist')) {
        document.execCommand('insertHTML', false, `<ul class="task-list"><li><input type="checkbox" class="task-checkbox" contenteditable="false" aria-label="${t('editor.checkboxAria')}"><span class="task-text" tabindex="0">&#8203;</span></li></ul>`);
      } else if (button.dataset.command) {
        document.execCommand(button.dataset.command, false, null);
      }
      if (['insertUnorderedList', 'insertOrderedList'].includes(button.dataset.command) && previousRange && elements.noteBody.contains(previousRange.startContainer)) {
        const selection = window.getSelection();
        selection.removeAllRanges();
        selection.addRange(previousRange);
      }
      rememberEditorRange();
      scheduleSave();
    });
  });
  elements.noteBody.addEventListener('keydown', event => {
    if (event.key === 'Backspace') {
      const selectedTask = taskTextAtSelection();
      const focusedCheckbox = event.target.matches?.('input.task-checkbox') ? event.target : null;
      const item = focusedCheckbox?.closest('li')
        || (selectedTask && !normalizeTaskText(selectedTask.textContent) ? selectedTask.closest('li') : null);
      if (item) {
        event.preventDefault();
        removeChecklistItem(item);
        $('#task-restore-suggestions').hidden = true;
        updateWordCount();
        scheduleSave();
      }
      return;
    }
    if (event.key !== 'Enter' || event.shiftKey) return;
    const selection = window.getSelection();
    const anchor = selection?.focusNode || selection?.anchorNode;
    const anchorElement = anchor?.nodeType === Node.ELEMENT_NODE ? anchor : anchor?.parentElement;
    const item = anchorElement?.closest('li');
    const list = item?.closest('ul, ol');
    if (!item || !list) return;

    const isTaskList = list.classList.contains('task-list');

    // Check if the item is essentially empty.
    // For task lists, it might contain a checkbox but empty text.
    // For normal lists, it might just be empty text.
    const taskTextNode = item.querySelector('.task-text');
    const isItemEmpty = isTaskList
        ? (!taskTextNode || !taskTextNode.textContent.replace(/[\u200B\u00A0\u200C\u200D\uFEFF\u200e\u200f]/g, '').trim())
        : !item.textContent.replace(/[\u200B\u00A0\u200C\u200D\uFEFF\u200e\u200f]/g, '').trim();

    if (isItemEmpty && item === list.lastElementChild) {
      event.preventDefault();
      const host = list.parentElement;
      const followingNode = list.nextSibling;
      item.remove();
      if (list.children.length === 0) {
        list.remove();
        if (host !== elements.noteBody && !host.textContent.trim() && !host.querySelector('ul, ol')) host.remove();
      }
      const paragraph = document.createElement('div');
      paragraph.append(document.createElement('br'));
      if (host === elements.noteBody) host.insertBefore(paragraph, followingNode);
      else host.after(paragraph);
      window.setTimeout(() => {
        placeEditorCaret(paragraph);
        // Force the browser to update command state
        if (!isTaskList) {
           if (document.queryCommandState('insertOrderedList')) document.execCommand('insertOrderedList', false, null);
           if (document.queryCommandState('insertUnorderedList')) document.execCommand('insertUnorderedList', false, null);
        }
      }, 0);

      if (isTaskList) {
        normalizeChecklistGroups();
        $('#task-restore-suggestions').hidden = true;
      }
      updateWordCount();
      scheduleSave();
      return;
    }

    // For task lists, we have custom behaviour on non-empty items
    if (isTaskList) {
      event.preventDefault();
      const nextItem = createChecklistItem();
      item.after(nextItem);
      normalizeChecklistGroups();
      const nextText = nextItem.querySelector('.task-text');
      window.setTimeout(() => placeEditorCaret(nextText), 0);
      $('#task-restore-suggestions').hidden = true;
      updateWordCount();
      scheduleSave();
    }
  });
  elements.noteBody.addEventListener('pointerdown', event => {
    if (event.button === 0) placeTaskCaretFromPointer(event);
  });
  elements.noteBody.addEventListener('change', event => {
    if (event.target.matches('input[type="checkbox"]')) {
      normalizeChecklistGroups();
      $('#task-restore-suggestions').hidden = true;
      scheduleSave();
    }
  });

  $('#capture-note').addEventListener('click', () => openEditor());
  $('#empty-create').addEventListener('click', () => openEditor());
  $('#close-editor').addEventListener('click', closeEditor);
  elements.backdrop.addEventListener('click', closeEditor);

  elements.navAdmin.addEventListener('click', () => {
    if (activeId) closeEditor();
    view = 'admin';
    render();
  });
  elements.adminLink.addEventListener('click', (e) => {
    e.preventDefault();
    $('#settings-menu').open = false;
    if (activeId) closeEditor();
    view = 'admin';
    render();
  });

  elements.nav.forEach(button => button.addEventListener('click', () => {
    if (activeId) closeEditor();
    view = button.dataset.view;
    render();
  }));
  elements.search.addEventListener('input', () => {
    query = elements.search.value.trim();
    render();
  });
  [elements.noteTitle, elements.noteBody, elements.tags].forEach(input => input.addEventListener('input', event => {
    if (input === elements.noteBody) {
      normalizeChecklistItemMarkup();
      updateWordCount();
      updateCompletedTaskSuggestions(taskTextAtSelection());
    }
    scheduleSave();
  }));
  $$('.color-swatch').forEach(swatch => swatch.addEventListener('click', () => {
    setColor(swatch.dataset.color);
    scheduleSave();
  }));
  elements.pin.addEventListener('click', () => {
    const note = notes.find(item => item.id === activeId);
    if (!note) return;
    note.pinned = !note.pinned;
    saveEditor();
    updateEditorActions(note);
  });
  elements.archive.addEventListener('click', () => {
    const note = notes.find(item => item.id === activeId);
    if (!note) return;
    const restoredFromTrash = note.deleted;
    if (restoredFromTrash) {
      note.deleted = false;
      note.archived = false;
    } else {
      note.archived = !note.archived;
    }
    if (note.archived) note.pinned = false;
    note.updatedAt = new Date().toISOString();
    saveEditor();
    updateEditorActions(note);
    showToast(t(restoredFromTrash ? 'editor.restoredToast' : note.archived ? 'editor.archivedToast' : 'editor.unarchivedToast'));
    closeEditor();
  });
  elements.delete.addEventListener('click', () => {
    const note = notes.find(item => item.id === activeId);
    if (!note) return;
    if (note.deleted) {
      notes = notes.filter(item => item.id !== note.id);
      showToast(t('editor.deletedToast'));
    } else {
      note.deleted = true;
      note.pinned = false;
      note.archived = false;
      note.updatedAt = new Date().toISOString();
      showToast(t('editor.trashedToast'));
    }
    persist();
    closeEditor();
  });
  $('#share-note').addEventListener('click', () => {
    saveEditor();
    if (activeId) openShare(activeId);
  });
  $('#close-share').addEventListener('click', closeShare);
  elements.shareBackdrop.addEventListener('click', closeShare);
  elements.shareForm.addEventListener('submit', submitShare);
  $('#dismiss-shared').addEventListener('click', () => {
    pendingSharedNote = null;
    elements.sharedBanner.hidden = true;
    window.history.replaceState(null, '', `${window.location.pathname}${window.location.search}`);
  });
  $('#save-shared').addEventListener('click', () => {
    if (!pendingSharedNote) return;
    const note = createNote(pendingSharedNote);
    notes.unshift(note);
    persist();
    pendingSharedNote = null;
    elements.sharedBanner.hidden = true;
    window.history.replaceState(null, '', `${window.location.pathname}${window.location.search}`);
    view = 'all';
    render();
    showToast(t('shared.saved'));
    openEditor(note.id);
  });
  document.addEventListener('click', event => {
    const menu = $('#settings-menu');
    if (menu.open && !menu.contains(event.target) && !elements.noteBody.contains(event.target) && !event.target.closest('.editor-panel')) menu.open = false;
  });
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape' && !elements.sharePanel.hidden && elements.sharePanel.classList.contains('is-open')) {
      closeShare();
      return;
    }
    if (event.key === 'Escape' && !elements.profilePanel.hidden && elements.profilePanel.classList.contains('is-open')) {
      closeProfile();
      return;
    }
    if (event.key === 'Escape' && $('#settings-menu').open) {
      $('#settings-menu').open = false;
      return;
    }
    if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
      event.preventDefault();
      elements.search.focus();
    }
    if (!event.metaKey && !event.ctrlKey && event.key.toLowerCase() === 'n' && !['INPUT', 'TEXTAREA'].includes(document.activeElement.tagName) && !activeId) {
      event.preventDefault();
      openEditor();
    }
    if (event.key === 'Escape' && activeId) closeEditor();
  });


  document.querySelector('#create-invite')?.addEventListener('click', async () => {
    const message = document.querySelector('#invite-message');
    message.hidden = true;
    try {
      const invite = await apiRequest('/api/admin/invites', { method: 'POST', body: '{}' });
      document.querySelector('#invite-url').value = invite.url;
      document.querySelector('#invite-expiry').textContent = t('admin.invites.expiry', { date: window.i18n.formatDateTime(invite.expiresAt) });
      document.querySelector('#invite-result').hidden = false;
      await refreshAdmin();
    } catch (error) {
      message.textContent = error.message;
      message.classList.add('is-error');
      message.hidden = false;
    }
  });

  document.querySelector('#backup-unencrypted-toggle')?.addEventListener('change', event => {
    const pwdInput = document.querySelector('#backup-password');
    if (pwdInput) pwdInput.disabled = event.target.checked;
  });

  initializeApp();

  let currentTarballUrl = null;

  document.querySelector('#check-update').addEventListener('click', async event => {
    const button = event.currentTarget;
    const message = document.querySelector('#update-message');
    const resultDiv = document.querySelector('#update-result');

    button.disabled = true;
    message.hidden = true;
    resultDiv.hidden = true;

    try {
      const result = await apiRequest('/api/admin/update/check');
      if (result.updateAvailable) {
        document.querySelector('#update-latest-version').textContent = result.latestVersion;
        currentTarballUrl = result.tarballUrl;
        resultDiv.hidden = false;
      } else {
        message.textContent = t('admin.update.upToDate', { version: result.currentVersion });
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
      await apiRequest('/api/admin/update/perform', {
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
    const isUnencrypted = document.querySelector('#backup-unencrypted-toggle')?.checked;
    const password = document.querySelector('#backup-password')?.value || '';
    if (!isUnencrypted && !password) {
      setBackupMessage(t('admin.backups.passwordRequired'), true);
      return;
    }
    button.disabled = true;
    setBackupMessage(t('admin.backups.creating'));
    try {
      const backup = await apiRequest('/api/admin/backups', {
        method: 'POST',
        body: JSON.stringify({ password: isUnencrypted ? null : password })
      });
      setBackupMessage(t('admin.backups.created', { filename: backup.filename }));
      await refresh();
    } catch (error) {
      setBackupMessage(error.message, true);
    } finally {
      button.disabled = false;
    }
  });

  window.i18n.onChange(() => {
    applyTheme(document.documentElement.dataset.theme);
    if (!elements.authView.hidden) showAuth(elements.registerForm.hidden ? 'login' : 'register', elements.authMessage.hidden ? '' : elements.authMessage.textContent);
    if (currentUser) render();
    if (activeId) {
      const current = notes.find(note => note.id === activeId);
      if (current) {
        elements.date.textContent = t('editor.created', { date: window.i18n.formatFullDate(current.createdAt) });
        updateWordCount();
        updateEditorActions(current);
      }
      normalizeChecklistGroups();
      $('#task-restore-suggestions').replaceChildren();
      $('#task-restore-suggestions').hidden = true;
    }
    if (pendingSharedNote) {
      elements.sharedTitle.textContent = pendingSharedNote.title || t('editor.untitled');
      elements.sharedPreview.textContent = noteText(pendingSharedNote) || t('editor.emptyNote');
    }
  });
})();
