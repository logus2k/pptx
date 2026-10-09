// The Artist's ideas at any time (the user, 2026-10-08): in the outline review, a slide's "Other ideas" lists proposals
// in other forms, the chosen one becomes its form; in the editor, "Ideas" lists them for any slide and the chosen one
// remakes it, a version Undo takes back. The e2e app's scripted model (its Artist proposes a list, two columns, a
// highlight, from the slide's own words) and fake knowledge base.
//   SLIDES_URL=http://localhost:2722/ SLIDES_PROXY_SECRET=e2e-secret node tests/ui/m11artist.mjs [width] [theme] [lang]
import { launch, open, overflow, recordMisses, authHeaders, BASE } from './lib.mjs';
import { mkdirSync } from 'node:fs';

const [width = '1440', theme = 'light', lang = 'en'] = process.argv.slice(2);
const W = Number(width);
const PT = lang === 'pt';
const out = new URL('./out/', import.meta.url).pathname;
mkdirSync(out, { recursive: true });
const user = `m11-${Date.now()}@example.com`;
const problems = [];
const check = (ok, what) => { if (!ok) problems.push(what); console.log(`${ok ? 'ok  ' : 'FAIL'} ${what}`); };
const shot = (p, step) => p.screenshot({ path: `${out}m11-${W}-${theme}-${lang}-${step}.png` });

const b = await launch();
const p = await open(b, user, { width: W, height: 900, storage: { 'slides.theme': theme, 'slides.uiLanguage': lang } });
await p.waitForSelector('.identity-btn');
const api = async (path, init = {}) => (await p.request.fetch(`${BASE}api/${path}`, { headers: authHeaders(user), ...init })).json();
await p.locator('.sb-view button[data-action="new-project"], .sb-view button.primary').first().click();
await p.locator('.jsPanel input').first().fill('Artista');
await p.locator('.jsPanel button.primary').click();
await p.waitForSelector('.page [data-action="generate"]');
const pid = new URL(p.url()).pathname.split('/').filter(Boolean).pop();
const closePane = p.locator('#right-panel button[title="Close panel"]:visible, #right-panel button[title="Fechar painel"]:visible');
if (W < 1280 && await closePane.count()) await closePane.first().click();

// 1. the outline review: a slide's other ideas, one chosen
await p.locator('.page [data-action="generate"]').click();
await p.waitForSelector('.generate-form');
await p.locator('input[name="query"]').fill('garantia');
await p.locator('input[name="slides"]').fill('4');
await p.locator('.generate-form button[type="submit"]').click();
await p.waitForSelector('.outline-slide', { timeout: 60000 });
check(await p.locator('.outline-design').count() >= 1, 'each slide says how it is shown');
// the person gives the first slide two points (the small scripted source gives it one), then asks for other ideas
await p.locator('.outline-slide').first().locator('[data-k="points"]').fill('Primeiro ponto da garantia\nSegundo ponto da garantia');
await p.locator('.outline-slide').first().locator('[data-ideas]').click();
await p.waitForSelector('.artist-ideas input[name="idea"]', { timeout: 30000 });
const ideas = await p.locator('.artist-ideas .idea').count();
check(ideas >= 2, `the Artist's ideas are listed (${ideas})`);
check(!(await overflow(p)), 'the ideas dialog: no sideways scroll');
await shot(p, '1-ideas');
await p.locator('.artist-ideas .idea', { hasText: PT ? 'Colunas' : 'Columns' }).first().locator('input').check();
await p.locator('.jsPanel .modal-buttons button.primary').click();
await p.waitForSelector('.outline-design .pill');
check((await p.locator('.outline-slide').first().locator('.outline-design .pill').innerText()).includes(PT ? 'Colunas' : 'Columns'),
  'the chosen idea is the slide\'s form');
await shot(p, '2-outline');
await p.locator('[data-action="build"]').click();
await p.waitForSelector('[data-action="open"]', { timeout: 60000 });
await p.locator('[data-action="open"]').click();
await p.waitForSelector('.slide-strip .strip-item', { timeout: 60000 });
const did = new URL(p.url()).pathname.split('/').filter(Boolean).pop();
const slides = (await api(`projects/${pid}/decks/${did}`)).slides.map((s) => s.id);
const second = await api(`projects/${pid}/decks/${did}/slides/${slides[1]}`);
const words = second.shapes.flatMap((s) => (s.paragraphs || []).map((q) => (q.runs || []).map((r) => r.text).join('')));
check(words.includes('Primeiro') && words.includes('Segundo'), 'the deck\'s first content slide is in columns');

// 2. the editor: ideas for any slide, the chosen one remakes it
const version = (await api(`projects/${pid}/decks/${did}`)).version;
await p.locator(`.strip-item[data-index="2"]`).click();
await p.waitForSelector('.shape-boxes .shape-box');
await p.locator('.editor-bar [data-action="ideas"]').click();
await p.waitForSelector('.artist-ideas input[name="idea"]', { timeout: 30000 });
await p.locator('.artist-ideas .idea', { hasText: PT ? 'Destaque' : 'Highlight' }).first().locator('input').check();
await shot(p, '3-editor-ideas');
await p.locator('.jsPanel .modal-buttons button.primary').click();
let v = version;
for (let i = 0; i < 60 && v === version; i += 1) { await p.waitForTimeout(250); v = (await api(`projects/${pid}/decks/${did}`)).version; }
check(v === version + 1, 'choosing an idea makes a version');
const after = (await api(`projects/${pid}/decks/${did}`)).slides.map((s) => s.id);
check(after.length === slides.length && !after.includes(slides[2]), 'the slide was made again at its place');
await p.waitForFunction(() => { const i = document.querySelector('.stage-sheet img'); return i && i.complete && i.naturalWidth > 0; }, null, { timeout: 90000 });
await shot(p, '4-remade');
await p.locator('.editor-bar [data-action="undo"]').click();
for (let i = 0; i < 60 && v === version + 1; i += 1) { await p.waitForTimeout(250); v = (await api(`projects/${pid}/decks/${did}`)).version; }
check((await api(`projects/${pid}/decks/${did}`)).slides.map((s) => s.id).includes(slides[2]), 'Undo brings the slide back');

if (await overflow(p)) problems.push('the page scrolls sideways');
for (const x of p.problems) problems.push(x);
if (PT) await recordMisses(p);
await b.close();
console.log(problems.length ? `PROBLEMS:\n${problems.join('\n')}` : 'M11 artist: no problems');
process.exit(problems.length ? 1 : 0);
