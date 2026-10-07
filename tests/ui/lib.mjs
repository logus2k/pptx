// Shared by the browser checks: Chrome through playwright-core, as Cortex's tests/ui do, with the identity header and
// the proxy secret the domain proxy would add (Cortex's tests/ui/auth.mjs), so the app is reached directly.
import { chromium } from 'playwright-core';
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';

export const BASE = process.env.SLIDES_URL || 'http://localhost:2720/';

export function proxySecret() {
  if (process.env.SLIDES_PROXY_SECRET !== undefined) return process.env.SLIDES_PROXY_SECRET;
  try {
    for (const line of readFileSync(new URL('../../.env', import.meta.url), 'utf8').split('\n')) {
      const eq = line.indexOf('=');
      if (eq > 0 && line.slice(0, eq).trim() === 'SLIDES_PROXY_SECRET') return line.slice(eq + 1).trim();
    }
  } catch { /* no .env: no secret */ }
  return '';
}

export function authHeaders(email) {
  const h = { 'X-Auth-Request-Email': email };
  const s = proxySecret();
  if (s) h['X-Slides-Proxy-Secret'] = s;
  return h;
}

/** Chrome; `audio`: a WAV file its fake microphone plays (the voice checks), allowed without asking. */
export async function launch({ audio = null } = {}) {
  const args = ['--disable-gpu', '--disable-gpu-compositing', '--disable-software-rasterizer'];
  if (audio) args.push('--use-fake-ui-for-media-stream', '--use-fake-device-for-media-stream', `--use-file-for-fake-audio-capture=${audio}`);
  return chromium.launch({ executablePath: '/usr/bin/google-chrome', args });
}

/** A page signed in as `email`, with its problems collected (page errors, console errors, missing files). */
export async function open(browser, email, { width = 1440, height = 900, scheme = 'light', path = '', storage = {} } = {}) {
  const ctx = await browser.newContext({ viewport: { width, height }, extraHTTPHeaders: authHeaders(email), colorScheme: scheme });
  // the translation audit is on in every check: recordMisses() collects what the Portuguese dictionary lacks
  await ctx.addInitScript((s) => { for (const [k, v] of Object.entries(s)) localStorage.setItem(k, v); },
    { 'slides.i18nAudit': '1', ...storage });
  const page = await ctx.newPage();
  page.problems = [];
  page.on('pageerror', (e) => page.problems.push(`page error: ${e.message}`));
  page.on('console', (m) => { if (m.type() === 'error' && !m.text().includes('favicon')) page.problems.push(`console: ${m.text()}`); });
  page.on('response', (r) => { if (r.status() >= 400) page.problems.push(`HTTP ${r.status()}: ${new URL(r.url()).pathname}`); });
  await page.goto(BASE + path, { waitUntil: 'networkidle' });
  return page;
}

/** Does the page scroll sideways (DESIGN.md, Layout: never)? */
export async function overflow(page) {
  return page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth);
}

/** Adds the interface texts the Portuguese dictionary lacks, as this page met them, to out/i18n-misses.json. */
export async function recordMisses(page) {
  const found = await page.evaluate(() => (window.i18nMisses || []).map((t) => `${t}  [${window.i18nWhere[t]}]`)).catch(() => []);
  const dir = new URL('./out/', import.meta.url).pathname;
  mkdirSync(dir, { recursive: true });
  const file = `${dir}i18n-misses.json`;
  const all = existsSync(file) ? JSON.parse(readFileSync(file, 'utf8')) : [];
  for (const t of found) if (!all.includes(t)) all.push(t);
  writeFileSync(file, JSON.stringify(all, null, 1));
}
