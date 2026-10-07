// The design-system page (milestone M0, technical design section 3): every component this app uses, as built here,
// to review in both themes and at every width. The specifications are the bancoctt-design skill's DESIGN.md.
import { html, raw, setHtml } from '../core/html.js';

const ROLES = ['--surface-page', '--surface', '--surface-field', '--surface-hover', '--surface-active', '--primary', '--primary-tint',
  '--brand-text', '--link', '--text', '--text-title', '--text-secondary', '--text-weak', '--divider', '--container-info',
  '--container-alert', '--container-primary', '--chip-fluid', '--skeleton', '--surface-inverse'];

const INFO_ICON = '<svg class="banner-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M12 11v6M12 7.5h.01"/></svg>';
const ALERT_ICON = '<svg class="banner-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 3 2 20h20zM12 10v4M12 17h.01"/></svg>';

export function buildDesignSystem(view) {
  const page = document.createElement('div');
  page.className = 'page';
  setHtml(page, html`
    <h1>Design system</h1>
    <p class="lead">The Banco CTT design system as this app uses it. Check it in Light, Dark and System, at every width.</p>

    <section>
      <h2 class="section-title">Colour roles</h2>
      <div class="card"><div class="swatches">${ROLES.map((r) => html`<span class="swatch notranslate"><i style="background: var(${r})"></i>${r}</span>`)}</div></div>
    </section>

    <section>
      <h2 class="section-title">Typography</h2>
      <div class="card type-sample">
        <p class="ds-h4">H4 · 34px Bold</p>
        <p class="ds-h5">H5 · 24px Bold</p>
        <h2>H6 · 20px Bold (card title)</h2>
        <p class="ds-p1">Paragraph 1 · 16px Regular (lead text)</p>
        <p>Paragraph 2 · 14px Regular (the default text)</p>
        <h3>Subtitle 2 · 14px Bold (list titles, tabs)</h3>
        <p class="ds-caption">Caption · 12px Regular (metadata)</p>
      </div>
    </section>

    <section>
      <h2 class="section-title">Buttons</h2>
      <div class="card">
        <div class="stack">
          <button type="button" class="primary">Primary action</button>
          <button type="button" class="secondary">Secondary action</button>
        </div>
        <p></p>
        <div class="row">
          <button type="button">Ghost</button>
          <button type="button" class="primary" disabled>Primary, disabled</button>
          <button type="button" class="secondary" disabled>Secondary, disabled</button>
        </div>
      </div>
    </section>

    <section>
      <h2 class="section-title">Fields</h2>
      <div class="card stack">
        <label class="field-box"><span>Project name</span><input type="text" value="Client X proposal"></label>
        <label class="field-box"><span>Template</span><select><option>Plain template</option><option>Banco CTT</option></select></label>
        <input type="text" placeholder="A compact field, in a toolbar">
        <label class="row"><input type="checkbox" checked> Speak the replies</label>
        <label class="row"><input type="radio" name="ds-radio" checked> Adapt to the target deck</label>
        <label class="row"><input type="radio" name="ds-radio"> Keep the source formatting</label>
      </div>
    </section>

    <section>
      <h2 class="section-title">Tabs</h2>
      <div class="card"><div class="main-tabs" role="tablist">
        <button type="button" class="main-tab active">Decks</button>
        <button type="button" class="main-tab">Conversations</button>
        <button type="button" class="main-tab">Assets</button>
      </div></div>
    </section>

    <section>
      <h2 class="section-title">List</h2>
      <ul class="list">
        <li class="clickable"><div class="list-text"><div class="list-title">Client X proposal</div><div class="list-caption">3 decks · changed today</div></div><span class="pill info">Shared</span></li>
        <li class="clickable selected"><div class="list-text"><div class="list-title">Warranty policy 2026</div><div class="list-caption">1 deck · changed yesterday</div></div><span class="count-badge">2</span></li>
        <li><div class="list-text"><span class="skeleton label"></span><p></p><span class="skeleton value"></span></div></li>
      </ul>
    </section>

    <section>
      <h2 class="section-title">Feedback blocks and tags</h2>
      <div class="stack" style="max-width: none">
        <div class="banner">${raw(INFO_ICON)}<div><b>Previews are approximate</b><small>They are rendered by LibreOffice, not PowerPoint.</small></div></div>
        <div class="banner alert">${raw(ALERT_ICON)}<div><b>A proposal is waiting</b><small>Accept or reject it before asking for another change.</small></div></div>
        <div class="banner error">${raw(ALERT_ICON)}<div><b>The file could not be read</b><small>Macro-enabled presentations are not accepted.</small></div></div>
        <div class="row"><span class="pill">Fluid</span><span class="pill info">Info</span><span class="pill alert">Pending</span><span class="pill error">Failed</span></div>
      </div>
    </section>

    <section>
      <h2 class="section-title">Data table</h2>
      <div class="data-table-wrap"><table class="data-table">
        <thead><tr><th>Version</th><th>Author</th><th class="num">Slides</th></tr></thead>
        <tbody><tr><td>3</td><td>Assistant</td><td class="num">12</td></tr><tr><td>2</td><td>Ana Costa</td><td class="num">11</td></tr></tbody>
      </table></div>
    </section>

    <section>
      <h2 class="section-title">Progress</h2>
      <div class="card"><div class="kb-progress"><div class="kb-progress-bar"><i style="width: 60%"></i></div><span class="kb-progress-text">Rendering slides · 12 of 20</span></div></div>
    </section>

    <section>
      <h2 class="section-title">Toast and dialog</h2>
      <div class="card row">
        <button type="button" class="secondary" data-action="toast">Show a toast</button>
        <button type="button" class="secondary" data-action="confirm">Open a dialog</button>
      </div>
    </section>`);
  page.querySelector('[data-action="toast"]').addEventListener('click', () => window.menus.toast('The deck was saved.'));
  page.querySelector('[data-action="confirm"]').addEventListener('click', () => modalConfirm('Delete the deck "Client X proposal"?', { title: 'Delete deck', confirmText: 'Delete', danger: true }));
  view.append(page);
}

