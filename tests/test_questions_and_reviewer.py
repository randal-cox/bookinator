import json
from pathlib import Path
from unittest.mock import patch

import pytest

import bookinator.server.__main__ as server


def test_question_details_preserve_specific_editorial_metadata() -> None:
    result = server.normalize_chapter_summary({
        "summary": "Mara refuses the invitation.",
        "key_points": ["Mara stays behind."],
        "new_questions": ["Old redundant question"],
        "question_details": [{
            "question": "Why does Mara hide the unopened letter after refusing Eli’s invitation?",
            "family": "motivation",
            "evidence": "She slid the unopened letter beneath the flour bin.",
            "why_it_matters": "Her refusal may protect a secret rather than express indifference.",
            "promises_answer": True,
        }],
    })

    assert result["newQuestions"] == ["Why does Mara hide the unopened letter after refusing Eli’s invitation?"]
    assert result["questionDetails"][0]["family"] == "motivation"
    assert result["questionDetails"][0]["promisesAnswer"] is True
    assert result["promptVersion"] == server.SUMMARY_PROMPT_VERSION


def test_annotation_round_trip_preserves_anchor_and_human_judgment(tmp_path: Path) -> None:
    manuscript = "# CHAPTER 1\n\nMara folded the letter twice. She hid it beneath the flour bin."
    book = {"id": "book-12345678", "manuscriptId": "manuscript-1"}
    root = tmp_path / "manuscript-1"
    root.mkdir(parents=True)
    (root / "extracted-chapters.json").write_text(json.dumps([{
        "sequence": 1,
        "number": 1,
        "title": "CHAPTER 1",
        "pageStart": 7,
        "pageEnd": 9,
        "text": manuscript,
    }]), encoding="utf-8")
    quote = "She hid it beneath the flour bin."
    start = manuscript.index(quote)

    with patch.object(server, "BOOKS_ROOT", tmp_path):
        annotation = server.create_annotation(book, {
            "chapterSequence": 1,
            "characterStart": start,
            "characterEnd": start + len(quote),
            "quote": quote,
            "comment": "This concealment needs a later consequence.",
            "categories": ["plot", "continuity"],
            "priority": "high",
        })
        archived = server.update_annotation(book, annotation["id"], {"status": "archived", "comment": "Paid off in Chapter 8."})
        archived_status = archived["status"]
        updated = server.update_annotation(book, annotation["id"], {"status": "open"})
        saved = server.load_annotations(book)

    assert annotation["schema"] == server.ANNOTATION_SCHEMA_VERSION
    assert annotation["pageStart"] == 7
    assert annotation["anchorFingerprint"]
    assert annotation["categories"] == ["plot", "continuity"]
    assert annotation["category"] == "plot"
    assert archived_status == "archived"
    assert updated["status"] == "open"
    assert saved[0]["comment"] == "Paid off in Chapter 8."


def test_annotation_category_updates_are_multi_select_and_validated(tmp_path: Path) -> None:
    manuscript = "# CHAPTER 1\n\nThe door was locked."
    book = {"id": "book-12345678", "manuscriptId": "manuscript-1"}
    root = tmp_path / "manuscript-1"
    root.mkdir(parents=True)
    (root / "extracted-chapters.json").write_text(json.dumps([{"sequence": 1, "title": "CHAPTER 1", "text": manuscript}]), encoding="utf-8")
    start = manuscript.index("door")
    with patch.object(server, "BOOKS_ROOT", tmp_path):
        annotation = server.create_annotation(book, {"chapterSequence": 1, "characterStart": start, "characterEnd": start + 4, "quote": "door", "comment": "Track this."})
        updated = server.update_annotation(book, annotation["id"], {"categories": ["question", "plot", "question"]})
        with pytest.raises(ValueError, match="at least one"):
            server.update_annotation(book, annotation["id"], {"categories": []})
    assert updated["categories"] == ["question", "plot"]
    assert updated["category"] == "question"


def test_loading_legacy_annotation_promotes_its_category_to_the_multi_select_schema(tmp_path: Path) -> None:
    book = {"id": "book-12345678", "manuscriptId": "manuscript-1"}
    root = tmp_path / "manuscript-1"
    root.mkdir(parents=True)
    (root / "annotations.json").write_text(json.dumps([{
        "schema": "bookinator-annotation-v1",
        "id": "legacy-note",
        "comment": "Keep this note.",
        "category": "praise",
    }]), encoding="utf-8")

    with patch.object(server, "BOOKS_ROOT", tmp_path):
        annotations = server.load_annotations(book)

    assert annotations[0]["schema"] == server.ANNOTATION_SCHEMA_VERSION
    assert annotations[0]["category"] == "praise"
    assert annotations[0]["categories"] == ["praise"]


def test_annotation_delete_is_permanent(tmp_path: Path) -> None:
    manuscript = "# CHAPTER 1\n\nThe door was locked."
    book = {"id": "book-12345678", "manuscriptId": "manuscript-1"}
    root = tmp_path / "manuscript-1"
    root.mkdir(parents=True)
    (root / "extracted-chapters.json").write_text(json.dumps([{"sequence": 1, "title": "CHAPTER 1", "text": manuscript}]), encoding="utf-8")
    start = manuscript.index("door")
    with patch.object(server, "BOOKS_ROOT", tmp_path):
        annotation = server.create_annotation(book, {"chapterSequence": 1, "characterStart": start, "characterEnd": start + 4, "quote": "door", "comment": "Remove this debugging note."})
        deleted = server.delete_annotation(book, annotation["id"])
        assert server.load_annotations(book) == []
        with pytest.raises(LookupError, match="not available"):
            server.delete_annotation(book, annotation["id"])
    assert deleted["id"] == annotation["id"]


def test_successive_annotation_archives_accumulate(tmp_path: Path) -> None:
    book = {"id": "book-12345678", "manuscriptId": "manuscript-1"}
    root = tmp_path / "manuscript-1"
    root.mkdir(parents=True)
    text = "The door opened. The room waited. The clock stopped."
    (root / "extracted-chapters.json").write_text(json.dumps([{"sequence": 1, "title": "CHAPTER 1", "text": text}]), encoding="utf-8")
    with patch.object(server, "BOOKS_ROOT", tmp_path):
        first = server.create_annotation(book, {"chapterSequence": 1, "characterStart": 4, "characterEnd": 8, "quote": "door", "comment": "First note."})
        second = server.create_annotation(book, {"chapterSequence": 1, "characterStart": 21, "characterEnd": 25, "quote": "room", "comment": "Second note."})
        server.update_annotation(book, first["id"], {"status": "archived"})
        server.update_annotation(book, second["id"], {"status": "archived"})
        saved = server.load_annotations(book)
    assert {item["id"] for item in saved if item["status"] == "archived"} == {first["id"], second["id"]}


def test_annotation_rejects_a_stale_selection(tmp_path: Path) -> None:
    manuscript = "# CHAPTER 1\n\nThe door was locked."
    book = {"id": "book-12345678", "manuscriptId": "manuscript-1"}
    root = tmp_path / "manuscript-1"
    root.mkdir(parents=True)
    (root / "extracted-chapters.json").write_text(json.dumps([{"sequence": 1, "title": "CHAPTER 1", "text": manuscript}]), encoding="utf-8")

    with patch.object(server, "BOOKS_ROOT", tmp_path), pytest.raises(ValueError, match="no longer matches"):
        server.create_annotation(book, {
            "chapterSequence": 1,
            "characterStart": manuscript.index("door"),
            "characterEnd": manuscript.index("door") + 4,
            "quote": "gate",
            "comment": "Check this.",
        })


def test_reviewer_signoff_round_trip_is_named_durable_and_reversible(tmp_path: Path) -> None:
    book = {"id": "book-12345678", "manuscriptId": "manuscript-1"}
    with patch.object(server, "BOOKS_ROOT", tmp_path):
        completed = server.save_reviewer_signoff(book, {"status": "complete", "reviewerName": "Randal", "notes": "Strong ending; revisit the middle."})
        saved = server.load_reviewer_signoff(book)
        reopened = server.save_reviewer_signoff(book, {"status": "open"})

    assert completed["schema"] == server.REVIEWER_SIGNOFF_SCHEMA_VERSION
    assert saved["status"] == "complete"
    assert saved["reviewerName"] == "Randal"
    assert saved["notes"] == "Strong ending; revisit the middle."
    assert saved["completedAt"]
    assert reopened["status"] == "open"
    assert reopened["reviewerName"] == "Randal"
    assert reopened["notes"] == "Strong ending; revisit the middle."


def test_reviewer_signoff_requires_a_name(tmp_path: Path) -> None:
    book = {"id": "book-12345678", "manuscriptId": "manuscript-1"}
    with patch.object(server, "BOOKS_ROOT", tmp_path), pytest.raises(ValueError, match="reviewer’s name"):
        server.save_reviewer_signoff(book, {"status": "complete", "reviewerName": "", "notes": "Done."})


def test_prompts_demand_specific_questions_with_evidence() -> None:
    source = Path(server.__file__).read_text(encoding="utf-8")
    assert "Reject generic discussion prompts" in source
    assert "question_details" in source
    assert "promises_answer" in source
    assert 'SUMMARY_PROMPT_VERSION = "chapter-summary-v2"' in source
    assert 'DOSSIER_PROMPT_VERSION = "chapter-dossier-v3"' in source


def test_front_matter_never_promotes_editorial_questions() -> None:
    chapter = {"sequence": 0, "title": "Front matter", "text": "Contents"}
    model_result = {
        "summary": "A contents page.",
        "key_points": [],
        "new_questions": ["Will the named chapter be important?"],
        "question_details": [{
            "question": "Will the named chapter be important?",
            "family": "reader_expectation",
            "evidence": "Contents",
            "why_it_matters": "It names a later chapter.",
            "promises_answer": True,
        }],
    }
    with patch.object(server, "run_structured_model", return_value=(model_result, json.dumps(model_result))):
        result = server.summarize_chapter(chapter, "test-model")
    assert result["newQuestions"] == []
    assert result["questionDetails"] == []


def test_reviewer_interface_exposes_real_annotation_controls() -> None:
    root = Path(server.__file__).parents[2]
    app = (root / "web" / "app.js").read_text(encoding="utf-8")
    index = (root / "web" / "index.html").read_text(encoding="utf-8")
    assert 'activeTab === "reviewer"' in app
    assert "data-review-chapter" in app
    assert 'id="annotate-selection"' in index
    assert 'id="annotate-selection-toolbar"' not in index
    assert 'id="chapter-review-controls"' not in index
    assert "/annotations" in app
    assert 'type="checkbox" name="category"' in app
    assert 'type="radio" name="priority"' in app
    assert 'values.getAll("category")' in app
    assert "savedCategories = annotationCategories(result.annotation" in app
    assert "state.reviewerAnnotations.delete(bookId)" in app
    assert 'function invalidateReviewerAnnotations(bookId)' in app
    assert 'if (state.currentBookId === bookId) state.pipelineSignature = ""' in app
    assert 'invalidateReviewerAnnotations(book.id);\n        await showBookPage(book.id, activeTab);' in app
    assert 'state.pipelineSignature = ""' in app
    assert "predates multi-category annotations" in app
    assert '{id: "reviewer-report", label: "Comments"}' in app
    assert 'htmlId: "reviewer", label: "Reviewer comments"' in app
    assert 'method: "DELETE"' in app
    assert 'data-delete-annotation' in app
    assert 'data-archive-annotation' in app
    assert 'data-restore-annotation' in app
    assert "data-toggle-annotation" not in app
    assert '<span>active</span>' in app
    assert '<span>archived</span>' in app
    assert "function annotationCategoryBadgesMarkup" in app
    assert "function annotationPriorityControl" in app
    assert '({low: "Low", normal: "Normal", high: "Urgent"})' in app
    assert 'data-annotation-priority=' in app
    assert 'await updateReviewerAnnotation(book.id, annotation.id, {priority})' in app
    assert "function reviewerActionButton" in app
    assert "function inlineAnnotationCommentMarkup" in app
    assert "data-inline-edit-annotation" in app
    assert "data-inline-annotation-form" in app
    assert 'await updateReviewerAnnotation(book.id, annotationId, {comment})' in app
    assert "form.requestSubmit()" in app
    assert "setInlineAnnotationEditing(candidate, false, saved.comment)" in app
    assert "const scrollTop = document.querySelector(\"#chapter-source-body\")?.scrollTop || 0" in app
    assert 'body.scrollTo({top: Number(focus.scrollTop), behavior: "auto"})' in app
    assert 'title: "Delete this note permanently?"' in app
    assert "Sharper questions are available." not in app
    assert 'data-reviewer-signoff-form' in app
    assert 'I’m all done with this part' in app
    assert 'data-rescind-review' in app
    assert 'Rescind this reviewer sign-off?' in app
    assert 'The reviewer name, general notes, and every annotation will remain saved.' in app
    assert 'pipeline: machinePipelineComplete && reviewerComplete' in app
    assert 'pipeline: false' in app
    assert 'pipeline: pipeline.status === "running"' not in app
    assert 'id: "reviewer-signoff"' in app
    assert 'function pipelineProgressWithReviewer(pipeline)' in app
    assert 'function bookAnalysisProgress(book)' in app
    assert 'typeof left === "number" && typeof right === "number"' in app
    assert 'class="book-row${analysisComplete ? " analysis-complete" : ""}"' in app
    assert 'reviewer: reviewerComplete' in app
    assert 'const analysisTabs = workspaceTabsForBook(currentBook, "analysis").filter((tab) => tab !== "pipeline");' in app
    assert 'const reportTabs = workspaceTabsForBook(currentBook, "explore").filter((tab) => tab !== "report");' in app
    assert '!["plot", "assessment"].includes(tab)' not in app
    assert 'const exploreComplete = exploreReady === reportTabs.length;' in app
    assert 'exploreGroup?.classList.toggle("is-complete", exploreComplete);' in app
    assert 'updateWorkspaceTabProgress(document.querySelector("#book-tabs"), state.workspacePipeline.pipeline, bookPage.dataset.activeTab);' in app


def test_emotions_tags_and_smells_have_deterministic_whole_book_disclosures() -> None:
    root = Path(server.__file__).parents[2]
    app = (root / "web" / "app.js").read_text(encoding="utf-8")
    styles = (root / "web" / "styles.css").read_text(encoding="utf-8")
    todo = (root / "docs" / "TODO.md").read_text(encoding="utf-8")

    assert "function tagRollupData(pipeline)" in app
    assert "function smellRollupData(pipeline)" in app
    assert "function normalizeSmellRollupKey(value)" in app
    smell_labels = (root / "web" / "smell-labels.js").read_text(encoding="utf-8")
    assert 'key.includes("oxford comma")' in smell_labels
    assert '["missing oxford comma", "Oxford comma"]' in smell_labels
    assert "function emotionRollupData(pipeline)" in app
    assert "Whole-book tag frequencies" in app
    assert "Whole-book emotional profile" in app
    emotion_report = app.split("function emotionMapReportMarkup", 1)[1].split("function inferenceLedgerMarkup", 1)[0]
    assert 'wholeBookSignalRollupMarkup(pipeline, "emotion", new Set(["rollup:emotion"]))' in emotion_report
    assert 'class="report-signal-rollup"' in emotion_report
    assert "Undismissed Smells by type" in app
    assert '<details class="whole-book-rollup' in app
    assert 'data-analysis-key="${rollupKey}"' in app
    assert "data-rollup-row-limit" in app
    assert "function rollupChapterReference(chapter)" in app
    assert "data-rollup-chapter" in app
    assert 'target.scrollIntoView({behavior: "smooth", block: "start"})' in app
    assert 'await navigateWorkspaceTab(book.id, `${kind}s`)' in app
    assert "Showing top ${selectedLimit.toLocaleString()}" in app
    assert "whole-book-rollup-more" not in app
    assert "Most frequent tags" in app
    assert "Most frequent issue types" in app
    assert ".whole-book-rollup" in styles
    assert ".whole-book-rollup-controls" in styles
    assert 'class="whole-book-rollup-chapter-count" tabindex="0"' in app
    assert 'class="whole-book-rollup-chapter-tooltip" role="group"' in app
    assert ".whole-book-rollup-chapter-count:hover .whole-book-rollup-chapter-tooltip" in styles
    assert ".whole-book-rollup-chapter-tooltip button" in styles
    assert ".whole-book-rollup-more" not in styles
    assert '.whole-book-rollup { --rollup-accent: #6b48a4' in styles
    assert '.whole-book-rollup.emotions,.whole-book-rollup.smells,.whole-book-rollup.tags { --rollup-accent: #6b48a4' in styles
    assert "These are immediate overviews of saved chapter work, not additional model jobs." in todo


def test_chapter_length_is_an_explore_report_not_a_chapter_map_tab() -> None:
    root = Path(server.__file__).parents[2]
    app = (root / "web" / "app.js").read_text(encoding="utf-8")
    styles = (root / "web" / "styles.css").read_text(encoding="utf-8")

    assert "function chapterLengthRollupMarkup(pipeline)" in app
    assert "function chapterLengthReportMarkup(pipeline)" in app
    assert 'activeTab === "chapter-length"' in app
    assert 'reportExportControl("chapter-length")' in app
    assert 'data-chapter-map-rollup-tab=' not in app
    assert "data-chapter-length-target" in app
    assert "data-chapter-map-sequence" in app
    assert 'target.scrollIntoView({behavior: "smooth", block: "center"})' in app
    assert ".chapter-length-chart" in styles
    assert ".chapter-length-report" in styles
    assert '.book-tool-button.is-complete[aria-current="page"]::after { background: #2d8064' in styles
    assert ".chapter-length-chart-scroll" not in styles
    assert "grid-template-columns: 31px minmax(180px, 1fr) 72px" in styles
    assert '<span><strong>${escapeHtml(point.title)}</strong></span>' not in app
    assert ".chapter-map-rollup-tabs" not in styles


def test_annotation_routes_accept_legacy_opaque_ids_and_delete_is_idempotent() -> None:
    source = Path(server.__file__).read_text(encoding="utf-8")
    assert source.count(r"annotations(?:/([A-Za-z0-9_-]{8,80}))?") == 1
    assert source.count(r"annotations/([A-Za-z0-9_-]{8,80})") == 1
    assert '"alreadyDeleted": True' in source
