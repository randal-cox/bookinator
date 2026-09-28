import { articlePages, roadmapItems } from "./pages.js";
import { fallbackIcon, imageFileToIcon, renderIcon, shortMark, unicodeIcon } from "./icon-picker.js?v=icon-contrast-110";
import { isTemporalDossierObservation } from "./dossier-index.js";
import { auditPortableReport, buildPortableReportHtml, buildPortableReportManifest, reportExportFilename } from "./portable-report.js?v=queue-order-166";
import { normalizeSmellKey, smellIssueLabel, smellIssueLabels } from "./smell-labels.js?v=canonical-labels-170";
import { sentenceCaseLabel } from "./lexical-labels.js?v=canonical-labels-170";

const storageKey = "bookinator.library.v1";
const libraryViewKey = "bookinator.library-view.v1";
const introKey = "bookinator.intro.seen";
const currentBookKey = "bookinator.current-book.v1";
const analysisTabsKey = "bookinator.analysis-tabs.v1";
const workspaceGroupsKey = "bookinator.workspace-groups.v1";
const chapterFontScaleKey = "bookinator.chapter-font-scale.v1";
const sourceAnalysisKey = "bookinator.source-analysis.v1";
const smellSortKey = "bookinator.smell-sort.v1";
const pipelineCoverageKey = "bookinator.pipeline-coverage.v1";
const pipelinePageSizeKey = "bookinator.pipeline-page-size.v1";
// Keep destructive category resets isolated from customer-facing controls so a
// release build can turn them off without changing the analysis toolbars.
const developmentControlsEnabled = true;
const pipelinePageSizes = [5, 10, 25, 50, "all"];
const sourceAnalysisDefaults = {emotion: {enabled: true, threshold: 10, neutral: true}, tag: {enabled: true, threshold: 25}, comments: {mode: "all"}};
let sourceAnalysisPreferences = structuredClone(sourceAnalysisDefaults);
let smellSortMode = localStorage.getItem(smellSortKey) === "type" ? "type" : "position";
let pipelineCoverageMode = localStorage.getItem(pipelineCoverageKey) === "reviewed" ? "reviewed" : "analysis";
const savedPipelinePageSize = localStorage.getItem(pipelinePageSizeKey);
let pipelinePageSize = savedPipelinePageSize === "all" ? "all" : Number(savedPipelinePageSize);
if (!pipelinePageSizes.includes(pipelinePageSize)) pipelinePageSize = 10;
let pipelinePage = 1;
let rememberedAnalysisTabs = {};
let rememberedWorkspaceGroups = {};
let rememberedLibraryView = {query: "", filter: "all", sort: {key: "title", direction: "asc"}};
try {
  const saved = JSON.parse(localStorage.getItem(sourceAnalysisKey) || "{}");
  sourceAnalysisPreferences = {
    emotion: {...sourceAnalysisDefaults.emotion, ...(saved.emotion || {})},
    tag: {...sourceAnalysisDefaults.tag, ...(saved.tag || {})},
    comments: {...sourceAnalysisDefaults.comments, ...(saved.comments || {}), mode: saved.comments?.mode === "hidden" || saved.comments?.enabled === false ? "hidden" : "all"},
  };
} catch {}
try {
  rememberedAnalysisTabs = JSON.parse(localStorage.getItem(analysisTabsKey) || "{}") || {};
} catch {}
try {
  rememberedWorkspaceGroups = JSON.parse(localStorage.getItem(workspaceGroupsKey) || "{}") || {};
} catch {}
try {
  const saved = JSON.parse(localStorage.getItem(libraryViewKey) || "{}") || {};
  const sortKeys = ["selection", "title", "priority", "analysis", "ingested", "changed"];
  rememberedLibraryView = {
    query: typeof saved.query === "string" ? saved.query : "",
    filter: typeof saved.filter === "string" ? saved.filter : "all",
    sort: {
      key: sortKeys.includes(saved.sort?.key) ? saved.sort.key : "title",
      direction: saved.sort?.direction === "desc" ? "desc" : "asc",
    },
  };
} catch {}

function rememberedAnalysisTab(bookId) {
  const tab = rememberedAnalysisTabs[bookId];
  return workspaceTabs.some((candidate) => candidate.id === tab) ? tab : "summaries";
}

function rememberAnalysisTab(bookId, tab) {
  if (!bookId || !workspaceTabs.some((candidate) => candidate.id === tab)) return;
  rememberedAnalysisTabs[bookId] = tab;
  localStorage.setItem(analysisTabsKey, JSON.stringify(rememberedAnalysisTabs));
  const group = workspaceGroupForTab(tab);
  if (group) rememberWorkspaceGroupState(bookId, group, {lastTab: tab});
}

function workspaceGroupState(bookId, group) {
  return rememberedWorkspaceGroups[bookId]?.[group] || {};
}

function rememberWorkspaceGroupState(bookId, group, changes) {
  if (!bookId || !group) return;
  rememberedWorkspaceGroups[bookId] = {
    ...(rememberedWorkspaceGroups[bookId] || {}),
    [group]: {...workspaceGroupState(bookId, group), ...changes},
  };
  localStorage.setItem(workspaceGroupsKey, JSON.stringify(rememberedWorkspaceGroups));
}

function saveSourceAnalysisPreferences() {
  localStorage.setItem(sourceAnalysisKey, JSON.stringify(sourceAnalysisPreferences));
}

const state = {
  books: [],
  selection: new Set(),
  pipelineSelection: new Set(),
  rememberedSelection: [],
  sort: rememberedLibraryView.sort,
  draftIcon: null,
  draftManuscriptId: null,
  editingBookId: null,
  pipelineTimer: null,
  libraryTimer: null,
  priorityInteractionActive: false,
  suggestedAbbreviation: "",
  abbreviationTitle: "",
  workspaceRequestId: 0,
  workspacePipeline: null,
  pipelineSignature: "",
  globalPipeline: {enabled: false, running: false, waitingBooks: 0, completed: 0, total: 0, percent: 0},
  currentBookId: localStorage.getItem(currentBookKey) || "",
  pendingDiagnostic: null,
  reviewerAnnotations: new Map(),
  activeReviewChapter: null,
  pendingAnnotationSelection: null,
};
const chapterSourcePreviewCache = new Map();

const directory = document.querySelector("#book-directory");
const search = document.querySelector("#search");
const filter = document.querySelector("#status-filter");
const bookIntakeInput = document.querySelector("#book-intake-file");
search.value = rememberedLibraryView.query;
if ([...filter.options].some((option) => option.value === rememberedLibraryView.filter)) filter.value = rememberedLibraryView.filter;

function saveLibraryViewPreferences() {
  localStorage.setItem(libraryViewKey, JSON.stringify({
    query: search.value,
    filter: filter.value,
    sort: state.sort,
  }));
}

function escapeHtml(value) {
  const node = document.createElement("span");
  node.textContent = value;
  return node.innerHTML;
}

function formatBookDateParts(value) {
  if (!value) return {date: "Unknown", time: ""};
  const date = new Date(value);
  if (Number.isNaN(date.valueOf())) return {date: String(value), time: ""};
  const pad = (part) => String(part).padStart(2, "0");
  return {
    date: `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`,
    time: `${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`,
  };
}

function bookDateMarkup(value) {
  const parts = formatBookDateParts(value);
  return `<span class="date-stack"><strong>${escapeHtml(parts.date)}</strong>${parts.time ? `<small>${escapeHtml(parts.time)}</small>` : ""}</span>`;
}

function formatBookDate(value) {
  const parts = formatBookDateParts(value);
  return parts.time ? `${parts.date} ${parts.time}` : parts.date;
}

function filteredBooks() {
  const query = search.value.trim().toLowerCase();
  return state.books.filter((book) => {
    const matchesText = `${book.title} ${book.author}`.toLowerCase().includes(query);
    const matchesStatus = filter.value === "all" || book.status === filter.value;
    return matchesText && matchesStatus;
  });
}

function compareBookValues(left, right) {
  if (left == null && right == null) return 0;
  if (left == null) return 1;
  if (right == null) return -1;
  if (typeof left === "number" && typeof right === "number") return left - right;
  return String(left).localeCompare(String(right), undefined, {numeric: true, sensitivity: "base"});
}

function bookAnalysisProgress(book) {
  const progress = book.pipeline?.progress || {};
  const completed = Number(progress.completed || 0);
  const total = Number(progress.total || 0);
  return {completed, total, percent: total ? Math.round(completed / total * 100) : 0};
}

function bookLengthMetrics(book) {
  return {
    words: Number(book.wordCount || 0),
    chapters: Number(book.chapterCount || 0),
    bytes: Number(book.sourceSizeBytes || 0),
  };
}

function sortedBooks(books) {
  const direction = state.sort.direction === "desc" ? -1 : 1;
  if (state.sort.key === "selection") return [...books].sort((left, right) => direction * (Number(state.selection.has(left.id)) - Number(state.selection.has(right.id))));
  if (state.sort.key === "length") return [...books].sort((left, right) => {
    const leftWords = bookLengthMetrics(left).words;
    const rightWords = bookLengthMetrics(right).words;
    const leftKnown = Number.isFinite(leftWords) && leftWords > 0;
    const rightKnown = Number.isFinite(rightWords) && rightWords > 0;
    if (leftKnown !== rightKnown) return leftKnown ? -1 : 1;
    if (!leftKnown) return compareBookValues(left.title, right.title);
    return direction * (leftWords - rightWords || compareBookValues(left.title, right.title));
  });
  const value = {
    title: (book) => book.title,
    priority: (book) => ({high: 0, normal: 1, low: 2, shelved: 3}[book.priority || "normal"] ?? 1),
    analysis: (book) => {
      const progress = bookAnalysisProgress(book);
      return progress.total ? progress.completed / progress.total : -1;
    },
    ingested: (book) => book.ingestedAt,
    changed: (book) => book.pipeline?.updatedAt || book.updatedAt || book.createdAt,
  }[state.sort.key] || ((book) => book.title);
  return [...books].sort((left, right) => direction * compareBookValues(value(left), value(right)));
}

function selectionState(books) {
  const selectedCount = books.filter((book) => state.selection.has(book.id)).length;
  return {selectedCount, totalCount: books.length, checked: books.length > 0 && selectedCount === books.length, indeterminate: selectedCount > 0 && selectedCount < books.length};
}

function sortButton(key, label) {
  const active = state.sort.key === key;
  const arrow = active ? state.sort.direction === "asc" ? "↑" : "↓" : "";
  return `<button type="button" class="directory-sort" data-sort="${key}"${active ? ` data-direction="${state.sort.direction}" aria-sort="${state.sort.direction === "asc" ? "ascending" : "descending"}"` : ""}>${label}<span aria-hidden="true">${arrow}</span></button>`;
}

function updateSelectionAction() {
  const hasSelection = state.selection.size > 0;
  for (const id of ["delete-books", "export-books"]) document.querySelector(`#${id}`).disabled = !hasSelection;
}

function updateGlobalPipelineStatus() {
  const panel = document.querySelector("#library-pipeline-panel");
  const toggle = document.querySelector("#toggle-library-pipeline");
  if (!panel || !toggle) return;
  const pipeline = state.globalPipeline || {};
  const waitingCount = Number(pipeline.waitingBooks || 0);
  const running = Boolean(pipeline.running);
  const enabled = Boolean(pipeline.enabled);
  const currentRun = pipeline.currentRun || {};
  const completed = Number(currentRun.completed ?? pipeline.completed ?? 0);
  const total = Number(currentRun.total ?? pipeline.total ?? 0);
  const percent = total ? Math.round(completed / total * 100) : 0;
  const etaSeconds = Number(pipeline.etaSeconds || 0);
  const etaText = etaSeconds > 0 ? formatEta(etaSeconds) : waitingCount > 0 ? "Estimating from recent work…" : "No queued work remaining";
  const navigation = document.querySelector("#pipeline-nav");
  const navigationStatus = document.querySelector("#pipeline-nav-status");
  const navigationAlert = document.querySelector("#pipeline-nav-alert");
  const navigationToggle = document.querySelector("#navigation-toggle");
  const navigationToggleAlert = document.querySelector("#navigation-toggle-alert");
  const diagnosticCount = Number(pipeline.diagnosticCount || 0);
  navigation?.classList.toggle("running", running);
  navigation?.classList.toggle("urgent", !enabled && waitingCount > 0);
  navigationToggle?.classList.toggle("running", running);
  navigationToggle?.classList.toggle("urgent", !enabled && waitingCount > 0);
  if (navigationAlert) {
    navigationAlert.hidden = diagnosticCount === 0;
    navigationAlert.textContent = String(diagnosticCount);
    navigationAlert.setAttribute("aria-label", `${diagnosticCount} analysis ${diagnosticCount === 1 ? "problem" : "problems"}`);
  }
  if (navigationToggleAlert) {
    navigationToggleAlert.hidden = diagnosticCount === 0;
    navigationToggleAlert.textContent = String(diagnosticCount);
  }
  if (navigationStatus) navigationStatus.textContent = running && etaSeconds > 0
    ? formatCompactEta(etaSeconds)
    : running
      ? `${waitingCount || 1} ${waitingCount === 1 ? "book" : "books"} processing`
    : waitingCount
      ? `${waitingCount} ${waitingCount === 1 ? "book" : "books"} waiting`
      : "Queue current";
  panel.classList.toggle("running", running);
  panel.classList.toggle("urgent", !enabled && waitingCount > 0);
  const runBooks = Number(currentRun.bookCount || 0);
  const addedUnits = Number(currentRun.addedUnits || 0);
  const deferredUnits = Number(currentRun.deferredUnits || 0);
  const started = currentRun.startedAt ? new Date(currentRun.startedAt).toLocaleString() : "now";
  const runFacts = [
    `${runBooks} ${runBooks === 1 ? "book" : "books"} · started ${started}`,
    addedUnits ? `${addedUnits.toLocaleString()} ${addedUnits === 1 ? "step" : "steps"} added after the run began` : "The starting scope is preserved",
    deferredUnits ? `${deferredUnits.toLocaleString()} deferred by shelving` : "",
  ].filter(Boolean).join(" · ");
  document.querySelector("#library-pipeline-progress").innerHTML = progressPanel({
    label: "Current run",
    completed,
    total,
    unit: "steps",
    percent,
    statusCopy: etaText,
    basisCopy: runFacts,
    activity: resolvedActivity(),
    fallbackActivity: "Bookinator is checking the global queue",
    className: "library-overall-progress",
  });
  toggle.hidden = !enabled && waitingCount === 0;
  toggle.classList.toggle("danger", enabled);
  toggle.setAttribute("aria-pressed", String(enabled));
  toggle.title = enabled ? "Stop after the current local model response" : "Start the global analysis queue";
  toggle.querySelector("small").textContent = enabled ? "Stop" : "Start";
  toggle.querySelector("svg").innerHTML = enabled ? '<rect x="6" y="6" width="12" height="12" rx="1"/>' : '<path d="m8 5 11 7-11 7Z"/>';
  const coverage = pipeline.libraryCoverage || {};
  const coverageTotal = Number(coverage.totalBooks || 0);
  const coverageComplete = pipelineCoverageMode === "reviewed" ? Number(coverage.reviewedComplete || 0) : Number(coverage.analysisComplete || 0);
  const coverageLabel = pipelineCoverageMode === "reviewed" ? "analyzed and signed off" : "finished Bookinator analysis";
  const coverageValue = document.querySelector("#library-coverage-value");
  if (coverageValue) coverageValue.textContent = `${coverageComplete.toLocaleString()} of ${coverageTotal.toLocaleString()} books ${coverageLabel}`;
  const coverageDetail = document.querySelector("#library-coverage-detail");
  if (coverageDetail) coverageDetail.textContent = pipelineCoverageMode === "reviewed"
    ? "Counts only books whose machine work is complete and whose reviewer has signed off."
    : "Counts machine analysis only; reviewer sign-off is not required.";
  const analysisCount = document.querySelector("#analysis-coverage-count");
  const reviewedCount = document.querySelector("#reviewed-coverage-count");
  if (analysisCount) analysisCount.textContent = String(Number(coverage.analysisComplete || 0));
  if (reviewedCount) reviewedCount.textContent = String(Number(coverage.reviewedComplete || 0));
  document.querySelectorAll("[data-coverage-mode]").forEach((button) => button.setAttribute("aria-pressed", String(button.dataset.coverageMode === pipelineCoverageMode)));
  updateLocalQueueStatus();
}

function queuedBooks() {
  return state.books.filter((book) => book.pipeline?.workRemaining && ((book.priority || "normal") !== "shelved" || book.pipeline?.nextAction === "prepare"));
}

function bookOwnsActiveWorker(book) {
  const activity = state.globalPipeline?.activity || {};
  if (activity.state !== "running") return false;
  if (activity.bookId) return activity.bookId === book.id;
  // Compatibility with servers that predate activity book IDs.
  return Boolean(activity.book && activity.book === book.title);
}

function pipelineBookStatus(book) {
  const globalActivity = state.globalPipeline?.activity || {};
  if (bookOwnsActiveWorker(book) && globalActivity.text) return {
    label: globalActivity.state === "running" ? "Working now" : "Up next",
    detail: globalActivity.text,
  };
  const phase = String(book.pipeline?.phase || "queued").replaceAll("-", " ");
  return {label: "Waiting", detail: phase === "queued" ? "Ready for its next chapter-step" : phase};
}

async function saveBookPriority(book, nextPriority) {
  const response = await fetch("/api/books", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({...book, priority: nextPriority})});
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.error || "Could not change queue priority.");
  state.books = state.books.map((item) => item.id === payload.book.id ? payload.book : item);
  return payload.book;
}

const pipelineTaskDefinitions = [
  {action: "summarize", stageId: "summaries", label: "Chapter summaries"},
  {action: "whole-summary", resultKey: "wholeBookSummary", label: "Whole-book summary"},
  {action: "dossiers", stageId: "dossiers", label: "Chapter dossiers"},
  {action: "whole-dossier", resultKey: "wholeBookDossier", label: "Whole-book dossier"},
  {action: "questions", resultKey: "questionTracker", label: "Questions & payoffs"},
  {action: "cumulative-context", stageId: "cumulative-context", label: "Cumulative context", optional: true},
  {action: "llm-review", stageId: "llm-review", label: "LLM Review", optional: true},
  {action: "whole-llm-review", stageId: "whole-book-llm-review", resultKey: "wholeBookLlmReview", label: "Whole-book LLM Review", optional: true},
  {action: "emotions", stageId: "emotions", label: "Chapter emotions"},
  {action: "tags", stageId: "tags", label: "Chapter tags"},
  {action: "smells", stageId: "smells", label: "Smells"},
];

function pipelineTasks() {
  const activity = state.globalPipeline?.activity || {};
  const activityAction = ({preparing: "prepare", summarizing: "summarize"})[activity.phase] || activity.phase || "";
  const serverQueue = new Map((state.globalPipeline?.queue || []).map((item) => [item.bookId,
    activity.state === "running" && activity.bookId === item.bookId && pipelineTaskDefinitions.some((definition) => definition.action === activityAction)
      ? {...item, action: activityAction, task: activity.task || item.task}
      : item
  ]));
  const tasks = [];
  state.books.forEach((book) => {
    const pipeline = book.pipeline || {};
    const queued = serverQueue.get(book.id);
    const priority = book.priority || "normal";
    const pausedActions = new Set(pipeline.pausedActions || []);
    if (priority === "shelved" && pipeline.nextAction !== "prepare") return;
    if (pipeline.nextAction === "prepare") {
      tasks.push({id: `${book.id}::prepare`, book, action: "prepare", label: "Manuscript inventory", detail: "Extract text, measure the manuscript, and propose its chapter map.", state: queued?.state === "running" ? "running" : "ready", required: true, bookRank: queued?.rank || 0, order: -1});
      return;
    }
    // Reviewer sign-off belongs to the book's completion meter, not the
    // machine queue. A book with no scheduler action and no explicit queue
    // ownership has no work to display here, even if an older server omitted
    // compact rollup records from the library response.
    if (!pipeline.nextAction && !queued && !pausedActions.size) return;
    const stages = new Map((pipeline.stages || []).map((stage) => [stage.id, stage]));
    pipelineTaskDefinitions.forEach((definition, order) => {
      const stage = stages.get(definition.stageId);
      if (definition.optional && !stage) return;
      const result = definition.resultKey ? pipeline[definition.resultKey] : null;
      const record = result && typeof result === "object" ? result : stage;
      const status = String(record?.status || (definition.resultKey ? "pending" : ""));
      if (!record || record.disabled || ["complete", "failed", "warning"].includes(status)) return;
      const paused = pausedActions.has(definition.action);
      const ownsWorker = queued?.state === "running" && (queued.action === definition.action || String(queued.task || "").toLocaleLowerCase() === definition.label.toLocaleLowerCase());
      const running = !paused && ownsWorker;
      const pausing = paused && ownsWorker;
      const ready = running || pipeline.nextAction === definition.action;
      tasks.push({
        id: `${book.id}::${definition.action}`, book, action: definition.action, label: definition.label,
        detail: String(record.detail || (ready ? "Ready for the local worker." : "Waiting for prerequisite work.")),
        state: pausing ? "pausing" : paused ? "paused" : running ? "running" : ready ? "ready" : "waiting", required: false,
        bookRank: queued?.rank || 9999, order,
      });
    });
    if (queued?.action && !tasks.some((task) => task.book.id === book.id && task.action === queued.action)) {
      const definition = pipelineTaskDefinitions.find((item) => item.action === queued.action);
      const label = definition?.label || String(queued.task || queued.action).replaceAll("-", " ").replace(/^./, (letter) => letter.toUpperCase());
      tasks.push({
        id: `${book.id}::${queued.action}`, book, action: queued.action, label,
        detail: queued.state === "running" ? "The local worker owns this job." : "Ready for the local worker.",
        state: queued.state === "running" ? "running" : "ready", required: false,
        bookRank: queued.rank || 9999, order: definition ? pipelineTaskDefinitions.indexOf(definition) : pipelineTaskDefinitions.length,
      });
    }
  });
  const priorityOrder = {high: 0, normal: 1, low: 2, shelved: 3};
  const stateOrder = {running: 0, pausing: 1, ready: 2, waiting: 3, paused: 4};
  tasks.sort((left, right) => stateOrder[left.state] - stateOrder[right.state]
    || (left.action === "prepare" ? -1 : right.action === "prepare" ? 1 : 0)
    || priorityOrder[left.book.priority || "normal"] - priorityOrder[right.book.priority || "normal"]
    || left.bookRank - right.bookRank || left.order - right.order
    || left.book.title.localeCompare(right.book.title));
  return tasks.map((task, index) => ({...task, rank: index + 1}));
}

function updatePipelineSelectionActions(tasks) {
  const selected = tasks.filter((task) => state.pipelineSelection.has(task.id));
  const label = document.querySelector("#pipeline-selection-count");
  if (label) label.textContent = `${selected.length} selected`;
  document.querySelectorAll("[data-pipeline-selection-action]").forEach((button) => {
    const action = button.dataset.pipelineSelectionAction;
    button.disabled = !selected.length
      || (action === "top" && !selected.some((task) => task.state === "ready" && !task.required))
      || (action === "pause" && !selected.some((task) => !["paused", "pausing"].includes(task.state) && !task.required))
      || (action === "resume" && !selected.some((task) => ["paused", "pausing"].includes(task.state)));
  });
}

function renderPipelineQueue() {
  const list = document.querySelector("#pipeline-book-list");
  const summary = document.querySelector("#pipeline-queue-summary");
  const footer = document.querySelector("#pipeline-queue-footer");
  if (!list || !summary) return;
  const tasks = pipelineTasks();
  const visibleIds = new Set(tasks.map((task) => task.id));
  for (const id of state.pipelineSelection) if (!visibleIds.has(id)) state.pipelineSelection.delete(id);
  summary.textContent = tasks.length
    ? `${tasks.length} remaining ${tasks.length === 1 ? "job" : "jobs"}. Ready work leads; dependent work stays visible behind it.`
    : "No analysis jobs are waiting.";
  updatePipelineSelectionActions(tasks);
  if (!tasks.length) {
    list.innerHTML = '<div class="pipeline-empty"><strong>The queue is clear.</strong><span>New manuscripts appear briefly for inventory; unshelved books remain for analysis.</span></div>';
    if (footer) footer.hidden = true;
    return;
  }
  const pageLimit = pipelinePageSize === "all" ? Math.max(tasks.length, 1) : pipelinePageSize;
  const pageCount = Math.ceil(tasks.length / pageLimit);
  pipelinePage = Math.max(1, Math.min(pipelinePage, pageCount));
  const pageStart = (pipelinePage - 1) * pageLimit;
  const pageTasks = tasks.slice(pageStart, pageStart + pageLimit);
  const allSelected = pageTasks.every((task) => state.pipelineSelection.has(task.id));
  const someSelected = pageTasks.some((task) => state.pipelineSelection.has(task.id));
  list.innerHTML = `<div class="pipeline-task-heading"><label><input type="checkbox" data-select-all-pipeline-tasks${allSelected ? " checked" : ""}><span class="sr-only">Select all pipeline jobs on this page</span></label><span>#</span><span>Book</span><span>Job</span><span>Status</span></div>${pageTasks.map((task) => {
    const running = task.state === "running";
    const statusLabel = running ? "Running" : task.state === "pausing" ? "Pausing" : task.state === "ready" ? "Ready" : task.state === "paused" ? "Paused" : "Waiting";
    return `<article class="pipeline-book-row pipeline-task-row ${escapeHtml(task.state)}">
      <label class="pipeline-task-selector"><input type="checkbox" data-select-pipeline-task="${escapeHtml(task.id)}"${state.pipelineSelection.has(task.id) ? " checked" : ""}><span class="sr-only">Select ${escapeHtml(task.label)} for ${escapeHtml(task.book.title)}</span></label>
      <span class="pipeline-queue-rank" aria-label="Queue position ${task.rank}">${task.rank}</span>
      <div class="pipeline-book-identity"><span class="book-cover${running ? " is-running" : ""}" data-pipeline-task-icon="${escapeHtml(task.id)}" aria-hidden="true"></span><div><strong>${escapeHtml(task.book.title)}</strong><small>${escapeHtml(task.book.author || "Author not specified")} · ${escapeHtml((task.book.priority || "normal").replace(/^./, (letter) => letter.toUpperCase()))}</small></div></div>
      <span class="pipeline-book-status"><strong>${escapeHtml(task.label)}</strong><small>${escapeHtml(task.detail)}</small></span>
      <span class="pipeline-task-state ${escapeHtml(task.state)}"><i aria-hidden="true"></i><strong>${statusLabel}</strong>${task.required ? "<small>Required intake</small>" : ""}</span>
    </article>`;
  }).join("")}`;
  if (footer) footer.hidden = false;
  const sizeMenu = document.querySelector("#pipeline-page-size");
  if (sizeMenu) sizeMenu.value = String(pipelinePageSize);
  const range = document.querySelector("#pipeline-page-range");
  if (range) range.textContent = `${pageStart + 1}–${pageStart + pageTasks.length} of ${tasks.length}`;
  const previous = document.querySelector("#pipeline-page-previous");
  const next = document.querySelector("#pipeline-page-next");
  if (previous) previous.disabled = pipelinePage === 1;
  if (next) next.disabled = pipelinePage === pageCount;
  const selectAll = list.querySelector("[data-select-all-pipeline-tasks]");
  selectAll.indeterminate = someSelected && !allSelected;
  selectAll.addEventListener("change", () => {
    if (selectAll.checked) pageTasks.forEach((task) => state.pipelineSelection.add(task.id));
    else pageTasks.forEach((task) => state.pipelineSelection.delete(task.id));
    renderPipelineQueue();
  });
  pageTasks.forEach((task) => renderIcon(list.querySelector(`[data-pipeline-task-icon="${CSS.escape(task.id)}"]`), task.book.icon, task.book.title, task.book.author));
  list.querySelectorAll("[data-select-pipeline-task]").forEach((checkbox) => checkbox.addEventListener("change", () => {
    checkbox.checked ? state.pipelineSelection.add(checkbox.dataset.selectPipelineTask) : state.pipelineSelection.delete(checkbox.dataset.selectPipelineTask);
    renderPipelineQueue();
  }));
}

function diagnosticTab(stage) {
  return ({summaries: "summaries", dossiers: "dossiers", emotions: "emotions", tags: "tags", smells: "smells"})[stage] || "pipeline";
}

function renderPipelineDiagnostics() {
  const section = document.querySelector(".pipeline-diagnostics-section");
  const list = document.querySelector("#pipeline-diagnostics-list");
  const summary = document.querySelector("#pipeline-diagnostics-summary");
  if (!section || !list || !summary) return;
  const diagnostics = Array.isArray(state.globalPipeline?.diagnostics) ? state.globalPipeline.diagnostics : [];
  const attention = document.querySelector("#pipeline-attention-button");
  const attentionCount = document.querySelector("#pipeline-attention-count");
  if (attention) attention.hidden = diagnostics.length === 0;
  if (attentionCount) attentionCount.textContent = `${diagnostics.length} ${diagnostics.length === 1 ? "problem" : "problems"}`;
  section.classList.toggle("has-errors", diagnostics.length > 0);
  summary.textContent = diagnostics.length
    ? `${diagnostics.length} current ${diagnostics.length === 1 ? "problem" : "problems"} across the library.`
    : "No current model or pipeline failures across the library.";
  if (!diagnostics.length) {
    list.innerHTML = '<div class="pipeline-empty"><strong>No analysis problems.</strong><span>Model and pipeline failures from every book will appear here.</span></div>';
    return;
  }
  list.innerHTML = diagnostics.map((diagnostic) => `<article class="pipeline-diagnostic-row">
    <span class="pipeline-diagnostic-identity"><strong>${escapeHtml(diagnostic.book || "Untitled")}</strong><small>${escapeHtml(diagnostic.item || diagnostic.stage || "Analysis")}${diagnostic.model ? ` · ${escapeHtml(diagnostic.model)}` : ""}</small></span>
    <span class="pipeline-diagnostic-message"><strong>${escapeHtml(String(diagnostic.status || "failed").replace(/^./, (letter) => letter.toUpperCase()))}</strong><small>${escapeHtml(diagnostic.error || "This analysis step needs attention.")}</small></span>
    <button class="pipeline-diagnostic-open" type="button" data-open-diagnostic-book="${escapeHtml(diagnostic.bookId || "")}" data-diagnostic-stage="${escapeHtml(diagnostic.stage || "pipeline")}" data-diagnostic-kind="${escapeHtml(diagnostic.resultKind || "stage")}" data-diagnostic-id="${escapeHtml(diagnostic.resultId ?? "")}">Inspect</button>
  </article>`).join("");
  list.querySelectorAll("[data-open-diagnostic-book]").forEach((button) => button.addEventListener("click", () => {
    if (!button.dataset.openDiagnosticBook) return;
    const tab = diagnosticTab(button.dataset.diagnosticStage);
    state.pendingDiagnostic = {bookId: button.dataset.openDiagnosticBook, tab, kind: button.dataset.diagnosticKind, id: button.dataset.diagnosticId};
    const target = `book/${button.dataset.openDiagnosticBook}/${tab}`;
    if (location.hash.replace(/^#/, "") === target) showBookPage(button.dataset.openDiagnosticBook, tab);
    else location.hash = target;
  }));
}

function openPendingDiagnostic(bookId, activeTab, body) {
  const target = state.pendingDiagnostic;
  if (!target || target.bookId !== bookId || target.tab !== activeTab) return;
  let inspectButton = null;
  if (target.kind === "stage") {
    const stage = [...body.querySelectorAll("[data-pipeline-stage]")].find((row) => row.dataset.pipelineStage === target.id);
    inspectButton = stage?.querySelector("[data-show-stage-details]");
  } else {
    const row = [...body.querySelectorAll("details.analysis-row")].find((candidate) => candidate.dataset.refreshKind === target.kind && candidate.dataset.refreshId === target.id);
    if (row) {
      row.open = true;
      row.scrollIntoView({block: "center"});
      inspectButton = row.querySelector("[data-show-reading-details]");
    }
  }
  state.pendingDiagnostic = null;
  inspectButton?.click();
}

function updateLocalQueueStatus() {
  const pipeline = state.globalPipeline || {};
  const running = Boolean(pipeline.running);
  const waiting = Number(pipeline.waitingBooks || 0);
  const panelStatus = document.querySelector("#models-queue-status");
  const activity = resolvedActivity();
  if (panelStatus) {
    panelStatus.classList.toggle("running", running);
    panelStatus.querySelector("span").textContent = running
      ? String(activity?.text || "Bookinator is alive · local model work is in progress")
      : waiting
        ? `${waiting} ${waiting === 1 ? "book is" : "books are"} waiting for local model work.`
        : "The local model queue is quiet.";
  }
}

function updateAnalysisNavigation() {
  let current = state.books.find((book) => book.id === state.currentBookId);
  if (!current && state.books.length) {
    current = state.books[0];
    state.currentBookId = current.id;
    localStorage.setItem(currentBookKey, current.id);
  }
  document.querySelector("#current-analysis-book").textContent = current?.title || "No book selected";
  return current;
}

function render() {
  const books = sortedBooks(filteredBooks());
  const titleCounts = state.books.reduce((counts, book) => {
    const title = String(book.title || "").trim().toLocaleLowerCase();
    if (title) counts.set(title, (counts.get(title) || 0) + 1);
    return counts;
  }, new Map());
  const visibleIds = new Set(books.map((book) => book.id));
  for (const id of state.selection) if (!visibleIds.has(id)) state.selection.delete(id);
  state.rememberedSelection = state.rememberedSelection.filter((id) => visibleIds.has(id));
  document.querySelector("#library-count").textContent = `${state.books.length} ${state.books.length === 1 ? "book" : "books"} on this computer`;
  updateAnalysisNavigation();
  updateGlobalPipelineStatus();
  renderPipelineQueue();
  renderPipelineDiagnostics();
  updateSelectionAction();
  if (!state.books.length) {
    directory.innerHTML = `<div class="empty-library"><img src="/assets/bookinator.svg" alt=""><h2>The shelves are suspiciously tidy.</h2><p>Add a manuscript and Bookinator will begin building a durable record of its characters, facts, promises, and loose ends.</p><button class="add-book-well large" data-add-book><span>⇣</span><strong>Add your first book</strong><small>Open the manuscript well</small></button></div>`;
    installBookWell(directory.querySelector("[data-add-book]"));
    return;
  }
  if (!books.length) {
    directory.innerHTML = `<div class="empty-library"><h2>No books match that search.</h2><p>Try another title, author, or reading status.</p></div>`;
    return;
  }
  directory.innerHTML = `
    <div class="directory-heading"><span class="selection-header"><input type="checkbox" data-select-visible aria-label="Select all visible books"><button type="button" data-sort="selection" title="Sort selected books first" aria-label="Sort selected books first">${state.sort.key === "selection" ? state.sort.direction === "desc" ? "↓" : "↑" : "↕"}</button></span><span>${sortButton("title", "Book")}</span><span>${sortButton("priority", "Priority")}</span><span>${sortButton("length", "Length")}</span><span>${sortButton("analysis", "Analysis")}</span><span>${sortButton("ingested", "Ingested")}</span><span>${sortButton("changed", "Last change")}</span><span></span></div>
    ${books.map((book) => {
      const analysis = bookAnalysisProgress(book);
      const length = bookLengthMetrics(book);
      const analysisComplete = analysis.total > 0 && analysis.completed >= analysis.total;
      const running = bookOwnsActiveWorker(book);
      const duplicateTitle = (titleCounts.get(String(book.title || "").trim().toLocaleLowerCase()) || 0) > 1;
      const duplicateIdentity = duplicateTitle
        ? `<small class="duplicate-book-identity ${book.sourceAvailable ? "with-source" : "without-source"}">${book.sourceAvailable ? "Original source" : "No source"} · project ${escapeHtml(String(book.id).slice(0, 8))}</small>`
        : "";
      return `<article class="book-row${analysisComplete ? " analysis-complete" : ""}">
      <label class="book-selector"><input type="checkbox" data-select-book="${escapeHtml(book.id)}"${state.selection.has(book.id) ? " checked" : ""}><span class="sr-only">Select ${escapeHtml(book.title)}</span></label>
      <div class="book-identity"><button type="button" class="book-cover${running ? " is-running" : ""} book-cover-edit" data-book-icon="${escapeHtml(book.id)}" data-open-book="${escapeHtml(book.id)}" aria-label="Open ${escapeHtml(book.title)}" title="Open book"></button><div><button type="button" class="book-title-link" data-open-book="${escapeHtml(book.id)}">${escapeHtml(book.title)}</button><span>${escapeHtml(book.author || "Author not specified")}</span>${duplicateIdentity}</div></div>
      <label class="priority-control priority-${escapeHtml(book.priority || "normal")}"><span class="sr-only">Priority for ${escapeHtml(book.title)}</span><select data-book-priority="${escapeHtml(book.id)}"><option value="high"${book.priority === "high" ? " selected" : ""}>High</option><option value="normal"${!book.priority || book.priority === "normal" ? " selected" : ""}>Normal</option><option value="low"${book.priority === "low" ? " selected" : ""}>Low</option><option value="shelved"${book.priority === "shelved" ? " selected" : ""}>Shelved</option></select></label>
      <span class="length-cell"><strong>${length.words > 0 ? `${length.words.toLocaleString()} words` : "Measuring…"}</strong><small>${[length.chapters > 0 ? countedLabel(length.chapters, "chapter") : "", length.bytes > 0 ? formatByteSize(length.bytes) : ""].filter(Boolean).join(" · ") || "Size pending"}</small></span>
      <span class="pipeline-cell"><strong>${analysis.percent}%</strong><small>${analysis.total ? `${analysis.completed.toLocaleString()} of ${analysis.total.toLocaleString()} required steps` : "awaiting chapter map"}</small></span>
      <span class="date-cell">${bookDateMarkup(book.ingestedAt)}</span>
      <span class="date-cell">${bookDateMarkup(book.pipeline?.updatedAt || book.updatedAt || book.createdAt)}</span>
      <button class="row-action-icon-button" type="button" data-open-book="${escapeHtml(book.id)}" title="Open ${escapeHtml(book.title)}" aria-label="Open ${escapeHtml(book.title)}"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 16.5V20h3.5L18 9.5 14.5 6 4 16.5Z"/><path d="m13 7.5 3.5 3.5"/></svg></button>
    </article>`;
    }).join("")}`;
  books.forEach((book) => renderIcon(directory.querySelector(`[data-book-icon="${CSS.escape(book.id)}"]`), book.icon, book.title, book.author));
  const headerSelection = directory.querySelector("[data-select-visible]");
  const visibleSelection = selectionState(books);
  headerSelection.checked = visibleSelection.checked;
  headerSelection.indeterminate = visibleSelection.indeterminate;
  headerSelection.title = visibleSelection.indeterminate ? `Select all visible books (${visibleSelection.selectedCount} of ${visibleSelection.totalCount} selected)` : visibleSelection.checked ? "Clear visible selection" : "Select all visible books";
  headerSelection.addEventListener("change", () => {
    const before = selectionState(books);
    if (before.indeterminate) {
      state.rememberedSelection = books.filter((book) => state.selection.has(book.id)).map((book) => book.id);
      books.forEach((book) => state.selection.add(book.id));
    } else if (before.checked) books.forEach((book) => state.selection.delete(book.id));
    else if (state.rememberedSelection.length && state.rememberedSelection.length < books.length) state.rememberedSelection.forEach((id) => state.selection.add(id));
    else books.forEach((book) => state.selection.add(book.id));
    render();
  });
  directory.querySelectorAll("[data-select-book]").forEach((checkbox) => checkbox.addEventListener("change", () => {
    checkbox.checked ? state.selection.add(checkbox.dataset.selectBook) : state.selection.delete(checkbox.dataset.selectBook);
    const selectedVisible = books.filter((book) => state.selection.has(book.id)).map((book) => book.id);
    if (selectedVisible.length && selectedVisible.length < books.length) state.rememberedSelection = selectedVisible;
    render();
  }));
  directory.querySelectorAll("[data-book-priority]").forEach((select) => {
    const beginInteraction = () => { state.priorityInteractionActive = true; };
    select.addEventListener("pointerdown", beginInteraction);
    select.addEventListener("focus", beginInteraction);
    select.addEventListener("blur", () => {
      if (select.dataset.saving === "true") return;
      state.priorityInteractionActive = false;
      render();
    });
    select.addEventListener("change", async () => {
      const book = state.books.find((item) => item.id === select.dataset.bookPriority);
      if (!book) return;
      const previousPriority = book.priority || "normal";
      const nextPriority = select.value;
      let cancelCurrentTask = false;
      if (nextPriority === "shelved" && previousPriority !== "shelved" && bookOwnsActiveWorker(book)) {
        const choice = await confirmAction({
          context: "Shelve a running book",
          title: `How should Bookinator stop ${book.title}?`,
          message: "Shelving prevents another task from starting. You can preserve the task already in progress, or cancel it now and retry it if you resume this book later.",
          acceptLabel: "Cancel task & shelve",
          secondaryLabel: "Finish task & shelve",
          cancelLabel: "Keep running",
          danger: true,
        });
        if (!choice) {
          select.value = previousPriority;
          state.priorityInteractionActive = false;
          render();
          return;
        }
        cancelCurrentTask = choice === "secondary" ? false : true;
      }
      book.priority = nextPriority;
      select.dataset.saving = "true";
      select.disabled = true;
      select.closest(".priority-control").className = `priority-control priority-${nextPriority}`;
      try {
        await saveBookPriority(book, nextPriority);
        if (cancelCurrentTask) {
          const response = await fetch(`/api/books/${encodeURIComponent(book.id)}/pipeline/stop`, {method: "POST"});
          const payload = await response.json();
          if (!response.ok && response.status !== 409) {
            await confirmAction({context: "Book shelved", title: "The active task could not be canceled", message: payload.error || "This book is shelved, but its current task may still finish.", acceptLabel: "Close"});
          }
        }
      } catch (error) {
        book.priority = previousPriority;
        await confirmAction({context: "Priority not changed", title: "Bookinator could not update the queue", message: error.message, acceptLabel: "Close"});
      } finally {
        state.priorityInteractionActive = false;
        render();
      }
    });
  });
  directory.querySelectorAll("[data-sort]").forEach((button) => button.addEventListener("click", () => {
    const key = button.dataset.sort;
    state.sort = {key, direction: state.sort.key === key && state.sort.direction === "asc" ? "desc" : key === "selection" ? "desc" : "asc"};
    saveLibraryViewPreferences();
    render();
  }));
}

function showDialog(id) {
  const dialog = document.querySelector(`#${id}`);
  dialog.hidden = false;
  dialog.querySelector("button, input")?.focus();
}

function closeDialog(id) {
  const dialog = document.querySelector(`#${id}`);
  if (!dialog) return;
  if (dialog.dataset.ephemeralDialog === "true") dialog.remove();
  else dialog.hidden = true;
}

function mountStandardDialog({id, className = "", labelledBy, content}) {
  document.querySelector(`#${id}`)?.remove();
  const backdrop = document.createElement("div");
  backdrop.id = id;
  backdrop.className = "backdrop";
  backdrop.dataset.ephemeralDialog = "true";
  backdrop.innerHTML = `<section class="standard-dialog ${className}" role="dialog" aria-modal="true" aria-labelledby="${escapeHtml(labelledBy)}"><button class="dialog-close" type="button" aria-label="Close">×</button>${content}</section>`;
  document.body.appendChild(backdrop);
  const dialog = backdrop.querySelector('[role="dialog"]');
  installMovableDialog(dialog);
  backdrop.querySelector(".dialog-close").addEventListener("click", () => closeDialog(id));
  backdrop.addEventListener("click", (event) => { if (event.target === backdrop) closeDialog(id); });
  dialog.querySelector("button, input")?.focus();
  return backdrop;
}

function showInformationDialog({id = "information-dialog", context = "Information", title, message}) {
  const titleId = `${id}-title`;
  return mountStandardDialog({
    id,
    className: "information-dialog",
    labelledBy: titleId,
    content: `<header class="dialog-heading"><div><p class="context">${escapeHtml(context)}</p><h2 id="${titleId}">${escapeHtml(title)}</h2></div></header><p class="information-dialog-message">${escapeHtml(message)}</p>`,
  });
}

function installDefaultDialogAction(backdrop, action) {
  const onKeydown = (event) => {
    if (event.key !== "Enter" || event.isComposing || event.target.closest("textarea, [contenteditable=true]")) return;
    event.preventDefault();
    event.stopPropagation();
    action();
  };
  backdrop.addEventListener("keydown", onKeydown);
  return () => backdrop.removeEventListener("keydown", onKeydown);
}

function confirmAction({context = "Confirm action", title, message, acceptLabel = "Continue", secondaryLabel = "", cancelLabel = "Cancel", danger = false}) {
  const backdrop = document.querySelector("#confirmation-dialog");
  backdrop.querySelector("#confirmation-input-wrap").hidden = true;
  backdrop.querySelector("#confirmation-context").textContent = context;
  backdrop.querySelector("#confirmation-title").textContent = title;
  backdrop.querySelector("#confirmation-message").textContent = message;
  const accept = backdrop.querySelector("#confirmation-accept");
  const secondary = backdrop.querySelector("#confirmation-secondary");
  const cancelButtons = [...backdrop.querySelectorAll("[data-confirm-cancel]")];
  const cancelButton = cancelButtons.find((button) => !button.classList.contains("dialog-close"));
  accept.textContent = acceptLabel;
  secondary.textContent = secondaryLabel;
  secondary.hidden = !secondaryLabel;
  if (cancelButton) cancelButton.textContent = cancelLabel;
  accept.disabled = false;
  accept.classList.toggle("danger-action", danger);
  showDialog("confirmation-dialog");
  accept.focus();
  return new Promise((resolve) => {
    let removeDefaultAction = () => {};
    const finish = (answer) => {
      backdrop.hidden = true;
      removeDefaultAction();
      accept.removeEventListener("click", approve);
      secondary.removeEventListener("click", chooseSecondary);
      cancelButtons.forEach((button) => button.removeEventListener("click", cancel));
      secondary.hidden = true;
      if (cancelButton) cancelButton.textContent = "Cancel";
      resolve(answer);
    };
    const approve = () => finish(true);
    const chooseSecondary = () => finish("secondary");
    const cancel = () => finish(false);
    removeDefaultAction = installDefaultDialogAction(backdrop, approve);
    accept.addEventListener("click", approve);
    secondary.addEventListener("click", chooseSecondary);
    cancelButtons.forEach((button) => button.addEventListener("click", cancel));
  });
}

function promptForText({context, title, message, label, value = "", acceptLabel = "Import book", validate}) {
  const backdrop = document.querySelector("#confirmation-dialog");
  const wrap = backdrop.querySelector("#confirmation-input-wrap");
  const input = backdrop.querySelector("#confirmation-input");
  const help = backdrop.querySelector("#confirmation-input-help");
  const accept = backdrop.querySelector("#confirmation-accept");
  backdrop.querySelector("#confirmation-secondary").hidden = true;
  const cancelButton = [...backdrop.querySelectorAll("[data-confirm-cancel]")].find((button) => !button.classList.contains("dialog-close"));
  if (cancelButton) cancelButton.textContent = "Cancel";
  backdrop.querySelector("#confirmation-context").textContent = context;
  backdrop.querySelector("#confirmation-title").textContent = title;
  backdrop.querySelector("#confirmation-message").textContent = message;
  backdrop.querySelector("#confirmation-input-label").textContent = label;
  wrap.hidden = false;
  input.value = value;
  accept.textContent = acceptLabel;
  accept.classList.remove("danger-action");
  const refresh = () => {
    const problem = validate?.(input.value.trim()) || "";
    help.textContent = problem;
    accept.disabled = Boolean(problem);
  };
  refresh();
  showDialog("confirmation-dialog");
  input.focus();
  input.select();
  return new Promise((resolve) => {
    let removeDefaultAction = () => {};
    const finish = (answer) => {
      backdrop.hidden = true;
      wrap.hidden = true;
      removeDefaultAction();
      input.removeEventListener("input", refresh);
      accept.removeEventListener("click", approve);
      backdrop.querySelectorAll("[data-confirm-cancel]").forEach((button) => button.removeEventListener("click", cancel));
      resolve(answer);
    };
    const approve = () => { if (!accept.disabled) finish(input.value.trim()); };
    const cancel = () => finish(null);
    removeDefaultAction = installDefaultDialogAction(backdrop, approve);
    input.addEventListener("input", refresh);
    accept.addEventListener("click", approve);
    backdrop.querySelectorAll("[data-confirm-cancel]").forEach((button) => button.addEventListener("click", cancel));
  });
}

function installMovableDialog(dialog) {
  if (!dialog || dialog.dataset.movableDialogInstalled === "true") return;
  dialog.dataset.movableDialogInstalled = "true";
  const handle = dialog.querySelector(".dialog-heading") || dialog;
  let drag = null;
  handle.addEventListener("pointerdown", (event) => {
    if (event.defaultPrevented || event.button !== 0 || event.target.closest("button, input, select, textarea, a, label, summary, [contenteditable], [data-no-dialog-drag]")) return;
    const rect = dialog.getBoundingClientRect();
    const styles = getComputedStyle(dialog);
    drag = {
      pointerId: event.pointerId,
      startX: event.clientX,
      startY: event.clientY,
      originX: Number.parseFloat(styles.getPropertyValue("--dialog-x")) || 0,
      originY: Number.parseFloat(styles.getPropertyValue("--dialog-y")) || 0,
      rect,
    };
    handle.setPointerCapture(event.pointerId);
    dialog.classList.add("is-dragging");
    event.preventDefault();
  });
  handle.addEventListener("pointermove", (event) => {
    if (!drag || event.pointerId !== drag.pointerId) return;
    const deltaX = event.clientX - drag.startX;
    const deltaY = event.clientY - drag.startY;
    const minX = drag.originX - drag.rect.left;
    const maxX = drag.originX + innerWidth - drag.rect.right;
    const minY = drag.originY - drag.rect.top;
    const maxY = drag.originY + innerHeight - drag.rect.bottom;
    dialog.style.setProperty("--dialog-x", `${Math.min(maxX, Math.max(minX, drag.originX + deltaX))}px`);
    dialog.style.setProperty("--dialog-y", `${Math.min(maxY, Math.max(minY, drag.originY + deltaY))}px`);
  });
  const finish = (event) => {
    if (!drag || event.pointerId !== drag.pointerId) return;
    drag = null;
    dialog.classList.remove("is-dragging");
  };
  handle.addEventListener("pointerup", finish);
  handle.addEventListener("pointercancel", finish);
}

function openAddDialog() {
  restoreBookFormToDialog();
  clearTimeout(identityAutosaveTimer);
  identityAutosaveTimer = 0;
  state.editingBookId = null;
  state.draftIcon = null;
  state.draftManuscriptId = null;
  state.suggestedAbbreviation = "";
  state.abbreviationTitle = "";
  document.querySelector("#book-form").reset();
  refreshLlmReviewSetting();
  manuscriptWell.hidden = false;
  document.querySelector("#manuscript-well-title").textContent = "Drop your manuscript into the well";
  document.querySelector("#manuscript-well-copy").textContent = "PDF, DOCX, EPUB, TXT, or Markdown";
  manuscriptWell.classList.remove("has-file");
  document.querySelector("#file-name").textContent = "";
  document.querySelector("#identity-status").hidden = true;
  document.querySelector("#book-identity-provenance").hidden = true;
  document.querySelector("#book-dialog-context").textContent = "New book";
  document.querySelector("#add-title").textContent = "Bring in a manuscript";
  document.querySelector("#book-dialog-description").textContent = "Drop in a PDF, ebook, or text manuscript. Bookinator will inspect its opening locally, suggest the title and author, and let you correct either before continuing.";
  document.querySelector("#save-book").textContent = "Add to library";
  setIdentitySaveState("", "All changes saved");
  refreshBookSaveState();
  resetBookMarkImageStatus();
  refreshDraftIcon();
  showDialog("add-dialog");
  document.querySelector("#manuscript-well").focus();
}

function restoreBookFormToDialog() {
  if (!bookFormDialog.contains(bookForm)) bookFormDialog.append(bookForm);
  bookForm.classList.remove("inline-book-form");
  document.querySelector("#shadow-heading-diagnostic").hidden = true;
  document.querySelector("#shadow-heading-results").hidden = true;
}

function renderShadowHeadingDiagnostic(result) {
  const results = document.querySelector("#shadow-heading-results");
  const issueCount = (result.chapterDiscrepancies || []).length;
  const previewByTerm = new Map((result.preview?.comparisons || []).map((item) => [item.term, item]));
  const rows = (result.comparisons || []).map((item) => {
    const preview = previewByTerm.get(item.term) || {};
    return `<tr>
    <th scope="row">${escapeHtml(item.term)}</th>
    <td>${Number(item.sourceCount || 0)}</td>
    <td>${Number(item.headingCount || 0)}</td>
    <td>${Number(preview.headingCount || 0)}</td>
    <td>${Number(item.attachedCount || 0) + Number(item.bareCount || 0)}</td>
    <td><span class="shadow-heading-verdict ${preview.ok ? "pass" : "fail"}">${preview.ok ? "Match" : "Check"}</span></td>
  </tr>`;
  }).join("");
  const groupedIssues = [...(result.attachedOccurrences || []), ...(result.bareOccurrences || [])];
  const issueMarkup = groupedIssues.length ? `<details><summary>${groupedIssues.length} malformed marker${groupedIssues.length === 1 ? "" : "s"}</summary><ol>${groupedIssues.map((item) => `<li><strong>${escapeHtml(item.term)}</strong> · Chapter ${Number(item.chapterSequence || 0)}, line ${Number(item.line || 0)}${item.excerpt ? `<blockquote>${escapeHtml(item.excerpt)}</blockquote>` : ""}</li>`).join("")}</ol></details>` : "";
  const chapterMarkup = (result.chapterDiscrepancies || []).length ? `<details><summary>${result.chapterDiscrepancies.length} chapter-level mismatch${result.chapterDiscrepancies.length === 1 ? "" : "es"}</summary><ol>${result.chapterDiscrepancies.map((item) => `<li><strong>${escapeHtml(item.term)} · Chapter ${Number(item.chapterSequence || 0)}</strong> — PDF ${Number(item.sourceCount || 0)}${item.sourcePages?.length ? ` (page${item.sourcePages.length === 1 ? "" : "s"} ${item.sourcePages.map(Number).join(", ")})` : ""}; headings ${Number(item.headingCount || 0)}${item.attachedCount || item.bareCount ? `; not headings ${Number(item.attachedCount || 0) + Number(item.bareCount || 0)}` : ""}</li>`).join("")}</ol></details>` : "";
  const excludedMarkup = (result.excludedSourceOccurrences || []).length ? `<p class="shadow-heading-excluded">Excluded ${(result.excludedSourceOccurrences || []).length} front-matter occurrence${result.excludedSourceOccurrences.length === 1 ? "" : "s"} from the source count.</p>` : "";
  const previewMarkup = result.preview ? `<section class="shadow-heading-preview ${result.preview.ok ? "pass" : "fail"}"><strong>${result.preview.ok ? "Dry-run reparse passes." : "The dry-run reparse still has heading mismatches."}</strong><span>${result.preview.ok ? "Using the current parser and approved boundaries would preserve every TIMMY / SHADOW heading. Nothing was written or queued." : "Inspect the dry-run counts before rebuilding or restarting analysis."}</span></section>` : "";
  results.className = `shadow-heading-results ${result.ok ? "pass" : "fail"}`;
  results.innerHTML = `${previewMarkup}<header><strong>${result.ok ? "The currently saved chapters agree with the source." : `${issueCount} chapter-level mismatch${issueCount === 1 ? "" : "es"} remain in the saved chapters.`}</strong><span>${escapeHtml(result.note || "")}</span></header>
    <table><thead><tr><th>Marker</th><th>Original PDF</th><th>Saved headings</th><th>Dry-run headings</th><th>Saved malformed</th><th>Dry-run result</th></tr></thead><tbody>${rows}</tbody></table>
    ${excludedMarkup}${chapterMarkup}${issueMarkup}`;
  results.hidden = false;
}

async function scanShadowHeadings() {
  const button = document.querySelector("#scan-shadow-headings");
  const results = document.querySelector("#shadow-heading-results");
  if (!state.editingBookId || button.disabled) return;
  button.disabled = true;
  button.classList.add("working");
  results.className = "shadow-heading-results loading";
  results.innerHTML = "<p>Scanning the preserved PDF and composed Markdown…</p>";
  results.hidden = false;
  try {
    await requireChapterMapApi("shadowHeadingDiagnostic", "Bookinator’s running server predates the Shadow heading check. Restart ./bin/serve, then try again.");
    const response = await fetch(`/api/books/${encodeURIComponent(state.editingBookId)}/debug/shadow-headings`, {cache: "no-store"});
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || "Could not scan the viewpoint headings.");
    renderShadowHeadingDiagnostic(result);
  } catch (error) {
    results.className = "shadow-heading-results fail";
    results.innerHTML = `<p><strong>Could not run the check.</strong> ${escapeHtml(error.message || String(error))}</p>`;
  } finally {
    button.disabled = false;
    button.classList.remove("working");
  }
}

function openExistingBook(bookId, {host = null} = {}) {
  const book = state.books.find((item) => item.id === bookId);
  if (!book) return;
  restoreBookFormToDialog();
  state.editingBookId = book.id;
  state.draftIcon = book.icon || null;
  state.draftManuscriptId = book.manuscriptId || null;
  state.suggestedAbbreviation = book.abbreviation || "";
  state.abbreviationTitle = book.title || "";
  document.querySelector("#book-form").reset();
  setBookPriority(book.priority || "normal");
  bookLlmReviewInput.checked = Boolean(book.llmReviewEnabled);
  refreshLlmReviewSetting();
  titleInput.value = book.title || "";
  document.querySelector("#book-author").value = book.author || "";
  const provenance = document.querySelector("#book-identity-provenance");
  provenance.hidden = false;
  document.querySelector("#book-ingested-label").textContent = book.importedAt ? "Imported" : "Ingested";
  document.querySelector("#book-ingested-at").textContent = formatBookDate(book.importedAt || book.ingestedAt || book.createdAt);
  const originalIngested = document.querySelector("#book-original-ingested-wrap");
  originalIngested.hidden = !book.originalIngestedAt;
  document.querySelector("#book-original-ingested-at").textContent = formatBookDate(book.originalIngestedAt);
  const sourceDocument = document.querySelector("#book-source-filename");
  sourceDocument.innerHTML = book.sourceAvailable
    ? `<a class="book-source-download" href="/api/books/${encodeURIComponent(book.id)}/source" download title="Download ${escapeHtml(book.sourceFilename || "source document")}"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3v12M7 10l5 5 5-5"/><path d="M5 20h14"/></svg><span><strong>Download source</strong><small>${escapeHtml(book.sourceFilename || "Source document")}</small></span></a>`
    : `<span class="book-source-unavailable">Not available</span>`;
  manuscriptWell.hidden = Boolean(book.manuscriptId);
  document.querySelector("#manuscript-well-title").textContent = "Reconnect this manuscript";
  document.querySelector("#manuscript-well-copy").textContent = "This book came from the early preview; drop its PDF here to enable reading pipelines.";
  const editStatus = document.querySelector("#identity-status");
  editStatus.hidden = Boolean(book.manuscriptId);
  if (!book.manuscriptId) {
    editStatus.className = "identity-status warning";
    editStatus.textContent = "The original preview saved this book’s details but not its PDF. Icon changes are safe; reconnect the PDF when you are ready to analyze it.";
  }
  document.querySelector("#book-dialog-context").textContent = "Book details";
  document.querySelector("#add-title").textContent = "Edit this book";
  document.querySelector("#book-dialog-description").textContent = "Change the title, author, or library icon. The manuscript and analysis remain attached to this book.";
  document.querySelector("#save-book").textContent = "Save changes";
  refreshBookSaveState();
  resetBookMarkImageStatus();
  refreshDraftIcon();
  if (host) {
    bookForm.classList.add("inline-book-form");
    host.append(bookForm);
    document.querySelector("#shadow-heading-diagnostic").hidden = false;
    document.querySelector("#shadow-heading-results").hidden = true;
    identitySavedRevision = identityChangeRevision;
    setIdentitySaveState("", "All changes saved");
    titleInput.focus({preventScroll: true});
    return;
  }
  showDialog("add-dialog");
  titleInput.focus();
}

function manuscriptFromDrop(event) {
  return [...event.dataTransfer.files].find((candidate) => /\.(pdf|docx|epub|txt|md)$/i.test(candidate.name));
}

function importTitleProblem(title, reservedTitles) {
  if (!title) return "Enter a title for the imported book.";
  if (reservedTitles.has(title.toLocaleLowerCase())) return "That title is already in this library. Choose a unique title.";
  return "";
}

function suggestedNewManuscriptTitle(title) {
  const reserved = new Set(state.books.map((book) => String(book.title || "").trim().toLocaleLowerCase()).filter(Boolean));
  const date = new Date().toISOString().slice(0, 10);
  const base = `${title || "Untitled"} (New import ${date})`;
  let candidate = base;
  let sequence = 2;
  while (reserved.has(candidate.toLocaleLowerCase())) candidate = `${base} ${sequence++}`;
  return candidate;
}

async function chooseImportTitles(collisions, initialOverrides = {}, copy = {}) {
  const overrides = {...initialOverrides};
  const reserved = new Set(state.books.map((book) => String(book.title || "").trim().toLocaleLowerCase()).filter(Boolean));
  Object.values(overrides).forEach((title) => reserved.add(String(title).trim().toLocaleLowerCase()));
  for (const collision of collisions) {
    const chosen = await promptForText({
      context: copy.context || "Name collision",
      title: `Another book is already named “${collision.title}”`,
      message: copy.message || "Bookinator will not create ambiguous library entries. Confirm the suggested import name or choose another unique title.",
      label: copy.label || "Title for this imported book",
      value: collision.suggestedTitle || `${collision.title} (Imported)`,
      validate: (value) => importTitleProblem(value, reserved),
    });
    if (chosen === null) return null;
    overrides[collision.importKey] = chosen;
    reserved.add(chosen.toLocaleLowerCase());
  }
  return overrides;
}

async function importCompleteBookinatorPackage(file, titleOverrides = {}) {
  const headers = {"Content-Type": "application/vnd.bookinator.project+zip"};
  if (Object.keys(titleOverrides).length) headers["X-Bookinator-Import-Titles"] = JSON.stringify(titleOverrides);
  const response = await fetch("/api/library/import-bundle", {method: "POST", headers, body: file});
  const result = await response.json().catch(() => ({}));
  if (response.status === 409 && result.code === "title-collision") {
    const resolved = await chooseImportTitles(result.collisions || [], titleOverrides);
    return resolved ? importCompleteBookinatorPackage(file, resolved) : null;
  }
  if (!response.ok) throw new Error(result.error || "The Bookinator package could not be imported.");
  return result;
}

async function prepareLegacyLibraryImport(legacy) {
  const importedAt = new Date().toISOString();
  const reserved = new Set(state.books.map((book) => String(book.title || "").trim().toLocaleLowerCase()).filter(Boolean));
  for (const [index, book] of (legacy.books || []).entries()) {
    if (!book || typeof book !== "object") continue;
    const originalTitle = String(book.title || "Untitled").trim() || "Untitled";
    if (reserved.has(originalTitle.toLocaleLowerCase())) {
      const date = importedAt.slice(0, 10);
      let suggested = `${originalTitle} (Imported ${date})`;
      let suffix = 2;
      while (reserved.has(suggested.toLocaleLowerCase())) suggested = `${originalTitle} (Imported ${date}) ${suffix++}`;
      const chosen = await promptForText({
        context: "Name collision",
        title: `Another book is already named “${originalTitle}”`,
        message: "This older export can restore saved analysis, but Bookinator still requires a unique library title.",
        label: "Title for this imported book",
        value: suggested,
        validate: (value) => importTitleProblem(value, reserved),
      });
      if (chosen === null) return null;
      book.title = chosen;
    }
    reserved.add(String(book.title || originalTitle).trim().toLocaleLowerCase());
    book.originalIngestedAt ||= book.ingestedAt || "";
    book.ingestedAt = importedAt;
    book.importedAt = importedAt;
    book.importKey ||= String(book.id || `book-${index + 1}`);
  }
  return legacy;
}

async function acceptBookFile(file) {
  if (!file) return;
  if (/\.bookinator$/i.test(file.name) || file.type === "application/vnd.bookinator.project+zip") {
    try {
      let result;
      const prefix = await file.slice(0, 64).text();
      if (prefix.trimStart().startsWith("{")) {
        let legacy = JSON.parse(await file.text());
        if (legacy.schema !== "bookinator-library-v1") throw new Error("This is not a recognized Bookinator project package.");
        legacy = await prepareLegacyLibraryImport(legacy);
        if (!legacy) return;
        result = await postLibraryAction("/api/library/import", legacy);
        result.legacy = true;
        result.warning = "This file came from the older library exporter. Its saved analysis was restored, but that format did not include the original source document, generated artifacts, or saved reports.";
      } else {
        result = await importCompleteBookinatorPackage(file);
        if (!result) return;
      }
      await refreshLibraryBooks();
      if (result.warning || result.collisions?.length) {
        const collisionDetails = (result.collisions || []).map((collision) => collision.message + (collision.importedAs !== collision.title ? ` It appears as “${collision.importedAs}”.` : "")).join(" ");
        const details = [result.warning, collisionDetails].filter(Boolean).join(" ");
        await confirmAction({context: result.legacy ? "Legacy import complete" : "Import complete", title: `${result.imported} ${result.imported === 1 ? "book" : "books"} imported`, message: details, acceptLabel: "Close"});
      }
    } catch (error) {
      await confirmAction({context: "Import failed", title: "Bookinator could not import that package", message: error.message || "Choose a complete .bookinator project export.", acceptLabel: "Close"});
    }
    return;
  }
  if (/\.json$/i.test(file.name) || file.type === "application/json") {
    try {
      await postLibraryAction("/api/library/import", JSON.parse(await file.text()));
      await refreshLibraryBooks();
    } catch (error) {
      await confirmAction({context: "Import failed", title: "Bookinator could not import that file", message: error.message || "Choose a Bookinator library JSON export.", acceptLabel: "Close"});
    }
    return;
  }
  if (/\.(pdf|docx|epub|txt|md)$/i.test(file.name)) {
    openAddDialog();
    await identifyManuscript(file);
    return;
  }
  await confirmAction({context: "File not added", title: "Bookinator does not recognize this format", message: "Choose an EPUB, PDF, DOCX, Markdown, text, or complete Bookinator project package.", acceptLabel: "Close"});
}

function installBookWell(well) {
  if (!well || well.dataset.bookWellInstalled === "true") return;
  well.dataset.bookWellInstalled = "true";
  well.addEventListener("click", () => bookIntakeInput.click());
  ["dragenter", "dragover"].forEach((type) => well.addEventListener(type, (event) => {
    event.preventDefault();
    event.dataTransfer.dropEffect = "copy";
    well.classList.add("dragging");
  }));
  ["dragleave", "drop"].forEach((type) => well.addEventListener(type, (event) => {
    event.preventDefault();
    well.classList.remove("dragging");
  }));
  well.addEventListener("drop", (event) => acceptBookFile([...event.dataTransfer.files][0]));
}

installBookWell(document.querySelector("#add-book"));
bookIntakeInput.addEventListener("change", async (event) => {
  await acceptBookFile(event.target.files[0]);
  event.target.value = "";
});
directory.addEventListener("click", (event) => {
  const editor = event.target.closest("[data-edit-book]");
  if (editor) {
    openExistingBook(editor.dataset.editBook);
    return;
  }
  const button = event.target.closest("[data-open-book]");
  if (button) location.hash = `book/${button.dataset.openBook}/${rememberedAnalysisTab(button.dataset.openBook)}`;
});
document.querySelector("#meet-bookinator").addEventListener("click", () => {
  localStorage.setItem(introKey, "true");
  closeDialog("welcome-dialog");
  openAddDialog();
});

document.querySelectorAll("[data-close]").forEach((button) => {
  button.addEventListener("click", () => closeDialog(button.dataset.close));
});

function beginPendingAnnotation() {
  const review = state.activeReviewChapter;
  const selection = state.pendingAnnotationSelection;
  if (!review || !selection) return;
  const scrollTop = document.querySelector("#chapter-source-body")?.scrollTop || 0;
  openAnnotationEditor({bookId: review.bookId, selection, afterSave: (annotation) => openChapterSource(review.bookId, review.sequence, {kind: "reviewer", annotationId: annotation.id, scrollTop}, review.analysisChapter)});
}
document.querySelector("#annotate-selection")?.addEventListener("click", beginPendingAnnotation);

document.querySelectorAll(".backdrop").forEach((backdrop) => {
  backdrop.addEventListener("click", (event) => {
    if (event.target !== backdrop || backdrop.id === "welcome-dialog") return;
    if (backdrop.id === "confirmation-dialog") backdrop.querySelector("[data-confirm-cancel]").click();
    else closeDialog(backdrop.id);
  });
});
document.querySelectorAll('.backdrop [role="dialog"]').forEach(installMovableDialog);
document.querySelectorAll("#reading-details-dialog [data-run-inspector-view]").forEach((button) => button.addEventListener("click", () => showRunInspectorView(button.dataset.runInspectorView)));
document.querySelector("#run-inspector-expand")?.addEventListener("click", (event) => {
  const dialog = document.querySelector("#reading-details-dialog .reading-details-dialog");
  const expanded = dialog.classList.toggle("is-expanded");
  dialog.style.removeProperty("--dialog-x");
  dialog.style.removeProperty("--dialog-y");
  event.currentTarget.setAttribute("aria-pressed", String(expanded));
  event.currentTarget.querySelector("strong").textContent = expanded ? "Restore" : "Expand";
  event.currentTarget.querySelector("span").textContent = expanded ? "↙" : "↗";
  event.currentTarget.title = expanded ? "Restore inspector size" : "Expand inspector";
});

document.addEventListener("keydown", (event) => {
  if (event.key !== "Escape") return;
  document.querySelectorAll(".backdrop:not([hidden])").forEach((dialog) => {
    if (dialog.id === "confirmation-dialog") dialog.querySelector("[data-confirm-cancel]").click();
    else if (dialog.id !== "welcome-dialog") closeDialog(dialog.id);
  });
});

const manuscriptWell = document.querySelector("#manuscript-well");
const manuscriptInput = document.querySelector("#book-file");
const titleInput = document.querySelector("#book-title");
const authorInput = document.querySelector("#book-author");
const bookPriorityInputs = [...document.querySelectorAll('input[name="book-priority"]')];
const bookLlmReviewInput = document.querySelector("#book-llm-review");
const llmReviewSettingCopy = document.querySelector("#llm-review-setting-copy");
const markPreview = document.querySelector("#book-mark-preview");
const markText = document.querySelector("#book-mark-text");
const imageMarkWell = document.querySelector("#image-mark-well");
const imageMarkInput = document.querySelector("#book-mark-image");
const imageMarkStatus = document.querySelector("#book-mark-image-status");
const addDialog = document.querySelector("#add-dialog");
const bookForm = document.querySelector("#book-form");
const bookFormDialog = bookForm.parentElement;
const markColor = document.querySelector("#book-mark-color");
const markOutline = document.querySelector("#book-mark-outline");
const saveBookButton = document.querySelector("#save-book");
const identitySaveState = document.querySelector("#identity-save-state");
document.querySelector("#scan-shadow-headings")?.addEventListener("click", scanShadowHeadings);
let identityAutosaveTimer = 0;
let identitySaveChain = Promise.resolve(true);
let identityChangeRevision = 0;
let identitySavedRevision = 0;
let identityQueuedRevision = 0;

function identityFormIsInline() {
  return bookForm.classList.contains("inline-book-form") && Boolean(state.editingBookId);
}

function setIdentitySaveState(kind, message) {
  identitySaveState.className = `identity-save-state${kind ? ` ${kind}` : ""}`;
  identitySaveState.textContent = message;
}

function scheduleIdentityAutosave() {
  if (!identityFormIsInline()) return;
  identityChangeRevision += 1;
  clearTimeout(identityAutosaveTimer);
  setIdentitySaveState("saving", "Saving changes…");
  identityAutosaveTimer = setTimeout(() => {
    identityAutosaveTimer = 0;
    queueIdentitySave(identityChangeRevision);
  }, 550);
}

function queueIdentitySave(revision = identityChangeRevision) {
  if (identityQueuedRevision >= revision) return identitySaveChain;
  identityQueuedRevision = revision;
  identitySaveChain = identitySaveChain.then(() => persistBookForm({embedded: true, revision}));
  return identitySaveChain;
}

async function flushIdentityAutosave() {
  if (!identityFormIsInline()) return true;
  if (identitySavedRevision >= identityChangeRevision) return true;
  clearTimeout(identityAutosaveTimer);
  identityAutosaveTimer = 0;
  return queueIdentitySave(identityChangeRevision);
}

function refreshBookSaveState() {
  const hasTitle = Boolean(titleInput.value.trim());
  const hasAuthor = Boolean(authorInput.value.trim());
  const ready = state.editingBookId ? hasTitle : Boolean(state.draftManuscriptId && hasTitle && hasAuthor);
  saveBookButton.disabled = !ready;
  saveBookButton.title = ready
    ? ""
    : state.editingBookId
      ? "Enter a title before saving."
      : "Wait for Bookinator to identify the manuscript, then confirm its title and author.";
}

function selectedBookPriority() {
  return bookPriorityInputs.find((input) => input.checked)?.value || "normal";
}

function setBookPriority(priority) {
  const value = ["high", "normal", "low", "shelved"].includes(priority) ? priority : "normal";
  bookPriorityInputs.forEach((input) => { input.checked = input.value === value; });
}

function refreshLlmReviewSetting() {
  llmReviewSettingCopy.textContent = bookLlmReviewInput.checked
    ? "On · adds cumulative context and optional machine review"
    : "Off · ordinary analysis and human review only";
}
bookLlmReviewInput.addEventListener("change", refreshLlmReviewSetting);
bookLlmReviewInput.addEventListener("change", scheduleIdentityAutosave);
bookPriorityInputs.forEach((input) => input.addEventListener("change", scheduleIdentityAutosave));

function resetBookMarkImageStatus() {
  imageMarkWell.classList.remove("invalid", "working");
  imageMarkWell.querySelector("span").textContent = "Choose image";
  imageMarkStatus.className = "book-mark-image-status";
  imageMarkStatus.textContent = "Drop, paste, or choose an image · ⌘V on macOS, Ctrl+V on Windows and Linux";
}

function refreshDraftIcon() {
  renderIcon(markPreview, state.draftIcon, titleInput.value || "B", authorInput.value);
  markText.value = state.draftIcon?.kind === "unicode" ? state.draftIcon.value : "";
  markColor.value = state.draftIcon?.background || "#071f4a";
  markOutline.checked = state.draftIcon?.outline ?? state.draftIcon?.kind !== "image";
}

function setDraftIcon(icon) {
  if (icon) {
    icon.background = markColor.value || icon.background || "#071f4a";
    icon.outline = icon.kind !== "image";
  }
  state.draftIcon = icon;
  refreshDraftIcon();
  scheduleIdentityAutosave();
}

titleInput.addEventListener("input", () => {
  if (titleInput.value.trim() !== state.abbreviationTitle) state.suggestedAbbreviation = "";
  if (!state.draftIcon) refreshDraftIcon();
  refreshBookSaveState();
  scheduleIdentityAutosave();
});
authorInput.addEventListener("input", () => {
  refreshDraftIcon();
  refreshBookSaveState();
  scheduleIdentityAutosave();
});

markText.addEventListener("input", () => {
  const value = shortMark(markText.value);
  if (markText.value !== value) markText.value = value;
  const changingToText = state.draftIcon?.kind !== "unicode";
  state.draftIcon = unicodeIcon(value);
  if (state.draftIcon) {
    state.draftIcon.background = markColor.value;
    state.draftIcon.outline = changingToText ? true : markOutline.checked;
    if (changingToText) markOutline.checked = true;
  }
  renderIcon(markPreview, state.draftIcon, titleInput.value || "B", authorInput.value);
  scheduleIdentityAutosave();
});

function updateDraftAppearance() {
  if (!state.draftIcon) state.draftIcon = fallbackIcon(titleInput.value || "B");
  state.draftIcon.background = markColor.value;
  state.draftIcon.outline = markOutline.checked;
  renderIcon(markPreview, state.draftIcon, titleInput.value || "B", authorInput.value);
}
markColor.addEventListener("input", () => { updateDraftAppearance(); scheduleIdentityAutosave(); });
markColor.addEventListener("change", () => { updateDraftAppearance(); scheduleIdentityAutosave(); });
markOutline.addEventListener("change", () => { updateDraftAppearance(); scheduleIdentityAutosave(); });

document.querySelector("#choose-emoji").addEventListener("click", () => showDialog("emoji-dialog"));
document.querySelector("#use-title-mark").addEventListener("click", async (event) => {
  const title = titleInput.value.trim();
  if (!title) return titleInput.focus();
  const button = event.currentTarget;
  if (state.suggestedAbbreviation && state.abbreviationTitle === title) {
    setDraftIcon(unicodeIcon(state.suggestedAbbreviation));
    return;
  }
  button.disabled = true;
  button.textContent = "Thinking…";
  try {
    const response = await fetch("/api/books/abbreviate", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({title})});
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || "Could not make a title mark.");
    state.suggestedAbbreviation = result.abbreviation;
    state.abbreviationTitle = title;
    setDraftIcon(unicodeIcon(result.abbreviation));
  } finally {
    button.disabled = false;
    button.textContent = "✨ Use title";
  }
});

const suggestedEmoji = ["📖", "📚", "✍️", "🪶", "🕵️", "🧭", "🗝️", "🧵", "🕰️", "🌊", "🌙", "🔥", "🌿", "🦉", "🐉", "🚀", "🏰", "🔎", "🧠", "⚙️", "💌", "🎭", "♟️", "💀"];
document.querySelector("#emoji-grid").innerHTML = suggestedEmoji.map((emoji) => `<button type="button" data-emoji="${emoji}" aria-label="Use ${emoji}">${emoji}</button>`).join("");
document.querySelectorAll("[data-emoji]").forEach((button) => button.addEventListener("click", () => {
  setDraftIcon(unicodeIcon(button.dataset.emoji));
  closeDialog("emoji-dialog");
}));

async function useBookMarkImage(file, successMessage = "Image ready") {
  if (!file) return;
  try {
    imageMarkWell.classList.remove("invalid");
    imageMarkWell.querySelector("span").textContent = "Choose image";
    imageMarkWell.classList.add("working");
    imageMarkStatus.className = "book-mark-image-status";
    imageMarkStatus.textContent = "Preparing image…";
    setDraftIcon(await imageFileToIcon(file));
    imageMarkStatus.className = "book-mark-image-status success";
    imageMarkStatus.textContent = successMessage;
  } catch (error) {
    imageMarkWell.classList.add("invalid");
    imageMarkWell.querySelector("span").textContent = error.message || "Choose an image";
    imageMarkStatus.className = "book-mark-image-status error";
    imageMarkStatus.textContent = error.message || "That clipboard item is not a usable image.";
  } finally {
    imageMarkWell.classList.remove("working");
  }
}

function clipboardImage(clipboardData) {
  if (!clipboardData) return null;
  const imageItem = [...clipboardData.items].find((item) => item.kind === "file" && item.type.startsWith("image/"));
  return imageItem?.getAsFile() || [...clipboardData.files].find((file) => file.type.startsWith("image/")) || null;
}

function isTextEditingTarget(target) {
  if (!(target instanceof Element)) return false;
  if (target.closest("textarea, [contenteditable='true']")) return true;
  const input = target.closest("input");
  return Boolean(input && !["file", "color", "checkbox", "radio", "button", "submit"].includes(input.type));
}

addDialog.addEventListener("paste", (event) => {
  if (isTextEditingTarget(event.target)) return;
  const image = clipboardImage(event.clipboardData);
  if (!image) return;
  event.preventDefault();
  useBookMarkImage(image, "Pasted from clipboard");
});

imageMarkInput.addEventListener("change", (event) => useBookMarkImage(event.target.files[0], "Chosen image ready"));
markPreview.addEventListener("click", () => imageMarkInput.click());
markPreview.addEventListener("keydown", (event) => {
  if (event.key === "Enter" || event.key === " ") {
    event.preventDefault();
    imageMarkInput.click();
  }
});
['dragenter', 'dragover'].forEach((type) => markPreview.addEventListener(type, (event) => {
  event.preventDefault();
  event.stopPropagation();
  event.dataTransfer.dropEffect = "copy";
  markPreview.classList.add("dragging");
}));
['dragleave', 'drop'].forEach((type) => markPreview.addEventListener(type, (event) => {
  event.preventDefault();
  event.stopPropagation();
  markPreview.classList.remove("dragging");
}));
markPreview.addEventListener("drop", (event) => useBookMarkImage([...event.dataTransfer.files].find((file) => file.type.startsWith("image/")), "Dropped image ready"));
["dragenter", "dragover"].forEach((type) => imageMarkWell.addEventListener(type, (event) => {
  event.preventDefault();
  event.stopPropagation();
  event.dataTransfer.dropEffect = "copy";
  imageMarkWell.classList.add("dragging");
}));
["dragleave", "drop"].forEach((type) => imageMarkWell.addEventListener(type, (event) => {
  event.preventDefault();
  event.stopPropagation();
  imageMarkWell.classList.remove("dragging");
}));
imageMarkWell.addEventListener("drop", (event) => useBookMarkImage([...event.dataTransfer.files].find((file) => file.type.startsWith("image/")), "Dropped image ready"));

async function identifyManuscript(file) {
  if (!file) return;
  const status = document.querySelector("#identity-status");
  const titleInput = document.querySelector("#book-title");
  const authorInput = document.querySelector("#book-author");
  manuscriptWell.classList.add("has-file");
  document.querySelector("#file-name").textContent = file.name;
  status.hidden = false;
  status.className = "identity-status working";
  status.innerHTML = '<strong>Reading the opening pages…</strong><small>Pages 1–10 only · looking for the title, author, and a possible book mark.</small><span class="intake-scan" aria-hidden="true"><i></i></span>';
  state.draftManuscriptId = null;
  titleInput.value = "";
  authorInput.value = "";
  refreshBookSaveState();
  try {
    const response = await fetch(`/api/manuscripts/identify?filename=${encodeURIComponent(file.name)}`, {
      method: "POST",
      headers: {"Content-Type": file.type || (file.name.toLowerCase().endsWith(".pdf") ? "application/pdf" : "text/plain")},
      body: file,
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || "Bookinator could not inspect this manuscript.");
    titleInput.value = result.title || "";
    authorInput.value = result.author || "";
    state.draftManuscriptId = result.manuscriptId || null;
    state.suggestedAbbreviation = result.abbreviation || "";
    state.abbreviationTitle = titleInput.value.trim();
    let suggestedIcon = null;
    if (result.icon?.kind === "image" && String(result.icon.value || "").startsWith("data:image/")) {
      try {
        const imageResponse = await fetch(result.icon.value);
        suggestedIcon = {
          ...await imageFileToIcon(await imageResponse.blob()),
          source: result.icon.source,
          model: result.icon.model,
          confidence: result.icon.confidence,
        };
      } catch {
        suggestedIcon = null;
      }
    }
    if (!state.draftIcon && suggestedIcon) setDraftIcon(suggestedIcon);
    else if (!state.draftIcon) refreshDraftIcon();
    if (result.source === "local-model") {
      status.className = "identity-status";
      status.textContent = suggestedIcon
        ? `Found the title, author, and a possible book icon with ${result.model}. Please give all three a quick look.`
        : `Found these on the title page with ${result.model}. Please give them a quick look.`;
    } else if (!result.pdfReaderReady) {
      status.className = "identity-status warning";
      status.textContent = "I used the filename for now. Install the PDF reader from Local setup to inspect the title page.";
    } else {
      status.className = "identity-status";
      status.textContent = "Found manuscript details in the opening pages. Please give them a quick look.";
    }
    const identifiedTitle = titleInput.value.trim();
    const titleCollision = state.books.some((book) => String(book.title || "").trim().toLocaleLowerCase() === identifiedTitle.toLocaleLowerCase());
    if (identifiedTitle && titleCollision) {
      const importKey = "new-manuscript";
      const overrides = await chooseImportTitles([{
        importKey,
        title: identifiedTitle,
        suggestedTitle: suggestedNewManuscriptTitle(identifiedTitle),
        reason: "same-title",
      }], {}, {
        context: "Duplicate book title",
        message: "This library already contains that title. Confirm the suggested name or choose another unique title before adding this manuscript.",
        label: "Title for this new manuscript",
      });
      if (overrides?.[importKey]) {
        titleInput.value = overrides[importKey];
        status.className = "identity-status";
        status.textContent = `This library already had “${identifiedTitle}.” This manuscript will be added as “${titleInput.value}.”`;
      } else {
        status.className = "identity-status warning";
        status.textContent = `This library already has a book named “${identifiedTitle}.” Choose a unique title before adding this manuscript.`;
      }
    }
    (titleInput.value ? authorInput : titleInput).focus();
    refreshBookSaveState();
  } catch (error) {
    titleInput.value = file.name.replace(/\.(pdf|docx|epub|txt|md)$/i, "").replace(/[-_]+/g, " ");
    if (!state.draftIcon) refreshDraftIcon();
    status.className = "identity-status warning";
    status.textContent = error instanceof Error && error.message ? error.message : "Bookinator could not inspect this manuscript. Check the local setup, then try again.";
    titleInput.focus();
    refreshBookSaveState();
  }
}

manuscriptInput.addEventListener("change", (event) => identifyManuscript(event.target.files[0]));
["dragenter", "dragover"].forEach((type) => manuscriptWell.addEventListener(type, (event) => {
  event.preventDefault();
  manuscriptWell.classList.add("dragging");
}));
["dragleave", "drop"].forEach((type) => manuscriptWell.addEventListener(type, (event) => {
  event.preventDefault();
  manuscriptWell.classList.remove("dragging");
}));
manuscriptWell.addEventListener("drop", (event) => {
  const file = manuscriptFromDrop(event);
  if (!file) {
    const status = document.querySelector("#identity-status");
    status.hidden = false;
    status.className = "identity-status warning";
    status.textContent = "Choose a PDF, DOCX, EPUB, TXT, or Markdown manuscript.";
    return;
  }
  identifyManuscript(file);
});

async function persistBookForm({embedded = identityFormIsInline(), revision = identityChangeRevision} = {}) {
  const title = document.querySelector("#book-title").value.trim();
  const author = document.querySelector("#book-author").value.trim();
  const existing = state.books.find((item) => item.id === state.editingBookId);
  if (!title || (!existing && (!author || !state.draftManuscriptId))) {
    refreshBookSaveState();
    if (embedded) setIdentitySaveState("error", !title ? "Enter a title to save these changes" : "Author information is required");
    else (!title ? titleInput : authorInput).focus();
    return false;
  }
  updateDraftAppearance();
  const requestedLlmReview = bookLlmReviewInput.checked;
  const book = { ...existing, id: existing?.id || crypto.randomUUID(), title, author, icon: state.draftIcon || fallbackIcon(title), abbreviation: state.suggestedAbbreviation, priority: selectedBookPriority(), llmReviewEnabled: requestedLlmReview, status: existing?.status || "new", progress: existing?.progress || "Ready to inspect", updated: "Just now", manuscriptId: state.draftManuscriptId };
  const status = document.querySelector("#identity-status");
  let savedBook;
  try {
    const response = await fetch("/api/books", { method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(book) });
    const result = await response.json();
    if (response.status === 409 && result.code === "title-collision" && !existing) {
      const overrides = await chooseImportTitles(result.collisions || [], {}, {
        context: "Duplicate book title",
        message: "This manuscript has not been added yet. Confirm the suggested name or choose another unique title so both books remain unmistakable.",
        label: "Title for this new manuscript",
      });
      if (!overrides) {
        status.hidden = false;
        status.className = "identity-status warning";
        status.textContent = "This manuscript was not added because its title matches another book.";
        return false;
      }
      const collision = result.collisions?.[0];
      const replacement = collision ? overrides[collision.importKey] : "";
      if (!replacement) throw new Error(result.error || "Choose a unique title for this manuscript.");
      titleInput.value = replacement;
      state.abbreviationTitle = "";
      refreshBookSaveState();
      return persistBookForm({embedded, revision});
    }
    if (!response.ok) throw new Error(result.error || "Bookinator could not save this book.");
    if (Boolean(result.book?.llmReviewEnabled) !== requestedLlmReview) {
      throw new Error("The running Bookinator server did not save the LLM Review setting. Let active analysis finish, restart ./bin/serve, then try again.");
    }
    savedBook = result.book;
    state.books = existing
      ? state.books.map((item) => item.id === result.book.id ? result.book : item)
      : [result.book, ...state.books];
  } catch (error) {
    const message = error instanceof Error ? error.message : "Bookinator could not save this book.";
    if (embedded) {
      identityQueuedRevision = Math.min(identityQueuedRevision, revision - 1);
      setIdentitySaveState("error", message);
    }
    else {
      status.hidden = false;
      status.className = "identity-status warning";
      status.textContent = message;
    }
    return false;
  }
  if (embedded) {
    const bookPage = document.querySelector("#book-page");
    const header = document.querySelector("#book-workspace-header");
    header.querySelector(".workspace-book-copy h1").textContent = savedBook.title;
    header.querySelector(".workspace-book-copy p").textContent = savedBook.author || "Author not specified";
    renderIcon(header.querySelector("#workspace-book-icon"), savedBook.icon, savedBook.title, savedBook.author);
    bookPage.dataset.identitySignature = JSON.stringify({id: savedBook.id, title: savedBook.title, author: savedBook.author, icon: savedBook.icon, priority: savedBook.priority, manuscriptId: savedBook.manuscriptId, sourceFilename: savedBook.sourceFilename, ingestedAt: savedBook.ingestedAt, llmReviewEnabled: savedBook.llmReviewEnabled});
    renderWorkspaceNavigation(document.querySelector("#book-tabs"), savedBook, "identity");
    identitySavedRevision = Math.max(identitySavedRevision, revision);
    if (revision === identityChangeRevision) setIdentitySaveState("", "All changes saved");
    return true;
  }
  bookForm.reset();
  state.draftIcon = null;
  state.draftManuscriptId = null;
  state.editingBookId = null;
  state.suggestedAbbreviation = "";
  state.abbreviationTitle = "";
  manuscriptWell.classList.remove("has-file");
  document.querySelector("#file-name").textContent = "";
  document.querySelector("#identity-status").hidden = true;
  refreshDraftIcon();
  closeDialog("add-dialog");
  if (existing) {
    state.pipelineSignature = "";
    route();
  }
  else location.hash = `book/${savedBook.id}/pipeline`;
  return true;
}

document.querySelector("#book-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (identityFormIsInline()) await flushIdentityAutosave();
  else await persistBookForm({embedded: false});
});

search.addEventListener("input", () => {
  saveLibraryViewPreferences();
  render();
});
filter.addEventListener("change", () => {
  saveLibraryViewPreferences();
  render();
});

async function refreshLibraryBooks({poll = false} = {}) {
  clearTimeout(state.libraryTimer);
  const libraryVisible = !document.querySelector("#books-page")?.hidden || !document.querySelector("#pipeline-page")?.hidden;
  let response = await fetch(libraryVisible ? "/api/books" : "/api/library/pipeline");
  // A browser may refresh before the long-running local server is restarted
  // onto the lightweight endpoint. Fall back without rebuilding hidden UI.
  if (!libraryVisible && !response.ok) response = await fetch("/api/books");
  const payload = await response.json();
  if (response.ok && libraryVisible && Array.isArray(payload.books)) {
    state.books = payload.books;
    state.globalPipeline = payload.pipeline || state.globalPipeline;
  } else if (response.ok && payload.pipeline) {
    state.globalPipeline = payload.pipeline;
  }
  if (!state.priorityInteractionActive && libraryVisible) render();
  else {
    updateGlobalPipelineStatus();
    updateLocalQueueStatus();
  }
  if (poll && (state.globalPipeline.running || (state.globalPipeline.enabled && state.globalPipeline.waitingBooks > 0))) {
    state.libraryTimer = setTimeout(() => refreshLibraryBooks({poll: true}), 1800);
  }
}

async function postLibraryAction(path, payload = {}) {
  const response = await fetch(path, {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(payload)});
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || "The library action failed.");
  return result;
}

async function handlePipelineSelectionAction(action) {
  const selected = pipelineTasks().filter((task) => state.pipelineSelection.has(task.id));
  if (!selected.length) return;
  const books = [...new Map(selected.map((task) => [task.book.id, task.book])).values()];
  try {
    if (action === "top") {
      const ready = selected.filter((task) => task.state === "ready" && !task.required);
      if (!ready.length) return;
      for (const task of [...ready].reverse()) {
        await postLibraryAction("/api/library/pipeline/prioritize", {bookId: task.book.id, action: task.action});
      }
    } else if (action === "raise" || action === "lower") {
      const levels = ["high", "normal", "low"];
      for (const book of books) {
        const current = levels.includes(book.priority) ? book.priority : "normal";
        const index = levels.indexOf(current);
        const next = levels[Math.max(0, Math.min(levels.length - 1, index + (action === "raise" ? -1 : 1)))];
        if (next !== current) await saveBookPriority(book, next);
      }
    } else if (action === "pause" || action === "resume") {
      const pausing = action === "pause";
      const changed = selected.filter((task) => !task.required && (pausing ? !["paused", "pausing"].includes(task.state) : ["paused", "pausing"].includes(task.state)));
      for (const task of changed) {
        await postLibraryAction("/api/library/pipeline/task-state", {bookId: task.book.id, action: task.action, paused: pausing});
      }
    }
    state.pipelineSelection.clear();
    await refreshLibraryBooks({poll: true});
  } catch (error) {
    await confirmAction({context: "Queue unchanged", title: "Bookinator could not update those jobs", message: error.message, acceptLabel: "Close"});
  }
}

document.querySelector(".pipeline-queue-actions")?.addEventListener("click", (event) => {
  const button = event.target.closest("[data-pipeline-selection-action]");
  if (button && !button.disabled) handlePipelineSelectionAction(button.dataset.pipelineSelectionAction);
});

document.querySelector("#pipeline-page-size")?.addEventListener("change", (event) => {
  const requested = event.currentTarget.value === "all" ? "all" : Number(event.currentTarget.value);
  pipelinePageSize = pipelinePageSizes.includes(requested) ? requested : 10;
  pipelinePage = 1;
  localStorage.setItem(pipelinePageSizeKey, String(pipelinePageSize));
  renderPipelineQueue();
});

document.querySelector("#pipeline-attention-button")?.addEventListener("click", () => {
  document.querySelector(".pipeline-diagnostics-section")?.scrollIntoView({behavior: "smooth", block: "start"});
});

document.querySelector("#pipeline-page-previous")?.addEventListener("click", () => {
  pipelinePage = Math.max(1, pipelinePage - 1);
  renderPipelineQueue();
});

document.querySelector("#pipeline-page-next")?.addEventListener("click", () => {
  pipelinePage += 1;
  renderPipelineQueue();
});

function localIsoDate(date = new Date()) {
  return [date.getFullYear(), String(date.getMonth() + 1).padStart(2, "0"), String(date.getDate()).padStart(2, "0")].join("-");
}

function libraryBundleFilename(books, date = new Date()) {
  const identity = books.length === 1
    ? String(books[0]?.title || "book").toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "") || "book"
    : `${books.length}_books`;
  return `bookinator-${identity}-${localIsoDate(date)}.bookinator`;
}

document.querySelector("#export-books").addEventListener("click", async () => {
  if (!state.selection.size) return;
  const selectedBooks = state.books.filter((book) => state.selection.has(book.id));
  const response = await fetch(`/api/library/export?ids=${encodeURIComponent([...state.selection].join(","))}`);
  if (!response.ok) {
    const result = await response.json().catch(() => ({}));
    await confirmAction({context: "Export failed", title: "Bookinator could not export those books", message: result.error || "The complete project package could not be built.", acceptLabel: "Close"});
    return;
  }
  const blob = await response.blob();
  const legacyExport = response.headers.get("Content-Type")?.includes("application/json");
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = legacyExport ? libraryBundleFilename(selectedBooks).replace(/\.bookinator$/, ".json") : libraryBundleFilename(selectedBooks);
  link.click();
  setTimeout(() => URL.revokeObjectURL(link.href), 1000);
  if (legacyExport) {
    await confirmAction({context: "Legacy export", title: "Restart Bookinator for complete project exports", message: "The running server is still using the older library exporter. This JSON download contains library metadata and saved analysis, but not source documents, generated artifacts, or saved reports.", acceptLabel: "Close"});
  }
});

document.querySelector("#delete-books").addEventListener("click", async () => {
  if (!state.selection.size) return;
  const count = state.selection.size;
  const selectedBooks = state.books.filter((book) => state.selection.has(book.id));
  const single = selectedBooks[0];
  const identity = count === 1
    ? ` “${single.title}” · project ${String(single.id).slice(0, 8)} · ${single.sourceAvailable ? `preserved source: ${single.sourceFilename}` : "no preserved source document"}.`
    : "";
  const approved = await confirmAction({context: "Delete from this computer", title: `Delete ${count} selected ${count === 1 ? "book" : "books"}?`, message: `This removes the saved PDF, chapter summaries, pipeline history, and library record.${identity} Export first if you may need the analysis later.`, acceptLabel: "Delete permanently"});
  if (!approved) return;
  const ids = [...state.selection];
  try {
    const result = await postLibraryAction("/api/library/delete", {ids});
    if (result.deleted !== ids.length) throw new Error(`Bookinator removed ${result.deleted} of ${ids.length} selected books.`);
    state.books = state.books.filter((book) => !state.selection.has(book.id));
    state.selection.clear();
    render();
    await refreshLibraryBooks();
    if (result.cleanupWarnings?.length) await confirmAction({context: "Book deleted", title: "The library record was removed", message: "Some manuscript files could not be cleaned up yet. Bookinator will not show the deleted book.", acceptLabel: "Close"});
  } catch (error) {
    await refreshLibraryBooks();
    await confirmAction({context: "Delete failed", title: "Bookinator could not finish deleting", message: error.message || "The selected book is still in the library.", acceptLabel: "Close"});
  }
});

document.querySelector("#toggle-library-pipeline").addEventListener("click", async (event) => {
  const button = event.currentTarget;
  if (button.disabled) return;
  button.disabled = true;
  try {
    await postLibraryAction(state.globalPipeline.enabled ? "/api/library/pipeline/stop" : "/api/library/pipeline/start");
    await refreshLibraryBooks({poll: true});
  } finally {
    button.disabled = false;
  }
});

document.querySelectorAll("[data-coverage-mode]").forEach((button) => button.addEventListener("click", () => {
  pipelineCoverageMode = button.dataset.coverageMode === "reviewed" ? "reviewed" : "analysis";
  localStorage.setItem(pipelineCoverageKey, pipelineCoverageMode);
  updateGlobalPipelineStatus();
}));

document.querySelector("#restart-current-run").addEventListener("click", async (event) => {
  const button = event.currentTarget;
  if (button.disabled) return;
  button.disabled = true;
  try {
    const result = await postLibraryAction("/api/library/pipeline/current-run/restart");
    state.globalPipeline = result.pipeline || state.globalPipeline;
    updateGlobalPipelineStatus();
  } catch (error) {
    await confirmAction({context: "Current run unchanged", title: "Bookinator could not start a fresh run", message: error.message, acceptLabel: "Close"});
  } finally {
    button.disabled = false;
  }
});

const setupInstructions = {
  "operating-system": ["Update this computer to a supported operating system and architecture.", "Bookinator currently targets macOS 14+ on Apple silicon, current 64-bit Windows 10+, and explicitly tested 64-bit Linux distributions.", "Return here after the operating-system update; Bookinator will run the check again."],
  memory: ["This computer does not meet Bookinator’s 32 GB supported memory floor for local analysis.", "Memory cannot usually be added through Bookinator. Use a machine with at least 32 GB, or move this library to one when workspace export is available.", "The library UI may still open, but model-backed analysis is blocked."],
  homebrew: ["Install Homebrew from https://brew.sh using its official installer.", "Reopen Bookinator after installation so it can verify the brew command.", "Bookinator will then use Homebrew—with confirmation—to install and update Ollama and other native dependencies."],
  python: ["Install a current Python 3 release supported by Bookinator; source builds require Python 3.11 or newer.", "Restart Bookinator from that Python environment.", "Packaged Bookinator releases will include their own tested Python and will not require this manual step."],
  "package-installer": ["This source environment has neither uv nor pip, so Bookinator cannot repair its Python components.", "Install uv from its official installer, or restore pip for this exact Python environment.", "Restart Bookinator and reopen Machine to verify the installer before adding components."],
  storage: ["Free space on the volume containing Bookinator’s data and model caches.", "Keep at least 10 GB of working headroom after accounting for every model you plan to install.", "Reopen Machine after moving data or removing files; Bookinator will measure again."],
  ollama: ["Download and install Ollama from https://ollama.com/download for this operating system.", "Start Ollama and leave its local service running.", "Return to Models; Bookinator will verify the local API and then offer only models appropriate for this machine."],
};

function setupInstructionsMarkup(key) {
  const steps = setupInstructions[key];
  if (!steps) return "";
  const external = key === "ollama" ? '<a class="component-install-link" href="https://ollama.com/download" target="_blank" rel="noreferrer">Open Ollama download ↗</a>' : key === "homebrew" ? '<a class="component-install-link" href="https://brew.sh" target="_blank" rel="noreferrer">Open Homebrew ↗</a>' : "";
  return `<button class="component-instructions" type="button" data-setup-instructions="${escapeHtml(key)}" aria-expanded="false">Show instructions</button><div class="setup-instructions" hidden><ol>${steps.map((step) => `<li>${escapeHtml(step)}</li>`).join("")}</ol>${external}</div>`;
}

function readinessCheckMarkup(check) {
  const status = check.status || "warning";
  const mark = status === "ready" ? "✓" : status === "blocked" ? "!" : status === "repairable" ? "↓" : "!";
  const action = check.action === "install-pdf-reader" ? '<button class="component-install" id="install-pdf-reader" type="button">Install</button>' : check.action === "update-ollama" ? '<button class="component-install" id="update-ollama" type="button">Install or update</button>' : "";
  const instructions = setupInstructionsMarkup(check.instructions);
  return `<div class="system-check ${escapeHtml(status)}" data-readiness-check="${escapeHtml(check.id || "")}"><b aria-label="${status === "blocked" ? "Blocking problem" : status === "ready" ? "Ready" : "Needs attention"}">${mark}</b><div><strong>${escapeHtml(check.label || "Readiness check")} · ${escapeHtml(check.value || "")}</strong><small>${escapeHtml(check.detail || "")}</small>${action}${instructions}</div></div>`;
}

function legacyMachineChecks(system) {
  const memoryGiB = Number(system.memoryGiB || 0);
  const pythonVersion = String(system.python || "");
  const [pythonMajor = 0, pythonMinor = 0] = pythonVersion.split(".").map((part) => Number(part) || 0);
  const pythonReady = pythonMajor > 3 || (pythonMajor === 3 && pythonMinor >= 11);
  const recognizedMac = system.platform === "Darwin" && Boolean(system.appleSilicon);
  return [
    {id: "server", label: "Bookinator server", status: "ready", value: "Running", detail: "The local Bookinator server answered this health check."},
    {id: "operating-system", label: "Operating system", status: recognizedMac ? "ready" : "warning", value: `${system.platform || "Unknown"} · ${system.architecture || "Unknown"}`, detail: recognizedMac ? "This Mac has the Apple silicon architecture Bookinator expects." : "Restart Bookinator to run the complete operating-system compatibility check.", instructions: recognizedMac ? "" : "operating-system"},
    {id: "memory", label: "Memory", status: !memoryGiB ? "warning" : memoryGiB >= 32 ? "ready" : "blocked", value: memoryGiB ? `${memoryGiB} GB` : "Unknown", detail: memoryGiB >= 32 ? "This computer meets Bookinator’s 32 GB supported memory floor." : memoryGiB ? "Bookinator requires at least 32 GB for supported model-backed analysis." : "This server could not measure physical memory.", instructions: !memoryGiB || memoryGiB < 32 ? "memory" : ""},
    {id: "python", label: "Python runtime", status: pythonReady ? "ready" : "blocked", value: pythonVersion || "Unknown", detail: pythonReady ? "Python 3.11 or newer is available." : "This source build requires Python 3.11 or newer.", instructions: pythonReady ? "" : "python"},
    {id: "pdf-reader", label: "Document reader", status: system.pdfReader ? "ready" : "repairable", value: system.pdfReader ? "PyMuPDF ready" : "PyMuPDF missing", detail: system.pdfReader ? "PDF and normalized manuscript pages can be read locally." : "Install Bookinator’s local document reader for manuscript ingestion.", action: system.pdfReader ? "" : "install-pdf-reader"},
  ];
}

function wireSetupInstructions(root = document) {
  root.querySelectorAll("[data-setup-instructions]").forEach((button) => button.addEventListener("click", () => {
    const instructions = button.nextElementSibling;
    const opening = instructions.hidden;
    instructions.hidden = !opening;
    button.setAttribute("aria-expanded", String(opening));
    button.textContent = opening ? "Hide instructions" : "Show instructions";
  }));
}

function leaveBookWorkspace() {
  clearTimeout(state.pipelineTimer);
  state.pipelineTimer = null;
  state.workspaceRequestId += 1;
}

async function openSystemPanel(panelName) {
  leaveBookWorkspace();
  document.querySelector("#books-page").hidden = true;
  document.querySelector("#pipeline-page").hidden = true;
  document.querySelector("#article-page").hidden = true;
  document.querySelector("#book-page").hidden = true;
  document.querySelector("#machine-page").hidden = false;
  document.querySelector("#welcome-dialog").hidden = true;
  document.querySelectorAll(".topbar nav [data-page]").forEach((item) => item.classList.toggle("active", item.dataset.page === "machine"));
  document.querySelectorAll(".footer-links a").forEach((link) => link.removeAttribute("aria-current"));
  const machinePanel = document.querySelector("#machine-panel");
  const modelsPanel = document.querySelector("#models-panel");
  const modelsSelected = panelName === "models";
  machinePanel.hidden = modelsSelected;
  modelsPanel.hidden = !modelsSelected;
  document.querySelector("#system-title").textContent = modelsSelected ? "Models" : "Machine";
  document.querySelector("#system-subtitle").textContent = modelsSelected ? "Local readers, specialists, and their assignments." : "Server and components on this computer.";
  document.querySelectorAll(".system-dialog-tabs [data-system-panel]").forEach((tab) => {
    if (tab.dataset.systemPanel === panelName) tab.setAttribute("aria-current", "page");
    else tab.removeAttribute("aria-current");
  });
  updateLocalQueueStatus();
  document.title = `${modelsSelected ? "Models" : "Machine"} · Bookinator`;
  const checks = document.querySelector("#system-checks");
  const modelChecks = document.querySelector("#model-checks");
  try {
    const response = await fetch("/api/system");
    const system = await response.json();
    const ollama = system.ollama;
    const emotionModel = system.emotionModel || {ready: false, runtime: false, model: false};
    const hasReadinessManifest = Array.isArray(system.readiness?.checks) && system.readiness.checks.length > 0;
    const machineChecks = hasReadinessManifest ? system.readiness.checks : legacyMachineChecks(system);
    const compatibilityNotice = hasReadinessManifest ? "" : '<div class="system-version-notice"><strong>Showing the checks this server can verify.</strong><span>Restart <code>./bin/serve</code> to add the complete OS, storage, and installer checks.</span></div>';
    checks.innerHTML = `${compatibilityNotice}${machineChecks.map(readinessCheckMarkup).join("")}`;
    const machineNavigation = document.querySelector("#machine-nav");
    const machineNavigationStatus = document.querySelector("#machine-nav-status");
    const blockedCount = hasReadinessManifest ? Number(system.readiness.blockedCount || 0) : machineChecks.filter((check) => check.status === "blocked").length;
    const readinessStatus = hasReadinessManifest ? system.readiness.status : blockedCount ? "blocked" : "warning";
    machineNavigationStatus.textContent = blockedCount ? `${blockedCount} blocking` : readinessStatus === "warning" ? "Needs attention" : "Local · Ready";
    machineNavigation.classList.toggle("blocked", blockedCount > 0);
    machineNavigation.classList.toggle("warning", !blockedCount && readinessStatus === "warning");
    modelChecks.innerHTML = `
      <div class="system-check ${emotionModel.ready ? "" : "warning"}" id="emotion-model-check"><b>${emotionModel.ready ? "✓" : "!"}</b><div><strong>${emotionModel.ready ? "Emotion classifier is ready" : "Emotion classifier needs installing"}</strong><small>${emotionModel.ready ? "Hartmann DistilRoBERTa is cached and runs locally." : "This installs PyTorch, Transformers, and the pinned Hartmann model inside Bookinator."}</small>${emotionModel.ready ? '<div class="model-card-actions"><a class="component-install-link" href="https://huggingface.co/j-hartmann/emotion-english-distilroberta-base" target="_blank" rel="noreferrer">Inspect model card ↗</a><button class="component-uninstall" data-manual-uninstall="emotion" type="button">Uninstall</button></div>' : '<button class="component-install" id="install-emotion-model" type="button">Install emotion classifier</button>'}</div></div>
      <div class="system-check ${ollama.running ? "ready" : "blocked"}"><b>${ollama.running ? "✓" : "!"}</b><div><strong>${ollama.running ? "Ollama is awake" : ollama.installed ? "Ollama is installed but not running" : "Ollama is not installed"}</strong><small>${ollama.running ? `${ollama.models.length} local ${ollama.models.length === 1 ? "model" : "models"} available.` : "Ollama is required for chapter summaries and other LLM analysis."}</small>${ollama.running ? '<div class="model-card-actions"><a class="component-install-link" href="https://ollama.com/download" target="_blank" rel="noreferrer">Inspect Ollama ↗</a><button class="component-uninstall" data-manual-uninstall="ollama" type="button">Uninstall</button></div>' : setupInstructionsMarkup("ollama")}</div></div>`;
    wireSetupInstructions(document.querySelector("#machine-page"));
    document.querySelectorAll("[data-manual-uninstall]").forEach((button) => button.addEventListener("click", async () => {
      const emotion = button.dataset.manualUninstall === "emotion";
      await confirmAction({
        context: "Manual uninstall",
        title: emotion ? "Remove the emotion classifier" : "Remove Ollama",
        message: emotion
          ? "Bookinator cannot safely edit its Python environment while the server is running. Quit Bookinator, remove the emotion-model packages and cached j-hartmann model from the Bookinator environment, then relaunch. A guided maintenance command belongs here before release; for now, keeping it installed is harmless."
          : "Quit Bookinator and Ollama first, then use Ollama’s official uninstall instructions for your operating system. Removing Ollama disables every local LLM pipeline until it is installed again; your books and completed analysis remain safe.",
        acceptLabel: "Close",
      });
    }));
    const workshop = document.querySelector("#model-workshop");
    workshop.hidden = !ollama.running;
    if (ollama.running) {
      const modelMessage = document.querySelector("#model-message");
      const showInstallStatus = (kind, title, detail = "", helpUrl = "", helpLabel = "Learn more") => {
        modelMessage.hidden = false;
        modelMessage.className = `model-install-status ${kind}`;
        modelMessage.innerHTML = `<strong>${escapeHtml(title)}</strong>${detail ? `<span>${escapeHtml(detail)}</span>` : ""}${helpUrl ? `<span><a href="${escapeHtml(helpUrl)}" target="_blank" rel="noreferrer">${escapeHtml(helpLabel)} ↗</a></span>` : ""}`;
      };
      const addInstalledModelToRoleMenus = (modelName) => {
        if (!ollama.models.includes(modelName)) ollama.models.push(modelName);
        document.querySelectorAll("[data-model-role]").forEach((select) => {
          if (![...select.options].some((option) => option.value === modelName)) select.add(new Option(modelName, modelName));
        });
      };
      const installModel = async (modelName, button = null) => {
        if (!modelName) return;
        const originalLabel = button?.textContent || "Install model";
        if (button) {
          button.disabled = true;
          button.textContent = "Installing…";
          button.closest(".model-option")?.classList.add("installing");
        }
        showInstallStatus("working", `Installing ${modelName}`, "Ollama is downloading the model. Large models can take quite a while; you may close this panel while it works.");
        try {
          const pullResponse = await fetch("/api/models/pull", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({model: modelName})});
          const pulled = await pullResponse.json();
          if (!pullResponse.ok) {
            const failure = new Error(pulled.error || "Ollama could not install that model.");
            failure.payload = pulled;
            throw failure;
          }
          addInstalledModelToRoleMenus(pulled.model);
          showInstallStatus("success", `${pulled.model} is installed`, "It is now available in the role selectors above. No Hugging Face key was required.");
          if (button) button.textContent = "Installed";
          return true;
        } catch (error) {
          const failure = error.payload || {};
          showInstallStatus("error", error.message || "Model installation failed", failure.guidance || "Open Ollama and try again.", failure.helpUrl || "", failure.needsHuggingFaceToken ? "Create a Hugging Face read token" : "Open Ollama’s model library");
          if (button) {
            button.disabled = false;
            button.textContent = originalLabel;
          }
          return false;
        } finally {
          button?.closest(".model-option")?.classList.remove("installing");
        }
      };
      const uninstallModel = async (modelName, modelLabel, button) => {
        const assignedRoles = Object.entries(system.models.roles || {}).filter(([, assigned]) => assigned === modelName).map(([role]) => system.models.roleLabels?.[role] || role);
        const assignmentWarning = assignedRoles.length ? ` It is currently assigned to ${assignedRoles.join(", ")}. Those roles will stop working until you assign another installed model.` : "";
        const approved = await confirmAction({
          context: "Remove local model",
          title: `Uninstall ${modelLabel}?`,
          message: `This deletes the model weights from Ollama on this computer. Bookinator will keep manuscripts and completed analysis.${assignmentWarning}`,
          acceptLabel: "Uninstall model",
        });
        if (!approved) return;
        const originalLabel = button.textContent;
        button.disabled = true;
        button.textContent = "Uninstalling…";
        try {
          const response = await fetch("/api/models/delete", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({model: modelName})});
          const result = await response.json();
          if (!response.ok) throw new Error(result.error || "Ollama could not uninstall that model.");
          await openSystemPanel("models");
        } catch (error) {
          button.disabled = false;
          button.textContent = originalLabel;
          showInstallStatus("error", error.message || "Model uninstall failed", assignedRoles.length ? "Stop the analysis queue or assign those roles to another installed model, then try again." : "Check that Ollama is running, then try again.");
        }
      };
      const primaryRecommendation = system.models.roleRecommendations.primary;
      const heavyweightAdvice = system.memoryGiB >= 320 ? "This Mac can also run the 235B Q8 heavyweight as a demanding second opinion." : system.memoryGiB >= 180 ? "This Mac can also run the 235B Q4 heavyweight as a demanding second opinion." : "Skip the 235B heavyweight on this machine; leave memory for long context and the rest of Bookinator.";
      document.querySelector("#hardware-advice").innerHTML = `<strong>${system.memoryGiB} GB of unified memory gives Bookinator room to think.</strong>Use <b>${escapeHtml(primaryRecommendation)}</b> as the primary reader. The fast utility model handles inexpensive intake work. ${heavyweightAdvice}`;
      document.querySelector("#role-models").innerHTML = Object.entries(system.models.roleLabels).map(([role, label]) => `<div class="role-model-row"><label for="role-${role}">${escapeHtml(label)}</label><select id="role-${role}" data-model-role="${role}"><option value=""${system.models.roles[role] ? "" : " selected"}>Not assigned</option>${ollama.models.map((model) => `<option value="${escapeHtml(model)}"${model === system.models.roles[role] ? " selected" : ""}>${escapeHtml(model)}${model === system.models.roleRecommendations[role] ? " · recommended" : ""}</option>`).join("")}</select></div>`).join("");
      document.querySelectorAll("[data-model-role]").forEach((select) => select.addEventListener("change", async () => {
        const saveResponse = await fetch("/api/settings", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({role: select.dataset.modelRole, model: select.value})});
        const saved = await saveResponse.json();
        showInstallStatus(saveResponse.ok ? "success" : "error", saveResponse.ok ? `${saved.model} is now assigned to ${system.models.roleLabels[saved.role].toLowerCase()}.` : saved.error);
        if (!saveResponse.ok) return;
        system.models.roles[select.dataset.modelRole] = saved.model;
      }));
      document.querySelector("#model-catalog").innerHTML = system.models.catalog.map((model) => {
        const installed = ollama.models.includes(model.tag);
        const facts = [
          `${model.sizeGb} GB`,
          model.tier,
          model.memory,
          model.license,
        ].filter(Boolean).map(escapeHtml).join(" · ");
        const source = model.hf ? `<a href="${escapeHtml(model.hf)}" target="_blank" rel="noreferrer">Inspect model card ↗</a>` : "";
        const consent = model.userDownload ? "Bookinator does not distribute these weights. Install asks your local Ollama service to download them from Hugging Face." : "";
        const action = installed
          ? `<button class="component-uninstall" type="button" data-remove-model="${escapeHtml(model.tag)}" data-model-label="${escapeHtml(model.label)}">Uninstall</button>`
          : `<button type="button" data-catalog-model="${escapeHtml(model.tag)}">${model.userDownload ? `Download ${model.sizeGb} GB` : "Install"}</button>`;
        return `<article class="model-option${model.category ? ` ${escapeHtml(model.category)}` : ""}"><strong>${escapeHtml(model.label)} · ${escapeHtml(model.tag)}</strong><span>${facts}</span><small>${escapeHtml(model.use)}</small>${consent ? `<small>${escapeHtml(consent)}</small>` : ""}<div class="model-card-actions">${source}${action}</div></article>`;
      }).join("");
      const catalogByTag = new Map(system.models.catalog.map((model) => [model.tag, model]));
      document.querySelector("#installed-models").innerHTML = ollama.models.map((modelName) => {
        const known = catalogByTag.get(modelName);
        const baseName = modelName.split(":", 1)[0];
        const cardUrl = known?.hf || `https://ollama.com/library/${encodeURIComponent(baseName)}`;
        return `<article class="model-option"><strong>${escapeHtml(known?.label || modelName)}</strong>${known?.label ? `<span>${escapeHtml(modelName)}</span>` : ""}<small>Installed locally in Ollama.</small><div class="model-card-actions"><a href="${escapeHtml(cardUrl)}" target="_blank" rel="noreferrer">Inspect model card ↗</a><button class="component-uninstall" type="button" data-remove-model="${escapeHtml(modelName)}" data-model-label="${escapeHtml(known?.label || modelName)}">Uninstall</button></div></article>`;
      }).join("") || "<p>No Ollama models are installed.</p>";
      document.querySelectorAll("[data-catalog-model]").forEach((button) => button.addEventListener("click", async () => {
        if (await installModel(button.dataset.catalogModel, button)) await openSystemPanel("models");
      }));
      document.querySelectorAll("[data-remove-model]").forEach((button) => button.addEventListener("click", () => uninstallModel(button.dataset.removeModel, button.dataset.modelLabel || button.dataset.removeModel, button)));
      const pullButton = document.querySelector("#pull-model");
      pullButton.onclick = async () => {
        const nameInput = document.querySelector("#model-name");
        const modelName = nameInput.value.trim();
        if (!modelName) return nameInput.focus();
        pullButton.disabled = true;
        pullButton.textContent = "Installing…";
        const installed = await installModel(modelName);
        pullButton.disabled = false;
        pullButton.textContent = "Install model";
        if (installed) nameInput.value = "";
      };
    }
    const installButton = document.querySelector("#install-pdf-reader");
    installButton?.addEventListener("click", async () => {
      installButton.disabled = true;
      installButton.textContent = "Installing locally…";
      try {
        const installResponse = await fetch("/api/setup/pdf-reader", {method: "POST"});
        const installResult = await installResponse.json();
        if (!installResponse.ok) throw new Error(installResult.message);
        document.querySelector("#pdf-reader-check").outerHTML = '<div class="system-check"><b>✓</b><div><strong>PDF reader is ready</strong><small>Bookinator can inspect manuscript text and metadata.</small></div></div>';
      } catch (error) {
        installButton.disabled = false;
        installButton.textContent = "Try installation again";
        document.querySelector("#pdf-reader-check small").textContent = error.message;
      }
    });
    const updateOllamaButton = document.querySelector("#update-ollama");
    updateOllamaButton?.addEventListener("click", async () => {
      const approved = await confirmAction({context: "Local dependency", title: "Install or update Ollama?", message: "Bookinator will ask Homebrew to install the current Ollama release. The analysis queue must be stopped first. Existing downloaded models and completed analysis will remain in place.", acceptLabel: "Install Ollama"});
      if (!approved) return;
      updateOllamaButton.disabled = true;
      updateOllamaButton.textContent = "Updating…";
      try {
        const response = await fetch("/api/setup/ollama", {method: "POST"});
        const result = await response.json();
        if (!response.ok) throw new Error(result.error || "Ollama could not be updated.");
        await openSystemPanel("machine");
      } catch (error) {
        updateOllamaButton.disabled = false;
        updateOllamaButton.textContent = "Try again";
        await confirmAction({context: "Ollama update", title: "Ollama was not updated", message: error.message, acceptLabel: "Close"});
      }
    });
    const emotionInstallButton = document.querySelector("#install-emotion-model");
    emotionInstallButton?.addEventListener("click", async () => {
      emotionInstallButton.disabled = true;
      emotionInstallButton.textContent = "Installing locally…";
      try {
        const installResponse = await fetch("/api/setup/emotion-model", {method: "POST"});
        const installResult = await installResponse.json();
        if (!installResponse.ok) throw new Error(installResult.message);
        document.querySelector("#emotion-model-check").outerHTML = '<div class="system-check"><b>✓</b><div><strong>Emotion classifier is ready</strong><small>Hartmann DistilRoBERTa is cached and runs locally.</small></div></div>';
        await refreshLibraryBooks({poll: true});
      } catch (error) {
        emotionInstallButton.disabled = false;
        emotionInstallButton.textContent = "Try installation again";
        document.querySelector("#emotion-model-check small").textContent = error.message;
      }
    });
  } catch {
    checks.innerHTML = "<p>Bookinator could not inspect this computer. Restart <code>./bin/serve</code> and try again.</p>";
    modelChecks.innerHTML = "<p>Bookinator could not inspect local models. Restart <code>./bin/serve</code> and try again.</p>";
  }
}

document.querySelectorAll(".system-dialog-tabs [data-system-panel]").forEach((tab) => tab.addEventListener("click", () => openSystemPanel(tab.dataset.systemPanel)));

function showBooksPage() {
  leaveBookWorkspace();
  document.querySelector("#books-page").hidden = false;
  document.querySelector("#pipeline-page").hidden = true;
  document.querySelector("#article-page").hidden = true;
  document.querySelector("#book-page").hidden = true;
  document.querySelector("#machine-page").hidden = true;
  document.querySelectorAll(".topbar nav [data-page]").forEach((item) => item.classList.toggle("active", item.dataset.page === "books"));
  document.querySelectorAll(".footer-links a").forEach((link) => link.removeAttribute("aria-current"));
  document.title = "Books · Bookinator";
}

function showPipelinePage() {
  leaveBookWorkspace();
  document.querySelector("#books-page").hidden = true;
  document.querySelector("#pipeline-page").hidden = false;
  document.querySelector("#article-page").hidden = true;
  document.querySelector("#book-page").hidden = true;
  document.querySelector("#machine-page").hidden = true;
  document.querySelector("#welcome-dialog").hidden = true;
  document.querySelectorAll(".topbar nav [data-page]").forEach((item) => item.classList.toggle("active", item.dataset.page === "pipeline"));
  document.querySelectorAll(".footer-links a").forEach((link) => link.removeAttribute("aria-current"));
  renderPipelineQueue();
  renderPipelineDiagnostics();
  updateGlobalPipelineStatus();
  document.title = "Pipeline · Bookinator";
}

function showArticlePage(collection, requestedTab) {
  leaveBookWorkspace();
  const page = articlePages[collection] || articlePages.about;
  const tabKeys = Object.keys(page.tabs);
  const activeTab = tabKeys.includes(requestedTab) ? requestedTab : tabKeys[0];
  document.querySelector("#books-page").hidden = true;
  document.querySelector("#pipeline-page").hidden = true;
  document.querySelector("#article-page").hidden = false;
  document.querySelector("#book-page").hidden = true;
  document.querySelector("#machine-page").hidden = true;
  document.querySelector("#welcome-dialog").hidden = true;
  document.querySelectorAll(".topbar nav [data-page]").forEach((item) => item.classList.remove("active"));
  const hero = document.querySelector("#article-hero");
  hero.classList.toggle("has-mark", Boolean(page.mark));
  hero.innerHTML = `${page.mark ? '<img src="/assets/bookinator.svg" alt="">' : ""}<p class="context">${page.kicker}</p><h1>${page.title}</h1><p>${page.intro}</p>`;
  const tabs = document.querySelector("#article-tabs");
  tabs.innerHTML = Object.entries(page.tabs).map(([key, [label]]) => `<button type="button" data-article-tab="${key}"${key === activeTab ? ' aria-current="page"' : ""}>${label}</button>`).join("");
  document.querySelector("#article-body").innerHTML = page.tabs[activeTab][1];
  if (collection === "roadmap") installRoadmapLedger();
  tabs.querySelectorAll("[data-article-tab]").forEach((button) => button.addEventListener("click", () => {
    location.hash = `${collection}/${button.dataset.articleTab}`;
  }));
  document.querySelectorAll(".footer-links a").forEach((link) => {
    if (link.dataset.page === collection) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  });
  document.title = `${page.title} · Bookinator`;
  scrollTo({top: 0, behavior: "auto"});
}

function roadmapRating(value, kind) {
  const labels = kind === "ease" ? ["", "Moonshot", "Hard", "Moderate", "Reachable", "Near"] : ["", "Niche", "Useful", "Strong", "Major", "Transformative"];
  return `<span class="roadmap-rating ${kind}" aria-label="${escapeHtml(labels[value])}: ${value} out of 5"><i style="--rating:${value}"></i><b>${escapeHtml(labels[value])}</b><small>${value}/5</small></span>`;
}

function installRoadmapLedger() {
  const ledger = document.querySelector("[data-roadmap-ledger]");
  if (!ledger) return;
  const columns = [
    {key: "name", label: "Name", first: "asc"},
    {key: "description", label: "Description", first: "asc"},
    {key: "tags", label: "Tags", first: "asc"},
    {key: "ease", label: "Ease", first: "desc"},
    {key: "impact", label: "Impact", first: "desc"},
    {key: "payoff", label: "Payoff", first: "desc"},
  ];
  let sortKey = "payoff";
  let sortDirection = "desc";
  let query = "";
  const selectedTags = new Set();
  const tags = [...new Set(roadmapItems.flatMap((item) => item.tags))].sort((left, right) => left.localeCompare(right));
  const compare = (left, right) => {
    const a = sortKey === "tags" ? left.tags.join(" ") : left[sortKey];
    const b = sortKey === "tags" ? right.tags.join(" ") : right[sortKey];
    const result = typeof a === "number" ? a - b : String(a).localeCompare(String(b));
    return (sortDirection === "asc" ? result : -result) || right.payoff - left.payoff || left.name.localeCompare(right.name);
  };
  const render = () => {
    const headings = columns.map((column) => `<th scope="col" aria-sort="${column.key === sortKey ? (sortDirection === "asc" ? "ascending" : "descending") : "none"}"><button type="button" data-roadmap-sort="${column.key}" data-sort-first="${column.first}">${column.label}<i aria-hidden="true">${column.key === sortKey ? (sortDirection === "asc" ? "↑" : "↓") : "↕"}</i></button></th>`).join("");
    const rows = [...roadmapItems].sort(compare).map((item, index) => `<tr data-roadmap-row data-roadmap-search="${escapeHtml(`${item.name} ${item.description} ${item.tags.join(" ")}`.toLocaleLowerCase())}" data-roadmap-tags="${escapeHtml(item.tags.join("|"))}"><td><span class="roadmap-rank" aria-label="Current rank ${index + 1}">${index + 1}</span></td><th scope="row" class="roadmap-name"><strong>${escapeHtml(item.name)}</strong></th><td class="roadmap-description">${escapeHtml(item.description)}</td><td><div class="roadmap-tags">${item.tags.map((tag) => `<span>${escapeHtml(tag)}</span>`).join("")}</div></td><td>${roadmapRating(item.ease, "ease")}</td><td>${roadmapRating(item.impact, "impact")}</td><td><span class="roadmap-payoff"><strong>${item.payoff}</strong><small>of 25</small></span></td></tr>`).join("");
    const tagButtons = tags.map((tag) => `<button type="button" data-roadmap-tag="${escapeHtml(tag)}" aria-pressed="${selectedTags.has(tag)}">${escapeHtml(tag)}</button>`).join("");
    ledger.innerHTML = `<header><div><h2>Roadmap ledger</h2><p><span data-roadmap-count>${roadmapItems.length}</span> of ${roadmapItems.length} capabilities · sorted by ${escapeHtml(columns.find((column) => column.key === sortKey)?.label || sortKey).toLocaleLowerCase()}</p></div><span class="roadmap-formula">Payoff = ease × impact</span></header><div class="roadmap-filters"><label class="roadmap-search"><span aria-hidden="true">⌕</span><span class="sr-only">Search the roadmap</span><input type="search" data-roadmap-search value="${escapeHtml(query)}" placeholder="Search names, descriptions, and tags" autocomplete="off"></label><div class="roadmap-tag-picker" role="group" aria-label="Filter roadmap by tag"><span>Tags</span><div>${tagButtons}</div></div><button class="roadmap-clear" type="button" data-roadmap-clear${query || selectedTags.size ? "" : " hidden"}>Clear filters</button></div><p class="roadmap-filter-empty" data-roadmap-empty hidden>No roadmap capabilities match these filters. Clear a tag or try a broader search.</p><div class="roadmap-table-wrap"><table class="roadmap-table"><colgroup><col class="roadmap-rank-column"><col class="roadmap-name-column"><col class="roadmap-description-column"><col class="roadmap-tags-column"><col class="roadmap-rating-column"><col class="roadmap-rating-column"><col class="roadmap-payoff-column"></colgroup><thead><tr><th scope="col" class="roadmap-rank-heading">#</th>${headings}</tr></thead><tbody>${rows}</tbody></table></div>`;
    const applyFilters = () => {
      let visible = 0;
      ledger.querySelectorAll("[data-roadmap-row]").forEach((row) => {
        const rowTags = new Set((row.dataset.roadmapTags || "").split("|").filter(Boolean));
        const matchesQuery = !query || row.dataset.roadmapSearch.includes(query);
        const matchesTags = !selectedTags.size || [...selectedTags].some((tag) => rowTags.has(tag));
        row.hidden = !(matchesQuery && matchesTags);
        if (!row.hidden) visible += 1;
      });
      ledger.querySelector("[data-roadmap-count]").textContent = visible.toLocaleString();
      ledger.querySelector("[data-roadmap-empty]").hidden = visible !== 0;
      ledger.querySelector("[data-roadmap-clear]").hidden = !query && !selectedTags.size;
    };
    ledger.querySelectorAll("[data-roadmap-sort]").forEach((button) => button.addEventListener("click", () => {
      const nextKey = button.dataset.roadmapSort;
      sortDirection = sortKey === nextKey ? (sortDirection === "asc" ? "desc" : "asc") : button.dataset.sortFirst;
      sortKey = nextKey;
      render();
    }));
    const search = ledger.querySelector("[data-roadmap-search]");
    search.addEventListener("input", () => { query = search.value.trim().toLocaleLowerCase(); applyFilters(); });
    ledger.querySelectorAll("[data-roadmap-tag]").forEach((button) => button.addEventListener("click", () => {
      const tag = button.dataset.roadmapTag;
      if (selectedTags.has(tag)) selectedTags.delete(tag);
      else selectedTags.add(tag);
      ledger.querySelectorAll("[data-roadmap-tag]").forEach((candidate) => candidate.setAttribute("aria-pressed", String(selectedTags.has(candidate.dataset.roadmapTag))));
      applyFilters();
    }));
    ledger.querySelector("[data-roadmap-clear]").addEventListener("click", () => { query = ""; selectedTags.clear(); render(); ledger.querySelector("[data-roadmap-search]").focus(); });
    applyFilters();
  };
  render();
}

function formatPipelineTime(value) {
  if (!value) return "Not yet";
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? value : date.toLocaleString();
}

function formatEta(seconds) {
  if (!Number.isFinite(seconds) || seconds <= 0) return "Estimating after the first completed chapter";
  const minutes = Math.max(1, Math.round(seconds / 60));
  if (minutes < 60) return `About ${minutes} minute${minutes === 1 ? "" : "s"} remaining`;
  const hours = Math.floor(minutes / 60);
  const remainder = minutes % 60;
  return `About ${hours}h${remainder ? ` ${remainder}m` : ""} remaining`;
}

function formatCompactEta(seconds) {
  if (!Number.isFinite(seconds) || seconds <= 0) return "Estimating ETA";
  const minutes = Math.max(1, Math.round(seconds / 60));
  if (minutes < 60) return `~${minutes}m left`;
  const hours = Math.floor(minutes / 60);
  const remainder = minutes % 60;
  return `~${hours}h${remainder ? ` ${remainder}m` : ""} left`;
}

function etaBasis(progress) {
  if (!progress.etaSampleSize) return "Waiting for one timed chapter";
  const average = Math.max(1, Math.round(progress.averageChapterSeconds / 60));
  return `${progress.etaSampleSize} recent ${progress.etaSampleSize === 1 ? "chapter" : "chapters"} averaged ${average}m · ${progress.remainingChapters} remaining`;
}

function formatRunDuration(seconds, status = "pending") {
  if (seconds === null || seconds === undefined || seconds === "") return status === "running" ? "In progress" : "Not recorded";
  const value = Number(seconds);
  if (!Number.isFinite(value) || value < 0) return status === "running" ? "In progress" : "Not recorded";
  const rounded = Math.round(value);
  if (rounded < 60) return `${rounded} second${rounded === 1 ? "" : "s"}`;
  const units = [[86400, "d"], [3600, "h"], [60, "m"], [1, "s"]];
  let remaining = rounded;
  const parts = [];
  for (const [size, suffix] of units) {
    const amount = Math.floor(remaining / size);
    if (amount || parts.length) {
      if (amount) parts.push(`${amount}${suffix}`);
      remaining %= size;
    }
    if (parts.length === 2) break;
  }
  return parts.join(" ");
}

function naturalTimeTicks(minimum, maximum, targetIntervals = 4) {
  const span = Math.max(1, maximum - minimum);
  const candidates = [1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 900, 1800, 3600, 7200, 10800, 21600, 43200, 86400, 172800, 432000, 604800];
  const ideal = span / targetIntervals;
  const step = candidates.find((candidate) => candidate >= ideal) || Math.ceil(ideal / 604800) * 604800;
  const start = Math.floor(minimum / step) * step;
  const end = Math.ceil(maximum / step) * step;
  const ticks = [];
  for (let value = start; value <= end + step * .01; value += step) ticks.push(value);
  return {minimum: start, maximum: Math.max(start + step, end), ticks};
}

function liveDurationMarkup({startedAt = "", completedAt = "", duration = null, status = "pending", baseDuration = 0} = {}) {
  const running = status === "running" && Boolean(startedAt);
  let seconds = running ? Number(baseDuration || 0) + (new Date() - new Date(startedAt)) / 1000 : Number(duration);
  if ((!Number.isFinite(seconds) || seconds < 0) && startedAt && (completedAt || running)) {
    const end = running ? new Date() : new Date(completedAt);
    seconds = (end - new Date(startedAt)) / 1000;
  }
  const label = formatRunDuration(Number.isFinite(seconds) && seconds >= 0 ? seconds : null, status);
  return `<span${running ? ` data-live-duration data-started-at="${escapeHtml(startedAt)}" data-base-seconds="${Number(baseDuration || 0)}"` : ""}>${escapeHtml(label)}${running && label !== "In progress" ? "+" : ""}</span>`;
}

let readingDetailsClock = null;
function startReadingDetailsClock() {
  clearInterval(readingDetailsClock);
  const update = () => document.querySelectorAll("#reading-details-dialog [data-live-duration]").forEach((item) => {
    const elapsed = Number(item.dataset.baseSeconds || 0) + (Date.now() - new Date(item.dataset.startedAt).valueOf()) / 1000;
    if (Number.isFinite(elapsed) && elapsed >= 0) item.textContent = `${formatRunDuration(elapsed, "running")}+`;
  });
  update();
  readingDetailsClock = setInterval(update, 1000);
}

function formatByteSize(bytes) {
  const value = Number(bytes);
  if (!Number.isFinite(value) || value <= 0) return "Size unavailable";
  const units = ["bytes", "KB", "MB", "GB", "TB"];
  let amount = value;
  let unit = 0;
  while (amount >= 1000 && unit < units.length - 1) {
    amount /= 1000;
    unit += 1;
  }
  const displayed = unit === 0 ? Math.round(amount).toLocaleString() : amount >= 100 ? amount.toFixed(0) : amount >= 10 ? amount.toFixed(1) : amount.toFixed(1);
  return `${displayed}${units[unit]}`;
}

function pipelineStageDuration(stage, pipeline) {
  const savedDuration = Number(stage?.durationSeconds);
  if (stage?.durationSeconds !== null && stage?.durationSeconds !== undefined && stage?.durationSeconds !== "" && Number.isFinite(savedDuration) && savedDuration > 0) return savedDuration;
  if (stage.id === "summaries") {
    const durations = (pipeline.chapters || []).map((chapter) => Number(chapter.durationSeconds)).filter((duration) => Number.isFinite(duration) && duration > 0);
    if (durations.length) return durations.reduce((total, duration) => total + duration, 0);
  }
  if (["emotions", "tags", "smells"].includes(stage.id)) {
    const prefix = stage.id === "emotions" ? "emotion" : stage.id === "tags" ? "tag" : "smell";
    const durations = (pipeline.chapters || []).map((chapter) => Number(chapter[`${prefix}DurationSeconds`])).filter((duration) => Number.isFinite(duration) && duration > 0);
    if (durations.length) return durations.reduce((total, duration) => total + duration, 0);
  }
  if (["cumulative-context", "llm-review"].includes(stage.id)) {
    const prefix = stage.id === "cumulative-context" ? "context" : "llmReview";
    const durations = (pipeline.chapters || []).map((chapter) => Number(chapter[`${prefix}DurationSeconds`])).filter((duration) => Number.isFinite(duration) && duration > 0);
    if (durations.length) return durations.reduce((total, duration) => total + duration, 0);
  }
  if (stage.id === "dossiers") {
    const durations = (pipeline.chunks || []).map((chunk) => Number(chunk.dossierDurationSeconds)).filter((duration) => Number.isFinite(duration) && duration > 0);
    if (durations.length) return durations.reduce((total, duration) => total + duration, 0);
  }
  if (stage.startedAt && stage.completedAt) {
    const elapsed = (new Date(stage.completedAt) - new Date(stage.startedAt)) / 1000;
    if (Number.isFinite(elapsed) && elapsed >= 0) return elapsed;
  }
  return null;
}

function pipelineStageFailures(stage, pipeline) {
  if (Array.isArray(stage.failures)) return stage.failures;
  if (stage.id === "summaries") return (pipeline.chapters || []).filter((chapter) => chapter.status === "failed").map((chapter) => `${displayHeading(chapter.title) || "Chapter"}: ${chapter.error || "The summary failed."}`);
  if (["emotions", "tags", "smells"].includes(stage.id)) {
    const prefix = stage.id === "emotions" ? "emotion" : stage.id === "tags" ? "tag" : "smell";
    return (pipeline.chapters || []).filter((chapter) => chapter[`${prefix}Status`] === "failed").map((chapter) => `${displayHeading(chapter.title) || "Chapter"}: ${chapter[`${prefix}Error`] || `The ${prefix} pass failed.`}`);
  }
  if (stage.id === "dossiers") return (pipeline.chunks || []).filter((chunk) => chunk.dossierStatus === "failed").map((chunk) => `${displayHeading(chunk.chapterLabel) || "Chapter"}, chunk ${chunk.chunkInChapter || 1}: ${chunk.dossierError || "The dossier failed."}`);
  if (stage.id === "cumulative-context") return (pipeline.chapters || []).filter((chapter) => chapter.contextStatus === "failed").map((chapter) => `${displayHeading(chapter.title) || "Chapter"}: ${chapter.contextError || "The context checkpoint failed."}`);
  if (stage.id === "llm-review") return (pipeline.chapters || []).filter((chapter) => chapter.llmReviewStatus === "failed").map((chapter) => `${displayHeading(chapter.title) || "Chapter"}: ${chapter.llmReviewError || "The machine review failed."}`);
  if (stage.id === "questions") return pipeline.questionTracker?.status === "failed" ? [pipeline.questionTracker.error || "Question reconciliation failed."] : [];
  if (stage.id === "structure") return pipeline.chapterMapWarnings || [];
  return stage.error ? [stage.error] : [];
}

function pipelineStageScope(stage, pipeline, book) {
  if (stage.scope) return stage.scope;
  if (stage.id === "source") return book.sourceFilename || "Saved manuscript";
  if (stage.id === "extraction") return countedLabel(pipeline.manuscriptMetrics?.pageCount || 0, "manuscript page");
  if (stage.id === "structure") return countedLabel(pipeline.chapters?.length || 0, "detected section");
  if (stage.id === "chapter-archive") return `${Number(pipeline.chapterArchive?.count || 0).toLocaleString()} saved objects · ${pipeline.chapterArchive?.relativePath || "location not recorded"}`;
  if (stage.id === "chunking") return `${Number(pipeline.chunkArchive?.count || pipeline.chunks?.length || 0).toLocaleString()} source chunks · ${pipeline.chunkArchive?.relativePath || "location not recorded"}`;
  if (stage.id === "summaries") return `${pipeline.progress?.completed || 0} of ${pipeline.progress?.total || 0} manuscript summaries complete`;
  if (stage.id === "emotions") return `${pipeline.emotionProgress?.completed || 0} of ${pipeline.emotionProgress?.total || 0} manuscript emotion records complete`;
  if (stage.id === "tags") return `${pipeline.tagProgress?.completed || 0} of ${pipeline.tagProgress?.total || 0} manuscript tag records complete`;
  if (stage.id === "smells") return `${pipeline.smellProgress?.completed || 0} of ${pipeline.smellProgress?.total || 0} manuscript smell reviews complete`;
  if (stage.id === "dossiers") return `${pipeline.dossierProgress?.completed || 0} of ${pipeline.dossierProgress?.total || 0} manuscript dossiers complete`;
  if (stage.id === "cumulative-context") return `${pipeline.contextProgress?.completed || 0} of ${pipeline.contextProgress?.total || 0} cumulative checkpoints cached`;
  if (stage.id === "llm-review") return `${pipeline.llmReviewProgress?.completed || 0} of ${pipeline.llmReviewProgress?.total || 0} chapter reviews complete`;
  if (stage.id === "whole-book-llm-review") return pipeline.wholeBookLlmReview?.status === "complete" ? "Whole-book editorial synthesis complete" : "Synthesizes every current chapter review";
  if (stage.id === "questions") {
    const items = pipeline.questionTracker?.items || [];
    const resolved = items.filter((item) => item.status === "resolved").length;
    return items.length ? `${items.length.toLocaleString()} grouped questions · ${resolved.toLocaleString()} resolved` : "Whole-book question and payoff reconciliation";
  }
  if (stage.id === "connections") {
    const complete = (pipeline.chunks || []).filter((chunk) => chunk.dossierStatus === "complete").length;
    const total = (pipeline.chunks || []).length;
    return `${complete.toLocaleString()} of ${total.toLocaleString()} dossier chunks compared`;
  }
  return "This book";
}

function visiblePipelineStages(pipeline) {
  const stages = [...(pipeline.stages || [])].filter((stage) => !["questions", "inferences", "prose"].includes(String(stage.id || "").toLocaleLowerCase()) && String(stage.label || "").toLocaleLowerCase() !== "prose");
  const signoff = pipeline.reviewerSignoff || {};
  const signed = signoff.status === "complete";
  stages.push({
    id: "reviewer-signoff",
    label: "Reviewer sign-off",
    status: signed ? "complete" : "pending",
    completedAt: signed ? signoff.completedAt : "",
    workspaceTab: "reviewer",
    method: "Human review gate",
    dependsOn: ["inferences"],
    detail: signed
      ? `Signed off by ${signoff.reviewerName || "the reviewer"}.`
      : "The saved analysis is ready, but a reviewer must sign off before the pipeline is complete.",
  });
  return stages;
}

function pipelineProgressWithReviewer(pipeline) {
  const progress = pipeline.pipelineProgress || {completed: 0, total: 0, percent: 0, etaSeconds: null};
  const machineCompleted = Number(progress.completed || 0);
  const machineTotal = Number(progress.total || 0);
  const reviewerComplete = pipeline.reviewerSignoff?.status === "complete";
  const completed = machineCompleted + Number(reviewerComplete);
  const total = machineTotal + 1;
  const machineDone = machineTotal > 0 && machineCompleted >= machineTotal;
  return {
    ...progress,
    completed,
    total,
    percent: total ? Math.round(completed / total * 100) : 0,
    etaLabel: machineDone && !reviewerComplete ? "Waiting for reviewer sign-off" : progress.etaLabel,
    basisLabel: `${progress.basisLabel || "Saved analysis steps"} · reviewer sign-off`,
  };
}

function pipelineStageDetails(stage, pipeline, book) {
  const status = stage.status || "pending";
  const failures = pipelineStageFailures(stage, pipeline);
  const dependencies = (stage.dependsOn || []).map((dependency) => (pipeline.stages || []).find((candidate) => candidate.id === dependency)?.label || dependency);
  const rows = [
    ["Status", status],
    ["Started", formatPipelineTime(stage.startedAt)],
    ["Finished", formatPipelineTime(stage.completedAt)],
    ["Processing time", liveDurationMarkup({startedAt: stage.startedAt, completedAt: stage.completedAt, duration: status === "running" ? null : pipelineStageDuration(stage, pipeline), status}), true],
    ["Model", stage.model || "No model used"],
    ["Scope", pipelineStageScope(stage, pipeline, book)],
    ["Depends on", dependencies.length ? dependencies.join(", ") : "No earlier pipeline step"],
    ["Run notes", stage.detail || "No run notes were recorded."],
  ];
  if (stage.id === "source") {
    rows.splice(2, 0, ["Format", stage.sourceFormat || book.sourceFormat || "Not recorded"], ["File size", formatByteSize(stage.sourceSizeBytes || book.sourceSizeBytes)]);
  }
  return `${failures.length ? `<section class="pipeline-stage-errors"><h3>Saved diagnostics · ${failures.length} ${failures.length === 1 ? "issue" : "issues"}</h3><ul>${failures.map((failure) => `<li>${escapeHtml(failure)}</li>`).join("")}</ul></section>` : ""}<section class="analysis-run-details pipeline-stage-run-details"><h3>Step record</h3><dl>${rows.map(([label, value, html]) => `<dt>${escapeHtml(label)}</dt><dd>${html ? value : escapeHtml(value)}</dd>`).join("")}</dl></section>`;
}

function pipelineStageInspectorTarget(stage, pipeline) {
  if (stage.inspectorKind && stage.inspectorId != null) return {kind: stage.inspectorKind, itemId: String(stage.inspectorId)};
  const chapterTargets = {
    summaries: {kind: "summary", status: "status", completed: "completedAt"},
    emotions: {kind: "emotion", status: "emotionStatus", completed: "emotionCompletedAt"},
    tags: {kind: "tag", status: "tagStatus", completed: "tagCompletedAt"},
    smells: {kind: "smell", status: "smellStatus", completed: "smellCompletedAt"},
    "cumulative-context": {kind: "context", status: "contextStatus", completed: "contextCompletedAt"},
    "llm-review": {kind: "llm-review", status: "llmReviewStatus", completed: "llmReviewCompletedAt"},
  };
  const chapterTarget = chapterTargets[stage.id];
  const newestInspectable = (items, target, sequenceKey = "sequence") => {
    const candidates = items.filter((item) => ["running", "complete", "failed"].includes(String(item[target.status] || "")));
    candidates.sort((left, right) => {
      const leftRunning = left[target.status] === "running" ? 1 : 0;
      const rightRunning = right[target.status] === "running" ? 1 : 0;
      if (leftRunning !== rightRunning) return rightRunning - leftRunning;
      const byTime = String(right[target.completed] || "").localeCompare(String(left[target.completed] || ""));
      return byTime || Number(right[sequenceKey] || 0) - Number(left[sequenceKey] || 0);
    });
    return candidates[0];
  };
  if (chapterTarget) {
    const chapter = newestInspectable(pipeline.chapters || [], chapterTarget);
    if (chapter?.sequence) return {kind: chapterTarget.kind, itemId: String(chapter.sequence)};
  }
  if (stage.id === "dossiers") {
    const target = {kind: "dossier", status: "dossierStatus", completed: "dossierCompletedAt"};
    const chunk = newestInspectable(pipeline.chunks || [], target);
    if (chunk?.sequence) return {kind: target.kind, itemId: String(chunk.sequence)};
  }
  const wholeBookTargets = {
    "whole-summary": "whole-summary",
    "whole-dossier": "whole-dossier",
    "whole-book-llm-review": "whole-llm-review",
  };
  if (wholeBookTargets[stage.id]) return {kind: wholeBookTargets[stage.id], itemId: "all"};
  return {kind: "stage", itemId: stage.id};
}

function stageMarkup(stage, pipeline, book, openRows = new Set(), inferenceChild = false) {
  const status = stage.status || "pending";
  const inspect = stage.id === "structure"
    ? '<button class="stage-review-button" data-open-chapter-map type="button">Review headings</button>'
    : stage.workspaceTab
      ? `<button class="stage-review-button" data-open-pipeline-tab="${escapeHtml(stage.workspaceTab)}" type="button">Inspect result</button>`
      : "";
  const statusLabel = status === "pending" ? "Waiting" : status;
  const isSource = stage.id === "source";
  const sourceMetadata = isSource ? `<span class="pipeline-source-facts"><span>${escapeHtml(stage.sourceFormat || book.sourceFormat || "FILE")}</span><span>${escapeHtml(formatByteSize(stage.sourceSizeBytes || book.sourceSizeBytes))}</span></span>` : "";
  const download = isSource && stage.downloadUrl ? `<a class="pipeline-source-download" href="${escapeHtml(stage.downloadUrl)}" download><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3v12m-5-5 5 5 5-5M5 20h14"/></svg><span>Download</span></a>` : "";
  const statusControl = analysisStatusControl({
    status,
    label: statusLabel,
    title: `Show status, inputs, and outputs for ${stage.label || stage.id}`,
    trigger: "stage",
  });
  const inspector = pipelineStageInspectorTarget(stage, pipeline);
  return `<article class="pipeline-stage ${escapeHtml(status)}${isSource ? " source-document-stage" : ""}${inferenceChild ? " inference-algorithm" : ""}${stage.elementary ? " pipeline-elementary-task" : ""}" data-pipeline-stage="${escapeHtml(stage.actionStageId || stage.id)}"${stage.taskId ? ` data-pipeline-task="${escapeHtml(stage.taskId)}"` : ""} data-inspector-kind="${escapeHtml(inspector.kind)}" data-inspector-id="${escapeHtml(inspector.itemId)}"><span class="stage-mark">${status === "complete" ? "✓" : status === "running" ? "↻" : ["failed", "warning"].includes(status) ? "!" : status === "blocked" ? "—" : "·"}</span><div class="pipeline-stage-copy"><span class="pipeline-stage-identity"><strong>${escapeHtml(stage.label || stage.id)}</strong><p>${escapeHtml(isSource ? (stage.sourceFilename || book.sourceFilename || stage.detail) : (stage.detail || "Waiting for the previous stage."))}</p><span class="pipeline-stage-meta"><small>${stage.method ? `${escapeHtml(stage.method)} · ` : stage.model ? `Model: ${escapeHtml(stage.model)} · ` : ""}${stage.completedAt ? `Finished ${escapeHtml(formatPipelineTime(stage.completedAt))}` : stage.startedAt ? `Started ${escapeHtml(formatPipelineTime(stage.startedAt))}` : escapeHtml(statusLabel)}</small>${inspect}</span></span>${sourceMetadata}</div><span class="pipeline-stage-reporting">${download}${statusControl}</span><template class="pipeline-stage-details-template">${pipelineStageDetails(stage, pipeline, book)}</template></article>`;
}

function chapterPipelineLedger(pipeline, book, openRows = new Set()) {
  const chapters = pipeline.chapters || [];
  if (!chapters.length) return "";
  const stageRecords = Object.fromEntries((pipeline.stages || []).map((stage) => [stage.id, stage]));
  const definitions = [
    {id: "summaries", label: "Summary", status: "status", model: "model", started: "startedAt", completed: "completedAt", duration: "durationSeconds", error: "error", inspector: "summary"},
    {id: "dossiers", label: "Dossier", collection: "chunks", status: "dossierStatus", model: "dossierModel", started: "dossierStartedAt", completed: "dossierCompletedAt", duration: "dossierDurationSeconds", error: "dossierError", inspector: "dossier"},
    {id: "llm-review", label: "LLM Review", status: "llmReviewStatus", model: "llmReviewModel", started: "llmReviewStartedAt", completed: "llmReviewCompletedAt", duration: "llmReviewDurationSeconds", error: "llmReviewError", inspector: "llm-review", optional: true},
    {id: "cumulative-context", label: "Context", status: "contextStatus", model: "contextModel", started: "contextStartedAt", completed: "contextCompletedAt", duration: "contextDurationSeconds", error: "contextError", inspector: "context", optional: true},
    {id: "emotions", label: "Emotions", status: "emotionStatus", model: "emotionModel", started: "emotionStartedAt", completed: "emotionCompletedAt", duration: "emotionDurationSeconds", error: "emotionError", inspector: "emotion"},
    {id: "tags", label: "Tags", status: "tagStatus", model: "tagModel", started: "tagStartedAt", completed: "tagCompletedAt", duration: "tagDurationSeconds", error: "tagError", inspector: "tag"},
    {id: "smells", label: "Smells", status: "smellStatus", model: "smellModel", started: "smellStartedAt", completed: "smellCompletedAt", duration: "smellDurationSeconds", error: "smellError", inspector: "smell"},
  ];
  const stageEnabled = (definition) => !definition.optional || Boolean(book.llmReviewEnabled);
  const taskFromRecord = (definition, record, chapter, suffix = "") => {
    const status = record?.[definition.status] || "pending";
    const title = displayHeading(chapter.title) || `Section ${chapter.sequence || chapter.number}`;
    const error = record?.[definition.error];
    return {
      id: definition.id,
      actionStageId: definition.id,
      taskId: `${definition.id}-${record?.sequence || chapter.sequence || chapter.number}${suffix}`,
      elementary: true,
      label: definition.label,
      detail: definition.collection ? `Chunk ${record?.chunkInChapter || 1} of ${title}` : title,
      status,
      model: record?.[definition.model] || stageRecords[definition.id]?.model || "",
      startedAt: record?.[definition.started],
      completedAt: record?.[definition.completed],
      durationSeconds: record?.[definition.duration],
      scope: definition.collection ? `${title} · chunk ${record?.chunkInChapter || 1}` : title,
      failures: status === "failed" ? [error || `${definition.label} failed for ${title}.`] : [],
      inspectorKind: definition.inspector,
      inspectorId: record?.sequence || chapter.sequence || chapter.number,
    };
  };
  const groups = chapters.map((chapter) => {
    const sequence = Number(chapter.sequence || chapter.number || 0);
    const frontMatter = displayHeading(chapter.title).toLocaleLowerCase() === "front matter";
    const tasks = [];
    definitions.forEach((definition) => {
      if (!stageEnabled(definition) || (frontMatter && !["summaries", "dossiers"].includes(definition.id))) return;
      if (definition.collection === "chunks") {
        (pipeline.chunks || []).filter((chunk) => Number(chunk.chapterSequence || 0) === sequence).forEach((chunk, index) => tasks.push(taskFromRecord(definition, chunk, chapter, `-${index + 1}`)));
      } else {
        tasks.push(taskFromRecord(definition, chapter, chapter));
      }
    });
    const statuses = tasks.map((task) => task.status);
    const status = statuses.includes("running") ? "running" : statuses.includes("failed") ? "failed" : statuses.length && statuses.every((item) => ["complete", "excluded"].includes(item)) ? "complete" : "pending";
    return {chapter, sequence, tasks, status};
  });
  const totals = definitions.filter(stageEnabled).map((definition) => {
    const tasks = groups.flatMap((group) => group.tasks).filter((task) => task.id === definition.id);
    if (!tasks.length) return "";
    const complete = tasks.filter((task) => task.status === "complete").length;
    return `<span><strong>${escapeHtml(definition.label)}</strong><small>${complete.toLocaleString()} of ${tasks.length.toLocaleString()}</small></span>`;
  }).filter(Boolean).join("");
  const rows = groups.map((group) => {
    const heading = displayHeading(group.chapter.title) || `Section ${group.sequence}`;
    const complete = group.tasks.filter((task) => task.status === "complete").length;
    const active = group.tasks.find((task) => task.status === "running");
    const key = `pipeline-chapter-${group.sequence}`;
    const open = openRows.has(key);
    const completedDuration = group.tasks.reduce((total, task) => total + (task.status === "running" ? 0 : Number(task.durationSeconds || 0)), 0);
    const failed = group.tasks.filter((task) => task.status === "failed").length;
    const waiting = Math.max(0, group.tasks.length - complete - failed - Number(Boolean(active)));
    const aggregateStatus = group.status === "failed" ? "failed" : group.status;
    const aggregateLabel = aggregateStatus === "failed" ? "Attention" : aggregateStatus === "pending" ? "Waiting" : signalLabel(aggregateStatus);
    const aggregateDuration = liveDurationMarkup({
      startedAt: active?.startedAt,
      duration: completedDuration,
      status: active ? "running" : aggregateStatus,
      baseDuration: completedDuration,
    });
    const groupDetails = `<section class="analysis-run-details chapter-group-run-details"><h3>Chapter processing total</h3><dl><dt>State</dt><dd>${escapeHtml(aggregateLabel)}</dd><dt>Processing time</dt><dd>${aggregateDuration}</dd><dt>Completed jobs</dt><dd>${complete.toLocaleString()} of ${group.tasks.length.toLocaleString()}</dd><dt>Waiting</dt><dd>${waiting.toLocaleString()}</dd><dt>Needs attention</dt><dd>${failed.toLocaleString()}</dd>${active ? `<dt>Running now</dt><dd>${escapeHtml(active.label)}</dd>` : ""}</dl><p>The total combines the elapsed processing time recorded by the elementary jobs below. Open an individual job to inspect its inputs and outputs.</p></section>`;
    const statusControl = `<button class="chapter-status" data-show-chapter-group-details type="button" title="Show aggregate chapter processing time">${escapeHtml(aggregateLabel)}</button>`;
    return `<details class="pipeline-chapter-group ${escapeHtml(group.status)}" data-analysis-key="${escapeHtml(key)}"${open ? " open" : ""}><summary><span class="pipeline-chapter-number">${escapeHtml(group.sequence)}</span><span><strong>${escapeHtml(heading)}</strong><small>${active ? `${escapeHtml(active.label)} running · ` : ""}${complete.toLocaleString()} of ${group.tasks.length.toLocaleString()} jobs complete</small></span>${statusControl}<span class="pipeline-chapter-disclosure" aria-hidden="true">⌄</span></summary><div class="pipeline-chapter-tasks">${group.tasks.map((task) => stageMarkup(task, pipeline, book, openRows)).join("")}</div><template class="chapter-group-details-template">${groupDetails}</template></details>`;
  }).join("");
  return `<section class="pipeline-chapter-ledger"><header><div><span>Execution order</span><h3>Chapter work</h3><p>Each chapter moves through these jobs before Bookinator advances to the next one.</p></div><div class="pipeline-stage-totals" aria-label="Stage totals">${totals}</div></header>${rows}</section>`;
}

function openChapterGroupDetails(button) {
  const group = button.closest(".pipeline-chapter-group");
  const template = group?.querySelector("template.chapter-group-details-template");
  if (!group || !template) return;
  document.querySelector("#reading-details-context").textContent = "Chapter work";
  document.querySelector("#reading-details-title").textContent = group.querySelector("summary strong")?.textContent || "Chapter processing";
  document.querySelector("#reading-details-subtitle").textContent = "Aggregate elapsed time and job counts";
  document.querySelector("#reading-details-body").innerHTML = template.innerHTML;
  document.querySelector("#refresh-analysis-result").hidden = true;
  document.querySelector("#restart-pipeline-stage").hidden = true;
  configureRunInspector();
  showDialog("reading-details-dialog");
  startReadingDetailsClock();
}

function openPipelineStageDetails(button) {
  const stage = button.closest("[data-pipeline-stage]");
  const template = stage?.querySelector("template.pipeline-stage-details-template");
  if (!stage || !template) return;
  document.querySelector("#reading-details-context").textContent = "Pipeline step";
  document.querySelector("#reading-details-title").textContent = stage.querySelector(".pipeline-stage-copy strong")?.textContent || "Run details";
  document.querySelector("#reading-details-subtitle").textContent = "Run notes, provenance, and processing time";
  document.querySelector("#reading-details-body").innerHTML = template.innerHTML;
  const restart = document.querySelector("#restart-pipeline-stage");
  const actions = {
    summaries: "restart",
    dossiers: "dossier-restart",
    emotions: "emotion-restart",
    tags: "tag-restart",
    smells: "smell-restart",
    questions: "questions",
    "cumulative-context": "cumulative-context",
    "llm-review": "llm-review",
    "whole-book-llm-review": "whole-llm-review",
  };
  const restartable = stage.classList.contains("running") || stage.classList.contains("failed");
  restart.hidden = !restartable || !actions[stage.dataset.pipelineStage];
  restart.textContent = stage.classList.contains("failed") ? "Retry step" : "Restart step";
  restart.dataset.pipelineAction = actions[stage.dataset.pipelineStage] || "";
  document.querySelector("#refresh-analysis-result").hidden = true;
  configureRunInspector({kind: stage.dataset.inspectorKind || "stage", itemId: stage.dataset.inspectorId || stage.dataset.pipelineStage});
  showDialog("reading-details-dialog");
  startReadingDetailsClock();
}

function updateWorkspaceTabProgress(tabs, pipeline, activeTab) {
  const stages = (pipeline.stages || []).filter((stage) => String(stage.id || "").toLocaleLowerCase() !== "prose" && String(stage.label || "").toLocaleLowerCase() !== "prose");
  const stageComplete = (id) => stages.some((stage) => stage.id === id && stage.status === "complete");
  const runningStages = new Set(stages.filter((stage) => stage.status === "running").map((stage) => String(stage.id || "")));
  const chapters = pipeline.chapters || [];
  const chunks = pipeline.chunks || [];
  const chapterSummariesComplete = chapters.length > 0 && chapters.every((chapter) => chapter.status === "complete");
  const chunkDossiersComplete = chunks.length > 0 && chunks.every((chunk) => chunk.dossierStatus === "complete");
  const wholeSummaryComplete = pipeline.wholeBookSummary?.status === "complete" && Boolean(pipeline.wholeBookSummary?.summary);
  const wholeDossierComplete = pipeline.wholeBookDossier?.status === "complete" && Boolean(pipeline.wholeBookDossier?.summary || pipeline.wholeBookDossier?.synopsis || pipeline.wholeBookDossier?.content);
  const reviewerComplete = pipeline.reviewerSignoff?.status === "complete";
  const machinePipelineComplete = stages.length > 0 && stages.every((stage) => stage.status === "complete");
  const complete = {
    pipeline: machinePipelineComplete && reviewerComplete,
    chapters: Boolean(pipeline.chapterMapApproved),
    summaries: (stageComplete("summaries") || chapterSummariesComplete) && wholeSummaryComplete,
    emotions: stageComplete("emotions") || (chapters.length > 0 && chapters.every((chapter) => chapter.emotionStatus === "complete")),
    tags: stageComplete("tags") || (chapters.length > 0 && chapters.every((chapter) => chapter.tagStatus === "complete")),
    smells: stageComplete("smells") || (chapters.length > 0 && chapters.every((chapter) => chapter.smellStatus === "complete")),
    dossiers: (stageComplete("dossiers") || chunkDossiersComplete) && wholeDossierComplete,
    inferences: Array.isArray(pipeline.inferences) && pipeline.inferences.length > 0 && pipeline.inferences.every((inference) => inference.status === "complete"),
    context: stageComplete("cumulative-context") || (chapters.length > 0 && chapters.filter((chapter) => displayHeading(chapter.title).toLocaleLowerCase() !== "front matter").every((chapter) => chapter.contextStatus === "complete")),
    "llm-review": (stageComplete("llm-review") || (chapters.length > 0 && chapters.filter((chapter) => displayHeading(chapter.title).toLocaleLowerCase() !== "front matter").every((chapter) => chapter.llmReviewStatus === "complete"))) && pipeline.wholeBookLlmReview?.status === "complete",
    reviewer: reviewerComplete,
    report: wholeSummaryComplete || chapterSummariesComplete,
    overview: wholeSummaryComplete,
    "chapter-length": chapters.length > 0 && chapters.every((chapter) => Number(chapter.wordCount || 0) > 0),
    "smell-report": (pipeline.chapters || []).some((chapter) => chapter.smellStatus === "complete"),
    "emotion-map": (pipeline.chapters || []).some((chapter) => chapter.emotionStatus === "complete"),
    "tag-report": (pipeline.chapters || []).some((chapter) => chapter.tagStatus === "complete"),
    connections: chunkDossiersComplete,
    questions: (pipeline.questionTracker?.items || []).length > 0 || pipeline.questionTracker?.status === "complete",
    "reviewer-report": (state.reviewerAnnotations.get(state.currentBookId) || []).some((annotation) => annotation.status !== "archived"),
    "llm-review-report": (stageComplete("llm-review") || (chapters.length > 0 && chapters.filter((chapter) => displayHeading(chapter.title).toLocaleLowerCase() !== "front matter").every((chapter) => chapter.llmReviewStatus === "complete"))) && pipeline.wholeBookLlmReview?.status === "complete",
  };
  const running = {
    // Pipeline is the orchestration view, not another unit of work. The actual
    // running stage owns the live indicator; Pipeline keeps only its terminal
    // completion mark once machine work and reviewer sign-off are both done.
    pipeline: false,
    chapters: runningStages.has("structure") || ["preparing", "extraction", "chapter-map"].includes(pipeline.phase),
    summaries: runningStages.has("summaries") || chapters.some((chapter) => chapter.status === "running"),
    dossiers: runningStages.has("dossiers") || chunks.some((chunk) => chunk.dossierStatus === "running"),
    emotions: runningStages.has("emotions") || chapters.some((chapter) => chapter.emotionStatus === "running"),
    tags: runningStages.has("tags") || chapters.some((chapter) => chapter.tagStatus === "running"),
    smells: runningStages.has("smells") || chapters.some((chapter) => chapter.smellStatus === "running"),
    context: runningStages.has("cumulative-context") || chapters.some((chapter) => chapter.contextStatus === "running"),
    "llm-review": runningStages.has("llm-review") || runningStages.has("whole-book-llm-review") || chapters.some((chapter) => chapter.llmReviewStatus === "running") || pipeline.wholeBookLlmReview?.status === "running",
    questions: pipeline.questionTracker?.status === "running",
  };
  tabs.querySelectorAll("[data-book-tab]").forEach((button) => {
    const tab = button.dataset.bookTab;
    button.classList.toggle("is-complete", Boolean(complete[tab]));
    button.classList.toggle("is-running", Boolean(running[tab]));
    button.toggleAttribute("data-complete", Boolean(complete[tab]));
    button.toggleAttribute("data-running", Boolean(running[tab]));
    button.setAttribute("aria-label", `${button.textContent.trim()}${running[tab] ? ", running" : complete[tab] ? ", complete" : ""}${tab === activeTab ? ", current view" : ""}`);
  });
  const currentBook = state.books.find((book) => book.id === state.currentBookId) || {};
  const analysisTabs = workspaceTabsForBook(currentBook, "analysis").filter((tab) => tab !== "pipeline");
  const completedAnalysis = analysisTabs.filter((tab) => complete[tab]).length;
  const analysisStatus = tabs.querySelector('[data-workspace-group-status="analysis"]');
  const runningAnalysis = analysisTabs.find((tab) => running[tab]);
  if (analysisStatus) analysisStatus.textContent = runningAnalysis ? `${workspaceTabs.find((tab) => tab.id === runningAnalysis)?.label || "Analysis"} running` : completedAnalysis === analysisTabs.length ? "Complete" : `${completedAnalysis} of ${analysisTabs.length} complete`;
  tabs.querySelector('[data-workspace-group="analysis"]')?.classList.toggle("is-complete", completedAnalysis === analysisTabs.length);
  const reportTabs = workspaceTabsForBook(currentBook, "explore").filter((tab) => tab !== "report");
  const exploreReady = reportTabs.filter((tab) => complete[tab]).length;
  const exploreComplete = exploreReady === reportTabs.length;
  const exploreStatus = tabs.querySelector('[data-workspace-group-status="explore"]');
  if (exploreStatus) exploreStatus.textContent = exploreComplete ? "Complete" : exploreReady ? `${exploreReady} of ${reportTabs.length} reports ready` : "Builds from analysis";
  const exploreGroup = tabs.querySelector('[data-workspace-group="explore"]');
  exploreGroup?.classList.toggle("has-results", exploreReady > 0);
  exploreGroup?.classList.toggle("is-complete", exploreComplete);
}

function chapterKey(chapter) {
  return `${chapter.pageStart}:${chapter.title}`;
}

function chapterDuration(chapter) {
  if (Number.isFinite(chapter.durationSeconds)) return `${chapter.durationSeconds} seconds`;
  if (chapter.startedAt && chapter.completedAt) {
    const elapsed = Math.round((new Date(chapter.completedAt) - new Date(chapter.startedAt)) / 1000);
    if (Number.isFinite(elapsed) && elapsed >= 0) return `${elapsed} seconds`;
  }
  return chapter.status === "complete" ? "Complete · duration not recorded" : chapter.status === "running" ? "In progress" : "Not complete";
}

function chapterSectionId(index, label) {
  const slug = String(label || "section").toLowerCase().normalize("NFKD").replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") || "section";
  return `chapter-section-${index + 1}-${slug}`;
}

function applyChapterFontScale(value, persist = true) {
  const scale = Math.max(.8, Math.min(1.6, Number(value) || 1));
  const dialog = document.querySelector("#chapter-source-dialog .chapter-source-dialog");
  dialog?.style.setProperty("--chapter-reader-scale", scale.toFixed(1));
  dialog?.style.setProperty("--chapter-reader-font-size", `${(12 * scale).toFixed(1)}px`);
  dialog?.style.setProperty("--chapter-reader-heading-size", `${(20 * scale).toFixed(1)}px`);
  dialog?.style.setProperty("--chapter-reader-marker-size", `${(11 * scale).toFixed(1)}px`);
  dialog?.querySelector('[data-chapter-font="decrease"]')?.toggleAttribute("disabled", scale <= .8);
  dialog?.querySelector('[data-chapter-font="increase"]')?.toggleAttribute("disabled", scale >= 1.6);
  if (persist) localStorage.setItem(chapterFontScaleKey, scale.toFixed(1));
  return scale;
}

function installChapterFontControls() {
  let scale = applyChapterFontScale(localStorage.getItem(chapterFontScaleKey) || 1, false);
  document.querySelectorAll("[data-chapter-font]").forEach((button) => button.addEventListener("click", () => {
    scale = applyChapterFontScale(scale + (button.dataset.chapterFont === "increase" ? .1 : -.1));
  }));
}

function renderChapterSource(chapter) {
  let sectionIndex = 0;
  if (chapter.markdown) {
    return String(chapter.markdown).split(/\n\s*\n+/).map((block) => {
      const value = block.trim();
      if (!value) return "";
      if (/^#\s+/.test(value)) return ""; // The dialog heading already carries H1.
      if (/^##\s+/.test(value)) return `<h2>${escapeHtml(value.replace(/^##\s+/, ""))}</h2>`;
      if (/^###\s+/.test(value)) {
        const label = displayHeading(value);
        return `<h3 class="section-marker" id="${escapeHtml(chapterSectionId(sectionIndex++, label))}" tabindex="-1">${escapeHtml(label)}</h3>`;
      }
      return `<p>${escapeHtml(value.replace(/\s*\n\s*/g, " "))}</p>`;
    }).join("");
  }
  if (chapter.displayBlocks?.length) {
    const label = String(chapter.title || "").trim();
    return chapter.displayBlocks.map((block) => {
      if (block.kind === "heading") {
        if (String(block.text).trim() === label) return "";
        const marker = chapter.sectionMarkers?.includes(block.text);
        return `<h2 class="${marker ? "section-marker" : "chapter-source-subtitle"}"${marker ? ` id="${escapeHtml(chapterSectionId(sectionIndex++, block.text))}" tabindex="-1"` : ""}>${escapeHtml(block.text)}</h2>`;
      }
      return `<p>${escapeHtml(block.text)}</p>`;
    }).join("");
  }
  const label = String(chapter.title || "").trim();
  const chapterTitle = String(chapter.chapterTitle || "").trim();
  const markers = new Set((chapter.sectionMarkers || []).map((value) => String(value).trim()));
  let skippedLabel = false;
  let skippedTitle = false;
  return String(chapter.text || "").split(/\n\s*\n+/).map((block) => block.trim()).filter((block) => block && !/^\d{1,4}$/.test(block)).map((block) => {
    if (!skippedLabel && block === label) {
      skippedLabel = true;
      return "";
    }
    if (!skippedTitle && chapterTitle && block === chapterTitle) {
      skippedTitle = true;
      return `<h2>${escapeHtml(block)}</h2>`;
    }
    if (markers.has(block)) return `<h2 class="section-marker" id="${escapeHtml(chapterSectionId(sectionIndex++, block))}" tabindex="-1">${escapeHtml(block)}</h2>`;
    return `<p>${escapeHtml(block).replace(/\n/g, "<br>")}</p>`;
  }).join("");
}

function emotionPeakSourceMarkup(chapter, focus) {
  const text = String(chapter.text || "");
  const start = Math.max(0, Math.min(text.length, Number(focus.characterStart) || 0));
  const end = Math.max(start, Math.min(text.length, Number(focus.characterEnd) || start));
  const contextStart = Math.max(0, text.lastIndexOf("\n\n", Math.max(0, start - 700)));
  const nextBoundary = text.indexOf("\n\n", Math.min(text.length, end + 700));
  const contextEnd = nextBoundary < 0 ? text.length : nextBoundary;
  const label = emotionPresentation[focus.label]?.[0] || signalLabel(focus.label);
  return `<section class="emotion-source-focus"><header><span aria-hidden="true">${escapeHtml(emotionPresentation[focus.label]?.[2] || "●")}</span><div><strong>${escapeHtml(label)} peak · segment ${Number(focus.sequence).toLocaleString()}</strong><small>${Math.round(Number(focus.score || 0) * 100)}% classifier score · characters ${start.toLocaleString()}–${end.toLocaleString()}</small></div></header><p>Highlighted below is the exact overlapping classifier window. Surrounding text is included for context.</p><pre>${contextStart > 0 ? "…\n\n" : ""}${escapeHtml(text.slice(contextStart, start))}<mark id="emotion-source-peak" tabindex="-1">${escapeHtml(text.slice(start, end))}</mark>${escapeHtml(text.slice(end, contextEnd))}${contextEnd < text.length ? "\n\n…" : ""}</pre></section>`;
}

function sourcePassageMarkup(chapter, focus) {
  const text = String(chapter.text || chapter.markdown || "");
  const start = Math.max(0, Math.min(text.length, Number(focus.characterStart) || 0));
  const end = Math.max(start, Math.min(text.length, Number(focus.characterEnd) || start));
  return `<section class="emotion-source-focus source-passage-focus"><header><span aria-hidden="true">¶</span><div><strong>Source evidence</strong><small>Characters ${start.toLocaleString()}–${end.toLocaleString()} of ${text.length.toLocaleString()}</small></div></header><p>This is the exact source passage behind the finding.</p><pre>${escapeHtml(text.slice(start, end))}</pre></section>`;
}

function chapterTextOverlays(chapter, text) {
  const overlays = [];
  const emotion = chapter?.emotion || {};
  const segments = new Map((emotion.segments || []).map((segment) => [Number(segment.sequence), segment]));
  (emotion.peaks || []).filter((peak) => Number(peak.score) > 0).forEach((peak) => {
    const segment = segments.get(Number(peak.segmentSequence));
    if (!segment) return;
    overlays.push({start: Number(segment.characterStart), type: "emotion", iconKey: peak.label, label: `${emotionPresentation[peak.label]?.[0] || signalLabel(peak.label)} peak`, score: Number(peak.score || 0)});
  });
  (chapter?.tag?.signals || []).filter((signal) => Number(signal.score) > 0).forEach((signal) => {
    (signal.evidence || []).forEach((evidence) => {
      const quote = String(evidence.quote || "").trim();
      if (!quote) return;
      let start = text.indexOf(quote);
      if (start < 0) start = text.toLocaleLowerCase().indexOf(quote.toLocaleLowerCase());
      if (start < 0) return;
      overlays.push({start, type: "tag", iconKey: signal.family, label: `${tagFamilyPresentation[signal.family]?.[0] || signalLabel(signal.family)}: ${signalLabel(signal.id)}`, score: Number(signal.score || 0)});
    });
  });
  return overlays.filter((item) => Number.isFinite(item.start) && item.start >= 0 && item.start <= text.length).sort((left, right) => left.start - right.start);
}

function emotionTextRegions(chapter, text) {
  const regions = (chapter?.emotion?.segments || []).map((segment) => {
    const label = String(segment.winner || "neutral").toLocaleLowerCase();
    return {
      start: Math.max(0, Math.min(text.length, Number(segment.characterStart) || 0)),
      end: Math.max(0, Math.min(text.length, Number(segment.characterEnd) || 0)),
      label,
      score: Number(segment.winnerScore || segment.scores?.[label] || 0),
      color: emotionPresentation[label]?.[1] || emotionPresentation.neutral[1],
    };
  }).filter((region) => region.end > region.start).sort((left, right) => left.start - right.start);
  for (let index = 1; index < regions.length; index += 1) {
    const previous = regions[index - 1];
    const current = regions[index];
    if (current.start < previous.end) {
      const boundary = Math.round((current.start + previous.end) / 2);
      previous.end = boundary;
      current.start = boundary;
    }
  }
  return regions;
}

function annotatedChapterTextMarkup(text, overlays, regions = []) {
  return annotatedChapterTextMarkupWithAnnotations(text, overlays, regions, []);
}

function editorMarkerIcon(kind, key) {
  const paths = {
    editorial: '<path d="M5 15.5 6 12l7.5-7.5 2 2L8 14z"/><path d="m12.5 5.5 2 2M5 17h12"/>', comments: '<path d="M3 4h14v10H8l-4 3v-3H3z"/><path d="M6 8h8M6 11h5"/>', clarity: '<path d="M2.5 10s2.7-4 7.5-4 7.5 4 7.5 4-2.7 4-7.5 4-7.5-4-7.5-4Z"/><circle cx="10" cy="10" r="2"/>', character: '<circle cx="10" cy="6.5" r="2.5"/><path d="M4.5 16c.5-3 2.3-4.5 5.5-4.5s5 1.5 5.5 4.5"/>', continuity: '<path d="M7.5 12.5 6 14a3 3 0 0 1-4-4l2.5-2.5a3 3 0 0 1 4 0M12.5 7.5 14 6a3 3 0 0 1 4 4l-2.5 2.5a3 3 0 0 1-4 0M7 13l6-6"/>', plot: '<circle cx="4" cy="15" r="1.5"/><circle cx="10" cy="5" r="1.5"/><circle cx="16" cy="12" r="1.5"/><path d="M5 13.8 9 6.4m2.2-.4 3.6 4.8"/>', prose: '<path d="M5 4h10M5 8h7M5 12h10M5 16h6"/>', question: '<path d="M7 7a3.2 3.2 0 1 1 4.5 3c-1 .5-1.5 1-1.5 2"/><path d="M10 16h.01"/>', praise: '<path d="m10 2.5 2.2 4.6 5 .7-3.6 3.5.9 5-4.5-2.4-4.5 2.4.9-5-3.6-3.5 5-.7z"/>',
    prose_mode: '<path d="M5 4h9M5 8h6M5 12h9M5 16h5"/>', chapter_function: '<path d="M5 17V3m0 1h9l-2 3 2 3H5"/>', reader_dynamics: '<path d="M3 15V9m5 6V5m5 10V8m4 7V3"/>', narrated_time: '<circle cx="10" cy="10" r="7"/><path d="M10 6v4l3 2"/>', viewpoint: '<path d="M2.5 10s2.7-4 7.5-4 7.5 4 7.5 4-2.7 4-7.5 4-7.5-4-7.5-4Z"/><circle cx="10" cy="10" r="2"/>', mood: '<path d="M3 12c2-4 4 4 7 0s5 3 7-1M4 6h.01M9 4h.01M15 6h.01"/>', genre_affinity: '<path d="M3 4.5h5.5A1.5 1.5 0 0 1 10 6v10H4.5A1.5 1.5 0 0 1 3 14.5zm14 0h-5.5A1.5 1.5 0 0 0 10 6v10h5.5a1.5 1.5 0 0 0 1.5-1.5z"/>', theme_topic: '<path d="M4 5h8l4 4-7 7-5-5z"/><circle cx="8" cy="8" r="1"/>',
  };
  const faces = {
    anger: '<path d="m5 7 3 1m7-1-3 1M6 14c2.5-2 5.5-2 8 0"/><circle cx="7" cy="10" r=".7"/><circle cx="13" cy="10" r=".7"/>', disgust: '<path d="M5 7.5 8 7m4 0 3 .5M6 13c2-1 3 1 4 0s2-1 4 0"/><circle cx="7" cy="10" r=".7"/><circle cx="13" cy="10" r=".7"/>', fear: '<circle cx="7" cy="8" r="1"/><circle cx="13" cy="8" r="1"/><ellipse cx="10" cy="13" rx="2" ry="2.5"/>', joy: '<path d="M5.5 11c1 4 8 4 9 0M6 7.5l2 1m6-1-2 1"/>', neutral: '<circle cx="7" cy="8" r=".7"/><circle cx="13" cy="8" r=".7"/><path d="M6.5 13h7"/>', sadness: '<path d="M6 15c2-3 6-3 8 0M6 8l2-1m6 1-2-1"/><path d="M15 10c1 1.3 1 2 0 2.7-1-.7-1-1.4 0-2.7Z"/>', surprise: '<circle cx="7" cy="8" r="1"/><circle cx="13" cy="8" r="1"/><circle cx="10" cy="13" r="2"/>',
  };
  const content = kind === "emotion" ? (faces[key] || faces.neutral) : (paths[key] || paths.editorial);
  return `<svg viewBox="0 0 20 20" aria-hidden="true" focusable="false">${content}</svg>`;
}

function chapterAnalysisControlsMarkup({hasEmotions, hasTags, hasComments}) {
  const emotion = sourceAnalysisPreferences.emotion;
  const tag = sourceAnalysisPreferences.tag;
  return [
    hasEmotions ? `<details class="source-analysis-setting emotion" data-analysis-settings="emotion"><summary aria-label="Emotion overlay settings" title="Emotions">${editorMarkerIcon("emotion", "joy")}<span class="sr-only">Emotions</span></summary><div class="source-analysis-menu"><label class="source-analysis-enabled"><input type="checkbox" data-analysis-enabled${emotion.enabled ? " checked" : ""}> Show emotions</label><label class="source-analysis-enabled neutral"><input type="checkbox" data-analysis-neutral${emotion.neutral ? " checked" : ""}> Include Neutral regions</label><label>Minimum emotion score <output data-analysis-output>${Number(emotion.threshold)}%</output></label><input data-analysis-threshold type="range" min="0" max="100" step="1" value="${Number(emotion.threshold)}"><div class="source-marker-presets"><button type="button" data-analysis-preset="5">Explore 5%</button><button type="button" data-analysis-preset="10">Balanced 10%</button><button type="button" data-analysis-preset="25">Strong 25%</button></div></div></details>` : "",
    hasTags ? `<details class="source-analysis-setting tag" data-analysis-settings="tag"><summary aria-label="Tag overlay settings" title="Tags">${editorMarkerIcon("tag", "theme_topic")}<span class="sr-only">Tags</span></summary><div class="source-analysis-menu"><label class="source-analysis-enabled"><input type="checkbox" data-analysis-enabled${tag.enabled ? " checked" : ""}> Show tag evidence</label><label>Minimum tag score <output data-analysis-output>${Number(tag.threshold)}%</output></label><input data-analysis-threshold type="range" min="0" max="100" step="1" value="${Number(tag.threshold)}"><div class="source-marker-presets"><button type="button" data-analysis-preset="25">Trace 25%</button><button type="button" data-analysis-preset="50">Material 50%</button><button type="button" data-analysis-preset="75">Dominant 75%</button></div></div></details>` : "",
    hasComments ? `<details class="source-analysis-setting comments" data-analysis-comments><summary aria-label="Editor comment display settings" title="Editor comments">${editorMarkerIcon("annotation", "comments")}<span class="sr-only">Editor comments</span></summary><div class="source-analysis-menu"><strong>Show editor comments</strong>${[["all", "Show active comments"], ["hidden", "Hide comments"]].map(([value, label]) => `<label class="source-comments-choice"><input type="radio" name="source-comments-mode" value="${value}" data-analysis-comments-mode${sourceAnalysisPreferences.comments.mode === value ? " checked" : ""}> ${label}</label>`).join("")}</div></details>` : "",
  ].join("");
}

function annotatedChapterTextMarkupWithAnnotations(text, overlays, regions = [], annotations = []) {
  const grouped = new Map();
  overlays.forEach((overlay) => grouped.set(overlay.start, [...(grouped.get(overlay.start) || []), overlay]));

  function markedRange(start, end) {
    const relevantRegions = regions.filter((region) => region.end > start && region.start < end);
    const relevantAnnotations = annotations.filter((annotation) => Number(annotation.characterEnd) > start && Number(annotation.characterStart) < end && annotation.status !== "archived");
    const markerPositions = [...grouped.keys()].filter((position) => position >= start && position < end);
    const boundaries = [...new Set([start, end, ...markerPositions, ...relevantRegions.flatMap((region) => [Math.max(start, region.start), Math.min(end, region.end)]), ...relevantAnnotations.flatMap((annotation) => [Math.max(start, Number(annotation.characterStart)), Math.min(end, Number(annotation.characterEnd))])])].sort((left, right) => left - right);
    return boundaries.slice(0, -1).map((position, index) => {
      const markers = grouped.get(position) || [];
      const annotationMarkers = relevantAnnotations.filter((annotation) => !annotation.transient && Math.max(start, Number(annotation.characterStart)) === position).flatMap((annotation) => annotationCategories(annotation).map((category) => ({type: "annotation", iconKey: category, label: annotationCategoryLabel(category), annotation})));
      const allMarkers = [...annotationMarkers, ...markers];
      const markerMarkup = allMarkers.length ? `<span class="text-signal-markers" contenteditable="false">${allMarkers.map((marker) => {
        if (marker.type === "annotation") return `<span class="text-signal-marker annotation annotation-${escapeHtml(marker.iconKey)}" data-annotation-id="${escapeHtml(marker.annotation.id)}" data-annotation-status="active" role="img" aria-label="${escapeHtml(marker.label)} annotation" title="${escapeHtml(marker.label)} annotation">${editorMarkerIcon("annotation", marker.iconKey)}</span>`;
        const percent = Math.round(marker.score * 100);
        return `<span class="text-signal-marker ${escapeHtml(marker.type)} marker-${escapeHtml(marker.iconKey)}" data-source-marker-type="${escapeHtml(marker.type)}" data-source-marker-score="${percent}" role="img" aria-label="${escapeHtml(marker.label)} ${percent} percent" title="${escapeHtml(marker.label)} · ${percent}%">${editorMarkerIcon(marker.type, marker.iconKey)}</span>`;
      }).join("")}</span>` : "";
      const next = boundaries[index + 1];
      const copy = escapeHtml(text.slice(position, next)).replace(/\n/g, "<br>");
      const region = relevantRegions.find((candidate) => position >= candidate.start && position < candidate.end);
      const annotation = relevantAnnotations.find((candidate) => position >= Number(candidate.characterStart) && position < Number(candidate.characterEnd));
      const classes = [];
      const attributes = [`data-source-start="${position}"`, `data-source-end="${next}"`];
      if (region) {
        const percent = Math.round(region.score * 100);
        const label = emotionPresentation[region.label]?.[0] || signalLabel(region.label);
        classes.push("emotion-region", `emotion-${escapeHtml(region.label)}`);
        attributes.push(`data-emotion-region-score="${percent}"`, `style="--emotion-region:${escapeHtml(region.color)}"`, `title="${escapeHtml(label)} region · ${percent}%"`);
      }
      if (annotation) {
        if (annotation.transient) {
          classes.push("machine-lead-range");
          attributes.push('data-machine-lead-focus="true"', `aria-label="Soft editorial lead: ${escapeHtml(annotation.comment || "Machine review lead")}"`);
        } else {
          classes.push("human-annotation-range", "annotation-active");
          attributes.push(`data-annotation-id="${escapeHtml(annotation.id)}"`, `aria-label="Editorial annotation: ${escapeHtml(annotation.comment || "Saved note")}"`);
        }
      }
      return `${markerMarkup}<span${classes.length ? ` class="${classes.join(" ")}"` : ""} ${attributes.join(" ")}>${copy}</span>`;
    }).join("");
  }

  const blocks = [...text.matchAll(/\S[\s\S]*?(?=\n\s*\n|$)/g)];
  let lastHeading = "";
  let sectionIndex = 0;
  const markup = blocks.map((match) => {
    const block = match[0].trimEnd();
    const start = match.index;
    const heading = block.match(/^(#{1,6})([\t ]+)([^\n]+)$/);
    if (!heading) return `<p>${markedRange(start, start + block.length)}</p>`;
    const label = heading[3].trim();
    const normalized = label.toLocaleLowerCase();
    if (normalized === lastHeading) return "";
    lastHeading = normalized;
    const contentStart = start + heading[1].length + heading[2].length;
    const content = markedRange(contentStart, contentStart + heading[3].length);
    if (heading[1].length === 1) return `<h2 class="chapter-source-title">${content}</h2>`;
    if (heading[1].length === 2) return `<h2 class="chapter-source-subtitle">${content}</h2>`;
    return `<h3 class="section-marker" id="${escapeHtml(chapterSectionId(sectionIndex++, label))}" tabindex="-1">${content}</h3>`;
  }).join("");
  return `<section class="annotated-source-text"><div class="annotated-source-copy">${markup}</div></section>`;
}

function wireSourceMarkerCutoff(body) {
  const controls = document.querySelector("#chapter-analysis-controls");
  const settings = [...controls.querySelectorAll("[data-analysis-settings]")];
  const commentsSetting = controls.querySelector("[data-analysis-comments]");
  if (!settings.length && !commentsSetting) return;
  const apply = () => {
    settings.forEach((setting) => {
      const kind = setting.dataset.analysisSettings;
      const threshold = Math.max(0, Math.min(100, Number(setting.querySelector("[data-analysis-threshold]")?.value) || 0));
      const enabled = setting.querySelector("[data-analysis-enabled]")?.checked !== false;
      const neutral = setting.querySelector("[data-analysis-neutral]")?.checked !== false;
      sourceAnalysisPreferences[kind] = {...sourceAnalysisPreferences[kind], enabled, threshold, ...(kind === "emotion" ? {neutral} : {})};
      const output = setting.querySelector("[data-analysis-output]");
      if (output) output.value = `${threshold}%`;
      setting.classList.toggle("disabled", !enabled);
      setting.querySelectorAll("[data-analysis-preset]").forEach((button) => button.classList.toggle("selected", Number(button.dataset.analysisPreset) === threshold));
    });
    const emotion = sourceAnalysisPreferences.emotion;
    const tag = sourceAnalysisPreferences.tag;
    body.querySelectorAll("[data-source-marker-score]").forEach((marker) => {
      const preference = marker.dataset.sourceMarkerType === "tag" ? tag : emotion;
      marker.hidden = !preference.enabled || Number(marker.dataset.sourceMarkerScore) < preference.threshold;
    });
    const commentsMode = sourceAnalysisPreferences.comments.mode || "all";
    const commentVisible = () => commentsMode !== "hidden";
    body.querySelectorAll(".text-signal-marker.annotation").forEach((marker) => {
      marker.hidden = !commentVisible(marker.dataset.annotationStatus || "open");
    });
    body.querySelectorAll(".text-signal-markers").forEach((group) => {
      group.hidden = ![...group.querySelectorAll(".text-signal-marker")].some((marker) => !marker.hidden);
    });
    body.querySelectorAll("[data-emotion-region-score]").forEach((region) => {
      region.classList.toggle("below-cutoff", Number(region.dataset.emotionRegionScore) < emotion.threshold);
    });
    const copy = body.querySelector(".annotated-source-copy");
    copy?.classList.toggle("show-emotion-regions", emotion.enabled);
    copy?.classList.toggle("hide-neutral-regions", !emotion.neutral);
    body.querySelectorAll(".human-annotation-range").forEach((range) => range.classList.toggle("annotation-filtered", !commentVisible()));
    saveSourceAnalysisPreferences();
  };
  settings.forEach((setting) => {
    setting.querySelectorAll("input").forEach((input) => input.addEventListener("input", apply));
    setting.querySelectorAll("[data-analysis-preset]").forEach((button) => button.addEventListener("click", () => {
      setting.querySelector("[data-analysis-threshold]").value = button.dataset.analysisPreset;
      apply();
    }));
  });
  commentsSetting?.querySelectorAll("[data-analysis-comments-mode]").forEach((input) => input.addEventListener("change", () => {
    if (!input.checked) return;
    sourceAnalysisPreferences.comments.mode = input.value;
    apply();
  }));
  apply();
}

function normalizedSelectionRange(source, selection, near = 0) {
  const wanted = String(selection || "").replace(/\s+/g, " ").trim();
  if (!wanted) return null;
  let normalized = "";
  const positions = [];
  let whitespace = false;
  for (let index = 0; index < source.length; index += 1) {
    if (/\s/.test(source[index])) {
      if (!whitespace && normalized) {
        normalized += " ";
        positions.push(index);
      }
      whitespace = true;
    } else {
      normalized += source[index];
      positions.push(index);
      whitespace = false;
    }
  }
  const candidates = [];
  let offset = normalized.indexOf(wanted);
  while (offset >= 0) {
    candidates.push(offset);
    offset = normalized.indexOf(wanted, offset + 1);
  }
  if (!candidates.length) return null;
  const chosen = candidates.sort((left, right) => Math.abs((positions[left] || 0) - near) - Math.abs((positions[right] || 0) - near))[0];
  return {start: positions[chosen], end: (positions[chosen + wanted.length - 1] ?? positions[chosen]) + 1};
}

function captureReviewerSelection(body) {
  const selection = window.getSelection();
  const button = document.querySelector("#annotate-selection");
  const setAction = ({disabled, label}) => {
    if (button) { button.disabled = disabled; button.textContent = label; }
  };
  if (!button || !selection || selection.isCollapsed || !body.contains(selection.anchorNode) || !body.contains(selection.focusNode)) {
    state.pendingAnnotationSelection = null;
    setAction({disabled: true, label: "Select text to annotate"});
    return;
  }
  const quote = selection.toString().replace(/^\s+|\s+$/g, "");
  const source = String(state.activeReviewChapter?.chapter?.text || state.activeReviewChapter?.chapter?.markdown || "");
  const anchor = selection.anchorNode?.parentElement?.closest?.("[data-source-start]");
  const located = normalizedSelectionRange(source, quote, Number(anchor?.dataset.sourceStart || 0));
  if (!located || !quote) {
    state.pendingAnnotationSelection = null;
    setAction({disabled: true, label: "Choose text in one chapter"});
    return;
  }
  state.pendingAnnotationSelection = {...located, quote: source.slice(located.start, located.end)};
  const words = quote.trim().split(/\s+/).filter(Boolean).length;
  setAction({disabled: false, label: `Annotate ${words.toLocaleString()} ${words === 1 ? "word" : "words"}`});
}

function annotationCategoryLabel(value) {
  return ({editorial: "Editorial note", clarity: "Clarity", character: "Character", continuity: "Continuity", plot: "Plot", prose: "Prose", question: "Question", praise: "Praise"})[value] || signalLabel(value || "editorial");
}

const annotationCategoryValues = ["editorial", "clarity", "character", "continuity", "plot", "prose", "question", "praise"];

function annotationCategories(annotation = {}) {
  const values = Array.isArray(annotation.categories) ? annotation.categories : [annotation.category || "editorial"];
  return [...new Set(values.filter((value) => annotationCategoryValues.includes(value)))];
}

function annotationCategorySummary(annotation = {}) {
  return annotationCategories(annotation).map(annotationCategoryLabel).join(" + ");
}

function annotationStatusLabel(annotation = {}) {
  return annotation.status === "archived" ? "Archived" : "Active";
}

function annotationPriorityLabel(value) {
  return ({low: "Low", normal: "Normal", high: "Urgent"})[value] || "Normal";
}

function annotationPriorityControl(annotation = {}) {
  const selected = ["low", "normal", "high"].includes(annotation.priority) ? annotation.priority : "normal";
  return `<div class="annotation-priority-control priority-${escapeHtml(selected)}" role="group" aria-label="Priority for this reviewer comment">${["low", "normal", "high"].map((priority) => `<button type="button" data-annotation-priority="${priority}" data-annotation-id="${escapeHtml(annotation.id)}" aria-pressed="${selected === priority}">${annotationPriorityLabel(priority)}</button>`).join("")}</div>`;
}

function annotationCategoryBadgesMarkup(annotation = {}) {
  const categories = annotationCategories(annotation).map((category) => `<span class="reviewer-note-category annotation-${escapeHtml(category)}"><i aria-hidden="true">${editorMarkerIcon("annotation", category)}</i><b>${escapeHtml(annotationCategoryLabel(category))}</b></span>`).join("");
  const origin = annotation.origin?.kind === "llm-review-proposal"
    ? '<span class="reviewer-note-category machine-origin"><i aria-hidden="true">✦</i><b>From machine proposal</b></span>'
    : "";
  return `${categories}${origin}`;
}

function reviewerActionIcon(action) {
  const paths = {
    view: '<path d="M2.5 10s2.8-4.5 7.5-4.5 7.5 4.5 7.5 4.5-2.8 4.5-7.5 4.5S2.5 10 2.5 10Z"/><circle cx="10" cy="10" r="2.25"/>',
    edit: '<path d="M4 14.7 5 11l7.9-7.9 2.9 2.9-7.9 7.9z"/><path d="m11.8 4.2 2.9 2.9M4 16h12"/>',
    archive: '<path d="M4 6h12M7 6V4h6v2m-7 0 1 11h6l1-11M8.5 9.2v4.7m3-4.7v4.7"/>',
    restore: '<path d="M5.5 7H2.8V4.3"/><path d="M3 7a7 7 0 1 1 .2 6.3"/>',
  };
  return `<svg viewBox="0 0 20 20" aria-hidden="true" focusable="false">${paths[action] || paths.view}</svg>`;
}

function reviewerActionButton({action, label, attribute, tone = ""}) {
  return `<button class="annotation-action-button ${escapeHtml(tone)}" type="button" ${attribute}>${reviewerActionIcon(action)}<span>${escapeHtml(label)}</span></button>`;
}

function inlineAnnotationCommentMarkup(annotation = {}) {
  const annotationId = escapeHtml(annotation.id || "");
  return `<div class="inline-annotation-comment" data-annotation-comment="${annotationId}">
    <p data-annotation-comment-text>${escapeHtml(annotation.comment || "")}</p>
    <form data-inline-annotation-form hidden>
      <label><span class="sr-only">Reviewer comment</span><textarea name="comment" rows="4" required maxlength="12000">${escapeHtml(annotation.comment || "")}</textarea></label>
      <p data-inline-annotation-message role="status"></p>
      <footer><button type="button" data-edit-annotation="${annotationId}">Categories and details…</button><span></span><button type="button" data-cancel-inline-annotation>Cancel</button><button class="primary-button" type="submit">Save comment</button></footer>
    </form>
  </div>`;
}

function openAnnotationEditor({bookId, selection = null, annotation = null, afterSave = null, afterDelete = null}) {
  const editing = Boolean(annotation?.id);
  const quote = String(annotation?.quote || selection?.quote || "");
  const selectedCategories = new Set(annotationCategories(annotation || {category: "editorial"}));
  const selectedPriority = annotation?.priority || "normal";
  const dialog = mountStandardDialog({
    id: "annotation-editor-dialog",
    className: "annotation-editor-dialog",
    labelledBy: "annotation-editor-title",
    content: `<header class="dialog-heading"><div><p class="context">Human editorial judgment</p><h2 id="annotation-editor-title">${editing ? "Edit annotation" : "Annotate this passage"}</h2><p>${editing ? "This note remains attached to its original passage." : "The quotation and its source position will be saved with your note."}</p></div></header><blockquote>${escapeHtml(quote)}</blockquote><form data-annotation-form><label>Comment<textarea name="comment" rows="5" required maxlength="12000" placeholder="What should the author understand or reconsider?">${escapeHtml(annotation?.comment || "")}</textarea></label><fieldset class="annotation-choice-field"><legend>Categories <small>Choose every lens that applies</small></legend><div class="annotation-category-choices">${annotationCategoryValues.map((value) => `<label class="annotation-choice-button annotation-category-${value}"><input type="checkbox" name="category" value="${value}"${selectedCategories.has(value) ? " checked" : ""}><span><i aria-hidden="true">${editorMarkerIcon("annotation", value)}</i>${escapeHtml(annotationCategoryLabel(value))}</span></label>`).join("")}</div></fieldset><fieldset class="annotation-choice-field"><legend>Priority <small>Choose one</small></legend><div class="annotation-priority-choices">${["low", "normal", "high"].map((value) => `<label class="annotation-choice-button priority-${value}"><input type="radio" name="priority" value="${value}"${selectedPriority === value ? " checked" : ""}><span>${escapeHtml(annotationPriorityLabel(value))}</span></label>`).join("")}</div></fieldset><p class="annotation-form-message" data-annotation-message role="status"></p><footer>${editing ? '<button class="danger-text-button annotation-delete-button" type="button" data-delete-annotation>Delete permanently</button>' : ""}<span class="annotation-editor-spacer"></span><button type="button" data-cancel-annotation>Cancel</button><button class="primary-button" type="submit">Save annotation</button></footer></form>`,
  });
  dialog.querySelector("[data-cancel-annotation]").addEventListener("click", () => closeDialog("annotation-editor-dialog"));
  dialog.querySelector("[data-delete-annotation]")?.addEventListener("click", async (event) => {
    const button = event.currentTarget;
    const confirmed = await confirmAnnotationDeletion(annotation);
    if (!confirmed) return;
    button.disabled = true;
    try {
      await deleteReviewerAnnotation(bookId, annotation.id);
      invalidateReviewerAnnotations(bookId);
      closeDialog("annotation-editor-dialog");
      if (afterDelete) await afterDelete(annotation);
    } catch (error) {
      button.disabled = false;
      dialog.querySelector("[data-annotation-message]").textContent = error.message || "The annotation could not be deleted.";
    }
  });
  dialog.querySelector("[data-annotation-form]").addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    const submit = form.querySelector('[type="submit"]');
    const message = form.querySelector("[data-annotation-message]");
    const values = new FormData(form);
    const categories = values.getAll("category");
    if (!categories.length) {
      message.textContent = "Choose at least one category.";
      return;
    }
    const payload = {comment: values.get("comment"), categories, priority: values.get("priority")};
    if (!editing) Object.assign(payload, {chapterSequence: state.activeReviewChapter?.sequence, characterStart: selection.start, characterEnd: selection.end, quote: selection.quote});
    submit.disabled = true;
    submit.textContent = "Saving…";
    try {
      const url = `/api/books/${encodeURIComponent(bookId)}/annotations${editing ? `/${encodeURIComponent(annotation.id)}` : ""}`;
      const response = await fetch(url, {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(payload)});
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || "The annotation could not be saved.");
      const savedCategories = annotationCategories(result.annotation || {});
      if (categories.some((category) => !savedCategories.includes(category))) {
        throw new Error("This running Bookinator server predates multi-category annotations. Let the current analysis finish, restart ./bin/serve, then save these categories again.");
      }
      invalidateReviewerAnnotations(bookId);
      closeDialog("annotation-editor-dialog");
      if (afterSave) await afterSave(result.annotation);
    } catch (error) {
      message.textContent = error.message || "The annotation could not be saved.";
      submit.disabled = false;
      submit.textContent = "Save annotation";
    }
  });
}

async function updateReviewerAnnotation(bookId, annotationId, changes) {
  const response = await fetch(`/api/books/${encodeURIComponent(bookId)}/annotations/${encodeURIComponent(annotationId)}`, {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(changes)});
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || "The annotation could not be updated.");
  return result.annotation;
}

async function deleteReviewerAnnotation(bookId, annotationId) {
  const response = await fetch(`/api/books/${encodeURIComponent(bookId)}/annotations/${encodeURIComponent(annotationId)}`, {method: "DELETE"});
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || "The annotation could not be deleted.");
  return result;
}

async function saveReviewerSignoff(bookId, changes) {
  const response = await fetch(`/api/books/${encodeURIComponent(bookId)}/reviewer-signoff`, {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(changes)});
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || "The reviewer sign-off could not be saved.");
  return result.reviewerSignoff;
}

function confirmAnnotationDeletion(annotation = {}) {
  const quote = String(annotation.quote || "").replace(/\s+/g, " ").trim();
  const excerpt = quote.length > 96 ? `${quote.slice(0, 93)}…` : quote;
  return confirmAction({
    context: "Delete human note",
    title: "Delete this note permanently?",
    message: `${excerpt ? `“${excerpt}” will no longer carry this note. ` : ""}The comment will disappear from the reader, Reviewer, Explore, and future exports. This cannot be undone.`,
    acceptLabel: "Delete permanently",
    danger: true,
  });
}

function installReviewerSelection(body) {
  const update = () => captureReviewerSelection(body);
  body.addEventListener("mouseup", update);
  body.addEventListener("keyup", update);
  body.querySelectorAll("[data-annotation-id]").forEach((range) => range.addEventListener("click", () => {
    const annotation = state.activeReviewChapter?.annotations?.find((item) => item.id === range.dataset.annotationId);
    if (!annotation || !state.activeReviewChapter) return;
    const review = state.activeReviewChapter;
    const scrollTop = body.scrollTop;
    openAnnotationEditor({bookId: review.bookId, annotation, afterSave: (saved) => openChapterSource(review.bookId, review.sequence, {kind: "reviewer", annotationId: saved.id, scrollTop}, review.analysisChapter), afterDelete: () => openChapterSource(review.bookId, review.sequence, {kind: "reviewer", scrollTop}, review.analysisChapter)});
  }));
}

async function openChapterSource(bookId, sequence, focus = null, analysisChapter = null) {
  const title = document.querySelector("#chapter-source-title");
  const subtitle = document.querySelector("#chapter-source-subtitle");
  const context = document.querySelector("#chapter-source-context");
  const jumps = document.querySelector("#chapter-source-jumps");
  const body = document.querySelector("#chapter-source-body");
  const analysisControls = document.querySelector("#chapter-analysis-controls");
  title.textContent = "Chapter";
  subtitle.textContent = "";
  context.textContent = "Canonical manuscript Markdown";
  jumps.hidden = true;
  jumps.innerHTML = "";
  body.innerHTML = "<p>Loading chapter…</p>";
  analysisControls.hidden = true;
  analysisControls.innerHTML = "";
  const annotateButton = document.querySelector("#annotate-selection");
  if (annotateButton) annotateButton.hidden = true;
  state.activeReviewChapter = null;
  state.pendingAnnotationSelection = null;
  showDialog("chapter-source-dialog");
  try {
    const response = await fetch(`/api/books/${encodeURIComponent(bookId)}/chapters/${encodeURIComponent(sequence)}/source`);
    const contentType = response.headers.get("content-type") || "";
    if (!contentType.includes("application/json")) throw new Error("Bookinator’s server needs a restart before it can open saved chapter text. Stop ./bin/serve, run it again, then retry.");
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || "Chapter source unavailable.");
    const chapter = result.chapter;
    const sourceBook = state.books.find((item) => item.id === bookId) || {};
    const sourceRange = sourcePageRange(sourceBook, chapter.pageStart, chapter.pageEnd);
    title.textContent = displayHeading(chapter.title) || `Section ${sequence}`;
    subtitle.textContent = [displayHeading(chapter.chapterTitle), sourceRange].filter(Boolean).join(" · ");
    const reviewMode = ["reviewer", "review-candidate"].includes(focus?.kind) || Boolean(focus?.annotationId);
    context.textContent = focus?.kind === "review-candidate"
      ? "Reviewer · Finding highlighted for human judgment"
      : reviewMode ? "Reviewer · Select a passage to annotate" : focus?.kind === "source" ? "Source evidence · Canonical manuscript text" : focus ? "Emotion evidence · Canonical manuscript text" : "Canonical manuscript Markdown · Read only";
    const markers = (chapter.sectionMarkers || []).map(displayHeading).filter(Boolean);
    jumps.innerHTML = markers.length ? `<span>Jump to</span>${markers.map((marker, index) => `<a href="#${escapeHtml(chapterSectionId(index, marker))}" data-chapter-jump="${escapeHtml(chapterSectionId(index, marker))}">${escapeHtml(marker)}</a>`).join("")}` : "";
    jumps.hidden = !markers.length;
    const text = String(chapter.text || chapter.markdown || "");
    const annotations = Array.isArray(result.annotations) ? result.annotations : [];
    let machineLead = null;
    if (reviewMode && focus?.kind === "review-candidate") {
      const quote = String(focus.quote || "").trim();
      const locatedStart = Number.isFinite(Number(focus.characterStart)) ? Number(focus.characterStart) : text.indexOf(quote);
      const locatedEnd = Number.isFinite(Number(focus.characterEnd)) ? Number(focus.characterEnd) : locatedStart + quote.length;
      if (quote && locatedStart >= 0 && locatedEnd > locatedStart) {
        machineLead = {id: "machine-lead-focus", transient: true, characterStart: locatedStart, characterEnd: locatedEnd, comment: focus.comment || "Machine editorial lead", categories: [focus.category || "editorial"], status: "open"};
      }
    }
    const overlays = chapterTextOverlays(analysisChapter, text);
    const regions = emotionTextRegions(analysisChapter, text);
    const visibleAnnotations = annotations.filter((annotation) => annotation.status !== "archived");
    analysisControls.innerHTML = chapterAnalysisControlsMarkup({
      hasEmotions: Boolean(regions.length || overlays.some((item) => item.type === "emotion")),
      hasTags: overlays.some((item) => item.type === "tag"),
      hasComments: reviewMode || Boolean(visibleAnnotations.length),
    });
    analysisControls.hidden = !analysisControls.innerHTML;
    const focusMarkup = focus?.kind === "source" ? sourcePassageMarkup(chapter, focus) : focus && !reviewMode ? emotionPeakSourceMarkup(chapter, focus) : "";
    const renderAnnotations = machineLead ? [...annotations, machineLead] : annotations;
    const overlayMarkup = `${focusMarkup}${focus?.kind === "source" ? "" : (reviewMode || overlays.length || regions.length || renderAnnotations.length ? annotatedChapterTextMarkupWithAnnotations(text, overlays, regions, renderAnnotations) : "")}`;
    const formattedMarkup = renderChapterSource(chapter) || "<p>No extracted text was saved for this chapter.</p>";
    body.innerHTML = overlayMarkup || formattedMarkup;
    wireSourceMarkerCutoff(body);
    if (reviewMode) {
      state.activeReviewChapter = {bookId, sequence: Number(sequence), chapter, analysisChapter, annotations};
      installReviewerSelection(body);
      annotateButton.hidden = false;
      if (machineLead) {
        state.pendingAnnotationSelection = {start: machineLead.characterStart, end: machineLead.characterEnd, quote: text.slice(machineLead.characterStart, machineLead.characterEnd)};
        annotateButton.disabled = false;
        annotateButton.textContent = "Annotate highlighted passage";
      } else {
        annotateButton.disabled = true;
        annotateButton.textContent = "Select text to annotate";
      }
    }
    jumps.querySelectorAll("[data-chapter-jump]").forEach((link) => link.addEventListener("click", (event) => {
      event.preventDefault();
      const target = body.querySelector(`#${CSS.escape(link.dataset.chapterJump)}`);
      target?.scrollIntoView({block: "start", behavior: "smooth"});
      target?.focus({preventScroll: true});
    }));
    if (Number.isFinite(Number(focus?.scrollTop))) {
      const annotation = focus?.annotationId ? body.querySelector(`[data-annotation-id="${CSS.escape(focus.annotationId)}"]`) : null;
      annotation?.classList.add("annotation-focus");
      requestAnimationFrame(() => body.scrollTo({top: Number(focus.scrollTop), behavior: "auto"}));
    } else if (focus?.annotationId) {
      const annotation = body.querySelector(`[data-annotation-id="${CSS.escape(focus.annotationId)}"]`);
      annotation?.scrollIntoView({block: "center", behavior: "smooth"});
      annotation?.classList.add("annotation-focus");
    } else if (machineLead) {
      const lead = body.querySelector('[data-machine-lead-focus="true"]');
      lead?.scrollIntoView({block: "center", behavior: "smooth"});
      lead?.focus?.({preventScroll: true});
    } else if (focus) {
      const peak = body.querySelector("#emotion-source-peak");
      peak?.scrollIntoView({block: "center", behavior: "smooth"});
      peak?.focus({preventScroll: true});
    }
  } catch (error) {
    body.innerHTML = `<p class="pipeline-error">${escapeHtml(error.message || "Chapter source unavailable.")}</p>`;
  }
}

function displayHeading(value) {
  return String(value || "").replace(/^[\u200B-\u200D\uFEFF\s]*#{1,6}[\t ]*/, "").trim();
}

function analysisSectionMarkup({label, icon, tone, items}) {
  if (!items?.length) return "";
  return `<section class="analysis-findings ${escapeHtml(tone)}"><h3 class="analysis-section-heading"><span aria-hidden="true">${escapeHtml(icon)}</span>${escapeHtml(label)}</h3><ul>${items.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul></section>`;
}

function wholeBookDossierMarkup(dossier) {
  const synopsis = dossier.synopsis || dossier.summary || dossier.content || "";
  const sections = [
    {label: "Established facts", icon: "✓", tone: "facts", items: dossier.facts},
    {label: "Events", icon: "↗", tone: "events", items: dossier.events},
    {label: "Entities", icon: "◎", tone: "entities", items: dossier.entities},
    {label: "Locations", icon: "⌖", tone: "locations", items: dossier.locations},
    {label: "Current times", icon: "◷", tone: "timeline", items: dossier.current_times},
    {label: "Questions", icon: "?", tone: "questions", items: dossier.questions},
    {label: "Promises", icon: "◇", tone: "promises", items: dossier.promises},
    {label: "Timeline observations", icon: "↦", tone: "timeline", items: dossier.timeline_observations},
    {label: "Contradictions", icon: "!", tone: "contradictions", items: dossier.contradictions},
  ];
  const populated = sections.filter((section) => section.items?.length);
  return `<div class="chapter-editorial-content whole-book-dossier-content"><section class="dossier-synopsis"><h3>Whole-book synopsis</h3><p>${escapeHtml(synopsis)}</p></section>${populated.length ? `<div class="whole-book-dossier-grid">${populated.map((section) => analysisSectionMarkup(section)).join("")}</div>` : ""}</div>`;
}

function analysisQuestionDetailsMarkup(items, label = "Questions now in play") {
  if (!items?.length) return "";
  return `<section class="analysis-findings question-details"><h3 class="analysis-section-heading"><span aria-hidden="true">?</span>${escapeHtml(label)}</h3><div>${items.map((item) => `<article><header><span>${escapeHtml(signalLabel(item.family || "reader expectation"))}</span>${item.promisesAnswer ? "<strong>Answer promised</strong>" : ""}</header><h4>${escapeHtml(item.question || "")}</h4>${item.whyItMatters ? `<p>${escapeHtml(item.whyItMatters)}</p>` : ""}${item.evidence ? `<blockquote>“${escapeHtml(item.evidence)}”</blockquote>` : ""}</article>`).join("")}</div></section>`;
}

function analysisSectionGroupMarkup({label, icon, tone, groups}) {
  const populated = groups.filter((group) => group.items?.length);
  if (!populated.length) return "";
  return `<section class="analysis-findings grouped ${escapeHtml(tone)}"><h3 class="analysis-section-heading"><span aria-hidden="true">${escapeHtml(icon)}</span>${escapeHtml(label)}</h3>${populated.map((group) => `<div class="analysis-subgroup"><h4>${escapeHtml(group.label)}</h4><ul>${group.items.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul></div>`).join("")}</section>`;
}

function analysisRunDetails({title, model, startedAt, completedAt, duration, status = "pending", inputCharacters, rows = []}) {
  const details = [
    ["Model", model || "Not assigned"],
    ["Started", formatPipelineTime(startedAt)],
    ["Finished", formatPipelineTime(completedAt)],
    ["Duration", liveDurationMarkup({startedAt, completedAt, duration, status}), "html"],
    ["Input", `${Number(inputCharacters || 0).toLocaleString()} characters`],
    ...rows.map((row) => [row.label, row.value, row.code]),
  ];
  return `<section class="analysis-run-details"><h3>${escapeHtml(title)}</h3><dl>${details.map(([label, value, code]) => `<dt>${escapeHtml(label)}</dt><dd>${code === "html" ? value : code ? `<code>${escapeHtml(value)}</code>` : escapeHtml(value)}</dd>`).join("")}</dl></section>`;
}

function chapterMarkup(chapter, openChapters = new Set(), book = {}) {
  const emptyComplete = chapter.status === "complete" && !String(chapter.summary || "").trim();
  const status = emptyComplete ? "failed" : chapter.status || "pending";
  const complete = status === "complete";
  const key = chapterKey(chapter);
  const isOpen = openChapters.has(key);
  const historyCount = chapter.summaryRuns?.length || 0;
  const retryCount = chapter.retryRuns?.length || 0;
  const failures = chapter.failedRuns?.length ? chapter.failedRuns : chapter.latestFailure ? [chapter.latestFailure] : status === "failed" ? [{model: chapter.model, completedAt: chapter.completedAt, error: chapter.error, inputCharacters: chapter.inputCharacters}] : [];
  const failureDiagnostics = failures.length ? `<section class="failure-diagnostics"><header><strong>Failure diagnostics</strong><span>${failures.length} ${failures.length === 1 ? "attempt" : "attempts"}</span></header>${failures.map((failure, index) => `<section><strong>Attempt ${index + 1} · ${escapeHtml(failure.model || "Unknown model")}</strong><dl><dt>Finished</dt><dd>${escapeHtml(formatPipelineTime(failure.completedAt))}</dd><dt>Error</dt><dd>${escapeHtml(failure.error || "Unknown failure")}</dd><dt>Response keys</dt><dd>${failure.responseKeys?.length ? escapeHtml(failure.responseKeys.join(", ")) : "None recorded"}</dd><dt>Input</dt><dd>${failure.inputCharacters || 0} characters</dd></dl>${failure.rawResponse ? `<details><summary>Raw model response</summary><pre>${escapeHtml(failure.rawResponse)}</pre></details>` : '<p>Raw response was not retained by the server that ran this attempt. Restart Bookinator before retrying to capture the next response.</p>'}</section>`).join("")}</section>` : "";
  const historyRows = (chapter.summaryRuns || []).map((run, index) => ({label: `Earlier run ${index + 1}`, value: `${run.model || "Unknown model"} · ${formatPipelineTime(run.completedAt)} · ${run.durationSeconds ?? "?"} seconds`}));
  if (retryCount) historyRows.push({label: "Recovered retries", value: `${retryCount} transient local-model ${retryCount === 1 ? "disconnect" : "disconnects"}`});
  const provenance = analysisRunDetails({title: `Reading details${historyCount ? ` · ${historyCount} earlier ${historyCount === 1 ? "run" : "runs"}` : ""}${retryCount ? ` · recovered after ${retryCount} ${retryCount === 1 ? "retry" : "retries"}` : ""}`, model: chapter.model, startedAt: chapter.startedAt, completedAt: chapter.completedAt, duration: chapter.durationSeconds, status, inputCharacters: chapter.inputCharacters, rows: historyRows});
  const chapterError = emptyComplete ? "The saved model response contained no chapter summary. Restart Bookinator, then Resume to retry this chapter." : chapter.error;
  const chapterQuestions = chapter.questionDetails?.length ? analysisQuestionDetailsMarkup(chapter.questionDetails) : analysisSectionMarkup({label: "Questions now in play", icon: "?", tone: "questions", items: chapter.newQuestions});
  const contents = complete ? `<p>${escapeHtml(chapter.summary)}</p>${analysisSectionMarkup({label: "What this chapter establishes", icon: "✓", tone: "establishes", items: chapter.keyPoints})}${chapterQuestions}` : chapterError ? `<p>This chapter does not have a usable summary. Select <strong>Failed</strong> for the error and attempt history.</p>` : `<p>${chapter.status === "running" ? "This chapter is being read now." : "Haven’t summarized this chapter yet."}</p>`;
  const statusBody = `${chapterError ? `<p class="pipeline-error">${escapeHtml(chapterError)}</p>` : ""}${failureDiagnostics}${provenance}`;
  return analysisDisclosure({status, key, open: isOpen, heading: displayHeading(chapter.title) || `Section ${chapter.number}`, subheading: displayHeading(chapter.chapterTitle), range: sourcePageRange(book, chapter.pageStart, chapter.pageEnd), metrics: chapter, body: contents, statusBody, sourceSequence: chapter.sequence || chapter.number, refreshKind: "summary", refreshId: chapter.sequence || chapter.number});
}

const emotionPresentation = {
  anger: ["Anger", "#c64b43", "⚡"], disgust: ["Disgust", "#748b45", "⊘"], fear: ["Fear", "#7656a8", "△"],
  joy: ["Joy", "#d69a24", "☀"], neutral: ["Neutral", "#7b8798", "○"], sadness: ["Sadness", "#4d78a8", "◇"], surprise: ["Surprise", "#b45b8e", "✦"],
};

const EMOTION_DISTRIBUTION_DISPLAY_THRESHOLD = .05;
const EMOTION_PEAK_DISPLAY_THRESHOLD = .25;
const wholeBookRollupRowLimits = {emotion: 10, tag: 10, smell: 10};
const selectedTagRollupClusters = new Set(["atmosphere", "structure", "experience"]);
let llmReviewScoreSort = "score";

const tagFamilyPresentation = {
  prose_mode: ["Prose mode", "¶"], chapter_function: ["Chapter function", "↗"], reader_dynamics: ["Reader dynamics", "◎"],
  narrated_time: ["Narrated time", "◴"], viewpoint: ["Viewpoint", "◉"], mood: ["Mood", "◒"], genre_affinity: ["Genre affinity", "⌁"], theme_topic: ["Theme topics", "◆"],
};

const tagClusterPresentation = [
  {id: "atmosphere", label: "Atmosphere & meaning", description: "Mood, genre affinity, and thematic concerns", icon: "◆", families: ["mood", "genre_affinity", "theme_topic"]},
  {id: "structure", label: "Structure & perspective", description: "Viewpoint, narrated time, and the chapter’s story function", icon: "◉", families: ["viewpoint", "narrated_time", "chapter_function"]},
  {id: "experience", label: "Experience & momentum", description: "How the prose moves and what it makes the reader track", icon: "↗", families: ["prose_mode", "reader_dynamics"]},
];

const tagLabelOverrides = {
  tension: "Narrative tension",
  tense: "Tense atmosphere",
  dialogue: "Dialogue",
  third_limited: "Third-person limited",
  third_omniscient: "Third-person omniscient",
  first_person: "First person",
  second_person: "Second person",
  chapter_end_propulsion: "Chapter-end propulsion",
  withheld_information: "Withheld information",
  primary_present: "Primary story time",
  objective_external: "Objective viewpoint",
  nonlinear_uncertain: "Uncertain chronology",
  neutral_uncertain: "Neutral or uncertain mood",
};

const tagDescriptions = {
  action: "Physical activity and consequential movement carry much of the chapter.",
  dialogue: "Spoken exchange carries much of the chapter, rather than description or narration.",
  exposition: "Background, explanation, or contextual information occupies a substantial part of the chapter.",
  description: "Sensory or visual description is a major part of how the chapter works.",
  introspection: "Interior thought, memory, or self-examination carries much of the chapter.",
  narrative_summary: "The narrator compresses events or spans time instead of presenting them moment by moment.",
  investigation: "Characters actively seek, test, compare, or connect evidence.",
  orientation: "The chapter locates the reader in a new place, time, situation, or point of view.",
  setup: "The chapter establishes information, relationships, or possibilities intended to matter later.",
  escalation: "Existing conflict, urgency, stakes, or difficulty materially increases.",
  complication: "A new obstacle or consequence makes the current situation harder to resolve.",
  discovery: "A character finds important information through observation or inquiry.",
  revelation: "Important information becomes known to the reader or characters, changing interpretation.",
  confrontation: "Opposed characters or forces meet directly and press their competing goals.",
  relationship_change: "A relationship materially changes in trust, intimacy, power, or allegiance.",
  reversal: "The apparent direction, advantage, or meaning of events changes sharply.",
  setback: "A meaningful goal becomes harder, farther away, or temporarily impossible.",
  payoff: "An earlier promise, question, preparation, or expectation receives a meaningful answer.",
  climax: "Conflict or stakes reach a local or book-level peak.",
  aftermath: "Characters absorb or interpret the consequences of an earlier event.",
  resolution: "The chapter closes important active threads or establishes a durable new state.",
  transition: "The chapter primarily connects larger story movements rather than completing one itself.",
  travel: "Movement between places is a principal function of the chapter.",
  mystery: "Mystery conventions are strongly visible in this chapter; this is a genre affinity, not merely an unanswered question.",
  withheld_information: "Material answers are withheld or complicated, giving the reader something important to solve.",
  suspense: "Anticipated danger or consequential uncertainty creates forward pressure.",
  tension: "Pressure between competing possibilities keeps the reader uncertain about what will happen or what it will cost.",
  stakes: "The chapter makes meaningful consequences of success or failure legible.",
  urgency: "Time pressure or an immediate need makes delay costly.",
  goal_progress: "A character makes measurable progress toward—or away from—an active goal.",
  story_state_change: "The chapter leaves the story in a materially different state than it began.",
  revelation_density: "The chapter delivers important new information at an unusually high rate.",
  causal_importance: "Events here strongly cause or constrain later events.",
  chapter_end_propulsion: "The ending creates a concrete reason to continue: an unresolved action, decision, danger, or question.",
  primary_present: "Events occur in the manuscript's main narrative time, even when written in past tense.",
  flashback: "The narrative dramatizes an earlier event as a scene.",
  remembered_past: "A character or narrator recalls earlier events without fully staging them as a scene.",
  flash_forward: "The narrative moves forward to dramatize a later event.",
  anticipated_future: "Characters imagine, predict, plan, or fear a possible future.",
  time_jump: "The narrative advances or retreats across a meaningful span of time.",
  simultaneous_branch: "The chapter follows events happening alongside another established story thread.",
  dream_or_vision: "A dream, vision, hallucination, or altered perception becomes a narrated event.",
  hypothetical_scene: "The text stages something imagined or conditional rather than an event known to occur.",
  nonlinear_uncertain: "The chapter's chronological position is deliberately or possibly unclear.",
  first_person: "A narrator within the story speaks as “I” or “we.”",
  second_person: "The narration addresses its focal character or reader as “you.”",
  third_limited: "Third-person narration stays largely within one character's perceptions and knowledge.",
  third_omniscient: "The narrator can move beyond any one character's knowledge or interior experience.",
  objective_external: "The narration reports observable action without sustained access to interior thought.",
  single_viewpoint: "One viewpoint controls the chapter.",
  multiple_viewpoints: "The chapter deliberately gives substantial access to more than one viewpoint.",
  viewpoint_shift: "The controlling viewpoint changes intentionally within the chapter.",
  viewpoint_drift_candidate: "The chapter may slip outside its established viewpoint rules; this is a review lead, not a verdict.",
  tense: "The atmosphere feels strained, pressured, or expectant. This describes mood, not narrative stakes.",
  foreboding: "The atmosphere suggests that something harmful or ominous is approaching.",
  ominous: "Details carry a threatening implication even when the danger is not explicit.",
  uncanny: "Something familiar feels subtly wrong, displaced, or difficult to explain.",
  horrific: "Threat, revulsion, violation, or supernatural dread dominates the atmosphere.",
  bleak: "The chapter presents little relief, hope, or possibility of improvement.",
  melancholic: "The atmosphere is shaped by reflective sadness, loss, or longing.",
  intimate: "The chapter feels emotionally close, private, or personally revealing.",
  romantic: "Romantic attraction, longing, or attachment shapes the atmosphere.",
  hopeful: "The chapter sustains credible possibility, recovery, or anticipated improvement.",
  playful: "The atmosphere is light, teasing, inventive, or knowingly mischievous.",
  comic: "Humor is a meaningful part of the chapter's emotional texture.",
  cozy: "Safety, familiarity, community, or comforting routine dominates despite possible conflict.",
  meditative: "The chapter invites sustained reflection more than urgency or action.",
  dreamlike: "The atmosphere feels fluid, associative, surreal, or only partly grounded.",
  wondrous: "Awe, discovery, beauty, or the extraordinary shapes the reader's experience.",
  triumphant: "Achievement, victory, or earned release dominates the emotional direction.",
  frenetic: "Rapid, crowded, or chaotic activity gives the chapter a breathless texture.",
  claustrophobic: "Restriction, confinement, or lack of escape shapes the atmosphere.",
  noir: "Fatalism, moral compromise, secrecy, and danger create a noir-like atmosphere.",
  neutral_uncertain: "No single mood clearly dominates, or the evidence is too mixed to name one confidently.",
};

const tagFamilyDescriptions = {
  prose_mode: "Describes the principal way the chapter delivers its material.",
  chapter_function: "Describes the job this chapter performs in the larger story.",
  reader_dynamics: "Describes the pressure, uncertainty, and forward movement experienced by the reader.",
  narrated_time: "Describes where the chapter sits relative to the main story timeline.",
  viewpoint: "Describes who perceives the chapter and how tightly narration follows that perspective.",
  mood: "Describes the atmosphere the passage is designed to create.",
  genre_affinity: "Describes which genre conventions are especially visible in this chapter; it is not a final classification of the whole book.",
  theme_topic: "Names a recurring subject the chapter engages; it does not claim what the book ultimately argues about it.",
};

function signalLabel(value) {
  const key = String(value || "");
  return tagLabelOverrides[key] || sentenceCaseLabel(key);
}

function signalDescription(id, family = "") {
  return tagDescriptions[id] || `${signalLabel(id)} is part of ${String(tagFamilyPresentation[family]?.[0] || signalLabel(family)).toLocaleLowerCase()}. ${tagFamilyDescriptions[family] || "This tag describes a supported pattern in the chapter."}`;
}

function explainedSignalLabel(id, family = "") {
  const label = signalLabel(id);
  return `<strong class="explained-signal" tabindex="0" data-tooltip-heading="${escapeHtml(label)}" data-tooltip="${escapeHtml(signalDescription(id, family))}">${escapeHtml(label)}<span aria-hidden="true">?</span></strong>`;
}

function emotionResultMarkup(artifact, chapter = {}) {
  const distribution = artifact?.distribution || {};
  const mapLabels = Object.keys(emotionPresentation).filter((label) => Number(distribution[label]) > 0);
  if (!mapLabels.length) return "<p>No emotion scores were returned.</p>";
  const displayedLabels = mapLabels.filter((label) => Number(distribution[label]) >= EMOTION_DISTRIBUTION_DISPLAY_THRESHOLD);
  const segmentPeaks = new Map(mapLabels.map((label) => {
    const segments = artifact.segments || [];
    return [label, segments.reduce((best, segment) => Number(segment.scores?.[label] || 0) > Number(best?.scores?.[label] || 0) ? segment : best, null)];
  }));
  const bar = `<div class="emotion-distribution" role="group" aria-label="Chapter emotion distribution">${mapLabels.map((label) => {
    const presentation = emotionPresentation[label];
    const average = Math.round(Number(distribution[label]) * 100);
    const peakSegment = segmentPeaks.get(label);
    const peakScore = Math.round(Number(peakSegment?.scores?.[label] || 0) * 100);
    const description = `${presentation[0]}: ${average}% chapter average. Strongest passage: ${peakScore}%.`;
    return `<button class="emotion-distribution-region" data-emotion-peak-preview data-chapter-sequence="${Number(chapter.sequence || chapter.number || 0)}" data-character-start="${Number(peakSegment?.characterStart || 0)}" data-character-end="${Number(peakSegment?.characterEnd || 0)}" type="button" style="--emotion:${presentation[1]};width:${Math.max(1, Number(distribution[label]) * 100)}%" aria-label="${escapeHtml(description)}"><span class="emotion-peak-diamond" style="--peak-position:${peakScore}%" aria-hidden="true"></span><span class="emotion-distribution-tooltip" role="tooltip"><i style="--emotion:${presentation[1]}" aria-hidden="true">${presentation[2]}</i><span><strong>${presentation[0]} · ${average}%</strong><small>Strongest passage ${peakScore}%</small><q data-emotion-peak-excerpt>Hover to preview the classifier window.</q></span></span></button>`;
  }).join("")}</div>`;
  const legend = `<div class="emotion-legend">${displayedLabels.map((label) => `<span><i style="--emotion:${emotionPresentation[label][1]}">${emotionPresentation[label][2]}</i><strong>${emotionPresentation[label][0]}</strong><small>${Math.round(Number(distribution[label]) * 100)}%</small></span>`).join("")}</div>`;
  const segments = new Map((artifact.segments || []).map((segment) => [Number(segment.sequence), segment]));
  const peaks = (artifact.peaks || []).filter((peak) => Number(peak.score) >= EMOTION_PEAK_DISPLAY_THRESHOLD).map((peak) => {
    const sequence = Number(peak.segmentSequence || 0);
    const segment = segments.get(sequence) || {};
    const inspect = Number.isFinite(Number(segment.characterStart)) && Number.isFinite(Number(segment.characterEnd))
      ? `<button class="emotion-peak-inspect" data-view-emotion-peak data-chapter-sequence="${Number(chapter.sequence || chapter.number || 0)}" data-segment-sequence="${sequence}" data-emotion-label="${escapeHtml(peak.label)}" type="button">View text</button>`
      : "";
    return `<li><span><strong>${escapeHtml(emotionPresentation[peak.label]?.[0] || signalLabel(peak.label))}</strong> peaks at ${Math.round(Number(peak.score || 0) * 100)}% in segment ${sequence.toLocaleString()}.</span>${inspect}</li>`;
  }).join("");
  const segmentNote = artifact.segments?.length ? `<p class="emotion-segment-note">Segments are paragraph-aware windows of roughly 1,200 characters with one paragraph of overlap, so neighboring peaks may share text.</p>` : "";
  return `${bar}${legend}${peaks ? `<section class="signal-notes emotion-peaks"><h3>Emotional peaks</h3>${segmentNote}<ul>${peaks}</ul></section>` : ""}`;
}

async function hydrateEmotionPeakPreview(button, bookId) {
  if (button.dataset.previewLoaded === "true" || button.dataset.previewLoading === "true") return;
  button.dataset.previewLoading = "true";
  const sequence = button.dataset.chapterSequence;
  const cacheKey = `${bookId}:${sequence}`;
  try {
    let text = chapterSourcePreviewCache.get(cacheKey);
    if (text === undefined) {
      const response = await fetch(`/api/books/${encodeURIComponent(bookId)}/chapters/${encodeURIComponent(sequence)}/source`);
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || "Text preview unavailable.");
      text = String(result.chapter?.text || result.chapter?.markdown || "");
      chapterSourcePreviewCache.set(cacheKey, text);
    }
    const start = Math.max(0, Math.min(text.length, Number(button.dataset.characterStart) || 0));
    const end = Math.max(start, Math.min(text.length, Number(button.dataset.characterEnd) || start));
    const windowText = text.slice(start, end).replace(/\s+/g, " ").trim();
    const excerpt = windowText.length > 280 ? `${windowText.slice(0, 277).trimEnd()}…` : windowText;
    const target = button.querySelector("[data-emotion-peak-excerpt]");
    if (target) target.textContent = excerpt || "No manuscript preview is available for this window.";
    button.dataset.previewLoaded = "true";
  } catch {
    const target = button.querySelector("[data-emotion-peak-excerpt]");
    if (target) target.textContent = "The manuscript preview could not be loaded.";
  } finally {
    delete button.dataset.previewLoading;
  }
}

function authoredSignalChapters(pipeline) {
  return (pipeline.chapters || []).filter((chapter) => displayHeading(chapter.title).toLocaleLowerCase() !== "front matter");
}

function rollupChapterReference(chapter) {
  const heading = displayHeading(chapter.title) || `Chapter ${chapter.number || chapter.sequence}`;
  const title = displayHeading(chapter.chapterTitle);
  return {
    sequence: Number(chapter.sequence || chapter.number || 0),
    number: reportChapterNumber(chapter),
    label: title ? `${heading} · ${title}` : heading,
  };
}

function tagRollupData(pipeline) {
  const chapters = authoredSignalChapters(pipeline);
  const entries = new Map();
  chapters.forEach((chapter) => {
    const seen = new Set();
    (chapter.tag?.signals || []).filter((signal) => Number(signal.score) >= .25).forEach((signal) => {
      const id = String(signal.id || "").trim();
      if (!id || seen.has(id)) return;
      seen.add(id);
      const entry = entries.get(id) || {id, family: signal.family || "other", chapters: [], totalScore: 0, peakScore: 0};
      entry.chapters.push(rollupChapterReference(chapter));
      entry.totalScore += Number(signal.score) || 0;
      entry.peakScore = Math.max(entry.peakScore, Number(signal.score) || 0);
      entries.set(id, entry);
    });
  });
  const items = [...entries.values()].map((entry) => ({
    ...entry,
    count: entry.chapters.length,
    averageScore: entry.chapters.length ? entry.totalScore / entry.chapters.length : 0,
  })).sort((left, right) => right.count - left.count || right.averageScore - left.averageScore || signalLabel(left.id).localeCompare(signalLabel(right.id)));
  return {items, totalChapters: chapters.length, availableChapters: chapters.filter((chapter) => chapter.tag?.signals?.length).length};
}

function emotionRollupData(pipeline) {
  const chapters = authoredSignalChapters(pipeline);
  const available = chapters.filter((chapter) => chapter.emotionStatus === "complete" && chapter.emotion?.distribution);
  const entries = new Map();
  Object.entries(emotionPresentation).forEach(([id, [label, color, icon]]) => {
    entries.set(id, {id, label, color, icon, chapters: [], totalScore: 0, peakScore: 0});
  });
  available.forEach((chapter) => {
    Object.entries(chapter.emotion.distribution || {}).forEach(([id, rawScore]) => {
      const score = Number(rawScore) || 0;
      const presentation = emotionPresentation[id] || [signalLabel(id), "#8393a8", "●"];
      const entry = entries.get(id) || {id, label: presentation[0], color: presentation[1], icon: presentation[2], chapters: [], totalScore: 0, peakScore: 0};
      entry.totalScore += score;
      entry.peakScore = Math.max(entry.peakScore, score);
      if (score >= .10) entry.chapters.push(rollupChapterReference(chapter));
      entries.set(id, entry);
    });
  });
  const items = [...entries.values()].map((entry) => ({
    ...entry,
    count: entry.chapters.length,
    averageScore: available.length ? entry.totalScore / available.length : 0,
  })).filter((entry) => entry.totalScore > 0)
    .sort((left, right) => right.averageScore - left.averageScore || right.count - left.count || left.label.localeCompare(right.label));
  return {items, totalChapters: chapters.length, availableChapters: available.length};
}

function normalizeSmellRollupKey(value) {
  return normalizeSmellKey(value);
}

function smellRollupIssue(item) {
  return smellIssueLabel(item);
}

function smellRollupData(pipeline) {
  const chapters = authoredSignalChapters(pipeline);
  const entries = new Map();
  const findings = reportableSmells(pipeline);
  findings.forEach(({chapter, item}) => {
    smellIssueLabels(item).forEach((label) => {
      const key = normalizeSmellRollupKey(label);
      const entry = entries.get(key) || {label, count: 0, chapters: new Map(), high: 0, medium: 0, low: 0};
      entry.count += 1;
      const reference = rollupChapterReference(chapter);
      entry.chapters.set(reference.sequence, reference);
      const severity = String(item.judgment?.severity || "low").toLocaleLowerCase();
      if (["high", "medium", "low"].includes(severity)) entry[severity] += 1;
      entries.set(key, entry);
    });
  });
  const items = [...entries.values()].map((entry) => ({...entry, chapters: [...entry.chapters.values()]}))
    .sort((left, right) => right.count - left.count || right.chapters.length - left.chapters.length || left.label.localeCompare(right.label));
  return {
    items,
    totalFindings: findings.length,
    totalChapters: chapters.length,
    availableChapters: chapters.filter((chapter) => Array.isArray(chapter.smell?.candidates)).length,
  };
}

function wholeBookRollupRows(items, {kind, totalChapters, availableChapters = totalChapters, visibleLimit = items.length, offset = 0}) {
  const maximum = Math.max(...items.map((item) => item.count), 1);
  return items.map((item, index) => {
    const tag = kind === "tag";
    const emotion = kind === "emotion";
    const label = tag ? signalLabel(item.id) : item.label;
    const secondary = tag ? signalLabel(item.family) : emotion ? `${Math.round(item.averageScore * 100)}% book average · ${Math.round(item.peakScore * 100)}% peak` : [item.high ? `${item.high} high` : "", item.medium ? `${item.medium} medium` : "", item.low ? `${item.low} low` : ""].filter(Boolean).join(" · ");
    const width = tag ? item.count / Math.max(totalChapters, 1) * 100 : emotion ? item.averageScore * 100 : item.count / maximum * 100;
    const metric = tag ? `${Math.round(item.averageScore * 100)}% avg` : emotion ? `${item.count} at 10%+` : `${item.count} ${item.count === 1 ? "finding" : "findings"}`;
    const chapterCount = `${item.chapters.length} ${item.chapters.length === 1 ? "chapter" : "chapters"}`;
    const chapterLinks = item.chapters.length ? `<span class="whole-book-rollup-chapter-count" tabindex="0" aria-label="${escapeHtml(chapterCount)}; focus to show chapter links"><small>${escapeHtml(chapterCount)}</small><span class="whole-book-rollup-chapter-tooltip" role="group" aria-label="${escapeHtml(`${label} chapters`)}">${item.chapters.map((chapter) => `<button type="button" data-rollup-chapter="${chapter.sequence}" data-rollup-kind="${kind}" title="${escapeHtml(chapter.label)}" aria-label="Open ${escapeHtml(chapter.label)} ${escapeHtml(kind)} results">${escapeHtml(chapter.number)}</button>`).join("")}</span></span>` : `<small class="whole-book-rollup-no-chapters">None at threshold</small>`;
    const marker = emotion ? `<span class="whole-book-rollup-emotion" style="--emotion:${escapeHtml(item.color)}">${escapeHtml(item.icon)}</span>` : `<span class="whole-book-rollup-rank">${offset + index + 1}</span>`;
    const name = tag ? explainedSignalLabel(item.id, item.family) : `<strong>${escapeHtml(label)}</strong>`;
    return `<article class="whole-book-rollup-row" data-rollup-row${tag ? ` data-rollup-family="${escapeHtml(item.family)}"` : ""}${index + offset >= visibleLimit ? " hidden" : ""}>${marker}<div class="whole-book-rollup-name">${name}<small>${escapeHtml(secondary)}</small></div><div class="whole-book-rollup-frequency"><span><b>${escapeHtml(metric)}</b>${chapterLinks}</span><i style="--rollup-width:${Math.max(2, width)}%"><b></b></i></div></article>`;
  }).join("");
}

function wholeBookSignalRollupMarkup(pipeline, kind, openRows = new Set()) {
  const data = kind === "tag" ? tagRollupData(pipeline) : kind === "emotion" ? emotionRollupData(pipeline) : smellRollupData(pipeline);
  const items = data.items;
  const tag = kind === "tag";
  const emotion = kind === "emotion";
  const title = tag ? "Whole-book tag frequencies" : emotion ? "Whole-book emotional profile" : "Undismissed Smells by type";
  const subtitle = tag
    ? `${items.length.toLocaleString()} distinct tags across ${data.availableChapters.toLocaleString()} of ${data.totalChapters.toLocaleString()} chapters.`
    : emotion ? `${data.availableChapters.toLocaleString()} of ${data.totalChapters.toLocaleString()} chapters scored · averages and substantial 10%+ appearances.`
    : `${data.totalFindings.toLocaleString()} findings across ${data.availableChapters.toLocaleString()} reviewed chapters.`;
  const empty = tag ? "Tag frequencies will appear as chapter tagging finishes." : emotion ? "The emotional profile will appear as chapter scoring finishes." : "No undismissed Smells are currently available to summarize.";
  const count = tag ? items.length.toLocaleString() : emotion ? `${data.availableChapters.toLocaleString()}/${data.totalChapters.toLocaleString()}` : data.totalFindings.toLocaleString();
  const rollupKey = `rollup:${kind}`;
  const configuredLimit = wholeBookRollupRowLimits[kind];
  const showingAll = configuredLimit === "all" || Number(configuredLimit) >= items.length;
  const selectedLimit = showingAll ? items.length : Number(configuredLimit) || 10;
  const rowOptions = {kind, totalChapters: data.totalChapters, availableChapters: data.availableChapters, visibleLimit: selectedLimit};
  const limitOptions = [10, 25, 50].filter((limit) => limit < items.length).map((limit) => `<option value="${limit}"${selectedLimit === limit ? " selected" : ""}>${limit}</option>`).join("");
  const familyFilters = tag ? `<fieldset class="tag-rollup-filters"><legend>Show tag groups</legend>${tagClusterPresentation.map((cluster) => `<button type="button" data-tag-rollup-cluster="${cluster.id}" data-tag-rollup-families="${cluster.families.join(",")}" aria-pressed="${selectedTagRollupClusters.has(cluster.id)}"><span aria-hidden="true">${cluster.icon}</span>${escapeHtml(cluster.label)}</button>`).join("")}</fieldset>` : "";
  const rowControls = items.length > 10 ? `<div class="whole-book-rollup-controls"><span data-rollup-visible-count>${showingAll ? `Showing all ${items.length.toLocaleString()}` : `Showing top ${selectedLimit.toLocaleString()} of ${items.length.toLocaleString()}`}</span><label>Rows <select data-rollup-row-limit data-rollup-kind="${kind}">${limitOptions}<option value="all"${showingAll ? " selected" : ""}>All (${items.length.toLocaleString()})</option></select></label></div>` : "";
  const controls = `${familyFilters}${rowControls}`;
  return `<details class="whole-book-rollup ${tag ? "tags" : emotion ? "emotions" : "smells"}" data-analysis-key="${rollupKey}"${openRows.has(rollupKey) ? " open" : ""}><summary><div><span>Whole book</span><h3>${escapeHtml(title)}</h3><p>${escapeHtml(subtitle)}</p></div><strong>${escapeHtml(count)}</strong></summary><div class="whole-book-rollup-body">${items.length ? `${controls}<div class="whole-book-rollup-list">${wholeBookRollupRows(items, rowOptions)}</div>` : `<p class="whole-book-rollup-empty">${escapeHtml(empty)}</p>`}</div></details>`;
}

function updateWholeBookRollupVisibility(rollup) {
  const rows = [...rollup.querySelectorAll("[data-rollup-row]")];
  const select = rollup.querySelector("[data-rollup-row-limit]");
  const selected = select?.value === "all" ? "all" : Number(select?.value) || 10;
  const enabledFamilies = new Set([...rollup.querySelectorAll("[data-tag-rollup-cluster][aria-pressed=true]")]
    .flatMap((button) => String(button.dataset.tagRollupFamilies || "").split(",").filter(Boolean)));
  const matching = rows.filter((row) => !row.dataset.rollupFamily || enabledFamilies.has(row.dataset.rollupFamily));
  const visible = selected === "all" ? matching.length : Math.min(selected, matching.length);
  rows.forEach((row) => { row.hidden = !matching.includes(row) || matching.indexOf(row) >= visible; });
  const count = rollup.querySelector("[data-rollup-visible-count]");
  if (count) count.textContent = selected === "all" ? `Showing all ${matching.length.toLocaleString()} matching` : `Showing top ${visible.toLocaleString()} of ${matching.length.toLocaleString()} matching`;
}

function tagResultMarkup(artifact, chapter = {}, openRows = new Set()) {
  const signals = (artifact?.signals || []).filter((signal) => Number(signal.score) >= .25);
  const candidateSignals = artifact?.candidateSignals || [];
  if (!signals.length && !candidateSignals.length) return "<p>No tags crossed the evidence threshold for this chapter.</p>";
  const chapterId = chapterKey(chapter);
  const clusters = tagClusterPresentation.map((cluster) => {
    const families = cluster.families.map((family) => {
      const items = signals.filter((signal) => signal.family === family);
      if (!items.length) return "";
      const [label] = tagFamilyPresentation[family] || [signalLabel(family)];
      const strongest = [...items].sort((left, right) => Number(right.score) - Number(left.score))[0];
      const familyKey = `tag:${chapterId}:family:${family}`;
      return `<details class="tag-family" data-analysis-key="${escapeHtml(familyKey)}"${openRows.has(familyKey) ? " open" : ""}><summary><h4>${escapeHtml(label)}</h4><span>${escapeHtml(signalLabel(strongest.id))}</span><small>${Math.round(Number(strongest.score) * 100)}%</small></summary><div class="tag-signals">${items.map((signal) => `<article class="tag-signal"><header>${explainedSignalLabel(signal.id, signal.family)}<span>${Math.round(Number(signal.score) * 100)}%</span><small>${Math.round(Number(signal.confidence) * 100)}% confidence</small></header><p class="tag-definition">${escapeHtml(signalDescription(signal.id, signal.family))}</p>${signal.explanation ? `<p>${escapeHtml(signal.explanation)}</p>` : ""}${signal.evidence?.length ? `<details><summary>Evidence</summary><ul>${signal.evidence.map((item) => `<li>“${escapeHtml(item.quote)}”${item.location ? `<small>${escapeHtml(item.location)}</small>` : ""}</li>`).join("")}</ul></details>` : ""}</article>`).join("")}</div></details>`;
    }).filter(Boolean).join("");
    if (!families) return "";
    const primaryHitters = cluster.families.flatMap((family) => {
      const familySignals = signals.filter((signal) => signal.family === family).sort((left, right) => Number(right.score) - Number(left.score));
      return familySignals.slice(0, 1);
    });
    const clusterSignals = signals.filter((signal) => cluster.families.includes(signal.family));
    const hitters = [...primaryHitters, ...clusterSignals.filter((signal) => !primaryHitters.includes(signal))].sort((left, right) => Number(right.score) - Number(left.score)).slice(0, 3);
    const clusterKey = `tag:${chapterId}:cluster:${cluster.id}`;
    return `<details class="tag-cluster ${escapeHtml(cluster.id)}" data-analysis-key="${escapeHtml(clusterKey)}"${openRows.has(clusterKey) ? " open" : ""}><summary><span class="tag-cluster-icon" aria-hidden="true">${cluster.icon}</span><span class="tag-cluster-heading"><strong>${escapeHtml(cluster.label)}</strong><small>${escapeHtml(cluster.description)}</small></span><span class="tag-cluster-hitters">${hitters.map((signal) => `<span>${escapeHtml(signalLabel(signal.id))}<small>${Math.round(Number(signal.score) * 100)}%</small></span>`).join("")}</span></summary><div class="tag-cluster-families">${families}</div></details>`;
  }).filter(Boolean).join("");
  const candidates = candidateSignals.length ? `<details class="tag-candidates"><summary><span><strong>Taxonomy candidates</strong><small>Suggestions outside the fixed vocabulary; not used in maps or manuscript markers.</small></span><b>${candidateSignals.length.toLocaleString()}</b></summary><ul>${candidateSignals.map((item) => `<li><strong>${escapeHtml(item.label || "Candidate")}</strong> ${escapeHtml(item.explanation || "")}</li>`).join("")}</ul></details>` : "";
  const corrections = artifact.normalizedSignals?.length ? `<details class="tag-run-notes"><summary>Run notes · ${artifact.normalizedSignals.length.toLocaleString()} ${artifact.normalizedSignals.length === 1 ? "taxonomy correction" : "taxonomy corrections"}</summary><ul>${artifact.normalizedSignals.map((item) => `<li><strong>${escapeHtml(signalLabel(item.id))}</strong> moved from ${escapeHtml(signalLabel(item.fromFamily || "unassigned"))} to ${escapeHtml(signalLabel(item.toFamily))}.</li>`).join("")}</ul></details>` : "";
  return `${clusters ? `<div class="tag-clusters">${clusters}</div>` : ""}${candidates}${corrections}`;
}

function smellResultMarkup(artifact, chapter) {
  const candidates = Array.isArray(artifact.candidates) ? artifact.candidates : [];
  const detectorRank = {"spacy": 0, "proselint": 1, "bookinator": 2, "harper": 3};
  const evidenceLabel = (entry = {}) => {
    const rule = String(entry.rule || "");
    if (String(entry.detector || "").toLowerCase() === "harper" && /oxford comma/i.test(entry.message || "")) return "Oxford comma";
    return ({"clause-count": "Complex sentence structure", "finite-verb-load": "Possible overloaded sentence", "sentence-length": "Long sentence", "clause-load-proxy": "Heavy clause load"})[rule] || signalLabel(rule || entry.detector || "Local detector finding");
  };
  const displayJudgment = (item) => {
    const judgment = item.judgment || {};
    const unreviewed = !item.judgment || judgment.issue === "Unreviewed local finding";
    const evidence = [...(item.evidence || [])].sort((left, right) => (detectorRank[String(left.detector || "").toLowerCase()] ?? 9) - (detectorRank[String(right.detector || "").toLowerCase()] ?? 9));
    const primary = evidence[0] || {};
    return unreviewed
      ? {...judgment, issue: smellRollupIssue(item) || evidenceLabel(primary), reason: primary.message || "A local detector flagged this sentence, but the editorial model did not finish reviewing it.", unreviewed: true}
      : {...judgment, issue: smellRollupIssue(item)};
  };
  const isReported = (item) => item.userStatus === "reported" || (["report", "keep"].includes(item.judgment?.verdict) && item.userStatus !== "dismissed");
  const candidateCard = (item, hidden = false) => {
    const judgment = displayJudgment(item);
    const evidence = (item.evidence || []).map((entry) => `<li><strong>${escapeHtml(entry.detector || "Detector")}</strong>: ${escapeHtml(entry.message || entry.rule || "Flagged this sentence")}</li>`).join("");
    const overlap = (item.detectors || []).length > 1 ? `<span class="smell-agreement">${item.detectors.length} detectors</span>` : "";
    const disposition = hidden
      ? `<button class="source-passage-inspect" data-smell-disposition="reported" data-smell-candidate="${escapeHtml(item.id || "")}" data-chapter-sequence="${Number(chapter.sequence || chapter.number || 0)}" type="button">Yes, report this</button>`
      : `<button class="source-passage-inspect" data-smell-disposition="dismissed" data-smell-candidate="${escapeHtml(item.id || "")}" data-chapter-sequence="${Number(chapter.sequence || chapter.number || 0)}" type="button">Dismiss</button>`;
    const sourceVerdict = item.userStatus === "dismissed" ? "Dismissed by you" : judgment.unreviewed ? "Awaiting review" : judgment.verdict === "informational" ? "Informational" : judgment.verdict === "dismiss" ? "Editor dismissed" : "Possible prose smell";
    return `<details class="editorial-finding ${hidden ? "neutral" : "caution"} smell-finding"><summary><span><strong>${escapeHtml(judgment.issue || "Possible prose smell")}</strong><small>${escapeHtml(judgment.reason || "The editorial model did not return a usable judgment.")}</small></span><span>${escapeHtml(sourceVerdict)}${overlap}</span></summary><blockquote>“${escapeHtml(item.sentence || "")}”</blockquote><h5>Why it was flagged</h5><ul>${evidence}</ul><footer><small>Characters ${Number(item.characterStart || 0).toLocaleString()}–${Number(item.characterEnd || 0).toLocaleString()}</small><span class="smell-actions">${disposition}<button class="source-passage-inspect" data-view-source-passage data-chapter-sequence="${Number(chapter.sequence || chapter.number || 0)}" data-character-start="${Number(item.characterStart || 0)}" data-character-end="${Number(item.characterEnd || 0)}" data-passage-sequence="smell" type="button">Annotate source</button></span></footer></details>`;
  };
  const orderedCandidates = [...candidates].sort((left, right) => smellSortMode === "type"
    ? smellRollupIssue(left).localeCompare(smellRollupIssue(right)) || Number(left.characterStart || 0) - Number(right.characterStart || 0)
    : Number(left.characterStart || 0) - Number(right.characterStart || 0) || smellRollupIssue(left).localeCompare(smellRollupIssue(right)));
  const visible = orderedCandidates.filter(isReported);
  const cards = visible.map((item) => candidateCard(item)).join("");
  const styleSignals = Array.isArray(artifact.styleSignals) ? artifact.styleSignals : [];
  const styleMeasurements = styleSignals.length ? `<section class="smell-style-summary"><header><div><strong>Chapter-level style measurements</strong><span>Patterns worth understanding, not sentence-level complaints.</span></div><b>${styleSignals.reduce((total, item) => total + Number(item.candidateCount || 0), 0).toLocaleString()}</b></header><div>${styleSignals.map((item) => `<span><strong>${escapeHtml(item.issue || "Style signal")}</strong><small>${Number(item.candidateCount || 0).toLocaleString()} ${Number(item.candidateCount || 0) === 1 ? "sentence" : "sentences"}</small></span>`).join("")}</div></section>` : "";
  const rejectedItems = orderedCandidates.filter((item) => !isReported(item) && item.routing?.route !== "style_metric");
  const hidden = rejectedItems.length;
  const unreviewed = candidates.filter((item) => displayJudgment(item).unreviewed).length;
  const rejected = hidden ? `<details class="editorial-glossary smell-rejected"><summary>Show ${hidden} dismissed, informational, or unreviewed candidates</summary><div class="editorial-findings">${rejectedItems.map((item) => candidateCard(item, true)).join("")}</div></details>` : "";
  const progress = artifact.reviewProgress || {};
  const progressNote = progress.complete === false ? `<p class="pipeline-progress-note">Editorial review: ${Number(progress.completedBatches || 0)} of ${Number(progress.totalBatches || 0)} batches saved.</p>` : "";
  return `${progressNote}${styleMeasurements}<p class="editorial-method-note"><strong>${visible.length} smells kept.</strong> ${Number(artifact.routedForDeepReview ?? candidates.length).toLocaleString()} candidates required deep review; ${Number(artifact.dismissed || 0)} were dismissed and ${unreviewed} still await review. Every judgment preserves its local detector evidence.</p>${cards ? `<div class="editorial-findings">${cards}</div>` : progress.complete === false || unreviewed ? "<p>Local findings are ready; editorial judgments are incomplete.</p>" : "<p>No reportable smells survived editorial review.</p>"}${rejected}`;
}

function smellSortControlMarkup() {
  return `<section class="smell-sort-toolbar"><div><strong>Arrange findings</strong><span>This order applies to every chapter.</span></div><div class="book-index-switch smell-sort-switch" role="group" aria-label="Arrange all chapter smells"><button type="button" data-smell-sort="position" aria-pressed="${smellSortMode === "position"}"><span aria-hidden="true">¶</span><strong>Position</strong><small>Book order</small></button><button type="button" data-smell-sort="type" aria-pressed="${smellSortMode === "type"}"><span aria-hidden="true">A</span><strong>Type</strong><small>A–Z</small></button></div></section>`;
}

function chapterSignalMarkup(chapter, kind, openRows = new Set(), book = {}) {
  const config = kind === "emotion"
    ? {status: "emotionStatus", artifact: "emotion", model: "emotionModel", started: "emotionStartedAt", completed: "emotionCompletedAt", duration: "emotionDurationSeconds", input: "emotionInputCharacters", error: "emotionError", title: "Emotion details", render: emotionResultMarkup}
    : kind === "smell"
        ? {status: "smellStatus", artifact: "smell", model: "smellModel", started: "smellStartedAt", completed: "smellCompletedAt", duration: "smellDurationSeconds", input: "smellInputCharacters", error: "smellError", title: "Smells details", render: smellResultMarkup}
      : {status: "tagStatus", artifact: "tag", model: "tagModel", started: "tagStartedAt", completed: "tagCompletedAt", duration: "tagDurationSeconds", input: "tagInputCharacters", error: "tagError", title: "Tagging details", render: tagResultMarkup};
  const artifact = chapter[config.artifact] || {};
  const status = chapter[config.status] || "pending";
  const key = `${kind}:${chapterKey(chapter)}`;
  const partialSmells = kind === "smell" && ["running", "failed"].includes(status) && Array.isArray(artifact.candidates);
  const body = status === "complete" || partialSmells
    ? config.render(artifact, chapter, openRows)
    : status === "excluded"
      ? `<p><strong>Not scored.</strong> Front matter is structural evidence, not narrative prose. Bookinator will not infer ${kind === "emotion" ? "emotional texture" : kind === "smell" ? "prose problems" : "themes, mood, genre, or story dynamics"} from a table of contents or other paratext.</p>`
      : status === "failed"
        ? `<p>This chapter does not have usable ${kind === "emotion" ? "emotion scores" : kind === "smell" ? "Smells judgments" : "tags"}. Select <strong>Failed</strong> for the error and run details.</p>`
        : `<p>${status === "running" ? `Bookinator is analyzing this chapter’s ${kind === "emotion" ? "emotional texture" : kind === "smell" ? "possible prose problems" : "editorial signals"} now.` : `Haven’t analyzed this chapter’s ${kind === "emotion" ? "emotions" : kind === "smell" ? "prose smells" : "tags"} yet.`}</p>`;
  const detailRows = kind === "emotion"
    ? [{label: "Schema", value: artifact.schema || "bookinator-emotion-v1", code: true}, {label: "Segments", value: String(artifact.segments?.length || 0)}]
    : kind === "smell"
        ? [{label: "Schema", value: artifact.schema || "bookinator-smells-v2", code: true}, {label: "Candidates", value: String(artifact.candidates?.length || 0)}, {label: "Deep review", value: String(artifact.routedForDeepReview ?? artifact.candidates?.length ?? 0)}, {label: "Kept", value: String(artifact.kept || 0)}]
      : [{label: "Schema", value: artifact.schema || "bookinator-chapter-tags-v1", code: true}, {label: "Taxonomy", value: artifact.taxonomyVersion || "bookinator-chapter-signals-v1", code: true}];
  const details = analysisRunDetails({title: config.title, model: chapter[config.model], startedAt: chapter[config.started], completedAt: chapter[config.completed], duration: chapter[config.duration], status, inputCharacters: chapter[config.input], rows: detailRows});
  const statusBody = `${chapter[config.error] ? `<p class="pipeline-error">${escapeHtml(chapter[config.error])}</p>` : ""}${details}`;
  return analysisDisclosure({className: `chapter-signal ${kind}`, status, key, open: openRows.has(key), heading: displayHeading(chapter.title) || `Section ${chapter.number}`, subheading: displayHeading(chapter.chapterTitle), range: sourcePageRange(book, chapter.pageStart, chapter.pageEnd), metrics: chapter, body, statusBody, sourceSequence: chapter.sequence || chapter.number, refreshKind: kind, refreshId: chapter.sequence || chapter.number});
}

function failedAnalysisCount(pipeline) {
  const chapters = pipeline.chapters || [];
  const chapterFailures = chapters.reduce((count, chapter) => count
    + (chapter.status === "failed" ? 1 : 0)
    + (["emotionStatus", "tagStatus", "smellStatus"].filter((field) => chapter[field] === "failed").length), 0);
  const dossierFailures = (pipeline.chunks || []).filter((chunk) => chunk.dossierStatus === "failed").length;
  const wholeBookFailures = [pipeline.wholeBookSummary, pipeline.wholeBookLlmReview]
    .filter((record) => record?.status === "failed").length;
  return chapterFailures + dossierFailures + wholeBookFailures;
}

function pipelineControl({action = "", label, title, stop = false, danger = false, disabled = false, development = false}) {
  const icon = stop
    ? '<rect x="7" y="7" width="10" height="10" rx="1"/>'
    : ["restart", "retry-failed", "start-over"].includes(action) || action.endsWith("-restart") || label === "Rebuild"
      ? '<path d="M4 11a8 8 0 1 1 2.3 6.1"/><path d="M4 5v6h6"/>'
      : '<path d="m8 5 11 7-11 7Z"/>';
  const attribute = stop ? "data-stop-reading" : `data-pipeline-action="${action}"`;
  return `<button class="pipeline-control-button${stop || danger ? " danger" : ""}" ${attribute}${development ? " data-development-control" : ""} type="button" title="${escapeHtml(title)}"${disabled ? " disabled" : ""}><svg viewBox="0 0 24 24" aria-hidden="true">${icon}</svg><small>${escapeHtml(label)}</small></button>`;
}

function resetCategoryControl(action, category) {
  if (!developmentControlsEnabled) return "";
  return pipelineControl({
    action,
    label: "Reset all",
    title: `Development control: clear every saved ${category} result and rerun this category from the beginning`,
    development: true,
  });
}

function collapseAnalysisControl() {
  return '<button class="pipeline-control-button" data-collapse-analysis type="button" title="Collapse all open disclosures"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="m7 10 5-5 5 5"/><path d="m7 17 5-5 5 5"/></svg><small>Collapse</small></button>';
}

const workspaceIcons = {
  identity: '<path d="M4 16.5V20h3.5L18 9.5 14.5 6 4 16.5Z"/><path d="m13 7.5 3.5 3.5"/><path d="M5 5h6"/>',
  pipeline: '<path d="M5 5v14M5 8h7a3 3 0 0 1 3 3v2a3 3 0 0 0 3 3h2"/><circle cx="5" cy="5" r="2"/><circle cx="5" cy="19" r="2"/><circle cx="19" cy="16" r="2"/>',
  chapters: '<path d="M5 4h14v16H5z"/><path d="M8 8h8M8 12h5M8 16h7"/><path d="m15 12 1.5 1.5L20 10"/>',
  summaries: '<path d="M6 4h12v16H6z"/><path d="M9 8h6M9 12h6M9 16h4"/>',
  emotions: '<path d="M12 20s-7-4.3-7-10a4 4 0 0 1 7-2.6A4 4 0 0 1 19 10c0 5.7-7 10-7 10Z"/><path d="M8.5 12.5c1.2 1.4 2.3 2 3.5 2s2.3-.6 3.5-2"/>',
  tags: '<path d="M4 5v6.5L12.5 20 20 12.5 11.5 4H5a1 1 0 0 0-1 1Z"/><circle cx="8" cy="8" r="1.5"/>',
  smells: '<path d="M6 19h12M8 16c0-3 2-4 2-7a2 2 0 0 1 4 0c0 3 2 4 2 7"/><path d="M9 16h6M5 7l2 1M19 7l-2 1M12 3v2"/>',
  dossiers: '<path d="M5 4h14v16H5z"/><path d="M8 8h8M8 12h8M8 16h5"/><path d="M3 7h2M3 12h2M3 17h2"/>',
  inferences: '<circle cx="5" cy="12" r="2"/><circle cx="12" cy="5" r="2"/><circle cx="19" cy="12" r="2"/><circle cx="12" cy="19" r="2"/><path d="m6.5 10.5 4-4M13.5 6.5l4 4M17.5 13.5l-4 4M10.5 17.5l-4-4"/><path d="M9 12h6"/>',
  plot: '<path d="M4 19h16M5 16c2.5 0 3-8 6-8s3 6 5 6 2-4 4-4"/><circle cx="5" cy="16" r="1"/><circle cx="11" cy="8" r="1"/><circle cx="16" cy="14" r="1"/><circle cx="20" cy="10" r="1"/>',
  connections: '<circle cx="5" cy="12" r="2"/><circle cx="12" cy="5" r="2"/><circle cx="19" cy="12" r="2"/><circle cx="12" cy="19" r="2"/><path d="m6.5 10.5 4-4M13.5 6.5l4 4M17.5 13.5l-4 4M10.5 17.5l-4-4"/>',
  questions: '<circle cx="9" cy="9" r="6"/><path d="M7.5 7.5A2 2 0 0 1 9.4 6c1.2 0 2.1.7 2.1 1.8 0 1.6-2.5 1.7-2.5 3.4M9 14h.01"/><path d="m14 17 2.2 2.2L21 14.5"/>',
  report: '<path d="M6 3h9l3 3v15H6z"/><path d="M15 3v4h4M9 11h6M9 15h6"/><path d="m9 18 3 2 3-2"/>',
  overview: '<path d="M5 4h14v16H5z"/><path d="M8 8h8M8 12h8M8 16h5"/>',
  "chapter-length": '<path d="M5 4v16M5 20h15"/><path d="M8 8h8M8 12h5M8 16h11"/><circle cx="8" cy="8" r="1"/><circle cx="8" cy="12" r="1"/><circle cx="8" cy="16" r="1"/>',
  reviewer: '<path d="M5 4h11v16H5z"/><path d="M8 8h5M8 12h4"/><path d="m13 17 6.5-6.5 2 2L15 19h-2v-2Z"/>',
  context: '<path d="M4 5h6l2 2h8v12H4z"/><path d="M8 11h8M8 15h5"/><path d="M7 3v4M17 3v4"/>',
  "llm-review": '<path d="M5 4h11v16H5z"/><path d="M8 8h5M8 12h4"/><path d="m14 15 2 2 4-5"/><path d="M18 3v4M16 5h4"/>',
  "llm-review-report": '<path d="M4 19V9M10 19V5M16 19v-7M22 19V3"/><path d="M2 19h22"/><path d="m4 7 6-4 6 7 6-9"/>',
  assessment: '<path d="M4 19V9M10 19V5M16 19v-7M22 19V3"/><path d="M2 19h22"/><path d="m4 7 6-4 6 7 6-9"/>',
};

const workspaceTabs = [
  {id: "identity", label: "Identity"},
  {id: "pipeline", label: "Pipeline"},
  {id: "chapters", label: "Chapters"},
  {id: "summaries", label: "Summaries"},
  {id: "dossiers", label: "Dossiers"},
  {id: "emotions", label: "Emotions"},
  {id: "tags", label: "Tags"},
  {id: "smells", label: "Smells"},
  {id: "context", label: "Context"},
  {id: "llm-review", label: "LLM Review"},
  {id: "inferences", label: "Inferences"},
  {id: "report", label: "Share"},
  {id: "overview", label: "Book summary"},
  {id: "chapter-length", label: "Chapter length"},
  {id: "reviewer-report", label: "Comments"},
  {id: "smell-report", label: "Smells"},
  {id: "emotion-map", label: "Emotion map"},
  {id: "tag-report", label: "Tag frequencies"},
  {id: "connections", label: "Connections"},
  {id: "questions", label: "Questions & payoffs"},
  {id: "llm-review-report", label: "LLM Review"},
  {id: "reviewer", label: "Reviewer"},
  {id: "assessment", label: "Assessment"},
];

const workspaceGroups = {
  analysis: ["pipeline", "chapters", "summaries", "dossiers", "emotions", "tags", "smells", "context", "llm-review", "inferences", "reviewer"],
  explore: ["report", "overview", "chapter-length", "reviewer-report", "emotion-map", "tag-report", "connections", "questions", "smell-report", "llm-review-report", "assessment"],
};

const workspaceShelfEndTabs = new Set(["reviewer", "assessment"]);

function workspaceGroupForTab(tab) {
  return Object.entries(workspaceGroups).find(([, tabs]) => tabs.includes(tab))?.[0] || "";
}

function workspaceTabsForBook(book, group) {
  const optional = new Set(["context", "llm-review", "llm-review-report", "assessment"]);
  return workspaceGroups[group].filter((id) => book.llmReviewEnabled || !optional.has(id));
}

function workspaceTabButton(tab, activeTab) {
  const fallbackId = {"smell-report": "smells", "emotion-map": "emotions", "tag-report": "tags", "reviewer-report": "reviewer"}[tab.id] || "overview";
  const icon = workspaceIcons[tab.id] || workspaceIcons[fallbackId];
  const classes = ["book-tool-button"];
  if (tab.id === "report") classes.push("shelf-lead-action");
  if (["pipeline", "report"].includes(tab.id)) classes.push("shelf-divider-after");
  return `<button type="button" class="${classes.join(" ")}" data-book-tab="${tab.id}"${activeTab === tab.id ? ' aria-current="page"' : ""}><span class="book-tool-icon" aria-hidden="true"><svg viewBox="0 0 24 24">${icon}</svg></span><small>${escapeHtml(tab.label)}</small></button>`;
}

async function navigateWorkspaceTab(bookId, tab, inference = "") {
  if (identityFormIsInline() && state.editingBookId === bookId && tab !== "identity") {
    const saved = await flushIdentityAutosave();
    if (!saved) return;
  }
  const suffix = inference ? `/${inference}` : "";
  history.pushState(null, "", `#book/${bookId}/${tab}${suffix}`);
  // The Pipeline tab is the authoritative work ledger. A cached workspace
  // payload may predate a worker that started while the reader was elsewhere,
  // which can otherwise pair a current global activity banner with stale
  // "Waiting" rows. Always revalidate this tab from the durable ledger.
  const cachedPipeline = tab !== "pipeline" && state.workspacePipeline?.bookId === bookId ? state.workspacePipeline.pipeline : null;
  return showBookPage(bookId, tab, inference, cachedPipeline);
}

function workspacePipelineNeedsPolling(bookId, pipeline) {
  if (["running", "queued"].includes(pipeline?.status)) return true;
  const localActivity = pipeline?.activity;
  if (["running", "stopping", "queued"].includes(localActivity?.state)) return true;
  const globalActivity = pipeline?.globalPipeline?.activity || state.globalPipeline?.activity;
  return ["running", "stopping", "queued"].includes(globalActivity?.state) && globalActivity?.bookId === bookId;
}

function renderWorkspaceNavigation(container, book, activeTab) {
  const activeGroup = workspaceGroupForTab(activeTab);
  const groupMarkup = (group, label, icon) => `<button type="button" class="book-tool-button workspace-group-button${activeGroup === group ? " is-active" : ""}" data-workspace-group="${group}" aria-expanded="${activeGroup === group && !workspaceGroupState(book.id, group).collapsed}" title="${label} workspace"><span class="book-tool-icon" aria-hidden="true"><svg viewBox="0 0 24 24">${workspaceIcons[icon]}</svg></span><span class="workspace-group-copy"><small>${label}</small><span class="workspace-group-status" data-workspace-group-status="${group}">${group === "analysis" ? "Analysis tools" : "Linked reports"}</span></span><span class="workspace-group-chevron" aria-hidden="true">⌄</span></button>`;
  const shelf = activeGroup && !workspaceGroupState(book.id, activeGroup).collapsed
    ? `<div class="book-workspace-shelf" data-workspace-shelf="${activeGroup}" aria-label="${activeGroup === "analysis" ? "Analysis" : "Explore"} tools">${workspaceTabsForBook(book, activeGroup).map((id) => `${workspaceShelfEndTabs.has(id) ? '<span class="workspace-shelf-spacer" aria-hidden="true"></span>' : ""}${workspaceTabButton(workspaceTabs.find((tab) => tab.id === id), activeTab)}`).join("")}</div>`
    : "";
  const identityButton = workspaceTabButton(workspaceTabs.find((tab) => tab.id === "identity"), activeTab).replace('class="book-tool-button"', 'class="book-tool-button book-bar-action"');
  container.innerHTML = `<div class="book-workspace-primary">${identityButton}${groupMarkup("analysis", "Analysis", "pipeline")}${groupMarkup("explore", "Explore", "connections")}<span class="workspace-primary-spacer" aria-hidden="true"></span></div>${shelf}`;
  container.querySelectorAll("[data-book-tab]").forEach((button) => button.addEventListener("click", () => navigateWorkspaceTab(book.id, button.dataset.bookTab)));
  container.querySelectorAll("[data-workspace-group]").forEach((button) => button.addEventListener("click", () => {
    const group = button.dataset.workspaceGroup;
    if (activeGroup === group) {
      rememberWorkspaceGroupState(book.id, group, {collapsed: button.getAttribute("aria-expanded") === "true"});
      renderWorkspaceNavigation(container, book, activeTab);
      if (state.workspacePipeline?.bookId === book.id) updateWorkspaceTabProgress(container, state.workspacePipeline.pipeline, activeTab);
      return;
    }
    const remembered = workspaceGroupState(book.id, group).lastTab;
    const availableTabs = workspaceTabsForBook(book, group);
    const destination = availableTabs.includes(remembered) ? remembered : availableTabs[0];
    rememberWorkspaceGroupState(book.id, group, {collapsed: false});
    navigateWorkspaceTab(book.id, destination);
  }));
}

const plannedWorkspaceViews = {
  plot: {
    icon: "plot",
    title: "Plot arcs",
    subtitle: "Story shape and narrated time will be drawn separately.",
    eyebrow: "Planned analysis view",
    heading: "A story has more than one curve.",
    text: "This view will compare tension, stakes, reversals, revelations, goal progress, and resolution while also mapping flashbacks, branches, uncertain dates, and the difference between story time and chapter order.",
    inputs: ["Chapter tags", "Dossiers", "Editor judgments"],
    output: "Inspectable plot and temporal diagrams",
  },
  reviewer: {
    icon: "reviewer",
    title: "Reviewer",
    subtitle: "The human editorial workspace, informed by every analysis pass.",
    eyebrow: "Human judgment",
    heading: "Advice arrives here. Decisions leave from here.",
    text: "The reviewer will read the manuscript with summaries, tags, dossiers, plot arcs, and connections close at hand; highlight passages; write durable annotations; challenge findings; and assemble the chapter/page/snippet/comment handoff for the author.",
    inputs: ["All analysis tabs", "Manuscript text", "Human annotations"],
    output: "An evidence-linked editorial review",
  },
  assessment: {
    icon: "assessment",
    title: "Assessment",
    subtitle: "An evidence-linked judgment of the manuscript’s strengths, risks, and market readiness.",
    eyebrow: "Planned editorial view",
    heading: "Quality and saleability need arguments, not a magic score.",
    text: "This view will assess readability, character appeal, narrative propulsion, genre fit, audience clarity, distinctiveness, and commercial positioning while preserving evidence, uncertainty, and room for a reviewer to disagree.",
    inputs: ["Whole-book analysis", "Comparable positioning", "Reviewer judgments"],
    output: "A qualified manuscript assessment",
  },
};

async function fetchReviewerAnnotations(bookId) {
  const response = await fetch(`/api/books/${encodeURIComponent(bookId)}/annotations`);
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || "Bookinator could not load the annotations.");
  const annotations = Array.isArray(result.annotations) ? result.annotations : [];
  state.reviewerAnnotations.set(bookId, annotations);
  const bookPage = document.querySelector("#book-page");
  if (bookPage?.dataset.bookId === bookId && state.workspacePipeline?.bookId === bookId) {
    updateWorkspaceTabProgress(document.querySelector("#book-tabs"), state.workspacePipeline.pipeline, bookPage.dataset.activeTab);
  }
  return annotations;
}

function invalidateReviewerAnnotations(bookId) {
  state.reviewerAnnotations.delete(bookId);
  if (state.currentBookId === bookId) state.pipelineSignature = "";
}

async function reviewerAnnotationsForExport(bookId) {
  if (state.reviewerAnnotations.has(bookId)) return state.reviewerAnnotations.get(bookId) || [];
  try {
    return await fetchReviewerAnnotations(bookId);
  } catch {
    return [];
  }
}

function annotationCsv(annotations, book = {}) {
  const cell = (value) => `"${String(value ?? "").replaceAll('"', '""')}"`;
  return [
    ["Chapter", "Source location", "Text snippet", "Category", "Priority", "Editor comment"],
    ...annotations.filter((item) => item.status !== "archived").map((item) => [displayHeading(item.chapterLabel), sourcePageRange(book, item.pageStart, item.pageEnd), item.quote, annotationCategorySummary(item), annotationPriorityLabel(item.priority), item.comment]),
  ].map((row) => row.map(cell).join(",")).join("\n") + "\n";
}

function reviewerSignoffMarkup(signoff = {}) {
  const complete = signoff.status === "complete";
  if (complete) {
    return `<section class="reviewer-signoff complete"><div class="reviewer-signoff-mark" aria-hidden="true">✓</div><div><p>Signed off for now</p><h3>${escapeHtml(signoff.reviewerName || "Reviewer")}</h3>${signoff.completedAt ? `<small>${escapeHtml(new Date(signoff.completedAt).toLocaleString())}</small>` : ""}${signoff.notes ? `<blockquote>${escapeHtml(signoff.notes)}</blockquote>` : ""}</div><button type="button" data-rescind-review>Rescind sign-off</button></section>`;
  }
  return `<section class="reviewer-signoff"><div class="reviewer-signoff-intro"><p>Review sign-off</p><h3>Finished with this pass?</h3><span>This marks the human review complete for now. You can reopen it whenever the manuscript—or your mind—changes.</span></div><form data-reviewer-signoff-form><label><span>Reviewer name</span><input name="reviewerName" maxlength="200" required value="${escapeHtml(signoff.reviewerName || "")}" placeholder="Your name"></label><label><span>General notes <small>Optional</small></span><textarea name="notes" maxlength="12000" rows="4" placeholder="What should the author understand about this review as a whole?">${escapeHtml(signoff.notes || "")}</textarea></label><p data-reviewer-signoff-message role="status"></p><button class="reviewer-signoff-button" type="submit"><span aria-hidden="true">✓</span>I’m all done with this part</button></form></section>`;
}

function reviewerWorkspaceMarkup(pipeline, annotations, book, signoff = {}) {
  const visible = annotations.filter((item) => item.status !== "archived");
  const archived = annotations.filter((item) => item.status === "archived");
  const byChapter = new Map();
  visible.forEach((annotation) => byChapter.set(Number(annotation.chapterSequence), [...(byChapter.get(Number(annotation.chapterSequence)) || []), annotation]));
  const chapters = (pipeline.chapters || []).filter((chapter) => displayHeading(chapter.title).toLocaleLowerCase() !== "front matter");
  const chapterList = chapters.map((chapter) => {
    const sequence = Number(chapter.sequence || chapter.number || 0);
    const count = byChapter.get(sequence)?.length || 0;
    return `<button class="reviewer-chapter-row" type="button" data-review-chapter="${sequence}"><span>${sequence.toLocaleString()}</span><span><strong>${escapeHtml(displayHeading(chapter.title) || `Section ${sequence}`)}</strong><small>${escapeHtml(displayHeading(chapter.chapterTitle) || sourcePageRange(book, chapter.pageStart, chapter.pageEnd))}</small></span><b>${count ? `${count} ${count === 1 ? "note" : "notes"}` : "Read"}</b></button>`;
  }).join("");
  const ledger = visible.length ? visible.map((annotation) => {
    const actions = [
      reviewerActionButton({action: "view", label: "View", attribute: `data-open-annotation="${escapeHtml(annotation.id)}"`}),
      reviewerActionButton({action: "edit", label: "Edit", attribute: `data-inline-edit-annotation="${escapeHtml(annotation.id)}"`}),
      reviewerActionButton({action: "archive", label: "Archive", attribute: `data-archive-annotation="${escapeHtml(annotation.id)}"`, tone: "archive"}),
    ].join("");
    return `<article class="reviewer-note active" data-reviewer-note="${escapeHtml(annotation.id)}"><header><span>${escapeHtml(displayHeading(annotation.chapterLabel) || `Section ${annotation.chapterSequence}`)}</span><span>${escapeHtml(sourcePageRange(book, annotation.pageStart, annotation.pageEnd))}</span>${annotationPriorityControl(annotation)}</header><blockquote>${escapeHtml(annotation.quote)}</blockquote>${inlineAnnotationCommentMarkup(annotation)}<footer><div class="reviewer-note-meta"><div class="reviewer-note-categories">${annotationCategoryBadgesMarkup(annotation)}</div><span class="reviewer-note-state active">Active</span></div><div class="reviewer-note-actions">${actions}</div></footer></article>`;
  }).join("") : '<div class="reviewer-empty"><strong>No human notes yet.</strong><p>Choose a chapter, select the passage that prompted your reaction, and annotate it. Machine analysis remains nearby, but it does not speak for you.</p></div>';
  const archive = archived.length ? `<details class="reviewer-archive"><summary>Archived comments <span>${archived.length.toLocaleString()}</span></summary><div>${archived.map((annotation) => `<article><div><strong>${escapeHtml(displayHeading(annotation.chapterLabel) || `Section ${annotation.chapterSequence}`)}</strong><p>${escapeHtml(annotation.comment)}</p></div>${reviewerActionButton({action: "restore", label: "Restore", attribute: `data-restore-annotation="${escapeHtml(annotation.id)}"`})}</article>`).join("")}</div></details>` : "";
  return `<section class="reviewer-workspace"><header class="reviewer-status"><div><strong>${visible.length.toLocaleString()}</strong><span>active</span></div><div><strong>${archived.length.toLocaleString()}</strong><span>archived</span></div><p>The manuscript is the reading surface. The ledger is the handoff.</p></header>${reviewerSignoffMarkup(signoff)}<div class="reviewer-layout"><aside><h3>Read the manuscript</h3><p>Select any passage to attach a durable local comment.</p><div class="reviewer-chapter-list">${chapterList || '<p>Prepare the manuscript to begin reviewing it.</p>'}</div></aside><section class="reviewer-ledger"><header><div><h3>Editorial notes</h3><p>Human judgments stay separate from regenerated machine analysis.</p></div>${visible.length ? '<button type="button" data-export-annotations>Export CSV</button>' : ""}</header><div>${ledger}</div>${archive}</section></div></section>`;
}

function reviewerReportMarkup(annotations, book, signoff = {}) {
  const visible = annotations.filter((item) => item.status !== "archived");
  const categoryCounts = new Map();
  visible.forEach((annotation) => annotationCategories(annotation).forEach((category) => categoryCounts.set(category, (categoryCounts.get(category) || 0) + 1)));
  const chapters = new Set(visible.map((item) => Number(item.chapterSequence || 0)).filter(Boolean));
  const categories = [...categoryCounts.entries()].sort((left, right) => right[1] - left[1] || annotationCategoryLabel(left[0]).localeCompare(annotationCategoryLabel(right[0])));
  const cards = visible.slice().sort((left, right) => Number(left.chapterSequence || 0) - Number(right.chapterSequence || 0) || String(left.createdAt || "").localeCompare(String(right.createdAt || ""))).map((annotation) => `<article class="review-comment-card active"><header><div><strong>${escapeHtml(displayHeading(annotation.chapterLabel) || `Section ${annotation.chapterSequence}`)}</strong><span>${escapeHtml(sourcePageRange(book, annotation.pageStart, annotation.pageEnd))}</span></div>${annotationPriorityControl(annotation)}</header><div class="review-comment-categories">${annotationCategoryBadgesMarkup(annotation)}</div><blockquote>“${escapeHtml(annotation.quote)}”</blockquote>${inlineAnnotationCommentMarkup(annotation)}<footer><span>Active</span><div class="review-comment-actions">${reviewerActionButton({action: "view", label: "View", attribute: `data-open-annotation="${escapeHtml(annotation.id)}"`})}${reviewerActionButton({action: "edit", label: "Edit", attribute: `data-inline-edit-annotation="${escapeHtml(annotation.id)}"`})}${reviewerActionButton({action: "archive", label: "Archive", attribute: `data-archive-annotation="${escapeHtml(annotation.id)}"`, tone: "archive"})}</div></footer></article>`).join("");
  const summary = visible.length ? `<section class="review-comment-summary"><div><strong>${visible.length.toLocaleString()}</strong><span>active comments</span></div><div><strong>${chapters.size.toLocaleString()}</strong><span>chapters</span></div><div class="review-comment-category-summary"><strong>What drew attention</strong><p>${categories.map(([category, count]) => `${annotationCategoryLabel(category)} ${count}`).join(" · ") || "No categories yet"}</p></div></section>` : "";
  const signoffSummary = signoff.status === "complete" ? `<section class="review-report-signoff"><span aria-hidden="true">✓</span><div><p>Review signed off by</p><h3>${escapeHtml(signoff.reviewerName || "Reviewer")}</h3>${signoff.notes ? `<blockquote>${escapeHtml(signoff.notes)}</blockquote>` : ""}</div></section>` : "";
  return workspaceTaskView({icon: "reviewer", title: "Reviewer comments", subtitle: visible.length ? `${visible.length} human ${visible.length === 1 ? "comment" : "comments"} across ${chapters.size} ${chapters.size === 1 ? "chapter" : "chapters"}.` : "No human comments have been included yet.", actions: reportExportControl("reviewer-report"), explanationTitle: "This is the human editorial record.", explanation: "It gathers the passages a reviewer marked, the lenses they applied, and what they want the author to understand. Machine findings remain elsewhere.", collapse: false, content: `<article class="editor-report reviewer-report">${signoffSummary}${summary}${cards ? `<div class="review-comment-list">${cards}</div>` : '<div class="pipeline-empty"><strong>No reviewer comments yet.</strong><p>Use Reviewer in Analysis to select a passage and leave the first human note.</p></div>'}</article>`});
}

function workspaceSectionHeading({icon, title, subtitle, actions = "", metrics = "", explanationTitle = "", explanation = "", collapse = true}) {
  const sideContent = `${metrics}${actions}${collapse ? collapseAnalysisControl() : ""}`;
  const side = sideContent ? `<div class="workspace-heading-side">${sideContent}</div>` : "";
  const help = explanationTitle || explanation
    ? ` tabindex="0" data-tooltip-heading="${escapeHtml(explanationTitle)}" data-tooltip="${escapeHtml(explanation)}" aria-label="${escapeHtml(title)}: ${escapeHtml(explanationTitle)} ${escapeHtml(explanation)}"`
    : "";
  return `<header class="workspace-section-heading"><div class="workspace-heading-main${explanationTitle || explanation ? " has-help" : ""}"${help}><span class="workspace-section-icon${explanationTitle || explanation ? " has-help" : ""}" aria-hidden="true"><svg viewBox="0 0 24 24">${workspaceIcons[icon]}</svg></span><div><h2>${escapeHtml(title)}</h2><p>${escapeHtml(subtitle)}</p></div></div>${side}</header>`;
}

function progressActivity(activity = {}, fallback = "Bookinator is checking the global queue") {
  const stateName = ["running", "stopping", "queued", "idle"].includes(activity?.state) ? activity.state : "idle";
  const copy = String(activity?.text || fallback);
  const task = String(activity?.task || "");
  const book = String(activity?.book || "");
  const item = String(activity?.item || "");
  const model = String(activity?.model || "");
  const structured = task && book
    ? `<span class="progress-live-copy"><strong>${escapeHtml(task)}</strong><small>${escapeHtml([book, item, model].filter(Boolean).join(" · "))}</small></span>`
    : `<span>${escapeHtml(copy)}</span>`;
  return `<span class="progress-live ${stateName}" title="${escapeHtml(copy)}"><i aria-hidden="true"></i>${structured}</span>`;
}

function resolvedActivity(pipeline = null) {
  const presentActivity = (activity) => {
    if (!activity) return activity;
    if (activity.phase === "questions") return {...activity, task: "Questions & payoffs", item: "Whole-book reconciliation", text: `Bookinator · ${activity.model || "the local model"} is matching questions to payoffs in ${activity.book || "this book"}`};
    const item = String(activity.item || "").replace(/^(\d+)(?=\s*(?:,|$))/, "Chapter $1");
    return item === activity.item ? activity : {...activity, item};
  };
  const local = presentActivity(pipeline?.activity);
  if (["running", "stopping", "queued"].includes(local?.state)) return local;
  const global = presentActivity(pipeline?.globalPipeline?.activity || state.globalPipeline?.activity);
  if (["running", "stopping", "queued"].includes(global?.state)) return global;
  if (pipeline?.stopRequested) return {state: "stopping", text: "Bookinator is stopping after the current local response"};
  if (pipeline?.status === "running") return {state: "running", text: `Bookinator is alive · ${pipeline.message || "working locally"}`};
  if (pipeline?.status === "queued") return {state: "queued", text: pipeline.message || "Bookinator is waiting for the local queue"};
  if (state.globalPipeline?.running) return {state: "running", text: "Bookinator is alive · working through the global queue"};
  if (state.globalPipeline?.enabled && Number(state.globalPipeline?.waitingBooks || 0)) return {state: "queued", text: "Bookinator is checking the global queue"};
  if (!state.globalPipeline?.enabled && Number(state.globalPipeline?.waitingBooks || 0)) return {state: "idle", text: "The global queue is off"};
  return local || global || {state: "idle", text: "Bookinator is ready; no analysis is waiting"};
}

function taskProgress({label, unit, progress, activity = null, status = ""}) {
  if (!progress?.total || progress.completed >= progress.total) return "";
  const partialEta = progress.etaPartial && Number.isFinite(progress.etaSeconds) && progress.etaSeconds > 0
    ? `${formatEta(progress.etaSeconds).replace(/^About /, "At least ")} · ${progress.etaUnestimatedStageCount} unfinished ${progress.etaUnestimatedStageCount === 1 ? "pass is" : "passes are"} still estimating`
    : "";
  const statusCopy = progress.etaLabel || (status === "complete" ? "Complete" : status === "paused" ? "Paused; resume whenever you are ready." : partialEta || formatEta(progress.etaSeconds));
  const basisCopy = progress.basisLabel || (progress.etaSampleSize ? `${progress.etaSampleSize} recent items used for the estimate` : "");
  return progressPanel({label, completed: progress.completed, total: progress.total, unit, percent: progress.percent, statusCopy, basisCopy, activity: activity || resolvedActivity()});
}

function progressPanel({label, completed = 0, total = 0, unit = "items", percent = 0, statusCopy = "", basisCopy = "", activity = null, fallbackActivity = "Bookinator is checking the global queue", className = ""}) {
  const completeText = `${Number(completed).toLocaleString()} of ${Number(total).toLocaleString()} ${unit} complete`;
  const safePercent = Math.max(0, Math.min(100, Number(percent) || 0));
  return `<section class="overall-progress${className ? ` ${escapeHtml(className)}` : ""}"><header><strong>${escapeHtml(label)}</strong><span>${escapeHtml(completeText)}</span></header><div class="progress-track" role="progressbar" aria-label="${escapeHtml(label)}" aria-valuemin="0" aria-valuemax="${Number(total) || 0}" aria-valuenow="${Number(completed) || 0}"><span style="width:${safePercent}%"></span></div><footer><p><strong>${safePercent}%</strong> ${escapeHtml(statusCopy)}${basisCopy ? `<small>${escapeHtml(basisCopy)}</small>` : ""}</p>${progressActivity(activity || resolvedActivity(), fallbackActivity)}</footer></section>`;
}

function taskHeadingActions({action = "", extra = ""}) {
  return `<div class="workspace-heading-actions">${action}${extra}</div>`;
}

function timingChartControl(view) {
  return `<button class="pipeline-control-button timing-chart-control" data-show-timing-chart="${escapeHtml(view)}" type="button" title="Chart saved elapsed times"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 19V5"/><path d="M4 19h16"/><path d="m7 15 4-5 3 2 5-7"/><circle cx="7" cy="15" r="1"/><circle cx="11" cy="10" r="1"/><circle cx="14" cy="12" r="1"/><circle cx="19" cy="5" r="1"/></svg><small>Timing</small></button>`;
}

function chartExportControl() {
  return `<details class="chart-export-menu" data-no-dialog-drag><summary class="pipeline-control-button" title="Export this chart"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3v12M7 10l5 5 5-5"/><path d="M5 19h14"/></svg><small>Export</small></summary><div role="menu"><button type="button" role="menuitem" data-chart-export="svg">SVG</button><button type="button" role="menuitem" data-chart-export="png">PNG</button><button type="button" role="menuitem" data-chart-export="pdf">PDF</button><button type="button" role="menuitem" data-chart-export="csv">CSV</button></div></details>`;
}

function reportExportControl(report) {
  return `<details class="chart-export-menu report-export-menu"><summary class="pipeline-control-button" title="Export this report"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3v12M7 10l5 5 5-5"/><path d="M5 19h14"/></svg><small>Export</small></summary><div role="menu"><button type="button" role="menuitem" data-report-export="${escapeHtml(report)}">PDF</button></div></details>`;
}

function downloadFile(content, filename, type) {
  const blob = content instanceof Blob ? content : new Blob([content], {type});
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

async function bookWithEmbeddedIcon(book) {
  const value = String(book.icon?.value || "");
  if (book.icon?.kind !== "image" || value.startsWith("data:image/")) return book;
  const response = await fetch(value);
  if (!response.ok) return book;
  const blob = await response.blob();
  const dataUrl = await new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || ""));
    reader.onerror = () => reject(reader.error || new Error("Book icon could not be embedded."));
    reader.readAsDataURL(blob);
  });
  return {...book, icon: {...book.icon, value: dataUrl, lazy: false}};
}

function exportableSvg(svg) {
  const clone = svg.cloneNode(true);
  clone.setAttribute("xmlns", "http://www.w3.org/2000/svg");
  clone.setAttribute("width", svg.viewBox.baseVal.width);
  clone.setAttribute("height", svg.viewBox.baseVal.height);
  clone.removeAttribute("style");
  const style = document.createElementNS("http://www.w3.org/2000/svg", "style");
  style.textContent = `.timing-grid,.timing-row-guide{stroke:#dce7f4;stroke-width:1}.timing-axis{stroke:#8091a8;stroke-width:1.25}.timing-axis-title{fill:#52657f;font:850 13px Arial,sans-serif}.timing-line{fill:none;stroke:#7a52bd;stroke-width:3;stroke-linejoin:round}circle{fill:#fff;stroke:#6f46b5;stroke-width:4}text{fill:#52657f;font:750 13px Arial,sans-serif}.timing-label{fill:#223b5e;font-weight:750}.timing-label-title{fill:#697b94;font-size:11px;font-weight:650}`;
  clone.prepend(style);
  return new XMLSerializer().serializeToString(clone);
}

let bookinatorLogoDataUrlPromise = null;
function bookinatorLogoDataUrl() {
  if (!bookinatorLogoDataUrlPromise) {
    bookinatorLogoDataUrlPromise = fetch("/assets/bookinator.svg").then((response) => response.text()).then((source) => {
      const bytes = new TextEncoder().encode(source);
      let binary = "";
      bytes.forEach((byte) => { binary += String.fromCharCode(byte); });
      return `data:image/svg+xml;base64,${btoa(binary)}`;
    });
  }
  return bookinatorLogoDataUrlPromise;
}

function iconPalette(icon) {
  const background = /^#[0-9a-f]{6}$/i.test(icon?.background || "") ? icon.background : "#071f4a";
  const rgb = [1, 3, 5].map((offset) => Number.parseInt(background.slice(offset, offset + 2), 16));
  const foreground = (0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]) / 255 > 0.62 ? "#10213d" : "#fff";
  return {background, foreground};
}

function exportedBookIcon(book, x, y, width = 38, height = 48) {
  const icon = book.icon?.value ? book.icon : fallbackIcon(book.title);
  const {background, foreground} = iconPalette(icon);
  if (icon.kind === "image") return `<rect x="${x}" y="${y}" width="${width}" height="${height}" rx="6" fill="${background}"/><image href="${escapeHtml(icon.value)}" x="${x + 3}" y="${y + 3}" width="${width - 6}" height="${height - 6}" preserveAspectRatio="xMidYMid meet"/>`;
  return `<rect x="${x}" y="${y}" width="${width}" height="${height}" rx="6" fill="${background}"/><text x="${x + width / 2}" y="${y + height / 2 + 5}" fill="${foreground}" font-family="Georgia,serif" font-size="16" text-anchor="middle">${escapeHtml(shortMark(icon.value) || "B")}</text>`;
}

async function brandedChartSvg(serialized, width, height, {book, analysisLabel, timingLabel}) {
  const logo = await bookinatorLogoDataUrl();
  const headerHeight = 92, footerHeight = 72, outputHeight = headerHeight + height + footerHeight;
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${outputHeight}" viewBox="0 0 ${width} ${outputHeight}"><rect width="100%" height="100%" fill="#fff"/>${exportedBookIcon(book, 32, 20)}<text x="82" y="42" fill="#102748" font-family="Georgia,serif" font-size="22" font-weight="700">${escapeHtml(book.title)}</text><text x="82" y="64" fill="#52657f" font-family="Arial,sans-serif" font-size="13">${escapeHtml(book.author || "Author not specified")}</text><text x="${width - 32}" y="42" fill="#143663" font-family="Arial,sans-serif" font-size="15" font-weight="700" text-anchor="end">${escapeHtml(analysisLabel)}</text><text x="${width - 32}" y="64" fill="#64758c" font-family="Arial,sans-serif" font-size="13" text-anchor="end">${escapeHtml(timingLabel)}</text><svg x="0" y="${headerHeight}" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}">${serialized.replace(/^<svg[^>]*>|<\/svg>$/g, "")}</svg><line x1="32" x2="${width - 32}" y1="${headerHeight + height + 10}" y2="${headerHeight + height + 10}" stroke="#d2deee"/><image href="${logo}" x="32" y="${headerHeight + height + 19}" width="42" height="42"/><text x="84" y="${headerHeight + height + 38}" fill="#143663" font-family="Arial,sans-serif" font-size="16" font-weight="700">Bookinator</text><text x="84" y="${headerHeight + height + 57}" fill="#64758c" font-family="Arial,sans-serif" font-size="11">Find what the author forgot.</text></svg>`;
}

function renderSvgToCanvas(serialized, width, height, scale = 2) {
  return new Promise((resolve, reject) => {
    const blob = new Blob([serialized], {type: "image/svg+xml;charset=utf-8"});
    const url = URL.createObjectURL(blob);
    const image = new Image();
    image.onload = () => {
      const canvas = document.createElement("canvas");
      canvas.width = Math.round(width * scale);
      canvas.height = Math.round(height * scale);
      const context = canvas.getContext("2d");
      context.fillStyle = "#fff";
      context.fillRect(0, 0, canvas.width, canvas.height);
      context.drawImage(image, 0, 0, canvas.width, canvas.height);
      URL.revokeObjectURL(url);
      resolve(canvas);
    };
    image.onerror = () => { URL.revokeObjectURL(url); reject(new Error("The chart could not be rendered.")); };
    image.src = url;
  });
}

function bytesFromDataUrl(dataUrl) {
  const binary = atob(dataUrl.split(",")[1]);
  return Uint8Array.from(binary, (character) => character.charCodeAt(0));
}

function pdfLiteral(value) {
  return String(value ?? "").replace(/[\u0000-\u001f\u007f]/g, " ").replace(/([\\()])/g, "\\$1");
}

function pdfCreationDate(date = new Date()) {
  return `D:${date.getFullYear()}${String(date.getMonth() + 1).padStart(2, "0")}${String(date.getDate()).padStart(2, "0")}${String(date.getHours()).padStart(2, "0")}${String(date.getMinutes()).padStart(2, "0")}${String(date.getSeconds()).padStart(2, "0")}`;
}

function jpegPagesPdf(pages, metadata = {}) {
  const encoder = new TextEncoder();
  const chunks = [];
  const offsets = [0];
  let length = 0;
  const append = (value) => { const bytes = typeof value === "string" ? encoder.encode(value) : value; chunks.push(bytes); length += bytes.length; };
  append("%PDF-1.4\n%\xE2\xE3\xCF\xD3\n");
  const infoId = 3 + pages.length * 3;
  const objectCount = infoId;
  const pageIds = pages.map((_, index) => 3 + index * 3);
  const object = (id, body) => { offsets[id] = length; append(`${id} 0 obj\n${body}\nendobj\n`); };
  object(1, "<< /Type /Catalog /Pages 2 0 R >>");
  object(2, `<< /Type /Pages /Count ${pages.length} /Kids [${pageIds.map((id) => `${id} 0 R`).join(" ")}] >>`);
  pages.forEach((page, index) => {
    const pageId = pageIds[index], imageId = pageId + 1, contentId = pageId + 2;
    object(pageId, `<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /XObject << /Im${index} ${imageId} 0 R >> >> /Contents ${contentId} 0 R >>`);
    offsets[imageId] = length;
    append(`${imageId} 0 obj\n<< /Type /XObject /Subtype /Image /Width ${page.width} /Height ${page.height} /ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /DCTDecode /Length ${page.bytes.length} >>\nstream\n`);
    append(page.bytes); append("\nendstream\nendobj\n");
    const stream = `q 612 0 0 792 0 0 cm /Im${index} Do Q`;
    object(contentId, `<< /Length ${stream.length} >>\nstream\n${stream}\nendstream`);
  });
  const title = pdfLiteral(metadata.title || "Bookinator report");
  const author = pdfLiteral(metadata.author || "");
  const subject = pdfLiteral(metadata.subject || "Bookinator editorial analysis");
  object(infoId, `<< /Title (${title}) /Author (${author}) /Subject (${subject}) /Creator (Bookinator) /Producer (Bookinator) /CreationDate (${pdfCreationDate(metadata.createdAt)}) >>`);
  const xref = length;
  append(`xref\n0 ${objectCount + 1}\n0000000000 65535 f \n`);
  for (let id = 1; id <= objectCount; id += 1) append(`${String(offsets[id]).padStart(10, "0")} 00000 n \n`);
  append(`trailer\n<< /Size ${objectCount + 1} /Root 1 0 R /Info ${infoId} 0 R >>\nstartxref\n${xref}\n%%EOF`);
  const output = new Uint8Array(length);
  let position = 0;
  chunks.forEach((chunk) => { output.set(chunk, position); position += chunk.length; });
  return output;
}

async function brandedChartPdf(chartCanvas, {book, analysisLabel, timingLabel}) {
  const pageWidth = 1224, pageHeight = 1584, margin = 72, headerHeight = 126, footerHeight = 120;
  const contentWidth = pageWidth - margin * 2;
  const contentHeight = pageHeight - margin * 2 - headerHeight - footerHeight;
  const sliceHeight = Math.max(1, Math.floor(contentHeight / contentWidth * chartCanvas.width));
  const pageCount = Math.ceil(chartCanvas.height / sliceHeight);
  const logo = new Image();
  const logoReady = new Promise((resolve) => { logo.onload = resolve; logo.onerror = resolve; });
  logo.src = "/assets/bookinator.svg";
  await logoReady;
  const bookImage = new Image();
  const bookImageReady = new Promise((resolve) => { bookImage.onload = resolve; bookImage.onerror = resolve; });
  if (book.icon?.kind === "image") bookImage.src = book.icon.value;
  if (book.icon?.kind === "image") await bookImageReady;
  const pages = [];
  for (let index = 0; index < pageCount; index += 1) {
    const canvas = document.createElement("canvas");
    canvas.width = pageWidth; canvas.height = pageHeight;
    const context = canvas.getContext("2d");
    context.fillStyle = "#fff"; context.fillRect(0, 0, pageWidth, pageHeight);
    const icon = book.icon?.value ? book.icon : fallbackIcon(book.title);
    const palette = iconPalette(icon);
    context.fillStyle = palette.background; context.beginPath(); context.roundRect(margin, 30, 58, 72, 9); context.fill();
    if (icon.kind === "image" && bookImage.complete && bookImage.naturalWidth) context.drawImage(bookImage, margin + 5, 35, 48, 62);
    else { context.fillStyle = palette.foreground; context.font = "700 25px Georgia, serif"; context.textAlign = "center"; context.fillText(shortMark(icon.value) || "B", margin + 29, 73); context.textAlign = "left"; }
    context.fillStyle = "#102748"; context.font = "700 30px Georgia, serif"; context.fillText(book.title, margin + 76, 59);
    context.fillStyle = "#52657f"; context.font = "18px Arial, sans-serif"; context.fillText(book.author || "Author not specified", margin + 76, 88);
    context.textAlign = "right"; context.fillStyle = "#143663"; context.font = "700 20px Arial, sans-serif"; context.fillText(analysisLabel, pageWidth - margin, 59);
    context.fillStyle = "#64758c"; context.font = "18px Arial, sans-serif"; context.fillText(timingLabel, pageWidth - margin, 88); context.textAlign = "left";
    const sourceY = index * sliceHeight;
    const sourceHeight = Math.min(sliceHeight, chartCanvas.height - sourceY);
    const renderedHeight = sourceHeight / chartCanvas.width * contentWidth;
    context.drawImage(chartCanvas, 0, sourceY, chartCanvas.width, sourceHeight, margin, margin + headerHeight, contentWidth, renderedHeight);
    const footerY = pageHeight - margin - footerHeight + 22;
    context.strokeStyle = "#d2deee"; context.lineWidth = 2; context.beginPath(); context.moveTo(margin, footerY - 18); context.lineTo(pageWidth - margin, footerY - 18); context.stroke();
    if (logo.complete && logo.naturalWidth) context.drawImage(logo, margin, footerY, 54, 54);
    context.fillStyle = "#143663"; context.font = "700 24px Arial, sans-serif"; context.fillText("Bookinator", margin + 70, footerY + 24);
    context.fillStyle = "#64758c"; context.font = "16px Arial, sans-serif"; context.fillText("Find what the author forgot.", margin + 70, footerY + 49);
    context.fillStyle = "#2a4a74"; context.font = "700 16px Arial, sans-serif"; context.textAlign = "right"; context.fillText(`Page ${index + 1} of ${pageCount}`, pageWidth - margin, footerY + 28); context.textAlign = "left";
    pages.push({bytes: bytesFromDataUrl(canvas.toDataURL("image/jpeg", 0.92)), width: pageWidth, height: pageHeight});
  }
  return jpegPagesPdf(pages, {
    title: `Bookinator - ${book.title} - ${book.author || "Author not specified"}`,
    author: book.author || "",
    subject: `${analysisLabel} - ${timingLabel}`,
  });
}

async function editorReportPdf(pipeline, book, {only = "", sections = [], annotations = []} = {}) {
  const width = 1224, height = 1584, renderScale = .75, pixelWidth = Math.round(width * renderScale), pixelHeight = Math.round(height * renderScale), margin = 76, contentWidth = width - margin * 2, contentBottom = height - 142;
  const canvases = [], pageMeta = [], sectionStarts = [];
  const logo = new Image();
  const logoReady = new Promise((resolve) => { logo.onload = resolve; logo.onerror = resolve; });
  logo.src = "/assets/bookinator.svg";
  const bookImage = new Image();
  const bookImageReady = new Promise((resolve) => { bookImage.onload = resolve; bookImage.onerror = resolve; });
  if (book.icon?.kind === "image") bookImage.src = book.icon.value;
  await Promise.all([logoReady, book.icon?.kind === "image" ? bookImageReady : Promise.resolve()]);
  const totalProjectTime = timingChartRows(pipeline, "pipeline").reduce((sum, row) => sum + Math.max(0, Number(row.seconds) || 0), 0);
  let canvas, context, y, currentSection = "Editorial report", tocCanvas = null;
  const linesFor = (text, maxWidth, font, target = context) => {
    target.font = font;
    const lines = [];
    String(text || "").split(/\n+/).forEach((paragraph, paragraphIndex, paragraphs) => {
      let line = "";
      paragraph.trim().split(/\s+/).filter(Boolean).forEach((word) => {
        const next = line ? `${line} ${word}` : word;
        if (line && target.measureText(next).width > maxWidth) { lines.push(line); line = word; } else line = next;
      });
      if (line) lines.push(line);
      if (paragraphIndex < paragraphs.length - 1) lines.push("");
    });
    return lines;
  };
  const drawBookIcon = (target, x, top, iconWidth = 52, iconHeight = 66) => {
    const icon = book.icon?.value ? book.icon : fallbackIcon(book.title);
    const palette = iconPalette(icon);
    target.fillStyle = palette.background; target.beginPath(); target.roundRect(x, top, iconWidth, iconHeight, 8); target.fill();
    if (icon.kind === "image" && bookImage.complete && bookImage.naturalWidth) target.drawImage(bookImage, x + 4, top + 4, iconWidth - 8, iconHeight - 8);
    else { target.fillStyle = palette.foreground; target.font = `700 ${Math.round(iconWidth * .42)}px Georgia, serif`; target.textAlign = "center"; target.fillText(shortMark(icon.value) || "B", x + iconWidth / 2, top + iconHeight * .62); target.textAlign = "left"; }
  };
  const drawStandardHeader = (target, section) => {
    target.save(); target.setTransform(renderScale, 0, 0, renderScale, 0, 0); target.globalAlpha = 1; target.globalCompositeOperation = "source-over"; target.textAlign = "left";
    drawBookIcon(target, margin, 26, 48, 60);
    target.fillStyle = "#102748"; target.font = "700 24px Georgia, serif"; target.fillText(book.title || "Untitled", margin + 64, 53);
    target.fillStyle = "#61738b"; target.font = "15px Arial, sans-serif"; target.fillText(book.author || "Author not specified", margin + 64, 78);
    target.textAlign = "right"; target.fillStyle = "#214d82"; target.font = "800 16px Arial, sans-serif"; target.fillText(section, width - margin, 60); target.textAlign = "left";
    target.strokeStyle = "#cfdceb"; target.lineWidth = 2; target.beginPath(); target.moveTo(margin, 108); target.lineTo(width - margin, 108); target.stroke(); target.restore();
  };
  const newPage = (section = currentSection, {register = false, bare = false} = {}) => {
    currentSection = section;
    canvas = document.createElement("canvas"); canvas.width = pixelWidth; canvas.height = pixelHeight;
    context = canvas.getContext("2d"); context.setTransform(renderScale, 0, 0, renderScale, 0, 0); context.fillStyle = "#fff"; context.fillRect(0, 0, width, height);
    if (!bare) drawStandardHeader(context, section);
    y = 150; canvases.push(canvas); pageMeta.push({section, bare});
    if (register) sectionStarts.push({title: section, page: canvases.length});
    return canvas;
  };
  const ensure = (space) => { if (y + space > contentBottom) newPage(`${currentSection.replace(/(?: · continued)+$/, "")} · continued`); };
  const heading = (text, level = 2) => {
    const font = level === 1 ? "700 39px Georgia, serif" : level === 2 ? "700 27px Georgia, serif" : "700 20px Georgia, serif";
    const lineHeight = level === 1 ? 47 : level === 2 ? 35 : 28;
    const lines = linesFor(text, contentWidth, font);
    ensure(lines.length * lineHeight + 18);
    context.fillStyle = level === 1 ? "#102748" : level === 2 ? "#214d82" : "#17365f"; context.font = font;
    lines.forEach((line) => { context.fillText(line, margin, y + lineHeight - 9); y += lineHeight; }); y += 10;
  };
  const paragraph = (text, {font = "18px Georgia, serif", color = "#314763", lineHeight = 29, indent = 0, maxWidth = contentWidth - indent, after = 8} = {}) => {
    const lines = linesFor(text, maxWidth, font);
    context.fillStyle = color; context.font = font;
    lines.forEach((line) => {
      ensure(lineHeight + 2);
      if (!line) y += Math.round(lineHeight * .55); else { context.fillStyle = color; context.font = font; context.fillText(line, margin + indent, y); y += lineHeight; }
    }); y += after;
  };
  const rule = () => { ensure(26); context.strokeStyle = "#d8e3ef"; context.lineWidth = 1; context.beginPath(); context.moveTo(margin, y); context.lineTo(width - margin, y); context.stroke(); y += 25; };
  const statusPill = (label, x, top, fill = "#2865ae", text = "#fff") => {
    context.font = "800 13px Arial, sans-serif"; const pillWidth = context.measureText(label).width + 24;
    context.fillStyle = fill; context.beginPath(); context.roundRect(x, top, pillWidth, 26, 13); context.fill();
    context.fillStyle = text; context.fillText(label, x + 12, top + 18); return pillWidth;
  };
  const selectedSections = new Set(sections);
  const section = (key, title, render) => {
    if ((only && only !== key) || (!only && selectedSections.size && !selectedSections.has(key))) return;
    newPage(title, {register: !only}); render();
  };
  if (!only) {
    newPage("Editorial report", {bare: true});
    context.fillStyle = "#17365f"; context.fillRect(0, 0, width, 116);
    if (logo.complete && logo.naturalWidth) context.drawImage(logo, margin, 26, 62, 62);
    context.fillStyle = "#fff"; context.font = "800 20px Arial, sans-serif"; context.fillText("BOOKINATOR", margin + 78, 64);
    context.fillStyle = "#cde0f7"; context.font = "14px Arial, sans-serif"; context.fillText("Editorial report", margin + 78, 86);
    drawBookIcon(context, margin, 224, 112, 142);
    context.fillStyle = "#102748"; context.font = "700 63px Georgia, serif";
    let coverY = 260;
    linesFor(book.title || "Untitled", contentWidth - 155, "700 63px Georgia, serif").slice(0, 3).forEach((line) => { context.fillText(line, margin + 145, coverY); coverY += 72; });
    context.fillStyle = "#52657f"; context.font = "26px Arial, sans-serif"; context.fillText(book.author || "Author not specified", margin + 145, coverY + 6);
    context.fillStyle = "#f4f0fa"; context.beginPath(); context.roundRect(margin, 470, contentWidth, 160, 14); context.fill();
    context.fillStyle = "#68439f"; context.font = "800 17px Arial, sans-serif"; context.fillText("EDITORIAL ANALYSIS", margin + 30, 512);
    context.fillStyle = "#253f60"; context.font = "21px Georgia, serif";
    linesFor("A linked, inspectable view of the manuscript’s summaries, evidence, editorial findings, emotions, questions, and analysis status.", contentWidth - 60, "21px Georgia, serif").forEach((line, index) => context.fillText(line, margin + 30, 552 + index * 32));
    context.fillStyle = "#65778e"; context.font = "16px Arial, sans-serif"; context.fillText(`Generated ${new Date().toLocaleString()} · ${formatRunDuration(totalProjectTime)} recorded project time`, margin, 700);
    tocCanvas = newPage("Table of contents");
  }

  section("status", "Analysis status", () => {
    const availableStages = (pipeline.stages || []).filter((stage) => !/^prose$/i.test(String(stage.id || "")) && !/^prose$/i.test(String(stage.label || "")));
    heading("What was available at export", 1); y += 18;
    paragraph(`${formatRunDuration(totalProjectTime)} of recorded project analysis time. Check this page before reading the report. Red markers identify analyses that were incomplete when this PDF was created, so their later sections may be partial.`, {font: "17px Arial, sans-serif", color: "#526984", lineHeight: 27, after: 18});
    availableStages.forEach((stage) => {
      ensure(62); const complete = stage.status === "complete", color = complete ? "#23765b" : "#b7483f";
      context.fillStyle = complete ? "#f2f8f5" : "#fff4f2"; context.beginPath(); context.roundRect(margin, y - 22, contentWidth, 49, 7); context.fill(); context.fillStyle = color; context.beginPath(); context.arc(margin + 18, y + 1, 8, 0, Math.PI * 2); context.fill();
      context.fillStyle = "#183b66"; context.font = "700 17px Arial, sans-serif"; context.fillText(stage.label || signalLabel(stage.id), margin + 38, y + 1);
      context.textAlign = "right"; context.fillStyle = color; context.font = "800 13px Arial, sans-serif"; context.fillText(signalLabel(stage.status || "pending"), width - margin - 14, y + 1); context.textAlign = "left";
      context.fillStyle = "#64758c"; context.font = "13px Arial, sans-serif"; context.fillText(String(stage.detail || "").slice(0, 126), margin + 38, y + 21); y += 62;
    });
  });

  section("overview", "Book summary", () => {
    heading("The story at a glance", 1);
    context.fillStyle = "#f2f6fb"; context.beginPath(); context.roundRect(margin, y, contentWidth, 18, 10); context.fill(); y += 30;
    paragraph(pipeline.wholeBookSummary?.summary || "The whole-book summary is not complete yet.", {font: "21px Georgia, serif", lineHeight: 34, indent: 22, maxWidth: contentWidth - 44, after: 22});
    heading("Chapter summaries", 2);
    (pipeline.chapters || []).filter((chapter) => displayHeading(chapter.title).toLocaleLowerCase() !== "front matter" && chapter.summary).forEach((chapter) => {
      ensure(118);
      const number = reportChapterNumber(chapter);
      context.fillStyle = "#2865ae"; context.beginPath(); context.arc(margin + 18, y + 17, 18, 0, Math.PI * 2); context.fill();
      context.fillStyle = "#fff"; context.font = "800 12px Arial, sans-serif"; context.textAlign = "center"; context.fillText(number, margin + 18, y + 21); context.textAlign = "left";
      context.fillStyle = "#17365f"; context.font = "700 20px Georgia, serif"; context.fillText(displayHeading(chapter.title) || `Chapter ${number}`, margin + 50, y + 14);
      if (displayHeading(chapter.chapterTitle)) { context.fillStyle = "#64758c"; context.font = "14px Arial, sans-serif"; context.fillText(displayHeading(chapter.chapterTitle), margin + 50, y + 36); }
      y += 58; paragraph(chapter.summary, {font: "17px Georgia, serif", lineHeight: 27, indent: 50, maxWidth: contentWidth - 50, after: 15}); rule();
    });
  });

  section("chapter-length", "Chapter length", () => {
    const chapters = (pipeline.chapters || []).filter((chapter) => displayHeading(chapter.title).toLocaleLowerCase() !== "front matter");
    const maximum = Math.max(...chapters.map((chapter) => Number(chapter.wordCount || 0)), 1);
    const orderedChapters = [...chapters].sort((left, right) => Number(left.wordCount || 0) - Number(right.wordCount || 0));
    const orderedCounts = orderedChapters.map((chapter) => Number(chapter.wordCount || 0));
    const middle = Math.floor(orderedCounts.length / 2);
    const median = orderedCounts.length ? (orderedCounts.length % 2 ? orderedCounts[middle] : Math.round((orderedCounts[middle - 1] + orderedCounts[middle]) / 2)) : 0;
    const shortest = orderedChapters[0];
    const longest = orderedChapters[orderedChapters.length - 1];
    heading("Chapter length", 1);
    paragraph(`${chapters.length.toLocaleString()} authored chapters · ${median.toLocaleString()} median words. Each row uses the same scale, so changes in chapter size remain visible without treating consistency as a score.`, {font: "16px Arial, sans-serif", color: "#60728a", lineHeight: 25, after: 20});
    if (chapters.length) {
      ensure(112);
      const cards = [
        {label: "Shortest", value: Number(shortest.wordCount || 0), detail: `${reportChapterNumber(shortest)} · ${displayHeading(shortest.chapterTitle) || displayHeading(shortest.title)}`},
        {label: "Median", value: median, detail: "Middle chapter length"},
        {label: "Longest", value: Number(longest.wordCount || 0), detail: `${reportChapterNumber(longest)} · ${displayHeading(longest.chapterTitle) || displayHeading(longest.title)}`},
      ];
      const gap = 14;
      const cardWidth = (contentWidth - gap * 2) / 3;
      cards.forEach((card, index) => {
        const x = margin + index * (cardWidth + gap);
        context.fillStyle = index === 1 ? "#f4f0fa" : "#edf5ff"; context.beginPath(); context.roundRect(x, y - 12, cardWidth, 84, 10); context.fill();
        context.fillStyle = index === 1 ? "#68439f" : "#2865ae"; context.font = "800 12px Arial, sans-serif"; context.fillText(card.label, x + 16, y + 10);
        context.fillStyle = "#102748"; context.font = "700 22px Georgia, serif"; context.fillText(`${card.value.toLocaleString()} words`, x + 16, y + 38);
        context.fillStyle = "#60728a"; context.font = "700 11px Arial, sans-serif"; context.fillText(String(card.detail || "").slice(0, 38), x + 16, y + 60);
      });
      y += 104;
    }
    chapters.forEach((chapter, index) => {
      ensure(42);
      const words = Math.max(0, Number(chapter.wordCount || 0));
      const barWidth = Math.max(4, words / maximum * (contentWidth - 205));
      const top = y - 18;
      if (index % 2) { context.fillStyle = "#f7faff"; context.beginPath(); context.roundRect(margin, top - 3, contentWidth, 38, 7); context.fill(); }
      context.fillStyle = "#2865ae"; context.beginPath(); context.arc(margin + 18, top + 15, 16, 0, Math.PI * 2); context.fill();
      context.fillStyle = "#fff"; context.font = "800 11px Arial, sans-serif"; context.textAlign = "center"; context.fillText(reportChapterNumber(chapter), margin + 18, top + 19); context.textAlign = "left";
      context.fillStyle = "#e1eaf4"; context.beginPath(); context.roundRect(margin + 50, top + 9, contentWidth - 170, 12, 6); context.fill();
      context.fillStyle = "#356fae"; context.beginPath(); context.roundRect(margin + 50, top + 9, barWidth, 12, 6); context.fill();
      context.fillStyle = "#425c7b"; context.font = "800 13px Arial, sans-serif"; context.textAlign = "right"; context.fillText(`${words.toLocaleString()} words`, width - margin - 10, top + 20); context.textAlign = "left";
      y += 42;
    });
    if (!chapters.length) paragraph("No chapter word counts are available yet.");
  });

  const dossier = pipeline.wholeBookDossier || {};
  section("dossier", "Dossier synthesis", () => {
    heading("Evidence-linked memory", 1);
    paragraph(dossier.synopsis || dossier.summary || "The whole-book Dossier synthesis is not complete yet.", {font: "21px Georgia, serif", lineHeight: 34, color: "#2d4565", after: 20});
    [["Established facts", dossier.facts], ["Consolidated events", dossier.events]].forEach(([label, items]) => {
      if (!items?.length) return; heading(label, 2); y += 16;
      items.forEach((item, index) => {
        ensure(52); context.fillStyle = index % 2 ? "#f7faff" : "#edf4fb"; context.beginPath(); context.roundRect(margin, y - 19, contentWidth, 42, 7); context.fill();
        paragraph(item, {font: "16px Arial, sans-serif", lineHeight: 25, indent: 17, maxWidth: contentWidth - 34, after: 7});
      });
    });
  });

  section("reviewer-report", "Reviewer comments", () => {
    const comments = annotations.filter((item) => item.status !== "archived").slice().sort((left, right) => Number(left.chapterSequence || 0) - Number(right.chapterSequence || 0) || String(left.createdAt || "").localeCompare(String(right.createdAt || "")));
    const chapterCount = new Set(comments.map((item) => Number(item.chapterSequence || 0)).filter(Boolean)).size;
    heading("Reviewer comments", 1);
    const reviewerSignoff = pipeline.reviewerSignoff || {};
    if (reviewerSignoff.status === "complete") {
      ensure(104);
      context.fillStyle = "#eef8f4"; context.beginPath(); context.roundRect(margin, y - 18, contentWidth, 76, 9); context.fill();
      context.fillStyle = "#28765d"; context.fillRect(margin, y - 18, 7, 76);
      context.fillStyle = "#28765d"; context.font = "800 12px Arial, sans-serif"; context.fillText("REVIEW SIGNED OFF FOR NOW", margin + 22, y + 2); y += 26;
      context.fillStyle = "#17365f"; context.font = "700 19px Georgia, serif"; context.fillText(String(reviewerSignoff.reviewerName || "Reviewer"), margin + 22, y + 2); y += 25;
      if (reviewerSignoff.completedAt) {
        context.fillStyle = "#64758c"; context.font = "12px Arial, sans-serif"; context.fillText(new Date(reviewerSignoff.completedAt).toLocaleString(), margin + 22, y); y += 20;
      }
      y += reviewerSignoff.completedAt ? 18 : 38;
      if (reviewerSignoff.notes) {
        paragraph("General review notes", {font: "800 12px Arial, sans-serif", color: "#28765d", lineHeight: 20, after: 5});
        paragraph(reviewerSignoff.notes, {font: "italic 15px Georgia, serif", color: "#334b62", lineHeight: 23, indent: 14, maxWidth: contentWidth - 28, after: 16});
      }
    }
    paragraph(`${comments.length.toLocaleString()} active human ${comments.length === 1 ? "comment" : "comments"} across ${chapterCount.toLocaleString()} ${chapterCount === 1 ? "chapter" : "chapters"}`, {font: "700 18px Arial, sans-serif", color: "#68439f", lineHeight: 28, after: 22});
    comments.forEach((annotation) => {
      ensure(178);
      const chapterLabel = displayHeading(annotation.chapterLabel) || `Chapter ${Number(annotation.chapterSequence || 0).toLocaleString()}`;
      const pageLabel = sourcePageRange(book, annotation.pageStart, annotation.pageEnd);
      context.fillStyle = "#f5f0fa"; context.beginPath(); context.roundRect(margin, y - 18, contentWidth, 42, 8); context.fill();
      context.fillStyle = "#68439f"; context.fillRect(margin, y - 18, 6, 42);
      context.fillStyle = "#17365f"; context.font = "700 17px Georgia, serif"; context.fillText(chapterLabel, margin + 20, y + 7);
      context.textAlign = "right"; context.fillStyle = "#64758c"; context.font = "13px Arial, sans-serif"; context.fillText(pageLabel, width - margin - 16, y + 7); context.textAlign = "left"; y += 58;
      let pillX = margin;
      const labels = [annotationPriorityLabel(annotation.priority || "normal"), ...annotationCategories(annotation).map(annotationCategoryLabel), ...(annotation.origin?.kind === "llm-review-proposal" ? ["From machine proposal"] : [])];
      labels.forEach((label, index) => {
        context.font = "800 12px Arial, sans-serif"; const pillWidth = context.measureText(label).width + 22;
        if (pillX + pillWidth > width - margin) { pillX = margin; y += 32; ensure(32); }
        const priority = index === 0;
        context.fillStyle = priority && annotation.priority === "high" ? "#a74745" : priority ? "#315f91" : "#e9def6"; context.beginPath(); context.roundRect(pillX, y - 18, pillWidth, 25, 12); context.fill();
        context.fillStyle = priority ? "#fff" : "#5f438c"; context.fillText(label, pillX + 11, y); pillX += pillWidth + 7;
      }); y += 24;
      if (annotation.quote) paragraph(`“${String(annotation.quote).slice(0, 600)}${String(annotation.quote).length > 600 ? "…" : ""}”`, {font: "italic 17px Georgia, serif", color: "#654f80", lineHeight: 27, indent: 18, maxWidth: contentWidth - 36, after: 10});
      paragraph(annotation.comment, {font: "18px Georgia, serif", color: "#263f61", lineHeight: 29, after: 8});
      paragraph("Active reviewer note", {font: "800 12px Arial, sans-serif", color: "#68439f", lineHeight: 20, after: 4});
      rule();
    });
    if (!comments.length) paragraph("No reviewer comments were included in this export.");
  });

  section("connections", "Connections", () => {
    const entityGroups = dossierIndexGroups(pipeline, "entities", book), locationGroups = dossierIndexGroups(pipeline, "locations", book), timeEntries = dossierTimeEntries(pipeline, book);
    heading("People, places, and time", 1);
    paragraph(`${entityGroups.length} entities · ${locationGroups.length} locations · ${timeEntries.length} concrete time observations`, {font: "700 18px Arial, sans-serif", color: "#526984", after: 18});
    [["Most recurring entities", entityGroups, "#2865ae"], ["Most recurring locations", locationGroups, "#26826b"]].forEach(([label, items, accent]) => {
      heading(label, 2); y += 16;
      [...items].sort((left, right) => Number(right.occurrences?.length || 0) - Number(left.occurrences?.length || 0)).slice(0, 24).forEach((item) => {
        ensure(46); context.fillStyle = "#f6f9fd"; context.fillRect(margin, y - 19, contentWidth, 38); context.fillStyle = accent; context.fillRect(margin, y - 19, 5, 38);
        context.fillStyle = "#17365f"; context.font = "700 16px Georgia, serif"; context.fillText(item.label, margin + 18, y + 4);
        context.textAlign = "right"; context.fillStyle = "#5c708b"; context.font = "14px Arial, sans-serif"; context.fillText(`${Number(item.occurrences?.length || 0)} mentions · ${item.chapters?.length || 0} chapters`, width - margin - 14, y + 4); context.textAlign = "left"; y += 46;
      });
    });
  });

  section("tag-report", "Tag frequencies", () => {
    const taggedChapters = (pipeline.chapters || []).filter((chapter) => chapter.tag?.signals?.length);
    const rollup = tagRollupData(pipeline);
    heading("Whole-book tag frequencies", 1);
    paragraph(`${taggedChapters.length} tagged ${taggedChapters.length === 1 ? "chapter" : "chapters"} · fixed-vocabulary editorial signals at 25% or higher.`, {font: "16px Arial, sans-serif", color: "#60728a"});
    if (rollup.items.length) {
      heading("Most frequent tags", 2); y += 14;
      rollup.items.slice(0, 18).forEach((item, index) => {
        ensure(48);
        context.fillStyle = index % 2 ? "#f7faff" : "#edf4fb"; context.beginPath(); context.roundRect(margin, y - 19, contentWidth, 40, 7); context.fill();
        context.fillStyle = "#2865ae"; context.fillRect(margin, y - 19, 5, 40);
        context.fillStyle = "#17365f"; context.font = "700 16px Georgia, serif"; context.fillText(signalLabel(item.id), margin + 18, y + 4);
        context.fillStyle = "#60728a"; context.font = "12px Arial, sans-serif"; context.fillText(signalLabel(item.family), margin + 230, y + 4);
        context.textAlign = "right"; context.fillStyle = "#315f91"; context.font = "800 13px Arial, sans-serif"; context.fillText(`${item.count} of ${rollup.totalChapters} chapters · ${Math.round(item.averageScore * 100)}% average`, width - margin - 14, y + 4); context.textAlign = "left"; y += 48;
      });
      if (rollup.items.length > 18) paragraph(`${rollup.items.length - 18} less frequent tags remain available in Bookinator.`, {font: "13px Arial, sans-serif", color: "#60728a", after: 14});
      rule(); heading("Chapter detail", 2); y += 14;
    }
    taggedChapters.forEach((chapter) => {
      const signals = (chapter.tag?.signals || []).filter((signal) => Number(signal.score) >= .25).sort((left, right) => Number(right.score) - Number(left.score));
      if (!signals.length) return; ensure(94); heading(displayHeading(chapter.title) || `Chapter ${chapter.number || chapter.sequence}`, 3); y += 12;
      let x = margin;
      signals.forEach((signal) => {
        const label = `${signalLabel(signal.id)} ${Math.round(Number(signal.score) * 100)}%`;
        context.font = "800 13px Arial, sans-serif"; const pillWidth = Math.min(contentWidth, context.measureText(label).width + 26);
        if (x + pillWidth > width - margin) { x = margin; y += 36; ensure(36); }
        context.fillStyle = "#e7f0fb"; context.beginPath(); context.roundRect(x, y - 20, pillWidth, 28, 14); context.fill(); context.fillStyle = "#2862a6"; context.fillText(label, x + 13, y); x += pillWidth + 8;
      }); y += 42;
    });
    if (!taggedChapters.length) paragraph("No saved chapter tags are available yet.");
  });

  section("emotion-map", "Emotion map", () => {
    const chapters = (pipeline.chapters || []).filter((chapter) => displayHeading(chapter.title).toLocaleLowerCase() !== "front matter");
    const maxWords = Math.max(...chapters.map((chapter) => Number(chapter.wordCount || 0)), 1);
    const rollup = emotionRollupData(pipeline);
    heading("Whole-book emotional profile", 1);
    paragraph(`${rollup.availableChapters} of ${rollup.totalChapters} chapters scored · averages and substantial 10%+ appearances.`, {font: "16px Arial, sans-serif", color: "#60728a", after: 16});
    rollup.items.forEach((item) => {
      ensure(58);
      context.fillStyle = "#f6f1fc"; context.beginPath(); context.roundRect(margin, y - 20, contentWidth, 48, 8); context.fill();
      context.fillStyle = item.color; context.beginPath(); context.roundRect(margin + 10, y - 12, 32, 32, 7); context.fill();
      context.fillStyle = "#fff"; context.font = "17px Arial, sans-serif"; context.textAlign = "center"; context.fillText(item.icon, margin + 26, y + 10); context.textAlign = "left";
      context.fillStyle = "#17365f"; context.font = "700 16px Georgia, serif"; context.fillText(item.label, margin + 54, y + 3);
      context.fillStyle = "#687a91"; context.font = "12px Arial, sans-serif"; context.fillText(`${Math.round(item.averageScore * 100)}% book average · ${Math.round(item.peakScore * 100)}% peak`, margin + 54, y + 21);
      context.textAlign = "right"; context.fillStyle = "#4c607a"; context.font = "800 13px Arial, sans-serif"; context.fillText(`${item.count} ${item.count === 1 ? "chapter" : "chapters"} at 10%+`, width - margin - 14, y + 5); context.textAlign = "left";
      y += 58;
    });
    rule();
    heading("Chapter emotion map", 1);
    paragraph("Track length represents chapter word count. Colored lanes show chapter-average emotions at 10% or higher.", {font: "16px Arial, sans-serif", color: "#60728a", after: 16});
    const represented = new Map();
    chapters.forEach((chapter) => Object.entries(chapter.emotion?.distribution || {}).filter(([, score]) => Number(score) >= .10).forEach(([label]) => represented.set(label, emotionPresentation[label] || [signalLabel(label), "#8393a8", "●"])));
    let legendX = margin;
    [...represented.values()].sort((left, right) => left[0].localeCompare(right[0])).forEach(([label, color, icon]) => {
      context.font = "700 13px Arial, sans-serif"; const legendWidth = context.measureText(label).width + 45;
      if (legendX + legendWidth > width - margin) { legendX = margin; y += 30; }
      context.fillStyle = color; context.beginPath(); context.roundRect(legendX, y - 18, 24, 24, 5); context.fill(); context.fillStyle = "#fff"; context.font = "13px Arial, sans-serif"; context.textAlign = "center"; context.fillText(icon, legendX + 12, y - 1); context.textAlign = "left";
      context.fillStyle = "#4c607a"; context.font = "700 13px Arial, sans-serif"; context.fillText(label, legendX + 31, y); legendX += legendWidth;
    }); y += 38; rule();
    chapters.forEach((chapter) => {
      const emotions = Object.entries(chapter.emotion?.distribution || {}).filter(([, score]) => Number(score) >= .10).sort((a, b) => Number(b[1]) - Number(a[1]));
      const rowHeight = Math.max(70, emotions.length * 28 + 22); ensure(rowHeight + 8);
      const labelWidth = 280, trackX = margin + labelWidth + 22, trackMax = contentWidth - labelWidth - 22, trackWidth = Math.max(170, Number(chapter.wordCount || 0) / maxWords * trackMax);
      context.fillStyle = "#f6f9fd"; context.beginPath(); context.roundRect(margin, y - 20, contentWidth, rowHeight, 8); context.fill();
      context.fillStyle = "#2865ae"; context.beginPath(); context.arc(margin + 18, y + 2, 15, 0, Math.PI * 2); context.fill(); context.fillStyle = "#fff"; context.font = "800 10px Arial, sans-serif"; context.textAlign = "center"; context.fillText(reportChapterNumber(chapter), margin + 18, y + 6); context.textAlign = "left";
      context.fillStyle = "#17365f"; context.font = "700 16px Georgia, serif"; context.fillText(displayHeading(chapter.title) || `Chapter ${chapter.number || chapter.sequence}`, margin + 42, y + 4);
      context.fillStyle = "#687a91"; context.font = "12px Arial, sans-serif"; context.fillText([displayHeading(chapter.chapterTitle), `${Number(chapter.wordCount || 0).toLocaleString()} words`].filter(Boolean).join(" · "), margin + 42, y + 25);
      context.fillStyle = "#dce8f4"; context.beginPath(); context.roundRect(trackX, y - 3, trackWidth, Math.max(22, rowHeight - 24), 6); context.fill();
      if (!emotions.length) { context.fillStyle = "#74859a"; context.font = "13px Arial, sans-serif"; context.fillText("No emotion at 10%+", trackX + 10, y + 15); }
      emotions.forEach(([label, score], index) => {
        const presentation = emotionPresentation[label] || [signalLabel(label), "#8393a8", "●"], barY = y + index * 28;
        context.fillStyle = presentation[1]; context.beginPath(); context.roundRect(trackX + 6, barY, Math.max(125, Math.min(trackWidth - 12, Number(score) * trackMax)), 22, 5); context.fill();
        context.fillStyle = "#fff"; context.font = "800 11px Arial, sans-serif"; context.fillText(`${presentation[2]} ${presentation[0]} ${Math.round(Number(score) * 100)}%`, trackX + 14, barY + 15);
      }); y += rowHeight + 8;
    });
  });

  section("questions", "Questions & payoffs", () => {
    const questions = pipeline.questionTracker?.items || []; heading(`${questions.length} tracked narrative ${questions.length === 1 ? "question" : "questions"}`, 1); y += 18;
    questions.forEach((item) => {
      ensure(138); const resolved = item.status === "resolved";
      context.fillStyle = resolved ? "#eff8f4" : "#fff8e9"; context.beginPath(); context.roundRect(margin, y - 20, contentWidth, 36, 8); context.fill();
      statusPill(signalLabel(item.status || "open"), margin + 14, y - 15, resolved ? "#24745c" : "#a97721"); y += 42;
      heading(item.question || item.canonicalQuestion || "Narrative question", 3);
      paragraph(`Raised in chapter ${item.triggerChapter || item.sourceChapter || "?"}${item.resolutionChapter ? ` · resolved in chapter ${item.resolutionChapter}` : " · not yet resolved"}`, {font: "700 14px Arial, sans-serif", color: resolved ? "#24745c" : "#8a6320", lineHeight: 22});
      if (item.answer) paragraph(item.answer, {font: "17px Georgia, serif", lineHeight: 27}); rule();
    });
  });

  section("llm-review-report", "LLM Review", () => {
    const synthesis = pipeline.wholeBookLlmReview || {};
    const reviewed = (pipeline.chapters || []).filter((chapter) => chapter.llmReviewStatus === "complete" && chapter.llmReview);
    heading("Whole-book editorial synthesis", 1);
    paragraph("Machine first-reader analysis. These judgments remain proposals until a human reviewer adopts them.", {font: "700 14px Arial, sans-serif", color: "#68439f", lineHeight: 23, after: 18});
    paragraph(synthesis.overallAssessment || "The whole-book editorial synthesis is not complete yet.", {font: "21px Georgia, serif", color: "#2d4565", lineHeight: 34, after: 22});
    const synthesisLists = [
      ["Strengths to preserve", synthesis.strengths, "title", "synthesis", "significance", "#28765d"],
      ["Whole-book risks", synthesis.risks, "title", "synthesis", "significance", "#a64c43"],
      ["Editorial priorities", synthesis.editorialPriorities, "title", "rationale", "scope", "#68439f"],
      ["Likely readers", synthesis.likelyReaders, "reader", "fit", "caution", "#2865ae"],
    ];
    synthesisLists.forEach(([label, items, titleField, bodyField, noteField, accent]) => {
      if (!Array.isArray(items) || !items.length) return;
      heading(label, 2); y += 8;
      items.forEach((item) => {
        ensure(104); context.fillStyle = "#f6f9fd"; context.beginPath(); context.roundRect(margin, y - 18, contentWidth, 12, 6); context.fill(); context.fillStyle = accent; context.fillRect(margin, y - 18, 6, 12);
        heading(item?.[titleField] || label, 3);
        if (item?.[bodyField]) paragraph(item[bodyField], {font: "16px Arial, sans-serif", lineHeight: 25, indent: 14, maxWidth: contentWidth - 28, after: 4});
        if (item?.[noteField]) paragraph(item[noteField], {font: "italic 14px Georgia, serif", color: "#64758c", lineHeight: 22, indent: 14, maxWidth: contentWidth - 28, after: 10});
      });
      rule();
    });
    if (synthesis.commercialPositioning) { heading("Commercial positioning", 2); paragraph(synthesis.commercialPositioning, {font: "19px Georgia, serif", lineHeight: 30, after: 18}); }

    const dimensions = Object.keys(llmReviewDimensionLabels).map((key) => {
      const scores = reviewed.map((chapter) => chapter.llmReview?.dimensions?.[key]).filter((item) => item && item.applicable !== false && Number(item.score) > 0).map((item) => Number(item.score));
      return {key, count: scores.length, percent: scores.length ? scores.reduce((sum, score) => sum + score, 0) / scores.length / 5 * 100 : 0};
    }).filter((item) => item.count).sort((left, right) => right.percent - left.percent || llmReviewDimensionLabels[left.key].localeCompare(llmReviewDimensionLabels[right.key]));
    if (dimensions.length) {
      heading("Whole-book assessment profile", 2); y += 8;
      dimensions.forEach((item) => {
        ensure(48); const barWidth = Math.max(4, item.percent / 100 * (contentWidth - 330));
        context.fillStyle = "#17365f"; context.font = "700 14px Arial, sans-serif"; context.fillText(llmReviewDimensionLabels[item.key], margin, y);
        context.fillStyle = "#e3eaf3"; context.beginPath(); context.roundRect(margin + 235, y - 12, contentWidth - 300, 13, 7); context.fill();
        context.fillStyle = item.percent >= 80 ? "#28765d" : item.percent >= 60 ? "#a97721" : "#a64c43"; context.beginPath(); context.roundRect(margin + 235, y - 12, barWidth, 13, 7); context.fill();
        context.textAlign = "right"; context.fillStyle = "#425c7b"; context.font = "800 13px Arial, sans-serif"; context.fillText(`${Math.round(item.percent)}%`, width - margin, y); context.textAlign = "left"; y += 42;
      });
      rule();
    }
    if (reviewed.length) {
      heading("Chapter conclusions", 2); y += 8;
      reviewed.forEach((chapter) => {
        const review = chapter.llmReview || {}; ensure(100);
        heading(displayHeading(chapter.title) || `Chapter ${chapter.sequence || chapter.number}`, 3);
        paragraph(review.editorialSummary || review.chapterAssessment || "No significant concerns were found.", {font: "16px Georgia, serif", lineHeight: 25, after: 5});
        [...(review.editorialStrengths || []), ...(review.commercialStrengths || []).map((item) => `Commercial strength: ${item}`), ...(review.commercialRisks || []).map((item) => `Commercial risk: ${item}`)].forEach((item) => paragraph(`• ${item}`, {font: "14px Arial, sans-serif", color: "#526984", lineHeight: 22, indent: 12, maxWidth: contentWidth - 24, after: 1}));
        rule();
      });
    }
  });

  section("smell-report", "Undismissed Smells", () => {
    const smells = reportableSmells(pipeline);
    const rollup = smellRollupData(pipeline);
    heading("Undismissed Smells", 1);
    paragraph(`${smells.length.toLocaleString()} editorial ${smells.length === 1 ? "finding remains" : "findings remain"} in the manuscript.`, {font: "700 19px Arial, sans-serif", color: "#9c493f", lineHeight: 28, after: 22});
    if (rollup.items.length) {
      heading("Most frequent issue types", 2); y += 14;
      rollup.items.slice(0, 20).forEach((item, index) => {
        ensure(48);
        context.fillStyle = index % 2 ? "#fff9f7" : "#fff3ef"; context.beginPath(); context.roundRect(margin, y - 19, contentWidth, 40, 7); context.fill();
        context.fillStyle = "#a64c43"; context.fillRect(margin, y - 19, 5, 40);
        context.fillStyle = "#17365f"; context.font = "700 16px Georgia, serif"; context.fillText(item.label, margin + 18, y + 4);
        context.textAlign = "right"; context.fillStyle = "#91443c"; context.font = "800 13px Arial, sans-serif"; context.fillText(`${item.count} ${item.count === 1 ? "finding" : "findings"} · ${item.chapters.length} ${item.chapters.length === 1 ? "chapter" : "chapters"}`, width - margin - 14, y + 4); context.textAlign = "left"; y += 48;
      });
      if (rollup.items.length > 20) paragraph(`${rollup.items.length - 20} less frequent issue types remain available in Bookinator.`, {font: "13px Arial, sans-serif", color: "#7d625e", after: 14});
      rule(); heading("Findings by chapter", 2); y += 14;
    }
    smells.forEach(({chapter, item}) => {
      ensure(156);
      context.fillStyle = "#fff7f4"; context.beginPath(); context.roundRect(margin, y - 12, contentWidth, 22, 8); context.fill();
      context.fillStyle = "#9c493f"; context.font = "800 13px Arial, sans-serif"; context.fillText(displayHeading(chapter.title) || `Chapter ${chapter.number || chapter.sequence}`, margin + 18, y + 5); y += 38;
      heading(smellRollupIssue(item), 3);
      paragraph(item.judgment?.reason || item.evidence?.[0]?.message || "This sentence deserves editorial attention.", {font: "16px Arial, sans-serif", color: "#4b607b", lineHeight: 25});
      paragraph(`“${item.sentence || ""}”`, {font: "italic 18px Georgia, serif", color: "#7d3e35", lineHeight: 28}); rule();
    });
    if (!smells.length) paragraph("No undismissed Smells are currently saved.");
  });

  if (tocCanvas) {
    const toc = tocCanvas.getContext("2d");
    toc.fillStyle = "#102748"; toc.font = "700 42px Georgia, serif"; toc.fillText("Contents", margin, 186);
    toc.fillStyle = "#64758c"; toc.font = "16px Arial, sans-serif"; toc.fillText("Every section reflects the results saved when this report was created.", margin, 220);
    let tocY = 278;
    sectionStarts.forEach(({title, page}, index) => {
      toc.fillStyle = index % 2 ? "#f7faff" : "#edf4fb"; toc.beginPath(); toc.roundRect(margin, tocY - 25, contentWidth, 54, 7); toc.fill();
      toc.fillStyle = "#2865ae"; toc.font = "800 13px Arial, sans-serif"; toc.fillText(String(index + 1).padStart(2, "0"), margin + 17, tocY + 3);
      toc.fillStyle = "#17365f"; toc.font = "700 19px Georgia, serif"; toc.fillText(title, margin + 60, tocY + 3);
      toc.textAlign = "right"; toc.fillStyle = "#526984"; toc.font = "800 15px Arial, sans-serif"; toc.fillText(String(page), width - margin - 18, tocY + 3); toc.textAlign = "left"; tocY += 66;
    });
  }

  const pageCount = canvases.length;
  const pages = canvases.map((page, index) => {
    const finalPage = document.createElement("canvas"); finalPage.width = pixelWidth; finalPage.height = pixelHeight;
    const pageContext = finalPage.getContext("2d"), footerY = height - 84;
    pageContext.setTransform(renderScale, 0, 0, renderScale, 0, 0); pageContext.fillStyle = "#fff"; pageContext.fillRect(0, 0, width, height); pageContext.drawImage(page, 0, 0, width, height);
    if (!pageMeta[index]?.bare) drawStandardHeader(pageContext, pageMeta[index]?.section || "Editorial report");
    pageContext.strokeStyle = "#d2deee"; pageContext.beginPath(); pageContext.moveTo(margin, footerY - 18); pageContext.lineTo(width - margin, footerY - 18); pageContext.stroke();
    if (logo.complete && logo.naturalWidth) pageContext.drawImage(logo, margin, footerY, 42, 42);
    pageContext.fillStyle = "#143663"; pageContext.font = "700 18px Arial, sans-serif"; pageContext.fillText("Bookinator", margin + 55, footerY + 18);
    pageContext.fillStyle = "#64758c"; pageContext.font = "13px Arial, sans-serif"; pageContext.fillText("Find what the author forgot.", margin + 55, footerY + 37);
    pageContext.textAlign = "right"; pageContext.fillStyle = "#2a4a74"; pageContext.font = "700 14px Arial, sans-serif"; pageContext.fillText(`Page ${index + 1} of ${pageCount}`, width - margin, footerY + 25); pageContext.textAlign = "left";
    return {bytes: bytesFromDataUrl(finalPage.toDataURL("image/jpeg", .93)), width: pixelWidth, height: pixelHeight};
  });
  return jpegPagesPdf(pages, {
    title: `Bookinator - ${book.title} - ${book.author || "Author not specified"}`,
    author: book.author || "",
    subject: only ? `Bookinator ${only} report` : "Bookinator editorial report",
  });
}

function csvCell(value) {
  return `"${String(value ?? "").replaceAll('"', '""')}"`;
}

function installChartExports({dialog, chart, rows, filename, book, analysisLabel, timingLabel, totalSeconds = null}) {
  dialog.querySelectorAll("[data-chart-export]").forEach((button) => button.addEventListener("click", async () => {
    const format = button.dataset.chartExport;
    const svg = chart.querySelector("svg");
    if (!svg) return;
    const serialized = exportableSvg(svg);
    const branded = ["svg", "png"].includes(format) ? await brandedChartSvg(serialized, svg.viewBox.baseVal.width, svg.viewBox.baseVal.height, {book, analysisLabel, timingLabel}) : null;
    if (format === "svg") downloadFile(branded, `${filename}.svg`, "image/svg+xml;charset=utf-8");
    if (format === "csv") {
      const csvRows = [`${csvCell("Chapter")},${csvCell("Elapsed seconds")},${csvCell("Elapsed time")}`, ...rows.map((row) => `${csvCell([row.label, row.title].filter(Boolean).join(" · "))},${csvCell(row.seconds)},${csvCell(formatRunDuration(row.seconds))}`)];
      if (Number.isFinite(totalSeconds)) csvRows.push(`${csvCell("Total project analysis time")},${csvCell(totalSeconds)},${csvCell(formatRunDuration(totalSeconds))}`);
      const csv = csvRows.join("\n");
      downloadFile(`${csv}\n`, `${filename}.csv`, "text/csv;charset=utf-8");
    }
    if (format === "png") {
      const headerAndFooter = 164;
      const canvas = await renderSvgToCanvas(branded, svg.viewBox.baseVal.width, svg.viewBox.baseVal.height + headerAndFooter);
      canvas.toBlob((png) => { if (png) downloadFile(png, `${filename}.png`, "image/png"); }, "image/png");
    }
    if (format === "pdf") {
      const canvas = await renderSvgToCanvas(serialized, svg.viewBox.baseVal.width, svg.viewBox.baseVal.height);
      const pdf = await brandedChartPdf(canvas, {book, analysisLabel, timingLabel});
      downloadFile(pdf, `${filename}.pdf`, "application/pdf");
    }
    button.closest("details")?.removeAttribute("open");
  }));
}

function wrapChartTitle(value, width = 38, limit = 2) {
  const words = String(value || "").trim().split(/\s+/).filter(Boolean);
  const lines = [];
  words.forEach((word) => {
    const current = lines.at(-1) || "";
    if (!current || current.length + word.length + 1 > width) lines.push(word);
    else lines[lines.length - 1] = `${current} ${word}`;
  });
  if (lines.length <= limit) return lines;
  const kept = lines.slice(0, limit);
  kept[limit - 1] = `${kept[limit - 1].slice(0, Math.max(1, width - 1))}…`;
  return kept;
}

function timingChartLabelWidth(rows) {
  const canvas = document.createElement("canvas");
  const context = canvas.getContext?.("2d");
  const measuredWidth = (value, font, fallbackPerCharacter) => {
    const text = String(value || "");
    if (!context) return text.length * fallbackPerCharacter;
    context.font = font;
    return context.measureText(text).width;
  };
  const widest = rows.reduce((maximum, row) => {
    const label = measuredWidth(row.label, "750 13px Inter, sans-serif", 7.2);
    const title = wrapChartTitle(row.title).reduce((width, line) => Math.max(width, measuredWidth(line, "650 11px Inter, sans-serif", 6)), 0);
    return Math.max(maximum, label, title);
  }, 0);
  return Math.ceil(Math.min(250, Math.max(94, widest + 24)));
}

function timingChartRows(pipeline, view) {
  const chapters = pipeline.chapters || [];
  const chapterIdentity = (chapter) => {
    const heading = displayHeading(chapter.title || `Chapter ${chapter.sequence || chapter.number}`).replace(/^chapter\b/i, "Chapter");
    const title = displayHeading(chapter.chapterTitle || "");
    return {label: heading, title, tooltip: title ? `${heading}: ${title}` : heading};
  };
  const durationField = {summaries: "durationSeconds", emotions: "emotionDurationSeconds", tags: "tagDurationSeconds", smells: "smellDurationSeconds", "llm-review": "llmReviewDurationSeconds"}[view];
  if (durationField) {
    const rows = chapters.map((chapter) => ({...chapterIdentity(chapter), seconds: Number(chapter[durationField] || 0), sequence: Number(chapter.sequence || chapter.number || 0)})).filter((item) => item.seconds > 0);
    const rollup = view === "summaries" ? pipeline.wholeBookSummary : view === "llm-review" ? pipeline.wholeBookLlmReview : null;
    if (Number(rollup?.durationSeconds || 0) > 0) rows.push({label: "Summary", title: "Whole book", tooltip: "Whole-book summary", seconds: Number(rollup.durationSeconds)});
    if (view === "llm-review" && Number(rollup?.durationSeconds || 0) > 0) {
      rows[rows.length - 1] = {label: "Synthesis", title: "Whole book", tooltip: "Whole-book LLM Review synthesis", seconds: Number(rollup.durationSeconds)};
    }
    return rows;
  }
  if (view === "chapters") {
    const preparation = [
      ["extraction", "Extraction", "Read and normalize the preserved source"],
      ["structure", "Chapter detection", "Detect chapter boundaries and build the proposed map"],
      ["chapter-archive", "Chapter archive", "Save canonical chapter objects"],
      ["chunking", "Chunking", "Save page-linked dossier inputs"],
    ];
    return preparation.map(([id, label, tooltip]) => {
      const stage = (pipeline.stages || []).find((item) => item.id === id) || {};
      return {label, title: "Chapter Map", tooltip, seconds: Number(pipelineStageDuration(stage, pipeline) || 0)};
    }).filter((item) => item.seconds > 0);
  }
  if (view === "dossiers") {
    const totals = new Map();
    (pipeline.chunks || []).forEach((chunk) => {
      const sequence = Number(chunk.chapterSequence || 0);
      if (!sequence || !Number(chunk.dossierDurationSeconds || 0)) return;
      const chapter = chapters.find((item) => Number(item.sequence || item.number || 0) === sequence) || {};
      const identity = chapterIdentity(chapter);
      const prior = totals.get(sequence) || {...identity, seconds: 0, sequence};
      prior.seconds += Number(chunk.dossierDurationSeconds || 0);
      totals.set(sequence, prior);
    });
    const rows = [...totals.values()].sort((left, right) => left.sequence - right.sequence);
    if (Number(pipeline.wholeBookDossier?.durationSeconds || 0) > 0) rows.push({label: "Dossier", title: "Whole book", tooltip: "Whole-book dossier", seconds: Number(pipeline.wholeBookDossier.durationSeconds)});
    return rows;
  }
  if (view === "inferences") {
    return (pipeline.inferences || [])
      .map((inference) => ({
        label: inference.label || signalLabel(inference.id),
        title: inference.method || "Book-level algorithm",
        tooltip: `${inference.label || signalLabel(inference.id)} · ${inference.method || "Book-level algorithm"}`,
        seconds: Number(inference.durationSeconds || 0),
      }))
      .filter((item) => item.seconds > 0);
  }
  if (view === "pipeline") {
    const stageDefinitions = [
      ["extraction", "Extraction"], ["structure", "Chapter detection"],
      ["chapter-archive", "Chapter archive"], ["chunking", "Chunking"],
      ["summaries", "Chapter summaries"], ["dossiers", "Chunk dossiers"],
      ["emotions", "Emotions"], ["tags", "Tags"], ["smells", "Smells"],
      ["cumulative-context", "Context"], ["llm-review", "LLM Review"],
    ];
    const rows = stageDefinitions.map(([id, label]) => {
      const stage = (pipeline.stages || []).find((item) => item.id === id) || {};
      return {label, tooltip: stage.label || label, seconds: Number(pipelineStageDuration(stage, pipeline) || 0)};
    }).filter((item) => item.seconds > 0);
    const rollups = [
      [pipeline.wholeBookSummary, "Whole-book summary"],
      [pipeline.wholeBookDossier, "Whole-book dossier"],
      [pipeline.questionTracker, "Questions & payoffs"],
      [pipeline.wholeBookLlmReview, "Whole-book LLM Review"],
    ].map(([record, label]) => ({label, tooltip: label, seconds: Number(record?.durationSeconds || 0)})).filter((item) => item.seconds > 0);
    return [...rows, ...rollups];
  }
  return [];
}

function openTimingChart(pipeline, view) {
  const rows = timingChartRows(pipeline, view).map((row, pipelineOrder) => ({...row, pipelineOrder}));
  if (!rows.length) return showInformationDialog({context: "Run timing", title: "No saved timing yet", message: "This view does not have a completed timed result to chart yet."});
  const dialogId = "timing-chart-dialog";
  const titleId = "timing-chart-title";
  const analysisLabel = view === "pipeline" ? "Pipeline" : workspaceTabs.find((tab) => tab.id === view)?.label || signalLabel(view);
  const timingLabel = view === "pipeline" ? "Timing by step" : view === "inferences" ? "Timing by inference" : "Timing by chapter";
  const totalElapsed = rows.reduce((sum, row) => sum + Math.max(0, Number(row.seconds) || 0), 0);
  const book = state.books.find((item) => item.id === state.currentBookId) || {title: "Bookinator manuscript", author: ""};
  const overlay = mountStandardDialog({
    id: dialogId,
    className: "timing-chart-dialog",
    labelledBy: titleId,
    content: `<header class="dialog-heading"><div class="timing-book-identity"><span class="timing-book-icon" data-timing-book-icon></span><span><strong id="${titleId}">${escapeHtml(book.title)}</strong><small>${escapeHtml(book.author || "Author not specified")}</small></span></div><div class="timing-report-identity"><strong>${escapeHtml(analysisLabel)}</strong><small>${escapeHtml(timingLabel)}</small></div></header><div class="timing-chart-toolbar" data-no-dialog-drag><p>${view === "pipeline" ? `<strong>Total project analysis time: ${escapeHtml(formatRunDuration(totalElapsed))}.</strong> ` : ""}Hover for exact elapsed time${["pipeline", "inferences"].includes(view) ? "." : "; select a point to inspect its chapter."}</p><div class="timing-chart-header-actions"><button class="pipeline-control-button" type="button" data-timing-order aria-pressed="false" title="Order: pipeline order. Select to show longest first" aria-label="Reorder timing rows; currently in pipeline order"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M8 6h11M8 12h8M8 18h5"/><path d="M5 4v16M3 18l2 2 2-2"/></svg><small>Reorder</small></button><button class="pipeline-control-button" type="button" data-timing-zero aria-pressed="true" title="Start the elapsed-time axis at zero"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 4v15h15"/><path d="M8 16h.01M8 12h.01M8 8h.01"/></svg><small>Zero</small></button><button class="pipeline-control-button" type="button" data-fit-chart title="Fit the whole chart to the available area"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M8 3H3v5M16 3h5v5M8 21H3v-5M16 21h5v-5"/><path d="m3 8 5-5M21 8l-5-5M3 16l5 5M21 16l-5 5"/></svg><small>Fit</small></button>${chartExportControl()}</div></div><div class="timing-chart-scroll" data-timing-chart></div><div class="timing-tooltip" role="status" hidden></div>`,
  });
  renderIcon(overlay.querySelector("[data-timing-book-icon]"), book.icon, book.title, book.author);
  const chart = overlay.querySelector("[data-timing-chart]");
  const tooltip = overlay.querySelector(".timing-tooltip");
  const chartContentWidth = () => {
    const style = getComputedStyle(chart);
    return Math.floor(chart.clientWidth - parseFloat(style.paddingLeft || 0) - parseFloat(style.paddingRight || 0));
  };
  const render = () => {
    const labelWidth = timingChartLabelWidth(rows), right = 34, top = 42, rowHeight = 66, bottom = 62;
    const width = Math.max(760, chartContentWidth() || 1080);
    const height = top + Math.max(1, rows.length - 1) * rowHeight + bottom;
    const maximum = Math.max(...rows.map((item) => item.seconds), 1);
    const observedMinimum = Math.min(...rows.map((item) => item.seconds));
    const startAtZero = overlay.querySelector("[data-timing-zero]").getAttribute("aria-pressed") === "true";
    const observedSpan = Math.max(1, maximum - observedMinimum);
    const rawMinimum = startAtZero ? 0 : Math.max(0, observedMinimum - Math.max(5, observedSpan * .18));
    const scale = naturalTimeTicks(rawMinimum, maximum);
    const minimum = scale.minimum;
    const domainMaximum = scale.maximum;
    const domain = Math.max(1, domainMaximum - minimum);
    const x = (seconds) => labelWidth + ((seconds - minimum) / domain) * (width - labelWidth - right);
    const y = (index) => top + index * rowHeight;
    const points = rows.map((item, index) => `${x(item.seconds)},${y(index)}`).join(" ");
    const ticks = scale.ticks;
    const plotBottom = y(rows.length - 1);
    const grid = ticks.map((value) => `<line x1="${x(value)}" x2="${x(value)}" y1="${top}" y2="${plotBottom}" class="timing-grid"/><text x="${x(value)}" y="${plotBottom + 30}" text-anchor="middle">${escapeHtml(formatRunDuration(value))}</text>`).join("");
    const nodes = rows.map((item, index) => {
      const target = item.sequence ? ` data-timing-sequence="${item.sequence}"` : "";
      const titleLines = wrapChartTitle(item.title);
      const titleMarkup = titleLines.map((line) => `<tspan class="timing-label-title" x="${labelWidth - 18}" dy="15">${escapeHtml(line)}</tspan>`).join("");
      return `<text class="timing-label" x="${labelWidth - 18}" y="${y(index) - (titleLines.length > 1 ? 15 : titleLines.length ? 7 : -4)}" text-anchor="end"><tspan>${escapeHtml(item.label)}</tspan>${titleMarkup}</text><line x1="${labelWidth}" x2="${width - right}" y1="${y(index)}" y2="${y(index)}" class="timing-row-guide"/><circle cx="${x(item.seconds)}" cy="${y(index)}" r="7" tabindex="0" role="button" data-timing-point data-timing-title="${escapeHtml(item.tooltip || item.label)}" data-timing-elapsed="${escapeHtml(formatRunDuration(item.seconds))}"${target}/>`;
    }).join("");
    chart.innerHTML = `<svg viewBox="0 0 ${width} ${height}" style="width:${width}px;height:${height}px" data-chart-layout-width="${width}" aria-label="Elapsed time by ${view === "pipeline" ? "pipeline step" : view === "inferences" ? "inference" : "chapter"}">${grid}<line x1="${labelWidth}" x2="${width - right}" y1="${plotBottom}" y2="${plotBottom}" class="timing-axis"/><text class="timing-axis-title" x="${labelWidth + (width - labelWidth - right) / 2}" y="${height - 4}" text-anchor="middle">Elapsed time</text><polyline points="${points}" class="timing-line"/>${nodes}</svg>`;
    chart.querySelectorAll("[data-timing-point]").forEach((node) => {
      const showTip = (event) => {
        tooltip.innerHTML = `<strong>${escapeHtml(node.dataset.timingTitle)}</strong><span>${escapeHtml(node.dataset.timingElapsed)} elapsed</span>`;
        tooltip.hidden = false;
        const dialog = overlay.querySelector(".timing-chart-dialog").getBoundingClientRect();
        const rect = node.getBoundingClientRect();
        tooltip.style.left = `${Math.min(dialog.width - 245, Math.max(12, rect.left - dialog.left - 90))}px`;
        tooltip.style.top = `${Math.max(90, rect.top - dialog.top - 66)}px`;
      };
      node.addEventListener("mouseenter", showTip); node.addEventListener("focus", showTip);
      node.addEventListener("mouseleave", () => { tooltip.hidden = true; }); node.addEventListener("blur", () => { tooltip.hidden = true; });
      if (node.dataset.timingSequence) node.addEventListener("click", () => navigateToTimingChapter(Number(node.dataset.timingSequence)));
    });
  };
  const close = () => closeDialog(dialogId);
  const navigateToTimingChapter = (sequence) => {
    close();
    const candidates = [...document.querySelectorAll(".analysis-list > details")].filter((details) => !details.classList.contains("whole-book-analysis"));
    const row = candidates.find((details) => Number(details.dataset.refreshId || 0) === sequence) || candidates.find((details) => Number(details.dataset.sourceSequence || 0) === sequence) || candidates[sequence - 1];
    if (row) { row.open = true; row.scrollIntoView({behavior: "smooth", block: "start"}); }
  };
  const zeroButton = overlay.querySelector("[data-timing-zero]");
  zeroButton.addEventListener("click", () => { zeroButton.setAttribute("aria-pressed", String(zeroButton.getAttribute("aria-pressed") !== "true")); render(); });
  const orderButton = overlay.querySelector("[data-timing-order]");
  orderButton.addEventListener("click", () => {
    const byElapsed = orderButton.getAttribute("aria-pressed") !== "true";
    orderButton.setAttribute("aria-pressed", String(byElapsed));
    orderButton.title = byElapsed ? "Order: longest elapsed time first. Select to restore pipeline order" : "Order: pipeline order. Select to show longest first";
    orderButton.setAttribute("aria-label", byElapsed ? "Reorder timing rows; currently longest elapsed time first" : "Reorder timing rows; currently in pipeline order");
    rows.sort(byElapsed
      ? (left, right) => right.seconds - left.seconds || left.pipelineOrder - right.pipelineOrder
      : (left, right) => left.pipelineOrder - right.pipelineOrder);
    render();
  });
  render();
  const fitButton = overlay.querySelector("[data-fit-chart]");
  const fitChart = () => {
    const svg = chart.querySelector("svg");
    if (!svg) return;
    const fitted = fitButton.getAttribute("aria-pressed") === "true";
    if (!fitted) { svg.style.width = `${svg.viewBox.baseVal.width}px`; svg.style.height = `${svg.viewBox.baseVal.height}px`; return; }
    const scale = Math.min(chart.clientWidth / svg.viewBox.baseVal.width, chart.clientHeight / svg.viewBox.baseVal.height);
    svg.style.width = `${Math.max(1, svg.viewBox.baseVal.width * scale)}px`;
    svg.style.height = `${Math.max(1, svg.viewBox.baseVal.height * scale)}px`;
  };
  fitButton.setAttribute("aria-pressed", "false");
  fitButton.addEventListener("click", () => { fitButton.setAttribute("aria-pressed", String(fitButton.getAttribute("aria-pressed") !== "true")); fitChart(); });
  let resizeFrame = 0;
  new ResizeObserver(() => {
    cancelAnimationFrame(resizeFrame);
    resizeFrame = requestAnimationFrame(() => {
      const svg = chart.querySelector("svg");
      const availableWidth = Math.max(760, chartContentWidth() || 1080);
      if (fitButton.getAttribute("aria-pressed") === "true") fitChart();
      else if (Number(svg?.dataset.chartLayoutWidth || 0) !== availableWidth) render();
    });
  }).observe(overlay.querySelector(".timing-chart-dialog"));
  installChartExports({dialog: overlay, chart, rows, filename: `bookinator-${view}-timing`, book, analysisLabel, timingLabel: view === "pipeline" ? `${timingLabel} · total ${formatRunDuration(totalElapsed)}` : timingLabel, totalSeconds: view === "pipeline" ? totalElapsed : null});
}

function workspaceTaskView({icon, title, subtitle, actions = "", metrics = "", explanationTitle, explanation, collapse = true, error = "", progress = "", content = ""}) {
  return `${workspaceSectionHeading({icon, title, subtitle, actions, metrics, explanationTitle, explanation, collapse})}${error ? `<p class="pipeline-error">${error}</p>` : ""}${progress}${content}`;
}

function provisionalAnalysisNotice(pipeline) {
  if (!pipeline.chapters?.length || pipeline.chapterMapApproved) return "";
  const detail = pipeline.chapterMapSuspicious
    ? "Bookinator found heading anomalies. Analysis can continue against this proposed map while you review them."
    : "Analysis is using the proposed chapter map. You can approve it whenever the structure looks right.";
  return `<p class="pipeline-notice"><strong>Provisional structure.</strong> ${escapeHtml(detail)} Changing a boundary marks dependent results stale and queues fresh work.</p>`;
}

function plannedWorkspaceView(view) {
  const flow = [...view.inputs, view.output];
  return workspaceTaskView({
    icon: view.icon,
    title: view.title,
    subtitle: view.subtitle,
    explanationTitle: view.heading,
    explanation: view.text,
    content: `<section class="planned-workspace-view"><span>${escapeHtml(view.eyebrow)}</span><ol aria-label="Planned information flow">${flow.map((item, index) => `<li${index === flow.length - 1 ? ' class="planned-output"' : ""}><i aria-hidden="true">${index === flow.length - 1 ? "✓" : index + 1}</i><strong>${escapeHtml(item)}</strong></li>`).join("")}</ol><p>This pane is part of the workspace now, but its analysis and editing controls are not wired yet.</p></section>`,
  });
}

async function requireChapterMapApi(requiredFeature = "chapterMapApproval", restartMessage = "Bookinator’s local server is older than this page. Stop ./bin/serve in Terminal, run ./bin/serve again, then press Approve.", minimumVersion = 1) {
  let response;
  try {
    response = await fetch("/api/health", {cache: "no-store"});
  } catch {
    throw new Error("Bookinator’s local server is not reachable. Start ./bin/serve, then try again.");
  }
  const contentType = response.headers.get("content-type") || "";
  if (!response.ok || !contentType.includes("application/json")) throw new Error(restartMessage);
  const health = await response.json();
  if (Number(health?.features?.[requiredFeature] || 0) < minimumVersion) throw new Error(restartMessage);
}

async function changeChapterBoundary(bookId, operation, page) {
  await requireChapterMapApi("chapterMapEditing");
  const response = await fetch(`/api/books/${encodeURIComponent(bookId)}/chapter-map/${operation}`, {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({page: Number(page)}),
  });
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || "Could not update that chapter boundary.");
  state.pipelineSignature = "";
  return result;
}

function reviewChapterMapControl(label = "Review map") {
  return `<button class="pipeline-control-button" data-open-chapter-map type="button" title="Inspect and approve the detected chapter structure"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 4h14v16H5z"/><path d="M8 8h8M8 12h5M8 16h7"/></svg><small>${escapeHtml(label)}</small></button>`;
}

function approveChapterMapControl() {
  return `<button class="pipeline-control-button" data-approve-chapter-map type="button" title="Approve this chapter map for downstream analysis"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="m5 12 4 4L19 6"/></svg><small>Approve</small></button>`;
}

function chapterMapReadyForReview(pipeline) {
  if (typeof pipeline.chapterMapReviewReady === "boolean") return pipeline.chapterMapReviewReady;
  const structure = (pipeline.stages || []).find((stage) => stage.id === "structure");
  return Boolean(pipeline.chapters?.length) && ["complete", "warning"].includes(structure?.status) && !["preparing", "chapter-map"].includes(pipeline.phase);
}

function chapterLengthRollupMarkup(pipeline) {
  const chapters = (pipeline.chapters || []).filter((chapter) => displayHeading(chapter.title).toLocaleLowerCase() !== "front matter");
  if (!chapters.length) return '<div class="pipeline-empty compact"><strong>No chapter lengths yet.</strong><p>Prepare the manuscript to calculate the chapter word counts.</p></div>';
  const points = chapters.map((chapter) => ({
    sequence: Number(chapter.sequence || chapter.number || 0),
    number: reportChapterNumber(chapter),
    title: displayHeading(chapter.chapterTitle) || displayHeading(chapter.title) || `Chapter ${chapter.number || chapter.sequence}`,
    words: Math.max(0, Number(chapter.wordCount || 0)),
  }));
  const ranked = [...points].sort((left, right) => left.words - right.words);
  const maximum = Math.max(...points.map((point) => point.words), 1);
  const middle = Math.floor(ranked.length / 2);
  const median = ranked.length % 2 ? ranked[middle].words : Math.round((ranked[middle - 1].words + ranked[middle].words) / 2);
  const shortest = ranked[0];
  const longest = ranked[ranked.length - 1];
  const ratio = shortest.words ? longest.words / shortest.words : 0;
  const bars = points.map((point) => {
    const width = Math.max(2, point.words / maximum * 100);
    const label = `${point.number} · ${point.title} · ${point.words.toLocaleString()} words`;
    return `<li><button type="button" data-chapter-length-target="${point.sequence}" title="${escapeHtml(label)}" aria-label="Open ${escapeHtml(label)}"><b>${escapeHtml(point.number)}</b><i aria-hidden="true"><em style="--chapter-length:${width}%"></em></i><small>${point.words.toLocaleString()}</small></button></li>`;
  }).join("");
  const stat = (label, point, value = point.words) => `<span><small>${escapeHtml(label)}</small><strong>${Number(value).toLocaleString()} words</strong>${point ? `<em>${escapeHtml(point.number)} · ${escapeHtml(point.title)}</em>` : ""}</span>`;
  return `<section class="chapter-length-rollup"><header><div>${stat("Shortest", shortest)}${stat("Median", null, median)}${stat("Longest", longest)}</div><p>${ratio ? `The longest chapter is ${ratio.toFixed(1)}× the length of the shortest.` : "Chapter lengths are shown in manuscript order."}</p></header><div class="chapter-length-chart"><div class="chapter-length-axis" aria-hidden="true"><span>Chapter</span><span>0</span><span>${Math.round(maximum / 2).toLocaleString()}</span><span>${maximum.toLocaleString()} words</span></div><ol aria-label="Chapter length in words">${bars}</ol></div></section>`;
}

function chapterLengthReportMarkup(pipeline) {
  const chapters = (pipeline.chapters || []).filter((chapter) => displayHeading(chapter.title).toLocaleLowerCase() !== "front matter");
  const wordCounts = chapters.map((chapter) => Math.max(0, Number(chapter.wordCount || 0))).sort((left, right) => left - right);
  const middle = Math.floor(wordCounts.length / 2);
  const median = wordCounts.length ? (wordCounts.length % 2 ? wordCounts[middle] : Math.round((wordCounts[middle - 1] + wordCounts[middle]) / 2)) : 0;
  return workspaceTaskView({icon: "chapter-length", title: "Chapter length", subtitle: `${chapters.length.toLocaleString()} authored ${chapters.length === 1 ? "chapter" : "chapters"} · ${median.toLocaleString()} median words.`, actions: reportExportControl("chapter-length"), explanationTitle: "Pacing has a silhouette.", explanation: "Each row is one chapter in reading order. The shared scale makes abrupt changes in chapter size visible without treating consistency as a score.", collapse: false, content: `<article class="editor-report chapter-length-report">${chapterLengthRollupMarkup(pipeline)}</article>`});
}

function chapterHeadingInspectionMarkup(pipeline, book = {}) {
  const report = pipeline.chapterHeadingReport || {};
  const topLevel = report.topLevel?.length
    ? report.topLevel
    : (pipeline.chapters || []).filter((chapter) => displayHeading(chapter.title).toLowerCase() !== "front matter").map((chapter) => ({label: displayHeading(chapter.title), page: chapter.pageStart}));
  if (!topLevel.length) return "";
  const candidates = report.otherCandidates || [];
  const candidateRows = candidates.length
    ? candidates.map((candidate) => {
      const pages = (candidate.pages || []).join(", ");
      const sourceLocation = hasFixedPagination(book) && pages ? `${Number(candidate.count || 0) === 1 ? "page" : "pages"} ${pages}` : "";
      const unique = Number(candidate.count || 0) === 1;
      const demotedPages = candidate.demotedPages || [];
        if (demotedPages.length) {
          const restoreButtons = demotedPages.map((page) => `<button class="heading-restore" data-restore-chapter-page="${Number(page)}" type="button">Restore chapter</button>`).join("");
          return `<div class="heading-candidate demoted"><span><strong>${escapeHtml(displayHeading(candidate.label))}</strong><small>${escapeHtml(`${sourceLocation ? `${sourceLocation} · ` : ""}excluded by the editor and folded into the preceding chapter`)}</small></span>${restoreButtons}</div>`;
        }
        if (candidate.classification && candidate.classification !== "unclassified") {
          return `<div class="heading-candidate explained"><span><strong>${escapeHtml(displayHeading(candidate.label))}</strong><small>${escapeHtml(candidate.explanation || `${sourceLocation ? `${sourceLocation} · ` : ""}explained by the accepted structure`)}</small></span><b>Understood</b></div>`;
        }
        const note = unique
          ? `${sourceLocation ? `${sourceLocation} · ` : ""}excluded opening heading`
          : `${sourceLocation ? `${sourceLocation} · ` : ""}appears ${candidate.count} times, probably a section or viewpoint marker`;
        return `<label class="heading-candidate${candidate.accepted ? " accepted" : ""}${unique ? "" : " repeated"}"><input type="checkbox" data-chapter-variant value="${escapeHtml(candidate.label)}"${candidate.accepted ? " checked" : ""}${unique ? "" : " disabled"}><span><strong>${escapeHtml(displayHeading(candidate.label))}</strong><small>${escapeHtml(note)}</small></span></label>`;
      }).join("")
    : '<p class="heading-family-empty">No other opening headings competed with the chapter pattern.</p>';
  const promotable = candidates.some((candidate) => Number(candidate.count || 0) === 1 && !(candidate.demotedPages || []).length && (!candidate.classification || candidate.classification === "unclassified"));
  const excluded = (pipeline.chapterHeadingReport?.otherCandidates || []).filter((candidate) => !(candidate.accepted || (candidate.demotedPages || []).length || (candidate.classification && candidate.classification !== "unclassified")));
  const warnings = pipeline.chapterMapWarnings || [];
  const tone = warnings.length ? "review" : pipeline.chapterMapApproved ? "approved" : "ready";
  const title = warnings.length
    ? `${warnings.length} structural ${warnings.length === 1 ? "question needs" : "questions need"} a decision.`
    : `${topLevel.length} ${pipeline.chapterMapApproved ? "approved" : "proposed"} ${topLevel.length === 1 ? "chapter follows" : "chapters follow"} the established manuscript pattern.`;
  const detail = warnings.length
    ? "Compare the green chapter family with the amber opening headings before approval."
    : `${excluded.length} other opening ${excluded.length === 1 ? "heading is" : "headings are"} being treated as section or viewpoint markers.`;
  const comparison = `<div class="chapter-heading-comparison"><section class="heading-family accepted-family"><h3>Established chapter pattern</h3><p>These headings define the current authored sequence.</p><ol>${topLevel.map((item) => `<li><strong>${escapeHtml(displayHeading(item.label))}</strong>${hasFixedPagination(book) ? `<span>page ${Number(item.page).toLocaleString()}</span>` : ""}</li>`).join("")}</ol></section><form class="heading-family candidate-family"><h3>Other opening headings</h3><p>Amber headings were excluded. Promote a unique legitimate variant, or restore a boundary you excluded earlier. Repeated labels remain section markers.</p><div class="heading-candidates">${candidateRows}</div>${promotable ? '<button class="secondary-button" data-apply-chapter-variants type="submit">Apply variants & rebuild</button>' : ""}</form></div>`;
  const verdict = `<header class="chapter-map-inspection-verdict ${tone}"><span class="chapter-map-summary-status" aria-hidden="true">${warnings.length ? "!" : "✓"}</span><span class="chapter-map-summary-copy"><strong>${escapeHtml(title)}</strong><small>${escapeHtml(detail)}</small></span></header>`;
  return `<section class="chapter-map-inspection">${verdict}${chapterBoundaryRecoveryMarkup(pipeline)}${comparison}</section>`;
}

function chapterBoundaryRecoveryMarkup(pipeline) {
  const pages = pipeline.demotedChapterBoundaryPages || [];
  if (!pages.length) return "";
  const candidates = pipeline.chapterHeadingReport?.otherCandidates || [];
  const labelForPage = (page) => candidates.find((candidate) => (candidate.demotedPages || []).map(Number).includes(Number(page)))?.label || `Page ${Number(page).toLocaleString()}`;
  return `<section class="chapter-boundary-recovery"><div><strong>${pages.length} excluded chapter ${pages.length === 1 ? "boundary" : "boundaries"}</strong><p>No text was deleted. Each excluded heading was folded into the preceding chapter and can be restored.</p></div><div>${pages.map((page) => `<button class="secondary-button heading-restore" data-restore-chapter-page="${Number(page)}" data-restore-chapter-title="${escapeHtml(displayHeading(labelForPage(page)))}" type="button">Restore ${escapeHtml(displayHeading(labelForPage(page)))}</button>`).join("")}</div></section>`;
}

function compactCharacterCount(value) {
  const count = Number(value || 0);
  if (Math.abs(count) < 1_000) return count.toLocaleString();
  const units = [[1_000_000, "M"], [1_000, "K"]];
  const [divisor, suffix] = units.find(([threshold]) => Math.abs(count) >= threshold);
  return `${(count / divisor).toLocaleString(undefined, {maximumFractionDigits: 1})}${suffix}`;
}

function countedLabel(value, singular, plural = `${singular}s`) {
  const count = Number(value || 0);
  return `${count.toLocaleString()} ${count === 1 ? singular : plural}`;
}

function hasFixedPagination(book) {
  const format = String(book?.sourceFormat || "").toUpperCase();
  const filename = String(book?.sourceFilename || "").toLowerCase();
  return format === "PDF" || (!format && filename.endsWith(".pdf"));
}

function sourcePageRange(book, start, end) {
  if (!hasFixedPagination(book)) return "";
  const first = Number(start || 0);
  const last = Number(end || start || 0);
  return `original ${first === last ? "page" : "pages"} ${first.toLocaleString()}${first === last ? "" : `–${last.toLocaleString()}`}`;
}

function sourcePageCount(book, count) {
  if (!hasFixedPagination(book)) return "";
  return `${Number(count || 0).toLocaleString()} original ${Number(count || 0) === 1 ? "page" : "pages"}`;
}

function sourceMetricParts(metrics, range = "") {
  const characterCount = Number(metrics.characterCount || metrics.inputCharacters || 0);
  return {
    primary: Number.isFinite(Number(metrics.wordCount)) ? {text: countedLabel(metrics.wordCount, "word")} : null,
    middle: [
      characterCount ? {text: `${compactCharacterCount(characterCount)} characters`, accessible: countedLabel(characterCount, "character")} : null,
      Number.isFinite(Number(metrics.paragraphCount)) ? {text: countedLabel(metrics.paragraphCount, "paragraph")} : null,
      Number.isFinite(Number(metrics.sectionCount)) ? {text: countedLabel(metrics.sectionCount, "section")} : null,
    ].filter(Boolean),
    pages: range ? {text: range} : null,
  };
}

function sourceMetricsMarkup(metrics, range = "", {className = "", title = "", caption = ""} = {}) {
  const parts = sourceMetricParts(metrics, range);
  if (!parts.primary && !parts.middle.length && !parts.pages) return "";
  const metric = (part) => `<span${part.accessible ? ` aria-label="${escapeHtml(part.accessible)}"` : ""}>${escapeHtml(part.text)}</span>`;
  return `<span class="source-metric-stack ${escapeHtml(className)}"${title ? ` title="${escapeHtml(title)}"` : ""}>${caption ? `<small class="source-metric-caption">${escapeHtml(caption)}</small>` : ""}${parts.primary ? `<strong class="source-metric-primary">${metric(parts.primary)}</strong>` : ""}${parts.middle.length ? `<span class="source-metric-middle">${parts.middle.map(metric).join("")}</span>` : ""}${parts.pages ? `<strong class="source-metric-pages">${metric(parts.pages)}</strong>` : ""}</span>`;
}

function analysisRowColumns({identity, metadata = "", reporting = ""}) {
  return `<span class="analysis-row-identity">${identity}</span><span class="analysis-row-metadata">${metadata}</span><span class="analysis-row-reporting">${reporting}</span>`;
}

function analysisStatusControl({status = "pending", label = "", inspectable = true, title = "Show run details", trigger = "analysis"} = {}) {
  const normalized = ["blocked", "ready"].includes(status) ? "pending" : status;
  const statusLabel = label || (normalized === "pending" ? "Waiting" : signalLabel(normalized));
  const triggerAttribute = trigger === "stage" ? "data-show-stage-details" : "data-show-reading-details";
  const attributes = inspectable ? ` ${triggerAttribute} type="button" title="${escapeHtml(title)}"` : "";
  const tag = inspectable ? "button" : "span";
  return `<${tag} class="chapter-status"${attributes}>${escapeHtml(statusLabel)}</${tag}>`;
}

function chapterSourceButton(sourceSequence, heading) {
  if (!sourceSequence) return "";
  return `<button class="chapter-source-eye" type="button" data-view-chapter-source="${escapeHtml(sourceSequence)}" data-no-dialog-drag aria-label="View ${escapeHtml(heading)} manuscript text" title="View chapter"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M2.5 12s3.5-6 9.5-6 9.5 6 9.5 6-3.5 6-9.5 6-9.5-6-9.5-6Z"/><circle cx="12" cy="12" r="2.7"/></svg></button>`;
}

function chapterSourceMetadata(sourceSequence, heading, stats) {
  return `<span class="chapter-source-metadata">${chapterSourceButton(sourceSequence, heading)}${stats}</span>`;
}

function wholeBookAnalysisRow(pipeline, kind = "summaries", book = {}) {
  const metrics = pipeline.manuscriptMetrics || {};
  if (kind !== "chapters" && !Number(metrics.pageCount || 0)) return "";
  const mapReady = chapterMapReadyForReview(pipeline);
  const definitions = {
    chapters: {
      label: "Map",
      subtitle: "Organized",
      status: !mapReady ? "running" : pipeline.chapterMapSuspicious ? "review" : pipeline.chapterMapApproved ? "complete" : "ready",
      statusLabel: !mapReady ? "Running" : pipeline.chapterMapSuspicious ? "Review" : pipeline.chapterMapApproved ? "Approved" : "Proposed",
      body: "The chapter designations, manuscript totals, and heading comparison are one structural map.",
    },
    summaries: {
      label: "Summary",
      subtitle: "Synthesis",
      status: pipeline.wholeBookSummary?.status === "running" && !(pipeline.status === "running" && pipeline.phase === "whole-summary") ? "ready" : pipeline.wholeBookSummary?.status || "blocked",
      body: "Bookinator will combine the chapter summaries into one book-level reading after every required chapter analysis is current.",
    },
    dossiers: {
      label: "Dossier",
      subtitle: "Reconciled",
      status: pipeline.wholeBookDossier?.status || (pipeline.dossierProgress?.total && pipeline.dossierProgress.completed >= pipeline.dossierProgress.total ? "ready" : "blocked"),
      body: "Bookinator will reconcile the chunk dossiers into one evidence-linked memory of the book after every source chunk is current.",
    },
    "llm-review": {
      label: "LLM Review",
      subtitle: "Whole-book synthesis",
      status: pipeline.wholeBookLlmReview?.status || "blocked",
      body: "After every chapter review is current, the primary reader will reconcile the evidence into one whole-book editorial judgment.",
    },
  };
  const definition = definitions[kind] || definitions.summaries;
  const structureStage = (pipeline.stages || []).find((stage) => stage.id === "structure") || {};
  const rollup = kind === "chapters" ? structureStage : kind === "summaries" ? pipeline.wholeBookSummary || {} : kind === "dossiers" ? pipeline.wholeBookDossier || {} : kind === "llm-review" ? pipeline.wholeBookLlmReview || {} : {};
  const displayRollup = rollup.summary || rollup.synopsis || rollup.content || rollup.overallAssessment ? rollup : rollup.previousResult || {};
  const result = displayRollup.summary || displayRollup.synopsis || displayRollup.content || displayRollup.overallAssessment || "";
  const rawStatus = kind === "chapters" ? definition.status : rollup.status || definition.status;
  const status = rawStatus === "blocked" ? "pending" : rawStatus;
  const statusLabel = definition.statusLabel || (["blocked", "ready", "pending"].includes(status) ? "Waiting" : signalLabel(status));
  const rollupInputs = kind === "summaries"
    ? (pipeline.chapters || []).filter((chapter) => chapter.status === "complete" && displayHeading(chapter.title).toLocaleLowerCase() !== "front matter")
      .map((chapter) => ({summary: chapter.summary, keyPoints: chapter.keyPoints, newQuestions: chapter.newQuestions}))
    : kind === "dossiers"
      ? (pipeline.chunks || []).filter((chunk) => chunk.dossierStatus === "complete" && chunk.dossier)
        .map((chunk) => chunk.dossier)
      : kind === "llm-review"
        ? (pipeline.chapters || []).filter((chapter) => chapter.llmReviewStatus === "complete" && chapter.llmReview)
          .map((chapter) => chapter.llmReview)
      : [];
  const inputCharacters = Number(rollup.inputCharacters || JSON.stringify(rollupInputs).length || 0);
  const model = kind === "chapters" ? "Deterministic parser" : rollup.model || (kind === "dossiers" ? pipeline.configuredDossierModel : pipeline.configuredReaderModel);
  const inputLabel = kind === "chapters"
    ? `${Number(metrics.pageCount || 0).toLocaleString()} source ${hasFixedPagination(book) ? "pages" : "spans"}`
    : kind === "dossiers"
    ? `${rollupInputs.length.toLocaleString()} current chunk ${rollupInputs.length === 1 ? "dossier" : "dossiers"}`
    : kind === "llm-review"
      ? `${rollupInputs.length.toLocaleString()} current chapter ${rollupInputs.length === 1 ? "review" : "reviews"}`
      : `${rollupInputs.length.toLocaleString()} current chapter ${rollupInputs.length === 1 ? "summary" : "summaries"}`;
  const dependencyLabel = kind === "chapters" ? "Extracted manuscript text" : kind === "dossiers" ? "Every source-chunk dossier" : kind === "llm-review" ? "Every chapter LLM Review" : "Every required chapter analysis";
  const stats = sourceMetricsMarkup(metrics, sourcePageCount(book, metrics.pageCount), {className: "analysis-source-stats whole-book-source-stats"});
  const body = kind === "chapters"
    ? chapterHeadingInspectionMarkup(pipeline, book)
    : result
    ? `${displayRollup !== rollup ? '<p class="analysis-stale-notice"><strong>Previous completed synthesis.</strong> Bookinator is waiting to replace it from the current inputs.</p>' : ""}${kind === "dossiers" ? wholeBookDossierMarkup(displayRollup) : kind === "llm-review" ? wholeBookLlmReviewMarkup(displayRollup, {embedded: true}) : `<div class="chapter-editorial-content"><p>${escapeHtml(result)}</p>${analysisSectionMarkup({label: "What this book establishes", icon: "✓", tone: "establishes", items: displayRollup.keyPoints})}${analysisSectionMarkup({label: "Questions resolved", icon: "✓", tone: "facts", items: displayRollup.resolvedQuestions})}${analysisSectionMarkup({label: "Questions still in play", icon: "?", tone: "questions", items: displayRollup.openQuestions})}</div>`}`
    : `<div class="whole-book-empty"><strong>${status === "ready" ? "Ready for whole-book synthesis." : kind === "chapters" ? "The manuscript scope is established." : "This rollup comes after its chapter-level work."}</strong><p>${escapeHtml(rollup.detail || definition.body)}</p></div>`;
  const identity = `<span class="whole-book-mark" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="M5 4.5c2.7-.7 5-.2 7 1.5 2-1.7 4.3-2.2 7-1.5v14c-2.7-.7-5-.2-7 1.5-2-1.7-4.3-2.2-7-1.5z"/><path d="M12 6v14"/><path class="whole-book-star" d="m17.4 7 .5 1.1 1.1.5-1.1.5-.5 1.1-.5-1.1-1.1-.5 1.1-.5z"/></svg></span><span class="chapter-heading"><span class="chapter-title-line"><span>${escapeHtml(definition.label)}</span><small>Whole book</small></span><strong>${escapeHtml(definition.subtitle)}</strong></span>`;
  const inspectable = ["chapters", "summaries", "dossiers", "llm-review"].includes(kind);
  const reporting = analysisStatusControl({
    status,
    label: statusLabel,
    inspectable,
    title: "Show status, model, inputs, and timing",
  });
  const details = inspectable
    ? `<template class="analysis-details-template">${rollup.error ? `<p class="pipeline-error">${escapeHtml(rollup.error)}</p>` : ""}${analysisRunDetails({title: `${definition.label} · whole book`, model, startedAt: rollup.startedAt, completedAt: rollup.completedAt, duration: rollup.durationSeconds, status, inputCharacters, rows: [{label: "State", value: statusLabel}, {label: "Inputs", value: inputLabel}, {label: "Depends on", value: dependencyLabel}]})}</template>`
    : "";
  const refreshKind = kind === "summaries" ? "whole-summary" : kind === "llm-review" ? "whole-llm-review" : "";
  const inspectorKind = kind === "chapters" ? "stage" : kind === "summaries" ? "whole-summary" : kind === "dossiers" ? "whole-dossier" : kind === "llm-review" ? "whole-llm-review" : "";
  const inspectorId = kind === "chapters" ? "structure" : "all";
  const refreshable = Boolean(refreshKind) && ["running", "failed", "complete"].includes(status);
  return `<details class="analysis-row chapter-summary whole-book-analysis ${escapeHtml(status)}" data-analysis-key="whole-book-${escapeHtml(kind)}" data-analysis-heading="${escapeHtml(definition.label)}" data-analysis-subheading="${escapeHtml(definition.subtitle)}" data-analysis-status="${escapeHtml(status)}" data-refresh-kind="${refreshable ? refreshKind : ""}" data-refresh-id="${refreshable ? "all" : ""}" data-inspector-kind="${escapeHtml(inspectorKind)}" data-inspector-id="${escapeHtml(inspectorId)}"><summary class="analysis-row-columns">${analysisRowColumns({identity, metadata: stats, reporting})}</summary><div class="chapter-summary-body">${body}</div>${details}</details>`;
}

function chapterMapRow(chapter, pipeline, book = {}) {
  const title = displayHeading(chapter.title) || `Section ${chapter.sequence || chapter.number}`;
  const subtitle = displayHeading(chapter.chapterTitle);
  const stats = sourceMetricsMarkup(chapter, sourcePageRange(book, chapter.pageStart, chapter.pageEnd), {className: "chapter-map-stats"});
  const frontMatter = title.toLowerCase() === "front matter";
  const authored = (pipeline.chapters || []).filter((item) => displayHeading(item.title).toLowerCase() !== "front matter");
  const firstAuthoredPage = Number(authored[0]?.pageStart || 0);
  const accepted = (pipeline.acceptedChapterLabelVariants || []).some((label) => displayHeading(label).toLowerCase() === title.toLowerCase());
  const numberedSpine = authored.filter((item) => /^chapter\s+(?:\d+|[ivxlcdm]+)\b/i.test(displayHeading(item.title))).length >= 3;
  const standard = /^(?:chapter\b|prologue$|epilogue$|interlude$|part\b)/i.test(title);
  const needsReview = !frontMatter && numberedSpine && !standard && !accepted;
  const validation = frontMatter ? "Front matter" : accepted ? "Accepted variant" : needsReview ? "Needs review" : "Pattern match";
  const validationTone = frontMatter ? "neutral" : needsReview ? "review" : "match";
  const mapReady = chapterMapReadyForReview(pipeline);
  const mapStatus = frontMatter ? "Excluded" : !mapReady ? "Building" : needsReview ? "Review" : pipeline.chapterMapApproved ? "Approved" : "Proposed";
  const mapStatusTone = frontMatter ? "neutral" : !mapReady ? "building" : needsReview ? "review" : pipeline.chapterMapApproved ? "approved" : "proposed";
  const correction = !frontMatter && Number(chapter.pageStart) !== firstAuthoredPage
    ? `<button class="chapter-map-correction" data-demote-chapter data-chapter-page="${Number(chapter.pageStart)}" data-chapter-title="${escapeHtml(title)}" type="button" title="Review whether this heading should be folded into the preceding chapter">Not a chapter…</button>`
    : "";
  const identity = `<span class="chapter-map-sequence">${Number(chapter.sequence || chapter.number || 0).toLocaleString()}</span><span class="chapter-map-title"><strong>${escapeHtml(title)}</strong>${subtitle ? `<small>${escapeHtml(subtitle)}</small>` : ""}<span class="chapter-map-verification"><span class="chapter-validation ${validationTone}"><i>${frontMatter ? "·" : needsReview ? "!" : "✓"}</i>${escapeHtml(validation)}</span>${correction}</span></span>`;
  const reporting = `<span class="chapter-map-status ${mapStatusTone}">${escapeHtml(mapStatus)}</span>`;
  return `<article class="chapter-map-row analysis-row-columns ${validationTone}" data-chapter-map-sequence="${Number(chapter.sequence || chapter.number || 0)}" tabindex="-1">${analysisRowColumns({identity, metadata: chapterSourceMetadata(chapter.sequence || chapter.number, title, stats), reporting})}</article>`;
}

function analysisDisclosure({className = "", status = "pending", key = "", open = false, heading, subheading = "", range, metrics = {}, body, statusBody = "", sourceSequence = "", refreshKind = "", refreshId = "", inspectorKind = refreshKind, inspectorId = refreshId}) {
  const statusControl = analysisStatusControl({status, title: status === "failed" ? "Show error and run details" : "Show run details"});
  const complexity = metrics.sentenceCount ? `${Number(metrics.sentenceCount).toLocaleString()} sentences · ${Number(metrics.averageSentenceWords || 0).toLocaleString()} average words/sentence · ${Number(metrics.sentenceLengthVariation || 0).toLocaleString()} sentence-length variation · ${Number(metrics.lexicalDiversity || 0).toLocaleString()} lexical diversity` : "";
  const sourceStats = sourceMetricsMarkup(metrics, range, {className: "analysis-source-stats", title: complexity});
  const identity = `<span class="chapter-heading"><span class="chapter-title-line"><span>${escapeHtml(heading)}</span></span>${subheading ? `<strong>${escapeHtml(subheading)}</strong>` : ""}</span>`;
  const metadata = sourceSequence ? chapterSourceMetadata(sourceSequence, heading, sourceStats) : sourceStats;
  return `<details class="analysis-row chapter-summary ${escapeHtml(className)} ${escapeHtml(status)}"${key ? ` data-analysis-key="${escapeHtml(key)}"` : ""} data-analysis-heading="${escapeHtml(heading)}" data-analysis-subheading="${escapeHtml(subheading)}" data-analysis-range="${escapeHtml(range || "")}" data-analysis-status="${escapeHtml(status)}" data-refresh-kind="${escapeHtml(refreshKind)}" data-refresh-id="${escapeHtml(refreshId)}" data-inspector-kind="${escapeHtml(inspectorKind)}" data-inspector-id="${escapeHtml(inspectorId)}"${open ? " open" : ""}><summary class="analysis-row-columns">${analysisRowColumns({identity, metadata: metadata, reporting: statusControl})}</summary><div class="chapter-summary-body"><div class="chapter-editorial-content">${body}</div></div><template class="analysis-details-template">${statusBody}</template></details>`;
}

function markAnalysisResultWaiting(kind, id) {
  const body = document.querySelector("#book-workspace-body");
  const row = [...body.querySelectorAll("details.analysis-row")].find((candidate) => candidate.dataset.refreshKind === kind && candidate.dataset.refreshId === id);
  if (!row) return;
  row.classList.remove("failed", "running", "complete", "paused");
  row.classList.add("pending");
  row.dataset.analysisStatus = "pending";
  const badge = row.querySelector("[data-show-reading-details]");
  if (badge) {
    badge.textContent = "waiting";
    badge.title = "Show queued run details";
  }
}

function openAnalysisDetails(button) {
  const row = button.closest("details.analysis-row");
  const template = row?.querySelector("template.analysis-details-template");
  if (!row || !template) return;
  const heading = row.dataset.analysisHeading || "Analysis";
  const subtitle = [row.dataset.analysisSubheading, row.dataset.analysisRange, row.dataset.analysisStatus].filter(Boolean).join(" · ");
  document.querySelector("#reading-details-context").textContent = "Saved model run";
  document.querySelector("#reading-details-title").textContent = `${heading} details`;
  document.querySelector("#reading-details-subtitle").textContent = subtitle;
  document.querySelector("#reading-details-body").innerHTML = template.innerHTML;
  const dialog = document.querySelector("#reading-details-dialog");
  const refresh = document.querySelector("#refresh-analysis-result");
  refresh.hidden = !row.dataset.refreshKind || !row.dataset.refreshId;
  refresh.dataset.refreshKind = row.dataset.refreshKind || "";
  refresh.dataset.refreshId = row.dataset.refreshId || "";
  refresh.dataset.runStatus = row.dataset.analysisStatus || "";
  refresh.textContent = row.dataset.analysisStatus === "running" ? "Restart" : row.dataset.analysisStatus === "failed" ? "Retry" : "Refresh";
  dialog.dataset.resultSignature = `${subtitle}\n${template.innerHTML}`;
  document.querySelector("#restart-pipeline-stage").hidden = true;
  configureRunInspector({kind: row.dataset.inspectorKind, itemId: row.dataset.inspectorId});
  showDialog("reading-details-dialog");
  startReadingDetailsClock();
}

function prettyJsonMarkup(value) {
  const raw = JSON.stringify(value, null, 2);
  if (raw === undefined) return "";
  const tokenPattern = /("(?:\\u[a-fA-F0-9]{4}|\\[^u]|[^\\"])*"\s*:)|("(?:\\u[a-fA-F0-9]{4}|\\[^u]|[^\\"])*")|\b(true|false)\b|\b(null)\b|-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?/g;
  let cursor = 0;
  let markup = "";
  for (const match of raw.matchAll(tokenPattern)) {
    markup += escapeHtml(raw.slice(cursor, match.index));
    const token = match[0];
    const className = match[1] ? "json-key" : match[2] ? "json-string" : match[3] ? "json-boolean" : match[4] ? "json-null" : "json-number";
    markup += `<span class="${className}">${escapeHtml(token)}</span>`;
    cursor = Number(match.index) + token.length;
  }
  return markup + escapeHtml(raw.slice(cursor));
}

function configureRunInspector({kind = "", itemId = ""} = {}) {
  const dialog = document.querySelector("#reading-details-dialog");
  dialog.dataset.inspectorKind = kind || "";
  dialog.dataset.inspectorId = itemId || "";
  dialog.dataset.inspectorArtifact = "";
  dialog.querySelectorAll("[data-run-inspector-view]").forEach((button) => {
    button.disabled = button.dataset.runInspectorView !== "summary" && (!kind || !itemId);
    button.setAttribute("aria-selected", String(button.dataset.runInspectorView === "summary"));
  });
  document.querySelector("#reading-details-body").hidden = false;
  document.querySelector("#reading-details-json").hidden = true;
}

async function showRunInspectorView(view) {
  const dialog = document.querySelector("#reading-details-dialog");
  const summary = document.querySelector("#reading-details-body");
  const jsonView = document.querySelector("#reading-details-json");
  dialog.querySelectorAll("[data-run-inspector-view]").forEach((button) => button.setAttribute("aria-selected", String(button.dataset.runInspectorView === view)));
  summary.hidden = view !== "summary";
  jsonView.hidden = view === "summary";
  if (view === "summary") return;
  jsonView.innerHTML = '<p class="artifact-inspector-loading">Loading saved run data…</p>';
  try {
    let artifact = dialog.dataset.inspectorArtifact ? JSON.parse(dialog.dataset.inspectorArtifact) : null;
    if (!artifact) {
      const response = await fetch(`/api/books/${encodeURIComponent(state.currentBookId)}/analysis/${encodeURIComponent(dialog.dataset.inspectorKind)}/${encodeURIComponent(dialog.dataset.inspectorId)}/artifact`);
      artifact = await response.json();
      if (!response.ok) throw new Error(artifact.error || "The saved run data could not be opened.");
      dialog.dataset.inspectorArtifact = JSON.stringify(artifact);
    }
    const value = artifact[view];
    const fidelity = view === "input" && artifact.inputFidelity === "reconstructed"
      ? "Reconstructed from canonical saved inputs; this may not be the byte-for-byte model request."
      : view === "input" ? "Exact saved input packet." : "Saved structured output.";
    jsonView.innerHTML = value == null
      ? '<div class="pipeline-empty"><strong>This run did not retain that packet.</strong><p>Future or refreshed runs may preserve more forensic detail.</p></div>'
      : `<section class="artifact-inspector"><header><span>${escapeHtml(fidelity)}</span><span>${escapeHtml(artifact.model || "No model recorded")}</span></header><pre tabindex="0"><code>${prettyJsonMarkup(value)}</code></pre></section>`;
  } catch (error) {
    jsonView.innerHTML = `<p class="pipeline-error">${escapeHtml(error.message || "The saved run data could not be opened.")}</p>`;
  }
}

function refreshOpenAnalysisDetails(body) {
  const dialog = document.querySelector("#reading-details-dialog");
  const refresh = document.querySelector("#refresh-analysis-result");
  if (!dialog || dialog.hidden || !refresh?.dataset.refreshKind || !refresh.dataset.refreshId) return;
  const row = [...body.querySelectorAll("details.analysis-row")].find((candidate) => candidate.dataset.refreshKind === refresh.dataset.refreshKind && candidate.dataset.refreshId === refresh.dataset.refreshId);
  const button = row?.querySelector("[data-show-reading-details]");
  const template = row?.querySelector("template.analysis-details-template");
  if (!row || !button || !template) return;
  const subtitle = [row.dataset.analysisSubheading, row.dataset.analysisRange, row.dataset.analysisStatus].filter(Boolean).join(" · ");
  if (dialog.dataset.resultSignature === `${subtitle}\n${template.innerHTML}`) return;
  openAnalysisDetails(button);
}

function chunkMarkup(chunk, openRows = new Set(), book = {}) {
  const status = chunk.dossierStatus || "pending";
  const dossier = chunk.dossier || {};
  const groups = [
    {label: "Facts", icon: "✓", tone: "facts", items: dossier.facts},
    {label: "Events", icon: "→", tone: "events", items: dossier.events},
    {label: "Entities", icon: "◎", tone: "entities", items: dossier.entities},
    {label: "Locations", icon: "⌖", tone: "locations", items: dossier.locations},
    {label: "Time and chronology", icon: "◴", tone: "timeline", grouped: [
      {label: "Current scene time", items: dossier.current_times},
      {label: "Timeline observations", items: dossier.timeline_observations},
    ]},
    ...(!dossier.questionDetails?.length ? [{label: "Questions", icon: "?", tone: "questions", items: dossier.questions}] : []),
    {label: "Promises and reader contracts", icon: "◇", tone: "promises", items: dossier.promises},
    {label: "Evidence", icon: "¶", tone: "evidence", items: dossier.evidence},
  ];
  const result = status === "complete" ? `<p>${escapeHtml(dossier.synopsis || "")}</p>${groups.map((group) => group.grouped ? analysisSectionGroupMarkup({...group, groups: group.grouped}) : analysisSectionMarkup(group)).join("")}${analysisQuestionDetailsMarkup(dossier.questionDetails, "Questions")}` : status === "failed" ? `<p>This source chunk does not have a usable dossier. Select <strong>Failed</strong> for the error and run details.</p>` : `<p>${status === "running" ? "This source chunk is being analyzed now." : "This source chunk has not been analyzed yet."}</p>`;
  const retryDiagnostics = dossier.retryDiagnostics || chunk.dossierRetryDiagnostics || [];
  const attempts = retryDiagnostics.length ? retryDiagnostics.length + (status === "complete" ? 1 : 0) : 1;
  const runDetails = analysisRunDetails({title: "Dossier details", model: chunk.dossierModel, startedAt: chunk.dossierStartedAt, completedAt: chunk.dossierCompletedAt, duration: chunk.dossierDurationSeconds, status, inputCharacters: chunk.inputCharacters, rows: [{label: "Model attempts", value: attempts}, {label: "Source overlap", value: chunk.overlap === "one-page" ? "One page" : "None"}, {label: "Artifact", value: chunk.id, code: true}]});
  const statusBody = `${chunk.dossierError ? `<p class="pipeline-error">${escapeHtml(chunk.dossierError)}</p>` : ""}${runDetails}`;
  return analysisDisclosure({className: "dossier-chunk", status, key: chunk.id, open: openRows.has(chunk.id), heading: displayHeading(chunk.chapterLabel) || `Chapter ${chunk.chapterSequence}`, subheading: `${chunk.chapterTitle ? `${displayHeading(chunk.chapterTitle)} · ` : ""}Chunk ${chunk.chunkInChapter}`, range: sourcePageRange(book, chunk.pageStart, chunk.pageEnd), metrics: chunk, body: result, statusBody, sourceSequence: chunk.chapterSequence, refreshKind: "dossier", refreshId: chunk.sequence});
}

function parseDossierIndexEntry(rawValue) {
  const raw = String(rawValue || "").replace(/\s+/g, " ").trim();
  if (!raw) return {name: "", note: ""};
  const dash = raw.match(/^(.+?)\s+[–—-]\s+(.+)$/);
  if (dash) return {name: dash[1].trim(), note: dash[2].trim()};
  const parenthetical = raw.match(/^(.+?)\s*\(([^()]+)\)\s*$/);
  if (parenthetical) return {name: parenthetical[1].trim(), note: parenthetical[2].trim()};
  return {name: raw, note: ""};
}

function dossierNameTokens(value, singular = false) {
  const normalized = String(value || "").normalize("NFKD").replace(/[‘’]/g, "'").toLocaleLowerCase().replace(/^(?:the|a|an)\s+/, "");
  const tokens = normalized.match(/[a-z0-9]+/g) || [];
  if (!singular) return tokens;
  return tokens.map((token) => {
    if (token.length > 4 && token.endsWith("ies")) return `${token.slice(0, -3)}y`;
    if (token.length > 4 && token.endsWith("sses")) return token.slice(0, -2);
    if (token.length > 3 && token.endsWith("s") && !token.endsWith("ss")) return token.slice(0, -1);
    return token;
  });
}

function dossierNameKey(value) {
  return dossierNameTokens(value).join("");
}

function dossierMorphologyKey(value) {
  return dossierNameTokens(value, true).join("");
}

function dossierPlaceLikeName(value) {
  const tokens = dossierNameTokens(value, true);
  const placeNouns = new Set(["airport", "avenue", "bandshell", "beach", "boulevard", "bridge", "building", "campus", "cavern", "cemetery", "city", "county", "fountain", "harbor", "hill", "hospital", "hotel", "island", "lake", "market", "mountain", "museum", "park", "pier", "planetarium", "plaza", "river", "road", "school", "station", "street", "territory", "trail", "town", "village"]);
  return Boolean(tokens.length && placeNouns.has(tokens[tokens.length - 1]));
}

function dossierEditDistance(left, right) {
  const previous = Array.from({length: right.length + 1}, (_, index) => index);
  for (let row = 1; row <= left.length; row += 1) {
    const current = [row];
    for (let column = 1; column <= right.length; column += 1) {
      current[column] = Math.min(current[column - 1] + 1, previous[column] + 1, previous[column - 1] + (left[row - 1] === right[column - 1] ? 0 : 1));
    }
    previous.splice(0, previous.length, ...current);
  }
  return previous[right.length];
}

function dossierNamesShouldMerge(left, right) {
  const leftKey = dossierNameKey(left);
  const rightKey = dossierNameKey(right);
  if (!leftKey || !rightKey) return false;
  if (leftKey === rightKey || dossierMorphologyKey(left) === dossierMorphologyKey(right)) return true;

  const leftTokens = dossierNameTokens(left, true);
  const rightTokens = dossierNameTokens(right, true);
  const [shorter, longer] = leftTokens.length <= rightTokens.length ? [leftTokens, rightTokens] : [rightTokens, leftTokens];
  const literalExtension = shorter.length >= 2 && shorter.every((token, index) => longer[index] === token) && longer[shorter.length] === "and";
  if (literalExtension) return true;

  const collectiveWords = new Set(["army", "force", "forces", "group", "team", "of", "war"]);
  const collectiveCore = (tokens) => tokens.filter((token) => !collectiveWords.has(token));
  const leftCore = collectiveCore(leftTokens);
  const rightCore = collectiveCore(rightTokens);
  const shorterWasPlural = dossierNameTokens(left).length === 1 && /s$/i.test(String(left).trim()) || dossierNameTokens(right).length === 1 && /s$/i.test(String(right).trim());
  if (shorterWasPlural && leftCore.length === 1 && rightCore.length === 1 && leftCore[0] === rightCore[0]) return true;

  const apostropheTypo = /['’‘]/.test(String(left)) && /['’‘]/.test(String(right)) && Math.min(leftKey.length, rightKey.length) >= 5 && dossierEditDistance(leftKey, rightKey) === 1;
  return apostropheTypo;
}

function mergeDossierIndexGroups(sourceGroups) {
  const parents = sourceGroups.map((_, index) => index);
  const root = (index) => parents[index] === index ? index : (parents[index] = root(parents[index]));
  const unite = (left, right) => {
    const leftRoot = root(left);
    const rightRoot = root(right);
    if (leftRoot !== rightRoot) parents[rightRoot] = leftRoot;
  };
  for (let left = 0; left < sourceGroups.length; left += 1) {
    for (let right = left + 1; right < sourceGroups.length; right += 1) {
      if ([...sourceGroups[left].variants].some((leftName) => [...sourceGroups[right].variants].some((rightName) => dossierNamesShouldMerge(leftName, rightName)))) unite(left, right);
    }
  }
  const merged = new Map();
  sourceGroups.forEach((group, index) => {
    const key = root(index);
    const target = merged.get(key) || {variants: new Set(), notes: new Set(), occurrences: []};
    group.variants.forEach((variant) => target.variants.add(variant));
    group.notes.forEach((note) => target.notes.add(note));
    target.occurrences.push(...group.occurrences);
    merged.set(key, target);
  });
  return [...merged.values()].map((group) => {
    const counts = new Map();
    group.occurrences.forEach((item) => counts.set(item.value, (counts.get(item.value) || 0) + 1));
    const label = [...group.variants].sort((left, right) => (counts.get(right) || 0) - (counts.get(left) || 0) || left.length - right.length || left.localeCompare(right))[0];
    return {...group, label};
  });
}

function dossierIndexGroups(pipeline, field, book = {}) {
  const groups = new Map();
  const completedChunks = (pipeline.chunks || []).filter((chunk) => chunk.dossierStatus === "complete");
  const inferredLocationValues = completedChunks.flatMap((chunk) => (chunk.dossier?.entities || []).filter((value) => dossierPlaceLikeName(parseDossierIndexEntry(value).name)));
  const locationKeys = new Set([...completedChunks.flatMap((chunk) => chunk.dossier?.locations || []), ...inferredLocationValues].map((value) => dossierMorphologyKey(parseDossierIndexEntry(value).name)).filter(Boolean));
  for (const chunk of pipeline.chunks || []) {
    if (chunk.dossierStatus !== "complete") continue;
    if (displayHeading(chunk.chapterLabel).toLocaleLowerCase() === "front matter") continue;
    const rawValues = field === "locations" ? [...chunk.dossier?.locations || [], ...(chunk.dossier?.entities || []).filter((value) => dossierPlaceLikeName(parseDossierIndexEntry(value).name))] : chunk.dossier?.[field] || [];
    const seenValues = new Set();
    for (const rawValue of rawValues) {
      const {name: label, note} = parseDossierIndexEntry(rawValue);
      if (!label) continue;
      if (field === "entities" && locationKeys.has(dossierMorphologyKey(label))) continue;
      const occurrenceKey = dossierMorphologyKey(label);
      if (seenValues.has(occurrenceKey)) continue;
      seenValues.add(occurrenceKey);
      const chapterLabel = displayHeading(chunk.chapterLabel) || `Chapter ${chunk.chapterSequence || "?"}`;
      const authoredNumber = chapterLabel.match(/\b(\d+)\b/)?.[1] || String(chunk.chapterSequence || "?");
      const key = dossierNameKey(label);
      const group = groups.get(key) || {label, variants: new Set(), notes: new Set(), occurrences: []};
      group.variants.add(label);
      if (note) group.notes.add(note);
      group.occurrences.push({
        sequence: Number(chunk.chapterSequence || 0),
        number: authoredNumber,
        chapter: chapterLabel,
        title: displayHeading(chunk.chapterTitle),
        pages: sourcePageRange(book, chunk.pageStart, chunk.pageEnd),
        chunk: Number(chunk.chunkInChapter || 1),
        value: label,
        note,
      });
      groups.set(key, group);
    }
  }
  const results = mergeDossierIndexGroups([...groups.values()]).map((group) => ({
    ...group,
    variants: [...group.variants],
    notes: [...group.notes],
    chapters: [...new Map(group.occurrences.filter((item) => item.sequence).map((item) => [item.sequence, item])).values()].sort((left, right) => left.sequence - right.sequence),
  }));
  for (const group of results) {
    group.closeNames = results
      .filter((candidate) => candidate !== group)
      .map((candidate) => ({...candidate, similarity: dossierNameSimilarity(group.label, candidate.label)}))
      .filter((candidate) => candidate.similarity >= .55)
      .sort((left, right) => right.similarity - left.similarity || left.label.localeCompare(right.label))
      .slice(0, 4);
  }
  return results.sort((left, right) => right.occurrences.length - left.occurrences.length || left.label.localeCompare(right.label));
}

function dossierNameSimilarity(left, right) {
  const a = dossierNameKey(left);
  const b = dossierNameKey(right);
  if (!a || !b) return 0;
  if (a === b) return 1;
  const edit = 1 - dossierEditDistance(a, b) / Math.max(a.length, b.length);
  const containment = (a.includes(b) || b.includes(a)) && Math.min(a.length, b.length) >= 4 ? Math.min(a.length, b.length) / Math.max(a.length, b.length) : 0;
  return Math.max(edit, containment);
}

function dossierAuthoredChapters(pipeline) {
  return (pipeline.chapters || []).filter((chapter) => displayHeading(chapter.title).toLocaleLowerCase() !== "front matter").map((chapter) => {
    const label = displayHeading(chapter.title) || `Chapter ${chapter.sequence || chapter.number || "?"}`;
    return {sequence: Number(chapter.sequence || chapter.number || 0), number: label.match(/\b(\d+)\b/)?.[1] || String(chapter.sequence || chapter.number || "?"), chapter: label, title: displayHeading(chapter.chapterTitle)};
  });
}

function dossierChapterCircle(item, present = true) {
  const title = present ? [item.chapter, item.title, item.pages].filter(Boolean).join(" · ") : `${item.chapter}${item.title ? ` · ${item.title}` : ""} · Not present`;
  return present ? `<button type="button" data-view-chapter-source="${item.sequence}" title="${escapeHtml(title)}">${escapeHtml(item.number)}</button>` : `<span class="absent" title="${escapeHtml(title)}" aria-label="${escapeHtml(title)}">${escapeHtml(item.number)}</span>`;
}

function dossierIndexInspector(detailsMarkup, kind, label) {
  return `<div class="book-index-inspector" data-index-inspector data-index-kind="${escapeHtml(kind)}" data-index-label="${escapeHtml(label)}"><div class="article-tabs book-index-row-tabs" role="tablist" aria-label="Inspect ${escapeHtml(label)}"><button type="button" role="tab" aria-selected="true" data-index-row-tab="details">Details</button><button type="button" role="tab" aria-selected="false" data-index-row-tab="connections">Connections</button></div><section role="tabpanel" data-index-row-panel="details">${detailsMarkup}</section><section role="tabpanel" data-index-row-panel="connections" hidden><div class="pipeline-empty compact"><strong>Connections are ready to inspect.</strong><p>Open this tab to compare shared sections and chapters.</p></div></section></div>`;
}

function dossierInspectCue(label) {
  return `<span class="book-index-disclosure-cue"><span class="sr-only">Inspect ${escapeHtml(label)}</span><svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="10.5" cy="10.5" r="6.5"/><path d="m15.5 15.5 5 5"/></svg><b aria-hidden="true">⌄</b></span>`;
}

function questionTrackerTable(pipeline, book, openRows = new Set()) {
  const tracker = pipeline.questionTracker || {};
  const chapters = new Map(dossierAuthoredChapters(pipeline).map((chapter) => [chapter.sequence, chapter]));
  const items = Array.isArray(tracker.items) ? tracker.items : [];
  if (!items.length) {
    const waiting = (pipeline.dossierProgress?.completed || 0) < (pipeline.dossierProgress?.total || 0);
    return `<div class="pipeline-empty"><strong>${waiting ? "Waiting for the dossiers." : tracker.status === "running" || pipeline.queuedAction === "questions" ? "Reconciliation is in progress." : "No question tracker yet."}</strong><p>${waiting ? "Bookinator will offer the tracker after every dossier is saved." : tracker.status === "running" || pipeline.queuedAction === "questions" ? "One whole-book pass is grouping retellings and looking for supported later payoffs." : "Build it from the completed chapter summaries and dossier questions."}</p></div>`;
  }
  const statusLabels = {resolved: "Resolved", possible: "Possible", open: "Open"};
  const statusRanks = {resolved: 3, possible: 2, open: 1};
  const rows = items.map((item, index) => {
    const status = ["resolved", "possible", "open"].includes(item.status) ? item.status : "open";
    const trigger = chapters.get(Number(item.triggerChapter || 0));
    const resolution = chapters.get(Number(item.resolutionChapter || 0));
    const delta = item.chapterDelta !== null && item.chapterDelta !== undefined && Number.isFinite(Number(item.chapterDelta)) ? Number(item.chapterDelta) : null;
    const key = `question-tracker-${index}-${encodeURIComponent(String(item.question || "").toLocaleLowerCase())}`;
    const retellings = (item.retellings || []).length
      ? `<ul>${item.retellings.map((retelling) => `<li><span>${escapeHtml(retelling.text)}</span>${chapters.get(Number(retelling.chapter || 0)) ? `<span class="question-chapter">${dossierChapterCircle(chapters.get(Number(retelling.chapter || 0)))}</span>` : ""}</li>`).join("")}</ul>`
      : `<p>No separate retelling was preserved.</p>`;
    const payoff = status === "open"
      ? `<p>No supported payoff appears in the completed chapter digests yet.</p>`
      : `<p>${escapeHtml(item.answer || "A possible payoff was found, but its answer was not summarized.")}</p><small>${escapeHtml(item.confidence || "low")} confidence · based on chapter digests, not an exact passage citation</small>`;
    return `<details class="question-tracker-row" data-analysis-key="${escapeHtml(key)}" data-question-row data-question-value-question="${escapeHtml(String(item.question || "").toLocaleLowerCase())}" data-question-value-status="${statusRanks[status]}" data-question-value-source="${Number(item.triggerChapter || 0)}" data-question-value-resolution="${Number(item.resolutionChapter || 0) || 9999}" data-question-value-delta="${delta ?? 9999}"${openRows.has(key) ? " open" : ""}><summary><div class="question-title"><strong>${escapeHtml(item.question || "Untitled question")}</strong><small>${(item.retellings || []).length.toLocaleString()} ${(item.retellings || []).length === 1 ? "retelling" : "retellings"}</small></div><span class="question-status ${status}">${statusLabels[status]}</span><div class="question-chapter">${trigger ? dossierChapterCircle(trigger) : "—"}</div><div class="question-chapter">${resolution ? dossierChapterCircle(resolution) : '<span class="question-none">—</span>'}</div><strong class="question-delta">${delta == null ? "—" : delta === 0 ? "Same" : `+${delta}`}</strong>${dossierInspectCue(item.question || "question")}</summary><div class="question-tracker-details"><section><h5>Retellings</h5>${retellings}</section><section><h5>${status === "resolved" ? "Payoff" : status === "possible" ? "Possible payoff" : "Still in play"}</h5>${payoff}</section></div></details>`;
  }).join("");
  return `<div class="question-tracker-table" data-question-table data-default-sort="source:asc"><header aria-label="Sortable question tracker columns"><span><button type="button" data-question-sort="question" data-sort-first="asc">Question <i aria-hidden="true">↕</i></button></span><span><button type="button" data-question-sort="status" data-sort-first="desc">Success <i aria-hidden="true">↕</i></button></span><span><button type="button" data-question-sort="source" data-sort-first="asc">Source <i aria-hidden="true">↕</i></button></span><span><button type="button" data-question-sort="resolution" data-sort-first="asc">Resolution <i aria-hidden="true">↕</i></button></span><span><button type="button" data-question-sort="delta" data-sort-first="asc">Δ chapter <i aria-hidden="true">↕</i></button></span><span class="book-index-inspect-heading"><span class="sr-only">Inspect</span></span></header>${rows}</div>`;
}

function dossierIndexPanel(kind, groups, chapters, active, openRows = new Set()) {
  const noun = kind === "entities" ? "entity" : "location";
  if (!groups.length) return `<section class="book-index-panel" data-index-panel="${kind}"${active ? "" : " hidden"}><div class="pipeline-empty"><strong>No ${noun} entries yet.</strong><p>Completed dossiers will add them here automatically.</p></div></section>`;
  const rows = groups.map((group) => {
    const present = new Map(group.chapters.map((item) => [item.sequence, item]));
    const chapterLinks = chapters.map((chapter) => dossierChapterCircle(present.get(chapter.sequence) || chapter, present.has(chapter.sequence))).join("");
    const rawForms = group.variants.map((value) => `<li>${escapeHtml(value)}</li>`).join("");
    const dossierNotes = group.notes.length ? `<section><h5>Dossier notes</h5><ul>${group.notes.map((note) => `<li>${escapeHtml(note)}</li>`).join("")}</ul></section>` : "";
    const closeNames = group.closeNames.length ? `<section><h5>Possible close names</h5><ul>${group.closeNames.map((candidate) => `<li><strong>${escapeHtml(candidate.label)}</strong><span>${Math.round(candidate.similarity * 100)}% textual similarity · chapters ${escapeHtml(candidate.chapters.map((item) => item.number).join(", "))}</span></li>`).join("")}</ul><p>Suggestions only. Nothing is merged automatically.</p></section>` : `<section><h5>Possible close names</h5><p>No strong textual match was found.</p></section>`;
    const detailsKey = `book-index-${kind}-${encodeURIComponent(group.label.toLocaleLowerCase())}`;
    const searchText = `${group.label} ${group.variants.join(" ")} ${group.notes.join(" ")} ${group.closeNames.map((item) => item.label).join(" ")} ${group.chapters.map((item) => `${item.chapter} ${item.title}`).join(" ")}`.toLocaleLowerCase();
    const details = `<div class="book-index-inspection"><div class="book-index-name-stack"><section><h5>Names and aliases</h5><ul>${rawForms}</ul></section>${closeNames}</div>${dossierNotes}</div>`;
    return `<details class="book-index-row" data-analysis-key="${escapeHtml(detailsKey)}" data-index-row data-index-kind="${kind}" data-index-label="${escapeHtml(group.label)}" data-index-search="${escapeHtml(searchText)}" data-sort-name="${escapeHtml(group.label.toLocaleLowerCase())}" data-sort-mentions="${group.occurrences.length}" data-sort-chapters="${group.chapters.length}"${openRows.has(detailsKey) ? " open" : ""}><summary><div class="book-index-name"><strong>${escapeHtml(group.label)}</strong><small>${group.variants.length.toLocaleString()} name ${group.variants.length === 1 ? "form" : "forms"}${group.closeNames.length ? ` · ${group.closeNames.length} possible close ${group.closeNames.length === 1 ? "name" : "names"}` : ""}</small></div><span class="book-index-count"><b>${group.occurrences.length.toLocaleString()}</b><small>${group.occurrences.length === 1 ? "mention" : "mentions"}</small></span><div class="book-index-chapters" aria-label="Chapters containing ${escapeHtml(group.label)}">${chapterLinks}</div>${dossierInspectCue(group.label)}</summary>${dossierIndexInspector(details, kind, group.label)}</details>`;
  }).join("");
  return `<section class="book-index-panel" data-index-panel="${kind}" data-default-sort="mentions:desc"${active ? "" : " hidden"}><div class="book-index-table"><header aria-label="Sortable columns"><span role="columnheader" data-sort-column="name" aria-sort="none"><button type="button" data-index-sort="name" data-sort-first="asc">Name <i aria-hidden="true">↕</i></button></span><span role="columnheader" data-sort-column="mentions" aria-sort="none"><button type="button" data-index-sort="mentions" data-sort-first="desc">Mentions <i aria-hidden="true">↕</i></button></span><span role="columnheader" data-sort-column="chapters" aria-sort="none"><button type="button" data-index-sort="chapters" data-sort-first="desc">Chapters <i aria-hidden="true">↕</i></button></span><span class="book-index-inspect-heading" role="columnheader"><span class="sr-only">Inspect</span></span></header>${rows}</div><p class="book-index-empty-filter" hidden>No ${noun} entries match that search.</p></section>`;
}

function dossierTimeEntries(pipeline, book = {}) {
  const entries = [];
  const seen = new Set();
  for (const chunk of pipeline.chunks || []) {
    if (chunk.dossierStatus !== "complete" || displayHeading(chunk.chapterLabel).toLocaleLowerCase() === "front matter") continue;
    const chapter = {sequence: Number(chunk.chapterSequence || 0), number: (displayHeading(chunk.chapterLabel).match(/\b(\d+)\b/) || [])[1] || String(chunk.chapterSequence || "?"), chapter: displayHeading(chunk.chapterLabel), title: displayHeading(chunk.chapterTitle), pages: sourcePageRange(book, chunk.pageStart, chunk.pageEnd), chunk: Number(chunk.chunkInChapter || 1)};
    for (const [field, label] of [["current_times", "Scene time"], ["timeline_observations", "Timeline observation"]]) {
      for (const rawValue of chunk.dossier?.[field] || []) {
        const value = String(rawValue || "").replace(/\s+/g, " ").trim();
        if (field === "timeline_observations" && !isTemporalDossierObservation(value)) continue;
        const key = `${field}|${chapter.sequence}|${value.toLocaleLowerCase()}`;
        if (!value || seen.has(key)) continue;
        seen.add(key);
        entries.push({value, label, chapter});
      }
    }
  }
  return entries.sort((left, right) => right.chapter.sequence - left.chapter.sequence || left.label.localeCompare(right.label) || left.value.localeCompare(right.value));
}

function dossierTimePanel(entries, active, openRows = new Set()) {
  if (!entries.length) return `<section class="book-index-panel" data-index-panel="times"${active ? "" : " hidden"}><div class="pipeline-empty"><strong>No time observations yet.</strong><p>Completed dossiers will add scene times and chronology notes here automatically.</p></div></section>`;
  const rows = entries.map((entry) => {
    const detailsKey = `book-index-times-${entry.chapter.sequence}-${entry.chapter.chunk}-${encodeURIComponent(entry.value.toLocaleLowerCase())}`;
    const details = `<div class="book-index-inspection time-details"><section><h5>Observation type</h5><p>${escapeHtml(entry.label)}</p></section><section><h5>Source</h5><p>${escapeHtml([entry.chapter.chapter, entry.chapter.title, entry.chapter.pages].filter(Boolean).join(" · "))}</p></section></div>`;
    return `<details class="book-index-row time" data-analysis-key="${escapeHtml(detailsKey)}" data-index-row data-index-kind="times" data-index-label="${escapeHtml(entry.value)}" data-index-search="${escapeHtml(`${entry.value} ${entry.label} ${entry.chapter.chapter} ${entry.chapter.title}`.toLocaleLowerCase())}" data-sort-observation="${escapeHtml(entry.value.toLocaleLowerCase())}" data-sort-chapter="${entry.chapter.sequence}"${openRows.has(detailsKey) ? " open" : ""}><summary><div class="book-index-name"><strong>${escapeHtml(entry.value)}</strong><small>${escapeHtml(entry.label)}</small></div><div class="book-index-chapters time-source" aria-label="Source chapter">${dossierChapterCircle(entry.chapter)}</div>${dossierInspectCue(entry.value)}</summary>${dossierIndexInspector(details, "times", entry.value)}</details>`;
  }).join("");
  return `<section class="book-index-panel" data-index-panel="times" data-default-sort="chapter:desc"${active ? "" : " hidden"}><div class="book-index-table times"><header aria-label="Sortable columns"><span role="columnheader" data-sort-column="observation" aria-sort="none"><button type="button" data-index-sort="observation" data-sort-first="asc">Observation <i aria-hidden="true">↕</i></button></span><span role="columnheader" data-sort-column="chapter" aria-sort="none"><button type="button" data-index-sort="chapter" data-sort-first="desc">Chapter <i aria-hidden="true">↕</i></button></span><span class="book-index-inspect-heading" role="columnheader"><span class="sr-only">Inspect</span></span></header>${rows}</div><p class="book-index-empty-filter" hidden>No time observations match that search.</p></section>`;
}

function dossierIntersectionItems(pipeline, book = {}) {
  const items = [];
  for (const kind of ["entities", "locations"]) {
    for (const group of dossierIndexGroups(pipeline, kind, book)) {
      items.push({kind, label: group.label, occurrences: group.occurrences.map((item) => ({...item, chunkKey: `${item.sequence}:${item.chunk}`}))});
    }
  }
  const timeGroups = new Map();
  for (const entry of dossierTimeEntries(pipeline, book)) {
    const key = entry.value.toLocaleLowerCase();
    const group = timeGroups.get(key) || {kind: "times", label: entry.value, occurrences: []};
    group.occurrences.push({...entry.chapter, chunkKey: `${entry.chapter.sequence}:${entry.chapter.chunk}`});
    timeGroups.set(key, group);
  }
  items.push(...timeGroups.values());
  return items;
}

function dossierIntersectionMarkup(pipeline, book, focusKind, focusLabel, showNonInteractions = false) {
  const items = dossierIntersectionItems(pipeline, book);
  const focus = items.find((item) => item.kind === focusKind && item.label === focusLabel);
  if (!focus) return `<div class="pipeline-empty"><strong>That index item is no longer available.</strong><p>Its source dossier may have changed while the pipeline was running.</p></div>`;
  const focusChapters = new Set(focus.occurrences.map((item) => item.sequence));
  const focusChunks = new Set(focus.occurrences.map((item) => item.chunkKey));
  const focusChapterList = [...new Map(focus.occurrences.map((item) => [item.sequence, item])).values()].sort((left, right) => left.sequence - right.sequence);
  const intersections = items.filter((item) => item !== focus).map((item) => {
    const chapters = [...new Map(item.occurrences.filter((occurrence) => focusChapters.has(occurrence.sequence)).map((occurrence) => [occurrence.sequence, occurrence])).values()].sort((left, right) => left.sequence - right.sequence);
    const sameSections = new Set(item.occurrences.filter((occurrence) => focusChunks.has(occurrence.chunkKey)).map((occurrence) => occurrence.chunkKey)).size;
    return {...item, chapters, sameSections};
  }).filter((item) => item.chapters.length).sort((left, right) => right.sameSections - left.sameSections || right.chapters.length - left.chapters.length || right.occurrences.length - left.occurrences.length || left.label.localeCompare(right.label));
  const kindNames = {entities: "Entities", locations: "Locations", times: "Times"};
  const sections = ["entities", "locations", "times"].map((kind) => {
    const related = intersections.filter((item) => item.kind === kind);
    const hitters = related.slice(0, 3).map((item) => item.label).join(", ");
    const rows = related.map((item) => {
      const relationParts = [];
      if (item.sameSections) relationParts.push(`${item.sameSections} same ${item.sameSections === 1 ? "section" : "sections"}`);
      if (item.chapters.length) relationParts.push(`${item.chapters.length} shared ${item.chapters.length === 1 ? "chapter" : "chapters"}`);
      const relation = relationParts.join(" · ");
      const shared = new Map(item.chapters.map((chapter) => [chapter.sequence, chapter]));
      const sharedChapters = `<div class="intersection-chapters" aria-label="Chapters where ${escapeHtml(focus.label)} and ${escapeHtml(item.label)} interact">${focusChapterList.map((chapter) => shared.has(chapter.sequence) ? dossierChapterCircle(shared.get(chapter.sequence)) : `<span class="no-interaction" title="${escapeHtml(chapter.chapter)} · No interaction with ${escapeHtml(item.label)}" aria-label="${escapeHtml(chapter.chapter)} · No interaction with ${escapeHtml(item.label)}">${escapeHtml(chapter.number)}</span>`).join("")}</div>`;
      return `<article class="intersection-row ${item.sameSections ? "same-section" : "same-chapter"}"><button type="button" data-open-connection-item="${item.kind}" data-intersection-label="${escapeHtml(item.label)}" title="Inspect ${escapeHtml(item.label)}"><strong>${escapeHtml(item.label)}</strong><small>${escapeHtml(relation)}</small></button>${sharedChapters}</article>`;
    }).join("");
    return `<details class="intersection-group"><summary><span>${escapeHtml(kindNames[kind])}</span><strong>${related.length.toLocaleString()}</strong><small>${escapeHtml(hitters || "No shared chapter")}</small></summary><div>${rows || `<p>No ${kindNames[kind].toLocaleLowerCase()} share a chapter with this item.</p>`}</div></details>`;
  }).join("");
  return `<div class="book-index-connections${showNonInteractions ? " show-no-interactions" : ""}"><div class="intersection-context"><strong>${focusChapterList.length.toLocaleString()} ${focusChapterList.length === 1 ? "chapter" : "chapters"}</strong><span>Connections share a section or appear elsewhere in the same chapter.</span></div><div class="intersection-legend"><span class="same-section">Same section</span><span class="same-chapter">Same chapter</span><span class="no-interaction-key">No interaction</span><label class="intersection-absence"><input type="checkbox" data-intersection-absences${showNonInteractions ? " checked" : ""}><span>Show chapters with no interaction</span></label></div><div class="intersection-groups">${sections}</div></div>`;
}

function dossierBookIndexMarkup(pipeline, book = {}, activeKind = "entities", showAbsences = false, openRows = new Set(), embedded = false) {
  const entities = dossierIndexGroups(pipeline, "entities", book);
  const locations = dossierIndexGroups(pipeline, "locations", book);
  const times = dossierTimeEntries(pipeline, book);
  const chapters = dossierAuthoredChapters(pipeline);
  const complete = (pipeline.chunks || []).filter((chunk) => chunk.dossierStatus === "complete").length;
  const total = (pipeline.chunks || []).length;
  const content = `<section class="book-index${showAbsences ? " show-absences" : ""}" data-book-index><div class="book-index-tools"><div class="book-index-switch" role="group" aria-label="Book index type"><button type="button" data-index-kind="entities" aria-pressed="${activeKind === "entities"}"><span aria-hidden="true">◎</span><strong>Entities</strong><small>${entities.length.toLocaleString()}</small></button><button type="button" data-index-kind="locations" aria-pressed="${activeKind === "locations"}"><span aria-hidden="true">⌖</span><strong>Locations</strong><small>${locations.length.toLocaleString()}</small></button><button type="button" data-index-kind="times" aria-pressed="${activeKind === "times"}"><span aria-hidden="true">◴</span><strong>Times</strong><small>${times.length.toLocaleString()}</small></button></div><div class="book-index-tool-end"><label class="book-index-absence"${activeKind === "times" ? " hidden" : ""}><input type="checkbox" data-index-absences${showAbsences ? " checked" : ""}><span>Show chapters not present</span></label><label class="book-index-search"><span>Find in this index</span><input type="search" data-index-search placeholder="Name, form, match, or chapter" autocomplete="off"></label></div></div>${dossierIndexPanel("entities", entities, chapters, activeKind === "entities", openRows)}${dossierIndexPanel("locations", locations, chapters, activeKind === "locations", openRows)}${dossierTimePanel(times, activeKind === "times", openRows)}<footer><strong>Reviewable grouping</strong><span>Typographic, plural, and high-confidence aliases share a row; every original dossier form remains inspectable. Other close names remain suggestions.</span></footer></section>`;
  if (embedded) return content;
  return workspaceTaskView({
    icon: "connections",
    title: "Connections",
    subtitle: `${entities.length.toLocaleString()} entities · ${locations.length.toLocaleString()} locations · ${times.length.toLocaleString()} time observations from ${complete.toLocaleString()} of ${total.toLocaleString()} dossiers.`,
    actions: reportExportControl("connections"),
    explanationTitle: "A concordance for the manuscript.",
    explanation: "Names, places, and time observations are collected from completed dossiers and linked back to their chapters. Open any row to inspect its original dossier forms and possible close names.",
    content,
  });
}

function reportableSmells(pipeline) {
  return (pipeline.chapters || []).flatMap((chapter) => (chapter.smell?.candidates || [])
    .filter((item) => item.userStatus === "reported" || (["report", "keep"].includes(item.judgment?.verdict) && item.userStatus !== "dismissed"))
    .map((item) => ({chapter, item})));
}

function reportChapterNumber(chapter) {
  return (displayHeading(chapter.title).match(/\b(\d+)\b/) || [])[1] || String(chapter.number || chapter.sequence || "");
}

function bookSummaryReportMarkup(pipeline) {
  const whole = pipeline.wholeBookSummary || {};
  const displayWhole = String(whole.summary || "").trim() ? whole : whole.previousResult || {};
  const chapters = (pipeline.chapters || []).filter((chapter) => displayHeading(chapter.title).toLocaleLowerCase() !== "front matter" && String(chapter.summary || "").trim());
  const summary = String(displayWhole.summary || "").trim();
  const priorNotice = summary && displayWhole !== whole ? '<p class="analysis-stale-notice"><strong>Previous completed synthesis.</strong> A replacement from the current chapter summaries is waiting in the pipeline.</p>' : "";
  return `<article class="editor-report book-summary-report"><header><p>Editorial overview</p><h2>${summary ? "The story at a glance" : "The whole-book summary is not ready yet"}</h2></header>${priorNotice}${summary ? `<div class="book-summary-lede"><p>${escapeHtml(summary)}</p></div>` : '<div class="pipeline-empty compact"><strong>Finish the Summary rollup first.</strong><p>Chapter summaries remain available below while the whole-book synthesis is unfinished.</p></div>'}<section class="chapter-digest-list"><h3>Chapter summaries</h3>${chapters.map((chapter) => `<article><header><span>${escapeHtml(reportChapterNumber(chapter))}</span><div><strong>${escapeHtml(displayHeading(chapter.title) || `Chapter ${chapter.number || chapter.sequence}`)}</strong>${displayHeading(chapter.chapterTitle) ? `<small>${escapeHtml(displayHeading(chapter.chapterTitle))}</small>` : ""}</div></header><p>${escapeHtml(chapter.summary)}</p></article>`).join("") || "<p>No chapter summaries are complete.</p>"}</section></article>`;
}

function smellsReportMarkup(pipeline) {
  const findings = reportableSmells(pipeline);
  const grouped = new Map();
  findings.forEach(({chapter, item}) => {
    const key = String(chapter.sequence || chapter.number || "");
    if (!grouped.has(key)) grouped.set(key, {chapter, items: []});
    grouped.get(key).items.push(item);
  });
  const content = [...grouped.values()].map(({chapter, items}) => `<section class="report-findings-chapter"><header><span>${escapeHtml(reportChapterNumber(chapter))}</span><div><h3>${escapeHtml(displayHeading(chapter.title) || `Chapter ${chapter.number || chapter.sequence}`)}</h3>${displayHeading(chapter.chapterTitle) ? `<p>${escapeHtml(displayHeading(chapter.chapterTitle))}</p>` : ""}</div><strong>${items.length} ${items.length === 1 ? "finding" : "findings"}</strong></header><div>${items.map((item) => `<article><h4>${escapeHtml(smellRollupIssue(item))}</h4><p>${escapeHtml(item.judgment?.reason || item.evidence?.[0]?.message || "This sentence deserves an editor’s attention.")}</p><blockquote>“${escapeHtml(item.sentence || "")}”</blockquote><button type="button" data-view-source-passage data-chapter-sequence="${Number(chapter.sequence || chapter.number || 0)}" data-character-start="${Number(item.characterStart || 0)}" data-character-end="${Number(item.characterEnd || 0)}" data-passage-sequence="smell-report">Annotate source</button></article>`).join("")}</div></section>`).join("");
  return workspaceTaskView({icon: "smells", title: "Smells report", subtitle: `${findings.length.toLocaleString()} undismissed editorial ${findings.length === 1 ? "finding" : "findings"} across the book.`, actions: reportExportControl("smell-report"), explanationTitle: "Only findings still in play belong here.", explanation: "This report excludes anything you dismissed and keeps every remaining concern connected to its exact sentence.", collapse: false, content: `<article class="editor-report smells-report">${content || '<div class="pipeline-empty"><strong>No undismissed smells.</strong><p>Completed chapters have no surviving editorial findings.</p></div>'}</article>`});
}

function tagsReportMarkup(pipeline) {
  const rollup = tagRollupData(pipeline);
  const frequencyRollup = wholeBookSignalRollupMarkup(pipeline, "tag", new Set(["rollup:tag"]));
  return workspaceTaskView({icon: "tags", title: "Tag frequencies", subtitle: `${rollup.items.length.toLocaleString()} distinct tags across ${rollup.availableChapters.toLocaleString()} of ${rollup.totalChapters.toLocaleString()} chapters.`, actions: reportExportControl("tag-report"), explanationTitle: "Patterns matter more than isolated labels.", explanation: "This report gathers the fixed-vocabulary tags from every completed chapter, then shows how often and how strongly each one appears. Use the group filters to compare atmosphere and meaning, structure and perspective, genre and audience, or other editorial families.", collapse: false, content: `<div class="report-signal-rollup tag-frequency-report">${frequencyRollup}</div>`});
}

function emotionMapReportMarkup(pipeline) {
  const chapters = (pipeline.chapters || []).filter((chapter) => displayHeading(chapter.title).toLocaleLowerCase() !== "front matter");
  const maximumWords = Math.max(...chapters.map((chapter) => Number(chapter.wordCount || 0)), 1);
  const available = chapters.filter((chapter) => chapter.emotionStatus === "complete" && chapter.emotion?.distribution).length;
  const representedEmotions = new Map();
  const track = chapters.map((chapter) => {
    const scale = Math.max(8, Number(chapter.wordCount || 0) / maximumWords * 100);
    const emotions = Object.entries(chapter.emotion?.distribution || {}).filter(([, score]) => Number(score) >= .10).sort((left, right) => Number(right[1]) - Number(left[1]));
    const bars = emotions.map(([label, score]) => {
      const presentation = emotionPresentation[label] || [signalLabel(label), "#8393a8", "●"];
      representedEmotions.set(label, presentation);
      return `<span class="emotion-map-bar" style="--emotion:${presentation[1]};--emotion-score:${Math.max(18, Number(score) * 100)}%" title="${escapeHtml(presentation[0])} · ${Math.round(Number(score) * 100)}%"><i aria-hidden="true">${escapeHtml(presentation[2])}</i><b>${escapeHtml(presentation[0])}</b><small>${Math.round(Number(score) * 100)}%</small></span>`;
    }).join("");
    const heading = displayHeading(chapter.title) || `Chapter ${chapter.number || chapter.sequence}`;
    const title = displayHeading(chapter.chapterTitle || "");
    return `<article class="emotion-map-chapter" aria-label="${escapeHtml(heading)}${title ? ` · ${escapeHtml(title)}` : ""}"><div class="emotion-map-chapter-label"><strong><span>${escapeHtml(reportChapterNumber(chapter))}</span>${escapeHtml(heading)}</strong>${title ? `<b>${escapeHtml(title)}</b>` : ""}<small>${Number(chapter.wordCount || 0).toLocaleString()} words</small></div><div class="emotion-map-length"><div class="emotion-map-bars" style="--chapter-scale:${scale}%">${bars || '<span class="emotion-map-empty">No emotion at 10%+</span>'}</div></div></article>`;
  }).join("");
  const legend = [...representedEmotions.values()].sort((left, right) => left[0].localeCompare(right[0])).map(([label, color, icon]) => `<span><i style="--emotion:${color}">${escapeHtml(icon)}</i>${escapeHtml(label)}</span>`).join("");
  const frequencyRollup = wholeBookSignalRollupMarkup(pipeline, "emotion", new Set(["rollup:emotion"]));
  return workspaceTaskView({icon: "emotions", title: "Emotion map", subtitle: `${available} of ${chapters.length} chapters scored · only emotions at 10% or higher are shown.`, actions: reportExportControl("emotion-map"), explanationTitle: "Length is part of the story shape.", explanation: "The whole-book profile shows emotional frequency and intensity. The map below preserves chapter order and scale so long emotional stretches and abrupt changes remain visible.", collapse: false, content: `<div class="report-signal-rollup">${frequencyRollup}</div><article class="editor-report emotion-map-report"><section class="emotion-map-key" aria-label="Emotion map key"><div><strong>How to read this</strong><span class="emotion-length-key"><i></i>Track length = chapter word count</span><span>Bars = chapter-average emotion at 10% or higher</span></div><div class="emotion-map-legend"><strong>Emotions in this book</strong>${legend || "<span>No completed emotion scores yet.</span>"}</div></section><div class="emotion-map-viewport"><div class="emotion-map-track">${track}</div></div></article>`});
}

function inferenceLedgerMarkup(pipeline) {
  const rows = (pipeline.inferences || []).map((algorithm) => {
    const status = String(algorithm.status || "blocked");
    const statusLabel = ({ready: "Ready", pending: "Queued", blocked: "Waiting", partial: "Partial"})[status] || signalLabel(status);
    const dependencies = (algorithm.dependsOn || []).map(signalLabel).join(" + ") || "Saved analysis";
    return `<article class="inference-step ${escapeHtml(status)}"><span class="inference-step-state" aria-hidden="true"></span><div><h3>${escapeHtml(algorithm.label || signalLabel(algorithm.id))}</h3><p>${escapeHtml(algorithm.detail || "Book-level inference")}</p><small>${escapeHtml(algorithm.method || "Book-level algorithm")} · Inputs: ${escapeHtml(dependencies)}</small></div><span class="inference-step-status">${escapeHtml(statusLabel)}</span></article>`;
  }).join("");
  return `<div class="inference-ledger">${rows || '<div class="pipeline-empty"><strong>No inference algorithms are registered.</strong><p>They will appear here as Bookinator gains whole-book reasoning tools.</p></div>'}</div>`;
}

function exportHistoryMarkup(book, history = []) {
  if (!history.length) return '<div class="export-history-empty">No saved reports yet.</div>';
  return history.map((item) => `<article><span class="export-history-format">${escapeHtml(String(item.format || "file").toUpperCase())}</span><div><strong>${escapeHtml(item.filename || "Bookinator report")}</strong><small>${escapeHtml(new Date(item.createdAt).toLocaleString())} · ${escapeHtml(formatByteSize(item.bytes))}</small><p>${escapeHtml((item.sections || []).map((id) => shareSectionDefinitions.find((definition) => definition.id === id)?.label || signalLabel(id)).join(" · "))}</p></div><div class="export-history-actions"><a href="/api/books/${encodeURIComponent(book.id)}/exports/${encodeURIComponent(item.id)}" download>Download</a><button type="button" data-delete-export="${escapeHtml(item.id)}" data-export-name="${escapeHtml(item.filename || "this report")}">Delete</button></div></article>`).join("");
}

async function refreshExportHistory(book, root) {
  const target = root?.querySelector("[data-export-history]");
  if (!target) return;
  try {
    const response = await fetch(`/api/books/${encodeURIComponent(book.id)}/exports`);
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || "Saved reports could not be loaded.");
    target.innerHTML = exportHistoryMarkup(book, payload.exports || []);
    target.querySelectorAll("[data-delete-export]").forEach((button) => button.addEventListener("click", async () => {
      const confirmed = await confirmAction({context: "Delete saved report", title: `Delete ${button.dataset.exportName}?`, message: "This removes the saved HTML or PDF from this Bookinator workspace. It cannot be recovered from Bookinator.", acceptLabel: "Delete report"});
      if (!confirmed) return;
      const deletion = await fetch(`/api/books/${encodeURIComponent(book.id)}/exports/${encodeURIComponent(button.dataset.deleteExport)}`, {method: "DELETE"});
      const result = await deletion.json();
      if (!deletion.ok) return confirmAction({context: "Delete failed", title: "Bookinator could not delete this report", message: result.error || "The saved file is still present.", acceptLabel: "Close"});
      await refreshExportHistory(book, root);
    }));
  } catch (error) {
    target.innerHTML = `<div class="export-history-empty">${escapeHtml(error.message || "Saved reports could not be loaded.")}</div>`;
  }
}

async function saveExportArtifact(book, content, {filename, mediaType, sections}, root) {
  const response = await fetch(`/api/books/${encodeURIComponent(book.id)}/exports?filename=${encodeURIComponent(filename)}&sections=${encodeURIComponent(sections.join(","))}`, {method: "POST", headers: {"Content-Type": mediaType, "X-Bookinator-Privacy-Audit": "passed"}, body: content});
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.error || "The report could not be saved in this workspace.");
  await refreshExportHistory(book, root);
  return payload.export;
}

function reportExportMarkup(pipeline, book, annotations = []) {
  const chapterSummaries = (pipeline.chapters || []).filter((chapter) => String(chapter.summary || "").trim()).length;
  const smells = reportableSmells(pipeline).length;
  const emotions = (pipeline.chapters || []).filter((chapter) => chapter.emotionStatus === "complete").length;
  const tags = tagRollupData(pipeline).items.length;
  const llmSynthesis = pipeline.wholeBookLlmReview?.status === "complete" && pipeline.wholeBookLlmReview?.overallAssessment;
  const questions = pipeline.questionTracker?.items?.length || 0;
  const comments = annotations.filter((item) => item.status !== "archived").length;
  return workspaceTaskView({icon: "report", title: "Share this analysis", subtitle: "Create a polished PDF or a model-free interactive site for this book.", actions: "", explanationTitle: "A publication, not a data dump.", explanation: "Both exports use saved analysis without including the full source manuscript. The interactive site opens on an ordinary computer and makes no network requests.", collapse: false, content: `<article class="editor-report export-report"><div class="report-export-preview"><div><p>Bookinator one-book report</p><h2>Ready to share</h2><ul><li>${chapterSummaries} chapter summaries</li><li>${comments} human ${comments === 1 ? "comment" : "comments"}</li><li>${emotions} emotion-scored chapters</li><li>${tags} distinct chapter tags</li>${llmSynthesis ? "<li>Whole-book LLM editorial synthesis</li>" : ""}<li>${questions} tracked questions</li><li>${smells} undismissed Smells</li></ul></div><span class="report-export-mark" aria-hidden="true">B</span></div><div class="report-download-actions"><button class="primary-button report-download" type="button" data-download-portable-report>Download interactive HTML</button><button class="secondary-button report-download" type="button" data-download-editor-report>Download PDF</button></div><p class="report-export-note"><strong>Every export passes a local privacy audit.</strong> Selected derived analysis and selected reviewer quotations are retained; the full manuscript, raw model responses, local paths, and network dependencies are rejected.</p><section class="export-history"><header><h3>Saved reports</h3><p>Stored in this book’s local Bookinator workspace.</p></header><div data-export-history><div class="export-history-empty">Loading saved reports…</div></div></section></article>`});
}

const shareSectionDefinitions = [
  {id: "overview", label: "Book summary", formats: ["html", "pdf"]},
  {id: "chapter-length", label: "Chapter length", formats: ["html", "pdf"]},
  {id: "chapters", label: "Chapter summaries", formats: ["html"]},
  {id: "dossier", label: "Dossier synthesis", formats: ["html", "pdf"], available: (pipeline) => pipeline.wholeBookDossier?.status === "complete" && Boolean(pipeline.wholeBookDossier?.synopsis || pipeline.wholeBookDossier?.summary)},
  {id: "reviewer-report", htmlId: "reviewer", label: "Reviewer comments", formats: ["html", "pdf"]},
  {id: "connections", label: "Connections", formats: ["html", "pdf"]},
  {id: "tag-report", htmlId: "tags", label: "Tag frequencies", formats: ["html", "pdf"]},
  {id: "emotion-map", htmlId: "emotions", label: "Emotional texture", formats: ["html", "pdf"]},
  {id: "questions", label: "Questions and payoffs", formats: ["html", "pdf"]},
  {id: "llm-review-report", htmlId: "llm-review", label: "LLM Review", formats: ["html", "pdf"], available: (pipeline) => pipeline.wholeBookLlmReview?.status === "complete" && Boolean(pipeline.wholeBookLlmReview?.overallAssessment)},
  {id: "smell-report", htmlId: "smells", label: "Editorial findings", formats: ["html", "pdf"]},
  {id: "status", htmlId: "method", label: "Analysis status and provenance", formats: ["html", "pdf"]},
];

function exportPreview({format, pipeline, annotations = []}) {
  const definitions = shareSectionDefinitions.filter((item) => item.formats.includes(format) && (!item.available || item.available(pipeline)));
  const chapterCount = (pipeline.chapters || []).filter((chapter) => String(chapter.summary || "").trim()).length;
  const reviewCount = annotations.filter((item) => item.status !== "archived").length;
  const authoredCount = (pipeline.chapters || []).filter((chapter) => displayHeading(chapter.title).toLocaleLowerCase() !== "front matter").length;
  const counts = {chapters: `${chapterCount} chapter summaries`, overview: format === "pdf" ? `${chapterCount} chapter summaries` : "Whole-book synthesis", "chapter-length": `${authoredCount} chapter word counts`, dossier: "Whole-book evidence synthesis", "reviewer-report": `${reviewCount} human ${reviewCount === 1 ? "comment" : "comments"}`, "tag-report": `${tagRollupData(pipeline).items.length} distinct tags`, "llm-review-report": `${(pipeline.chapters || []).filter((chapter) => chapter.llmReviewStatus === "complete").length} chapters plus whole-book synthesis`, "smell-report": `${reportableSmells(pipeline).length} retained findings`, questions: `${pipeline.questionTracker?.items?.length || 0} tracked questions`};
  const id = `export-preview-${format}`;
  const backdrop = mountStandardDialog({id, className: "export-preview-dialog", labelledBy: `${id}-title`, content: `<header class="dialog-heading"><div><p class="context">${format === "html" ? "Interactive HTML" : "Editorial PDF"}</p><h2 id="${id}-title">Choose what to share</h2><p>Only checked analysis and human comments will be written to the exported file.</p></div></header><form><fieldset><legend>Report sections</legend><div class="export-preview-sections">${definitions.map((item) => `<label><input type="checkbox" name="section" value="${escapeHtml(item.id)}" checked><span><strong>${escapeHtml(item.label)}</strong>${counts[item.id] ? `<small>${escapeHtml(counts[item.id])}</small>` : ""}</span></label>`).join("")}</div></fieldset><aside class="export-exclusion"><strong>Always excluded</strong><p>The full manuscript, unselected chapter source text, dismissed findings, model files, and private application data are not placed in this export. If Reviewer comments are included, their selected quotations are included too.</p></aside><footer><button type="button" data-export-cancel>Cancel</button><button class="primary-button" type="submit">Create ${format === "html" ? "interactive report" : "PDF"}</button></footer></form>`});
  return new Promise((resolve) => {
    let settled = false;
    const onEscape = (event) => { if (event.key === "Escape") finish(null); };
    const finish = (value) => { if (settled) return; settled = true; document.removeEventListener("keydown", onEscape, true); closeDialog(id); resolve(value); };
    document.addEventListener("keydown", onEscape, true);
    backdrop.querySelector("[data-export-cancel]").addEventListener("click", () => finish(null));
    backdrop.querySelector(".dialog-close").addEventListener("click", () => finish(null), {once: true});
    backdrop.addEventListener("click", (event) => { if (event.target === backdrop) finish(null); });
    backdrop.querySelector("form").addEventListener("submit", (event) => {
      event.preventDefault();
      const sections = [...backdrop.querySelectorAll('input[name="section"]:checked')].map((input) => input.value);
      if (sections.length) finish(sections);
    });
  });
}

const llmReviewDimensionLabels = {
  narrative_engagement: "Narrative engagement",
  character_likability: "Character likability",
  character_relatability: "Character relatability",
  clarity: "Clarity",
  stakes_and_tension: "Stakes & tension",
  coherence_and_continuity: "Coherence & continuity",
  voice_and_distinctiveness: "Voice & distinctiveness",
  emotional_impact: "Emotional impact",
  genre_and_audience_fit: "Genre & audience fit",
  saleability: "Saleability",
};

function contextCheckpointMarkup(checkpoint = {}, fallbackSummary = "") {
  const summary = checkpoint.storySoFar || fallbackSummary;
  const sections = [
    ["Key events", "◆", "establishes", checkpoint.keyEvents],
    ["Established facts", "✓", "facts", checkpoint.establishedFacts],
    ["Entities and significance", "◎", "establishes", checkpoint.entitiesAndSignificance],
    ["Character states", "◉", "facts", checkpoint.characterStates],
    ["Relationships", "↔", "establishes", checkpoint.relationshipStates],
    ["Who knows what", "◌", "facts", checkpoint.knowledgeStates],
    ["Locations and timeline", "⌖", "establishes", checkpoint.locationsAndTimeline],
    ["Open threads", "?", "questions", checkpoint.openThreads],
    ["Resolved threads", "✓", "facts", checkpoint.resolvedThreads],
    ["Promises to the reader", "→", "questions", checkpoint.readerPromises],
    ["Themes and motifs", "◇", "establishes", checkpoint.themesAndMotifs],
    ["Voice and form", "✦", "facts", checkpoint.voiceAndForm],
  ];
  return `<div class="context-checkpoint">${summary ? `<p>${escapeHtml(summary)}</p>` : ""}${sections.map(([label, icon, tone, items]) => analysisSectionMarkup({label, icon, tone, items})).join("")}</div>`;
}

function annotationsForReviewLead(lead = {}, annotations = [], chapterSequence = 0) {
  const leadStart = Number(lead.characterStart);
  const leadEnd = Number(lead.characterEnd);
  const hasLeadRange = Number.isFinite(leadStart) && Number.isFinite(leadEnd) && leadEnd > leadStart;
  const matches = annotations.filter((annotation) => {
    if (annotation.id === lead.annotationId || (annotation.origin?.proposalId && annotation.origin.proposalId === lead.id)) return true;
    const annotationStart = Number(annotation.characterStart);
    const annotationEnd = Number(annotation.characterEnd);
    const sameChapter = Number(annotation.chapterSequence) === Number(chapterSequence);
    return sameChapter && hasLeadRange && Number.isFinite(annotationStart) && Number.isFinite(annotationEnd)
      && annotationStart < leadEnd && annotationEnd > leadStart;
  });
  return [...new Map(matches.map((annotation) => [annotation.id, annotation])).values()];
}

function linkedReviewAnnotationMarkup(annotation, lead = {}, position = 0, total = 1) {
  if (!annotation) return lead.status === "accepted" ? '<aside class="llm-linked-annotation unavailable"><strong>Human annotation unavailable</strong><p>It may have been permanently deleted.</p></aside>' : "";
  const label = total > 1 ? `Human annotation ${position + 1} of ${total}` : "Human annotation";
  return `<aside class="llm-linked-annotation ${escapeHtml(annotation.status || "open")}"><header><div><span>${label}</span><strong>${escapeHtml(annotationStatusLabel(annotation))}</strong></div>${annotationPriorityControl(annotation)}</header><div class="review-comment-categories">${annotationCategoryBadgesMarkup(annotation)}</div><p>${escapeHtml(annotation.comment || "No reviewer comment was saved.")}</p><footer><button type="button" data-open-annotation="${escapeHtml(annotation.id)}">View annotated passage</button><button type="button" data-open-reviewer>Open Reviewer</button></footer></aside>`;
}

function reviewLeadToolsMarkup({lead = {}, chapterSequence = 0, candidateIndex = null, linkedAnnotations = []} = {}) {
  const proposal = candidateIndex === null;
  const identity = proposal
    ? `data-lead-kind="proposal" data-proposal-id="${escapeHtml(lead.id || "")}"`
    : `data-lead-kind="candidate" data-candidate-chapter="${chapterSequence}" data-candidate-index="${candidateIndex}"`;
  const inspect = proposal
    ? `<button type="button" data-view-review-proposal data-proposal-id="${escapeHtml(lead.id || "")}" data-proposal-chapter="${chapterSequence}">Review in manuscript</button>`
    : `<button type="button" data-view-review-candidate data-candidate-chapter="${chapterSequence}" data-candidate-index="${candidateIndex}">Review in manuscript</button>`;
  const count = linkedAnnotations.length;
  const noteLabel = count ? `${count} manuscript ${count === 1 ? "note" : "notes"}` : "No manuscript notes yet";
  return `<div class="review-lead-tools"><label>Category <select data-review-lead-category ${identity}>${annotationCategoryValues.map((value) => `<option value="${value}"${value === (lead.category || "editorial") ? " selected" : ""}>${escapeHtml(annotationCategoryLabel(value))}</option>`).join("")}</select></label><span class="review-lead-note-count${count ? " has-notes" : ""}">${noteLabel}</span>${inspect}</div>`;
}

function llmReviewCandidateMarkup(review = {}, chapterSequence = 0, {allowPromotion = true, annotations = []} = {}) {
  const candidates = Array.isArray(review.rejectedCandidates) ? review.rejectedCandidates : [];
  const active = candidates.map((candidate, index) => ({candidate, index})).filter(({candidate}) => !["dismissed", "promoted", "accepted"].includes(candidate.status) && !annotationsForReviewLead(candidate, annotations, chapterSequence).length);
  const annotated = candidates.map((candidate, index) => ({candidate, index})).filter(({candidate}) => candidate.status !== "promoted" && (candidate.status === "accepted" || annotationsForReviewLead(candidate, annotations, chapterSequence).length));
  const dismissed = candidates.map((candidate, index) => ({candidate, index})).filter(({candidate}) => candidate.status === "dismissed" && !annotationsForReviewLead(candidate, annotations, chapterSequence).length);
  const row = ({candidate, index}, mode = "active") => {
    const archived = mode === "dismissed";
    const accepted = mode === "annotated";
    const actions = !allowPromotion ? "" : accepted
      ? ""
      : archived
      ? `<button type="button" data-review-candidate-action="reopen" data-candidate-chapter="${chapterSequence}" data-candidate-index="${index}">Restore soft lead</button>`
      : `<button class="primary-button" type="button" data-review-candidate-action="promote" data-candidate-chapter="${chapterSequence}" data-candidate-index="${index}">Promote to significant</button><button type="button" data-review-candidate-action="dismiss" data-candidate-chapter="${chapterSequence}" data-candidate-index="${index}">Dismiss</button>`;
    const linkedAnnotations = annotationsForReviewLead(candidate, annotations, chapterSequence);
    const tools = allowPromotion ? reviewLeadToolsMarkup({lead: candidate, chapterSequence, candidateIndex: index, linkedAnnotations}) : "";
    const annotationMarkup = linkedAnnotations.length
      ? linkedAnnotations.map((annotation, position) => linkedReviewAnnotationMarkup(annotation, candidate, position, linkedAnnotations.length)).join("")
      : candidate.status === "accepted" ? linkedReviewAnnotationMarkup(null, candidate) : "";
    return `<article class="llm-review-candidate${archived ? " dismissed" : accepted ? " accepted" : ""}"><blockquote>“${escapeHtml(candidate.quote || "No source quotation was retained.")}”</blockquote><h5>First-reader criticism</h5><p>${escapeHtml(candidate.comment || "The first reader raised a possible concern.")}</p><h5>Counter-review</h5><p>${escapeHtml(candidate.reason || "The skeptical pass did not affirm this candidate.")}</p>${tools}${annotationMarkup}<footer><span class="llm-candidate-confidence">${Math.round(Number(candidate.confidence || 0) * 100)}% initial confidence</span><span class="llm-candidate-actions">${actions}</span><span class="llm-candidate-message" data-candidate-message role="status" aria-live="polite"></span></footer></article>`;
  };
  const activeMarkup = active.length ? `<details class="llm-review-candidates"><summary><span><strong>Soft leads from the first reader</strong><small>Demoted by the counter-review; preserved for human judgment.</small></span><b>${active.length}</b></summary><div>${active.map((item) => row(item)).join("")}</div></details>` : "";
  const dismissedMarkup = dismissed.length ? `<details class="llm-review-candidates dismissed"><summary><span><strong>Dismissed soft leads</strong><small>Cratered from the active review, but retained for provenance.</small></span><b>${dismissed.length}</b></summary><div>${dismissed.map((item) => row(item, "dismissed")).join("")}</div></details>` : "";
  const annotatedMarkup = annotated.length ? `<details class="llm-review-candidates annotated"><summary><span><strong>Soft leads used in annotations</strong><small>These crossed from machine suggestion into the human editorial record.</small></span><b>${annotated.length}</b></summary><div>${annotated.map((item) => row(item, "annotated")).join("")}</div></details>` : "";
  return activeMarkup + annotatedMarkup + dismissedMarkup;
}

function activeLlmReviewCandidates(review = {}) {
  return (review.rejectedCandidates || []).filter((candidate) => !["dismissed", "promoted", "accepted"].includes(candidate?.status));
}

function llmReviewProposalMarkup(proposal = {}, chapterSequence = 0, annotations = []) {
  const linkedAnnotations = annotationsForReviewLead(proposal, annotations, chapterSequence);
  const status = proposal.status || "proposed";
  const actions = status === "accepted"
    ? ""
    : status === "rejected"
      ? `<span class="llm-proposal-decision rejected">Rejected</span><button type="button" data-review-proposal-action="reopen" data-review-proposal-id="${escapeHtml(proposal.id)}">Reconsider</button>`
      : `<button type="button" data-review-proposal-action="reject" data-review-proposal-id="${escapeHtml(proposal.id)}">Reject</button>`;
  const origin = proposal.origin === "human_promoted_soft_lead" ? '<em class="llm-proposal-origin">Promoted by reviewer</em>' : "";
  const annotationMarkup = linkedAnnotations.length
    ? linkedAnnotations.map((annotation, position) => linkedReviewAnnotationMarkup(annotation, proposal, position, linkedAnnotations.length)).join("")
    : status === "accepted" ? linkedReviewAnnotationMarkup(null, proposal) : "";
  const tools = reviewLeadToolsMarkup({lead: proposal, chapterSequence, linkedAnnotations});
  return `<article class="llm-review-proposal ${escapeHtml(status)}${linkedAnnotations.length ? " has-annotations" : ""}"><header><strong>${escapeHtml(signalLabel(proposal.category))} · ${escapeHtml(signalLabel(proposal.priority))}</strong><span>${origin}${Math.round(Number(proposal.confidence || 0) * 100)}% confidence</span></header><blockquote>“${escapeHtml(proposal.quote)}”</blockquote><p>${escapeHtml(proposal.comment)}</p><dl><div><dt>Reader effect</dt><dd>${escapeHtml(proposal.readerEffect || proposal.whyItMatters || "")}</dd></div><div><dt>Why it may be accidental</dt><dd>${escapeHtml(proposal.intentionalityCheck || "")}</dd></div><div><dt>Revision goal</dt><dd>${escapeHtml(proposal.revisionGoal || proposal.suggestion || "")}</dd></div></dl>${proposal.adjudicationReason ? `<small class="llm-proposal-adjudication">Skeptical pass: ${escapeHtml(proposal.adjudicationReason)}</small>` : ""}${tools}${annotationMarkup}<footer>${actions}<span data-proposal-message role="status"></span></footer></article>`;
}

function optionalChapterRows(pipeline, kind, openRows = new Set(), book = {}, reviewerAnnotations = []) {
  const context = kind === "context";
  const prefix = context ? "context" : "llmReview";
  const chapters = (pipeline.chapters || []).filter((chapter) => displayHeading(chapter.title).toLocaleLowerCase() !== "front matter");
  return chapters.map((chapter, index) => {
    const rawStatus = chapter[`${prefix}Status`] || "pending";
    const status = ["blocked", "ready"].includes(rawStatus) ? "pending" : rawStatus;
    const sequence = Number(chapter.sequence || chapter.number || index + 1);
    const authoredNumber = index + 1;
    const review = chapter.llmReview || {};
    const checkpoint = chapter.context || {};
    const summary = context ? (checkpoint.storySoFar || chapter.contextSummary) : (review.editorialSummary || review.chapterAssessment);
    const contextDetailCount = context ? Object.entries(checkpoint).reduce((count, [key, value]) => count + (key === "storySoFar" ? 0 : Array.isArray(value) ? value.length : 0), 0) : 0;
    const survivingProposals = (review.editorialProposals || []).length;
    const rejectedCandidates = activeLlmReviewCandidates(review).length;
    const consideredCandidates = survivingProposals + rejectedCandidates;
    const metadata = context
      ? `${chapter.contextRebased ? "Rebased checkpoint" : "Incremental checkpoint"}${contextDetailCount ? ` · ${contextDetailCount} retained details` : ""}${chapter.contextModel ? ` · ${chapter.contextModel}` : ""}`
      : consideredCandidates ? `${consideredCandidates} ${consideredCandidates === 1 ? "candidate" : "candidates"} reviewed · ${survivingProposals} significant` : "No candidate concerns";
    const waiting = context
      ? "Story memory waits for this chapter’s summary and dossiers."
      : index === 0
        ? "Ready to review the canonical chapter text."
        : `Waiting for Context ${index} and the canonical chapter text.`;
    const running = context
      ? "Building story memory through this chapter now."
      : `Reviewing the canonical chapter text${index ? ` against Context ${index}` : ""}.`;
    const error = chapter[`${prefix}Error`];
    const displaySummary = !context && !survivingProposals ? "No significant concerns were found." : summary;
    let resultMarkup = "";
    if (summary) {
      if (context) {
        resultMarkup = contextCheckpointMarkup(checkpoint, summary);
      } else {
        const rationaleMarkup = survivingProposals && review.editorialRationale
          ? `<p>${escapeHtml(review.editorialRationale)}</p>`
          : "";
        const annotations = reviewerAnnotations.length ? reviewerAnnotations : (state.reviewerAnnotations.get(book.id) || []);
        const proposalsMarkup = (review.editorialProposals || []).map((proposal) => llmReviewProposalMarkup(proposal, sequence, annotations)).join("");
        resultMarkup = `<p>${escapeHtml(displaySummary)}</p>${rationaleMarkup}${proposalsMarkup ? `<h4>Significant concerns</h4>${proposalsMarkup}` : ""}${llmReviewCandidateMarkup(review, sequence, {annotations})}`;
      }
    }
    const contents = summary
      ? `${resultMarkup}<p class="editorial-method-note">${escapeHtml(metadata)}</p>`
      : error
        ? `<p>This chapter does not have a usable ${context ? "context checkpoint" : "machine review"}. Select <strong>Failed</strong> for the saved error and run details.</p>`
        : `<p>${escapeHtml(status === "running" ? running : waiting)}</p>`;
    const details = `${error ? `<p class="pipeline-error">${escapeHtml(error)}</p>` : ""}${analysisRunDetails({
      title: context ? "Context details" : "LLM Review details",
      model: chapter[`${prefix}Model`],
      startedAt: chapter[`${prefix}StartedAt`],
      completedAt: chapter[`${prefix}CompletedAt`],
      duration: chapter[`${prefix}DurationSeconds`],
      status,
      inputCharacters: chapter.characterCount || chapter.inputCharacters,
      rows: [
        {label: "State", value: status === "pending" ? "Waiting" : signalLabel(status)},
        {label: context ? "Checkpoint" : "Inputs", value: context ? (chapter.contextRebased ? "Five-chapter rebase" : "Incremental") : index ? `Context ${index} + canonical Chapter ${authoredNumber}` : `Canonical Chapter ${authoredNumber}`},
      ],
    })}`;
    const key = `${context ? "context" : "llm-review"}-${sequence}`;
    return analysisDisclosure({
      className: context ? "chapter-context" : "chapter-llm-review",
      status,
      key,
      open: openRows.has(key),
      heading: displayHeading(chapter.title) || `Chapter ${authoredNumber}`,
      subheading: displayHeading(chapter.chapterTitle),
      range: sourcePageRange(book, chapter.pageStart, chapter.pageEnd),
      metrics: chapter,
      body: contents,
      statusBody: details,
      sourceSequence: sequence,
      refreshKind: context ? "context" : "llm-review",
      refreshId: sequence,
    });
  }).join("");
}

function wholeBookReviewList(items, tone, fields) {
  const usable = Array.isArray(items) ? items.filter((item) => item && typeof item === "object") : [];
  if (!usable.length) return '<div class="llm-review-rollup-empty">The whole-book synthesis did not identify a supported item in this category.</div>';
  return `<ul>${usable.map((item) => {
    const title = String(item[fields.title] || "").trim();
    const body = String(item[fields.body] || "").trim();
    const note = String(item[fields.note] || "").trim();
    return `<li class="${escapeHtml(tone)}"><strong>${escapeHtml(title)}</strong>${body ? `<span>${escapeHtml(body)}</span>` : ""}${note ? `<small>${escapeHtml(note)}</small>` : ""}</li>`;
  }).join("")}</ul>`;
}

function wholeBookLlmReviewMarkup(review, {embedded = false} = {}) {
  if (!review?.overallAssessment) return "";
  const strengths = wholeBookReviewList(review.strengths, "strengths", {title: "title", body: "synthesis", note: "significance"});
  const risks = wholeBookReviewList(review.risks, "risks", {title: "title", body: "synthesis", note: "significance"});
  const priorities = wholeBookReviewList(review.editorialPriorities, "priorities", {title: "title", body: "rationale", note: "scope"});
  const readers = wholeBookReviewList(review.likelyReaders, "audience", {title: "reader", body: "fit", note: "caution"});
  const header = embedded ? "" : `<header><div><h2>Whole-book editorial synthesis</h2><p>A separate model pass reconciled the completed chapter assessments into one manuscript-scale judgment.</p></div><span>${Number(review.sourceChapterCount || 0).toLocaleString()} chapters</span></header>`;
  return `<section class="llm-review-rollup whole-book-synthesis">${header}<div class="llm-review-overall"><span>Overall assessment</span><p>${escapeHtml(review.overallAssessment)}</p></div><div class="llm-review-synthesis-grid"><section class="llm-review-rollup-column strengths"><h3>Strengths to preserve</h3>${strengths}</section><section class="llm-review-rollup-column risks"><h3>Whole-book risks</h3>${risks}</section><section class="llm-review-rollup-column priorities"><h3>Editorial priorities</h3>${priorities}</section><section class="llm-review-rollup-column audience"><h3>Likely readers</h3>${readers}</section></div><div class="llm-review-positioning"><strong>Commercial positioning</strong><p>${escapeHtml(review.commercialPositioning || "The supplied chapter assessments did not support a confident positioning claim.")}</p></div></section>`;
}

function llmReviewReportMarkup(pipeline, annotations = []) {
  const complete = (pipeline.chapters || []).filter((chapter) => chapter.llmReviewStatus === "complete" && chapter.llmReview);
  const dimensionEntries = Object.keys(llmReviewDimensionLabels).map((key, order) => {
    const scores = complete.map((chapter) => chapter.llmReview?.dimensions?.[key]).filter((dimension) => dimension && dimension.applicable !== false && Number(dimension.score) > 0).map((dimension) => Number(dimension.score));
    const average = scores.length ? scores.reduce((sum, score) => sum + score, 0) / scores.length : 0;
    return {key, average, count: scores.length, order, percent: average / 5 * 100};
  });
  const sortedDimensions = [...dimensionEntries].sort((left, right) => llmReviewScoreSort === "alphabetical" ? llmReviewDimensionLabels[left.key].localeCompare(llmReviewDimensionLabels[right.key]) : right.percent - left.percent || left.order - right.order);
  const scoreCards = sortedDimensions.map(({key, count, order, percent}) => {
    const tone = !count ? "unavailable" : percent >= 80 ? "strong" : percent >= 60 ? "mixed" : "concern";
    return `<article class="llm-review-score ${tone}" data-review-score="${percent}" data-review-order="${order}" data-review-label="${escapeHtml(llmReviewDimensionLabels[key])}"><span>${escapeHtml(llmReviewDimensionLabels[key])}</span><strong>${count ? Math.round(percent) : "—"}${count ? "<small>%</small>" : ""}</strong><i><em style="width:${count ? percent : 0}%"></em></i></article>`;
  }).join("");
  const chapters = complete.map((chapter) => {
    const review = chapter.llmReview || {};
    const chapterSequence = Number(chapter.sequence || chapter.number || 0);
    const proposals = (review.editorialProposals || []).map((proposal) => llmReviewProposalMarkup(proposal, chapterSequence, annotations)).join("");
    const lens = review.specialistLens?.id ? ` · ${signalLabel(review.specialistLens.id)} lens` : "";
    const hasConcerns = (review.editorialVerdict || ((review.editorialProposals || []).length ? "material_concerns_found" : "no_material_concerns")) === "material_concerns_found";
    const editorialSummary = hasConcerns ? (review.editorialSummary || review.chapterAssessment || "Material editorial concerns found.") : "No significant concerns were found.";
    const strengths = review.editorialStrengths || [];
    const rejectedCount = activeLlmReviewCandidates(review).length;
    return `<details class="llm-review-chapter"><summary><span><strong>${escapeHtml(displayHeading(chapter.title) || `Chapter ${chapter.sequence || chapter.number}`)}</strong><small>${(review.editorialProposals || []).length} significant · ${rejectedCount} soft ${rejectedCount === 1 ? "lead" : "leads"}${escapeHtml(lens)}</small></span><span aria-hidden="true">⌄</span></summary><div><div class="llm-review-verdict ${hasConcerns ? "concerns" : "clear"}"><strong>${hasConcerns ? "Editorial concerns found" : "No significant concerns"}</strong><span>${escapeHtml(editorialSummary)}</span></div>${hasConcerns && review.editorialRationale ? `<p>${escapeHtml(review.editorialRationale)}</p>` : ""}${strengths.length ? `<h4>Strengths worth preserving</h4><ul>${strengths.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>` : ""}${(review.commercialStrengths || []).length ? `<h4>Commercial strengths</h4><ul>${review.commercialStrengths.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>` : ""}${(review.commercialRisks || []).length ? `<h4>Commercial risks</h4><ul>${review.commercialRisks.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>` : ""}${proposals ? `<h4>Significant concerns</h4>${proposals}` : ""}${llmReviewCandidateMarkup(review, Number(chapter.sequence || chapter.number || 0), {annotations})}</div></details>`;
  }).join("");
  const scoreControls = `<div class="llm-review-score-controls"><div><strong>Whole-book assessment profile</strong><span>Average applicable chapter score</span></div><label>Sort <select data-llm-score-sort><option value="score"${llmReviewScoreSort === "score" ? " selected" : ""}>Highest score</option><option value="alphabetical"${llmReviewScoreSort === "alphabetical" ? " selected" : ""}>A–Z</option></select></label></div>`;
  const synthesis = pipeline.wholeBookLlmReview || {};
  const synthesisMarkup = synthesis.status === "complete" && synthesis.overallAssessment
    ? wholeBookLlmReviewMarkup(synthesis)
    : complete.length
      ? `<section class="llm-review-rollup whole-book-synthesis pending"><header><div><h2>Whole-book editorial synthesis</h2><p>${escapeHtml(synthesis.detail || "The separate synthesis pass will run after every chapter review is current.")}</p></div><span>${escapeHtml(synthesis.status === "running" ? "Running" : "Waiting")}</span></header></section>`
      : "";
  return workspaceTaskView({icon: "llm-review-report", title: "LLM Review", subtitle: complete.length ? `${complete.length} chapters reviewed by the primary reader${synthesis.status === "complete" ? " · whole-book synthesis complete" : ""}. Machine judgments remain proposals.` : "The optional first-reader pass has not produced any results yet.", actions: synthesis.status === "complete" ? reportExportControl("llm-review-report") : "", explanationTitle: "Evidence, not a magic score.", explanation: "These ratings describe the model’s current argument about engagement, character appeal, clarity, genre fit, and commercial legibility. They are neither reviewer sign-off nor a prediction of sales.", collapse: false, content: `${synthesisMarkup}${scoreControls}<section class="llm-review-score-grid">${scoreCards}</section><section class="llm-review-chapters">${chapters || '<div class="pipeline-empty"><strong>No machine review yet.</strong><p>Enable LLM Review in Identity. Chapter 1 can start immediately; each later chapter uses only the context accumulated before it.</p></div>'}</section>`});
}

async function showBookPage(bookId, requestedTab = "", requestedInference = "", cachedPipeline = null) {
  clearTimeout(state.pipelineTimer);
  const requestId = ++state.workspaceRequestId;
  const book = state.books.find((item) => item.id === bookId);
  if (!book) return showBooksPage();
  state.currentBookId = book.id;
  localStorage.setItem(currentBookKey, book.id);
  updateAnalysisNavigation();
  const optionalLlmTabs = new Set(["context", "llm-review", "llm-review-report", "assessment"]);
  const candidateTab = workspaceTabs.some((tab) => tab.id === requestedTab) ? requestedTab : rememberedAnalysisTab(bookId);
  const activeTab = !book.llmReviewEnabled && optionalLlmTabs.has(candidateTab) ? "identity" : candidateTab;
  rememberAnalysisTab(bookId, activeTab);
  document.querySelector("#books-page").hidden = true;
  document.querySelector("#pipeline-page").hidden = true;
  document.querySelector("#article-page").hidden = true;
  document.querySelector("#machine-page").hidden = true;
  const bookPage = document.querySelector("#book-page");
  const sameWorkspace = bookPage.dataset.bookId === bookId && bookPage.dataset.activeTab === activeTab;
  if (bookForm.closest("#book-workspace-body") && (!sameWorkspace || activeTab !== "identity")) restoreBookFormToDialog();
  const identitySignature = JSON.stringify({id: book.id, title: book.title, author: book.author, icon: book.icon, priority: book.priority, manuscriptId: book.manuscriptId, sourceFilename: book.sourceFilename, ingestedAt: book.ingestedAt, llmReviewEnabled: book.llmReviewEnabled});
  const sameIdentity = bookPage.dataset.identitySignature === identitySignature;
  const body = document.querySelector("#book-workspace-body");
  const openRows = new Set([...body.querySelectorAll("details[data-analysis-key][open]")].map((details) => details.dataset.analysisKey));
  const priorIndexQuery = body.querySelector("[data-index-search]")?.value || "";
  const priorScrollY = window.scrollY;
  document.querySelector("#book-page").hidden = false;
  document.querySelector("#welcome-dialog").hidden = true;
  document.querySelectorAll(".topbar nav [data-page]").forEach((item) => item.classList.remove("active"));
  document.querySelector('#analysis-nav').classList.add("active");
  if (!sameIdentity) {
    bookPage.dataset.identitySignature = identitySignature;
    delete bookPage.dataset.connectionIntersectionKind;
    delete bookPage.dataset.connectionIntersectionLabel;
    const header = document.querySelector("#book-workspace-header");
    header.innerHTML = `<div class="workspace-page-context"><p class="workspace-page-title">Analysis</p><p>Evidence, reports, and editorial work for this manuscript.</p></div><button type="button" class="workspace-book-icon" id="workspace-book-icon" title="Open book identity" aria-label="Open identity for ${escapeHtml(book.title)}"></button><div class="workspace-book-copy"><h1>${escapeHtml(book.title)}</h1><p>${escapeHtml(book.author || "Author not specified")}</p></div>`;
    renderIcon(document.querySelector("#workspace-book-icon"), book.icon, book.title, book.author);
    document.querySelector("#workspace-book-icon").addEventListener("click", () => navigateWorkspaceTab(book.id, "identity"));
  }
  const workspaceContext = document.querySelector("#book-workspace-header .workspace-page-context");
  workspaceContext.querySelector(".workspace-page-title").textContent = activeTab === "identity" ? "Identity" : "Analysis";
  workspaceContext.querySelector("p:last-child").textContent = activeTab === "identity"
    ? "Title, authorship, priority, provenance, and the visual mark for this manuscript."
    : "Evidence, reports, and editorial work for this manuscript.";
  if (!sameWorkspace) {
    bookPage.dataset.bookId = bookId;
    bookPage.dataset.activeTab = activeTab;
    state.pipelineSignature = "";
    const tabs = document.querySelector("#book-tabs");
    renderWorkspaceNavigation(tabs, book, activeTab);
    body.innerHTML = '<div class="pipeline-loading">Inspecting the local pipeline…</div>';
  }
  document.title = `${book.title} · Bookinator`;
  try {
    const response = cachedPipeline ? null : await fetch(`/api/books/${encodeURIComponent(book.id)}/pipeline`);
    const pipeline = cachedPipeline || await response.json();
    if (requestId !== state.workspaceRequestId) return;
    if (response && !response.ok) throw new Error(pipeline.error || "Pipeline unavailable.");
    state.workspacePipeline = {bookId: book.id, pipeline};
    if (pipeline.globalPipeline) state.globalPipeline = pipeline.globalPipeline;
    const impossibleCompletions = (pipeline.chapters || []).filter((chapter) => chapter.status === "complete" && !String(chapter.summary || "").trim());
    impossibleCompletions.forEach((chapter) => {
      chapter.status = "failed";
      chapter.error = "The saved model response contained no chapter summary. Restart Bookinator, then Resume to retry this chapter.";
    });
    updateWorkspaceTabProgress(document.querySelector("#book-tabs"), pipeline, activeTab);
    if (pipeline.progress && pipeline.chapters?.length) {
      const manuscriptChapters = pipeline.chapters.filter((chapter) => String(chapter.title || "").trim().toLowerCase() !== "front matter");
      const completedChapters = manuscriptChapters.filter((chapter) => chapter.status === "complete");
      const activeModel = (pipeline.stages || []).find((stage) => stage.id === "summaries")?.model;
      const timed = completedChapters.filter((chapter) => chapter.durationSeconds && (!activeModel || chapter.model === activeModel)).sort((left, right) => String(left.completedAt || "").localeCompare(String(right.completedAt || ""))).slice(-5);
      const durations = timed.map((chapter) => Number(chapter.durationSeconds)).filter((duration) => Number.isFinite(duration) && duration > 0);
      pipeline.progress.completed = completedChapters.length;
      pipeline.progress.total = manuscriptChapters.length;
      pipeline.progress.percent = manuscriptChapters.length ? Math.round(completedChapters.length / manuscriptChapters.length * 100) : 0;
      pipeline.progress.etaSeconds = durations.length ? Math.round(durations.reduce((sum, duration) => sum + duration, 0) / durations.length * (manuscriptChapters.length - completedChapters.length)) : null;
      pipeline.progress.etaSampleSize = durations.length;
      pipeline.progress.averageChapterSeconds = durations.length ? Math.round(durations.reduce((sum, duration) => sum + duration, 0) / durations.length) : null;
      pipeline.progress.remainingChapters = manuscriptChapters.length - completedChapters.length;
      pipeline.progress.etaModel = activeModel || "";
    }
    const libraryBook = state.books.find((item) => item.id === book.id);
    if (libraryBook) libraryBook.pipeline = {
      ...libraryBook.pipeline,
      status: pipeline.status,
      summariesCompleted: pipeline.progress?.completed || 0,
      summariesTotal: pipeline.progress?.total || pipeline.chapters?.length || 0,
      updatedAt: pipeline.updatedAt,
    };
    updateGlobalPipelineStatus();
    const signature = JSON.stringify(pipeline);
    if (sameWorkspace && activeTab === "identity" && bookForm.closest("#book-workspace-body")) {
      state.pipelineSignature = signature;
      if (workspacePipelineNeedsPolling(book.id, pipeline)) state.pipelineTimer = setTimeout(() => showBookPage(book.id, activeTab), pipeline.status === "queued" ? 500 : 1800);
      return;
    }
    if (sameWorkspace && signature === state.pipelineSignature) {
      if (workspacePipelineNeedsPolling(book.id, pipeline)) state.pipelineTimer = setTimeout(() => showBookPage(book.id, activeTab), pipeline.status === "queued" ? 500 : 1800);
      return;
    }
    const running = pipeline.status === "running";
    const queued = pipeline.status === "queued";
    const chapterMapApproved = Boolean(pipeline.chapterMapApproved);
    const progress = pipeline.progress || {completed: 0, total: 0, percent: 0, etaSeconds: null};
    const summariesDone = Boolean(progress.total) && progress.completed >= progress.total;
    const activeChapter = pipeline.chapters?.find((chapter) => chapter.status === "running");
    const summaryQueued = queued && ["summarize", "restart"].includes(pipeline.queuedAction);
    const currentActivity = resolvedActivity(pipeline);
    const progressMarkup = taskProgress({label: "Overall reading progress", unit: "chapters", progress, activity: currentActivity, status: pipeline.status});
    const pipelineProgress = pipelineProgressWithReviewer(pipeline);
    const dossierProgress = pipeline.dossierProgress || {completed: 0, total: pipeline.chunks?.length || 0, percent: 0, etaSeconds: null};
    const dossierRunning = running && pipeline.phase === "dossiers";
    const activeChunk = pipeline.chunks?.find((chunk) => chunk.dossierStatus === "running");
    const dossierQueued = queued && pipeline.queuedAction === "dossiers";
    const dossiersDone = Boolean(dossierProgress.total) && dossierProgress.completed >= dossierProgress.total;
    const dossierReset = pipeline.chunks?.length ? resetCategoryControl("dossier-restart", "dossier") : "";
    const mapReviewControl = !chapterMapApproved && pipeline.chapters?.length ? reviewChapterMapControl(pipeline.chapterMapSuspicious ? "Review" : "Review map") : "";
    const dossierActions = taskHeadingActions({extra: `${timingChartControl("dossiers")}${dossierReset}${mapReviewControl}`});
    const activeChunkLabel = activeChunk ? `${activeChunk.chapterLabel || "the next chapter"}, chunk ${activeChunk.chunkInChapter || 1}` : "the next chunk";
    const dossierProgressMarkup = taskProgress({label: "Overall dossier progress", unit: "chunks", progress: dossierProgress, activity: currentActivity, status: pipeline.status});
    const signalView = activeTab === "emotions" ? {
      kind: "emotion", stageId: "emotions", progressKey: "emotionProgress", phase: "emotions", queued: ["emotions", "emotion-restart"],
      title: "Chapter emotions", noun: "emotion scores", icon: "emotions", action: "emotions", restart: "emotion-restart",
      explanationTitle: "Emotion is a texture, not a verdict.", explanation: "The Hartmann classifier scores recognizable textual emotion across overlapping paragraph groups. It does not decide whose emotion it is or what a reader ought to feel.",
    } : activeTab === "tags" ? {
      kind: "tag", stageId: "tags", progressKey: "tagProgress", phase: "tags", queued: ["tags", "tag-restart"],
      title: "Chapter tags", noun: "tag sets", icon: "tags", action: "tags", restart: "tag-restart",
      explanationTitle: "Tags are claims with receipts.", explanation: "Bookinator scores a fixed editorial vocabulary for prose mode, chapter function, reader dynamics, time, viewpoint, mood, genre affinity, and theme. Material scores require manuscript evidence.",
    } : activeTab === "smells" ? {
      kind: "smell", stageId: "smells", progressKey: "smellProgress", phase: "smells", queued: ["smells", "smell-restart"],
      title: "Smells", noun: "editorial smell reviews", icon: "smells", action: "smells", restart: "smell-restart",
      explanationTitle: "Evidence first; editorial judgment second.", explanation: "Bookinator, its spaCy syntax rules, Proselint, and Harper’s Oxford-comma check identify candidates locally. The assigned editor model then keeps, dismisses, or marks each one informational without hiding the original evidence.",
    } : null;
    const rebuildControl = pipeline.chapters?.length && !running && !queued
      ? pipelineControl({action: "prepare", label: "Rebuild", title: "Re-extract this manuscript and rebuild its canonical Markdown and source chunks"})
      : "";
    const reconnectControl = pipeline.status === "blocked" && !pipeline.chapters?.length
      ? '<button class="primary-button" data-reconnect-pdf type="button">Reconnect source</button>'
      : "";
    const chapterMapWarning = pipeline.chapterMapSuspicious
      ? `<p class="pipeline-error"><strong>Chapter map needs review.</strong> ${escapeHtml((pipeline.chapterMapWarnings || ["The detected chapter labels do not follow one consistent pattern."]).join(" "))} Compare the headings and choose whether an outlier is legitimate before rebuilding.</p>`
      : "";
    const failedCount = failedAnalysisCount(pipeline);
    const retryFailedControl = failedCount
      ? pipelineControl({action: "retry-failed", label: `Retry ${failedCount} failed`, title: `Retry ${failedCount} failed analysis result${failedCount === 1 ? "" : "s"}`})
      : "";
    const startOverControl = pipelineControl({action: "start-over", label: "Start over", title: "Clear this book’s derived analysis and restart from source ingestion", danger: true});
    const pipelineWorkspaceActions = taskHeadingActions({extra: `${timingChartControl("pipeline")}${retryFailedControl}${reconnectControl}${mapReviewControl}${rebuildControl}${startOverControl}`});
    if (activeTab === "identity") {
      restoreBookFormToDialog();
      body.innerHTML = workspaceTaskView({icon: "identity", title: "Book identity", subtitle: "Change how this manuscript is named, prioritized, and represented throughout Bookinator.", collapse: false, explanationTitle: "Identity travels with the book.", explanation: "These details appear in the library, workspace, exports, and reviewer handoffs. Editing them does not alter the manuscript or its analysis.", content: '<section class="workspace-identity-editor"><div data-book-identity-form-host></div></section>'});
      openExistingBook(book.id, {host: body.querySelector("[data-book-identity-form-host]")});
    } else if (activeTab === "pipeline") {
      const pipelineProgressMarkup = taskProgress({label: "Overall pipeline progress", unit: "analysis steps", progress: pipelineProgress, activity: currentActivity, status: pipeline.status});
      const pipelineError = ["warning", "failed", "blocked"].includes(pipeline.status) && pipeline.error ? escapeHtml(pipeline.error) : "";
      const chapterStageIds = new Set(["summaries", "dossiers", "emotions", "tags", "smells", "cumulative-context", "llm-review"]);
      const bookStages = visiblePipelineStages(pipeline);
      const fixedStages = bookStages.filter((stage) => !chapterStageIds.has(stage.id));
      const preparationIds = new Set(["source", "extraction", "structure", "chapter-archive", "chunking"]);
      const preparation = fixedStages.filter((stage) => preparationIds.has(stage.id));
      const finishing = fixedStages.filter((stage) => !preparationIds.has(stage.id));
      const chapterLedger = chapterPipelineLedger(pipeline, book, openRows);
      body.innerHTML = workspaceTaskView({icon: "pipeline", title: "Reading pipeline", subtitle: pipeline.message || "Ready.", actions: pipelineWorkspaceActions, explanationTitle: "The pipeline is the work ledger.", explanation: "It shows every elementary job in the order Bookinator attempts it. Stage totals summarize the ledger; they are not queue items.", error: pipelineError, progress: pipelineProgressMarkup, content: `${provisionalAnalysisNotice(pipeline)}${chapterMapWarning}<section class="pipeline-ledger-section"><header><span>Preparation</span><h3>Manuscript intake</h3></header><div class="pipeline-stages">${preparation.map((stage) => stageMarkup(stage, pipeline, book, openRows)).join("")}</div></section>${chapterLedger}${finishing.length ? `<section class="pipeline-ledger-section"><header><span>After analysis</span><h3>Book-level completion</h3></header><div class="pipeline-stages">${finishing.map((stage) => stageMarkup(stage, pipeline, book, openRows)).join("")}</div></section>` : ""}`});
    } else if (activeTab === "chapters") {
      const mapReady = chapterMapReadyForReview(pipeline);
      const chapterAction = !mapReady
        ? ""
        : pipeline.chapterMapSuspicious
          ? pipelineControl({action: "prepare", label: "Rebuild", title: "Rebuild the chapter map with the accepted heading rules"})
          : chapterMapApproved
            ? pipelineControl({action: "prepare", label: "Rebuild", title: "Re-extract the manuscript and propose a fresh chapter map"})
            : approveChapterMapControl();
      const chapterSubtitle = !mapReady
        ? "Bookinator is still constructing the chapter map."
        : pipeline.chapterMapSuspicious
          ? "The detected heading family needs an editorial decision."
          : chapterMapApproved
            ? `${pipeline.chapters?.length || 0} sections approved as the structural source of truth.`
            : `${pipeline.chapters?.length || 0} detected sections are waiting for approval.`;
      const chapterActivity = !mapReady
        ? '<p class="pipeline-notice"><strong>Chapter detection is still running.</strong> Approval will appear when the proposed boundaries are stable.</p>'
        : "";
      body.innerHTML = workspaceTaskView({
        icon: "chapters",
        title: "Chapter map",
        subtitle: chapterSubtitle,
        actions: taskHeadingActions({action: chapterAction, extra: timingChartControl("chapters")}),
        explanationTitle: "Structure is a contract.",
        explanation: chapterMapApproved
          ? "This approved map is the structural source of truth. Changing a boundary later marks every dependent artifact stale and queues fresh work."
          : "Bookinator can analyze a stable proposed map immediately. Approval makes it the structural source of truth; changing a boundary later marks every dependent artifact stale and queues fresh work.",
        error: pipeline.chapterMapSuspicious ? escapeHtml((pipeline.chapterMapWarnings || []).join(" ")) : "",
        content: `${chapterActivity}<div class="chapter-map-list">${wholeBookAnalysisRow(pipeline, "chapters", book)}${mapReady && pipeline.chapters?.length ? pipeline.chapters.map((chapter) => chapterMapRow(chapter, pipeline, book)).join("") : mapReady ? '<div class="pipeline-empty"><strong>No chapter map yet.</strong><p>Prepare the manuscript to extract pages and propose its structure.</p></div>' : ""}</div>`,
      });
    } else if (signalView) {
      const signalStage = (pipeline.stages || []).find((stage) => stage.id === signalView.stageId) || {};
      const signalProgress = pipeline[signalView.progressKey] || {completed: 0, total: pipeline.chapters?.length || 0, percent: 0, etaSeconds: null};
      const signalDone = Boolean(signalProgress.total) && signalProgress.completed >= signalProgress.total;
      const signalDisabled = Boolean(signalStage.disabled);
      const signalRunning = running && pipeline.phase === signalView.phase;
      const signalQueued = queued && signalView.queued.includes(pipeline.queuedAction);
      const activeSignalChapter = pipeline.chapters?.find((chapter) => chapter[`${signalView.kind}Status`] === "running");
      const signalReset = pipeline.chapters?.length ? resetCategoryControl(signalView.restart, signalView.noun) : "";
      const modelAction = taskHeadingActions({extra: `${timingChartControl(signalView.stageId)}${signalReset}${mapReviewControl}`});
      const signalProgressMarkup = taskProgress({label: `Overall ${signalView.noun} progress`, unit: "chapters", progress: signalProgress, activity: currentActivity, status: signalStage.status || pipeline.status});
      const signalChapters = (pipeline.chapters || []).filter((chapter) => displayHeading(chapter.title).toLowerCase() !== "front matter");
      const wholeBookRollup = ["emotion", "tag", "smell"].includes(signalView.kind) ? wholeBookSignalRollupMarkup(pipeline, signalView.kind, openRows) : "";
      const signalControls = signalView.kind === "smell" ? smellSortControlMarkup() : "";
      const signalContent = `${signalControls}${wholeBookRollup}<div class="analysis-list">${signalChapters.length ? signalChapters.map((chapter) => chapterSignalMarkup(chapter, signalView.kind, openRows, book)).join("") : '<div class="pipeline-empty"><strong>First, map the manuscript.</strong><p>Bookinator needs durable chapter objects before this pass can begin.</p></div>'}</div>`;
      const blocked = signalDisabled
        ? `<strong>${escapeHtml(signalView.title)} is paused.</strong> ${escapeHtml(signalStage.detail || "This pass is excluded from the automatic queue; saved results remain inspectable.")}`
        : signalStage.status === "blocked" ? `<strong>${escapeHtml(signalView.title)} need setup.</strong> ${escapeHtml(signalStage.detail || "The assigned local model is not available.")}` : "";
      body.innerHTML = workspaceTaskView({icon: signalView.icon, title: signalView.title, subtitle: signalDone ? `${signalProgress.total} chapter ${signalView.noun} complete.` : `${signalProgress.completed} of ${signalProgress.total} chapter ${signalView.noun} complete.`, actions: modelAction, explanationTitle: signalView.explanationTitle, explanation: signalView.explanation, error: blocked || (signalRunning && pipeline.error ? escapeHtml(pipeline.error) : ""), progress: signalDone ? "" : signalProgressMarkup, content: `${provisionalAnalysisNotice(pipeline)}${signalContent}`});
    } else if (activeTab === "dossiers") {
      const chunks = pipeline.chunks || [];
      const dossierComplete = dossierProgress.completed || 0;
      const dossierSubtitle = dossierProgress.total ? `${dossierProgress.total} manuscript source chunks saved locally · ${dossierComplete} structured dossiers complete.` : "Prepare the manuscript to create page-linked source chunks.";
      const dossierContent = `<div class="analysis-list">${wholeBookAnalysisRow(pipeline, "dossiers", book)}${chunks.length ? chunks.map((chunk) => chunkMarkup(chunk, openRows, book)).join("") : '<div class="pipeline-empty"><strong>No chunks yet.</strong><p>Prepare the manuscript first. Bookinator will preserve chapter boundaries while creating smaller evidence-linked reading units.</p></div>'}</div>`;
      body.innerHTML = workspaceTaskView({icon: "dossiers", title: "Chunk dossiers", subtitle: dossierSubtitle, actions: dossierActions, explanationTitle: "Dossiers are memory.", explanation: "Each source chunk keeps its manuscript pages, facts, events, entities, questions, promises, timeline observations, and exact supporting passages.", error: pipeline.phase === "dossiers" && pipeline.error ? escapeHtml(pipeline.error) : "", progress: dossiersDone ? "" : dossierProgressMarkup, content: `${provisionalAnalysisNotice(pipeline)}${dossierContent}`});
    } else if (activeTab === "context") {
      const contextProgress = pipeline.contextProgress || {completed: 0, total: pipeline.chapters?.length || 0, percent: 0};
      const contextDone = Boolean(contextProgress.total) && contextProgress.completed >= contextProgress.total;
      const contextStage = (pipeline.stages || []).find((stage) => stage.id === "cumulative-context") || {};
      const contextRetry = ["warning", "failed"].includes(contextStage.status) ? pipelineControl({action: "cumulative-context", label: "Retry", title: "Retry cumulative context from the first incomplete checkpoint"}) : "";
      body.innerHTML = workspaceTaskView({icon: "context", title: "Cumulative context", subtitle: contextDone ? `${contextProgress.total} evidence-linked chapter checkpoints cached.` : `${contextProgress.completed} of ${contextProgress.total} chapter checkpoints cached.`, actions: taskHeadingActions({action: contextRetry, extra: timingChartControl("cumulative-context")}), explanationTitle: "The model should remember without rereading everything.", explanation: "Each checkpoint carries forward established state, uncertainty, character knowledge, relationships, chronology, open threads, themes, and voice. Every fifth chapter is rebuilt from the prior checkpoint plus the original five chapter digests to limit drift.", error: contextStage.error ? escapeHtml(contextStage.error) : "", progress: contextDone ? "" : taskProgress({label: "Cumulative context progress", unit: "chapters", progress: contextProgress, activity: currentActivity, status: contextStage.status || pipeline.status}), content: `<div class="analysis-list">${optionalChapterRows(pipeline, "context", openRows, book)}</div>`});
    } else if (activeTab === "llm-review") {
      let annotations = state.reviewerAnnotations.get(book.id) || [];
      let annotationError = "";
      try {
        annotations = await fetchReviewerAnnotations(book.id);
      } catch (error) {
        annotationError = error.message || "Bookinator could not load the manuscript-note links.";
      }
      const reviewProgress = pipeline.llmReviewProgress || {completed: 0, total: pipeline.chapters?.length || 0, percent: 0};
      const reviewChaptersDone = Boolean(reviewProgress.total) && reviewProgress.completed >= reviewProgress.total;
      const reviewDone = reviewChaptersDone && pipeline.wholeBookLlmReview?.status === "complete";
      const reviewStage = (pipeline.stages || []).find((stage) => stage.id === "llm-review") || {};
      const wholeReviewStage = (pipeline.stages || []).find((stage) => stage.id === "whole-book-llm-review") || {};
      const reviewRetry = ["warning", "failed"].includes(reviewStage.status) ? pipelineControl({action: "llm-review", label: "Retry", title: "Retry LLM Review from the first incomplete chapter"}) : "";
      const subtitle = reviewDone
        ? `${reviewProgress.total} chapters reviewed and synthesized; every judgment remains a machine proposal.`
        : reviewChaptersDone
          ? `${reviewProgress.total} chapters reviewed · whole-book synthesis ${pipeline.wholeBookLlmReview?.status === "running" ? "running" : "waiting"}.`
          : `${reviewProgress.completed} of ${reviewProgress.total} chapters reviewed.`;
      body.innerHTML = workspaceTaskView({icon: "llm-review", title: "LLM Review", subtitle, actions: taskHeadingActions({action: reviewRetry, extra: timingChartControl("llm-review")}), explanationTitle: "A first reader, never the final editor.", explanation: "The primary reader evaluates each chapter, then a separate whole-book pass reconciles those judgments into manuscript-scale strengths, risks, readers, and editorial priorities.", error: escapeHtml(annotationError || reviewStage.error || wholeReviewStage.error || ""), progress: reviewDone || reviewChaptersDone ? "" : taskProgress({label: "LLM Review progress", unit: "chapters", progress: reviewProgress, activity: currentActivity, status: reviewStage.status || pipeline.status}), content: `<div class="analysis-list">${wholeBookAnalysisRow(pipeline, "llm-review", book)}${optionalChapterRows(pipeline, "review", openRows, book, annotations)}</div>`});
    } else if (activeTab === "llm-review-report") {
      let annotations = state.reviewerAnnotations.get(book.id) || [];
      let annotationError = "";
      try {
        annotations = await fetchReviewerAnnotations(book.id);
      } catch (error) {
        annotationError = error.message || "Bookinator could not load the linked reviewer annotations.";
      }
      body.innerHTML = `${annotationError ? `<p class="pipeline-error">${escapeHtml(annotationError)}</p>` : ""}${llmReviewReportMarkup(pipeline, annotations)}`;
    } else if (activeTab === "report") {
      let annotations = state.reviewerAnnotations.get(book.id) || [];
      try {
        annotations = await fetchReviewerAnnotations(book.id);
      } catch {
        // Sharing remains available even when the optional human-comment ledger cannot be loaded.
      }
      body.innerHTML = reportExportMarkup(pipeline, book, annotations);
    } else if (activeTab === "overview") {
      body.innerHTML = workspaceTaskView({icon: "overview", title: "Book summary", subtitle: "The editor’s first orientation to the manuscript, followed by every chapter digest.", actions: reportExportControl("overview"), explanationTitle: "Start with the shape of the story.", explanation: "The whole-book synthesis leads. Chapter summaries remain directly below it so an editor can move from the broad account to the local sequence without changing tools.", collapse: false, content: bookSummaryReportMarkup(pipeline)});
    } else if (activeTab === "chapter-length") {
      body.innerHTML = chapterLengthReportMarkup(pipeline);
    } else if (activeTab === "smell-report") {
      body.innerHTML = smellsReportMarkup(pipeline);
    } else if (activeTab === "emotion-map") {
      body.innerHTML = emotionMapReportMarkup(pipeline);
    } else if (activeTab === "tag-report") {
      body.innerHTML = tagsReportMarkup(pipeline);
    } else if (activeTab === "reviewer-report") {
      let annotations = state.reviewerAnnotations.get(book.id) || [];
      let annotationError = "";
      try {
        annotations = await fetchReviewerAnnotations(book.id);
      } catch (error) {
        annotationError = error.message || "Bookinator could not load the reviewer comments.";
      }
      body.innerHTML = `${annotationError ? `<p class="pipeline-error">${escapeHtml(annotationError)}</p>` : ""}${reviewerReportMarkup(annotations, book, pipeline.reviewerSignoff || {})}`;
    } else if (activeTab === "connections") {
      body.innerHTML = dossierBookIndexMarkup(pipeline, book, bookPage.dataset.connectionIndexKind || "entities", bookPage.dataset.connectionShowAbsences === "true", openRows);
    } else if (activeTab === "questions") {
      const tracker = pipeline.questionTracker || {};
      const trackerItems = Array.isArray(tracker.items) ? tracker.items : [];
      const resolvedCount = trackerItems.filter((item) => item.status === "resolved").length;
      const possibleCount = trackerItems.filter((item) => item.status === "possible").length;
      const openCount = trackerItems.filter((item) => item.status === "open").length;
      const trackerRunning = tracker.status === "running" && pipeline.status === "running" && pipeline.phase === "questions";
      const trackerQueued = !trackerRunning && pipeline.queuedAction === "questions";
      const trackerReady = dossiersDone && summariesDone;
      const trackerAction = trackerRunning || trackerQueued ? "" : pipelineControl({action: "questions", label: trackerItems.length ? "Rebuild" : "Build", title: trackerItems.length ? "Reconcile every current question and payoff again" : "Group question retellings and match them to later payoffs", disabled: !trackerReady});
      const subtitle = trackerItems.length
        ? `${trackerItems.length} narrative questions · ${resolvedCount} resolved · ${possibleCount} possible · ${openCount} open.`
        : trackerReady
          ? "Chapter summaries and dossiers are ready for reconciliation."
          : `${dossierProgress.completed || 0} of ${dossierProgress.total || 0} dossiers complete; the tracker waits for the full book.`;
      body.innerHTML = workspaceTaskView({icon: "questions", title: "Questions & payoffs", subtitle, actions: `${trackerAction}${reportExportControl("questions")}`, explanationTitle: "Narrative promises should have visible outcomes.", explanation: "Bookinator groups repeated versions of a question, links each one to where it was raised, and looks for later answers or unresolved obligations.", error: tracker.status === "failed" ? escapeHtml(tracker.error || "Question reconciliation failed.") : "", content: questionTrackerTable(pipeline, book, openRows)});
    } else if (activeTab === "reviewer") {
      let annotations = state.reviewerAnnotations.get(book.id) || [];
      let annotationError = "";
      try {
        annotations = await fetchReviewerAnnotations(book.id);
      } catch (error) {
        annotationError = error.message || "Bookinator could not load the annotations.";
      }
      const visible = annotations.filter((item) => item.status !== "archived");
      body.innerHTML = workspaceTaskView({icon: "reviewer", title: "Reviewer", subtitle: pipeline.reviewerSignoff?.status === "complete" ? `Signed off by ${pipeline.reviewerSignoff.reviewerName}.` : visible.length ? `${visible.length} active human ${visible.length === 1 ? "annotation" : "annotations"}.` : "Read the manuscript and leave durable human judgments.", actions: "", explanationTitle: "Advice arrives here. Decisions leave from here.", explanation: "Select manuscript text, attach an editorial comment, and build the chapter/page/snippet/comment handoff. Human notes remain separate from model output.", collapse: false, error: escapeHtml(annotationError), content: reviewerWorkspaceMarkup(pipeline, annotations, book, pipeline.reviewerSignoff || {})});
    } else if (activeTab === "inferences") {
      const algorithms = pipeline.inferences || [];
      const finished = algorithms.filter((algorithm) => algorithm.status === "complete").length;
      body.innerHTML = workspaceTaskView({icon: "inferences", title: "Inferences", subtitle: `${finished} of ${algorithms.length} book-level algorithms complete.`, actions: taskHeadingActions({extra: timingChartControl("inferences")}), explanationTitle: "These are jobs, not reports.", explanation: "Each step combines evidence across the manuscript. The pipeline runs eligible algorithms automatically; inspect their editorial results in Explore.", collapse: false, content: inferenceLedgerMarkup(pipeline)});
    } else if (activeTab === "summaries") {
      const complete = progress.completed;
      const wholeSummaryDone = pipeline.wholeBookSummary?.status === "complete" && Boolean(pipeline.wholeBookSummary?.summary);
      const wholeSummaryQueued = pipeline.wholeBookSummary?.status === "running" || pipeline.queuedAction === "whole-summary";
      const summaryAction = summariesDone && !wholeSummaryDone && !wholeSummaryQueued
        ? pipelineControl({action: "whole-summary", label: "Finish", title: "Build the whole-book summary now without waiting for independent analysis passes"})
        : "";
      const summaryReset = pipeline.chapters?.length ? resetCategoryControl("restart", "chapter summary") : "";
      const summaryHeadingActions = taskHeadingActions({action: summaryAction, extra: `${timingChartControl("summaries")}${summaryReset}${mapReviewControl}`});
      const summaryTitle = "Chapter summaries";
      const summarySubtitle = summariesDone
          ? `${progress.total} manuscript chapter summaries complete.`
          : pipeline.chapters?.length
            ? `${complete} of ${progress.total} manuscript summaries complete.`
            : pipeline.message || "No chapters have been detected yet.";
      const summaryContent = `<div class="analysis-list">${wholeBookAnalysisRow(pipeline, "summaries", book)}${pipeline.chapters?.length ? pipeline.chapters.map((chapter) => chapterMarkup(chapter, openRows, book)).join("") : '<div class="pipeline-empty"><strong>First, map the manuscript.</strong><p>Bookinator will extract the pages and propose chapter boundaries before any model begins summarizing.</p></div>'}</div>`;
      body.innerHTML = workspaceTaskView({icon: "summaries", title: summaryTitle, subtitle: summarySubtitle, actions: summaryHeadingActions, explanationTitle: "Summaries are navigation.", explanation: "Each chapter digest gives you a quick map of what happened, what the chapter establishes, and which questions remain open.", error: !summariesDone && pipeline.error ? `<strong>The local reader stopped.</strong> ${escapeHtml(pipeline.error)}` : "", progress: summariesDone ? "" : progressMarkup, content: `${provisionalAnalysisNotice(pipeline)}${chapterMapWarning}${summaryContent}`});
    } else {
      body.innerHTML = plannedWorkspaceView(plannedWorkspaceViews[activeTab]);
    }
    state.pipelineSignature = signature;
    if (sameWorkspace) requestAnimationFrame(() => window.scrollTo({top: priorScrollY, behavior: "auto"}));
    body.querySelectorAll("[data-show-timing-chart]").forEach((button) => button.addEventListener("click", () => openTimingChart(pipeline, button.dataset.showTimingChart)));
    if (body.querySelector("[data-export-history]")) refreshExportHistory(book, body);
    body.querySelector("[data-download-portable-report]")?.addEventListener("click", async (event) => {
      const button = event.currentTarget;
      const annotations = await reviewerAnnotationsForExport(book.id);
      const sections = await exportPreview({format: "html", pipeline, annotations});
      if (!sections) return;
      const original = button.textContent;
      button.disabled = true;
      button.textContent = "Building site…";
      try {
        const htmlSections = sections.map((id) => shareSectionDefinitions.find((item) => item.id === id)?.htmlId || id);
        const manifest = buildPortableReportManifest(pipeline, await bookWithEmbeddedIcon(book), {sections: htmlSections, annotations});
        const html = buildPortableReportHtml(manifest);
        auditPortableReport({manifest, artifact: html, pipeline});
        const filename = reportExportFilename(book, "html");
        await saveExportArtifact(book, html, {filename, mediaType: "text/html;charset=utf-8", sections}, body);
        downloadFile(html, filename, "text/html;charset=utf-8");
      } catch (error) {
        await confirmAction({context: "Export blocked", title: "Bookinator did not save this report", message: error.message || "The report did not pass its local export checks.", acceptLabel: "Close"});
      } finally {
        button.disabled = false;
        button.textContent = original;
      }
    });
    body.querySelector("[data-download-editor-report]")?.addEventListener("click", async (event) => {
      const button = event.currentTarget;
      const annotations = await reviewerAnnotationsForExport(book.id);
      const sections = await exportPreview({format: "pdf", pipeline, annotations});
      if (!sections) return;
      const original = button.textContent;
      button.disabled = true;
      button.textContent = "Building PDF…";
      try {
        const htmlSections = sections.map((id) => shareSectionDefinitions.find((item) => item.id === id)?.htmlId || id);
        const manifest = buildPortableReportManifest(pipeline, await bookWithEmbeddedIcon(book), {sections: htmlSections, annotations});
        auditPortableReport({manifest, pipeline});
        const pdf = await editorReportPdf(pipeline, book, {sections, annotations});
        const filename = reportExportFilename(book, "pdf");
        await saveExportArtifact(book, pdf, {filename, mediaType: "application/pdf", sections}, body);
        downloadFile(pdf, filename, "application/pdf");
      } catch (error) {
        await confirmAction({context: "PDF export failed", title: "Bookinator could not build the report", message: error.message || "The browser could not render this report.", acceptLabel: "Close"});
      } finally {
        button.disabled = false;
        button.textContent = original;
      }
    });
    body.querySelectorAll("[data-report-export]").forEach((button) => button.addEventListener("click", async (event) => {
      const control = event.currentTarget;
      const report = control.dataset.reportExport;
      const reportNames = {overview: "book-summary", "chapter-length": "chapter-length", "reviewer-report": "reviewer-comments", "tag-report": "tag-frequencies", "llm-review-report": "llm-review", "smell-report": "smells", "emotion-map": "emotion-map", connections: "connections", questions: "questions-and-payoffs"};
      const original = control.textContent;
      control.disabled = true;
      control.textContent = "Building…";
      try {
        const annotations = await reviewerAnnotationsForExport(book.id);
        const pdf = await editorReportPdf(pipeline, book, {only: report, annotations});
        downloadFile(pdf, reportExportFilename(book, "pdf", {section: reportNames[report] || report}), "application/pdf");
        control.closest("details")?.removeAttribute("open");
      } catch (error) {
        await confirmAction({context: "PDF export failed", title: "Bookinator could not build this report", message: error.message || "The browser could not render this report.", acceptLabel: "Close"});
      } finally {
        control.disabled = false;
        control.textContent = original;
      }
    }));
    body.querySelector("[data-reconnect-pdf]")?.addEventListener("click", () => navigateWorkspaceTab(book.id, "identity"));
    body.querySelectorAll("[data-open-chapter-map]").forEach((button) => button.addEventListener("click", () => {
      navigateWorkspaceTab(book.id, "chapters");
    }));
    body.querySelector("[data-approve-chapter-map]")?.addEventListener("click", async (event) => {
      const button = event.currentTarget;
      button.disabled = true;
      button.setAttribute("aria-busy", "true");
      try {
        await requireChapterMapApi();
        const response = await fetch(`/api/books/${encodeURIComponent(book.id)}/chapter-map/approve`, {method: "POST", headers: {"Content-Type": "application/json"}, body: "{}"});
        const contentType = response.headers.get("content-type") || "";
        if (!contentType.includes("application/json")) throw new Error("Bookinator’s local server needs a restart before it can approve chapter maps.");
        const result = await response.json();
        if (!response.ok) throw new Error(result.error || "Could not approve this chapter map.");
        if (Number(result.chapterMapProtocol || 0) < 1) throw new Error("Bookinator’s local server needs a restart before it can approve chapter maps.");
        state.pipelineSignature = "";
        state.workspacePipeline = {bookId: book.id, pipeline: result.pipeline};
        const currentBookPage = document.querySelector("#book-page");
        const stillInsideBook = !currentBookPage.hidden && currentBookPage.dataset.bookId === book.id;
        if (stillInsideBook) await showBookPage(book.id, currentBookPage.dataset.activeTab || "chapters", "", result.pipeline);
        else await refreshLibraryBooks({poll: true});
      } catch (error) {
        button.disabled = false;
        button.removeAttribute("aria-busy");
        body.insertAdjacentHTML("afterbegin", `<p class="pipeline-error">${escapeHtml(error.message)}</p>`);
      }
    });
    body.querySelector(".candidate-family")?.addEventListener("submit", async (event) => {
      event.preventDefault();
      const form = event.currentTarget;
      const button = form.querySelector("[data-apply-chapter-variants]");
      const labels = [...form.querySelectorAll("[data-chapter-variant]:checked")].map((input) => input.value);
      button.disabled = true;
      button.setAttribute("aria-busy", "true");
      button.textContent = "Rebuilding…";
      try {
        await requireChapterMapApi();
        const response = await fetch(`/api/books/${encodeURIComponent(book.id)}/chapter-map/variants`, {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({labels})});
        const result = await response.json();
        if (!response.ok) throw new Error(result.error || "Could not update the chapter-heading rules.");
        state.pipelineSignature = "";
        showBookPage(book.id, "chapters");
      } catch (error) {
        button.disabled = false;
        button.removeAttribute("aria-busy");
        button.textContent = "Apply variants & rebuild";
        form.insertAdjacentHTML("beforeend", `<p class="pipeline-error">${escapeHtml(error.message)}</p>`);
      }
    });
    body.querySelectorAll("[data-demote-chapter]").forEach((button) => button.addEventListener("click", async (event) => {
      event.preventDefault();
      event.stopPropagation();
      const title = button.dataset.chapterTitle || "This heading";
      const page = Number(button.dataset.chapterPage);
      const confirmed = await confirmAction({
        context: "Change chapter boundary",
        title: `${title} is not a chapter?`,
        message: `This does not delete any manuscript text. Bookinator will remove the chapter boundary at page ${page.toLocaleString()} and fold this section into the preceding chapter. Existing summaries, dossiers, and later analysis that depend on this map will become stale and regenerate. If this is wrong, restore the boundary from the Excluded boundaries panel.`,
        acceptLabel: "Fold into previous",
      });
      if (!confirmed) return;
      button.disabled = true;
      button.setAttribute("aria-busy", "true");
      try {
        await changeChapterBoundary(book.id, "demote", page);
        showBookPage(book.id, "chapters");
      } catch (error) {
        button.disabled = false;
        button.removeAttribute("aria-busy");
        body.insertAdjacentHTML("afterbegin", `<p class="pipeline-error">${escapeHtml(error.message)}</p>`);
      }
    }));
    body.querySelectorAll("[data-restore-chapter-page]").forEach((button) => button.addEventListener("click", async (event) => {
      event.preventDefault();
      const page = Number(button.dataset.restoreChapterPage);
      const title = button.dataset.restoreChapterTitle || "this excluded heading";
      const confirmed = await confirmAction({
        context: "Restore chapter boundary",
        title: `Restore ${title} as a chapter?`,
        message: `Bookinator will restore the chapter boundary at page ${page.toLocaleString()} and rebuild the proposed map. Existing dependent analysis will become stale and regenerate; no manuscript text will be changed.`,
        acceptLabel: "Restore chapter",
      });
      if (!confirmed) return;
      button.disabled = true;
      button.setAttribute("aria-busy", "true");
      try {
        await changeChapterBoundary(book.id, "restore", page);
        showBookPage(book.id, "chapters");
      } catch (error) {
        button.disabled = false;
        button.removeAttribute("aria-busy");
        body.insertAdjacentHTML("afterbegin", `<p class="pipeline-error">${escapeHtml(error.message)}</p>`);
      }
    }));
    body.querySelectorAll("[data-view-chapter-source]").forEach((button) => button.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      const analysisChapter = (pipeline.chapters || []).find((item) => Number(item.sequence || item.number) === Number(button.dataset.viewChapterSource));
      openChapterSource(book.id, button.dataset.viewChapterSource, null, analysisChapter);
    }));
    body.querySelectorAll("[data-open-reviewer]").forEach((button) => button.addEventListener("click", () => navigateWorkspaceTab(book.id, "reviewer")));
    body.querySelectorAll("[data-review-proposal-action]").forEach((button) => button.addEventListener("click", async () => {
      const action = button.dataset.reviewProposalAction;
      const proposal = button.closest(".llm-review-proposal");
      const message = proposal?.querySelector("[data-proposal-message]");
      button.disabled = true;
      if (message) message.textContent = "Saving decision…";
      try {
        const response = await fetch(`/api/books/${encodeURIComponent(book.id)}/llm-review/proposals/${encodeURIComponent(button.dataset.reviewProposalId)}`, {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({action})});
        const result = await response.json();
        if (!response.ok) throw new Error(result.error || "The proposal decision could not be saved.");
        invalidateReviewerAnnotations(book.id);
        await showBookPage(book.id, "llm-review-report");
      } catch (error) {
        button.disabled = false;
        if (message) message.textContent = error.message || "The proposal decision could not be saved.";
      }
    }));
    body.querySelector("[data-llm-score-sort]")?.addEventListener("change", (event) => {
      llmReviewScoreSort = event.currentTarget.value === "alphabetical" ? "alphabetical" : "score";
      const grid = body.querySelector(".llm-review-score-grid");
      const cards = [...grid.querySelectorAll(".llm-review-score")];
      cards.sort((left, right) => llmReviewScoreSort === "alphabetical"
        ? String(left.dataset.reviewLabel).localeCompare(String(right.dataset.reviewLabel))
        : Number(right.dataset.reviewScore) - Number(left.dataset.reviewScore) || Number(left.dataset.reviewOrder) - Number(right.dataset.reviewOrder));
      cards.forEach((card) => grid.append(card));
    });
    body.querySelectorAll("[data-view-review-candidate]").forEach((button) => button.addEventListener("click", () => {
      const sequence = Number(button.dataset.candidateChapter || 0);
      const chapter = (pipeline.chapters || []).find((item) => Number(item.sequence || item.number) === sequence);
      const candidate = chapter?.llmReview?.rejectedCandidates?.[Number(button.dataset.candidateIndex)];
      if (!chapter || !candidate) return;
      openChapterSource(book.id, sequence, {
        kind: "review-candidate",
        quote: candidate.quote,
        comment: candidate.comment,
        category: candidate.category,
        characterStart: candidate.characterStart,
        characterEnd: candidate.characterEnd,
      }, chapter);
    }));
    body.querySelectorAll("[data-view-review-proposal]").forEach((button) => button.addEventListener("click", () => {
      const sequence = Number(button.dataset.proposalChapter || 0);
      const chapter = (pipeline.chapters || []).find((item) => Number(item.sequence || item.number) === sequence);
      const proposal = chapter?.llmReview?.editorialProposals?.find((item) => item.id === button.dataset.proposalId);
      if (!chapter || !proposal) return;
      openChapterSource(book.id, sequence, {
        kind: "review-candidate",
        quote: proposal.quote,
        comment: proposal.comment,
        category: proposal.category,
        characterStart: proposal.characterStart,
        characterEnd: proposal.characterEnd,
      }, chapter);
    }));
    body.querySelectorAll("[data-review-lead-category]").forEach((select) => select.addEventListener("change", async () => {
      const previous = select.dataset.previousValue || "";
      const category = select.value;
      select.disabled = true;
      try {
        const proposal = select.dataset.leadKind === "proposal";
        const path = proposal
          ? `/api/books/${encodeURIComponent(book.id)}/llm-review/proposals/${encodeURIComponent(select.dataset.proposalId)}`
          : `/api/books/${encodeURIComponent(book.id)}/llm-review/candidates/${encodeURIComponent(select.dataset.candidateChapter)}/${encodeURIComponent(select.dataset.candidateIndex)}`;
        const response = await fetch(path, {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({action: "categorize", category})});
        const result = await response.json();
        if (!response.ok) throw new Error(result.error || "The editorial category could not be saved.");
        if (proposal) {
          const chapter = (pipeline.chapters || []).find((item) => (item.llmReview?.editorialProposals || []).some((lead) => lead.id === select.dataset.proposalId));
          const lead = chapter?.llmReview?.editorialProposals?.find((item) => item.id === select.dataset.proposalId);
          if (lead) Object.assign(lead, result.proposal || {category});
        } else {
          const sequence = Number(select.dataset.candidateChapter);
          const chapter = (pipeline.chapters || []).find((item) => Number(item.sequence || item.number) === sequence);
          const lead = chapter?.llmReview?.rejectedCandidates?.[Number(select.dataset.candidateIndex)];
          if (lead) Object.assign(lead, result.candidate || {category});
          if (result.proposal) {
            const promoted = chapter?.llmReview?.editorialProposals?.find((item) => item.id === result.proposal.id);
            if (promoted) Object.assign(promoted, result.proposal);
          }
        }
        state.pipelineSignature = "";
        await showBookPage(book.id, activeTab, "", pipeline);
      } catch (error) {
        select.value = previous;
        select.disabled = false;
        const article = select.closest(".llm-review-proposal, .llm-review-candidate");
        const message = article?.querySelector("[data-proposal-message], [data-candidate-message]");
        if (message) message.textContent = error.message || "The editorial category could not be saved.";
      }
    }));
    body.querySelectorAll("[data-review-lead-category]").forEach((select) => { select.dataset.previousValue = select.value; });
    body.querySelectorAll("[data-review-candidate-action]").forEach((button) => button.addEventListener("click", async () => {
      const article = button.closest(".llm-review-candidate");
      const message = article?.querySelector("[data-candidate-message]");
      const action = button.dataset.reviewCandidateAction;
      try {
        await requireChapterMapApi("llmReviewCandidatePromotion", "Bookinator’s running server predates soft-lead triage. Restart ./bin/serve, then try again.", 2);
      } catch (error) {
        if (message) message.textContent = error.message;
        return;
      }
      if (action !== "reopen") {
        const confirmed = await confirmAction(action === "promote" ? {
          context: "Soft editorial lead",
          title: "Promote this to a significant concern?",
          message: "It will move into Significant concerns as a machine proposal. It will not become a human annotation unless someone adds it to Reviewer there.",
          acceptLabel: "Promote to significant",
        } : {
          context: "Soft editorial lead",
          title: "Dismiss this soft lead?",
          message: "It will leave the active review and move into Dismissed soft leads. Its provenance will remain available, and it can be restored later.",
          acceptLabel: "Dismiss soft lead",
        });
        if (!confirmed) return;
      }
      button.disabled = true;
      if (message) message.textContent = action === "promote" ? "Promoting to significant…" : action === "dismiss" ? "Dismissing…" : "Restoring…";
      try {
        const response = await fetch(`/api/books/${encodeURIComponent(book.id)}/llm-review/candidates/${encodeURIComponent(button.dataset.candidateChapter)}/${encodeURIComponent(button.dataset.candidateIndex)}`, {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({action})});
        const result = await response.json();
        if (!response.ok) throw new Error(result.error || "The soft-lead decision could not be saved.");
        const sequence = Number(button.dataset.candidateChapter);
        const candidateIndex = Number(button.dataset.candidateIndex);
        const chapter = (pipeline.chapters || []).find((item) => Number(item.sequence || item.number) === sequence);
        const review = chapter?.llmReview;
        if (review && Array.isArray(review.rejectedCandidates) && review.rejectedCandidates[candidateIndex]) {
          Object.assign(review.rejectedCandidates[candidateIndex], result.candidate || {});
          if (action === "promote" && result.proposal) {
            const proposals = Array.isArray(review.editorialProposals) ? review.editorialProposals : (review.editorialProposals = []);
            const existing = proposals.find((proposal) => proposal.id === result.proposal.id);
            if (existing) Object.assign(existing, result.proposal);
            else proposals.push(result.proposal);
            review.editorialVerdict = "material_concerns_found";
            review.editorialSummary = "A soft lead was promoted for significant editorial consideration.";
          }
        }
        state.pipelineSignature = "";
        await showBookPage(book.id, activeTab, "", pipeline);
      } catch (error) {
        button.disabled = false;
        if (message) message.textContent = error.message || "The soft-lead decision could not be saved.";
      }
    }));
    body.querySelectorAll("[data-chapter-length-target]").forEach((button) => button.addEventListener("click", async () => {
      await navigateWorkspaceTab(book.id, "chapters");
      const target = document.querySelector(`#book-workspace-body [data-chapter-map-sequence="${CSS.escape(button.dataset.chapterLengthTarget)}"]`);
      if (!target) return;
      target.scrollIntoView({behavior: "smooth", block: "center"});
      target.focus({preventScroll: true});
    }));
    body.querySelectorAll("[data-review-chapter]").forEach((button) => button.addEventListener("click", () => {
      const sequence = Number(button.dataset.reviewChapter);
      const analysisChapter = (pipeline.chapters || []).find((item) => Number(item.sequence || item.number) === sequence);
      openChapterSource(book.id, sequence, {kind: "reviewer"}, analysisChapter);
    }));
    const currentAnnotations = () => state.reviewerAnnotations.get(book.id) || [];
    body.querySelectorAll("[data-open-annotation]").forEach((button) => button.addEventListener("click", () => {
      const annotation = currentAnnotations().find((item) => item.id === button.dataset.openAnnotation);
      if (!annotation) return;
      const analysisChapter = (pipeline.chapters || []).find((item) => Number(item.sequence || item.number) === Number(annotation.chapterSequence));
      openChapterSource(book.id, annotation.chapterSequence, {kind: "reviewer", annotationId: annotation.id}, analysisChapter);
    }));
    const setInlineAnnotationEditing = (wrapper, editing, comment = "") => {
      const text = wrapper?.querySelector("[data-annotation-comment-text]");
      const form = wrapper?.querySelector("[data-inline-annotation-form]");
      const textarea = form?.querySelector("textarea[name=comment]");
      if (!wrapper || !text || !form || !textarea) return;
      wrapper.classList.toggle("editing", editing);
      text.hidden = editing;
      form.hidden = !editing;
      form.querySelector("[data-inline-annotation-message]").textContent = "";
      if (editing) {
        textarea.value = comment;
        textarea.focus({preventScroll: true});
        textarea.setSelectionRange(textarea.value.length, textarea.value.length);
      }
    };
    body.querySelectorAll("[data-inline-edit-annotation]").forEach((button) => button.addEventListener("click", () => {
      const annotation = currentAnnotations().find((item) => item.id === button.dataset.inlineEditAnnotation);
      const wrapper = button.closest("[data-reviewer-note], .review-comment-card")?.querySelector("[data-annotation-comment]");
      if (annotation && wrapper) setInlineAnnotationEditing(wrapper, true, annotation.comment || "");
    }));
    body.querySelectorAll("[data-cancel-inline-annotation]").forEach((button) => button.addEventListener("click", () => {
      const wrapper = button.closest("[data-annotation-comment]");
      const annotation = currentAnnotations().find((item) => item.id === wrapper?.dataset.annotationComment);
      setInlineAnnotationEditing(wrapper, false, annotation?.comment || "");
    }));
    body.querySelectorAll("[data-inline-annotation-form]").forEach((form) => {
      form.querySelector("textarea").addEventListener("keydown", (event) => {
        if (event.key === "Escape") {
          event.preventDefault();
          form.querySelector("[data-cancel-inline-annotation]").click();
        } else if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) {
          event.preventDefault();
          form.requestSubmit();
        }
      });
      form.addEventListener("submit", async (event) => {
        event.preventDefault();
        const wrapper = form.closest("[data-annotation-comment]");
        const annotationId = wrapper?.dataset.annotationComment;
        const annotation = currentAnnotations().find((item) => item.id === annotationId);
        const textarea = form.querySelector("textarea[name=comment]");
        const message = form.querySelector("[data-inline-annotation-message]");
        const submit = form.querySelector('[type="submit"]');
        const comment = textarea.value.trim();
        if (!annotation || !comment) {
          message.textContent = "Write a comment before saving.";
          textarea.focus();
          return;
        }
        if (comment === String(annotation.comment || "").trim()) {
          setInlineAnnotationEditing(wrapper, false, annotation.comment || "");
          return;
        }
        submit.disabled = true;
        submit.textContent = "Saving…";
        message.textContent = "";
        try {
          const saved = await updateReviewerAnnotation(book.id, annotationId, {comment});
          Object.assign(annotation, saved);
          body.querySelectorAll("[data-annotation-comment]").forEach((candidate) => {
            if (candidate.dataset.annotationComment !== annotationId) return;
            candidate.querySelector("[data-annotation-comment-text]").textContent = saved.comment;
            setInlineAnnotationEditing(candidate, false, saved.comment);
          });
        } catch (error) {
          message.textContent = error.message || "The comment could not be saved.";
        } finally {
          submit.disabled = false;
          submit.textContent = "Save comment";
        }
      });
    });
    body.querySelectorAll("[data-edit-annotation]").forEach((button) => button.addEventListener("click", () => {
      const annotation = currentAnnotations().find((item) => item.id === button.dataset.editAnnotation);
      const draftComment = button.closest("[data-inline-annotation-form]")?.querySelector("textarea[name=comment]")?.value;
      if (annotation) openAnnotationEditor({bookId: book.id, annotation: draftComment === undefined ? annotation : {...annotation, comment: draftComment}, afterSave: () => showBookPage(book.id, activeTab), afterDelete: () => showBookPage(book.id, activeTab)});
    }));
    body.querySelectorAll("[data-annotation-priority]").forEach((button) => button.addEventListener("click", async () => {
      const annotation = currentAnnotations().find((item) => item.id === button.dataset.annotationId);
      const priority = button.dataset.annotationPriority;
      if (!annotation || annotation.priority === priority) return;
      const control = button.closest(".annotation-priority-control");
      control?.querySelectorAll("button").forEach((item) => { item.disabled = true; });
      try {
        await updateReviewerAnnotation(book.id, annotation.id, {priority});
        invalidateReviewerAnnotations(book.id);
        await showBookPage(book.id, activeTab);
      } catch (error) {
        control?.querySelectorAll("button").forEach((item) => { item.disabled = false; });
        body.insertAdjacentHTML("afterbegin", `<p class="pipeline-error">${escapeHtml(error.message)}</p>`);
      }
    }));
    body.querySelectorAll("[data-archive-annotation]").forEach((button) => button.addEventListener("click", async () => {
      const annotation = currentAnnotations().find((item) => item.id === button.dataset.archiveAnnotation);
      if (!annotation || !await confirmAction({context: "Archive editor comment", title: "Archive this comment?", message: "It will leave the active review and exported reports, but it will remain available in Archived comments.", acceptLabel: "Archive comment"})) return;
      button.disabled = true;
      try {
        await updateReviewerAnnotation(book.id, annotation.id, {status: "archived"});
        invalidateReviewerAnnotations(book.id);
        await showBookPage(book.id, activeTab);
      } catch (error) {
        button.disabled = false;
        body.insertAdjacentHTML("afterbegin", `<p class="pipeline-error">${escapeHtml(error.message)}</p>`);
      }
    }));
    body.querySelectorAll("[data-restore-annotation]").forEach((button) => button.addEventListener("click", async () => {
      button.disabled = true;
      try {
        await updateReviewerAnnotation(book.id, button.dataset.restoreAnnotation, {status: "open"});
        invalidateReviewerAnnotations(book.id);
        await showBookPage(book.id, activeTab);
      } catch (error) {
        button.disabled = false;
        body.insertAdjacentHTML("afterbegin", `<p class="pipeline-error">${escapeHtml(error.message)}</p>`);
      }
    }));
    body.querySelectorAll("[data-delete-annotation]").forEach((button) => button.addEventListener("click", async () => {
      const annotation = currentAnnotations().find((item) => item.id === button.dataset.deleteAnnotation);
      if (!annotation || !await confirmAnnotationDeletion(annotation)) return;
      button.disabled = true;
      try {
        await deleteReviewerAnnotation(book.id, annotation.id);
        invalidateReviewerAnnotations(book.id);
        await showBookPage(book.id, activeTab);
      } catch (error) {
        button.disabled = false;
        body.insertAdjacentHTML("afterbegin", `<p class="pipeline-error">${escapeHtml(error.message)}</p>`);
      }
    }));
    body.querySelector("[data-export-annotations]")?.addEventListener("click", () => {
      const filename = `${String(book.title || "book").toLocaleLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") || "book"}-editorial-annotations.csv`;
      downloadFile(annotationCsv(currentAnnotations(), book), filename, "text/csv;charset=utf-8");
    });
    body.querySelector("[data-reviewer-signoff-form]")?.addEventListener("submit", async (event) => {
      event.preventDefault();
      const form = event.currentTarget;
      const button = form.querySelector("button[type=submit]");
      const message = form.querySelector("[data-reviewer-signoff-message]");
      button.disabled = true;
      message.textContent = "Saving your sign-off…";
      try {
        await saveReviewerSignoff(book.id, {status: "complete", reviewerName: form.elements.reviewerName.value, notes: form.elements.notes.value});
        state.pipelineSignature = "";
        await showBookPage(book.id, "reviewer");
      } catch (error) {
        message.textContent = error.message || "The reviewer sign-off could not be saved.";
        button.disabled = false;
      }
    });
    body.querySelector("[data-rescind-review]")?.addEventListener("click", async (event) => {
      const button = event.currentTarget;
      const confirmed = await confirmAction({
        context: "Human review",
        title: "Rescind this reviewer sign-off?",
        message: "The pipeline will no longer be marked complete. The reviewer name, general notes, and every annotation will remain saved.",
        acceptLabel: "Rescind sign-off",
      });
      if (!confirmed) return;
      button.disabled = true;
      try {
        await saveReviewerSignoff(book.id, {status: "open"});
        state.pipelineSignature = "";
        await showBookPage(book.id, "reviewer");
      } catch (error) {
        button.disabled = false;
        body.insertAdjacentHTML("afterbegin", `<p class="pipeline-error">${escapeHtml(error.message || "The review could not be reopened.")}</p>`);
      }
    });
    const bookIndex = body.querySelector("[data-book-index]");
    if (bookIndex) {
      const sortStateName = (kind) => `connectionSort${kind.charAt(0).toLocaleUpperCase()}${kind.slice(1)}`;
      const sortIndexPanel = (panel, key, direction) => {
        const table = panel.querySelector(".book-index-table");
        if (!table) return;
        const rows = [...table.querySelectorAll(":scope > [data-index-row]")];
        rows.sort((left, right) => {
          const leftValue = left.getAttribute(`data-sort-${key}`) || "";
          const rightValue = right.getAttribute(`data-sort-${key}`) || "";
          const numeric = leftValue !== "" && rightValue !== "" && Number.isFinite(Number(leftValue)) && Number.isFinite(Number(rightValue));
          const comparison = numeric ? Number(leftValue) - Number(rightValue) : leftValue.localeCompare(rightValue, undefined, {numeric: true, sensitivity: "base"});
          return direction === "asc" ? comparison : -comparison;
        });
        table.append(...rows);
        panel.dataset.sortKey = key;
        panel.dataset.sortDirection = direction;
        panel.querySelectorAll("[data-sort-column]").forEach((column) => {
          const active = column.dataset.sortColumn === key;
          column.setAttribute("aria-sort", active ? (direction === "asc" ? "ascending" : "descending") : "none");
          const indicator = column.querySelector("i");
          if (indicator) indicator.textContent = active ? (direction === "asc" ? "↑" : "↓") : "↕";
        });
      };
      bookIndex.querySelectorAll("[data-index-panel]").forEach((panel) => {
        const kind = panel.dataset.indexPanel;
        const saved = bookPage.dataset[sortStateName(kind)] || panel.dataset.defaultSort || "name:asc";
        const [key, direction] = saved.split(":");
        sortIndexPanel(panel, key, direction === "asc" ? "asc" : "desc");
      });
      const activateInspectorTab = (row, tab) => {
        const inspector = row?.querySelector(":scope > [data-index-inspector]");
        if (!inspector) return;
        row.open = true;
        inspector.querySelectorAll("[data-index-row-tab]").forEach((button) => button.setAttribute("aria-selected", String(button.dataset.indexRowTab === tab)));
        inspector.querySelectorAll("[data-index-row-panel]").forEach((panel) => { panel.hidden = panel.dataset.indexRowPanel !== tab; });
        if (tab === "connections") {
          const panel = inspector.querySelector('[data-index-row-panel="connections"]');
          const kind = inspector.dataset.indexKind;
          const label = inspector.dataset.indexLabel;
          panel.innerHTML = dossierIntersectionMarkup(pipeline, book, kind, label, bookPage.dataset.connectionShowNonInteractions === "true");
          bookPage.dataset.connectionInspectorKind = kind;
          bookPage.dataset.connectionInspectorLabel = label;
        } else if (bookPage.dataset.connectionInspectorKind === inspector.dataset.indexKind && bookPage.dataset.connectionInspectorLabel === inspector.dataset.indexLabel) {
          delete bookPage.dataset.connectionInspectorKind;
          delete bookPage.dataset.connectionInspectorLabel;
        }
      };
      const switchIndex = (kind) => {
        bookPage.dataset.connectionIndexKind = kind;
        bookIndex.querySelectorAll("[data-index-kind]").forEach((button) => button.setAttribute("aria-pressed", String(button.dataset.indexKind === kind)));
        bookIndex.querySelectorAll("[data-index-panel]").forEach((panel) => { panel.hidden = panel.dataset.indexPanel !== kind; });
        const absenceControl = bookIndex.querySelector(".book-index-absence");
        if (absenceControl) absenceControl.hidden = kind === "times";
        bookIndex.querySelector("[data-index-search]").dispatchEvent(new Event("input"));
      };
      bookIndex.querySelectorAll("[data-index-kind]").forEach((button) => button.addEventListener("click", () => switchIndex(button.dataset.indexKind)));
      const indexSearch = bookIndex.querySelector("[data-index-search]");
      indexSearch?.addEventListener("input", (event) => {
        const query = event.currentTarget.value.trim().toLocaleLowerCase();
        const panel = bookIndex.querySelector("[data-index-panel]:not([hidden])");
        const rows = [...panel.querySelectorAll("[data-index-row]")];
        rows.forEach((row) => { row.hidden = Boolean(query) && !row.dataset.indexSearch.includes(query); });
        panel.querySelector(".book-index-empty-filter").hidden = rows.some((row) => !row.hidden);
      });
      if (indexSearch && priorIndexQuery) {
        indexSearch.value = priorIndexQuery;
        indexSearch.dispatchEvent(new Event("input"));
      }
      bookIndex.querySelector("[data-index-absences]")?.addEventListener("change", (event) => {
        const show = event.currentTarget.checked;
        bookPage.dataset.connectionShowAbsences = String(show);
        bookIndex.classList.toggle("show-absences", show);
      });
      bookIndex.addEventListener("click", (event) => {
        const sortButton = event.target.closest("[data-index-sort]");
        if (sortButton) {
          const panel = sortButton.closest("[data-index-panel]");
          const key = sortButton.dataset.indexSort;
          const direction = panel.dataset.sortKey === key ? (panel.dataset.sortDirection === "asc" ? "desc" : "asc") : sortButton.dataset.sortFirst;
          bookPage.dataset[sortStateName(panel.dataset.indexPanel)] = `${key}:${direction}`;
          sortIndexPanel(panel, key, direction);
          return;
        }
        const inspectorTab = event.target.closest("[data-index-row-tab]");
        if (inspectorTab) {
          event.preventDefault();
          activateInspectorTab(inspectorTab.closest("[data-index-row]"), inspectorTab.dataset.indexRowTab);
          return;
        }
        const related = event.target.closest("[data-open-connection-item]");
        if (related) {
          event.preventDefault();
          const kind = related.dataset.openConnectionItem;
          const label = related.dataset.intersectionLabel;
          switchIndex(kind);
          const target = [...bookIndex.querySelectorAll(`[data-index-panel="${kind}"] [data-index-row]`)].find((row) => row.dataset.indexLabel === label);
          if (target) {
            activateInspectorTab(target, "connections");
            target.scrollIntoView({block: "nearest"});
            target.querySelector("summary")?.focus({preventScroll: true});
          }
          return;
        }
      });
      bookIndex.addEventListener("change", (event) => {
        if (!event.target.matches("[data-intersection-absences]")) return;
        const show = event.target.checked;
        bookPage.dataset.connectionShowNonInteractions = String(show);
        event.target.closest(".book-index-connections")?.classList.toggle("show-no-interactions", show);
      });
      bookIndex.querySelectorAll("[data-index-row]").forEach((row) => row.addEventListener("toggle", () => {
        if (row.open || row.dataset.indexKind !== bookPage.dataset.connectionInspectorKind || row.dataset.indexLabel !== bookPage.dataset.connectionInspectorLabel) return;
        delete bookPage.dataset.connectionInspectorKind;
        delete bookPage.dataset.connectionInspectorLabel;
      }));
      if (bookPage.dataset.connectionInspectorKind && bookPage.dataset.connectionInspectorLabel) {
        const restored = [...bookIndex.querySelectorAll(`[data-index-panel="${bookPage.dataset.connectionInspectorKind}"] [data-index-row]`)].find((row) => row.dataset.indexLabel === bookPage.dataset.connectionInspectorLabel);
        if (restored) activateInspectorTab(restored, "connections");
      }
    }
    body.querySelectorAll("[data-view-emotion-peak]").forEach((button) => button.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      const chapter = (pipeline.chapters || []).find((item) => Number(item.sequence || item.number) === Number(button.dataset.chapterSequence));
      const segment = chapter?.emotion?.segments?.find((item) => Number(item.sequence) === Number(button.dataset.segmentSequence));
      const peak = chapter?.emotion?.peaks?.find((item) => item.label === button.dataset.emotionLabel && Number(item.segmentSequence) === Number(button.dataset.segmentSequence));
      if (!chapter || !segment) return;
      openChapterSource(book.id, chapter.sequence || chapter.number, {...segment, label: button.dataset.emotionLabel, score: peak?.score}, chapter);
    }));
    body.querySelectorAll("[data-rollup-row-limit]").forEach((select) => select.addEventListener("change", () => {
      const rollup = select.closest(".whole-book-rollup");
      const selected = select.value === "all" ? "all" : Number(select.value) || 10;
      wholeBookRollupRowLimits[select.dataset.rollupKind] = selected;
      updateWholeBookRollupVisibility(rollup);
    }));
    body.querySelectorAll("[data-smell-sort]").forEach((button) => button.addEventListener("click", async () => {
      const nextMode = button.dataset.smellSort === "type" ? "type" : "position";
      if (nextMode === smellSortMode) return;
      smellSortMode = nextMode;
      localStorage.setItem(smellSortKey, smellSortMode);
      await showBookPage(book.id, "smells");
    }));
    body.querySelectorAll("[data-tag-rollup-cluster]").forEach((button) => button.addEventListener("click", () => {
      const selected = button.getAttribute("aria-pressed") !== "true";
      button.setAttribute("aria-pressed", String(selected));
      if (selected) selectedTagRollupClusters.add(button.dataset.tagRollupCluster);
      else selectedTagRollupClusters.delete(button.dataset.tagRollupCluster);
      updateWholeBookRollupVisibility(button.closest(".whole-book-rollup"));
    }));
    body.querySelectorAll(".whole-book-rollup.tags").forEach(updateWholeBookRollupVisibility);
    body.querySelectorAll("[data-rollup-chapter]").forEach((button) => button.addEventListener("click", async () => {
      const sequence = Number(button.dataset.rollupChapter || 0);
      const kind = button.dataset.rollupKind;
      let target = [...body.querySelectorAll(`details.chapter-signal.${kind}`)].find((details) => Number(details.dataset.refreshId || 0) === sequence);
      if (!target && ["emotion", "tag", "smell"].includes(kind)) {
        await navigateWorkspaceTab(book.id, `${kind}s`);
        target = [...document.querySelectorAll(`#book-workspace-body details.chapter-signal.${kind}`)].find((details) => Number(details.dataset.refreshId || 0) === sequence);
      }
      if (!target) return;
      target.open = true;
      target.scrollIntoView({behavior: "smooth", block: "start"});
      target.querySelector(":scope > summary")?.focus({preventScroll: true});
    }));
    body.querySelectorAll("[data-view-source-passage]").forEach((button) => button.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      const chapter = (pipeline.chapters || []).find((item) => Number(item.sequence || item.number) === Number(button.dataset.chapterSequence));
      if (!chapter) return;
      const start = Number(button.dataset.characterStart || 0);
      const end = Number(button.dataset.characterEnd || 0);
      const smellFinding = String(button.dataset.passageSequence || "").startsWith("smell")
        ? (chapter.smell?.candidates || []).find((item) => Number(item.characterStart || 0) === start && Number(item.characterEnd || 0) === end)
        : null;
      openChapterSource(book.id, chapter.sequence || chapter.number, {
        kind: smellFinding ? "review-candidate" : "source",
        sequence: button.dataset.passageSequence || "1",
        characterStart: start,
        characterEnd: end,
        quote: smellFinding?.sentence || "",
        comment: smellFinding ? `${smellRollupIssue(smellFinding)}: ${smellFinding.judgment?.reason || smellFinding.evidence?.[0]?.message || "This passage deserves editorial attention."}` : "",
      }, chapter);
    }));
    body.querySelectorAll("[data-smell-disposition]").forEach((button) => button.addEventListener("click", async () => {
      button.disabled = true;
      try {
        const response = await fetch(`/api/books/${encodeURIComponent(book.id)}/analysis/smell-disposition`, {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({chapter: button.dataset.chapterSequence, candidateId: button.dataset.smellCandidate, disposition: button.dataset.smellDisposition})});
        const payload = await response.json();
        if (!response.ok) throw new Error(payload.error || "This Smells decision could not be saved.");
        state.pipelineSignature = "";
        await showBookPage(book.id, "smells");
      } catch (error) {
        await confirmAction({context: "Smells decision not saved", title: "Bookinator could not save that decision", message: error.message, acceptLabel: "Close"});
        button.disabled = false;
      }
    }));
    body.querySelectorAll("[data-emotion-peak-preview]").forEach((button) => {
      button.addEventListener("mouseenter", () => hydrateEmotionPeakPreview(button, book.id));
      button.addEventListener("focus", () => hydrateEmotionPeakPreview(button, book.id));
    });
    body.querySelectorAll("[data-show-reading-details]").forEach((button) => button.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      openAnalysisDetails(button);
    }));
    refreshOpenAnalysisDetails(body);
    body.querySelectorAll("[data-show-stage-details]").forEach((button) => button.addEventListener("click", (event) => {
      event.preventDefault();
      openPipelineStageDetails(button);
    }));
    body.querySelectorAll("[data-show-chapter-group-details]").forEach((button) => button.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      openChapterGroupDetails(button);
    }));
    body.querySelectorAll("[data-open-pipeline-tab]").forEach((button) => button.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      navigateWorkspaceTab(book.id, button.dataset.openPipelineTab);
    }));
    body.querySelectorAll("[data-inference-view]").forEach((button) => button.addEventListener("click", () => {
      navigateWorkspaceTab(book.id, "inferences", button.dataset.inferenceView);
    }));
    openPendingDiagnostic(book.id, activeTab, body);
    const questionTable = body.querySelector("[data-question-table]");
    if (questionTable) {
      const sortQuestions = (key, direction) => {
        const rows = [...questionTable.querySelectorAll("[data-question-row]")];
        rows.sort((left, right) => {
          const a = left.dataset[`questionValue${key[0].toUpperCase()}${key.slice(1)}`];
          const b = right.dataset[`questionValue${key[0].toUpperCase()}${key.slice(1)}`];
          const comparison = key === "question" ? a.localeCompare(b) : Number(a) - Number(b);
          return direction === "asc" ? comparison : -comparison;
        });
        rows.forEach((row) => questionTable.append(row));
        questionTable.dataset.sortKey = key;
        questionTable.dataset.sortDirection = direction;
        questionTable.querySelectorAll("header > span").forEach((heading) => heading.setAttribute("aria-sort", "none"));
        const active = questionTable.querySelector(`[data-question-sort="${key}"]`)?.parentElement;
        active?.setAttribute("aria-sort", direction === "asc" ? "ascending" : "descending");
        const icon = active?.querySelector("i");
        if (icon) icon.textContent = direction === "asc" ? "↑" : "↓";
      };
      questionTable.querySelectorAll("[data-question-sort]").forEach((button) => button.addEventListener("click", () => {
        const key = button.dataset.questionSort;
        const direction = questionTable.dataset.sortKey === key ? (questionTable.dataset.sortDirection === "asc" ? "desc" : "asc") : button.dataset.sortFirst;
        sortQuestions(key, direction);
      }));
      sortQuestions("source", "asc");
    }
    const collapseButton = body.querySelector("[data-collapse-analysis]");
    if (collapseButton) {
      const disclosureRows = [...body.querySelectorAll("details")];
      const syncCollapseButton = () => {
        const anyOpen = disclosureRows.some((details) => details.open);
        collapseButton.disabled = !anyOpen;
        collapseButton.title = anyOpen ? "Collapse all open disclosures" : "All disclosures are collapsed";
      };
      collapseButton.addEventListener("click", () => {
        disclosureRows.forEach((details) => details.removeAttribute("open"));
        syncCollapseButton();
      });
      disclosureRows.forEach((details) => details.addEventListener("toggle", syncCollapseButton));
      syncCollapseButton();
    }
    body.querySelector("[data-stop-reading]")?.addEventListener("click", async (event) => {
      const stopButton = event.currentTarget;
      stopButton.disabled = true;
      stopButton.setAttribute("aria-busy", "true");
      await fetch("/api/library/pipeline/stop", {method: "POST"});
      await new Promise((resolve) => setTimeout(resolve, 200));
      state.pipelineSignature = "";
      showBookPage(book.id, activeTab);
    });
    body.querySelectorAll("[data-pipeline-action]").forEach((button) => button.addEventListener("click", async (event) => {
      const actionButton = event.currentTarget;
      const action = actionButton.dataset.pipelineAction;
      if (action === "start-over") {
        const restart = await confirmAction({
          context: "Restart the entire book",
          title: "Start this pipeline completely over?",
          message: "Bookinator will permanently remove every machine-generated chapter map, summary, dossier, emotion score, tag, Smells result, inference, LLM Review result, and saved timing for this book. The original source, book identity, saved reports, and human annotations remain. Reviewer sign-off is reopened. If this book is running, its active response will be stopped first.",
          acceptLabel: "Clear analysis & start over",
          danger: true,
        });
        if (!restart) return;
        actionButton.disabled = true;
        actionButton.setAttribute("aria-busy", "true");
        const response = await fetch(`/api/books/${encodeURIComponent(book.id)}/pipeline/start-over`, {method: "POST"});
        const result = await response.json();
        if (!response.ok) {
          actionButton.disabled = false;
          actionButton.removeAttribute("aria-busy");
          const error = response.status === 404
            ? "Bookinator’s server needs a restart before Start over is available. Stop ./bin/serve, run it again, then retry."
            : result.error || "Could not restart this pipeline.";
          body.insertAdjacentHTML("afterbegin", `<p class="pipeline-error">${escapeHtml(error)}</p>`);
          return;
        }
        state.pipelineSignature = "";
        showBookPage(book.id, activeTab);
        return;
      }
      if (action === "retry-failed") {
        const failedCount = failedAnalysisCount(pipeline);
        const retry = await confirmAction({context: "Pipeline recovery", title: `Retry ${failedCount} failed analysis result${failedCount === 1 ? "" : "s"}?`, message: "Bookinator will preserve each failed run in its history, return only failed chapter and chunk results to pending, and let the normal dependency queue retry them in order. Successful results stay untouched. If a model is active, Bookinator will pause it safely first.", acceptLabel: "Retry failed work"});
        if (!retry) return;
        actionButton.disabled = true;
        actionButton.setAttribute("aria-busy", "true");
        const response = await fetch(`/api/books/${encodeURIComponent(book.id)}/pipeline/retry-failed`, {method: "POST"});
        const result = await response.json();
        if (!response.ok) {
          actionButton.disabled = false;
          actionButton.removeAttribute("aria-busy");
          body.insertAdjacentHTML("afterbegin", `<p class="pipeline-error">${escapeHtml(result.error || "Could not retry the failed work.")}</p>`);
          return;
        }
        if (result.queuedBehindActiveResponse) {
          await confirmAction({context: "Recovery queued", title: "Failed work is next in line", message: "The current model response will finish first. Bookinator will then return all failed results to the normal dependency queue automatically.", acceptLabel: "Done"});
        }
        state.pipelineSignature = "";
        showBookPage(book.id, activeTab);
        return;
      }
      if (action === "restart") {
        const restart = await confirmAction({context: "Development reset", title: "Reset every chapter summary?", message: "Bookinator will archive the model and timing details for the current summaries, clear the whole-book rollup, mark every chapter pending, and rebuild this category from the beginning. Unrelated analysis and human annotations remain untouched. If a model response is active, the reset will begin safely after it finishes.", acceptLabel: "Reset summaries"});
        if (!restart) return;
      }
      if (action === "dossier-restart") {
        const restart = await confirmAction({context: "Development reset", title: "Reset every chunk dossier?", message: "Bookinator will archive the current dossier run details, clear the whole-book rollup, mark every source chunk pending, and rebuild this category from the beginning. Unrelated analysis and human annotations remain untouched. If a model response is active, the reset will begin safely after it finishes.", acceptLabel: "Reset dossiers"});
        if (!restart) return;
      }
      if (action === "questions" && (pipeline.questionTracker?.items || []).length) {
        const rebuild = await confirmAction({context: "Fresh reconciliation", title: "Rebuild questions and payoffs?", message: "Bookinator will replace the current groupings and payoff matches with a new whole-book reconciliation from the latest chapter summaries and dossiers.", acceptLabel: "Rebuild tracker"});
        if (!rebuild) return;
      }
      if (["emotion-restart", "tag-restart", "smell-restart"].includes(action)) {
        const emotions = action === "emotion-restart";
        const smells = action === "smell-restart";
        const restart = await confirmAction({context: "Development reset", title: emotions ? "Reset every chapter’s emotion scores?" : smells ? "Reset every chapter’s Smells review?" : "Reset every chapter’s tags?", message: `Bookinator will archive the current run details, clear the category rollup, mark every chapter pending for this pass, and rebuild the ${emotions ? "Hartmann emotion scores" : smells ? "local detector evidence and editorial judgments" : "evidence-bearing tags"} from the beginning. Unrelated analysis and human annotations remain untouched.${smells ? " Manual Smells dismissals are restored when the same source finding returns." : ""} If a model response is active, the reset will begin safely after it finishes.`, acceptLabel: emotions ? "Reset emotions" : smells ? "Reset Smells" : "Reset tags"});
        if (!restart) return;
      }
      if (action === "prepare" && pipeline.chapters?.length) {
        const rebuild = await confirmAction({context: "Rebuild manuscript", title: "Re-extract this book?", message: "Bookinator will recreate the canonical Markdown, chapter objects, and source chunks from the saved manuscript. Dependent summaries and dossiers will be marked stale, then regenerated automatically from the proposed map.", acceptLabel: "Rebuild manuscript"});
        if (!rebuild) return;
      }
      const originalLabel = actionButton.querySelector("small").textContent;
      actionButton.disabled = true;
      actionButton.setAttribute("aria-busy", "true");
      const start = await fetch("/api/library/pipeline/prioritize", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({bookId: book.id, action})});
      const result = await start.json();
      if (!start.ok) {
        actionButton.disabled = false;
        actionButton.querySelector("small").textContent = "Retry";
        actionButton.removeAttribute("aria-busy");
        body.insertAdjacentHTML("afterbegin", `<p class="pipeline-error">${escapeHtml(result.error || "Could not start the pipeline.")}</p>`);
        return;
      }
      if (result.queueProtocol !== 2) {
        actionButton.disabled = false;
        actionButton.querySelector("small").textContent = originalLabel;
        actionButton.removeAttribute("aria-busy");
        body.insertAdjacentHTML("afterbegin", '<p class="pipeline-error"><strong>Bookinator’s server needs a restart.</strong> The page is newer than the running local server, so no pipeline worker claimed this request. Stop <code>./bin/serve</code>, run it again, then press Continue.</p>');
        return;
      }
      state.pipelineSignature = "";
      showBookPage(book.id, activeTab);
    }));
    if (workspacePipelineNeedsPolling(book.id, pipeline)) state.pipelineTimer = setTimeout(() => showBookPage(book.id, activeTab), queued ? 500 : 1800);
  } catch (error) {
    body.innerHTML = `<p class="pipeline-error">${escapeHtml(error.message || "Pipeline unavailable.")}</p>`;
  }
}

function installTooltips() {
  const tooltip = document.querySelector("#app-tooltip");
  let owner = null;

  const normalize = (root = document) => {
    const candidates = [];
    if (root.nodeType === 1 && root.hasAttribute?.("title")) candidates.push(root);
    candidates.push(...root.querySelectorAll?.("[title]") || []);
    for (const element of candidates) {
      const copy = element.getAttribute("title")?.trim();
      if (copy) element.dataset.tooltip = copy;
      element.removeAttribute("title");
    }
  };

  const hide = () => {
    if (owner?.getAttribute("aria-describedby") === tooltip.id) owner.removeAttribute("aria-describedby");
    owner = null;
    tooltip.classList.remove("visible");
    tooltip.hidden = true;
  };

  const show = (element) => {
    const copy = element?.dataset.tooltip;
    if (!copy) return;
    owner = element;
    const heading = element.dataset.tooltipHeading?.trim();
    tooltip.replaceChildren();
    tooltip.classList.toggle("rich", Boolean(heading));
    if (heading) {
      const title = document.createElement("strong");
      title.textContent = heading;
      tooltip.append(title);
      const body = document.createElement("span");
      body.textContent = copy;
      tooltip.append(body);
    } else {
      tooltip.textContent = copy;
    }
    tooltip.hidden = false;
    tooltip.classList.add("visible");
    element.setAttribute("aria-describedby", tooltip.id);
    const anchor = element.getBoundingClientRect();
    const box = tooltip.getBoundingClientRect();
    const gap = 9;
    const margin = 10;
    const above = anchor.top - box.height - gap;
    const top = above >= margin ? above : Math.min(window.innerHeight - box.height - margin, anchor.bottom + gap);
    const centered = anchor.left + anchor.width / 2 - box.width / 2;
    const left = Math.max(margin, Math.min(window.innerWidth - box.width - margin, centered));
    tooltip.style.left = `${Math.round(left)}px`;
    tooltip.style.top = `${Math.round(top)}px`;
  };

  normalize();
  new MutationObserver((mutations) => {
    for (const mutation of mutations) {
      if (mutation.type === "attributes") normalize(mutation.target);
      else for (const node of mutation.addedNodes) if (node.nodeType === 1) normalize(node);
    }
  }).observe(document.body, {subtree: true, childList: true, attributes: true, attributeFilter: ["title"]});

  document.addEventListener("pointerover", (event) => {
    const target = event.target.closest?.("[data-tooltip]");
    if (target && target !== owner) show(target);
  });
  document.addEventListener("pointerout", (event) => {
    if (owner && !owner.contains(event.relatedTarget)) hide();
  });
  document.addEventListener("focusin", (event) => show(event.target.closest?.("[data-tooltip]")));
  document.addEventListener("focusout", (event) => {
    if (owner && !owner.contains(event.relatedTarget)) hide();
  });
  document.addEventListener("keydown", (event) => { if (event.key === "Escape") hide(); });
  window.addEventListener("scroll", hide, true);
  window.addEventListener("resize", hide);
}

function route() {
  const [collection = "books", part, tab, subtab] = location.hash.replace(/^#/, "").split("/");
  if (collection === "book" && part) showBookPage(part, tab, subtab);
  else if (collection === "pipeline") showPipelinePage();
  else if (collection === "machine") openSystemPanel(part === "models" ? "models" : "machine");
  else if (collection === "books" || !articlePages[collection]) showBooksPage();
  else showArticlePage(collection, part);
}

const navigationToggle = document.querySelector("#navigation-toggle");
const primaryNavigation = document.querySelector("#primary-navigation");

function closePrimaryNavigation() {
  primaryNavigation?.classList.remove("open");
  navigationToggle?.setAttribute("aria-expanded", "false");
  navigationToggle?.setAttribute("aria-label", "Open navigation");
}

navigationToggle?.addEventListener("click", (event) => {
  event.stopPropagation();
  const opening = !primaryNavigation.classList.contains("open");
  primaryNavigation.classList.toggle("open", opening);
  navigationToggle.setAttribute("aria-expanded", String(opening));
  navigationToggle.setAttribute("aria-label", opening ? "Close navigation" : "Open navigation");
});
document.addEventListener("click", (event) => {
  if (!event.target.closest(".topbar")) closePrimaryNavigation();
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") closePrimaryNavigation();
});
window.matchMedia("(min-width: 1051px)").addEventListener?.("change", (event) => { if (event.matches) closePrimaryNavigation(); });

document.querySelectorAll('button[data-page="books"]').forEach((button) => button.addEventListener("click", () => {
  closePrimaryNavigation();
  if (location.hash === "#books") showBooksPage();
  else location.hash = "books";
}));
document.querySelector("#pipeline-nav")?.addEventListener("click", () => { closePrimaryNavigation(); location.hash = "pipeline"; });
document.querySelector("#analysis-nav")?.addEventListener("click", () => {
  closePrimaryNavigation();
  const current = updateAnalysisNavigation();
  location.hash = current ? `book/${current.id}/${rememberedAnalysisTab(current.id)}` : "books";
});
document.querySelector("#machine-nav")?.addEventListener("click", () => {
  closePrimaryNavigation();
  location.hash = "machine";
});
document.querySelector("#refresh-analysis-result")?.addEventListener("click", async (event) => {
  const button = event.currentTarget;
  const bookId = state.currentBookId;
  const kind = button.dataset.refreshKind;
  const id = button.dataset.refreshId;
  if (!bookId || !kind || !id) return;
  const restarting = button.dataset.runStatus === "running";
  const retrying = button.dataset.runStatus === "failed";
  const retryInterruptsQueue = retrying && Boolean(state.globalPipeline?.running);
  const confirmed = await confirmAction({
    context: restarting ? "Restart active analysis" : retrying ? "Retry failed analysis" : "Refresh saved analysis",
    title: restarting ? "Stop and restart this result?" : retrying ? "Retry this result?" : "Run this result again?",
    message: restarting ? "Bookinator will stop the active local response, preserve its diagnostics, and queue this result again with the currently assigned model." : retryInterruptsQueue ? "Bookinator will finish the active model response, preserve this failed run, then retry it next with the currently assigned model. You do not need to stop the library queue." : "Bookinator will preserve the prior run in its history, then replace this result using the currently assigned model.",
    acceptLabel: restarting ? "Restart" : retrying ? "Retry" : "Refresh",
  });
  if (!confirmed) return;
  button.disabled = true;
  try {
    const response = await fetch(`/api/books/${encodeURIComponent(bookId)}/analysis/refresh`, {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({kind, id})});
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || "This result could not be refreshed.");
    closeDialog("reading-details-dialog");
    if (payload.queuedBehindActiveResponse) {
      await confirmAction({context: "Retry queued", title: "This result is next in line", message: "The current model response will finish first. Bookinator now shows this result as waiting and will retry it automatically after the active response finishes.", acceptLabel: "Done"});
    } else {
      markAnalysisResultWaiting(kind, id);
    }
    state.pipelineSignature = "";
    await showBookPage(bookId, document.querySelector("#book-page").dataset.activeTab || "summaries");
  } catch (error) {
    const staleOptionalReviewServer = ["context", "llm-review"].includes(kind) && /not refreshable/i.test(error.message);
    await confirmAction({
      context: staleOptionalReviewServer ? "Server restart needed" : "Refresh failed",
      title: staleOptionalReviewServer ? "This running server predates review refresh" : "Bookinator could not refresh this result",
      message: staleOptionalReviewServer
        ? "Let the active model response finish, then restart Bookinator. The completed Context and LLM Review rows will support Refresh after that restart."
        : error.message,
      acceptLabel: "Close",
    });
  } finally {
    button.disabled = false;
  }
});
document.querySelector("#restart-pipeline-stage")?.addEventListener("click", async (event) => {
  const action = event.currentTarget.dataset.pipelineAction;
  const bookId = state.currentBookId;
  if (!action || !bookId) return;
  const confirmed = await confirmAction({context: "Restart active pipeline step", title: "Stop and restart this step?", message: "Bookinator will stop the current response, preserve completed units and saved diagnostics, then queue this analysis step again from its first unfinished unit.", acceptLabel: "Restart step"});
  if (!confirmed) return;
  event.currentTarget.disabled = true;
  try {
    await fetch("/api/library/pipeline/stop", {method: "POST"});
    const response = await fetch("/api/library/pipeline/prioritize", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({bookId, action})});
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || "This pipeline step could not be restarted.");
    closeDialog("reading-details-dialog");
    state.pipelineSignature = "";
    await showBookPage(bookId, document.querySelector("#book-page").dataset.activeTab || "pipeline");
  } catch (error) {
    await confirmAction({context: "Restart failed", title: "Bookinator could not restart this step", message: error.message, acceptLabel: "Close"});
  } finally {
    event.currentTarget.disabled = false;
  }
});
installTooltips();
installChapterFontControls();
window.addEventListener("hashchange", async () => {
  if (identityFormIsInline()) {
    const editingBookId = state.editingBookId;
    const saved = await flushIdentityAutosave();
    if (!saved) {
      history.replaceState(null, "", `#book/${editingBookId}/identity`);
      return;
    }
  }
  route();
});
route();
if (!localStorage.getItem(introKey) && (!location.hash || location.hash === "#books")) showDialog("welcome-dialog");
async function hydrateLibrary() {
  const browserBooks = JSON.parse(localStorage.getItem(storageKey) || "[]");
  try {
    const response = await fetch("/api/books");
    const payload = await response.json();
    state.books = Array.isArray(payload.books) ? payload.books : [];
    state.globalPipeline = payload.pipeline || state.globalPipeline;
    for (const oldBook of browserBooks) {
      if (state.books.some((book) => book.id === oldBook.id)) continue;
      const migration = await fetch("/api/books", { method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(oldBook) });
      if (migration.ok) {
        const { book } = await migration.json();
        state.books.push(book);
      }
    }
    localStorage.removeItem(storageKey);
  } catch {
    state.books = browserBooks;
  }
  render();
  if (state.globalPipeline.running || (state.globalPipeline.enabled && state.globalPipeline.waitingBooks > 0)) refreshLibraryBooks({poll: true});
  if (location.hash.startsWith("#book/")) route();
}

hydrateLibrary();
