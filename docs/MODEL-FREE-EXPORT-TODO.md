# Model-free one-book export milestone

This is Bookinator's next product milestone, ahead of Reviewer annotations and
the Author editing panel. The deliverable is a polished, interactive, static
publication of **one completed book analysis**. A recipient can inspect it on
an ordinary computer without Bookinator, Python, Ollama, a local model, or the
source manuscript.

The same artifact must support two distribution paths:

1. an editor exports a private book analysis, unzips or sends it, and the
   recipient opens `index.html`; and
2. Bookinator publishes approved public-domain examples unchanged beneath
   `book.inator.com/books/<slug>/`.

This is not a hosted Bookinator, an editable workspace, or a cloud inference
service. It is a frozen, inspectable editorial publication.

## Product promise

- Open locally by double-clicking `index.html`; do not require a local web
  server merely to read the export.
- Host the same files on any static web server without a build step.
- Preserve Bookinator's strongest interaction: every conclusion can lead back
  to its included evidence and provenance.
- Make incomplete, stale, failed, provisional, and unreviewed material honest.
  Export must not turn saved machine output into an approved editorial claim.
- Include only one book and only the sections the exporter deliberately chose.
- Omit the full manuscript by default. Selected evidence snippets are separate
  export records with visible chapter/page context.
- Do not export chapter text, a chapter-by-chapter text surrogate, or enough
  adjacent/overlapping excerpts to reconstruct substantial portions of the
  manuscript. The source PDF being absent is not sufficient protection.
- Carry no model runtime, API endpoint, writable control, analytics beacon,
  remote font, CDN dependency, or hidden request.

## Explicit non-goals for this milestone

- Running or retrying analysis.
- Editing manuscript text.
- Receiving author comments or synchronizing changes back to Bookinator.
- Accounts, authentication, revocation, access logs, or hosted collaboration.
- A complete `.bookinator` workspace backup or viewer-only workspace import.
- Automatic publication to `book.inator.com`; public examples can initially be
  copied into the website repository deliberately.
- A generic multi-book portal inside each export. The public website owns its
  gallery/catalog; every exported book remains independently viewable.

## User stories

- As an editor, I can preview exactly what another person will receive.
- As an editor, I can include or exclude each report family and individual
  sensitive evidence excerpt.
- As an author, I can open the analysis without installing anything and move
  between a claim, its chapter, and its evidence.
- As a recipient, I can tell which content came from a model, which came from a
  human reviewer, what was incomplete, and when the export was generated.
- As the maintainer of `book.inator.com`, I can add many public-domain book
  exports without building a different viewer for every title.

## Architectural spine: one canonical report manifest

Create a versioned, immutable JSON-compatible manifest before building the
viewer. The PDF and HTML exporter should eventually consume this same contract;
do not scrape the live DOM or invent a second interpretation of pipeline data.

Suggested top-level shape:

```json
{
  "schema": "bookinator-report-v1",
  "export": {
    "id": "...",
    "createdAt": "...",
    "bookinatorVersion": "...",
    "sourceFingerprint": "...",
    "manifestChecksum": "...",
    "freshness": "current"
  },
  "book": {
    "title": "...",
    "author": "...",
    "edition": "...",
    "icon": {},
    "wordCount": 0,
    "chapterCount": 0
  },
  "selection": {},
  "completeness": {},
  "provenance": [],
  "chapters": [],
  "sections": [],
  "evidence": [],
  "assets": []
}
```

The real schema must define and test:

- stable IDs for chapters, findings, questions, entities, charts, annotations,
  and evidence excerpts;
- schema version and migration/rejection behavior;
- source fingerprint, analysis/run versions, model identity, prompt/schema
  version where available, and human-review state;
- current, stale, partial, failed, provisional, and omitted states without
  treating `partial` as `complete`;
- explicit section order and visibility rather than relying on object order;
- links between claims and evidence using IDs, not copied display strings;
- a distinction between public export copy and private/internal workspace data;
- deterministic serialization so checksums and regression fixtures are useful.

## Report-section registry

Define one registry that supplies labels, descriptions, availability,
completeness, default inclusion, manifest serialization, viewer rendering, and
eventual PDF rendering. Start with:

- Orientation: book identity, export scope, completeness ledger, provenance.
- Whole-book summary and chapter summaries.
- Questions and payoffs.
- Connections: entities, locations, and their occurrence evidence.
- Emotions and other useful finished charts.
- Smells, separated into reviewed findings, informational items, dismissed
  items when deliberately included, and incomplete editorial judgments.
- Pipeline/method appendix with models, versions, duration, failures, and
  omitted passes.
- Reviewer annotations later, without changing the manifest's basic shape.
- Assessment later as a qualified, evidence-linked section rather than a
  universal score.

Unavailable sections should be absent or explicitly marked unavailable; they
must not appear as empty decorative navigation.

## Export selection and privacy boundary

Build a standard Bookinator dialog that previews the publication and controls
the manifest selection. It should use shared form controls and interaction
contracts rather than an export-only UI system.

- Select report families individually, with sensible presets such as
  **Reader**, **Editor detail**, and **Compact**.
- Show counts and state beside every selectable section.
- Default to reviewed or reportable material. Require an affirmative choice to
  include dismissed findings, failed diagnostics, or unreviewed machine output.
- List every manuscript excerpt that will leave the machine. Allow inclusion,
  exclusion, and replacement with a redacted marker.
- Never include full chapter text, source PDF, private notes, local filesystem
  paths, Ollama URLs, machine usernames, logs, raw prompts, or raw model output
  unless a later feature names and confirms that separate export explicitly.
- Sanitize HTML and text at manifest creation and again at rendering boundaries.
- Warn about stale/provisional results before generation; preserve those labels
  in the artifact if the editor proceeds.
- Provide an inspectable export inventory before download: sections, excerpts,
  files, byte size, and external requests (**zero**).

## Static viewer

Build the viewer as a small reusable static application, visually related to
Bookinator but unmistakably read-only.

- Book header with generated icon, title, author, edition/export date, and an
  unobtrusive “Made with Bookinator” link.
- Clear contents/navigation that works with keyboard, touch, narrow screens,
  reduced motion, and print.
- Overview landing page with scope, completeness, freshness, and a short guide
  to machine versus human material.
- Search across included titles, summaries, findings, questions, entities, and
  evidence without sending text anywhere.
- Deep links to sections and stable items within the export.
- Disclosures for dense evidence; do not hide essential meaning behind hover.
- Existing charts rendered read-only with accessible summaries, useful
  tooltips, and export/print behavior only where it adds value.
- A provenance/method view understandable by a curious author, plus deeper run
  detail for an editor.
- Honest empty/error treatment. A partial analysis should remain useful without
  claiming that absent results were checked and found clean.
- No controls that imply the artifact can rerun, modify, dismiss, annotate, or
  save anything.

To work over `file://`, embed the manifest in `index.html` as escaped inert JSON
or load it through a generated local script assignment. Do not depend on
`fetch("manifest.json")`, which browsers commonly restrict for local files.
Keep CSS, JavaScript, fonts, icons, and images local to the bundle.

## Packaging

The first reliable format should be a directory bundle and downloadable ZIP:

```text
shadow-bookinator-report/
  index.html
  assets/
    viewer.css
    viewer.js
    book-icon.svg
    ...included chart/image assets
  README.txt
```

- The unzipped directory opens locally and can be hosted unchanged.
- Use content-hashed or versioned asset names so hosted examples cache safely.
- Include a human-readable README explaining how to open, host, and verify the
  export and stating that it contains no model or server.
- Give files safe, portable names and avoid symlinks, absolute paths, and
  platform-specific metadata.
- Generate a ZIP checksum and store the export record in Bookinator without
  silently overwriting prior exports.
- A single-file HTML option can follow if it proves useful; do not let base64
  asset complexity delay the robust bundle.

## Public-domain gallery reuse

The gallery is a first-class reason for this architecture, not a fork.

- Let `book.inator.com` own the gallery wrapper: its normal header, navigation,
  typography, breadcrumbs, descriptive copy, and catalog cards should make the
  examples feel like ordinary links within the public website—not a detached
  second application or a directory listing.
- Maintain a catalog at `book.inator.com` with cover/icon, title, author,
  publication year, genre/tags, analysis completeness, and a link to the
  unchanged static export directory.
- Give each hosted export a clear route back to the gallery and the main
  Bookinator explanation, while keeping the downloaded/private bundle fully
  functional without the public-site wrapper.
- Avoid iframes and duplicated viewer implementations. The website supplies
  discovery and surrounding context; the generated export supplies the actual
  one-book analysis experience.
- Publish a varied corpus: novels, short fiction, nonfiction, different eras,
  genres, narrative persons, chapter structures, and lengths.
- Show source edition and public-domain basis prominently. Do not assume a work
  is public domain merely because a downloadable copy exists.
- Preserve Bookinator/model/prompt versions so visitors can compare examples
  honestly and older exports do not masquerade as current performance.
- Curate an “interesting findings” entry point for each book without hiding the
  full analysis.
- Permit regeneration as Bookinator improves while retaining prior export
  metadata or an explicit replacement history.
- Keep gallery analytics, if ever added, outside the exported book bundle so a
  privately shared artifact never acquires tracking code.

## Implementation sequence

### 1. Freeze the publication contract

- Inventory every field currently consumed by the editor PDF and Explore views.
- Define `bookinator-report-v1`, selection state, completeness semantics, and
  stable evidence links.
- Build a *Shadow* manifest fixture and at least one small public-domain fixture.
- Validate manifests server-side and in browser tests.

**Exit:** the fixture completely describes a useful export without reading live
DOM state, local files, or mutable application globals.

### 2. Extract shared report serialization

- Create server/domain serializers from canonical saved book/pipeline data.
- Move section availability and inclusion rules into the registry.
- Adapt the PDF path toward the manifest rather than duplicating selection
  rules; exact PDF convergence may finish after the first HTML slice.
- Record all omissions and degraded states in the completeness ledger.

**Exit:** identical saved state and selection produce deterministic manifest
content, and private fields have explicit exclusion tests.

### 3. Build the static viewer against fixtures

- Develop the viewer without a running Bookinator server.
- Implement navigation, search, disclosures, evidence jumps, responsive layout,
  accessibility, print CSS, provenance, and incomplete-state presentation.
- Reuse shared visual tokens deliberately, but do not import the entire live app
  or its writable controls.

**Exit:** both fixtures work from `file://` with the network disabled.

### 4. Add preview and export

- Add the standard preview/selection dialog to Explore's PDF report area or a
  shared publishing control.
- Generate the bundle, ZIP it locally, download it, and save export history.
- Show filename, size, checksum, creation time, selection, and freshness.

**Exit:** a user can export *Shadow*, unzip it on another ordinary computer,
and inspect the selected analysis without Bookinator.

### 5. Harden privacy and fidelity

- Snapshot-test manifest contents and rendered sections.
- Test adversarial manuscript strings, HTML/script injection, Unicode, very long
  titles, missing authors, missing icons, malformed analysis, and partial runs.
- Assert zero remote requests in a browser/network test.
- Diff visible section counts and key claims against the source manifest.
- Test that excluded sections, evidence, private notes, paths, and raw model
  material are absent from both ZIP bytes and rendered DOM.

**Exit:** “not visible” and “not present in the artifact” are both proven.

### 6. Publish the first public-domain collection

- Choose a small varied initial corpus with recorded source editions and rights
  evidence.
- Generate exports using the normal Bookinator pathway.
- Add the gallery/catalog using `book.inator.com`'s existing site navigation,
  cards, routes, and visual language, then link into individual exports as
  ordinary first-class site destinations.
- Review each example for genuinely compelling, evidence-linked moments rather
  than publishing a wall of mechanically generated reports.

**Exit:** visitors can immediately inspect several real books and understand
why Bookinator is different without installing it.

## Required test matrix

- Manifest schema/version validation and deterministic serialization.
- Complete, partial, failed, stale, provisional, and omitted analysis states.
- Preset and per-section selection behavior.
- Evidence allowlist/redaction and absence of forbidden private fields.
- Malicious text escaping in HTML, attributes, JSON embedding, SVG, and search.
- Offline `file://` opening in Safari, Chrome, and Edge where available.
- Responsive layouts and keyboard navigation.
- Search and deep-link behavior.
- ZIP portability and safe filenames on macOS, Windows, and Linux.
- Zero external requests and zero dependency on a Bookinator API.
- Hosted-path behavior below a non-root prefix such as
  `/books/the-time-machine/`.
- PDF/HTML section-selection parity once both use the manifest.

## Milestone acceptance

This milestone is complete when:

1. *Shadow* can produce a ZIP that opens locally on a different computer;
2. it contains only deliberately selected analysis and evidence;
3. it accurately distinguishes machine output, human judgment, incomplete
   work, provenance, and freshness;
4. its primary views are pleasant and useful on desktop and phone;
5. it performs no network request and requires no runtime;
6. one public-domain export can be hosted unchanged under
   `book.inator.com/books/<slug>/`; and
7. adding another public-domain book is a content operation, not a new viewer
   implementation.

## Decisions to make while building, not before

- Whether public examples expose all dismissed/informational findings or use a
  curated preset.
- Whether charts remain inline SVG or become serialized chart data rendered by
  the viewer.
- Whether the initial exporter lives in the browser or server; manifest
  generation should remain domain logic either way.
- Whether a compact single-file HTML export is worth supporting after the ZIP
  bundle is proven.
- The initial public-domain corpus size and order. Variety and compelling
  examples matter more than a large undifferentiated count.
