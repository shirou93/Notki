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
  getLanguage: jest.fn().mockReturnValue('en-US')
};

// require the module
const { bufferToBase64, getTaskStatsFromHtml, tableCell, createIconSvg, apiRequest } = require('../../app.js');

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

describe('apiRequest', () => {
  let originalFetch;

  beforeEach(() => {
    originalFetch = global.fetch;
    global.fetch = jest.fn();
    window.i18n.t.mockImplementation(key => `translated:${key}`);

    // Since apiRequest updates elements.storageNote internally via setOnlineStatus->updateStorageIndicator
    // We need to ensure the document has this element so it doesn't crash during DOM operations
    if (!document.querySelector('.storage-note')) {
      const el = document.createElement('div');
      el.className = 'storage-note';
      document.body.appendChild(el);
    }
  });

  afterEach(() => {
    global.fetch = originalFetch;
    jest.clearAllMocks();
  });

  it('should make a successful fetch request and return json payload', async () => {
    const mockPayload = { data: 'success' };
    global.fetch.mockResolvedValueOnce({
      ok: true,
      json: jest.fn().mockResolvedValueOnce(mockPayload)
    });

    const result = await apiRequest('/api/test');

    expect(global.fetch).toHaveBeenCalledWith('/api/test', expect.objectContaining({
      cache: 'no-store',
      credentials: 'same-origin',
      headers: expect.any(Headers)
    }));

    expect(result).toEqual(mockPayload);
  });

  it('should set Content-Type to application/json when body is provided', async () => {
    global.fetch.mockResolvedValueOnce({
      ok: true,
      json: jest.fn().mockResolvedValueOnce({})
    });

    await apiRequest('/api/test', { method: 'POST', body: JSON.stringify({ a: 1 }) });

    const callArgs = global.fetch.mock.calls[0];
    const headers = callArgs[1].headers;
    expect(headers.get('Content-Type')).toBe('application/json');
    expect(headers.get('Accept-Language')).toBe('en-US');
  });

  it('should preserve provided Content-Type header', async () => {
    global.fetch.mockResolvedValueOnce({
      ok: true,
      json: jest.fn().mockResolvedValueOnce({})
    });

    const customHeaders = new Headers({ 'Content-Type': 'text/plain' });
    await apiRequest('/api/test', { method: 'POST', body: 'some text', headers: customHeaders });

    const callArgs = global.fetch.mock.calls[0];
    const headers = callArgs[1].headers;
    expect(headers.get('Content-Type')).toBe('text/plain');
  });

  it('should throw payload.error if response is not ok', async () => {
    global.fetch.mockResolvedValueOnce({
      ok: false,
      json: jest.fn().mockResolvedValueOnce({ error: 'custom server error' })
    });

    await expect(apiRequest('/api/test')).rejects.toThrow('custom server error');
  });

  it('should throw fallback translated error if response is not ok and no payload error is present', async () => {
    global.fetch.mockResolvedValueOnce({
      ok: false,
      json: jest.fn().mockRejectedValueOnce(new Error('JSON parse error'))
    });

    await expect(apiRequest('/api/test')).rejects.toThrow('translated:error.server');
  });

  it('should handle network fetch failure', async () => {
    const networkError = new TypeError('Failed to fetch');
    global.fetch.mockRejectedValueOnce(networkError);

    await expect(apiRequest('/api/test')).rejects.toThrow(networkError);
  });
});
