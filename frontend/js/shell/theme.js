// Slides: copied from Cortex (static/js/shell/theme.js); only the storage keys changed (marked "Slides:").
// theme.js — Light / Dark / System (the Banco CTT design system: DESIGN.md, Colors › Switching themes).
//
// Three states, Light by default. Light and Dark are written as <html data-theme>; System removes the attribute, and
// tokens.css then follows the OS (prefers-color-scheme). The choice is stored as 'light' | 'dark' | 'system'; with
// nothing stored, Light applies. The inline script in <head> applies it before the first paint; this module keeps
// it in step and answers what is in effect.
//
// Stored per browser under cortex.theme - part of a project's workspace (project-boot.js), so a project opens in the
// theme it was left in.

const STORAGE_KEY = 'slides.theme';   // Slides: own key (localStorage is shared with Cortex on the same host)
const DEFAULT = 'light';
const dark = window.matchMedia('(prefers-color-scheme: dark)');

function stored() {
  try {
    const value = window.localStorage.getItem(STORAGE_KEY);
    return value === 'dark' || value === 'light' || value === 'system' ? value : null;
  } catch {
    return null;   // private mode / blocked storage: the default
  }
}

function persist(theme) {
  try {
    if (theme) window.localStorage.setItem(STORAGE_KEY, theme);
    else window.localStorage.removeItem(STORAGE_KEY);
  } catch { /* not fatal — the choice just won't survive a reload */ }
}

/** What applies: 'light' | 'dark' | 'system' (Light until the person chooses). */
export function themeChoice() {
  return stored() || DEFAULT;
}

/** The theme on screen right now: 'light' | 'dark' (System resolved against the OS). */
export function effectiveTheme() {
  const choice = themeChoice();
  return choice === 'system' ? (dark.matches ? 'dark' : 'light') : choice;
}

/** Apply the choice to <html>. Call once, early. */
export function applyStoredTheme() {
  const choice = themeChoice();
  if (choice === 'system') document.documentElement.removeAttribute('data-theme');
  else document.documentElement.setAttribute('data-theme', choice);
  return effectiveTheme();
}

/** Choose 'light', 'dark' or 'system' (anything else: back to the default). Returns the theme now on screen. */
export function setTheme(theme) {
  persist(theme === 'light' || theme === 'dark' || theme === 'system' ? theme : null);
  return applyStoredTheme();
}

// On System, the OS switching between light and dark changes the page: tell whoever draws with the
// theme's colours outside CSS (the timeline canvas, the phone's theme-color).
dark.addEventListener('change', () => { if (themeChoice() === 'system') document.dispatchEvent(new Event('theme-changed')); });
