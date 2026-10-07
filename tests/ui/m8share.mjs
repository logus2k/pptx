// M8's sharing check (technical design section 13, M8 "Done when": sharing with two users, the lease shown and
// enforced), through the page with two people in two browsers: Ana shares her project with Rui as editor; while Ana
// has the deck open, Rui's editor says it is being edited by her and changes nothing (its buttons off, the server
// refusing); Ana closes it and Rui can edit; in their shared conversation Rui sees who wrote Ana's message.
//   SLIDES_URL=http://localhost:2722/ SLIDES_PROXY_SECRET=e2e-secret node tests/ui/m8share.mjs [width] [theme]
import { launch, open, authHeaders, BASE } from './lib.mjs';
import { mkdirSync, writeFileSync } from 'node:fs';

const [width = '1440', theme = 'light'] = process.argv.slice(2);
const W = Number(width);
const out = new URL('./out/', import.meta.url).pathname;
mkdirSync(out, { recursive: true });
const FIX = new URL('../../fixtures/decks/', import.meta.url).pathname;
const SCRIPT = new URL('../e2e/out/script.json', import.meta.url).pathname;
const stamp = Date.now();
const ana = `ana-${stamp}@example.com`;
const rui = `rui-${stamp}@example.com`;
const problems = [];
const check = (ok, what) => { if (!ok) problems.push(what); console.log(`${ok ? 'ok  ' : 'FAIL'} ${what}`); };
const shot = (p, step) => p.screenshot({ path: `${out}m8share-${W}-${theme}-${step}.png` });

const b = await launch();
const pa = await open(b, ana, { width: W, height: 900, storage: { 'slides.theme': theme, 'slides.uiLanguage': 'en' } });
await pa.waitForSelector('.identity-btn');
await pa.locator('.sb-view button', { hasText: 'New project' }).click();
await pa.locator('.jsPanel input').first().fill('Shared proposal');
await pa.locator('.jsPanel button.primary', { hasText: 'Create' }).click();
await pa.waitForSelector('.page h1:text("Shared proposal")');
const pid = new URL(pa.url()).pathname.split('/').filter(Boolean).at(-1);

// Ana adds Rui as editor, from the project's Members section
await pa.locator('button', { hasText: 'Add a member' }).click();
await pa.locator('.jsPanel input').first().fill(rui);
await pa.locator('.jsPanel select').selectOption('editor');
await pa.locator('.jsPanel button.primary', { hasText: 'Add' }).click();
await pa.waitForSelector(`.members-list .list-title:text("${rui}")`, { timeout: 10000 });
check(true, 'Ana added Rui from the Members section');
await shot(pa, '1-members');

// Ana uploads a deck: her editor opens and holds it
const chooser = pa.waitForEvent('filechooser');
await pa.locator('button', { hasText: 'Upload a presentation' }).click();
await (await chooser).setFiles(`${FIX}simple.pptx`);
await pa.waitForSelector('.slide-strip .strip-item');
const did = new URL(pa.url()).pathname.split('/').filter(Boolean).at(-1);
check(!(await pa.locator('.lease-note').count()), "Ana's editor is hers: no note");
check(await pa.locator(".editor-bar [data-action=\"delete-slide\"]").isEnabled(), "Ana's editor can delete a slide");

// Rui: the project is in his list; the deck open in Ana's editor is shown as hers, and nothing can be changed
const pr = await open(b, rui, { width: W, height: 900, storage: { 'slides.theme': theme, 'slides.uiLanguage': 'en' }, path: `projects/${pid}/decks/${did}` });
await pr.waitForSelector('.slide-strip .strip-item', { timeout: 30000 });
await pr.waitForSelector('.lease-note', { timeout: 10000 }).catch(() => {});
const note = await pr.locator('.lease-note').textContent().catch(() => '');
check(note.includes('Being edited by') && note.includes(ana), `Rui's editor says the deck is being edited by Ana ("${note.trim().replaceAll('\n', ' ')}")`);
for (const action of ['delete-slide', 'undo', 'rename']) {
  check(!(await pr.locator(`.editor-bar [data-action="${action}"]`).isEnabled()), `Rui's ${action} button is off`);
}
check(!(await pr.locator(".editor-bar [data-action=\"edit-text\"]").isEnabled()), "Rui's Edit text button is off");
await shot(pr, '2-rui-held');
const deck = await (await pr.request.fetch(`${BASE}api/projects/${pid}/decks/${did}`, { headers: authHeaders(rui) })).json();
const refused = await pr.request.fetch(`${BASE}api/projects/${pid}/decks/${did}/edits`, {
  method: 'POST', headers: { ...authHeaders(rui), 'Content-Type': 'application/json' },
  data: JSON.stringify({ base_version: deck.version, op: 'delete', slide_id: deck.slides[1].id }),
});
check(refused.status() === 409, `the server refuses Rui's change while Ana holds the deck (${refused.status()})`);
const list = await (await pr.request.fetch(`${BASE}api/projects`, { headers: authHeaders(rui) })).json();
check(list.projects.some((x) => x.id === pid && x.role === 'editor'), 'the project is in Rui\'s list, as editor');

// Ana writes in the conversation; Rui sees it with her address (on a tablet the pane is opened from its menu, as m3)
writeFileSync(SCRIPT, JSON.stringify([{ text: 'Noted.' }, { text: 'Noted.' }]));
async function pane(p) {
  if (await p.locator('.assistant textarea').isVisible()) return;
  await p.locator('#menu-toggle').click();
  await p.locator('#menubar .menu-btn', { hasText: 'Assistant' }).click();
  await p.locator('#menubar .menu-item', { hasText: 'Show the assistant' }).click();
  await p.waitForSelector('.assistant textarea', { state: 'visible', timeout: 5000 });
}
await pane(pa);
await pa.locator('.assistant textarea').fill('Please keep the agenda short.');
await pa.locator('.assistant textarea').press('Enter');
await pa.waitForSelector('.chat-msg.bot:has-text("Noted.")', { timeout: 30000 });

// Ana closes the deck: Rui's editor, reloaded, is his to change (on a tablet the pane over the editor is closed first)
const closePane = pa.locator('#right-panel button[title="Close panel"]:visible');
if (W < 1280 && await closePane.count()) await closePane.first().click();
await pa.locator('.main-tab.active .main-tab-close').click();
await pa.waitForTimeout(1000);
const held = await (await pr.request.fetch(`${BASE}api/projects/${pid}/decks/${did}`, { headers: authHeaders(rui) })).json();
check(held.lease === null, 'closing the deck released it');
await pr.reload({ waitUntil: 'networkidle' });
await pr.waitForSelector('.slide-strip .strip-item', { timeout: 30000 });
await pr.waitForTimeout(500);
check(!(await pr.locator('.lease-note').count()), "Rui's editor has no note once Ana closed the deck");
check(await pr.locator(".editor-bar [data-action=\"delete-slide\"]").isEnabled(), 'Rui can now delete a slide');
await pane(pr);
const conv = pr.locator('.assistant select');
if (await conv.count()) {
  const options = await conv.locator('option').allTextContents();
  const shared = options.findIndex((t) => t.includes('agenda'));
  if (shared >= 0) await conv.selectOption({ index: shared });
}
await pr.waitForSelector('.chat-msg .chat-author', { timeout: 10000 }).catch(() => {});
const author = await pr.locator('.chat-msg .chat-author').first().textContent().catch(() => '');
check(author === ana, `Rui sees who wrote Ana's message (${author || 'nothing'})`);
await shot(pr, '3-rui-free');

for (const x of [...pa.problems, ...pr.problems]) if (!x.includes('409')) problems.push(x);
await b.close();
console.log(problems.length ? `PROBLEMS:\n${problems.join('\n')}` : 'M8 sharing: no problems');
process.exit(problems.length ? 1 : 0);
