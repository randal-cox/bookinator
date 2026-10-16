# Chapter 2 qualitative review

Observed 2026-10-16 against the second authored chapter in the isolated
public-domain *The Dunwich Horror* specimen. The artifact was produced by
`chapter-reading-v5` before the quality contracts were strengthened.

## What worked

- The visible production command advanced the checkpoint from Chapter 1 to
  Chapter 2 without changing Chapter 1's artifact hash.
- Summary, Dossier, Review, Emotions, Tags, Smells, and deterministic Context
  completed, after which the pipeline locked a second development checkpoint.
- Summary, Dossier, and Review were visibly `running` together while the
  combined read was active; the Dossier state was durable in its chunk artifact.
- All 32 normalized evidence anchors matched the canonical source at their
  declared offsets.

## Material defects

- The summary again stopped before an anchored final-quarter movement while
  the old coverage rule called the absence of late evidence a pass.
- Old Whateley's cast role incorrectly made him father to both Wilbur and
  Lavinia. The attached quotation established neither that relationship nor
  Wilbur's presence, yet the consistency pass called it accurate.
- Alderney cows were promoted into the cast participant ledger.
- The consistency model emitted verbose “keep” decisions for every accepted
  candidate and “no changes needed” cast corrections, despite instructions to
  report only actual corrections and rejections.
- Every applicable Review dimension initially contained evaluative paraphrase
  where verbatim evidence was required. Normalization correctly discarded the
  fake quotations, leaving all ten evidence arrays empty; the old acceptance
  gate did not object.
- The generated questions remain broad and generic rather than sharply tied to
  an unresolved causal, relational, or continuity pressure.

## Resulting contracts

The next prompt/schema version requires one canonical cast record per
participant, excludes concepts and incidental ontology terms from cast,
generalizes unanchored kinship roles instead of publishing them, gives the
consistency verifier an explicit terminal-source obligation, refuses missing
final-quarter coverage, accepts only rejection decisions from that verifier,
and requires exact evidence-reference objects for every applicable Review
dimension.

## Verdict

Operational checkpoint behavior, persistence, and provenance pass. Editorial
quality fails the strengthened acceptance gate. The retained failure is the
before specimen for `chapter-reading-v6`.
