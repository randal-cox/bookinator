# Public-domain demo corpus

## Purpose

Build a varied, legally legible corpus for Bookinator ingestion, whole-book analysis, regression testing, and public demonstrations. The first cohort deliberately favors books published from 1928 through 1930: modern enough to stress contemporary narrative machinery, but unambiguously in the United States public domain as of 2026 when sourced from the editions identified below.

This is a provenance record, not legal advice. Public-domain status varies by country. Before redistributing any text, retain the source page, source edition, acquisition date, and the source's own rights statement. Repository visibility is not itself evidence that a work is public domain.

## Format policy

Acquire source files from Project Gutenberg, Standard Ebooks, Wikimedia Commons, or another institution that identifies the work and its rights status. Prefer:

1. EPUB for reflow and chapter-structure testing.
2. Plain text for encoding and structure-recovery testing.
3. Scanned PDF for OCR, page geometry, headers, and page-number provenance.
4. Markdown and DOCX derived locally from an authoritative public-domain text, with the derivation recorded in the manifest.

Do not use a questionable mirror merely to obtain a format. A derived fixture is safer and more reproducible.

## First cohort

| Work | Year | Genre / structural value | Primary source | Planned fixture | Why Bookinator wants it |
|---|---:|---|---|---|---|
| *The Maltese Falcon* — Dashiell Hammett | 1930 | Noir / detective | [Project Gutenberg 77600](https://www.gutenberg.org/ebooks/77600) | EPUB | Dense deception, aliases, object continuity, and clue knowledge across a compact plot. |
| *Murder at the Vicarage* — Agatha Christie | 1930 | Village mystery | [Project Gutenberg 78220](https://www.gutenberg.org/ebooks/78220) | TXT | Large suspect set, alibis, times, competing testimony, and a long clue ledger. |
| *Strong Poison* — Dorothy L. Sayers | 1930 | Detective / courtroom | [Project Gutenberg 78157](https://www.gutenberg.org/ebooks/78157) | EPUB | Evidence chains, trial facts, investigative delegation, and relationship development. |
| *The Roman Hat Mystery* — Ellery Queen | 1929 | Fair-play mystery | [Project Gutenberg 76339](https://www.gutenberg.org/ebooks/76339) | scanned or generated PDF | A map, explicit clue inventory, large cast, time window, and reader challenge. |
| *The Seven Dials Mystery* — Agatha Christie | 1929 | Conspiracy mystery | [Project Gutenberg 75288](https://www.gutenberg.org/ebooks/75288) | EPUB | Secret identities, organization membership, reversals, and object clues. |
| *The Sound and the Fury* — William Faulkner | 1929 | Literary modernism | [Project Gutenberg 75170](https://www.gutenberg.org/ebooks/75170) | EPUB | Multiple narrators, nonlinear chronology, repeated events, and unstable naming. |
| *Passing* — Nella Larsen | 1929 | Harlem Renaissance / psychological | [Wikimedia Commons scan](https://commons.wikimedia.org/wiki/File:Passing_(1929).pdf) | scanned PDF | Ambiguous motivation, social identity, unreliable inference, and deliberate uncertainty. |
| *The Well of Loneliness* — Radclyffe Hall | 1928 | Literary / queer fiction | [Project Gutenberg 73042](https://www.gutenberg.org/ebooks/73042) | TXT | Long character arc, changing relationships, setting continuity, and period terminology. |
| *A Farewell to Arms* — Ernest Hemingway | 1929 | War / romance | [Project Gutenberg 75201](https://www.gutenberg.org/ebooks/75201) | DOCX derived from PG text | Travel chronology, military events, injuries, relationship arc, and intentionally sparse exposition. |
| *The Dunwich Horror* — H. P. Lovecraft | 1929 | Cosmic horror novella | [Project Gutenberg 50133](https://www.gutenberg.org/ebooks/50133) | Markdown derived from PG text | Short control case with family history, dates, occult rules, and escalating reveals. |
| *Gladiator* — Philip Wylie | 1930 | Proto-superhero SF | [Project Gutenberg 42914](https://www.gutenberg.org/ebooks/42914) | TXT | Stable capability rules, secrecy, life-stage chronology, and repeated ethical conflicts. |
| *Last and First Men* — Olaf Stapledon | 1930 | Future history / science fiction | [Project Gutenberg 79003](https://www.gutenberg.org/ebooks/79003) | EPUB | Extreme timescale, many human species, global events, and intentionally compressed narrative. |

## Second cohort

Add these after the first twelve complete one clean end-to-end run:

- *As I Lay Dying* — William Faulkner (1930): many narrators, journey chronology, repeated perception.
- *The Secret of the Old Clock* — Carolyn Keene (1930): juvenile mystery, editions must be pinned because later revisions remain protected.
- *Vile Bodies* — Evelyn Waugh (1930): ensemble satire, social aliases, episodic structure.
- *Cakes and Ale* — W. Somerset Maugham (1930): memory, literary reputation, nested recollection.
- *Red Harvest* — Dashiell Hammett (1929): large faction graph, violence chronology, shifting alliances.
- *Quicksand* — Nella Larsen (1928): location changes, identity, relationships, and repeated social pressures.
- *The Bishop Murder Case* — S. S. Van Dine (1928): symbolic clue system and serial crimes.
- *The Greene Murder Case* — S. S. Van Dine (1928): family graph, inheritance motives, and accumulating evidence.
- *The Purple Cloud* — M. P. Shiel (1901): older, but useful later as a long first-person unreliable-narrator stress test.
- A public-domain nonfiction book and a short-story collection, to ensure Bookinator does not assume every imported book is a conventional novel.

## Science-fiction depots

### SF Supernova

[SF Supernova](https://sfsupernova.com/library/) currently describes a library of 4,170 public-domain science-fiction titles, including 538 dated to the 1960s, seven to the 1970s, and five to the 1980s. This is probably the depot remembered from the earlier analysis.

Treat it as a discovery index, not yet as the corpus authority. For every post-1930 title, record why the particular edition is in the U.S. public domain—failure to renew, publication without a compliant notice, government authorship, explicit dedication, or another title-specific basis—before downloading it into a redistributable demo set.

### SF Nexus / Temple Paskow corpus

The [SF Nexus extracted-features dataset](https://huggingface.co/datasets/SF-Corpus/EF_Full_Texts) covers 403 mid-century books, especially New Wave-era works from 1964–80. Its own dataset card says the underlying fiction is copyrighted and the books were disaggregated for non-consumptive research. Use it to study evaluation methods or metadata, not as a source of redistributable whole books.

### Standard Ebooks

[Standard Ebooks](https://standardebooks.org/) is the preferred EPUB source when it has a title. Its editions are carefully produced, its source repositories are inspectable, and its ebook production files are dedicated to the public domain. Project Gutenberg remains the broadest source for plain text and alternate ebook formats.

## Evaluation design

Do not merely run the books and collect attractive reports. For each work:

1. Record source, edition, checksum, format, file size, and acquisition date.
2. Preserve the untouched source file beside any derived fixture.
3. Create five to fifteen human-written expectations: known chronology traps, identity ambiguity, clue dependencies, recurring objects, or deliberately unresolved questions.
4. Grade findings as useful, plausible but wrong, distracting, or harmful.
5. Record time to verify or dismiss each finding from its cited passages.
6. Compare formats of the same book where useful. Differences are importer failures, not model-quality differences.
7. Publish only source texts whose redistribution status is recorded; reports can link to externally hosted source files when bundling is undesirable.

## Recommended first run

Start with four books rather than twelve:

1. *The Dunwich Horror* — short Markdown control.
2. *The Maltese Falcon* — compact, clue-dense EPUB.
3. *Passing* — scanned PDF with ambiguity that should resist overconfident findings.
4. *The Sound and the Fury* — deliberately difficult chronology and narration.

That quartet gives us format diversity and four very different failure modes before we spend local-model time on the full cohort.
