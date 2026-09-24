"""Experimental, source-linked prose warnings from several local detectors.

This module deliberately favors recall over precision.  It is a bake-off layer:
every finding names its detector and retains the exact source sentence so that
we can decide which rules deserve to become Bookinator product behavior.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parents[1]
HARPER_RUNNER = ROOT / "tools" / "prose-cruft-harper.mjs"


def prose_projection(text: str) -> str:
    """Mask Markdown structure while preserving every canonical source offset."""
    return re.sub(r"(?m)^\s*#{1,6}\s+.*$", lambda match: " " * len(match.group(0)), text)


def sentence_spans(text: str) -> list[tuple[int, int, str]]:
    """Return non-heading sentence spans without losing source offsets."""
    masked = prose_projection(text)
    spans: list[tuple[int, int, str]] = []
    block_start = 0
    for block in re.split(r"(\n\s*\n+)", masked):
        if not block or re.fullmatch(r"\n\s*\n+", block):
            block_start += len(block)
            continue
        for match in re.finditer(r"\S(?:.*?\S)?(?:[.!?](?:[\"”’']+)?(?=\s|$)|$)", block, re.S):
            raw_start = block_start + match.start()
            raw_end = block_start + match.end()
            sentence = text[raw_start:raw_end].strip()
            if not sentence:
                continue
            leading = len(match.group(0)) - len(match.group(0).lstrip())
            start = raw_start + leading
            spans.append((start, start + len(sentence), sentence))
        block_start += len(block)
    return spans


def containing_sentence(spans: list[tuple[int, int, str]], start: int, end: int) -> tuple[int, int, str]:
    for sentence in spans:
        if sentence[0] <= start < sentence[1] or (start <= sentence[0] and end >= sentence[1]):
            return sentence
    snippet_start = max(0, start - 80)
    snippet_end = max(end, start + 1) + 80
    return snippet_start, snippet_end, ""


def finding(detector: str, rule: str, message: str, text: str, spans: list[tuple[int, int, str]], start: int, end: int, **details: object) -> dict[str, object]:
    sentence_start, sentence_end, sentence = containing_sentence(spans, start, end)
    if not sentence:
        sentence = text[sentence_start:sentence_end].strip()
    return {
        "detector": detector,
        "rule": rule,
        "message": message,
        "characterStart": max(0, start),
        "characterEnd": max(start, end),
        "sentenceStart": sentence_start,
        "sentenceEnd": sentence_end,
        "sentence": sentence,
        **details,
    }


def deterministic_findings(text: str, spans: list[tuple[int, int, str]]) -> list[dict[str, object]]:
    results: list[dict[str, object]] = []
    for start, end, sentence in spans:
        words = re.findall(r"\b[\w’'-]+\b", sentence)
        count = len(words)
        if count >= 30:
            strength = "very long" if count >= 45 else "long"
            results.append(finding("Bookinator", "sentence-length", f"{strength.capitalize()} sentence: {count} words.", text, spans, start, end, wordCount=count))
        repeated = re.search(r"\b([A-Za-z][\w'-]*)\s+\1\b", sentence, re.I)
        if repeated:
            results.append(finding("Bookinator", "repeated-word", f"Repeated word: “{repeated.group(1)}”.", text, spans, start + repeated.start(), start + repeated.end()))
        semicolons = sentence.count(";")
        conjunctions = len(re.findall(r"\b(?:and|but|or|yet|so|because|although|though|while|when|which|that|who)\b", sentence, re.I))
        if count >= 24 and semicolons + conjunctions >= 4:
            results.append(finding("Bookinator", "clause-load-proxy", f"Heavy clause load: {conjunctions} connectors and {semicolons} semicolons in {count} words.", text, spans, start, end, wordCount=count, connectorCount=conjunctions))
    return results


def proselint_findings(text: str, spans: list[tuple[int, int, str]]) -> list[dict[str, object]]:
    from proselint.checks import __register__
    from proselint.registry import CheckRegistry
    from proselint.tools import LintFile

    registry = CheckRegistry()
    if not registry.checks:
        registry.register_many(__register__)
    results: list[dict[str, object]] = []
    for item in LintFile("<bookinator>", prose_projection(text)).lint():
        check = item.check_result
        # LintFile pads content with one leading newline.
        start = max(0, int(check.span[0]) - 1)
        end = max(start + 1, int(check.span[1]) - 1)
        results.append(finding("Proselint", str(check.check_path), str(check.message), text, spans, start, end, replacements=check.replacements))
    return results


def spacy_findings(text: str, spans: list[tuple[int, int, str]]) -> list[dict[str, object]]:
    import en_core_web_sm

    nlp = en_core_web_sm.load(disable=["ner"])
    nlp.max_length = max(nlp.max_length, len(text) + 100)
    results: list[dict[str, object]] = []
    clausal_dependencies = {"advcl", "ccomp", "xcomp", "relcl", "acl"}
    for doc_sentence in nlp(prose_projection(text)).sents:
        sentence = doc_sentence.text.strip()
        if not sentence or re.match(r"^#{1,6}\s+", sentence):
            continue
        start = doc_sentence.start_char + len(doc_sentence.text) - len(doc_sentence.text.lstrip())
        end = start + len(sentence)
        words = [token for token in doc_sentence if not token.is_punct and not token.is_space]
        clauses = [token for token in doc_sentence if token.dep_ in clausal_dependencies]
        finite_verbs = [token for token in doc_sentence if token.pos_ in {"VERB", "AUX"} and "Fin" in token.morph.get("VerbForm")]
        if len(clauses) >= 3:
            results.append(finding("spaCy", "clause-count", f"Complex sentence structure: {len(clauses)} dependent clauses across {len(words)} words.", text, spans, start, end, clauseCount=len(clauses), wordCount=len(words)))
        if len(words) >= 24 and len(finite_verbs) >= 4:
            results.append(finding("spaCy", "finite-verb-load", f"Possible run-on or overloaded sentence: {len(finite_verbs)} finite verbs across {len(words)} words.", text, spans, start, end, finiteVerbCount=len(finite_verbs), wordCount=len(words)))
    return results


def harper_findings(text: str, spans: list[tuple[int, int, str]]) -> list[dict[str, object]]:
    process = subprocess.run(
        ["node", str(HARPER_RUNNER)],
        input=prose_projection(text),
        text=True,
        capture_output=True,
        check=True,
        timeout=120,
    )
    results: list[dict[str, object]] = []
    for item in json.loads(process.stdout):
        # Harper's fiction-wide advice is too noisy for Bookinator. Its Oxford
        # comma rule is the sole retained specialty in the Smells pipeline.
        if "Oxford comma" not in str(item.get("message") or ""):
            continue
        start, end = int(item["start"]), int(item["end"])
        results.append(finding("Harper", str(item["kind"]), str(item["message"]), text, spans, start, end, problemText=item.get("problemText"), suggestions=item.get("suggestions", [])))
    return results


def analyze(text: str, detectors: Iterable[str] = ("bookinator", "proselint", "spacy", "harper")) -> dict[str, object]:
    spans = sentence_spans(text)
    runners = {
        "bookinator": deterministic_findings,
        "proselint": proselint_findings,
        "spacy": spacy_findings,
        "harper": harper_findings,
    }
    findings: list[dict[str, object]] = []
    errors: dict[str, str] = {}
    for detector in detectors:
        try:
            findings.extend(runners[detector](text, spans))
        except Exception as exc:  # A bake-off should expose one broken detector, not hide all results.
            errors[detector] = f"{type(exc).__name__}: {exc}"
    findings.sort(key=lambda item: (int(item["sentenceStart"]), str(item["detector"]), str(item["rule"])))
    return {"schema": "bookinator-prose-cruft-v1", "inputCharacters": len(text), "sentenceCount": len(spans), "findings": findings, "errors": errors}
