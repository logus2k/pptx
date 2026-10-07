// Slides: copied verbatim from Cortex (static/js/shell/focus.js).
// The tab with the focus: the one last clicked, typed in or brought forward - docked in the left, the middle or the
// right pane, or floating in its own window (any tab can). The status bar names it and shows its details
// (statusbar.js). A tab that goes (closed, or hidden behind another) hands the focus back to the one that had it
// before and is still on screen.
//
// Each tab's owner describes its view: describe(element, () => ({ name, literal, details })) - sidebar.js,
// right-panel.js, main-tabs.js and what opens a tab (kb-ui.js for a document). An Assistant reports its last answer's
// token counts on its view: element.dispatchEvent(new CustomEvent('assistant-usage', { bubbles: true, detail })).
import { homeOf } from './undock.js';

const describers = new WeakMap();        // view element -> () => description
const usage = new WeakMap();             // an Assistant's view element -> its last answer's { in, out, tps }
const panes = [];                        // { container, front: () => the view element it shows }
let order = [];                          // the views that had the focus, the most recent first
let activatedAt = -1;                    // when a tab was last brought forward by the page itself

/** This view can hold the focus; fn() -> { name, literal (a name its user wrote: never translated), details:
 *  [{ text, title, literal }] } as it is NOW (called while it has the focus). */
export function describe(element, fn) {
  describers.set(element, fn);
  element.setAttribute('data-focus-view', '');
}

/** A pane of tabs: a click on its own bars (not inside a view) focuses the view it shows. */
export function pane(container, front) { panes.push({ container, front }); }

/** The focus moves to this view. activated: the page brought it forward (a tab clicked in a strip, a document
 *  opened from a citation): the click that caused it does not then pull the focus back to where it happened. */
export function focusOn(element, { activated = false } = {}) {
  if (!element || !describers.has(element)) return;
  if (activated) activatedAt = performance.now();
  if (order[0] === element) return;
  order = [element, ...order.filter((e) => e !== element && e.isConnected)];
  document.dispatchEvent(new Event('focus-view-changed'));
}

// on screen: laid out, or - the Recording tab behind another tab - with one of its sections floating
const onScreen = (el) => el.isConnected && (el.getClientRects().length > 0 || !!el.querySelector('.undock-placeholder'));

/** The view with the focus (the most recent one still on screen), or null. */
export function focused() { return order.find(onScreen) || null; }

// ── the Outline panel: the table of contents of the document with the focus ──
// A view that shows a document gives its contents: outline(element, fn), fn() -> (a promise of) { name, items:
// [{ text, level (1-4; 0 a group heading, not a link), go(), current, literal (the document's
// words: never translated), page (a manual's page), at (where it starts: "p. 12") }], empty (said when there are no
// items) }. The panel shows the contents of the most recent such view still on screen: the focus moving to a view
// that is no document (an Assistant, the panel itself) leaves the document's contents there.
const outlines = new WeakMap();          // view element -> () => contents
export function outline(element, fn) { outlines.set(element, fn); }
/** The view whose contents the Outline panel shows, or null. */
export function outlineSource() { return order.find((e) => outlines.has(e) && onScreen(e)) || null; }
export function outlineOf(element) { return element ? outlines.get(element) || null : null; }
/** A document's contents changed (it finished rendering, an article grew a heading): the panel reads them again. */
export function outlineChanged(element) {
  document.dispatchEvent(new CustomEvent('outline-changed', { detail: { element } }));
}

/** Headings of a rendered document, as outline items: `root()` is read again on a click, so a document laid out
 *  anew meanwhile (a Word document re-paginated) still scrolls to the right heading. */
export function headingsOutline(root, selector = 'h1, h2, h3, h4') {
  const el = root();
  if (!el) return [];
  return [...el.querySelectorAll(selector)].map((h, i) => ({
    text: h.textContent.trim(), level: Number(h.tagName[1]), literal: true,
    go: () => root()?.querySelectorAll(selector)[i]?.scrollIntoView({ behavior: 'smooth', block: 'start' }),
  })).filter((x) => x.text);
}

/** Its description for the status bar, or null. */
export function description() {
  const el = focused();
  if (!el) return null;
  try { return { ...describers.get(el)(), usage: usage.get(el) || null }; } catch (e) { console.error('focus', e); return null; }
}

/** A size as the status bar writes it: 812 B, 45 KB, 1.2 MB, 3.4 GB. */
export function bytes(n) {
  if (!(n >= 0)) return '';
  if (n < 1000) return `${n} B`;
  const units = ['KB', 'MB', 'GB', 'TB'];
  let v = n / 1000, i = 0;
  while (v >= 1000 && i < units.length - 1) { v /= 1000; i += 1; }
  return `${v >= 100 || i === 0 ? Math.round(v) : v.toFixed(1)} ${units[i]}`;
}

function viewOf(target) {
  if (!(target instanceof Element)) return null;
  const inView = target.closest('[data-focus-view]');
  if (inView) return inView;
  const home = homeOf(target);                           // a floating section (Transcript, Article...): its tab
  if (home) return home.closest('[data-focus-view]');
  const win = target.closest('.jsPanel');                // a floating tab's own title bar
  if (win) return win.querySelector('[data-focus-view]');
  const p = panes.find((x) => x.container.contains(target));
  return p ? p.front() : null;
}

// click, not pointerdown: by then a clicked tab has come forward (its owner called focusOn), and that wins
document.addEventListener('click', (e) => {
  if (activatedAt > e.timeStamp) return;
  focusOn(viewOf(e.target));
});
document.addEventListener('focusin', (e) => focusOn(viewOf(e.target)));
document.addEventListener('assistant-usage', (e) => {
  const el = e.target instanceof Element && e.target.closest('[data-focus-view]');
  if (el && e.detail) { usage.set(el, e.detail); document.dispatchEvent(new Event('focus-view-changed')); }
});

window.cortexFocus = { describe, focusOn, focused, description, outlineSource };   // app.js and the tests
