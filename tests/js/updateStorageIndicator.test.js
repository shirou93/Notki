const fs = require('fs');
const path = require('path');

const indexHtmlPath = path.join(__dirname, '../../index.html');
const indexHtmlContent = fs.readFileSync(indexHtmlPath, 'utf8');
document.body.innerHTML = indexHtmlContent;

// Mock window.matchMedia
Object.defineProperty(window, 'matchMedia', {
  writable: true,
  value: jest.fn().mockImplementation(query => ({
    matches: false,
  })),
});

window.i18n = {
  t: jest.fn(key => key),
  plural: jest.fn(),
  onChange: jest.fn(),
  applyTranslations: jest.fn(),
  formatDate: jest.fn(),
  formatFullDate: jest.fn(),
  formatDateTime: jest.fn(),
  getLanguage: jest.fn(() => 'pl')
};

const {
  updateStorageIndicator,
  setIsOffline,
  setIsSyncing,
  setPendingSync,
  setCurrentUser,
  queueSync,
} = require('../../app.js');

global.DOMPurify = require('dompurify')(window);

describe('updateStorageIndicator', () => {
  let container, dot, label, topbarSync;

  beforeEach(() => {
    // Reset DOM state before each test if necessary, but index.html has it
    document.body.innerHTML = indexHtmlContent;
    container = document.querySelector('.storage-note');
    dot = container.querySelector('.storage-dot');
    label = container.querySelector('span:not(.storage-dot)');

    topbarSync = document.getElementById('topbar-sync-button');

    // Reset module state
    setIsOffline(false);
    setIsSyncing(false);
    setPendingSync(false);
    setCurrentUser(null);
    localStorage.clear();
  });

  it('handles offline state correctly', () => {
    setIsOffline(true);
    updateStorageIndicator();

    if (topbarSync) {
      expect(topbarSync.hidden).toBe(false);
      expect(topbarSync.disabled).toBe(false);
    }

    expect(dot.style.background).toBe('rgb(229, 115, 115)'); // #e57373 -> hex to rgb
    expect(label.textContent).toBe('nav.storageOffline');
  });

  it('handles syncing state correctly', () => {
    setIsSyncing(true);
    updateStorageIndicator();

    if (topbarSync) {
      expect(topbarSync.hidden).toBe(true);
      expect(topbarSync.disabled).toBe(true);
    }

    expect(dot.style.background).toBe('rgb(230, 200, 117)'); // #e6c875
    expect(label.textContent).toBe('nav.storageSyncing');
  });

  it('handles pending sync state with user correctly', () => {
    setCurrentUser({ id: 'user1' });
    setPendingSync(true);
    updateStorageIndicator();

    if (topbarSync) {
      expect(topbarSync.hidden).toBe(true);
      expect(topbarSync.disabled).toBe(false);
    }

    expect(dot.style.background).toBe('rgb(230, 200, 117)'); // #e6c875
    expect(label.textContent).toBe('nav.storageSyncing');
  });

  it('handles pending sync state from cache with user correctly', () => {
    setCurrentUser({ id: 'user1' });
    queueSync('user1'); // Sets cache for pending sync
    updateStorageIndicator();

    expect(dot.style.background).toBe('rgb(230, 200, 117)');
    expect(label.textContent).toBe('nav.storageSyncing');
  });

  it('handles default online/saved state correctly', () => {
    updateStorageIndicator();

    if (topbarSync) {
      expect(topbarSync.hidden).toBe(true);
      expect(topbarSync.disabled).toBe(false);
    }

    expect(dot.style.background).toBe('rgb(169, 211, 119)'); // #a9d377
    expect(label.textContent).toBe('nav.storage');
  });

  it('does nothing if container is missing', () => {
    container.remove(); // Removes it from the DOM
    setIsOffline(true);

    expect(() => {
        updateStorageIndicator();
    }).not.toThrow();
  });

});
