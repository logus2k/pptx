// The hands-free voice detector (frontend/js/assistant/vad.js) on synthetic audio: 100 ms frames of noise and of a
// tone at chosen levels. Run: node tests/ui/vad.test.mjs (make e2e runs it first).
import { Vad, levelDb, FRAME_MS, MAX_FRAMES } from '../../frontend/js/assistant/vad.js';

const problems = [];
const check = (ok, what) => { if (!ok) problems.push(what); console.log(`${ok ? 'ok  ' : 'FAIL'} ${what}`); };
let seed = 7;
const rand = () => { seed = (seed * 1103515245 + 12345) % 2147483648; return seed / 2147483648 - 0.5; };
/** A frame at `db` dBFS: noise, or a 220 Hz tone (a voice's level and steadiness, not its sound). */
function frame(db, tone = false) {
  const n = (16000 * FRAME_MS) / 1000;
  const amp = 32768 * 10 ** (db / 20) * (tone ? Math.SQRT2 : Math.sqrt(12));
  const out = new Int16Array(n);
  for (let i = 0; i < n; i += 1) out[i] = Math.round(tone ? amp * Math.sin((2 * Math.PI * 220 * i) / 16000) : amp * rand());
  return out;
}

check(Math.abs(levelDb(frame(-30, true)) + 30) < 0.5, `a -30 dBFS tone measures ${levelDb(frame(-30, true)).toFixed(1)} dBFS`);

function run(frames) {
  const events = [];
  let i = 0;
  const vad = new Vad({
    onStart: (pre) => events.push(['start', pre.length, i]),
    onAudio: () => events.push(['audio']),
    onEnd: (why) => events.push(['end', why]),
  });
  for (const f of frames) { vad.feed(f); i += 1; }
  return events;
}
const quiet = (n, db = -62) => Array.from({ length: n }, () => frame(db));
const voice = (n, db = -28) => Array.from({ length: n }, () => frame(db, true));

let e = run(quiet(50));
check(e.length === 0, 'a quiet room: nothing starts');

e = run([...quiet(30), frame(-20, true), ...quiet(30)]);
check(e.length === 0, 'a 100 ms click: nothing starts');

e = run([...quiet(30), ...voice(20), ...quiet(15)]);
const start = e.findIndex((x) => x[0] === 'start');
check(start === 0 && e[0][1] === 5 && e[0][2] === 31, `speech starts once, 200 ms into it, with the 300 ms before (${JSON.stringify(e[0])})`);
check(e.filter((x) => x[0] === 'end').length === 1 && e.at(-1)[1] === 'silence', 'and ends once, on silence');
const sent = e.filter((x) => x[0] === 'audio').length;
check(sent === 18 + 9, `every frame after the start is sent, through the 900 ms of quiet (${sent})`);

e = run([...quiet(30), ...voice(10), ...quiet(5), ...voice(10), ...quiet(12)]);
check(e.filter((x) => x[0] === 'start').length === 1, 'a half-second pause in a sentence does not end it');

e = run([...quiet(30), ...voice(MAX_FRAMES + 20)]);
check(e.some((x) => x[0] === 'end' && x[1] === 'length'), 'a request longer than 30 s is ended and sent');

e = run([...quiet(250, -45), ...voice(20, -40), ...quiet(15, -45)]);
check(e.filter((x) => x[0] === 'start').length === 0, 'in a noisy room (-45 dBFS) a voice 5 dB above it does not start');
e = run([...quiet(250, -45), ...voice(20, -25), ...quiet(15, -45)]);
const starts = e.filter((x) => x[0] === 'start');
check(starts.length === 1 && starts[0][2] === 251, `but one 20 dB above it does, when it speaks (${JSON.stringify(starts)})`);
e = run([...quiet(3, -45), ...quiet(40, -45)]);
check(e.length === 0, 'turned on in a noisy room: the room itself is never a request');

console.log(problems.length ? `PROBLEMS:\n${problems.join('\n')}` : 'voice detector: no problems');
process.exit(problems.length ? 1 : 0);
