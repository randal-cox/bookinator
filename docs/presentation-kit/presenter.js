export function initPresenter({ deckId }) {
  const ids = ["current-number","total-number","current-title","current-note","next-title","next-note"];
  const el = Object.fromEntries(ids.map((id) => [id, document.getElementById(id)]));
  const channel = new BroadcastChannel(`${deckId}-presenter`);
  const render = (state) => {
    if (!state?.slides) return;
    const current = state.slides[state.index] || {}, next = state.slides[state.index + 1] || {};
    el["current-number"].textContent = state.index + 1; el["total-number"].textContent = state.total;
    el["current-title"].textContent = current.title; el["current-note"].textContent = current.note;
    el["next-title"].textContent = next.title || "End"; el["next-note"].textContent = next.note || "";
  };
  try { render(JSON.parse(localStorage.getItem(`${deckId}-presenter-state`))); } catch {}
  channel.addEventListener("message", ({ data }) => data?.type === "slide-state" && render(data));
  document.getElementById("first").onclick = () => channel.postMessage({ type: "go-to", index: 0 });
  document.getElementById("previous").onclick = () => channel.postMessage({ type: "navigate", delta: -1 });
  document.getElementById("next").onclick = () => channel.postMessage({ type: "navigate", delta: 1 });
  document.getElementById("last").onclick = () => channel.postMessage({ type: "go-to", index: 999 });
  channel.postMessage({ type: "presenter-ready" });
}
