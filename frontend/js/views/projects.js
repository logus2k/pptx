// The side panel's Projects view (spec PJ-1, PJ-3): the person's projects, newest change first, and "New project".
// A project opens its home in the middle pane (route projects/<id>).
import { api } from '../core/api.js';
import { html, setHtml } from '../core/html.js';

let listEl = null;
let onOpen = () => {};
let current = null;

function when(iso) {
  try { return new Date(iso).toLocaleDateString(window.uiLanguage() === 'pt' ? 'pt-PT' : 'en-GB', { day: 'numeric', month: 'short', year: 'numeric' }); }
  catch { return ''; }
}

export async function refreshProjects() {
  if (!listEl) return [];
  let projects = [];
  try {
    projects = (await api('projects')).projects;
  } catch (e) {
    setHtml(listEl, html`<div class="banner error"><div><b>The projects could not be loaded</b><small class="user-text">${e.message}</small></div></div>`);
    return [];
  }
  if (!projects.length) {
    setHtml(listEl, html`<p class="muted">No projects yet. Create one to start.</p>`);
    return projects;
  }
  // a choice of the current project: listbox and options (a list's items cannot be buttons: axe, WCAG 1.3.1)
  setHtml(listEl, html`<ul class="list" role="listbox" aria-label="Projects">${projects.map((p) => html`
    <li class="clickable${p.id === current ? ' selected' : ''}" data-id="${p.id}" tabindex="0" role="option" aria-selected="${p.id === current ? 'true' : 'false'}">
      <div class="list-text"><div class="list-title user-text">${p.name}</div>
      <div class="list-caption notranslate">${when(p.updated_at)}</div></div>
    </li>`)}</ul>`);
  for (const li of listEl.querySelectorAll('li[data-id]')) {
    const open = () => onOpen(li.dataset.id);
    li.addEventListener('click', open);
    li.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); open(); } });
  }
  return projects;
}

export function markCurrent(pid) {
  current = pid;
  for (const li of listEl?.querySelectorAll('li[data-id]') || []) {
    li.classList.toggle('selected', li.dataset.id === pid);
    li.setAttribute('aria-selected', li.dataset.id === pid ? 'true' : 'false');
  }
}

export async function newProject() {
  const values = await modalForm({
    title: 'New project', confirmText: 'Create',
    fields: [{ name: 'name', label: 'Name' }, { name: 'description', label: 'Description (optional)' }],
    validate: (v) => (v.name ? null : 'Give the project a name.'),
  });
  if (!values) return null;
  const project = await api('projects', { method: 'POST', json: { name: values.name, description: values.description } });
  await refreshProjects();
  onOpen(project.id);
  return project;
}

// a project's archive (spec PJ-14), exported from its page, imported here as a new project of the person's
export async function importProject() {
  const file = await new Promise((resolve) => {
    const input = Object.assign(document.createElement('input'), { type: 'file', accept: '.zip,application/zip' });
    input.addEventListener('change', () => resolve(input.files[0] || null));
    input.click();
  });
  if (!file) return null;
  const form = new FormData();
  form.append('file', file);
  const project = await api('projects/import', { method: 'POST', form });
  await refreshProjects();
  onOpen(project.id);
  return project;
}

export function buildProjectsView(element, { open }) {
  onOpen = open;
  setHtml(element, html`
    <div class="stack" style="max-width: none; margin-bottom: var(--space-4)">
      <button type="button" class="primary" data-action="new">New project</button>
      <button type="button" class="secondary" data-action="import">Import a project</button>
    </div>
    <div class="projects-list"></div>`);
  listEl = element.querySelector('.projects-list');
  element.querySelector('[data-action="new"]').addEventListener('click', () => newProject().catch((e) => modalAlert(e.message, { title: 'New project' })));
  element.querySelector('[data-action="import"]').addEventListener('click', () => importProject().catch((e) => modalAlert(e.message, { title: 'Import a project' })));
  return refreshProjects();
}
