// The editor's controls (the user's rule, 2026-10-07: every change the assistant can make has a control too): from the
// Slide, Insert and Format menus, the Add slide button, the selected shape's actions and the speaker notes - a slide
// added with its points, duplicated, re-laid, given notes; a chart and a diagram inserted; a table cell, a picture's
// alt text and a text's format changed; slides copied from another deck; the deck's template changed. Each checked in
// the deck itself (the API), each a "manual" version. No model is involved.
//   SLIDES_URL=http://localhost:2722/ SLIDES_PROXY_SECRET=e2e-secret node tests/ui/m10controls.mjs [width] [theme] [lang]
import { launch, open, overflow, recordMisses, authHeaders, BASE } from './lib.mjs';
import { mkdirSync, readFileSync } from 'node:fs';

const [width = '1440', theme = 'light', lang = 'en'] = process.argv.slice(2);
const W = Number(width);
const PT = lang === 'pt';
const T = (en, pt) => (PT ? pt : en);
const out = new URL('./out/', import.meta.url).pathname;
mkdirSync(out, { recursive: true });
const FIX = new URL('../../fixtures/decks/', import.meta.url).pathname;
const user = `m10-${Date.now()}@example.com`;
const problems = [];
const check = (ok, what) => { if (!ok) problems.push(what); console.log(`${ok ? 'ok  ' : 'FAIL'} ${what}`); };
const shot = (p, step) => p.screenshot({ path: `${out}m10-${W}-${theme}-${lang}-${step}.png` });

const b = await launch();
const p = await open(b, user, { width: W, height: 900, storage: { 'slides.theme': theme, 'slides.uiLanguage': lang } });
await p.waitForSelector('.identity-btn');
const api = async (path, init = {}) => (await p.request.fetch(`${BASE}api/${path}`, { headers: authHeaders(user), ...init })).json();

await p.locator('.sb-view button', { hasText: T('New project', 'Novo projeto') }).click();
await p.locator('.jsPanel input').first().fill('Controls');
await p.locator('.jsPanel button.primary').click();
await p.waitForSelector('.page h1:text("Controls")');
const pid = new URL(p.url()).pathname.split('/').filter(Boolean).pop();
// a second deck to copy slides from, uploaded beside it
await p.request.fetch(`${BASE}api/projects/${pid}/decks`, { method: 'POST', headers: authHeaders(user),
  multipart: { file: { name: 'simple.pptx', mimeType: 'application/vnd.openxmlformats-officedocument.presentationml.presentation', buffer: readFileSync(`${FIX}simple.pptx`) } } });
const chooser = p.waitForEvent('filechooser');
await p.locator('button', { hasText: T('Upload a presentation', 'Carregar uma apresentação') }).click();
await (await chooser).setFiles(`${FIX}features.pptx`);
await p.waitForSelector('.slide-strip .strip-item');
const did = new URL(p.url()).pathname.split('/').filter(Boolean).pop();
const closePane = p.locator('#right-panel button[title="Close panel"]:visible, #right-panel button[title="Fechar painel"]:visible');
if (W < 1280 && await closePane.count()) await closePane.first().click();
const deck = () => api(`projects/${pid}/decks/${did}`);
const slideOf = (sid) => api(`projects/${pid}/decks/${did}/slides/${sid}`);
const version = async () => (await deck()).version;
const waitVersion = async (n) => {
  for (let i = 0; i < 60; i += 1) { if (await version() === n) return true; await p.waitForTimeout(250); }
  return false;
};
const words = (rep) => rep.shapes.flatMap((s) => (s.paragraphs || []).map((q) => (q.runs || []).map((r) => r.text).join('')));

async function menu(label, item) {   // a menu of the menu bar (behind the drawer below 1280 px)
  if (W < 1280) await p.locator('#menu-toggle').click();
  await p.locator('#menubar .menu-btn', { hasText: label }).click();
  const it = p.locator('#menubar .menu.open .menu-item', { hasText: item }).first();
  check(!(await it.evaluate((e) => e.classList.contains('disabled'))), `${label} › ${item} is on`);
  await it.click();
}
async function form(values, confirm) {   // the open dialog's fields, by their order, then its main button
  await p.waitForSelector('.jsPanel .kb-field');
  const fields = p.locator('.jsPanel .kb-field');
  for (const [i, v] of values) {
    const el = fields.nth(i).locator('input, select, textarea');
    if (await el.evaluate((e) => e.tagName) === 'SELECT') await el.selectOption(v); else await el.fill(v);
  }
  check(!(await overflow(p)), `the ${confirm} dialog: no sideways scroll`);
  await p.locator('.jsPanel .modal-buttons button.primary').click();
}
const strip = async () => (await deck()).slides.map((s) => s.id);
const selectSlide = async (i) => { await p.locator(`.strip-item[data-index="${i}"]`).click(); await p.waitForSelector('.shape-boxes .shape-box'); };
const rendered = () => p.waitForFunction(() => { const i = document.querySelector('.stage-sheet img'); return i && i.complete && i.naturalWidth > 0; }, null, { timeout: 90000 });
const pickShape = async (sid) => { await p.locator(`.shape-box[data-shape="${sid}"]`).click(); };

const start = await strip();
let v = await version();

// 1. a slide added after the first, from the editor bar's button, with its title and points
await selectSlide(0);
await p.locator('.editor-bar [data-action="add-slide"]').click();
await p.waitForSelector('.jsPanel textarea');
await shot(p, '1-add-form');
await form([[1, 'Novo diapositivo'], [3, 'Primeiro ponto\nSegundo ponto']], 'Add slide');
check(await waitVersion(++v), 'Add slide makes a version');
const added = (await strip())[1];
check(!start.includes(added) && words(await slideOf(added)).join('|') === 'Novo diapositivo|Primeiro ponto|Segundo ponto', 'the new slide is second, with its title and points');

// 2. duplicated, then re-laid, from the Slide menu
await p.waitForSelector('.strip-item[data-index="1"][aria-current="true"]');
await menu(T('Slide', 'Diapositivo'), T('Duplicate slide', 'Duplicar diapositivo'));
check(await waitVersion(++v), 'Duplicate slide makes a version');
const copy = (await strip())[2];
check(words(await slideOf(copy)).join('|') === 'Novo diapositivo|Primeiro ponto|Segundo ponto', 'the copy is right after it');
await menu(T('Slide', 'Diapositivo'), T('Change layout...', 'Alterar esquema...'));
await form([[0, 'Title Only']], 'Change layout');
check(await waitVersion(++v), 'Change layout makes a version');
check((await slideOf((await strip())[2])).layout === 'Title Only', 'the selected slide is on "Title Only"');

// 3. speaker notes, from the card under the slide
await p.locator('.notes-block [data-action="notes"]').click();
await form([[0, 'Dizer primeiro o objetivo.']], 'Speaker notes');
check(await waitVersion(++v), 'saving the notes makes a version');
const sel = (await strip())[2];
check((await slideOf(sel)).notes === 'Dizer primeiro o objetivo.', 'the slide has the notes');
await p.waitForFunction(() => document.querySelector('.notes-text')?.textContent.includes('Dizer primeiro'));
check(true, 'the notes card shows them');
await shot(p, '2-notes');

// 4. a chart and a diagram, from the Insert menu, on the last slide
const last = (await strip()).length - 1;
await selectSlide(last);
await menu(T('Insert', 'Inserir'), T('Chart...', 'Gráfico...'));
await form([[1, 'Vendas'], [2, '; 2025; 2026\nT1; 12; 14\nT2; 15; 17,5']], 'Insert chart');
check(await waitVersion(++v), 'Insert chart makes a version');
const covering = async (what) => {   // placed over the slide's list: the person is told, and dismisses it
  const said = p.locator('.jsPanel .modal-text', { hasText: T('It covers other content', 'Cobre outro conteúdo') });
  check(await said.waitFor({ timeout: 10000 }).then(() => true).catch(() => false), `${what} over the slide's text: the person is told`);
  await p.locator('.jsPanel .modal-buttons button.primary').click();
};
await covering('the chart');
const lastId = (await strip())[last];
const chart = (await slideOf(lastId)).shapes.find((s) => s.type === 'chart');
check(chart && JSON.stringify(chart.chart.series.map((s) => s.values)) === '[[12,15],[14,17.5]]', 'the chart has the typed figures (17,5 read as 17.5)');
await menu(T('Insert', 'Inserir'), T('Diagram...', 'Diagrama...'));
await form([[0, 'Pedido\nAnálise\nDecisão']], 'Insert diagram');
check(await waitVersion(++v), 'Insert diagram makes a version');
await covering('the diagram');
const lastWords = words(await slideOf(lastId));
check(['Pedido', 'Análise', 'Decisão'].every((w) => lastWords.includes(w)), 'the diagram has its three boxes');
await rendered();
await shot(p, '3-chart-diagram');

// 5. a table cell, from the selected table's actions
await selectSlide(0);
const table = (await slideOf(start[0])).shapes.find((s) => s.type === 'table');
await pickShape(table.shape_id);
await p.locator('.shape-actions [data-shape-action="edit-table"]').click();
await p.waitForSelector('.jsPanel textarea');
const rows = (await p.locator('.jsPanel textarea').inputValue()).split('\n');
rows[1] = ['Mudado', ...rows[1].split(' | ').slice(1)].join(' | ');
await form([[0, rows.join('\n')]], 'Edit table');
check(await waitVersion(++v), 'Edit table makes a version');
check((await slideOf(start[0])).shapes.find((s) => s.type === 'table').table.cells[1][0] === 'Mudado', 'the cell changed');

// 6. a picture's alt text, from the Format menu
const picSlide = (await strip()).indexOf(start[1]);
await selectSlide(picSlide);
const pic = (await slideOf(start[1])).shapes.find((s) => s.type === 'picture');
await pickShape(pic.shape_id);
await menu(T('Format', 'Formatar'), T('Alt text...', 'Texto alternativo...'));
await form([[0, 'O logótipo do banco']], 'Alt text');
check(await waitVersion(++v), 'Alt text makes a version');
check((await slideOf(start[1])).shapes.find((s) => s.type === 'picture').alt_text === 'O logótipo do banco', 'the picture has the alt text');

// 7. a text's format, from the selected text box's actions
const bodySlide = (await strip()).indexOf(start[3]);
await selectSlide(bodySlide);
const body = (await slideOf(start[3])).shapes.find((s) => s.placeholder?.idx === 0);   // its title (the diagram covers its body)
await pickShape(body.shape_id);
await p.locator('.shape-actions [data-shape-action="format"]').click();
await form([[1, '1']], 'Format text');
check(await waitVersion(++v), 'Format text makes a version');
const runs = (await slideOf(start[3])).shapes.find((s) => s.shape_id === body.shape_id).paragraphs.flatMap((q) => q.runs || []);
check(runs.length > 0 && runs.every((r) => r.bold), 'the text is bold');
await rendered();
await shot(p, '4-format');

// 8. slides copied from the other deck, then the deck's template changed, from the Slide menu
const n = (await strip()).length;
await menu(T('Slide', 'Diapositivo'), T('Copy slides from another deck...', 'Copiar diapositivos de outra apresentação...'));
await form([[1, '1, 2']], 'Copy slides');
check(await waitVersion(++v), 'Copy slides makes a version');
check((await strip()).length === n + 2, 'two slides were copied in');
await menu(T('Slide', 'Diapositivo'), T("Change the deck's template...", 'Alterar o modelo da apresentação...'));
await form([], 'Change template');
check(await waitVersion(++v), 'Change template makes a version');

const sources = (await api(`projects/${pid}/decks/${did}/versions`)).versions.map((x) => x.source);
check(sources.slice(0, v - 1).every((s) => s === 'manual'), 'each control made a manual version');
// Undo takes the last back
await p.locator('.editor-bar [data-action="undo"]').click();
check(await waitVersion(++v), 'Undo makes a version');

if (await overflow(p)) problems.push('the page scrolls sideways');
for (const x of p.problems) problems.push(x);
if (PT) await recordMisses(p);
await shot(p, '5-done');
await b.close();
console.log(problems.length ? `PROBLEMS:\n${problems.join('\n')}` : 'M10 controls: no problems');
process.exit(problems.length ? 1 : 0);
