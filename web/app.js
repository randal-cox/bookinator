import { articlePages, roadmapItems } from "./pages.js";
import { fallbackIcon, imageFileToIcon, renderIcon, shortMark, unicodeIcon } from "./icon-picker.js";
import { isTemporalDossierObservation } from "./dossier-index.js";

const storageKey = "bookinator.library.v1";
const introKey = "bookinator.intro.seen";
const currentBookKey = "bookinator.current-book.v1";
const analysisTabsKey = "bookinator.analysis-tabs.v1";
const workspaceGroupsKey = "bookinator.workspace-groups.v1";
const chapterFontScaleKey = "bookinator.chapter-font-scale.v1";
const sourceAnalysisKey = "bookinator.source-analysis.v1";
const sourceAnalysisDefaults = {emotion: {enabled: true, threshold: 10, neutral: true}, tag: {enabled: true, threshold: 25}};
let sourceAnalysisPreferences = structuredClone(sourceAnalysisDefaults);
let rememberedAnalysisTabs = {};
let rememberedWorkspaceGroups = {};
try {
  const saved = JSON.parse(localStorage.getItem(sourceAnalysisKey) || "{}");
  sourceAnalysisPreferences = {
    emotion: {...sourceAnalysisDefaults.emotion, ...(saved.emotion || {})},
    tag: {...sourceAnalysisDefaults.tag, ...(saved.tag || {})},
  };
} catch {}
try {
  rememberedAnalysisTabs = JSON.parse(localStorage.getItem(analysisTabsKey) || "{}") || {};
} catch {}
try {
  rememberedWorkspaceGroups = JSON.parse(localStorage.getItem(workspaceGroupsKey) || "{}") || {};
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
  rememberedSelection: [],
  sort: {key: "title", direction: "asc"},
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
};
const chapterSourcePreviewCache = new Map();

const directory = document.querySelector("#book-directory");
const search = document.querySelector("#search");
const filter = document.querySelector("#status-filter");
const bookIntakeInput = document.querySelector("#book-intake-file");

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
  return String(left).localeCompare(String(right), undefined, {numeric: true, sensitivity: "base"});
}

function sortedBooks(books) {
  const direction = state.sort.direction === "desc" ? -1 : 1;
  if (state.sort.key === "selection") return [...books].sort((left, right) => direction * (Number(state.selection.has(left.id)) - Number(state.selection.has(right.id))));
  const value = {
    title: (book) => book.title,
    priority: (book) => ({high: 0, normal: 1, low: 2, shelved: 3}[book.priority || "normal"] ?? 1),
    analysis: (book) => book.pipeline?.progress?.total ? book.pipeline.progress.completed / book.pipeline.progress.total : -1,
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
  const completed = Number(pipeline.completed || 0);
  const total = Number(pipeline.total || 0);
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
  const detail = enabled
    ? running ? "Higher-priority books run first; each book advances chapter by chapter." : "The queue is on and will pick up new work automatically."
    : waitingCount ? "The queue is off. Start it to resume all eligible work." : "New analysis will appear here when a manuscript or dependency changes.";
  document.querySelector("#library-pipeline-progress").innerHTML = progressPanel({
    label: "Overall library progress",
    completed,
    total,
    unit: "steps",
    percent,
    statusCopy: etaText,
    basisCopy: detail,
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
  updateLocalQueueStatus();
}

function queuedBooks() {
  return state.books.filter((book) => (book.priority || "normal") !== "shelved" && book.pipeline?.workRemaining);
}

function pipelineBookStatus(book) {
  const globalActivity = state.globalPipeline?.activity || {};
  if (globalActivity.book === book.title && globalActivity.text) return {
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

function renderPipelineQueue() {
  const list = document.querySelector("#pipeline-book-list");
  const summary = document.querySelector("#pipeline-queue-summary");
  if (!list || !summary) return;
  const books = sortedBooks(queuedBooks());
  summary.textContent = books.length
    ? `${books.length} ${books.length === 1 ? "book is" : "books are"} eligible for automatic analysis.`
    : "No books are waiting for analysis.";
  if (!books.length) {
    list.innerHTML = '<div class="pipeline-empty"><strong>The queue is clear.</strong><span>Unshelved books appear here whenever analysis becomes stale or incomplete.</span></div>';
    return;
  }
  list.innerHTML = books.map((book) => {
    const status = pipelineBookStatus(book);
    return `<article class="pipeline-book-row">
      <div class="pipeline-book-identity"><span class="book-cover" data-pipeline-book-icon="${escapeHtml(book.id)}"></span><div><strong>${escapeHtml(book.title)}</strong><small>${escapeHtml(book.author || "Author not specified")} · ${escapeHtml((book.priority || "normal").replace(/^./, (letter) => letter.toUpperCase()))} priority</small></div></div>
      <span class="pipeline-book-status"><strong>${escapeHtml(status.label)}</strong><small>${escapeHtml(status.detail)}</small></span>
      <button class="pipeline-remove-book action-button" type="button" data-remove-from-queue="${escapeHtml(book.id)}" title="Shelve ${escapeHtml(book.title)} and remove it from automatic analysis"><span class="command-icon" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="M5 12h14"/></svg></span><small>Remove</small></button>
    </article>`;
  }).join("");
  books.forEach((book) => renderIcon(list.querySelector(`[data-pipeline-book-icon="${CSS.escape(book.id)}"]`), book.icon, book.title));
  list.querySelectorAll("[data-remove-from-queue]").forEach((button) => button.addEventListener("click", async () => {
    const book = state.books.find((item) => item.id === button.dataset.removeFromQueue);
    if (!book || button.disabled) return;
    const label = button.querySelector("small");
    button.disabled = true;
    label.textContent = "Removing…";
    try {
      await saveBookPriority(book, "shelved");
      await refreshLibraryBooks({poll: true});
    } catch (error) {
      button.disabled = false;
      label.textContent = "Remove";
      await confirmAction({context: "Queue unchanged", title: "Bookinator could not remove this book", message: error.message, acceptLabel: "Close"});
    }
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
    <div class="directory-heading"><span class="selection-header"><input type="checkbox" data-select-visible aria-label="Select all visible books"><button type="button" data-sort="selection" title="Sort selected books first" aria-label="Sort selected books first">${state.sort.key === "selection" ? state.sort.direction === "desc" ? "↓" : "↑" : "↕"}</button></span><span>${sortButton("title", "Book")}</span><span>${sortButton("priority", "Priority")}</span><span>${sortButton("analysis", "Analysis")}</span><span>${sortButton("ingested", "Ingested")}</span><span>${sortButton("changed", "Last change")}</span><span></span></div>
    ${books.map((book) => `<article class="book-row">
      <label class="book-selector"><input type="checkbox" data-select-book="${escapeHtml(book.id)}"${state.selection.has(book.id) ? " checked" : ""}><span class="sr-only">Select ${escapeHtml(book.title)}</span></label>
      <div class="book-identity"><span class="book-cover" data-book-icon="${escapeHtml(book.id)}"></span><div><button type="button" class="book-title-link" data-open-book="${escapeHtml(book.id)}">${escapeHtml(book.title)}</button><span>${escapeHtml(book.author || "Author not specified")}</span></div></div>
      <label class="priority-control priority-${escapeHtml(book.priority || "normal")}"><span class="sr-only">Priority for ${escapeHtml(book.title)}</span><select data-book-priority="${escapeHtml(book.id)}"><option value="high"${book.priority === "high" ? " selected" : ""}>High</option><option value="normal"${!book.priority || book.priority === "normal" ? " selected" : ""}>Normal</option><option value="low"${book.priority === "low" ? " selected" : ""}>Low</option><option value="shelved"${book.priority === "shelved" ? " selected" : ""}>Shelved</option></select></label>
      <span class="pipeline-cell"><strong>${Number(book.pipeline?.progress?.completed || 0).toLocaleString()} / ${Number(book.pipeline?.progress?.total || 0).toLocaleString()}</strong><small>${book.pipeline?.workRemaining ? "steps complete" : book.pipeline?.progress?.total ? "all steps current" : "awaiting chapter map"}</small></span>
      <span class="date-cell">${bookDateMarkup(book.ingestedAt)}</span>
      <span class="date-cell">${bookDateMarkup(book.pipeline?.updatedAt || book.updatedAt || book.createdAt)}</span>
      <button class="row-action-icon-button" type="button" data-open-book="${escapeHtml(book.id)}" title="Open ${escapeHtml(book.title)}" aria-label="Open ${escapeHtml(book.title)}"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 16.5V20h3.5L18 9.5 14.5 6 4 16.5Z"/><path d="m13 7.5 3.5 3.5"/></svg></button>
    </article>`).join("")}`;
  books.forEach((book) => renderIcon(directory.querySelector(`[data-book-icon="${CSS.escape(book.id)}"]`), book.icon, book.title));
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
      book.priority = nextPriority;
      select.dataset.saving = "true";
      select.disabled = true;
      select.closest(".priority-control").className = `priority-control priority-${nextPriority}`;
      try {
        await saveBookPriority(book, nextPriority);
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

function confirmAction({context = "Confirm action", title, message, acceptLabel = "Continue"}) {
  const backdrop = document.querySelector("#confirmation-dialog");
  backdrop.querySelector("#confirmation-context").textContent = context;
  backdrop.querySelector("#confirmation-title").textContent = title;
  backdrop.querySelector("#confirmation-message").textContent = message;
  const accept = backdrop.querySelector("#confirmation-accept");
  accept.textContent = acceptLabel;
  showDialog("confirmation-dialog");
  return new Promise((resolve) => {
    const finish = (answer) => {
      backdrop.hidden = true;
      accept.removeEventListener("click", approve);
      backdrop.querySelectorAll("[data-confirm-cancel]").forEach((button) => button.removeEventListener("click", cancel));
      resolve(answer);
    };
    const approve = () => finish(true);
    const cancel = () => finish(false);
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
  state.editingBookId = null;
  state.draftIcon = null;
  state.draftManuscriptId = null;
  state.suggestedAbbreviation = "";
  state.abbreviationTitle = "";
  document.querySelector("#book-form").reset();
  manuscriptWell.hidden = false;
  document.querySelector("#manuscript-well-title").textContent = "Drop your manuscript into the well";
  document.querySelector("#manuscript-well-copy").textContent = "PDF, DOCX, EPUB, TXT, or Markdown";
  manuscriptWell.classList.remove("has-file");
  document.querySelector("#file-name").textContent = "";
  document.querySelector("#identity-status").hidden = true;
  document.querySelector("#book-dialog-context").textContent = "New book";
  document.querySelector("#add-title").textContent = "Bring in a manuscript";
  document.querySelector("#book-dialog-description").textContent = "Drop in a PDF, ebook, or text manuscript. Bookinator will inspect its opening locally, suggest the title and author, and let you correct either before continuing.";
  document.querySelector("#save-book").textContent = "Add to library";
  resetBookMarkImageStatus();
  refreshDraftIcon();
  showDialog("add-dialog");
  document.querySelector("#manuscript-well").focus();
}

function openExistingBook(bookId) {
  const book = state.books.find((item) => item.id === bookId);
  if (!book) return;
  state.editingBookId = book.id;
  state.draftIcon = book.icon || null;
  state.draftManuscriptId = book.manuscriptId || null;
  state.suggestedAbbreviation = book.abbreviation || "";
  state.abbreviationTitle = book.title || "";
  document.querySelector("#book-form").reset();
  titleInput.value = book.title || "";
  document.querySelector("#book-author").value = book.author || "";
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
  resetBookMarkImageStatus();
  refreshDraftIcon();
  showDialog("add-dialog");
  titleInput.focus();
}

function manuscriptFromDrop(event) {
  return [...event.dataTransfer.files].find((candidate) => /\.(pdf|docx|epub|txt|md)$/i.test(candidate.name));
}

async function acceptBookFile(file) {
  if (!file) return;
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
  await confirmAction({context: "File not added", title: "Bookinator does not recognize this format", message: "Choose an EPUB, PDF, DOCX, Markdown, text, or Bookinator JSON file.", acceptLabel: "Close"});
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

document.querySelectorAll(".backdrop").forEach((backdrop) => {
  backdrop.addEventListener("click", (event) => {
    if (event.target !== backdrop || backdrop.id === "welcome-dialog") return;
    if (backdrop.id === "confirmation-dialog") backdrop.querySelector("[data-confirm-cancel]").click();
    else closeDialog(backdrop.id);
  });
});
document.querySelectorAll('.backdrop [role="dialog"]').forEach(installMovableDialog);

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
const markPreview = document.querySelector("#book-mark-preview");
const markText = document.querySelector("#book-mark-text");
const imageMarkWell = document.querySelector("#image-mark-well");
const imageMarkInput = document.querySelector("#book-mark-image");
const imageMarkStatus = document.querySelector("#book-mark-image-status");
const addDialog = document.querySelector("#add-dialog");
const markColor = document.querySelector("#book-mark-color");
const markOutline = document.querySelector("#book-mark-outline");

function resetBookMarkImageStatus() {
  imageMarkWell.classList.remove("invalid", "working");
  imageMarkWell.querySelector("span").textContent = "Choose image";
  imageMarkStatus.className = "book-mark-image-status";
  imageMarkStatus.textContent = "Drop, paste, or choose an image · ⌘V on macOS, Ctrl+V on Windows and Linux";
}

function refreshDraftIcon() {
  renderIcon(markPreview, state.draftIcon, titleInput.value || "B");
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
}

titleInput.addEventListener("input", () => {
  if (titleInput.value.trim() !== state.abbreviationTitle) state.suggestedAbbreviation = "";
  if (!state.draftIcon) refreshDraftIcon();
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
  renderIcon(markPreview, state.draftIcon, titleInput.value || "B");
});

function updateDraftAppearance() {
  if (!state.draftIcon) state.draftIcon = fallbackIcon(titleInput.value || "B");
  state.draftIcon.background = markColor.value;
  state.draftIcon.outline = markOutline.checked;
  renderIcon(markPreview, state.draftIcon, titleInput.value || "B");
}
markColor.addEventListener("input", updateDraftAppearance);
markColor.addEventListener("change", updateDraftAppearance);
markOutline.addEventListener("change", updateDraftAppearance);

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
  titleInput.value = "";
  authorInput.value = "";
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
    (titleInput.value ? authorInput : titleInput).focus();
  } catch (error) {
    titleInput.value = file.name.replace(/\.(pdf|docx|epub|txt|md)$/i, "").replace(/[-_]+/g, " ");
    if (!state.draftIcon) refreshDraftIcon();
    status.className = "identity-status warning";
    status.textContent = error instanceof Error && error.message ? error.message : "Bookinator could not inspect this manuscript. Check the local setup, then try again.";
    titleInput.focus();
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

document.querySelector("#book-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const title = document.querySelector("#book-title").value.trim();
  const author = document.querySelector("#book-author").value.trim();
  const existing = state.books.find((item) => item.id === state.editingBookId);
  updateDraftAppearance();
  const book = { ...existing, id: existing?.id || crypto.randomUUID(), title, author, icon: state.draftIcon || fallbackIcon(title), abbreviation: state.suggestedAbbreviation, status: existing?.status || "new", progress: existing?.progress || "Ready to inspect", updated: "Just now", manuscriptId: state.draftManuscriptId };
  const status = document.querySelector("#identity-status");
  let savedBook;
  try {
    const response = await fetch("/api/books", { method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(book) });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || "Bookinator could not save this book.");
    savedBook = result.book;
    state.books = existing
      ? state.books.map((item) => item.id === result.book.id ? result.book : item)
      : [result.book, ...state.books];
  } catch (error) {
    status.hidden = false;
    status.className = "identity-status warning";
    status.textContent = error instanceof Error ? error.message : "Bookinator could not save this book.";
    return;
  }
  event.target.reset();
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
  if (existing) route();
  else location.hash = `book/${savedBook.id}/pipeline`;
});

search.addEventListener("input", render);
filter.addEventListener("change", render);

async function refreshLibraryBooks({poll = false} = {}) {
  clearTimeout(state.libraryTimer);
  const response = await fetch("/api/books");
  const payload = await response.json();
  if (response.ok && Array.isArray(payload.books)) {
    state.books = payload.books;
    state.globalPipeline = payload.pipeline || state.globalPipeline;
  }
  if (!state.priorityInteractionActive) render();
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

document.querySelector("#export-books").addEventListener("click", async () => {
  if (!state.selection.size) return;
  const response = await fetch(`/api/library/export?ids=${encodeURIComponent([...state.selection].join(","))}`);
  const blob = await response.blob();
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = `bookinator-analysis-${new Date().toISOString().slice(0, 10)}.json`;
  link.click();
  setTimeout(() => URL.revokeObjectURL(link.href), 1000);
});

document.querySelector("#delete-books").addEventListener("click", async () => {
  if (!state.selection.size) return;
  const count = state.selection.size;
  const approved = await confirmAction({context: "Delete from this computer", title: `Delete ${count} selected ${count === 1 ? "book" : "books"}?`, message: "This removes the saved PDF, chapter summaries, pipeline history, and library record. Export first if you may need the analysis later.", acceptLabel: "Delete permanently"});
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

async function openSystemPanel(panelName) {
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
  showDialog("system-dialog");
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
    wireSetupInstructions(document.querySelector("#system-dialog"));
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
      document.querySelector("#hardware-advice").innerHTML = `<strong>${system.memoryGiB} GB of unified memory gives Bookinator room to think.</strong>Use <b>${escapeHtml(primaryRecommendation)}</b> as the primary editor. ${heavyweightAdvice}`;
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
  clearTimeout(state.pipelineTimer);
  document.querySelector("#books-page").hidden = false;
  document.querySelector("#pipeline-page").hidden = true;
  document.querySelector("#article-page").hidden = true;
  document.querySelector("#book-page").hidden = true;
  document.querySelectorAll(".topbar nav [data-page]").forEach((item) => item.classList.toggle("active", item.dataset.page === "books"));
  document.querySelectorAll(".footer-links a").forEach((link) => link.removeAttribute("aria-current"));
  document.title = "Books · Bookinator";
}

function showPipelinePage() {
  clearTimeout(state.pipelineTimer);
  document.querySelector("#books-page").hidden = true;
  document.querySelector("#pipeline-page").hidden = false;
  document.querySelector("#article-page").hidden = true;
  document.querySelector("#book-page").hidden = true;
  document.querySelector("#welcome-dialog").hidden = true;
  document.querySelectorAll(".topbar nav [data-page]").forEach((item) => item.classList.toggle("active", item.dataset.page === "pipeline"));
  document.querySelectorAll(".footer-links a").forEach((link) => link.removeAttribute("aria-current"));
  renderPipelineQueue();
  renderPipelineDiagnostics();
  updateGlobalPipelineStatus();
  document.title = "Pipeline · Bookinator";
}

function showArticlePage(collection, requestedTab) {
  clearTimeout(state.pipelineTimer);
  const page = articlePages[collection] || articlePages.about;
  const tabKeys = Object.keys(page.tabs);
  const activeTab = tabKeys.includes(requestedTab) ? requestedTab : tabKeys[0];
  document.querySelector("#books-page").hidden = true;
  document.querySelector("#pipeline-page").hidden = true;
  document.querySelector("#article-page").hidden = false;
  document.querySelector("#book-page").hidden = true;
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
  const minutes = Math.floor(rounded / 60);
  const remainder = rounded % 60;
  return `${minutes}m${remainder ? ` ${remainder}s` : ""}`;
}

function liveDurationMarkup({startedAt = "", completedAt = "", duration = null, status = "pending"} = {}) {
  const running = status === "running" && Boolean(startedAt);
  let seconds = running ? Number.NaN : Number(duration);
  if ((!Number.isFinite(seconds) || seconds < 0) && startedAt && (completedAt || running)) {
    const end = running ? new Date() : new Date(completedAt);
    seconds = (end - new Date(startedAt)) / 1000;
  }
  const label = formatRunDuration(Number.isFinite(seconds) && seconds >= 0 ? seconds : null, status);
  return `<span${running ? ` data-live-duration data-started-at="${escapeHtml(startedAt)}"` : ""}>${escapeHtml(label)}${running && label !== "In progress" ? "+" : ""}</span>`;
}

let readingDetailsClock = null;
function startReadingDetailsClock() {
  clearInterval(readingDetailsClock);
  const update = () => document.querySelectorAll("#reading-details-dialog [data-live-duration]").forEach((item) => {
    const elapsed = (Date.now() - new Date(item.dataset.startedAt).valueOf()) / 1000;
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
  if (Number.isFinite(Number(stage.durationSeconds))) return Number(stage.durationSeconds);
  if (stage.id === "summaries") {
    const durations = (pipeline.chapters || []).map((chapter) => Number(chapter.durationSeconds)).filter(Number.isFinite);
    if (durations.length) return durations.reduce((total, duration) => total + duration, 0);
  }
  if (["emotions", "tags", "smells"].includes(stage.id)) {
    const prefix = stage.id === "emotions" ? "emotion" : stage.id === "tags" ? "tag" : "smell";
    const durations = (pipeline.chapters || []).map((chapter) => Number(chapter[`${prefix}DurationSeconds`])).filter(Number.isFinite);
    if (durations.length) return durations.reduce((total, duration) => total + duration, 0);
  }
  if (stage.id === "dossiers") {
    const durations = (pipeline.chunks || []).map((chunk) => Number(chunk.dossierDurationSeconds)).filter(Number.isFinite);
    if (durations.length) return durations.reduce((total, duration) => total + duration, 0);
  }
  if (stage.startedAt && stage.completedAt) {
    const elapsed = (new Date(stage.completedAt) - new Date(stage.startedAt)) / 1000;
    if (Number.isFinite(elapsed) && elapsed >= 0) return elapsed;
  }
  return null;
}

function pipelineStageFailures(stage, pipeline) {
  if (stage.id === "summaries") return (pipeline.chapters || []).filter((chapter) => chapter.status === "failed").map((chapter) => `${displayHeading(chapter.title) || "Chapter"}: ${chapter.error || "The summary failed."}`);
  if (["emotions", "tags", "smells"].includes(stage.id)) {
    const prefix = stage.id === "emotions" ? "emotion" : stage.id === "tags" ? "tag" : "smell";
    return (pipeline.chapters || []).filter((chapter) => chapter[`${prefix}Status`] === "failed").map((chapter) => `${displayHeading(chapter.title) || "Chapter"}: ${chapter[`${prefix}Error`] || `The ${prefix} pass failed.`}`);
  }
  if (stage.id === "dossiers") return (pipeline.chunks || []).filter((chunk) => chunk.dossierStatus === "failed").map((chunk) => `${displayHeading(chunk.chapterLabel) || "Chapter"}, chunk ${chunk.chunkInChapter || 1}: ${chunk.dossierError || "The dossier failed."}`);
  if (stage.id === "questions") return pipeline.questionTracker?.status === "failed" ? [pipeline.questionTracker.error || "Question reconciliation failed."] : [];
  if (stage.id === "structure") return pipeline.chapterMapWarnings || [];
  return stage.error ? [stage.error] : [];
}

function pipelineStageScope(stage, pipeline, book) {
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
  return [...(pipeline.stages || [])].filter((stage) => !["questions", "inferences"].includes(stage.id));
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
  return `<article class="pipeline-stage ${escapeHtml(status)}${isSource ? " source-document-stage" : ""}${inferenceChild ? " inference-algorithm" : ""}" data-pipeline-stage="${escapeHtml(stage.id)}"><span class="stage-mark">${status === "complete" ? "✓" : status === "running" ? "↻" : ["failed", "warning"].includes(status) ? "!" : status === "blocked" ? "—" : "·"}</span><div class="pipeline-stage-copy"><span class="pipeline-stage-identity"><strong>${escapeHtml(stage.label || stage.id)}</strong><p>${escapeHtml(isSource ? (stage.sourceFilename || book.sourceFilename || stage.detail) : (stage.detail || "Waiting for the previous stage."))}</p><span class="pipeline-stage-meta"><small>${stage.method ? `${escapeHtml(stage.method)} · ` : stage.model ? `Model: ${escapeHtml(stage.model)} · ` : ""}${stage.completedAt ? `Finished ${escapeHtml(formatPipelineTime(stage.completedAt))}` : stage.startedAt ? `Started ${escapeHtml(formatPipelineTime(stage.startedAt))}` : escapeHtml(statusLabel)}</small>${inspect}</span></span>${sourceMetadata}</div><span class="pipeline-stage-reporting">${download}<button class="pipeline-stage-badge" data-show-stage-details type="button" title="Inspect run notes and timing for ${escapeHtml(stage.label || stage.id)}">${escapeHtml(statusLabel)}</button></span><template class="pipeline-stage-details-template">${pipelineStageDetails(stage, pipeline, book)}</template></article>`;
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
  const actions = {summaries: "restart", dossiers: "dossier-restart", emotions: "emotion-restart", tags: "tag-restart", smells: "smell-restart", questions: "questions"};
  restart.hidden = stage.classList.contains("running") ? !actions[stage.dataset.pipelineStage] : true;
  restart.dataset.pipelineAction = actions[stage.dataset.pipelineStage] || "";
  document.querySelector("#refresh-analysis-result").hidden = true;
  showDialog("reading-details-dialog");
  startReadingDetailsClock();
}

function updateWorkspaceTabProgress(tabs, pipeline, activeTab) {
  const stages = pipeline.stages || [];
  const stageComplete = (id) => stages.some((stage) => stage.id === id && stage.status === "complete");
  const chapters = pipeline.chapters || [];
  const chunks = pipeline.chunks || [];
  const chapterSummariesComplete = chapters.length > 0 && chapters.every((chapter) => chapter.status === "complete");
  const chunkDossiersComplete = chunks.length > 0 && chunks.every((chunk) => chunk.dossierStatus === "complete");
  const wholeSummaryComplete = pipeline.wholeBookSummary?.status === "complete" && Boolean(pipeline.wholeBookSummary?.summary);
  const wholeDossierComplete = pipeline.wholeBookDossier?.status === "complete" && Boolean(pipeline.wholeBookDossier?.summary || pipeline.wholeBookDossier?.synopsis || pipeline.wholeBookDossier?.content);
  const complete = {
    pipeline: stages.length > 0 && stages.every((stage) => stage.status === "complete"),
    chapters: Boolean(pipeline.chapterMapApproved),
    summaries: (stageComplete("summaries") || chapterSummariesComplete) && wholeSummaryComplete,
    emotions: stageComplete("emotions") || (chapters.length > 0 && chapters.every((chapter) => chapter.emotionStatus === "complete")),
    tags: stageComplete("tags") || (chapters.length > 0 && chapters.every((chapter) => chapter.tagStatus === "complete")),
    smells: stageComplete("smells") || (chapters.length > 0 && chapters.every((chapter) => chapter.smellStatus === "complete")),
    dossiers: (stageComplete("dossiers") || chunkDossiersComplete) && wholeDossierComplete,
    inferences: Array.isArray(pipeline.inferences) && pipeline.inferences.length > 0 && pipeline.inferences.every((inference) => inference.status === "complete"),
    report: wholeSummaryComplete || chapterSummariesComplete,
    overview: wholeSummaryComplete,
    "smell-report": (pipeline.chapters || []).some((chapter) => chapter.smellStatus === "complete"),
    "emotion-map": (pipeline.chapters || []).some((chapter) => chapter.emotionStatus === "complete"),
    connections: chunkDossiersComplete,
    questions: (pipeline.questionTracker?.items || []).length > 0 || pipeline.questionTracker?.status === "complete",
  };
  tabs.querySelectorAll("[data-book-tab]").forEach((button) => {
    const tab = button.dataset.bookTab;
    button.classList.toggle("is-complete", Boolean(complete[tab]));
    button.toggleAttribute("data-complete", Boolean(complete[tab]));
    button.setAttribute("aria-label", `${button.textContent.trim()}${complete[tab] ? ", complete" : ""}${tab === activeTab ? ", current view" : ""}`);
  });
  const analysisTabs = workspaceGroups.analysis.filter((tab) => tab !== "reviewer");
  const completedAnalysis = analysisTabs.filter((tab) => complete[tab]).length;
  const analysisStatus = tabs.querySelector('[data-workspace-group-status="analysis"]');
  if (analysisStatus) analysisStatus.textContent = completedAnalysis === analysisTabs.length ? "Complete" : `${completedAnalysis} of ${analysisTabs.length} complete`;
  tabs.querySelector('[data-workspace-group="analysis"]')?.classList.toggle("is-complete", completedAnalysis === analysisTabs.length);
  const reportTabs = workspaceGroups.explore.filter((tab) => !["plot", "assessment"].includes(tab));
  const exploreReady = reportTabs.filter((tab) => complete[tab]).length;
  const exploreStatus = tabs.querySelector('[data-workspace-group-status="explore"]');
  if (exploreStatus) exploreStatus.textContent = exploreReady ? `${exploreReady} of ${reportTabs.length} reports ready` : "Builds from analysis";
  tabs.querySelector('[data-workspace-group="explore"]')?.classList.toggle("has-results", exploreReady > 0);
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
    overlays.push({start: Number(segment.characterStart), type: "emotion", label: `${emotionPresentation[peak.label]?.[0] || signalLabel(peak.label)} peak`, icon: emotionPresentation[peak.label]?.[2] || "●", score: Number(peak.score || 0)});
  });
  (chapter?.tag?.signals || []).filter((signal) => Number(signal.score) > 0).forEach((signal) => {
    (signal.evidence || []).forEach((evidence) => {
      const quote = String(evidence.quote || "").trim();
      if (!quote) return;
      let start = text.indexOf(quote);
      if (start < 0) start = text.toLocaleLowerCase().indexOf(quote.toLocaleLowerCase());
      if (start < 0) return;
      const cluster = tagClusterPresentation.find((item) => item.families.includes(signal.family));
      overlays.push({start, type: "tag", label: signalLabel(signal.id), icon: cluster?.icon || tagFamilyPresentation[signal.family]?.[1] || "◆", score: Number(signal.score || 0)});
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
  const grouped = new Map();
  overlays.forEach((overlay) => grouped.set(overlay.start, [...(grouped.get(overlay.start) || []), overlay]));

  function markedRange(start, end) {
    const relevantRegions = regions.filter((region) => region.end > start && region.start < end);
    const markerPositions = [...grouped.keys()].filter((position) => position >= start && position < end);
    const boundaries = [...new Set([start, end, ...markerPositions, ...relevantRegions.flatMap((region) => [Math.max(start, region.start), Math.min(end, region.end)])])].sort((left, right) => left - right);
    return boundaries.slice(0, -1).map((position, index) => {
      const markers = grouped.get(position) || [];
      const markerMarkup = markers.length ? `<span class="text-signal-markers" contenteditable="false">${markers.map((marker) => {
        const percent = Math.round(marker.score * 100);
        return `<span class="text-signal-marker ${escapeHtml(marker.type)}" data-source-marker-type="${escapeHtml(marker.type)}" data-source-marker-score="${percent}" role="img" aria-label="${escapeHtml(marker.label)} ${percent} percent" title="${escapeHtml(marker.label)} · ${percent}%">${escapeHtml(marker.icon)}</span>`;
      }).join("")}</span>` : "";
      const next = boundaries[index + 1];
      const copy = escapeHtml(text.slice(position, next)).replace(/\n/g, "<br>");
      const region = relevantRegions.find((candidate) => position >= candidate.start && position < candidate.end);
      if (!region) return `${markerMarkup}${copy}`;
      const percent = Math.round(region.score * 100);
      const label = emotionPresentation[region.label]?.[0] || signalLabel(region.label);
      return `${markerMarkup}<span class="emotion-region emotion-${escapeHtml(region.label)}" data-emotion-region-score="${percent}" style="--emotion-region:${escapeHtml(region.color)}" title="${escapeHtml(label)} region · ${percent}%">${copy}</span>`;
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
  const hasEmotions = regions.length || overlays.some((item) => item.type === "emotion");
  const hasTags = overlays.some((item) => item.type === "tag");
  const emotion = sourceAnalysisPreferences.emotion;
  const tag = sourceAnalysisPreferences.tag;
  const controls = `${hasEmotions ? `<details class="source-analysis-setting emotion" data-analysis-settings="emotion"><summary aria-label="Emotion overlay settings"><i aria-hidden="true">●</i><span>Emotions</span></summary><div class="source-analysis-menu"><label class="source-analysis-enabled"><input type="checkbox" data-analysis-enabled${emotion.enabled ? " checked" : ""}> Show emotions</label><label class="source-analysis-enabled neutral"><input type="checkbox" data-analysis-neutral${emotion.neutral ? " checked" : ""}> Include Neutral regions</label><label>Minimum emotion score <output data-analysis-output>${Number(emotion.threshold)}%</output></label><input data-analysis-threshold type="range" min="0" max="100" step="1" value="${Number(emotion.threshold)}"><div class="source-marker-presets"><button type="button" data-analysis-preset="5">Explore 5%</button><button type="button" data-analysis-preset="10">Balanced 10%</button><button type="button" data-analysis-preset="25">Strong 25%</button></div></div></details>` : ""}${hasTags ? `<details class="source-analysis-setting tag" data-analysis-settings="tag"><summary aria-label="Tag overlay settings"><i aria-hidden="true">◆</i><span>Tags</span></summary><div class="source-analysis-menu"><label class="source-analysis-enabled"><input type="checkbox" data-analysis-enabled${tag.enabled ? " checked" : ""}> Show tag evidence</label><label>Minimum tag score <output data-analysis-output>${Number(tag.threshold)}%</output></label><input data-analysis-threshold type="range" min="0" max="100" step="1" value="${Number(tag.threshold)}"><div class="source-marker-presets"><button type="button" data-analysis-preset="25">Trace 25%</button><button type="button" data-analysis-preset="50">Material 50%</button><button type="button" data-analysis-preset="75">Dominant 75%</button></div></div></details>` : ""}`;
  return `<section class="annotated-source-text"><div class="source-overlay-key"><div class="source-analysis-controls" role="group" aria-label="Analysis shown in the manuscript"><strong>Analysis</strong>${controls}</div></div><div class="annotated-source-copy">${markup}</div></section>`;
}

function wireSourceMarkerCutoff(body) {
  const settings = [...body.querySelectorAll("[data-analysis-settings]")];
  if (!settings.length) return;
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
    body.querySelectorAll(".text-signal-markers").forEach((group) => {
      group.hidden = ![...group.querySelectorAll("[data-source-marker-score]")].some((marker) => !marker.hidden);
    });
    body.querySelectorAll("[data-emotion-region-score]").forEach((region) => {
      region.classList.toggle("below-cutoff", Number(region.dataset.emotionRegionScore) < emotion.threshold);
    });
    const copy = body.querySelector(".annotated-source-copy");
    copy?.classList.toggle("show-emotion-regions", emotion.enabled);
    copy?.classList.toggle("hide-neutral-regions", !emotion.neutral);
    saveSourceAnalysisPreferences();
  };
  settings.forEach((setting) => {
    setting.querySelectorAll("input").forEach((input) => input.addEventListener("input", apply));
    setting.querySelectorAll("[data-analysis-preset]").forEach((button) => button.addEventListener("click", () => {
      setting.querySelector("[data-analysis-threshold]").value = button.dataset.analysisPreset;
      apply();
    }));
  });
  apply();
}

async function openChapterSource(bookId, sequence, focus = null, analysisChapter = null) {
  const title = document.querySelector("#chapter-source-title");
  const subtitle = document.querySelector("#chapter-source-subtitle");
  const context = document.querySelector("#chapter-source-context");
  const jumps = document.querySelector("#chapter-source-jumps");
  const body = document.querySelector("#chapter-source-body");
  title.textContent = "Chapter";
  subtitle.textContent = "";
  context.textContent = "Canonical manuscript Markdown";
  jumps.hidden = true;
  jumps.innerHTML = "";
  body.innerHTML = "<p>Loading chapter…</p>";
  showDialog("chapter-source-dialog");
  try {
    const response = await fetch(`/api/books/${encodeURIComponent(bookId)}/chapters/${encodeURIComponent(sequence)}/source`);
    const contentType = response.headers.get("content-type") || "";
    if (!contentType.includes("application/json")) throw new Error("Bookinator’s server needs a restart before it can open saved chapter text. Stop ./bin/serve, run it again, then retry.");
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || "Chapter source unavailable.");
    const chapter = result.chapter;
    title.textContent = displayHeading(chapter.title) || `Section ${sequence}`;
    subtitle.textContent = chapter.chapterTitle ? `${displayHeading(chapter.chapterTitle)} · pages ${chapter.pageStart}–${chapter.pageEnd}` : `pages ${chapter.pageStart}–${chapter.pageEnd}`;
    context.textContent = focus?.kind === "source" ? "Source evidence · Canonical manuscript text" : focus ? "Emotion evidence · Canonical manuscript text" : "Canonical manuscript Markdown · Read only";
    const markers = (chapter.sectionMarkers || []).map(displayHeading).filter(Boolean);
    jumps.innerHTML = markers.length ? `<span>Jump to</span>${markers.map((marker, index) => `<a href="#${escapeHtml(chapterSectionId(index, marker))}" data-chapter-jump="${escapeHtml(chapterSectionId(index, marker))}">${escapeHtml(marker)}</a>`).join("")}` : "";
    jumps.hidden = !markers.length;
    const text = String(chapter.text || chapter.markdown || "");
    const overlays = chapterTextOverlays(analysisChapter, text);
    const regions = emotionTextRegions(analysisChapter, text);
    const focusMarkup = focus?.kind === "source" ? sourcePassageMarkup(chapter, focus) : focus ? emotionPeakSourceMarkup(chapter, focus) : "";
    const overlayMarkup = `${focusMarkup}${focus?.kind === "source" ? "" : (overlays.length || regions.length ? annotatedChapterTextMarkup(text, overlays, regions) : "")}`;
    const formattedMarkup = renderChapterSource(chapter) || "<p>No extracted text was saved for this chapter.</p>";
    body.innerHTML = overlayMarkup || formattedMarkup;
    wireSourceMarkerCutoff(body);
    jumps.querySelectorAll("[data-chapter-jump]").forEach((link) => link.addEventListener("click", (event) => {
      event.preventDefault();
      const target = body.querySelector(`#${CSS.escape(link.dataset.chapterJump)}`);
      target?.scrollIntoView({block: "start", behavior: "smooth"});
      target?.focus({preventScroll: true});
    }));
    if (focus) {
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
  const contents = complete ? `<p>${escapeHtml(chapter.summary)}</p>${analysisSectionMarkup({label: "What this chapter establishes", icon: "✓", tone: "establishes", items: chapter.keyPoints})}${analysisSectionMarkup({label: "Questions now in play", icon: "?", tone: "questions", items: chapter.newQuestions})}` : chapterError ? `<p>This chapter does not have a usable summary. Select <strong>Failed</strong> for the error and attempt history.</p>` : `<p>${chapter.status === "running" ? "This chapter is being read now." : "Haven’t summarized this chapter yet."}</p>`;
  const statusBody = `${chapterError ? `<p class="pipeline-error">${escapeHtml(chapterError)}</p>` : ""}${failureDiagnostics}${provenance}`;
  return analysisDisclosure({status, key, open: isOpen, heading: displayHeading(chapter.title) || `Section ${chapter.number}`, subheading: displayHeading(chapter.chapterTitle), range: sourcePageRange(book, chapter.pageStart, chapter.pageEnd), metrics: chapter, body: contents, statusBody, sourceSequence: chapter.sequence || chapter.number, refreshKind: "summary", refreshId: chapter.sequence || chapter.number});
}

const emotionPresentation = {
  anger: ["Anger", "#c64b43", "⚡"], disgust: ["Disgust", "#748b45", "⊘"], fear: ["Fear", "#7656a8", "△"],
  joy: ["Joy", "#d69a24", "☀"], neutral: ["Neutral", "#7b8798", "○"], sadness: ["Sadness", "#4d78a8", "◇"], surprise: ["Surprise", "#b45b8e", "✦"],
};

const EMOTION_DISTRIBUTION_DISPLAY_THRESHOLD = .05;
const EMOTION_PEAK_DISPLAY_THRESHOLD = .25;

const tagFamilyPresentation = {
  prose_mode: ["Prose mode", "¶"], chapter_function: ["Chapter function", "↗"], reader_dynamics: ["Reader dynamics", "◎"],
  narrated_time: ["Narrated time", "◴"], viewpoint: ["Viewpoint", "◉"], mood: ["Mood", "◒"], genre_affinity: ["Genre affinity", "⌁"], theme_topic: ["Theme topics", "◆"],
};

const tagClusterPresentation = [
  {id: "atmosphere", label: "Atmosphere & meaning", description: "Mood, genre affinity, and thematic concerns", icon: "◆", families: ["mood", "genre_affinity", "theme_topic"]},
  {id: "structure", label: "Structure & perspective", description: "Viewpoint, narrated time, and the chapter’s story function", icon: "◉", families: ["viewpoint", "narrated_time", "chapter_function"]},
  {id: "experience", label: "Experience & momentum", description: "How the prose moves and what it makes the reader track", icon: "↗", families: ["prose_mode", "reader_dynamics"]},
];

function signalLabel(value) {
  return String(value || "").replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
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
      return `<details class="tag-family" data-analysis-key="${escapeHtml(familyKey)}"${openRows.has(familyKey) ? " open" : ""}><summary><h4>${escapeHtml(label)}</h4><span>${escapeHtml(signalLabel(strongest.id))}</span><small>${Math.round(Number(strongest.score) * 100)}%</small></summary><div class="tag-signals">${items.map((signal) => `<article class="tag-signal"><header><strong>${escapeHtml(signalLabel(signal.id))}</strong><span>${Math.round(Number(signal.score) * 100)}%</span><small>${Math.round(Number(signal.confidence) * 100)}% confidence</small></header><p>${escapeHtml(signal.explanation || "")}</p>${signal.evidence?.length ? `<details><summary>Evidence</summary><ul>${signal.evidence.map((item) => `<li>“${escapeHtml(item.quote)}”${item.location ? `<small>${escapeHtml(item.location)}</small>` : ""}</li>`).join("")}</ul></details>` : ""}</article>`).join("")}</div></details>`;
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
      ? {...judgment, issue: evidenceLabel(primary), reason: primary.message || "A local detector flagged this sentence, but the editorial model did not finish reviewing it.", unreviewed: true}
      : judgment;
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
    return `<details class="editorial-finding ${hidden ? "neutral" : "caution"} smell-finding"><summary><span><strong>${escapeHtml(judgment.issue || "Local finding")}</strong><small>${escapeHtml(judgment.reason || "The editorial model did not return a usable judgment.")}</small></span><span>${escapeHtml(sourceVerdict)}${overlap}</span></summary><blockquote>“${escapeHtml(item.sentence || "")}”</blockquote><h5>Why it was flagged</h5><ul>${evidence}</ul><footer><small>Characters ${Number(item.characterStart || 0).toLocaleString()}–${Number(item.characterEnd || 0).toLocaleString()}</small><span class="smell-actions">${disposition}<button class="source-passage-inspect" data-view-source-passage data-chapter-sequence="${Number(chapter.sequence || chapter.number || 0)}" data-character-start="${Number(item.characterStart || 0)}" data-character-end="${Number(item.characterEnd || 0)}" data-passage-sequence="smell" type="button">View sentence</button></span></footer></details>`;
  };
  const visible = candidates.filter(isReported);
  const cards = visible.map((item) => candidateCard(item)).join("");
  const hidden = candidates.length - visible.length;
  const rejectedItems = candidates.filter((item) => !isReported(item));
  const unreviewed = candidates.filter((item) => displayJudgment(item).unreviewed).length;
  const rejected = hidden ? `<details class="editorial-glossary smell-rejected"><summary>Show ${hidden} dismissed, informational, or unreviewed candidates</summary><div class="editorial-findings">${rejectedItems.map((item) => candidateCard(item, true)).join("")}</div></details>` : "";
  const progress = artifact.reviewProgress || {};
  const progressNote = progress.complete === false ? `<p class="pipeline-progress-note">Editorial review: ${Number(progress.completedBatches || 0)} of ${Number(progress.totalBatches || 0)} batches saved.</p>` : "";
  return `${progressNote}<p class="editorial-method-note"><strong>${visible.length} smells kept.</strong> ${Number(artifact.dismissed || 0)} dismissed, ${Math.max(0, Number(artifact.informational || 0) - unreviewed)} informational, and ${unreviewed} awaiting editorial review. Every judgment preserves its local detector evidence.</p>${cards ? `<div class="editorial-findings">${cards}</div>` : progress.complete === false || unreviewed ? "<p>Local findings are ready; editorial judgments are incomplete.</p>" : "<p>No reportable smells survived editorial review.</p>"}${rejected}`;
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
        ? [{label: "Schema", value: artifact.schema || "bookinator-smells-v1", code: true}, {label: "Candidates", value: String(artifact.candidates?.length || 0)}, {label: "Kept", value: String(artifact.kept || 0)}]
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
  const wholeBookFailure = pipeline.wholeBookSummary?.status === "failed" ? 1 : 0;
  return chapterFailures + dossierFailures + wholeBookFailure;
}

function pipelineControl({action = "", label, title, stop = false, disabled = false}) {
  const icon = stop
    ? '<rect x="7" y="7" width="10" height="10" rx="1"/>'
    : ["restart", "dossier-restart", "retry-failed"].includes(action) || label === "Rebuild"
      ? '<path d="M4 11a8 8 0 1 1 2.3 6.1"/><path d="M4 5v6h6"/>'
      : '<path d="m8 5 11 7-11 7Z"/>';
  const attribute = stop ? "data-stop-reading" : `data-pipeline-action="${action}"`;
  return `<button class="pipeline-control-button${stop ? " danger" : ""}" ${attribute} type="button" title="${escapeHtml(title)}"${disabled ? " disabled" : ""}><svg viewBox="0 0 24 24" aria-hidden="true">${icon}</svg><small>${escapeHtml(label)}</small></button>`;
}

function collapseAnalysisControl() {
  return '<button class="pipeline-control-button" data-collapse-analysis type="button" title="Collapse all open disclosures"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="m7 10 5-5 5 5"/><path d="m7 17 5-5 5 5"/></svg><small>Collapse</small></button>';
}

function modelControl(model, task = "reader") {
  const value = String(model || "Automatic selection");
  const colon = value.indexOf(":");
  const label = colon > 0
    ? `<span>${escapeHtml(value.slice(0, colon + 1))}</span><span>${escapeHtml(value.slice(colon + 1))}</span>`
    : `<span>${escapeHtml(value)}</span>`;
  const taskLabel = task === "dossier" ? "dossier model" : task === "tags" ? "chapter tag model" : "chapter reader model";
  return `<button class="model-control-button" data-open-task-model="${task}" type="button" aria-label="Change ${taskLabel}. Current model: ${escapeHtml(value)}" title="Change ${taskLabel}"><svg viewBox="0 0 24 24" aria-hidden="true"><rect x="6" y="6" width="12" height="12" rx="2"/><path d="M9 2v4M15 2v4M9 18v4M15 18v4M2 9h4M2 15h4M18 9h4M18 15h4"/><circle cx="10" cy="10" r="1"/><circle cx="14" cy="14" r="1"/><path d="m11 11 2 2"/></svg><small>${label}</small></button>`;
}

async function openTaskModelDialog(book, pipeline, task = "reader") {
  const dialogId = "reader-model-dialog";
  const select = document.querySelector("#book-reader-model");
  const note = document.querySelector("#reader-model-note");
  const message = document.querySelector("#reader-model-message");
  const nameInput = document.querySelector("#book-reader-model-name");
  const installButton = document.querySelector("#install-book-reader-model");
  const dossier = task === "dossier";
  const tags = task === "tags";
  const taskIsActive = dossier
    ? pipeline.phase === "dossiers" || pipeline.queuedAction === "dossiers"
    : tags ? pipeline.phase === "tags" || ["tags", "tag-restart"].includes(pipeline.queuedAction) : pipeline.phase === "summarizing" || ["summarize", "restart"].includes(pipeline.queuedAction);
  const locked = ["running", "queued"].includes(pipeline.status) && taskIsActive;
  showDialog(dialogId);
  document.querySelector("#reader-model-title").textContent = dossier ? "Choose the dossier model" : tags ? "Choose the chapter tagger" : "Choose the chapter reader";
  document.querySelector(".reader-model-select").childNodes[0].textContent = dossier ? "Dossier model" : tags ? "Chapter tagger" : "Chapter reader";
  document.querySelector("#reader-model-description").textContent = `${book.title} can use its own model for ${dossier ? "chunk dossiers" : tags ? "evidence-bearing chapter tags" : "chapter summaries"} without changing workspace defaults.`;
  message.textContent = "Loading installed models…";

  const refreshChoices = async (preferred = (dossier ? pipeline.dossierModelOverride : tags ? pipeline.tagModelOverride : pipeline.readerModelOverride) || "") => {
    const response = await fetch("/api/system");
    const system = await response.json();
    const installed = system.ollama?.models || [];
    const workspaceDefault = dossier ? (pipeline.workspaceDossierModel || system.models?.roles?.primary) : tags ? (pipeline.workspaceTagModel || system.models?.roles?.tags || system.models?.roles?.reader) : system.models?.roles?.reader;
    select.innerHTML = `<option value="">Use workspace default · ${escapeHtml(workspaceDefault)}</option>${installed.map((model) => `<option value="${escapeHtml(model)}">${escapeHtml(model)}</option>`).join("")}`;
    select.value = installed.includes(preferred) ? preferred : "";
    select.disabled = locked;
    installButton.disabled = locked;
    note.textContent = locked ? "Stop this book’s pipeline before changing its model." : select.value ? "This model overrides the workspace default for this book only." : `This book currently follows the workspace ${dossier ? "primary-model" : tags ? "chapter-tagger" : "chapter-reader"} default.`;
    message.textContent = system.ollama?.running ? "" : "Ollama must be running to choose or install a reader.";
    return system;
  };

  const assign = async (model) => {
    const response = await fetch(`/api/books/${encodeURIComponent(book.id)}/${task}-model`, {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({model})});
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || "Could not change this book’s chapter reader.");
    pipeline[dossier ? "dossierModelOverride" : tags ? "tagModelOverride" : "readerModelOverride"] = result.model;
    pipeline[dossier ? "configuredDossierModel" : tags ? "configuredTagModel" : "configuredReaderModel"] = result.effectiveModel;
    note.textContent = result.model ? "This model overrides the workspace default for this book only." : "This book now follows the workspace chapter-reader default.";
    message.textContent = result.model ? `${result.model} will build ${dossier ? "chunk dossiers" : tags ? "chapter tags" : "chapter summaries"} for this book.` : "Workspace default restored for this book.";
    state.pipelineSignature = "";
    showBookPage(book.id, document.querySelector("#book-page").dataset.activeTab || "summaries");
    const hasResults = dossier ? pipeline.chunks?.some((chunk) => chunk.dossierStatus === "complete") : tags ? pipeline.chapters?.some((chapter) => chapter.tagStatus === "complete") : pipeline.chapters?.some((chapter) => chapter.status === "complete");
    if (hasResults) {
      const rerun = await confirmAction({context: dossier ? "New dossier model" : tags ? "New tag model" : "New chapter reader", title: dossier ? "Rebuild unfinished dossiers?" : tags ? "Retag this book?" : "Re-summarize this book?", message: `${result.effectiveModel || "The workspace model"} is now assigned to this task. Existing results remain intact.`, acceptLabel: dossier ? "Continue dossiers" : tags ? "Retag book" : "Re-summarize book"});
      if (rerun) {
        closeDialog(dialogId);
        await fetch("/api/library/pipeline/prioritize", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({bookId: book.id, action: dossier ? "dossiers" : tags ? "tag-restart" : "restart"})});
        state.pipelineSignature = "";
        showBookPage(book.id, dossier ? "dossiers" : tags ? "tags" : "summaries");
      }
    }
  };

  await refreshChoices();
  select.onchange = async () => {
    select.disabled = true;
    try { await assign(select.value); }
    catch (error) { message.textContent = error.message; }
    finally { select.disabled = locked; }
  };
  installButton.onclick = async () => {
    const model = nameInput.value.trim();
    if (!model) return nameInput.focus();
    installButton.disabled = true;
    installButton.textContent = "Installing…";
    message.textContent = "Ollama is downloading the model. Large readers can take a while.";
    try {
      const pullResponse = await fetch("/api/models/pull", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({model})});
      const pulled = await pullResponse.json();
      if (!pullResponse.ok) throw new Error(pulled.error || "Ollama could not install that model.");
      await refreshChoices(pulled.model);
      await assign(pulled.model);
      nameInput.value = "";
    } catch (error) {
      message.textContent = error.message;
    } finally {
      installButton.disabled = locked;
      installButton.textContent = "Install & use";
    }
  };
}

const workspaceIcons = {
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
  reviewer: '<path d="M5 4h11v16H5z"/><path d="M8 8h5M8 12h4"/><path d="m13 17 6.5-6.5 2 2L15 19h-2v-2Z"/>',
  assessment: '<path d="M4 19V9M10 19V5M16 19v-7M22 19V3"/><path d="M2 19h22"/><path d="m4 7 6-4 6 7 6-9"/>',
};

const workspaceTabs = [
  {id: "pipeline", label: "Pipeline"},
  {id: "chapters", label: "Chapters"},
  {id: "summaries", label: "Summaries"},
  {id: "dossiers", label: "Dossiers"},
  {id: "emotions", label: "Emotions"},
  {id: "tags", label: "Tags"},
  {id: "smells", label: "Smells"},
  {id: "inferences", label: "Inferences"},
  {id: "report", label: "PDF report"},
  {id: "overview", label: "Book summary"},
  {id: "smell-report", label: "Smells"},
  {id: "emotion-map", label: "Emotion map"},
  {id: "connections", label: "Connections"},
  {id: "questions", label: "Questions & payoffs"},
  {id: "plot", label: "Plot arcs"},
  {id: "reviewer", label: "Reviewer"},
  {id: "assessment", label: "Assessment"},
];

const workspaceGroups = {
  analysis: ["pipeline", "chapters", "summaries", "dossiers", "emotions", "tags", "smells", "inferences", "reviewer"],
  explore: ["report", "overview", "emotion-map", "connections", "questions", "plot", "smell-report", "assessment"],
};

const workspaceShelfEndTabs = new Set(["reviewer", "assessment"]);

function workspaceGroupForTab(tab) {
  return Object.entries(workspaceGroups).find(([, tabs]) => tabs.includes(tab))?.[0] || "";
}

function workspaceTabButton(tab, activeTab) {
  const icon = workspaceIcons[tab.id] || workspaceIcons[tab.id === "smell-report" ? "smells" : tab.id === "emotion-map" ? "emotions" : "overview"];
  return `<button type="button" class="book-tool-button${tab.id === "report" ? " shelf-lead-action" : ""}" data-book-tab="${tab.id}"${activeTab === tab.id ? ' aria-current="page"' : ""}><span class="book-tool-icon" aria-hidden="true"><svg viewBox="0 0 24 24">${icon}</svg></span><small>${escapeHtml(tab.label)}</small></button>`;
}

function navigateWorkspaceTab(bookId, tab, inference = "") {
  const suffix = inference ? `/${inference}` : "";
  history.pushState(null, "", `#book/${bookId}/${tab}${suffix}`);
  const cachedPipeline = state.workspacePipeline?.bookId === bookId ? state.workspacePipeline.pipeline : null;
  showBookPage(bookId, tab, inference, cachedPipeline);
}

function renderWorkspaceNavigation(container, book, activeTab) {
  const activeGroup = workspaceGroupForTab(activeTab);
  const groupMarkup = (group, label, icon) => `<button type="button" class="book-tool-button workspace-group-button${activeGroup === group ? " is-active" : ""}" data-workspace-group="${group}" aria-expanded="${activeGroup === group && !workspaceGroupState(book.id, group).collapsed}" title="${label} workspace"><span class="book-tool-icon" aria-hidden="true"><svg viewBox="0 0 24 24">${workspaceIcons[icon]}</svg></span><span class="workspace-group-copy"><small>${label}</small><span class="workspace-group-status" data-workspace-group-status="${group}">${group === "analysis" ? "Analysis tools" : "Linked reports"}</span></span><span class="workspace-group-chevron" aria-hidden="true">⌄</span></button>`;
  const shelf = activeGroup && !workspaceGroupState(book.id, activeGroup).collapsed
    ? `<div class="book-workspace-shelf" data-workspace-shelf="${activeGroup}" aria-label="${activeGroup === "analysis" ? "Analysis" : "Explore"} tools">${workspaceGroups[activeGroup].map((id) => `${workspaceShelfEndTabs.has(id) ? '<span class="workspace-shelf-spacer" aria-hidden="true"></span>' : ""}${workspaceTabButton(workspaceTabs.find((tab) => tab.id === id), activeTab)}`).join("")}</div>`
    : "";
  container.innerHTML = `<div class="book-workspace-primary"><button type="button" class="book-tool-button book-bar-action" data-edit-identity title="Edit book identity"><span class="book-tool-icon" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="M4 16.5V20h3.5L18 9.5 14.5 6 4 16.5Z"/><path d="m13 7.5 3.5 3.5"/></svg></span><small>Identity</small></button>${groupMarkup("analysis", "Analysis", "pipeline")}${groupMarkup("explore", "Explore", "connections")}<span class="workspace-primary-spacer" aria-hidden="true"></span></div>${shelf}`;
  container.querySelector("[data-edit-identity]")?.addEventListener("click", () => openExistingBook(book.id));
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
    const destination = workspaceGroups[group].includes(remembered) ? remembered : workspaceGroups[group][0];
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
  const presentActivity = (activity) => activity?.phase === "questions"
    ? {...activity, task: "Questions & payoffs", item: "Whole-book reconciliation", text: `Bookinator · ${activity.model || "the local model"} is matching questions to payoffs in ${activity.book || "this book"}`}
    : activity;
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
  const statusCopy = progress.etaLabel || (status === "complete" ? "Complete" : status === "paused" ? "Paused; resume whenever you are ready." : formatEta(progress.etaSeconds));
  const basisCopy = progress.basisLabel || (progress.etaSampleSize ? `${progress.etaSampleSize} recent items used for the estimate` : "");
  return progressPanel({label, completed: progress.completed, total: progress.total, unit, percent: progress.percent, statusCopy, basisCopy, activity: activity || resolvedActivity()});
}

function progressPanel({label, completed = 0, total = 0, unit = "items", percent = 0, statusCopy = "", basisCopy = "", activity = null, fallbackActivity = "Bookinator is checking the global queue", className = ""}) {
  const completeText = `${Number(completed).toLocaleString()} of ${Number(total).toLocaleString()} ${unit} complete`;
  const safePercent = Math.max(0, Math.min(100, Number(percent) || 0));
  return `<section class="overall-progress${className ? ` ${escapeHtml(className)}` : ""}"><header><strong>${escapeHtml(label)}</strong><span>${escapeHtml(completeText)}</span></header><div class="progress-track" role="progressbar" aria-label="${escapeHtml(label)}" aria-valuemin="0" aria-valuemax="${Number(total) || 0}" aria-valuenow="${Number(completed) || 0}"><span style="width:${safePercent}%"></span></div><footer><p><strong>${safePercent}%</strong> ${escapeHtml(statusCopy)}${basisCopy ? `<small>${escapeHtml(basisCopy)}</small>` : ""}</p>${progressActivity(activity || resolvedActivity(), fallbackActivity)}</footer></section>`;
}

function taskHeadingActions({model = "", role = "", action = "", extra = ""}) {
  return `<div class="workspace-heading-actions">${model && role ? modelControl(model, role) : ""}${action}${extra}</div>`;
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

function jpegPagesPdf(pages) {
  const encoder = new TextEncoder();
  const chunks = [];
  const offsets = [0];
  let length = 0;
  const append = (value) => { const bytes = typeof value === "string" ? encoder.encode(value) : value; chunks.push(bytes); length += bytes.length; };
  append("%PDF-1.4\n%\xE2\xE3\xCF\xD3\n");
  const objectCount = 2 + pages.length * 3;
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
  const xref = length;
  append(`xref\n0 ${objectCount + 1}\n0000000000 65535 f \n`);
  for (let id = 1; id <= objectCount; id += 1) append(`${String(offsets[id]).padStart(10, "0")} 00000 n \n`);
  append(`trailer\n<< /Size ${objectCount + 1} /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF`);
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
  return jpegPagesPdf(pages);
}

async function editorReportPdf(pipeline, book, {only = ""} = {}) {
  const width = 1224, height = 1584, renderScale = .75, pixelWidth = Math.round(width * renderScale), pixelHeight = Math.round(height * renderScale), margin = 76, contentWidth = width - margin * 2, contentBottom = height - 142;
  const canvases = [], pageMeta = [], sectionStarts = [];
  const logo = new Image();
  const logoReady = new Promise((resolve) => { logo.onload = resolve; logo.onerror = resolve; });
  logo.src = "/assets/bookinator.svg";
  const bookImage = new Image();
  const bookImageReady = new Promise((resolve) => { bookImage.onload = resolve; bookImage.onerror = resolve; });
  if (book.icon?.kind === "image") bookImage.src = book.icon.value;
  await Promise.all([logoReady, book.icon?.kind === "image" ? bookImageReady : Promise.resolve()]);
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
  const section = (key, title, render) => {
    if (only && only !== key) return;
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
    context.fillStyle = "#65778e"; context.font = "16px Arial, sans-serif"; context.fillText(`Generated ${new Date().toLocaleString()}`, margin, 700);
    tocCanvas = newPage("Table of contents");
  }

  section("status", "Analysis status", () => {
    const availableStages = (pipeline.stages || []).filter((stage) => !/^prose$/i.test(String(stage.id || "")) && !/^prose$/i.test(String(stage.label || "")));
    heading("What was available at export", 1); y += 18;
    paragraph("Check this page before reading the report. Red markers identify analyses that were incomplete when this PDF was created, so their later sections may be partial.", {font: "17px Arial, sans-serif", color: "#526984", lineHeight: 27, after: 18});
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

  section("tags", "Chapter tags", () => {
    const taggedChapters = (pipeline.chapters || []).filter((chapter) => chapter.tag?.signals?.length);
    heading(`${taggedChapters.length} tagged ${taggedChapters.length === 1 ? "chapter" : "chapters"}`, 1);
    paragraph("Fixed-vocabulary editorial signals at 25% or higher.", {font: "16px Arial, sans-serif", color: "#60728a"});
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

  section("smell-report", "Undismissed Smells", () => {
    const smells = reportableSmells(pipeline);
    heading("Undismissed Smells", 1);
    paragraph(`${smells.length.toLocaleString()} editorial ${smells.length === 1 ? "finding remains" : "findings remain"} in the manuscript.`, {font: "700 19px Arial, sans-serif", color: "#9c493f", lineHeight: 28, after: 22});
    smells.forEach(({chapter, item}) => {
      ensure(156);
      context.fillStyle = "#fff7f4"; context.beginPath(); context.roundRect(margin, y - 12, contentWidth, 22, 8); context.fill();
      context.fillStyle = "#9c493f"; context.font = "800 13px Arial, sans-serif"; context.fillText(displayHeading(chapter.title) || `Chapter ${chapter.number || chapter.sequence}`, margin + 18, y + 5); y += 38;
      heading(item.judgment?.issue || "Possible prose smell", 3);
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
  return jpegPagesPdf(pages);
}

function csvCell(value) {
  return `"${String(value ?? "").replaceAll('"', '""')}"`;
}

function installChartExports({dialog, chart, rows, filename, book, analysisLabel, timingLabel}) {
  dialog.querySelectorAll("[data-chart-export]").forEach((button) => button.addEventListener("click", async () => {
    const format = button.dataset.chartExport;
    const svg = chart.querySelector("svg");
    if (!svg) return;
    const serialized = exportableSvg(svg);
    const branded = ["svg", "png"].includes(format) ? await brandedChartSvg(serialized, svg.viewBox.baseVal.width, svg.viewBox.baseVal.height, {book, analysisLabel, timingLabel}) : null;
    if (format === "svg") downloadFile(branded, `${filename}.svg`, "image/svg+xml;charset=utf-8");
    if (format === "csv") {
      const csv = [`${csvCell("Chapter")},${csvCell("Elapsed seconds")},${csvCell("Elapsed time")}`, ...rows.map((row) => `${csvCell([row.label, row.title].filter(Boolean).join(" · "))},${csvCell(row.seconds)},${csvCell(formatRunDuration(row.seconds))}`)].join("\n");
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

function timingChartRows(pipeline, view) {
  const chapters = pipeline.chapters || [];
  const chapterIdentity = (chapter) => {
    const heading = displayHeading(chapter.title || `Chapter ${chapter.sequence || chapter.number}`).replace(/^chapter\b/i, "Chapter");
    const title = displayHeading(chapter.chapterTitle || "");
    return {label: heading, title, tooltip: title ? `${heading}: ${title}` : heading};
  };
  const durationField = {summaries: "durationSeconds", emotions: "emotionDurationSeconds", tags: "tagDurationSeconds", smells: "smellDurationSeconds"}[view];
  if (durationField) {
    const rows = chapters.map((chapter) => ({...chapterIdentity(chapter), seconds: Number(chapter[durationField] || 0), sequence: Number(chapter.sequence || chapter.number || 0)})).filter((item) => item.seconds > 0);
    const rollup = view === "summaries" ? pipeline.wholeBookSummary : null;
    if (Number(rollup?.durationSeconds || 0) > 0) rows.push({label: "Summary", title: "Whole book", tooltip: "Whole-book summary", seconds: Number(rollup.durationSeconds)});
    return rows;
  }
  if (view === "chapters") {
    const seconds = (pipeline.stages || []).filter((stage) => ["extraction", "structure", "chapter-archive", "chunking"].includes(stage.id)).reduce((sum, stage) => sum + Number(stage.durationSeconds || 0), 0);
    return [{label: "Chapter Map", title: "Preparation", tooltip: seconds ? "Chapter-map preparation" : "No saved timing data", seconds}];
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
  if (view === "pipeline") {
    const definitions = [
      ["Summaries", "durationSeconds", "chapters"],
      ["Dossiers", "dossierDurationSeconds", "chunks"], ["Emotions", "emotionDurationSeconds", "chapters"],
      ["Tags", "tagDurationSeconds", "chapters"], ["Smells", "smellDurationSeconds", "chapters"],
    ];
    const chapterPreparation = (pipeline.stages || []).filter((stage) => ["extraction", "structure", "chapter-archive", "chunking"].includes(stage.id)).reduce((sum, stage) => sum + Number(stage.durationSeconds || 0), 0);
    const measured = definitions.map(([label, field, collection]) => ({label, seconds: (pipeline[collection] || []).reduce((sum, item) => sum + Number(item[field] || 0), 0)})).filter((item) => item.seconds > 0);
    return [{label: "Chapter Map", tooltip: chapterPreparation ? "Chapter-map preparation" : "No saved timing data", seconds: chapterPreparation}, ...measured];
  }
  return [];
}

function openTimingChart(pipeline, view) {
  const rows = timingChartRows(pipeline, view);
  if (!rows.length) return confirmAction({context: "Run timing", title: "No saved timing yet", message: "This view does not have a completed timed result to chart yet.", acceptLabel: "Close"});
  const dialogId = "timing-chart-dialog";
  const titleId = "timing-chart-title";
  const analysisLabel = view === "pipeline" ? "Pipeline" : workspaceTabs.find((tab) => tab.id === view)?.label || signalLabel(view);
  const timingLabel = view === "pipeline" ? "Timing by step" : "Timing by chapter";
  const book = state.books.find((item) => item.id === state.currentBookId) || {title: "Bookinator manuscript", author: ""};
  const overlay = mountStandardDialog({
    id: dialogId,
    className: "timing-chart-dialog",
    labelledBy: titleId,
    content: `<header class="dialog-heading"><div class="timing-book-identity"><span class="timing-book-icon" data-timing-book-icon></span><span><strong id="${titleId}">${escapeHtml(book.title)}</strong><small>${escapeHtml(book.author || "Author not specified")}</small></span></div><div class="timing-report-identity"><strong>${escapeHtml(analysisLabel)}</strong><small>${escapeHtml(timingLabel)}</small></div></header><div class="timing-chart-toolbar" data-no-dialog-drag><p>Hover for exact elapsed time; select a point to inspect its chapter.</p><div class="timing-chart-header-actions"><button class="pipeline-control-button" type="button" data-timing-zero aria-pressed="true" title="Start the elapsed-time axis at zero"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 4v15h15"/><path d="M8 16h.01M8 12h.01M8 8h.01"/></svg><small>Zero</small></button><button class="pipeline-control-button" type="button" data-fit-chart title="Fit the whole chart to the available area"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M8 3H3v5M16 3h5v5M8 21H3v-5M16 21h5v-5"/><path d="m3 8 5-5M21 8l-5-5M3 16l5 5M21 16l-5 5"/></svg><small>Fit</small></button>${chartExportControl()}</div></div><div class="timing-chart-scroll" data-timing-chart></div><div class="timing-tooltip" role="status" hidden></div>`,
  });
  renderIcon(overlay.querySelector("[data-timing-book-icon]"), book.icon, book.title);
  const chart = overlay.querySelector("[data-timing-chart]");
  const tooltip = overlay.querySelector(".timing-tooltip");
  const render = () => {
    const width = 860, labelWidth = 285, right = 28, top = 42, rowHeight = 66, bottom = 62, height = top + Math.max(1, rows.length - 1) * rowHeight + bottom;
    const maximum = Math.max(...rows.map((item) => item.seconds), 1);
    const observedMinimum = Math.min(...rows.map((item) => item.seconds));
    const startAtZero = overlay.querySelector("[data-timing-zero]").getAttribute("aria-pressed") === "true";
    const observedSpan = Math.max(1, maximum - observedMinimum);
    const minimum = startAtZero ? 0 : Math.max(0, observedMinimum - Math.max(5, observedSpan * .18));
    const domain = Math.max(1, maximum - minimum);
    const x = (seconds) => labelWidth + ((seconds - minimum) / domain) * (width - labelWidth - right);
    const y = (index) => top + index * rowHeight;
    const points = rows.map((item, index) => `${x(item.seconds)},${y(index)}`).join(" ");
    const ticks = Array.from({length: 5}, (_, index) => minimum + domain * index / 4);
    const plotBottom = y(rows.length - 1);
    const grid = ticks.map((value) => `<line x1="${x(value)}" x2="${x(value)}" y1="${top}" y2="${plotBottom}" class="timing-grid"/><text x="${x(value)}" y="${plotBottom + 30}" text-anchor="middle">${escapeHtml(formatRunDuration(value))}</text>`).join("");
    const nodes = rows.map((item, index) => {
      const target = item.sequence ? ` data-timing-sequence="${item.sequence}"` : "";
      const titleLines = wrapChartTitle(item.title);
      const titleMarkup = titleLines.map((line) => `<tspan class="timing-label-title" x="${labelWidth - 18}" dy="15">${escapeHtml(line)}</tspan>`).join("");
      return `<text class="timing-label" x="${labelWidth - 18}" y="${y(index) - (titleLines.length > 1 ? 15 : titleLines.length ? 7 : -4)}" text-anchor="end"><tspan>${escapeHtml(item.label)}</tspan>${titleMarkup}</text><line x1="${labelWidth}" x2="${width - right}" y1="${y(index)}" y2="${y(index)}" class="timing-row-guide"/><circle cx="${x(item.seconds)}" cy="${y(index)}" r="7" tabindex="0" role="button" data-timing-point data-timing-title="${escapeHtml(item.tooltip || item.label)}" data-timing-elapsed="${escapeHtml(formatRunDuration(item.seconds))}"${target}/>`;
    }).join("");
    chart.innerHTML = `<svg viewBox="0 0 ${width} ${height}" style="width:${width}px;height:${height}px" aria-label="Elapsed time by ${view === "pipeline" ? "pipeline step" : "chapter"}">${grid}<line x1="${labelWidth}" x2="${width - right}" y1="${plotBottom}" y2="${plotBottom}" class="timing-axis"/><text class="timing-axis-title" x="${labelWidth + (width - labelWidth - right) / 2}" y="${height - 4}" text-anchor="middle">Elapsed time</text><polyline points="${points}" class="timing-line"/>${nodes}</svg>`;
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
  new ResizeObserver(fitChart).observe(overlay.querySelector(".timing-chart-dialog"));
  installChartExports({dialog: overlay, chart, rows, filename: `bookinator-${view}-timing`, book, analysisLabel, timingLabel});
}

function workspaceTaskView({icon, title, subtitle, actions = "", metrics = "", explanationTitle, explanation, collapse = true, activity = "", error = "", progress = "", content = ""}) {
  return `${workspaceSectionHeading({icon, title, subtitle, actions, metrics, explanationTitle, explanation, collapse})}${activity}${error ? `<p class="pipeline-error">${error}</p>` : ""}${progress}${content}`;
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

async function requireChapterMapApi(requiredFeature = "chapterMapApproval") {
  const restartMessage = "Bookinator’s local server is older than this page. Stop ./bin/serve in Terminal, run ./bin/serve again, then press Approve.";
  let response;
  try {
    response = await fetch("/api/health", {cache: "no-store"});
  } catch {
    throw new Error("Bookinator’s local server is not reachable. Start ./bin/serve, then try again.");
  }
  const contentType = response.headers.get("content-type") || "";
  if (!response.ok || !contentType.includes("application/json")) throw new Error(restartMessage);
  const health = await response.json();
  if (Number(health?.features?.[requiredFeature] || 0) < 1) throw new Error(restartMessage);
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

function chapterHeadingInspectionMarkup(pipeline) {
  const report = pipeline.chapterHeadingReport || {};
  const topLevel = report.topLevel?.length
    ? report.topLevel
    : (pipeline.chapters || []).filter((chapter) => displayHeading(chapter.title).toLowerCase() !== "front matter").map((chapter) => ({label: displayHeading(chapter.title), page: chapter.pageStart}));
  if (!topLevel.length) return "";
  const candidates = report.otherCandidates || [];
  const candidateRows = candidates.length
    ? candidates.map((candidate) => {
        const pages = (candidate.pages || []).join(", ");
        const unique = Number(candidate.count || 0) === 1;
        const demotedPages = candidate.demotedPages || [];
        if (demotedPages.length) {
          const restoreButtons = demotedPages.map((page) => `<button class="heading-restore" data-restore-chapter-page="${Number(page)}" type="button">Restore chapter</button>`).join("");
          return `<div class="heading-candidate demoted"><span><strong>${escapeHtml(displayHeading(candidate.label))}</strong><small>${escapeHtml(`page ${pages} · excluded by the editor and folded into the preceding chapter`)}</small></span>${restoreButtons}</div>`;
        }
        const note = unique ? `page ${pages} · excluded opening heading` : `pages ${pages} · appears ${candidate.count} times, probably a section or viewpoint marker`;
        return `<label class="heading-candidate${candidate.accepted ? " accepted" : ""}${unique ? "" : " repeated"}"><input type="checkbox" data-chapter-variant value="${escapeHtml(candidate.label)}"${candidate.accepted ? " checked" : ""}${unique ? "" : " disabled"}><span><strong>${escapeHtml(displayHeading(candidate.label))}</strong><small>${escapeHtml(note)}</small></span></label>`;
      }).join("")
    : '<p class="heading-family-empty">No other page-opening headings competed with the chapter pattern.</p>';
  const promotable = candidates.some((candidate) => Number(candidate.count || 0) === 1 && !(candidate.demotedPages || []).length);
  const excluded = (pipeline.chapterHeadingReport?.otherCandidates || []).filter((candidate) => !(candidate.accepted || (candidate.demotedPages || []).length));
  const warnings = pipeline.chapterMapWarnings || [];
  const tone = warnings.length ? "review" : pipeline.chapterMapApproved ? "approved" : "ready";
  const title = warnings.length
    ? `${warnings.length} structural ${warnings.length === 1 ? "question needs" : "questions need"} a decision.`
    : `${topLevel.length} ${pipeline.chapterMapApproved ? "approved" : "proposed"} ${topLevel.length === 1 ? "chapter follows" : "chapters follow"} the established manuscript pattern.`;
  const detail = warnings.length
    ? "Compare the green chapter family with the amber opening headings before approval."
    : `${excluded.length} other opening ${excluded.length === 1 ? "heading is" : "headings are"} being treated as section or viewpoint markers.`;
  const comparison = `<div class="chapter-heading-comparison"><section class="heading-family accepted-family"><h3>Established chapter pattern</h3><p>These headings define the current authored sequence.</p><ol>${topLevel.map((item) => `<li><strong>${escapeHtml(displayHeading(item.label))}</strong><span>page ${Number(item.page).toLocaleString()}</span></li>`).join("")}</ol></section><form class="heading-family candidate-family"><h3>Other opening headings</h3><p>Amber headings were excluded. Promote a unique legitimate variant, or restore a boundary you excluded earlier. Repeated labels remain section markers.</p><div class="heading-candidates">${candidateRows}</div>${promotable ? '<button class="secondary-button" data-apply-chapter-variants type="submit">Apply variants & rebuild</button>' : ""}</form></div>`;
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

function paginationKind(book) {
  const format = String(book?.sourceFormat || "").toUpperCase();
  const filename = String(book?.sourceFilename || "").toLowerCase();
  return format === "PDF" || (!format && filename.endsWith(".pdf")) ? "original" : "generated";
}

function sourcePageRange(book, start, end) {
  return `${paginationKind(book)} pages ${Number(start || 0).toLocaleString()}–${Number(end || start || 0).toLocaleString()}`;
}

function sourcePageCount(book, count) {
  return `${Number(count || 0).toLocaleString()} ${paginationKind(book)} ${Number(count || 0) === 1 ? "page" : "pages"}`;
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
  const definitions = {
    chapters: {
      label: "Map",
      subtitle: "Organized",
      status: pipeline.chapterMapSuspicious ? "review" : pipeline.chapterMapApproved ? "complete" : "ready",
      statusLabel: pipeline.chapterMapSuspicious ? "Review" : pipeline.chapterMapApproved ? "Approved" : "Proposed",
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
  };
  const definition = definitions[kind] || definitions.summaries;
  const rollup = kind === "summaries" ? pipeline.wholeBookSummary || {} : kind === "dossiers" ? pipeline.wholeBookDossier || {} : {};
  const result = rollup.summary || rollup.synopsis || rollup.content || "";
  const status = result ? "complete" : definition.status;
  const statusLabel = definition.statusLabel || (status === "blocked" ? "Waiting" : status === "ready" ? "Ready" : status);
  const rollupInputs = kind === "summaries"
    ? (pipeline.chapters || []).filter((chapter) => chapter.status === "complete" && displayHeading(chapter.title).toLocaleLowerCase() !== "front matter")
      .map((chapter) => ({summary: chapter.summary, keyPoints: chapter.keyPoints, newQuestions: chapter.newQuestions}))
    : kind === "dossiers"
      ? (pipeline.chunks || []).filter((chunk) => chunk.dossierStatus === "complete" && chunk.dossier)
        .map((chunk) => chunk.dossier)
      : [];
  const inputCharacters = Number(rollup.inputCharacters || JSON.stringify(rollupInputs).length || 0);
  const model = rollup.model || (kind === "dossiers" ? pipeline.configuredDossierModel : pipeline.configuredReaderModel);
  const inputLabel = kind === "dossiers"
    ? `${rollupInputs.length.toLocaleString()} current chunk ${rollupInputs.length === 1 ? "dossier" : "dossiers"}`
    : `${rollupInputs.length.toLocaleString()} current chapter ${rollupInputs.length === 1 ? "summary" : "summaries"}`;
  const dependencyLabel = kind === "dossiers" ? "Every source-chunk dossier" : "Every required chapter analysis";
  const stats = sourceMetricsMarkup(metrics, sourcePageCount(book, metrics.pageCount), {className: "analysis-source-stats whole-book-source-stats"});
  const body = kind === "chapters"
    ? chapterHeadingInspectionMarkup(pipeline)
    : result
    ? `<div class="chapter-editorial-content"><p>${escapeHtml(result)}</p>${kind === "summaries" ? `${analysisSectionMarkup({label: "What this book establishes", icon: "✓", tone: "establishes", items: rollup.keyPoints})}${analysisSectionMarkup({label: "Questions resolved", icon: "✓", tone: "facts", items: rollup.resolvedQuestions})}${analysisSectionMarkup({label: "Questions still in play", icon: "?", tone: "questions", items: rollup.openQuestions})}` : ""}</div>`
    : `<div class="whole-book-empty"><strong>${status === "ready" ? "Ready for whole-book synthesis." : kind === "chapters" ? "The manuscript scope is established." : "This rollup comes after its chapter-level work."}</strong><p>${escapeHtml(rollup.detail || definition.body)}</p></div>`;
  const identity = `<span class="whole-book-mark" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="M5 4.5c2.7-.7 5-.2 7 1.5 2-1.7 4.3-2.2 7-1.5v14c-2.7-.7-5-.2-7 1.5-2-1.7-4.3-2.2-7-1.5z"/><path d="M12 6v14"/><path class="whole-book-star" d="m17.4 7 .5 1.1 1.1.5-1.1.5-.5 1.1-.5-1.1-1.1-.5 1.1-.5z"/></svg></span><span class="chapter-heading"><span class="chapter-title-line"><span>${escapeHtml(definition.label)}</span><small>Whole book</small></span><strong>${escapeHtml(definition.subtitle)}</strong></span>`;
  const inspectable = kind === "summaries" || kind === "dossiers";
  const reporting = inspectable
    ? `<button class="whole-book-status" data-show-reading-details type="button" title="Show status, model, inputs, and timing">${escapeHtml(statusLabel)}</button>`
    : `<span class="whole-book-status">${escapeHtml(statusLabel)}</span>`;
  const details = inspectable
    ? `<template class="analysis-details-template">${rollup.error ? `<p class="pipeline-error">${escapeHtml(rollup.error)}</p>` : ""}${analysisRunDetails({title: `${definition.label} · whole book`, model, startedAt: rollup.startedAt, completedAt: rollup.completedAt, duration: rollup.durationSeconds, status, inputCharacters, rows: [{label: "State", value: statusLabel}, {label: "Inputs", value: inputLabel}, {label: "Depends on", value: dependencyLabel}]})}</template>`
    : "";
  const refreshableSummary = kind === "summaries" && ["running", "failed", "complete"].includes(status);
  return `<details class="analysis-row chapter-summary whole-book-analysis ${escapeHtml(status)}" data-analysis-key="whole-book-${escapeHtml(kind)}" data-analysis-heading="${escapeHtml(definition.label)}" data-analysis-subheading="${escapeHtml(definition.subtitle)}" data-analysis-status="${escapeHtml(status)}" data-refresh-kind="${refreshableSummary ? "whole-summary" : ""}" data-refresh-id="${refreshableSummary ? "all" : ""}"><summary class="analysis-row-columns">${analysisRowColumns({identity, metadata: stats, reporting})}</summary><div class="chapter-summary-body">${body}</div>${details}</details>`;
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
  const mapStatus = frontMatter ? "Excluded" : needsReview ? "Review" : pipeline.chapterMapApproved ? "Approved" : "Proposed";
  const mapStatusTone = frontMatter ? "neutral" : needsReview ? "review" : pipeline.chapterMapApproved ? "approved" : "proposed";
  const correction = !frontMatter && Number(chapter.pageStart) !== firstAuthoredPage
    ? `<button class="chapter-map-correction" data-demote-chapter data-chapter-page="${Number(chapter.pageStart)}" data-chapter-title="${escapeHtml(title)}" type="button" title="Review whether this heading should be folded into the preceding chapter">Not a chapter…</button>`
    : "";
  const identity = `<span class="chapter-map-sequence">${Number(chapter.sequence || chapter.number || 0).toLocaleString()}</span><span class="chapter-map-title"><strong>${escapeHtml(title)}</strong>${subtitle ? `<small>${escapeHtml(subtitle)}</small>` : ""}<span class="chapter-map-verification"><span class="chapter-validation ${validationTone}"><i>${frontMatter ? "·" : needsReview ? "!" : "✓"}</i>${escapeHtml(validation)}</span>${correction}</span></span>`;
  const reporting = `<span class="chapter-map-status ${mapStatusTone}">${escapeHtml(mapStatus)}</span>`;
  return `<article class="chapter-map-row analysis-row-columns ${validationTone}">${analysisRowColumns({identity, metadata: chapterSourceMetadata(chapter.sequence || chapter.number, title, stats), reporting})}</article>`;
}

function analysisDisclosure({className = "", status = "pending", key = "", open = false, heading, subheading = "", range, metrics = {}, body, statusBody = "", sourceSequence = "", refreshKind = "", refreshId = ""}) {
  const statusLabel = status === "pending" ? "waiting" : status;
  const statusControl = `<button class="chapter-status" type="button" data-show-reading-details title="${status === "failed" ? "Show error and run details" : "Show run details"}">${escapeHtml(statusLabel)}</button>`;
  const complexity = metrics.sentenceCount ? `${Number(metrics.sentenceCount).toLocaleString()} sentences · ${Number(metrics.averageSentenceWords || 0).toLocaleString()} average words/sentence · ${Number(metrics.sentenceLengthVariation || 0).toLocaleString()} sentence-length variation · ${Number(metrics.lexicalDiversity || 0).toLocaleString()} lexical diversity` : "";
  const sourceStats = sourceMetricsMarkup(metrics, range, {className: "analysis-source-stats", title: complexity});
  const identity = `<span class="chapter-heading"><span class="chapter-title-line"><span>${escapeHtml(heading)}</span></span>${subheading ? `<strong>${escapeHtml(subheading)}</strong>` : ""}</span>`;
  const metadata = sourceSequence ? chapterSourceMetadata(sourceSequence, heading, sourceStats) : sourceStats;
  return `<details class="analysis-row chapter-summary ${escapeHtml(className)} ${escapeHtml(status)}"${key ? ` data-analysis-key="${escapeHtml(key)}"` : ""} data-analysis-heading="${escapeHtml(heading)}" data-analysis-subheading="${escapeHtml(subheading)}" data-analysis-range="${escapeHtml(range || "")}" data-analysis-status="${escapeHtml(status)}" data-refresh-kind="${escapeHtml(refreshKind)}" data-refresh-id="${escapeHtml(refreshId)}"${open ? " open" : ""}><summary class="analysis-row-columns">${analysisRowColumns({identity, metadata: metadata, reporting: statusControl})}</summary><div class="chapter-summary-body"><div class="chapter-editorial-content">${body}</div></div><template class="analysis-details-template">${statusBody}</template></details>`;
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
  showDialog("reading-details-dialog");
  startReadingDetailsClock();
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
    {label: "Questions", icon: "?", tone: "questions", items: dossier.questions},
    {label: "Promises and reader contracts", icon: "◇", tone: "promises", items: dossier.promises},
    {label: "Evidence", icon: "¶", tone: "evidence", items: dossier.evidence},
  ];
  const result = status === "complete" ? `<p>${escapeHtml(dossier.synopsis || "")}</p>${groups.map((group) => group.grouped ? analysisSectionGroupMarkup({...group, groups: group.grouped}) : analysisSectionMarkup(group)).join("")}` : status === "failed" ? `<p>This source chunk does not have a usable dossier. Select <strong>Failed</strong> for the error and run details.</p>` : `<p>${status === "running" ? "This source chunk is being analyzed now." : "This source chunk has not been analyzed yet."}</p>`;
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
  const chapters = (pipeline.chapters || []).filter((chapter) => displayHeading(chapter.title).toLocaleLowerCase() !== "front matter" && String(chapter.summary || "").trim());
  const summary = String(whole.summary || "").trim();
  return `<article class="editor-report book-summary-report"><header><p>Editorial overview</p><h2>${summary ? "The story at a glance" : "The whole-book summary is not ready yet"}</h2></header>${summary ? `<div class="book-summary-lede"><p>${escapeHtml(summary)}</p></div>` : '<div class="pipeline-empty compact"><strong>Finish the Summary rollup first.</strong><p>Chapter summaries remain available below while the whole-book synthesis is unfinished.</p></div>'}<section class="chapter-digest-list"><h3>Chapter summaries</h3>${chapters.map((chapter) => `<article><header><span>${escapeHtml(reportChapterNumber(chapter))}</span><div><strong>${escapeHtml(displayHeading(chapter.title) || `Chapter ${chapter.number || chapter.sequence}`)}</strong>${displayHeading(chapter.chapterTitle) ? `<small>${escapeHtml(displayHeading(chapter.chapterTitle))}</small>` : ""}</div></header><p>${escapeHtml(chapter.summary)}</p></article>`).join("") || "<p>No chapter summaries are complete.</p>"}</section></article>`;
}

function smellsReportMarkup(pipeline) {
  const findings = reportableSmells(pipeline);
  const grouped = new Map();
  findings.forEach(({chapter, item}) => {
    const key = String(chapter.sequence || chapter.number || "");
    if (!grouped.has(key)) grouped.set(key, {chapter, items: []});
    grouped.get(key).items.push(item);
  });
  const content = [...grouped.values()].map(({chapter, items}) => `<section class="report-findings-chapter"><header><span>${escapeHtml(reportChapterNumber(chapter))}</span><div><h3>${escapeHtml(displayHeading(chapter.title) || `Chapter ${chapter.number || chapter.sequence}`)}</h3>${displayHeading(chapter.chapterTitle) ? `<p>${escapeHtml(displayHeading(chapter.chapterTitle))}</p>` : ""}</div><strong>${items.length} ${items.length === 1 ? "finding" : "findings"}</strong></header><div>${items.map((item) => `<article><h4>${escapeHtml(item.judgment?.issue || "Possible prose smell")}</h4><p>${escapeHtml(item.judgment?.reason || item.evidence?.[0]?.message || "This sentence deserves an editor’s attention.")}</p><blockquote>“${escapeHtml(item.sentence || "")}”</blockquote><button type="button" data-view-source-passage data-chapter-sequence="${Number(chapter.sequence || chapter.number || 0)}" data-character-start="${Number(item.characterStart || 0)}" data-character-end="${Number(item.characterEnd || 0)}" data-passage-sequence="smell-report">Inspect source</button></article>`).join("")}</div></section>`).join("");
  return workspaceTaskView({icon: "smells", title: "Smells report", subtitle: `${findings.length.toLocaleString()} undismissed editorial ${findings.length === 1 ? "finding" : "findings"} across the book.`, actions: reportExportControl("smell-report"), explanationTitle: "Only findings still in play belong here.", explanation: "This report excludes anything you dismissed and keeps every remaining concern connected to its exact sentence.", collapse: false, content: `<article class="editor-report smells-report">${content || '<div class="pipeline-empty"><strong>No undismissed smells.</strong><p>Completed chapters have no surviving editorial findings.</p></div>'}</article>`});
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
  return workspaceTaskView({icon: "emotions", title: "Emotion map", subtitle: `${available} of ${chapters.length} chapters scored · only emotions at 10% or higher are shown.`, actions: reportExportControl("emotion-map"), explanationTitle: "Length is part of the story shape.", explanation: "Each row is a chapter. Its track length is proportional to word count; the colored bars show substantial emotion scores so long emotional stretches and abrupt changes remain visible without sacrificing chapter names.", collapse: false, content: `<article class="editor-report emotion-map-report"><section class="emotion-map-key" aria-label="Emotion map key"><div><strong>How to read this</strong><span class="emotion-length-key"><i></i>Track length = chapter word count</span><span>Bars = chapter-average emotion at 10% or higher</span></div><div class="emotion-map-legend"><strong>Emotions in this book</strong>${legend || "<span>No completed emotion scores yet.</span>"}</div></section><div class="emotion-map-viewport"><div class="emotion-map-track">${track}</div></div></article>`});
}

function inferenceLedgerMarkup(pipeline) {
  const rows = (pipeline.inferences || []).map((algorithm) => {
    const status = String(algorithm.status || "blocked");
    const dependencies = (algorithm.dependsOn || []).map(signalLabel).join(" + ") || "Saved analysis";
    const run = algorithm.id === "questions" && !["running", "blocked"].includes(status)
      ? pipelineControl({action: "questions", label: status === "complete" ? "Rebuild" : "Run", title: status === "complete" ? "Reconcile questions and payoffs again" : "Run questions and payoffs"})
      : "";
    return `<article class="inference-step ${escapeHtml(status)}"><span class="inference-step-state" aria-hidden="true"></span><div><h3>${escapeHtml(algorithm.label || signalLabel(algorithm.id))}</h3><p>${escapeHtml(algorithm.detail || "Book-level inference")}</p><small>${escapeHtml(algorithm.method || "Book-level algorithm")} · Inputs: ${escapeHtml(dependencies)}</small></div><span class="inference-step-status">${escapeHtml(status)}</span>${run}</article>`;
  }).join("");
  return `<div class="inference-ledger">${rows || '<div class="pipeline-empty"><strong>No inference algorithms are registered.</strong><p>They will appear here as Bookinator gains whole-book reasoning tools.</p></div>'}</div>`;
}

function reportExportMarkup(pipeline) {
  const chapterSummaries = (pipeline.chapters || []).filter((chapter) => String(chapter.summary || "").trim()).length;
  const smells = reportableSmells(pipeline).length;
  const emotions = (pipeline.chapters || []).filter((chapter) => chapter.emotionStatus === "complete").length;
  const questions = pipeline.questionTracker?.items?.length || 0;
  return workspaceTaskView({icon: "report", title: "Editor PDF", subtitle: "A branded snapshot of every useful result currently saved for this book.", actions: "", explanationTitle: "A handoff, not a data dump.", explanation: "The export puts its completeness ledger immediately after the contents, before any editorial claims. The book overview, linked evidence, emotions, questions, and other reports follow; undismissed Smells remain the final appendix.", collapse: false, content: `<article class="editor-report export-report"><div class="report-export-preview"><div><p>Bookinator editorial report</p><h2>Ready to share</h2><ul><li>${chapterSummaries} chapter summaries</li><li>${smells} undismissed Smells</li><li>${emotions} emotion-scored chapters</li><li>${questions} tracked questions</li></ul></div><span class="report-export-mark" aria-hidden="true">B</span></div><button class="primary-button report-download" type="button" data-download-editor-report>Download</button><p class="report-export-note">This exports the results saved now. Running Tags or Smells can be included by downloading again after they finish.</p></article>`});
}

async function showBookPage(bookId, requestedTab = "", requestedInference = "", cachedPipeline = null) {
  clearTimeout(state.pipelineTimer);
  const requestId = ++state.workspaceRequestId;
  const book = state.books.find((item) => item.id === bookId);
  if (!book) return showBooksPage();
  state.currentBookId = book.id;
  localStorage.setItem(currentBookKey, book.id);
  updateAnalysisNavigation();
  const activeTab = workspaceTabs.some((tab) => tab.id === requestedTab) ? requestedTab : rememberedAnalysisTab(bookId);
  rememberAnalysisTab(bookId, activeTab);
  document.querySelector("#books-page").hidden = true;
  document.querySelector("#pipeline-page").hidden = true;
  document.querySelector("#article-page").hidden = true;
  const bookPage = document.querySelector("#book-page");
  const sameWorkspace = bookPage.dataset.bookId === bookId && bookPage.dataset.activeTab === activeTab;
  const identitySignature = JSON.stringify({id: book.id, title: book.title, author: book.author, icon: book.icon, manuscriptId: book.manuscriptId, sourceFilename: book.sourceFilename, ingestedAt: book.ingestedAt});
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
    const manuscriptLink = book.hasPdf ? `<a href="/api/books/${encodeURIComponent(book.id)}/manuscript" target="_blank" rel="noopener">Open ${escapeHtml(book.sourceFilename || "ingested PDF")}</a>` : "<span>No PDF attached</span>";
    header.innerHTML = `<div class="workspace-book-icon" id="workspace-book-icon"></div><div><p class="context">Book workspace</p><h1>${escapeHtml(book.title)}</h1><p>${escapeHtml(book.author || "Author not specified")}</p><div class="book-workspace-meta"><span>Ingested ${escapeHtml(formatBookDate(book.ingestedAt))}</span>${manuscriptLink}</div></div>`;
    renderIcon(document.querySelector("#workspace-book-icon"), book.icon, book.title);
  }
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
    if (sameWorkspace && signature === state.pipelineSignature) {
      if (["running", "queued"].includes(pipeline.status)) state.pipelineTimer = setTimeout(() => showBookPage(book.id, activeTab), pipeline.status === "queued" ? 500 : 1800);
      return;
    }
    const running = pipeline.status === "running";
    const queued = pipeline.status === "queued";
    const chapterMapApproved = Boolean(pipeline.chapterMapApproved);
    const summaryStage = (pipeline.stages || []).find((stage) => stage.id === "summaries") || {};
    const readerModel = running ? summaryStage.model || pipeline.configuredReaderModel || "Automatic selection" : pipeline.configuredReaderModel || summaryStage.model || "Automatic selection";
    const progress = pipeline.progress || {completed: 0, total: 0, percent: 0, etaSeconds: null};
    const summariesDone = Boolean(progress.total) && progress.completed >= progress.total;
    const activeChapter = pipeline.chapters?.find((chapter) => chapter.status === "running");
    const summaryQueued = queued && ["summarize", "restart"].includes(pipeline.queuedAction);
    const currentActivity = resolvedActivity(pipeline);
    const progressMarkup = taskProgress({label: "Overall reading progress", unit: "chapters", progress, activity: currentActivity, status: pipeline.status});
    const pipelineProgress = pipeline.pipelineProgress || {completed: 0, total: 0, percent: 0, etaSeconds: null};
    const dossierProgress = pipeline.dossierProgress || {completed: 0, total: pipeline.chunks?.length || 0, percent: 0, etaSeconds: null};
    const dossierRunning = running && pipeline.phase === "dossiers";
    const activeChunk = pipeline.chunks?.find((chunk) => chunk.dossierStatus === "running");
    const dossierModel = pipeline.configuredDossierModel || (pipeline.stages || []).find((stage) => stage.id === "dossiers")?.model || "Automatic selection";
    const dossierQueued = queued && pipeline.queuedAction === "dossiers";
    const dossiersDone = Boolean(dossierProgress.total) && dossierProgress.completed >= dossierProgress.total;
    const dossierAction = !dossierRunning && !dossierQueued
      ? dossiersDone
        ? pipelineControl({action: "dossier-restart", label: "Redo", title: "Redo every chunk dossier with the selected model"})
        : pipelineControl({action: "dossiers", label: "Finish", title: "Finish the remaining dossiers before returning to other analysis"})
      : "";
    const mapReviewControl = !chapterMapApproved && pipeline.chapters?.length ? reviewChapterMapControl(pipeline.chapterMapSuspicious ? "Review" : "Review map") : "";
    const dossierActions = taskHeadingActions({model: dossierModel, role: "dossier", action: dossierAction, extra: `${timingChartControl("dossiers")}${mapReviewControl}`});
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
    const pipelineWorkspaceActions = pipeline.phase?.startsWith("dossiers")
      ? taskHeadingActions({model: dossierModel, role: "dossier", extra: `${timingChartControl("pipeline")}${retryFailedControl}${reconnectControl}${mapReviewControl}${rebuildControl}`})
      : taskHeadingActions({model: readerModel, role: "reader", extra: `${timingChartControl("pipeline")}${retryFailedControl}${reconnectControl}${mapReviewControl}${rebuildControl}`});
    if (activeTab === "pipeline") {
      const pipelineProgressMarkup = taskProgress({label: "Overall pipeline progress", unit: "chapter-steps", progress: pipelineProgress, activity: currentActivity, status: pipeline.status});
      const pipelineError = ["warning", "failed", "blocked"].includes(pipeline.status) && pipeline.error ? escapeHtml(pipeline.error) : "";
      body.innerHTML = workspaceTaskView({icon: "pipeline", title: "Reading pipeline", subtitle: pipeline.message || "Ready.", actions: pipelineWorkspaceActions, explanationTitle: "The pipeline is the work ledger.", explanation: "It shows what Bookinator has saved, what the local model is doing now, and what remains available to run.", error: pipelineError, progress: pipelineProgressMarkup, content: `${provisionalAnalysisNotice(pipeline)}${chapterMapWarning}<div class="pipeline-stages">${visiblePipelineStages(pipeline).map((stage) => stageMarkup(stage, pipeline, book, openRows)).join("")}</div>`});
    } else if (activeTab === "chapters") {
      const chapterAction = pipeline.chapterMapSuspicious
        ? pipelineControl({action: "prepare", label: "Rebuild", title: "Rebuild the chapter map with the accepted heading rules"})
        : chapterMapApproved
          ? pipelineControl({action: "prepare", label: "Rebuild", title: "Re-extract the manuscript and propose a fresh chapter map"})
          : approveChapterMapControl();
      const chapterSubtitle = pipeline.chapterMapSuspicious
        ? "The detected heading family needs an editorial decision."
        : chapterMapApproved
          ? `${pipeline.chapters?.length || 0} sections approved as the structural source of truth.`
          : `${pipeline.chapters?.length || 0} detected sections are waiting for approval.`;
      body.innerHTML = workspaceTaskView({
        icon: "chapters",
        title: "Chapter map",
        subtitle: chapterSubtitle,
        actions: taskHeadingActions({action: chapterAction, extra: timingChartControl("chapters")}),
        explanationTitle: "Structure is a contract.",
        explanation: "Bookinator can analyze this proposed map immediately. Approval makes it the structural source of truth; changing a boundary later marks every dependent artifact stale and queues fresh work.",
        error: pipeline.chapterMapSuspicious ? escapeHtml((pipeline.chapterMapWarnings || []).join(" ")) : "",
        content: `<div class="chapter-map-list">${wholeBookAnalysisRow(pipeline, "chapters", book)}${pipeline.chapters?.length ? pipeline.chapters.map((chapter) => chapterMapRow(chapter, pipeline, book)).join("") : '<div class="pipeline-empty"><strong>No chapter map yet.</strong><p>Prepare the manuscript to extract pages and propose its structure.</p></div>'}</div>`,
      });
    } else if (signalView) {
      const signalStage = (pipeline.stages || []).find((stage) => stage.id === signalView.stageId) || {};
      const signalProgress = pipeline[signalView.progressKey] || {completed: 0, total: pipeline.chapters?.length || 0, percent: 0, etaSeconds: null};
      const signalDone = Boolean(signalProgress.total) && signalProgress.completed >= signalProgress.total;
      const signalDisabled = Boolean(signalStage.disabled);
      const signalRunning = running && pipeline.phase === signalView.phase;
      const signalQueued = queued && signalView.queued.includes(pipeline.queuedAction);
      const activeSignalChapter = pipeline.chapters?.find((chapter) => chapter[`${signalView.kind}Status`] === "running");
      const signalModel = signalView.kind === "emotion" ? (signalStage.model || "Hartmann DistilRoBERTa") : signalView.kind === "smell" ? (signalStage.model || readerModel || "Automatic selection") : (pipeline.configuredTagModel || signalStage.model || "Automatic selection");
      const signalAction = !signalDisabled && signalDone && !signalRunning && !signalQueued
        ? pipelineControl({action: signalView.restart, label: "Redo", title: `Redo every chapter’s ${signalView.noun}`})
        : "";
      const modelAction = signalView.kind === "tag" ? taskHeadingActions({model: signalModel, role: "tags", action: signalAction, extra: `${timingChartControl(signalView.stageId)}${mapReviewControl}`}) : taskHeadingActions({action: signalAction, extra: `${timingChartControl(signalView.stageId)}${mapReviewControl}`});
      const signalProgressMarkup = taskProgress({label: `Overall ${signalView.noun} progress`, unit: "chapters", progress: signalProgress, activity: currentActivity, status: signalStage.status || pipeline.status});
      const signalChapters = (pipeline.chapters || []).filter((chapter) => displayHeading(chapter.title).toLowerCase() !== "front matter");
      const signalContent = `<div class="analysis-list">${signalChapters.length ? signalChapters.map((chapter) => chapterSignalMarkup(chapter, signalView.kind, openRows, book)).join("") : '<div class="pipeline-empty"><strong>First, map the manuscript.</strong><p>Bookinator needs durable chapter objects before this pass can begin.</p></div>'}</div>`;
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
    } else if (activeTab === "report") {
      body.innerHTML = reportExportMarkup(pipeline);
    } else if (activeTab === "overview") {
      body.innerHTML = workspaceTaskView({icon: "overview", title: "Book summary", subtitle: "The editor’s first orientation to the manuscript, followed by every chapter digest.", actions: reportExportControl("overview"), explanationTitle: "Start with the shape of the story.", explanation: "The whole-book synthesis leads. Chapter summaries remain directly below it so an editor can move from the broad account to the local sequence without changing tools.", collapse: false, content: bookSummaryReportMarkup(pipeline)});
    } else if (activeTab === "smell-report") {
      body.innerHTML = smellsReportMarkup(pipeline);
    } else if (activeTab === "emotion-map") {
      body.innerHTML = emotionMapReportMarkup(pipeline);
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
    } else if (activeTab === "inferences") {
      const algorithms = pipeline.inferences || [];
      const finished = algorithms.filter((algorithm) => algorithm.status === "complete").length;
      body.innerHTML = workspaceTaskView({icon: "inferences", title: "Inferences", subtitle: `${finished} of ${algorithms.length} book-level algorithms complete.`, actions: "", explanationTitle: "These are jobs, not reports.", explanation: "Each step combines evidence across the manuscript. Run and inspect the algorithm here; use its editorial result in Explore.", collapse: false, content: inferenceLedgerMarkup(pipeline)});
    } else if (activeTab === "summaries") {
      const complete = progress.completed;
      const wholeSummaryDone = pipeline.wholeBookSummary?.status === "complete" && Boolean(pipeline.wholeBookSummary?.summary);
      const wholeSummaryQueued = pipeline.wholeBookSummary?.status === "running" || pipeline.queuedAction === "whole-summary";
      const summaryAction = summariesDone && !wholeSummaryDone && !wholeSummaryQueued
        ? pipelineControl({action: "whole-summary", label: "Finish", title: "Build the whole-book summary now without waiting for independent analysis passes"})
        : summariesDone && wholeSummaryDone && !running && !queued
          ? pipelineControl({action: "restart", label: "Redo", title: "Redo every chapter summary with the selected model"})
          : "";
      const summaryHeadingActions = taskHeadingActions({model: pipeline.chapters?.length ? readerModel : "", role: "reader", action: summaryAction, extra: `${timingChartControl("summaries")}${mapReviewControl}`});
      const summaryTitle = "Chapter summaries";
      const summarySubtitle = summariesDone
          ? `${progress.total} manuscript chapter summaries complete.`
          : pipeline.chapters?.length
            ? `${complete} of ${progress.total} manuscript summaries complete.`
            : pipeline.message || "No chapters have been detected yet.";
      const summaryContent = `<div class="analysis-list">${wholeBookAnalysisRow(pipeline, "summaries", book)}${pipeline.chapters?.length ? pipeline.chapters.map((chapter) => chapterMarkup(chapter, openRows, book)).join("") : '<div class="pipeline-empty"><strong>First, map the manuscript.</strong><p>Bookinator will extract the pages and propose chapter boundaries before any model begins summarizing.</p></div>'}</div>`;
      body.innerHTML = workspaceTaskView({icon: "summaries", title: summaryTitle, subtitle: summarySubtitle, actions: summaryHeadingActions, explanationTitle: "Summaries are navigation.", explanation: "Each chapter digest gives you a quick map of what happened, what the chapter establishes, and which questions remain open.", activity: summariesDone ? "" : activity, error: !summariesDone && pipeline.error ? `<strong>The local reader stopped.</strong> ${escapeHtml(pipeline.error)}` : "", progress: summariesDone ? "" : progressMarkup, content: `${provisionalAnalysisNotice(pipeline)}${chapterMapWarning}${summaryContent}`});
    } else {
      body.innerHTML = plannedWorkspaceView(plannedWorkspaceViews[activeTab]);
    }
    state.pipelineSignature = signature;
    if (sameWorkspace) requestAnimationFrame(() => window.scrollTo({top: priorScrollY, behavior: "auto"}));
    body.querySelectorAll("[data-show-timing-chart]").forEach((button) => button.addEventListener("click", () => openTimingChart(pipeline, button.dataset.showTimingChart)));
    body.querySelector("[data-download-editor-report]")?.addEventListener("click", async (event) => {
      const button = event.currentTarget;
      const original = button.textContent;
      button.disabled = true;
      button.textContent = "Building PDF…";
      try {
        const pdf = await editorReportPdf(pipeline, book);
        const filename = `${String(book.title || "book").toLocaleLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") || "book"}-editorial-report.pdf`;
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
      const reportNames = {overview: "book-summary", "smell-report": "smells", "emotion-map": "emotion-map", connections: "connections", questions: "questions-and-payoffs"};
      const original = control.textContent;
      control.disabled = true;
      control.textContent = "Building…";
      try {
        const pdf = await editorReportPdf(pipeline, book, {only: report});
        const bookSlug = String(book.title || "book").toLocaleLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") || "book";
        downloadFile(pdf, `${bookSlug}-${reportNames[report] || report}.pdf`, "application/pdf");
        control.closest("details")?.removeAttribute("open");
      } catch (error) {
        await confirmAction({context: "PDF export failed", title: "Bookinator could not build this report", message: error.message || "The browser could not render this report.", acceptLabel: "Close"});
      } finally {
        control.disabled = false;
        control.textContent = original;
      }
    }));
    body.querySelector("[data-reconnect-pdf]")?.addEventListener("click", () => openExistingBook(book.id));
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
        showBookPage(book.id, "chapters");
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
    body.querySelectorAll("[data-open-task-model]").forEach((button) => button.addEventListener("click", () => openTaskModelDialog(book, pipeline, button.dataset.openTaskModel)));
    body.querySelectorAll("[data-view-chapter-source]").forEach((button) => button.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      const analysisChapter = (pipeline.chapters || []).find((item) => Number(item.sequence || item.number) === Number(button.dataset.viewChapterSource));
      openChapterSource(book.id, button.dataset.viewChapterSource, null, analysisChapter);
    }));
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
    body.querySelectorAll("[data-view-source-passage]").forEach((button) => button.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      const chapter = (pipeline.chapters || []).find((item) => Number(item.sequence || item.number) === Number(button.dataset.chapterSequence));
      if (!chapter) return;
      openChapterSource(book.id, chapter.sequence || chapter.number, {
        kind: "source",
        sequence: button.dataset.passageSequence || "1",
        characterStart: Number(button.dataset.characterStart || 0),
        characterEnd: Number(button.dataset.characterEnd || 0),
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
        const restart = await confirmAction({context: "Fresh reading", title: "Redo every chapter summary?", message: "Bookinator will archive the model and timing details for the current summaries, mark all chapters pending, and replace the summaries one at a time. You can stop safely and resume later.", acceptLabel: "Redo summaries"});
        if (!restart) return;
      }
      if (action === "dossier-restart") {
        const restart = await confirmAction({context: "Fresh dossiers", title: "Redo every chunk dossier?", message: "Bookinator will archive the current dossier run details, mark every source chunk pending, and rebuild the dossiers one at a time with the selected model.", acceptLabel: "Redo dossiers"});
        if (!restart) return;
      }
      if (action === "questions" && (pipeline.questionTracker?.items || []).length) {
        const rebuild = await confirmAction({context: "Fresh reconciliation", title: "Rebuild questions and payoffs?", message: "Bookinator will replace the current groupings and payoff matches with a new whole-book reconciliation from the latest chapter summaries and dossiers.", acceptLabel: "Rebuild tracker"});
        if (!rebuild) return;
      }
      if (["emotion-restart", "tag-restart", "smell-restart"].includes(action)) {
        const emotions = action === "emotion-restart";
        const smells = action === "smell-restart";
        const restart = await confirmAction({context: emotions ? "Fresh emotion pass" : smells ? "Fresh Smells pass" : "Fresh tag pass", title: emotions ? "Redo every chapter’s emotion scores?" : smells ? "Redo every chapter’s Smells review?" : "Redo every chapter’s tags?", message: `Bookinator will archive the current run details, mark every chapter pending for this pass, and rebuild the ${emotions ? "Hartmann emotion scores" : smells ? "local detector evidence and editorial judgments" : "evidence-bearing tags"} one chapter at a time. Your manual Smells dismissals are restored when the same source finding returns.`, acceptLabel: emotions ? "Redo emotions" : smells ? "Redo Smells" : "Redo tags"});
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
    if (running || queued) state.pipelineTimer = setTimeout(() => showBookPage(book.id, activeTab), queued ? 500 : 1800);
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

document.querySelectorAll('button[data-page="books"]').forEach((button) => button.addEventListener("click", () => { closePrimaryNavigation(); location.hash = "books"; }));
document.querySelector("#pipeline-nav")?.addEventListener("click", () => { closePrimaryNavigation(); location.hash = "pipeline"; });
document.querySelector("#analysis-nav")?.addEventListener("click", () => {
  closePrimaryNavigation();
  const current = updateAnalysisNavigation();
  location.hash = current ? `book/${current.id}/${rememberedAnalysisTab(current.id)}` : "books";
});
document.querySelector("#machine-nav")?.addEventListener("click", () => {
  closePrimaryNavigation();
  openSystemPanel("machine");
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
    await confirmAction({context: "Refresh failed", title: "Bookinator could not refresh this result", message: error.message, acceptLabel: "Close"});
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
window.addEventListener("hashchange", route);
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
