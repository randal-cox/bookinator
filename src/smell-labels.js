import { normalizeLexicalKey, sentenceCaseLabel } from "./lexical-labels.js?v=canonical-labels-170";

const canonicalSmellLabels = new Map([
  ["clause count", "Complex sentence"], ["clause load", "Complex sentence"],
  ["clause load proxy", "Complex sentence"], ["clause complexity", "Complex sentence"],
  ["clause overload", "Complex sentence"], ["dependent clauses", "Complex sentence"],
  ["complexity", "Complex sentence"], ["complex structure", "Complex sentence"],
  ["complex sentence", "Complex sentence"], ["complex sentence structure", "Complex sentence"],
  ["nested structure", "Complex sentence"], ["heavy clause load", "Complex sentence"],
  ["many clauses", "Complex sentence"],
  ["finite verb load", "Overloaded sentence"], ["overloaded sentence", "Overloaded sentence"],
  ["possible overloaded sentence", "Overloaded sentence"], ["run on", "Overloaded sentence"],
  ["length", "Long sentence"], ["sentence length", "Long sentence"],
  ["long sentence", "Long sentence"], ["very long sentence", "Long sentence"],
  ["oxford comma", "Oxford comma"], ["missing oxford comma", "Oxford comma"],
]);

export function normalizeSmellKey(value) {
  return normalizeLexicalKey(value);
}

function canonicalSmellLabel(value) {
  const key = normalizeSmellKey(value);
  if (key.includes("oxford comma")) return "Oxford comma";
  const family = [
    ["weasel words", "Weasel words"], ["cliches", "Cliché"], ["redundancy", "Redundancy"],
    ["typography punctuation", "Punctuation"], ["lexical illusion", "Repeated phrase"],
    ["repeated word", "Repeated word"],
  ].find(([prefix]) => key.startsWith(prefix));
  return family?.[1] || canonicalSmellLabels.get(key) || sentenceCaseLabel(key, "Possible prose smell");
}

export function smellIssueLabels(item = {}) {
  const evidence = Array.isArray(item.evidence) ? item.evidence : [];
  const issueParts = String(item.judgment?.issue || "").split(/[,;|]+/).map((value) => value.trim()).filter(Boolean);
  const rawLabels = [
    ...issueParts,
    ...evidence.map((entry) => entry?.rule).filter(Boolean),
    ...evidence.filter((entry) => normalizeSmellKey(entry?.message).includes("oxford comma")).map(() => "Oxford comma"),
  ];
  const ignored = new Set(["Unreviewed local finding", "Possible prose smell"]);
  const labels = rawLabels.map(canonicalSmellLabel).filter((label) => label && !ignored.has(label));
  return [...new Set(labels.length ? labels : ["Possible prose smell"])];
}

export function smellIssueLabel(item = {}) {
  return smellIssueLabels(item).join(" · ");
}
