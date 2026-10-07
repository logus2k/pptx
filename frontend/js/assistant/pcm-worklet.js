// Slides: copied verbatim from Cortex (static/js/recording/pcm-worklet.js).
// Captures mono audio at the AudioContext rate, resamples it to 16 kHz
// (linear interpolation) and posts PCM16 ArrayBuffers of ~100 ms.
class PcmResampler extends AudioWorkletProcessor {
  constructor() {
    super();
    this.ratio = sampleRate / 16000;  // input samples per output sample
    this.pos = 0;                     // fractional read position into `prev`+input
    this.prev = 0;                    // last input sample of the previous block
    this.out = new Int16Array(1600);
    this.n = 0;
  }

  process(inputs) {
    const ch = inputs[0] && inputs[0][0];
    if (!ch) return true;
    // Sample at virtual index i: i=-1 -> prev, i>=0 -> ch[i].
    const at = (i) => (i < 0 ? this.prev : ch[i]);
    while (this.pos < ch.length - 1) {
      const i = Math.floor(this.pos);
      const f = this.pos - i;
      const s = at(i) * (1 - f) + at(i + 1) * f;
      // same 1/32768 scale the server divides by
      this.out[this.n++] = Math.max(-32768, Math.min(32767, Math.round(s * 32768)));
      if (this.n === this.out.length) {
        this.port.postMessage(this.out.buffer, [this.out.buffer]);
        this.out = new Int16Array(1600);
        this.n = 0;
      }
      this.pos += this.ratio;
    }
    this.pos -= ch.length;
    this.prev = ch[ch.length - 1];
    return true;
  }
}

registerProcessor('pcm-resampler', PcmResampler);
