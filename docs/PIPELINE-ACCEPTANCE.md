# Pipeline acceptance assay

Bookinator's ordinary tests do not claim that a local model can process a real
manuscript. Before a milestone or pipeline release, run a bounded live assay in
an isolated data root with a public-domain fixture. The assay must use the
ordinary browser/API pipeline controls, stop at a development checkpoint, and
preserve evidence without committing manuscript or model-response prose.

## Required journey

1. Start an isolated Bookinator server with a new data directory.
2. Import `demo-corpus/fixtures/the-dunwich-horror.md` through the rendered Add
   Book interface and approve the observed chapter map.
3. Set `developmentAnalysisLimit` to the first authored chapter. Run the normal
   chapter-first pipeline until `developmentCheckpointLocked` is true.
4. Inspect Summary, Dossier, cumulative context, LLM Review, Emotions, Tags,
   and Smells in the rendered workspace. Reject false, unsupported, clipped,
   unusable, or contradictory output rather than treating completion as
   quality.
5. Use the visible **Run next chapter** command. Repeat through at least a
   second authored chapter, proving that earlier artifacts remain unchanged.
6. Run the evidence collector:

```sh
BOOKINATOR_ACCEPTANCE_URL=http://127.0.0.1:4892 \
BOOKINATOR_ACCEPTANCE_DATA_DIR=/path/to/disposable-data \
BOOKINATOR_ACCEPTANCE_BOOK_ID=the-assay-book-id \
BOOKINATOR_ACCEPTANCE_MIN_CHAPTERS=2 \
npm run test:pipeline-acceptance
```

The collector requires a locked checkpoint, the requested number of completed
authored specimens, non-empty Summary/Dossier/Review projections, exact
offset-and-text matching for every emitted evidence anchor, an anchored
final-quarter movement in each summary, one canonical cast record per identity,
resolved cast references in Summary and Dossier, no unsupported compact
kinship assertion in Summary prose, safely generalized unsupported cast roles,
no ignored or misaddressed cast exclusions, closure of rejected Summary claims,
minimum evidence breadth for long chapters (three Summary claims, three Dossier
claims, and a sixty-word digest), and all ten structured Review dimensions with one to three exact source
quotations whenever applicable. It records hashes, counts, timings, model
identity, role-generalization warnings, and these semantic-hygiene results under
`evidence/pipeline-acceptance/`; it does not copy raw manuscript or generated
analysis into Git.

Those rules are deliberately insufficient to declare the prose useful. Record
a separate qualitative review beside the machine report. It must name false or
unsupported interpretations, missing material movement, duplicate or
misclassified entities, generic questions, contradictory projections, and an
uninformative Review even when every quoted anchor is real.

## What this proves—and does not

This assay proves that one disclosed model/hardware/fixture combination passed
the real pipeline, checkpoint, persistence, and evidence-anchor boundaries. It
does not prove that every interpretation is useful, that omissions are benign,
or that another model or manuscript format behaves the same way. Human visual
and editorial inspection remains a separate required judgment. Failures,
timeouts, recovery actions, and model substitutions belong in the retained
report rather than being erased from the story of the run.
