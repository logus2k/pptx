// M4's browser check: the knowledge base through the page, with the scripted model and the fake KB
// (tests/e2e/fake_app.py, port 2722). The project page lists the person's KB domains; one is chosen and saved; the
// assistant answers from a KB search, and its reply lists the source with its link (spec KB-3, PJ-12).
//   SLIDES_URL=http://localhost:2722/ SLIDES_PROXY_SECRET=e2e-secret node tests/ui/m4.mjs [width] [theme] [lang]
import { launch, open, overflow, recordMisses, authHeaders, BASE } from './lib.mjs';
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';

const [width = '1440', theme = 'light', lang = 'en'] = process.argv.slice(2);
const W = Number(width);
const L = lang === 'pt'
  ? { kb: 'Base de conhecimento', save: 'Guardar domínios', sources: 'Fontes (2)' }
  : { kb: 'Knowledge base', save: 'Save domains', sources: 'Sources (2)' };
const out = new URL('./out/', import.meta.url).pathname;
mkdirSync(out, { recursive: true });
const SCRIPT = new URL('../e2e/out/script.json', import.meta.url).pathname;
const FIX = new URL('../../fixtures/decks/', import.meta.url).pathname;
const user = `m4-${Date.now()}@example.com`;
const problems = [];
const check = (ok, what) => { if (!ok) problems.push(what); console.log(`${ok ? 'ok  ' : 'FAIL'} ${what}`); };
const shot = (p, step) => p.screenshot({ path: `${out}m4-${W}-${theme}${lang === 'en' ? '' : `-${lang}`}-${step}.png` });

const b = await launch();
const p = await open(b, user, { width: W, height: 900, storage: { 'slides.theme': theme, 'slides.uiLanguage': lang } });
await p.waitForSelector('.identity-btn');
const call = async (path, init = {}) => (await p.request.fetch(`${BASE}api/${path}`, { headers: authHeaders(user), ...init })).json();

// a project with a deck, made through the API
const project = await call('projects', { method: 'POST', data: { name: 'KB check' } });
const pid = project.id;
const deck = await call(`projects/${pid}/decks`, { method: 'POST', multipart: {
  file: { name: 'simple.pptx', mimeType: 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
    buffer: readFileSync(`${FIX}simple.pptx`) } } });

// the project page: the person's domains; one chosen and saved
await p.goto(`${BASE}projects/${pid}`, { waitUntil: 'networkidle' });
await p.waitForSelector('[data-kb]');
check((await p.locator('.section-title', { hasText: L.kb }).count()) === 1, 'the project page has its knowledge-base section');
const names = await p.locator('.kb-domains label').allTextContents();
check(names.map((n) => n.trim()).join('|') === 'Produtos|Jurídico', `the person's domains are listed (${names.map((n) => n.trim())})`);
await p.locator('[data-kb="produtos"]').check();
await p.locator('button', { hasText: L.save }).click();
await p.waitForTimeout(500);
check(JSON.stringify((await call(`projects/${pid}`)).settings.kb_domains) === '["produtos"]', 'the chosen domain is saved in the project');
await p.reload({ waitUntil: 'networkidle' });
await p.waitForSelector('[data-kb]');
check(await p.locator('[data-kb="produtos"]').isChecked() && !(await p.locator('[data-kb="juridico"]').isChecked()), 'it is still ticked after a reload');
await p.locator('.section-title', { hasText: L.kb }).scrollIntoViewIfNeeded();
await shot(p, '1-domains');

// the assistant answers from the KB: the reply lists its source, with the link to Cortex
await p.goto(`${BASE}projects/${pid}/decks/${deck.id}`, { waitUntil: 'networkidle' });
await p.waitForSelector('.slide-strip .strip-item');
if (!(await p.locator('.assistant textarea').isVisible())) {
  await p.locator('#menu-toggle').click();
  await p.locator('#menubar .menu-btn', { hasText: lang === 'pt' ? 'Assistente' : 'Assistant' }).click();
  await p.locator('#menubar .menu-item', { hasText: lang === 'pt' ? 'Mostrar o assistente' : 'Show the assistant' }).click();
}
writeFileSync(SCRIPT, JSON.stringify([
  { tools: [['kb_search', { query: 'política de garantia 2026' }]] },
  { text: 'A garantia de 2026 cobre **2 anos** a partir da compra.' },
]));
await p.locator('.assistant textarea').fill('o que diz a política de garantia de 2026?');
await p.locator('.assistant textarea').press('Enter');
await p.waitForSelector('.chat-sources', { timeout: 30000 });
check((await p.locator('.chat-sources summary').textContent()).trim() === L.sources, 'the reply counts the documents it read (the policy, and the notes the search also found)');
await p.locator('.chat-sources summary').click();
const link = p.locator('.chat-sources a').first();
const href = await link.getAttribute('href');
check((await link.textContent()).trim() === 'Política de garantia 2026', 'the source is named by its document title');
check(href.startsWith('https://cortex.example/?open=produtos') && (await link.getAttribute('target')) === '_blank', 'it opens the document in Cortex, in a new tab');
const detail = (await p.locator('.chat-sources small').first().textContent()).trim();
check(detail === 'Cobertura · Exclusões · Como acionar · 2026-09-01', `its line says the sections read and the date (${detail})`);
await shot(p, '2-sources');

if (await overflow(p)) problems.push('the page scrolls sideways');
for (const x of p.problems) problems.push(x);
await recordMisses(p);
await b.close();
console.log(problems.length ? `PROBLEMS:\n${problems.join('\n')}` : 'M4 end to end: no problems');
process.exit(problems.length ? 1 : 0);
