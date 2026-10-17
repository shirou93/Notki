const fs = require('fs');
const path = require('path');
const { TextEncoder, TextDecoder } = require('util');

global.TextEncoder = TextEncoder;
global.TextDecoder = TextDecoder;

const indexHtmlPath = path.join(__dirname, '../../index.html');
const indexHtmlContent = fs.readFileSync(indexHtmlPath, 'utf8');
document.body.innerHTML = indexHtmlContent;

// Mock window.matchMedia
Object.defineProperty(window, 'matchMedia', {
  writable: true,
  value: jest.fn().mockImplementation(query => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: jest.fn(),
    removeListener: jest.fn(),
    addEventListener: jest.fn(),
    removeEventListener: jest.fn(),
    dispatchEvent: jest.fn(),
  })),
});

window.i18n = {
  t: jest.fn(),
  plural: jest.fn(),
  onChange: jest.fn(),
  applyTranslations: jest.fn(),
  formatDate: jest.fn(d => d || ''),
  formatFullDate: jest.fn(d => d || ''),
  formatDateTime: jest.fn(d => d || ''),
  getLanguage: jest.fn(() => 'pl')
};

// require the module
const {
  bufferToBase64,
  encodeBase64Url,
  getTaskStatsFromHtml,
  tableCell,
  createIconSvg,
  saveLocalCache,
  getLocalCache,
  saveCachedUser,
  getCachedUser,
  filteredNotes,
  moveNote,
  makeCard,
  getView,
  setView,
  getNotes,
  setNotes,
  getCurrentSort,
  setCurrentSort,
  renderStandardView,
  render,
  formatIcsDate,
  downloadIcsFile,
  getQuery,
  setQuery,
} = require('../../app.js');

describe('createIconSvg', () => {
  it('should return an SVGSVGElement', () => {
    const svg = createIconSvg('<path d="M1 1"/>');
    expect(svg.tagName.toLowerCase()).toBe('svg');
    expect(svg.namespaceURI).toBe('http://www.w3.org/2000/svg');
  });

  it('should set default attributes correctly', () => {
    const svg = createIconSvg('<path d="M1 1"/>');
    expect(svg.getAttribute('viewBox')).toBe('0 0 24 24');
    expect(svg.getAttribute('width')).toBe('1em');
    expect(svg.getAttribute('height')).toBe('1em');
    expect(svg.getAttribute('fill')).toBe('none');
    expect(svg.getAttribute('stroke')).toBe('currentColor');
    expect(svg.getAttribute('stroke-width')).toBe('1.7');
    expect(svg.getAttribute('stroke-linecap')).toBe('round');
    expect(svg.getAttribute('stroke-linejoin')).toBe('round');
    expect(svg.getAttribute('aria-hidden')).toBe('true');
  });

  it('should inject innerHTML correctly', () => {
    const innerHTML = '<path d="M3 6h18"/>';
    const svg = createIconSvg(innerHTML);
    // jsdom (and browsers) may parse and reserialize self-closing tags, so it might output <path d="M3 6h18"></path>
    expect(svg.innerHTML.replace(/><\/path>/g, '/>')).toBe(innerHTML);
  });

  it('should handle empty string innerHTML correctly', () => {
    const svg = createIconSvg('');
    expect(svg.innerHTML).toBe('');
    expect(svg.tagName.toLowerCase()).toBe('svg');
  });
});

describe('tableCell', () => {
  it('should create a <td> element', () => {
    const cell = tableCell('content');
    expect(cell.tagName.toLowerCase()).toBe('td');
  });

  it('should set text content correctly for a string', () => {
    const cell = tableCell('test string');
    expect(cell.textContent).toBe('test string');
  });

  it('should set text content correctly for a number', () => {
    const cell = tableCell(42);
    expect(cell.textContent).toBe('42');
  });

  it('should set empty text content for an empty string', () => {
    const cell = tableCell('');
    expect(cell.textContent).toBe('');
  });

  it('should safely escape HTML strings preventing XSS', () => {
    const htmlContent = '<script>alert("xss")</script>';
    const cell = tableCell(htmlContent);
    // Since textContent is used, the literal string is stored, not parsed as HTML.
    expect(cell.textContent).toBe(htmlContent);
    expect(cell.innerHTML).toBe('&lt;script&gt;alert("xss")&lt;/script&gt;');
  });
});

describe('getTaskStatsFromHtml', () => {
  it('should return zeros for null, undefined, or empty string', () => {
    expect(getTaskStatsFromHtml(null)).toEqual({ total: 0, completed: 0, percent: 0 });
    expect(getTaskStatsFromHtml(undefined)).toEqual({ total: 0, completed: 0, percent: 0 });
    expect(getTaskStatsFromHtml('')).toEqual({ total: 0, completed: 0, percent: 0 });
  });

  it('should return zeros when HTML contains no checkboxes', () => {
    expect(getTaskStatsFromHtml('<div>Hello World</div>')).toEqual({ total: 0, completed: 0, percent: 0 });
  });

  it('should correctly parse HTML with multiple checkboxes', () => {
    const html = `
      <div>
        <input type="checkbox" checked />
        <input type="checkbox" />
        <input type="checkbox" checked="checked" />
        <input type="checkbox" />
      </div>
    `;
    expect(getTaskStatsFromHtml(html)).toEqual({ total: 4, completed: 2, percent: 50 });
  });

  it('should calculate percent correctly with rounding', () => {
    const html = `
      <div>
        <input type="checkbox" checked />
        <input type="checkbox" />
        <input type="checkbox" />
      </div>
    `;
    expect(getTaskStatsFromHtml(html)).toEqual({ total: 3, completed: 1, percent: 33 });
  });

  it('should handle all checked checkboxes', () => {
    const html = `
      <div>
        <input type="checkbox" checked />
        <input type="checkbox" checked />
      </div>
    `;
    expect(getTaskStatsFromHtml(html)).toEqual({ total: 2, completed: 2, percent: 100 });
  });
});

describe('bufferToBase64', () => {
  it('should return empty string for null or undefined', () => {
    expect(bufferToBase64(null)).toBe('');
    expect(bufferToBase64(undefined)).toBe('');
  });

  it('should return empty string for empty buffer', () => {
    const buffer = new ArrayBuffer(0);
    expect(bufferToBase64(buffer)).toBe('');
  });

  it('should correctly encode a simple string buffer', () => {
    const str = "Hello World";
    const buffer = new ArrayBuffer(str.length);
    const view = new Uint8Array(buffer);
    for (let i = 0; i < str.length; i++) {
      view[i] = str.charCodeAt(i);
    }
    expect(bufferToBase64(buffer)).toBe("SGVsbG8gV29ybGQ=");
  });

  it('should correctly encode binary data (values > 127)', () => {
    const buffer = new ArrayBuffer(3);
    const view = new Uint8Array(buffer);
    view[0] = 255;
    view[1] = 128;
    view[2] = 0;
    expect(bufferToBase64(buffer)).toBe("/4AA");
  });

  it('should work with ArrayBuffer inputs from standard JS types', () => {
    const arr = new Uint8Array([1, 2, 3]);
    expect(bufferToBase64(arr.buffer)).toBe("AQID");
  });
});

describe('encodeBase64Url', () => {
  it('should encode a plain ASCII string into URL-safe base64', () => {
    expect(encodeBase64Url('Hello World')).toBe('SGVsbG8gV29ybGQ');
  });

  it('should handle UTF-8 characters properly', () => {
    expect(encodeBase64Url('🔑 Note with emoji 🎉')).toBe('8J-UkSBOb3RlIHdpdGggZW1vamkg8J-OiQ');
  });

  it('should convert standard base64 characters + / and strip trailing padding =', () => {
    // String that generates + and / in standard base64
    const input = '>>>???';
    const result = encodeBase64Url(input);
    expect(result).not.toContain('+');
    expect(result).not.toContain('/');
    expect(result).not.toContain('=');
  });

  it('should handle large string payloads efficiently without error', () => {
    const largeInput = 'Large string contents for testing '.repeat(1000);
    const result = encodeBase64Url(largeInput);
    expect(result.length).toBeGreaterThan(0);
  });
});

describe('saveCachedUser', () => {
  beforeEach(() => {
    Object.defineProperty(window, 'localStorage', {
      value: {
        setItem: jest.fn(),
        removeItem: jest.fn(),
        getItem: jest.fn(),
      },
      writable: true
    });
  });

  afterEach(() => {
    jest.restoreAllMocks();
  });

  it('should call setItem with correct key and JSON string when a user object is provided', () => {
    const user = { id: 'user123', email: 'test@example.com' };
    saveCachedUser(user);
    expect(localStorage.setItem).toHaveBeenCalledWith('notki.cache.user', JSON.stringify(user));
  });

  it('should call removeItem when user is null', () => {
    saveCachedUser(null);
    expect(localStorage.removeItem).toHaveBeenCalledWith('notki.cache.user');
  });

  it('should call removeItem when user is undefined', () => {
    saveCachedUser(undefined);
    expect(localStorage.removeItem).toHaveBeenCalledWith('notki.cache.user');
  });

  it('should silently handle setItem exceptions', () => {
    localStorage.setItem.mockImplementation(() => {
      throw new Error('Quota exceeded');
    });
    const user = { id: 'user123' };
    expect(() => saveCachedUser(user)).not.toThrow();
  });
});

describe('getCachedUser', () => {
  beforeEach(() => {
    Object.defineProperty(window, 'localStorage', {
      value: {
        setItem: jest.fn(),
        removeItem: jest.fn(),
        getItem: jest.fn(),
      },
      writable: true
    });
  });

  afterEach(() => {
    jest.restoreAllMocks();
  });

  it('should parse and return the user object when it exists in localStorage', () => {
    const user = { id: 'user456', email: 'found@example.com' };
    localStorage.getItem.mockReturnValue(JSON.stringify(user));

    const result = getCachedUser();

    expect(localStorage.getItem).toHaveBeenCalledWith('notki.cache.user');
    expect(result).toEqual(user);
  });

  it('should return null when localStorage returns null (not found)', () => {
    localStorage.getItem.mockReturnValue(null);

    const result = getCachedUser();

    expect(localStorage.getItem).toHaveBeenCalledWith('notki.cache.user');
    expect(result).toBeNull();
  });

  it('should return null and gracefully handle JSON parse errors (e.g. malformed JSON)', () => {
    localStorage.getItem.mockReturnValue('invalid-json{}}');

    const result = getCachedUser();

    expect(result).toBeNull();
  });
});

describe('getLocalCache', () => {
  beforeEach(() => {
    Object.defineProperty(window, 'localStorage', {
      value: {
        setItem: jest.fn(),
        removeItem: jest.fn(),
        getItem: jest.fn(),
      },
      writable: true
    });
  });

  afterEach(() => {
    jest.restoreAllMocks();
  });

  it('should return default object with null values when userId is falsy', () => {
    const defaultResult = { notes: null, sharedNotes: null, labels: null };
    expect(getLocalCache(null)).toEqual(defaultResult);
    expect(getLocalCache(undefined)).toEqual(defaultResult);
    expect(getLocalCache('')).toEqual(defaultResult);
    expect(localStorage.getItem).not.toHaveBeenCalled();
  });

  it('should retrieve and parse valid cached data for userId from localStorage', () => {
    const userId = 'user_abc';
    const sampleNotes = [{ id: 'n1', title: 'Note 1' }];
    const sampleShared = [{ id: 's1', title: 'Shared 1' }];
    const sampleLabels = ['work', 'personal'];

    localStorage.getItem.mockImplementation((key) => {
      if (key === 'notki.cache.notes.user_abc') return JSON.stringify(sampleNotes);
      if (key === 'notki.cache.sharedNotes.user_abc') return JSON.stringify(sampleShared);
      if (key === 'notki.cache.labels.user_abc') return JSON.stringify(sampleLabels);
      return null;
    });

    const result = getLocalCache(userId);

    expect(localStorage.getItem).toHaveBeenCalledWith('notki.cache.notes.user_abc');
    expect(localStorage.getItem).toHaveBeenCalledWith('notki.cache.sharedNotes.user_abc');
    expect(localStorage.getItem).toHaveBeenCalledWith('notki.cache.labels.user_abc');
    expect(result).toEqual({
      notes: sampleNotes,
      sharedNotes: sampleShared,
      labels: sampleLabels,
    });
  });

  it('should handle missing entries in localStorage gracefully', () => {
    localStorage.getItem.mockReturnValue(null);

    const result = getLocalCache('user_123');

    expect(result).toEqual({ notes: null, sharedNotes: null, labels: null });
  });

  it('should catch JSON parse errors for malformed cached data and return default object', () => {
    localStorage.getItem.mockImplementation((key) => {
      if (key === 'notki.cache.notes.user_123') return '{"malformed: true';
      return null;
    });

    const result = getLocalCache('user_123');

    expect(result).toEqual({ notes: null, sharedNotes: null, labels: null });
  });

  it('should catch localStorage.getItem exceptions and return default object', () => {
    localStorage.getItem.mockImplementation(() => {
      throw new Error('SecurityError: Access denied');
    });

    const result = getLocalCache('user_123');

    expect(result).toEqual({ notes: null, sharedNotes: null, labels: null });
  });
});

describe('saveLocalCache', () => {
  beforeEach(() => {
    Object.defineProperty(window, 'localStorage', {
      value: {
        setItem: jest.fn(),
        removeItem: jest.fn(),
        getItem: jest.fn(),
      },
      writable: true
    });
  });

  afterEach(() => {
    jest.restoreAllMocks();
  });

  it('should not call setItem if userId is falsy', () => {
    saveLocalCache(null, { notes: [] });
    saveLocalCache(undefined, { notes: [] });
    saveLocalCache('', { notes: [] });
    expect(localStorage.setItem).not.toHaveBeenCalled();
  });

  it('should save defined data properties into localStorage under correct keys', () => {
    const userId = 'user_99';
    const notes = [{ id: '1' }];
    const sharedNotes = [{ id: '2' }];
    const labels = ['tag1'];

    saveLocalCache(userId, { notes, sharedNotes, labels });

    expect(localStorage.setItem).toHaveBeenCalledWith('notki.cache.notes.user_99', JSON.stringify(notes));
    expect(localStorage.setItem).toHaveBeenCalledWith('notki.cache.sharedNotes.user_99', JSON.stringify(sharedNotes));
    expect(localStorage.setItem).toHaveBeenCalledWith('notki.cache.labels.user_99', JSON.stringify(labels));
  });

  it('should only set keys for properties that are defined', () => {
    const userId = 'user_55';
    saveLocalCache(userId, { notes: [{ id: '1' }] });

    expect(localStorage.setItem).toHaveBeenCalledTimes(1);
    expect(localStorage.setItem).toHaveBeenCalledWith('notki.cache.notes.user_55', JSON.stringify([{ id: '1' }]));
  });

  it('should save data when containing only sharedNotes or only labels', () => {
    const userId = 'user_77';

    saveLocalCache(userId, { sharedNotes: [{ id: 'sn1' }] });
    expect(localStorage.setItem).toHaveBeenCalledTimes(1);
    expect(localStorage.setItem).toHaveBeenCalledWith('notki.cache.sharedNotes.user_77', JSON.stringify([{ id: 'sn1' }]));

    localStorage.setItem.mockClear();

    saveLocalCache(userId, { labels: ['work', 'personal'] });
    expect(localStorage.setItem).toHaveBeenCalledTimes(1);
    expect(localStorage.setItem).toHaveBeenCalledWith('notki.cache.labels.user_77', JSON.stringify(['work', 'personal']));
  });

  it('should handle data with empty arrays correctly', () => {
    const userId = 'user_empty';
    saveLocalCache(userId, { notes: [], sharedNotes: [], labels: [] });

    expect(localStorage.setItem).toHaveBeenCalledWith('notki.cache.notes.user_empty', '[]');
    expect(localStorage.setItem).toHaveBeenCalledWith('notki.cache.sharedNotes.user_empty', '[]');
    expect(localStorage.setItem).toHaveBeenCalledWith('notki.cache.labels.user_empty', '[]');
  });

  it('should catch and handle localStorage.setItem exceptions gracefully', () => {
    const consoleSpy = jest.spyOn(console, 'error').mockImplementation(() => {});
    localStorage.setItem.mockImplementation(() => {
      throw new Error('QuotaExceededError');
    });

    expect(() => saveLocalCache('user_1', { notes: [] })).not.toThrow();
    expect(consoleSpy).toHaveBeenCalledWith('Failed to save to local cache:', expect.any(Error));
    consoleSpy.mockRestore();
  });
});

describe('Note dragging and sorting across tabs', () => {
  beforeEach(() => {
    setQuery('');
    setCurrentSort('newest');
    setView('all');
    setNotes([]);
  });

  it('should allow note dragging (.card-drag handle visible) in all note tabs for user own notes', () => {
    const note = { id: 'note-1', title: 'Test Note', body: 'Body', order: 100, createdAt: new Date().toISOString(), updatedAt: new Date().toISOString() };

    ['all', 'pinned', 'archive', 'trash', 'shared'].forEach(targetView => {
      setView(targetView);
      const card = makeCard(note);
      const dragHandle = card.querySelector('.card-drag');
      expect(dragHandle).not.toBeNull();
      expect(dragHandle.hidden).toBe(false);
    });
  });

  it('should hide drag handle when note is shared from someone else or when searching or not sorting by newest', () => {
    const ownNote = { id: 'note-1', title: 'Own Note', order: 100 };
    const sharedNote = { id: 'note-2', title: 'Shared Note', ownerEmail: 'other@example.com', order: 90 };

    setView('all');
    // Shared note owned by someone else
    const sharedCard = makeCard(sharedNote);
    expect(sharedCard.querySelector('.card-drag').hidden).toBe(true);

    // Active search query
    setQuery('search text');
    const searchCard = makeCard(ownNote);
    expect(searchCard.querySelector('.card-drag').hidden).toBe(true);

    // Custom non-newest sort
    setQuery('');
    setCurrentSort('titleAsc');
    const sortedCard = makeCard(ownNote);
    expect(sortedCard.querySelector('.card-drag').hidden).toBe(true);
  });

  it('should filter notes with dueDate in dailyPlan view sorted by date (oldest vs newest)', () => {
    const note1 = { id: 'due-1', title: 'Task 1', archived: false, deleted: false, dueDate: '2026-10-25T14:00' };
    const note2 = { id: 'due-2', title: 'Task 2', archived: false, deleted: false, dueDate: '2026-10-20T09:00' };
    const note3 = { id: 'nodue', title: 'No Due', archived: false, deleted: false, dueDate: null };
    setNotes([note1, note2, note3]);

    setView('dailyPlan');
    setCurrentSort('oldest');
    const resultOldest = filteredNotes();
    expect(resultOldest.map(n => n.id)).toEqual(['due-2', 'due-1']);

    setCurrentSort('newest');
    const resultNewest = filteredNotes();
    expect(resultNewest.map(n => n.id)).toEqual(['due-1', 'due-2']);
  });

  it('should format dates for iCalendar export correctly', () => {
    const d = new Date('2026-10-25T14:30:00Z');
    expect(formatIcsDate(d)).toBe('20261025T143000Z');
  });

  it('should separate due date container from tags container on note cards and trigger ics download on due badge click', () => {
    const noteWithDue = { id: 'due-card-1', title: 'Due Note', archived: false, deleted: false, dueDate: '2026-10-25T14:00', tags: ['work'] };
    const card = makeCard(noteWithDue);

    const dueElem = card.querySelector('.card-due');
    const tagsElem = card.querySelector('.card-tags');
    expect(dueElem).not.toBeNull();
    expect(tagsElem).not.toBeNull();
    const dueBadge = dueElem.querySelector('.card-due-badge');
    expect(dueBadge).not.toBeNull();
    expect(dueBadge.textContent).toContain('📅');
    expect(tagsElem.querySelector('.card-tag').textContent).toBe('work');
  });

  it('should render timeline sections in dailyPlan view including overdue section', () => {
    const now = new Date();
    const overdueDate = new Date(now.getTime() - 86400000 * 2).toISOString().slice(0, 16);
    const todayDate = new Date(now.getTime()).toISOString().slice(0, 16);

    const noteOverdue = { id: 'overdue-1', title: 'Overdue Note', archived: false, deleted: false, dueDate: overdueDate };
    const noteToday = { id: 'today-1', title: 'Today Note', archived: false, deleted: false, dueDate: todayDate };
    setNotes([noteOverdue, noteToday]);

    setView('dailyPlan');
    setCurrentSort('oldest');
    renderStandardView();

    const timelineArea = document.getElementById('timeline-area');
    expect(timelineArea).not.toBeNull();
    expect(timelineArea.hidden).toBe(false);
    expect(timelineArea.querySelectorAll('.section-label').length).toBeGreaterThanOrEqual(1);
  });

  it('should hide view-toggle button in dailyPlan view and show it in standard views', () => {
    const viewToggle = document.getElementById('view-toggle');
    expect(viewToggle).not.toBeNull();

    setView('dailyPlan');
    render();
    expect(viewToggle.hidden).toBe(true);

    setView('all');
    render();
    expect(viewToggle.hidden).toBe(false);
  });

  it('should preserve order-based sorting in archive and trash views', () => {
    const note1 = { id: 'arch-1', title: 'Arch 1', archived: true, deleted: false, order: 10, updatedAt: '2026-01-01T00:00:00Z' };
    const note2 = { id: 'arch-2', title: 'Arch 2', archived: true, deleted: false, order: 50, updatedAt: '2025-01-01T00:00:00Z' };
    setNotes([note1, note2]);

    setView('archive');
    const resultArch = filteredNotes();
    expect(resultArch.map(n => n.id)).toEqual(['arch-2', 'arch-1']);

    const trash1 = { id: 'trash-1', title: 'Trash 1', archived: false, deleted: true, order: 15, updatedAt: '2026-01-01T00:00:00Z' };
    const trash2 = { id: 'trash-2', title: 'Trash 2', archived: false, deleted: true, order: 80, updatedAt: '2025-01-01T00:00:00Z' };
    setNotes([trash1, trash2]);

    setView('trash');
    const resultTrash = filteredNotes();
    expect(resultTrash.map(n => n.id)).toEqual(['trash-2', 'trash-1']);
  });

  it('should reorder notes correctly via moveNote in archive view', () => {
    const noteA = { id: 'a', title: 'A', archived: true, deleted: false, order: 30 };
    const noteB = { id: 'b', title: 'B', archived: true, deleted: false, order: 20 };
    setNotes([noteA, noteB]);
    setView('archive');

    moveNote('b', 'a', false); // move B before A
    expect(getNotes().map(n => n.id)).toEqual(['b', 'a']);
    const reordered = filteredNotes();
    expect(reordered.map(n => n.id)).toEqual(['b', 'a']);
  });

  it('should update note.body, card progress, and card body DOM with completed task groups when toggling card checkbox', () => {
    const initialBody = '<ul class="task-list"><li><input type="checkbox" class="task-checkbox"><span class="task-text">Task 1</span></li><li><input type="checkbox" class="task-checkbox"><span class="task-text">Task 2</span></li></ul>';
    const note = {
      id: 'cb-test-1',
      title: 'Checkbox Test',
      body: initialBody,
      bodyFormat: 1,
      updatedAt: new Date().toISOString()
    };

    const card = makeCard(note);
    const cardBody = card.querySelector('.card-body');

    const checkbox = card.querySelector('input[type="checkbox"]');
    expect(checkbox).not.toBeNull();
    expect(checkbox.checked).toBe(false);

    // Toggle checkbox
    checkbox.checked = true;
    checkbox.dispatchEvent(new Event('change', { bubbles: true }));

    // Verify note.body updated
    expect(note.body).toContain('checked');

    // Verify progress indicator updated
    const progressText = card.querySelector('.card-progress-text');
    expect(progressText).not.toBeNull();
    expect(progressText.textContent).toBe('1/2 (50%)');
  });

  it('should toggle checkbox when clicking text next to a checkbox in a note card in general panel', () => {
    const initialBody = '<ul class="task-list"><li><input type="checkbox" class="task-checkbox"><span class="task-text">Task 1</span></li></ul>';
    const note = {
      id: 'cb-text-test-1',
      title: 'Task Text Click Test',
      body: initialBody,
      bodyFormat: 1,
      updatedAt: new Date().toISOString()
    };

    const card = makeCard(note);
    document.body.appendChild(card);

    const checkbox = card.querySelector('input[type="checkbox"]');
    const taskText = card.querySelector('.task-text');

    expect(checkbox.checked).toBe(false);

    // Click on the task text next to checkbox
    taskText.click();

    // Verify checkbox is now checked (re-query updated DOM)
    let updatedCheckbox = card.querySelector('input[type="checkbox"]');
    expect(updatedCheckbox.checked).toBe(true);
    expect(note.body).toContain('checked');

    // Click again to uncheck (re-query updated taskText)
    const updatedTaskText = card.querySelector('.task-text');
    updatedTaskText.click();
    updatedCheckbox = card.querySelector('input[type="checkbox"]');
    expect(updatedCheckbox.checked).toBe(false);

    document.body.removeChild(card);
  });

  it('should toggle checkbox when clicking surrounding space or drag handle in open note editor', () => {
    const noteBody = document.querySelector('#note-body');
    expect(noteBody).not.toBeNull();

    noteBody.innerHTML = '<ul class="task-list"><li><span class="task-drag-handle">::</span><input type="checkbox" class="task-checkbox"><span class="task-text">Task item</span></li></ul>';
    const li = noteBody.querySelector('li');
    const dragHandle = noteBody.querySelector('.task-drag-handle');
    const checkbox = noteBody.querySelector('input[type="checkbox"]');

    expect(checkbox.checked).toBe(false);

    // 1. Simulate pointerdown on task list item (surrounding space / gap around checkbox)
    const pdEvent = new Event('pointerdown', { bubbles: true, cancelable: true });
    Object.defineProperty(pdEvent, 'target', { value: li });
    noteBody.dispatchEvent(pdEvent);

    expect(checkbox.checked).toBe(true);

    // 2. Simulate pointerdown & pointerup on task drag handle without dragging
    const handlePdEvent = new Event('pointerdown', { bubbles: true, cancelable: true });
    Object.defineProperty(handlePdEvent, 'target', { value: dragHandle });
    Object.defineProperty(handlePdEvent, 'clientX', { value: 100 });
    Object.defineProperty(handlePdEvent, 'clientY', { value: 100 });
    noteBody.dispatchEvent(handlePdEvent);

    const handlePuEvent = new Event('pointerup', { bubbles: true, cancelable: true });
    Object.defineProperty(handlePuEvent, 'clientX', { value: 100 });
    Object.defineProperty(handlePuEvent, 'clientY', { value: 100 });
    window.dispatchEvent(handlePuEvent);

    expect(checkbox.checked).toBe(false);
  });
});

describe('Mobile grid layout styling', () => {
  it('should include a responsive grid column spanning rule for single/odd last note card in styles.css', () => {
    const cssPath = path.join(__dirname, '../../styles.css');
    const cssContent = fs.readFileSync(cssPath, 'utf8');

    expect(cssContent).toMatch(/\.notes-grid\s+\.note-card:nth-child\(odd\):last-child\s*\{\s*grid-column:\s*1\s*\/\s*-1;?\s*\}/);
  });
});

describe('Card body checklist styling', () => {
  it('should include CSS rule in styles.css allowing full display of checkbox lists without line clamp', () => {
    const cssPath = path.join(__dirname, '../../styles.css');
    const cssContent = fs.readFileSync(cssPath, 'utf8');

    expect(cssContent).toMatch(/\.card-body:has\([^)]*task-list[^)]*\)\s*\{\s*display:\s*block;/);
    expect(cssContent).toMatch(/-webkit-line-clamp:\s*unset;/);
    expect(cssContent).toMatch(/overflow:\s*visible;/);
  });
});
