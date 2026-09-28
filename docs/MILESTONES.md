# Bookinator milestones

This is Bookinator’s high-level release history. It records what each milestone made possible and why that change mattered. Implementation details belong in commits, tests, and technical documentation; this document is the story of the product becoming more useful.

The same history is available inside Bookinator from **Releases** in the footer.

## 0.3.0 — The Engine Room

**Planned next milestone · Independent pipeline**

Bookinator’s analysis engine will become a durable background service rather
than a thread owned by the web server. The browser remains the richest control
and inspection surface, but closing it—or restarting the web application—will
not own the lifetime of an active analysis queue.

### Intended pieces

- **One independent worker owns computation.** Queue scheduling, job claiming,
  model calls, retries, cancellation, crash recovery, and pipeline-state writes
  move behind a stable worker boundary.
- **Every controller speaks the same protocol.** The web UI, a command-line
  controller, and a later menu-bar companion can inspect, start, pause, drain,
  prioritize, retry, or stop work without reimplementing the scheduler.
- **Background work behaves like a guest.** Conservative concurrency,
  pause-after-current semantics, battery and thermal awareness, and explicit
  resource profiles keep unattended analysis understandable and courteous.
- **The queue becomes transactionally durable.** Atomic claims, ordered human
  priorities, current ownership, attempts, and recent history survive process
  restarts without relying on in-process locks.
- **Bookinator proves the reusable contract first.** The shared pipeline
  contract will move into Inator only after Bookinator has exercised the real
  process boundary, reconnect behavior, and failure semantics.

### Why it matters

Bookinator already performs work that can occupy a machine for hours. The
Engine Room turns that work into infrastructure: the analysis can continue
without an open browser, the UI can reconnect without guessing, and other
Inator products can adopt a proven worker contract instead of inheriting
Bookinator’s server internals.

### Deliberately not finished

This milestone establishes one reliable local worker and its control plane. It
does not promise cloud execution, multiple simultaneous model workers, or a
hosted Bookinator service. Those choices come after the local contract is
boringly trustworthy.

---

## 0.4.0 — Look Here

**Planned following milestone · Editorial attention routing**

Bookinator will add small, fast, inspectable models that decide where the
expensive reader should look—not what the editor should conclude. The first
goal is sharper attention: Qwen receives a ranked evidence packet instead of
being asked to rediscover every possibly relevant passage. The second goal is
speed where the evidence supports it: confidently irrelevant candidates can
avoid a full-model reading, while uncertain material still reaches Qwen.

### Intended pieces

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

## 0.2.0 — Reviewer Tools

**In progress · Human judgment milestone**

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

Run **Carmilla** by J. Sheridan Le Fanu from fresh EPUB ingestion through
chapter approval, every enabled analysis pass, LLM Review, human annotation,
reviewer sign-off, `.bookinator` backup and restore, interactive HTML, and PDF.
Its compact, chaptered Gothic structure makes a complete run practical, while
its queer desire, predation, illness, horror, and narrative ambiguity give the
editorial machinery something real to contend with. Record failures as release
blockers; do not describe the regression as complete until the exported
artifacts have been inspected.

### Deliberately not finished

The full Editorial Assessment remains a separate milestone. It will make
book-level claims about clarity, propulsion, character appeal, agency, stakes,
payoff, voice, genre fit, and possible audience or commercial positioning.
Those claims need their own dimension schema, evidence aggregation,
counterarguments, reviewer voting and commentary, and calibration across more
than one famous public-domain novel. Fast implementation is not sufficient
validation for that stronger promise.

The independent background worker is likewise not part of Reviewer Tools. It
is the center of **0.3.0 — The Engine Room**, immediately following this
release.

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
