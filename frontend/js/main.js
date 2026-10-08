// The app: its views in the shell (Cortex's, in shell/) and the router. Routes use the History API under the page's
// <base href> (technical design section 3): "" the home, "projects/<pid>" a project's home,
// "projects/<pid>/decks/<did>" a deck in the editor. The server answers index.html for every such path.
import { openTab, activate, closeTab, isOpen, setTitle } from './shell/main-tabs.js';
import { ICONS } from './shell/side-menu.js';
import { buildHome } from './views/home.js';
import { buildDesignSystem } from './views/design-system.js';
import { buildProjectsView, markCurrent, newProject, refreshProjects } from './views/projects.js';
import { buildProject } from './views/project.js';
import { buildDeck } from './views/deck.js';
import { buildGenerate } from './views/generate.js';
import { buildAdminTemplates, buildUsage, buildAuditLog } from './views/admin.js';
import * as store from './core/store.js';
import { showAssistant, newConversation } from './assistant/assistant.js';

const BASE = new URL(document.baseURI).pathname;          // "/slides/" behind the proxy, "/" directly

/** The route of the page, relative to the base: "" for the home, "projects/abc" ... */
export function route() {
  let path = location.pathname.startsWith(BASE) ? location.pathname.slice(BASE.length) : '';
  while (path.endsWith('/')) path = path.slice(0, -1);
  return path;
}

/** Go to a route (relative to the base) without reloading. */
export function navigate(to) {
  const url = BASE + to;
  if (url !== location.pathname) history.pushState({}, '', url);
  render();
}

function ready(name, event) {
  return window[name] ? Promise.resolve() : new Promise((r) => document.addEventListener(event, r, { once: true }));
}

// ── the open project (the status bar's pill, the side list's selection) ──
let currentProject = null;
const projectViews = new Map();                             // pid -> {reload}
function setProject(p) {
  currentProject = p;

  const pill = document.getElementById('sb-project');
  pill.textContent = p ? p.name : '—';
  markCurrent(p?.id || null);
}

function openHome() {
  openTab('home', { title: 'Home', build: (view) => buildHome(view) });
  activate('home');
}

function openDesignSystem() {
  openTab('design-system', { title: 'Design system', build: (view) => buildDesignSystem(view) });
  activate('design-system');
}

function openProject(pid) {
  const key = `project:${pid}`;
  if (store.get('project') !== pid) {
    store.set('conversation', null);
    store.set('proposal', null);
    store.set('project', pid);
    // the assistant works in the open project: on a desktop its pane opens beside the content
    if (window.matchMedia('(min-width: 1280px)').matches) showAssistant();
  }
  const record = openTab(key, {
    title: window.cortexT('Project'),       // until its name arrives; the name is never translated
    named: true,
    build: (view) => {
      projectViews.set(pid, buildProject(view, {
        pid,
        openDeck: (did) => navigate(`projects/${pid}/decks/${did}`),
        generate: () => navigate(`projects/${pid}/generate`),
        onChanged: (p) => { setTitle(key, p.name); setProject(p); refreshProjects(); },
        onDeleted: () => { closeTab(key); projectViews.delete(pid); setProject(null); refreshProjects(); navigate(''); },
      }));
    },
    onClose: () => projectViews.delete(pid),
  });
  activate(key);
  return record;
}

const deckProject = new Map();                              // did -> pid, for the tab's route
const deckViews = new Map();                                // did -> the editor (its selection, when its tab comes forward)
function openDeck(pid, did) {
  const key = `deck:${did}`;
  deckProject.set(did, pid);
  // the editor needs the width: the side panel steps aside (its menu item brings it back)
  if (window.matchMedia('(min-width: 834px)').matches) window.sideMenu.hide({ reclaim: true });
  openTab(key, {
    title: window.cortexT('Deck'),
    named: true,
    build: (view) => deckViews.set(did, buildDeck(view, { pid, did, onTitle: (t) => setTitle(key, t), onChanged: () => projectViews.get(pid)?.reload() })),
    onClose: () => { deckViews.get(did)?.release?.(); deckProject.delete(did); deckViews.delete(did); if (store.get('deck') === did) { store.set('deck', null); store.set('selection', null); } },
  });
  activate(key);
}

// administration (spec AD-4..AD-6): a tab each, in the side menu for administrators only (as Cortex's admin areas)
const ADMIN = {
  templates: { title: 'Templates', build: buildAdminTemplates },
  usage: { title: 'Usage', build: buildUsage },
  audit: { title: 'Audit log', build: buildAuditLog },
};
function openAdmin(area) {
  const a = ADMIN[area];
  if (!a) { openHome(); return; }
  openTab(`admin:${area}`, { title: a.title, build: (view) => a.build(view) });
  activate(`admin:${area}`);
}

// a deck generated from a source (spec NL-12): the form, then its outline; the assistant's plan card opens the outline
const generateViews = new Map();
function openGenerate(pid, gid = null) {
  if (!isOpen(`project:${pid}`)) openProject(pid);
  const key = gid ? `generate:${gid}` : `generate:new:${pid}`;
  openTab(key, {
    title: window.cortexT('Generate a deck'),
    build: (view) => generateViews.set(key, buildGenerate(view, {
      pid, gid,
      openDeck: (did) => { projectViews.get(pid)?.reload(); navigate(`projects/${pid}/decks/${did}`); },
      onStarted: (id) => history.replaceState({}, '', `${BASE}projects/${pid}/generate/${id}`),
    })),
    onClose: () => { generateViews.get(key)?.close(); generateViews.delete(key); },
  });
  activate(key);
}
document.addEventListener('sa:open-generation', (e) => { const pid = store.get('project'); if (pid) navigate(`projects/${pid}/generate/${e.detail.id}`); });

function render() {
  const parts = route().split('/');
  if (parts[0] === 'projects' && parts[1] && parts[2] === 'generate') { openGenerate(parts[1], parts[3] || null); return; }
  if (parts[0] === 'admin') { openAdmin(parts[1]); return; }
  if (parts[0] === 'projects' && parts[1]) {
    if (!isOpen(`project:${parts[1]}`)) openProject(parts[1]);
    if (parts[2] === 'decks' && parts[3]) openDeck(parts[1], parts[3]);
    else activate(`project:${parts[1]}`);
    return;
  }
  openHome();
}

// a tab brought forward makes its route the page's (so a reload, or a shared link, opens the same thing)
document.addEventListener('main-tab-activated', (e) => {
  const key = e.detail.key;
  let to = null;
  if (key === 'home') to = '';
  else if (key.startsWith('admin:')) to = `admin/${key.slice(6)}`;
  else if (key.startsWith('project:')) to = `projects/${key.slice(8)}`;
  else if (key.startsWith('deck:') && deckProject.has(key.slice(5))) {
    to = `projects/${deckProject.get(key.slice(5))}/decks/${key.slice(5)}`;
    deckViews.get(key.slice(5))?.focus();                   // the assistant's "this deck" and "this slide"
  }
  if (to !== null && BASE + to !== location.pathname) history.replaceState({}, '', BASE + to);
});

async function about() {
  let version = '?';
  try { version = (await (await fetch('api/health')).json()).version; } catch { /* unknown */ }
  await modalAlert(`Slides ${version}\n\nPresentations edited with an assistant, on the Banco CTT design system.`, { title: 'About' });
}

await ready('sideMenu', 'side-menu-ready');
const projectsEl = window.sideMenu.addView('projects', { section: 'Workspace', label: 'Projects', title: 'Projects', icon: ICONS.projects });
buildProjectsView(projectsEl, { open: (pid) => navigate(`projects/${pid}`) });

await ready('menus', 'menus-ready');
window.menus.command('project.new', () => newProject().catch((e) => modalAlert(e.message, { title: 'New project' })));
window.menus.command('project.list', () => window.sideMenu.show('projects'));
window.menus.command('view.home', () => navigate(''));
// the Assistant menu: the pane opens beside the content on a desktop, over it on a tablet; closed, this brings it back
window.menus.context('projectOpen', () => !!store.get('project'));
window.menus.command('assistant.show', showAssistant);
window.menus.command('assistant.new', () => { showAssistant(); newConversation(); });
window.menus.command('help.designSystem', openDesignSystem);
window.menus.command('help.about', about);
window.addEventListener('popstate', render);
// "Review" in the assistant's card: the deck its changes are in; on a tablet the pane, over the editor, steps aside
document.addEventListener('sa:review', (e) => {
  const pid = store.get('project');
  if (!pid || !e.detail.deck) return;
  if (!window.matchMedia('(min-width: 1280px)').matches) window.rightPane.close('assistant');
  navigate(`projects/${pid}/decks/${e.detail.deck}`);
});
document.addEventListener('sa:project-changed', () => { const pid = store.get('project'); if (pid) projectViews.get(pid)?.reload(); });
// a deck the assistant created: the project's home lists it
document.addEventListener('sa:assistant-reply', () => { const pid = store.get('project'); if (pid) projectViews.get(pid)?.reload(); });
try {
  const me = await (await fetch('api/me')).json();
  if (me.is_admin) {
    for (const [area, label] of [['templates', 'Templates'], ['usage', 'Usage'], ['audit', 'Audit log']]) {
      window.sideMenu.addAction(`admin-${area}`, { section: 'Administration', label, icon: ICONS[`admin-${area}`], action: () => navigate(`admin/${area}`) });
    }
  }
} catch { /* not known: no administration items */ }
render();
if (!route()) window.sideMenu.show('projects');            // the home opens with the person's projects beside it
