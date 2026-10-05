# AI Slide Assistant: Technical Design

**Version:** 0.3 (draft): no database; LLM, STT, TTS and KB consumed as services; authentication by nginx + OAuth2 Proxy **Companion to:** *AI Slide Assistant: Project Specification* v0.5 (the "product spec") **Audience:** engineers and coding agents implementing the system

This document turns the product spec into implementable decisions. The guiding rule is **the smallest system that meets the requirements**: one application process storing everything as files on disk, behind the existing nginx and OAuth2 Proxy, calling existing services for the language model, speech and the Knowledge Base. A component may be added only when a requirement cannot be met without it, and the addition is recorded as a decision in `docs/decisions.md`.

Where this document and the product spec disagree, the product spec decides *what* to build and this document decides *how*. Items marked **\[ASSUMPTION\]** are listed in section 15 for confirmation.

## 0. Rules for implementing agents

Copy these rules into `AGENTS.md` and `CLAUDE.md` at the repository root in milestone M0.

**Design system.** Before writing or changing any frontend markup, CSS or component, load and follow the **Banco CTT Design System Agent Skill**. Its components, tokens, typography, spacing, icons, accessibility patterns and tone of voice take precedence over any visual detail in these documents. Never introduce colours, fonts, spacing or icons that do not come from it; if something is missing, record it in `docs/design-gaps.md` instead of inventing a style.

**No frameworks, no build step.** The frontend is plain JavaScript (ES modules) served as-is to the browser. No React, Vue, Angular, Svelte, Lit, jQuery, bundlers or transpilers.

**No new infrastructure.** Do not add databases (including SQLite), caches, queues, message brokers, extra services or containers. Do not implement authentication; identity comes from proxy headers (section 1.1). Do not add a dependency without a one-line justification and a licence check in `docs/licenses.md`.

**Contracts first.** Changes to tool schemas, the slide representation or WebSocket events start in `contracts/`, then code on both sides, then passing tests.

**Done means** `make check` passes, new code has tests, and the milestone's "Done when" checks in section 13 pass. Never call real LLM, speech or KB services from automated tests, and never disable a failing test to make a build pass.

## 1. Stack

| Area | Decision |
| --- | --- |
| Frontend | JavaScript ES2022 modules, no build step. Encapsulation through module scope and classes with private `#fields`; UI elements are Custom Elements **without** Shadow DOM, so the design system's CSS applies normally. |
| Backend | Python 3.12, FastAPI, Uvicorn: a single process that serves the API, the WebSocket and the frontend's static files. |
| Authentication | Existing nginx + OAuth2 Proxy. The app reads the user from forwarded headers (section 1.1). |
| Persistence | Files on disk only: `.pptx` files for decks, JSON for metadata, JSON Lines for conversations and the audit log (section 4). No database. **\[ASSUMPTION\]** A-3: single instance. |
| Background work | `asyncio` tasks in the same process, with a semaphore limiting concurrent renders. |
| Document engine | python-pptx + lxml, plus custom Open XML code where python-pptx has gaps (section 9). |
| Rendering | LibreOffice headless called as a subprocess from the backend; PDF pages rasterised with pypdfium2. |
| Language model | LLM services reached by URL through an OpenAI-compatible chat-completions API with tool calling and image input. On-premises and remote models are both just configured services; the app does not distinguish them. |
| Speech | STT service (Whisper large-v3-turbo) and TTS service (Kokoro), proxied by the backend (section 7). |
| Knowledge Base | Service owned by the KB project (section 8). |
| Tests | Python `pytest` (backend); Node's built-in `node:test` (frontend logic); Playwright (end to end). |
| Packaging | One Docker image containing the backend, the frontend files, LibreOffice and template fonts. |

The application adds one container and a data volume to the existing environment:

```mermaid
flowchart LR
  Browser["Browser<br/>ES modules + Banco CTT DS"] <--> Nginx["nginx + OAuth2 Proxy<br/>(existing)"]
  Nginx <--> App
  subgraph App["App container"]
    API["FastAPI<br/>REST + WebSocket + static files"]
    Agent["Agent loop + tools"]
    Engine["Document engine<br/>python-pptx"]
    LO["LibreOffice<br/>(subprocess)"]
    DB[("Files<br/>on data volume")]
    API --- Agent --- Engine
    Engine --- LO
    API --- DB
  end
  App --> LLM["LLM services"]
  App --> STT["STT service<br/>Whisper large-v3-turbo"]
  App --> TTS["TTS service<br/>Kokoro"]
  App --> KB["Knowledge Base service"]
```

### 1.1 Identity from the proxy

OAuth2 Proxy authenticates the user and nginx forwards the request with identity headers; the application never sees credentials and has no login screen. A FastAPI dependency reads the user ID, email, display name and groups from the configured headers (by default `X-Forwarded-User`, `X-Forwarded-Email`, `X-Forwarded-Preferred-Username` and `X-Forwarded-Groups`; names configurable, A-2) and rejects requests without them. If the KB requires the user's token, OAuth2 Proxy passes it in `X-Forwarded-Access-Token` and the KB client forwards it. Because the app trusts these headers, it listens only on the internal network that nginx uses, and nginx strips any identity headers sent by clients. The WebSocket upgrade passes through the same nginx location, so it carries the same headers. In development, an environment variable `DEV_USER` makes the app act as a fixed user; it is refused when `ENV=production`.

## 2. Repository layout

```
/
├── AGENTS.md, CLAUDE.md
├── Makefile                  # make dev | check | e2e | eval
├── Dockerfile
├── contracts/
│   ├── tools/*.schema.json   # one JSON Schema per assistant tool
│   ├── slide.schema.json     # structured slide representation
│   ├── ws-events.schema.json # WebSocket messages
│   ├── openapi.json          # generated by FastAPI, committed; CI fails on drift
│   ├── kb/                   # KB API spec, provided by the KB project (read-only)
│   ├── speech/               # STT and TTS API specs, provided by their owners (read-only)
│   └── storage/*.schema.json # JSON Schemas of the stored metadata files
├── frontend/
│   ├── index.html
│   ├── js/
│   │   ├── main.js           # bootstrap and router
│   │   ├── core/             # store, api client, ws client, html helper
│   │   ├── audio/            # recorder, player
│   │   ├── components/       # one module per custom element
│   │   └── views/            # project list, project home, editor, history
│   ├── css/                  # app-level layout only; all styling from the design system
│   └── test/
├── backend/
│   ├── app/
│   │   ├── main.py
│   │   ├── api/              # routers
│   │   ├── domain/           # projects, decks, versions, proposals, conversations, memory
│   │   ├── agent/            # loop, context, prompts/, tools/
│   │   ├── docengine/        # read model, operations, copy, layouts, overflow, render
│   │   ├── clients/          # llm, stt, tts, kb
│   │   └── storage/          # file repository: atomic writes, project locks, layout
│   └── tests/
├── fixtures/                 # decks, templates, fake-model scripts, kb mock data, evals
└── docs/                     # decisions.md, design-gaps.md, licenses.md, spikes/
```

## 3. Frontend

**Encapsulation.** Each component is a class in its own module with private fields and methods; only a small documented public surface (properties and methods) is exposed. Components are registered as Custom Elements (prefix `sa-`, for example `sa-slide-strip`) so they compose in HTML and have lifecycle callbacks, but they render into their own element (light DOM), which lets the Banco CTT Design System's styles and components work without workarounds. Data goes down through properties; events go up as `CustomEvent`s prefixed `sa:` (for example `sa:slide-selected`). Components never query or modify elements belonging to another component.

**State.** One `store.js` module holds application state (user, project, active deck, selection, conversation, pending proposal, voice state). State changes only through named actions; views subscribe to what they need. HTTP, WebSocket and audio live in modules under `core/` and `audio/`, not in components.

**Rendering.** A tagged-template `html` helper escapes all interpolated values. Text from slides, the KB or the model is always inserted as text, never as HTML.

**Views.** Project list (`/`), project home (`/projects/:pid`: decks, conversations, assets, instructions, memory, settings), editor (`/projects/:pid/decks/:did`: slide strip, slide stage with diff view, assistant panel with messages, composer and voice button), version history. Routing uses the History API; the backend serves `index.html` for these paths.

**Slide stage.** Shows the rendered PNG of the slide with clickable selection boxes positioned from shape geometry in the slide representation. The selected shape IDs are sent with each chat message.

## 4. Storage

Everything lives under one data directory (`DATA_DIR`). The entities from product spec 4.3 map to files:

```
DATA_DIR/
└── projects/
    └── <project_id>/
        ├── project.json            # name, description, owner, members + roles, settings, instructions, archived
        ├── memory.json             # list of memory items with source conversation and author
        ├── audit.jsonl             # one line per tool call or version change
        ├── decks/
        │   └── <deck_id>/
        │       ├── deck.json       # title, template, current version number, version list (number, source, author, date, proposal)
        │       └── versions/
        │           ├── 1.pptx
        │           └── 2.pptx
        ├── conversations/
        │   └── <conversation_id>/
        │       ├── conversation.json   # title, rolling summary, last summarised message number
        │       ├── messages.jsonl      # append-only, one message per line, numbered
        │       └── proposals/<proposal_id>/
        │           ├── proposal.json   # status, plan, per-deck base version and recorded operations
        │           └── drafts/<deck_id>.pptx
        ├── assets/
        │   ├── assets.json         # id, kind, file name, hash, description, extracted text
        │   └── <asset_id>.<ext>
        └── renders/<sha256>/       # slide PNGs cached by .pptx hash; safe to delete
```

The JSON files have schemas in `contracts/storage/` and carry a `schema_version` so the format can evolve with small upgrade functions run at startup.

**Consistency.** All writes go through a `storage` module. Every JSON or `.pptx` write goes to a temporary file in the same directory followed by `os.replace`, so a crash never leaves a half-written file. Writes within a project are serialised by a per-project `asyncio.Lock`; a version is published by writing the new `.pptx` first and updating `deck.json` last, so a reader never sees a version without its file. This is correct only with a single application process (A-3).

**Lookups.** The project list is built by reading each `project.json` the user is a member of; at the expected scale (hundreds of projects) this takes milliseconds, and the result is cached in memory and refreshed on change. Conversation search (`search_conversations`) scans the project's `messages.jsonl` files with a case- and accent-insensitive match; a project's conversations are at most a few megabytes of text, so no index is needed.

**Backup and deletion.** Backup is a copy of `DATA_DIR`. Deleting a project moves its directory to `DATA_DIR/trash/` with a timestamp and a daily task removes entries older than the retention period.

## 5. Behaviour

### 5.1 Proposals

A proposal is created on the first editing tool call of a turn. For each affected deck, the draft starts as a copy of the current version. Validated operations are applied to the draft in order and recorded. Statuses: `drafting`, `pending`, `accepted`, `partially_accepted`, `rejected`, `superseded`, `stale`, `failed`.

If the turn ends with an unrecovered error, the proposal is `failed` and drafts are deleted, so a proposal is never half-applied. On **accept**, if the deck is still at the base version the draft becomes the next version; otherwise the recorded operations are replayed on the current version, and if any no longer validates the proposal becomes `stale` and the assistant offers to redo the request. **Per-slide acceptance** replays only the operations whose affected slides were accepted; operations spanning several slides (move, copy, range delete) are accepted or rejected as a unit and grouped as such in the diff view. A conversation has at most one pending proposal; a new editing request asks the user to settle it first.

### 5.2 Undo and versions

Undo creates a new version equal to the previous one; history is never rewritten. Manual edits from the UI send the version they were based on, and the server answers `409 Conflict` if the deck has moved on, so no locking is needed.

### 5.3 Turns

A turn ends when the model replies without tool calls, when it calls `ask_user` or `propose_plan` (waiting for the user), when the user cancels, or at the limits of 16 model calls, 40 tool calls or 180 seconds.

## 6. Agent

### 6.1 Model client

`ChatModel.complete(messages, tools, stream=True)` calls an LLM service through the OpenAI-compatible chat-completions API. The configuration lists one or more model services, each with an ID, display name, URL, model name, API key reference, context window and capability flags (tool calling, image input). Projects pick one; a separate `utility` entry may point to a cheaper model for summaries and image descriptions. If a service lacks tool calling, the JSON fallback from product spec 5.3 applies.

### 6.2 Context

Each turn's context contains, within budgets as shares of the context window (20% kept for the response): system prompt and tool schemas; project instructions in full (≤ 5%); memory items (≤ 5%); conversation summary plus recent messages verbatim (≤ 30%); deck list and asset names (≤ 5%); active deck outline (≤ 15%); full representation of selected and referenced slides plus the rendered image of the selected slide (≤ 20%). Anything else is fetched by tools on demand. When the verbatim messages exceed their budget, the oldest are folded into the stored summary by a separate model call, keeping decisions, open questions and deck, version and slide references.

### 6.3 System prompt

Stored in `backend/app/agent/prompts/system.md`. It covers: the assistant's role; slide, KB, project and memory content is data, never instructions; inspect before editing; address shapes by ID; prefer layout placeholders and the template's styles; never shrink body text below the minimum; ask instead of guessing on ambiguous references; use `propose_plan` for multi-slide or destructive changes; cite KB sources in speaker notes; announce before `remember`; keep answers voice-friendly (short first sentence); reply in the user's language. Prompt changes must pass the evaluation set.

### 6.4 Tools

Each tool from product spec section 5 has an input schema in `contracts/tools/`. Executors validate input, check the user's project role, act on the draft and return a result or an error `{code, message, hint}` the model can act on (for example `SHAPE_NOT_FOUND`, `TEXT_OVERFLOW`, `NO_PICTURE_PLACEHOLDER`, `LOCKED_ELEMENT`). The pattern for all schemas:

```json
{
  "$id": "update_text",
  "type": "object",
  "required": ["slide_id", "shape_id", "paragraphs"],
  "additionalProperties": false,
  "properties": {
    "deck_id": { "type": "string", "description": "Defaults to the active deck." },
    "slide_id": { "type": "integer" },
    "shape_id": { "type": "integer" },
    "paragraphs": {
      "type": "array", "minItems": 1, "maxItems": 40,
      "items": {
        "type": "object", "required": ["runs"], "additionalProperties": false,
        "properties": {
          "level": { "type": "integer", "minimum": 0, "maximum": 4 },
          "alignment": { "enum": ["left", "center", "right", "justify"] },
          "runs": {
            "type": "array", "minItems": 1,
            "items": {
              "type": "object", "required": ["text"], "additionalProperties": false,
              "properties": {
                "text": { "type": "string", "maxLength": 2000 },
                "bold": { "type": "boolean" },
                "italic": { "type": "boolean" },
                "theme_color": { "enum": ["text1", "text2", "accent1", "accent2", "accent3", "accent4", "accent5", "accent6"] }
              }
            }
          }
        }
      }
    }
  }
}
```

Images are referenced as `{ "asset_id": "…" }` or `{ "kb_document_id": "…", "kb_image_id": "…" }`, never by URL.

### 6.5 Slide representation

Defined in `contracts/slide.schema.json`. Example:

```json
{
  "deck_id": "…", "slide_id": 258, "index": 4, "layout": "Title and Content", "hidden": false,
  "shapes": [
    { "shape_id": 2, "type": "placeholder", "placeholder": { "type": "title", "idx": 0 },
      "box": { "x": 0.06, "y": 0.05, "w": 0.88, "h": 0.14 },
      "paragraphs": [{ "level": 0, "runs": [{ "text": "Warranty policy 2026" }] }],
      "overflow": false, "locked": false },
    { "shape_id": 5, "type": "picture", "box": { "x": 0.55, "y": 0.25, "w": 0.40, "h": 0.60 },
      "alt_text": "", "description": "Photo of a parcel sorting line.", "locked": false },
    { "shape_id": 9, "type": "other", "subtype": "smartart", "locked": true }
  ],
  "notes": "Source: KB 'Warranty Policy v4' (WP-4)."
}
```

`box` values are fractions of slide width and height. Image descriptions come from the model's vision capability and are cached by image hash.

## 7. Speech

Both speech services already exist. The backend proxies them so credentials never reach the browser and so calls are authenticated and logged. Their specifications go in `contracts/speech/` (assumption A-6). Clients sit behind two small interfaces, `Transcriber` and `Synthesizer`, so the providers can change without touching the rest.

**STT (Whisper large-v3-turbo).** The browser records with `MediaRecorder` while the microphone button is held (push-to-talk) and sends the clip when it is released; the backend forwards it to the STT service with the project language (default `pt`) and a vocabulary prompt of project terms (product names, acronyms), then returns the text to the composer for review before sending. If the STT service supports streaming, live partial transcripts (product spec VO-1) and hands-free mode (VO-2) are enabled through the WebSocket; if it accepts only complete recordings, the UI shows a recording indicator instead of live text, and hands-free mode is deferred.

**TTS (Kokoro).** The assistant's reply includes a short `speakable` version. The backend splits it into sentences and requests audio per sentence, streaming each to the browser as soon as it arrives, so playback starts after the first sentence rather than after the whole reply. The browser plays the clips in sequence; pressing the microphone button stops playback and cancels outstanding requests (barge-in).

**Portuguese voice.** Kokoro's Portuguese voices are Brazilian Portuguese. If European Portuguese is required for Banco CTT users, the TTS provider needs another voice or engine for `pt-PT` (assumption A-7).

## 8. Knowledge Base

The KB is a separate project consumed as a service, whose API specification the KB team provides in `contracts/kb/` (assumption A-4). A `KnowledgeBaseClient` exposes what the tools need: `search(user, query, collections, top_k)`, `get_document(user, doc_id, passage_id)`, and `get_image(user, doc_id, image_id)` if the KB offers it. The user's identity is forwarded as the KB requires (for example the access token from OAuth2 Proxy, section 1.1) so its own permissions apply. Calls time out after 8 seconds and errors become tool errors. For tests and local development, a fake client returns fixture documents, including prompt-injection test documents.

## 9. Document engine

The engine provides a read model (deck outline and slide representation) and one function per operation, each taking a loaded presentation and returning the affected slide IDs. It changes only the targeted elements, keeps unknown XML intact, and takes styles from layouts and theme.

Three operations need custom Open XML work because python-pptx does not provide them. **Copying slides between decks:** create a slide with the best-matching layout in the target, deep-copy the shape tree, copy referenced parts (images, charts and their workbooks, notes) with new relationship IDs, and map placeholders to the target layout when adapting formatting; charts, SmartArt and embedded objects are copied as-is and marked locked. **Changing layout:** create a slide with the new layout at the same position, move content into placeholders matched by type then index, keep other shapes in place, report anything unmatched, delete the old slide. **Overflow detection:** estimate text height from font metrics (template fonts installed in the image), frame size, insets and autofit settings; the render check is the second line of defence.

**Rendering:** after a version or draft changes, convert it to PDF with LibreOffice (including hidden slides, so page N is slide N), rasterise pages with pypdfium2 to preview and thumbnail PNGs, and cache by file hash. Each conversion uses a fresh LibreOffice profile directory and a 60-second timeout. At most two conversions run at once.

Every operation's result is saved and reloaded before it is accepted; a file that fails to reload rejects the operation.

## 10. Interfaces

**REST** endpoints follow product spec section 9 (nested under `/projects`). FastAPI generates the OpenAPI document; it is committed to `contracts/openapi.json` and CI fails if it changes without being committed. Errors use `application/problem+json`.

**WebSocket**, one per open conversation. Messages are JSON `{type, payload}`. Client to server: `user_message` (text, active deck, selection, input mode), `cancel_turn`, `answer`, `proposal_decision`. Server to client: `assistant_delta`, `assistant_message` (with `speakable` text), `tool_progress` (a short human-readable description), `question`, `plan`, `proposal_updated`, `memory_changed`, `deck_changed`, `turn_ended`, `error`. On reconnection the client requests messages after the last sequence number it received. TTS audio for a reply is fetched over HTTP by message ID.

## 11. Security

The application trusts identity headers only because it is reachable solely through nginx (section 1.1); deployment must keep its port off any other network. Uploads are checked by content (a ZIP containing a presentation part), size and decompressed size; macro-enabled content is rejected. XML parsing has entity resolution and network access disabled. The LibreOffice subprocess runs with a timeout and a temporary profile. The assistant has no tool that fetches URLs, sends messages or runs code. Every tool call and version change is written to the audit log.

## 12. Testing

`make check` runs `ruff` and `pytest` for the backend (domain, tool executors, document engine golden tests on fixture decks, contract checks) and `node --test` for frontend logic (store, html helper, API and WebSocket clients). `make e2e` runs Playwright against the app with identity headers injected by the test harness, a **scripted fake model**, and fake speech and KB clients, covering product spec scenarios S1 to S10 deterministically. `make eval` runs the editing evaluation set against the real configured model and reports targeting accuracy, overflow rate and injection resistance; it is not part of CI.

Fixtures created in M0–M1: about 12 decks (default and Banco CTT templates, hidden slides, SmartArt, charts, tables, animations, embedded video, grouped shapes, notes, long text, Portuguese with accents, 100+ slides), 60 evaluation requests (half in Portuguese), and a handful of prompt-injection documents and decks.

## 13. Spikes and milestones

Spikes come first; each ends with a short report in `docs/spikes/`.

| ID | Question | Exit criterion |
| --- | --- | --- |
| SP-1 | Copying slides between decks with different templates. | 20 combinations open in PowerPoint without repair; unsupported cases listed. |
| SP-2 | Changing layouts without losing content. | 15 changes on fixture decks; nothing lost; unmatched content reported. |
| SP-3 | Overflow estimation accuracy. | Agrees with rendered output on ≥ 90% of 100 text frames. |
| SP-4 | Render time and fidelity with template fonts. | 30-slide deck in \< 10 s; 10 slides compared with PowerPoint exports. |
| SP-5 | Which model handles the tools well? | 2–4 candidates on the 60-request set; selected model ≥ 90% targeting accuracy. |
| SP-6 | STT accuracy on domain terms and TTS voice acceptability through the provided APIs. | Error rate measured on 50 recorded utterances with and without vocabulary prompt; voice decision recorded. |

| # | Scope | Done when |
| --- | --- | --- |
| M0 | Repository, Dockerfile, `make` targets, `AGENTS.md`/`CLAUDE.md`, contracts skeleton, design-system integration and a page showing the DS components used by the app, fixtures v1. | `make dev` serves the app; `make check` passes; DS page reviewed. |
| M1 | Identity from proxy headers, file storage, projects, deck upload/create/download, versions, rendering, project home and editor (no assistant). | E2E: create project, upload deck, see thumbnails, download identical file, restore a version. |
| M2 | Read model and single-deck operations with golden tests. | Golden tests pass; 10 outputs checked in PowerPoint. |
| M3 | Agent loop, model client, tools, conversations, proposals and diff view, per-slide accept, undo, summaries, project instructions. | E2E S1, S5, S6, S7 pass with the fake model; eval ≥ 90% with the selected model. |
| M4 | KB client, KB tools, citations, clarifying questions. | E2E S2, S4 pass; injection evals cause no unconfirmed destructive action. |
| M5 | Voice: push-to-talk, playback, barge-in, voice confirmations. | E2E S3 passes with recorded audio and fake speech clients. |
| M6 | Memory, conversation search, assets and reference documents, cross-deck operations. | E2E S8, S9, S10 pass. |
| M7 | Accessibility audit, security review, PDF export, sharing. | Findings closed or accepted. |

## 14. Licences

| Component | Licence |
| --- | --- |
| FastAPI, Uvicorn, Pydantic, python-pptx, lxml | MIT / BSD |
| pypdfium2 | Apache 2.0 / BSD |
| LibreOffice (unmodified, run as a subprocess) | MPL 2.0 |
| pytest, ruff, Playwright | MIT / Apache 2.0 (development only) |

The licensing of the STT and TTS services is their providers' concern.

## 15. Assumptions to confirm

| ID | Assumption |
| --- | --- |
| A-1 | The Banco CTT Design System Agent Skill is available to implementing agents; its exact name and form (CSS, web components, tokens) are to be confirmed. Whether it also governs the slide templates is undecided; if so, the .pptx templates must be supplied. |
| A-2 | The existing nginx + OAuth2 Proxy setup forwards user ID, email, name and groups as headers (names to be confirmed), strips client-supplied identity headers, and can pass the user's access token if the KB needs it. |
| A-3 | One application instance serves all users. File storage relies on this; running several instances would require shared storage and a different consistency mechanism, which is out of scope. |
| A-4 | The KB team provides an API specification with search, document retrieval and, ideally, image retrieval, and a way to act for the user. |
| A-5 | Template fonts may be installed on the server for rendering and overflow measurement. |
| A-6 | The STT and TTS service API specifications are provided, including whether STT supports streaming and TTS supports per-request voice and language. |
| A-7 | A decision on European Portuguese speech output, given that Kokoro's Portuguese voices are Brazilian. |
| A-8 | Default UI and assistant language is European Portuguese, with English available. |