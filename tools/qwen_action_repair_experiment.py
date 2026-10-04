#!/usr/bin/env python3
"""Run a small, evidence-bounded repair after an action-scaffold reading.

The full chapter has already been read. This experiment finds material action
passages that did not survive into structured views, gives Qwen only those
gaps plus anchored existing claims, and asks for an append-only repair patch.
It never rewrites Bookinator's durable analysis artifacts.
"""

from __future__ import annotations

import argparse
import json
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from bookinator.server import __main__ as server


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def evidence_ref(item: object) -> dict[str, object] | None:
    if not isinstance(item, dict):
        return None
    value = item.get("evidence_ref")
    return value if isinstance(value, dict) and value.get("passage_id") else None


def claim_inventory(treatment: dict[str, object]) -> list[dict[str, object]]:
    inventory: list[dict[str, object]] = []

    def add(path: str, values: object, claim_key: str) -> None:
        if not isinstance(values, list):
            return
        for index, item in enumerate(values):
            ref = evidence_ref(item)
            if not isinstance(item, dict) or not ref:
                continue
            inventory.append({
                "claim_id": f"{path}:{index}",
                "path": path,
                "claim": str(item.get(claim_key) or ""),
                "subject": str(item.get("subject") or ""),
                "evidence_ref": ref,
            })

    summary = treatment.get("summary") if isinstance(treatment.get("summary"), dict) else {}
    add("summary.key_points", summary.get("key_points"), "claim")
    add("summary.ending_state", summary.get("ending_state"), "fact")
    dossier = treatment.get("dossier") if isinstance(treatment.get("dossier"), dict) else {}
    for field in ("facts", "events", "entities", "locations", "current_times", "promises", "timeline_observations"):
        add(f"dossier.{field}", dossier.get(field), "claim")
    ledger = treatment.get("entity_chapter_ledger") if isinstance(treatment.get("entity_chapter_ledger"), list) else []
    for entity_index, entity in enumerate(ledger):
        if not isinstance(entity, dict):
            continue
        for action_index, action in enumerate(entity.get("actions_and_experiences", [])):
            ref = evidence_ref(action)
            if not isinstance(action, dict) or not ref:
                continue
            inventory.append({
                "claim_id": f"entity_chapter_ledger:{entity_index}.actions_and_experiences:{action_index}",
                "path": "entity_chapter_ledger.actions_and_experiences",
                "claim": str(action.get("claim") or ""),
                "subject": str(entity.get("entity_id") or ""),
                "evidence_ref": ref,
            })
    return inventory


def action_coverage_gaps(treatment: dict[str, object], inventory: list[dict[str, object]]) -> list[dict[str, object]]:
    audit = treatment.get("specialist_audit") if isinstance(treatment.get("specialist_audit"), dict) else {}
    material = [
        item for item in audit.get("action_passages", [])
        if isinstance(item, dict) and item.get("verdict") == "material_action" and item.get("passage_id")
    ]
    paths_by_passage: dict[str, set[str]] = {}
    for claim in inventory:
        ref = claim.get("evidence_ref") if isinstance(claim.get("evidence_ref"), dict) else {}
        passage_id = str(ref.get("passage_id") or "")
        if passage_id:
            paths_by_passage.setdefault(passage_id, set()).add(str(claim.get("path") or ""))
    gaps: list[dict[str, object]] = []
    target_prefixes = {
        "summary_key_point": "summary.",
        "dossier_event": "dossier.events",
        "ledger_action": "entity_chapter_ledger.actions_and_experiences",
    }
    for action in material:
        passage_id = str(action["passage_id"])
        represented = paths_by_passage.get(passage_id, set())
        for target, prefix in target_prefixes.items():
            if not any(path.startswith(prefix) for path in represented):
                gaps.append({
                    "passage_id": passage_id,
                    "target": target,
                    "audited_actor": action.get("actor_entity_id"),
                    "audited_action": action.get("literal_action"),
                    "audited_resulting_state": action.get("resulting_state"),
                    "evidence_ref": action.get("evidence_ref"),
                })
    return gaps


def repair_schema() -> dict[str, object]:
    evidence = server.source_evidence_ref_schema()
    return {
        "type": "object",
        "properties": {
            "reviewed_gaps": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "passage_id": {"type": "string", "minLength": 1},
                        "target": {"type": "string", "enum": ["summary_key_point", "dossier_event", "ledger_action"]},
                        "verdict": {"type": "string", "enum": ["add", "omit_as_immaterial"]},
                        "reason": {"type": "string", "minLength": 1},
                    },
                    "required": ["passage_id", "target", "verdict", "reason"],
                },
            },
            "additions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "target": {"type": "string", "enum": ["summary_key_point", "summary_ending_state", "dossier_event", "ledger_action"]},
                        "claim": {"type": "string", "minLength": 1},
                        "subject": {"type": "string", "minLength": 1},
                        "evidence_ref": evidence,
                        "reason": {"type": "string", "minLength": 1},
                    },
                    "required": ["target", "claim", "subject", "evidence_ref", "reason"],
                },
            },
            "claim_corrections": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "claim_id": {"type": "string", "minLength": 1},
                        "replacement_claim": {"type": "string", "minLength": 1},
                        "replacement_subject": {"type": "string", "minLength": 1},
                        "evidence_ref": evidence,
                        "reason": {"type": "string", "minLength": 1},
                    },
                    "required": ["claim_id", "replacement_claim", "replacement_subject", "evidence_ref", "reason"],
                },
            },
            "revised_summary_text": {"type": "string"},
            "repair_summary": {"type": "string", "minLength": 1},
        },
        "required": ["reviewed_gaps", "additions", "claim_corrections", "revised_summary_text", "repair_summary"],
    }


def repair_prompt(treatment: dict[str, object], inventory: list[dict[str, object]], gaps: list[dict[str, object]]) -> str:
    summary = treatment.get("summary") if isinstance(treatment.get("summary"), dict) else {}
    dossier = treatment.get("dossier") if isinstance(treatment.get("dossier"), dict) else {}
    cast = treatment.get("cast") if isinstance(treatment.get("cast"), list) else []
    ledger = treatment.get("entity_chapter_ledger") if isinstance(treatment.get("entity_chapter_ledger"), list) else []
    return f"""Repair a completed chapter reading using only this compact, source-anchored packet. Do not reread or rewrite the chapter from imagination. Return a JSON patch matching the supplied schema.

The action audit is a fallible proposal, but every listed evidence_ref is exact canonical source. Review every coverage gap exactly once. Add a missing claim only when the passage is materially necessary in that target; otherwise explicitly omit_as_immaterial. A Summary may omit secondary motion, but the Dossier event ledger should preserve concrete consequential action, and an entity ledger should preserve what its actor materially did or experienced.

Audit the existing claim inventory for concrete errors exposed by its own exact quotation. Correct grammatical actors, literal actions, chronology, negation, and resulting states. Do not stylistically rewrite sound claims. Never turn suggestion into certainty: “as I thought, hid herself” is the narrator's perception, not proof. Do not say an actor vanished when the source gives a movement or destination. Do not credit a doctor with an examination performed by servants.

If additions materially change the digest, return a complete revised_summary_text; otherwise return an empty string. Patches append or replace structured claims; they never erase the source audit.

CAST
{json.dumps(cast, ensure_ascii=False)}

CURRENT SUMMARY
{json.dumps(summary, ensure_ascii=False)}

CURRENT DOSSIER
{json.dumps(dossier, ensure_ascii=False)}

CURRENT ENTITY LEDGER
{json.dumps(ledger, ensure_ascii=False)}

ANCHORED CLAIM INVENTORY
{json.dumps(inventory, ensure_ascii=False)}

POTENTIAL COVERAGE GAPS
{json.dumps(gaps, ensure_ascii=False)}
"""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--treatment", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model", default="qwen3.8:27b")
    args = parser.parse_args()

    source_artifact = json.loads(args.treatment.read_text(encoding="utf-8"))
    treatment = source_artifact.get("treatment") if isinstance(source_artifact.get("treatment"), dict) else {}
    if not treatment:
        raise SystemExit("Treatment artifact has no completed treatment response.")
    inventory = claim_inventory(treatment)
    gaps = action_coverage_gaps(treatment, inventory)
    prompt = repair_prompt(treatment, inventory, gaps)
    schema = repair_schema()
    artifact: dict[str, Any] = {
        "schema": "bookinator-action-repair-experiment-v1",
        "status": "running",
        "startedAt": utc_now(),
        "model": args.model,
        "sourceTreatment": str(args.treatment),
        "input": {"coverageGaps": gaps, "claimInventory": inventory, "prompt": prompt, "schema": schema},
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(artifact, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Auditing {len(gaps)} potential coverage gaps and {len(inventory)} anchored claims.", flush=True)
    started = time.monotonic()
    try:
        repair, raw = server.run_structured_model(
            prompt, args.model, schema, threading.Event(),
            "experiment:carmilla:chapter-1:action-repair", activity="action coverage repair experiment",
        )
        artifact.update({
            "status": "complete", "completedAt": utc_now(),
            "durationSeconds": round(time.monotonic() - started, 1),
            "repair": repair, "rawResponse": raw,
        })
        print(json.dumps(repair, ensure_ascii=False, indent=2), flush=True)
    except Exception as error:
        artifact.update({
            "status": "failed", "completedAt": utc_now(),
            "durationSeconds": round(time.monotonic() - started, 1),
            "error": f"{type(error).__name__}: {error}",
        })
        raise
    finally:
        args.output.write_text(json.dumps(artifact, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
