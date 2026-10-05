import { definePipelineSnapshot } from "/commons/@inator/engine/pipeline-contract.js";

const projectPriority = Object.freeze({ high: "high", normal: "normal", low: "low", shelved: "deferred" });
const unitStatus = Object.freeze({ running: "running", pausing: "stopping", ready: "waiting", waiting: "blocked", paused: "paused" });

export function createBookinatorPipelineSnapshot({ books = [], pipeline = {}, tasks = [] } = {}) {
  const currentRun = pipeline.currentRun || {};
  const completed = Math.max(0, Number(currentRun.completed ?? pipeline.completed ?? 0));
  const reportedTotal = Math.max(0, Number(currentRun.total ?? pipeline.total ?? 0));
  const total = Math.max(completed, reportedTotal, tasks.length);
  const started = currentRun.startedAt ? new Date(currentRun.startedAt).toLocaleString() : "not started";
  const runBooks = Math.max(0, Number(currentRun.bookCount || 0));
  const addedUnits = Math.max(0, Number(currentRun.addedUnits || 0));
  const deferredUnits = Math.max(0, Number(currentRun.deferredUnits || 0));
  const basis = [
    `${runBooks} ${runBooks === 1 ? "project" : "projects"} · started ${started}`,
    addedUnits ? `${addedUnits.toLocaleString()} added after the run began` : "Starting scope preserved",
    deferredUnits ? `${deferredUnits.toLocaleString()} deferred by project policy` : ""
  ].filter(Boolean).join(" · ");
  const runId = String(currentRun.id || currentRun.startedAt || "bookinator-current-run");

  return definePipelineSnapshot({
    schema: "inator.pipeline-snapshot.v1",
    id: runId,
    runId,
    state: pipeline.running ? "running" : pipeline.enabled ? "ready" : "stopped",
    projects: books.map((book) => ({
      id: String(book.id),
      label: String(book.title || "Untitled project"),
      detail: String(book.author || "Author not specified"),
      priority: projectPriority[book.priority] || "normal"
    })),
    units: tasks.map((task) => ({
      id: String(task.id),
      projectId: String(task.book.id),
      label: String(task.label),
      detail: String(task.detail || ""),
      method: String(task.action || "pipeline.work"),
      action: String(task.action || ""),
      provider: "local",
      sequence: Number(task.rank || 0),
      rank: Number(task.bookRank || task.rank || 0),
      status: unitStatus[task.state] || "blocked",
      dependencyIds: [],
      attempts: [],
      policy: {
        required: Boolean(task.required),
        paused: task.state === "paused" || task.state === "pausing",
        pinned: false,
        stopAfter: false,
        notifyOnComplete: false,
        retry: "explicit",
        recovery: "retry-attempt",
        safeStopBoundary: "attempt"
      },
      gate: { state: "not-required" }
    })),
    progress: { completed, total, basis, referenceAt: currentRun.startedAt || null },
    controls: { start: true, stop: true, moveTop: true, projectPriority: true, pause: true, resume: true },
    completion: { machine: completed === total && total > 0 ? "complete" : "incomplete", review: "product-owned" }
  });
}
