// M7's browser check of the edits by hand (spec PM-7): a title edited in place, a slide dragged to another place in
// the strip, one moved with the keyboard (Alt+Up / Alt+Down), one deleted, and Undo bringing it back; each checked in
// the deck itself (the API), each a "manual" version. No model is involved.
//   SLIDES_URL=http://localhost:2722/ SLIDES_PROXY_SECRET=e2e-secret node tests/ui/m7.mjs [width] [theme] [lang]
import { launch, open, overflow, recordMisses, authHeaders, BASE } from './lib.mjs';
import { mkdirSync } from 'node:fs';

const [width = '1440', theme = 'light', lang = 'en'] = process.argv.slice(2);
const W = Number(width);
const L = lang === 'pt'
  ? { newProject: 'Novo projeto', create: 'Criar', upload: 'Carregar uma apresentação', del: 'Eliminar', delSlide: 'Eliminar diapositivo', undo: 'Anular', editText: 'Editar texto' }
  : { newProject: 'New project', create: 'Create', upload: 'Upload a presentation', del: 'Delete', delSlide: 'Delete slide', undo: 'Undo', editText: 'Edit text' };
const out = new URL('./out/', import.meta.url).pathname;
mkdirSync(out, { recursive: true });
const FIX = new URL('../../fixtures/decks/', import.meta.url).pathname;
const user = `m7-${Date.now()}@example.com`;
const problems = [];
const check = (ok, what) => { if (!ok) problems.push(what); console.log(`${ok ? 'ok  ' : 'FAIL'} ${what}`); };
const shot = (p, step) => p.screenshot({ path: `${out}m7-${W}-${theme}${lang === 'en' ? '' : `-${lang}`}-${step}.png` });

const b = await launch();
const p = await open(b, user, { width: W, height: 900, storage: { 'slides.theme': theme, 'slides.uiLanguage': lang } });
await p.waitForSelector('.identity-btn');
const api = async (path, init = {}) => (await p.request.fetch(`${BASE}api/${path}`, { headers: authHeaders(user), ...init })).json();

await p.locator('.sb-view button', { hasText: L.newProject }).click();
await p.locator('.jsPanel input').first().fill('Manual edits');
await p.locator('.jsPanel button.primary', { hasText: L.create }).click();
await p.waitForSelector('.page h1:text("Manual edits")');
const chooser = p.waitForEvent('filechooser');
await p.locator('button', { hasText: L.upload }).click();
await (await chooser).setFiles(`${FIX}simple.pptx`);
await p.waitForSelector('.slide-strip .strip-item');
const [pid, , did] = new URL(p.url()).pathname.split('/').filter(Boolean).slice(-3);
const order = async () => (await api(`projects/${pid}/decks/${did}`)).slides.map((s) => s.id);
const sources = async () => (await api(`projects/${pid}/decks/${did}/versions`)).versions.map((v) => v.source);
const waitVersion = async (n) => {
  for (let i = 0; i < 40; i += 1) { if ((await api(`projects/${pid}/decks/${did}/versions`)).current_version === n) return true; await p.waitForTimeout(250); }
  return false;
};
const start = await order();

// 1. the first slide's title, edited where it is: double-click, type, Ctrl+Enter
const titleId = (await api(`projects/${pid}/decks/${did}/slides/${start[0]}`)).shapes.find((s) => s.placeholder?.idx === 0).shape_id;
await p.waitForSelector(`.shape-box[data-shape="${titleId}"]`);
await p.locator(`.shape-box[data-shape="${titleId}"]`).dblclick();
await p.waitForSelector('.text-edit textarea');
check(await p.locator('.text-edit textarea').inputValue() !== '', 'the editor opens with the title\'s text');
await p.locator('.text-edit textarea').fill('Título editado à mão');
await shot(p, '1-editing');
await p.locator('.text-edit textarea').press('Control+Enter');
check(await waitVersion(2), 'saving makes version 2');
const title = (await api(`projects/${pid}/decks/${did}/slides/${start[0]}`)).shapes.find((s) => s.shape_id === titleId);
check(title.paragraphs.map((q) => q.runs.map((r) => r.text).join('')).join('\n') === 'Título editado à mão', 'the deck has the new title');
await p.waitForSelector('.text-edit', { state: 'detached' });

// 2. the third slide dragged to the top of the strip
await p.waitForSelector('.slide-strip li[draggable="true"]');
await p.locator('.slide-strip li').nth(2).dragTo(p.locator('.slide-strip li').nth(0));
check(await waitVersion(3), 'dropping it makes version 3');
check(JSON.stringify(await order()) === JSON.stringify([start[2], start[0], start[1]]), 'the slide is now first');
await shot(p, '2-dragged');

// 3. the keyboard's drag: the selected (first) slide one place down
await p.waitForSelector('.strip-item[data-index="0"]');
await p.locator('.strip-item[data-index="0"]').focus();
await p.keyboard.press('Alt+ArrowDown');
check(await waitVersion(4), 'Alt+Down makes version 4');
check(JSON.stringify(await order()) === JSON.stringify([start[0], start[2], start[1]]), 'the slide moved one place down');

// 4. a slide deleted (with its confirmation), then Undo brings it back
await p.locator('.strip-item[data-index="2"]').click();
await p.locator('.editor-bar button', { hasText: L.delSlide }).click();
await p.locator('.jsPanel').getByRole('button', { name: L.del, exact: true }).click();
check(await waitVersion(5), 'deleting makes version 5');
check(JSON.stringify(await order()) === JSON.stringify([start[0], start[2]]), 'the slide is gone');
await shot(p, '3-deleted');
await p.locator('.editor-bar').getByRole('button', { name: L.undo, exact: true }).click();
check(await waitVersion(6), 'Undo makes version 6');
check((await order()).length === 3, 'Undo brings the slide back');
check(JSON.stringify((await sources()).slice(0, 5)) === JSON.stringify(['undo', 'manual', 'manual', 'manual', 'manual']), 'each edit by hand is a manual version');

// the edit button follows the selection: on for one text box, off for none
await p.locator('.strip-item[data-index="0"]').click();
await p.waitForSelector(`.shape-box[data-shape="${titleId}"]`);
check(await p.locator('.editor-bar button', { hasText: L.editText }).isDisabled(), 'Edit text waits for a text box to be selected');
await p.locator(`.shape-box[data-shape="${titleId}"]`).click();
check(!(await p.locator('.editor-bar button', { hasText: L.editText }).isDisabled()), 'one selected text box: Edit text is on');
await p.waitForTimeout(2000);   // and it stays so (nothing re-renders the selection away)
check(await p.locator('.shape-box.on').count() === 1, 'the box stays selected');
check(!(await p.locator('.editor-bar button', { hasText: L.editText }).isDisabled()), 'Edit text stays on');
await shot(p, '4-selected');

if (await overflow(p)) problems.push('the page scrolls sideways');
for (const x of p.problems) problems.push(x);
await recordMisses(p);
await b.close();
console.log(problems.length ? `PROBLEMS:\n${problems.join('\n')}` : 'M7 edits by hand: no problems');
process.exit(problems.length ? 1 : 0);
