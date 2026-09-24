# Chapter signals

See [`research/chapter-signal-models.md`](research/chapter-signal-models.md) for
the current Hugging Face model shortlist, detector routing, canonical signal
IDs, scoring anchors, and evaluation plan.

Chapter signals are scored, evidence-bearing descriptions of a chapter. They
are not verdicts and they are not quality grades. The first implementation
should store every signal as structured data and render only the strongest few
from each family until the editor asks for more.

## Record contract

Every inferred signal records:

- stable tag ID, label, Unicode icon, and family;
- score from 0 to 1, where 0 means absent and 1 means dominant or unusually
  strong for that signal;
- confidence from 0 to 1, kept separate from the score;
- evidence passages with chapter and source-page provenance;
- detector type (`classifier`, `LLM`, or `deterministic`), model/version,
  prompt/schema version, and run ID;
- taxonomy version; and
- origin (`inferred`, `author`, or `editor`). Human tags are never overwritten
  by a later model pass.

Scores should be calibrated within a family. A chapter can be 0.8 action and
0.7 dialogue; these are not percentages that must add to 1. Emotion
distributions are the exception: each requested emotional perspective should
also expose a normalized distribution.

## Proposed tag catalog

### Narrative mode and chapter function

| Icon | Tag | What the score means |
|---|---|---|
| ⚡ | Action | Physical activity and consequential movement dominate |
| “ ” | Dialogue | Spoken exchange carries the chapter |
| ¶ | Exposition | Background or explanation dominates |
| ◔ | Introspection | Interior thought and self-examination dominate |
| ⌕ | Investigation | Characters actively seek, test, or connect evidence |
| ? | Mystery | The chapter withholds or complicates material answers |
| ✦ | Discovery | Important information is found rather than merely explained |
| ⚔ | Conflict | Opposed goals collide directly |
| ♡ | Relationship | A relationship changes materially |
| ☺ | Comedy | Comic beats are structurally important |
| ☾ | Horror | Threat, revulsion, or supernatural dread drives the chapter |
| ⧗ | Suspense | Anticipated danger or uncertainty drives forward motion |
| ⇢ | Travel | Movement between places is a principal function |
| → | Transition | The chapter primarily connects larger movements |
| ∴ | Aftermath | Characters absorb consequences of an earlier event |
| ◇ | Setup | The chapter establishes a future obligation or possibility |
| ✓ | Payoff | An established promise, question, or preparation resolves |
| ↶ | Reversal | The apparent direction or meaning changes sharply |
| ▲ | Climax | Conflict or stakes reach a local or book-level peak |
| ▽ | Resolution | The chapter closes important active threads |

### Emotional tenor

Run emotional tagging from two perspectives when possible: emotions expressed
by focal characters and emotions the passage appears designed to evoke in a
reader.

| Icon | Tag | Family |
|---|---|---|
| ☀ | Joy | Ekman-style emotion |
| ◒ | Sadness | Ekman-style emotion |
| ▲ | Anger | Ekman-style emotion |
| △ | Fear | Ekman-style emotion |
| ≀ | Disgust | Ekman-style emotion |
| ✦ | Surprise | Ekman-style emotion |
| ⌁ | Contempt | Useful extension to the basic six |
| · | Neutral / uncertain | Explicit low-affect or uncertain result |

### Mood and atmosphere

| Icon | Tag | Icon | Tag |
|---|---|---|---|
| ◐ | Noir | ♨ | Cozy |
| ◣ | Foreboding | ✿ | Playful |
| □ | Bleak | ♡ | Romantic |
| ◉ | Uncanny | ∿ | Meditative |
| ≋ | Frenetic | ▣ | Claustrophobic |
| ↑ | Triumphant | ◒ | Melancholic |
| ◠ | Hopeful | ▼ | Ominous |
| ✧ | Wondrous | ⧗ | Tense |
| ≈ | Dreamlike | ⌂ | Intimate |

Mood scores form a distribution that can change across a chapter. The stored
result should retain segment-level values so the later emotional-shape graphic
does not flatten a sharp turn into one average.

### Genre and subgenre affinity

Genre is primarily a book-level classification, but chapter-level affinity is
useful for seeing mode changes.

| Icon | Tags |
|---|---|
| ⌕ | Mystery, detective, procedural |
| ⧗ | Thriller, suspense |
| ⚖ | Crime, legal |
| ♡ | Romance, romantic comedy |
| ✧ | Fantasy, urban fantasy, epic fantasy, magical realism |
| ◉ | Horror, supernatural horror, psychological horror, gothic |
| ⬡ | Science fiction, hard SF, space opera, cyberpunk |
| ◷ | Historical, alternate history, time travel |
| ⚡ | Adventure, action |
| ◈ | Literary, experimental |
| ☺ | Comedy, satire |
| ◐ | Noir |
| ♨ | Cozy mystery / cozy fantasy |
| ◠ | Coming of age, young adult, middle grade |
| ▼ | Dystopian, post-apocalyptic |
| ⌂ | Domestic, family saga |
| ⇢ | Western, road story, quest |

### Themes

Themes require two layers. A **topic** says what recurs; a **proposition** says
what the manuscript appears to argue about that topic. “Power” is a topic.
“Power isolates the person who seeks it” is a proposition. Both need evidence.

| Icon | Seed theme tags |
|---|---|
| ◇ | Identity, belonging, self-knowledge |
| ⌂ | Family, friendship, community |
| ♡ | Love, intimacy, loyalty |
| ◒ | Grief, loss, memory, trauma, healing |
| ♜ | Power, ambition, corruption, duty |
| ⚖ | Justice, revenge, mercy, responsibility |
| ⛓ | Freedom, captivity, oppression, prejudice |
| ◷ | Mortality, aging, legacy, time |
| ⊙ | Truth, deception, secrecy, perception |
| ⇄ | Fate, free will, chance, choice |
| ✦ | Faith, doubt, redemption, sacrifice |
| ⬡ | Technology, progress, alienation |
| ❧ | Nature, civilization, survival |

The seed list is not closed. Models may propose a new theme label, but it must
be normalized into a stable book-level theme only after recurrence and evidence
are established.

### Style and literary devices

These scores represent salience or density, never whether the device is good.

| Icon | Tag | Icon | Tag |
|---|---|---|---|
| ≍ | Metaphor | ≈ | Simile |
| ◇ | Symbolism | ↗ | Allusion |
| ⟳ | Motif | ◈ | Sensory imagery |
| ↺ | Irony | ◌ | Foreshadowing |
| ♙ | Personification | ≡ | Allegory |
| ∥ | Parallelism | _ | Understatement |
| ↑ | Hyperbole | ≠ | Unreliable narration |
| ⊙ | Dramatic irony | ♫ | Sonic / rhythmic emphasis |
| ⋯ | Fragmentation | “ ” | Distinctive voice / idiom |

### Story dynamics

| Icon | Tag |
|---|---|
| ⧗ | Tension |
| ▲ | Stakes |
| » | Urgency |
| ↑ | Protagonist goal progress |
| ↓ | Setback |
| Δ | Story-state change |
| ✦ | Revelation density |
| ↶ | Reversal strength |
| ⛓ | Causal importance |
| → | Chapter-end propulsion |
| ◇ / ✓ | Setup and payoff strength |
| ◎ | Centrality to the book's active threads |

These become inputs to plot and causal visualizations; they should not be
presented as tags without source-linked explanations.

### Time, viewpoint, and setting

| Icon | Tag |
|---|---|
| ▶ | Primary narrated present |
| ↶ | Flashback / remembered scene |
| ↷ | Flash-forward / anticipated scene |
| ∥ | Simultaneous branch |
| ◌ | Dream, hypothetical, or imagined scene |
| ⇄ | Nonlinear or uncertain placement |
| ◉ | Single viewpoint |
| ◎ | Multiple viewpoints |
| ≠ | Viewpoint drift candidate |
| ⌖ | Location change |
| ◷ | Material time jump |
| ◫ | Interior setting |
| □ | Exterior setting |

Named viewpoint characters, locations, and time expressions remain entities
with confidence and evidence. The tags describe structural behavior around
them.

### Optional audience and content signals

Keep these behind an explicit editor preference: violence, sexual content,
strong language, substance use, self-harm, abuse, prejudice, medical trauma,
and other sensitivity categories; plus likely age band and reading level. They
must be described as passage-level content signals, never moral judgments.

## Not tags

Contradictions, typographical errors, prose cruft, unresolved questions,
continuity findings, and AI-writing indicators are findings with their own
evidence and lifecycle. They should not be flattened into colorful tag chips.

## First implementation slice

1. Run deterministic ratios first: dialogue, paragraphs, sentences, and source
   metrics.
2. Add narrative-mode, story-dynamic, mood, and Ekman distributions using one
   assigned local model and a versioned JSON schema.
3. Retain supporting passages and confidence; reject a response that supplies
   scores without evidence.
4. Show the strongest tags with icons on each chapter and provide a sortable
   all-signals list.
5. Evaluate local Hugging Face emotion classifiers against the LLM pass before
   choosing a default. Store the methods separately so disagreement remains
   inspectable.
