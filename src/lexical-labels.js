export function normalizeLexicalKey(value) {
  return String(value || "").normalize("NFKD").toLocaleLowerCase()
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/[_\-–—/]+/g, " ")
    .replace(/[^a-z0-9 ]+/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

export function sentenceCaseLabel(value, fallback = "Unclassified") {
  const words = normalizeLexicalKey(value);
  return words ? `${words.charAt(0).toLocaleUpperCase()}${words.slice(1)}` : fallback;
}
