# Chapter-map benchmark

Chapter structure is load-bearing. A false boundary can invalidate hours of downstream analysis, while a noisy warning teaches users to approve maps without reading them. We will not tune this detector from a handful of memorable books.

## What the lab tests

`bin/chapter-map-lab` calls the same extraction and chapter-detection functions as the production pipeline. It does not copy or simplify the heuristic. For each source it records:

- immutable source checksum, format, size, and span count;
- detected boundaries and labels;
- EPUB navigation labels when available;
- excluded page-opening candidates and current warnings;
- runtime and source revision;
- a provisional inspection queue; and
- a separate human verdict and note.

EPUB navigation is comparison evidence, not ground truth. A publisher can include title pages, parts, appendices, nested headings, or a broken table of contents. The review surface deliberately shows both lists without treating either as authoritative.

## Run it

Acquire the initial public-domain cohort through Gutenberg's supported catalog
and robot-harvest endpoints (the default two-second delay is deliberate):

```sh
./bin/build-chapter-map-corpus
```

This writes sources and a resumable provenance/checksum manifest under
`.bookinator/benchmarks/chapter-map-corpus/`, outside Git. The base cohort is
300 distinct EPUB works with 50 matched plain-text editions for immediate
cross-format comparisons. PDF/OCR and genuine DOCX sources remain separate
acquisition cohorts; generated conversions must not be counted as substitutes.

### First corpus run — September 26, 2026

- Acquired 300 distinct English-language works and 350 format specimens: 300
  EPUB plus 50 matched UTF-8 plain-text editions (109,723,659 source bytes).
- Verified every downloaded file against the checksum in the corpus manifest.
- The production detector processed all 350 without a runtime error: 117 auto
  candidates, 215 mention candidates, and 18 block candidates.
- Forty-five of 50 EPUB/text pairs produced different detected chapter counts,
  often by a large margin. Import format is therefore a first-order structural
  variable and must be measured separately from heading classification.
- Fourteen mismatched pairs were labeled auto candidates in both formats, and
  31 mismatched pairs had at least one format labeled auto. Direct source
  checks show that the plain-text path can miss obvious `CHAPTER` headings
  that occur inside its synthetic spans—for example, finding 9 of 24 chapters
  in one novel and 1 of 14 in another. The provisional auto tier is therefore
  not safe to ship until non-paginated heading detection is repaired and this
  paired cohort is rerun.
- All 18 inspect-first candidates now have source-adjudicated verdicts: 14 are
  detector failures, three are genuinely ambiguous structures that should
  block for review, and one is a usable map that deserves only a mention.
  Confirmed failures include omitted opening chapters, lost Part hierarchy,
  duplicated or reordered divisions, and substantive appendices discarded as
  though they were boilerplate. The one false block correctly found all 62
  chapter boundaries but compared abbreviated Roman-numeral labels too
  literally against the EPUB's descriptive navigation titles.

These are baseline observations, not detector accuracy rates. The 215 mention
candidates and 117 auto candidates still need sampled human judgment, and the
native-text PDF, scanned-PDF-with-embedded-OCR, and genuine DOCX cohorts have
not yet been assembled. Bookinator does not currently perform OCR itself.

### First detector repair

The paired-format failure led to a deliberately narrow repair: native
plain-text imports now preserve explicit `CHAPTER`, `PROLOGUE`, `EPILOGUE`,
and repeated Roman/Arabic heading blocks as virtual-page boundaries. Contents
rows with trailing page numbers are excluded, duplicate visible/markup labels
collapse to one boundary, and isolated numbers do not establish a chapter
spine.

The full 350-specimen rerun completed without an error. Among the 50 paired
works, authored chapter-count disagreements (excluding Bookinator's synthetic
`Front matter` segment) fell from 44 to 25. Pairs rated auto in both formats
but still disagreeing fell from 14 to three. Those three are now useful EPUB
regressions rather than an undifferentiated format problem:

- *The Call from Beyond* detects four authored chapters in text but only two
  in EPUB.
- *The Shades of Toffee* detects thirteen in text but eight in EPUB.
- *A Trace of Memory* detects eighteen authored divisions in text but twelve
  in EPUB.

In each case the missing EPUB labels exist inside reflowed content rather than
at the current virtual-page openings. A trial that preserved every plain EPUB
heading changed 219 of 300 EPUB maps and moved 14 confidence tiers, so it was
rejected rather than shipped on the strength of three improvements. The safe
text repair remains; EPUB needs a structure-aware extractor that can use its
markup and spine without promoting contents rows or inline false positives.
The inspectable repaired run is stored locally at
`.bookinator/benchmarks/chapter-maps-after-text-headings-v3/index.html`.

### EPUB structural repair

The EPUB follow-up now uses document structure rather than treating the
reflowed book as vaguely paginated prose. It preserves chapter-family labels
introduced by semantic chapter rules such as `hr.chap`, separates compound
book-title/chapter/title headings, and removes HTML `head` metadata before
Project Gutenberg boilerplate detection. That last change prevents a license
document title from truncating a legitimate epilogue that precedes the actual
footer. Plain-text contents headers such as `CHAPTER I. PAGE` are also rejected
as boundaries.

Appendices, prologues, epilogues, interludes, and front matter now carry an
explicit analysis role. Substantive appendices remain analyzable divisions;
they are not silently discarded as boilerplate. EPUB navigation comparison
matches structural ordinal identity, so `CHAPTER XIV`, `Chapter Fourteen — A
Title`, and `XIV` can corroborate one another without requiring identical
display text.

The second full 350-specimen rerun completed without an error: 133 auto
candidates, 199 mention candidates, and 18 block candidates. The 50 matched
EPUB/text works now have 13 authored chapter-count disagreements, down from 44
at baseline and 25 after the text-only repair. Six remaining mismatches involve
one auto candidate, but **none are auto candidates in both formats**. The three
previously identified EPUB regressions now agree across formats.

The inspectable run is stored locally at
`.bookinator/benchmarks/chapter-maps-after-epub-structure-v2/index.html`.
Known nested structures—Parts or Books containing repeated Roman-numbered
subsections, anthologies, periodicals, and similarly ambiguous collections—are
deliberately not flattened by guesswork. Bookinator preserves the inexpensive
source/chapter/chunk artifacts, then pauses derived analysis for human review.
A future hierarchy chooser should let an editor select the analysis level
rather than hiding that product decision inside the detector.

```sh
./bin/chapter-map-lab .bookinator/benchmarks/chapter-map-corpus/sources \
  --output .bookinator/benchmarks/chapter-maps
```

Open `.bookinator/benchmarks/chapter-maps/index.html`. Reviews persist in that browser and can be downloaded as `chapter-map-reviews.json`. Machine output remains in `results.json`, so a detector change can be run again without confusing new output with old human judgments.

To carry a shared review ledger into a new detector run, add `--reviews chapter-map-reviews.json`. Review records bind to the source checksum, so renamed files retain their judgment while changed editions do not inherit one accidentally.

Use `--limit 20` for a deterministic smoke test. Point the command at multiple files or directories for a full run. Generated benchmark artifacts belong under `.bookinator/` and are intentionally not committed.

## Corpus target

The first confidence gate is **300 independently inspectable works**, followed by a 1,000-work unattended regression sweep. The 300-work set should be deliberately stratified rather than “the first 300 files we found”:

| Cohort | Minimum | Why |
| --- | ---: | --- |
| EPUB novels and novellas | 140 | Dominant import path; navigation supplies useful comparison evidence |
| Plain text and Markdown | 50 | Weak or explicit structure without package metadata |
| PDF, including native text and scans with embedded OCR text | 50 | Page-opening noise, running heads, title pages, and geometry |
| DOCX manuscripts | 30 | Real author workflow and style-driven headings |
| Same work in two formats | 30 pairs | Finds importer differences that masquerade as detector differences |

Across those formats, deliberately include numbered and named chapters, parts plus chapters, prologues and epilogues, appendices, letters, dates as headings, repeated viewpoint labels, short stories, plays, nonfiction, front matter, unchaptered works, and malformed source files.

Appendices are not presumed disposable. The benchmark should separately score
whether Bookinator finds their boundaries, labels them as back matter, and
preserves substantive appendix content for role-aware analysis. Only actual
boilerplate—licenses, navigation debris, publisher ads, and similar non-book
material—should be expected to disappear.

For public-domain acquisition, use a local Project Gutenberg mirror or its documented robot-harvest/offline-catalog routes; do not crawl human-facing ebook pages. Preserve source URLs, edition notes, rights statements, checksums, and acquisition dates in a corpus manifest. Keep the large source corpus outside Git; keep a small, redistributable regression shelf in `demo-corpus/`.

## Human judgments

Every specimen receives one of four verdicts:

- **Pass** — boundaries and order are usable without intervention.
- **Mention** — the map is usable, but a non-blocking note would help.
- **Block** — analysis should wait for a person because the ambiguity is real.
- **Fail** — Bookinator silently produced a materially wrong map.

Randal and Codex should independently inspect the “inspect first” cohort and a random sample of the other tiers. Disagreements are adjudicated against the source. Review notes should identify false boundaries, missed boundaries, ordering errors, front-matter leakage, label problems, or source corruption.

## Release gate

Do not promote the proposed confidence tiers into production merely because the aggregate chapter counts look plausible. Before changing warning behavior:

1. Review all provisional block candidates.
2. Review all machine errors.
3. Randomly review at least 75 mention candidates and 75 auto candidates.
4. Require zero silent catastrophic maps in the curated regression shelf.
5. Measure false-safe and false-block rates separately by format and structure family.
6. Freeze every confirmed failure—and a representative set of successes—as regression fixtures.

The initial numerical goals are hypotheses, not a way to game the detector: under 1% materially unsafe maps in the auto tier, under 10% needless blocks, and no known repeatable catastrophic failure. The benchmark should make failures legible; human review decides whether those targets are strict enough.
