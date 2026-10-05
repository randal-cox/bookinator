import { createProductResourcePage, defineResourceCatalog } from "/commons/@inator/ui/index.js";

export async function createBookinatorResourcePage({ root } = {}) {
  if (!root) throw new TypeError("createBookinatorResourcePage requires root.");
  root.setAttribute("aria-busy", "true");
  try {
    const response = await fetch("/docs/presentations/catalog.json", { cache: "no-store" });
    if (!response.ok) throw new Error(`Resource catalog request failed (${response.status}).`);
    const catalog = defineResourceCatalog(await response.json());
    root.removeAttribute("aria-busy");
    return createProductResourcePage({ root, catalog, productLabel: "Bookinator", heading: "The story of the work, ready to carry.", introduction: "Presentations, product briefs, and carefully bounded language for explaining Bookinator without overstating what it can do." });
  } catch (error) {
    root.removeAttribute("aria-busy");
    root.innerHTML = `<p class="resources-error" role="alert">${error.message}</p>`;
    return null;
  }
}
