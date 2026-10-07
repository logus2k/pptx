// M7's browser check of hands-free voice (spec VO-2): turned on, it says so; a spoken request, from a recording with
// pauses played by Chrome's fake microphone, is found by the voice detector (frontend/js/assistant/vad.js), transcribed
// and sent with no button pressed; it waits while the assistant answers; turned off, it says so and the microphone
// closes. The speech services are the e2e app's stand-ins (tests/e2e/fake_app.py).
//   SLIDES_URL=http://localhost:2722/ SLIDES_PROXY_SECRET=e2e-secret node tests/ui/m7v.mjs [width] [theme] [lang]
import { launch, open, overflow, recordMisses, authHeaders, BASE } from './lib.mjs';
import { existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';

const [width = '1440', theme = 'light', lang = 'pt'] = process.argv.slice(2);
const W = Number(width);
const pt = lang === 'pt';
const L = pt
  ? { listening: 'Mãos livres ligado · a ouvir', off: 'Desligar', assistant: 'Assistente', show: 'Mostrar o assistente' }
  : { listening: 'Hands-free on · listening', off: 'Turn off', assistant: 'Assistant', show: 'Show the assistant' };
const out = new URL('./out/', import.meta.url).pathname;
mkdirSync(out, { recursive: true });
const E2E = new URL('../e2e/out/', import.meta.url).pathname;
const FIX = new URL('../../fixtures/', import.meta.url).pathname;
const user = `m7v-${Date.now()}@example.com`;
const problems = [];
const check = (ok, what) => { if (!ok) problems.push(what); console.log(`${ok ? 'ok  ' : 'FAIL'} ${what}`); };
const shot = (p, step) => p.screenshot({ path: `${out}m7v-${W}-${theme}${pt ? '' : `-${lang}`}-${step}.png` });
const json = (name) => (existsSync(`${E2E}${name}`) ? JSON.parse(readFileSync(`${E2E}${name}`, 'utf8')) : []);
rmSync(`${E2E}stt.json`, { force: true });
const SAID = 'Aumenta o título e lê-me o que está no diapositivo seguinte.';
writeFileSync(`${E2E}stt.txt`, SAID);
const REPLY = 'Combinado.';
writeFileSync(`${E2E}script.json`, JSON.stringify(Array.from({ length: 6 }, () => ({ text: REPLY }))));   // one per request heard

// 1.5 s of a quiet room, the request (4.3 s), 2.5 s of quiet, again and again
const b = await launch({ audio: `${FIX}audio/s3-pt-pauses.wav` });
const p = await open(b, user, { width: W, height: 900, storage: { 'slides.theme': theme, 'slides.uiLanguage': lang } });
await p.waitForSelector('.identity-btn');
const call = async (path, init = {}) => (await p.request.fetch(`${BASE}api/${path}`, { headers: authHeaders(user), ...init })).json();
const project = await call('projects', { method: 'POST', data: { name: 'Hands-free check' } });
const deck = await call(`projects/${project.id}/decks`, { method: 'POST', multipart: {
  file: { name: 'features.pptx', mimeType: 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
    buffer: readFileSync(`${FIX}decks/features.pptx`) } } });
await p.goto(`${BASE}projects/${project.id}/decks/${deck.id}`, { waitUntil: 'networkidle' });
await p.waitForSelector('.slide-strip .strip-item');
if (!(await p.locator('.assistant textarea').isVisible())) {
  await p.locator('#menu-toggle').click();
  await p.locator('#menubar .menu-btn', { hasText: L.assistant }).click();
  await p.locator('#menubar .menu-item', { hasText: L.show }).click();
}
await p.waitForSelector('.assistant textarea', { state: 'visible' });

// off at first; turned on, the bar says so
check(await p.locator('.hands-free-bar').isHidden(), 'hands-free is off at first, and no bar says otherwise');
await p.locator('[data-action="hands-free"]').click();
await p.waitForSelector('.hands-free-bar:not([hidden])', { timeout: 10000 });
check((await p.locator('[data-action="hands-free"]').getAttribute('aria-pressed')) === 'true', 'the button shows it is on');
check((await p.locator('.hands-free-text').textContent()).startsWith(pt ? 'Mãos livres ligado' : 'Hands-free on'), `the bar says it is on (${await p.locator('.hands-free-text').textContent()})`);
await shot(p, '1-on');

// the request is heard, transcribed and sent, with nothing pressed
await p.waitForSelector('.hands-free-bar.hearing', { timeout: 15000 }).catch(() => {});
check(await p.locator('.hands-free-bar.hearing').count() === 1, 'it hears the request start (the dot pulses)');
await shot(p, '2-hearing');
await p.waitForSelector(`.chat-msg.me:text("${SAID}")`, { timeout: 30000 }).catch(() => {});
check(await p.locator('.chat-msg.me', { hasText: SAID }).count() >= 1, 'the spoken request is sent as a message');
await p.waitForSelector(`.chat-msg:text("${REPLY}")`, { timeout: 30000 }).catch(() => {});
check(await p.locator('.chat-msg', { hasText: REPLY }).count() >= 1, 'and the assistant answers it');
const heard = json('stt.json')[0] || {};
check(heard.seconds > 3.5 && heard.seconds < 7.5, `the recogniser got the whole request, not the pauses around it (${heard.seconds} s)`);
check(heard.dbfs > -40, `at a voice's level (${heard.dbfs} dBFS)`);
check((await p.locator('.assistant textarea').inputValue()) === '', 'the composer is left empty');
await shot(p, '3-sent');

// turned off from the bar: it says so, and the microphone closes
await p.locator('.hands-free-bar button', { hasText: L.off }).click();
check(await p.locator('.hands-free-bar').isHidden(), 'turned off, the bar goes');
check((await p.locator('[data-action="hands-free"]').getAttribute('aria-pressed')) === 'false', 'the button shows it is off');
check(await p.evaluate(() => !window.slidesHandsFree.on && !window.slidesHandsFree.stream), 'the microphone is closed');
const requests = json('stt.json').length;
await p.waitForTimeout(9000);   // a whole loop of the recording: nothing more is heard
check(json('stt.json').length === requests, `nothing is transcribed once it is off (${requests} then ${json('stt.json').length})`);
check(json('stt.json').every((x) => x.seconds > 3.5), `no request was cut short, not even by turning it off (${json('stt.json').map((x) => x.seconds)})`);
check((await p.locator('.assistant textarea').inputValue()) === '', 'and nothing half-heard reaches the composer');

if (await overflow(p)) problems.push('the page scrolls sideways');
for (const x of p.problems) problems.push(x);
await recordMisses(p);
await b.close();
console.log(problems.length ? `PROBLEMS:\n${problems.join('\n')}` : 'M7 hands-free: no problems');
process.exit(problems.length ? 1 : 0);
