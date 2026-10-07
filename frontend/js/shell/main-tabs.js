// Slides: copied from Cortex (static/js/shell/main-tabs.js); changes marked "Slides:".
// Tabs in the main area: "Recording" (the capture and review view) and one per opened knowledge-base document.
// The Recording tab starts closed: a session (recording, upload, an opened recording) brings it, and a project whose
// layout had it open reopens it (layout.js). A tab's view is built once and kept while the tab
// is open, so switching tabs keeps each document's scroll position and highlight.
// Any tab can float in its own window (↗ in its title bar): the tab leaves the strip while it
// floats, activating it brings the window forward, and closing the window docks it back here.
// Every tab closes (× on the tab and in the title bar); closing "Recording" only hides it - the
// session stays - and View > Recording, or a new session, brings it back.
import { floatView, frontView, DETACH_ICON, onUndockAll, onRestoreFloating } from './undock.js';
import { describe, focusOn, pane } from './focus.js';

const tabsEl = document.getElementById('main-tabs');
const viewsEl = document.getElementById('main-views');
const tabs = new Map();            // key -> { tab, view, closable, onClose }
let active = null;

// the title bar under the tabs, as the side panes have: the active view's name, ↗ and ×
const bar = Object.assign(document.createElement('div'), { className: 'sidebar-title-bar main-title-bar' });
const barTitle = Object.assign(document.createElement('span'), { className: 'sidebar-title' });
const barFloat = Object.assign(document.createElement('button'), { type: 'button', className: 'panel-undock-btn', title: 'Detach into a floating window', innerHTML: DETACH_ICON });
const barClose = Object.assign(document.createElement('button'), { type: 'button', className: 'sidebar-close-btn', title: 'Close panel',
  innerHTML: '<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18"/></svg>' });
barFloat.addEventListener('click', () => active && floatTab(active));
barClose.addEventListener('click', () => active && closeTab(active));
bar.append(barTitle, barFloat, barClose);
tabsEl.after(bar);

function render() {
  for (const [key, t] of tabs) {
    t.tab.classList.toggle('active', key === active);
    t.tab.setAttribute('aria-selected', String(key === active));
    if (!t.floating) t.view.hidden = key !== active;
  }
  const t = active && tabs.get(active);
  bar.hidden = !t;
  // no tab left in the strip (every one floating or closed): no empty white strip above the pane either
  tabsEl.hidden = ![...tabs.values()].some((x) => !x.tab.hidden);
  barTitle.classList.toggle('notranslate', !!t?.named);   // Slides: a named tab's title bar too
  barTitle.textContent = t ? (t.barTitle ?? t.tab.title) : '';
}

// The focus (focus.js): a tab's view says its name - its title bar's - and what its opener adds (openTab's
// `describe`, setDescribe): { literal, details }. A click on the strip or the title bar focuses the tab in front.
function describeTab(key) {
  const t = tabs.get(key);
  describe(t.view, () => ({ name: t.barTitle ?? t.tab.title, literal: t.named || undefined, ...(t.describe?.() || {}) }));
}
pane(tabsEl, () => (active ? tabs.get(active).view : null));
pane(bar, () => (active ? tabs.get(active).view : null));
/** What the status bar adds for `key` while it has the focus: fn() -> { literal, details } (focus.js). */
export function setDescribe(key, fn) { const t = tabs.get(key); if (t) t.describe = fn; }
window.setMainTabDescribe = setDescribe;     // sidebar.js describes the Recording tab (it knows the session)

const docked = () => [...tabs.keys()].filter((k) => !tabs.get(k).floating && !tabs.get(k).closed);

function floatTab(key) {
  const t = tabs.get(key);
  if (!t || t.floating) return;
  t.floating = true;
  t.tab.hidden = true;
  if (active === key) {
    active = null;
    const next = docked().at(-1);
    if (next) activate(next); else render();
  }
  focusOn(t.view, { activated: true });                  // the window it is now in has the focus
  floatView(`main:${key}`, t.view, {
    title: t.tab.title, width: key === 'recording' ? 1100 : 820, height: 760,
    onDock: (view, docked) => {
      t.floating = false;
      t.tab.hidden = false;
      viewsEl.append(view);
      if (docked) activate(key);
      else { view.hidden = true; closeTab(key); }        // its window's close closes the tab
    },
  });
}

// a tab that floated before a reload floats again once it is open (layout.js reopens it; undock.js retries)
onRestoreFloating('view:main:', (key) => {
  const t = tabs.get(key);
  if (!t || t.closed) return false;
  if (!t.floating) floatTab(key);
  return true;
});

function makeTab(key, title, closable, named = false) {
  const tab = document.createElement('button');
  tab.type = 'button';
  // Slides: a named tab (a project's or a deck's: a name people gave) is never translated (i18n.js); its × is
  tab.className = named ? 'main-tab notranslate' : 'main-tab';
  tab.setAttribute('role', 'tab');
  tab.title = title;
  tab.append(Object.assign(document.createElement('span'), { className: 'main-tab-title', textContent: title }));
  const close = Object.assign(document.createElement('span'), { className: 'main-tab-close', title: named ? window.cortexT('Close') : 'Close' });
  close.addEventListener('click', (e) => { e.stopPropagation(); closeTab(key); });
  tab.append(close);
  tab.addEventListener('click', () => activate(key));
  tab.addEventListener('auxclick', (e) => { if (e.button === 1) closeTab(key); });   // middle click
  return tab;
}

// Undock All (View menu): the tab in front of the middle pane - the Recording tab's sections float on
// their own (menu-commands.js makeUndockable), so it stays
onUndockAll(() => { const key = active; return key && key !== 'recording' ? () => floatTab(key) : null; });

export function activate(key) {
  if (!tabs.has(key)) return;
  const t = tabs.get(key);
  if (t.floating) { frontView(`main:${key}`); focusOn(t.view, { activated: true }); return; }
  if (t.closed) { t.closed = false; t.tab.hidden = false; }            // a hidden Recording tab, back
  active = key;
  render();
  focusOn(t.view, { activated: true });
  document.dispatchEvent(new CustomEvent('main-tab-activated', { detail: { key } }));
}

/** Open (or bring forward) the tab `key`. `build(view)` fills a new view once; the
 *  returned object is the tab's record, so callers can keep state on it. `describe()` -> { literal, details }: what the
 *  status bar shows beside the tab's name while it has the focus (focus.js). */
export function openTab(key, { title, build, onClose = null, describe: describeFn = null, named = false }) {
  if (tabs.has(key)) { activate(key); return tabs.get(key); }
  const view = document.createElement('div');
  view.className = 'main-view doc-view';
  view.setAttribute('role', 'tabpanel');
  viewsEl.append(view);
  const tab = makeTab(key, title, true, named);
  tabsEl.append(tab);
  const record = { tab, view, closable: true, onClose, describe: describeFn, named };
  tabs.set(key, record);
  describeTab(key);
  if (build) build(view, record);
  activate(key);
  document.dispatchEvent(new CustomEvent('main-tabs-changed', { detail: { opened: key, title } }));
  return record;
}

export function closeTab(key) {
  const t = tabs.get(key);
  if (!t) return;
  if (!t.closable) {                                // Recording: hidden, never destroyed (the session lives on)
    t.closed = true;
    t.tab.hidden = true;
    t.view.hidden = true;
    if (active === key) { const rest = docked(); if (rest.length) activate(rest[0]); else { active = null; render(); } }
    document.dispatchEvent(new CustomEvent('main-tabs-changed', { detail: { closed: key } }));   // the layout keeps it
    return;
  }
  const keys = [...tabs.keys()];
  const i = keys.indexOf(key);
  t.onClose?.();
  t.tab.remove();
  t.view.remove();
  tabs.delete(key);
  document.dispatchEvent(new CustomEvent('main-tabs-changed', { detail: { closed: key } }));
  if (active === key) { const rest = docked(); if (rest.length) activate(rest[Math.max(0, i - 1)] ?? rest[0]); else { active = null; render(); } }
}

export function setTitle(key, title) {
  const t = tabs.get(key);
  if (!t) return;
  t.tab.title = title;
  t.tab.querySelector('.main-tab-title').textContent = title;
  if (key === active) barTitle.textContent = title;
}

/** What the title bar says for `key` when it differs from its tab's label (the Recording tab: the session's name). */
export function setViewTitle(key, text) {
  const t = tabs.get(key);
  if (!t) return;
  t.barTitle = text;
  if (key === active) barTitle.textContent = text;
}
window.setMainViewTitle = setViewTitle;      // app.js is a classic script
window.showMainTab = (key) => activate(key);

export function isOpen(key) { return tabs.has(key); }
export function isShown(key) { const t = tabs.get(key); return !!t && !t.closed; }
export function activeKey() { return active; }
/** The closable tabs open now, in order (layout.js keeps them per project). */
export function openKeys() { return [...tabs.entries()].filter(([, t]) => t.closable).map(([k]) => k); }

// Slides: Cortex's permanent "Recording" tab is not created here (this app has no recording view); the remaining
// mentions of the 'recording' key above never match a key this app opens.
render();
