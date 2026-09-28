(() => {
  const STORAGE_KEY = 'notki.notes.v1';
  const COLORS = ['default', 'mint', 'lemon', 'peach', 'lilac', 'sky'];
  const VIEW_LABELS = { all: 'Wszystkie notatki', pinned: 'Przypięte', archive: 'Archiwum', trash: 'Kosz' };
  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
  const elements = {
    allCount: $('#count-all'), pinnedCount: $('#count-pinned'), archiveCount: $('#count-archive'), trashCount: $('#count-trash'),
    nav: $$('.nav-item'), breadcrumb: $('#breadcrumb-view'), title: $('#page-title'), countLabel: $('#note-count-label'),
    pinnedLabel: $('#pinned-label'), pinnedGrid: $('#pinned-grid'), otherLabel: $('#other-label'), otherLabelText: $('#other-label-text'),
    grid: $('#notes-grid'), empty: $('#empty-state'), emptyTitle: $('#empty-title'), emptyCopy: $('#empty-copy'),
    footerCount: $('#footer-count'), search: $('#search-input'), panel: $('#editor-panel'), backdrop: $('#editor-backdrop'),
    noteTitle: $('#note-title'), noteBody: $('#note-body'), tags: $('#note-tags'), saveState: $('#save-state'), date: $('#editor-date'),
    words: $('#editor-words'), pin: $('#pin-note'), archive: $('#archive-note'), delete: $('#delete-note'), toast: $('#toast'),
    sharedBanner: $('#shared-banner'), sharedTitle: $('#shared-title'), sharedPreview: $('#shared-preview'),
  };

  let notes = loadNotes();
  let view = 'all';
  let query = '';
  let activeId = null;
  let activeColor = 'default';
  let toastTimeout;
  let saveTimeout;
  let pendingSharedNote = null;
  let returnFocus = null;
  let dragState = null;
  let editorRange = null;

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
        checkbox.setAttribute('aria-label', 'Oznacz zadanie jako wykonane');
        parent.append(checkbox);
        return;
      }
      const safeNode = document.createElement(node.tagName.toLowerCase());
      if (node.tagName === 'UL' && node.classList.contains('task-list')) safeNode.className = 'task-list';
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
    String(text || '').split(/\r\n|\r|\n/).forEach((line, index) => {
      if (index) output.append(document.createElement('br'));
      output.append(document.createTextNode(line));
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

  function rememberEditorRange() {
    const selection = window.getSelection();
    if (!selection?.rangeCount || !elements.noteBody.contains(selection.anchorNode) || !elements.noteBody.contains(selection.focusNode)) return;
    editorRange = selection.getRangeAt(0).cloneRange();
    updateFormatToolbar();
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
    checkbox.setAttribute('aria-label', 'Oznacz zadanie jako wykonane');

    const content = document.createElement('span');
    content.className = 'task-text';
    content.contentEditable = 'true';
    content.setAttribute('role', 'textbox');
    content.tabIndex = 0;
    content.textContent = '\u00A0';
    item.append(checkbox, content);
    return item;
  }

  function placeEditorCaret(container) {
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

      container.focus();
    }

    const range = document.createRange();
    if (target.nodeType === Node.TEXT_NODE) {
      range.setStart(target, 0);
      range.collapse(true);
    } else {
      range.selectNodeContents(target);
      range.collapse(true);
    }

    selection.removeAllRanges();
    selection.addRange(range);
    rememberEditorRange();
  }

  function clearDragMarkers() {
    if (!dragState) return;
    dragState.card.classList.remove('is-dragging');
    dragState.targetCard?.classList.remove('drop-before', 'drop-after', 'drop-before-vertical', 'drop-after-vertical');
    dragState.preview?.remove();
    document.body.classList.remove('is-dragging-note');
  }

  function finishNoteDrag(event, commit) {
    if (!dragState || event.pointerId !== dragState.pointerId) return;
    const { active, noteId, targetId, after } = dragState;
    clearDragMarkers();
    dragState = null;
    if (commit && active && targetId) moveNote(noteId, targetId, after);
  }

  function trackNoteDrag(event) {
    if (!dragState || event.pointerId !== dragState.pointerId) return;
    if (!dragState.active && Math.hypot(event.clientX - dragState.startX, event.clientY - dragState.startY) < 6) return;
    event.preventDefault();
    if (!dragState.active) {
      dragState.active = true;
      dragState.card.classList.add('is-dragging');
      document.body.classList.add('is-dragging-note');
      const note = notes.find(item => item.id === dragState.noteId);
      const preview = document.createElement('div');
      preview.className = 'note-drag-preview';
      preview.setAttribute('aria-hidden', 'true');
      const title = document.createElement('strong');
      title.textContent = note?.title || 'Bez tytułu';
      const body = document.createElement('span');
      body.textContent = note?.body || 'Pusta notatka';
      preview.append(title, body);
      document.body.append(preview);
      dragState.preview = preview;
    }
    const previewOffset = event.pointerType === 'touch' && event.clientY > 115 ? -100 : 16;
    dragState.preview.style.transform = `translate3d(${event.clientX + 16}px, ${event.clientY + previewOffset}px, 0)`;
    const hovered = document.elementFromPoint(event.clientX, event.clientY);
    const targetCard = hovered?.closest('.note-card');
    if (!targetCard || targetCard === dragState.card || targetCard.parentElement !== dragState.grid) {
      dragState.targetCard?.classList.remove('drop-before', 'drop-after', 'drop-before-vertical', 'drop-after-vertical');
      dragState.targetCard = null;
      dragState.targetId = null;
      return;
    }
    const bounds = targetCard.getBoundingClientRect();
    const singleColumn = getComputedStyle(dragState.grid).gridTemplateColumns.trim().split(/\s+/).length === 1;
    const after = singleColumn ? event.clientY >= bounds.top + bounds.height / 2 : event.clientX >= bounds.left + bounds.width / 2;
    dragState.targetCard?.classList.remove('drop-before', 'drop-after', 'drop-before-vertical', 'drop-after-vertical');
    targetCard.classList.add(singleColumn ? after ? 'drop-after-vertical' : 'drop-before-vertical' : after ? 'drop-after' : 'drop-before');
    dragState.targetCard = targetCard;
    dragState.targetId = targetCard.dataset.id;
    dragState.after = after;
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
    localStorage.setItem(STORAGE_KEY, JSON.stringify(notes));
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
    return notes.filter(note => {
      if (view === 'all' && !isActive(note)) return false;
      if (view === 'pinned' && (!isActive(note) || !note.pinned)) return false;
      if (view === 'archive' && (!note.archived || note.deleted)) return false;
      if (view === 'trash' && !note.deleted) return false;
      if (!query) return true;
      const searchable = `${note.title} ${noteText(note)} ${(note.tags || []).join(' ')}`.toLocaleLowerCase('pl');
      return searchable.includes(query.toLocaleLowerCase('pl'));
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
    elements.nav.forEach(button => button.classList.toggle('is-active', button.dataset.view === view));
    elements.breadcrumb.textContent = VIEW_LABELS[view].replace(' notatki', '');
    elements.title.replaceChildren(
      document.createTextNode(VIEW_LABELS[view]),
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
    elements.otherLabelText.textContent = 'POZOSTAŁE';
    elements.empty.hidden = visible.length !== 0;
    elements.countLabel.textContent = query ? `${visible.length} WYNIKÓW WYSZUKIWANIA` : `${visible.length} ${plural(visible.length, 'NOTATKA', 'NOTATKI', 'NOTATEK')}`;
    elements.footerCount.textContent = `${visible.length} ${plural(visible.length, 'notatka', 'notatki', 'notatek')}`;
    updateEmptyState();
    if (activeId) {
      const current = notes.find(note => note.id === activeId);
      if (current) updateEditorActions(current);
    }
  }

  function makeCard(note) {
    const card = $('#note-template').content.firstElementChild.cloneNode(true);
    card.dataset.id = note.id;
    card.classList.add(`color-${COLORS.includes(note.color) ? note.color : 'default'}`);
    $('.card-date', card).textContent = formatDate(note.updatedAt);
    $('.card-title', card).textContent = note.title || 'Bez tytułu';
    const cardBody = $('.card-body', card);
    if (note.bodyFormat === 1 && note.body) {
      cardBody.innerHTML = sanitizeRichHtml(note.body);
    } else {
      cardBody.textContent = noteText(note) || 'Pusta notatka';
    }
    const pin = $('.card-pin', card);
    pin.classList.toggle('is-pinned', note.pinned);
    pin.setAttribute('aria-label', note.pinned ? 'Odepnij notatkę' : 'Przypnij notatkę');
    pin.addEventListener('click', event => {
      event.stopPropagation();
      note.pinned = !note.pinned;
      note.updatedAt = new Date().toISOString();
      moveToFront(note);
      persist();
      render();
    });
    const dragHandle = $('.card-drag', card);
    dragHandle.addEventListener('click', event => event.stopPropagation());
    dragHandle.addEventListener('pointerdown', event => {
      if (event.button !== 0) return;
      event.preventDefault();
      dragState = { noteId: note.id, card, grid: card.parentElement, pointerId: event.pointerId, startX: event.clientX, startY: event.clientY, active: false, targetId: null, after: false, targetCard: null };
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
    $('.card-share', card).addEventListener('click', event => {
      event.stopPropagation();
      shareNote(note);
    });
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
      if (!event.target.closest('button')) openEditor(note.id);
    });
    return card;
  }

  function updateEmptyState() {
    const copy = {
      all: ['Tu zaczyna się dobra myśl.', 'Zapisz pierwszą notatkę. Będzie czekać na Ciebie właśnie tutaj.'],
      pinned: ['Nic tu jeszcze nie ma.', 'Przypnij ważną notatkę, aby mieć ją zawsze pod ręką.'],
      archive: ['Archiwum jest puste.', 'Zarchiwizowane notatki pojawią się właśnie tutaj.'],
      trash: ['Kosz jest pusty.', 'Usunięte notatki będą tu dostępne, dopóki nie usuniesz ich na stałe.'],
    }[view];
    elements.emptyTitle.textContent = query ? 'Nie znaleziono notatek.' : copy[0];
    elements.emptyCopy.textContent = query ? 'Spróbuj innego tytułu, fragmentu treści albo etykiety.' : copy[1];
    $('#empty-create').hidden = view !== 'all' || Boolean(query);
  }

  function openEditor(id = null) {
    const existing = notes.find(note => note.id === id);
    if (!existing && view === 'trash') return;
    const note = existing || createNote();
    if (!existing) {
      notes.unshift(note);
      persist();
    }
    activeId = note.id;
    activeColor = note.color;
    returnFocus = document.activeElement;
    elements.noteTitle.value = note.title;
    editorRange = null;
    elements.noteBody.innerHTML = note.bodyFormat === 1 ? sanitizeRichHtml(note.body) : plainTextToHtml(note.body);
    elements.tags.value = (note.tags || []).join(', ');
    elements.date.textContent = `Utworzono ${formatFullDate(note.createdAt)}`;
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
    saveEditor();
    activeId = null;
    elements.panel.classList.remove('is-open');
    elements.panel.setAttribute('aria-hidden', 'true');
    elements.backdrop.hidden = true;
    document.body.style.overflow = '';
    if (returnFocus && typeof returnFocus.focus === 'function') returnFocus.focus();
    render();
  }

  function saveEditor() {
    const note = notes.find(item => item.id === activeId);
    if (!note) return;
    note.title = elements.noteTitle.value.trim();
    note.body = serializedEditorBody();
    note.bodyFormat = 1;
    note.tags = [...new Set(elements.tags.value.split(',').map(tag => tag.trim().toLocaleLowerCase('pl')).filter(Boolean))];
    note.color = activeColor;
    note.updatedAt = new Date().toISOString();
    moveToFront(note);
    persist();
    elements.saveState.classList.remove('is-saving');
    elements.saveState.innerHTML = '<span class="save-dot"></span>Zapisano';
    elements.date.textContent = `Utworzono ${formatFullDate(note.createdAt)}`;
    updateWordCount();
    render();
  }

  function scheduleSave() {
    elements.saveState.classList.add('is-saving');
    elements.saveState.innerHTML = '<span class="save-dot"></span>Zapisywanie';
    window.clearTimeout(saveTimeout);
    saveTimeout = window.setTimeout(saveEditor, 180);
  }

  function updateWordCount() {
    const text = elements.noteBody.innerText || elements.noteBody.textContent || '';
    const count = text.trim().split(/\s+/).filter(Boolean).length;
    elements.words.textContent = `${count} ${plural(count, 'słowo', 'słowa', 'słów')}`;
  }

  function updateEditorActions(note) {
    elements.pin.classList.toggle('is-pinned', note.pinned);
    elements.pin.textContent = note.pinned ? '⌖' : '⌖';
    elements.pin.setAttribute('aria-label', note.pinned ? 'Odepnij notatkę' : 'Przypnij notatkę');
    elements.pin.title = note.pinned ? 'Odepnij' : 'Przypnij';
    elements.archive.textContent = note.deleted ? '↶' : '▣';
    elements.archive.setAttribute('aria-label', note.deleted ? 'Przywróć z kosza' : note.archived ? 'Przywróć z archiwum' : 'Archiwizuj notatkę');
    elements.archive.title = note.deleted || note.archived ? 'Przywróć' : 'Archiwizuj';
    elements.delete.setAttribute('aria-label', note.deleted ? 'Usuń trwale' : 'Przenieś do kosza');
    elements.delete.title = note.deleted ? 'Usuń trwale' : 'Przenieś do kosza';
    elements.pin.hidden = note.deleted;
    $('#share-note').hidden = note.deleted;
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
      showToast('Link skopiowany. Każda osoba z linkiem zobaczy tę kopię notatki.');
    } catch {
      showToast('Nie udało się skopiować linku. Sprawdź uprawnienia schowka przeglądarki.');
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
      elements.sharedTitle.textContent = pendingSharedNote.title || 'Bez tytułu';
      elements.sharedPreview.textContent = noteText(pendingSharedNote) || 'Pusta notatka';
      elements.sharedBanner.hidden = false;
      elements.sharedBanner.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    } catch {
      showToast('Ten link nie zawiera prawidłowej notatki.');
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

  function formatDate(value) {
    const date = new Date(value);
    const today = new Date();
    if (date.toDateString() === today.toDateString()) return `Dziś, ${new Intl.DateTimeFormat('pl-PL', { hour: '2-digit', minute: '2-digit' }).format(date)}`;
    return new Intl.DateTimeFormat('pl-PL', { day: 'numeric', month: 'short' }).format(date);
  }

  function formatFullDate(value) {
    return new Intl.DateTimeFormat('pl-PL', { day: 'numeric', month: 'long', year: 'numeric' }).format(new Date(value));
  }

  function plural(count, one, few, many) {
    if (count === 1) return one;
    const lastTwo = count % 100;
    const last = count % 10;
    return last >= 2 && last <= 4 && (lastTwo < 12 || lastTwo > 14) ? few : many;
  }

  function showToast(message) {
    elements.toast.textContent = message;
    elements.toast.classList.add('is-visible');
    window.clearTimeout(toastTimeout);
    toastTimeout = window.setTimeout(() => elements.toast.classList.remove('is-visible'), 3200);
  }

  function exportBackup() {
    $('#settings-menu').open = false;
    const backup = { format: 'notki-backup', version: 1, exportedAt: new Date().toISOString(), notes };
    const blob = new Blob([JSON.stringify(backup, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `notki-backup-${new Date().toISOString().slice(0, 10)}.json`;
    document.body.append(link);
    link.click();
    link.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    showToast(`Kopia zapasowa pobrana: ${notes.length} ${plural(notes.length, 'notatka', 'notatki', 'notatek')}.`);
  }

  function normalizeBackupNote(candidate) {
    if (!candidate || typeof candidate !== 'object' || Array.isArray(candidate) || typeof candidate.id !== 'string' || !candidate.id.trim()) return null;
    if (typeof candidate.title !== 'string' && typeof candidate.body !== 'string') return null;
    if (typeof candidate.body === 'string' && candidate.body.length > 1000000) return null;
    const now = new Date().toISOString();
    const createdAt = Number.isFinite(Date.parse(candidate.createdAt)) ? new Date(candidate.createdAt).toISOString() : now;
    const updatedAt = Number.isFinite(Date.parse(candidate.updatedAt)) ? new Date(candidate.updatedAt).toISOString() : createdAt;
    const deleted = Boolean(candidate.deleted);
    const archived = !deleted && Boolean(candidate.archived);
    return {
      id: candidate.id.trim().slice(0, 160),
      title: typeof candidate.title === 'string' ? candidate.title.slice(0, 160) : '',
      body: typeof candidate.body === 'string' ? candidate.body : '',
      bodyFormat: candidate.bodyFormat === 1 ? 1 : 0,
      color: COLORS.includes(candidate.color) ? candidate.color : 'default',
      tags: [...new Set((Array.isArray(candidate.tags) ? candidate.tags : []).filter(tag => typeof tag === 'string').map(tag => tag.trim().toLocaleLowerCase('pl')).filter(Boolean))].slice(0, 50),
      pinned: !deleted && !archived && Boolean(candidate.pinned),
      archived,
      deleted,
      createdAt,
      updatedAt,
      order: Number.isFinite(candidate.order) ? candidate.order : Date.parse(updatedAt),
    };
  }

  async function importBackup(file) {
    if (file.size > 10000000) throw new Error('Plik kopii zapasowej przekracza limit 10 MB.');
    const parsed = JSON.parse(await file.text());
    const records = Array.isArray(parsed) ? parsed : parsed?.format === 'notki-backup' && parsed.version === 1 ? parsed.notes : null;
    if (!Array.isArray(records) || records.length > 10000) throw new Error('Plik nie jest prawidłową kopią Notki.');
    const knownIds = new Set(notes.map(note => note.id));
    const imported = [];
    let skipped = 0;
    records.forEach(record => {
      const note = normalizeBackupNote(record);
      if (!note || knownIds.has(note.id)) {
        skipped += 1;
        return;
      }
      knownIds.add(note.id);
      imported.push(note);
    });
    if (!imported.length) {
      showToast(records.length ? `Nic nie dodano; pominięto ${skipped} duplikatów lub błędnych wpisów.` : 'Ta kopia zapasowa nie zawiera notatek.');
      return;
    }
    const existingNotes = notes;
    notes = [...imported, ...notes];
    try {
      persist();
    } catch {
      notes = existingNotes;
      throw new Error('Brak miejsca w pamięci przeglądarki na import tych notatek.');
    }
    render();
    showToast(`Import zakończony: dodano ${imported.length}, pominięto ${skipped}.`);
  }

  $('#export-notes').addEventListener('click', exportBackup);
  $('#import-notes').addEventListener('click', () => $('#import-file').click());
  $('#import-file').addEventListener('change', async event => {
    const input = event.currentTarget;
    const file = input.files[0];
    if (!file) return;
    try {
      await importBackup(file);
    } catch (error) {
      showToast(error instanceof SyntaxError ? 'Plik nie zawiera poprawnego JSON-u.' : error.message);
    } finally {
      input.value = '';
      $('#settings-menu').open = false;
    }
  });

  document.addEventListener('selectionchange', rememberEditorRange);
  $$('#format-toolbar button').forEach(button => {
    button.addEventListener('mousedown', event => event.preventDefault());
    button.addEventListener('click', () => {
      restoreEditorRange();
      const previousRange = editorRange?.cloneRange();
      if (button.hasAttribute('data-insert-checklist')) {
        document.execCommand('insertHTML', false, '<ul class="task-list"><li><input type="checkbox" class="task-checkbox" contenteditable="false" aria-label="Oznacz zadanie jako wykonane"><span class="task-text" contenteditable="true" role="textbox">&#8203;</span></li></ul>');
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
    if (event.key !== 'Enter' || event.shiftKey) return;
    const selection = window.getSelection();
    const anchor = selection?.anchorNode;
    const anchorElement = anchor?.nodeType === Node.ELEMENT_NODE ? anchor : anchor?.parentElement;
    const item = anchorElement?.closest('li');
    const list = item?.closest('ul.task-list');
    if (!item || !list) return;
    event.preventDefault();
    if (!item.textContent.trim() && item === list.lastElementChild) {
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
      window.setTimeout(() => placeEditorCaret(paragraph), 0);
    } else {
      const nextItem = createChecklistItem();
      item.after(nextItem);
      const nextText = nextItem.querySelector('.task-text');
      window.setTimeout(() => placeEditorCaret(nextText), 0);
    }
    updateWordCount();
    scheduleSave();
  });
  elements.noteBody.addEventListener('change', event => {
    if (event.target.matches('input[type="checkbox"]')) scheduleSave();
  });

  $('#create-note').addEventListener('click', () => openEditor());
  $('#create-note-heading').addEventListener('click', () => openEditor());
  $('#capture-note').addEventListener('click', () => openEditor());
  $('#empty-create').addEventListener('click', () => openEditor());
  $('#close-editor').addEventListener('click', closeEditor);
  elements.backdrop.addEventListener('click', closeEditor);
  elements.nav.forEach(button => button.addEventListener('click', () => {
    if (activeId) closeEditor();
    view = button.dataset.view;
    render();
  }));
  elements.search.addEventListener('input', () => {
    query = elements.search.value.trim();
    render();
  });
  [elements.noteTitle, elements.noteBody, elements.tags].forEach(input => input.addEventListener('input', () => {
    if (input === elements.noteBody) updateWordCount();
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
    showToast(restoredFromTrash ? 'Notatka przywrócona z kosza.' : note.archived ? 'Notatka przeniesiona do archiwum.' : 'Notatka przywrócona z archiwum.');
    closeEditor();
  });
  elements.delete.addEventListener('click', () => {
    const note = notes.find(item => item.id === activeId);
    if (!note) return;
    if (note.deleted) {
      notes = notes.filter(item => item.id !== note.id);
      showToast('Notatka usunięta na stałe.');
    } else {
      note.deleted = true;
      note.pinned = false;
      note.archived = false;
      note.updatedAt = new Date().toISOString();
      showToast('Notatka przeniesiona do kosza.');
    }
    persist();
    closeEditor();
  });
  $('#share-note').addEventListener('click', () => {
    saveEditor();
    const note = notes.find(item => item.id === activeId);
    if (note) shareNote(note);
  });
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
    showToast('Udostępniona notatka zapisana u Ciebie.');
    openEditor(note.id);
  });
  document.addEventListener('click', event => {
    const menu = $('#settings-menu');
    if (menu.open && !menu.contains(event.target)) menu.open = false;
  });
  document.addEventListener('keydown', event => {
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

  render();
  readSharedNote();
})();
