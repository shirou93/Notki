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
  applyTranslations: jest.fn()
};

// require the module
const { bufferToBase64, getTaskStatsFromHtml, tableCell } = require('../../app.js');

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
