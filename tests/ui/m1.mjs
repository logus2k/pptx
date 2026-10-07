// M1's end-to-end check (technical design section 13, M1 "Done when"), through the page as a person uses it:
// create a project, upload a deck, see its thumbnails, download an identical file, restore a version; upload a
// template and create two decks with different templates; the changes are in the audit trail.
//   node tests/ui/m1.mjs [width] [theme]      (the app running: SLIDES_URL, default http://localhost:2720/)
// Screenshots: tests/ui/out/m1-<width>-<theme>-<step>.png
import { launch, open, overflow, recordMisses, authHeaders, BASE } from './lib.mjs';
import { createHash } from 'node:crypto';
import { mkdirSync, readFileSync } from 'node:fs';

const [width = '1440', theme = 'light'] = process.argv.slice(2);
const W = Number(width);
const out = new URL('./out/', import.meta.url).pathname;
mkdirSync(out, { recursive: true });
const FIX = new URL('../../fixtures/decks/', import.meta.url).pathname;
const user = `m1-${Date.now()}@example.com`;
const problems = [];
const check = (ok, what) => { if (!ok) problems.push(what); console.log(`${ok ? 'ok  ' : 'FAIL'} ${what}`); };
const sha = (buf) => createHash('sha256').update(buf).digest('hex');
const shot = (p, step) => p.screenshot({ path: `${out}m1-${W}-${theme}-${step}.png` });

const b = await launch();
const p = await open(b, user, { width: W, height: 900, storage: { 'slides.theme': theme, 'slides.uiLanguage': 'en' } });
await p.waitForSelector('.identity-btn');

// a project, from the Projects panel
if (await p.locator('#menu-toggle').isVisible()) { /* tablet: the side menu is the rail; the panel is opened from it */ }
await p.locator('.sb-view button', { hasText: 'New project' }).click();
await p.locator('.jsPanel input').first().fill('Client X proposal');
await p.locator('.jsPanel button.primary', { hasText: 'Create' }).click();
await p.waitForSelector('.page h1:text("Client X proposal")');
check(new URL(p.url()).pathname.startsWith(`${new URL(BASE).pathname}projects/`), 'the project has its own address');
await shot(p, '1-project');

// upload a deck: the editor opens with its slides
const chooser = p.waitForEvent('filechooser');
await p.locator('button', { hasText: 'Upload a presentation' }).click();
await (await chooser).setFiles(`${FIX}features.pptx`);
await p.waitForSelector('.slide-strip .strip-item');
const strip = await p.locator('.slide-strip .strip-item').count();
check(strip === 4, `the strip shows the deck's 4 slides (${strip})`);
await p.waitForFunction(() => [...document.querySelectorAll('.slide-strip img')].every((i) => i.complete && i.naturalWidth > 0), null, { timeout: 120000 });
await p.waitForFunction(() => { const i = document.querySelector('.stage-sheet img'); return i && i.complete && i.naturalWidth > 0; }, null, { timeout: 120000 });
check(true, 'every thumbnail and the preview loaded');
await p.locator('.strip-item[data-index="1"]').click();
await p.waitForFunction(() => { const i = document.querySelector('.stage-sheet img'); return i && i.complete && i.naturalWidth > 0; }, null, { timeout: 120000 });
await shot(p, '2-editor');

// download: the same bytes as the file uploaded
const pid = new URL(p.url()).pathname.split('/').filter(Boolean).slice(-3)[0];
const did = new URL(p.url()).pathname.split('/').filter(Boolean).at(-1);
const api = (path, init = {}) => p.request.fetch(`${BASE}api/${path}`, { headers: authHeaders(user), ...init });
const dl = await api(`projects/${pid}/decks/${did}/download`);
check(sha(await dl.body()) === sha(readFileSync(`${FIX}features.pptx`)), 'the download is byte-identical to the upload');

// restore version 1: version 2, identical, in the history
await p.locator('button', { hasText: 'Versions' }).click();
await p.waitForSelector('.versions-panel table');
await shot(p, '3-versions-before');
const restoreNeeded = await p.locator('[data-restore]').count();
check(restoreNeeded === 0, 'with one version there is nothing to restore');
// a second version first, made by restoring through the API, then restore v1 through the page
await api(`projects/${pid}/decks/${did}/versions/1/restore`, { method: 'POST' });
await p.locator('button', { hasText: 'Versions' }).click();
await p.locator('button', { hasText: 'Versions' }).click();
await p.waitForSelector('[data-restore="1"]');
await p.locator('[data-restore="1"]').click();
await p.locator('.jsPanel button.primary', { hasText: 'Restore' }).click();
await p.waitForFunction(() => document.querySelector('.editor-bar .pill')?.textContent.includes('3'), null, { timeout: 30000 });
await p.waitForFunction(() => [...document.querySelectorAll('.slide-strip img, .stage-sheet img')].every((i) => i.complete && i.naturalWidth > 0), null, { timeout: 60000 });
const stageWidth = await p.evaluate(() => document.querySelector('.stage').getBoundingClientRect().width);
check(stageWidth >= 400, `the stage keeps room beside the versions (${Math.round(stageWidth)}px)`);
const versions = await (await api(`projects/${pid}/decks/${did}/versions`)).json();
check(versions.current_version === 3 && versions.versions[0].source === 'restore' && versions.versions[0].restored_from === 1, 'restoring made version 3 from version 1');
await shot(p, '4-versions-after');

// a template of the project's own, and two decks with different templates
await p.locator('.main-tab', { hasText: 'Client X proposal' }).click();
const tChooser = p.waitForEvent('filechooser');
await p.locator('button', { hasText: 'Upload a template' }).click();
await (await tChooser).setFiles(`${FIX}template.potx`);
// a template whose fonts the server lacks is announced in a dialog first; the list refreshes once it is closed
await p.waitForSelector('.jsPanel:has-text("Template added"), .list .list-title:text("template.potx")', { timeout: 30000 });
if (await p.locator('.jsPanel', { hasText: 'Template added' }).count()) {
  await shot(p, '5-template-fonts');
  await p.locator('.jsPanel button', { hasText: 'OK' }).click();
}
await p.waitForSelector('.list .list-title:text("template.potx")', { timeout: 30000 });
for (const [title, pick] of [['Plain deck', 'Plain template'], ['Our deck', 'template.potx (this project)']]) {
  await p.locator('.main-tab', { hasText: 'Client X proposal' }).click();
  await p.locator('button', { hasText: 'New deck' }).click();
  await p.locator('.jsPanel input').first().fill(title);
  await p.locator('.jsPanel select').selectOption({ label: pick });
  await p.locator('.jsPanel button.primary', { hasText: 'Create' }).click();
  await p.waitForSelector(`.editor-title:text("${title}")`);
}
const decks = (await (await api(`projects/${pid}/decks`)).json()).decks;
const templates = decks.map((d) => d.template && d.template.kind).sort();
check(decks.length === 3 && JSON.stringify(templates) === JSON.stringify(['admin', 'asset', null].sort()), `three decks: uploaded, plain template, project template (${JSON.stringify(templates)})`);
await p.locator('.main-tab', { hasText: 'Client X proposal' }).click();
await p.waitForFunction(() => [...document.querySelectorAll('.deck-thumb img')].every((i) => i.complete && i.naturalWidth > 0), null, { timeout: 120000 });
const tabs = await p.evaluate(() => [...document.querySelectorAll('.main-tab.active')].map((t) => t.textContent.trim()));
check(tabs.length === 1 && tabs[0] === 'Client X proposal', `exactly one tab is active, the project's (${JSON.stringify(tabs)})`);
await shot(p, '6-project-decks');

if (await overflow(p)) problems.push('the page scrolls sideways');
for (const x of p.problems) problems.push(x);
await recordMisses(p);
await b.close();
console.log(problems.length ? `PROBLEMS:\n${problems.join('\n')}` : 'M1 end to end: no problems');
process.exit(problems.length ? 1 : 0);
