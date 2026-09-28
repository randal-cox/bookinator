# Chapter-signal models and standard vocabulary

Research snapshot: September 23, 2026

## First implementation decision

The immediate priorities are now fixed:

1. **Emotions:** implement a separate pipeline stage with
   `j-hartmann/emotion-english-distilroberta-base` and its seven-label
   Ekman-plus-neutral vocabulary.
2. **Tags:** implement structured, evidence-bearing canonical tag scoring with
   the existing assigned Qwen-family chapter reader.
3. **Later comparisons:** evaluate GLiClass against the frozen tag vocabulary,
   then embeddings and GLiNER for retrieval/entity support. Do not delay the
   first real runs for this bake-off.

Chapter Signals should be an ensemble, not a single-model opinion. A compact
classifier can score a known label set cheaply; a generative reader can explain
literary functions and cite evidence; deterministic measurements can establish
facts such as quoted-dialogue ratio; and embeddings can find recurrence across
the book. Store these methods separately so agreement is useful evidence and
disagreement remains inspectable.

## Recommended detector stack

| Layer | Best use | Initial direction |
|---|---|---|
| Deterministic | Dialogue ratio, scene breaks, time expressions, paragraph and sentence measurements, direct structural cues | Run first on every chapter; never ask an LLM to estimate a value we can count |
| Specialist classifier | Segment-level emotional expression | Evaluate an Ekman-plus-neutral model against a richer multilabel emotion model |
| Zero-shot classifier | Cheap secondary scores over a frozen vocabulary | Evaluate GLiClass and ModernBERT zero-shot; do not treat their raw scores as calibrated literary truth |
| Generative reader | Narrative function, mood, theme propositions, plot dynamics, viewpoint behavior, evidence selection | Use the assigned Qwen-family reader with a versioned schema and constrained vocabulary |
| Embeddings | Recurring themes, motifs, setups/payoffs, similar scenes, candidate clusters across chapters | Use a small local embedding model to retrieve candidates; require a reader or editor to interpret them |
| Span/entity extractor | Characters, locations, organizations, objects, time expressions | Consider GLiNER as a fast candidate generator; preserve dossier evidence and human alias correction |

## Hugging Face candidates worth evaluating

These are candidates for a local bake-off, not defaults. Each must be tested on
Bookinator's public-domain and consented fiction fixtures, including older
prose, dialogue-heavy scenes, interior monologue, horror, comedy, and deliberate
ambiguity.

### Emotion

- [`j-hartmann/emotion-english-distilroberta-base`](https://huggingface.co/j-hartmann/emotion-english-distilroberta-base)
  is the cleanest first Ekman experiment. It predicts anger, disgust, fear,
  joy, sadness, surprise, and neutral. The checkpoint is roughly 329 MB and was
  trained from six datasets. Run it on short overlapping passages, not entire
  chapters; compare expressed character emotion with the reader-effect judgment
  from the generative model rather than pretending those are the same target.
- [`SamLowe/roberta-base-go_emotions`](https://huggingface.co/SamLowe/roberta-base-go_emotions)
  is a useful richer comparison: multilabel GoEmotions rather than the compact
  Ekman vocabulary. Map its fine-grained labels into Bookinator's display
  taxonomy only after retaining the original scores.
- [`cardiffnlp/twitter-roberta-base-emotion-multilabel-latest`](https://huggingface.co/cardiffnlp/twitter-roberta-base-emotion-multilabel-latest)
  adds anticipation, love, optimism, pessimism, and trust to several Ekman-like
  labels. Its reported test scores are respectable, but it is trained on tweets;
  use it as a domain-shift stress test, not an assumed fiction model.

### Fixed-vocabulary zero-shot scoring

- [`knowledgator/gliclass-modern-base-v3.0`](https://huggingface.co/knowledgator/gliclass-modern-base-v3.0)
  is a 151M-parameter, Apache-2.0, multilabel zero-shot classifier designed to
  score arbitrary labels in one forward pass. It is an interesting economical
  second opinion for narrative mode, chapter function, mood, and broad genre
  affinity. The card's generic benchmarks do not establish literary validity.
- [`knowledgator/gliclass-edge-v3.0`](https://huggingface.co/knowledgator/gliclass-edge-v3.0)
  is the small-footprint experiment in the same family. Its lower benchmark
  scores may still be adequate for candidate generation on modest hardware.
- [`MoritzLaurer/ModernBERT-large-zeroshot-v2.0`](https://huggingface.co/MoritzLaurer/ModernBERT-large-zeroshot-v2.0)
  is an Apache-2.0 ModernBERT zero-shot checkpoint with a roughly 792 MB
  safetensors weight file. Test it as the higher-cost encoder baseline against
  GLiClass and the existing Qwen reader.

Zero-shot labels should be written as explicit hypotheses rather than bare
words—for example, “Spoken exchange carries a substantial part of this
passage,” not merely “dialogue.” This reduces ambiguity and makes the exact
question inspectable.

### Retrieval and span candidates

- [`BAAI/bge-small-en-v1.5`](https://huggingface.co/BAAI/bge-small-en-v1.5)
  is a small MIT-licensed English embedding baseline with a roughly 133 MB
  safetensors file. It is suitable for local motif/theme recurrence retrieval,
  but similarity alone must not declare that two passages have the same meaning
  or form a setup/payoff pair.
- [`urchade/gliner_small-v2.1`](https://huggingface.co/urchade/gliner_small-v2.1)
  is an Apache-2.0 open-label entity extractor worth evaluating for characters,
  locations, organizations, significant objects, and explicit time expressions.
  It belongs beside dossier extraction, not in the semantic tag score itself.

### Upcoming annotation and guidance experiments

- **Semantic Echoes:** start with
  [`sentence-transformers/all-MiniLM-L6-v2`](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2)
  as a small local sentence/paragraph embedding baseline. Retrieve similar
  passages across chapter distance and preserve both endpoints. Candidate uses
  include callbacks, recurring sensory images, repeated exposition, parallel
  scenes, and near-duplicate phrasing. Similarity is retrieval, not an editorial
  conclusion: a Qwen reader or editor must distinguish motif development from
  coincidence, boilerplate, or unwanted repetition.
- **Metaphor-related language density:** evaluate
  [`CreativeLang/metaphor_detection_roberta_seq`](https://huggingface.co/CreativeLang/metaphor_detection_roberta_seq)
  as the first token-level baseline. Its VUA20/MIPVU lineage is broader than
  obvious “X is Y” figures and includes indirect, conventional, direct,
  implicit, and personifying metaphorical word use. The checkpoint nevertheless
  emits a binary metaphor-related token judgment; it does not identify
  conceptual metaphors or separately cover every figurative family. Display its
  result as metaphor-related density until separately evaluated simile,
  symbolism, irony, hyperbole, metonymy, imagery, and other device evidence can
  support a broader aggregate.
- **GLiNER guidance:** compare the small and multi checkpoints over a
  Bookinator-specific open-label vocabulary: person, group, location,
  institution, creature, artifact, event, and supernatural force. Give Qwen the
  extracted spans as candidates with provenance; never let GLiNER silently
  merge aliases or convert a location into a character/entity assertion.
- **ModernBERT guidance:** evaluate an Apache-licensed ModernBERT NLI checkpoint
  over explicit hypotheses for chapter function, genre affinity, thematic
  setting, viewpoint behavior, and narrative texture. Use it to rank evidence
  and decide where deeper Qwen attention may pay off, not to manufacture a
  mandatory label for every hypothesis.

These experiments share one artifact contract: model revision and license,
input/source version, segment and overlap rules, exact evidence ranges, raw
scores, thresholds, and aggregation method. Their outputs remain distinct from
Qwen interpretations and human annotations so disagreement is inspectable.

## What should remain a generative reading task

No specialist model found in this pass has a sufficiently relevant model card
to become the authority for literary genre, theme, mood, flashback function,
exposition, setup/payoff, reversal, climax, or chapter-end propulsion. Models
advertised as book-genre classifiers commonly classify blurbs, titles, or
catalog categories rather than chapter prose. Bookinator should initially ask
its local Qwen-style reader for these signals using the controlled vocabulary
below, require evidence, and evaluate the answers against editor labels.

## Canonical scoring language

Every signal uses a stable `snake_case` ID. The display label may change without
changing stored data. Score and confidence are separate:

| Score | Meaning |
|---:|---|
| 0.00 | Absent or unsupported |
| 0.25 | Present briefly or weakly |
| 0.50 | Material to a substantial passage |
| 0.75 | Dominant through much of the chapter |
| 1.00 | Defining structural function of the chapter |

Scores between anchors are allowed. Confidence answers “how sure is the
detector?” rather than “how much is present?” A score above 0.25 requires at
least one source passage; above 0.60 requires evidence from more than one moment
unless one scene clearly dominates the chapter.

### Prose mode

- `action`: physical acts and consequential movement carry the passage.
- `dialogue`: spoken exchange carries the passage.
- `exposition`: background, rules, history, or explanatory information is
  delivered primarily for reader understanding.
- `description`: people, objects, places, or sensory conditions are rendered
  without action or explanation being the main purpose.
- `introspection`: interior thought, memory, feeling, or self-examination is
  foregrounded.
- `narrative_summary`: events or elapsed time are compressed rather than
  dramatized moment by moment.
- `investigation`: characters actively seek, test, compare, or connect evidence.

These may coexist. Dialogue is partly deterministic; “dialogue carries the
chapter” remains a semantic judgment.

### Chapter function

- `orientation`: establishes who, where, when, or the immediate situation.
- `setup`: creates a future obligation, possibility, question, or planted detail.
- `escalation`: increases pressure, danger, cost, or difficulty already in play.
- `complication`: adds an obstacle or condition without necessarily raising
  stakes.
- `discovery`: characters find material information.
- `revelation`: information changes the reader's or character's understanding.
- `confrontation`: opposed parties meet or goals collide directly.
- `relationship_change`: a relationship materially strengthens, weakens, or
  changes kind.
- `reversal`: the apparent direction, advantage, goal, or meaning turns.
- `setback`: progress toward an active goal is lost or obstructed.
- `payoff`: an established setup, promise, question, or preparation resolves.
- `climax`: active conflict reaches a local or book-level peak.
- `aftermath`: consequences of a prior event are absorbed or assessed.
- `resolution`: important active threads close or settle.
- `transition`: chiefly connects larger movements, places, times, or phases.
- `travel`: movement between locations is itself a principal function.

### Reader dynamics

- `mystery`: material answers are deliberately withheld or complicated.
- `suspense`: anticipation of an uncertain outcome drives attention.
- `tension`: incompatible pressures remain active in the scene.
- `stakes`: the magnitude of what may be gained, lost, or harmed.
- `urgency`: limited time or immediate pressure demands action.
- `goal_progress`: a focal character materially advances an active goal.
- `story_state_change`: the chapter leaves the active situation meaningfully
  different from how it began.
- `revelation_density`: consequential new understanding arrives frequently.
- `causal_importance`: later events materially depend on what occurs here.
- `chapter_end_propulsion`: the ending creates a concrete reason to continue.

### Narrated time

- `primary_present`: the scene belongs to the chapter's main narrated now.
- `flashback`: the narration dramatizes an earlier event.
- `remembered_past`: an earlier event is recalled or reported but not fully
  dramatized as the active scene.
- `flash_forward`: the narration dramatizes a later event.
- `anticipated_future`: a possible or expected future is imagined or discussed.
- `time_jump`: materially elapsed story time is crossed.
- `simultaneous_branch`: the chapter follows events concurrent with another
  established strand.
- `dream_or_vision`: dream, hallucination, prophecy, or vision changes the
  temporal/reality frame.
- `hypothetical_scene`: an unrealized alternative is narrated.
- `nonlinear_uncertain`: placement is deliberately or evidentially uncertain.

### Viewpoint behavior

- `first_person`, `second_person`, `third_limited`, `third_omniscient`, and
  `objective_external` describe narrative access, not grammatical pronoun counts.
- `single_viewpoint` and `multiple_viewpoints` describe the chapter's structure.
- `viewpoint_shift` is an intentional or neutral access change.
- `viewpoint_drift_candidate` is a potentially unintended access change and is
  a review candidate, not a stylistic verdict.

### Mood vocabulary

Use this closed first-pass list: `tense`, `foreboding`, `ominous`, `uncanny`,
`horrific`, `bleak`, `melancholic`, `intimate`, `romantic`, `hopeful`, `playful`,
`comic`, `cozy`, `meditative`, `dreamlike`, `wondrous`, `triumphant`, `frenetic`,
`claustrophobic`, `noir`, and `neutral_uncertain`.

Mood is atmosphere created by the passage. It is not the same as a character's
emotion or the reader emotion the passage appears designed to evoke.

### Genre affinity

Use book-level genre as context and allow chapter-level mode scores from this
initial vocabulary: `mystery`, `detective`, `procedural`, `crime`, `legal`,
`thriller`, `suspense`, `romance`, `romantic_comedy`, `fantasy`, `epic_fantasy`,
`urban_fantasy`, `magical_realism`, `horror`, `gothic`, `supernatural_horror`,
`psychological_horror`, `science_fiction`, `hard_sf`, `space_opera`, `cyberpunk`,
`historical`, `alternate_history`, `time_travel`, `adventure`, `western`,
`road_story`, `quest`, `literary`, `experimental`, `comedy`, `satire`, `noir`,
`cozy`, `coming_of_age`, `young_adult`, `middle_grade`, `dystopian`,
`post_apocalyptic`, `domestic`, and `family_saga`.

Genre scores express affinity, not exclusive membership. Do not infer audience
age from protagonist age alone.

### Themes and literary devices

Theme output has two different records:

- `theme_topic`: a normalized recurring subject such as identity, belonging,
  family, love, grief, power, justice, freedom, mortality, truth, fate, faith,
  technology, nature, memory, trauma, or responsibility.
- `theme_proposition`: a short evidence-bearing statement about what the book
  appears to suggest about that topic. One chapter may propose a candidate; a
  whole-book pass determines recurrence and development.

Literary-device IDs begin with `device_`: `metaphor`, `simile`, `symbolism`,
`allusion`, `motif`, `sensory_imagery`, `irony`, `foreshadowing`,
`personification`, `allegory`, `parallelism`, `understatement`, `hyperbole`,
`unreliable_narration`, `dramatic_irony`, `sonic_emphasis`, and `fragmentation`.
They describe salience or density, never quality.

## Model instructions that should be invariant

1. Score only the supplied canonical IDs; propose additions in a separate
   `candidate_signals` field.
2. Separate observed textual behavior from interpretation.
3. Supply exact, short evidence passages and their source locations.
4. Give both score and confidence; never derive one from the other.
5. Use `neutral_uncertain` and low confidence rather than forcing a label.
6. Distinguish character emotion, intended reader emotion, and mood.
7. Distinguish topic from thematic proposition.
8. Distinguish narrated order from story chronology.
9. Treat genre as overlapping affinity, not one mandatory class.
10. Do not turn prose preferences into defects. Tags are descriptions; findings
    have a separate review lifecycle.

## Evaluation plan

1. Segment chapters into overlapping passages small enough for encoder models;
   retain chapter aggregation and segment-level peaks.
2. Hand-label a stratified fixture set for a narrow first slice: dialogue,
   action, exposition, introspection, flashback, current scene time, the seven
   Ekman-plus-neutral emotions, tension, setup, payoff, and revelation.
3. Compare deterministic values, the specialist emotion model, one zero-shot
   encoder, and the Qwen reader without averaging away disagreement.
4. Measure per-label precision/recall, calibration, evidence validity,
   cross-genre stability, runtime, memory, and editor correction time.
5. Choose defaults per family. A model that wins emotion need not score genre,
   and a fast candidate generator need not become editorial authority.
