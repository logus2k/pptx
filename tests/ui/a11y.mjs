// The accessibility audit (spec section 8: WCAG 2.2 AA in both themes; every assistant action reachable by keyboard).
// axe-core (tests/ui/node_modules, a development dependency: docs/licenses.md) on each screen a person meets - the
// projects page and its new-project dialog, a project, the editor with its slides, the assistant with a plan card and
// a proposal, the versions panel - at the given width and theme; then the keyboard: the request typed and sent, the
// plan approved and the proposal reviewed without the mouse, every focused control visibly marked.
//   SLIDES_URL=http://localhost:2722/ SLIDES_PROXY_SECRET=e2e-secret node tests/ui/a11y.mjs [width] [theme]
// (the e2e app with the scripted model, as make e2e starts it). Writes tests/ui/out/a11y-<width>-<theme>.json.
import { launch, open, authHeaders, BASE } from './lib.mjs';
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';

const [width = '1440', theme = 'light'] = process.argv.slice(2);
const W = Number(width);
const out = new URL('./out/', import.meta.url).pathname;
mkdirSync(out, { recursive: true });
const AXE = readFileSync(new URL('./node_modules/axe-core/axe.min.js', import.meta.url), 'utf8');
const SCRIPT = new URL('../e2e/out/script.json', import.meta.url).pathname;
const FIX = new URL('../../fixtures/decks/', import.meta.url).pathname;
const user = `a11y-${Date.now()}@example.com`;
const script = (steps) => writeFileSync(SCRIPT, JSON.stringify(steps));
const found = [];
const problems = [];
const check = (ok, what) => { if (!ok) problems.push(what); console.log(`${ok ? 'ok  ' : 'FAIL'} ${what}`); };

async function audit(p, screen) {
  await p.addScriptTag({ content: AXE });
  const r = await p.evaluate(async () => window.axe.run(document, {
    runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa'] },
  }));
  for (const v of r.violations) {
    found.push({ screen, rule: v.id, impact: v.impact, help: v.help, nodes: v.nodes.map((n) => ({ target: n.target.join(' '), summary: n.failureSummary })) });
  }
  check(r.violations.length === 0, `${screen}: ${r.violations.length ? r.violations.map((v) => `${v.id} (${v.nodes.length}: ${v.nodes.map((n) => n.target.join(' ')).slice(0, 3).join('; ')})`).join(', ') : 'no WCAG A/AA violations'}`);
}

/** Tab until the focused element matches `test` (at most `limit` presses); is its focus visible? */
async function tabTo(p, test, what, limit = 80) {
  for (let i = 0; i < limit; i += 1) {
    await p.keyboard.press('Tab');
    const hit = await p.evaluate(test);
    if (hit) {
      const visible = await p.evaluate(() => {
        const e = document.activeElement;
        const s = getComputedStyle(e);
        // an outline (DESIGN.md, Shapes: 2px --primary), or for a field its 2px underline (Components, inputs)
        return (s.outlineStyle !== 'none' && parseFloat(s.outlineWidth) > 0) || s.boxShadow !== 'none'
          || (e.matches('input, textarea, select') && parseFloat(s.borderBottomWidth) >= 2);
      });
      check(visible, `${what}: reached by Tab (${i + 1} presses), its focus visible`);
      return true;
    }
  }
  check(false, `${what}: reached by Tab`);
  return false;
}

const b = await launch();
// the administration (spec AD-4..AD-6), as an administrator (the e2e app's: tests/e2e/fake_app.py)
const pa = await open(b, 'admin@example.com', { width: W, height: 900, storage: { 'slides.theme': theme, 'slides.uiLanguage': 'pt' } });
// a change first, so the usage and the audit log have a row on a fresh server
await pa.request.fetch(`${BASE}api/projects`, { method: 'POST', headers: { ...authHeaders(user), 'Content-Type': 'application/json' }, data: JSON.stringify({ name: 'Auditoria' }) });
for (const [area, rows] of [['templates', '.admin-templates li'], ['usage', '.usage-table tbody tr'], ['audit', '.audit-table tbody tr']]) {
  await pa.goto(`${BASE}admin/${area}`, { waitUntil: 'networkidle' });
  await pa.waitForSelector(rows, { timeout: 10000 }).then(() => audit(pa, `administration: ${area}`)).catch(() => check(false, `the administration's ${area} opened`));
}

await pa.close();
const p = await open(b, user, { width: W, height: 900, storage: { 'slides.theme': theme, 'slides.uiLanguage': 'pt' } });
await p.waitForSelector('.identity-btn');
await audit(p, 'projects');
await p.locator('.sb-view button', { hasText: 'Novo projeto' }).click();
await p.waitForSelector('.jsPanel input');
await audit(p, 'new-project dialog');
await p.locator('.jsPanel input').first().fill('Acessibilidade');
await p.keyboard.press('Enter');
await p.waitForSelector('.page h1:text("Acessibilidade")', { timeout: 10000 }).catch(async () => {
  await p.locator('.jsPanel button.primary').click();  // Enter did not create it: noted, and the audit goes on
  check(false, 'the new-project dialog is submitted with Enter');
  await p.waitForSelector('.page h1:text("Acessibilidade")');
});
await audit(p, 'project');
const chooser = p.waitForEvent('filechooser');
await p.locator('button', { hasText: 'Carregar uma apresentação' }).click();
await (await chooser).setFiles(`${FIX}simple.pptx`);
if (W < 600) {  // spec section 8: no editor on a phone, a note that editing needs a larger screen
  await p.waitForSelector('text=A edição precisa de um ecrã maior', { timeout: 30000 })
    .then(() => check(true, 'a phone gets the note that editing needs a larger screen'))
    .catch(() => check(false, 'a phone gets the note that editing needs a larger screen'));
  await audit(p, 'deck on a phone');
  writeFileSync(`${out}a11y-${W}-${theme}.json`, JSON.stringify(found, null, 1));
  await b.close();
  console.log(problems.length ? `PROBLEMS (${problems.length}): see out/a11y-${W}-${theme}.json` : 'accessibility: no problems');
  process.exit(problems.length ? 1 : 0);
}
await p.waitForSelector('.slide-strip .strip-item');
await p.waitForFunction(() => [...document.querySelectorAll('.slide-strip img')].every((i) => i.complete && i.naturalWidth > 0), null, { timeout: 120000 });
if (!(await p.locator('.assistant textarea').isVisible())) {
  await p.locator('#menu-toggle').click();
  await p.locator('#menubar .menu-btn', { hasText: 'Assistente' }).click();
  await p.locator('#menubar .menu-item', { hasText: 'Mostrar o assistente' }).click();
}
await audit(p, 'editor and assistant');

// the keyboard: to the request box, typed and sent; the plan approved; the proposal reviewed
script([{ tools: [['propose_plan', { steps: ['Encurtar a agenda'] }]] }]);
await p.locator('body').click({ position: { x: 1, y: 1 } });
if (await tabTo(p, () => document.activeElement?.matches('.assistant textarea'), 'the request box')) {
  await p.keyboard.type('encurta a agenda');
  await p.keyboard.press('Enter');
  await p.waitForSelector('.chat-card.plan', { timeout: 30000 });
  await audit(p, 'assistant with a plan');
  const [pid, , did] = new URL(p.url()).pathname.split('/').filter(Boolean).slice(-3);
  const api = async (path) => (await p.request.fetch(`${BASE}api/${path}`, { headers: authHeaders(user) })).json();
  const deck = await api(`projects/${pid}/decks/${did}`);
  const agenda = deck.slides[1].id;
  const shape = (await api(`projects/${pid}/decks/${did}/slides/${agenda}`)).shapes.find((s) => s.placeholder?.idx === 1).shape_id;
  script([{ tools: [['update_text', { slide_id: agenda, shape_id: shape, paragraphs: [{ text: 'Contexto' }, { text: 'Solução' }] }]] }, { text: 'Encurtei a agenda.' }]);
  if (await tabTo(p, () => document.activeElement?.closest('.chat-card.plan') && document.activeElement.tagName === 'BUTTON' && document.activeElement.textContent.includes('Avançar'), 'the plan\'s Go ahead')) {
    await p.keyboard.press('Enter');
    await p.waitForSelector('.chat-card.proposal', { timeout: 30000 });
    await audit(p, 'assistant with a proposal');
    check(await tabTo(p, () => document.activeElement?.closest('.chat-card.proposal') && document.activeElement.tagName === 'BUTTON', 'the proposal\'s Review'), 'the proposal can be reviewed by keyboard');
  }
}
await p.locator('button', { hasText: 'Versões' }).first().click().catch(() => {});
await p.waitForSelector('.versions-panel', { timeout: 10000 }).then(() => audit(p, 'versions')).catch(() => check(false, 'the versions panel opened'));

writeFileSync(`${out}a11y-${W}-${theme}.json`, JSON.stringify(found, null, 1));
await b.close();
console.log(problems.length ? `PROBLEMS (${problems.length}): see out/a11y-${W}-${theme}.json` : 'accessibility: no problems');
process.exit(problems.length ? 1 : 0);
