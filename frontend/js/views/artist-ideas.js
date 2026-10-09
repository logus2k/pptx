// The Artist's ideas for a slide (agent/artist.py; the user, 2026-10-08: "we should be able to ask the Artist for ideas
// or a different proposal at any time"): a dialog listing the proposals - each its form, what it shows and why - to
// choose one, with a field to say what the person would like and ask again. Used by the outline review
// (views/generate.js) and the deck editor (views/deck.js). The dialog is a jsPanel modal as shell/modal.js's are.
import { html, setHtml } from '../core/html.js';

export const FORM_TEXT = {
  bullets: 'List', columns: 'Columns', figures: 'Key figures', highlight: 'Highlight', table: 'Table', chart: 'Chart', diagram: 'Diagram',
};

/** What a design shows, in a line: "Requisitos pessoais | Requisitos financeiros". */
export function summary(d) {
  if (!d) return '';
  if (d.form === 'columns') return (d.columns || []).map((c) => c.heading).join(' | ');
  if (d.form === 'figures') return (d.figures || []).map((f) => `${f.value} ${f.label}`).join(' | ');
  if (d.form === 'highlight') return d.highlight?.statement || '';
  if (d.form === 'table') return (d.table?.rows?.[0] || []).join(' | ');
  if (d.form === 'chart') return (d.chart?.categories || []).join(', ');
  if (d.form === 'diagram') return (d.diagram?.nodes || []).join(' → ');
  return (d.points || []).slice(0, 3).join(' · ');
}

/** Resolves the chosen design, or null. fetchIdeas(wish) -> Promise<[design]>. */
export function chooseIdea({ title = 'Ideas from the Artist', fetchIdeas }) {
  return new Promise((resolve) => {
    let answer = null;
    let ideas = [];
    const box = document.createElement('div');
    box.className = 'artist-ideas';
    jsPanel.modal.create({
      headerTitle: title, theme: 'none', contentSize: { width: Math.min(568, window.innerWidth - 32), height: 'auto' }, position: 'center',
      headerControls: 'closeonly', closeOnEscape: true, closeOnBackdrop: false,
      footerToolbar: '<div class="modal-buttons"></div>',
      onclosed: [() => { resolve(answer); return true; }],
      callback: (panel) => {
        panel.classList.add('cortex-dialog');
        panel.content.append(box);
        const bar = panel.footer.querySelector('.modal-buttons');
        const cancel = Object.assign(document.createElement('button'), { type: 'button', textContent: 'Cancel' });
        cancel.addEventListener('click', () => panel.close());
        const ok = Object.assign(document.createElement('button'), { type: 'button', className: 'primary', textContent: 'Use this idea', disabled: true });
        ok.addEventListener('click', () => {
          const picked = box.querySelector('input[name="idea"]:checked');
          if (!picked) return;
          answer = ideas[Number(picked.value)];
          panel.close();
        });
        bar.append(cancel, ok);

        async function load(wish = '') {
          ok.disabled = true;
          setHtml(box, html`<p class="muted" role="status">The Artist is thinking…</p>`);
          try {
            ideas = await fetchIdeas(wish);
          } catch (e) {
            setHtml(box, html`<p class="user-text" role="alert">${e.message}</p>`);
            return;
          }
          setHtml(box, html`
            <fieldset class="idea-list"><legend class="visually-hidden">Ideas</legend>
              ${ideas.map((d, i) => html`<label class="idea card"><input type="radio" name="idea" value="${i}">
                <span class="stack"><b>${FORM_TEXT[d.form] || d.form}</b>
                  <span class="user-text">${summary(d)}</span>
                  ${d.why ? html`<small class="muted user-text">${d.why}</small>` : ''}</span></label>`)}
            </fieldset>
            <label class="kb-field"><span>Something else? Say what you would like</span>
              <input type="text" data-wish maxlength="300" placeholder="More visual, as a diagram, two columns…"></label>
            <div class="row"><button type="button" data-again>Ask again</button></div>`);
          box.querySelectorAll('input[name="idea"]').forEach((r) => r.addEventListener('change', () => { ok.disabled = false; }));
          box.querySelector('[data-again]').addEventListener('click', () => load(box.querySelector('[data-wish]').value.trim()));
          box.querySelector('[data-wish]').addEventListener('keydown', (e) => {
            if (e.key === 'Enter') { e.preventDefault(); load(e.target.value.trim()); }
          });
          panel.reposition();
          box.querySelector('input[name="idea"]')?.focus();
        }
        load();
      },
    });
  });
}
