// The top menu: noted's MenuBar (verbatim, in MenuBar.js), entries in menu.json, as Cortex does
// (static/js/shell/menu-commands.js). Cortex's menu-commands.js is mostly its own commands, bound to its recording view;
// this keeps its generic part - the drawer on tablet and phone, the toast, the context refresh - and lets feature
// modules register their commands through window.menus.
import { MenuBar } from './MenuBar.js';
import { undockAll, dockAll, anyFloating } from './undock.js';

const menuBar = new MenuBar('#menubar');

// Tablet and phone (layout.css, < 1280px): the menus are in a drawer behind the top bar's menu button (Cortex's code)
const menuToggle = document.getElementById('menu-toggle');
const topBar = menuToggle.closest('header');
function setMenuDrawer(open) {
  topBar.classList.toggle('menus-open', open);
  menuToggle.setAttribute('aria-expanded', String(open));
  if (!open) menuBar.closeAll();
}
menuToggle.addEventListener('click', (e) => { e.stopPropagation(); setMenuDrawer(!topBar.classList.contains('menus-open')); });
document.getElementById('menubar').addEventListener('click', (e) => {
  const item = e.target.closest('.menu-item');
  if (item && !item.classList.contains('has-sub') && !item.classList.contains('disabled')) setMenuDrawer(false);
}, true);
document.addEventListener('click', (e) => { if (topBar.classList.contains('menus-open') && !e.target.closest('#menubar')) setMenuDrawer(false); });
document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && topBar.classList.contains('menus-open')) setMenuDrawer(false); });
window.matchMedia('(min-width: 1280px)').addEventListener('change', (m) => { if (m.matches) setMenuDrawer(false); });
await menuBar.load('static/menu.json');

// ── short notices: the Banco CTT toast (Cortex's toast helper) ───────
const toastEl = document.getElementById('toast');
let toastTimer = null;
export function toast(text) {
  toastEl.textContent = text;
  toastEl.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { toastEl.hidden = true; }, 2600);
}

// ── context: what is enabled, re-read when the page changes ─────────
const contexts = new Map([['anyFloating', () => anyFloating()]]);
function syncContext() {
  let changed = false;
  for (const [key, fn] of contexts) {
    const v = !!fn();
    if (menuBar.getContext(key) !== v) { menuBar.setContext(key, v); changed = true; }
  }
  if (changed) menuBar.refresh();
}
document.addEventListener('ui-sections-changed', syncContext);
setInterval(syncContext, 500);

menuBar.registerCommand('view.undockAll', () => undockAll());
menuBar.registerCommand('view.dockAll', () => dockAll());

/** Feature modules: window.menus.command(id, handler), window.menus.context(key, fn), window.menus.toast(text). */
window.menus = {
  command(id, handler) { menuBar.registerCommand(id, handler); },
  context(key, fn) { contexts.set(key, fn); syncContext(); },
  toast,
};
syncContext();
document.dispatchEvent(new Event('menus-ready'));
