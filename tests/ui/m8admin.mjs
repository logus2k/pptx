// M8's administration (spec AD-4, AD-5, AD-6), through the page: someone who is not an administrator has no
// Administration in the side menu and is refused its routes; the administrator uploads a template, makes it the default
// and retires the old one (no longer offered to people), sees the usage per period and the audit log, filters it by
// person and downloads it as CSV.
//   SLIDES_URL=http://localhost:2722/ SLIDES_PROXY_SECRET=e2e-secret node tests/ui/m8admin.mjs [width] [theme] [lang]
import { launch, open, authHeaders, overflow, recordMisses, BASE } from './lib.mjs';
import { mkdirSync } from 'node:fs';

const [width = '1440', theme = 'light', lang = 'en'] = process.argv.slice(2);
const W = Number(width);
const out = new URL('./out/', import.meta.url).pathname;
mkdirSync(out, { recursive: true });
const FIX = new URL('../../fixtures/decks/', import.meta.url).pathname;
const stamp = Date.now();
const ADMIN = 'admin@example.com';
const rui = `rui-${stamp}@example.com`;
const problems = [];
const check = (ok, what) => { if (!ok) problems.push(what); console.log(`${ok ? 'ok  ' : 'FAIL'} ${what}`); };
const shot = (p, step) => p.screenshot({ path: `${out}m8admin-${W}-${theme}-${lang}-${step}.png`, fullPage: true });
const storage = { 'slides.theme': theme, 'slides.uiLanguage': lang };
const get = async (p, email, path) => (await p.request.fetch(`${BASE}api/${path}`, { headers: authHeaders(email) }));

const b = await launch();
// someone else: no Administration, and its routes refused
const pr = await open(b, rui, { width: W, height: 900, storage });
await pr.waitForSelector('.identity-btn');
check(!(await pr.locator('.icon-bar-btn[data-key^="admin-"]').count()), 'no Administration items for someone who is not an administrator');
for (const path of ['admin/templates', 'audit', 'usage']) check((await get(pr, rui, path)).status() === 403, `${path} is refused to them (403)`);
const created = await pr.request.fetch(`${BASE}api/projects`, { method: 'POST', headers: { ...authHeaders(rui), 'Content-Type': 'application/json' },
  data: JSON.stringify({ name: 'Rui project' }) });
check(created.status() === 201, 'they create a project (a change for the audit log)');

// the administrator: the side menu's Administration (a phone has no room for it in its bar: the address opens it)
const pa = await open(b, ADMIN, { width: W, height: 900, storage });
await pa.waitForSelector('.identity-btn');
// nothing cut off inside the page (the document not scrolling sideways is not enough: a tab beside the side panel is
// narrower than the screen): every button and text block fits within the page's own width
const clipped = () => pa.evaluate(() => {
  const page = document.querySelector('.main-tab-view:not([hidden]) .admin-page, .admin-page');
  const box = [...document.querySelectorAll('.admin-page')].find((x) => x.offsetParent) || page;
  const r = box.getBoundingClientRect();
  const bad = [...box.querySelectorAll('button, .list-title, .list-caption, td, .field-box')].filter((e) => e.offsetParent)
    .filter((e) => { const q = e.getBoundingClientRect(); return q.right > r.right + 1 || q.left < r.left - 1 || (q.width < 120 && e.matches('.list-caption')); });
  return bad.slice(0, 3).map((e) => `${e.tagName.toLowerCase()}.${e.className} "${e.textContent.trim().slice(0, 30)}"`)
    .concat(box.scrollWidth > box.clientWidth + 1 ? [`the page scrolls sideways (${box.scrollWidth} > ${box.clientWidth})`] : []);
});
async function go(area) {
  const item = pa.locator(`.icon-bar-btn[data-key="admin-${area}"]`);
  if (W >= 834) {
    if (W < 1280) await pa.locator('.menu-collapse').click();                  // the tablet's rail opens over the page
    await item.click();
  } else await pa.goto(`${BASE}admin/${area}`, { waitUntil: 'networkidle' });
  await pa.waitForSelector(`.main-tab.active`);
}
check((await pa.locator('.icon-bar-btn[data-key^="admin-"]').count()) === 3, 'the administrator has Templates, Usage and Audit log in the side menu');

// Templates (AD-4)
const before = await (await get(pa, ADMIN, 'admin/templates')).json();
const oldDefault = before.default;
await go('templates');
await pa.waitForSelector('.admin-templates li');
const chooser = pa.waitForEvent('filechooser');
await pa.locator('[data-action="upload"]').click();
await (await chooser).setFiles(`${FIX}simple.pptx`);
await pa.locator('.jsPanel input').first().fill(`Corporate ${stamp}`);
await pa.locator('.jsPanel button.primary').click();
const mine = pa.locator('.admin-templates li', { hasText: `Corporate ${stamp}` });
await mine.waitFor({ timeout: 30000 });
check(true, 'a template is uploaded from the page');
await mine.locator('[data-action="default"]').click();
await mine.locator('.pill').first().waitFor({ timeout: 10000 });
const old = pa.locator(`.admin-templates li[data-id="${oldDefault}"]`);
await old.locator('[data-action="retire"]').waitFor({ timeout: 10000 });
check(!(await mine.locator('[data-action="retire"]').count()), 'the default has no Retire');
await old.locator('[data-action="retire"]').click();
await pa.locator('.jsPanel button.danger').click();
await old.locator('[data-action="bring-back"]').waitFor({ timeout: 10000 });
check(true, 'the old default is retired, and can be brought back');
const offered = await (await get(pr, rui, 'templates')).json();
check(offered.default === (await mine.getAttribute('data-id')) && !offered.templates.some((t) => t.id === oldDefault),
  'people are offered the new default and no longer the retired one');
check(!(await overflow(pa)), 'Templates: no sideways scroll');
{ const c = await clipped(); check(!c.length, `Templates: nothing cut off or crushed in the page (${c.join('; ') || 'none'})`); }
await shot(pa, '1-templates');
// put back as it was (the following checks create decks from the default)
await old.locator('[data-action="bring-back"]').click();
await old.locator('[data-action="default"]').waitFor({ timeout: 10000 });
await old.locator('[data-action="default"]').click();
await mine.locator('[data-action="retire"]').waitFor({ timeout: 10000 });
check((await (await get(pa, ADMIN, 'admin/templates')).json()).default === oldDefault, 'the old template is the default again');

// Usage (AD-5)
await go('usage');
await pa.waitForSelector('.usage-table tbody tr', { timeout: 10000 });
const people = Number((await pa.locator('.usage-table tbody tr').first().locator('td').nth(1).innerText()).split('\n').at(-1));
check(people >= 1, `Usage: this period lists the people active (${people})`);
await pa.locator('[data-field="by"]').selectOption('month');
await pa.waitForTimeout(500);
check((await pa.locator('.usage-table tbody tr').count()) >= 1, 'Usage per month');
check(!(await overflow(pa)), 'Usage: no sideways scroll');
{ const c = await clipped(); check(!c.length, `Usage: nothing cut off or crushed in the page (${c.join('; ') || 'none'})`); }
await shot(pa, '2-usage');

// Audit log (AD-6)
await go('audit');
await pa.waitForSelector('.audit-table tbody tr', { timeout: 10000 });
await pa.locator('[data-field="user"]').selectOption(rui);
await pa.waitForTimeout(800);
const who = await pa.locator('.audit-table tbody tr td:nth-child(2) .notranslate').allTextContents();
check(who.length >= 1 && who.every((x) => x === rui), `Audit log filtered by person: only their changes (${who.length})`);
const target = await pa.locator('.audit-table tbody tr .audit-target').first().textContent();
check(target.includes('pid: ') && !target.includes('Rui project'), 'which data: identifiers, never the names written');
check(!(await overflow(pa)), 'Audit log: no sideways scroll');
{ const c = await clipped(); check(!c.length, `Audit log: nothing cut off or crushed in the page (${c.join('; ') || 'none'})`); }
await shot(pa, '3-audit');
const csv = await get(pa, ADMIN, `audit.csv?user=${encodeURIComponent(rui)}`);
const lines = (await csv.text()).trim().split('\n');
check(csv.status() === 200 && lines.length >= 2 && lines.slice(1).every((l) => l.includes(rui)), `the CSV has the same filter (${lines.length - 1} rows)`);

if (lang === 'pt') await recordMisses(pa);
for (const x of [...pa.problems, ...pr.problems]) if (!x.includes('403')) problems.push(x);
await b.close();
console.log(problems.length ? `PROBLEMS:\n${problems.join('\n')}` : 'M8 administration: no problems');
process.exit(problems.length ? 1 : 0);
