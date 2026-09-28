import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PRESENTATIONS = ROOT / "docs" / "presentations"
DECK = ROOT / "docs" / "pitch-authors-editors"
BRIEFS = ROOT / "docs" / "briefs"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_resource_catalog_describes_current_materials():
    resources = json.loads(read(PRESENTATIONS / "catalog.json"))

    assert [resource["id"] for resource in resources] == [
        "why-bookinator",
        "one-pager",
        "elevator-pitches",
        "wish-list",
    ]
    assert resources[-1]["title"] == "Next bets and evaluation"
    assert resources[-1]["status"] == "Working direction"
    assert all("free forever" not in json.dumps(resource).lower() for resource in resources)

    for resource in resources:
        for action in resource["actions"]:
            target = (PRESENTATIONS / action["url"]).resolve()
            if target.is_dir():
                target /= "index.html"
            assert target.exists(), f"Missing resource target: {target}"


def test_audience_deck_separates_working_product_from_future_work():
    deck = read(DECK / "index.html")

    assert len(re.findall(r'<section class="slide\b', deck)) == 16
    for phrase in (
        "Holy Crap, that Worked",
        "Connections",
        "Questions &amp; Payoffs",
        "PDF and interactive exports",
        "Working now",
        "Still future work",
        "Business Source License 1.1",
    ):
        assert phrase in deck

    assert "double-clickable" not in deck.lower()
    assert "portable book projects" not in deck.lower()


def test_briefs_use_precise_claims_and_explicit_aspirations():
    overview = read(BRIEFS / "one-pager.html")
    pitches = read(BRIEFS / "elevator-pitches.html")
    bets = read(BRIEFS / "wish-list.html")

    assert "Business Source License 1.1" in overview
    assert "Questions &amp; Payoffs" in overview
    assert "interactive HTML" in overview
    assert "produces editorial leads, not proof" in overview

    assert "Do not say “free forever.”" in pitches
    assert "Do not claim revision comparison" in pitches

    assert "Proved in 0.1.0" in bets
    assert "Next" in bets
    assert "Aspirations" in bets
    assert "directions, not release promises" in bets


def test_resource_catalog_bypasses_stale_browser_cache():
    script = read(PRESENTATIONS / "presentations.js")
    assert 'fetch("catalog.json", { cache: "no-store" })' in script
