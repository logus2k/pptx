// Slides: copied verbatim from Cortex (static/js/shell/statusbar.js).
// The status bar, from the left: the open project (project.js), the tab with the focus and its details (focus.js);
// at the right, what concerns the whole page: a session running in a tab that does not have the focus (sidebar.js),
// the connection, the bell (notifications.js).
//
// Details come from the tab's description ({ name, literal, kind, details: [{ text, title, literal }] }) and, for an
// Assistant, its last answer's token counts. The Recording tab's own (state, speakers, article, engine, the live
// numbers) are fixed elements the session code writes (sidebar.js, app.js): shown only while that tab has the focus
// (the bar's data-kind="recording"; .rec-only in vendor-theme.css).
import { description } from './focus.js';

const bar = document.getElementById('status-bar');
const nameEl = document.getElementById('sb-focus');
const detailsEl = document.getElementById('sb-details');
let last = '';

function render() {
  const d = description();
  const details = [...(d?.details || [])].filter((x) => x && x.text);
  if (d?.usage) {
    details.push({ text: `${d.usage.in} tokens in`, title: 'The last answer: tokens the model read (the question, the conversation, the material)' });
    details.push({ text: `${d.usage.out} tokens out`, title: 'The last answer: tokens the model wrote' });
    if (d.usage.tps) details.push({ text: `${d.usage.tps} tokens/s`, title: 'The last answer: how fast the model wrote' });
  }
  const now = JSON.stringify([d?.name, d?.literal, d?.kind, details]);
  if (now === last) return;                 // written only when it changes (the translator watches the page)
  last = now;
  bar.dataset.kind = d?.kind || '';
  nameEl.hidden = !d;
  nameEl.classList.toggle('notranslate', !!d?.literal);
  nameEl.textContent = d?.name || '';
  nameEl.title = d ? 'The tab with the focus' : '';
  detailsEl.replaceChildren(...details.map((x) => {
    const s = document.createElement('span');
    if (x.literal) s.className = 'notranslate';
    s.textContent = x.text;
    if (x.title) s.title = x.title;
    return s;
  }));
}
document.addEventListener('focus-view-changed', render);
setInterval(render, 500);                   // details change while a tab keeps the focus (a recording's duration)
render();
