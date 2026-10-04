import { createProductDocsFlow, createProductFaq } from "/commons/@inator/ui/index.js";

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
