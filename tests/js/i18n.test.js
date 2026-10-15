const { normalizeLanguage } = require('../../i18n.js');

describe('normalizeLanguage', () => {
  it('should return empty string for null or undefined', () => {
    expect(normalizeLanguage(null)).toBe('');
    expect(normalizeLanguage(undefined)).toBe('');
  });

  it('should return empty string for empty or whitespace-only strings', () => {
    expect(normalizeLanguage('')).toBe('');
    expect(normalizeLanguage('   ')).toBe('');
  });

  it('should return the correct language code for exact supported tags', () => {
    expect(normalizeLanguage('en')).toBe('en');
    expect(normalizeLanguage('pl')).toBe('pl');
    expect(normalizeLanguage('de')).toBe('de');
    expect(normalizeLanguage('fr')).toBe('fr');
    expect(normalizeLanguage('ja')).toBe('ja');
    expect(normalizeLanguage('ko')).toBe('ko');
    expect(normalizeLanguage('it')).toBe('it');
    expect(normalizeLanguage('es')).toBe('es');
  });

  it('should strip region codes from supported language tags', () => {
    expect(normalizeLanguage('en-US')).toBe('en');
    expect(normalizeLanguage('en-GB')).toBe('en');
    expect(normalizeLanguage('pl-PL')).toBe('pl');
    expect(normalizeLanguage('fr-CA')).toBe('fr');
  });

  it('should handle uppercase and mixed-case supported tags correctly', () => {
    expect(normalizeLanguage('EN')).toBe('en');
    expect(normalizeLanguage('Pl')).toBe('pl');
    expect(normalizeLanguage('de-DE')).toBe('de');
    expect(normalizeLanguage('eN-uS')).toBe('en');
  });

  it('should handle strings with leading and trailing whitespaces', () => {
    expect(normalizeLanguage('  en  ')).toBe('en');
    expect(normalizeLanguage('\tfr-FR\n')).toBe('fr');
  });

  it('should return empty string for unsupported language codes', () => {
    expect(normalizeLanguage('zh')).toBe('');
    expect(normalizeLanguage('ru-RU')).toBe('');
    expect(normalizeLanguage('unknown')).toBe('');
    expect(normalizeLanguage('xx-YY')).toBe('');
  });

  it('should handle non-string inputs safely', () => {
    expect(normalizeLanguage(123)).toBe('');
    expect(normalizeLanguage({})).toBe('');
    expect(normalizeLanguage([])).toBe('');
    expect(normalizeLanguage(true)).toBe('');
    expect(normalizeLanguage(false)).toBe('');
  });
});
