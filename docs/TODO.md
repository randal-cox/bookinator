# Bookinator TODO

## Next milestone: model-free one-book export

Build the static, interactive one-book publication described in
[`MODEL-FREE-EXPORT-TODO.md`](MODEL-FREE-EXPORT-TODO.md) **before Reviewer
annotations and the Author editing panel**. This is now a core distribution
surface, not a secondary export option: it lets one capable Bookinator machine
produce an analysis that any author, editor, writing group, or visitor to
`book.inator.com` can inspect without models or expensive hardware.

The private handoff and public-domain gallery must use the same generated
artifact. Start with a locally openable directory/ZIP, a canonical versioned
report manifest, explicit section/evidence selection, zero network requests,
and honest completeness/provenance. The first public website collection should
host unchanged exports for varied public-domain books so visitors can see real
Bookinator results immediately. `book.inator.com` should wrap discovery in its
normal navigation, catalog, and visual language so these read as ordinary site
destinations; the linked one-book artifact must still work independently when
downloaded. Private exports contain selected evidence snippets, never the whole
book or enough overlapping text to reconstruct it.

- Extend the new full-library progress view with per-pass ETA learning and a more detailed inspectable ordering forecast. High, Normal, and Low books auto-run; Shelved books remain browseable but stay out of the automatic queue.
- Instrument manuscript preparation and chapter-map construction with high-resolution elapsed timing. Preserve sub-second precision (for example, 1.2 ms) in the saved pipeline ledger and timing charts rather than rounding fast structural work to zero.

## Desktop launcher and installers

- Build an app creator and release packaging pipeline for macOS, Windows, and
  Linux. Produce signed/notarized installers where the platform supports them,
  plus documented checksum-bearing release artifacts on GitHub.
- Keep the native app deliberately tiny. Bookinator remains a browser-based
  local application; the native shell owns process lifecycle rather than
  duplicating the product UI.
- On double-click, start the loopback-only Bookinator server and pipeline,
  wait for a successful health check, then open the Bookinator URL in the
  user's default browser. Reopening the app should find the existing healthy
  instance and open its tab rather than starting a second server.
- Give the launcher one small status window instead of making it completely
  headless. Show **Starting**, **Running**, **Stopping**, or **Needs attention**;
  the local URL and port; server/pipeline health; and the Bookinator data
  location. Provide only **Open Bookinator**, **Show logs**, and **Quit** as
  primary actions.
- Quitting the native app must gracefully stop the queue, close active model
  responses, let Bookinator persist resumable state, terminate every server
  process the launcher owns, and then exit. The web UI's Stop control remains
  a non-quitting way to pause pipeline work.
- Make lifecycle ownership explicit and testable: no orphan server processes,
  no duplicate instances, no browser-tab ownership assumptions, bounded
  startup/shutdown timeouts, useful failure diagnostics, and recovery after a
  crash or occupied port.
- Preserve developer mode. `./bin/serve` remains the inspectable source-tree
  workflow, while packaged builds locate bundled resources and user data
  without requiring a terminal, Python installation, or repository checkout.
- Define clean install, upgrade, and uninstall behavior. Upgrades must preserve
  the local book library; uninstall must clearly offer whether to retain or
  remove manuscripts, models/configuration, logs, and derived analysis.
- Build a first-launch and readiness-repair guide. On first launch—and whenever
  Bookinator detects that a required capability has gone missing—open the
  relevant setup tool automatically instead of making the user discover Local
  settings, diagnose a pipeline failure, or hunt through documentation.
  Implement the versioned prerequisite matrix and guided-repair contract in
  [`setup-readiness.md`](setup-readiness.md); treat its blockers as product
  support policy rather than scattered UI warnings.
- Present setup as a short, resumable checklist with plain-language outcomes:
  install/start Ollama; install a recommended general reader such as the chosen
  Qwen model; install specialist models such as the emotion classifier; assign
  models to their roles; then run a small local readiness check. Distinguish
  required items from optional heavyweight or specialist additions, preserve
  completed steps, and provide Retry, Skip optional, and Open setup controls.
- Keep consent and download size visible before starting model/runtime installs.
  Setup may launch the correct installer or Bookinator tool and return to the
  checklist automatically, but it must not silently download multi-gigabyte
  models or disguise a failed dependency as a healthy system.
- Organize setup by the user's mental model rather than installation mechanism:
  **Machine** contains the server, document readers, storage, and platform
  components; **Models** contains Ollama, Qwen-family LLMs, role assignments,
  and specialist classifiers. The emotion classifier belongs under Models even
  though Bookinator installs it through Python/Hugging Face rather than Ollama.

## Near-term delivery order

The canonical book-workspace order puts **Reviewer at the far right of the
Analysis shelf** and **Assessment at the far right of the Explore shelf**.
Identity and the two workspace selectors remain in row one. Analysis gathers
the manuscript-reading machinery and culminates in human editorial judgment;
Explore gathers book-level reports and culminates in a qualified assessment of
quality, audience fit, and saleability. Reviewer and Assessment are deliberately
pushed to the right so neither reads as just another machine-generated result.
Revisit whether Plot arcs and Inferences should move only after their real data
and interaction patterns make that distinction clearer; do not move them on
speculation alone.

After the model-free export milestone, build the Reviewer annotation core and
then let Tags, Dossiers, Plot arcs, and Connections become additional
inspectable inputs as they mature.

- **Chapter contract first:** finish the chapter-map proof sheet with stored
  statistics, pattern validation, promotion of legitimate special headings, and
  safe correction of false chapter boundaries. Analysis may run against a
  clearly labeled proposed map; approval blesses that exact map as the
  structural source of truth rather than acting as a compute lock.
- **DRY pipeline-stage framework:** before adding many more analysis passes,
  refactor Chapters, Summaries, Tags, Emotions, Dossiers, Plot arcs, and
  Connections onto one shared stage contract. The shared framework must own:
  stage registration and ordering; readiness and dependency checks; pending,
  queued, running, stopping, complete, partial, failed, and stale states;
  global queue start/stop, stage-level redo, and collapse controls; model selection;
  chapter progress and live activity; bounded retries and chapter-local errors;
  polling without replacing active controls or open UI state; result
  disclosures and source/evidence links; run provenance; invalidation; and
  persistence/API conventions. A new stage should declare its identity,
  dependencies, worker, result schema, and specialized renderer—not copy an
  existing stage and gradually drift. Preserve specialization where it is
  real: Emotions has different segmentation and calibration from Qwen Tags,
  but that does not justify another bespoke lifecycle or action bar.
- **Inference algorithms belong behind one Analysis button:** do not add a
  top-level Pipeline row or top-level Analysis button for every book-level
  inference. `Inferences` owns a compact button bar with independent status,
  dependencies, method, provenance, rebuild behavior, and an inspectable
  result for each algorithm. Start with
  Questions & payoffs and deterministic Dossier connections. Add chronology
  reconstruction, contradiction candidates, recurring-scene use, reveal/setup
  links, and plot-shape algorithms as real results become available; do not
  expose empty algorithm rows as roadmap decoration. The dedicated Analysis
  workspaces remain the places to explore those results.
- **Emotions next:** add a separate Hartmann-powered pipeline stage with
  segment-level seven-label scores, evidence, and chapter-level emotional shape.
- **Tags alongside/after emotions:** use the assigned Qwen reader for structured,
  evidence-backed tags from a fixed vocabulary, with independently tracked
  stage state and provenance inside the shared pipeline framework rather than
  another bespoke lifecycle.
  Follow the evidence and provenance contract in `CHAPTER-SIGNALS.md`.
- **Literary devices as a separate pipeline stage:** locate similes, metaphors,
  imagery, symbolism, personification, and other devices with exact evidence
  ranges. Research and bake off specialist detectors before choosing its model;
  do not fold contradictions or integrity analysis into this stage.
- **Model-free one-book export before human editing:** implement the canonical
  report manifest, offline static viewer, export selection/privacy boundary,
  ZIP packaging, and first public-domain hosted example in
  [`MODEL-FREE-EXPORT-TODO.md`](MODEL-FREE-EXPORT-TODO.md).
- **Human annotations after the export milestone:** finish selection-based notes in the
  chapter viewer, durable anchors, an annotation list, and the shareable
  chapter/page/snippet/comment table. These become the first working tools in
  the far-right **Reviewer** workspace.
- **Causal, plot, and temporal views after annotations:** build these from the
  approved chapter map, chapter signals, and evidence-preserving dossiers so
  every visual connection can be inspected rather than merely admired.
- **Book indices and whole-book synthesis alongside those views:** ship sortable
  entities, locations, times, questions, promises, and facts, then merge the
  piece-level results into compact book views with links to their sources.

## Immediate dossier-powered demo wins

Prefer linked, interactive book views over static reports. The first demoable
slice should reuse the completed dossier fields directly, retain every
chapter/chunk/source link, and make proposed semantic grouping inspectable and
correctable. Do not wait for a perfect whole-book ontology before exposing
useful navigation.

1. **Entity and location indices:** build one reusable index component with
   separate Entities and Locations views. List every dossier mention, group
   likely aliases with an LLM, show the proposed canonical name and occurrence
   count, and link each occurrence to its chapter, source chunk, page range,
   and supporting dossier evidence where available. Let the editor merge or
   split a proposed group. This is the fastest high-visibility win because both
   views share the same interaction and provenance model.
2. **Question ledger and answer links:** consolidate similar questions across
   dossiers, show where each question enters the manuscript, and propose later
   passages that answer, transform, repeat, or leave it unresolved. Preserve
   uncertainty and competing matches. Add the first authored-order connection
   arcs here; selecting an arc opens both endpoints and their evidence.
3. **Fact and event explorer:** provide category filters, semantic clusters,
   authored-order occurrences, and links back to chapters. Use LLM grouping to
   connect paraphrases without flattening distinct propositions—for example,
   bullying as an event, an ongoing condition, a fear, or guilt about an act.
   Reuse the same merge/split and evidence UI as the entity index.
4. **Lightweight connection map:** layer question/answer, repeated entity,
   revisited location, and repeated-fact arcs over the chapter sequence. Keep
   each connection family independently toggleable and make the list view the
   accessible, inspectable source of truth; the diagram is another view of the
   same stored connections, not a separate analysis product.

## Urgent: sharper questions from summaries and dossiers

The current Qwen prompts too often produce generic, low-pressure questions.
Improve question quality before treating the question ledger as editorially
finished. This is a prompt-focus task, not a reason to replace the assigned
model.

- Give **chapter summaries** an explicitly interpretive question brief. Ask
  what remains uncertain about **why** a character chose or avoided something,
  what competing motives may be operating, what a decision costs, how an event
  changes a relationship or the reader's understanding, what thematic tension
  the chapter develops, and what expectation the chapter creates for what must
  happen next.
- Keep **dossier questions** concrete enough to track across later chapters,
  but broaden them beyond missing facts. Include unresolved motivation, causal
  bridges, concealed knowledge, conflicting goals, relationship consequences,
  moral or thematic pressure, promises implied by an important choice, and
  ambiguities that materially affect how the scene can be understood.
- Require every proposed question to name the specific action, revelation,
  contradiction, image, line of dialogue, or change that earned it. Reject
  generic prompts that could be attached to almost any chapter, including
  vague formulations such as “How will this experience affect the character?”
  without a particular unresolved pressure and evidence.
- Prefer questions that a later passage could **answer, complicate, transform,
  or deliberately leave open**. Separate these from free-floating discussion
  prompts and from questions the current passage has already answered.
- Ask Qwen to cover several useful families when the chapter supports them:
  **motivation**, **causality**, **character knowledge**, **relationship
  change**, **thematic consequence**, **reader expectation**, **setup/payoff**,
  and **factual continuity**. Do not manufacture one question in every family.
- Preserve the distinction between a productive interpretive question and a
  manuscript obligation. The UI and saved schema should identify the family,
  evidence range, why the question matters, and whether the manuscript appears
  to promise an eventual answer.
- Build a small before/after fixture from several *Shadow* chapters and review
  the actual questions for specificity, usefulness, duplication, and
  answerability before invalidating the whole book. Version the summary and dossier prompts;
  when the improvement ships, clearly mark affected question artifacts stale
  and explain that regenerating them requires the relevant Summary or Dossier
  work to run again.

## Active: Smells, actionable prose criticism

Do this immediately after a few dossier-powered wins are stable. The Smells
workflow must lead with exact, fixable source ranges and explain why each
passage deserves attention.

- Build a fast local prose-hygiene layer for long and manuscript-relative
  outlier sentences, likely run-ons and comma splices, clause and nesting load,
  delayed subjects, ambiguous or distant pronoun antecedents, repeated sentence
  openings, duplicated words, filler, weak abstractions, punctuation/quotation
  mismatches, dense paragraphs, and rhythm monotony. Separate objective defects
  from contextual craft advice; never imply a universal ideal sentence length.
- The first bakeoff is complete. Keep **spaCy**, guarded **Proselint**, and
  Bookinator-owned checks; they find complementary problems. Mask Markdown and
  headings before Proselint without changing source offsets. Keep **Harper only
  for Oxford-comma candidates** and discard its other advice. Do not add
  LanguageTool (Java) or Vale. Preserve every credible candidate even when only
  one detector reports it, and show every detector reason when they overlap.
- Use a parser for measurable structure—sentence boundaries, dependency depth,
  finite verbs, coordinated and subordinate clauses, antecedent distance—and
  reserve an LLM adjudicator for ambiguous candidates. The LLM may explain or
  dismiss a candidate, but it should not regenerate the passage or invent the
  initial long-sentence/complexity signal.
- Smells is now a first-class, inspectable pipeline stage. Finish the product
  loop with durable per-finding dismissal, **Show rejected**, model-prompt
  versioning, a small editor-labeled regression fixture, and precision/recall
  reporting. The editorial judge must checkpoint batches so a slow or malformed
  later batch cannot hide already completed work.
- Put every result through the shared overlay contract: exact source range,
  detector and rule version, severity or descriptive status, rationale,
  optional suggestion, accept/dismiss, durable dismissal, and **Show rejected**.
  Authors should be able to hide supportive or merely descriptive observations
  and work through likely problems almost mechanically.
- Add a dedicated **Transitions / coherence** search for possible
  non-sequiturs. First inspect each paragraph transition locally; then retrieve
  relevant earlier exact passages plus dossier observations, summaries,
  entities, locations, facts, and unresolved questions. A second-pass judge
  classifies **likely non-sequitur**, **missing transition**, **supported by
  earlier context**, **deliberate interruption/reveal**, or **uncertain**.
  Prior dossiers are retrieval evidence, not an automatic subtraction filter:
  earlier context may explain a reference while the local transition remains
  confusing. Show the suspect transition and the earlier evidence together.
- Keep continuity contradictions in Integrity. Coherence asks whether the reader
  can follow the move *here*; continuity asks whether the move is supported
  *somewhere in the book*. Preserve both findings when both are true.

Second-wave dossier synthesis:

- Reconcile current-scene time and timeline observations into an editable
  chronology only after the basic indices expose extraction and alias errors.
- Generate contradiction candidates only after facts and events have stable
  canonical groupings. A contradiction is a relationship between sourced
  claims, never a free-floating verdict; show both passages, confidence, and a
  non-contradictory alternative reading.
- Defer a full Plot Diagram until question/payoff arcs, event grouping, and
  chronology are useful independently. Plot shapes should be built from those
  inspectable primitives rather than generated as an attractive but
  untraceable picture.

Build semantic reconciliation as a shared versioned artifact rather than one
prompt per screen. Each proposed group records its member dossier items,
canonical label, relation type, confidence, model/prompt version, and human
merge/split decisions. Entities, locations, events, facts, questions, and times
then reuse one grouping/provenance contract while keeping their specialized
renderers.

Current dossier categories are primarily arrays of strings. The first indices
may honestly link each occurrence to its source chunk and page range, but do not
pretend the generic dossier evidence list is a claim-level citation. Before
shipping proposed answers, contradictions, or other editorial findings,
version the dossier item schema so each fact/event/question/time observation
has a durable ID and one or more exact source ranges or quotations. Preserve
the original string artifacts as prior run history during that migration.

## Shared task-pane contract

- Keep every analysis pane on one reusable task-view contract: icon/title/
  subtitle, assigned model, stage-level Redo action, optional structural Rebuild,
  error state, live lower-right activity, progress while incomplete, and no
  progress bar after completion.
- Start and Stop belong to the one global queue on Books. Pending stage panes
  report their place in that queue; they do not create competing local queues
  or task-shaped Start buttons.
- Preserve the same model-alive indicator and ETA placement in every running
  task. A finished task offers **Redo**, never Continue or Resume.
- The Pipeline pane uses one aggregate ledger across every implemented
  chapter-level pass: manuscript chapters × current passes. Individual task
  panes retain their finer progress (chapters for summaries, chunks for
  dossiers). Exclude front matter from the aggregate manuscript denominator.
- Show source metrics in chapter/chunk rows: page range, words, characters,
  paragraphs, and source lines. Add book-level totals and sortable columns where
  they help comparison.
- Keep future panes visible as honest roadmap surfaces rather than fake working
  controls. A planned pane must say what it consumes, what it will produce, and
  that it is not wired yet.

## Reviewer workspace

- Make Reviewer the final workspace tab and the primary human editing surface.
  It consumes the approved manuscript structure, summaries, scored tags,
  dossiers, plot/temporal arcs, chapter connections, and book-wide indices.
- Keep automated claims visibly separate from human annotations. Advice may be
  accepted, rejected, challenged, or linked to a note, but never silently
  becomes the editor's judgment.
- Let the reviewer read the manuscript, highlight a durable text range, attach
  a comment, inspect nearby automated evidence, ask the counter-critic to push
  back, and assemble the chapter/page/snippet/comment handoff without leaving
  this workspace.
- Make selection the entry point: selecting manuscript text reveals a compact
  **Annotate** action. The annotation editor stores freeform editorial text,
  optional category/severity/status, the selected quotation, chapter identity,
  source character offsets, page information when available, and enough
  surrounding-text fingerprinting to repair or flag the anchor after revisions.
- Show a small, unobtrusive marker beside every annotated range. Selecting the
  marker reopens the note; a view control can hide human annotations separately
  from Emotions, Prose, Tags, contradictions, and other automated layers.
- When the selected range overlaps an automated finding—especially a Prose
  hygiene complaint—offer one-click complaint chips such as **Long sentence**
  or **Complicated syntax**. Choosing one creates a normal human annotation
  linked to that exact finding and its provenance; the editor may add text,
  revise the category, or dismiss it. Machine advice never enters the author
  handoff merely because it overlapped the selection.
- Keep annotation history and judgment durable: open/resolved, accepted from
  analysis, rejected, revised, and stale-anchor states must be recoverable.
  Preserve rejected machine findings behind **Show rejected** so Bookinator is
  helpful without becoming nagging or forgetful.
- Build the author handoff from the same annotation records, not a parallel
  report store. Provide a sortable/filterable chapter · original page · quoted
  passage · category · severity · editor comment · status table, then export it
  through Reports. A later author-facing editor may resolve or discuss these
  notes in situ without changing their identity or provenance.
- Provide filters for unresolved annotations, automated findings awaiting
  judgment, author questions, severity, chapter, evidence type, and stale
  anchors after a manuscript revision.

## Pipeline dependency graph and invalidation

- Treat every pipeline artifact as a versioned node with declared inputs. The
  initial graph is Source → Extraction → Chapter map → Saved chapter objects;
  saved chapters feed Summaries and Source chunks, while Source chunks feed
  Dossiers. Future indices and whole-book synthesis must declare their inputs
  the same way rather than hand-coding scattered reset behavior.
- Schedule the global queue in three nested orders: highest-priority book
  first (normally finishing that book before advancing), authored chapter
  order inside the book, then dependency-ordered chapter passes. The initial
  chapter chain is Summary → Dossier; Tags and later chapter checks join this
  same chain instead of creating independent book-wide sweeps.
- Run whole-book synthesis only after every chapter-scoped input it consumes is
  current. Treat that synthesis as a real dependency-graph node, and use the
  deterministic chapter/pass order to learn separate duration estimates for
  each kind of work before publishing a global ETA.
- The **whole-book summary consumes chapter summaries only** and therefore runs
  as soon as every chapter summary is current. It does not wait for Dossiers,
  Emotions, Tags, or any future analysis pass. Those passes may eventually have
  their own book-level rollups, but they are not prerequisites for the summary.
- Model this as a reusable **stage-local rollup barrier**: the expected child
  set must be known, every child artifact must be complete and current, and no
  matching rollup may already be running, complete, or failed for the same
  input signature. Recheck barriers after every child result and when the
  server reconstructs the queue at startup. Register future Dossier, Emotion,
  and Tag rollups through the same contract instead of adding terminal-pipeline
  special cases.
- Experiment with **hierarchical Dossier reconciliation**, but do not assume it
  is an optimization. Benchmark the current one-pass whole-book rollup (about
  15 minutes for Shadow) against chapter-level consolidation followed by a
  final merge. Compare wall time and model work as well as coverage,
  contradiction retention, provenance, and output quality. Adopt it only if
  those measurements justify the added passes and complexity; whole-book
  reconciliation is infrequent enough that a merely clever architecture is
  not a win.
- Give every analysis stage an explicit book-level meaning rather than calling
  every terminal artifact a generic “summary”:
  - **Tags → story signal map:** recurring and changing tag families, chapter
    concentrations, outliers, and source-linked peaks. This describes the
    manuscript; it does not invent a new taxonomy.
  - **Prose → style map:** stable tendencies, deliberate variation, chapter
    outliers, passage coverage, and confidence. Separate supportive,
    descriptive, and cautionary observations.
  - **Smells → editorial worklist:** unresolved reported findings grouped by
    issue, severity, detector agreement, and chapter, with dismissed,
    informational, and user-promoted decisions preserved and filterable. Build
    this deterministically from reviewed candidates; an LLM may label clusters
    but must not decide whether saved findings exist.
  - **Inferences → inference index:** one status-and-results entry per
    independent algorithm (connections, questions/payoffs, later
    contradictions and non-sequiturs), plus cross-links. Inferences are not one
    blocking pipeline pass and should not be collapsed into a single prose
    synopsis.
  Register each actual rollup with its exact child collection, completion
  barrier, input signature, invalidation edges, timing, and source navigation.
- Invalidation walks the graph transitively and marks derived artifacts stale;
  it does not silently delete prior runs. A chapter-map rebuild invalidates
  saved chapters, chunks, summaries, dossiers, and all later book-wide results.
  A summary redo invalidates only summaries and their own consumers—not
  dossiers. A dossier redo likewise leaves summaries intact.
- A structural Rebuild automatically queues fresh summaries and dossiers after
  the new chapter objects and chunks exist. Approval of an unchanged proposed
  map invalidates nothing; it changes provenance from provisional to approved.
- Investigate the chapter-map approval affordance as a deliberate **force redo**
  entry point after a manuscript has already been approved. The UX must clearly
  distinguish “this map is approved” from “reopen and rebuild the map,” explain
  which downstream artifacts become stale, preserve the prior approved map for
  recovery, and require confirmation before invalidating analysis.
- Store input hashes, prompt/schema versions, model versions, and run IDs on
  every node. Green means “current for these exact inputs,” never merely “a
  result exists.” Add regression tests for every dependency edge and every
  first-class Redo/Rebuild control.

## Runtime expectations and watchdogs

- Treat the queue heartbeat as operational state, not decoration. Every running
  status opens live details showing start time, elapsed time with a trailing
  `+`, current book/chapter/chunk, model, input size, saved diagnostics, and a
  guarded Restart action.
- Learn expected duration distributions separately for each stage and model,
  conditioned on machine profile (OS, CPU/GPU/backend, RAM/VRAM), input size and
  structure, context length, and recent observed throughput. Never use one
  global timeout for extraction, Qwen generation, and classifier passes.
- Apply two adaptive thresholds: **taking longer than usual** is a visible
  warning that preserves the running job; **probably stalled** triggers an
  automatic diagnostic probe and bounded recovery. Record the expected range
  and why the watchdog chose its threshold so the decision is inspectable.
- Recovery should close the active response, preserve partial/error diagnostics,
  return the interrupted unit to pending, restart it at most a small bounded
  number of times with backoff, and then continue other safe work. Never leave
  an infinite retry loop or require the user to discover and repair an ordinary
  hung model response manually.
- Distinguish slow from dead using observable progress: streamed tokens,
  classifier segment completion, child-process health, Ollama API health,
  memory pressure, and last durable checkpoint. A long chapter that continues
  producing tokens is not stalled merely because it crossed a wall-clock limit.

## Ingestion quality and regression fixtures

- Treat chapter-map consistency as an editorial warning, not a compute gate.
  When labels break an established heading family, list every suspicious label,
  keep the proposed map inspectable, and let provisional analysis continue in
  the background. Use deterministic structural checks as the reproducible
  warning and an LLM second opinion for genuinely ambiguous maps.
- Every manuscript-specific detector correction must add a small anonymized
  regression fixture. Keep fixtures for numbered chapters with viewpoint
  headings, named-only chapters, tables of contents, prologues/interludes, Roman
  numerals, and chapters that begin mid-page.
- Make **Chapter map** a first-class workspace step. Compare the established
  heading family with excluded page-opening candidates, highlighting anomalies
  and showing both good and bad headings together rather than reporting only
  the outliers. Provisional results remain usable; changing a boundary
  invalidates and regenerates only dependent artifacts.
- Add an editor for the proposed chapter map so a person can promote a valid
  variant (Epilogue, Intermission, or a manuscript-specific heading), merge,
  split, rename, reorder, or demote a false chapter without changing parser
  code. Persist accepted variants as book-specific structural rules and rerun
  the same consistency gate before approval.

## Whole-book synthesis

- Add a book-level result bar for Summaries, Dossiers, and later analysis passes.
  Build it after the piece-level work by asking the assigned model to merge the
  stored results, with links back to every contributing chapter/chunk and the
  exact evidence beneath those artifacts.
- Keep **Dossiers immediately after Summaries** in both the workspace and the
  chapter-pass order because both are navigational readings of manuscript
  units. Preserve separate schemas and provenance for now; reconsider combining
  them only after real usage shows that one view can carry both jobs cleanly.
- Produce a concise overall synopsis, structural outline, character/location/
  time index, unresolved obligations, and prioritized editorial findings. Make
  each section independently regenerable instead of one indivisible report.
- Track synthesis provenance: contributing artifact versions, model, prompt,
  start/finish time, and stale status after any underlying piece is redone.

## Emotions — next implementation priority

- Make **Emotions** its own resumable pipeline stage over canonical chapter
  text. It may contribute signals to the Tags UI, but it has a different model,
  segmentation method, result schema, calibration problem, and lifecycle; do
  not hide it inside one generic LLM tagging request.
- Use
  [`j-hartmann/emotion-english-distilroberta-base`](https://huggingface.co/j-hartmann/emotion-english-distilroberta-base)
  for the first implementation. Its fixed first-pass vocabulary is **anger,
  disgust, fear, joy, neutral, sadness, and surprise**. Pin the model revision,
  record the downloaded-file checksums and license/model-card metadata, and make
  installation inspectable through Local → Models rather than downloading it
  silently during analysis.
- Run the classifier over short, paragraph-aware overlapping segments that fit
  its input window—not one truncated chapter. Retain every segment's source
  offsets, page range, seven raw scores, winning label, and model revision.
  Aggregate chapters with both duration/length-weighted distributions and peak
  moments so a brief emotional turn is not averaged out of existence.
- Be precise about what this first model measures: emotion expressed or
  recognizable in a passage. It does not reliably identify which character
  feels it, whether the narrator endorses it, or what emotion a reader is meant
  to experience. Add those as later evidence-bearing Qwen judgments and keep
  the outputs separate.
- Store a versioned `bookinator-emotion-v1` artifact per chapter containing
  chapter/source signature, model ID and revision, segment policy version,
  segment results, chapter distribution, peaks, runtime, device, completion
  state, and errors. Stop/resume works at segment or chapter boundaries; a
  changed chapter invalidates only that chapter and dependent emotional-shape
  synthesis.
- Display the seven-label distribution, strongest peaks with source links, and
  an authored-order emotional-shape view. Never turn a high anger/fear/sadness
  score into a quality warning. Keep raw classifier outputs available for later
  recalibration.
- Build a small hand-labeled fiction fixture before choosing thresholds. Include
  dialogue, interior monologue, restrained prose, horror, comedy, mixed emotion,
  neutral exposition, archaic language, and negated emotion. Measure calibration
  and editor correction time in addition to ordinary precision/recall.
- Defer GoEmotions, Cardiff TweetNLP, and other emotion models until the Hartmann
  pipeline produces real Bookinator data. They are comparison candidates, not
  dependencies of the first pass.

## Tags — next implementation priority

- Add a separate resumable **Chapter tags** pipeline stage over canonical
  chapter text. Use the book's assigned Qwen-family chapter reader for the first
  pass; do not block implementation on GLiClass, ModernBERT zero-shot, GLiNER,
  or embeddings. Those remain later comparison/candidate-generation models.
- Use the versioned standard vocabulary and scoring anchors in
  [`CHAPTER-SIGNALS.md`](CHAPTER-SIGNALS.md) and
  [`research/chapter-signal-models.md`](research/chapter-signal-models.md).
  The model may score only canonical IDs. New ideas go into a separate
  `candidate_signals` collection and never silently expand the taxonomy.
- Ask Qwen for structured `bookinator-chapter-tags-v1` JSON containing:
  `chapter_sequence`, `taxonomy_version`, `model`, `prompt_version`, and
  `signals`. Every signal contains `id`, `family`, `score`, `confidence`, a
  compact explanation, and one or more evidence records with an exact quote and
  source page/location. Include `candidate_signals` separately. Reject or retry
  malformed results and any material score without evidence.
- First-pass families are **prose mode**, **chapter function**, **reader
  dynamics**, **narrated time**, **viewpoint behavior**, **mood**, **genre
  affinity**, and **theme topic/proposition**. Begin with the canonical IDs
  already documented rather than asking the model to improvise labels.
- Give the model invariant instructions: separate score from confidence;
  describe rather than grade; allow absent and uncertain; distinguish mood from
  character emotion and intended reader emotion; distinguish theme topics from
  propositions; distinguish narrated order from story chronology; and treat
  genre as overlapping affinity rather than one mandatory class.
- Combine model results with deterministic measurements without pretending they
  are the same detector. Calculate dialogue proportion, paragraph/sentence
  metrics, scene breaks, and explicit structural cues directly. Show agreement
  or disagreement alongside the Qwen score and preserve each method's
  provenance.
- Keep authored tags, editor tags, deterministic measures, Qwen inferences, and
  future classifier scores as distinct origins. A later run may supersede an
  earlier inferred result but must never overwrite human metadata or erase run
  history.
- Render the strongest tags on each chapter, plus a sortable/filterable
  all-signals table with family, score, confidence, source evidence, detector,
  model, and taxonomy version. Provide Redo, Stop, resume, chapter-local failure,
  and stale-state behavior consistent with Summaries and Dossiers.
- Use the first real runs to narrow the vocabulary. Evaluate which signals are
  stable, useful, redundant, or consistently vague before adding specialist
  zero-shot scoring. The first encoder comparison after Qwen should be GLiClass
  Edge or Modern Base over exactly the same fixed hypotheses.
- **Pressing performance TODO:** current Qwen 32B tagging is taking roughly
  five minutes per chapter on the development machine. Let the present run
  finish, then profile short, medium, and long chapters; record prompt tokens,
  generated tokens, context-build time, generation time, and evidence payload
  size. Target routine tagging near one minute per ordinary chapter or better.
  Benchmark a smaller assigned model, a more compact schema, and a two-pass
  classification-then-evidence strategy without weakening source-grounded
  claims. Keep 32B available as an explicit deep-tagging option rather than the
  only viable path.
- Later tag families may add figurative-language salience, setting behavior,
  sensory emphasis, humor/dread, causal importance, setup/payoff strength, and
  chapter-end propulsion. Keep examples inspectable and avoid bogus precision.

## Editorial challenge and prose hygiene

- Build the shared **editorial overlay system** described in
  [`research/editorial-overlays.md`](research/editorial-overlays.md): composable
  colored regions for continuous patterns plus conservative, explainable
  underlines for localized prose worth inspecting. Users can combine a few
  layers, control thresholds, and inspect every detector and source range.
- First overlay pass: long sentences, clause/nesting load, repeated words and
  phrases, punctuation/quote problems, rhythm monotony, dense paragraphs,
  manuscript-relative readability outliers, and separate lexical-texture
  filters. Prefer deterministic parsing and counts over model guesses.
- Next maps: prose mode, pacing/rhythm, POV and narrative distance, narrated
  time/tense, information density, sensory versus abstract language, and the
  existing emotion regions. Preserve independent results even when displayed
  together.
- Bake off a CoLA acceptability model, ModernBERT readability regression, and
  a token-level metaphor detector only after the deterministic foundation has
  a labeled fiction fixture. Do not make any of them silent dependencies.
- Do **not** ship “AI likelihood” as an authorship verdict. If explored, call it
  statistical regularity or genericity, expose the contributing measurements,
  label it experimental, and never turn it into an accusation or quality score.

- Add a **counter-critic** role for human findings. It should make the strongest
  evidence-based case against an editor's criticism, identify alternative
  readings, and state what evidence would change its mind. Never overwrite or
  quietly downgrade the human note; show critic, counter-critic, and optional
  judge as separate provenance-bearing voices.
- Add a deterministic prose-hygiene pass for misspellings, duplicated or
  missing words, mismatched quotation marks and brackets, inconsistent dashes
  and ellipses, stray typography/invisible characters, encoding damage,
  accidental page furniture, anomalous Markdown, and suspicious formatting.
- Add a model-assisted **word cruft and prose smell** pass for filler,
  repetition, clichés, vague antecedents, overused gestures/adverbs, accidental
  tense or viewpoint drift, and awkward rhythm. Present passage-level
  candidates—not universal rules—and allow editor dismissal or acceptance.

## Text statistics and authorship signals

- Compute deterministic statistics when saved chapter objects are created:
  characters, words, paragraphs, nonblank source lines, sections/viewpoints,
  sentences, average and distribution of sentence lengths, vocabulary richness,
  dialogue proportion, paragraph-length variation, and readability measures.
  Store raw measurements separately from display formatting.
- Add book-relative comparisons so an editor can see unusual chapters without
  pretending that long sentences, dense vocabulary, or dialogue are defects.
- Research an **AI-writing indicators** pass, but do not label prose as AI-made
  from one detector score. The field has severe domain shift, false positives,
  model/version sensitivity, and incentives for overclaiming. If shipped, show
  multiple signals, calibration data, uncertainty, and the exact passages that
  influenced the result; phrase findings as “resembles this detector’s training
  distribution,” never authorship fact.

## Plot shape and temporal structure

- Build a rigorous Plot Diagram from chapter-level event salience, protagonist
  goal progress, stakes, tension, reversals, revelations, losses/gains, climax
  candidates, and resolution. Preserve competing interpretations rather than
  forcing every story into one Freytag-shaped curve.
- Compare model-generated scores with simpler deterministic signals and a small
  editor-labeled evaluation set. Show inter-model disagreement and allow an
  editor to move or relabel proposed beats.
- Create a temporal graph separate from authored chapter order. Represent story
  events, narrated order, flashbacks/flash-forwards, remembered or hypothetical
  events, simultaneous branches, alternative timelines, loops, and uncertain
  dates. Draw branches and joins with evidence-linked nodes and an adjustable
  confidence threshold.
- Build a complete evidence-linked **story chronology** by reconciling every
  dossier's current scene time, events, and timeline observations across the
  whole manuscript. Keep story time separate from chapter/narration order and
  represent exact dates, approximate intervals, before/after constraints,
  durations, deadlines, ages, travel time, simultaneity, and unknown gaps.
- Treat chronology assembly as a whole-book inference problem rather than
  asking each chunk digest to know the entire clock. Preserve competing
  placements and confidence when evidence is incomplete; surface impossible
  overlaps, inconsistent elapsed time, and date or age contradictions for
  editorial review instead of silently forcing one answer.
- Let editors move, pin, merge, split, or annotate proposed events and choose
  relative versus calendar views. Every event and temporal edge must link back
  to its chapter, dossier observation, and exact source passage.

## Cross-chapter connection map

- Build an authored-order chapter graphic with offset semicircular arcs for
  questions answered, promises kept, repeated facts, contradictions, revisited
  locations, flashbacks/time links, and entity changes.
- Let each connection type be toggled independently. Clicking or hovering an
  arc should show a compact explanation, both endpoints, evidence, confidence,
  and the analysis run that proposed it.
- Bundle dense arcs into lanes and offer filters by entity, severity, confidence,
  and distance between chapters so a large manuscript remains legible.

## Low priority: spatial journey map

- Turn dossier locations into an optional map-based reading of a book. For
  real-world settings—or fictional places that deliberately reuse real names—
  resolve locations cautiously and draw the manuscript's movement between them
  in authored order.
- Represent appearances with small round chapter/sub-section markers. Marker
  labels, color, size, and connecting paths should distinguish authored order,
  repeated visits, simultaneous branches, uncertain locations, and movement
  that is remembered, reported, imagined, or actually occurring.
- Support author-supplied fictional maps as first-class local assets. Provide a
  simple annotation/calibration mode for placing named locations on an image,
  then reuse the same chapter markers and journey paths without pretending the
  image has real-world coordinates.
- Keep every plotted point linked to its dossier evidence, chapter, section,
  and source passage. Let an editor merge aliases, split mistakenly conflated
  places, reposition uncertain points, or mark a location as intentionally
  unmappable.
- Avoid silently sending manuscript locations to a cloud geocoder. Prefer an
  offline gazetteer; if an external map or geocoding service is ever offered,
  make the transmitted place names and privacy tradeoff explicit before use.
- Treat this as a delightful exploratory widget, not a prerequisite for the
  core editorial pipeline. Build it only after the location index and evidence
  links are reliable.

## Low priority: book-title research and collision checking

- Add an optional title-research tool that searches exact titles, close title
  variants, distinctive phrase overlap, and meaningfully similar titles. Show
  likely collisions with author, publication date, edition, publisher, genre,
  identifiers, and direct source links so the user can distinguish a real
  discoverability problem from an unrelated use of ordinary words.
- Separate bibliographic identity from storefront presence. Reconcile title
  and author variants across reliable book catalogs first; treat retailer,
  search-engine, and review-site results as time-stamped external observations,
  never permanent facts about the work.
- Explain why a result is similar: exact match, subtitle overlap, reordered
  phrase, phonetic resemblance, shared distinctive terms, or semantic
  similarity. Let the author dismiss irrelevant collisions and retain useful
  alternatives or research notes.
- Keep manuscript privacy explicit. Title lookup may contact external services,
  but it must transmit only the title and any author/genre terms the user
  approves—not manuscript text or derived analysis.
- Treat sales performance as a stretch research layer. Reliable title-level
  unit sales are often proprietary, incomplete, edition-specific, or distorted
  by format and territory. Show only sourced measures such as disclosed sales,
  time-stamped retailer rank, review counts, library holdings, or other clearly
  labeled proxies; never convert them into invented lifetime-sales estimates.
- A later comparison view may explore whether similar titles appear crowded,
  memorable, genre-appropriate, or commercially legible, but should present
  evidence and competing interpretations rather than issue a universal title
  score.

## Additional analysis ideas

- Add a **character-state ledger**: goals, knowledge, relationships, injuries,
  possessions, location, and beliefs at chapter boundaries. Flag impossible or
  unexplained changes, but preserve uncertainty and evidence.
- Add a **scene-purpose pass** that labels what materially changes in each scene
  and surfaces scenes where no goal, information, relationship, or story state
  appears to move.
- Add **setup/payoff distance** and **absence reports**: promises waiting longest,
  important entities that vanish unexpectedly, and locations or objects heavily
  established but never used.
- Add **voice and viewpoint drift** candidates using vocabulary, sentence
  rhythm, interiority, and knowledge boundaries—presented as comparisons, not
  claims that variation is automatically wrong.
- Add **revision impact**: when a manuscript is re-ingested, identify changed
  chapters, stale downstream artifacts, annotations whose anchors moved, and
  analyses that can safely be retained.
- Add a **reader knowledge ledger** alongside character knowledge: what the
  manuscript has told the reader, what each viewpoint character knows, and
  where suspense depends on the gap between them.
- Add a **causal graph** distinguishing “happened before” from “caused,”
  “enabled,” “prevented,” or “motivated.” Weak or missing causal bridges are
  often more editorially useful than generic plot-hole judgments.
- Add a **motif and image return** index for repeated objects, phrases, sensory
  images, jokes, symbols, and thematic language, including returns that change
  meaning rather than merely repeat.
- Add a **reader promise contract** view: genre promises, opening expectations,
  explicit mysteries, emotional bargains, and which audience expectations the
  ending fulfills, subverts deliberately, or appears to forget.

## Active writing and incremental analysis

- Support a watched manuscript or project folder. Fingerprint chapters and
  rerun only changed chapters plus downstream book-level analyses that actually
  depend on them. Preserve unchanged summaries, dossiers, annotations, and
  provenance.
- Present a revision inbox: changed chapters, added/removed sections, moved
  annotations, newly stale findings, and the minimum recommended analysis queue.
- Let writers add private notes, intentions, unresolved questions, promises,
  continuity reminders, and “check this later” markers while drafting. Treat
  these as author-supplied obligations with distinct provenance—not manuscript
  facts—and follow them through the same evidence-linked queue.
- Consider a focused Markdown writing surface inside Bookinator, but begin with
  excellent watched-file support and round-trip-safe Markdown/DOCX import. A
  full word processor is a separate product-sized commitment and should only
  happen if the analysis-aware writing loop proves valuable.
- Add a low-power companion mode for writers who cannot run the largest local
  model: perform deterministic indexing immediately, queue heavy work for a
  stronger Mac, and import signed/versioned result bundles without losing the
  ability to inspect provenance.

## Unresolved questions and narrative obligations

- Build a book-level **Open questions** pass from the factual questions recorded
  in chunk dossiers. Treat dossier questions as the primary evidence because
  they are generally more concrete and useful than the speculative prompts in
  chapter summaries.
- Track each question forward through later chunks, attaching evidence that
  answers it, partially answers it, contradicts it, or leaves it unresolved.
  Preserve originating chapter/chunk, relevant page ranges, supporting
  passages, model/run provenance, and confidence.
- At the end of the manuscript, present the questions that remain genuinely
  unresolved. Rank factual continuity and story-obligation questions above
  thematic, rhetorical, or reader-reflection prompts.
- Filter low-value questions such as “How does Timmy’s adventure affect his
  perception of himself and his life?” unless the manuscript explicitly frames
  the issue as a promised or unresolved story question. Keep the filtered items
  inspectable so an editor can restore one rather than silently deleting it.
- Let the editor mark a question as resolved, intentionally ambiguous, sequel
  material, irrelevant, or still open. Those judgments should become durable
  workspace data and feed the final editorial report.

## Entity index and appearances

- Build a book-level **Entities** list from the structured entities recorded in
  chunk dossiers. Merge obvious aliases while preserving the original names and
  evidence used for each match; editors must be able to split an incorrect
  merge or combine missed aliases.
- Make the list sortable by name, entity type, first appearance, last
  appearance, chapter count, total mentions, and editorial importance. Keep
  sorting based on structured values rather than display strings.
- For every entity, show links to each chapter in which it appears, in authored
  order. Each chapter link should open the relevant chapter and, where retained
  evidence permits, jump to the supporting section or passage.
- Distinguish a direct manuscript appearance from an entity merely mentioned by
  a model in a summary or inference. Preserve chapter/chunk IDs, page ranges,
  supporting passages, confidence, and model/run provenance.
- Provide filters for people, places, organizations, objects, concepts, and
  unresolved/unknown types, plus a compact entity detail view suitable for
  later continuity and relationship analysis.

## Library-scale metadata, tagging, and workflow

- Build a first-class metadata system for managing a large library of source
  books and manuscripts. Do not treat every value as an undifferentiated tag:
  preserve separate typed fields, controlled vocabularies, freeform labels,
  computed measurements, inferred classifications, and human workflow state.
- Record bibliographic/source identity such as author, editor, translator,
  publisher, imprint, publication date, edition, language, identifier, source
  repository, source URL, file format, rights basis, acquisition date, and
  source checksum. Preserve the difference between work-level identity and the
  specific edition or file Bookinator ingested.
- Add deterministic manuscript measurements including page count, word count,
  chapter/section count, source size, ingestion date, last source change, and
  analysis completion. Sort and filter using raw structured values rather than
  formatted display strings.
- Add editorial and pipeline workflow fields: priority, queued/running/stopped,
  per-pass progress, stale/current results, assigned editor, editor sign-off,
  review status, outstanding annotations, last reviewed date, and readiness for
  author handoff. Sign-offs must identify the person, artifact version, time,
  and exact analysis state that was approved.
- Track export state without pretending that “exported” means “approved”:
  export type, generated time, included artifact versions, destination or
  recipient label when supplied by the user, checksum, and whether newer source
  or analysis changes have made the export stale.
- Support authored, editor-supplied, and model-inferred classifications for
  genre/subgenre, themes, mood distributions, tone, audience, setting,
  viewpoint, narrative form, plot structure, story dynamics, and content
  descriptors. Keep provenance, confidence, taxonomy version, evidence, and
  human confirmation or rejection with every inferred value.
- Provide multi-column sorting, faceted filters, saved views, column selection,
  bulk tagging, bulk priority/workflow changes, and clear chips for active
  filters. Useful views should include unfinished analysis, awaiting editor
  sign-off, stale exports, public-domain demo sources, genre/theme combinations,
  and books whose inferred classifications remain unreviewed.
- Design the Books table and book workspace from one metadata registry so field
  labels, formatting, sorting, filtering, export, validation, and provenance do
  not drift into separate implementations. Allow plugins or future shared
  inator infrastructure to register additional typed fields without rewriting
  the library.
- Define migration and conflict rules before scaling up: aliases and authority
  for authors/publishers, multi-author ordering, unknown versus empty values,
  conflicting embedded/catalog/editor metadata, taxonomy changes, and edition
  replacement. Never silently overwrite a human correction with a later import
  or model run.
- Add compact and expanded library views. The compact table should remain
  operational and sortable; an optional expanded view may expose cover art,
  classification summaries, progress, sign-offs, and export freshness without
  becoming a decorative card grid.

## Sharing and portability

- **Next milestone:** implement the model-free, self-contained HTML publication
  in [`MODEL-FREE-EXPORT-TODO.md`](MODEL-FREE-EXPORT-TODO.md). Keep this section
  as the larger portability context rather than a duplicate implementation
  checklist.
- Define a versioned `.bookinator` workspace archive that can preserve the full
  inspectable analysis and optionally include the manuscript.
- Add a viewer-only import mode for less powerful Macs, with model controls
  hidden or disabled and imported provenance clearly identified.
- Generate the portable editorial PDF from the same canonical workspace data.

## Not too soon: report publishing

- Add report-publishing controls only after the annotation, finding, sign-off,
  whole-book synthesis, and export-provenance contracts are stable. Reviewer is
  where editorial decisions are made; publishing packages those decisions for
  another person. It must never silently convert unreviewed model output into
  an approved editorial conclusion.
- Export polished PDF reports with selectable sections, book/edition identity,
  editor attribution and sign-off, generation time, source fingerprint,
  analysis/model provenance, evidence citations, and explicit stale-state
  warnings. Support author-facing, editor-detail, and compact summary presets
  without creating separate report data models.
- Generate a model-free **live mini viewer site** from the same canonical report
  manifest. It should be a self-contained, responsive local/static site with
  navigation, summaries, findings, annotations, plots, selected evidence, and
  provenance—usable without Bookinator, Ollama, or a running server.
- Let the editor preview exactly what will be shared, include or exclude each
  section, redact manuscript passages, choose whether the source manuscript is
  omitted, and verify that private notes stay private. The PDF and mini site
  must consume one report-selection state so their contents cannot drift.
- Treat every generated PDF or viewer site as a versioned export artifact.
  Record its manifest, included analysis versions, checksum, creation time,
  format version, and freshness relative to later manuscript or editorial
  changes. Allow regeneration and comparison; do not overwrite history
  silently.
- Keep the mini viewer honest about “live”: initially it means an interactive
  static export, not a hosted collaboration service. Hosting, comments,
  authentication, update channels, and revocation are separate later decisions
  with privacy and security consequences.

## Human annotations and editorial handoff

- Deliver annotations in this order: selection capture → durable text anchors →
  annotations list → shareable chapter/page/snippet/comment table. Each step is
  independently useful and must survive restarts before the next one ships.

- Let an editor select text in the chapter viewer and press **Annotate** to add
  a durable, local comment. Preserve the book and chapter IDs, chapter label and
  title, chapter page range, the smallest useful quoted snippet, the comment,
  surrounding anchor text, and timestamps so the note can survive reflow and
  modest manuscript revisions.
- Show saved highlights in the local reader, but never require hover text to
  understand or transport a note.
- Compose a shareable notes table with **Chapter**, **Chapter pages**, **Text
  snippet**, and **Comment** columns. The portable PDF/HTML export should contain
  only the cited snippets and comments—not the full manuscript—so an editor can
  send human reading notes to an author or friend without redistributing the
  book.
- Include annotation provenance and a source-manuscript fingerprint in exports,
  with an explicit warning when an annotation's text anchor no longer matches a
  revised manuscript.
