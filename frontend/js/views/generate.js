// A deck generated from a source (spec NL-12; backend domain/generations.py): route projects/<pid>/generate[/<gid>].
// The form's path - the assistant's is generate_deck, whose plan card opens this same page on its outline (both
// paths: the user's rule). Three states on one page: the options (a corporate presentation or a training; a
// knowledge-base topic, a knowledge-base document or a project document; size, audience, focus, where it goes), the
// reading's progress, then the outline the person edits (titles, points, the presenter's notes; slides moved, removed,
// added) before the slides are made.
import { api } from '../core/api.js';
import { html, raw, setHtml } from '../core/html.js';
import { chooseIdea, FORM_TEXT, summary } from './artist-ideas.js';

const ALERT_ICON = '<svg class="banner-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 3 2 20h20zM12 10v4M12 17h.01"/></svg>';
const DESIGNED = ['content'];  // the roles the Artist gives a form (agent/artist.py: DESIGNED_ROLES)
const ROLE_TEXT = { content: 'Slide', objectives: 'Objectives', section: 'Module', questions: 'Questions', summary: 'Summary' };
const STAGE_TEXT = { reading: 'Reading the source', condensing: 'Condensing the points', planning: 'Planning the goals and the storyboard' };
const SIZES = { corporate: 8, training: 14 };

function nameOf(t) { return t.name?.[window.uiLanguage()] || t.name?.en || t.id; }

export function buildGenerate(view, { pid, gid = null, openDeck, onStarted }) {
  const page = Object.assign(document.createElement('div'), { className: 'page generate-page' });
  view.append(page);
  let timer = null;
  let record = null;

  const fail = (where, e) => setHtml(page, html`<h1>Generate a deck</h1>
    <div class="banner error">${raw(ALERT_ICON)}<div><b>${where}</b><small>${e.message || e}</small></div></div>`);

  // ── 1. the options ─────────────────────────────────────────────
  async function form() {
    let documents = [], decks = [], templates = { templates: [], default: null };
    try {
      const [assets, d, t] = await Promise.all([api(`projects/${pid}/assets`), api(`projects/${pid}/decks`), api(`templates?project=${pid}`)]);
      documents = assets.assets.filter((a) => a.kind === 'document');
      decks = d.decks;
      templates = t;
    } catch (e) { fail('This page could not be opened', e); return; }
    setHtml(page, html`
      <h1>Generate a deck</h1>
      <p class="lead">A presentation or a training made from the knowledge base or a document. You see and can change its outline before the slides are made.</p>
      <form class="card stack generate-form" novalidate>
        <fieldset class="stack"><legend class="section-title">What to make</legend>
          <label class="row"><input type="radio" name="kind" value="corporate" checked> Corporate presentation</label>
          <label class="row"><input type="radio" name="kind" value="training"> Training</label>
        </fieldset>
        <fieldset class="stack"><legend class="section-title">From</legend>
          <label class="row"><input type="radio" name="source" value="kb_topic" checked> A topic in the knowledge base</label>
          <label class="row"><input type="radio" name="source" value="kb_document"> A knowledge-base document</label>
          <label class="row"><input type="radio" name="source" value="document" ${documents.length ? '' : 'disabled'}> A document of this project${documents.length ? '' : ' (none yet)'}</label>
          <label class="field-box" data-for="kb_topic"><span>Topic</span><input type="text" name="query" maxlength="500" placeholder="A product, a process, a rule"></label>
          <div class="stack" data-for="kb_document" hidden>
            <div class="row"><label class="field-box generate-search"><span>Search the knowledge base</span><input type="search" name="kbq" maxlength="300"></label>
              <button type="button" class="secondary" data-action="kb-search">Search</button></div>
            <label class="field-box"><span>Document</span><select name="kbdoc"><option value="">Search first</option></select></label>
          </div>
          <label class="field-box" data-for="document" hidden><span>Document</span><select name="asset">${documents.map((a) => html`<option class="notranslate" value="${a.id}">${a.name}</option>`)}</select></label>
        </fieldset>
        <fieldset class="stack"><legend class="section-title">Options</legend>
          <label class="field-box"><span>Number of slides</span><input type="number" name="slides" min="1" max="40" placeholder="${SIZES.corporate}"></label>
          <label class="field-box"><span>Audience</span><input type="text" name="audience" maxlength="300" placeholder="Who it is for"></label>
          <label class="field-box"><span>Focus</span><textarea name="focus" rows="2" maxlength="1000" placeholder="What to keep to"></textarea></label>
        </fieldset>
        <fieldset class="stack"><legend class="section-title">Where</legend>
          <label class="row"><input type="radio" name="target" value="new" checked> A new deck</label>
          <label class="field-box" data-for="new"><span>Template</span><select name="template">${templates.templates.map((t) => html`<option class="notranslate" value="${t.kind}:${t.id}" ${t.kind === 'admin' && t.id === templates.default ? 'selected' : ''}>${t.kind === 'asset' ? `${nameOf(t)} (this project)` : nameOf(t)}</option>`)}</select></label>
          <label class="row"><input type="radio" name="target" value="deck" ${decks.length ? '' : 'disabled'}> After the slides of a deck${decks.length ? '' : ' (none yet)'}</label>
          <label class="field-box" data-for="deck" hidden><span>Deck</span><select name="deck">${decks.map((d) => html`<option class="notranslate" value="${d.id}">${d.title}</option>`)}</select></label>
        </fieldset>
        <div class="banner error" data-error hidden>${raw(ALERT_ICON)}<div><small data-error-text></small></div></div>
        <div class="row"><button type="submit" class="primary">Read and plan</button></div>
      </form>`);
    const f = page.querySelector('form');
    const show = () => {
      for (const group of ['source', 'target']) {
        const chosen = f.querySelector(`input[name="${group}"]:checked`).value;
        f.querySelectorAll(`[data-for]`).forEach((el) => {
          if (['kb_topic', 'kb_document', 'document'].includes(el.dataset.for) === (group === 'source')) el.hidden = el.dataset.for !== chosen;
        });
      }
      f.slides.placeholder = String(SIZES[f.querySelector('input[name="kind"]:checked').value]);
    };
    f.addEventListener('change', show);
    show();
    f.querySelector('[data-action="kb-search"]').addEventListener('click', async () => {
      const q = f.kbq.value.trim();
      if (q.length < 2) return;
      try {
        const r = await api(`projects/${pid}/kb/documents?q=${encodeURIComponent(q)}`);
        f.kbdoc.replaceChildren(...(r.documents.length ? r.documents.map((d) => Object.assign(new Option(d.title, `${d.domain}\n${d.path}`), { className: 'notranslate' }))
          : [new Option(r.available ? 'Nothing found' : 'The knowledge base is not available', '')]));
      } catch (e) { error(e.message); }
    });
    const error = (text) => { f.querySelector('[data-error]').hidden = !text; f.querySelector('[data-error-text]').textContent = text || ''; };
    f.addEventListener('submit', async (ev) => {
      ev.preventDefault();
      const kind = f.querySelector('input[name="kind"]:checked').value;
      const sk = f.querySelector('input[name="source"]:checked').value;
      const source = { kind: sk };
      if (sk === 'kb_topic') source.query = f.query.value.trim();
      else if (sk === 'kb_document') { const [domain, path] = f.kbdoc.value.split('\n'); Object.assign(source, { domain, path }); }
      else source.asset_id = f.asset.value;
      if ((sk === 'kb_topic' && !source.query) || (sk === 'kb_document' && !source.path) || (sk === 'document' && !source.asset_id)) {
        error(sk === 'kb_topic' ? 'Say the topic.' : 'Choose the document.');
        return;
      }
      const tk = f.querySelector('input[name="target"]:checked').value;
      const target = { kind: tk };
      if (tk === 'deck') target.deck_id = f.deck.value;
      else if (f.template.value) { const [k, ...rest] = f.template.value.split(':'); target.template = { kind: k, id: rest.join(':') }; }
      const body = { kind, source, target, language: window.uiLanguage() === 'en' ? 'en' : 'pt',
        audience: f.audience.value.trim(), focus: f.focus.value.trim() };
      if (f.slides.value) body.slides = Number(f.slides.value);
      try {
        record = await api(`projects/${pid}/generations`, { method: 'POST', json: body });
        onStarted?.(record.id);
        poll();
      } catch (e) { error(e.message); }
    });
  }

  // ── 2. the reading ─────────────────────────────────────────────
  async function poll() {
    clearTimeout(timer);
    try { record = await api(`projects/${pid}/generations/${record?.id || gid}`); } catch (e) { fail('This outline could not be read', e); return; }
    if (record.status === 'reading') {
      const p = record.progress || {};
      const pct = p.total ? Math.round((100 * p.done) / p.total) : 0;
      const what = p.stage === 'reading' && p.total ? `Reading part ${Math.min(p.done + 1, p.total)} of ${p.total}`
        : p.stage === 'writing' && p.total ? `Writing slide ${Math.min(p.done + 1, p.total)} of ${p.total}`
        : p.stage === 'reviewing' && p.total ? `Reviewing slide ${Math.min(p.done + 1, p.total)} of ${p.total}`
        : p.stage === 'designing' && p.total ? `Designing slide ${Math.min(p.done + 1, p.total)} of ${p.total}` : (STAGE_TEXT[p.stage] || 'Reading the source');
      setHtml(page, html`<h1>Generate a deck</h1>
        <p class="lead">The source is read in parts and the slides planned. This takes a few minutes; you can leave this page and come back.</p>
        <div class="card"><div class="kb-progress" role="status"><div class="kb-progress-bar"><i style="width: ${pct}%"></i></div>
          <span class="kb-progress-text">${what}…</span></div></div>`);
      timer = setTimeout(poll, 1000);
      return;
    }
    if (record.status === 'failed') {
      setHtml(page, html`<h1>Generate a deck</h1>
        <div class="banner error">${raw(ALERT_ICON)}<div><b>The outline could not be made</b><small>${record.error || ''}</small></div></div>
        <div class="row" style="margin-top: var(--space-4)"><button type="button" class="primary" data-action="again">Try again</button></div>`);
      page.querySelector('[data-action="again"]').addEventListener('click', () => { record = null; form(); });
      return;
    }
    if (record.status === 'built') { done(); return; }
    editor();
  }

  // ── 3. the outline ─────────────────────────────────────────────
  let slides = [];
  function editor() {
    slides = record.outline.slides.map((s) => ({ ...s }));
    const kind = record.outline.kind === 'training' ? 'Training' : 'Corporate presentation';
    setHtml(page, html`
      <h1>Generate a deck</h1>
      <p class="lead">${kind}: the outline read from the source. Change what you need, then make the slides; each slide's notes say what to present and where it comes from.</p>
      <div class="card stack">
        <label class="field-box"><span>Title of the presentation</span><input type="text" data-field="title" maxlength="300" value="${record.outline.title}"></label>
        <p class="muted">Read: ${record.outline.read?.passages ?? 0} passages, ${record.outline.read?.parts ?? 0} parts.</p>
      </div>
      ${record.outline.goals?.length ? html`<div class="card stack outline-goals">
        <h2>Goals</h2>
        <p class="muted">What the audience will know or be able to do at the end. Each slide below serves one of them.</p>
        <ol>${record.outline.goals.map((g) => html`<li class="user-text">${g}</li>`)}</ol></div>` : ''}
      <ol class="outline-list"></ol>
      <div class="row" style="margin: var(--space-4) 0"><button type="button" class="secondary" data-action="add">Add a slide</button></div>
      <div class="banner error" data-error hidden>${raw(ALERT_ICON)}<div><small data-error-text></small></div></div>
      <div class="row"><button type="button" class="primary" data-action="build">Make the slides</button></div>`);
    list();
    page.querySelector('[data-action="add"]').addEventListener('click', () => {
      collect();
      slides.push({ role: 'content', title: 'New slide', points: [], notes: '', sources: [] });
      list();
    });
    page.querySelector('[data-action="build"]').addEventListener('click', build);
  }

  function list() {
    const ol = page.querySelector('.outline-list');
    setHtml(ol, html`${slides.map((s, i) => html`
      <li class="card stack outline-slide" data-i="${i}">
        <div class="row outline-head"><span class="pill">${i + 1}. ${ROLE_TEXT[s.role] || 'Slide'}</span>
          <span class="spacer"></span>
          <span class="row outline-actions">
            <button type="button" data-move="-1" ${i === 0 ? 'disabled' : ''} aria-label="Move up">Up</button>
            <button type="button" data-move="1" ${i === slides.length - 1 ? 'disabled' : ''} aria-label="Move down">Down</button>
            <button type="button" data-remove ${slides.length === 1 ? 'disabled' : ''}>Remove</button></span></div>
        ${s.task ? html`<p class="outline-task"><span class="muted">${s.goal ? `Task, for goal ${s.goal}:` : 'Task:'}</span> <span class="user-text">${s.task}</span></p>` : ''}
        <label class="field-box"><span>Title</span><input type="text" data-k="title" maxlength="300" value="${s.title}"></label>
        <label class="field-box"><span>Points, one per line</span><textarea data-k="points" rows="${Math.max(2, s.points.length)}">${s.points.join('\n')}</textarea></label>
        <label class="field-box"><span>Speaker notes</span><textarea data-k="notes" rows="2">${s.notes || ''}</textarea></label>
        ${DESIGNED.includes(s.role) ? html`<div class="outline-design row">
          <span class="stack"><span><b>Shown as:</b> <span class="pill">${FORM_TEXT[s.design?.form || 'bullets']}</span>
            ${s.design && s.design.form !== 'bullets' ? html` <span class="user-text">${summary(s.design)}</span>` : ''}</span>
            ${s.design?.why ? html`<small class="muted user-text">${s.design.why}</small>` : ''}
            ${s.reset ? html`<small class="muted">Its points changed: shown as a list. Ask the Artist again for another form.</small>` : ''}</span>
          <span class="spacer"></span>
          <span class="row outline-actions"><button type="button" data-ideas>Other ideas</button>
            ${s.design && s.design.form !== 'bullets' ? html`<button type="button" data-list>As a list</button>` : ''}</span></div>` : ''}
        ${s.review ? html`<div class="outline-review stack">
          ${s.review.verdict === 'good' && !s.review.issues.length ? html`<p><b>Critic:</b> <span class="muted">no issues seen on the rendered slide.</span></p>`
            : html`<p><b>Critic:</b> <span class="muted">${s.review.verdict === 'good' ? 'suggestions for the rendered slide' : 'what is still wrong on the rendered slide, and how to fix it'}</span></p>
              <ul>${s.review.issues.map((x) => html`<li class="user-text"><span class="pill">${x.severity === 'could' ? 'Suggestion' : 'Must fix'}</span> <b>${x.what}</b> <span class="muted">Fix:</span> ${x.fix}</li>`)}</ul>`}
        </div>` : ''}
        ${s.sources?.length ? html`<p class="muted">Sources: <span class="notranslate">${s.sources.join('; ')}</span></p>` : ''}
      </li>`)}`);
    ol.querySelectorAll('[data-move]').forEach((b) => b.addEventListener('click', () => {
      collect();
      const i = Number(b.closest('[data-i]').dataset.i), j = i + Number(b.dataset.move);
      [slides[i], slides[j]] = [slides[j], slides[i]];
      list();
    }));
    ol.querySelectorAll('[data-remove]').forEach((b) => b.addEventListener('click', () => {
      collect();
      slides.splice(Number(b.closest('[data-i]').dataset.i), 1);
      list();
    }));
    ol.querySelectorAll('[data-list]').forEach((b) => b.addEventListener('click', () => {
      collect();
      const s = slides[Number(b.closest('[data-i]').dataset.i)];
      s.design = { form: 'bullets', points: s.points };
      list();
    }));
    ol.querySelectorAll('[data-ideas]').forEach((b) => b.addEventListener('click', async () => {
      collect();
      const i = Number(b.closest('[data-i]').dataset.i);
      try { await save(); } catch (e) { modalAlert(e.message, { title: 'Ideas from the Artist' }); return; }
      const chosen = await chooseIdea({ fetchIdeas: async (wish) => (await api(`projects/${pid}/generations/${record.id}/slides/${i}/ideas`, { method: 'POST', json: { wish } })).ideas });
      if (!chosen) return;
      slides[i].design = chosen;
      slides[i].reset = false;
      list();
    }));
  }

  function collect() {
    page.querySelectorAll('.outline-slide').forEach((li) => {
      const s = slides[Number(li.dataset.i)];
      s.title = li.querySelector('[data-k="title"]').value.trim() || s.title;
      const points = li.querySelector('[data-k="points"]').value.split('\n').map((x) => x.trim()).filter(Boolean);
      if (points.join('\n') !== s.points.join('\n') && s.design && s.design.form !== 'bullets') {
        s.design = { form: 'bullets', points };  // what the form showed no longer holds: a list (accuracy) until asked again
        s.reset = true;
      }
      s.points = points;
      s.notes = li.querySelector('[data-k="notes"]').value.trim();
    });
  }

  // the outline as the person has it now (the Artist's ideas are asked of the saved outline)
  async function save() {
    const title = page.querySelector('[data-field="title"]').value.trim() || record.outline.title;
    const sent = slides.map(({ reset, ...s }) => s);
    record = await api(`projects/${pid}/generations/${record.id}/outline`, { method: 'PUT', json: { title, slides: sent } });
    record.outline.slides.forEach((x, i) => { if (slides[i]) slides[i].design = x.design; });  // as the server checked them
  }

  async function build() {
    collect();
    const err = page.querySelector('[data-error]');
    const button = page.querySelector('[data-action="build"]');
    button.disabled = true;
    window.menus?.toast('Making the slides…');
    try {
      await save();
      record = await api(`projects/${pid}/generations/${record.id}/build`, { method: 'POST' });
      done();
    } catch (e) {
      err.hidden = false;
      err.querySelector('[data-error-text]').textContent = e.message;
      button.disabled = false;
    }
  }

  function done() {
    setHtml(page, html`<h1>Generate a deck</h1>
      <div class="banner"><div><b>The slides were made</b><small>${record.slide_ids?.length || 0} slides. Undo in the editor takes them back.</small></div></div>
      <div class="row" style="margin-top: var(--space-4)"><button type="button" class="primary" data-action="open">Open the deck</button></div>`);
    page.querySelector('[data-action="open"]').addEventListener('click', () => openDeck(record.deck_id));
  }

  if (gid) poll(); else form();
  return { close: () => clearTimeout(timer) };
}
