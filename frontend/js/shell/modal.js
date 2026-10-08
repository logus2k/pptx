// Slides: copied verbatim from Cortex (static/js/shell/modal.js).
// Application dialogs in place of the browser's alert() and confirm(), which look foreign,
// cannot be themed and block the page. Same pattern as noted's modal.js: jsPanel's modal
// extension, awaited like the functions they replace
//   if (!await modalConfirm('Delete it?', { confirmText: 'Delete', danger: true })) return;
// Messages go in as TEXT, never HTML: they carry recording and article titles.
// A plain script (like app.js), so app.js and the module scripts all see these functions.

function _modalText(message) {
  const box = document.createElement('div');
  box.className = 'modal-text';
  // translated whole, before it is cut in paragraphs: the dictionary has the message as the page wrote it (i18n.js
  // translates text node by text node, and no paragraph alone is the message)
  const text = window.cortexT ? window.cortexT(String(message)) : String(message);
  for (const para of text.split('\n\n')) {
    box.append(Object.assign(document.createElement('p'), { textContent: para }));
  }
  return box;
}

function _modal({ title, message, buttons, onClose }) {
  return jsPanel.modal.create({
    headerTitle: title,
    theme: 'none',
    contentSize: { width: Math.min(568, window.innerWidth - 32), height: 'auto' },   // DESIGN.md, Components > Modal: 568px
    position: 'center',
    headerControls: 'closeonly',
    closeOnEscape: true,
    closeOnBackdrop: false,
    footerToolbar: '<div class="modal-buttons"></div>',
    // no backdrop cleanup here (noted's modal.js has one): jsPanel.modal 1.2.5 removes its
    // own backdrop, and removing it first made that throw "removeChild: not a child"
    onclosed: [() => { onClose(); return true; }],
    callback: (panel) => {
      panel.classList.add('cortex-dialog');
      panel.content.append(_modalText(message));
      const bar = panel.footer.querySelector('.modal-buttons');
      for (const b of buttons) {
        const el = Object.assign(document.createElement('button'), { type: 'button', textContent: b.text });
        if (b.cls) el.className = b.cls;
        el.addEventListener('click', () => { b.onClick(); panel.close(); });
        bar.append(el);
      }
      // Enter takes the default (last) button, as a native dialog does
      const main = bar.lastElementChild;
      panel.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); main.click(); } });
      main.focus();                                   // at once: an Enter pressed right away must land here
    },
  });
}

// Resolves true when confirmed; false on Cancel, the close button or Escape.
function modalConfirm(message, { title = 'Confirm', confirmText = 'OK', cancelText = 'Cancel', danger = false } = {}) {
  return new Promise((resolve) => {
    let answer = false;
    _modal({
      title, message, onClose: () => resolve(answer),
      buttons: [
        { text: cancelText, onClick: () => {} },
        { text: confirmText, cls: danger ? 'danger' : 'primary', onClick: () => { answer = true; } },
      ],
    });
  });
}

// Resolves when dismissed.
function modalAlert(message, { title = 'Notice', buttonText = 'OK' } = {}) {
  return new Promise((resolve) => {
    _modal({ title, message, onClose: () => resolve(), buttons: [{ text: buttonText, cls: 'primary', onClick: () => {} }] });
  });
}

// A small form: resolves {name: value, ...} on confirm, null on Cancel / close / Escape.
// fields: [{name, label, value?, placeholder?, options?: [[value, text], ...], hint?, multiline?, rows?}]
// (Slides: multiline and rows added)
// `validate(values)` (optional) returns an error text to keep the dialog open.
function modalForm({ title = 'Edit', fields = [], confirmText = 'OK', validate = null } = {}) {
  return new Promise((resolve) => {
    let answer = null;
    const form = document.createElement('div');
    form.className = 'kb-target';
    const inputs = {};
    for (const f of fields) {
      let input;
      if (f.options) {
        input = document.createElement('select');
        for (const [value, text] of f.options) input.append(new Option(text, value));
      } else if (f.multiline) {
        // Slides: several lines (a slide's points, its notes, a chart's or a table's data), as the editor's controls need
        input = Object.assign(document.createElement('textarea'), { rows: f.rows || 5, placeholder: f.placeholder || '' });
      } else {
        input = Object.assign(document.createElement('input'), { type: 'text', placeholder: f.placeholder || '' });
      }
      if (f.value !== undefined && f.value !== null) input.value = f.value;
      inputs[f.name] = input;
      const label = document.createElement('label');
      label.className = 'kb-field';
      label.append(Object.assign(document.createElement('span'), { textContent: f.label }), input);
      form.append(label);
      if (f.hint) form.append(Object.assign(document.createElement('div'), { className: 'kb-hint', textContent: f.hint }));
    }
    const error = Object.assign(document.createElement('div'), { className: 'kb-error' });
    form.append(error);
    jsPanel.modal.create({
      // Slides: never wider than the screen (measured on a 390 px phone: 440 px, from x -25, its close button cut off)
      headerTitle: title, theme: 'none', contentSize: { width: Math.min(440, window.innerWidth - 32), height: 'auto' }, position: 'center',
      headerControls: 'closeonly', closeOnEscape: true, closeOnBackdrop: false,
      footerToolbar: '<div class="modal-buttons"></div>',
      onclosed: [() => { resolve(answer); return true; }],
      callback: (panel) => {
        panel.classList.add('cortex-dialog');
        panel.content.append(form);
        const bar = panel.footer.querySelector('.modal-buttons');
        const cancel = Object.assign(document.createElement('button'), { type: 'button', textContent: 'Cancel' });
        cancel.addEventListener('click', () => panel.close());
        const ok = Object.assign(document.createElement('button'), { type: 'button', className: 'primary', textContent: confirmText });
        ok.addEventListener('click', () => {
          const values = Object.fromEntries(Object.entries(inputs).map(([k, el]) => [k, el.value.trim()]));
          const why = validate?.(values);
          if (why) { error.textContent = why; return; }
          answer = values;
          panel.close();
        });
        bar.append(cancel, ok);
        panel.addEventListener('keydown', (e) => { if (e.key === 'Enter' && e.target.tagName === 'INPUT') { e.preventDefault(); ok.click(); } });
        panel.reposition();
        // Slides: on a touch screen the keyboard waits for a tap (focused at once, iOS zoomed the page in and the
        // dialog was drawn without its panel); with a mouse, the first field takes the typing as before
        if (window.matchMedia('(pointer: fine)').matches) Object.values(inputs)[0]?.focus();
      },
    });
  });
}
