// A tagged template that escapes every interpolated value (technical design section 3): text from slides, the KB,
// the model or people is always inserted as text, never as HTML.
//   el.innerHTML = html`<li>${title}</li>`;
// A value wrapped with raw() is inserted as it is: only for markup this code built itself (another html`` result).

const RAW = Symbol('raw');

export function raw(markup) {
  return { [RAW]: String(markup) };
}

export function escape(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

function piece(value) {
  if (value && typeof value === 'object' && RAW in value) return value[RAW];
  if (Array.isArray(value)) return value.map(piece).join('');
  return escape(value);
}

export function html(strings, ...values) {
  let out = strings[0];
  for (let i = 0; i < values.length; i++) out += piece(values[i]) + strings[i + 1];
  return raw(out);
}

/** Put html`` markup into an element. */
export function setHtml(el, markup) {
  el.innerHTML = piece(markup);
}
