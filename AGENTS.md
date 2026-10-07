# AGENTS.md

The AI Slide Assistant ("Slides"): people edit PowerPoint decks by talking to an assistant. What to build is
`documentation/AI Slide Assistant_ Project Specification.md`; how is `documentation/AI Slide Assistant_ Technical Design.md`.
Where they disagree, the specification decides what, the technical design decides how.

## Rules (technical design, section 0)

- **Design system.** For any UI work (pages, components, styles, layout, charts), use the bancoctt-design skill
  (`.claude/skills/bancoctt-design/`). Follow its `SKILL.md` and read the sections of `references/DESIGN.md` it points
  to before writing UI code. Colours, type, spacing, radii and shadows come only from `tokens.css`. When a component is
  not specified, use the closest one in DESIGN.md › Components, say so in a comment, and record it in
  `docs/design-gaps.md`. Never edit the installed skill or the files copied from it (`frontend/css/tokens.css`,
  `frontend/images/bancoctt-logo*.svg`): copy them again from `~/env/assets/bancoctt_design_system`.
- **Reuse Cortex.** `~/env/assets/cortex` solved sign-in, the frontend shell, logging and audit for the same
  environment. Before building a part, check how Cortex does it and copy that. Copied files say so in their first line;
  every change in them is marked with a comment starting `Slides:`. Copied third-party stylesheets are never edited:
  their look comes from `frontend/css/vendor-theme.css`.
- **No frameworks, no build step.** Plain ES modules, HTML and CSS, served as they are. The only third-party browser
  code is in `frontend/vendor/` (listed in `docs/licenses.md`).
- **No new infrastructure.** No databases (not even SQLite), caches, queues or extra services: files on disk under
  `DATA_DIR`. No authentication code: identity comes from the proxy (`X-Auth-Request-Email` + the shared secret).
  A new dependency needs a one-line reason and a licence entry in `docs/licenses.md`.
- **No regular expressions** without asking the project owner first, in code, tests or throwaway scripts.
- **Logging** follows Banco CTT's standard as Cortex does (`backend/app/telemetry.py`): ids, counts and lengths only -
  never slide text, prompts, answers, file or project names, addresses or secrets.
- **Contracts first.** Tool schemas, the slide representation and socket.io events start in `contracts/`.
- **Done means** `make check` passes, new code has tests, and the milestone's "Done when" checks pass - including
  looking at the screenshots of any UI change (`make ui`), in both themes and at every width. Never call real LLM,
  speech or KB services from automated tests; never disable a failing test.
- `frontend/` is copied into the image: a change is served by the container only after
  `docker compose build slides && docker compose up -d slides`.
