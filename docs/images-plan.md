# Plan: images and visual elements in generated decks

Status: **proposed, 2026-10-09**, approved in principle by the project owner ("I agree with all proposed actions"),
to start once the current generation work is finished and tested. Nothing here is built yet.

Source of the request: the project owner, 2026-10-09 - add images or other visual elements to slides when they add
value; options for how a presentation uses images (more sober vs creative-friendly); the Artist relies on vision to
make sure an image is adequate, how it must be cropped or processed before it is inserted, and to validate its final
shape. Reference material: *Royalty-Free Image Repositories: Backend Integration Guide* (Unsplash, Pexels, Pixabay).

## 1. Goal and what "done" means

A generated deck (corporate presentation or training, from the form or the assistant) gets a picture or visual
element **only where it helps its audience understand or remember the slide** - never as decoration - in the style the
person chose, accurate to the slide, legally usable by the bank, cropped to its place, and checked on the rendered
slide. The person sees every proposed image before the slides are made, can change or remove it, and can also ask for
images on any slide of any deck, from the editor or the chat.

Done when, measured on real generations of at least three different subjects (Crédito à Habitação, Squad Model, one
more) and two templates:

- every image placed passes the vision checks of section 5, and the Critic finds no "must" issue about it;
- the person can see, change and remove each image in the outline review, and the same from the editor and the chat;
- every image has its source, author, licence and link recorded (slide notes and the project's audit trail);
- with the style "no images", nothing changes from today; with the stock sources off, nothing leaves the bank;
- `make check`, `make e2e`, `make a11y` pass; the UI screenshots are looked at in both themes and every width.

Non-goals (for now): video, image generation (IM-6 stays off until its own decision), editing images beyond crop,
resize and compression, images inside charts or diagrams.

## 2. What exists today (the starting point)

| Piece | Where | Use in this plan |
|---|---|---|
| Insert into a picture placeholder (cropped to it) or a box (proportions kept) | `ops.insert_image` | Placing the chosen image |
| Replace an image keeping its frame, centre-cropped | `ops.replace_image` | "Another image" on an existing slide |
| Alt text | `ops.set_alt_text`, tool `set_alt_text` | Every placed image gets alt text |
| Knowledge-base images (Word, PDF, Markdown pictures) | `kb.images`, tool `kb_list_images` (spec IM-3) | Source 1: the organisation's own images |
| Project assets (uploaded images), stored once, reused | `domain/assets`, spec PJ-11 | Source 2, and where every fetched image is kept |
| Image descriptions by the model's vision, cached by hash | `describe.py` (IM-4) | Describing candidates; alt text |
| The model sees images (vision test passed, 2026-10-09) | `llm.Models.vision` | Choosing, cropping, checking |
| Slides rendered to PNG; the Critic judges each rendered slide | `render.py`, `agent/critic.py` | The final check of the composition |
| The Artist chooses each slide's form; the app chooses the layout from the template's own places | `agent/artist.py`, `ops.add_designed` | A new form: text with an image |
| Image generation client, off unless configured | `imagegen.py` (IM-6) | Not in this plan |

Constraints that bind the design: images are referenced by asset or KB id, **never by URL** (technical design §8 and
the `insert_image` contract); no new infrastructure without a reason recorded and a licence entry
(`docs/licenses.md`); logs carry ids, counts and lengths only - never slide text, queries or image descriptions; the
code stays template-generic (layouts found by their places, not their names).

## 3. The style option

A setting on the generation request (form and assistant), defaulting from the project's settings:

| Style | What the Artist may use | Sources searched |
|---|---|---|
| **No images** (default until the sources are approved) | Nothing new - today's behaviour | - |
| **Sober** | Icons and simple illustrations for concepts; photos only of objects or places, subdued, no people; at most one image per slide, on content slides only; none on the questions and summary | Organisation's images first, then icons/vectors |
| **Balanced** | As sober, plus photos with people when they show the subject (an advisor and a client for "atendimento"); a cover image | All enabled sources |
| **Creative** | As balanced, plus image-led slides (a large image with one message), divider images | All enabled sources |

The style also travels to the Artist and the Critic as words they read, so their judgement follows it. Contract:
`contracts/storage/generation.schema.json` (request `visual_style`), project settings schema (`visual_style`
default), the generate form and the assistant's `generate_deck` tool schema.

## 4. Where images come from (sources), in order

1. **The project's own images** (uploaded assets) and **the knowledge base's images** for the documents the deck was
   read from (IM-3). No data leaves the bank. Already licensed for the bank's use.
2. **An administrator-approved library** (spec IM-3's "asset library"): a folder of approved images (icons, brand
   photography) managed from the administration, each with its description. Phase 2 of this plan; its first contents
   could be the bank's own icon set.
3. **Stock sources, opt-in**: one provider first behind a common interface, more later. Off unless configured
   (`services.images.<provider>` in `config.json`, the key in `.env`), and off per project unless enabled. Suggested
   first provider: **Pixabay** for the sober style (vectors, illustrations, transparent PNGs, `image_type=vector`,
   exclusion terms), then **Pexels** for photography (business subjects, `color` hex to match the template's palette,
   `locale`), **Unsplash** last (artistic; heavier attribution and download-tracking rules).

A provider adapter answers one call: `search(query, kind, orientation, colour, count) -> [candidate]`, a candidate
being `{provider, id, thumb_url, full_url, width, height, author, author_url, page_url, licence}`; and
`fetch(candidate) -> bytes` (the full image, size-limited), which also does what the provider's API terms require
(Unsplash's download-tracking call). Nothing is inserted from a URL: the bytes become a project asset first.

## 5. The pipeline for a generated deck

After the Writer and before the Critic (so the Critic sees the slides with their images):

1. **Decide (the Artist, per content slide).** Given the slide's goal, task, points, the deck's style and the forms
   around it, the Artist answers whether a visual adds value and of what kind - `none`, `icon` (a concept), `photo`
   (a real thing or place), `illustration` - with a one-line reason and a **search brief**: what it must show, what it
   must not show (people, text, logos, other brands), and the mood. Rule in its prompt: a visual must make the slide
   clearer or more memorable for its audience; when in doubt, none. A deck-level cap (e.g. a third of content slides
   in sober) keeps it from becoming decorative.
2. **Find candidates.** Organisation's images first: the KB images of the slide's source documents and the project's
   assets, matched to the brief with the existing reranker over their descriptions. Then, if enabled, the stock
   source: the brief turned into the provider's query (English; the provider's own filters for orientation from the
   picture place's shape, `image_type`, colour from the template's theme, exclusions such as `-people` in sober).
   Up to 8 candidates, thumbnails only.
3. **Choose (vision).** The model sees the candidates' thumbnails together with the slide's text and brief, and
   answers which one, and for each refusal why: off-topic, text or watermark in the image, a logo or another bank's
   brand, people when the style excludes them, a sensitive or culturally unsuitable scene, low quality. Then the
   chosen full image is fetched and described (`describe.py`); the description must agree with the brief - a
   reranker score between brief and description, threshold measured on real candidates (as SAME_FACT was).
4. **Crop and process.** The target shape is the picture place's (the layout chosen for the form: the template's
   picture placeholder, or the box the app gives the image beside the text). The vision model gives the **focal box**
   (the region that must stay: a face, the object) on the full image; the app crops to the target ratio keeping the
   focal box whole and centred as far as possible, resizes to the place's size at 150-200 dpi, converts to JPEG
   (photos) or PNG (icons with transparency), and strips metadata. SVG from vector sources is converted to PNG
   (spec IM-1). If no crop keeps the focal box whole, the next candidate.
5. **Place.** The form "text with image" goes on a layout with a picture place and text (found by `layouts.slots`,
   generic), or, when the template has none, beside the text in a box the app sizes; icons go beside the point they
   illustrate. Alt text from the description; the source line in the notes ("Imagem: <author>, <provider> - <link>").
6. **Check (vision, the Critic).** The Critic, already rendering each slide, gets one more criterion: the image -
   does it fit the slide's message, is anything important cropped away, is text over it readable, does it look
   professional. A "must" on the image means: the next candidate, or no image (never a third try on the same slide).
7. **Record.** The image becomes a project asset with `{provider, id, author, licence, page_url, fetched_at, brief
   hash}`; the project's audit trail gets an `image_added` line (ids only).

The outline review shows each slide's proposed image (thumbnail), why, and its source, with **Other images** (the next
candidates, and "search for…" with the person's own words), **No image**, and **Upload one**. Chosen images are fixed
in the outline; building the deck only places them.

## 6. Images on any deck (not only generated ones)

Both paths, as every feature: in the editor, **Insert › Image › Find an image…** (a search dialog over the same
sources, with the style) and, on a selected picture, **Other images…**; in the chat, "put an image of X on this
slide" / "find a better image" route to tools `find_images(slide, brief)` and `insert_image` with the chosen
candidate's asset. The same choose-crop-check steps run.

## 7. Contracts and code (contracts first)

- `contracts/storage/generation.schema.json`: request `visual_style`; slide `image` (`{asset_id, provider, author,
  page_url, focal, why}` or `null`) and `image_brief`.
- `contracts/storage/asset.schema.json` (or the existing assets record): `source` block with provider, id, author,
  licence, page URL, fetch date.
- `contracts/config.schema.json`: `services.images` (per provider: enabled, base URL); keys in `.env`
  (`SLIDES_PIXABAY_KEY`, ...); limits (candidates per slide, image bytes, images per deck).
- Tools: `find_images` (new), `insert_image` accepting a candidate's asset; schemas in `contracts/tools/`.
- Backend: `app/images/` - `sources.py` (adapters, one file per provider), `choose.py` (vision choice and focal box),
  `process.py` (crop, resize, convert); the Artist's decision in `agent/artist.py`; the Critic's criterion in
  `prompts/critic.md`; the pipeline step in `domain/generations.py`.
- Presets: `slides_image_brief` (or a field of the Artist's answer), `slides_image_choice` (vision).
- Frontend: generate form (style), outline review (image row), editor dialog, i18n.
- `docs/licenses.md`: each provider (its licence and API terms, why); `docs/decisions.md`: each decision below.

## 8. Compliance, privacy, security

- **Data leaving the bank**: a stock search sends the brief to a third party. Briefs are written from the slide's
  subject, never its figures or names; stock sources off by default, enabled per environment by the administrator
  and per project by its owner; the UI says which sources are searched. Needs the owner's and, likely, the bank's
  approval before production.
- **Licences and API terms**: free commercial use, no attribution required by the licences - but the APIs' terms add
  obligations (credit and link to author/provider where results are shown; Unsplash's download tracking and
  hotlinking rules; rate limits). Model or property releases are not guaranteed: sober excludes people by default.
  Every image's source is recorded (notes and audit), so it can be credited or removed later.
- **Content safety**: the vision choice refuses text, logos, other banks' brands, watermarks, unsuitable scenes; the
  person reviews every image.
- **Security**: fetched bytes are size-limited, decoded and re-encoded by Pillow (no original file is kept or
  served), never SVG embedded as SVG; provider calls through the app's HTTP client with timeouts; keys only in
  `.env`; logs carry provider, candidate counts, sizes, durations - never the brief or the image description.

## 9. Measuring it (before trusting each step)

As with the planner and the Critic: capture real calls, read them, replay, measure.

- A fixed set of slides from the three test decks (about 40), each with the owner's or my judgement of "an image
  helps / does not" - the Artist's decision is measured against it (aim: no decorative images; misses acceptable).
- For each slide given an image: candidates and the choice saved; I look at every chosen image and every refusal on
  the first runs; the vision model's choice agreement with mine, its refusals' correctness, the focal box kept whole
  after crop (looked at on the renders).
- The brief-description reranker threshold calibrated on real candidates (positives and negatives), as SAME_FACT was.
- Three full generations per style per subject, rendered and looked at slide by slide, before calling a phase done.

## 10. Phases

| Phase | Content | Done when |
|---|---|---|
| **A** | Style option (form, assistant, project default); the Artist's visual decision and brief; images from the project's assets and the KB's documents only; crop by focal box; placing on picture layouts; alt text; notes source; outline review row with Other images / No image / Upload | Measured as in §9 on the organisation's own images; e2e and a11y of the new UI |
| **B** | Stock source interface and the first provider (Pixabay, icons and illustrations), off by default; asset provenance; licence entry; administrator setting | Owner's approval of data leaving the bank; measured as in §9 with the provider on |
| **C** | Vision choice among candidates with refusal reasons; brief-description check; Critic's image criterion and its loop (next candidate or none) | Measured: choices and refusals looked at on three subjects |
| **D** | Editor and chat paths for any deck (`find_images`, dialog, Other images on a picture) | Both paths e2e; scenarios with the real model |
| **E** | Second provider (Pexels photography) and the approved library (administration) | As B |

Each phase ends with `make check`, `make e2e`, `make a11y`, screenshots looked at, decisions recorded, and the
measurements written in `docs/decisions.md`.

## 11. Decisions needed from the owner

1. Approval for stock searches to leave the bank (and whether the bank's legal/brand team must approve), or the
   organisation's own images only for now.
2. Which providers, in what order, and who obtains the API keys.
3. The default style for new projects (proposed: no images until B is approved; then sober).
4. People in images: excluded in sober (proposed); allowed in balanced and creative?
5. Whether an approved library exists or should be started (and who curates it).

## 12. Risks

- **The vision model's judgement** (gemma-4 E4B): on slides it caught empty space and small text but missed an
  invented column; on photos, subtler problems (an off-brand scene, a watermark) may pass. Mitigation: measured
  before trusted; refusal reasons logged as categories for review; the person reviews every image.
- **Time**: candidates and vision choice add about a minute per image-bearing slide; capped per deck.
- **Provider limits and outages**: searches degrade to "no image", said in the review, never a failed generation.
- **Template variety**: layouts without picture places get images beside text in a box the app sizes; checked on both
  templates.
