// The home view (route "/"): what the app is, and where to start - the person's projects are in the side panel.
import { html, setHtml } from '../core/html.js';
import { newProject } from './projects.js';

export function buildHome(view) {
  const page = document.createElement('div');
  page.className = 'page';
  setHtml(page, html`
    <h1 class="notranslate">Slides</h1>
    <p class="lead">Create and revise PowerPoint presentations by talking to an assistant.</p>
    <section>
      <h2 class="section-title">Getting started</h2>
      <div class="card">
        <p>Choose a project in the Projects panel, or create a new one. A project holds your decks and the templates they use.</p>
        <div class="row"><button type="button" class="secondary" data-action="new">New project</button></div>
      </div>
    </section>`);
  page.querySelector('[data-action="new"]').addEventListener('click', () => newProject().catch((e) => modalAlert(e.message, { title: 'New project' })));
  view.append(page);
}
