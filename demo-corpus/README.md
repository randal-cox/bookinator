# Bookinator demo corpus

This directory contains source books, derived fixtures, and the machine-readable acquisition catalog for the public-domain demo corpus. The first four books were acquired on September 23, 2026.

See [`../docs/research/public-domain-demo-corpus.md`](../docs/research/public-domain-demo-corpus.md) for selection, provenance, format, and evaluation policy.

Before adding a source file:

1. Confirm that the source page identifies the work as public domain in the United States.
2. Record the exact edition and download URL.
3. Save a SHA-256 checksum and acquisition date.
4. Keep source files distinct from locally derived Markdown or DOCX fixtures.
5. Do not add post-1930 SF merely because an index labels it public domain; record the title-specific copyright basis first.

## Current starter set

- `sources/maltese-falcon/the-maltese-falcon.epub` — source EPUB
- `sources/sound-and-the-fury/the-sound-and-the-fury.epub` — source EPUB
- `sources/passing/passing-1929.pdf` — scanned source PDF
- `sources/dunwich-horror/the-dunwich-horror.txt` — source plain text
- `fixtures/the-dunwich-horror.md` — locally derived Markdown control

The `artifacts` records in `catalog.json` contain exact download URLs, byte sizes, acquisition dates, derivation notes, and SHA-256 checksums. “Public domain” here means the recorded source represents the item as public domain in the United States; it is not a claim about every edition or jurisdiction.

## Chapter-map benchmark

Run the production structure detector over the locally available corpus without adding books to the library or starting model work:

```sh
./bin/chapter-map-lab demo-corpus/public-domain \
  --output .bookinator/benchmarks/chapter-maps
```

The generated review surface keeps source-navigation evidence, detector output, and human judgments separate. See [`../docs/research/chapter-map-benchmark.md`](../docs/research/chapter-map-benchmark.md) for the 300-work confidence gate and corpus policy.
