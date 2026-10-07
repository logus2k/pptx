// M5's browser check, spec scenario S3 (hands busy): a spoken request, from a recording played by Chrome's fake
// microphone, comes back as text in the composer; sent, the assistant edits; its reply is read aloud; pressing the
// microphone while it speaks stops it (barge-in). The speech services are the e2e app's stand-ins
// (tests/e2e/fake_app.py: the recogniser answers only audio it heard, the speaker keeps what it was asked to say).
//   SLIDES_URL=http://localhost:2722/ SLIDES_PROXY_SECRET=e2e-secret node tests/ui/m5.mjs [width] [theme] [lang]
import { launch, open, overflow, recordMisses, authHeaders, BASE } from './lib.mjs';
import { existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';

const [width = '1440', theme = 'light', lang = 'pt'] = process.argv.slice(2);
const W = Number(width);
const out = new URL('./out/', import.meta.url).pathname;
mkdirSync(out, { recursive: true });
const E2E = new URL('../e2e/out/', import.meta.url).pathname;
const SCRIPT = `${E2E}script.json`;
const FIX = new URL('../../fixtures/', import.meta.url).pathname;
const user = `m5-${Date.now()}@example.com`;
const problems = [];
const check = (ok, what) => { if (!ok) problems.push(what); console.log(`${ok ? 'ok  ' : 'FAIL'} ${what}`); };
const shot = (p, step) => p.screenshot({ path: `${out}m5-${W}-${theme}${lang === 'pt' ? '' : `-${lang}`}-${step}.png` });
const json = (name) => (existsSync(`${E2E}${name}`) ? JSON.parse(readFileSync(`${E2E}${name}`, 'utf8')) : []);
for (const f of ['stt.json', 'tts.json']) rmSync(`${E2E}${f}`, { force: true });
const SAID = 'Aumenta o título e lê-me o que está no diapositivo seguinte.';
writeFileSync(`${E2E}stt.txt`, SAID);

const b = await launch({ audio: `${FIX}audio/s3-pt.wav` });
const p = await open(b, user, { width: W, height: 900, storage: { 'slides.theme': theme, 'slides.uiLanguage': lang } });
await p.waitForSelector('.identity-btn');
const call = async (path, init = {}) => (await p.request.fetch(`${BASE}api/${path}`, { headers: authHeaders(user), ...init })).json();
const project = await call('projects', { method: 'POST', data: { name: 'Voice check' } });
const deck = await call(`projects/${project.id}/decks`, { method: 'POST', multipart: {
  file: { name: 'features.pptx', mimeType: 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
    buffer: readFileSync(`${FIX}decks/features.pptx`) } } });
await p.goto(`${BASE}projects/${project.id}/decks/${deck.id}`, { waitUntil: 'networkidle' });
await p.waitForSelector('.slide-strip .strip-item');
if (!(await p.locator('.assistant textarea').isVisible())) {
  await p.locator('#menu-toggle').click();
  await p.locator('#menubar .menu-btn', { hasText: lang === 'pt' ? 'Assistente' : 'Assistant' }).click();
  await p.locator('#menubar .menu-item', { hasText: lang === 'pt' ? 'Mostrar o assistente' : 'Show the assistant' }).click();
}

// spoken replies on (a gesture: the browser lets the page play sound from now on)
await p.locator('[data-action="speaker"]').click();
check((await p.locator('[data-action="speaker"]').getAttribute('aria-pressed')) === 'true', 'spoken replies are on');

// hold the microphone while the recording plays, then let go: the words land in the composer, not sent
const mic = p.locator('[data-action="mic"]');
await mic.hover();
await p.mouse.down();
await p.waitForSelector('[data-action="mic"].active', { timeout: 10000 });
await shot(p, '1-listening');
await p.waitForTimeout(4500);
await p.mouse.up();
await p.waitForFunction((t) => document.querySelector('.assistant textarea').value === t, SAID, { timeout: 15000 }).catch(() => {});
check((await p.locator('.assistant textarea').inputValue()) === SAID, 'the spoken request is in the composer, to check before sending');
const heard = json('stt.json').at(-1) || {};
check(heard.seconds > 3 && heard.dbfs > -50, `the recogniser got the recording (${heard.seconds} s at ${heard.dbfs} dBFS)`);
check(heard.language === lang && (heard.prompt || '').startsWith('Preços por escalão'), `in the person's language, with the deck's words (${heard.language}; ${(heard.prompt || '').slice(0, 40)})`);
check(!(await p.locator('.chat-msg.me').count()), 'nothing was sent by speaking alone');

// sent: the assistant makes the title bigger and says what the next slide holds; the reply is read aloud
const reply = 'Aumentei o título do diapositivo 1. O diapositivo seguinte, Fotografia da linha de triagem, mostra uma fotografia.';
writeFileSync(SCRIPT, JSON.stringify([
  { tools: [['format_text', { slide_id: 1, shape_id: 2, style: { size_pt: 40 } }]] },
  { text: reply },
]));
await p.locator('.assistant textarea').press('Enter');
await p.waitForSelector('.chat-card.proposal', { timeout: 30000 });
await p.waitForFunction(() => window.slidesTts && window.slidesTts.speaking(), null, { timeout: 15000 }).catch(() => {});
const spoken = json('tts.json').filter((x) => x.text);
check(spoken.length === 1 && spoken[0].text === 'Aumentei o título do diapositivo 1.', `the reply's first sentence is read aloud (${JSON.stringify(spoken[0]?.text)})`);
check(spoken[0]?.voice === (lang === 'pt' ? 'pf_dora' : 'af_heart'), `in the language's voice (${spoken[0]?.voice})`);
check(await p.evaluate(() => window.slidesTts.speaking()), 'the audio is playing');
check(await p.locator('[data-action="speaker"].speaking').count() === 1, 'the speaker shows it is speaking');
await shot(p, '2-speaking');

// barge-in: pressing the microphone stops the reply at once (and listens)
await mic.click();
await p.waitForTimeout(300);
check(!(await p.evaluate(() => window.slidesTts.speaking())), 'pressing the microphone stops the reply');
check(json('tts.json').some((x) => x.stop), 'and tells the speech service to stop');
await mic.click();   // the second press: finish
await p.waitForTimeout(500);

if (await overflow(p)) problems.push('the page scrolls sideways');
for (const x of p.problems) problems.push(x);
await recordMisses(p);
await b.close();
console.log(problems.length ? `PROBLEMS:\n${problems.join('\n')}` : 'M5 end to end: no problems');
process.exit(problems.length ? 1 : 0);
