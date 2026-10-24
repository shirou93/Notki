const fs = require('fs');
const path = require('path');

describe('setup.js', () => {
  beforeEach(() => {
    jest.resetModules();

    const htmlPath = path.join(__dirname, '../../setup.html');
    const htmlContent = fs.readFileSync(htmlPath, 'utf8');
    document.body.innerHTML = htmlContent;

    window.i18n = {
      t: jest.fn(key => key),
      getLanguage: jest.fn(() => 'en'),
      onChange: jest.fn()
    };

    delete window.location;
    window.location = { replace: jest.fn() };

    global.fetch = jest.fn();
    global.FormData = class FormData { append(k, v) { this[k] = v; } };
  });

  afterEach(() => {
    jest.restoreAllMocks();
  });

  // Helper to run the module and wait for async checkSetup to finish
  const loadModule = async () => {
    require('../../setup.js');
    document.dispatchEvent(new Event('DOMContentLoaded'));
    await new Promise(resolve => setTimeout(resolve, 0));
  };

  describe('checkSetup', () => {
    it('redirects to / if setup is not needed', async () => {
      global.fetch.mockResolvedValueOnce({
        ok: true,
        json: async () => ({ needsSetup: false })
      });

      await loadModule();

      expect(global.fetch).toHaveBeenCalledWith('/api/setup/status', expect.any(Object));
      expect(window.location.replace).toHaveBeenCalledWith('/');
    });

    it('shows connection error if status check fails', async () => {
      global.fetch.mockRejectedValueOnce(new Error('Network error'));

      await loadModule();

      const message = document.querySelector('#setup-message');
      expect(message.textContent).toBe('Network error');
      expect(message.dataset.kind).toBe('connection');
      expect(message.hidden).toBe(false);
    });
  });

  describe('Admin Setup Form', () => {
    beforeEach(() => {
      // Setup checkSetup to pass normally without redirecting
      global.fetch.mockResolvedValueOnce({
        ok: true,
        json: async () => ({ needsSetup: true })
      });
    });

    it('prevents submission when passwords mismatch', async () => {
      await loadModule();

      document.querySelector('#setup-token').value = 'test-setup-token';
      document.querySelector('#setup-email').value = 'admin@example.com';
      document.querySelector('#setup-password').value = 'password123';
      document.querySelector('#setup-confirm').value = 'password456';

      const form = document.querySelector('#setup-form');
      form.dispatchEvent(new Event('submit', { cancelable: true }));

      const message = document.querySelector('#setup-message');
      expect(message.textContent).toBe('setup.passwordMismatch');
      expect(message.hidden).toBe(false);

      // Ensure fetch wasn't called for the form submission
      expect(global.fetch).toHaveBeenCalledTimes(1); // Only checkSetup was called
    });

    it('requires the setup token before submitting', async () => {
      await loadModule();

      document.querySelector('#setup-email').value = 'admin@example.com';
      document.querySelector('#setup-password').value = 'password123';
      document.querySelector('#setup-confirm').value = 'password123';

      const form = document.querySelector('#setup-form');
      form.dispatchEvent(new Event('submit', { cancelable: true }));

      const message = document.querySelector('#setup-message');
      expect(message.textContent).toBe('setup.tokenRequired');
      expect(global.fetch).toHaveBeenCalledTimes(1);
    });

    it('successfully creates an admin and redirects', async () => {
      await loadModule();

      document.querySelector('#setup-token').value = 'test-setup-token';
      document.querySelector('#setup-email').value = 'admin@example.com';
      document.querySelector('#setup-password').value = 'password123';
      document.querySelector('#setup-confirm').value = 'password123';

      // Mock the successful form submission fetch
      global.fetch.mockResolvedValueOnce({
        ok: true,
        json: async () => ({})
      });

      const form = document.querySelector('#setup-form');
      form.dispatchEvent(new Event('submit', { cancelable: true }));

      await new Promise(resolve => setTimeout(resolve, 0)); // Wait for async submit to finish

      expect(global.fetch).toHaveBeenCalledWith('/api/setup/admin', expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ email: 'admin@example.com', password: 'password123' })
      }));
      expect(window.location.replace).toHaveBeenCalledWith('/');
    });

    it('handles server errors during admin creation', async () => {
      await loadModule();

      document.querySelector('#setup-token').value = 'test-setup-token';
      document.querySelector('#setup-email').value = 'admin@example.com';
      document.querySelector('#setup-password').value = 'password123';
      document.querySelector('#setup-confirm').value = 'password123';

      // Mock an API error format for the form submission
      global.fetch.mockResolvedValueOnce({
        ok: false,
        json: async () => ({ error: 'Invalid email' })
      });

      const form = document.querySelector('#setup-form');
      const button = form.querySelector('button[type="submit"]');

      form.dispatchEvent(new Event('submit', { cancelable: true }));

      await new Promise(resolve => setTimeout(resolve, 0));

      const message = document.querySelector('#setup-message');
      expect(message.textContent).toBe('Invalid email');
      expect(message.hidden).toBe(false);
      expect(button.disabled).toBe(false);
    });
  });

});
