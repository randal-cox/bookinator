import json
import io
import threading
import time
import urllib.error
import zipfile
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from bookinator.server.__main__ import API_FEATURES, DOCS_ROOT, ModelTransportExhausted, PipelineCancelled, add_pipeline_progress, aggregate_manuscript_metrics, archive_manuscript_metadata_and_images, archive_manuscript_text, assigned_model_roles, automatic_queue_books, cancel_active_model_response, chapter_heading_report, chapter_heading_report_warnings, chapter_map_warnings, chapter_markdown, chapter_structure, choose_metadata_model, choose_primary_model, detect_chapters, ensure_chapter_artifacts, front_matter_metadata, global_pipeline_diagnostics, global_pipeline_estimate, infer_manuscript_icon, infer_manuscript_identity, invalidate_downstream_analysis, invalidate_pipeline_stage, join_pdf_lines, load_chapter_source, manuscript_text_metrics, model_parameter_billions, model_runtime_failure, next_pipeline_action, normalize_book_priority, normalize_chapter_summary, normalize_pdf_text, ollama_pull_error, page_bounded_chunks, pdf_blocks_to_paragraph_text, pipeline_activity, pipeline_stage_dependents, pipeline_stage_ready, pipeline_worker_is_alive, prioritize_pipeline_action, quiesce_pipeline_for_refresh, recommended_roles, reset_dossier_run, reset_inactive_whole_book_runs, reset_interrupted_rollup, reset_summary_run, stage_rollup_action, stage_rollup_input_signature, summarize_chapter, summarize_chapter_resilient, system_status, text_manuscript_to_pdf, title_from_filename, write_pipeline
import bookinator.server.__main__ as server


def test_markdown_front_matter_is_explicit_identity() -> None:
    source = b'---\ntitle: The Dunwich Horror\nauthor: "H. P. Lovecraft"\nsource: Gutenberg\n---\n\n# Wrong Nearby Heading\n'
    assert front_matter_metadata(source) == {"title": "The Dunwich Horror", "author": "H. P. Lovecraft"}


def test_authoritative_metadata_cannot_be_overwritten_by_model() -> None:
    response = {"message": {"content": json.dumps({"title": "THE SHOGGONLINE", "author": "H.P. LOVECRAFT", "abbreviation": "SHO"})}}
    with patch("bookinator.server.__main__.urllib.request.urlopen") as urlopen:
        urlopen.return_value.__enter__.return_value = io.StringIO(json.dumps(response))
        identity = infer_manuscript_identity(
            "THE SHOGGONLINE by H.P. LOVECRAFT",
            {"title": "The Dunwich Horror", "author": "H. P. Lovecraft"},
            ["qwen3.5:9b"],
            metadata_authoritative=True,
        )
    assert identity["title"] == "The Dunwich Horror"
    assert identity["author"] == "H. P. Lovecraft"
    assert identity["abbreviation"] == "DH"


def test_epub_package_metadata_and_declared_cover_are_extracted() -> None:
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w") as archive:
        archive.writestr("META-INF/container.xml", '<?xml version="1.0"?><container xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles><rootfile full-path="OEBPS/package.opf"/></rootfiles></container>')
        archive.writestr("OEBPS/package.opf", '<?xml version="1.0"?><package xmlns="http://www.idpf.org/2007/opf"><metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>Passing</dc:title><dc:creator>Nella Larsen</dc:creator></metadata><manifest><item id="cover" href="images/cover.jpg" media-type="image/jpeg" properties="cover-image"/></manifest></package>')
        archive.writestr("OEBPS/images/cover.jpg", b"JPEG" * 100)
    metadata, candidates = archive_manuscript_metadata_and_images(payload.getvalue(), ".epub")
    assert metadata == {"title": "Passing", "author": "Nella Larsen"}
    assert candidates[0]["role"] == "cover"
    icon = infer_manuscript_icon(candidates, [])
    assert icon and icon["source"] == "embedded-cover"
    assert str(icon["value"]).startswith("data:image/jpeg;base64,")


def test_system_status_is_local_only() -> None:
    status = system_status()
    assert status["localOnly"] is True
    assert status["platform"]
    assert status["architecture"]
    assert status["python"]
    assert isinstance(status["ollama"], dict)
    assert status["readiness"]["status"] in {"ready", "warning", "blocked"}
    expected_checks = {"operating-system", "memory", "python", "ollama", "package-installer", "storage", "pdf-reader"}
    if status["platform"] == "Darwin":
        expected_checks.add("homebrew")
    assert {check["id"] for check in status["readiness"]["checks"]} == expected_checks
    if status["platform"] == "Darwin":
        assert [check["id"] for check in status["readiness"]["checks"]][:3] == ["operating-system", "memory", "homebrew"]
    assert all(check["status"] in {"ready", "repairable", "warning", "blocked"} for check in status["readiness"]["checks"])
    assert set(status["emotionModel"]) >= {"runtime", "model", "ready", "modelId", "runtimeError"}


def test_model_uninstall_is_guarded_and_uses_ollama_delete() -> None:
    source = (Path(__file__).parents[1] / "bookinator" / "server" / "__main__.py").read_text(encoding="utf-8")
    assert 'route.path in {"/api/models/pull", "/api/models/delete"}' in source
    assert '"http://127.0.0.1:11434/api/delete"' in source
    assert 'assigned_model_roles(model' in source
    assert 'method="DELETE"' in source


def test_model_uninstall_guard_only_identifies_models_assigned_to_bookinator() -> None:
    available = ["qwen2.5:32B", "llama3.1:8b", "nomic-embed-text"]
    with patch("bookinator.server.__main__.load_settings", return_value={"readerModel": "qwen2.5:32B", "primaryModel": "qwen2.5:32B", "tagsModel": "qwen2.5:32B"}):
        assert assigned_model_roles("llama3.1:8b", available) == []
        assert assigned_model_roles("qwen2.5:32B", available)


def test_installed_emotion_runtime_clears_stale_per_book_setup_block() -> None:
    import bookinator.server.__main__ as server

    pipeline = {
        "stages": [{"id": "emotions", "status": "blocked", "detail": "Not installed", "setupRequired": True}],
        "chapters": [{"sequence": 1, "emotionStatus": "pending"}],
    }
    with patch.object(server, "emotion_model_status", return_value={"ready": True}):
        server.ensure_signal_stages(pipeline)
    stage = pipeline["stages"][0]
    assert stage["status"] == "pending"
    assert stage["detail"] == server.PIPELINE_STAGE_DEFINITIONS["emotions"][1]
    assert "setupRequired" not in stage


def test_stopped_signal_stage_cannot_leave_a_zombie_running_chapter() -> None:
    import bookinator.server.__main__ as server

    pipeline = {
        "stages": [{"id": "tags", "status": "warning", "detail": "The model process ended."}],
        "chapters": [{"sequence": 1, "tagStatus": "running", "tagStartedAt": "2026-09-23T22:40:52+00:00"}],
        "chunks": [],
    }
    assert server.reconcile_orphaned_child_runs(pipeline) is True
    assert pipeline["chapters"][0]["tagStatus"] == "pending"
    assert pipeline["chapters"][0]["tagError"] == "The model process ended."
    assert pipeline["chapters"][0]["interruptedAt"]


def test_stale_running_stage_cannot_validate_its_own_zombie_child() -> None:
    import bookinator.server.__main__ as server

    pipeline = {
        "status": "queued", "phase": "emotions",
        "stages": [{"id": "tags", "status": "running", "detail": "Analyzing tags."}],
        "chapters": [{"sequence": 1, "tagStatus": "running", "tagStartedAt": "2026-09-23T22:40:52+00:00"}],
        "chunks": [],
    }
    assert server.reconcile_orphaned_child_runs(pipeline) is True
    assert pipeline["stages"][0]["status"] == "warning"
    assert pipeline["chapters"][0]["tagStatus"] == "pending"
    assert "ready to retry" in pipeline["chapters"][0]["tagError"]


def test_serial_stage_reconciles_competing_running_children() -> None:
    import bookinator.server.__main__ as server

    pipeline = {
        "status": "running", "phase": "tags",
        "stages": [{"id": "tags", "status": "running", "detail": "Analyzing tags."}],
        "chapters": [
            {"sequence": 1, "tagStatus": "running", "tagStartedAt": "2026-09-23T22:40:52+00:00"},
            {"sequence": 2, "tagStatus": "running", "tagStartedAt": "2026-09-23T22:41:52+00:00"},
        ],
        "chunks": [],
    }
    assert server.reconcile_orphaned_child_runs(pipeline) is True
    assert pipeline["chapters"][0]["tagStatus"] == "pending"
    assert "competing local worker" in pipeline["chapters"][0]["tagError"]
    assert pipeline["chapters"][1]["tagStatus"] == "running"


def test_non_running_attempt_does_not_accrue_duration_forever() -> None:
    app = (Path(__file__).parents[1] / "web" / "app.js").read_text(encoding="utf-8")
    duration = app.split("function liveDurationMarkup", 1)[1].split("let readingDetailsClock", 1)[0]
    assert 'const running = status === "running" && Boolean(startedAt)' in duration
    assert 'const end = running ? new Date() : new Date(completedAt)' in duration


def test_failed_analysis_dialog_calls_its_rerun_action_retry() -> None:
    app = (Path(__file__).parents[1] / "web" / "app.js").read_text(encoding="utf-8")
    assert 'row.dataset.analysisStatus === "failed" ? "Retry" : "Refresh"' in app
    assert 'retrying ? "Retry failed analysis"' in app
    assert 'retrying ? "Retry this result?"' in app
    assert 'retrying ? "Retry" : "Refresh"' in app
    assert "function refreshOpenAnalysisDetails(body)" in app
    assert "refreshOpenAnalysisDetails(body);" in app


def test_analysis_navigation_remembers_each_books_last_workspace_tab() -> None:
    app = (Path(__file__).parents[1] / "web" / "app.js").read_text(encoding="utf-8")
    assert 'const analysisTabsKey = "bookinator.analysis-tabs.v1"' in app
    assert "function rememberedAnalysisTab(bookId)" in app
    assert "rememberAnalysisTab(bookId, activeTab)" in app
    assert '`book/${current.id}/${rememberedAnalysisTab(current.id)}`' in app


def test_library_uses_one_global_queue_control_and_priority_membership() -> None:
    root = Path(__file__).parents[1]
    page = (root / "web" / "index.html").read_text(encoding="utf-8")
    app = (root / "web" / "app.js").read_text(encoding="utf-8")
    assert 'id="toggle-library-pipeline"' in page
    assert 'id="global-pipeline-status"' not in page
    assert 'id="queue-books"' not in page
    assert 'id="dequeue-books"' not in page
    assert "Add to pipeline" not in app
    assert "Remove from pipeline" not in app
    assert 'id="pipeline-nav"' in page
    assert 'id="pipeline-page"' in page
    assert page.index('id="pipeline-page"') < page.index('id="library-pipeline-panel"')
    assert 'id="library-pipeline-panel"' not in page[page.index('id="books-page"'):page.index('id="pipeline-page"')]
    assert 'data-remove-from-queue' in app
    assert 'class="pipeline-remove-book action-button"' in app
    assert '<small>Remove</small>' in app
    assert 'label.textContent = "Removing…"' in app
    assert 'button.textContent = "Remove"' not in app
    assert 'saveBookPriority(book, "shelved")' in app
    assert 'id="library-pipeline-progress"' in page
    assert 'label: "Overall library progress"' in app
    assert "function progressPanel(" in app
    assert "return progressPanel({label, completed: progress.completed" in app
    assert 'id="pipeline-diagnostics-list"' in page
    assert "function renderPipelineDiagnostics()" in app
    assert "function progressActivity(" in app


def test_pipeline_activity_names_the_model_book_and_active_chapter() -> None:
    book = {"id": "book-1234", "title": "Shadow", "manuscriptId": "m1", "priority": "normal"}
    pipeline = {
        "status": "running", "phase": "summarizing", "stages": [{"id": "summaries", "model": "qwen2.5:32b"}],
        "chapters": [{"title": "CHAPTER 9", "status": "running"}], "chunks": [],
    }
    activity = pipeline_activity(book, pipeline)
    assert activity["state"] == "running"
    assert activity["model"] == "qwen2.5:32b"
    assert activity["task"] == "Chapter summary"
    assert activity["book"] == "Shadow"
    assert activity["item"] == "CHAPTER 9"
    assert activity["text"] == "Bookinator · qwen2.5:32b is reading Shadow · CHAPTER 9"


def test_question_reconciliation_is_named_honestly() -> None:
    pipeline = {
        "status": "running",
        "phase": "questions",
        "stages": [
            {"id": "summaries", "status": "complete", "model": "qwen2.5:32B"},
            {"id": "dossiers", "status": "complete"},
        ],
        "chapters": [{"status": "complete", "summary": "Ready."}],
        "chunks": [{"dossierStatus": "complete", "dossier": {"questions": ["Who?"]}}],
        "questionTracker": {"status": "running", "model": "qwen2.5:32B"},
    }

    activity = pipeline_activity({"id": "book-1234", "title": "Shadow"}, pipeline)

    assert activity["task"] == "Questions & payoffs"
    assert activity["item"] == "Whole-book reconciliation"
    assert "matching questions to payoffs in Shadow" in activity["text"]


def test_starting_one_whole_book_run_retires_stale_running_siblings() -> None:
    pipeline = {
        "updatedAt": "2026-09-24T01:00:00+00:00",
        "wholeBookSummary": {"status": "running", "startedAt": "earlier", "model": "reader"},
        "questionTracker": {"status": "running", "startedAt": "now", "model": "reader"},
    }

    reset_inactive_whole_book_runs(pipeline, "questions")

    assert pipeline["wholeBookSummary"]["status"] == "ready"
    assert pipeline["wholeBookSummary"]["interruptedAt"] == pipeline["updatedAt"]
    assert pipeline["questionTracker"]["status"] == "running"


def test_global_eta_uses_separate_recent_durations_and_diagnostics_collect_failed_items() -> None:
    book = {"id": "book-1234", "title": "Shadow", "manuscriptId": "m1", "priority": "normal"}
    pipeline = {
        "stages": [{"id": "chapter-archive", "status": "complete"}],
        "chapters": [
            {"sequence": 0, "title": "Front matter", "status": "complete", "tagStatus": "failed", "tagError": "Stale legacy failure"},
            {"sequence": 1, "title": "Chapter 1", "status": "complete", "durationSeconds": 60, "emotionStatus": "complete", "emotionDurationSeconds": 2, "tagStatus": "complete", "tagDurationSeconds": 40},
            {"sequence": 2, "title": "Chapter 2", "status": "pending", "emotionStatus": "pending", "tagStatus": "failed", "tagError": "Unknown signal", "tagModel": "reader"},
        ],
        "chunks": [
            {"chapterSequence": 1, "dossierStatus": "complete", "dossierDurationSeconds": 30},
            {"chapterSequence": 2, "dossierStatus": "pending"},
        ],
        "wholeBookSummary": {"status": "blocked"},
    }
    estimate = global_pipeline_estimate([(book, pipeline)])
    assert estimate["etaSeconds"] == 92
    assert estimate["estimates"]["summaries"] == {"remaining": 1, "averageSeconds": 60, "sampleSize": 1, "fallback": False}
    diagnostics = global_pipeline_diagnostics([(book, pipeline)])
    assert len(diagnostics) == 1
    assert diagnostics[0]["stage"] == "tags"
    assert diagnostics[0]["resultKind"] == "tag"
    assert diagnostics[0]["resultId"] == 2
    assert diagnostics[0]["item"] == "Chapter tags · Chapter 2"
    assert diagnostics[0]["error"] == "Unknown signal"


def test_global_diagnostics_name_dossier_process_chapter_and_chunk() -> None:
    book = {"id": "book-1234", "title": "Shadow"}
    pipeline = {
        "stages": [],
        "chapters": [],
        "chunks": [{
            "sequence": 36,
            "chapterLabel": "CHAPTER 24",
            "chunkInChapter": 2,
            "dossierStatus": "failed",
            "dossierError": "Connection refused",
            "dossierModel": "qwen2.5:32B",
        }],
    }
    diagnostics = global_pipeline_diagnostics([(book, pipeline)])
    assert diagnostics[0]["item"] == "Chapter dossier · CHAPTER 24 · Chunk 2"
    assert diagnostics[0]["model"] == "qwen2.5:32B"
    assert diagnostics[0]["resultKind"] == "dossier"
    assert diagnostics[0]["resultId"] == 36


def test_global_diagnostics_ignore_ordinary_dependency_blocks_but_report_setup_blocks() -> None:
    book = {"id": "book-1234", "title": "Shadow"}
    pipeline = {"stages": [
        {"id": "summaries", "label": "Summaries", "status": "blocked", "detail": "Waiting for chapters."},
        {"id": "emotions", "label": "Emotions", "status": "blocked", "detail": "Classifier is missing.", "setupRequired": True},
    ], "chapters": [], "chunks": []}
    diagnostics = global_pipeline_diagnostics([(book, pipeline)])
    assert [item["stage"] for item in diagnostics] == ["emotions"]


def test_server_advertises_chapter_map_approval_protocol() -> None:
    assert API_FEATURES["chapterMapApproval"] == 1
    assert API_FEATURES["chapterMapEditing"] == 1
    assert API_FEATURES["provisionalAnalysis"] == 1
    assert API_FEATURES["globalPriorityQueue"] == 1


def test_automatic_queue_orders_priority_and_skips_shelved() -> None:
    books = [
        {"id": "low-book", "manuscriptId": "m1", "priority": "low", "updatedAt": "2026-01-01"},
        {"id": "high-new", "manuscriptId": "m2", "priority": "high", "updatedAt": "2026-02-01"},
        {"id": "high-old", "manuscriptId": "m3", "priority": "high", "updatedAt": "2026-01-01"},
        {"id": "shelved", "manuscriptId": "m4", "priority": "shelved", "updatedAt": "2025-01-01"},
    ]
    pending = {"stages": [], "chapters": []}
    with patch("bookinator.server.__main__.load_pipeline", return_value=pending):
        queued = automatic_queue_books(books)
    assert queued == [("high-old", "prepare"), ("high-new", "prepare"), ("low-book", "prepare")]


def test_next_pipeline_action_advances_without_retrying_failed_work_forever() -> None:
    book = {"id": "book-1234", "manuscriptId": "manuscript", "priority": "normal"}
    stages = [{"id": "extraction", "status": "complete"}, {"id": "chapter-archive", "status": "complete"}]
    pipeline = {"stages": stages, "chapters": [{"status": "failed", "emotionStatus": "failed", "tagStatus": "failed"}], "chunks": [{"dossierStatus": "pending"}]}
    assert next_pipeline_action(book, pipeline) == "dossiers"
    pipeline["chunks"][0]["dossierStatus"] = "failed"
    assert next_pipeline_action(book, pipeline) == ""
    assert normalize_book_priority("unexpected") == "normal"


def test_retry_failed_analysis_is_selective_and_preserves_run_history(tmp_path: Path) -> None:
    import bookinator.server.__main__ as server

    pipeline = {
        "status": "complete",
        "stages": [
            {"id": "summaries", "status": "failed"},
            {"id": "tags", "status": "failed"},
            {"id": "dossiers", "status": "failed"},
        ],
        "chapters": [
            {"sequence": 1, "status": "failed", "model": "reader", "error": "bad JSON", "tagStatus": "failed", "tagModel": "tagger", "tagError": "bad tag"},
            {"sequence": 2, "status": "complete", "summary": "Keep me", "tagStatus": "complete", "tag": {"signals": []}},
        ],
        "chunks": [{"sequence": 1, "dossierStatus": "failed", "dossierModel": "reader", "dossierError": "timeout"}],
    }
    with patch("bookinator.server.__main__.chunk_artifacts_path", return_value=tmp_path):
        count = server.retry_failed_analysis({"id": "book-1234"}, pipeline)

    assert count == 3
    assert pipeline["chapters"][0]["status"] == "pending"
    assert pipeline["chapters"][0]["tagStatus"] == "pending"
    assert pipeline["chapters"][0]["summaryRuns"][-1]["error"] == "bad JSON"
    assert pipeline["chapters"][0]["tagRuns"][-1]["tagError"] == "bad tag"
    assert pipeline["chunks"][0]["dossierStatus"] == "pending"
    assert pipeline["chunks"][0]["dossierRuns"][-1]["dossierError"] == "timeout"
    assert pipeline["chapters"][1]["summary"] == "Keep me"
    assert pipeline["chapters"][1]["tagStatus"] == "complete"


@pytest.mark.parametrize("kind,stage_id", [("emotion", "emotions"), ("tag", "tags"), ("smell", "smells")])
def test_one_result_refresh_uses_the_same_contract_for_every_chapter_signal(kind: str, stage_id: str) -> None:
    pipeline = {
        "status": "complete",
        "stages": [{"id": stage_id, "status": "complete"}],
        "chapters": [
            {"sequence": 1, "status": "complete", f"{kind}Status": "complete", kind: {"saved": True}, f"{kind}Model": "model", f"{kind}CompletedAt": "now"},
            {"sequence": 2, "status": "complete", f"{kind}Status": "complete", kind: {"keep": True}},
        ],
        "chunks": [],
    }
    with patch.object(server, "write_pipeline"):
        action, _ = server.refresh_analysis_result({"id": "book-1234"}, pipeline, kind, 1)

    assert action == stage_id
    assert pipeline["chapters"][0][f"{kind}Status"] == "pending"
    assert kind not in pipeline["chapters"][0]
    assert pipeline["chapters"][1][f"{kind}Status"] == "complete"
    assert pipeline["chapters"][1][kind] == {"keep": True}


def test_deferred_analysis_refreshes_survive_a_server_restart(tmp_path: Path) -> None:
    deferred_path = tmp_path / "deferred-analysis-refreshes.json"
    expected = {"book-1234": [("smell", 2), ("summary", 3)]}
    with patch.object(server, "DEFERRED_REFRESHES_PATH", deferred_path):
        server.save_deferred_analysis_refreshes(expected)
        restored = server.load_deferred_analysis_refreshes()

    assert restored == expected


def test_deferred_single_refresh_is_presented_as_waiting_without_mutating_saved_failure() -> None:
    pipeline = {
        "status": "running", "phase": "tags",
        "stages": [{"id": "smells", "status": "warning"}, {"id": "tags", "status": "running"}],
        "chapters": [{"sequence": 2, "smellStatus": "failed", "smellError": "review failed"}, {"sequence": 3, "tagStatus": "running"}],
        "chunks": [],
    }
    with patch.dict(server.QUEUE_ACTIONS, {"book-1234": "deferred-refresh"}, clear=True), patch.dict(server.DEFERRED_ANALYSIS_REFRESHES, {"book-1234": [("smell", 2)]}, clear=True):
        visible = server.pipeline_for_client("book-1234", pipeline)

    assert visible["chapters"][0]["smellStatus"] == "pending"
    assert visible["chapters"][0]["refreshQueued"] is True
    assert visible["stages"][0]["status"] == "pending"
    assert pipeline["chapters"][0]["smellStatus"] == "failed"


def test_summary_and_dossier_refresh_share_the_saved_result_contract(tmp_path: Path) -> None:
    summary_pipeline = {
        "stages": [{"id": "summaries", "status": "complete"}],
        "chapters": [{"sequence": 2, "status": "complete", "summary": "Old", "model": "reader", "completedAt": "now"}],
        "chunks": [],
    }
    dossier_pipeline = {
        "stages": [{"id": "dossiers", "status": "complete"}],
        "chapters": [],
        "chunks": [{"sequence": 7, "dossierStatus": "complete", "dossier": {"facts": []}, "dossierModel": "reader", "dossierCompletedAt": "now"}],
    }
    with patch.object(server, "write_pipeline"):
        summary_action, _ = server.refresh_analysis_result({"id": "book-1234"}, summary_pipeline, "summary", 2)
    with patch.object(server, "write_pipeline"), patch.object(server, "chunk_artifacts_path", return_value=tmp_path):
        dossier_action, _ = server.refresh_analysis_result({"id": "book-1234"}, dossier_pipeline, "dossier", 7)

    assert summary_action == "summarize"
    assert summary_pipeline["chapters"][0]["status"] == "pending"
    assert "summary" not in summary_pipeline["chapters"][0]
    assert dossier_action == "dossiers"
    assert dossier_pipeline["chunks"][0]["dossierStatus"] == "pending"
    assert "dossier" not in dossier_pipeline["chunks"][0]


def test_pipeline_exposes_one_book_level_failed_work_recovery_control() -> None:
    app = (Path(__file__).parents[1] / "web" / "app.js").read_text(encoding="utf-8")
    assert "function failedAnalysisCount(pipeline)" in app
    assert 'action: "retry-failed"' in app
    assert 'context: "Pipeline recovery"' in app
    assert 'acceptLabel: "Retry failed work"' in app
    assert "/pipeline/retry-failed" in app
    assert "queuedBehindActiveResponse" in app
    assert "You do not need to stop the library queue." in app


def test_development_launcher_has_a_safe_highlander_mode() -> None:
    launcher = (Path(__file__).parents[1] / "bin" / "serve").read_text(encoding="utf-8")
    assert "--highlander" in launcher
    assert 'listener_command" != *"bookinator.server"*' in launcher
    assert 'listener_cwd" != "$project_dir"' in launcher
    assert "pgrep -f 'python.*-m bookinator" in launcher
    assert 'kill "$listener_pid"' in launcher
    assert "refusing to force-kill it" in launcher
    assert "Bookinator was replaced by another local launcher (SIGTERM)." in launcher
    assert 'make new tab with properties {URL:targetURL}' in launcher
    assert '/usr/bin/open -a Safari "$url" ||' in launcher


def test_pipeline_payload_does_not_resend_manuscript_source_text() -> None:
    import bookinator.server.__main__ as server

    pipeline = {"chapters": [{"sequence": 1, "markdown": "# CHAPTER 1\n\nSource prose", "text": "Source prose", "summary": "Keep this"}]}
    visible = server.compact_pipeline_payload(pipeline)

    assert visible["chapters"][0] == {"sequence": 1, "summary": "Keep this"}
    assert pipeline["chapters"][0]["markdown"].startswith("# CHAPTER")


def test_overall_manuscript_metrics_exclude_front_matter() -> None:
    metrics = aggregate_manuscript_metrics([
        {"title": "Front matter", "pageStart": 1, "pageEnd": 4, "characterCount": 13_329, "wordCount": 282, "paragraphCount": 72, "sectionCount": 0},
        {"title": "CHAPTER 1", "pageStart": 5, "pageEnd": 9, "characterCount": 7_505, "wordCount": 1_363, "paragraphCount": 22, "sectionCount": 1},
        {"title": "## CHAPTER 2", "pageStart": 10, "pageEnd": 21, "characterCount": 19_482, "wordCount": 3_511, "paragraphCount": 59, "sectionCount": 2},
    ])
    assert metrics == {
        "pageCount": 17, "characterCount": 26_987, "wordCount": 4_874,
        "paragraphCount": 81, "sectionCount": 3, "chapterCount": 2,
        "excludesFrontMatter": True,
    }


def test_unapproved_chapter_map_can_enter_provisional_analysis_queue() -> None:
    class ActiveQueue:
        @staticmethod
        def is_alive() -> bool:
            return True

    pipeline = {"chapterMapApproved": False, "chapterMapSuspicious": True, "status": "ready"}
    with (
        patch("bookinator.server.__main__.find_book", return_value={"id": "book-1234"}),
        patch("bookinator.server.__main__.load_pipeline", return_value=pipeline),
        patch("bookinator.server.__main__.load_queue", return_value=[]),
        patch("bookinator.server.__main__.save_queue"),
        patch("bookinator.server.__main__.set_pipeline_enabled"),
        patch("bookinator.server.__main__.write_pipeline"),
        patch("bookinator.server.__main__.persist_queue_action"),
        patch("bookinator.server.__main__.QUEUE_THREAD", ActiveQueue()),
    ):
        queued = prioritize_pipeline_action("book-1234", "summarize")
    assert queued["status"] == "queued"
    assert queued["queuedAction"] == "summarize"


def test_structural_prepare_queues_dependent_analysis_after_rebuild() -> None:
    class ActiveQueue:
        @staticmethod
        def is_alive() -> bool:
            return True

    pipeline = {"chapterMapApproved": True, "status": "ready"}
    with (
        patch("bookinator.server.__main__.find_book", return_value={"id": "book-1234"}),
        patch("bookinator.server.__main__.load_pipeline", return_value=pipeline),
        patch("bookinator.server.__main__.load_queue", return_value=[]),
        patch("bookinator.server.__main__.save_queue"),
        patch("bookinator.server.__main__.set_pipeline_enabled"),
        patch("bookinator.server.__main__.write_pipeline"),
        patch("bookinator.server.__main__.persist_queue_action"),
        patch("bookinator.server.__main__.QUEUE_THREAD", ActiveQueue()),
    ):
        queued = prioritize_pipeline_action("book-1234", "prepare")
    assert queued["continueAnalysisAfterPrepare"] is True
    assert queued["queuedAction"] == "prepare"


def test_overall_pipeline_progress_counts_current_passes_per_manuscript_chapter() -> None:
    pipeline = {
        "stages": [{"id": "chapter-archive", "status": "complete"}],
        "chapters": [
            {"sequence": 1, "title": "Front matter", "status": "complete"},
            {"sequence": 2, "title": "CHAPTER 1", "status": "complete"},
            {"sequence": 3, "title": "CHAPTER 2", "status": "pending"},
        ],
        "chunks": [
            {"chapterSequence": 1, "dossierStatus": "complete"},
            {"chapterSequence": 2, "dossierStatus": "complete"},
            {"chapterSequence": 3, "dossierStatus": "pending"},
        ],
    }
    progress = add_pipeline_progress(pipeline)["pipelineProgress"]
    assert progress["total"] == 10
    assert progress["completed"] == 4
    assert progress["percent"] == 40
    assert progress["chapterCount"] == 2
    assert "front matter excluded" in progress["basisLabel"]


def test_public_docs_exist_inside_the_docs_root() -> None:
    resources = (DOCS_ROOT / "presentations" / "index.html").resolve()
    assert resources.is_file()
    assert DOCS_ROOT.resolve() in resources.parents


def test_roadmap_is_a_sortable_footer_destination() -> None:
    root = Path(__file__).parents[1]
    page = (root / "web" / "index.html").read_text(encoding="utf-8")
    pages = (root / "web" / "pages.js").read_text(encoding="utf-8")
    app = (root / "web" / "app.js").read_text(encoding="utf-8")
    styles = (root / "web" / "styles.css").read_text(encoding="utf-8")
    assert 'href="#roadmap/priorities" data-page="roadmap">Roadmap</a>' in page
    assert "export const roadmapItems" in pages
    assert "Sharper summary and dossier questions" in pages
    assert "Book-title collision research" in pages
    for field in ("name", "description", "tags", "ease", "impact"):
        assert f"{field}:" in pages
    assert "item.payoff = item.ease * item.impact" in pages
    assert 'if (collection === "roadmap") installRoadmapLedger();' in app
    for field in ("name", "description", "tags", "ease", "impact", "payoff"):
        assert f'key: "{field}"' in app
    assert '<table class="roadmap-table">' in app
    assert '<th scope="col" aria-sort=' in app
    assert '<th scope="row" class="roadmap-name">' in app
    assert 'data-roadmap-search' in app
    assert 'data-roadmap-tag' in app
    assert 'data-roadmap-clear' in app
    assert 'selectedTags.some' not in app
    assert '[...selectedTags].some' in app
    assert ".roadmap-filters" in styles
    assert '.roadmap-tag-picker button[aria-pressed="true"]' in styles
    assert ".roadmap-introduction" in styles
    assert ".roadmap-table" in styles


def test_editorial_question_and_title_research_priorities_are_documented() -> None:
    todo = (Path(__file__).parents[1] / "docs" / "TODO.md").read_text(encoding="utf-8")
    assert "## Urgent: sharper questions from summaries and dossiers" in todo
    assert "## Low priority: book-title research and collision checking" in todo


def test_workspace_groups_end_with_their_human_judgment_views() -> None:
    source = (Path(__file__).parents[1] / "web" / "app.js").read_text(encoding="utf-8")
    tabs = source.split("const workspaceTabs = [", 1)[1].split("];", 1)[0]
    expected = ["pipeline", "chapters", "summaries", "dossiers", "emotions", "tags", "smells", "inferences", "report", "overview", "smell-report", "emotion-map", "connections", "questions", "plot", "reviewer", "assessment"]
    positions = [tabs.index(f'{{id: "{tab}"') for tab in expected]
    assert positions == sorted(positions)
    assert tabs.rstrip().endswith('{id: "assessment", label: "Assessment"},')
    styles = (Path(__file__).parents[1] / "web" / "styles.css").read_text(encoding="utf-8")
    assert 'const workspaceGroups = {' in source
    assert 'analysis: ["pipeline", "chapters", "summaries", "dossiers", "emotions", "tags", "smells", "inferences", "reviewer"]' in source
    assert 'explore: ["report", "overview", "emotion-map", "connections", "questions", "plot", "smell-report", "assessment"]' in source
    assert 'const workspaceShelfEndTabs = new Set(["reviewer", "assessment"]);' in source
    assert 'title: "Assessment"' in source
    assert ".book-workspace-primary" in styles
    assert ".book-workspace-shelf" in styles
    assert ".workspace-primary-spacer" in styles
    assert ".workspace-shelf-spacer" in styles


def test_questions_and_payoffs_is_a_sortable_queued_workspace() -> None:
    root = Path(__file__).parents[1]
    app = (root / "web" / "app.js").read_text(encoding="utf-8")
    styles = (root / "web" / "styles.css").read_text(encoding="utf-8")
    server = (root / "bookinator" / "server" / "__main__.py").read_text(encoding="utf-8")
    assert "Questions & payoffs" in app
    for key in ("status", "source", "resolution", "delta"):
        assert f'data-question-sort="{key}"' in app
    assert 'pipelineControl({action: "questions"' in app
    assert ".question-tracker-table" in styles
    assert '"question-tracker": ("summaries", "dossiers")' in server
    assert "def reconcile_questions_and_payoffs" in server
    assert '{id: "questions", label: "Questions & payoffs"}' in app
    assert 'activeTab === "questions"' in app
    assert 'visiblePipelineStages(pipeline)' in app


def test_inferences_group_book_level_algorithms_behind_one_workspace_button() -> None:
    pipeline = {
        "stages": [
            {"id": "chapter-archive", "status": "complete"},
            {"id": "summaries", "status": "complete", "model": "reader"},
            {"id": "dossiers", "status": "complete", "model": "reader"},
        ],
        "chapters": [{"sequence": 1, "title": "CHAPTER 1", "status": "complete", "summary": "A question is raised."}],
        "chunks": [{"chapterSequence": 1, "dossierStatus": "complete", "dossier": {"questions": ["Who did it?"]}}],
        "questionTracker": {"status": "ready", "model": "reader", "detail": "Ready to reconcile."},
    }

    add_pipeline_progress(pipeline)

    algorithms = {algorithm["id"]: algorithm for algorithm in pipeline["inferences"]}
    assert list(algorithms) == ["questions", "connections"]
    assert algorithms["questions"]["status"] == pipeline["questionTracker"]["status"]
    assert algorithms["questions"]["workspaceTab"] == "questions"
    assert algorithms["connections"]["workspaceTab"] == "connections"
    assert not any(item["id"] in {"questions", "inferences"} for item in pipeline["stages"])


def test_incomplete_dossiers_can_be_finished_ahead_of_other_analysis() -> None:
    app = (Path(__file__).parents[1] / "web" / "app.js").read_text(encoding="utf-8")
    assert 'pipelineControl({action: "dossiers", label: "Finish"' in app
    assert 'title: "Finish the remaining dossiers before returning to other analysis"' in app


def test_summary_and_dossier_tabs_require_their_whole_book_entries() -> None:
    app = (Path(__file__).parents[1] / "web" / "app.js").read_text(encoding="utf-8")
    assert 'summaries: (stageComplete("summaries") || chapterSummariesComplete) && wholeSummaryComplete' in app
    assert 'dossiers: (stageComplete("dossiers") || chunkDossiersComplete) && wholeDossierComplete' in app
    assert 'pipeline.wholeBookSummary?.status === "complete"' in app
    assert 'pipeline.wholeBookDossier?.status === "complete"' in app


def test_whole_book_summary_and_dossier_statuses_share_run_details() -> None:
    app = (Path(__file__).parents[1] / "web" / "app.js").read_text(encoding="utf-8")
    row = app[app.index("function wholeBookAnalysisRow"):app.index("function chapterMapRow")]
    assert 'const inspectable = kind === "summaries" || kind === "dossiers"' in row
    assert 'data-show-reading-details' in row
    assert 'label: "State"' in row
    assert 'label: "Inputs"' in row
    assert 'label: "Depends on"' in row
    assert 'refreshableSummary' in row
    assert 'pipelineControl({action: "whole-summary", label: "Finish"' in app
    assert 'without waiting for independent analysis passes' in app


def test_question_tracker_preserves_possible_payoffs_and_promise_sources() -> None:
    import bookinator.server.__main__ as server
    pipeline = {
        "stages": [{"id": "summaries", "status": "complete"}, {"id": "dossiers", "status": "complete"}],
        "chapters": [
            {"sequence": 1, "title": "Chapter 1", "status": "complete", "summary": "A locked door is found.", "newQuestions": ["What is behind the door?"]},
            {"sequence": 2, "title": "Chapter 2", "status": "complete", "summary": "The key is found, but the door stays shut.", "newQuestions": []},
        ],
        "chunks": [{"chapterSequence": 1, "chunkInChapter": 1, "dossierStatus": "complete", "dossier": {"questions": ["What does the door hide?"], "promises": ["Story promise: the locked door will matter."]}}],
    }
    response = {"groups": [{"canonical_question": "What is behind the door?", "retellings": [{"text": "What does the door hide?", "chapter": 1}], "trigger_chapter": 1, "status": "possible", "resolution_chapter": 2, "answer": "A key is found, but the contents remain unknown.", "confidence": "medium"}]}
    with patch.object(server, "run_structured_model", return_value=(response, "raw")) as run:
        result = server.reconcile_questions_and_payoffs(pipeline, "reader")
    assert result["items"][0]["status"] == "possible"
    assert result["items"][0]["chapterDelta"] == 1
    assert result["sourceQuestionCount"] == 3
    assert "Story promise: the locked door will matter." in run.call_args.args[0]


def test_hydrated_dossier_cannot_stay_running_while_tags_are_active() -> None:
    import bookinator.server.__main__ as server
    pipeline = {
        "status": "running",
        "phase": "tags",
        "stages": [{"id": "tags", "status": "running"}, {"id": "dossiers", "status": "pending", "detail": "Completed 35 of 37 structured dossiers."}],
        "chapters": [{"sequence": 2, "tagStatus": "running"}],
        "chunks": [{"sequence": 36, "dossierStatus": "running", "dossierStartedAt": "2026-09-24T02:57:17+00:00"}],
    }
    assert server.reconcile_orphaned_child_runs(pipeline)
    assert pipeline["chunks"][0]["dossierStatus"] == "pending"
    assert "previous dossier run stopped" in pipeline["chunks"][0]["dossierError"].lower()
    source = (Path(__file__).parents[1] / "bookinator" / "server" / "__main__.py").read_text(encoding="utf-8")
    hydration = source.index('payload["chunks"] = chunk_archive.get("chunks", [])')
    assert source.index("hydrated_orphaned_changed = reconcile_orphaned_child_runs(payload)", hydration) > hydration
    assert "write_chunk_artifact(book, sequence, chunk)" in source[hydration:]


def test_book_icon_paste_uses_shared_image_pipeline_without_hijacking_text_fields() -> None:
    root = Path(__file__).parents[1]
    app = (root / "web" / "app.js").read_text(encoding="utf-8")
    page = (root / "web" / "index.html").read_text(encoding="utf-8")
    assert 'addDialog.addEventListener("paste"' in app
    assert "isTextEditingTarget(event.target)" in app
    assert 'useBookMarkImage(image, "Pasted from clipboard")' in app
    assert "Drop or paste an image" in page


def test_dossier_time_sections_are_grouped_and_promises_include_reader_contracts() -> None:
    root = Path(__file__).parents[1]
    app = (root / "web" / "app.js").read_text(encoding="utf-8")
    server = (root / "bookinator" / "server" / "__main__.py").read_text(encoding="utf-8")
    assert 'label: "Time and chronology"' in app
    assert 'label: "Current scene time"' in app
    assert 'label: "Timeline observations"' in app
    assert 'label: "Promises and reader contracts"' in app
    assert 'Begin each promise with "Character promise:" or "Story promise:"' in server


def test_connections_workspace_uses_dry_inspectable_entity_location_and_time_indices() -> None:
    root = Path(__file__).parents[1]
    app = (root / "web" / "app.js").read_text(encoding="utf-8")
    styles = (root / "web" / "styles.css").read_text(encoding="utf-8")
    assert 'function dossierIndexGroups(pipeline, field, book = {})' in app
    assert 'dossierIndexGroups(pipeline, "entities", book)' in app
    assert 'dossierIndexGroups(pipeline, "locations", book)' in app
    assert "function dossierTimeEntries(pipeline, book = {})" in app
    assert 'data-index-kind="times"' in app
    assert 'data-default-sort="chapter:desc"' in app
    assert 'data-index-sort="chapter"' in app
    assert 'data-index-sort="mentions"' in app
    assert 'class="book-index-table times"' in app
    assert 'data-sort-source' not in app
    assert 'title: "Connections"' in app
    assert "collapse: false" in app
    assert "const sortIndexPanel = (panel, key, direction)" in app
    assert 'right.chapter.sequence - left.chapter.sequence' in app
    assert 'data-index-absences' in app
    assert "function dossierNameSimilarity(left, right)" in app
    assert "function dossierNamesShouldMerge(left, right)" in app
    assert "function mergeDossierIndexGroups(sourceGroups)" in app
    assert 'field === "entities" && locationKeys.has(dossierMorphologyKey(label))' in app
    assert "function dossierPlaceLikeName(value)" in app
    assert 'field === "locations" ?' in app
    assert 'const apostropheTypo =' in app
    assert 'const collectiveCore =' in app
    assert "function dossierIntersectionItems(pipeline, book = {})" in app
    assert "function dossierIndexInspector(detailsMarkup, kind, label)" in app
    assert "function dossierIntersectionMarkup(pipeline, book, focusKind, focusLabel, showNonInteractions = false)" in app
    assert 'class="article-tabs book-index-row-tabs"' in app
    assert 'data-index-row-tab="details"' in app
    assert 'data-index-row-tab="connections"' in app
    assert 'class="book-index-disclosure-cue"' in app
    assert "function dossierInspectCue(label)" in app
    assert '<span class="sr-only">Inspect ${escapeHtml(label)}</span>' in app
    assert 'class="book-index-inspect-heading"' in app
    assert 'data-explore-intersections' not in app
    assert 'data-index-intersection' not in app
    assert 'class="book-index-connections${showNonInteractions ? " show-no-interactions" : ""}"' in app
    assert 'data-intersection-absences' in app
    assert "Show chapters with no interaction" in app
    assert "Back to index" not in app
    assert "share a section or appear elsewhere in the same chapter" in app
    assert "Nearby chapter" not in app
    assert "Possible close names" in app
    assert "function parseDossierIndexEntry(rawValue)" in app
    assert "Dossier notes" in app
    assert "<h5>Names and aliases</h5>" in app
    assert 'class="book-index-name-stack"' in app
    assert 'class="absent"' in app
    assert 'activeTab === "inferences"' in app
    assert 'content: inferenceLedgerMarkup(pipeline)' in app
    assert 'activeTab === "connections"' in app
    assert 'data-view-chapter-source="${item.sequence}"' in app
    assert 'data-index-kind="entities"' in app
    assert 'data-index-kind="locations"' in app
    assert ".book-index-table" in styles
    assert ".book-index-row-tabs" in styles
    assert ".book-index-disclosure-cue" in styles
    assert '[role="columnheader"]' in styles
    assert '[aria-sort]' in styles
    assert ".book-index-chapters" in styles
    assert ".book-index.show-absences" in styles
    assert ".book-index-inspection" in styles
    assert ".intersection-groups" in styles
    assert ".intersection-row.same-section" in styles
    assert ".book-index-connections.show-no-interactions" in styles
    assert ".intersection-legend .nearby" not in styles
    assert "grid-template-columns: auto max-content minmax(0,1fr)" in styles
    assert "white-space: nowrap" in styles


def test_time_index_filters_non_temporal_timeline_commentary_without_rewriting_dossiers() -> None:
    root = Path(__file__).parents[1]
    app = (root / "web" / "app.js").read_text(encoding="utf-8")
    index_logic = (root / "web" / "dossier-index.js").read_text(encoding="utf-8")
    assert 'field === "timeline_observations" && !isTemporalDossierObservation(value)' in app
    assert "export function isTemporalDossierObservation(value)" in index_logic
    assert "Dossiers remain untouched" in index_logic


def test_workspace_headings_share_collapse_with_explicit_report_exceptions() -> None:
    app = (Path(__file__).parents[1] / "web" / "app.js").read_text(encoding="utf-8")
    assert "function collapseAnalysisControl()" in app
    assert 'data-collapse-analysis' in app
    section_heading = app.split("function workspaceSectionHeading", 1)[1].split("function taskProgress", 1)[0]
    assert "collapse = true" in section_heading
    assert 'collapse ? collapseAnalysisControl() : ""' in section_heading
    assert 'body.querySelectorAll("details")' in app
    assert 'title: "Connections"' in app
    assert 'title: "Editor PDF"' in app
    assert 'title: "Book summary"' in app
    assert 'title: "Smells report"' in app
    assert 'title: "Emotion map"' in app


def test_explore_reports_are_separate_from_inference_jobs_and_export_one_pdf() -> None:
    root = Path(__file__).parents[1]
    app = (root / "web" / "app.js").read_text(encoding="utf-8")
    styles = (root / "web" / "styles.css").read_text(encoding="utf-8")
    inference_branch = app.split('} else if (activeTab === "inferences") {', 1)[1].split('} else if (activeTab === "summaries") {', 1)[0]
    assert "dossierBookIndexMarkup" not in inference_branch
    assert "questionTrackerTable" not in inference_branch
    assert "inferenceLedgerMarkup(pipeline)" in inference_branch
    assert "function bookSummaryReportMarkup" in app
    assert "function smellsReportMarkup" in app
    assert "function emotionMapReportMarkup" in app
    assert "function editorReportPdf" in app
    assert "data-download-editor-report" in app
    assert "reportableSmells(pipeline)" in app
    assert 'Number(score) >= .10' in app
    assert "--chapter-scale" in app
    assert 'reportExportControl("overview")' in app
    assert 'reportExportControl("emotion-map")' in app
    assert 'data-report-export="${escapeHtml(report)}"' in app
    assert 'data-download-editor-report>Download</button>' in app
    assert 'tocCanvas = newPage("Table of contents")' in app
    assert "drawBookIcon(context" in app
    pdf = app.split("async function editorReportPdf", 1)[1].split("function csvCell", 1)[0]
    assert pdf.index('section("status", "Analysis status"') < pdf.index('section("overview", "Book summary"')
    assert pdf.index('section("overview", "Book summary"') < pdf.index('section("smell-report", "Undismissed Smells"')
    assert '!/^prose$/i.test(String(stage.id || ""))' in pdf
    assert 'color = complete ? "#23765b" : "#b7483f"' in pdf
    assert 'heading("Undismissed Smells", 1)' in pdf
    assert 'currentSection.replace(/(?: · continued)+$/' in pdf
    assert ".shelf-lead-action" in styles
    assert ".emotion-map-track" in styles
    assert ".emotion-map-legend" in styles


def test_workspace_task_explanations_use_shared_rich_icon_tooltip() -> None:
    root = Path(__file__).parents[1]
    app = (root / "web" / "app.js").read_text(encoding="utf-8")
    styles = (root / "web" / "styles.css").read_text(encoding="utf-8")
    assert 'data-tooltip-heading="${escapeHtml(explanationTitle)}"' in app
    assert 'workspaceSectionHeading({icon, title, subtitle, actions, metrics, explanationTitle, explanation, collapse})' in app
    assert 'tooltip.classList.toggle("rich", Boolean(heading))' in app
    assert 'class="task-explanation"' not in app
    assert ".app-tooltip.rich strong" in styles
    assert ".workspace-section-icon.has-help:focus-visible" in styles
    assert ".task-explanation" not in styles


def test_chapter_source_control_lives_with_source_metrics_not_identity() -> None:
    app = (Path(__file__).parents[1] / "web" / "app.js").read_text(encoding="utf-8")
    disclosure = app.split("function analysisDisclosure", 1)[1].split("function openAnalysisDetails", 1)[0]
    chapter_map = app.split("function chapterMapRow", 1)[1].split("function analysisDisclosure", 1)[0]
    assert "function chapterSourceMetadata" in app
    assert 'const identity = `<span class="chapter-heading">' in disclosure
    assert "sourceSequence ? chapterSourceMetadata(sourceSequence, heading, sourceStats) : sourceStats" in disclosure
    assert "metadata: chapterSourceMetadata(chapter.sequence || chapter.number, title, stats)" in chapter_map


def test_primary_navigation_unifies_machine_and_pipeline_with_responsive_status() -> None:
    root = Path(__file__).parents[1]
    page = (root / "web" / "index.html").read_text(encoding="utf-8")
    app = (root / "web" / "app.js").read_text(encoding="utf-8")
    styles = (root / "web" / "styles.css").read_text(encoding="utf-8")
    assert 'id="primary-navigation"' in page
    assert 'id="navigation-toggle"' in page
    assert 'id="navigation-toggle-alert"' in page
    assert 'id="machine-nav"' in page
    assert '<strong>Books</strong><small>Library</small>' in page
    assert 'data-system-panel="machine"' in page
    assert 'data-system-panel="models"' in page
    assert '<h2 id="system-title">Machine</h2>' in page
    assert 'id="models-queue-status"' in page
    assert 'id="local-menu"' not in page
    assert "function updateLocalQueueStatus()" in app
    assert 'openSystemPanel("machine")' in app
    assert 'navigationToggle?.classList.toggle("running", running)' in app
    assert 'primaryNavigation.classList.toggle("open", opening)' in app
    assert '.topbar nav.primary-navigation.open' in styles
    assert '@media (max-width: 1050px)' in styles
    assert "function readinessCheckMarkup(check)" in app
    assert "function legacyMachineChecks(system)" in app
    assert "Showing the checks this server can verify." in app
    assert "machineChecks.map(readinessCheckMarkup)" in app
    assert 'label: "Bookinator server", status: "ready"' in app
    assert 'status === "blocked" ? "!"' in app
    assert 'data-setup-instructions=' in app
    assert 'check.action === "install-pdf-reader"' in app


def test_chapter_boundary_demotion_is_guarded_and_persistently_reversible() -> None:
    app = (Path(__file__).parents[1] / "web" / "app.js").read_text(encoding="utf-8")
    assert "Not a chapter…" in app
    assert "This does not delete any manuscript text." in app
    assert "function chapterBoundaryRecoveryMarkup(pipeline)" in app
    assert "Excluded boundaries panel" in app
    assert 'context: "Restore chapter boundary"' in app


def test_chapter_inspection_is_embedded_in_the_whole_book_disclosure() -> None:
    app = (Path(__file__).parents[1] / "web" / "app.js").read_text(encoding="utf-8")
    styles = (Path(__file__).parents[1] / "web" / "styles.css").read_text(encoding="utf-8")
    assert 'label: "Map"' in app
    assert 'subtitle: "Organized"' in app
    assert 'chapterHeadingInspectionMarkup(pipeline)' in app
    assert 'function chapterHeadingComparisonMarkup' not in app
    assert 'content: `<div class="chapter-map-list">${wholeBookAnalysisRow' in app
    assert 'content: `${chapterBoundaryRecoveryMarkup(pipeline)}${chapterHeadingComparisonMarkup(pipeline)}' not in app
    assert 'class="chapter-map-inspection"' in app
    assert "chapterMapAssessmentMarkup" not in app
    assert ".chapter-map-inspection-verdict" in styles


def test_server_launch_starts_the_library_pipeline_by_default() -> None:
    import bookinator.server.__main__ as server

    pipeline_started = threading.Event()

    class LocalServer:
        def serve_forever(self) -> None:
            assert pipeline_started.wait(timeout=1)
            return None

        def server_close(self) -> None:
            return None

    with patch.object(server, "ThreadingHTTPServer", return_value=LocalServer()), \
         patch.object(server, "start_global_pipeline", side_effect=pipeline_started.set) as start_pipeline, \
         patch.object(server.sys, "argv", ["bookinator"]):
        server.main()
    start_pipeline.assert_called_once_with()


def test_background_pipeline_startup_does_not_block_http_startup() -> None:
    import bookinator.server.__main__ as server

    release_pipeline = threading.Event()
    pipeline_started = threading.Event()

    def blocked_pipeline_start() -> None:
        pipeline_started.set()
        release_pipeline.wait(timeout=1)

    with patch.object(server, "start_global_pipeline", side_effect=blocked_pipeline_start):
        started_at = time.monotonic()
        thread = server.start_background_services()
        elapsed = time.monotonic() - started_at
        assert pipeline_started.wait(timeout=1)
        assert elapsed < 0.25
        assert thread.daemon is True
        assert thread.name == "bookinator-pipeline-startup"
        release_pipeline.set()
        thread.join(timeout=1)


def test_global_pipeline_does_not_load_books_while_holding_queue_lock() -> None:
    import bookinator.server.__main__ as server

    lock_owned_while_loading: list[bool] = []
    book = {"id": "book-1234", "title": "Test book"}

    def find_book(_book_id: str):
        acquired = server.QUEUE_LOCK.acquire(blocking=False)
        lock_owned_while_loading.append(not acquired)
        if acquired:
            server.QUEUE_LOCK.release()
        return book

    with patch.object(server, "set_pipeline_enabled"), \
         patch.object(server, "automatic_queue_books", return_value=[("book-1234", "tags")]), \
         patch.object(server, "save_queue"), \
         patch.object(server, "find_book", side_effect=find_book), \
         patch.object(server, "load_pipeline", return_value={"status": "queued", "queuedAction": "tags"}), \
         patch.object(server, "load_queue_actions", return_value={}), \
         patch.object(server, "QUEUE_THREAD", None), \
         patch.object(server.threading, "Thread") as thread:
        server.QUEUE_ACTIONS.clear()
        server.start_global_pipeline()

    assert lock_owned_while_loading == [False]
    assert server.QUEUE_ACTIONS["book-1234"] == "tags"
    thread.return_value.start.assert_called_once_with()
    server.QUEUE_ACTIONS.clear()


def test_pipeline_steps_own_their_inspectable_run_records() -> None:
    source = (Path(__file__).parents[1] / "web" / "app.js").read_text(encoding="utf-8")
    assert 'data-show-stage-details' in source
    assert 'pipeline-stage-details-template' in source
    assert '["Processing time", liveDurationMarkup' in source
    assert '["Run notes", stage.detail' in source
    assert '<details class="pipeline-record">' not in source
    assert 'class="pipeline-stage-meta"' in source


def test_source_document_stage_shows_format_size_and_download_control() -> None:
    source = (Path(__file__).parents[1] / "web" / "app.js").read_text(encoding="utf-8")
    assert 'function formatByteSize(bytes)' in source
    assert 'class="pipeline-source-facts"' in source
    assert 'class="pipeline-source-download"' in source
    assert '<span>Download</span>' in source


def test_original_source_document_is_preserved_with_download_metadata() -> None:
    import tempfile
    import bookinator.server.__main__ as server

    original = b"PK-original-docx"
    normalized_pdf = b"%PDF-normalized-reading-copy"
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        with patch.object(server, "BOOKS_ROOT", root):
            manuscript_id = server.store_manuscript(
                normalized_pdf,
                "Novel Draft.docx",
                original,
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
            source_path, metadata = server.source_document_path(manuscript_id)
        assert (root / manuscript_id / "manuscript.pdf").read_bytes() == normalized_pdf
        assert source_path and source_path.read_bytes() == original
        assert metadata["sourceFilename"] == "Novel Draft.docx"
        assert metadata["sourceFormat"] == "DOCX"
        assert metadata["sourceSizeBytes"] == len(original)
        assert metadata["sourceOriginalPreserved"] is True


def test_whole_book_rows_are_special_reusable_analysis_rows() -> None:
    source = (Path(__file__).parents[1] / "web" / "app.js").read_text(encoding="utf-8")
    styles = (Path(__file__).parents[1] / "web" / "styles.css").read_text(encoding="utf-8")
    assert 'function wholeBookAnalysisRow' in source
    assert 'class="analysis-row chapter-summary whole-book-analysis' in source
    assert 'wholeBookAnalysisRow(pipeline, "chapters", book)' in source
    assert 'wholeBookAnalysisRow(pipeline, "summaries", book)' in source
    assert 'wholeBookAnalysisRow(pipeline, "dossiers", book)' in source
    assert 'metrics: manuscriptSourceStats' not in source
    assert ".whole-book-analysis.complete .whole-book-status" in styles
    assert "background: var(--green)" in styles.split(
        ".whole-book-analysis.complete .whole-book-status", 1
    )[1].split("}", 1)[0]


def test_chapter_map_overview_contains_names_and_pattern_while_chapter_rows_stay_outside() -> None:
    source = (Path(__file__).parents[1] / "web" / "app.js").read_text(encoding="utf-8")
    assert 'label: "Map"' in source
    assert 'subtitle: "Organized"' in source
    inspection = source.split("function chapterHeadingInspectionMarkup", 1)[1].split("function chapterBoundaryRecoveryMarkup", 1)[0]
    assert "report.topLevel" in inspection
    assert 'class="chapter-heading-comparison"' in inspection
    chapters_view = source.split('} else if (activeTab === "chapters") {', 1)[1].split('} else if (signalView)', 1)[0]
    assert chapters_view.count('wholeBookAnalysisRow(pipeline, "chapters", book)') == 1
    assert 'pipeline.chapters.map((chapter) => chapterMapRow' in chapters_view


def test_chapter_map_rows_have_authoritative_status_badges() -> None:
    source = (Path(__file__).parents[1] / "web" / "app.js").read_text(encoding="utf-8")
    assert 'const mapStatus = frontMatter ? "Excluded"' in source
    assert 'pipeline.chapterMapApproved ? "Approved" : "Proposed"' in source
    assert 'class="chapter-map-status ${mapStatusTone}"' in source


def test_analysis_rows_share_the_three_column_layout_contract() -> None:
    source = (Path(__file__).parents[1] / "web" / "app.js").read_text(encoding="utf-8")
    styles = (Path(__file__).parents[1] / "web" / "styles.css").read_text(encoding="utf-8")
    assert 'function analysisRowColumns({identity, metadata = "", reporting = ""})' in source
    assert source.count("analysisRowColumns({identity, metadata:") >= 3
    assert 'class="analysis-row-columns"' in source
    assert 'class="chapter-map-row analysis-row-columns ${validationTone}"' in source
    assert '.analysis-row-identity' in styles
    assert '.analysis-row-metadata' in styles
    assert '.analysis-row-reporting' in styles


def test_running_details_show_live_duration_and_restart_controls() -> None:
    root = Path(__file__).parents[1]
    app = (root / "web" / "app.js").read_text(encoding="utf-8")
    page = (root / "web" / "index.html").read_text(encoding="utf-8")
    server = (root / "bookinator" / "server" / "__main__.py").read_text(encoding="utf-8")
    assert "function liveDurationMarkup" in app
    assert "data-live-duration" in app
    assert '`${formatRunDuration(elapsed, "running")}+`' in app
    assert 'id="restart-pipeline-stage"' in page
    assert 'refresh.textContent = row.dataset.analysisStatus === "running" ? "Restart" : row.dataset.analysisStatus === "failed" ? "Retry" : "Refresh"' in app
    assert '{"summary", "dossier", "emotion", "tag", "smell", "whole-summary"}' in server


def test_official_ollama_model_error_does_not_ask_for_hugging_face_token() -> None:
    failure = ollama_pull_error("qwen3.5:35b", 500, '{"error":"download failed"}')
    assert failure["kind"] == "ollama-error"
    assert failure["needsHuggingFaceToken"] is False
    assert "download failed" in failure["error"]
    assert "does not need a Hugging Face key" in failure["guidance"]


def test_gated_hugging_face_model_explains_access_token_requirement() -> None:
    failure = ollama_pull_error("hf.co/example/private-model", 403, '{"error":"gated repository"}')
    assert failure["kind"] == "hugging-face-auth"
    assert failure["needsHuggingFaceToken"] is True
    assert failure["helpUrl"] == "https://huggingface.co/settings/tokens"


def test_model_runtime_failure_names_the_model_and_preserves_diagnostic() -> None:
    import urllib.error

    failure = model_runtime_failure("qwen3.5:35b", urllib.error.URLError("connection refused"))
    assert "qwen3.5:35b stopped responding" in failure
    assert "connection refused" in failure


def test_title_from_filename_cleans_separators() -> None:
    assert title_from_filename("the-clockmakers_alibi.pdf") == "the clockmakers alibi"


def test_metadata_model_prefers_small_general_model_families() -> None:
    models = ["qwen2.5:32B", "qwen2.5:14b", "qwen2.5:7b", "deepseek-r1:1.5b"]
    assert choose_metadata_model(models) == "qwen2.5:7b"
    assert model_parameter_billions("qwen2.5:7b") == 7
    assert choose_primary_model(models) == "qwen2.5:32B"
    assert choose_primary_model([*models, "deepseek-r1:latest"]) == "qwen2.5:32B"


def test_large_memory_recommends_large_primary_editor() -> None:
    assert recommended_roles(645)["primary"] == "qwen3.5:122b"


def test_chapters_keep_manuscript_order_regardless_of_title() -> None:
    pages = [
        "CHAPTER TEN\nOpening text.",
        "More chapter ten.",
        "CHAPTER TWO\nOpening text.",
    ]
    chapters, _ = detect_chapters(pages)
    assert [chapter["title"] for chapter in chapters] == ["CHAPTER TEN", "CHAPTER TWO"]
    assert [chapter["sequence"] for chapter in chapters] == [1, 2]
    assert [chapter["pageStart"] for chapter in chapters] == [1, 3]


def test_named_only_chapters_keep_the_all_caps_fallback() -> None:
    chapters, method = detect_chapters([
        "THE LIGHTHOUSE\nOpening text.",
        "More lighthouse.",
        "THE HARBOR\nClosing text.",
    ])
    assert [chapter["title"] for chapter in chapters] == ["THE LIGHTHOUSE", "THE HARBOR"]
    assert method == "opening-line chapter headings"


def test_numbered_chapter_spine_keeps_page_opening_viewpoints_inside_chapters() -> None:
    chapters, method = detect_chapters([
        "CHAPTER 16\nTHE ROAD WARRIORS\nSHADOW\nOpening text.",
        "TIMMY\nA new viewpoint begins on a new PDF page.",
        "More of Timmy's viewpoint.",
        "CHAPTER 17\nTHE FARM\nSHADOW\nNext chapter.",
        "More of the next chapter.",
    ])
    assert [chapter["title"] for chapter in chapters] == ["CHAPTER 16", "CHAPTER 17"]
    assert chapters[0]["pageStart"] == 1
    assert chapters[0]["pageEnd"] == 3
    assert chapters[0]["chapterTitle"] == "THE ROAD WARRIORS"
    assert chapters[0]["sectionMarkers"] == ["SHADOW", "TIMMY"]
    assert method == "explicit opening-line chapter headings"


def test_heading_report_compares_established_chapters_with_excluded_openers() -> None:
    pages = [
        "CHAPTER 1\nARRIVAL\nOpening text.",
        "TIMMY\nA viewpoint begins on a new page.",
        "CHAPTER 2\nDEPARTURE\nNext chapter.",
        "TIMMY\nThe viewpoint returns.",
        "INTERMISSION\nA legitimate unnumbered break.",
    ]
    chapters, _ = detect_chapters(pages)
    report = chapter_heading_report(pages, chapters)
    assert [item["label"] for item in report["topLevel"]] == ["CHAPTER 1", "CHAPTER 2"]
    assert [(item["label"], item["count"]) for item in report["otherCandidates"]] == [("TIMMY", 2), ("INTERMISSION", 1)]
    assert chapter_heading_report_warnings(report) == ["Unique page-opening headings outside the established chapter pattern: INTERMISSION"]


def test_editor_can_promote_a_unique_named_chapter_variant() -> None:
    pages = [
        "CHAPTER 1\nOpening text.",
        "INTERMISSION\nA deliberate structural break.",
        "CHAPTER 2\nNext chapter.",
    ]
    chapters, _ = detect_chapters(pages, ["INTERMISSION"])
    assert [chapter["title"] for chapter in chapters] == ["CHAPTER 1", "INTERMISSION", "CHAPTER 2"]
    assert chapter_heading_report_warnings(chapter_heading_report(pages, chapters, ["INTERMISSION"])) == []


def test_editor_can_demote_and_restore_a_false_chapter_boundary() -> None:
    pages = [
        "CHAPTER 1\nOpening text.",
        "TIMMY\nA viewpoint begins on a new page.",
        "TIMMY\nThe viewpoint returns on another page.",
        "CHAPTER 2\nThis heading was intentionally demoted for the test.",
    ]
    chapters, _ = detect_chapters(pages, demoted_pages=[4])
    assert [chapter["title"] for chapter in chapters] == ["CHAPTER 1"]
    assert chapters[0]["pageEnd"] == 4
    report = chapter_heading_report(pages, chapters, demoted_pages=[4])
    demoted = next(item for item in report["otherCandidates"] if item["label"] == "CHAPTER 2")
    assert demoted["demotedPages"] == [4]
    assert chapter_heading_report_warnings(report) == []

    restored, _ = detect_chapters(pages)
    assert [chapter["title"] for chapter in restored] == ["CHAPTER 1", "CHAPTER 2"]


def test_chapter_map_guard_lists_viewpoint_labels_that_break_numbered_spine() -> None:
    warnings = chapter_map_warnings([
        {"title": "Front matter"}, {"title": "CHAPTER 15"}, {"title": "CHAPTER 16"},
        {"title": "TIMMY"}, {"title": "CHAPTER 17"}, {"title": "SHADOW"},
    ])
    assert warnings == ["Chapter labels outside the established numbered pattern: TIMMY, SHADOW"]


def test_untrusted_chapter_map_invalidates_every_downstream_artifact() -> None:
    pipeline = {
        "status": "complete", "phase": "dossiers-complete", "completedAt": "then",
        "stages": [
            {"id": "structure", "status": "complete"},
            {"id": "chapter-archive", "status": "complete", "completedAt": "then"},
            {"id": "chunking", "status": "complete", "completedAt": "then"},
            {"id": "summaries", "status": "complete", "completedAt": "then"},
            {"id": "dossiers", "status": "complete", "completedAt": "then"},
        ],
        "chapters": [{"title": "TIMMY", "status": "complete", "summary": "Old"}],
        "chunks": [{"id": "one", "dossierStatus": "complete", "dossier": {"synopsis": "Old"}}],
    }
    warnings = ["Chapter labels outside the established numbered pattern: TIMMY"]
    invalidate_downstream_analysis(pipeline, warnings)
    assert pipeline["status"] == "review"
    assert pipeline["chapterMapWarnings"] == warnings
    assert pipeline["chapters"][0]["status"] == "pending"
    assert pipeline["chapters"][0]["stale"] is True
    assert pipeline["chunks"][0]["dossierStatus"] == "pending"
    assert {stage["id"]: stage["status"] for stage in pipeline["stages"]} == {
        "structure": "warning", "chapter-archive": "blocked", "chunking": "blocked",
        "summaries": "blocked", "dossiers": "blocked",
    }


def test_pipeline_dependency_graph_cascades_structure_but_not_summary_siblings() -> None:
    assert pipeline_stage_dependents("structure") == {"chapter-archive", "chunking", "summaries", "emotions", "tags", "smells", "dossiers", "question-tracker", "whole-book-summary", "whole-book-dossier"}
    assert pipeline_stage_dependents("summaries") == {"question-tracker", "whole-book-summary"}
    pipeline = {"stages": [
        {"id": "source", "status": "complete"},
        {"id": "extraction", "status": "complete"},
        {"id": "structure", "status": "complete"},
        {"id": "chapter-archive", "status": "complete"},
        {"id": "chunking", "status": "complete"},
        {"id": "summaries", "status": "complete"},
        {"id": "dossiers", "status": "complete"},
    ]}
    invalidate_pipeline_stage(pipeline, "structure")
    states = {stage["id"]: stage["status"] for stage in pipeline["stages"]}
    assert states == {"source": "complete", "extraction": "complete", "structure": "complete", "chapter-archive": "blocked", "chunking": "blocked", "summaries": "blocked", "dossiers": "blocked"}


def test_restart_archives_provenance_and_returns_every_chapter_to_pending() -> None:
    pipeline = {
        "status": "complete",
        "stages": [{"id": "summaries", "status": "complete", "model": "old-reader", "completedAt": "2026-09-22T10:05:00+00:00"}, {"id": "dossiers", "status": "complete", "model": "dossier-reader"}],
        "chapters": [
            {"title": "One", "status": "complete", "summary": "Old", "model": "old-reader", "startedAt": "2026-09-22T10:00:00+00:00", "completedAt": "2026-09-22T10:01:00+00:00", "durationSeconds": 60, "inputCharacters": 1200},
            {"title": "Two", "status": "pending"},
        ],
    }
    with patch("bookinator.server.__main__.write_pipeline"):
        reset_summary_run({"id": "book"}, pipeline)
    assert [chapter["status"] for chapter in pipeline["chapters"]] == ["pending", "pending"]
    assert "summary" not in pipeline["chapters"][0]
    assert pipeline["chapters"][0]["summaryRuns"][0]["model"] == "old-reader"
    assert pipeline["chapters"][0]["summaryRuns"][0]["durationSeconds"] == 60
    assert pipeline["stages"][0]["status"] == "pending"
    assert pipeline["stages"][1]["status"] == "complete"


def test_dossier_restart_archives_provenance_and_returns_every_chunk_to_pending() -> None:
    pipeline = {
        "status": "complete",
        "stages": [{"id": "summaries", "status": "complete", "model": "summary-reader"}, {"id": "dossiers", "status": "complete", "model": "old-reader"}],
        "chunks": [{"id": "chunk-1", "dossierStatus": "complete", "dossier": {"synopsis": "Old"}, "dossierModel": "old-reader", "dossierCompletedAt": "2026-09-22T10:01:00+00:00", "dossierDurationSeconds": 60}],
    }
    with patch("bookinator.server.__main__.write_pipeline"):
        reset_dossier_run({"id": "book"}, pipeline)
    assert pipeline["chunks"][0]["dossierStatus"] == "pending"
    assert "dossier" not in pipeline["chunks"][0]
    assert pipeline["chunks"][0]["dossierRuns"][0]["dossierModel"] == "old-reader"
    assert pipeline["stages"][0]["status"] == "complete"
    assert pipeline["stages"][1]["status"] == "pending"


def test_progress_describes_paid_manuscript_chapters_when_resuming() -> None:
    pipeline = {
        "runId": "current-pass",
        "chapters": [
            {"title": "Front matter", "status": "running", "runId": "current-pass"},
            {"title": "Chapter 1", "status": "complete", "runId": "older-pass", "durationSeconds": 60},
            {"title": "Chapter 2", "status": "pending"},
        ],
    }
    progress = add_pipeline_progress(pipeline)["progress"]
    assert progress["completed"] == 1
    assert progress["total"] == 2
    assert progress["percent"] == 50
    assert progress["etaSeconds"] == 60


def test_plain_text_manuscript_becomes_a_readable_local_pdf() -> None:
    import pymupdf

    rendered = text_manuscript_to_pdf(b"THE CLOCKMAKER'S ALIBI\n\nby Example Author\n\nChapter One\nThe story begins.")
    with pymupdf.open(stream=rendered, filetype="pdf") as document:
        assert len(document) == 1
        assert "CLOCKMAKER" in document[0].get_text()


def test_docx_text_can_enter_the_same_local_pipeline() -> None:
    import io
    import zipfile

    source = io.BytesIO()
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("word/document.xml", "<w:document><w:body><w:p><w:r><w:t>A DOCX TITLE</w:t></w:r></w:p><w:p><w:r><w:t>by An Author</w:t></w:r></w:p></w:body></w:document>")
    assert b"A DOCX TITLE" in archive_manuscript_text(source.getvalue(), ".docx")


def test_chapter_summary_stream_can_be_cancelled_promptly() -> None:
    import threading

    cancel = threading.Event()

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def __iter__(self):
            yield b'{"message":{"content":"{\\"summary\\":"},"done":false}\n'
            cancel.set()
            yield b'{"message":{"content":"late"},"done":false}\n'

    with patch("bookinator.server.__main__.resident_ollama_models", return_value=set()), patch("bookinator.server.__main__.urllib.request.urlopen", return_value=Response()):
        try:
            summarize_chapter({"title": "One", "text": "Words", "pageStart": 1, "pageEnd": 2}, "reader", cancel)
        except PipelineCancelled:
            pass
        else:
            raise AssertionError("A stopped model stream must not finish the chapter")


def test_active_model_response_can_be_closed_immediately() -> None:
    import bookinator.server.__main__ as server

    class Response:
        closed = False

        def close(self):
            self.closed = True

    response = Response()
    server.ACTIVE_MODEL_RESPONSES["book-1234"] = response
    assert cancel_active_model_response("book-1234") is True
    assert response.closed is True
    assert "book-1234" not in server.ACTIVE_MODEL_RESPONSES


def test_chapter_summary_accepts_common_model_key_variants() -> None:
    result = normalize_chapter_summary({"Chapter Summary": "A useful digest.", "Key Points": ["One"], "NewQuestions": ["Why?"]})
    assert result == {"summary": "A useful digest.", "keyPoints": ["One"], "newQuestions": ["Why?"]}


def test_front_matter_summary_preserves_structure_without_inventing_story_questions() -> None:
    import bookinator.server.__main__ as server

    response = {"summary": "The contents alternate TIMMY and SHADOW labels.", "key_points": ["The labels alternate."], "new_questions": ["Will identity be resolved?"]}
    with patch.object(server, "run_structured_model", return_value=(response, "raw")) as model:
        result = server.summarize_chapter({"title": "Front matter", "text": "CONTENTS\nTIMMY\nSHADOW"}, "reader")
    prompt = model.call_args.args[0]
    assert "Treat it as paratext and structural evidence only" in prompt
    assert "titles are labels, not evidence of plot, theme, mood" in prompt
    assert "alternating TIMMY and SHADOW labels" in prompt
    assert result["summary"] == response["summary"]
    assert result["keyPoints"] == ["The labels alternate."]
    assert result["newQuestions"] == []
    assert result["analysisMode"] == "front-matter-structural"


def test_empty_chapter_summary_is_not_accepted_as_complete() -> None:
    try:
        normalize_chapter_summary({"summary": "", "key_points": []})
    except ValueError as error:
        assert "remains retryable" in str(error)
    else:
        raise AssertionError("An empty model response must not become a completed chapter")


def test_chapter_reader_recovers_from_transient_local_model_disconnects() -> None:
    import urllib.error

    recovered = {"summary": "Recovered.", "keyPoints": [], "newQuestions": []}
    with patch("bookinator.server.__main__.summarize_chapter", side_effect=[urllib.error.URLError("reset"), TimeoutError("slow"), recovered]) as summarize:
        result, failures = summarize_chapter_resilient({"title": "CHAPTER 1", "text": "Words"}, "reader", retry_delays=(0, 0))
    assert result == recovered
    assert summarize.call_count == 3
    assert [failure["attempt"] for failure in failures] == [1, 2]


def test_chapter_reader_exhausts_retries_without_stopping_the_book_worker() -> None:
    import urllib.error

    with patch("bookinator.server.__main__.summarize_chapter", side_effect=urllib.error.URLError("reset")):
        try:
            summarize_chapter_resilient({"title": "CHAPTER 1", "text": "Words"}, "reader", retry_delays=(0, 0))
        except ModelTransportExhausted as error:
            assert len(error.failures) == 3
            assert all("stopped responding during this attempt" in failure["error"] for failure in error.failures)
        else:
            raise AssertionError("Repeated local model disconnects must become an item-level failure")


def test_foreign_live_server_worker_is_not_declared_dead() -> None:
    import bookinator.server.__main__ as server

    server.PIPELINE_THREADS.pop("book-1234", None)
    with patch.object(server.os, "getpid", return_value=100), patch.object(server, "process_is_alive", return_value=True) as alive:
        assert pipeline_worker_is_alive("book-1234", {"workerPid": 200}) is True
    alive.assert_called_once_with(200)


def test_missing_or_dead_worker_is_detected_after_server_exit() -> None:
    import bookinator.server.__main__ as server

    server.PIPELINE_THREADS.pop("book-1234", None)
    with patch.object(server.os, "getpid", return_value=100), patch.object(server, "process_is_alive", return_value=False):
        assert pipeline_worker_is_alive("book-1234", {"workerPid": 200}) is False
        assert pipeline_worker_is_alive("book-1234", {}) is False


def test_global_queue_owner_is_recognized_as_live_worker() -> None:
    import bookinator.server.__main__ as server

    queue_thread = Mock()
    queue_thread.is_alive.return_value = True
    with patch.object(server, "QUEUE_THREAD", queue_thread), \
         patch.object(server, "QUEUE_CURRENT_TASK", {"bookId": "book-1234", "action": "questions"}):
        assert pipeline_worker_is_alive("book-1234", {"workerPid": server.os.getpid()}) is True
        assert pipeline_worker_is_alive("another-book", {"workerPid": server.os.getpid()}) is False


def test_interrupted_question_rollup_is_ready_instead_of_still_running() -> None:
    pipeline = {
        "questionTracker": {
            "status": "running",
            "model": "qwen2.5:32B",
            "startedAt": "2026-09-24T05:37:07+00:00",
            "durationSeconds": 10,
        }
    }

    reset_interrupted_rollup(pipeline, "questions", "The model process ended.")

    assert pipeline["questionTracker"]["status"] == "ready"
    assert pipeline["questionTracker"]["model"] == "qwen2.5:32B"
    assert pipeline["questionTracker"]["error"] == "The model process ended."
    assert "interruptedAt" in pipeline["questionTracker"]
    assert "durationSeconds" not in pipeline["questionTracker"]


def test_refresh_quiesces_the_owning_worker_before_pipeline_mutation() -> None:
    import bookinator.server.__main__ as server

    event = server.threading.Event()
    with patch.object(server, "PIPELINE_CANCEL_EVENTS", {"book-1234": event}), \
         patch.object(server, "pipeline_worker_is_alive", side_effect=[True, False]) as alive, \
         patch.object(server, "cancel_active_model_response", return_value=True) as cancel:
        assert quiesce_pipeline_for_refresh("book-1234", {"status": "running"}, timeout_seconds=.1) is True
    assert event.is_set()
    cancel.assert_called_once_with("book-1234")
    assert alive.call_count == 2
    server.QUEUE_CANCEL_EVENT.clear()


def test_dossier_analysis_preserves_structured_evidence() -> None:
    import bookinator.server.__main__ as server

    response = {
        "synopsis": "A concise account.", "facts": ["A fact"], "events": ["An event"],
        "entities": ["A person"], "locations": ["Union Station"], "current_times": ["Late afternoon"], "questions": ["A question?"], "promises": ["A promise"],
        "timeline_observations": ["Later that day"], "evidence": ["Exact supporting words"],
    }
    with patch("bookinator.server.__main__.run_structured_model", return_value=(response, "raw")):
        result = server.analyze_chunk_dossier({"chapterLabel": "Chapter 1", "text": "Words"}, "model")
    assert result == response


def test_dossier_analysis_retries_one_malformed_structured_response() -> None:
    import bookinator.server.__main__ as server

    response = {
        "synopsis": "A concise account.", "facts": [], "events": [], "entities": [], "locations": [],
        "current_times": [], "questions": [], "promises": [], "timeline_observations": [], "evidence": [],
    }
    malformed = json.JSONDecodeError("Unterminated string", '{"synopsis":"', 12)
    with patch.object(server, "run_structured_model", side_effect=[malformed, (response, "raw")]) as run_model:
        result = server.analyze_chunk_dossier_resilient({"chapterLabel": "Chapter 24", "text": "Words"}, "qwen", retry_delay=0)
    assert run_model.call_count == 2
    assert result["synopsis"] == "A concise account."
    assert result["retryDiagnostics"][0]["error"] == "Malformed dossier JSON: Unterminated string"


def test_dossier_analysis_preserves_all_attempts_when_model_runtime_stays_down() -> None:
    import bookinator.server.__main__ as server

    refused = urllib.error.URLError(ConnectionRefusedError(61, "Connection refused"))
    with patch.object(server, "run_structured_model", side_effect=[refused, refused]):
        with pytest.raises(server.DossierAnalysisExhausted) as failure:
            server.analyze_chunk_dossier_resilient({"chapterLabel": "Chapter 24", "text": "Words"}, "qwen", retry_delay=0)
    assert len(failure.value.failures) == 2
    assert all(item["exceptionType"] == "URLError" for item in failure.value.failures)


def test_dossier_retry_history_accepts_legacy_null_runs() -> None:
    import bookinator.server.__main__ as server

    chunk = {"dossierRuns": None, "dossierModel": "qwen", "dossierStatus": "failed", "dossierError": "Malformed JSON"}
    server.append_dossier_run(chunk)
    assert chunk["dossierRuns"] == [{"dossierModel": "qwen", "dossierStatus": "failed", "dossierError": "Malformed JSON"}]


def test_dossier_refresh_source_updates_pipeline_index_and_chunk_artifact() -> None:
    server = Path(__file__).parents[1] / "bookinator" / "server" / "__main__.py"
    source = server.read_text(encoding="utf-8")
    assert 'matching = [chunk for chunk in pipeline.get("chunks", []) if int(chunk.get("sequence") or 0) == sequence]' in source
    assert 'artifact["dossierStatus"] = "pending"' in source
    assert 'write_chunk_artifact(book, int(chunk.get("sequence") or sequence), artifact)' in source


def test_refresh_ui_immediately_relabels_an_accepted_failure_as_waiting() -> None:
    app = (Path(__file__).parents[1] / "web" / "app.js").read_text(encoding="utf-8")
    assert 'const statusLabel = status === "pending" ? "waiting" : status;' in app
    assert "function markAnalysisResultWaiting(kind, id)" in app
    assert "markAnalysisResultWaiting(kind, id);" in app


def test_front_matter_dossier_cannot_turn_titles_into_story_obligations() -> None:
    import bookinator.server.__main__ as server

    response = {
        "synopsis": "A table of contents alternates two labels.", "facts": ["TIMMY and SHADOW alternate."],
        "events": ["Timmy confronts Shadow."], "entities": ["TIMMY", "SHADOW"], "locations": [],
        "current_times": ["The story begins at night."], "questions": ["Who is Shadow?"],
        "promises": ["Story promise: Shadow will be revealed."], "timeline_observations": ["The titles imply a chronology."],
        "evidence": ["TIMMY / SHADOW"],
    }
    with patch.object(server, "run_structured_model", return_value=(response, "raw")) as model:
        result = server.analyze_chunk_dossier({"chapterLabel": "Front matter", "text": "CONTENTS\nTIMMY\nSHADOW"}, "reader")
    prompt = model.call_args.args[0]
    assert "Treat it as paratext and structural evidence only" in prompt
    assert "never manufacture them from a table of contents" in prompt
    assert result["facts"] == ["TIMMY and SHADOW alternate."]
    assert result["events"] == result["questions"] == result["promises"] == []
    assert result["current_times"] == result["timeline_observations"] == []
    assert result["analysisMode"] == "front-matter-structural"


def test_front_matter_signal_views_explain_why_they_are_not_scored() -> None:
    app = (Path(__file__).parents[1] / "web" / "app.js").read_text(encoding="utf-8")
    server = (Path(__file__).parents[1] / "bookinator" / "server" / "__main__.py").read_text(encoding="utf-8")
    assert "Front matter is structural evidence, not narrative prose." in app
    assert "front-matter-not-applicable" in server
    assert "Narrative analysis does not produce trustworthy scores" in server


def test_emotion_peaks_open_exact_classifier_windows_in_chapter_source() -> None:
    root = Path(__file__).parents[1]
    app = (root / "web" / "app.js").read_text(encoding="utf-8")
    styles = (root / "web" / "styles.css").read_text(encoding="utf-8")
    assert "function emotionPeakSourceMarkup(chapter, focus)" in app
    assert 'data-view-emotion-peak' in app
    assert 'segment.characterStart' in app
    assert 'segment.characterEnd' in app
    assert 'openChapterSource(book.id, chapter.sequence || chapter.number, {...segment' in app
    assert "paragraph-aware windows of roughly 1,200 characters" in app
    assert 'id="emotion-source-peak"' in app
    assert ".emotion-source-focus mark" in styles
    assert "function chapterTextOverlays(chapter, text)" in app
    assert "function annotatedChapterTextMarkup(text, overlays, regions = [])" in app
    assert 'data-analysis-settings="emotion"' in app
    assert 'data-analysis-settings="tag"' in app
    assert 'data-toggle-source-signals' not in app
    assert ".text-signal-marker" in styles


def test_chapter_tags_are_grouped_into_functional_hunks() -> None:
    root = Path(__file__).parents[1]
    app = (root / "web" / "app.js").read_text(encoding="utf-8")
    styles = (root / "web" / "styles.css").read_text(encoding="utf-8")
    assert "Atmosphere & meaning" in app
    assert "Structure & perspective" in app
    assert "Experience & momentum" in app
    assert 'families: ["mood", "genre_affinity", "theme_topic"]' in app
    assert 'families: ["viewpoint", "narrated_time", "chapter_function"]' in app
    assert 'families: ["prose_mode", "reader_dynamics"]' in app
    assert 'class="tag-clusters"' in app
    assert 'class="tag-cluster-hitters"' in app
    assert '<details class="tag-cluster' in app
    assert '<details class="tag-family"' in app
    assert '<details class="tag-candidates">' in app
    assert "not used in maps or manuscript markers" in app
    assert 'details[data-analysis-key][open]' in app
    assert ".tag-cluster-families" in styles
    assert "width: max-content" in styles


def test_emotion_presentation_keeps_full_map_but_filters_low_signal_icons() -> None:
    app = (Path(__file__).parents[1] / "web" / "app.js").read_text(encoding="utf-8")
    emotion_view = app.split("function emotionResultMarkup", 1)[1].split("function tagResultMarkup", 1)[0]
    overlays = app.split("function chapterTextOverlays", 1)[1].split("function annotatedChapterTextMarkup", 1)[0]
    assert "const EMOTION_DISTRIBUTION_DISPLAY_THRESHOLD = .05" in app
    assert "const EMOTION_PEAK_DISPLAY_THRESHOLD = .25" in app
    assert "mapLabels.map" in emotion_view
    assert "displayedLabels.map" in emotion_view
    assert "displayedLabels.sort" not in emotion_view
    assert 'class="emotion-distribution-region"' in emotion_view
    assert 'class="emotion-peak-diamond"' in emotion_view
    assert "Strongest passage ${peakScore}%" in emotion_view
    assert "segmentPeaks" in emotion_view
    assert "Number(peak.score) >= EMOTION_PEAK_DISPLAY_THRESHOLD" in emotion_view
    assert "Number(peak.score) > 0" in overlays
    assert 'data-analysis-settings="emotion"' in app
    assert 'data-analysis-settings="tag"' in app
    assert 'data-analysis-preset="10">Balanced 10%' in app
    assert 'data-analysis-preset="50">Material 50%' in app
    assert "sourceAnalysisPreferences" in app
    assert "function wireSourceMarkerCutoff(body)" in app
    assert 'data-source-marker-score=' in app
    assert "function emotionTextRegions(chapter, text)" in app
    assert "data-analysis-neutral" in app
    assert 'emotion-${escapeHtml(region.label)}' in app
    assert 'data-emotion-region-score=' in app
    assert ".show-emotion-regions .emotion-region:not(.below-cutoff)" in (Path(__file__).parents[1] / "web" / "styles.css").read_text(encoding="utf-8")
    assert 'copy?.classList.toggle("show-emotion-regions", emotion.enabled)' in app
    assert 'data-emotion-peak-excerpt' in emotion_view
    assert "function hydrateEmotionPeakPreview(button, bookId)" in app


def test_manuscript_metrics_count_reflowed_structure() -> None:
    metrics = manuscript_text_metrics("# CHAPTER 1\n\nFirst paragraph.\n\nSecond paragraph.")
    assert {key: metrics[key] for key in ("wordCount", "characterCount", "paragraphCount", "lineCount")} == {
        "wordCount": 6, "characterCount": 48, "paragraphCount": 3, "lineCount": 3,
    }
    assert metrics["sentenceCount"] == 2
    assert metrics["averageSentenceWords"] == 2.0
    assert metrics["sentenceLengthVariation"] == 0.0


def test_chapter_title_and_viewpoint_markers_preserve_authored_order() -> None:
    text = """10

CHAPTER 2
HAPPY BIRTHDAY

TIMMY

Opening prose.

DOWNTOWN!!

SHADOW

More prose.

TIMMY
"""
    assert chapter_structure(text, "CHAPTER 2") == {
        "chapterTitle": "HAPPY BIRTHDAY",
        "sectionMarkers": ["TIMMY", "SHADOW", "TIMMY"],
    }


def test_chapter_structure_reads_canonical_markdown_without_leaking_hashes() -> None:
    text = """# CHAPTER 1

## SHADOW

### SHADOW

Opening prose.
"""
    assert chapter_structure(text, "CHAPTER 1") == {
        "chapterTitle": "SHADOW",
        "sectionMarkers": [],
    }


def test_chapters_are_materialized_as_separate_local_objects() -> None:
    import tempfile
    from pathlib import Path

    chapters = [
        {"sequence": 1, "title": "CHAPTER 1", "pageStart": 1, "pageEnd": 4, "text": "One"},
        {"sequence": 2, "title": "CHAPTER 2", "pageStart": 5, "pageEnd": 9, "text": "Two"},
    ]
    with tempfile.TemporaryDirectory() as directory:
        root_path = Path(directory)
        with patch("bookinator.server.__main__.BOOKS_ROOT", root_path):
            archive = ensure_chapter_artifacts({"id": "book-1234", "manuscriptId": "manuscript-1234"}, chapters)
        root = root_path / "manuscript-1234" / "chapters"
        assert archive["saved"] is True
        assert archive["count"] == 2
        assert (root / "0001.json").is_file()
        assert (root / "0002.json").is_file()
        assert (root / "0001.md").read_text().startswith("# CHAPTER 1\n")
        assert (root / "0002.md").read_text().startswith("# CHAPTER 2\n")
        assert (root / "manifest.json").is_file()


def test_pdf_line_joining_preserves_word_boundaries_and_hyphens() -> None:
    assert join_pdf_lines(["This line wraps", "between words."]) == "This line wraps between words."
    assert join_pdf_lines(["an ear-", "shaking noise"]) == "an ear-shaking noise"
    assert normalize_pdf_text("A wrapped\nparagraph.\n\n14\n\nA second\nparagraph.") == "A wrapped paragraph.\n\nA second paragraph."


def test_chapter_markdown_has_semantic_heading_levels_and_no_page_numbers() -> None:
    chapter = {
        "sequence": 3, "title": "CHAPTER 3", "chapterTitle": "NAVY PIER", "sectionMarkers": ["TIMMY"],
        "text": "CHAPTER 3\n\nNAVY PIER\n\n22\n\nTIMMY\n\nTimmy looked out\nover the lake.",
    }
    assert chapter_markdown(chapter) == "# CHAPTER 3\n\n## NAVY PIER\n\n### TIMMY\n\nTimmy looked out over the lake.\n"


def test_chapter_markdown_does_not_repeat_title_as_first_section_marker() -> None:
    chapter = {
        "sequence": 1, "title": "CHAPTER 1", "chapterTitle": "SHADOW", "sectionMarkers": ["SHADOW"],
        "text": "CHAPTER 1\n\nSHADOW\n\nSHADOW\n\nOpening prose.",
    }
    assert chapter_markdown(chapter) == "# CHAPTER 1\n\n## SHADOW\n\nOpening prose.\n"


def test_pdf_block_geometry_joins_visual_lines_but_preserves_paragraphs() -> None:
    pages = [
        [(72, 10, 500, 20, "First visual line\n"), (72, 30, 500, 40, "continues here.\n"), (108, 50, 500, 60, "Indented paragraph\n")],
        [(72, 10, 500, 20, "continues on next page.\n"), (72, 30, 90, 40, "14\n"), (72, 50, 500, 60, " \nA blank-line paragraph.\n")],
    ]
    assert pdf_blocks_to_paragraph_text(pages) == "First visual line continues here.\n\nIndented paragraph continues on next page.\n\nA blank-line paragraph."


def test_saved_chapter_source_can_be_loaded_for_inspection() -> None:
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        manuscript = root / "manuscript-1234"
        manuscript.mkdir()
        (manuscript / "extracted-chapters.json").write_text(json.dumps([{"sequence": 2, "title": "# CHAPTER 2", "chapterTitle": "## HAPPY BIRTHDAY", "sectionMarkers": ["### TIMMY"], "pageStart": 10, "pageEnd": 21, "text": "# CHAPTER 2\n\n## HAPPY BIRTHDAY\n\n### TIMMY\n\nOpening prose."}]))
        with patch("bookinator.server.__main__.BOOKS_ROOT", root):
            chapter = load_chapter_source({"manuscriptId": "manuscript-1234"}, 2)
        assert chapter["title"] == "CHAPTER 2"
        assert chapter["chapterTitle"] == "HAPPY BIRTHDAY"
        assert chapter["sectionMarkers"] == ["TIMMY"]
        assert chapter["text"].endswith("Opening prose.")


def test_pipeline_write_removes_markdown_syntax_from_display_metadata() -> None:
    import tempfile
    from pathlib import Path

    pipeline = {
        "chapters": [{
            "title": "\ufeff # CHAPTER 2",
            "chapterTitle": "## HAPPY BIRTHDAY",
            "sectionMarkers": ["### TIMMY", "SHADOW"],
        }],
    }
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        with patch("bookinator.server.__main__.BOOKS_ROOT", root):
            write_pipeline({"manuscriptId": "manuscript-1234"}, pipeline)
        saved = json.loads((root / "manuscript-1234" / "pipeline.json").read_text())
    chapter = saved["chapters"][0]
    assert chapter["title"] == "CHAPTER 2"
    assert chapter["chapterTitle"] == "HAPPY BIRTHDAY"
    assert chapter["sectionMarkers"] == ["TIMMY", "SHADOW"]


def test_chunks_keep_page_provenance_and_overlap_at_boundaries() -> None:
    chapters = [{"sequence": 1, "title": "CHAPTER 1", "chapterTitle": "ARRIVAL", "pageStart": 1, "pageEnd": 3}]
    chunks = page_bounded_chunks(chapters, ["A" * 20, "B" * 20, "C" * 20], target_characters=45)
    assert [(chunk["pageStart"], chunk["pageEnd"]) for chunk in chunks] == [(1, 2), (2, 3)]
    assert chunks[1]["overlap"] == "one-page"
    assert all(chunk["chapterTitle"] == "ARRIVAL" for chunk in chunks)


def test_queue_worker_claims_continue_arriving_while_it_is_finishing() -> None:
    import bookinator.server.__main__ as server

    calls = []

    def process_book(book_id: str, **_kwargs) -> None:
        calls.append(book_id)
        if len(calls) == 1:
            # This reproduces Continue arriving while the existing worker is
            # still alive but has already processed this durable queue member.
            server.QUEUE_ACTIONS[book_id] = "summarize"

    server.QUEUE_CANCEL_EVENT.clear()
    server.QUEUE_ACTIONS.clear()
    server.QUEUE_ACTIONS["book-1234"] = "summarize"
    with patch.object(server, "load_queue", return_value=["book-1234"]), patch.object(server, "find_book", return_value={"id": "book-1234"}), patch.object(server, "load_pipeline", return_value={"chapters": [{"status": "pending"}]}), patch.object(server, "run_book_chapter_pipeline", side_effect=process_book):
        server.run_library_queue()
    server.PIPELINE_THREADS.pop("book-1234", None)
    server.PIPELINE_CANCEL_EVENTS.pop("book-1234", None)
    assert calls == ["book-1234", "book-1234"]


def test_global_queue_uses_chapter_pipeline_even_when_first_pending_work_is_dossiers() -> None:
    import bookinator.server.__main__ as server

    server.QUEUE_ACTIONS.clear()
    server.QUEUE_CANCEL_EVENT.clear()
    server.QUEUE_THREAD = None
    with patch.object(server, "set_pipeline_enabled"), \
         patch.object(server, "automatic_queue_books", return_value=[("book-1234", "dossiers")]), \
         patch.object(server, "save_queue"), \
         patch.object(server, "find_book", return_value={"id": "book-1234"}), \
         patch.object(server, "load_pipeline", return_value={"status": "ready"}), \
         patch.object(server, "load_queue_actions", return_value={}), \
         patch.object(server.threading, "Thread") as thread:
        queued = server.start_global_pipeline()
    assert queued == [("book-1234", "dossiers")]
    assert server.QUEUE_ACTIONS["book-1234"] == "chapter-pipeline"
    thread.assert_called_once()


def test_global_queue_preserves_explicit_dossier_refresh_across_restart() -> None:
    import bookinator.server.__main__ as server

    server.QUEUE_ACTIONS.clear()
    server.QUEUE_CANCEL_EVENT.clear()
    server.QUEUE_THREAD = None
    with patch.object(server, "set_pipeline_enabled"), \
         patch.object(server, "automatic_queue_books", return_value=[("book-1234", "dossiers")]), \
         patch.object(server, "save_queue"), \
         patch.object(server, "find_book", return_value={"id": "book-1234"}), \
         patch.object(server, "load_pipeline", return_value={"status": "queued", "queuedAction": "dossiers"}), \
         patch.object(server, "load_queue_actions", return_value={}), \
         patch.object(server.threading, "Thread"):
        server.start_global_pipeline()
    assert server.QUEUE_ACTIONS["book-1234"] == "dossiers"


def test_global_queue_restores_durable_questions_request_across_restart() -> None:
    import bookinator.server.__main__ as server

    server.QUEUE_ACTIONS.clear()
    server.QUEUE_CANCEL_EVENT.clear()
    server.QUEUE_THREAD = None
    with patch.object(server, "set_pipeline_enabled"), \
         patch.object(server, "automatic_queue_books", return_value=[("book-1234", "tags")]), \
         patch.object(server, "save_queue"), \
         patch.object(server, "find_book", return_value={"id": "book-1234"}), \
         patch.object(server, "load_pipeline", return_value={"status": "running", "phase": "tags"}), \
         patch.object(server, "load_queue_actions", return_value={"book-1234": "questions"}), \
         patch.object(server.threading, "Thread"):
        server.start_global_pipeline()
    assert server.QUEUE_ACTIONS["book-1234"] == "questions"


def test_prioritizing_running_pipeline_persists_requested_action(tmp_path: Path) -> None:
    import bookinator.server.__main__ as server

    class ActiveQueue:
        @staticmethod
        def is_alive() -> bool:
            return True

    server.QUEUE_ACTIONS.clear()
    actions_path = tmp_path / "pipeline-actions.json"
    with patch.object(server, "QUEUE_ACTIONS_PATH", actions_path), \
         patch.object(server, "find_book", return_value={"id": "book-1234"}), \
         patch.object(server, "load_pipeline", return_value={"status": "running", "phase": "tags"}), \
         patch.object(server, "load_queue", return_value=[]), \
         patch.object(server, "save_queue"), \
         patch.object(server, "set_pipeline_enabled"), \
         patch.object(server, "QUEUE_THREAD", ActiveQueue()):
        visible = server.prioritize_pipeline_action("book-1234", "questions")
        client = server.pipeline_for_client("book-1234", visible)

    assert json.loads(actions_path.read_text()) == {"book-1234": "questions"}
    assert client["phase"] == "tags"
    assert client["queuedAction"] == "questions"
    assert client["explicitActionQueued"] is True
    server.QUEUE_ACTIONS.clear()


def test_automatic_queue_resume_runs_all_chapter_steps_not_one_whole_stage() -> None:
    import bookinator.server.__main__ as server

    server.QUEUE_ACTIONS.clear()
    server.QUEUE_CANCEL_EVENT.clear()
    calls = []
    with patch.object(server, "load_queue", side_effect=[["book-1234"], []]), \
         patch.object(server, "find_book", return_value={"id": "book-1234"}), \
         patch.object(server, "load_pipeline", return_value={"chapters": [{"status": "complete"}]}), \
         patch.object(server, "next_pipeline_action", return_value="dossiers"), \
         patch.object(server, "run_book_chapter_pipeline", side_effect=lambda book_id, **kwargs: calls.append((book_id, kwargs))):
        server.run_library_queue()
    assert calls == [("book-1234", {})]


def test_book_worker_runs_each_chapter_through_dependency_order_before_advancing() -> None:
    import bookinator.server.__main__ as server

    pipeline = {
        "chapters": [
            {"sequence": 1, "status": "pending", "emotionStatus": "pending", "tagStatus": "pending"},
            {"sequence": 2, "status": "pending", "emotionStatus": "pending", "tagStatus": "pending"},
        ],
        "chunks": [
            {"sequence": 1, "chapterSequence": 1, "dossierStatus": "pending"},
            {"sequence": 2, "chapterSequence": 2, "dossierStatus": "pending"},
        ],
    }
    calls = []
    rollup_ran = False

    def summarize(_book_id: str, chapter_sequence: int | None = None) -> None:
        calls.append(("summaries", chapter_sequence))
        pipeline["chapters"][chapter_sequence - 1]["status"] = "complete"

    def dossier(_book_id: str, chapter_sequence: int | None = None) -> None:
        calls.append(("dossiers", chapter_sequence))
        next(chunk for chunk in pipeline["chunks"] if chunk["chapterSequence"] == chapter_sequence)["dossierStatus"] = "complete"

    def signal(_book_id: str, kind: str, chapter_sequence: int | None = None) -> None:
        calls.append(({"emotion": "emotions", "tag": "tags", "smell": "smells"}[kind], chapter_sequence))
        pipeline["chapters"][chapter_sequence - 1][f"{kind}Status"] = "complete"

    def ready_rollups(_book_id: str) -> None:
        nonlocal rollup_ran
        if not rollup_ran and all(chapter["status"] == "complete" for chapter in pipeline["chapters"]):
            calls.append(("summary-rollup", None))
            rollup_ran = True

    server.QUEUE_CANCEL_EVENT.clear()
    with patch.object(server, "find_book", return_value={"id": "book-1234"}), \
         patch.object(server, "load_pipeline", return_value=pipeline), \
         patch.object(server, "run_summary_pipeline", side_effect=summarize), \
         patch.object(server, "run_chapter_signal_pipeline", side_effect=signal), \
         patch.object(server, "run_dossier_pipeline", side_effect=dossier), \
         patch.object(server, "run_ready_stage_rollups", side_effect=ready_rollups):
        server.run_book_chapter_pipeline("book-1234")
    server.PIPELINE_THREADS.pop("book-1234", None)
    server.PIPELINE_CANCEL_EVENTS.pop("book-1234", None)
    assert calls == [("summaries", 1), ("dossiers", 1), ("emotions", 1), ("tags", 1), ("summaries", 2), ("summary-rollup", None), ("dossiers", 2), ("emotions", 2), ("tags", 2)]


def test_summary_rollup_requires_summaries_but_not_independent_analysis_passes() -> None:
    pipeline = {
        "stages": [
            {"id": "chapter-archive", "status": "complete"},
            {"id": "summaries", "status": "complete"},
            {"id": "emotions", "status": "pending"},
            {"id": "tags", "status": "pending"},
            {"id": "dossiers", "status": "pending"},
        ],
        "chapters": [{"sequence": 1, "title": "CHAPTER 1", "status": "complete", "summary": "Arrival.", "keyPoints": ["A"], "newQuestions": ["Why?"], "model": "reader", "completedAt": "2026-09-23T12:00:00Z"}],
        "chunks": [{"chapterSequence": 1, "dossierStatus": "pending"}],
    }
    assert pipeline_stage_ready(pipeline, "whole-book-summary") is True
    assert add_pipeline_progress(pipeline)["wholeBookSummary"]["status"] == "ready"
    assert stage_rollup_action(pipeline) == "whole-summary"
    signature = stage_rollup_input_signature(pipeline, "summary")
    pipeline["wholeBookSummary"] = {"status": "complete", "inputSignature": signature}
    assert stage_rollup_action(pipeline) == ""
    pipeline["chapters"][0]["summary"] = "A changed arrival."
    assert stage_rollup_action(pipeline) == "whole-summary"


def test_ready_rollup_precedes_independent_tags() -> None:
    book = {"id": "book-1234", "manuscriptId": "manuscript", "priority": "normal"}
    pipeline = {
        "stages": [
            {"id": "chapter-archive", "status": "complete"},
            {"id": "summaries", "status": "complete"},
            {"id": "dossiers", "status": "complete"},
            {"id": "emotions", "status": "complete"},
            {"id": "tags", "status": "pending"},
        ],
        "chapters": [{"sequence": 1, "title": "CHAPTER 1", "status": "complete", "summary": "Arrival.", "emotionStatus": "complete", "tagStatus": "pending"}],
        "chunks": [{"sequence": 1, "chapterSequence": 1, "dossierStatus": "complete", "dossier": {"synopsis": "Arrival."}}],
    }

    assert next_pipeline_action(book, pipeline) == "whole-summary"


def test_dossier_rollup_follows_complete_chunk_dossiers() -> None:
    pipeline = {
        "stages": [
            {"id": "chapter-archive", "status": "complete"},
            {"id": "summaries", "status": "complete"},
            {"id": "dossiers", "status": "complete"},
        ],
        "chapters": [{"sequence": 1, "title": "CHAPTER 1", "status": "complete", "summary": "Arrival."}],
        "chunks": [{"sequence": 1, "chapterSequence": 1, "chunkInChapter": 1, "dossierStatus": "complete", "dossier": {"synopsis": "Arrival.", "facts": ["A"]}}],
    }
    summary_signature = stage_rollup_input_signature(pipeline, "summary")
    pipeline["wholeBookSummary"] = {"status": "complete", "inputSignature": summary_signature}

    assert pipeline_stage_ready(pipeline, "whole-book-dossier") is True
    assert stage_rollup_action(pipeline) == "whole-dossier"
    dossier_signature = stage_rollup_input_signature(pipeline, "dossier")
    pipeline["wholeBookDossier"] = {"status": "complete", "inputSignature": dossier_signature}
    assert stage_rollup_action(pipeline) == ""


def test_stale_whole_book_run_does_not_hide_active_chapter_work() -> None:
    pipeline = {
        "status": "running",
        "phase": "tags",
        "stages": [
            {"id": "summaries", "status": "complete", "model": "reader"},
            {"id": "dossiers", "status": "pending"},
            {"id": "emotions", "status": "pending"},
            {"id": "tags", "status": "running", "model": "tagger"},
        ],
        "chapters": [{"title": "CHAPTER 1", "tagStatus": "running"}],
        "wholeBookSummary": {"status": "running", "model": "reader"},
    }
    activity = pipeline_activity({"title": "Shadow"}, pipeline)
    assert activity["phase"] == "tags"
    assert "tagger" in activity["text"]


def test_summary_rollup_waits_when_any_chapter_summary_is_not_current() -> None:
    pipeline = {
        "stages": [{"id": "summaries", "status": "running"}],
        "chapters": [
            {"sequence": 1, "title": "CHAPTER 1", "status": "complete", "summary": "Ready."},
            {"sequence": 2, "title": "CHAPTER 2", "status": "failed", "summary": ""},
        ],
    }
    assert stage_rollup_input_signature(pipeline, "summary") == ""
    assert stage_rollup_action(pipeline) == ""
    assert add_pipeline_progress(pipeline)["wholeBookSummary"]["status"] == "blocked"


def test_prioritizing_preparation_persists_queued_state_and_wakes_worker() -> None:
    import bookinator.server.__main__ as server

    class Worker:
        started = False
        def is_alive(self): return False
        def start(self): self.started = True

    worker = Worker()
    pipeline = {"status": "ready", "stages": [], "chapters": []}
    with patch.object(server, "find_book", return_value={"id": "book-1234", "manuscriptId": "ms-1234"}), \
         patch.object(server, "load_queue", return_value=[]), patch.object(server, "save_queue") as save_queue, \
         patch.object(server, "set_pipeline_enabled"), \
         patch.object(server, "load_pipeline", return_value=pipeline), patch.object(server, "write_pipeline") as write_pipeline, \
         patch.object(server, "persist_queue_action") as persist_queue_action, \
         patch.object(server.threading, "Thread", return_value=worker), patch.object(server, "QUEUE_THREAD", None):
        queued = server.prioritize_pipeline_action("book-1234", "prepare")
    assert queued["status"] == "queued"
    assert queued["queuedAction"] == "prepare"
    save_queue.assert_called_once_with(["book-1234"])
    write_pipeline.assert_called_once()
    persist_queue_action.assert_called_once_with("book-1234", "prepare")
    assert worker.started is True


def test_emotion_segments_preserve_paragraph_boundaries_and_overlap() -> None:
    import bookinator.server.__main__ as server
    text = "First paragraph has feeling.\n\nSecond paragraph carries the scene.\n\nThird paragraph changes it again."
    segments = server.emotion_segments({"text": text, "pageStart": 4, "pageEnd": 5}, target_characters=35)
    assert len(segments) >= 2
    assert segments[0]["text"].endswith("Second paragraph carries the scene.")
    assert segments[1]["text"].startswith("Second paragraph carries the scene.")
    assert all(segment["pageStart"] == 4 and segment["pageEnd"] == 5 for segment in segments)


def test_chapter_tags_require_known_evidence_bearing_signals() -> None:
    import bookinator.server.__main__ as server
    response = {
        "signals": [{"id": "investigation", "family": "prose_mode", "score": .75, "confidence": .8, "explanation": "The character searches for an answer.", "evidence": [{"quote": "She checked every locked room."}]}],
        "candidate_signals": [],
    }
    with patch.object(server, "run_structured_model", return_value=(response, "{}")):
        artifact = server.analyze_chapter_tags({"sequence": 2, "title": "CHAPTER 1", "text": "She checked every locked room."}, "qwen")
    assert artifact["schema"] == "bookinator-chapter-tags-v1"
    assert artifact["signals"][0]["id"] == "investigation"
    assert artifact["signals"][0]["evidence"][0]["quote"] == "She checked every locked room."


def test_chapter_tag_schema_requires_evidence_for_every_returned_signal() -> None:
    import bookinator.server.__main__ as server
    schema = server.chapter_tag_schema()
    signal = schema["properties"]["signals"]["items"]
    assert signal["properties"]["score"]["minimum"] == .25
    assert signal["properties"]["evidence"]["minItems"] == 1
    assert server.TAG_PROMPT_VERSION == "chapter-tags-v2"


def test_chapter_tags_accept_family_scoped_duplicate_signal_ids() -> None:
    import bookinator.server.__main__ as server
    response = {
        "signals": [
            {"id": "mystery", "family": "reader_dynamics", "score": .5, "confidence": .8, "explanation": "An answer is withheld.", "evidence": [{"quote": "No one knew who opened the door."}]},
            {"id": "mystery", "family": "genre_affinity", "score": .5, "confidence": .7, "explanation": "The chapter uses mystery conventions.", "evidence": [{"quote": "No one knew who opened the door."}]},
        ],
        "candidate_signals": [],
    }
    with patch.object(server, "run_structured_model", return_value=(response, "{}")):
        artifact = server.analyze_chapter_tags({"sequence": 2, "title": "CHAPTER 1", "text": "No one knew who opened the door."}, "qwen")
    assert [(signal["family"], signal["id"]) for signal in artifact["signals"]] == [("reader_dynamics", "mystery"), ("genre_affinity", "mystery")]


def test_chapter_tags_correct_unique_family_mismatches_without_failing_the_chapter() -> None:
    import bookinator.server.__main__ as server
    response = {
        "signals": [
            {"id": "confrontation", "family": "reader_dynamics", "score": .75, "confidence": .9, "explanation": "The opponents finally meet.", "evidence": [{"quote": "They faced each other across the pier."}]},
            {"id": "action", "family": "prose_mode", "score": .75, "confidence": .8, "explanation": "The scene moves quickly.", "evidence": [{"quote": "She ran."}]},
        ],
        "candidate_signals": [],
    }
    with patch.object(server, "run_structured_model", return_value=(response, "{}")):
        artifact = server.analyze_chapter_tags({"sequence": 3, "title": "CHAPTER 3", "text": "They faced each other across the pier. She ran."}, "qwen")
    assert [(signal["family"], signal["id"]) for signal in artifact["signals"]] == [("chapter_function", "confrontation"), ("prose_mode", "action")]
    assert artifact["normalizedSignals"] == [{"id": "confrontation", "fromFamily": "reader_dynamics", "toFamily": "chapter_function"}]
    assert artifact["rejectedSignals"] == []


def test_chapter_tags_retain_unknown_or_unsupported_labels_as_candidates() -> None:
    import bookinator.server.__main__ as server
    response = {
        "signals": [
            {"id": "showdown_energy", "family": "reader_dynamics", "score": .75, "confidence": .8, "explanation": "Not fixed vocabulary.", "evidence": [{"quote": "They circled."}]},
            {"id": "tension", "family": "reader_dynamics", "score": .75, "confidence": .8, "explanation": "No receipt.", "evidence": []},
        ],
        "candidate_signals": [],
    }
    with patch.object(server, "run_structured_model", return_value=(response, "{}")):
        artifact = server.analyze_chapter_tags({"sequence": 3, "title": "CHAPTER 3", "text": "They circled."}, "qwen")
    assert artifact["signals"] == []
    assert [item["label"] for item in artifact["candidateSignals"]] == ["showdown_energy", "tension"]
    assert len(artifact["rejectedSignals"]) == 2


def test_chapter_tags_retry_one_malformed_structured_response() -> None:
    import bookinator.server.__main__ as server
    response = {
        "signals": [{"id": "action", "family": "prose_mode", "score": .75, "confidence": .8, "explanation": "The scene moves quickly.", "evidence": [{"quote": "She ran."}]}],
        "candidate_signals": [],
    }
    malformed = json.JSONDecodeError("Unterminated string", '{"signals":["', 12)
    with patch.object(server, "run_structured_model", side_effect=[malformed, (response, "{}")] ) as run_model:
        artifact = server.analyze_chapter_tags_resilient({"sequence": 3, "title": "CHAPTER 3", "text": "She ran."}, "qwen")
    assert run_model.call_count == 2
    assert artifact["signals"][0]["id"] == "action"
    assert artifact["retryDiagnostics"][0]["attempt"] == 1


def test_current_tag_contract_requeues_legacy_failures_once() -> None:
    import bookinator.server.__main__ as server
    pipeline = {
        "stages": [{"id": "tags", "label": "Chapter tags", "status": "warning"}],
        "chapters": [{"title": "CHAPTER 3", "tagStatus": "failed", "tagError": "The tagger returned an unknown or mismatched signal: confrontation."}],
    }
    server.ensure_signal_stages(pipeline)
    chapter = pipeline["chapters"][0]
    assert chapter["tagStatus"] == "pending"
    assert chapter["tagFailurePromptVersion"] == server.TAG_PROMPT_VERSION
    assert "tagError" not in chapter

    chapter.update({"tagStatus": "failed", "tagError": "Still malformed"})
    server.ensure_signal_stages(pipeline)
    assert chapter["tagStatus"] == "failed"


def test_available_tag_model_repairs_stale_setup_block() -> None:
    import bookinator.server.__main__ as server
    pipeline = {
        "status": "blocked",
        "phase": "tags-blocked",
        "error": "Assign or install a local tag model.",
        "tagModel": "qwen2.5:32B",
        "stages": [{"id": "tags", "label": "Chapter tags", "status": "blocked", "setupRequired": True}],
        "chapters": [{"title": "CHAPTER 1", "tagStatus": "pending"}],
    }
    with patch.object(server, "ollama_status", return_value={"running": True, "models": ["qwen2.5:32B"]}), patch.object(server, "load_settings", return_value={}):
        server.ensure_signal_stages(pipeline)
    tags = next(stage for stage in pipeline["stages"] if stage["id"] == "tags")
    assert tags["status"] == "pending"
    assert "setupRequired" not in tags
    assert pipeline["status"] == "ready"
    assert pipeline["phase"] == "chapter-complete"
    assert "error" not in pipeline


def test_signal_queue_ignores_front_matter_status() -> None:
    import bookinator.server.__main__ as server
    book = {"id": "book-1234", "manuscriptId": "manuscript", "priority": "normal"}
    stages = [
        {"id": "extraction", "status": "complete"}, {"id": "chapter-archive", "status": "complete"},
        {"id": "emotions", "status": "blocked"}, {"id": "tags", "status": "complete"},
    ]
    pipeline = {
        "stages": stages,
        "chapters": [
            {"title": "Front matter", "status": "complete", "emotionStatus": "pending", "tagStatus": "failed"},
            {"title": "CHAPTER 1", "status": "complete", "emotionStatus": "pending", "tagStatus": "complete"},
        ],
        "chunks": [],
    }
    with patch.object(server, "stage_rollup_action", return_value=""):
        assert next_pipeline_action(book, pipeline) == ""


def test_chapter_pipeline_yields_to_new_priority_at_chapter_boundary() -> None:
    import bookinator.server.__main__ as server
    book = {"id": "book-1234", "manuscriptId": "manuscript", "priority": "normal"}
    pipeline = {
        "stages": [{"id": "tags", "status": "pending"}],
        "chapters": [
            {"sequence": 1, "title": "CHAPTER 1", "status": "complete", "tagStatus": "pending"},
            {"sequence": 2, "title": "CHAPTER 2", "status": "complete", "tagStatus": "pending"},
        ],
        "chunks": [],
    }
    server.QUEUE_ACTIONS.clear()
    try:
        def run_first_chapter(book_id: str, kind: str, chapter_sequence: int | None = None) -> None:
            server.QUEUE_ACTIONS[book_id] = "tags"

        with patch.object(server, "find_book", return_value=book), patch.object(server, "load_pipeline", return_value=pipeline), patch.object(server, "run_chapter_signal_pipeline", side_effect=run_first_chapter) as run_signal:
            server.run_book_chapter_pipeline(book["id"], summaries=False, emotions=False, tags=True, smells=False, dossiers=False)
        run_signal.assert_called_once_with(book["id"], "tag", chapter_sequence=1)
    finally:
        server.QUEUE_ACTIONS.clear()


def test_smells_preserve_all_evidence_and_checkpoint_editorial_batches() -> None:
    findings = [
        {"detector": "spacy", "rule": "many-clauses", "message": "Many clauses.", "sentenceStart": 0, "sentenceEnd": 25, "sentence": "This sentence winds around."},
        {"detector": "bookinator", "rule": "sentence-length", "message": "Long sentence.", "sentenceStart": 0, "sentenceEnd": 25, "sentence": "This sentence winds around."},
    ]
    checkpoints = []

    def judge(_prompt, _model, _schema, _cancel_event, _run_key):
        return {"judgments": [{"id": server.hashlib.sha256(b"0:25:This sentence winds around.").hexdigest()[:16], "verdict": "report", "severity": "medium", "issue": "Clause overload", "reason": "The sentence obscures its main action."}]}, "raw"

    with patch.object(server, "analyze_prose_smells", return_value={"findings": findings, "errors": {}}), patch.object(server, "run_structured_model", side_effect=judge):
        artifact = server.analyze_chapter_smells({"text": "This sentence winds around."}, "editor-model", on_batch=lambda item: checkpoints.append(item))

    assert artifact["schema"] == "bookinator-smells-v1"
    assert artifact["kept"] == 1
    assert artifact["candidates"][0]["detectors"] == ["bookinator", "spacy"]
    assert len(artifact["candidates"][0]["evidence"]) == 2
    assert checkpoints[0]["reviewProgress"] == {"completedBatches": 0, "totalBatches": 1, "complete": False}
    assert checkpoints[-1]["reviewProgress"] == {"completedBatches": 1, "totalBatches": 1, "complete": True}


def test_smells_keep_local_candidates_but_do_not_claim_complete_when_editor_review_fails() -> None:
    findings = [{"detector": "spacy", "rule": "garden-path", "message": "Possible garden path.", "sentenceStart": 0, "sentenceEnd": 16, "sentence": "While reading fell."}]
    with patch.object(server, "analyze_prose_smells", return_value={"findings": findings, "errors": {}}), patch.object(server, "run_structured_model", side_effect=RuntimeError("connection refused")):
        artifact = server.analyze_chapter_smells({"text": "While reading fell."}, "editor-model")

    assert artifact["reviewProgress"] == {"completedBatches": 1, "totalBatches": 1, "complete": False}
    assert artifact["reviewErrors"][0]["error"] == "connection refused"
    assert "judgment" not in artifact["candidates"][0]
