describe('theme.js', () => {
  const STORAGE_KEY = 'notki.theme.v1';
  let matchMediaMock;
  let matchMediaListeners = [];

  beforeEach(() => {
    jest.resetModules();

    // Clear listeners array for each test
    matchMediaListeners = [];

    // Mock matchMedia
    matchMediaMock = {
      matches: false,
      addEventListener: jest.fn((event, callback) => {
        if (event === 'change') {
          matchMediaListeners.push(callback);
        }
      }),
      removeEventListener: jest.fn(),
    };

    Object.defineProperty(window, 'matchMedia', {
      writable: true,
      value: jest.fn().mockImplementation(query => matchMediaMock),
    });

    // Mock localStorage
    const localStorageMock = (() => {
      let store = {};
      return {
        getItem: jest.fn(key => store[key] || null),
        setItem: jest.fn((key, value) => {
          store[key] = value.toString();
        }),
        removeItem: jest.fn(key => {
          delete store[key];
        }),
        clear: jest.fn(() => {
          store = {};
        }),
      };
    })();

    Object.defineProperty(window, 'localStorage', {
      value: localStorageMock,
      writable: true
    });

    window.localStorage.clear();

    // Setup DOM
    document.documentElement.dataset.theme = '';
    document.head.innerHTML = '<meta name="theme-color" content="#f6f8f5">';
    document.body.innerHTML = `
      <select data-theme-select>
        <option value="light">Light</option>
        <option value="dark">Dark</option>
        <option value="system">System</option>
      </select>
    `;
  });

  function loadThemeModule() {
    require('../../theme.js');
  }

  describe('getTheme', () => {
    it('returns "dark" when document.documentElement.dataset.theme is "dark"', () => {
      loadThemeModule();
      document.documentElement.dataset.theme = 'dark';
      expect(window.notkiTheme.get()).toBe('dark');
    });

    it('returns "light" when document.documentElement.dataset.theme is not "dark"', () => {
      loadThemeModule();
      document.documentElement.dataset.theme = 'light';
      expect(window.notkiTheme.get()).toBe('light');

      document.documentElement.dataset.theme = '';
      expect(window.notkiTheme.get()).toBe('light');
    });
  });

  describe('setTheme', () => {
    it('sets light theme', () => {
      loadThemeModule();
      window.notkiTheme.set('light');
      expect(document.documentElement.dataset.theme).toBe('light');
      expect(document.querySelector('meta[name="theme-color"]').getAttribute('content')).toBe('#f6f8f5');
    });

    it('sets dark theme', () => {
      loadThemeModule();
      window.notkiTheme.set('dark');
      expect(document.documentElement.dataset.theme).toBe('dark');
      expect(document.querySelector('meta[name="theme-color"]').getAttribute('content')).toBe('#141c17');
    });

    it('sets system theme based on system preference (light)', () => {
      matchMediaMock.matches = false;
      loadThemeModule();
      window.notkiTheme.set('system');
      expect(document.documentElement.dataset.theme).toBe('light');
      expect(document.querySelector('meta[name="theme-color"]').getAttribute('content')).toBe('#f6f8f5');
    });

    it('sets system theme based on system preference (dark)', () => {
      matchMediaMock.matches = true;
      loadThemeModule();
      window.notkiTheme.set('system');
      expect(document.documentElement.dataset.theme).toBe('dark');
      expect(document.querySelector('meta[name="theme-color"]').getAttribute('content')).toBe('#141c17');
    });

    it('persists theme to localStorage when persist is true', () => {
      loadThemeModule();
      window.notkiTheme.set('dark', { persist: true });
      expect(window.localStorage.setItem).toHaveBeenCalledWith(STORAGE_KEY, 'dark');
    });

    it('removes theme from localStorage when setting system theme with persist true', () => {
      loadThemeModule();
      window.localStorage.setItem(STORAGE_KEY, 'dark');
      window.notkiTheme.set('system', { persist: true });
      expect(window.localStorage.removeItem).toHaveBeenCalledWith(STORAGE_KEY);
    });

    it('does not persist theme when persist is false', () => {
      loadThemeModule();
      window.notkiTheme.set('dark', { persist: false });
      expect(window.localStorage.setItem).not.toHaveBeenCalled();
    });

    it('returns the resolved theme', () => {
      loadThemeModule();
      expect(window.notkiTheme.set('dark')).toBe('dark');
      matchMediaMock.matches = true;
      expect(window.notkiTheme.set('system')).toBe('dark');
    });
  });

  describe('onChange', () => {
    it('notifies listeners when theme is set', () => {
      loadThemeModule();
      const listener = jest.fn();
      window.notkiTheme.onChange(listener);

      window.notkiTheme.set('dark');
      expect(listener).toHaveBeenCalledWith('dark');
    });

    it('allows detaching listeners', () => {
      loadThemeModule();
      const listener = jest.fn();
      const detach = window.notkiTheme.onChange(listener);

      detach();
      window.notkiTheme.set('dark');
      expect(listener).not.toHaveBeenCalled();
    });
  });

  describe('syncControls', () => {
    it('syncs select elements with stored preference', () => {
      window.localStorage.setItem(STORAGE_KEY, 'dark');
      loadThemeModule(); // initialize calls syncControls

      expect(document.querySelector('select[data-theme-select]').value).toBe('dark');
    });

    it('defaults to system if stored preference is invalid', () => {
      window.localStorage.setItem(STORAGE_KEY, 'invalid-theme');
      loadThemeModule();

      expect(document.querySelector('select[data-theme-select]').value).toBe('system');
    });

    it('can be triggered manually', () => {
      loadThemeModule();
      window.localStorage.setItem(STORAGE_KEY, 'dark');

      window.notkiTheme.sync();
      expect(document.querySelector('select[data-theme-select]').value).toBe('dark');
    });
  });

  describe('Event Listeners', () => {
    it('sets persisted theme when select value changes', () => {
      loadThemeModule();
      const select = document.querySelector('select[data-theme-select]');

      // Simulate change event
      select.value = 'dark';
      select.dispatchEvent(new Event('change'));

      expect(document.documentElement.dataset.theme).toBe('dark');
      expect(window.localStorage.setItem).toHaveBeenCalledWith(STORAGE_KEY, 'dark');
    });

    it('updates active theme when system preference changes and stored theme is system', () => {
      // Setup stored theme as system (or null)
      window.localStorage.removeItem(STORAGE_KEY);
      loadThemeModule();

      // Initial state is system(light)
      expect(document.documentElement.dataset.theme).toBe('light');

      // Change system preference to dark
      matchMediaMock.matches = true;
      matchMediaListeners.forEach(listener => listener(new Event('change')));

      expect(document.documentElement.dataset.theme).toBe('dark');
    });

    it('does not update active theme when system preference changes and stored theme is not system', () => {
      window.localStorage.setItem(STORAGE_KEY, 'light');
      loadThemeModule();

      expect(document.documentElement.dataset.theme).toBe('light');

      // Change system preference to dark
      matchMediaMock.matches = true;
      matchMediaListeners.forEach(listener => listener(new Event('change')));

      // Should still be light
      expect(document.documentElement.dataset.theme).toBe('light');
    });
  });
});
