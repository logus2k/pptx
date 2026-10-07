// M0's design check (technical design section 13): the page in Light and Dark at the design system's widths, the
// home and the design-system page, the user menu and the Preferences dialog; screenshots to look at, plus the checks
// a screenshot cannot make: page errors, failed requests, sideways overflow, untranslated text.
//   node tests/ui/shots.mjs [widths] [themes]      (the app must be running: SLIDES_URL, default http://localhost:2720/)
// Screenshots: tests/ui/out/<width>-<theme>-<scene>.png
import { launch, open, overflow, recordMisses } from './lib.mjs';
import { mkdirSync } from 'node:fs';

const [widths = '375,834,1280,1440', themes = 'light,dark', lang = 'pt'] = process.argv.slice(2);
const out = new URL('./out/', import.meta.url).pathname;
mkdirSync(out, { recursive: true });
const b = await launch();
let bad = 0;

// the labels as the page shows them, in the language under test (plain strings: Playwright matches a substring)
const L = lang === 'pt' ? { help: 'Ajuda', design: 'Sistema de design', prefs: 'Preferências' }
                        : { help: 'Help', design: 'Design system', prefs: 'Preferences' };
const SCENES = {
  home: async () => {},
  design: async (p) => {
    // tablet and phone: the menus are in a drawer behind the top bar's menu button (layout.css)
    if (await p.locator('#menu-toggle').isVisible()) await p.locator('#menu-toggle').click();
    await p.locator('#menubar .menu-btn', { hasText: L.help }).click();
    await p.locator('#menubar .menu-item', { hasText: L.design }).click();
    await p.waitForTimeout(300);
  },
  menu: async (p) => { await p.locator('.identity-btn').click(); await p.waitForTimeout(200); },
  prefs: async (p) => {
    await p.locator('.identity-btn').click();
    await p.locator('.identity-item', { hasText: L.prefs }).click();
    await p.waitForTimeout(400);
  },
};

for (const w of widths.split(',').map(Number)) {
  for (const t of themes.split(',')) {
    for (const [name, scene] of Object.entries(SCENES)) {
      if (w < 834 && (name === 'design' || name === 'menu' || name === 'prefs')) continue;   // phones: list and home only
      // the design page scrolls inside its pane: a tall window shows all of it in one screenshot
      const p = await open(b, 'ana.costa@example.com', { width: w, height: name === 'design' ? 3400 : w < 834 ? 812 : 900,
        storage: { 'slides.theme': t, 'slides.uiLanguage': lang } });
      try {
        await p.waitForSelector('.identity-btn', { timeout: 10000 });
        await scene(p);
        await p.screenshot({ path: `${out}${w}-${t}-${name}.png` });
        if (await overflow(p)) p.problems.push('the page scrolls sideways');
      } catch (e) {
        p.problems.push(`scene failed: ${e.message.split('\n')[0]}`);
      }
      if (p.problems.length) { bad++; console.log(`${w} ${t} ${name}:`, p.problems.join(' | ')); }
      await recordMisses(p);
      await p.context().close();
    }
  }
}
await b.close();
console.log(bad ? `${bad} scene(s) with problems` : 'no problems found');
process.exit(bad ? 1 : 0);
