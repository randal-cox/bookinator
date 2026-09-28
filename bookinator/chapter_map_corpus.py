"""Acquire a provenance-rich Project Gutenberg corpus through its robot feeds."""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import html
import io
import json
import re
import time
import urllib.request
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

CATALOG_URL = "https://www.gutenberg.org/cache/epub/feeds/pg_catalog.csv.gz"
HARVEST_URL = "https://www.gutenberg.org/robot/harvest"
USER_AGENT = "Bookinator chapter-map research; contact via https://github.com/randal-cox/bookinator"
DEFAULT_QUOTAS = {
    "fiction": 110,
    "nonfiction": 70,
    "short-stories": 35,
    "children": 25,
    "drama": 20,
    "poetry": 20,
    "letters-diaries": 20,
}
ANCHOR_IDS = (11, 43, 55, 74, 76, 84, 98, 120, 174, 345, 768, 1260, 1342, 1661, 1952, 2701)


@dataclass(frozen=True)
class Candidate:
    gutenberg_id: int
    title: str
    author: str
    subjects: str
    bookshelves: str
    issued: str
    category: str
    epub_url: str


def fetch(url: str) -> bytes:
    # Gutenberg's robot feed currently emits aleph.gutenberg.org HTTPS URLs
    # with a certificate for the main host. The identical documented mirror
    # path is available on www.gutenberg.org with a valid certificate.
    url = url.replace("https://aleph.gutenberg.org/", "https://www.gutenberg.org/")
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=90) as response:
        return response.read()


def harvest_page_url(filetype: str, offset: str = "") -> str:
    query = f"filetypes[]={filetype}&langs[]=en"
    return f"{HARVEST_URL}?{f'offset={offset}&' if offset else ''}{query}"


def parse_harvest_page(payload: bytes) -> tuple[dict[int, str], str]:
    text = payload.decode("utf-8", errors="replace")
    links: dict[int, str] = {}
    for raw_url in re.findall(r'href="(https://aleph\.gutenberg\.org/[^"?#]+)"', text):
        url = html.unescape(raw_url).replace("https://aleph.gutenberg.org/", "https://www.gutenberg.org/")
        match = re.search(r"/cache/epub/(\d+)/", url)
        if not match:
            match = re.search(r"/(\d+)(?:-[^/]*)?\.(?:epub|zip|txt)$", url)
        if match:
            links[int(match.group(1))] = url
    next_matches = re.findall(r'href="harvest\?offset=(\d+)&amp;', text)
    return links, next_matches[-1] if next_matches else ""


def collect_harvest_links(filetype: str, minimum: int, delay: float, cache_path: Path | None = None) -> dict[int, str]:
    links: dict[int, str] = {}
    offset = ""
    if cache_path and cache_path.exists():
        cached = json.loads(cache_path.read_text(encoding="utf-8"))
        links = {int(key): str(value) for key, value in cached.get("links", {}).items()}
        offset = str(cached.get("nextOffset") or "")
        print(f"Harvest {filetype}: resuming from {len(links)} cached files")
    while len(links) < minimum:
        payload = fetch(harvest_page_url(filetype, offset))
        page_links, next_offset = parse_harvest_page(payload)
        links.update(page_links)
        print(f"Harvest {filetype}: {len(links)} files listed")
        if cache_path:
            cache_path.write_text(json.dumps({"nextOffset": next_offset, "links": links}, indent=2) + "\n", encoding="utf-8")
        if not next_offset or next_offset == offset:
            break
        offset = next_offset
        if delay:
            time.sleep(delay)
    return links


def category_for(row: dict[str, str]) -> str:
    evidence = " ".join((row.get("Subjects", ""), row.get("Bookshelves", ""))).casefold()
    if any(term in evidence for term in ("short stories", "short story")):
        return "short-stories"
    if any(term in evidence for term in ("juvenile fiction", "children's", "children --")):
        return "children"
    if any(term in evidence for term in ("drama", "plays", "tragedies", "comedies")):
        return "drama"
    if any(term in evidence for term in ("poetry", "poems", "verse")):
        return "poetry"
    if any(term in evidence for term in ("correspondence", "diaries", "diary", "letters")):
        return "letters-diaries"
    if any(term in evidence for term in ("fiction", "novel")):
        return "fiction"
    return "nonfiction"


def read_catalog(payload: bytes, epub_links: dict[int, str]) -> list[Candidate]:
    decoded = gzip.decompress(payload).decode("utf-8-sig", errors="replace")
    candidates: list[Candidate] = []
    for row in csv.DictReader(io.StringIO(decoded)):
        try:
            gutenberg_id = int(row.get("Text#", ""))
        except ValueError:
            continue
        if gutenberg_id not in epub_links or row.get("Type") != "Text" or row.get("Language") != "en":
            continue
        title = re.sub(r"\s+", " ", row.get("Title", "")).strip()
        author = re.sub(r"\s+", " ", row.get("Authors", "")).strip()
        if not title or not author:
            continue
        candidates.append(Candidate(
            gutenberg_id=gutenberg_id,
            title=title,
            author=author,
            subjects=row.get("Subjects", ""),
            bookshelves=row.get("Bookshelves", ""),
            issued=row.get("Issued", ""),
            category=category_for(row),
            epub_url=epub_links[gutenberg_id],
        ))
    return candidates


def select_candidates(candidates: list[Candidate], target: int) -> list[Candidate]:
    quotas = {key: round(value * target / sum(DEFAULT_QUOTAS.values())) for key, value in DEFAULT_QUOTAS.items()}
    while sum(quotas.values()) > target:
        largest = max(quotas, key=quotas.get)
        quotas[largest] -= 1
    while sum(quotas.values()) < target:
        quotas["nonfiction"] += 1
    pools: dict[str, list[Candidate]] = defaultdict(list)
    for candidate in candidates:
        pools[candidate.category].append(candidate)
    stable = lambda item: hashlib.sha256(f"bookinator-structure-v1:{item.gutenberg_id}:{item.title}".encode()).hexdigest()
    for pool in pools.values():
        pool.sort(key=stable)
    selected: list[Candidate] = []
    chosen: set[int] = set()
    by_id = {item.gutenberg_id: item for item in candidates}
    for gutenberg_id in ANCHOR_IDS:
        candidate = by_id.get(gutenberg_id)
        if candidate and len(selected) < target:
            selected.append(candidate)
            chosen.add(gutenberg_id)
    counts: dict[str, int] = defaultdict(int)
    for item in selected:
        counts[item.category] += 1
    for category, quota in quotas.items():
        for candidate in pools.get(category, []):
            if counts[category] >= quota:
                break
            if candidate.gutenberg_id in chosen:
                continue
            selected.append(candidate)
            chosen.add(candidate.gutenberg_id)
            counts[category] += 1
    if len(selected) < target:
        for candidate in sorted(candidates, key=stable):
            if candidate.gutenberg_id in chosen:
                continue
            selected.append(candidate)
            chosen.add(candidate.gutenberg_id)
            if len(selected) == target:
                break
    return selected[:target]


def safe_name(candidate: Candidate) -> str:
    stem = re.sub(r"[^a-z0-9]+", "-", candidate.title.casefold()).strip("-")[:70] or "untitled"
    return f"pg{candidate.gutenberg_id}-{stem}"


def download_source(url: str, path: Path, delay: float) -> dict[str, object]:
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = fetch(url)
        temporary = path.with_suffix(path.suffix + ".part")
        temporary.write_bytes(payload)
        temporary.replace(path)
        if delay:
            time.sleep(delay)
    payload = path.read_bytes()
    return {"path": str(path), "bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}


def build_corpus(destination: Path, target: int = 300, text_pairs: int = 50, delay: float = 2.0) -> dict[str, object]:
    destination.mkdir(parents=True, exist_ok=True)
    catalog_path = destination / "pg_catalog.csv.gz"
    if not catalog_path.exists():
        catalog_path.write_bytes(fetch(CATALOG_URL))
    epub_links = collect_harvest_links("epub.noimages", max(target * 12, 3600), delay, destination / "harvest-epub-noimages.json")
    candidates = read_catalog(catalog_path.read_bytes(), epub_links)
    selected = select_candidates(candidates, target)
    if len(selected) < target:
        raise RuntimeError(f"Only {len(selected)} eligible works were found; {target} are required.")
    # Generated UTF-8 text lives beside each generated EPUB in Gutenberg's
    # cache, so paired formats do not require crawling the legacy zip listing.
    text_links = {
        item.gutenberg_id: f"https://www.gutenberg.org/cache/epub/{item.gutenberg_id}/pg{item.gutenberg_id}.txt"
        for item in selected[:text_pairs]
    }
    pair_candidates = selected[:text_pairs]
    paired_ids = {item.gutenberg_id for item in pair_candidates}
    acquired_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    works: list[dict[str, object]] = []
    for index, candidate in enumerate(selected, 1):
        stem = safe_name(candidate)
        print(f"[{index}/{len(selected)}] {candidate.title}")
        epub = download_source(candidate.epub_url, destination / "sources" / "epub" / f"{stem}.epub", delay)
        formats = [{**epub, "format": "epub", "sourceUrl": candidate.epub_url}]
        if candidate.gutenberg_id in paired_ids:
            text_url = text_links[candidate.gutenberg_id]
            text = download_source(text_url, destination / "sources" / "text" / f"{stem}.txt", delay)
            formats.append({**text, "format": "txt", "sourceUrl": text_url})
        works.append({
            "gutenbergId": candidate.gutenberg_id,
            "title": candidate.title,
            "author": candidate.author,
            "issued": candidate.issued,
            "category": candidate.category,
            "subjects": candidate.subjects.split("; ") if candidate.subjects else [],
            "bookshelves": candidate.bookshelves.split("; ") if candidate.bookshelves else [],
            "landingUrl": f"https://www.gutenberg.org/ebooks/{candidate.gutenberg_id}",
            "rightsNote": "Project Gutenberg source selected from its English public-domain catalog; jurisdiction-specific reuse must be checked separately.",
            "formats": formats,
        })
        manifest = {
            "schema": "bookinator-chapter-map-corpus-v1",
            "generatedAt": acquired_at,
            "catalogUrl": CATALOG_URL,
            "harvestUrl": HARVEST_URL,
            "selection": {"targetWorks": target, "textPairs": text_pairs, "quotas": DEFAULT_QUOTAS},
            "works": works,
        }
        (destination / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Acquire the public-domain Bookinator chapter-map corpus.")
    parser.add_argument("--destination", type=Path, default=Path(".bookinator/benchmarks/chapter-map-corpus"))
    parser.add_argument("--target", type=int, default=300)
    parser.add_argument("--text-pairs", type=int, default=50)
    parser.add_argument("--delay", type=float, default=2.0, help="Seconds between Gutenberg requests")
    args = parser.parse_args(argv)
    manifest = build_corpus(args.destination, args.target, args.text_pairs, max(0, args.delay))
    specimens = sum(len(work["formats"]) for work in manifest["works"])
    print(f"Acquired {len(manifest['works'])} works and {specimens} format specimens.")
    return 0
