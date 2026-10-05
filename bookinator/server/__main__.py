from __future__ import annotations

import argparse
import base64
import binascii
import copy
import difflib
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
import textwrap
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zipfile
import unicodedata
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
APP_ROOT = ROOT / "src"
DOCS_ROOT = ROOT / "docs"
COMMONS_UI_ROOT = ROOT / "node_modules" / "@inator" / "ui" / "src"
COMMONS_ENGINE_ROOT = ROOT / "node_modules" / "@inator" / "engine" / "src"
LOCAL_PACKAGES = ROOT / ".bookinator" / "packages"
DATA_ROOT = Path(os.environ.get("BOOKINATOR_DATA_DIR", ROOT / ".bookinator"))
SETTINGS_PATH = DATA_ROOT / "settings.json"
QUEUE_PATH = DATA_ROOT / "pipeline-queue.json"
QUEUE_ACTIONS_PATH = DATA_ROOT / "pipeline-actions.json"
TASK_PAUSES_PATH = DATA_ROOT / "pipeline-task-pauses.json"
DEFERRED_REFRESHES_PATH = DATA_ROOT / "deferred-analysis-refreshes.json"
CURRENT_RUN_PATH = DATA_ROOT / "pipeline-current-run.json"
BOOKS_ROOT = DATA_ROOT / "books"
REPORTS_ROOT = DATA_ROOT / "reports"
LIBRARY_PATH = DATA_ROOT / "library.json"
LIBRARY_LOCK = threading.Lock()
REPORTS_LOCK = threading.Lock()
ANNOTATIONS_LOCK = threading.Lock()
PIPELINE_WRITE_LOCK = threading.RLock()
PIPELINE_THREADS: dict[str, threading.Thread] = {}
PIPELINE_CANCEL_EVENTS: dict[str, threading.Event] = {}
# Stage runners historically remove PIPELINE_CANCEL_EVENTS when each elementary
# call returns. Keep a second chapter-pass owner so per-book Stop survives that
# handoff and cannot be mistaken for permission to begin the next stage.
BOOK_PIPELINE_CANCEL_EVENTS: dict[str, threading.Event] = {}
ACTIVE_MODEL_RESPONSES: dict[str, object] = {}
ACTIVE_MODEL_RESPONSES_LOCK = threading.Lock()
MODEL_RESPONSE_TELEMETRY: dict[str, dict[str, object]] = {}
STRUCTURED_MODEL_LOCK = threading.RLock()
LAST_STRUCTURED_MODEL = ""
QUEUE_THREAD: threading.Thread | None = None
QUEUE_CANCEL_EVENT = threading.Event()
QUEUE_ACTIONS: dict[str, str] = {}
QUEUE_LOCK = threading.Lock()
QUEUE_WAKE_PENDING = False
CURRENT_RUN_LOCK = threading.RLock()
QUEUE_CURRENT_TASK: dict[str, str] = {}
DEFERRED_ANALYSIS_REFRESHES: dict[str, list[tuple[str, int]]] = {}
EXPLICIT_QUEUE_ACTIONS = {
    "prepare", "summarize", "restart", "whole-summary", "whole-dossier", "questions",
    "emotions", "emotion-restart", "tags", "tag-restart", "smells", "smell-restart",
    "dossiers", "dossier-restart", "chapter-pipeline", "gliner-signals", "cumulative-context", "llm-review", "whole-llm-review",
    "deferred-refresh", "deferred-retry-failed",
}
PAUSABLE_PIPELINE_ACTIONS = {
    "summarize", "whole-summary", "dossiers", "whole-dossier", "questions",
    "gliner-signals", "cumulative-context", "llm-review", "whole-llm-review", "emotions", "tags", "smells",
}
BOOK_PRIORITY_ORDER = {"high": 0, "normal": 1, "low": 2, "shelved": 3}
PIPELINE_SNAPSHOT_SCHEMA = "inator.pipeline-snapshot.v1"
PIPELINE_CONTROL_INTENT_SCHEMA = "inator.pipeline-control-intent.v1"
PIPELINE_PRODUCT_COMMAND_SCHEMA = "bookinator.pipeline-product-command.v1"
PIPELINE_RUN_BASIS_VERSION = "bookinator-atomic-operation-v1"
PIPELINE_PROJECT_PRIORITIES = {"high": "high", "normal": "normal", "low": "low", "shelved": "deferred"}
PIPELINE_TASK_DEFINITIONS = (
    {"action": "gliner-signals", "stageId": "gliner-signals", "label": "GLiNER signals", "optional": True},
    {"action": "summarize", "stageId": "summaries", "label": "Chapter summaries"},
    {"action": "whole-summary", "resultKey": "wholeBookSummary", "label": "Whole-book summary"},
    {"action": "dossiers", "stageId": "dossiers", "label": "Chapter dossiers"},
    {"action": "whole-dossier", "resultKey": "wholeBookDossier", "label": "Whole-book dossier"},
    {"action": "questions", "resultKey": "questionTracker", "label": "Questions & payoffs"},
    {"action": "cumulative-context", "stageId": "cumulative-context", "label": "Cumulative context", "optional": True},
    {"action": "llm-review", "stageId": "llm-review", "label": "LLM Review", "optional": True},
    {"action": "whole-llm-review", "stageId": "whole-book-llm-review", "resultKey": "wholeBookLlmReview", "label": "Whole-book LLM Review", "optional": True},
    {"action": "emotions", "stageId": "emotions", "label": "Chapter emotions"},
    {"action": "tags", "stageId": "tags", "label": "Chapter tags"},
    {"action": "smells", "stageId": "smells", "label": "Smells"},
)
if LOCAL_PACKAGES.exists():
    sys.path.insert(0, str(LOCAL_PACKAGES))
from bookinator.prose_cruft import analyze as analyze_prose_smells
MAX_PREVIEW_BYTES = 80 * 1024 * 1024
MODEL_ROLES = {
    "primary": "Primary reader",
    "fast": "Fast intake & utilities",
}
MODEL_CATALOG = [
    {"tag": "qwen3.8:27b", "sizeGb": 18, "tier": "recommended", "label": "Qwen 3.8 editor", "use": "Primary chapter reading, whole-book synthesis, and editorial analysis", "hf": "https://huggingface.co/Qwen/Qwen3.8-27B"},
]
API_FEATURES = {
    "chapterMapApproval": 1,
    "chapterMapEditing": 1,
    "provisionalAnalysis": 1,
    "globalPriorityQueue": 1,
    "chapterEmotions": 1,
    "chapterTags": 1,
    "chapterSmells": 1,
    "reviewerAnnotations": 2,
    "reviewerSignoff": 1,
    "llmReview": 1,
    "llmReviewCandidatePromotion": 2,
    "shadowHeadingDiagnostic": 1,
}
BUNDLE_SCHEMA = "bookinator-project-v2"
MAX_BUNDLE_BYTES = 1024 * 1024 * 1024
MAX_BUNDLE_EXPANDED_BYTES = 4 * 1024 * 1024 * 1024


class ImportTitleCollision(ValueError):
    def __init__(self, collisions: list[dict[str, object]]):
        super().__init__("Choose a unique title before adding this book to the library.")
        self.collisions = collisions

EMOTION_MODEL_ID = "j-hartmann/emotion-english-distilroberta-base"
GLINER_MODEL_ID = "fastino/gliner2.5-small-v1"
GLINER_SCHEMA_VERSION = "bookinator-gliner-chapter-signals-v1"
EMOTION_SCHEMA_VERSION = "bookinator-emotion-v1"
EMOTION_LABELS = ("anger", "disgust", "fear", "joy", "neutral", "sadness", "surprise")
TAG_SCHEMA_VERSION = "bookinator-chapter-tags-v2"
TAG_TAXONOMY_VERSION = "bookinator-chapter-signals-v2"
TAG_PROMPT_VERSION = "chapter-tags-v6"
SMELL_SCHEMA_VERSION = "bookinator-smells-v2"
SMELL_POLICY_VERSION = "smell-routing-v1"
SMELL_PROMPT_VERSION = "smell-review-v2"
SUMMARY_PROMPT_VERSION = "chapter-summary-v6"
DOSSIER_PROMPT_VERSION = "chapter-dossier-v7"
CHAPTER_READING_PROMPT_VERSION = "chapter-reading-v5"
CHAPTER_READING_CONSISTENCY_VERSION = "chapter-reading-consistency-v4"
ANNOTATION_SCHEMA_VERSION = "bookinator-annotation-v2"
REVIEWER_SIGNOFF_SCHEMA_VERSION = "bookinator-reviewer-signoff-v1"
ANNOTATION_CATEGORIES = ("editorial", "clarity", "character", "continuity", "plot", "prose", "question", "praise")
QUESTION_FAMILIES = (
    "motivation", "causality", "character_knowledge", "relationship_change",
    "thematic_consequence", "reader_expectation", "setup_payoff", "factual_continuity",
)
LLM_REVIEW_PROMPT_VERSION = "llm-review-v12"
WHOLE_BOOK_LLM_REVIEW_PROMPT_VERSION = "whole-book-llm-review-v1"
CUMULATIVE_CONTEXT_PROMPT_VERSION = "cumulative-context-ledger-v2"
CUMULATIVE_CONTEXT_REBASE_INTERVAL = 5
LLM_REVIEW_DIMENSIONS = (
    "narrative_engagement", "character_likability", "character_relatability",
    "clarity", "stakes_and_tension", "coherence_and_continuity",
    "voice_and_distinctiveness", "emotional_impact", "genre_and_audience_fit",
    "saleability",
)
LLM_REVIEW_SPECIALIST_LENSES: tuple[tuple[str, str], ...] = (
    ("viewpoint", "viewpoint control, information access, distance, and unintended drift"),
    ("payoff", "setup, delayed answers, earned revelations, and promises this chapter advances or neglects"),
    ("structure", "scene purpose, pacing, escalation, transitions, and whether the chapter materially changes the story"),
    ("audience", "genre promise, audience expectations, tonal contract, accessibility, and productive versus accidental difficulty"),
)
TAG_FAMILIES: dict[str, tuple[str, ...]] = {
    "prose_mode": ("action", "dialogue", "exposition", "description", "introspection", "narrative_summary", "investigation"),
    "chapter_function": ("orientation", "setup", "escalation", "complication", "discovery", "revelation", "confrontation", "relationship_change", "reversal", "setback", "payoff", "climax", "aftermath", "resolution", "transition", "travel"),
    "reader_dynamics": ("withheld_information", "suspense", "tension", "stakes", "urgency", "goal_progress", "story_state_change", "revelation_density", "causal_importance", "chapter_end_propulsion"),
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
    "gliner-signals": ("chapter-archive",),
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
    "cumulative-context": ("summaries", "dossiers"),
    "llm-review": ("cumulative-context",),
    "whole-book-llm-review": ("llm-review",),
}

# This is the authored-chapter work order inside one book. New chapter-scoped
# passes (tags, cruft checks, and similar work) belong here, with their inputs
# declared above, rather than in another book-wide loop.
CHAPTER_PIPELINE_STAGE_ORDER: tuple[str, ...] = (
    "gliner-signals", "summaries", "dossiers", "llm-review", "cumulative-context", "emotions", "tags", "smells",
)

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
        "payloadFields": ("sequence", "number", "title", "chapterTitle", "summary", "keyPoints", "endingState", "newQuestions", "questionDetails", "promptVersion", "model", "completedAt"),
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
    "review": {
        "action": "whole-llm-review",
        "dependencyStage": "whole-book-llm-review",
        "stageId": "whole-book-llm-review",
        "resultKey": "wholeBookLlmReview",
        "collection": "chapters",
        "statusField": "llmReviewStatus",
        "payloadFields": ("sequence", "number", "title", "chapterTitle", "llmReview", "llmReviewModel", "llmReviewCompletedAt"),
        "promptVersion": WHOLE_BOOK_LLM_REVIEW_PROMPT_VERSION,
        "excludeFrontMatter": True,
    },
}

PIPELINE_STAGE_DEFINITIONS: dict[str, tuple[str, str]] = {
    "gliner-signals": ("GLiNER signals", "Extract fast source-anchored entity and classification candidates before the chapter reader."),
    "emotions": ("Chapter emotions", "Score the recognizable emotional texture of every chapter with the local Hartmann model."),
    "tags": ("Chapter tags", "Apply the fixed evidence-bearing editorial taxonomy with the assigned local model."),
    "smells": ("Smells", "Find source-linked prose problems locally, then ask the assigned editor model which candidates are worth showing."),
    "cumulative-context": ("Cumulative context", "Carry forward an evidence-linked story state and rebase it from saved chapter evidence every five chapters."),
    "llm-review": ("LLM Review", "Generate optional machine-authored editorial proposals and qualified chapter-level review evidence for human consideration."),
    "whole-book-llm-review": ("Whole-book LLM Review", "Synthesize the completed chapter reviews into one reconciled editorial view of the book."),
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


def remove_legacy_prose_analysis(pipeline: dict[str, object]) -> bool:
    """Permanently remove the retired Gemma Prose pass from older ledgers."""
    changed = False
    stages = pipeline.get("stages")
    if isinstance(stages, list):
        retained = [
            stage for stage in stages
            if not (
                isinstance(stage, dict)
                and (
                    str(stage.get("id") or "").strip().casefold() == "prose"
                    or str(stage.get("label") or "").strip().casefold() == "prose"
                )
            )
        ]
        if len(retained) != len(stages):
            stages[:] = retained
            changed = True
    for key in list(pipeline):
        if str(key).casefold().startswith("prose"):
            pipeline.pop(key, None)
            changed = True
    for chapter in pipeline.get("chapters", []):
        if not isinstance(chapter, dict):
            continue
        for key in list(chapter):
            if str(key).casefold().startswith("prose"):
                chapter.pop(key, None)
                changed = True
    return changed


def ensure_signal_stages(pipeline: dict[str, object]) -> None:
    """Migrate older ledgers without creating a second UI/backend contract."""
    repaired_setup: set[str] = set()
    stages = pipeline.setdefault("stages", [])
    existing = {str(stage.get("id") or "") for stage in stages}
    dossier_index = next((index for index, stage in enumerate(stages) if stage.get("id") == "dossiers"), len(stages))
    additions = []
    for stage_id in ("gliner-signals", "emotions", "tags", "smells"):
        if stage_id not in existing:
            label, detail = PIPELINE_STAGE_DEFINITIONS[stage_id]
            additions.append({"id": stage_id, "label": label, "status": "pending", "detail": detail})
    stages[dossier_index:dossier_index] = additions
    # A migrated ledger may already contain every other signal stage. Keep the
    # new pre-read scaffold in its semantic position instead of appending it
    # near the end of the chapter pipeline.
    gliner_index = next((index for index, stage in enumerate(stages) if stage.get("id") == "gliner-signals"), None)
    summary_index = next((index for index, stage in enumerate(stages) if stage.get("id") == "summaries"), None)
    if gliner_index is not None and summary_index is not None and gliner_index > summary_index:
        gliner_stage = stages.pop(gliner_index)
        summary_index = next(index for index, stage in enumerate(stages) if stage.get("id") == "summaries")
        stages.insert(summary_index, gliner_stage)
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
        preferred = configured_primary_model(settings)
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


def ensure_llm_review_stages(book: dict[str, object], pipeline: dict[str, object]) -> bool:
    """Expose optional review work only for books whose owner opted in."""
    stages = pipeline.setdefault("stages", [])
    optional_ids = {"cumulative-context", "llm-review", "whole-book-llm-review"}
    if not book.get("llmReviewEnabled"):
        retained = [stage for stage in stages if str(stage.get("id") or "") not in optional_ids]
        changed = len(retained) != len(stages)
        stages[:] = retained
        return changed
    changed = False
    checkpoint_locked = bool(pipeline.get("developmentCheckpointLocked")) or pipeline.get("phase") == "development-checkpoint"
    try:
        checkpoint_limit = int(pipeline.get("developmentAnalysisLimit") or 0)
        preserved_through = int(pipeline.get("developmentPreservedThroughSequence") or 0)
    except (TypeError, ValueError):
        checkpoint_limit = preserved_through = 0
    if checkpoint_locked:
        preserved_through = max(preserved_through, checkpoint_limit)
    if checkpoint_locked and not pipeline.get("developmentCheckpointLocked"):
        pipeline["developmentCheckpointLocked"] = True
        changed = True
    # A development boundary protects the comparison baseline even while the
    # next specimen is open and running. The durable child artifacts are the
    # authority for that baseline; an older server or an interrupted worker may
    # have left an in-memory chapter status pending without damaging the saved
    # result itself.
    if preserved_through:
        for chapter in pipeline.get("chapters", []):
            sequence = int(chapter.get("sequence") or chapter.get("number") or 0)
            if not sequence or sequence > preserved_through or strip_markdown_heading(chapter.get("title")).casefold() == "front matter":
                continue
            context_artifact = read_json_artifact(cumulative_context_path(book, sequence))
            if context_artifact.get("status") == "complete" and isinstance(context_artifact.get("context"), dict):
                context_needs_restore = chapter.get("contextStatus") != "complete" or not isinstance(chapter.get("context"), dict)
                context = context_artifact["context"]
                chapter.update({
                    "contextStatus": "complete", "context": context,
                    "contextSummary": str(context.get("storySoFar") or ""),
                    "contextModel": context_artifact.get("model"),
                    "contextStartedAt": context_artifact.get("startedAt"),
                    "contextCompletedAt": context_artifact.get("completedAt"),
                    "contextDurationSeconds": context_artifact.get("durationSeconds"),
                    "contextInputSignature": context_artifact.get("inputSignature"),
                    "contextRebased": context_artifact.get("rebased"),
                })
                changed = context_needs_restore or changed
            review_artifact = read_json_artifact(llm_review_result_path(book, sequence))
            if review_artifact.get("status") == "complete" and isinstance(review_artifact.get("result"), dict):
                review_needs_restore = chapter.get("llmReviewStatus") != "complete" or not isinstance(chapter.get("llmReview"), dict)
                chapter.update({
                    "llmReviewStatus": "complete", "llmReview": review_artifact["result"],
                    "llmReviewModel": review_artifact.get("model"),
                    "llmReviewStartedAt": review_artifact.get("startedAt"),
                    "llmReviewCompletedAt": review_artifact.get("completedAt"),
                    "llmReviewDurationSeconds": review_artifact.get("durationSeconds"),
                    "llmReviewInputSignature": review_artifact.get("inputSignature"),
                })
                changed = review_needs_restore or changed
    for stage_id in ("cumulative-context", "llm-review", "whole-book-llm-review"):
        if any(item.get("id") == stage_id for item in stages):
            continue
        label, detail = PIPELINE_STAGE_DEFINITIONS[stage_id]
        stages.append({"id": stage_id, "label": label, "status": "pending", "detail": detail, "workspaceTab": "llm-review" if stage_id == "whole-book-llm-review" else stage_id})
        changed = True
    review_stage = next((item for item in stages if item.get("id") == "llm-review"), None)
    whole_review_stage = next((item for item in stages if item.get("id") == "whole-book-llm-review"), None)
    context_stage = next((item for item in stages if item.get("id") == "cumulative-context"), None)
    if whole_review_stage and whole_review_stage.get("workspaceTab") != "llm-review":
        whole_review_stage["workspaceTab"] = "llm-review"
        changed = True
    stale_context = False
    for chapter in pipeline.get("chapters", []):
        if chapter.get("contextStatus") != "complete":
            continue
        sequence = int(chapter.get("sequence") or chapter.get("number") or 0)
        if sequence and sequence <= preserved_through:
            continue
        artifact = read_json_artifact(cumulative_context_path(book, sequence)) if sequence else {}
        if artifact.get("schema") == CUMULATIVE_CONTEXT_PROMPT_VERSION:
            continue
        stale_context = True
        break
    if stale_context and not checkpoint_locked:
        for chapter in pipeline.get("chapters", []):
            sequence = int(chapter.get("sequence") or chapter.get("number") or 0)
            if sequence and sequence <= preserved_through:
                continue
            if strip_markdown_heading(chapter.get("title")).casefold() == "front matter":
                continue
            chapter["contextStatus"] = "pending"
            chapter["llmReviewStatus"] = "pending"
            for key in (
                "context", "contextSummary", "contextStartedAt", "contextCompletedAt", "contextDurationSeconds",
                "contextInputSignature", "contextModel", "contextRebased", "contextError",
                "llmReview", "llmReviewStartedAt", "llmReviewCompletedAt", "llmReviewDurationSeconds",
                "llmReviewInputSignature", "llmReviewModel", "llmReviewError",
            ):
                chapter.pop(key, None)
        for stage in (context_stage, review_stage, whole_review_stage):
            if stage:
                stage.update({"status": "pending", "detail": "The cumulative-memory contract changed; rebuild context and its dependent machine reviews."})
                for key in ("startedAt", "completedAt", "durationSeconds", "error"):
                    stage.pop(key, None)
        changed = True
    for chapter in pipeline.get("chapters", []):
        if chapter.get("llmReviewStatus") != "complete":
            continue
        sequence = int(chapter.get("sequence") or chapter.get("number") or 0)
        if sequence and sequence <= preserved_through:
            continue
        artifact = read_json_artifact(llm_review_result_path(book, sequence)) if sequence else {}
        if artifact.get("schema") == LLM_REVIEW_PROMPT_VERSION:
            continue
        if checkpoint_locked:
            continue
        chapter["llmReviewStatus"] = "pending"
        for key in (
            "llmReview", "llmReviewStartedAt", "llmReviewCompletedAt", "llmReviewDurationSeconds",
            "llmReviewInputSignature", "llmReviewModel", "llmReviewError",
        ):
            chapter.pop(key, None)
        if review_stage:
            review_stage.update({
                "status": "pending",
                "detail": "The review prompt or output contract changed; rebuild the machine proposals from prior context plus canonical chapter text.",
            })
            review_stage.pop("completedAt", None)
        if whole_review_stage:
            whole_review_stage.update({"status": "pending", "detail": "Waiting for the refreshed chapter reviews before whole-book synthesis."})
            for key in ("startedAt", "completedAt", "durationSeconds", "error"):
                whole_review_stage.pop(key, None)
        changed = True
    record_pipeline_dependencies(pipeline)
    return changed


def reconcile_orphaned_child_runs(pipeline: dict[str, object]) -> bool:
    """A child cannot remain running after its owning stage has stopped."""
    changed = False
    stages = {str(stage.get("id") or ""): stage for stage in pipeline.get("stages", [])}
    now = utc_now()
    active_stage_ids = ({
        "summarizing": {"summaries"},
        "dossiers": {"dossiers"},
        "chapter-reading": {"summaries", "dossiers", "llm-review"},
        "chapter-reading-consistency": {"summaries", "dossiers", "llm-review"},
        "emotions": {"emotions"},
        "tags": {"tags"},
        "smells": {"smells"},
        "cumulative-context": {"cumulative-context"},
        "llm-review": {"llm-review"},
    }.get(str(pipeline.get("phase") or ""), set()) if pipeline.get("status") == "running" else set())
    # A stage is serial by contract. Multiple running children can only be
    # stale ledger state (most commonly two local servers sharing one data
    # directory). Preserve the newest marker and make every older one safely
    # retryable instead of presenting impossible simultaneous activity.
    child_fields = {
        "summaries": ("status", "error", "startedAt"),
        "emotions": ("emotionStatus", "emotionError", "emotionStartedAt"),
        "tags": ("tagStatus", "tagError", "tagStartedAt"),
        "smells": ("smellStatus", "smellError", "smellStartedAt"),
        "cumulative-context": ("contextStatus", "contextError", "contextStartedAt"),
        "llm-review": ("llmReviewStatus", "llmReviewError", "llmReviewStartedAt"),
    }
    # A successful retry supersedes its earlier diagnostic. Older servers
    # sometimes left the error field beside a complete result, causing the UI
    # to present a real saved artifact as if it were still broken.
    for status_field, error_field, _started_field in child_fields.values():
        for chapter in pipeline.get("chapters", []):
            if chapter.get(status_field) == "complete" and error_field in chapter:
                chapter.pop(error_field, None)
                changed = True
    for chunk in pipeline.get("chunks", []):
        if chunk.get("dossierStatus") == "complete" and "dossierError" in chunk:
            chunk.pop("dossierError", None)
            changed = True
    for stage_id, (status_field, _error_field, _started_field) in child_fields.items():
        stage = stages.get(stage_id, {})
        if stage.get("status") not in {"failed", "warning"} and not any(chapter.get(status_field) == "failed" for chapter in pipeline.get("chapters", [])) and "error" in stage:
            stage.pop("error", None)
            changed = True
    for stage_id, (status_field, error_field, started_field) in child_fields.items():
        if stage_id not in active_stage_ids:
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
    if "dossiers" in active_stage_ids:
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
        if stage.get("status") != "running" or stage_id in active_stage_ids:
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
        for key in ("startedAt", "completedAt", "durationSeconds"):
            stage.pop(key, None)
    if "question-tracker" in invalidated:
        previous = pipeline.get("questionTracker") if isinstance(pipeline.get("questionTracker"), dict) else {}
        pipeline["questionTracker"] = {**previous, "status": "blocked", "dependsOn": list(PIPELINE_STAGE_DEPENDENCIES["question-tracker"]), "detail": detail}
    if "cumulative-context" in invalidated:
        for chapter in pipeline.get("chapters", []):
            chapter["contextStatus"] = "pending"
            chapter.pop("contextError", None)
    if "llm-review" in invalidated:
        for chapter in pipeline.get("chapters", []):
            chapter["llmReviewStatus"] = "pending"
            chapter.pop("llmReviewError", None)
    if "whole-book-llm-review" in invalidated:
        previous = pipeline.get("wholeBookLlmReview") if isinstance(pipeline.get("wholeBookLlmReview"), dict) else {}
        pipeline["wholeBookLlmReview"] = {
            **previous,
            "status": "blocked",
            "dependsOn": list(PIPELINE_STAGE_DEPENDENCIES["whole-book-llm-review"]),
            "detail": detail,
        }
    return invalidated


def load_library_records() -> list[dict[str, object]]:
    """Read durable book metadata without hydrating every analysis ledger."""
    try:
        payload = json.loads(LIBRARY_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return [item for item in payload if isinstance(item, dict)] if isinstance(payload, list) else []


def load_library() -> list[dict[str, object]]:
    return [enrich_book(item) for item in load_library_records()]


def library_pipeline_snapshot(book: dict[str, object]) -> dict[str, object]:
    """Read the saved ledger without re-verifying its derived artifact tree.

    The library needs counts and statuses, not a repair pass over every saved
    chapter and dossier. Analysis workers and book workspaces continue to use
    ``load_pipeline`` and therefore retain the stronger verification contract.
    """
    path = pipeline_path(book)
    if not path:
        return new_pipeline(book)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return new_pipeline(book)
    return payload if isinstance(payload, dict) else new_pipeline(book)


def book_for_library_client(book: dict[str, object]) -> dict[str, object]:
    """Replace an embedded image with its lazy local URL for shelf views."""
    visible = dict(book)
    icon = book.get("icon") if isinstance(book.get("icon"), dict) else None
    if icon and icon.get("kind") == "image" and str(icon.get("value") or "").startswith("data:image/"):
        visible["icon"] = {
            **{key: value for key, value in icon.items() if key != "value"},
            "value": f"/api/books/{urllib.parse.quote(str(book.get('id') or ''))}/icon",
            "lazy": True,
        }
    return visible


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


def source_has_fixed_pagination(book: dict[str, object]) -> bool:
    """Only a preserved PDF has stable page coordinates worth showing."""
    return str(manuscript_metadata(str(book.get("manuscriptId") or "")).get("sourceFormat") or "").upper() == "PDF"


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
    child_payload = [{field: item.get(field) for field in payload_fields} for item in children]
    payload = {"promptVersion": definition.get("promptVersion"), "children": child_payload} if definition.get("promptVersion") else child_payload
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def load_pipeline_task_pauses() -> dict[str, list[str]]:
    try:
        payload = json.loads(TASK_PAUSES_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    return {
        str(book_id): sorted({str(action) for action in actions if str(action) in PAUSABLE_PIPELINE_ACTIONS})
        for book_id, actions in payload.items() if isinstance(book_id, str) and isinstance(actions, list)
    }


def save_pipeline_task_pauses(pauses: dict[str, list[str]]) -> None:
    TASK_PAUSES_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {book_id: sorted(set(actions)) for book_id, actions in pauses.items() if actions}
    temporary = TASK_PAUSES_PATH.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    temporary.replace(TASK_PAUSES_PATH)


def paused_pipeline_actions(book_id: str) -> set[str]:
    return set(load_pipeline_task_pauses().get(str(book_id), []))


def set_pipeline_action_paused(book_id: str, action: str, paused: bool) -> list[str]:
    if action not in PAUSABLE_PIPELINE_ACTIONS:
        raise ValueError("Choose a pipeline task that can be paused.")
    pauses = load_pipeline_task_pauses()
    actions = set(pauses.get(book_id, []))
    actions.add(action) if paused else actions.discard(action)
    if actions:
        pauses[book_id] = sorted(actions)
    else:
        pauses.pop(book_id, None)
    save_pipeline_task_pauses(pauses)
    return sorted(actions)


def stage_rollup_action(pipeline: dict[str, object], paused_actions: set[str] | None = None) -> str:
    """Return the first eligible stale/missing rollup without retrying failures."""
    paused = paused_actions if paused_actions is not None else paused_pipeline_actions(str(pipeline.get("bookId") or ""))
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
        action = str(definition["action"])
        if action not in paused:
            return action
    return ""


def latest_completed_rollup_result(
    pipeline: dict[str, object], result_key: str, history_key: str,
) -> dict[str, object] | None:
    """Return the last usable rollup while a replacement is pending or running."""
    current = pipeline.get(result_key) if isinstance(pipeline.get(result_key), dict) else {}
    history = pipeline.get(history_key) if isinstance(pipeline.get(history_key), list) else []
    candidates = [current.get("previousResult"), *reversed(history)]
    for candidate in candidates:
        if not isinstance(candidate, dict) or candidate.get("status") != "complete":
            continue
        if not any(str(candidate.get(field) or "").strip() for field in ("summary", "synopsis", "content", "overallAssessment")):
            continue
        result = dict(candidate)
        result.pop("previousResult", None)
        return result
    return None


def development_limited_items(
    pipeline: dict[str, object], items: list[dict[str, object]], sequence_field: str,
) -> list[dict[str, object]]:
    """Apply an explicit development-run boundary without falsifying statuses."""
    try:
        limit = int(pipeline.get("developmentAnalysisLimit") or 0)
    except (TypeError, ValueError):
        limit = 0
    if limit < 1:
        return list(items)
    return [
        item for item in items
        if int(item.get(sequence_field) or item.get("number") or 0) <= limit
    ]


def advance_development_checkpoint(
    pipeline: dict[str, object], sequence: int, label: str,
) -> dict[str, object]:
    """Open exactly the next bounded specimen without invalidating the baseline."""
    current = int(pipeline.get("developmentAnalysisLimit") or 0)
    if current < 1 or sequence <= current:
        raise ValueError("Advance the development checkpoint to a later section.")
    pipeline.update({
        "developmentPreservedThroughSequence": max(current, int(pipeline.get("developmentPreservedThroughSequence") or 0)),
        "developmentAnalysisLimit": sequence,
        "developmentAnalysisLimitLabel": label,
        "developmentCheckpointLocked": False,
        "status": "ready", "phase": "ready", "stopRequested": False,
        "message": f"Development run advanced to {label}; earlier comparison artifacts remain preserved.",
        "updatedAt": utc_now(),
    })
    for key in ("queuedAction", "completedAt", "error", "workerPid"):
        pipeline.pop(key, None)
    pipeline.pop("developmentAnalysisLabel", None)  # Legacy field; do not expose a contradictory checkpoint name.
    return pipeline


def next_pipeline_action(book: dict[str, object], pipeline: dict[str, object]) -> str:
    """Return the next safe automatic pass, without endlessly retrying failures."""
    if not book.get("manuscriptId"):
        return ""
    # Paused is a durable scheduling decision, not merely presentation state.
    # Only an explicit Continue/Prioritize request may move the ledger back to
    # queued. Without this gate a stopped book reappears in the automatic queue
    # after a server restart, once its in-memory cancellation token is gone.
    if pipeline.get("status") == "paused" and pipeline.get("phase") == "paused":
        return ""
    book_id = str(book.get("id") or "")
    book_cancel = BOOK_PIPELINE_CANCEL_EVENTS.get(book_id)
    if book_cancel and book_cancel.is_set():
        return ""
    if pipeline.get("ledgerReadError"):
        return ""
    stages = {str(stage.get("id") or ""): str(stage.get("status") or "pending") for stage in pipeline.get("stages", [])}
    paused = paused_pipeline_actions(str(book.get("id") or ""))
    chapters = development_limited_items(pipeline, pipeline.get("chapters", []), "sequence")
    manuscript_chapters = [chapter for chapter in chapters if strip_markdown_heading(chapter.get("title")).casefold() != "front matter"]
    if not chapters or stages.get("extraction") in {"pending", "blocked", "failed"} or stages.get("chapter-archive") in {"pending", "blocked", "failed"}:
        return "prepare"
    if normalize_book_priority(book.get("priority")) == "shelved":
        return ""
    # A bounded regression checkpoint is an explicit human inspection gate.
    # Prompt-version migration may mark saved work stale, but it must not
    # silently spend hours or destroy the before/after boundary on startup.
    if pipeline.get("developmentCheckpointLocked") or pipeline.get("phase") == "development-checkpoint":
        return ""
    # Finish the cheap preservation work, then stop before an anomalous map
    # becomes the input to hours of derived analysis. A clean map may still
    # run provisionally; this gate is reserved for structure we distrust.
    if pipeline.get("chapterMapSuspicious") and not pipeline.get("chapterMapApproved"):
        return ""
    gliner_stage = next((stage for stage in pipeline.get("stages", []) if stage.get("id") == "gliner-signals"), {})
    if gliner_stage and "gliner-signals" not in paused and gliner_stage.get("status") != "blocked" and any(
        chapter.get("glinerStatus") in {None, "pending", "ready", "paused", "running"}
        for chapter in manuscript_chapters
    ):
        return "gliner-signals"
    if "summarize" not in paused and any(chapter.get("status") in {None, "pending", "ready", "paused", "running"} for chapter in chapters):
        return "summarize"
    eligible_sequences = {int(chapter.get("sequence") or chapter.get("number") or 0) for chapter in chapters}
    chunks = [chunk for chunk in pipeline.get("chunks", []) if int(chunk.get("chapterSequence") or 0) in eligible_sequences]
    if "dossiers" not in paused and chunks and any(chunk.get("dossierStatus") in {None, "pending", "ready", "paused", "running"} for chunk in chunks):
        return "dossiers"
    # Whole-book rollups are the completion of their source stages, not
    # optional enrichment. Run them as soon as their own inputs are current,
    # before slower independent passes such as Tags and Smells.
    if rollup_action := stage_rollup_action(pipeline, paused):
        return rollup_action
    # Inferences declare their own prerequisites. Once those are current, run
    # them before unrelated chapter passes instead of displaying a misleading
    # wait on Emotions, Tags, or Smells.
    question_signature = question_tracker_input_signature(pipeline)
    question_tracker = pipeline.get("questionTracker") if isinstance(pipeline.get("questionTracker"), dict) else {}
    question_current = question_tracker_is_current(pipeline, question_tracker, question_signature)
    if (
        question_signature
        and "questions" not in paused
        and pipeline_stage_ready(pipeline, "question-tracker")
        and not (question_current and question_tracker.get("status") in {"complete", "running", "failed"})
    ):
        return "questions"
    if book.get("llmReviewEnabled"):
        context_stage = next((stage for stage in pipeline.get("stages", []) if stage.get("id") == "cumulative-context"), {})
        review_stage = next((stage for stage in pipeline.get("stages", []) if stage.get("id") == "llm-review"), {})
        for index, chapter in enumerate(manuscript_chapters):
            review_pending = chapter.get("llmReviewStatus") in {None, "pending", "ready", "paused", "running"}
            prior_context_ready = index == 0 or manuscript_chapters[index - 1].get("contextStatus") == "complete"
            if "llm-review" not in paused and not (review_stage.get("status") == "blocked" and review_stage.get("setupRequired")) and review_pending and prior_context_ready:
                return "llm-review"
            context_pending = chapter.get("contextStatus") in {None, "pending", "ready", "paused", "running"}
            sequence = int(chapter.get("sequence") or chapter.get("number") or 0)
            chapter_chunks = [chunk for chunk in chunks if int(chunk.get("chapterSequence") or 0) == sequence]
            context_inputs_ready = chapter.get("status") == "complete" and bool(chapter_chunks) and all(chunk.get("dossierStatus") == "complete" for chunk in chapter_chunks)
            if "cumulative-context" not in paused and not (context_stage.get("status") == "blocked" and context_stage.get("setupRequired")) and context_pending and context_inputs_ready:
                return "cumulative-context"
    emotion_stage = next((stage for stage in pipeline.get("stages", []) if stage.get("id") == "emotions"), {})
    if "emotions" not in paused and emotion_stage.get("status") != "blocked" and any(chapter.get("emotionStatus") in {None, "pending", "ready", "paused", "running"} for chapter in manuscript_chapters):
        return "emotions"
    if "tags" not in paused and any(chapter.get("tagStatus") in {None, "pending", "ready", "paused", "running"} for chapter in manuscript_chapters):
        return "tags"
    smell_stage = next((stage for stage in pipeline.get("stages", []) if stage.get("id") == "smells"), None)
    if "smells" not in paused and smell_stage and any(chapter.get("smellStatus") in {None, "pending", "ready", "paused", "running"} for chapter in manuscript_chapters):
        return "smells"
    return ""


def automatic_queue_books(books: list[dict[str, object]] | None = None) -> list[tuple[str, str]]:
    """Inventory every eligible book before ordering expensive work by priority."""
    candidates: list[tuple[int, int, str, str, str]] = []
    for book in books if books is not None else load_library():
        priority = normalize_book_priority(book.get("priority"))
        action = next_pipeline_action(book, load_pipeline(book))
        if not action or (priority == "shelved" and action != "prepare"):
            continue
        candidates.append((0 if action == "prepare" else 1, BOOK_PRIORITY_ORDER[priority], str(book.get("updatedAt") or book.get("createdAt") or ""), str(book.get("id") or ""), action))
    candidates.sort(key=lambda item: (item[0], item[1], item[2], item[3]))
    return [(book_id, action) for _, _, _, book_id, action in candidates if book_id]


def queue_ids_by_current_priority(book_ids: list[str]) -> list[str]:
    """Inventory unprepared books first, then apply priority without losing FIFO ties."""
    books = {str(book.get("id") or ""): book for book in load_library_records()}
    priorities = {book_id: BOOK_PRIORITY_ORDER[normalize_book_priority(book.get("priority"))] for book_id, book in books.items()}
    preparation = {
        book_id: 0 if next_pipeline_action(book, load_pipeline(book)) == "prepare" else 1
        for book_id, book in books.items()
    }
    indexed = [
        (index, book_id) for index, book_id in enumerate(book_ids)
        if book_id not in books or (
            normalize_book_priority(books[book_id].get("priority")) != "shelved"
            or next_pipeline_action(books[book_id], load_pipeline(books[book_id])) == "prepare"
        )
    ]
    indexed.sort(key=lambda item: (preparation.get(item[1], 1), priorities.get(item[1], BOOK_PRIORITY_ORDER["normal"]), item[0]))
    return [book_id for _, book_id in indexed]


def higher_priority_book_waiting(book_id: str) -> bool:
    """Return whether automatic work should yield after its current safe step."""
    library = load_library_records()
    current = next((book for book in library if str(book.get("id") or "") == book_id), None)
    if not current:
        return False
    if normalize_book_priority(current.get("priority")) == "shelved":
        return True
    current_priority = BOOK_PRIORITY_ORDER[normalize_book_priority(current.get("priority"))]
    if current_priority == BOOK_PRIORITY_ORDER["high"]:
        return False
    for candidate in library:
        candidate_id = str(candidate.get("id") or "")
        if not candidate_id or candidate_id == book_id:
            continue
        candidate_priority = BOOK_PRIORITY_ORDER[normalize_book_priority(candidate.get("priority"))]
        if candidate_priority >= current_priority:
            continue
        if next_pipeline_action(candidate, load_pipeline(candidate)):
            return True
    return False


def pipeline_activity(book: dict[str, object], pipeline: dict[str, object]) -> dict[str, object]:
    """Describe one book's current queue work for every progress surface."""
    title = str(book.get("title") or "this book")
    book_id = str(book.get("id") or "")
    phase = str(pipeline.get("phase") or "")
    status = str(pipeline.get("status") or "ready")
    stages = {str(stage.get("id") or ""): stage for stage in pipeline.get("stages", [])}
    active_chapter = next((chapter for chapter in pipeline.get("chapters", []) if chapter.get("status") == "running"), None)
    active_gliner = next((chapter for chapter in pipeline.get("chapters", []) if chapter.get("glinerStatus") == "running"), None)
    active_emotion = next((chapter for chapter in pipeline.get("chapters", []) if chapter.get("emotionStatus") == "running"), None)
    active_tag = next((chapter for chapter in pipeline.get("chapters", []) if chapter.get("tagStatus") == "running"), None)
    active_smell = next((chapter for chapter in pipeline.get("chapters", []) if chapter.get("smellStatus") == "running"), None)
    active_context = next((chapter for chapter in pipeline.get("chapters", []) if chapter.get("contextStatus") == "running"), None)
    active_review = next((chapter for chapter in pipeline.get("chapters", []) if chapter.get("llmReviewStatus") == "running"), None)
    active_chunk = next((chunk for chunk in pipeline.get("chunks", []) if chunk.get("dossierStatus") == "running"), None)
    whole_book = pipeline.get("wholeBookSummary") if isinstance(pipeline.get("wholeBookSummary"), dict) else {}

    def chapter_activity_label(value: object, sequence: object = "") -> str:
        label = strip_markdown_heading(value)
        if label.isdigit():
            return f"Chapter {label}"
        return label or (f"Chapter {sequence}" if sequence else "the next chapter")

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
    whole_review = pipeline.get("wholeBookLlmReview") if isinstance(pipeline.get("wholeBookLlmReview"), dict) else {}
    if phase == "whole-llm-review" and whole_review.get("status") == "running":
        model = str(whole_review.get("model") or stages.get("whole-book-llm-review", {}).get("model") or "the primary reader")
        return {"state": "running", "phase": phase, "bookId": book_id, "book": title, "task": "Whole-book LLM Review", "model": model, "item": "Editorial synthesis", "text": f"Bookinator · {model} is synthesizing the whole-book review for {title}"}
    if phase == "cumulative-context" and active_context:
        model = str(stages.get("cumulative-context", {}).get("model") or "the primary reader")
        item = chapter_activity_label(active_context.get("title"), active_context.get("sequence"))
        return {"state": "running", "phase": phase, "bookId": book_id, "book": title, "task": "Cumulative context", "model": model, "item": item, "text": f"Bookinator · {model} is updating story memory through {item}"}
    if phase == "llm-review" and active_review:
        model = str(stages.get("llm-review", {}).get("model") or "the primary reader")
        item = chapter_activity_label(active_review.get("title"), active_review.get("sequence"))
        return {"state": "running", "phase": phase, "bookId": book_id, "book": title, "task": "LLM Review", "model": model, "item": item, "text": f"Bookinator · {model} is reviewing {item} in context"}
    if status == "running":
        if phase == "gliner-signals":
            model = str(stages.get("gliner-signals", {}).get("model") or GLINER_MODEL_ID)
            item = chapter_activity_label((active_gliner or {}).get("title"), (active_gliner or {}).get("sequence"))
            task = "GLiNER signals"
            text = f"Bookinator · {model} is extracting source signals from {title} · {item}"
        elif phase == "summarizing":
            model = str(stages.get("summaries", {}).get("model") or "the local model")
            item = chapter_activity_label((active_chapter or {}).get("title"), (active_chapter or {}).get("sequence"))
            task = "Chapter summary"
            text = f"Bookinator · {model} is reading {title} · {item}"
        elif phase == "dossiers":
            model = str(stages.get("dossiers", {}).get("model") or "the local model")
            chapter = chapter_activity_label((active_chunk or {}).get("chapterLabel"), (active_chunk or {}).get("chapterSequence"))
            chunk = int((active_chunk or {}).get("chunkInChapter") or 1)
            item = f"{chapter}, chunk {chunk}"
            task = "Chapter dossier"
            text = f"Bookinator · {model} is building {title} · {item}"
        elif phase == "emotions":
            model = str(stages.get("emotions", {}).get("model") or EMOTION_MODEL_ID)
            item = chapter_activity_label((active_emotion or {}).get("title"), (active_emotion or {}).get("sequence"))
            task = "Emotion scoring"
            text = f"Bookinator · {model} is scoring emotions in {title} · {item}"
        elif phase == "tags":
            model = str(stages.get("tags", {}).get("model") or "the local model")
            item = chapter_activity_label((active_tag or {}).get("title"), (active_tag or {}).get("sequence"))
            task = "Chapter tags"
            text = f"Bookinator · {model} is tagging {title} · {item}"
        elif phase == "smells":
            model = str(stages.get("smells", {}).get("model") or "the local editor")
            item = chapter_activity_label((active_smell or {}).get("title"), (active_smell or {}).get("sequence"))
            task = "Prose smells"
            text = f"Bookinator · {model} is reviewing smells in {title} · {item}"
        elif phase in {"preparing", "extraction", "chapter-map", "chapter-archive", "chunking"}:
            model = ""
            item = ""
            preparation_labels = {
                "extraction": "extracting manuscript text",
                "chapter-map": "detecting chapters",
                "chapter-archive": "saving chapter objects",
                "chunking": "creating source chunks",
            }
            task = "Chapter map" if phase == "chapter-map" else "Manuscript intake"
            text = f"Bookinator is {preparation_labels.get(phase, 'preparing')} for {title}"
        else:
            model = ""
            item = ""
            task = "Pipeline work"
            text = f"Bookinator is working on {title} · {str(pipeline.get('message') or 'saving the next local step')}"
        return {"state": "running", "phase": phase, "bookId": book_id, "book": title, "task": task, "model": model, "item": item, "text": text}
    if status == "queued":
        action = str(pipeline.get("queuedAction") or next_pipeline_action(book, pipeline) or "analysis")
        labels = {"prepare": "map", "gliner-signals": "extract source signals from", "summarize": "read", "restart": "reread", "whole-summary": "merge", "whole-dossier": "reconcile the dossier for", "questions": "match questions and payoffs in", "dossiers": "build dossiers for", "dossier-restart": "rebuild dossiers for", "emotions": "score emotions in", "emotion-restart": "rescore emotions in", "tags": "tag", "tag-restart": "retag", "smells": "review prose smells in", "smell-restart": "re-review prose smells in", "cumulative-context": "build context for", "llm-review": "review", "whole-llm-review": "synthesize the review for"}
        tasks = {"prepare": "Manuscript map", "gliner-signals": "GLiNER signals", "summarize": "Chapter summary", "restart": "Chapter summaries", "whole-summary": "Whole-book summary", "whole-dossier": "Whole-book dossier", "questions": "Questions & payoffs", "dossiers": "Chapter dossier", "dossier-restart": "Chapter dossiers", "emotions": "Emotion scoring", "emotion-restart": "Emotion scoring", "tags": "Chapter tags", "tag-restart": "Chapter tags", "smells": "Smells", "smell-restart": "Smells", "cumulative-context": "Cumulative context", "llm-review": "LLM Review", "whole-llm-review": "Whole-book LLM Review"}
        return {"state": "queued", "phase": action, "bookId": book_id, "book": title, "task": tasks.get(action, "Analysis"), "text": f"Bookinator is waiting to {labels.get(action, 'analyze')} {title}"}
    return {"state": "idle", "phase": phase, "bookId": book_id, "book": title, "task": "Ready", "text": f"Bookinator is ready for the next step in {title}"}


def reset_inactive_whole_book_runs(pipeline: dict[str, object], active_phase: str) -> None:
    """Only one whole-book model response can own the single local queue."""
    interrupted_at = str(pipeline.get("updatedAt") or utc_now())
    for phase, key, detail in (
        ("whole-summary", "wholeBookSummary", "The earlier synthesis is not active. Ready to restart."),
        ("whole-dossier", "wholeBookDossier", "The earlier dossier reconciliation is not active. Ready to restart."),
        ("questions", "questionTracker", "The earlier reconciliation is not active. Ready to restart."),
        ("whole-llm-review", "wholeBookLlmReview", "The earlier review synthesis is not active. Ready to restart."),
    ):
        rollup = pipeline.get(key)
        if phase == active_phase or not isinstance(rollup, dict) or rollup.get("status") != "running":
            continue
        rollup.update({"status": "ready", "interruptedAt": rollup.get("interruptedAt") or interrupted_at, "detail": detail})
        rollup.pop("completedAt", None)
        rollup.pop("durationSeconds", None)


GLOBAL_ETA_FALLBACK_SECONDS: dict[str, float] = {
    "structure": 12,
    "gliner-signals": 5,
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
            ("gliner-signals", "glinerStatus", "glinerDurationSeconds"),
            ("summaries", "status", "durationSeconds"),
            ("emotions", "emotionStatus", "emotionDurationSeconds"),
            ("tags", "tagStatus", "tagDurationSeconds"),
            ("smells", "smellStatus", "smellDurationSeconds"),
        )
        for kind, status_key, duration_key in mappings:
            if kind in {"gliner-signals", "smells"} and kind not in stages:
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
        "gliner-signals": "GLiNER signals",
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
                ("gliner-signals", "glinerStatus", "glinerError", "glinerModel", "glinerCompletedAt"),
                ("summaries", "status", "error", "model", "completedAt"),
                ("emotions", "emotionStatus", "emotionError", "emotionModel", "emotionCompletedAt"),
                ("tags", "tagStatus", "tagError", "tagModel", "tagCompletedAt"),
                ("smells", "smellStatus", "smellError", "smellModel", "smellCompletedAt"),
            ):
                if stage in {"gliner-signals", "emotions", "tags", "smells"} and not manuscript_chapter:
                    continue
                if chapter.get(status_key) != "failed":
                    continue
                item = f"{process_labels[stage]} · {chapter_label}"
                diagnostics.append({"bookId": book_id, "book": title, "stage": stage, "resultKind": {"gliner-signals": "gliner", "summaries": "summary", "emotions": "emotion", "tags": "tag", "smells": "smell"}[stage], "resultId": chapter.get("sequence") or chapter.get("number"), "status": "failed", "item": item, "error": str(chapter.get(error_key) or "The local model did not produce a usable result."), "model": chapter.get(model_key), "completedAt": chapter.get(completed_key)})
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


def pipeline_with_reflowable_labels(book: dict[str, object] | None, pipeline: dict[str, object]) -> dict[str, object]:
    """Hide legacy synthetic page-group titles without invalidating analysis."""
    if not book or source_has_fixed_pagination(book):
        return pipeline
    authored = [
        chapter for chapter in pipeline.get("chapters", [])
        if isinstance(chapter, dict) and strip_markdown_heading(chapter.get("title")).casefold() != "front matter"
    ]
    if len(authored) != 1 or not re.fullmatch(r"Pages\s+\d+[–-]\d+", strip_markdown_heading(authored[0].get("title")), re.IGNORECASE):
        return pipeline
    visible = copy.deepcopy(pipeline)
    sequence = int(authored[0].get("sequence") or authored[0].get("number") or 0)
    for chapter in visible.get("chapters", []):
        if int(chapter.get("sequence") or chapter.get("number") or 0) == sequence:
            chapter["title"] = "Entirety"
    for chunk in visible.get("chunks", []):
        if int(chunk.get("chapterSequence") or 0) == sequence:
            chunk["chapterLabel"] = "Entirety"
    return visible


def pipeline_for_client(book_id: str, pipeline: dict[str, object]) -> dict[str, object]:
    """Present queued overrides and deferred retries without mutating the worker ledger."""
    pipeline = pipeline_with_reflowable_labels(find_book(book_id), pipeline)
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
        for phase, key in (("whole-summary", "wholeBookSummary"), ("whole-dossier", "wholeBookDossier"), ("questions", "questionTracker"), ("whole-llm-review", "wholeBookLlmReview"))
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
            if kind == "whole-llm-review":
                if isinstance(visible.get("wholeBookLlmReview"), dict):
                    visible["wholeBookLlmReview"]["status"] = "pending"
                affected_stages.add("whole-book-llm-review")
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


def pipeline_attempts_for_snapshot(unit_id: str, record: dict[str, object], status: str) -> tuple[list[dict[str, object]], str | None, str | None]:
    """Expose product attempt evidence without inventing a second ledger."""
    attempts = []
    sources = record.get("attempts")
    for index, source in enumerate(sources if isinstance(sources, list) else []):
        if not isinstance(source, dict):
            continue
        attempt_id = str(source.get("id") or source.get("attemptId") or f"{unit_id}:attempt:{index + 1}")
        attempt_status = str(source.get("status") or "unknown")
        disposition = str(source.get("disposition") or (attempt_status if attempt_status in {"stale", "superseded"} else "candidate"))
        attempts.append({
            **source,
            "id": attempt_id,
            "attemptId": attempt_id,
            "status": attempt_status,
            "disposition": disposition if disposition in {"candidate", "accepted", "stale", "superseded", "rejected"} else "candidate",
        })
    if not attempts and status in {"running", "stopping", "failed", "stale", "superseded"}:
        attempt_id = f"{unit_id}:current"
        attempts.append({
            "id": attempt_id,
            "attemptId": attempt_id,
            "status": "running" if status in {"running", "stopping"} else status,
            "startedAt": record.get("startedAt"),
            "completedAt": record.get("completedAt") or record.get("failedAt"),
            "inputSignature": record.get("inputSignature"),
            "workerId": record.get("workerId") or "bookinator-local",
            "disposition": status if status in {"stale", "superseded"} else "candidate",
        })
    attempt_ids = {str(attempt["id"]) for attempt in attempts}
    accepted = str(record.get("acceptedAttemptId") or "") or None
    current = str(record.get("currentAttemptId") or "") or None
    if not current and status in {"running", "stopping"} and attempts:
        current = str(attempts[-1]["id"])
    return attempts, accepted if accepted in attempt_ids else None, current if current in attempt_ids else None


def build_commons_pipeline_snapshot(
    books: list[dict[str, object]],
    pipeline_records: list[tuple[dict[str, object], dict[str, object]]],
    queue: list[dict[str, object]],
    current_run: dict[str, object],
    *,
    enabled: bool,
    running: bool,
) -> dict[str, object]:
    """Translate authoritative scheduler state into the Commons protocol."""
    queue_by_book = {str(item.get("bookId") or ""): item for item in queue}
    records_by_book = {str(book.get("id") or ""): pipeline for book, pipeline in pipeline_records}
    pinned_actions = load_queue_actions()
    run_books = current_run.get("books") if isinstance(current_run.get("books"), dict) else {}
    run_book_ids = {str(book_id) for book_id in run_books} or {str(book.get("id") or "") for book in books}
    projects = []
    priority_by_project: dict[str, str] = {}
    units = []
    for book in books:
        book_id = str(book.get("id") or "")
        if not book_id:
            continue
        priority = normalize_book_priority(book.get("priority"))
        priority_by_project[book_id] = priority
        projects.append({
            "id": book_id,
            "label": str(book.get("title") or "Untitled project"),
            "detail": str(book.get("author") or "Author not specified"),
            "priority": PIPELINE_PROJECT_PRIORITIES[priority],
            "deferred": priority == "shelved",
        })
        if book_id not in run_book_ids:
            continue
        compact = book.get("pipeline") if isinstance(book.get("pipeline"), dict) else {}
        ledger = records_by_book.get(book_id, {})
        next_action = str(compact.get("nextAction") or "")
        paused_actions = {str(action) for action in compact.get("pausedActions", [])}
        queued = queue_by_book.get(book_id, {})
        stages = {
            str(stage.get("id") or ""): stage
            for stage in ledger.get("stages", compact.get("stages", []))
            if isinstance(stage, dict)
        }
        active_operations: dict[str, list[dict[str, object]]] = {}
        projected_operations = pipeline_atomic_operations(book, ledger)
        for operation in projected_operations:
            if operation["status"] in {"complete", "cancelled", "superseded"}:
                continue
            active_operations.setdefault(str(operation["action"]), []).append(operation)

        definitions = list(PIPELINE_TASK_DEFINITIONS)
        if active_operations.get("prepare"):
            definitions.insert(0, {
                "action": "prepare", "label": "Manuscript inventory", "required": True,
                "detail": "Extract text, measure the manuscript, and propose its chapter map.",
            })
        for order, definition in enumerate(definitions):
            action = str(definition["action"])
            atomic_children = active_operations.get(action, [])
            result_key = str(definition.get("resultKey") or "")
            stage_id = str(definition.get("stageId") or "")
            record = ledger.get(result_key) if result_key else stages.get(stage_id)
            if action == "prepare":
                record = {"status": "pending", "detail": definition["detail"]}
            if definition.get("optional") and not record and not atomic_children:
                continue
            if not isinstance(record, dict) or record.get("disabled"):
                continue
            record_status = str(record.get("status") or "pending")
            if not atomic_children and not projected_operations and record_status not in {"complete", "warning", "cancelled"}:
                atomic_children = [{
                    "id": f"{book_id}::{action}::legacy-control",
                    "action": action,
                    "label": str(definition["label"]),
                    "detail": str(record.get("detail") or "Legacy aggregate work awaiting its first atomic ledger projection."),
                    "status": pipeline_atomic_status(record_status),
                    "sequence": 1,
                }]
            if not atomic_children:
                continue
            owns_worker = queued.get("state") == "running" and str(queued.get("action") or "") == action
            paused = action in paused_actions
            gate_waiting = action != "prepare" and bool(ledger.get("chapterMapSuspicious")) and not bool(ledger.get("chapterMapApproved"))
            if owns_worker and paused:
                status = "stopping"
            elif paused:
                status = "paused"
            elif owns_worker:
                status = "running"
            elif record_status in {"failed", "stale", "superseded"}:
                status = record_status
            elif next_action == action:
                status = "waiting"
            else:
                status = "blocked"
            unit_id = f"{book_id}::{action}"
            attempts, accepted_attempt_id, current_attempt_id = pipeline_attempts_for_snapshot(unit_id, record, status)
            children = []
            running_child_assigned = any(child.get("status") == "running" for child in atomic_children)
            for child in atomic_children:
                child_status = str(child.get("status") or "waiting")
                if paused:
                    child_status = "paused"
                elif gate_waiting:
                    child_status = "blocked"
                elif child_status not in {"failed", "stale", "superseded", "running", "stopping"}:
                    if owns_worker and not running_child_assigned:
                        child_status = "running"
                        running_child_assigned = True
                    elif owns_worker:
                        child_status = "blocked"
                    elif next_action != action:
                        child_status = "blocked"
                    else:
                        child_status = "waiting"
                children.append({
                    **child,
                    "status": child_status,
                    "method": action,
                    "provider": "local",
                })
            units.append({
                "id": unit_id,
                "workUnitId": unit_id,
                "projectId": book_id,
                "label": str(definition["label"]),
                "detail": str(record.get("detail") or ("Ready for the local worker." if status == "waiting" else "Waiting for prerequisite work.")),
                "method": action,
                "action": action,
                "provider": "local",
                "sequence": len(units) + 1,
                "rank": int(queued.get("rank") or 9999) * 100 + order,
                "status": status,
                "dependencyIds": [],
                "attempts": attempts,
                "children": children,
                "acceptedAttemptId": accepted_attempt_id,
                "currentAttemptId": current_attempt_id,
                "inputSignature": record.get("inputSignature"),
                "policy": {
                    "required": bool(definition.get("required")),
                    "paused": paused,
                    "pinned": pinned_actions.get(book_id) == action,
                    "stopAfter": False,
                    "notifyOnComplete": False,
                    "retry": "explicit",
                    "recovery": "retry-attempt" if status == "failed" else "manual",
                    "safeStopBoundary": "attempt",
                },
                "gate": {
                    "state": "waiting" if gate_waiting else "not-required",
                    "prompt": "Review and approve the proposed chapter map before derived analysis." if gate_waiting else None,
                },
                "product": {"bookId": book_id, "action": action},
            })

        queued_action = str(queued.get("action") or "")
        queued_id = f"{book_id}::{queued_action}"
        if queued_action and not any(unit["id"] == queued_id for unit in units):
            unit_status = "running" if queued.get("state") == "running" else "waiting"
            attempts, _, current_attempt_id = pipeline_attempts_for_snapshot(queued_id, {}, unit_status)
            units.append({
                "id": queued_id, "workUnitId": queued_id, "projectId": book_id,
                "label": str(queued.get("task") or queued_action.replace("-", " ").title()),
                "detail": "The local worker owns this job." if unit_status == "running" else "Ready for the local worker.",
                "method": queued_action, "action": queued_action, "provider": "local",
                "sequence": len(units) + 1, "rank": int(queued.get("rank") or 9999) * 100 + len(definitions),
                "status": unit_status, "dependencyIds": [], "attempts": attempts,
                "children": [{
                    "id": f"{queued_id}::queued", "label": str(queued.get("task") or queued_action.replace("-", " ").title()),
                    "detail": "The scheduler retained an explicit action outside the ordinary ledger projection.",
                    "method": queued_action, "provider": "local", "status": unit_status, "sequence": 1,
                }],
                "acceptedAttemptId": None, "currentAttemptId": current_attempt_id,
                "policy": {"required": False, "paused": False, "pinned": pinned_actions.get(book_id) == queued_action, "stopAfter": False, "notifyOnComplete": False, "retry": "explicit", "recovery": "manual", "safeStopBoundary": "attempt"},
                "gate": {"state": "not-required"}, "product": {"bookId": book_id, "action": queued_action},
            })

    status_order = {"running": 0, "stopping": 1, "waiting": 2, "paused": 3, "blocked": 4, "failed": 5, "stale": 6, "superseded": 7}

    def unit_sort_key(unit: dict[str, object]) -> tuple[object, ...]:
        project_priority = priority_by_project[str(unit["projectId"])]
        dispatchable = unit["status"] == "waiting" and project_priority != "shelved" and unit["gate"]["state"] not in {"waiting", "rejected"}
        tier = 0 if unit["status"] in {"running", "stopping"} else 1 if dispatchable else 2
        return tier, BOOK_PRIORITY_ORDER[project_priority], status_order.get(str(unit["status"]), 99), unit["rank"], unit["sequence"], unit["id"]

    units.sort(key=unit_sort_key)
    for sequence, unit in enumerate(units, 1):
        unit["sequence"] = sequence
    active = sum(len(unit.get("children", [])) or 1 for unit in units)
    completed = max(0, int(current_run.get("completed") or 0))
    total = completed + active
    run_id = str(current_run.get("id") or current_run.get("startedAt") or "bookinator-current-run")
    revision_basis = {
        "enabled": enabled,
        "running": running,
        "projects": [(project["id"], project["priority"]) for project in projects],
        "units": [(
            unit["id"], unit["status"], unit["rank"], unit["policy"]["paused"], unit["policy"]["pinned"], unit["gate"]["state"], unit.get("currentAttemptId"),
            [(child["id"], child["status"]) for child in unit.get("children", [])],
        ) for unit in units],
    }
    revision = int(hashlib.sha256(json.dumps(revision_basis, sort_keys=True).encode("utf-8")).hexdigest()[:12], 16)
    started = str(current_run.get("startedAt") or "")
    run_projects = max(0, int(current_run.get("bookCount") or 0))
    basis = f"{run_projects} {'project' if run_projects == 1 else 'projects'}"
    if started:
        basis += f" · started {started}"
    if int(current_run.get("deferredUnits") or 0):
        basis += f" · {int(current_run['deferredUnits'])} deferred by project policy"
    return {
        "schema": PIPELINE_SNAPSHOT_SCHEMA,
        "id": run_id,
        "runId": run_id,
        "revision": revision,
        "state": "running" if running else "ready" if enabled else "stopped",
        "projects": projects,
        "units": units,
        "progress": {"completed": completed, "total": total, "active": active, "scope": "current-run", "unit": "atomic operation", "basis": basis, "referenceAt": started or None},
        "controls": {"start": True, "stop": True, "moveTop": True, "projectPriority": True, "pause": True, "resume": True},
        "completion": {"machine": "complete" if total and completed == total else "incomplete", "review": "product-owned"},
    }


def global_pipeline_state(
    books: list[dict[str, object]] | None = None,
    pipeline_records: list[tuple[dict[str, object], dict[str, object]]] | None = None,
    *,
    wake: bool = True,
) -> dict[str, object]:
    library = books if books is not None else load_library()
    actionable = [
        book for book in library
        if book.get("pipeline", {}).get("nextAction")
        and (normalize_book_priority(book.get("priority")) != "shelved" or book.get("pipeline", {}).get("nextAction") == "prepare")
    ]
    pipeline_records = pipeline_records if pipeline_records is not None else [
        (book, add_pipeline_progress(pipeline_for_client(str(book.get("id") or ""), load_pipeline(book))))
        for book in library
    ]
    live_book_ids = {
        str(book.get("id") or "") for book, pipeline in pipeline_records
        if pipeline_worker_is_alive(str(book.get("id") or ""), pipeline)
    }
    running = bool(QUEUE_THREAD and QUEUE_THREAD.is_alive()) or bool(live_book_ids)
    current_run = sync_current_pipeline_run(pipeline_records)
    completed = int(current_run.get("completed") or 0)
    total = int(current_run.get("total") or 0)
    activities = [pipeline_activity(book, pipeline) for book, pipeline in pipeline_records]
    with QUEUE_LOCK:
        current_task = dict(QUEUE_CURRENT_TASK)
    activity = next((item for item in activities if item["state"] == "stopping" and item.get("bookId") in live_book_ids), None)
    activity = activity or next((item for item in activities if item["state"] == "running" and item.get("bookId") == current_task.get("bookId") and item.get("bookId") in live_book_ids), None)
    activity = activity or next((item for item in activities if item["state"] == "running" and item.get("bookId") in live_book_ids), None)
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
    task_labels = {
        "prepare": "Manuscript inventory", "gliner-signals": "GLiNER signals", "summarize": "Chapter summary", "dossiers": "Chapter dossier",
        "whole-summary": "Whole-book summary", "whole-dossier": "Whole-book dossier", "questions": "Questions & payoffs",
        "emotions": "Emotion scoring", "tags": "Chapter tags", "smells": "Smells",
        "cumulative-context": "Cumulative context", "llm-review": "LLM Review", "whole-llm-review": "Whole-book LLM Review",
    }
    active_action = {
        "preparing": "prepare", "extraction": "prepare", "chapter-map": "prepare",
        "chapter-archive": "prepare", "chunking": "prepare",
        "summarizing": "summarize",
    }.get(str(activity.get("phase") or ""), str(activity.get("phase") or ""))
    if active_action not in task_labels:
        requested_action = str(current_task.get("action") or "")
        active_action = requested_action if requested_action in task_labels else ""
    current_book_id = str(current_task.get("bookId") or activity.get("bookId") or "")
    queue = []
    for book in actionable:
        action = str(book.get("pipeline", {}).get("nextAction") or "")
        is_running = str(book.get("id") or "") == current_book_id
        if is_running and active_action:
            # nextAction describes what follows the current response. The queue
            # row must describe the response that actually owns the worker.
            action = active_action
        displayed_task = str(activity.get("task") or "") if is_running else ""
        queue.append({
            "bookId": str(book.get("id") or ""), "book": str(book.get("title") or "Untitled book"),
            "priority": normalize_book_priority(book.get("priority")), "action": action,
            "task": displayed_task or task_labels.get(action, action.replace("-", " ").title() or "Next chapter-step"),
            "state": "running" if is_running else "queued",
            "updatedAt": str(book.get("pipeline", {}).get("updatedAt") or book.get("updatedAt") or book.get("createdAt") or ""),
        })
    queue.sort(key=lambda item: (
        0 if item["state"] == "running" else 1,
        0 if item["action"] == "prepare" else 1,
        BOOK_PRIORITY_ORDER.get(str(item["priority"]), BOOK_PRIORITY_ORDER["normal"]),
        str(item["updatedAt"]), str(item["bookId"]),
    ))
    for rank, item in enumerate(queue, 1):
        item["rank"] = rank
    enabled = pipeline_is_enabled()
    state = {
        "enabled": enabled,
        "running": running,
        "waitingBooks": len(actionable),
        "completed": completed,
        "total": total,
        "percent": round(completed / total * 100) if total else 0,
        "currentRun": current_run,
        "libraryCoverage": library_coverage(library),
        "activity": activity,
        **estimate,
        "diagnosticCount": len(diagnostics),
        "diagnostics": diagnostics,
        "queue": queue,
    }
    state["snapshot"] = build_commons_pipeline_snapshot(
        library, pipeline_records, queue, current_run, enabled=enabled, running=running
    )
    # The browser polls this endpoint while the workspace is open. If a queue
    # worker disappeared between two durable chapter-steps, use that ordinary
    # status poll as a lightweight watchdog. The wake happens off-request so a
    # slow disk inventory never makes the library UI wait for the scheduler.
    if wake and state["enabled"] and actionable and not running:
        schedule_global_pipeline_wake()
    return state


def schedule_global_pipeline_wake() -> None:
    """Wake a stopped queue once without making status requests run the queue."""
    global QUEUE_WAKE_PENDING
    with QUEUE_LOCK:
        if QUEUE_WAKE_PENDING or (QUEUE_THREAD and QUEUE_THREAD.is_alive()):
            return
        QUEUE_WAKE_PENDING = True

    def wake() -> None:
        global QUEUE_WAKE_PENDING
        try:
            start_global_pipeline()
        finally:
            with QUEUE_LOCK:
                QUEUE_WAKE_PENDING = False

    threading.Thread(target=wake, daemon=True, name="bookinator-queue-watchdog").start()


def pipeline_atomic_status(value: object) -> str:
    status = str(value or "pending")
    if status in {"complete", "running", "stopping", "paused", "blocked", "failed", "cancelled", "stale", "superseded"}:
        return status
    return "waiting"


def pipeline_atomic_operations(book: dict[str, object], pipeline: dict[str, object]) -> list[dict[str, object]]:
    """Project the durable ledger into the operations the denominator counts."""
    book_id = str(book.get("id") or pipeline.get("bookId") or "project")
    chapters = [chapter for chapter in pipeline.get("chapters", []) if isinstance(chapter, dict)]
    manuscript_chapters = [
        chapter for chapter in chapters
        if strip_markdown_heading(chapter.get("title")).casefold() != "front matter"
    ]
    stages = {
        str(stage.get("id") or ""): stage
        for stage in pipeline.get("stages", []) if isinstance(stage, dict)
    }
    operations: list[dict[str, object]] = []

    def append(action: str, suffix: str, label: str, status: object, detail: str = "") -> None:
        operations.append({
            "id": f"{book_id}::{action}::{suffix}",
            "action": action,
            "label": label,
            "detail": detail,
            "status": pipeline_atomic_status(status),
            "sequence": len(operations) + 1,
        })

    next_action = str(book.get("pipeline", {}).get("nextAction") or pipeline.get("queuedAction") or "")
    if not manuscript_chapters:
        if next_action == "prepare" or (book.get("manuscriptId") and not chapters):
            append("prepare", "inventory", "Manuscript inventory", "waiting", "Extract text and establish the chapter map.")
        return operations

    chapter_archive = stages.get("chapter-archive", {})
    for index, chapter in enumerate(manuscript_chapters, 1):
        sequence = str(chapter.get("sequence") or chapter.get("number") or index)
        chapter_label = str(chapter.get("title") or chapter.get("chapterTitle") or f"Chapter {index}")
        if chapter_archive:
            append("prepare", f"chapter-{sequence}", f"Chapter archive · {chapter_label}", "complete" if chapter_archive.get("status") == "complete" else chapter_archive.get("status"), "Preserve the canonical chapter source artifact.")
        chapter_passes = [
            ("summarize", "summaries", "status", "Chapter summary"),
            ("gliner-signals", "gliner-signals", "glinerStatus", "GLiNER signals"),
            ("emotions", "emotions", "emotionStatus", "Emotion scoring"),
            ("tags", "tags", "tagStatus", "Chapter tags"),
            ("smells", "smells", "smellStatus", "Smells"),
            ("cumulative-context", "cumulative-context", "contextStatus", "Cumulative context"),
            ("llm-review", "llm-review", "llmReviewStatus", "LLM Review"),
        ]
        for action, stage_id, status_key, label in chapter_passes:
            stage = stages.get(stage_id)
            if action != "summarize" and (not stage or stage.get("disabled")):
                continue
            append(action, f"chapter-{sequence}", f"{label} · {chapter_label}", chapter.get(status_key), str(stage.get("detail") or "") if stage else "")

    chapter_sequences = {str(chapter.get("sequence") or chapter.get("number") or "") for chapter in manuscript_chapters}
    for index, chunk in enumerate(pipeline.get("chunks", []) if isinstance(pipeline.get("chunks"), list) else [], 1):
        if not isinstance(chunk, dict) or str(chunk.get("chapterSequence") or "") not in chapter_sequences:
            continue
        sequence = str(chunk.get("sequence") or chunk.get("id") or index)
        chapter_label = str(chunk.get("chapterLabel") or chunk.get("chapterTitle") or f"Chapter {chunk.get('chapterSequence') or '?'}")
        chunk_in_chapter = chunk.get("chunkInChapter")
        label = f"Chapter dossier · {chapter_label}" + (f" · Chunk {chunk_in_chapter}" if chunk_in_chapter not in (None, "") else "")
        append("dossiers", f"chunk-{sequence}", label, chunk.get("dossierStatus"), str(stages.get("dossiers", {}).get("detail") or ""))

    for action, key, label in (
        ("whole-summary", "wholeBookSummary", "Whole-book summary"),
        ("whole-dossier", "wholeBookDossier", "Whole-book dossier"),
        ("questions", "questionTracker", "Questions & payoffs"),
        ("whole-llm-review", "wholeBookLlmReview", "Whole-book LLM Review"),
    ):
        record = pipeline.get(key)
        if not isinstance(record, dict) or record.get("disabled"):
            continue
        append(action, "rollup", label, record.get("status"), str(record.get("detail") or ""))
    return operations


def machine_analysis_progress(book: dict[str, object], pipeline: dict[str, object]) -> dict[str, int]:
    """Count the same durable atomic operations exposed by the Commons queue."""
    operations = pipeline_atomic_operations(book, pipeline)
    if operations:
        completed = sum(1 for operation in operations if operation["status"] == "complete")
        return {"completed": completed, "total": len(operations)}
    # Compatibility for saved pre-atomic ledgers and focused tests that carry
    # only the prior aggregate. Real hydrated ledgers take the branch above.
    progress = pipeline.get("pipelineProgress") if isinstance(pipeline.get("pipelineProgress"), dict) else {}
    completed = int(progress.get("completed") or 0)
    total = int(progress.get("total") or 0)
    return {"completed": min(completed, total), "total": total}


def load_current_pipeline_run() -> dict[str, object]:
    try:
        payload = json.loads(CURRENT_RUN_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) and payload.get("schema") == "bookinator-current-run-v1" else {}


def save_current_pipeline_run(run: dict[str, object]) -> None:
    CURRENT_RUN_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = CURRENT_RUN_PATH.with_suffix(".tmp")
    temporary.write_text(json.dumps(run, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(CURRENT_RUN_PATH)


def current_run_candidate(book: dict[str, object], pipeline: dict[str, object]) -> bool:
    progress = machine_analysis_progress(book, pipeline)
    next_action = str(book.get("pipeline", {}).get("nextAction") or "")
    # Deferred projects remain part of the truthful run denominator and
    # snapshot; scheduling policy makes them ineligible without erasing them.
    return progress["completed"] < progress["total"] or bool(next_action)


def new_current_pipeline_run(pipeline_records: list[tuple[dict[str, object], dict[str, object]]]) -> dict[str, object]:
    now = utc_now()
    books: dict[str, dict[str, object]] = {}
    for book, pipeline in pipeline_records:
        if not current_run_candidate(book, pipeline):
            continue
        progress = machine_analysis_progress(book, pipeline)
        book_id = str(book.get("id") or "")
        if not book_id:
            continue
        books[book_id] = {
            "title": str(book.get("title") or "Untitled book"),
            "baselineCompleted": progress["completed"],
            "targetTotal": progress["total"],
            "addedAt": now,
        }
    return {
        "schema": "bookinator-current-run-v1",
        "basisVersion": PIPELINE_RUN_BASIS_VERSION,
        "id": str(uuid.uuid4()),
        "startedAt": now,
        "updatedAt": now,
        "status": "active" if books else "complete",
        "books": books,
        "initialBookCount": len(books),
        "addedUnits": 0,
    }


def sync_current_pipeline_run(
    pipeline_records: list[tuple[dict[str, object], dict[str, object]]], *, restart: bool = False
) -> dict[str, object]:
    """Maintain a durable, honest denominator for work undertaken together."""
    with CURRENT_RUN_LOCK:
        run = {} if restart else load_current_pipeline_run()
        new_run_created = False
        if run.get("basisVersion") != PIPELINE_RUN_BASIS_VERSION:
            run = {}
        candidates = [(book, pipeline) for book, pipeline in pipeline_records if current_run_candidate(book, pipeline)]
        if not run or (run.get("status") == "complete" and candidates):
            run = new_current_pipeline_run(pipeline_records)
            new_run_created = True
        entries = run.setdefault("books", {})
        if not isinstance(entries, dict):
            entries = {}
            run["books"] = entries
        changed = restart or new_run_created or not CURRENT_RUN_PATH.exists()
        added_units = int(run.get("addedUnits") or 0)
        records = {str(book.get("id") or ""): (book, pipeline) for book, pipeline in pipeline_records}
        for book, pipeline in candidates:
            book_id = str(book.get("id") or "")
            progress = machine_analysis_progress(book, pipeline)
            entry = entries.get(book_id)
            if not isinstance(entry, dict):
                entries[book_id] = {
                    "title": str(book.get("title") or "Untitled book"),
                    "baselineCompleted": progress["completed"],
                    "targetTotal": progress["total"],
                    "addedAt": utc_now(),
                }
                added_units += max(0, progress["total"] - progress["completed"])
                changed = True
                continue
            if progress["completed"] < int(entry.get("baselineCompleted") or 0):
                entry["baselineCompleted"] = progress["completed"]
                changed = True
            if progress["total"] != int(entry.get("targetTotal") or 0):
                added_units += max(0, progress["total"] - int(entry.get("targetTotal") or 0))
                entry["targetTotal"] = progress["total"]
                entry["baselineCompleted"] = min(int(entry.get("baselineCompleted") or 0), progress["total"])
                changed = True
            title = str(book.get("title") or "Untitled book")
            if entry.get("title") != title:
                entry["title"] = title
                changed = True
        completed = 0
        total = 0
        deferred_units = 0
        deferred_books = 0
        for book_id, entry in entries.items():
            if not isinstance(entry, dict):
                continue
            baseline = int(entry.get("baselineCompleted") or 0)
            target = max(baseline, int(entry.get("targetTotal") or 0))
            units = target - baseline
            total += units
            record = records.get(str(book_id))
            current = baseline
            if record:
                book, pipeline = record
                current = machine_analysis_progress(book, pipeline)["completed"]
                if normalize_book_priority(book.get("priority")) == "shelved":
                    deferred_books += 1
                    deferred_units += max(0, target - max(baseline, current))
            completed += min(units, max(0, current - baseline))
        status = "complete" if completed >= total else "active"
        now = utc_now()
        if run.get("status") != status:
            run["status"] = status
            changed = True
            if status == "complete":
                run["completedAt"] = now
        run.update({
            "completed": completed,
            "total": total,
            "percent": round(completed / total * 100) if total else 100,
            "remaining": max(0, total - completed),
            "bookCount": len(entries),
            "addedUnits": added_units,
            "deferredUnits": deferred_units,
            "deferredBooks": deferred_books,
        })
        if changed:
            run["updatedAt"] = now
            save_current_pipeline_run(run)
        return run


def library_coverage(books: list[dict[str, object]]) -> dict[str, int]:
    eligible = [book for book in books if book.get("manuscriptId")]
    analysis_complete = sum(1 for book in eligible if book.get("pipeline", {}).get("machineComplete"))
    reviewed_complete = sum(
        1 for book in eligible
        if book.get("pipeline", {}).get("machineComplete") and book.get("pipeline", {}).get("reviewerComplete")
    )
    return {"totalBooks": len(eligible), "analysisComplete": analysis_complete, "reviewedComplete": reviewed_complete}


def enrich_book(book: dict[str, object], pipeline_snapshot: dict[str, object] | None = None) -> dict[str, object]:
    enriched = dict(book)
    metadata = manuscript_metadata(str(book.get("manuscriptId") or ""))
    if metadata.get("sourceFilename"):
        enriched["sourceFilename"] = metadata["sourceFilename"]
    enriched.setdefault("ingestedAt", metadata.get("ingestedAt", ""))
    for key in ("sourceSizeBytes", "sourceFormat", "sourceMediaType", "sourceAvailable", "sourceOriginalPreserved"):
        enriched[key] = metadata.get(key)
    manuscript_path = BOOKS_ROOT / str(book.get("manuscriptId") or "") / "manuscript.pdf"
    enriched["hasPdf"] = manuscript_path.is_file()
    pipeline = pipeline_snapshot or add_pipeline_progress(pipeline_for_client(str(book.get("id") or ""), load_pipeline(book)))
    chapters = pipeline.get("chapters", [])
    manuscript_metrics = pipeline.get("manuscriptMetrics", {}) if isinstance(pipeline.get("manuscriptMetrics"), dict) else {}
    enriched["wordCount"] = int(manuscript_metrics.get("wordCount") or 0)
    enriched["chapterCount"] = int(manuscript_metrics.get("chapterCount") or 0)
    completed = sum(1 for chapter in chapters if chapter.get("status") == "complete")
    stages = {stage.get("id"): stage.get("status", "pending") for stage in pipeline.get("stages", [])}
    next_action = next_pipeline_action(book, pipeline)
    machine_progress = dict(pipeline.get("pipelineProgress", {}))
    machine_total = int(machine_progress.get("total") or 0)
    reviewer_signoff = load_reviewer_signoff(book)
    reviewer_complete = reviewer_signoff.get("status") == "complete"
    paused_actions = sorted(paused_pipeline_actions(str(book.get("id") or "")))
    analysis_progress = machine_analysis_progress({**book, "pipeline": {"nextAction": next_action}}, pipeline)
    machine_complete = bool(analysis_progress["total"]) and analysis_progress["completed"] >= analysis_progress["total"] and not next_action and not paused_actions
    task_stages = [
        {key: stage.get(key) for key in ("id", "status", "detail", "disabled") if key in stage}
        for stage in pipeline.get("stages", []) if isinstance(stage, dict)
    ]
    task_result_defaults = {
        "wholeBookSummary": "Waiting for current chapter summaries.",
        "wholeBookDossier": "Waiting for current chunk dossiers.",
        "questionTracker": "Waiting for current summaries and dossiers.",
        "wholeBookLlmReview": "Waiting for current chapter reviews.",
    }
    task_results = {}
    for key, detail in task_result_defaults.items():
        result = pipeline.get(key)
        task_results[key] = (
            {field: result.get(field) for field in ("status", "detail", "disabled") if field in result}
            if isinstance(result, dict) else {"status": "blocked", "detail": detail}
        )
    if machine_total:
        machine_completed = int(machine_progress.get("completed") or 0)
        library_progress = {
            **machine_progress,
            "completed": machine_completed + int(reviewer_complete),
            "total": machine_total + 1,
            "percent": round((machine_completed + int(reviewer_complete)) / (machine_total + 1) * 100),
            "basisLabel": f'{machine_progress.get("basisLabel") or "Saved analysis steps"} · reviewer sign-off',
        }
    else:
        library_progress = machine_progress
    enriched["pipeline"] = {
        "queued": str(book.get("id")) in load_queue(),
        "status": pipeline.get("status", "ready"),
        "structure": stages.get("structure", "pending"),
        "summariesCompleted": completed,
        "summariesTotal": len(chapters),
        "updatedAt": pipeline.get("updatedAt", ""),
        "nextAction": next_action,
        "workRemaining": bool(next_action or paused_actions) or bool(machine_total and not reviewer_complete),
        "reviewerPending": bool(machine_total and not reviewer_complete),
        "machineProgress": analysis_progress,
        "machineComplete": machine_complete,
        "reviewerComplete": reviewer_complete,
        "progress": library_progress,
        "stages": task_stages,
        "pausedActions": paused_actions,
        **task_results,
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
    allowed = {"gliner", "summary", "dossier", "emotion", "tag", "smell", "context", "llm-review", "whole-summary", "whole-llm-review"}
    return {
        str(book_id): [(str(item[0]), int(item[1])) for item in requests if isinstance(item, list) and len(item) == 2 and str(item[0]) in allowed]
        for book_id, requests in payload.items() if isinstance(book_id, str) and isinstance(requests, list)
    }


def save_deferred_analysis_refreshes(refreshes: dict[str, list[tuple[str, int]]]) -> None:
    DEFERRED_REFRESHES_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = DEFERRED_REFRESHES_PATH.with_suffix(".tmp")
    temporary.write_text(json.dumps(refreshes, indent=2) + "\n", encoding="utf-8")
    temporary.replace(DEFERRED_REFRESHES_PATH)


def refresh_followup_action(owner_action: str) -> str:
    """Resume normal chapter order after one row-level refresh.

    The owner action identifies the stage that must be unpaused. It must not be
    mistaken for a request to drain that entire category. Whole-book rows are
    the exception because their result is itself the complete queue task.
    """
    return owner_action if owner_action in {"whole-summary", "whole-llm-review"} else "chapter-pipeline"


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


def suggested_new_book_title(title: str, claimed_titles: set[str], created_on: object | None = None) -> str:
    date = str(created_on or datetime.now().date().isoformat())
    base = f"{title or 'Untitled'} (New import {date})"
    candidate = base
    sequence = 2
    while candidate.casefold() in claimed_titles:
        candidate = f"{base} {sequence}"
        sequence += 1
    return candidate


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
        "originalIngestedAt": str(book.get("originalIngestedAt") or ""),
        "importedAt": str(book.get("importedAt") or ""),
        "createdAt": str(book.get("createdAt") or utc_now()),
        "updatedAt": utc_now(),
        "abbreviation": str(book.get("abbreviation") or "").strip()[:3],
        "priority": normalize_book_priority(book.get("priority")),
        "llmReviewEnabled": bool(book.get("llmReviewEnabled")),
    }
    with LIBRARY_LOCK:
        library = load_library_records()
        existing = next((index for index, item in enumerate(library) if item.get("id") == book_id), None)
        incoming_icon = normalized.get("icon") if isinstance(normalized.get("icon"), dict) else {}
        lazy_icon_url = f"/api/books/{urllib.parse.quote(book_id)}/icon"
        if existing is not None and incoming_icon.get("kind") == "image" and incoming_icon.get("value") == lazy_icon_url:
            # The shelf deliberately receives a URL instead of a large data
            # URI. Saving unrelated Identity changes must retain the durable
            # embedded icon rather than persisting that presentation URL.
            normalized["icon"] = copy.deepcopy(library[existing].get("icon"))
        claimed_titles = {
            str(item.get("title") or "").strip().casefold()
            for item in library
            if str(item.get("id") or "") != book_id and str(item.get("title") or "").strip()
        }
        if normalized["title"].casefold() in claimed_titles:
            raise ImportTitleCollision([{
                "importKey": book_id,
                "title": normalized["title"],
                "suggestedTitle": suggested_new_book_title(normalized["title"], claimed_titles),
                "reason": "same-title",
            }])
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


def _portable_book_record(book: dict[str, object]) -> dict[str, object]:
    """Return durable library metadata without computed presentation fields."""
    return {
        key: value
        for key, value in book.items()
        if key not in {"pipeline", "hasPdf", "analysisCompletion", "analysisComplete", "queued", "queuePosition"}
    }


def _bundle_files(root: Path, prefix: str) -> list[tuple[str, Path]]:
    if not root.is_dir():
        return []
    files: list[tuple[str, Path]] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        files.append((f"{prefix}/{path.relative_to(root).as_posix()}", path))
    return files


def library_bundle_filename(books: list[dict[str, object]], exported_on: object | None = None) -> str:
    day = str(exported_on or datetime.now().date().isoformat())
    if len(books) == 1:
        identity = re.sub(r"[^a-z0-9]+", "_", str(books[0].get("title") or "book").casefold()).strip("_") or "book"
    else:
        identity = f"{len(books)}_books"
    return f"bookinator-{identity}-{day}.bookinator"


def build_library_bundle(books: list[dict[str, object]]) -> bytes:
    """Build a complete, checksummed, model-independent project transfer."""
    exported_books: list[dict[str, object]] = []
    archive_files: list[tuple[str, Path]] = []
    for book in books:
        book_id = str(book.get("id") or "")
        manuscript_id = str(book.get("manuscriptId") or "")
        if not book_id or not manuscript_id:
            continue
        exported_books.append(_portable_book_record(book))
        archive_files.extend(_bundle_files(BOOKS_ROOT / manuscript_id, f"books/{manuscript_id}"))
        archive_files.extend(_bundle_files(REPORTS_ROOT / book_id, f"reports/{book_id}"))

    file_records: list[dict[str, object]] = []
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for archive_name, path in archive_files:
            content = path.read_bytes()
            archive.writestr(archive_name, content)
            file_records.append({
                "path": archive_name,
                "bytes": len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
            })
        manifest = {
            "schema": BUNDLE_SCHEMA,
            "exportedAt": utc_now(),
            "books": exported_books,
            "files": file_records,
            "contents": {
                "sourceDocuments": True,
                "analysis": True,
                "chapterAndChunkArtifacts": True,
                "annotationsAndSignoff": True,
                "savedReports": True,
            },
        }
        archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    return payload.getvalue()


def _safe_bundle_path(value: object) -> str:
    path = str(value or "")
    pure = Path(path)
    if not path or path.startswith(("/", "\\")) or pure.is_absolute() or ".." in pure.parts or "\\" in path:
        raise ValueError("The Bookinator package contains an unsafe file path.")
    return path


def _import_copy_title(title: str, existing_titles: set[str]) -> str:
    base = title or "Untitled"
    candidate = f"{base} (Imported copy)"
    sequence = 2
    while candidate.casefold() in existing_titles:
        candidate = f"{base} (Imported copy {sequence})"
        sequence += 1
    return candidate


def _suggest_import_title(title: str, claimed_titles: set[str], imported_on: str) -> str:
    base = f"{title or 'Untitled'} (Imported {imported_on})"
    candidate = base
    sequence = 2
    while candidate.casefold() in claimed_titles:
        candidate = f"{base} {sequence}"
        sequence += 1
    return candidate


def _resolve_import_titles(
    incoming_books: list[dict[str, object]],
    existing: list[dict[str, object]],
    overrides: dict[str, str] | None,
) -> tuple[dict[str, str], list[dict[str, object]]]:
    overrides = overrides or {}
    claimed = {str(book.get("title") or "").strip().casefold() for book in existing}
    used_book_ids = {str(book.get("id") or "") for book in existing}
    used_manuscript_ids = {str(book.get("manuscriptId") or "") for book in existing}
    imported_on = datetime.now().date().isoformat()
    resolved: dict[str, str] = {}
    renamed: list[dict[str, object]] = []
    conflicts: list[dict[str, object]] = []
    for index, incoming in enumerate(incoming_books):
        import_key = str(incoming.get("id") or f"book-{index + 1}")
        original = str(incoming.get("title") or "Untitled").strip() or "Untitled"
        requested = str(overrides.get(import_key) or "").strip()
        identity_collision = str(incoming.get("id") or "") in used_book_ids or str(incoming.get("manuscriptId") or "") in used_manuscript_ids
        original_collision = original.casefold() in claimed or identity_collision
        candidate = requested or original
        candidate_collision = candidate.casefold() in claimed
        if (original_collision and not requested) or candidate_collision:
            conflicts.append({
                "importKey": import_key,
                "title": original,
                "suggestedTitle": _suggest_import_title(original, claimed, imported_on),
                "reason": "existing-project" if identity_collision else "same-title",
            })
            continue
        candidate = candidate[:500]
        resolved[import_key] = candidate
        claimed.add(candidate.casefold())
        if candidate != original:
            renamed.append({
                "kind": "renamed-import",
                "title": original,
                "importedAs": candidate,
                "message": f"{original} was imported as {candidate}.",
            })
    if conflicts:
        raise ImportTitleCollision(conflicts)
    return resolved, renamed


def import_legacy_library_export(manifest: dict[str, object], title_overrides: dict[str, str] | None = None) -> dict[str, object]:
    """Recover metadata and saved analysis from the retired JSON-only export."""
    if manifest.get("schema") != "bookinator-library-v1" or not isinstance(manifest.get("books"), list):
        raise ValueError("This is not a recognized Bookinator project package.")
    incoming_books = [book for book in manifest["books"] if isinstance(book, dict)]
    title_plan, collisions = _resolve_import_titles(incoming_books, load_library(), title_overrides)
    imported_at = utc_now()
    imported: list[dict[str, object]] = []
    for index, incoming in enumerate(incoming_books):
        book_id = str(uuid.uuid4())
        manuscript_id = str(uuid.uuid4())
        project_root = BOOKS_ROOT / manuscript_id
        project_root.mkdir(parents=True, exist_ok=False)
        import_key = str(incoming.get("id") or f"book-{index + 1}")
        title = title_plan[import_key]
        try:
            analysis = incoming.get("analysis") if isinstance(incoming.get("analysis"), dict) else None
            if analysis:
                analysis = dict(analysis)
                analysis["bookId"] = book_id
                (project_root / "pipeline.json").write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            portable = {key: value for key, value in incoming.items() if key != "analysis"}
            portable.update({
                "id": book_id,
                "manuscriptId": manuscript_id,
                "title": title,
                "sourceFilename": "",
                "originalIngestedAt": str(incoming.get("originalIngestedAt") or incoming.get("ingestedAt") or ""),
                "ingestedAt": imported_at,
                "importedAt": imported_at,
            })
            saved = save_book(portable)
        except Exception:
            shutil.rmtree(project_root, ignore_errors=True)
            raise
        imported.append({"id": book_id, "manuscriptId": manuscript_id, "title": str(saved.get("title") or title)})
    return {
        "imported": len(imported),
        "books": imported,
        "collisions": collisions,
        "schema": "bookinator-library-v1",
        "legacy": True,
        "warning": "This was a legacy library export. Its saved analysis was restored, but that older format did not contain the original source document, generated artifacts, or saved reports.",
    }


def import_library_bundle(payload: bytes, title_overrides: dict[str, str] | None = None) -> dict[str, object]:
    """Validate and import a complete project bundle without overwriting local work."""
    if not payload or len(payload) > MAX_BUNDLE_BYTES:
        raise ValueError("Bookinator packages must be between 1 byte and 1 GB.")
    if not zipfile.is_zipfile(io.BytesIO(payload)):
        try:
            legacy_manifest = json.loads(payload.decode("utf-8-sig"))
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            raise ValueError("This is not a valid Bookinator project package.") from error
        if not isinstance(legacy_manifest, dict):
            raise ValueError("This is not a valid Bookinator project package.")
        return import_legacy_library_export(legacy_manifest, title_overrides)
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        try:
            manifest = json.loads(archive.read("manifest.json"))
        except (KeyError, json.JSONDecodeError, UnicodeDecodeError) as error:
            raise ValueError("This is not a valid Bookinator project package.") from error
        if not isinstance(manifest, dict) or manifest.get("schema") != BUNDLE_SCHEMA:
            raise ValueError("This Bookinator package uses an unsupported format.")
        incoming_books = manifest.get("books")
        file_records = manifest.get("files")
        if not isinstance(incoming_books, list) or not isinstance(file_records, list):
            raise ValueError("The Bookinator package manifest is incomplete.")

        archive_names = set(archive.namelist())
        verified: dict[str, bytes] = {}
        expanded_bytes = 0
        for record in file_records:
            if not isinstance(record, dict):
                raise ValueError("The Bookinator package file index is invalid.")
            path = _safe_bundle_path(record.get("path"))
            if path not in archive_names or path == "manifest.json":
                raise ValueError(f"The Bookinator package is missing {path}.")
            content = archive.read(path)
            expanded_bytes += len(content)
            if expanded_bytes > MAX_BUNDLE_EXPANDED_BYTES:
                raise ValueError("The expanded Bookinator package is too large.")
            if int(record.get("bytes") or -1) != len(content) or str(record.get("sha256") or "") != hashlib.sha256(content).hexdigest():
                raise ValueError(f"The Bookinator package failed its integrity check for {path}.")
            verified[path] = content

    existing = load_library()
    used_book_ids = {str(book.get("id") or "") for book in existing}
    used_manuscript_ids = {str(book.get("manuscriptId") or "") for book in existing}
    incoming_book_records = [book for book in incoming_books if isinstance(book, dict)]
    title_plan, collisions = _resolve_import_titles(incoming_book_records, existing, title_overrides)
    imported_at = utc_now()
    imported: list[dict[str, object]] = []

    for index, incoming in enumerate(incoming_book_records):
        original_book_id = str(incoming.get("id") or "")
        original_manuscript_id = str(incoming.get("manuscriptId") or "")
        if not re.fullmatch(r"[A-Za-z0-9_-]{8,80}", original_book_id) or not re.fullmatch(r"[A-Za-z0-9_-]{8,80}", original_manuscript_id):
            raise ValueError("A book in the package has invalid project identity.")
        identity_collision = original_book_id in used_book_ids or original_manuscript_id in used_manuscript_ids
        book_id = str(uuid.uuid4()) if original_book_id in used_book_ids else original_book_id
        manuscript_id = str(uuid.uuid4()) if original_manuscript_id in used_manuscript_ids else original_manuscript_id
        import_key = original_book_id or f"book-{index + 1}"
        title = title_plan[import_key]

        project_prefix = f"books/{original_manuscript_id}/"
        project_files = {path.removeprefix(project_prefix): content for path, content in verified.items() if path.startswith(project_prefix)}
        if not project_files:
            raise ValueError(f"The package contains no project files for {title}.")
        report_prefix = f"reports/{original_book_id}/"
        report_files = {path.removeprefix(report_prefix): content for path, content in verified.items() if path.startswith(report_prefix)}

        project_root = BOOKS_ROOT / manuscript_id
        report_root = REPORTS_ROOT / book_id
        if project_root.exists() or report_root.exists():
            raise ValueError("The destination project identity is already in use.")
        project_root.mkdir(parents=True, exist_ok=False)
        try:
            for relative, content in project_files.items():
                target = project_root / _safe_bundle_path(relative)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(content)
            pipeline_file = project_root / "pipeline.json"
            if pipeline_file.is_file():
                pipeline = json.loads(pipeline_file.read_text(encoding="utf-8"))
                if isinstance(pipeline, dict):
                    pipeline["bookId"] = book_id
                    pipeline_file.write_text(json.dumps(pipeline, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            if report_files:
                report_root.mkdir(parents=True, exist_ok=False)
                for relative, content in report_files.items():
                    target = report_root / _safe_bundle_path(relative)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(content)
            portable = dict(incoming)
            portable.update({
                "id": book_id,
                "manuscriptId": manuscript_id,
                "title": title,
                "updated": "Imported just now",
                "originalIngestedAt": str(incoming.get("originalIngestedAt") or incoming.get("ingestedAt") or ""),
                "ingestedAt": imported_at,
                "importedAt": imported_at,
            })
            saved = save_book(portable)
        except Exception:
            shutil.rmtree(project_root, ignore_errors=True)
            shutil.rmtree(report_root, ignore_errors=True)
            raise
        used_book_ids.add(book_id)
        used_manuscript_ids.add(manuscript_id)
        imported.append({"id": book_id, "manuscriptId": manuscript_id, "title": str(saved.get("title") or title)})

    return {"imported": len(imported), "books": imported, "collisions": collisions, "schema": BUNDLE_SCHEMA}


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
    visual_lines: list[str] = []
    for source_line in text.splitlines():
        if not source_line.strip():
            visual_lines.append("")
            continue
        visual_lines.extend(textwrap.wrap(source_line, width=78, replace_whitespace=False, drop_whitespace=True) or [""])
    for start in range(0, len(visual_lines), 48):
        chunk = "\n".join(visual_lines[start:start + 48])
        page = document.new_page(width=612, height=792)
        remaining = page.insert_textbox(pymupdf.Rect(54, 54, 558, 738), chunk, fontsize=10.5, fontname="courier", lineheight=1.25)
        if remaining < 0:
            document.close()
            raise ValueError("Bookinator could not paginate that text manuscript without truncating it.")
    rendered = document.tobytes(garbage=4, deflate=True)
    document.close()
    return rendered


def epub_spine_documents(archive: zipfile.ZipFile) -> list[str]:
    """Return EPUB reading documents in package spine order."""
    try:
        container = ET.fromstring(archive.read("META-INF/container.xml"))
        package_path = str(container.find(".//{*}rootfile").attrib.get("full-path") or "")
        package = ET.fromstring(archive.read(package_path))
        package_root = posixpath.dirname(package_path)
        manifest = {
            str(item.attrib.get("id") or ""): item.attrib
            for item in package.findall(".//{*}manifest/{*}item")
        }
        names = []
        for itemref in package.findall(".//{*}spine/{*}itemref"):
            item = manifest.get(str(itemref.attrib.get("idref") or ""), {})
            if str(item.get("media-type") or "").casefold() not in {"application/xhtml+xml", "text/html"}:
                continue
            href = urllib.parse.unquote(str(item.get("href") or ""))
            if href:
                names.append(posixpath.normpath(posixpath.join(package_root, href)))
        if names:
            return names
    except (KeyError, AttributeError, ET.ParseError):
        pass
    return sorted(name for name in archive.namelist() if name.casefold().endswith((".xhtml", ".html", ".htm")))


def html_manuscript_to_markdown(markup: str) -> str:
    """Keep authored HTML paragraphs and heading boundaries in reflowable text."""
    # Metadata titles are not manuscript prose. In particular, Gutenberg can
    # title its final spine document "THE FULL ... LICENSE" even when that
    # document begins with the book's epilogue; retaining the head makes the
    # later boilerplate stripper truncate legitimate authored text.
    markup = re.sub(r"<head\b[^>]*>.*?</head>", "", markup, flags=re.IGNORECASE | re.DOTALL)
    markup = re.sub(r"<(script|style)\b[^>]*>.*?</\1>", "", markup, flags=re.IGNORECASE | re.DOTALL)
    markup = re.sub(
        r"<(?P<boilerplate_tag>header|footer|div|section)\b[^>]*class\s*=\s*['\"][^'\"]*\bpg-boilerplate\b[^'\"]*['\"][^>]*>.*?</(?P=boilerplate_tag)>",
        "",
        markup,
        flags=re.IGNORECASE | re.DOTALL,
    )
    # Some Gutenberg EPUBs append a publisher-style catalogue to the final
    # authored spine document rather than putting it in the removable footer.
    # Keep ordinary appendices and back matter analyzable, but discard this
    # narrowly identifiable trailing advertisement before it becomes part of
    # the book's final chapter.
    markup = re.sub(
        r"<hr\b[^>]*?/?>\s*"
        r"<p\b(?=[^>]*class\s*=\s*['\"][^'\"]*\bletter\b[^'\"]*['\"])[^>]*>\s*"
        r"Other\s+books\s+by\b.*?</p>"
        r"(?=\s*(?:(?:</div\s*>|<div\b[^>]*/>)\s*)*</body\s*>)",
        "",
        markup,
        flags=re.IGNORECASE | re.DOTALL,
    )

    def chapter_break(match: re.Match[str]) -> str:
        """Promote semantic EPUB chapter breaks before virtual pagination."""
        body = html.unescape(re.sub(r"<[^>]+>", " ", match.group("body")))
        label = re.sub(r"\s+", " ", body).strip()
        if EXPLICIT_CHAPTER_HEADING_PATTERN.fullmatch(label):
            return f"\n\n## {label}\n\n"
        return match.group(0)

    # Gutenberg and many publisher EPUBs use a chapter-rule element followed
    # by a styled paragraph instead of an h1-h6 element. Once flattened, that
    # label becomes ordinary prose and can land midway through a virtual page.
    # Preserve only explicit chapter-family labels at semantic rule breaks;
    # this avoids treating arbitrary styled paragraphs as structure.
    markup = re.sub(
        r"<hr\b[^>]*class\s*=\s*['\"][^'\"]*\bchap(?:ter)?\b[^'\"]*['\"][^>]*?/?>\s*"
        r"<(?P<break_tag>p|div)\b[^>]*>(?P<body>.*?)</(?P=break_tag)>",
        chapter_break,
        markup,
        flags=re.IGNORECASE | re.DOTALL,
    )

    def heading(match: re.Match[str]) -> str:
        level = int(match.group("level") or 2)
        body_markup = re.sub(r"<br\s*/?>", "\n", match.group("body"), flags=re.IGNORECASE)
        segments = [
            re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", line))).strip()
            for line in body_markup.splitlines()
        ]
        segments = [segment for segment in segments if segment]
        for index, segment in enumerate(segments):
            if not EXPLICIT_CHAPTER_HEADING_PATTERN.fullmatch(segment):
                continue
            # Some first-chapter headings include the book title before the
            # actual chapter label; very long subtitles can also make the
            # combined h2 fail the explicit-label grammar. Preserve the label
            # as the boundary and its next line as the displayed title.
            title = segments[index + 1] if index + 1 < len(segments) else ""
            suffix = f"\n\n{'#' * min(max(level + 1, 1), 6)} {title}" if title else ""
            return f"\n\n{'#' * min(max(level, 1), 6)} {segment}{suffix}\n\n"
        body = html.unescape(re.sub(r"<[^>]+>", " ", match.group("body")))
        label = re.sub(r"\s+", " ", body).strip()
        return f"\n\n{'#' * min(max(level, 1), 6)} {label}\n\n" if label else "\n\n"

    markup = re.sub(
        r"<h(?P<level>[1-6])\b[^>]*>(?P<body>.*?)</h[1-6]>",
        heading,
        markup,
        flags=re.IGNORECASE | re.DOTALL,
    )
    markup = re.sub(
        r"<div\b[^>]*class\s*=\s*['\"][^'\"]*\bh(?P<level>[1-6])\b[^'\"]*['\"][^>]*>(?P<body>.*?)</div>",
        heading,
        markup,
        flags=re.IGNORECASE | re.DOTALL,
    )
    markup = re.sub(r"<br\s*/?>", "\n", markup, flags=re.IGNORECASE)
    markup = re.sub(r"</(?:p|div|li|blockquote|section|article|header|footer)>", "\n\n", markup, flags=re.IGNORECASE)
    text = html.unescape(re.sub(r"<[^>]+>", "", markup)).replace("\r\n", "\n")
    blocks = []
    for block in re.split(r"\n\s*\n+", text):
        value = block.strip()
        if not value:
            continue
        if re.match(r"^#{1,6}\s+", value):
            lines = value.splitlines()
            blocks.append(lines[0].strip())
            remainder = re.sub(r"\s+", " ", " ".join(lines[1:])).strip()
            if remainder:
                blocks.append(remainder)
        else:
            blocks.append(re.sub(r"\s+", " ", value))
    return "\n\n".join(blocks).strip()


def strip_project_gutenberg_boilerplate(text: str) -> str:
    """Keep the authored work while removing Project Gutenberg's transport wrapper."""
    body = text.replace("\r\n", "\n")
    start = re.search(r"(?im)^\s*(?:#{1,6}\s*)?\*{3}\s*START OF THE PROJECT GUTENBERG (?:EBOOK|ETEXT)\b.*?\*{3}\s*$", body)
    if start:
        body = body[start.end():]
    end = re.search(r"(?im)^\s*(?:#{1,6}\s*)?\*{3}\s*END OF THE PROJECT GUTENBERG (?:EBOOK|ETEXT)\b.*?\*{3}\s*$", body)
    if end:
        body = body[:end.start()]
    license_heading = re.search(r"(?im)^\s*(?:#{1,6}\s*)?THE FULL PROJECT GUTENBERG(?:™|\(TM\))? LICENSE\s*$", body)
    if license_heading:
        body = body[:license_heading.start()]
    return body.strip()


def archive_manuscript_text(source: bytes, suffix: str) -> bytes:
    with zipfile.ZipFile(io.BytesIO(source)) as archive:
        if sum(item.file_size for item in archive.infolist()) > MAX_PREVIEW_BYTES:
            raise ValueError("The expanded manuscript is larger than 80 MB.")
        names = ["word/document.xml"] if suffix == ".docx" else epub_spine_documents(archive)
        fragments = []
        for name in names:
            try:
                markup = archive.read(name).decode("utf-8", errors="replace")
            except KeyError:
                continue
            if suffix == ".docx":
                markup = re.sub(r"</w:p>", "\n\n", markup, flags=re.IGNORECASE)
                fragments.append(html.unescape(re.sub(r"<[^>]+>", "", markup)))
            else:
                fragments.append(html_manuscript_to_markdown(markup))
    text = strip_project_gutenberg_boilerplate("\n\n".join(fragment for fragment in fragments if fragment.strip()))
    if not text:
        raise ValueError("Bookinator could not find readable text in that manuscript.")
    return text.encode("utf-8")


EXPLICIT_CHAPTER_HEADING_PATTERN = re.compile(
    r"^(?:chapter(?:\s+|\s*[:.\-—]\s*)\S.{0,100}|prologue(?:\s*[:.\-—]\s*.*)?|epilogue(?:\s*[:.\-—]\s*.*)?|interlude(?:\s*[:.\-—]\s*.*)?|appendix(?:\s+|\s*[:.\-—]\s*)\S.{0,100}|foreword\s+to\s+appendix)$",
    re.IGNORECASE,
)


def source_block_starts_authored_heading(block: str, preserve_plain_headings: bool = False) -> bool:
    """Keep explicit reflowable headings visible to the page-opening detector."""
    lines = [line.strip() for line in block.splitlines() if line.strip()]
    if not lines:
        return False
    first = lines[0]
    if re.match(r"^#{1,6}[\t ]+\S", first):
        return True
    if not preserve_plain_headings:
        return False
    if re.search(r"\s{2,}\d+\s*$", first):
        return False
    # A contents row can begin with exactly the same words as a chapter
    # heading. Treat blocks containing several chapter labels as navigation,
    # not as one enormous heading stack that swallows the first real chapter.
    explicit_lines = [line for line in lines if EXPLICIT_CHAPTER_HEADING_PATTERN.fullmatch(line)]
    if len(explicit_lines) > 1:
        return False
    if re.fullmatch(r"chapter\s+(?:page|title|contents)", first, re.IGNORECASE) or re.fullmatch(r"chapter\b.*\bpage", first, re.IGNORECASE):
        return False
    if len(lines) == 1 and re.fullmatch(r"(?:\d{1,4}|[IVXLCDM]{1,12})(?:\s*[.:\-—]\s*\S.{0,90})?", first):
        return True
    return bool(EXPLICIT_CHAPTER_HEADING_PATTERN.fullmatch(first))


def source_text_to_pages(text: str, target_characters: int = 3200, *, preserve_plain_headings: bool = False) -> list[str]:
    """Create lossless virtual pages while keeping authored headings at page starts."""
    blocks = [block.strip() for block in re.split(r"\n\s*\n+", text.replace("\r\n", "\n")) if block.strip()]
    pages: list[str] = []
    current: list[str] = []
    current_size = 0

    def flush() -> None:
        nonlocal current_size
        if current:
            pages.append("\n\n".join(current).strip())
            current.clear()
            current_size = 0

    for block in blocks:
        authored_heading = source_block_starts_authored_heading(block, preserve_plain_headings)
        current_is_heading_stack = current and all(source_block_starts_authored_heading(item, preserve_plain_headings) for item in current)
        if authored_heading and not current_is_heading_stack:
            flush()
        block_size = len(block) + (2 if current else 0)
        if current and current_size + block_size > target_characters:
            flush()
        current.append(block)
        current_size += block_size
    flush()
    return pages


def native_manuscript_pages(book: dict[str, object]) -> list[str]:
    """Read preserved non-PDF source without routing it back through a synthetic PDF."""
    source_path, metadata = source_document_path(str(book.get("manuscriptId") or ""))
    suffix = Path(str(metadata.get("sourceFilename") or (source_path.name if source_path else ""))).suffix.casefold()
    if not source_path or suffix not in {".md", ".txt", ".docx", ".epub"}:
        return []
    source = source_path.read_bytes()
    if suffix in {".docx", ".epub"}:
        source = archive_manuscript_text(source, suffix)
    text = strip_project_gutenberg_boilerplate(source.decode("utf-8-sig", errors="replace"))
    return source_text_to_pages(text, preserve_plain_headings=suffix == ".txt")


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
    # Explicit whole-book work runs on the single library queue thread. The
    # stage worker removes its PIPELINE_THREADS entry when it finishes, and a
    # request can observe that small hand-off window while the queue still owns
    # the book. Treating that as an orphan resets live state under the worker.
    with QUEUE_LOCK:
        queue_thread = QUEUE_THREAD
        queue_book_id = str(QUEUE_CURRENT_TASK.get("bookId") or "")
    if local_thread and local_thread.is_alive():
        # Chapter-scoped work also registers the shared queue thread here. A
        # skipped/already-complete stage must not leave that thread making an
        # older book look alive after the queue has moved to another book.
        if local_thread is queue_thread:
            return queue_book_id == book_id
        return True
    if queue_thread and queue_thread.is_alive() and queue_book_id == book_id:
        return True
    try:
        owner_pid = int(pipeline.get("workerPid") or 0)
    except (TypeError, ValueError):
        owner_pid = 0
    return owner_pid != os.getpid() and process_is_alive(owner_pid)


def reconcile_development_checkpoint(book: dict[str, object], pipeline: dict[str, object]) -> bool:
    """Record an intentional bounded run without masquerading as a crashed worker."""
    try:
        limit = int(pipeline.get("developmentAnalysisLimit") or 0)
    except (TypeError, ValueError):
        limit = 0
    phase = str(pipeline.get("phase") or "")
    if limit < 1 or phase not in {"running", "chapter-complete", "interrupted", "development-checkpoint"}:
        return False
    # A shelved book has no next action by definition. Probe the bounded work
    # with a neutral priority so shelving cannot falsely complete a checkpoint.
    probe_book = {**book, "priority": "normal"}
    if next_pipeline_action(probe_book, pipeline):
        return False
    eligible = development_limited_items(pipeline, pipeline.get("chapters", []), "sequence")
    if not eligible:
        return False
    label = str(
        pipeline.get("developmentAnalysisLimitLabel")
        or pipeline.get("developmentAnalysisLabel")
        or f"section {limit}"
    )
    authored = [chapter for chapter in eligible if strip_markdown_heading(chapter.get("title")).casefold() != "front matter"]
    detail = f"Development checkpoint reached through {label}; {len(authored)} authored sections are preserved for inspection."
    before = (pipeline.get("status"), pipeline.get("phase"), pipeline.get("message"), pipeline.get("error"))
    pipeline.update({
        "status": "paused",
        "phase": "development-checkpoint",
        "developmentCheckpointLocked": True,
        "message": detail,
        "stopRequested": False,
        "updatedAt": utc_now(),
    })
    # A bounded specimen can finish after a stage's ordinary whole-book pass
    # wrote its aggregate detail. Recount from the durable chapter statuses so
    # the checkpoint reports the specimen that actually just finished.
    all_authored = [
        chapter for chapter in pipeline.get("chapters", [])
        if strip_markdown_heading(chapter.get("title")).casefold() != "front matter"
    ]
    for stage_id, status_field, label_text in (
        ("emotions", "emotionStatus", "emotions"),
        ("tags", "tagStatus", "tags"),
        ("smells", "smellStatus", "smells"),
    ):
        stage = next((item for item in pipeline.get("stages", []) if item.get("id") == stage_id), None)
        if not stage:
            continue
        completed = sum(1 for chapter in all_authored if chapter.get(status_field) == "complete")
        failed = sum(1 for chapter in all_authored if chapter.get(status_field) == "failed")
        stage.update({
            "status": "pending" if completed + failed < len(all_authored) else "warning" if failed else "complete",
            "detail": f"Completed {completed} of {len(all_authored)} manuscript chapter {label_text}; front matter excluded.",
        })
    for key in ("error", "queuedAction", "workerPid"):
        pipeline.pop(key, None)
    for stage_id in ("cumulative-context", "llm-review"):
        stage = next((item for item in pipeline.get("stages", []) if item.get("id") == stage_id), None)
        if stage and stage.get("status") not in {"complete", "warning", "failed"}:
            stage.update({"status": "pending", "detail": detail})
            for key in ("error", "startedAt", "completedAt", "durationSeconds"):
                stage.pop(key, None)
    return before != (pipeline.get("status"), pipeline.get("phase"), pipeline.get("message"), pipeline.get("error"))


def repair_orphaned_pipeline(book: dict[str, object], pipeline: dict[str, object]) -> bool:
    """Return an abandoned running ledger to the automatic queue."""
    book_id = str(book.get("id") or "")
    if pipeline.get("status") != "running" or pipeline_worker_is_alive(book_id, pipeline):
        return False
    if reconcile_development_checkpoint(book, pipeline):
        return True
    phase = str(pipeline.get("phase") or "")
    active_stage_id = {
        "preparing": "extraction", "extraction": "extraction", "chapter-map": "structure",
        "chapter-archive": "chapter-archive", "chunking": "chunking",
        "summarizing": "summaries", "dossiers": "dossiers", "chapter-reading": "summaries",
    }.get(phase, phase if phase in {"cumulative-context", "llm-review"} else "extraction")
    model = str(next((stage.get("model") for stage in pipeline.get("stages", []) if stage.get("id") == active_stage_id), "") or "The local model")
    if phase in {"preparing", "extraction", "chapter-map", "chapter-archive", "chunking"}:
        diagnostic = "The previous manuscript-preparation process ended before it recorded completion. Bookinator returned that task to the queue."
    else:
        diagnostic = f"{model}'s previous reading process ended without returning a result. Bookinator returned that task to the queue."
    reset_interrupted_rollup(pipeline, phase, diagnostic)
    interrupted_at = utc_now()
    recoveries = pipeline.get("recoveryDiagnostics") if isinstance(pipeline.get("recoveryDiagnostics"), list) else []
    recoveries.append({"at": interrupted_at, "phase": phase, "message": diagnostic})
    pipeline["recoveryDiagnostics"] = recoveries[-20:]
    pipeline.update({
        "status": "ready",
        "phase": "recovering",
        "message": "An interrupted task was returned to the queue automatically. Completed work is safe; independent work can continue.",
        "updatedAt": interrupted_at,
    })
    for key in ("error", "queuedAction", "workerPid"):
        pipeline.pop(key, None)
    for chapter in pipeline.get("chapters", []):
        if chapter.get("chapterReadingStatus") == "running":
            chapter.update({
                "chapterReadingStatus": "pending",
                "chapterReadingError": diagnostic,
                "interruptedAt": interrupted_at,
            })
    for stage in pipeline.get("stages", []):
        if stage.get("status") == "running":
            stage.update({"status": "pending", "detail": "Interrupted before completion; waiting to retry automatically.", "lastInterruption": diagnostic})
            stage.pop("error", None)
    child_statuses = (
        ("status", "error"),
        ("emotionStatus", "emotionError"),
        ("tagStatus", "tagError"),
        ("smellStatus", "smellError"),
        ("contextStatus", "contextError"),
        ("llmReviewStatus", "llmReviewError"),
    )
    for chapter in pipeline.get("chapters", []):
        for status_key, error_key in child_statuses:
            if chapter.get(status_key) != "running":
                continue
            chapter.update({status_key: "pending", error_key: diagnostic, "interruptedAt": interrupted_at})
            if status_key == "status":
                chapter.pop("completedAt", None)
                chapter.pop("durationSeconds", None)
    for chunk in pipeline.get("chunks", []):
        if chunk.get("dossierStatus") != "running":
            continue
        chunk.update({"dossierStatus": "pending", "dossierError": diagnostic, "interruptedAt": interrupted_at})
        try:
            artifact = json.loads((chunk_artifacts_path(book) / f"{int(chunk.get('sequence')):04d}.json").read_text(encoding="utf-8"))
            artifact.update({"dossierStatus": "pending", "dossierError": diagnostic, "interruptedAt": interrupted_at})
            write_chunk_artifact(book, int(chunk.get("sequence")), artifact)
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            pass
    return True


def migrate_manual_interruption(pipeline: dict[str, object]) -> bool:
    """Remove the old debugging-era Continue gate from saved ledgers."""
    changed = False
    recoveries = pipeline.get("recoveryDiagnostics") if isinstance(pipeline.get("recoveryDiagnostics"), list) else []
    for recovery in recoveries:
        if not isinstance(recovery, dict) or "Press Continue" not in str(recovery.get("message") or ""):
            continue
        recovery["message"] = "The local model's previous reading process ended without returning a result. Bookinator returned that task to the queue."
        changed = True
    if pipeline.get("phase") != "interrupted":
        return changed
    diagnostic = str(pipeline.get("error") or "")
    if "previous reading process ended" not in diagnostic and "previous manuscript-preparation process ended" not in diagnostic:
        return False
    interrupted_at = str(pipeline.get("updatedAt") or utc_now())
    recovery_note = (
        "The previous manuscript-preparation process ended before it recorded completion. Bookinator returned that task to the queue."
        if "manuscript-preparation" in diagnostic
        else "The local model's previous reading process ended without returning a result. Bookinator returned that task to the queue."
    )
    recoveries.append({"at": interrupted_at, "phase": "interrupted", "message": recovery_note})
    pipeline["recoveryDiagnostics"] = recoveries[-20:]
    pipeline.update({
        "status": "ready",
        "phase": "recovering",
        "message": "The interrupted task is back in the automatic queue. Completed work is safe; independent work can continue.",
        "updatedAt": utc_now(),
    })
    pipeline.pop("error", None)
    pipeline.pop("workerPid", None)
    for stage in pipeline.get("stages", []):
        if stage.get("status") == "warning" and (
            "previous reading process ended" in str(stage.get("detail") or "")
            or "previous manuscript-preparation process ended" in str(stage.get("detail") or "")
        ):
            stage.update({"status": "pending", "detail": "Interrupted before completion; waiting to retry automatically.", "lastInterruption": recovery_note})
            stage.pop("error", None)
    return True


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
    # Internal callers need the durable identity record, not a recursively
    # hydrated library row. Hydrating every book here made a single book-page
    # request read every pipeline before reading the requested pipeline again.
    return next((book for book in load_library_records() if book.get("id") == book_id), None)


def saved_report_index_path(book_id: str) -> Path:
    return REPORTS_ROOT / book_id / "index.json"


def load_saved_reports(book_id: str) -> list[dict[str, object]]:
    try:
        records = json.loads(saved_report_index_path(book_id).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return [record for record in records if isinstance(record, dict)] if isinstance(records, list) else []


def write_saved_reports(book_id: str, records: list[dict[str, object]]) -> None:
    root = REPORTS_ROOT / book_id
    root.mkdir(parents=True, exist_ok=True)
    target = root / "index.json"
    temporary = root / "index.json.tmp"
    temporary.write_text(json.dumps(records, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(target)


def saved_report_path(book_id: str, artifact_id: str, extension: str) -> Path:
    return REPORTS_ROOT / book_id / f"{artifact_id}.{extension}"


def annotations_path(book: dict[str, object]) -> Path:
    manuscript_id = str(book.get("manuscriptId") or "")
    return BOOKS_ROOT / manuscript_id / "annotations.json"


def reviewer_signoff_path(book: dict[str, object]) -> Path:
    manuscript_id = str(book.get("manuscriptId") or "")
    return BOOKS_ROOT / manuscript_id / "reviewer-signoff.json"


def load_reviewer_signoff(book: dict[str, object]) -> dict[str, object]:
    try:
        payload = json.loads(reviewer_signoff_path(book).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"schema": REVIEWER_SIGNOFF_SCHEMA_VERSION, "status": "open", "reviewerName": "", "notes": ""}
    if not isinstance(payload, dict):
        return {"schema": REVIEWER_SIGNOFF_SCHEMA_VERSION, "status": "open", "reviewerName": "", "notes": ""}
    return {
        "schema": REVIEWER_SIGNOFF_SCHEMA_VERSION,
        "status": "complete" if payload.get("status") == "complete" else "open",
        "reviewerName": str(payload.get("reviewerName") or "")[:200],
        "notes": str(payload.get("notes") or "")[:12_000],
        "completedAt": str(payload.get("completedAt") or ""),
        "updatedAt": str(payload.get("updatedAt") or ""),
    }


def save_reviewer_signoff(book: dict[str, object], payload: dict[str, object]) -> dict[str, object]:
    previous = load_reviewer_signoff(book)
    status = str(payload.get("status") or "").strip().casefold()
    if status not in {"open", "complete"}:
        raise ValueError("Choose whether this review is open or complete.")
    reviewer_name = str(payload.get("reviewerName", previous.get("reviewerName") or "")).strip()
    notes = str(payload.get("notes", previous.get("notes") or "")).strip()
    if len(reviewer_name) > 200:
        raise ValueError("Reviewer names must be 200 characters or fewer.")
    if len(notes) > 12_000:
        raise ValueError("General review notes must be 12,000 characters or fewer.")
    if status == "complete" and not reviewer_name:
        raise ValueError("Enter the reviewer’s name before signing off.")
    now = utc_now()
    result = {
        "schema": REVIEWER_SIGNOFF_SCHEMA_VERSION,
        "status": status,
        "reviewerName": reviewer_name,
        "notes": notes,
        "completedAt": now if status == "complete" else str(previous.get("completedAt") or ""),
        "updatedAt": now,
    }
    target = reviewer_signoff_path(book)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(target)
    return result


def load_annotations(book: dict[str, object]) -> list[dict[str, object]]:
    try:
        payload = json.loads(annotations_path(book).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(payload, list):
        return []
    annotations: list[dict[str, object]] = []
    for saved in payload:
        if not isinstance(saved, dict):
            continue
        annotation = dict(saved)
        categories = normalize_annotation_categories(annotation)
        annotation.update({"schema": ANNOTATION_SCHEMA_VERSION, "category": categories[0], "categories": categories})
        annotations.append(annotation)
    return annotations


def write_annotations(book: dict[str, object], annotations: list[dict[str, object]]) -> None:
    target = annotations_path(book)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(annotations, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(target)


def normalize_annotation_categories(payload: dict[str, object], *, strict: bool = False) -> list[str]:
    supplied = payload.get("categories")
    values = supplied if isinstance(supplied, list) else [payload.get("category")]
    categories: list[str] = []
    for value in values:
        category = str(value or "").strip().casefold().replace(" ", "_")
        if not category:
            continue
        if category not in ANNOTATION_CATEGORIES:
            if strict:
                raise ValueError("Choose valid annotation categories.")
            continue
        if category not in categories:
            categories.append(category)
    if strict and not categories:
        raise ValueError("Choose at least one annotation category.")
    return categories or ["editorial"]


def create_annotation(book: dict[str, object], payload: dict[str, object], *, machine_origin: dict[str, object] | None = None) -> dict[str, object]:
    sequence = int(payload.get("chapterSequence") or 0)
    chapter = load_chapter_source(book, sequence)
    if not chapter:
        raise ValueError("That chapter source is not available.")
    text = str(chapter.get("text") or chapter.get("markdown") or "")
    start = int(payload.get("characterStart") or 0)
    end = int(payload.get("characterEnd") or 0)
    if start < 0 or end <= start or end > len(text) or end - start > 8_000:
        raise ValueError("Select a passage of no more than 8,000 characters.")
    quote = text[start:end]
    supplied_quote = str(payload.get("quote") or "")
    if supplied_quote and re.sub(r"\s+", " ", supplied_quote).strip() != re.sub(r"\s+", " ", quote).strip():
        raise ValueError("The selected passage no longer matches the saved chapter text.")
    comment = str(payload.get("comment") or "").strip()
    if not comment or len(comment) > 12_000:
        raise ValueError("Write an editorial comment of no more than 12,000 characters.")
    categories = normalize_annotation_categories(payload)
    priority = str(payload.get("priority") or "normal").strip().casefold()
    if priority not in {"low", "normal", "high"}:
        priority = "normal"
    created_at = utc_now()
    context_radius = 96
    annotation = {
        "schema": ANNOTATION_SCHEMA_VERSION,
        "id": uuid.uuid4().hex,
        "chapterSequence": sequence,
        "chapterLabel": str(chapter.get("title") or f"Section {sequence}"),
        "chapterTitle": str(chapter.get("chapterTitle") or ""),
        "pageStart": chapter.get("pageStart"),
        "pageEnd": chapter.get("pageEnd"),
        "characterStart": start,
        "characterEnd": end,
        "quote": quote,
        "prefix": text[max(0, start - context_radius):start],
        "suffix": text[end:min(len(text), end + context_radius)],
        "anchorFingerprint": hashlib.sha256(f"{text[max(0, start - context_radius):min(len(text), end + context_radius)]}".encode("utf-8")).hexdigest(),
        "comment": comment,
        "category": categories[0],
        "categories": categories,
        "priority": priority,
        "status": "open",
        "createdAt": created_at,
        "updatedAt": created_at,
    }
    if machine_origin:
        annotation["origin"] = {
            "kind": "llm-review-proposal",
            "proposalId": str(machine_origin.get("proposalId") or ""),
            "model": str(machine_origin.get("model") or ""),
            "promptVersion": str(machine_origin.get("promptVersion") or LLM_REVIEW_PROMPT_VERSION),
            "acceptedAt": created_at,
        }
    with ANNOTATIONS_LOCK:
        annotations = load_annotations(book)
        annotations.append(annotation)
        write_annotations(book, annotations)
    return annotation


def decide_llm_review_proposal(book: dict[str, object], proposal_id: str, action: str, category: str = "") -> dict[str, object]:
    """Record a durable human decision without turning undecided model output into authorship."""
    if action not in {"accept", "reject", "reopen", "categorize"}:
        raise ValueError("Choose accept, reject, reopen, or categorize for this proposal.")
    if action == "categorize" and category not in ANNOTATION_CATEGORIES:
        raise ValueError("Choose a valid editorial category.")
    pipeline = load_pipeline(book)
    chapter = next((
        item for item in pipeline.get("chapters", [])
        if any(str(proposal.get("id") or "") == proposal_id for proposal in (item.get("llmReview") or {}).get("editorialProposals", []))
    ), None)
    if not chapter:
        raise LookupError("That LLM Review proposal is not available.")
    review = chapter.get("llmReview") if isinstance(chapter.get("llmReview"), dict) else {}
    proposal = next((item for item in review.get("editorialProposals", []) if str(item.get("id") or "") == proposal_id), None)
    if not proposal:
        raise LookupError("That LLM Review proposal is not available.")
    current_status = str(proposal.get("status") or "proposed")
    if current_status == "accepted" and action not in {"accept", "categorize"}:
        raise ValueError("This proposal already became a human annotation. Edit or archive that annotation instead.")
    now = utc_now()
    annotation: dict[str, object] | None = None
    if action == "categorize":
        proposal["category"] = category
        proposal["decisionAt"] = now
    elif action == "accept":
        annotation_id = str(proposal.get("annotationId") or "")
        annotation = next((item for item in load_annotations(book) if str(item.get("id") or "") == annotation_id), None)
        if not annotation:
            sequence = int(chapter.get("sequence") or chapter.get("number") or 0)
            annotation = create_annotation(book, {
                "chapterSequence": sequence,
                "characterStart": proposal.get("characterStart"),
                "characterEnd": proposal.get("characterEnd"),
                "quote": proposal.get("quote"),
                "comment": proposal.get("comment"),
                "categories": [proposal.get("category") or "editorial"],
                "priority": proposal.get("priority") or "normal",
            }, machine_origin={
                "proposalId": proposal_id,
                "model": chapter.get("llmReviewModel"),
                "promptVersion": LLM_REVIEW_PROMPT_VERSION,
            })
        proposal.update({"status": "accepted", "decisionAt": now, "annotationId": annotation.get("id")})
    elif action == "reject":
        proposal.update({"status": "rejected", "decisionAt": now})
        proposal.pop("annotationId", None)
    else:
        proposal.update({"status": "proposed", "decisionAt": now})
        proposal.pop("annotationId", None)

    sequence = int(chapter.get("sequence") or chapter.get("number") or 0)
    artifact = read_json_artifact(llm_review_result_path(book, sequence))
    if isinstance(artifact.get("result"), dict):
        artifact["result"] = review
        artifact["humanDecisionAt"] = now
        write_json_artifact(llm_review_result_path(book, sequence), artifact)
    write_pipeline(book, pipeline)
    return {"proposal": proposal, "annotation": annotation}


def promote_llm_review_candidate(book: dict[str, object], chapter_sequence: int, candidate_index: int) -> dict[str, object]:
    """Let a human rescue a counter-review demotion into Reviewer with provenance intact."""
    pipeline = load_pipeline(book)
    chapter = next((
        item for item in pipeline.get("chapters", [])
        if int(item.get("sequence") or item.get("number") or 0) == chapter_sequence
    ), None)
    if not chapter:
        raise LookupError("That LLM Review chapter is not available.")
    review = chapter.get("llmReview") if isinstance(chapter.get("llmReview"), dict) else {}
    candidates = review.get("rejectedCandidates") if isinstance(review.get("rejectedCandidates"), list) else []
    if candidate_index < 0 or candidate_index >= len(candidates) or not isinstance(candidates[candidate_index], dict):
        raise LookupError("That soft lead is not available.")
    candidate = candidates[candidate_index]
    if candidate.get("status") == "accepted" and candidate.get("annotationId"):
        annotation = next((item for item in load_annotations(book) if item.get("id") == candidate.get("annotationId")), None)
        return {"candidate": candidate, "annotation": annotation}
    source = load_chapter_source(book, chapter_sequence)
    if not source:
        raise ValueError("That chapter source is not available.")
    text = str(source.get("text") or source.get("markdown") or "")
    quote = str(candidate.get("quote") or "").strip()
    start = int(candidate.get("characterStart")) if candidate.get("characterStart") is not None else -1
    end = int(candidate.get("characterEnd")) if candidate.get("characterEnd") is not None else -1
    if not quote:
        raise ValueError("The saved soft lead does not include a source quotation.")
    if start < 0 or end <= start or re.sub(r"\s+", " ", text[start:end]).strip() != re.sub(r"\s+", " ", quote).strip():
        start = text.find(quote)
        end = start + len(quote) if start >= 0 else -1
    if start < 0:
        flexible = re.compile(r"\s+".join(re.escape(part) for part in quote.split()), re.MULTILINE)
        match = flexible.search(text)
        if match:
            start, end = match.span()
    if start < 0 or end <= start:
        raise ValueError("The saved soft lead no longer matches the chapter source.")
    candidate_id = hashlib.sha256(f"{chapter_sequence}:{candidate_index}:{quote}".encode("utf-8")).hexdigest()[:32]
    annotation = create_annotation(book, {
        "chapterSequence": chapter_sequence,
        "characterStart": start,
        "characterEnd": end,
        "quote": text[start:end],
        "comment": candidate.get("comment") or "Reconsider this first-reader concern.",
        "categories": [candidate.get("category") or "editorial"],
        "priority": candidate.get("priority") or "low",
    }, machine_origin={
        "proposalId": candidate_id,
        "model": chapter.get("llmReviewModel"),
        "promptVersion": LLM_REVIEW_PROMPT_VERSION,
    })
    candidate.update({"id": candidate_id, "status": "accepted", "decisionAt": utc_now(), "annotationId": annotation.get("id")})
    artifact = read_json_artifact(llm_review_result_path(book, chapter_sequence))
    if isinstance(artifact.get("result"), dict):
        artifact["result"] = review
        artifact["humanDecisionAt"] = candidate["decisionAt"]
        write_json_artifact(llm_review_result_path(book, chapter_sequence), artifact)
    write_pipeline(book, pipeline)
    return {"candidate": candidate, "annotation": annotation}


def decide_llm_review_candidate(book: dict[str, object], chapter_sequence: int, candidate_index: int, action: str, category: str = "") -> dict[str, object]:
    """Triage a counter-review soft lead without falsely attributing it to a human reviewer."""
    if action not in {"dismiss", "promote", "reopen", "categorize"}:
        raise ValueError("Choose dismiss, promote, reopen, or categorize for this soft lead.")
    if action == "categorize" and category not in ANNOTATION_CATEGORIES:
        raise ValueError("Choose a valid editorial category.")
    pipeline = load_pipeline(book)
    chapter = next((
        item for item in pipeline.get("chapters", [])
        if int(item.get("sequence") or item.get("number") or 0) == chapter_sequence
    ), None)
    if not chapter:
        raise LookupError("That LLM Review chapter is not available.")
    review = chapter.get("llmReview") if isinstance(chapter.get("llmReview"), dict) else {}
    candidates = review.get("rejectedCandidates") if isinstance(review.get("rejectedCandidates"), list) else []
    if candidate_index < 0 or candidate_index >= len(candidates) or not isinstance(candidates[candidate_index], dict):
        raise LookupError("That soft lead is not available.")
    candidate = candidates[candidate_index]
    quote = str(candidate.get("quote") or "").strip()
    candidate_id = str(candidate.get("id") or hashlib.sha256(f"{chapter_sequence}:{candidate_index}:{quote}".encode("utf-8")).hexdigest()[:32])
    candidate["id"] = candidate_id
    now = utc_now()
    proposal: dict[str, object] | None = None

    if action == "categorize":
        candidate["category"] = category
        candidate["decisionAt"] = now
        proposal_id = str(candidate.get("proposalId") or "")
        if proposal_id:
            proposal = next((item for item in review.get("editorialProposals", []) if isinstance(item, dict) and str(item.get("id") or "") == proposal_id), None)
            if proposal is not None:
                proposal["category"] = category
                proposal["decisionAt"] = now
    elif action == "dismiss":
        candidate.update({"status": "dismissed", "decisionAt": now})
        candidate.pop("proposalId", None)
    elif action == "reopen":
        candidate.update({"status": "rejected_by_model", "decisionAt": now})
        candidate.pop("proposalId", None)
    else:
        source = load_chapter_source(book, chapter_sequence)
        if not source:
            raise ValueError("That chapter source is not available.")
        text = str(source.get("text") or source.get("markdown") or "")
        start = int(candidate.get("characterStart")) if candidate.get("characterStart") is not None else -1
        end = int(candidate.get("characterEnd")) if candidate.get("characterEnd") is not None else -1
        if not quote:
            raise ValueError("The saved soft lead does not include a source quotation.")
        if start < 0 or end <= start or re.sub(r"\s+", " ", text[start:end]).strip() != re.sub(r"\s+", " ", quote).strip():
            match = re.compile(r"\s+".join(re.escape(part) for part in quote.split()), re.MULTILINE).search(text)
            if not match:
                raise ValueError("The saved soft lead no longer matches the chapter source.")
            start, end = match.span()
        proposal_id = hashlib.sha256(f"promoted:{candidate_id}".encode("utf-8")).hexdigest()[:32]
        proposals = review.setdefault("editorialProposals", [])
        proposal = next((item for item in proposals if isinstance(item, dict) and str(item.get("id") or "") == proposal_id), None)
        if proposal is None:
            proposal = {
                "id": proposal_id,
                "quote": text[start:end],
                "characterStart": start,
                "characterEnd": end,
                "category": candidate.get("category") or "editorial",
                "priority": candidate.get("priority") or "normal",
                "comment": candidate.get("comment") or "Reconsider this first-reader concern.",
                "confidence": candidate.get("confidence"),
                "readerEffect": candidate.get("readerEffect") or candidate.get("whyItMatters") or "",
                "intentionalityCheck": candidate.get("intentionalityCheck") or "",
                "revisionGoal": candidate.get("revisionGoal") or candidate.get("suggestion") or "",
                "adjudicationReason": candidate.get("reason") or "The counter-review originally demoted this concern.",
                "origin": "human_promoted_soft_lead",
                "status": "proposed",
                "promotedAt": now,
            }
            proposals.append(proposal)
        candidate.update({"status": "promoted", "decisionAt": now, "proposalId": proposal_id})
        if review.get("editorialVerdict") != "material_concerns_found":
            review["editorialVerdict"] = "material_concerns_found"
            review["editorialSummary"] = "A soft lead was promoted for significant editorial consideration."

    artifact = read_json_artifact(llm_review_result_path(book, chapter_sequence))
    if isinstance(artifact.get("result"), dict):
        artifact["result"] = review
        artifact["humanDecisionAt"] = now
        write_json_artifact(llm_review_result_path(book, chapter_sequence), artifact)
    write_pipeline(book, pipeline)
    return {"candidate": candidate, "proposal": proposal}


def update_annotation(book: dict[str, object], annotation_id: str, payload: dict[str, object]) -> dict[str, object]:
    with ANNOTATIONS_LOCK:
        annotations = load_annotations(book)
        annotation = next((item for item in annotations if str(item.get("id") or "") == annotation_id), None)
        if not annotation:
            raise LookupError("That annotation is not available.")
        if "comment" in payload:
            comment = str(payload.get("comment") or "").strip()
            if not comment or len(comment) > 12_000:
                raise ValueError("Write an editorial comment of no more than 12,000 characters.")
            annotation["comment"] = comment
        if "categories" in payload or "category" in payload:
            categories = normalize_annotation_categories(payload, strict=True)
            annotation["category"] = categories[0]
            annotation["categories"] = categories
        if "priority" in payload:
            priority = str(payload.get("priority") or "").strip().casefold()
            if priority not in {"low", "normal", "high"}:
                raise ValueError("Choose a valid annotation priority.")
            annotation["priority"] = priority
        if "status" in payload:
            status = str(payload.get("status") or "").strip().casefold()
            if status not in {"open", "archived"}:
                raise ValueError("Choose active or archived.")
            annotation["status"] = status
        annotation["updatedAt"] = utc_now()
        write_annotations(book, annotations)
    return annotation


def delete_annotation(book: dict[str, object], annotation_id: str) -> dict[str, object]:
    with ANNOTATIONS_LOCK:
        annotations = load_annotations(book)
        annotation = next((item for item in annotations if str(item.get("id") or "") == annotation_id), None)
        if not annotation:
            raise LookupError("That annotation is not available.")
        write_annotations(book, [item for item in annotations if str(item.get("id") or "") != annotation_id])
    return annotation


def pipeline_path(book: dict[str, object]) -> Path | None:
    manuscript_id = str(book.get("manuscriptId") or "")
    return BOOKS_ROOT / manuscript_id / "pipeline.json" if manuscript_id else None


def append_pipeline_event(book: dict[str, object], event: str, **details: object) -> None:
    """Append a small forensic record for destructive or rejected transitions."""
    path = pipeline_path(book)
    if not path:
        return
    record = {
        "at": utc_now(),
        "event": event,
        "bookId": book.get("id"),
        "pid": os.getpid(),
        "thread": threading.current_thread().name,
        **details,
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with (path.parent / "pipeline-events.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError:
        pass


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


def new_pipeline(book: dict[str, object]) -> dict[str, object]:
    """Return an empty analysis ledger for a preserved manuscript source."""
    pipeline: dict[str, object] = {
        "bookId": book.get("id"),
        "status": "ready",
        "message": "The manuscript is saved and ready for its first reading.",
        "stages": [
            {"id": "source", "label": "Source document", "status": "complete", "detail": "The uploaded source is preserved locally."},
            {"id": "extraction", "label": "Page extraction", "status": "pending", "detail": "Preserve text with source-page provenance."},
            {"id": "structure", "label": "Chapter detection", "status": "pending", "detail": "Find likely chapter boundaries for review."},
            {"id": "chapter-archive", "label": "Saved chapter objects", "status": "pending", "detail": "Write one durable local object per ordered manuscript section."},
            {"id": "chunking", "label": "Source chunks", "status": "pending", "detail": "Create page-linked processing units without replacing chapter structure."},
            {"id": "gliner-signals", "label": "GLiNER signals", "status": "pending", "detail": PIPELINE_STAGE_DEFINITIONS["gliner-signals"][1]},
            {"id": "summaries", "label": "Chapter summaries", "status": "pending", "detail": "Read each chapter with the assigned local model."},
            {"id": "emotions", "label": "Chapter emotions", "status": "pending", "detail": PIPELINE_STAGE_DEFINITIONS["emotions"][1]},
            {"id": "tags", "label": "Chapter tags", "status": "pending", "detail": PIPELINE_STAGE_DEFINITIONS["tags"][1]},
            {"id": "smells", "label": "Smells", "status": "pending", "detail": PIPELINE_STAGE_DEFINITIONS["smells"][1]},
            {"id": "dossiers", "label": "Chunk dossiers", "status": "pending", "detail": "Build evidence-linked records from every source chunk."},
        ],
        "chapters": [],
    }
    update_source_stage(book, pipeline["stages"])
    ensure_llm_review_stages(book, pipeline)
    return pipeline


def pipeline_read_failure(book: dict[str, object], error: BaseException) -> dict[str, object]:
    """Fail closed when a durable ledger cannot be read.

    Treating a transient or malformed ledger as a brand-new book lets the
    automatic queue run destructive preparation over recoverable work. A
    blocked ledger is noisier, but it preserves the evidence needed to repair
    the real failure.
    """
    append_pipeline_event(book, "ledger-read-failed", error=str(error)[:800] or type(error).__name__)
    return {
        "bookId": book.get("id"),
        "status": "blocked",
        "phase": "ledger-read-error",
        "message": "Bookinator could not safely read this book’s analysis ledger. The source and derived artifacts were left untouched.",
        "error": str(error)[:800] or type(error).__name__,
        "ledgerReadError": True,
        "stages": [],
        "chapters": [],
    }


def load_pipeline(book: dict[str, object]) -> dict[str, object]:
    path = pipeline_path(book)
    if not path:
        return {"bookId": book.get("id"), "status": "blocked", "message": "This book has no saved manuscript. Drop the PDF in again to begin analysis.", "stages": [], "chapters": []}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            return {}
        ensure_signal_stages(payload)
        completed_reading_changed = reconcile_completed_chapter_readings(book, payload)
        llm_review_stages_changed = ensure_llm_review_stages(book, payload)
        legacy_prose_changed = remove_legacy_prose_analysis(payload)
        development_checkpoint_changed = reconcile_development_checkpoint(book, payload)
        manual_interruption_changed = migrate_manual_interruption(payload)
        interrupted_worker_changed = repair_orphaned_pipeline(book, payload)
        orphaned_child_changed = reconcile_orphaned_child_runs(payload)
        before = json.dumps({key: payload.get(key) for key in ("wholeBookSummary", "wholeBookDossier", "questionTracker", "wholeBookLlmReview")}, sort_keys=True)
        active_rollup_phase = str(payload.get("phase") or "") if pipeline_worker_is_alive(str(book.get("id") or ""), payload) else ""
        reset_inactive_whole_book_runs(payload, active_rollup_phase)
        orphaned_child_changed = orphaned_child_changed or before != json.dumps({key: payload.get(key) for key in ("wholeBookSummary", "wholeBookDossier", "questionTracker", "wholeBookLlmReview")}, sort_keys=True)
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
        heading_metadata_changed = classify_heading_report(payload.get("chapterHeadingReport", {}), payload.get("chapters", [])) or heading_metadata_changed
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
                structure.update({"status": "warning", "detail": f"Proposed map needs review: {'; '.join(warnings)} Derived analysis is paused until the structure is resolved."})
        else:
            structure = next((stage for stage in payload.get("stages", []) if stage.get("id") == "structure"), None)
            if structure and structure.get("status") == "warning" and str(structure.get("detail") or "").startswith("Proposed map needs review:"):
                structure.update({"status": "complete", "detail": f"Detected {len(payload.get('chapters', []))} sections; every competing opener is explained by the accepted structure."})
                heading_metadata_changed = True
        if payload.get("phase") in {"preparing", "extraction", "chapter-map", "chapter-archive", "chunking"}:
            if llm_review_stages_changed or legacy_prose_changed or (heading_metadata_changed and payload.get("status") != "running"):
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
        tracker = payload.get("questionTracker") if isinstance(payload.get("questionTracker"), dict) else {}
        previous_question_signature = str(tracker.get("inputSignature") or "")
        if tracker.get("status") == "complete":
            question_tracker_is_current(payload, tracker)
        question_signature_migrated = previous_question_signature != str(tracker.get("inputSignature") or "")
        if completed_reading_changed or llm_review_stages_changed or legacy_prose_changed or development_checkpoint_changed or manual_interruption_changed or interrupted_worker_changed or orphaned_child_changed or question_signature_migrated or (heading_metadata_changed and payload.get("status") != "running"):
            write_pipeline(book, payload)
        return payload
    except FileNotFoundError as error:
        # A manuscript that has never entered the pipeline legitimately has no
        # ledger. Missing pipeline.json beside durable derived artifacts is a
        # recovery incident and must not masquerade as first-time ingestion.
        project = path.parent
        has_derived_artifacts = (
            (project / "extracted-chapters.json").is_file()
            or (project / "chapters" / "manifest.json").is_file()
            or (project / "chunks" / "manifest.json").is_file()
        )
        return pipeline_read_failure(book, error) if has_derived_artifacts else new_pipeline(book)
    except (OSError, json.JSONDecodeError) as error:
        return pipeline_read_failure(book, error)


def development_write_boundary(pipeline: dict[str, object]) -> int:
    """Return the highest sequence protected by a bounded development run."""
    try:
        limit = int(pipeline.get("developmentAnalysisLimit") or 0)
    except (TypeError, ValueError):
        limit = 0
    try:
        preserved = int(pipeline.get("developmentPreservedThroughSequence") or 0)
    except (TypeError, ValueError):
        preserved = 0
    return max(limit, preserved)


def write_pipeline(book: dict[str, object], pipeline: dict[str, object]) -> None:
    """Serialize ledger writes so an older worker cannot replace newer state."""
    with PIPELINE_WRITE_LOCK:
        _write_pipeline_locked(book, pipeline)


def _write_pipeline_locked(book: dict[str, object], pipeline: dict[str, object]) -> None:
    path = pipeline_path(book)
    if not path:
        return
    # Long model calls retain an in-memory pipeline for minutes. A reviewer may
    # approve or edit the chapter map during that call; never let the older
    # worker snapshot overwrite the newer human structural decision.
    try:
        persisted = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        persisted = {}
    # A bounded regression run is a destructive-analysis boundary chosen by a
    # human. Model workers can retain an in-memory ledger for many minutes; if
    # one began before that boundary was created or advanced, its eventual
    # write must not replace the newer ledger wholesale. Intentional full
    # resets unlink pipeline.json before writing, so rejecting this stale write
    # does not interfere with the explicit reset path.
    persisted_boundary = development_write_boundary(persisted) if isinstance(persisted, dict) else 0
    incoming_boundary = development_write_boundary(pipeline)
    if persisted_boundary > incoming_boundary:
        append_pipeline_event(
            book, "stale-write-rejected", reason="development-boundary",
            persistedBoundary=persisted_boundary, incomingBoundary=incoming_boundary,
        )
        return
    try:
        persisted_revision = int(persisted.get("ledgerRevision") or 0) if isinstance(persisted, dict) else 0
    except (TypeError, ValueError):
        persisted_revision = 0
    try:
        incoming_revision = int(pipeline.get("ledgerRevision") or 0)
    except (TypeError, ValueError):
        incoming_revision = 0
    persisted_decision = str(persisted.get("chapterMapDecisionAt") or persisted.get("chapterMapApprovedAt") or "") if isinstance(persisted, dict) else ""
    incoming_decision = str(pipeline.get("chapterMapDecisionAt") or pipeline.get("chapterMapApprovedAt") or "")
    if persisted_decision and persisted_decision > incoming_decision:
        for key in (
            "chapterMapApproved", "chapterMapApprovedAt", "chapterMapDecisionAt",
            "chapterMapApprovalAfterRebuild", "acceptedChapterLabelVariants",
            "demotedChapterBoundaryPages",
        ):
            if key in persisted:
                pipeline[key] = copy.deepcopy(persisted[key])
            else:
                pipeline.pop(key, None)
        pipeline["analysisProvisional"] = bool(pipeline.get("chapterMapWarnings") or not pipeline.get("chapterMapApproved"))
    # The LLM Review worker also holds a long-lived snapshot. Human proposal
    # decisions made while it advances through later chapters must win over
    # that older snapshot just as chapter-map decisions do.
    persisted_chapters = {
        int(chapter.get("sequence") or chapter.get("number") or 0): chapter
        for chapter in persisted.get("chapters", [])
        if isinstance(chapter, dict)
    } if isinstance(persisted, dict) else {}
    for chapter in pipeline.get("chapters", []):
        saved_chapter = persisted_chapters.get(int(chapter.get("sequence") or chapter.get("number") or 0))
        incoming_review = chapter.get("llmReview") if isinstance(chapter.get("llmReview"), dict) else {}
        saved_review = saved_chapter.get("llmReview") if isinstance(saved_chapter, dict) and isinstance(saved_chapter.get("llmReview"), dict) else {}
        incoming_proposals = {str(item.get("id") or ""): item for item in incoming_review.get("editorialProposals", []) if isinstance(item, dict)}
        for saved_proposal in saved_review.get("editorialProposals", []):
            if not isinstance(saved_proposal, dict):
                continue
            proposal = incoming_proposals.get(str(saved_proposal.get("id") or ""))
            if proposal is None and saved_proposal.get("origin") == "human_promoted_soft_lead":
                incoming_review.setdefault("editorialProposals", []).append(copy.deepcopy(saved_proposal))
                continue
            if proposal is None or str(saved_proposal.get("decisionAt") or "") <= str(proposal.get("decisionAt") or ""):
                continue
            for key in ("status", "decisionAt", "annotationId"):
                if key in saved_proposal:
                    proposal[key] = copy.deepcopy(saved_proposal[key])
                else:
                    proposal.pop(key, None)
        incoming_candidates = incoming_review.get("rejectedCandidates", []) if isinstance(incoming_review.get("rejectedCandidates"), list) else []
        for saved_index, saved_candidate in enumerate(saved_review.get("rejectedCandidates", [])):
            if not isinstance(saved_candidate, dict) or not saved_candidate.get("decisionAt"):
                continue
            candidate = next((
                item for item in incoming_candidates if isinstance(item, dict) and (
                    (saved_candidate.get("id") and item.get("id") == saved_candidate.get("id"))
                    or (item.get("quote") == saved_candidate.get("quote") and item.get("comment") == saved_candidate.get("comment"))
                )
            ), incoming_candidates[saved_index] if saved_index < len(incoming_candidates) and isinstance(incoming_candidates[saved_index], dict) else None)
            if candidate is None or str(saved_candidate.get("decisionAt") or "") <= str(candidate.get("decisionAt") or ""):
                continue
            for key in ("id", "status", "decisionAt", "proposalId"):
                if key in saved_candidate:
                    candidate[key] = copy.deepcopy(saved_candidate[key])
                else:
                    candidate.pop(key, None)
    reconcile_orphaned_child_runs(pipeline)
    for chapter in pipeline.get("chapters", []):
        sanitize_chapter_headings(chapter)
    ensure_signal_stages(pipeline)
    remove_legacy_prose_analysis(pipeline)
    pipeline["ledgerRevision"] = max(persisted_revision, incoming_revision) + 1
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(json.dumps(pipeline, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def reset_book_pipeline(book: dict[str, object]) -> dict[str, object]:
    """Discard derived analysis and return one preserved source to ingestion."""
    book_id = str(book.get("id") or "")
    manuscript_id = str(book.get("manuscriptId") or "")
    project_root = BOOKS_ROOT / manuscript_id
    if not book_id or not manuscript_id or project_root.parent != BOOKS_ROOT:
        raise ValueError("This book does not have a resettable manuscript project.")

    pipeline_file = pipeline_path(book)
    previous = {}
    try:
        previous = json.loads(pipeline_file.read_text(encoding="utf-8")) if pipeline_file else {}
    except (OSError, json.JSONDecodeError):
        pass
    append_pipeline_event(
        book, "analysis-reset",
        reason="explicit-start-over",
        previousRunId=previous.get("runId") if isinstance(previous, dict) else None,
        previousStatus=previous.get("status") if isinstance(previous, dict) else None,
        previousChapterCount=len(previous.get("chapters", [])) if isinstance(previous, dict) else 0,
    )
    if pipeline_file:
        pipeline_file.unlink(missing_ok=True)
    extracted_chapters_path(book).unlink(missing_ok=True)
    for derived_root in (
        chapter_artifacts_path(book), chunk_artifacts_path(book),
        project_root / "chapter-readings", project_root / "gliner-signals", project_root / "llm-review",
    ):
        if derived_root.parent == project_root and derived_root.is_dir():
            shutil.rmtree(derived_root)

    pauses = load_pipeline_task_pauses()
    if book_id in pauses:
        pauses.pop(book_id, None)
        save_pipeline_task_pauses(pauses)
    refreshes = load_deferred_analysis_refreshes()
    if book_id in refreshes:
        refreshes.pop(book_id, None)
        save_deferred_analysis_refreshes(refreshes)
    with QUEUE_LOCK:
        QUEUE_ACTIONS.pop(book_id, None)
        remove_queue_action(book_id)

    signoff = load_reviewer_signoff(book)
    save_reviewer_signoff(book, {
        "status": "open",
        "reviewerName": signoff.get("reviewerName") or "",
        "notes": signoff.get("notes") or "",
    })
    pipeline = new_pipeline(book)
    pipeline.update({"resetAt": utc_now(), "message": "Previous analysis was cleared. Source ingestion is first in line."})
    write_pipeline(book, pipeline)
    return pipeline


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


def chapter_map_review_ready(pipeline: dict[str, object]) -> bool:
    """Only expose structural decisions after the proposed map is stable."""
    chapters = pipeline.get("chapters", [])
    if not isinstance(chapters, list) or not chapters:
        return False
    structure = next(
        (stage for stage in pipeline.get("stages", []) if isinstance(stage, dict) and stage.get("id") == "structure"),
        {},
    )
    return structure.get("status") in {"complete", "warning"} and str(pipeline.get("phase") or "") not in {"preparing", "chapter-map"}


def add_pipeline_progress(pipeline: dict[str, object]) -> dict[str, object]:
    chapters = pipeline.get("chapters", [])
    if not isinstance(chapters, list) or not chapters:
        pipeline["chapterMapReviewReady"] = False
        pipeline["progress"] = {"completed": 0, "total": 0, "percent": 0, "etaSeconds": None}
        pipeline["emotionProgress"] = {"completed": 0, "total": 0, "percent": 0, "etaSeconds": None}
        pipeline["tagProgress"] = {"completed": 0, "total": 0, "percent": 0, "etaSeconds": None}
        pipeline["smellProgress"] = {"completed": 0, "total": 0, "percent": 0, "etaSeconds": None}
        pipeline["dossierProgress"] = {"completed": 0, "total": 0, "percent": 0, "etaSeconds": None}
        pipeline["contextProgress"] = {"completed": 0, "total": 0, "percent": 0, "etaSeconds": None}
        pipeline["llmReviewProgress"] = {"completed": 0, "total": 0, "percent": 0, "etaSeconds": None}
        pipeline["pipelineProgress"] = {"completed": 0, "total": 0, "percent": 0, "etaSeconds": None}
        pipeline["manuscriptMetrics"] = aggregate_manuscript_metrics([])
        return pipeline
    pipeline["chapterMapReviewReady"] = chapter_map_review_ready(pipeline)
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
    context_complete = sum(1 for chapter in manuscript_chapters if chapter.get("contextStatus") == "complete")
    llm_review_complete = sum(1 for chapter in manuscript_chapters if chapter.get("llmReviewStatus") == "complete")
    for prefix, output_key in (("context", "contextProgress"), ("llmReview", "llmReviewProgress")):
        complete_count = context_complete if prefix == "context" else llm_review_complete
        timed_items = [chapter for chapter in manuscript_chapters if chapter.get(f"{prefix}Status") == "complete" and chapter.get(f"{prefix}DurationSeconds")]
        durations = [float(chapter[f"{prefix}DurationSeconds"]) for chapter in timed_items[-5:]]
        remaining_count = total - complete_count
        pipeline[output_key] = {
            "completed": complete_count, "total": total,
            "percent": round(complete_count / total * 100) if total else 0,
            "etaSeconds": round(sum(durations) / len(durations) * remaining_count) if durations else None,
            "etaSampleSize": len(durations), "remainingChapters": remaining_count,
        }
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
    includes_llm_review = "cumulative-context" in stages and "llm-review" in stages
    pipeline_stage_count = 5 + int(includes_smells) + (2 if includes_llm_review else 0)
    whole_review_record = pipeline.get("wholeBookLlmReview") if isinstance(pipeline.get("wholeBookLlmReview"), dict) else {}
    whole_review_complete = includes_llm_review and whole_review_record.get("status") == "complete"
    pipeline_completed = structure_complete + summary_complete + emotion_complete + tag_complete + (smell_complete if includes_smells else 0) + dossier_chapters_complete + (context_complete + llm_review_complete + int(whole_review_complete) if includes_llm_review else 0)
    pipeline_total = len(manuscript_chapters) * pipeline_stage_count + int(includes_llm_review)
    remaining_progress = [
        pipeline["progress"],
        pipeline["dossierProgress"],
        pipeline["emotionProgress"],
        pipeline["tagProgress"],
        *([pipeline["smellProgress"]] if includes_smells else []),
        *([pipeline["contextProgress"], pipeline["llmReviewProgress"]] if includes_llm_review else []),
    ]
    unfinished_progress = [
        progress for progress in remaining_progress
        if int(progress.get("completed") or 0) < int(progress.get("total") or 0)
    ]
    estimated_progress = [
        progress for progress in unfinished_progress
        if isinstance(progress.get("etaSeconds"), (int, float))
    ]
    unestimated_stage_count = len(unfinished_progress) - len(estimated_progress)
    pipeline_eta_seconds = round(sum(float(progress["etaSeconds"]) for progress in estimated_progress)) if estimated_progress else None
    pipeline["pipelineProgress"] = {
        "completed": pipeline_completed,
        "total": pipeline_total,
        "percent": round(pipeline_completed / pipeline_total * 100) if pipeline_total else 0,
        "etaSeconds": pipeline_eta_seconds,
        "etaPartial": bool(estimated_progress and unestimated_stage_count),
        "etaEstimatedStageCount": len(estimated_progress),
        "etaUnestimatedStageCount": unestimated_stage_count,
        "stageCount": pipeline_stage_count,
        "stages": ["Chapters", "Summaries", "Dossiers", "Emotions", "Tags", *(["Smells"] if includes_smells else []), *(["Context", "LLM Review", "Whole-book LLM Review"] if includes_llm_review else [])],
        "chapterCount": len(manuscript_chapters),
        "basisLabel": (
            f"{pipeline_stage_count} current passes × {len(manuscript_chapters)} manuscript chapters · front matter excluded"
            + (" · 1 whole-book review synthesis" if includes_llm_review else "")
            + (f" · {unestimated_stage_count} unfinished {'pass is' if unestimated_stage_count == 1 else 'passes are'} still learning timing" if unestimated_stage_count else "")
        ),
        "etaLabel": None if estimated_progress else "Estimating after the first completed chapter in each remaining pass",
    }
    summary_signature = stage_rollup_input_signature(pipeline, "summary")
    whole_book_ready = bool(summary_signature and pipeline_stage_ready(pipeline, "whole-book-summary"))
    previous_whole_book = pipeline.get("wholeBookSummary") if isinstance(pipeline.get("wholeBookSummary"), dict) else {}
    previous_summary_result = latest_completed_rollup_result(pipeline, "wholeBookSummary", "wholeBookSummaryRuns")
    if previous_summary_result and not str(previous_whole_book.get("summary") or "").strip():
        previous_whole_book["previousResult"] = previous_summary_result
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
    review_signature = stage_rollup_input_signature(pipeline, "review")
    whole_review_ready = bool(review_signature and pipeline_stage_ready(pipeline, "whole-book-llm-review"))
    previous_whole_review = pipeline.get("wholeBookLlmReview") if isinstance(pipeline.get("wholeBookLlmReview"), dict) else {}
    previous_review_status = str(previous_whole_review.get("status") or "")
    whole_review_current = bool(review_signature and previous_whole_review.get("inputSignature") == review_signature)
    pipeline["wholeBookLlmReview"] = {
        **previous_whole_review,
        "status": previous_review_status if whole_review_ready and whole_review_current and previous_review_status in {"complete", "running", "failed"} else "ready" if whole_review_ready else "blocked",
        "dependsOn": list(PIPELINE_STAGE_DEPENDENCIES["whole-book-llm-review"]),
        "detail": "Every chapter review is current; whole-book editorial synthesis may run."
        if whole_review_ready else "Waiting for every chapter LLM Review to finish.",
    }
    whole_review_stage = stages.get("whole-book-llm-review")
    if whole_review_stage:
        whole_review_stage.update({
            "status": pipeline["wholeBookLlmReview"]["status"],
            "detail": pipeline["wholeBookLlmReview"]["detail"],
            **{key: pipeline["wholeBookLlmReview"][key] for key in ("model", "startedAt", "completedAt", "durationSeconds", "error") if pipeline["wholeBookLlmReview"].get(key) is not None},
        })
    question_signature = question_tracker_input_signature(pipeline)
    question_ready = bool(question_signature and pipeline_stage_ready(pipeline, "question-tracker"))
    previous_questions = pipeline.get("questionTracker") if isinstance(pipeline.get("questionTracker"), dict) else {}
    question_status = str(previous_questions.get("status") or "")
    question_current = question_tracker_is_current(pipeline, previous_questions, question_signature)
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
            else "Chapter summaries and dossiers are current; Questions & payoffs is ready for the queue."
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
    inference_total = len(inference_algorithms)
    inference_complete = sum(1 for algorithm in inference_algorithms if algorithm.get("status") == "complete")
    overall_progress = pipeline["pipelineProgress"]
    overall_progress["completed"] = int(overall_progress.get("completed") or 0) + inference_complete
    overall_progress["total"] = int(overall_progress.get("total") or 0) + inference_total
    overall_progress["percent"] = round(overall_progress["completed"] / overall_progress["total"] * 100) if overall_progress["total"] else 0
    overall_progress["inferenceCompleted"] = inference_complete
    overall_progress["inferenceTotal"] = inference_total
    overall_progress["basisLabel"] = f"{overall_progress.get('basisLabel') or ''} · {inference_total} whole-book inferences".strip(" ·")
    if inference_complete < inference_total and not unfinished_progress:
        overall_progress["etaLabel"] = "Whole-book inference work remains in the queue"
    stages_list = pipeline.setdefault("stages", [])
    stages_list[:] = [stage for stage in stages_list if stage.get("id") not in {"questions", "inferences"}]
    return pipeline


def opening_chapter_candidates(page_texts: list[str], allow_bare_numerals: bool = False) -> tuple[list[tuple[int, str]], list[tuple[int, str]]]:
    explicit_starts: list[tuple[int, str]] = []
    bare_numeral_starts: dict[str, list[tuple[int, str]]] = {"roman": [], "arabic": []}
    named_starts: list[tuple[int, str]] = []
    for page_index, text in enumerate(page_texts):
        opening_lines = [line.strip() for line in text.splitlines()[:25] if line.strip()]
        matches = []
        bare_numeral_on_page = False
        for line in opening_lines:
            markdown_heading = re.match(r"^#{1,6}[\t ]+(?P<title>.+?)\s*$", line)
            candidate = strip_markdown_heading(line)
            if re.fullmatch(r"chapter\s+(?:page|title|contents)", candidate, re.IGNORECASE) or re.fullmatch(r"chapter\b.*\bpage", candidate, re.IGNORECASE):
                continue
            match = EXPLICIT_CHAPTER_HEADING_PATTERN.fullmatch(candidate)
            if match:
                matches.append(match.group(0).strip())
            elif markdown_heading and re.fullmatch(r"(?:\d{1,4}|[IVXLCDM]{1,12})(?:\s*[.:\-—]\s*\S.{0,90})?", candidate, re.IGNORECASE):
                matches.append(candidate)
            elif allow_bare_numerals and re.fullmatch(r"(?:\d{1,4}|[IVXLCDM]{1,12})(?:\s*[.:\-—]\s*\S.{0,90})?", candidate):
                family = "arabic" if candidate[0].isdigit() else "roman"
                bare_numeral_starts[family].append((page_index, candidate))
                bare_numeral_on_page = True
        matches = list({re.sub(r"\W+", "", match).casefold(): match for match in matches}.values())
        if len(matches) == 1:
            explicit_starts.append((page_index, matches[0]))
        elif not matches and opening_lines and not bare_numeral_on_page:
            # Named chapters often omit the word "Chapter" entirely. At the
            # top of a page, a short all-caps line is a useful signal only when
            # the manuscript has not established an explicit numbered spine.
            # Otherwise viewpoint markers such as TIMMY or SHADOW become false
            # chapters whenever they happen to begin a PDF page.
            candidate = strip_markdown_heading(opening_lines[0])
            words = candidate.split()
            letters = [character for character in candidate if character.isalpha()]
            if 1 <= len(words) <= 10 and len(candidate) <= 100 and letters and candidate == candidate.upper():
                named_starts.append((page_index, candidate))
    if len(explicit_starts) < 2:
        roman = bare_numeral_starts["roman"]
        arabic = bare_numeral_starts["arabic"]
        if len(roman) >= 2:
            explicit_starts.extend(roman)
        if len(arabic) >= 2:
            numbers = [int(re.match(r"\d+", label).group(0)) for _, label in arabic]
            if min(numbers) <= 2 and numbers == sorted(numbers):
                explicit_starts.extend(arabic)
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
    report = {
        "pattern": "Numbered or named chapter headings" if explicit_starts else "Named opening headings",
        "topLevel": top_level,
        "otherCandidates": sorted(grouped.values(), key=lambda item: int(item["pages"][0])),
        "acceptedVariants": sorted(accepted_labels or [], key=str.casefold),
    }
    classify_heading_report(report, chapters)
    return report


def classify_heading_report(report: dict[str, object], chapters: list[dict[str, object]]) -> bool:
    """Explain harmless opening headings instead of presenting every singleton as structural ambiguity."""
    candidates = report.get("otherCandidates", []) if isinstance(report.get("otherCandidates"), list) else []
    authored = [chapter for chapter in chapters if strip_markdown_heading(chapter.get("title")).casefold() != "front matter"]
    first_authored_page = min((int(chapter.get("pageStart") or 0) for chapter in authored if int(chapter.get("pageStart") or 0) > 0), default=0)
    chapter_titles = {
        re.sub(r"\W+", "", str(chapter.get("chapterTitle") or "")).casefold(): chapter
        for chapter in authored if str(chapter.get("chapterTitle") or "").strip()
    }
    changed = False
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        label_key = re.sub(r"\W+", "", str(candidate.get("label") or "")).casefold()
        pages = [int(page) for page in candidate.get("pages", []) if str(page).isdigit()]
        classification = "unclassified"
        explanation = ""
        matched = chapter_titles.get(label_key)
        if pages and first_authored_page and max(pages) < first_authored_page:
            classification = "front-matter"
            explanation = "Appears before the authored chapter sequence and is retained as front matter."
        elif "projectgutenberg" in label_key and any(marker in label_key for marker in ("license", "ebook", "etext", "terms")):
            classification = "source-boilerplate"
            explanation = "Belongs to the Project Gutenberg distribution wrapper, not the authored chapter structure."
        elif matched:
            classification = "chapter-title-carryover"
            explanation = f"Matches the title of chapter {strip_markdown_heading(matched.get('title'))}; the source placed a copy at the preceding boundary."
        if candidate.get("classification") != classification or candidate.get("explanation") != explanation:
            candidate["classification"] = classification
            candidate["explanation"] = explanation
            changed = True
    return changed


def chapter_heading_report_warnings(report: dict[str, object]) -> list[str]:
    """Flag unique excluded openers while leaving repeated viewpoint labels alone."""
    candidates = report.get("otherCandidates", []) if isinstance(report, dict) else []
    unusual = [
        str(item.get("label") or "").strip()
        for item in candidates if isinstance(item, dict)
        and int(item.get("count") or 0) == 1
        and not item.get("accepted")
        and not item.get("demotedPages")
        and item.get("classification", "unclassified") == "unclassified"
        and str(item.get("label") or "").strip()
    ]
    return [f"Unique opening headings outside the established chapter pattern: {', '.join(unusual)}"] if unusual else []


def detect_chapters(
    page_texts: list[str], accepted_labels: list[str] | None = None,
    demoted_pages: list[int] | None = None,
    *, fixed_pagination: bool = True, allow_bare_numerals: bool = False,
) -> tuple[list[dict[str, object]], str]:
    explicit_starts, named_starts = opening_chapter_candidates(page_texts, allow_bare_numerals=allow_bare_numerals)
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
        if fixed_pagination:
            starts = [(index, f"Pages {index + 1}–{min(index + 15, len(page_texts))}") for index in range(0, len(page_texts), 15)]
            method = "page groups; no confident chapter headings were found"
        else:
            starts = [(0, "Entirety")]
            method = "entire reflowable work; no confident chapter headings were found"
    else:
        if starts[0][0] > 0:
            starts.insert(0, (0, "Front matter"))
        method = "explicit opening-line chapter headings" if has_explicit_spine else "opening-line chapter headings"
    chapters: list[dict[str, object]] = []
    for number, (start, title) in enumerate(starts, start=1):
        end = starts[number][0] - 1 if number < len(starts) else len(page_texts) - 1
        text = "\n\n".join(page_texts[start:end + 1]).strip()
        chapters.append({"number": number, "sequence": number, "title": title, "analysisRole": analysis_role_for_label(title), "pageStart": start + 1, "pageEnd": end + 1, "text": text, **chapter_structure(text, title)})
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

    def standalone_heading(lines: list[str]) -> bool:
        if len(lines) != 1:
            return False
        value = lines[0]
        letters = [character for character in value if character.isalpha()]
        return bool(letters) and value == value.upper() and 1 <= len(value.split()) <= 8 and len(value) <= 60 and not value.endswith((".", "!", "?", ":", ";"))

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
            # A page turn does not end an ordinary paragraph, but a
            # standalone all-caps block is authored structure rather than the
            # continuation of the prior page's sentence. Preserve it as its
            # own paragraph so viewpoint headings such as TIMMY and SHADOW do
            # not become "…last sentence. TIMMY" during reflow.
            if standalone_heading(lines):
                flush()
                paragraphs.append(lines[0])
                continue
            # Word-processors commonly encode a first-line indent in x0. A
            # leading blank line in a PDF block is another paragraph signal.
            begins_paragraph = float(block[0]) >= 96 or bool(re.match(r"^\s*\n", raw))
            if begins_paragraph:
                flush()
            # Some word processors put a standalone heading and the prose
            # after it in one positioned PDF block. Treat an all-caps visual
            # line as authored structure even when it shares that block;
            # otherwise the heading either vanishes into the prose or is
            # attached to the preceding paragraph during reflow.
            for line in lines:
                if standalone_heading([line]) and len([character for character in line if character.isalpha()]) >= 2:
                    flush()
                    paragraphs.append(line)
                else:
                    current.append(line)
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
        if (cleaned := strip_markdown_heading(value))
    }
    output = [f"# {label}"]
    if title:
        output.extend(["", f"## {title}"])
    skipped_label = skipped_title = False
    for raw_block in re.split(r"\n\s*\n+", str(chapter.get("text") or "").replace("\r\n", "\n")):
        lines = [line.strip() for line in raw_block.splitlines() if line.strip() and not re.fullmatch(r"\d{1,4}", line.strip())]
        while lines:
            first = lines[0]
            authored_heading = strip_markdown_heading(first)
            if not skipped_label and re.sub(r"\W+", "", authored_heading).casefold() == re.sub(r"\W+", "", label).casefold():
                skipped_label = True
                lines.pop(0)
                continue
            if title and not skipped_title and authored_heading == title:
                skipped_title = True
                lines.pop(0)
                continue
            if authored_heading in markers:
                output.extend(["", f"### {authored_heading}"])
                lines.pop(0)
                continue
            break
        paragraph = join_pdf_lines(lines)
        if paragraph:
            output.extend(["", paragraph])
    return "\n".join(output).strip() + "\n"


def analysis_role_for_label(label: str) -> str:
    if label.casefold() == "front matter":
        return "front-matter"
    if re.match(r"^(?:appendix\b|foreword\s+to\s+appendix$)", label, re.IGNORECASE):
        return "appendix"
    for role in ("prologue", "epilogue", "interlude"):
        if re.match(rf"^{role}\b", label, re.IGNORECASE):
            return role
    return "chapter"


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
        allowed = re.compile(r"^(?:FRONT MATTER|PROLOGUE|EPILOGUE|INTERLUDE|PART\b|APPENDIX\b|FOREWORD\s+TO\s+APPENDIX$)", re.IGNORECASE)
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


def finalize_rebuilt_chapter_map_approval(pipeline: dict[str, object], warnings: list[str]) -> bool:
    """Preserve an editor's prior approval across an intentional map correction."""
    restore_approval = bool(pipeline.pop("chapterMapApprovalAfterRebuild", False))
    approved = restore_approval and not warnings
    pipeline["chapterMapApproved"] = approved
    pipeline["chapterMapDecisionAt"] = utc_now()
    if approved:
        pipeline["chapterMapApprovedAt"] = utc_now()
    else:
        pipeline.pop("chapterMapApprovedAt", None)
    pipeline["analysisProvisional"] = bool(warnings or not approved)
    return approved


def begin_chapter_map_rebuild(pipeline: dict[str, object]) -> None:
    """Suspend, rather than revoke, a clean human map decision during rebuild."""
    pipeline["chapterMapApprovalAfterRebuild"] = bool(
        pipeline.get("chapterMapApprovalAfterRebuild") or pipeline.get("chapterMapApproved")
    )
    pipeline["chapterMapApproved"] = False
    pipeline["chapterMapDecisionAt"] = utc_now()
    pipeline.pop("chapterMapApprovedAt", None)


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


class LLMReviewAnalysisExhausted(RuntimeError):
    """Keep malformed LLM Review output inspectable after a bounded retry."""

    def __init__(self, step: str, failures: list[dict[str, object]], cause: Exception):
        self.step = step
        self.failures = failures
        self.cause = cause
        super().__init__(f"LLM Review returned malformed JSON twice during {step}. Retry this chapter; both raw responses were preserved.")


def normalized_model_field(payload: dict[str, object], *names: str) -> object:
    normalized = {re.sub(r"[^a-z0-9]", "", str(key).casefold()): value for key, value in payload.items()}
    return next((normalized[re.sub(r"[^a-z0-9]", "", name.casefold())] for name in names if re.sub(r"[^a-z0-9]", "", name.casefold()) in normalized), None)


def normalize_question_details(value: object) -> list[dict[str, object]]:
    """Keep useful question metadata while tolerating older string-only runs."""
    if not isinstance(value, list):
        return []
    details: list[dict[str, object]] = []
    for item in value:
        if isinstance(item, str):
            question = item.strip()
            if question:
                details.append({"question": question, "family": "reader_expectation", "evidence": "", "whyItMatters": "", "promisesAnswer": False})
            continue
        if not isinstance(item, dict):
            continue
        question = str(normalized_model_field(item, "question", "text") or "").strip()
        if not question:
            continue
        family = str(normalized_model_field(item, "family", "type") or "reader_expectation").strip().casefold().replace("-", "_").replace(" ", "_")
        if family not in QUESTION_FAMILIES:
            family = "reader_expectation"
        promised_value = normalized_model_field(item, "promises answer", "promises_answer", "manuscript obligation")
        details.append({
            "question": question,
            "family": family,
            "evidence": str(normalized_model_field(item, "evidence", "trigger", "source") or "").strip(),
            "whyItMatters": str(normalized_model_field(item, "why it matters", "why_it_matters", "importance") or "").strip(),
            "promisesAnswer": promised_value is True or str(promised_value).strip().casefold() in {"true", "yes", "1"},
        })
    return details


EXPLICIT_NEGATION_RE = re.compile(r"\b(?:no|not|never|neither|none|nothing|nobody|without)\b", re.I)
EVIDENCE_NEGATION_RE = re.compile(r"\b(?:no|not|never|neither|none|nothing|nobody|without|absent|empty|gone|missing|failed|refused|unable)\b", re.I)


def claim_polarity_is_supported(claim: object, evidence: object) -> bool:
    """Reject the easiest and most damaging unsupported polarity reversals.

    This is intentionally narrow. It does not pretend to perform textual
    entailment; it catches claims such as "without forced entry" when the
    cited source contains no negation or absence at all.
    """
    claim_text = re.sub(r"\s+", " ", str(claim or "")).strip()
    evidence_text = re.sub(r"\s+", " ", str(evidence or "")).strip()
    return not EXPLICIT_NEGATION_RE.search(claim_text) or bool(EVIDENCE_NEGATION_RE.search(evidence_text))


def claim_relation_is_supported(claim: object, evidence: object) -> bool:
    """Reject a few high-cost relation upgrades absent from the cited words.

    This deliberately covers only relations whose language is recognizable.
    General entailment still belongs to the reader model and ultimately the
    human reviewer.
    """
    claim_text = re.sub(r"\s+", " ", str(claim or "")).strip()
    evidence_text = re.sub(r"\s+", " ", str(evidence or "")).strip()
    guarded_relations = (
        (r"\b(?:cause[sd]?|causing|source of|responsible for|results? in|leads? to)\b", r"\b(?:cause[sd]?|causing|source|responsible|because|due to|results? in|leads? to|comes? from|origin)\b"),
        (r"\b(?:diagnos(?:e[sd]?|is|tic)|medically confirms?)\b", r"\b(?:diagnos(?:e[sd]?|is|tic)|disease|illness|condition|symptom)\b"),
        (r"\b(?:prove[sd]?|validate[sd]?|confirm[sd]?)\b", r"\b(?:prove[sd]?|validate[sd]?|confirm[sd]?|demonstrate[sd]?|show[sd]?)\b"),
        (r"\b(?:an? (?:external )?threat|enemy|hostile force)\b", r"\b(?:threat|danger|enemy|hostile|attack(?:ed|ing|s)?|harm(?:ed|ing|s)?|menace)\b"),
    )
    return all(not re.search(claim_pattern, claim_text, re.I) or bool(re.search(evidence_pattern, evidence_text, re.I)) for claim_pattern, evidence_pattern in guarded_relations)


def normalized_evidence_claims(value: object, source_text: str) -> list[dict[str, object]]:
    """Normalize model claim forms while retaining only source-anchored facts."""
    if not isinstance(value, list):
        return []
    claims: list[dict[str, object]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        claim = str(normalized_model_field(item, "claim", "fact", "state", "text") or "").strip()
        subject = str(normalized_model_field(item, "subject", "actor", "entity") or "").strip()
        anchor = resolve_source_evidence(source_text, normalized_model_field(item, "evidence ref", "evidence_ref", "evidence")) if source_text else None
        if not claim or not anchor or not claim_polarity_is_supported(claim, anchor.get("quote")) or not claim_relation_is_supported(claim, anchor.get("quote")):
            continue
        claims.append({
            "claim": claim,
            "subject": subject,
            "evidence": anchor["quote"],
            "evidenceAnchor": anchor,
        })
    return claims


SUMMARY_COVERAGE_STOPWORDS = {
    "about", "after", "again", "against", "also", "among", "another", "because", "before", "being", "chapter", "could",
    "does", "during", "each", "from", "have", "into", "itself", "later", "more", "narrator", "other", "over", "scene",
    "should", "state", "still", "that", "their", "there", "these", "they", "this", "those", "through", "under", "very",
    "what", "when", "where", "which", "while", "with", "would",
}


def chapter_summary_ending_coverage(summary: object, normalized: dict[str, object], source_text: str) -> dict[str, object]:
    """Check that a digest reaches at least one anchored final-quarter event.

    The check is intentionally lexical and conservative. It does not judge
    prose quality; it only catches summaries that stop after an early scene
    despite the model having already identified exact late-chapter facts.
    """
    if len(source_text) < 500:
        return {"covered": True, "reason": "short-source"}
    candidates: list[dict[str, object]] = []
    for field, text_field in (("keyPointDetails", "claim"), ("endingState", "fact")):
        for item in normalized.get(field, []) if isinstance(normalized.get(field), list) else []:
            if not isinstance(item, dict) or not isinstance(item.get("evidenceAnchor"), dict):
                continue
            start = int(item["evidenceAnchor"].get("characterStart") or 0)
            if start >= int(len(source_text) * 0.75):
                candidates.append({"text": str(item.get(text_field) or ""), "characterStart": start})
    if not candidates:
        return {"covered": True, "reason": "no-anchored-final-quarter-fact"}

    summary_terms = {
        token for token in re.findall(r"[A-Za-z][A-Za-z'-]{3,}", str(summary or "").casefold())
        if token not in SUMMARY_COVERAGE_STOPWORDS
    }
    latest = sorted(candidates, key=lambda item: int(item["characterStart"]), reverse=True)[:3]
    for item in latest:
        fact_terms = {
            token for token in re.findall(r"[A-Za-z][A-Za-z'-]{3,}", str(item["text"]).casefold())
            if token not in SUMMARY_COVERAGE_STOPWORDS
        }
        overlap = sorted(summary_terms & fact_terms)
        if len(overlap) >= 2:
            return {"covered": True, "reason": "late-fact-overlap", "matchingTerms": overlap[:8]}
    return {
        "covered": False,
        "reason": "summary-does-not-reach-final-quarter",
        "lateFacts": [str(item["text"]) for item in latest],
    }


def normalize_chapter_summary(payload: dict[str, object], source_text: str = "") -> dict[str, object]:
    summary = str(normalized_model_field(payload, "summary", "chapter summary", "chapter_summary", "digest", "synopsis") or "").strip()
    if not summary:
        raise ChapterSummaryError("The model returned JSON without a chapter summary. This chapter remains retryable.", json.dumps(payload, ensure_ascii=False), [str(key) for key in payload])
    key_points = normalized_model_field(payload, "key points", "key_points", "keyPoints", "established facts")
    new_questions = normalized_model_field(payload, "new questions", "new_questions", "newQuestions", "open questions")
    raw_question_details = normalized_model_field(payload, "question details", "question_details", "questionDetails")
    raw_ending_state = normalized_model_field(payload, "ending state", "ending_state", "endingState")
    question_details = normalize_question_details(raw_question_details)
    if source_text and question_details:
        raw_by_question = {
            str(normalized_model_field(item, "question", "text") or "").strip(): item
            for item in raw_question_details if isinstance(item, dict)
        } if isinstance(raw_question_details, list) else {}
        for detail in question_details:
            raw = raw_by_question.get(str(detail["question"]), {})
            anchor = resolve_source_evidence(source_text, raw.get("evidence_ref") or raw.get("evidence"))
            if anchor:
                detail["evidence"] = anchor["quote"]
                detail["evidenceAnchor"] = anchor
            else:
                # Never present model-authored near-quotes as source evidence.
                # The question remains useful, but navigation is withheld until
                # a canonical anchor exists.
                detail["evidence"] = ""
    questions = [str(item).strip() for item in new_questions if str(item).strip()] if isinstance(new_questions, list) else []
    if question_details:
        questions = [str(item["question"]) for item in question_details]
    key_point_details = normalized_evidence_claims(key_points, source_text) if source_text else []
    legacy_key_points = [str(item).strip() for item in key_points if isinstance(item, str) and str(item).strip()] if isinstance(key_points, list) else []
    normalized = {
        "summary": summary,
        "keyPoints": [str(item["claim"]) for item in key_point_details] or legacy_key_points,
        "newQuestions": questions,
    }
    if key_point_details:
        normalized["keyPointDetails"] = key_point_details
    ending_state: list[dict[str, object]] = []
    for item in raw_ending_state if isinstance(raw_ending_state, list) else []:
        if not isinstance(item, dict):
            continue
        fact = str(normalized_model_field(item, "fact", "state") or "").strip()
        anchor = resolve_source_evidence(source_text, normalized_model_field(item, "evidence ref", "evidence_ref", "evidence")) if source_text else None
        if fact and anchor and claim_polarity_is_supported(fact, anchor.get("quote")):
            ending_state.append({"fact": fact, "evidence": anchor["quote"], "evidenceAnchor": anchor})
    if ending_state:
        normalized["endingState"] = ending_state
    if question_details:
        normalized.update({"questionDetails": question_details, "promptVersion": SUMMARY_PROMPT_VERSION})
    return normalized


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


def model_response_telemetry(book_id: str) -> dict[str, object]:
    """Return the newest safe progress snapshot for a book's local model call."""
    with ACTIVE_MODEL_RESPONSES_LOCK:
        candidates = [
            dict(value)
            for key, value in MODEL_RESPONSE_TELEMETRY.items()
            if key == book_id or key.startswith(f"{book_id}:")
        ]
    if not candidates:
        return {"active": False}
    latest = max(candidates, key=lambda item: str(item.get("lastActivityAt") or item.get("startedAt") or ""))
    latest["active"] = latest.get("status") in {"connecting", "generating"}
    return latest


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


def run_structured_model(
    prompt: str, model: str, schema: dict[str, object], cancel_event: threading.Event | None = None,
    run_key: str = "", *, activity: str = "",
) -> tuple[dict[str, object], str]:
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
        return _run_structured_model(prompt, model, schema, cancel_event, run_key, activity=activity)


def _run_structured_model(
    prompt: str, model: str, schema: dict[str, object], cancel_event: threading.Event | None = None,
    run_key: str = "", *, activity: str = "",
) -> tuple[dict[str, object], str]:
    options = {"temperature": 0.1}
    telemetry_key = run_key or f"anonymous:{uuid.uuid4().hex}"
    telemetry = {
        "runKey": telemetry_key,
        "model": model,
        "status": "connecting",
        "startedAt": utc_now(),
        "lastActivityAt": utc_now(),
        "inputCharacters": len(prompt),
        "outputCharacters": 0,
        "responseText": "",
        "responseFragments": 0,
        "activity": activity,
    }
    with ACTIVE_MODEL_RESPONSES_LOCK:
        previous = MODEL_RESPONSE_TELEMETRY.get(telemetry_key)
        if isinstance(previous, dict) and previous.get("status") == "complete":
            telemetry["previousCall"] = {
                key: previous.get(key)
                for key in (
                    "activity", "model", "status", "startedAt", "completedAt",
                    "inputCharacters", "outputCharacters", "responseFragments",
                    "promptTokens", "generatedTokens", "totalDurationNanoseconds",
                )
                if previous.get(key) is not None
            }
        telemetry_owner = telemetry_key.split(":", 1)[0]
        for stale_key in [key for key in MODEL_RESPONSE_TELEMETRY if key.split(":", 1)[0] == telemetry_owner and key != telemetry_key]:
            MODEL_RESPONSE_TELEMETRY.pop(stale_key, None)
        MODEL_RESPONSE_TELEMETRY[telemetry_key] = telemetry
    request = urllib.request.Request(
        "http://127.0.0.1:11434/api/chat",
        data=json.dumps({"model": model, "stream": True, "think": False, "format": schema, "keep_alive": "10m", "options": options, "messages": [{"role": "user", "content": prompt}]}).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST",
    )
    parts: list[str] = []
    stream_error: OSError | ValueError | AttributeError | None = None
    try:
        response = urllib.request.urlopen(request, timeout=900)
    except (OSError, ValueError):
        with ACTIVE_MODEL_RESPONSES_LOCK:
            telemetry.update({"status": "failed", "completedAt": utc_now(), "lastActivityAt": utc_now()})
        raise
    with ACTIVE_MODEL_RESPONSES_LOCK:
        if run_key:
            ACTIVE_MODEL_RESPONSES[run_key] = response
        telemetry["status"] = "generating"
        telemetry["connectedAt"] = utc_now()
        telemetry["lastActivityAt"] = telemetry["connectedAt"]
    try:
        with response:
            for line in response:
                if cancel_event and cancel_event.is_set():
                    raise PipelineCancelled()
                if not line.strip():
                    continue
                payload = json.loads(line)
                content = str(payload.get("message", {}).get("content") or "")
                parts.append(content)
                with ACTIVE_MODEL_RESPONSES_LOCK:
                    telemetry["lastActivityAt"] = utc_now()
                    if content:
                        telemetry["outputCharacters"] = int(telemetry.get("outputCharacters") or 0) + len(content)
                        telemetry["responseText"] = str(telemetry.get("responseText") or "") + content
                        telemetry["responseFragments"] = int(telemetry.get("responseFragments") or 0) + 1
                    for source, target in (
                        ("prompt_eval_count", "promptTokens"),
                        ("eval_count", "generatedTokens"),
                        ("load_duration", "loadDurationNanoseconds"),
                        ("prompt_eval_duration", "promptDurationNanoseconds"),
                        ("eval_duration", "generationDurationNanoseconds"),
                        ("total_duration", "totalDurationNanoseconds"),
                    ):
                        if payload.get(source) is not None:
                            telemetry[target] = payload[source]
                    if payload.get("done_reason"):
                        telemetry["doneReason"] = payload["done_reason"]
                if payload.get("done"):
                    break
    except PipelineCancelled:
        with ACTIVE_MODEL_RESPONSES_LOCK:
            telemetry.update({"status": "cancelled", "completedAt": utc_now(), "lastActivityAt": utc_now()})
        raise
    except (OSError, ValueError, AttributeError) as error:
        if cancel_event and cancel_event.is_set():
            with ACTIVE_MODEL_RESPONSES_LOCK:
                telemetry.update({"status": "cancelled", "completedAt": utc_now(), "lastActivityAt": utc_now()})
            raise PipelineCancelled() from error
        stream_error = error
        with ACTIVE_MODEL_RESPONSES_LOCK:
            telemetry.update({"status": "failed", "completedAt": utc_now(), "lastActivityAt": utc_now()})
    finally:
        if run_key:
            with ACTIVE_MODEL_RESPONSES_LOCK:
                if ACTIVE_MODEL_RESPONSES.get(run_key) is response:
                    ACTIVE_MODEL_RESPONSES.pop(run_key, None)
                if telemetry.get("status") == "generating":
                    telemetry.update({"status": "complete", "completedAt": utc_now(), "lastActivityAt": utc_now()})
    if cancel_event and cancel_event.is_set():
        raise PipelineCancelled()
    raw_response = "".join(parts)
    if stream_error is not None:
        # Closing a streaming HTTPResponse from another thread can race with
        # BufferedReader.peek(). If Ollama's complete JSON object is already in
        # hand, preserve the expensive result instead of turning a cleanup
        # hiccup into a failed chapter. Incomplete content still raises the
        # original transport exception and remains visibly retryable.
        try:
            recovered = json.loads(raw_response)
        except (json.JSONDecodeError, TypeError):
            raise stream_error
        if not isinstance(recovered, dict):
            raise stream_error
        with ACTIVE_MODEL_RESPONSES_LOCK:
            telemetry.update({
                "status": "complete", "completedAt": utc_now(), "lastActivityAt": utc_now(),
                "transportRecovered": type(stream_error).__name__,
                "transportRecoveryMessage": str(stream_error)[:200],
            })
        return recovered, raw_response
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


def manuscript_location_prompt(item: dict[str, object]) -> str:
    if item.get("sourcePagination") == "reflowable":
        return "Source pagination: reflowable; no stable page numbers"
    return f"Original PDF pages: {item.get('pageStart')}-{item.get('pageEnd')}"


def source_evidence_ref_schema() -> dict[str, object]:
    return {
        "type": "object",
        "properties": {
            "passage_id": {"type": "string", "minLength": 1},
            "quote": {"type": "string", "minLength": 1},
            "character_start": {"type": "integer", "minimum": 0},
            "character_end": {"type": "integer", "minimum": 1},
        },
        "required": ["passage_id", "quote", "character_start", "character_end"],
    }


def chapter_summary_schema() -> dict[str, object]:
    evidence_ref = source_evidence_ref_schema()
    evidence_claim = {
        "type": "object",
        "properties": {
            "claim": {"type": "string", "minLength": 1},
            "subject": {"type": "string", "minLength": 1},
            "evidence_ref": evidence_ref,
        },
        "required": ["claim", "subject", "evidence_ref"],
    }
    ending_state = {
        "type": "object",
        "properties": {"fact": {"type": "string", "minLength": 1}, "evidence_ref": evidence_ref},
        "required": ["fact", "evidence_ref"],
    }
    question_detail = {
        "type": "object",
        "properties": {
            "question": {"type": "string", "minLength": 1},
            "family": {"type": "string", "enum": list(QUESTION_FAMILIES)},
            "evidence": {"type": "string"},
            "evidence_ref": evidence_ref,
            "why_it_matters": {"type": "string"},
            "promises_answer": {"type": "boolean"},
        },
        "required": ["question", "family", "evidence", "evidence_ref", "why_it_matters", "promises_answer"],
    }
    return {
        "type": "object",
        "properties": {
            "summary": {"type": "string", "minLength": 1},
            "key_points": {"type": "array", "items": evidence_claim},
            "ending_state": {"type": "array", "items": ending_state},
            "new_questions": {"type": "array", "items": {"type": "string"}},
            "question_details": {"type": "array", "items": question_detail},
        },
        "required": ["summary", "key_points", "ending_state", "new_questions", "question_details"],
    }


def chapter_dossier_schema() -> dict[str, object]:
    evidence_ref = source_evidence_ref_schema()
    evidence_claim = {
        "type": "object",
        "properties": {
            "claim": {"type": "string", "minLength": 1},
            "subject": {"type": "string", "minLength": 1},
            "evidence_ref": evidence_ref,
        },
        "required": ["claim", "subject", "evidence_ref"],
    }
    promise_claim = {
        "type": "object",
        "properties": {**evidence_claim["properties"], "promise_type": {"type": "string", "enum": ["character", "story"]}},
        "required": ["claim", "subject", "promise_type", "evidence_ref"],
    }
    question_detail = {
        "type": "object",
        "properties": {
            "question": {"type": "string", "minLength": 1},
            "family": {"type": "string", "enum": list(QUESTION_FAMILIES)},
            "evidence": {"type": "string"},
            "evidence_ref": evidence_ref,
            "why_it_matters": {"type": "string"},
            "promises_answer": {"type": "boolean"},
        },
        "required": ["question", "family", "evidence", "evidence_ref", "why_it_matters", "promises_answer"],
    }
    claims = {"type": "array", "items": evidence_claim}
    return {
        "type": "object",
        "properties": {
            "synopsis": {"type": "string", "minLength": 1},
            "facts": claims, "events": claims, "entities": claims, "locations": claims,
            "current_times": claims,
            "questions": {"type": "array", "items": {"type": "string"}},
            "question_details": {"type": "array", "items": question_detail},
            "promises": {"type": "array", "items": promise_claim},
            "timeline_observations": claims,
            "evidence": {"type": "array", "items": evidence_ref},
        },
        "required": ["synopsis", "facts", "events", "entities", "locations", "current_times", "questions", "question_details", "promises", "timeline_observations", "evidence"],
    }


def summarize_chapter(chapter: dict[str, object], model: str, cancel_event: threading.Event | None = None, run_key: str = "") -> dict[str, object]:
    text = str(chapter.get("text") or "")[:60_000]
    material_guidance = front_matter_analysis_guidance("summary") if is_front_matter(chapter) else "This is narrative manuscript material."
    prompt = f"""Read this manuscript chapter and create a compact editorial digest.
Return JSON only with: summary (string, 2-4 paragraphs), key_points (array of evidence-linked claim objects), ending_state (array of objects), new_questions (array of strings), and question_details (array of objects).
Report what the text establishes; do not invent resolutions or facts. This is a chapter summary, not a critique.

Every factual assertion in summary must also appear, in equivalent wording, as a key_points claim with an exact evidence_ref. Treat this as a verification ledger, not an invitation to produce more claims. A key_points object contains claim, subject, and evidence_ref. Copy the grammatical subject carefully. If the source says "my father," that is the narrator's father—not the nearest named character's father. Check negative assertions especially: never write "no," "not," "never," or "without" unless the cited source establishes that polarity. Do not promise to follow these rules in the output; actually verify the claims and return only the requested data.

Before drafting the summary, inspect the final source passages closely. The summary must cover the chapter's full narrative movement, including its final material turn, encounter, decision, discovery, or changed state; do not write a polished summary of only the opening scene. ending_state is the literal state of important people, objects, places, and unresolved actions at the chapter boundary. Each object contains fact and evidence_ref. Anchor every fact to an exact source quotation. Preserve grammatical actors and objects: a locked door or room does not mean a person was found locked inside it; a forced entry followed by an empty room means the person is absent, not found. Distinguish observation, diagnosis, inference, and established cause. If a doctor observes a mark, do not call the mark the cause of symptoms or a diagnosis unless the source explicitly makes that relation. If summary prose conflicts with anchored ending_state, ending_state must be correct.

Questions must be specific editorial leads earned by this chapter. Ask what remains uncertain about a particular choice, avoided action, competing motive, causal bridge, concealed knowledge, relationship change, thematic pressure, reader expectation, setup, or factual continuity. Name the exact action, revelation, contradiction, image, line of dialogue, or change that creates the question. Reject generic discussion prompts that could fit almost any chapter, and reject questions the chapter already answers. Prefer questions a later passage could answer, complicate, transform, or deliberately leave open. Do not force a question when the chapter creates no meaningful unresolved pressure.

Each question_details object must contain:
- question: the concrete question, exactly matching an entry in new_questions
- family: exactly one of motivation, causality, character_knowledge, relationship_change, thematic_consequence, reader_expectation, setup_payoff, factual_continuity
- evidence: a short exact quotation from this chapter
- evidence_ref: the supplied passage ID, printed character start and end, and the same exact copied quotation
- why_it_matters: the consequence for character, causality, relationship, theme, continuity, or reader expectation
- promises_answer: true only when the manuscript appears to create an obligation to answer this later

Material-specific instructions:
{material_guidance}

Chapter: {chapter.get('title')}
Chapter title: {chapter.get('chapterTitle') or 'Not stated'}
Viewpoint or section markers: {json.dumps(chapter.get('sectionMarkers') or [], ensure_ascii=False)}
{manuscript_location_prompt(chapter)}

Canonical source passages:
{evidence_passage_prompt(text)}
"""
    schema = chapter_summary_schema()
    try:
        result, raw_response = run_structured_model(prompt, model, schema, cancel_event, run_key)
    except json.JSONDecodeError as error:
        raise ChapterSummaryError(f"The model returned malformed JSON: {error.msg}. This chapter remains retryable.") from error
    try:
        normalized = normalize_chapter_summary(result, text)
        normalized.setdefault("questionDetails", [])
        normalized.setdefault("endingState", [])
        normalized["promptVersion"] = SUMMARY_PROMPT_VERSION
        if is_front_matter(chapter):
            # Never promote questions inferred from a table of contents into
            # the story's obligation ledger, even if the model overreaches.
            normalized["newQuestions"] = []
            normalized["questionDetails"] = []
            normalized["endingState"] = []
            normalized["analysisMode"] = "front-matter-structural"
        else:
            coverage = chapter_summary_ending_coverage(normalized.get("summary"), normalized, text)
            normalized["endingCoverage"] = coverage
            if not coverage.get("covered"):
                raise ChapterSummaryError(
                    "The model summarized an early scene but omitted the chapter's anchored final movement. This chapter remains retryable.",
                    raw_response,
                    [str(item) for item in coverage.get("lateFacts", [])],
                )
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
        except ChapterSummaryError as error:
            failure = {
                "attempt": attempt,
                "model": model,
                "completedAt": utc_now(),
                "error": str(error),
                "exceptionType": type(error).__name__,
                "inputCharacters": len(str(chapter.get("text") or "")),
            }
            failures.append(failure)
            if attempt > len(retry_delays):
                raise
            if on_retry:
                on_retry(attempt, failure)
            delay = retry_delays[attempt - 1]
            if cancel_event and cancel_event.wait(delay):
                raise PipelineCancelled() from None
            if not cancel_event:
                time.sleep(delay)
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
            "questionDetails": chapter.get("questionDetails") or [],
            "promptVersion": chapter.get("promptVersion") or "chapter-summary-v1",
        }
        for chapter in pipeline.get("chapters", [])
        if chapter.get("status") == "complete" and strip_markdown_heading(chapter.get("title")).casefold() != "front matter"
    ]
    dossier_questions = [
        {
            "chapter": int(chunk.get("chapterSequence") or 0),
            "chunk": int(chunk.get("chunkInChapter") or 0),
            "questions": (chunk.get("dossier") or {}).get("questions") or [],
            "questionDetails": (chunk.get("dossier") or {}).get("questionDetails") or [],
            "promises": (chunk.get("dossier") or {}).get("promises") or [],
            "promptVersion": (chunk.get("dossier") or {}).get("promptVersion") or "chapter-dossier-v1",
        }
        for chunk in pipeline.get("chunks", [])
        if chunk.get("dossierStatus") == "complete" and isinstance(chunk.get("dossier"), dict)
    ]
    source = json.dumps({"chapters": chapters, "dossierQuestions": dossier_questions}, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def legacy_question_tracker_input_signature(pipeline: dict[str, object]) -> str:
    """Fingerprint the inputs used before richer question metadata was added."""
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


def question_tracker_is_current(
    pipeline: dict[str, object], tracker: dict[str, object], current_signature: str = "",
) -> bool:
    """Keep completed legacy trackers current until their inputs gain richer question data."""
    signature = current_signature or question_tracker_input_signature(pipeline)
    if not signature:
        return False
    if tracker.get("inputSignature") == signature:
        return True
    has_richer_inputs = any(
        "questionDetails" in chapter or "promptVersion" in chapter
        for chapter in pipeline.get("chapters", [])
        if isinstance(chapter, dict)
    ) or any(
        "questionDetails" in dossier or "promptVersion" in dossier
        for chunk in pipeline.get("chunks", [])
        if isinstance(chunk, dict) and isinstance((dossier := chunk.get("dossier")), dict)
    )
    legacy_signature = legacy_question_tracker_input_signature(pipeline)
    if (
        tracker.get("status") == "complete"
        and not has_richer_inputs
        and legacy_signature
        and tracker.get("inputSignature") == legacy_signature
    ):
        # This is a schema-only signature migration. The analyzed evidence did
        # not change, so do not spend another long model run recreating it.
        tracker["inputSignature"] = signature
        return True
    return False


def reconcile_questions_and_payoffs(pipeline: dict[str, object], model: str, cancel_event: threading.Event | None = None, run_key: str = "") -> dict[str, object]:
    """Group repeated narrative questions and identify only supported payoffs."""
    chapters = [
        {
            "sequence": int(chapter.get("sequence") or chapter.get("number") or 0),
            "title": strip_markdown_heading(chapter.get("title")),
            "summary": chapter.get("summary"),
            "establishes": chapter.get("keyPoints") or [],
            "questions": chapter.get("newQuestions") or [],
            "questionDetails": chapter.get("questionDetails") or [],
        }
        for chapter in pipeline.get("chapters", [])
        if chapter.get("status") == "complete" and strip_markdown_heading(chapter.get("title")).casefold() != "front matter"
    ]
    dossier_questions = [
        {
            "chapter": int(chunk.get("chapterSequence") or 0),
            "chunk": int(chunk.get("chunkInChapter") or 0),
            "questions": (chunk.get("dossier") or {}).get("questions") or [],
            "questionDetails": (chunk.get("dossier") or {}).get("questionDetails") or [],
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


def normalize_lexical_key(value: object) -> str:
    """Give model-authored labels one stable, punctuation-insensitive identity."""
    normalized = unicodedata.normalize("NFKD", str(value or "")).casefold()
    normalized = "".join(character for character in normalized if not unicodedata.combining(character))
    normalized = re.sub(r"[_\-\u2013\u2014/]+", " ", normalized)
    normalized = re.sub(r"[^a-z0-9 ]+", " ", normalized)
    return re.sub(r"\s+", " ", normalized).strip()


def sentence_case_label(value: object, fallback: str = "Unclassified") -> str:
    key = normalize_lexical_key(value)
    return f"{key[:1].upper()}{key[1:]}" if key else fallback


SMELL_LABEL_ALIASES = {
    **{key: "Complex sentence" for key in (
        "clause count", "clause load", "clause load proxy", "clause complexity",
        "clause overload", "dependent clauses", "complexity", "complex structure",
        "complex sentence", "complex sentence structure", "nested structure",
        "heavy clause load", "many clauses",
    )},
    **{key: "Overloaded sentence" for key in (
        "finite verb load", "overloaded sentence", "possible overloaded sentence", "run on",
    )},
    **{key: "Long sentence" for key in (
        "length", "sentence length", "long sentence", "very long sentence",
    )},
    "oxford comma": "Oxford comma",
    "missing oxford comma": "Oxford comma",
    "weasel words": "Weasel words",
    "cliches": "Cliché",
    "cliche": "Cliché",
    "redundancy": "Redundancy",
    "typography punctuation": "Punctuation",
    "lexical illusion": "Repeated phrase",
    "repeated word": "Repeated word",
}


def canonical_smell_label(value: object) -> str:
    key = normalize_lexical_key(value)
    if "oxford comma" in key:
        return "Oxford comma"
    for prefix, label in (
        ("weasel words", "Weasel words"), ("cliches", "Cliché"),
        ("redundancy", "Redundancy"), ("typography punctuation", "Punctuation"),
        ("lexical illusion", "Repeated phrase"), ("repeated word", "Repeated word"),
    ):
        if key.startswith(prefix):
            return label
    return SMELL_LABEL_ALIASES.get(key) or sentence_case_label(key, "Possible prose smell")


def source_evidence_passages(text: str) -> list[dict[str, object]]:
    """Make compact, exact source choices the model can cite without recopying prose."""
    passages: list[dict[str, object]] = []
    for paragraph_match in re.finditer(r"\S(?:.*?\S)?(?=\n\s*\n|\s*\Z)", text, re.S):
        paragraph = paragraph_match.group()
        base = paragraph_match.start()
        boundaries = [0]
        boundaries.extend(match.end() for match in re.finditer(r"[.!?][”\"']*\s+(?=[A-Z“\"'])", paragraph))
        boundaries.append(len(paragraph))
        for left, right in zip(boundaries, boundaries[1:]):
            while left < right and paragraph[left].isspace():
                left += 1
            while right > left and paragraph[right - 1].isspace():
                right -= 1
            if right <= left:
                continue
            start, end = base + left, base + right
            passages.append({"id": f"P{len(passages) + 1:04d}", "characterStart": start, "characterEnd": end, "text": text[start:end]})
    return passages


CHAPTER_ACTION_CUE = re.compile(
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


def chapter_action_passages(text: str, limit: int = 16) -> list[dict[str, object]]:
    """Select exact action-bearing passages as recall hints, never as facts."""
    candidates: list[dict[str, object]] = []
    for passage in source_evidence_passages(text):
        cues = [match.group(0) for match in CHAPTER_ACTION_CUE.finditer(str(passage.get("text") or ""))]
        if not cues:
            continue
        candidates.append({
            "passage_id": passage["id"],
            "exact_source": passage["text"],
            "character_start": passage["characterStart"],
            "character_end": passage["characterEnd"],
            "cue_words": cues,
            "selection_score": len(cues),
        })
    selected = sorted(
        sorted(candidates, key=lambda item: (-int(item["selection_score"]), int(item["character_start"])))[:limit],
        key=lambda item: int(item["character_start"]),
    )
    return selected


GLINER_IDENTITY_LABELS = {"person", "named animal", "group", "creature", "supernatural force"}


def gliner_identity_candidates(artifact: dict[str, object], text: str) -> list[dict[str, object]]:
    """Compact raw GLiNER spans into fallible identity hints for Qwen."""
    raw = artifact.get("raw") if isinstance(artifact.get("raw"), dict) else {}
    mentions = raw.get("mentions") if isinstance(raw.get("mentions"), dict) else {}
    entities = mentions.get("entities") if isinstance(mentions.get("entities"), dict) else {}
    passages = source_evidence_passages(text)
    grouped: dict[tuple[str, str], dict[str, object]] = {}
    for label, values in entities.items():
        if str(label) not in GLINER_IDENTITY_LABELS or not isinstance(values, list):
            continue
        for value in values:
            if not isinstance(value, dict):
                continue
            mention = str(value.get("text") or "").strip()
            confidence = float(value.get("confidence") or 0)
            start, end = int(value.get("start") or 0), int(value.get("end") or 0)
            if confidence < 0.55 or not mention or re.fullmatch(r"(?:he|she|him|her|they|them|it|we|us|i|me)", mention, re.I):
                continue
            passage = next((item for item in passages if int(item["characterStart"]) <= start and int(item["characterEnd"]) >= end), None)
            if not passage:
                continue
            key = (str(label), re.sub(r"^(?:my|the|a|an)\s+", "", mention.casefold()).strip())
            candidate = grouped.setdefault(key, {
                "proposed_type": str(label), "exact_mention": mention,
                "max_confidence": 0.0, "mentions": [],
            })
            candidate["max_confidence"] = max(float(candidate["max_confidence"]), confidence)
            candidate["mentions"].append({
                "confidence": round(confidence, 4), "character_start": start, "character_end": end,
                "evidence_ref": {
                    "passage_id": passage["id"], "quote": passage["text"],
                    "character_start": passage["characterStart"], "character_end": passage["characterEnd"],
                },
            })
    return [
        {"candidate_id": f"G{index:03d}", **candidate, "max_confidence": round(float(candidate["max_confidence"]), 4)}
        for index, candidate in enumerate(grouped.values(), 1)
    ]


def evidence_passage_prompt(text: str) -> str:
    return "\n".join(
        f"[{item['id']} {item['characterStart']}:{item['characterEnd']}] {item['text']}"
        for item in source_evidence_passages(text)
    )


def _anchor_tokens(value: object) -> list[str]:
    return re.findall(r"[a-z0-9]+", unicodedata.normalize("NFKC", str(value or "")).casefold())


def resolve_source_evidence(text: str, evidence: object) -> dict[str, object] | None:
    """Triangulate model text, offsets, and passage ID; never guess an ambiguous anchor."""
    if isinstance(evidence, str):
        supplied = {"quote": evidence}
    elif isinstance(evidence, dict):
        supplied = evidence
    else:
        return None
    quote = str(supplied.get("quote") or "").strip()
    requested_start = int(supplied.get("character_start", supplied.get("characterStart", -1)) or -1)
    requested_end = int(supplied.get("character_end", supplied.get("characterEnd", -1)) or -1)
    passage_id = str(supplied.get("passage_id", supplied.get("passageId", "")) or "").strip()
    passages = source_evidence_passages(text)

    exact_positions = [match.start() for match in re.finditer(re.escape(quote), text)] if quote else []
    if exact_positions:
        passage = next((item for item in passages if item["id"] == passage_id), None)
        if requested_start >= 0:
            start = min(exact_positions, key=lambda value: abs(value - requested_start))
        elif passage:
            within = [value for value in exact_positions if int(passage["characterStart"]) <= value < int(passage["characterEnd"])]
            if len(within) != 1:
                return None
            start = within[0]
        elif len(exact_positions) == 1:
            start = exact_positions[0]
        else:
            return None
        return {
            "quote": text[start:start + len(quote)], "characterStart": start, "characterEnd": start + len(quote),
            "passageId": next((str(item["id"]) for item in passages if int(item["characterStart"]) <= start < int(item["characterEnd"])), passage_id),
            "matchMethod": "exact", "matchScore": 1.0,
        }

    quote_tokens = _anchor_tokens(quote)
    if quote_tokens:
        source_matches = list(re.finditer(r"[A-Za-z0-9]+", text))
        source_tokens = [match.group().casefold() for match in source_matches]
        width = len(quote_tokens)
        token_positions = [index for index in range(0, len(source_tokens) - width + 1) if source_tokens[index:index + width] == quote_tokens]
        if token_positions:
            passage = next((item for item in passages if item["id"] == passage_id), None)
            if requested_start >= 0:
                index = min(token_positions, key=lambda value: abs(source_matches[value].start() - requested_start))
            elif passage:
                within = [value for value in token_positions if int(passage["characterStart"]) <= source_matches[value].start() < int(passage["characterEnd"])]
                if len(within) != 1:
                    return None
                index = within[0]
            elif len(token_positions) == 1:
                index = token_positions[0]
            else:
                return None
            start, end = source_matches[index].start(), source_matches[index + width - 1].end()
            return {
                "quote": text[start:end], "characterStart": start, "characterEnd": end,
                "passageId": next((str(item["id"]) for item in passages if int(item["characterStart"]) <= start < int(item["characterEnd"])), passage_id),
                "matchMethod": "normalized", "matchScore": 0.99,
            }

    candidates = []
    for passage in passages:
        passage_tokens = _anchor_tokens(passage["text"])
        if not quote_tokens or not passage_tokens:
            continue
        matcher = difflib.SequenceMatcher(None, quote_tokens, passage_tokens, autojunk=False)
        longest = matcher.find_longest_match()
        coverage = longest.size / max(1, len(quote_tokens))
        similarity = matcher.ratio()
        score = 0.55 * coverage + 0.45 * similarity
        if passage_id and passage["id"] == passage_id:
            score += 0.10
        if requested_start >= 0 and int(passage["characterStart"]) <= requested_start <= int(passage["characterEnd"]):
            score += 0.08
        candidates.append((min(1.0, score), passage))
    candidates.sort(key=lambda item: item[0], reverse=True)
    if candidates and candidates[0][0] >= 0.84 and (len(candidates) == 1 or candidates[0][0] - candidates[1][0] >= 0.06):
        score, passage = candidates[0]
        start, end = int(passage["characterStart"]), int(passage["characterEnd"])
        return {
            "quote": text[start:end], "characterStart": start, "characterEnd": end,
            "passageId": passage["id"], "matchMethod": "fuzzy-triangulated", "matchScore": round(score, 3),
            "suppliedQuote": quote,
        }
    return None


def text_masking_quoted_dialogue(text: str) -> str:
    """Blank quoted spans without changing canonical character offsets."""
    return re.sub(r"[“\"].*?[”\"]", lambda match: " " * len(match.group()), text, flags=re.S)


def narrative_person_metrics(text: str) -> dict[str, object]:
    narration = text_masking_quoted_dialogue(text)
    first = len(re.findall(r"\b(?:I|me|my|mine|myself|we|us|our|ours|ourselves)\b", narration, re.I))
    second = len(re.findall(r"\b(?:you|your|yours|yourself|yourselves)\b", narration, re.I))
    third = len(re.findall(r"\b(?:he|him|his|himself|she|her|hers|herself|they|them|their|theirs|themselves)\b", narration, re.I))
    words = max(1, len(re.findall(r"\b[A-Za-z]+\b", narration)))
    dominant = "uncertain"
    # Third-person references are expected inside first-person narration; they
    # do not vote against a sustained unquoted narrator speaking as I/we.
    if first >= 4 and first / words >= 0.0025:
        dominant = "first_person"
    elif second >= 8 and second / words >= 0.008:
        dominant = "second_person"
    elif third >= 6:
        dominant = "third_person"
    return {"firstPersonPronouns": first, "secondPersonPronouns": second, "thirdPersonPronouns": third, "narrationWordCount": words, "dominantPerson": dominant}


def evidence_supports_viewpoint_shift(source_text: str, evidence_items: list[dict[str, object]]) -> bool:
    """Require before/after narrative evidence rather than pronouns in speech."""
    if len(evidence_items) < 2:
        return False
    masked = text_masking_quoted_dialogue(source_text)
    persons: set[str] = set()
    for item in evidence_items:
        start = max(0, int(item.get("characterStart") or 0))
        end = min(len(masked), int(item.get("characterEnd") or start))
        narrative_evidence = masked[start:end]
        if len(re.findall(r"\b[A-Za-z]+\b", narrative_evidence)) < 8:
            continue
        first = len(re.findall(r"\b(?:I|me|my|mine|myself|we|us|our|ours|ourselves)\b", narrative_evidence, re.I))
        second = len(re.findall(r"\b(?:you|your|yours|yourself|yourselves)\b", narrative_evidence, re.I))
        third = len(re.findall(r"\b(?:he|him|his|himself|she|her|hers|herself|they|them|their|theirs|themselves)\b", narrative_evidence, re.I))
        person = "uncertain"
        if first and first >= second and first >= third:
            person = "first_person"
        elif second >= 2 and second > first and second >= third:
            person = "second_person"
        elif third >= 2 and third > first and third > second:
            person = "third_person"
        if person != "uncertain":
            persons.add(person)
    return len(persons) >= 2


def evidence_supports_mortality(evidence_items: list[dict[str, object]]) -> bool:
    """Require the mortality tag to point at death or credible mortal danger."""
    language = " ".join(str(item.get("quote") or "") for item in evidence_items)
    return bool(re.search(
        r"\b(?:death|dead|die|dies|died|dying|mortal|mortality|kill(?:ed|ing|s)?|murder(?:ed|ing|s)?|"
        r"assassin(?:ated|ation)?|fatal|corpse|grave|burial|buried|life[- ]threatening|life and death)\b",
        language, re.I,
    ))


def chapter_tag_schema() -> dict[str, object]:
    all_ids = [signal_id for ids in TAG_FAMILIES.values() for signal_id in ids]
    evidence = {"type": "object", "properties": {"passage_id": {"type": "string", "minLength": 1}, "quote": {"type": "string", "minLength": 1}, "character_start": {"type": "integer", "minimum": 0}, "character_end": {"type": "integer", "minimum": 1}, "location": {"type": "string"}}, "required": ["passage_id", "quote", "character_start", "character_end"]}
    # Structured generation must enforce the same provenance contract as the
    # semantic validator below. Returned signals are material findings, so an
    # empty evidence array is never a valid shape; weak or absent signals are
    # omitted instead of emitted without support.
    signal = {"type": "object", "properties": {"id": {"type": "string", "enum": all_ids}, "family": {"type": "string", "enum": list(TAG_FAMILIES)}, "score": {"type": "number", "minimum": .25, "maximum": 1}, "confidence": {"type": "number", "minimum": 0, "maximum": 1}, "explanation": {"type": "string", "minLength": 1}, "evidence": {"type": "array", "minItems": 1, "items": evidence}}, "required": ["id", "family", "score", "confidence", "explanation", "evidence"]}
    return {"type": "object", "properties": {"signals": {"type": "array", "items": signal}, "candidate_signals": {"type": "array", "items": {"type": "object", "properties": {"label": {"type": "string"}, "family": {"type": "string"}, "explanation": {"type": "string"}}, "required": ["label", "explanation"]}}}, "required": ["signals", "candidate_signals"]}


def analyze_chapter_tags(chapter: dict[str, object], model: str, cancel_event: threading.Event | None = None, run_key: str = "") -> dict[str, object]:
    vocabulary = "\n".join(f"- {family}: {', '.join(ids)}" for family, ids in TAG_FAMILIES.items())
    text = str(chapter.get("text") or "")[:60_000]
    person_metrics = narrative_person_metrics(text)
    prompt = f"""Score this manuscript chapter against Bookinator's fixed editorial taxonomy.
Return JSON matching the supplied schema. Use only the listed signal IDs and their matching family.
Score means strength in the text; confidence means confidence in your judgment. Use score anchors .25, .5, .75, and 1.
Return only signals that score at least .25. Every returned signal requires at least one evidence reference; signals above .6 normally require two unless one scene dominates the chapter. For every reference return the supplied passage ID, its printed character start and end, and an exact quote copied from that passage. These redundant coordinates will be triangulated against the canonical source. Omit weak or absent signals instead of returning them with empty evidence. Do not force a label. Put a useful missing label in candidate_signals rather than inventing an ID.

Narration measured outside quoted dialogue: {json.dumps(person_metrics, ensure_ascii=False)}. Treat a decisive measured person as a constraint. Do not label first-person narration as third-person merely because the narrator describes other characters.
Evidence discipline: a first_person signal must cite a passage containing first-person narration (I, me, my, we, or us) outside dialogue. Do not use a neutral descriptive sentence merely because it occurs in a first-person chapter.
Viewpoint-shift discipline: dialogue never changes the narrative viewpoint. Return viewpoint_shift only with at least two exact evidence references: one establishing the prior narrative person and another establishing sustained narration in a different person. Pronouns spoken by a character, including "you" in dialogue, are not evidence of a viewpoint shift.

Chapter-function discipline: use setup only when this chapter plants a specific later-facing obligation, condition, object, relationship, or expectation that is not already active. Mere orientation, exposition, atmosphere, or continuation of an existing thread is not setup. Prefer the more concrete function when the evidence supports one.

Taxonomy discipline:
- exposition requires direct delivery of prior-world facts, background, history, or an explicit explanation. Recollection of the immediately preceding action, active dialogue, atmosphere, and dream imagery are not exposition merely because they inform the reader.
- mortality requires direct evidence of death, dying, fatal danger, bodily decline that credibly threatens life, or a character's explicit confrontation with mortality. Melancholy, sleep, elapsed time, or languor alone are insufficient.
- setup requires a newly planted later-facing element. Do not relabel a continuing mystery or already-active promise as setup.

Taxonomy:
{vocabulary}

Chapter: {chapter.get('title')}
Chapter title: {chapter.get('chapterTitle') or 'Not stated'}
{manuscript_location_prompt(chapter)}

Canonical source passages:
{evidence_passage_prompt(text)}
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
        evidence_items = []
        for item in raw.get("evidence", []) if isinstance(raw.get("evidence"), list) else []:
            anchored = resolve_source_evidence(text, item)
            if anchored:
                if isinstance(item, dict) and item.get("location"):
                    anchored["location"] = str(item["location"])
                evidence_items.append(anchored)
        if not evidence_items:
            reason = f"The model suggested {signal_id}, but its evidence could not be anchored uniquely in the chapter."
            candidate_signals.append({"label": signal_id, "family": family, "explanation": reason})
            rejected_signals.append({"id": signal_id, "family": family, "reason": reason})
            continue
        if signal_id == "first_person" and not any(
            int(narrative_person_metrics(str(item.get("quote") or "")).get("firstPersonPronouns") or 0) > 0
            for item in evidence_items
        ):
            reason = "The model labeled this chapter first-person, but none of its evidence passages contains first-person narration."
            candidate_signals.append({"label": signal_id, "family": family, "explanation": reason})
            rejected_signals.append({"id": signal_id, "family": family, "reason": reason})
            continue
        if signal_id == "mortality" and not evidence_supports_mortality(evidence_items):
            reason = "The model labeled this chapter mortality, but its evidence does not mention death, dying, or credible mortal danger."
            candidate_signals.append({"label": signal_id, "family": family, "explanation": reason})
            rejected_signals.append({"id": signal_id, "family": family, "reason": reason})
            continue
        if signal_id == "viewpoint_shift" and not evidence_supports_viewpoint_shift(text, evidence_items):
            reason = "The model labeled a viewpoint shift, but its exact evidence does not establish two different narrative viewpoints outside dialogue."
            candidate_signals.append({"label": signal_id, "family": family, "explanation": reason})
            rejected_signals.append({"id": signal_id, "family": family, "reason": reason})
            continue
        dominant_person = str(person_metrics.get("dominantPerson") or "uncertain")
        if family == "viewpoint" and dominant_person == "first_person" and signal_id in {"third_limited", "third_omniscient", "objective_external"}:
            reason = f"The model suggested {signal_id}, but first-person pronouns decisively dominate narration outside dialogue."
            rejected_signals.append({"id": signal_id, "family": family, "reason": reason})
            continue
        signals.append({"id": signal_id, "family": family, "score": round(score, 3), "confidence": round(confidence, 3), "explanation": str(raw.get("explanation") or "").strip(), "evidence": evidence_items})
    deduplicated: dict[str, dict[str, object]] = {}
    for signal in signals:
        key = normalize_lexical_key(signal["id"])
        current = deduplicated.get(key)
        if current is None:
            deduplicated[key] = signal
            continue
        current["score"] = max(float(current["score"]), float(signal["score"]))
        current["confidence"] = max(float(current["confidence"]), float(signal["confidence"]))
        receipts = {(int(item["characterStart"]), int(item["characterEnd"])): item for item in current["evidence"]}
        receipts.update({(int(item["characterStart"]), int(item["characterEnd"])): item for item in signal["evidence"]})
        current["evidence"] = list(receipts.values())
        normalized_signals.append({"id": str(signal["id"]), "fromFamily": str(signal["family"]), "toFamily": str(current["family"]), "reason": "Merged duplicate canonical tag identity."})
    signals = list(deduplicated.values())
    signals.sort(key=lambda item: (-float(item["score"]), -float(item["confidence"]), str(item["family"]), str(item["id"])))
    dialogue_characters = sum(len(match.group()) for match in re.finditer(r"[“\"].*?[”\"]", text, re.S))
    return {"schema": TAG_SCHEMA_VERSION, "taxonomyVersion": TAG_TAXONOMY_VERSION, "promptVersion": TAG_PROMPT_VERSION, "chapterSequence": chapter.get("sequence") or chapter.get("number"), "model": model, "signals": signals, "candidateSignals": candidate_signals, "normalizedSignals": normalized_signals, "rejectedSignals": rejected_signals, "deterministic": {"dialogueCharacterRatio": round(dialogue_characters / len(text), 4) if text else 0, "narrativePerson": person_metrics, "paragraphCount": chapter.get("paragraphCount"), "sentenceCount": chapter.get("sentenceCount"), "sectionCount": chapter.get("sectionCount")}}


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


SMELL_DENSITY_RULES = {
    "clause count", "clause load proxy", "finite verb load", "sentence length",
}


def smell_evidence_family(evidence: dict[str, object]) -> str:
    """Give detector rules a stable editorial family before any model sees them."""
    rule = normalize_lexical_key(evidence.get("rule"))
    if rule in {"clause count", "clause load proxy"}:
        return "Complex sentence"
    if rule == "finite verb load":
        return "Overloaded sentence"
    if rule == "sentence length":
        return "Long sentence"
    if rule == "repeated word":
        return "Repeated word"
    if rule.startswith("weasel words"):
        return "Weasel words"
    if rule == "misc but":
        return "Paragraph-opening conjunction"
    message = str(evidence.get("message") or "")
    return canonical_smell_label(rule or message)


def route_smell_candidate(candidate: dict[str, object]) -> dict[str, object]:
    """Apply cheap, inspectable policy before spending a primary-model read.

    Sentence length and clause density are measurements, not defects. A single
    density detector therefore becomes a chapter-level style observation. We
    ask the deep reader only when independent measurements overlap strongly
    enough that there may be a concrete local reading cost.
    """
    evidence = [item for item in candidate.get("evidence", []) if isinstance(item, dict)]
    rules = {normalize_lexical_key(item.get("rule")) for item in evidence}
    families = list(dict.fromkeys(smell_evidence_family(item) for item in evidence))
    candidate["issueFamilies"] = families
    policy_measurement = bool(rules) and all(rule in SMELL_DENSITY_RULES or rule.startswith("weasel words") or rule == "misc but" for rule in rules)
    word_count = max((int(item.get("wordCount") or 0) for item in evidence), default=0)
    clause_count = max((int(item.get("clauseCount") or 0) for item in evidence), default=0)
    finite_verbs = max((int(item.get("finiteVerbCount") or 0) for item in evidence), default=0)
    connectors = max((int(item.get("connectorCount") or 0) for item in evidence), default=0)
    density_signals = len(rules & SMELL_DENSITY_RULES)
    unusually_dense = word_count >= 65 or density_signals >= 3 or (density_signals >= 2 and word_count >= 40)
    if policy_measurement and not unusually_dense:
        issue = families[0] if families else "Sentence complexity"
        return {
            "route": "style_metric", "review": False, "issue": issue,
            "reason": "Recorded as a chapter-level style measurement; the available evidence does not establish a sentence-level reading problem.",
        }
    return {
        "route": "deep_review", "review": True,
        "issue": families[0] if len(families) == 1 else "Overlapping prose signals",
        "reason": "Independent evidence or a non-density detector warrants a selective editorial read.",
    }


def smell_style_signals(candidates: list[dict[str, object]]) -> list[dict[str, object]]:
    grouped: dict[str, dict[str, object]] = {}
    for candidate in candidates:
        routing = candidate.get("routing") if isinstance(candidate.get("routing"), dict) else {}
        if routing.get("route") != "style_metric":
            continue
        for family in candidate.get("issueFamilies", []) or [routing.get("issue")]:
            label = str(family or "Sentence complexity")
            item = grouped.setdefault(label, {"issue": label, "candidateCount": 0, "characterStarts": []})
            item["candidateCount"] = int(item["candidateCount"]) + 1
            item["characterStarts"].append(int(candidate.get("characterStart") or 0))
    return sorted(grouped.values(), key=lambda item: (-int(item["candidateCount"]), str(item["issue"])))


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
        candidate = {"id": candidate_id, "characterStart": start, "characterEnd": end, "sentence": sentence, "context": text[context_start:context_end].strip(), "evidence": evidence, "detectors": sorted({str(item.get("detector") or "") for item in evidence})}
        candidate["routing"] = route_smell_candidate(candidate)
        candidates.append(candidate)
    if candidate_limit is not None:
        candidates = candidates[:max(0, candidate_limit)]
    item_schema = {"type": "object", "properties": {"id": {"type": "string"}, "verdict": {"type": "string", "enum": ["report", "dismiss", "informational"]}, "severity": {"type": "string", "enum": ["low", "medium", "high"]}, "issue": {"type": "string"}, "reason": {"type": "string"}}, "required": ["id", "verdict", "severity", "issue", "reason"]}
    schema = {"type": "object", "properties": {"judgments": {"type": "array", "items": item_schema}}, "required": ["judgments"]}
    judgments: dict[str, dict[str, object]] = {}
    for candidate in candidates:
        routing = candidate.get("routing") if isinstance(candidate.get("routing"), dict) else {}
        if not routing.get("review", True):
            judgments[str(candidate["id"])] = {
                "id": candidate["id"], "verdict": "informational", "severity": "low",
                "issue": str(routing.get("issue") or "Style measurement"),
                "reason": str(routing.get("reason") or "Recorded as a chapter-level style measurement."),
                "policyDecision": True,
            }
    review_candidates = [candidate for candidate in candidates if (candidate.get("routing") or {}).get("review", True)]
    review_errors: list[dict[str, object]] = []
    batch_size = 8
    total_batches = (len(review_candidates) + batch_size - 1) // batch_size

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
            "schema": SMELL_SCHEMA_VERSION, "policyVersion": SMELL_POLICY_VERSION,
            "promptVersion": SMELL_PROMPT_VERSION, "model": model, "inputCharacters": len(text),
            "candidates": visible_candidates,
            "kept": sum(item["judgment"].get("verdict") in {"report", "keep"} for item in decided),
            "dismissed": sum(item["judgment"].get("verdict") == "dismiss" for item in decided),
            "informational": sum(item["judgment"].get("verdict") == "informational" for item in decided),
            "styleSignals": smell_style_signals(visible_candidates),
            "routedForDeepReview": len(review_candidates),
            "detectorErrors": local.get("errors", {}), "reviewErrors": copy.deepcopy(review_errors),
            "reviewProgress": {"completedBatches": completed_batches, "totalBatches": total_batches, "complete": complete},
        }

    if on_batch:
        on_batch(artifact_snapshot(0))
    for offset in range(0, len(review_candidates), batch_size):
        batch = review_candidates[offset:offset + batch_size]
        payload = [{"id": item["id"], "sentence": item["sentence"], "context": item["context"], "evidence": [{"detector": evidence.get("detector"), "rule": evidence.get("rule"), "message": evidence.get("message")} for evidence in item["evidence"]]} for item in batch]
        prompt = f"""You are Bookinator's selective fiction editor. A deterministic policy has already removed ordinary sentence-length and clause-density measurements from this deep-review batch. Judge only these routed candidates; do not invent new complaints.
Preserve voice, rhythm, dialect, fragments, deliberate repetition, unusual vocabulary, genre conventions, and character speech. Do not reward blandness or mechanically simplified prose. A measurement can be true without being a problem. But you are still an editor: preservation of voice is not a reason to excuse a comma splice, garden path, ambiguous reference, accidental repetition, or a sentence whose nested structure makes its main action unnecessarily hard to recover.
Return exactly one judgment per id. "report" means a professional editor would probably interrupt the author at this exact passage because the source demonstrates a concrete reading cost, ambiguity, grammatical fault, or avoidable burden. It does not mean the sentence is objectively bad. Dismiss wrong, doctrinaire, or clearly purposeful complaints. Mark a true observation informational when it is useful but not a local defect. Consolidate overlapping evidence. Do not rewrite. Make issue a specific 2–6 word label. Make reason one concrete sentence about this text; never merely say that complexity adds richness or does not impede comprehension.

Consistency rules:
- If your reason says the sentence is clear, understandable, effective, flows well, or does not impede comprehension, verdict must be dismiss or informational—not report.
- Length or clause count alone is not a reading cost. For report, identify what the reader may misattach, lose, reread, or mistake.
- If you cannot name the exact words or relationship that creates that cost, use informational or dismiss—not report.
- A real comma splice between independent clauses is report. A deliberate fragment, paragraph-opening "But," dialect, or harmless repeated function word is normally dismiss.
- An Oxford-comma candidate is report only when it is a real series of three or more coordinate items; dismiss false positives on paired adjectives or trailing descriptors.

Candidates: {json.dumps(payload, ensure_ascii=False)}"""
        try:
            result, _ = run_structured_model(prompt, model, schema, cancel_event, f"{run_key}:batch-{offset // batch_size + 1}")
            allowed = {str(candidate["id"]) for candidate in batch}
            for item in result.get("judgments", []) if isinstance(result.get("judgments"), list) else []:
                if isinstance(item, dict) and str(item.get("id") or "") in allowed:
                    raw_issue = str(item.get("issue") or "").strip()
                    judgments[str(item["id"])] = {
                        **item,
                        "rawIssue": raw_issue,
                        "issueKey": normalize_lexical_key(canonical_smell_label(raw_issue)),
                        "issue": canonical_smell_label(raw_issue),
                    }
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


SHADOW_VIEWPOINT_HEADINGS = ("TIMMY", "SHADOW")


def compile_shadow_heading_diagnostic(
    source_occurrences: list[dict[str, object]], chapters: list[dict[str, object]],
) -> dict[str, object]:
    """Compare Michael's standalone PDF markers with canonical Markdown headings.

    This is intentionally a narrow, read-only diagnostic for *Shadow*, not a
    general manuscript-structure heuristic. Page-to-chapter assignment keeps
    the cover/title occurrence of SHADOW out of the story count.
    """
    terms = SHADOW_VIEWPOINT_HEADINGS
    chapter_rows: list[dict[str, object]] = []
    story_ranges: list[tuple[int, int, int, str]] = []
    canonical_occurrences: list[dict[str, object]] = []
    attached_occurrences: list[dict[str, object]] = []
    bare_occurrences: list[dict[str, object]] = []
    heading_pattern = re.compile(r"^\s*(#{1,6})\s+(TIMMY|SHADOW)\s*$", re.IGNORECASE)
    bare_pattern = re.compile(r"^\s*(TIMMY|SHADOW)\s*$", re.IGNORECASE)
    attached_pattern = re.compile(r"\b(TIMMY|SHADOW)\s*$")

    for chapter in chapters:
        sequence = int(chapter.get("sequence") or chapter.get("number") or 0)
        title = strip_markdown_heading(chapter.get("title") or f"Section {sequence}")
        page_start = int(chapter.get("pageStart") or 0)
        page_end = int(chapter.get("pageEnd") or page_start)
        is_front_matter = title.strip().casefold().startswith("front matter")
        if not is_front_matter and page_start > 0:
            story_ranges.append((page_start, page_end, sequence, title))
        markdown = str(chapter.get("markdown") or chapter.get("text") or "")
        per_term = {term: {"headings": 0, "attached": 0, "bare": 0} for term in terms}
        if is_front_matter:
            chapter_rows.append({
                "sequence": sequence, "title": title, "pageStart": page_start,
                "pageEnd": page_end, "frontMatter": True, "canonical": per_term,
            })
            continue
        for line_number, line in enumerate(markdown.splitlines(), start=1):
            heading_match = heading_pattern.fullmatch(line)
            if heading_match:
                term = heading_match.group(2).upper()
                level = len(heading_match.group(1))
                per_term[term]["headings"] += 1
                canonical_occurrences.append({
                    "term": term, "chapterSequence": sequence, "chapterTitle": title,
                    "line": line_number, "level": level,
                })
                continue
            bare_match = bare_pattern.fullmatch(line)
            if bare_match:
                term = bare_match.group(1).upper()
                per_term[term]["bare"] += 1
                bare_occurrences.append({
                    "term": term, "chapterSequence": sequence, "chapterTitle": title,
                    "line": line_number,
                })
                continue
            attached_match = attached_pattern.search(line)
            if attached_match:
                term = attached_match.group(1).upper()
                per_term[term]["attached"] += 1
                excerpt = re.sub(r"\s+", " ", line).strip()
                attached_occurrences.append({
                    "term": term, "chapterSequence": sequence, "chapterTitle": title,
                    "line": line_number, "excerpt": excerpt[-180:],
                })
        chapter_rows.append({
            "sequence": sequence, "title": title, "pageStart": page_start,
            "pageEnd": page_end, "frontMatter": is_front_matter, "canonical": per_term,
        })

    story_source: list[dict[str, object]] = []
    excluded_source: list[dict[str, object]] = []
    for occurrence in source_occurrences:
        page = int(occurrence.get("page") or 0)
        owner = next((item for item in story_ranges if item[0] <= page <= item[1]), None)
        enriched = {"term": str(occurrence.get("term") or "").upper(), "page": page}
        if owner:
            enriched.update({"chapterSequence": owner[2], "chapterTitle": owner[3]})
            story_source.append(enriched)
        else:
            enriched["reason"] = "Outside the mapped story chapters (usually cover or front matter)."
            excluded_source.append(enriched)

    comparisons: list[dict[str, object]] = []
    for term in terms:
        source_count = sum(1 for item in story_source if item["term"] == term)
        headings = [item for item in canonical_occurrences if item["term"] == term]
        attached = [item for item in attached_occurrences if item["term"] == term]
        bare = [item for item in bare_occurrences if item["term"] == term]
        invalid_levels = [item for item in headings if item["level"] not in {2, 3}]
        ok = source_count == len(headings) and not attached and not bare and not invalid_levels
        comparisons.append({
            "term": term, "sourceCount": source_count, "headingCount": len(headings),
            "attachedCount": len(attached), "bareCount": len(bare),
            "invalidLevelCount": len(invalid_levels), "difference": len(headings) - source_count,
            "ok": ok,
        })

    chapter_discrepancies: list[dict[str, object]] = []
    story_sequences = {item[2]: item[3] for item in story_ranges}
    for sequence, title in story_sequences.items():
        for term in terms:
            source_items = [item for item in story_source if item["term"] == term and item.get("chapterSequence") == sequence]
            heading_items = [item for item in canonical_occurrences if item["term"] == term and item.get("chapterSequence") == sequence]
            attached_items = [item for item in attached_occurrences if item["term"] == term and item.get("chapterSequence") == sequence]
            bare_items = [item for item in bare_occurrences if item["term"] == term and item.get("chapterSequence") == sequence]
            invalid_items = [item for item in heading_items if item["level"] not in {2, 3}]
            if len(source_items) == len(heading_items) and not attached_items and not bare_items and not invalid_items:
                continue
            chapter_discrepancies.append({
                "term": term, "chapterSequence": sequence, "chapterTitle": title,
                "sourceCount": len(source_items), "sourcePages": [item["page"] for item in source_items],
                "headingCount": len(heading_items), "headingLines": [item["line"] for item in heading_items],
                "attachedCount": len(attached_items), "bareCount": len(bare_items),
                "invalidLevelCount": len(invalid_items),
            })

    return {
        "schema": "bookinator-shadow-heading-diagnostic-v1",
        "terms": list(terms),
        "ok": all(item["ok"] for item in comparisons),
        "comparisons": comparisons,
        "sourceOccurrences": story_source,
        "excludedSourceOccurrences": excluded_source,
        "canonicalOccurrences": canonical_occurrences,
        "attachedOccurrences": attached_occurrences,
        "bareOccurrences": bare_occurrences,
        "chapterDiscrepancies": chapter_discrepancies,
        "chapters": chapter_rows,
        "note": "Canonical chapter titles use ##; viewpoint changes within a chapter use ###.",
    }


def shadow_heading_diagnostic(book: dict[str, object]) -> dict[str, object]:
    manuscript_id = str(book.get("manuscriptId") or "")
    manuscript_path = BOOKS_ROOT / manuscript_id / "manuscript.pdf"
    if not manuscript_id or not manuscript_path.is_file():
        raise FileNotFoundError("This book has no preserved PDF to scan.")
    try:
        raw_chapters = json.loads(extracted_chapters_path(book).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise FileNotFoundError("This book has no composed chapters to compare yet.") from error
    if not isinstance(raw_chapters, list) or not raw_chapters:
        raise FileNotFoundError("This book has no composed chapters to compare yet.")
    chapters = []
    for raw_chapter in raw_chapters:
        if not isinstance(raw_chapter, dict):
            continue
        sequence = int(raw_chapter.get("sequence") or raw_chapter.get("number") or 0)
        canonical = load_chapter_source(book, sequence) or raw_chapter
        chapters.append({**raw_chapter, **canonical})
    try:
        import pymupdf  # type: ignore[import-not-found]
        source_occurrences: list[dict[str, object]] = []
        with pymupdf.open(manuscript_path) as document:
            page_blocks = [page.get_text("blocks") for page in document]
            for page_number, blocks in enumerate(page_blocks, start=1):
                for block in blocks:
                    for raw_line in str(block[4] or "").splitlines():
                        line = re.sub(r"\s+", " ", raw_line).strip().upper()
                        if line in SHADOW_VIEWPOINT_HEADINGS:
                            source_occurrences.append({"term": line, "page": page_number})
    except ImportError as error:
        raise RuntimeError("PDF text support is not installed in this Bookinator environment.") from error
    result = compile_shadow_heading_diagnostic(source_occurrences, chapters)
    preview_chapters: list[dict[str, object]] = []
    for raw_chapter in raw_chapters:
        if not isinstance(raw_chapter, dict):
            continue
        first_page = max(0, int(raw_chapter.get("pageStart") or 1) - 1)
        last_page = min(len(page_blocks), int(raw_chapter.get("pageEnd") or first_page + 1))
        text = pdf_blocks_to_paragraph_text(page_blocks[first_page:last_page])
        preview = {**raw_chapter, "text": text}
        preview.update(chapter_structure(text, str(raw_chapter.get("title") or "")))
        preview["markdown"] = chapter_markdown(preview)
        preview_chapters.append(preview)
    result["preview"] = compile_shadow_heading_diagnostic(source_occurrences, preview_chapters)
    result.update({"bookId": book.get("id"), "title": book.get("title"), "scannedAt": utc_now()})
    return result


def chapter_artifacts_path(book: dict[str, object]) -> Path:
    return BOOKS_ROOT / str(book.get("manuscriptId")) / "chapters"


def chunk_artifacts_path(book: dict[str, object]) -> Path:
    return BOOKS_ROOT / str(book.get("manuscriptId")) / "chunks"


def cumulative_context_path(book: dict[str, object], sequence: int) -> Path:
    return BOOKS_ROOT / str(book.get("manuscriptId")) / "llm-review" / "contexts" / f"{sequence:04d}.json"


def llm_review_packet_path(book: dict[str, object], sequence: int) -> Path:
    return BOOKS_ROOT / str(book.get("manuscriptId")) / "llm-review" / "packets" / f"{sequence:04d}.json"


def llm_review_result_path(book: dict[str, object], sequence: int) -> Path:
    return BOOKS_ROOT / str(book.get("manuscriptId")) / "llm-review" / "results" / f"{sequence:04d}.json"


def chapter_reading_path(book: dict[str, object], sequence: int) -> Path:
    return BOOKS_ROOT / str(book.get("manuscriptId")) / "chapter-readings" / f"{sequence:04d}.json"


def gliner_signals_path(book: dict[str, object], sequence: int) -> Path:
    return BOOKS_ROOT / str(book.get("manuscriptId")) / "gliner-signals" / f"{sequence:04d}.json"


def write_json_artifact(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def read_json_artifact(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def reconcile_completed_chapter_readings(book: dict[str, object], pipeline: dict[str, object]) -> bool:
    """Rehydrate a completed atomic reading if its final ledger write was lost.

    The chapter-reading artifact is written before pipeline.json. A process
    interruption—or a rejected stale snapshot—must never force the expensive
    model call to run again when that durable artifact is already complete.
    """
    changed = False
    stages = {str(stage.get("id") or ""): stage for stage in pipeline.get("stages", [])}
    for chapter in pipeline.get("chapters", []):
        try:
            sequence = int(chapter.get("sequence") or chapter.get("number") or 0)
        except (TypeError, ValueError):
            continue
        if sequence < 1 or chapter.get("chapterReadingStatus") == "complete":
            continue
        artifact = read_json_artifact(chapter_reading_path(book, sequence))
        normalized = artifact.get("normalized") if isinstance(artifact.get("normalized"), dict) else {}
        summary = normalized.get("summary") if isinstance(normalized.get("summary"), dict) else {}
        dossier = normalized.get("dossier") if isinstance(normalized.get("dossier"), dict) else {}
        review = normalized.get("review") if isinstance(normalized.get("review"), dict) else {}
        if artifact.get("status") != "complete" or not summary or not dossier:
            continue
        completed_at = str(artifact.get("completedAt") or utc_now())
        duration = float(artifact.get("durationSeconds") or 0)
        model = str(artifact.get("model") or "")
        signature = str(artifact.get("inputSignature") or "")
        chapter.update(copy.deepcopy(summary))
        chapter.update({
            "status": "complete", "completedAt": completed_at, "durationSeconds": 0.0,
            "model": model, "chapterReadingStatus": "complete",
            "chapterReadingStartedAt": artifact.get("startedAt"),
            "chapterReadingCompletedAt": completed_at,
            "chapterReadingDurationSeconds": duration,
            "chapterReadingPrimaryDurationSeconds": artifact.get("primaryDurationSeconds"),
            "chapterReadingConsistencyDurationSeconds": artifact.get("consistencyDurationSeconds"),
            "chapterReadingInputSignature": signature,
            "chapterReadingPromptVersion": str(artifact.get("schema") or CHAPTER_READING_PROMPT_VERSION),
            "chapterReadingPhase": "complete",
            "chapterReadingCast": copy.deepcopy(normalized.get("cast") or []),
            "chapterReadingConsistency": copy.deepcopy(normalized.get("consistency") or {}),
        })
        for key in ("error", "chapterReadingError", "interruptedAt"):
            chapter.pop(key, None)
        chunks = [item for item in pipeline.get("chunks", []) if int(item.get("chapterSequence") or 0) == sequence]
        for index, chunk in enumerate(chunks):
            shared = {
                "dossierStatus": "complete", "dossierModel": model,
                "dossierCompletedAt": completed_at, "dossierDurationSeconds": 0.0,
                "chapterReadingDurationSeconds": duration,
                "chapterReadingInputSignature": signature,
            }
            if index == 0:
                shared["dossier"] = copy.deepcopy(dossier)
            elif chunks:
                shared["dossierCoveredByChapterReading"] = int(chunks[0].get("sequence") or 0)
            chunk.update(shared)
            chunk_artifact = read_json_artifact(chunk_artifacts_path(book) / f"{int(chunk.get('sequence') or index + 1):04d}.json")
            chunk_artifact.update(shared)
            write_chunk_artifact(book, int(chunk.get("sequence") or index + 1), chunk_artifact)
        if review:
            chapter.update({
                "llmReviewStatus": "complete", "llmReviewCompletedAt": completed_at,
                "llmReviewDurationSeconds": 0.0, "llmReviewSharedDurationSeconds": duration,
                "llmReviewModel": model, "llmReviewInputSignature": signature,
                "llmReview": copy.deepcopy(review),
            })
            chapter.pop("llmReviewError", None)
        changed = True
    if changed:
        chapter_count = len(pipeline.get("chapters", []))
        summary_complete = sum(chapter.get("status") == "complete" for chapter in pipeline.get("chapters", []))
        dossier_count = len(pipeline.get("chunks", []))
        dossier_complete = sum(chunk.get("dossierStatus") == "complete" for chunk in pipeline.get("chunks", []))
        review_chapters = [chapter for chapter in pipeline.get("chapters", []) if strip_markdown_heading(chapter.get("title")).casefold() != "front matter"]
        review_complete = sum(chapter.get("llmReviewStatus") == "complete" for chapter in review_chapters)
        if stage := stages.get("summaries"):
            stage.update({"status": "complete" if summary_complete == chapter_count else "pending", "detail": f"Completed {summary_complete} of {chapter_count} chapter summaries."})
        if stage := stages.get("dossiers"):
            stage.update({"status": "complete" if dossier_complete == dossier_count else "pending", "detail": f"Completed {dossier_complete} of {dossier_count} structured dossiers."})
        if stage := stages.get("llm-review"):
            stage.update({"status": "complete" if review_complete == len(review_chapters) else "pending", "detail": f"Saved optional first-reader review for {review_complete} of {len(review_chapters)} chapters."})
    return changed


def optional_analysis_artifact(book: dict[str, object], kind: str, sequence: int) -> dict[str, object]:
    """Return a forensic view without adding debug payloads to normal pipeline responses."""
    if kind == "context":
        artifact = read_json_artifact(cumulative_context_path(book, sequence))
        inspection_input = artifact.get("input") if isinstance(artifact.get("input"), dict) else None
        inspection_output = artifact.get("context") if isinstance(artifact.get("context"), dict) else None
    elif kind == "llm-review":
        artifact = read_json_artifact(llm_review_result_path(book, sequence))
        packet = read_json_artifact(llm_review_packet_path(book, sequence))
        inspection_input = packet or None
        inspection_output = {
            "modelResponses": artifact.get("modelOutput") if isinstance(artifact.get("modelOutput"), dict) else None,
            "normalizedResult": artifact.get("result") if isinstance(artifact.get("result"), dict) else None,
        }
    else:
        raise ValueError("Choose Context or LLM Review.")
    if not artifact and not (kind == "llm-review" and packet):
        raise LookupError("That analysis artifact is not available.")
    return {
        "kind": kind,
        "chapterSequence": sequence,
        "status": artifact.get("status"),
        "error": artifact.get("error"),
        "schema": artifact.get("schema"),
        "model": artifact.get("model"),
        "input": inspection_input,
        "output": inspection_output,
    }


def analysis_run_artifact(book: dict[str, object], kind: str, item_id: str) -> dict[str, object]:
    """Expose the saved or reconstructable boundary around an analysis run.

    Newer optional LLM jobs retain their exact request packets. Older and
    deterministic jobs expose the canonical inputs Bookinator can reconstruct,
    and say so explicitly rather than pretending that they are byte-identical
    model requests.
    """
    if kind in {"context", "llm-review"}:
        return {**optional_analysis_artifact(book, kind, int(item_id)), "inputFidelity": "saved"}
    if kind == "gliner":
        sequence = int(item_id)
        artifact = read_json_artifact(gliner_signals_path(book, sequence))
        if not artifact:
            raise LookupError("That GLiNER signals artifact is not available.")
        return {
            "kind": kind,
            "chapterSequence": sequence,
            "status": artifact.get("status"),
            "error": artifact.get("error"),
            "schema": artifact.get("schema"),
            "model": artifact.get("model") or GLINER_MODEL_ID,
            "input": artifact.get("input"),
            "output": {
                "identityCandidates": artifact.get("identityCandidates", []),
                "raw": artifact.get("raw", {}),
                "timing": artifact.get("timing", {}),
            },
            "inputFidelity": "saved",
        }
    if kind == "chapter-reading":
        sequence = int(item_id)
        artifact = read_json_artifact(chapter_reading_path(book, sequence))
        if not artifact:
            raise LookupError("That Chapter Reading artifact is not available.")
        return {
            "kind": kind,
            "chapterSequence": sequence,
            "status": artifact.get("status"),
            "error": artifact.get("error"),
            "schema": artifact.get("schema"),
            "model": artifact.get("model"),
            "input": artifact.get("input"),
            "output": {
                "modelResponse": artifact.get("output"),
                "normalized": artifact.get("normalized"),
            },
            "inputFidelity": "saved",
        }

    pipeline = load_pipeline(book)
    chapters = pipeline.get("chapters", []) if isinstance(pipeline.get("chapters"), list) else []
    chunks = pipeline.get("chunks", []) if isinstance(pipeline.get("chunks"), list) else []

    def chapter_record() -> dict[str, object]:
        sequence = int(item_id)
        chapter = next((item for item in chapters if int(item.get("sequence") or item.get("number") or 0) == sequence), None)
        if not isinstance(chapter, dict):
            raise LookupError("That chapter analysis is not available.")
        return chapter

    if kind == "summary":
        chapter = chapter_record()
        sequence = int(item_id)
        inspection_input = load_chapter_source(book, sequence)
        inspection_output = {key: chapter.get(key) for key in (
            "status", "summary", "keyPoints", "endingState", "newQuestions", "questionDetails", "model",
            "startedAt", "completedAt", "durationSeconds", "error", "failedRuns", "summaryRuns",
        ) if chapter.get(key) is not None}
        status = chapter.get("status")
        model = chapter.get("model")
    elif kind == "dossier":
        sequence = int(item_id)
        chunk = next((item for item in chunks if int(item.get("sequence") or 0) == sequence), None)
        if not isinstance(chunk, dict):
            raise LookupError("That dossier analysis is not available.")
        saved_chunk = read_json_artifact(chunk_artifacts_path(book) / f"{sequence:04d}.json")
        inspection_input = {key: saved_chunk.get(key, chunk.get(key)) for key in (
            "id", "sequence", "chapterSequence", "chapterLabel", "chapterTitle", "chunkInChapter",
            "pageStart", "pageEnd", "overlap", "text",
        ) if saved_chunk.get(key, chunk.get(key)) is not None}
        inspection_output = {key: chunk.get(key) for key in (
            "dossierStatus", "dossier", "dossierModel", "dossierStartedAt", "dossierCompletedAt",
            "dossierDurationSeconds", "dossierError", "dossierRetryDiagnostics", "dossierRuns",
        ) if chunk.get(key) is not None}
        status = chunk.get("dossierStatus")
        model = chunk.get("dossierModel")
    elif kind in {"emotion", "tag", "smell"}:
        chapter = chapter_record()
        sequence = int(item_id)
        prefix = {"emotion": "emotion", "tag": "tag", "smell": "smell"}[kind]
        inspection_input = load_chapter_source(book, sequence)
        inspection_output = {
            "status": chapter.get(f"{prefix}Status"),
            "result": chapter.get(prefix),
            "model": chapter.get(f"{prefix}Model"),
            "startedAt": chapter.get(f"{prefix}StartedAt"),
            "completedAt": chapter.get(f"{prefix}CompletedAt"),
            "durationSeconds": chapter.get(f"{prefix}DurationSeconds"),
            "error": chapter.get(f"{prefix}Error"),
        }
        inspection_output = {key: value for key, value in inspection_output.items() if value is not None}
        status = chapter.get(f"{prefix}Status")
        model = chapter.get(f"{prefix}Model")
    elif kind in {"whole-summary", "whole-dossier", "whole-llm-review"}:
        if kind == "whole-summary":
            inspection_input = [
                {key: chapter.get(key) for key in ("sequence", "title", "summary", "keyPoints", "endingState", "newQuestions", "questionDetails") if chapter.get(key) is not None}
                for chapter in chapters if chapter.get("status") == "complete"
            ]
            record = pipeline.get("wholeBookSummary")
        elif kind == "whole-dossier":
            inspection_input = [
                {"sequence": chunk.get("sequence"), "chapterSequence": chunk.get("chapterSequence"), "dossier": chunk.get("dossier")}
                for chunk in chunks if chunk.get("dossierStatus") == "complete" and chunk.get("dossier")
            ]
            record = pipeline.get("wholeBookDossier")
        else:
            inspection_input = [
                {"sequence": chapter.get("sequence"), "title": chapter.get("title"), "llmReview": chapter.get("llmReview")}
                for chapter in chapters if chapter.get("llmReviewStatus") == "complete" and chapter.get("llmReview")
            ]
            record = pipeline.get("wholeBookLlmReview")
        inspection_output = record if isinstance(record, dict) else None
        status = record.get("status") if isinstance(record, dict) else None
        model = record.get("model") if isinstance(record, dict) else None
    elif kind == "stage":
        stage = next((item for item in pipeline.get("stages", []) if str(item.get("id") or "") == item_id), None)
        if not isinstance(stage, dict):
            raise LookupError("That pipeline step is not available.")
        dependencies = set(stage.get("dependsOn") or [])
        if item_id == "structure":
            metadata = manuscript_metadata(str(book.get("manuscriptId") or ""))
            inspection_input = {
                "scope": {"bookId": book.get("id"), "manuscriptId": book.get("manuscriptId")},
                "sourceFormat": metadata.get("sourceFormat") or book.get("sourceFormat"),
                "sourcePagination": "fixed" if source_has_fixed_pagination(book) else "reflowable",
                "sourceSpans": int((pipeline.get("manuscriptMetrics") or {}).get("pageCount") or 0),
                "acceptedHeadingVariants": pipeline.get("acceptedChapterLabelVariants", []),
                "demotedBoundarySpans": pipeline.get("demotedChapterBoundaryPages", []),
            }
            inspection_output = {
                "stage": stage,
                "chapters": chapters,
                "warnings": pipeline.get("chapterMapWarnings", []),
                "headingReport": pipeline.get("chapterHeadingReport", {}),
            }
        else:
            inspection_input = {
                "dependencies": [item for item in pipeline.get("stages", []) if item.get("id") in dependencies],
                "scope": {"bookId": book.get("id"), "manuscriptId": book.get("manuscriptId")},
            }
            inspection_output = stage
        status = stage.get("status")
        model = stage.get("model")
    else:
        raise ValueError("Choose a supported analysis run.")

    return {
        "kind": kind,
        "itemId": item_id,
        "status": status,
        "model": model,
        "inputFidelity": "reconstructed",
        "input": inspection_input,
        "output": inspection_output,
    }


def page_bounded_chunks(
    chapters: list[dict[str, object]], page_texts: list[str], target_characters: int = 32_000,
    *, preserve_source: bool = False,
) -> list[dict[str, object]]:
    chunks: list[dict[str, object]] = []
    for chapter in chapters:
        page_start = int(chapter.get("pageStart") or 1)
        page_end = int(chapter.get("pageEnd") or page_start)
        pages = [
            (number, page_texts[number - 1].strip() if preserve_source else normalize_pdf_text(page_texts[number - 1]))
            for number in range(page_start, min(page_end, len(page_texts)) + 1)
        ]
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
                "sourcePagination": chapter.get("sourcePagination", "fixed"),
                "text": chunk_text,
                "inputCharacters": len(chunk_text),
                **chunk_metrics,
                "overlap": "one-page" if chapter_chunk > 1 else "none",
                "dossierStatus": "pending",
            })
    return chunks


def ensure_chunk_artifacts(
    book: dict[str, object], chapters: list[dict[str, object]], page_texts: list[str] | None = None,
    *, preserve_source: bool | None = None,
) -> dict[str, object]:
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
                metadata.append({key: artifact.get(key) for key in ("id", "sequence", "chapterSequence", "chapterLabel", "chapterTitle", "chunkInChapter", "pageStart", "pageEnd", "sourcePagination", "inputCharacters", "characterCount", "wordCount", "paragraphCount", "lineCount", "sentenceCount", "averageSentenceWords", "sentenceLengthVariation", "lexicalDiversity", "averageParagraphWords", "sectionCount", "overlap", "dossierStatus", "dossier", "dossierModel", "dossierStartedAt", "dossierCompletedAt", "dossierDurationSeconds", "dossierError", "dossierRetryDiagnostics", "dossierRuns", "chapterMapStatus")})
            if len(metadata) == int(manifest.get("count") or 0):
                return {"saved": True, "count": len(metadata), "relativePath": "chunks/", "format": "bookinator-chunk-v1", "signature": manifest.get("signature"), "chunks": metadata}
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        pass
    if page_texts is None:
        page_texts = native_manuscript_pages(book)
        preserve_source = bool(page_texts)
    if not page_texts:
        manuscript = BOOKS_ROOT / str(book.get("manuscriptId")) / "manuscript.pdf"
        page_texts = []
        try:
            import pymupdf  # type: ignore[import-not-found]
            with pymupdf.open(manuscript) as document:
                page_texts = [pdf_blocks_to_paragraph_text([page.get_text("blocks")]) for page in document]
        except (OSError, ImportError):
            pass
    chunks = page_bounded_chunks(chapters, page_texts, preserve_source=bool(preserve_source))
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
        metadata.append({key: artifact.get(key) for key in ("id", "sequence", "chapterSequence", "chapterLabel", "chapterTitle", "chunkInChapter", "pageStart", "pageEnd", "sourcePagination", "inputCharacters", "characterCount", "wordCount", "paragraphCount", "lineCount", "sentenceCount", "averageSentenceWords", "sentenceLengthVariation", "lexicalDiversity", "averageParagraphWords", "sectionCount", "overlap", "dossierStatus", "dossier", "dossierModel", "dossierStartedAt", "dossierCompletedAt", "dossierDurationSeconds", "dossierError", "dossierRetryDiagnostics", "dossierRuns", "chapterMapStatus")})
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
    pipeline.update({"status": "running", "phase": "extraction", "message": "Extracting manuscript text with source provenance.", "workerPid": os.getpid(), "startedAt": utc_now(), "updatedAt": utc_now()})
    for key in ("error", "completedAt", "stopRequested"):
        pipeline.pop(key, None)
    stages = {stage["id"]: stage for stage in pipeline.get("stages", [])}
    pipeline["chapters"] = []
    pipeline["chunks"] = []
    pipeline.pop("chapterArchive", None)
    pipeline.pop("chunkArchive", None)
    pipeline.pop("chapterMapWarnings", None)
    pipeline["chapterMapSuspicious"] = False
    # A durable prepare request can survive a server restart. Re-extraction is
    # not, by itself, a human decision to revoke an accepted structure. Carry
    # the approval through the rebuild and restore it only when the rebuilt map
    # is clean; genuine boundary edits and new warnings still invalidate it.
    begin_chapter_map_rebuild(pipeline)
    invalidate_pipeline_stage(
        pipeline, "extraction", include_self=True, status="pending",
        detail="Waiting for manuscript preparation.",
    )
    for stage_id in pipeline_stage_dependents("extraction") | {"extraction"}:
        if stage := stages.get(stage_id):
            stage.pop("model", None)
    active_stage_id = "extraction"
    stage_started = time.monotonic()
    try:
        stages["extraction"].update({"status": "running", "startedAt": utc_now()})
        write_pipeline(book, pipeline)
        page_texts = native_manuscript_pages(book)
        native_source = bool(page_texts)
        page_blocks: list[list[tuple[object, ...]]] = []
        if not native_source:
            manuscript = BOOKS_ROOT / str(book.get("manuscriptId")) / "manuscript.pdf"
            import pymupdf  # type: ignore[import-not-found]
            with pymupdf.open(manuscript) as document:
                page_blocks = [page.get_text("blocks") for page in document]
                page_texts = ["\n\n".join(str(block[4] or "") for block in sorted(blocks, key=lambda item: (item[1], item[0]))) for blocks in page_blocks]
        boundary_label = "source spans" if native_source else "pages with page boundaries"
        stages["extraction"].update({"status": "complete", "completedAt": utc_now(), "durationSeconds": round(time.monotonic() - stage_started, 3), "detail": f"Extracted {len(page_texts)} {boundary_label}."})
        active_stage_id = "structure"
        stage_started = time.monotonic()
        stages["structure"].update({"status": "running", "startedAt": utc_now()})
        pipeline.update({"phase": "chapter-map", "message": "Detecting chapter boundaries.", "updatedAt": utc_now()})
        write_pipeline(book, pipeline)
        accepted_variants = [str(label) for label in pipeline.get("acceptedChapterLabelVariants", [])]
        demoted_pages = [int(page) for page in pipeline.get("demotedChapterBoundaryPages", [])]
        fixed_pagination = source_has_fixed_pagination(book)
        source_format = str(manuscript_metadata(str(book.get("manuscriptId") or "")).get("sourceFormat") or "").casefold()
        chapters, method = detect_chapters(
            page_texts, accepted_variants, demoted_pages,
            fixed_pagination=fixed_pagination, allow_bare_numerals=source_format == "txt",
        )
        for chapter in chapters:
            chapter["sourcePagination"] = "fixed" if fixed_pagination else "reflowable"
            first_page = max(0, int(chapter.get("pageStart") or 1) - 1)
            last_page = min(len(page_texts), int(chapter.get("pageEnd") or first_page + 1))
            chapter["text"] = "\n\n".join(page_texts[first_page:last_page]).strip() if native_source else pdf_blocks_to_paragraph_text(page_blocks[first_page:last_page])
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
        stages["structure"].update({"status": "warning" if map_warnings else "complete", "completedAt": utc_now(), "durationSeconds": round(time.monotonic() - stage_started, 3), "detail": f"Detected {len(chapters)} sections using {method}." + (f" Review required: {'; '.join(map_warnings)}" if map_warnings else "")})
        visible_chapters = []
        for chapter in chapters:
            visible = {key: value for key, value in chapter.items() if key != "text"} | {"status": "pending"}
            visible_chapters.append(visible)
        pipeline["chapters"] = visible_chapters
        pipeline["chapterMapWarnings"] = map_warnings
        pipeline["chapterMapSuspicious"] = bool(map_warnings)
        map_approved = finalize_rebuilt_chapter_map_approval(pipeline, map_warnings)
        provisional_note = "accepted" if map_approved else "proposed" if map_warnings else "unapproved"
        if map_warnings:
            stages["summaries"].update({"status": "blocked", "detail": "Waiting for the anomalous chapter map to be resolved."})
            stages["dossiers"].update({"status": "blocked", "detail": "Waiting for the anomalous chapter map to be resolved."})
        else:
            stages["summaries"].update({"status": "pending", "detail": f"Ready to summarize {len(chapters)} chapters from the {provisional_note} map."})
            stages["dossiers"].update({"status": "pending", "detail": f"Source chunks from the {provisional_note} map are ready for fresh structured dossiers."})
        # Chapter detection is complete and the proposed map is stable. Publish
        # it before the derived archives are written so later bookkeeping is
        # never mislabeled as chapter-map work in the interface.
        pipeline.update({
            "status": "running", "phase": "chapter-archive",
            "message": "Saving the detected chapters as durable local objects.",
            "updatedAt": utc_now(),
        })
        write_pipeline(book, pipeline)
        active_stage_id = "chapter-archive"
        stage_started = time.monotonic()
        stages["chapter-archive"].update({"status": "running", "startedAt": utc_now()})
        extracted_chapters_path(book).write_text(json.dumps(chapters, ensure_ascii=False) + "\n", encoding="utf-8")
        archive = ensure_chapter_artifacts(book, chapters)
        stages["chapter-archive"].update({"status": "complete", "completedAt": utc_now(), "durationSeconds": round(time.monotonic() - stage_started, 3), "detail": f"Saved {archive['count']} ordered chapter objects locally for later analysis."})
        pipeline["chapterArchive"] = archive
        active_stage_id = "chunking"
        stage_started = time.monotonic()
        stages["chunking"].update({"status": "running", "startedAt": utc_now()})
        pipeline.update({
            "phase": "chunking", "message": "Creating source-linked processing chunks.",
            "updatedAt": utc_now(),
        })
        write_pipeline(book, pipeline)
        chunk_archive = ensure_chunk_artifacts(book, chapters, page_texts, preserve_source=native_source)
        stages["chunking"].update({"status": "complete", "completedAt": utc_now(), "durationSeconds": round(time.monotonic() - stage_started, 3), "detail": f"Saved {chunk_archive['count']} page-linked source chunks; structured dossiers are waiting."})
        pipeline["chunkArchive"] = {key: value for key, value in chunk_archive.items() if key != "chunks"}
        pipeline["chunks"] = chunk_archive.get("chunks", [])
        review_copy = " Resolve the reported anomalies before analysis continues." if map_warnings else " Review it when convenient."
        pipeline.update({
            "status": "review" if map_warnings else "ready",
            "phase": "chapter-map-approved" if map_approved else "chapter-map-proposed",
            "normalizationVersion": 2,
            "message": f"Rebuilt {len(chapters)} sections and preserved the editor’s approval." if map_approved else f"Found {len(chapters)} sections.{review_copy}",
            "updatedAt": utc_now(),
        })
        pipeline.pop("error", None)
        pipeline.pop("completedAt", None)
        pipeline.pop("stopRequested", None)
        write_pipeline(book, pipeline)
    except Exception as error:
        active_stage = stages.get(active_stage_id)
        if active_stage and active_stage.get("status") == "running":
            active_stage.update({
                "status": "failed", "completedAt": utc_now(),
                "durationSeconds": round(time.monotonic() - stage_started, 3),
                "error": str(error)[:800],
            })
        pipeline.update({"status": "failed", "message": "Manuscript preparation stopped.", "error": str(error)[:800], "updatedAt": utc_now()})
        write_pipeline(book, pipeline)
    finally:
        PIPELINE_THREADS.pop(book_id, None)
        PIPELINE_CANCEL_EVENTS.pop(book_id, None)


def reset_summary_run(book: dict[str, object], pipeline: dict[str, object]) -> dict[str, object]:
    archived_fields = ("model", "startedAt", "completedAt", "durationSeconds", "inputCharacters", "status")
    generated_fields = ("summary", "keyPoints", "endingState", "newQuestions", "questionDetails", "promptVersion", "analysisMode", "error", "model", "startedAt", "completedAt", "durationSeconds", "inputCharacters")
    for chapter in pipeline.get("chapters", []):
        if chapter.get("model") or chapter.get("completedAt"):
            history = chapter.setdefault("summaryRuns", [])
            history.append({key: chapter.get(key) for key in archived_fields if chapter.get(key) is not None})
        for key in generated_fields:
            chapter.pop(key, None)
        chapter["status"] = "pending"
    previous_rollup = pipeline.get("wholeBookSummary") if isinstance(pipeline.get("wholeBookSummary"), dict) else {}
    if previous_rollup.get("completedAt"):
        pipeline.setdefault("wholeBookSummaryRuns", []).append(dict(previous_rollup))
    pipeline["wholeBookSummary"] = {
        "status": "blocked",
        "dependsOn": list(PIPELINE_STAGE_DEPENDENCIES["whole-book-summary"]),
        "detail": "Waiting for the reset chapter summaries.",
    }
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
    previous_rollup = pipeline.get("wholeBookDossier") if isinstance(pipeline.get("wholeBookDossier"), dict) else {}
    if previous_rollup.get("completedAt"):
        pipeline.setdefault("wholeBookDossierRuns", []).append(dict(previous_rollup))
    pipeline["wholeBookDossier"] = {
        "status": "blocked",
        "dependsOn": list(PIPELINE_STAGE_DEPENDENCIES["whole-book-dossier"]),
        "detail": "Waiting for the reset chunk dossiers.",
    }
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


def reset_analysis_after_sequence(
    book: dict[str, object], pipeline: dict[str, object], sequence: int, label: str,
) -> dict[str, object]:
    """Clear derived work after one chapter and cap the development queue there."""
    if sequence < 1:
        raise ValueError("Choose a valid development boundary.")
    summary_fields = (
        "summary", "keyPoints", "endingState", "newQuestions", "questionDetails", "promptVersion",
        "analysisMode", "error", "model", "startedAt", "completedAt",
        "durationSeconds", "inputCharacters", "summaryRuns", "chapterReadingStatus",
        "chapterReadingStartedAt", "chapterReadingCompletedAt", "chapterReadingDurationSeconds",
        "chapterReadingPrimaryDurationSeconds", "chapterReadingModel", "chapterReadingInputSignature",
        "chapterReadingPromptVersion",
    )
    optional_fields = {
        "context": (
            "contextSummary", "contextModel", "contextStartedAt", "contextCompletedAt",
            "contextDurationSeconds", "contextInputSignature", "contextRebased",
            "contextError", "contextRuns",
        ),
        "llmReview": (
            "llmReview", "llmReviewModel", "llmReviewStartedAt", "llmReviewCompletedAt",
            "llmReviewDurationSeconds", "llmReviewInputSignature", "llmReviewError",
            "llmReviewRuns", "llmReviewSharedDurationSeconds",
        ),
    }
    for chapter in pipeline.get("chapters", []):
        chapter_sequence = int(chapter.get("sequence") or chapter.get("number") or 0)
        if chapter_sequence <= sequence:
            continue
        for key in (
            "glinerStatus", "glinerModel", "glinerStartedAt", "glinerCompletedAt",
            "glinerDurationSeconds", "glinerInputCharacters", "glinerCandidateCount", "glinerError",
        ):
            chapter.pop(key, None)
        chapter["glinerStatus"] = "pending"
        gliner_signals_path(book, chapter_sequence).unlink(missing_ok=True)
        for key in summary_fields:
            chapter.pop(key, None)
        chapter["status"] = "pending"
        for kind in ("emotion", "tag", "smell"):
            for key in (
                kind, f"{kind}Model", f"{kind}StartedAt", f"{kind}CompletedAt",
                f"{kind}DurationSeconds", f"{kind}InputCharacters", f"{kind}Error",
                f"{kind}Runs",
            ):
                chapter.pop(key, None)
            chapter[f"{kind}Status"] = "pending"
        for prefix, fields in optional_fields.items():
            for key in fields:
                chapter.pop(key, None)
            chapter[f"{prefix}Status"] = "pending"
        for path in (
            cumulative_context_path(book, chapter_sequence),
            llm_review_packet_path(book, chapter_sequence),
            llm_review_result_path(book, chapter_sequence),
            chapter_reading_path(book, chapter_sequence),
        ):
            path.unlink(missing_ok=True)

    dossier_fields = (
        "dossier", "dossierModel", "dossierStartedAt", "dossierCompletedAt",
        "dossierDurationSeconds", "dossierError", "dossierRetryDiagnostics", "dossierRuns",
        "dossierCoveredByChapterReading", "chapterReadingDurationSeconds", "chapterReadingInputSignature",
    )
    for chunk in pipeline.get("chunks", []):
        if int(chunk.get("chapterSequence") or 0) <= sequence:
            continue
        for key in dossier_fields:
            chunk.pop(key, None)
        chunk["dossierStatus"] = "pending"
        artifact_path = chunk_artifacts_path(book) / f"{int(chunk.get('sequence') or 0):04d}.json"
        artifact = read_json_artifact(artifact_path)
        if artifact:
            for key in dossier_fields:
                artifact.pop(key, None)
            artifact["dossierStatus"] = "pending"
            write_chunk_artifact(book, int(chunk.get("sequence") or 0), artifact)

    detail = f"Development boundary at {label}; later results were cleared deliberately."
    for stage_id in ("gliner-signals", "summaries", "dossiers", "emotions", "tags", "smells", "cumulative-context", "llm-review", "whole-book-llm-review"):
        stage = next((item for item in pipeline.get("stages", []) if item.get("id") == stage_id), None)
        if stage:
            stage.update({"status": "pending", "detail": detail})
            for key in ("startedAt", "completedAt", "durationSeconds", "error"):
                stage.pop(key, None)
    pipeline["wholeBookSummary"] = {"status": "blocked", "dependsOn": ["summaries"], "detail": detail}
    pipeline["wholeBookDossier"] = {"status": "blocked", "dependsOn": ["dossiers"], "detail": detail}
    pipeline["questionTracker"] = {"status": "blocked", "dependsOn": ["summaries", "dossiers"], "detail": detail, "items": []}
    pipeline["wholeBookLlmReview"] = {"status": "blocked", "dependsOn": ["llm-review"], "detail": detail}
    pipeline.update({
        "developmentAnalysisLimit": sequence,
        "developmentAnalysisLimitLabel": label,
        "developmentCheckpointLocked": False,
        "status": "ready", "phase": "ready",
        "message": f"Development run is capped at {label}. Later analysis is cleared and held.",
        "updatedAt": utc_now(),
    })
    for key in ("queuedAction", "completedAt", "stopRequested", "error"):
        pipeline.pop(key, None)
    pipeline.pop("developmentAnalysisLabel", None)  # Legacy field; the limit label is authoritative.
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
    elif kind == "whole-llm-review":
        previous = pipeline.get("wholeBookLlmReview") if isinstance(pipeline.get("wholeBookLlmReview"), dict) else {}
        was_running = previous.get("status") == "running"
        history = list(pipeline.get("wholeBookLlmReviewRuns") or [])
        if previous.get("completedAt"):
            history.append(previous)
        pipeline["wholeBookLlmReviewRuns"] = history
        pipeline["wholeBookLlmReview"] = {
            "status": "ready",
            "dependsOn": ["llm-review"],
            "detail": "A fresh whole-book LLM Review is queued.",
        }
        stage = next((item for item in pipeline.get("stages", []) if item.get("id") == "whole-book-llm-review"), None)
        if stage:
            stage.update({"status": "pending", "detail": pipeline["wholeBookLlmReview"]["detail"]})
            for key in ("model", "startedAt", "completedAt", "durationSeconds", "error"):
                stage.pop(key, None)
        action = "whole-llm-review"
    elif kind == "gliner":
        chapter = next((item for item in pipeline.get("chapters", []) if int(item.get("sequence") or item.get("number") or 0) == sequence), None)
        if not chapter:
            raise LookupError("Chapter not found.")
        was_running = chapter.get("glinerStatus") == "running"
        for key in (
            "glinerModel", "glinerStartedAt", "glinerCompletedAt", "glinerDurationSeconds",
            "glinerInputCharacters", "glinerCandidateCount", "glinerError",
        ):
            chapter.pop(key, None)
        chapter["glinerStatus"] = "pending"
        gliner_signals_path(book, sequence).unlink(missing_ok=True)
        invalidate_pipeline_stage(
            pipeline, "gliner-signals", include_self=True, status="pending",
            detail=f"Chapter {sequence} is waiting for fresh GLiNER signals.",
        )
        # Chapter Reading consumes these candidates, so a refreshed signal set
        # deliberately invalidates its combined downstream views.
        if chapter.get("chapterReadingStatus") == "complete":
            for key in (
                "summary", "keyPoints", "endingState", "newQuestions", "questionDetails",
                "promptVersion", "analysisMode", "error", "model", "startedAt", "completedAt",
                "durationSeconds", "inputCharacters", "chapterReadingStartedAt",
                "chapterReadingCompletedAt", "chapterReadingDurationSeconds",
                "chapterReadingPrimaryDurationSeconds", "chapterReadingModel",
                "chapterReadingInputSignature", "chapterReadingPromptVersion",
            ):
                chapter.pop(key, None)
            chapter.update({"status": "pending", "chapterReadingStatus": "pending"})
            chapter_reading_path(book, sequence).unlink(missing_ok=True)
            for chunk in pipeline.get("chunks", []):
                if int(chunk.get("chapterSequence") or 0) != sequence:
                    continue
                for key in (
                    "dossier", "dossierModel", "dossierStartedAt", "dossierCompletedAt",
                    "dossierDurationSeconds", "dossierError", "dossierRetryDiagnostics",
                    "dossierCoveredByChapterReading", "chapterReadingDurationSeconds",
                    "chapterReadingInputSignature",
                ):
                    chunk.pop(key, None)
                chunk["dossierStatus"] = "pending"
        action = "gliner-signals"
    elif kind == "summary":
        chapter = next((item for item in pipeline.get("chapters", []) if int(item.get("sequence") or item.get("number") or 0) == sequence), None)
        if not chapter:
            raise LookupError("Chapter not found.")
        was_running = chapter.get("status") == "running"
        if chapter.get("model") or chapter.get("completedAt"):
            chapter.setdefault("summaryRuns", []).append({key: chapter.get(key) for key in ("model", "startedAt", "completedAt", "durationSeconds", "inputCharacters", "status", "error") if chapter.get(key) is not None})
        for key in ("summary", "keyPoints", "endingState", "newQuestions", "questionDetails", "promptVersion", "analysisMode", "error", "model", "startedAt", "completedAt", "durationSeconds", "inputCharacters"):
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
    elif kind in {"context", "llm-review"}:
        authored_chapters = [
            item for item in pipeline.get("chapters", [])
            if strip_markdown_heading(item.get("title")).casefold() != "front matter"
        ]
        target_index = next((
            index for index, item in enumerate(authored_chapters)
            if int(item.get("sequence") or item.get("number") or 0) == sequence
        ), None)
        if target_index is None:
            raise LookupError("Chapter not found.")

        def archive_optional_run(chapter: dict[str, object], prefix: str, result_key: str) -> None:
            if not (chapter.get(f"{prefix}Model") or chapter.get(f"{prefix}CompletedAt") or chapter.get(result_key)):
                return
            chapter.setdefault(f"{prefix}Runs", []).append({
                key: chapter.get(key)
                for key in (
                    f"{prefix}Model", f"{prefix}StartedAt", f"{prefix}CompletedAt",
                    f"{prefix}DurationSeconds", f"{prefix}InputSignature", f"{prefix}Status",
                    f"{prefix}Error",
                )
                if chapter.get(key) is not None
            })

        def reset_optional_artifact(path: Path, schema: str) -> None:
            previous = read_json_artifact(path)
            previous_runs = list(previous.get("previousRuns") or []) if isinstance(previous.get("previousRuns"), list) else []
            if previous.get("status") == "complete":
                previous_runs.append({
                    key: previous.get(key)
                    for key in ("schema", "model", "startedAt", "completedAt", "durationSeconds", "inputSignature")
                    if previous.get(key) is not None
                })
            write_json_artifact(path, {"schema": schema, "status": "pending", "previousRuns": previous_runs})

        target_chapter = authored_chapters[target_index]
        if kind == "llm-review":
            was_running = target_chapter.get("llmReviewStatus") == "running"
            archive_optional_run(target_chapter, "llmReview", "llmReview")
            for key in (
                "llmReview", "llmReviewModel", "llmReviewStartedAt", "llmReviewCompletedAt",
                "llmReviewDurationSeconds", "llmReviewInputSignature", "llmReviewError",
            ):
                target_chapter.pop(key, None)
            target_chapter["llmReviewStatus"] = "pending"
            reset_optional_artifact(llm_review_result_path(book, sequence), LLM_REVIEW_PROMPT_VERSION)
            stage_id = "llm-review"
            action = "llm-review"
            detail = f"Chapter {sequence} is waiting for a fresh LLM Review."
        else:
            was_running = any(item.get("contextStatus") == "running" for item in authored_chapters[target_index:])
            for chapter in authored_chapters[target_index:]:
                chapter_sequence = int(chapter.get("sequence") or chapter.get("number") or 0)
                archive_optional_run(chapter, "context", "contextSummary")
                for key in (
                    "contextSummary", "contextModel", "contextStartedAt", "contextCompletedAt",
                    "contextDurationSeconds", "contextInputSignature", "contextRebased", "contextError",
                ):
                    chapter.pop(key, None)
                chapter["contextStatus"] = "pending"
                reset_optional_artifact(cumulative_context_path(book, chapter_sequence), CUMULATIVE_CONTEXT_PROMPT_VERSION)
            # Review N reads Context N-1. Rebuilding Context N therefore makes
            # Review N+1 and every later review stale, while Review N remains valid.
            for chapter in authored_chapters[target_index + 1:]:
                chapter_sequence = int(chapter.get("sequence") or chapter.get("number") or 0)
                archive_optional_run(chapter, "llmReview", "llmReview")
                for key in (
                    "llmReview", "llmReviewModel", "llmReviewStartedAt", "llmReviewCompletedAt",
                    "llmReviewDurationSeconds", "llmReviewInputSignature", "llmReviewError",
                ):
                    chapter.pop(key, None)
                chapter["llmReviewStatus"] = "pending"
                reset_optional_artifact(llm_review_result_path(book, chapter_sequence), LLM_REVIEW_PROMPT_VERSION)
            review_stage = next((item for item in pipeline.get("stages", []) if item.get("id") == "llm-review"), None)
            if review_stage and target_index + 1 < len(authored_chapters):
                review_stage.update({"status": "pending", "detail": f"Reviews after chapter {sequence} are waiting for rebuilt context."})
                for key in ("startedAt", "completedAt", "durationSeconds", "error"):
                    review_stage.pop(key, None)
            stage_id = "cumulative-context"
            action = "cumulative-context"
            detail = f"Context {sequence} and its dependent checkpoints are waiting for a fresh pass."

        stage = next((item for item in pipeline.get("stages", []) if item.get("id") == stage_id), None)
        if stage:
            stage.update({"status": "pending", "detail": detail})
            for key in ("startedAt", "completedAt", "durationSeconds", "error"):
                stage.pop(key, None)
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
    target = "the whole book" if kind in {"whole-summary", "whole-llm-review"} else f"dossier chunk {sequence}" if kind == "dossier" else f"chapter {sequence}"
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
        if chapter.get("glinerStatus") == "failed":
            for key in (
                "glinerModel", "glinerStartedAt", "glinerCompletedAt", "glinerDurationSeconds",
                "glinerInputCharacters", "glinerCandidateCount", "glinerError",
            ):
                chapter.pop(key, None)
            chapter["glinerStatus"] = "pending"
            gliner_signals_path(book, int(chapter.get("sequence") or chapter.get("number") or 0)).unlink(missing_ok=True)
            retried += 1
            affected_stages.add("gliner-signals")
        if chapter.get("status") == "failed":
            if chapter.get("model") or chapter.get("completedAt") or chapter.get("error"):
                chapter.setdefault("summaryRuns", []).append({
                    key: chapter.get(key)
                    for key in ("model", "startedAt", "completedAt", "durationSeconds", "inputCharacters", "status", "error")
                    if chapter.get(key) is not None
                })
            for key in ("summary", "keyPoints", "endingState", "newQuestions", "questionDetails", "promptVersion", "analysisMode", "error", "model", "startedAt", "completedAt", "durationSeconds", "inputCharacters"):
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

    whole_review = pipeline.get("wholeBookLlmReview")
    if isinstance(whole_review, dict) and whole_review.get("status") == "failed":
        pipeline.setdefault("wholeBookLlmReviewRuns", []).append(dict(whole_review))
        pipeline["wholeBookLlmReview"] = {
            "status": "ready",
            "dependsOn": ["llm-review"],
            "detail": "A fresh whole-book LLM Review is queued.",
        }
        retried += 1
        affected_stages.add("whole-book-llm-review")

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


def run_gliner_signal_pipeline(book_id: str, chapter_sequence: int | None = None) -> None:
    """Run the fast, source-anchored GLiNER pass as its own inspectable task."""
    book = find_book(book_id)
    if not book:
        return
    pipeline = load_pipeline(book)
    ensure_signal_stages(pipeline)
    stages = {stage["id"]: stage for stage in pipeline.get("stages", [])}
    stage = stages.get("gliner-signals")
    if not stage:
        return
    runtime = ROOT / ".venv-gliner" / "bin" / "python"
    runner = ROOT / "tools" / "gliner_chapter_spike.py"
    if not runtime.is_file() or not runner.is_file():
        detail = "Install the isolated GLiNER runtime before running chapter signals."
        stage.update({"status": "blocked", "detail": detail, "setupRequired": True})
        pipeline.update({"status": "blocked", "phase": "gliner-signals-blocked", "message": detail, "updatedAt": utc_now()})
        write_pipeline(book, pipeline)
        return
    cancel_event = PIPELINE_CANCEL_EVENTS.setdefault(book_id, threading.Event())
    eligible = [
        chapter for chapter in development_limited_items(pipeline, pipeline.get("chapters", []), "sequence")
        if not is_front_matter(chapter)
    ]
    for chapter in pipeline.get("chapters", []):
        if is_front_matter(chapter):
            chapter["glinerStatus"] = "excluded"
    stage.update({
        "status": "running", "startedAt": stage.get("startedAt") or utc_now(),
        "model": GLINER_MODEL_ID, "detail": "Extracting exact entity and classification candidates with GLiNER.",
    })
    pipeline.update({"status": "running", "phase": "gliner-signals", "workerPid": os.getpid(), "updatedAt": utc_now()})
    write_pipeline(book, pipeline)
    try:
        for position, chapter in enumerate(eligible, 1):
            sequence = int(chapter.get("sequence") or chapter.get("number") or 0)
            if chapter_sequence is not None and sequence != chapter_sequence:
                continue
            if chapter.get("glinerStatus") == "complete":
                continue
            if cancel_event.is_set():
                raise PipelineCancelled()
            source = load_chapter_source(book, sequence)
            text = str(source.get("text") or "")
            started_at, started = utc_now(), time.monotonic()
            chapter.update({
                "glinerStatus": "running", "glinerModel": GLINER_MODEL_ID,
                "glinerStartedAt": started_at, "glinerInputCharacters": len(text),
            })
            pipeline.update({"message": f"Extracting GLiNER signals for {chapter.get('title')} · chapter {position} of {len(eligible)}.", "updatedAt": utc_now()})
            write_pipeline(book, pipeline)
            output_path = gliner_signals_path(book, sequence)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            input_path = output_path.with_suffix(".source.txt")
            input_path.write_text(text, encoding="utf-8")
            try:
                completed = subprocess.run(
                    [str(runtime), str(runner), str(input_path), "--model", GLINER_MODEL_ID,
                     "--output", str(output_path), "--skip-events"],
                    cwd=ROOT, capture_output=True, text=True, timeout=600, check=False,
                )
                if cancel_event.is_set():
                    raise PipelineCancelled()
                if completed.returncode:
                    raise RuntimeError((completed.stderr or completed.stdout or "GLiNER failed without diagnostics.")[-1000:])
                artifact = read_json_artifact(output_path)
                artifact.update({
                    "schema": GLINER_SCHEMA_VERSION, "status": "complete",
                    "chapterSequence": sequence, "startedAt": started_at, "completedAt": utc_now(),
                    "durationSeconds": round(time.monotonic() - started, 3),
                    "input": {"chapter": {key: source.get(key) for key in ("sequence", "title", "chapterTitle")}, "text": text},
                })
                artifact["identityCandidates"] = gliner_identity_candidates(artifact, text)
                write_json_artifact(output_path, artifact)
                chapter.update({
                    "glinerStatus": "complete", "glinerCompletedAt": artifact["completedAt"],
                    "glinerDurationSeconds": artifact["durationSeconds"],
                    "glinerCandidateCount": len(artifact["identityCandidates"]),
                })
                chapter.pop("glinerError", None)
            finally:
                input_path.unlink(missing_ok=True)
            write_pipeline(book, pipeline)
        completed_count = sum(chapter.get("glinerStatus") == "complete" for chapter in eligible)
        failed_count = sum(chapter.get("glinerStatus") == "failed" for chapter in eligible)
        remaining = len(eligible) - completed_count - failed_count
        stage.update({
            "status": "pending" if remaining else "warning" if failed_count else "complete",
            "detail": f"Completed {completed_count} of {len(eligible)} manuscript chapter GLiNER signal sets; front matter excluded.",
        })
        if not remaining:
            stage["completedAt"] = utc_now()
        pipeline.update({"status": "running" if chapter_sequence is not None and remaining else "complete", "phase": "chapter-complete", "message": "GLiNER signals saved; continuing through this book.", "updatedAt": utc_now()})
    except PipelineCancelled:
        for chapter in eligible:
            if chapter.get("glinerStatus") == "running":
                chapter["glinerStatus"] = "pending"
        stage.update({"status": "paused", "detail": "GLiNER signals stopped safely."})
        pipeline.update({"status": "paused", "phase": "gliner-signals-paused", "message": "GLiNER signals stopped; completed results are safe.", "updatedAt": utc_now()})
    except Exception as error:
        active = next((chapter for chapter in eligible if chapter.get("glinerStatus") == "running"), None)
        if active:
            active.update({"glinerStatus": "failed", "glinerCompletedAt": utc_now(), "glinerError": str(error)[:500]})
        stage.update({"status": "warning", "detail": "One or more GLiNER signal sets failed."})
        pipeline.update({"status": "warning", "phase": "chapter-complete", "message": "GLiNER signals need attention.", "updatedAt": utc_now()})
    finally:
        write_pipeline(book, pipeline)
        PIPELINE_THREADS.pop(book_id, None)
        PIPELINE_CANCEL_EVENTS.pop(book_id, None)


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
            preferred = configured_primary_model(settings)
            model = preferred if preferred in models else effective_primary_model(models, settings)
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
        visible_by_sequence = {
            int(chapter.get("sequence") or chapter.get("number") or 0): chapter
            for chapter in pipeline.get("chapters", [])
            if isinstance(chapter, dict)
        }
        for index, source in enumerate(chapters):
            sequence = int(source.get("sequence") or source.get("number") or index + 1)
            visible = visible_by_sequence.get(sequence)
            if visible is None:
                continue
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
    chapters = development_limited_items(pipeline, pipeline.get("chapters", []), "sequence")
    for index, chapter in enumerate(chapters, start=1):
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
        if higher_priority_book_waiting(book_id):
            return
        book = find_book(book_id)
        if not book:
            return
        action = stage_rollup_action(load_pipeline(book), paused_pipeline_actions(book_id))
        if action == "whole-summary":
            PIPELINE_CANCEL_EVENTS[book_id] = threading.Event()
            PIPELINE_THREADS[book_id] = threading.current_thread()
            run_whole_book_summary_pipeline(book_id)
            continue
        if action == "whole-dossier":
            PIPELINE_CANCEL_EVENTS[book_id] = threading.Event()
            PIPELINE_THREADS[book_id] = threading.current_thread()
            run_whole_book_dossier_pipeline(book_id)
            continue
        if action == "whole-llm-review":
            PIPELINE_CANCEL_EVENTS[book_id] = threading.Event()
            PIPELINE_THREADS[book_id] = threading.current_thread()
            run_whole_book_llm_review_pipeline(book_id)
            continue
        return


def run_book_chapter_pipeline(
    book_id: str, *, summaries: bool = True, emotions: bool = True,
    tags: bool = True, smells: bool = True, dossiers: bool = True,
    context: bool | None = None, llm_review: bool | None = None,
    gliner_signals: bool = True,
) -> None:
    """Finish one book chapter-by-chapter, respecting per-stage dependencies."""
    book = find_book(book_id)
    if not book:
        return
    initial_pipeline = load_pipeline(book)
    if initial_pipeline.get("chapterMapSuspicious") and not initial_pipeline.get("chapterMapApproved"):
        return
    # Legacy/synthetic ledgers used by repair tools may not declare this new
    # stage. Only run it when the migrated pipeline explicitly owns the step.
    gliner_signals = bool(gliner_signals and any(
        stage.get("id") == "gliner-signals" for stage in initial_pipeline.get("stages", [])
        if isinstance(stage, dict)
    ))
    optional_review = bool(book.get("llmReviewEnabled"))
    # Keep one cancellation identity for the entire chapter-first pass. Child
    # runners may remove the public registry entry when they return, but this
    # local event remains authoritative so Stop cannot cancel one elementary
    # stage only to have the outer worker create a fresh event and continue.
    book_cancel_event = BOOK_PIPELINE_CANCEL_EVENTS.get(book_id)
    if book_cancel_event is None or book_cancel_event.is_set():
        book_cancel_event = threading.Event()
        BOOK_PIPELINE_CANCEL_EVENTS[book_id] = book_cancel_event
    PIPELINE_CANCEL_EVENTS[book_id] = book_cancel_event
    context = optional_review if context is None else context
    llm_review = optional_review if llm_review is None else llm_review
    enabled_stages = {
        stage_id for stage_id, enabled in (("summaries", summaries), ("emotions", emotions), ("tags", tags), ("smells", smells), ("dossiers", dossiers)) if enabled
    }
    if gliner_signals:
        enabled_stages.add("gliner-signals")
    if context:
        enabled_stages.add("cumulative-context")
    if llm_review:
        enabled_stages.add("llm-review")
    if higher_priority_book_waiting(book_id):
        return
    run_ready_stage_rollups(book_id)

    def claim_stage_worker() -> None:
        PIPELINE_CANCEL_EVENTS[book_id] = book_cancel_event
        PIPELINE_THREADS[book_id] = threading.current_thread()

    for sequence in ordered_chapter_sequences(load_pipeline(book)):
        if QUEUE_CANCEL_EVENT.is_set() or book_cancel_event.is_set():
            return
        # The normal path reads a fresh chapter once, then projects that one
        # structured response into Summary, Dossier, and optional LLM Review.
        # The individual runners remain available as surgical repair actions
        # for one stale or failed view without spending another complete read.
        pipeline = load_pipeline(book)
        chapter = next((item for item in pipeline.get("chapters", []) if int(item.get("sequence") or item.get("number") or 0) == sequence), None)
        if (
            gliner_signals and chapter and not is_front_matter(chapter)
            and chapter.get("glinerStatus") in {None, "pending", "ready", "paused", "running"}
            and "gliner-signals" not in paused_pipeline_actions(book_id)
        ):
            claim_stage_worker()
            run_gliner_signal_pipeline(book_id, chapter_sequence=sequence)
            if QUEUE_CANCEL_EVENT.is_set() or book_cancel_event.is_set():
                return
            pipeline = load_pipeline(book)
            chapter = next((item for item in pipeline.get("chapters", []) if int(item.get("sequence") or item.get("number") or 0) == sequence), None)
            if chapter and chapter.get("glinerStatus") != "complete":
                return
        chapter_chunks = [item for item in pipeline.get("chunks", []) if int(item.get("chapterSequence") or 0) == sequence]
        summary_needs_read = bool(chapter and chapter.get("status") in {None, "pending", "ready", "paused", "running"})
        dossier_needs_read = bool(chapter_chunks and any(item.get("dossierStatus") in {None, "pending", "ready", "paused", "running"} for item in chapter_chunks))
        if summaries and dossiers and summary_needs_read and dossier_needs_read:
            if not ({"summarize", "dossiers"} & paused_pipeline_actions(book_id)):
                claim_stage_worker()
                run_chapter_reading_pipeline(
                    book_id, sequence,
                    include_review=bool(llm_review and "llm-review" not in paused_pipeline_actions(book_id)),
                )
                if QUEUE_CANCEL_EVENT.is_set() or book_cancel_event.is_set():
                    return
                if higher_priority_book_waiting(book_id):
                    return
                run_ready_stage_rollups(book_id)
        for stage_id in CHAPTER_PIPELINE_STAGE_ORDER:
            if QUEUE_CANCEL_EVENT.is_set() or book_cancel_event.is_set():
                return
            if stage_id not in enabled_stages:
                continue
            stage_action = {"summaries": "summarize", "dossiers": "dossiers"}.get(stage_id, stage_id)
            if stage_action in paused_pipeline_actions(book_id):
                continue
            pipeline = load_pipeline(book)
            stage = next((item for item in pipeline.get("stages", []) if item.get("id") == stage_id), {})
            if not stage and stage_id == "smells":
                continue
            if stage.get("disabled"):
                continue
            if stage.get("status") == "blocked" and stage.get("setupRequired"):
                continue
            if stage_id == "gliner-signals":
                chapter = next((item for item in pipeline.get("chapters", []) if int(item.get("sequence") or item.get("number") or 0) == sequence), None)
                if chapter and not is_front_matter(chapter) and chapter.get("glinerStatus") in {None, "pending", "ready", "paused", "running"}:
                    claim_stage_worker()
                    run_gliner_signal_pipeline(book_id, chapter_sequence=sequence)
            elif stage_id == "summaries":
                chapter = next((item for item in pipeline.get("chapters", []) if int(item.get("sequence") or item.get("number") or 0) == sequence), None)
                if chapter and chapter.get("status") in {None, "pending", "ready", "paused", "running"}:
                    claim_stage_worker()
                    run_summary_pipeline(book_id, chapter_sequence=sequence)
            elif stage_id == "dossiers":
                chapter_chunks = [chunk for chunk in pipeline.get("chunks", []) if int(chunk.get("chapterSequence") or 0) == sequence]
                if any(chunk.get("dossierStatus") in {None, "pending", "ready", "paused", "running"} for chunk in chapter_chunks):
                    claim_stage_worker()
                    run_dossier_pipeline(book_id, chapter_sequence=sequence)
            elif stage_id in {"emotions", "tags", "smells"}:
                prefix = "emotion" if stage_id == "emotions" else "tag" if stage_id == "tags" else "smell"
                chapter = next((item for item in pipeline.get("chapters", []) if int(item.get("sequence") or item.get("number") or 0) == sequence), None)
                if chapter and chapter.get(f"{prefix}Status") in {None, "pending", "ready", "paused", "running"}:
                    claim_stage_worker()
                    run_chapter_signal_pipeline(book_id, prefix, chapter_sequence=sequence)
            elif stage_id == "llm-review":
                chapter = next((item for item in pipeline.get("chapters", []) if int(item.get("sequence") or item.get("number") or 0) == sequence), None)
                if chapter and strip_markdown_heading(chapter.get("title")).casefold() != "front matter" and chapter.get("llmReviewStatus") in {None, "pending", "ready", "paused", "running"}:
                    claim_stage_worker()
                    run_llm_review_pipeline(book_id, chapter_sequence=sequence)
            elif stage_id == "cumulative-context":
                chapter = next((item for item in pipeline.get("chapters", []) if int(item.get("sequence") or item.get("number") or 0) == sequence), None)
                if chapter and strip_markdown_heading(chapter.get("title")).casefold() != "front matter" and chapter.get("contextStatus") in {None, "pending", "ready", "paused", "running"}:
                    claim_stage_worker()
                    run_cumulative_context_pipeline(book_id, chapter_sequence=sequence)
            if QUEUE_CANCEL_EVENT.is_set() or book_cancel_event.is_set():
                return
            # Priority is a scheduling contract. Finish the active model
            # response safely, then yield before another stage or rollup when a
            # higher-priority book has eligible work.
            if higher_priority_book_waiting(book_id):
                return
            run_ready_stage_rollups(book_id)
        # A user may refresh or prioritize a result while this worker is in a
        # long chapter pass. Finish the active chapter, then yield to the outer
        # queue so that explicit request runs next instead of waiting behind the
        # rest of the book.
        with QUEUE_LOCK:
            if book_id in QUEUE_ACTIONS:
                return
    run_ready_stage_rollups(book_id)
    pipeline = load_pipeline(book)
    if reconcile_development_checkpoint(book, pipeline):
        write_pipeline(book, pipeline)


def retain_book_for_automatic_followup(processed: set[str], book_id: str) -> str:
    """Keep a book at the front when a completed pass unlocks another pass."""
    book = find_book(book_id)
    action = next_pipeline_action(book, load_pipeline(book)) if book else ""
    if action:
        processed.discard(book_id)
    return action


def run_library_queue() -> None:
    global QUEUE_THREAD, QUEUE_CURRENT_TASK
    worker = threading.current_thread()
    processed: set[str] = set()
    try:
        while True:
            if QUEUE_CANCEL_EVENT.is_set():
                break
            queued = queue_ids_by_current_priority(load_queue())
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
            if action in paused_pipeline_actions(book_id):
                complete_queue_action(book_id, action)
                retain_book_for_automatic_followup(processed, book_id)
                continue
            if action == "deferred-refresh":
                with QUEUE_LOCK:
                    persisted_refreshes = load_deferred_analysis_refreshes()
                    requests = DEFERRED_ANALYSIS_REFRESHES.pop(book_id, []) or persisted_refreshes.pop(book_id, [])
                    save_deferred_analysis_refreshes(persisted_refreshes)
                for kind, sequence in requests:
                    owner_action, _ = refresh_analysis_result(book, load_pipeline(book), kind, sequence)
                    if owner_action in PAUSABLE_PIPELINE_ACTIONS:
                        set_pipeline_action_paused(book_id, owner_action, False)
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
                retain_book_for_automatic_followup(processed, book_id)
                continue
            if action == "restart":
                pipeline = reset_summary_run(book, pipeline)
                run_book_chapter_pipeline(book_id, summaries=True, dossiers=pipeline_is_enabled())
                complete_queue_action(book_id, action)
                retain_book_for_automatic_followup(processed, book_id)
                continue
            if action == "prepare":
                PIPELINE_CANCEL_EVENTS[book_id] = threading.Event()
                PIPELINE_THREADS[book_id] = threading.current_thread()
                prepare_manuscript_pipeline(book_id)
                prepared = load_pipeline(book)
                continue_analysis = bool(prepared.pop("continueAnalysisAfterPrepare", False) or pipeline_is_enabled())
                if continue_analysis:
                    write_pipeline(book, prepared)
                if continue_analysis and not QUEUE_CANCEL_EVENT.is_set() and prepared.get("chapters"):
                    run_book_chapter_pipeline(book_id)
                complete_queue_action(book_id, action)
                retain_book_for_automatic_followup(processed, book_id)
                continue
            if action == "summarize":
                run_book_chapter_pipeline(book_id, summaries=True, dossiers=pipeline_is_enabled())
                complete_queue_action(book_id, action)
                retain_book_for_automatic_followup(processed, book_id)
                continue
            if action == "whole-summary":
                PIPELINE_CANCEL_EVENTS[book_id] = threading.Event()
                PIPELINE_THREADS[book_id] = threading.current_thread()
                run_whole_book_summary_pipeline(book_id)
                run_ready_stage_rollups(book_id)
                complete_queue_action(book_id, action)
                retain_book_for_automatic_followup(processed, book_id)
                continue
            if action == "whole-dossier":
                PIPELINE_CANCEL_EVENTS[book_id] = threading.Event()
                PIPELINE_THREADS[book_id] = threading.current_thread()
                run_whole_book_dossier_pipeline(book_id)
                complete_queue_action(book_id, action)
                retain_book_for_automatic_followup(processed, book_id)
                continue
            if action == "questions":
                PIPELINE_CANCEL_EVENTS[book_id] = threading.Event()
                PIPELINE_THREADS[book_id] = threading.current_thread()
                run_question_tracker_pipeline(book_id)
                complete_queue_action(book_id, action)
                retain_book_for_automatic_followup(processed, book_id)
                continue
            if action == "gliner-signals":
                run_book_chapter_pipeline(
                    book_id, summaries=False, emotions=False, tags=False, smells=False,
                    dossiers=False, context=False, llm_review=False, gliner_signals=True,
                )
                complete_queue_action(book_id, action)
                retain_book_for_automatic_followup(processed, book_id)
                continue
            if action == "cumulative-context":
                run_book_chapter_pipeline(book_id, summaries=False, emotions=False, tags=False, smells=False, dossiers=False, context=True, llm_review=False)
                complete_queue_action(book_id, action)
                retain_book_for_automatic_followup(processed, book_id)
                continue
            if action == "llm-review":
                # Review N reads only Context N-1 plus canonical chapter N.
                # Running the paired optional stages chapter-first repairs any
                # missing predecessor checkpoint without exposing Context N to
                # the review of chapter N.
                run_book_chapter_pipeline(book_id, summaries=False, emotions=False, tags=False, smells=False, dossiers=False, context=True, llm_review=True)
                complete_queue_action(book_id, action)
                retain_book_for_automatic_followup(processed, book_id)
                continue
            if action == "whole-llm-review":
                PIPELINE_CANCEL_EVENTS[book_id] = threading.Event()
                PIPELINE_THREADS[book_id] = threading.current_thread()
                run_whole_book_llm_review_pipeline(book_id)
                complete_queue_action(book_id, action)
                retain_book_for_automatic_followup(processed, book_id)
                continue
            if action == "dossiers":
                run_book_chapter_pipeline(book_id, summaries=False, emotions=False, tags=False, smells=False, dossiers=True)
                complete_queue_action(book_id, action)
                retain_book_for_automatic_followup(processed, book_id)
                continue
            if action == "dossier-restart":
                pipeline = reset_dossier_run(book, pipeline)
                PIPELINE_CANCEL_EVENTS[book_id] = threading.Event()
                PIPELINE_THREADS[book_id] = threading.current_thread()
                run_dossier_pipeline(book_id)
                complete_queue_action(book_id, action)
                retain_book_for_automatic_followup(processed, book_id)
                continue
            if action in {"emotions", "emotion-restart", "tags", "tag-restart", "smells", "smell-restart"}:
                kind = "emotion" if action.startswith("emotion") else "tag" if action.startswith("tag") else "smell"
                if action.endswith("restart"):
                    pipeline = reset_chapter_signal_run(book, pipeline, kind)
                run_book_chapter_pipeline(book_id, summaries=False, emotions=kind == "emotion", tags=kind == "tag", smells=kind == "smell", dossiers=False)
                complete_queue_action(book_id, action)
                retain_book_for_automatic_followup(processed, book_id)
                continue
            automatic_action = next_pipeline_action(book, pipeline)
            with QUEUE_LOCK:
                QUEUE_CURRENT_TASK.update({"action": automatic_action or "chapter-pipeline", "task": {"prepare": "Manuscript map", "gliner-signals": "GLiNER signals", "summarize": "Chapter summary", "dossiers": "Chapter dossier", "emotions": "Emotion scoring", "tags": "Chapter tags", "smells": "Prose smells", "whole-summary": "Whole-book summary", "whole-dossier": "Whole-book dossier", "questions": "Questions & payoffs", "cumulative-context": "Cumulative context", "llm-review": "LLM Review", "whole-llm-review": "Whole-book LLM Review"}.get(automatic_action, "Next chapter-step")})
            if automatic_action == "prepare":
                PIPELINE_CANCEL_EVENTS[book_id] = threading.Event()
                PIPELINE_THREADS[book_id] = threading.current_thread()
                prepare_manuscript_pipeline(book_id)
                prepared = load_pipeline(book)
                if pipeline_is_enabled() and not QUEUE_CANCEL_EVENT.is_set() and prepared.get("chapters"):
                    run_book_chapter_pipeline(book_id)
                continue
            if automatic_action in {"gliner-signals", "summarize", "dossiers", "emotions", "tags", "smells", "cumulative-context", "llm-review"}:
                # Automatic work is chapter-first, not stage-first. Once the
                # structural inputs exist, run every eligible pass for one
                # chapter before advancing to the next chapter. Explicit UI
                # redo actions above remain deliberately stage-scoped.
                run_book_chapter_pipeline(book_id)
            elif automatic_action == "whole-summary":
                PIPELINE_CANCEL_EVENTS[book_id] = threading.Event()
                PIPELINE_THREADS[book_id] = threading.current_thread()
                run_whole_book_summary_pipeline(book_id)
            elif automatic_action == "whole-dossier":
                PIPELINE_CANCEL_EVENTS[book_id] = threading.Event()
                PIPELINE_THREADS[book_id] = threading.current_thread()
                run_whole_book_dossier_pipeline(book_id)
            elif automatic_action == "questions":
                PIPELINE_CANCEL_EVENTS[book_id] = threading.Event()
                PIPELINE_THREADS[book_id] = threading.current_thread()
                run_question_tracker_pipeline(book_id)
            elif automatic_action == "whole-llm-review":
                PIPELINE_CANCEL_EVENTS[book_id] = threading.Event()
                PIPELINE_THREADS[book_id] = threading.current_thread()
                run_whole_book_llm_review_pipeline(book_id)
            retain_book_for_automatic_followup(processed, book_id)
    finally:
        # A Continue request can arrive after this worker has chosen to exit but
        # before Thread.is_alive() turns false. Preserve that request and hand it
        # to a replacement worker instead of leaving the UI stuck at Starting.
        with QUEUE_LOCK:
            # A replacement worker may have been installed while this older
            # thread was finishing its final stage. Only the worker that still
            # owns the queue may clear or replace that shared identity.
            if QUEUE_THREAD is worker:
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


def stop_global_pipeline() -> None:
    """Request a safe stop and persist interrupted work as resumable."""
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
                for prefix in ("gliner", "emotion", "tag", "smell"):
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


def change_pipeline_project_priority(book_id: str, direction: str) -> dict[str, object]:
    book = find_book(book_id)
    if not book:
        raise ValueError("Choose a valid project.")
    levels = ["high", "normal", "low", "shelved"]
    current = normalize_book_priority(book.get("priority"))
    offset = -1 if direction == "raise" else 1
    priority = levels[max(0, min(len(levels) - 1, levels.index(current) + offset))]
    saved = save_book({**book, "priority": priority})
    if priority != "shelved" and pipeline_is_enabled():
        action = next_pipeline_action(saved, load_pipeline(saved))
        if action:
            prioritize_pipeline_action(book_id, action)
    return saved


class PipelineRevisionConflict(ValueError):
    def __init__(self, state: dict[str, object]):
        super().__init__("The pipeline changed. Review the refreshed queue and try again.")
        self.state = state


def require_pipeline_revision(intent: dict[str, object]) -> dict[str, object]:
    """Return the observed pipeline only when the caller still owns its revision."""
    current = global_pipeline_state(wake=False)
    expected_revision = intent.get("expectedRevision")
    if expected_revision is None or isinstance(expected_revision, bool):
        raise ValueError("A pipeline snapshot revision is required.")
    try:
        expected_revision = int(expected_revision)
    except (TypeError, ValueError):
        raise ValueError("A valid pipeline snapshot revision is required.") from None
    if expected_revision != current["snapshot"]["revision"]:
        raise PipelineRevisionConflict(current)
    return current


def apply_pipeline_control_intent(intent: dict[str, object]) -> dict[str, object]:
    """Apply one versioned Commons command against one observed revision."""
    if intent.get("schema") != PIPELINE_CONTROL_INTENT_SCHEMA:
        raise ValueError("Choose the supported pipeline control protocol.")
    action = str(intent.get("action") or "")
    supported = {"start", "stop", "move-top", "raise", "lower", "pause", "resume"}
    if action not in supported:
        raise ValueError("Choose a supported pipeline action.")
    raw_unit_ids = intent.get("unitIds", [])
    if not isinstance(raw_unit_ids, list) or any(not isinstance(unit_id, str) or not unit_id for unit_id in raw_unit_ids):
        raise ValueError("Pipeline unit ids must be non-empty strings.")
    unit_ids = list(dict.fromkeys(raw_unit_ids))
    current = require_pipeline_revision(intent)
    snapshot = current["snapshot"]

    units_by_id = {str(unit["id"]): unit for unit in snapshot["units"]}
    if action not in {"start", "stop"} and not unit_ids:
        raise ValueError("Select at least one pipeline unit.")
    unknown = [unit_id for unit_id in unit_ids if unit_id not in units_by_id]
    if unknown:
        raise ValueError("One or more selected pipeline units no longer exist.")
    selected = [units_by_id[unit_id] for unit_id in unit_ids]

    if action == "start":
        start_global_pipeline()
    elif action == "stop":
        stop_global_pipeline()
    elif action == "move-top":
        for unit in reversed(selected):
            product = unit.get("product", {})
            prioritize_pipeline_action(str(product.get("bookId") or unit["projectId"]), str(product.get("action") or unit.get("action") or ""))
    elif action in {"raise", "lower"}:
        for project_id in dict.fromkeys(str(unit["projectId"]) for unit in selected):
            change_pipeline_project_priority(project_id, action)
    elif action in {"pause", "resume"}:
        paused = action == "pause"
        for unit in selected:
            product = unit.get("product", {})
            book_id = str(product.get("bookId") or unit["projectId"])
            unit_action = str(product.get("action") or unit.get("action") or "")
            if unit.get("policy", {}).get("required") or unit_action not in PAUSABLE_PIPELINE_ACTIONS:
                continue
            set_pipeline_action_paused(book_id, unit_action, paused)
            if paused:
                with QUEUE_LOCK:
                    if QUEUE_ACTIONS.get(book_id) == unit_action:
                        QUEUE_ACTIONS.pop(book_id, None)
                    durable = load_queue_actions()
                    if durable.get(book_id) == unit_action:
                        durable.pop(book_id, None)
                        save_queue_actions(durable)
            else:
                save_queue([*load_queue(), book_id])
        if action == "resume" and pipeline_is_enabled():
            start_global_pipeline()
    return global_pipeline_state()


def apply_pipeline_product_command(intent: dict[str, object]) -> dict[str, object]:
    """Apply Bookinator-owned pipeline semantics behind the Commons revision boundary."""
    if intent.get("schema") != PIPELINE_PRODUCT_COMMAND_SCHEMA:
        raise ValueError("Choose the supported Bookinator pipeline command protocol.")
    require_pipeline_revision(intent)
    command = str(intent.get("command") or "")
    if command == "restart-current-run":
        library = load_library()
        pipeline_records = [
            (book, add_pipeline_progress(pipeline_for_client(str(book.get("id") or ""), load_pipeline(book))))
            for book in library
        ]
        sync_current_pipeline_run(pipeline_records, restart=True)
        return global_pipeline_state(library, pipeline_records)
    project_id = str(intent.get("projectId") or "")
    if command == "advance-development-checkpoint":
        book = find_book(project_id)
        if not book:
            raise ValueError("Choose a valid project.")
        pipeline = load_pipeline(book)
        try:
            current_limit = int(pipeline.get("developmentAnalysisLimit") or 0)
        except (TypeError, ValueError):
            current_limit = 0
        next_chapter = min(
            (
                chapter for chapter in pipeline.get("chapters", [])
                if int(chapter.get("sequence") or chapter.get("number") or 0) > current_limit
            ),
            key=lambda chapter: int(chapter.get("sequence") or chapter.get("number") or 0),
            default=None,
        )
        if current_limit < 1 or not next_chapter:
            raise ValueError("This project has no later development chapter to run.")
        sequence = int(next_chapter.get("sequence") or next_chapter.get("number") or 0)
        label = str(next_chapter.get("title") or f"section {sequence}")
        advance_development_checkpoint(pipeline, sequence, label)
        write_pipeline(book, pipeline)
        prioritize_pipeline_action(project_id, "chapter-pipeline")
        return global_pipeline_state()
    if not project_id or command not in EXPLICIT_QUEUE_ACTIONS:
        raise ValueError("Choose a valid project and Bookinator pipeline command.")
    prioritize_pipeline_action(project_id, command)
    return global_pipeline_state()


def prioritize_pipeline_action(book_id: str, action: str) -> dict[str, object]:
    """Durably put one book first and ensure the single local worker is awake."""
    global QUEUE_THREAD
    book = find_book(book_id)
    if not book or action not in EXPLICIT_QUEUE_ACTIONS:
        raise ValueError("Choose a valid book and pipeline action.")
    # An explicit Continue/Prioritize request is the authority to revoke a
    # prior per-book Stop and create a fresh chapter-pass cancellation token.
    BOOK_PIPELINE_CANCEL_EVENTS.pop(book_id, None)
    base_action = {"restart": "summarize", "dossier-restart": "dossiers", "emotion-restart": "emotions", "tag-restart": "tags", "smell-restart": "smells"}.get(action, action)
    if base_action in paused_pipeline_actions(book_id):
        set_pipeline_action_paused(book_id, base_action, False)
    pipeline = load_pipeline(book)
    if pipeline.get("developmentCheckpointLocked") or pipeline.get("phase") == "development-checkpoint":
        raise ValueError("Run the next bounded development chapter before issuing an ordinary pipeline command.")
    if action != "prepare" and pipeline.get("chapterMapSuspicious") and not pipeline.get("chapterMapApproved"):
        raise ValueError("Review and resolve this book’s chapter map before starting derived analysis.")
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
        preferred = configured_primary_model(settings)
        model = preferred if preferred in models else effective_primary_model(models, settings)
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
    settings = load_settings()
    available = ollama_status()
    models = available["models"] if available["running"] else []
    model = effective_primary_model(models, settings)
    started_at = utc_now()
    started = time.monotonic()
    dependencies = list(PIPELINE_STAGE_DEPENDENCIES["whole-book-summary"])
    input_signature = stage_rollup_input_signature(pipeline, "summary")
    reset_inactive_whole_book_runs(pipeline, "whole-summary")
    previous_result = latest_completed_rollup_result(pipeline, "wholeBookSummary", "wholeBookSummaryRuns")
    pipeline["wholeBookSummary"] = {
        "status": "running", "model": model, "startedAt": started_at, "inputSignature": input_signature,
        "dependsOn": dependencies, "detail": "Synthesizing every current chapter summary.",
        **({"previousResult": previous_result} if previous_result else {}),
    }
    write_pipeline(book, pipeline)
    try:
        if not model or not input_signature:
            raise ValueError("Complete every chapter summary and assign a chapter reader before refreshing this rollup.")
        synthesis = summarize_whole_book(pipeline, model, cancel_event, book_id)
        pipeline["wholeBookSummary"] = {**synthesis, "status": "complete", "model": model, "startedAt": started_at, "completedAt": utc_now(), "durationSeconds": round(time.monotonic() - started, 1), "inputSignature": input_signature, "dependsOn": dependencies, "detail": "Synthesized from every current chapter summary."}
    except PipelineCancelled:
        pipeline["wholeBookSummary"] = {
            "status": "ready", "model": model, "inputSignature": input_signature,
            "dependsOn": dependencies, "detail": "Stopped before whole-book summary synthesis finished.",
            **({"previousResult": previous_result} if previous_result else {}),
        }
    except Exception as error:
        pipeline["wholeBookSummary"] = {
            "status": "failed", "model": model, "startedAt": started_at, "completedAt": utc_now(),
            "durationSeconds": round(time.monotonic() - started, 1), "inputSignature": input_signature,
            "error": str(error)[:500], "dependsOn": dependencies,
            "detail": "Summary synthesis failed; chapter summaries remain safe.",
            **({"previousResult": previous_result} if previous_result else {}),
        }
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
    settings = load_settings()
    available = ollama_status()
    models = available["models"] if available["running"] else []
    model = effective_primary_model(models, settings)
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


def llm_review_input_signature(payload: object) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def chapter_dossier_payloads(pipeline: dict[str, object], sequence: int) -> list[dict[str, object]]:
    return [
        dict(chunk.get("dossier") or {})
        for chunk in pipeline.get("chunks", [])
        if int(chunk.get("chapterSequence") or 0) == sequence and chunk.get("dossierStatus") == "complete" and isinstance(chunk.get("dossier"), dict)
    ]


def context_thread_is_actionable(value: object) -> bool:
    """Reject bookkeeping questions that do not name a durable uncertainty."""
    thread = re.sub(r"\s+", " ", str(value or "")).strip()
    if not thread:
        return False
    return not any(re.match(pattern, thread, re.I) for pattern in (
        r"^what (?:event|events) (?:occurs?|occurred|happens?|happened)(?: at the end of| in) (?:the )?chapter\??$",
        r"^what happens next\??$",
        r"^what does this mean\??$",
        r"^what will happen\??$",
    ))


def cumulative_context_schema() -> dict[str, object]:
    strings = {"type": "array", "items": {"type": "string"}}
    thread_update = {
        "type": "object",
        "properties": {
            "previous_thread": {"type": "string", "minLength": 1},
            "status": {"type": "string", "enum": ["open", "resolved", "retired"]},
            "current_wording": {"type": "string", "minLength": 1},
        },
        "required": ["previous_thread", "status", "current_wording"],
    }
    return {
        "type": "object",
        "properties": {
            "story_so_far": {"type": "string", "minLength": 1},
            "key_events": strings,
            "established_facts": strings,
            "entities_and_significance": strings,
            "character_states": strings,
            "relationship_states": strings,
            "knowledge_states": strings,
            "locations_and_timeline": strings,
            "open_threads": strings,
            "resolved_threads": strings,
            "retired_threads": strings,
            "thread_updates": {"type": "array", "items": thread_update},
            "reader_promises": strings,
            "themes_and_motifs": strings,
            "voice_and_form": strings,
        },
        "required": ["story_so_far", "key_events", "established_facts", "entities_and_significance", "character_states", "relationship_states", "knowledge_states", "locations_and_timeline", "open_threads", "resolved_threads", "retired_threads", "thread_updates", "reader_promises", "themes_and_motifs", "voice_and_form"],
    }


def build_cumulative_context(
    *, previous: dict[str, object], evidence: list[dict[str, object]], through_chapter: object,
    model: str, rebased: bool, cancel_event: threading.Event, run_key: str,
) -> dict[str, object]:
    """Build cumulative memory by indexing evidence, never by rewriting it.

    `previous`, `model`, `rebased`, `cancel_event`, and `run_key` remain in the
    signature so saved jobs and focused tests can cross the architecture change
    without a second control path. The ledger is rebuilt from the supplied
    chapter evidence; this is cheap enough to be deterministic and complete.
    """
    del previous, model, rebased, cancel_event, run_key
    through_label = f"Chapter {through_chapter}" if isinstance(through_chapter, int) else str(through_chapter)
    latest_index = max(0, len(evidence) - 1)
    records_by_key: dict[tuple[str, str], dict[str, object]] = {}
    chapter_digests: list[dict[str, object]] = []
    retired_threads: list[str] = []

    def remember(
        kind: str, claim: object, chapter: dict[str, object], *, subject: object = "",
        evidence_text: object = "", evidence_anchor: object = None, status: str = "active",
    ) -> None:
        value = re.sub(r"\s+", " ", str(claim or "")).strip()
        if not value:
            return
        if kind == "open_thread" and not context_thread_is_actionable(value):
            if value not in retired_threads:
                retired_threads.append(value)
            return
        key = (kind, normalize_lexical_key(value))
        chapter_index = int(chapter.get("ledgerIndex") or 0)
        chapter_label = str(chapter.get("chapter") or f"Section {chapter_index + 1}")
        source_sequence = int(chapter.get("sourceSequence") or 0)
        provenance = {
            "chapter": chapter_label,
            "sourceSequence": source_sequence,
            "evidence": str(evidence_text or "").strip(),
        }
        if isinstance(evidence_anchor, dict):
            provenance["evidenceAnchor"] = dict(evidence_anchor)
        existing = records_by_key.get(key)
        if existing:
            existing.update({
                "lastConfirmedChapter": chapter_label,
                "lastConfirmedSequence": source_sequence,
                "chaptersAgo": latest_index - chapter_index,
            })
            if provenance not in existing["provenance"]:
                existing["provenance"].append(provenance)
            return
        record_id = hashlib.sha256(f"{kind}:{key[1]}".encode("utf-8")).hexdigest()[:16]
        records_by_key[key] = {
            "id": record_id,
            "kind": kind,
            "claim": value,
            "subject": str(subject or "").strip(),
            "status": status,
            "introducedChapter": chapter_label,
            "introducedSequence": source_sequence,
            "lastConfirmedChapter": chapter_label,
            "lastConfirmedSequence": source_sequence,
            "chaptersAgo": latest_index - chapter_index,
            "provenance": [provenance],
        }

    dossier_kind_map = {
        "facts": "fact", "events": "event", "entities": "entity", "locations": "location",
        "current_times": "current_time", "promises": "reader_promise", "timeline_observations": "timeline",
    }
    for chapter_index, raw_chapter in enumerate(evidence):
        chapter = {**raw_chapter, "ledgerIndex": chapter_index}
        chapter_label = str(chapter.get("chapter") or f"Section {chapter_index + 1}")
        chapter_digests.append({
            "chapter": chapter_label,
            "sourceSequence": int(chapter.get("sourceSequence") or 0),
            "title": str(chapter.get("title") or "").strip(),
            "chaptersAgo": latest_index - chapter_index,
        })
        key_point_details = chapter.get("keyPointDetails") if isinstance(chapter.get("keyPointDetails"), list) else []
        if key_point_details:
            for item in key_point_details:
                if isinstance(item, dict):
                    remember("fact", item.get("claim"), chapter, subject=item.get("subject"), evidence_text=item.get("evidence"), evidence_anchor=item.get("evidenceAnchor"))
        for item in chapter.get("endingState", []) if isinstance(chapter.get("endingState"), list) else []:
            if isinstance(item, dict):
                remember("ending_state", item.get("fact"), chapter, evidence_text=item.get("evidence"), evidence_anchor=item.get("evidenceAnchor"))
        for item in chapter.get("questions", []) if isinstance(chapter.get("questions"), list) else []:
            if isinstance(item, dict):
                remember("open_thread", item.get("question"), chapter, evidence_text=item.get("evidence"), evidence_anchor=item.get("evidenceAnchor"))
        for dossier in chapter.get("dossiers", []) if isinstance(chapter.get("dossiers"), list) else []:
            if not isinstance(dossier, dict):
                continue
            claim_records = dossier.get("claimRecords") if isinstance(dossier.get("claimRecords"), list) else []
            if claim_records:
                for item in claim_records:
                    if not isinstance(item, dict):
                        continue
                    remember(
                        dossier_kind_map.get(str(item.get("kind") or ""), str(item.get("kind") or "fact")),
                        item.get("claim"), chapter, subject=item.get("subject"),
                        evidence_text=item.get("evidence"), evidence_anchor=item.get("evidenceAnchor"),
                    )
            for item in dossier.get("questionDetails", []) if isinstance(dossier.get("questionDetails"), list) else []:
                if isinstance(item, dict):
                    remember("open_thread", item.get("question"), chapter, evidence_text=item.get("evidence"), evidence_anchor=item.get("evidenceAnchor"))

    records = list(records_by_key.values())
    records.sort(key=lambda item: (int(item.get("chaptersAgo") or 0), str(item.get("kind") or ""), str(item.get("claim") or "").casefold()))

    def claims(*kinds: str) -> list[str]:
        accepted = set(kinds)
        return [str(item["claim"]) for item in records if item.get("kind") in accepted and item.get("status") == "active"]

    counts = Counter(str(item.get("kind") or "unknown") for item in records)
    orientation = (
        f"Evidence ledger through {through_label}: "
        f"{counts.get('fact', 0)} facts, {counts.get('event', 0)} events, "
        f"{counts.get('ending_state', 0)} ending states, and {counts.get('open_thread', 0)} open questions. "
        "Each retained entry remains linked to its source passage; chapter summaries are not used as cumulative memory."
    )
    return {
        "schema": CUMULATIVE_CONTEXT_PROMPT_VERSION,
        "throughChapter": through_label,
        "storySoFar": orientation,
        "chapterDigests": chapter_digests,
        "records": records,
        "recordCounts": dict(counts),
        "keyEvents": claims("event"),
        "establishedFacts": claims("fact", "ending_state"),
        "entitiesAndSignificance": claims("entity"),
        "characterStates": [],
        "relationshipStates": [],
        "knowledgeStates": [],
        "locationsAndTimeline": claims("location", "current_time", "timeline"),
        "openThreads": claims("open_thread"),
        "resolvedThreads": [],
        "retiredThreads": retired_threads,
        "threadUpdates": [],
        "readerPromises": claims("reader_promise"),
        "themesAndMotifs": [],
        "voiceAndForm": [],
    }


def authored_chapter_label(chapter: dict[str, object], authored_index: int) -> str:
    role = str(chapter.get("analysisRole") or "").casefold()
    title = strip_markdown_heading(chapter.get("title")).strip()
    if role == "prologue" or normalize_lexical_key(title) == "prologue":
        return "Prologue"
    if role in {"epilogue", "appendix"}:
        return title or role.title()
    match = re.match(r"^(?:chapter\s+)?([ivxlcdm]+|\d+)\b", title, re.I)
    return f"Chapter {match.group(1)}" if match else f"Chapter {authored_index}"


def cumulative_context_evidence(
    pipeline: dict[str, object], chapters: list[dict[str, object]], stop_index: int,
) -> list[dict[str, object]]:
    """Collect saved evidence through one authored chapter without prose rewriting."""
    labels = {
        int(chapter.get("sequence") or chapter.get("number") or index + 1): authored_chapter_label(chapter, index + 1)
        for index, chapter in enumerate(chapters)
    }
    evidence: list[dict[str, object]] = []
    for source_chapter in chapters[:stop_index + 1]:
        source_sequence = int(source_chapter.get("sequence") or source_chapter.get("number") or 0)
        evidence.append({
            "chapter": labels.get(source_sequence, f"Chapter {source_sequence}"),
            "sourceSequence": source_sequence,
            "title": strip_markdown_heading(source_chapter.get("title")),
            "keyPoints": source_chapter.get("keyPoints", []),
            "keyPointDetails": source_chapter.get("keyPointDetails", []),
            "endingState": source_chapter.get("endingState", []),
            "questions": source_chapter.get("questionDetails") or source_chapter.get("newQuestions", []),
            "dossiers": chapter_dossier_payloads(pipeline, source_sequence),
        })
    return evidence


def run_cumulative_context_pipeline(book_id: str, chapter_sequence: int | None = None) -> None:
    book = find_book(book_id)
    if not book or not book.get("llmReviewEnabled"):
        return
    pipeline = add_pipeline_progress(load_pipeline(book))
    ensure_llm_review_stages(book, pipeline)
    stages = {stage["id"]: stage for stage in pipeline.get("stages", [])}
    stage = stages["cumulative-context"]
    dependencies = list(PIPELINE_STAGE_DEPENDENCIES["cumulative-context"])
    if chapter_sequence is None and not pipeline_stage_ready(pipeline, "cumulative-context"):
        stage.update({"status": "blocked", "dependsOn": dependencies, "detail": "Waiting for chapter summaries and chunk dossiers."})
        write_pipeline(book, pipeline)
        return
    model = "Bookinator deterministic ledger"
    cancel_event = PIPELINE_CANCEL_EVENTS.setdefault(book_id, threading.Event())
    chapters = [chapter for chapter in pipeline.get("chapters", []) if strip_markdown_heading(chapter.get("title")).casefold() != "front matter"]
    authored_numbers = {
        int(chapter.get("sequence") or chapter.get("number") or index + 1): index + 1
        for index, chapter in enumerate(chapters)
    }
    authored_labels = {
        int(chapter.get("sequence") or chapter.get("number") or index + 1): authored_chapter_label(chapter, index + 1)
        for index, chapter in enumerate(chapters)
    }
    stage.update({"status": "running", "model": model, "startedAt": stage.get("startedAt") or utc_now(), "dependsOn": dependencies, "detail": "Indexing evidence-linked story memory chapter by chapter."})
    stage.pop("setupRequired", None)
    pipeline.update({"status": "running", "phase": "cumulative-context", "message": "Indexing cumulative manuscript context…", "updatedAt": utc_now()})
    write_pipeline(book, pipeline)
    try:
        for index, chapter in enumerate(chapters):
            sequence = int(chapter.get("sequence") or chapter.get("number") or index + 1)
            authored_number = index + 1
            if chapter_sequence is not None and sequence != chapter_sequence:
                continue
            if cancel_event.is_set() or QUEUE_CANCEL_EVENT.is_set():
                raise PipelineCancelled()
            chunks = [item for item in pipeline.get("chunks", []) if int(item.get("chapterSequence") or 0) == sequence]
            if chapter.get("status") != "complete" or not chunks or any(item.get("dossierStatus") != "complete" for item in chunks):
                if chapter_sequence is not None:
                    stage.update({"status": "pending", "dependsOn": dependencies, "detail": f"Chapter {authored_number} context is waiting for its summary and chunk dossiers."})
                    write_pipeline(book, pipeline)
                continue
            rebased = False
            previous: dict[str, object] = {}
            evidence = cumulative_context_evidence(pipeline, chapters, index)
            authored_label = authored_labels.get(sequence, f"Chapter {authored_number}")
            signature = llm_review_input_signature({"version": CUMULATIVE_CONTEXT_PROMPT_VERSION, "evidence": evidence, "authoredLabel": authored_label})
            existing = read_json_artifact(cumulative_context_path(book, sequence))
            if existing.get("inputSignature") == signature and existing.get("status") == "complete":
                saved_context = existing.get("context") if isinstance(existing.get("context"), dict) else {}
                chapter.update({"contextStatus": "complete", "contextCompletedAt": existing.get("completedAt"), "contextModel": existing.get("model"), "contextRebased": existing.get("rebased"), "context": saved_context, "contextSummary": str(saved_context.get("storySoFar") or "")})
                continue
            started_at = utc_now()
            started = time.monotonic()
            chapter.update({"contextStatus": "running", "contextStartedAt": started_at})
            write_pipeline(book, pipeline)
            artifact = {"schema": CUMULATIVE_CONTEXT_PROMPT_VERSION, "status": "running", "chapterSequence": sequence, "throughChapter": authored_label, "rebased": False, "model": model, "startedAt": started_at, "inputSignature": signature, "input": {"chapterEvidence": evidence, "authoredChapter": authored_label, "generator": "deterministic-evidence-ledger"}, "previousRuns": list(existing.get("previousRuns") or []) if isinstance(existing.get("previousRuns"), list) else []}
            write_json_artifact(cumulative_context_path(book, sequence), artifact)
            context = build_cumulative_context(previous=previous, evidence=evidence, through_chapter=authored_label, model=model, rebased=rebased, cancel_event=cancel_event, run_key=book_id)
            completed_at = utc_now()
            artifact.update({"status": "complete", "completedAt": completed_at, "durationSeconds": round(time.monotonic() - started, 1), "context": context})
            write_json_artifact(cumulative_context_path(book, sequence), artifact)
            chapter.update({"contextStatus": "complete", "contextCompletedAt": completed_at, "contextDurationSeconds": artifact["durationSeconds"], "contextModel": model, "contextRebased": rebased, "contextInputSignature": signature, "context": context, "contextSummary": context.get("storySoFar", "")})
            write_pipeline(book, pipeline)
        completed = sum(chapter.get("contextStatus") == "complete" for chapter in chapters)
        if completed == len(chapters):
            stage.update({"status": "complete", "model": model, "completedAt": utc_now(), "detail": f"Saved {len(chapters)} deterministic cumulative checkpoints."})
            pipeline.update({"status": "complete", "phase": "complete", "message": "Cumulative manuscript context is ready.", "updatedAt": utc_now()})
        else:
            stage.update({"status": "pending", "model": model, "detail": f"Saved {completed} of {len(chapters)} cumulative checkpoints."})
            pipeline.update({"status": "running", "phase": "chapter-complete", "message": f"Saved context through chapter {chapter_sequence or completed}.", "updatedAt": utc_now()})
    except PipelineCancelled:
        for chapter in chapters:
            if chapter.get("contextStatus") == "running":
                chapter["contextStatus"] = "pending"
        stage.update({"status": "pending", "detail": "Stopped safely; completed context checkpoints remain cached."})
        pipeline.update({"status": "paused", "phase": "paused", "message": "Cumulative context stopped; saved checkpoints remain safe.", "updatedAt": utc_now()})
    except Exception as error:
        active = next((chapter for chapter in chapters if chapter.get("contextStatus") == "running"), None)
        if active:
            active.update({"contextStatus": "failed", "contextError": str(error)[:500]})
        stage.update({"status": "warning", "error": str(error)[:500], "detail": "Context building stopped at the first unsafe gap; earlier checkpoints remain usable."})
        pipeline.update({"status": "warning", "phase": "complete", "message": "Cumulative context needs attention.", "updatedAt": utc_now()})
    finally:
        write_pipeline(book, pipeline)
        PIPELINE_THREADS.pop(book_id, None)
        PIPELINE_CANCEL_EVENTS.pop(book_id, None)


def llm_assessment_schema() -> dict[str, object]:
    dimension = {
        "type": "object",
        "properties": {
            "applicable": {"type": "boolean"},
            "score": {"type": "integer", "minimum": 0, "maximum": 5},
            "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
            "rationale": {"type": "string", "minLength": 1},
            "evidence": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["applicable", "score", "confidence", "rationale", "evidence"],
    }
    return {
        "type": "object",
        "properties": {
            "dimensions": {"type": "object", "properties": {key: dimension for key in LLM_REVIEW_DIMENSIONS}, "required": list(LLM_REVIEW_DIMENSIONS)},
            "likely_readers": {"type": "array", "items": {"type": "string"}},
            "commercial_strengths": {"type": "array", "items": {"type": "string"}},
            "commercial_risks": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["dimensions", "likely_readers", "commercial_strengths", "commercial_risks"],
    }


def llm_editorial_schema() -> dict[str, object]:
    proposal = {
        "type": "object",
        "properties": {
            "passage_id": {"type": "string", "minLength": 1},
            "quote": {"type": "string", "minLength": 1},
            "character_start": {"type": "integer", "minimum": 0},
            "character_end": {"type": "integer", "minimum": 1},
            "category": {"type": "string", "enum": list(ANNOTATION_CATEGORIES)},
            "priority": {"type": "string", "enum": ["low", "normal", "high"]},
            "comment": {"type": "string", "minLength": 1},
            "reader_effect": {"type": "string", "minLength": 1},
            "prior_context": {"type": "string"},
            "intentionality_check": {"type": "string", "minLength": 1},
            "revision_goal": {"type": "string", "minLength": 1},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        },
        "required": ["passage_id", "quote", "character_start", "character_end", "category", "priority", "comment", "reader_effect", "prior_context", "intentionality_check", "revision_goal", "confidence"],
    }
    return {
        "type": "object",
        "properties": {
            "editorial_verdict": {"type": "string", "enum": ["no_material_concerns", "material_concerns_found"]},
            "editorial_summary": {"type": "string", "minLength": 1},
            "verdict_basis": {"type": "string", "minLength": 1},
            "strengths": {"type": "array", "items": {"type": "string", "minLength": 1}, "maxItems": 3},
            "editorial_proposals": {"type": "array", "items": proposal, "maxItems": 3},
        },
        "required": ["editorial_verdict", "editorial_summary", "verdict_basis", "strengths", "editorial_proposals"],
    }


def llm_editorial_adjudication_schema() -> dict[str, object]:
    return {
        "type": "object",
        "properties": {
            "decisions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "candidate_number": {"type": "integer", "minimum": 1, "maximum": 3},
                        "verdict": {"type": "string", "enum": ["significant", "soft", "reject"]},
                        "already_answered_nearby": {"type": "boolean"},
                        "concrete_source_problem": {"type": "boolean"},
                        "withheld_information": {"type": "boolean"},
                        "present_scene_comprehensible": {"type": "boolean"},
                        "withholding_is_functional": {"type": "boolean"},
                        "source_observation": {"type": "string"},
                        "proposal_defect": {"type": "string", "enum": ["none", "unsupported", "factually_mistaken", "duplicative", "resolved_by_prior_context", "resolved_in_local_lead_in", "resolved_in_local_continuation", "generic", "deterministic_smell_only", "misreads_deliberate_technique"]},
                        "reason": {"type": "string", "minLength": 1},
                    },
                    "required": ["candidate_number", "verdict", "already_answered_nearby", "concrete_source_problem", "withheld_information", "present_scene_comprehensible", "withholding_is_functional", "source_observation", "proposal_defect", "reason"],
                },
                "maxItems": 3,
            },
        },
        "required": ["decisions"],
    }


def context_for_review(context: dict[str, object], max_characters: int = 24_000) -> dict[str, object]:
    """Build conservative model memory from source-linked records, not summaries.

    Prose chapter summaries are useful navigation but unsafe recursive input: a
    fluent mistake can become inherited story truth. The reader receives only
    compact records with exact source provenance, balanced by kind and age.
    """
    if not context:
        return {}
    records = context.get("records") if isinstance(context.get("records"), list) else []
    if not records:
        return {"schema": CUMULATIVE_CONTEXT_PROMPT_VERSION, "throughChapter": context.get("throughChapter"), "records": [], "selectionNote": "Legacy cumulative prose was excluded because it has no source-linked record boundary."}

    selected: dict[str, object] = {
        "schema": CUMULATIVE_CONTEXT_PROMPT_VERSION,
        "throughChapter": context.get("throughChapter"),
        "records": [],
        "recordCounts": context.get("recordCounts") or {},
        "selectionNote": "Chapter summaries are excluded. Every supplied memory record carries a short exact source quotation.",
    }
    # Roles, inferred clock time, broad location summaries, and model-authored
    # promises are disproportionately prone to unsupported elaboration. The
    # current chapter can establish those afresh; prior memory stays narrower.
    allowed_kinds = {"ending_state", "fact", "event", "open_thread"}
    kind_order = ("ending_state", "event", "fact", "open_thread")
    priority = {kind: index for index, kind in enumerate(kind_order)}
    active = sorted(
        (item for item in records if isinstance(item, dict) and item.get("status") == "active" and item.get("kind") in allowed_kinds),
        key=lambda item: (int(item.get("chaptersAgo") or 0), priority.get(str(item.get("kind") or ""), 99)),
    )
    buckets: dict[str, list[dict[str, object]]] = {}
    duplicate_count = 0
    unsupported_count = 0
    seen_claims: set[str] = set()
    seen_evidence: set[str] = set()
    for item in active:
        kind = str(item.get("kind") or "other")
        claim_key = normalize_lexical_key(item.get("claim") or item.get("question") or item.get("text") or item.get("id") or "")
        provenance = item.get("provenance") if isinstance(item.get("provenance"), list) else []
        source = next((entry for entry in reversed(provenance) if isinstance(entry, dict) and str(entry.get("evidence") or "").strip()), None)
        anchor = source.get("evidenceAnchor") if isinstance(source, dict) and isinstance(source.get("evidenceAnchor"), dict) else {}
        try:
            match_score = float(anchor.get("matchScore") or 0)
        except (TypeError, ValueError):
            match_score = 0.0
        exact = str(anchor.get("matchMethod") or "").casefold() == "exact" or match_score >= .98
        if not source or not exact:
            unsupported_count += 1
            continue
        if claim_key and claim_key in seen_claims:
            duplicate_count += 1
            continue
        seen_claims.add(claim_key)
        evidence_key = normalize_lexical_key(source.get("evidence"))
        if kind != "open_thread" and evidence_key and evidence_key in seen_evidence:
            duplicate_count += 1
            continue
        if kind != "open_thread" and evidence_key:
            seen_evidence.add(evidence_key)
        compact = {
            "kind": kind,
            "claim": str(item.get("claim") or "").strip(),
            "subject": str(item.get("subject") or "").strip(),
            "chapter": str(source.get("chapter") or item.get("lastConfirmedChapter") or ""),
            "chaptersAgo": int(item.get("chaptersAgo") or 0),
            "evidence": str(source.get("evidence") or "").strip()[:600],
        }
        buckets.setdefault(kind, []).append(compact)

    # Preserve both immediate continuity and older orientation. Pure recency
    # would let a verbose chapter crowd the beginning of a book entirely out
    # of memory; keeping everything makes the prompt repetitive and brittle.
    kind_limits = {"ending_state": 8, "event": 12, "fact": 16, "open_thread": 12}
    for kind, items in list(buckets.items()):
        limit = kind_limits.get(kind, 12)
        if len(items) <= limit:
            continue
        recent_count = max(1, limit // 2)
        recent = items[:recent_count]
        older = items[recent_count:]
        older_slots = limit - len(recent)
        sampled = [older[min(len(older) - 1, int(index * len(older) / older_slots))] for index in range(older_slots)]
        buckets[kind] = recent + sampled

    indices = {kind: 0 for kind in buckets}
    schedule = list(kind_order) + sorted(kind for kind in buckets if kind not in kind_order)
    while any(indices[kind] < len(items) for kind, items in buckets.items()):
        made_progress = False
        for kind in schedule:
            items = buckets.get(kind, [])
            index = indices.get(kind, 0)
            if index >= len(items):
                continue
            item = items[index]
            indices[kind] = index + 1
            made_progress = True
            candidate = {**selected, "records": [*selected["records"], item]}
            if len(json.dumps(candidate, ensure_ascii=False)) <= max_characters:
                selected["records"].append(item)
        if not made_progress:
            break
    def finalize_selection_metadata() -> None:
        selected["selectedRecordCount"] = len(selected["records"])
        selected["selectedRecordCounts"] = dict(Counter(str(item.get("kind") or "other") for item in selected["records"]))
        selected["duplicateRecordCount"] = duplicate_count
        selected["unsupportedRecordCount"] = unsupported_count
        selected["omittedRecordCount"] = max(0, len(active) - duplicate_count - unsupported_count - len(selected["records"]))

    finalize_selection_metadata()
    while selected["records"] and len(json.dumps(selected, ensure_ascii=False)) > max_characters:
        selected["records"].pop()
        finalize_selection_metadata()
    return selected


def build_llm_review_packet(book: dict[str, object], pipeline: dict[str, object], chapter: dict[str, object], source: dict[str, object], prior_context: dict[str, object]) -> dict[str, object]:
    sequence = int(chapter.get("sequence") or chapter.get("number") or 0)
    authored_chapters = [
        item for item in pipeline.get("chapters", [])
        if strip_markdown_heading(item.get("title")).casefold() != "front matter"
    ]
    authored_number = next((
        index + 1 for index, item in enumerate(authored_chapters)
        if int(item.get("sequence") or item.get("number") or 0) == sequence
    ), max(1, sequence))
    specialist_id, specialist_description = LLM_REVIEW_SPECIALIST_LENSES[(authored_number - 1) % len(LLM_REVIEW_SPECIALIST_LENSES)]
    packet = {
        "schema": "bookinator-editorial-context-packet-v3",
        "book": {"title": book.get("title"), "author": book.get("author")},
        "chapter": {"number": authored_number, "authoredLabel": authored_chapter_label(chapter, authored_number), "sourceSequence": sequence, "title": source.get("title"), "chapterTitle": source.get("chapterTitle"), "pageStart": source.get("pageStart"), "pageEnd": source.get("pageEnd"), "text": source.get("text")},
        "priorContext": context_for_review(prior_context),
        "specialistLens": {"id": specialist_id, "description": specialist_description},
    }
    packet["inputSignature"] = llm_review_input_signature({"version": LLM_REVIEW_PROMPT_VERSION, **packet})
    return packet


def run_llm_review_structured_step(
    step: str, prompt: str, model: str, schema: dict[str, object], cancel_event: threading.Event,
    run_key: str, trace: dict[str, object] | None = None, attempts: int = 2,
) -> dict[str, object]:
    """Retry malformed reviewer JSON once and retain the exact evidence."""
    failures: list[dict[str, object]] = []
    for attempt in range(1, max(1, attempts) + 1):
        try:
            result, _ = run_structured_model(prompt, model, schema, cancel_event, run_key, activity=step)
            if failures and trace is not None:
                trace.setdefault("recoveredFailures", []).extend(failures)
            return result
        except PipelineCancelled:
            raise
        except json.JSONDecodeError as error:
            failures.append({
                "step": step,
                "attempt": attempt,
                "error": f"Malformed JSON: {error.msg}",
                "line": error.lineno,
                "column": error.colno,
                "character": error.pos,
                "completedAt": utc_now(),
                "rawResponse": str(getattr(error, "raw_response", ""))[:20_000],
            })
            if trace is not None:
                trace["failedAttempts"] = list(failures)
            if attempt >= max(1, attempts):
                raise LLMReviewAnalysisExhausted(step, failures, error) from error
    raise RuntimeError("The LLM Review model did not return a result.")


def normalize_assessment_evidence(chapter_text: str, values: object, limit: int = 3) -> list[str]:
    """Turn model passage references into a few exact, readable source quotations."""
    if not isinstance(values, list) or not chapter_text:
        return []
    passages = {str(item.get("id") or ""): item for item in source_evidence_passages(chapter_text)}
    normalized: list[str] = []

    def remember(quote: object) -> None:
        value = str(quote or "").strip()
        if value and value not in normalized:
            normalized.append(value)

    for raw in values:
        value = str(raw or "").strip()
        if not value:
            continue
        passage_ids = re.findall(r"\bP\d{4}\b", value, re.I)
        if passage_ids:
            for passage_id in passage_ids:
                passage = passages.get(passage_id.upper())
                if passage:
                    remember(passage.get("text"))
                if len(normalized) >= limit:
                    return normalized
            continue
        anchor = resolve_source_evidence(chapter_text, {"quote": value})
        if anchor:
            remember(anchor.get("quote"))
        if len(normalized) >= limit:
            break
    return normalized


def deterministic_review_defect(candidate: dict[str, object], local_before: str, local_continuation: str) -> dict[str, str] | None:
    """Catch narrow proposal mistakes that do not require another model opinion."""
    quote = str(candidate.get("quote") or "")
    proposal_text = " ".join(str(candidate.get(field) or "") for field in ("comment", "reader_effect", "intentionality_check", "revision_goal")).casefold()
    observation_window = f"{local_before[-240:]} {quote}"
    if re.search(r"\b(?:viewpoint|point of view|pov|omniscien|interior(?:ity| thought)|inside (?:his|her|their) (?:head|mind))\b", proposal_text):
        if re.search(r"\bI\s+(?:saw|see|noticed|notice|heard|hear|watched|watch|observed|observe)\b", observation_window, re.I):
            return {
                "proposal_defect": "factually_mistaken",
                "reason": "The passage explicitly frames the detail as the first-person narrator's direct observation, not access to another character's interior state.",
            }
    if "?" in quote and re.search(r"\b(?:unanswered|answer|explain|clarif|continuity|confus|missing information|not addressed)\b", proposal_text):
        continuation = local_continuation.strip()
        if continuation and (re.search(r"\b(?:said|replied|answered|responded|returned|asked)\b", continuation[:700], re.I) or re.search(r"[\"“‘]", continuation[:300])):
            return {
                "proposal_defect": "resolved_in_local_continuation",
                "reason": "The anchor is a character's spoken question and the nearby continuation immediately engages it; the question itself is not a continuity failure.",
            }
    return None


def review_context_packet(
    packet: dict[str, object], model: str, cancel_event: threading.Event, run_key: str,
    trace: dict[str, object] | None = None,
    precomputed_editorial: dict[str, object] | None = None,
    precomputed_assessment: dict[str, object] | None = None,
) -> dict[str, object]:
    rubric = {
        "narrative_engagement": "moment-to-moment interest and desire to continue",
        "character_likability": "appeal, fascination, or productive investment; not moral goodness",
        "character_relatability": "emotional intelligibility and access to motives or experience",
        "clarity": "comprehensibility of action, viewpoint, time, causality, and stakes",
        "stakes_and_tension": "meaningful pressure, consequence, uncertainty, and propulsion",
        "coherence_and_continuity": "consistency with the story state known before this chapter",
        "voice_and_distinctiveness": "specificity, confidence, memorability, and freedom from generic treatment",
        "emotional_impact": "earned feeling and the chapter's capacity to move its intended reader",
        "genre_and_audience_fit": "delivery on likely genre promises and clarity about the intended reader",
        "saleability": "commercial legibility and readiness, not a sales prediction or verdict on artistic worth",
    }
    chapter_packet = packet.get("chapter") if isinstance(packet.get("chapter"), dict) else {}
    chapter_text = str(chapter_packet.get("text") or "")
    chapter_metadata = {key: value for key, value in chapter_packet.items() if key != "text"}
    chapter_identity = {
        "book": packet.get("book"),
        "chapter": chapter_metadata,
    }
    # Context has already been selected at whole-record boundaries. Never slice
    # serialized JSON: doing so used to hide late fields and could hand the
    # reader a syntactically incomplete memory once a book grew past 30k chars.
    prior_context_json = json.dumps(packet.get("priorContext") or {}, ensure_ascii=False)
    chapter_identity_json = json.dumps(chapter_identity, ensure_ascii=False)[:8_000]
    current_chapter_text = chapter_text if precomputed_editorial is not None else chapter_text[:68_000]
    shared_inputs = f"""Prior cumulative story state:
{prior_context_json}

Current chapter identity:
{chapter_identity_json}

Current canonical chapter text, divided into exact source passages and offsets:
{evidence_passage_prompt(current_chapter_text)}"""
    specialist = packet.get("specialistLens") if isinstance(packet.get("specialistLens"), dict) else {}
    editorial_prompt = f"""Act as a rigorous first reader, not the manuscript's final editor. Review the current chapter in light of what a reader could know before it. Produce proposals for a human to accept, revise, or reject; do not impersonate the reviewer.

NO ISSUE IS THE DEFAULT. Most passages do not need an annotation. Returning an empty editorial_proposals array is a successful, often preferable result. The lenses below are a search space, not a form: never manufacture one observation per lens and never invent criticism merely to make the response look complete.

Stable core lenses: non-sequiturs, reader confusion, causality, continuity, character motivation, emotional logic, engagement, and scene purpose.
Specialist lens for this chapter: {specialist.get('id') or 'structure'} — {specialist.get('description') or 'scene purpose and structural consequence'}.

Return a formal editorial verdict, a concise editorial summary, up to three specific strengths worth preserving, and AT MOST THREE editorial proposals ranked strongest first.

The verdict and summary must obey this contract:
- If editorial_proposals is empty, editorial_verdict MUST be "no_material_concerns" and editorial_summary MUST be exactly "No material editorial concerns found."
- If editorial_proposals contains one or more items, editorial_verdict MUST be "material_concerns_found" and editorial_summary must state the number and nature of those concerns directly.
- verdict_basis is always required. Explain why the strongest plausible concerns did or did not cross the professional-interruption threshold. Name the chapter's actual purpose, technique, or evidence; do not merely restate the verdict.
- Put praise only in strengths. Never use phrases such as "however," "a few areas," "could benefit," or "may need refinement" unless each claimed concern appears as a source-anchored editorial proposal.

Return a proposal only when all of these are true:
1. A specific source passage supports it. Return that passage ID, its printed character start and end, and an exact copied quotation; Bookinator will triangulate all four values.
2. A reasonable reader's comprehension, belief, emotional response, or engagement is materially affected.
3. Prior context, genre convention, character viewpoint, deliberate ambiguity, or intentionally withheld information does not already explain the effect.
4. A professional editor would probably interrupt the author about it rather than merely note an unusual choice or personal preference.
5. The confidence is at least 0.75 and there is a concrete revision goal.

Do not restate deterministic Smells unless their narrative consequence matters. Do not report generic advice, plot summary, mild stylistic preference, or a concern already resolved by the supplied context. A strength is allowed only when it teaches the author something specific worth preserving. When uncertain, omit the proposal.

Preserve the manuscript's epistemic and causal boundaries in proposals, verdict_basis, and strengths. Observation is not diagnosis; sequence or proximity is not causation; a tense scene does not make every arriving person an external threat; and a character's reaction is not evidence of concealed conflict when the local text gives another explanation. Do not say a detail proves, validates, confirms, causes, diagnoses, or threatens unless the current source or prior context explicitly establishes that relation. State warranted interpretations as interpretations, not facts.

Distinguish present-scene clarity from intentionally withheld story knowledge. A reader may understand what is happening, what a character experiences, and why the moment matters while not yet knowing the concealed cause, identity, mechanism, cure, or final explanation. Do not propose that a Gothic, mystery, suspense, or revelation-driven manuscript answer such a live question early merely because the answer is not yet available. Only flag withholding when the present action itself becomes incoherent, the text contradicts what the reader already knows, or the delay creates a concrete reader-facing cost worth discussing.

{shared_inputs}
"""
    assessment_prompt = f"""Act as a rigorous manuscript assessor. Evaluate the current chapter in light of what a reader could know before it. This assessment is evidence for a human reviewer, not a verdict and not an editorial annotation task.

Assess every dimension with confidence, concise rationale, and one to three short VERBATIM quotations copied from the current canonical chapter text. The evidence array must contain readable source words, never passage IDs, offset notation, paraphrases, or an exhaustive list of citations. Apply these definitions:
{json.dumps(rubric, ensure_ascii=False, indent=2)}

First decide whether each dimension meaningfully applies to this chapter. When it does not, return applicable=false, score=0, explain why in rationale, and leave evidence empty. Do not penalize an atmospheric, transitional, documentary, or setting-focused chapter merely because a character, relationship, conflict, or other inapplicable subject is absent. When applicable=true, score must be 1 through 5.

For saleability, discuss audience clarity, genre promise, positioning, accessibility, and revision readiness. Never predict sales, invent market data, or treat conventionality as quality. Likability means reader investment, including compellingly difficult characters. Relatability means emotional intelligibility, not demographic similarity.

Preserve the manuscript's epistemic and causal boundaries in every rationale, strength, and risk. Observation is not diagnosis; sequence or proximity is not causation; a tense scene does not make every arriving person a threat; and a reaction does not prove hidden conflict when nearby text supplies another explanation. Do not say a detail proves, validates, confirms, causes, diagnoses, or threatens unless the supplied source explicitly establishes that relation. Label interpretation as interpretation.

{shared_inputs}
"""
    editorial_result = precomputed_editorial or run_llm_review_structured_step("editorial review", editorial_prompt, model, llm_editorial_schema(), cancel_event, run_key, trace)
    if trace is not None:
        trace["editorial"] = editorial_result
    raw_candidates = []
    for item in editorial_result.get("editorial_proposals", []) if isinstance(editorial_result.get("editorial_proposals"), list) else []:
        if not isinstance(item, dict):
            continue
        quote = str(item.get("quote") or "").strip()
        confidence = float(item.get("confidence") or 0)
        anchor = resolve_source_evidence(chapter_text, item)
        if not anchor or confidence < 0.75:
            continue
        raw_candidates.append({
            **item,
            "quote": anchor["quote"],
            "passage_id": anchor.get("passageId"),
            "character_start": anchor["characterStart"],
            "character_end": anchor["characterEnd"],
            "anchor_match_method": anchor["matchMethod"],
            "anchor_match_score": anchor["matchScore"],
            "candidate_number": len(raw_candidates) + 1,
        })
        if len(raw_candidates) == 3:
            break

    adjudication = {"decisions": []}
    deterministic_defects: dict[int, dict[str, str]] = {}
    if raw_candidates:
        skeptical_candidates = []
        for candidate in raw_candidates:
            start = int(candidate["character_start"])
            end = int(candidate["character_end"])
            local_before = chapter_text[max(0, start - 1200):start]
            local_continuation = chapter_text[end:min(len(chapter_text), end + 1200)]
            gate = deterministic_review_defect(candidate, local_before, local_continuation)
            if gate:
                deterministic_defects[int(candidate["candidate_number"])] = gate
            skeptical_candidates.append({
                **candidate,
                "local_before": local_before,
                "anchored_passage": chapter_text[start:end],
                "local_continuation": local_continuation,
                "deterministic_check": gate or {"proposal_defect": "none"},
            })
        adjudication_prompt = f"""Be a fair senior editor calibrating another model's proposed annotations. Preserve useful uncertainty instead of forcing every candidate into a yes/no decision.

Decide each supplied candidate independently:
- significant: the source supports a concrete material reader effect and a professional editor would probably interrupt the author about it.
- soft: the source contains a concrete, nameable problem or tradeoff worth showing a human, but intent, context, severity, or the best revision remains uncertain.
- reject: identify a concrete defect in the proposal itself—it is unsupported by the source, factually mistaken, duplicative, already resolved by prior context, purely generic, or merely restates a deterministic Smell without narrative consequence.

For significant or soft, set concrete_source_problem=true and use source_observation to name what the passage actually does—not what it vaguely "may" do. A generic possibility is not a soft lead. For example, "this may slow pacing; consider shortening" is generic unless it identifies the redundant beat, delayed expectation, or lost causal/emotional step. "The transition could be smoother" is generic unless it identifies the missing temporal, spatial, causal, or viewpoint bridge. Reject such proposals with proposal_defect=generic. Set concrete_source_problem=false for every rejected generic or unsupported proposal.

Before assigning a verdict, read both local_before and local_continuation. Set already_answered_nearby=true when either side supplies the clarification, recognition, causal bridge, or explanation the proposal requests. In that case verdict must be reject. Use proposal_defect=resolved_in_local_lead_in when the answer precedes the anchor, or resolved_in_local_continuation when it follows. A proposal cannot be significant merely because its isolated anchor looks confusing after the model ignores nearby setup or a deliberately timed answer.

Two calibration examples are rules, not optional suggestions. "I saw her glance toward him" reports visible behavior through first-person observation; it is not omniscient viewpoint drift or access to her thoughts. A character asking a question is not itself a continuity defect; read the following dialogue, and reject the proposal when the scene immediately engages or answers that question. If deterministic_check names one of these defects, verdict must be reject with that defect.

For each candidate, explicitly decide whether it concerns withheld_information, whether the present_scene_comprehensible without that answer, and whether the withholding_is_functional for mystery, suspense, dread, viewpoint limitation, or a later revelation. When all three are true, reject with proposal_defect=misreads_deliberate_technique. Asking the author to explain a concealed cause, supernatural mechanism, diagnosis, identity, or protection rule before the story chooses to reveal it is not a clarity repair when the immediate action and reader effect remain legible. A real tradeoff in pacing, trust, or emotional access may still be soft—but name that concrete cost instead of treating unanswered information itself as the defect.

Consult the prior story state's open_threads and reader_promises. If the candidate merely demands an answer to an uncertainty the manuscript is actively carrying, reject it as misreads_deliberate_technique unless the present scene cannot be understood without the answer.

For every decision choose one proposal_defect. Use none only for significant or genuinely soft concerns. A reject requires a concrete non-none defect; if no concrete defect applies, use soft rather than reject.

Subjectivity or uncertainty alone is not grounds for rejection; use soft. Deliberate technique is grounds for rejection only when the candidate has misunderstood that technique rather than identified a real tradeoff. Do not improve or replace weak candidates. It is acceptable for every candidate to be significant, soft, or rejected, but explain the actual evidence for each decision.

Prior story state:
{prior_context_json}

Current chapter identity:
{chapter_identity_json}

Candidates with local source context:
{json.dumps(skeptical_candidates, ensure_ascii=False)[:28_000]}
"""
        adjudication = run_llm_review_structured_step("skeptical adjudication", adjudication_prompt, model, llm_editorial_adjudication_schema(), cancel_event, run_key, trace)
        if trace is not None:
            trace["adjudication"] = adjudication
    assessment_result = precomputed_assessment or run_llm_review_structured_step("chapter assessment", assessment_prompt, model, llm_assessment_schema(), cancel_event, run_key, trace)
    if trace is not None:
        trace["assessment"] = assessment_result
    dimensions = {}
    raw_dimensions = assessment_result.get("dimensions") if isinstance(assessment_result.get("dimensions"), dict) else {}
    for key in LLM_REVIEW_DIMENSIONS:
        item = raw_dimensions.get(key) if isinstance(raw_dimensions.get(key), dict) else {}
        applicable = bool(item.get("applicable", True))
        score = max(0, min(5, int(item.get("score") or 0)))
        if applicable and score == 0:
            score = 1
        dimensions[key] = {
            "applicable": applicable,
            "score": score if applicable else 0,
            "confidence": str(item.get("confidence") or "low"),
            "rationale": str(item.get("rationale") or "").strip(),
            "evidence": normalize_assessment_evidence(chapter_text, item.get("evidence", [])),
        }
    decisions = {
        int(item.get("candidate_number") or 0): item
        for item in adjudication.get("decisions", []) if isinstance(adjudication.get("decisions"), list) and isinstance(item, dict)
    }
    proposals = []
    rejected_candidates = []
    discarded_candidates = []
    for item in raw_candidates:
        decision = decisions.get(int(item["candidate_number"]), {})
        verdict = str(decision.get("verdict") or "soft")
        concrete_source_problem = decision.get("concrete_source_problem")
        deterministic_defect = deterministic_defects.get(int(item["candidate_number"]))
        if deterministic_defect:
            verdict = "reject"
            decision = {
                **decision,
                **deterministic_defect,
                "concrete_source_problem": False,
            }
        if not deterministic_defect and (
            bool(decision.get("withheld_information"))
            and bool(decision.get("present_scene_comprehensible"))
            and bool(decision.get("withholding_is_functional"))
        ):
            verdict = "reject"
            decision = {
                **decision,
                "proposal_defect": "misreads_deliberate_technique",
                "reason": str(decision.get("reason") or "The proposal mistakes functional withholding for a present-scene clarity failure."),
            }
        if verdict in {"significant", "soft"} and concrete_source_problem is False:
            verdict = "reject"
            decision = {
                **decision,
                "proposal_defect": "generic",
                "reason": str(decision.get("reason") or "The proposal does not identify a concrete source-level problem."),
            }
        if verdict != "significant":
            candidate = {
                "quote": str(item.get("quote") or ""),
                "comment": str(item.get("comment") or ""),
                "category": str(item.get("category") or "editorial"),
                "priority": str(item.get("priority") or "low"),
                "confidence": float(item.get("confidence") or 0),
                "reason": str(decision.get("reason") or "The skeptical pass did not affirm this candidate."),
                "adjudicationDefect": str(decision.get("proposal_defect") or "none"),
                "alreadyAnsweredNearby": bool(decision.get("already_answered_nearby", False)),
                "adjudicationObservation": str(decision.get("source_observation") or "").strip(),
                "characterStart": int(item.get("character_start") or 0),
                "characterEnd": int(item.get("character_end") or 0),
                "readerEffect": str(item.get("reader_effect") or "").strip(),
                "priorContext": str(item.get("prior_context") or "").strip(),
                "intentionalityCheck": str(item.get("intentionality_check") or "").strip(),
                "revisionGoal": str(item.get("revision_goal") or "").strip(),
                "passageId": str(item.get("passage_id") or ""),
                "anchorMatchMethod": str(item.get("anchor_match_method") or ""),
                "anchorMatchScore": float(item.get("anchor_match_score") or 0),
                "status": "soft_lead" if verdict == "soft" else "rejected_by_model",
            }
            (rejected_candidates if verdict == "soft" else discarded_candidates).append(candidate)
            continue
        quote = str(item.get("quote") or "").strip()
        start = int(item["character_start"])
        end = int(item["character_end"])
        category = str(item.get("category") or "editorial")
        proposals.append({
            "id": uuid.uuid4().hex,
            "quote": quote,
            "characterStart": start,
            "characterEnd": end,
            "passageId": str(item.get("passage_id") or ""),
            "anchorMatchMethod": str(item.get("anchor_match_method") or ""),
            "anchorMatchScore": float(item.get("anchor_match_score") or 0),
            "anchorFingerprint": hashlib.sha256(chapter_text[max(0, start - 96):min(len(chapter_text), end + 96)].encode("utf-8")).hexdigest(),
            "category": category if category in ANNOTATION_CATEGORIES else "editorial",
            "priority": str(item.get("priority") or "normal") if str(item.get("priority") or "normal") in {"low", "normal", "high"} else "normal",
            "comment": str(item.get("comment") or "").strip(),
            "readerEffect": str(item.get("reader_effect") or "").strip(),
            "priorContext": str(item.get("prior_context") or "").strip(),
            "intentionalityCheck": str(item.get("intentionality_check") or "").strip(),
            "revisionGoal": str(item.get("revision_goal") or "").strip(),
            "confidence": float(item.get("confidence") or 0),
            "adjudicationReason": str(decision.get("reason") or "").strip(),
            "adjudicationDefect": str(decision.get("proposal_defect") or "none"),
            "alreadyAnsweredNearby": bool(decision.get("already_answered_nearby", False)),
            "adjudicationObservation": str(decision.get("source_observation") or "").strip(),
            "status": "proposed",
        })
    concern_count = len(proposals)
    editorial_summary = (
        f"{concern_count} material editorial {'concern' if concern_count == 1 else 'concerns'} found."
        if concern_count
        else "No material editorial concerns found."
    )
    model_editorial_summary = str(editorial_result.get("editorial_summary") or "").strip()
    verdict_basis = str(editorial_result.get("verdict_basis") or "").strip()
    if not concern_count and rejected_candidates:
        verdict_basis = f"{len(rejected_candidates)} plausible editorial {'lead remains' if len(rejected_candidates) == 1 else 'leads remain'} for human review; none crossed the significant-concern threshold."
    elif not concern_count and discarded_candidates:
        reasons = [item["reason"] for item in discarded_candidates if item.get("reason")]
        verdict_basis = "No candidate survived calibrated review." + (f" {reasons[0]}" if reasons else "")
    return {
        "editorialVerdict": "material_concerns_found" if concern_count else "no_material_concerns",
        "editorialSummary": editorial_summary,
        "editorialRationale": verdict_basis or (model_editorial_summary if concern_count else "The model found no source-anchored concern that crossed the professional-interruption threshold."),
        "editorialStrengths": [str(item).strip() for item in editorial_result.get("strengths", []) if str(item).strip()][:3] if isinstance(editorial_result.get("strengths"), list) else [],
        # Compatibility for saved reports and clients created before v4. This is
        # deliberately the normalized verdict, never the model's free prose.
        "chapterAssessment": editorial_summary,
        "dimensions": dimensions,
        "editorialProposals": proposals,
        "rejectedCandidates": rejected_candidates,
        "discardedCandidates": discarded_candidates,
        "specialistLens": specialist,
        "likelyReaders": [str(item).strip() for item in assessment_result.get("likely_readers", []) if str(item).strip()] if isinstance(assessment_result.get("likely_readers"), list) else [],
        "commercialStrengths": [str(item).strip() for item in assessment_result.get("commercial_strengths", []) if str(item).strip()] if isinstance(assessment_result.get("commercial_strengths"), list) else [],
        "commercialRisks": [str(item).strip() for item in assessment_result.get("commercial_risks", []) if str(item).strip()] if isinstance(assessment_result.get("commercial_risks"), list) else [],
    }


def chapter_reading_schema(include_review: bool) -> dict[str, object]:
    cast_entry = {
        "type": "object",
        "properties": {
            "entity_id": {"type": "string", "minLength": 1},
            "canonical_name": {"type": "string", "minLength": 1},
            "aliases": {"type": "array", "items": {"type": "string"}},
            "role": {"type": "string", "minLength": 1},
            "evidence_ref": source_evidence_ref_schema(),
        },
        "required": ["entity_id", "canonical_name", "aliases", "role", "evidence_ref"],
    }
    properties: dict[str, object] = {
        "cast": {"type": "array", "items": cast_entry},
        "action_audit": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "passage_id": {"type": "string", "minLength": 1},
                    "verdict": {"type": "string", "enum": ["material_action", "background_or_description"]},
                    "actor_entity_id": {"type": "string"},
                    "literal_action": {"type": "string", "minLength": 1},
                    "resulting_state": {"type": "string", "minLength": 1},
                    "epistemic_status": {"type": "string", "minLength": 1},
                    "reason": {"type": "string", "minLength": 1},
                    "evidence_ref": source_evidence_ref_schema(),
                },
                "required": [
                    "passage_id", "verdict", "actor_entity_id", "literal_action",
                    "resulting_state", "epistemic_status", "reason", "evidence_ref",
                ],
            },
        },
        "summary": chapter_summary_schema(),
        "dossier": chapter_dossier_schema(),
    }
    required = ["cast", "action_audit", "summary", "dossier"]
    if include_review:
        properties.update({"editorial": llm_editorial_schema(), "assessment": llm_assessment_schema()})
        required.extend(("editorial", "assessment"))
    return {"type": "object", "properties": properties, "required": required}


def normalize_chapter_reading_cast(value: object, source_text: str) -> list[dict[str, object]]:
    """Canonicalize the model's identity ledger and discard unsupported entries."""
    if not isinstance(value, list):
        return []
    cast: list[dict[str, object]] = []
    used_ids: set[str] = set()
    used_aliases: dict[str, str] = {}
    for index, item in enumerate(value, 1):
        if not isinstance(item, dict):
            continue
        canonical_name = re.sub(r"\s+", " ", str(item.get("canonical_name") or "")).strip()
        role = re.sub(r"\s+", " ", str(item.get("role") or "")).strip()
        anchor = resolve_source_evidence(source_text, item.get("evidence_ref"))
        if not canonical_name or not role or not anchor:
            continue
        requested_id = re.sub(r"[^a-z0-9_-]+", "-", str(item.get("entity_id") or "").casefold()).strip("-")
        entity_id = requested_id or f"entity-{index}"
        if entity_id in used_ids:
            suffix = 2
            while f"{entity_id}-{suffix}" in used_ids:
                suffix += 1
            entity_id = f"{entity_id}-{suffix}"
        aliases = [canonical_name]
        for alias in item.get("aliases", []) if isinstance(item.get("aliases"), list) else []:
            cleaned = re.sub(r"\s+", " ", str(alias or "")).strip()
            if cleaned and cleaned.casefold() not in {known.casefold() for known in aliases}:
                aliases.append(cleaned)
        unique_aliases: list[str] = []
        for alias in aliases:
            alias_key = re.sub(r"[^a-z0-9]+", " ", alias.casefold()).strip()
            if not alias_key or (alias_key in used_aliases and used_aliases[alias_key] != entity_id):
                continue
            used_aliases[alias_key] = entity_id
            unique_aliases.append(alias)
        used_ids.add(entity_id)
        cast.append({
            "entityId": entity_id,
            "canonicalName": canonical_name,
            "aliases": unique_aliases,
            "role": role,
            "evidence": anchor["quote"],
            "evidenceAnchor": anchor,
        })
    return cast


def chapter_reading_consistency_candidates(raw: dict[str, object], source_text: str) -> list[dict[str, object]]:
    """Build a compact, source-local audit packet rather than rereading the chapter."""
    candidates: list[dict[str, object]] = []
    for index, item in enumerate(raw.get("cast", []) if isinstance(raw.get("cast"), list) else []):
        if not isinstance(item, dict):
            continue
        anchor = resolve_source_evidence(source_text, item.get("evidence_ref"))
        if not anchor:
            continue
        aliases = ", ".join(str(alias) for alias in item.get("aliases", []) if str(alias).strip())
        candidates.append({
            "candidateId": f"cast:{index}",
            "path": "cast",
            "subject": str(item.get("entity_id") or ""),
            "claim": f"{item.get('canonical_name')}: {item.get('role')}" + (f"; aliases: {aliases}" if aliases else ""),
            "evidence": anchor["quote"],
            "characterStart": int(anchor["characterStart"]),
            "characterEnd": int(anchor["characterEnd"]),
        })
    collections = [
        ("summary.key_points", raw.get("summary", {}).get("key_points") if isinstance(raw.get("summary"), dict) else []),
        ("summary.ending_state", raw.get("summary", {}).get("ending_state") if isinstance(raw.get("summary"), dict) else []),
    ]
    collections.extend(
        (f"dossier.{field}", raw.get("dossier", {}).get(field) if isinstance(raw.get("dossier"), dict) else [])
        for field in ("facts", "events", "entities", "locations", "current_times", "promises", "timeline_observations")
    )
    collections.append((
        "editorial.editorial_proposals",
        raw.get("editorial", {}).get("editorial_proposals") if isinstance(raw.get("editorial"), dict) else [],
    ))
    for path, values in collections:
        for index, item in enumerate(values if isinstance(values, list) else []):
            if not isinstance(item, dict):
                continue
            evidence_value = item.get("evidence_ref") or ({"quote": item.get("quote")} if item.get("quote") else None)
            anchor = resolve_source_evidence(source_text, evidence_value)
            if not anchor:
                continue
            candidates.append({
                "candidateId": f"{path}:{index}",
                "path": path,
                "subject": str(item.get("subject") or ""),
                "claim": str(item.get("claim") or item.get("fact") or item.get("comment") or ""),
                "evidence": anchor["quote"],
                "characterStart": int(anchor["characterStart"]),
                "characterEnd": int(anchor["characterEnd"]),
            })
    assessment = raw.get("assessment") if isinstance(raw.get("assessment"), dict) else {}
    dimensions = assessment.get("dimensions") if isinstance(assessment.get("dimensions"), dict) else {}
    for dimension, item in dimensions.items():
        if not isinstance(item, dict):
            continue
        anchor = next((
            resolve_source_evidence(source_text, {"quote": evidence})
            for evidence in item.get("evidence", []) if str(evidence).strip()
            if resolve_source_evidence(source_text, {"quote": evidence})
        ), None) if isinstance(item.get("evidence"), list) else None
        if not anchor:
            continue
        candidates.append({
            "candidateId": f"assessment.dimensions:{dimension}",
            "path": "assessment.dimensions",
            "subject": str(dimension),
            "claim": str(item.get("rationale") or ""),
            "evidence": anchor["quote"],
            "characterStart": int(anchor["characterStart"]),
            "characterEnd": int(anchor["characterEnd"]),
        })
    return candidates


def chapter_action_coverage_gaps(raw: dict[str, object], source_text: str) -> list[dict[str, object]]:
    """Find audited material actions absent from Summary or Dossier evidence."""
    represented: dict[str, set[str]] = {"summary_key_point": set(), "dossier_event": set()}
    owners = (
        ("summary_key_point", raw.get("summary", {}).get("key_points") if isinstance(raw.get("summary"), dict) else []),
        ("dossier_event", raw.get("dossier", {}).get("events") if isinstance(raw.get("dossier"), dict) else []),
    )
    for target, values in owners:
        for item in values if isinstance(values, list) else []:
            if not isinstance(item, dict):
                continue
            anchor = resolve_source_evidence(source_text, item.get("evidence_ref"))
            if anchor and anchor.get("passageId"):
                represented[target].add(str(anchor["passageId"]))

    gaps: list[dict[str, object]] = []
    for action in raw.get("action_audit", []) if isinstance(raw.get("action_audit"), list) else []:
        if not isinstance(action, dict) or action.get("verdict") != "material_action":
            continue
        anchor = resolve_source_evidence(source_text, action.get("evidence_ref"))
        passage_id = str(action.get("passage_id") or (anchor or {}).get("passageId") or "")
        if not anchor or not passage_id:
            continue
        for target in ("summary_key_point", "dossier_event"):
            if passage_id not in represented[target]:
                gaps.append({
                    "passage_id": passage_id,
                    "target": target,
                    "audited_actor": str(action.get("actor_entity_id") or ""),
                    "audited_action": str(action.get("literal_action") or ""),
                    "audited_resulting_state": str(action.get("resulting_state") or ""),
                    "epistemic_status": str(action.get("epistemic_status") or ""),
                    "evidence_ref": {
                        "passage_id": anchor["passageId"], "quote": anchor["quote"],
                        "character_start": anchor["characterStart"], "character_end": anchor["characterEnd"],
                    },
                })
    return gaps


def identity_sensitive_source_excerpts(source_text: str, cast: list[dict[str, object]]) -> list[str]:
    """Expose compact source passages where names and relationship labels coexist.

    These are deliberately source-derived rather than model-derived. They give
    the verifier a chance to notice constructions such as "Millarca joined my
    ward", which prove that two labels cannot name the same participant.
    """
    relationship = re.compile(
        r"\b(?:ward|daughter|son|child|niece|nephew|mother|father|sister|brother|wife|husband|friend|companion|chaperon(?:e)?)\b",
        re.I,
    )
    names = {
        str(value).strip()
        for item in cast
        for value in (item.get("canonicalName"), *(item.get("aliases") or []))
        if len(str(value).strip()) >= 3
    }
    paragraphs = [re.sub(r"\s+", " ", part).strip() for part in re.split(r"\n\s*\n", source_text) if part.strip()]
    excerpts: list[str] = []
    for paragraph in paragraphs:
        mentioned = [name for name in names if re.search(rf"\b{re.escape(name)}\b", paragraph, re.I)]
        if relationship.search(paragraph) and mentioned:
            excerpts.append(paragraph[:1800])
        elif len(mentioned) >= 2:
            excerpts.append(paragraph[:1800])
        if len(excerpts) >= 16:
            break
    return excerpts


def chapter_reading_consistency_schema() -> dict[str, object]:
    return {
        "type": "object",
        "properties": {
            "corrected_summary": {"type": "string"},
            "corrected_dossier_synopsis": {"type": "string"},
            "cast_corrections": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "candidate_id": {"type": "string", "minLength": 1},
                        "canonical_name": {"type": "string", "minLength": 1},
                        "aliases": {"type": "array", "items": {"type": "string"}},
                        "role": {"type": "string", "minLength": 1},
                        "evidence_ref": source_evidence_ref_schema(),
                        "reason": {"type": "string", "minLength": 1},
                    },
                    "required": ["candidate_id", "canonical_name", "aliases", "role", "evidence_ref", "reason"],
                },
            },
            "decisions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "candidate_id": {"type": "string", "minLength": 1},
                        "verdict": {"type": "string", "enum": ["keep", "reject"]},
                        "reason": {"type": "string", "minLength": 1},
                    },
                    "required": ["candidate_id", "verdict", "reason"],
                },
            },
            "coverage_decisions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "passage_id": {"type": "string", "minLength": 1},
                        "target": {"type": "string", "enum": ["summary_key_point", "dossier_event"]},
                        "verdict": {"type": "string", "enum": ["add", "omit_as_immaterial"]},
                        "claim": {"type": "string"},
                        "subject": {"type": "string"},
                        "evidence_ref": source_evidence_ref_schema(),
                        "reason": {"type": "string", "minLength": 1},
                    },
                    "required": ["passage_id", "target", "verdict", "claim", "subject", "evidence_ref", "reason"],
                },
            },
            "issues": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["corrected_summary", "corrected_dossier_synopsis", "cast_corrections", "decisions", "coverage_decisions", "issues"],
    }


EPISTEMIC_SOURCE_MARKER = re.compile(
    r"\b(?:as\s+i\s+(?:thought|supposed|believed)|seem(?:ed|s)?|appear(?:ed|s)?|"
    r"apparently|perhaps|possibly|probably|may|might|could|i\s+(?:thought|supposed|believed))\b",
    re.I,
)
EPISTEMIC_CLAIM_MARKER = re.compile(
    r"\b(?:thought|supposed|believed|perceived|seem(?:ed|s)?|appear(?:ed|s)?|"
    r"apparently|perhaps|possibly|probably|may|might|could|according\s+to)\b",
    re.I,
)


def preserves_epistemic_boundary(claim: object, quotation: object) -> bool:
    """Do not let a repair silently turn perception or uncertainty into fact."""
    source = str(quotation or "")
    return not EPISTEMIC_SOURCE_MARKER.search(source) or bool(EPISTEMIC_CLAIM_MARKER.search(str(claim or "")))


def apply_chapter_reading_consistency(
    raw: dict[str, object], audit: dict[str, object], candidate_ids: set[str],
    coverage_gaps: list[dict[str, object]] | None = None,
) -> tuple[dict[str, object], dict[str, object]]:
    """Apply only explicit, addressable audit decisions; retain everything else."""
    cleaned = copy.deepcopy(raw)
    cast_corrections: list[dict[str, str]] = []
    cast_values = cleaned.get("cast") if isinstance(cleaned.get("cast"), list) else []
    for correction in audit.get("cast_corrections", []) if isinstance(audit.get("cast_corrections"), list) else []:
        if not isinstance(correction, dict):
            continue
        candidate_id = str(correction.get("candidate_id") or "")
        path, _, index_value = candidate_id.rpartition(":")
        if candidate_id not in candidate_ids or path != "cast" or not index_value.isdigit():
            continue
        index = int(index_value)
        if index >= len(cast_values) or not isinstance(cast_values[index], dict):
            continue
        updated = dict(cast_values[index])
        updated.update({
            "canonical_name": str(correction.get("canonical_name") or "").strip(),
            "aliases": [str(item).strip() for item in correction.get("aliases", []) if str(item).strip()],
            "role": str(correction.get("role") or "").strip(),
            "evidence_ref": correction.get("evidence_ref"),
        })
        cast_values[index] = updated
        cast_corrections.append({
            "candidateId": candidate_id,
            "canonicalName": updated["canonical_name"],
            "role": updated["role"],
            "reason": str(correction.get("reason") or "").strip(),
        })
    rejected: dict[str, str] = {}
    decisions: list[dict[str, str]] = []
    for decision in audit.get("decisions", []) if isinstance(audit.get("decisions"), list) else []:
        if not isinstance(decision, dict):
            continue
        candidate_id = str(decision.get("candidate_id") or "")
        verdict = str(decision.get("verdict") or "").casefold()
        reason = str(decision.get("reason") or "").strip()
        if candidate_id not in candidate_ids or verdict not in {"keep", "reject"}:
            continue
        decisions.append({"candidateId": candidate_id, "verdict": verdict, "reason": reason})
        if verdict == "reject":
            rejected[candidate_id] = reason
    grouped: dict[str, set[int]] = {}
    for candidate_id in rejected:
        path, _, index_value = candidate_id.rpartition(":")
        if index_value.isdigit():
            grouped.setdefault(path, set()).add(int(index_value))
        elif path == "assessment.dimensions":
            assessment = cleaned.get("assessment") if isinstance(cleaned.get("assessment"), dict) else {}
            dimensions = assessment.get("dimensions") if isinstance(assessment.get("dimensions"), dict) else {}
            if index_value in dimensions:
                dimensions[index_value] = {
                    "applicable": False,
                    "score": 0,
                    "confidence": "low",
                    "rationale": "Withheld because the identity and boundary audit found a source conflict.",
                    "evidence": [],
                }
    for path, indices in grouped.items():
        owner: object = cleaned
        parts = path.split(".")
        for part in parts[:-1]:
            owner = owner.get(part) if isinstance(owner, dict) else None
        values = owner.get(parts[-1]) if isinstance(owner, dict) else None
        if isinstance(values, list):
            owner[parts[-1]] = [item for index, item in enumerate(values) if index not in indices]
    summary = cleaned.get("summary") if isinstance(cleaned.get("summary"), dict) else None
    corrected_summary = str(audit.get("corrected_summary") or "").strip()
    if summary is not None and corrected_summary:
        summary["summary"] = corrected_summary
    dossier = cleaned.get("dossier") if isinstance(cleaned.get("dossier"), dict) else None
    corrected_synopsis = str(audit.get("corrected_dossier_synopsis") or "").strip()
    if dossier is not None and corrected_synopsis:
        dossier["synopsis"] = corrected_synopsis
    allowed_gaps = {
        (str(item.get("passage_id") or ""), str(item.get("target") or "")): item
        for item in (coverage_gaps or []) if isinstance(item, dict)
    }
    coverage_decisions: list[dict[str, object]] = []
    coverage_additions = 0
    unsafe_coverage_additions = 0
    for decision in audit.get("coverage_decisions", []) if isinstance(audit.get("coverage_decisions"), list) else []:
        if not isinstance(decision, dict):
            continue
        passage_id = str(decision.get("passage_id") or "")
        target = str(decision.get("target") or "")
        verdict = str(decision.get("verdict") or "")
        gap = allowed_gaps.get((passage_id, target))
        if not gap or verdict not in {"add", "omit_as_immaterial"}:
            continue
        record = {
            "passageId": passage_id, "target": target, "verdict": verdict,
            "reason": str(decision.get("reason") or "").strip(),
        }
        if verdict == "add":
            claim = str(decision.get("claim") or "").strip()
            subject = str(decision.get("subject") or "").strip()
            evidence = gap.get("evidence_ref") if isinstance(gap.get("evidence_ref"), dict) else {}
            if not claim or not subject or not preserves_epistemic_boundary(claim, evidence.get("quote")):
                record["verdict"] = "rejected_unsafe_addition"
                unsafe_coverage_additions += 1
            else:
                addition = {"claim": claim, "subject": subject, "evidence_ref": copy.deepcopy(evidence)}
                if target == "summary_key_point" and summary is not None:
                    summary.setdefault("key_points", []).append(addition)
                    coverage_additions += 1
                elif target == "dossier_event" and dossier is not None:
                    dossier.setdefault("events", []).append(addition)
                    coverage_additions += 1
        coverage_decisions.append(record)
    report = {
        "schema": CHAPTER_READING_CONSISTENCY_VERSION,
        "issues": [str(item).strip() for item in audit.get("issues", []) if str(item).strip()] if isinstance(audit.get("issues"), list) else [],
        "decisions": decisions,
        "rejectedCandidateCount": len(rejected),
        "castCorrections": cast_corrections,
        "castCorrectionCount": len(cast_corrections),
        "coverageDecisions": coverage_decisions,
        "coverageAdditionCount": coverage_additions,
        "unsafeCoverageAdditionCount": unsafe_coverage_additions,
    }
    return cleaned, report


def replace_cast_ids_with_names(raw: dict[str, object], cast: list[dict[str, object]]) -> dict[str, object]:
    """Keep stable IDs inside the model contract but expose readable subjects downstream."""
    cleaned = copy.deepcopy(raw)
    names = {
        str(item.get("entityId") or ""): str(item.get("canonicalName") or "")
        for item in cast if item.get("entityId") and item.get("canonicalName")
    }
    for owner_name in ("summary", "dossier"):
        owner = cleaned.get(owner_name)
        if not isinstance(owner, dict):
            continue
        for values in owner.values():
            if not isinstance(values, list):
                continue
            for item in values:
                if isinstance(item, dict) and str(item.get("subject") or "") in names:
                    item["subject"] = names[str(item["subject"])]
    return cleaned


def audit_chapter_reading_consistency(
    raw: dict[str, object], cast: list[dict[str, object]], source_text: str, model: str,
    cancel_event: threading.Event, run_key: str, trace: dict[str, object],
) -> tuple[dict[str, object], dict[str, object], list[dict[str, object]]]:
    candidates = chapter_reading_consistency_candidates(raw, source_text)
    coverage_gaps = chapter_action_coverage_gaps(raw, source_text)
    summary = raw.get("summary") if isinstance(raw.get("summary"), dict) else {}
    dossier = raw.get("dossier") if isinstance(raw.get("dossier"), dict) else {}
    prompt = f"""Audit this chapter reading for IDENTITY, CLAIM/EVIDENCE ENTAILMENT, and CHAPTER-BOUNDARY consistency. This is a short verification pass, not another chapter analysis.

THE CANONICAL SOURCE IS THE ONLY IDENTITY AUTHORITY. The proposed cast is a hypothesis to audit, not a fact source. Correct a cast entry when its canonical name, aliases, role, or relationship conflicts with the source. In particular, if a sentence places a named person alongside "my ward", "her daughter", or another description, those labels identify different participants unless the source explicitly says otherwise. Preserve an entity_id when correcting its label or role.

For every non-cast candidate, ask whether the cited evidence and its local source actually entail the claim. An exact quotation proves location, not truth. Reject a claim when it changes the grammatical actor or object; invents a role or relationship; upgrades proximity or sequence into causation; supplies a location, clock time, chronology, number, polarity, motive, or diagnosis the source does not establish; or states an incorrect chapter-ending condition. For example, a father standing near a carriage is not necessarily its driver, "by this time" does not establish daytime, and a conversation does not by itself establish friendship or guardianship.

KEEP IS THE DEFAULT only when the claim is genuinely supported. Do not reject for style, harmless incompleteness, or a qualified interpretation that the cited passage reasonably supports. A name and its true alias are one participant; two separately introduced or co-present people remain distinct. Do not delete a plausible cast alias merely because it is absent from this chapter; correct it only when this chapter's source conflicts with it.

Review every ACTION COVERAGE GAP exactly once. Use add only when that exact action is materially necessary in the named target; otherwise use omit_as_immaterial. An addition must preserve the grammatical actor, literal action, resulting state, and epistemic status. Perception, uncertainty, reported belief, and phrases such as "as I thought" are facts about the observer—not permission to turn the perceived event into objective fact. Copy the supplied exact evidence_ref. Return an empty claim and subject for an omission.

Before auditing individual candidates, compare CURRENT SUMMARY and CURRENT DOSSIER SYNOPSIS with the final 20 percent of CANONICAL SOURCE. They must include the last material action, revelation, arrival, departure, decision, or change actually reached by the chapter. If either stops early, return a minimally corrected replacement even when no individual candidate is rejected. This boundary check is mandatory.

Return cast_corrections ONLY for cast entries that need correction, using exact source evidence. Return decisions ONLY for other candidates that must be rejected; omit keep decisions. Return an empty corrected_summary or corrected_dossier_synopsis when that prose is already sound. When either contains a rejected factual assertion, identity error, or boundary error, return a minimally corrected version that removes it without adding facts.

CAST LEDGER
{json.dumps(cast, ensure_ascii=False)}

CANDIDATES WITH EXACT QUOTES AND CANONICAL OFFSETS
{json.dumps(candidates, ensure_ascii=False)}

ACTION COVERAGE GAPS
{json.dumps(coverage_gaps, ensure_ascii=False)}

CURRENT SUMMARY
{str(summary.get('summary') or '')}

CURRENT DOSSIER SYNOPSIS
{str(dossier.get('synopsis') or '')}

CANONICAL SOURCE — supplied once; use candidate offsets to inspect local context
{source_text}
"""
    audit = run_llm_review_structured_step(
        "chapter reading consistency", prompt, model, chapter_reading_consistency_schema(),
        cancel_event, run_key, trace, attempts=2,
    )
    trace["result"] = audit
    cleaned, report = apply_chapter_reading_consistency(
        raw, audit, {str(item["candidateId"]) for item in candidates}, coverage_gaps,
    )
    verified_cast = normalize_chapter_reading_cast(cleaned.get("cast"), source_text)
    return replace_cast_ids_with_names(cleaned, verified_cast), report, verified_cast


def chapter_reading_prompt(
    book: dict[str, object], chapter: dict[str, object], source: dict[str, object],
    prior_context: dict[str, object], include_review: bool,
    specialist_signals: dict[str, object] | None = None,
) -> str:
    """Ask the primary reader to create every semantic view during one read."""
    text = str(source.get("text") or "")
    action_passages = [] if is_front_matter(chapter) else chapter_action_passages(text)
    identity_candidates = specialist_signals.get("identityCandidates", []) if isinstance(specialist_signals, dict) else []
    front_matter = is_front_matter(chapter)
    material_guidance = front_matter_analysis_guidance("summary and dossier") if front_matter else "This is narrative manuscript material."
    review_instructions = ""
    if include_review:
        specialist_index = max(0, int(chapter.get("sequence") or chapter.get("number") or 1) - 1) % len(LLM_REVIEW_SPECIALIST_LENSES)
        specialist_id, specialist_description = LLM_REVIEW_SPECIALIST_LENSES[specialist_index]
        review_instructions = f"""
EDITORIAL AND ASSESSMENT VIEW
Act as a rigorous first reader whose output is a proposal for a human, never a reviewer decision. NO ISSUE IS THE DEFAULT. Return at most three editorial proposals, and only when an exact source passage supports a material reader effect, context and deliberate technique do not already explain it, confidence is at least 0.75, and a professional editor would probably interrupt the author. Put praise only in strengths. The specialist lens is {specialist_id}: {specialist_description}.

If there are no proposals, editorial_verdict must be no_material_concerns and editorial_summary exactly "No material editorial concerns found." Otherwise use material_concerns_found and state the number and nature directly. Every proposal must contain its passage ID, printed offsets, exact copied quotation, reader effect, intentionality check, and concrete revision goal.

Assess all ten rubric dimensions using their schema. Mark a dimension applicable=false with score 0 when it genuinely does not apply; otherwise score 1-5. Evidence must be one to three short verbatim quotations, not passage IDs or paraphrase. Likability means reader investment rather than moral goodness. Relatability means emotional intelligibility. Saleability concerns audience clarity, positioning, accessibility, and readiness—not predicted sales.
"""
    return f"""Read this canonical manuscript chapter ONCE and return all requested editorial views in one JSON object. The nested cast, summary, dossier, editorial, and assessment objects are different projections of the same reading, not separate passes. Actually fill every requested field; never narrate or promise that you will follow the instructions.

IDENTITY LEDGER — DO THIS FIRST
- Before writing any other field, build cast for every person, creature, organization, or identity-sensitive entity used by the other views.
- Give each one a short stable entity_id, its canonical_name, every name or description that refers to the SAME entity, its role in this chapter, and exact evidence_ref.
- Do not borrow a nearby proper name for an unnamed person. If the text calls someone only "the General's ward," keep that descriptive canonical name until the text itself identifies them.
- A name and its alias are one entity, never two participants. Conversely, two people introduced separately remain two entities even when they occupy similar roles.
- When a summary or dossier claim concerns a cast member, put that entity_id in the claim's subject field. The prose may use the canonical name, but must preserve the ledger's identity distinctions.
- Audit every supplied GLiNER identity candidate as a fallible attention signal. It proves only that an exact source span resembled a requested label; it does not establish canonical identity, role, relationship, action, or story fact.

SOURCE DISCIPLINE
- The canonical text is authoritative. Copy exact evidence quotations and the supplied passage ID and printed character offsets. Bookinator will triangulate them.
- Preserve grammatical actors: "my father" belongs to the narrator, not the nearest named character.
- Observation is not diagnosis; proximity or sequence is not causation; reaction is not proof; unease is not hostility. Use qualified language for inference.
- Never assert no, not, never, or without unless the cited words establish that polarity.
- Intentionally withheld story knowledge is not present-scene confusion when the action and reader effect remain legible.
- Preserve epistemic qualifiers everywhere they travel. "As I thought," "seemed," "perhaps," reported belief, dreams, and perceptions describe the observer's knowledge; never flatten them into objective fact in Summary, Dossier, Editorial, or Assessment.

ACTION RECALL AUDIT
- Audit every supplied action passage exactly once in action_audit. The deterministic selector is a fallible attention aid; a cue word is not proof of a material action.
- For a material action, record its grammatical actor, literal action, resulting state, and epistemic status. For background or description, say why it is not a material action.
- Then cross-check Summary and Dossier against the completed audit. Material actions may be omitted only deliberately; they must not silently disappear or be replaced by a contradictory generic paraphrase.

SUMMARY VIEW
Write a compact 2-4 paragraph digest covering the chapter's complete movement, especially its final material turn. Every factual summary assertion must have an equivalent evidence-linked key_points claim. ending_state records the literal boundary state of important people, objects, places, and unresolved actions. Questions must name a concrete choice, causal bridge, concealed knowledge, relationship change, thematic pressure, reader expectation, setup, or continuity issue earned here; do not manufacture generic prompts or repeat answered questions.

DOSSIER VIEW
Build an evidence-preserving ledger of facts, events, entities, locations, current scene times, promises, and timeline observations. A character promise requires an actual commitment; a story promise requires a concrete setup or withheld answer. Keep current scene time distinct from remembered events and chronology. The synopsis follows the same source discipline. Dossier questions use the same specificity standard as summary questions.
{review_instructions}
MATERIAL GUIDANCE
{material_guidance}

BOOK AND PRIOR READER KNOWLEDGE
{json.dumps({"title": book.get("title"), "author": book.get("author"), "priorContext": prior_context}, ensure_ascii=False)}

PRIOR-CONTEXT SAFETY
Prior reader knowledge is fallible orientation, never source authority. The canonical chapter text overrides it. Do not copy an identity, relationship, causality, or chapter-boundary claim from prior context unless this chapter independently supports using it. When prior context and the chapter disagree, follow the chapter and preserve the disagreement for the human rather than harmonizing them.

CHAPTER
{json.dumps({key: source.get(key) for key in ("sequence", "title", "chapterTitle", "sectionMarkers", "pageStart", "pageEnd", "sourcePagination")}, ensure_ascii=False)}

DETERMINISTIC ACTION-PASSAGE CANDIDATES
{json.dumps(action_passages, ensure_ascii=False)}

GLINER IDENTITY CANDIDATES
{json.dumps(identity_candidates, ensure_ascii=False)}

CANONICAL SOURCE PASSAGES
{evidence_passage_prompt(text)}
"""


def prior_context_for_chapter(
    book: dict[str, object], pipeline: dict[str, object], chapters: list[dict[str, object]],
    chapter_index: int, cancel_event: threading.Event,
) -> dict[str, object]:
    if chapter_index <= 0:
        return {}
    previous = chapters[chapter_index - 1]
    previous_sequence = int(previous.get("sequence") or previous.get("number") or chapter_index)
    artifact = read_json_artifact(cumulative_context_path(book, previous_sequence))
    if artifact.get("schema") == CUMULATIVE_CONTEXT_PROMPT_VERSION and isinstance(artifact.get("context"), dict):
        return artifact["context"]
    evidence = cumulative_context_evidence(pipeline, chapters, chapter_index - 1)
    return build_cumulative_context(
        previous={}, evidence=evidence,
        through_chapter=authored_chapter_label(previous, chapter_index),
        model="", rebased=False, cancel_event=cancel_event, run_key=str(book.get("id") or ""),
    )


def run_chapter_reading_pipeline(book_id: str, chapter_sequence: int, include_review: bool | None = None) -> None:
    """Produce Summary, Dossier, and optional first-reader analysis from one model read."""
    book = find_book(book_id)
    if not book:
        return
    pipeline = add_pipeline_progress(load_pipeline(book))
    ensure_llm_review_stages(book, pipeline)
    stages = {stage["id"]: stage for stage in pipeline.get("stages", [])}
    chapters = list(pipeline.get("chapters", []))
    chapter_index = next((index for index, item in enumerate(chapters) if int(item.get("sequence") or item.get("number") or 0) == chapter_sequence), -1)
    if chapter_index < 0:
        return
    chapter = chapters[chapter_index]
    source = load_chapter_source(book, chapter_sequence)
    if not source:
        raise ValueError(f"Canonical source for chapter {chapter_sequence} is missing.")
    text = str(source.get("text") or "")
    cancel_event = PIPELINE_CANCEL_EVENTS.setdefault(book_id, threading.Event())
    settings = load_settings()
    available = ollama_status()
    models = available["models"] if available["running"] else []
    model = effective_primary_model(models, settings)
    if not model:
        raise ValueError("Assign or install the primary reader before starting Chapter Reading.")
    include_review = bool(book.get("llmReviewEnabled")) if include_review is None else bool(include_review)
    include_review = include_review and strip_markdown_heading(chapter.get("title")).casefold() != "front matter"
    review_chapters = [item for item in chapters if strip_markdown_heading(item.get("title")).casefold() != "front matter"]
    review_index = review_chapters.index(chapter) if chapter in review_chapters else -1
    prior_context = prior_context_for_chapter(book, pipeline, review_chapters, review_index, cancel_event) if include_review else {}
    packet = build_llm_review_packet(book, pipeline, chapter, source, prior_context) if include_review else {}
    # The deterministic ledger is deliberately exhaustive; the reader gets
    # the balanced, record-safe selection already prepared for LLM Review.
    # Feeding the raw ledger here would erase much of the single-read speedup.
    reading_context = packet.get("priorContext") if include_review and isinstance(packet.get("priorContext"), dict) else {}
    specialist_signals = read_json_artifact(gliner_signals_path(book, chapter_sequence))
    if not is_front_matter(chapter) and specialist_signals.get("status") != "complete":
        raise ValueError("Run the visible GLiNER signals step before Chapter Reading.")
    prompt = chapter_reading_prompt(book, chapter, source, reading_context, include_review, specialist_signals)
    signature = llm_review_input_signature({
        "version": CHAPTER_READING_PROMPT_VERSION, "model": model,
        "chapter": {key: source.get(key) for key in ("sequence", "title", "chapterTitle")},
        "source": text, "priorContext": reading_context, "includeReview": include_review,
        "glinerSignals": specialist_signals.get("identityCandidates", []),
    })
    started_at = utc_now()
    started = time.monotonic()
    chapter.update({
        "status": "running", "llmReviewStatus": "running" if include_review else chapter.get("llmReviewStatus"),
        "chapterReadingStatus": "running", "chapterReadingStartedAt": started_at,
        "chapterReadingModel": model, "chapterReadingInputSignature": signature,
    })
    chunks = [item for item in pipeline.get("chunks", []) if int(item.get("chapterSequence") or 0) == chapter_sequence]
    for chunk in chunks:
        chunk.update({"dossierStatus": "running", "dossierModel": model, "dossierStartedAt": started_at})
    for stage_id in ("summaries", "dossiers", "llm-review"):
        if stage_id == "llm-review" and not include_review:
            continue
        stages[stage_id].update({"status": "running", "model": model, "startedAt": stages[stage_id].get("startedAt") or started_at, "detail": f"Chapter Reading is producing the {stage_id.replace('-', ' ')} view."})
    pipeline.update({"status": "running", "phase": "chapter-reading", "message": f"Reading {chapter.get('title') or source.get('title')} once for Summary, Dossier, and LLM Review…", "workerPid": os.getpid(), "updatedAt": utc_now()})
    write_pipeline(book, pipeline)
    artifact = {
        "schema": CHAPTER_READING_PROMPT_VERSION, "status": "running", "chapterSequence": chapter_sequence,
        "model": model, "startedAt": started_at, "inputSignature": signature,
        "input": {"book": {"title": book.get("title"), "author": book.get("author")}, "chapter": source, "priorContext": reading_context, "includeReview": include_review, "glinerSignals": specialist_signals},
    }
    write_json_artifact(chapter_reading_path(book, chapter_sequence), artifact)
    try:
        primary_raw = run_llm_review_structured_step(
            "chapter reading", prompt, model, chapter_reading_schema(include_review),
            cancel_event, book_id, artifact, attempts=2,
        )
        primary_duration = round(time.monotonic() - started, 1)
        cast = normalize_chapter_reading_cast(primary_raw.get("cast"), text)
        chapter["chapterReadingPhase"] = "consistency"
        pipeline.update({
            "phase": "chapter-reading-consistency",
            "message": f"Checking identities and the ending of {chapter.get('title') or source.get('title')}…",
            "updatedAt": utc_now(),
        })
        artifact.update({"phase": "consistency", "primaryDurationSeconds": primary_duration, "primaryResponse": primary_raw})
        write_json_artifact(chapter_reading_path(book, chapter_sequence), artifact)
        write_pipeline(book, pipeline)
        consistency_trace: dict[str, object] = {}
        raw, consistency_report, cast = audit_chapter_reading_consistency(
            primary_raw, cast, text, model, cancel_event, book_id, consistency_trace,
        )
        summary = normalize_chapter_summary(raw.get("summary") if isinstance(raw.get("summary"), dict) else {}, text)
        summary.setdefault("questionDetails", [])
        summary.setdefault("endingState", [])
        summary["promptVersion"] = SUMMARY_PROMPT_VERSION
        if is_front_matter(chapter):
            summary.update({"newQuestions": [], "questionDetails": [], "endingState": [], "analysisMode": "front-matter-structural"})
        else:
            summary["endingCoverage"] = chapter_summary_ending_coverage(summary.get("summary"), summary, text)
        dossier_source = {
            **source, "text": text,
            "chapterLabel": chapter.get("title") or source.get("title"),
            "chapterTitle": chapter.get("chapterTitle") or source.get("chapterTitle"),
        }
        dossier = analyze_chunk_dossier(
            dossier_source, model, cancel_event, book_id, canonical_chapter_text=text,
            precomputed_result=raw.get("dossier") if isinstance(raw.get("dossier"), dict) else {},
        )
        completed_at = utc_now()
        duration = round(time.monotonic() - started, 1)
        chapter.update(summary)
        chapter.update({
            "status": "complete", "completedAt": completed_at, "durationSeconds": 0.0,
            "model": model, "chapterReadingStatus": "complete", "chapterReadingCompletedAt": completed_at,
            "chapterReadingDurationSeconds": duration, "chapterReadingPromptVersion": CHAPTER_READING_PROMPT_VERSION,
            "chapterReadingPhase": "complete", "chapterReadingCast": cast, "chapterReadingConsistency": consistency_report,
        })
        for chunk_index, chunk in enumerate(chunks):
            chunk_artifact = read_json_artifact(chunk_artifacts_path(book) / f"{int(chunk.get('sequence') or chunk_index + 1):04d}.json")
            shared = {
                "dossierStatus": "complete", "dossierModel": model, "dossierCompletedAt": completed_at,
                "dossierDurationSeconds": 0.0, "chapterReadingDurationSeconds": duration,
                "chapterReadingInputSignature": signature,
            }
            if chunk_index == 0:
                shared["dossier"] = dossier
            else:
                shared["dossierCoveredByChapterReading"] = int(chunks[0].get("sequence") or 0) if chunks else 0
                chunk_artifact.pop("dossier", None)
                chunk.pop("dossier", None)
            chunk.update(shared)
            chunk_artifact.update(shared)
            write_chunk_artifact(book, int(chunk.get("sequence") or chunk_index + 1), chunk_artifact)
        review_result: dict[str, object] = {}
        if include_review:
            packet["inputSignature"] = signature
            write_json_artifact(llm_review_packet_path(book, chapter_sequence), packet)
            review_trace: dict[str, object] = {"chapterReading": raw, "chapterReadingConsistency": consistency_trace}
            review_result = review_context_packet(
                packet, model, cancel_event, book_id, review_trace,
                precomputed_editorial=raw.get("editorial") if isinstance(raw.get("editorial"), dict) else {},
                precomputed_assessment=raw.get("assessment") if isinstance(raw.get("assessment"), dict) else {},
            )
            review_artifact = {
                "schema": LLM_REVIEW_PROMPT_VERSION, "sourceSchema": CHAPTER_READING_PROMPT_VERSION,
                "status": "complete", "chapterSequence": chapter_sequence, "model": model,
                "startedAt": started_at, "completedAt": utc_now(), "durationSeconds": 0.0,
                "chapterReadingDurationSeconds": duration, "inputSignature": signature,
                "modelOutput": review_trace, "result": review_result,
            }
            write_json_artifact(llm_review_result_path(book, chapter_sequence), review_artifact)
            chapter.update({
                "llmReviewStatus": "complete", "llmReviewCompletedAt": review_artifact["completedAt"],
                "llmReviewDurationSeconds": 0.0, "llmReviewSharedDurationSeconds": duration,
                "llmReviewModel": model, "llmReviewInputSignature": signature, "llmReview": review_result,
            })
        total_duration = round(time.monotonic() - started, 1)
        chapter.update({
            "chapterReadingPrimaryDurationSeconds": primary_duration,
            "chapterReadingConsistencyDurationSeconds": round(max(0.0, duration - primary_duration), 1),
            "chapterReadingDurationSeconds": total_duration,
        })
        if include_review:
            chapter["llmReviewSharedDurationSeconds"] = total_duration
        for chunk in chunks:
            chunk["chapterReadingDurationSeconds"] = total_duration
            chunk_artifact = read_json_artifact(chunk_artifacts_path(book) / f"{int(chunk.get('sequence') or 0):04d}.json")
            chunk_artifact["chapterReadingDurationSeconds"] = total_duration
            write_chunk_artifact(book, int(chunk.get("sequence") or 0), chunk_artifact)
        artifact.update({
            "status": "complete", "completedAt": utc_now(), "durationSeconds": total_duration,
            "primaryDurationSeconds": primary_duration,
            "consistencyDurationSeconds": round(max(0.0, duration - primary_duration), 1),
            "output": {"primaryResponse": primary_raw, "consistencyAudit": consistency_trace, "acceptedResponse": raw},
            "normalized": {"cast": cast, "consistency": consistency_report, "summary": summary, "dossier": dossier, **({"review": review_result} if include_review else {})},
        })
        write_json_artifact(chapter_reading_path(book, chapter_sequence), artifact)
        summary_complete = sum(item.get("status") == "complete" for item in chapters)
        dossier_complete = sum(item.get("dossierStatus") == "complete" for item in pipeline.get("chunks", []))
        stages["summaries"].update({"status": "complete" if summary_complete == len(chapters) else "pending", "detail": f"Completed {summary_complete} of {len(chapters)} chapter summaries."})
        stages["dossiers"].update({"status": "complete" if dossier_complete == len(pipeline.get("chunks", [])) else "pending", "detail": f"Completed {dossier_complete} of {len(pipeline.get('chunks', []))} structured dossiers."})
        if include_review:
            review_complete = sum(item.get("llmReviewStatus") == "complete" for item in review_chapters)
            stages["llm-review"].update({"status": "complete" if review_complete == len(review_chapters) else "pending", "detail": f"Saved optional first-reader review for {review_complete} of {len(review_chapters)} chapters."})
        pipeline.update({"status": "running", "phase": "chapter-complete", "message": f"Chapter Reading saved for {chapter.get('title') or chapter_sequence}; continuing through this book.", "updatedAt": utc_now()})
    except PipelineCancelled:
        duration = round(time.monotonic() - started, 1)
        chapter.update({
            "status": "pending", "chapterReadingStatus": "pending",
            "chapterReadingDurationSeconds": duration, "interruptedAt": utc_now(),
        })
        if include_review:
            chapter["llmReviewStatus"] = "pending"
        for chunk in chunks:
            chunk.update({"dossierStatus": "pending", "dossierError": "Stopped before completion."})
        artifact.update({"status": "pending", "interruptedAt": utc_now(), "durationSeconds": duration})
        write_json_artifact(chapter_reading_path(book, chapter_sequence), artifact)
        raise
    except Exception as error:
        duration = round(time.monotonic() - started, 1)
        chapter.update({"status": "failed", "chapterReadingStatus": "failed", "chapterReadingCompletedAt": utc_now(), "chapterReadingDurationSeconds": duration, "error": str(error)[:500]})
        if include_review:
            chapter.update({"llmReviewStatus": "failed", "llmReviewError": str(error)[:500]})
        for chunk in chunks:
            chunk.update({"dossierStatus": "failed", "dossierError": str(error)[:500], "dossierCompletedAt": utc_now()})
        artifact.update({"status": "failed", "completedAt": utc_now(), "durationSeconds": duration, "error": str(error)[:500]})
        write_json_artifact(chapter_reading_path(book, chapter_sequence), artifact)
        raise
    finally:
        write_pipeline(book, pipeline)


def run_llm_review_pipeline(book_id: str, chapter_sequence: int | None = None) -> None:
    book = find_book(book_id)
    if not book or not book.get("llmReviewEnabled"):
        return
    pipeline = add_pipeline_progress(load_pipeline(book))
    ensure_llm_review_stages(book, pipeline)
    stages = {stage["id"]: stage for stage in pipeline.get("stages", [])}
    stage = stages["llm-review"]
    dependencies = list(PIPELINE_STAGE_DEPENDENCIES["llm-review"])
    settings = load_settings()
    available = ollama_status()
    models = available["models"] if available["running"] else []
    model = effective_primary_model(models, settings)
    if not model:
        stage.update({"status": "blocked", "setupRequired": True, "detail": "Assign or install the primary reader before starting LLM Review."})
        write_pipeline(book, pipeline)
        return
    cancel_event = PIPELINE_CANCEL_EVENTS.setdefault(book_id, threading.Event())
    chapters = [chapter for chapter in pipeline.get("chapters", []) if strip_markdown_heading(chapter.get("title")).casefold() != "front matter"]
    stage.update({"status": "running", "model": model, "startedAt": stage.get("startedAt") or utc_now(), "dependsOn": dependencies, "detail": "Reviewing cached chapter packets with the optional first-reader rubric."})
    stage.pop("error", None)
    pipeline.update({"status": "running", "phase": "llm-review", "message": "Running the optional LLM Review…", "updatedAt": utc_now()})
    write_pipeline(book, pipeline)
    try:
        for index, chapter in enumerate(chapters):
            sequence = int(chapter.get("sequence") or chapter.get("number") or index + 1)
            if chapter_sequence is not None and sequence != chapter_sequence:
                continue
            if cancel_event.is_set() or QUEUE_CANCEL_EVENT.is_set():
                raise PipelineCancelled()
            if index and chapters[index - 1].get("contextStatus") != "complete":
                if chapter_sequence is not None:
                    previous_sequence = int(chapters[index - 1].get("sequence") or index)
                    stage.update({"status": "pending", "dependsOn": dependencies, "detail": f"Chapter {sequence} review is waiting for Context {previous_sequence}."})
                    write_pipeline(book, pipeline)
                continue
            source = load_chapter_source(book, sequence)
            if not source:
                raise ValueError(f"Canonical source for chapter {sequence} is missing.")
            prior_context: dict[str, object] = {}
            if index:
                previous_sequence = int(chapters[index - 1].get("sequence") or index)
                prior_artifact = read_json_artifact(cumulative_context_path(book, previous_sequence))
                if prior_artifact.get("schema") == CUMULATIVE_CONTEXT_PROMPT_VERSION and isinstance(prior_artifact.get("context"), dict):
                    prior_context = prior_artifact["context"]
                else:
                    # A bounded regression may deliberately preserve older
                    # artifacts. Re-index their saved evidence instantly so a
                    # new review never consumes the obsolete LLM rewrite.
                    prior_evidence = cumulative_context_evidence(pipeline, chapters, index - 1)
                    prior_context = build_cumulative_context(
                        previous={}, evidence=prior_evidence,
                        through_chapter=authored_chapter_label(chapters[index - 1], index),
                        model="", rebased=False, cancel_event=cancel_event, run_key=book_id,
                    )
            packet = build_llm_review_packet(book, pipeline, chapter, source, prior_context)
            signature = str(packet["inputSignature"])
            existing = read_json_artifact(llm_review_result_path(book, sequence))
            if existing.get("inputSignature") == signature and existing.get("status") == "complete":
                result = existing.get("result") if isinstance(existing.get("result"), dict) else {}
                chapter.update({"llmReviewStatus": "complete", "llmReviewCompletedAt": existing.get("completedAt"), "llmReviewModel": existing.get("model"), "llmReviewInputSignature": signature, "llmReview": result})
                chapter.pop("llmReviewError", None)
                continue
            write_json_artifact(llm_review_packet_path(book, sequence), packet)
            started_at = utc_now()
            started = time.monotonic()
            chapter.update({"llmReviewStatus": "running", "llmReviewStartedAt": started_at})
            chapter.pop("llmReviewError", None)
            write_pipeline(book, pipeline)
            model_output: dict[str, object] = {}
            result = review_context_packet(packet, model, cancel_event, book_id, model_output)
            completed_at = utc_now()
            artifact = {"schema": LLM_REVIEW_PROMPT_VERSION, "status": "complete", "chapterSequence": sequence, "model": model, "startedAt": started_at, "completedAt": completed_at, "durationSeconds": round(time.monotonic() - started, 1), "inputSignature": signature, "modelOutput": model_output, "result": result, "previousRuns": list(existing.get("previousRuns") or []) if isinstance(existing.get("previousRuns"), list) else []}
            write_json_artifact(llm_review_result_path(book, sequence), artifact)
            chapter.update({"llmReviewStatus": "complete", "llmReviewCompletedAt": completed_at, "llmReviewDurationSeconds": artifact["durationSeconds"], "llmReviewModel": model, "llmReviewInputSignature": signature, "llmReview": result})
            chapter.pop("llmReviewError", None)
            write_pipeline(book, pipeline)
        completed = sum(chapter.get("llmReviewStatus") == "complete" for chapter in chapters)
        if completed == len(chapters):
            stage.update({"status": "complete", "model": model, "completedAt": utc_now(), "detail": f"Saved optional first-reader review for {len(chapters)} chapters."})
            stage.pop("error", None)
            pipeline.update({"status": "complete", "phase": "complete", "message": "LLM Review is ready to inspect.", "updatedAt": utc_now()})
        else:
            stage.update({"status": "pending", "model": model, "detail": f"Saved optional first-reader review for {completed} of {len(chapters)} chapters."})
            stage.pop("error", None)
            pipeline.update({"status": "running", "phase": "chapter-complete", "message": f"Saved LLM Review for chapter {chapter_sequence or completed}.", "updatedAt": utc_now()})
    except PipelineCancelled:
        for chapter in chapters:
            if chapter.get("llmReviewStatus") == "running":
                chapter["llmReviewStatus"] = "pending"
        stage.update({"status": "pending", "detail": "Stopped safely; completed machine reviews remain cached."})
        pipeline.update({"status": "paused", "phase": "paused", "message": "LLM Review stopped; completed chapters remain safe.", "updatedAt": utc_now()})
    except Exception as error:
        active = next((chapter for chapter in chapters if chapter.get("llmReviewStatus") == "running"), None)
        if active:
            failed_at = utc_now()
            duration = round(time.monotonic() - started, 1) if "started" in locals() else None
            active.update({"llmReviewStatus": "failed", "llmReviewError": str(error)[:500], "llmReviewCompletedAt": failed_at})
            if duration is not None:
                active["llmReviewDurationSeconds"] = duration
            if "packet" in locals() and "signature" in locals() and "model_output" in locals():
                failure_artifact = {
                    "schema": LLM_REVIEW_PROMPT_VERSION,
                    "status": "failed",
                    "chapterSequence": int(active.get("sequence") or active.get("number") or 0),
                    "model": model,
                    "startedAt": active.get("llmReviewStartedAt"),
                    "completedAt": failed_at,
                    "durationSeconds": duration,
                    "inputSignature": signature,
                    "modelOutput": model_output,
                    "error": str(error)[:500],
                    "previousRuns": list(existing.get("previousRuns") or []) if "existing" in locals() and isinstance(existing.get("previousRuns"), list) else [],
                }
                write_json_artifact(llm_review_result_path(book, int(active.get("sequence") or active.get("number") or 0)), failure_artifact)
        stage.update({"status": "warning", "error": str(error)[:500], "detail": "LLM Review stopped at the first failed chapter; completed proposals remain safe."})
        pipeline.update({"status": "warning", "phase": "complete", "message": "LLM Review needs attention.", "updatedAt": utc_now()})
    finally:
        write_pipeline(book, pipeline)
        PIPELINE_THREADS.pop(book_id, None)
        PIPELINE_CANCEL_EVENTS.pop(book_id, None)


def whole_book_llm_review_schema() -> dict[str, object]:
    finding = {
        "type": "object",
        "properties": {
            "title": {"type": "string", "minLength": 1},
            "synthesis": {"type": "string", "minLength": 1},
            "significance": {"type": "string", "minLength": 1},
        },
        "required": ["title", "synthesis", "significance"],
    }
    priority = {
        "type": "object",
        "properties": {
            "title": {"type": "string", "minLength": 1},
            "rationale": {"type": "string", "minLength": 1},
            "scope": {"type": "string", "minLength": 1},
            "priority": {"type": "string", "enum": ["low", "normal", "high"]},
        },
        "required": ["title", "rationale", "scope", "priority"],
    }
    audience = {
        "type": "object",
        "properties": {
            "reader": {"type": "string", "minLength": 1},
            "fit": {"type": "string", "minLength": 1},
            "caution": {"type": "string"},
        },
        "required": ["reader", "fit", "caution"],
    }
    return {
        "type": "object",
        "properties": {
            "overall_assessment": {"type": "string", "minLength": 1},
            "strengths": {"type": "array", "items": finding},
            "risks": {"type": "array", "items": finding},
            "editorial_priorities": {"type": "array", "items": priority},
            "likely_readers": {"type": "array", "items": audience},
            "commercial_positioning": {"type": "string", "minLength": 1},
        },
        "required": ["overall_assessment", "strengths", "risks", "editorial_priorities", "likely_readers", "commercial_positioning"],
    }


def whole_book_llm_review_inputs(pipeline: dict[str, object]) -> list[dict[str, object]]:
    inputs: list[dict[str, object]] = []
    for index, chapter in enumerate(pipeline.get("chapters", []), start=1):
        if strip_markdown_heading(chapter.get("title")).casefold() == "front matter" or chapter.get("llmReviewStatus") != "complete":
            continue
        review = chapter.get("llmReview") if isinstance(chapter.get("llmReview"), dict) else {}
        dimensions = {
            key: {
                "score": item.get("score"),
                "applicable": item.get("applicable", True),
                "rationale": item.get("rationale"),
            }
            for key, item in (review.get("dimensions") or {}).items()
            if isinstance(item, dict)
        }
        inputs.append({
            "chapter": index,
            "title": strip_markdown_heading(chapter.get("chapterTitle") or chapter.get("title")),
            "editorialSummary": review.get("editorialSummary") or review.get("chapterAssessment"),
            "strengths": [*(review.get("editorialStrengths") or []), *(review.get("commercialStrengths") or [])],
            "risks": review.get("commercialRisks") or [],
            "likelyReaders": review.get("likelyReaders") or [],
            "dimensions": dimensions,
            "materialConcerns": [item.get("comment") for item in (review.get("editorialProposals") or []) if isinstance(item, dict) and item.get("comment")],
            "softLeads": [item.get("comment") for item in (review.get("rejectedCandidates") or []) if isinstance(item, dict) and item.get("comment") and item.get("status") not in {"dismissed", "promoted", "accepted"}],
        })
    return inputs


def synthesize_whole_book_llm_review(pipeline: dict[str, object], model: str, cancel_event: threading.Event | None, run_key: str) -> tuple[dict[str, object], int]:
    inputs = whole_book_llm_review_inputs(pipeline)
    prompt = f"""Act as a senior developmental editor synthesizing completed chapter-level assessments into one whole-book editorial view.

This is synthesis, not concatenation. Identify durable patterns across the book, merge repetition, reconcile contradictions, distinguish isolated chapter effects from book-wide tendencies, and prioritize only claims that matter at manuscript scale. Do not walk chapter by chapter. Do not mention chapter numbers or count occurrences unless location is indispensable to the overall conclusion. Treat soft leads as possibilities, not facts. Do not predict sales or manufacture criticism merely to fill a category. Empty arrays are acceptable when the evidence does not support a claim.

Return:
- one concise overall assessment of the book as a reading experience;
- synthesized strengths worth preserving;
- synthesized risks or weaknesses, with their likely reader or market significance;
- a short, ranked set of whole-book editorial priorities;
- reconciled likely-reader groups;
- cautious commercial positioning based only on the supplied assessments.

Completed chapter assessments:
{json.dumps(inputs, ensure_ascii=False)}
"""
    raw, _ = run_structured_model(prompt, model, whole_book_llm_review_schema(), cancel_event, f"{run_key}:whole-review")
    result = {
        "schema": WHOLE_BOOK_LLM_REVIEW_PROMPT_VERSION,
        "overallAssessment": str(raw.get("overall_assessment") or "").strip(),
        "strengths": raw.get("strengths") if isinstance(raw.get("strengths"), list) else [],
        "risks": raw.get("risks") if isinstance(raw.get("risks"), list) else [],
        "editorialPriorities": raw.get("editorial_priorities") if isinstance(raw.get("editorial_priorities"), list) else [],
        "likelyReaders": raw.get("likely_readers") if isinstance(raw.get("likely_readers"), list) else [],
        "commercialPositioning": str(raw.get("commercial_positioning") or "").strip(),
        "sourceChapterCount": len(inputs),
    }
    return result, len(prompt)


def run_whole_book_llm_review_pipeline(book_id: str) -> None:
    book = find_book(book_id)
    if not book or not book.get("llmReviewEnabled"):
        return
    pipeline = add_pipeline_progress(load_pipeline(book))
    ensure_llm_review_stages(book, pipeline)
    stages = {str(stage.get("id") or ""): stage for stage in pipeline.get("stages", [])}
    stage = stages.get("whole-book-llm-review", {})
    dependencies = list(PIPELINE_STAGE_DEPENDENCIES["whole-book-llm-review"])
    input_signature = stage_rollup_input_signature(pipeline, "review")
    if not input_signature or not pipeline_stage_ready(pipeline, "whole-book-llm-review"):
        pipeline["wholeBookLlmReview"] = {**(pipeline.get("wholeBookLlmReview") if isinstance(pipeline.get("wholeBookLlmReview"), dict) else {}), "status": "blocked", "dependsOn": dependencies, "detail": "Waiting for every chapter LLM Review to finish."}
        stage.update({"status": "blocked", "dependsOn": dependencies, "detail": pipeline["wholeBookLlmReview"]["detail"]})
        write_pipeline(book, pipeline)
        return
    settings = load_settings()
    available = ollama_status()
    models = available["models"] if available["running"] else []
    model = effective_primary_model(models, settings)
    cancel_event = PIPELINE_CANCEL_EVENTS.setdefault(book_id, threading.Event())
    started_at = utc_now()
    started = time.monotonic()
    reset_inactive_whole_book_runs(pipeline, "whole-llm-review")
    previous_result = latest_completed_rollup_result(pipeline, "wholeBookLlmReview", "wholeBookLlmReviewRuns")
    pipeline["wholeBookLlmReview"] = {"status": "running", "model": model, "startedAt": started_at, "inputSignature": input_signature, "dependsOn": dependencies, "detail": "Synthesizing chapter reviews into one whole-book editorial judgment.", **({"previousResult": previous_result} if previous_result else {})}
    stage.update({"status": "running", "model": model, "startedAt": started_at, "dependsOn": dependencies, "detail": pipeline["wholeBookLlmReview"]["detail"]})
    pipeline.update({"status": "running", "phase": "whole-llm-review", "message": "Synthesizing the whole-book LLM Review…", "updatedAt": utc_now()})
    write_pipeline(book, pipeline)
    try:
        if not model:
            raise ValueError("Assign or install the primary reader before synthesizing the whole-book LLM Review.")
        synthesis, input_characters = synthesize_whole_book_llm_review(pipeline, model, cancel_event, book_id)
        completed_at = utc_now()
        duration = round(time.monotonic() - started, 1)
        record = {**synthesis, "status": "complete", "model": model, "startedAt": started_at, "completedAt": completed_at, "durationSeconds": duration, "inputCharacters": input_characters, "inputSignature": input_signature, "dependsOn": dependencies, "detail": "Synthesized from every current chapter LLM Review."}
        pipeline["wholeBookLlmReview"] = record
        stage.update({"status": "complete", "model": model, "startedAt": started_at, "completedAt": completed_at, "durationSeconds": duration, "detail": record["detail"]})
        pipeline.update({"status": "complete", "phase": "complete", "message": "The whole-book LLM Review is ready.", "updatedAt": utc_now()})
    except PipelineCancelled:
        pipeline["wholeBookLlmReview"] = {"status": "ready", "model": model, "inputSignature": input_signature, "dependsOn": dependencies, "detail": "Stopped before whole-book review synthesis finished."}
        stage.update({"status": "pending", "detail": pipeline["wholeBookLlmReview"]["detail"]})
        pipeline.update({"status": "ready", "phase": "ready", "message": "The whole-book LLM Review is ready to synthesize.", "updatedAt": utc_now()})
    except Exception as error:
        duration = round(time.monotonic() - started, 1)
        pipeline["wholeBookLlmReview"] = {"status": "failed", "model": model, "startedAt": started_at, "completedAt": utc_now(), "durationSeconds": duration, "inputSignature": input_signature, "error": str(error)[:500], "dependsOn": dependencies, "detail": "Whole-book review synthesis failed; chapter reviews remain safe.", **({"previousResult": previous_result} if previous_result else {})}
        stage.update({"status": "failed", "error": str(error)[:500], "completedAt": utc_now(), "durationSeconds": duration, "detail": pipeline["wholeBookLlmReview"]["detail"]})
        pipeline.update({"status": "warning", "phase": "complete", "message": "The whole-book LLM Review needs another try.", "updatedAt": utc_now()})
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
    settings = load_settings()
    available = ollama_status()
    models = available["models"] if available["running"] else []
    model = effective_primary_model(models, settings)
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


def dossier_question_is_specific(value: object) -> bool:
    """Keep questions that name an actual unresolved narrative pressure."""
    question = re.sub(r"\s+", " ", str(value or "")).strip()
    if not question:
        return False
    return not any(re.match(pattern, question, re.I) for pattern in (
        r"^what is the relationship between .+ and .+\??$",
        r"^what happens next\??$",
        r"^what does this mean\??$",
        r"^why is this important\??$",
        r"^who is .+\??$",
    ))


def character_promise_is_supported(evidence: object) -> bool:
    """Require an actual commitment in the cited words, not a schema-filling guess."""
    return bool(re.search(
        r"\b(?:promise(?:d|s)?|swear|swore|vow(?:ed|s)?|pledge(?:d|s)?|shall|will|would|intend(?:ed|s)?\s+to|mean(?:t|s)?\s+to|going\s+to)\b",
        str(evidence or ""), re.I,
    ))


def analyze_chunk_dossier(
    chunk: dict[str, object], model: str, cancel_event: threading.Event | None = None,
    run_key: str = "", canonical_chapter_text: str = "",
    precomputed_result: dict[str, object] | None = None,
) -> dict[str, object]:
    front_matter = is_front_matter(chunk, "chapterLabel")
    material_guidance = front_matter_analysis_guidance("dossier") if front_matter else "This is narrative manuscript material; apply the dossier fields normally."
    text = str(chunk.get("text") or "")
    if precomputed_result is None:
        text = text[:45_000]
    prompt = f"""Build an evidence-preserving editorial dossier for this manuscript excerpt.
Return JSON with: synopsis (non-empty string); facts, events, entities, locations, current_times, promises, and timeline_observations (arrays of evidence-linked claim objects); questions (an array of strings); evidence (an array of evidence references); and question_details (an array of objects).
Every claim object contains claim, subject, and evidence_ref. Copy a short exact source quotation into evidence_ref and use the grammatical actor as subject. If a first-person narrator says "my father," the subject is the narrator's father—not another named character's father. Do not turn a character's speculation into objective fact. Preserve the source's relation strength: observation is not diagnosis; proximity or sequence is not causation; unease is not proof of hostility; an arrival is not an external threat merely because the chapter is tense; and a character's reaction is not hidden conflict when nearby text supplies a benign explanation. Use "suggests" or "the character believes" for warranted inference and reserve cause, source, diagnosis, proves, validates, confirms, threat, and motive for relations the quoted words establish. Apply this discipline to the synopsis as well as the claim arrays. Check negative assertions especially: never write "no," "not," "never," or "without" unless the cited source establishes that polarity. Do not announce that you will follow these instructions or promise to ask questions later; actually fill the evidence-linked form.
Entities should name people, organizations, creatures, significant objects, and concepts. Locations should separately name every physical place or setting present or explicitly discussed. Current_times should describe when the scene itself occurs, including date, season, time of day, elapsed-story time, or relation to earlier events when stated or strongly supported.
Timeline_observations should capture temporal evidence that connects this excerpt to events elsewhere: event order, elapsed durations, deadlines, flashbacks, remembered events, simultaneity, contradictions, and uncertainty. Keep these distinct from current_times, which describe the excerpt's present scene.
Promise objects additionally contain promise_type, exactly "character" or "story". A character promise requires an actual commitment in the quoted source—such as promises, will, shall, vows, or intends—not merely an action the model thinks would be useful. A story promise requires a concrete setup or withheld answer in the source. Identify the promiser or the story/narration as subject.
Evidence entries must include one supplied passage ID, the printed character start and end, and a short exact quote copied from that passage. These redundant coordinates are triangulated against the canonical source; unanchorable evidence is discarded. Do not invent facts or resolve uncertainty.

Questions must be concrete enough to track later. Include unresolved motivation, causal bridges, concealed knowledge, conflicting goals, relationship consequences, moral or thematic pressure, implied promises, and ambiguities that materially change how the scene can be understood. Every question must name the exact action, revelation, contradiction, image, dialogue, or change that earned it. Reject generic discussion prompts and questions already answered in this excerpt. Do not manufacture questions merely to fill categories.

Do not emit bare prompts such as "What is the relationship between X and Y?", "Who is X?", "What happens next?", or "What does this mean?" A relationship question must name the specific change, contradiction, concealment, or choice that remains unresolved. If the excerpt already establishes the relationship or identity, record it as a fact instead of asking about it.

Each question_details object must contain question, family, evidence, evidence_ref, why_it_matters, and promises_answer. The question must exactly match an entry in questions. Family must be exactly one of: {', '.join(QUESTION_FAMILIES)}. Evidence is a short exact quotation or precise trigger. evidence_ref contains its supplied passage ID, printed character start and end, and copied quote. promises_answer is true only when the manuscript appears to owe the reader an eventual answer.

Material-specific instructions:
{material_guidance}

Chapter: {chunk.get('chapterLabel')}
Chapter title: {chunk.get('chapterTitle') or 'Not stated'}
{manuscript_location_prompt(chunk)}

Canonical source passages:
{evidence_passage_prompt(text)}
"""
    result = precomputed_result
    if result is None:
        result, _ = run_structured_model(prompt, model, chapter_dossier_schema(), cancel_event, run_key)
    synopsis = str(result.get("synopsis") or "").strip()
    if not synopsis:
        raise ValueError("The model returned a dossier without a synopsis.")
    question_details = normalize_question_details(result.get("question_details"))
    question_details = [item for item in question_details if dossier_question_is_specific(item.get("question"))]

    def canonical_anchor(value: object) -> dict[str, object] | None:
        """Resolve against the model input, then relocate into reader-visible text."""
        chunk_anchor = resolve_source_evidence(text, value)
        if not chunk_anchor:
            return None
        if not canonical_chapter_text:
            return chunk_anchor
        chapter_anchor = resolve_source_evidence(canonical_chapter_text, {"quote": chunk_anchor["quote"]})
        if not chapter_anchor:
            return None
        chapter_anchor["chunkCharacterStart"] = chunk_anchor["characterStart"]
        chapter_anchor["chunkCharacterEnd"] = chunk_anchor["characterEnd"]
        chapter_anchor["anchorSource"] = "canonical-chapter"
        return chapter_anchor

    evidence_anchors = [anchor for item in result.get("evidence", []) if (anchor := canonical_anchor(item))] if isinstance(result.get("evidence"), list) else []
    normalized = {"synopsis": synopsis, "questions": [str(item).strip() for item in result.get("questions", []) if str(item).strip()] if isinstance(result.get("questions"), list) else [], "evidence": [str(item["quote"]) for item in evidence_anchors], "evidenceAnchors": evidence_anchors}
    claim_records: list[dict[str, object]] = []
    for kind in ("facts", "events", "entities", "locations", "current_times", "promises", "timeline_observations"):
        values: list[str] = []
        for item in result.get(kind, []) if isinstance(result.get(kind), list) else []:
            if isinstance(item, str):
                # Compatibility with older saved/model fixtures. New schema
                # responses must use the evidence-linked object form.
                if item.strip():
                    values.append(item.strip())
                continue
            if not isinstance(item, dict):
                continue
            claim = str(normalized_model_field(item, "claim", "fact", "text") or "").strip()
            subject = str(normalized_model_field(item, "subject", "actor", "entity") or "").strip()
            anchor = canonical_anchor(normalized_model_field(item, "evidence ref", "evidence_ref", "evidence"))
            promise_type = str(normalized_model_field(item, "promise type", "promise_type") or "").strip().casefold()
            if not claim or not subject or not anchor or not claim_polarity_is_supported(claim, anchor.get("quote")) or not claim_relation_is_supported(claim, anchor.get("quote")):
                continue
            if kind == "promises" and promise_type == "character" and not character_promise_is_supported(anchor.get("quote")):
                continue
            record = {"kind": kind, "claim": claim, "subject": subject, "evidence": anchor["quote"], "evidenceAnchor": anchor}
            if kind == "promises":
                record["promiseType"] = promise_type if promise_type in {"character", "story"} else "story"
            claim_records.append(record)
            values.append(claim)
        normalized[kind] = values
    normalized["claimRecords"] = claim_records
    normalized["questions"] = [item for item in normalized["questions"] if dossier_question_is_specific(item)]
    if "question_details" in result:
        raw_details = {str(item.get("question") or ""): item for item in result.get("question_details", []) if isinstance(item, dict)}
        for detail in question_details:
            raw = raw_details.get(str(detail["question"]), {})
            anchor = canonical_anchor(raw.get("evidence_ref") or raw.get("evidence"))
            if anchor:
                detail["evidence"] = anchor["quote"]
                detail["evidenceAnchor"] = anchor
        if question_details:
            normalized["questions"] = [str(item["question"]) for item in question_details]
        normalized.update({"questionDetails": question_details, "promptVersion": DOSSIER_PROMPT_VERSION})
    if front_matter:
        # Suggestive labels are not events, reader contracts, or chronology.
        for field in ("events", "questions", "promises", "current_times", "timeline_observations"):
            normalized[field] = []
        normalized["questionDetails"] = []
        normalized["analysisMode"] = "front-matter-structural"
    return normalized


def analyze_chunk_dossier_resilient(
    chunk: dict[str, object],
    model: str,
    cancel_event: threading.Event | None = None,
    run_key: str = "",
    canonical_chapter_text: str = "",
    attempts: int = 2,
    retry_delay: float = 0.75,
) -> dict[str, object]:
    """Retry one malformed or interrupted dossier response and retain why."""
    failures: list[dict[str, object]] = []
    for attempt in range(1, max(1, attempts) + 1):
        try:
            dossier = analyze_chunk_dossier(chunk, model, cancel_event, run_key, canonical_chapter_text)
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
    preferred = configured_primary_model(settings)
    model = preferred if preferred in models else effective_primary_model(models, settings)
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
                chapter_source = load_chapter_source(book, int(visible.get("chapterSequence") or 0))
                canonical_chapter_text = str(chapter_source.get("text") or "") if chapter_source else ""
                dossier = analyze_chunk_dossier_resilient(
                    artifact, model, cancel_event, book_id,
                    canonical_chapter_text=canonical_chapter_text,
                )
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


def local_executable(name: str) -> str | None:
    """Find local tools even when a GUI launcher supplies a minimal PATH."""
    if found := shutil.which(name):
        return found
    candidates = {
        "brew": ("/opt/homebrew/bin/brew", "/usr/local/bin/brew"),
        "uv": ("/opt/homebrew/bin/uv", "/usr/local/bin/uv"),
        "ollama": (
            "/opt/homebrew/bin/ollama",
            "/usr/local/bin/ollama",
            "/Applications/Ollama.app/Contents/Resources/ollama",
        ),
    }
    return next((path for path in candidates.get(name, ()) if Path(path).is_file() and os.access(path, os.X_OK)), None)


def machine_readiness(ollama: dict[str, object] | None = None) -> dict[str, object]:
    """Return actionable host checks without confusing unknown with failure."""
    system = platform.system()
    machine = platform.machine()
    memory_gib = physical_memory_gib()
    python_version = platform.python_version()
    python_supported = sys.version_info >= (3, 11)
    pip_available = importlib.util.find_spec("pip") is not None
    uv_available = local_executable("uv") is not None
    ollama = ollama or ollama_status()
    ollama_version = str(ollama.get("version") or "")
    ollama_installed = bool(ollama.get("installed"))
    ollama_running = bool(ollama.get("running"))
    brew_path = local_executable("brew") if system == "Darwin" else None
    brew_available = brew_path is not None
    brew_version = ""
    if brew_available:
        try:
            brew_version = subprocess.run([brew_path, "--version"], capture_output=True, text=True, timeout=5, check=True).stdout.splitlines()[0].strip()
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
        {"id": "ollama", "label": "Ollama runtime", "status": "ready" if ollama_running else "repairable" if brew_available else "blocked", "value": f"Ollama {ollama_version}" if ollama_version else "Running (version unavailable)" if ollama_running else "Not installed or version unavailable", "detail": "Ollama is serving Bookinator's local models." if ollama_running else "Bookinator requires a running Ollama service for local model analysis.", "action": "update-ollama" if brew_available and not ollama_installed and not ollama_running else "", "instructions": "ollama" if not brew_available and not ollama_running else ""},
        {"id": "package-installer", "label": "Library installer", "status": "ready" if pip_available or uv_available else "warning", "value": "uv" if uv_available else "pip" if pip_available else "Missing", "detail": "Bookinator can install its managed Python components." if pip_available or uv_available else "Automatic repair of Python components is unavailable until uv or pip is installed.", "instructions": "package-installer" if not pip_available and not uv_available else ""},
        {"id": "storage", "label": "Working storage", "status": "warning" if not free_disk_gib else "ready" if free_disk_gib >= 10 else "blocked", "value": f"{free_disk_gib:g} GB free" if free_disk_gib else "Unknown", "detail": "At least 10 GB of working headroom is required in addition to model downloads." if free_disk_gib else "Bookinator could not measure free space on its data volume.", "instructions": "storage" if not free_disk_gib or free_disk_gib < 10 else ""},
        {"id": "pdf-reader", "label": "Document reader", "status": "ready" if pdf_reader_ready() else "repairable" if pip_available or uv_available else "blocked", "value": "PyMuPDF ready" if pdf_reader_ready() else "PyMuPDF missing", "detail": "PDF and normalized manuscript pages can be read locally." if pdf_reader_ready() else "Bookinator needs its local document reader for manuscript ingestion.", "action": "install-pdf-reader" if not pdf_reader_ready() and (pip_available or uv_available) else "", "instructions": "package-installer" if not pdf_reader_ready() and not (pip_available or uv_available) else ""},
    ]
    blocked = sum(1 for check in checks if check["status"] == "blocked")
    return {"status": "blocked" if blocked else "warning" if any(check["status"] in {"warning", "repairable"} for check in checks) else "ready", "blockedCount": blocked, "checks": checks}


def recommended_roles(memory_gib: float) -> dict[str, str]:
    return {
        "primary": "qwen3.8:27b",
        # Preserve the proven small intake recommendation until the recorded
        # Qwen 2.5 versus 3.8 intake benchmark establishes a better choice.
        "fast": "qwen2.5:7b",
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
    if uv := local_executable("uv"):
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


def gliner_model_status() -> dict[str, object]:
    """Report the isolated GLiNER runtime and pinned product checkpoint."""
    runtime = ROOT / ".venv-gliner" / "bin" / "python"
    runner = ROOT / "tools" / "gliner_chapter_spike.py"
    package_files = (ROOT / ".venv-gliner" / "lib").glob("python*/site-packages/gliner2/__init__.py")
    runtime_ready = runtime.is_file() and runner.is_file() and any(package_files)
    cache_root = Path(os.environ.get("HF_HOME") or (Path.home() / ".cache" / "huggingface"))
    model_root = cache_root / "hub" / "models--fastino--gliner2.5-small-v1" / "snapshots"
    cached = model_root.is_dir() and any((snapshot / "config.json").is_file() for snapshot in model_root.iterdir() if snapshot.is_dir())
    return {
        "runtime": runtime_ready,
        "model": cached,
        "ready": runtime_ready and cached,
        "modelId": GLINER_MODEL_ID,
        "runtimeError": "" if runtime_ready else "The isolated GLiNER runtime is incomplete.",
        "provider": "isolated-python-hugging-face",
    }


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


def configured_primary_model(settings: dict[str, str]) -> str:
    """Resolve the one deliberate model used for substantive reading work.

    The legacy keys remain fallbacks so an existing installation transitions
    without silently forgetting its previous assignment.
    """
    return str(settings.get("primaryModel") or settings.get("readerModel") or settings.get("tagsModel") or "")


def configured_fast_model(settings: dict[str, str]) -> str:
    """Resolve the small model used for intake and other inexpensive utilities."""
    return str(settings.get("fastModel") or settings.get("intakeModel") or "")


def effective_primary_model(models: list[str], settings: dict[str, str] | None = None) -> str:
    configured = configured_primary_model(settings or load_settings())
    return configured if configured in models else str(choose_primary_model(models) or "")


def effective_fast_model(models: list[str], settings: dict[str, str] | None = None) -> str:
    configured = configured_fast_model(settings or load_settings())
    return configured if configured in models else str(choose_metadata_model(models) or "")


def save_settings(settings: dict[str, str]) -> None:
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_PATH.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")


def infer_manuscript_identity(text: str, metadata: dict[str, str], models: list[str], configured_model: str = "", metadata_authoritative: bool = False) -> dict[str, str]:
    authoritative_title = str(metadata.get("title") or "").strip() if metadata_authoritative else ""
    authoritative_author = str(metadata.get("author") or "").strip() if metadata_authoritative else ""
    if authoritative_title and authoritative_author:
        return {
            "title": authoritative_title,
            "author": authoritative_author,
            "abbreviation": fallback_title_mark(authoritative_title),
        }
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
    installed = local_executable("ollama") is not None
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
    role_recommendations = recommended_roles(memory_gib)
    available_models = ollama["models"] if ollama["running"] else []
    assignments = {
        "primary": effective_primary_model(available_models, settings),
        "fast": effective_fast_model(available_models, settings),
    }
    return {
        "platform": platform.system(),
        "architecture": machine,
        "memoryGiB": memory_gib,
        "appleSilicon": platform.system() == "Darwin" and machine == "arm64",
        "python": platform.python_version(),
        "readiness": machine_readiness(ollama),
        "pdfReader": pdf_reader_ready(),
        "emotionModel": emotion_model_status(),
        "glinerModel": gliner_model_status(),
        "ollama": ollama,
        "models": {
            "intake": assignments["fast"],
            "recommended": assignments["fast"],
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
    wanted = model.casefold()
    assignments: list[str] = []
    effective_roles = {
        "primary": effective_primary_model(available, settings),
        "fast": effective_fast_model(available, settings),
    }
    for role, label in MODEL_ROLES.items():
        effective = effective_roles[role]
        if effective.casefold() == wanted:
            assignments.append(label)
    return assignments


class BookinatorHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, directory=str(APP_ROOT), **kwargs)

    def end_headers(self) -> None:
        if not self.path.startswith("/api/"):
            self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, message: str, *args: object) -> None:
        print(f"[Bookinator]: {message % args}")

    def translate_path(self, path: str) -> str:
        route_path = urllib.parse.unquote(urllib.parse.urlsplit(path).path)
        if route_path == "/docs" or route_path.startswith("/docs/"):
            relative = route_path.removeprefix("/docs").lstrip("/")
            candidate = (DOCS_ROOT / relative).resolve()
            if candidate == DOCS_ROOT.resolve() or DOCS_ROOT.resolve() in candidate.parents:
                return str(candidate)
        if route_path == "/commons/@inator/ui" or route_path.startswith("/commons/@inator/ui/"):
            relative = route_path.removeprefix("/commons/@inator/ui").lstrip("/") or "index.js"
            candidate = (COMMONS_UI_ROOT / relative).resolve()
            if candidate.suffix in {".css", ".js"} and COMMONS_UI_ROOT.resolve() in candidate.parents:
                return str(candidate)
        if route_path == "/commons/@inator/engine" or route_path.startswith("/commons/@inator/engine/"):
            relative = route_path.removeprefix("/commons/@inator/engine").lstrip("/") or "index.js"
            candidate = (COMMONS_ENGINE_ROOT / relative).resolve()
            if candidate.suffix == ".js" and COMMONS_ENGINE_ROOT.resolve() in candidate.parents:
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
            books: list[dict[str, object]] = []
            pipeline_records: list[tuple[dict[str, object], dict[str, object]]] = []
            for record in load_library_records():
                pipeline = add_pipeline_progress(pipeline_for_client(str(record.get("id") or ""), library_pipeline_snapshot(record)))
                book = enrich_book(record, pipeline)
                books.append(book)
                pipeline_records.append((book, pipeline))
            self.send_json({"books": [book_for_library_client(book) for book in books], "pipeline": global_pipeline_state(books, pipeline_records)})
            return
        if self.path == "/api/library/pipeline":
            # Workspace polling needs queue truth, not every book record and
            # its embedded cover image. Keep this response deliberately small.
            self.send_json({"pipeline": global_pipeline_state()})
            return
        telemetry_match = re.fullmatch(r"/api/books/([A-Za-z0-9_-]{8,80})/model-telemetry", route.path)
        if telemetry_match:
            book_id = telemetry_match.group(1)
            if not find_book(book_id):
                self.send_json({"error": "Book not found."}, HTTPStatus.NOT_FOUND)
                return
            self.send_json({"telemetry": model_response_telemetry(book_id)})
            return
        icon_match = re.fullmatch(r"/api/books/([A-Za-z0-9_-]{8,80})/icon", route.path)
        if icon_match:
            book = find_book(icon_match.group(1))
            icon = book.get("icon") if isinstance(book, dict) and isinstance(book.get("icon"), dict) else {}
            value = str(icon.get("value") or "")
            match = re.fullmatch(r"data:(image/(?:png|jpeg|webp|gif));base64,([A-Za-z0-9+/=\s]+)", value, re.IGNORECASE)
            if not match:
                self.send_error(HTTPStatus.NOT_FOUND, "Book icon not found")
                return
            try:
                image = base64.b64decode(match.group(2), validate=True)
            except (ValueError, binascii.Error):
                self.send_error(HTTPStatus.NOT_FOUND, "Book icon is invalid")
                return
            etag = hashlib.sha256(image).hexdigest()[:24]
            if self.headers.get("If-None-Match") == f'"{etag}"':
                self.send_response(HTTPStatus.NOT_MODIFIED)
                self.send_header("ETag", f'"{etag}"')
                self.send_header("Cache-Control", "private, max-age=300")
                self.end_headers()
                return
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", match.group(1).lower())
            self.send_header("Content-Length", str(len(image)))
            self.send_header("ETag", f'"{etag}"')
            self.send_header("Cache-Control", "private, max-age=300")
            self.end_headers()
            self.wfile.write(image)
            return
        if route.path == "/api/library/export":
            requested = {item for item in urllib.parse.parse_qs(route.query).get("ids", [""])[0].split(",") if item}
            books = [book for book in load_library() if not requested or str(book.get("id")) in requested]
            if not books:
                self.send_json({"error": "Select at least one book to export."}, HTTPStatus.BAD_REQUEST)
                return
            bundle = build_library_bundle(books)
            filename = library_bundle_filename(books)
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/vnd.bookinator.project+zip")
            self.send_header("Content-Length", str(len(bundle)))
            self.send_header("Content-Disposition", f"attachment; filename*=UTF-8''{urllib.parse.quote(filename)}")
            self.send_header("Cache-Control", "private, no-store")
            self.end_headers()
            self.wfile.write(bundle)
            return
        reports_match = re.fullmatch(r"/api/books/([A-Za-z0-9_-]{8,80})/exports", route.path)
        if reports_match:
            if not find_book(reports_match.group(1)):
                self.send_json({"error": "Book not found."}, HTTPStatus.NOT_FOUND)
                return
            self.send_json({"exports": load_saved_reports(reports_match.group(1))})
            return
        annotations_match = re.fullmatch(r"/api/books/([A-Za-z0-9_-]{8,80})/annotations", route.path)
        if annotations_match:
            book = find_book(annotations_match.group(1))
            if not book:
                self.send_json({"error": "Book not found."}, HTTPStatus.NOT_FOUND)
                return
            self.send_json({"schema": ANNOTATION_SCHEMA_VERSION, "annotations": load_annotations(book)})
            return
        reviewer_signoff_match = re.fullmatch(r"/api/books/([A-Za-z0-9_-]{8,80})/reviewer-signoff", route.path)
        if reviewer_signoff_match:
            book = find_book(reviewer_signoff_match.group(1))
            if not book:
                self.send_json({"error": "Book not found."}, HTTPStatus.NOT_FOUND)
                return
            self.send_json({"reviewerSignoff": load_reviewer_signoff(book)})
            return
        analysis_artifact_match = re.fullmatch(r"/api/books/([A-Za-z0-9_-]{8,80})/analysis/(chapter-reading|gliner|summary|dossier|emotion|tag|smell|context|llm-review|whole-summary|whole-dossier|whole-llm-review|stage)/([A-Za-z0-9_-]{1,80})/artifact", route.path)
        if analysis_artifact_match:
            book_id, kind, item_id = analysis_artifact_match.groups()
            book = find_book(book_id)
            if not book:
                self.send_json({"error": "Book not found."}, HTTPStatus.NOT_FOUND)
                return
            try:
                payload = analysis_run_artifact(book, kind, item_id)
            except LookupError as error:
                self.send_json({"error": str(error)}, HTTPStatus.NOT_FOUND)
                return
            except (ValueError, TypeError) as error:
                self.send_json({"error": str(error)}, HTTPStatus.BAD_REQUEST)
                return
            self.send_json(payload)
            return
        report_file_match = re.fullmatch(r"/api/books/([A-Za-z0-9_-]{8,80})/exports/([a-f0-9]{32})", route.path)
        if report_file_match:
            book_id, artifact_id = report_file_match.groups()
            record = next((item for item in load_saved_reports(book_id) if item.get("id") == artifact_id), None)
            if not record:
                self.send_json({"error": "That saved report is not available."}, HTTPStatus.NOT_FOUND)
                return
            extension = str(record.get("format") or "")
            if extension not in {"html", "pdf"}:
                self.send_json({"error": "That saved report record is invalid."}, HTTPStatus.NOT_FOUND)
                return
            path = saved_report_path(book_id, artifact_id, extension)
            if not path.is_file():
                self.send_json({"error": "That saved report file is missing."}, HTTPStatus.NOT_FOUND)
                return
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", str(record.get("mediaType") or "application/octet-stream"))
            self.send_header("Content-Length", str(path.stat().st_size))
            self.send_header("Content-Disposition", f"attachment; filename*=UTF-8''{urllib.parse.quote(str(record.get('filename') or path.name))}")
            self.send_header("Cache-Control", "private, no-store")
            self.end_headers()
            with path.open("rb") as report_file:
                shutil.copyfileobj(report_file, self.wfile)
            return
        chapter_source_match = re.fullmatch(r"/api/books/([A-Za-z0-9_-]{8,80})/chapters/(\d{1,5})/source", route.path)
        if chapter_source_match:
            book = find_book(chapter_source_match.group(1))
            chapter = load_chapter_source(book, int(chapter_source_match.group(2))) if book else None
            if not chapter:
                self.send_json({"error": "That saved chapter source is not available."}, HTTPStatus.NOT_FOUND)
                return
            if not source_has_fixed_pagination(book) and re.fullmatch(r"Pages\s+\d+[–-]\d+", str(chapter.get("title") or ""), re.IGNORECASE):
                chapter["title"] = "Entirety"
            annotations = [item for item in load_annotations(book) if int(item.get("chapterSequence") or 0) == int(chapter_source_match.group(2)) and item.get("status") != "archived"]
            self.send_json({"chapter": chapter, "annotations": annotations})
            return
        shadow_heading_match = re.fullmatch(r"/api/books/([A-Za-z0-9_-]{8,80})/debug/shadow-headings", route.path)
        if shadow_heading_match:
            book = find_book(shadow_heading_match.group(1))
            if not book:
                self.send_json({"error": "Book not found."}, HTTPStatus.NOT_FOUND)
                return
            try:
                self.send_json(shadow_heading_diagnostic(book))
            except FileNotFoundError as error:
                self.send_json({"error": str(error)}, HTTPStatus.NOT_FOUND)
            except (OSError, RuntimeError) as error:
                self.send_json({"error": str(error)}, HTTPStatus.INTERNAL_SERVER_ERROR)
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
            primary_model = configured_primary_model(load_settings())
            pipeline["configuredReaderModel"] = primary_model
            pipeline["configuredDossierModel"] = primary_model
            pipeline["configuredTagModel"] = primary_model
            pipeline["chapterMapWarnings"] = [
                *chapter_map_warnings(pipeline.get("chapters", []), pipeline.get("acceptedChapterLabelVariants", [])),
                *chapter_heading_report_warnings(pipeline.get("chapterHeadingReport", {})),
            ]
            pipeline["chapterMapSuspicious"] = bool(pipeline["chapterMapWarnings"])
            pipeline["reviewerSignoff"] = load_reviewer_signoff(book)
            pipeline = pipeline_for_client(pipeline_match.group(1), pipeline)
            pipeline["activity"] = pipeline_activity(book, pipeline)
            self.send_json(compact_pipeline_payload(add_pipeline_progress(pipeline)))
            return
        super().do_GET()

    def do_DELETE(self) -> None:  # noqa: N802
        route = urllib.parse.urlsplit(self.path)
        annotation_match = re.fullmatch(r"/api/books/([A-Za-z0-9_-]{8,80})/annotations/([A-Za-z0-9_-]{8,80})", route.path)
        if annotation_match:
            book = find_book(annotation_match.group(1))
            if not book:
                self.send_json({"error": "Book not found."}, HTTPStatus.NOT_FOUND)
                return
            try:
                deleted = delete_annotation(book, annotation_match.group(2))
            except LookupError:
                self.send_json({"deleted": True, "id": annotation_match.group(2), "alreadyDeleted": True})
                return
            self.send_json({"deleted": True, "id": deleted.get("id")})
            return
        report_match = re.fullmatch(r"/api/books/([A-Za-z0-9_-]{8,80})/exports/([a-f0-9]{32})", route.path)
        if not report_match:
            self.send_json({"error": "Not found."}, HTTPStatus.NOT_FOUND)
            return
        book_id, artifact_id = report_match.groups()
        with REPORTS_LOCK:
            records = load_saved_reports(book_id)
            record = next((item for item in records if item.get("id") == artifact_id), None)
            if not record:
                self.send_json({"error": "That saved report is not available."}, HTTPStatus.NOT_FOUND)
                return
            extension = str(record.get("format") or "")
            if extension not in {"html", "pdf"}:
                self.send_json({"error": "That saved report record is invalid."}, HTTPStatus.NOT_FOUND)
                return
            path = saved_report_path(book_id, artifact_id, extension)
            try:
                path.unlink(missing_ok=True)
                write_saved_reports(book_id, [item for item in records if item.get("id") != artifact_id])
            except OSError as error:
                self.send_json({"error": str(error) or "The report could not be deleted."}, HTTPStatus.INTERNAL_SERVER_ERROR)
                return
        self.send_json({"deleted": True, "id": artifact_id})

    def do_POST(self) -> None:  # noqa: N802
        global QUEUE_THREAD
        route = urllib.parse.urlsplit(self.path)
        if route.path == "/api/library/import-bundle":
            try:
                length = int(self.headers.get("Content-Length", "0") or 0)
                if length <= 0 or length > MAX_BUNDLE_BYTES:
                    raise ValueError("Bookinator packages must be between 1 byte and 1 GB.")
                raw_overrides = self.headers.get("X-Bookinator-Import-Titles", "")
                title_overrides = json.loads(raw_overrides) if raw_overrides else {}
                if not isinstance(title_overrides, dict) or not all(isinstance(key, str) and isinstance(value, str) for key, value in title_overrides.items()):
                    raise ValueError("The import title choices are invalid.")
                result = import_library_bundle(self.rfile.read(length), title_overrides)
            except ImportTitleCollision as error:
                self.send_json({"error": str(error), "code": "title-collision", "collisions": error.collisions}, HTTPStatus.CONFLICT)
                return
            except (OSError, ValueError, TypeError, zipfile.BadZipFile) as error:
                self.send_json({"error": str(error) or "The Bookinator package could not be imported."}, HTTPStatus.BAD_REQUEST)
                return
            self.send_json(result, HTTPStatus.CREATED)
            return
        reviewer_signoff_match = re.fullmatch(r"/api/books/([A-Za-z0-9_-]{8,80})/reviewer-signoff", route.path)
        if reviewer_signoff_match:
            book = find_book(reviewer_signoff_match.group(1))
            if not book:
                self.send_json({"error": "Book not found."}, HTTPStatus.NOT_FOUND)
                return
            try:
                length = int(self.headers.get("Content-Length", "0") or 0)
                if length <= 0 or length > 64 * 1024:
                    raise ValueError("Invalid reviewer sign-off request.")
                payload = json.loads(self.rfile.read(length))
                if not isinstance(payload, dict):
                    raise ValueError("Invalid reviewer sign-off request.")
                signoff = save_reviewer_signoff(book, payload)
            except (ValueError, TypeError, json.JSONDecodeError) as error:
                self.send_json({"error": str(error) or "Invalid reviewer sign-off request."}, HTTPStatus.BAD_REQUEST)
                return
            self.send_json({"saved": True, "reviewerSignoff": signoff})
            return
        proposal_match = re.fullmatch(r"/api/books/([A-Za-z0-9_-]{8,80})/llm-review/proposals/([a-f0-9]{32})", route.path)
        if proposal_match:
            book = find_book(proposal_match.group(1))
            if not book:
                self.send_json({"error": "Book not found."}, HTTPStatus.NOT_FOUND)
                return
            try:
                length = int(self.headers.get("Content-Length", "0") or 0)
                if length <= 0 or length > 16 * 1024:
                    raise ValueError("Invalid proposal decision request.")
                payload = json.loads(self.rfile.read(length))
                if not isinstance(payload, dict):
                    raise ValueError("Invalid proposal decision request.")
                result = decide_llm_review_proposal(book, proposal_match.group(2), str(payload.get("action") or ""), str(payload.get("category") or ""))
            except LookupError as error:
                self.send_json({"error": str(error)}, HTTPStatus.NOT_FOUND)
                return
            except (ValueError, TypeError, json.JSONDecodeError) as error:
                self.send_json({"error": str(error) or "Invalid proposal decision request."}, HTTPStatus.BAD_REQUEST)
                return
            self.send_json({"saved": True, **result})
            return
        candidate_match = re.fullmatch(r"/api/books/([A-Za-z0-9_-]{8,80})/llm-review/candidates/([0-9]{1,5})/([0-9]{1,3})", route.path)
        if candidate_match:
            book = find_book(candidate_match.group(1))
            if not book:
                self.send_json({"error": "Book not found."}, HTTPStatus.NOT_FOUND)
                return
            try:
                length = int(self.headers.get("Content-Length", "0") or 0)
                if length <= 0 or length > 16 * 1024:
                    raise ValueError("Invalid soft-lead decision request.")
                payload = json.loads(self.rfile.read(length))
                if not isinstance(payload, dict):
                    raise ValueError("Invalid soft-lead decision request.")
                result = decide_llm_review_candidate(book, int(candidate_match.group(2)), int(candidate_match.group(3)), str(payload.get("action") or ""), str(payload.get("category") or ""))
            except LookupError as error:
                self.send_json({"error": str(error)}, HTTPStatus.NOT_FOUND)
                return
            except (ValueError, TypeError, json.JSONDecodeError) as error:
                self.send_json({"error": str(error) or "That soft lead decision could not be saved."}, HTTPStatus.BAD_REQUEST)
                return
            self.send_json({"saved": True, **result})
            return
        annotation_match = re.fullmatch(r"/api/books/([A-Za-z0-9_-]{8,80})/annotations(?:/([A-Za-z0-9_-]{8,80}))?", route.path)
        if annotation_match:
            book = find_book(annotation_match.group(1))
            if not book:
                self.send_json({"error": "Book not found."}, HTTPStatus.NOT_FOUND)
                return
            try:
                length = int(self.headers.get("Content-Length", "0") or 0)
                if length <= 0 or length > 256 * 1024:
                    raise ValueError("Invalid annotation request.")
                payload = json.loads(self.rfile.read(length))
                if not isinstance(payload, dict):
                    raise ValueError("Invalid annotation request.")
                annotation = update_annotation(book, annotation_match.group(2), payload) if annotation_match.group(2) else create_annotation(book, payload)
            except LookupError as error:
                self.send_json({"error": str(error)}, HTTPStatus.NOT_FOUND)
                return
            except (ValueError, TypeError, json.JSONDecodeError) as error:
                self.send_json({"error": str(error) or "Invalid annotation request."}, HTTPStatus.BAD_REQUEST)
                return
            self.send_json({"saved": True, "annotation": annotation}, HTTPStatus.OK if annotation_match.group(2) else HTTPStatus.CREATED)
            return
        reports_match = re.fullmatch(r"/api/books/([A-Za-z0-9_-]{8,80})/exports", route.path)
        if reports_match:
            book_id = reports_match.group(1)
            if not find_book(book_id):
                self.send_json({"error": "Book not found."}, HTTPStatus.NOT_FOUND)
                return
            try:
                length = int(self.headers.get("Content-Length", "0") or 0)
                if length <= 0 or length > 50 * 1024 * 1024:
                    raise ValueError("Saved reports must be between 1 byte and 50 MB.")
                if self.headers.get("X-Bookinator-Privacy-Audit") != "passed":
                    raise ValueError("The report did not pass Bookinator's privacy audit.")
                media_type = str(self.headers.get("Content-Type") or "").split(";", 1)[0].strip().casefold()
                extension = {"text/html": "html", "application/pdf": "pdf"}.get(media_type)
                if not extension:
                    raise ValueError("Only Bookinator HTML and PDF reports can be saved here.")
                query = urllib.parse.parse_qs(route.query)
                filename = Path(query.get("filename", [f"bookinator-report.{extension}"])[0]).name
                if not filename.casefold().endswith(f".{extension}"):
                    filename += f".{extension}"
                sections = [item for item in query.get("sections", [""])[0].split(",") if item]
                content = self.rfile.read(length)
                artifact_id = uuid.uuid4().hex
                root = REPORTS_ROOT / book_id
                root.mkdir(parents=True, exist_ok=True)
                saved_report_path(book_id, artifact_id, extension).write_bytes(content)
                record = {"id": artifact_id, "filename": filename, "format": extension, "mediaType": media_type, "bytes": len(content), "createdAt": utc_now(), "sections": sections}
                with REPORTS_LOCK:
                    records = [record, *load_saved_reports(book_id)]
                    write_saved_reports(book_id, records)
            except (OSError, ValueError) as error:
                self.send_json({"error": str(error) or "The report could not be saved."}, HTTPStatus.BAD_REQUEST)
                return
            self.send_json({"export": record}, HTTPStatus.CREATED)
            return
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
                pauses = load_pipeline_task_pauses()
                if any(book_id in pauses for book_id in ids):
                    for book_id in ids:
                        pauses.pop(book_id, None)
                    save_pipeline_task_pauses(pauses)
                for book_id in ids:
                    with QUEUE_LOCK:
                        QUEUE_ACTIONS.pop(book_id, None)
                        remove_queue_action(book_id)
                    if event := PIPELINE_CANCEL_EVENTS.get(book_id):
                        event.set()
                self.send_json({"deleted": len(removed), "deletedIds": [str(book.get("id")) for book in removed], "cleanupWarnings": cleanup_warnings})
                return
            try:
                result = import_legacy_library_export(payload)
            except ImportTitleCollision as error:
                self.send_json({"error": str(error), "code": "title-collision", "collisions": error.collisions}, HTTPStatus.CONFLICT)
                return
            except (OSError, ValueError, TypeError) as error:
                self.send_json({"error": str(error) or "The library export could not be imported."}, HTTPStatus.BAD_REQUEST)
                return
            self.send_json(result, HTTPStatus.CREATED)
            return
        if route.path == "/api/library/pipeline/control":
            try:
                length = int(self.headers.get("Content-Length", "0") or 0)
                if length <= 0 or length > 256 * 1024:
                    raise ValueError("Invalid pipeline control request size.")
                intent = json.loads(self.rfile.read(length))
                if not isinstance(intent, dict):
                    raise ValueError("Invalid pipeline control request.")
                pipeline = apply_pipeline_control_intent(intent)
            except PipelineRevisionConflict as error:
                self.send_json({
                    "error": str(error), "code": "stale-pipeline-snapshot",
                    "snapshot": error.state["snapshot"], "pipeline": error.state,
                }, HTTPStatus.CONFLICT)
                return
            except (ValueError, TypeError, json.JSONDecodeError) as error:
                self.send_json({"error": str(error) or "Invalid pipeline control request."}, HTTPStatus.BAD_REQUEST)
                return
            self.send_json({"applied": True, "snapshot": pipeline["snapshot"], "pipeline": pipeline})
            return
        if route.path == "/api/library/pipeline/product-command":
            try:
                length = int(self.headers.get("Content-Length", "0") or 0)
                if length <= 0 or length > 256 * 1024:
                    raise ValueError("Invalid product command request size.")
                intent = json.loads(self.rfile.read(length))
                if not isinstance(intent, dict):
                    raise ValueError("Invalid product command request.")
                pipeline = apply_pipeline_product_command(intent)
            except PipelineRevisionConflict as error:
                self.send_json({
                    "error": str(error), "code": "stale-pipeline-snapshot",
                    "snapshot": error.state["snapshot"], "pipeline": error.state,
                }, HTTPStatus.CONFLICT)
                return
            except (ValueError, TypeError, json.JSONDecodeError) as error:
                self.send_json({"error": str(error) or "Invalid product command request."}, HTTPStatus.BAD_REQUEST)
                return
            self.send_json({"applied": True, "snapshot": pipeline["snapshot"], "pipeline": pipeline}, HTTPStatus.ACCEPTED)
            return
        start_over_match = re.fullmatch(r"/api/books/([A-Za-z0-9_-]{8,80})/pipeline/start-over", route.path)
        if start_over_match:
            book_id = start_over_match.group(1)
            book = find_book(book_id)
            if not book:
                self.send_json({"error": "Book not found."}, HTTPStatus.NOT_FOUND)
                return
            if not manuscript_metadata(str(book.get("manuscriptId") or "")).get("sourceAvailable"):
                self.send_json({"error": "Reconnect the source document before starting this pipeline over."}, HTTPStatus.CONFLICT)
                return
            pipeline = load_pipeline(book)
            if pipeline_worker_is_alive(book_id, pipeline) and not quiesce_pipeline_for_refresh(book_id, pipeline):
                self.send_json({"error": "Bookinator could not safely stop the active model response. Stop the queue, then try again."}, HTTPStatus.CONFLICT)
                return
            try:
                reset_book_pipeline(book)
                prioritize_pipeline_action(book_id, "prepare")
            except (OSError, ValueError) as error:
                self.send_json({"error": str(error) or "The pipeline could not be reset."}, HTTPStatus.BAD_REQUEST)
                return
            self.send_json({"startedOver": True, "bookId": book_id, "action": "prepare", "queueProtocol": 2}, HTTPStatus.ACCEPTED)
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
                sequence = int(payload.get("id") or 0) if kind not in {"whole-summary", "whole-llm-review"} else 0
            except (ValueError, TypeError, json.JSONDecodeError):
                self.send_json({"error": "Choose a valid analysis result to refresh."}, HTTPStatus.BAD_REQUEST)
                return
            whole_kind = kind in {"whole-summary", "whole-llm-review"}
            if not book or kind not in {"gliner", "summary", "dossier", "emotion", "tag", "smell", "context", "llm-review", "whole-summary", "whole-llm-review"} or (not whole_kind and sequence < 1):
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
            if action in PAUSABLE_PIPELINE_ACTIONS:
                set_pipeline_action_paused(book_id, action, False)
            queue_action = refresh_followup_action(action)
            prioritize_pipeline_action(book_id, queue_action)
            self.send_json({"refreshing": True, "kind": kind, "id": sequence, "status": "pending", "queueAction": queue_action, "interruptedActiveWork": interrupted_active_work}, HTTPStatus.ACCEPTED)
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
                if not chapter_map_review_ready(pipeline):
                    self.send_json({"error": "Wait for chapter detection to finish before approving this map."}, HTTPStatus.CONFLICT)
                    return
                warnings = [
                    *chapter_map_warnings(pipeline.get("chapters", []), pipeline.get("acceptedChapterLabelVariants", [])),
                    *chapter_heading_report_warnings(pipeline.get("chapterHeadingReport", {})),
                ]
                if warnings:
                    self.send_json({"error": "Resolve or rebuild the anomalous chapter headings before approving this map.", "warnings": warnings}, HTTPStatus.CONFLICT)
                    return
                decision_at = utc_now()
                pipeline.update({"chapterMapApproved": True, "chapterMapApprovedAt": decision_at, "chapterMapDecisionAt": decision_at, "analysisProvisional": False, "updatedAt": decision_at})
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
                pipeline["chapterMapApprovalAfterRebuild"] = bool(pipeline.get("chapterMapApprovalAfterRebuild") or pipeline.get("chapterMapApproved"))
                pipeline["chapterMapApproved"] = False
                pipeline["chapterMapDecisionAt"] = utc_now()
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
            invalid = [
                label for label in labels
                if label.casefold() not in candidates
                or int(candidates[label.casefold()].get("count") or 0) != 1
                or candidates[label.casefold()].get("classification", "unclassified") != "unclassified"
            ]
            if invalid:
                self.send_json({"error": f"Only a unique excluded heading can become a chapter variant: {', '.join(invalid)}"}, HTTPStatus.BAD_REQUEST)
                return
            pipeline["acceptedChapterLabelVariants"] = list(dict.fromkeys(labels))
            pipeline["chapterMapApprovalAfterRebuild"] = bool(pipeline.get("chapterMapApprovalAfterRebuild") or pipeline.get("chapterMapApproved"))
            pipeline["chapterMapApproved"] = False
            pipeline["chapterMapDecisionAt"] = utc_now()
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
            event = BOOK_PIPELINE_CANCEL_EVENTS.get(book_id) or PIPELINE_CANCEL_EVENTS.get(book_id)
            running = PIPELINE_THREADS.get(book_id)
            if not book or not event or not running or not running.is_alive():
                self.send_json({"error": "No analysis task is currently running for this book."}, HTTPStatus.CONFLICT)
                return
            event.set()
            cancel_active_model_response(book_id)
            # Do not race the worker's final cancellation checkpoint. The old
            # implementation wrote "paused" immediately; the worker then
            # overwrote it from stale in-memory state and began another stage.
            deadline = time.monotonic() + 8.0
            while time.monotonic() < deadline and pipeline_worker_is_alive(book_id, load_pipeline(book)):
                time.sleep(0.05)
            if pipeline_worker_is_alive(book_id, load_pipeline(book)):
                self.send_json({
                    "stopping": True, "stopped": False,
                    "message": "The active response is closing. No later chapter stage will begin.",
                }, HTTPStatus.ACCEPTED)
                return
            pipeline = load_pipeline(book)
            for chapter in pipeline.get("chapters", []):
                if chapter.get("status") == "running":
                    chapter.update({"status": "pending", "interruptedAt": utc_now(), "error": "Stopped before completion. Resume retries this chapter."})
                for prefix in ("gliner", "emotion", "tag", "smell"):
                    if chapter.get(f"{prefix}Status") == "running":
                        chapter.update({f"{prefix}Status": "pending", f"{prefix}Error": "Stopped before completion. Resume retries this chapter."})
                if chapter.get("contextStatus") == "running":
                    chapter.update({"contextStatus": "pending", "contextError": "Stopped before completion. Resume retries this chapter."})
                if chapter.get("llmReviewStatus") == "running":
                    chapter.update({"llmReviewStatus": "pending", "llmReviewError": "Stopped before completion. Resume retries this chapter."})
            for chunk in pipeline.get("chunks", []):
                if chunk.get("dossierStatus") == "running":
                    chunk.update({"dossierStatus": "pending", "dossierError": "Stopped before completion. Resume retries this chunk."})
                    try:
                        artifact = json.loads((chunk_artifacts_path(book) / f"{int(chunk.get('sequence')):04d}.json").read_text(encoding="utf-8"))
                        artifact.update({"dossierStatus": "pending", "dossierError": chunk["dossierError"]})
                        write_chunk_artifact(book, int(chunk.get("sequence")), artifact)
                    except (OSError, ValueError, TypeError, json.JSONDecodeError):
                        pass
            for stage in pipeline.get("stages", []):
                if stage.get("status") == "running":
                    stage.update({"status": "pending", "detail": "Stopped safely; Resume retries the interrupted work."})
            pipeline.update({"status": "paused", "phase": "paused", "stopRequested": False, "message": "Reader stopped. Completed chapters are safe; Resume retries the interrupted chapter.", "updatedAt": utc_now()})
            for key in ("workerPid", "queuedAction"):
                pipeline.pop(key, None)
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
            except ImportTitleCollision as error:
                self.send_json({"error": str(error), "code": "title-collision", "collisions": error.collisions}, HTTPStatus.CONFLICT)
                return
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
            self.send_json(infer_title_mark(title, ollama["models"] if ollama["running"] else [], configured_fast_model(settings)))
            return
        if route.path == "/api/setup/pdf-reader":
            installed, message = install_pdf_reader()
            self.send_json({"installed": installed, "message": message}, HTTPStatus.OK if installed else HTTPStatus.INTERNAL_SERVER_ERROR)
            return
        if route.path == "/api/setup/ollama":
            brew_path = local_executable("brew") if platform.system() == "Darwin" else None
            if not brew_path:
                self.send_json({"error": "Automatic Ollama installation is currently available only for Homebrew-managed macOS systems.", "instructions": "ollama"}, HTTPStatus.NOT_IMPLEMENTED)
                return
            if pipeline_is_enabled():
                self.send_json({"error": "Stop the analysis queue before installing or updating Ollama so an active model response is not interrupted."}, HTTPStatus.CONFLICT)
                return
            installed = subprocess.run([brew_path, "list", "--versions", "ollama"], capture_output=True, text=True, timeout=30).returncode == 0
            command = [brew_path, "upgrade" if installed else "install", "ollama"]
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
                role = str(payload.get("role", "fast")).strip()
                selected_model = str(payload.get("model", payload.get("fastModel", ""))).strip()
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
        identity = infer_manuscript_identity(opening_text, metadata, ollama["models"] if ollama["running"] else [], configured_fast_model(settings), metadata_authoritative=bool(structured_metadata))
        icon = infer_manuscript_icon(image_candidates, ollama["models"] if ollama["running"] else [], configured_fast_model(settings))
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
            if pipeline_is_enabled():
                start_global_pipeline()
        except Exception as error:
            print(f"[Bookinator]: Could not restore the analysis queue: {error}", file=sys.stderr)

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
    if os.environ.get("INATOR_SHARED_LAUNCHER") != "1":
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
