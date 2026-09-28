import json
import io
import shutil
import subprocess
import threading
import time
import urllib.error
import zipfile
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from bookinator.server.__main__ import API_FEATURES, DOCS_ROOT, ModelTransportExhausted, PipelineCancelled, add_pipeline_progress, aggregate_manuscript_metrics, archive_manuscript_metadata_and_images, archive_manuscript_text, assigned_model_roles, automatic_queue_books, cancel_active_model_response, chapter_heading_report, chapter_heading_report_warnings, chapter_map_warnings, chapter_markdown, chapter_structure, choose_metadata_model, choose_primary_model, detect_chapters, development_limited_items, ensure_chapter_artifacts, front_matter_metadata, global_pipeline_diagnostics, global_pipeline_estimate, infer_manuscript_icon, infer_manuscript_identity, invalidate_downstream_analysis, invalidate_pipeline_stage, join_pdf_lines, load_chapter_source, manuscript_text_metrics, model_parameter_billions, model_runtime_failure, next_pipeline_action, normalize_book_priority, normalize_chapter_summary, normalize_pdf_text, ollama_pull_error, page_bounded_chunks, pdf_blocks_to_paragraph_text, pipeline_activity, pipeline_stage_dependents, pipeline_stage_ready, pipeline_worker_is_alive, prioritize_pipeline_action, queue_ids_by_current_priority, quiesce_pipeline_for_refresh, recommended_roles, refresh_followup_action, reset_analysis_after_sequence, reset_dossier_run, reset_inactive_whole_book_runs, reset_interrupted_rollup, reset_summary_run, stage_rollup_action, stage_rollup_input_signature, summarize_chapter, summarize_chapter_resilient, system_status, text_manuscript_to_pdf, title_from_filename, write_pipeline
import bookinator.server.__main__ as server


def test_markdown_front_matter_is_explicit_identity() -> None:
    source = b'---\ntitle: The Dunwich Horror\nauthor: "H. P. Lovecraft"\nsource: Gutenberg\n---\n\n# Wrong Nearby Heading\n'
    assert front_matter_metadata(source) == {"title": "The Dunwich Horror", "author": "H. P. Lovecraft"}


def test_complete_authoritative_metadata_skips_model_inference() -> None:
    with patch("bookinator.server.__main__.urllib.request.urlopen") as urlopen:
        identity = infer_manuscript_identity(
            "THE SHOGGONLINE by H.P. LOVECRAFT",
            {"title": "The Dunwich Horror", "author": "H. P. Lovecraft"},
            ["qwen3.5:9b"],
            metadata_authoritative=True,
        )
    assert identity["title"] == "The Dunwich Horror"
    assert identity["author"] == "H. P. Lovecraft"
    assert identity["abbreviation"] == "DH"
    urlopen.assert_not_called()


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


def test_epub_text_follows_spine_and_preserves_numeric_chapter_headings() -> None:
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w") as archive:
        archive.writestr("META-INF/container.xml", '<?xml version="1.0"?><container xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles><rootfile full-path="OEBPS/package.opf"/></rootfiles></container>')
        archive.writestr("OEBPS/package.opf", '<?xml version="1.0"?><package xmlns="http://www.idpf.org/2007/opf"><manifest><item id="second" href="second.xhtml" media-type="application/xhtml+xml"/><item id="first" href="first.xhtml" media-type="application/xhtml+xml"/></manifest><spine><itemref idref="first"/><itemref idref="second"/></spine></package>')
        archive.writestr("OEBPS/first.xhtml", '<html><body><div class="h1">1</div><h2>FIRST CASE</h2><p>First paragraph.</p><p>Second paragraph.</p></body></html>')
        archive.writestr("OEBPS/second.xhtml", '<html><body><div class="h1">2</div><h2>SECOND CASE</h2><p>Third paragraph.</p></body></html>')

    text = archive_manuscript_text(payload.getvalue(), ".epub").decode("utf-8")
    pages = server.source_text_to_pages(text, target_characters=80)
    chapters, method = detect_chapters(pages)

    assert text.index("FIRST CASE") < text.index("SECOND CASE")
    assert "First paragraph.\n\nSecond paragraph." in text
    assert [chapter["title"] for chapter in chapters] == ["1", "2"]
    assert [chapter["chapterTitle"] for chapter in chapters] == ["FIRST CASE", "SECOND CASE"]
    assert method == "explicit opening-line chapter headings"
    assert chapter_heading_report_warnings(chapter_heading_report(pages, chapters)) == []
    first = chapter_markdown(chapters[0])
    assert first.count("## FIRST CASE") == 1


def test_epub_semantic_rule_preserves_styled_chapter_paragraphs() -> None:
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w") as archive:
        archive.writestr("META-INF/container.xml", '<?xml version="1.0"?><container xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles><rootfile full-path="OPS/package.opf"/></rootfiles></container>')
        archive.writestr("OPS/package.opf", '<?xml version="1.0"?><package xmlns="http://www.idpf.org/2007/opf"><manifest><item id="story" href="story.xhtml" media-type="application/xhtml+xml"/></manifest><spine><itemref idref="story"/></spine></package>')
        archive.writestr("OPS/story.xhtml", '''<html><body>
          <p>Opening matter.</p>
          <hr class="chap"/><p class="ph2">CHAPTER I</p><p>First chapter.</p>
          <p>Enough intervening prose that the next heading is not naturally a virtual-page opener.</p>
          <hr class="chapter"/><p class="display">CHAPTER II</p><p>Second chapter.</p>
        </body></html>''')

    text = archive_manuscript_text(payload.getvalue(), ".epub").decode("utf-8")
    pages = server.source_text_to_pages(text, target_characters=10_000)
    chapters, method = detect_chapters(pages, fixed_pagination=False)

    assert "## CHAPTER I" in text
    assert "## CHAPTER II" in text
    assert [chapter["title"] for chapter in chapters] == ["Front matter", "CHAPTER I", "CHAPTER II"]
    assert method == "explicit opening-line chapter headings"


def test_epub_first_chapter_heading_discards_book_title_prefix() -> None:
    markup = '''<html><head><title>BOOK TITLE CHAPTER I FIRST CASE</title></head><body>
      <h2><span>BOOK TITLE</span><br/><span>CHAPTER I</span><br/><span>FIRST CASE</span></h2>
      <p>First chapter.</p><hr class="chap"/><p>CHAPTER II</p><p>Second chapter.</p>
    </body></html>'''
    text = server.html_manuscript_to_markdown(markup)
    pages = server.source_text_to_pages(text, target_characters=10_000)
    chapters, _ = detect_chapters(pages, fixed_pagination=False)

    assert "BOOK TITLE CHAPTER I" not in text
    assert [chapter["title"] for chapter in chapters] == ["CHAPTER I", "CHAPTER II"]
    assert chapters[0]["chapterTitle"] == "FIRST CASE"
    assert chapters[0]["text"].rstrip().endswith("First chapter.")
    assert "CHAPTER II" not in chapters[0]["text"]


def test_epub_license_document_title_does_not_truncate_epilogue() -> None:
    markup = '''<html><head><title>THE FULL PROJECT GUTENBERG™ LICENSE</title></head><body>
      <hr class="chap"/><p class="ph2">Epilogue</p><p>The authored ending.</p>
      <div class="pg-boilerplate pgheader footer">THE FULL PROJECT GUTENBERG™ LICENSE</div>
    </body></html>'''
    text = server.html_manuscript_to_markdown(markup)

    assert "## Epilogue" in text
    assert "The authored ending." in text
    assert "FULL PROJECT GUTENBERG" not in text


def test_epub_trailing_other_books_catalogue_does_not_pollute_final_chapter() -> None:
    markup = '''<html><body><div class="chapter">
      <h2>CHAPTER XVI. Conclusion</h2><p>The authored ending.</p>
      <hr style="width: 25%;"/>
      <p class="letter">Other books by J. Sheridan LeFanu<br/><br/>
      Green Tea and Other Stories<br/>Carmilla and Other Classic Tales</p>
    </div><div/></body></html>'''
    text = server.html_manuscript_to_markdown(markup)

    assert "The authored ending." in text
    assert "Other books by" not in text
    assert "Green Tea and Other Stories" not in text


def test_epub_appendices_are_analyzable_role_marked_divisions() -> None:
    markup = '''<html><body>
      <h2>CHAPTER I</h2><p>The chapter.</p>
      <h2>FOREWORD TO APPENDIX</h2><p>Why this material matters.</p>
      <h2>APPENDIX A</h2><p>Substantive supporting material.</p>
    </body></html>'''
    text = server.html_manuscript_to_markdown(markup)
    pages = server.source_text_to_pages(text, target_characters=10_000)
    chapters, _ = detect_chapters(pages, fixed_pagination=False)

    assert [chapter["title"] for chapter in chapters] == ["CHAPTER I", "FOREWORD TO APPENDIX", "APPENDIX A"]
    assert [chapter["analysisRole"] for chapter in chapters] == ["chapter", "appendix", "appendix"]


def test_markdown_numeric_headings_and_paragraphs_survive_native_extraction() -> None:
    source = """---
title: The Dunwich Horror
---

# The Dunwich Horror

Opening matter.

## 1

First paragraph wraps
across source lines.

Second paragraph remains separate.

## 2

The next chapter begins.
"""
    pages = server.source_text_to_pages(source, target_characters=70)
    chapters, method = detect_chapters(pages)
    canonical = [chapter_markdown(chapter) for chapter in chapters]

    assert [chapter["title"] for chapter in chapters] == ["Front matter", "1", "2"]
    assert method == "explicit opening-line chapter headings"
    assert "First paragraph wraps across source lines.\n\nSecond paragraph remains separate." in canonical[1]
    assert "The next chapter begins." in canonical[2]


def test_plain_text_chapter_headings_survive_virtual_pagination() -> None:
    source = """A title page and introductory material.

CHAPTER I

THE FIRST TEST

""" + ("First chapter prose. " * 40) + """

CHAPTER II

THE SECOND TEST

Second chapter prose.
"""
    pages = server.source_text_to_pages(source, target_characters=90, preserve_plain_headings=True)
    chapters, method = detect_chapters(pages, fixed_pagination=False, allow_bare_numerals=True)

    assert [chapter["title"] for chapter in chapters] == ["Front matter", "CHAPTER I", "CHAPTER II"]
    assert "First chapter prose." in chapters[1]["text"]
    assert "Second chapter prose." in chapters[2]["text"]
    assert method == "explicit opening-line chapter headings"


def test_duplicate_markup_and_visible_heading_count_as_one_boundary() -> None:
    pages = [
        "CHAPTER I A BEGINNING\n\n## CHAPTER I A BEGINNING\n\nFirst chapter.",
        "CHAPTER II AN ENDING\n\n## CHAPTER II AN ENDING\n\nSecond chapter.",
    ]
    chapters, _ = detect_chapters(pages, fixed_pagination=False, allow_bare_numerals=True)
    assert [chapter["title"] for chapter in chapters] == ["CHAPTER I A BEGINNING", "CHAPTER II AN ENDING"]


def test_plain_text_contents_column_header_is_not_a_chapter() -> None:
    source = """CONTENTS

CHAPTER PAGE

CHAPTER I

First chapter.

CHAPTER II

Second chapter.
"""
    chapters, _ = detect_chapters(server.source_text_to_pages(source, target_characters=40, preserve_plain_headings=True), fixed_pagination=False)
    assert [chapter["title"] for chapter in chapters] == ["Front matter", "CHAPTER I", "CHAPTER II"]


def test_plain_text_contents_chapter_page_row_is_not_a_chapter() -> None:
    source = """CONTENTS

CHAPTER I.               PAGE

THE FIRST CHAPTER           1

CHAPTER I

THE FIRST CHAPTER

First chapter prose.

CHAPTER II

Second chapter prose.
"""
    pages = server.source_text_to_pages(source, target_characters=500, preserve_plain_headings=True)
    chapters, _ = detect_chapters(pages, fixed_pagination=False)
    assert [chapter["title"] for chapter in chapters] == ["Front matter", "CHAPTER I", "CHAPTER II"]


def test_contents_block_does_not_swallow_first_real_chapter_heading() -> None:
    source = """CONTENTS

CHAPTER I.      THE BEGINNING       1

CHAPTER II.     THE END             9

CHAPTER I.

THE BEGINNING

First chapter prose.

CHAPTER II.

THE END

Second chapter prose.
"""
    pages = server.source_text_to_pages(source, target_characters=500, preserve_plain_headings=True)
    chapters, _ = detect_chapters(pages, fixed_pagination=False)

    assert [chapter["title"] for chapter in chapters] == ["Front matter", "CHAPTER I.", "CHAPTER II."]
    assert "First chapter prose." in chapters[1]["text"]


def test_repeated_plain_text_roman_numerals_form_a_reflowable_spine() -> None:
    source = """A title page.

I

First chapter prose.

II

Second chapter prose.

III

Third chapter prose.
"""
    pages = server.source_text_to_pages(source, target_characters=40, preserve_plain_headings=True)
    chapters, method = detect_chapters(pages, fixed_pagination=False, allow_bare_numerals=True)
    assert [chapter["title"] for chapter in chapters] == ["Front matter", "I", "II", "III"]
    assert method == "explicit opening-line chapter headings"


def test_one_plain_text_roman_numeral_does_not_create_a_spine() -> None:
    source = "An unchaptered work.\n\nI\n\nA decorative section marker."
    pages = server.source_text_to_pages(source, target_characters=40, preserve_plain_headings=True)
    chapters, _ = detect_chapters(pages, fixed_pagination=False, allow_bare_numerals=True)
    assert [chapter["title"] for chapter in chapters] == ["Entirety"]


def test_plain_text_year_is_not_mixed_into_roman_chapter_spine() -> None:
    source = """1906

Publication note.

I

First chapter.

II

Second chapter.
"""
    pages = server.source_text_to_pages(source, target_characters=40, preserve_plain_headings=True)
    chapters, _ = detect_chapters(pages, fixed_pagination=False, allow_bare_numerals=True)
    assert [chapter["title"] for chapter in chapters] == ["Front matter", "I", "II"]


def test_sentence_beginning_with_roman_letters_is_not_a_roman_heading() -> None:
    source = """I

First chapter.

Mill. There in the shadow he stopped.

II

Second chapter.
"""
    pages = server.source_text_to_pages(source, target_characters=40, preserve_plain_headings=True)
    chapters, _ = detect_chapters(pages, fixed_pagination=False, allow_bare_numerals=True)
    assert [chapter["title"] for chapter in chapters] == ["I", "II"]


def test_preserved_markdown_source_is_preferred_over_converted_pdf(tmp_path: Path) -> None:
    manuscript_id = "native-source"
    root = tmp_path / manuscript_id
    root.mkdir()
    (root / "source.json").write_text(json.dumps({"filename": "story.md", "storedAs": "source.md"}), encoding="utf-8")
    (root / "source.md").write_text("## 1\n\nExact first paragraph.\n\nExact second paragraph.\n", encoding="utf-8")
    (root / "manuscript.pdf").write_bytes(b"synthetic preview is not canonical")

    with patch.object(server, "BOOKS_ROOT", tmp_path):
        pages = server.native_manuscript_pages({"manuscriptId": manuscript_id})

    assert pages == ["## 1\n\nExact first paragraph.\n\nExact second paragraph."]


def test_complete_book_bundle_round_trip_and_collision_policy(tmp_path: Path) -> None:
    origin_books = tmp_path / "origin" / "books"
    origin_reports = tmp_path / "origin" / "reports"
    book_id = "book-original-1234"
    manuscript_id = "manuscript-original-1234"
    project = origin_books / manuscript_id
    project.mkdir(parents=True)
    (project / "source.md").write_text("## 1\n\nComplete source text.\n", encoding="utf-8")
    (project / "source.json").write_text(json.dumps({"filename": "story.md", "storedAs": "source.md"}), encoding="utf-8")
    (project / "manuscript.pdf").write_bytes(b"PDF preview")
    (project / "pipeline.json").write_text(json.dumps({"bookId": book_id, "status": "complete", "chapters": [{"sequence": 1, "summary": "Everything."}]}), encoding="utf-8")
    (project / "annotations.json").write_text(json.dumps([{"id": "note-12345678", "body": "Keep this."}]), encoding="utf-8")
    (project / "reviewer-signoff.json").write_text(json.dumps({"status": "complete", "reviewerName": "Randal"}), encoding="utf-8")
    report = origin_reports / book_id
    report.mkdir(parents=True)
    (report / "index.json").write_text(json.dumps([{"id": "a" * 32, "format": "html"}]), encoding="utf-8")
    (report / f"{'a' * 32}.html").write_text("<html>Saved report</html>", encoding="utf-8")
    book = {"id": book_id, "manuscriptId": manuscript_id, "title": "Same Title", "author": "One Author", "icon": {"kind": "image", "value": "data:image/png;base64,AAAA"}, "priority": "normal"}

    with patch.object(server, "BOOKS_ROOT", origin_books), patch.object(server, "REPORTS_ROOT", origin_reports):
        bundle = server.build_library_bundle([book])

    with zipfile.ZipFile(io.BytesIO(bundle)) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["schema"] == "bookinator-project-v2"
        assert manifest["contents"] == {
            "sourceDocuments": True,
            "analysis": True,
            "chapterAndChunkArtifacts": True,
            "annotationsAndSignoff": True,
            "savedReports": True,
        }
        assert f"books/{manuscript_id}/source.md" in archive.namelist()
        assert f"books/{manuscript_id}/annotations.json" in archive.namelist()
        assert f"reports/{book_id}/{'a' * 32}.html" in archive.namelist()

    destination = tmp_path / "destination"
    destination_books = destination / "books"
    destination_reports = destination / "reports"
    destination_library = destination / "library.json"
    destination_books.mkdir(parents=True)
    other_project = destination_books / "different-manuscript-1234"
    other_project.mkdir()
    (other_project / "pipeline.json").write_text("{}", encoding="utf-8")
    destination_library.write_text(json.dumps([{
        "id": "different-book-1234", "manuscriptId": "different-manuscript-1234", "title": "Same Title", "author": "Another Author", "priority": "normal"
    }]), encoding="utf-8")

    with patch.object(server, "BOOKS_ROOT", destination_books), patch.object(server, "REPORTS_ROOT", destination_reports), patch.object(server, "LIBRARY_PATH", destination_library):
        with pytest.raises(server.ImportTitleCollision) as collision:
            server.import_library_bundle(bundle)
        assert collision.value.collisions[0]["title"] == "Same Title"
        assert collision.value.collisions[0]["suggestedTitle"].startswith("Same Title (Imported ")

        first = server.import_library_bundle(bundle, {book_id: "Same Title (Imported test)"})
        assert first["imported"] == 1
        assert first["collisions"] == [{
            "kind": "renamed-import",
            "title": "Same Title",
            "importedAs": "Same Title (Imported test)",
            "message": "Same Title was imported as Same Title (Imported test).",
        }]
        imported = next(item for item in server.load_library() if item["id"] == book_id)
        assert imported["title"] == "Same Title (Imported test)"
        assert imported["icon"]["value"] == "data:image/png;base64,AAAA"
        assert imported["importedAt"]
        assert imported["ingestedAt"] == imported["importedAt"]
        assert (destination_books / manuscript_id / "source.md").read_text(encoding="utf-8") == "## 1\n\nComplete source text.\n"
        assert json.loads((destination_books / manuscript_id / "pipeline.json").read_text(encoding="utf-8"))["bookId"] == book_id
        assert (destination_books / manuscript_id / "annotations.json").is_file()
        assert (destination_books / manuscript_id / "reviewer-signoff.json").is_file()
        assert (destination_reports / book_id / f"{'a' * 32}.html").is_file()

        with pytest.raises(server.ImportTitleCollision):
            server.import_library_bundle(bundle)
        second = server.import_library_bundle(bundle, {book_id: "Same Title (Restored again)"})
        assert second["imported"] == 1
        assert second["collisions"][0]["kind"] == "renamed-import"
        assert second["books"][0]["title"] == "Same Title (Restored again)"
        assert second["books"][0]["id"] != book_id
        assert second["books"][0]["manuscriptId"] != manuscript_id


def test_library_bundle_filename_describes_one_or_many_books() -> None:
    exported_on = "2026-09-24"

    assert server.library_bundle_filename([{"title": "Shadow"}], exported_on) == "bookinator-shadow-2026-09-24.bookinator"
    assert server.library_bundle_filename([{"title": "The Dunwich Horror!"}], exported_on) == "bookinator-the_dunwich_horror-2026-09-24.bookinator"
    assert server.library_bundle_filename([{}, {}, {}], exported_on) == "bookinator-3_books-2026-09-24.bookinator"


def test_mislabeled_legacy_json_bookinator_export_is_recovered(tmp_path: Path) -> None:
    books_root = tmp_path / "books"
    library_path = tmp_path / "library.json"
    books_root.mkdir()
    library_path.write_text("[]", encoding="utf-8")
    legacy = {
        "schema": "bookinator-library-v1",
        "books": [{
            "id": "old-shadow-id",
            "title": "Shadow",
            "author": "Michael Donaubauer",
            "analysis": {"bookId": "old-shadow-id", "status": "complete", "chapters": []},
        }],
    }

    with patch.object(server, "BOOKS_ROOT", books_root), patch.object(server, "LIBRARY_PATH", library_path):
        result = server.import_library_bundle(json.dumps(legacy).encode())

        assert result["legacy"] is True
        assert result["imported"] == 1
        assert "did not contain the original source document" in result["warning"]
        imported = server.load_library()[0]
        assert imported["title"] == "Shadow"
        assert imported["sourceAvailable"] is False
        assert imported["importedAt"] == imported["ingestedAt"]
        pipeline = json.loads((books_root / imported["manuscriptId"] / "pipeline.json").read_text(encoding="utf-8"))
        assert pipeline["bookId"] == imported["id"]


def test_legacy_import_collision_writes_nothing_until_title_is_unique(tmp_path: Path) -> None:
    books_root = tmp_path / "books"
    library_path = tmp_path / "library.json"
    books_root.mkdir()
    library_path.write_text(json.dumps([{"id": "existing-shadow", "manuscriptId": "existing-manuscript", "title": "Shadow"}]), encoding="utf-8")
    legacy = {"schema": "bookinator-library-v1", "books": [{"id": "old-shadow", "title": "Shadow", "analysis": {"status": "complete"}}]}

    with patch.object(server, "BOOKS_ROOT", books_root), patch.object(server, "LIBRARY_PATH", library_path):
        with pytest.raises(server.ImportTitleCollision) as collision:
            server.import_legacy_library_export(legacy)
        assert collision.value.collisions[0]["suggestedTitle"].startswith("Shadow (Imported ")
        assert list(books_root.iterdir()) == []

        result = server.import_legacy_library_export(legacy, {"old-shadow": "Shadow restored"})
        assert result["books"][0]["title"] == "Shadow restored"
        assert len(list(books_root.iterdir())) == 1


def test_book_bundle_rejects_path_traversal(tmp_path: Path) -> None:
    payload = io.BytesIO()
    content = b"bad"
    manifest = {
        "schema": "bookinator-project-v2",
        "books": [],
        "files": [{"path": "../outside.txt", "bytes": len(content), "sha256": server.hashlib.sha256(content).hexdigest()}],
    }
    with zipfile.ZipFile(payload, "w") as archive:
        archive.writestr("manifest.json", json.dumps(manifest))
        archive.writestr("../outside.txt", content)
    with pytest.raises(ValueError, match="unsafe file path"):
        server.import_library_bundle(payload.getvalue())


def test_text_pdf_pagination_does_not_drop_late_source_text() -> None:
    import pymupdf

    source = ("A complete paragraph with enough words to wrap safely.\n\n" * 300 + "FINAL SENTINEL").encode()
    rendered = text_manuscript_to_pdf(source)
    with pymupdf.open(stream=rendered, filetype="pdf") as document:
        page_count = len(document)
        extracted = "\n".join(page.get_text() for page in document)
    assert page_count > 1
    assert "FINAL SENTINEL" in extracted


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
    assert status["models"]["roleLabels"] == {"primary": "Primary reader", "fast": "Fast intake & utilities"}
    assert set(status["models"]["roles"]) == {"primary", "fast"}


def test_analysis_ui_does_not_offer_per_task_model_overrides() -> None:
    root = Path(__file__).parents[1]
    app = (root / "web" / "app.js").read_text(encoding="utf-8")
    page = (root / "web" / "index.html").read_text(encoding="utf-8")
    styles = (root / "web" / "styles.css").read_text(encoding="utf-8")
    assert "data-open-task-model" not in app
    assert "openTaskModelDialog" not in app
    assert "reader-model-dialog" not in page
    assert ".model-control-button" not in styles


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


def test_two_global_model_roles_accept_legacy_assignments_during_transition() -> None:
    import bookinator.server.__main__ as server

    assert server.configured_primary_model({"readerModel": "legacy-reader"}) == "legacy-reader"
    assert server.configured_primary_model({"primaryModel": "new-primary", "readerModel": "legacy-reader"}) == "new-primary"
    assert server.configured_fast_model({"intakeModel": "legacy-fast"}) == "legacy-fast"
    assert server.configured_fast_model({"fastModel": "new-fast", "intakeModel": "legacy-fast"}) == "new-fast"


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


def test_completed_retry_drops_stale_child_and_stage_errors() -> None:
    import bookinator.server.__main__ as server

    pipeline = {
        "status": "running", "phase": "cumulative-context",
        "stages": [{"id": "llm-review", "status": "pending", "error": "Unterminated string"}],
        "chapters": [{"sequence": 1, "llmReviewStatus": "complete", "llmReviewError": "Unterminated string"}],
        "chunks": [],
    }

    assert server.reconcile_orphaned_child_runs(pipeline) is True
    assert "llmReviewError" not in pipeline["chapters"][0]
    assert "error" not in pipeline["stages"][0]


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
    assert 'data-pipeline-selection-action="top"' in page
    assert 'data-pipeline-selection-action="raise"' in page
    assert 'data-pipeline-selection-action="lower"' in page
    assert 'data-pipeline-selection-action="pause"' in page
    assert 'data-pipeline-selection-action="resume"' in page
    assert 'data-pipeline-selection-action="remove"' not in page
    assert 'id="pipeline-page-size"' in page
    assert 'id="pipeline-page-previous"' in page
    assert 'id="pipeline-page-next"' in page
    assert '<option value="5">5</option><option value="10">10</option><option value="25">25</option><option value="50">50</option><option value="all">All</option>' in page
    assert 'id="pipeline-attention-button"' in page
    assert 'id="pipeline-selection-count"' in page.split('class="pipeline-queue-footer"', 1)[1]
    assert 'const pageTasks = tasks.slice(pageStart, pageStart + pageLimit)' in app
    assert 'pageTasks.forEach((task) => state.pipelineSelection.add(task.id))' in app
    assert 'localStorage.setItem(pipelinePageSizeKey' in app
    assert 'pipelinePageSize = 10' in app
    assert 'scrollIntoView({behavior: "smooth", block: "start"})' in app
    assert 'data-select-pipeline-task' in app
    assert 'function pipelineTasks()' in app
    assert 'activity.bookId === item.bookId' in app
    assert '{...item, action: activityAction, task: activity.task || item.task}' in app
    assert 'action: "whole-dossier"' in app
    assert 'action: "questions"' in app
    assert 'postLibraryAction("/api/library/pipeline/task-state"' in app
    assert 'id="library-pipeline-progress"' in page
    assert 'label: "Current run"' in app
    assert 'id="restart-current-run"' in page
    assert 'class="pipeline-control-button pipeline-new-run"' in page
    assert '<small>Start here</small>' in page
    assert "New run from here" not in page
    assert 'data-coverage-mode="analysis"' in page
    assert 'data-coverage-mode="reviewed"' in page
    assert "function progressPanel(" in app
    assert "return progressPanel({label, completed: progress.completed" in app
    assert 'id="pipeline-diagnostics-list"' in page
    assert "function renderPipelineDiagnostics()" in app
    assert "function progressActivity(" in app


def test_pipeline_panel_can_start_one_book_completely_over() -> None:
    root = Path(__file__).parents[1]
    app = (root / "web" / "app.js").read_text(encoding="utf-8")
    server_source = (root / "bookinator" / "server" / "__main__.py").read_text(encoding="utf-8")

    assert 'action: "start-over", label: "Start over"' in app
    assert "Start this pipeline completely over?" in app
    assert "/pipeline/start-over" in app
    assert 're.fullmatch(r"/api/books/([A-Za-z0-9_-]{8,80})/pipeline/start-over"' in server_source


def test_duplicate_library_titles_show_source_and_project_identity() -> None:
    app = (Path(__file__).parents[1] / "web" / "app.js").read_text(encoding="utf-8")
    assert 'class="duplicate-book-identity ${book.sourceAvailable ? "with-source" : "without-source"}' in app
    assert '${book.sourceAvailable ? "Original source" : "No source"} · project ${escapeHtml(String(book.id).slice(0, 8))}' in app


def test_library_cover_opens_book_and_shelving_offers_a_safe_handoff() -> None:
    root = Path(__file__).parents[1]
    page = (root / "web" / "index.html").read_text(encoding="utf-8")
    app = (root / "web" / "app.js").read_text(encoding="utf-8")
    cover_markup = app[app.index('<div class="book-identity">'):app.index('<div class="book-identity">') + 700]
    assert 'data-open-book="${escapeHtml(book.id)}"' in cover_markup
    assert 'data-edit-book="${escapeHtml(book.id)}"' not in cover_markup
    assert 'id="confirmation-secondary" hidden' in page
    assert 'secondaryLabel: "Finish task & shelve"' in app
    assert 'acceptLabel: "Cancel task & shelve"' in app
    assert 'cancelLabel: "Keep running"' in app
    assert '/pipeline/stop`, {method: "POST"}' in app


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


def test_pipeline_activity_expands_numeric_chapter_titles() -> None:
    pipeline = {
        "status": "running", "phase": "summarizing", "stages": [{"id": "summaries", "status": "running", "model": "qwen2.5:32b"}],
        "chapters": [{"sequence": 4, "title": "3", "status": "running"}], "chunks": [],
    }

    activity = pipeline_activity({"title": "The Dunwich Horror"}, pipeline)

    assert activity["item"] == "Chapter 3"
    assert activity["text"].endswith("The Dunwich Horror · Chapter 3")


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
    assert API_FEATURES["reviewerSignoff"] == 1
    assert API_FEATURES["shadowHeadingDiagnostic"] == 1


def test_retired_prose_analysis_is_removed_from_legacy_ledgers() -> None:
    pipeline = {
        "proseProgress": {"completed": 2, "total": 24},
        "stages": [
            {"id": "summaries", "label": "Summaries", "status": "complete"},
            {"id": "prose", "label": "Prose", "status": "paused", "disabled": True},
        ],
        "chapters": [{
            "sequence": 1,
            "summary": "Keep me.",
            "proseStatus": "complete",
            "proseModel": "retired-gemma",
            "prose": {"dimensions": ["remove me"]},
            "proseRuns": [{"proseStatus": "failed"}],
        }],
    }

    assert server.remove_legacy_prose_analysis(pipeline)
    assert [stage["id"] for stage in pipeline["stages"]] == ["summaries"]
    assert "proseProgress" not in pipeline
    assert pipeline["chapters"] == [{"sequence": 1, "summary": "Keep me."}]
    assert not server.remove_legacy_prose_analysis(pipeline)


def test_automatic_queue_orders_priority_and_inventories_shelved_books() -> None:
    books = [
        {"id": "low-book", "manuscriptId": "m1", "priority": "low", "updatedAt": "2026-01-01"},
        {"id": "high-new", "manuscriptId": "m2", "priority": "high", "updatedAt": "2026-02-01"},
        {"id": "high-old", "manuscriptId": "m3", "priority": "high", "updatedAt": "2026-01-01"},
        {"id": "shelved", "manuscriptId": "m4", "priority": "shelved", "updatedAt": "2025-01-01"},
    ]
    pending = {"stages": [], "chapters": []}
    with patch("bookinator.server.__main__.load_pipeline", return_value=pending):
        queued = automatic_queue_books(books)
    assert queued == [("high-old", "prepare"), ("high-new", "prepare"), ("low-book", "prepare"), ("shelved", "prepare")]


def test_automatic_queue_inventories_a_low_priority_book_before_model_work() -> None:
    high = {"id": "high-book", "manuscriptId": "high", "priority": "high", "updatedAt": "2026-01-01"}
    low = {"id": "low-book", "manuscriptId": "low", "priority": "low", "updatedAt": "2026-02-01"}
    prepared = {"stages": [{"id": "summaries", "status": "pending"}], "chapters": [{"sequence": 1, "status": "pending"}]}
    unprepared = {"stages": [], "chapters": []}

    with patch.object(server, "load_pipeline", side_effect=lambda book: unprepared if book["id"] == "low-book" else prepared):
        queued = automatic_queue_books([high, low])

    assert queued == [("low-book", "prepare"), ("high-book", "summarize")]


def test_prepared_shelved_book_does_not_enter_expensive_queue() -> None:
    book = {"id": "shelved", "manuscriptId": "manuscript", "priority": "shelved"}
    prepared = {"stages": [{"id": "summaries", "status": "pending"}], "chapters": [{"sequence": 1, "status": "pending"}]}
    with patch.object(server, "load_pipeline", return_value=prepared):
        assert automatic_queue_books([book]) == []


def test_library_marks_only_the_global_worker_book_as_running() -> None:
    root = Path(__file__).parents[1]
    app = (root / "web" / "app.js").read_text(encoding="utf-8")
    styles = (root / "web" / "styles.css").read_text(encoding="utf-8")

    assert "function bookOwnsActiveWorker(book)" in app
    assert 'if (activity.bookId) return activity.bookId === book.id;' in app
    assert app.count('book-cover${running ? " is-running" : ""}') == 2
    assert ".book-cover.is-running::after" in styles
    assert ".book-cover.is-running::after" in styles and "background: var(--blue)" in styles
    assert "animation: book-running-pulse" in styles
    assert "@media (prefers-reduced-motion: reduce)" in styles


def test_library_view_preferences_survive_reload_and_priority_colors_are_semantic() -> None:
    root = Path(__file__).parents[1]
    app = (root / "web" / "app.js").read_text(encoding="utf-8")
    styles = (root / "web" / "styles.css").read_text(encoding="utf-8")

    assert 'const libraryViewKey = "bookinator.library-view.v1";' in app
    assert "function saveLibraryViewPreferences()" in app
    assert "sort: rememberedLibraryView.sort" in app
    assert 'search.addEventListener("input", () => {' in app
    assert 'filter.addEventListener("change", () => {' in app
    assert ".priority-high select" in styles
    assert ".priority-normal select" in styles
    assert ".priority-low select" in styles
    assert ".priority-shelved select" in styles


def test_durable_queue_is_reordered_by_current_priority() -> None:
    import bookinator.server.__main__ as server

    books = [
        {"id": "low-book", "priority": "low"},
        {"id": "normal-book", "priority": "normal"},
        {"id": "high-book", "priority": "high"},
    ]
    with patch.object(server, "load_library_records", return_value=books):
        assert queue_ids_by_current_priority(["low-book", "normal-book", "high-book"]) == ["high-book", "normal-book", "low-book"]


def test_durable_queue_inventories_before_resuming_model_work() -> None:
    books = [
        {"id": "high-book", "manuscriptId": "high", "priority": "high"},
        {"id": "low-book", "manuscriptId": "low", "priority": "low"},
    ]
    prepared = {"stages": [{"id": "summaries", "status": "pending"}], "chapters": [{"sequence": 1, "status": "pending"}]}
    unprepared = {"stages": [], "chapters": []}
    with (
        patch.object(server, "load_library_records", return_value=books),
        patch.object(server, "load_pipeline", side_effect=lambda book: unprepared if book["id"] == "low-book" else prepared),
    ):
        assert queue_ids_by_current_priority(["high-book", "low-book"]) == ["low-book", "high-book"]


def test_durable_queue_skips_shelved_analysis_but_keeps_required_intake() -> None:
    shelved_ready = {"id": "ready-book", "manuscriptId": "ready", "priority": "shelved"}
    shelved_new = {"id": "new-book", "manuscriptId": "new", "priority": "shelved"}
    ready_pipeline = {"stages": [{"id": "summaries", "status": "pending"}], "chapters": [{"sequence": 1, "status": "pending"}]}
    new_pipeline = {"stages": [], "chapters": []}

    def load(candidate):
        return new_pipeline if candidate["id"] == "new-book" else ready_pipeline

    with (
        patch.object(server, "load_library_records", return_value=[shelved_ready, shelved_new]),
        patch.object(server, "load_pipeline", side_effect=load),
    ):
        assert queue_ids_by_current_priority(["ready-book", "new-book"]) == ["new-book"]


def test_shelved_running_book_yields_after_its_current_safe_step() -> None:
    shelved = {"id": "book-1234", "manuscriptId": "book", "priority": "shelved"}
    with patch.object(server, "load_library_records", return_value=[shelved]):
        assert server.higher_priority_book_waiting("book-1234") is True


def test_global_status_ignores_an_orphaned_running_ledger(tmp_path: Path) -> None:
    import bookinator.server.__main__ as server

    book = {
        "id": "book-1234", "title": "Stale book", "priority": "normal",
        "pipeline": {"workRemaining": True, "nextAction": "smells", "progress": {"completed": 2, "total": 3}},
    }
    pipeline = {
        "status": "running", "phase": "smells", "chapters": [{"sequence": 1, "smellStatus": "running"}],
        "stages": [{"id": "smells", "label": "Smells", "status": "running"}], "chunks": [],
    }
    with (
        patch.object(server, "pipeline_worker_is_alive", return_value=False),
        patch.object(server, "pipeline_is_enabled", return_value=True),
        patch.object(server, "schedule_global_pipeline_wake") as wake,
        patch.object(server, "CURRENT_RUN_PATH", tmp_path / "current-run.json"),
    ):
        state = server.global_pipeline_state([book], [(book, pipeline)])
    assert state["activity"].get("bookId") != "book-1234"
    assert state["activity"]["state"] == "queued"
    wake.assert_called_once_with()


def test_global_queue_row_names_the_active_action_not_the_following_action(tmp_path: Path) -> None:
    import bookinator.server.__main__ as server

    book = {
        "id": "book-1234", "title": "Active book", "priority": "high",
        "pipeline": {"nextAction": "questions", "updatedAt": "2026-09-26T20:00:00+00:00"},
    }
    pipeline = {
        "status": "running", "phase": "llm-review",
        "chapters": [{"sequence": 1, "title": "Chapter 1", "llmReviewStatus": "running"}],
        "stages": [{"id": "llm-review", "label": "LLM Review", "status": "running", "model": "reader"}],
        "pipelineProgress": {"completed": 1, "total": 2},
    }
    queue_thread = Mock()
    queue_thread.is_alive.return_value = True
    with (
        patch.object(server, "pipeline_worker_is_alive", return_value=True),
        patch.object(server, "pipeline_is_enabled", return_value=True),
        patch.object(server, "QUEUE_THREAD", queue_thread),
        patch.object(server, "QUEUE_CURRENT_TASK", {"bookId": "book-1234", "action": "chapter-pipeline"}),
        patch.object(server, "CURRENT_RUN_PATH", tmp_path / "current-run.json"),
    ):
        state = server.global_pipeline_state([book], [(book, pipeline)])

    assert state["activity"]["phase"] == "llm-review"
    assert state["queue"][0]["action"] == "llm-review"
    assert state["queue"][0]["task"] == "LLM Review"
    assert state["queue"][0]["state"] == "running"


def test_repair_orphaned_pipeline_clears_every_false_running_marker() -> None:
    import bookinator.server.__main__ as server

    book = {"id": "book-1234", "title": "Interrupted book"}
    pipeline = {
        "status": "running", "phase": "smells", "workerPid": 999,
        "stages": [{"id": "smells", "status": "running", "model": "reader"}],
        "chapters": [{"sequence": 1, "status": "complete", "smellStatus": "running"}],
        "chunks": [],
    }
    with patch.object(server, "pipeline_worker_is_alive", return_value=False):
        assert server.repair_orphaned_pipeline(book, pipeline) is True

    assert pipeline["status"] == "ready"
    assert pipeline["phase"] == "recovering"
    assert pipeline["stages"][0]["status"] == "pending"
    assert pipeline["chapters"][0]["smellStatus"] == "pending"
    assert pipeline["chapters"][0]["smellError"]
    assert pipeline["recoveryDiagnostics"][-1]["phase"] == "smells"
    assert "error" not in pipeline


def test_saved_manual_interruption_migrates_back_to_automatic_queue() -> None:
    import bookinator.server.__main__ as server

    diagnostic = "The local model's previous reading process ended without returning a result. Press Continue to retry the interrupted work."
    pipeline = {
        "status": "warning", "phase": "interrupted", "error": diagnostic,
        "stages": [{"id": "emotions", "status": "warning", "detail": diagnostic}],
    }

    assert server.migrate_manual_interruption(pipeline) is True
    assert pipeline["status"] == "ready"
    assert pipeline["phase"] == "recovering"
    assert pipeline["stages"][0]["status"] == "pending"
    assert "error" not in pipeline
    assert "returned that task to the queue" in pipeline["recoveryDiagnostics"][-1]["message"]
    assert "Press Continue" not in pipeline["recoveryDiagnostics"][-1]["message"]


def test_queue_watchdog_coalesces_status_poll_wakes() -> None:
    import bookinator.server.__main__ as server

    worker = Mock()
    server.QUEUE_WAKE_PENDING = False
    with patch.object(server, "QUEUE_THREAD", None), patch.object(server.threading, "Thread", return_value=worker) as thread:
        server.schedule_global_pipeline_wake()
        server.schedule_global_pipeline_wake()

    thread.assert_called_once()
    worker.start.assert_called_once_with()
    server.QUEUE_WAKE_PENDING = False


def test_development_checkpoint_is_not_reported_as_an_interrupted_model_run() -> None:
    import bookinator.server.__main__ as server

    book = {"id": "book-1234", "title": "Bounded book", "priority": "high"}
    pipeline = {
        "status": "running", "phase": "chapter-complete", "workerPid": 999,
        "developmentAnalysisLimit": 4, "developmentAnalysisLabel": "Chapter II",
        "stages": [
            {"id": "cumulative-context", "status": "pending"},
            {"id": "llm-review", "status": "pending"},
        ],
        "chapters": [
            {"sequence": 1, "title": "Front matter", "status": "complete"},
            {"sequence": 2, "title": "Prologue", "status": "complete"},
            {"sequence": 3, "title": "I", "status": "complete"},
            {"sequence": 4, "title": "II", "status": "complete"},
            {"sequence": 5, "title": "III", "status": "pending"},
        ],
        "error": "The local model's previous reading process ended without returning a result.",
    }
    with patch.object(server, "pipeline_worker_is_alive", return_value=False), patch.object(server, "next_pipeline_action", return_value=""):
        assert server.repair_orphaned_pipeline(book, pipeline) is True

    assert pipeline["status"] == "paused"
    assert pipeline["phase"] == "development-checkpoint"
    assert "Chapter II" in pipeline["message"]
    assert "error" not in pipeline


def test_assessment_evidence_converts_passage_ids_to_readable_source_quotes() -> None:
    import bookinator.server.__main__ as server

    text = "Laura waited beside the window. The carriage arrived after midnight. Nothing moved in the courtyard."
    passages = server.source_evidence_passages(text)
    result = server.normalize_assessment_evidence(
        text,
        [f"{passages[0]['id']} {passages[0]['characterStart']}:{passages[0]['characterEnd']}", passages[1]["id"], passages[2]["text"], passages[0]["id"]],
    )

    assert result == [passages[0]["text"], passages[1]["text"], passages[2]["text"]]


def test_current_run_tracks_only_work_remaining_at_start_and_expands_explicitly(tmp_path: Path) -> None:
    path = tmp_path / "current-run.json"
    book = {"id": "book-one", "title": "One", "priority": "high", "pipeline": {"nextAction": "summarize"}}
    pipeline = {"pipelineProgress": {"completed": 4, "total": 10}}
    with patch.object(server, "CURRENT_RUN_PATH", path):
        started = server.sync_current_pipeline_run([(book, pipeline)])
        assert (started["completed"], started["total"], started["percent"]) == (0, 6, 0)

        pipeline["pipelineProgress"]["completed"] = 7
        advanced = server.sync_current_pipeline_run([(book, pipeline)])
        assert (advanced["completed"], advanced["total"], advanced["percent"]) == (3, 6, 50)

        second = {"id": "book-two", "title": "Two", "priority": "normal", "pipeline": {"nextAction": "tags"}}
        second_pipeline = {"pipelineProgress": {"completed": 1, "total": 3}}
        expanded = server.sync_current_pipeline_run([(book, pipeline), (second, second_pipeline)])
        assert expanded["total"] == 8
        assert expanded["addedUnits"] == 2
        assert json.loads(path.read_text(encoding="utf-8"))["books"]["book-two"]["baselineCompleted"] == 1


def test_library_coverage_separates_machine_analysis_from_reviewer_signoff() -> None:
    books = [
        {"manuscriptId": "one", "pipeline": {"machineComplete": True, "reviewerComplete": True}},
        {"manuscriptId": "two", "pipeline": {"machineComplete": True, "reviewerComplete": False}},
        {"manuscriptId": "three", "pipeline": {"machineComplete": False, "reviewerComplete": False}},
    ]
    assert server.library_coverage(books) == {"totalBooks": 3, "analysisComplete": 2, "reviewedComplete": 1}


def test_lower_priority_chapter_pipeline_yields_before_starting_work() -> None:
    import bookinator.server.__main__ as server

    low = {"id": "low-book", "manuscriptId": "low", "priority": "low"}
    high = {"id": "high-book", "manuscriptId": "high", "priority": "high"}
    low_pipeline = {"stages": [{"id": "summaries", "status": "pending"}], "chapters": [{"sequence": 1, "status": "pending"}], "chunks": []}
    high_pipeline = {"stages": [{"id": "extraction", "status": "pending"}], "chapters": [], "chunks": []}

    def load(candidate):
        return high_pipeline if candidate["id"] == "high-book" else low_pipeline

    with patch.object(server, "find_book", return_value=low), \
         patch.object(server, "load_library_records", return_value=[low, high]), \
         patch.object(server, "load_pipeline", side_effect=load), \
         patch.object(server, "run_summary_pipeline") as summarize:
        server.run_book_chapter_pipeline("low-book", emotions=False, tags=False, smells=False, dossiers=False)
    summarize.assert_not_called()


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


def test_single_dossier_refresh_preserves_every_sibling_result(tmp_path: Path) -> None:
    first = {"sequence": 7, "dossierStatus": "complete", "dossier": {"facts": ["Refresh me"]}, "dossierModel": "reader", "dossierCompletedAt": "now"}
    sibling = {"sequence": 8, "dossierStatus": "complete", "dossier": {"facts": ["Keep me"]}, "dossierModel": "reader", "dossierCompletedAt": "later"}
    pipeline = {"stages": [{"id": "dossiers", "status": "complete"}], "chapters": [], "chunks": [first, sibling]}
    (tmp_path / "0007.json").write_text(json.dumps(first), encoding="utf-8")
    (tmp_path / "0008.json").write_text(json.dumps(sibling), encoding="utf-8")

    with patch.object(server, "write_pipeline"), patch.object(server, "chunk_artifacts_path", return_value=tmp_path):
        owner_action, _ = server.refresh_analysis_result({"id": "book-1234"}, pipeline, "dossier", 7)

    assert owner_action == "dossiers"
    assert refresh_followup_action(owner_action) == "chapter-pipeline"
    assert pipeline["chunks"][0]["dossierStatus"] == "pending"
    assert "dossier" not in pipeline["chunks"][0]
    assert pipeline["chunks"][1] == sibling
    assert json.loads((tmp_path / "0008.json").read_text(encoding="utf-8"))["dossier"] == {"facts": ["Keep me"]}


def test_row_refresh_never_turns_into_a_category_wide_queue_request() -> None:
    for owner_action in ("summarize", "dossiers", "emotions", "tags", "smells", "cumulative-context", "llm-review"):
        assert refresh_followup_action(owner_action) == "chapter-pipeline"
    assert refresh_followup_action("whole-summary") == "whole-summary"
    assert refresh_followup_action("whole-llm-review") == "whole-llm-review"


def test_development_boundary_limits_automatic_work_without_falsifying_later_statuses() -> None:
    pipeline = {
        "developmentAnalysisLimit": 2,
        "stages": [
            {"id": "extraction", "status": "complete"}, {"id": "chapter-archive", "status": "complete"},
            {"id": "summaries", "status": "pending"}, {"id": "dossiers", "status": "pending"},
            {"id": "cumulative-context", "status": "pending"}, {"id": "llm-review", "status": "pending"},
        ],
        "chapters": [
            {"sequence": 2, "title": "PROLOGUE", "status": "complete", "contextStatus": "pending", "llmReviewStatus": "pending"},
            {"sequence": 3, "title": "I. Later", "status": "pending", "contextStatus": "pending", "llmReviewStatus": "pending"},
        ],
        "chunks": [{"sequence": 2, "chapterSequence": 2, "dossierStatus": "complete"}],
    }
    book = {"id": "book", "manuscriptId": "manuscript", "priority": "normal", "llmReviewEnabled": True}

    assert development_limited_items(pipeline, pipeline["chapters"], "sequence") == [pipeline["chapters"][0]]
    with patch.object(server, "paused_pipeline_actions", return_value=set()):
        assert next_pipeline_action(book, pipeline) == "llm-review"
    assert pipeline["chapters"][1]["status"] == "pending"


def test_development_checkpoint_blocks_version_migration_until_human_advances_it(tmp_path: Path) -> None:
    book = {"id": "book", "manuscriptId": "manuscript", "priority": "high", "llmReviewEnabled": True}
    pipeline = {
        "status": "paused", "phase": "development-checkpoint",
        "developmentAnalysisLimit": 2,
        "stages": [{"id": "extraction", "status": "complete"}, {"id": "chapter-archive", "status": "complete"}],
        "chapters": [{"sequence": 2, "title": "PROLOGUE", "status": "complete", "contextStatus": "pending", "llmReviewStatus": "pending"}],
        "chunks": [],
    }
    context_path = tmp_path / "manuscript" / "llm-review" / "contexts" / "0002.json"
    review_path = tmp_path / "manuscript" / "llm-review" / "results" / "0002.json"
    context_path.parent.mkdir(parents=True)
    review_path.parent.mkdir(parents=True)
    context_path.write_text(json.dumps({
        "schema": "cumulative-context-v3", "status": "complete", "model": "qwen",
        "completedAt": "earlier", "inputSignature": "old-context", "context": {"storySoFar": "Preserve me."},
    }), encoding="utf-8")
    review_path.write_text(json.dumps({
        "schema": "llm-review-v7", "status": "complete", "model": "qwen",
        "completedAt": "earlier", "inputSignature": "old-review", "result": {"editorialSummary": "Preserve me too."},
    }), encoding="utf-8")

    with patch.object(server, "BOOKS_ROOT", tmp_path):
        assert server.ensure_llm_review_stages(book, pipeline) is True
        with patch.object(server, "paused_pipeline_actions", return_value=set()):
            assert next_pipeline_action(book, pipeline) == ""

    chapter = pipeline["chapters"][0]
    assert pipeline["developmentCheckpointLocked"] is True
    assert chapter["contextStatus"] == "complete"
    assert chapter["context"]["storySoFar"] == "Preserve me."
    assert chapter["llmReviewStatus"] == "complete"
    assert chapter["llmReview"]["editorialSummary"] == "Preserve me too."


def test_reset_after_development_boundary_preserves_earlier_results_and_clears_later_work(tmp_path: Path) -> None:
    book = {"id": "book", "manuscriptId": "manuscript"}
    kept = {"sequence": 4, "title": "II. Kept", "status": "complete", "summary": "Keep", "tagStatus": "complete", "tag": {"tags": ["keep"]}, "contextStatus": "pending", "llmReviewStatus": "pending"}
    cleared = {"sequence": 5, "title": "III. Cleared", "status": "complete", "summary": "Remove", "tagStatus": "complete", "tag": {"tags": ["remove"]}, "emotionStatus": "complete", "emotion": {"scores": []}, "smellStatus": "complete", "smell": {"candidates": []}, "contextStatus": "pending", "llmReviewStatus": "pending"}
    kept_chunk = {"sequence": 4, "chapterSequence": 4, "dossierStatus": "complete", "dossier": {"facts": ["Keep"]}}
    cleared_chunk = {"sequence": 5, "chapterSequence": 5, "dossierStatus": "complete", "dossier": {"facts": ["Remove"]}}
    pipeline = {
        "stages": [{"id": stage, "status": "complete"} for stage in ("summaries", "dossiers", "emotions", "tags", "smells", "cumulative-context", "llm-review", "whole-book-llm-review")],
        "chapters": [kept, cleared], "chunks": [kept_chunk, cleared_chunk],
        "wholeBookSummary": {"status": "complete", "summary": "Old"},
        "wholeBookDossier": {"status": "complete", "synopsis": "Old"},
    }
    chunks_root = tmp_path / "books" / "manuscript" / "chunks"
    chunks_root.mkdir(parents=True)
    (chunks_root / "0005.json").write_text(json.dumps(cleared_chunk), encoding="utf-8")

    with patch.object(server, "BOOKS_ROOT", tmp_path / "books"), patch.object(server, "write_pipeline"):
        reset_analysis_after_sequence(book, pipeline, 4, "Chapter II")

    assert kept["summary"] == "Keep"
    assert kept_chunk["dossier"] == {"facts": ["Keep"]}
    assert cleared["status"] == "pending" and "summary" not in cleared
    assert cleared["tagStatus"] == "pending" and "tag" not in cleared
    assert cleared_chunk["dossierStatus"] == "pending" and "dossier" not in cleared_chunk
    assert json.loads((chunks_root / "0005.json").read_text(encoding="utf-8"))["dossierStatus"] == "pending"
    assert pipeline["developmentAnalysisLimit"] == 4
    assert pipeline["wholeBookSummary"]["status"] == "blocked"


def test_pipeline_exposes_one_book_level_failed_work_recovery_control() -> None:
    app = (Path(__file__).parents[1] / "web" / "app.js").read_text(encoding="utf-8")
    assert "function failedAnalysisCount(pipeline)" in app
    assert 'action: "retry-failed"' in app
    assert 'context: "Pipeline recovery"' in app
    assert 'acceptLabel: "Retry failed work"' in app
    assert "/pipeline/retry-failed" in app
    assert "queuedBehindActiveResponse" in app
    assert "You do not need to stop the library queue." in app


def test_development_launcher_delegates_to_the_shared_inator_launcher() -> None:
    launcher = (Path(__file__).parents[1] / "bin" / "serve").read_text(encoding="utf-8")
    assert 'commons_dir="${INATOR_COMMONS_DIR:-$project_dir/../inator}"' in launcher
    assert '"$project_dir/../../inator/node_modules/.bin/inator-serve"' in launcher
    assert 'launcher="$commons_dir/node_modules/.bin/inator-serve"' in launcher
    assert 'INATOR_PROJECT_DIR="$project_dir"' in launcher
    assert 'PYTHONPATH="$project_dir${PYTHONPATH:+:$PYTHONPATH}"' in launcher
    assert '"$launcher" "$@" -- python3 -m bookinator.server' in launcher


def test_pipeline_payload_does_not_resend_manuscript_source_text() -> None:
    import bookinator.server.__main__ as server

    pipeline = {"chapters": [{"sequence": 1, "markdown": "# CHAPTER 1\n\nSource prose", "text": "Source prose", "summary": "Keep this"}]}
    visible = server.compact_pipeline_payload(pipeline)

    assert visible["chapters"][0] == {"sequence": 1, "summary": "Keep this"}
    assert pipeline["chapters"][0]["markdown"].startswith("# CHAPTER")


def test_book_workspace_does_not_rebuild_or_redownload_the_library_while_polling() -> None:
    root = Path(__file__).parents[1]
    app = (root / "web" / "app.js").read_text(encoding="utf-8")
    server = (root / "bookinator" / "server" / "__main__.py").read_text(encoding="utf-8")
    pipeline_route = server.split('pipeline_match = re.fullmatch(r"/api/books/', 1)[1].split("super().do_GET()", 1)[0]

    assert 'if self.path == "/api/library/pipeline"' in server
    assert 'self.send_json({"pipeline": global_pipeline_state()})' in server
    assert 'pipeline["globalPipeline"] = global_pipeline_state()' not in pipeline_route
    assert 'libraryVisible ? "/api/books" : "/api/library/pipeline"' in app
    assert 'if (!state.priorityInteractionActive && libraryVisible) render();' in app


def test_library_externalizes_embedded_cover_images_without_losing_metadata() -> None:
    book = {
        "id": "book-12345678", "title": "A Book",
        "icon": {"kind": "image", "value": "data:image/webp;base64,YWJj", "background": "#123456", "outline": False},
    }
    visible = server.book_for_library_client(book)

    assert visible["icon"] == {
        "kind": "image", "value": "/api/books/book-12345678/icon",
        "background": "#123456", "outline": False, "lazy": True,
    }
    assert book["icon"]["value"].startswith("data:image/webp;base64,")


def test_saving_lazy_library_icon_preserves_durable_embedded_image(tmp_path: Path) -> None:
    embedded = {"kind": "image", "value": "data:image/webp;base64,YWJj", "background": "#123456"}
    record = {"id": "book-12345678", "title": "A Book", "author": "An Author", "icon": embedded}
    library_path = tmp_path / "library.json"
    library_path.write_text(json.dumps([record]), encoding="utf-8")
    submitted = {**record, "author": "A Better Author", "icon": {**embedded, "value": "/api/books/book-12345678/icon", "lazy": True}}

    with patch.object(server, "LIBRARY_PATH", library_path), patch.object(server, "BOOKS_ROOT", tmp_path / "books"):
        saved = server.save_book(submitted)
        durable = json.loads(library_path.read_text(encoding="utf-8"))[0]

    assert saved["author"] == "A Better Author"
    assert durable["icon"] == embedded


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


def test_chapter_map_approval_waits_for_stable_structure() -> None:
    pipeline = {
        "phase": "preparing",
        "stages": [{"id": "structure", "status": "running"}],
        "chapters": [{"sequence": 1, "title": "CHAPTER I"}],
    }
    assert server.chapter_map_review_ready(pipeline) is False

    pipeline["phase"] = "ready"
    pipeline["stages"][0]["status"] = "complete"
    assert server.chapter_map_review_ready(pipeline) is True
    assert add_pipeline_progress(pipeline)["chapterMapReviewReady"] is True

    pipeline["phase"] = "chapter-archive"
    assert server.chapter_map_review_ready(pipeline) is True


def test_suspicious_unapproved_chapter_map_cannot_enter_analysis_queue() -> None:
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
        with pytest.raises(ValueError, match="Review and resolve"):
            prioritize_pipeline_action("book-1234", "summarize")


def test_suspicious_chapter_map_stops_automatic_analysis_but_clean_map_may_run() -> None:
    book = {"id": "book-1234", "manuscriptId": "manuscript", "priority": "normal"}
    pipeline = {
        "chapterMapApproved": False,
        "chapterMapSuspicious": True,
        "stages": [
            {"id": "extraction", "status": "complete"},
            {"id": "chapter-archive", "status": "complete"},
            {"id": "summaries", "status": "blocked"},
        ],
        "chapters": [{"sequence": 1, "status": "pending"}],
        "chunks": [],
    }
    with patch.object(server, "paused_pipeline_actions", return_value=set()):
        assert next_pipeline_action(book, pipeline) == ""
        pipeline["chapterMapSuspicious"] = False
        pipeline["stages"][-1]["status"] = "pending"
        assert next_pipeline_action(book, pipeline) == "summarize"


def test_chapter_worker_refuses_suspicious_unapproved_map() -> None:
    pipeline = {"chapterMapApproved": False, "chapterMapSuspicious": True}
    with (
        patch.object(server, "find_book", return_value={"id": "book-1234", "manuscriptId": "manuscript"}),
        patch.object(server, "load_pipeline", return_value=pipeline),
        patch.object(server, "run_ready_stage_rollups") as rollups,
        patch.object(server, "run_summary_pipeline") as summarize,
    ):
        server.run_book_chapter_pipeline("book-1234")
    rollups.assert_not_called()
    summarize.assert_not_called()


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


def test_rebuilt_map_preserves_prior_editor_approval_only_when_clean() -> None:
    pipeline = {"chapterMapApprovalAfterRebuild": True, "chapterMapApproved": False, "analysisProvisional": True}
    assert server.finalize_rebuilt_chapter_map_approval(pipeline, []) is True
    assert pipeline["chapterMapApproved"] is True
    assert pipeline["analysisProvisional"] is False
    assert pipeline["chapterMapApprovedAt"]
    assert "chapterMapApprovalAfterRebuild" not in pipeline

    warned = {"chapterMapApprovalAfterRebuild": True, "chapterMapApproved": False, "chapterMapApprovedAt": "old"}
    assert server.finalize_rebuilt_chapter_map_approval(warned, ["Unexpected heading"]) is False
    assert warned["chapterMapApproved"] is False
    assert warned["analysisProvisional"] is True
    assert "chapterMapApprovedAt" not in warned


def test_restarted_prepare_suspends_instead_of_revoking_editor_approval() -> None:
    pipeline = {
        "chapterMapApproved": True,
        "chapterMapApprovedAt": "2026-09-25T00:12:00+00:00",
        "chapterMapDecisionAt": "2026-09-25T00:12:00+00:00",
    }
    server.begin_chapter_map_rebuild(pipeline)
    assert pipeline["chapterMapApproved"] is False
    assert pipeline["chapterMapApprovalAfterRebuild"] is True
    assert "chapterMapApprovedAt" not in pipeline
    assert server.finalize_rebuilt_chapter_map_approval(pipeline, []) is True


def test_find_book_does_not_hydrate_every_pipeline() -> None:
    records = [{"id": "first-book", "title": "First"}, {"id": "wanted-book", "title": "Wanted"}]
    with patch.object(server, "load_library_records", return_value=records), patch.object(server, "enrich_book") as enrich:
        found = server.find_book("wanted-book")
    assert found == records[1]
    enrich.assert_not_called()


def test_stale_worker_cannot_overwrite_newer_chapter_map_decision(tmp_path: Path) -> None:
    book = {"id": "book-1234", "manuscriptId": "manuscript-1234"}
    project = tmp_path / "manuscript-1234"
    project.mkdir()
    persisted = {
        "bookId": "book-1234",
        "chapterMapApproved": True,
        "chapterMapApprovedAt": "2026-09-25T00:12:00+00:00",
        "chapterMapDecisionAt": "2026-09-25T00:12:00+00:00",
        "analysisProvisional": False,
        "acceptedChapterLabelVariants": ["INTERLUDE"],
        "stages": [],
        "chapters": [],
    }
    (project / "pipeline.json").write_text(json.dumps(persisted), encoding="utf-8")
    stale_worker = {
        "bookId": "book-1234",
        "chapterMapApproved": False,
        "chapterMapDecisionAt": "2026-09-25T00:10:00+00:00",
        "analysisProvisional": True,
        "acceptedChapterLabelVariants": [],
        "stages": [],
        "chapters": [],
    }

    with patch.object(server, "BOOKS_ROOT", tmp_path):
        server.write_pipeline(book, stale_worker)

    saved = json.loads((project / "pipeline.json").read_text(encoding="utf-8"))
    assert saved["chapterMapApproved"] is True
    assert saved["analysisProvisional"] is False
    assert saved["acceptedChapterLabelVariants"] == ["INTERLUDE"]


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
    assert progress["total"] == 12
    assert progress["completed"] == 4
    assert progress["percent"] == 33
    assert progress["chapterCount"] == 2
    assert progress["inferenceTotal"] == 2
    assert "front matter excluded" in progress["basisLabel"]
    assert "whole-book inferences" in progress["basisLabel"]


def test_overall_pipeline_progress_counts_completed_whole_book_inferences() -> None:
    pipeline = {
        "stages": [
            {"id": "chapter-archive", "status": "complete"},
            {"id": "summaries", "status": "complete"},
            {"id": "dossiers", "status": "complete"},
        ],
        "chapters": [{"sequence": 1, "title": "CHAPTER 1", "status": "complete", "summary": "Arrival."}],
        "chunks": [{"chapterSequence": 1, "dossierStatus": "complete", "dossier": {"questions": ["Who arrived?"]}}],
        "questionTracker": {"status": "complete", "questions": [], "inputSignature": "placeholder"},
    }
    pipeline["questionTracker"]["inputSignature"] = server.question_tracker_input_signature(pipeline)

    progress = add_pipeline_progress(pipeline)["pipelineProgress"]

    assert progress["inferenceTotal"] == 2
    assert progress["inferenceCompleted"] == 2
    assert progress["completed"] == 5
    assert progress["total"] == 7


def test_library_analysis_progress_includes_reviewer_signoff() -> None:
    pipeline = {
        "status": "complete",
        "chapters": [{"status": "complete"}],
        "stages": [],
        "pipelineProgress": {"completed": 12, "total": 12, "percent": 100},
    }
    with (
        patch.object(server, "manuscript_metadata", return_value={}),
        patch.object(server, "load_pipeline", return_value={}),
        patch.object(server, "pipeline_for_client", return_value={}),
        patch.object(server, "add_pipeline_progress", return_value=pipeline),
        patch.object(server, "next_pipeline_action", return_value=""),
        patch.object(server, "load_queue", return_value=[]),
    ):
        with patch.object(server, "load_reviewer_signoff", return_value={"status": "open"}):
            open_review = server.enrich_book({"id": "book", "manuscriptId": "manuscript"})
        with patch.object(server, "load_reviewer_signoff", return_value={"status": "complete"}):
            signed_review = server.enrich_book({"id": "book", "manuscriptId": "manuscript"})

    assert open_review["pipeline"]["progress"] == {"completed": 12, "total": 13, "percent": 92, "basisLabel": "Saved analysis steps · reviewer sign-off"}
    assert open_review["pipeline"]["reviewerPending"] is True
    assert signed_review["pipeline"]["progress"] == {"completed": 13, "total": 13, "percent": 100, "basisLabel": "Saved analysis steps · reviewer sign-off"}
    assert signed_review["pipeline"]["workRemaining"] is False


def test_library_book_exposes_early_length_metrics() -> None:
    pipeline = {
        "status": "ready",
        "chapters": [{"status": "pending"}, {"status": "pending"}],
        "stages": [],
        "manuscriptMetrics": {"wordCount": 48_321, "chapterCount": 2},
        "pipelineProgress": {"completed": 0, "total": 0, "percent": 0},
    }
    with (
        patch.object(server, "manuscript_metadata", return_value={"sourceSizeBytes": 765_432}),
        patch.object(server, "load_pipeline", return_value={}),
        patch.object(server, "pipeline_for_client", return_value={}),
        patch.object(server, "add_pipeline_progress", return_value=pipeline),
        patch.object(server, "next_pipeline_action", return_value="summarize"),
        patch.object(server, "load_queue", return_value=[]),
        patch.object(server, "load_reviewer_signoff", return_value={"status": "open"}),
    ):
        book = server.enrich_book({"id": "book", "manuscriptId": "manuscript"})

    assert book["wordCount"] == 48_321
    assert book["chapterCount"] == 2
    assert book["sourceSizeBytes"] == 765_432


def test_library_book_exposes_compact_pipeline_task_records() -> None:
    pipeline = {
        "status": "running",
        "chapters": [{"status": "complete"}],
        "stages": [
            {"id": "summaries", "status": "complete", "detail": "Done", "model": "large-private-value"},
            {"id": "dossiers", "status": "running", "detail": "Chunk 2"},
        ],
        "wholeBookSummary": {"status": "pending", "detail": "Waiting", "summary": "Do not duplicate the report."},
        "pipelineProgress": {"completed": 1, "total": 3, "percent": 33},
    }
    with (
        patch.object(server, "manuscript_metadata", return_value={}),
        patch.object(server, "load_pipeline", return_value={}),
        patch.object(server, "pipeline_for_client", return_value={}),
        patch.object(server, "add_pipeline_progress", return_value=pipeline),
        patch.object(server, "next_pipeline_action", return_value="dossiers"),
        patch.object(server, "load_queue", return_value=[]),
        patch.object(server, "load_reviewer_signoff", return_value={"status": "open"}),
    ):
        book = server.enrich_book({"id": "book", "manuscriptId": "manuscript"})

    assert book["pipeline"]["stages"] == [
        {"id": "summaries", "status": "complete", "detail": "Done"},
        {"id": "dossiers", "status": "running", "detail": "Chunk 2"},
    ]
    assert book["pipeline"]["wholeBookSummary"] == {"status": "pending", "detail": "Waiting"}


def test_paused_pipeline_task_is_skipped_without_hiding_later_work() -> None:
    book = {"id": "book", "manuscriptId": "manuscript", "priority": "normal"}
    pipeline = {
        "bookId": "book",
        "stages": [
            {"id": "summaries", "status": "pending"},
            {"id": "dossiers", "status": "pending"},
        ],
        "chapters": [{"sequence": 1, "status": "pending"}],
        "chunks": [{"sequence": 1, "chapterSequence": 1, "dossierStatus": "pending"}],
    }
    with patch.object(server, "paused_pipeline_actions", return_value={"summarize"}):
        assert next_pipeline_action(book, pipeline) == "dossiers"


def test_pipeline_task_pause_is_durable_and_reversible(tmp_path: Path) -> None:
    pause_path = tmp_path / "pipeline-task-pauses.json"
    with patch.object(server, "TASK_PAUSES_PATH", pause_path):
        assert server.set_pipeline_action_paused("book", "smells", True) == ["smells"]
        assert server.paused_pipeline_actions("book") == {"smells"}
        assert server.set_pipeline_action_paused("book", "smells", False) == []
        assert server.paused_pipeline_actions("book") == set()


def test_library_ui_has_one_word_sorted_length_column() -> None:
    root = Path(server.__file__).parents[2]
    app = (root / "web" / "app.js").read_text(encoding="utf-8")
    styles = (root / "web" / "styles.css").read_text(encoding="utf-8")

    assert 'sortButton("length", "Length")' in app
    assert 'if (state.sort.key === "length")' in app
    assert 'class="length-cell"' in app
    assert '`${length.words.toLocaleString()} words`' in app
    assert ".length-cell strong" in styles


def test_book_icon_text_uses_contrast_aware_foreground() -> None:
    root = Path(server.__file__).parents[2]
    icon_picker = (root / "web" / "icon-picker.js").read_text(encoding="utf-8")
    styles = (root / "web" / "styles.css").read_text(encoding="utf-8")

    assert "export function iconTextAppearance(background)" in icon_picker
    assert 'element.style.setProperty("--icon-foreground", textAppearance.foreground)' in icon_picker
    assert "color: var(--icon-foreground, #fff)" in styles
    assert "text-shadow: var(--icon-text-shadow" in styles


def test_overall_pipeline_progress_sums_remaining_stage_estimates() -> None:
    pipeline = {
        "stages": [
            {"id": "chapter-archive", "status": "complete"},
            {"id": "summaries", "model": "reader"},
            {"id": "dossiers", "model": "dossier"},
            {"id": "emotions", "model": "emotion"},
            {"id": "tags", "model": "tagger"},
            {"id": "smells", "model": "editor"},
        ],
        "chapters": [
            {
                "sequence": 1, "title": "CHAPTER 1", "status": "complete", "model": "reader", "durationSeconds": 10,
                "emotionStatus": "complete", "emotionModel": "emotion", "emotionDurationSeconds": 20,
                "tagStatus": "complete", "tagModel": "tagger", "tagDurationSeconds": 30,
                "smellStatus": "complete", "smellModel": "editor", "smellDurationSeconds": 40,
            },
            {"sequence": 2, "title": "CHAPTER 2", "status": "pending", "emotionStatus": "pending", "tagStatus": "pending", "smellStatus": "pending"},
        ],
        "chunks": [
            {"chapterSequence": 1, "dossierStatus": "complete", "dossierModel": "dossier", "dossierDurationSeconds": 50},
            {"chapterSequence": 2, "dossierStatus": "pending"},
        ],
    }

    result = add_pipeline_progress(pipeline)
    progress = result["pipelineProgress"]

    assert result["progress"]["etaSeconds"] == 10
    assert result["dossierProgress"]["etaSeconds"] == 50
    assert progress["etaSeconds"] == 150
    assert progress["etaEstimatedStageCount"] == 5
    assert progress["etaUnestimatedStageCount"] == 0
    assert progress["etaPartial"] is False
    assert progress["etaLabel"] is None


def test_pending_whole_book_summary_keeps_last_completed_synthesis_visible() -> None:
    pipeline = {
        "stages": [{"id": "chapter-archive", "status": "complete"}, {"id": "summaries", "status": "complete"}],
        "chapters": [{"sequence": 1, "title": "CHAPTER 1", "status": "complete", "summary": "Current chapter"}],
        "chunks": [],
        "wholeBookSummary": {"status": "ready", "detail": "Waiting for replacement."},
        "wholeBookSummaryRuns": [{"status": "complete", "summary": "Last completed synthesis", "completedAt": "earlier"}],
    }

    result = add_pipeline_progress(pipeline)

    assert result["wholeBookSummary"]["status"] == "ready"
    assert result["wholeBookSummary"]["previousResult"]["summary"] == "Last completed synthesis"


def test_inferences_are_pipeline_owned_and_have_a_timing_view() -> None:
    app = (Path(__file__).parents[1] / "web" / "app.js").read_text(encoding="utf-8")
    assert 'timingChartControl("inferences")' in app
    assert 'view === "inferences"' in app
    assert 'const statusLabel = ({ready: "Ready", pending: "Queued", blocked: "Waiting", partial: "Partial"})[status]' in app
    assert 'pipelineControl({action: "questions", label: status === "complete" ? "Rebuild" : "Run"' not in app


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


def test_model_free_report_is_wired_to_a_privacy_safe_manifest() -> None:
    root = Path(__file__).parents[1]
    app = (root / "web" / "app.js").read_text(encoding="utf-8")
    exporter = (root / "web" / "portable-report.js").read_text(encoding="utf-8")
    assert 'from "./portable-report.js?v=' in app
    assert 'from "./smell-labels.js?v=canonical-labels-170"' in exporter
    assert "data-download-portable-report" in app
    assert 'schema: "bookinator-report-v1"' in exporter
    assert "chapter.text" not in exporter
    assert "chapter.markdown" not in exporter
    assert "JSON.stringify(pipeline)" not in exporter
    assert "networkRequired: false" in exporter
    assert '.site-nav-groups button[aria-current="true"]{color:#fff;background:#19385f' in exporter
    assert '.site-nav .site-nav-shelf a[aria-current="page"]{color:#10264a;background:#eaf6ff' in exporter
    assert "border-bottom-color:#55d6ff" not in exporter

    node = shutil.which("node")
    if not node:
        pytest.skip("Node is required for the portable report behavior test")
    script = r'''
      import {auditPortableReport, buildPortableReportManifest, buildPortableReportHtml, reportExportFilename} from "./web/portable-report.js";
      const pipeline = {
        chapters: [{sequence: 1, title: "CHAPTER 1", text: "SECRET SOURCE", markdown: "# SECRET", summary: "Safe summary", status: "complete", wordCount: 100, durationSeconds: 60, emotionStatus: "complete", emotion: {distribution: {fear: .62, disgust: .21}}, tagStatus: "complete", tag: {signals: [{id: "third-limited", family: "perspective", score: .91}, {id: "horror", family: "genre", score: .82}]}, llmReviewStatus: "complete", llmReview: {editorialVerdict: "no_material_concerns", editorialSummary: "A confident opening.", editorialStrengths: ["Atmosphere"], commercialStrengths: ["Clear audience"], commercialRisks: ["Niche appeal"], likelyReaders: ["Gothic readers"], dimensions: {narrative_engagement: {applicable: true, score: 4}}},
          smell: {candidates: [{id: "finding", sentence: "Selected sentence", userStatus: "reported", judgment: {issue: "Concern", reason: "Reason", severity: "medium"}}]} }],
        chunks: [{chapterSequence: 1, dossierStatus: "complete", dossier: {entities: ["Timmy - protagonist"], facts: ["PRIVATE DOSSIER FACT"]}}],
        stages: [{id: "summaries", label: "Summaries", status: "complete", model: "reader"}, {id: "prose", label: "Prose", status: "paused", model: "retired-gemma"}],
        wholeBookLlmReview: {status: "complete", overallAssessment: "An atmospheric, commercially focused story.", strengths: [{title: "Atmosphere", synthesis: "Dread accumulates.", significance: "Preserve it."}], risks: [{title: "Distance", synthesis: "Characters remain remote.", significance: "Some readers may disengage."}], editorialPriorities: [{title: "Protect the voice", rationale: "It defines the work.", scope: "Whole manuscript", priority: "high"}], likelyReaders: [{reader: "Lovecraft fans", fit: "Strong fit.", caution: "Deliberate distance."}], commercialPositioning: "For readers of literary cosmic horror.", sourceChapterCount: 1},
        wholeBookDossier: {status: "complete", synopsis: "A consolidated account.", facts: ["The house is old."], events: ["A visitor arrives."], entities: ["The visitor"], locations: ["The house"]},
        reviewerSignoff: {status: "complete", reviewerName: "Randal", notes: "The structure is ready for Michael.", completedAt: "2026-09-24T12:00:00Z"}
      };
      const annotation = {id: "note-1", chapterSequence: 1, chapterLabel: "CHAPTER 1", pageStart: 5, pageEnd: 6, quote: "A selected passage", comment: "Randal wants this promise paid off.", categories: ["plot", "continuity"], priority: "high", status: "resolved"};
      const manifest = buildPortableReportManifest(pipeline, {title: "Shadow", author: "Michael"}, {annotations: [annotation]});
      const serialized = JSON.stringify(manifest);
      const html = buildPortableReportHtml(manifest);
      const summaryOnly = buildPortableReportManifest(pipeline, {title: "Shadow", author: "Michael"}, {sections: ["overview"]});
      if (serialized.includes("SECRET SOURCE") || serialized.includes("PRIVATE DOSSIER FACT")) process.exit(2);
      if (!html.includes("Shadow") || !html.includes("Selected sentence") || !html.includes("bookinator-report-v1")) process.exit(3);
      if (!html.includes("Reviewer comments") || !html.includes("Randal wants this promise paid off.") || !html.includes("A selected passage")) process.exit(11);
      if (manifest.reviewerSignoff.reviewerName !== "Randal" || manifest.completeness.reviewerSignoff.status !== "complete") process.exit(15);
      if (!html.includes("Review signed off for now") || !html.includes("The structure is ready for Michael.")) process.exit(16);
      if (serialized.includes('retired-gemma') || manifest.completeness.stages.some((stage) => stage.id === 'prose')) process.exit(17);
      if (!manifest.export.sections.includes("chapter-length") || !html.includes('chapter-length-row') || !html.includes("'Chapter length'")) process.exit(14);
      if (manifest.reviewerComments[0].categories.join(",") !== "plot,continuity" || manifest.completeness.reviewerComments.count !== 1) process.exit(12);
      if (manifest.reviewerComments[0].status !== "active" || !html.includes("Active reviewer note") || html.includes("Accepted by the reviewer")) process.exit(28);
      if (!html.includes("<title>Bookinator - Shadow - Michael</title>")) process.exit(13);
      if (!html.includes("Whole-book emotional profile") || !html.includes("chapters at 10%+")) process.exit(24);
      if (!manifest.export.sections.includes("tags") || manifest.chapters[0].tags[0].label !== "Third limited" || !html.includes("Tag frequencies") || !html.includes("tag-profile-row")) process.exit(25);
      if (!manifest.export.sections.includes("llm-review") || manifest.wholeBookLlmReview.likelyReaders[0].reader !== "Lovecraft fans" || !html.includes("Whole-book risks") || !html.includes("Chapter conclusions") || !html.includes("llm-synthesis-overall")) process.exit(26);
      if (!manifest.export.sections.includes("dossier") || manifest.wholeBookDossier.facts[0] !== "The house is old." || !html.includes("Dossier synthesis") || !html.includes("Evidence-linked whole-book memory")) process.exit(27);
      const exportDate = new Date(2026, 8, 24, 12, 0, 0);
      if (reportExportFilename({title: "The Dunwich Horror"}, "html", {date: exportDate}) !== "bookinator-the_dunwich_horror-2026-09-24.html") process.exit(22);
      if (reportExportFilename({title: "The Dunwich Horror"}, "pdf", {section: "Emotion map", date: exportDate}) !== "bookinator-the_dunwich_horror-emotion_map-2026-09-24.pdf") process.exit(23);
      if (summaryOnly.chapters[0].summary || summaryOnly.smells.length || summaryOnly.chapters[0].smells.length || summaryOnly.chapters[0].llmReview || summaryOnly.wholeBookLlmReview || summaryOnly.wholeBookDossier) process.exit(4);
      if (JSON.stringify(summaryOnly).includes("Selected sentence")) process.exit(5);
      if (!html.includes('id="menu-toggle"') || !html.includes("addEventListener('hashchange', showPage)")) process.exit(6);
      if (!html.includes('class="site-nav-groups"') || !html.includes('class="site-nav-shelf"')) process.exit(18);
      if (!html.includes("{id:'book', label:'Book', sections:['overview','chapters','chapter-length','dossier']}") || !html.includes("{id:'story', label:'Story', sections:['emotions','tags','questions','connections']}")) process.exit(19);
      if (!html.includes("{id:'editorial', label:'Editorial', sections:['reviewer','llm-review','smells']}") || !html.includes("{id:'about', label:'About this report', sections:['method','guide']}")) process.exit(20);
      if (html.includes("sections:['method','guide','license']")) process.exit(21);
      if (!html.includes('href="#license"') || !html.includes('Using this report') || !html.includes('Business Source License 1.1')) process.exit(7);
      if (!manifest.export.totalAnalysisSeconds || !manifest.provenance[0].durationSeconds) process.exit(8);
      if (!auditPortableReport({manifest, artifact: html, pipeline}).ok) process.exit(9);
      let blocked = false;
      try { auditPortableReport({manifest: {...manifest, rawResponse: "forbidden"}, artifact: html, pipeline}); } catch { blocked = true; }
      if (!blocked) process.exit(10);
    '''
    subprocess.run([node, "--input-type=module", "-e", script], cwd=root, check=True)


def test_confirmation_dialog_enter_activates_its_default_action() -> None:
    app = (Path(__file__).parents[1] / "web" / "app.js").read_text(encoding="utf-8")
    assert 'event.key !== "Enter"' in app
    assert 'installDefaultDialogAction(backdrop, approve)' in app
    assert "accept.focus();" in app
    assert 'event.target.closest("textarea, [contenteditable=true]")' in app


def test_saved_report_index_is_local_to_each_book(tmp_path: Path) -> None:
    records = [{"id": "a" * 32, "filename": "shadow.html", "format": "html", "bytes": 123}]
    with patch.object(server, "REPORTS_ROOT", tmp_path):
        server.write_saved_reports("book-1234", records)
        assert server.load_saved_reports("book-1234") == records
        assert server.load_saved_reports("other-book") == []
        assert server.saved_report_path("book-1234", "a" * 32, "html") == tmp_path / "book-1234" / f"{'a' * 32}.html"


def test_editorial_question_and_title_research_priorities_are_documented() -> None:
    todo = (Path(__file__).parents[1] / "docs" / "TODO.md").read_text(encoding="utf-8")
    assert "## Urgent: sharper questions from summaries and dossiers" in todo
    assert "## Low priority: book-title research and collision checking" in todo


def test_workspace_groups_end_with_their_human_judgment_views() -> None:
    source = (Path(__file__).parents[1] / "web" / "app.js").read_text(encoding="utf-8")
    tabs = source.split("const workspaceTabs = [", 1)[1].split("];", 1)[0]
    expected = ["pipeline", "chapters", "summaries", "dossiers", "emotions", "tags", "smells", "context", "llm-review", "inferences", "report", "overview", "chapter-length", "reviewer-report", "smell-report", "emotion-map", "tag-report", "connections", "questions", "reviewer", "assessment"]
    positions = [tabs.index(f'{{id: "{tab}"') for tab in expected]
    assert positions == sorted(positions)
    assert tabs.lstrip().startswith('{id: "identity", label: "Identity"},')
    assert tabs.rstrip().endswith('{id: "assessment", label: "Assessment"},')
    assert '{id: "report", label: "Share"}' in tabs
    styles = (Path(__file__).parents[1] / "web" / "styles.css").read_text(encoding="utf-8")
    assert 'const workspaceGroups = {' in source
    assert 'analysis: ["pipeline", "chapters", "summaries", "dossiers", "emotions", "tags", "smells", "context", "llm-review", "inferences", "reviewer"]' in source
    assert 'explore: ["report", "overview", "chapter-length", "reviewer-report", "emotion-map", "tag-report", "connections", "questions", "smell-report", "llm-review-report", "assessment"]' in source
    assert '{id: "plot", label: "Plot arcs"}' not in tabs
    assert 'const workspaceShelfEndTabs = new Set(["reviewer", "assessment"]);' in source
    assert 'title: "Assessment"' in source
    assert ".book-workspace-primary" in styles
    assert ".book-workspace-shelf" in styles
    assert ".workspace-primary-spacer" in styles
    assert ".workspace-shelf-spacer" in styles
    assert 'activeTab === "identity"' in source
    assert 'data-book-identity-form-host' in source
    assert 'openExistingBook(book.id, {host:' in source
    assert 'function restoreBookFormToDialog()' in source
    assert 'data-edit-identity' not in source
    assert ".inline-book-form" in styles


def test_identity_form_orders_icon_and_priority_before_llm_review() -> None:
    root = Path(__file__).parents[1]
    page = (root / "web" / "index.html").read_text(encoding="utf-8")
    app = (root / "web" / "app.js").read_text(encoding="utf-8")
    styles = (root / "web" / "styles.css").read_text(encoding="utf-8")
    form = page.split('<form id="book-form">', 1)[1].split("</form>", 1)[0]

    positions = [
        form.index('class="identity-fields"'),
        form.index('class="book-mark-editor"'),
        form.index('class="analysis-priority-picker"'),
        form.index('class="llm-review-setting"'),
    ]
    assert positions == sorted(positions)
    assert form.count('type="radio" name="book-priority"') == 4
    assert '<select id="book-priority"' not in form
    assert "Analyze in the normal library queue." not in form
    assert "llm-review-setting" in form.split("<footer>", 1)[0].rsplit("</section>", 1)[0]
    assert "selectedBookPriority()" in app
    assert "setBookPriority(book.priority || \"normal\")" in app
    assert "The running Bookinator server did not save the LLM Review setting." in app
    assert ".book-mark-editor { display: grid; grid-template-columns: 136px" in styles
    assert ".book-mark-preview { position: relative; grid-row: 1 / 3; width: 132px; height: 162px;" in styles
    assert ".book-mark-preview.has-cover-metadata .book-icon-face { inset: 18px 8px auto 16%; width: auto; height: 92px; }" in styles
    assert ".book-mark-preview.has-cover-metadata .book-cover-author { top: 122px;" in styles
    assert ".has-cover-metadata .book-cover-author::before { content: none; }" in styles
    assert ".book-mark-image-status { grid-column: 2;" in styles


def test_embedded_identity_form_autosaves_but_creation_dialog_still_submits() -> None:
    root = Path(__file__).parents[1]
    page = (root / "web" / "index.html").read_text(encoding="utf-8")
    app = (root / "web" / "app.js").read_text(encoding="utf-8")
    styles = (root / "web" / "styles.css").read_text(encoding="utf-8")

    assert 'id="identity-save-state" role="status" aria-live="polite"' in page
    assert "function scheduleIdentityAutosave()" in app
    assert "async function flushIdentityAutosave()" in app
    assert "persistBookForm({embedded: true, revision})" in app
    assert 'setIdentitySaveState("saving", "Saving changes…")' in app
    assert 'setIdentitySaveState("", "All changes saved")' in app
    assert "const saved = await flushIdentityAutosave();" in app
    assert "else await persistBookForm({embedded: false});" in app
    assert 'sameWorkspace && activeTab === "identity" && bookForm.closest("#book-workspace-body")' in app
    assert '.inline-book-form footer .identity-save-state { display: inline-flex; }' in styles
    assert '.inline-book-form footer button { display: none;' in styles


def test_save_book_preserves_llm_review_opt_in_and_priority(tmp_path: Path) -> None:
    library_path = tmp_path / "library.json"
    library_path.write_text("[]", encoding="utf-8")
    with patch.object(server, "LIBRARY_PATH", library_path):
        saved = server.save_book({
            "id": "book-12345678",
            "title": "The Dunwich Horror",
            "author": "H. P. Lovecraft",
            "priority": "high",
            "llmReviewEnabled": True,
        })

        assert saved["priority"] == "high"
        assert saved["llmReviewEnabled"] is True
        assert server.load_library()[0]["llmReviewEnabled"] is True


def test_save_book_rejects_duplicate_titles_but_allows_same_book_updates(tmp_path: Path) -> None:
    library_path = tmp_path / "library.json"
    library_path.write_text(json.dumps([{
        "id": "book-original-1234",
        "manuscriptId": "manuscript-original-1234",
        "title": "Shadow",
        "author": "Michael Donaubauer",
    }]), encoding="utf-8")

    with patch.object(server, "LIBRARY_PATH", library_path):
        with pytest.raises(server.ImportTitleCollision) as collision:
            server.save_book({
                "id": "book-new-copy-1234",
                "manuscriptId": "manuscript-new-copy-1234",
                "title": " shadow ",
                "author": "Michael Donaubauer",
            })

        assert collision.value.collisions == [{
            "importKey": "book-new-copy-1234",
            "title": "shadow",
            "suggestedTitle": f"shadow (New import {server.datetime.now().date().isoformat()})",
            "reason": "same-title",
        }]
        assert len(server.load_library_records()) == 1

        updated = server.save_book({
            "id": "book-original-1234",
            "manuscriptId": "manuscript-original-1234",
            "title": "Shadow",
            "author": "Michael Donaubauer",
            "priority": "high",
        })
        assert updated["priority"] == "high"
        assert len(server.load_library_records()) == 1


def test_new_book_action_waits_for_identified_title_and_author() -> None:
    root = Path(__file__).parents[1]
    app = (root / "web" / "app.js").read_text(encoding="utf-8")
    page = (root / "web" / "index.html").read_text(encoding="utf-8")
    styles = (root / "web" / "styles.css").read_text(encoding="utf-8")
    assert 'const ready = state.editingBookId ? hasTitle : Boolean(state.draftManuscriptId && hasTitle && hasAuthor);' in app
    assert 'state.draftManuscriptId = null;\n  titleInput.value = "";\n  authorInput.value = "";\n  refreshBookSaveState();' in app
    assert 'id="save-book" type="submit" disabled' in page
    assert ".primary-button:disabled" in styles


def test_new_manuscript_title_collision_prompts_before_resubmitting() -> None:
    app = (Path(__file__).parents[1] / "web" / "app.js").read_text(encoding="utf-8")

    assert 'response.status === 409 && result.code === "title-collision" && !existing' in app
    assert 'context: "Duplicate book title"' in app
    assert 'label: "Title for this new manuscript"' in app
    assert "function suggestedNewManuscriptTitle(title)" in app
    assert 'const titleCollision = state.books.some(' in app
    assert 'importKey = "new-manuscript"' in app
    assert "This library already contains that title." in app
    assert "This manuscript was not added because its title matches another book." in app
    assert "return persistBookForm({embedded, revision});" in app


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


def test_ready_question_inference_is_part_of_the_automatic_queue() -> None:
    book = {"id": "book-1234", "manuscriptId": "manuscript", "priority": "normal"}
    pipeline = {
        "stages": [
            {"id": "chapter-archive", "status": "complete"},
            {"id": "summaries", "status": "complete"},
            {"id": "dossiers", "status": "complete"},
            {"id": "emotions", "status": "pending"},
            {"id": "tags", "status": "pending"},
            {"id": "smells", "status": "pending"},
        ],
        "chapters": [{"sequence": 1, "title": "CHAPTER 1", "status": "complete", "summary": "A question is raised.", "emotionStatus": "pending", "tagStatus": "pending", "smellStatus": "pending"}],
        "chunks": [{"sequence": 1, "chapterSequence": 1, "dossierStatus": "complete", "dossier": {"questions": ["Who did it?"]}}],
    }

    with patch.object(server, "stage_rollup_action", return_value=""):
        assert next_pipeline_action(book, pipeline) == "questions"

    signature = server.question_tracker_input_signature(pipeline)
    pipeline["questionTracker"] = {"status": "complete", "inputSignature": signature}
    with patch.object(server, "stage_rollup_action", return_value=""):
        assert next_pipeline_action(book, pipeline) == "emotions"


def test_completed_legacy_question_tracker_is_migrated_without_requeueing() -> None:
    book = {"id": "book-1234", "manuscriptId": "manuscript", "priority": "normal"}
    pipeline = {
        "stages": [
            {"id": "chapter-archive", "status": "complete"},
            {"id": "summaries", "status": "complete"},
            {"id": "dossiers", "status": "complete"},
            {"id": "emotions", "status": "pending"},
        ],
        "chapters": [{"sequence": 1, "title": "CHAPTER 1", "status": "complete", "summary": "A question is raised.", "keyPoints": [], "newQuestions": ["Who did it?"], "emotionStatus": "pending"}],
        "chunks": [{"sequence": 1, "chapterSequence": 1, "dossierStatus": "complete", "dossier": {"questions": ["Who did it?"], "promises": []}}],
    }
    legacy_signature = server.legacy_question_tracker_input_signature(pipeline)
    current_signature = server.question_tracker_input_signature(pipeline)
    assert legacy_signature != current_signature
    pipeline["questionTracker"] = {"status": "complete", "items": [], "inputSignature": legacy_signature}

    add_pipeline_progress(pipeline)

    assert pipeline["questionTracker"]["status"] == "complete"
    assert pipeline["questionTracker"]["inputSignature"] == current_signature
    assert all(inference["status"] == "complete" for inference in pipeline["inferences"])
    with patch.object(server, "stage_rollup_action", return_value=""):
        assert next_pipeline_action(book, pipeline) == "emotions"


def test_loading_a_completed_legacy_question_tracker_persists_the_signature_migration(tmp_path: Path) -> None:
    book = {"id": "book-1234", "manuscriptId": "manuscript"}
    pipeline = {
        "status": "complete",
        "phase": "complete",
        "stages": [
            {"id": "chapter-archive", "status": "complete"},
            {"id": "summaries", "status": "complete"},
            {"id": "dossiers", "status": "complete"},
        ],
        "chapters": [{"sequence": 1, "title": "CHAPTER 1", "status": "complete", "summary": "A question is raised.", "keyPoints": [], "newQuestions": ["Who did it?"]}],
        "chunks": [{"sequence": 1, "chapterSequence": 1, "chunkInChapter": 1, "dossierStatus": "complete", "dossier": {"questions": ["Who did it?"], "promises": []}}],
    }
    legacy_signature = server.legacy_question_tracker_input_signature(pipeline)
    pipeline["questionTracker"] = {"status": "complete", "items": [], "inputSignature": legacy_signature}
    root = tmp_path / "books"
    target = root / "manuscript" / "pipeline.json"
    target.parent.mkdir(parents=True)
    target.write_text(json.dumps(pipeline), encoding="utf-8")

    with patch.object(server, "BOOKS_ROOT", root), patch.object(server, "pipeline_worker_is_alive", return_value=False):
        loaded = server.load_pipeline(book)

    current_signature = server.question_tracker_input_signature(loaded)
    saved = json.loads(target.read_text(encoding="utf-8"))
    assert loaded["questionTracker"]["status"] == "complete"
    assert saved["questionTracker"]["inputSignature"] == current_signature


def test_legacy_question_tracker_does_not_mask_richer_question_inputs() -> None:
    pipeline = {
        "stages": [{"id": "chapter-archive", "status": "complete"}, {"id": "summaries", "status": "complete"}, {"id": "dossiers", "status": "complete"}],
        "chapters": [{"sequence": 1, "title": "CHAPTER 1", "status": "complete", "summary": "A question is raised.", "keyPoints": [], "newQuestions": ["Who did it?"]}],
        "chunks": [{"sequence": 1, "chapterSequence": 1, "dossierStatus": "complete", "dossier": {"questions": ["Who did it?"], "promises": []}}],
    }
    legacy_signature = server.legacy_question_tracker_input_signature(pipeline)
    pipeline["chapters"][0]["promptVersion"] = "chapter-summary-v2"
    pipeline["questionTracker"] = {"status": "complete", "items": [], "inputSignature": legacy_signature}

    add_pipeline_progress(pipeline)

    assert pipeline["questionTracker"]["status"] == "ready"


def test_incomplete_dossiers_rely_on_the_automatic_queue() -> None:
    app = (Path(__file__).parents[1] / "web" / "app.js").read_text(encoding="utf-8")
    assert 'pipelineControl({action: "dossiers", label: "Finish"' not in app
    assert 'title: "Finish the remaining dossiers before returning to other analysis"' not in app
    assert 'resetCategoryControl("dossier-restart", "dossier")' in app


def test_analysis_categories_expose_development_reset_all_controls() -> None:
    app = (Path(__file__).parents[1] / "web" / "app.js").read_text(encoding="utf-8")
    assert 'label: "Reset all"' in app
    assert 'data-development-control' in app
    assert 'const developmentControlsEnabled = true' in app
    assert 'if (!developmentControlsEnabled) return ""' in app
    assert 'resetCategoryControl("restart", "chapter summary")' in app
    assert 'resetCategoryControl("dossier-restart", "dossier")' in app
    assert 'resetCategoryControl(signalView.restart, signalView.noun)' in app
    assert 'pipeline.chapters?.length ? resetCategoryControl' in app
    assert 'pipeline.chunks?.length ? resetCategoryControl' in app


def test_summary_and_dossier_tabs_require_their_whole_book_entries() -> None:
    app = (Path(__file__).parents[1] / "web" / "app.js").read_text(encoding="utf-8")
    assert 'summaries: (stageComplete("summaries") || chapterSummariesComplete) && wholeSummaryComplete' in app
    assert 'dossiers: (stageComplete("dossiers") || chunkDossiersComplete) && wholeDossierComplete' in app
    assert 'pipeline.wholeBookSummary?.status === "complete"' in app
    assert 'pipeline.wholeBookDossier?.status === "complete"' in app
    assert 'progressMarkup = taskProgress({label: "Overall reading progress", unit: "chapters", progress, activity: currentActivity' in app
    assert 'activity: summariesDone ? "" : currentActivity' not in app


def test_whole_book_dossier_discloses_the_reconciled_memory() -> None:
    app = (Path(__file__).parents[1] / "web" / "app.js").read_text(encoding="utf-8")
    assert "function wholeBookDossierMarkup(dossier)" in app
    for field in ("facts", "events", "entities", "locations", "current_times", "questions", "promises", "timeline_observations", "contradictions"):
        assert f"dossier.{field}" in app
    assert 'kind === "dossiers" ? wholeBookDossierMarkup(displayRollup)' in app


def test_whole_book_summary_and_dossier_statuses_share_run_details() -> None:
    app = (Path(__file__).parents[1] / "web" / "app.js").read_text(encoding="utf-8")
    row = app[app.index("function wholeBookAnalysisRow"):app.index("function chapterMapRow")]
    assert 'const inspectable = ["chapters", "summaries", "dossiers", "llm-review"].includes(kind)' in row
    assert 'analysisStatusControl({' in row
    assert 'label: "State"' in row
    assert 'label: "Inputs"' in row
    assert 'label: "Depends on"' in row
    assert 'kind === "llm-review" ? "whole-llm-review"' in row
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
    assert 'title: "Share this analysis"' in app
    assert 'title: "Book summary"' in app
    assert 'title: "Smells report"' in app
    assert 'title: "Emotion map"' in app


def test_reviewer_notes_are_active_or_archived_without_author_acceptance_ui() -> None:
    root = Path(__file__).parents[1]
    app = (root / "web" / "app.js").read_text(encoding="utf-8")
    portable = (root / "web" / "portable-report.js").read_text(encoding="utf-8")

    reviewer_ui = app.split("function reviewerWorkspaceMarkup", 1)[1].split("function reviewerReportMarkup", 1)[0]
    reviewer_report = app.split("function reviewerReportMarkup", 1)[1].split("const shareSectionDefinitions", 1)[0]
    assert "data-toggle-annotation" not in app
    assert "Accept</span>" not in reviewer_ui
    assert "Reopen</span>" not in reviewer_ui
    assert "accepted</span>" not in reviewer_ui
    assert "<span>active</span>" in reviewer_ui
    assert "<span>archived</span>" in reviewer_ui
    assert "active comments" in reviewer_report
    assert "Accepted by the reviewer" not in app
    assert "Accepted by the reviewer" not in portable
    assert "Active reviewer note" in portable
    assert 'status: "active"' in portable


def test_explore_reports_are_separate_from_inference_jobs_and_export_shareable_artifacts() -> None:
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
    assert "function tagsReportMarkup" in app
    assert "function chapterLengthReportMarkup" in app
    assert "function reviewerReportMarkup" in app
    assert "function editorReportPdf" in app
    assert "data-download-editor-report" in app
    assert "reportableSmells(pipeline)" in app
    assert 'Number(score) >= .10' in app
    assert "--chapter-scale" in app
    assert 'reportExportControl("overview")' in app
    assert 'reportExportControl("chapter-length")' in app
    assert '"chapter-length": chapters.length > 0' in app
    assert 'reportExportControl("emotion-map")' in app
    assert 'reportExportControl("tag-report")' in app
    assert 'reportExportControl("llm-review-report")' in app
    assert '{id: "llm-review-report", htmlId: "llm-review", label: "LLM Review", formats: ["html", "pdf"]' in app
    assert 'item.formats.includes(format) && (!item.available || item.available(pipeline))' in app
    assert 'reportExportControl("reviewer-report")' in app
    assert 'data-report-export="${escapeHtml(report)}"' in app
    assert 'data-download-portable-report>Download interactive HTML</button>' in app
    assert 'data-download-editor-report>Download PDF</button>' in app
    assert 'tocCanvas = newPage("Table of contents")' in app
    assert "drawBookIcon(context" in app
    pdf = app.split("async function editorReportPdf", 1)[1].split("function csvCell", 1)[0]
    emotion_pdf = pdf.split('section("emotion-map", "Emotion map"', 1)[1].split('section("questions"', 1)[0]
    assert 'const rollup = emotionRollupData(pipeline)' in emotion_pdf
    assert 'heading("Whole-book emotional profile", 1)' in emotion_pdf
    tag_pdf = pdf.split('section("tag-report", "Tag frequencies"', 1)[1].split('section("emotion-map"', 1)[0]
    assert 'const rollup = tagRollupData(pipeline)' in tag_pdf
    assert 'heading("Whole-book tag frequencies", 1)' in tag_pdf
    llm_pdf = pdf.split('section("llm-review-report", "LLM Review"', 1)[1].split('section("smell-report"', 1)[0]
    assert 'synthesis.overallAssessment' in llm_pdf
    assert '"Strengths to preserve"' in llm_pdf
    assert '"Whole-book risks"' in llm_pdf
    assert '"Editorial priorities"' in llm_pdf
    assert '"Likely readers"' in llm_pdf
    assert 'heading("Whole-book assessment profile", 2)' in llm_pdf
    assert 'heading("Chapter conclusions", 2)' in llm_pdf
    assert pdf.index('section("status", "Analysis status"') < pdf.index('section("overview", "Book summary"')
    assert pdf.index('section("overview", "Book summary"') < pdf.index('section("chapter-length", "Chapter length"')
    assert pdf.index('section("chapter-length", "Chapter length"') < pdf.index('section("smell-report", "Undismissed Smells"')
    chapter_length_pdf = pdf.split('section("chapter-length", "Chapter length"', 1)[1].split('section("dossier"', 1)[0]
    assert '{label: "Shortest"' in chapter_length_pdf
    assert '{label: "Median"' in chapter_length_pdf
    assert '{label: "Longest"' in chapter_length_pdf
    assert pdf.index('section("overview", "Book summary"') < pdf.index('section("smell-report", "Undismissed Smells"')
    assert pdf.index('section("overview", "Book summary"') < pdf.index('section("reviewer-report", "Reviewer comments"')
    assert pdf.index('section("reviewer-report", "Reviewer comments"') < pdf.index('section("smell-report", "Undismissed Smells"')
    reviewer_pdf = pdf.split('section("reviewer-report", "Reviewer comments"', 1)[1].split('section("emotion-map"', 1)[0]
    assert "annotation.chapterLabel" in reviewer_pdf
    assert "annotation.pageStart" in reviewer_pdf
    assert "annotation.quote" in reviewer_pdf
    assert "annotation.comment" in reviewer_pdf
    assert "annotationCategories(annotation)" in reviewer_pdf
    assert "annotation.priority" in reviewer_pdf
    assert 'paragraph("Active reviewer note"' in reviewer_pdf
    assert "Accepted by the reviewer" not in reviewer_pdf
    assert "pipeline.reviewerSignoff" in reviewer_pdf
    assert "REVIEW SIGNED OFF FOR NOW" in reviewer_pdf
    assert "reviewerSignoff.reviewerName" in reviewer_pdf
    assert "reviewerSignoff.notes" in reviewer_pdf
    assert '!/^prose$/i.test(String(stage.id || ""))' in pdf
    assert 'color = complete ? "#23765b" : "#b7483f"' in pdf
    assert 'heading("Undismissed Smells", 1)' in pdf
    assert 'currentSection.replace(/(?: · continued)+$/' in pdf
    assert ".shelf-lead-action" in styles
    assert ".emotion-map-track" in styles
    assert ".emotion-map-legend" in styles
    assert ".review-comment-card" in styles


def test_every_implemented_explore_report_has_html_and_pdf_selectors() -> None:
    app = (Path(__file__).parents[1] / "web" / "app.js").read_text(encoding="utf-8")
    definitions = app.split("const shareSectionDefinitions = [", 1)[1].split("];", 1)[0]
    expected = {
        "overview", "chapter-length", "reviewer-report", "emotion-map", "tag-report",
        "connections", "questions", "smell-report", "llm-review-report",
    }
    for report in expected:
        definition = definitions.split(f'{{id: "{report}"', 1)[1].split("}", 1)[0]
        assert 'formats: ["html", "pdf"]' in definition
    dossier = definitions.split('{id: "dossier"', 1)[1].split("}", 1)[0]
    assert 'formats: ["html", "pdf"]' in dossier
    assert 'available: (pipeline) => pipeline.wholeBookDossier?.status === "complete"' in dossier
    assert 'available: (pipeline) => pipeline.wholeBookLlmReview?.status === "complete"' in definitions


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
    assert '<main class="machine-page" id="machine-page" hidden>' in page
    assert '<h1 id="system-title">Machine</h1>' in page
    assert 'id="system-dialog"' not in page
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


def test_workspace_identity_and_shelf_separators_follow_primary_navigation() -> None:
    root = Path(__file__).parents[1]
    app = (root / "web" / "app.js").read_text(encoding="utf-8")
    styles = (root / "web" / "styles.css").read_text(encoding="utf-8")
    assert '<p class="workspace-page-title">Analysis</p>' in app
    assert "Book workspace</p>" not in app
    assert 'if (["pipeline", "report"].includes(tab.id)) classes.push("shelf-divider-after")' in app
    assert ".shelf-divider-after::before" in styles


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
    assert 'chapterHeadingInspectionMarkup(pipeline, book)' in app
    assert 'function chapterHeadingComparisonMarkup' not in app
    assert 'content: `${chapterActivity}<div class="chapter-map-list">${wholeBookAnalysisRow' in app
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


def test_pipeline_ledger_exposes_elementary_work_in_chapter_order() -> None:
    root = Path(__file__).parents[1]
    source = (root / "web" / "app.js").read_text(encoding="utf-8")
    styles = (root / "web" / "styles.css").read_text(encoding="utf-8")
    ledger = source.split("function chapterPipelineLedger", 1)[1].split("function openPipelineStageDetails", 1)[0]

    assert 'id: "summaries", label: "Summary"' in ledger
    assert 'id: "dossiers", label: "Dossier"' in ledger
    assert ledger.index('id: "llm-review"') < ledger.index('id: "cumulative-context"') < ledger.index('id: "emotions"') < ledger.index('id: "tags"') < ledger.index('id: "smells"')
    assert 'class="pipeline-chapter-group' in ledger
    assert 'const open = openRows.has(key);' in ledger
    assert 'data-show-chapter-group-details' in ledger
    assert 'Chapter processing total' in ledger
    assert 'configureRunInspector();' in source
    assert 'data-pipeline-task=' in source
    assert 'Stage totals summarize the ledger; they are not queue items.' in source
    assert ".pipeline-chapter-tasks" in styles
    assert ".pipeline-elementary-task" in styles
    assert ".pipeline-chapter-group.running .chapter-status" in styles


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
    assert ".chapter-summary.complete .chapter-status" in styles
    assert "background: var(--status-color)" in styles.split(
        ".chapter-summary.complete .chapter-status", 1
    )[1].split("}", 1)[0]
    assert 'const status = rawStatus === "blocked" ? "pending" : rawStatus;' in source
    assert ".chapter-summary.pending .chapter-status" in styles
    assert "background: #dce4ed" in styles.split(
        ".chapter-summary.pending .chapter-status", 1
    )[1].split("}", 1)[0]
    assert ".whole-book-status" not in styles


def test_summary_workspace_does_not_render_structured_activity_as_text() -> None:
    source = (Path(__file__).parents[1] / "web" / "app.js").read_text(encoding="utf-8")
    task_view = source.split("function workspaceTaskView", 1)[1].split("function provisionalAnalysisNotice", 1)[0]
    summary_view = source.split('const summaryTitle = "Chapter summaries"', 1)[1].split("} else {", 1)[0]
    assert "activity =" not in task_view
    assert "${activity}" not in task_view
    assert "activity:" not in summary_view


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
    assert 'const mapReady = chapterMapReadyForReview(pipeline)' in source
    assert 'statusLabel: !mapReady ? "Running"' in source
    assert '["chapters", "summaries", "dossiers", "llm-review"].includes(kind)' in source
    assert 'kind === "chapters" ? "stage"' in source
    assert 'kind === "chapters" ? "structure"' in source
    assert 'mapReady && pipeline.chapters?.length' in source
    assert 'class="chapter-map-status ${mapStatusTone}"' in source
    chapters_view = source.split('} else if (activeTab === "chapters") {', 1)[1].split('} else if (signalView)', 1)[0]
    assert "Current pipeline work" not in chapters_view
    assert "The chapter map is finished" not in chapters_view


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
    assert '{"summary", "dossier", "emotion", "tag", "smell", "context", "llm-review", "whole-summary", "whole-llm-review"}' in server


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
    assert recommended_roles(645) == {"primary": "qwen3.5:122b", "fast": "qwen3.5:9b"}


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


def test_unchaptered_reflowable_work_is_one_entirety_without_fake_page_chapters() -> None:
    chapters, method = detect_chapters([
        "The wallpaper changes when the light changes.",
        "The narrator continues watching it from the room.",
        "The pattern appears to move at night.",
    ], fixed_pagination=False)

    assert len(chapters) == 1
    assert chapters[0]["title"] == "Entirety"
    assert chapters[0]["pageStart"] == 1
    assert chapters[0]["pageEnd"] == 3
    assert method == "entire reflowable work; no confident chapter headings were found"


def test_existing_reflowable_page_group_is_presented_as_entirety_without_mutating_analysis() -> None:
    book = {"id": "book-12345678", "manuscriptId": "manuscript-1234"}
    pipeline = {
        "chapters": [{"sequence": 1, "title": "Pages 1–10", "status": "complete", "summary": "Preserved."}],
        "chunks": [{"chapterSequence": 1, "chapterLabel": "Pages 1–10", "dossierStatus": "complete"}],
    }

    with patch.object(server, "source_has_fixed_pagination", return_value=False):
        visible = server.pipeline_with_reflowable_labels(book, pipeline)

    assert visible["chapters"][0]["title"] == "Entirety"
    assert visible["chunks"][0]["chapterLabel"] == "Entirety"
    assert visible["chapters"][0]["summary"] == "Preserved."
    assert pipeline["chapters"][0]["title"] == "Pages 1–10"


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
    assert chapter_heading_report_warnings(report) == ["Unique opening headings outside the established chapter pattern: INTERMISSION"]


def test_heading_report_explains_front_matter_and_repeated_chapter_title() -> None:
    pages = [
        "THE MALTESE FALCON\nDASHIELL HAMMETT",
        "# 1\nSPADE AND ARCHER\nOpening text.",
        "THE THIRD MURDER",
        "# 2\nTHE THIRD MURDER\nNext chapter.",
    ]
    chapters, _ = detect_chapters(pages)
    report = chapter_heading_report(pages, chapters)

    candidates = {item["label"]: item for item in report["otherCandidates"]}
    assert candidates["THE MALTESE FALCON"]["classification"] == "front-matter"
    assert candidates["THE THIRD MURDER"]["classification"] == "chapter-title-carryover"
    assert chapter_heading_report_warnings(report) == []


def test_heading_report_ignores_project_gutenberg_distribution_boilerplate() -> None:
    pages = [
        "CHAPTER I\nThe story begins.",
        "CHAPTER II\nThe story continues.",
        "THE FULL PROJECT GUTENBERG™ LICENSE\nPlease read these terms.",
    ]
    chapters, _ = detect_chapters(pages)
    report = chapter_heading_report(pages, chapters)

    license_heading = next(item for item in report["otherCandidates"] if "GUTENBERG" in item["label"])
    assert license_heading["classification"] == "source-boilerplate"
    assert chapter_heading_report_warnings(report) == []


def test_gutenberg_wrapper_is_removed_before_analysis() -> None:
    text = """The Project Gutenberg eBook of A Story

*** START OF THE PROJECT GUTENBERG EBOOK A STORY ***

# A Story

The authored sentence remains.

*** END OF THE PROJECT GUTENBERG EBOOK A STORY ***

THE FULL PROJECT GUTENBERG™ LICENSE

License terms must not reach the model.
"""
    cleaned = server.strip_project_gutenberg_boilerplate(text)
    assert cleaned == "# A Story\n\nThe authored sentence remains."


def test_markdown_roman_chapter_numbers_with_titles_form_a_spine() -> None:
    chapters, method = detect_chapters([
        "# The Time Machine\nH. G. Wells",
        "## I. Introduction\nThe story begins.",
        "## II. The Machine\nThe story continues.",
        "## III. The Time Traveller Returns\nThe story advances.",
    ])

    assert [chapter["title"] for chapter in chapters] == ["Front matter", "I. Introduction", "II. The Machine", "III. The Time Traveller Returns"]
    assert method == "explicit opening-line chapter headings"


def test_leaving_book_workspace_invalidates_delayed_analysis_refresh() -> None:
    app = (Path(__file__).parents[1] / "web" / "app.js").read_text(encoding="utf-8")
    assert "function leaveBookWorkspace()" in app
    assert "state.workspaceRequestId += 1;" in app
    assert "if (location.hash === \"#books\") showBooksPage();" in app
    assert "The local worker owns this job." in app
    assert "if (!pipeline.nextAction && !queued && !pausedActions.size) return;" in app
    assert 'definition.resultKey ? {status: "pending"' not in app


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
    assert pipeline_stage_dependents("structure") == {"chapter-archive", "chunking", "summaries", "emotions", "tags", "smells", "dossiers", "question-tracker", "whole-book-summary", "whole-book-dossier", "cumulative-context", "llm-review", "whole-book-llm-review"}
    assert pipeline_stage_dependents("summaries") == {"question-tracker", "whole-book-summary", "cumulative-context", "llm-review", "whole-book-llm-review"}
    pipeline = {"stages": [
        {"id": "source", "status": "complete"},
        {"id": "extraction", "status": "complete"},
        {"id": "structure", "status": "complete"},
        {"id": "chapter-archive", "status": "complete", "startedAt": "then", "completedAt": "later", "durationSeconds": 2.5},
        {"id": "chunking", "status": "complete"},
        {"id": "summaries", "status": "complete"},
        {"id": "dossiers", "status": "complete"},
    ]}
    invalidate_pipeline_stage(pipeline, "structure")
    states = {stage["id"]: stage["status"] for stage in pipeline["stages"]}
    assert states == {"source": "complete", "extraction": "complete", "structure": "complete", "chapter-archive": "blocked", "chunking": "blocked", "summaries": "blocked", "dossiers": "blocked"}
    archive = next(stage for stage in pipeline["stages"] if stage["id"] == "chapter-archive")
    assert not {"startedAt", "completedAt", "durationSeconds"} & archive.keys()


def test_timing_charts_cover_preparation_rollups_and_optional_review_work() -> None:
    app = (Path(__file__).parents[1] / "web" / "app.js").read_text(encoding="utf-8")
    timing = app.split("function timingChartRows", 1)[1].split("function openTimingChart", 1)[0]
    server = (Path(__file__).parents[1] / "bookinator" / "server" / "__main__.py").read_text(encoding="utf-8")
    prepare = server.split("def prepare_manuscript_pipeline", 1)[1].split("def reset_summary_run", 1)[0]

    for stage_id in ("extraction", "structure", "chapter-archive", "chunking"):
        assert f'["{stage_id}",' in timing
    for label in ("Whole-book summary", "Whole-book dossier", "Questions & payoffs", "Context", "LLM Review"):
        assert label in timing
    assert prepare.count('"durationSeconds": round(time.monotonic() - stage_started, 3)') == 5


def test_timing_chart_can_toggle_between_pipeline_and_elapsed_order() -> None:
    app = (Path(__file__).parents[1] / "web" / "app.js").read_text(encoding="utf-8")
    chart = app.split("function openTimingChart", 1)[1].split("function workspaceTaskView", 1)[0]

    assert "data-timing-order" in chart
    assert "Reorder" in chart
    assert "longest elapsed time first" in chart
    assert "right.seconds - left.seconds" in chart
    assert "left.pipelineOrder - right.pipelineOrder" in chart


def test_timing_chart_uses_fallback_durations_and_standard_information_dialog() -> None:
    app = (Path(__file__).parents[1] / "web" / "app.js").read_text(encoding="utf-8")
    duration = app.split("function pipelineStageDuration", 1)[1].split("function pipelineStageStatus", 1)[0]
    chart = app.split("function openTimingChart", 1)[1].split("function workspaceTaskView", 1)[0]
    information = app.split("function showInformationDialog", 1)[1].split("function installDefaultDialogAction", 1)[0]

    assert 'stage?.durationSeconds !== null' in duration
    assert "duration > 0" in duration
    assert "showInformationDialog" in chart
    assert "confirmAction" not in chart.split("const dialogId", 1)[0]
    assert "mountStandardDialog" in information
    assert "information-dialog-message" in information


def test_start_over_preserves_source_annotations_and_identity_but_clears_analysis(tmp_path: Path) -> None:
    book = {"id": "book-12345678", "manuscriptId": "manuscript-1234", "title": "Shadow", "llmReviewEnabled": True}
    project = tmp_path / "manuscript-1234"
    project.mkdir()
    (project / "source.pdf").write_bytes(b"source")
    (project / "source.json").write_text(json.dumps({"filename": "Shadow.pdf", "storedAs": "source.pdf"}), encoding="utf-8")
    (project / "annotations.json").write_text(json.dumps([{"id": "human-note", "comment": "Keep me."}]), encoding="utf-8")
    (project / "reviewer-signoff.json").write_text(json.dumps({"status": "complete", "reviewerName": "Randal", "notes": "Keep these notes."}), encoding="utf-8")
    (project / "extracted-chapters.json").write_text("[]", encoding="utf-8")
    (project / "pipeline.json").write_text(json.dumps({"status": "complete", "chapters": [{"summary": "Old"}]}), encoding="utf-8")
    for dirname in ("chapters", "chunks", "llm-review"):
        derived = project / dirname
        derived.mkdir()
        (derived / "old.json").write_text("{}", encoding="utf-8")

    with patch.object(server, "BOOKS_ROOT", tmp_path), \
         patch.object(server, "TASK_PAUSES_PATH", tmp_path / "task-pauses.json"), \
         patch.object(server, "DEFERRED_REFRESHES_PATH", tmp_path / "deferred.json"), \
         patch.object(server, "QUEUE_ACTIONS_PATH", tmp_path / "actions.json"):
        reset = server.reset_book_pipeline(book)

    assert reset["status"] == "ready"
    assert reset["chapters"] == []
    assert (project / "source.pdf").read_bytes() == b"source"
    assert json.loads((project / "annotations.json").read_text(encoding="utf-8"))[0]["comment"] == "Keep me."
    signoff = json.loads((project / "reviewer-signoff.json").read_text(encoding="utf-8"))
    assert signoff["status"] == "open"
    assert signoff["reviewerName"] == "Randal"
    assert signoff["notes"] == "Keep these notes."
    assert not (project / "extracted-chapters.json").exists()
    assert not (project / "chapters").exists()
    assert not (project / "chunks").exists()
    assert not (project / "llm-review").exists()
    assert json.loads((project / "pipeline.json").read_text(encoding="utf-8"))["message"] == "Previous analysis was cleared. Source ingestion is first in line."


def test_restart_archives_provenance_and_returns_every_chapter_to_pending() -> None:
    pipeline = {
        "status": "complete",
        "stages": [{"id": "summaries", "status": "complete", "model": "old-reader", "completedAt": "2026-09-22T10:05:00+00:00"}, {"id": "dossiers", "status": "complete", "model": "dossier-reader"}],
        "wholeBookSummary": {"status": "complete", "summary": "Old whole-book summary", "completedAt": "2026-09-22T10:06:00+00:00"},
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
    assert pipeline["wholeBookSummary"] == {"status": "blocked", "dependsOn": ["summaries"], "detail": "Waiting for the reset chapter summaries."}
    assert pipeline["wholeBookSummaryRuns"][0]["summary"] == "Old whole-book summary"
    assert pipeline["stages"][0]["status"] == "pending"
    assert pipeline["stages"][1]["status"] == "complete"


def test_dossier_restart_archives_provenance_and_returns_every_chunk_to_pending() -> None:
    pipeline = {
        "status": "complete",
        "stages": [{"id": "summaries", "status": "complete", "model": "summary-reader"}, {"id": "dossiers", "status": "complete", "model": "old-reader"}],
        "wholeBookDossier": {"status": "complete", "synopsis": "Old whole-book dossier", "completedAt": "2026-09-22T10:02:00+00:00"},
        "chunks": [{"id": "chunk-1", "dossierStatus": "complete", "dossier": {"synopsis": "Old"}, "dossierModel": "old-reader", "dossierCompletedAt": "2026-09-22T10:01:00+00:00", "dossierDurationSeconds": 60}],
    }
    with patch("bookinator.server.__main__.write_pipeline"):
        reset_dossier_run({"id": "book"}, pipeline)
    assert pipeline["chunks"][0]["dossierStatus"] == "pending"
    assert "dossier" not in pipeline["chunks"][0]
    assert pipeline["chunks"][0]["dossierRuns"][0]["dossierModel"] == "old-reader"
    assert pipeline["wholeBookDossier"] == {"status": "blocked", "dependsOn": ["dossiers"], "detail": "Waiting for the reset chunk dossiers."}
    assert pipeline["wholeBookDossierRuns"][0]["synopsis"] == "Old whole-book dossier"
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


def test_stale_stage_registration_does_not_make_an_old_book_look_running() -> None:
    import bookinator.server.__main__ as server

    queue_thread = Mock()
    queue_thread.is_alive.return_value = True
    with patch.object(server, "QUEUE_THREAD", queue_thread), \
         patch.object(server, "QUEUE_CURRENT_TASK", {"bookId": "current-book", "action": "dossiers"}), \
         patch.dict(server.PIPELINE_THREADS, {"old-book": queue_thread}, clear=True):
        assert pipeline_worker_is_alive("old-book", {"workerPid": server.os.getpid()}) is False
        assert pipeline_worker_is_alive("current-book", {"workerPid": server.os.getpid()}) is True


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
        "timeline_observations": ["Later that day"], "evidence": [{"passage_id": "P0001", "quote": "Exact supporting words", "character_start": 0, "character_end": 22}],
    }
    with patch("bookinator.server.__main__.run_structured_model", return_value=(response, "raw")):
        result = server.analyze_chunk_dossier({"chapterLabel": "Chapter 1", "text": "Exact supporting words"}, "model")
    assert result["evidence"] == ["Exact supporting words"]
    assert result["evidenceAnchors"][0]["characterStart"] == 0
    assert result["facts"] == response["facts"]


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
    assert 'const statusLabel = label || (normalized === "pending" ? "Waiting" : signalLabel(normalized));' in app
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
    assert 'class="tag-rollup-filters"' in app
    assert "selectedTagRollupClusters" in app
    assert "updateWholeBookRollupVisibility" in app
    assert "not used in maps or manuscript markers" in app
    assert 'details[data-analysis-key][open]' in app
    assert ".tag-cluster-families" in styles
    assert "width: max-content" in styles


def test_smell_rollup_collapses_detector_aliases_into_editor_facing_families() -> None:
    normalizer = (Path(__file__).parents[1] / "web" / "smell-labels.js").read_text(encoding="utf-8")
    lexical = (Path(__file__).parents[1] / "web" / "lexical-labels.js").read_text(encoding="utf-8")
    for alias in ("clause count", "clause load", "clause load proxy", "clause complexity", "complexity", "nested structure", "many clauses"):
        assert f'["{alias}", "Complex sentence"]' in normalizer
    for alias in ("length", "sentence length", "long sentence", "very long sentence"):
        assert f'["{alias}", "Long sentence"]' in normalizer
    assert '["missing oxford comma", "Oxford comma"]' in normalizer
    assert 'replace(/[_\\-–—/]+/g, " ")' in lexical
    assert 'export function smellIssueLabels(item = {})' in normalizer
    assert 'split(/[,;|]+/)' in normalizer
    assert 'join(" · ")' in normalizer
    app = (Path(__file__).parents[1] / "web" / "app.js").read_text(encoding="utf-8")
    assert 'smellIssueLabels(item).forEach((label) =>' in app
    assert 'totalFindings: findings.length' in app


def test_smells_share_one_sort_control_and_open_the_annotation_reader() -> None:
    app = (Path(__file__).parents[1] / "web" / "app.js").read_text(encoding="utf-8")
    styles = (Path(__file__).parents[1] / "web" / "styles.css").read_text(encoding="utf-8")
    assert 'function smellSortControlMarkup()' in app
    assert 'data-smell-sort="position"' in app
    assert 'data-smell-sort="type"' in app
    assert 'This order applies to every chapter.' in app
    assert 'localStorage.setItem(smellSortKey, smellSortMode)' in app
    assert 'kind: smellFinding ? "review-candidate" : "source"' in app
    assert '>Annotate source</button>' in app
    assert '.smell-sort-toolbar' in styles


def test_app_modularization_is_an_urgent_documented_task() -> None:
    todo = (Path(__file__).parents[1] / "docs" / "TODO.md").read_text(encoding="utf-8")
    assert "### Urgent: split the browser application into owned modules" in todo
    assert "`web/app.js` has outgrown safe single-file maintenance" in todo


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


def test_chapter_reader_groups_analysis_and_text_controls_at_the_top() -> None:
    root = Path(__file__).parents[1]
    app = (root / "web" / "app.js").read_text(encoding="utf-8")
    page = (root / "web" / "index.html").read_text(encoding="utf-8")
    styles = (root / "web" / "styles.css").read_text(encoding="utf-8")
    assert 'id="chapter-analysis-controls"' in page
    assert 'class="chapter-control-cluster text"' in page
    assert "function chapterAnalysisControlsMarkup" in app
    assert 'data-analysis-comments' in app
    assert 'title="Emotions"' in app
    assert 'title="Tags"' in app
    assert 'title="Editor comments"' in app
    assert '<div class="source-overlay-key">' not in app
    assert ".chapter-reader-toolbar" in styles
    assert ".chapter-control-cluster.analysis { position: relative;" in styles
    assert ".chapter-reader-toolbar .source-analysis-setting { position: static; }" in styles
    assert ".chapter-reader-toolbar .source-analysis-setting .source-analysis-menu { right: 0; left: auto; }" in styles
    assert ".chapter-reader-toolbar .source-analysis-setting .source-analysis-menu { right: auto; left: 0; }" in styles
    assert ".human-annotation-range.annotation-filtered" in styles


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
        "sectionMarkers": ["SHADOW"],
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


def test_chapter_markdown_preserves_viewpoint_marker_that_matches_chapter_title() -> None:
    chapter = {
        "sequence": 1, "title": "CHAPTER 1", "chapterTitle": "SHADOW", "sectionMarkers": ["SHADOW"],
        "text": "CHAPTER 1\n\nSHADOW\n\nSHADOW\n\nOpening prose.",
    }
    assert chapter_markdown(chapter) == "# CHAPTER 1\n\n## SHADOW\n\n### SHADOW\n\nOpening prose.\n"


def test_pdf_block_geometry_joins_visual_lines_but_preserves_paragraphs() -> None:
    pages = [
        [(72, 10, 500, 20, "First visual line\n"), (72, 30, 500, 40, "continues here.\n"), (108, 50, 500, 60, "Indented paragraph\n")],
        [(72, 10, 500, 20, "continues on next page.\n"), (72, 30, 90, 40, "14\n"), (72, 50, 500, 60, " \nA blank-line paragraph.\n")],
    ]
    assert pdf_blocks_to_paragraph_text(pages) == "First visual line continues here.\n\nIndented paragraph continues on next page.\n\nA blank-line paragraph."


def test_pdf_block_geometry_preserves_viewpoint_heading_at_page_boundary() -> None:
    pages = [
        [(72, 680, 500, 700, "I led the way north. “Okay, kid. Let’s make tracks.”\n")],
        [(72, 40, 140, 58, "TIMMY\n"), (72, 72, 500, 96, "They walked along the Lakeshore trail.\n")],
    ]
    assert pdf_blocks_to_paragraph_text(pages) == (
        "I led the way north. “Okay, kid. Let’s make tracks.”\n\n"
        "TIMMY\n\n"
        "They walked along the Lakeshore trail."
    )


def test_pdf_block_geometry_preserves_heading_embedded_before_prose_in_one_block() -> None:
    pages = [[
        (72, 10, 500, 80, "TIMMY\n\nTimmy heard scratching at his window. He’s here!\n"),
        (72, 90, 500, 110, "He ran across the room.\n"),
    ]]
    assert pdf_blocks_to_paragraph_text(pages) == (
        "TIMMY\n\n"
        "Timmy heard scratching at his window. He’s here! He ran across the room."
    )


def test_shadow_heading_diagnostic_excludes_front_matter_and_finds_glued_markers() -> None:
    source_occurrences = [
        {"term": "SHADOW", "page": 1},
        {"term": "SHADOW", "page": 5},
        {"term": "TIMMY", "page": 10},
        {"term": "SHADOW", "page": 17},
    ]
    chapters = [
        {"sequence": 1, "title": "Front matter", "pageStart": 1, "pageEnd": 4, "markdown": "## SHADOW"},
        {"sequence": 2, "title": "CHAPTER 1", "pageStart": 5, "pageEnd": 9, "markdown": "# CHAPTER 1\n\n## SHADOW\n\nOpening."},
        {"sequence": 3, "title": "CHAPTER 2", "pageStart": 10, "pageEnd": 21, "markdown": "# CHAPTER 2\n\n### TIMMY\n\nWalk faster. SHADOW"},
    ]

    result = server.compile_shadow_heading_diagnostic(source_occurrences, chapters)

    assert not result["ok"]
    assert result["excludedSourceOccurrences"] == [{
        "term": "SHADOW", "page": 1,
        "reason": "Outside the mapped story chapters (usually cover or front matter).",
    }]
    assert result["comparisons"] == [
        {"term": "TIMMY", "sourceCount": 1, "headingCount": 1, "attachedCount": 0, "bareCount": 0, "invalidLevelCount": 0, "difference": 0, "ok": True},
        {"term": "SHADOW", "sourceCount": 2, "headingCount": 1, "attachedCount": 1, "bareCount": 0, "invalidLevelCount": 0, "difference": -1, "ok": False},
    ]
    assert result["attachedOccurrences"][0]["chapterSequence"] == 3
    assert result["attachedOccurrences"][0]["excerpt"] == "Walk faster. SHADOW"


def test_shadow_heading_diagnostic_accepts_chapter_title_and_viewpoint_levels() -> None:
    result = server.compile_shadow_heading_diagnostic(
        [{"term": "SHADOW", "page": 5}, {"term": "TIMMY", "page": 7}],
        [{
            "sequence": 1, "title": "CHAPTER 1", "pageStart": 5, "pageEnd": 9,
            "markdown": "# CHAPTER 1\n\n## Shadow\n\nProse.\n\n### TIMMY\n\nMore prose.",
        }],
    )

    assert result["ok"]
    assert [item["level"] for item in result["canonicalOccurrences"]] == [2, 3]


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


def test_retiring_queue_worker_cannot_erase_replacement_worker_identity() -> None:
    import bookinator.server.__main__ as server

    replacement = Mock()
    marker = {"bookId": "replacement-book", "action": "tags"}
    with patch.object(server, "load_queue", return_value=[]), \
         patch.object(server, "QUEUE_THREAD", replacement), \
         patch.object(server, "QUEUE_CURRENT_TASK", marker):
        server.run_library_queue()
        assert server.QUEUE_THREAD is replacement
        assert server.QUEUE_CURRENT_TASK == marker


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
    assert stage_rollup_action(pipeline, {"whole-summary"}) == ""
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


def test_whole_book_review_is_a_separate_rollup_after_chapter_reviews() -> None:
    pipeline = {
        "stages": [
            {"id": "llm-review", "status": "complete"},
            {"id": "whole-book-llm-review", "status": "pending"},
        ],
        "chapters": [{
            "sequence": 1, "title": "CHAPTER 1", "llmReviewStatus": "complete",
            "llmReview": {"editorialStrengths": ["Atmosphere"], "commercialRisks": ["Niche audience"]},
            "llmReviewModel": "reader", "llmReviewCompletedAt": "2026-09-25T12:00:00Z",
        }],
    }
    assert stage_rollup_action(pipeline) == "whole-llm-review"
    signature = stage_rollup_input_signature(pipeline, "review")
    pipeline["wholeBookLlmReview"] = {"status": "complete", "inputSignature": signature, "overallAssessment": "A cohesive work."}
    assert stage_rollup_action(pipeline) == ""


def test_whole_book_review_prompt_requires_synthesis_not_chapter_listing() -> None:
    import bookinator.server.__main__ as server
    captured = {}
    response = {
        "overall_assessment": "A cohesive atmospheric horror story.",
        "strengths": [{"title": "Atmosphere", "synthesis": "Dread accumulates consistently.", "significance": "Preserve the restraint."}],
        "risks": [{"title": "Distance", "synthesis": "The antiquarian voice limits intimacy.", "significance": "Some readers may disengage."}],
        "editorial_priorities": [{"title": "Protect the voice", "rationale": "It is the book's signature.", "scope": "Whole manuscript", "priority": "high"}],
        "likely_readers": [{"reader": "Cosmic horror readers", "fit": "Strong genre fit.", "caution": "Deliberately distant characters."}],
        "commercial_positioning": "A focused work for readers of literary cosmic horror.",
    }

    def structured(prompt, model, schema, cancel_event, run_key):
        captured.update({"prompt": prompt, "schema": schema, "runKey": run_key})
        return response, "{}"

    pipeline = {"chapters": [{
        "sequence": 1, "title": "CHAPTER 1", "llmReviewStatus": "complete",
        "llmReview": {"editorialSummary": "Atmospheric opening.", "editorialStrengths": ["Atmosphere"]},
    }]}
    with patch.object(server, "run_structured_model", side_effect=structured):
        result, input_characters = server.synthesize_whole_book_llm_review(pipeline, "qwen", threading.Event(), "book-1234")

    assert "This is synthesis, not concatenation" in captured["prompt"]
    assert "Do not walk chapter by chapter" in captured["prompt"]
    assert captured["runKey"] == "book-1234:whole-review"
    assert input_characters == len(captured["prompt"])
    assert result["overallAssessment"] == response["overall_assessment"]
    assert result["editorialPriorities"][0]["priority"] == "high"
    assert result["sourceChapterCount"] == 1


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
    assert artifact["schema"] == "bookinator-chapter-tags-v2"
    assert artifact["signals"][0]["id"] == "investigation"
    assert artifact["signals"][0]["evidence"][0]["quote"] == "She checked every locked room."
    assert artifact["signals"][0]["evidence"][0]["characterStart"] == 0


def test_lexical_organizer_and_smell_aliases_establish_canonical_identity() -> None:
    import bookinator.server.__main__ as server

    assert server.normalize_lexical_key(" Clause_load—Proxy! ") == "clause load proxy"
    assert server.canonical_smell_label("clause-load") == "Complex sentence"
    assert server.canonical_smell_label("Clause Load") == "Complex sentence"
    assert server.canonical_smell_label("missing-oxford_comma") == "Oxford comma"


def test_source_evidence_triangulates_quote_offsets_and_rejects_ambiguity() -> None:
    import bookinator.server.__main__ as server

    text = "She stepped into the carriage.\n\nThe bell rang. The bell rang."
    fuzzy = server.resolve_source_evidence(text, {
        "passage_id": "P0001", "quote": "She stepped into carriage.",
        "character_start": 0, "character_end": 26,
    })
    assert fuzzy
    assert fuzzy["quote"] == "She stepped into the carriage."
    assert fuzzy["matchMethod"] == "fuzzy-triangulated"
    assert server.resolve_source_evidence(text, {"quote": "The bell rang."}) is None
    second = server.resolve_source_evidence(text, {"quote": "The bell rang.", "character_start": 48, "character_end": 62})
    assert second and second["characterStart"] > text.index("The bell rang.")


def test_first_person_measurement_rejects_contradictory_third_limited_tag() -> None:
    import bookinator.server.__main__ as server

    text = "I remember the room. My father called me. I knew what I saw, and I kept my fear to myself."
    response = {
        "signals": [{"id": "third_limited", "family": "viewpoint", "score": .75, "confidence": .8, "explanation": "Close viewpoint.", "evidence": [{"quote": "I remember the room."}]}],
        "candidate_signals": [],
    }
    with patch.object(server, "run_structured_model", return_value=(response, "{}")):
        artifact = server.analyze_chapter_tags({"sequence": 2, "title": "I", "text": text}, "qwen")
    assert artifact["signals"] == []
    assert artifact["deterministic"]["narrativePerson"]["dominantPerson"] == "first_person"
    assert "first-person pronouns" in artifact["rejectedSignals"][0]["reason"]


def test_dialogue_first_person_does_not_override_third_person_narration() -> None:
    import bookinator.server.__main__ as server

    text = '“I told you I would come. I brought my coat,” she said. She crossed the room while he watched her.'
    metrics = server.narrative_person_metrics(text)
    assert metrics["firstPersonPronouns"] == 0
    assert metrics["dominantPerson"] != "first_person"


def test_chapter_tag_schema_requires_evidence_for_every_returned_signal() -> None:
    import bookinator.server.__main__ as server
    schema = server.chapter_tag_schema()
    signal = schema["properties"]["signals"]["items"]
    assert signal["properties"]["score"]["minimum"] == .25
    assert signal["properties"]["evidence"]["minItems"] == 1
    assert server.TAG_PROMPT_VERSION == "chapter-tags-v3"


def test_chapter_tags_keep_mystery_genre_distinct_from_withheld_information() -> None:
    import bookinator.server.__main__ as server
    response = {
        "signals": [
            {"id": "withheld_information", "family": "reader_dynamics", "score": .5, "confidence": .8, "explanation": "An answer is withheld.", "evidence": [{"quote": "No one knew who opened the door."}]},
            {"id": "mystery", "family": "genre_affinity", "score": .5, "confidence": .7, "explanation": "The chapter uses mystery conventions.", "evidence": [{"quote": "No one knew who opened the door."}]},
        ],
        "candidate_signals": [],
    }
    with patch.object(server, "run_structured_model", return_value=(response, "{}")):
        artifact = server.analyze_chapter_tags({"sequence": 2, "title": "CHAPTER 1", "text": "No one knew who opened the door."}, "qwen")
    assert [(signal["family"], signal["id"]) for signal in artifact["signals"]] == [("reader_dynamics", "withheld_information"), ("genre_affinity", "mystery")]


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


def test_llm_review_stages_are_per_book_and_enter_the_queue_only_after_opt_in() -> None:
    book = {"id": "book-1234", "manuscriptId": "manuscript", "priority": "normal", "llmReviewEnabled": False}
    pipeline = {
        "stages": [
            {"id": "extraction", "status": "complete"}, {"id": "chapter-archive", "status": "complete"},
            {"id": "summaries", "status": "complete"}, {"id": "dossiers", "status": "complete"},
            {"id": "emotions", "status": "complete"}, {"id": "tags", "status": "complete"},
            {"id": "smells", "status": "complete"},
        ],
        "chapters": [{"sequence": 1, "title": "CHAPTER 1", "status": "complete", "emotionStatus": "complete", "tagStatus": "complete", "smellStatus": "complete"}],
        "chunks": [{"chapterSequence": 1, "dossierStatus": "complete", "dossier": {"synopsis": "One"}}],
    }
    server.ensure_llm_review_stages(book, pipeline)
    assert not {"cumulative-context", "llm-review", "whole-book-llm-review"} & {stage["id"] for stage in pipeline["stages"]}

    book["llmReviewEnabled"] = True
    assert server.ensure_llm_review_stages(book, pipeline) is True
    assert {"cumulative-context", "llm-review", "whole-book-llm-review"} <= {stage["id"] for stage in pipeline["stages"]}
    with patch.object(server, "stage_rollup_action", return_value=""), patch.object(server, "question_tracker_input_signature", return_value=""):
        assert next_pipeline_action(book, pipeline) == "llm-review"
        pipeline["chapters"][0]["llmReviewStatus"] = "complete"
        assert next_pipeline_action(book, pipeline) == "cumulative-context"
        pipeline["chapters"][0]["contextStatus"] = "complete"
        assert next_pipeline_action(book, pipeline) == ""


def test_llm_review_uses_only_prior_context_and_current_canonical_chapter() -> None:
    book = {"title": "Dunwich", "author": "H. P. Lovecraft"}
    chapter = {
        "sequence": 2, "summary": "This must not enter the review packet.",
        "keyPoints": ["Neither should this."], "emotion": {"fear": 0.9},
        "tag": {"mood": ["ominous"]}, "smell": {"findings": ["noise"]},
    }
    pipeline = {
        "chapters": [
            {"sequence": 1, "title": "Front matter"},
            {"sequence": 2, "title": "1"},
        ],
        "chunks": [{"chapterSequence": 2, "dossier": {"facts": ["Nope"]}}],
    }
    source = {"title": "1", "text": "Only the canonical chapter belongs here."}
    prior_context = {"storySoFar": "What the reader knew through chapter 1."}

    packet = server.build_llm_review_packet(book, pipeline, chapter, source, prior_context)

    assert packet["chapter"]["text"] == source["text"]
    assert packet["priorContext"] == prior_context
    assert not {"summary", "dossiers", "signals"} & packet.keys()
    assert packet["schema"] == "bookinator-editorial-context-packet-v3"
    assert packet["chapter"]["number"] == 1
    assert packet["chapter"]["sourceSequence"] == 2


def test_cumulative_context_uses_authored_number_and_preserves_comprehensive_fields() -> None:
    captured = {}

    def structured(prompt, _model, _schema, _cancel_event, _run_key):
        captured["prompt"] = prompt
        return ({
            "story_so_far": "Dunwich has been introduced.",
            "key_events": ["The narrator surveys Dunwich."],
            "established_facts": ["Dunwich is isolated."],
            "entities_and_significance": ["Dunwich — the principal setting."],
            "character_states": [],
            "relationship_states": [],
            "knowledge_states": ["The reader knows the region's reputation."],
            "locations_and_timeline": ["Dunwich — present-day survey."],
            "open_threads": ["The sounds in the hills remain unexplained."],
            "resolved_threads": [],
            "reader_promises": ["The source of the sounds will matter."],
            "themes_and_motifs": ["Inherited decay."],
            "voice_and_form": ["Antiquarian omniscient narration."],
        }, "raw")

    evidence = [{"chapter": 1, "sourceSequence": 2, "summary": "A remote region is introduced."}]
    with patch.object(server, "run_structured_model", side_effect=structured):
        context = server.build_cumulative_context(
            previous={}, evidence=evidence, through_chapter=1, model="qwen2.5:32B",
            rebased=False, cancel_event=threading.Event(), run_key="book-1234",
        )

    assert "authored chapter 1" in captured["prompt"]
    assert '"sourceSequence": 2' in captured["prompt"]
    assert "Never silently drop an earlier open thread" in captured["prompt"]
    assert "explicit subject's name" in captured["prompt"]
    assert context["keyEvents"] == ["The narrator surveys Dunwich."]
    assert context["entitiesAndSignificance"] == ["Dunwich — the principal setting."]
    assert context["readerPromises"] == ["The source of the sounds will matter."]


def test_cumulative_context_disposes_every_prior_open_thread_without_silent_loss() -> None:
    def structured(_prompt, _model, _schema, _cancel_event, _run_key):
        return ({
            "story_so_far": "The visitor arrived.", "key_events": [], "established_facts": [],
            "entities_and_significance": [], "character_states": [], "relationship_states": [],
            "knowledge_states": [], "locations_and_timeline": [],
            "open_threads": ["The locked room remains unexplained."],
            "resolved_threads": ["The caller was revealed as Carmilla."],
            "thread_updates": [
                {"previous_thread": "Who called at midnight?", "status": "resolved", "current_wording": "The caller was revealed as Carmilla."},
            ],
            "reader_promises": [], "themes_and_motifs": [], "voice_and_form": [],
        }, "raw")

    previous = {"openThreads": ["Who called at midnight?", "Why is the portrait familiar?"]}
    with patch.object(server, "run_structured_model", side_effect=structured):
        context = server.build_cumulative_context(
            previous=previous, evidence=[], through_chapter=2, model="qwen",
            rebased=False, cancel_event=threading.Event(), run_key="book-1234",
        )

    assert "The caller was revealed as Carmilla." in context["resolvedThreads"]
    assert "Who called at midnight?" not in context["openThreads"]
    assert "Why is the portrait familiar?" in context["openThreads"]
    assert context["threadUpdates"][0]["status"] == "resolved"


def test_authored_chapter_labels_do_not_count_prologue_as_chapter_one() -> None:
    assert server.authored_chapter_label({"title": "PROLOGUE", "analysisRole": "prologue"}, 1) == "Prologue"
    assert server.authored_chapter_label({"title": "I. An Early Fright", "analysisRole": "chapter"}, 2) == "Chapter I"
    assert server.authored_chapter_label({"title": "Chapter 7: Search", "analysisRole": "chapter"}, 8) == "Chapter 7"


def test_optional_review_pipeline_alternates_review_then_context_by_chapter() -> None:
    book = {"id": "book-1234", "manuscriptId": "manuscript", "priority": "normal", "llmReviewEnabled": True}
    pipeline = {
        "stages": [
            {"id": "summaries", "status": "complete"}, {"id": "dossiers", "status": "complete"},
            {"id": "cumulative-context", "status": "pending"}, {"id": "llm-review", "status": "pending"},
        ],
        "chapters": [
            {"sequence": 1, "title": "CHAPTER 1", "status": "complete"},
            {"sequence": 2, "title": "CHAPTER 2", "status": "complete"},
        ],
        "chunks": [
            {"chapterSequence": 1, "dossierStatus": "complete"},
            {"chapterSequence": 2, "dossierStatus": "complete"},
        ],
    }
    calls = []

    def review(_book_id, chapter_sequence=None):
        calls.append(("review", chapter_sequence))
        pipeline["chapters"][chapter_sequence - 1]["llmReviewStatus"] = "complete"

    def context(_book_id, chapter_sequence=None):
        calls.append(("context", chapter_sequence))
        pipeline["chapters"][chapter_sequence - 1]["contextStatus"] = "complete"

    server.QUEUE_ACTIONS.clear()
    try:
        with patch.object(server, "find_book", return_value=book), \
             patch.object(server, "load_pipeline", return_value=pipeline), \
             patch.object(server, "run_ready_stage_rollups"), \
             patch.object(server, "run_llm_review_pipeline", side_effect=review), \
             patch.object(server, "run_cumulative_context_pipeline", side_effect=context):
            server.run_book_chapter_pipeline(
                book["id"], summaries=False, dossiers=False, emotions=False,
                tags=False, smells=False, context=True, llm_review=True,
            )
    finally:
        server.QUEUE_ACTIONS.clear()

    assert calls == [("review", 1), ("context", 1), ("review", 2), ("context", 2)]


def test_context_and_llm_review_reuse_standard_analysis_rows() -> None:
    source = (Path(__file__).parents[1] / "web" / "app.js").read_text(encoding="utf-8")
    renderer = source.split("function optionalChapterRows", 1)[1].split("function llmReviewReportMarkup", 1)[0]

    assert "return analysisDisclosure({" in renderer
    assert "optional-review-row" not in source
    assert 'content: `<div class="analysis-list">${optionalChapterRows(pipeline, "context", openRows, book)}</div>`' in source
    assert '${wholeBookAnalysisRow(pipeline, "llm-review", book)}${optionalChapterRows(pipeline, "review", openRows, book, annotations)}' in source
    assert "Review waits for this chapter’s cumulative context." not in source
    assert 'refreshKind: context ? "context" : "llm-review"' in renderer
    assert "refreshId: sequence" in renderer
    assert "contextCheckpointMarkup(checkpoint, summary)" in renderer
    assert "retained details" in renderer
    assert "canonical Chapter ${authoredNumber}" in renderer
    assert '`${consideredCandidates} ${consideredCandidates === 1 ? "candidate" : "candidates"} reviewed · ${survivingProposals} significant`' in renderer
    assert "No significant concerns were found." in renderer
    assert "rubric dimensions" not in renderer
    assert "llmReviewCandidateMarkup(review, sequence, {annotations})" in renderer
    assert "llmReviewProposalMarkup(proposal, sequence, annotations)" in renderer


def test_completed_llm_review_can_be_refreshed_through_standard_analysis_contract(tmp_path: Path) -> None:
    book = {"id": "book-12345678", "manuscriptId": "manuscript-12345678", "llmReviewEnabled": True}
    review = {"editorialVerdict": "no_material_concerns", "editorialProposals": []}
    pipeline = {
        "status": "complete", "phase": "complete",
        "stages": [{"id": "cumulative-context", "status": "complete"}, {"id": "llm-review", "status": "complete", "completedAt": "later"}],
        "chapters": [{
            "sequence": 1, "title": "CHAPTER 1", "llmReviewStatus": "complete", "llmReview": review,
            "llmReviewModel": "qwen", "llmReviewStartedAt": "start", "llmReviewCompletedAt": "finish",
            "llmReviewDurationSeconds": 42, "llmReviewInputSignature": "signature",
        }],
        "chunks": [],
    }
    artifact_path = tmp_path / book["manuscriptId"] / "llm-review" / "results" / "0001.json"
    artifact_path.parent.mkdir(parents=True)
    artifact_path.write_text(json.dumps({
        "schema": server.LLM_REVIEW_PROMPT_VERSION, "status": "complete", "model": "qwen",
        "startedAt": "start", "completedAt": "finish", "durationSeconds": 42,
        "inputSignature": "signature", "result": review,
    }), encoding="utf-8")

    with patch.object(server, "BOOKS_ROOT", tmp_path), patch.object(server, "write_pipeline") as write_pipeline:
        action, was_running = server.refresh_analysis_result(book, pipeline, "llm-review", 1)

    assert action == "llm-review"
    assert was_running is False
    assert pipeline["chapters"][0]["llmReviewStatus"] == "pending"
    assert "llmReview" not in pipeline["chapters"][0]
    assert pipeline["chapters"][0]["llmReviewRuns"][0]["llmReviewDurationSeconds"] == 42
    assert pipeline["stages"][1]["status"] == "pending"
    saved = json.loads(artifact_path.read_text(encoding="utf-8"))
    assert saved["status"] == "pending"
    assert saved["previousRuns"][0]["durationSeconds"] == 42
    write_pipeline.assert_called_once_with(book, pipeline)


def test_old_server_refresh_rejection_explains_that_a_restart_is_needed() -> None:
    source = (Path(__file__).parents[1] / "web" / "app.js").read_text(encoding="utf-8")

    assert 'staleOptionalReviewServer = ["context", "llm-review"].includes(kind)' in source
    assert "This running server predates review refresh" in source
    assert "Let the active model response finish, then restart Bookinator." in source


def test_refreshing_context_invalidates_only_reviews_that_consumed_it(tmp_path: Path) -> None:
    book = {"id": "book-12345678", "manuscriptId": "manuscript-12345678", "llmReviewEnabled": True}
    chapters = [
        {
            "sequence": sequence, "title": f"CHAPTER {sequence}",
            "contextStatus": "complete", "contextSummary": f"Through {sequence}", "contextModel": "qwen",
            "llmReviewStatus": "complete", "llmReview": {"chapter": sequence}, "llmReviewModel": "qwen",
        }
        for sequence in (1, 2, 3)
    ]
    pipeline = {
        "status": "complete", "phase": "complete", "chapters": chapters, "chunks": [],
        "stages": [{"id": "cumulative-context", "status": "complete"}, {"id": "llm-review", "status": "complete"}],
    }
    with patch.object(server, "BOOKS_ROOT", tmp_path), patch.object(server, "write_pipeline"):
        action, _ = server.refresh_analysis_result(book, pipeline, "context", 2)

    assert action == "cumulative-context"
    assert chapters[0]["contextStatus"] == "complete"
    assert chapters[1]["contextStatus"] == chapters[2]["contextStatus"] == "pending"
    assert chapters[0]["llmReviewStatus"] == chapters[1]["llmReviewStatus"] == "complete"
    assert chapters[2]["llmReviewStatus"] == "pending"
    assert pipeline["stages"][0]["status"] == "pending"
    assert pipeline["stages"][1]["status"] == "pending"


def test_whole_book_rollups_reuse_standard_analysis_status_control() -> None:
    source = (Path(__file__).parents[1] / "web" / "app.js").read_text(encoding="utf-8")
    styles = (Path(__file__).parents[1] / "web" / "styles.css").read_text(encoding="utf-8")
    renderer = source.split("function wholeBookAnalysisRow", 1)[1].split("function chapterMapRow", 1)[0]

    assert "analysisStatusControl({" in renderer
    assert "whole-book-status" not in source
    assert ".whole-book-status" not in styles
    assert ".chapter-summary.running .chapter-status" in styles
    assert ".chapter-summary.ready .chapter-status" in styles


def test_completed_pass_keeps_same_book_active_when_it_unlocks_followup_work() -> None:
    processed = {"book-1234", "book-5678"}
    with patch.object(server, "find_book", return_value={"id": "book-1234"}), \
         patch.object(server, "load_pipeline", return_value={"stages": []}), \
         patch.object(server, "next_pipeline_action", return_value="cumulative-context"):
        assert server.retain_book_for_automatic_followup(processed, "book-1234") == "cumulative-context"
    assert processed == {"book-5678"}

    with patch.object(server, "find_book", return_value={"id": "book-1234"}), \
         patch.object(server, "load_pipeline", return_value={"stages": []}), \
         patch.object(server, "next_pipeline_action", return_value=""):
        assert server.retain_book_for_automatic_followup(processed, "book-5678") == ""
    assert processed == {"book-5678"}


def test_llm_review_rejects_proposed_annotations_without_an_exact_source_quote() -> None:
    dimensions = {
        key: {"score": 4, "confidence": "medium", "rationale": "Supported.", "evidence": ["Evidence"]}
        for key in server.LLM_REVIEW_DIMENSIONS
    }
    editorial_response = {
        "editorial_verdict": "material_concerns_found",
        "editorial_summary": "One passage deserves attention.",
        "verdict_basis": "One exact passage crosses the interruption threshold.",
        "strengths": ["The opening establishes place efficiently."],
        "editorial_proposals": [
            {"quote": "Exact sentence.", "category": "praise", "priority": "normal", "comment": "Keep this.", "reader_effect": "It lands.", "prior_context": "Earlier.", "intentionality_check": "The precision appears deliberate.", "revision_goal": "Preserve it.", "confidence": 0.91},
            {"quote": "Invented sentence.", "category": "clarity", "priority": "high", "comment": "Fix this.", "reader_effect": "Confusing.", "prior_context": "", "intentionality_check": "No explanation.", "revision_goal": "Clarify it.", "confidence": 0.95},
        ],
    }
    assessment_response = {
        "dimensions": dimensions,
        "likely_readers": ["Gothic readers"], "commercial_strengths": ["Voice"], "commercial_risks": ["Slow opening"],
    }
    adjudication_response = {"decisions": [{"candidate_number": 1, "verdict": "significant", "reason": "Specific and supported."}]}
    packet = {"chapter": {"sequence": 1, "text": "Exact sentence."}, "priorContext": {"storySoFar": "Earlier."}}
    with patch.object(server, "run_structured_model", side_effect=[(editorial_response, "editorial raw"), (adjudication_response, "adjudication raw"), (assessment_response, "assessment raw")]) as run_model:
        result = server.review_context_packet(packet, "reader", threading.Event(), "book-1234")
    assert run_model.call_count == 3
    assert [proposal["quote"] for proposal in result["editorialProposals"]] == ["Exact sentence."]
    assert result["editorialProposals"][0]["characterStart"] == 0
    assert result["editorialProposals"][0]["confidence"] == 0.91
    assert result["editorialProposals"][0]["passageId"] == "P0001"
    assert result["editorialProposals"][0]["anchorMatchMethod"] == "exact"
    adjudication_prompt = run_model.call_args_list[1].args[0]
    assert "local_continuation" in adjudication_prompt
    assert "already_answered_nearby=true" in adjudication_prompt
    assert result["dimensions"]["saleability"]["score"] == 4
    assert result["editorialVerdict"] == "material_concerns_found"
    assert result["editorialSummary"] == "1 material editorial concern found."
    assert result["editorialStrengths"] == ["The opening establishes place efficiently."]


def test_llm_review_calibration_preserves_significant_soft_and_discarded_outcomes() -> None:
    text = "The door opened without warning. The clock contradicted her memory. The wallpaper was blue."
    proposals = []
    for quote, comment in (
        ("The door opened without warning.", "The transition may be too abrupt."),
        ("The clock contradicted her memory.", "The chronology may confuse readers."),
        ("The wallpaper was blue.", "Blue may be too subjective."),
    ):
        start = text.index(quote)
        proposals.append({
            "passage_id": "P0001", "quote": quote, "character_start": start, "character_end": start + len(quote),
            "category": "clarity", "priority": "normal", "comment": comment,
            "reader_effect": "The reader may pause.", "prior_context": "", "intentionality_check": "Intent is uncertain.",
            "revision_goal": "Check the transition.", "confidence": .9,
        })
    editorial = {
        "editorial_verdict": "material_concerns_found", "editorial_summary": "Candidates found.",
        "verdict_basis": "Three passages merit calibration.", "strengths": [], "editorial_proposals": proposals,
    }
    decisions = {"decisions": [
        {"candidate_number": 1, "verdict": "significant", "reason": "Concrete interruption."},
        {"candidate_number": 2, "verdict": "soft", "reason": "Plausible but uncertain."},
        {"candidate_number": 3, "verdict": "reject", "reason": "No editorial consequence."},
    ]}
    dimensions = {key: {"applicable": True, "score": 3, "confidence": "medium", "rationale": "Supported.", "evidence": []} for key in server.LLM_REVIEW_DIMENSIONS}
    assessment = {"dimensions": dimensions, "likely_readers": [], "commercial_strengths": [], "commercial_risks": []}
    packet = {"chapter": {"sequence": 1, "text": text}, "priorContext": {}}

    with patch.object(server, "run_structured_model", side_effect=[(editorial, ""), (decisions, ""), (assessment, "")]):
        result = server.review_context_packet(packet, "reader", threading.Event(), "book-1234")

    assert len(result["editorialProposals"]) == 1
    assert result["rejectedCandidates"][0]["status"] == "soft_lead"
    assert result["discardedCandidates"][0]["status"] == "rejected_by_model"


def test_llm_review_normalizes_an_empty_proposal_set_to_a_direct_clear_verdict() -> None:
    dimensions = {
        key: {"applicable": True, "score": 4, "confidence": "medium", "rationale": "Supported.", "evidence": ["Evidence"]}
        for key in server.LLM_REVIEW_DIMENSIONS
    }
    editorial_response = {
        "editorial_verdict": "material_concerns_found",
        "editorial_summary": "The chapter works, but a few areas could benefit from refinement.",
        "verdict_basis": "The descriptive density is deliberate and no passage creates material confusion.",
        "strengths": ["The setting creates sustained unease."],
        "editorial_proposals": [],
    }
    assessment_response = {
        "dimensions": dimensions,
        "likely_readers": ["Gothic readers"], "commercial_strengths": ["Atmosphere"], "commercial_risks": [],
    }
    packet = {"chapter": {"sequence": 1, "text": "The hills crowded close."}, "priorContext": {}}
    with patch.object(server, "run_structured_model", side_effect=[(editorial_response, "editorial raw"), (assessment_response, "assessment raw")]):
        result = server.review_context_packet(packet, "reader", threading.Event(), "book-1234")

    assert result["editorialVerdict"] == "no_material_concerns"
    assert result["editorialSummary"] == "No material editorial concerns found."
    assert result["chapterAssessment"] == "No material editorial concerns found."
    assert result["editorialRationale"] == "The descriptive density is deliberate and no passage creates material confusion."
    assert result["editorialStrengths"] == ["The setting creates sustained unease."]


def test_llm_review_ui_renders_formal_verdict_and_strengths() -> None:
    source = (Path(__file__).parents[1] / "web" / "app.js").read_text(encoding="utf-8")
    styles = (Path(__file__).parents[1] / "web" / "styles.css").read_text(encoding="utf-8")

    assert "review.editorialSummary || review.chapterAssessment" in source
    assert "Strengths worth preserving" in source
    assert 'class="llm-review-verdict ${hasConcerns ? "concerns" : "clear"}"' in source
    assert ".llm-review-verdict.clear" in styles
    assert ".llm-review-verdict.concerns" in styles
    assert "Whole-book assessment profile" in source
    assert "Whole-book editorial synthesis" in source
    assert "wholeBookLlmReviewMarkup" in source
    assert 'data-llm-score-sort' in source
    assert '>A–Z</option>' in source
    assert "Soft leads from the first reader" in source
    assert "Review in manuscript" in source
    assert 'kind: "review-candidate"' in source
    assert "Annotate highlighted passage" in source
    assert "No significant concerns were found." in source
    assert ".llm-review-candidates" in styles
    assert "--type-caption: 11px" in styles
    assert "--type-small: 12px" in styles


def test_tag_ui_explains_fixed_vocabulary_and_disambiguates_tension() -> None:
    source = (Path(__file__).parents[1] / "web" / "app.js").read_text(encoding="utf-8")

    assert 'tension: "Narrative tension"' in source
    assert 'tense: "Tense atmosphere"' in source
    assert 'third_limited: "Third-person limited"' in source
    assert 'chapter_end_propulsion: "Chapter-end propulsion"' in source
    assert "function signalDescription" in source
    assert "function explainedSignalLabel" in source
    assert 'class="tag-definition"' in source


def test_llm_review_preserves_not_applicable_dimensions() -> None:
    dimensions = {
        key: {"applicable": True, "score": 4, "confidence": "medium", "rationale": "Supported.", "evidence": ["Evidence"]}
        for key in server.LLM_REVIEW_DIMENSIONS
    }
    dimensions["character_likability"] = {
        "applicable": False, "score": 0, "confidence": "high",
        "rationale": "This setting chapter has no focal character to assess.", "evidence": [],
    }
    editorial = {
        "editorial_verdict": "no_material_concerns",
        "editorial_summary": "No material editorial concerns found.",
        "verdict_basis": "The chapter succeeds as an atmospheric orientation.",
        "strengths": [], "editorial_proposals": [],
    }
    assessment = {"dimensions": dimensions, "likely_readers": [], "commercial_strengths": [], "commercial_risks": []}
    packet = {"chapter": {"number": 1, "text": "The hills crowded close."}, "priorContext": {}}
    with patch.object(server, "run_structured_model", side_effect=[(editorial, "editorial raw"), (assessment, "assessment raw")]):
        result = server.review_context_packet(packet, "reader", threading.Event(), "book-1234")

    assert result["dimensions"]["character_likability"] == {
        "applicable": False, "score": 0, "confidence": "high",
        "rationale": "This setting chapter has no focal character to assess.", "evidence": [],
    }


def test_llm_review_retries_malformed_json_and_preserves_recovered_output() -> None:
    malformed = json.JSONDecodeError("Unterminated string", '{"editorial_summary":"cut', 22)
    malformed.raw_response = '{"editorial_summary":"cut'
    recovered = {"editorial_verdict": "no_material_concerns"}
    trace: dict[str, object] = {}

    with patch.object(server, "run_structured_model", side_effect=[malformed, (recovered, json.dumps(recovered))]) as run_model:
        result = server.run_llm_review_structured_step(
            "editorial review", "prompt", "qwen", {"type": "object"},
            threading.Event(), "book-1234", trace,
        )

    assert result == recovered
    assert run_model.call_count == 2
    assert trace["recoveredFailures"][0]["rawResponse"] == '{"editorial_summary":"cut'
    assert trace["recoveredFailures"][0]["column"] == 23


def test_llm_review_reports_human_diagnosis_after_two_malformed_responses() -> None:
    first = json.JSONDecodeError("Unterminated string", '{"one":"cut', 8)
    first.raw_response = '{"one":"cut'
    second = json.JSONDecodeError("Expecting value", '{"two":', 7)
    second.raw_response = '{"two":'
    trace: dict[str, object] = {}

    with patch.object(server, "run_structured_model", side_effect=[first, second]), pytest.raises(server.LLMReviewAnalysisExhausted) as raised:
        server.run_llm_review_structured_step(
            "chapter assessment", "prompt", "qwen", {"type": "object"},
            threading.Event(), "book-1234", trace,
        )

    assert "malformed JSON twice during chapter assessment" in str(raised.value)
    assert len(raised.value.failures) == 2
    assert [item["rawResponse"] for item in trace["failedAttempts"]] == ['{"one":"cut', '{"two":']


def test_optional_analysis_artifacts_expose_exact_saved_input_and_output(tmp_path: Path) -> None:
    book = {"id": "book-12345678", "manuscriptId": "manuscript-12345678"}
    review_root = tmp_path / book["manuscriptId"] / "llm-review"
    (review_root / "packets").mkdir(parents=True)
    (review_root / "results").mkdir()
    (review_root / "contexts").mkdir()
    packet = {"schema": "packet-v3", "chapter": {"number": 1, "text": "Exact chapter text."}, "priorContext": {}}
    model_output = {"editorial": {"editorial_verdict": "no_material_concerns"}, "assessment": {"dimensions": {}}}
    normalized = {"editorialVerdict": "no_material_concerns", "editorialProposals": []}
    context_input = {"previousContext": {}, "chapterEvidence": [{"chapter": 1, "summary": "Evidence"}]}
    context_output = {"storySoFar": "Evidence retained.", "establishedFacts": ["One fact."]}
    (review_root / "packets" / "0002.json").write_text(json.dumps(packet), encoding="utf-8")
    (review_root / "results" / "0002.json").write_text(json.dumps({
        "schema": server.LLM_REVIEW_PROMPT_VERSION, "status": "complete", "model": "qwen",
        "modelOutput": model_output, "result": normalized,
    }), encoding="utf-8")
    (review_root / "packets" / "0003.json").write_text(json.dumps(packet), encoding="utf-8")
    (review_root / "results" / "0003.json").write_text(json.dumps({
        "schema": server.LLM_REVIEW_PROMPT_VERSION, "status": "failed", "model": "qwen",
        "modelOutput": {"failedAttempts": [{"rawResponse": "truncated"}]},
        "error": "LLM Review returned malformed JSON twice during editorial review.",
    }), encoding="utf-8")
    (review_root / "contexts" / "0002.json").write_text(json.dumps({
        "schema": server.CUMULATIVE_CONTEXT_PROMPT_VERSION, "status": "complete", "model": "qwen",
        "input": context_input, "context": context_output,
    }), encoding="utf-8")

    with patch.object(server, "BOOKS_ROOT", tmp_path):
        review = server.optional_analysis_artifact(book, "llm-review", 2)
        failed_review = server.optional_analysis_artifact(book, "llm-review", 3)
        context = server.optional_analysis_artifact(book, "context", 2)

    assert review["input"] == packet
    assert review["output"] == {"modelResponses": model_output, "normalizedResult": normalized}
    assert failed_review["status"] == "failed"
    assert failed_review["error"] == "LLM Review returned malformed JSON twice during editorial review."
    assert failed_review["output"]["modelResponses"]["failedAttempts"][0]["rawResponse"] == "truncated"
    assert context["input"] == context_input
    assert context["output"] == context_output


def test_run_inspector_is_shared_by_standard_status_dialogs() -> None:
    source = (Path(__file__).parents[1] / "web" / "app.js").read_text(encoding="utf-8")
    index = (Path(__file__).parents[1] / "web" / "index.html").read_text(encoding="utf-8")
    styles = (Path(__file__).parents[1] / "web" / "styles.css").read_text(encoding="utf-8")

    assert "configureRunInspector" in source
    assert "showRunInspectorView" in source
    assert "prettyJsonMarkup" in source
    assert "function pipelineStageInspectorTarget" in source
    assert 'configureRunInspector({kind: stage.dataset.inspectorKind || "stage"' in source
    assert 'summaries: {kind: "summary"' in source
    assert 'tags: {kind: "tag"' in source
    assert 'const target = {kind: "dossier"' in source
    assert 'trigger: "stage"' in source
    assert 'trigger === "stage" ? "data-show-stage-details"' in source
    assert "pipeline-stage-badge" not in source
    assert "pipeline-stage-badge" not in styles
    assert ".pipeline-stage.running .chapter-status" in styles
    assert '"cumulative-context": "cumulative-context"' in source
    assert '"llm-review": "llm-review"' in source
    assert "Input JSON" in index
    assert "Output JSON" in index
    assert "run-inspector-expand" in index
    assert ".run-inspector-tabs" in styles
    assert ".reading-details-dialog.is-expanded" in styles
    assert ".artifact-inspector pre" in styles


def test_generic_run_artifact_reconstructs_standard_chapter_inputs(tmp_path: Path) -> None:
    book = {"id": "book-12345678", "manuscriptId": "manuscript-12345678"}
    project = tmp_path / book["manuscriptId"]
    project.mkdir()
    source = {"sequence": 1, "title": "CHAPTER 1", "text": "The old road climbed.", "pageStart": 1, "pageEnd": 2}
    (project / "extracted-chapters.json").write_text(json.dumps([source]), encoding="utf-8")
    pipeline = {"chapters": [{**source, "status": "complete", "summary": "A road climbs.", "keyPoints": ["The road is old."], "model": "qwen"}], "chunks": [], "stages": []}

    with patch.object(server, "BOOKS_ROOT", tmp_path), patch.object(server, "load_pipeline", return_value=pipeline):
        artifact = server.analysis_run_artifact(book, "summary", "1")

    assert artifact["inputFidelity"] == "reconstructed"
    assert artifact["input"]["text"] == "The old road climbed."
    assert artifact["output"]["summary"] == "A road climbs."
    assert artifact["output"]["keyPoints"] == ["The road is old."]


def test_chapter_map_run_artifact_exposes_parser_inputs_and_detected_structure() -> None:
    book = {"id": "book-12345678", "manuscriptId": "manuscript-12345678", "sourceFormat": "EPUB"}
    chapter = {"sequence": 1, "title": "CHAPTER I", "pageStart": 1, "pageEnd": 3}
    pipeline = {
        "manuscriptMetrics": {"pageCount": 12},
        "acceptedChapterLabelVariants": ["PROLOGUE"],
        "demotedChapterBoundaryPages": [7],
        "chapterMapWarnings": [],
        "chapterHeadingReport": {"topLevel": ["CHAPTER I"]},
        "chapters": [chapter], "chunks": [],
        "stages": [{"id": "structure", "status": "complete", "durationSeconds": 0.12}],
    }
    with patch.object(server, "load_pipeline", return_value=pipeline), \
         patch.object(server, "manuscript_metadata", return_value={"sourceFormat": "EPUB"}), \
         patch.object(server, "source_has_fixed_pagination", return_value=False):
        artifact = server.analysis_run_artifact(book, "stage", "structure")

    assert artifact["input"]["sourceFormat"] == "EPUB"
    assert artifact["input"]["sourcePagination"] == "reflowable"
    assert artifact["input"]["sourceSpans"] == 12
    assert artifact["input"]["acceptedHeadingVariants"] == ["PROLOGUE"]
    assert artifact["output"]["chapters"] == [chapter]
    assert artifact["output"]["stage"]["durationSeconds"] == 0.12


def test_accepting_llm_review_proposal_creates_attributed_human_note(tmp_path: Path) -> None:
    proposal_id = "a" * 32
    book = {"id": "book-12345678", "manuscriptId": "manuscript-12345678", "title": "Dunwich", "llmReviewEnabled": True}
    project = tmp_path / book["manuscriptId"]
    project.mkdir()
    source = "The old road climbed past the ruined wall."
    (project / "extracted-chapters.json").write_text(json.dumps([{"sequence": 1, "title": "CHAPTER 1", "text": source}]), encoding="utf-8")
    review = {"editorialProposals": [{
        "id": proposal_id, "quote": "ruined wall", "characterStart": 30, "characterEnd": 41,
        "category": "continuity", "priority": "normal", "comment": "Check when this ruin was established.", "status": "proposed",
    }]}
    pipeline = {
        "bookId": book["id"], "status": "complete", "stages": [
            {"id": "summaries", "status": "complete"}, {"id": "dossiers", "status": "complete"},
            {"id": "cumulative-context", "status": "complete"}, {"id": "llm-review", "status": "complete"},
        ],
        "chapters": [{"sequence": 1, "title": "CHAPTER 1", "llmReviewStatus": "complete", "llmReviewModel": "qwen", "llmReview": review}],
        "chunks": [],
    }
    (project / "pipeline.json").write_text(json.dumps(pipeline), encoding="utf-8")
    result_path = project / "llm-review" / "results" / "0001.json"
    result_path.parent.mkdir(parents=True)
    result_path.write_text(json.dumps({"status": "complete", "result": review}), encoding="utf-8")

    def persist_pipeline(_book, payload):
        (project / "pipeline.json").write_text(json.dumps(payload), encoding="utf-8")

    with patch.object(server, "BOOKS_ROOT", tmp_path), patch.object(server, "load_pipeline", return_value=pipeline), patch.object(server, "write_pipeline", side_effect=persist_pipeline):
        result = server.decide_llm_review_proposal(book, proposal_id, "accept")
        saved_pipeline = json.loads((project / "pipeline.json").read_text(encoding="utf-8"))
        saved_artifact = json.loads(result_path.read_text(encoding="utf-8"))
        annotations = server.load_annotations(book)

    assert result["proposal"]["status"] == "accepted"
    assert saved_pipeline["chapters"][0]["llmReview"]["editorialProposals"][0]["status"] == "accepted"
    assert saved_artifact["result"]["editorialProposals"][0]["status"] == "accepted"
    assert annotations[0]["quote"] == "ruined wall"
    assert annotations[0]["origin"] == {
        "kind": "llm-review-proposal", "proposalId": proposal_id, "model": "qwen",
        "promptVersion": server.LLM_REVIEW_PROMPT_VERSION, "acceptedAt": annotations[0]["createdAt"],
    }


def test_promoting_counter_review_soft_lead_creates_source_anchored_annotation(tmp_path: Path) -> None:
    book = {"id": "book-12345678", "manuscriptId": "manuscript-12345678", "title": "Dunwich"}
    project = tmp_path / book["manuscriptId"]
    project.mkdir()
    source = "The manuscript appeared\nabruptly, and the hills answered."
    (project / "extracted-chapters.json").write_text(json.dumps([{"sequence": 8, "title": "CHAPTER 8", "text": source}]), encoding="utf-8")
    review = {"editorialProposals": [], "rejectedCandidates": [{
        "quote": "The manuscript appeared abruptly",
        "comment": "The transition may disorient the reader.",
        "reason": "The counter-review considered the disruption intentional.",
        "category": "clarity",
        "priority": "high",
        "characterStart": 0,
        "characterEnd": len("The manuscript appeared abruptly"),
        "confidence": .85,
        "status": "rejected_by_model",
    }]}
    pipeline = {"chapters": [{"sequence": 8, "title": "CHAPTER 8", "llmReview": review, "llmReviewModel": "qwen"}], "stages": [], "chunks": []}
    result_path = project / "llm-review" / "results" / "0008.json"
    result_path.parent.mkdir(parents=True)
    result_path.write_text(json.dumps({"status": "complete", "result": review}), encoding="utf-8")

    with patch.object(server, "BOOKS_ROOT", tmp_path), patch.object(server, "load_pipeline", return_value=pipeline), patch.object(server, "write_pipeline"):
        result = server.promote_llm_review_candidate(book, 8, 0)
        annotations = server.load_annotations(book)

    assert result["candidate"]["status"] == "accepted"
    assert annotations[0]["quote"] == "The manuscript appeared\nabruptly"
    assert annotations[0]["comment"] == "The transition may disorient the reader."
    assert annotations[0]["categories"] == ["clarity"]
    assert annotations[0]["priority"] == "high"
    assert annotations[0]["origin"]["kind"] == "llm-review-proposal"
    assert json.loads(result_path.read_text(encoding="utf-8"))["result"]["rejectedCandidates"][0]["status"] == "accepted"


def test_soft_leads_can_be_dismissed_or_promoted_without_becoming_human_annotations(tmp_path: Path) -> None:
    book = {"id": "book-12345678", "manuscriptId": "manuscript-12345678", "title": "Dunwich"}
    project = tmp_path / book["manuscriptId"]
    project.mkdir()
    source = "The manuscript appeared abruptly, and the hills answered."
    (project / "extracted-chapters.json").write_text(json.dumps([{"sequence": 8, "title": "CHAPTER 8", "text": source}]), encoding="utf-8")
    review = {"editorialVerdict": "no_material_concerns", "editorialProposals": [], "rejectedCandidates": [
        {"quote": "manuscript appeared abruptly", "comment": "The transition may disorient the reader.", "reason": "It may be intentional.", "category": "clarity", "priority": "high", "confidence": .85},
        {"quote": "hills answered", "comment": "The image may confuse a literal reading.", "reason": "The personification fits the voice.", "category": "prose", "priority": "low", "confidence": .45},
    ]}
    pipeline = {"chapters": [{"sequence": 8, "title": "CHAPTER 8", "llmReview": review, "llmReviewModel": "qwen"}], "stages": [], "chunks": []}
    result_path = project / "llm-review" / "results" / "0008.json"
    result_path.parent.mkdir(parents=True)
    result_path.write_text(json.dumps({"status": "complete", "result": review}), encoding="utf-8")

    with patch.object(server, "BOOKS_ROOT", tmp_path), patch.object(server, "load_pipeline", return_value=pipeline), patch.object(server, "write_pipeline"):
        promoted = server.decide_llm_review_candidate(book, 8, 0, "promote")
        dismissed = server.decide_llm_review_candidate(book, 8, 1, "dismiss")
        annotations = server.load_annotations(book)

    assert promoted["candidate"]["status"] == "promoted"
    assert promoted["proposal"]["status"] == "proposed"
    assert promoted["proposal"]["origin"] == "human_promoted_soft_lead"
    assert review["editorialVerdict"] == "material_concerns_found"
    assert dismissed["candidate"]["status"] == "dismissed"
    assert annotations == []
    saved = json.loads(result_path.read_text(encoding="utf-8"))["result"]
    assert saved["rejectedCandidates"][0]["status"] == "promoted"
    assert saved["rejectedCandidates"][1]["status"] == "dismissed"


def test_machine_review_lead_categories_can_be_corrected_without_creating_annotations(tmp_path: Path) -> None:
    proposal_id = "b" * 32
    book = {"id": "book-12345678", "manuscriptId": "manuscript-12345678", "title": "Dunwich"}
    project = tmp_path / book["manuscriptId"]
    project.mkdir()
    review = {
        "editorialProposals": [{"id": proposal_id, "quote": "the old road", "category": "editorial", "status": "proposed"}],
        "rejectedCandidates": [{"quote": "the ruined wall", "category": "clarity", "status": "dismissed"}],
    }
    pipeline = {"chapters": [{"sequence": 1, "title": "CHAPTER 1", "llmReview": review}], "stages": [], "chunks": []}
    result_path = project / "llm-review" / "results" / "0001.json"
    result_path.parent.mkdir(parents=True)
    result_path.write_text(json.dumps({"status": "complete", "result": review}), encoding="utf-8")

    with patch.object(server, "BOOKS_ROOT", tmp_path), patch.object(server, "load_pipeline", return_value=pipeline), patch.object(server, "write_pipeline"):
        proposal_result = server.decide_llm_review_proposal(book, proposal_id, "categorize", "plot")
        candidate_result = server.decide_llm_review_candidate(book, 1, 0, "categorize", "continuity")
        annotations = server.load_annotations(book)

    assert proposal_result["proposal"]["category"] == "plot"
    assert candidate_result["candidate"]["category"] == "continuity"
    assert annotations == []
    saved = json.loads(result_path.read_text(encoding="utf-8"))["result"]
    assert saved["editorialProposals"][0]["category"] == "plot"
    assert saved["rejectedCandidates"][0]["category"] == "continuity"


def test_soft_lead_promotion_has_an_explicit_server_capability_handshake() -> None:
    root = Path(__file__).parents[1]
    app = (root / "web" / "app.js").read_text(encoding="utf-8")

    assert API_FEATURES["llmReviewCandidatePromotion"] == 2
    assert 'requireChapterMapApi("llmReviewCandidatePromotion"' in app
    assert "running server predates soft-lead triage" in app
    assert 'class="llm-candidate-actions"' in app
    assert 'class="llm-candidate-message"' in app
    assert 'data-review-candidate-action="promote"' in app
    assert 'data-review-candidate-action="dismiss"' in app
    assert "Promote to significant" in app
    assert "Dismissed soft leads" in app
    assert "function annotationsForReviewLead" in app
    assert "function linkedReviewAnnotationMarkup" in app
    assert "function llmReviewProposalMarkup" in app
    assert 'proposalsMarkup ? `<h4>Significant concerns</h4>${proposalsMarkup}`' in app
    assert 'Object.assign(review.rejectedCandidates[candidateIndex], result.candidate || {})' in app
    assert 'await showBookPage(book.id, activeTab, "", pipeline)' in app
    assert "Soft leads used in annotations" in app
    assert 'llmReviewReportMarkup(pipeline, annotations)' in app
    assert 'data-open-annotation=' in app
    assert "annotation.comment" in app
    assert "annotationStart < leadEnd && annotationEnd > leadStart" in app
    assert "Number(annotation.chapterSequence) === Number(chapterSequence)" in app
    assert "Human annotation ${position + 1} of ${total}" in app
    assert "function reviewLeadToolsMarkup" in app
    assert 'data-view-review-proposal' in app
    assert 'data-review-lead-category' in app
    assert "No manuscript notes yet" in app
    assert 'body: JSON.stringify({action: "categorize", category})' in app


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

    assert artifact["schema"] == server.SMELL_SCHEMA_VERSION
    assert artifact["policyVersion"] == server.SMELL_POLICY_VERSION
    assert artifact["kept"] == 1
    assert artifact["candidates"][0]["detectors"] == ["bookinator", "spacy"]
    assert len(artifact["candidates"][0]["evidence"]) == 2
    assert checkpoints[0]["reviewProgress"] == {"completedBatches": 0, "totalBatches": 1, "complete": False}
    assert checkpoints[-1]["reviewProgress"] == {"completedBatches": 1, "totalBatches": 1, "complete": True}


def test_smells_keep_single_density_measurements_out_of_deep_review() -> None:
    findings = [{
        "detector": "Bookinator", "rule": "sentence-length", "message": "Long sentence: 34 words.",
        "sentenceStart": 0, "sentenceEnd": 32, "sentence": "A long but intelligible sentence.", "wordCount": 34,
    }]
    with patch.object(server, "analyze_prose_smells", return_value={"findings": findings, "errors": {}}), \
         patch.object(server, "run_structured_model") as run_model:
        artifact = server.analyze_chapter_smells({"text": "A long but intelligible sentence."}, "editor-model")

    run_model.assert_not_called()
    assert artifact["routedForDeepReview"] == 0
    assert artifact["informational"] == 1
    assert artifact["kept"] == 0
    assert artifact["styleSignals"][0]["issue"] == "Long sentence"
    assert artifact["candidates"][0]["routing"]["route"] == "style_metric"
    assert artifact["reviewProgress"] == {"completedBatches": 0, "totalBatches": 0, "complete": True}


def test_smell_policy_canonicalizes_doctrinaire_proselint_advice_without_deep_review() -> None:
    candidate = {"evidence": [{
        "detector": "Proselint", "rule": "weasel_words.very",
        "message": "Substitute ‘damn’ every time you’re inclined to write ‘very’.",
    }]}
    route = server.route_smell_candidate(candidate)

    assert candidate["issueFamilies"] == ["Weasel words"]
    assert route["route"] == "style_metric"
    assert route["review"] is False


def test_smells_keep_local_candidates_but_do_not_claim_complete_when_editor_review_fails() -> None:
    findings = [{"detector": "spacy", "rule": "garden-path", "message": "Possible garden path.", "sentenceStart": 0, "sentenceEnd": 16, "sentence": "While reading fell."}]
    with patch.object(server, "analyze_prose_smells", return_value={"findings": findings, "errors": {}}), patch.object(server, "run_structured_model", side_effect=RuntimeError("connection refused")):
        artifact = server.analyze_chapter_smells({"text": "While reading fell."}, "editor-model")

    assert artifact["reviewProgress"] == {"completedBatches": 1, "totalBatches": 1, "complete": False}
    assert artifact["reviewErrors"][0]["error"] == "connection refused"
    assert "judgment" not in artifact["candidates"][0]


def test_pipeline_workspace_revalidates_cached_status_when_live_work_starts() -> None:
    app = (Path(__file__).parents[1] / "web" / "app.js").read_text(encoding="utf-8")

    assert 'const cachedPipeline = tab !== "pipeline"' in app
    assert "function workspacePipelineNeedsPolling(bookId, pipeline)" in app
    assert "globalActivity?.bookId === bookId" in app
    assert app.count("workspacePipelineNeedsPolling(book.id, pipeline)") == 3
