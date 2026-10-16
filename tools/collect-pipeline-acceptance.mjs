import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";

const baseURL = process.env.BOOKINATOR_ACCEPTANCE_URL || "http://127.0.0.1:4892";
const dataRoot = path.resolve(process.env.BOOKINATOR_ACCEPTANCE_DATA_DIR || "");
const bookId = process.env.BOOKINATOR_ACCEPTANCE_BOOK_ID || "";
const minimumAuthoredChapters = Number(process.env.BOOKINATOR_ACCEPTANCE_MIN_CHAPTERS || 2);
const output = path.resolve(process.env.BOOKINATOR_ACCEPTANCE_OUTPUT || "evidence/pipeline-acceptance/report.json");
assert.ok(process.env.BOOKINATOR_ACCEPTANCE_DATA_DIR, "Set BOOKINATOR_ACCEPTANCE_DATA_DIR to the isolated assay data root.");
assert.ok(bookId, "Set BOOKINATOR_ACCEPTANCE_BOOK_ID to the assayed book.");

const sha256 = (value) => createHash("sha256").update(value).digest("hex");
const json = async (file) => JSON.parse(await readFile(file, "utf8"));
const unresolvedSubjectTokens = (value) => {
  const tokens = new Set();
  const visit = (item) => {
    if (Array.isArray(item)) return item.forEach(visit);
    if (!item || typeof item !== "object") return;
    if (/^[A-Za-z]\d+$/.test(String(item.subject || ""))) tokens.add(String(item.subject));
    Object.values(item).forEach(visit);
  };
  visit(value);
  return [...tokens].sort();
};
const unsupportedKinshipClaims = (summary, source) => {
  const name = "[A-Z][A-Za-z'’-]*(?:\\s+[A-Z][A-Za-z'’-]*){0,3}";
  const relation = "son|daughter|mother|father|sister|brother|wife|husband|niece|nephew|ward";
  const pattern = new RegExp(`\\b(${name}),?\\s+(?:the\\s+)?(${relation})\\s+of\\s+(${name})\\b`, "g");
  const escape = (value) => value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const findings = [];
  for (const match of String(summary || "").matchAll(pattern)) {
    const [, subject, kinship, relative] = match;
    const supported = [
      new RegExp(`\\b${escape(subject)}\\b[\\s\\S]{0,320}\\b${kinship}\\b[\\s\\S]{0,320}\\b${escape(relative)}\\b`, "i"),
      new RegExp(`\\b${escape(relative)}\\b[\\s\\S]{0,320}\\b${kinship}\\b[\\s\\S]{0,320}\\b${escape(subject)}\\b`, "i"),
    ].some((candidate) => candidate.test(source));
    if (!supported) findings.push(match[0]);
  }
  return findings;
};
const library = await json(path.join(dataRoot, "library.json"));
const book = library.find((record) => record.id === bookId);
assert.ok(book?.manuscriptId, `Book ${bookId} is absent from the isolated library.`);
const artifactRoot = path.join(dataRoot, "books", book.manuscriptId);
const response = await fetch(`${baseURL}/api/books/${bookId}/pipeline`);
assert.equal(response.ok, true, `Pipeline endpoint failed with ${response.status}.`);
const pipeline = await response.json();
const limit = Number(pipeline.developmentAnalysisLimit || 0);
const authored = pipeline.chapters.filter((chapter) =>
  Number(chapter.sequence || chapter.number || 0) <= limit
  && String(chapter.title || "").toLowerCase() !== "front matter"
);

const checks = [];
const check = (id, passed, evidence) => checks.push({ id, status: passed ? "passed" : "failed", evidence });
check("checkpoint.locked", pipeline.status === "paused" && pipeline.phase === "development-checkpoint" && pipeline.developmentCheckpointLocked === true, {
  status: pipeline.status, phase: pipeline.phase, locked: pipeline.developmentCheckpointLocked === true, limit,
});
check("chapters.minimum", authored.length >= minimumAuthoredChapters, { completedSpecimens: authored.length, required: minimumAuthoredChapters });

const chapters = [];
for (const chapter of authored) {
  const sequence = Number(chapter.sequence || chapter.number || 0);
  const canonicalBytes = await readFile(path.join(artifactRoot, "chapters", `${String(sequence).padStart(4, "0")}.json`));
  const canonical = JSON.parse(canonicalBytes);
  const readingBytes = await readFile(path.join(artifactRoot, "chapter-readings", `${String(sequence).padStart(4, "0")}.json`));
  const reading = JSON.parse(readingBytes);
  const source = String(canonical.text || canonical.markdown || "");
  const anchors = [];
  const claims = [];
  const visit = (value) => {
    if (Array.isArray(value)) return value.forEach(visit);
    if (!value || typeof value !== "object") return;
    if (typeof value.claim === "string") claims.push(value.claim);
    if (value.evidenceAnchor && typeof value.evidenceAnchor.quote === "string") anchors.push(value.evidenceAnchor);
    Object.values(value).forEach(visit);
  };
  visit(reading.normalized);
  const exactAnchors = anchors.filter((anchor) => {
    const start = Number(anchor.characterStart);
    const end = Number(anchor.characterEnd);
    return Number.isInteger(start) && Number.isInteger(end) && source.slice(start, end) === anchor.quote;
  });
  const summary = reading.normalized?.summary || {};
  const dossier = reading.normalized?.dossier || {};
  const review = reading.normalized?.review || {};
  const complete = reading.status === "complete" && chapter.chapterReadingStatus === "complete";
  const projections = Boolean(String(summary.summary || "").trim() && Object.keys(dossier).length && Object.keys(review).length);
  const evidenceBound = anchors.length > 0 && exactAnchors.length === anchors.length;
  const cast = Array.isArray(reading.normalized?.cast) ? reading.normalized.cast : [];
  const castKeys = cast.map((entry) => String(entry.canonicalName || "").toLocaleLowerCase().replace(/[^a-z0-9]+/g, " ").trim()).filter(Boolean);
  const uniqueCast = new Set(castKeys);
  const probableDuplicateCast = [];
  for (let left = 0; left < castKeys.length; left += 1) {
    for (let right = left + 1; right < castKeys.length; right += 1) {
      const shorter = castKeys[left].length <= castKeys[right].length ? castKeys[left] : castKeys[right];
      const longer = shorter === castKeys[left] ? castKeys[right] : castKeys[left];
      if (shorter && longer.startsWith(`${shorter} `)) probableDuplicateCast.push([castKeys[left], castKeys[right]]);
    }
  }
  const incidentalCast = cast
    .filter((entry) => /^mentioned in context\b/i.test(String(entry.role || "")))
    .map((entry) => String(entry.canonicalName || ""));
  const castRoleGeneralizations = cast.filter((entry) => entry.roleEvidenceStatus === "unsupported-generalized");
  const castRolesEvidenceBound = castRoleGeneralizations.every((entry) => entry.role === "Participant mentioned in this chapter");
  const endingCoverage = summary.endingCoverage || {};
  const endingCovered = endingCoverage.covered === true && ["short-source", "late-fact-overlap"].includes(endingCoverage.reason);
  const semanticHygiene = endingCovered && castKeys.length === uniqueCast.size && probableDuplicateCast.length === 0 && castRolesEvidenceBound;
  const unresolvedSubjects = unresolvedSubjectTokens({summary, dossier});
  const unsupportedKinship = unsupportedKinshipClaims(summary.summary, source);
  const referentialIntegrity = unresolvedSubjects.length === 0 && unsupportedKinship.length === 0;
  const dimensions = review.dimensions && typeof review.dimensions === "object" ? Object.keys(review.dimensions) : [];
  const dimensionEvidenceComplete = dimensions.every((key) => {
    const dimension = review.dimensions[key] || {};
    if (dimension.applicable === false) return true;
    return Array.isArray(dimension.evidence)
      && dimension.evidence.length >= 1
      && dimension.evidence.length <= 3
      && dimension.evidence.every((quote) => source.includes(String(quote)));
  });
  const reviewStructured = ["no_material_concerns", "material_concerns_found"].includes(review.editorialVerdict)
    && dimensions.length === 10
    && dimensionEvidenceComplete;
  const consistency = reading.normalized?.consistency || {};
  const rejectedSummaryCandidates = Array.isArray(consistency.decisions)
    ? consistency.decisions.filter((item) => String(item.candidateId || "").startsWith("summary."))
    : [];
  const consistencyClosed = rejectedSummaryCandidates.length === 0 || consistency.summaryCorrectionApplied === true;
  check(`chapter.${sequence}.complete`, complete, { readingStatus: reading.status, chapterStatus: chapter.chapterReadingStatus, model: reading.model, durationSeconds: reading.durationSeconds });
  check(`chapter.${sequence}.projections`, projections, { summary: Boolean(String(summary.summary || "").trim()), dossier: Object.keys(dossier).length > 0, review: Object.keys(review).length > 0 });
  check(`chapter.${sequence}.anchors`, evidenceBound, { observed: anchors.length, exactInCanonicalSource: exactAnchors.length });
  check(`chapter.${sequence}.semantic-hygiene`, semanticHygiene, {
    endingCovered,
    endingReason: endingCoverage.reason || "missing",
    castEntries: castKeys.length,
    uniqueCanonicalCast: uniqueCast.size,
    probableDuplicateCast,
    incidentalCast,
    castRolesEvidenceBound,
    castRoleGeneralizations: castRoleGeneralizations.length,
  });
  check(`chapter.${sequence}.referential-integrity`, referentialIntegrity, {
    unresolvedSubjects,
    unsupportedKinshipClaims: unsupportedKinship,
  });
  check(`chapter.${sequence}.review-structure`, reviewStructured, {
    editorialVerdict: review.editorialVerdict || "missing",
    rubricDimensions: dimensions.length,
    applicableDimensionsHaveExactEvidence: dimensionEvidenceComplete,
  });
  check(`chapter.${sequence}.consistency-closure`, consistencyClosed, {
    rejectedSummaryCandidates: rejectedSummaryCandidates.map((item) => item.candidateId),
    summaryCorrectionApplied: consistency.summaryCorrectionApplied === true,
  });
  chapters.push({
    sequence,
    label: chapter.title,
    model: reading.model,
    durationSeconds: reading.durationSeconds,
    sourceSha256: sha256(canonicalBytes),
    artifactSha256: sha256(readingBytes),
    claims: claims.length,
    evidenceAnchors: anchors.length,
    exactEvidenceAnchors: exactAnchors.length,
    endingCovered,
    castEntries: castKeys.length,
    uniqueCanonicalCast: uniqueCast.size,
    probableDuplicateCast,
    incidentalCast,
    castRolesEvidenceBound,
    castRoleGeneralizations: castRoleGeneralizations.length,
    unresolvedSubjects,
    unsupportedKinshipClaims: unsupportedKinship,
    rubricDimensions: dimensions.length,
    applicableDimensionsHaveExactEvidence: dimensionEvidenceComplete,
    consistencyClosed,
  });
}

const failures = checks.filter((item) => item.status === "failed");
const report = {
  schema: "bookinator.pipeline-acceptance.v1",
  observedAt: new Date().toISOString(),
  subject: { bookId, title: book.title, source: "public-domain local fixture", developmentLimit: limit },
  boundary: { baseURL, dataRootKind: "isolated-disposable", minimumAuthoredChapters, rawManuscriptRetained: false },
  summary: { status: failures.length ? "failed" : "passed", checks: checks.length, passed: checks.length - failures.length, failed: failures.length },
  checks,
  chapters,
  limitations: [
    "Exact source-anchor matching checks provenance integrity, not whether every interpretation is persuasive.",
    "A local public-domain specimen does not represent every manuscript format, language, model, or hardware profile.",
    "Human editorial judgment remains required for usefulness, omissions, tone, and commercial readiness.",
  ],
};
await mkdir(path.dirname(output), { recursive: true });
await writeFile(output, `${JSON.stringify(report, null, 2)}\n`);
console.log(`Bookinator pipeline acceptance ${report.summary.status}: ${report.summary.passed}/${report.summary.checks} checks · ${output}`);
if (failures.length) process.exitCode = 1;
