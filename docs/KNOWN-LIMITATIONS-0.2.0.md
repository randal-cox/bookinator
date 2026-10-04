# Reviewer Tools 0.2.0: release limits and closeout

Reviewer Tools is a functional local editorial-analysis pipeline, not a claim
that a language model can read without error. Bookinator preserves machine
authorship, evidence, run provenance, and human decisions so an editor can use
imperfect proposals without confusing them with verified fact.

## Known limits

- **Deep analysis is slow and hardware-sensitive.** A whole book can occupy a
  high-memory local machine for many hours. Timing varies substantially by
  model, chapter length, generated output, retries, and thermal conditions.
- **Model output remains probabilistic.** Summaries, Dossiers, Tags, Smells, and
  LLM Review can omit useful details, overstate an inference, confuse an actor,
  or produce awkward prose. Source evidence and human review remain decisive.
- **Taxonomies are useful but not perfectly clean.** Canonical presentation
  collapses many lexical variants, but near-duplicate or debatable Tags and
  Smell families can still require reviewer judgment.
- **Ambiguous book structure may require a human.** Front matter, story
  prologues, embedded documents, appendices, and unconventional headings cannot
  always be classified safely from typography alone. Bookinator should expose
  ambiguity instead of silently inventing a chapter map.
- **The web server still owns the worker lifetime.** The queue is inspectable
  and recoverable, but 0.2.0 does not yet provide the independent background
  process planned for the later 0.5.0 Engine Room milestone.
- **The rebuilt reader is experimental.** GLiNER Chapter Signals, semantic
  forks, action/entity ledgers, deterministic repair, conditional
  reconciliation, and Jev-style attention routing are 0.4.0 Reanimator work.
  Experimental scripts and artifacts are not production pipeline stages.
- **Bookinator assists editorial judgment.** It does not prove plot holes,
  certify factual correctness, replace a developmental editor, or turn model
  proposals into reviewer-authored advice automatically.

## Fixed closeout checklist

The milestone is ready to tag when these checks pass on the release candidate:

- [ ] A short multi-chapter smoke book completes without corrupt, phantom, or
  permanently stuck pipeline state.
- [ ] Interrupted or failed work remains inspectable and can be retried without
  deleting unrelated completed artifacts.
- [ ] Chapter approval waits for a finished proposal, and source-evidence links
  resolve to canonical manuscript text.
- [ ] A human annotation can be created, edited, resolved or archived, and
  distinguished from every model proposal through reviewer sign-off.
- [ ] Interactive HTML and PDF exports have been inspected for content,
  attribution, navigation, and evidence behavior.
- [ ] A `.bookinator` backup restores collision-safely with source, analysis,
  reviewer state, and provenance intact.
- [ ] The current automated test suite passes, the release version is updated,
  and the release commit contains no unrelated experimental artifacts by
  accident.

Quality observations discovered during closeout should be recorded for
Reanimator. Reopen Reviewer Tools only for a failure of data integrity, truthful
workflow state, evidence inspection, human judgment, or portable handoff.
