import { createProductAboutPage, createProductDocsFlow, defineProductAbout } from "/commons/@inator/ui/index.js";

export const bookinatorAbout = defineProductAbout({
  product: {
    name: "Bookinator",
    summary: "A local-first manuscript analysis workbench for authors and editors."
  },
  citation: {
    title: "Bookinator",
    authors: ["Randal Cox"],
    version: "0.1.0",
    year: 2026,
    url: "https://github.com/randal-cox/bookinator",
    text: "Randal Cox. Bookinator, version 0.1.0 (2026)."
  }
});

const recordRoutes = Object.freeze({
  milestones: "#releases/milestones",
  roadmap: "#roadmap/priorities",
  security: "#legal/security",
  privacy: "#legal/privacy"
});

export function createBookinatorAboutPage({ root, tabs } = {}) {
  const sections = Object.entries(tabs || {}).map(([id, [label, content]]) => ({ id, heading: label, content }));
  const controller = createProductAboutPage({
    root,
    productLabel: bookinatorAbout.product.name,
    productContent: createProductDocsFlow({ sections })
  });
  for (const [record, href] of Object.entries(recordRoutes)) {
    const link = root.querySelector(`.inator-record-link--${record}`);
    if (link) link.href = href;
  }
  return controller;
}
