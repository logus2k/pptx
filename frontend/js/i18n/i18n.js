// Slides: copied from Cortex (static/js/i18n/i18n.js). Changes marked "Slides:": the storage key, European Portuguese
// as the default (English on request), and this app's content areas in CONTENT.
// The interface language (the profile menu: Português or English; localStorage slides.uiLanguage).
// A classic script loaded right after project-boot.js, before the body: it translates the page AS IT IS BUILT, so
// the English never shows first. One dictionary (i18n/pt.js: window.CORTEX_PT, English -> Portuguese) and one
// observer - the page's code writes English, every text node and title / placeholder / aria-label the page puts
// on screen is looked up:
//   exact      "Knowledge Base Manager..."            -> "Gestor da base de conhecimento..."
//   template   "{0} documents · {1} passages"          -> "{0} documentos · {1} passagens"  (the holes found by plain
//              substring search between the literal parts - no regular expressions)
// What people and models wrote is never touched: articles, transcripts, answers, documents, trainings' questions and
// the manual (which has its own Portuguese edition) are excluded by CONTENT below.
//   window.cortexT(text)   the same lookup, for text that never reaches the page as such (window.prompt, confirm)
//   window.uiLanguage()  'en' | 'pt'
(function () {
  var KEY = 'slides.uiLanguage';                 // Slides: own key (localStorage is shared with Cortex on the same host)
  var lang = 'pt';                                // Slides: European Portuguese unless English was chosen
  try { lang = localStorage.getItem(KEY) === 'en' ? 'en' : 'pt'; } catch (e) { /* storage unavailable: Portuguese */ }
  window.uiLanguage = function () { return lang; };
  window.cortexT = function (s) { return s; };
  // Slides: the audit (localStorage slides.i18nAudit = '1', used by the browser checks): every interface text the
  // dictionary lacks is recorded in window.i18nMisses; in English the page itself is left as it is
  var audit = false;
  try { audit = localStorage.getItem('slides.i18nAudit') === '1'; } catch (e) { /* storage unavailable: no audit */ }
  if (lang !== 'pt' && !audit) return;
  var misses = window.i18nMisses = [];
  var where = window.i18nWhere = {};             // text -> the element it was met in (tag.class), for the audit's report
  function miss(text, el) {
    var core = text.trim();
    if (!audit || !core || core.toLowerCase() === core.toUpperCase() || misses.indexOf(core) >= 0) return;
    misses.push(core);
    where[core] = el ? el.tagName.toLowerCase() + (el.className && typeof el.className === 'string' ? '.' + el.className.split(' ').join('.') : '') : '';
  }
  if (lang === 'pt') document.documentElement.lang = 'pt-PT';

  // the content areas: what people and models wrote, never translated
  // Slides: this app's content areas (what people, decks and the model wrote); Cortex's own list removed
  var CONTENT = [
    '.notranslate', 'textarea', 'input', '[contenteditable="true"]', 'code', 'pre',
    '.chat-msg.bot .chat-body', '.chat-msg.me', '.chat-think-body', '.notif-body .notif-text',
    '.user-text', '.slide-text', '.identity-name', '.identity-email',
  ].join(', ');
  // for attributes (title, placeholder, aria-label) a field is interface, not content: its words are never touched
  // (the text nodes of a textarea are), but its placeholder and tooltip are translated
  var CONTENT_ATTR = CONTENT.split(', ').filter(function (s) { return s !== 'textarea' && s !== 'input' && s !== '[contenteditable="true"]'; }).join(', ');

  var exact = Object.create(null);
  var templates = [];                       // { parts: [literal...], order: [hole index...], to: 'pt {0} …' }
  function holes(s) {                       // "a {0} b {1}" -> { parts: ['a ', ' b ', ''], order: [0, 1] }
    var parts = [], order = [], cur = '', i = 0;
    while (i < s.length) {
      if (s[i] === '{') {
        var j = s.indexOf('}', i);
        var n = j > i ? s.slice(i + 1, j) : '';
        if (n !== '' && String(Number(n)) === n) { parts.push(cur); cur = ''; order.push(Number(n)); i = j + 1; continue; }
      }
      cur += s[i]; i += 1;
    }
    parts.push(cur);
    return { parts: parts, order: order };
  }
  function load(dict) {
    Object.keys(dict).forEach(function (en) {
      if (en.indexOf('{0}') < 0) { exact[en] = dict[en]; return; }
      var h = holes(en);
      templates.push({ parts: h.parts, order: h.order, to: dict[en] });
    });
    // longer literal text first: the most specific template wins
    templates.sort(function (a, b) { return b.parts.join('').length - a.parts.join('').length; });
  }
  function fill(to, values) {
    var out = '', i = 0;
    while (i < to.length) {
      if (to[i] === '{') {
        var j = to.indexOf('}', i);
        var n = j > i ? to.slice(i + 1, j) : '';
        if (n !== '' && String(Number(n)) === n && values[Number(n)] !== undefined) { out += values[Number(n)]; i = j + 1; continue; }
      }
      out += to[i]; i += 1;
    }
    return out;
  }
  function matchTemplate(text) {
    for (var k = 0; k < templates.length; k++) {
      var tp = templates[k], parts = tp.parts, last = parts.length - 1;
      if (!text.startsWith(parts[0]) || !text.endsWith(parts[last])) continue;
      if (text.length < parts[0].length + parts[last].length) continue;
      var pos = parts[0].length, values = [], ok = true;
      for (var p = 1; p <= last; p++) {
        if (p < last && parts[p] === '') { ok = false; break; }       // two holes in a row: ambiguous
        var at = p === last ? text.length - parts[last].length : text.indexOf(parts[p], pos);
        if (at < pos) { ok = false; break; }
        var value = text.slice(pos, at);
        if (value === '') { ok = false; break; }
        values[tp.order[p - 1]] = translate(value, true);                // a hole may hold a translatable label
        pos = at + parts[p].length;
      }
      if (ok) return fill(tp.to, values);
    }
    return null;
  }
  // the lookup: exact (the trimmed text, its surrounding spaces kept), else a template; null = not in the dictionary
  function translate(text, inner) {
    if (!text) return null;
    var start = 0, end = text.length;
    while (start < end && (text[start] === ' ' || text[start] === '\n' || text[start] === '\t')) start++;
    while (end > start && (text[end - 1] === ' ' || text[end - 1] === '\n' || text[end - 1] === '\t')) end--;
    var core = text.slice(start, end);
    if (!core) return null;
    var hit = exact[core];
    if (hit === undefined) hit = matchTemplate(core);
    if (hit == null) return inner ? text : null;
    return text.slice(0, start) + hit + text.slice(end);
  }
  if (lang === 'pt') window.cortexT = function (s) { var r = translate(String(s)); return r == null ? s : r; };

  var ATTRS = ['title', 'placeholder', 'aria-label'];
  // what this translator wrote, per text node and per attribute: never translated again. Its own output can match
  // a template once more - "16 total" -> "16 no total" still ends in " total" - and was rewritten without end
  // (measured 2026-10-03: the page hung in Access control); the page's next English text is translated as usual.
  var wroteText = new WeakMap();
  var wroteAttr = new WeakMap();
  function excluded(el) { return !!(el && el.closest && el.closest(CONTENT)); }
  function excludedAttr(el) { return !!(el && el.closest && el.closest(CONTENT_ATTR)); }
  function doText(node) {
    var el = node.parentElement;
    // Slides: the page title is the application's name, the same in every language
    if (!el || el.tagName === 'SCRIPT' || el.tagName === 'STYLE' || el.tagName === 'TITLE' || excluded(el)) return;
    if (wroteText.get(node) === node.nodeValue) return;
    var r = translate(node.nodeValue);
    if (r == null) miss(node.nodeValue, el);
    if (lang !== 'pt') return;
    if (r != null && r !== node.nodeValue) { node.nodeValue = r; wroteText.set(node, r); }
  }
  function doAttrs(el) {
    if (excludedAttr(el)) return;
    var mine = wroteAttr.get(el);
    for (var i = 0; i < ATTRS.length; i++) {
      var v = el.getAttribute(ATTRS[i]);
      if (!v || (mine && mine[ATTRS[i]] === v)) continue;
      var r = translate(v);
      if (r == null) miss(v, el);
      if (lang !== 'pt') continue;
      if (r != null && r !== v) {
        el.setAttribute(ATTRS[i], r);
        if (!mine) { mine = {}; wroteAttr.set(el, mine); }
        mine[ATTRS[i]] = r;
      }
    }
  }
  function walk(root) {
    if (root.nodeType === 3) { doText(root); return; }
    if (root.nodeType !== 1) return;
    doAttrs(root);
    if (excluded(root)) return;
    var w = document.createTreeWalker(root, NodeFilter.SHOW_TEXT | NodeFilter.SHOW_ELEMENT);
    var n = w.nextNode();
    while (n) {
      if (n.nodeType === 3) doText(n);
      else doAttrs(n);
      n = w.nextNode();
    }
  }
  var observer = new MutationObserver(function (records) {
    for (var i = 0; i < records.length; i++) {
      var r = records[i];
      if (r.type === 'childList') for (var j = 0; j < r.addedNodes.length; j++) walk(r.addedNodes[j]);
      else if (r.type === 'characterData') doText(r.target);
      else if (r.type === 'attributes') doAttrs(r.target);
    }
  });
  function start() {
    load(window.CORTEX_PT || {});
    observer.observe(document.documentElement, { childList: true, subtree: true, characterData: true,
                                                  attributes: true, attributeFilter: ATTRS });
    if (document.body) walk(document.body);
  }
  // the dictionary is the next script (i18n/pt.js); start as soon as it has defined it
  if (window.CORTEX_PT) start();
  else window.__cortexI18nStart = start;
})();
