// Slides: copied from Cortex (static/js/shell/undock.js); only the storage keys changed (marked "Slides:").
// Floating windows. Two kinds of thing float, both by MOVING their element into a jsPanel,
// so everything bound to it keeps working, and closing the window docks it back:
//   - sections (Transcript, Article, Timeline): undock()/dock(), back to where they were;
//   - tab views (the left pane's, the right pane's, the main area's): floatView(), whose
//     owner puts the view back into its tabs (onDock) - see sidebar.js, right-panel.js,
//     main-tabs.js.
// Windows are styled like the player's (.cortex-window: the jarbas control box) and remember
// where they were and how big, per browser (by key).


// the detach / reattach icons, shared by every title bar, section and floating window: a diagonal double arrow
// pointing out (detach: it opens out into its own window) or two arrows pointing in (reattach: it goes back into the
// page). No frame, and the close button's span (6-18) and stroke, so the two read as a pair
const svg = (inner) => `<svg class="dock-icon" viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${inner}</svg>`;
export const DETACH_ICON = svg('<path d="M6 18L18 6"/><path d="M12 6h6v6"/><path d="M6 12v6h6"/>');
export const ATTACH_ICON = svg('<path d="M18 6l-4 4"/><path d="M14 6.5V10h3.5"/><path d="M6 18l4-4"/><path d="M10 17.5V14H6.5"/>');

const REMEMBERED = 'slides.windows';   // Slides: own key
const windows = new Map();                 // section element -> { panel, placeholder }

function held(key) {
  try { return (JSON.parse(localStorage.getItem(REMEMBERED) || '{}'))[key] || null; } catch { return null; }
}
function remember(key, panel) {
  try {
    const all = JSON.parse(localStorage.getItem(REMEMBERED) || '{}');
    const r = panel.getBoundingClientRect();
    all[key] = { left: Math.round(r.left), top: Math.round(r.top), width: Math.round(r.width), height: Math.round(r.height) };
    localStorage.setItem(REMEMBERED, JSON.stringify(all));
  } catch { /* storage unavailable: the window just opens at its default place */ }
}

// ── which windows float, kept across a reload (and, like every "cortex." key, with the project's workspace) ──
// The keys of the windows open now, from the bottom of the stack to its top (cortex.floating). A reload floats them again
// (restoreFloating, once the layout has reopened its tabs), each at its remembered place (cortex.windows). Dock All
// docks them all and forgets their places: undocked again, each opens where it first did (a reset). A window
// reattached or closed on its own leaves the list and keeps its place.
const FLOATING = 'slides.floating';   // Slides: own key
function floatingKeys() {
  try { const v = JSON.parse(localStorage.getItem(FLOATING) || '[]'); return Array.isArray(v) ? v : []; } catch { return []; }
}
function setFloating(keys) { try { localStorage.setItem(FLOATING, JSON.stringify(keys)); } catch { /* not kept */ } }
// the stacking too: a window brought to the front moves to the end of the list, so the reload, opening them in that
// order, stacks them as they were (the last opened is on top)
document.addEventListener('jspanelfronted', (e) => {
  const key = document.getElementById(e.detail)?.dataset.windowKey;
  const keys = floatingKeys();
  if (key && keys.includes(key) && keys.at(-1) !== key) setFloating([...keys.filter((k) => k !== key), key]);
});
let leaving = false;                       // the page is going away: its windows are not being closed
addEventListener('pagehide', () => { leaving = true; });
const restorers = [];                      // { prefix, fn(rest) -> true when it floated it }
/** How to float a window again after a reload: for a key starting with `prefix`, fn(the rest of the key) floats it
 *  (sidebar.js, right-panel.js, main-tabs.js, the sections) and returns true; false when it cannot be floated now
 *  (its document is gone, no recording is open), and then it is tried again when a main tab comes forward. */
export function onRestoreFloating(prefix, fn) { restorers.push({ prefix, fn }); }
let pending = [];
function tryRestore(keys) {
  const left = [];
  for (const key of keys) {
    if (isOpenKey(key)) continue;
    const r = restorers.filter((x) => key.startsWith(x.prefix)).sort((a, b) => b.prefix.length - a.prefix.length)[0];
    let done = false;
    try { done = !!(r && r.fn(key.slice(r.prefix.length))); } catch (e) { console.error('restore window', key, e); }
    if (!done && r) left.push(key);
  }
  restack();
  return left;
}
// what floated again, stacked as it was: brought forward from the bottom of the list to its top (a window that could
// float only later - its tab reopened after the others - would otherwise end on top)
function restack() {
  for (const key of floatingKeys()) {
    const panel = document.querySelector(`.jsPanel.cortex-window[data-window-key="${CSS.escape(key)}"]`);
    try { panel?.front(); } catch { /* closed meanwhile */ }
  }
}
// a window's key: a section's own ('transcript'), or 'view:' + a tab view's ('view:left:kb')
function isOpenKey(key) {
  return key.startsWith('view:') ? views.has(key.slice('view:'.length)) : [...windows.values()].some((w) => w.key === key);
}
function restoreFloating() {
  const keys = floatingKeys();
  pending = tryRestore(keys);
  // kept in the list: what could not float yet (it may later), and what did; nothing else
  setFloating(keys.filter((k) => pending.includes(k) || isOpenKey(k)));
}
for (const ev of ['main-tab-activated', 'recording-loaded']) {
  document.addEventListener(ev, () => { if (pending.length) pending = tryRestore(pending); });
}
// after the layout has reopened its tabs (layout.js: layout-restored) and the page has loaded (the right pane
// restores its tabs on load)
Promise.all([new Promise((r) => document.addEventListener('layout-restored', r, { once: true })),
             new Promise((r) => (document.readyState === 'complete' ? r() : addEventListener('load', r, { once: true })))])
  .then(() => requestAnimationFrame(restoreFloating));

function forget(key) {
  try {
    const all = JSON.parse(localStorage.getItem(REMEMBERED) || '{}');
    delete all[key];
    localStorage.setItem(REMEMBERED, JSON.stringify(all));
  } catch { /* storage unavailable */ }
}

// The page closes up around a floating section. Transcript and Article share a two-column
// row: with one away the other takes the whole row; with both away the row goes.
/** Lay the transcript | article area out again (a section shown, hidden, floated or docked). */
export function relayout() { syncWorkspace(); }

function syncWorkspace() {
  document.querySelectorAll('.workspace').forEach((ws) => {
    const docked = [...ws.children].filter((c) => !c.classList.contains('undock-placeholder') && !windows.has(c) && !c.hidden);
    ws.classList.toggle('single', docked.length === 1);
    ws.classList.toggle('empty', docked.length === 0);
  });
  document.dispatchEvent(new Event('ui-sections-changed'));
}

export function isFloating(section) { return windows.has(section); }
/** Where a floating section belongs: the marker left in its place, for what is inside its window (focus.js). */
export function homeOf(node) {
  for (const [section, w] of windows) if (section.contains(node) || w.panel.contains(node)) return w.placeholder;
  return null;
}

export function dock(section) {
  const w = windows.get(section);
  if (w) { w.panel.dockBack = true; w.panel.close(); }   // docked, not closed; onclosed moves the section back
}

/** A Cortex floating window holding `element`; onClosed(docked) runs when it is closed: docked is
 *  true when its reattach button (or dockView) closed it, false for its close button. */
function openWindow({ key, title, width, height, element, onClosed, closeTitle = 'Close' }) {
  const at = held(key);
  // never larger than the page, and a cascade that keeps every new window on screen
  const w = Math.min(at ? at.width : width, innerWidth - 40);
  const h = Math.min(at ? at.height : height, innerHeight - 80);
  const step = 30 * ((windows.size + views.size) % 6);
  const off = Math.max(0, Math.min(step, (innerHeight - h) / 2 - 20, (innerWidth - w) / 2 - 20));
  const panel = jsPanel.create({
    headerTitle: title,
    theme: 'none',
    borderRadius: '8px',
    boxShadow: 3,
    panelSize: { width: w, height: h },
    position: at ? { my: 'left-top', at: 'left-top', offsetX: Math.min(at.left, innerWidth - w), offsetY: Math.min(at.top, innerHeight - h) }
                 : { my: 'center', at: 'center', offsetX: off, offsetY: off },
    // full opacity while dragged (jsPanel fades it by default), as jarbas's panel
    dragit: { opacity: 1, stop: () => remember(key, panel) },
    resizeit: { minWidth: 320, minHeight: 200, stop: () => remember(key, panel) },
    headerControls: { minimize: 'remove', smallify: 'remove', normalize: 'remove', maximize: 'remove' },
    onclosed: (p) => {
      if (!leaving) setFloating(floatingKeys().filter((k) => k !== key));
      onClosed(!!(p && p.dockBack));
      return true;
    },
    callback: (p) => {
      p.classList.add('cortex-window');
      p.dataset.windowKey = key;
      p.content.style.cssText = 'padding:0;overflow:hidden;display:flex;flex-direction:column;height:100%;';
      p.content.append(element);
      const close = p.querySelector('.jsPanel-btn-close');
      if (close) {
        close.title = closeTitle;
        // the reattach control beside it: docks it back (close closes)
        const back = Object.assign(document.createElement('button'), { type: 'button', className: 'dock-back-btn',
                                                                        title: 'Reattach into the page', innerHTML: ATTACH_ICON });
        back.addEventListener('click', () => { p.dockBack = true; p.close(); });
        close.before(back);
      }
    },
  });
  if (!floatingKeys().includes(key)) setFloating([...floatingKeys(), key]);
  if (!at) remember(key, panel);                      // its first place is its place (a reload puts it back there)
  return panel;
}

/** Float a section; closing its window docks it back, and then - when its close button (not the
 *  reattach button) closed it - onClose() hides it (the View menu shows it again). */
export function undock(section, { key, title, width = 720, height = 480, onClose = null }) {
  if (windows.has(section)) { windows.get(section).panel.front(); return; }
  section.hidden = false;
  // an invisible marker where the section was, so it docks back to the same place;
  // it takes no room: the rest of the page uses the space (the window's close docks it back)
  const placeholder = document.createElement('div');
  placeholder.className = 'undock-placeholder';
  placeholder.hidden = true;
  section.before(placeholder);
  section.classList.add('floating');
  const panel = openWindow({ key, title, width, height, element: section, closeTitle: onClose ? 'Close' : 'Dock back into the page',
                            onClosed: (docked) => {
    placeholder.replaceWith(section);                 // back where it was, in any case
    section.classList.remove('floating');
    windows.delete(section);
    if (!docked && onClose) onClose();                // the close button: hidden (the View menu shows it)
    syncWorkspace();
  } });
  windows.set(section, { panel, placeholder, key });
  syncWorkspace();
}

// ── tab views ────────────────────────────────────────────────────────
const views = new Map();                   // view key -> the window holding it

/** Float a tab's view in its own window. The owner has already taken it out of its tabs;
 *  `onDock(element, docked)` puts it back when the window is closed: docked (the reattach button)
 *  -> back into its tabs, shown; else (the close button) -> the tab is closed. */
export function floatView(key, element, { title, width = 520, height = 620, onDock }) {
  if (views.has(key)) { views.get(key).front(); return views.get(key); }
  element.classList.add('floating-view');
  element.hidden = false;
  element.style.display = '';
  const panel = openWindow({ key: `view:${key}`, title, width, height, element, onClosed: (docked) => {
    views.delete(key);
    element.classList.remove('floating-view');
    onDock(element, docked);
    document.dispatchEvent(new Event('ui-sections-changed'));
  } });
  views.set(key, panel);
  document.dispatchEvent(new Event('ui-sections-changed'));
  return panel;
}
export function isViewFloating(key) { return views.has(key); }
export function frontView(key) { views.get(key)?.front(); }
export function dockView(key) { const p = views.get(key); if (p) { p.dockBack = true; p.close(); } }

// A section gets its ↗ button from its markup (button.undock-btn inside it).
export function makeUndockable(section, options) {
  const btn = section.querySelector('.undock-btn');
  if (btn) { btn.innerHTML = DETACH_ICON; btn.addEventListener('click', () => undock(section, options)); }
  // Undock All: this section too, when it is on screen
  onUndockAll(() => (!isFloating(section) && section.getClientRects().length ? () => undock(section, options) : null));
  // floating before a reload: again, while the Recording tab it belongs to is shown
  onRestoreFloating(options.key, (rest) => {
    if (rest || !section.closest('#view-recording') || document.getElementById('view-recording').hidden) return false;
    undock(section, options);
    return true;
  });
}

// ── View > Undock All / Dock All ─────────────────────────────────────
// Undock All floats what is on screen: each pane registers what it shows (sidebar.js, right-panel.js,
// main-tabs.js; the sections above). Two steps: every hook first looks (and returns the action that
// floats what it shows, or null), then the actions run - floating one thing changes what is on screen
// (floating the middle pane's tab brings another to the front), which must not add to the set.
const floaters = [];
/** fn() -> (() => void) | null: what to float, judged on what is on screen now. */
export function onUndockAll(fn) { floaters.push(fn); }
export function undockAll() {
  const actions = [];
  for (const f of floaters) {
    try { const a = f(); if (a) actions.push(a); } catch (e) { console.error('undock all', e); }
  }
  const before = new Set(document.querySelectorAll('.jsPanel'));
  for (const a of actions) {
    try { a(); } catch (e) { console.error('undock all', e); }
  }
  cascade([...document.querySelectorAll('.jsPanel')].filter((p) => !before.has(p)));
}

// The windows Undock All opened, stepped from the work area's top-left so every title bar shows (their
// own default places centre them, and big ones - the Timeline's 980 x 700 - covered the rest). Each new
// place is the window's home for window-fit.js (a synthetic drag stop).
const CASCADE_STEP = 34;
function cascade(panels) {
  const bar = document.querySelector('#app > header');
  const status = document.getElementById('status-bar');
  const top0 = (bar ? bar.getBoundingClientRect().bottom : 0) + 12;
  const bottom = status ? status.getBoundingClientRect().top : innerHeight;
  const left0 = 64;
  panels.forEach((p, i) => {
    const r = p.getBoundingClientRect();
    const left = Math.max(4, Math.min(left0 + i * CASCADE_STEP, innerWidth - r.width - 4));
    const top = Math.max(top0, Math.min(top0 + i * CASCADE_STEP, bottom - r.height - 4));
    const cs = getComputedStyle(p);
    p.style.left = `${Math.round(parseFloat(cs.left) + (left - r.left))}px`;
    p.style.top = `${Math.round(parseFloat(cs.top) + (top - r.top))}px`;
    document.dispatchEvent(new CustomEvent('jspaneldragstop', { detail: p.id }));
    if (p.dataset.windowKey) remember(p.dataset.windowKey, p);   // its place now, for a reload
  });
}
export function dockAll() {
  // a reset too: every window docked forgets its place, so undocked again it opens where it first did
  const keys = [...[...windows.values()].map((w) => w.key), ...[...views.keys()].map((k) => `view:${k}`)];
  for (const section of [...windows.keys()]) dock(section);
  for (const key of [...views.keys()]) dockView(key);
  keys.forEach(forget);
  setFloating([]);
  pending = [];
}
/** Is any window floating (Dock All has something to do)? */
export function anyFloating() { return windows.size + views.size > 0; }
