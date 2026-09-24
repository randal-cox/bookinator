from __future__ import annotations

import argparse
import base64
import copy
import gzip
import html
import hashlib
import importlib.util
import io
import json
import mimetypes
import os
import platform
import posixpath
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zipfile
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WEB_ROOT = ROOT / "web"
DOCS_ROOT = ROOT / "docs"
LOCAL_PACKAGES = ROOT / ".bookinator" / "packages"
DATA_ROOT = Path(os.environ.get("BOOKINATOR_DATA_DIR", ROOT / ".bookinator"))
SETTINGS_PATH = DATA_ROOT / "settings.json"
QUEUE_PATH = DATA_ROOT / "pipeline-queue.json"
QUEUE_ACTIONS_PATH = DATA_ROOT / "pipeline-actions.json"
DEFERRED_REFRESHES_PATH = DATA_ROOT / "deferred-analysis-refreshes.json"
BOOKS_ROOT = DATA_ROOT / "books"
LIBRARY_PATH = DATA_ROOT / "library.json"
LIBRARY_LOCK = threading.Lock()
PIPELINE_THREADS: dict[str, threading.Thread] = {}
PIPELINE_CANCEL_EVENTS: dict[str, threading.Event] = {}
ACTIVE_MODEL_RESPONSES: dict[str, object] = {}
ACTIVE_MODEL_RESPONSES_LOCK = threading.Lock()
STRUCTURED_MODEL_LOCK = threading.RLock()
LAST_STRUCTURED_MODEL = ""
QUEUE_THREAD: threading.Thread | None = None
QUEUE_CANCEL_EVENT = threading.Event()
QUEUE_ACTIONS: dict[str, str] = {}
QUEUE_LOCK = threading.Lock()
QUEUE_CURRENT_TASK: dict[str, str] = {}
DEFERRED_ANALYSIS_REFRESHES: dict[str, list[tuple[str, int]]] = {}
EXPLICIT_QUEUE_ACTIONS = {
    "prepare", "summarize", "restart", "whole-summary", "whole-dossier", "questions",
    "emotions", "emotion-restart", "tags", "tag-restart", "smells", "smell-restart",
    "dossiers", "dossier-restart", "chapter-pipeline",
    "deferred-refresh", "deferred-retry-failed",
}
BOOK_PRIORITY_ORDER = {"high": 0, "normal": 1, "low": 2, "shelved": 3}
if LOCAL_PACKAGES.exists():
    sys.path.insert(0, str(LOCAL_PACKAGES))
from bookinator.prose_cruft import analyze as analyze_prose_smells
MAX_PREVIEW_BYTES = 80 * 1024 * 1024
MODEL_ROLES = {
    "intake": "Manuscript intake",
    "reader": "Chapter reader",
    "tags": "Chapter tagger",
    "primary": "Primary analysis",
    "defender": "Adversarial defender",
    "judge": "Finding judge",
    "embedding": "Similarity search",
}
MODEL_CATALOG = [
    {"tag": "qwen3.5:9b", "sizeGb": 6.6, "tier": "quick", "label": "Quick reader", "use": "Intake, extraction, and inexpensive structured passes", "hf": "https://huggingface.co/Qwen"},
    {"tag": "qwen3.5:35b", "sizeGb": 24, "tier": "balanced", "label": "Balanced editor", "use": "Chapter reading and routine editorial roles", "hf": "https://huggingface.co/Qwen"},
    {"tag": "qwen3.5:122b", "sizeGb": 81, "tier": "primary", "label": "Primary editor", "use": "Whole-book synthesis, continuity, structure, and argument", "hf": "https://huggingface.co/Qwen"},
    {"tag": "qwen3:235b-a22b-instruct-2507-q8_0", "sizeGb": 250, "tier": "heavy", "label": "Heavyweight reviewer", "use": "Maximum-capability comparison and difficult adjudication", "hf": "https://huggingface.co/Qwen/Qwen3-235B-A22B-Instruct-2507"},
    {"tag": "qwen3-embedding:8b", "sizeGb": 4.7, "tier": "embedding", "label": "Similarity engine", "use": "Redundancy candidates and evidence retrieval", "hf": "https://huggingface.co/Qwen/Qwen3-Embedding-8B"},
]
API_FEATURES = {
    "chapterMapApproval": 1,
    "chapterMapEditing": 1,
    "provisionalAnalysis": 1,
    "globalPriorityQueue": 1,
    "chapterEmotions": 1,
    "chapterTags": 1,
    "chapterSmells": 1,
}

EMOTION_MODEL_ID = "j-hartmann/emotion-english-distilroberta-base"
EMOTION_SCHEMA_VERSION = "bookinator-emotion-v1"
EMOTION_LABELS = ("anger", "disgust", "fear", "joy", "neutral", "sadness", "surprise")
TAG_SCHEMA_VERSION = "bookinator-chapter-tags-v1"
TAG_TAXONOMY_VERSION = "bookinator-chapter-signals-v1"
TAG_PROMPT_VERSION = "chapter-tags-v2"
TAG_FAMILIES: dict[str, tuple[str, ...]] = {
    "prose_mode": ("action", "dialogue", "exposition", "description", "introspection", "narrative_summary", "investigation"),
    "chapter_function": ("orientation", "setup", "escalation", "complication", "discovery", "revelation", "confrontation", "relationship_change", "reversal", "setback", "payoff", "climax", "aftermath", "resolution", "transition", "travel"),
    "reader_dynamics": ("mystery", "suspense", "tension", "stakes", "urgency", "goal_progress", "story_state_change", "revelation_density", "causal_importance", "chapter_end_propulsion"),
    "narrated_time": ("primary_present", "flashback", "remembered_past", "flash_forward", "anticipated_future", "time_jump", "simultaneous_branch", "dream_or_vision", "hypothetical_scene", "nonlinear_uncertain"),
    "viewpoint": ("first_person", "second_person", "third_limited", "third_omniscient", "objective_external", "single_viewpoint", "multiple_viewpoints", "viewpoint_shift", "viewpoint_drift_candidate"),
    "mood": ("tense", "foreboding", "ominous", "uncanny", "horrific", "bleak", "melancholic", "intimate", "romantic", "hopeful", "playful", "comic", "cozy", "meditative", "dreamlike", "wondrous", "triumphant", "frenetic", "claustrophobic", "noir", "neutral_uncertain"),
    "genre_affinity": ("mystery", "thriller", "horror", "fantasy", "science_fiction", "romance", "historical", "crime", "adventure", "literary", "comedy", "drama"),
    "theme_topic": ("identity", "belonging", "family", "love", "loss", "power", "justice", "freedom", "duty", "memory", "mortality", "transformation", "isolation", "community", "faith", "truth"),
}

# Every derived artifact declares the stages it reads. Invalidation walks this
# graph transitively, so a structural rebuild cannot leave a green downstream
# artifact behind, while a summary-only redo cannot disturb independent
# dossier work.
PIPELINE_STAGE_DEPENDENCIES: dict[str, tuple[str, ...]] = {
    "source": (),
    "extraction": ("source",),
    "structure": ("extraction",),
    "chapter-archive": ("structure",),
    "chunking": ("chapter-archive",),
    "summaries": ("chapter-archive",),
    "emotions": ("chapter-archive",),
    "tags": ("chapter-archive",),
    "smells": ("chapter-archive",),
    "dossiers": ("chunking",),
    "question-tracker": ("summaries", "dossiers"),
    # The synthesis prompt consumes chapter summaries only. Independent
    # Dossier, emotion, tag, and smell passes must never hold it hostage.
    "whole-book-summary": ("summaries",),
    "whole-book-dossier": ("dossiers",),
}

# This is the authored-chapter work order inside one book. New chapter-scoped
# passes (tags, cruft checks, and similar work) belong here, with their inputs
# declared above, rather than in another book-wide loop.
CHAPTER_PIPELINE_STAGE_ORDER: tuple[str, ...] = ("summaries", "dossiers", "emotions", "tags", "smells")

# A rollup consumes only its own completed child artifacts. Adding another
# whole-book view means registering its collection, status field, and payload
# fields here—not inserting another ad hoc terminal condition into the queue.
STAGE_ROLLUP_DEFINITIONS: dict[str, dict[str, object]] = {
    "summary": {
        "action": "whole-summary",
        "dependencyStage": "whole-book-summary",
        "stageId": "summaries",
        "resultKey": "wholeBookSummary",
        "collection": "chapters",
        "statusField": "status",
        "payloadFields": ("sequence", "number", "title", "chapterTitle", "summary", "keyPoints", "newQuestions", "model", "completedAt"),
        "excludeFrontMatter": True,
    },
    "dossier": {
        "action": "whole-dossier",
        "dependencyStage": "whole-book-dossier",
        "stageId": "dossiers",
        "resultKey": "wholeBookDossier",
        "collection": "chunks",
        "statusField": "dossierStatus",
        "payloadFields": ("sequence", "chapterSequence", "chunkInChapter", "dossier", "dossierModel", "dossierCompletedAt"),
        "excludeFrontMatter": False,
    },
}

PIPELINE_STAGE_DEFINITIONS: dict[str, tuple[str, str]] = {
    "emotions": ("Chapter emotions", "Score the recognizable emotional texture of every chapter with the local Hartmann model."),
    "tags": ("Chapter tags", "Apply the fixed evidence-bearing editorial taxonomy with the assigned local model."),
    "smells": ("Smells", "Find source-linked prose problems locally, then ask the assigned editor model which candidates are worth showing."),
}


def pipeline_stage_dependents(stage_id: str) -> set[str]:
    """Return every stage transitively derived from stage_id."""
    dependents: set[str] = set()
    changed = True
    while changed:
        changed = False
        for candidate, parents in PIPELINE_STAGE_DEPENDENCIES.items():
            if candidate not in dependents and (stage_id in parents or any(parent in dependents for parent in parents)):
                dependents.add(candidate)
                changed = True
    return dependents


def pipeline_stage_ready(pipeline: dict[str, object], stage_id: str) -> bool:
    """A stage is runnable only when every declared input is current."""
    stages = {str(stage.get("id") or ""): str(stage.get("status") or "pending") for stage in pipeline.get("stages", [])}
    return all(stages.get(parent) == "complete" for parent in PIPELINE_STAGE_DEPENDENCIES.get(stage_id, ()))


def record_pipeline_dependencies(pipeline: dict[str, object]) -> None:
    pipeline["dependencySchema"] = "bookinator-pipeline-dependencies-v1"
    for stage in pipeline.get("stages", []):
        stage_id = str(stage.get("id") or "")
        stage["dependsOn"] = list(PIPELINE_STAGE_DEPENDENCIES.get(stage_id, ()))


def ensure_signal_stages(pipeline: dict[str, object]) -> None:
    """Migrate older ledgers without creating a second UI/backend contract."""
    repaired_setup: set[str] = set()
    stages = pipeline.setdefault("stages", [])
    existing = {str(stage.get("id") or "") for stage in stages}
    dossier_index = next((index for index, stage in enumerate(stages) if stage.get("id") == "dossiers"), len(stages))
    additions = []
    for stage_id in ("emotions", "tags", "smells"):
        if stage_id not in existing:
            label, detail = PIPELINE_STAGE_DEFINITIONS[stage_id]
            additions.append({"id": stage_id, "label": label, "status": "pending", "detail": detail})
    stages[dossier_index:dossier_index] = additions
    record_pipeline_dependencies(pipeline)
    emotion_stage = next((stage for stage in stages if stage.get("id") == "emotions"), None)
    if emotion_stage and emotion_stage.get("setupRequired") and emotion_model_status().get("ready"):
        repaired_setup.add("emotions")
        emotion_stage.update({"status": "pending", "detail": PIPELINE_STAGE_DEFINITIONS["emotions"][1]})
        for key in ("setupRequired", "startedAt", "completedAt"):
            emotion_stage.pop(key, None)
        for chapter in pipeline.get("chapters", []):
            if chapter.get("emotionStatus") in {None, "blocked", "failed"} and not chapter.get("emotion"):
                chapter["emotionStatus"] = "pending"
                chapter.pop("emotionError", None)
    tag_stage = next((stage for stage in stages if stage.get("id") == "tags"), None)
    if tag_stage and tag_stage.get("setupRequired"):
        ollama = ollama_status()
        models = ollama.get("models", []) if ollama.get("running") else []
        settings = load_settings()
        preferred = str(pipeline.get("tagModel") or settings.get("tagsModel") or pipeline.get("readerModel") or settings.get("readerModel", ""))
        if (preferred and preferred in models) or choose_primary_model(models):
            repaired_setup.add("tags")
            tag_stage.update({"status": "pending", "detail": PIPELINE_STAGE_DEFINITIONS["tags"][1]})
            for key in ("setupRequired", "startedAt", "completedAt"):
                tag_stage.pop(key, None)
    # Tag prompt v2 accepts a valid signal in the wrong family and retains
    # unsupported labels as candidates. Failures written by the stricter v1
    # validator are safe to retry once under the current contract.
    for chapter in pipeline.get("chapters", []):
        if chapter.get("tagStatus") != "failed" or chapter.get("tag") or chapter.get("tagFailurePromptVersion") == TAG_PROMPT_VERSION:
            continue
        chapter["tagStatus"] = "pending"
        chapter["tagFailurePromptVersion"] = TAG_PROMPT_VERSION
        chapter["tagMigrationNote"] = "Queued once for retry under the current tag taxonomy validator."
        chapter.pop("tagError", None)
    blocked_stage = {
        "emotions-blocked": "emotions",
        "tags-blocked": "tags",
    }.get(str(pipeline.get("phase") or ""))
    if pipeline.get("status") == "blocked" and blocked_stage in repaired_setup:
        pipeline.update({
            "status": "ready",
            "phase": "chapter-complete",
            "message": "Local analysis models are available; queued work can resume.",
        })
        pipeline.pop("error", None)


def reconcile_orphaned_child_runs(pipeline: dict[str, object]) -> bool:
    """A child cannot remain running after its owning stage has stopped."""
    changed = False
    stages = {str(stage.get("id") or ""): stage for stage in pipeline.get("stages", [])}
    now = utc_now()
    active_stage_id = {
        "summarizing": "summaries",
        "dossiers": "dossiers",
        "emotions": "emotions",
        "tags": "tags",
        "smells": "smells",
    }.get(str(pipeline.get("phase") or ""), "") if pipeline.get("status") == "running" else ""
    # A stage is serial by contract. Multiple running children can only be
    # stale ledger state (most commonly two local servers sharing one data
    # directory). Preserve the newest marker and make every older one safely
    # retryable instead of presenting impossible simultaneous activity.
    child_fields = {
        "summaries": ("status", "error", "startedAt"),
        "emotions": ("emotionStatus", "emotionError", "emotionStartedAt"),
        "tags": ("tagStatus", "tagError", "tagStartedAt"),
        "smells": ("smellStatus", "smellError", "smellStartedAt"),
    }
    for stage_id, (status_field, error_field, started_field) in child_fields.items():
        if stage_id != active_stage_id:
            continue
        running = [chapter for chapter in pipeline.get("chapters", []) if chapter.get(status_field) == "running"]
        if len(running) <= 1:
            continue
        newest = max(running, key=lambda chapter: str(chapter.get(started_field) or ""))
        for chapter in running:
            if chapter is newest:
                continue
            chapter.update({
                status_field: "pending",
                error_field: "A competing local worker stopped before completion. This chapter is ready to retry.",
                "interruptedAt": now,
            })
            changed = True
    if active_stage_id == "dossiers":
        running_chunks = [chunk for chunk in pipeline.get("chunks", []) if chunk.get("dossierStatus") == "running"]
        if len(running_chunks) > 1:
            newest = max(running_chunks, key=lambda chunk: str(chunk.get("dossierStartedAt") or ""))
            for chunk in running_chunks:
                if chunk is newest:
                    continue
                chunk.update({
                    "dossierStatus": "pending",
                    "dossierError": "A competing local worker stopped before completion. This chunk is ready to retry.",
                    "interruptedAt": now,
                })
                changed = True
    for stage_id in ("summaries", "dossiers", "emotions", "tags", "smells"):
        stage = stages.get(stage_id, {})
        if stage.get("status") != "running" or stage_id == active_stage_id:
            continue
        stage.update({
            "status": "warning",
            "detail": f"The previous {stage_id} process ended before it recorded completion. The unfinished item is ready to retry.",
        })
        changed = True
    for stage_id, status_field, error_field in (
        ("summaries", "status", "error"),
        ("emotions", "emotionStatus", "emotionError"),
        ("tags", "tagStatus", "tagError"),
        ("smells", "smellStatus", "smellError"),
    ):
        stage = stages.get(stage_id, {})
        if stage.get("status") == "running":
            continue
        diagnostic = str(stage.get("detail") or f"The previous {stage_id} run stopped before this chapter completed.")
        for chapter in pipeline.get("chapters", []):
            if chapter.get(status_field) != "running":
                continue
            chapter.update({status_field: "pending", error_field: diagnostic, "interruptedAt": now})
            changed = True
    dossier_stage = stages.get("dossiers", {})
    if dossier_stage.get("status") != "running":
        diagnostic = "The previous dossier run stopped before this chunk completed. This chunk is ready to retry."
        for chunk in pipeline.get("chunks", []):
            if chunk.get("dossierStatus") == "running":
                chunk.update({"dossierStatus": "pending", "dossierError": diagnostic, "interruptedAt": now})
                changed = True
    return changed


def invalidate_pipeline_stage(
    pipeline: dict[str, object], stage_id: str, *, include_self: bool = False,
    status: str = "blocked", detail: str = "Waiting for an upstream artifact.",
) -> set[str]:
    """Invalidate exactly one stage branch according to the dependency graph."""
    invalidated = pipeline_stage_dependents(stage_id)
    if include_self:
        invalidated.add(stage_id)
    for stage in pipeline.get("stages", []):
        if stage.get("id") not in invalidated:
            continue
        stage.update({"status": status, "detail": detail})
        for key in ("startedAt", "completedAt"):
            stage.pop(key, None)
    if "question-tracker" in invalidated:
        previous = pipeline.get("questionTracker") if isinstance(pipeline.get("questionTracker"), dict) else {}
        pipeline["questionTracker"] = {**previous, "status": "blocked", "dependsOn": list(PIPELINE_STAGE_DEPENDENCIES["question-tracker"]), "detail": detail}
    return invalidated


def load_library() -> list[dict[str, object]]:
    try:
        payload = json.loads(LIBRARY_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return [enrich_book(item) for item in payload if isinstance(item, dict)] if isinstance(payload, list) else []


def manuscript_metadata(manuscript_id: str) -> dict[str, object]:
    if not manuscript_id:
        return {}
    manuscript_root = BOOKS_ROOT / manuscript_id
    source_path = manuscript_root / "source.json"
    metadata: dict[str, object] = {}
    try:
        source = json.loads(source_path.read_text(encoding="utf-8"))
        if isinstance(source, dict):
            metadata["sourceFilename"] = str(source.get("filename") or "manuscript.pdf")
            metadata["ingestedAt"] = str(source.get("ingestedAt") or "")
            metadata["sourceStoredAs"] = str(source.get("storedAs") or "")
            metadata["sourceMediaType"] = str(source.get("mediaType") or "")
            metadata["sourceSizeBytes"] = int(source.get("sizeBytes") or 0)
    except (OSError, json.JSONDecodeError):
        pass
    manuscript_path = manuscript_root / "manuscript.pdf"
    if not metadata.get("ingestedAt") and manuscript_path.exists():
        metadata["ingestedAt"] = datetime.fromtimestamp(manuscript_path.stat().st_mtime, timezone.utc).isoformat(timespec="seconds")
    stored_name = Path(str(metadata.get("sourceStoredAs") or "")).name
    stored_path = manuscript_root / stored_name if stored_name else None
    original_preserved = bool(stored_path and stored_path.is_file())
    if not original_preserved and manuscript_path.is_file():
        stored_path = manuscript_path
        stored_name = manuscript_path.name
    available = bool(stored_path and stored_path.is_file())
    source_filename = Path(str(metadata.get("sourceFilename") or "manuscript.pdf")).name
    legacy_converted = available and not original_preserved and Path(source_filename).suffix.casefold() != ".pdf"
    if legacy_converted:
        source_filename = f"{Path(source_filename).stem or 'manuscript'}-converted.pdf"
    source_suffix = Path(source_filename).suffix.casefold()
    metadata.update({
        "sourceFilename": source_filename,
        "sourceStoredAs": stored_name,
        "sourceFormat": (source_suffix.removeprefix(".") or "file").upper(),
        "sourceMediaType": str(metadata.get("sourceMediaType") or mimetypes.guess_type(source_filename)[0] or "application/octet-stream"),
        "sourceSizeBytes": int(metadata.get("sourceSizeBytes") or (stored_path.stat().st_size if available else 0)),
        "sourceAvailable": available,
        "sourceOriginalPreserved": original_preserved or (available and source_suffix == ".pdf"),
    })
    return metadata


def source_document_path(manuscript_id: str) -> tuple[Path | None, dict[str, object]]:
    metadata = manuscript_metadata(manuscript_id)
    stored_name = Path(str(metadata.get("sourceStoredAs") or "")).name
    source_path = BOOKS_ROOT / manuscript_id / stored_name if manuscript_id and stored_name else None
    return (source_path if source_path and source_path.is_file() else None), metadata


def normalize_book_priority(value: object) -> str:
    priority = str(value or "normal").strip().lower()
    return priority if priority in BOOK_PRIORITY_ORDER else "normal"


def pipeline_is_enabled() -> bool:
    return load_settings().get("pipelineEnabled", "false").lower() == "true"


def set_pipeline_enabled(enabled: bool) -> None:
    settings = load_settings()
    settings["pipelineEnabled"] = "true" if enabled else "false"
    save_settings(settings)


def stage_rollup_input_signature(pipeline: dict[str, object], rollup_id: str) -> str:
    """Hash the exact complete child set consumed by one stage-local rollup."""
    definition = STAGE_ROLLUP_DEFINITIONS.get(rollup_id)
    if not definition:
        return ""
    collection = pipeline.get(str(definition["collection"]), [])
    if not isinstance(collection, list):
        return ""
    children = [item for item in collection if isinstance(item, dict)]
    if definition.get("excludeFrontMatter"):
        children = [item for item in children if re.sub(r"^#{1,6}\s+", "", str(item.get("title") or "").strip()).casefold() != "front matter"]
    status_field = str(definition["statusField"])
    if not children or any(str(item.get(status_field) or "pending") != "complete" for item in children):
        return ""
    payload_fields = tuple(definition.get("payloadFields", ()))
    payload = [{field: item.get(field) for field in payload_fields} for item in children]
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def stage_rollup_action(pipeline: dict[str, object]) -> str:
    """Return the first eligible stale/missing rollup without retrying failures."""
    for rollup_id, definition in STAGE_ROLLUP_DEFINITIONS.items():
        dependency_stage = str(definition.get("dependencyStage") or "")
        if dependency_stage and not pipeline_stage_ready(pipeline, dependency_stage):
            continue
        signature = stage_rollup_input_signature(pipeline, rollup_id)
        if not signature:
            continue
        result = pipeline.get(str(definition["resultKey"]))
        result = result if isinstance(result, dict) else {}
        if result.get("inputSignature") == signature and result.get("status") in {"complete", "running", "failed"}:
            continue
        return str(definition["action"])
    return ""


def next_pipeline_action(book: dict[str, object], pipeline: dict[str, object]) -> str:
    """Return the next safe automatic pass, without endlessly retrying failures."""
    if normalize_book_priority(book.get("priority")) == "shelved" or not book.get("manuscriptId"):
        return ""
    stages = {str(stage.get("id") or ""): str(stage.get("status") or "pending") for stage in pipeline.get("stages", [])}
    chapters = pipeline.get("chapters", [])
    manuscript_chapters = [chapter for chapter in chapters if strip_markdown_heading(chapter.get("title")).casefold() != "front matter"]
    if not chapters or stages.get("extraction") in {"pending", "blocked", "failed"} or stages.get("chapter-archive") in {"pending", "blocked", "failed"}:
        return "prepare"
    if any(chapter.get("status") in {None, "pending", "ready", "paused", "running"} for chapter in chapters):
        return "summarize"
    chunks = pipeline.get("chunks", [])
    if chunks and any(chunk.get("dossierStatus") in {None, "pending", "ready", "paused", "running"} for chunk in chunks):
        return "dossiers"
    # Whole-book rollups are the completion of their source stages, not
    # optional enrichment. Run them as soon as their own inputs are current,
    # before slower independent passes such as Tags and Smells.
    if rollup_action := stage_rollup_action(pipeline):
        return rollup_action
    emotion_stage = next((stage for stage in pipeline.get("stages", []) if stage.get("id") == "emotions"), {})
    if emotion_stage.get("status") != "blocked" and any(chapter.get("emotionStatus") in {None, "pending", "ready", "paused", "running"} for chapter in manuscript_chapters):
        return "emotions"
    if any(chapter.get("tagStatus") in {None, "pending", "ready", "paused", "running"} for chapter in manuscript_chapters):
        return "tags"
    smell_stage = next((stage for stage in pipeline.get("stages", []) if stage.get("id") == "smells"), None)
    if smell_stage and any(chapter.get("smellStatus") in {None, "pending", "ready", "paused", "running"} for chapter in manuscript_chapters):
        return "smells"
    return ""


def automatic_queue_books(books: list[dict[str, object]] | None = None) -> list[tuple[str, str]]:
    """Select unfinished books by priority, then oldest change, for fair background work."""
    candidates: list[tuple[int, str, str, str]] = []
    for book in books if books is not None else load_library():
        priority = normalize_book_priority(book.get("priority"))
        if priority == "shelved":
            continue
        action = next_pipeline_action(book, load_pipeline(book))
        if not action:
            continue
        candidates.append((BOOK_PRIORITY_ORDER[priority], str(book.get("updatedAt") or book.get("createdAt") or ""), str(book.get("id") or ""), action))
    candidates.sort(key=lambda item: (item[0], item[1], item[2]))
    return [(book_id, action) for _, _, book_id, action in candidates if book_id]


def pipeline_activity(book: dict[str, object], pipeline: dict[str, object]) -> dict[str, object]:
    """Describe one book's current queue work for every progress surface."""
    title = str(book.get("title") or "this book")
    book_id = str(book.get("id") or "")
    phase = str(pipeline.get("phase") or "")
    status = str(pipeline.get("status") or "ready")
    stages = {str(stage.get("id") or ""): stage for stage in pipeline.get("stages", [])}
    active_chapter = next((chapter for chapter in pipeline.get("chapters", []) if chapter.get("status") == "running"), None)
    active_emotion = next((chapter for chapter in pipeline.get("chapters", []) if chapter.get("emotionStatus") == "running"), None)
    active_tag = next((chapter for chapter in pipeline.get("chapters", []) if chapter.get("tagStatus") == "running"), None)
    active_smell = next((chapter for chapter in pipeline.get("chapters", []) if chapter.get("smellStatus") == "running"), None)
    active_chunk = next((chunk for chunk in pipeline.get("chunks", []) if chunk.get("dossierStatus") == "running"), None)
    whole_book = pipeline.get("wholeBookSummary") if isinstance(pipeline.get("wholeBookSummary"), dict) else {}

    if pipeline.get("stopRequested"):
        return {"state": "stopping", "phase": phase, "bookId": book_id, "book": title, "task": "Stopping safely", "text": "Bookinator is stopping after the current local response"}
    if phase == "whole-summary" and whole_book.get("status") == "running" and pipeline_stage_ready(pipeline, "whole-book-summary"):
        model = str(whole_book.get("model") or stages.get("summaries", {}).get("model") or "the local model")
        return {"state": "running", "phase": "whole-summary", "bookId": book_id, "book": title, "task": "Whole-book summary", "model": model, "item": "Synthesis", "text": f"Bookinator · {model} is merging the whole-book summary for {title}"}
    whole_dossier = pipeline.get("wholeBookDossier") if isinstance(pipeline.get("wholeBookDossier"), dict) else {}
    if phase == "whole-dossier" and whole_dossier.get("status") == "running" and pipeline_stage_ready(pipeline, "whole-book-dossier"):
        model = str(whole_dossier.get("model") or stages.get("dossiers", {}).get("model") or "the local model")
        return {"state": "running", "phase": "whole-dossier", "bookId": book_id, "book": title, "task": "Whole-book dossier", "model": model, "item": "Reconciliation", "text": f"Bookinator · {model} is reconciling the whole-book dossier for {title}"}
    question_tracker = pipeline.get("questionTracker") if isinstance(pipeline.get("questionTracker"), dict) else {}
    if phase == "questions" and question_tracker.get("status") == "running" and pipeline_stage_ready(pipeline, "question-tracker"):
        model = str(question_tracker.get("model") or stages.get("summaries", {}).get("model") or "the local model")
        return {"state": "running", "phase": "questions", "bookId": book_id, "book": title, "task": "Questions & payoffs", "model": model, "item": "Whole-book reconciliation", "text": f"Bookinator · {model} is matching questions to payoffs in {title}"}
    if status == "running":
        if phase == "summarizing":
            model = str(stages.get("summaries", {}).get("model") or "the local model")
            item = strip_markdown_heading((active_chapter or {}).get("title")) or "the next chapter"
            task = "Chapter summary"
            text = f"Bookinator · {model} is reading {title} · {item}"
        elif phase == "dossiers":
            model = str(stages.get("dossiers", {}).get("model") or "the local model")
            chapter = str((active_chunk or {}).get("chapterLabel") or "the next chapter")
            chunk = int((active_chunk or {}).get("chunkInChapter") or 1)
            item = f"{chapter}, chunk {chunk}"
            task = "Chapter dossier"
            text = f"Bookinator · {model} is building {title} · {item}"
        elif phase == "emotions":
            model = str(stages.get("emotions", {}).get("model") or EMOTION_MODEL_ID)
            item = strip_markdown_heading((active_emotion or {}).get("title")) or "the next chapter"
            task = "Emotion scoring"
            text = f"Bookinator · {model} is scoring emotions in {title} · {item}"
        elif phase == "tags":
            model = str(stages.get("tags", {}).get("model") or "the local model")
            item = strip_markdown_heading((active_tag or {}).get("title")) or "the next chapter"
            task = "Chapter tags"
            text = f"Bookinator · {model} is tagging {title} · {item}"
        elif phase == "smells":
            model = str(stages.get("smells", {}).get("model") or "the local editor")
            item = strip_markdown_heading((active_smell or {}).get("title")) or "the next chapter"
            task = "Prose smells"
            text = f"Bookinator · {model} is reviewing smells in {title} · {item}"
        elif phase == "preparing":
            model = ""
            item = ""
            task = "Manuscript map"
            text = f"Bookinator is mapping {title}"
        else:
            model = ""
            item = ""
            task = "Pipeline work"
            text = f"Bookinator is working on {title} · {str(pipeline.get('message') or 'saving the next local step')}"
        return {"state": "running", "phase": phase, "bookId": book_id, "book": title, "task": task, "model": model, "item": item, "text": text}
    if status == "queued":
        action = str(pipeline.get("queuedAction") or next_pipeline_action(book, pipeline) or "analysis")
        labels = {"prepare": "map", "summarize": "read", "restart": "reread", "whole-summary": "merge", "whole-dossier": "reconcile the dossier for", "questions": "match questions and payoffs in", "dossiers": "build dossiers for", "dossier-restart": "rebuild dossiers for", "emotions": "score emotions in", "emotion-restart": "rescore emotions in", "tags": "tag", "tag-restart": "retag", "smells": "review prose smells in", "smell-restart": "re-review prose smells in"}
        tasks = {"prepare": "Manuscript map", "summarize": "Chapter summary", "restart": "Chapter summaries", "whole-summary": "Whole-book summary", "whole-dossier": "Whole-book dossier", "questions": "Questions & payoffs", "dossiers": "Chapter dossier", "dossier-restart": "Chapter dossiers", "emotions": "Emotion scoring", "emotion-restart": "Emotion scoring", "tags": "Chapter tags", "tag-restart": "Chapter tags", "smells": "Smells", "smell-restart": "Smells"}
        return {"state": "queued", "phase": action, "bookId": book_id, "book": title, "task": tasks.get(action, "Analysis"), "text": f"Bookinator is waiting to {labels.get(action, 'analyze')} {title}"}
    return {"state": "idle", "phase": phase, "bookId": book_id, "book": title, "task": "Ready", "text": f"Bookinator is ready for the next step in {title}"}


def reset_inactive_whole_book_runs(pipeline: dict[str, object], active_phase: str) -> None:
    """Only one whole-book model response can own the single local queue."""
    interrupted_at = str(pipeline.get("updatedAt") or utc_now())
    for phase, key, detail in (
        ("whole-summary", "wholeBookSummary", "The earlier synthesis is not active. Ready to restart."),
        ("whole-dossier", "wholeBookDossier", "The earlier dossier reconciliation is not active. Ready to restart."),
        ("questions", "questionTracker", "The earlier reconciliation is not active. Ready to restart."),
    ):
        rollup = pipeline.get(key)
        if phase == active_phase or not isinstance(rollup, dict) or rollup.get("status") != "running":
            continue
        rollup.update({"status": "ready", "interruptedAt": rollup.get("interruptedAt") or interrupted_at, "detail": detail})
        rollup.pop("completedAt", None)
        rollup.pop("durationSeconds", None)


GLOBAL_ETA_FALLBACK_SECONDS: dict[str, float] = {
    "structure": 12,
    "summaries": 150,
    "dossiers": 150,
    "emotions": 3,
    "tags": 150,
    "smells": 540,
    "summary-rollup": 180,
}


def global_pipeline_estimate(pipeline_records: list[tuple[dict[str, object], dict[str, object]]]) -> dict[str, object]:
    """Estimate unlike work with unlike timings, falling back conservatively when history is sparse."""
    samples: dict[str, list[float]] = {kind: [] for kind in GLOBAL_ETA_FALLBACK_SECONDS}
    remaining: dict[str, int] = {kind: 0 for kind in GLOBAL_ETA_FALLBACK_SECONDS}
    for book, pipeline in pipeline_records:
        if normalize_book_priority(book.get("priority")) == "shelved" or not book.get("manuscriptId"):
            continue
        chapters = [
            chapter for chapter in pipeline.get("chapters", []) if isinstance(chapter, dict)
            and strip_markdown_heading(chapter.get("title")).casefold() != "front matter"
        ]
        stages = {str(stage.get("id") or ""): stage for stage in pipeline.get("stages", []) if isinstance(stage, dict)}
        if chapters and stages.get("chapter-archive", {}).get("status") != "complete":
            remaining["structure"] += len(chapters)
        mappings = (
            ("summaries", "status", "durationSeconds"),
            ("emotions", "emotionStatus", "emotionDurationSeconds"),
            ("tags", "tagStatus", "tagDurationSeconds"),
            ("smells", "smellStatus", "smellDurationSeconds"),
        )
        for kind, status_key, duration_key in mappings:
            if kind == "smells" and "smells" not in stages:
                continue
            remaining[kind] += sum(1 for chapter in chapters if chapter.get(status_key) in {None, "pending", "ready", "paused", "running"})
            samples[kind].extend(float(chapter[duration_key]) for chapter in chapters if chapter.get(duration_key) and chapter.get(status_key) == "complete")
        chapter_sequences = {str(chapter.get("sequence") or chapter.get("number") or "") for chapter in chapters}
        chunks = [chunk for chunk in pipeline.get("chunks", []) if isinstance(chunk, dict) and str(chunk.get("chapterSequence") or "") in chapter_sequences]
        remaining["dossiers"] += sum(1 for chunk in chunks if chunk.get("dossierStatus") in {None, "pending", "ready", "paused", "running"})
        samples["dossiers"].extend(float(chunk["dossierDurationSeconds"]) for chunk in chunks if chunk.get("dossierDurationSeconds") and chunk.get("dossierStatus") == "complete")
        rollup = pipeline.get("wholeBookSummary") if isinstance(pipeline.get("wholeBookSummary"), dict) else {}
        if rollup.get("status") in {"ready", "running"}:
            remaining["summary-rollup"] += 1
        if rollup.get("status") == "complete" and rollup.get("durationSeconds"):
            samples["summary-rollup"].append(float(rollup["durationSeconds"]))

    estimates: dict[str, dict[str, object]] = {}
    eta_seconds = 0.0
    fallback_items = 0
    measured_items = 0
    for kind, fallback in GLOBAL_ETA_FALLBACK_SECONDS.items():
        recent = samples[kind][-20:]
        average = sum(recent) / len(recent) if recent else fallback
        count = remaining[kind]
        eta_seconds += average * count
        if count:
            if recent:
                measured_items += count
            else:
                fallback_items += count
        estimates[kind] = {"remaining": count, "averageSeconds": round(average), "sampleSize": len(recent), "fallback": not bool(recent)}
    total_items = measured_items + fallback_items
    confidence = "measured" if total_items and not fallback_items else "learning" if measured_items else "early"
    return {
        "etaSeconds": round(eta_seconds) if total_items else 0,
        "etaConfidence": confidence,
        "etaLabel": "Measured from recent work" if confidence == "measured" else "Learning from recent work" if confidence == "learning" else "Early estimate using cautious defaults",
        "estimates": estimates,
    }


def global_pipeline_diagnostics(pipeline_records: list[tuple[dict[str, object], dict[str, object]]]) -> list[dict[str, object]]:
    """Collect current model and pipeline problems without requiring the affected book to be open."""
    process_labels = {
        "summaries": "Chapter summary",
        "dossiers": "Chapter dossier",
        "emotions": "Chapter emotions",
        "tags": "Chapter tags",
        "smells": "Smells",
    }
    diagnostics: list[dict[str, object]] = []
    for book, pipeline in pipeline_records:
        book_id = str(book.get("id") or "")
        title = str(book.get("title") or "Untitled")
        if pipeline.get("error"):
            diagnostics.append({"bookId": book_id, "book": title, "stage": "pipeline", "resultKind": "stage", "resultId": "pipeline", "status": "failed", "item": "Pipeline", "error": str(pipeline["error"]), "completedAt": pipeline.get("updatedAt")})
        for stage in pipeline.get("stages", []):
            if not isinstance(stage, dict):
                continue
            stage_failed = stage.get("status") == "failed"
            stage_needs_setup = stage.get("status") == "blocked" and bool(stage.get("setupRequired") or stage.get("error"))
            if not stage_failed and not stage_needs_setup:
                continue
            stage_id = str(stage.get("id") or "pipeline")
            diagnostics.append({"bookId": book_id, "book": title, "stage": stage_id, "resultKind": "stage", "resultId": stage_id, "status": stage.get("status"), "item": str(stage.get("label") or stage.get("id") or "Pipeline step"), "error": str(stage.get("error") or stage.get("detail") or "This step needs attention."), "model": stage.get("model"), "completedAt": stage.get("completedAt") or pipeline.get("updatedAt")})
        for chapter in pipeline.get("chapters", []):
            if not isinstance(chapter, dict):
                continue
            chapter_label = str(chapter.get("title") or chapter.get("chapterTitle") or "Chapter")
            manuscript_chapter = strip_markdown_heading(chapter.get("title")).casefold() != "front matter"
            for stage, status_key, error_key, model_key, completed_key in (
                ("summaries", "status", "error", "model", "completedAt"),
                ("emotions", "emotionStatus", "emotionError", "emotionModel", "emotionCompletedAt"),
                ("tags", "tagStatus", "tagError", "tagModel", "tagCompletedAt"),
                ("smells", "smellStatus", "smellError", "smellModel", "smellCompletedAt"),
            ):
                if stage in {"emotions", "tags", "smells"} and not manuscript_chapter:
                    continue
                if chapter.get(status_key) != "failed":
                    continue
                item = f"{process_labels[stage]} · {chapter_label}"
                diagnostics.append({"bookId": book_id, "book": title, "stage": stage, "resultKind": {"summaries": "summary", "emotions": "emotion", "tags": "tag", "smells": "smell"}[stage], "resultId": chapter.get("sequence") or chapter.get("number"), "status": "failed", "item": item, "error": str(chapter.get(error_key) or "The local model did not produce a usable result."), "model": chapter.get(model_key), "completedAt": chapter.get(completed_key)})
        for chunk in pipeline.get("chunks", []):
            if not isinstance(chunk, dict) or chunk.get("dossierStatus") != "failed":
                continue
            chapter_label = str(chunk.get("chapterLabel") or chunk.get("chapterTitle") or chunk.get("id") or "Source chunk")
            chunk_number = chunk.get("chunkInChapter")
            item = f"{process_labels['dossiers']} · {chapter_label}"
            if chunk_number not in (None, ""):
                item += f" · Chunk {chunk_number}"
            diagnostics.append({"bookId": book_id, "book": title, "stage": "dossiers", "resultKind": "dossier", "resultId": chunk.get("sequence") or chunk.get("id"), "status": "failed", "item": item, "error": str(chunk.get("dossierError") or "The local model did not produce a usable dossier."), "model": chunk.get("dossierModel"), "completedAt": chunk.get("dossierCompletedAt")})
        rollup = pipeline.get("wholeBookSummary") if isinstance(pipeline.get("wholeBookSummary"), dict) else {}
        if rollup.get("status") == "failed":
            diagnostics.append({"bookId": book_id, "book": title, "stage": "summaries", "status": "failed", "item": "Whole-book summary", "error": str(rollup.get("error") or "The whole-book summary failed."), "model": rollup.get("model"), "completedAt": rollup.get("completedAt")})
    diagnostics.sort(key=lambda item: str(item.get("completedAt") or ""), reverse=True)
    return diagnostics


def pipeline_for_client(book_id: str, pipeline: dict[str, object]) -> dict[str, object]:
    """Present queued overrides and deferred retries without mutating the worker ledger."""
    with QUEUE_LOCK:
        retry_waiting = QUEUE_ACTIONS.get(book_id) == "deferred-retry-failed"
        requested_action = QUEUE_ACTIONS.get(book_id, "")
        deferred_refreshes = list(DEFERRED_ANALYSIS_REFRESHES.get(book_id, []))
    if not requested_action:
        requested_action = load_queue_actions().get(book_id, "")
    if requested_action == "deferred-refresh" and not deferred_refreshes:
        deferred_refreshes = load_deferred_analysis_refreshes().get(book_id, [])
    stale_rollup = any(
        isinstance(pipeline.get(key), dict)
        and pipeline.get(key, {}).get("status") == "running"
        and str(pipeline.get("phase") or "") != phase
        for phase, key in (("whole-summary", "wholeBookSummary"), ("whole-dossier", "wholeBookDossier"), ("questions", "questionTracker"))
    )
    if not retry_waiting and not requested_action and not stale_rollup:
        return pipeline

    visible = copy.deepcopy(pipeline)
    reset_inactive_whole_book_runs(visible, str(visible.get("phase") or ""))
    if requested_action in EXPLICIT_QUEUE_ACTIONS:
        visible["queuedAction"] = requested_action
        visible["explicitActionQueued"] = True
    if requested_action == "deferred-refresh" and deferred_refreshes:
        affected_stages: set[str] = set()
        for kind, sequence in deferred_refreshes:
            if kind == "whole-summary":
                if isinstance(visible.get("wholeBookSummary"), dict):
                    visible["wholeBookSummary"]["status"] = "pending"
                affected_stages.add("whole-book-summary")
                continue
            if kind == "dossier":
                for chunk in visible.get("chunks", []):
                    if int(chunk.get("sequence") or 0) == sequence:
                        chunk["dossierStatus"] = "pending"
                        chunk["refreshQueued"] = True
                affected_stages.add("dossiers")
                continue
            chapter = next((item for item in visible.get("chapters", []) if int(item.get("sequence") or item.get("number") or 0) == sequence), None)
            if not chapter:
                continue
            if kind == "summary":
                chapter["status"] = "pending"
                affected_stages.add("summaries")
            else:
                chapter[f"{kind}Status"] = "pending"
                affected_stages.add({"emotion": "emotions", "tag": "tags", "smell": "smells"}[kind])
            chapter["refreshQueued"] = True
        for stage in visible.get("stages", []):
            if stage.get("id") in affected_stages and stage.get("status") in {"failed", "warning", "complete"}:
                stage["status"] = "pending"
                stage["detail"] = "A saved result is waiting to rerun after the current model response."
        visible["refreshQueued"] = True
        visible["message"] = "The selected result is waiting behind the current model response."
    if not retry_waiting:
        return visible

    affected_stages: set[str] = set()
    for chapter in visible.get("chapters", []):
        if chapter.get("status") == "failed":
            chapter["status"] = "pending"
            affected_stages.add("summaries")
        for kind, stage_id in (("emotion", "emotions"), ("tag", "tags"), ("smell", "smells")):
            if chapter.get(f"{kind}Status") == "failed":
                chapter[f"{kind}Status"] = "pending"
                affected_stages.add(stage_id)
    for chunk in visible.get("chunks", []):
        if chunk.get("dossierStatus") == "failed":
            chunk["dossierStatus"] = "pending"
            affected_stages.add("dossiers")
    whole_summary = visible.get("wholeBookSummary")
    if isinstance(whole_summary, dict) and whole_summary.get("status") == "failed":
        whole_summary["status"] = "pending"
        affected_stages.add("whole-book-summary")
    for stage in visible.get("stages", []):
        if stage.get("id") in affected_stages and stage.get("status") in {"failed", "warning"}:
            stage["status"] = "pending"
            stage["detail"] = "Waiting for the current model response, then retrying failed work in normal pipeline order."
    visible["retryFailedQueued"] = True
    visible["message"] = "Failed work is waiting behind the current model response. Normal pipeline order resumes next."
    return visible


def compact_pipeline_payload(pipeline: dict[str, object]) -> dict[str, object]:
    """Omit source prose that chapter endpoints already load on demand."""
    visible = copy.deepcopy(pipeline)
    for chapter in visible.get("chapters", []):
        chapter.pop("text", None)
        chapter.pop("markdown", None)
    return visible


def global_pipeline_state(books: list[dict[str, object]] | None = None) -> dict[str, object]:
    library = books if books is not None else load_library()
    actionable = [book for book in library if book.get("pipeline", {}).get("workRemaining") and normalize_book_priority(book.get("priority")) != "shelved"]
    pipeline_records = [
        (book, add_pipeline_progress(pipeline_for_client(str(book.get("id") or ""), load_pipeline(book))))
        for book in library
    ]
    running = bool(QUEUE_THREAD and QUEUE_THREAD.is_alive()) or any(
        pipeline_worker_is_alive(str(book.get("id") or ""), pipeline) for book, pipeline in pipeline_records
    )
    completed = sum(int(book.get("pipeline", {}).get("progress", {}).get("completed") or 0) for book in library if normalize_book_priority(book.get("priority")) != "shelved")
    total = sum(int(book.get("pipeline", {}).get("progress", {}).get("total") or 0) for book in library if normalize_book_priority(book.get("priority")) != "shelved")
    activities = [pipeline_activity(book, pipeline) for book, pipeline in pipeline_records]
    with QUEUE_LOCK:
        current_task = dict(QUEUE_CURRENT_TASK)
    activity = next((item for item in activities if item["state"] == "stopping"), None)
    activity = activity or next((item for item in activities if item["state"] == "running" and item.get("bookId") == current_task.get("bookId")), None)
    activity = activity or next((item for item in activities if item["state"] == "running"), None)
    if not activity and running and current_task:
        activity = {"state": "running", "phase": current_task.get("action", "queue"), **current_task, "text": f"Bookinator is starting {current_task.get('task', 'the next task').lower()} in {current_task.get('book', 'the next book')}"}
    activity = activity or next((item for item in activities if item["state"] == "queued"), None)
    if not activity and running:
        activity = {"state": "running", "phase": "queue", "text": "Bookinator is choosing the next chapter-step"}
    if not activity:
        enabled = pipeline_is_enabled()
        activity = {
            "state": "queued" if actionable and enabled else "idle",
            "phase": "queue",
            "text": "Bookinator is checking the global queue" if actionable and enabled else "The global queue is off" if actionable else "Bookinator is ready; no analysis is waiting",
        }
    estimate = global_pipeline_estimate(pipeline_records)
    diagnostics = global_pipeline_diagnostics(pipeline_records)
    return {
        "enabled": pipeline_is_enabled(),
        "running": running,
        "waitingBooks": len(actionable),
        "completed": completed,
        "total": total,
        "percent": round(completed / total * 100) if total else 0,
        "activity": activity,
        **estimate,
        "diagnosticCount": len(diagnostics),
        "diagnostics": diagnostics,
    }


def enrich_book(book: dict[str, object]) -> dict[str, object]:
    enriched = dict(book)
    metadata = manuscript_metadata(str(book.get("manuscriptId") or ""))
    if metadata.get("sourceFilename"):
        enriched["sourceFilename"] = metadata["sourceFilename"]
    enriched.setdefault("ingestedAt", metadata.get("ingestedAt", ""))
    for key in ("sourceSizeBytes", "sourceFormat", "sourceMediaType", "sourceAvailable", "sourceOriginalPreserved"):
        enriched[key] = metadata.get(key)
    manuscript_path = BOOKS_ROOT / str(book.get("manuscriptId") or "") / "manuscript.pdf"
    enriched["hasPdf"] = manuscript_path.is_file()
    pipeline = add_pipeline_progress(pipeline_for_client(str(book.get("id") or ""), load_pipeline(book)))
    chapters = pipeline.get("chapters", [])
    completed = sum(1 for chapter in chapters if chapter.get("status") == "complete")
    stages = {stage.get("id"): stage.get("status", "pending") for stage in pipeline.get("stages", [])}
    next_action = next_pipeline_action(book, pipeline)
    enriched["pipeline"] = {
        "queued": str(book.get("id")) in load_queue(),
        "status": pipeline.get("status", "ready"),
        "structure": stages.get("structure", "pending"),
        "summariesCompleted": completed,
        "summariesTotal": len(chapters),
        "updatedAt": pipeline.get("updatedAt", ""),
        "nextAction": next_action,
        "workRemaining": bool(next_action),
        "progress": pipeline.get("pipelineProgress", {}),
    }
    return enriched


def load_queue() -> list[str]:
    try:
        payload = json.loads(QUEUE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return [str(item) for item in payload if isinstance(item, str)] if isinstance(payload, list) else []


def save_queue(book_ids: list[str]) -> None:
    QUEUE_PATH.parent.mkdir(parents=True, exist_ok=True)
    QUEUE_PATH.write_text(json.dumps(list(dict.fromkeys(book_ids)), indent=2) + "\n", encoding="utf-8")


def load_queue_actions() -> dict[str, str]:
    """Load one-shot user requests that must survive a server restart."""
    try:
        payload = json.loads(QUEUE_ACTIONS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    return {
        str(book_id): str(action)
        for book_id, action in payload.items()
        if isinstance(book_id, str) and action in EXPLICIT_QUEUE_ACTIONS
    }


def save_queue_actions(actions: dict[str, str]) -> None:
    QUEUE_ACTIONS_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = QUEUE_ACTIONS_PATH.with_suffix(".tmp")
    temporary.write_text(json.dumps(actions, indent=2) + "\n", encoding="utf-8")
    temporary.replace(QUEUE_ACTIONS_PATH)


def load_deferred_analysis_refreshes() -> dict[str, list[tuple[str, int]]]:
    """Load chapter refresh requests that have not yet reached a safe handoff."""
    try:
        payload = json.loads(DEFERRED_REFRESHES_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    allowed = {"summary", "dossier", "emotion", "tag", "smell", "whole-summary"}
    return {
        str(book_id): [(str(item[0]), int(item[1])) for item in requests if isinstance(item, list) and len(item) == 2 and str(item[0]) in allowed]
        for book_id, requests in payload.items() if isinstance(book_id, str) and isinstance(requests, list)
    }


def save_deferred_analysis_refreshes(refreshes: dict[str, list[tuple[str, int]]]) -> None:
    DEFERRED_REFRESHES_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = DEFERRED_REFRESHES_PATH.with_suffix(".tmp")
    temporary.write_text(json.dumps(refreshes, indent=2) + "\n", encoding="utf-8")
    temporary.replace(DEFERRED_REFRESHES_PATH)


def persist_queue_action(book_id: str, action: str) -> None:
    actions = load_queue_actions()
    actions[book_id] = action
    save_queue_actions(actions)


def complete_queue_action(book_id: str, action: str) -> None:
    """Forget a durable request only after its requested pass returns."""
    actions = load_queue_actions()
    if actions.get(book_id) != action:
        return
    actions.pop(book_id, None)
    save_queue_actions(actions)


def remove_queue_action(book_id: str) -> None:
    actions = load_queue_actions()
    if book_id not in actions:
        return
    actions.pop(book_id, None)
    save_queue_actions(actions)


def save_book(book: dict[str, object]) -> dict[str, object]:
    book_id = str(book.get("id") or uuid.uuid4())
    if not re.fullmatch(r"[A-Za-z0-9_-]{8,80}", book_id):
        book_id = str(uuid.uuid4())
    manuscript_id = str(book.get("manuscriptId") or "")
    manuscript = manuscript_metadata(manuscript_id)
    normalized = {
        "id": book_id,
        "title": str(book.get("title") or "Untitled").strip()[:500],
        "author": str(book.get("author") or "").strip()[:500],
        "icon": book.get("icon") if isinstance(book.get("icon"), dict) else None,
        "status": str(book.get("status") or "new"),
        "progress": str(book.get("progress") or "Ready to inspect"),
        "updated": str(book.get("updated") or "Just now"),
        "manuscriptId": manuscript_id,
        "sourceFilename": str(book.get("sourceFilename") or manuscript.get("sourceFilename") or ""),
        "ingestedAt": str(book.get("ingestedAt") or manuscript.get("ingestedAt") or ""),
        "createdAt": str(book.get("createdAt") or utc_now()),
        "updatedAt": utc_now(),
        "abbreviation": str(book.get("abbreviation") or "").strip()[:3],
        "priority": normalize_book_priority(book.get("priority")),
    }
    with LIBRARY_LOCK:
        library = load_library()
        existing = next((index for index, item in enumerate(library) if item.get("id") == book_id), None)
        if existing is None:
            library.insert(0, normalized)
        else:
            library[existing] = normalized
        LIBRARY_PATH.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = LIBRARY_PATH.with_suffix(".tmp")
        temporary_path.write_text(json.dumps(library, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary_path.replace(LIBRARY_PATH)
    if normalized["priority"] == "shelved":
        save_queue([queued_id for queued_id in load_queue() if queued_id != book_id])
        with QUEUE_LOCK:
            QUEUE_ACTIONS.pop(book_id, None)
            remove_queue_action(book_id)
    return enrich_book(normalized)


def store_manuscript(pdf_bytes: bytes, filename: str, source_bytes: bytes | None = None, media_type: str = "") -> str:
    manuscript_id = str(uuid.uuid4())
    manuscript_root = BOOKS_ROOT / manuscript_id
    manuscript_root.mkdir(parents=True, exist_ok=False)
    (manuscript_root / "manuscript.pdf").write_bytes(pdf_bytes)
    safe_filename = Path(filename).name or "manuscript.pdf"
    original = source_bytes if source_bytes is not None else pdf_bytes
    suffix = Path(safe_filename).suffix.casefold()
    stored_name = "manuscript.pdf" if suffix == ".pdf" else f"source{suffix if suffix in {'.docx', '.epub', '.txt', '.md'} else '.bin'}"
    if stored_name != "manuscript.pdf":
        (manuscript_root / stored_name).write_bytes(original)
    source_record = {
        "filename": safe_filename,
        "ingestedAt": utc_now(),
        "storedAs": stored_name,
        "sizeBytes": len(original),
        "mediaType": media_type or mimetypes.guess_type(safe_filename)[0] or "application/octet-stream",
        "normalizedPdfSizeBytes": len(pdf_bytes),
    }
    (manuscript_root / "source.json").write_text(json.dumps(source_record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manuscript_id


def text_manuscript_to_pdf(source: bytes) -> bytes:
    text = source.decode("utf-8-sig", errors="replace").replace("\r\n", "\n")
    if not text.strip():
        raise ValueError("The text manuscript is empty.")
    import pymupdf  # type: ignore[import-not-found]
    document = pymupdf.open()
    chunks = [text[index:index + 3200] for index in range(0, len(text), 3200)]
    for chunk in chunks:
        page = document.new_page(width=612, height=792)
        page.insert_textbox(pymupdf.Rect(54, 54, 558, 738), chunk, fontsize=10.5, fontname="courier", lineheight=1.25)
    rendered = document.tobytes(garbage=4, deflate=True)
    document.close()
    return rendered


def archive_manuscript_text(source: bytes, suffix: str) -> bytes:
    with zipfile.ZipFile(io.BytesIO(source)) as archive:
        if sum(item.file_size for item in archive.infolist()) > MAX_PREVIEW_BYTES:
            raise ValueError("The expanded manuscript is larger than 80 MB.")
        if suffix == ".docx":
            names = ["word/document.xml"]
        else:
            names = sorted(name for name in archive.namelist() if name.casefold().endswith((".xhtml", ".html", ".htm")))
        fragments = []
        for name in names:
            try:
                markup = archive.read(name).decode("utf-8", errors="replace")
            except KeyError:
                continue
            markup = re.sub(r"</(?:w:p|p|h[1-6]|div|li)>", "\n", markup, flags=re.IGNORECASE)
            fragments.append(html.unescape(re.sub(r"<[^>]+>", "", markup)))
    text = "\n".join(fragments).strip()
    if not text:
        raise ValueError("Bookinator could not find readable text in that manuscript.")
    return text.encode("utf-8")


def front_matter_metadata(source: bytes) -> dict[str, str]:
    """Read the small, explicit YAML subset Bookinator uses for identity."""
    text = source.decode("utf-8-sig", errors="replace").replace("\r\n", "\n")
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    metadata: dict[str, str] = {}
    for line in lines[1:101]:
        if line.strip() in {"---", "..."}:
            break
        match = re.match(r"^\s*(title|author)\s*:\s*(.*?)\s*$", line, re.IGNORECASE)
        if not match:
            continue
        value = match.group(2).strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        metadata[match.group(1).casefold()] = value.strip()
    else:
        return {}
    return {key: value for key, value in metadata.items() if value}


def archive_manuscript_metadata_and_images(source: bytes, suffix: str) -> tuple[dict[str, str], list[dict[str, object]]]:
    """Extract package identity and embedded image candidates from EPUB or DOCX."""
    metadata: dict[str, str] = {}
    candidates: list[dict[str, object]] = []
    with zipfile.ZipFile(io.BytesIO(source)) as archive:
        if sum(item.file_size for item in archive.infolist()) > MAX_PREVIEW_BYTES:
            raise ValueError("The expanded manuscript is larger than 80 MB.")
        names = set(archive.namelist())
        image_entries: list[tuple[str, str, str]] = []
        if suffix == ".docx":
            try:
                core = ET.fromstring(archive.read("docProps/core.xml"))
                metadata = {
                    "title": str(core.findtext("{*}title") or "").strip(),
                    "author": str(core.findtext("{*}creator") or "").strip(),
                }
            except (KeyError, ET.ParseError):
                pass
            for name in sorted(names):
                if name.casefold().startswith("word/media/") and name.casefold().endswith((".png", ".jpg", ".jpeg", ".gif", ".webp")):
                    extension = Path(name).suffix.casefold().lstrip(".").replace("jpg", "jpeg")
                    image_entries.append((name, f"image/{extension}", "attachment"))
        elif suffix == ".epub":
            try:
                container = ET.fromstring(archive.read("META-INF/container.xml"))
                package_path = str(container.find(".//{*}rootfile").attrib.get("full-path") or "")
                package = ET.fromstring(archive.read(package_path))
                package_root = posixpath.dirname(package_path)
                package_metadata = package.find("{*}metadata")
                if package_metadata is not None:
                    metadata = {
                        "title": str(package_metadata.findtext("{*}title") or "").strip(),
                        "author": str(package_metadata.findtext("{*}creator") or "").strip(),
                    }
                manifest = package.find("{*}manifest")
                items = list(manifest) if manifest is not None else []
                cover_ids = {
                    str(meta.attrib.get("content") or "")
                    for meta in package.findall(".//{*}meta")
                    if str(meta.attrib.get("name") or "").casefold() == "cover"
                }
                cover_ids.update(str(item.attrib.get("id") or "") for item in items if "cover-image" in str(item.attrib.get("properties") or "").split())
                for item in items:
                    media_type = str(item.attrib.get("media-type") or "")
                    if not media_type.startswith("image/"):
                        continue
                    name = posixpath.normpath(posixpath.join(package_root, urllib.parse.unquote(str(item.attrib.get("href") or ""))))
                    if name in names:
                        role = "cover" if str(item.attrib.get("id") or "") in cover_ids else "attachment"
                        image_entries.append((name, media_type, role))
            except (KeyError, AttributeError, ET.ParseError):
                pass
        image_entries.sort(key=lambda item: item[2] != "cover")
        for name, media_type, role in image_entries[:12]:
            try:
                data = archive.read(name)
            except KeyError:
                continue
            if not 256 <= len(data) <= 8 * 1024 * 1024:
                continue
            candidates.append({
                "page": 0,
                "width": 0,
                "height": 0,
                "data": base64.b64encode(data).decode("ascii"),
                "mediaType": media_type,
                "role": role,
                "name": name,
            })
    return {key: value for key, value in metadata.items() if value}, candidates


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def process_is_alive(pid: int) -> bool:
    """Check another local server process without sending it a signal."""
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except PermissionError:
        return True
    except OSError:
        return False


def pipeline_worker_is_alive(book_id: str, pipeline: dict[str, object]) -> bool:
    """Recognize workers owned by this server or another live local server."""
    local_thread = PIPELINE_THREADS.get(book_id)
    if local_thread and local_thread.is_alive():
        return True
    # Explicit whole-book work runs on the single library queue thread. The
    # stage worker removes its PIPELINE_THREADS entry when it finishes, and a
    # request can observe that small hand-off window while the queue still owns
    # the book. Treating that as an orphan resets live state under the worker.
    with QUEUE_LOCK:
        queue_thread = QUEUE_THREAD
        queue_book_id = str(QUEUE_CURRENT_TASK.get("bookId") or "")
    if queue_thread and queue_thread.is_alive() and queue_book_id == book_id:
        return True
    try:
        owner_pid = int(pipeline.get("workerPid") or 0)
    except (TypeError, ValueError):
        owner_pid = 0
    return owner_pid != os.getpid() and process_is_alive(owner_pid)


def reset_interrupted_rollup(pipeline: dict[str, object], phase: str, diagnostic: str) -> None:
    """Make an abandoned whole-book run honestly retryable."""
    interrupted_at = utc_now()
    if phase == "questions":
        previous = pipeline.get("questionTracker") if isinstance(pipeline.get("questionTracker"), dict) else {}
        pipeline["questionTracker"] = {
            **previous,
            "status": "ready",
            "interruptedAt": interrupted_at,
            "error": diagnostic,
            "detail": "The previous reconciliation was interrupted. Ready to retry.",
        }
        pipeline["questionTracker"].pop("completedAt", None)
        pipeline["questionTracker"].pop("durationSeconds", None)
    elif phase == "whole-summary":
        previous = pipeline.get("wholeBookSummary") if isinstance(pipeline.get("wholeBookSummary"), dict) else {}
        pipeline["wholeBookSummary"] = {
            **previous,
            "status": "ready",
            "interruptedAt": interrupted_at,
            "error": diagnostic,
            "detail": "The previous whole-book synthesis was interrupted. Ready to retry.",
        }
        pipeline["wholeBookSummary"].pop("completedAt", None)
        pipeline["wholeBookSummary"].pop("durationSeconds", None)
    elif phase == "whole-dossier":
        previous = pipeline.get("wholeBookDossier") if isinstance(pipeline.get("wholeBookDossier"), dict) else {}
        pipeline["wholeBookDossier"] = {
            **previous,
            "status": "ready",
            "interruptedAt": interrupted_at,
            "error": diagnostic,
            "detail": "The previous whole-book dossier reconciliation was interrupted. Ready to retry.",
        }
        pipeline["wholeBookDossier"].pop("completedAt", None)
        pipeline["wholeBookDossier"].pop("durationSeconds", None)


def find_book(book_id: str) -> dict[str, object] | None:
    return next((book for book in load_library() if book.get("id") == book_id), None)


def pipeline_path(book: dict[str, object]) -> Path | None:
    manuscript_id = str(book.get("manuscriptId") or "")
    return BOOKS_ROOT / manuscript_id / "pipeline.json" if manuscript_id else None


def update_source_stage(book: dict[str, object], stages: list[dict[str, object]]) -> None:
    metadata = manuscript_metadata(str(book.get("manuscriptId") or ""))
    available = bool(metadata.get("sourceAvailable"))
    filename = str(metadata.get("sourceFilename") or book.get("sourceFilename") or "Source document")
    detail = f"{filename} is preserved locally and ready to download." if available else "The original source document is not available in this imported analysis."
    source_stage = next((stage for stage in stages if stage.get("id") == "source"), None)
    values = {
        "id": "source",
        "label": "Source document",
        "status": "complete" if available else "warning",
        "detail": detail,
        "sourceFilename": filename,
        "sourceFormat": str(metadata.get("sourceFormat") or "FILE"),
        "sourceSizeBytes": int(metadata.get("sourceSizeBytes") or 0),
        "sourceAvailable": available,
        "sourceOriginalPreserved": bool(metadata.get("sourceOriginalPreserved")),
        "downloadUrl": f"/api/books/{urllib.parse.quote(str(book.get('id') or ''))}/source" if available else "",
    }
    if source_stage:
        source_stage.update(values)
    else:
        stages.insert(0, values)


def load_pipeline(book: dict[str, object]) -> dict[str, object]:
    path = pipeline_path(book)
    if not path:
        return {"bookId": book.get("id"), "status": "blocked", "message": "This book has no saved manuscript. Drop the PDF in again to begin analysis.", "stages": [], "chapters": []}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            return {}
        ensure_signal_stages(payload)
        orphaned_child_changed = reconcile_orphaned_child_runs(payload)
        before = json.dumps({key: payload.get(key) for key in ("wholeBookSummary", "wholeBookDossier", "questionTracker")}, sort_keys=True)
        active_rollup_phase = str(payload.get("phase") or "") if pipeline_worker_is_alive(str(book.get("id") or ""), payload) else ""
        reset_inactive_whole_book_runs(payload, active_rollup_phase)
        orphaned_child_changed = orphaned_child_changed or before != json.dumps({key: payload.get(key) for key in ("wholeBookSummary", "wholeBookDossier", "questionTracker")}, sort_keys=True)
        update_source_stage(book, payload.setdefault("stages", []))
        if "chapterMapApproved" not in payload:
            worked = any(
                stage.get("id") in {"summaries", "dossiers"} and stage.get("status") not in {None, "pending", "blocked"}
                for stage in payload.get("stages", [])
            ) or any(chapter.get("status") in {"running", "complete", "failed"} for chapter in payload.get("chapters", []))
            payload["chapterMapApproved"] = worked
        heading_metadata_changed = False
        for chapter in payload.get("chapters", []):
            heading_metadata_changed = sanitize_chapter_headings(chapter) or heading_metadata_changed
            if chapter.get("status") == "complete" and not str(chapter.get("summary") or "").strip():
                chapter.update({"status": "failed", "error": "The previous model response contained no chapter summary. Resume to retry this chapter."})
            smell = chapter.get("smell") if isinstance(chapter.get("smell"), dict) else {}
            if chapter.get("smellStatus") == "complete" and smell.get("reviewErrors"):
                progress = smell.get("reviewProgress") if isinstance(smell.get("reviewProgress"), dict) else {}
                failed_batches = len(smell.get("reviewErrors", []))
                total_batches = int(progress.get("totalBatches") or 0)
                chapter.update({
                    "smellStatus": "failed",
                    "smellError": f"Incomplete Smells review: the editor model failed {failed_batches} of {total_batches} batches. Local evidence and usable judgments were preserved.",
                })
                orphaned_child_changed = True
        warnings = [
            *chapter_map_warnings(payload.get("chapters", []), payload.get("acceptedChapterLabelVariants", [])),
            *chapter_heading_report_warnings(payload.get("chapterHeadingReport", {})),
        ]
        payload["chapterMapWarnings"] = warnings
        payload["chapterMapSuspicious"] = bool(warnings)
        payload["analysisProvisional"] = bool(warnings or not payload.get("chapterMapApproved"))
        if warnings:
            structure = next((stage for stage in payload.get("stages", []) if stage.get("id") == "structure"), None)
            if structure and structure.get("status") not in {"pending", "running"}:
                structure.update({"status": "warning", "detail": f"Proposed map needs review: {'; '.join(warnings)} Analysis may continue provisionally."})
        if payload.get("phase") in {"preparing", "chapter-map"}:
            if heading_metadata_changed and payload.get("status") != "running":
                write_pipeline(book, payload)
            return payload
        try:
            extracted = json.loads(extracted_chapters_path(book).read_text(encoding="utf-8"))
            structure = {item.get("pageStart"): chapter_structure(str(item.get("text") or ""), str(item.get("title") or "")) for item in extracted}
            for chapter in payload.get("chapters", []):
                chapter.update({key: value for key, value in structure.get(chapter.get("pageStart"), {}).items() if value})
                heading_metadata_changed = sanitize_chapter_headings(chapter) or heading_metadata_changed
            archive = ensure_chapter_artifacts(book, extracted)
            payload["chapterArchive"] = archive
            chunk_archive = ensure_chunk_artifacts(book, extracted)
            payload["chunkArchive"] = {key: value for key, value in chunk_archive.items() if key != "chunks"}
            payload["chunks"] = chunk_archive.get("chunks", [])
            running_chunk_sequences = {
                int(chunk.get("sequence") or 0)
                for chunk in payload["chunks"]
                if chunk.get("dossierStatus") == "running"
            }
            hydrated_orphaned_changed = reconcile_orphaned_child_runs(payload)
            if hydrated_orphaned_changed:
                # Chunk artifacts are the durable source rehydrated above. If
                # reconciliation repairs only the in-memory ledger, the stale
                # running marker returns on the next request. Persist exactly
                # the artifacts that entered this load as running and were
                # proven orphaned by the active-stage invariant.
                for chunk in payload["chunks"]:
                    sequence = int(chunk.get("sequence") or 0)
                    if sequence in running_chunk_sequences and chunk.get("dossierStatus") != "running":
                        write_chunk_artifact(book, sequence, chunk)
                orphaned_child_changed = True
            stages = payload.setdefault("stages", [])
            archive_stage = next((stage for stage in stages if stage.get("id") == "chapter-archive"), None)
            archive_status = "complete" if archive.get("saved") else "warning"
            archive_detail = f"Saved {archive.get('count', 0)} ordered chapter objects locally for later analysis." if archive.get("saved") else "Chapter objects could not be verified on disk."
            if archive_stage:
                archive_stage.update({"status": archive_status, "detail": archive_detail})
            else:
                summary_index = next((index for index, stage in enumerate(stages) if stage.get("id") == "summaries"), len(stages))
                stages.insert(summary_index, {"id": "chapter-archive", "label": "Saved chapter objects", "status": archive_status, "detail": archive_detail})
            chunk_stage = next((stage for stage in stages if stage.get("id") == "chunking"), None)
            chunk_detail = f"Saved {chunk_archive.get('count', 0)} page-linked source chunks; structured dossiers are waiting." if chunk_archive.get("saved") else "Source chunks could not be verified on disk."
            if chunk_stage:
                chunk_stage.update({"status": "complete" if chunk_archive.get("saved") else "warning", "detail": chunk_detail})
            else:
                summary_index = next((index for index, stage in enumerate(stages) if stage.get("id") == "summaries"), len(stages))
                stages.insert(summary_index, {"id": "chunking", "label": "Source chunks", "status": "complete" if chunk_archive.get("saved") else "warning", "detail": chunk_detail})
            dossier_stage = next((stage for stage in stages if stage.get("id") == "dossiers"), None)
            dossier_complete = sum(1 for chunk in chunk_archive.get("chunks", []) if chunk.get("dossierStatus") == "complete")
            dossier_detail = f"Completed {dossier_complete} of {chunk_archive.get('count', 0)} structured dossiers."
            if dossier_stage:
                if dossier_stage.get("status") not in {"running", "paused", "warning"}:
                    dossier_stage.update({"status": "complete" if dossier_complete == chunk_archive.get("count", 0) and dossier_complete else "pending", "detail": dossier_detail})
            else:
                stages.append({"id": "dossiers", "label": "Chunk dossiers", "status": "complete" if dossier_complete == chunk_archive.get("count", 0) and dossier_complete else "pending", "detail": dossier_detail})
        except (OSError, json.JSONDecodeError, TypeError):
            pass
        if orphaned_child_changed or (heading_metadata_changed and payload.get("status") != "running"):
            write_pipeline(book, payload)
        return payload
    except (OSError, json.JSONDecodeError):
        payload = {
            "bookId": book.get("id"),
            "status": "ready",
            "message": "The manuscript is saved and ready for its first reading.",
            "stages": [
                {"id": "source", "label": "Source document", "status": "complete", "detail": "The uploaded source is preserved locally."},
                {"id": "extraction", "label": "Page extraction", "status": "pending", "detail": "Preserve text with PDF page provenance."},
                {"id": "structure", "label": "Chapter detection", "status": "pending", "detail": "Find likely chapter boundaries for review."},
                {"id": "chapter-archive", "label": "Saved chapter objects", "status": "pending", "detail": "Write one durable local object per ordered manuscript section."},
                {"id": "chunking", "label": "Source chunks", "status": "pending", "detail": "Create page-linked processing units without replacing chapter structure."},
                {"id": "summaries", "label": "Chapter summaries", "status": "pending", "detail": "Read each chapter with the assigned local model."},
                {"id": "emotions", "label": "Chapter emotions", "status": "pending", "detail": PIPELINE_STAGE_DEFINITIONS["emotions"][1]},
                {"id": "tags", "label": "Chapter tags", "status": "pending", "detail": PIPELINE_STAGE_DEFINITIONS["tags"][1]},
                {"id": "smells", "label": "Smells", "status": "pending", "detail": PIPELINE_STAGE_DEFINITIONS["smells"][1]},
                {"id": "dossiers", "label": "Chunk dossiers", "status": "pending", "detail": "Build evidence-linked records from every source chunk."},
            ],
            "chapters": [],
        }
        update_source_stage(book, payload["stages"])
        return payload


def write_pipeline(book: dict[str, object], pipeline: dict[str, object]) -> None:
    path = pipeline_path(book)
    if not path:
        return
    reconcile_orphaned_child_runs(pipeline)
    for chapter in pipeline.get("chapters", []):
        sanitize_chapter_headings(chapter)
    ensure_signal_stages(pipeline)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(pipeline, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def aggregate_manuscript_metrics(chapters: list[dict[str, object]]) -> dict[str, int | bool]:
    """Sum authored-manuscript counts without front matter or chunk overlap."""
    manuscript_chapters = [
        chapter for chapter in chapters
        if re.sub(r"^#{1,6}\s+", "", str(chapter.get("title") or "").strip()).casefold() != "front matter"
    ]
    source_pages: set[int] = set()
    for chapter in manuscript_chapters:
        try:
            first_page = int(chapter.get("pageStart") or 0)
            last_page = int(chapter.get("pageEnd") or first_page)
        except (TypeError, ValueError):
            continue
        if first_page > 0 and last_page >= first_page:
            source_pages.update(range(first_page, last_page + 1))
    return {
        "pageCount": len(source_pages),
        "characterCount": sum(int(chapter.get("characterCount") or 0) for chapter in manuscript_chapters),
        "wordCount": sum(int(chapter.get("wordCount") or 0) for chapter in manuscript_chapters),
        "paragraphCount": sum(int(chapter.get("paragraphCount") or 0) for chapter in manuscript_chapters),
        "sectionCount": sum(int(chapter.get("sectionCount") or 0) for chapter in manuscript_chapters),
        "chapterCount": len(manuscript_chapters),
        "excludesFrontMatter": True,
    }


def add_pipeline_progress(pipeline: dict[str, object]) -> dict[str, object]:
    chapters = pipeline.get("chapters", [])
    if not isinstance(chapters, list) or not chapters:
        pipeline["progress"] = {"completed": 0, "total": 0, "percent": 0, "etaSeconds": None}
        pipeline["emotionProgress"] = {"completed": 0, "total": 0, "percent": 0, "etaSeconds": None}
        pipeline["tagProgress"] = {"completed": 0, "total": 0, "percent": 0, "etaSeconds": None}
        pipeline["smellProgress"] = {"completed": 0, "total": 0, "percent": 0, "etaSeconds": None}
        pipeline["dossierProgress"] = {"completed": 0, "total": 0, "percent": 0, "etaSeconds": None}
        pipeline["pipelineProgress"] = {"completed": 0, "total": 0, "percent": 0, "etaSeconds": None}
        pipeline["manuscriptMetrics"] = aggregate_manuscript_metrics([])
        return pipeline
    pipeline["manuscriptMetrics"] = aggregate_manuscript_metrics(chapters)
    manuscript_chapters = [
        chapter for chapter in chapters
        if strip_markdown_heading(chapter.get("title")).casefold() != "front matter"
    ]
    completed_chapters = [chapter for chapter in manuscript_chapters if chapter.get("status") == "complete"]
    summary_stage = next((stage for stage in pipeline.get("stages", []) if stage.get("id") == "summaries"), {})
    active_model = str(summary_stage.get("model") or "")
    timed = [chapter for chapter in completed_chapters if chapter.get("durationSeconds") and (not active_model or chapter.get("model") == active_model)]
    timed.sort(key=lambda chapter: str(chapter.get("completedAt") or ""))
    durations = [float(chapter["durationSeconds"]) for chapter in timed[-5:]]
    completed = len(completed_chapters)
    total = len(manuscript_chapters)
    remaining = total - completed
    eta_seconds = round(sum(durations) / len(durations) * remaining) if durations else None
    pipeline["progress"] = {
        "completed": completed,
        "total": total,
        "percent": round(completed / total * 100) if total else 100,
        "etaSeconds": eta_seconds,
        "etaSampleSize": len(durations),
        "averageChapterSeconds": round(sum(durations) / len(durations)) if durations else None,
        "remainingChapters": remaining,
        "etaModel": active_model,
    }
    for prefix, output_key, stage_id in (("emotion", "emotionProgress", "emotions"), ("tag", "tagProgress", "tags"), ("smell", "smellProgress", "smells")):
        completed_items = [chapter for chapter in manuscript_chapters if chapter.get(f"{prefix}Status") == "complete"]
        active_stage_model = str(next((stage.get("model") for stage in pipeline.get("stages", []) if stage.get("id") == stage_id), "") or "")
        timed_items = [chapter for chapter in completed_items if chapter.get(f"{prefix}DurationSeconds") and (not active_stage_model or chapter.get(f"{prefix}Model") == active_stage_model)]
        timed_items.sort(key=lambda chapter: str(chapter.get(f"{prefix}CompletedAt") or ""))
        stage_durations = [float(chapter[f"{prefix}DurationSeconds"]) for chapter in timed_items[-5:]]
        stage_remaining = total - len(completed_items)
        pipeline[output_key] = {
            "completed": len(completed_items), "total": total,
            "percent": round(len(completed_items) / total * 100) if total else 0,
            "etaSeconds": round(sum(stage_durations) / len(stage_durations) * stage_remaining) if stage_durations else None,
            "etaSampleSize": len(stage_durations), "remainingChapters": stage_remaining,
            "etaModel": active_stage_model,
        }
    chunks = pipeline.get("chunks", [])
    chapter_sequences = {str(chapter.get("sequence") or chapter.get("number") or "") for chapter in manuscript_chapters}
    manuscript_chunks = [chunk for chunk in chunks if str(chunk.get("chapterSequence") or "") in chapter_sequences] if isinstance(chunks, list) else []
    dossier_complete = [chunk for chunk in manuscript_chunks if chunk.get("dossierStatus") == "complete"]
    dossier_model = str(next((stage.get("model") for stage in pipeline.get("stages", []) if stage.get("id") == "dossiers"), "") or "")
    dossier_timed = [chunk for chunk in dossier_complete if chunk.get("dossierDurationSeconds") and (not dossier_model or chunk.get("dossierModel") == dossier_model)]
    dossier_timed.sort(key=lambda chunk: str(chunk.get("dossierCompletedAt") or ""))
    dossier_durations = [float(chunk["dossierDurationSeconds"]) for chunk in dossier_timed[-5:]]
    dossier_total = len(manuscript_chunks)
    dossier_remaining = dossier_total - len(dossier_complete)
    pipeline["dossierProgress"] = {
        "completed": len(dossier_complete), "total": dossier_total,
        "percent": round(len(dossier_complete) / dossier_total * 100) if dossier_total else 0,
        "etaSeconds": round(sum(dossier_durations) / len(dossier_durations) * dossier_remaining) if dossier_durations else None,
        "etaSampleSize": len(dossier_durations), "remainingChunks": dossier_remaining,
    }
    stages = {str(stage.get("id") or ""): stage for stage in pipeline.get("stages", [])}
    structure_complete = len(manuscript_chapters) if stages.get("chapter-archive", {}).get("status") == "complete" else 0
    summary_complete = sum(1 for chapter in manuscript_chapters if chapter.get("status") == "complete")
    emotion_complete = sum(1 for chapter in manuscript_chapters if chapter.get("emotionStatus") == "complete")
    tag_complete = sum(1 for chapter in manuscript_chapters if chapter.get("tagStatus") == "complete")
    smell_complete = sum(1 for chapter in manuscript_chapters if chapter.get("smellStatus") == "complete")
    chunks_by_chapter: dict[str, list[dict[str, object]]] = {}
    for chunk in chunks if isinstance(chunks, list) else []:
        sequence = str(chunk.get("chapterSequence") or "")
        if sequence in chapter_sequences:
            chunks_by_chapter.setdefault(sequence, []).append(chunk)
    dossier_chapters_complete = sum(
        1 for sequence in chapter_sequences
        if chunks_by_chapter.get(sequence)
        and all(chunk.get("dossierStatus") == "complete" for chunk in chunks_by_chapter[sequence])
    )
    includes_smells = "smells" in stages and not stages.get("smells", {}).get("disabled")
    pipeline_stage_count = 5 + int(includes_smells)
    pipeline_completed = structure_complete + summary_complete + emotion_complete + tag_complete + (smell_complete if includes_smells else 0) + dossier_chapters_complete
    pipeline_total = len(manuscript_chapters) * pipeline_stage_count
    pipeline["pipelineProgress"] = {
        "completed": pipeline_completed,
        "total": pipeline_total,
        "percent": round(pipeline_completed / pipeline_total * 100) if pipeline_total else 0,
        "etaSeconds": None,
        "stageCount": pipeline_stage_count,
        "stages": ["Chapters", "Summaries", "Dossiers", "Emotions", "Tags", *(["Smells"] if includes_smells else [])],
        "chapterCount": len(manuscript_chapters),
        "basisLabel": f"{pipeline_stage_count} current passes × {len(manuscript_chapters)} manuscript chapters · front matter excluded",
        "etaLabel": "ETA will improve as Bookinator learns each pass",
    }
    summary_signature = stage_rollup_input_signature(pipeline, "summary")
    whole_book_ready = bool(summary_signature and pipeline_stage_ready(pipeline, "whole-book-summary"))
    previous_whole_book = pipeline.get("wholeBookSummary") if isinstance(pipeline.get("wholeBookSummary"), dict) else {}
    previous_status = str(previous_whole_book.get("status") or "")
    whole_book_current = bool(summary_signature and previous_whole_book.get("inputSignature") == summary_signature)
    pipeline["wholeBookSummary"] = {
        **previous_whole_book,
        "status": previous_status if whole_book_ready and whole_book_current and previous_status in {"complete", "running", "failed"} else "ready" if whole_book_ready else "blocked",
        "dependsOn": list(PIPELINE_STAGE_DEPENDENCIES["whole-book-summary"]),
        "detail": "Every chapter pass is current; the Summary rollup may run."
        if whole_book_ready else "Waiting for every chapter summary to be current.",
    }
    dossier_signature = stage_rollup_input_signature(pipeline, "dossier")
    whole_dossier_ready = bool(dossier_signature and pipeline_stage_ready(pipeline, "whole-book-dossier"))
    previous_whole_dossier = pipeline.get("wholeBookDossier") if isinstance(pipeline.get("wholeBookDossier"), dict) else {}
    dossier_status = str(previous_whole_dossier.get("status") or "")
    whole_dossier_current = bool(dossier_signature and previous_whole_dossier.get("inputSignature") == dossier_signature)
    pipeline["wholeBookDossier"] = {
        **previous_whole_dossier,
        "status": dossier_status if whole_dossier_ready and whole_dossier_current and dossier_status in {"complete", "running", "failed"} else "ready" if whole_dossier_ready else "blocked",
        "dependsOn": list(PIPELINE_STAGE_DEPENDENCIES["whole-book-dossier"]),
        "detail": "Every chunk dossier is current; the whole-book Dossier may run."
        if whole_dossier_ready else "Waiting for every chunk dossier to finish.",
    }
    question_signature = question_tracker_input_signature(pipeline)
    question_ready = bool(question_signature and pipeline_stage_ready(pipeline, "question-tracker"))
    previous_questions = pipeline.get("questionTracker") if isinstance(pipeline.get("questionTracker"), dict) else {}
    question_status = str(previous_questions.get("status") or "")
    question_current = bool(question_signature and previous_questions.get("inputSignature") == question_signature)
    pipeline["questionTracker"] = {
        **previous_questions,
        "status": question_status if question_ready and question_current and question_status in {"complete", "running", "failed"} else "ready" if question_ready else "blocked",
        "dependsOn": list(PIPELINE_STAGE_DEPENDENCIES["question-tracker"]),
        "detail": (
            "Grouped repeated questions and matched supported later payoffs."
            if question_ready and question_current and question_status == "complete"
            else "Matching repeated questions to supported later payoffs."
            if question_ready and question_current and question_status == "running"
            else "Question reconciliation failed; the evidence inputs remain safe."
            if question_ready and question_current and question_status == "failed"
            else "Chapter summaries and dossiers are current; questions can be reconciled."
            if question_ready else "Waiting for every chapter summary and dossier to finish."
        ),
    }
    tracker = pipeline["questionTracker"]
    connection_status = (
        "complete" if dossier_total and len(dossier_complete) == dossier_total
        else "partial" if dossier_complete
        else "blocked"
    )
    inference_algorithms = [
        {
            "id": "questions",
            "label": "Questions & payoffs",
            "status": tracker.get("status", "blocked"),
            "model": tracker.get("model"),
            "startedAt": tracker.get("startedAt"),
            "completedAt": tracker.get("completedAt"),
            "durationSeconds": tracker.get("durationSeconds"),
            "error": tracker.get("error"),
            "dependsOn": ["summaries", "dossiers"],
            "workspaceTab": "questions",
            "method": "Whole-book model reconciliation",
            "detail": tracker.get("detail") or "Group repeated questions and match supported later payoffs across the book.",
        },
        {
            "id": "connections",
            "label": "Dossier connections",
            "status": connection_status,
            "dependsOn": ["dossiers"],
            "workspaceTab": "connections",
            "method": "Deterministic section and chapter intersections",
            "detail": (
                f"Compare entities, locations, and times across {len(dossier_complete)} current dossiers."
                if dossier_complete else "Waiting for dossier evidence to compare."
            ),
        },
    ]
    pipeline["inferences"] = inference_algorithms
    stages_list = pipeline.setdefault("stages", [])
    stages_list[:] = [stage for stage in stages_list if stage.get("id") not in {"questions", "inferences"}]
    return pipeline


def opening_chapter_candidates(page_texts: list[str]) -> tuple[list[tuple[int, str]], list[tuple[int, str]]]:
    heading_pattern = re.compile(r"^(?P<title>(?:chapter(?:\s+|\s*[:.\-—]\s*)\S.{0,100}|prologue(?:\s*[:.\-—]\s*.*)?|epilogue(?:\s*[:.\-—]\s*.*)?|interlude(?:\s*[:.\-—]\s*.*)?))\s*$", re.IGNORECASE)
    explicit_starts: list[tuple[int, str]] = []
    named_starts: list[tuple[int, str]] = []
    for page_index, text in enumerate(page_texts):
        opening_lines = [line.strip() for line in text.splitlines()[:25] if line.strip()]
        matches = [match.group("title").strip() for line in opening_lines if (match := heading_pattern.match(line))]
        if len(matches) == 1:
            explicit_starts.append((page_index, matches[0]))
        elif not matches and opening_lines:
            # Named chapters often omit the word "Chapter" entirely. At the
            # top of a page, a short all-caps line is a useful signal only when
            # the manuscript has not established an explicit numbered spine.
            # Otherwise viewpoint markers such as TIMMY or SHADOW become false
            # chapters whenever they happen to begin a PDF page.
            candidate = opening_lines[0]
            words = candidate.split()
            letters = [character for character in candidate if character.isalpha()]
            if 1 <= len(words) <= 10 and len(candidate) <= 100 and letters and candidate == candidate.upper():
                named_starts.append((page_index, candidate))
    return explicit_starts, named_starts


def chapter_heading_report(
    page_texts: list[str], chapters: list[dict[str, object]], accepted_labels: list[str] | None = None,
    demoted_pages: list[int] | None = None,
) -> dict[str, object]:
    """Describe the repeatable heading family and excluded page-opening candidates."""
    explicit_starts, named_starts = opening_chapter_candidates(page_texts)
    accepted = {re.sub(r"\W+", "", label).casefold() for label in accepted_labels or []}
    demoted = {int(page) for page in demoted_pages or []}
    top_level = [
        {"label": str(chapter.get("title") or ""), "page": int(chapter.get("pageStart") or 1)}
        for chapter in chapters if str(chapter.get("title") or "").casefold() != "front matter"
    ]
    grouped: dict[str, dict[str, object]] = {}
    candidates = [*named_starts, *((page, label) for page, label in explicit_starts if page + 1 in demoted)]
    for page, label in candidates:
        key = re.sub(r"\W+", "", label).casefold()
        item = grouped.setdefault(key, {"label": label, "pages": [], "count": 0, "accepted": key in accepted, "demotedPages": []})
        item["pages"].append(page + 1)
        item["count"] = int(item["count"]) + 1
        if page + 1 in demoted:
            item["demotedPages"].append(page + 1)
    return {
        "pattern": "Numbered or named chapter headings" if explicit_starts else "Named opening headings",
        "topLevel": top_level,
        "otherCandidates": sorted(grouped.values(), key=lambda item: int(item["pages"][0])),
        "acceptedVariants": sorted(accepted_labels or [], key=str.casefold),
    }


def chapter_heading_report_warnings(report: dict[str, object]) -> list[str]:
    """Flag unique excluded openers while leaving repeated viewpoint labels alone."""
    candidates = report.get("otherCandidates", []) if isinstance(report, dict) else []
    unusual = [
        str(item.get("label") or "").strip()
        for item in candidates if isinstance(item, dict)
        and int(item.get("count") or 0) == 1
        and not item.get("accepted")
        and not item.get("demotedPages")
        and str(item.get("label") or "").strip()
    ]
    return [f"Unique page-opening headings outside the established chapter pattern: {', '.join(unusual)}"] if unusual else []


def detect_chapters(
    page_texts: list[str], accepted_labels: list[str] | None = None,
    demoted_pages: list[int] | None = None,
) -> tuple[list[dict[str, object]], str]:
    explicit_starts, named_starts = opening_chapter_candidates(page_texts)
    has_explicit_spine = len(explicit_starts) >= 2
    accepted = {re.sub(r"\W+", "", label).casefold() for label in accepted_labels or []}
    demoted = {int(page) for page in demoted_pages or []}
    explicit_starts = [(page, title) for page, title in explicit_starts if page + 1 not in demoted]
    named_starts = [(page, title) for page, title in named_starts if page + 1 not in demoted]
    # Two explicit headings establish a repeatable authored grammar. Mixing in
    # bare all-caps page openers after that point is much more likely to split
    # viewpoint/section headings than to discover real chapters. Named-only
    # manuscripts continue to use the all-caps fallback.
    accepted_named = [(page, title) for page, title in named_starts if re.sub(r"\W+", "", title).casefold() in accepted]
    starts = [*explicit_starts, *accepted_named] if has_explicit_spine else [*explicit_starts, *named_starts]
    if starts:
        # Contents pages often contain chapter-looking lines before the real
        # headings. A real heading should be unique; when a title repeats, the
        # later occurrence is the manuscript chapter rather than its TOC entry.
        last_occurrence = {re.sub(r"\W+", "", title).casefold(): page for page, title in starts}
        starts = [(page, title) for page, title in starts if last_occurrence[re.sub(r"\W+", "", title).casefold()] == page]
        starts.sort(key=lambda item: item[0])
    if not starts:
        starts = [(index, f"Pages {index + 1}–{min(index + 15, len(page_texts))}") for index in range(0, len(page_texts), 15)]
        method = "page groups; no confident chapter headings were found"
    else:
        if starts[0][0] > 0:
            starts.insert(0, (0, "Front matter"))
        method = "explicit opening-line chapter headings" if has_explicit_spine else "opening-line chapter headings"
    chapters: list[dict[str, object]] = []
    for number, (start, title) in enumerate(starts, start=1):
        end = starts[number][0] - 1 if number < len(starts) else len(page_texts) - 1
        text = "\n\n".join(page_texts[start:end + 1]).strip()
        chapters.append({"number": number, "sequence": number, "title": title, "pageStart": start + 1, "pageEnd": end + 1, "text": text, **chapter_structure(text, title)})
    return chapters, method


def join_pdf_lines(lines: list[str]) -> str:
    """Join visual PDF lines without losing the boundary between words."""
    joined = ""
    for raw_line in lines:
        line = re.sub(r"\s+", " ", raw_line).strip()
        if not line or re.fullmatch(r"\d{1,4}", line):
            continue
        if not joined:
            joined = line
        elif joined.endswith("-"):
            joined += line
        else:
            joined += " " + line
    return joined.strip()


def normalize_pdf_text(text: str) -> str:
    """Turn PDF layout text into reflowable paragraphs and remove page numerals."""
    paragraphs = []
    for block in re.split(r"\n\s*\n+", text.replace("\r\n", "\n")):
        paragraph = join_pdf_lines(block.splitlines())
        if paragraph and not re.fullmatch(r"\d{1,4}", paragraph):
            paragraphs.append(paragraph)
    return "\n\n".join(paragraphs)


def manuscript_text_metrics(text: str) -> dict[str, int | float]:
    body = str(text or "").strip()
    words = re.findall(r"\b[\w’'-]+\b", body, re.UNICODE)
    prose = " ".join(line for line in body.splitlines() if not re.match(r"^#{1,6}\s+", line.strip()))
    sentences = [part.strip() for part in re.split(r"(?<=[.!?])(?:[\"”’']*)\s+", prose) if part.strip()]
    sentence_lengths = [len(re.findall(r"\b[\w’'-]+\b", sentence, re.UNICODE)) for sentence in sentences]
    paragraphs = [part for part in re.split(r"\n\s*\n+", body) if part.strip()]

    def average(values: list[int]) -> float:
        return round(sum(values) / len(values), 1) if values else 0.0

    def variation(values: list[int]) -> float:
        if not values:
            return 0.0
        mean = sum(values) / len(values)
        return round((sum((value - mean) ** 2 for value in values) / len(values)) ** 0.5, 1)

    return {
        "wordCount": len(words),
        "characterCount": len(body),
        "paragraphCount": len(paragraphs),
        "lineCount": len([line for line in body.splitlines() if line.strip()]),
        "sentenceCount": len(sentence_lengths),
        "averageSentenceWords": average(sentence_lengths),
        "sentenceLengthVariation": variation(sentence_lengths),
        "lexicalDiversity": round(len({word.casefold() for word in words}) / len(words), 3) if words else 0.0,
        "averageParagraphWords": average([len(re.findall(r"\b[\w’'-]+\b", paragraph, re.UNICODE)) for paragraph in paragraphs]),
    }


def pdf_blocks_to_paragraph_text(pages: list[list[tuple[object, ...]]]) -> str:
    """Reconstruct logical paragraphs from positioned PDF line blocks."""
    paragraphs: list[str] = []
    current: list[str] = []

    def flush() -> None:
        if current:
            paragraph = join_pdf_lines(current)
            if paragraph:
                paragraphs.append(paragraph)
            current.clear()

    for page_blocks in pages:
        for block in sorted(page_blocks, key=lambda item: (float(item[1]), float(item[0]))):
            raw = str(block[4] or "").replace("\r\n", "\n")
            lines = [line.strip() for line in raw.splitlines() if line.strip() and not re.fullmatch(r"\d{1,4}", line.strip())]
            if not lines:
                continue
            if re.match(r"^(?:CHAPTER\b|PROLOGUE$|EPILOGUE$|INTERLUDE$)", lines[0], re.IGNORECASE):
                flush()
                paragraphs.extend(lines)
                continue
            # Word-processors commonly encode a first-line indent in x0. A
            # leading blank line in a PDF block is another paragraph signal.
            begins_paragraph = float(block[0]) >= 96 or bool(re.match(r"^\s*\n", raw))
            if begins_paragraph:
                flush()
            current.extend(lines)
    flush()
    return "\n\n".join(paragraphs)


def strip_markdown_heading(value: object) -> str:
    """Return authored heading text without its Markdown level marker."""
    return re.sub(r"^[\u200b-\u200d\ufeff\s]*#{1,6}[\t ]*", "", str(value or "")).strip()


def is_front_matter(item: dict[str, object], label_key: str = "title") -> bool:
    """Keep paratext from silently inheriting narrative-analysis assumptions."""
    return strip_markdown_heading(item.get(label_key)).casefold() == "front matter"


def front_matter_analysis_guidance(task: str) -> str:
    """Set the evidentiary ceiling for non-narrative opening material."""
    shared = """This excerpt is FRONT MATTER, not a story chapter. Treat it as paratext and structural evidence only.
Report only what is literally printed or mechanically observable: document type, ordering, repeated labels, alternation, numbering, credited names, dates, and other explicit publication or organizational facts.
Chapter and section titles are labels, not evidence of plot, theme, mood, genre, character identity, conflict, chronology, promises, or unanswered story questions. Do not infer abstract concepts or narrative meaning from title wording."""
    if task == "summary":
        return f"""{shared}
Write a compact structural inventory rather than a narrative summary. It is appropriate to note an observable pattern such as alternating TIMMY and SHADOW labels. Keep new_questions empty; a table of contents does not put story questions in play."""
    if task == "dossier":
        return f"""{shared}
Use the synopsis for a plain description of the paratext. Facts may contain explicit bibliographic or structural observations. Keep events, questions, promises, current_times, and timeline_observations empty unless the front matter itself states them directly in prose; never manufacture them from a table of contents."""
    return shared


def sanitize_chapter_headings(chapter: dict[str, object]) -> bool:
    """Keep Markdown syntax in chapter documents, never in display metadata."""
    changed = False
    for key in ("title", "chapterTitle"):
        value = chapter.get(key)
        cleaned = strip_markdown_heading(value)
        if value is not None and cleaned != value:
            chapter[key] = cleaned
            changed = True
    markers = chapter.get("sectionMarkers")
    if isinstance(markers, list):
        cleaned_markers = [cleaned for value in markers if (cleaned := strip_markdown_heading(value))]
        if cleaned_markers != markers:
            chapter["sectionMarkers"] = cleaned_markers
            changed = True
    return changed


def chapter_markdown(chapter: dict[str, object]) -> str:
    """Create the canonical, reflowable Markdown representation of a chapter."""
    label = strip_markdown_heading(chapter.get("title") or f"Section {chapter.get('sequence') or ''}")
    title = strip_markdown_heading(chapter.get("chapterTitle"))
    markers = {
        cleaned
        for value in chapter.get("sectionMarkers") or []
        if (cleaned := strip_markdown_heading(value)) and cleaned.casefold() != title.casefold()
    }
    output = [f"# {label}"]
    if title:
        output.extend(["", f"## {title}"])
    skipped_label = skipped_title = duplicate_title_skipped = False
    for raw_block in re.split(r"\n\s*\n+", str(chapter.get("text") or "").replace("\r\n", "\n")):
        lines = [line.strip() for line in raw_block.splitlines() if line.strip() and not re.fullmatch(r"\d{1,4}", line.strip())]
        while lines:
            first = lines[0]
            if not skipped_label and re.sub(r"\W+", "", first).casefold() == re.sub(r"\W+", "", label).casefold():
                skipped_label = True
                lines.pop(0)
                continue
            if title and not skipped_title and first == title:
                skipped_title = True
                lines.pop(0)
                continue
            if title and skipped_title and not duplicate_title_skipped and first == title:
                duplicate_title_skipped = True
                lines.pop(0)
                continue
            if first in markers:
                output.extend(["", f"### {first}"])
                lines.pop(0)
                continue
            break
        paragraph = join_pdf_lines(lines)
        if paragraph:
            output.extend(["", paragraph])
    return "\n".join(output).strip() + "\n"


def chapter_structure(text: str, label: str) -> dict[str, object]:
    """Extract a displayed chapter title and ordered section/viewpoint markers."""
    if label.casefold() == "front matter":
        return {}
    # Canonical chapter text is Markdown. Structural inference should operate on
    # the authored heading text, not expose Markdown punctuation in the UI.
    lines = [strip_markdown_heading(line) for line in text.splitlines()]
    meaningful = [(index, line) for index, line in enumerate(lines) if line]
    label_key = re.sub(r"\W+", "", label).casefold()
    label_position = next((position for position, (_, line) in enumerate(meaningful[:30]) if re.sub(r"\W+", "", line).casefold() == label_key), None)
    if label_position is None:
        return {}

    def structural_heading(value: str) -> bool:
        letters = [character for character in value if character.isalpha()]
        return bool(letters) and value == value.upper() and 1 <= len(value.split()) <= 8 and len(value) <= 60 and not value.endswith((".", "!", "?", ":", ";"))

    following = meaningful[label_position + 1:]
    chapter_title = next((line for _, line in following[:8] if structural_heading(line) and not line.isdigit()), "")
    markers: list[str] = []
    title_consumed = False
    for _, line in following:
        if not structural_heading(line) or line.isdigit():
            continue
        if chapter_title and line == chapter_title and not title_consumed:
            title_consumed = True
            continue
        if re.match(r"^(?:CHAPTER\b|PROLOGUE$|EPILOGUE$|INTERLUDE$)", line, re.IGNORECASE):
            continue
        markers.append(line)
    while chapter_title and markers and markers[0].casefold() == chapter_title.casefold():
        markers.pop(0)
    return {"chapterTitle": chapter_title, "sectionMarkers": markers}


def chapter_map_warnings(chapters: list[dict[str, object]], accepted_labels: list[str] | None = None) -> list[str]:
    warnings: list[str] = []
    accepted = {re.sub(r"\W+", "", label).casefold() for label in accepted_labels or []}
    seen: set[str] = set()
    duplicates: list[str] = []
    for chapter in chapters:
        displayed = str(chapter.get("title") or "").strip()
        title = re.sub(r"\W+", "", displayed).casefold()
        if title and title in seen and displayed not in duplicates:
            duplicates.append(displayed)
        seen.add(title)
    if duplicates:
        warnings.append(f"Repeated chapter labels: {', '.join(duplicates)}")

    numbered = [str(chapter.get("title") or "").strip() for chapter in chapters if re.match(r"^CHAPTER\s+(?:\d+|[IVXLCDM]+|ONE|TWO|THREE|FOUR|FIVE|SIX|SEVEN|EIGHT|NINE|TEN)\b", str(chapter.get("title") or "").strip(), re.IGNORECASE)]
    if len(numbered) >= 3:
        allowed = re.compile(r"^(?:FRONT MATTER|PROLOGUE|EPILOGUE|INTERLUDE|PART\b)", re.IGNORECASE)
        outliers = [
            str(chapter.get("title") or "").strip() for chapter in chapters
            if str(chapter.get("title") or "").strip()
            and not re.match(r"^CHAPTER\b", str(chapter.get("title") or "").strip(), re.IGNORECASE)
            and not allowed.match(str(chapter.get("title") or "").strip())
            and re.sub(r"\W+", "", str(chapter.get("title") or "")).casefold() not in accepted
        ]
        if outliers:
            warnings.append(f"Chapter labels outside the established numbered pattern: {', '.join(outliers)}")
    return warnings


def chapter_map_suspicious(chapters: list[dict[str, object]]) -> bool:
    return bool(chapter_map_warnings(chapters))


def invalidate_downstream_analysis(pipeline: dict[str, object], warnings: list[str], *, clear: bool = False) -> None:
    """Make every derivative of an untrusted chapter map visibly non-current."""
    stages = {stage.get("id"): stage for stage in pipeline.get("stages", [])}
    if structure := stages.get("structure"):
        structure.update({"status": "warning", "detail": f"Chapter map needs review: {'; '.join(warnings)}"})
    invalidate_pipeline_stage(
        pipeline, "structure", detail="Waiting for the chapter map to be accepted and rebuilt."
    )
    blocked = {
        "chapter-archive": "Waiting for an accepted chapter map.",
        "chunking": "Waiting for an accepted chapter map.",
        "summaries": "Previous summaries are stale until the chapter map is accepted and rebuilt.",
        "emotions": "Previous emotion scores are stale until the chapter map is accepted and rebuilt.",
        "tags": "Previous chapter tags are stale until the chapter map is accepted and rebuilt.",
        "dossiers": "Previous dossiers are stale until source chunks are rebuilt.",
    }
    for stage_id, detail in blocked.items():
        if stage := stages.get(stage_id):
            stage.update({"status": "blocked", "detail": detail})
            for key in ("startedAt", "completedAt"):
                stage.pop(key, None)
    if clear:
        pipeline["chapters"] = []
        pipeline["chunks"] = []
        pipeline.pop("chapterArchive", None)
        pipeline.pop("chunkArchive", None)
    else:
        for chapter in pipeline.get("chapters", []):
            chapter.update({"status": "pending", "emotionStatus": "pending", "tagStatus": "pending", "smellStatus": "pending", "stale": True})
        for chunk in pipeline.get("chunks", []):
            chunk.update({"dossierStatus": "pending", "stale": True})
    pipeline.update({
        "status": "review", "phase": "chapter-map", "chapterMapSuspicious": True,
        "chapterMapWarnings": warnings,
        "message": "Chapter map needs review before derived analysis can continue.",
        "updatedAt": utc_now(),
    })
    for key in ("completedAt", "stopRequested", "error"):
        pipeline.pop(key, None)


class PipelineCancelled(Exception):
    """Raised when a cooperative model stream is stopped by the editor."""


class ChapterSummaryError(ValueError):
    """A retryable model-output failure with inspectable response evidence."""

    def __init__(self, message: str, raw_response: str = "", response_keys: list[str] | None = None):
        super().__init__(message)
        self.raw_response = raw_response
        self.response_keys = response_keys or []


class ModelTransportExhausted(RuntimeError):
    """Raised after a local model connection fails repeatedly for one item."""

    def __init__(self, failures: list[dict[str, object]]):
        self.failures = failures
        super().__init__(str(failures[-1].get("error") or "The local model stopped responding."))


class DossierAnalysisExhausted(RuntimeError):
    """Keep every failed dossier attempt while exposing the final diagnosis."""

    def __init__(self, failures: list[dict[str, object]], cause: Exception):
        self.failures = failures
        self.cause = cause
        super().__init__(str(cause))


def normalized_model_field(payload: dict[str, object], *names: str) -> object:
    normalized = {re.sub(r"[^a-z0-9]", "", str(key).casefold()): value for key, value in payload.items()}
    return next((normalized[re.sub(r"[^a-z0-9]", "", name.casefold())] for name in names if re.sub(r"[^a-z0-9]", "", name.casefold()) in normalized), None)


def normalize_chapter_summary(payload: dict[str, object]) -> dict[str, object]:
    summary = str(normalized_model_field(payload, "summary", "chapter summary", "chapter_summary", "digest", "synopsis") or "").strip()
    if not summary:
        raise ChapterSummaryError("The model returned JSON without a chapter summary. This chapter remains retryable.", json.dumps(payload, ensure_ascii=False), [str(key) for key in payload])
    key_points = normalized_model_field(payload, "key points", "key_points", "keyPoints", "established facts")
    new_questions = normalized_model_field(payload, "new questions", "new_questions", "newQuestions", "open questions")
    return {
        "summary": summary,
        "keyPoints": [str(item).strip() for item in key_points if str(item).strip()] if isinstance(key_points, list) else [],
        "newQuestions": [str(item).strip() for item in new_questions if str(item).strip()] if isinstance(new_questions, list) else [],
    }


def cancel_active_model_response(book_id: str) -> bool:
    """Close the live Ollama stream so cancellation does not wait for another token."""
    with ACTIVE_MODEL_RESPONSES_LOCK:
        response = ACTIVE_MODEL_RESPONSES.pop(book_id, None)
    if not response:
        return False
    try:
        response.close()
    except OSError:
        pass
    return True


def quiesce_pipeline_for_refresh(book_id: str, pipeline: dict[str, object], timeout_seconds: float = 5.0) -> bool:
    """Stop an owning worker before an external refresh mutates its pipeline.

    Workers keep an in-memory pipeline while a model responds. Letting a retry
    write beside that worker allows its next checkpoint to resurrect the stale
    result. Cancellation is cooperative and the interrupted item remains
    pending, so the requested retry can safely become first in line.
    """
    if not pipeline_worker_is_alive(book_id, pipeline):
        return True
    QUEUE_CANCEL_EVENT.set()
    event = PIPELINE_CANCEL_EVENTS.get(book_id)
    if event:
        event.set()
    cancel_active_model_response(book_id)
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if not pipeline_worker_is_alive(book_id, pipeline):
            return True
        time.sleep(0.05)
    return not pipeline_worker_is_alive(book_id, pipeline)


def resident_ollama_models() -> set[str]:
    try:
        with urllib.request.urlopen("http://127.0.0.1:11434/api/ps", timeout=5) as response:
            return {
                str(item.get("name") or item.get("model") or "")
                for item in json.load(response).get("models", [])
                if isinstance(item, dict)
            }
    except (OSError, ValueError, TypeError, AttributeError, urllib.error.URLError, json.JSONDecodeError):
        return set()


def run_structured_model(prompt: str, model: str, schema: dict[str, object], cancel_event: threading.Event | None = None, run_key: str = "") -> tuple[dict[str, object], str]:
    """Run one structured response at a time, reusing only the current resident model."""
    global LAST_STRUCTURED_MODEL
    with STRUCTURED_MODEL_LOCK:
        resident_models = resident_ollama_models()
        if not resident_models and LAST_STRUCTURED_MODEL:
            resident_models.add(LAST_STRUCTURED_MODEL)
        for previous in resident_models - {model}:
            unload = urllib.request.Request(
                "http://127.0.0.1:11434/api/generate",
                data=json.dumps({"model": previous, "keep_alive": 0}).encode("utf-8"),
                headers={"Content-Type": "application/json"}, method="POST",
            )
            try:
                with urllib.request.urlopen(unload, timeout=30):
                    pass
            except (OSError, urllib.error.URLError):
                # The new request remains authoritative; Ollama may already
                # have evicted the previous model during a service recovery.
                pass
        LAST_STRUCTURED_MODEL = model
        return _run_structured_model(prompt, model, schema, cancel_event, run_key)


def _run_structured_model(prompt: str, model: str, schema: dict[str, object], cancel_event: threading.Event | None = None, run_key: str = "") -> tuple[dict[str, object], str]:
    options = {"temperature": 0.1}
    request = urllib.request.Request(
        "http://127.0.0.1:11434/api/chat",
        data=json.dumps({"model": model, "stream": True, "format": schema, "keep_alive": "10m", "options": options, "messages": [{"role": "user", "content": prompt}]}).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST",
    )
    parts: list[str] = []
    response = urllib.request.urlopen(request, timeout=900)
    if run_key:
        with ACTIVE_MODEL_RESPONSES_LOCK:
            ACTIVE_MODEL_RESPONSES[run_key] = response
    try:
        with response:
            for line in response:
                if cancel_event and cancel_event.is_set():
                    raise PipelineCancelled()
                if not line.strip():
                    continue
                payload = json.loads(line)
                parts.append(str(payload.get("message", {}).get("content") or ""))
                if payload.get("done"):
                    break
    except (OSError, ValueError):
        if cancel_event and cancel_event.is_set():
            raise PipelineCancelled() from None
        raise
    finally:
        if run_key:
            with ACTIVE_MODEL_RESPONSES_LOCK:
                if ACTIVE_MODEL_RESPONSES.get(run_key) is response:
                    ACTIVE_MODEL_RESPONSES.pop(run_key, None)
    if cancel_event and cancel_event.is_set():
        raise PipelineCancelled()
    raw_response = "".join(parts)
    try:
        result = json.loads(raw_response)
    except json.JSONDecodeError as error:
        # Preserve enough evidence for bounded callers to diagnose truncation
        # without putting the model's full response into the UI or logs.
        error.raw_response = raw_response
        raise
    if not isinstance(result, dict):
        raise ValueError("The model returned an invalid structured object.")
    return result, raw_response


def summarize_chapter(chapter: dict[str, object], model: str, cancel_event: threading.Event | None = None, run_key: str = "") -> dict[str, object]:
    text = str(chapter.get("text") or "")[:60_000]
    material_guidance = front_matter_analysis_guidance("summary") if is_front_matter(chapter) else "This is narrative manuscript material."
    prompt = f"""Read this manuscript chapter and create a compact editorial digest.
Return JSON only with: summary (string, 2-4 paragraphs), key_points (array of strings), new_questions (array of strings).
Report what the text establishes; do not invent resolutions or facts. This is a chapter summary, not a critique.

Material-specific instructions:
{material_guidance}

Chapter: {chapter.get('title')}
Chapter title: {chapter.get('chapterTitle') or 'Not stated'}
Viewpoint or section markers: {json.dumps(chapter.get('sectionMarkers') or [], ensure_ascii=False)}
PDF pages: {chapter.get('pageStart')}-{chapter.get('pageEnd')}

{text}
"""
    schema = {"type": "object", "properties": {"summary": {"type": "string", "minLength": 1}, "key_points": {"type": "array", "items": {"type": "string"}}, "new_questions": {"type": "array", "items": {"type": "string"}}}, "required": ["summary", "key_points", "new_questions"]}
    try:
        result, raw_response = run_structured_model(prompt, model, schema, cancel_event, run_key)
    except json.JSONDecodeError as error:
        raise ChapterSummaryError(f"The model returned malformed JSON: {error.msg}. This chapter remains retryable.") from error
    try:
        normalized = normalize_chapter_summary(result)
        if is_front_matter(chapter):
            # Never promote questions inferred from a table of contents into
            # the story's obligation ledger, even if the model overreaches.
            normalized["newQuestions"] = []
            normalized["analysisMode"] = "front-matter-structural"
        return normalized
    except ChapterSummaryError as error:
        error.raw_response = raw_response
        raise


def summarize_chapter_resilient(
    chapter: dict[str, object],
    model: str,
    cancel_event: threading.Event | None = None,
    run_key: str = "",
    retry_delays: tuple[float, ...] = (0.75, 2.0),
    on_retry=None,
) -> tuple[dict[str, object], list[dict[str, object]]]:
    """Retry local transport failures without stopping the rest of the book."""
    failures: list[dict[str, object]] = []
    for attempt in range(1, len(retry_delays) + 2):
        try:
            return summarize_chapter(chapter, model, cancel_event, run_key), failures
        except PipelineCancelled:
            raise
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError) as error:
            failure = {
                "attempt": attempt,
                "model": model,
                "completedAt": utc_now(),
                "error": model_runtime_failure(model, error),
                "exceptionType": type(error).__name__,
                "inputCharacters": len(str(chapter.get("text") or "")),
            }
            failures.append(failure)
            if cancel_event and cancel_event.is_set():
                raise PipelineCancelled() from None
            if attempt > len(retry_delays):
                raise ModelTransportExhausted(failures) from error
            if on_retry:
                on_retry(attempt, failure)
            delay = retry_delays[attempt - 1]
            if cancel_event and cancel_event.wait(delay):
                raise PipelineCancelled() from None
            if not cancel_event:
                time.sleep(delay)


def summarize_whole_book(pipeline: dict[str, object], model: str, cancel_event: threading.Event | None = None, run_key: str = "") -> dict[str, object]:
    chapters = [
        {
            "sequence": chapter.get("sequence") or chapter.get("number"),
            "title": strip_markdown_heading(chapter.get("title")),
            "chapter_title": strip_markdown_heading(chapter.get("chapterTitle")),
            "summary": chapter.get("summary"),
            "establishes": chapter.get("keyPoints") or [],
            "questions_in_play": chapter.get("newQuestions") or [],
        }
        for chapter in pipeline.get("chapters", [])
        if chapter.get("status") == "complete" and strip_markdown_heading(chapter.get("title")).casefold() != "front matter"
    ]
    source = json.dumps(chapters, ensure_ascii=False)
    prompt = f"""Synthesize these ordered chapter digests into a whole-book editorial digest.
Return JSON only with: summary (string, 3-6 compact paragraphs), key_points (array of what the book establishes), resolved_questions (array), and open_questions (array of questions still in play at the end).
Reconcile repeated questions across chapters. A question is resolved only when a later digest supplies a clear answer; do not infer a resolution merely because the question stops appearing. Preserve uncertainty and do not critique the manuscript.

Ordered chapter digests:
{source[:180_000]}
"""
    schema = {"type": "object", "properties": {
        "summary": {"type": "string", "minLength": 1},
        "key_points": {"type": "array", "items": {"type": "string"}},
        "resolved_questions": {"type": "array", "items": {"type": "string"}},
        "open_questions": {"type": "array", "items": {"type": "string"}},
    }, "required": ["summary", "key_points", "resolved_questions", "open_questions"]}
    result, _ = run_structured_model(prompt, model, schema, cancel_event, run_key)
    summary = str(result.get("summary") or "").strip()
    if not summary:
        raise ChapterSummaryError("The model returned JSON without a whole-book summary.", json.dumps(result, ensure_ascii=False), [str(key) for key in result])
    return {
        "summary": summary,
        "keyPoints": [str(item).strip() for item in result.get("key_points", []) if str(item).strip()],
        "resolvedQuestions": [str(item).strip() for item in result.get("resolved_questions", []) if str(item).strip()],
        "openQuestions": [str(item).strip() for item in result.get("open_questions", []) if str(item).strip()],
        "inputCharacters": len(source),
    }


def reconcile_whole_book_dossier(pipeline: dict[str, object], model: str, cancel_event: threading.Event | None = None, run_key: str = "") -> dict[str, object]:
    """Merge current chunk dossiers into one inspectable book memory."""
    chunks = [
        {
            "chapter": int(chunk.get("chapterSequence") or 0),
            "chunk": int(chunk.get("chunkInChapter") or 0),
            **{
                field: (chunk.get("dossier") or {}).get(field) or ([] if field != "synopsis" else "")
                for field in ("synopsis", "facts", "events", "entities", "locations", "current_times", "questions", "promises", "timeline_observations")
            },
        }
        for chunk in pipeline.get("chunks", [])
        if chunk.get("dossierStatus") == "complete" and isinstance(chunk.get("dossier"), dict)
    ]
    source = json.dumps(chunks, ensure_ascii=False)
    prompt = f"""Reconcile these ordered chunk dossiers into one whole-book dossier.
Return JSON only with: synopsis (3-6 compact paragraphs), facts, events, entities, locations, current_times, questions, promises, timeline_observations, and contradictions (arrays of concise strings).
Deduplicate repeated observations and names while preserving meaningful uncertainty, chronology, and variant forms. Do not invent manuscript facts. A contradiction must identify two genuinely incompatible claims; ordinary change over time is not a contradiction. Keep questions and promises distinct from established facts.

Ordered chunk dossiers:
{source[:180_000]}
"""
    array = {"type": "array", "items": {"type": "string"}}
    schema = {
        "type": "object",
        "properties": {"synopsis": {"type": "string", "minLength": 1}, **{field: array for field in ("facts", "events", "entities", "locations", "current_times", "questions", "promises", "timeline_observations", "contradictions")}},
        "required": ["synopsis", "facts", "events", "entities", "locations", "current_times", "questions", "promises", "timeline_observations", "contradictions"],
    }
    result, _ = run_structured_model(prompt, model, schema, cancel_event, run_key)
    synopsis = str(result.get("synopsis") or "").strip()
    if not synopsis:
        raise ValueError("The model returned JSON without a whole-book dossier synopsis.")
    return {
        "synopsis": synopsis,
        **{field: [str(item).strip() for item in result.get(field, []) if str(item).strip()] for field in ("facts", "events", "entities", "locations", "current_times", "questions", "promises", "timeline_observations", "contradictions")},
        "inputCharacters": len(source),
    }


def question_tracker_input_signature(pipeline: dict[str, object]) -> str:
    """Fingerprint the chapter digests and dossier questions used by the tracker."""
    if not pipeline_stage_ready(pipeline, "question-tracker"):
        return ""
    chapters = [
        {
            "sequence": int(chapter.get("sequence") or chapter.get("number") or 0),
            "title": strip_markdown_heading(chapter.get("title")),
            "summary": str(chapter.get("summary") or ""),
            "keyPoints": chapter.get("keyPoints") or [],
            "newQuestions": chapter.get("newQuestions") or [],
        }
        for chapter in pipeline.get("chapters", [])
        if chapter.get("status") == "complete" and strip_markdown_heading(chapter.get("title")).casefold() != "front matter"
    ]
    dossier_questions = [
        {
            "chapter": int(chunk.get("chapterSequence") or 0),
            "chunk": int(chunk.get("chunkInChapter") or 0),
            "questions": (chunk.get("dossier") or {}).get("questions") or [],
            "promises": (chunk.get("dossier") or {}).get("promises") or [],
        }
        for chunk in pipeline.get("chunks", [])
        if chunk.get("dossierStatus") == "complete" and isinstance(chunk.get("dossier"), dict)
    ]
    source = json.dumps({"chapters": chapters, "dossierQuestions": dossier_questions}, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def reconcile_questions_and_payoffs(pipeline: dict[str, object], model: str, cancel_event: threading.Event | None = None, run_key: str = "") -> dict[str, object]:
    """Group repeated narrative questions and identify only supported payoffs."""
    chapters = [
        {
            "sequence": int(chapter.get("sequence") or chapter.get("number") or 0),
            "title": strip_markdown_heading(chapter.get("title")),
            "summary": chapter.get("summary"),
            "establishes": chapter.get("keyPoints") or [],
            "questions": chapter.get("newQuestions") or [],
        }
        for chapter in pipeline.get("chapters", [])
        if chapter.get("status") == "complete" and strip_markdown_heading(chapter.get("title")).casefold() != "front matter"
    ]
    dossier_questions = [
        {
            "chapter": int(chunk.get("chapterSequence") or 0),
            "chunk": int(chunk.get("chunkInChapter") or 0),
            "questions": (chunk.get("dossier") or {}).get("questions") or [],
            "promises": (chunk.get("dossier") or {}).get("promises") or [],
        }
        for chunk in pipeline.get("chunks", [])
        if chunk.get("dossierStatus") == "complete" and isinstance(chunk.get("dossier"), dict) and ((chunk.get("dossier") or {}).get("questions") or (chunk.get("dossier") or {}).get("promises"))
    ]
    source = json.dumps({"chapters": chapters, "dossierQuestions": dossier_questions}, ensure_ascii=False)
    prompt = f"""Reconcile the narrative questions in this ordered manuscript digest into a questions-and-payoffs tracker.
Return JSON only with a groups array. Each group must contain:
- canonical_question: a short question readers can recognize
- retellings: every materially equivalent phrasing as objects with text and chapter
- trigger_chapter: the earliest chapter that raises the question
- status: exactly resolved, possible, or open
- resolution_chapter: the chapter that answers it, or 0 when there is no supported answer
- answer: a compact statement of the answer or possible payoff, empty when open
- confidence: high, medium, or low

Story and character promises may be rewritten as the question their payoff would answer. Group phrasings only when they express the same narrative obligation. Do not merge merely related mysteries.
Mark resolved only when a chapter at or after the trigger supplies a clear answer. Mark possible when a later digest plausibly answers it but the match or answer is incomplete. Otherwise mark open. A question disappearing is not a resolution. Preserve uncertainty. Use only the supplied chapter digests and dossier questions; do not invent manuscript facts.

Ordered source material:
{source[:180_000]}
"""
    retelling_schema = {"type": "object", "properties": {"text": {"type": "string"}, "chapter": {"type": "integer", "minimum": 0}}, "required": ["text", "chapter"]}
    group_schema = {
        "type": "object",
        "properties": {
            "canonical_question": {"type": "string", "minLength": 1},
            "retellings": {"type": "array", "items": retelling_schema},
            "trigger_chapter": {"type": "integer", "minimum": 0},
            "status": {"type": "string", "enum": ["resolved", "possible", "open"]},
            "resolution_chapter": {"type": "integer", "minimum": 0},
            "answer": {"type": "string"},
            "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
        },
        "required": ["canonical_question", "retellings", "trigger_chapter", "status", "resolution_chapter", "answer", "confidence"],
    }
    result, _ = run_structured_model(prompt, model, {"type": "object", "properties": {"groups": {"type": "array", "items": group_schema}}, "required": ["groups"]}, cancel_event, run_key)
    valid_chapters = {int(chapter["sequence"]) for chapter in chapters if int(chapter["sequence"]) > 0}
    groups: list[dict[str, object]] = []
    for raw in result.get("groups", []) if isinstance(result.get("groups"), list) else []:
        if not isinstance(raw, dict):
            continue
        question = str(raw.get("canonical_question") or "").strip()
        if not question:
            continue
        retellings = []
        for item in raw.get("retellings", []) if isinstance(raw.get("retellings"), list) else []:
            if not isinstance(item, dict):
                continue
            text = str(item.get("text") or "").strip()
            chapter = int(item.get("chapter") or 0)
            if text and chapter in valid_chapters:
                retellings.append({"text": text, "chapter": chapter})
        trigger = int(raw.get("trigger_chapter") or 0)
        if trigger not in valid_chapters:
            trigger = min((item["chapter"] for item in retellings), default=min(valid_chapters, default=0))
        status = str(raw.get("status") or "open").casefold()
        if status not in {"resolved", "possible", "open"}:
            status = "open"
        resolution = int(raw.get("resolution_chapter") or 0)
        if resolution not in valid_chapters or resolution < trigger or status == "open":
            resolution = 0
            if status == "resolved":
                status = "possible" if str(raw.get("answer") or "").strip() else "open"
        groups.append({
            "question": question,
            "retellings": retellings,
            "triggerChapter": trigger,
            "status": status,
            "resolutionChapter": resolution,
            "chapterDelta": resolution - trigger if resolution and trigger else None,
            "answer": str(raw.get("answer") or "").strip() if status != "open" else "",
            "confidence": str(raw.get("confidence") or "low").casefold() if str(raw.get("confidence") or "").casefold() in {"high", "medium", "low"} else "low",
        })
    groups.sort(key=lambda item: (int(item.get("triggerChapter") or 0), str(item.get("question") or "").casefold()))
    return {"items": groups, "sourceQuestionCount": sum(len(item.get("questions") or []) + len(item.get("promises") or []) for item in dossier_questions) + sum(len(item.get("questions") or []) for item in chapters), "inputCharacters": len(source)}
def emotion_segments(chapter: dict[str, object], target_characters: int = 1_200) -> list[dict[str, object]]:
    """Create paragraph-aware, lightly overlapping classifier inputs."""
    text = str(chapter.get("text") or "")
    paragraphs = [(match.start(), match.end(), re.sub(r"\s+", " ", match.group()).strip()) for match in re.finditer(r"\S.*?(?=\n\s*\n|\Z)", text, re.S)]
    paragraphs = [item for item in paragraphs if item[2] and not re.fullmatch(r"#{1,6}\s+.*", item[2])]
    if not paragraphs and text.strip():
        paragraphs = [(0, len(text), re.sub(r"\s+", " ", text).strip())]
    segments: list[dict[str, object]] = []
    index = 0
    while index < len(paragraphs):
        start_index = index
        selected: list[tuple[int, int, str]] = []
        length = 0
        while index < len(paragraphs) and (length < target_characters or not selected):
            selected.append(paragraphs[index])
            length += len(paragraphs[index][2]) + 2
            index += 1
        segments.append({"sequence": len(segments) + 1, "characterStart": selected[0][0], "characterEnd": selected[-1][1], "pageStart": chapter.get("pageStart"), "pageEnd": chapter.get("pageEnd"), "text": "\n\n".join(item[2] for item in selected)})
        if index < len(paragraphs) and index - start_index > 1:
            index -= 1
    return segments


_EMOTION_CLASSIFIER: object | None = None


def classify_emotion_segments(segments: list[dict[str, object]], cancel_event: threading.Event | None = None) -> list[dict[str, object]]:
    """Run the pinned Hartmann model from the local HF cache; never download silently."""
    global _EMOTION_CLASSIFIER
    if importlib.util.find_spec("transformers") is None or importlib.util.find_spec("torch") is None:
        raise RuntimeError("The Hartmann emotion runtime is not installed. Install Bookinator’s emotion-model components in Local setup, then run this stage again.")
    if _EMOTION_CLASSIFIER is None:
        from transformers import AutoModelForSequenceClassification, AutoTokenizer, pipeline as hf_pipeline
        try:
            tokenizer = AutoTokenizer.from_pretrained(EMOTION_MODEL_ID, local_files_only=True)
            model = AutoModelForSequenceClassification.from_pretrained(EMOTION_MODEL_ID, local_files_only=True)
        except OSError as error:
            raise RuntimeError("The Hartmann emotion model is not installed locally. Install it from Local setup, then run this stage again.") from error
        _EMOTION_CLASSIFIER = hf_pipeline("text-classification", model=model, tokenizer=tokenizer, top_k=None, device=-1)
    results: list[dict[str, object]] = []
    for segment in segments:
        if cancel_event and cancel_event.is_set():
            raise PipelineCancelled()
        raw = _EMOTION_CLASSIFIER(str(segment.get("text") or ""), truncation=True, max_length=512)
        values = raw[0] if raw and isinstance(raw[0], list) else raw
        scores = {str(item.get("label") or "").casefold(): round(float(item.get("score") or 0), 6) for item in values or [] if isinstance(item, dict)}
        normalized = {label: scores.get(label, 0.0) for label in EMOTION_LABELS}
        winner = max(normalized, key=normalized.get) if normalized else "neutral"
        results.append({**{key: value for key, value in segment.items() if key != "text"}, "scores": normalized, "winner": winner, "winnerScore": normalized.get(winner, 0.0)})
    return results


def analyze_chapter_emotions(chapter: dict[str, object], cancel_event: threading.Event | None = None) -> dict[str, object]:
    scored = classify_emotion_segments(emotion_segments(chapter), cancel_event)
    distribution = {label: round(sum(float(item["scores"].get(label, 0)) for item in scored) / len(scored), 6) if scored else 0.0 for label in EMOTION_LABELS}
    peaks = sorted(({"label": label, "score": max((float(item["scores"].get(label, 0)) for item in scored), default=0.0), "segmentSequence": max(scored, key=lambda item: float(item["scores"].get(label, 0)))["sequence"] if scored else None} for label in EMOTION_LABELS), key=lambda item: item["score"], reverse=True)[:3]
    return {"schema": EMOTION_SCHEMA_VERSION, "model": EMOTION_MODEL_ID, "labels": list(EMOTION_LABELS), "segmentPolicy": "paragraph-aware-1200-characters-one-paragraph-overlap", "segments": scored, "distribution": distribution, "peaks": peaks}


def chapter_tag_schema() -> dict[str, object]:
    all_ids = [signal_id for ids in TAG_FAMILIES.values() for signal_id in ids]
    evidence = {"type": "object", "properties": {"quote": {"type": "string", "minLength": 1}, "location": {"type": "string"}}, "required": ["quote"]}
    # Structured generation must enforce the same provenance contract as the
    # semantic validator below. Returned signals are material findings, so an
    # empty evidence array is never a valid shape; weak or absent signals are
    # omitted instead of emitted without support.
    signal = {"type": "object", "properties": {"id": {"type": "string", "enum": all_ids}, "family": {"type": "string", "enum": list(TAG_FAMILIES)}, "score": {"type": "number", "minimum": .25, "maximum": 1}, "confidence": {"type": "number", "minimum": 0, "maximum": 1}, "explanation": {"type": "string", "minLength": 1}, "evidence": {"type": "array", "minItems": 1, "items": evidence}}, "required": ["id", "family", "score", "confidence", "explanation", "evidence"]}
    return {"type": "object", "properties": {"signals": {"type": "array", "items": signal}, "candidate_signals": {"type": "array", "items": {"type": "object", "properties": {"label": {"type": "string"}, "family": {"type": "string"}, "explanation": {"type": "string"}}, "required": ["label", "explanation"]}}}, "required": ["signals", "candidate_signals"]}


def analyze_chapter_tags(chapter: dict[str, object], model: str, cancel_event: threading.Event | None = None, run_key: str = "") -> dict[str, object]:
    vocabulary = "\n".join(f"- {family}: {', '.join(ids)}" for family, ids in TAG_FAMILIES.items())
    prompt = f"""Score this manuscript chapter against Bookinator's fixed editorial taxonomy.
Return JSON matching the supplied schema. Use only the listed signal IDs and their matching family.
Score means strength in the text; confidence means confidence in your judgment. Use score anchors .25, .5, .75, and 1.
Return only signals that score at least .25. Every returned signal requires at least one short exact supporting quote in its evidence array; signals above .6 normally require two quotes unless one scene dominates the chapter. Omit weak or absent signals instead of returning them with empty evidence. Do not force a label. Put a useful missing label in candidate_signals rather than inventing an ID.

Taxonomy:
{vocabulary}

Chapter: {chapter.get('title')}
Chapter title: {chapter.get('chapterTitle') or 'Not stated'}
Source pages: {chapter.get('pageStart')}-{chapter.get('pageEnd')}

{str(chapter.get('text') or '')[:60_000]}
"""
    result, _ = run_structured_model(prompt, model, chapter_tag_schema(), cancel_event, run_key)
    allowed: dict[str, set[str]] = {}
    for allowed_family, ids in TAG_FAMILIES.items():
        for signal_id in ids:
            allowed.setdefault(signal_id, set()).add(allowed_family)
    signals: list[dict[str, object]] = []
    candidate_signals = [dict(item) for item in result.get("candidate_signals", []) if isinstance(item, dict)] if isinstance(result.get("candidate_signals"), list) else []
    normalized_signals: list[dict[str, str]] = []
    rejected_signals: list[dict[str, object]] = []
    for raw in result.get("signals", []) if isinstance(result.get("signals"), list) else []:
        if not isinstance(raw, dict):
            rejected_signals.append({"reason": "The model returned a tag that was not an object.", "raw": raw})
            continue
        signal_id = str(raw.get("id") or "").strip()
        family = str(raw.get("family") or "").strip()
        allowed_families = allowed.get(signal_id, set())
        if not allowed_families:
            reason = f"The model suggested {signal_id or 'an unnamed tag'}, which is not in the fixed taxonomy."
            candidate_signals.append({"label": signal_id or "Unnamed tag", "family": family, "explanation": reason})
            rejected_signals.append({"id": signal_id, "family": family, "reason": reason})
            continue
        if family not in allowed_families:
            if len(allowed_families) == 1:
                canonical_family = next(iter(allowed_families))
                normalized_signals.append({"id": signal_id, "fromFamily": family, "toFamily": canonical_family})
                family = canonical_family
            else:
                reason = f"The model assigned {signal_id} to {family or 'no family'}, but that tag belongs to more than one possible family."
                candidate_signals.append({"label": signal_id, "family": family, "explanation": reason})
                rejected_signals.append({"id": signal_id, "family": family, "reason": reason})
                continue
        score = max(0.0, min(1.0, float(raw.get("score") or 0)))
        confidence = max(0.0, min(1.0, float(raw.get("confidence") or 0)))
        evidence_items = [item for item in raw.get("evidence", []) if isinstance(item, dict) and str(item.get("quote") or "").strip()]
        if not evidence_items:
            reason = f"The model suggested {signal_id}, but supplied no supporting quotation."
            candidate_signals.append({"label": signal_id, "family": family, "explanation": reason})
            rejected_signals.append({"id": signal_id, "family": family, "reason": reason})
            continue
        signals.append({"id": signal_id, "family": family, "score": round(score, 3), "confidence": round(confidence, 3), "explanation": str(raw.get("explanation") or "").strip(), "evidence": evidence_items})
    signals.sort(key=lambda item: (-float(item["score"]), -float(item["confidence"]), str(item["family"]), str(item["id"])))
    text = str(chapter.get("text") or "")
    dialogue_characters = sum(len(match.group()) for match in re.finditer(r"[“\"].*?[”\"]", text, re.S))
    return {"schema": TAG_SCHEMA_VERSION, "taxonomyVersion": TAG_TAXONOMY_VERSION, "promptVersion": TAG_PROMPT_VERSION, "chapterSequence": chapter.get("sequence") or chapter.get("number"), "model": model, "signals": signals, "candidateSignals": candidate_signals, "normalizedSignals": normalized_signals, "rejectedSignals": rejected_signals, "deterministic": {"dialogueCharacterRatio": round(dialogue_characters / len(text), 4) if text else 0, "paragraphCount": chapter.get("paragraphCount"), "sentenceCount": chapter.get("sentenceCount"), "sectionCount": chapter.get("sectionCount")}}


def analyze_chapter_tags_resilient(
    chapter: dict[str, object],
    model: str,
    cancel_event: threading.Event | None = None,
    run_key: str = "",
    attempts: int = 2,
) -> dict[str, object]:
    """Retry one malformed structured response without hiding the diagnosis."""
    failures: list[dict[str, object]] = []
    for attempt in range(1, max(1, attempts) + 1):
        try:
            artifact = analyze_chapter_tags(chapter, model, cancel_event, run_key)
            if failures:
                artifact["retryDiagnostics"] = failures
            return artifact
        except PipelineCancelled:
            raise
        except json.JSONDecodeError as error:
            failures.append({
                "attempt": attempt,
                "error": f"Malformed tag JSON: {error.msg}",
                "line": error.lineno,
                "column": error.colno,
                "completedAt": utc_now(),
            })
            if attempt >= max(1, attempts):
                raise
    raise RuntimeError("The chapter tagger did not return a result.")


def analyze_chapter_smells(
    chapter: dict[str, object],
    model: str,
    cancel_event: threading.Event | None = None,
    run_key: str = "",
    on_batch=None,
    candidate_limit: int | None = None,
) -> dict[str, object]:
    """Consolidate local detector evidence, then obtain inspectable editorial judgments."""
    text = str(chapter.get("text") or "")
    local = analyze_prose_smells(text)
    grouped: dict[tuple[int, int, str], list[dict[str, object]]] = {}
    for evidence in local.get("findings", []):
        key = (int(evidence.get("sentenceStart") or 0), int(evidence.get("sentenceEnd") or 0), str(evidence.get("sentence") or ""))
        grouped.setdefault(key, []).append(evidence)
    candidates: list[dict[str, object]] = []
    for (start, end, sentence), evidence in grouped.items():
        candidate_id = hashlib.sha256(f"{start}:{end}:{sentence}".encode()).hexdigest()[:16]
        paragraph_start, paragraph_end = text.rfind("\n\n", 0, start), text.find("\n\n", end)
        context_start = 0 if paragraph_start < 0 else paragraph_start + 2
        context_end = len(text) if paragraph_end < 0 else paragraph_end
        candidates.append({"id": candidate_id, "characterStart": start, "characterEnd": end, "sentence": sentence, "context": text[context_start:context_end].strip(), "evidence": evidence, "detectors": sorted({str(item.get("detector") or "") for item in evidence})})
    if candidate_limit is not None:
        candidates = candidates[:max(0, candidate_limit)]
    item_schema = {"type": "object", "properties": {"id": {"type": "string"}, "verdict": {"type": "string", "enum": ["report", "dismiss", "informational"]}, "severity": {"type": "string", "enum": ["low", "medium", "high"]}, "issue": {"type": "string"}, "reason": {"type": "string"}}, "required": ["id", "verdict", "severity", "issue", "reason"]}
    schema = {"type": "object", "properties": {"judgments": {"type": "array", "items": item_schema}}, "required": ["judgments"]}
    judgments: dict[str, dict[str, object]] = {}
    review_errors: list[dict[str, object]] = []
    batch_size = 8
    total_batches = (len(candidates) + batch_size - 1) // batch_size

    def artifact_snapshot(completed_batches: int, complete: bool = False) -> dict[str, object]:
        visible_candidates = copy.deepcopy(candidates)
        for candidate in visible_candidates:
            judgment = judgments.get(str(candidate["id"]))
            if judgment:
                candidate["judgment"] = judgment
            elif complete:
                candidate["judgment"] = {
                    "id": candidate["id"], "verdict": "informational", "severity": "low",
                    "issue": "Unreviewed local finding",
                    "reason": "The editorial model did not return a judgment for this candidate.",
                }
        decided = [item for item in visible_candidates if isinstance(item.get("judgment"), dict)]
        return {
            "schema": "bookinator-smells-v1", "model": model, "inputCharacters": len(text),
            "candidates": visible_candidates,
            "kept": sum(item["judgment"].get("verdict") in {"report", "keep"} for item in decided),
            "dismissed": sum(item["judgment"].get("verdict") == "dismiss" for item in decided),
            "informational": sum(item["judgment"].get("verdict") == "informational" for item in decided),
            "detectorErrors": local.get("errors", {}), "reviewErrors": copy.deepcopy(review_errors),
            "reviewProgress": {"completedBatches": completed_batches, "totalBatches": total_batches, "complete": complete},
        }

    if on_batch:
        on_batch(artifact_snapshot(0))
    for offset in range(0, len(candidates), batch_size):
        batch = candidates[offset:offset + batch_size]
        payload = [{"id": item["id"], "sentence": item["sentence"], "context": item["context"], "evidence": [{"detector": evidence.get("detector"), "rule": evidence.get("rule"), "message": evidence.get("message")} for evidence in item["evidence"]]} for item in batch]
        prompt = f"""You are Bookinator's skeptical fiction editor. Judge only these concrete prose-smell candidates; do not invent new complaints.
Preserve voice, rhythm, dialect, fragments, deliberate repetition, unusual vocabulary, genre conventions, and character speech. Do not reward blandness or mechanically simplified prose. A measurement can be true without being a problem. But you are still an editor: preservation of voice is not a reason to excuse a comma splice, garden path, ambiguous reference, accidental repetition, or a sentence whose nested structure makes its main action unnecessarily hard to recover.
Return exactly one judgment per id. "report" means "show this detector complaint to the author for a quick human decision"; it does not mean preserve the sentence and it does not mean the sentence is objectively bad. Report a candidate when a competent author might reasonably reconsider it because you can name a concrete reading cost, ambiguity, grammatical fault, or avoidable burden—even if the sentence remains understandable. Dismiss wrong, doctrinaire, or clearly purposeful complaints. Mark a true observation informational when it is useful but not a defect. Consolidate overlapping evidence. Do not rewrite. Make issue a specific 2–6 word label. Make reason one concrete sentence about this text; never merely say that complexity adds richness or does not impede comprehension.

Consistency rules:
- If your reason says the sentence is clear, understandable, effective, flows well, or does not impede comprehension, verdict must be dismiss or informational—not report.
- Length or clause count alone is not a reading cost. For report, identify what the reader may misattach, lose, reread, or mistake.
- A real comma splice between independent clauses is report. A deliberate fragment, paragraph-opening "But," dialect, or harmless repeated function word is normally dismiss.
- An Oxford-comma candidate is report only when it is a real series of three or more coordinate items; dismiss false positives on paired adjectives or trailing descriptors.

Candidates: {json.dumps(payload, ensure_ascii=False)}"""
        try:
            result, _ = run_structured_model(prompt, model, schema, cancel_event, f"{run_key}:batch-{offset // batch_size + 1}")
            allowed = {str(candidate["id"]) for candidate in batch}
            for item in result.get("judgments", []) if isinstance(result.get("judgments"), list) else []:
                if isinstance(item, dict) and str(item.get("id") or "") in allowed:
                    judgments[str(item["id"])] = item
        except PipelineCancelled:
            raise
        except Exception as error:
            review_errors.append({"firstCandidate": batch[0]["id"], "count": len(batch), "error": str(error)[:500]})
        if on_batch:
            on_batch(artifact_snapshot(offset // batch_size + 1))
    artifact = artifact_snapshot(total_batches, complete=not review_errors)
    if on_batch:
        on_batch(artifact)
    return artifact


def extracted_chapters_path(book: dict[str, object]) -> Path:
    return BOOKS_ROOT / str(book.get("manuscriptId")) / "extracted-chapters.json"


def load_chapter_source(book: dict[str, object], sequence: int) -> dict[str, object] | None:
    try:
        chapters = json.loads(extracted_chapters_path(book).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(chapters, list):
        return None
    chapter = next((item for item in chapters if isinstance(item, dict) and int(item.get("sequence") or item.get("number") or 0) == sequence), None)
    if not chapter:
        return None
    structure = chapter_structure(str(chapter.get("text") or ""), str(chapter.get("title") or ""))
    markdown_path = chapter_artifacts_path(book) / f"{sequence:04d}.md"
    try:
        markdown = markdown_path.read_text(encoding="utf-8")
    except OSError:
        markdown = str(chapter.get("markdown") or "") or chapter_markdown({**chapter, **structure})
    return {
        "sequence": sequence,
        "title": strip_markdown_heading(chapter.get("title") or f"Section {sequence}"),
        "chapterTitle": strip_markdown_heading(structure.get("chapterTitle") or chapter.get("chapterTitle")),
        "sectionMarkers": [strip_markdown_heading(value) for value in (structure.get("sectionMarkers") or chapter.get("sectionMarkers") or []) if strip_markdown_heading(value)],
        "pageStart": chapter.get("pageStart"),
        "pageEnd": chapter.get("pageEnd"),
        "text": str(chapter.get("text") or markdown),
        "markdown": markdown,
    }


def chapter_artifacts_path(book: dict[str, object]) -> Path:
    return BOOKS_ROOT / str(book.get("manuscriptId")) / "chapters"


def chunk_artifacts_path(book: dict[str, object]) -> Path:
    return BOOKS_ROOT / str(book.get("manuscriptId")) / "chunks"


def page_bounded_chunks(chapters: list[dict[str, object]], page_texts: list[str], target_characters: int = 32_000) -> list[dict[str, object]]:
    chunks: list[dict[str, object]] = []
    for chapter in chapters:
        page_start = int(chapter.get("pageStart") or 1)
        page_end = int(chapter.get("pageEnd") or page_start)
        pages = [(number, normalize_pdf_text(page_texts[number - 1])) for number in range(page_start, min(page_end, len(page_texts)) + 1)]
        if not pages:
            pages = [(page_start, str(chapter.get("text") or ""))]
        groups: list[list[tuple[int, str]]] = []
        current: list[tuple[int, str]] = []
        current_size = 0
        for page in pages:
            page_size = len(page[1])
            if current and current_size + page_size > target_characters:
                groups.append(current)
                current = [current[-1], page] if len(current) > 1 else [page]
                current_size = sum(len(item[1]) for item in current)
            else:
                current.append(page)
                current_size += page_size
        if current:
            groups.append(current)
        for chapter_chunk, group in enumerate(groups, start=1):
            sequence = len(chunks) + 1
            chunk_text = "\n\n--- PAGE BREAK ---\n\n".join(text for _, text in group).strip()
            chunk_metrics = manuscript_text_metrics(chunk_text)
            chunk_metrics["sectionCount"] = len(chapter_structure(chunk_text, str(chapter.get("title") or "")).get("sectionMarkers", []))
            chunks.append({
                "id": f"chapter-{int(chapter.get('sequence') or chapter.get('number') or 0):04d}-chunk-{chapter_chunk:03d}",
                "sequence": sequence,
                "chapterSequence": chapter.get("sequence") or chapter.get("number"),
                "chapterLabel": chapter.get("title"),
                "chapterTitle": chapter.get("chapterTitle", ""),
                "chunkInChapter": chapter_chunk,
                "pageStart": group[0][0],
                "pageEnd": group[-1][0],
                "text": chunk_text,
                "inputCharacters": len(chunk_text),
                **chunk_metrics,
                "overlap": "one-page" if chapter_chunk > 1 else "none",
                "dossierStatus": "pending",
            })
    return chunks


def ensure_chunk_artifacts(book: dict[str, object], chapters: list[dict[str, object]]) -> dict[str, object]:
    root = chunk_artifacts_path(book)
    chapter_signature = hashlib.sha256(json.dumps([{key: chapter.get(key) for key in ("sequence", "title", "pageStart", "pageEnd", "text")} for chapter in chapters], ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
    try:
        manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
        if manifest.get("chapterSignature") == chapter_signature:
            metadata = []
            for filename in manifest.get("files", []):
                artifact = json.loads((root / filename).read_text(encoding="utf-8"))
                if not isinstance(artifact.get("sectionCount"), int):
                    artifact["sectionCount"] = len(chapter_structure(str(artifact.get("text") or ""), str(artifact.get("chapterLabel") or "")).get("sectionMarkers", []))
                metadata.append({key: artifact.get(key) for key in ("id", "sequence", "chapterSequence", "chapterLabel", "chapterTitle", "chunkInChapter", "pageStart", "pageEnd", "inputCharacters", "characterCount", "wordCount", "paragraphCount", "lineCount", "sentenceCount", "averageSentenceWords", "sentenceLengthVariation", "lexicalDiversity", "averageParagraphWords", "sectionCount", "overlap", "dossierStatus", "dossier", "dossierModel", "dossierStartedAt", "dossierCompletedAt", "dossierDurationSeconds", "dossierError", "dossierRetryDiagnostics", "dossierRuns", "chapterMapStatus")})
            if len(metadata) == int(manifest.get("count") or 0):
                return {"saved": True, "count": len(metadata), "relativePath": "chunks/", "format": "bookinator-chunk-v1", "signature": manifest.get("signature"), "chunks": metadata}
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        pass
    manuscript = BOOKS_ROOT / str(book.get("manuscriptId")) / "manuscript.pdf"
    page_texts: list[str] = []
    try:
        import pymupdf  # type: ignore[import-not-found]
        with pymupdf.open(manuscript) as document:
            page_texts = [pdf_blocks_to_paragraph_text([page.get_text("blocks")]) for page in document]
    except (OSError, ImportError):
        pass
    chunks = page_bounded_chunks(chapters, page_texts)
    signature = hashlib.sha256(json.dumps([{key: chunk.get(key) for key in ("id", "pageStart", "pageEnd", "text")} for chunk in chunks], ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
    root.mkdir(parents=True, exist_ok=True)
    metadata = []
    for chunk in chunks:
        target = root / f"{int(chunk['sequence']):04d}.json"
        existing_dossier_fields: dict[str, object] = {}
        try:
            existing = json.loads(target.read_text(encoding="utf-8"))
            if existing.get("sourceSignature") == chapter_signature and isinstance(existing.get("dossier"), dict):
                existing_dossier_fields = {key: existing.get(key) for key in ("dossier", "dossierStatus", "dossierModel", "dossierStartedAt", "dossierCompletedAt", "dossierDurationSeconds", "dossierError", "chapterMapStatus") if existing.get(key) is not None}
        except (OSError, json.JSONDecodeError):
            pass
        artifact = {"schema": "bookinator-chunk-v1", "bookId": book.get("id"), "sourceSignature": chapter_signature, **chunk}
        if existing_dossier_fields:
            artifact.update(existing_dossier_fields)
        temporary = target.with_suffix(".tmp")
        temporary.write_text(json.dumps(artifact, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(target)
        metadata.append({key: artifact.get(key) for key in ("id", "sequence", "chapterSequence", "chapterLabel", "chapterTitle", "chunkInChapter", "pageStart", "pageEnd", "inputCharacters", "characterCount", "wordCount", "paragraphCount", "lineCount", "sentenceCount", "averageSentenceWords", "sentenceLengthVariation", "lexicalDiversity", "averageParagraphWords", "sectionCount", "overlap", "dossierStatus", "dossier", "dossierModel", "dossierStartedAt", "dossierCompletedAt", "dossierDurationSeconds", "dossierError", "dossierRetryDiagnostics", "dossierRuns", "chapterMapStatus")})
    expected = {f"{index:04d}.json" for index in range(1, len(chunks) + 1)}
    for stale in root.glob("[0-9][0-9][0-9][0-9].json"):
        if stale.name not in expected:
            stale.unlink()
    manifest = {"schema": "bookinator-chunk-archive-v1", "bookId": book.get("id"), "count": len(chunks), "signature": signature, "chapterSignature": chapter_signature, "targetCharacters": 32_000, "overlap": "one page", "files": sorted(expected), "updatedAt": utc_now()}
    temporary_manifest = (root / "manifest.json").with_suffix(".tmp")
    temporary_manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary_manifest.replace(root / "manifest.json")
    return {"saved": True, "count": len(chunks), "relativePath": "chunks/", "format": "bookinator-chunk-v1", "signature": signature, "chunks": metadata}


def ensure_chapter_artifacts(book: dict[str, object], chapters: list[dict[str, object]]) -> dict[str, object]:
    root = chapter_artifacts_path(book)
    canonical_chapters = [{**chapter, "markdown": str(chapter.get("markdown") or "") or chapter_markdown(chapter)} for chapter in chapters]
    signature_source = [{key: chapter.get(key) for key in ("sequence", "title", "chapterTitle", "pageStart", "pageEnd", "markdown")} for chapter in canonical_chapters]
    signature = hashlib.sha256(json.dumps(signature_source, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
    manifest_path = root / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        manifest = {}
    expected_names = [f"{index:04d}.json" for index in range(1, len(chapters) + 1)]
    expected_markdown = [f"{index:04d}.md" for index in range(1, len(chapters) + 1)]
    if manifest.get("signature") == signature and all((root / name).is_file() for name in [*expected_names, *expected_markdown]):
        return {"saved": True, "count": len(chapters), "relativePath": "chapters/", "format": "bookinator-chapter-markdown-v2", "signature": signature}
    root.mkdir(parents=True, exist_ok=True)
    for index, chapter in enumerate(canonical_chapters, start=1):
        artifact = {"schema": "bookinator-chapter-v2", "bookId": book.get("id"), **chapter, "text": chapter["markdown"]}
        target = root / f"{index:04d}.json"
        temporary = target.with_suffix(".tmp")
        temporary.write_text(json.dumps(artifact, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(target)
        markdown_target = root / f"{index:04d}.md"
        markdown_temporary = markdown_target.with_suffix(".tmp")
        markdown_temporary.write_text(str(chapter.get("markdown") or chapter.get("text") or ""), encoding="utf-8")
        markdown_temporary.replace(markdown_target)
    for stale in root.glob("[0-9][0-9][0-9][0-9].json"):
        if stale.name not in expected_names:
            stale.unlink()
    for stale in root.glob("[0-9][0-9][0-9][0-9].md"):
        if stale.name not in expected_markdown:
            stale.unlink()
    manifest = {"schema": "bookinator-chapter-archive-v2", "bookId": book.get("id"), "count": len(chapters), "signature": signature, "files": expected_names, "markdownFiles": expected_markdown, "canonicalFormat": "Markdown", "updatedAt": utc_now()}
    temporary_manifest = manifest_path.with_suffix(".tmp")
    temporary_manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary_manifest.replace(manifest_path)
    return {"saved": True, "count": len(chapters), "relativePath": "chapters/", "format": "bookinator-chapter-markdown-v2", "signature": signature}


def prepare_manuscript_pipeline(book_id: str) -> None:
    book = find_book(book_id)
    if not book:
        return
    pipeline = load_pipeline(book)
    pipeline.update({"status": "running", "phase": "preparing", "message": "Extracting pages and finding chapter boundaries.", "workerPid": os.getpid(), "startedAt": utc_now(), "updatedAt": utc_now()})
    for key in ("error", "completedAt", "stopRequested"):
        pipeline.pop(key, None)
    stages = {stage["id"]: stage for stage in pipeline.get("stages", [])}
    pipeline["chapters"] = []
    pipeline["chunks"] = []
    pipeline.pop("chapterArchive", None)
    pipeline.pop("chunkArchive", None)
    pipeline.pop("chapterMapWarnings", None)
    pipeline["chapterMapSuspicious"] = False
    pipeline["chapterMapApproved"] = False
    pipeline.pop("chapterMapApprovedAt", None)
    invalidate_pipeline_stage(
        pipeline, "extraction", include_self=True, status="pending",
        detail="Waiting for manuscript preparation.",
    )
    for stage_id in pipeline_stage_dependents("extraction") | {"extraction"}:
        if stage := stages.get(stage_id):
            stage.pop("model", None)
    try:
        manuscript = BOOKS_ROOT / str(book.get("manuscriptId")) / "manuscript.pdf"
        stages["extraction"].update({"status": "running", "startedAt": utc_now()})
        write_pipeline(book, pipeline)
        import pymupdf  # type: ignore[import-not-found]
        with pymupdf.open(manuscript) as document:
            page_blocks = [page.get_text("blocks") for page in document]
            page_texts = ["\n\n".join(str(block[4] or "") for block in sorted(blocks, key=lambda item: (item[1], item[0]))) for blocks in page_blocks]
        stages["extraction"].update({"status": "complete", "completedAt": utc_now(), "detail": f"Extracted {len(page_texts)} pages with page boundaries."})
        stages["structure"].update({"status": "running", "startedAt": utc_now()})
        accepted_variants = [str(label) for label in pipeline.get("acceptedChapterLabelVariants", [])]
        demoted_pages = [int(page) for page in pipeline.get("demotedChapterBoundaryPages", [])]
        chapters, method = detect_chapters(page_texts, accepted_variants, demoted_pages)
        for chapter in chapters:
            first_page = max(0, int(chapter.get("pageStart") or 1) - 1)
            last_page = min(len(page_blocks), int(chapter.get("pageEnd") or first_page + 1))
            chapter["text"] = pdf_blocks_to_paragraph_text(page_blocks[first_page:last_page])
            chapter.update(chapter_structure(str(chapter["text"]), str(chapter.get("title") or "")))
            markdown = chapter_markdown(chapter)
            chapter["markdown"] = markdown
            chapter["text"] = markdown
            chapter.update(manuscript_text_metrics(markdown))
            chapter["sectionCount"] = len(chapter.get("sectionMarkers", []))
        pipeline["chapterHeadingReport"] = chapter_heading_report(page_texts, chapters, accepted_variants, demoted_pages)
        map_warnings = [
            *chapter_map_warnings(chapters, accepted_variants),
            *chapter_heading_report_warnings(pipeline["chapterHeadingReport"]),
        ]
        stages["structure"].update({"status": "warning" if map_warnings else "complete", "completedAt": utc_now(), "detail": f"Detected {len(chapters)} sections using {method}." + (f" Review required: {'; '.join(map_warnings)}" if map_warnings else "")})
        visible_chapters = []
        for chapter in chapters:
            visible = {key: value for key, value in chapter.items() if key != "text"} | {"status": "pending"}
            visible_chapters.append(visible)
        pipeline["chapters"] = visible_chapters
        pipeline["chapterMapWarnings"] = map_warnings
        pipeline["chapterMapSuspicious"] = bool(map_warnings)
        pipeline["analysisProvisional"] = True
        provisional_note = "proposed" if map_warnings else "unapproved"
        stages["summaries"].update({"status": "pending", "detail": f"Ready to summarize {len(chapters)} chapters from the {provisional_note} map."})
        stages["dossiers"].update({"status": "pending", "detail": f"Source chunks from the {provisional_note} map are ready for fresh structured dossiers."})
        extracted_chapters_path(book).write_text(json.dumps(chapters, ensure_ascii=False) + "\n", encoding="utf-8")
        archive = ensure_chapter_artifacts(book, chapters)
        stages["chapter-archive"].update({"status": "complete", "completedAt": utc_now(), "detail": f"Saved {archive['count']} ordered chapter objects locally for later analysis."})
        pipeline["chapterArchive"] = archive
        chunk_archive = ensure_chunk_artifacts(book, chapters)
        stages["chunking"].update({"status": "complete", "completedAt": utc_now(), "detail": f"Saved {chunk_archive['count']} page-linked source chunks; structured dossiers are waiting."})
        pipeline["chunkArchive"] = {key: value for key, value in chunk_archive.items() if key != "chunks"}
        pipeline["chunks"] = chunk_archive.get("chunks", [])
        review_copy = " The map has anomalies worth reviewing." if map_warnings else " Review it when convenient."
        pipeline.update({"status": "ready", "phase": "chapter-map-proposed", "normalizationVersion": 2, "message": f"Found {len(chapters)} sections. Analysis can run provisionally.{review_copy}", "updatedAt": utc_now()})
        pipeline.pop("error", None)
        pipeline.pop("completedAt", None)
        pipeline.pop("stopRequested", None)
        write_pipeline(book, pipeline)
    except Exception as error:
        pipeline.update({"status": "failed", "message": "Manuscript preparation stopped.", "error": str(error)[:800], "updatedAt": utc_now()})
        write_pipeline(book, pipeline)
    finally:
        PIPELINE_THREADS.pop(book_id, None)
        PIPELINE_CANCEL_EVENTS.pop(book_id, None)


def reset_summary_run(book: dict[str, object], pipeline: dict[str, object]) -> dict[str, object]:
    archived_fields = ("model", "startedAt", "completedAt", "durationSeconds", "inputCharacters", "status")
    generated_fields = ("summary", "keyPoints", "newQuestions", "analysisMode", "error", "model", "startedAt", "completedAt", "durationSeconds", "inputCharacters")
    for chapter in pipeline.get("chapters", []):
        if chapter.get("model") or chapter.get("completedAt"):
            history = chapter.setdefault("summaryRuns", [])
            history.append({key: chapter.get(key) for key in archived_fields if chapter.get(key) is not None})
        for key in generated_fields:
            chapter.pop(key, None)
        chapter["status"] = "pending"
    invalidate_pipeline_stage(
        pipeline, "summaries", include_self=True, status="pending",
        detail="Fresh reading requested; every chapter is waiting for the assigned model.",
    )
    stages = {stage.get("id"): stage for stage in pipeline.get("stages", [])}
    summaries = stages.get("summaries")
    if summaries:
        summaries.update({"status": "pending", "detail": "Fresh reading requested; every chapter is waiting for the assigned model."})
        for key in ("model", "startedAt", "completedAt"):
            summaries.pop(key, None)
    pipeline.update({"status": "ready", "phase": "ready", "message": "Fresh reading requested. All chapters are waiting to be summarized.", "summaryStartedAt": utc_now(), "updatedAt": utc_now(), "runId": str(uuid.uuid4()), "runTargetTotal": len(pipeline.get("chapters", []))})
    for key in ("completedAt", "stopRequested", "error"):
        pipeline.pop(key, None)
    write_pipeline(book, pipeline)
    return pipeline


def reset_dossier_run(book: dict[str, object], pipeline: dict[str, object]) -> dict[str, object]:
    archived_fields = ("dossierModel", "dossierStartedAt", "dossierCompletedAt", "dossierDurationSeconds", "inputCharacters", "dossierStatus", "dossierError")
    generated_fields = ("dossier", "dossierModel", "dossierStartedAt", "dossierCompletedAt", "dossierDurationSeconds", "dossierError")
    for chunk in pipeline.get("chunks", []):
        if chunk.get("dossierModel") or chunk.get("dossierCompletedAt"):
            history = chunk.setdefault("dossierRuns", [])
            history.append({key: chunk.get(key) for key in archived_fields if chunk.get(key) is not None})
        for key in generated_fields:
            chunk.pop(key, None)
        chunk["dossierStatus"] = "pending"
    invalidate_pipeline_stage(
        pipeline, "dossiers", include_self=True, status="pending",
        detail="Fresh dossier pass requested; every source chunk is waiting for the assigned model.",
    )
    stages = {stage.get("id"): stage for stage in pipeline.get("stages", [])}
    dossiers = stages.get("dossiers")
    if dossiers:
        dossiers.update({"status": "pending", "detail": "Fresh dossier pass requested; every source chunk is waiting for the assigned model."})
        for key in ("model", "startedAt", "completedAt"):
            dossiers.pop(key, None)
    pipeline.update({"status": "ready", "phase": "ready", "message": "Fresh dossier pass requested.", "updatedAt": utc_now(), "runId": str(uuid.uuid4())})
    for key in ("completedAt", "stopRequested", "error"):
        pipeline.pop(key, None)
    write_pipeline(book, pipeline)
    return pipeline


def reset_chapter_signal_run(book: dict[str, object], pipeline: dict[str, object], kind: str) -> dict[str, object]:
    if kind not in {"emotion", "tag", "smell"}:
        raise ValueError("Unknown chapter signal pass.")
    stage_id = {"emotion": "emotions", "tag": "tags", "smell": "smells"}[kind]
    title = {"emotion": "emotion", "tag": "tag", "smell": "Smells"}[kind]
    generated = (kind, f"{kind}Model", f"{kind}StartedAt", f"{kind}CompletedAt", f"{kind}DurationSeconds", f"{kind}Error")
    for chapter in pipeline.get("chapters", []):
        if chapter.get(f"{kind}Model") or chapter.get(f"{kind}CompletedAt"):
            chapter.setdefault(f"{kind}Runs", []).append({key: chapter.get(key) for key in (*generated[1:], f"{kind}Status") if chapter.get(key) is not None})
        for key in generated:
            chapter.pop(key, None)
        chapter[f"{kind}Status"] = "excluded" if strip_markdown_heading(chapter.get("title")).casefold() == "front matter" else "pending"
    invalidate_pipeline_stage(pipeline, stage_id, include_self=True, status="pending", detail=f"Fresh {title} pass requested; every chapter is waiting.")
    stage = next((item for item in pipeline.get("stages", []) if item.get("id") == stage_id), None)
    if stage:
        stage.update({"status": "pending", "detail": f"Fresh {title} pass requested; every chapter is waiting."})
        for key in ("model", "startedAt", "completedAt", "setupRequired"):
            stage.pop(key, None)
    pipeline.update({"status": "ready", "phase": "ready", "message": f"Fresh {title} pass requested.", "updatedAt": utc_now(), "runId": str(uuid.uuid4())})
    for key in ("completedAt", "stopRequested", "error"):
        pipeline.pop(key, None)
    write_pipeline(book, pipeline)
    return pipeline


def refresh_analysis_result(book: dict[str, object], pipeline: dict[str, object], kind: str, sequence: int) -> tuple[str, bool]:
    """Reset one saved result after its owning worker has yielded the ledger."""
    was_running = False
    sibling_running = False
    if kind == "whole-summary":
        previous = pipeline.get("wholeBookSummary") if isinstance(pipeline.get("wholeBookSummary"), dict) else {}
        was_running = previous.get("status") == "running"
        history = list(pipeline.get("wholeBookSummaryRuns") or [])
        if previous.get("completedAt"):
            history.append(previous)
        pipeline["wholeBookSummaryRuns"] = history
        pipeline["wholeBookSummary"] = {"status": "ready", "dependsOn": ["summaries"], "detail": "A fresh whole-book summary is queued."}
        action = "whole-summary"
    elif kind == "summary":
        chapter = next((item for item in pipeline.get("chapters", []) if int(item.get("sequence") or item.get("number") or 0) == sequence), None)
        if not chapter:
            raise LookupError("Chapter not found.")
        was_running = chapter.get("status") == "running"
        if chapter.get("model") or chapter.get("completedAt"):
            chapter.setdefault("summaryRuns", []).append({key: chapter.get(key) for key in ("model", "startedAt", "completedAt", "durationSeconds", "inputCharacters", "status", "error") if chapter.get(key) is not None})
        for key in ("summary", "keyPoints", "newQuestions", "analysisMode", "error", "model", "startedAt", "completedAt", "durationSeconds", "inputCharacters"):
            chapter.pop(key, None)
        chapter["status"] = "pending"
        invalidate_pipeline_stage(pipeline, "summaries", include_self=True, status="pending", detail=f"Chapter {sequence} is waiting for a fresh summary.")
        pipeline["wholeBookSummary"] = {"status": "blocked", "dependsOn": ["summaries"], "detail": "Waiting for the refreshed chapter summary."}
        action = "summarize"
    elif kind in {"emotion", "tag", "smell"}:
        chapter = next((item for item in pipeline.get("chapters", []) if int(item.get("sequence") or item.get("number") or 0) == sequence), None)
        if not chapter:
            raise LookupError("Chapter not found.")
        was_running = chapter.get(f"{kind}Status") == "running"
        stage_id = {"emotion": "emotions", "tag": "tags", "smell": "smells"}[kind]
        if chapter.get(f"{kind}Model") or chapter.get(f"{kind}CompletedAt"):
            chapter.setdefault(f"{kind}Runs", []).append({key: chapter.get(key) for key in (f"{kind}Model", f"{kind}StartedAt", f"{kind}CompletedAt", f"{kind}DurationSeconds", f"{kind}Status", f"{kind}Error") if chapter.get(key) is not None})
        for key in (kind, f"{kind}Model", f"{kind}StartedAt", f"{kind}CompletedAt", f"{kind}DurationSeconds", f"{kind}InputCharacters", f"{kind}Error"):
            chapter.pop(key, None)
        chapter[f"{kind}Status"] = "pending"
        invalidate_pipeline_stage(pipeline, stage_id, status="pending", detail=f"Chapter {sequence} is waiting for fresh {kind} analysis.")
        sibling_running = any(item is not chapter and item.get(f"{kind}Status") == "running" for item in pipeline.get("chapters", []))
        stage = next((item for item in pipeline.get("stages", []) if item.get("id") == stage_id), None)
        if stage and not sibling_running:
            stage.update({"status": "pending", "detail": f"Chapter {sequence} is waiting for fresh {kind} analysis."})
            for key in ("startedAt", "completedAt"):
                stage.pop(key, None)
        action = stage_id
    else:
        matching = [chunk for chunk in pipeline.get("chunks", []) if int(chunk.get("sequence") or 0) == sequence]
        if not matching:
            raise LookupError("Dossier source chunk not found.")
        was_running = any(chunk.get("dossierStatus") == "running" for chunk in matching)
        for chunk in matching:
            if chunk.get("dossierModel") or chunk.get("dossierCompletedAt"):
                append_dossier_run(chunk)
            for key in ("dossier", "dossierModel", "dossierStartedAt", "dossierCompletedAt", "dossierDurationSeconds", "dossierError", "dossierRetryDiagnostics"):
                chunk.pop(key, None)
            chunk["dossierStatus"] = "pending"
            artifact_path = chunk_artifacts_path(book) / f"{int(chunk.get('sequence') or sequence):04d}.json"
            if artifact_path.exists():
                artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
                if artifact.get("dossierModel") or artifact.get("dossierCompletedAt"):
                    append_dossier_run(artifact)
                for key in ("dossier", "dossierModel", "dossierStartedAt", "dossierCompletedAt", "dossierDurationSeconds", "dossierError", "dossierRetryDiagnostics"):
                    artifact.pop(key, None)
                artifact["dossierStatus"] = "pending"
                write_chunk_artifact(book, int(chunk.get("sequence") or sequence), artifact)
        invalidate_pipeline_stage(pipeline, "dossiers", include_self=True, status="pending", detail=f"Dossier chunk {sequence} is waiting for fresh analysis.")
        action = "dossiers"
    target = "the whole book" if kind == "whole-summary" else f"dossier chunk {sequence}" if kind == "dossier" else f"chapter {sequence}"
    if sibling_running:
        pipeline.update({"message": f"Fresh {kind} requested for {target}; the active chapter continues first.", "updatedAt": utc_now()})
    else:
        pipeline.update({"status": "ready", "phase": "ready", "message": f"Fresh {kind} requested for {target}.", "updatedAt": utc_now()})
    write_pipeline(book, pipeline)
    return action, was_running


def retry_failed_analysis(book: dict[str, object], pipeline: dict[str, object]) -> int:
    """Return failed child results to the normal queue without touching successes."""
    retried = 0
    affected_stages: set[str] = set()
    summary_failed = False
    for chapter in pipeline.get("chapters", []):
        if chapter.get("status") == "failed":
            if chapter.get("model") or chapter.get("completedAt") or chapter.get("error"):
                chapter.setdefault("summaryRuns", []).append({
                    key: chapter.get(key)
                    for key in ("model", "startedAt", "completedAt", "durationSeconds", "inputCharacters", "status", "error")
                    if chapter.get(key) is not None
                })
            for key in ("summary", "keyPoints", "newQuestions", "analysisMode", "error", "model", "startedAt", "completedAt", "durationSeconds", "inputCharacters"):
                chapter.pop(key, None)
            chapter["status"] = "pending"
            retried += 1
            summary_failed = True
            affected_stages.add("summaries")
        for kind, stage_id in (("emotion", "emotions"), ("tag", "tags"), ("smell", "smells")):
            if chapter.get(f"{kind}Status") != "failed":
                continue
            chapter.setdefault(f"{kind}Runs", []).append({
                key: chapter.get(key)
                for key in (f"{kind}Model", f"{kind}StartedAt", f"{kind}CompletedAt", f"{kind}DurationSeconds", f"{kind}InputCharacters", f"{kind}Status", f"{kind}Error")
                if chapter.get(key) is not None
            })
            for key in (kind, f"{kind}Model", f"{kind}StartedAt", f"{kind}CompletedAt", f"{kind}DurationSeconds", f"{kind}InputCharacters", f"{kind}Error"):
                chapter.pop(key, None)
            chapter[f"{kind}Status"] = "pending"
            retried += 1
            affected_stages.add(stage_id)

    for chunk in pipeline.get("chunks", []):
        if chunk.get("dossierStatus") != "failed":
            continue
        append_dossier_run(chunk)
        for key in ("dossier", "dossierModel", "dossierStartedAt", "dossierCompletedAt", "dossierDurationSeconds", "dossierError", "dossierRetryDiagnostics"):
            chunk.pop(key, None)
        chunk["dossierStatus"] = "pending"
        sequence = int(chunk.get("sequence") or 0)
        artifact_path = chunk_artifacts_path(book) / f"{sequence:04d}.json"
        if sequence and artifact_path.exists():
            try:
                artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
                append_dossier_run(artifact)
                for key in ("dossier", "dossierModel", "dossierStartedAt", "dossierCompletedAt", "dossierDurationSeconds", "dossierError", "dossierRetryDiagnostics"):
                    artifact.pop(key, None)
                artifact["dossierStatus"] = "pending"
                write_chunk_artifact(book, sequence, artifact)
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                pass
        retried += 1
        affected_stages.add("dossiers")

    whole_summary = pipeline.get("wholeBookSummary")
    if isinstance(whole_summary, dict) and whole_summary.get("status") == "failed":
        pipeline.setdefault("wholeBookSummaryRuns", []).append(dict(whole_summary))
        pipeline["wholeBookSummary"] = {
            "status": "blocked" if summary_failed else "ready",
            "dependsOn": ["summaries"],
            "detail": "Waiting for retried chapter work." if summary_failed else "A fresh whole-book summary is queued.",
        }
        retried += 1
        affected_stages.add("whole-book-summary")
    elif summary_failed and isinstance(whole_summary, dict):
        if whole_summary.get("status") == "complete" or whole_summary.get("completedAt"):
            pipeline.setdefault("wholeBookSummaryRuns", []).append(dict(whole_summary))
        pipeline["wholeBookSummary"] = {
            "status": "blocked", "dependsOn": ["summaries"],
            "detail": "Waiting for retried chapter summaries.",
        }

    stages = {stage.get("id"): stage for stage in pipeline.get("stages", [])}
    for stage_id in affected_stages:
        stage = stages.get(stage_id)
        if not stage:
            continue
        stage.update({"status": "pending", "detail": "Retrying only the failed work in this stage."})
        for key in ("startedAt", "completedAt", "error", "setupRequired"):
            stage.pop(key, None)
    if summary_failed and isinstance(pipeline.get("wholeBookSummary"), dict):
        pipeline["wholeBookSummary"].update({"status": "blocked", "detail": "Waiting for retried chapter summaries."})
    if retried:
        pipeline.update({
            "status": "ready", "phase": "ready", "runId": str(uuid.uuid4()),
            "message": f"Queued {retried} failed analysis result{'s' if retried != 1 else ''} for retry.",
            "updatedAt": utc_now(),
        })
        for key in ("completedAt", "stopRequested", "error"):
            pipeline.pop(key, None)
    return retried


def run_chapter_signal_pipeline(book_id: str, kind: str, chapter_sequence: int | None = None) -> None:
    """Run one DRY chapter-signal stage; only the analyzer differs."""
    if kind not in {"emotion", "tag", "smell"}:
        return
    book = find_book(book_id)
    if not book:
        return
    pipeline = load_pipeline(book)
    ensure_signal_stages(pipeline)
    stages = {stage["id"]: stage for stage in pipeline.get("stages", [])}
    stage_id = {"emotion": "emotions", "tag": "tags", "smell": "smells"}[kind]
    prefix = kind
    label = "emotions" if kind == "emotion" else "smells" if kind == "smell" else "tags"
    cancel_event = PIPELINE_CANCEL_EVENTS.setdefault(book_id, threading.Event())
    try:
        try:
            chapters = json.loads(extracted_chapters_path(book).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pipeline.update({"status": "failed", "message": f"Prepare the manuscript before starting chapter {label}.", "updatedAt": utc_now()})
            write_pipeline(book, pipeline)
            return
        model = EMOTION_MODEL_ID if kind == "emotion" else ""
        if kind in {"tag", "smell"}:
            settings = load_settings()
            available = ollama_status()
            models = available["models"] if available["running"] else []
            preferred = str(pipeline.get("tagModel") or settings.get("tagsModel") or pipeline.get("readerModel") or settings.get("readerModel", ""))
            model = preferred if preferred in models else choose_primary_model(models)
            if not model:
                detail = "Assign or install a local tag model."
                stages[stage_id].update({"status": "blocked", "detail": detail, "setupRequired": True})
                pipeline.update({"status": "blocked", "phase": f"{label}-blocked", "message": detail, "updatedAt": utc_now()})
                write_pipeline(book, pipeline)
                return
        pipeline.update({"status": "running", "phase": label, "stopRequested": False, "message": f"Starting chapter {label} with {model}.", "workerPid": os.getpid(), "updatedAt": utc_now()})
        pipeline.pop("error", None)
        stages[stage_id].update({"status": "running", "startedAt": stages[stage_id].get("startedAt") or utc_now(), "model": model, "detail": f"Analyzing chapter {label} with {model}."})
        stages[stage_id].pop("setupRequired", None)
        write_pipeline(book, pipeline)
        eligible: list[tuple[int, dict[str, object], dict[str, object]]] = []
        for index, source in enumerate(chapters):
            visible = pipeline["chapters"][index]
            if is_front_matter(visible):
                visible[f"{prefix}Status"] = "excluded"
                visible[kind] = {
                    "analysisMode": "front-matter-not-applicable",
                    "reason": "Narrative analysis does not produce trustworthy scores from tables of contents or other paratext.",
                }
                visible.pop(f"{prefix}Error", None)
                continue
            eligible.append((index, source, visible))
        write_pipeline(book, pipeline)
        for position, (index, source, visible) in enumerate(eligible, start=1):
            sequence = int(visible.get("sequence") or visible.get("number") or index + 1)
            if chapter_sequence is not None and sequence != chapter_sequence:
                continue
            if visible.get(f"{prefix}Status") == "complete":
                continue
            if cancel_event.is_set():
                stages[stage_id].update({"status": "paused", "detail": f"Chapter {label} paused safely."})
                pipeline.update({"status": "paused", "phase": f"{label}-paused", "message": f"Chapter {label} paused. Completed results are saved.", "updatedAt": utc_now()})
                write_pipeline(book, pipeline)
                return
            started = time.monotonic()
            visible.update({f"{prefix}Status": "running", f"{prefix}Model": model, f"{prefix}StartedAt": utc_now(), f"{prefix}InputCharacters": len(str(source.get("text") or ""))})
            for stale_key in (f"{prefix}Error", f"{prefix}CompletedAt", f"{prefix}DurationSeconds"):
                visible.pop(stale_key, None)
            pipeline.update({"message": f"Analyzing {label} for {visible.get('title')} · chapter {position} of {len(eligible)}.", "updatedAt": utc_now()})
            write_pipeline(book, pipeline)
            prior_smell_dispositions = {
                str(item.get("id")): str(item.get("userStatus"))
                for item in visible.get("smell", {}).get("candidates", [])
                if isinstance(item, dict) and item.get("id") and item.get("userStatus")
            } if kind == "smell" and isinstance(visible.get("smell"), dict) else {}
            if kind == "smell" and isinstance(visible.get("smellDispositions"), dict):
                prior_smell_dispositions.update({
                    str(candidate_id): str(record.get("status"))
                    for candidate_id, record in visible["smellDispositions"].items()
                    if isinstance(record, dict) and record.get("status")
                })
            try:
                def restore_smell_dispositions(smell_artifact: dict[str, object]) -> dict[str, object]:
                    for candidate in smell_artifact.get("candidates", []):
                        if isinstance(candidate, dict) and str(candidate.get("id")) in prior_smell_dispositions:
                            candidate["userStatus"] = prior_smell_dispositions[str(candidate.get("id"))]
                    return smell_artifact

                def save_smell_batch(partial_artifact: dict[str, object]) -> None:
                    restore_smell_dispositions(partial_artifact)
                    visible["smell"] = partial_artifact
                    progress = partial_artifact.get("reviewProgress") if isinstance(partial_artifact.get("reviewProgress"), dict) else {}
                    pipeline.update({
                        "message": f"Reviewing Smells for {visible.get('title')} · batch {progress.get('completedBatches', 0)} of {progress.get('totalBatches', 0)} saved.",
                        "updatedAt": utc_now(),
                    })
                    write_pipeline(book, pipeline)

                artifact = analyze_chapter_emotions(source, cancel_event) if kind == "emotion" else analyze_chapter_smells(source, model, cancel_event, book_id, save_smell_batch) if kind == "smell" else analyze_chapter_tags_resilient(source, model, cancel_event, book_id)
                if kind == "smell":
                    restore_smell_dispositions(artifact)
                partial_smells = kind == "smell" and bool(artifact.get("reviewErrors"))
                visible.update({kind: artifact, f"{prefix}Status": "failed" if partial_smells else "complete", f"{prefix}CompletedAt": utc_now(), f"{prefix}DurationSeconds": round(time.monotonic() - started, 1)})
                if partial_smells:
                    progress = artifact.get("reviewProgress") if isinstance(artifact.get("reviewProgress"), dict) else {}
                    failed_batches = len(artifact.get("reviewErrors", []))
                    total_batches = int(progress.get("totalBatches") or 0)
                    visible[f"{prefix}Error"] = f"Incomplete Smells review: the editor model failed {failed_batches} of {total_batches} batches. Local evidence and usable judgments were preserved."
                if kind == "tag":
                    visible.pop("tagFailurePromptVersion", None)
                    visible.pop("tagMigrationNote", None)
            except PipelineCancelled:
                visible[f"{prefix}Status"] = "pending"
                stages[stage_id].update({"status": "paused", "detail": f"Stopped safely; Resume retries the interrupted chapter {label}."})
                pipeline.update({"status": "paused", "phase": f"{label}-paused", "message": f"Chapter {label} stopped. Completed results are saved.", "updatedAt": utc_now()})
                write_pipeline(book, pipeline)
                return
            except RuntimeError as error:
                if kind == "emotion" and ("not installed" in str(error).lower()):
                    visible[f"{prefix}Status"] = "pending"
                    stages[stage_id].update({"status": "blocked", "detail": str(error), "setupRequired": True})
                    pipeline.update({"status": "running" if chapter_sequence is not None else "ready", "phase": "chapter-complete", "message": "Emotion scoring is waiting for its local model; continuing with other available passes.", "updatedAt": utc_now()})
                    write_pipeline(book, pipeline)
                    return
                visible.update({f"{prefix}Status": "failed", f"{prefix}CompletedAt": utc_now(), f"{prefix}DurationSeconds": round(time.monotonic() - started, 1), f"{prefix}Error": str(error)[:500]})
            except Exception as error:
                visible.update({f"{prefix}Status": "failed", f"{prefix}CompletedAt": utc_now(), f"{prefix}DurationSeconds": round(time.monotonic() - started, 1), f"{prefix}Error": str(error)[:500]})
                if kind == "tag":
                    visible["tagFailurePromptVersion"] = TAG_PROMPT_VERSION
            write_pipeline(book, pipeline)
        eligible_visible = [visible for _, _, visible in eligible]
        completed = sum(1 for chapter in eligible_visible if chapter.get(f"{prefix}Status") == "complete")
        failed = sum(1 for chapter in eligible_visible if chapter.get(f"{prefix}Status") == "failed")
        remaining = len(eligible_visible) - completed - failed
        stages[stage_id].update({"status": "pending" if remaining else "warning" if failed else "complete", "detail": f"Completed {completed} of {len(eligible_visible)} manuscript chapter {label}; front matter excluded."})
        if not remaining:
            stages[stage_id]["completedAt"] = utc_now()
        pipeline.update({"status": "running" if chapter_sequence is not None and remaining else "complete" if not failed and not remaining else "warning", "phase": "chapter-complete" if chapter_sequence is not None and remaining else "complete", "message": f"Chapter {label} saved; continuing through this book." if chapter_sequence is not None and remaining else f"Chapter {label} pass complete.", "updatedAt": utc_now()})
        write_pipeline(book, pipeline)
    finally:
        PIPELINE_THREADS.pop(book_id, None)
        PIPELINE_CANCEL_EVENTS.pop(book_id, None)


def ordered_chapter_sequences(pipeline: dict[str, object]) -> list[int]:
    sequences: list[int] = []
    seen: set[int] = set()
    for index, chapter in enumerate(pipeline.get("chapters", []), start=1):
        try:
            sequence = int(chapter.get("sequence") or chapter.get("number") or index)
        except (TypeError, ValueError):
            sequence = index
        if sequence not in seen:
            sequences.append(sequence)
            seen.add(sequence)
    return sequences


def run_ready_stage_rollups(book_id: str) -> None:
    """Finish newly eligible stage rollups before continuing independent work."""
    while not QUEUE_CANCEL_EVENT.is_set():
        book = find_book(book_id)
        if not book:
            return
        action = stage_rollup_action(load_pipeline(book))
        if action == "whole-summary":
            PIPELINE_CANCEL_EVENTS[book_id] = QUEUE_CANCEL_EVENT
            PIPELINE_THREADS[book_id] = threading.current_thread()
            run_whole_book_summary_pipeline(book_id)
            continue
        if action == "whole-dossier":
            PIPELINE_CANCEL_EVENTS[book_id] = QUEUE_CANCEL_EVENT
            PIPELINE_THREADS[book_id] = threading.current_thread()
            run_whole_book_dossier_pipeline(book_id)
            continue
        return


def run_book_chapter_pipeline(book_id: str, *, summaries: bool = True, emotions: bool = True, tags: bool = True, smells: bool = True, dossiers: bool = True) -> None:
    """Finish one book chapter-by-chapter, respecting per-stage dependencies."""
    book = find_book(book_id)
    if not book:
        return
    enabled_stages = {
        stage_id for stage_id, enabled in (("summaries", summaries), ("emotions", emotions), ("tags", tags), ("smells", smells), ("dossiers", dossiers)) if enabled
    }
    run_ready_stage_rollups(book_id)
    for sequence in ordered_chapter_sequences(load_pipeline(book)):
        for stage_id in CHAPTER_PIPELINE_STAGE_ORDER:
            if QUEUE_CANCEL_EVENT.is_set():
                return
            if stage_id not in enabled_stages:
                continue
            pipeline = load_pipeline(book)
            stage = next((item for item in pipeline.get("stages", []) if item.get("id") == stage_id), {})
            if not stage and stage_id == "smells":
                continue
            if stage.get("disabled"):
                continue
            if stage.get("status") == "blocked" and stage.get("setupRequired"):
                continue
            PIPELINE_CANCEL_EVENTS[book_id] = QUEUE_CANCEL_EVENT
            PIPELINE_THREADS[book_id] = threading.current_thread()
            if stage_id == "summaries":
                chapter = next((item for item in pipeline.get("chapters", []) if int(item.get("sequence") or item.get("number") or 0) == sequence), None)
                if chapter and chapter.get("status") in {None, "pending", "ready", "paused", "running"}:
                    run_summary_pipeline(book_id, chapter_sequence=sequence)
            elif stage_id == "dossiers":
                chapter_chunks = [chunk for chunk in pipeline.get("chunks", []) if int(chunk.get("chapterSequence") or 0) == sequence]
                if any(chunk.get("dossierStatus") in {None, "pending", "ready", "paused", "running"} for chunk in chapter_chunks):
                    run_dossier_pipeline(book_id, chapter_sequence=sequence)
            elif stage_id in {"emotions", "tags", "smells"}:
                prefix = "emotion" if stage_id == "emotions" else "tag" if stage_id == "tags" else "smell"
                chapter = next((item for item in pipeline.get("chapters", []) if int(item.get("sequence") or item.get("number") or 0) == sequence), None)
                if chapter and chapter.get(f"{prefix}Status") in {None, "pending", "ready", "paused", "running"}:
                    run_chapter_signal_pipeline(book_id, prefix, chapter_sequence=sequence)
            run_ready_stage_rollups(book_id)
        # A user may refresh or prioritize a result while this worker is in a
        # long chapter pass. Finish the active chapter, then yield to the outer
        # queue so that explicit request runs next instead of waiting behind the
        # rest of the book.
        with QUEUE_LOCK:
            if book_id in QUEUE_ACTIONS:
                return
    run_ready_stage_rollups(book_id)


def run_library_queue() -> None:
    global QUEUE_THREAD, QUEUE_CURRENT_TASK
    processed: set[str] = set()
    try:
        while True:
            if QUEUE_CANCEL_EVENT.is_set():
                break
            queued = load_queue()
            with QUEUE_LOCK:
                requested = next((candidate for candidate in queued if candidate in QUEUE_ACTIONS), None)
            book_id = requested or next((candidate for candidate in queued if candidate not in processed), None)
            if not book_id:
                break
            processed.add(book_id)
            book = find_book(book_id)
            if not book:
                continue
            pipeline = load_pipeline(book)
            with QUEUE_LOCK:
                action = QUEUE_ACTIONS.pop(book_id, "")
                QUEUE_CURRENT_TASK = {"bookId": book_id, "book": str(book.get("title") or "this book"), "action": action or "chapter-pipeline", "task": "Next chapter-step" if not action or action == "chapter-pipeline" else str(action).replace("-", " ").title()}
            if action == "deferred-refresh":
                with QUEUE_LOCK:
                    persisted_refreshes = load_deferred_analysis_refreshes()
                    requests = DEFERRED_ANALYSIS_REFRESHES.pop(book_id, []) or persisted_refreshes.pop(book_id, [])
                    save_deferred_analysis_refreshes(persisted_refreshes)
                for kind, sequence in requests:
                    refresh_analysis_result(book, load_pipeline(book), kind, sequence)
                complete_queue_action(book_id, action)
                with QUEUE_LOCK:
                    QUEUE_ACTIONS[book_id] = "chapter-pipeline"
                continue
            if action == "deferred-retry-failed":
                deferred_pipeline = load_pipeline(book)
                retry_failed_analysis(book, deferred_pipeline)
                write_pipeline(book, deferred_pipeline)
                with QUEUE_LOCK:
                    QUEUE_ACTIONS[book_id] = "chapter-pipeline"
                continue
            if action == "chapter-pipeline":
                run_book_chapter_pipeline(book_id)
                complete_queue_action(book_id, action)
                continue
            if action == "restart":
                pipeline = reset_summary_run(book, pipeline)
                run_book_chapter_pipeline(book_id, summaries=True, dossiers=pipeline_is_enabled())
                complete_queue_action(book_id, action)
                continue
            if action == "prepare":
                PIPELINE_CANCEL_EVENTS[book_id] = QUEUE_CANCEL_EVENT
                PIPELINE_THREADS[book_id] = threading.current_thread()
                prepare_manuscript_pipeline(book_id)
                prepared = load_pipeline(book)
                continue_analysis = bool(prepared.pop("continueAnalysisAfterPrepare", False) or pipeline_is_enabled())
                if continue_analysis:
                    write_pipeline(book, prepared)
                if continue_analysis and not QUEUE_CANCEL_EVENT.is_set() and prepared.get("chapters"):
                    run_book_chapter_pipeline(book_id)
                complete_queue_action(book_id, action)
                continue
            if action == "summarize":
                run_book_chapter_pipeline(book_id, summaries=True, dossiers=pipeline_is_enabled())
                complete_queue_action(book_id, action)
                continue
            if action == "whole-summary":
                PIPELINE_CANCEL_EVENTS[book_id] = QUEUE_CANCEL_EVENT
                PIPELINE_THREADS[book_id] = threading.current_thread()
                run_whole_book_summary_pipeline(book_id)
                run_ready_stage_rollups(book_id)
                complete_queue_action(book_id, action)
                continue
            if action == "whole-dossier":
                PIPELINE_CANCEL_EVENTS[book_id] = QUEUE_CANCEL_EVENT
                PIPELINE_THREADS[book_id] = threading.current_thread()
                run_whole_book_dossier_pipeline(book_id)
                complete_queue_action(book_id, action)
                continue
            if action == "questions":
                PIPELINE_CANCEL_EVENTS[book_id] = QUEUE_CANCEL_EVENT
                PIPELINE_THREADS[book_id] = threading.current_thread()
                run_question_tracker_pipeline(book_id)
                complete_queue_action(book_id, action)
                continue
            if action == "dossiers":
                run_book_chapter_pipeline(book_id, summaries=False, emotions=False, tags=False, smells=False, dossiers=True)
                complete_queue_action(book_id, action)
                continue
            if action == "dossier-restart":
                pipeline = reset_dossier_run(book, pipeline)
                PIPELINE_CANCEL_EVENTS[book_id] = QUEUE_CANCEL_EVENT
                PIPELINE_THREADS[book_id] = threading.current_thread()
                run_dossier_pipeline(book_id)
                complete_queue_action(book_id, action)
                continue
            if action in {"emotions", "emotion-restart", "tags", "tag-restart", "smells", "smell-restart"}:
                kind = "emotion" if action.startswith("emotion") else "tag" if action.startswith("tag") else "smell"
                if action.endswith("restart"):
                    pipeline = reset_chapter_signal_run(book, pipeline, kind)
                run_book_chapter_pipeline(book_id, summaries=False, emotions=kind == "emotion", tags=kind == "tag", smells=kind == "smell", dossiers=False)
                complete_queue_action(book_id, action)
                continue
            automatic_action = next_pipeline_action(book, pipeline)
            with QUEUE_LOCK:
                QUEUE_CURRENT_TASK.update({"action": automatic_action or "chapter-pipeline", "task": {"prepare": "Manuscript map", "summarize": "Chapter summary", "dossiers": "Chapter dossier", "emotions": "Emotion scoring", "tags": "Chapter tags", "smells": "Prose smells", "whole-summary": "Whole-book summary", "whole-dossier": "Whole-book dossier"}.get(automatic_action, "Next chapter-step")})
            if automatic_action == "prepare":
                PIPELINE_CANCEL_EVENTS[book_id] = QUEUE_CANCEL_EVENT
                PIPELINE_THREADS[book_id] = threading.current_thread()
                prepare_manuscript_pipeline(book_id)
                prepared = load_pipeline(book)
                if pipeline_is_enabled() and not QUEUE_CANCEL_EVENT.is_set() and prepared.get("chapters"):
                    run_book_chapter_pipeline(book_id)
                continue
            if automatic_action in {"summarize", "dossiers", "emotions", "tags", "smells"}:
                # Automatic work is chapter-first, not stage-first. Once the
                # structural inputs exist, run every eligible pass for one
                # chapter before advancing to the next chapter. Explicit UI
                # redo actions above remain deliberately stage-scoped.
                run_book_chapter_pipeline(book_id)
            elif automatic_action == "whole-summary":
                PIPELINE_CANCEL_EVENTS[book_id] = QUEUE_CANCEL_EVENT
                PIPELINE_THREADS[book_id] = threading.current_thread()
                run_whole_book_summary_pipeline(book_id)
            elif automatic_action == "whole-dossier":
                PIPELINE_CANCEL_EVENTS[book_id] = QUEUE_CANCEL_EVENT
                PIPELINE_THREADS[book_id] = threading.current_thread()
                run_whole_book_dossier_pipeline(book_id)
    finally:
        # A Continue request can arrive after this worker has chosen to exit but
        # before Thread.is_alive() turns false. Preserve that request and hand it
        # to a replacement worker instead of leaving the UI stuck at Starting.
        with QUEUE_LOCK:
            QUEUE_CURRENT_TASK = {}
            QUEUE_THREAD = None
            QUEUE_CANCEL_EVENT.clear()
            if QUEUE_ACTIONS:
                QUEUE_THREAD = threading.Thread(target=run_library_queue, daemon=True, name="bookinator-library-queue")
                QUEUE_THREAD.start()


def start_global_pipeline() -> list[tuple[str, str]]:
    """Enable the workspace worker and fill it from all eligible books."""
    global QUEUE_THREAD
    set_pipeline_enabled(True)
    automatic = automatic_queue_books()
    ordered_ids = [book_id for book_id, _ in automatic]
    save_queue(ordered_ids)
    # Loading a book enriches it for the client and briefly consults
    # QUEUE_ACTIONS. Do all disk inspection before taking QUEUE_LOCK; otherwise
    # startup deadlocks itself on this ordinary, non-reentrant lock and
    # /api/books waits forever behind it.
    queued_actions: dict[str, str] = {}
    durable_actions = load_queue_actions()
    for book_id, _action in automatic:
        book = find_book(book_id)
        pipeline = load_pipeline(book) if book else {}
        queued_action = durable_actions.get(book_id, "")
        if not queued_action and pipeline.get("status") == "queued":
            queued_action = str(pipeline.get("queuedAction") or "")
        queued_actions[book_id] = queued_action if queued_action in EXPLICIT_QUEUE_ACTIONS else "chapter-pipeline"
    with QUEUE_LOCK:
        for book_id, _action in automatic:
            # The returned action describes the first unfinished work for UI
            # status. The worker receives the broader chapter-first contract,
            # so resuming at Dossiers cannot accidentally drain that entire
            # stage before Tags and Emotions get a turn. A durable explicit
            # request such as Refresh dossier remains stage-scoped across a
            # server restart, however.
            QUEUE_ACTIONS[book_id] = queued_actions[book_id]
        if automatic and (not QUEUE_THREAD or not QUEUE_THREAD.is_alive()):
            QUEUE_CANCEL_EVENT.clear()
            QUEUE_THREAD = threading.Thread(target=run_library_queue, daemon=True, name="bookinator-library-queue")
            QUEUE_THREAD.start()
    return automatic


def prioritize_pipeline_action(book_id: str, action: str) -> dict[str, object]:
    """Durably put one book first and ensure the single local worker is awake."""
    global QUEUE_THREAD
    book = find_book(book_id)
    if not book or action not in EXPLICIT_QUEUE_ACTIONS:
        raise ValueError("Choose a valid book and pipeline action.")
    pipeline = load_pipeline(book)
    if action == "prepare":
        pipeline["continueAnalysisAfterPrepare"] = True
    set_pipeline_enabled(True)
    save_queue([book_id, *[queued_id for queued_id in load_queue() if queued_id != book_id]])
    if pipeline.get("status") != "running":
        pipeline.update({
            "status": "queued", "phase": "queued", "queuedAction": action,
            "message": "First in line. Waiting for the local pipeline worker to start…",
            "stopRequested": False, "updatedAt": utc_now(),
        })
        pipeline.pop("error", None)
        write_pipeline(book, pipeline)
    with QUEUE_LOCK:
        persist_queue_action(book_id, action)
        QUEUE_ACTIONS[book_id] = action
        if not QUEUE_THREAD or not QUEUE_THREAD.is_alive():
            QUEUE_CANCEL_EVENT.clear()
            QUEUE_THREAD = threading.Thread(target=run_library_queue, daemon=True, name="bookinator-library-queue")
            QUEUE_THREAD.start()
    return pipeline


def run_summary_pipeline(book_id: str, chapter_sequence: int | None = None) -> None:
    book = find_book(book_id)
    if not book:
        return
    pipeline = load_pipeline(book)
    stages = {stage["id"]: stage for stage in pipeline.get("stages", [])}
    cancel_event = PIPELINE_CANCEL_EVENTS.setdefault(book_id, threading.Event())
    try:
        try:
            chapters = json.loads(extracted_chapters_path(book).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pipeline.update({"status": "failed", "message": "Prepare the manuscript before starting summaries.", "updatedAt": utc_now()})
            write_pipeline(book, pipeline)
            return
        settings = load_settings()
        ollama = ollama_status()
        models = ollama["models"] if ollama["running"] else []
        preferred = str(pipeline.get("readerModel") or settings.get("readerModel", ""))
        model = preferred if preferred in models else choose_primary_model(models)
        pipeline.update({"status": "running", "phase": "summarizing", "stopRequested": False, "message": f"Waking {model or 'the chapter reader'} for the next unfinished chapter.", "workerPid": os.getpid(), "summaryStartedAt": pipeline.get("summaryStartedAt") or utc_now(), "runId": pipeline.get("runId") or str(uuid.uuid4()), "updatedAt": utc_now()})
        pipeline.pop("error", None)
        stages["summaries"].update({"status": "running" if model else "blocked", "startedAt": utc_now(), "model": model, "detail": f"Reading with {model}." if model else "Assign or install a local reader model, then run again."})
        write_pipeline(book, pipeline)
        if not model:
            pipeline.update({"status": "blocked", "message": "Page extraction is complete, but chapter summaries need a local reader model.", "updatedAt": utc_now()})
            write_pipeline(book, pipeline)
            return
        for index, chapter in enumerate(chapters):
            visible = pipeline["chapters"][index]
            if chapter_sequence is not None and int(visible.get("sequence") or visible.get("number") or index + 1) != chapter_sequence:
                continue
            if visible.get("status") == "complete":
                continue
            if cancel_event.is_set():
                completed = sum(1 for item in pipeline["chapters"] if item.get("status") == "complete")
                stages["summaries"].update({"status": "paused", "detail": f"Paused after {completed} of {len(chapters)} chapter summaries. Resume continues with the next unfinished chapter."})
                pipeline.update({"status": "paused", "phase": "paused", "stopRequested": False, "message": "Reading paused safely. Completed summaries are saved.", "updatedAt": utc_now()})
                write_pipeline(book, pipeline)
                return
            chapter_started = time.monotonic()
            visible.update({
                "status": "running", "runId": pipeline.get("runId"), "model": model,
                "startedAt": utc_now(), "inputCharacters": len(str(chapter.get("text") or "")),
                "chapterMapStatus": "approved" if pipeline.get("chapterMapApproved") else "provisional",
            })
            visible.pop("error", None)
            pipeline["message"] = f"Reading {chapter['title']} · section {index + 1} of {len(chapters)}."
            pipeline["updatedAt"] = utc_now()
            write_pipeline(book, pipeline)

            def record_retry(attempt: int, failure: dict[str, object]) -> None:
                visible["retrying"] = failure
                pipeline["message"] = f"{model} briefly disconnected during {visible.get('title', 'this chapter')}; retrying automatically ({attempt + 1} of 3)."
                pipeline["updatedAt"] = utc_now()
                write_pipeline(book, pipeline)

            try:
                summary, recovered_failures = summarize_chapter_resilient(chapter, model, cancel_event, book_id, on_retry=record_retry)
                visible.update(summary)
                if recovered_failures:
                    visible.setdefault("retryRuns", []).extend(recovered_failures)
                visible.pop("retrying", None)
                visible.pop("error", None)
                visible.update({"status": "complete", "completedAt": utc_now(), "durationSeconds": round(time.monotonic() - chapter_started, 1)})
            except PipelineCancelled:
                visible.update({"status": "pending", "interruptedAt": utc_now()})
                for key in ("completedAt", "durationSeconds", "error"):
                    visible.pop(key, None)
                completed = sum(1 for item in pipeline["chapters"] if item.get("status") == "complete")
                stages["summaries"].update({"status": "paused", "detail": f"Paused with {completed} completed chapter summaries. Resume retries {visible.get('title', 'the interrupted chapter')}."})
                pipeline.update({"status": "paused", "phase": "paused", "stopRequested": False, "message": "Reading stopped. Completed summaries are saved; the interrupted chapter will restart on Resume.", "updatedAt": utc_now()})
                write_pipeline(book, pipeline)
                return
            except ModelTransportExhausted as error:
                finished_at = utc_now()
                duration = round(time.monotonic() - chapter_started, 1)
                visible.setdefault("failedRuns", []).extend(error.failures)
                visible.pop("retrying", None)
                visible.update({"status": "failed", "completedAt": finished_at, "durationSeconds": duration, "error": str(error), "latestFailure": error.failures[-1]})
            except ChapterSummaryError as error:
                finished_at = utc_now()
                duration = round(time.monotonic() - chapter_started, 1)
                failure = {
                    "model": model,
                    "startedAt": visible.get("startedAt"),
                    "completedAt": finished_at,
                    "durationSeconds": duration,
                    "inputCharacters": visible.get("inputCharacters", 0),
                    "error": str(error)[:500],
                    "responseKeys": error.response_keys,
                    "rawResponse": error.raw_response[:20_000],
                }
                visible.setdefault("failedRuns", []).append(failure)
                visible.update({"status": "failed", "completedAt": finished_at, "durationSeconds": duration, "error": failure["error"], "latestFailure": failure})
            except Exception as error:
                finished_at = utc_now()
                duration = round(time.monotonic() - chapter_started, 1)
                failure = {"model": model, "startedAt": visible.get("startedAt"), "completedAt": finished_at, "durationSeconds": duration, "inputCharacters": visible.get("inputCharacters", 0), "error": str(error)[:500], "exceptionType": type(error).__name__}
                visible.setdefault("failedRuns", []).append(failure)
                visible.update({"status": "failed", "completedAt": finished_at, "durationSeconds": duration, "error": failure["error"], "latestFailure": failure})
            write_pipeline(book, pipeline)
        completed = sum(1 for chapter in pipeline["chapters"] if chapter.get("status") == "complete")
        failed = sum(1 for chapter in pipeline["chapters"] if chapter.get("status") == "failed")
        remaining = len(chapters) - completed - failed
        stage_status = "pending" if remaining else "warning" if failed else "complete"
        stages["summaries"].update({"status": stage_status, "detail": f"Completed {completed} of {len(chapters)} chapter summaries."})
        if not remaining:
            stages["summaries"]["completedAt"] = utc_now()
        else:
            stages["summaries"].pop("completedAt", None)
        pipeline.update({
            "status": "running" if chapter_sequence is not None and remaining else "complete" if not failed and not remaining else "warning",
            "phase": "chapter-complete" if chapter_sequence is not None and remaining else "complete",
            "message": "Chapter summary saved; continuing through this book." if chapter_sequence is not None and remaining else "The first reading is complete." if not failed else "The reading finished with some chapters needing another try.",
            "updatedAt": utc_now(),
        })
        if not remaining:
            pipeline["completedAt"] = utc_now()
        write_pipeline(book, pipeline)
    except Exception as error:
        pipeline.update({"status": "failed", "message": "The reading pipeline stopped.", "error": str(error)[:800], "updatedAt": utc_now()})
        write_pipeline(book, pipeline)
    finally:
        PIPELINE_THREADS.pop(book_id, None)
        PIPELINE_CANCEL_EVENTS.pop(book_id, None)


def run_whole_book_summary_pipeline(book_id: str) -> None:
    book = find_book(book_id)
    if not book:
        return
    pipeline = load_pipeline(book)
    if not pipeline_stage_ready(pipeline, "whole-book-summary"):
        pipeline["wholeBookSummary"] = {
            **(pipeline.get("wholeBookSummary") if isinstance(pipeline.get("wholeBookSummary"), dict) else {}),
            "status": "blocked",
            "dependsOn": list(PIPELINE_STAGE_DEPENDENCIES["whole-book-summary"]),
            "detail": "Waiting for every chapter summary to be current.",
        }
        write_pipeline(book, pipeline)
        return
    cancel_event = PIPELINE_CANCEL_EVENTS.setdefault(book_id, threading.Event())
    model = str(next((stage.get("model") for stage in pipeline.get("stages", []) if stage.get("id") == "summaries"), "") or pipeline.get("readerModel") or "")
    started_at = utc_now()
    started = time.monotonic()
    dependencies = list(PIPELINE_STAGE_DEPENDENCIES["whole-book-summary"])
    input_signature = stage_rollup_input_signature(pipeline, "summary")
    reset_inactive_whole_book_runs(pipeline, "whole-summary")
    pipeline["wholeBookSummary"] = {"status": "running", "model": model, "startedAt": started_at, "inputSignature": input_signature, "dependsOn": dependencies, "detail": "Synthesizing every current chapter summary."}
    write_pipeline(book, pipeline)
    try:
        if not model or not input_signature:
            raise ValueError("Complete every chapter summary and assign a chapter reader before refreshing this rollup.")
        synthesis = summarize_whole_book(pipeline, model, cancel_event, book_id)
        pipeline["wholeBookSummary"] = {**synthesis, "status": "complete", "model": model, "startedAt": started_at, "completedAt": utc_now(), "durationSeconds": round(time.monotonic() - started, 1), "inputSignature": input_signature, "dependsOn": dependencies, "detail": "Synthesized from every current chapter summary."}
    except Exception as error:
        pipeline["wholeBookSummary"] = {"status": "failed", "model": model, "startedAt": started_at, "completedAt": utc_now(), "durationSeconds": round(time.monotonic() - started, 1), "inputSignature": input_signature, "error": str(error)[:500], "dependsOn": dependencies, "detail": "Summary synthesis failed; chapter summaries remain safe."}
    finally:
        pipeline["updatedAt"] = utc_now()
        write_pipeline(book, pipeline)
        PIPELINE_THREADS.pop(book_id, None)
        PIPELINE_CANCEL_EVENTS.pop(book_id, None)


def run_whole_book_dossier_pipeline(book_id: str) -> None:
    book = find_book(book_id)
    if not book:
        return
    pipeline = add_pipeline_progress(load_pipeline(book))
    dependencies = list(PIPELINE_STAGE_DEPENDENCIES["whole-book-dossier"])
    if not pipeline_stage_ready(pipeline, "whole-book-dossier"):
        pipeline["wholeBookDossier"] = {
            **(pipeline.get("wholeBookDossier") if isinstance(pipeline.get("wholeBookDossier"), dict) else {}),
            "status": "blocked", "dependsOn": dependencies, "detail": "Waiting for every chunk dossier to finish.",
        }
        write_pipeline(book, pipeline)
        return
    cancel_event = PIPELINE_CANCEL_EVENTS.setdefault(book_id, threading.Event())
    model = str(next((stage.get("model") for stage in pipeline.get("stages", []) if stage.get("id") == "dossiers"), "") or pipeline.get("dossierModel") or load_settings().get("primaryModel") or "")
    started_at = utc_now()
    started = time.monotonic()
    input_signature = stage_rollup_input_signature(pipeline, "dossier")
    reset_inactive_whole_book_runs(pipeline, "whole-dossier")
    pipeline["wholeBookDossier"] = {"status": "running", "model": model, "startedAt": started_at, "inputSignature": input_signature, "dependsOn": dependencies, "detail": "Reconciling every current chunk dossier into one whole-book memory."}
    pipeline.update({"status": "running", "phase": "whole-dossier", "message": "Reconciling the whole-book dossier…", "updatedAt": utc_now()})
    pipeline.pop("error", None)
    write_pipeline(book, pipeline)
    try:
        if not model or not input_signature:
            raise ValueError("Complete every chunk dossier and assign a dossier model before building the whole-book Dossier.")
        result = reconcile_whole_book_dossier(pipeline, model, cancel_event, book_id)
        pipeline["wholeBookDossier"] = {**result, "status": "complete", "model": model, "startedAt": started_at, "completedAt": utc_now(), "durationSeconds": round(time.monotonic() - started, 1), "inputSignature": input_signature, "dependsOn": dependencies, "detail": "Reconciled from every current chunk dossier."}
        pipeline.update({"status": "complete", "phase": "complete", "message": "The whole-book Dossier is ready.", "updatedAt": utc_now()})
    except PipelineCancelled:
        pipeline["wholeBookDossier"] = {"status": "ready", "model": model, "inputSignature": input_signature, "dependsOn": dependencies, "detail": "Stopped before whole-book reconciliation finished."}
        pipeline.update({"status": "ready", "phase": "ready", "message": "The whole-book Dossier is ready to build.", "updatedAt": utc_now()})
    except Exception as error:
        pipeline["wholeBookDossier"] = {"status": "failed", "model": model, "startedAt": started_at, "completedAt": utc_now(), "durationSeconds": round(time.monotonic() - started, 1), "inputSignature": input_signature, "error": str(error)[:500], "dependsOn": dependencies, "detail": "Whole-book dossier reconciliation failed; chunk dossiers remain safe."}
        pipeline.update({"status": "warning", "phase": "complete", "message": "The whole-book Dossier needs another try.", "updatedAt": utc_now()})
    finally:
        write_pipeline(book, pipeline)
        PIPELINE_THREADS.pop(book_id, None)
        PIPELINE_CANCEL_EVENTS.pop(book_id, None)


def run_question_tracker_pipeline(book_id: str) -> None:
    book = find_book(book_id)
    if not book:
        return
    pipeline = load_pipeline(book)
    dependencies = list(PIPELINE_STAGE_DEPENDENCIES["question-tracker"])
    if not pipeline_stage_ready(pipeline, "question-tracker"):
        pipeline["questionTracker"] = {
            **(pipeline.get("questionTracker") if isinstance(pipeline.get("questionTracker"), dict) else {}),
            "status": "blocked",
            "dependsOn": dependencies,
            "detail": "Waiting for every chapter summary and dossier to finish.",
        }
        write_pipeline(book, pipeline)
        return
    cancel_event = PIPELINE_CANCEL_EVENTS.setdefault(book_id, threading.Event())
    model = str(next((stage.get("model") for stage in pipeline.get("stages", []) if stage.get("id") == "summaries"), "") or pipeline.get("readerModel") or "")
    started_at = utc_now()
    started = time.monotonic()
    input_signature = question_tracker_input_signature(pipeline)
    reset_inactive_whole_book_runs(pipeline, "questions")
    pipeline["questionTracker"] = {"status": "running", "model": model, "startedAt": started_at, "inputSignature": input_signature, "dependsOn": dependencies, "detail": "Matching repeated questions to supported later payoffs."}
    pipeline.update({"status": "running", "phase": "questions", "message": "Matching questions to payoffs…", "updatedAt": utc_now()})
    pipeline.pop("error", None)
    write_pipeline(book, pipeline)
    try:
        if not model or not input_signature:
            raise ValueError("Complete every chapter summary and dossier before building the questions tracker.")
        result = reconcile_questions_and_payoffs(pipeline, model, cancel_event, book_id)
        pipeline["questionTracker"] = {**result, "status": "complete", "model": model, "startedAt": started_at, "completedAt": utc_now(), "durationSeconds": round(time.monotonic() - started, 1), "inputSignature": input_signature, "dependsOn": dependencies, "detail": "Grouped from chapter digests and dossier questions; resolutions are digest-supported."}
        pipeline.update({"status": "complete", "phase": "complete", "message": "Questions and payoffs are ready.", "updatedAt": utc_now()})
    except PipelineCancelled:
        pipeline["questionTracker"] = {"status": "ready", "model": model, "inputSignature": input_signature, "dependsOn": dependencies, "detail": "Stopped before reconciliation finished."}
        pipeline.update({"status": "ready", "phase": "ready", "message": "Questions and payoffs are ready to build.", "updatedAt": utc_now()})
    except Exception as error:
        pipeline["questionTracker"] = {"status": "failed", "model": model, "startedAt": started_at, "completedAt": utc_now(), "durationSeconds": round(time.monotonic() - started, 1), "inputSignature": input_signature, "error": str(error)[:500], "dependsOn": dependencies, "detail": "Question reconciliation failed; summaries and dossiers remain safe."}
        pipeline.update({"status": "warning", "phase": "complete", "message": "Questions and payoffs need another try.", "updatedAt": utc_now()})
    finally:
        if pipeline.get("questionTracker", {}).get("status") != "failed":
            pipeline.pop("error", None)
        write_pipeline(book, pipeline)
        PIPELINE_THREADS.pop(book_id, None)
        PIPELINE_CANCEL_EVENTS.pop(book_id, None)


def analyze_chunk_dossier(chunk: dict[str, object], model: str, cancel_event: threading.Event | None = None, run_key: str = "") -> dict[str, object]:
    front_matter = is_front_matter(chunk, "chapterLabel")
    material_guidance = front_matter_analysis_guidance("dossier") if front_matter else "This is narrative manuscript material; apply the dossier fields normally."
    prompt = f"""Build an evidence-preserving editorial dossier for this manuscript excerpt.
Return JSON with: synopsis (non-empty string), facts, events, entities, locations, current_times, questions, promises, timeline_observations, and evidence (arrays of strings).
Entities should name people, organizations, creatures, significant objects, and concepts. Locations should separately name every physical place or setting present or explicitly discussed. Current_times should describe when the scene itself occurs, including date, season, time of day, elapsed-story time, or relation to earlier events when stated or strongly supported.
Timeline_observations should capture temporal evidence that connects this excerpt to events elsewhere: event order, elapsed durations, deadlines, flashbacks, remembered events, simultaneity, contradictions, and uncertainty. Keep these distinct from current_times, which describe the excerpt's present scene.
Promises must include both explicit commitments made by characters and narrative promises made by the story to its reader: planted questions, withheld identities, foreshadowed disclosures, setups that imply a later payoff, and mysteries the narration invites the reader to expect will be resolved. Begin each promise with "Character promise:" or "Story promise:" and identify the promiser or implied reader agreement when the excerpt supports it.
Evidence entries should be short exact passages from the excerpt. Do not invent facts or resolve uncertainty.

Material-specific instructions:
{material_guidance}

Chapter: {chunk.get('chapterLabel')}
Chapter title: {chunk.get('chapterTitle') or 'Not stated'}
PDF pages: {chunk.get('pageStart')}-{chunk.get('pageEnd')}

{str(chunk.get('text') or '')[:45_000]}
"""
    array = {"type": "array", "items": {"type": "string"}}
    schema = {"type": "object", "properties": {"synopsis": {"type": "string", "minLength": 1}, "facts": array, "events": array, "entities": array, "locations": array, "current_times": array, "questions": array, "promises": array, "timeline_observations": array, "evidence": array}, "required": ["synopsis", "facts", "events", "entities", "locations", "current_times", "questions", "promises", "timeline_observations", "evidence"]}
    result, _ = run_structured_model(prompt, model, schema, cancel_event, run_key)
    synopsis = str(result.get("synopsis") or "").strip()
    if not synopsis:
        raise ValueError("The model returned a dossier without a synopsis.")
    normalized = {"synopsis": synopsis, **{key: [str(item).strip() for item in result.get(key, []) if str(item).strip()] if isinstance(result.get(key), list) else [] for key in ("facts", "events", "entities", "locations", "current_times", "questions", "promises", "timeline_observations", "evidence")}}
    if front_matter:
        # Suggestive labels are not events, reader contracts, or chronology.
        for field in ("events", "questions", "promises", "current_times", "timeline_observations"):
            normalized[field] = []
        normalized["analysisMode"] = "front-matter-structural"
    return normalized


def analyze_chunk_dossier_resilient(
    chunk: dict[str, object],
    model: str,
    cancel_event: threading.Event | None = None,
    run_key: str = "",
    attempts: int = 2,
    retry_delay: float = 0.75,
) -> dict[str, object]:
    """Retry one malformed or interrupted dossier response and retain why."""
    failures: list[dict[str, object]] = []
    for attempt in range(1, max(1, attempts) + 1):
        try:
            dossier = analyze_chunk_dossier(chunk, model, cancel_event, run_key)
            if failures:
                dossier["retryDiagnostics"] = failures
            return dossier
        except PipelineCancelled:
            raise
        except (json.JSONDecodeError, urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError) as error:
            failure: dict[str, object] = {
                "attempt": attempt,
                "model": model,
                "completedAt": utc_now(),
                "exceptionType": type(error).__name__,
                "inputCharacters": len(str(chunk.get("text") or "")),
            }
            if isinstance(error, json.JSONDecodeError):
                failure.update({"error": f"Malformed dossier JSON: {error.msg}", "line": error.lineno, "column": error.colno})
            else:
                failure["error"] = model_runtime_failure(model, error)
            failures.append(failure)
            if cancel_event and cancel_event.is_set():
                raise PipelineCancelled() from None
            if attempt >= max(1, attempts):
                raise DossierAnalysisExhausted(failures, error) from error
            if cancel_event and cancel_event.wait(retry_delay):
                raise PipelineCancelled() from None
            if not cancel_event:
                time.sleep(retry_delay)
    raise RuntimeError("The dossier model did not return a result.")


def write_chunk_artifact(book: dict[str, object], sequence: int, artifact: dict[str, object]) -> None:
    target = chunk_artifacts_path(book) / f"{sequence:04d}.json"
    temporary = target.with_suffix(".tmp")
    temporary.write_text(json.dumps(artifact, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(target)


def append_dossier_run(record: dict[str, object]) -> dict[str, object]:
    run = {key: record.get(key) for key in ("dossierModel", "dossierStartedAt", "dossierCompletedAt", "dossierDurationSeconds", "dossierStatus", "dossierError", "dossierRetryDiagnostics") if record.get(key) is not None}
    runs = record.get("dossierRuns") if isinstance(record.get("dossierRuns"), list) else []
    runs.append(run)
    record["dossierRuns"] = runs
    return run


def run_dossier_pipeline(book_id: str, chapter_sequence: int | None = None) -> None:
    book = find_book(book_id)
    if not book:
        return
    pipeline = load_pipeline(book)
    stages = {stage["id"]: stage for stage in pipeline.get("stages", [])}
    cancel_event = PIPELINE_CANCEL_EVENTS.setdefault(book_id, threading.Event())
    settings = load_settings()
    ollama = ollama_status()
    models = ollama["models"] if ollama["running"] else []
    preferred = str(pipeline.get("dossierModel") or settings.get("primaryModel", ""))
    model = preferred if preferred in models else choose_primary_model(models)
    chunks = pipeline.get("chunks", [])
    pipeline.update({"status": "running", "phase": "dossiers", "stopRequested": False, "message": f"Waking {model or 'the dossier model'} for the next unfinished source chunk.", "workerPid": os.getpid(), "updatedAt": utc_now()})
    pipeline.pop("error", None)
    dossier_stage = stages.setdefault("dossiers", {"id": "dossiers", "label": "Chunk dossiers"})
    dossier_stage.update({"status": "running" if model else "blocked", "model": model, "startedAt": utc_now(), "detail": f"Building dossiers with {model}." if model else "Assign or install a dossier model."})
    if dossier_stage not in pipeline.get("stages", []):
        pipeline.setdefault("stages", []).append(dossier_stage)
    write_pipeline(book, pipeline)
    try:
        if not model:
            pipeline.update({"status": "blocked", "message": "Dossiers need a local model.", "updatedAt": utc_now()})
            write_pipeline(book, pipeline)
            return
        for index, visible in enumerate(chunks):
            if chapter_sequence is not None and int(visible.get("chapterSequence") or 0) != chapter_sequence:
                continue
            if visible.get("dossierStatus") == "complete":
                continue
            artifact_path = chunk_artifacts_path(book) / f"{int(visible.get('sequence') or index + 1):04d}.json"
            artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
            if cancel_event.is_set():
                pipeline.update({"status": "paused", "phase": "dossiers-paused", "message": "Dossier work paused. Completed dossiers are saved.", "updatedAt": utc_now()})
                dossier_stage.update({"status": "paused"})
                write_pipeline(book, pipeline)
                return
            started = time.monotonic()
            started_at = utc_now()
            if visible.get("dossierStatus") == "failed" and (visible.get("dossierModel") or visible.get("dossierCompletedAt")):
                append_dossier_run(visible)
                append_dossier_run(artifact)
            for stale_key in ("dossierError", "dossierRetryDiagnostics"):
                visible.pop(stale_key, None)
                artifact.pop(stale_key, None)
            visible.update({"dossierStatus": "running", "dossierModel": model, "dossierStartedAt": started_at})
            artifact.update({"dossierStatus": "running", "dossierModel": model, "dossierStartedAt": started_at})
            write_chunk_artifact(book, int(visible.get("sequence") or index + 1), artifact)
            pipeline.update({"message": f"Building dossier {index + 1} of {len(chunks)} · {visible.get('chapterLabel')}, chunk {visible.get('chunkInChapter')}.", "updatedAt": utc_now()})
            write_pipeline(book, pipeline)
            try:
                dossier = analyze_chunk_dossier_resilient(artifact, model, cancel_event, book_id)
                finished = utc_now()
                duration = round(time.monotonic() - started, 1)
                result = {
                    "dossier": dossier, "dossierStatus": "complete", "dossierModel": model,
                    "dossierCompletedAt": finished, "dossierDurationSeconds": duration,
                    "chapterMapStatus": "approved" if pipeline.get("chapterMapApproved") else "provisional",
                }
                visible.update(result)
                artifact.update(result)
                artifact.pop("dossierError", None)
                artifact.pop("dossierRetryDiagnostics", None)
                visible.pop("dossierError", None)
                visible.pop("dossierRetryDiagnostics", None)
            except PipelineCancelled:
                visible.update({"dossierStatus": "pending", "dossierError": "Stopped before completion."})
                artifact.update({"dossierStatus": "pending", "dossierError": "Stopped before completion."})
                write_chunk_artifact(book, int(visible.get("sequence") or index + 1), artifact)
                dossier_stage.update({"status": "paused", "detail": "Stopped safely; Resume retries the interrupted chunk."})
                pipeline.update({"status": "paused", "phase": "dossiers-paused", "message": "Dossier work stopped. Completed dossiers are saved.", "updatedAt": utc_now()})
                write_pipeline(book, pipeline)
                return
            except Exception as error:
                finished = utc_now()
                result = {"dossierStatus": "failed", "dossierModel": model, "dossierCompletedAt": finished, "dossierDurationSeconds": round(time.monotonic() - started, 1), "dossierError": str(error)[:500]}
                retry_diagnostics = getattr(error, "failures", None)
                if isinstance(retry_diagnostics, list):
                    result["dossierRetryDiagnostics"] = retry_diagnostics
                visible.update(result)
                artifact.update(result)
            write_chunk_artifact(book, int(visible.get("sequence") or index + 1), artifact)
            write_pipeline(book, pipeline)
        completed = sum(1 for chunk in chunks if chunk.get("dossierStatus") == "complete")
        failed = sum(1 for chunk in chunks if chunk.get("dossierStatus") == "failed")
        remaining = len(chunks) - completed - failed
        stage_status = "pending" if remaining else "warning" if failed else "complete"
        dossier_stage.update({"status": stage_status, "detail": f"Completed {completed} of {len(chunks)} structured dossiers."})
        if not remaining:
            dossier_stage["completedAt"] = utc_now()
        else:
            dossier_stage.pop("completedAt", None)
        pipeline.update({
            "status": "running" if chapter_sequence is not None and remaining else "complete" if not failed and not remaining else "warning",
            "phase": "chapter-complete" if chapter_sequence is not None and remaining else "dossiers-complete",
            "message": "Chapter dossier saved; continuing through this book." if chapter_sequence is not None and remaining else "Dossier pass complete." if not failed else "Dossier pass finished with retryable chunks.",
            "updatedAt": utc_now(),
        })
        write_pipeline(book, pipeline)
    except Exception as error:
        pipeline.update({"status": "failed", "phase": "dossiers", "message": "The dossier pipeline stopped.", "error": str(error)[:800], "updatedAt": utc_now()})
        write_pipeline(book, pipeline)
    finally:
        PIPELINE_THREADS.pop(book_id, None)
        PIPELINE_CANCEL_EVENTS.pop(book_id, None)


def physical_memory_gib() -> float:
    if platform.system() == "Darwin":
        try:
            result = subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True, text=True, timeout=2, check=True)
            return round(int(result.stdout.strip()) / (1024 ** 3), 1)
        except (OSError, ValueError, subprocess.SubprocessError):
            pass
    try:
        return round(os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / (1024 ** 3), 1)
    except (AttributeError, OSError, ValueError):
        return 0


def machine_readiness(ollama: dict[str, object] | None = None) -> dict[str, object]:
    """Return actionable host checks without confusing unknown with failure."""
    system = platform.system()
    machine = platform.machine()
    memory_gib = physical_memory_gib()
    python_version = platform.python_version()
    python_supported = sys.version_info >= (3, 11)
    pip_available = importlib.util.find_spec("pip") is not None
    uv_available = shutil.which("uv") is not None
    ollama = ollama or ollama_status()
    ollama_version = str(ollama.get("version") or "")
    ollama_installed = bool(ollama.get("installed"))
    ollama_running = bool(ollama.get("running"))
    brew_available = system == "Darwin" and shutil.which("brew") is not None
    brew_version = ""
    if brew_available:
        try:
            brew_version = subprocess.run(["brew", "--version"], capture_output=True, text=True, timeout=5, check=True).stdout.splitlines()[0].strip()
        except (OSError, subprocess.SubprocessError, IndexError):
            brew_available = False
    try:
        disk_root = DATA_ROOT if DATA_ROOT.exists() else DATA_ROOT.parent
        free_disk_gib = round(shutil.disk_usage(disk_root).free / (1024 ** 3), 1)
    except OSError:
        free_disk_gib = 0

    if system == "Darwin":
        try:
            os_major = int((platform.mac_ver()[0] or "0").split(".")[0])
        except ValueError:
            os_major = 0
        platform_supported = machine == "arm64" and os_major >= 14
        platform_detail = f"macOS {platform.mac_ver()[0] or 'version unknown'} on {machine}. Bookinator requires macOS 14 or later on Apple silicon."
        platform_status = "ready" if platform_supported else "blocked"
    elif system == "Windows":
        platform_supported = machine.casefold() in {"amd64", "x86_64"} and sys.getwindowsversion().major >= 10
        platform_detail = f"Windows {platform.release()} on {machine}. Bookinator requires a current 64-bit Windows 10 or later installation."
        platform_status = "ready" if platform_supported else "blocked"
    elif system == "Linux":
        platform_supported = machine.casefold() in {"x86_64", "amd64", "aarch64", "arm64"}
        platform_detail = f"Linux on {machine}. This architecture is viable, but Bookinator must still verify the distribution and model backend before declaring full support."
        platform_status = "warning" if platform_supported else "blocked"
    else:
        platform_supported = False
        platform_detail = f"{system or 'Unknown OS'} on {machine or 'unknown architecture'} is not currently supported."
        platform_status = "blocked"

    checks = [
        {"id": "operating-system", "label": "Operating system", "status": platform_status, "value": f"{system} · {machine}", "detail": platform_detail, "instructions": "operating-system" if platform_status != "ready" else ""},
        {"id": "memory", "label": "Memory", "status": "warning" if not memory_gib else "ready" if memory_gib >= 32 else "blocked", "value": f"{memory_gib:g} GB" if memory_gib else "Unknown", "detail": "Bookinator's supported floor for model-backed analysis is 32 GB of physical memory." if memory_gib else "Bookinator could not measure physical memory on this computer.", "instructions": "memory" if not memory_gib or memory_gib < 32 else ""},
        *([{"id": "homebrew", "label": "Homebrew", "status": "ready" if brew_available else "blocked", "value": brew_version or "Missing", "detail": "Bookinator uses Homebrew to install and maintain Ollama and other native dependencies on macOS." if brew_available else "Homebrew is required for Bookinator's managed dependency installation on macOS.", "instructions": "homebrew" if not brew_available else ""}] if system == "Darwin" else []),
        {"id": "python", "label": "Python runtime", "status": "ready" if python_supported else "blocked", "value": python_version, "detail": "Python 3.11 or newer is available." if python_supported else "This source build requires Python 3.11 or newer.", "instructions": "python" if not python_supported else ""},
        {"id": "ollama", "label": "Ollama runtime", "status": "ready" if ollama_installed and ollama_running else "repairable" if brew_available else "blocked", "value": f"Ollama {ollama_version}" if ollama_version else "Not installed or version unavailable", "detail": "Ollama is installed and serving Bookinator's local models." if ollama_running else "Bookinator requires a running Ollama service for local model analysis.", "action": "update-ollama" if brew_available and not ollama_installed else "", "instructions": "ollama" if not brew_available and not ollama_running else ""},
        {"id": "package-installer", "label": "Library installer", "status": "ready" if pip_available or uv_available else "warning", "value": "uv" if uv_available else "pip" if pip_available else "Missing", "detail": "Bookinator can install its managed Python components." if pip_available or uv_available else "Automatic repair of Python components is unavailable until uv or pip is installed.", "instructions": "package-installer" if not pip_available and not uv_available else ""},
        {"id": "storage", "label": "Working storage", "status": "warning" if not free_disk_gib else "ready" if free_disk_gib >= 10 else "blocked", "value": f"{free_disk_gib:g} GB free" if free_disk_gib else "Unknown", "detail": "At least 10 GB of working headroom is required in addition to model downloads." if free_disk_gib else "Bookinator could not measure free space on its data volume.", "instructions": "storage" if not free_disk_gib or free_disk_gib < 10 else ""},
        {"id": "pdf-reader", "label": "Document reader", "status": "ready" if pdf_reader_ready() else "repairable" if pip_available or uv_available else "blocked", "value": "PyMuPDF ready" if pdf_reader_ready() else "PyMuPDF missing", "detail": "PDF and normalized manuscript pages can be read locally." if pdf_reader_ready() else "Bookinator needs its local document reader for manuscript ingestion.", "action": "install-pdf-reader" if not pdf_reader_ready() and (pip_available or uv_available) else "", "instructions": "package-installer" if not pdf_reader_ready() and not (pip_available or uv_available) else ""},
    ]
    blocked = sum(1 for check in checks if check["status"] == "blocked")
    return {"status": "blocked" if blocked else "warning" if any(check["status"] in {"warning", "repairable"} for check in checks) else "ready", "blockedCount": blocked, "checks": checks}


def recommended_roles(memory_gib: float) -> dict[str, str]:
    primary = "qwen3.5:122b" if memory_gib >= 128 else "qwen3.5:35b" if memory_gib >= 48 else "qwen3.5:9b"
    return {
        "intake": "qwen3.5:9b",
        "reader": "qwen3.5:35b" if memory_gib >= 48 else "qwen3.5:9b",
        "primary": primary,
        "defender": primary,
        "judge": primary,
        "embedding": "qwen3-embedding:8b",
    }


def pdf_reader_ready() -> bool:
    try:
        import pymupdf  # type: ignore[import-not-found]  # noqa: F401
    except ImportError:
        return False
    return True


def managed_package_install_command(*requirements: str) -> list[str]:
    """Use the installer available for this exact runtime, preferring pip."""
    if importlib.util.find_spec("pip") is not None:
        return [sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "--target", str(LOCAL_PACKAGES), *requirements]
    if uv := shutil.which("uv"):
        return [uv, "pip", "install", "--python", sys.executable, "--target", str(LOCAL_PACKAGES), *requirements]
    return []


def install_pdf_reader() -> tuple[bool, str]:
    LOCAL_PACKAGES.mkdir(parents=True, exist_ok=True)
    command = managed_package_install_command("PyMuPDF>=1.26,<2")
    if not command:
        return False, "Bookinator needs uv or pip before it can install the PDF reader."
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=240, check=False)
    except (OSError, subprocess.TimeoutExpired) as error:
        return False, f"The PDF reader could not be installed: {error}"
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip().splitlines()
        return False, detail[-1] if detail else "The PDF reader installation failed."
    if str(LOCAL_PACKAGES) not in sys.path:
        sys.path.insert(0, str(LOCAL_PACKAGES))
    return pdf_reader_ready(), "The local PDF reader is ready."


def emotion_model_status() -> dict[str, object]:
    runtime_error = ""
    try:
        import torch  # type: ignore[import-not-found]  # noqa: F401
        import transformers  # type: ignore[import-not-found]  # noqa: F401
        runtime = True
    except Exception as error:
        runtime = False
        runtime_error = str(error)[:300]
    cache_root = Path(os.environ.get("HF_HOME") or (Path.home() / ".cache" / "huggingface"))
    model_root = cache_root / "hub" / "models--j-hartmann--emotion-english-distilroberta-base" / "snapshots"
    cached = model_root.is_dir() and any((snapshot / "config.json").is_file() for snapshot in model_root.iterdir() if snapshot.is_dir())
    return {"runtime": runtime, "model": cached, "ready": runtime and cached, "modelId": EMOTION_MODEL_ID, "runtimeError": runtime_error}


def install_emotion_model() -> tuple[bool, str]:
    """Install the explicit local classifier runtime and cache the pinned model."""
    LOCAL_PACKAGES.mkdir(parents=True, exist_ok=True)
    command = managed_package_install_command("transformers>=4.48,<5", "torch>=2.2,<3")
    if not command:
        return False, "Bookinator needs uv or pip before it can install the emotion runtime."
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=1_200, check=False)
    except (OSError, subprocess.TimeoutExpired) as error:
        return False, f"The emotion runtime could not be installed: {error}"
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip().splitlines()
        return False, detail[-1] if detail else "The emotion runtime installation failed."
    if str(LOCAL_PACKAGES) not in sys.path:
        sys.path.insert(0, str(LOCAL_PACKAGES))
    importlib.invalidate_caches()
    try:
        from transformers import AutoModelForSequenceClassification, AutoTokenizer
        AutoTokenizer.from_pretrained(EMOTION_MODEL_ID)
        AutoModelForSequenceClassification.from_pretrained(EMOTION_MODEL_ID)
    except Exception as error:
        return False, f"The Hartmann model could not be saved locally: {error}"
    for book in load_library():
        pipeline = load_pipeline(book)
        stage = next((item for item in pipeline.get("stages", []) if item.get("id") == "emotions"), None)
        if not stage or not stage.get("setupRequired"):
            continue
        stage.update({"status": "pending", "detail": PIPELINE_STAGE_DEFINITIONS["emotions"][1]})
        stage.pop("setupRequired", None)
        for chapter in pipeline.get("chapters", []):
            if chapter.get("emotionStatus") in {None, "blocked", "failed"} and not chapter.get("emotion"):
                chapter["emotionStatus"] = "pending"
                chapter.pop("emotionError", None)
        pipeline.update({"status": "ready", "phase": "ready", "message": "The local emotion classifier is ready.", "updatedAt": utc_now()})
        write_pipeline(book, pipeline)
    return True, "The Hartmann emotion classifier is installed locally."


def title_from_filename(filename: str) -> str:
    stem = Path(filename).stem
    stem = re.sub(r"[-_]+", " ", stem)
    stem = re.sub(r"\s+", " ", stem).strip()
    return stem


def extract_pdf_preview(pdf_bytes: bytes) -> tuple[dict[str, str], str, list[dict[str, object]]]:
    try:
        import pymupdf  # type: ignore[import-not-found]
    except ImportError:
        return {}, "", []

    with tempfile.NamedTemporaryFile(suffix=".pdf") as temporary_pdf:
        temporary_pdf.write(pdf_bytes)
        temporary_pdf.flush()
        with pymupdf.open(temporary_pdf.name) as document:
            metadata = {
                "title": (document.metadata.get("title") or "").strip(),
                "author": (document.metadata.get("author") or "").strip(),
            }
            opening_pages = list(document)[:10]
            pages = [page.get_text("text") for page in opening_pages]
            image_candidates: list[dict[str, object]] = []
            seen_xrefs: set[int] = set()
            for page_number, page in enumerate(opening_pages[:2], start=1):
                page_area = max(page.rect.width * page.rect.height, 1)
                for image in page.get_images(full=True):
                    xref = int(image[0])
                    if xref in seen_xrefs:
                        continue
                    seen_xrefs.add(xref)
                    try:
                        rectangles = page.get_image_rects(xref)
                        rectangle = max(rectangles, key=lambda item: item.width * item.height) if rectangles else None
                        display_area = rectangle.width * rectangle.height if rectangle else 0
                        width, height = int(image[2]), int(image[3])
                        aspect = width / max(height, 1)
                        if width < 48 or height < 48 or not 0.2 <= aspect <= 5 or not 0.001 <= display_area / page_area <= 0.45:
                            continue
                        pixmap = pymupdf.Pixmap(document, xref)
                        if pixmap.alpha or pixmap.colorspace.n not in (1, 3):
                            pixmap = pymupdf.Pixmap(pymupdf.csRGB, pixmap)
                        while max(pixmap.width, pixmap.height) > 512:
                            pixmap.shrink(1)
                        encoded = base64.b64encode(pixmap.tobytes("png")).decode("ascii")
                        image_candidates.append({
                            "page": page_number,
                            "width": pixmap.width,
                            "height": pixmap.height,
                            "data": encoded,
                        })
                    except Exception:
                        continue
                    if len(image_candidates) >= 6:
                        break
                if len(image_candidates) >= 6:
                    break
    return metadata, "\n\n--- PAGE BREAK ---\n\n".join(pages)[:24_000], image_candidates


def infer_manuscript_icon(candidates: list[dict[str, object]], models: list[str], configured_model: str = "") -> dict[str, object] | None:
    """Ask the local intake model to select title-page art, with refusal as the default."""
    declared_cover = next((candidate for candidate in candidates if candidate.get("role") == "cover"), None)
    if declared_cover:
        media_type = str(declared_cover.get("mediaType") or "image/png")
        return {
            "kind": "image",
            "value": f"data:{media_type};base64,{declared_cover['data']}",
            "width": declared_cover.get("width", 0),
            "height": declared_cover.get("height", 0),
            "source": "embedded-cover",
            "confidence": 1,
        }
    model = configured_model if configured_model in models else choose_metadata_model(models)
    if not model or not candidates:
        return None
    descriptions = [
        f"Candidate {index}: {candidate.get('role', 'image')}"
        + (f" embedded on opening page {candidate['page']}" if candidate.get("page") else f" named {candidate.get('name', 'unknown')}")
        + "."
        for index, candidate in enumerate(candidates)
    ]
    prompt = """Decide whether one of these ordered manuscript images is a distinctive icon or emblem for this particular book.
Reject publisher logos, software marks, signatures, QR codes, page furniture, generic ornaments, and photographs that are merely part of a scanned page.
Prefer a compact illustration, crest, symbol, or intentional cover/title-page mark that would remain recognizable as a small square library icon.
Return JSON only with exactly these fields: candidate_index (integer, or -1 for none), confidence (number from 0 to 1), rationale (short string).
Choose none unless the evidence is strong.

""" + "\n".join(descriptions)
    request = urllib.request.Request(
        "http://127.0.0.1:11434/api/chat",
        data=json.dumps({
            "model": model,
            "stream": False,
            "format": "json",
            "options": {"temperature": 0},
            "messages": [{
                "role": "user",
                "content": prompt,
                "images": [candidate["data"] for candidate in candidates],
            }],
        }).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=300) as response:
            payload = json.load(response)
        result = json.loads(payload["message"]["content"])
        selected = int(result.get("candidate_index", -1))
        confidence = float(result.get("confidence", 0))
        if selected < 0 or selected >= len(candidates) or confidence < 0.7:
            return None
        candidate = candidates[selected]
        media_type = str(candidate.get("mediaType") or "image/png")
        return {
            "kind": "image",
            "value": f"data:{media_type};base64,{candidate['data']}",
            "width": candidate["width"],
            "height": candidate["height"],
            "source": "title-page-art",
            "model": model,
            "confidence": confidence,
        }
    except (KeyError, TypeError, ValueError, OSError, urllib.error.URLError, json.JSONDecodeError):
        return None


def model_parameter_billions(name: str) -> float:
    matches = re.findall(r"(?:^|[:_-])(\d+(?:\.\d+)?)b(?:$|[:_-])", name.lower())
    return float(matches[-1]) if matches else 999.0


def choose_metadata_model(models: list[str]) -> str | None:
    if not models:
        return None
    preferred = ("qwen3", "qwen2.5", "llama3.2", "mistral")
    for family in preferred:
        matches = [model for model in models if family in model.lower() and model_parameter_billions(model) >= 3]
        if matches:
            return min(matches, key=model_parameter_billions)
    return min(models, key=model_parameter_billions)


def choose_primary_model(models: list[str]) -> str | None:
    generative = [model for model in models if "embed" not in model.lower()]
    qwen = [model for model in generative if "qwen" in model.lower() and model_parameter_billions(model) < 999]
    known = [model for model in generative if model_parameter_billions(model) < 999]
    candidates = qwen or known or generative
    return max(candidates, key=model_parameter_billions) if candidates else None


def load_settings() -> dict[str, str]:
    try:
        payload = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return {key: str(value) for key, value in payload.items() if isinstance(value, str)}


def save_settings(settings: dict[str, str]) -> None:
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_PATH.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")


def infer_manuscript_identity(text: str, metadata: dict[str, str], models: list[str], configured_model: str = "", metadata_authoritative: bool = False) -> dict[str, str]:
    model = configured_model if configured_model in models else choose_metadata_model(models)
    if not model or not text.strip():
        return dict(metadata)
    prompt = f"""Identify the manuscript title and author from the opening pages below.
Return JSON only with exactly these string fields: title, author, abbreviation.
Prefer explicit title-page evidence. Source metadata may already contain authoritative fields; do not contradict populated fields.
Do not invent either value. Use an empty string when uncertain.
For abbreviation, create a distinctive 1-3 character uppercase library mark from the title. Prefer meaningful initials or a memorable title fragment; do not merely take the first three letters when better initials exist.

Source metadata: {json.dumps(metadata, ensure_ascii=False)}

Opening pages:
{text}
"""
    request = urllib.request.Request(
        "http://127.0.0.1:11434/api/chat",
        data=json.dumps({
            "model": model,
            "stream": False,
            "format": "json",
            "options": {"temperature": 0},
            "messages": [{"role": "user", "content": prompt}],
        }).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=300) as response:
            payload = json.load(response)
        result = json.loads(payload["message"]["content"])
        model_title = str(result.get("title") or "").strip()
        authoritative_title = str(metadata.get("title") or "").strip() if metadata_authoritative else ""
        abbreviation = str(result.get("abbreviation") or "").strip()[:3]
        if authoritative_title and model_title.casefold() != authoritative_title.casefold():
            abbreviation = fallback_title_mark(authoritative_title)
        return {
            "title": str(metadata.get("title") if metadata_authoritative and metadata.get("title") else result.get("title") or metadata.get("title") or "").strip(),
            "author": str(metadata.get("author") if metadata_authoritative and metadata.get("author") else result.get("author") or metadata.get("author") or "").strip(),
            "abbreviation": abbreviation,
            "model": model,
        }
    except (KeyError, TypeError, ValueError, OSError, urllib.error.URLError, json.JSONDecodeError):
        return dict(metadata)


def fallback_title_mark(title: str) -> str:
    words = re.findall(r"[\w]+", title, flags=re.UNICODE)
    useful = [word for word in words if word.casefold() not in {"a", "an", "and", "of", "the", "to"}]
    return "".join(word[0] for word in (useful or words)[:3]).upper() or "B"


def infer_title_mark(title: str, models: list[str], configured_model: str = "") -> dict[str, str]:
    model = configured_model if configured_model in models else choose_metadata_model(models)
    fallback = fallback_title_mark(title)
    if not model:
        return {"abbreviation": fallback, "source": "initials"}
    request = urllib.request.Request(
        "http://127.0.0.1:11434/api/chat",
        data=json.dumps({
            "model": model, "stream": False, "format": "json", "options": {"temperature": 0.2},
            "messages": [{"role": "user", "content": f"Create a memorable 1-3 character uppercase library mark for the book title {json.dumps(title)}. Prefer meaningful initials or a distinctive title fragment. Return JSON only with one string field: abbreviation."}],
        }).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=300) as response:
            payload = json.load(response)
        result = json.loads(payload["message"]["content"])
        abbreviation = str(result.get("abbreviation") or "").strip()[:3]
        return {"abbreviation": abbreviation or fallback, "source": "local-model", "model": model}
    except (KeyError, TypeError, ValueError, OSError, urllib.error.URLError, json.JSONDecodeError):
        return {"abbreviation": fallback, "source": "initials"}


def ollama_status() -> dict[str, object]:
    installed = shutil.which("ollama") is not None
    running = False
    models: list[str] = []
    version = ""
    try:
        with urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=3) as response:
            payload = json.load(response)
        running = True
        models = [model.get("name", "") for model in payload.get("models", []) if model.get("name")]
        try:
            with urllib.request.urlopen("http://127.0.0.1:11434/api/version", timeout=3) as response:
                version = str(json.load(response).get("version") or "")
        except (OSError, urllib.error.URLError, TimeoutError, json.JSONDecodeError, AttributeError):
            pass
    except (OSError, urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        pass
    return {"installed": installed, "running": running, "version": version, "models": models}


def ollama_pull_error(model: str, status: int | None, response_body: str = "") -> dict[str, object]:
    """Turn Ollama's often terse pull failures into useful, truthful UI guidance."""
    detail = response_body.strip()
    try:
        payload = json.loads(detail)
        if isinstance(payload, dict):
            detail = str(payload.get("error") or payload.get("message") or detail).strip()
    except json.JSONDecodeError:
        pass
    official_library_model = not model.casefold().startswith("hf.co/")
    auth_words = ("unauthorized", "forbidden", "gated", "access token", "authentication")
    needs_hugging_face_token = not official_library_model and (status in {401, 403} or any(word in detail.casefold() for word in auth_words))
    if needs_hugging_face_token:
        guidance = "This Hugging Face model is private or gated. Request access on its Hugging Face page, then create a read token. Bookinator does not store Hugging Face tokens yet."
        kind = "hugging-face-auth"
    elif status == 404:
        guidance = "Ollama could not find that model name. Check the tag in the Ollama model library and try again."
        kind = "model-not-found"
    else:
        guidance = "This Ollama Library model does not need a Hugging Face key. Make sure Ollama is current, then retry; the diagnostic below is Ollama's own response."
        kind = "ollama-error"
    message = f"Ollama could not install {model}."
    if detail:
        message += f" {detail}"
    elif status:
        message += f" Ollama returned HTTP {status}."
    return {
        "error": message,
        "model": model,
        "kind": kind,
        "guidance": guidance,
        "needsHuggingFaceToken": needs_hugging_face_token,
        "helpUrl": "https://huggingface.co/settings/tokens" if needs_hugging_face_token else "https://ollama.com/library",
    }


def model_runtime_failure(model: str, error: BaseException) -> str:
    """Describe a model runner disappearing without hiding Ollama's response."""
    detail = ""
    if isinstance(error, urllib.error.HTTPError):
        try:
            detail = error.read().decode("utf-8", errors="replace").strip()
            payload = json.loads(detail)
            if isinstance(payload, dict):
                detail = str(payload.get("error") or payload.get("message") or detail).strip()
        except (OSError, json.JSONDecodeError):
            pass
    if not detail:
        detail = str(getattr(error, "reason", "") or error).strip()
    message = f"{model} stopped responding during this attempt."
    if detail:
        message += f" Ollama reported: {detail}"
    return message


def system_status() -> dict[str, object]:
    machine = platform.machine()
    memory_gib = physical_memory_gib()
    ollama = ollama_status()
    settings = load_settings()
    recommended_model = choose_metadata_model(ollama["models"] if ollama["running"] else [])
    installed_primary = choose_primary_model(ollama["models"] if ollama["running"] else [])
    role_recommendations = recommended_roles(memory_gib)
    available_models = ollama["models"] if ollama["running"] else []
    assignments = {}
    for role in MODEL_ROLES:
        saved = settings.get(f"{role}Model", "")
        fallback = recommended_model if role == "intake" else next((model for model in available_models if "embed" in model.lower()), "") if role == "embedding" else installed_primary
        assignments[role] = saved if saved in available_models else fallback
    return {
        "platform": platform.system(),
        "architecture": machine,
        "memoryGiB": memory_gib,
        "appleSilicon": platform.system() == "Darwin" and machine == "arm64",
        "python": platform.python_version(),
        "readiness": machine_readiness(ollama),
        "pdfReader": pdf_reader_ready(),
        "emotionModel": emotion_model_status(),
        "ollama": ollama,
        "models": {
            "intake": assignments["intake"],
            "recommended": recommended_model,
            "roles": assignments,
            "roleLabels": MODEL_ROLES,
            "roleRecommendations": role_recommendations,
            "catalog": MODEL_CATALOG,
        },
        "localOnly": True,
    }


def assigned_model_roles(model: str, available_models: list[str] | None = None) -> list[str]:
    """Return the Bookinator roles that currently resolve to an Ollama model."""
    available = available_models if available_models is not None else list(ollama_status().get("models") or [])
    settings = load_settings()
    recommended_model = choose_metadata_model(available)
    installed_primary = choose_primary_model(available)
    wanted = model.casefold()
    assignments: list[str] = []
    for role, label in MODEL_ROLES.items():
        saved = str(settings.get(f"{role}Model", "") or "")
        fallback = recommended_model if role == "intake" else next((candidate for candidate in available if "embed" in candidate.lower()), "") if role == "embedding" else installed_primary
        effective = saved if saved in available else fallback
        if effective.casefold() == wanted:
            assignments.append(label)
    return assignments


class BookinatorHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, directory=str(WEB_ROOT), **kwargs)

    def end_headers(self) -> None:
        if not self.path.startswith("/api/"):
            self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, message: str, *args: object) -> None:
        print(f"[bookinator] {message % args}")

    def translate_path(self, path: str) -> str:
        route_path = urllib.parse.unquote(urllib.parse.urlsplit(path).path)
        if route_path == "/docs" or route_path.startswith("/docs/"):
            relative = route_path.removeprefix("/docs").lstrip("/")
            candidate = (DOCS_ROOT / relative).resolve()
            if candidate == DOCS_ROOT.resolve() or DOCS_ROOT.resolve() in candidate.parents:
                return str(candidate)
        return super().translate_path(path)

    def send_json(self, payload: dict[str, object], status: HTTPStatus = HTTPStatus.OK) -> None:
        encoded = json.dumps(payload).encode("utf-8")
        compressed = len(encoded) >= 1024 and "gzip" in str(self.headers.get("Accept-Encoding") or "").casefold()
        body = gzip.compress(encoded, compresslevel=5) if compressed else encoded
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        if compressed:
            self.send_header("Content-Encoding", "gzip")
            self.send_header("Vary", "Accept-Encoding")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_GET(self) -> None:  # noqa: N802
        route = urllib.parse.urlsplit(self.path)
        if self.path == "/api/health":
            self.send_json({"ok": True, "features": API_FEATURES})
            return
        if self.path == "/api/system":
            self.send_json(system_status())
            return
        if self.path == "/api/books":
            books = load_library()
            self.send_json({"books": books, "pipeline": global_pipeline_state(books)})
            return
        if route.path == "/api/library/export":
            requested = {item for item in urllib.parse.parse_qs(route.query).get("ids", [""])[0].split(",") if item}
            books = [book for book in load_library() if not requested or str(book.get("id")) in requested]
            portable = []
            for book in books:
                record = {key: value for key, value in book.items() if key not in {"pipeline", "hasPdf", "manuscriptId"}}
                record["analysis"] = load_pipeline(book)
                portable.append(record)
            self.send_json({"schema": "bookinator-library-v1", "exportedAt": utc_now(), "books": portable})
            return
        chapter_source_match = re.fullmatch(r"/api/books/([A-Za-z0-9_-]{8,80})/chapters/(\d{1,5})/source", route.path)
        if chapter_source_match:
            book = find_book(chapter_source_match.group(1))
            chapter = load_chapter_source(book, int(chapter_source_match.group(2))) if book else None
            if not chapter:
                self.send_json({"error": "That saved chapter source is not available."}, HTTPStatus.NOT_FOUND)
                return
            self.send_json({"chapter": chapter})
            return
        manuscript_match = re.fullmatch(r"/api/books/([A-Za-z0-9_-]{8,80})/manuscript", route.path)
        if manuscript_match:
            book = find_book(manuscript_match.group(1))
            manuscript_id = str(book.get("manuscriptId") or "") if book else ""
            manuscript_path = BOOKS_ROOT / manuscript_id / "manuscript.pdf" if manuscript_id else None
            if not book or not manuscript_path or not manuscript_path.is_file():
                self.send_json({"error": "This book has no saved PDF."}, HTTPStatus.NOT_FOUND)
                return
            filename = str(book.get("sourceFilename") or "manuscript.pdf")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/pdf")
            self.send_header("Content-Length", str(manuscript_path.stat().st_size))
            self.send_header("Content-Disposition", f"inline; filename*=UTF-8''{urllib.parse.quote(filename)}")
            self.send_header("Cache-Control", "private, no-store")
            self.end_headers()
            with manuscript_path.open("rb") as manuscript_file:
                shutil.copyfileobj(manuscript_file, self.wfile)
            return
        source_match = re.fullmatch(r"/api/books/([A-Za-z0-9_-]{8,80})/source", route.path)
        if source_match:
            book = find_book(source_match.group(1))
            manuscript_id = str(book.get("manuscriptId") or "") if book else ""
            source_path, metadata = source_document_path(manuscript_id)
            if not book or not source_path:
                self.send_json({"error": "This book has no saved source document."}, HTTPStatus.NOT_FOUND)
                return
            filename = str(metadata.get("sourceFilename") or source_path.name)
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", str(metadata.get("sourceMediaType") or "application/octet-stream"))
            self.send_header("Content-Length", str(source_path.stat().st_size))
            self.send_header("Content-Disposition", f"attachment; filename*=UTF-8''{urllib.parse.quote(filename)}")
            self.send_header("Cache-Control", "private, no-store")
            self.end_headers()
            with source_path.open("rb") as source_file:
                shutil.copyfileobj(source_file, self.wfile)
            return
        pipeline_match = re.fullmatch(r"/api/books/([A-Za-z0-9_-]{8,80})/pipeline", route.path)
        if pipeline_match:
            book = find_book(pipeline_match.group(1))
            if not book:
                self.send_json({"error": "Book not found."}, HTTPStatus.NOT_FOUND)
                return
            pipeline = load_pipeline(book)
            if pipeline.get("status") == "running" and not pipeline_worker_is_alive(pipeline_match.group(1), pipeline):
                phase = str(pipeline.get("phase") or "")
                active_stage_id = "dossiers" if phase == "dossiers" else "summaries" if phase == "summarizing" else "extraction"
                model = str(next((stage.get("model") for stage in pipeline.get("stages", []) if stage.get("id") == active_stage_id), "") or "The local model")
                ollama_running = bool(ollama_status()["running"])
                if phase == "preparing":
                    diagnostic = "The previous manuscript-preparation process ended before it recorded completion. Press Rebuild to retry extraction."
                    message = "Manuscript preparation was interrupted. The saved source is safe."
                else:
                    diagnostic = f"{model} is no longer responding because Ollama is not running. Open Ollama, then press Continue." if not ollama_running else f"{model}'s previous reading process ended without returning a result. Press Continue to retry the interrupted work."
                    message = "The previous model run was interrupted. Completed work is safe."
                reset_interrupted_rollup(pipeline, phase, diagnostic)
                pipeline.update({"status": "warning", "phase": "interrupted", "message": message, "error": diagnostic, "updatedAt": utc_now()})
                for stage in pipeline.get("stages", []):
                    if stage.get("status") == "running":
                        stage.update({"status": "warning", "detail": diagnostic})
                for chapter in pipeline.get("chapters", []):
                    if chapter.get("status") == "running":
                        chapter.update({"status": "pending", "interruptedAt": utc_now(), "error": diagnostic})
                        for key in ("completedAt", "durationSeconds"):
                            chapter.pop(key, None)
                for chunk in pipeline.get("chunks", []):
                    if chunk.get("dossierStatus") == "running":
                        chunk.update({"dossierStatus": "pending", "dossierError": diagnostic})
                        try:
                            artifact = json.loads((chunk_artifacts_path(book) / f"{int(chunk.get('sequence')):04d}.json").read_text(encoding="utf-8"))
                            artifact.update({"dossierStatus": "pending", "dossierError": diagnostic})
                            write_chunk_artifact(book, int(chunk.get("sequence")), artifact)
                        except (OSError, ValueError, TypeError, json.JSONDecodeError):
                            pass
                write_pipeline(book, pipeline)
            workspace_reader = load_settings().get("readerModel", "")
            workspace_dossier = load_settings().get("primaryModel", "")
            workspace_tags = load_settings().get("tagsModel", "") or workspace_reader
            pipeline["readerModelOverride"] = str(pipeline.get("readerModel") or "")
            pipeline["workspaceReaderModel"] = workspace_reader
            pipeline["configuredReaderModel"] = str(pipeline.get("readerModel") or workspace_reader)
            pipeline["dossierModelOverride"] = str(pipeline.get("dossierModel") or "")
            pipeline["workspaceDossierModel"] = workspace_dossier
            pipeline["configuredDossierModel"] = str(pipeline.get("dossierModel") or workspace_dossier)
            pipeline["tagModelOverride"] = str(pipeline.get("tagModel") or "")
            pipeline["workspaceTagModel"] = workspace_tags
            pipeline["configuredTagModel"] = str(pipeline.get("tagModel") or workspace_tags)
            pipeline["chapterMapWarnings"] = [
                *chapter_map_warnings(pipeline.get("chapters", []), pipeline.get("acceptedChapterLabelVariants", [])),
                *chapter_heading_report_warnings(pipeline.get("chapterHeadingReport", {})),
            ]
            pipeline["chapterMapSuspicious"] = bool(pipeline["chapterMapWarnings"])
            pipeline = pipeline_for_client(pipeline_match.group(1), pipeline)
            pipeline["activity"] = pipeline_activity(book, pipeline)
            pipeline["globalPipeline"] = global_pipeline_state()
            self.send_json(compact_pipeline_payload(add_pipeline_progress(pipeline)))
            return
        super().do_GET()

    def do_POST(self) -> None:  # noqa: N802
        global QUEUE_THREAD
        route = urllib.parse.urlsplit(self.path)
        if route.path in {"/api/library/queue", "/api/library/delete", "/api/library/import"}:
            try:
                length = int(self.headers.get("Content-Length", "0") or 0)
                payload = json.loads(self.rfile.read(length))
                if not isinstance(payload, dict):
                    raise ValueError("Invalid library request.")
            except (ValueError, TypeError, json.JSONDecodeError) as error:
                self.send_json({"error": str(error) or "Invalid library request."}, HTTPStatus.BAD_REQUEST)
                return
            if route.path == "/api/library/queue":
                ids = [str(item) for item in payload.get("ids", [])]
                valid = {str(book.get("id")) for book in load_library()}
                queue = load_queue()
                if payload.get("action") == "add":
                    queue.extend(book_id for book_id in ids if book_id in valid)
                elif payload.get("action") == "remove":
                    queue = [book_id for book_id in queue if book_id not in ids]
                else:
                    self.send_json({"error": "Choose add or remove."}, HTTPStatus.BAD_REQUEST)
                    return
                save_queue(queue)
                self.send_json({"queued": load_queue()})
                return
            if route.path == "/api/library/delete":
                ids = {str(item) for item in payload.get("ids", [])}
                with LIBRARY_LOCK:
                    library = load_library()
                    removed = [book for book in library if str(book.get("id")) in ids]
                    kept = [{key: value for key, value in book.items() if key not in {"pipeline", "hasPdf"}} for book in library if str(book.get("id")) not in ids]
                    temporary_path = LIBRARY_PATH.with_suffix(".tmp")
                    temporary_path.write_text(json.dumps(kept, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                    temporary_path.replace(LIBRARY_PATH)
                cleanup_warnings = []
                for book in removed:
                    manuscript_id = str(book.get("manuscriptId") or "")
                    target = BOOKS_ROOT / manuscript_id if manuscript_id else None
                    if target and target.parent == BOOKS_ROOT and target.is_dir():
                        try:
                            shutil.rmtree(target)
                        except OSError as error:
                            cleanup_warnings.append(f"{manuscript_id}: {error}")
                save_queue([book_id for book_id in load_queue() if book_id not in ids])
                for book_id in ids:
                    with QUEUE_LOCK:
                        QUEUE_ACTIONS.pop(book_id, None)
                        remove_queue_action(book_id)
                    if event := PIPELINE_CANCEL_EVENTS.get(book_id):
                        event.set()
                self.send_json({"deleted": len(removed), "deletedIds": [str(book.get("id")) for book in removed], "cleanupWarnings": cleanup_warnings})
                return
            imported = 0
            for incoming in payload.get("books", []):
                if not isinstance(incoming, dict):
                    continue
                project_id = str(uuid.uuid4())
                project_root = BOOKS_ROOT / project_id
                project_root.mkdir(parents=True, exist_ok=False)
                analysis = incoming.get("analysis") if isinstance(incoming.get("analysis"), dict) else None
                if analysis:
                    (project_root / "pipeline.json").write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                portable = {key: value for key, value in incoming.items() if key != "analysis"}
                portable.update({"id": str(uuid.uuid4()), "manuscriptId": project_id, "sourceFilename": "", "ingestedAt": str(incoming.get("ingestedAt") or utc_now())})
                save_book(portable)
                imported += 1
            self.send_json({"imported": imported}, HTTPStatus.CREATED)
            return
        if route.path == "/api/library/pipeline/start":
            automatic = start_global_pipeline()
            self.send_json({"started": True, "queued": len(automatic), "pipeline": global_pipeline_state()}, HTTPStatus.ACCEPTED)
            return
        if route.path == "/api/library/pipeline/prioritize":
            try:
                length = int(self.headers.get("Content-Length", "0") or 0)
                payload = json.loads(self.rfile.read(length))
                book_id = str(payload.get("bookId") or "")
                action = str(payload.get("action") or "summarize")
            except (ValueError, TypeError, json.JSONDecodeError):
                self.send_json({"error": "Invalid pipeline request."}, HTTPStatus.BAD_REQUEST)
                return
            try:
                prioritize_pipeline_action(book_id, action)
            except ValueError as error:
                self.send_json({"error": str(error)}, HTTPStatus.BAD_REQUEST)
                return
            self.send_json({"started": True, "prioritized": book_id, "action": action, "queueProtocol": 2}, HTTPStatus.ACCEPTED)
            return
        if route.path == "/api/library/pipeline/stop":
            set_pipeline_enabled(False)
            QUEUE_CANCEL_EVENT.set()
            with QUEUE_LOCK:
                QUEUE_ACTIONS.clear()
                save_queue_actions({})
            for event in PIPELINE_CANCEL_EVENTS.values():
                event.set()
            for book_id in list(PIPELINE_CANCEL_EVENTS):
                cancel_active_model_response(book_id)
            for book in load_library():
                pipeline = load_pipeline(book)
                if pipeline.get("status") == "running":
                    for chapter in pipeline.get("chapters", []):
                        if chapter.get("status") == "running":
                            chapter.update({"status": "pending", "interruptedAt": utc_now(), "error": "Stopped before completion. Resume retries this chapter."})
                        for prefix in ("emotion", "tag", "smell"):
                            if chapter.get(f"{prefix}Status") == "running":
                                chapter.update({f"{prefix}Status": "pending", f"{prefix}Error": "Stopped before completion. Resume retries this chapter."})
                    for chunk in pipeline.get("chunks", []):
                        if chunk.get("dossierStatus") == "running":
                            chunk.update({"dossierStatus": "pending", "dossierError": "Stopped before completion. Resume retries this chunk."})
                            try:
                                artifact = json.loads((chunk_artifacts_path(book) / f"{int(chunk.get('sequence')):04d}.json").read_text(encoding="utf-8"))
                                artifact.update({"dossierStatus": "pending", "dossierError": chunk["dossierError"]})
                                write_chunk_artifact(book, int(chunk.get("sequence")), artifact)
                            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                                pass
                    pipeline.update({"status": "paused", "phase": "paused", "stopRequested": False, "message": "Reader stopped. Completed chapters are safe; Resume retries the interrupted chapter.", "updatedAt": utc_now()})
                    write_pipeline(book, pipeline)
                elif pipeline.get("status") == "queued":
                    pipeline.update({"status": "paused", "phase": "paused", "stopRequested": False, "message": "Stopped before the local reader began. Continue whenever you are ready.", "updatedAt": utc_now()})
                    write_pipeline(book, pipeline)
            self.send_json({"stopping": True}, HTTPStatus.ACCEPTED)
            return
        retry_failed_match = re.fullmatch(r"/api/books/([A-Za-z0-9_-]{8,80})/pipeline/retry-failed", route.path)
        if retry_failed_match:
            book_id = retry_failed_match.group(1)
            book = find_book(book_id)
            if not book:
                self.send_json({"error": "Book not found."}, HTTPStatus.NOT_FOUND)
                return
            pipeline = load_pipeline(book)
            interrupted_active_work = pipeline_worker_is_alive(book_id, pipeline)
            queue_owned_work = bool(QUEUE_THREAD and QUEUE_THREAD.is_alive() and PIPELINE_THREADS.get(book_id) is QUEUE_THREAD)
            if interrupted_active_work and queue_owned_work:
                with QUEUE_LOCK:
                    QUEUE_ACTIONS[book_id] = "deferred-retry-failed"
                self.send_json({"retrying": True, "queuedBehindActiveResponse": True, "interruptedActiveWork": False, "queueProtocol": 2}, HTTPStatus.ACCEPTED)
                return
            if interrupted_active_work:
                if not quiesce_pipeline_for_refresh(book_id, pipeline):
                    self.send_json({"error": "Bookinator could not safely finish the active model handoff. Stop the queue, then retry the failed work."}, HTTPStatus.CONFLICT)
                    return
                pipeline = load_pipeline(book)
            count = retry_failed_analysis(book, pipeline)
            if not count:
                self.send_json({"error": "No failed analysis work remains to retry."}, HTTPStatus.CONFLICT)
                return
            write_pipeline(book, pipeline)
            prioritize_pipeline_action(book_id, "chapter-pipeline")
            self.send_json({"retrying": True, "count": count, "interruptedActiveWork": interrupted_active_work, "queueProtocol": 2}, HTTPStatus.ACCEPTED)
            return
        smell_disposition_match = re.fullmatch(r"/api/books/([A-Za-z0-9_-]{8,80})/analysis/smell-disposition", route.path)
        if smell_disposition_match:
            book = find_book(smell_disposition_match.group(1))
            try:
                length = int(self.headers.get("Content-Length", "0") or 0)
                payload = json.loads(self.rfile.read(length))
                sequence = int(payload.get("chapter") or 0)
                candidate_id = str(payload.get("candidateId") or "")
                disposition = str(payload.get("disposition") or "")
            except (ValueError, TypeError, json.JSONDecodeError):
                self.send_json({"error": "Choose a valid Smells finding."}, HTTPStatus.BAD_REQUEST)
                return
            if not book or sequence < 1 or not candidate_id or disposition not in {"active", "dismissed", "reported"}:
                self.send_json({"error": "That Smells finding cannot be updated."}, HTTPStatus.BAD_REQUEST)
                return
            pipeline = load_pipeline(book)
            chapter = next((item for item in pipeline.get("chapters", []) if int(item.get("sequence") or item.get("number") or 0) == sequence), None)
            candidates = chapter.get("smell", {}).get("candidates", []) if isinstance(chapter, dict) and isinstance(chapter.get("smell"), dict) else []
            candidate = next((item for item in candidates if str(item.get("id") or "") == candidate_id), None)
            if not isinstance(candidate, dict):
                self.send_json({"error": "That saved Smells finding no longer exists."}, HTTPStatus.NOT_FOUND)
                return
            candidate["userStatus"] = disposition
            candidate["userStatusUpdatedAt"] = utc_now()
            chapter.setdefault("smellDispositions", {})[candidate_id] = {
                "status": disposition, "updatedAt": candidate["userStatusUpdatedAt"],
            }
            write_pipeline(book, pipeline)
            self.send_json({"saved": True, "disposition": disposition})
            return
        refresh_match = re.fullmatch(r"/api/books/([A-Za-z0-9_-]{8,80})/analysis/refresh", route.path)
        if refresh_match:
            book_id = refresh_match.group(1)
            book = find_book(book_id)
            try:
                length = int(self.headers.get("Content-Length", "0") or 0)
                payload = json.loads(self.rfile.read(length))
                kind = str(payload.get("kind") or "")
                sequence = int(payload.get("id") or 0) if kind != "whole-summary" else 0
            except (ValueError, TypeError, json.JSONDecodeError):
                self.send_json({"error": "Choose a valid analysis result to refresh."}, HTTPStatus.BAD_REQUEST)
                return
            if not book or kind not in {"summary", "dossier", "emotion", "tag", "smell", "whole-summary"} or (kind != "whole-summary" and sequence < 1):
                self.send_json({"error": "That analysis result is not refreshable."}, HTTPStatus.BAD_REQUEST)
                return
            pipeline = load_pipeline(book)
            interrupted_active_work = pipeline_worker_is_alive(book_id, pipeline)
            queue_owned_work = bool(QUEUE_THREAD and QUEUE_THREAD.is_alive() and PIPELINE_THREADS.get(book_id) is QUEUE_THREAD)
            if interrupted_active_work and queue_owned_work:
                # Do not fight a model that may still be loading before an
                # interruptible response stream exists. The chapter-first
                # worker yields when it sees this action; reset the requested
                # results only after its final checkpoint is safely on disk.
                with QUEUE_LOCK:
                    pending = DEFERRED_ANALYSIS_REFRESHES.setdefault(book_id, [])
                    request = (kind, sequence)
                    if request not in pending:
                        pending.append(request)
                    persisted_refreshes = load_deferred_analysis_refreshes()
                    persisted = persisted_refreshes.setdefault(book_id, [])
                    if request not in persisted:
                        persisted.append(request)
                    save_deferred_analysis_refreshes(persisted_refreshes)
                    QUEUE_ACTIONS[book_id] = "deferred-refresh"
                    persist_queue_action(book_id, "deferred-refresh")
                self.send_json({"refreshing": True, "queuedBehindActiveResponse": True, "kind": kind, "id": sequence, "status": "queued", "queueProtocol": 2}, HTTPStatus.ACCEPTED)
                return
            if interrupted_active_work:
                if not quiesce_pipeline_for_refresh(book_id, pipeline):
                    self.send_json({"error": "Bookinator could not safely finish the active model handoff. Stop the queue, then retry this result."}, HTTPStatus.CONFLICT)
                    return
                pipeline = load_pipeline(book)
            try:
                action, was_running = refresh_analysis_result(book, pipeline, kind, sequence)
            except LookupError as error:
                self.send_json({"error": str(error)}, HTTPStatus.NOT_FOUND)
                return
            if was_running:
                QUEUE_CANCEL_EVENT.set()
                cancel_active_model_response(book_id)
            prioritize_pipeline_action(book_id, action)
            self.send_json({"refreshing": True, "kind": kind, "id": sequence, "status": "pending", "interruptedActiveWork": interrupted_active_work}, HTTPStatus.ACCEPTED)
            return
        chapter_map_match = re.fullmatch(r"/api/books/([A-Za-z0-9_-]{8,80})/chapter-map/(approve|variants|demote|restore)", route.path)
        if chapter_map_match:
            book_id, operation = chapter_map_match.groups()
            book = find_book(book_id)
            if not book:
                self.send_json({"error": "Book not found."}, HTTPStatus.NOT_FOUND)
                return
            try:
                length = int(self.headers.get("Content-Length", "0") or 0)
                request = json.loads(self.rfile.read(length) or b"{}")
                if not isinstance(request, dict):
                    raise ValueError("Invalid chapter-map request.")
            except (ValueError, TypeError, json.JSONDecodeError) as error:
                self.send_json({"error": str(error) or "Invalid chapter-map request."}, HTTPStatus.BAD_REQUEST)
                return
            pipeline = load_pipeline(book)
            if operation == "approve":
                warnings = [
                    *chapter_map_warnings(pipeline.get("chapters", []), pipeline.get("acceptedChapterLabelVariants", [])),
                    *chapter_heading_report_warnings(pipeline.get("chapterHeadingReport", {})),
                ]
                if warnings:
                    self.send_json({"error": "Resolve or rebuild the anomalous chapter headings before approving this map.", "warnings": warnings}, HTTPStatus.CONFLICT)
                    return
                pipeline.update({"chapterMapApproved": True, "chapterMapApprovedAt": utc_now(), "analysisProvisional": False, "updatedAt": utc_now()})
                if pipeline.get("status") not in {"running", "queued", "paused", "complete", "warning"}:
                    pipeline.update({"status": "ready", "phase": "chapter-map-approved", "message": "Chapter map approved. Existing analysis now belongs to the accepted structure."})
                write_pipeline(book, pipeline)
                self.send_json({"approved": True, "chapterMapProtocol": 1, "pipeline": add_pipeline_progress(pipeline)})
                return
            if operation in {"demote", "restore"}:
                try:
                    page = int(request.get("page") or 0)
                except (TypeError, ValueError):
                    page = 0
                chapter = next(
                    (item for item in pipeline.get("chapters", []) if int(item.get("pageStart") or 0) == page),
                    None,
                )
                demoted = {int(value) for value in pipeline.get("demotedChapterBoundaryPages", [])}
                if operation == "demote":
                    if not chapter or str(chapter.get("title") or "").casefold() == "front matter":
                        self.send_json({"error": "Only a proposed manuscript chapter can be demoted."}, HTTPStatus.BAD_REQUEST)
                        return
                    authored = [item for item in pipeline.get("chapters", []) if str(item.get("title") or "").casefold() != "front matter"]
                    if len(authored) <= 1:
                        self.send_json({"error": "A manuscript must retain at least one chapter."}, HTTPStatus.BAD_REQUEST)
                        return
                    if int(authored[0].get("pageStart") or 0) == page:
                        self.send_json({"error": "The first manuscript chapter cannot be folded backward. Promote an earlier boundary or rebuild instead."}, HTTPStatus.BAD_REQUEST)
                        return
                    demoted.add(page)
                    message = f"{strip_markdown_heading(chapter.get('title'))} will be folded into the preceding section. Rebuilding the map…"
                else:
                    if page not in demoted:
                        self.send_json({"error": "That boundary is not currently excluded."}, HTTPStatus.BAD_REQUEST)
                        return
                    demoted.remove(page)
                    message = "Restoring the chapter boundary and rebuilding the map…"
                pipeline["demotedChapterBoundaryPages"] = sorted(demoted)
                pipeline["chapterMapApproved"] = False
                pipeline.pop("chapterMapApprovedAt", None)
                invalidate_pipeline_stage(
                    pipeline, "structure", include_self=True, status="pending",
                    detail="Chapter boundaries changed; rebuild the map before analysis.",
                )
                pipeline.update({"status": "review", "phase": "chapter-map", "message": message, "updatedAt": utc_now()})
                write_pipeline(book, pipeline)
                prioritize_pipeline_action(book_id, "prepare")
                self.send_json({"demotedPages": sorted(demoted), "rebuilding": True, "chapterMapEditing": 1}, HTTPStatus.ACCEPTED)
                return
            labels = [str(label).strip() for label in request.get("labels", []) if str(label).strip()]
            candidates = {
                str(item.get("label") or "").casefold(): item
                for item in pipeline.get("chapterHeadingReport", {}).get("otherCandidates", [])
                if isinstance(item, dict)
            }
            invalid = [label for label in labels if label.casefold() not in candidates or int(candidates[label.casefold()].get("count") or 0) != 1]
            if invalid:
                self.send_json({"error": f"Only a unique excluded heading can become a chapter variant: {', '.join(invalid)}"}, HTTPStatus.BAD_REQUEST)
                return
            pipeline["acceptedChapterLabelVariants"] = list(dict.fromkeys(labels))
            pipeline["chapterMapApproved"] = False
            pipeline.pop("chapterMapApprovedAt", None)
            invalidate_pipeline_stage(
                pipeline, "structure", include_self=True, status="pending",
                detail="Chapter-heading rules changed; rebuild the map before analysis.",
            )
            pipeline.update({"status": "review", "phase": "chapter-map", "message": "Chapter variants changed. Rebuilding the map…", "updatedAt": utc_now()})
            write_pipeline(book, pipeline)
            prioritize_pipeline_action(book_id, "prepare")
            self.send_json({"acceptedVariants": labels, "rebuilding": True}, HTTPStatus.ACCEPTED)
            return
        stop_match = re.fullmatch(r"/api/books/([A-Za-z0-9_-]{8,80})/pipeline/stop", route.path)
        if stop_match:
            book_id = stop_match.group(1)
            book = find_book(book_id)
            event = PIPELINE_CANCEL_EVENTS.get(book_id)
            running = PIPELINE_THREADS.get(book_id)
            if not book or not event or not running or not running.is_alive():
                self.send_json({"error": "No chapter reader is currently running."}, HTTPStatus.CONFLICT)
                return
            event.set()
            cancel_active_model_response(book_id)
            pipeline = load_pipeline(book)
            for chapter in pipeline.get("chapters", []):
                if chapter.get("status") == "running":
                    chapter.update({"status": "pending", "interruptedAt": utc_now(), "error": "Stopped before completion. Resume retries this chapter."})
                for prefix in ("emotion", "tag", "smell"):
                    if chapter.get(f"{prefix}Status") == "running":
                        chapter.update({f"{prefix}Status": "pending", f"{prefix}Error": "Stopped before completion. Resume retries this chapter."})
            pipeline.update({"status": "paused", "phase": "paused", "stopRequested": False, "message": "Reader stopped. Completed chapters are safe; Resume retries the interrupted chapter.", "updatedAt": utc_now()})
            write_pipeline(book, pipeline)
            self.send_json({"stopping": False, "stopped": True, "pipeline": add_pipeline_progress(pipeline)}, HTTPStatus.OK)
            return
        pipeline_match = re.fullmatch(r"/api/books/([A-Za-z0-9_-]{8,80})/pipeline/(prepare|summarize|restart|run)", route.path)
        if pipeline_match:
            book_id = pipeline_match.group(1)
            action = pipeline_match.group(2)
            book = find_book(book_id)
            if not book:
                self.send_json({"error": "Book not found."}, HTTPStatus.NOT_FOUND)
                return
            if not pipeline_path(book):
                self.send_json({"error": "Drop this manuscript in again before starting its reading."}, HTTPStatus.CONFLICT)
                return
            pipeline = load_pipeline(book)
            running = PIPELINE_THREADS.get(book_id)
            if not running or not running.is_alive():
                if action == "run":
                    action = "summarize" if pipeline.get("chapters") else "prepare"
                if action == "restart":
                    pipeline = reset_summary_run(book, pipeline)
                    action = "summarize"
                if action == "summarize" and not extracted_chapters_path(book).exists():
                    self.send_json({"error": "Prepare the manuscript first."}, HTTPStatus.CONFLICT)
                    return
                target = prepare_manuscript_pipeline if action == "prepare" else run_summary_pipeline
                PIPELINE_CANCEL_EVENTS[book_id] = threading.Event()
                running = threading.Thread(target=target, args=(book_id,), daemon=True, name=f"bookinator-{action}-{book_id[:8]}")
                PIPELINE_THREADS[book_id] = running
                running.start()
            self.send_json({"started": True, "action": action, "pipeline": load_pipeline(book)}, HTTPStatus.ACCEPTED)
            return
        if route.path == "/api/books":
            try:
                length = int(self.headers.get("Content-Length", "0") or 0)
                if length <= 0 or length > 4 * 1024 * 1024:
                    raise ValueError("Invalid book record size.")
                payload = json.loads(self.rfile.read(length))
                if not isinstance(payload, dict) or not str(payload.get("title") or "").strip():
                    raise ValueError("A title is required.")
                prior = find_book(str(payload.get("id") or ""))
                saved = save_book(payload)
            except (ValueError, TypeError, json.JSONDecodeError) as error:
                self.send_json({"error": str(error) or "Invalid book record."}, HTTPStatus.BAD_REQUEST)
                return
            book = find_book(str(saved.get("id") or ""))
            manuscript_changed = bool(book and str(book.get("manuscriptId") or "") != str((prior or {}).get("manuscriptId") or ""))
            needs_preparation = bool(book and book.get("manuscriptId") and (manuscript_changed or not extracted_chapters_path(book).is_file()))
            if book and normalize_book_priority(book.get("priority")) == "shelved":
                book_id = str(book.get("id") or "")
                save_queue([queued_id for queued_id in load_queue() if queued_id != book_id])
                with QUEUE_LOCK:
                    QUEUE_ACTIONS.pop(book_id, None)
                    remove_queue_action(book_id)
            elif needs_preparation:
                prioritize_pipeline_action(str(book.get("id")), "prepare")
                saved = enrich_book(book)
            elif book and pipeline_is_enabled():
                action = next_pipeline_action(book, load_pipeline(book))
                if action:
                    prioritize_pipeline_action(str(book.get("id")), action)
                    saved = enrich_book(book)
            self.send_json({"book": saved, "preparationQueued": needs_preparation}, HTTPStatus.CREATED)
            return
        if route.path == "/api/books/abbreviate":
            try:
                length = int(self.headers.get("Content-Length", "0") or 0)
                payload = json.loads(self.rfile.read(length))
                title = str(payload.get("title") or "").strip()
                if not title:
                    raise ValueError("Enter a title first.")
            except (ValueError, TypeError, json.JSONDecodeError) as error:
                self.send_json({"error": str(error) or "Invalid title."}, HTTPStatus.BAD_REQUEST)
                return
            ollama = ollama_status()
            settings = load_settings()
            self.send_json(infer_title_mark(title, ollama["models"] if ollama["running"] else [], settings.get("intakeModel", "")))
            return
        if route.path == "/api/setup/pdf-reader":
            installed, message = install_pdf_reader()
            self.send_json({"installed": installed, "message": message}, HTTPStatus.OK if installed else HTTPStatus.INTERNAL_SERVER_ERROR)
            return
        if route.path == "/api/setup/ollama":
            if platform.system() != "Darwin" or not shutil.which("brew"):
                self.send_json({"error": "Automatic Ollama installation is currently available only for Homebrew-managed macOS systems.", "instructions": "ollama"}, HTTPStatus.NOT_IMPLEMENTED)
                return
            if pipeline_is_enabled():
                self.send_json({"error": "Stop the analysis queue before installing or updating Ollama so an active model response is not interrupted."}, HTTPStatus.CONFLICT)
                return
            installed = subprocess.run(["brew", "list", "--versions", "ollama"], capture_output=True, text=True, timeout=30).returncode == 0
            command = ["brew", "upgrade" if installed else "install", "ollama"]
            try:
                result = subprocess.run(command, capture_output=True, text=True, timeout=1800)
            except (OSError, subprocess.TimeoutExpired) as error:
                self.send_json({"error": f"Bookinator could not run Homebrew: {error}"}, HTTPStatus.INTERNAL_SERVER_ERROR)
                return
            if result.returncode != 0:
                detail = (result.stderr or result.stdout or "Homebrew did not explain the failure.").strip()
                self.send_json({"error": f"Homebrew could not {'update' if installed else 'install'} Ollama.", "detail": detail}, HTTPStatus.BAD_GATEWAY)
                return
            verified = ollama_status()
            self.send_json({"installed": True, "updated": installed, "version": verified.get("version"), "running": verified.get("running"), "restartRequired": not bool(verified.get("running"))})
            return
        if route.path == "/api/setup/emotion-model":
            installed, message = install_emotion_model()
            if installed and pipeline_is_enabled():
                start_global_pipeline()
            self.send_json({"installed": installed, "message": message}, HTTPStatus.OK if installed else HTTPStatus.INTERNAL_SERVER_ERROR)
            return
        if route.path == "/api/settings":
            try:
                length = int(self.headers.get("Content-Length", "0") or 0)
                payload = json.loads(self.rfile.read(length))
                role = str(payload.get("role", "intake")).strip()
                selected_model = str(payload.get("model", payload.get("intakeModel", ""))).strip()
            except (ValueError, TypeError, json.JSONDecodeError):
                self.send_json({"error": "Invalid settings."}, HTTPStatus.BAD_REQUEST)
                return
            if role not in MODEL_ROLES:
                self.send_json({"error": "Unknown model role."}, HTTPStatus.BAD_REQUEST)
                return
            available = ollama_status()["models"]
            if selected_model and selected_model not in available:
                self.send_json({"error": "Choose a model installed in Ollama."}, HTTPStatus.BAD_REQUEST)
                return
            settings = load_settings()
            settings[f"{role}Model"] = selected_model
            save_settings(settings)
            self.send_json({"saved": True, "role": role, "model": selected_model})
            return
        task_model_match = re.fullmatch(r"/api/books/([A-Za-z0-9_-]{8,80})/(reader|dossier|tags)-model", route.path)
        if task_model_match:
            book = find_book(task_model_match.group(1))
            task = task_model_match.group(2)
            if not book:
                self.send_json({"error": "Book not found."}, HTTPStatus.NOT_FOUND)
                return
            try:
                length = int(self.headers.get("Content-Length", "0") or 0)
                payload = json.loads(self.rfile.read(length))
                selected_model = str(payload.get("model", "")).strip()
            except (ValueError, TypeError, json.JSONDecodeError):
                self.send_json({"error": "Invalid task model selection."}, HTTPStatus.BAD_REQUEST)
                return
            pipeline = load_pipeline(book)
            if pipeline.get("status") in {"running", "queued"}:
                self.send_json({"error": "Stop this book’s pipeline before changing its model."}, HTTPStatus.CONFLICT)
                return
            available = ollama_status()["models"]
            if selected_model and selected_model not in available:
                self.send_json({"error": "Install this model in Ollama before assigning it to the book."}, HTTPStatus.BAD_REQUEST)
                return
            model_key = {"reader": "readerModel", "dossier": "dossierModel", "tags": "tagModel"}[task]
            if selected_model:
                pipeline[model_key] = selected_model
            else:
                pipeline.pop(model_key, None)
            pipeline["updatedAt"] = utc_now()
            write_pipeline(book, pipeline)
            workspace_model = load_settings().get({"reader": "readerModel", "dossier": "primaryModel", "tags": "tagsModel"}[task], "") or load_settings().get("readerModel", "")
            self.send_json({"saved": True, "task": task, "model": selected_model, "effectiveModel": selected_model or workspace_model})
            return
        if route.path in {"/api/models/pull", "/api/models/delete"}:
            try:
                length = int(self.headers.get("Content-Length", "0") or 0)
                payload = json.loads(self.rfile.read(length))
                model = str(payload.get("model", "")).strip()
            except (ValueError, TypeError, json.JSONDecodeError):
                self.send_json({"error": "Invalid model request."}, HTTPStatus.BAD_REQUEST)
                return
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,119}", model):
                self.send_json({"error": "Enter a valid Ollama model name."}, HTTPStatus.BAD_REQUEST)
                return
            ollama = ollama_status()
            if not ollama["running"]:
                self.send_json({
                    "error": "Ollama is not running.",
                    "model": model,
                    "kind": "ollama-offline",
                    "guidance": "Open the Ollama app, wait for it to finish starting, and try the installation again.",
                    "needsHuggingFaceToken": False,
                    "helpUrl": "https://ollama.com/download",
                }, HTTPStatus.SERVICE_UNAVAILABLE)
                return
            if route.path == "/api/models/delete":
                assigned_roles = assigned_model_roles(model, list(ollama.get("models") or []))
                if pipeline_is_enabled() and assigned_roles:
                    roles = ", ".join(assigned_roles)
                    self.send_json({"error": f"Stop the analysis queue before uninstalling {model}; Bookinator currently uses it for {roles}."}, HTTPStatus.CONFLICT)
                    return
                request = urllib.request.Request(
                    "http://127.0.0.1:11434/api/delete",
                    data=json.dumps({"name": model}).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="DELETE",
                )
                try:
                    with urllib.request.urlopen(request, timeout=120) as response:
                        response.read()
                except urllib.error.HTTPError as error:
                    try:
                        detail = error.read().decode("utf-8", errors="replace").strip()
                    except OSError:
                        detail = ""
                    self.send_json({"error": f"Ollama could not uninstall {model}. {detail}".strip()}, HTTPStatus.BAD_GATEWAY)
                    return
                except (OSError, urllib.error.URLError, TimeoutError) as error:
                    self.send_json({"error": f"Bookinator could not reach Ollama to uninstall {model}. {error}"}, HTTPStatus.BAD_GATEWAY)
                    return
                self.send_json({"installed": False, "model": model})
                return
            request = urllib.request.Request(
                "http://127.0.0.1:11434/api/pull",
                data=json.dumps({"model": model, "stream": False}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            try:
                with urllib.request.urlopen(request, timeout=1800) as response:
                    json.load(response)
            except urllib.error.HTTPError as error:
                try:
                    response_body = error.read().decode("utf-8", errors="replace")
                except OSError:
                    response_body = ""
                self.send_json(ollama_pull_error(model, error.code, response_body), HTTPStatus.BAD_GATEWAY)
                return
            except (OSError, urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
                failure = ollama_pull_error(model, None, str(error))
                failure["kind"] = "ollama-unreachable"
                failure["guidance"] = "Bookinator could not reach Ollama. Open the Ollama app, then try again."
                self.send_json(failure, HTTPStatus.BAD_GATEWAY)
                return
            self.send_json({"installed": True, "model": model})
            return
        if route.path != "/api/manuscripts/identify":
            self.send_json({"error": "Not found"}, HTTPStatus.NOT_FOUND)
            return
        content_type = self.headers.get("Content-Type", "")
        content_length = int(self.headers.get("Content-Length", "0") or 0)
        query = urllib.parse.parse_qs(route.query)
        filename = query.get("filename", ["manuscript.pdf"])[0]
        media_type = content_type.split(";", 1)[0].strip()
        suffix = Path(filename).suffix.casefold()
        if media_type != "application/pdf" and suffix not in {".txt", ".md", ".docx", ".epub"}:
            self.send_json({"error": "Bookinator currently accepts PDF, DOCX, EPUB, TXT, and Markdown manuscripts."}, HTTPStatus.UNSUPPORTED_MEDIA_TYPE)
            return
        if content_length <= 0 or content_length > MAX_PREVIEW_BYTES:
            self.send_json({"error": "Choose a source document smaller than 80 MB for this first pass."}, HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
            return
        source_bytes = self.rfile.read(content_length)
        structured_metadata: dict[str, str] = {}
        archive_image_candidates: list[dict[str, object]] = []
        try:
            if media_type == "application/pdf" or suffix == ".pdf":
                pdf_bytes = source_bytes
            else:
                if suffix in {".docx", ".epub"}:
                    structured_metadata, archive_image_candidates = archive_manuscript_metadata_and_images(source_bytes, suffix)
                    text_source = archive_manuscript_text(source_bytes, suffix)
                else:
                    text_source = source_bytes
                    structured_metadata = front_matter_metadata(source_bytes)
                pdf_bytes = text_manuscript_to_pdf(text_source)
        except (ValueError, OSError, zipfile.BadZipFile) as error:
            self.send_json({"error": str(error) or "Bookinator could not read that text manuscript."}, HTTPStatus.UNPROCESSABLE_ENTITY)
            return
        try:
            pdf_metadata, opening_text, image_candidates = extract_pdf_preview(pdf_bytes)
        except Exception:
            self.send_json({"error": "Bookinator could not prepare a readable copy of that source document."}, HTTPStatus.UNPROCESSABLE_ENTITY)
            return
        metadata = dict(pdf_metadata)
        metadata.update(structured_metadata)
        image_candidates = archive_image_candidates + image_candidates
        try:
            manuscript_id = store_manuscript(pdf_bytes, filename, source_bytes, media_type)
        except OSError:
            self.send_json({"error": "Bookinator could not save that manuscript locally."}, HTTPStatus.INTERNAL_SERVER_ERROR)
            return
        ollama = ollama_status()
        settings = load_settings()
        identity = infer_manuscript_identity(opening_text, metadata, ollama["models"] if ollama["running"] else [], settings.get("intakeModel", ""), metadata_authoritative=bool(structured_metadata))
        icon = infer_manuscript_icon(image_candidates, ollama["models"] if ollama["running"] else [], settings.get("intakeModel", ""))
        identity["title"] = identity.get("title") or title_from_filename(filename)
        identity_source = "structured-metadata" if structured_metadata else "local-model" if identity.get("model") else "pdf-metadata" if metadata else "filename"
        self.send_json({
            "title": identity.get("title", ""),
            "author": identity.get("author", ""),
            "abbreviation": identity.get("abbreviation", ""),
            "model": identity.get("model"),
            "source": identity_source,
            "pdfReaderReady": bool(opening_text or metadata),
            "icon": icon,
            "iconCandidates": len(image_candidates),
            "manuscriptId": manuscript_id,
            "pagesInspected": min(10, len(opening_text.split("--- PAGE BREAK ---"))) if opening_text else 0,
        })


def start_background_services() -> threading.Thread:
    """Wake durable background work without delaying the HTTP listener."""

    def wake_pipeline() -> None:
        try:
            start_global_pipeline()
        except Exception as error:
            print(f"Bookinator could not restore the analysis queue: {error}", file=sys.stderr)

    thread = threading.Thread(
        target=wake_pipeline,
        daemon=True,
        name="bookinator-pipeline-startup",
    )
    thread.start()
    return thread


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve Bookinator on this Mac")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=4877)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), BookinatorHandler)
    print(f"Bookinator local server listening on http://{args.host}:{args.port}")
    # A stopped pipeline is a runtime choice, not a durable launch mode. Wake
    # eligible library work automatically, but never make HTTP availability
    # wait for queue restoration or a slow local-model check.
    start_background_services()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
