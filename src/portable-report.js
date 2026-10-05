import { smellIssueLabel } from "./smell-labels.js?v=canonical-labels-170";
import { sentenceCaseLabel } from "./lexical-labels.js?v=canonical-labels-170";

const text = (value) => String(value ?? "").trim();
const number = (value) => Number.isFinite(Number(value)) ? Number(value) : 0;
const list = (value) => Array.isArray(value) ? value : [];
const heading = (value) => text(value).replace(/^#{1,6}\s+/, "");
const fixedPagination = (book) => text(book?.sourceFormat).toLocaleUpperCase() === "PDF" || (!text(book?.sourceFormat) && text(book?.sourceFilename).toLocaleLowerCase().endsWith(".pdf"));
const tagLabel = (value) => {
  return sentenceCaseLabel(value, "Other");
};

export function reportExportFilename(book, extension, {section = "", date = new Date()} = {}) {
  const slug = (value, fallback) => text(value)
    .toLocaleLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "") || fallback;
  const dateStamp = [date.getFullYear(), String(date.getMonth() + 1).padStart(2, "0"), String(date.getDate()).padStart(2, "0")].join("-");
  const parts = ["bookinator", slug(book?.title, "book")];
  if (section) parts.push(slug(section, "report"));
  return `${parts.join("-")}-${dateStamp}.${slug(extension, "html")}`;
}
const BOOKINATOR_LICENSE = `Business Source License 1.1

Parameters

Licensor:             Randal
Licensed Work:        Bookinator 0.1.0
                      The Licensed Work is (c) 2026 Randal.
Additional Use Grant: You may make production use of the Licensed Work for personal, educational, research, or internal business purposes, provided that you do not use the Licensed Work to provide a commercial hosted or managed service to third parties and do not sell or distribute the Licensed Work as part of a competing commercial product.
Change Date:          September 24, 2030
Change License:       GPL-3.0-or-later

For information about alternative licensing arrangements for the Licensed Work, open an issue at https://github.com/randal-cox/bookinator.

Notice

Business Source License 1.1

License text copyright © 2017 MariaDB Corporation Ab, All Rights Reserved.
"Business Source License" is a trademark of MariaDB Corporation Ab.

Terms

The Licensor hereby grants you the right to copy, modify, create derivative works, redistribute, and make non-production use of the Licensed Work. The Licensor may make an Additional Use Grant, above, permitting limited production use.

Effective on the Change Date, or the fourth anniversary of the first publicly available distribution of a specific version of the Licensed Work under this License, whichever comes first, the Licensor hereby grants you rights under the terms of the Change License, and the rights granted in the paragraph above terminate.

If your use of the Licensed Work does not comply with the requirements currently in effect as described in this License, you must purchase a commercial license from the Licensor, its affiliated entities, or authorized resellers, or you must refrain from using the Licensed Work.

All copies of the original and modified Licensed Work, and derivative works of the Licensed Work, are subject to this License. This License applies separately for each version of the Licensed Work and the Change Date may vary for each version.

You must conspicuously display this License on each original or modified copy of the Licensed Work. If you receive the Licensed Work in original or modified form from a third party, the terms and conditions set forth in this License apply to your use of that work.

Any use of the Licensed Work in violation of this License will automatically terminate your rights under this License for the current and all other versions of the Licensed Work.

This License does not grant you any right in any trademark or logo of Licensor or its affiliates (provided that you may use a trademark or logo of Licensor as expressly required by this License).

TO THE EXTENT PERMITTED BY APPLICABLE LAW, THE LICENSED WORK IS PROVIDED ON AN “AS IS” BASIS. LICENSOR HEREBY DISCLAIMS ALL WARRANTIES AND CONDITIONS, EXPRESS OR IMPLIED, INCLUDING (WITHOUT LIMITATION) WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE, NON-INFRINGEMENT, AND TITLE.

MariaDB hereby grants you permission to use this License’s text to license your works, and to refer to it using the trademark “Business Source License”, as long as you comply with the Covenants of Licensor below.

Covenants of Licensor

In consideration of the right to use this License’s text and the “Business Source License” name and trademark, Licensor covenants to MariaDB, and to all other recipients of the licensed work to be provided by Licensor:

1. To specify as the Change License the GPL Version 2.0 or any later version, or a license that is compatible with GPL Version 2.0 or a later version, where “compatible” means that software provided under the Change License can be included in a program with software provided under GPL Version 2.0 or a later version. Licensor may specify additional Change Licenses without limitation.

2. To either: (a) specify an additional grant of rights to use that does not impose any additional restriction on the right granted in this License, as the Additional Use Grant; or (b) insert the text “None”.

3. To specify a Change Date.

4. Not to modify this License in any other way.`;

function safeIcon(icon, title) {
  if (icon?.kind === "image" && /^data:image\/(?:png|jpeg|webp|gif);base64,/i.test(text(icon.value))) {
    return {kind: "image", value: text(icon.value)};
  }
  if (icon?.kind === "unicode" && text(icon.value)) return {kind: "unicode", value: text(icon.value).slice(0, 8)};
  return {kind: "unicode", value: text(title).slice(0, 1).toLocaleUpperCase() || "B"};
}

function reportableSmells(chapter) {
  return list(chapter?.smell?.candidates)
    .filter((item) => item?.userStatus === "reported" || (["report", "keep"].includes(item?.judgment?.verdict) && item?.userStatus !== "dismissed"))
    .map((item) => ({
      id: text(item.id) || `smell-${number(chapter.sequence || chapter.number)}-${number(item.characterStart)}`,
      issue: smellIssueLabel(item),
      reason: text(item.judgment?.reason) || text(item.evidence?.[0]?.message) || "This sentence deserves editorial attention.",
      severity: ["low", "medium", "high"].includes(text(item.judgment?.severity).toLocaleLowerCase()) ? text(item.judgment.severity).toLocaleLowerCase() : "medium",
      sentence: text(item.sentence),
      detectors: list(item.detectors).map(text).filter(Boolean),
      chapter: number(chapter.sequence || chapter.number),
    }));
}

function connectionIndex(chunks, key) {
  const groups = new Map();
  list(chunks).forEach((chunk) => {
    if (chunk?.dossierStatus !== "complete") return;
    list(chunk?.dossier?.[key]).forEach((raw) => {
      const value = text(raw);
      if (!value) return;
      const name = value.split(/\s+(?:-|—|:)\s+/)[0].trim() || value;
      const normalized = name.toLocaleLowerCase().replace(/[^\p{L}\p{N}]+/gu, " ").trim();
      const current = groups.get(normalized) || {name, mentions: 0, chapters: new Set()};
      current.mentions += 1;
      const chapter = number(chunk.chapterSequence);
      if (chapter) current.chapters.add(chapter);
      groups.set(normalized, current);
    });
  });
  return [...groups.values()]
    .map((item) => ({name: item.name, mentions: item.mentions, chapters: [...item.chapters].sort((a, b) => a - b)}))
    .sort((a, b) => b.mentions - a.mentions || a.name.localeCompare(b.name));
}

function stageDuration(stage, pipeline) {
  const direct = Number(stage?.durationSeconds);
  if (Number.isFinite(direct) && direct >= 0) return direct;
  const sum = (items, field) => list(items).reduce((total, item) => total + (Number(item?.[field]) || 0), 0);
  if (stage?.id === "summaries") return sum(pipeline.chapters, "durationSeconds");
  if (stage?.id === "dossiers") return sum(pipeline.chunks, "dossierDurationSeconds");
  if (stage?.id === "emotions") return sum(pipeline.chapters, "emotionDurationSeconds");
  if (stage?.id === "tags") return sum(pipeline.chapters, "tagDurationSeconds");
  if (stage?.id === "smells") return sum(pipeline.chapters, "smellDurationSeconds");
  if (stage?.startedAt && stage?.completedAt) {
    const elapsed = (new Date(stage.completedAt) - new Date(stage.startedAt)) / 1000;
    if (Number.isFinite(elapsed) && elapsed >= 0) return elapsed;
  }
  return 0;
}

function totalProjectSeconds(pipeline) {
  const preparation = list(pipeline.stages).filter((stage) => ["extraction", "structure", "chapter-archive", "chunking"].includes(stage.id)).reduce((total, stage) => total + stageDuration(stage, pipeline), 0);
  const stageIds = ["summaries", "dossiers", "emotions", "tags", "smells"];
  return preparation + stageIds.reduce((total, id) => total + stageDuration({id}, pipeline), 0);
}

export function buildPortableReportManifest(pipeline = {}, book = {}, options = {}) {
  const hasPages = fixedPagination(book);
  const chapters = list(pipeline.chapters)
    .filter((chapter) => heading(chapter.title).toLocaleLowerCase() !== "front matter")
    .map((chapter) => ({
      id: `chapter-${number(chapter.sequence || chapter.number)}`,
      sequence: number(chapter.sequence || chapter.number),
      heading: heading(chapter.title) || `Chapter ${number(chapter.sequence || chapter.number)}`,
      title: heading(chapter.chapterTitle),
      pages: hasPages ? {start: number(chapter.pageStart), end: number(chapter.pageEnd)} : {start: 0, end: 0},
      wordCount: number(chapter.wordCount),
      status: text(chapter.status) || "unknown",
      summary: text(chapter.summary),
      establishes: list(chapter.keyPoints).map(text).filter(Boolean),
      questions: list(chapter.newQuestions).map(text).filter(Boolean),
      emotion: chapter.emotionStatus === "complete" && chapter.emotion?.distribution
        ? Object.fromEntries(Object.entries(chapter.emotion.distribution).map(([key, value]) => [text(key), number(value)]).filter(([key]) => key))
        : {},
      tags: chapter.tagStatus === "complete"
        ? list(chapter.tag?.signals).filter((signal) => number(signal?.score) >= .25).map((signal) => ({id: text(signal.id), label: tagLabel(signal.id), family: text(signal.family) || "other", familyLabel: tagLabel(signal.family || "other"), score: number(signal.score)})).filter((signal) => signal.id)
        : [],
      llmReview: chapter.llmReviewStatus === "complete" && chapter.llmReview
        ? {
            editorialVerdict: text(chapter.llmReview.editorialVerdict),
            editorialSummary: text(chapter.llmReview.editorialSummary || chapter.llmReview.chapterAssessment),
            editorialRationale: text(chapter.llmReview.editorialRationale),
            strengths: list(chapter.llmReview.editorialStrengths).map(text).filter(Boolean),
            commercialStrengths: list(chapter.llmReview.commercialStrengths).map(text).filter(Boolean),
            commercialRisks: list(chapter.llmReview.commercialRisks).map(text).filter(Boolean),
            likelyReaders: list(chapter.llmReview.likelyReaders).map(text).filter(Boolean),
            dimensions: Object.fromEntries(Object.entries(chapter.llmReview.dimensions || {}).map(([key, item]) => [text(key), {score: number(item?.score), applicable: item?.applicable !== false}]).filter(([key]) => key)),
          }
        : null,
      smells: reportableSmells(chapter),
    }));
  const stages = list(pipeline.stages).filter((stage) => text(stage.id).toLocaleLowerCase() !== "prose" && text(stage.label).toLocaleLowerCase() !== "prose").map((stage) => ({
    id: text(stage.id),
    label: text(stage.label) || heading(stage.id),
    status: text(stage.status) || "unknown",
    model: text(stage.model),
    detail: text(stage.detail),
    durationSeconds: stageDuration(stage, pipeline),
  })).filter((stage) => stage.id);
  const tracker = pipeline.questionTracker || {};
  const questions = list(tracker.items).map((item, index) => ({
    id: `question-${index + 1}`,
    question: text(item.question || item.canonical_question),
    status: ["resolved", "possible", "open"].includes(text(item.status).toLocaleLowerCase()) ? text(item.status).toLocaleLowerCase() : "open",
    triggerChapter: number(item.triggerChapter || item.trigger_chapter),
    resolutionChapter: number(item.resolutionChapter || item.resolution_chapter),
    answer: text(item.answer),
    confidence: text(item.confidence) || "low",
  })).filter((item) => item.question);
  const smells = chapters.flatMap((chapter) => chapter.smells.map((item) => ({...item, chapterHeading: chapter.heading, chapterTitle: chapter.title})));
  const reviewerComments = list(options.annotations)
    .filter((item) => item?.status !== "archived")
    .map((item, index) => {
      const categories = list(item.categories).length ? list(item.categories) : [item.category];
      const quote = text(item.quote);
      return {
        id: text(item.id) || `reviewer-comment-${index + 1}`,
        chapterSequence: number(item.chapterSequence),
        chapterHeading: heading(item.chapterLabel) || `Chapter ${number(item.chapterSequence)}`,
        chapterTitle: heading(item.chapterTitle),
        pages: hasPages ? {start: number(item.pageStart), end: number(item.pageEnd)} : {start: 0, end: 0},
        quote: quote.length > 600 ? `${quote.slice(0, 597)}...` : quote,
        comment: text(item.comment),
        categories: [...new Set(categories.map(text).filter(Boolean))],
        priority: ["low", "normal", "high"].includes(text(item.priority)) ? text(item.priority) : "normal",
        status: "active",
        origin: item.origin?.kind === "llm-review-proposal" ? {kind: "llm-review-proposal", model: text(item.origin.model), promptVersion: text(item.origin.promptVersion)} : null,
      };
    })
    .filter((item) => item.comment);
  const savedReviewerSignoff = pipeline.reviewerSignoff || {};
  const reviewerSignoff = savedReviewerSignoff.status === "complete"
    ? {
        status: "complete",
        reviewerName: text(savedReviewerSignoff.reviewerName),
        notes: text(savedReviewerSignoff.notes),
        completedAt: text(savedReviewerSignoff.completedAt),
      }
    : {status: "open", reviewerName: "", notes: "", completedAt: ""};
  const completedChapters = chapters.filter((chapter) => chapter.status === "complete" && chapter.summary).length;
  const selected = new Set(list(options.sections).map(text).filter(Boolean));
  const synthesis = pipeline.wholeBookLlmReview || {};
  const llmSynthesisAvailable = synthesis.status === "complete" && Boolean(text(synthesis.overallAssessment));
  const dossierSource = pipeline.wholeBookDossier || {};
  const dossierAvailable = dossierSource.status === "complete" && Boolean(text(dossierSource.synopsis || dossierSource.summary));
  const defaultSections = ["overview", "chapter-length", "chapters"];
  if (dossierAvailable) defaultSections.push("dossier");
  defaultSections.push("reviewer", "questions", "connections", "emotions", "tags");
  if (llmSynthesisAvailable) defaultSections.push("llm-review");
  defaultSections.push("smells", "method");
  const include = (id) => selected.size ? selected.has(id) : defaultSections.includes(id);
  const reviewItems = (items, fields) => list(items).map((item) => Object.fromEntries(fields.map((field) => [field, text(item?.[field])]))).filter((item) => Object.values(item).some(Boolean));
  const wholeBookLlmReview = include("llm-review") && llmSynthesisAvailable ? {
    overallAssessment: text(synthesis.overallAssessment),
    strengths: reviewItems(synthesis.strengths, ["title", "synthesis", "significance"]),
    risks: reviewItems(synthesis.risks, ["title", "synthesis", "significance"]),
    editorialPriorities: reviewItems(synthesis.editorialPriorities, ["title", "rationale", "scope", "priority"]),
    likelyReaders: reviewItems(synthesis.likelyReaders, ["reader", "fit", "caution"]),
    commercialPositioning: text(synthesis.commercialPositioning),
    sourceChapterCount: number(synthesis.sourceChapterCount),
  } : null;
  const wholeBookDossier = include("dossier") && dossierAvailable ? {
    synopsis: text(dossierSource.synopsis || dossierSource.summary),
    facts: list(dossierSource.facts).map(text).filter(Boolean),
    events: list(dossierSource.events).map(text).filter(Boolean),
    entities: list(dossierSource.entities).map(text).filter(Boolean),
    locations: list(dossierSource.locations).map(text).filter(Boolean),
    currentTimes: list(dossierSource.current_times).map(text).filter(Boolean),
    questions: list(dossierSource.questions).map(text).filter(Boolean),
    promises: list(dossierSource.promises).map(text).filter(Boolean),
    timelineObservations: list(dossierSource.timeline_observations).map(text).filter(Boolean),
    contradictions: list(dossierSource.contradictions).map(text).filter(Boolean),
  } : null;
  return {
    schema: "bookinator-report-v1",
    export: {
      createdAt: new Date().toISOString(),
      sourceFingerprint: text(pipeline.sourceFingerprint || pipeline.manuscriptFingerprint),
      freshness: list(stages).some((stage) => stage.status === "stale") ? "stale" : "current",
      networkRequired: false,
      totalAnalysisSeconds: totalProjectSeconds(pipeline),
      sections: selected.size ? [...selected] : defaultSections,
    },
    book: {
      title: text(book.title) || "Untitled",
      author: text(book.author) || "Author not specified",
      icon: safeIcon(book.icon, book.title),
      chapterCount: chapters.length,
      wordCount: chapters.reduce((total, chapter) => total + chapter.wordCount, 0),
      fixedPagination: hasPages,
    },
    completeness: {
      chapterSummaries: {complete: completedChapters, total: chapters.length},
      questions: {status: text(tracker.status) || "unavailable", count: questions.length},
      smells: {count: smells.length},
      reviewerComments: {count: reviewerComments.length},
      reviewerSignoff: {status: reviewerSignoff.status},
      llmReview: {status: llmSynthesisAvailable ? "complete" : "unavailable", chapters: chapters.filter((chapter) => chapter.llmReview).length},
      dossier: {status: dossierAvailable ? "complete" : "unavailable"},
      stages: stages.map(({id, label, status}) => ({id, label, status})),
    },
    overview: {
      summary: include("overview") ? text(pipeline.wholeBookSummary?.summary) : "",
      dossierSynopsis: include("overview") ? text(pipeline.wholeBookDossier?.synopsis) : "",
    },
    chapters: chapters.map((chapter) => ({
      ...chapter,
      summary: include("chapters") ? chapter.summary : "",
      establishes: include("chapters") ? chapter.establishes : [],
      questions: include("chapters") ? chapter.questions : [],
      emotion: include("emotions") ? chapter.emotion : {},
      tags: include("tags") ? chapter.tags : [],
      llmReview: include("llm-review") ? chapter.llmReview : null,
      smells: include("smells") ? chapter.smells : [],
    })),
    questions: include("questions") ? questions : [],
    reviewerComments: include("reviewer") ? reviewerComments : [],
    reviewerSignoff: include("reviewer") ? reviewerSignoff : {status: "open", reviewerName: "", notes: "", completedAt: ""},
    connections: {
      entities: include("connections") ? connectionIndex(pipeline.chunks, "entities") : [],
      locations: include("connections") ? connectionIndex(pipeline.chunks, "locations") : [],
    },
    wholeBookLlmReview,
    wholeBookDossier,
    smells: include("smells") ? smells : [],
    provenance: include("method") ? stages : [],
  };
}

export function auditPortableReport({manifest, artifact = "", pipeline = {}} = {}) {
  if (!manifest || manifest.schema !== "bookinator-report-v1") throw new Error("The report manifest is missing or invalid.");
  const forbiddenKeys = new Set(["text", "markdown", "sourcetext", "sourcepath", "manuscriptpath", "rawresponse", "rawmodelresponse", "prompt", "messages"]);
  const violations = [];
  const inspect = (value, path = "report") => {
    if (Array.isArray(value)) return value.forEach((item, index) => inspect(item, `${path}[${index}]`));
    if (!value || typeof value !== "object") return;
    Object.entries(value).forEach(([key, child]) => {
      if (forbiddenKeys.has(key.toLocaleLowerCase())) violations.push(`${path}.${key}`);
      inspect(child, `${path}.${key}`);
    });
  };
  inspect(manifest);
  const serialized = JSON.stringify(manifest);
  const sourceValues = [];
  const collectSources = (value) => {
    if (Array.isArray(value)) return value.forEach(collectSources);
    if (!value || typeof value !== "object") return;
    Object.entries(value).forEach(([key, child]) => {
      if (["text", "markdown", "sourceText", "rawResponse", "rawModelResponse"].includes(key) && typeof child === "string" && child.length >= 160) sourceValues.push(child);
      else collectSources(child);
    });
  };
  collectSources(pipeline);
  if (sourceValues.some((source) => serialized.includes(source))) violations.push("report contains source manuscript or raw model output");
  const artifactText = typeof artifact === "string" ? artifact : "";
  if (artifactText) {
    if (sourceValues.some((source) => artifactText.includes(source))) violations.push("artifact contains source manuscript or raw model output");
    if (/(?:src|href)=["'](?:https?:)?\/\//i.test(artifactText.replace(/<a\b[^>]*>[\s\S]*?<\/a>/gi, ""))) violations.push("artifact contains a remote embedded dependency");
    if (/(?:file:\/\/|https?:\/\/(?:localhost|127\.0\.0\.1))/i.test(artifactText)) violations.push("artifact contains a local filesystem or server URL");
  }
  if (manifest.export?.networkRequired !== false) violations.push("report is not marked offline");
  if (violations.length) throw new Error(`Privacy audit failed: ${[...new Set(violations)].join("; ")}.`);
  return {ok: true, checks: ["allowlisted manifest", "source text excluded", "raw model output excluded", "no local URLs", "no remote embedded dependencies"]};
}

function jsonForHtml(value) {
  return JSON.stringify(value).replace(/&/g, "\\u0026").replace(/</g, "\\u003c").replace(/>/g, "\\u003e").replace(/\u2028/g, "\\u2028").replace(/\u2029/g, "\\u2029");
}

export function buildPortableReportHtml(manifest) {
  const data = jsonForHtml(manifest);
  const license = jsonForHtml(BOOKINATOR_LICENSE);
  const documentTitle = ["Bookinator", manifest.book.title, manifest.book.author]
    .map((value) => String(value || "").trim())
    .filter(Boolean)
    .join(" - ")
    .replace(/[&<>]/g, (character) => ({"&": "&amp;", "<": "&lt;", ">": "&gt;"})[character]);
  return `<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light"><title>${documentTitle}</title>
<style>
:root{--ink:#10264a;--copy:#334b6a;--muted:#667995;--line:#cfdaea;--paper:#fbfcfe;--blue:#2863c7;--blue-soft:#edf5ff;--violet:#7550b8;--violet-soft:#f6f1fc;--amber:#9a6810;--amber-soft:#fff7df;--green:#28765d;--rail:18rem}*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;color:var(--copy);background:var(--paper);font:16px/1.58 ui-sans-serif,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}button,input{font:inherit}a{color:var(--blue)}.skip{position:fixed;left:1rem;top:-5rem;z-index:9;padding:.7rem 1rem;background:#fff;border:2px solid var(--blue);border-radius:.5rem}.skip:focus{top:1rem}.rail{position:fixed;inset:0 auto 0 0;width:var(--rail);padding:1.6rem 1.2rem;background:#10264a;color:#fff;overflow:auto}.brand{display:flex;align-items:center;gap:.8rem;margin-bottom:1.6rem}.brand-mark{width:2.5rem;height:3.25rem;display:grid;place-items:center;overflow:hidden;background:#dce9fb;color:#10264a;border-radius:.45rem;font:700 1.35rem Georgia,serif}.brand-mark img{width:100%;height:100%;object-fit:cover}.brand strong{font:700 1.2rem Georgia,serif}.brand small{display:block;color:#bcd0eb}.search{width:100%;padding:.72rem .8rem;color:#10264a;background:#fff;border:2px solid transparent;border-radius:.55rem}.search:focus{outline:0;border-color:#75a9ef}.rail nav{margin-top:1.2rem;display:grid;gap:.15rem}.rail nav a{padding:.52rem .65rem;color:#d9e7f8;text-decoration:none;border-radius:.4rem}.rail nav a:hover,.rail nav a:focus{color:#fff;background:#ffffff18;outline:0}.rail footer{margin-top:2rem;padding-top:1rem;border-top:1px solid #ffffff28;color:#aec4e1;font-size:.82rem}.page{margin-left:var(--rail)}.hero{min-height:19rem;padding:4.6rem clamp(2rem,7vw,7.5rem) 3.4rem;background:linear-gradient(112deg,#eaf3ff 0 56%,#f7f2fc 56%);border-bottom:1px solid var(--line)}.bookline{display:flex;align-items:center;gap:1.25rem}.book-icon{width:4.8rem;height:6.1rem;flex:none;display:grid;place-items:center;overflow:hidden;color:#fff;background:var(--ink);border-radius:.65rem;box-shadow:0 14px 30px #10264a20;font:700 2.2rem Georgia,serif}.book-icon img{width:100%;height:100%;object-fit:cover}.hero h1{max-width:18ch;margin:0;color:var(--ink);font:700 clamp(2.5rem,6vw,5.2rem)/.98 Georgia,serif;letter-spacing:-.035em}.hero .author{margin:.75rem 0 0;color:#526a88;font-size:1.16rem}.hero-note{max-width:48rem;margin:2.2rem 0 0;padding-top:1.25rem;border-top:1px solid #a9bfdc}.hero-note strong{color:var(--ink)}main{max-width:76rem;padding:2.8rem clamp(1.5rem,5vw,5rem) 7rem}.section{scroll-margin-top:1rem;margin-bottom:4.5rem}.section-heading{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:1rem;align-items:end;margin-bottom:1.5rem;padding-bottom:.75rem;border-bottom:2px solid var(--ink)}h2,h3{color:var(--ink);font-family:Georgia,serif}.section h2{margin:0;font-size:2rem}.section-heading p{margin:0;color:var(--muted)}.lede{max-width:52rem;font:1.26rem/1.7 Georgia,serif;color:#263f61}.ledger{display:grid;grid-template-columns:repeat(auto-fit,minmax(10rem,1fr));gap:.8rem;margin:1.5rem 0}.ledger div{padding:1rem 1.1rem;background:#fff;border:1px solid var(--line);border-top:4px solid var(--blue);border-radius:.45rem}.ledger strong{display:block;color:var(--ink);font-size:1.5rem}.status{display:inline-flex;align-items:center;padding:.22rem .58rem;border-radius:99rem;background:var(--blue-soft);color:#245da9;font-size:.78rem;font-weight:750}.status.open,.status.high{background:var(--amber-soft);color:#805407}.status.resolved,.status.complete{background:#e7f5ef;color:var(--green)}.status.possible,.status.medium{background:var(--violet-soft);color:var(--violet)}.chapter-list,.finding-list,.question-list{display:grid;gap:.8rem}.card{background:#fff;border:1px solid var(--line);border-radius:.55rem}.card>summary{cursor:pointer;list-style:none;display:grid;grid-template-columns:auto minmax(0,1fr) auto;gap:.9rem;align-items:center;padding:1rem 1.15rem}.card>summary::-webkit-details-marker{display:none}.number{width:2.25rem;height:2.25rem;display:grid;place-items:center;border-radius:50%;color:var(--blue);background:var(--blue-soft);font-weight:800}.card>summary strong{display:block;color:var(--ink)}.card>summary small{color:var(--muted)}.card[open]>summary{border-bottom:1px solid var(--line)}.card-body{padding:1.15rem 1.35rem 1.45rem}.card-body p{max-width:72ch;margin-top:0}.facts{display:grid;grid-template-columns:repeat(auto-fit,minmax(16rem,1fr));gap:1rem}.facts section{padding:1rem;background:#f6f9fd;border-radius:.4rem}.facts h4{margin:0 0 .5rem;color:var(--ink)}.facts ul{margin:0;padding-left:1.2rem}.question{padding:1.15rem 1.25rem;border-left:5px solid var(--violet)}.question h3{margin:.25rem 0 .5rem;font-size:1.13rem}.question p{margin:.3rem 0}.connection-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:1rem}.connection-grid section{background:#fff;border:1px solid var(--line);border-radius:.55rem;overflow:hidden}.connection-grid h3{margin:0;padding:1rem 1.1rem;background:var(--blue-soft)}.connection-grid ol{list-style:none;margin:0;padding:0}.connection-grid li{display:flex;justify-content:space-between;gap:1rem;padding:.7rem 1.1rem;border-top:1px solid #e5ebf3}.connection-grid small{color:var(--muted)}.chapter-length-list{display:grid;gap:.3rem;padding:1rem;background:#fff;border:1px solid var(--line);border-radius:.55rem}.chapter-length-row{display:grid;grid-template-columns:2.4rem minmax(10rem,1fr) 6.5rem;gap:.75rem;align-items:center;min-height:2.6rem;padding:.25rem .4rem;border-radius:.35rem}.chapter-length-row:nth-child(even){background:#f7faff}.chapter-length-row strong{display:grid;place-items:center;width:2rem;height:2rem;color:#fff;background:var(--blue);border-radius:50%;font-size:.78rem}.chapter-length-track{height:.7rem;overflow:hidden;background:#e1eaf4;border-radius:99rem}.chapter-length-track i{display:block;width:var(--chapter-length);height:100%;background:#356fae;border-radius:inherit}.chapter-length-row small{text-align:right;color:var(--muted);font-weight:750}.emotion-row{display:grid;grid-template-columns:minmax(9rem,15rem) 1fr;gap:1rem;align-items:center;padding:.7rem 0;border-bottom:1px solid #e2e9f2}.emotion-bars{display:flex;height:1.8rem;overflow:hidden;border-radius:.3rem;background:#edf1f6}.emotion-bars span{min-width:2rem;display:grid;place-items:center;padding:0 .4rem;color:#fff;background:var(--emotion);font-size:.7rem;font-weight:800}.finding{padding:1.1rem 1.25rem;border-left:5px solid var(--amber)}.finding h3{margin:0 0 .35rem;font-size:1.1rem}.finding blockquote{margin:.8rem 0 0;padding:.8rem 1rem;background:var(--amber-soft);border-radius:.35rem;font-family:Georgia,serif}.method-table{width:100%;border-collapse:collapse;background:#fff}.method-table th,.method-table td{padding:.75rem;text-align:left;border-bottom:1px solid var(--line)}.method-table th{color:var(--ink)}.empty{padding:1.2rem;color:var(--muted);background:#f4f7fb;border:1px dashed #b8c7da;border-radius:.5rem}[hidden]{display:none!important}.report-footer{padding:2rem clamp(1.5rem,5vw,5rem);color:#d6e4f5;background:var(--ink)}.report-footer strong{font-family:Georgia,serif}.report-footer a{color:#fff}@media(max-width:760px){:root{--rail:0px}.rail{position:relative;width:auto}.rail nav{grid-template-columns:repeat(2,minmax(0,1fr))}.page{margin:0}.hero{padding:2.5rem 1.4rem}.hero h1{font-size:2.7rem}.connection-grid{grid-template-columns:1fr}.section-heading{grid-template-columns:1fr}.chapter-length-row{grid-template-columns:2.2rem minmax(5rem,1fr) 5.5rem}.emotion-row{grid-template-columns:1fr}.method-table{display:block;overflow:auto}}@media print{.rail{display:none}.page{margin:0}.hero{min-height:0;padding:2rem}.section{break-inside:avoid}.card>summary{display:block}.card:not([open])>.card-body{display:block}.report-footer{background:#fff;color:var(--copy)}a{color:inherit}}@media(prefers-reduced-motion:reduce){html{scroll-behavior:auto}}
</style><style>
.emotion-profile{margin-bottom:2rem;padding:1rem;background:var(--violet-soft);border:1px solid #d9caee;border-radius:.6rem}.emotion-profile h3{margin:.1rem 0 .8rem}.emotion-profile-row{display:grid;grid-template-columns:minmax(8rem,1fr) auto;gap:.35rem 1rem;padding:.65rem .75rem;background:#fff;border-top:1px solid #e5daf3}.emotion-profile-row:first-of-type{border-top:0}.emotion-profile-row strong{color:var(--ink)}.emotion-profile-row small{color:var(--muted)}.emotion-profile-track{grid-column:1/-1;height:.45rem;overflow:hidden;background:#e8e4ee;border-radius:99rem}.emotion-profile-track i{display:block;width:var(--emotion-average);height:100%;background:var(--emotion);border-radius:inherit}
.tag-profile{padding:1rem;background:var(--blue-soft);border:1px solid #c7d9ef;border-radius:.6rem}.tag-profile-row{display:grid;grid-template-columns:minmax(10rem,1fr) auto;gap:.35rem 1rem;padding:.75rem;background:#fff;border-top:1px solid #dce6f2}.tag-profile-row:first-child{border-top:0}.tag-profile-row strong{color:var(--ink)}.tag-profile-row small{color:var(--muted)}.tag-profile-track{grid-column:1/-1;height:.48rem;overflow:hidden;background:#e1eaf4;border-radius:99rem}.tag-profile-track i{display:block;width:var(--tag-frequency);height:100%;background:var(--blue);border-radius:inherit}
.llm-synthesis{display:grid;gap:1rem}.llm-synthesis-overall{padding:1.35rem 1.5rem;background:var(--violet-soft);border-left:6px solid var(--violet);border-radius:.55rem}.llm-synthesis-overall strong{display:block;margin-bottom:.35rem;color:var(--violet);font-size:.76rem;text-transform:uppercase;letter-spacing:.07em}.llm-synthesis-overall p{margin:0;color:var(--ink);font:1.25rem/1.6 Georgia,serif}.llm-synthesis-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:1rem}.llm-synthesis-grid>section{padding:1rem 1.1rem;background:#fff;border:1px solid var(--line);border-radius:.55rem}.llm-synthesis-grid h3{margin:.1rem 0 .8rem}.llm-synthesis-grid article{padding:.7rem 0;border-top:1px solid #e3e9f2}.llm-synthesis-grid article:first-of-type{border-top:0}.llm-synthesis-grid article strong,.llm-synthesis-grid article span,.llm-synthesis-grid article small{display:block}.llm-synthesis-grid article span{margin-top:.2rem}.llm-synthesis-grid article small{margin-top:.25rem;color:var(--muted)}.llm-positioning{padding:1.1rem 1.25rem;background:var(--blue-soft);border-radius:.55rem}.llm-positioning strong{color:var(--blue)}.llm-positioning p{margin:.35rem 0 0}.llm-profile{display:grid;gap:.4rem}.llm-profile-row{display:grid;grid-template-columns:minmax(11rem,1fr) auto;gap:.35rem 1rem;padding:.7rem .8rem;background:#fff;border:1px solid var(--line);border-radius:.4rem}.llm-profile-row strong{color:var(--ink)}.llm-profile-track{grid-column:1/-1;height:.48rem;overflow:hidden;background:#e1e7ef;border-radius:99rem}.llm-profile-track i{display:block;width:var(--review-score);height:100%;background:var(--review-color);border-radius:inherit}.llm-chapter-conclusions{display:grid;gap:.7rem;margin-top:1.5rem}.llm-chapter-conclusions details{background:#fff;border:1px solid var(--line);border-radius:.5rem}.llm-chapter-conclusions summary{cursor:pointer;padding:.85rem 1rem;color:var(--ink);font-weight:750}.llm-chapter-conclusions details>div{padding:0 1rem 1rem}.llm-chapter-conclusions li{margin:.35rem 0}@media(max-width:760px){.llm-synthesis-grid{grid-template-columns:1fr}}
.site-header{min-height:78px;display:flex;align-items:center;gap:28px;padding:0 28px;color:#fff;background:#071f4a;border-bottom:1px solid #ffffff20}.site-brand{min-width:270px;display:flex;align-items:center;gap:12px;color:#fff;text-decoration:none}.site-logo{width:47px;height:47px;flex:none}.site-brand strong,.site-brand small{display:block}.site-brand strong{font:500 21px/1.05 Georgia,serif}.site-brand small{margin-top:4px;color:#b9d9ff;font-size:11px;font-weight:650}.site-nav{align-self:stretch;display:flex;margin-left:auto}.site-nav a{min-width:92px;display:grid;place-items:center;padding:0 13px;color:#cfdef4;text-decoration:none;border:0;font-size:12px;font-weight:750;text-align:center}.site-nav a:hover,.site-nav a:focus{color:#fff;outline:0}.site-utility{display:flex;gap:6px;padding-left:14px;border-left:1px solid #ffffff28}.site-utility a{min-width:auto;padding-inline:8px;font-size:10px}.page{margin-left:0}.hero{min-height:0;padding:3.4rem clamp(2rem,7vw,7.5rem) 2.7rem}.bookline{align-items:stretch}.book-icon{position:relative;width:5.2rem;height:6.5rem;border:1px solid #10213d38;border-radius:5px 11px 11px 5px;box-shadow:none}.book-icon:after{content:"";position:absolute;inset:5px;border:1px solid #ffffff66;border-radius:3px 7px 7px 3px;pointer-events:none}.bookline>div{min-height:6.5rem;display:flex;flex-direction:column;justify-content:center}.hero h1{font-size:clamp(2.35rem,5vw,4.7rem)}.report-tools{display:flex;align-items:center;gap:12px;padding:14px clamp(1.5rem,5vw,5rem);background:#fff;border-bottom:1px solid var(--line)}.report-search{min-width:16rem;max-width:46rem;flex:1;display:flex;align-items:center;gap:8px;padding:0 12px;background:#f8fbff;border:1px solid var(--line);border-radius:.65rem}.report-search span{color:var(--blue);font-size:1.45rem}.report-search input{width:100%;padding:.75rem 0;background:transparent;border:0;outline:0}.report-tools button{padding:.58rem .8rem;color:var(--blue);background:#fff;border:1px solid #a8c7ea;border-radius:.5rem;font-weight:750}.report-tools output{margin-left:auto;color:var(--muted);font-size:.82rem}.report-footer{display:grid;grid-template-columns:minmax(230px,1fr) auto auto;align-items:center;gap:2rem}.footer-brand{display:flex;align-items:center;gap:.75rem}.footer-brand .site-logo{width:38px;height:38px}.footer-brand strong,.footer-brand small{display:block}.footer-brand small{color:#a9c0dc;font-size:.78rem}.footer-menu{display:flex;flex-wrap:wrap;gap:.4rem 1.1rem}.footer-note{max-width:24rem;color:#a9c0dc;font-size:.78rem;text-align:right}
@media(max-width:980px){.site-header{align-items:flex-start;flex-wrap:wrap;padding-block:12px}.site-brand{min-width:0}.site-nav{order:3;width:100%;overflow:auto;margin:0}.site-nav a{min-height:42px;min-width:105px}.site-utility{margin-left:auto}.report-footer{grid-template-columns:1fr}.footer-note{text-align:left}}
@media(max-width:620px){.site-header{padding-inline:16px}.site-brand span{display:none}.site-utility a:not(:first-child){display:none}.hero{padding:2rem 1.25rem}.book-icon{width:4.4rem;height:5.6rem}.bookline>div{min-height:5.6rem}.report-tools{align-items:stretch;flex-wrap:wrap}.report-search{min-width:100%}.report-tools output{width:100%;margin:0}.report-footer{padding-inline:1.25rem}}
</style><style>
.site-header{position:sticky;top:0;z-index:8}.menu-toggle{display:none;width:44px;height:44px;margin-left:auto;color:#fff;background:transparent;border:1px solid #ffffff45;border-radius:7px}.menu-toggle span,.menu-toggle:before,.menu-toggle:after{content:"";width:20px;height:2px;display:block;margin:4px auto;background:currentColor}.site-nav{align-self:stretch;display:grid;grid-template-rows:70px 46px;margin-left:auto}.site-nav-groups{display:flex;align-items:end;justify-content:flex-end;gap:4px;padding:9px 8px 0}.site-nav-groups button{min-width:116px;height:61px;padding:0 16px;color:#bcd0e9;background:transparent;border:1px solid transparent;border-bottom:0;border-radius:11px 11px 0 0;font-size:12px;font-weight:750;cursor:pointer}.site-nav-groups button:hover,.site-nav-groups button:focus-visible{color:#fff;background:#ffffff0a;border-color:#ffffff1f;outline:0}.site-nav-groups button[aria-current="true"]{color:#fff;background:#19385f;border-color:#ffffff2b;box-shadow:0 -6px 18px #020b1b38}.site-nav-shelf{display:flex;align-items:center;justify-content:flex-end;gap:5px;min-height:46px;padding:6px 8px;background:#19385f;border-top:1px solid #ffffff2b}.site-nav .site-nav-shelf a{min-width:0;max-width:none;display:flex;align-items:center;min-height:34px;padding:7px 13px;color:#c7d8ed;text-decoration:none;border:1px solid transparent;border-radius:7px;font-size:10px;font-weight:700;line-height:1.2;white-space:nowrap}.site-nav .site-nav-shelf a:hover,.site-nav .site-nav-shelf a:focus-visible{color:#fff;background:#ffffff12;border-color:#ffffff24;outline:0}.site-nav .site-nav-shelf a[aria-current="page"]{color:#10264a;background:#eaf6ff;border-color:#9fdaf3;box-shadow:0 2px 8px #020b1b3d}.section{margin:0}.section[aria-hidden="true"]{display:none}.book-icon{overflow:visible;background:transparent;border:0;border-radius:0;box-shadow:none}.book-icon:before{content:"";position:absolute;inset:4px -5px -6px 5px;background:#b9c4d1;border-radius:5px 11px 11px 5px;box-shadow:0 10px 18px #10213d38}.book-icon:after{inset:4px;z-index:2}.book-icon img{position:relative;z-index:1;width:100%;height:100%;padding:4px;object-fit:contain;background:var(--ink);border:1px solid #10213d55;border-radius:5px 11px 11px 5px}.book-icon:not(:has(img)){overflow:hidden;background:var(--ink);border:1px solid #10213d55;box-shadow:1px 1px #fff,4px 4px #b9c4d1,7px 10px 16px #10213d38}.chapter-search{margin:0 0 1.4rem;padding:0;background:transparent;border:0}.chapter-search .report-search{max-width:none}.artifact-guide{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:1px;background:var(--line);border:1px solid var(--line)}.artifact-guide article{padding:1.25rem;background:#fff}.artifact-guide strong{display:block;color:var(--ink);font-family:Georgia,serif;font-size:1.08rem}.artifact-guide p{margin:.45rem 0 0}.license-summary{padding:1.1rem 1.25rem;background:var(--blue-soft);border-left:5px solid var(--blue)}.license-document{max-width:70rem;margin:1.2rem 0 0;padding:1.6rem 1.8rem;color:#344b68;background:#fff;border:1px solid var(--line);border-radius:.45rem;font:15px/1.7 Georgia,serif}.license-document h3{margin:2rem 0 .7rem;padding-bottom:.35rem;border-bottom:1px solid var(--line);font-size:1.35rem}.license-document h3:first-child{margin-top:0;color:var(--blue);font-size:1.55rem}.license-document h4{margin:1.25rem 0 .5rem;font-size:1.05rem}.license-document p{max-width:78ch;margin:.85rem 0}.license-parameters{display:grid;gap:.45rem;margin:1rem 0 1.35rem}.license-parameters div{display:grid;grid-template-columns:10.5rem minmax(0,1fr);gap:.8rem}.license-parameters dt{color:var(--ink);font-weight:800}.license-parameters dd{margin:0}.license-document ol{max-width:78ch;padding-left:1.5rem}.license-document li{margin:.8rem 0;padding-left:.3rem}.license-warranty{padding:1rem 1.15rem;background:#f5f7fa;border-left:4px solid #8da0b7;font-size:.88rem;font-weight:700;letter-spacing:.01em}@media(max-width:900px){.site-header{min-height:70px;flex-wrap:wrap;padding:11px 16px}.menu-toggle{display:block}.site-nav{display:none;order:3;width:100%;align-self:auto;margin:0;padding:8px 0 2px;border-top:1px solid #ffffff28}.site-header.menu-open .site-nav{display:block}.site-nav-groups,.site-nav-shelf{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:5px;padding:5px;background:transparent;border:0}.site-nav-groups button{min-height:48px;height:auto;border:1px solid transparent;border-radius:8px}.site-nav-groups button[aria-current="true"]{background:#19385f;border-color:#ffffff2b;box-shadow:none}.site-nav .site-nav-shelf a{min-height:44px;justify-content:center}.site-brand{min-width:0}.artifact-guide{grid-template-columns:1fr}.license-document{padding:1.15rem}.license-parameters div{grid-template-columns:1fr;gap:.1rem}}@media print{.site-header{position:static}.site-nav{display:none}.section[aria-hidden="true"]{display:block}}
</style><style>
.review-signoff{display:grid;grid-template-columns:auto minmax(0,1fr);gap:1rem;align-items:start;margin:0 0 1.4rem;padding:1.2rem 1.35rem;color:#244f43;background:#eef8f4;border:1px solid #b8dfd1;border-left:6px solid var(--green);border-radius:.55rem}.review-signoff-mark{width:2.4rem;height:2.4rem;display:grid;place-items:center;color:#fff;background:var(--green);border-radius:50%;font-weight:900}.review-signoff p,.review-signoff h3{margin:0}.review-signoff p{color:var(--green);font-size:.76rem;font-weight:800;text-transform:uppercase;letter-spacing:.07em}.review-signoff small{display:block;margin:.15rem 0 .55rem;color:var(--muted)}.review-signoff blockquote{max-width:60rem;margin:.65rem 0 0;padding:.7rem .9rem;color:#334b62;background:#fff;border-left:3px solid #83bba8;font:1rem/1.55 Georgia,serif}.review-comment-list{display:grid;gap:1rem}.review-comment{padding:1.2rem 1.3rem;background:#fff;border:1px solid #d9cdec;border-left:5px solid var(--violet);border-radius:.55rem}.review-comment header{display:flex;align-items:flex-start;justify-content:space-between;gap:1rem}.review-comment header strong,.review-comment header small{display:block}.review-comment header small{margin-top:.2rem;color:var(--muted)}.review-comment-tags{display:flex;flex-wrap:wrap;gap:.4rem;margin:.85rem 0}.review-comment-tags span{padding:.22rem .58rem;color:#634395;background:var(--violet-soft);border-radius:99rem;font-size:.76rem;font-weight:750}.review-comment blockquote{margin:.8rem 0;padding:.9rem 1rem;color:#4d3e65;background:#faf7fd;border-left:3px solid #9879c5;font:1rem/1.58 Georgia,serif}.review-comment>p{margin:.75rem 0 0;color:#273f5f;font-size:1.05rem}.review-comment footer{margin-top:.9rem;color:var(--muted);font-size:.78rem;font-weight:750}.reviewer-ledger-summary div{border-top-color:var(--violet)}
</style></head><body><a class="skip" href="#report-main">Skip to report</a><header class="site-header" id="site-header"><a class="site-brand" href="#overview" aria-label="Bookinator report home"><svg class="site-logo" viewBox="0 0 64 64" aria-hidden="true"><rect x="2" y="2" width="60" height="60" rx="14" fill="#071f4a" stroke="#28cce6" stroke-width="3"/><path d="M12 17c7-2 14-1 20 5v29c-6-6-13-7-20-5V17Zm40 0c-7-2-14-1-20 5v29c6-6 13-7 20-5V17Z" fill="none" stroke="#59ecf4" stroke-width="3.5" stroke-linejoin="round"/><path d="M15 33c6 1 9-5 14-3 2 .7 3 2 5 3.2" fill="none" stroke="#59ecf4" stroke-width="3.5" stroke-linecap="round"/><path d="M43 34c2 .5 4 .1 6-1" fill="none" stroke="#59ecf4" stroke-width="3.5" stroke-linecap="round"/><circle cx="39" cy="34" r="4" fill="#071f4a" stroke="#f2a31b" stroke-width="3"/></svg><span><strong>Bookinator</strong><small>Find what the author forgot.</small></span></a><button class="menu-toggle" id="menu-toggle" type="button" aria-expanded="false" aria-controls="report-nav" aria-label="Open report menu"><span></span></button><nav class="site-nav" id="report-nav" aria-label="Report sections"></nav></header><div class="page"><header class="hero"><div class="bookline"><span class="book-icon" id="book-icon"></span><div><h1 id="book-title"></h1><p class="author" id="book-author"></p></div></div><p class="hero-note"><strong>A saved editorial view.</strong> This publication contains selected analysis and evidence—not the manuscript. Machine observations remain suggestions for human judgment.</p></header><main id="report-main"></main><footer class="report-footer"><div class="footer-brand"><svg class="site-logo" viewBox="0 0 64 64" aria-hidden="true"><rect x="2" y="2" width="60" height="60" rx="14" fill="#071f4a" stroke="#28cce6" stroke-width="3"/><path d="M12 17c7-2 14-1 20 5v29c-6-6-13-7-20-5V17Zm40 0c-7-2-14-1-20 5v29c6-6 13-7 20-5V17Z" fill="none" stroke="#59ecf4" stroke-width="3.5" stroke-linejoin="round"/><path d="M15 33c6 1 9-5 14-3 2 .7 3 2 5 3.2" fill="none" stroke="#59ecf4" stroke-width="3.5" stroke-linecap="round"/><path d="M43 34c2 .5 4 .1 6-1" fill="none" stroke="#59ecf4" stroke-width="3.5" stroke-linecap="round"/><circle cx="39" cy="34" r="4" fill="#071f4a" stroke="#f2a31b" stroke-width="3"/></svg><span><strong>Bookinator</strong><small>Local manuscript intelligence</small></span></div><nav class="footer-menu" aria-label="Bookinator information"><a href="https://book.inator.com">Website</a><a href="https://github.com/randal-cox/bookinator">GitHub</a><a href="#license">License</a><a href="#guide">Using this report</a></nav><p class="footer-note">Self-contained and model-free. Opening this report makes no network request.</p></footer></div>
<script id="report-data" type="application/json">${data}</script><script>
(() => {
  const d = JSON.parse(document.querySelector('#report-data').textContent);
  const licenseText = ${license};
  const main = document.querySelector('#report-main');
  const nav = document.querySelector('#report-nav');
  const e = (value) => String(value ?? '').replace(/[&<>"']/g, (character) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[character]));
  const licenseMarkup = (value) => {
    const blocks = String(value || '').trim().split(/\\n\\s*\\n/).map((block) => block.trim()).filter(Boolean);
    const headings = new Set(['Parameters', 'Notice', 'Terms', 'Covenants of Licensor']);
    const output = [];
    let numbered = [];
    const flushNumbered = () => {
      if (!numbered.length) return;
      output.push('<ol>' + numbered.map((item) => '<li>' + e(item.replace(/^\\d+\\.\\s*/, '')) + '</li>').join('') + '</ol>');
      numbered = [];
    };
    blocks.forEach((block, index) => {
      if (/^\\d+\\.\\s/.test(block)) { numbered.push(block); return; }
      flushNumbered();
      if (index === 0) { output.push('<h3>' + e(block) + '</h3>'); return; }
      if (headings.has(block)) { output.push('<h3>' + e(block) + '</h3>'); return; }
      if (blocks[index - 1] === 'Parameters') {
        const rows = [];
        block.split('\\n').forEach((line) => {
          const match = line.match(/^([^:]+):\\s*(.*)$/);
          if (match) rows.push({label: match[1].trim(), value: match[2].trim()});
          else if (rows.length) rows[rows.length - 1].value += ' ' + line.trim();
        });
        output.push('<dl class="license-parameters">' + rows.map((row) => '<div><dt>' + e(row.label) + '</dt><dd>' + e(row.value) + '</dd></div>').join('') + '</dl>');
        return;
      }
      if (block === 'Business Source License 1.1') { output.push('<h4>' + e(block) + '</h4>'); return; }
      output.push('<p' + (/^TO THE EXTENT PERMITTED/.test(block) ? ' class="license-warranty"' : '') + '>' + e(block).replace(/\\n/g, '<br>') + '</p>');
    });
    flushNumbered();
    return output.join('');
  };
  const n = (value) => Number(value || 0).toLocaleString();
  const duration = (seconds) => { let remaining = Math.max(0, Math.round(Number(seconds) || 0)); const units = [[86400,'d'],[3600,'h'],[60,'m'],[1,'s']], parts = []; for (const [size,suffix] of units) { const amount = Math.floor(remaining / size); if (amount) parts.push(amount + suffix); remaining %= size; if (parts.length === 2) break; } return parts.join(' ') || 'Not recorded'; };
  const empty = (message) => '<p class="empty">' + e(message) + '</p>';
  const section = (id, title, meta, body) => '<section class="section" id="' + id + '"><header class="section-heading"><h2>' + e(title) + '</h2><p>' + e(meta || '') + '</p></header>' + body + '</section>';
  const status = (value, label = value) => '<span class="status ' + e(value) + '">' + e(label) + '</span>';
  const has = (id) => !Array.isArray(d.export.sections) || d.export.sections.includes(id);

  const icon = d.book.icon || {};
  const iconHtml = icon.kind === 'image' ? '<img alt="" src="' + e(icon.value) + '">' : e(icon.value || 'B');
  document.querySelector('#book-icon').innerHTML = iconHtml;
  document.querySelector('#book-title').textContent = d.book.title;
  document.querySelector('#book-author').textContent = d.book.author;
  document.title = ['Bookinator', d.book.title, d.book.author].filter(Boolean).join(' - ');

  const parts = [];
  const overview = '<p class="lede" data-search-item>' + e(d.overview.summary || d.overview.dossierSynopsis || 'A whole-book synthesis was not included in this export.') + '</p>'
    + '<div class="ledger"><div><strong>' + n(d.book.chapterCount) + '</strong>chapters</div><div><strong>' + n(d.book.wordCount) + '</strong>words analyzed</div><div><strong>'
    + n(d.completeness.chapterSummaries.complete) + ' / ' + n(d.completeness.chapterSummaries.total) + '</strong>summaries</div><div><strong>' + n(d.reviewerComments?.length) + '</strong>human comments</div><div><strong>' + n(d.smells.length) + '</strong>editorial findings</div><div><strong>' + duration(d.export.totalAnalysisSeconds) + '</strong>recorded project time</div></div>';
  if (has('overview')) parts.push(section('overview', 'Overview', 'Generated ' + new Date(d.export.createdAt).toLocaleString(), overview));

  const lengthMaximum = Math.max.apply(null, d.chapters.map((chapter) => Number(chapter.wordCount) || 0).concat([1]));
  const chapterLengthRows = d.chapters.map((chapter) => {
    const words = Number(chapter.wordCount) || 0;
    const label = [chapter.heading, chapter.title, n(words) + ' words'].filter(Boolean).join(' · ');
    return '<div class="chapter-length-row" title="' + e(label) + '"><strong>' + e(chapter.sequence) + '</strong><span class="chapter-length-track"><i style="--chapter-length:' + Math.max(2, words / lengthMaximum * 100) + '%"></i></span><small>' + n(words) + ' words</small></div>';
  }).join('');
  if (has('chapter-length')) parts.push(section('chapter-length', 'Chapter length', d.chapters.length + ' chapters in reading order', chapterLengthRows ? '<div class="chapter-length-list">' + chapterLengthRows + '</div>' : empty('No chapter word counts were included.')));

  const chapters = d.chapters.filter((chapter) => chapter.summary);
  const chapterCards = chapters.map((chapter) => {
    const pages = d.book.fixedPagination && chapter.pages.start ? 'Pages ' + chapter.pages.start + (chapter.pages.end && chapter.pages.end !== chapter.pages.start ? '–' + chapter.pages.end : '') : '';
    const facts = chapter.establishes.length ? '<section><h4>What this establishes</h4><ul>' + chapter.establishes.map((item) => '<li>' + e(item) + '</li>').join('') + '</ul></section>' : '';
    const questions = chapter.questions.length ? '<section><h4>Questions carried forward</h4><ul>' + chapter.questions.map((item) => '<li>' + e(item) + '</li>').join('') + '</ul></section>' : '';
    return '<details class="card" data-search-item><summary><span class="number">' + e(chapter.sequence) + '</span><span><strong>' + e(chapter.heading) + '</strong><small>' + e(chapter.title || pages) + '</small></span><small>' + n(chapter.wordCount) + ' words</small></summary><div class="card-body"><p>' + e(chapter.summary) + '</p><div class="facts">' + facts + questions + '</div></div></details>';
  }).join('');
  const chapterSearch = '<section class="report-tools chapter-search" aria-label="Search chapter summaries"><label class="report-search"><span aria-hidden="true">⌕</span><input id="report-search" type="search" placeholder="Search chapter summaries" aria-label="Search chapter summaries"></label><button id="search-clear" type="button" hidden>Clear</button><output id="search-status" aria-live="polite">' + chapters.length + ' chapters</output></section>';
  if (has('chapters')) parts.push(section('chapters', 'Chapter summaries', chapters.length + ' included', chapterSearch + (chapterCards ? '<div class="chapter-list">' + chapterCards + '</div>' : empty('No completed chapter summaries were included.'))));

  const dossier = d.wholeBookDossier;
  if (has('dossier') && dossier) {
    const dossierGroups = [['Established facts',dossier.facts],['Events',dossier.events],['Entities',dossier.entities],['Locations',dossier.locations],['Current times',dossier.currentTimes],['Questions',dossier.questions],['Promises',dossier.promises],['Timeline observations',dossier.timelineObservations],['Contradictions',dossier.contradictions]];
    const dossierDetails = dossierGroups.filter((item) => item[1]?.length).map((item) => '<section data-search-item><h4>' + e(item[0]) + '</h4><ul>' + item[1].map((value) => '<li>' + e(value) + '</li>').join('') + '</ul></section>').join('');
    parts.push(section('dossier', 'Dossier synthesis', 'Evidence-linked whole-book memory', '<p class="lede" data-search-item>' + e(dossier.synopsis) + '</p>' + (dossierDetails ? '<div class="facts">' + dossierDetails + '</div>' : ''));
  }

  const categoryName = (value) => ({editorial:'Editorial note',clarity:'Clarity',character:'Character',continuity:'Continuity',plot:'Plot',prose:'Prose',question:'Question',praise:'Praise'}[value] || String(value || '').replace(/(^|[-_ ])\w/g, (match) => match.toUpperCase()));
  const priorityName = (value) => ({low:'Low',normal:'Normal',high:'Urgent'}[value] || 'Normal');
  const reviewerCards = (d.reviewerComments || []).map((comment) => {
    const pages = d.book.fixedPagination && comment.pages?.start ? 'Pages ' + comment.pages.start + (comment.pages.end && comment.pages.end !== comment.pages.start ? '–' + comment.pages.end : '') : '';
    const tags = (comment.categories || []).map((category) => '<span>' + e(categoryName(category)) + '</span>').join('') + (comment.origin?.kind === 'llm-review-proposal' ? '<span>From machine proposal</span>' : '');
    return '<article class="review-comment active" data-search-item><header><div><strong>' + e(comment.chapterHeading) + '</strong><small>' + e([comment.chapterTitle, pages].filter(Boolean).join(' · ')) + '</small></div>' + status(comment.priority, priorityName(comment.priority)) + '</header><div class="review-comment-tags">' + tags + '</div>' + (comment.quote ? '<blockquote>“' + e(comment.quote) + '”</blockquote>' : '') + '<p>' + e(comment.comment) + '</p><footer>Active reviewer note</footer></article>';
  }).join('');
  const reviewerSignoff = d.reviewerSignoff?.status === 'complete'
    ? '<article class="review-signoff"><span class="review-signoff-mark" aria-hidden="true">✓</span><div><p>Review signed off for now</p><h3>' + e(d.reviewerSignoff.reviewerName || 'Reviewer') + '</h3>' + (d.reviewerSignoff.completedAt ? '<small>' + e(new Date(d.reviewerSignoff.completedAt).toLocaleString()) + '</small>' : '') + (d.reviewerSignoff.notes ? '<blockquote>' + e(d.reviewerSignoff.notes) + '</blockquote>' : '') + '</div></article>'
    : '';
  if (has('reviewer')) parts.push(section('reviewer', 'Reviewer comments', (d.reviewerComments || []).length + ' active human notes', reviewerSignoff + '<div class="ledger reviewer-ledger-summary"><div><strong>' + n((d.reviewerComments || []).length) + '</strong>active comments</div><div><strong>' + n(new Set((d.reviewerComments || []).map((item) => item.chapterSequence)).size) + '</strong>chapters</div></div>' + (reviewerCards ? '<div class="review-comment-list">' + reviewerCards + '</div>' : empty('No reviewer comments were included.'))));

  const questionCards = d.questions.map((question) => '<article class="card question" data-search-item>' + status(question.status) + '<h3>' + e(question.question) + '</h3><p>Raised in Chapter ' + e(question.triggerChapter) + (question.resolutionChapter ? ' · possible payoff in Chapter ' + e(question.resolutionChapter) : '') + '</p>' + (question.answer ? '<p><strong>Answer or payoff:</strong> ' + e(question.answer) + '</p>' : '') + '</article>').join('');
  if (has('questions')) parts.push(section('questions', 'Questions and payoffs', d.questions.length + ' tracked', questionCards ? '<div class="question-list">' + questionCards + '</div>' : empty('No reconciled questions were included.')));

  const connectionList = (title, items) => '<section><h3>' + e(title) + '</h3>' + (items.length ? '<ol>' + items.slice(0, 100).map((item) => '<li data-search-item><span>' + e(item.name) + '</span><small>' + n(item.mentions) + ' mentions · Chapters ' + e(item.chapters.join(', ')) + '</small></li>').join('') + '</ol>' : empty('No entries included.')) + '</section>';
  if (has('connections')) parts.push(section('connections', 'Connections', 'From completed dossiers', '<div class="connection-grid">' + connectionList('Entities', d.connections.entities) + connectionList('Locations', d.connections.locations) + '</div>'));

  const tagTotals = new Map();
  d.chapters.forEach((chapter) => (chapter.tags || []).forEach((tag) => {
    const item = tagTotals.get(tag.id) || {id:tag.id,label:tag.label,family:tag.familyLabel,count:0,total:0,chapters:new Set()};
    if (!item.chapters.has(chapter.sequence)) { item.count += 1; item.chapters.add(chapter.sequence); }
    item.total += Number(tag.score) || 0;
    tagTotals.set(tag.id, item);
  }));
  const tagItems = [...tagTotals.values()].map((item) => ({...item,average:item.count ? item.total / item.count : 0})).sort((left, right) => right.count - left.count || right.average - left.average || left.label.localeCompare(right.label));
  const tagRows = tagItems.map((item) => '<div class="tag-profile-row" data-search-item><strong>' + e(item.label) + '</strong><small>' + e(item.family) + ' · ' + n(item.count) + ' of ' + n(d.chapters.length) + ' chapters · ' + Math.round(item.average * 100) + '% average</small><span class="tag-profile-track"><i style="--tag-frequency:' + Math.max(2, item.count / Math.max(d.chapters.length, 1) * 100) + '%"></i></span></div>').join('');
  if (has('tags')) parts.push(section('tags', 'Tag frequencies', tagItems.length + ' distinct tags', tagRows ? '<div class="tag-profile">' + tagRows + '</div>' : empty('No completed chapter tags were included.')));

  const palette = ['#2863c7','#7550b8','#28765d','#b45948','#9a6810','#4c7894','#7c5f91'];
  const emotional = d.chapters.filter((chapter) => Object.keys(chapter.emotion).length);
  const emotionTotals = new Map();
  emotional.forEach((chapter) => Object.entries(chapter.emotion).forEach(([label, rawScore]) => {
    const score = Number(rawScore) || 0;
    const item = emotionTotals.get(label) || {label, total:0, peak:0, chapters:0};
    item.total += score; item.peak = Math.max(item.peak, score); if (score >= .1) item.chapters += 1;
    emotionTotals.set(label, item);
  }));
  const emotionProfileItems = [...emotionTotals.values()].map((item) => ({...item, average:emotional.length ? item.total / emotional.length : 0})).filter((item) => item.total > 0).sort((left, right) => right.average - left.average || right.chapters - left.chapters || left.label.localeCompare(right.label));
  const emotionProfileRows = emotionProfileItems.map((item, index) => '<div class="emotion-profile-row" data-search-item><strong>' + e(item.label) + '</strong><small>' + n(item.chapters) + ' chapters at 10%+ · ' + Math.round(item.average * 100) + '% book average · ' + Math.round(item.peak * 100) + '% peak</small><span class="emotion-profile-track"><i style="--emotion:' + palette[index % palette.length] + ';--emotion-average:' + Math.max(2, item.average * 100) + '%"></i></span></div>').join('');
  const emotionProfile = emotionProfileRows ? '<section class="emotion-profile"><h3>Whole-book emotional profile</h3>' + emotionProfileRows + '</section>' : '';
  const emotionRows = emotional.map((chapter) => {
    const values = Object.entries(chapter.emotion).filter((item) => item[1] >= .1).sort((left, right) => right[1] - left[1]);
    const bars = values.map((item, index) => '<span style="--emotion:' + palette[index % palette.length] + ';flex:' + Math.max(.08, item[1]) + '" title="' + e(item[0]) + ' ' + Math.round(item[1] * 100) + '%">' + e(item[0]) + '</span>').join('');
    return '<div class="emotion-row" data-search-item><strong>' + e(chapter.heading) + '</strong><div class="emotion-bars">' + (bars || '<small>No emotion at 10% or higher</small>') + '</div></div>';
  }).join('');
  if (has('emotions')) parts.push(section('emotions', 'Emotional texture', emotional.length + ' chapters scored', emotionProfile + (emotionRows || empty('No completed emotion scores were included.'))));

  const synthesis = d.wholeBookLlmReview;
  if (has('llm-review') && synthesis) {
    const reviewList = (title, items, titleField, bodyField, noteField) => '<section><h3>' + e(title) + '</h3>' + (items || []).map((item) => '<article data-search-item><strong>' + e(item[titleField]) + '</strong>' + (item[bodyField] ? '<span>' + e(item[bodyField]) + '</span>' : '') + (item[noteField] ? '<small>' + e(item[noteField]) + '</small>' : '') + '</article>').join('') + '</section>';
    const synthesisGrid = '<div class="llm-synthesis-grid">' + reviewList('Strengths to preserve', synthesis.strengths, 'title', 'synthesis', 'significance') + reviewList('Whole-book risks', synthesis.risks, 'title', 'synthesis', 'significance') + reviewList('Editorial priorities', synthesis.editorialPriorities, 'title', 'rationale', 'scope') + reviewList('Likely readers', synthesis.likelyReaders, 'reader', 'fit', 'caution') + '</div>';
    const dimensionLabels = {narrative_engagement:'Narrative engagement',character_likability:'Character likability',character_relatability:'Character relatability',clarity:'Clarity',stakes_and_tension:'Stakes & tension',coherence_and_continuity:'Coherence & continuity',voice_and_distinctiveness:'Voice & distinctiveness',emotional_impact:'Emotional impact',genre_and_audience_fit:'Genre & audience fit',saleability:'Saleability'};
    const reviewed = d.chapters.filter((chapter) => chapter.llmReview);
    const dimensions = Object.keys(dimensionLabels).map((key) => {
      const scores = reviewed.map((chapter) => chapter.llmReview.dimensions?.[key]).filter((item) => item && item.applicable !== false && Number(item.score) > 0).map((item) => Number(item.score));
      return {key,count:scores.length,percent:scores.length ? scores.reduce((sum, score) => sum + score, 0) / scores.length / 5 * 100 : 0};
    }).filter((item) => item.count).sort((left, right) => right.percent - left.percent || dimensionLabels[left.key].localeCompare(dimensionLabels[right.key]));
    const profile = dimensions.length ? '<section><h3>Whole-book assessment profile</h3><div class="llm-profile">' + dimensions.map((item) => { const color = item.percent >= 80 ? '#28765d' : item.percent >= 60 ? '#a97721' : '#a64c43'; return '<div class="llm-profile-row" data-search-item><strong>' + e(dimensionLabels[item.key]) + '</strong><small>' + Math.round(item.percent) + '%</small><span class="llm-profile-track"><i style="--review-score:' + item.percent + '%;--review-color:' + color + '"></i></span></div>'; }).join('') + '</div></section>' : '';
    const chapterConclusions = reviewed.map((chapter) => {
      const review = chapter.llmReview;
      const strengths = [...(review.strengths || []).map((item) => 'Strength: ' + item), ...(review.commercialStrengths || []).map((item) => 'Commercial strength: ' + item), ...(review.commercialRisks || []).map((item) => 'Commercial risk: ' + item)];
      return '<details data-search-item><summary>' + e(chapter.heading) + (chapter.title ? ' · ' + e(chapter.title) : '') + '</summary><div><p>' + e(review.editorialSummary || 'No significant concerns were found.') + '</p>' + (review.editorialRationale ? '<p>' + e(review.editorialRationale) + '</p>' : '') + (strengths.length ? '<ul>' + strengths.map((item) => '<li>' + e(item) + '</li>').join('') + '</ul>' : '') + '</div></details>';
    }).join('');
    const reviewMarkup = '<div class="llm-synthesis"><div class="llm-synthesis-overall"><strong>Overall assessment</strong><p>' + e(synthesis.overallAssessment) + '</p></div>' + synthesisGrid + (synthesis.commercialPositioning ? '<div class="llm-positioning"><strong>Commercial positioning</strong><p>' + e(synthesis.commercialPositioning) + '</p></div>' : '') + profile + (chapterConclusions ? '<section><h3>Chapter conclusions</h3><div class="llm-chapter-conclusions">' + chapterConclusions + '</div></section>' : '') + '</div>';
    parts.push(section('llm-review', 'LLM Review', reviewed.length + ' chapters plus whole-book synthesis', reviewMarkup));
  }

  const findings = d.smells.map((finding) => '<article class="card finding" data-search-item>' + status(finding.severity) + '<h3>' + e(finding.issue) + '</h3><p>' + e(finding.reason) + '</p><small>' + e(finding.chapterHeading) + (finding.chapterTitle ? ' · ' + e(finding.chapterTitle) : '') + '</small>' + (finding.sentence ? '<blockquote>“' + e(finding.sentence) + '”</blockquote>' : '') + '</article>').join('');
  if (has('smells')) parts.push(section('smells', 'Editorial findings', d.smells.length + ' retained', findings ? '<div class="finding-list">' + findings + '</div>' : empty('No retained prose findings were included.')));

  const provenance = d.provenance.map((item) => '<tr data-search-item><td>' + e(item.label || item.id) + '</td><td>' + status(item.status) + '</td><td>' + e(item.model || 'Not recorded') + '</td><td>' + e(duration(item.durationSeconds)) + '</td></tr>').join('');
  if (has('method')) parts.push(section('method', 'Method and provenance', d.export.freshness, '<p>This export contains selected derived analysis only. It does not contain the source manuscript or chapter prose.</p><table class="method-table"><thead><tr><th>Analysis</th><th>Status</th><th>Model</th><th>Duration</th></tr></thead><tbody>' + provenance + '</tbody></table>'));
  parts.push(section('guide', 'Using this report', 'A read-only Bookinator publication', '<div class="artifact-guide"><article><strong>Choose a view</strong><p>Use the menu to move among summaries, reviewer comments, questions, connections, findings, and methods. Browser Back and Forward work normally.</p></article><article><strong>Separate judgment from suggestion</strong><p>Reviewer comments record a person’s judgment and selected quotation. Machine observations remain editorial suggestions, not automatic corrections.</p></article><article><strong>Keep it portable</strong><p>This single file works offline. Send or archive it as-is; it cannot rerun analysis or alter the original Bookinator project.</p></article></div>'));
  parts.push(section('license', 'License', 'Bookinator 0.1.0', '<div class="license-summary"><strong>Business Source License 1.1.</strong> Personal, educational, research, and internal business use is allowed. The work changes to GPL-3.0-or-later on September 24, 2030.</div><div class="license-document">' + licenseMarkup(licenseText) + '</div>'));

  main.innerHTML = parts.join('');
  const sections = [...main.querySelectorAll('.section')];
  const sectionIds = new Set(sections.map((item) => item.id));
  const navigationGroups = [
    {id:'book', label:'Book', sections:['overview','chapters','chapter-length','dossier']},
    {id:'story', label:'Story', sections:['emotions','tags','questions','connections']},
    {id:'editorial', label:'Editorial', sections:['reviewer','llm-review','smells']},
    {id:'about', label:'About this report', sections:['method','guide']},
  ].map((group) => ({...group, sections:group.sections.filter((id) => sectionIds.has(id))})).filter((group) => group.sections.length);
  nav.innerHTML = '<div class="site-nav-groups" aria-label="Report groups">' + navigationGroups.map((group) => '<button type="button" data-nav-group="' + group.id + '" aria-controls="site-nav-shelf" aria-expanded="false">' + e(group.label) + '</button>').join('') + '</div><div class="site-nav-shelf" id="site-nav-shelf" aria-label="Current report group"></div>';
  const navShelf = nav.querySelector('.site-nav-shelf');
  const groupForSection = (id) => navigationGroups.find((group) => group.sections.includes(id)) || (id === 'license' ? navigationGroups.find((group) => group.id === 'about') : null) || navigationGroups[0];
  const renderNavigationShelf = (group, current) => {
    navShelf.innerHTML = group.sections.map((id) => {
      const item = sections.find((section) => section.id === id);
      return '<a href="#' + id + '" data-nav-section="' + id + '"' + (id === current ? ' aria-current="page"' : '') + '>' + e(item.querySelector('h2').textContent) + '</a>';
    }).join('');
    navShelf.setAttribute('aria-label', group.label + ' reports');
  };
  const header = document.querySelector('#site-header');
  const menu = document.querySelector('#menu-toggle');
  const showPage = () => {
    const requested = location.hash.slice(1);
    const current = sections.some((item) => item.id === requested) ? requested : sections[0]?.id;
    const activeGroup = groupForSection(current);
    sections.forEach((item) => item.setAttribute('aria-hidden', item.id === current ? 'false' : 'true'));
    nav.querySelectorAll('[data-nav-group]').forEach((button) => {
      const active = button.dataset.navGroup === activeGroup.id;
      button.setAttribute('aria-current', active ? 'true' : 'false');
      button.setAttribute('aria-expanded', active ? 'true' : 'false');
    });
    renderNavigationShelf(activeGroup, current);
    header.classList.remove('menu-open'); menu.setAttribute('aria-expanded', 'false');
    if (requested !== current && current) history.replaceState(null, '', '#' + current);
    scrollTo({top: 0, behavior: 'auto'});
  };
  nav.addEventListener('click', (event) => {
    const button = event.target.closest('[data-nav-group]');
    if (!button) return;
    const group = navigationGroups.find((candidate) => candidate.id === button.dataset.navGroup);
    if (!group?.sections[0]) return;
    if (matchMedia('(max-width:900px)').matches) {
      nav.querySelectorAll('[data-nav-group]').forEach((candidate) => {
        const active = candidate === button;
        candidate.setAttribute('aria-current', active ? 'true' : 'false');
        candidate.setAttribute('aria-expanded', active ? 'true' : 'false');
      });
      renderNavigationShelf(group, '');
      return;
    }
    location.hash = group.sections[0];
  });
  addEventListener('hashchange', showPage);
  menu.addEventListener('click', () => { const open = header.classList.toggle('menu-open'); menu.setAttribute('aria-expanded', String(open)); });
  showPage();
  const search = document.querySelector('#report-search');
  if (!search) return;
  const clear = document.querySelector('#search-clear');
  const searchStatus = document.querySelector('#search-status');
  const applySearch = () => {
    const query = search.value.trim().toLocaleLowerCase();
    let matches = 0;
    document.querySelector('#chapters').querySelectorAll('[data-search-item]').forEach((item) => {
      const match = !query || item.textContent.toLocaleLowerCase().includes(query);
      item.hidden = !match;
      if (query && match) {
        matches += 1;
        if (item.matches('details')) item.open = true;
      }
    });
    clear.hidden = !query;
    searchStatus.textContent = query ? (matches ? matches + (matches === 1 ? ' chapter' : ' chapters') : 'No chapters') : chapters.length + (chapters.length === 1 ? ' chapter' : ' chapters');
  };
  search.addEventListener('input', () => {
    applySearch();
  });
  clear.addEventListener('click', () => { search.value = ''; applySearch(); search.focus(); });
})();
</script></body></html>`;
}
