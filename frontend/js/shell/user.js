// Slides: copied from Cortex (static/js/shell/user.js); changes marked "Slides:".
// Signed-in user widget (who is signed in, Sign out) + the stored theme applied, as in devaikb (identity.js from devops,
// theme.js from devaikb). Access control is the proxy's job: nginx lets only
// allowed accounts reach this page and forwards who they are; the
// server reports that on request. With no proxy in front (direct :2710) there
// is no identity and the widget stays hidden.
import { initIdentity } from './identity.js';
import { applyStoredTheme, setTheme, themeChoice } from './theme.js';

applyStoredTheme();     // the inline <head> script already set it; keep in step

// Slides: the theme (Light / Dark / System) and the interface language are chosen in a Preferences dialog opened from
// the user menu (identity.js's settings item): Cortex has them in its Settings view, which this app does not have.
async function preferences() {
  const values = await modalForm({
    title: 'Preferences', confirmText: 'Save',
    fields: [
      { name: 'theme', label: 'Theme', value: themeChoice(), options: [['light', 'Light'], ['dark', 'Dark'], ['system', 'System']] },
      { name: 'language', label: 'Interface language', value: window.uiLanguage(), options: [['pt', 'Português'], ['en', 'English']] },
    ],
  });
  if (!values) return;
  setTheme(values.theme);
  document.dispatchEvent(new Event('theme-changed'));
  if (values.language !== window.uiLanguage()) {
    // the page is translated as it is built (i18n.js): a new language takes a reload
    try { localStorage.setItem('slides.uiLanguage', values.language); } catch { /* not remembered */ }
    location.reload();
  }
}

let shown = false;

// Ask rather than wait for a push: emits are buffered until the socket
// connects, and the reply cannot race this module's loading.
socket.emit('whoami', {}, (me) => {
  if (shown || !me || !me.authenticated) return;
  shown = true;
  window.__user = me;                       // the status bar shows who is signed in; Settings reads is_admin
  initIdentity(document.getElementById('identity'), me, null, null, preferences);   // Slides: + Preferences
  document.dispatchEvent(new CustomEvent('identity-known', { detail: me }));   // Settings > Access control
});
