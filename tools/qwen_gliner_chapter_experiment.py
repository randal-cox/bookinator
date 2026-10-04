#!/usr/bin/env python3
"""Compare an existing Chapter Reading with one GLiNER-assisted Qwen read.

This intentionally does not write Bookinator's durable pipeline artifacts. The
existing reading is the control; the treatment and its complete input packet
are written to a separate experiment artifact for inspection.
"""

from __future__ import annotations

import argparse
import copy
import json
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from bookinator.server import __main__ as server


IDENTITY_LABELS = {"person", "named animal", "group", "creature", "supernatural force"}
ACTION_CUE = re.compile(
    r"\b(?:"
    r"start(?:ed|s|ing)?|slip(?:ped|s|ping)?|hid(?:e|den|ing)?|run|ran|running|"
    r"walk(?:ed|s|ing)?|enter(?:ed|s|ing)?|leav(?:e|es|ing)|left|go|goes|going|gone|went|"
    r"come|comes|coming|came|stand|stands|standing|stood|sit|sits|sitting|sat|"
    r"lie|lies|lying|lay|lain|fall|falls|falling|fell|rise|rises|rising|rose|"
    r"turn(?:ed|s|ing)?|open(?:ed|s|ing)?|clos(?:e|es|ed|ing)|take|takes|taking|took|taken|"
    r"put|puts|putting|draw|draws|drawing|drew|drawn|carry|carries|carried|carrying|"
    r"throw|throws|throwing|threw|thrown|strike|strikes|striking|struck|"
    r"touch(?:ed|es|ing)?|caress(?:ed|es|ing)?|kiss(?:ed|es|ing)?|"
    r"wake|wakes|waking|woke|woken|waken|wakens|wakened|wakening|sleep|sleeps|sleeping|slept|"
    r"appear(?:ed|s|ing)?|disappear(?:ed|s|ing)?|vanish(?:ed|es|ing)?|"
    r"become|becomes|becoming|became|grow|grows|growing|grew|remain(?:ed|s|ing)?|"
    r"die|dies|died|dying|cry|cries|cried|crying|scream(?:ed|s|ing)?|"
    r"find|finds|finding|found|search(?:ed|es|ing)?|look(?:ed|s|ing)?|see|sees|seeing|saw|seen"
    r")\b",
    re.I,
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def evidence_for_span(passages: list[dict[str, object]], start: int, end: int) -> dict[str, object] | None:
    overlapping = [
        item for item in passages
        if int(item.get("characterStart") or 0) <= start
        and int(item.get("characterEnd") or 0) >= end
    ]
    if not overlapping:
        return None
    passage = min(overlapping, key=lambda item: int(item.get("characterEnd") or 0) - int(item.get("characterStart") or 0))
    return {
        "passage_id": passage.get("id"),
        "quote": passage.get("text"),
        "character_start": passage.get("characterStart"),
        "character_end": passage.get("characterEnd"),
    }


def build_specialist_packet(gliner: dict[str, object], text: str) -> dict[str, object]:
    passages = server.source_evidence_passages(text)
    raw = gliner.get("raw") if isinstance(gliner.get("raw"), dict) else {}
    mention_groups = raw.get("mentions") if isinstance(raw.get("mentions"), dict) else {}
    entities = mention_groups.get("entities") if isinstance(mention_groups.get("entities"), dict) else {}
    grouped_candidates: dict[tuple[str, str], dict[str, object]] = {}
    for label, mentions in entities.items():
        if not isinstance(mentions, list):
            continue
        for mention in mentions:
            if not isinstance(mention, dict):
                continue
            confidence = float(mention.get("confidence") or 0)
            start = int(mention.get("start") or 0)
            end = int(mention.get("end") or 0)
            value = str(mention.get("text") or "").strip()
            # Low-confidence and pronoun-only candidates add output work but
            # no useful identity constraint. They remain preserved in the raw
            # GLiNER artifact, just not in Qwen's compact treatment packet.
            if confidence < 0.55 or not value or re.fullmatch(r"(?:he|she|him|her|they|them|it|we|us|i|me)", value, re.I):
                continue
            evidence = evidence_for_span(passages, start, end)
            if not evidence:
                continue
            if str(label) not in IDENTITY_LABELS:
                continue
            normalized_value = re.sub(r"^(?:my|the|a|an)\s+", "", value.casefold()).strip()
            key = (str(label), normalized_value)
            candidate = grouped_candidates.setdefault(key, {
                "proposed_type": str(label),
                "exact_mention": value,
                "max_confidence": 0.0,
                "mentions": [],
            })
            candidate["max_confidence"] = max(float(candidate["max_confidence"]), confidence)
            candidate["mentions"].append({
                "confidence": round(confidence, 4),
                "character_start": start,
                "character_end": end,
                "evidence_ref": evidence,
            })

    candidates = []
    for candidate_index, candidate in enumerate(grouped_candidates.values(), 1):
        mentions = candidate["mentions"]
        # Keep source order. For "under the bed," for example, the first
        # occurrence states the concrete action while the higher-confidence
        # second occurrence only describes the servants' search.
        candidate["mentions"] = sorted(mentions, key=lambda item: int(item["character_start"]))
        candidate["max_confidence"] = round(float(candidate["max_confidence"]), 4)
        candidates.append({"candidate_id": f"G{candidate_index:03d}", **candidate})

    action_passages = []
    for passage in passages:
        exact = str(passage.get("text") or "")
        cue_words = [match.group(0) for match in ACTION_CUE.finditer(exact)]
        if not cue_words:
            continue
        passage_start = int(passage.get("characterStart") or 0)
        passage_end = int(passage.get("characterEnd") or 0)
        nearby = [
            candidate["candidate_id"]
            for candidate in candidates
            if any(
                int(mention["character_start"]) < passage_end
                and int(mention["character_end"]) > passage_start
                for mention in candidate["mentions"]
            )
        ]
        # Prefer concrete passages with several movements or an identity
        # mention. This is intentionally recall-oriented: Qwen must decide
        # whether each exact passage describes a material action or background.
        score = len(cue_words) * 2 + len(nearby) * 3
        action_passages.append({
            "passage_id": passage.get("id"),
            "exact_source": exact,
            "character_start": passage_start,
            "character_end": passage_end,
            "cue_words": cue_words,
            "nearby_candidate_ids": nearby,
            "selection_score": score,
        })
    action_passages = sorted(
        sorted(action_passages, key=lambda item: (-int(item["selection_score"]), int(item["character_start"])))[:16],
        key=lambda item: int(item["character_start"]),
    )
    return {
        "schema": "bookinator-gliner-qwen-treatment-v2",
        "model": gliner.get("model"),
        "source_characters": len(text),
        "entity_candidates": candidates,
        "action_passages": action_passages,
        "excluded": {
            "generic_events": "Excluded after the spike mixed actors, actions, targets, and resulting states.",
            "tag_hypotheses": "Kept out of Chapter Reading so tag auditing cannot distract or inflate this call.",
            "low_confidence_or_pronoun_mentions": "Retained in the raw GLiNER artifact but omitted from this compact Qwen packet.",
        },
        "interpretation": "Every item is a fallible attention signal. The canonical source is the only authority.",
    }


def treatment_schema(include_review: bool) -> dict[str, object]:
    schema = copy.deepcopy(server.chapter_reading_schema(include_review))
    evidence = server.source_evidence_ref_schema()
    schema["properties"]["specialist_audit"] = {
        "type": "object",
        "properties": {
            "entity_candidates": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "candidate_id": {"type": "string", "minLength": 1},
                        "verdict": {"type": "string", "enum": ["keep", "correct", "reject"]},
                        "canonical_name": {"type": "string"},
                        "entity_type": {"type": "string"},
                        "reason": {"type": "string", "minLength": 1},
                        "evidence_ref": evidence,
                    },
                    "required": ["candidate_id", "verdict", "canonical_name", "entity_type", "reason", "evidence_ref"],
                },
            },
            "action_passages": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "passage_id": {"type": "string", "minLength": 1},
                        "verdict": {"type": "string", "enum": ["material_action", "background_or_description"]},
                        "actor_entity_id": {"type": "string"},
                        "literal_action": {"type": "string", "minLength": 1},
                        "resulting_state": {"type": "string", "minLength": 1},
                        "reason": {"type": "string", "minLength": 1},
                        "evidence_ref": evidence,
                    },
                    "required": ["passage_id", "verdict", "actor_entity_id", "literal_action", "resulting_state", "reason", "evidence_ref"],
                },
            },
        },
        "required": ["entity_candidates", "action_passages"],
    }
    schema["properties"]["entity_chapter_ledger"] = {
        "type": "array",
        "items": {
            "type": "object",
            "properties": {
                "entity_id": {"type": "string", "minLength": 1},
                "candidate_ids": {"type": "array", "items": {"type": "string"}},
                "state_on_entry": {"type": "string", "minLength": 1},
                "actions_and_experiences": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {"claim": {"type": "string", "minLength": 1}, "evidence_ref": evidence},
                        "required": ["claim", "evidence_ref"],
                    },
                },
                "relationship_changes": {"type": "array", "items": {"type": "string"}},
                "knowledge_changes": {"type": "array", "items": {"type": "string"}},
                "material_changes": {"type": "array", "items": {"type": "string"}},
                "state_on_exit": {"type": "string", "minLength": 1},
            },
            "required": ["entity_id", "candidate_ids", "state_on_entry", "actions_and_experiences", "relationship_changes", "knowledge_changes", "material_changes", "state_on_exit"],
        },
    }
    schema["required"].extend(["specialist_audit", "entity_chapter_ledger"])
    return schema


def treatment_prompt(base_prompt: str, packet: dict[str, object]) -> str:
    return f"""{base_prompt}

SPECIALIST ATTENTION SCAFFOLD — AUDIT, DO NOT OBEY
The following was produced by a fast, fallible encoder. It proposes exact
identity mentions and deterministically selected action-bearing passages; it does not establish identity, role,
causality, action, or story fact. Generic event extraction was deliberately
excluded because it failed to preserve grammatical actors and resulting
states.

Before finalizing cast, summary, dossier, editorial, or assessment:
1. Audit every supplied entity candidate as keep, correct, or reject. Preserve
   its candidate_id, append a corrected canonical identity when needed, and
   explain the decision from the exact canonical source.
2. Audit EVERY supplied action passage exactly once. Identify its grammatical
   actor, literal action, and resulting state when it contains material action;
   otherwise mark it background_or_description. A cue word is not proof.
3. Build entity_chapter_ledger only for entities that materially act,
   experience something, change, learn, or change a relationship in this
   chapter. Do not manufacture boilerplate ledgers for merely mentioned people.
   Do not infer disappearance when the source states a concrete movement or
   destination. Do not assign an action to a nearby named entity.
4. Cross-check Summary and Dossier against the action audit. A material action
   cannot silently disappear from those views, and a generic paraphrase cannot
   contradict its literal movement or resulting state. Cite canonical passage
   evidence—not the specialist packet—as authority.

SPECIALIST PACKET
{json.dumps(packet, ensure_ascii=False)}
"""


def baseline_response(artifact: dict[str, object]) -> dict[str, object]:
    output = artifact.get("output") if isinstance(artifact.get("output"), dict) else {}
    value = output.get("primaryResponse") or artifact.get("primaryResponse")
    return value if isinstance(value, dict) else {}


def comparison_snapshot(control: dict[str, object], treatment: dict[str, object]) -> dict[str, object]:
    def summary(value: dict[str, object]) -> str:
        nested = value.get("summary") if isinstance(value.get("summary"), dict) else {}
        return str(nested.get("summary") or "")

    def cast_names(value: dict[str, object]) -> list[str]:
        return [
            str(item.get("canonical_name") or "")
            for item in value.get("cast", []) if isinstance(item, dict)
        ]

    def probes(value: str) -> dict[str, bool]:
        folded = value.casefold()
        return {
            "says_hidden_under_bed": "under the bed" in folded or "beneath the bed" in folded,
            "says_vanished": "vanish" in folded or "disappear" in folded,
            "preserves_floor_action": "floor" in folded,
        }

    control_summary = summary(control)
    treatment_summary = summary(treatment)
    return {
        "control": {"summary": control_summary, "cast": cast_names(control), "probes": probes(control_summary)},
        "treatment": {"summary": treatment_summary, "cast": cast_names(treatment), "probes": probes(treatment_summary)},
        "treatmentAuditCounts": {
            "entityCandidates": len((treatment.get("specialist_audit") or {}).get("entity_candidates", [])) if isinstance(treatment.get("specialist_audit"), dict) else 0,
            "actionPassages": len((treatment.get("specialist_audit") or {}).get("action_passages", [])) if isinstance(treatment.get("specialist_audit"), dict) else 0,
            "entityLedger": len(treatment.get("entity_chapter_ledger", [])) if isinstance(treatment.get("entity_chapter_ledger"), list) else 0,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--book-id", required=True)
    parser.add_argument("--chapter", type=int, required=True)
    parser.add_argument("--gliner", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model")
    parser.add_argument("--without-review", action="store_true")
    args = parser.parse_args()

    book = server.find_book(args.book_id)
    if not book:
        raise SystemExit(f"Unknown book: {args.book_id}")
    source = server.load_chapter_source(book, args.chapter)
    if not source:
        raise SystemExit(f"Missing canonical chapter {args.chapter}")
    pipeline = server.add_pipeline_progress(server.load_pipeline(book))
    chapter = next(
        (item for item in pipeline.get("chapters", []) if int(item.get("sequence") or item.get("number") or 0) == args.chapter),
        None,
    )
    if not isinstance(chapter, dict):
        raise SystemExit(f"Missing pipeline chapter {args.chapter}")
    control_artifact = server.read_json_artifact(server.chapter_reading_path(book, args.chapter))
    control = baseline_response(control_artifact)
    if not control:
        raise SystemExit("The control chapter-reading artifact has no primary response.")
    gliner = json.loads(args.gliner.read_text(encoding="utf-8"))
    text = str(source.get("text") or "")
    packet = build_specialist_packet(gliner, text)
    include_review = not args.without_review
    base = server.chapter_reading_prompt(book, chapter, source, {}, include_review)
    prompt = treatment_prompt(base, packet)
    model = args.model or str(control_artifact.get("model") or "qwen3.8:27b")
    artifact: dict[str, Any] = {
        "schema": "bookinator-qwen-gliner-ab-v2",
        "status": "running",
        "startedAt": utc_now(),
        "bookId": args.book_id,
        "chapterSequence": args.chapter,
        "model": model,
        "controlArtifact": str(server.chapter_reading_path(book, args.chapter)),
        "glinerArtifact": str(args.gliner),
        "specialistPacket": packet,
        "input": {"prompt": prompt, "schema": treatment_schema(include_review)},
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(artifact, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Running {model} treatment with {len(packet['entity_candidates'])} identity signals and {len(packet['action_passages'])} exact action passages.", flush=True)
    started = time.monotonic()
    try:
        treatment, raw = server.run_structured_model(
            prompt, model, treatment_schema(include_review), threading.Event(),
            f"experiment:{args.book_id}:{args.chapter}", activity="GLiNER-assisted chapter reading experiment",
        )
        artifact.update({
            "status": "complete",
            "completedAt": utc_now(),
            "durationSeconds": round(time.monotonic() - started, 1),
            "rawResponse": raw,
            "treatment": treatment,
            "comparison": comparison_snapshot(control, treatment),
        })
        print(json.dumps(artifact["comparison"], ensure_ascii=False, indent=2), flush=True)
    except Exception as error:
        artifact.update({
            "status": "failed",
            "completedAt": utc_now(),
            "durationSeconds": round(time.monotonic() - started, 1),
            "error": f"{type(error).__name__}: {error}",
        })
        raise
    finally:
        args.output.write_text(json.dumps(artifact, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
