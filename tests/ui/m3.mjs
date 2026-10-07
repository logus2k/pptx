// M3's browser check (technical design section 13, M3): the assistant through the page, with the scripted model
// (tests/e2e/fake_app.py, in the test image on port 2722). A request gets a plan; approved, the changes arrive as a
// proposal; the editor shows Before and After; one slide is left out and the rest accepted; Undo.
//   SLIDES_URL=http://localhost:2722/ SLIDES_PROXY_SECRET=e2e-secret node tests/ui/m3.mjs [width] [theme]
import { launch, open, overflow, recordMisses, authHeaders, BASE } from './lib.mjs';
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';

const [width = '1440', theme = 'light', lang = 'en'] = process.argv.slice(2);
// the labels as the page shows them, in the language under test (plain strings: Playwright matches a substring)
const L = lang === 'pt'
  ? { newProject: 'Novo projeto', create: 'Criar', upload: 'Carregar uma apresentação', goAhead: 'Avançar', acceptSelected: 'Aceitar selecionados', undo: 'Anular', review: 'Rever', assistant: 'Assistente', show: 'Mostrar o assistente' }
  : { newProject: 'New project', create: 'Create', upload: 'Upload a presentation', goAhead: 'Go ahead', acceptSelected: 'Accept selected', undo: 'Undo', review: 'Review', assistant: 'Assistant', show: 'Show the assistant' };
const W = Number(width);
const out = new URL('./out/', import.meta.url).pathname;
mkdirSync(out, { recursive: true });
const SCRIPT = new URL('../e2e/out/script.json', import.meta.url).pathname;
const FIX = new URL('../../fixtures/decks/', import.meta.url).pathname;
const user = `m3-${Date.now()}@example.com`;
const problems = [];
const check = (ok, what) => { if (!ok) problems.push(what); console.log(`${ok ? 'ok  ' : 'FAIL'} ${what}`); };
const shot = (p, step) => p.screenshot({ path: `${out}m3-${W}-${theme}${lang === 'en' ? '' : `-${lang}`}-${step}.png` });
const script = (steps) => writeFileSync(SCRIPT, JSON.stringify(steps));

const b = await launch();
const p = await open(b, user, { width: W, height: 900, storage: { 'slides.theme': theme, 'slides.uiLanguage': lang } });
await p.waitForSelector('.identity-btn');
const api = async (path, init = {}) => (await p.request.fetch(`${BASE}api/${path}`, { headers: authHeaders(user), ...init })).json();

// a project with a deck, opened in the editor; the assistant pane is beside it
await p.locator('.sb-view button', { hasText: L.newProject }).click();
await p.locator('.jsPanel input').first().fill('Assistant check');
await p.locator('.jsPanel button.primary', { hasText: L.create }).click();
await p.waitForSelector('.page h1:text("Assistant check")');
const chooser = p.waitForEvent('filechooser');
await p.locator('button', { hasText: L.upload }).click();
await (await chooser).setFiles(`${FIX}simple.pptx`);
await p.waitForSelector('.slide-strip .strip-item');
if (W >= 1280) check(await p.locator('.assistant textarea').isVisible(), 'the assistant pane is open beside the editor');
else {
  // a tablet: the pane stays closed until asked for (Assistant menu, in the drawer); it opens over the editor
  check(!(await p.locator('.assistant textarea').isVisible()), 'on a tablet the pane waits to be asked for');
  await p.locator('#menu-toggle').click();
  await p.locator('#menubar .menu-btn', { hasText: L.assistant }).click();
  await p.locator('#menubar .menu-item', { hasText: L.show }).click();
  await p.waitForSelector('.assistant textarea', { state: 'visible', timeout: 5000 }).catch(() => {});
  check(await p.locator('.assistant textarea').isVisible(), 'the Assistant menu opens the pane');
}
const [pid, , did] = new URL(p.url()).pathname.split('/').filter(Boolean).slice(-3);
const deck = await api(`projects/${pid}/decks/${did}`);
const [s1, s2, s3] = deck.slides.map((s) => s.id);
const body = async (sid) => (await api(`projects/${pid}/decks/${did}/slides/${sid}`)).shapes.find((s) => s.placeholder?.idx === 1).shape_id;

// a request: the model proposes a plan first
script([{ tools: [['propose_plan', { steps: ['Shorten the agenda on slide 2', 'Shorten the columns on slide 3'] }]] }]);
await p.locator('.assistant textarea').fill('tighten slides 2 and 3');
await p.locator('.assistant textarea').press('Enter');
await p.waitForSelector('.chat-card.plan', { timeout: 30000 });
check((await p.locator('.chat-card.plan li').count()) === 2, 'the plan card shows its two steps');
await p.waitForFunction(() => document.querySelector('.assistant select').selectedOptions[0]?.textContent === 'tighten slides 2 and 3', null, { timeout: 10000 }).catch(() => {});
check(await p.evaluate(() => document.querySelector('.assistant select').selectedOptions[0]?.textContent) === 'tighten slides 2 and 3',
  'the conversation is named after its first message');
await shot(p, '1-plan');

// approved: the changes arrive as a proposal; the editor reviews them
script([
  { tools: [['update_text', { slide_id: s2, shape_id: await body(s2), paragraphs: [{ runs: [{ text: 'Contexto' }] }, { runs: [{ text: 'Proposta' }] }] }],
            ['update_text', { slide_id: s3, shape_id: await body(s3), paragraphs: [{ runs: [{ text: 'Antes: manual' }] }] }]] },
  { text: 'I shortened slides 2 and 3. **Review** them before accepting.' },
]);
await p.locator('.chat-card.plan button', { hasText: L.goAhead }).click();
await p.waitForSelector('.chat-card.proposal', { timeout: 30000 });
if (W < 1280) {      // a tablet: Review in the card takes the person to the editor, the pane stepping aside
  await p.locator('.chat-card.proposal button', { hasText: L.review }).click();
  await p.waitForSelector('.assistant textarea', { state: 'hidden', timeout: 5000 }).catch(() => {});
  check(!(await p.locator('.assistant textarea').isVisible()), 'Review closes the pane over the editor');
}
await p.waitForSelector('.review-bar', { timeout: 30000 });
check((await p.locator('.strip-badge').count()) === 2, 'the strip marks the two changed slides');
await p.waitForFunction(() => [...document.querySelectorAll('.diff img')].length === 2
  && [...document.querySelectorAll('.diff img')].every((i) => i.complete && i.naturalWidth > 0), null, { timeout: 120000 });
check(true, 'Before and After both render');
check((await p.locator('.chat-msg.bot strong').count()) >= 1, "the assistant's reply is rendered as Markdown");
await shot(p, '2-review');

// leave slide 3 out, accept slide 2
await p.locator('.strip-item.state-changed').nth(1).click();
await p.locator('[data-include]').uncheck();
await p.locator('.review-bar button', { hasText: L.acceptSelected }).click();
await p.waitForSelector('.review-bar', { state: 'detached', timeout: 30000 });
await p.waitForFunction(() => document.querySelector('.editor-bar .pill')?.textContent.includes('2'), null, { timeout: 30000 });
const after = await api(`projects/${pid}/decks/${did}`);
const text = async (sid) => (await api(`projects/${pid}/decks/${did}/slides/${sid}`)).shapes.find((s) => s.placeholder?.idx === 1)
  .paragraphs.map((x) => x.runs.map((r) => r.text).join('')).join(' / ');
check(after.version === 2 && (await text(s2)) === 'Contexto / Proposta', 'slide 2 changed in version 2');
check((await text(s3)).startsWith('Processos manuais'), 'slide 3, left out, is as it was');
await p.waitForFunction(() => [...document.querySelectorAll('.slide-strip img')].every((i) => i.complete && i.naturalWidth > 0), null, { timeout: 120000 });
await shot(p, '3-accepted');

// Undo: back to the uploaded content, as version 3
await p.locator('.editor-bar button', { hasText: L.undo }).click();
await p.waitForFunction(() => document.querySelector('.editor-bar .pill')?.textContent.includes('3'), null, { timeout: 30000 });
check((await text(s2)).startsWith('Contexto e objetivos'), 'Undo brings the original back as version 3');
await p.waitForTimeout(500);
await shot(p, '4-undone');

// the shapes of the selected slide can be selected: the assistant receives them
await p.locator('.strip-item').first().click();
await p.waitForSelector('.shape-box');
await p.locator('.shape-box').first().click();
check(await p.locator('.shape-box.on').count() === 1, 'a shape box is selected on the stage');
await shot(p, '5-selection');

if (await overflow(p)) problems.push('the page scrolls sideways');
for (const x of p.problems) problems.push(x);
await recordMisses(p);
await b.close();
console.log(problems.length ? `PROBLEMS:\n${problems.join('\n')}` : 'M3 end to end: no problems');
process.exit(problems.length ? 1 : 0);
