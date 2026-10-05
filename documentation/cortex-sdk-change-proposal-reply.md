# Reply: additions to the Cortex integration API (`/api/v1`) for the AI Slide Assistant

**From:** Cortex. **To:** the AI Slide Assistant project (`~/env/assets/pptx`).
**Replies to:** `cortex-sdk-change-proposal.md` (2026-10-05). **Date:** 2026-10-05. **Status:** all five changes
implemented, checked and documented in the Developer SDK manual.

Thank you for a precise proposal. Its description of today's API was correct: we checked it against `cortex/api/v1.py`
and the Developer SDK manual. Below, for each change: what we found in Cortex's code and data, what was built, and
where it differs from your contract. Everything stated as a fact was checked on the running Cortex and its knowledge
bases on 2026-10-05 (`tests/v1_check.py`, `tests/ui/links.mjs`).

| # | Change | State |
|---|---|---|
| 1 | Calls on behalf of the signed-in person | **Done**, with a different way in: an internal service address, never Cortex's proxy secret (1.1) |
| 2 | A document's passages, in order | **Done**, with two corrections to the contract (2.1) |
| 3 | A document's images | **Done** for PDF, Word and Markdown (3) |
| 4 | Search within named documents | **Done**: the named documents' passages are ranked, not searched for (4) |
| 5 | A stable link to a document | **Done**: a `link` on every passage, opening Cortex's viewer at the page or section (5) |

## Start here

1. **Ask a Cortex administrator for a service key** for the AI Slide Assistant (*Settings › API keys › New service
   key*; optionally limited to the domains your projects use). It looks like `ctxs_…` and is shown once.
2. **Call from your server, on the Docker network** (`logus2k_network`), at
   `http://proxy_server:8710/cortex/api/v1/` (on a Cortex installed with its own deploy stack:
   `http://cortex-proxy:8710/api/v1/`). That address is not reachable from outside.
3. **Send on every call** `Authorization: Bearer <service key>` and `X-On-Behalf-Of: <the signed-in person's address>`,
   the address your own sign-in gives you for the user (the one Microsoft Entra ID gave them), never one from a
   browser page or a request field.
4. Read **Help › Developer SDK** in Cortex (or `static/help/sdk/`): *Create an API key… (and service keys)*, *Search for
   passages* (`documents`), *Get a cited passage, a document, its passages or its images*, *Errors, limits*.

---

## 1. Calls on behalf of the signed-in person

### 1.1 What we found: the proxy secret is a master key

Your plan had your server call `http://cortex:2710/api/v1/…` with Cortex's proxy secret. That secret must not leave
the domain proxy:

- Cortex refuses every request without the secret (`X-Cortex-Proxy-Secret`). With it, Cortex's **page** routes trust
  the identity in `X-Auth-Request-Email`, whatever it says. A server holding the secret could act as **any person,
  administrators included**, on every route, including those that change data, without any key.
- The secret does not tell an internal call from a public one: the proxy's public `/cortex/api/v1/` route sends the
  same secret. Only what the proxy passes on or clears separates them.

### 1.2 What was built

A **service key**, as you proposed: issued by administrators in *Settings › API keys* (`ctxs_…`, only its SHA-256
kept, shown once), with an optional domain ceiling; listed with its kind, last use and call count; issuing and
revoking in the audit log. Cortex answers with `access.for_user(<person>, scoped=False)`, so roles, grants and units
apply unchanged, within the ceiling. Where it differs from your proposal:

- **The way in.** The domain proxy has a second server, on port 8710, which its compose file does not publish: only a
  container on the Docker network reaches it. It alone passes `X-On-Behalf-Of` on to Cortex, adding the secret itself;
  the public `/cortex/api/v1/` route empties `X-On-Behalf-Of`. Your server never holds the secret, and a leaked
  service key used from outside is refused.
- **Errors.** A service key without `X-On-Behalf-Of`, or with a value that is not an address: `400`. A personal key
  **with** `X-On-Behalf-Of`: `400` (refused, not ignored). Revoked or expired: `401`.
- **Rate limit.** 60 a minute per (service key, person), and 600 a minute per service key.
- **Accountability.** Every call is logged with the service key and the person's pseudonym (`userId`, never the
  address). Reads stay out of the audit table.

**Checked:** for two people with different grants, `domains` through the service key equals each person's own
personal key (a domain only the administrator holds appears for them only, and its document is `404` for the other);
the ceiling limits `domains`, `search` (with and without `domains`) and named domains (`404`); 62 quick calls for one
person give 60 × 200 and 2 × 429 while another person still gets 200; through the public route `400`, through the
internal one `200`; a personal key on the internal route with the header `400`; revoked `401`; issuing and revoking
audited without the secret.

**Later:** a header asserted by a service is still a claim; whoever holds the service key can name any person. The
stronger form is a Microsoft Entra **on-behalf-of token** that Cortex validates (reading the person's immutable id,
`oid`). It needs Cortex to key people by their Entra object id instead of their address, which is planned
(accountability plan, step 3). It will come as a `v1` addition; the service key keeps working.

## 2. A document's passages, in order

### 2.1 What we found

We read every PDF and Word document in the knowledge bases (2 PDFs, 17 Word documents) and the ingestion code:

- **The `#i` of `chunk_id` is not a position.** For documents ingested by Cortex it counts from 0 in each document. For
  documents ingested by devaikb (the `bancoctt` domain) it counts across the whole corpus: only 4 of 2,122 documents
  start at 0. Within a document the numbers are always contiguous and in reading order.
- **PDFs carry section roll-ups after their passages.** ingestion-server (`chunking/pdf_docling.py`,
  `_add_super_parent_chunks`) appends, after the reading-order passages, one passage per top-level section with two or
  more subsections: the section's heading followed by all its subsections' text, for broad questions. It repeats the
  document. *BCTT - Arquitetura DC v5.pdf* has 611 passages in reading order and then 32 roll-ups that start again
  from page 4; the other PDF has 41 and 3.
- Word documents have no roll-ups; Markdown and spreadsheets are chunked by Cortex in reading order.

### 2.2 The contract

```
GET /api/v1/documents/passages?domain=<id>&path=<document>[&after=<n>&limit=<n>]
```

```json
{
  "domain": "ch",
  "document": "CH/11 - Crédito Habitação Jovem.docx",
  "title": "11 - Crédito Habitação Jovem",
  "updated": "2026-10-01T22:36:25Z",
  "total": 13,
  "passages": [
    {"id": "a0e06fa7fb6b", "index": 0, "section": "… > O que é o Crédito Habitação Jovem", "text": "…", "link": "https://…"},
    {"id": "e39c12896d2e", "index": 1, "section": "… > Critérios de Elegibilidade", "text": "…", "link": "https://…"}
  ],
  "next": 2
}
```

As you proposed, except:

- **`index` is the passage's position in the document** (0, 1, 2… in reading order), not the `#i` of `chunk_id`.
- **Roll-ups are left out**: the list is the document once. A roll-up is recognised by what it is built from: it
  contains the whole text of another passage of the same document. `total` counts the passages listed.
- **A search hit may be a roll-up**, and then its `id` is not in the list; its `section` names the section to read.
- `page` when the document has pages (PDF). `after`/`limit`/`next` as you proposed (50 by default, at most 200).

**Checked** against the stored passages read directly from the database: a Markdown (3) and a Word document (13) come
out whole and in stored order; the 643-passage PDF as its 611 reading-order passages, pages non-decreasing, without
the 32 roll-ups (each repeats listed text); paging gives the same list; ids resolve through `GET passages/{id}`;
`400`/`404` as documented. Two things to know:

- **Word passages start with their place in the document** (`title > section > subsection`): that is how
  ingestion-server stores them, to help search. Strip it if you quote the text.
- **The rate limit counts every page.** Use `limit=200` for long documents (the 643-passage PDF is 4 calls).

## 3. A document's images

```
GET /api/v1/documents/images?domain=<id>&path=<document>
GET /api/v1/documents/images/<image id>?domain=<id>&path=<document>
```

The list (in reading order) gives each image's `id`, `page` (PDF), `section`, `caption` (Markdown and Word: their
alternative text), `width`, `height`, `type`, and `repeats` for a picture on many pages; the second route returns
its bytes with its own `Content-Type`. `404` for a document or image that does not exist or may not be read, `413`
over 10 MB.

- **PDF:** the regions stored for citations do not mark pictures (your question 4: they are `{page_no, bbox}` only).
  So Cortex reads the PDF itself (pypdfium2): each image object on each page, cropped from the page at 150 dpi as
  drawn there. A picture repeated on many pages (a logo) is listed once; one smaller than a third of an inch on a side
  is left out. Diagrams drawn as vector lines and text are not images in a PDF and are not listed. No re-ingestion.
- **Word:** the images embedded in the document. No Word document in today's knowledge bases has one, so this path
  could not be checked on real data.
- **Markdown and wiki:** the images a page shows that are files of its domain (a wiki's `/.attachments/` included);
  images on the web are not listed.

**Checked:** *BCTT - Arquitetura DC v5.pdf* lists 32 images, each with its page and section; the crops looked at (a
sequence diagram on page 42, an app screen on page 12) are exactly the pictures, without the surrounding text. A
wiki page with five attachment images lists the five; each fetches as an image.

## 4. Search within named documents

Your field, `documents: [{domain, path}]` (1 to 10), on `POST search`. Cortex keeps or drops passages by unit
**after** the search engines pick candidates, so a document filter applied that way would starve (in a domain of
2,000 documents the named one's passages are often not among the candidates). Instead, **all** of the named
documents' passages (roll-ups excluded) are ranked against the query by Cortex's reranker and the best `top_k`
returned; at most 1,500 passages in one call. The answer adds `documents`. `404` for a document that does not exist
or may not be read; with `domains` too, the documents must lie in them (`400`).

**Checked:** "Débitos diretos" inside the 643-passage PDF returns five of its passages, best first, the best one its
"Gestão de débitos diretos" table (page 16); a question whose answer is in another document still returns only the
named one's passages.

## 5. A stable link to a document

Every passage (search, ask's passages, a document's passages, a single passage) carries `link`: Cortex's page at the
document, at its page (PDF) or section, behind Cortex's sign-in:

```
https://logus2k.com/cortex/?open=<domain>&path=<document>[&page=<n>|&section=<heading>]
```

Cortex opens the document there, then takes the parameters off the address. This form is kept stable like `/api/v1`:
write it in speaker notes. `/cortex/api/files/content` stays an internal route of the page; do not use it.

**Checked:** a link opens *BCTT - Arquitetura DC v5.pdf* at page 11, also when the same document's tab is being
reopened at that moment, and a Word document scrolled to its section's heading.

## Your questions

1. **Network path for change 1:** the proxy's internal service address, not the proxy secret (1.1, 1.2).
2. **Issuing service keys:** in the page (*Settings › API keys › New service key*), administrators only, audited.
3. **Order of passages:** contiguous and in reading order within each document for every ingestion path, but `#i`
   does not start at 0 for devaikb's documents, and PDFs end with section roll-ups (2.1). The new route handles both.
4. **PDF regions:** they do not mark pictures (3); Cortex reads the PDF's images itself.
5. **Versioning:** each change is a documented `v1` addition (new routes, new optional fields); all five are shipped.
