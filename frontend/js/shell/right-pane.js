// The right pane, as in Cortex (static/js/shell/right-panel.js): noted's RightPanel (verbatim, in RightPanel.js) with
// a resizer. Cortex's right-panel.js registers its own Assistants and follows its recording Mode; this keeps the
// generic part - registering views, showing and hiding the pane, the width remembered - for this app's assistant
// (milestone M3), through window.rightPane.
import { RightPanel } from './RightPanel.js';
import { DETACH_ICON } from './undock.js';
import { describe, pane } from './focus.js';

const container = document.getElementById('right-panel');
const resizer = document.getElementById('right-resizer');
const panel = new RightPanel(container);
panel._undockBtn.hidden = true;            // (floating the assistant: not in this app's first milestones)
panel._undockBtn.innerHTML = DETACH_ICON;
pane(container, () => panel._views[panel._activeView]?.element || null);

function sync() {
  const docked = panel.openViews.size > 0;
  container.style.display = docked ? 'flex' : 'none';
  resizer.hidden = !docked;
}
panel.onClose = () => sync();

// ── width: drag the resizer (remembered per browser), Cortex's code ──
const WIDTH_KEY = 'slides.right-width';
const setWidth = (px) => { container.style.flexBasis = `${px}px`; };
try { const w = Number(localStorage.getItem(WIDTH_KEY)); if (w) setWidth(w); } catch { /* storage unavailable */ }
resizer.addEventListener('pointerdown', (e) => {
  if (e.button !== 0) return;
  e.preventDefault();
  resizer.setPointerCapture(e.pointerId);
  resizer.classList.add('dragging');
  document.body.style.userSelect = 'none';
  document.body.style.cursor = 'col-resize';
  const startX = e.clientX;
  const startW = container.getBoundingClientRect().width;
  const move = (ev) => setWidth(Math.max(300, Math.min(startW + startX - ev.clientX, window.innerWidth - 500)));
  const up = () => {
    resizer.classList.remove('dragging');
    document.body.style.userSelect = '';
    document.body.style.cursor = '';
    resizer.removeEventListener('pointermove', move);
    resizer.removeEventListener('pointerup', up);
    resizer.removeEventListener('pointercancel', up);
    try { localStorage.setItem(WIDTH_KEY, String(Math.round(container.getBoundingClientRect().width))); } catch { /* storage unavailable */ }
  };
  resizer.addEventListener('pointermove', move);
  resizer.addEventListener('pointerup', up);
  resizer.addEventListener('pointercancel', up);
});

/** window.rightPane.add(key, {label, element}), show(key), close(key), shown(key). */
window.rightPane = {
  add(key, { label, element }) {
    panel.registerView(key, { tabLabel: label, title: '', element, undockable: false });
    describe(element, () => ({ name: label }));
  },
  show(key) { panel.show(key); sync(); },
  close(key) { panel.close(key); sync(); },
  shown(key) { return panel.openViews.has(key); },
};
sync();
