# Chapter 1 qualitative review

Observed 2026-10-16 against the isolated public-domain *The Dunwich Horror*
acceptance specimen. This is a human/LLM editorial assessment layered on top of
the machine-verifiable report in `chapter-1.json`; it does not alter the
generated artifacts.

## What worked

- The pipeline reached and locked the declared development checkpoint.
- Summary, Dossier, and Review projections were nonempty and durable.
- All 46 emitted evidence anchors matched the canonical chapter source exactly.
- The summary captured the chapter's broad function: establishing Dunwich's
  landscape, history, social isolation, and supernatural unease.

## Material defects the automated verifier missed

- The cast contains duplicate Whippoorwills and Satan records.
- Mentioned abstractions or traditions (for example Satan-worship and
  witch-blood) are promoted to cast entities, weakening the meaning of “cast.”
- A key point calls whippoorwills psychopomps although its attached quotation
  only describes their sound and the surrounding marshland.
- The summary claims the chapter ends with Reverend Hoadley's sermon. Considerable
  historical and folkloric material follows it; the ending-state check therefore
  certified the wrong boundary.
- Several questions are generic promises about later supernatural events rather
  than discriminating editorial questions grounded in this chapter.
- The editorial Review returns “no material concerns” and no proposals. For this
  acceptance purpose that output is uninformative, even if the source is a
  canonical published work.
- The consistency pass reports no issues and does not reconcile duplicate cast
  entries, the unsupported psychopomp interpretation, or the false ending claim.

## Verdict

Operational checkpoint behavior and provenance integrity pass. Editorial
usefulness is provisional and fails the stronger human-quality bar. Do not use
the successful anchor count as a proxy for interpretive correctness.
