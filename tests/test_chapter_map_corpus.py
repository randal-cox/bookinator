from bookinator.chapter_map_corpus import Candidate, category_for, parse_harvest_page, select_candidates


def test_harvest_page_exposes_mirror_files_and_next_offset() -> None:
    payload = b'''<a href="https://aleph.gutenberg.org/cache/epub/84/pg84.epub">book</a>
    <a href="harvest?offset=12345&amp;filetypes[]=epub.noimages&amp;langs[]=en">next</a>'''
    links, offset = parse_harvest_page(payload)
    assert links == {84: "https://www.gutenberg.org/cache/epub/84/pg84.epub"}
    assert offset == "12345"


def test_category_rules_preserve_structural_variety() -> None:
    assert category_for({"Subjects": "Short stories, English", "Bookshelves": ""}) == "short-stories"
    assert category_for({"Subjects": "Children -- Juvenile fiction", "Bookshelves": ""}) == "children"
    assert category_for({"Subjects": "History", "Bookshelves": ""}) == "nonfiction"


def test_selection_is_deterministic_and_unique() -> None:
    candidates = [Candidate(index, f"Title {index}", "Author", "History", "", "1900-01-01", "nonfiction", f"https://example/{index}.epub") for index in range(1, 401)]
    first = select_candidates(candidates, 40)
    second = select_candidates(list(reversed(candidates)), 40)
    assert [item.gutenberg_id for item in first] == [item.gutenberg_id for item in second]
    assert len({item.gutenberg_id for item in first}) == 40
