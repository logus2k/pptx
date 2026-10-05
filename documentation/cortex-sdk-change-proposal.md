# Proposal: additions to the Cortex integration API (`/api/v1`) for the AI Slide Assistant

**From:** the AI Slide Assistant project (`~/env/assets/pptx`): a Banco CTT web app in which people edit PowerPoint decks by talking to an assistant. It uses Cortex's knowledge bases as its Knowledge Base. Requirement ids below (KB-5, NL-12, …) are from its specification, `~/env/assets/pptx/documentation/AI Slide Assistant_ Project Specification.md`.
**To:** Cortex, for implementation, feedback, or both.
**Date:** 2026-10-05. **Status:** proposal. Nothing here is implemented.

## Why this document

The AI Slide Assistant reads Cortex's knowledge bases only through the integration API documented in the Developer SDK manual (`static/help/sdk/`). We read the manual and `cortex/api/v1.py` and checked that they agree. The API already covers most of what we need:

- `GET domains` to choose the domains a project uses;
- `POST search` to find passages, including asking the user which document they meant when several match;
- `GET passages/{id}` to fetch a passage;
- the passage fields (`title`, `section`, `page`, `updated`, `domain`, `document`) to cite sources in speaker notes.

We do not need `POST ask`: our assistant writes with its own model from `search` results, as the manual's *Good practice* recommends, and so it does not occupy the shared local model.

Four things are missing, and one existing address needs a confirmation. They are listed below in order of priority. Each says what to add, why, how this project uses it, a proposed contract, and how to check it. The contracts are suggestions: Cortex knows its code, and different shapes that meet the same need are welcome. Every addition is read-only, keeps `v1`'s promise (new routes and optional fields only), and keeps Cortex's rule that a document someone may not read answers `404`, the same as one that does not exist.

| # | Change | Priority | Our requirement |
|---|---|---|---|
| 1 | Calls on behalf of the signed-in person | Required before go-live | KB-5: the assistant never retrieves what the user could not open in Cortex |
| 2 | A document's passages, in order | Required | KB-2 (use a whole document); NL-12 (build slides from a document or topic) |
| 3 | A document's images | Wanted (our Phase 2) | IM-3: put a KB image on a slide |
| 4 | Search within named documents | Small; optional | Better targeting when the user names a document |
| 5 | A stable link to a document | Confirmation only | KB-3: a clickable source in the speaker notes |

---

## 1. Calls on behalf of the signed-in person

### What is missing

A key acts as the person who created it (`api_keys.verify`, `v1.caller`). A service has no way to say *who* it is asking for. The AI Slide Assistant serves many people, and each must see only the domains and units they may read in Cortex.

The workarounds are poor:

- **One service key:** every user sees the same domains, so access control is lost.
- **One key per user:** each person creates a Cortex key, pastes it into our app, and renews it within a year. A key also outlives the person's removal from the sign-in allow-list (manual, *What administrators should know*).

### Proposed change

A **service client**: a credential an administrator issues to one named application. Calls made with it must name the person they are for, and Cortex answers with **that person's** access.

- **Issuing.** In *Settings › API keys*, administrators only: **New service key**, with an application name (`slides`), an expiry, and optionally the domains it may ever touch (a ceiling over each person's own access). Stored like personal keys (SHA-256 only, shown once), with a distinct prefix, e.g. `ctxs_…`.
- **Calling.** `Authorization: Bearer ctxs_…` plus `X-On-Behalf-Of: <sign-in address>`, the address Microsoft Entra ID gave the person through our proxy (`X-Auth-Request-Email`).
- **Answering.** Exactly as for a personal key whose owner is that address: `access.for_user(<address>, scoped=False)`, so roles, grants and units apply unchanged. An address with no grants sees nothing (empty `domains`, `404` on a named domain), which is already Cortex's behaviour for a person without access.
- **Errors.**
  - A service key without `X-On-Behalf-Of`: `400`.
  - A personal key with `X-On-Behalf-Of`: `400`, or the header is ignored. Either is fine, but say which.
  - A revoked or expired service key: `401`, as today.
- **Rate limit.** Per (service key, person), so one busy user cannot block the others. The same 60 a minute is enough for us: one assistant turn makes a handful of searches. A ceiling per service key (for example 600 a minute) protects Cortex.
- **Where it is accepted.** Only on the **internal** path, never on the public one:
  - the domain proxy's public `location ^~ /cortex/api/v1/` (in `proxy_server/conf/route-cortex.conf`; a one-line change there, not in Cortex) clears `X-On-Behalf-Of` as it already clears the identity headers;
  - our server calls Cortex on the internal Docker network (`http://cortex:2710/api/v1/…`) with Cortex's proxy secret.

  A leaked service key alone then reads nothing on anyone's behalf from outside.
- **Accountability.**
  - Every call is logged with the service name and the person's pseudonym (`userId`), following Cortex's logging rules.
  - The *API keys* tab shows each service key's last use and call count.
  - Issuing and revoking a service key are audit events, as for personal keys.
  - Read calls stay out of the audit table, as today. If Cortex prefers to record service reads, that is fine with us.

### Use cases in this project

- **Search.** A user asks "add a slide summarising our 2026 warranty policy". Our server calls `POST search` on behalf of that person, over the domains chosen in the project's settings. Passages from units they may not read never reach our model.
- **Project settings.** When someone opens a project's settings, `GET domains` on their behalf lists only the domains *they* may use.
- **Shared projects (our Phase 3).** Two members of one project search with their own access each. The assistant never shows one member a passage only the other may read.
- **People who leave.** When someone is removed from Cortex's access, our app loses that access at once. There is no personal key to revoke.

### How to check

- **Identical answers.** For two addresses with different grants, `search` and `domains` through the service key equal those through each person's own personal key.
- **Header cleared on the public route.** Through the public route, `X-On-Behalf-Of` has no effect.
- **Errors.** A revoked service key answers `401`.
- **Rate limit.** The per-person limit holds independently for two people.

---

## 2. A document's passages, in order

### What is missing

`GET documents` returns the stored file (Markdown, PDF, Word, Excel). To use a whole document, a client must turn PDF, Word and Excel into text itself, which repeats what Cortex's ingestion (ingestion-server with docling, and `md_chunker`) has already done. The result would also differ from the passages Cortex cites. `search` returns at most 20 passages and cannot be asked for "all of this document".

Cortex appears to have what is needed already: passages are stored with their position. For documents ingested by `kbase/ingest.py`, `chunk_id` is `{origin}:{source_path}#{i}`, stored with `section_path`, `page_no` and `text`. We have not checked that every ingestion path (docling PDF and Word, Excel) builds ids the same way: see question 3.

### Proposed change

```
GET /api/v1/documents/passages?domain=<id>&path=<document>[&after=<n>&limit=<n>]
```

```json
{
  "domain": "ch",
  "document": "CH/11 - Crédito Habitação Jovem.docx",
  "title": "Crédito Habitação Jovem",
  "updated": "2026-10-05T03:42:07Z",
  "passages": [
    {"id": "…", "index": 0, "section": "Condições > Elegibilidade", "page": null, "text": "…"},
    {"id": "…", "index": 1, "section": "Condições > Montantes", "page": null, "text": "…"}
  ],
  "next": 2
}
```

- **Order and fields.** Passages come in document order (`index` = the `#i` of `chunk_id`), active ones only, with the same fields as `search` (no `score`).
- **Paging.** `after` is the `index` to start from (0 when left out); `limit` defaults to 50, at most 200. `next` is the value to send as `after` for the following page, and is absent on the last page.
- **Access.** The same check as `GET documents` (`acc.may_use(domain)` and `acc.allows_path(domain, path)`). `404` when the document does not exist or may not be read.
- **Consistency.** The `id`s are the ones `search` returns, so a passage found by search can be located inside its document.

### Use cases in this project

- **Slides from a whole document.** "Build five slides from the *Crédito Habitação Jovem* document." The assistant finds the document with `search`, reads its passages in order, and drafts the slides. Each slide's notes cite the sections it came from.
- **A run of slides on a topic.** The assistant reads the two or three documents that `search` ranks highest for the topic, in order, instead of a scatter of passages.
- **Context around a hit.** The assistant reads the passages before and after a search hit, by `index`, when a single passage is too short to write a slide from.
- **Fitting a small model.** The local model's window is 32k tokens. Paging lets us read a long document section by section within our token budget, instead of fetching a 100-page file.

### How to check

- **Match with the stored passages.** For a Markdown, a PDF and a Word document, the passages equal, in content and order, the active `Chunk` rows of that document. Each `id` resolves through `GET passages/{id}`.
- **Access.** A document in a unit the person may not read answers `404`.
- **Paging.** Pages concatenate to the whole list with no gaps or repeats.

---

## 3. A document's images

### What is missing

No route lists or returns the pictures inside a document. Our users want to reuse diagrams and photos from approved documents on their slides.

From reading Cortex's code, most of the material appears to be there already. **Please confirm:**

- **Markdown and wiki domains:** images are files in the domain (`/.attachments/…`, rewritten by `files._rewrite_images`). `GET documents` can return them once their path is known, but a client cannot list which images a document uses.
- **Word:** `files.word_content` (the viewer's `as=html`) converts the document with mammoth, images included (mammoth's default puts them in the HTML as data URIs; we have not checked Cortex's settings).
- **PDF:** ingestion-server's `chunking/pdf_docling.py` produces one region per picture item, and Cortex keeps page regions in each passage's `regions_json` (used today for citation highlights). If those regions still say which ones are pictures, Cortex could crop a picture from the page on demand, with no re-ingestion. We have not checked this: see question 4.

### Proposed change

```
GET /api/v1/documents/images?domain=<id>&path=<document>
GET /api/v1/documents/images/<image id>?domain=<id>&path=<document>
```

```json
{
  "domain": "ch", "document": "CH/02 - Fases do Processo de Crédito Habitação.pdf",
  "images": [
    {"id": "p3-1", "page": 3, "section": "Fases > Avaliação", "caption": "Figura 2 - Fluxo do processo",
     "width": 1240, "height": 860, "type": "image/png"}
  ]
}
```

- **Listing.** The images of the document, in order, with what is known about each: `page` (PDF), `section`, `caption` when the document has one, pixel size and type. The `id` only needs to be stable for as long as the document is not ingested again, as for passage ids.
- **Fetching.** The image bytes, with their own `Content-Type`. For PDF, a crop of the page at a resolution usable on a slide (for example 150 dpi). Vector images may be rasterised to PNG.
- **Limits.** A size limit per image (for example 10 MB). Images in documents the person may not read answer `404`.
- **Phasing.** If one format is much harder, start with Markdown and Word and add PDF later. Say which are covered.

### Use cases in this project

- **A diagram from a document.** "Put the process diagram from the *Fases do Processo* document on slide 4." The assistant lists that document's images, picks one by caption, section or page (or asks the user to choose), and inserts it into the slide's picture placeholder. The slide's notes cite the document and page.
- **Reuse of approved visuals.** A slide on a policy uses the figure from the approved policy document instead of a stock image, so the visual and the text come from the same source.
- **Alt text.** The caption, when present, seeds the image's alt text, which the user reviews.

### How to check

- **Listing.** For one Markdown, one Word and one PDF document with known pictures, `images` lists them all (count and order checked by eye).
- **Fetching.** Each image fetches and opens, and the PDF crops show the picture and not the surrounding text.
- **Access.** A document the person may not read answers `404` on both routes.

---

## 4. Search within named documents (optional, small)

### What is missing

`POST search` can be limited to domains, not to documents. When the user names a document, searching the whole domain lowers precision: passages from other documents compete with the named one. With change 2, reading the whole document works but costs tokens on long documents.

### Proposed change

An optional field on `POST search`: `documents: [{"domain": "ch", "path": "CH/11 - Crédito Habitação Jovem.docx"}]`. It restricts the candidates to those documents before reranking. If a listed document does not exist or may not be read, answer `404`, as for `domains`.

### Use cases in this project

- **Targeted questions about one document.** "From the *Crédito Habitação Jovem* document, add the eligibility conditions to slide 3." Search runs inside that document only, and the best passages are the eligibility ones.
- **Large documents.** In a 100-page PDF, searching inside the document finds the relevant pages without reading all its passages.

### How to check

Every returned passage belongs to a listed document. Results for a query whose best match lies in another document no longer include that document.

---

## 5. A stable link to a document (confirmation only)

### What we plan

Speaker notes should carry a link people can click to check a source. Cortex already has one: the viewer's *Download the original* address, `/cortex/api/files/content?root=<domain>&path=<document>`. It sits behind Cortex's Microsoft sign-in, answers `404` to anyone who may not read the document, and returns the original file. We plan to write it in the notes beside the title, section or page, and date.

### What we ask

- **Confirm** that this address may be used in documents that outlive a release, and will be kept or redirected if it changes. It is a route of Cortex's page, not of the versioned `/api/v1`.
- **Optionally, later:** a page address that opens Cortex's viewer at the cited section or page (for example `/cortex/?doc=<domain>/<path>#page=3`). That would let a reader see the passage in context instead of downloading the file.

---

## Questions for Cortex

1. **Change 1, network path.** Is the internal-network path plus Cortex's proxy secret the right place to accept `X-On-Behalf-Of`, or does Cortex prefer a separate route (for example `/api/v1/service/…`)?
2. **Change 1, issuing.** Should service keys be issued in the page (*Settings › API keys*) or by configuration (environment) only? We have no preference.
3. **Change 2, unit of retrieval.** Is `index` from `chunk_id` the right order for every ingestion path (Markdown, docling PDF and Word, Excel)? Are there documents whose passages are not in reading order?
4. **Change 3, PDF regions.** Does `regions_json` mark which regions are pictures, or would the PDF crop need the ingestion-server's picture items again?
5. **Versioning.** Should the changes ship together as one documented addition to the Developer SDK manual, or one by one? We can start with changes 1 and 2.
