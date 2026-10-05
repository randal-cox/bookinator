import { createInatorIcon, createProductAboutPage, createProductDocsFlow, defineCitationRegistry, defineProductAbout, defineTrustSurface } from "/commons/@inator/ui/index.js";

export const bookinatorAbout = defineProductAbout({
  product: { name: "Bookinator", summary: "A local-first editorial workbench that connects manuscript evidence across chapters while preserving human judgment." },
  citation: { title: "Bookinator", authors: ["Randal Cox"], version: "0.1.0", year: 2026, url: "https://github.com/randal-cox/bookinator", text: "Randal Cox. Bookinator, version 0.1.0 (2026)." }
});

const recordRoutes = Object.freeze({ milestones: "#releases/milestones", roadmap: "#roadmap/priorities", security: "#security", privacy: "#privacy" });

function uniqueModels(system = {}) {
  const roles = system.models?.roles || {};
  const records = new Map();
  const add = (id, role, provider, ready = null) => {
    const modelId = String(id || "").trim();
    if (!modelId) return;
    const current = records.get(modelId) || { id: modelId, roles: [], provider, ready };
    if (role && !current.roles.includes(role)) current.roles.push(role);
    if (ready != null) current.ready = ready;
    records.set(modelId, current);
  };
  for (const model of system.ollama?.models || []) add(model, "Installed locally", "Ollama", true);
  add(roles.primary, system.models?.roleLabels?.primary || "Primary reader", "Ollama", system.ollama?.running);
  add(roles.fast, system.models?.roleLabels?.fast || "Fast intake & utilities", "Ollama", system.ollama?.running);
  add(system.glinerModel?.modelId, "Entity and classification specialist", "Hugging Face · isolated Python", system.glinerModel?.ready);
  add(system.emotionModel?.modelId, "Emotion classifier", "Hugging Face · local Python", system.emotionModel?.ready);
  return [...records.values()];
}

function modelSource(record) {
  const family = record.id.split(":")[0];
  const gliner = record.id.includes("gliner");
  const emotion = record.id.includes("emotion-english-distilroberta");
  const qwen = /^qwen/i.test(record.id);
  return {
    id: `model-${record.id.toLowerCase().replace(/[^a-z0-9.-]+/g, "-").replace(/^-|-$/g, "")}`,
    type: "software", title: record.id,
    authors: [{ literal: emotion ? "Jochen Hartmann" : gliner ? "Fastino" : qwen ? "Qwen Team" : "Model publisher" }],
    issued: { literal: "Current model release" }, version: record.id,
    genre: record.roles.join(", ") || "Installed local model",
    url: gliner || emotion ? `https://huggingface.co/${record.id}` : `https://ollama.com/library/${encodeURIComponent(family)}`,
    citationText: `${record.id}. ${record.provider}. Used locally by Bookinator${record.roles.length ? ` for ${record.roles.join(", ")}` : ""}.`
  };
}

function createModelCitationRegistry(system) {
  return defineCitationRegistry({ id: "bookinator-models", sources: uniqueModels(system).map(modelSource) });
}

function createBookinatorTrust(system) {
  const models = uniqueModels(system).filter((model) => model.roles.some((role) => role !== "Installed locally"));
  const modelInputs = models.map((model, index) => ({ id: `model-${index + 1}`, label: `${model.id} · ${model.roles.join(", ")}`, version: model.id }));
  const modelInputIds = modelInputs.map(({ id }) => id);
  return defineTrustSurface({
    id: "bookinator-editorial-chain", title: "How Bookinator turns a manuscript into editorial evidence",
    provenance: {
      id: "bookinator-editorial-provenance", schemaVersion: "1",
      subject: { id: "editorial-evidence", label: "Saved editorial evidence", kind: "local-workspace", claimIds: ["local-pipeline", "visible-provenance", "human-authority"] },
      producer: { id: "bookinator", label: "Bookinator", version: bookinatorAbout.citation.version },
      inputs: [{ id: "manuscript", label: "Imported manuscript with page and chapter provenance" }, ...modelInputs],
      steps: [
        { id: "ingest", label: "Extract text and establish reviewable chapter boundaries", kind: "deterministic", inputIds: ["manuscript"], dependsOnStepIds: [] },
        { id: "signals", label: "Run local deterministic and specialist evidence passes", kind: "local-analysis", inputIds: modelInputIds, dependsOnStepIds: ["ingest"] },
        { id: "reading", label: "Create chapter records and cumulative context", kind: "local-model", inputIds: modelInputIds, dependsOnStepIds: ["ingest", "signals"] },
        { id: "reconcile", label: "Build whole-book connections, questions, and editorial synthesis", kind: "local-model", inputIds: [], dependsOnStepIds: ["reading"] },
        { id: "review", label: "Keep human annotations and sign-off separate from machine proposals", kind: "human-review", inputIds: [], dependsOnStepIds: ["reconcile"] },
        { id: "publish", label: "Create bounded PDF or offline HTML reports", kind: "export", inputIds: [], dependsOnStepIds: ["review"] }
      ]
    },
    evidence: { id: "bookinator-trust-evidence", entries: [
      { id: "local-boundary", claimId: "local-pipeline", kind: "source", status: "supported", summary: "The browser uses Bookinator's loopback server and locally configured model runtimes.", basis: "The maintained server, live system inventory, and model-role assignments." },
      { id: "run-ledger", claimId: "visible-provenance", kind: "observed-data", status: "supported", summary: "Saved attempts retain model identity, timing, input size, failure detail, and source-linked artifacts.", basis: "The per-book pipeline and artifact inspectors." },
      { id: "review-boundary", claimId: "human-authority", kind: "human-review", status: "supported", summary: "Machine findings remain proposals until a reviewer accepts, dismisses, annotates, or signs off.", basis: "Reviewer annotations and sign-off are stored separately from model output." }
    ] },
    limitations: {
      id: "bookinator-trust-limits", claimId: "editorial-evidence",
      boundary: "Trust describes the recorded chain of work; it does not certify the literary truth of a model's interpretation.",
      doesNotEstablish: ["That every important manuscript problem was detected.", "That a model interpretation is correct, fair, or aligned with author intent.", "That a completed pipeline is a completed edit.", "That model behavior will remain identical after a model, prompt, or manuscript revision."],
      openQuestions: [
        { id: "model-benchmark", text: "The Qwen 2.5 versus Qwen 3.8 intake speed and quality comparison remains to be run." },
        { id: "artifact-packet", text: "A portable per-book Trust packet should bind exported claims to the exact saved source and model-run snapshot." }
      ]
    }
  });
}

function trustIntro(system) {
  const section = document.createElement("section"); section.className = "book-about-models";
  const heading = document.createElement("header");
  const icon = document.createElement("span"); icon.className = "about-box-icon"; icon.append(createInatorIcon("models"));
  const copy = document.createElement("div"); copy.innerHTML = `<h3>Models and tools in this installation</h3><p>Generated from Bookinator's live system inventory. Citation exports use the same list.</p>`;
  heading.append(icon, copy); section.append(heading);
  const list = document.createElement("div"); list.className = "book-about-model-list";
  for (const model of uniqueModels(system)) {
    const article = document.createElement("article");
    const name = document.createElement("strong"); name.textContent = model.id;
    const roles = document.createElement("span"); roles.textContent = model.roles.join(" · ") || "Installed locally";
    const status = document.createElement("small"); status.textContent = `${model.provider}${model.ready == null ? "" : model.ready ? " · Ready" : " · Not ready"}`;
    article.append(name, roles, status);
    list.append(article);
  }
  section.append(list); return section;
}

async function aboutSystemInventory() {
  try {
    const response = await fetch("/api/system", { cache: "no-store" });
    if (!response.ok) throw new Error("System inventory unavailable");
    return await response.json();
  } catch {
    return { models: { roles: {}, roleLabels: {} }, ollama: { models: [], running: false }, glinerModel: { modelId: "fastino/gliner2.5-small-v1", ready: false }, emotionModel: { modelId: "j-hartmann/emotion-english-distilroberta-base", ready: false } };
  }
}

function installAboutIcons(root) {
  root.querySelectorAll("[data-inator-icon]").forEach((mount) => mount.replaceChildren(createInatorIcon(mount.dataset.inatorIcon)));
}

let activeAboutController = null;
let aboutRenderSequence = 0;

function bindSharedAboutDisclosure(disclosure) {
  if (!disclosure) return;
  // Commons currently constructs disclosures before their product panel is connected.
  // Rebind only the trigger; the dialog, focus, Escape, backdrop, and close behavior remain shared.
  disclosure.trigger.addEventListener("click", (event) => {
    event.stopImmediatePropagation();
    disclosure.dialog.open(disclosure.trigger);
  }, { capture: true });
}

export async function createBookinatorAboutPage({ root, tabs } = {}) {
  const renderSequence = ++aboutRenderSequence;
  root.innerHTML = '<p class="book-about-loading" role="status">Preparing the current Bookinator record…</p>';
  const system = await aboutSystemInventory();
  if (renderSequence !== aboutRenderSequence || root.dataset.articleCollection !== "about") return null;
  activeAboutController?.destroy();
  const sections = Object.entries(tabs || {}).map(([id, [label, content]]) => ({ id, heading: label, content }));
  const controller = createProductAboutPage({
    root, productLabel: bookinatorAbout.product.name, productContent: createProductDocsFlow({ sections }), about: bookinatorAbout,
    citationRegistry: createModelCitationRegistry(system), trust: createBookinatorTrust(system), trustIntroContent: () => trustIntro(system),
    recordIds: Object.keys(recordRoutes)
  });
  activeAboutController = controller;
  bindSharedAboutDisclosure(controller.trustDisclosure);
  bindSharedAboutDisclosure(controller.citationDisclosure);
  installAboutIcons(root);
  for (const [record, href] of Object.entries(recordRoutes)) {
    const link = root.querySelector(`.inator-record-link--${record}`);
    if (link) link.href = href;
  }
  return controller;
}
