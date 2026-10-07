// The side menu and the side panel, as in Cortex (static/js/shell/sidebar.js): noted's SidebarPanel (verbatim, in
// SidebarPanel.js) and the Banco CTT side menu (DESIGN.md, Layout: the wordmark and the product name, then the views
// under section titles; 200px on desktop, collapsible to a 72px rail; the rail on tablet, expanding as an overlay; the
// bottom bar on a phone). Cortex's sidebar.js cannot be copied as it is: half of it is its recording views, bound to
// Cortex's app.js. This keeps its generic half - the same markup and classes, so the copied CSS applies - and this
// app's own views. Views register through window.sideMenu (below), so feature modules add theirs.
import { SidebarPanel } from './SidebarPanel.js';
import { floatView, isViewFloating, frontView, DETACH_ICON, onUndockAll, onRestoreFloating } from './undock.js';
import { describe, focusOn, pane } from './focus.js';

// one outline set, 24px, in currentColor (DESIGN.md, Components > Icons)
const icon = (inner) => `<svg class="menu-icon" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${inner}</svg>`;
export const ICONS = {
  projects: icon('<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>'),
  decks: icon('<rect x="3" y="4" width="18" height="13" rx="2"/><path d="M8 21h8M12 17v4"/>'),
  assistant: icon('<rect x="4" y="7" width="16" height="12" rx="3"/><path d="M12 3v4M9 12h.01M15 12h.01M9 16h6"/>'),
  'admin-templates': icon('<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M3 9h18M9 9v11"/>'),
  'admin-usage': icon('<path d="M4 20V10M10 20V4M16 20v-7M22 20H2"/>'),
  'admin-audit': icon('<path d="M9 4h10v16H5V8z"/><path d="M9 4v4H5M9 12h6M9 16h6"/>'),
};

// ── the side panel (noted's SidebarPanel, verbatim) ──────────────────
const sidebar = new SidebarPanel({ onViewChange: () => syncIcons() });
const registerView = sidebar.registerView.bind(sidebar);
sidebar.registerView = (key, v) => { registerView(key, v); describe(v.element, () => ({ name: v.title || v.tabLabel })); };
const showView = sidebar.show.bind(sidebar);
sidebar.show = (key) => { showView(key); focusOn(sidebar._views[key]?.element, { activated: true }); };
pane(sidebar._panel, () => sidebar._views[sidebar.activeView]?.element || null);

// any view can float in its own window (↗ in the title bar), as in Cortex
const undockBtn = Object.assign(document.createElement('button'), { type: 'button', className: 'panel-undock-btn',
                                                                  innerHTML: DETACH_ICON, title: 'Detach into a floating window' });
undockBtn.addEventListener('click', () => { if (sidebar.activeView) floatSidebarView(sidebar.activeView); });
onUndockAll(() => { const key = sidebar.activeView; return key && sidebar._contentEl.getClientRects().length ? () => floatSidebarView(key) : null; });
sidebar._titleBar.insertBefore(undockBtn, sidebar._closeBtn);

function floatSidebarView(key) {
  const v = sidebar._views[key];
  if (!v) return;
  sidebar.close(key);
  v._tab.style.display = 'none';
  focusOn(v.element, { activated: true });
  floatView(`left:${key}`, v.element, {
    title: v.title, width: 460, height: 640,
    onDock: (el, docked) => {
      sidebar._contentEl.appendChild(el);
      el.style.display = 'none';
      v._tab.style.display = '';
      if (docked) sidebar.show(key);
      syncIcons();
    },
  });
  v.onActivate?.();
  syncIcons();
}
onRestoreFloating('view:left:', (key) => { if (!sidebar._views[key]) return false; floatSidebarView(key); return true; });
const viewShown = (key) => sidebar.activeView === key || isViewFloating(`left:${key}`);

// ── the side menu ────────────────────────────────────────────────────
const bar = document.getElementById('icon-bar');
const app = document.getElementById('app');
const buttons = {};
const tablet = window.matchMedia('(min-width: 834px) and (max-width: 1279px)');
const phone = window.matchMedia('(max-width: 833px)');

function menuButton(e) {
  const b = document.createElement('button');
  b.type = 'button';
  b.className = 'icon-bar-btn';
  b.innerHTML = e.icon;
  b.append(Object.assign(document.createElement('span'), { className: 'icon-bar-label', textContent: e.label }));
  if (e.badge) b.append(Object.assign(document.createElement('span'), { className: 'menu-badge', hidden: true }));
  b.title = e.title || e.label;
  b.dataset.key = e.key;
  b.addEventListener('click', () => {
    if (e.view && isViewFloating(`left:${e.key}`)) frontView(`left:${e.key}`);
    else if (e.view) sidebar.toggle(e.key);
    else e.action?.(b);
    app.classList.remove('menu-expanded');                // the tablet's overlay menu closes on a choice
    syncIcons();
    document.dispatchEvent(new Event('ui-sections-changed'));
  });
  buttons[e.key] = b;
  return b;
}

const logo = Object.assign(document.createElement('div'), { className: 'menu-logo' });
logo.innerHTML = '<img class="logo-light" src="static/images/bancoctt-logo.svg" alt="Banco CTT" width="83" height="18">'
  + '<img class="logo-dark" src="static/images/bancoctt-logo-dark.svg" alt="Banco CTT" width="83" height="18">'
  + '<span class="product notranslate">Slides</span>';
// desktop: collapsed to the rail or not, remembered; tablet: the rail is the menu, the button opens it over the page
const COLLAPSED = 'slides.menuCollapsed';
const collapse = Object.assign(document.createElement('button'), { type: 'button', className: 'menu-collapse' });
function paintCollapse() {
  const open = tablet.matches ? app.classList.contains('menu-expanded') : !app.classList.contains('menu-collapsed');
  collapse.title = open ? 'Collapse the menu' : 'Expand the menu';
  collapse.setAttribute('aria-label', collapse.title);
  collapse.setAttribute('aria-expanded', String(open));
}
collapse.addEventListener('click', (ev) => {
  ev.stopPropagation();
  if (tablet.matches) app.classList.toggle('menu-expanded');
  else {
    const collapsed = app.classList.toggle('menu-collapsed');
    try { localStorage.setItem(COLLAPSED, collapsed ? '1' : '0'); } catch { /* not remembered */ }
  }
  paintCollapse();
});
try { app.classList.toggle('menu-collapsed', localStorage.getItem(COLLAPSED) === '1'); } catch { /* expanded */ }
document.addEventListener('click', (ev) => {
  if (app.classList.contains('menu-expanded') && !bar.contains(ev.target)) { app.classList.remove('menu-expanded'); paintCollapse(); }
});
document.addEventListener('keydown', (ev) => {
  if (ev.key === 'Escape' && app.classList.contains('menu-expanded')) { app.classList.remove('menu-expanded'); paintCollapse(); }
});
tablet.addEventListener('change', () => { app.classList.remove('menu-expanded'); paintCollapse(); });
paintCollapse();

bar.append(logo, collapse);
const top = Object.assign(document.createElement('div'), { className: 'icon-bar-group' });
bar.append(top);
bar.append(Object.assign(document.createElement('div'), { className: 'icon-bar-spacer' }));
const bottom = Object.assign(document.createElement('div'), { className: 'icon-bar-group icon-bar-bottom' });
bar.append(bottom);
const sectionsEl = {};

function section(title) {
  if (!sectionsEl[title]) {
    const head = Object.assign(document.createElement('div'), { className: 'menu-section', textContent: title });
    const group = document.createElement('div');
    group.style.display = 'contents';
    top.append(head, group);
    sectionsEl[title] = group;
  }
  return sectionsEl[title];
}

// on a phone the side panel is the whole screen: a view opened from it in the middle pane makes it step aside
document.addEventListener('main-tab-activated', () => { if (phone.matches && sidebar.visible) { sidebar.hide(); syncIcons(); } });

function syncIcons() {
  for (const [key, b] of Object.entries(buttons)) {
    if (sidebar._views[key]) b.classList.toggle('icon-bar-btn-active', viewShown(key));
  }
}

function makeView(className = '') {
  const el = document.createElement('div');
  el.className = `sb-view ${className}`.trim();
  return el;
}

/** The side menu's API for feature modules.
 *  addView(key, {section, label, title, icon, element, onActivate}) - a side-panel view with its menu item;
 *  addAction(key, {section, label, title, icon, action, bottom}) - a menu item that does something;
 *  show(key), hide(), toggle(key), shown(key). */
window.sideMenu = {
  addView(key, { section: sec, label, title, icon: ic, element, onActivate }) {
    const el = element || makeView();
    sidebar.registerView(key, { tabLabel: label, title: title || label, element: el, onActivate });
    section(sec).append(menuButton({ key, label, title, icon: ic, view: true }));
    syncIcons();
    return el;
  },
  addAction(key, { section: sec, label, title, icon: ic, action, bottom: atBottom = false }) {
    const b = menuButton({ key, label, title, icon: ic, action });
    (atBottom ? bottom : section(sec)).append(b);
    return b;
  },
  show(key) { if (!viewShown(key)) sidebar.show(key); syncIcons(); },
  /** Hide the panel. SidebarPanel keeps a closed panel's width as an empty margin so the content does not move;
   *  `reclaim` gives that width back to the content (the editor needs it). */
  hide({ reclaim = false } = {}) {
    sidebar.hide();
    if (reclaim) { sidebar._resizer.style.marginLeft = '0px'; sidebar._savedMargin = null; }
    syncIcons();
  },
  toggle(key) { sidebar.toggle(key); syncIcons(); },
  shown: viewShown,
};
document.dispatchEvent(new Event('side-menu-ready'));
