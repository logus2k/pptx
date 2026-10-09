// The editor's controls for what the assistant can also do (the user's rule, 2026-10-07: asking the assistant is
// never the only way): add, copy, re-lay and copy in slides, charts, diagrams, pictures, alt text, speaker notes, table
// cells, text format and fit, the deck's template. Each is a form over one of the assistant's editing tools, sent to
// POST /edits as {op: "tool", tool, args} and checked against the same schema (contracts/tools); each makes a version
// that Undo takes back. Reached from the Slide, Insert and Format menus (menu.json, as Cortex's commands are).
import { api } from '../core/api.js';
import { chooseIdea, FORM_TEXT } from './artist-ideas.js';

function pickFile(accept) {   // as project.js and admin.js
  return new Promise((resolve) => {
    const input = Object.assign(document.createElement('input'), { type: 'file', accept });
    input.addEventListener('change', () => resolve(input.files[0] || null), { once: true });
    input.click();
  });
}

const lines = (text) => String(text || '').split('\n').map((x) => x.trim()).filter(Boolean);
const textOf = (p) => (p.runs || []).map((r) => r.text || '').join('');

// a number as people type it here: "1 234,5", "1234.5", "15%" (the % is the format's, not the value's)
function number(text) {
  const t = String(text).split(' ').join('').replace('%', '').replace('€', '');
  const v = Number(t.includes(',') && !t.includes('.') ? t.replace(',', '.') : t.split(',').join(''));
  return Number.isFinite(v) ? v : null;
}

// a chart's data as a person types it: a first line "; Series 1; Series 2", then one line per category
// "Category; 3; 5" (";" as a spreadsheet exported in Portugal separates its cells)
function chartData(text) {
  const rows = lines(text).map((l) => l.split(';').map((c) => c.trim()));
  if (rows.length < 2) return { error: 'Give a first line with the series names, then one line per category.' };
  const names = rows[0].slice(1).filter(Boolean);
  if (!names.length) return { error: 'The first line names the series: ; 2025; 2026' };
  const categories = [];
  const series = names.map((name) => ({ name, values: [] }));
  for (const r of rows.slice(1)) {
    categories.push(r[0] || '');
    for (let i = 0; i < names.length; i++) {
      const v = number(r[i + 1] ?? '');
      if (v === null) return { error: `"${r[i + 1] ?? ''}" in the line "${r.join('; ')}" is not a number.` };
      series[i].values.push(v);
    }
  }
  return { categories, series };
}

function chartText(chart) {
  const head = ['', ...chart.series.map((s) => s.name)].join('; ');
  return [head, ...chart.categories.map((c, i) => [c, ...chart.series.map((s) => s.values[i])].join('; '))].join('\n');
}

const CHART_KINDS = [['column', 'Columns'], ['bar', 'Bars'], ['line', 'Line'], ['pie', 'Pie']];
const ASSET_ACCEPT = 'image/png,image/jpeg,image/webp,image/svg+xml';

/** ed: {pid, did, slide(): the selected slide {id} or null, shape(): the one selected shape or null, shapes(),
 *  slides(): the deck's slides, run(tool, args, done): the edit, reloaded after, select(slideId)} */
export function controls(ed) {
  const failed = (title) => (e) => modalAlert(e.message, { title });

  async function layoutOptions(withAuto) {
    const { layouts } = await api(`projects/${ed.pid}/decks/${ed.did}/layouts`);
    const opts = layouts.map((x) => [x.name, x.name]);
    return withAuto ? [['', 'The one the content fits'], ...opts] : opts;
  }

  async function addSlide() {
    const v = await modalForm({ title: 'Add slide', confirmText: 'Add', fields: [
      { name: 'layout', label: 'Layout', value: '', options: await layoutOptions(true) },
      { name: 'title', label: 'Title' },
      { name: 'subtitle', label: 'Subtitle' },
      { name: 'points', label: 'Points, one a line', multiline: true, rows: 5 },
    ], validate: (x) => (x.title || x.points || x.layout ? null : 'Give the slide a title, its points or a layout.') });
    if (!v) return;
    const content = { ...(v.title ? { title: v.title } : {}), ...(v.subtitle ? { subtitle: v.subtitle } : {}),
      ...(lines(v.points).length ? { points: lines(v.points) } : {}) };
    const args = { ...(v.layout ? { layout: v.layout } : {}), ...(Object.keys(content).length ? { content } : {}),
      ...(ed.slide() ? { after_slide_id: ed.slide().id } : {}) };
    const got = await ed.run('add_slide', args, 'Slide added.');
    if (got?.result?.slides?.length) ed.select(got.result.slides[0]);
  }

  async function duplicateSlide() {
    const s = ed.slide();
    const got = await ed.run('duplicate_slide', { slide_id: s.id }, 'Slide duplicated.');
    if (got?.result?.slides?.length) ed.select(got.result.slides[0]);
  }

  async function changeLayout() {
    const v = await modalForm({ title: 'Change layout', confirmText: 'Change', fields: [
      { name: 'layout', label: 'Layout', value: ed.slide().layout || '', options: await layoutOptions(false) },
    ] });
    if (v) await ed.run('change_layout', { slide_id: ed.slide().id, layout: v.layout }, 'Layout changed.');
  }

  async function copySlides() {
    const { decks } = await api(`projects/${ed.pid}/decks`);
    const others = decks.filter((d) => d.id !== ed.did);
    if (!others.length) { modalAlert('This project has no other deck to copy slides from.', { title: 'Copy slides' }); return; }
    const v = await modalForm({ title: 'Copy slides from another deck', confirmText: 'Copy', fields: [
      { name: 'deck', label: 'From the deck', value: others[0].id, options: others.map((d) => [d.id, d.title]) },
      { name: 'slides', label: 'Slides', placeholder: '1, 3, 4', hint: 'Their numbers in that deck, separated by commas. They go after the selected slide.' },
    ], validate: (x) => (x.slides.split(',').every((n) => Number.isInteger(Number(n.trim())) && Number(n.trim()) > 0) ? null : 'Give the slides by their numbers, separated by commas.') });
    if (!v) return;
    const ids = v.slides.split(',').map((n) => Number(n.trim()));
    await ed.run('copy_slides', { from_deck_id: v.deck, slide_ids: ids, ...(ed.slide() ? { after_slide_id: ed.slide().id } : {}) },
      ids.length === 1 ? 'Slide copied.' : `${ids.length} slides copied.`);
  }

  async function changeTemplate() {
    const listing = await api(`templates?project=${ed.pid}`);
    const name = (t) => t.name?.[window.uiLanguage()] || t.name?.en || t.id;   // as project.js's nameOf
    const options = listing.templates.map((t) => [`${t.kind}:${t.id}`, t.kind === 'asset' ? `${name(t)} (this project)` : name(t)]);
    const v = await modalForm({ title: 'Change template', confirmText: 'Change', fields: [
      { name: 'template', label: 'Template', value: options[0]?.[0], options,
        hint: 'The slides keep their content and take the new template\'s layouts, colours and fonts. Undo takes it back.' },
    ] });
    if (!v) return;
    const [kind, ...rest] = v.template.split(':');
    await ed.run('change_template', { template: { kind, id: rest.join(':') } }, 'Template changed.');
  }

  async function notes() {
    const s = ed.slide();
    const rep = await api(`projects/${ed.pid}/decks/${ed.did}/slides/${s.id}`);
    const v = await modalForm({ title: 'Speaker notes', confirmText: 'Save', fields: [
      { name: 'text', label: 'What to say on this slide', value: rep.notes || '', multiline: true, rows: 8 },
    ] });
    if (v && v.text !== (rep.notes || '').trim()) await ed.run('set_notes', { slide_id: s.id, text: v.text }, 'Notes saved.');
  }

  async function chart(existing) {
    const v = await modalForm({ title: existing ? 'Edit chart' : 'Insert chart', confirmText: existing ? 'Save' : 'Insert', fields: [
      { name: 'kind', label: 'Kind', value: existing?.chart?.kind || 'column', options: CHART_KINDS },
      { name: 'title', label: 'Title', value: existing?.chart?.title || '' },
      { name: 'data', label: 'Data', multiline: true, rows: 6, value: existing?.chart ? chartText(existing.chart) : '',
        placeholder: '; 2025; 2026\nT1; 12; 14\nT2; 15; 17',
        hint: 'A first line with the series\' names, then one line per category; ";" between the cells.' },
    ], validate: (x) => chartData(x.data).error || null });
    if (!v) return;
    const { categories, series } = chartData(v.data);
    const s = ed.slide();
    if (existing) await ed.run('edit_chart', { slide_id: s.id, shape_id: existing.shape_id, kind: v.kind, title: v.title, categories, series }, 'Chart changed.');
    else await ed.run('add_chart', { slide_id: s.id, kind: v.kind, categories, series, ...(v.title ? { title: v.title } : {}) }, 'Chart inserted.');
  }

  async function diagram() {
    const v = await modalForm({ title: 'Insert diagram', confirmText: 'Insert', fields: [
      { name: 'nodes', label: 'Boxes, one a line, in order', multiline: true, rows: 6, placeholder: 'Pedido\nAnálise\nDecisão' },
      { name: 'direction', label: 'Shape', value: 'right', options: [['right', 'A flow, left to right'], ['down', 'A hierarchy, top to bottom']],
        hint: 'Each box points to the next. Its look is taken from the deck\'s own diagrams.' },
    ], validate: (x) => (lines(x.nodes).length >= 2 ? (lines(x.nodes).length <= 20 ? null : 'At most 20 boxes.') : 'Give at least two boxes.') });
    if (!v) return;
    await ed.run('draw_diagram', { slide_id: ed.slide().id, nodes: lines(v.nodes).map((text) => ({ text })), direction: v.direction }, 'Diagram inserted.');
  }

  async function uploadImage() {
    const file = await pickFile(ASSET_ACCEPT);
    if (!file) return null;
    const form = new FormData();
    form.append('kind', 'image');
    form.append('file', file);
    window.menus.toast('Uploading…');
    try { return await api(`projects/${ed.pid}/assets`, { method: 'POST', form }); }
    catch (e) { failed('Picture')(e); return null; }
  }

  async function insertImage() {
    const asset = await uploadImage();
    if (!asset) return;
    // inside the slide's body, its proportions kept (insert_image); moved or resized afterwards in PowerPoint
    const box = { x: 0.1, y: 0.25, w: 0.8, h: 0.65 };
    await ed.run('insert_image', { slide_id: ed.slide().id, image: { asset_id: asset.id }, target: { box } }, 'Picture inserted.');
  }

  async function replaceImage() {
    const sh = ed.shape();
    const asset = await uploadImage();
    if (asset) await ed.run('replace_image', { slide_id: ed.slide().id, shape_id: sh.shape_id, image: { asset_id: asset.id } }, 'Picture replaced.');
  }

  async function altText() {
    const sh = ed.shape();
    const v = await modalForm({ title: 'Alt text', confirmText: 'Save', fields: [
      { name: 'text', label: 'What the picture shows, for people who cannot see it', value: sh.alt_text || '', multiline: true, rows: 3 },
    ] });
    if (v) await ed.run('set_alt_text', { slide_id: ed.slide().id, shape_id: sh.shape_id, text: v.text }, 'Alt text saved.');
  }

  async function editTable() {
    const sh = ed.shape();
    const cells = sh.table?.cells || [];
    const v = await modalForm({ title: 'Edit table', confirmText: 'Save', fields: [
      { name: 'rows', label: 'Rows, one a line', multiline: true, rows: Math.min(14, cells.length + 2),
        value: cells.map((r) => r.map((c) => (typeof c === 'string' ? c : '')).join(' | ')).join('\n'),
        hint: '" | " between the cells. A line added at the end adds a row; a line removed removes the last row.' },
    ] });
    if (!v) return;
    const want = v.rows.split('\n').filter((l) => l.trim()).map((l) => l.split('|').map((c) => c.trim()));
    const cols = cells[0]?.length || 0;
    const operations = [];
    want.forEach((row, r) => {
      if (r >= cells.length) { operations.push({ op: 'add_row', cells: Array.from({ length: cols }, (_, c) => row[c] ?? '') }); return; }
      for (let c = 0; c < cols; c++) {
        const now = typeof cells[r][c] === 'string' ? cells[r][c] : '';
        if ((row[c] ?? '') !== now) operations.push({ op: 'set_cell', row: r, col: c, text: row[c] ?? '' });
      }
    });
    for (let r = cells.length - 1; r >= want.length; r--) operations.push({ op: 'delete_row', row: r });
    if (!operations.length) return;
    await ed.run('edit_table', { slide_id: ed.slide().id, shape_id: sh.shape_id, operations }, 'Table changed.');
  }

  async function formatText() {
    const sh = ed.shape();
    const keep = ['', 'As it is'];
    const v = await modalForm({ title: 'Format text', confirmText: 'Apply', fields: [
      { name: 'size', label: 'Size (pt)', placeholder: 'As it is' },
      { name: 'bold', label: 'Bold', value: '', options: [keep, ['1', 'Bold'], ['0', 'Not bold']] },
      { name: 'italic', label: 'Italic', value: '', options: [keep, ['1', 'Italic'], ['0', 'Not italic']] },
      { name: 'alignment', label: 'Alignment', value: '', options: [keep, ['left', 'Left'], ['center', 'Centred'], ['right', 'Right'], ['justify', 'Justified']] },
      { name: 'colour', label: 'Colour', value: '', options: [keep, ['text1', 'Text'], ['text2', 'Text 2'], ['accent1', 'Accent 1'], ['accent2', 'Accent 2'], ['accent3', 'Accent 3'], ['accent4', 'Accent 4'], ['accent5', 'Accent 5'], ['accent6', 'Accent 6']],
        hint: 'The template\'s own colours.' },
    ], validate: (x) => {
      if (x.size && !(number(x.size) >= 8 && number(x.size) <= 96)) return 'A size from 8 to 96 points.';
      return x.size || x.bold || x.italic || x.alignment || x.colour ? null : 'Choose something to change.';
    } });
    if (!v) return;
    const style = { ...(v.size ? { size_pt: number(v.size) } : {}), ...(v.bold ? { bold: v.bold === '1' } : {}),
      ...(v.italic ? { italic: v.italic === '1' } : {}), ...(v.alignment ? { alignment: v.alignment } : {}),
      ...(v.colour ? { theme_color: v.colour } : {}) };
    await ed.run('format_text', { slide_id: ed.slide().id, shape_id: sh.shape_id, style }, 'Text formatted.');
  }

  // the Artist's ideas for the slide (agent/artist.py): one chosen, the slide made again in that form, its title and notes
  // kept (ops.redesign_slide)
  async function askArtist() {
    const s = ed.slide();
    const chosen = await chooseIdea({
      fetchIdeas: async (wish) => (await api(`projects/${ed.pid}/decks/${ed.did}/slides/${s.id}/ideas`, { method: 'POST', json: { wish } })).ideas,
    });
    if (!chosen) return;
    const got = await ed.run('redesign_slide', { slide_id: s.id, design: chosen }, `The slide is now shown as: ${FORM_TEXT[chosen.form] || chosen.form}.`);
    if (got?.result?.slides?.length) ed.select(got.result.slides[0]);
  }

  async function fitText() {
    await ed.run('fit_text', { slide_id: ed.slide().id, shape_id: ed.shape().shape_id }, 'Text fitted to its box.');
  }

  return { addSlide, duplicateSlide, changeLayout, copySlides, changeTemplate, notes, insertChart: () => chart(null),
    editChart: () => chart(ed.shape()), diagram, askArtist, insertImage, replaceImage, altText, editTable, formatText, fitText, textOf };
}
