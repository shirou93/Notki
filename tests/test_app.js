const assert = require('assert');

// Mock minimal browser environment required to load app.js
global.window = {
    location: { search: '', pathname: '', hash: '', replace: () => {} },
    i18n: { getLanguage: () => 'en', onChange: () => {}, t: (k) => k, plural: (k) => k, formatDateTime: () => '', formatDate: () => '', applyTranslations: () => {} },
    addEventListener: () => {},
    matchMedia: () => ({ matches: false }),
    history: { replaceState: () => {}, pushState: () => {} },
    setTimeout: () => {},
    clearTimeout: () => {},
};

const dummyElement = {
    addEventListener: () => {},
    classList: { add: () => {}, remove: () => {}, toggle: () => {}, contains: () => false },
    setAttribute: () => {},
    removeAttribute: () => {},
    style: {},
    appendChild: () => {},
    append: () => {},
    replaceChildren: () => {},
    dataset: {}
};

global.document = {
    querySelector: () => dummyElement,
    querySelectorAll: () => [],
    getElementById: () => dummyElement,
    addEventListener: () => {},
    createElement: () => dummyElement,
    createElementNS: () => dummyElement,
    body: dummyElement,
    documentElement: dummyElement
};

global.navigator = { onLine: true };
global.localStorage = { getItem: () => null, setItem: () => {}, removeItem: () => {} };
global.URLSearchParams = class URLSearchParams { get() { return null; } };
global.crypto = { randomUUID: () => 'uuid' };

// Mock global fetch for initialization
global.fetch = async () => ({
    ok: false,
    json: async () => ({})
});

// Import the module
const app = require('../app.js');

function runTests() {
    console.log("Running getCacheKey tests...");

    // Happy path tests
    assert.strictEqual(app.getCacheKey('123', 'notes'), 'notki.cache.notes.123', 'Should format string correctly');
    assert.strictEqual(app.getCacheKey('userA', 'labels'), 'notki.cache.labels.userA', 'Should handle alphanumeric strings');
    assert.strictEqual(app.getCacheKey(123, 'test'), 'notki.cache.test.123', 'Should handle numeric userId');

    // Edge cases
    assert.strictEqual(app.getCacheKey('', ''), 'notki.cache..', 'Should handle empty strings');
    assert.strictEqual(app.getCacheKey(null, null), 'notki.cache.null.null', 'Should convert nulls to strings');
    assert.strictEqual(app.getCacheKey(undefined, undefined), 'notki.cache.undefined.undefined', 'Should convert undefined to strings');

    console.log("All getCacheKey tests passed successfully! ✅");
    process.exit(0);
}

try {
    runTests();
} catch (error) {
    console.error("Test failed: ", error.message);
    process.exit(1);
}
