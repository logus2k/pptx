// Administration (spec AD-4, AD-5, AD-6), for administrators only; the server refuses these routes to anyone else.
//   Templates   the organisation's templates: upload, rename, retire or bring back, make the default (AD-4)
//   Usage       per period: people, projects, assistant turns, proposals accepted and rejected, model errors (AD-5)
//   Audit log   who changed which data, and when; filtered by person, words and period; exported as CSV (AD-6).
//               Ported from Cortex's Settings > Audit log (static/js/settings/audit-log.js): the same filters, keyset
//               pages ("Show more") and CSV with the same filters; drawn with this app's page, fields and data table.
import { api } from '../core/api.js';
import { html, raw, setHtml } from '../core/html.js';

const ACCEPT = '.pptx,.potx,application/vnd.openxmlformats-officedocument.presentationml.presentation,application/vnd.openxmlformats-officedocument.presentationml.template';
const ALERT_ICON = '<svg class="banner-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 3 2 20h20zM12 10v4M12 17h.01"/></svg>';
const PAGE = 100;

const locale = () => (window.uiLanguage() === 'pt' ? 'pt-PT' : 'en-GB');
function when(iso) {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString(locale(), { day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' });
}
const nameOf = (t) => t.name?.[window.uiLanguage()] || t.name?.en || t.id;
const descriptionOf = (t) => t.description?.[window.uiLanguage()] || t.description?.en || '';

function pickFile(accept) {
  return new Promise((resolve) => {
    const input = Object.assign(document.createElement('input'), { type: 'file', accept });
    input.addEventListener('change', () => resolve(input.files[0] || null), { once: true });
    input.click();
  });
}

function refused(page, title, e) {
  setHtml(page, html`<h1>${title}</h1><div class="banner error">${raw(ALERT_ICON)}<div><b>This page could not be opened</b><small>${e.message}</small></div></div>`);
}

// ── Templates (AD-4) ────────────────────────────────────────────────
export function buildAdminTemplates(view) {
  const page = Object.assign(document.createElement('div'), { className: 'page admin-page' });
  view.append(page);
  let listing = { templates: [], default: null };

  async function load() {
    try { listing = await api('admin/templates'); } catch (e) { refused(page, 'Templates', e); return; }
    render();
  }

  function render() {
    const items = [...listing.templates].sort((a, b) => Number(a.retired) - Number(b.retired));
    setHtml(page, html`
      <h1>Templates</h1>
      <p class="lead">The organisation's templates, offered for every new deck. A retired template is no longer offered; decks made from it keep it.</p>
      <div class="row" style="margin-bottom: var(--space-4)"><button type="button" class="primary" data-action="upload">Upload a template</button></div>
      <ul class="list admin-templates">${items.map((t) => html`
        <li data-id="${t.id}"><div class="list-text">
            <div class="list-title user-text">${nameOf(t)}</div>
            ${descriptionOf(t) ? html`<div class="list-caption user-text">${descriptionOf(t)}</div>` : ''}
            <div class="list-caption">${(t.layouts || []).length} layouts</div>
            ${t.missing_fonts?.length ? html`<div class="list-caption">Fonts not on the server, replaced in previews: <span class="user-text">${t.missing_fonts.join(', ')}</span></div>` : ''}
          </div>
          <div class="row">
            ${t.default ? html`<span class="pill">Default</span>` : ''}${t.retired ? html`<span class="pill">Retired</span>` : ''}
            <button type="button" data-action="rename" data-id="${t.id}">Rename</button>
            ${t.default || t.retired ? '' : html`<button type="button" data-action="default" data-id="${t.id}">Make default</button>`}
            ${t.retired ? html`<button type="button" data-action="bring-back" data-id="${t.id}">Bring back</button>`
              : t.default ? '' : html`<button type="button" data-action="retire" data-id="${t.id}">Retire</button>`}
          </div></li>`)}</ul>`);
  }

  const failed = (title) => (e) => modalAlert(e.message, { title });
  const change = (tid, json, title) => api(`admin/templates/${tid}`, { method: 'PATCH', json }).then(load).catch(failed(title));

  async function upload() {
    const file = await pickFile(ACCEPT);
    if (!file) return;
    const base = file.name.includes('.') ? file.name.slice(0, file.name.lastIndexOf('.')) : file.name;
    const v = await modalForm({ title: 'Upload a template', confirmText: 'Upload',
      fields: [{ name: 'name', label: 'Name', value: base }, { name: 'description', label: 'Description' }],
      validate: (x) => (x.name ? null : 'Give the template a name.') });
    if (!v) return;
    const form = new FormData();
    form.append('name', v.name);
    form.append('description', v.description || '');
    form.append('file', file);
    window.menus.toast('Uploading…');
    try {
      const t = await api('admin/templates', { method: 'POST', form });
      if (t.missing_fonts?.length) {
        await modalAlert(`The template uses fonts the server does not have: ${t.missing_fonts.join(', ')}. Previews replace them with similar fonts; the downloaded file keeps them.`, { title: 'Template added' });
      } else window.menus.toast('The template was added.');
      load();
    } catch (e) { failed('Upload a template')(e); }
  }

  async function rename(tid) {
    const t = listing.templates.find((x) => x.id === tid);
    const v = await modalForm({ title: 'Rename template', confirmText: 'Save',
      fields: [{ name: 'name', label: 'Name', value: nameOf(t) }, { name: 'description', label: 'Description', value: descriptionOf(t) }],
      validate: (x) => (x.name ? null : 'Give the template a name.') });
    if (v) change(tid, { name: v.name, description: v.description || '' }, 'Rename template');
  }

  async function retire(tid) {
    if (!await modalConfirm('It will no longer be offered for new decks. Decks already made from it keep it.', { title: 'Retire template', confirmText: 'Retire', danger: true })) return;
    change(tid, { retired: true }, 'Retire template');
  }

  page.addEventListener('click', (e) => {
    const b = e.target.closest('button[data-action]');
    if (!b) return;
    const tid = b.dataset.id;
    if (b.dataset.action === 'upload') upload();
    else if (b.dataset.action === 'rename') rename(tid);
    else if (b.dataset.action === 'default') change(tid, { default: true }, 'Make default');
    else if (b.dataset.action === 'retire') retire(tid);
    else if (b.dataset.action === 'bring-back') change(tid, { retired: false }, 'Bring back');
  });
  load();
}

// ── Usage (AD-5) ────────────────────────────────────────────────────
const COLUMNS = [['people', 'People'], ['projects', 'Projects'], ['turns', 'Assistant turns'], ['accepted', 'Accepted'],
  ['rejected', 'Rejected'], ['errors', 'Model errors']];

function periodText(p, by) {
  if (by === 'month') {
    const d = new Date(`${p}-01T00:00:00Z`);
    return d.toLocaleDateString(locale(), { month: 'long', year: 'numeric', timeZone: 'UTC' });
  }
  const d = new Date(`${p}T00:00:00Z`);
  const day = d.toLocaleDateString(locale(), { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' });
  return by === 'week' ? `Week of ${day}` : day;
}

export function buildUsage(view) {
  const page = Object.assign(document.createElement('div'), { className: 'page admin-page' });
  view.append(page);
  setHtml(page, html`
    <h1>Usage</h1>
    <p class="lead">Per period, from the audit log: who used Slides, in how many projects, and how the assistant did.</p>
    <div class="row admin-filters">
      <label class="field-box"><span>Per</span><select data-field="by"><option value="day">Day</option><option value="week" selected>Week</option><option value="month">Month</option></select></label>
      <label class="field-box"><span>From</span><input type="date" data-field="since"></label>
      <label class="field-box"><span>To</span><input type="date" data-field="until"></label>
    </div>
    <div class="data-table-wrap"><table class="data-table admin-table usage-table">
      <thead><tr><th>Period</th>${COLUMNS.map(([, label]) => html`<th class="num">${label}</th>`)}</tr></thead>
      <tbody></tbody></table></div>
    <p class="muted admin-status" aria-live="polite"></p>`);
  const field = (name) => page.querySelector(`[data-field="${name}"]`);
  const body = page.querySelector('tbody');
  const status = page.querySelector('.admin-status');

  async function load() {
    const p = new URLSearchParams({ by: field('by').value });
    if (field('since').value) p.set('since', `${field('since').value}T00:00:00Z`);
    if (field('until').value) p.set('until', `${field('until').value}T23:59:59Z`);
    let d;
    try { d = await api(`usage?${p}`); } catch (e) { refused(page, 'Usage', e); return; }
    const rows = [...d.periods].reverse();                // newest first, as the audit log
    // the period in the interface's language (dates formatted for it: never looked up again)
    setHtml(body, html`${rows.map((r) => html`<tr><td><span class="cell-label">Period</span><span class="notranslate">${window.cortexT(periodText(r.period, d.by))}</span></td>${COLUMNS.map(([key, label]) => html`<td class="num"><span class="cell-label">${label}</span>${r[key]}</td>`)}</tr>`)}`);
    status.textContent = rows.length ? '' : 'Nothing recorded for this period.';
  }
  for (const name of ['by', 'since', 'until']) field(name).addEventListener('change', load);
  load();
}

// ── Audit log (AD-6) ────────────────────────────────────────────────
// which data, as text: "pid: 9c84… · did: 1f0e…" (the identifiers the server kept)
function targetText(t) {
  return Object.entries(t || {}).map(([k, v]) => `${k}: ${typeof v === 'string' ? v : JSON.stringify(v)}`).join(' · ');
}

export function buildAuditLog(view) {
  const page = Object.assign(document.createElement('div'), { className: 'page admin-page' });
  view.append(page);
  setHtml(page, html`
    <h1>Audit log</h1>
    <p class="lead">Who changed which data, and when. What was written is not recorded; reading and asking are not recorded either.</p>
    <div class="row admin-filters">
      <label class="field-box"><span>Person</span><select data-field="user"><option value="">Everyone</option></select></label>
      <label class="field-box admin-q"><span>Filter</span><input type="search" data-field="q" placeholder="An action, an id…"></label>
      <label class="field-box"><span>From</span><input type="date" data-field="since"></label>
      <label class="field-box"><span>To</span><input type="date" data-field="until"></label>
      <button type="button" class="secondary" data-action="csv">Download CSV</button>
    </div>
    <div class="data-table-wrap"><table class="data-table admin-table audit-table">
      <thead><tr><th>When</th><th>Who</th><th>What</th><th>Which data</th></tr></thead>
      <tbody></tbody></table></div>
    <p class="muted admin-status" aria-live="polite"></p>
    <button type="button" class="secondary" data-action="more" hidden>Show more</button>`);
  const field = (name) => page.querySelector(`[data-field="${name}"]`);
  const body = page.querySelector('tbody');
  const status = page.querySelector('.admin-status');
  const more = page.querySelector('[data-action="more"]');

  const params = () => {
    const p = new URLSearchParams();
    if (field('user').value) p.set('user', field('user').value);
    if (field('q').value.trim()) p.set('q', field('q').value.trim());
    if (field('since').value) p.set('since', `${field('since').value}T00:00:00Z`);
    if (field('until').value) p.set('until', `${field('until').value}T23:59:59Z`);
    return p;
  };
  let last = 0;
  let shown = 0;
  async function load(append = false) {
    const p = params();
    p.set('limit', String(PAGE));
    if (append && last) p.set('before', String(last));
    let d;
    try { d = await api(`audit?${p}`); } catch (e) {
      status.textContent = `The audit log could not be read: ${e.message}`;
      return;
    }
    if (!append) {
      body.replaceChildren();
      shown = 0;
      const select = field('user');
      const chosen = select.value;                        // the people in the log (kept as they are: addresses)
      select.replaceChildren(new Option('Everyone', ''), ...d.users.map((u) => Object.assign(new Option(u, u), { className: 'notranslate' })));
      select.value = d.users.includes(chosen) ? chosen : '';
    }
    for (const e of d.entries) {
      const row = document.createElement('tr');
      // the time, the route and the identifiers as they are; the label in the interface's language
      setHtml(row, html`<td><span class="cell-label">When</span><span class="notranslate" title="${e.at}">${when(e.at)}</span></td>
        <td><span class="cell-label">Who</span><span class="notranslate">${e.user}</span></td>
        <td><span class="cell-label">What</span><span class="notranslate" title="${e.action}">${e.label ? window.cortexT(e.label) : e.action}</span></td>
        <td class="audit-target"><span class="cell-label">Which data</span><span class="notranslate">${targetText(e.target)}</span></td>`);
      body.append(row);
      last = e.id;
    }
    shown += d.entries.length;
    more.hidden = !d.more;
    status.textContent = shown ? `${shown} ${shown === 1 ? 'entry' : 'entries'} shown${d.more ? ', more below' : ''}` : 'Nothing recorded for these filters.';
  }
  let timer = null;
  for (const name of ['user', 'since', 'until']) field(name).addEventListener('change', () => load());
  field('q').addEventListener('input', () => { clearTimeout(timer); timer = setTimeout(() => load(), 300); });
  more.addEventListener('click', () => load(true));
  // sent as an attachment: the page stays
  page.querySelector('[data-action="csv"]').addEventListener('click', () => { location.href = `api/audit.csv?${params()}`; });
  load();
}
