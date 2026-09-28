import json
import zipfile
from pathlib import Path

from bookinator.chapter_map_lab import epub_reference_headings, evaluate_specimen, heading_labels_match, provisional_triage, run_benchmark, structural_reference_headings


def make_epub(path: Path) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("META-INF/container.xml", """<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles><rootfile full-path="OPS/package.opf"/></rootfiles></container>""")
        archive.writestr("OPS/package.opf", """<package xmlns="http://www.idpf.org/2007/opf"><manifest><item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/><item id="c1" href="chapter.xhtml" media-type="application/xhtml+xml"/></manifest><spine><itemref idref="c1"/></spine></package>""")
        archive.writestr("OPS/nav.xhtml", """<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops"><body><nav epub:type="toc"><ol><li><a href="chapter.xhtml#one">Chapter One</a></li><li><a href="chapter.xhtml#two">Chapter Two</a></li></ol></nav></body></html>""")
        archive.writestr("OPS/chapter.xhtml", """<html xmlns="http://www.w3.org/1999/xhtml"><body><h2 id="one">CHAPTER ONE</h2><p>First.</p><h2 id="two">CHAPTER TWO</h2><p>Second.</p></body></html>""")


def test_epub_navigation_is_comparison_evidence(tmp_path: Path) -> None:
    source = tmp_path / "two-chapters.epub"
    make_epub(source)
    assert epub_reference_headings(source.read_bytes()) == ["Chapter One", "Chapter Two"]
    result = evaluate_specimen(source, tmp_path)
    assert [item["title"] for item in result["detected"]] == ["CHAPTER ONE", "CHAPTER TWO"]
    assert result["referenceCount"] == 2
    assert result["provisionalTier"] == "auto-candidate"


def test_structural_navigation_ignores_chrome_but_recovers_embedded_chapter_labels() -> None:
    labels = ["CONTENTS", "A decorative caption. CHAPTER II.", "Letter 3", "XIV. A Vision", "THE FULL PROJECT GUTENBERG LICENSE"]
    assert structural_reference_headings(labels) == ["CHAPTER II.", "Letter 3", "XIV. A Vision"]


def test_navigation_comparison_matches_ordinal_despite_richer_titles() -> None:
    assert heading_labels_match("CHAPTER XIV", "Chapter Fourteen — The River")
    assert heading_labels_match("XIV", "Chapter 14. The River")
    chapters = [{"title": "CHAPTER I"}, {"title": "CHAPTER II"}, {"title": "CHAPTER III"}]
    tier, reasons = provisional_triage(chapters, ["Chapter One — A", "Chapter Two — B", "Chapter Three — C"], [])
    assert tier == "auto-candidate"
    assert reasons == ["3 of 3 source-navigation labels match by structural identity."]


def test_benchmark_writes_machine_results_and_human_review_surface(tmp_path: Path) -> None:
    source = tmp_path / "story.md"
    source.write_text("## 1\n\nFirst.\n\n## 2\n\nSecond.\n", encoding="utf-8")
    output = tmp_path / "output"
    payload = run_benchmark([source], output)
    assert payload["schema"] == "bookinator-chapter-map-benchmark-v1"
    assert len(payload["specimens"]) == 1
    assert json.loads((output / "results.json").read_text(encoding="utf-8"))["specimens"][0]["detectedCount"] == 2
    report = (output / "index.html").read_text(encoding="utf-8")
    assert "Human judgment" in report
    assert "Export reviews" in report
    assert "bookinator.chapter-map-reviews.v1" in report

    specimen_id = payload["specimens"][0]["id"]
    reviews = tmp_path / "reviews.json"
    reviews.write_text(json.dumps({"schema": "bookinator-chapter-map-reviews-v1", "reviews": {specimen_id: {"verdict": "pass", "note": "Correct."}}}), encoding="utf-8")
    rerun = tmp_path / "rerun"
    run_benchmark([source], rerun, reviews_path=reviews)
    seeded = (rerun / "index.html").read_text(encoding="utf-8")
    assert '"verdict": "pass"' in seeded
    assert "Correct." in seeded
