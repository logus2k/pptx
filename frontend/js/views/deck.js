// A deck in the editor (route projects/<pid>/decks/<did>; spec PM-3, PM-4, PM-6, NL-9, NL-10): the slide strip, the
// selected slide large with clickable boxes over its shapes (the selection the assistant reads as "this"), the version
// history with Restore, Undo and Redo, Download. While the assistant's changes to this deck wait for a decision, the
// editor shows them: the draft's strip with added, changed and removed slides marked, Before and After side by side,
// and a choice per slide (accept selected, or reject all). The previews are LibreOffice's rendering and say so. On a
// phone there is no editor (spec section 8). Simple edits by hand (spec PM-7): a text box's text in place (double-click
// it, F2, or Edit text), slides reordered by dragging them in the strip (or Alt+Up / Alt+Down), a slide deleted; each
// is a new version that Undo takes back, sent with the version it was made on (a deck that moved on answers 409).
import { api, downloadUrl, slideImage } from '../core/api.js';
import { html, raw, setHtml } from '../core/html.js';
import * as store from '../core/store.js';
import { decide } from '../assistant/assistant.js';
import { controls } from './deck-controls.js';

const phone = window.matchMedia('(max-width: 833px)');
const INFO_ICON = '<svg class="banner-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M12 11v6M12 7.5h.01"/></svg>';
// the editor the Slide, Insert and Format menus act on (the one last shown); its commands are registered once
let active = null;
const SHAPE_ACTIONS = {   // the selected shape's actions under the slide, by its kind (the menus have the same)
  text: [['edit-text', 'Edit text'], ['format', 'Format text'], ['fit', 'Fit text']],
  picture: [['alt-text', 'Alt text'], ['replace-image', 'Replace picture']],
  chart: [['edit-chart', 'Edit chart'], ['alt-text', 'Alt text']],
  table: [['edit-table', 'Edit table']],
};
const SOURCES = { upload: 'Uploaded', template: 'Created from a template', restore: 'Restored', assistant: 'Assistant', manual: 'Edited', undo: 'Undone', redo: 'Redone', duplicate: 'Copied from another deck' };

function when(iso) {
  try { return new Date(iso).toLocaleString(window.uiLanguage() === 'pt' ? 'pt-PT' : 'en-GB', { day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' }); }
  catch { return ''; }
}

function draftImage(pid, cid, prid, did, sid, size) {
  return `api/projects/${pid}/conversations/${cid}/proposals/${prid}/decks/${did}/slides/${sid}/image?size=${size}`;
}

export function buildDeck(view, { pid, did, onTitle, onChanged }) {
  const root = document.createElement('div');
  root.className = 'editor';
  view.append(root);
  let info = null;
  let selected = 0;               // index in the strip (the deck's slides, or the draft's while reviewing)
  let selectedShapes = new Set();
  let showVersions = false;
  let review = null;              // {proposal, deck: its entry, include: Set of slide ids}
  let shapes = [];                // the selected slide's shapes (read model), for editing text in place
  let slideRep = null;            // the selected slide's read model: its layout, notes and shapes
  let dragFrom = null;            // the strip index being dragged
  // the edit lease (spec PJ-13): taken on opening, renewed while the editor is open, released on closing; while
  // another member holds it, this editor views the deck and changes nothing ("being edited by ...")
  let lease = { mine: false, holder: null, viewer: false };
  const RENEW_MS = 60_000;

  async function takeLease() {
    try {
      await api(`projects/${pid}/decks/${did}/lease`, { method: 'POST' });
      lease = { mine: true, holder: null, viewer: false };
    } catch (e) {
      if (e.status === 404) lease = { mine: false, holder: null, viewer: true };       // a viewer: no lease to take
      else if (e.status === 409) lease = { mine: false, holder: info?.lease?.holder || null, viewer: false };
    }
  }

  const renew = setInterval(async () => {
    if (!root.isConnected) { clearInterval(renew); return; }
    const was = lease.mine;
    await takeLease();
    if (lease.mine !== was) load(true);            // freed (or taken by someone else): the editor follows
  }, RENEW_MS);

  function release() {
    clearInterval(renew);
    if (lease.mine) fetch(`api/projects/${pid}/decks/${did}/lease`, { method: 'DELETE', keepalive: true }).catch(() => {});
    lease = { mine: false, holder: null, viewer: false };
  }
  window.addEventListener('pagehide', release);

  async function load(keepSelection = false) {
    try {
      info = await api(`projects/${pid}/decks/${did}`);
    } catch (e) {
      setHtml(root, html`<div class="page"><div class="banner error">${raw(INFO_ICON)}<div><b>This deck could not be opened</b><small class="user-text">${e.message}</small></div></div></div>`);
      return;
    }
    await takeLease();
    if (!lease.mine && !lease.viewer) lease.holder = info.lease?.holder || lease.holder;
    if (!keepSelection) selected = 0;
    onTitle?.(info.deck.title);
    syncReview(store.get('proposal'));
    render();
  }

  function stripSlides() {
    if (review) return review.deck.order.map((s) => ({ id: s.id, title: s.title, hidden: s.hidden, state: s.state }));
    return info.slides.map((s) => ({ id: s.id, title: s.title, hidden: s.hidden, state: 'same' }));
  }

  function current() {
    const removed = review ? review.deck.slides.filter((s) => s.state === 'removed').map((s) => ({ id: s.slide_id, title: s.title, hidden: false, state: 'removed' })) : [];
    const all = [...stripSlides(), ...removed];
    selected = Math.min(selected, Math.max(0, all.length - 1));
    return { all, slide: all[selected] };
  }

  function image(s, size) {
    if (!review || s.state === 'removed') return slideImage(pid, did, s.id, review ? review.deck.base_version : info.version, size);
    return draftImage(pid, review.proposal.conversation_id, review.proposal.id, did, s.id, size);
  }

  function publishSelection(slide) {
    store.set('deck', did);
    store.set('version', info.version);
    store.set('selection', slide && !review ? { slide_id: slide.id, shape_ids: [...selectedShapes] } : null);
    // the menus follow the selection at once (measured: Format › Alt text still off right after a picture was picked)
    document.dispatchEvent(new Event('ui-sections-changed'));
  }

  function render() {
    const d = info.deck;
    if (phone.matches) {
      setHtml(root, html`<div class="page"><h1 class="user-text">${d.title}</h1>
        <div class="banner phone-note">${raw(INFO_ICON)}<div><b>Editing needs a larger screen</b><small>Open this deck on a tablet or a computer to edit it.</small></div></div>
        <div class="stack"><a class="button-link secondary" href="${downloadUrl(pid, did)}">Download</a></div></div>`);
      return;
    }
    const { all, slide } = current();
    publishSelection(slide);
    const locked = !lease.mine;                    // another member's, or a viewer's: nothing changes from here
    const off = locked ? 'disabled' : '';
    setHtml(root, html`
      ${locked ? html`<div class="banner info lease-note" role="status">${raw(INFO_ICON)}<div>${lease.viewer
        ? html`<b>You can view this deck</b><small>Your role in this project is viewer.</small>`
        : html`<b>Being edited by <span class="notranslate">${lease.holder || 'another member'}</span></b><small>You can view it; you can change it when they close it.</small>`}</div></div>` : ''}
      <div class="editor-bar">
        <span class="editor-title user-text">${d.title}</span>
        <span class="pill">Version ${info.version}</span>
        <span class="editor-spacer"></span>
        <button type="button" data-action="undo" title="Undo the last accepted change" ${review || locked ? 'disabled' : ''}>Undo</button>
        <button type="button" data-action="redo" title="Redo" ${review || locked ? 'disabled' : ''}>Redo</button>
        <button type="button" data-action="add-slide" title="Add a slide after this one (also in the Slide menu)" ${review || locked ? 'disabled' : ''}>Add slide</button>
        <button type="button" data-action="edit-text" title="Edit the selected text box (F2, or double-click it)" disabled>Edit text</button>
        <button type="button" data-action="delete-slide" ${review || !slide || locked ? 'disabled' : ''}>Delete slide</button>
        <button type="button" data-action="rename" ${off}>Rename</button>
        <button type="button" data-action="versions" aria-pressed="${showVersions}">Versions</button>
        <a class="button-link" href="${downloadUrl(pid, did)}" download>Download</a>
        <a class="button-link" href="${downloadUrl(pid, did).replace('/download', '/pdf')}" download>PDF</a>
      </div>
      ${review ? html`<div class="review-bar">
        <span>The assistant's changes: ${review.include.size} of ${review.deck.slides.length} slides selected. Nothing is saved until you accept.</span>
        <span class="editor-spacer"></span>
        <button type="button" class="primary" data-action="accept" ${review.include.size && !locked ? '' : 'disabled'}>Accept selected</button>
        <button type="button" data-action="reject">Reject all</button></div>` : ''}
      <div class="editor-body">
        <ol class="slide-strip" aria-label="Slides">${all.map((s, i) => html`
          <li draggable="${review || locked ? 'false' : 'true'}" data-index="${i}"><button type="button" class="strip-item${i === selected ? ' selected' : ''}${s.hidden ? ' hidden-slide' : ''} state-${s.state}" data-index="${i}"
               aria-current="${i === selected}">
            <span class="strip-number">${s.state === 'removed' ? '–' : i + 1}</span>
            <span class="strip-thumb"><img class="notranslate" alt="${s.title || ''}" title="${s.title || ''}" loading="lazy" src="${image(s, 'thumb')}">${s.state !== 'same' ? html`<span class="strip-badge pill ${s.state === 'removed' ? 'error' : 'alert'}">${{ added: 'New', changed: 'Changed', removed: 'Removed' }[s.state]}</span>` : ''}</span>
          </button></li>`)}</ol>
        <div class="stage">${stage(slide, all.length)}</div>
        ${showVersions ? html`<aside class="versions-panel" aria-label="Versions"><h2 class="section-title">Versions</h2><div class="versions-body"><span class="skeleton value"></span></div></aside>` : ''}
      </div>`);
    wire();
    loading(root);
    if (showVersions) loadVersions();
    if (slide && !review) loadShapes(slide.id);
  }

  // a slide image still rendering shows the skeleton on its frame, not a white page that looks empty
  function loading(el) {
    for (const img of el.querySelectorAll('.strip-thumb img, .stage-sheet img')) {
      if (img.complete && img.naturalWidth) continue;
      const frame = img.closest('.strip-thumb, .stage-sheet');
      frame.classList.add('loading');
      img.addEventListener('load', () => frame.classList.remove('loading'), { once: true });
    }
  }

  function stage(slide, count) {
    if (!slide) return html`<div class="banner">${raw(INFO_ICON)}<div><b>No slides yet</b><small>Ask the assistant to add some, or upload a presentation.</small></div></div>`;
    const position = slide.state === 'removed' ? 'Removed slide' : `Slide ${selected + 1} of ${count}`;
    // one span per sentence: each is translated on its own (i18n.js looks up whole texts)
    const note = html`<p class="stage-note">${slide.hidden ? html`<span>Hidden slide</span> · ` : ''}<span>${position}</span> · <span>Previews are approximate: they are rendered by LibreOffice, not PowerPoint.</span></p>`;
    if (!review || slide.state === 'same') {
      return html`<div class="stage-sheet"><img alt="" src="${image(slide, 'preview')}"><div class="shape-boxes"></div></div>
        <div class="shape-actions row" role="group" aria-label="The selected shape" hidden></div>${note}
        <section class="notes-block" aria-labelledby="notes-title"><div class="row"><h2 class="section-title" id="notes-title">Speaker notes</h2>
          <span class="editor-spacer"></span><button type="button" data-action="notes" ${lease.mine ? '' : 'disabled'}>Edit notes</button></div>
          <p class="notes-text user-text muted">…</p></section>`;
    }
    const before = slideImage(pid, did, slide.id, review.deck.base_version, 'preview');
    const after = draftImage(pid, review.proposal.conversation_id, review.proposal.id, did, slide.id, 'preview');
    return html`<div class="diff">
        ${slide.state !== 'added' ? html`<figure><figcaption>Before</figcaption><div class="stage-sheet"><img alt="" src="${before}"></div></figure>` : ''}
        ${slide.state !== 'removed' ? html`<figure><figcaption>After</figcaption><div class="stage-sheet"><img alt="" src="${after}"></div></figure>` : ''}
      </div>
      <label class="row include"><input type="checkbox" data-include="${slide.id}" ${review.include.has(slide.id) ? 'checked' : ''}> Accept this slide's change</label>
      ${note}`;
  }

  async function loadShapes(slideId) {
    let rep;
    try { rep = await api(`projects/${pid}/decks/${did}/slides/${slideId}?version=${info.version}`); } catch { return; }
    const layer = root.querySelector('.shape-boxes');
    if (!layer) return;
    shapes = rep.shapes || [];
    slideRep = rep;
    const notesEl = root.querySelector('.notes-text');
    if (notesEl) {   // the person's notes as written; the empty state is interface text, translated
      notesEl.classList.toggle('user-text', Boolean(rep.notes));
      notesEl.textContent = rep.notes || (window.cortexT ? window.cortexT('No notes.') : 'No notes.');
    }
    const boxes = shapes.filter((s) => s.box && s.type !== 'group');
    setHtml(layer, html`${boxes.map((s) => html`<button type="button" class="shape-box notranslate${selectedShapes.has(s.shape_id) ? ' on' : ''}" data-shape="${s.shape_id}"
      style="left:${s.box.x * 100}%;top:${s.box.y * 100}%;width:${s.box.w * 100}%;height:${s.box.h * 100}%"
      title="${s.name}" aria-pressed="${selectedShapes.has(s.shape_id)}" aria-label="${s.name}"></button>`)}`);
    layer.querySelectorAll('.shape-box').forEach((b) => b.addEventListener('click', () => {
      const id = Number(b.dataset.shape);
      if (selectedShapes.has(id)) selectedShapes.delete(id); else selectedShapes.add(id);
      b.classList.toggle('on', selectedShapes.has(id));
      b.setAttribute('aria-pressed', String(selectedShapes.has(id)));
      publishSelection(current().slide);
      editButton();
      shapeActions();
    }));
    layer.querySelectorAll('.shape-box').forEach((b) => {
      b.addEventListener('dblclick', () => editText(Number(b.dataset.shape)));
      b.addEventListener('keydown', (e) => { if (e.key === 'F2') { e.preventDefault(); editText(Number(b.dataset.shape)); } });
    });
    editButton();
    shapeActions();
  }

  // the kind of the one selected shape, for its actions: text, picture, chart, table, or null
  function selectedShape() {
    return selectedShapes.size === 1 ? shapes.find((s) => s.shape_id === [...selectedShapes][0]) || null : null;
  }
  function kindOf(s) {
    if (!s) return null;
    if (s.type === 'table') return 'table';
    if (s.type === 'chart') return 'chart';
    if (s.type === 'picture') return 'picture';
    return editable(s) ? 'text' : null;
  }

  function shapeActions() {
    const bar = root.querySelector('.shape-actions');
    if (!bar) return;
    const kind = lease.mine && !review ? kindOf(selectedShape()) : null;
    bar.hidden = !kind;
    setHtml(bar, html`${(SHAPE_ACTIONS[kind] || []).map(([a, label]) => html`<button type="button" data-shape-action="${a}">${label}</button>`)}`);
    bar.querySelectorAll('[data-shape-action]').forEach((b) => b.addEventListener('click', () => command(b.dataset.shapeAction)));
  }

  // ── the editor's controls (deck-controls.js): each a version, as the edits below ─────
  async function run(tool, args, done) {
    if (!lease.mine || review) return null;
    let got = null;
    try {
      got = await api(`projects/${pid}/decks/${did}/edits`, { method: 'POST', json: { base_version: info.version, op: 'tool', tool, args } });
      window.menus.toast(done);
      // a chart or a diagram over the slide's own content (deck-controls: placed under the title), said
      if (got.result?.covers?.length) modalAlert('It covers other content on this slide. Undo takes it back; on a slide of its own it has the room.', { title: 'Edit' });
      if (got.result?.moved_to_notes) modalAlert("The subtitle did not fit the cover with its other lines: it is in the slide's speaker notes.", { title: 'Edit' });
      if (got.result?.left_out?.length) modalAlert(`The layout had no place for some of it, left out: ${got.result.left_out.join(', ')}.`, { title: 'Edit' });
    } catch (e) {
      if (e.status === 409) window.menus.toast('The deck had changed since you opened it: it has been reloaded. Try again.');
      else modalAlert(e.message, { title: 'Edit' });
    }
    await load(true);
    onChanged?.();
    return got;
  }

  const ctl = controls({
    pid, did, run,
    slide: () => { const s = current().slide; return s && s.state !== 'removed' ? { id: s.id, layout: slideRep?.slide_id === s.id ? slideRep.layout : '' } : null; },
    shape: selectedShape,
    select: (slideId) => { const i = info.slides.findIndex((x) => x.id === slideId); if (i >= 0) select(i); },
  });

  function command(name) {
    const can = lease.mine && !review;
    if (!can) return;
    const slide = current().slide;
    const kind = kindOf(selectedShape());
    const act = {
      'add-slide': ctl.addSlide, 'duplicate-slide': slide && ctl.duplicateSlide, 'change-layout': slide && ctl.changeLayout,
      'move-up': slide && (() => moveSlide(selected, selected - 1)), 'move-down': slide && (() => moveSlide(selected, selected + 1)),
      'copy-slides': ctl.copySlides, 'change-template': ctl.changeTemplate, notes: slide && ctl.notes,
      'insert-chart': slide && ctl.insertChart, 'insert-diagram': slide && ctl.diagram, 'insert-image': slide && ctl.insertImage,
      'edit-text': kind === 'text' && (() => editText(selectedShape().shape_id)), format: kind === 'text' && ctl.formatText,
      fit: kind === 'text' && ctl.fitText, 'alt-text': (kind === 'picture' || kind === 'chart') && ctl.altText,
      'replace-image': kind === 'picture' && ctl.replaceImage, 'edit-chart': kind === 'chart' && ctl.editChart,
      'edit-table': kind === 'table' && ctl.editTable,
    }[name];
    if (act) Promise.resolve(act()).catch((e) => modalAlert(e.message, { title: 'Edit' }));
  }

  // what the menus may offer now (menus.js reads these every half second)
  const can = () => active === api_ && root.isConnected && !!info && lease.mine && !review && !phone.matches;
  function contexts() {
    const k = can() ? kindOf(selectedShape()) : null;
    return { deckEditable: can(), slideSelected: can() && !!current().slide, shapeText: k === 'text',
      shapePicture: k === 'picture', shapeChart: k === 'chart', shapeTable: k === 'table', shapeAlt: k === 'picture' || k === 'chart' };
  }

  // ── edits by hand (spec PM-7) ──────────────────────────────────────
  const textOf = (p) => (p.runs || []).map((r) => r.text || '').join('');
  const editable = (s) => s && Array.isArray(s.paragraphs) && s.type !== 'table' && s.type !== 'picture' && !s.locked;

  function editButton() {
    const b = root.querySelector('[data-action="edit-text"]');
    if (!b) return;
    const one = selectedShapes.size === 1 ? shapes.find((s) => s.shape_id === [...selectedShapes][0]) : null;
    b.disabled = Boolean(review) || !lease.mine || !editable(one);
  }

  async function manual(body, done) {
    try {
      await api(`projects/${pid}/decks/${did}/edits`, { method: 'POST', json: { base_version: info.version, ...body } });
      window.menus.toast(done);
    } catch (e) {
      if (e.status === 409) window.menus.toast('The deck had changed since you opened it: it has been reloaded. Try again.');
      else modalAlert(e.message, { title: 'Edit' });
    }
    await load(true);
    onChanged?.();
  }

  function editText(shapeId) {
    if (!lease.mine) return;                       // another member's deck, or a viewer's: nothing to edit here
    const s = shapes.find((x) => x.shape_id === shapeId);
    const layer = root.querySelector('.shape-boxes');
    if (review || !editable(s) || !layer) return;
    layer.querySelector('.text-edit')?.remove();
    const box = document.createElement('div');
    box.className = 'text-edit';
    box.style.left = `${s.box.x * 100}%`;
    box.style.top = `${s.box.y * 100}%`;
    box.style.width = `${s.box.w * 100}%`;
    setHtml(box, html`<label class="visually-hidden" for="text-edit-${shapeId}">Text, one paragraph a line</label>
      <textarea id="text-edit-${shapeId}" class="user-text" rows="${Math.min(12, Math.max(3, s.paragraphs.length + 1))}"></textarea>
      <div class="row"><button type="button" class="primary" data-edit="save">Save</button><button type="button" data-edit="cancel">Cancel</button>
      <small class="list-caption">Ctrl+Enter saves · Esc cancels</small></div>`);
    layer.append(box);
    const area = box.querySelector('textarea');
    area.value = s.paragraphs.map(textOf).join('\n');
    const close = () => { box.remove(); layer.querySelector(`[data-shape="${shapeId}"]`)?.focus(); };
    const save = () => {
      const lines = area.value.split('\n');
      if (lines.join('\n') === s.paragraphs.map(textOf).join('\n')) { close(); return; }
      manual({ op: 'text', slide_id: current().slide.id, shape_id: shapeId, paragraphs: lines }, 'Text changed.');
    };
    box.querySelector('[data-edit="save"]').addEventListener('click', save);
    box.querySelector('[data-edit="cancel"]').addEventListener('click', close);
    area.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') { e.preventDefault(); close(); }
      if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); save(); }
    });
    area.focus();
  }

  async function deleteSlide() {
    if (!lease.mine) return;
    const { all, slide } = current();
    if (review || !slide) return;
    if (!await modalConfirm(`Delete slide ${selected + 1}? Undo brings it back.`, { title: 'Delete slide', confirmText: 'Delete' })) return;
    if (selected >= all.length - 1) selected = Math.max(0, selected - 1);
    selectedShapes = new Set();
    await manual({ op: 'delete', slide_id: slide.id }, 'Slide deleted.');
  }

  async function moveSlide(from, to) {
    if (!lease.mine) return;
    const { all } = current();
    if (review || from === to || to < 0 || to >= all.length) return;
    selected = to;
    await manual({ op: 'move', slide_id: all[from].id, position: to }, `Slide moved to position ${to + 1}.`);
    root.querySelector(`.strip-item[data-index="${to}"]`)?.focus();
  }

  function wire() {
    root.querySelector('[data-action="rename"]').addEventListener('click', rename);
    root.querySelector('[data-action="add-slide"]').addEventListener('click', () => command('add-slide'));
    root.querySelector('[data-action="notes"]')?.addEventListener('click', () => command('notes'));
    root.querySelector('[data-action="edit-text"]').addEventListener('click', () => editText([...selectedShapes][0]));
    root.querySelector('[data-action="delete-slide"]').addEventListener('click', deleteSlide);
    for (const li of root.querySelectorAll('.slide-strip li[draggable="true"]')) {
      li.addEventListener('dragstart', (e) => { dragFrom = Number(li.dataset.index); e.dataTransfer.effectAllowed = 'move'; e.dataTransfer.setData('text/plain', li.dataset.index); });
      li.addEventListener('dragover', (e) => { if (dragFrom === null) return; e.preventDefault(); li.classList.add('drop-target'); });
      li.addEventListener('dragleave', () => li.classList.remove('drop-target'));
      li.addEventListener('dragend', () => { dragFrom = null; root.querySelectorAll('.drop-target').forEach((x) => x.classList.remove('drop-target')); });
      li.addEventListener('drop', (e) => { e.preventDefault(); const from = dragFrom; dragFrom = null; li.classList.remove('drop-target'); if (from !== null) moveSlide(from, Number(li.dataset.index)); });
    }
    root.querySelector('[data-action="versions"]').addEventListener('click', () => { showVersions = !showVersions; render(); });
    root.querySelector('[data-action="undo"]').addEventListener('click', () => history('undo'));
    root.querySelector('[data-action="redo"]').addEventListener('click', () => history('redo'));
    root.querySelector('[data-action="accept"]')?.addEventListener('click', () => decide(review.proposal, true, { [did]: [...review.include] }));
    root.querySelector('[data-action="reject"]')?.addEventListener('click', () => decide(review.proposal, false));
    root.querySelector('[data-include]')?.addEventListener('change', (e) => {
      const id = Number(e.target.dataset.include);
      if (e.target.checked) review.include.add(id); else review.include.delete(id);
      render();
    });
    for (const b of root.querySelectorAll('.strip-item')) b.addEventListener('click', () => select(Number(b.dataset.index)));
    root.querySelector('.slide-strip').addEventListener('keydown', (e) => {
      const n = root.querySelectorAll('.strip-item').length;
      if (e.altKey && e.key === 'ArrowDown') { e.preventDefault(); moveSlide(selected, selected + 1); return; }   // the keyboard's drag
      if (e.altKey && e.key === 'ArrowUp') { e.preventDefault(); moveSlide(selected, selected - 1); return; }
      if (e.key === 'Delete') { e.preventDefault(); deleteSlide(); return; }
      if (e.key === 'ArrowDown' || e.key === 'ArrowRight') { e.preventDefault(); select(Math.min(selected + 1, n - 1), true); }
      if (e.key === 'ArrowUp' || e.key === 'ArrowLeft') { e.preventDefault(); select(Math.max(selected - 1, 0), true); }
    });
  }

  function select(i, focus = false) {
    if (i !== selected) selectedShapes = new Set();
    selected = i;
    render();
    if (focus) root.querySelector(`.strip-item[data-index="${i}"]`)?.focus();
  }

  async function history(kind) {
    try {
      await api(`projects/${pid}/decks/${did}/${kind}`, { method: 'POST' });
      window.menus.toast(kind === 'undo' ? 'Undone.' : 'Redone.');
      await load(true);
      onChanged?.();
    } catch (e) { modalAlert(e.message, { title: kind === 'undo' ? 'Undo' : 'Redo' }); }
  }

  async function loadVersions() {
    const body = root.querySelector('.versions-body');
    try {
      const { current_version: currentV, versions } = await api(`projects/${pid}/decks/${did}/versions`);
      setHtml(body, html`<div class="data-table-wrap"><table class="data-table">
        <thead><tr><th>Version</th><th>Change</th></tr></thead>
        <tbody>${versions.map((x) => html`<tr>
          <td>${x.number}${x.number === currentV ? html` <span class="pill info">Current</span>` : ''}</td>
          <td><span>${SOURCES[x.source] || x.source}</span>${x.restored_from ? ` (${x.restored_from})` : ''}
              <div class="list-caption user-text version-author">${x.author}</div><div class="list-caption">${when(x.created_at)}</div>
              <div class="row">${x.number === currentV ? '' : html`<button type="button" data-restore="${x.number}">Restore</button>`}
                <a class="button-link" href="${downloadUrl(pid, did, x.number)}" download>Download</a></div></td>
        </tr>`)}</tbody></table></div>`);
      for (const b of body.querySelectorAll('[data-restore]')) b.addEventListener('click', () => restore(Number(b.dataset.restore)));
    } catch (e) {
      setHtml(body, html`<p class="user-text">${e.message}</p>`);
    }
  }

  async function restore(number) {
    if (!await modalConfirm(`Restore version ${number}? It becomes a new version; nothing is lost.`, { title: 'Restore version', confirmText: 'Restore' })) return;
    try {
      await api(`projects/${pid}/decks/${did}/versions/${number}/restore`, { method: 'POST' });
      window.menus.toast(`Version ${number} restored.`);
      await load(true);
      onChanged?.();
    } catch (e) { modalAlert(e.message, { title: 'Restore version' }); }
  }

  async function rename() {
    const v = await modalForm({ title: 'Rename deck', confirmText: 'Save', fields: [{ name: 'title', label: 'Title', value: info.deck.title }],
      validate: (x) => (x.title ? null : 'Give the deck a title.') });
    if (!v) return;
    try { await api(`projects/${pid}/decks/${did}`, { method: 'PATCH', json: v }); await load(true); onChanged?.(); }
    catch (e) { modalAlert(e.message, { title: 'Rename deck' }); }
  }

  function syncReview(p) {
    const entry = p && p.status === 'pending' ? p.decks?.[did] : null;
    if (!entry) { review = null; return; }
    if (!review || review.proposal.id !== p.id) {
      review = { proposal: p, deck: entry, include: new Set(entry.slides.map((s) => s.slide_id)) };
      const firstChanged = entry.order.findIndex((s) => s.state !== 'same');
      selected = firstChanged >= 0 ? firstChanged : 0;
    } else {
      review.proposal = p;
      review.deck = entry;
    }
  }

  store.on('proposal', (p) => { if (!info) return; const was = review; syncReview(p); if (was || review) render(); });
  document.addEventListener('sa:deck-changed', (e) => { if (e.detail.deck_id === did) { load(true); onChanged?.(); } });
  document.addEventListener('sa:review', (e) => { if (e.detail.deck === did && store.get('proposal')) { syncReview(store.get('proposal')); render(); } });
  phone.addEventListener('change', () => info && render());
  load();
  const api_ = { reload: () => load(true), title: () => info?.deck.title, release, command, contexts,
    focus: () => { active = api_; if (info) publishSelection(current().slide); } };
  active = api_;
  return api_;
}

// the menus' commands and contexts, once: they act on the editor last shown
const COMMANDS = ['add-slide', 'duplicate-slide', 'move-up', 'move-down', 'change-layout', 'copy-slides', 'change-template',
  'notes', 'insert-chart', 'insert-diagram', 'insert-image', 'edit-text', 'format', 'fit', 'alt-text', 'replace-image',
  'edit-chart', 'edit-table'];
function registerMenus() {
  for (const c of COMMANDS) window.menus.command(`deck.${c}`, () => active?.command(c));
  for (const key of ['deckEditable', 'slideSelected', 'shapeText', 'shapePicture', 'shapeChart', 'shapeTable', 'shapeAlt']) {
    window.menus.context(key, () => Boolean(active?.contexts()[key]));
  }
}
if (window.menus) registerMenus(); else document.addEventListener('menus-ready', registerMenus, { once: true });
