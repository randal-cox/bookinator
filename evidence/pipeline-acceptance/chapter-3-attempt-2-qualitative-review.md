# Chapter 3 attempt 2 qualitative review

Date: 2026-10-16

Fixture: public-domain *The Dunwich Horror*

Model: `qwen2.5:7b`
Disposition: rejected after machine completion

## Material improvement

The strengthened ending obligation worked. The Summary reached the 1917 draft
board, government investigation, newspaper attention, and public exposure that
attempt 1 omitted. All 30 retained evidence anchors matched the canonical
source exactly. The Review populated all ten dimensions and every applicable
dimension retained exact source evidence. The operational pipeline then
completed Context, Emotions, Tags, and Smells and locked the third development
checkpoint.

## Why the apparent pass was rejected

The normalized cast was not referentially sound:

- the consistency model supplied off-by-one cast corrections that renamed
  adjacent candidates;
- the application accepted those canonical-name changes without proving that
  the old and new labels co-occurred as aliases;
- Summary and Dossier records still referred to removed IDs `G001`, `G003`,
  `G004`, and `G005`; and
- the final cast contained only Wilbur, Lavinia, and Squire Sawyer Whateley,
  while projections still relied on Old Whateley and other removed identities.

The Summary also asserted that Wilbur was "the son of Old Whateley." The local
chapter establishes the relevant relationship as grandson, not son. Exact
anchors elsewhere in the artifact did not make this unsupported prose claim
safe.

The evidence collector therefore failed both semantic hygiene and the new
referential-integrity check. Machine completion, exact quotations, populated
rubric fields, and a locked checkpoint were all insufficient.

## Resulting contract changes

- A cast correction may change a canonical name only when one exact source
  quotation contains both the prior and proposed labels.
- Projection subject IDs are matched case-insensitively and must resolve to a
  surviving canonical cast record.
- Compact kinship assertions in Summary prose require local source support.
- The acceptance collector independently reports unresolved subject IDs and
  unsupported kinship claims.

No raw manuscript or generated response is committed with this review. The
machine report retains hashes, counts, and the exact failed obligations.
