#!/usr/bin/env python3
"""Run the disposable GLiNER2.5 chapter-scaffold experiment.

This is deliberately outside the Bookinator queue. It lets us evaluate a
small, source-anchored encoder before making model installation, pipeline, or
artifact-format promises in the product.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path


ENTITY_LABELS = {
    "person": "A named or specifically identified human character",
    "named animal": "An animal character identified by a name",
    "group": "A named or specifically identified group of people or beings",
    "place": "A geographic place, building, room, region, or named natural feature",
    "institution": "An organization, household, government, school, church, or company",
    "creature": "A non-human, supernatural, monstrous, or folkloric being",
    "artifact": "A named or narratively significant physical object",
    "document or work": "A letter, manuscript, book, artwork, song, or other authored work",
    "event": "A named historical, social, or ceremonial event",
    "supernatural force": "A specifically described supernatural presence, power, or phenomenon",
}

EVENT_SCHEMA = {
    "story_event": [
        "actor::str::The person, creature, group, or force performing or experiencing the action",
        "action::str::The concrete action or change that occurs",
        "target::str::The person, object, place, or condition affected, if any",
        "resulting_state::str::The concrete state after the action, if stated",
        "location::str::Where the event occurs, if stated",
        "time_marker::str::When the event occurs, if stated",
        "evidence::str::The shortest exact source wording that states the action or change",
    ]
}

CLASSIFICATION_SCHEMA = {
    "viewpoint": ["first person", "second person", "third limited", "third omniscient", "objective external", "mixed or uncertain"],
    "prose_modes": {
        "labels": ["action", "dialogue", "exposition", "description", "introspection", "narrative summary", "investigation"],
        "multi_label": True,
        "cls_threshold": 0.35,
    },
    "moods": {
        "labels": ["tense", "foreboding", "ominous", "uncanny", "horrific", "bleak", "melancholic", "intimate", "romantic", "hopeful", "playful", "comic", "cozy", "meditative", "dreamlike", "wondrous", "triumphant", "frenetic", "claustrophobic", "neutral or uncertain"],
        "multi_label": True,
        "cls_threshold": 0.35,
    },
    "genre_affinities": {
        "labels": ["mystery", "thriller", "horror", "fantasy", "science fiction", "romance", "historical", "crime", "adventure", "literary", "comedy", "drama"],
        "multi_label": True,
        "cls_threshold": 0.35,
    },
    "theme_topics": {
        "labels": ["identity", "belonging", "family", "love", "loss", "power", "justice", "freedom", "duty", "memory", "mortality", "transformation", "isolation", "community", "faith", "truth"],
        "multi_label": True,
        "cls_threshold": 0.35,
    },
}


def paragraph_windows(text: str, target: int = 900, overlap: int = 160) -> list[tuple[int, str]]:
    """Prefer paragraph boundaries, but split oversized literary paragraphs.

    Nineteenth-century prose routinely puts several thousand characters in one
    paragraph. Keeping such a paragraph intact silently truncates the action at
    its end—the exact failure this experiment is meant to expose.
    """
    windows: list[tuple[int, str]] = []
    start = 0
    cursor = 0
    parts: list[str] = []
    for paragraph in text.splitlines(keepends=True):
        if len(paragraph) > target:
            if parts:
                value = "".join(parts)
                windows.append((start, value))
                parts = []
            local = 0
            while local < len(paragraph):
                desired_end = min(len(paragraph), local + target)
                end = desired_end
                if desired_end < len(paragraph):
                    boundary = max(
                        paragraph.rfind(". ", local + target // 2, desired_end),
                        paragraph.rfind("? ", local + target // 2, desired_end),
                        paragraph.rfind("! ", local + target // 2, desired_end),
                    )
                    if boundary >= 0:
                        end = boundary + 1
                windows.append((cursor + local, paragraph[local:end]))
                if end >= len(paragraph):
                    break
                local = max(local + 1, end - overlap)
            cursor += len(paragraph)
            start = cursor
            continue
        if parts and sum(len(part) for part in parts) + len(paragraph) > target:
            value = "".join(parts)
            windows.append((start, value))
            start = cursor
            parts = []
        if not parts:
            start = cursor
        parts.append(paragraph)
        cursor += len(paragraph)
    if parts:
        windows.append((start, "".join(parts)))
    return [(offset, value) for offset, value in windows if value.strip()]


def remap_spans(value: object, offset: int) -> object:
    if isinstance(value, list):
        return [remap_spans(item, offset) for item in value]
    if not isinstance(value, dict):
        return value
    result = {key: remap_spans(item, offset) for key, item in value.items()}
    if isinstance(result.get("start"), int):
        result["start"] += offset
    if isinstance(result.get("end"), int):
        result["end"] += offset
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("chapter", type=Path)
    parser.add_argument("--model", default="fastino/gliner2.5-small-v1")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--threshold", type=float, default=0.35)
    parser.add_argument("--skip-events", action="store_true")
    parser.add_argument("--skip-classification", action="store_true")
    args = parser.parse_args()

    from gliner2 import AutoExtractor

    text = args.chapter.read_text(encoding="utf-8")
    loaded_at = time.perf_counter()
    extractor = AutoExtractor.from_pretrained(args.model, map_location="cpu")
    load_seconds = time.perf_counter() - loaded_at

    entity_started = time.perf_counter()
    mentions = extractor.extract_entities_long(
        text,
        ENTITY_LABELS,
        chunk_size=384,
        chunk_overlap=64,
        include_spans=True,
        include_confidence=True,
        threshold=args.threshold,
    )
    entity_seconds = time.perf_counter() - entity_started

    events: list[dict[str, object]] = []
    classifications: list[dict[str, object]] = []
    event_started = time.perf_counter()
    windows = paragraph_windows(text)
    if not args.skip_events:
        for window_index, (offset, window) in enumerate(windows, start=1):
            extracted = extractor.extract_json(
                window,
                EVENT_SCHEMA,
                include_spans=True,
                include_confidence=True,
            )
            for event in extracted.get("story_event", []):
                remapped = remap_spans(event, offset)
                if isinstance(remapped, dict):
                    remapped["window"] = window_index
                    events.append(remapped)
    event_seconds = time.perf_counter() - event_started

    classification_started = time.perf_counter()
    if not args.skip_classification:
        for window_index, (offset, window) in enumerate(windows, start=1):
            classifications.append({
                "window": window_index,
                "start": offset,
                "end": offset + len(window),
                "result": extractor.classify_text(
                    window, CLASSIFICATION_SCHEMA, include_confidence=True,
                ),
            })
    classification_seconds = time.perf_counter() - classification_started

    payload = {
        "schema": "bookinator-gliner-chapter-spike-v1",
        "source": str(args.chapter),
        "sourceCharacters": len(text),
        "model": args.model,
        "threshold": args.threshold,
        "entityLabels": ENTITY_LABELS,
        "timing": {
            "modelLoadSeconds": round(load_seconds, 3),
            "entitySeconds": round(entity_seconds, 3),
            "eventSeconds": round(event_seconds, 3),
            "classificationSeconds": round(classification_seconds, 3),
            "totalSeconds": round(load_seconds + entity_seconds + event_seconds + classification_seconds, 3),
        },
        "raw": {"mentions": mentions, "events": events, "classifications": classifications},
        "audit": {
            "status": "not-run",
            "entityAudit": [],
            "eventAudit": [],
            "entityChapterLedger": [],
        },
    }
    rendered = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")


if __name__ == "__main__":
    main()
