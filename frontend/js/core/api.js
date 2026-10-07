// The REST API (backend app/api.py), relative to the page's base: "api/projects" is /slides/api/projects behind the
// proxy. Errors become ApiError with the server's message for people (its detail.message) and its code.

export class ApiError extends Error {
  constructor(status, code, message) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

async function fail(r) {
  let code = String(r.status);
  let message = `The server answered ${r.status}.`;
  try {
    const body = await r.json();
    const d = body.detail;
    if (d && typeof d === 'object' && !Array.isArray(d)) { code = d.code || code; message = d.message || message; }
    else if (typeof d === 'string') message = d;
  } catch { /* not JSON */ }
  if (r.status === 404) message = 'Not found: it may have been deleted, or you may not have access to it.';
  throw new ApiError(r.status, code, message);
}

export async function api(path, { method = 'GET', json, form } = {}) {
  const init = { method, headers: {} };
  if (json !== undefined) { init.headers['Content-Type'] = 'application/json'; init.body = JSON.stringify(json); }
  if (form !== undefined) init.body = form;
  const r = await fetch(`api/${path}`, init);
  if (!r.ok) await fail(r);
  if (r.status === 204) return null;
  return r.json();
}

/** The address of a slide's image: versioned, so the browser keeps it (the server marks it immutable). */
export function slideImage(pid, did, slideId, version, size = 'thumb') {
  return `api/projects/${pid}/decks/${did}/slides/${slideId}/image?size=${size}&version=${version}`;
}

export function downloadUrl(pid, did, version = null) {
  return `api/projects/${pid}/decks/${did}/download${version ? `?version=${version}` : ''}`;
}
