# Third-party components and their licences

Every dependency, with why it is here (technical design section 0). Python versions are in `requirements.txt`.

| Component | Version | Licence | Why |
|---|---|---|---|
| FastAPI, Starlette, Uvicorn, Pydantic | see requirements.txt | MIT / BSD-3 | The REST API and its server (as Cortex) |
| python-socketio, python-engineio, wsproto | 5.17.0 / 4.14.0 / 1.3.2 | MIT | The realtime channel (as Cortex) |
| python-multipart | 0.0.32 | Apache 2.0 | File uploads |
| requests, httpx | 2.34.2 / 0.28.1 | Apache 2.0 / BSD-3 | Calls to the environment's services |
| jsonschema | 4.26.0 | MIT | Validating the configuration file and contracts |
| python-pptx | 1.0.2 | MIT | The document engine |
| lxml | 6.1.3 | BSD-3 | Open XML where python-pptx has gaps |
| Pillow, pypdfium2 | 12.3.0 / 5.14.0 | MIT-CMU / Apache 2.0 or BSD-3 | Rasterising rendered slides |
| OpenTelemetry SDK, OTLP exporter, instrumentations | 1.45.0 / 0.66b0 | Apache 2.0 | Banco CTT's logging standard (as Cortex) |
| LibreOffice (unmodified, a subprocess, in the base image) | Debian 13's 25.2 | MPL 2.0 | Rendering slides and PDF export |
| libraqm (base image) | Debian 13's | MIT | Pillow's text layout with the fonts' kerning, as LibreOffice lays text out: the overflow estimate's word widths |
| Carlito, Caladea, Liberation, DejaVu fonts (base image) | Debian 13's | SIL OFL 1.1 / GPL with font exception | Office-compatible metrics for previews |
| The templates' fonts: Arial Nova, Aptos (+ Display, Narrow), Arial, Arial Narrow, Arial Black, Calibri, Cambria, Consolas, Courier New, Georgia, Century Gothic, Segoe UI, Symbol, Tahoma, Times New Roman, Trebuchet MS, Verdana, Wingdings 1-3; Open Sans | Those of this machine's Windows and Office (Office's cloud fonts for Arial Nova and Aptos) | Microsoft / Monotype, licensed to Banco CTT with Windows and Microsoft 365: **not redistributable** (Open Sans: Apache 2.0) | Previews, PDFs and fit checks that match PowerPoint (Banco CTT's template is set in Arial Nova; without it LibreOffice used DejaVu Sans, wider: titles wrapped that fit in PowerPoint). Kept in `fonts/` (git-ignored, docker-ignored), mounted read-only at `/usr/share/fonts/slides`: never committed, never in an image. Another host needs its own copy from a licensed machine |
| Acto CTT (Thin to Black, with italics) | CTT's web fonts, as CTT publishes them (ctt.pt, `acto ctt_webfonts.zip`, 2015), the TrueType files | CTT's typeface, for Banco CTT's decks (no licence file in the archive: CTT's to say) | Previews, PDFs and fit checks in CTT's own typeface (the Squad Model deck sets about 1 500 runs in it). In `fonts/acto-ctt/` (git-ignored, never in an image); `config/fonts.conf` maps the weights decks name as families ("Acto CTT Light", "Acto CTT Bold") to the family at that weight |
| Inter (frontend/fonts) | variable, as in Cortex | SIL OFL 1.1 (`frontend/fonts/Inter-LICENSE.txt`) | The design system's typeface |
| socket.io client (frontend/vendor) | 4.8.1 | MIT | The realtime channel in the browser (as Cortex) |
| marked (frontend/vendor) | 15.0.12 | MIT | Rendering the assistant's Markdown (as Cortex) |
| DOMPurify (frontend/vendor) | 3.2.6 | Apache 2.0 or MPL 2.0 | Sanitising rendered Markdown (as Cortex) |
| jsPanel (frontend/vendor) | 4.16.1 | MIT | Dialogs and floating windows (as Cortex) |
| Notyf (frontend/vendor) | not stated in the file; Cortex's copy | MIT | Toasts (as Cortex) |
| Shell modules and stylesheets copied from Cortex | - | same owner | The frontend shell (technical design section 3) |
| numpy | 2.5.3 | BSD 3-Clause | A spoken request's level before Whisper (as Cortex) |
| aiohttp | 3.14.3 | Apache 2.0 | socket.io's async client to stt_server (as Cortex) |
| anthropic | 1.8.0 | MIT | Claude models, when a key is set (as Cortex) |
| axe-core (development, tests/ui) | 4.14.0 | MPL 2.0 | The accessibility audit (make a11y): WCAG 2.2 A/AA rules run in the browser on each screen |
| pytest, ruff, websocket-client (development) | 9.1.1 / 0.16.10 / 1.9.0 | MIT / MIT / Apache 2.0 | Tests and lint |
| playwright-core (development, tests/ui) | 1.63.0 | Apache 2.0 | Browser checks (as Cortex) |
