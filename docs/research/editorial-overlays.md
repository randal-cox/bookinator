# Editorial overlays: prose signals that matter

Research snapshot: September 23, 2026

## Product decision

Bookinator should treat manuscript analysis as a stack of independent,
inspectable overlays rather than one color-coded verdict. Users may combine a
few layers at a time. Every layer retains its detector, version, source range,
raw measurement or score, threshold, and explanation.

Two visual channels have different meanings:

- **Persistent underlines** identify localized prose worth inspecting. They are
  not emotional annotations and must say exactly what triggered them.
- **Optional colored regions** reveal a continuous pattern across the text:
  emotion, complexity, pacing, dialogue density, narrative distance, or another
  selected dimension.

Never use color alone. Hover, focus, and the accessible text view must name the
signal, value, comparison baseline, source range, and detector. The overlay
picker should permit several active layers, show a compact legend for each,
and warn when the display becomes visually ambiguous rather than imposing an
arbitrary one-layer limit.

## First brainstorm: measurable candidates

### Sentence and paragraph mechanics

- Sentence length in words and characters.
- Clause count, subordinate-clause depth, dependency-tree depth, and nesting.
- Very long sentences and very dense sentences as separate measurements.
- Paragraph length, dialogue-paragraph density, and walls of text.
- Fragments, run-ons, comma splices, repeated words, punctuation/quote balance,
  and possible agreement errors.
- Passive constructions, nominalizations, adverb density, intensifiers,
  hedges, filter words, and weak or generic verbs.

These are descriptions or inspection candidates, not universal defects.
Fragments may be excellent prose; a long sentence may be the point.

### Rhythm and repetition

- Local sentence-length variation and monotonous runs of similarly sized
  sentences.
- Repeated sentence openings, repeated syntactic shapes, repeated words, and
  near-duplicate phrases within a configurable distance.
- Alliteration, sound repetition, punctuation cadence, and paragraph-break
  rhythm.
- Dialogue/action/exposition alternation and unusually long uninterrupted
  stretches of one mode.

### Cognitive and stylistic load

- Lexical density and vocabulary rarity.
- Readability estimates, shown relative to the manuscript and genre rather than
  as a school-grade quality score.
- Pronoun/reference load, number of entities introduced, and possible ambiguous
  antecedents.
- Abstraction versus concrete/sensory language.
- Figurative-language and metaphor density.
- Information/revelation density and the spacing of new names, facts, terms, or
  world rules.

### Narrative and editorial continuity

- Viewpoint and narrative-distance regions; possible POV drift underlines.
- Grammatical-tense regions; possible unmotivated tense-shift underlines.
- Dialogue, action, description, exposition, introspection, and narrative
  summary regions.
- Character, location, and timeline presence.
- Emotional regions and peaks.
- Pacing/scene-energy regions, scene transitions, and chapter-end propulsion.
- Repeated explanations, continuity conflicts, unresolved references, and
  terminology/name inconsistencies.

### Authorship-pattern experiments

An “AI likelihood” label is not reliable enough for the ordinary editorial UI.
Current detectors can fail under domain shift, paraphrasing, newer generators,
and mixed human/model editing; polished human prose can also be flagged. A
future research-only layer may expose **statistical regularity**—low burstiness,
predictability, repeated transition patterns, generic phrasing, and unusually
uniform syntax—but it must not claim who wrote the passage. Known provenance
from the author's own revision history is stronger evidence than a detector.

## Hugging Face findings

### Worth a controlled bake-off

- [`cointegrated/roberta-large-cola-krishna2020`](https://huggingface.co/cointegrated/roberta-large-cola-krishna2020)
  scores sentence-level grammatical acceptability. It is a possible second
  opinion for suspicious sentences, not a grammar explanation or error-span
  detector. CoLA judgments do not establish that deliberately fragmented or
  dialectal fiction is wrong.
- [`kiddom/modernbert-readability-grade-predictor`](https://huggingface.co/kiddom/modernbert-readability-grade-predictor)
  is a roughly 100M-parameter, MIT-licensed grade-level regressor. Its card
  reports RMSE 1.41 and R-squared 0.81, but it targets US educational grade
  levels, warns about very short inputs and specialized text, and was trained
  from educational readability targets. Compare it with deterministic formulas
  and manuscript-relative measures; do not make it a prose-quality judge.
- [`tommyleo2077/deberta-v3-large-direct-metaphor`](https://huggingface.co/tommyleo2077/deberta-v3-large-direct-metaphor)
  is an Apache-2.0 token classifier with source-span output. It reports 83.4%
  sentence-level F1 on a small validation set. It is genuinely relevant to
  passage annotation, but its card also notes LLM-generated training labels,
  limited validation, imprecise span boundaries, and British-English domain
  limits. Test it only after the deterministic overlay foundation.
### Useful later, but not a scoring foundation

- [`grammarly/coedit-large`](https://huggingface.co/grammarly/coedit-large) can
  generate instruction-directed revisions and grammar corrections. Rewriting
  is a different and riskier job than detecting an inspectable issue. Its
  CC-BY-NC-4.0 license also makes it a poor common-infrastructure default under
  Bookinator's Business Source License distribution model.
- Grammar-correction T5 models can produce candidate rewrites, but generated
  differences are not dependable error labels and can flatten authorial voice.
  If Bookinator later offers suggestions, always show the original, rationale,
  diff, model, and an explicit accept action.
- The existing Qwen structured reader is more promising for meaning-dependent
  layers than generic sentiment, catalog-genre, or educational-readability
  classifiers.

### Do not ship as an authority

- AI-text classifiers trained on HC3, GPT-2, or a small set of generators are
  not authorship verification. Even responsible model cards restrict them to
  research or exploratory screening. Published work finds practical detectors
  vulnerable to paraphrasing and predicts declining separability as generators
  improve. Bookinator should not create a red “AI-written” underline.
- A grammatical-acceptability score is not the same as grammatical diagnosis.
- A readability grade is not prose quality, accessibility, or suitability for a
  particular genre.
- A generic LLM's dislike of a sentence is not an editorial finding.

## Revised priorities: what writers and editors will actually use

### Tier 1 — build first: fast, explainable, always available

1. **Long sentence** — absolute threshold plus percentile relative to this book.
2. **Clause and nesting load** — clauses, dependency depth, parentheticals, and
   stacked modifiers; distinguish length from syntactic complexity.
3. **Possible mechanical problem** — repeated word, punctuation/quote mismatch,
   run-on/comma-splice candidate, or agreement candidate, with the exact rule.
4. **Echo and repetition** — nearby repeated words, phrases, openings, and
   unusually similar sentences.
5. **Rhythm monotony** — a run of similar sentence lengths or structures.
6. **Dense paragraph** — length and sentence count relative to the manuscript's
   own distribution.
7. **Readability/load outlier** — formula ensemble and manuscript-relative
   percentile, never a quality grade.
8. **Lexical texture** — content-word density, rare-word density, adverbs,
   intensifiers, hedges, passive constructions, and nominalizations as separate
   optional filters.

The first four are candidates for the persistent “stinky text” underline. The
default underline should be conservative, severity-aware, and dismissible by
type, passage, book, or author preference.

### Tier 2 — high-value maps built from deterministic signals plus Qwen

9. **Prose mode** — dialogue, action, description, exposition, introspection,
   and narrative summary.
10. **Pacing and rhythm** — sentence/paragraph cadence, scene density, action,
    dialogue, and information load rather than one mysterious pace score.
11. **POV and narrative distance** — stable regions with possible shifts linked
    to evidence.
12. **Tense and narrated time** — main narrated now, memories, flashbacks,
    anticipations, and possible tense drift.
13. **Information density** — new entities, terms, facts, rules, and revelations.
14. **Concrete/sensory versus abstract language** — preferably broken into
    sight, sound, touch, smell, taste, bodily sensation, and abstraction.
15. **Emotion** — the existing classifier regions and peaks, kept descriptive.

### Tier 3 — experiments that need a labeled fiction fixture

16. **Grammatical acceptability second opinion** — CoLA model versus rules and
    editor judgments, especially on dialogue, fragments, dialect, and archaic
    prose.
17. **Metaphor/figurative density** — specialist token model versus Qwen and
    editor spans.
18. **Cohesion and ambiguous reference** — candidate links, never automatic
    correction.
19. **Voice/style consistency** — compare a passage with the book's own baseline
    or a character's established dialogue, not with a universal ideal.
20. **Genericity/statistical regularity** — research-only descriptive features;
    never an AI-authorship verdict.

## Implementation contract

Every overlay result should use source offsets and include:

- `id`, `family`, and display label;
- `start`, `end`, chapter, and page range where available;
- raw value, normalized display score, threshold, and manuscript percentile;
- detector kind (`rule`, `parser`, `classifier`, `reader`, or `human`), version,
  model/revision when applicable, and runtime;
- one-sentence explanation and the exact feature(s) that triggered it;
- user state: visible, dismissed, accepted, false positive, or intentional;
- invalidation signature tied to the source text.

Do not merge unlike evidence into one opaque “bad prose” score. An underline may
carry several reasons, but users must be able to inspect and toggle each one.

## Evaluation before defaults

Build a passage-level fixture containing polished long sentences, deliberate
fragments, dialect, dialogue, stream of consciousness, archaic prose, technical
exposition, children's prose, genre fiction, translated prose, and intentionally
bad examples. Ask authors and editors whether each signal is useful, ignorable,
or harmful. Measure false-positive dismissal time and retained findings—not just
classifier accuracy.
