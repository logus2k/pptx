// M8's archive check (spec PJ-14, "done when": a lossless round trip, checked file by file in the backend tests),
// through the page: a project's "Export project" downloads its archive; "Import a project" makes it a new project
// of the person's, opened at once, with its deck and instructions; a file that is not an archive is refused, said.
//   SLIDES_URL=http://localhost:2722/ SLIDES_PROXY_SECRET=e2e-secret node tests/ui/m8archive.mjs [width] [theme]
import { launch, open, authHeaders, BASE } from './lib.mjs';
import { mkdirSync, writeFileSync } from 'node:fs';

const [width = '1440', theme = 'light'] = process.argv.slice(2);
const W = Number(width);
const out = new URL('./out/', import.meta.url).pathname;
mkdirSync(out, { recursive: true });
const FIX = new URL('../../fixtures/decks/', import.meta.url).pathname;
const problems = [];
const check = (ok, what) => { if (!ok) problems.push(what); console.log(`${ok ? 'ok  ' : 'FAIL'} ${what}`); };

const b = await launch();
const me = `arc-${Date.now()}@example.com`;
const p = await open(b, me, { width: W, height: 900, storage: { 'slides.theme': theme, 'slides.uiLanguage': 'en' } });
await p.waitForSelector('.identity-btn');
await p.locator('.sb-view button', { hasText: 'New project' }).click();
await p.locator('.jsPanel input').first().fill('Archived');
await p.locator('.jsPanel button.primary', { hasText: 'Create' }).click();
await p.waitForSelector('.page h1:text("Archived")');
await p.locator('[data-field="instructions"]').fill('Prices in EUR.');
await p.locator('button', { hasText: 'Save instructions' }).click();
const chooser = p.waitForEvent('filechooser');
await p.locator('button', { hasText: 'Upload a presentation' }).click();
await (await chooser).setFiles(`${FIX}simple.pptx`);
await p.waitForSelector('.slide-strip .strip-item');
await p.locator('.main-tab', { hasText: 'Archived' }).click();
// the link, fetched as the browser does with the proxy's sign-in (headless downloads here do not carry the test's
// identity headers: m1 checks Download the same way)
const href = await p.locator('a', { hasText: 'Export project' }).getAttribute('href');
const pid = new URL(p.url()).pathname.split('/').filter(Boolean).at(-1);
check(href === `api/projects/${pid}/export` && await p.locator('a', { hasText: 'Export project' }).getAttribute('download') !== null, 'the page links to the project\'s archive');
const fetched = await p.request.fetch(`${BASE}${href}`, { headers: authHeaders(me) });
const zip = `${out}m8archive-${W}-${theme}.zip`;
writeFileSync(zip, await fetched.body());
check(fetched.headers()['content-disposition'] === 'attachment; filename="Archived.zip"', `the archive downloads as Archived.zip (${fetched.headers()['content-disposition']})`);

async function projectsPanel() {  // the side menu's Projects entry opens the panel when it is closed
  if (!(await p.locator('.sb-view button', { hasText: 'Import a project' }).isVisible())) {
    await p.locator('.icon-bar-btn[data-key="projects"]').click();
    await p.waitForSelector('.sb-view button:has-text("Import a project")', { state: 'visible', timeout: 5000 });
  }
}
await projectsPanel();
const picker = p.waitForEvent('filechooser');
await p.locator('.sb-view button', { hasText: 'Import a project' }).click();
await (await picker).setFiles(zip);
await p.waitForFunction(() => document.querySelectorAll('.sb-view .list li').length === 2, null, { timeout: 30000 });
const shown = p.locator('.page:visible');  // the imported project's page (the original, also "Archived", is behind its tab)
await p.waitForFunction((old) => !location.pathname.endsWith(old), pid, { timeout: 10000 });
await shown.locator('h1:text("Archived")').waitFor({ timeout: 10000 });
check(new URL(p.url()).pathname.split('/').filter(Boolean).at(-1) !== pid, 'the imported project opens, a new project');
await shown.locator('.deck-card').first().waitFor({ timeout: 10000 }).catch(() => {});
check(await shown.locator('.deck-card').count() === 1, 'it has the deck');
check(await shown.locator('[data-field="instructions"]').inputValue() === 'Prices in EUR.', 'and the instructions');
await p.screenshot({ path: `${out}m8archive-${W}-${theme}-imported.png` });

writeFileSync(`${out}not-an-archive.zip`, 'nothing');
await projectsPanel();
const again = p.waitForEvent('filechooser');
await p.locator('.sb-view button', { hasText: 'Import a project' }).click();
await (await again).setFiles(`${out}not-an-archive.zip`);
await p.waitForSelector('.jsPanel:has-text("Import a project")', { timeout: 10000 }).catch(() => {});
const said = await p.locator('.jsPanel').last().textContent().catch(() => '');
check(said.includes('not a ZIP archive'), `a file that is not an archive is refused, said (${said.slice(0, 80)})`);
for (const x of p.problems) if (!x.includes('422')) problems.push(x);
await b.close();
console.log(problems.length ? `PROBLEMS:\n${problems.join('\n')}` : 'M8 archive: no problems');
process.exit(problems.length ? 1 : 0);
