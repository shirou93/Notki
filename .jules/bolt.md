## 2026-10-13 - Rich Text Extract Memoization with WeakMap
**Learning:** In frontend search inputs and list filtering loops, calling DOM text parsing routines (`document.createElement('div')` + `sanitizeRichHtml`) on rich-text note objects on every keypress blocks the main thread. Caching extracted plain text in a `WeakMap` keyed by note object avoids DOM parsing overhead on search inputs while preventing memory leaks or extra object properties.
**Action:** Always memoize DOM-parsing string transformations in search/filtering render cycles using `WeakMap`.
