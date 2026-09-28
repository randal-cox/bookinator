# Bookinator TODO

## Current milestone: Reviewer Tools

The 0.2.0 working release name is **Reviewer Tools**. Sharper questions,
in-manuscript annotation, reviewer sign-off, portable human comments, and the
evidence-anchored editorial first pass all serve the same center of gravity:
giving a human reviewer useful proposals, durable judgment, and an attributable
author-facing handoff.

Make Bookinator ask specific, editorially useful questions in chapter summaries
and dossiers, then give a human reviewer the smallest real workflow needed to
answer the machine back. Questions should identify their editorial family,
the manuscript evidence that triggered them, why they matter, and whether the
text appears to promise an answer. Reject generic prompts that could apply to
any novel.

The proto-Reviewer is deliberately narrower than the eventual editing suite:
read canonical chapter text, select an exact passage, attach a categorized and
prioritized comment, reopen it later, resolve it, or permanently delete a
debugging mistake. Keep human judgment visually and structurally distinct from model
output. Use **Frankenstein** as the first clean-book stress test for both the
new prompt contract and the annotation anchors.

Close this milestone with deterministic whole-book rollups for **Tags** and
**Smells**. Tags summarize frequency, strength, family, and chapter coverage;
Smells summarize undismissed issue types, counts, severity, and chapter reach.
These are immediate overviews of saved chapter work, not additional model jobs. Emotions, Tags, and Smells should each expose a compact, disclosure-based whole-book rollup as soon as any chapter results exist.

### Immediate transition: two model roles

Bookinator now has two global LLM assignments: **Primary reader** for
substantive manuscript analysis and **Fast intake & utilities** for other cheap,
structured work. Remove per-book and per-stage model controls from Analysis;
the model recorded on each completed run remains visible as provenance. Keep
specialist non-LLM dependencies, such as the emotion classifier, explicit in
Machine without pretending they are interchangeable reader roles.

The model-free one-book publication described in
[`MODEL-FREE-EXPORT-TODO.md`](MODEL-FREE-EXPORT-TODO.md) remains the distribution
follow-through. It should let one capable Bookinator machine produce an
analysis that authors and editors can inspect and annotate later without local
models or expensive hardware.

### Carmilla release audit

The September 27 full run completed every chapter-scoped pass and all three
model rollups across the Prologue and sixteen numbered chapters. Its saved
evidence anchors are healthy: every reported Smell and every rejected LLM
Review candidate resolves to exact chapter text. The run also exposed the
remaining release work rather than silently qualifying as a pass:

- Questions & Payoffs was interrupted after it entered `running`; retry it and
  verify that both the inference row and overall pipeline settle honestly.
- Rebuild the EPUB structure with the trailing Gutenberg “Other books by”
  catalogue excluded. The current parser also no longer repeats the next
  chapter title at the previous chapter boundary; keep both cases covered by
  extraction regression tests.
- Validate the new deterministic narrative-person guard across a broader mix
  of first-, second-, third-, and embedded-document narration. The taxonomy now
  reserves `mystery` for genre affinity and uses `withheld_information` for the
  distinct reader-dynamics concept.
- Calibrate the skeptical LLM Review pass. It rejected all 30 source-anchored
  candidates and promoted none. That may be defensible for a canonical work,
  but the uniform outcome and repeatedly protective “intentional gothic style”
  rationale need human inspection before becoming the expected threshold.
- Normalize model-emitted Smell labels at storage or presentation time. This
  run produced many spellings of the same clause-load family; detector rule
  provenance must remain available underneath the canonical editor-facing name.
- Complete the human portion of the release gate: add a real Carmilla
  annotation, sign off as the reviewer, export and inspect HTML and PDF, then
  test a `.bookinator` backup and collision-safe restore.

### Near-term responsiveness and regression loop

- Profile the roughly three-second frozen interval when opening a book. Keep
  initial navigation and shell rendering immediate; hydrate large pipeline,
  chapter, annotation, and report payloads asynchronously, and retain the
  current page instead of presenting an apparently hung interface. Measure
  server serialization, JSON transfer and parsing, pipeline-ledger migration,
  artifact rehydration, and DOM rendering separately before choosing a fix.
- Keep Carmilla as the serious end-to-end Reviewer Tools regression, but add a
  much cheaper chaptered smoke-test book for ordinary development. Prefer a
  short work with several real divisions so it still exercises chapter
  interleaving, cumulative context, rollups, Questions & Payoffs, LLM Review,
  exports, and restore—not a one-section essay that merely finishes quickly.
- Record elapsed time and model-call count for both tiers. The smoke test should
  catch workflow breakage quickly; Carmilla remains the slower quality and
  ambiguity test before release.
- Keep manuscript identity tiered. Trust complete EPUB/DOCX/YAML title and
  author metadata immediately; do not wake a model to repeat authoritative
  fields. For PDFs and incomplete sources, deterministically collect short
  candidate blocks from document metadata, filenames, title-page typography,
  opening pages, and copyright/byline patterns. The later Jev-compatible
  attention router can cheaply rank those blocks with narrow questions such as
  “is this likely to contain the work title?” and “is this likely to name the
  author?” before the fast utility model extracts only from the shortlist.
  Preserve the candidate and confidence trail so a quick answer remains
  inspectable rather than magical.

## Milestone capstone: evidence-anchored editorial first pass

Use the Frankenstein stress test to close the better-questions and
proto-Reviewer work, then add an explicitly machine-authored editorial pass as
the final large piece of this milestone.
This is the integrated final analysis step: Qwen reads each canonical chapter
alongside its saved summary, dossier, emotions, Tags, and undismissed Smells,
then proposes a small number of useful editorial annotations. It may correctly
return no proposals. The goal is discernment, not coverage.

Keep this feature safe for editors and genuinely useful for authors:

- Store proposals separately from human annotations. Label them visibly as
  **Proposed by Qwen** with model, prompt version, input versions, and run time.
  They must never inherit a reviewer name, satisfy reviewer sign-off, or appear
  in an author handoff merely because the model emitted them.
- Require an exact quotation that exists in the canonical chapter. Resolve it
  to chapter identity, character offsets, original pages when available, and a
  surrounding-text fingerprint. Reject invented, ambiguous, or unanchorable
  quotations before saving the proposal.
- Ask for a bounded editorial record: category, priority, concise comment,
  actionable revision question or suggestion, why it matters, and which saved
  signals informed it. Do not dump emotions, Tags, or Smells back at the user;
  synthesize them only when they support a real observation.
- Default to roughly three to five strong proposals per chapter and permit
  fewer. Repetition, generic praise, plot summary, style policing without
  consequence, and paraphrases of deterministic Smells are failures.
- Put proposals in a review queue where a human can accept, edit, reject,
  challenge, or leave them undecided. Acceptance creates a normal editorial
  annotation that preserves its machine origin and the reviewer’s later edits;
  rejection remains durable calibration evidence rather than disappearing.
- Make reruns versioned and non-destructive. Changed source text or changed
  upstream analysis marks proposals stale; it does not rewrite accepted human
  comments or resurrect rejected advice.
- Treat this as an inspectable per-chapter Analysis pass with ordinary queue,
  progress, retry, failure, and timing behavior. It is not an Inference job and
  it must not block the existing evidence-producing passes.
- Evaluate the first pass on Frankenstein with a short human-written rubric:
  anchor correctness, specificity, actionability, novelty beyond existing
  Smells, false-positive burden, and whether an editor would keep the note.

Product language should frame this as a **first reader, not a final editor**.
For authors it can provide a serious editorial starting point; for editors it
can triage passages and assemble candidates without claiming their judgment.
The distinction is structural, not merely a disclaimer: machine proposals,
human decisions, and exported advice remain separately attributable.

- Extend the new full-library progress view with per-pass ETA learning and a more detailed inspectable ordering forecast. High, Normal, and Low books auto-run; Shelved books remain browseable but stay out of the automatic queue.
- Instrument manuscript preparation and chapter-map construction with high-resolution elapsed timing. Preserve sub-second precision (for example, 1.2 ms) in the saved pipeline ledger and timing charts rather than rounding fast structural work to zero.

## Almost urgent: GLiNER Entity Signals

Do not bury GLiNER inside the later attention-router experiment. Prototype it
as a useful pipeline in its own right as soon as the Reviewer Tools release gate
is clean. A fast, source-anchored entity inventory has immediate value even
before Qwen consumes it, and it can become common evidence for dossiers,
Connections, continuity, character work, questions, and LLM Review.

- Start with Apache-2.0 `urchade/gliner_small-v2.1` for English manuscripts and
  bake it off against `gliner_medium-v2.1`. Prefer the small model if entity
  recall is acceptably close; the point of this pass is cheap, early evidence.
  Evaluate the supported ONNX CPU path on Apple Silicon as well as ordinary
  PyTorch before choosing the runtime.
- Make **Entity Signals** an inspectable per-chapter Analysis stage with a
  deterministic whole-book rollup. Save every mention's canonical text span,
  chapter, character offsets, original pages when available, requested label,
  raw label, confidence, model revision, threshold, and run timing.
- Begin with a versioned fiction vocabulary: person, named animal, group,
  place, institution, creature, artifact, significant object, document or work,
  event, supernatural force, technology, and fictional substance. Test labels
  empirically; similar labels can compete, so do not expand the vocabulary
  casually or silently.
- Present useful results before identity resolution: grouped mention lists,
  frequency, first and last appearance, chapter coverage, and links to every
  source span. Clearly call these **mentions**, not canonical characters or
  facts. Surface overlapping or competing labels rather than pretending the
  model settled them.
- Feed the evidence spans into chapter dossiers immediately, but ask Qwen to
  perform the harder work: aliases, pronouns, identity, merge/split decisions,
  relationships, chronology, narrative importance, and fact reconciliation.
  Compare dossier completeness, hallucinated entities, prompt size, and elapsed
  time with and without the Entity Signals packet.
- Add a later whole-book reconciliation step that proposes canonical entities
  from the mentions without destroying the underlying spans. Human merge,
  split, rename, and ignore decisions must survive reruns and become
  calibration evidence.
- Keep installation optional, visible in Machine, and explicit. Never silently
  download model weights. If GLiNER is unavailable, dossiers retain their
  present Qwen-only path.
- Validate first on Shadow, The Dunwich Horror, Carmilla, Frankenstein, and The
  Maltese Falcon. Score span correctness, label usefulness, missed important
  entities, duplicate surface forms, runtime, and downstream dossier value—not
  generic NER benchmark accuracy.

## Future-enabling refactor: replaceable compute workers

This is the planned **0.3.0 — The Engine Room** milestone. Finish and release
Reviewer Tools first, then separate the worker process, durable control plane,
and web controller before extracting any pipeline implementation into Inator.
Bookinator must prove the process boundary and reconnect behavior; Inator gets
the resulting contract, not the current server-owned thread machinery.

Bookinator is local-first today, but its useful audience is artificially limited
by the cost and speed of local model inference. Preserve local processing as the
default and add a clean compute-provider boundary so the same UI can eventually
use one local worker, several machines on a LAN, rented GPU capacity, or a
hosted Bookinator service. **This section does not commit Bookinator to AWS or
make remote processing a near-term milestone.** The intermediate refactor is
valuable on its own because it separates computation from presentation, makes
crash recovery explicit, and permits safe parallelism.

### Three useful Bookinators, not one oversized requirement

- Treat deep analysis, light analysis, and review as distinct hardware tiers.
  **Deep analysis** uses the primary reader for summaries, dossiers, editorial
  review, and whole-book synthesis and may require a modern high-memory machine.
  **Light analysis** runs deterministic detectors and specialist models for
  chapter structure, statistics, emotions, Smells candidates, entity mentions,
  taxonomy hypotheses, and other bounded signals on more ordinary hardware.
  **Review and editing** opens an already-complete `.bookinator` package with
  no model installation required. Product requirements and setup guidance must
  say which tier each capability belongs to rather than claiming one
  intimidating minimum for the whole application.
- Give Light analysis its own honest completion contract and availability
  disclosure. Missing Qwen artifacts are not failures: label the result as a
  specialist-only analysis and state which deeper readings were not run. A
  later Deep analysis machine must be able to add the remaining stages without
  discarding the cheap work.
- Keep the portable Bookinator object as the handoff between those tiers. It
  must contain the source, analysis, assets, provenance, and reviewer state
  needed for another installation to open, inspect, annotate, and export the
  book without recreating expensive analysis.
- Make the directory worker below the medium-term bridge: a headless Python
  process uses the same durable library and job files as the local UI, keeps
  processing after the browser closes, and exposes progress when the browser
  reconnects. The browser is a controller and observer, not the owner of the
  worker lifetime.
- Give the UI a conspicuous global Pause control for that worker, with honest
  active, pausing, paused, and draining states. Before enabling unattended use
  for a broad audience, add explicit opt-in/autostart policy, workload profiles,
  battery and thermal awareness, quiet hours, and clear explanations of CPU,
  memory, and GPU use so background analysis never feels like malware.

### Near-term shared Inator background runner

- Build a small double-clickable companion that owns the background service
  without pretending to be the full product UI. On macOS it should fit naturally
  as a menu-bar application; equivalent Windows and Linux shells may use the
  system tray. Its compact surface shows current work, queue depth, learned ETA,
  recent history, Start/Pause, resource policy, diagnostics, and **Open
  Bookinator**.
- Make background capability declarative in the shared Inator shell. Products
  without workers omit the controls; products with workers provide service
  identity, queue/status endpoints, workload profiles, and launch action rather
  than forking another bespoke launcher.
- Install and manage the platform-native service mechanism (LaunchAgent on
  macOS, an appropriate user service on Windows/Linux). Never equate “installed”
  with “allowed to monopolize the machine”: default to conservative concurrency,
  lower process priority, yield between safe pipeline units, and offer idle-only,
  battery, thermal-pressure, quiet-hours, and manual-pause policies.
- Treat model calls as bounded units that may not be safely preemptible. A Pause
  request should stop before the next unit, describe whether the current call is
  draining or being cancelled, and optionally unload idle models. Do not claim
  instantaneous suspension when the provider cannot guarantee it.

### Machine-learned completion estimates

- Replace one flat average per stage with a local performance model built from
  this machine's completed attempts. Estimate fixed overhead plus throughput per
  input character/token for each stage, model, prompt/schema version, and
  provider; use robust recent samples so one crash or pathological chapter does
  not distort every book.
- Calculate both whole-book and **work remaining** estimates from the actual
  unfinished chapter/chunk input sizes. Include current elapsed work and serial
  rollups, exclude human reviewer time, and label confidence honestly while the
  machine is still learning.
- Show the estimate immediately after structural intake so the library can help
  choose demo-sized books before expensive work starts. Preserve the underlying
  per-stage estimate and confidence interval for inspection instead of exposing
  one falsely precise finish time.

The product promise worth preserving is compelling: an author with an ordinary
computer could optionally submit a book, watch durable results arrive within
minutes, and pay a bounded amount on the order of a few dollars rather than own
an expensive inference machine. A deliberately aggressive future offer might
be “process a book in minutes for about $10,” using several large workers when
the workload parallelizes cleanly. Treat that as a benchmark and product
hypothesis—not a price claim—until real books establish tokens, elapsed time,
startup overhead, failure rates, and cost.

### Architectural seam

- Refactor every model-backed pipeline step to depend on a small compute
  provider protocol rather than call Ollama directly: submit an immutable job,
  observe it, cancel it, and retrieve normalized results. Local Ollama becomes
  the first provider and remains fully supported.
- Keep the browser and local Bookinator server authoritative for the library,
  user choices, review state, and presentation. Workers receive only the
  bounded source and saved evidence required for one job; they do not need the
  whole application or unrestricted access to the local workspace.
- Define a filesystem-shaped transport that works in an ordinary directory
  first and maps cleanly to an object store later. Organize immutable job
  envelopes, leases/claims, heartbeats, attempts, incremental result objects,
  terminal manifests, diagnostics, and cancellation requests by book, stage,
  chapter, and stable job ID.
- Do not use the presence of `.done` alone to claim a job. Local workers should
  claim through atomic creation or rename; remote/object-store workers should
  use conditional writes. Claims have an owner and an expiring lease so an
  abandoned job becomes eligible for retry after a machine dies.
- Make submission and result application idempotent. A stable job ID plus
  prompt, schema, model, source, and dependency versions must make duplicate
  delivery harmless. Publish results to temporary/versioned names, validate
  them, then expose one terminal manifest atomically. Never let the UI consume
  a partially written result.
- Preserve every attempt rather than overwrite it. Record worker identity,
  provider, model and quantization, prompt/schema versions, timestamps, token
  counts, timings, estimated/actual cost, exit reason, and structured failure.
  The local pipeline chooses the accepted result and retains rejected or stale
  attempts as inspectable provenance.
- Let the UI monitor the shared transport and merge completed results as they
  appear. The UI must remain useful while workers are offline, reconnect after
  restarts, distinguish queued/claimed/running/stale/failed/complete, and never
  infer liveness merely from a persisted `running` label.
- Express dependencies in job data rather than process order. Independent
  chapter work may run concurrently; whole-book reconciliation waits for its
  declared inputs. Cap concurrency per model/provider so parallelism improves
  throughput without exhausting VRAM or multiplying expense invisibly.
- Keep deterministic and cheap local stages local unless measurement proves a
  reason to move them. Remote execution is primarily for heavyweight model
  inference, not a reason to upload everything.

### Backend progression

1. **In-process local provider:** wrap the current Ollama calls behind the new
   provider and normalized job/result contracts without changing behavior.
2. **Directory worker:** run a separate worker process against a shared local
   directory. Prove atomic claims, leases, heartbeats, retries, cancellation,
   result validation, and recovery after killing either process.
3. **Local multi-worker experiment:** use two processes or two trusted machines
   on a LAN. Benchmark chapter-level parallelism and prove that duplicate work,
   stale leases, and out-of-order results cannot corrupt pipeline state.
4. **Object-store adapter:** map the same logical protocol to secure remote
   storage and notifications without teaching the UI AWS concepts. The local
   application should be able to watch results even after compute has vanished.
5. **Disposable GPU proof:** benchmark one representative book on a modest
   rented GPU and a credible 14B-capable machine (at least roughly 32 GB usable
   VRAM; preferably a 48 GB L40S-class worker). Compare local M1, rented GPU,
   and any faster option by model-load time, tokens per second, stage time,
   total time, failures, and actual cost.
6. **Optional managed provider:** only after the protocol is trustworthy,
   consider AWS Batch/ECS, another GPU rental service, or a Bookinator-operated
   service. Providers remain replaceable; no analysis schema or UI should
   depend on one vendor.

### Remote security and cost guardrails

- Remote processing is explicit opt-in per book/run. Explain exactly what text
  and derived evidence leave the computer, where they are stored, who operates
  the account, retention duration, and how deletion is verified. Local-only
  remains a first-class mode rather than a degraded fallback.
- Encrypt transport and storage; use narrowly scoped per-job credentials,
  private storage, auditable access, automatic expiration, and no inbound
  public worker service. Prefer workers that pull bounded jobs and push results.
- Keep durable inputs/results in inexpensive encrypted object storage; treat
  GPU instances as disposable and untrusted to preserve state. Download or
  ingest each completed result immediately, but do not require the local UI to
  remain online for the remote job to finish safely.
- Put several independent brakes between a bug and a large bill: allowed
  instance-type list, maximum worker count, per-job wall-clock limit, idle
  shutdown, absolute instance TTL, external watchdog/reaper, queue kill switch,
  low budget alarms, and a conspicuous live estimate of accrued and maximum
  remaining cost. A worker must not be solely responsible for terminating
  itself.
- Start with one modest on-demand worker. Do not introduce Spot interruption,
  Kubernetes, multi-GPU instances, or automatic wide fan-out until ordinary
  execution and cost accounting are proven. Parallelism must show the user its
  multiplier before submission.
- Benchmark before promising speed. A 14B model on a 48 GB L40S-class GPU may
  plausibly beat an M1 by several times, and an H100 plus parallel chapter work
  may approach an order-of-magnitude end-to-end gain, but prompt ingestion,
  model loading, serial rollups, and retries make hardware ratios unreliable.

### Product and ecosystem implications

- Remote workers could expand Bookinator from owners of unusually capable
  computers to nearly any author or editor willing to trust a selected provider
  and pay a bounded per-book charge. Fast, inexpensive reruns also make revision
  comparison and iterative editing substantially more useful.
- Permit bring-your-own-compute: a publisher, writing group, or technically
  capable friend could operate a worker while authors keep the Bookinator UI on
  modest laptops. A future hosted provider is one implementation, not the
  architecture.
- Be candid about the historical constraint: Bookinator combines many long,
  evidence-rich readings of a manuscript. This product is only becoming
  practical as strong public models and affordable high-memory inference
  converge. Hosted proprietary LLM APIs could have reduced the infrastructure
  burden earlier, but would change privacy, reproducibility, model control, and
  per-token economics. Keep an API-backed provider possible without making
  OpenAI, Anthropic, AWS, or any other vendor the canonical engine.
- Use saved timing and cost provenance to answer the business question with
  data: actual cost per book, cost by pass, speed versus quality, useful
  parallelism, rerun cost after revisions, and which analyses deserve premium
  compute at all.

## Planned 0.4.0 milestone: Look Here

Finish **0.3.0 — The Engine Room** first. Its independent worker and durable
control protocol are prerequisites for safely managing another local model.
Then add an **editorial attention router**: a small, replaceable decision model
that tells Qwen where to look. It produces ranked candidate evidence, never an
editorial conclusion.

### Decision contract and first engine

- Define an internal Jev-compatible contract for typed **yes/no**, **choice**,
  and **score** judgments. Save the exact state, question wording, options,
  probabilities, confidence, model ID and revision, prompt-contract version,
  threshold version, source ranges, elapsed time, and routing decision.
- Begin with Apache-2.0 `simple-jev` as the integration baseline and benchmark
  Qwen2.5-3B as the first small decoder. The public `us/jev-local` measurements
  make that model a credible candidate, but the repository currently exposes
  no software license, so use its results as research rather than importing its
  code. Keep the adapter replaceable and evaluate dual MIT/Apache `jev-rs` if
  the Engine Room adopts llama.cpp/GGUF strongly enough to make its
  one-prefill path attractive.
- Prefer several narrow yes/no judgments to one clever multiclass question.
  For a candidate passage and narrative question, separately ask whether it
  directly addresses the question, adds new information, reduces uncertainty,
  contradicts or complicates the current understanding, and supplies an
  answer. Reduce those results deterministically into **irrelevant**,
  **reminder**, **advance**, **complicate**, **resolve**, or **uncertain**.
- Treat confidence as routing evidence, not truth. Wording, option order, and
  model priors can move probabilities; preserve an uncertainty band that always
  falls through to Qwen.

### One-model-at-a-time scheduling

- Never keep the small router resident beside Qwen and never alternate models
  passage by passage. Claim a coherent batch, load the router once, score the
  entire book or stage, persist a resumable candidate ledger, unload the
  router, then load Qwen once to consume the ranked work.
- Make router batches ordinary Engine Room work with queue priority, pause,
  cancellation, retries, timing, stale-input invalidation, and standard
  input/output inspection. Record load and unload time separately so apparent
  savings do not hide model-thrashing costs.
- If the router is absent, failed, uncalibrated, or sees an unsupported input,
  fall back to the existing full-Qwen path. Specialist installation remains
  optional and never begins as a silent model download.

### Staged experiments

1. **Smells calibration laboratory and first optimization.** Score existing deterministic candidates
   for likely editorial usefulness. Run in shadow mode first: do not suppress
   any finding, and compare scores with dismissals, retained findings,
   promotions, overlapping human annotations, and reviewer actions. Once the
   held-out recall gate is met, let confidently irrelevant candidates skip
   Qwen while every uncertain candidate falls through to the current path.
   Measure model-load overhead and Qwen batches avoided, not merely router
   accuracy.
2. **Tags fast path.** Compare Jev-style hypothesis decisions with GLiClass or
   ModernBERT over the fixed tag taxonomy. Ask Qwen for evidence and synthesis
   only for plausible or uncertain tags; retain Qwen 32B as the deep path. A
   router may suppress an implausible taxonomy hypothesis, but it must never
   manufacture the evidence-bearing tag artifact itself.
3. **Entity Signals and dossier feedstock.** Promote the near-term GLiNER pilot
   into an Engine Room batch with durable model lifecycle, standard inspection,
   and measured dossier improvements. Preserve its standalone entity report;
   the output is useful even when Qwen never consumes it.
4. **LLM Review attention routing.** Evaluate passage windows against narrow
   lenses such as causality, continuity, motivation, emotional logic,
   confusion, scene purpose, engagement, and payoff. Initially rank the packet
   without removing any chapter from Qwen's review.
5. **Questions and payoffs.** Use embeddings to retrieve likely passages, then
   apply the decomposed yes/no judgments above. Qwen reconciles the surviving
   evidence across chapters and remains responsible for the explanation.

### Calibration and release gate

- Build versioned gold cases from multiple genres and structures, with separate
  train/tuning and held-out books. Include Shadow, The Dunwich Horror,
  Frankenstein, Carmilla, and at least one book where the present detector or
  reviewer produced substantial false positives.
- Measure candidate recall, precision at each threshold, false-negative type,
  Qwen input tokens, passages sent to Qwen, model-load overhead, wall-clock
  time, and reviewer keep/dismiss outcomes. Report focus improvement even when
  elapsed time does not improve.
- Keep every experiment in shadow mode until it has at least 200 diverse,
  human-adjudicated positive examples and held-out recall of at least 98% for
  human-promoted or annotation-overlapping candidates, with no major editorial
  family below 95%. These are graduation gates, not claims of general literary
  accuracy.
- Graduate one expensive stage only after it cuts Qwen-reviewed passage volume
  by at least 30% without crossing those recall gates. Display how many
  candidates were routed, passed through, held as uncertain, or skipped, and
  let developers inspect every skipped item.
- Treat **10–30% less primary-reader work across a complete book** as the
  initial performance hypothesis, not a promised speedup. Measure Qwen calls
  and input tokens alongside wall-clock time because model loading and swapping
  can erase an apparent routing win.
- Routers never inherit a reviewer name, satisfy sign-off, or enter an
  author-facing report as findings. They are scouts. Qwen and the human remain
  separately attributable readers.

### Non-magical primary-reader optimization research

Routing is the first practical saving, but retain five additional experiments
for the expensive Summary, Dossier, Context, and LLM Review paths. None may
weaken the saved artifact contract merely to improve a timing chart.

1. **Confidence-based model cascades.** Let a smaller reader attempt a narrow,
   structured artifact and escalate malformed, unsupported, contradictory, or
   low-confidence results to the primary reader. Compare total model-loading,
   prefill, generation, retry, and validation cost—not only the fast model's
   inference time. Do not use self-reported confidence as the only escalation
   signal.
2. **Reusable prefix and KV work.** Summary, Dossier, Context, and Review often
   read overlapping canonical text. Evaluate runtimes that can safely reuse a
   stable source prefix or saved prefill state across distinct prompts. Version
   the tokenizer, model, prompt prefix, and source hash; silently reusing an
   incompatible cache is worse than recomputing it.
3. **Better evidence packets.** Use GLiNER mentions, Jev decisions, retrieval,
   deterministic measurements, prior Context, and exact source spans to reduce
   rediscovery. Measure both input reduction and omissions. Comprehensive jobs
   such as Summary and Dossier retain a full-reading fallback when a packet is
   not demonstrably sufficient.
4. **Bookinator-specific distillation.** Treat versioned Qwen artifacts plus
   human promotions, dismissals, edits, and annotations as a possible future
   training corpus for narrow local readers. Separate training, threshold
   tuning, and held-out books; preserve licenses and manuscript privacy; never
   train on private user text without explicit consent.
5. **Interchangeable faster compute.** The Engine Room provider contract should
   permit a stronger local machine, a LAN worker, or an explicitly chosen
   rented GPU to execute the same immutable job. Compare normalized outputs,
   provenance, startup overhead, privacy, and total cost. Faster hardware is an
   execution option, not permission to fork pipeline semantics.

For every experiment, preserve the current Qwen path as the quality baseline.
Track input and output tokens, time to first token, generation time, retries,
model load/unload cost, artifact validity, anchor correctness, and human-rated
editorial value. A cheaper answer that omits essential book evidence is not an
optimization.

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
  components; **Models** contains Ollama, Qwen-family LLMs, the two global role assignments,
  and specialist classifiers. The emotion classifier belongs under Models even
  though Bookinator installs it through Python/Hugging Face rather than Ollama.

## Near-term delivery order

### Urgent: split the browser application into owned modules

`web/app.js` has outgrown safe single-file maintenance. Prune it into cohesive
modules without changing behavior: workspace navigation and routing; pipeline
and queue presentation; chapter reader and annotations; Analysis renderers;
Explore reports and exports; library/import; dialogs and shared controls. Keep
one explicit state boundary, avoid circular imports, and move shared primitives
before feature code so later work stops duplicating interactions inside the
monolith. Require the existing full test suite plus direct browser smoke tests
through the transition.

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

Complete the better-questions and proto-Reviewer vertical slice first. Then use
the Frankenstein run to expose prompt, provenance, and anchoring failures before
expanding Reviewer to Tags, Dossiers, Plot arcs, and Connections. Plot arcs are
a distinct later milestone; improved entity/location grouping can ship in a
smaller intervening pass.

- **Enforce the proposal boundary, with an explicit demo escape hatch:** Qwen
  produces editorial **proposals**, never reviewer comments. A proposal must not
  receive a reviewer's name, satisfy reviewer sign-off, or enter an
  author-facing report until a human accepts it. For development, testing, and
  deliberate demos, provide a disabled-by-default override that can promote
  proposals into exportable demo annotations and complete a simulated review.
  Stamp every promoted record and resulting report as **Demo/test acceptance**,
  never attribute it to a real reviewer, keep the operation reversible, and
  prevent the override from silently becoming the normal workflow.
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
- **Lightweight annotation and guidance models:** keep a short, explicit bake-off
  queue for specialist models that can cheaply annotate the manuscript or give
  a larger reader better evidence. The first candidates are semantic Echoes,
  metaphor-related language density, GLiNER open-label spans, and ModernBERT
  hypothesis scoring. These models propose evidence; Qwen interprets it and a
  human remains the editorial authority. See
  [`research/chapter-signal-models.md`](research/chapter-signal-models.md).
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
- Keep permanent deletion narrow and explicit: it removes a human note from the
  reader, reports, and exports and cannot stand in for disagreement. Model
  claims and editorial comments instead need durable response threads where a
  reviewer, author, or counter-critic can agree, disagree, qualify, and cite
  another passage without erasing the claim being contested.
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
- Schedule the global queue in four nested orders: first perform deterministic
  structural intake for every imported manuscript (including Shelved books),
  then choose the highest-priority analyzable book, authored chapter order
  inside that book, and dependency-ordered chapter passes. The initial chapter
  chain is Summary → Dossier; Tags and later chapter checks join this same chain
  instead of creating independent book-wide sweeps.
- Show the resulting next-task order explicitly on the Pipeline page. A later
  queue editor may select one or more tasks and move them to a durable human
  head-of-queue lane. Persist those overrides as ordered queue records with
  actor, timestamp, and completion scope instead of rewriting book priority.
  The precedence is: structural intake, human-pinned tasks, ordinary book
  priority, then FIFO ties. Pins survive restart and expire only when their
  selected unit completes or the user removes them.
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
    manuscript; it does not invent a new taxonomy. Start with a deterministic
    whole-book frequency rollup: total uses and chapter coverage for each tag,
    sortable by frequency and grouped by tag family, so the manuscript's most
    common signals are visible at a glance.
  - **Prose → style map:** stable tendencies, deliberate variation, chapter
    outliers, passage coverage, and confidence. Separate supportive,
    descriptive, and cautionary observations.
  - **Smells → editorial worklist:** unresolved reported findings grouped by
    issue, severity, detector agreement, and chapter, with dismissed,
    informational, and user-promoted decisions preserved and filterable. Build
    this deterministically from reviewed candidates; an LLM may label clusters
    but must not decide whether saved findings exist. Lead with a whole-book
    issue-frequency rollup showing each smell type and its unresolved count,
    with chapter coverage and drill-through to the underlying findings.
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
- Treat substantive back matter—especially appendices—as authored, analyzable
  sections rather than automatically excluding it with boilerplate. Mark its
  structural role separately from narrative chapters, retain it in the chapter
  map, and design a role-aware analysis profile: ordinary summaries, dossiers,
  tags, and relevant smells may still apply, while narrative-only passes should
  be optional or interpreted differently. Distinguish this from indexes,
  licenses, publisher ads, and other non-content back matter.

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
- **Medium priority — genre and thematic-setting coverage:** strengthen the
  canonical vocabulary and tag prompt so Qwen explicitly considers overlapping
  genre affinities such as fantasy, horror, mystery, science fiction, romance,
  thriller, and historical fiction instead of naming only the most obvious
  shelf. Add a distinct **setting character** family for descriptions such as
  contemporary urban, isolated rural, Gothic domestic, institutional,
  frontier, or secondary-world—not proper-place extraction such as Chicago.
  These remain optional, evidence-backed signals rather than boxes the model
  must fill. Calibrate the change against **Shadow** and **The Dunwich Horror**:
  it should recover meaningful fantasy affinity in the former without
  manufacturing every plausible genre or confusing locations with setting.
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
- Build a **figurative-language density** experiment in honest layers. Begin
  with a token-level VUA/MIPVU-style detector and call its output
  *metaphor-related language density*: it can catch indirect, conventional,
  direct, implicit, and personifying metaphorical uses, but it is not a
  universal detector for simile, symbolism, irony, hyperbole, metonymy, or
  imagery. Preserve token spans and scores, then add separately evaluated
  detectors or rules for those other families before presenting an aggregate
  figurative-language measure.
- Build a **semantic Echoes** experiment from sentence or paragraph embeddings.
  Use similarity to retrieve candidate callbacks, recurring images, repeated
  exposition, and near-duplicate phrasing across distant chapters. Similarity
  alone must not label a motif, setup/payoff, or defect; Qwen or an editor must
  explain what recurs and whether its meaning changes.
- Evaluate **GLiNER** as a cheap open-label span generator for people, groups,
  places, institutions, creatures, artifacts, events, and supernatural forces.
  Feed its evidence spans into dossiers and Qwen prompts, but retain the
  existing merge/split workflow because extraction is not identity resolution.
- Evaluate **ModernBERT NLI/zero-shot scoring** against explicit, versioned
  hypotheses for scene function, genre affinity, thematic setting, viewpoint
  behavior, and narrative texture. Treat scores as candidate evidence and
  routing hints, never as calibrated literary fact.
- Every specialist artifact must retain model revision and license, prompt or
  hypothesis version, exact source ranges, raw scores, aggregation rules, and
  thresholds. Benchmark Shadow, The Dunwich Horror, and Frankenstein before
  choosing defaults; keep installation optional and never download a model
  silently.
- Do **not** ship “AI likelihood” as an authorship verdict. If explored, call it
  statistical regularity or genericity, expose the contributing measurements,
  label it experimental, and never turn it into an accusation or quality score.

- Add a **counter-critic** role for human findings. It should make the strongest
  evidence-based case against an editor's criticism, identify alternative
  readings, and state what evidence would change its mind. Never overwrite or
  quietly downgrade the human note; show critic, counter-critic, and optional
  judge as separate provenance-bearing voices.
- Add a **whole-book LLM Review synthesis pass** after every chapter review is
  current. Collate recurring strengths, recurring risks, minority/outlier
  concerns, audience and commercial patterns, and disagreements between the
  first reader and counter-review. Preserve chapter and passage provenance;
  this is a new timed, invalidatable pipeline artifact, not a concatenated
  summary or a replacement for the chapter reviews.
- Generate the documented **LLM Review rubric reference** directly from the
  versioned server dimension definitions and prompt contract. The UI should
  not advertise an implementation count such as “10 rubric dimensions”; Docs
  should explain each dimension, applicability, scoring, confidence, first
  reader, counter-review, and human-promotion semantics without duplicating a
  hand-maintained list.
- Add a deterministic prose-hygiene pass for misspellings, duplicated or
  missing words, mismatched quotation marks and brackets, inconsistent dashes
  and ellipses, stray typography/invisible characters, encoding damage,
  accidental page furniture, anomalous Markdown, and suspicious formatting.
- Add a model-assisted **word cruft and prose smell** pass for filler,
  repetition, clichés, vague antecedents, overused gestures/adverbs, accidental
  tense or viewpoint drift, and awkward rhythm. Present passage-level
  candidates—not universal rules—and allow editor dismissal or acceptance.
- Give canonical Smell families stable icons and use them consistently in the
  whole-book rollup, chapter findings, exported HTML, and PDF. Keep detector
  rule names in provenance, while collapsing synonymous surface labels such as
  clause-load, clause-count, clause-load-proxy, and clause complexity into one
  editor-facing family.

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

- **Distribution follow-through:** implement the model-free, self-contained HTML publication
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
