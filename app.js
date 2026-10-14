(() => {
  const STORAGE_KEY = 'notki.notes.v1';
  const MIGRATION_KEY = 'notki.server-migrated.v1';
  const COLORS = ['default', 'mint', 'lemon', 'peach', 'lilac', 'sky', 'rose', 'sand', 'sage', 'plum'];
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
    noteTitle: $('#note-title'), noteBody: $('#note-body'), labelsContainer: $('#note-labels'), saveState: $('#save-state'), date: $('#editor-date'),
    words: $('#editor-words'), pin: $('#pin-note'), archive: $('#archive-note'), delete: $('#delete-note'), toast: $('#toast'),
    appShell: $('#app-shell'), authView: $('#auth-view'), authHeading: $('#auth-heading'), authDescription: $('#auth-description'), authMessage: $('#auth-message'),
    topbar: $('header.topbar'), loginForm: $('#login-form'), registerForm: $('#register-form'), login2faForm: $('#login-2fa-form'), loginTotp: $('#login-totp'), loginPasskeyBtn: $('#login-passkey-btn') || $('#login-2fa-passkey-btn'), authSwitch: $('#auth-switch'), adminLink: $('#admin-link'), navAdmin: $('#nav-admin'), adminArea: $('#admin-area'), pageHeading: $('.page-heading'), captureWrap: $('.capture-wrap'), notesArea: $('.notes-area'), topbarSearch: $('.search-box'),
    sharedBanner: $('#shared-banner'), sharedTitle: $('#shared-title'), sharedPreview: $('#shared-preview'),
    avatar: $('#avatar'), profilePanel: $('#profile-panel'), profileBackdrop: $('#profile-backdrop'), profileAccount: $('#profile-account'),
    profileMessage: $('#profile-message'), passwordForm: $('#password-form'),
    avatarPreview: $('#profile-avatar-preview'), avatarInput: $('#avatar-input'), avatarMessage: $('#avatar-message'),
    sidebarAvatar: $('#sidebar-avatar'), sidebarUserEmail: $('#sidebar-user-email'), sidebarProfileButton: $('#sidebar-profile-button'),
    sidebar: $('#sidebar'), sidebarBackdrop: $('#sidebar-backdrop'), hamburgerToggle: $('#hamburger-toggle'),
    topbarSyncBtn: $('#topbar-sync-button'),
    sharedCount: $('#count-shared'), sharePanel: $('#share-panel'), shareBackdrop: $('#share-backdrop'),
    shareForm: $('#share-form'), shareEmail: $('#share-email'), sharePermission: $('#share-permission'),
    shareMessage: $('#share-message'), shareList: $('#share-list'), shareEmpty: $('#share-empty'),
    shareNoteName: $('#share-note-name'),
  };

  let notes = [];
  let sharedNotes = [];
  let userLabels = [];
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
  let isOffline = !navigator.onLine;
  let isSyncing = false;
  let pendingSync = false;
  let passkeyConditionalAbortController = null;
  let passkeyConditionalPromise = null;

  function bufferToBase64(buffer) {
    if (!buffer) return '';
    const bytes = new Uint8Array(buffer);
    let binary = '';
    for (let i = 0; i < bytes.byteLength; i++) {
      binary += String.fromCharCode(bytes[i]);
    }
    return btoa(binary);
  }

  function getCacheKey(userId, key) {
    return `notki.cache.${key}.${userId}`;
  }

  function saveLocalCache(userId, data) {
    if (!userId) return;
    try {
      if (data.notes !== undefined) localStorage.setItem(getCacheKey(userId, 'notes'), JSON.stringify(data.notes));
      if (data.sharedNotes !== undefined) localStorage.setItem(getCacheKey(userId, 'sharedNotes'), JSON.stringify(data.sharedNotes));
      if (data.labels !== undefined) localStorage.setItem(getCacheKey(userId, 'labels'), JSON.stringify(data.labels));
    } catch (e) {
      console.error('Failed to save to local cache:', e);
    }
  }

  function getLocalCache(userId) {
    if (!userId) return { notes: null, sharedNotes: null, labels: null };
    try {
      const notes = JSON.parse(localStorage.getItem(getCacheKey(userId, 'notes')) || 'null');
      const sharedNotes = JSON.parse(localStorage.getItem(getCacheKey(userId, 'sharedNotes')) || 'null');
      const labels = JSON.parse(localStorage.getItem(getCacheKey(userId, 'labels')) || 'null');
      return { notes, sharedNotes, labels };
    } catch (e) {
      return { notes: null, sharedNotes: null, labels: null };
    }
  }

  function saveCachedUser(user) {
    try {
      if (user) localStorage.setItem('notki.cache.user', JSON.stringify(user));
      else localStorage.removeItem('notki.cache.user');
    } catch (e) {}
  }

  function getCachedUser() {
    try {
      return JSON.parse(localStorage.getItem('notki.cache.user') || 'null');
    } catch (e) {
      return null;
    }
  }

  function setOnlineStatus(online) {
    const changed = isOffline === online;
    isOffline = !online;
    updateStorageIndicator();
    if (changed && online && currentUser) {
      syncPendingChanges();
    }
  }

  function updateStorageIndicator() {
    const container = $('.storage-note');
    if (!container) return;
    const dot = container.querySelector('.storage-dot');
    const label = container.querySelector('span:not(.storage-dot)');

    const showSync = isOffline;
    const topbarSync = elements.topbarSyncBtn || $('#topbar-sync-button');

    if (topbarSync) {
      topbarSync.hidden = !showSync;
      topbarSync.disabled = isSyncing;
    }

    if (isSyncing) {
      if (dot) dot.style.background = '#e6c875'; // Yellow
      if (label) label.textContent = t('nav.storageSyncing');
    } else if (isOffline) {
      if (dot) dot.style.background = '#e57373'; // Red/orange
      if (label) label.textContent = t('nav.storageOffline');
    } else if (currentUser && (hasPendingSync(currentUser.id) || pendingSync)) {
      if (dot) dot.style.background = '#e6c875'; // Yellow
      if (label) label.textContent = t('nav.storageSyncing');
    } else {
      if (dot) dot.style.background = '#a9d377'; // Green
      if (label) label.textContent = t('nav.storage');
    }
  }

  window.addEventListener('online', () => setOnlineStatus(true));
  window.addEventListener('offline', () => setOnlineStatus(false));

  function getTaskStatsFromElement(rootElement) {
    if (!rootElement) return { total: 0, completed: 0, percent: 0 };
    const checkboxes = [...rootElement.querySelectorAll('input[type="checkbox"]')];
    const total = checkboxes.length;
    if (!total) return { total: 0, completed: 0, percent: 0 };
    const completed = checkboxes.filter(cb => cb.checked || cb.hasAttribute('checked')).length;
    const percent = Math.round((completed / total) * 100);
    return { total, completed, percent };
  }

  function getTaskStatsFromHtml(html) {
    if (!html) return { total: 0, completed: 0, percent: 0 };
    const temp = document.createElement('div');
    temp.innerHTML = html;
    return getTaskStatsFromElement(temp);
  }

  function getTaskStats(note) {
    if (!note || !note.body) return { total: 0, completed: 0, percent: 0 };
    const html = note.bodyFormat === 1 ? sanitizeRichHtml(note.body) : plainTextToHtml(note.body);
    return getTaskStatsFromHtml(html);
  }

  function updateEditorProgress() {
    const container = $('#editor-progress');
    if (!container) return;
    const stats = getTaskStatsFromElement(elements.noteBody);
    if (stats.total === 0) {
      container.hidden = true;
      return;
    }
    container.hidden = false;
    const textEl = $('#editor-progress-text');
    const fillEl = $('#editor-progress-fill');
    if (textEl) textEl.textContent = `${stats.completed}/${stats.total} (${stats.percent}%)`;
    if (fillEl) {
      fillEl.style.width = `${stats.percent}%`;
      fillEl.classList.toggle('is-complete', stats.percent === 100);
    }
  }

  function cleanupAllTaskDrags() {
    $$('.task-drag-preview').forEach(preview => preview.remove());
    $$('.is-dragging-task').forEach(item => item.classList.remove('is-dragging-task'));
    document.body.classList.remove('is-dragging-task-active');
  }

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
    window.notkiTheme.sync();
  }

  async function apiRequest(path, options = {}) {
    const headers = new Headers(options.headers || {});
    if (options.body && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json');
    headers.set('Accept-Language', window.i18n.getLanguage());
    try {
      const response = await fetch(path, { cache: 'no-store', ...options, headers, credentials: 'same-origin' });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(payload.error || t('error.server'));
      setOnlineStatus(true);
      return payload;
    } catch (err) {
      if (err.name === 'TypeError' || err.message === 'Failed to fetch') {
        setOnlineStatus(false);
      }
      throw err;
    }
  }

  function showAuth(mode, message = '') {
    if (elements.authView) elements.authView.hidden = false;
    if (elements.appShell) elements.appShell.hidden = true;
    if (elements.panel) elements.panel.hidden = true;
    if (elements.backdrop) elements.backdrop.hidden = true;
    if (elements.login2faForm) elements.login2faForm.hidden = true;
    if (elements.loginPasskeyBtn) elements.loginPasskeyBtn.hidden = true;
    if (elements.loginForm) elements.loginForm.hidden = mode !== 'login';
    if (elements.registerForm) elements.registerForm.hidden = mode !== 'register';
    const authHeadingSpan = elements.authHeading?.querySelector?.('span[data-i18n]');
    if (authHeadingSpan) {
      authHeadingSpan.dataset.i18n = mode === 'register' ? 'auth.heading.register' : 'auth.heading.login';
    } else if (elements.authHeading?.firstChild) {
      elements.authHeading.firstChild.dataset.i18n = mode === 'register' ? 'auth.heading.register' : 'auth.heading.login';
    }
    if (elements.authDescription) {
      elements.authDescription.dataset.i18n = mode === 'register' ? 'auth.description.register' : 'auth.description.login';
    }
    if (window.i18n && elements.authView) window.i18n.applyTranslations(elements.authView);
    if (elements.authMessage) {
      elements.authMessage.textContent = message;
      elements.authMessage.hidden = !message;
    }
    if (elements.authSwitch) {
      elements.authSwitch.hidden = !inviteToken;
      elements.authSwitch.textContent = t(mode === 'register' ? 'auth.switch.register' : 'auth.switch.login');
    }
    document.body.classList.add('is-auth');

    if (mode === 'login') {
      triggerConditionalPasskeyLogin();
    } else {
      await cancelConditionalPasskeyLogin();
    }
  }

  async function cancelConditionalPasskeyLogin() {
    if (passkeyConditionalAbortController) {
      passkeyConditionalAbortController.abort();
      passkeyConditionalAbortController = null;
    }
    if (passkeyConditionalPromise) {
      const p = passkeyConditionalPromise;
      passkeyConditionalPromise = null;
      try {
        await p;
      } catch (e) {
        // Ignored - expected AbortError
      }
      await new Promise(resolve => setTimeout(resolve, 50));
    }
  }

  async function triggerConditionalPasskeyLogin() {
    if (!window.isSecureContext || !navigator?.credentials?.get || !window.PublicKeyCredential) {
      return;
    }
    try {
      if (typeof PublicKeyCredential.isConditionalMediationAvailable === 'function') {
        const available = await PublicKeyCredential.isConditionalMediationAvailable();
        if (!available) return;
      } else {
        return;
      }
    } catch (e) {
      return;
    }

    await cancelConditionalPasskeyLogin();
    passkeyConditionalAbortController = new AbortController();

    const hostname = window.location.hostname;
    const isDomain = Boolean(hostname && !/^(\d{1,3}\.){3}\d{1,3}$/.test(hostname) && hostname !== 'localhost');
    const publicKeyOptions = {
      challenge: new Uint8Array(32),
      userVerification: 'preferred'
    };
    if (isDomain) {
      publicKeyOptions.rpId = hostname;
    }

    try {
      passkeyConditionalPromise = navigator.credentials.get({
        publicKey: publicKeyOptions,
        mediation: 'conditional',
        signal: passkeyConditionalAbortController.signal
      });
      const assertion = await passkeyConditionalPromise;

      if (!assertion) return;

      const payload = {
        id: assertion.id,
        authenticatorData: bufferToBase64(assertion.response.authenticatorData),
        clientDataJSON: bufferToBase64(assertion.response.clientDataJSON),
        signature: bufferToBase64(assertion.response.signature)
      };

      const { user } = await apiRequest('/api/login/passkey', {
        method: 'POST',
        body: JSON.stringify(payload)
      });
      await cancelConditionalPasskeyLogin();
      await showApp(user);
    } catch (error) {
      // Passive conditional mediation runs in the background for autofill.
      // Any errors (e.g. aborted request, missing authenticator) should be swallowed silently.
    } finally {
      passkeyConditionalPromise = null;
    }
  }

  async function showApp(user) {
    currentUser = user;
    saveCachedUser(user);
    userLabels = user.labels || [];

    let loadedFromOnline = false;
    try {
      const [response, shared] = await Promise.all([apiRequest('/api/notes'), apiRequest('/api/shared')]);
      notes = response.notes;
      sharedNotes = shared.notes;
      loadedFromOnline = true;
      saveLocalCache(user.id, { notes, sharedNotes, labels: userLabels });
    } catch (err) {
      // Offline fallback
      const cached = getLocalCache(user.id);
      notes = cached.notes || [];
      sharedNotes = cached.sharedNotes || [];
      if (cached.labels) userLabels = cached.labels;
    }

    const migratedKey = `${MIGRATION_KEY}.${user.id}`;
    if (loadedFromOnline && !notes.length && legacyNotes.length && !localStorage.getItem(migratedKey)) {
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
    if ($('#sidebar-admin-link')) $('#sidebar-admin-link').hidden = !user.isAdmin;
    if (user.isAdmin) { document.querySelector('#admin-account').textContent = user.email; }
    elements.avatar.title = user.email;
    elements.avatar.setAttribute('aria-label', t('topbar.accountAria', { email: user.email }));
    elements.profileAccount.textContent = user.email;
    if (elements.sidebarUserEmail) elements.sidebarUserEmail.textContent = user.email;
    renderAvatar(user);
    document.body.classList.remove('is-auth');
    applyHashIntent();
    render();
    readSharedNote();
    updateStorageIndicator();

    if (loadedFromOnline) {
      syncPendingChanges();
    }
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

  function tableCell(content) {
    const cell = document.createElement('td');
    cell.textContent = content;
    return cell;
  }

  function formatDate(isoString) {
    if (!isoString) return '';
    return window.i18n.formatDateTime(isoString);
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
      await refreshAdmin();
    } catch (error) {
      alert(error.message);
    }
  }

  function createTrashIconSvg() {
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('viewBox', '0 0 24 24');
    svg.setAttribute('width', '1em');
    svg.setAttribute('height', '1em');
    svg.setAttribute('fill', 'none');
    svg.setAttribute('stroke', 'currentColor');
    svg.setAttribute('stroke-width', '1.7');
    svg.setAttribute('stroke-linecap', 'round');
    svg.setAttribute('stroke-linejoin', 'round');
    svg.setAttribute('aria-hidden', 'true');
    svg.innerHTML = '<path d="M3 6h18"/><path d="M8 6V4h8v2"/><path d="M6 6l1 14h10l1-14"/><path d="M10 10v7M14 10v7"/>';
    return svg;
  }

  function createShieldOffIconSvg() {
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('viewBox', '0 0 24 24');
    svg.setAttribute('width', '1em');
    svg.setAttribute('height', '1em');
    svg.setAttribute('fill', 'none');
    svg.setAttribute('stroke', 'currentColor');
    svg.setAttribute('stroke-width', '1.7');
    svg.setAttribute('stroke-linecap', 'round');
    svg.setAttribute('stroke-linejoin', 'round');
    svg.setAttribute('aria-hidden', 'true');
    svg.innerHTML = '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/><path d="M4.5 4.5l15 15"/>';
    return svg;
  }

  function createDownloadIconSvg() {
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('viewBox', '0 0 24 24');
    svg.setAttribute('width', '1em');
    svg.setAttribute('height', '1em');
    svg.setAttribute('fill', 'none');
    svg.setAttribute('stroke', 'currentColor');
    svg.setAttribute('stroke-width', '1.7');
    svg.setAttribute('stroke-linecap', 'round');
    svg.setAttribute('stroke-linejoin', 'round');
    svg.setAttribute('aria-hidden', 'true');
    svg.innerHTML = '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/>';
    return svg;
  }

  function createRestoreIconSvg() {
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('viewBox', '0 0 24 24');
    svg.setAttribute('width', '1em');
    svg.setAttribute('height', '1em');
    svg.setAttribute('fill', 'none');
    svg.setAttribute('stroke', 'currentColor');
    svg.setAttribute('stroke-width', '1.7');
    svg.setAttribute('stroke-linecap', 'round');
    svg.setAttribute('stroke-linejoin', 'round');
    svg.setAttribute('aria-hidden', 'true');
    svg.innerHTML = '<polyline points="1 4 1 10 7 10"/><path d="M3.51 15a9 9 0 1 0 2.13-9.36L1 10"/>';
    return svg;
  }

  function createLockIconSvg() {
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('viewBox', '0 0 24 24');
    svg.setAttribute('width', '1em');
    svg.setAttribute('height', '1em');
    svg.setAttribute('fill', 'none');
    svg.setAttribute('stroke', 'currentColor');
    svg.setAttribute('stroke-width', '1.7');
    svg.setAttribute('stroke-linecap', 'round');
    svg.setAttribute('stroke-linejoin', 'round');
    svg.setAttribute('aria-hidden', 'true');
    svg.innerHTML = '<rect x="3" y="11" width="18" height="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/>';
    return svg;
  }

  async function resetUser2FA(userId, email) {
    if (!confirm(t('admin.users.confirmReset2FA', { email }))) return;
    try {
      await apiRequest(`/api/admin/users/${userId}/2fa`, { method: 'DELETE' });
      await refreshAdmin();
    } catch (error) {
      alert(error.message);
    }
  }

  function renderUsers(users) {
    const rows = users.map(user => {
      const row = document.createElement('tr');
      const actions = document.createElement('td');
      actions.className = 'admin-table-actions backup-actions';
      if (user.has2FA) {
        actions.append(backupAction(createShieldOffIconSvg(), t('admin.users.reset2FA'), () => resetUser2FA(user.id, user.email), true));
      }
      if (user.role !== 'admin') {
        actions.append(backupAction(createTrashIconSvg(), t('admin.users.delete'), () => deleteUser(user.id), true));
      } else {
        actions.append(backupAction(createLockIconSvg(), t('admin.users.cannotDeleteAdmin'), null, false, true));
      }
      const roleCell = document.createElement('td');
      const roleBadge = document.createElement('span');
      roleBadge.className = `admin-badge ${user.role === 'admin' ? 'admin-badge-role-admin' : 'admin-badge-role-user'}`;
      roleBadge.textContent = t(user.role === 'admin' ? 'admin.role.admin' : 'admin.role.user');
      roleCell.append(roleBadge);
      if (user.has2FA) {
        const badge2fa = document.createElement('span');
        badge2fa.className = 'admin-badge admin-badge-status-pending';
        badge2fa.textContent = '2FA';
        badge2fa.style.marginLeft = '6px';
        roleCell.append(badge2fa);
      }

      row.append(
        tableCell(user.email),
        roleCell,
        tableCell(formatDate(user.createdAt)),
        tableCell(String(user.notes)),
        actions
      );
      return row;
    });
    document.querySelector('#admin-users').replaceChildren(...rows);
  }

  async function deleteInvite(tokenHash) {
    if (!confirm(t('admin.invites.confirmDelete'))) return;
    try {
      await apiRequest(`/api/admin/invites/${encodeURIComponent(tokenHash)}`, { method: 'DELETE' });
      await refreshAdmin();
    } catch (error) {
      alert(error.message);
    }
  }

  function renderInvites(invites) {
    const rows = invites.map(invite => {
      const row = document.createElement('tr');
      const expired = new Date(invite.expiresAt) <= new Date();
      const statusKey = invite.usedAt ? 'used' : expired ? 'expired' : 'pending';
      const statusClass = invite.usedAt ? 'status-used' : expired ? 'status-expired' : 'status-pending';
      const actions = document.createElement('td');
      actions.className = 'admin-table-actions backup-actions';
      if (invite.tokenHash) {
        actions.append(backupAction(createTrashIconSvg(), t('admin.invites.delete'), () => deleteInvite(invite.tokenHash), true));
      }
      const statusCell = document.createElement('td');
      const statusBadge = document.createElement('span');
      statusBadge.className = `admin-badge admin-badge-${statusClass}`;
      statusBadge.textContent = t(`admin.invites.${statusKey}`);
      statusCell.append(statusBadge);

      row.append(
        tableCell(formatDate(invite.createdAt)),
        tableCell(formatDate(invite.expiresAt)),
        statusCell,
        actions
      );
      return row;
    });
    document.querySelector('#admin-invites').replaceChildren(...rows);
  }

  function backupAction(content, title, handler, isDanger = false, isDisabled = false) {
    const button = document.createElement('button');
    button.className = `button-secondary backup-action${isDanger ? ' backup-action-danger' : ''}`;
    button.type = 'button';
    if (typeof content === 'string') {
      button.textContent = content;
    } else {
      button.append(content);
    }
    button.title = title;
    button.setAttribute('aria-label', title);
    if (isDisabled) {
      button.disabled = true;
      button.style.opacity = '0.6';
      button.style.cursor = 'not-allowed';
    } else if (handler) {
      button.addEventListener('click', handler);
    }
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
        backupAction(createDownloadIconSvg(), t('admin.backups.download'), () => downloadBackup(backup.filename)),
        backupAction(createRestoreIconSvg(), t('admin.backups.restore'), () => restoreBackup(backup)),
        backupAction(createTrashIconSvg(), t('admin.backups.delete'), () => deleteBackup(backup.filename), true),
      );
      row.append(filename, tableCell(formatDate(backup.createdAt)), tableCell(size), actions);
      return row;
    });
    body.replaceChildren(...rows);
  }


  async function refreshAdmin() {
    const [summary, backupList, settings] = await Promise.all([
      apiRequest('/api/admin/summary'),
      apiRequest('/api/admin/backups'),
      apiRequest('/api/admin/settings').catch(() => ({}))
    ]);
    renderStats(summary.stats);
    renderUsers(summary.users);
    renderInvites(summary.invites);
    renderBackups(backupList.backups);

    if (settings) {
      if ($('#admin-require-2fa')) $('#admin-require-2fa').checked = settings.require2FA;
      if ($('#admin-session-days')) $('#admin-session-days').value = settings.sessionDays ?? 30;
    }
  }

  async function saveAdminSettings() {
    try {
      const require2FA = $('#admin-require-2fa')?.checked ?? false;
      const sessionDays = parseInt($('#admin-session-days')?.value, 10) || 30;
      await apiRequest('/api/admin/settings', {
        method: 'POST',
        body: JSON.stringify({ require2FA, sessionDays })
      });
    } catch (e) {
      alert(e.message);
    }
  }

  $('#admin-require-2fa')?.addEventListener('change', saveAdminSettings);
  $('#admin-session-days')?.addEventListener('change', saveAdminSettings);

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

  async function restoreBackup(backupTarget) {
    const filename = typeof backupTarget === 'string' ? backupTarget : (backupTarget && backupTarget.filename) ? backupTarget.filename : '';
    if (!filename) return;

    const confirmed = window.confirm(t('admin.backups.confirmRestore', { filename }));
    if (!confirmed) return;

    setBackupMessage(t('admin.backups.restoring'));
    try {
      await apiRequest(`/api/admin/backups/${encodeURIComponent(filename)}/restore`, {
        method: 'POST',
        body: '{}'
      });
      setBackupMessage(t('admin.backups.restored'));
      setTimeout(() => window.location.reload(), 1000);
    } catch (error) {
      setBackupMessage(error.message, true);
    }
  }

  async function deleteBackup(filename) {
    if (!window.confirm(t('admin.backups.confirmDelete', { filename }))) return;
    try {
      await apiRequest(`/api/admin/backups/${encodeURIComponent(filename)}`, { method: 'DELETE' });
      setBackupMessage(t('admin.backups.deleted', { filename }));
      await refreshAdmin();
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
      const cachedUser = getCachedUser();
      if (cachedUser) {
        setOnlineStatus(false);
        await showApp(cachedUser);
      } else {
        showAuth(inviteToken ? 'register' : 'login', t('auth.connectionFailed', { message: error.message }));
      }
    }
  }

  elements.authSwitch.addEventListener('click', () => {
    showAuth(elements.registerForm.hidden ? 'register' : 'login');
  });
  let loginTempToken = '';

  const handlePasskeyLogin = async (useTempToken = false) => {
    await cancelConditionalPasskeyLogin();
    try {
      if (!window.isSecureContext || !navigator?.credentials?.get) {
        throw new Error(t('topbar.2fa.passkeyNotSupported'));
      }
      const passkeyBtn = elements.loginPasskeyBtn || $('#login-passkey-btn') || $('#login-2fa-passkey-btn');
      if (passkeyBtn) passkeyBtn.hidden = false;

      const hostname = window.location.hostname;
      const isDomain = Boolean(hostname && !/^(\d{1,3}\.){3}\d{1,3}$/.test(hostname) && hostname !== 'localhost');
      const publicKeyOptions = {
        challenge: new Uint8Array(32),
        userVerification: "preferred"
      };
      if (isDomain) {
        publicKeyOptions.rpId = hostname;
      }
      const assertion = await navigator.credentials.get({ publicKey: publicKeyOptions });
      const payload = {
        id: assertion.id,
        authenticatorData: bufferToBase64(assertion.response.authenticatorData),
        clientDataJSON: bufferToBase64(assertion.response.clientDataJSON),
        signature: bufferToBase64(assertion.response.signature)
      };
      if (useTempToken && loginTempToken) {
        payload.tempToken = loginTempToken;
      }
      const { user } = await apiRequest('/api/login/passkey', {
        method: 'POST',
        body: JSON.stringify(payload),
      });
      await showApp(user);
    } catch (error) {
      const passkeyBtn = elements.loginPasskeyBtn || $('#login-passkey-btn') || $('#login-2fa-passkey-btn');
      if (passkeyBtn && useTempToken) passkeyBtn.hidden = false;

      if (error.name !== 'NotAllowedError' && error.name !== 'AbortError' && error.name !== 'InvalidStateError') {
        if (elements.authMessage) {
          elements.authMessage.textContent = error.message;
          elements.authMessage.hidden = false;
        }
      }
    }
  };

  elements.loginForm?.addEventListener('submit', async event => {
    event.preventDefault();
    try {
      const emailVal = $('#login-email')?.value || '';
      const passwordVal = $('#login-password')?.value || '';
      const response = await apiRequest('/api/login', {
        method: 'POST',
        body: JSON.stringify({ email: emailVal, password: passwordVal }),
      });
      if (response.requires2FA) {
        loginTempToken = response.tempToken;
        if (elements.loginForm) elements.loginForm.hidden = true;
        const form2fa = elements.login2faForm || $('#login-2fa-form');
        if (form2fa) form2fa.hidden = false;
        const totpInput = elements.loginTotp || $('#login-totp');
        if (totpInput) {
          totpInput.hidden = !response.hasTotp;
          if (totpInput.previousElementSibling) {
            totpInput.previousElementSibling.hidden = !response.hasTotp;
          }
        }
        const totpSubmitBtn = form2fa?.querySelector('button[type="submit"]');
        if (totpSubmitBtn) totpSubmitBtn.hidden = !response.hasTotp;
        const passkeyBtn = elements.loginPasskeyBtn || $('#login-passkey-btn') || $('#login-2fa-passkey-btn');
        if (passkeyBtn) passkeyBtn.hidden = !response.hasPasskey;

        if (response.hasPasskey) {
          handlePasskeyLogin(true);
        } else if (response.hasTotp && totpInput) {
          totpInput.focus();
        }
        return;
      }
      await cancelConditionalPasskeyLogin();
      await showApp(response.user);
    } catch (error) {
      if ($('#login-password')) $('#login-password').value = '';
      showAuth('login', error.message);
    }
  });

  (elements.login2faForm || $('#login-2fa-form'))?.addEventListener('submit', async event => {
    event.preventDefault();
    try {
      const totpVal = (elements.loginTotp || $('#login-totp'))?.value || '';
      const { user } = await apiRequest('/api/login/2fa', {
        method: 'POST',
        body: JSON.stringify({ tempToken: loginTempToken, totpCode: totpVal }),
      });
      await showApp(user);
    } catch (error) {
      if (elements.loginTotp || $('#login-totp')) (elements.loginTotp || $('#login-totp')).value = '';
      if (elements.authMessage) {
        elements.authMessage.textContent = error.message;
        elements.authMessage.hidden = false;
      }
    }
  });

  (elements.loginPasskeyBtn || $('#login-passkey-btn') || $('#login-2fa-passkey-btn'))?.addEventListener('click', () => handlePasskeyLogin(true));

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
    const targets = [elements.avatar, elements.avatarPreview, elements.sidebarAvatar].filter(Boolean);
    for (const node of targets) {
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
    refresh2faStatus();
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
      const filtered = users.filter(user => user.email !== currentUser?.email);
      elements.shareEmail.replaceChildren(...filtered.map(user => {
        const option = document.createElement('option');
        option.value = user.email;
        option.textContent = user.email;
        return option;
      }));
    } catch {
      // Failed to load directory
    }
  }

  async function openShare(noteId) {
    const note = notes.find(item => item.id === noteId) || sharedNotes.find(item => item.id === noteId);
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

    const shared = Boolean(note.ownerEmail);
    if (shared) {
      elements.shareForm.hidden = true;
      elements.shareEmpty.textContent = t('share.ownerLabel', { email: note.ownerEmail });
      elements.shareEmpty.hidden = false;
    } else {
      elements.shareForm.hidden = false;
      window.setTimeout(() => elements.shareEmail.focus(), 180);
      await Promise.all([loadShares(), loadDirectory()]);
    }
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
      const targetNote = notes.find(item => item.id === shareNoteId) || sharedNotes.find(item => item.id === shareNoteId);
      if (targetNote) {
        targetNote.shareCount = shares.length;
        updateCardShareState(shareNoteId, shares.length);
        render();
      }
    } catch (error) {
      showShareMessage(t('share.failed', { message: error.message }), true);
    }
  }

  function updateCardShareState(noteId, shareCount) {
    const cards = $$(`.note-card[data-id="${CSS.escape ? CSS.escape(noteId) : noteId}"]`);
    cards.forEach(card => {
      const shareBtn = $('.card-share', card);
      if (!shareBtn) return;
      const isSharedOut = Boolean(shareCount && shareCount > 0);
      if (isSharedOut) {
        shareBtn.classList.add('is-shared');
        shareBtn.hidden = false;
      } else {
        shareBtn.classList.remove('is-shared');
      }
    });
  }

  async function revokeShare(userId) {
    if (!shareNoteId) return;
    try {
      const { shares } = await apiRequest(`/api/notes/${encodeURIComponent(shareNoteId)}/shares/${userId}`, { method: 'DELETE' });
      renderShareList(shares);
      showShareMessage(t('share.revoked'));
      const targetNote = notes.find(item => item.id === shareNoteId) || sharedNotes.find(item => item.id === shareNoteId);
      if (targetNote) {
        targetNote.shareCount = shares.length;
        updateCardShareState(shareNoteId, shares.length);
        render();
      }
    } catch (error) {
      showShareMessage(t('share.revokeFailed', { message: error.message }), true);
    }
  }

  $('#profile-button').addEventListener('click', () => {
    $('#settings-menu').open = false;
    openProfile();
  });
  $('#sidebar-profile-link')?.addEventListener('click', () => {
    if ($('#sidebar-user-menu')) $('#sidebar-user-menu').open = false;
    closeSidebar();
    openProfile();
  });
  $('#sidebar-admin-link')?.addEventListener('click', (e) => {
    e.preventDefault();
    if ($('#sidebar-user-menu')) $('#sidebar-user-menu').open = false;
    if (activeId) closeEditor();
    closeLabelsModal();
    closeSidebar();
    view = 'admin';
    render();
  });
  $('#sidebar-logout-button')?.addEventListener('click', async () => {
    try {
      await apiRequest('/api/logout', { method: 'POST', body: '{}' });
      window.location.assign('/');
    } catch (error) {
      showToast(error.message);
    }
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

  $('#setup-totp-btn').addEventListener('click', async () => {
    try {
      const response = await apiRequest('/api/account/totp', { method: 'POST', body: '{}' });
      $('#totp-secret-code').textContent = response.secret;
      if ($('#totp-qr-container') && response.qrSvg) {
        $('#totp-qr-container').innerHTML = response.qrSvg;
      }
      $('#totp-verify-area').hidden = false;
      $('#setup-totp-btn').hidden = true;
    } catch (error) {
      alert(error.message);
    }
  });

  let currentBackupCodes = [];

  $('#totp-verify-form').addEventListener('submit', async event => {
    event.preventDefault();
    try {
      const response = await apiRequest('/api/account/totp/verify', { method: 'POST', body: JSON.stringify({ code: $('#totp-verify-code').value }) });
      $('#totp-verify-area').hidden = true;
      $('#totp-verify-code').value = '';
      if (response.backupCodes && response.backupCodes.length) {
        currentBackupCodes = response.backupCodes;
        const listEl = $('#backup-codes-list');
        if (listEl) {
          listEl.replaceChildren(...response.backupCodes.map(code => {
            const item = document.createElement('div');
            item.textContent = code;
            return item;
          }));
        }
        $('#backup-codes-display-area').hidden = false;
      }
      await refresh2faStatus();
    } catch (error) {
      alert(error.message);
    }
  });

  $('#copy-backup-codes-btn')?.addEventListener('click', async event => {
    const button = event.currentTarget;
    const textToCopy = currentBackupCodes.join('\n');
    try {
      await navigator.clipboard.writeText(textToCopy);
      button.textContent = t('admin.invites.copied');
      window.setTimeout(() => { button.textContent = t('topbar.2fa.copyBackupCodes'); }, 1600);
    } catch {
      alert(textToCopy);
    }
  });

  $('#remove-totp-btn').addEventListener('click', async () => {
    if (!confirm(t('topbar.2fa.confirmRemoveTotp'))) return;
    try {
      await apiRequest('/api/account/totp', { method: 'DELETE' });
      currentBackupCodes = [];
      if ($('#backup-codes-display-area')) $('#backup-codes-display-area').hidden = true;
      await refresh2faStatus();
    } catch (error) {
      alert(error.message);
    }
  });

  $('#add-passkey-btn')?.addEventListener('click', async () => {
    try {
      if (!window.isSecureContext || !navigator?.credentials?.create) {
        throw new Error(t('topbar.2fa.passkeyNotSupported'));
      }

      const hostname = window.location.hostname;
      const isDomain = Boolean(hostname && !/^(\d{1,3}\.){3}\d{1,3}$/.test(hostname) && hostname !== 'localhost');
      const rpConfig = { name: 'Notki' };
      if (isDomain) {
        rpConfig.id = hostname;
      }

      const credential = await navigator.credentials.create({
        publicKey: {
          challenge: new Uint8Array(32),
          rp: rpConfig,
          user: {
            id: new TextEncoder().encode(currentUser?.email || 'user'),
            name: currentUser?.email || 'user',
            displayName: currentUser?.email || 'user',
          },
          pubKeyCredParams: [
            { alg: -7, type: 'public-key' },
            { alg: -257, type: 'public-key' },
          ],
          authenticatorSelection: {
            residentKey: 'required',
            requireResidentKey: true,
            userVerification: 'preferred',
          },
          timeout: 60000,
        },
      });

      if (!credential || !credential.response) {
        throw new Error(t('topbar.2fa.passkeyNotSupported'));
      }

      let spkiBuffer = null;
      if (typeof credential.response.getPublicKey === 'function') {
        spkiBuffer = credential.response.getPublicKey();
      } else if (credential.response.attestationObject) {
        // Fallback for WebKit browsers or authenticators that don't expose getPublicKey directly
        spkiBuffer = credential.response.attestationObject;
      }

      if (!spkiBuffer) {
        throw new Error(t('topbar.2fa.passkeyNotSupported'));
      }

      const pubKeyB64 = bufferToBase64(spkiBuffer);
      const defaultName = (typeof WebAssembly === 'object' && /iPad|iPhone|iPod/.test(navigator.userAgent)) ? 'iOS Device' : t('topbar.2fa.passkeyDefaultName');
      const inputName = prompt(t('topbar.2fa.passkeyPromptName'), defaultName);
      const name = (inputName && inputName.trim()) ? inputName.trim() : defaultName;

      await apiRequest('/api/account/passkey', {
        method: 'POST',
        body: JSON.stringify({
          id: credential.id,
          name,
          publicKey: pubKeyB64,
        }),
      });

      await refresh2faStatus();
    } catch (error) {
      if (error.name !== 'NotAllowedError' && error.name !== 'AbortError') {
        alert(error.message);
      }
    }
  });

  async function refresh2faStatus() {
    try {
      const status = await apiRequest('/api/account/2fa');
      if ($('#totp-active-area')) $('#totp-active-area').hidden = !status.hasTotp;
      if ($('#totp-setup-area')) $('#totp-setup-area').hidden = status.hasTotp;
      if ($('#setup-totp-btn')) $('#setup-totp-btn').hidden = status.hasTotp;
      const list = $('#passkey-list');
      if (list) {
        list.innerHTML = '';
        status.passkeys.forEach(pk => {
          const li = document.createElement('li');
          li.style.display = 'flex';
          li.style.justifyContent = 'space-between';
          li.style.alignItems = 'center';
          li.style.padding = '4px 0';

          const nameSpan = document.createElement('span');
          nameSpan.textContent = pk.name + ' (' + new Date(pk.createdAt).toLocaleDateString() + ')';

          const delBtn = document.createElement('button');
          delBtn.textContent = t('topbar.2fa.removePasskey');
          delBtn.className = 'button-secondary';
          delBtn.style.padding = '2px 8px';
          delBtn.addEventListener('click', async () => {
            if (!confirm(t('topbar.2fa.confirmRemovePasskey'))) return;
            await apiRequest(`/api/account/passkey/${encodeURIComponent(pk.id)}`, { method: 'DELETE' });
            refresh2faStatus();
          });

          li.append(nameSpan, delBtn);
          list.append(li);
        });
      }
    } catch (error) {
      console.error(error);
    }
  }

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
      if (node.tagName === 'LI' && node.closest('.task-list')) {
        }
      if (node.tagName === 'P' && node.classList.contains('task-group-label')) {
        safeNode.className = 'task-group-label';
        safeNode.contentEditable = 'false';
      }
      if (node.tagName === 'SPAN' && node.classList.contains('task-drag-handle')) {
        safeNode.className = 'task-drag-handle';
        safeNode.contentEditable = 'false';
        safeNode.setAttribute('aria-label', t('card.drag'));
        safeNode.title = t('card.dragTitle');
        safeNode.textContent = '⠟';
      }
      if (node.tagName === 'SPAN' && (node.classList.contains('task-text')
          || (!node.classList.contains('task-drag-handle') && node.parentElement?.matches('li') && node.parentElement.querySelector('input[type="checkbox"]')))) {
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

  const plainTextCache = new WeakMap();

  // Memoizes extracted plain text for rich-text notes using a WeakMap keyed by the note object.
  // Avoids repeated DOM node creation and HTML sanitization on every keystroke during search/render.
  function noteText(note) {
    if (!note) return '';
    if (note.bodyFormat !== 1) return note.body || '';
    const cached = plainTextCache.get(note);
    if (cached && cached.body === note.body) {
      return cached.text;
    }
    const output = document.createElement('div');
    output.innerHTML = sanitizeRichHtml(note.body);
    const text = (output.innerText || output.textContent || '').replace(/\n{3,}/g, '\n\n');
    plainTextCache.set(note, { body: note.body, text });
    return text;
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
      let dragHandle = item.querySelector(':scope > .task-drag-handle');
      if (!dragHandle) {
        dragHandle = document.createElement('span');
        dragHandle.className = 'task-drag-handle';
        dragHandle.contentEditable = 'false';
        dragHandle.textContent = '⠿';
        dragHandle.setAttribute('aria-label', t('card.drag'));
        dragHandle.title = t('card.dragTitle');
        item.insertBefore(dragHandle, checkbox);
      }
      let text = item.querySelector(':scope > .task-text');
      const strayNodes = [...item.childNodes].filter(node => node !== checkbox && node !== text && node !== dragHandle);
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
    if (event.target.closest?.('.task-drag-handle')) return;
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
    if (event.target.closest?.('.task-drag-handle')) return;
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
    root.querySelectorAll('input.task-checkbox').forEach(cb => {
      if (cb.checked) cb.setAttribute('checked', '');
      else cb.removeAttribute('checked');
    });
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
    const dragHandle = document.createElement('span');
    dragHandle.className = 'task-drag-handle';
    dragHandle.contentEditable = 'false';
    dragHandle.textContent = '⠿';
    dragHandle.setAttribute('aria-label', t('card.drag'));
    dragHandle.title = t('card.dragTitle');

    const checkbox = document.createElement('input');
    checkbox.type = 'checkbox';
    checkbox.className = 'task-checkbox';
    checkbox.contentEditable = 'false';
    checkbox.setAttribute('aria-label', t('editor.checkboxAria'));

    const content = document.createElement('span');
    content.className = 'task-text';
    content.tabIndex = 0;
    content.textContent = '\u00A0';
    item.append(dragHandle, checkbox, content);
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
    const { active, noteId, gapIndex, startIndex, pointerId } = dragState;
    if (event.target && typeof event.target.releasePointerCapture === 'function') {
      try { event.target.releasePointerCapture(pointerId); } catch {}
    }
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

  function queueSync(userId) {
    if (!userId) return;
    try {
      localStorage.setItem(`notki.sync.pending.${userId}`, '1');
    } catch (e) {}
    pendingSync = true;
    updateStorageIndicator();
  }

  function clearSyncQueue(userId) {
    if (!userId) return;
    try {
      localStorage.removeItem(`notki.sync.pending.${userId}`);
    } catch (e) {}
    pendingSync = false;
    updateStorageIndicator();
  }

  function hasPendingSync(userId) {
    if (!userId) return false;
    try {
      return localStorage.getItem(`notki.sync.pending.${userId}`) === '1';
    } catch (e) {
      return false;
    }
  }

  async function syncPendingChanges(force = false) {
    if (!currentUser || isSyncing) return;
    if (!force) {
      if (isOffline) return;
      if (!hasPendingSync(currentUser.id) && !pendingSync) return;
    }

    isSyncing = true;
    updateStorageIndicator();

    try {
      // 1. Fetch remote notes
      const remoteResponse = await apiRequest('/api/notes');
      const remoteNotes = remoteResponse.notes || [];

      // 2. Merge local and remote notes
      // Keyed by ID. If modified dates differ, take the latest.
      const noteMap = new Map();
      remoteNotes.forEach(note => noteMap.set(note.id, note));

      notes.forEach(localNote => {
        const remoteNote = noteMap.get(localNote.id);
        if (!remoteNote) {
          noteMap.set(localNote.id, localNote);
        } else {
          const localTime = Date.parse(localNote.updatedAt) || 0;
          const remoteTime = Date.parse(remoteNote.updatedAt) || 0;
          if (localTime > remoteTime) {
            noteMap.set(localNote.id, localNote);
          }
        }
      });

      const mergedNotes = [...noteMap.values()];
      mergedNotes.forEach((note, index) => { note.order = mergedNotes.length - index; });

      // 3. Save merged list to server
      const snapshot = JSON.stringify({ notes: mergedNotes });
      await apiRequest('/api/notes', { method: 'PUT', body: snapshot });

      // 4. Update memory & cache
      notes = mergedNotes;
      saveLocalCache(currentUser.id, { notes: mergedNotes });
      clearSyncQueue(currentUser.id);
      render();
      if (force) {
        showToast(t('nav.syncSuccess'));
      }
    } catch (err) {
      console.error('Failed syncPendingChanges:', err);
      if (force) {
        showToast(t('nav.syncFailed', { message: err.message || '' }));
      }
    } finally {
      isSyncing = false;
      updateStorageIndicator();
    }
  }

  function persist() {
    notes.forEach((note, index) => { note.order = notes.length - index; });
    if (!currentUser) return;
    saveLocalCache(currentUser.id, { notes });
    queueSync(currentUser.id);
    const snapshot = JSON.stringify({ notes });
    saveQueue = saveQueue.catch(() => {}).then(() => apiRequest('/api/notes', { method: 'PUT', body: snapshot }))
      .then(() => {
        clearSyncQueue(currentUser.id);
      });
    saveQueue.catch(error => {
      if (!isOffline && error.name !== 'TypeError' && error.message !== 'Failed to fetch') {
        showToast(t('editor.saveFailed', { message: error.message }));
      }
    });
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
    const q = query ? query.toLocaleLowerCase() : '';
    if (view === 'shared') {
      const matches = sharedNotes.filter(note => {
        if (!q) return true;
        const searchable = `${note.title} ${noteText(note)} ${(note.tags || []).join(' ')} ${note.ownerEmail || ''}`.toLocaleLowerCase();
        return searchable.includes(q);
      });
      return matches.sort((a, b) => Date.parse(b.updatedAt) - Date.parse(a.updatedAt));
    }
    return notes.filter(note => {
      if (view === 'all' && !isActive(note)) return false;
      if (view === 'pinned' && (!isActive(note) || !note.pinned)) return false;
      if (view === 'archive' && (!note.archived || note.deleted)) return false;
      if (view === 'trash' && !note.deleted) return false;
      if (!q) return true;
      const searchable = `${note.title} ${noteText(note)} ${(note.tags || []).join(' ')}`.toLocaleLowerCase();
      return searchable.includes(q);
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
    const sharedByMeCount = active.filter(note => note.shareCount && note.shareCount > 0).length;
    elements.allCount.textContent = String(active.length);
    elements.pinnedCount.textContent = String(pinned);
    elements.archiveCount.textContent = String(notes.filter(note => note.archived && !note.deleted).length);
    elements.trashCount.textContent = String(notes.filter(note => note.deleted).length);
    elements.sharedCount.textContent = String(sharedNotes.length + sharedByMeCount);
    elements.nav.forEach(button => button.classList.toggle('is-active', button.dataset.view === view));
    elements.navAdmin.classList.toggle('is-active', view === 'admin');

    if (view === 'admin') {
      if (elements.topbar) elements.topbar.hidden = true;
      elements.pageHeading.hidden = true;
      elements.captureWrap.hidden = true;
      elements.notesArea.hidden = true;
      elements.topbarSearch.hidden = true;
      if ($('#view-toggle')) $('#view-toggle').hidden = true;
      elements.adminArea.hidden = false;
      elements.breadcrumb.textContent = t('nav.adminPanel');
      refreshAdmin().catch(() => {});
      window.history.pushState(null, '', '/admin');
    } else {
      if (elements.topbar) elements.topbar.hidden = false;
      elements.pageHeading.hidden = false;
      elements.captureWrap.hidden = false;
      elements.notesArea.hidden = false;
      elements.topbarSearch.hidden = false;
      if ($('#view-toggle')) $('#view-toggle').hidden = false;
      elements.adminArea.hidden = true;
      elements.breadcrumb.textContent = t(NAV_KEYS[view]);
      if (window.location.pathname === '/admin') {
         window.history.pushState(null, '', '/');
      }
      elements.title.replaceChildren(
        document.createTextNode(t(VIEW_KEYS[view])),
        Object.assign(document.createElement('span'), { className: 'heading-period', textContent: '.' }),
      );

      if (view === 'shared') {
        const sharedWithMe = sharedNotes.filter(note => {
          if (!query) return true;
          const searchable = `${note.title} ${noteText(note)} ${(note.tags || []).join(' ')} ${note.ownerEmail || ''}`.toLocaleLowerCase();
          return searchable.includes(query.toLocaleLowerCase());
        }).sort((a, b) => Date.parse(b.updatedAt) - Date.parse(a.updatedAt));

        const sharedByMe = notes.filter(note => {
          if (!isActive(note)) return false;
          if (!note.shareCount || note.shareCount <= 0) return false;
          if (!query) return true;
          const searchable = `${note.title} ${noteText(note)} ${(note.tags || []).join(' ')}`.toLocaleLowerCase();
          return searchable.includes(query.toLocaleLowerCase());
        }).sort((a, b) => Date.parse(b.updatedAt) - Date.parse(a.updatedAt));

        const totalVisible = sharedWithMe.length + sharedByMe.length;

        elements.pinnedGrid.replaceChildren(...sharedWithMe.map(makeCard));
        elements.grid.replaceChildren(...sharedByMe.map(makeCard));

        if ($('#pinned-label-text')) $('#pinned-label-text').textContent = t('section.sharedWithMe');
        elements.pinnedLabel.hidden = sharedWithMe.length === 0;

        elements.otherLabelText.textContent = t('section.sharedByMe');
        elements.otherLabel.hidden = sharedByMe.length === 0;

        elements.empty.hidden = totalVisible !== 0;
        elements.countLabel.textContent = query
          ? t('count.searchResults', { count: totalVisible })
          : `${totalVisible} ${pluralText('count.sharedLabel', totalVisible)}`;
        elements.footerCount.textContent = `${totalVisible} ${pluralText('footer.count', totalVisible)}`;
        updateEmptyState();
        if (activeId) {
          const current = notes.find(note => note.id === activeId) || sharedNotes.find(note => note.id === activeId);
          if (current) updateEditorActions(current);
        }
      } else {
        if ($('#pinned-label-text')) $('#pinned-label-text').textContent = t('section.pinned');
        elements.otherLabelText.textContent = t('section.other');

        const visible = filteredNotes();
        const splitPinned = view === 'all' && !query;
        const pinnedItems = splitPinned ? visible.filter(note => note.pinned) : [];
        const regularItems = splitPinned ? visible.filter(note => !note.pinned) : visible;
        elements.pinnedGrid.replaceChildren(...pinnedItems.map(makeCard));
        elements.grid.replaceChildren(...regularItems.map(makeCard));
        elements.pinnedLabel.hidden = pinnedItems.length === 0;
        elements.otherLabel.hidden = pinnedItems.length === 0 || regularItems.length === 0;
        elements.empty.hidden = visible.length !== 0;
        elements.countLabel.textContent = query
          ? t('count.searchResults', { count: visible.length })
          : `${visible.length} ${pluralText('count.notesLabel', visible.length)}`;
        elements.footerCount.textContent = `${visible.length} ${pluralText('footer.count', visible.length)}`;
        updateEmptyState();
        if (activeId) {
          const current = notes.find(note => note.id === activeId) || sharedNotes.find(note => note.id === activeId);
          if (current) updateEditorActions(current);
        }
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
    const cardTitle = $('.card-title', card);
    cardTitle.textContent = note.title || t('editor.untitled');

    const taskStats = getTaskStats(note);
    if (taskStats.total > 0) {
      const progressEl = document.createElement('div');
      progressEl.className = 'card-progress';
      progressEl.innerHTML = `
        <div class="card-progress-track">
          <div class="card-progress-fill${taskStats.percent === 100 ? ' is-complete' : ''}" style="width: ${taskStats.percent}%"></div>
        </div>
        <span class="card-progress-text">${taskStats.completed}/${taskStats.total} (${taskStats.percent}%)</span>
      `;
      cardTitle.after(progressEl);
    }

    const cardBody = $('.card-body', card);
    if (note.bodyFormat === 1 && note.body) {
      cardBody.innerHTML = sanitizeRichHtml(note.body);
    } else {
      cardBody.textContent = noteText(note) || t('editor.emptyNote');
    }
    const shareBtn = $('.card-share', card);
    const isSharedOut = Boolean(note.shareCount && note.shareCount > 0);
    if (shareBtn) {
      if (shared || isSharedOut) {
        shareBtn.classList.add('is-shared');
        shareBtn.hidden = false;
      } else {
        shareBtn.hidden = note.archived || note.deleted || view === 'archive' || view === 'trash';
      }
      shareBtn.addEventListener('click', event => {
        event.stopPropagation();
        openShare(note.id);
      });
    }

    const pin = $('.card-pin', card);
    pin.classList.toggle('is-pinned', note.pinned);
    pin.setAttribute('aria-label', t(note.pinned ? 'editor.unpin' : 'editor.pin'));
    pin.title = t(note.pinned ? 'editor.unpinTitle' : 'editor.pinTitle');
    pin.hidden = note.archived || note.deleted || shared || view === 'archive' || view === 'trash';
    pin.addEventListener('click', event => {
      event.stopPropagation();
      if (note.archived || note.deleted || view === 'archive' || view === 'trash') return;
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
      if (document.activeElement && document.activeElement instanceof HTMLElement && document.activeElement !== document.body) {
        document.activeElement.blur();
      }
      try { dragHandle.setPointerCapture(event.pointerId); } catch {}
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
    const swipeBgRight = $('.card-swipe-right', card);
    const swipeBgLeft = $('.card-swipe-left', card);
    const labelRight = $('.card-swipe-label-right', card);
    const labelLeft = $('.card-swipe-label-left', card);
    const iconLeft = $('.card-swipe-icon-left', card);
    const iconRight = $('.card-swipe-icon-right', card);

    if (labelRight) {
      if (view === 'archive' || view === 'trash') labelRight.textContent = t('editor.unarchiveTitle');
      else labelRight.textContent = t(note.pinned ? 'editor.unpinTitle' : 'editor.pinTitle');
    }
    if (iconRight) {
      if (view === 'archive' || view === 'trash') iconRight.textContent = '↺';
      else iconRight.textContent = '📌';
    }
    if (labelLeft) {
      if (view === 'trash') labelLeft.textContent = t('editor.deleteForeverTitle');
      else if (view === 'archive') labelLeft.textContent = t('editor.deleteTitle');
      else labelLeft.textContent = t('editor.archiveTitle');
    }
    if (iconLeft) {
      if (view === 'trash') iconLeft.textContent = '🗑';
      else if (view === 'archive') iconLeft.textContent = '🗑';
      else iconLeft.textContent = '📦';
    }

    const cardInner = $('.card-inner', card);
    let cardSwipeState = null;

    card.addEventListener('pointerdown', event => {
      if (readOnly) return;
      if (event.button !== 0) return;
      if (event.target.closest('button, input, .task-checkbox, .task-drag-handle, .card-drag, .card-pin, .card-tag, .card-share')) return;

      cardSwipeState = {
        pointerId: event.pointerId,
        startX: event.clientX,
        startY: event.clientY,
        deltaX: 0,
        deltaY: 0,
        swiping: false,
        direction: null,
        disqualified: false,
      };
    });

    card.addEventListener('pointermove', event => {
      if (!cardSwipeState || cardSwipeState.disqualified || event.pointerId !== cardSwipeState.pointerId) return;

      const deltaX = event.clientX - cardSwipeState.startX;
      const deltaY = event.clientY - cardSwipeState.startY;

      if (!cardSwipeState.swiping) {
        if (Math.abs(deltaY) > 10 && Math.abs(deltaY) > Math.abs(deltaX)) {
          cardSwipeState.disqualified = true;
          return;
        }
        if (Math.abs(deltaX) > 10 && Math.abs(deltaX) > Math.abs(deltaY)) {
          cardSwipeState.swiping = true;
          card.classList.add('is-swiping');
          try { card.setPointerCapture(event.pointerId); } catch {}
        }
      }

      if (cardSwipeState.swiping) {
        event.preventDefault();
        cardSwipeState.deltaX = deltaX;
        const width = card.getBoundingClientRect().width || 200;
        const maxSwipe = width * 0.7;
        const maxSwipeRight = maxSwipe;
        const clampedX = Math.max(-maxSwipe, Math.min(maxSwipeRight, deltaX));
        cardInner.style.transform = `translateX(${clampedX}px)`;

        const SWIPE_THRESHOLD = 70;
        if (clampedX > 0) {
          swipeBgRight.classList.add('is-visible');
          swipeBgLeft.classList.remove('is-visible');
          swipeBgRight.classList.toggle('is-active', clampedX >= SWIPE_THRESHOLD);
        } else if (clampedX < 0) {
          swipeBgLeft.classList.add('is-visible');
          swipeBgRight.classList.remove('is-visible');
          swipeBgLeft.classList.toggle('is-active', Math.abs(clampedX) >= SWIPE_THRESHOLD);
        } else {
          swipeBgRight.classList.remove('is-visible');
          swipeBgLeft.classList.remove('is-visible');
        }
      }
    });

    let wasSwiping = false;

    const finishSwipe = (event) => {
      if (!cardSwipeState || event.pointerId !== cardSwipeState.pointerId) return;
      const { swiping, deltaX } = cardSwipeState;
      const pointerId = cardSwipeState.pointerId;
      cardSwipeState = null;

      if (swiping) {
        wasSwiping = true;
        window.setTimeout(() => { wasSwiping = false; }, 300);

        card.classList.remove('is-swiping');
        try { card.releasePointerCapture(pointerId); } catch {}
        cardInner.style.transform = '';
        swipeBgRight.classList.remove('is-visible', 'is-active');
        swipeBgLeft.classList.remove('is-visible', 'is-active');

        const SWIPE_THRESHOLD = 70;
        if (deltaX >= SWIPE_THRESHOLD) {
          // Swipe Right: Restore (Archive/Trash) or Pin/Unpin (Notes)
          if (view === 'trash') {
            note.deleted = false;
            note.archived = false;
            note.pinned = false;
            note.updatedAt = new Date().toISOString();
            moveToFront(note);
            persist();
            showToast(t('editor.restoredToast'));
            render();
          } else if (view === 'archive') {
            note.archived = false;
            note.deleted = false;
            note.pinned = false;
            note.updatedAt = new Date().toISOString();
            moveToFront(note);
            persist();
            showToast(t('editor.unarchivedToast'));
            render();
          } else if (!note.archived && !note.deleted) {
            note.pinned = !note.pinned;
            note.updatedAt = new Date().toISOString();
            moveToFront(note);
            persist();
            showToast(t(note.pinned ? 'editor.pin' : 'editor.unpin'));
            render();
          }
        } else if (deltaX <= -SWIPE_THRESHOLD) {
          // Swipe Left: Archive / Trash / Delete
          if (view === 'trash') {
            notes = notes.filter(item => item.id !== note.id);
            showToast(t('editor.deletedToast'));
          } else if (view === 'archive') {
            note.deleted = true;
            note.pinned = false;
            note.archived = false;
            note.updatedAt = new Date().toISOString();
            showToast(t('editor.trashedToast'));
          } else {
            note.archived = !note.archived;
            if (note.archived) note.pinned = false;
            note.updatedAt = new Date().toISOString();
            showToast(t(note.archived ? 'editor.archivedToast' : 'editor.unarchivedToast'));
          }
          persist();
          render();
        }
      }
    };

    card.addEventListener('pointerup', finishSwipe);
    card.addEventListener('pointercancel', finishSwipe);

    card.addEventListener('click', event => {
      if (wasSwiping || (cardSwipeState && cardSwipeState.swiping)) {
        event.stopPropagation();
        event.preventDefault();
        return;
      }
      if (event.target.closest('input[type="checkbox"], .task-checkbox, .task-drag-handle')) return;
      if (event.target.closest('button')) return;
      if (event.target.closest('.card-drag, .card-pin')) return;
      openEditor(note.id);
    });

    let cardTaskDragItem = null;
    let cardTaskPointerId = null;
    let cardTaskDragPreview = null;
    let cardTaskDragFrame = null;
    let cardTaskOffsetX = 0;
    let cardTaskOffsetY = 0;

    card.addEventListener('pointerdown', event => {
      if (readOnly) return;
      const handle = event.target.closest?.('.task-drag-handle');
      if (!handle) return;
      const item = handle.closest('li');
      if (!item || !item.closest('ul.task-list')) return;

      event.preventDefault();
      event.stopPropagation();
      if (document.activeElement && document.activeElement instanceof HTMLElement && document.activeElement !== document.body) {
        document.activeElement.blur();
      }
      cleanupAllTaskDrags();
      cardTaskDragItem = item;
      cardTaskPointerId = event.pointerId;
      const itemRect = item.getBoundingClientRect();
      cardTaskOffsetX = event.clientX - itemRect.left;
      cardTaskOffsetY = event.clientY - itemRect.top;

      item.classList.add('is-dragging-task');
      document.body.classList.add('is-dragging-task-active');
      cardTaskDragPreview = document.createElement('div');
      cardTaskDragPreview.className = 'task-drag-preview';
      cardTaskDragPreview.style.width = `${itemRect.width}px`;
      const isChecked = item.querySelector('.task-checkbox')?.checked;
      const cDownContent = item.querySelector('.task-text')?.textContent || '';
      cardTaskDragPreview.innerHTML = `<span class="task-drag-handle">⠿</span><input type="checkbox" class="task-checkbox"${isChecked ? ' checked' : ''} disabled><span class="task-text">${cDownContent}</span>`;
      cardTaskDragPreview.style.transform = `translate3d(${event.clientX - cardTaskOffsetX}px, ${event.clientY - cardTaskOffsetY}px, 0)`;
      document.body.append(cardTaskDragPreview);

      const onCardPointerMove = (e) => {
        if (!cardTaskDragItem || e.pointerId !== cardTaskPointerId) return;
        if (!cardTaskDragFrame) {
          cardTaskDragFrame = requestAnimationFrame(() => {
            cardTaskDragFrame = null;
            if (!cardTaskDragPreview) return;
            cardTaskDragPreview.style.transform = `translate3d(${e.clientX - cardTaskOffsetX}px, ${e.clientY - cardTaskOffsetY}px, 0)`;

            const list = cardTaskDragItem.closest('ul.task-list');
            if (!list) return;

            const elemBelow = document.elementFromPoint(e.clientX, e.clientY);
            const target = elemBelow?.closest?.('li');
            if (!target || target === cardTaskDragItem || target.closest('ul.task-list') !== list) return;

            const rect = target.getBoundingClientRect();
            const mid = rect.top + rect.height / 2;
            if (e.clientY < mid) {
              target.before(cardTaskDragItem);
            } else {
              target.after(cardTaskDragItem);
            }
          });
        }
      };

      const endCardTaskPointerDrag = (e) => {
        if (!cardTaskDragItem || (e && cardTaskPointerId !== null && e.pointerId !== cardTaskPointerId)) return;
        window.removeEventListener('pointermove', onCardPointerMove);
        window.removeEventListener('pointerup', endCardTaskPointerDrag);
        window.removeEventListener('pointercancel', endCardTaskPointerDrag);

        try { handle.releasePointerCapture(cardTaskPointerId); } catch {}
        cleanupAllTaskDrags();
        cardTaskDragItem = null;
        cardTaskPointerId = null;

        const cardBody = $('.card-body', card);
        const wrapper = document.createElement('div');
        wrapper.innerHTML = cardBody.innerHTML;
        normalizeChecklistGroups(wrapper);
        note.body = sanitizeRichHtml(wrapper.innerHTML);
        note.updatedAt = new Date().toISOString();
        if (shared && !readOnly) {
          persistShared(note);
        } else {
          persist();
        }
        const cardDate = $('.card-date', card);
        if (cardDate) cardDate.textContent = window.i18n.formatDate(note.updatedAt);
        if (cardBody) {
          if (note.bodyFormat === 1 && note.body) {
            cardBody.innerHTML = sanitizeRichHtml(note.body);
          } else {
            cardBody.textContent = noteText(note) || t('editor.emptyNote');
          }
        }
      };

      window.addEventListener('pointermove', onCardPointerMove);
      window.addEventListener('pointerup', endCardTaskPointerDrag);
      window.addEventListener('pointercancel', endCardTaskPointerDrag);

      try { handle.setPointerCapture(event.pointerId); } catch {}
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
          const cardDate = $('.card-date', card);
          if (cardDate) cardDate.textContent = window.i18n.formatDate(note.updatedAt);

          const taskStats = getTaskStats(note);
          let progressEl = $('.card-progress', card);
          if (taskStats.total > 0) {
            if (!progressEl) {
              progressEl = document.createElement('div');
              progressEl.className = 'card-progress';
              const cardTitle = $('.card-title', card);
              if (cardTitle) cardTitle.after(progressEl);
            }
            progressEl.innerHTML = `
              <div class="card-progress-track">
                <div class="card-progress-fill${taskStats.percent === 100 ? ' is-complete' : ''}" style="width: ${taskStats.percent}%"></div>
              </div>
              <span class="card-progress-text">${taskStats.completed}/${taskStats.total} (${taskStats.percent}%)</span>
            `;
          } else if (progressEl) {
            progressEl.remove();
          }

          const cardBody = $('.card-body', card);
          if (cardBody) {
            if (note.bodyFormat === 1 && note.body) {
              cardBody.innerHTML = sanitizeRichHtml(note.body);
            } else {
              cardBody.textContent = noteText(note) || t('editor.emptyNote');
            }
          }
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
    updateEditorProgress();
    $('#task-restore-suggestions').replaceChildren();
    $('#task-restore-suggestions').hidden = true;
    renderLabels(note.tags || []);
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


  function renderLabels(activeTags = []) {
    elements.labelsContainer.replaceChildren();
    const combined = [...new Set([...userLabels, ...(activeTags || [])])];
    combined.forEach(label => {
      const chip = document.createElement('button');
      chip.type = 'button';
      chip.className = 'label-chip';
      if (activeTags.includes(label)) {
        chip.classList.add('is-active');
      }
      chip.textContent = label;
      chip.dataset.label = label;
      chip.addEventListener('click', () => {
        const note = notes.find(item => item.id === activeId) || sharedNotes.find(item => item.id === activeId);
        if (note && note.ownerEmail && note.permission !== 'write') return; // Readonly check
        chip.classList.toggle('is-active');
        scheduleSave();
      });
      elements.labelsContainer.append(chip);
    });
  }

  function openLabelsModal() {
    document.getElementById('labels-panel').hidden = false;
    document.getElementById('labels-panel').classList.add('is-open');
    document.getElementById('labels-panel').setAttribute('aria-hidden', 'false');
    document.getElementById('labels-backdrop').hidden = false;
    renderLabelsEditList();
  }

  function closeLabelsModal() {
    document.getElementById('labels-panel').classList.remove('is-open');
    document.getElementById('labels-panel').setAttribute('aria-hidden', 'true');
    document.getElementById('labels-panel').hidden = true;
    document.getElementById('labels-backdrop').hidden = true;
  }

  function renderLabelsEditList() {
    const list = document.getElementById('labels-edit-list');
    list.replaceChildren();
    userLabels.forEach((label, index) => {
      const item = document.createElement('div');
      item.style.display = 'flex';
      item.style.justifyContent = 'space-between';
      item.style.alignItems = 'center';
      item.style.gap = '8px';
      item.style.padding = '6px 8px';
      item.style.border = '1px solid var(--line)';
      item.style.borderRadius = '5px';

      const input = document.createElement('input');
      input.className = 'auth-input label-edit-input';
      input.type = 'text';
      input.value = label;
      input.maxLength = 80;
      input.style.flex = '1';
      input.style.height = '34px';

      const saveLabelChange = async () => {
        const oldLabel = label;
        const newLabel = input.value.trim().toLowerCase();
        if (!newLabel) {
          input.value = oldLabel;
          return;
        }
        if (newLabel === oldLabel) return;
        if (userLabels.some((l, i) => i !== index && l === newLabel)) {
          showToast(t('labels.alreadyExists') || 'Label already exists.');
          input.value = oldLabel;
          return;
        }

        userLabels[index] = newLabel;

        try {
          await apiRequest('/api/account/labels', {
            method: 'POST',
            body: JSON.stringify({ labels: userLabels })
          });

          let notesUpdated = false;
          notes.forEach(note => {
            if (Array.isArray(note.tags) && note.tags.includes(oldLabel)) {
              note.tags = note.tags.map(t => t === oldLabel ? newLabel : t);
              notesUpdated = true;
            }
          });

          if (notesUpdated) {
            persist();
          }

          renderLabelsEditList();
          render();
          if (activeId) {
            const note = notes.find(item => item.id === activeId) || sharedNotes.find(item => item.id === activeId);
            if (note) renderLabels(note.tags || []);
          }
        } catch (error) {
          showToast(error.message);
          input.value = oldLabel;
        }
      };

      input.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
          e.preventDefault();
          input.blur();
        }
      });
      input.addEventListener('blur', saveLabelChange);

      const delBtn = document.createElement('button');
      delBtn.className = 'share-revoke';
      delBtn.type = 'button';
      delBtn.textContent = t('labels.remove');
      delBtn.addEventListener('click', async () => {
        userLabels = userLabels.filter((_, i) => i !== index);
        try {
          await apiRequest('/api/account/labels', {
            method: 'POST',
            body: JSON.stringify({ labels: userLabels })
          });
          renderLabelsEditList();
          if (activeId) {
            const note = notes.find(item => item.id === activeId) || sharedNotes.find(item => item.id === activeId);
            if (note) renderLabels(note.tags || []);
          }
        } catch (error) {
          showToast(error.message);
        }
      });

      item.append(input, delBtn);
      list.append(item);
    });
  }

  $('#edit-labels').addEventListener('click', openLabelsModal);
  $('#nav-labels').addEventListener('click', openLabelsModal);
  $('#close-labels').addEventListener('click', closeLabelsModal);
  $('#labels-backdrop').addEventListener('click', closeLabelsModal);

  $('#add-label-form').addEventListener('submit', async event => {
    event.preventDefault();
    const input = document.getElementById('new-label-input');
    const newLabel = input.value.trim();
    if (!newLabel || userLabels.includes(newLabel)) return;

    userLabels.push(newLabel);
    input.value = '';

    try {
      await apiRequest('/api/account/labels', {
        method: 'POST',
        body: JSON.stringify({ labels: userLabels })
      });
      renderLabelsEditList();
      if (activeId) {
        const note = notes.find(item => item.id === activeId) || sharedNotes.find(item => item.id === activeId);
        if (note) renderLabels(note.tags || []);
      }
    } catch (error) {
      showToast(error.message);
    }
  });

  function hasEditorContent() {
    return Boolean(
      elements.noteTitle.value.trim()
      || [...elements.labelsContainer.querySelectorAll('.label-chip.is-active')].length > 0
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
    note.tags = [...elements.labelsContainer.querySelectorAll('.label-chip.is-active')].map(chip => chip.dataset.label);
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
    saveQueue = saveQueue.catch(() => {}).then(() => apiRequest(`/api/shared/${encodeURIComponent(note.id)}`, { method: 'PUT', body: payload }))
      .then(() => {
        if (currentUser) saveLocalCache(currentUser.id, { sharedNotes });
      });
    saveQueue.catch(error => {
      if (!isOffline && error.name !== 'TypeError' && error.message !== 'Failed to fetch') {
        showToast(t('editor.saveFailed', { message: error.message }));
      }
    });
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

    const ARCHIVE_ICON_SVG = '<svg viewBox="0 0 24 24" width="1em" height="1em" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="21 8 21 21 3 21 3 8"/><rect x="1" y="3" width="22" height="5"/><line x1="10" y1="12" x2="14" y2="12"/></svg>';
    const RESTORE_ICON_SVG = '<svg viewBox="0 0 24 24" width="1em" height="1em" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="1 4 1 10 7 10"/><path d="M3.51 15a9 9 0 1 0 2.13-9.36L1 10"/></svg>';

    elements.archive.innerHTML = (note.deleted || note.archived) ? RESTORE_ICON_SVG : ARCHIVE_ICON_SVG;
    elements.archive.setAttribute('aria-label', t(note.deleted ? 'editor.restoreTrash' : note.archived ? 'editor.unarchive' : 'editor.archive'));
    elements.archive.title = t(note.deleted || note.archived ? 'editor.unarchiveTitle' : 'editor.archiveTitle');
    elements.delete.setAttribute('aria-label', t(note.deleted ? 'editor.deleteForever' : 'editor.delete'));
    elements.delete.title = t(note.deleted ? 'editor.deleteForever' : 'editor.delete');
    // A recipient never gets the owner's pin, archive, delete or re-share controls.
    // Pinning is also disabled in archive and trash.
    elements.pin.hidden = note.archived || note.deleted || shared || view === 'archive' || view === 'trash';
    elements.archive.hidden = shared;
    elements.delete.hidden = shared;
    $('#share-note').hidden = note.deleted || shared;
    elements.noteTitle.readOnly = readOnly;
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
        document.execCommand('insertHTML', false, `<ul class="task-list"><li><span class="task-drag-handle" contenteditable="false" aria-label="Drag task" title="Drag to reorder">⠿</span><input type="checkbox" class="task-checkbox" contenteditable="false" aria-label="${t('editor.checkboxAria')}"><span class="task-text" tabindex="0">&#8203;</span></li></ul>`);
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
    const checkbox = event.target.closest?.('input[type="checkbox"], .task-checkbox');
    if (checkbox) {
      if (document.activeElement && document.activeElement instanceof HTMLElement && document.activeElement !== document.body) {
        document.activeElement.blur();
      }
      event.preventDefault();
      checkbox.checked = !checkbox.checked;
      checkbox.dispatchEvent(new Event('change', { bubbles: true }));
      return;
    }
    if (event.target.closest?.('.task-drag-handle')) {
      if (document.activeElement && document.activeElement instanceof HTMLElement && document.activeElement !== document.body) {
        document.activeElement.blur();
      }
      event.preventDefault();
      return;
    }
    if (event.button === 0) placeTaskCaretFromPointer(event);
  });
  elements.noteBody.addEventListener('change', event => {
    if (event.target.matches('input[type="checkbox"]')) {
      normalizeChecklistGroups();
      $('#task-restore-suggestions').hidden = true;
      updateEditorProgress();
      scheduleSave();
    }
  });

  let taskDragItem = null;
  let taskPointerId = null;
  let taskDragPreview = null;
  let taskDragFrame = null;
  let taskOffsetX = 0;
  let taskOffsetY = 0;

  elements.noteBody.addEventListener('dragstart', event => {
    const item = event.target.closest?.('li');
    if (!item || !item.closest('ul.task-list')) return;
    cleanupAllTaskDrags();
    taskDragItem = item;
    const itemRect = item.getBoundingClientRect();
    taskOffsetX = event.clientX - itemRect.left;
    taskOffsetY = event.clientY - itemRect.top;
    event.dataTransfer.effectAllowed = 'move';
    item.classList.add('is-dragging-task');
    document.body.classList.add('is-dragging-task-active');
    taskDragPreview = document.createElement('div');
    taskDragPreview.className = 'task-drag-preview';
    taskDragPreview.style.width = `${itemRect.width}px`;
    const isChecked = item.querySelector('.task-checkbox')?.checked;
    const dragStartTextContent = item.querySelector('.task-text')?.textContent || '';
    taskDragPreview.innerHTML = `<span class="task-drag-handle">⠿</span><input type="checkbox" class="task-checkbox"${isChecked ? ' checked' : ''} disabled><span class="task-text">${dragStartTextContent}</span>`;
    taskDragPreview.style.transform = `translate3d(${event.clientX - taskOffsetX}px, ${event.clientY - taskOffsetY}px, 0)`;
    document.body.append(taskDragPreview);
    const emptyImage = new Image();
    emptyImage.src = 'data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7';
    event.dataTransfer.setDragImage(emptyImage, 0, 0);
  });

  elements.noteBody.addEventListener('dragover', event => {
    if (!taskDragItem) return;
    event.preventDefault();
    if (taskDragPreview) {
      taskDragPreview.style.transform = `translate3d(${event.clientX - taskOffsetX}px, ${event.clientY - taskOffsetY}px, 0)`;
    }
    event.dataTransfer.dropEffect = 'move';
    const list = taskDragItem.closest('ul.task-list');
    const target = event.target.closest?.('li');
    if (!target || target === taskDragItem || target.closest('ul.task-list') !== list) return;

    const rect = target.getBoundingClientRect();
    const mid = rect.top + rect.height / 2;
    if (event.clientY < mid) {
      target.before(taskDragItem);
    } else {
      target.after(taskDragItem);
    }
  });

  elements.noteBody.addEventListener('dragend', () => {
    cleanupAllTaskDrags();
    taskDragItem = null;
    normalizeChecklistGroups();
    scheduleSave();
  });

  // Pointer event support for touch/mouse handle dragging in task list
  elements.noteBody.addEventListener('pointerdown', event => {
    const handle = event.target.closest?.('.task-drag-handle');
    if (!handle) return;
    const item = handle.closest('li');
    if (!item || !item.closest('ul.task-list')) return;

    event.preventDefault();
    event.stopPropagation();
    if (document.activeElement && document.activeElement instanceof HTMLElement && document.activeElement !== document.body) {
      document.activeElement.blur();
    }
    cleanupAllTaskDrags();
    taskDragItem = item;
    taskPointerId = event.pointerId;
    const itemRect = item.getBoundingClientRect();
    taskOffsetX = event.clientX - itemRect.left;
    taskOffsetY = event.clientY - itemRect.top;

    item.classList.add('is-dragging-task');
    document.body.classList.add('is-dragging-task-active');
    taskDragPreview = document.createElement('div');
    taskDragPreview.className = 'task-drag-preview';
    taskDragPreview.style.width = `${itemRect.width}px`;
    const isChecked = item.querySelector('.task-checkbox')?.checked;
    const pDownContent = item.querySelector('.task-text')?.textContent || '';
    taskDragPreview.innerHTML = `<span class="task-drag-handle">⠿</span><input type="checkbox" class="task-checkbox"${isChecked ? ' checked' : ''} disabled><span class="task-text">${pDownContent}</span>`;
    taskDragPreview.style.transform = `translate3d(${event.clientX - taskOffsetX}px, ${event.clientY - taskOffsetY}px, 0)`;
    document.body.append(taskDragPreview);

    const onTaskPointerMove = (e) => {
      if (!taskDragItem || e.pointerId !== taskPointerId) return;
      if (!taskDragFrame) {
        taskDragFrame = requestAnimationFrame(() => {
          taskDragFrame = null;
          if (!taskDragPreview) return;
          taskDragPreview.style.transform = `translate3d(${e.clientX - taskOffsetX}px, ${e.clientY - taskOffsetY}px, 0)`;

          const list = taskDragItem.closest('ul.task-list');
          if (!list) return;

          const elemBelow = document.elementFromPoint(e.clientX, e.clientY);
          const target = elemBelow?.closest?.('li');
          if (!target || target === taskDragItem || target.closest('ul.task-list') !== list) return;

          const rect = target.getBoundingClientRect();
          const mid = rect.top + rect.height / 2;
          if (e.clientY < mid) {
            target.before(taskDragItem);
          } else {
            target.after(taskDragItem);
          }
        });
      }
    };

    const endTaskPointerDrag = (e) => {
      if (!taskDragItem || (e && taskPointerId !== null && e.pointerId !== taskPointerId)) return;
      window.removeEventListener('pointermove', onTaskPointerMove);
      window.removeEventListener('pointerup', endTaskPointerDrag);
      window.removeEventListener('pointercancel', endTaskPointerDrag);

      try { handle.releasePointerCapture(taskPointerId); } catch {}
      cleanupAllTaskDrags();
      taskDragItem = null;
      taskPointerId = null;
      normalizeChecklistGroups();
      scheduleSave();
    };

    window.addEventListener('pointermove', onTaskPointerMove);
    window.addEventListener('pointerup', endTaskPointerDrag);
    window.addEventListener('pointercancel', endTaskPointerDrag);

    try { handle.setPointerCapture(event.pointerId); } catch {}
  });

  $('#capture-note').addEventListener('click', () => openEditor());
  $('#fab-add-note').addEventListener('click', () => openEditor());

  if (window.IntersectionObserver) {
    const fabObserver = new IntersectionObserver((entries) => {
      const isVisible = entries[0].isIntersecting;
      // Only show FAB if capture box is not visible AND we are not in admin view
      if (!isVisible && view !== 'admin') {
        $('#fab-add-note').hidden = false;
      } else {
        $('#fab-add-note').hidden = true;
      }
    }, { threshold: 0 });
    if (elements.captureWrap) fabObserver.observe(elements.captureWrap);

    // Also re-check on view changes
    const originalRender = render;
    render = function() {
      originalRender();
      if (view === 'admin') {
        $('#fab-add-note').hidden = true;
      } else if (elements.captureWrap) {
        const rect = elements.captureWrap.getBoundingClientRect();
        const isVisible = rect.bottom > 0 && rect.top < window.innerHeight;
        $('#fab-add-note').hidden = isVisible;
      }
    };
  }
  $('#empty-create').addEventListener('click', () => openEditor());
  $('#close-editor').addEventListener('click', closeEditor);
  elements.backdrop.addEventListener('click', closeEditor);

  let listViewPref = localStorage.getItem('notki.list-view') === '1';
  function applyViewPref() {
    elements.pinnedGrid.classList.toggle('is-list-view', listViewPref);
    elements.grid.classList.toggle('is-list-view', listViewPref);
    $('#view-toggle').textContent = listViewPref ? '▦' : '▤';
  }
  applyViewPref();

  $('#view-toggle').addEventListener('click', () => {
    listViewPref = !listViewPref;
    localStorage.setItem('notki.list-view', listViewPref ? '1' : '0');
    applyViewPref();
  });

  function closeSidebar() {
    elements.sidebar?.classList.remove('is-open');
    if (elements.sidebarBackdrop) elements.sidebarBackdrop.hidden = true;
    if (elements.hamburgerToggle) elements.hamburgerToggle.setAttribute('aria-expanded', 'false');
  }

  function toggleSidebar() {
    if (elements.sidebar?.classList.contains('is-open')) {
      closeSidebar();
    } else {
      elements.sidebar?.classList.add('is-open');
      if (elements.sidebarBackdrop) elements.sidebarBackdrop.hidden = false;
      if (elements.hamburgerToggle) elements.hamburgerToggle.setAttribute('aria-expanded', 'true');
    }
  }

  const handleManualSync = () => syncPendingChanges(true);
  elements.topbarSyncBtn?.addEventListener('click', handleManualSync);

  $('#toggle-writer-mode')?.addEventListener('click', () => {
    const isWriter = elements.panel.classList.toggle('is-writer-mode');
    const toggleBtn = $('#toggle-writer-mode');
    if (toggleBtn) {
      toggleBtn.classList.toggle('is-active', isWriter);
      const labelKey = isWriter ? 'editor.writerModeExit' : 'editor.writerMode';
      const labelText = t(labelKey);
      toggleBtn.setAttribute('aria-label', labelText);
      toggleBtn.title = labelText;
      toggleBtn.innerHTML = isWriter
        ? '<svg viewBox="0 0 24 24" width="1em" height="1em" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="4 14 10 14 10 20"/><polyline points="20 10 14 10 14 4"/><line x1="14" y1="10" x2="21" y2="3"/><line x1="10" y1="14" x2="3" y2="21"/></svg>'
        : '<svg viewBox="0 0 24 24" width="1em" height="1em" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="15 3 21 3 21 9"/><polyline points="9 21 3 21 3 15"/><line x1="21" y1="3" x2="14" y2="10"/><line x1="3" y1="21" x2="10" y2="14"/></svg>';
    }
  });

  elements.hamburgerToggle?.addEventListener('click', toggleSidebar);
  elements.sidebarBackdrop?.addEventListener('click', closeSidebar);

  elements.navAdmin.addEventListener('click', () => {
    if (activeId) closeEditor();
    closeLabelsModal();
    closeSidebar();
    view = 'admin';
    render();
  });
  elements.adminLink.addEventListener('click', (e) => {
    e.preventDefault();
    $('#settings-menu').open = false;
    if (activeId) closeEditor();
    closeLabelsModal();
    closeSidebar();
    view = 'admin';
    render();
  });

  elements.nav.forEach(button => button.addEventListener('click', () => {
    if (activeId) closeEditor();
    if (button.id !== 'nav-labels') closeLabelsModal();
    closeSidebar();
    if (button.dataset.view) {
      view = button.dataset.view;
      render();
    }
  }));
  elements.search.addEventListener('input', () => {
    query = elements.search.value.trim();
    render();
  });
  [elements.noteTitle, elements.noteBody].forEach(input => input.addEventListener('input', event => {
    if (input === elements.noteBody) {
      normalizeChecklistItemMarkup();
      updateWordCount();
      updateEditorProgress();
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
    if (!note || note.archived || note.deleted || view === 'archive' || view === 'trash') return;
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
    if (menu?.open && !menu.contains(event.target) && !elements.noteBody.contains(event.target) && !event.target.closest('.editor-panel')) menu.open = false;
    const sidebarMenu = $('#sidebar-user-menu');
    if (sidebarMenu?.open && !sidebarMenu.contains(event.target)) sidebarMenu.open = false;
  });
  window.addEventListener('blur', cleanupAllTaskDrags);
  window.addEventListener('pointercancel', cleanupAllTaskDrags);

  document.addEventListener('keydown', event => {
    if (event.key === 'Escape' && !elements.sharePanel.hidden && elements.sharePanel.classList.contains('is-open')) {
      closeShare();
      return;
    }
    if (event.key === 'Escape' && !elements.profilePanel.hidden && elements.profilePanel.classList.contains('is-open')) {
      closeProfile();
      return;
    }
    const labelsPanel = $('#labels-panel');
    if (event.key === 'Escape' && labelsPanel && !labelsPanel.hidden && labelsPanel.classList.contains('is-open')) {
      closeLabelsModal();
      return;
    }
    if (event.key === 'Escape' && $('#sidebar-user-menu')?.open) {
      $('#sidebar-user-menu').open = false;
      return;
    }
    if (event.key === 'Escape' && elements.sidebar?.classList.contains('is-open')) {
      closeSidebar();
      return;
    }
    if (event.key === 'Escape' && $('#settings-menu')?.open) {
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
    const daysInput = document.querySelector('#invite-days');
    const days = daysInput ? parseInt(daysInput.value, 10) || 7 : 7;
    try {
      const invite = await apiRequest('/api/admin/invites', { method: 'POST', body: JSON.stringify({ days }) });
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

  initializeApp();

  let currentTarballUrl = null;

  document.querySelector('#check-update')?.addEventListener('click', async event => {
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

  function showUpdateLoadingOverlay() {
    const backdrop = document.querySelector('#update-loading-backdrop');
    if (backdrop) backdrop.hidden = false;
  }

  async function pollServerUntilOnline() {
    const maxAttempts = 60;
    for (let attempt = 0; attempt < maxAttempts; attempt++) {
      await new Promise(resolve => setTimeout(resolve, 2000));
      try {
        const response = await fetch('/api/setup/status', { cache: 'no-store' });
        if (response.ok) {
          window.location.reload();
          return;
        }
      } catch {
        // Server still restarting / unreachable
      }
    }
    window.location.reload();
  }

  document.querySelector('#perform-update')?.addEventListener('click', async event => {
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
      showUpdateLoadingOverlay();
      pollServerUntilOnline();
    } catch (error) {
      message.textContent = error.message;
      message.classList.add('is-error');
      button.disabled = false;
    }
  });

  document.querySelector('#copy-invite')?.addEventListener('click', async event => {
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

  const handleCreateBackup = async event => {
    if (event) event.preventDefault();
    const button = document.querySelector('#create-backup');
    if (button) button.disabled = true;
    setBackupMessage(t('admin.backups.creating'));
    try {
      const backup = await apiRequest('/api/admin/backups', {
        method: 'POST',
        body: '{}'
      });
      setBackupMessage(t('admin.backups.created', { filename: backup.filename }));
      await refreshAdmin();
    } catch (error) {
      setBackupMessage(error.message, true);
    } finally {
      if (button) button.disabled = false;
    }
  };

  document.querySelector('#backup-form')?.addEventListener('submit', handleCreateBackup);

  document.querySelector('#restore-file-btn')?.addEventListener('click', async () => {
    const fileInput = document.querySelector('#restore-file-input');
    const file = fileInput?.files?.[0];
    if (!file) {
      setBackupMessage(t('admin.backups.noFileSelected'), true);
      return;
    }
    const confirmed = window.confirm(t('admin.backups.confirmRestoreFile'));
    if (!confirmed) return;

    setBackupMessage(t('admin.backups.restoring'));

    try {
      if (file.name.endsWith('.json') || file.type.includes('json')) {
        const text = await file.text();
        const snapshot = JSON.parse(text);
        await apiRequest('/api/admin/backups/upload-restore', {
          method: 'POST',
          body: JSON.stringify({ snapshot })
        });
      } else {
        const buffer = await file.arrayBuffer();
        const response = await fetch('/api/admin/backups/upload-restore', {
          method: 'POST',
          body: buffer,
          credentials: 'same-origin',
          headers: {
            'Content-Type': 'application/octet-stream',
            'Accept-Language': window.i18n.getLanguage(),
          },
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok) {
          throw new Error(data.error || t('admin.backups.restoreFailed'));
        }
      }
      setBackupMessage(t('admin.backups.restored'));
      fileInput.value = '';
      setTimeout(() => window.location.reload(), 1200);
    } catch (err) {
      setBackupMessage(err.message, true);
    }
  });

  window.i18n.onChange(() => {
    applyTheme(document.documentElement.dataset.theme);
    if (!elements.authView.hidden) showAuth(elements.registerForm.hidden ? 'login' : 'register', elements.authMessage.hidden ? '' : elements.authMessage.textContent);
    updateStorageIndicator();
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

  document.addEventListener('pointerdown', event => {
    const isCheckbox = event.target.matches?.('input[type="checkbox"], .task-checkbox') || event.target.closest?.('.task-checkbox');
    const isDragHandle = event.target.closest?.('.task-drag-handle, .card-drag');
    if (isCheckbox || isDragHandle) {
      if (document.activeElement && document.activeElement instanceof HTMLElement && document.activeElement !== document.body) {
        document.activeElement.blur();
      }
    }
    if (isDragHandle) {
      event.preventDefault();
    }
  }, true);
})();
