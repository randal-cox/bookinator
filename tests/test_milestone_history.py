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
    index = (ROOT / "src" / "index.html").read_text(encoding="utf-8")
    pages = (ROOT / "src" / "pages.js").read_text(encoding="utf-8")
    app = (ROOT / "src" / "app.js").read_text(encoding="utf-8")
    history = (ROOT / "src" / "product-history.js").read_text(encoding="utf-8")
    shell = (ROOT / "src" / "product-shell.js").read_text(encoding="utf-8")

    assert 'data-inator-product-footer' in index
    assert 'href: "#help/start"' in shell
    assert 'resources: "docs/presentations/catalog.json"' in shell
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


def test_footer_information_architecture_uses_the_strict_commons_rollup():
    shell = (ROOT / "src" / "product-shell.js").read_text(encoding="utf-8")
    assert 'href: "#about/premise"' in shell
    assert 'href: "#help/start"' in shell
    assert 'createStandardProductShellPolicy' in shell
    assert 'defineProductInformationContract' in shell
    assert 'productShellFooterLinks' in shell
    assert 'label: "Resources"' not in shell
    assert 'omit:' not in shell


def test_docs_use_shared_editorial_flow_without_replacing_product_prose():
    index = (ROOT / "src" / "index.html").read_text(encoding="utf-8")
    app = (ROOT / "src" / "app.js").read_text(encoding="utf-8")
    pages = (ROOT / "src" / "pages.js").read_text(encoding="utf-8")
    docs = (ROOT / "src" / "product-docs.js").read_text(encoding="utf-8")

    assert '/commons/@inator/ui/product-information.css' in index
    assert 'createBookinatorHelpPage' in app
    assert 'collection === "help"' in app
    assert 'createProductDocsPage' in docs
    assert 'createProductDocsFlow' in docs
    assert 'createProductFaq' in docs
    assert 'HELP_GRAPHIC_ICONS' in docs
    assert 'replaceHelpLabelsWithGraphics(root)' in docs
    assert 'title: "How the local system works"' in pages
    assert "The browser directs; the server owns the work." in pages
    assert "Normal analysis remains on this computer." in pages


def test_about_uses_shared_product_and_ecosystem_tabs_with_record_shelf():
    app = (ROOT / "src" / "app.js").read_text(encoding="utf-8")
    pages = (ROOT / "src" / "pages.js").read_text(encoding="utf-8")
    information = (ROOT / "src" / "product-information.js").read_text(encoding="utf-8")

    assert "createBookinatorAboutPage" in app
    assert "createProductAboutPage" in information
    assert 'initialTab: requestedTab === "ecosystem" ? "ecosystem" : "product"' in app
    assert '"#about/ecosystem"' in app
    assert "createProductDocsFlow" in information
    assert "about: bookinatorAbout" in information
    assert "recordIds: Object.keys(recordRoutes)" in information
    for destination in ("milestones", "roadmap", "security", "privacy"):
        assert f'{destination}:' in information
    practice = (ROOT / "src" / "product-practice.js").read_text(encoding="utf-8")
    shell = (ROOT / "src" / "product-shell.js").read_text(encoding="utf-8")
    assert "createProductPracticeViewForFooter" in practice
    assert "defineProductPrivacy" in practice
    assert "defineProductSecurity" in practice
    assert 'createBookinatorPracticePage({ root: articleBody, destination: collection })' in app
    assert 'bookinatorShellPolicy.destinations.find' not in app
    assert 'privacy: {href: "#privacy"' in shell
    assert 'security: {href: "#security"' in shell


def test_ui_conformance_scans_bookinators_actual_source_root():
    package = (ROOT / "package.json").read_text(encoding="utf-8")
    assert 'inator audit-ui src --baseline .inator/ui-audit-baseline.json' in package


def test_about_guide_and_docs_describe_the_current_product():
    pages = (ROOT / "src" / "pages.js").read_text(encoding="utf-8")

    assert 'title: "A book remembers more than any prompt can hold"' in pages
    assert 'title: "From manuscript to editorial map"' in pages
    assert 'title: "How the local system works"' in pages
    assert "Interactive HTML" in pages
    assert "Questions &amp; Payoffs" in pages
    assert "Loopback only" in pages


def test_about_exposes_shared_trust_live_model_citations_and_editorial_artwork():
    information = (ROOT / "src" / "product-information.js").read_text(encoding="utf-8")
    pages = (ROOT / "src" / "pages.js").read_text(encoding="utf-8")
    styles = (ROOT / "src" / "styles.css").read_text(encoding="utf-8")

    assert "defineTrustSurface" in information
    assert "defineCitationRegistry" in information
    assert 'fetch("/api/system"' in information
    assert "citationRegistry: createModelCitationRegistry(system)" in information
    assert "trust: createBookinatorTrust(system)" in information
    assert "book-analysis-paper-landscape.png" in pages
    assert (ROOT / "src" / "assets" / "book-analysis-paper-landscape.png").is_file()
    assert "data-inator-icon" in pages
    assert ".article-body.inator-about-page .capability-bands p" in styles
    assert "activeAboutController?.destroy()" in information
    assert 'root.dataset.articleCollection !== "about"' in information
