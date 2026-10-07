// Spoken replies (technical design section 7; spec VO-3, VO-4): Cortex's `tts` player (static/js/recording/app.js),
// without its meeting parts. The browser connects to tts_server's own socket.io at /tts/socket.io through the domain
// proxy, registers as an audio client, sends the reply's short `speakable` text with the voice for the language, and
// plays the audio chunks in sequence as they arrive. stop() is the barge-in: the microphone calls it.
// The voices: tts_server's (Kokoro). Its Portuguese voice is Brazilian (technical design A-7).
const VOICES = { pt: 'pf_dora', en: 'af_heart' };

export const tts = {
  socket: null, ctx: null, queue: [], playing: null, onState: null,
  id: `slides-${Math.random().toString(36).slice(2, 10)}`,

  connect() {
    if (this.socket) return;
    // the environment's /tts/ route, at the site's root (this app is under /slides/)
    this.socket = io(location.origin, {
      path: '/tts/socket.io', transports: ['websocket'], forceNew: true, reconnectionAttempts: 3,
      query: { type: 'browser', format: 'binary', main_client_id: this.id },
    });
    this.socket.on('connect', () => this.socket.emit('register_audio_client', {
      main_client_id: this.id, connection_type: 'browser', mode: 'tts', format: 'binary' }));
    this.socket.on('connect_error', (e) => this.onState?.('error', `Speech unavailable: ${e.message}`));
    this.socket.on('tts_audio_chunk', (evt) => this.enqueue(evt.audio_buffer));
    this.socket.on('tts_error', (e) => this.onState?.('error', `Speech error: ${e.message || e.error || 'unknown'}`));
  },
  /** Inside a user gesture (the autoplay policy): the speaker button, the microphone. */
  unlock() {
    this.connect();
    if (!this.ctx) this.ctx = new AudioContext();
    if (this.ctx.state === 'suspended') this.ctx.resume();
  },
  speak(text, language) {
    if (!text) return;
    this.connect();
    if (!this.ctx) this.ctx = new AudioContext();
    this.socket.emit('tts_configure_client', { client_id: this.id, voice: VOICES[language] || VOICES.en, speed: 1.1 });
    this.socket.emit('tts_text_chunk', { chunk: text, target_client_id: this.id, final: true });
  },
  async enqueue(buf) {
    if (!buf || !this.ctx) return;
    try { this.queue.push(await this.ctx.decodeAudioData(buf.slice(0))); } catch { return; }
    if (!this.playing) this.next();
  },
  next() {
    const buffer = this.queue.shift();
    if (!buffer) { this.playing = null; this.onState?.('idle'); return; }
    if (this.ctx.state === 'suspended') this.ctx.resume();
    const src = this.ctx.createBufferSource();
    src.buffer = buffer;
    src.connect(this.ctx.destination);
    src.onended = () => this.next();
    this.playing = src;
    this.onState?.('speaking');
    src.start();
  },
  stop() {
    this.queue = [];
    if (this.playing) { this.playing.onended = null; try { this.playing.stop(); } catch { /* already ended */ } this.playing = null; }
    if (this.socket) this.socket.emit('stop_generation', { client_id: this.id });
    this.onState?.('idle');
  },
  speaking() { return !!this.playing || this.queue.length > 0; },
};
window.slidesTts = tts;   // the browser checks look at it
