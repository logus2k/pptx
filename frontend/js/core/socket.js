// The socket.io connection, as Cortex's app.js opens it (a classic script: the shell modules copied from Cortex - user.js,
// notifications - use `socket` by name). Its path follows where the app is served: the page's <base href> (/slides/
// behind the proxy, / when reached directly), so the channel goes through the same proxy location as the page.
// The connection indicator at the right of the status bar is Cortex's (app.js setStatus): "conn on" / "conn off".
const socket = io({ path: `${new URL(document.baseURI).pathname}socket.io`, transports: ['websocket'] });

(function () {
  function setStatus(on) {
    const el = document.getElementById('status');
    if (!el) return;
    el.classList.toggle('on', on);
    el.classList.toggle('off', !on);
    el.textContent = on ? 'connected' : 'disconnected';
  }
  socket.on('connect', () => setStatus(true));
  socket.on('disconnect', () => setStatus(false));
  socket.on('connect_error', () => setStatus(false));
})();
