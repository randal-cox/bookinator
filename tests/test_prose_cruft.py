from bookinator.prose_cruft import analyze, prose_projection, sentence_spans


def test_sentence_spans_preserve_offsets_and_skip_markdown_heading():
    text = "# CHAPTER 1\n\nFirst sentence. Second sentence!"
    spans = sentence_spans(text)
    assert [item[2] for item in spans] == ["First sentence.", "Second sentence!"]
    assert text[spans[0][0] : spans[0][1]] == "First sentence."


def test_deterministic_bakeoff_reports_full_flagged_sentence():
    sentence = "And ".join(["this clause"] * 16) + "."
    result = analyze(sentence, detectors=("bookinator",))
    assert result["errors"] == {}
    assert any(item["rule"] == "sentence-length" for item in result["findings"])
    assert all(item["sentence"] == sentence for item in result["findings"])


def test_prose_projection_masks_markdown_headings_without_moving_offsets():
    text = "# CHAPTER 1\n\n## SHADOW\n\nTimmy watches the road."
    projected = prose_projection(text)
    assert len(projected) == len(text)
    assert projected[:11] == " " * 11
    assert projected.index("Timmy") == text.index("Timmy")
    assert "CHAPTER" not in projected
    assert "SHADOW" not in projected
