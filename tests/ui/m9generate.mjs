// A deck generated from a source (spec NL-12), both paths (the user's rule): the project's "Generate a deck" form - a
// training from a knowledge-base topic, its outline edited, the slides made and opened - and the assistant's
// generate_deck, whose plan card opens the same outline. The e2e app's scripted model and fake knowledge base.
//   SLIDES_URL=http://localhost:2722/ SLIDES_PROXY_SECRET=e2e-secret node tests/ui/m9generate.mjs [width] [theme] [lang]
import { launch, open, overflow, recordMisses } from './lib.mjs';
import { mkdirSync, writeFileSync } from 'node:fs';

const [width = '1440', theme = 'light', lang = 'en'] = process.argv.slice(2);
const W = Number(width);
const out = new URL('./out/', import.meta.url).pathname;
mkdirSync(out, { recursive: true });
const SCRIPT = new URL('../e2e/out/script.json', import.meta.url).pathname;
const stamp = Date.now();
const problems = [];
const check = (ok, what) => { if (!ok) problems.push(what); console.log(`${ok ? 'ok  ' : 'FAIL'} ${what}`); };
const shot = (p, step) => p.screenshot({ path: `${out}m9generate-${W}-${theme}-${lang}-${step}.png`, fullPage: true });
const clipped = (p) => p.evaluate(() => {
  const box = [...document.querySelectorAll('.generate-page')].find((x) => x.offsetParent);
  if (!box) return ['no page'];
  const r = box.getBoundingClientRect();
  return [...box.querySelectorAll('button, .field-box, .pill, .card')].filter((e) => e.offsetParent)
    .filter((e) => { const q = e.getBoundingClientRect(); return q.right > r.right + 1 || q.left < r.left - 1; })
    .slice(0, 3).map((e) => `${e.tagName.toLowerCase()}.${e.className}`);
});

const b = await launch();
const p = await open(b, `gen-${stamp}@example.com`, { width: W, height: 900, storage: { 'slides.theme': theme, 'slides.uiLanguage': lang } });
await p.waitForSelector('.identity-btn');
await p.locator('.sb-view button[data-action="new-project"], .sb-view button.primary').first().click();
await p.locator('.jsPanel input').first().fill('Formações');
await p.locator('.jsPanel button.primary').click();
await p.waitForSelector('.page [data-action="generate"]');
const closePane = p.locator('#right-panel button[title="Close panel"]:visible, #right-panel button[title="Fechar painel"]:visible');
if (W < 1280 && await closePane.count()) await closePane.first().click();

// the form
await p.locator('.page [data-action="generate"]').click();
await p.waitForSelector('.generate-form');
await p.locator('input[name="kind"][value="training"]').check();
await p.locator('input[name="query"]').fill('garantia');
await p.locator('input[name="slides"]').fill('8');
check(!(await overflow(p)) && !(await clipped(p)).length, 'the form: nothing cut off, no sideways scroll');
await shot(p, '1-form');
await p.locator('.generate-form button[type="submit"]').click();
await p.waitForSelector('.outline-slide', { timeout: 60000 });
const n = await p.locator('.outline-slide').count();
check(n >= 5, `the outline is shown (${n} slides), the first the objectives`);
check((await p.locator('.outline-slide').first().locator('.pill').innerText()).length > 0, 'each slide shows its role');
await p.locator('.outline-slide').nth(1).locator('[data-k="title"]').fill(`Módulo editado ${stamp}`);
await p.locator('.outline-slide').last().locator('[data-remove]').click();
check(await p.locator('.outline-slide').count() === n - 1, 'a slide removed from the outline');
check(!(await overflow(p)) && !(await clipped(p)).length, 'the outline: nothing cut off, no sideways scroll');
await shot(p, '2-outline');
await p.locator('[data-action="build"]').click();
await p.waitForSelector('[data-action="open"]', { timeout: 60000 });
await shot(p, '3-made');
await p.locator('[data-action="open"]').click();
if (W < 600) {  // spec section 8: no editor on a phone, its note instead
  const noted = p.locator('text=larger screen').or(p.locator('text=ecrã maior'));   // plain text, either language
  const note = await noted.first().waitFor({ timeout: 30000 }).then(() => true).catch(() => false);
  check(note, 'on a phone the deck opens to the note that editing needs a larger screen');
} else {
  await p.waitForSelector('.slide-strip .strip-item', { timeout: 60000 });
  const strip = await p.locator('.slide-strip .strip-item').count();
  check(strip === n, `the deck opens with the cover and the edited outline's slides (${strip} of ${n})`);
}

// the assistant's path: generate_deck's plan opens the same outline
const pid = new URL(p.url()).pathname.split('/').filter(Boolean)[1];
writeFileSync(SCRIPT, JSON.stringify([{ tools: [['generate_deck', { kind: 'corporate', source: { kind: 'kb_topic', query: 'garantia' }, slides: 5 }]] },
  { text: 'Fiz a apresentação.' }, { text: 'Fiz a apresentação.' }]));
async function pane() {
  if (await p.locator('.assistant textarea').isVisible()) return;
  await p.locator('#menu-toggle').click();
  await p.locator('#menubar .menu-btn').nth(1).click();
  await p.locator('#menubar .menu-item:visible').first().click();   // the Assistant menu's first: show the assistant
  await p.waitForSelector('.assistant textarea', { state: 'visible', timeout: 5000 });
}
await pane();
await p.locator('.assistant textarea').fill('Faz uma apresentação sobre a garantia a partir da base de conhecimento');
await p.locator('.assistant textarea').press('Enter');
await p.waitForSelector('.chat-card.plan [data-outline]', { timeout: 60000 });
const lists = p.locator('.chat-card.plan ol');
check((await lists.count()) === 2 && (await lists.first().locator('li').count()) >= 1, 'the plan card lists the goals, then the slides');
const steps = lists.last().locator('li');
check((await steps.count()) >= 2 && (await steps.first().innerText()).startsWith('Capa'), 'the slides start with the cover');
await shot(p, '4-plan');
await p.locator('.chat-card.plan [data-outline]').click();
await p.waitForSelector('.generate-page .outline-slide', { timeout: 20000 });
check(p.url().includes(`projects/${pid}/generate/`), 'the plan card opens the outline in the generation page');
await pane();
await p.locator('.chat-card.plan [data-approve="1"]').click();
await p.waitForSelector('.chat-msg.bot:has-text("Fiz a apresentação.")', { timeout: 60000 });
check(true, 'approved in the chat, the deck is made');

if (lang === 'pt') await recordMisses(p);
for (const x of p.problems) problems.push(x);
await b.close();
console.log(problems.length ? `PROBLEMS:\n${problems.join('\n')}` : 'M9 generate: no problems');
process.exit(problems.length ? 1 : 0);
