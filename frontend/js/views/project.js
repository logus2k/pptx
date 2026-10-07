// A project's home (route projects/<id>; spec PJ-2, PJ-3, PM-1, PM-2, PM-9): its decks (each with its first slide),
// a new deck from a template, an uploaded presentation, and the project's own templates.
import { api, slideImage } from '../core/api.js';
import { html, raw, setHtml } from '../core/html.js';

const ACCEPT = '.pptx,.potx,application/vnd.openxmlformats-officedocument.presentationml.presentation,application/vnd.openxmlformats-officedocument.presentationml.template';
const ALERT_ICON = '<svg class="banner-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 3 2 20h20zM12 10v4M12 17h.01"/></svg>';

function size(bytes) {
  return bytes >= 1048576 ? `${(bytes / 1048576).toFixed(1)} MB` : `${Math.max(1, Math.round(bytes / 1024))} KB`;
}

function when(iso) {
  try { return new Date(iso).toLocaleString(window.uiLanguage() === 'pt' ? 'pt-PT' : 'en-GB', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' }); }
  catch { return ''; }
}

function pickFile(accept) {
  return new Promise((resolve) => {
    const input = Object.assign(document.createElement('input'), { type: 'file', accept });
    input.addEventListener('change', () => resolve(input.files[0] || null), { once: true });
    input.click();
  });
}

function nameOf(t) { return t.name?.[window.uiLanguage()] || t.name?.en || t.id; }

export function buildProject(view, { pid, openDeck, onChanged, onDeleted }) {
  const page = document.createElement('div');
  page.className = 'page';
  view.append(page);
  let project = null;
  let kb = { available: false, domains: [] };   // the person's knowledge-base domains (GET kb/domains)
  let remembered = [];                           // the project's memory (spec PJ-9)
  let files = [];                                // its images and reference documents (spec PJ-11)

  async function load() {
    try {
      const [p, decks, assets, domains, memory] = await Promise.all([api(`projects/${pid}`), api(`projects/${pid}/decks`), api(`projects/${pid}/assets`),
        api('kb/domains').catch(() => ({ available: false, domains: [] })), api(`projects/${pid}/memory`)]);
      project = p;
      kb = domains;
      remembered = memory.items;
      files = assets.assets.filter((a) => a.kind !== 'template');
      render(decks.decks, assets.assets.filter((a) => a.kind === 'template'));
      onChanged?.(p);
    } catch (e) {
      setHtml(page, html`<div class="banner error">${raw(ALERT_ICON)}<div><b>This project could not be opened</b><small class="user-text">${e.message}</small></div></div>`);
    }
  }

  function render(decks, templates) {
    const canWrite = project.role !== 'viewer';           // the person's own role (the server says it)
    setHtml(page, html`
      <h1 class="user-text">${project.name}</h1>
      <p class="lead user-text">${project.description || ''}</p>
      <div class="row" style="margin-bottom: var(--space-8)">
        <button type="button" data-action="rename">Rename</button>
        ${project.role === 'owner' ? html`<button type="button" data-action="delete">Delete project</button>` : ''}
      </div>
      <section>
        <h2 class="section-title">Decks</h2>
        <div class="row" style="margin-bottom: var(--space-4)">
          <button type="button" class="primary" data-action="new-deck" ${canWrite ? '' : 'disabled'}>New deck</button>
          <button type="button" class="secondary" data-action="upload-deck" ${canWrite ? '' : 'disabled'}>Upload a presentation</button>
        </div>
        ${decks.length ? html`<div class="deck-grid">${decks.map((d) => html`
          <button type="button" class="deck-card" data-id="${d.id}">
            <span class="deck-thumb">${d.slide_count ? html`<img alt="" loading="lazy" data-deck="${d.id}" data-version="${d.current_version}">` : html`<span class="deck-empty">Empty deck</span>`}</span>
            <span class="deck-title user-text">${d.title}</span>
            <span class="deck-caption">${d.slide_count === 1 ? '1 slide' : `${d.slide_count} slides`} · ${when(d.updated_at)}</span>
          </button>`)}</div>`
        : html`<p class="muted">No decks yet: start from a template, or upload a presentation.</p>`}
      </section>
      <section>
        <h2 class="section-title">Project instructions</h2>
        <p class="muted">Rules the assistant follows in every deck and conversation of this project: audience, tone, terms to use or avoid.</p>
        <label class="field-box instructions-box"><span>Instructions</span><textarea rows="4" data-field="instructions" ${canWrite ? '' : 'disabled'}>${project.instructions}</textarea></label>
        <div class="row" style="margin-top: var(--space-2)"><button type="button" class="secondary" data-action="save-instructions" ${canWrite ? '' : 'disabled'}>Save instructions</button></div>
      </section>
      <section>
        <h2 class="section-title">Project memory</h2>
        <p class="muted">Facts and decisions the assistant keeps from your conversations and follows in this project. It says so in the chat whenever it keeps one.</p>
        ${remembered.length ? html`<ul class="list memory-list">${remembered.map((m) => html`
          <li><div class="list-text"><div class="list-title user-text">${m.text}</div>
            <div class="list-caption">${when(m.created_at)} · ${m.conversation_id ? 'from a conversation' : 'written here'}</div></div>
            <div class="row"><button type="button" data-action="edit-memory" data-id="${m.id}" ${canWrite ? '' : 'disabled'}>Edit</button>
            <button type="button" data-action="delete-memory" data-id="${m.id}" ${canWrite ? '' : 'disabled'}>Delete</button></div></li>`)}</ul>`
        : html`<p class="muted">Nothing kept yet.</p>`}
        <div class="row" style="margin-top: var(--space-2)"><button type="button" class="secondary" data-action="add-memory" ${canWrite ? '' : 'disabled'}>Add to memory</button></div>
      </section>
      <section>
        <h2 class="section-title">Images and reference documents</h2>
        <p class="muted">Images to use in any deck of the project, and documents (PDF, Word, text) the assistant can search and cite.</p>
        ${files.length ? html`<ul class="list">${files.map((a) => html`
          <li><div class="list-text"><div class="list-title user-text">${a.name}</div>
            <div class="list-caption">${a.kind === 'image' ? 'Image' : 'Document'} · ${size(a.size)}${a.kind === 'document' ? html` · ${a.passages} passages` : ''}</div></div>
            <button type="button" data-action="delete-asset" data-id="${a.id}" ${canWrite ? '' : 'disabled'}>Delete</button></li>`)}</ul>`
        : ''}
        <div class="row" style="margin-top: var(--space-2)"><button type="button" class="secondary" data-action="upload-document" ${canWrite ? '' : 'disabled'}>Add a document</button></div>
      </section>
      <section>
        <h2 class="section-title">Knowledge base</h2>
        ${kb.available ? html`<p class="muted">The assistant searches these domains of Cortex's knowledge base. None ticked: every domain you can use.</p>
          <div class="kb-domains">${kb.domains.map((d) => html`<label class="row include"><input type="checkbox" data-kb="${d.id}"
            ${(project.settings.kb_domains || []).includes(d.id) ? 'checked' : ''} ${canWrite ? '' : 'disabled'}><span class="notranslate">${d.name}</span></label>`)}</div>
          <div class="row" style="margin-top: var(--space-2)"><button type="button" class="secondary" data-action="save-kb" ${canWrite ? '' : 'disabled'}>Save domains</button></div>`
        : html`<p class="muted">The knowledge base is not available here.</p>`}
      </section>
      <section>
        <h2 class="section-title">This project's templates</h2>
        <p class="muted">Templates you upload here can be chosen for any deck of this project, beside the organisation's.</p>
        <div class="row" style="margin-bottom: var(--space-4)">
          <button type="button" class="secondary" data-action="upload-template" ${canWrite ? '' : 'disabled'}>Upload a template</button>
        </div>
        ${templates.length ? html`<ul class="list">${templates.map((t) => html`
          <li><div class="list-text"><div class="list-title user-text">${t.name}</div>
            <div class="list-caption">${(t.layouts || []).length} layouts</div>
            ${t.missing_fonts?.length ? html`<div class="list-caption">Fonts not on the server, replaced in previews: <span class="user-text">${t.missing_fonts.join(', ')}</span></div>` : ''}
            </div>
            <button type="button" data-action="delete-template" data-id="${t.id}" ${canWrite ? '' : 'disabled'}>Delete</button></li>`)}</ul>`
        : ''}
      </section>`);
    // the first slide of each deck (its image renders on first view; the address is versioned, so it is kept)
    for (const img of page.querySelectorAll('img[data-deck]')) {
      api(`projects/${pid}/decks/${img.dataset.deck}?version=${img.dataset.version}`).then((info) => {
        if (info.slides.length) img.src = slideImage(pid, img.dataset.deck, info.slides[0].id, img.dataset.version);
      }).catch(() => {});
    }
    for (const card of page.querySelectorAll('.deck-card')) card.addEventListener('click', () => openDeck(card.dataset.id));
    page.querySelector('[data-action="rename"]').addEventListener('click', rename);
    page.querySelector('[data-action="delete"]')?.addEventListener('click', remove);
    page.querySelector('[data-action="new-deck"]').addEventListener('click', newDeck);
    page.querySelector('[data-action="upload-deck"]').addEventListener('click', uploadDeck);
    page.querySelector('[data-action="upload-template"]').addEventListener('click', uploadTemplate);
    page.querySelector('[data-action="save-instructions"]').addEventListener('click', async () => {
      try {
        await api(`projects/${pid}`, { method: 'PATCH', json: { instructions: page.querySelector('[data-field="instructions"]').value } });
        window.menus.toast('The instructions were saved.');
      } catch (e) { failed('Project instructions')(e); }
    });
    for (const b of page.querySelectorAll('[data-action="delete-template"]')) b.addEventListener('click', () => deleteTemplate(b.dataset.id));
    page.querySelector('[data-action="add-memory"]').addEventListener('click', () => editMemory(null));
    for (const b of page.querySelectorAll('[data-action="edit-memory"]')) b.addEventListener('click', () => editMemory(remembered.find((m) => m.id === b.dataset.id)));
    for (const b of page.querySelectorAll('[data-action="delete-memory"]')) b.addEventListener('click', () => deleteMemory(b.dataset.id));
    page.querySelector('[data-action="upload-document"]').addEventListener('click', uploadDocument);
    for (const b of page.querySelectorAll('[data-action="delete-asset"]')) b.addEventListener('click', () => deleteAsset(b.dataset.id));
    page.querySelector('[data-action="save-kb"]')?.addEventListener('click', async () => {
      const ids = [...page.querySelectorAll('[data-kb]:checked')].map((c) => c.dataset.kb);
      try {
        project = await api(`projects/${pid}`, { method: 'PATCH', json: { settings: { kb_domains: ids } } });
        window.menus.toast('The domains were saved.');
      } catch (e) { failed('Knowledge base')(e); }
    });
  }

  const failed = (title) => (e) => modalAlert(e.message, { title });

  async function rename() {
    const v = await modalForm({ title: 'Rename project', confirmText: 'Save',
      fields: [{ name: 'name', label: 'Name', value: project.name }, { name: 'description', label: 'Description', value: project.description }],
      validate: (x) => (x.name ? null : 'Give the project a name.') });
    if (!v) return;
    await api(`projects/${pid}`, { method: 'PATCH', json: v }).catch(failed('Rename project'));
    load();
  }

  async function remove() {
    if (!await modalConfirm(`Delete the project "${project.name}" and all its decks?`, { title: 'Delete project', confirmText: 'Delete', danger: true })) return;
    try { await api(`projects/${pid}`, { method: 'DELETE' }); onDeleted?.(); }
    catch (e) { failed('Delete project')(e); }
  }

  async function newDeck() {
    const listing = await api(`templates?project=${pid}`);
    const options = listing.templates.map((t) => [`${t.kind}:${t.id}`, t.kind === 'asset' ? `${nameOf(t)} (this project)` : nameOf(t)]);
    const v = await modalForm({ title: 'New deck', confirmText: 'Create',
      fields: [{ name: 'title', label: 'Title' }, { name: 'template', label: 'Template', value: `admin:${listing.default}`, options }],
      validate: (x) => (x.title ? null : 'Give the deck a title.') });
    if (!v) return;
    const [kind, ...rest] = v.template.split(':');
    try {
      const deck = await api(`projects/${pid}/decks`, { method: 'POST', json: { title: v.title, template: { kind, id: rest.join(':') } } });
      openDeck(deck.id);
      load();
    } catch (e) { failed('New deck')(e); }
  }

  async function uploadDeck() {
    const file = await pickFile(ACCEPT);
    if (!file) return;
    const form = new FormData();
    form.append('file', file);
    window.menus.toast('Uploading…');
    try {
      const deck = await api(`projects/${pid}/decks`, { method: 'POST', form });
      window.menus.toast('The presentation was added.');
      openDeck(deck.id);
      load();
    } catch (e) { failed('Upload a presentation')(e); }
  }

  async function uploadTemplate() {
    const file = await pickFile(ACCEPT);
    if (!file) return;
    const form = new FormData();
    form.append('kind', 'template');
    form.append('file', file);
    try {
      const asset = await api(`projects/${pid}/assets`, { method: 'POST', form });
      if (asset.missing_fonts?.length) {
        await modalAlert(`The template uses fonts the server does not have: ${asset.missing_fonts.join(', ')}. Previews replace them with similar fonts; the downloaded file keeps them.`, { title: 'Template added' });
      } else window.menus.toast('The template was added.');
      load();
    } catch (e) { failed('Upload a template')(e); }
  }

  async function editMemory(item) {
    const v = await modalForm({ title: item ? 'Edit memory' : 'Add to memory', confirmText: 'Save',
      fields: [{ name: 'text', label: 'Fact or decision', value: item?.text || '' }],
      validate: (x) => (x.text && x.text.length <= 500 ? null : 'One short fact (up to 500 characters).') });
    if (!v) return;
    try {
      await api(item ? `projects/${pid}/memory/${item.id}` : `projects/${pid}/memory`, { method: item ? 'PATCH' : 'POST', json: { text: v.text } });
      load();
    } catch (e) { failed('Project memory')(e); }
  }

  async function deleteMemory(id) {
    if (!await modalConfirm('Delete this memory item? The assistant will no longer follow it.', { title: 'Delete memory', confirmText: 'Delete', danger: true })) return;
    await api(`projects/${pid}/memory/${id}`, { method: 'DELETE' }).catch(failed('Delete memory'));
    load();
  }

  async function uploadDocument() {
    const file = await pickFile('.pdf,.docx,.txt,.md,application/pdf,text/plain,text/markdown,application/vnd.openxmlformats-officedocument.wordprocessingml.document');
    if (!file) return;
    const form = new FormData();
    form.append('kind', 'document');
    form.append('file', file);
    try {
      await api(`projects/${pid}/assets`, { method: 'POST', form });
      window.menus.toast('The document was added.');
      load();
    } catch (e) { failed('Add a document')(e); }
  }

  async function deleteAsset(aid) {
    if (!await modalConfirm('Delete this file from the project? Slides already using an image keep it.', { title: 'Delete file', confirmText: 'Delete', danger: true })) return;
    await api(`projects/${pid}/assets/${aid}`, { method: 'DELETE' }).catch(failed('Delete file'));
    load();
  }

  async function deleteTemplate(aid) {
    if (!await modalConfirm('Delete this template? Decks already made from it keep their look.', { title: 'Delete template', confirmText: 'Delete', danger: true })) return;
    await api(`projects/${pid}/assets/${aid}`, { method: 'DELETE' }).catch(failed('Delete template'));
    load();
  }

  load();
  return { reload: load };
}
