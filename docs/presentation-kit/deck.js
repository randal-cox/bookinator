export function initDeck({ deckId, presenterUrl = "presenter.html" }) {
  const slides = [...document.querySelectorAll(".slide")];
  const fill = document.querySelector("#progress-fill");
  const channel = "BroadcastChannel" in window ? new BroadcastChannel(`${deckId}-presenter`) : null;
  let index = Math.max(0, Math.min(slides.length - 1, Number(location.hash.slice(1) || 1) - 1));
  const state = () => ({ type: "slide-state", index, total: slides.length, slides: slides.map((slide) => ({
    title: slide.querySelector("h1,h2")?.textContent.trim() || "",
    note: slide.querySelector(".speaker-note")?.textContent.trim() || ""
  })) });
  const render = (hash = true) => {
    slides.forEach((slide, i) => slide.classList.toggle("is-active", i === index));
    if (fill) fill.style.width = `${((index + 1) / slides.length) * 100}%`;
    if (hash) history.replaceState(null, "", `#${index + 1}`);
    localStorage.setItem(`${deckId}-presenter-state`, JSON.stringify(state()));
    channel?.postMessage(state());
  };
  const go = (next) => { index = Math.max(0, Math.min(slides.length - 1, next)); render(); };
  addEventListener("keydown", (event) => {
    if (["ArrowRight", "PageDown", " "].includes(event.key)) { event.preventDefault(); go(index + 1); }
    if (["ArrowLeft", "PageUp"].includes(event.key)) { event.preventDefault(); go(index - 1); }
    if (event.key === "Home") go(0);
    if (event.key === "End") go(slides.length - 1);
    if (event.key.toLowerCase() === "n") window.open(presenterUrl, `${deckId}-presenter`, "popup,width=680,height=760")?.focus();
    if (event.key.toLowerCase() === "f") document.fullscreenElement ? document.exitFullscreen() : document.documentElement.requestFullscreen();
  });
  channel?.addEventListener("message", ({ data }) => {
    if (data?.type === "presenter-ready") render(false);
    if (data?.type === "navigate") go(index + Number(data.delta || 0));
    if (data?.type === "go-to") go(Number(data.index || 0));
  });
  addEventListener("hashchange", () => { index = Math.max(0, Math.min(slides.length - 1, Number(location.hash.slice(1) || 1) - 1)); render(false); });
  render(!location.hash);
}
