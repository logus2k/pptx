// Slides: copied from Cortex (static/js/shell/identity.js); changes marked "Slides:".
// identity.js — signed-in user widget: the person's photo + pull-down menu.
//
// The photo and display name come from /api/me, which exchanges the OAuth
// access token nginx forwards (X-Access-Token) for the provider's OpenID claims (cortex/server/identity.py).
// Everything here degrades: no photo falls back to initials, and a failed
// lookup still shows the email.

function initials(nameOrEmail) {
  const source = (nameOrEmail || '').trim();
  if (!source) return '?';
  const words = source.split(' ').filter(Boolean);
  if (words.length >= 2) return (words[0][0] + words[1][0]).toUpperCase();
  return source.slice(0, 2).toUpperCase();
}

export const SUN = `<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor"
  stroke-width="1.8" stroke-linecap="round"><circle cx="12" cy="12" r="4.2"/>
  <line x1="12" y1="2.5" x2="12" y2="5"/><line x1="12" y1="19" x2="12" y2="21.5"/>
  <line x1="2.5" y1="12" x2="5" y2="12"/><line x1="19" y1="12" x2="21.5" y2="12"/>
  <line x1="5.3" y1="5.3" x2="7" y2="7"/><line x1="17" y1="17" x2="18.7" y2="18.7"/>
  <line x1="5.3" y1="18.7" x2="7" y2="17"/><line x1="17" y1="7" x2="18.7" y2="5.3"/></svg>`;

const GLOBE = `<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor"
  stroke-width="1.7" stroke-linecap="round"><circle cx="12" cy="12" r="9"/>
  <path d="M3 12h18M12 3c2.5 2.7 2.5 15.3 0 18M12 3c-2.5 2.7-2.5 15.3 0 18"/></svg>`;

export const MOON = `<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor"
  stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
  <path d="M20 14.5A8.5 8.5 0 0 1 9.5 4a8.5 8.5 0 1 0 10.5 10.5z"/></svg>`;

export function initIdentity(root, me, theme = null, lang = null, onSettings = null) {
  if (!root || !me || !me.authenticated) return;

  root.replaceChildren();
  root.hidden = false;

  // --- the button: photo, or initials when there is none ---
  const button = document.createElement('button');
  button.type = 'button';
  button.className = 'identity-btn notranslate';    // Slides: a person's name, email and initials: never translated
  button.setAttribute('aria-haspopup', 'menu');
  button.setAttribute('aria-expanded', 'false');
  button.title = me.name ? `${me.name} (${me.email})` : me.email;

  // Cortex: the Banco CTT top bar's profile - the avatar (a circle holding the photo, or the initials), the name
  // and a chevron (the copy from devops had the avatar alone)
  const face = document.createElement('span');
  face.className = 'identity-face';
  button.appendChild(face);
  const fallback = document.createElement('span');
  fallback.className = 'identity-initials';
  fallback.textContent = initials(me.name || me.email);
  face.appendChild(fallback);

  if (me.picture) {
    const img = document.createElement('img');
    img.className = 'identity-avatar';
    img.alt = '';                       // decorative; the button has a title
    // (a provider's CDN - Google's - refuses requests that carry a referrer from another origin)
    img.referrerPolicy = 'no-referrer';
    img.addEventListener('load', () => { fallback.hidden = true; });
    img.addEventListener('error', () => { img.remove(); });   // keep initials
    img.src = me.picture;
    face.appendChild(img);
  }
  const shown = document.createElement('span');
  shown.className = 'identity-btn-name notranslate';
  shown.textContent = me.name || me.email;
  const chevron = document.createElement('span');
  chevron.className = 'identity-chevron';
  chevron.setAttribute('aria-hidden', 'true');
  button.append(shown, chevron);
  root.appendChild(button);

  // --- the pull-down ---
  const menu = document.createElement('div');
  menu.className = 'identity-menu';
  menu.setAttribute('role', 'menu');
  menu.hidden = true;

  const who = document.createElement('div');
  who.className = 'identity-who';
  const name = document.createElement('div');
  name.className = 'identity-name';
  name.textContent = me.name || '';
  const email = document.createElement('div');
  email.className = 'identity-email';
  email.textContent = me.email || '';
  who.append(name, email);
  menu.appendChild(who);

  // --- theme toggle ---
  if (theme) {
    const themeItem = document.createElement('button');
    themeItem.type = 'button';
    themeItem.className = 'identity-item identity-toggle';
    themeItem.setAttribute('role', 'menuitemcheckbox');

    const label = document.createElement('span');
    const icon = document.createElement('span');
    icon.className = 'identity-icon';
    themeItem.append(icon, label);

    // The label names what you would switch TO, so the action is unambiguous.
    const paint = (current) => {
      const goingDark = current !== 'dark';
      label.textContent = goingDark ? 'Dark theme' : 'Light theme';
      icon.innerHTML = goingDark ? MOON : SUN;
      themeItem.setAttribute('aria-checked', current === 'dark' ? 'true' : 'false');
      themeItem.title = `Currently ${current}. Click to switch.`;
    };
    paint(theme.current());

    themeItem.addEventListener('click', (event) => {
      event.stopPropagation();
      paint(theme.toggle());
      close();                   // a choice dismisses the menu, as every item does
      document.dispatchEvent(new Event('theme-changed'));
    });
    document.addEventListener('theme-changed', () => paint(theme.current()));   // the Settings view
    menu.appendChild(themeItem);

  }

  // --- language toggle, directly under the theme row ---
  if (lang) {
    const langItem = document.createElement('button');
    langItem.type = 'button';
    langItem.className = 'identity-item identity-toggle';
    langItem.setAttribute('role', 'menuitem');

    const icon = document.createElement('span');
    icon.className = 'identity-icon';
    icon.innerHTML = GLOBE;
    const label = document.createElement('span');
    langItem.append(icon, label);

    // The label names the language you would switch TO.
    const paint = () => { label.textContent = lang.otherLabel(); };
    paint();

    langItem.addEventListener('click', (event) => {
      event.stopPropagation();
      lang.toggle();
      paint();
      close();
    });
    menu.appendChild(langItem);
  }

  if (theme || lang) {
    const divider = document.createElement('div');
    divider.className = 'identity-divider';
    menu.appendChild(divider);
  }

  // Review settings: the audit checklist and the story exemplars. Sits with the
  // theme and language toggles because it is the same kind of thing — the
  // user's own preferences about how the app behaves, not a work-item action.
  if (onSettings) {
    const settingsItem = document.createElement('button');
    settingsItem.type = 'button';
    settingsItem.className = 'identity-item identity-toggle';
    settingsItem.setAttribute('role', 'menuitem');
    const icon = document.createElement('span');
    icon.className = 'identity-icon';
    icon.textContent = '⚙';
    const label = document.createElement('span');
    label.textContent = 'Preferences';   // Slides: this app's preferences dialog (user.js); the copy said "Review settings"
    settingsItem.append(icon, label);
    settingsItem.addEventListener('click', (event) => {
      event.stopPropagation();
      close();
      onSettings();
    });
    menu.appendChild(settingsItem);
  }

  const signOut = document.createElement('a');
  signOut.className = 'identity-item';
  signOut.setAttribute('role', 'menuitem');
  signOut.href = me.signOutUrl || 'oauth2-entra/sign_out';   // Slides: the fallback is this domain's Entra proxy
  signOut.dataset.i18n = 'menu.signOut';   // filled by applyTranslations()
  signOut.textContent = 'Sign out';
  menu.appendChild(signOut);

  root.appendChild(menu);

  const close = () => {
    menu.hidden = true;
    button.setAttribute('aria-expanded', 'false');
  };
  const open = () => {
    menu.hidden = false;
    button.setAttribute('aria-expanded', 'true');
  };

  button.addEventListener('click', (event) => {
    event.stopPropagation();
    menu.hidden ? open() : close();
  });
  // Click anywhere else, or Escape, dismisses it.
  document.addEventListener('click', (event) => {
    if (!root.contains(event.target)) close();
  });
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') close();
  });

  return { close };
}
