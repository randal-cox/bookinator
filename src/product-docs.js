import { createInformationGraphic, createProductDocsFlow, createProductDocsPage, createProductFaq, defineProductDocs } from "/commons/@inator/ui/index.js";

const HELP_GRAPHIC_ICONS = Object.freeze({
  "Before the book reads itself": "machine",
  "The book has an operating surface": "analysis",
  "Local reading takes time": "timing",
  "After the analysis": "reports",
  "Local application architecture": "connections",
  "Durable local state": "archive",
  "Repeatable work": "pipeline",
  "Ollama model roles": "models",
  "The boundary": "trust"
});

function replaceHelpLabelsWithGraphics(root) {
  root.querySelectorAll(".information-lede > p:first-child").forEach((label) => {
    const topic = label.textContent.trim();
    label.replaceWith(createInformationGraphic({
      icon: HELP_GRAPHIC_ICONS[topic] || "guide",
      label: topic,
      className: "help-topic-graphic"
    }));
  });
}

function fragmentFromMarkup(markup) {
  const template = document.createElement("template");
  template.innerHTML = String(markup || "").trim();
  return template.content;
}

function privacyFaq(list) {
  const items = [...list.querySelectorAll(":scope > li")].map((item) => {
    const label = item.querySelector("strong")?.textContent?.replace(/:\s*$/, "").trim() || "Privacy";
    return {
      question: `What does “${label}” mean?`,
      answer: `<p>${item.innerHTML}</p>`
    };
  });
  return createProductFaq({ items });
}

export function createBookinatorDocsFlow({ tab, markup } = {}) {
  const source = fragmentFromMarkup(markup);
  const introduction = source.querySelector(":scope > .information-lede");
  const remaining = document.createDocumentFragment();
  [...source.children].filter((node) => node !== introduction).forEach((node) => remaining.append(node));

  const sections = [];
  if (introduction) sections.push({ id: `${tab}-introduction`, content: introduction });

  if (tab === "privacy") {
    const list = remaining.querySelector(".privacy-doc");
    if (list) {
      list.remove();
      if (remaining.children.length) sections.push({ id: `${tab}-detail`, content: remaining });
      sections.push({ id: `${tab}-faq`, heading: "Common privacy questions", content: privacyFaq(list) });
    } else if (remaining.children.length) sections.push({ id: `${tab}-detail`, content: remaining });
  } else if (remaining.children.length) {
    sections.push({ id: `${tab}-detail`, content: remaining });
  }

  return createProductDocsFlow({ sections });
}

function flowForTabs(tabs = {}) {
  return createProductDocsFlow({ sections: Object.entries(tabs).map(([id, [heading, content]]) => ({ id: `help-${id}`, heading, content })) });
}

export function createBookinatorHelpPage({ root, guideTabs = {}, referenceTabs = {}, initialSection = "start", onSelect = null } = {}) {
  const guideEntries = Object.entries(guideTabs);
  const start = guideEntries[0]?.[1]?.[1] || "<p>Choose a book to begin.</p>";
  const tasks = Object.fromEntries(guideEntries.slice(1));
  const faq = createProductFaq({ items: [
    { question: "Does Bookinator upload the manuscript?", answer: "<p>No. Normal manuscript analysis, saved evidence, and reports remain on this computer.</p>" },
    { question: "Why can analysis take a while?", answer: "<p>Bookinator reads locally. Large models and long chapters can take minutes, so the Pipeline keeps waiting, running, completed, and failed work visible.</p>" },
    { question: "What should I share?", answer: "<p>Use the model-free HTML or PDF reports. They carry selected analysis and provenance without including the source manuscript.</p>" },
    { question: "Where do I inspect models and prerequisites?", answer: "<p>Open Workspace, then Machine. Models and installed software are deliberately kept out of the everyday editorial workflow.</p>" }
  ] });
  const docs = defineProductDocs({
    productLabel: "Bookinator",
    heading: "Find your bearings. Then follow the evidence.",
    introduction: "Start with the first run, follow an everyday task, look up the local architecture, or answer a common question.",
    sections: {
      start: { content: createBookinatorDocsFlow({ tab: "start", markup: start }) },
      tasks: { content: flowForTabs(tasks) },
      reference: { content: flowForTabs(referenceTabs) },
      faq: { content: faq }
    }
  });
  const controller = createProductDocsPage({ root, docs, initialSection, onSelect });
  replaceHelpLabelsWithGraphics(root);
  return controller;
}
