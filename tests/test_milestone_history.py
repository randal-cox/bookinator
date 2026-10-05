from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_milestone_document_records_first_release_at_product_level():
    history = (ROOT / "docs" / "MILESTONES.md").read_text(encoding="utf-8")

    assert "0.3.0 — Common Ground" in history
    assert "0.4.0 — Reanimator" in history
    assert "0.5.0 — The Engine Room" in history
    assert "0.2.0 — Reviewer Tools" in history
    assert "0.1.0 — Holy Crap, that Worked" in history
    assert "ordinary consumer of the installable Inator Commons" in history
    assert "temporary sibling-checkout dependency" in history
    assert "Use **Carmilla**" in history
    assert "What this milestone made possible" in history
    assert "Why it mattered" in history
    assert "Deliberately not finished" in history


def test_releases_use_shared_history_and_footer_uses_abbreviated_information_menu():
    index = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    pages = (ROOT / "web" / "pages.js").read_text(encoding="utf-8")
    app = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
    history = (ROOT / "web" / "product-history.js").read_text(encoding="utf-8")
    shell = (ROOT / "web" / "product-shell.js").read_text(encoding="utf-8")

    assert 'data-inator-product-footer' in index
    assert 'href: "#docs/architecture"' in shell
    assert 'label: "Resources"' in shell
    assert 'title: "Milestones, not machinery"' in pages
    assert '/commons/@inator/ui/product-history.css' in index
    assert 'createProductHistoryView' in app
    assert 'data-product-history' in app
    assert 'defineProductHistory' in history
    assert 'title: "Common Ground"' in history
    assert 'title: "Reviewer Tools"' in history
    assert 'title: "Holy Crap, that Worked"' in history
    assert 'title: "Reanimator"' in history
    assert 'title: "The Engine Room"' in history
    footer_config = shell.split("footer: {", 1)[1].split("}", 1)[0]
    assert "brand:" not in footer_config
    assert "status:" not in footer_config


def test_footer_information_architecture_is_about_docs_and_resources():
    shell = (ROOT / "web" / "product-shell.js").read_text(encoding="utf-8")
    labels = ['href: "#docs/architecture"', 'label: "Resources"']
    positions = [shell.index(label) for label in labels]
    assert positions == sorted(positions)
    assert 'href: "#about/premise"' in shell
    assert 'href: "#docs/architecture"' in shell
    assert 'defineProductShellPolicy' in shell
    assert 'productShellFooterLinks' in shell
    assert 'roles: ["developer", "team"]' in shell


def test_docs_use_shared_editorial_flow_without_replacing_product_prose():
    index = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    app = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
    pages = (ROOT / "web" / "pages.js").read_text(encoding="utf-8")
    docs = (ROOT / "web" / "product-docs.js").read_text(encoding="utf-8")

    assert '/commons/@inator/ui/product-information.css' in index
    assert 'createBookinatorDocsFlow' in app
    assert 'collection === "docs"' in app
    assert 'createProductDocsFlow' in docs
    assert 'createProductFaq' in docs
    assert 'title: "How the local system works"' in pages
    assert "The browser directs; the server owns the work." in pages
    assert "Normal analysis remains on this computer." in pages


def test_about_uses_shared_product_and_ecosystem_tabs_with_record_shelf():
    app = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
    pages = (ROOT / "web" / "pages.js").read_text(encoding="utf-8")
    information = (ROOT / "web" / "product-information.js").read_text(encoding="utf-8")

    assert "createBookinatorAboutPage" in app
    assert "createProductAboutPage" in information
    assert "createProductDocsFlow" in information
    assert "about: bookinatorAbout" in information
    assert "recordIds: Object.keys(recordRoutes)" in information
    for destination in ("milestones", "roadmap", "security", "privacy"):
        assert f'{destination}:' in information
    assert 'security: ["Security"' in pages


def test_about_guide_and_docs_describe_the_current_product():
    pages = (ROOT / "web" / "pages.js").read_text(encoding="utf-8")

    assert 'title: "The book is larger than a prompt"' in pages
    assert 'title: "From manuscript to editorial map"' in pages
    assert 'title: "How the local system works"' in pages
    assert "Interactive HTML" in pages
    assert "Questions &amp; Payoffs" in pages
    assert "Loopback only" in pages
