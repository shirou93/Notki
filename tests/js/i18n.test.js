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

describe('applyTranslations', () => {
  beforeEach(() => {
    jest.resetModules();
    document.body.innerHTML = '';
    window.notkiTranslations = {
      en: {
        'test.textContent': 'Text Content',
        'test.placeholder': 'Placeholder',
        'test.dataPlaceholder': 'Data Placeholder',
        'test.ariaLabel': 'Aria Label',
        'test.title': 'Title',
        'test.content': 'Content'
      }
    };
    require('../../i18n.js');
    window.i18n.setLanguage('en', { persist: false });
  });

  it('should translate textContent for elements with data-i18n', () => {
    document.body.innerHTML = '<div data-i18n="test.textContent"></div>';
    window.i18n.applyTranslations();
    expect(document.body.querySelector('div').textContent).toBe('Text Content');
  });

  it('should translate placeholder for elements with data-i18n-placeholder', () => {
    document.body.innerHTML = '<input data-i18n-placeholder="test.placeholder" />';
    window.i18n.applyTranslations();
    expect(document.body.querySelector('input').getAttribute('placeholder')).toBe('Placeholder');
  });

  it('should translate data-placeholder for elements with data-i18n-data-placeholder', () => {
    document.body.innerHTML = '<div data-i18n-data-placeholder="test.dataPlaceholder"></div>';
    window.i18n.applyTranslations();
    expect(document.body.querySelector('div').getAttribute('data-placeholder')).toBe('Data Placeholder');
  });

  it('should translate aria-label for elements with data-i18n-aria-label', () => {
    document.body.innerHTML = '<button data-i18n-aria-label="test.ariaLabel"></button>';
    window.i18n.applyTranslations();
    expect(document.body.querySelector('button').getAttribute('aria-label')).toBe('Aria Label');
  });

  it('should translate title for elements with data-i18n-title', () => {
    document.body.innerHTML = '<a data-i18n-title="test.title"></a>';
    window.i18n.applyTranslations();
    expect(document.body.querySelector('a').getAttribute('title')).toBe('Title');
  });

  it('should translate content for elements with data-i18n-content', () => {
    document.body.innerHTML = '<meta data-i18n-content="test.content" />';
    window.i18n.applyTranslations();
    expect(document.body.querySelector('meta').getAttribute('content')).toBe('Content');
  });

  it('should scope translations to a specific root element if provided', () => {
    document.body.innerHTML = `
      <div id="root1">
        <span data-i18n="test.textContent"></span>
      </div>
      <div id="root2">
        <span data-i18n="test.textContent"></span>
      </div>
    `;
    const root1 = document.getElementById('root1');
    const root2 = document.getElementById('root2');

    window.i18n.applyTranslations(root1);

    expect(root1.querySelector('span').textContent).toBe('Text Content');
    expect(root2.querySelector('span').textContent).toBe(''); // Should remain unchanged
  });
});

describe('admin panel translation keys', () => {
  const fs = require('fs');
  const path = require('path');

  const languages = ['pl', 'en', 'de', 'es', 'fr', 'it', 'ja', 'ko'];
  const requiredAdminKeys = [
    'admin.security.apply',
    'admin.backups.restoreFailed',
    'admin.invites.validityDays',
    'admin.security.sessionDays',
    'admin.update.betaChannel'
  ];

  languages.forEach(lang => {
    it(`should contain all required admin translation keys for language '${lang}'`, () => {
      const filePath = path.join(__dirname, `../../translations/${lang}.js`);
      const fileContent = fs.readFileSync(filePath, 'utf8');
      requiredAdminKeys.forEach(key => {
        expect(fileContent.includes(`'${key}'`) || fileContent.includes(`"${key}"`)).toBe(true);
      });
    });
  });
});
