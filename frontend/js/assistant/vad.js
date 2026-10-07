// Voice-activity detection for the hands-free mode (spec VO-2): the level of each ~100 ms PCM16 frame from the
// microphone's worklet, measured as Cortex measures its input meter (static/js/recording/app.js: RMS in dBFS), against
// the room's noise floor, which it follows (down at once, up slowly). Speech starts after START_FRAMES frames above
// the floor + MARGIN_DB, and the frames just before it are sent too (the first syllable rises from the noise); it ends
// after END_FRAMES frames below, or at MAX_FRAMES. No dependency: plain arithmetic over the samples.
export const FRAME_MS = 100;
export const START_FRAMES = 2;      // 200 ms of voice: a cough or a click is not a request
export const END_FRAMES = 9;        // 900 ms of quiet ends the request
export const PREROLL_FRAMES = 3;    // 300 ms sent from before the start
export const MAX_FRAMES = 300;      // 30 s: then it is sent as it is
export const MARGIN_DB = 12;        // voice is this much above the room's noise
export const FLOOR_MIN_DB = -75;
export const FLOOR_MAX_DB = -35;    // a noisy room still needs a voice above it
export const CALIBRATE_FRAMES = 5;  // the first 500 ms only learn the room (measured: a -45 dBFS room, against a
                                    // starting floor of -60, started a "request" of noise at once)
const FLOOR_RISE_DB = 0.05;         // per frame: the floor follows a noisier room in ~20 s, never a voice

export function levelDb(pcm) {
  if (!pcm.length) return -Infinity;
  let sum = 0;
  for (let i = 0; i < pcm.length; i += 1) sum += pcm[i] * pcm[i];
  return 20 * Math.log10(Math.sqrt(sum / pcm.length) / 32768 + 1e-9);
}

/** feed(frame): returns nothing; calls onStart(preroll frames), onAudio(frame) while speaking, onEnd(reason). */
export class Vad {
  constructor({ onStart, onAudio, onEnd }) {
    Object.assign(this, { onStart, onAudio, onEnd });
    this.floor = null;
    this.calibrating = CALIBRATE_FRAMES;
    this.reset();
  }

  reset() {
    this.speaking = false;
    this.loud = 0;
    this.quiet = 0;
    this.frames = 0;
    this.recent = [];
  }

  feed(pcm) {
    const db = levelDb(pcm);
    if (this.calibrating > 0) {   // the room's level: the quietest frame heard while turning on
      this.calibrating -= 1;
      this.floor = Math.min(FLOOR_MAX_DB, Math.max(FLOOR_MIN_DB, this.floor === null ? db : Math.min(this.floor, db)));
      return;
    }
    const threshold = this.floor + MARGIN_DB;
    if (!this.speaking) {
      // the floor learns only from what is not speech
      this.floor = Math.min(FLOOR_MAX_DB, Math.max(FLOOR_MIN_DB, db < this.floor ? db : this.floor + FLOOR_RISE_DB));
      this.recent.push(pcm);
      if (this.recent.length > PREROLL_FRAMES + START_FRAMES) this.recent.shift();
      this.loud = db > threshold ? this.loud + 1 : 0;
      if (this.loud >= START_FRAMES) {
        this.speaking = true;
        this.quiet = 0;
        this.frames = this.recent.length;
        this.onStart(this.recent);
        this.recent = [];
      }
      return;
    }
    this.onAudio(pcm);
    this.frames += 1;
    this.quiet = db > threshold - 3 ? 0 : this.quiet + 1;   // 3 dB of hysteresis: a soft word does not end it
    if (this.quiet >= END_FRAMES || this.frames >= MAX_FRAMES) {
      const reason = this.quiet >= END_FRAMES ? 'silence' : 'length';
      this.reset();
      this.onEnd(reason);
    }
  }
}
