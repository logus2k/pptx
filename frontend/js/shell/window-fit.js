// Slides: copied verbatim from Cortex (static/js/shell/window-fit.js).
// Floating windows (every jsPanel: undocked sections and tabs, the player, dialogs) stay inside the
// browser window when it is resized.
//
// Each window keeps a "home": the place and size the person gave it (when it opened, and after each
// drag or resize they make). On a browser resize every window is put at its home, moved - and shrunk
// only when it is larger than the browser window - just enough to be fully visible. Moving it there
// does not change its home, so when the browser window grows back each window returns to where it was
// put, or as close to it as fits.

const MARGIN = 4;                         // px kept between a window and the visible area's edges
const home = new WeakMap();               // panel element -> {left, top, width, height}

function setHome(panel) {
  const r = panel.getBoundingClientRect();
  home.set(panel, { left: r.left, top: r.top, width: r.width, height: r.height });
}

const byId = (e) => (e && e.detail ? document.getElementById(e.detail) : null);
for (const ev of ['jspanelloaded', 'jspaneldragstop', 'jspanelresizestop']) {
  document.addEventListener(ev, (e) => { const p = byId(e); if (p) setHome(p); });
}

// the visible area: between the top bar (the menus stay above windows) and the status bar
function area() {
  const bar = document.querySelector('#app > header');
  const status = document.getElementById('status-bar');
  const top = bar ? bar.getBoundingClientRect().bottom : 0;
  const bottom = status ? status.getBoundingClientRect().top : window.innerHeight;
  return { top, bottom, width: window.innerWidth };
}

function fit() {
  const { top: T, bottom: B, width: W } = area();
  for (const p of document.querySelectorAll('.jsPanel')) {
    if (!p.offsetParent && getComputedStyle(p).position !== 'fixed') continue;     // hidden
    if (!home.has(p)) setHome(p);
    const h = home.get(p);
    const width = Math.min(h.width, W - 2 * MARGIN);
    const height = Math.min(h.height, B - T - 2 * MARGIN);
    const left = Math.max(MARGIN, Math.min(h.left, W - width - MARGIN));
    const top = Math.max(T + MARGIN, Math.min(h.top, B - height - MARGIN));
    const r = p.getBoundingClientRect();
    if (Math.round(r.width) !== Math.round(width) || Math.round(r.height) !== Math.round(height)) {
      p.style.width = `${Math.round(width)}px`;
      p.style.height = `${Math.round(height)}px`;
    }
    // jsPanel writes its offsets in several forms ("310px", "calc(600px)"): shift the computed value (px)
    // by the difference, which is right for a fixed panel (viewport offsets) and an absolute one alike
    const cs = getComputedStyle(p);
    if (Math.round(r.left) !== Math.round(left)) p.style.left = `${Math.round(parseFloat(cs.left) + (left - r.left))}px`;
    if (Math.round(r.top) !== Math.round(top)) p.style.top = `${Math.round(parseFloat(cs.top) + (top - r.top))}px`;
  }
}

let frame = 0;
window.addEventListener('resize', () => {
  cancelAnimationFrame(frame);
  frame = requestAnimationFrame(fit);
});
