from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_milestone_document_records_first_release_at_product_level():
    history = (ROOT / "docs" / "MILESTONES.md").read_text(encoding="utf-8")

    assert "0.3.0 — The Engine Room" in history
    assert "0.2.0 — Reviewer Tools" in history
    assert "0.1.0 — Holy Crap, that Worked" in history
    assert "Run **Carmilla**" in history
    assert "contract will move into Inator only after Bookinator" in history
    assert "What this milestone made possible" in history
    assert "Why it mattered" in history
    assert "Deliberately not finished" in history


def test_releases_are_reachable_from_the_app_footer():
    index = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    pages = (ROOT / "web" / "pages.js").read_text(encoding="utf-8")

    assert 'href="#releases/milestones"' in index
    assert 'data-page="releases"' in index
    assert ">Releases</a>" in index
    assert 'title: "Milestones, not machinery"' in pages
    assert "The Engine Room" in pages
    assert "Reviewer Tools" in pages
    assert "Carmilla gets the complete treatment" in pages
    assert "Holy Crap, that Worked" in pages
    assert "What came next" in pages


def test_footer_information_architecture_has_three_ordered_groups():
    index = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    footer = index[index.index('<nav class="footer-links"'):index.index("</nav>", index.index('<nav class="footer-links"'))]

    labels = [">About</a>", ">Guide</a>", ">Docs</a>", ">Roadmap</a>", ">Releases</a>", ">Resources</a>"]
    positions = [footer.index(label) for label in labels]
    assert positions == sorted(positions)
    assert footer.count('class="footer-link-group"') == 3
    assert footer.count('class="footer-link-divider"') == 2


def test_about_guide_and_docs_describe_the_current_product():
    pages = (ROOT / "web" / "pages.js").read_text(encoding="utf-8")

    assert 'title: "The book is larger than a prompt"' in pages
    assert 'title: "From manuscript to editorial map"' in pages
    assert 'title: "How the local system works"' in pages
    assert "Interactive HTML" in pages
    assert "Questions &amp; Payoffs" in pages
    assert "Loopback only" in pages
