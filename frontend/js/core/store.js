// The application's state (technical design section 3): one place, changed only through set(); views follow the keys
// they need with on(key, fn). Keys: project (id), deck (id), selection ({slide_id, shape_ids}), conversation (id),
// proposal (the conversation's pending proposal, or null), version (the open deck's version).
const state = { project: null, deck: null, selection: null, conversation: null, proposal: null, version: null };
const bus = new EventTarget();

export function get(key) { return state[key]; }

export function set(key, value) {
  if (state[key] === value) return;
  state[key] = value;
  bus.dispatchEvent(new CustomEvent(key, { detail: value }));
}

/** Follow a key; returns a function that stops following. */
export function on(key, fn) {
  const handler = (e) => fn(e.detail);
  bus.addEventListener(key, handler);
  return () => bus.removeEventListener(key, handler);
}
