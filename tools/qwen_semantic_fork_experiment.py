#!/usr/bin/env python3
"""Test focused Ollama continuations over one byte-identical chapter prefix.

This is deliberately an experiment, not a pipeline writer.  It keeps the
existing Chapter Reading as the control and writes every branch, timing, and
Ollama cache metric to a separate JSON artifact while it runs.
"""

from __future__ import annotations

import argparse
import copy
import json
import re
import subprocess
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from bookinator.server import __main__ as server


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def write_artifact(path: Path, artifact: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(artifact, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def rank_action_passages(text: str, limit: int = 6) -> list[dict[str, object]]:
    """Prefer passages where actor, sequence, or uncertainty errors are costly."""
    candidates = server.chapter_action_passages(text, limit=64)
    uncertainty = re.compile(r"\b(?:as I thought|seem(?:ed|s)?|appear(?:ed|s)?|perhaps|fancied|suppos(?:e|ed)|believ(?:e|ed))\b", re.I)
    transition = re.compile(r"\b(?:and then|then|but|while|after|before|until|when)\b", re.I)
    for item in candidates:
        passage = str(item.get("exact_source") or "")
        cue_count = len(item.get("cue_words") or [])
        item["risk_score"] = (
            cue_count * 3
            + min(4, len(transition.findall(passage)))
            + (6 if uncertainty.search(passage) else 0)
            + (2 if len(passage) >= 220 else 0)
        )
    selected = sorted(candidates, key=lambda item: (-int(item["risk_score"]), int(item["character_start"])))[:limit]
    return sorted(selected, key=lambda item: int(item["character_start"]))


def branch_definitions(include_review: bool, action_passages: list[dict[str, object]]) -> list[dict[str, object]]:
    complete = server.chapter_reading_schema(include_review)
    properties = complete["properties"]
    evidence = server.source_evidence_ref_schema()
    if isinstance(evidence.get("properties"), dict) and isinstance(evidence["properties"].get("quote"), dict):
        evidence["properties"]["quote"]["maxLength"] = 320
    action_audit = {
        "type": "array",
        "items": {
            "type": "object",
            "properties": {
                "passage_id": {"type": "string", "minLength": 1},
                "verdict": {"type": "string", "enum": ["material_action", "background_or_description"]},
                "actions": {
                    "type": "array",
                    "maxItems": 10,
                    "items": {
                        "type": "object",
                        "properties": {
                            "actor": {"type": "string", "minLength": 1, "maxLength": 100},
                            "literal_action": {"type": "string", "minLength": 1, "maxLength": 240},
                            "resulting_state": {"type": "string", "minLength": 1, "maxLength": 240},
                            "epistemic_status": {"type": "string", "enum": ["fact", "perceived", "reported", "uncertain"]},
                            "evidence_ref": evidence,
                        },
                        "required": ["actor", "literal_action", "resulting_state", "epistemic_status", "evidence_ref"],
                    },
                },
                "reason": {"type": "string", "minLength": 1, "maxLength": 240},
                "evidence_ref": evidence,
            },
            "required": ["passage_id", "verdict", "actions", "reason", "evidence_ref"],
        },
    }

    summary_schema = copy.deepcopy(properties["summary"])
    summary_properties = summary_schema["properties"]
    summary_schema["properties"] = {
        key: summary_properties[key]
        for key in ("key_points", "ending_state", "new_questions", "question_details", "summary")
    }
    summary_schema["required"] = ["key_points", "ending_state", "new_questions", "question_details", "summary"]
    summary_schema["properties"]["key_points"]["maxItems"] = 10
    summary_schema["properties"]["ending_state"]["maxItems"] = 3
    summary_schema["properties"]["new_questions"]["maxItems"] = 5
    summary_schema["properties"]["question_details"]["maxItems"] = 5
    summary_schema["properties"]["summary"]["maxLength"] = 1800

    dossier_schema = copy.deepcopy(properties["dossier"])
    dossier_properties = dossier_schema["properties"]
    dossier_order = (
        "facts", "events", "entities", "locations", "current_times", "questions",
        "question_details", "promises", "timeline_observations", "evidence", "synopsis",
    )
    dossier_schema["properties"] = {key: dossier_properties[key] for key in dossier_order}
    dossier_schema["required"] = list(dossier_order)
    dossier_limits = {
        "facts": 12, "events": 12, "entities": 10, "locations": 6,
        "current_times": 4, "questions": 5, "question_details": 5,
        "promises": 5, "timeline_observations": 6, "evidence": 16,
    }
    for key, limit in dossier_limits.items():
        dossier_schema["properties"][key]["maxItems"] = limit
    dossier_schema["properties"]["synopsis"]["maxLength"] = 1800
    cast_schema = copy.deepcopy(properties["cast"])
    cast_schema["maxItems"] = 12
    branches: list[dict[str, object]] = [
        {
            "id": "identity",
            "label": "Identity resolution",
            "properties": {"cast": cast_schema},
            "required": ["cast"],
            "instruction": """Resolve only the recurring or consequential cast from the supplied GLiNER candidates and source. Merge mentions that clearly refer to the same entity. Do not treat contextual descriptions such as 'Madame' or 'the young lady' as stable aliases when they can refer to more than one entity. Return no more than twelve identities. Do not summarize or audit actions.""",
        },
    ]
    for index in range(0, len(action_passages), 3):
        batch = action_passages[index:index + 3]
        passage_ids = [str(item.get("passage_id") or "") for item in batch]
        batch_audit_schema = copy.deepcopy(action_audit)
        batch_audit_schema["minItems"] = len(batch)
        batch_audit_schema["maxItems"] = len(batch)
        branches.append({
            "id": f"action-audit-{index // 3 + 1}",
            "label": f"Action audit {index // 3 + 1}",
            "properties": {"action_audit": batch_audit_schema},
            "required": ["action_audit"],
            "instruction": f"""Audit exactly these high-risk passages: {', '.join(passage_ids)}. Return each assigned passage exactly once and no other passages. This is grammatical extraction, not a materiality filter: speech, perception, intention, locomotion, reaction, physical change, and events performed by animals or objects are actions. Extract every distinct action in a sequence separately. Because these passages were selected as action-bearing, an empty actions array is an explicit finding that must be justified from the grammar. Preserve actors, resulting states, and uncertainty. Do not summarize.""",
        })
    branches.extend([
        {
            "id": "summary",
            "label": "Summary",
            "properties": {"summary": summary_schema},
            "required": ["summary"],
            "instruction": """Produce only the compact Summary view. Select at most ten consequential key points; do not inventory every beat. Fill key_points and ending_state BEFORE writing summary prose. Cover the chapter's complete movement and final material turn in no more than 250 words. Preserve uncertainty, chronology, and actor attribution. Every factual proposition in the summary prose and every why_it_matters claim must be entailed by exact cited evidence or explicitly labeled inference. Never write 'vanished' or 'disappeared' unless exact evidence entails that result. Do not write a Dossier or editorial review.""",
        },
        {
            "id": "dossier",
            "label": "Dossier",
            "properties": {"dossier": dossier_schema},
            "required": ["dossier"],
            "instruction": """Produce only a selective evidence-preserving Dossier, not a transcript or exhaustive inventory. Retain at most twelve facts and twelve events: only identity, state, action, promise, question, or chronology records likely to matter in later chapters. Omit decorative description and minor mechanical beats. Fill ledgers before the synopsis. Preserve distinct actions, grammatical actors, and uncertainty. Every factual proposition in the synopsis must be entailed by a cited ledger claim. Calculate no elapsed interval unless the source explicitly links its endpoints. Keep the synopsis under 250 words. Do not write editorial assessment.""",
        },
    ])
    if include_review:
        branches.extend([
            {
                "id": "editorial",
                "label": "Editorial first read",
                "properties": {"editorial": properties["editorial"]},
                "required": ["editorial"],
                "instruction": """Produce only the rigorous editorial first-read view. No issue is the default. Return no more than three source-anchored proposals, and only for concrete material reader effects a professional editor would probably interrupt the author about. Preserve deliberate mystery and epistemic uncertainty.""",
            },
            {
                "id": "assessment",
                "label": "Quality assessment",
                "properties": {"assessment": properties["assessment"]},
                "required": ["assessment"],
                "instruction": """Produce only the ten-dimension manuscript assessment. Saleability is always applicable. Use one concise sentence and no more than two short exact quotations per dimension. Attribute quoted speakers correctly. Mark other genuinely inapplicable dimensions inapplicable. Do not manufacture weaknesses merely to populate the rubric.""",
            },
        ])
    return branches


def branch_schema(branch: dict[str, object]) -> dict[str, object]:
    return {
        "type": "object",
        "properties": copy.deepcopy(branch["properties"]),
        "required": list(branch["required"]),
    }


def common_messages(
    book: dict[str, object], chapter: dict[str, object], source: dict[str, object],
    prior_context: dict[str, object], gliner: dict[str, object],
    action_passages: list[dict[str, object]],
) -> list[dict[str, str]]:
    text = str(source.get("text") or "")
    system = """You are Bookinator's evidence-disciplined manuscript reader. The canonical source is authoritative. Preserve grammatical actors, chronology, polarity, causality, and epistemic qualifiers. Observation is not diagnosis; sequence is not causation; phrases such as 'as I thought', 'seemed', and 'perhaps' must never become objective fact. Copy exact evidence quotations and the supplied passage IDs and offsets. GLiNER and deterministic action candidates are fallible attention aids, never fact sources. Return only the focused JSON requested in the final assignment."""
    packet = {
        "book": {"title": book.get("title"), "author": book.get("author")},
        "chapter": {key: source.get(key) for key in ("sequence", "title", "chapterTitle", "sectionMarkers", "sourcePagination")},
        "prior_reader_context": prior_context,
        "gliner_identity_candidates": gliner.get("identityCandidates", []),
        "high_risk_action_candidates": action_passages,
    }
    user = f"""Read and retain this complete evidence packet. Do not collapse uncertain perception into fact. Do not answer any particular editorial task until the final focused assignment.

STRUCTURED ATTENTION PACKET
{json.dumps(packet, ensure_ascii=False)}

CANONICAL SOURCE PASSAGES
{server.evidence_passage_prompt(text)}"""
    # This fixed assistant turn gives every request a normal chat boundary while
    # keeping the token prefix byte-identical through the fork point.
    assistant = "I have read the canonical evidence packet and will now perform only the focused assignment that follows."
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
        {"role": "assistant", "content": assistant},
    ]


def ensure_experiment_gliner(
    book: dict[str, object], source: dict[str, object], chapter_sequence: int, output_path: Path,
) -> dict[str, object]:
    """Use a durable GLiNER result when available; otherwise make a /tmp-only one."""
    durable = server.read_json_artifact(server.gliner_signals_path(book, chapter_sequence))
    if durable.get("status") == "complete":
        return durable
    runtime = server.ROOT / ".venv-gliner" / "bin" / "python"
    runner = server.ROOT / "tools" / "gliner_chapter_spike.py"
    if not runtime.is_file() or not runner.is_file():
        return {"status": "unavailable", "identityCandidates": []}
    source_path = output_path.with_suffix(".gliner-source.txt")
    gliner_path = output_path.with_suffix(".gliner.json")
    text = str(source.get("text") or "")
    source_path.write_text(text, encoding="utf-8")
    try:
        completed = subprocess.run(
            [str(runtime), str(runner), str(source_path), "--model", server.GLINER_MODEL_ID,
             "--output", str(gliner_path), "--skip-events"],
            cwd=server.ROOT, capture_output=True, text=True, timeout=600, check=False,
        )
        if completed.returncode:
            raise RuntimeError((completed.stderr or completed.stdout or "GLiNER failed")[-1000:])
        artifact = json.loads(gliner_path.read_text(encoding="utf-8"))
        artifact.update({
            "status": "complete", "chapterSequence": chapter_sequence,
            "identityCandidates": server.gliner_identity_candidates(artifact, text),
        })
        write_artifact(gliner_path, artifact)
        return artifact
    finally:
        source_path.unlink(missing_ok=True)


def reconciliation_branch(
    branches: list[dict[str, object]], validation_issues: list[dict[str, object]],
) -> tuple[list[dict[str, str]], dict[str, object]]:
    results = {str(item.get("id")): item.get("result") for item in branches if isinstance(item.get("result"), dict)}
    identity = results.get("identity") if isinstance(results.get("identity"), dict) else {}
    action_audit = [
        audit
        for branch_id, result in results.items()
        if branch_id.startswith("action-audit-") and isinstance(result, dict)
        for audit in result.get("action_audit", [])
        if isinstance(audit, dict)
    ]
    summary = results.get("summary") if isinstance(results.get("summary"), dict) else {}
    dossier = results.get("dossier") if isinstance(results.get("dossier"), dict) else {}
    summary_view = summary.get("summary") if isinstance(summary.get("summary"), dict) else {}
    dossier_view = dossier.get("dossier") if isinstance(dossier.get("dossier"), dict) else {}
    editorial = results.get("editorial") if isinstance(results.get("editorial"), dict) else {}
    assessment = results.get("assessment") if isinstance(results.get("assessment"), dict) else {}
    compact = {
        "cast": identity.get("cast", []),
        "action_audit": action_audit,
        "summary": {
            "prose": summary_view.get("summary"),
            "key_points": summary_view.get("key_points", []),
            "ending_state": summary_view.get("ending_state", []),
            "question_details": summary_view.get("question_details", []),
        },
        "dossier": {
            "synopsis": dossier_view.get("synopsis"),
            "facts": dossier_view.get("facts", []),
            "events": dossier_view.get("events", []),
            "current_times": dossier_view.get("current_times", []),
            "timeline_observations": dossier_view.get("timeline_observations", []),
            "question_details": dossier_view.get("question_details", []),
        },
        "editorial": editorial.get("editorial"),
        "assessment": assessment.get("assessment"),
        "deterministic_validation_issues": validation_issues,
    }
    system = """You are a terse contradiction linter, not a manuscript reader. Inspect only the supplied branch outputs. Treat exact evidence quotations as authority. Return surgical correction records, never rewritten essays or hidden deliberation. Preserve actors, chronology, causality, and epistemic qualifiers."""
    user = f"""Inspect these focused branch outputs for contradictions and unsupported synthesis.

{json.dumps(compact, ensure_ascii=False)}

Return at most eight material corrections. For each, copy the exact offending claim and provide a concise replacement. Check prose, question explanations, aliases, editorial claims, assessment rationales, speaker attribution, chronology, and action omissions. Do not repeat supported material. If no correction is needed, return an empty list."""
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
        {"role": "assistant", "content": "I will reconcile only the supplied branch outputs and exact evidence."},
    ]
    schema = {
        "type": "object",
        "properties": {
            "corrections": {
                "type": "array",
                "maxItems": 8,
                "items": {
                    "type": "object",
                    "properties": {
                        "target": {"type": "string", "minLength": 1},
                        "offending_claim": {"type": "string", "minLength": 1, "maxLength": 400},
                        "replacement": {"type": "string", "minLength": 1, "maxLength": 400},
                        "reason": {"type": "string", "minLength": 1, "maxLength": 300},
                        "evidence_passage_ids": {"type": "array", "maxItems": 4, "items": {"type": "string"}},
                    },
                    "required": ["target", "offending_claim", "replacement", "reason", "evidence_passage_ids"],
                },
            },
            "unresolved_conflicts": {"type": "array", "maxItems": 4, "items": {"type": "string", "maxLength": 300}},
        },
        "required": ["corrections", "unresolved_conflicts"],
    }
    branch = {
        "id": "reconciliation", "label": "Cross-branch reconciliation",
        "properties": schema["properties"], "required": schema["required"],
        "instruction": "Return only the compact correction list now. Do not show your reasoning or rewrite whole outputs.",
    }
    return messages, branch


def deterministic_validation(
    branches: list[dict[str, object]], source_text: str,
    action_passages: list[dict[str, object]],
) -> list[dict[str, object]]:
    """Find cheap, concrete reasons to invoke semantic reconciliation."""
    issues: list[dict[str, object]] = []
    results = {
        str(item.get("id")): item.get("result")
        for item in branches if item.get("status") == "complete" and isinstance(item.get("result"), dict)
    }
    identity = results.get("identity") if isinstance(results.get("identity"), dict) else {}
    alias_owners: dict[str, set[str]] = {}
    for entity in identity.get("cast", []) if isinstance(identity.get("cast"), list) else []:
        if not isinstance(entity, dict):
            continue
        owner = str(entity.get("canonical_name") or entity.get("entity_id") or "unknown")
        for alias in entity.get("aliases", []) if isinstance(entity.get("aliases"), list) else []:
            normalized = re.sub(r"\s+", " ", str(alias).casefold()).strip()
            if normalized and normalized not in {"i", "he", "she", "they", "we", "it"}:
                alias_owners.setdefault(normalized, set()).add(owner)
    for alias, owners in alias_owners.items():
        if len(owners) > 1:
            issues.append({"kind": "alias_collision", "alias": alias, "owners": sorted(owners)})

    audited: dict[str, dict[str, object]] = {}
    for branch_id, result in results.items():
        if not branch_id.startswith("action-audit-") or not isinstance(result, dict):
            continue
        for item in result.get("action_audit", []) if isinstance(result.get("action_audit"), list) else []:
            if isinstance(item, dict):
                audited[str(item.get("passage_id") or "")] = item
    for passage in action_passages:
        passage_id = str(passage.get("passage_id") or "")
        item = audited.get(passage_id)
        if not item:
            issues.append({"kind": "missing_action_audit", "passage_id": passage_id})
        elif not item.get("actions"):
            issues.append({
                "kind": "empty_high_risk_action_audit", "passage_id": passage_id,
                "quote": str(passage.get("exact_source") or "")[:400],
            })

    def walk(value: object, path: str = "") -> None:
        if isinstance(value, list):
            for index, item in enumerate(value):
                walk(item, f"{path}[{index}]")
            return
        if not isinstance(value, dict):
            return
        evidence = value.get("evidence_ref")
        if isinstance(evidence, dict) and not server.resolve_source_evidence(source_text, evidence):
            issues.append({"kind": "unresolved_evidence", "path": path})
        for key, item in value.items():
            walk(item, f"{path}.{key}" if path else str(key))

    for branch_id, result in results.items():
        walk(result, branch_id)

    assessment = results.get("assessment") if isinstance(results.get("assessment"), dict) else {}
    assessment_view = assessment.get("assessment") if isinstance(assessment.get("assessment"), dict) else {}
    dimensions = assessment_view.get("dimensions") if isinstance(assessment_view.get("dimensions"), dict) else {}
    saleability = dimensions.get("saleability") if isinstance(dimensions.get("saleability"), dict) else {}
    if saleability and not saleability.get("applicable"):
        issues.append({"kind": "saleability_marked_inapplicable", "path": "assessment.dimensions.saleability"})
    for dimension, value in dimensions.items():
        if not isinstance(value, dict):
            continue
        for index, quote in enumerate(value.get("evidence", []) if isinstance(value.get("evidence"), list) else []):
            if str(quote).strip() and str(quote).strip() not in source_text:
                issues.append({
                    "kind": "non_exact_assessment_evidence",
                    "path": f"assessment.dimensions.{dimension}.evidence[{index}]",
                })
    return issues[:24]


def run_branch(
    *, model: str, messages: list[dict[str, str]], branch: dict[str, object],
    artifact: dict[str, Any], output_path: Path, experiment_deadline: float | None = None,
) -> tuple[dict[str, object], str, dict[str, object]]:
    payload = {
        "model": model,
        "stream": True,
        "think": False,
        "format": branch_schema(branch),
        "keep_alive": "60m",
        "options": {"temperature": 0.1},
        "messages": [*messages, {"role": "user", "content": str(branch["instruction"])}],
    }
    request = urllib.request.Request(
        "http://127.0.0.1:11434/api/chat",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    started = time.monotonic()
    started_at = utc_now()
    branch_state: dict[str, Any] = {
        "id": branch["id"], "label": branch["label"], "status": "running",
        "startedAt": started_at, "outputCharacters": 0, "lastActivityAt": started_at,
    }
    artifact["activeBranch"] = branch["id"]
    artifact.setdefault("branches", []).append(branch_state)
    write_artifact(output_path, artifact)
    parts: list[str] = []
    final_payload: dict[str, object] = {}
    last_checkpoint = time.monotonic()
    with urllib.request.urlopen(request, timeout=3600) as response:
        for line in response:
            if experiment_deadline is not None and time.monotonic() >= experiment_deadline:
                raise TimeoutError("The explicitly requested experiment budget was exceeded")
            if not line.strip():
                continue
            item = json.loads(line)
            content = str((item.get("message") or {}).get("content") or "")
            if content:
                parts.append(content)
                branch_state["outputCharacters"] = int(branch_state["outputCharacters"]) + len(content)
                branch_state["lastActivityAt"] = utc_now()
            if item.get("done"):
                final_payload = item
                break
            if time.monotonic() - last_checkpoint >= 5:
                write_artifact(output_path, artifact)
                last_checkpoint = time.monotonic()
    raw = "".join(parts)
    result = json.loads(raw)
    if not isinstance(result, dict):
        raise ValueError(f"{branch['label']} returned a non-object JSON value")
    metrics = {
        "promptTokens": final_payload.get("prompt_eval_count"),
        "cachedPromptTokens": final_payload.get("prompt_eval_cached_count"),
        "generatedTokens": final_payload.get("eval_count"),
        "loadDurationNanoseconds": final_payload.get("load_duration"),
        "promptDurationNanoseconds": final_payload.get("prompt_eval_duration"),
        "generationDurationNanoseconds": final_payload.get("eval_duration"),
        "totalDurationNanoseconds": final_payload.get("total_duration"),
        "doneReason": final_payload.get("done_reason"),
    }
    prompt_tokens = int(metrics.get("promptTokens") or 0)
    cached_tokens = int(metrics.get("cachedPromptTokens") or 0)
    metrics["cacheFraction"] = round(cached_tokens / prompt_tokens, 4) if prompt_tokens else None
    branch_state.update({
        "status": "complete", "completedAt": utc_now(),
        "durationSeconds": round(time.monotonic() - started, 1),
        "metrics": metrics, "rawResponse": raw, "result": result,
    })
    write_artifact(output_path, artifact)
    return result, raw, metrics


def probe_results(branches: list[dict[str, object]], action_passages: list[dict[str, object]]) -> dict[str, object]:
    audits = [
        audit
        for branch in branches
        if str(branch.get("id") or "").startswith("action-audit-") and isinstance(branch.get("result"), dict)
        for audit in branch["result"].get("action_audit", [])
        if isinstance(audit, dict)
    ]
    return {
        "selectedActionPassages": len(action_passages),
        "auditedActionPassages": len(audits),
        "extractedActions": sum(len(item.get("actions") or []) for item in audits),
        "multiActionPassages": sum(1 for item in audits if len(item.get("actions") or []) > 1),
        "emptyActionPassages": [str(item.get("passage_id") or "") for item in audits if not item.get("actions")],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--book-id", required=True)
    parser.add_argument("--chapter", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model")
    parser.add_argument("--without-review", action="store_true")
    parser.add_argument("--budget-minutes", type=float, default=0.0, help="Optional explicit wall-clock ceiling; zero means no target.")
    args = parser.parse_args()

    book = server.find_book(args.book_id)
    if not book:
        raise SystemExit(f"Unknown book: {args.book_id}")
    source = server.load_chapter_source(book, args.chapter)
    if not source:
        raise SystemExit(f"Missing canonical chapter {args.chapter}")
    # This experiment is read-only with respect to Bookinator's durable
    # ledger. load_pipeline() deliberately reconciles and persists migrations,
    # which is inappropriate for an out-of-band A/B run.
    pipeline_path = server.pipeline_path(book)
    pipeline = server.read_json_artifact(pipeline_path) if pipeline_path else {}
    chapter = next((item for item in pipeline.get("chapters", []) if int(item.get("sequence") or item.get("number") or 0) == args.chapter), None)
    if not isinstance(chapter, dict):
        raise SystemExit(f"Missing pipeline chapter {args.chapter}")
    control_path = server.chapter_reading_path(book, args.chapter)
    control = server.read_json_artifact(control_path)
    model = args.model or str(control.get("model") or "qwen3.8:27b")
    control_input = control.get("input") if isinstance(control.get("input"), dict) else {}
    prior_context = control_input.get("priorContext") if isinstance(control_input.get("priorContext"), dict) else {}
    if not prior_context:
        narrative_chapters = [item for item in pipeline.get("chapters", []) if not server.is_front_matter(item)]
        chapter_index = narrative_chapters.index(chapter) if chapter in narrative_chapters else -1
        if chapter_index > 0:
            previous = narrative_chapters[chapter_index - 1]
            previous_sequence = int(previous.get("sequence") or previous.get("number") or 0)
            context_artifact = server.read_json_artifact(server.cumulative_context_path(book, previous_sequence))
            if isinstance(context_artifact.get("context"), dict):
                prior_context = context_artifact["context"]
    gliner = ensure_experiment_gliner(book, source, args.chapter, args.output)
    action_passages = rank_action_passages(str(source.get("text") or ""))
    messages = common_messages(book, chapter, source, prior_context, gliner, action_passages)
    branches = branch_definitions(not args.without_review, action_passages)
    artifact: dict[str, Any] = {
        "schema": "bookinator-semantic-fork-experiment-v4",
        "status": "running", "startedAt": utc_now(), "bookId": args.book_id,
        "chapterSequence": args.chapter, "chapterTitle": chapter.get("title"),
        "model": model, "controlArtifact": str(control_path),
        "controlTiming": ({
            "primaryDurationSeconds": control.get("primaryDurationSeconds"),
            "consistencyDurationSeconds": control.get("consistencyDurationSeconds"),
            "totalDurationSeconds": control.get("durationSeconds"),
        } if control.get("status") == "complete" else None),
        "gliner": {
            "status": gliner.get("status"), "model": gliner.get("model"),
            "candidateCount": len(gliner.get("identityCandidates", [])),
        },
        "commonPrefix": {"messages": messages, "characterCount": sum(len(item["content"]) for item in messages)},
        "budgetMinutes": args.budget_minutes or None,
        "selectedActionPassages": action_passages,
        "branchOrder": [item["id"] for item in branches] + ["reconciliation"], "branches": [],
    }
    write_artifact(args.output, artifact)
    experiment_started = time.monotonic()
    experiment_deadline = experiment_started + (args.budget_minutes * 60) if args.budget_minutes > 0 else None
    try:
        for branch in branches:
            print(f"Starting {branch['label']}…", flush=True)
            try:
                run_branch(
                    model=model, messages=messages, branch=branch, artifact=artifact,
                    output_path=args.output, experiment_deadline=experiment_deadline,
                )
            except Exception as error:
                failed = artifact["branches"][-1]
                failed.update({
                    "status": "failed", "completedAt": utc_now(),
                    "durationSeconds": round(time.monotonic() - experiment_started, 1),
                    "error": f"{type(error).__name__}: {error}",
                })
                artifact.setdefault("componentErrors", []).append({
                    "id": branch["id"], "error": failed["error"],
                })
                write_artifact(args.output, artifact)
                if isinstance(error, TimeoutError):
                    break
        validation_issues = deterministic_validation(artifact["branches"], str(source.get("text") or ""), action_passages)
        artifact["validationIssues"] = validation_issues
        reconciled: dict[str, object] | None = None
        if validation_issues and not any(isinstance(item, dict) and item.get("error", "").startswith("TimeoutError:") for item in artifact.get("componentErrors", [])):
            reconcile_messages, reconcile = reconciliation_branch(artifact["branches"], validation_issues)
            print(f"Starting {reconcile['label']}…", flush=True)
            try:
                reconciled, _, _ = run_branch(
                    model=model, messages=reconcile_messages, branch=reconcile,
                    artifact=artifact, output_path=args.output, experiment_deadline=experiment_deadline,
                )
            except Exception as error:
                failed = artifact["branches"][-1]
                failed.update({
                    "status": "failed", "completedAt": utc_now(),
                    "durationSeconds": round(time.monotonic() - experiment_started, 1),
                    "error": f"{type(error).__name__}: {error}",
                })
                artifact.setdefault("componentErrors", []).append({"id": "reconciliation", "error": failed["error"]})
        else:
            artifact["reconciliationStatus"] = "skipped-no-deterministic-findings" if not validation_issues else "skipped-budget-exceeded"
        artifact.update({
            "status": "complete_with_attention" if artifact.get("componentErrors") else "complete",
            "completedAt": utc_now(),
            "durationSeconds": round(time.monotonic() - experiment_started, 1),
            "activeBranch": None, "structuralProbes": probe_results(artifact["branches"], action_passages),
            "reconciled": reconciled,
        })
    except Exception as error:
        artifact.update({
            "status": "failed", "completedAt": utc_now(),
            "durationSeconds": round(time.monotonic() - experiment_started, 1),
            "error": f"{type(error).__name__}: {error}",
        })
        for branch_state in reversed(artifact.get("branches", [])):
            if branch_state.get("status") == "running":
                branch_state.update({"status": "failed", "completedAt": utc_now(), "error": artifact["error"]})
                break
        raise
    finally:
        write_artifact(args.output, artifact)


if __name__ == "__main__":
    main()
