// M6's browser check: the project page's memory and reference documents (spec PJ-9, PJ-11), with the scripted model
// (tests/e2e/fake_app.py, port 2722): a document added; a memory item added, edited and deleted by hand; one kept by
// the assistant appears on the page, marked as coming from a conversation.
//   SLIDES_URL=http://localhost:2722/ SLIDES_PROXY_SECRET=e2e-secret node tests/ui/m6.mjs [width] [theme] [lang]
import { launch, open, overflow, recordMisses, authHeaders, BASE } from './lib.mjs';
import { mkdirSync, writeFileSync } from 'node:fs';

const [width = '1440', theme = 'light', lang = 'en'] = process.argv.slice(2);
const W = Number(width);
const pt = lang === 'pt';
const L = pt
  ? { addDoc: 'Acrescentar um documento', addMem: 'Acrescentar à memória', save: 'Guardar', edit: 'Editar', del: 'Eliminar', fromConv: 'de uma conversa', here: 'escrito aqui', passages: 'passagens' }
  : { addDoc: 'Add a document', addMem: 'Add to memory', save: 'Save', edit: 'Edit', del: 'Delete', fromConv: 'from a conversation', here: 'written here', passages: 'passages' };
const out = new URL('./out/', import.meta.url).pathname;
mkdirSync(out, { recursive: true });
const SCRIPT = new URL('../e2e/out/script.json', import.meta.url).pathname;
const DOC = new URL('../../fixtures/docs/precario-2026.md', import.meta.url).pathname;
const user = `m6-${Date.now()}@example.com`;
const problems = [];
const check = (ok, what) => { if (!ok) problems.push(what); console.log(`${ok ? 'ok  ' : 'FAIL'} ${what}`); };
const shot = (p, step) => p.screenshot({ path: `${out}m6-${W}-${theme}${lang === 'en' ? '' : `-${lang}`}-${step}.png` });

const b = await launch();
const p = await open(b, user, { width: W, height: 900, storage: { 'slides.theme': theme, 'slides.uiLanguage': lang } });
await p.waitForSelector('.identity-btn');
const call = async (path, init = {}) => (await p.request.fetch(`${BASE}api/${path}`, { headers: authHeaders(user), ...init })).json();
const project = await call('projects', { method: 'POST', data: { name: 'Memory check' } });
await p.goto(`${BASE}projects/${project.id}`, { waitUntil: 'networkidle' });

// a reference document
const chooser = p.waitForEvent('filechooser');
await p.locator('button', { hasText: L.addDoc }).click();
await (await chooser).setFiles(DOC);
await p.waitForSelector(`.list-title:text("precario-2026.md")`, { timeout: 15000 });
const caption = (await p.locator('.list-item, li', { hasText: 'precario-2026.md' }).locator('.list-caption').first().textContent()).trim();
check(caption.includes(`3 ${L.passages}`), `the document is listed with its passages (${caption})`);

// memory by hand: added, edited, deleted
await p.locator('button', { hasText: L.addMem }).click();
await p.locator('.jsPanel input, .jsPanel textarea').first().fill('O cliente prefere menos marcadores.');
await p.locator('.jsPanel button.primary', { hasText: L.save }).click();
await p.waitForSelector('.memory-list .list-title', { timeout: 10000 });
check((await p.locator('.memory-list .list-caption').first().textContent()).includes(L.here), 'an item written on the page says so');
await p.locator('.memory-list button', { hasText: L.edit }).click();
await p.locator('.jsPanel input, .jsPanel textarea').first().fill('Máximo de quatro marcadores por diapositivo.');
await p.locator('.jsPanel button.primary', { hasText: L.save }).click();
await p.waitForSelector('.memory-list .list-title:text("Máximo de quatro marcadores por diapositivo.")', { timeout: 10000 });
check(true, 'the item is edited');
await p.locator('.memory-list button', { hasText: L.del }).click();
await p.locator('.jsPanel button.danger', { hasText: L.del }).click();   // a deletion's confirm button is the danger one
await p.waitForSelector('.memory-list', { state: 'detached', timeout: 10000 });
check(true, 'and deleted');

// the assistant keeps one: it appears on the page, from a conversation
writeFileSync(SCRIPT, JSON.stringify([
  { tools: [['remember', { text: 'Preços sempre em EUR, sem descontos visíveis.' }]] },
  { text: 'Combinado: vou lembrar-me de que os preços são em EUR e sem descontos.' },
]));
await p.evaluate(() => window.rightPane.show('assistant'));
await p.locator('.assistant textarea').fill('os preços são sempre em euros e sem descontos visíveis');
await p.locator('.assistant textarea').press('Enter');
await p.waitForSelector('.memory-list .list-title:text("Preços sempre em EUR, sem descontos visíveis.")', { timeout: 30000 });
check((await p.locator('.memory-list .list-caption').first().textContent()).includes(L.fromConv), 'an item the assistant kept shows it came from a conversation');
await p.locator('.section-title', { hasText: pt ? 'Memória do projeto' : 'Project memory' }).scrollIntoViewIfNeeded();
await shot(p, '1-memory');

if (await overflow(p)) problems.push('the page scrolls sideways');
for (const x of p.problems) problems.push(x);
await recordMisses(p);
await b.close();
console.log(problems.length ? `PROBLEMS:\n${problems.join('\n')}` : 'M6 end to end: no problems');
process.exit(problems.length ? 1 : 0);
