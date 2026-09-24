export const roadmapItems = [
  {name: "Reviewer annotations", description: "Highlight manuscript text, write durable editorial comments, accept or dismiss machine findings, set priority, and carry reviewed decisions into author-facing reports.", tags: ["Reviewer", "Editing", "Reports"], ease: 5, impact: 5},
  {name: "Sharper summary and dossier questions", description: "Focus Qwen on specific motivation, causality, character knowledge, relationship change, thematic consequence, reader expectation, and setup/payoff questions instead of generic discussion prompts.", tags: ["Questions", "Prompts", "LLM"], ease: 5, impact: 4},
  {name: "Author action panel", description: "Turn accepted smells, findings, and comments into a rapid chapter-by-chapter editing queue where authors can revise text, respond, defer, or mark an issue resolved.", tags: ["Author", "Editing", "Workflow"], ease: 4, impact: 5},
  {name: "Revision comparison", description: "Compare manuscript versions at line, passage, scene, and chapter scale, then summarize what materially changed and which prior findings became stale or resolved.", tags: ["Versions", "Editing", "Infrastructure"], ease: 4, impact: 5},
  {name: "Portable mini-site", description: "Export a private, model-free analysis site with reviewed findings, plots, annotations, evidence excerpts, and provenance for authors on ordinary computers.", tags: ["Sharing", "Reports", "Author"], ease: 4, impact: 5},
  {name: "Editorial assessment room", description: "Assess clarity, propulsion, character appeal, agency, stakes, payoff, voice, genre fit, and commercial positioning with evidence, counterarguments, and visible model disagreement.", tags: ["Assessment", "LLM", "Reviewer"], ease: 4, impact: 5},
  {name: "Scene purpose map", description: "Identify who wants what, what obstructs them, what changes, and why the next scene follows; surface scenes with weak state change or repeated structural jobs.", tags: ["Structure", "Scenes", "Plot"], ease: 4, impact: 5},
  {name: "Open questions and payoffs", description: "Follow mysteries, promises, setup, repetition, answers, and intentional ambiguity across the manuscript with exact evidence at both endpoints.", tags: ["Continuity", "Reader", "Plot"], ease: 5, impact: 4},
  {name: "Character state ledger", description: "Show where each character begins and ends a chapter: location, goals, knowledge, beliefs, relationships, injuries, possessions, and unresolved intentions.", tags: ["Characters", "Continuity", "Author"], ease: 4, impact: 5},
  {name: "Character intelligence", description: "Combine presence, agency, emotional movement, relationship changes, dialogue share, voice, goals, and causal influence into an evidence-linked portrait of every major character.", tags: ["Characters", "Connections", "Reports"], ease: 4, impact: 5},
  {name: "Causality and coherence map", description: "Distinguish happened-before from caused, enabled, prevented, and motivated; find missing bridges, unsupported decisions, overloaded coincidences, and local non-sequiturs.", tags: ["Causality", "Integrity", "Plot"], ease: 3, impact: 5},
  {name: "Multiple plot arcs", description: "Chart external action, goal progress, agency, emotional pressure, mystery pressure, relationships, revelations, losses, and setup/payoff activity without forcing one universal story curve.", tags: ["Plot", "Charts", "Structure"], ease: 3, impact: 5},
  {name: "Reader memory simulation", description: "Read chapter by chapter as readers with different attention and recall, tracking what feels salient, forgotten, confusing, expected, or genuinely surprising.", tags: ["Reader", "LLM", "Research"], ease: 3, impact: 5},
  {name: "Revision impact graph", description: "After an edit, identify moved anchors, changed obligations, invalidated analyses, newly broken connections, and downstream work that can safely remain cached.", tags: ["Versions", "Infrastructure", "Continuity"], ease: 3, impact: 5},
  {name: "Continuity engine", description: "Reconcile character state, world rules, deadlines, objects, relationships, and reader knowledge to find impossible or unexplained changes across distant chapters.", tags: ["Continuity", "Integrity", "Characters"], ease: 3, impact: 5},
  {name: "Author-intent contracts", description: "Let an author state goals such as ‘keep this a surprise until Chapter 12,’ then test revisions against those intentions as evidence-linked manuscript unit tests.", tags: ["Author", "Intent", "Editing"], ease: 3, impact: 5},
  {name: "Evidence and anchor foundation", description: "Give every observation, comment, event, relationship, and obligation stable source ranges, version signatures, provenance, and repairable anchors across manuscript revisions.", tags: ["Infrastructure", "Provenance", "Versions"], ease: 4, impact: 4},
  {name: "Editorial packet builder", description: "Package reviewed findings, annotations, summaries, charts, evidence, sign-off, and freshness into configurable author, editor-detail, and compact PDF reports.", tags: ["Reports", "Reviewer", "Sharing"], ease: 4, impact: 4},
  {name: "Geography and journey maps", description: "Plot real-world travel or place story events on an author-supplied fictional map, preserving authored order, uncertainty, simultaneous branches, and evidence.", tags: ["Geography", "Charts", "World"], ease: 3, impact: 4},
  {name: "Story chronology graph", description: "Separate narrated order from story time using before/after constraints, durations, dates, ages, flashbacks, simultaneity, uncertainty, and competing placements.", tags: ["Time", "Continuity", "Graph"], ease: 2, impact: 5},
  {name: "Dialogue dynamics", description: "Inspect interruption, dominance, unanswered questions, information asymmetry, subtext, and who changes the direction of a conversation.", tags: ["Dialogue", "Characters", "Scenes"], ease: 3, impact: 4},
  {name: "Motif evolution", description: "Trace returning objects, phrases, sensory images, jokes, and symbols, including where a repeated image changes meaning rather than merely recurring.", tags: ["Style", "Themes", "Reader"], ease: 3, impact: 4},
  {name: "Attention budget", description: "Measure how many new names, locations, rules, mysteries, and concepts a reader must absorb at once and where old threads go cold.", tags: ["Reader", "Readability", "Structure"], ease: 3, impact: 4},
  {name: "Editorial calibration corpus", description: "Learn privately from accepted, dismissed, restored, and resolved findings to evaluate detectors and tune ranking to an editor without inventing universal rules.", tags: ["Evaluation", "Reviewer", "Infrastructure"], ease: 2, impact: 5},
  {name: "Editorial sandbox", description: "Move or remove scenes, compare alternate endings, and estimate which promises, knowledge boundaries, causal links, and downstream passages each experiment disturbs.", tags: ["Editing", "Simulation", "Versions"], ease: 2, impact: 5},
  {name: "Time-travel consistency", description: "Extend chronology into branches, loops, overwritten histories, observer-specific knowledge, causal origin, paradox candidates, and uncertain timeline joins.", tags: ["Time", "Science fiction", "Graph"], ease: 1, impact: 5},
  {name: "Character voice test", description: "Hide dialogue attribution and test whether speakers remain distinguishable through vocabulary, rhythm, syntax, interiority, and recurring verbal habits.", tags: ["Dialogue", "Characters", "Style"], ease: 3, impact: 3},
  {name: "Audiobook lens", description: "Find confusable character names, unclear dialogue attribution, typography-dependent meaning, and passages likely to become harder when heard instead of seen.", tags: ["Audio", "Accessibility", "Names"], ease: 3, impact: 3},
  {name: "World-rule ledger", description: "Collect every stated rule, exception, demonstration, and apparent violation for magic systems, technologies, institutions, and fictional cultures.", tags: ["World", "Continuity", "Genre"], ease: 2, impact: 4},
  {name: "Counter-critic panels", description: "For consequential assessments, show the criticism, the strongest evidence-based defense, and an optional judge without silently erasing human judgment.", tags: ["Reviewer", "LLM", "Trust"], ease: 3, impact: 3},
  {name: "Adaptation lens", description: "Expose cast load, location load, effects-heavy sequences, contained episodes, and scene dependencies for adaptation exploration without judging the novel by production cost.", tags: ["Adaptation", "Structure", "Reports"], ease: 2, impact: 3},
  {name: "Book-title collision research", description: "Search exact and similar published titles, explain the kind of overlap, and—where defensible—show sourced, time-stamped market proxies without inventing sales figures.", tags: ["Titles", "Research", "Market"], ease: 2, impact: 2},
];

roadmapItems.forEach((item) => { item.payoff = item.ease * item.impact; });

export const articlePages = {
  about: {
    kicker: "About Bookinator",
    title: "A memory for the whole manuscript",
    intro: "Bookinator is a local editorial workbench for problems that only become visible after somebody has read every chapter and kept unusually good notes.",
    mark: true,
    tabs: {
      story: ["The idea", `<h2>Find what the author forgot.</h2><p>A detail appears on page 30: a promise, a rule, an unanswered question, a character who cannot read. Four hundred pages later, the manuscript may contradict it—or simply never return. Ordinary summaries are very good at smoothing those details away. Bookinator is built to keep them alive.</p><div class="story-thread"><i></i><h3>The manuscript makes an obligation</h3><p>Bookinator records the fact, thread, promise, or question with exact source evidence.</p></div><div class="story-thread"><i></i><h3>The book changes</h3><p>Each chapter can advance, resolve, modify, or challenge what came before.</p></div><div class="story-thread"><i></i><h3>The editor gets an argument, not a verdict</h3><p>Findings show their passages, provenance, criticism, and defense. The human editor decides what matters.</p></div>`],
      use: ["Who it is for", `<h2>For editors who work at book scale</h2><p>Bookinator is for developmental editors, authors, and researchers working with manuscripts too large for a single prompt and too interconnected for isolated copyediting.</p><h3>It looks for</h3><p>Unresolved threads, continuity failures, chronology trouble, repeated explanations, terminology drift, unsupported claims, unclear causality, and passages whose purpose has become difficult to defend.</p><p>It does not replace editorial judgment. It gives that judgment a durable memory and a faster route back to the evidence.</p>`],
      local: ["Why local", `<h2>The unpublished book stays unpublished.</h2><p>Bookinator runs on the editor's computer. Manuscript text is extracted locally, stored locally, and analyzed by local models through Ollama.</p><p>The promise is plain: <strong>Bookinator does not need to send the manuscript to a commercial language-model service.</strong></p>`],
    },
  },
  guide: {
    kicker: "Bookinator guide", title: "A short tour of the gizmo", intro: "Enough to get oriented. The serious manual can grow alongside the serious machinery.",
    tabs: {
      start: ["Start a book", `<h2>From PDF to living book</h2><ol class="guide-steps"><li>Drop a PDF into any manuscript well.</li><li>Check the title and author Bookinator found.</li><li>Review the detected chapters before expensive analysis begins.</li><li>Let the local reader work chapter by chapter.</li></ol>`],
      state: ["Book State", `<h2>What the book asks us to remember</h2><p>Chapter summaries answer what happened. Book State answers what still matters.</p><p>It keeps ledgers for entities, facts, questions, promises, threads, terminology, claims, and timeline constraints. Items remain active until the manuscript gives Bookinator evidence that something changed.</p>`],
      findings: ["Findings", `<h2>Follow the evidence</h2><p>A finding is not a mysterious score. It is a claim with severity, confidence, source passages, the critic's argument, and—when enabled—an adversarial defense.</p><p>Agree, disagree, call it intentional, or leave a note. Human dispositions survive later analysis runs.</p>`],
    },
  },
  docs: {
    kicker: "Bookinator documentation", title: "How the machine is put together", intro: "A compact technical map of local projects, models, evidence, and repeatable analysis.",
    tabs: {
      overview: ["Overview", `<h2>The working architecture</h2><p>Bookinator combines a loopback Python server, an HTML/CSS/JavaScript interface, local PDF extraction, project state, and Ollama inference.</p><p>The browser is the control surface. The server owns files, jobs, installation checks, and model communication.</p>`],
      projects: ["Book projects", `<h2>One directory per book</h2><p>Every imported book becomes a portable local project containing its immutable source, extracted Markdown, page provenance, ledgers, runs, and reports.</p>`],
      models: ["Models", `<h2>Different jobs, different costs</h2><p>A quick model can identify a title page; a stronger primary model can reconcile Book State and perform whole-book analysis; an embedding model can retrieve distant, related passages.</p>`],
    },
  },
  legal: {
    kicker: "Bookinator information", title: "Legal and privacy", intro: "Short, readable promises now; formal release documents before distribution.",
    tabs: {
      privacy: ["Privacy", `<h2>Local means local.</h2><p>Bookinator is designed to keep manuscripts, derived text, model prompts, embeddings, findings, and reports on the user's computer.</p><p>Installing a model may contact Ollama's registry. Manuscript content is not part of that request.</p>`],
      license: ["License", `<h2>Business Source License 1.1</h2><p>Bookinator 0.1.0 is source-available. Personal, educational, research, and internal business production use is permitted; offering Bookinator as a commercial hosted or managed service, or selling it as part of a competing commercial product, requires a separate commercial license.</p><p>On September 24, 2030, this version converts to GPL-3.0-or-later. The repository <code>LICENSE</code> file contains the controlling terms.</p>`],
      terms: ["Terms", `<h2>Editorial aid, not editorial authority</h2><p>Bookinator produces evidence-linked hypotheses. It can be wrong, overly literal, or unaware of deliberate ambiguity. Authors and editors remain responsible for applying its findings.</p>`],
    },
  },
  roadmap: {
    kicker: "Bookinator roadmap",
    title: "A larger memory for the book",
    intro: "This is the working field of possibilities: practical editorial wins, enabling foundations, and ambitious experiments. The order is a hypothesis, not a promise—sort it to see what rises when ease, impact, or subject matters most.",
    tabs: {
      priorities: ["Priorities", `<section class="roadmap-introduction"><div><h2>Build the editorial loop, then widen the intelligence.</h2><p>Bookinator already reads a manuscript as connected evidence rather than isolated prompts. The next work closes the loop between machine observation, human judgment, author revision, and trustworthy sharing. Beyond that lie deeper models of causality, reader memory, character state, geography, and time.</p></div><dl><div><dt>Ease</dt><dd>How directly the idea can grow from foundations already in Bookinator.</dd></div><div><dt>Impact</dt><dd>How much editorial or author value the finished capability could create.</dd></div><div><dt>Payoff</dt><dd>Ease × impact. A useful first ordering—not a substitute for judgment.</dd></div></dl></section><section class="roadmap-landscape" aria-label="Roadmap payoff landscape"><div><strong>Close the loop</strong><span>Reviewer · Author editing · Revisions · Sharing</span></div><i aria-hidden="true"></i><div><strong>Understand the book</strong><span>Scenes · Characters · Causality · Reader memory</span></div><i aria-hidden="true"></i><div><strong>Explore the frontier</strong><span>Chronology · Maps · Simulations · Time travel</span></div></section><section class="roadmap-ledger" data-roadmap-ledger></section>`],
    },
  },
};
