# Bookinator milestones

This is Bookinator’s high-level release history. It records what each milestone made possible and why that change mattered. Implementation details belong in commits, tests, and technical documentation; this document is the story of the product becoming more useful.

The same history is available inside Bookinator from **Releases** in the footer.

## 0.3.0 — Common Ground

**Planned next milestone · Complete the Commons conversion**

Bookinator will become an ordinary consumer of the installable Inator Commons
architecture. The temporary sibling-checkout dependency and remaining bespoke
shell, lifecycle, backup, diagnostics, and shared-interface seams will move to
versioned public Commons packages and contracts without relocating
Bookinator-owned manuscript, analysis, or editorial logic.

### Intended pieces

- **Installable Commons is the foundation.** Bookinator consumes versioned
  launcher, UI, lifecycle, backup, and diagnostics contracts through public
  package boundaries. Product-owned manuscript, analysis, and editorial logic
  stays in Bookinator; Commons source is not copied into the repository.
- **Migration does not redesign analysis.** Preserve current pipeline behavior,
  saved-book compatibility, and the existing local-first privacy boundary so
  infrastructure failures remain distinguishable from model-quality problems.
- **Shared interface means shared behavior.** Adopt Commons navigation, dialogs,
  status, releases, help, backup, and machine/lifecycle conventions through thin
  Bookinator adapters rather than one-off imitations.
- **Installation becomes reproducible.** Setup and launch no longer require a
  neighboring Commons source checkout; versioned dependencies and diagnostics
  can explain exactly what is installed and what needs attention.

### Why it matters

Bookinator has already benefited from Commons while depending on its development
checkout. Common Ground completes that relationship: Bookinator becomes a real
consumer with the same installable, testable boundaries expected of the rest of
the Inator family. That gives later pipeline experiments a stable platform
instead of asking infrastructure and model research to change simultaneously.

### Deliberately not finished

This milestone does not redesign Chapter Reading, add GLiNER to production, tune
Qwen, or separate the pipeline into its eventual independent worker. Those are
Reanimator and later Engine Room concerns. Common Ground should be small enough
to finish and boring enough to trust.

---

## 0.4.0 — Reanimator

**Planned following milestone · Structured reading and attention routing**

Bookinator will rebuild its experimental deep reader around focused, inspectable
parts. Small, fast models decide where the expensive reader should look—not
what the editor should conclude. Cached semantic forks give separate jobs to
identity, action, summary, dossier, and editorial branches without one enormous
prompt asking the model to do everything at once. Deterministic validators and
bounded reconciliation keep errors visible instead of letting dubious prose
silently become cumulative memory.

The first goal is factual discipline and attributable failure. The second is
sharper attention: Qwen receives a ranked evidence packet instead of being
asked to rediscover every possibly relevant passage. The third is speed where
the evidence supports it: confidently irrelevant candidates can avoid a
full-model reading, while uncertain material still reaches Qwen.

### Intended pieces

- **Chapter Reading becomes componentized.** Entity identity, high-risk
  multi-action passages, selective Summary and Dossier records, editorial
  assessment, and conditional reconciliation become bounded components with
  independent status, provenance, and failure handling.
- **Prefix reuse prevents needless rereading.** Focused semantic forks reuse a
  byte-identical chapter-and-evidence prefix where the local provider supports
  it. Output schemas remain deliberately small; cache reuse is not an excuse
  for unbounded generation.
- **Deterministic checks come before another model call.** Exact quotation and
  offset resolution, alias collisions, missing action audits, unsupported
  relations, and schema/cardinality checks produce concrete repair requests.
  Reconciliation returns surgical claim changes rather than another essay.
- **One stable decision contract.** Jev-compatible yes/no, choice, and score
  requests become a replaceable local routing interface with saved inputs,
  probabilities, model revision, thresholds, timing, and exact source ranges.
- **Small models run in batches, not beside Qwen.** Bookinator loads the
  lightweight router, evaluates a whole stage or book, persists its candidate
  ledger, unloads it, and only then loads the primary reader. Model swapping
  never happens once per chapter or passage.
- **Smells provide the first calibration laboratory.** Existing deterministic
  candidates, dismissals, promotions, and human annotations let Bookinator
  measure whether a router can focus attention without silently losing useful
  findings. This is the first optimization target: Qwen should stop rereading
  every mechanically detected candidate once the router has demonstrated that
  it can safely discard obvious false positives and pass uncertainty through.
- **Tags provide the second fast path.** Their fixed, versioned taxonomy makes
  each tag a narrow hypothesis. A small router can reject implausible tags and
  identify uncertain ones before Qwen supplies the evidence and interpretation
  for the plausible subset.
- **Entity Signals become useful before Qwen reads.** The near-term GLiNER
  pipeline supplies fast, source-anchored mention lists and whole-book coverage
  on its own, then becomes shared feedstock for dossiers, Connections,
  continuity, questions, and editorial review.
- **LLM Review and questions become later staged experiments.** A router can
  prioritize passages for editorial review and judge likely question/payoff
  evidence before Qwen receives a focused packet, but those jobs require more
  semantic judgment and are not the first speed targets.
- **Shadow mode precedes suppression.** Early decisions remain visible and do
  not remove Qwen work. Bookinator graduates a route only after held-out books
  demonstrate high recall for human-retained material and a meaningful
  reduction in expensive reading.
- **Deep-reader optimization remains an active research lane.** Beyond routing,
  benchmark smaller-model cascades with Qwen escalation, reusable prompt-prefix
  or KV-cache work, richer specialist evidence packets, eventual distillation
  from Bookinator's adjudicated runs, and interchangeable faster compute
  providers. These are measured possibilities, not assumptions that every
  expensive whole-chapter reading can be skipped.

### Why it matters

A larger model is most valuable when it spends its context and attention on
the passages that deserve interpretation. This milestone turns cheap models
into scouts: even when wall-clock savings are modest, Qwen should receive a
cleaner, more deliberate reading assignment. When confidence is genuinely
high, the same machinery can also shorten multi-hour local runs.

It also creates a useful middle product tier. **Light analysis** runs
deterministic detectors and specialist models—Smells candidates, emotions,
entity mentions, taxonomy hypotheses, chapter statistics, and other bounded
signals—without requiring the primary reader. An ordinary machine may
therefore produce a smaller but still useful Bookinator rather than being
limited to opening work analyzed elsewhere.

Treat a provisional **10–30% reduction in primary-reader work** as an
engineering hypothesis, not a product promise. Record Qwen calls, input tokens,
candidate volume, model-load overhead, elapsed time, and retained editorial
value before claiming an actual saving.

### Deliberately not finished

Routers do not create editorial findings, resolve identities, decide literary
meaning, or replace reviewer judgment. Their output remains candidate evidence
with an inspectable fallback to full Qwen processing. Remote inference and
custom-trained Bookinator classifiers remain later choices; the first release
uses replaceable off-the-shelf local models and Bookinator's own evaluation
corpus.

---

## 0.5.0 — The Engine Room

**Planned later milestone · Independent pipeline**

Bookinator's analysis engine becomes a durable background service rather than a
thread owned by the web server. Queue scheduling, job claiming, retries,
cancellation, crash recovery, and pipeline-state writes move behind one stable
worker protocol shared by the web UI, command line, and later native controller.

The worker must behave like a guest: conservative concurrency,
pause-after-current semantics, battery and thermal awareness, durable claims,
and honest reconnect behavior. This milestone does not promise cloud execution
or multiple simultaneous model workers; it establishes one boringly reliable
local process boundary first.

---

## 0.2.0 — Reviewer Tools

**Closing release candidate · Human judgment milestone**

Bookinator is becoming an editorial workspace rather than only an analysis
machine. The product now asks sharper manuscript-specific questions, gives a
reviewer a durable reading and annotation surface, carries those decisions into
portable reports, and makes human sign-off part of what “finished” means. The
milestone’s capstone is a selective, evidence-anchored Qwen first pass whose
significant concerns, soft leads, counterarguments, and whole-book synthesis
stay visibly separate from human judgment until a reviewer acts.

### Major pieces

- **Questions become editorially useful.** Chapter summaries and dossiers ask
  specific questions about motivation, causality, character knowledge,
  relationships, thematic consequence, reader expectation, setup, and payoff,
  with evidence and an explanation of why the question matters.
- **The reviewer can work in the manuscript.** A human can select an exact
  passage, add a categorized and prioritized note, return to its source,
  revise it in place, change its severity, archive it, or permanently remove a
  debugging mistake without losing their reading position.
- **Human judgment has a lifecycle.** Editorial notes remain distinct from
  model output, reviewer sign-off is named and reversible, and the overall
  pipeline is not complete until the reviewer explicitly finishes their part.
- **Editorial decisions travel with the report.** Reviewer annotations appear
  in Explore and in the portable HTML and PDF outputs, with book identity,
  navigation, provenance, and export-time availability made clear.
- **Whole-book signals become useful overviews.** Emotions, Tags, and
  undismissed Smells have deterministic whole-book rollups with normalized
  groupings, counts, chapter reach, and links back to the relevant chapter
  evidence. Chapter-length reporting adds another immediately useful editorial
  view.
- **The workspace and exports scale more coherently.** Grouped navigation,
  nested portable-report menus, consistent completion semantics, a real
  Machine page, improved book-library progress, and clearer disclosure patterns
  keep the growing toolset understandable.
- **Public-domain books harden the foundations.** A 350-specimen EPUB and text
  corpus exposes chapter-map disagreements before they cost hours of analysis.
  Markdown and EPUB repairs preserve numeric headings, paragraph boundaries,
  epilogues, appendices, and source text; genuinely ambiguous structures pause
  for review instead of being guessed.
- **Qwen provides a bounded first editorial pass.** The model scores a stable
  editorial rubric, produces source-linked significant concerns and inspectable
  soft leads, argues against its own candidates, and synthesizes whole-book
  strengths and risks. A reviewer can promote, archive, annotate, or disagree;
  machine output never silently becomes human judgment.

### Why it matters

The first milestone proved that Bookinator could read and remember a whole
book. This milestone makes that accumulated intelligence answerable to a human.
It creates the beginnings of a real centaur workflow: the machine gathers and
proposes; the reviewer judges, changes, signs, and hands off.

### Release gate

Use **Carmilla** by J. Sheridan Le Fanu as the accumulated full-pipeline
regression and run a short chaptered smoke book against the final code. Inspect
chapter approval, pipeline completion and recovery, evidence navigation, human
annotation, reviewer sign-off, `.bookinator` backup and restore, interactive
HTML, and PDF. Release blockers are loss or corruption of source/reviewer data,
dishonest or unrecoverable pipeline state, broken evidence navigation, or a
failed handoff/export path.

Imperfect tags, awkward prose, missed editorial opportunities, conservative or
over-eager model judgment, and slow local inference are known quality limits,
not an endlessly moving release gate, provided their machine authorship and
evidence remain inspectable. Record them for **0.4.0 — Reanimator** rather than
holding Reviewer Tools open until a probabilistic reader becomes flawless.

### Deliberately not finished

The full Editorial Assessment remains a separate milestone. It will make
book-level claims about clarity, propulsion, character appeal, agency, stakes,
payoff, voice, genre fit, and possible audience or commercial positioning.
Those claims need their own dimension schema, evidence aggregation,
counterarguments, reviewer voting and commentary, and calibration across more
than one famous public-domain novel. Fast implementation is not sufficient
validation for that stronger promise.

The Commons conversion is likewise not part of Reviewer Tools. It is the center
of **0.3.0 — Common Ground**, immediately following this release. The
structured-reader, GLiNER, semantic-fork, and attention-routing experiments
belong to **0.4.0 — Reanimator**; the independent background worker remains the
later **0.5.0 — The Engine Room** milestone.

---

## 0.1.0 — Holy Crap, that Worked

**September 24, 2026 · First working milestone**

Bookinator became an end-to-end, local editorial workbench. An editor can bring in a manuscript, let Bookinator build a durable understanding chapter by chapter, inspect what it found, explore patterns across the whole book, and export a professional report—all without sending the manuscript to a commercial language-model service.

### What this milestone made possible

- **A manuscript becomes a navigable book.** Bookinator imports common manuscript formats, preserves the source, detects chapter structure, and keeps analysis connected to the passages it came from.
- **The machine remembers beyond one prompt.** Chapter summaries and evidence-rich dossiers accumulate into whole-book rollups instead of treating every chapter as an isolated exercise.
- **Editors can see the shape of the book.** Emotion maps, editorial tags, and prose smells expose patterns that are difficult to notice while reading linearly.
- **Distant details become connected.** Book-wide indexes connect entities, locations, and time observations; inference tools trace relationships and follow narrative questions toward their payoffs.
- **Analysis stays inspectable.** Pipeline state, model runs, failures, evidence, and source passages remain visible. Bookinator offers arguments and provenance rather than pretending to be an oracle.
- **Results can leave the app.** A branded, book-specific PDF gathers the strongest available analysis into a shareable editorial artifact.
- **Private work remains local.** Manuscripts and derived analysis live on the editor’s computer and local models perform the reading.

### Why it mattered

This milestone proved the full loop: ingest a real book, remember it at book scale, surface useful editorial patterns, and turn the work into something another person can inspect. The pieces stopped feeling like experiments and began behaving like one product.

### Deliberately not finished

This is an early working release, not a claim of editorial completeness. Reviewer annotations, a mature author-feedback loop, stronger revision tools, and additional ways to share and explore results belong to later milestones.

---

## Adding the next milestone

Keep future entries at this altitude:

1. Say what became possible.
2. Group related changes into a few reader-facing accomplishments.
3. Explain why the milestone mattered.
4. Name the important boundary that remains.

Avoid commit-by-commit inventories, internal class names, and exhaustive bug lists. Those details already have better homes.
