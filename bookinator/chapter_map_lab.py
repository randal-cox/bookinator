"""Standalone, human-reviewed chapter-map benchmark using Bookinator's production detector."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import subprocess
import time
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

from bookinator.server.__main__ import (
    archive_manuscript_text,
    chapter_heading_report,
    chapter_heading_report_warnings,
    chapter_map_warnings,
    detect_chapters,
    source_text_to_pages,
    strip_markdown_heading,
    strip_project_gutenberg_boilerplate,
)

SUPPORTED_SUFFIXES = {".epub", ".md", ".txt", ".docx", ".pdf"}


def normalized_heading(value: object) -> str:
    return re.sub(r"\W+", "", strip_markdown_heading(value)).casefold()


NUMBER_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
    "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16,
    "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50,
}


def normalized_ordinal(value: str) -> str:
    token = re.sub(r"[^A-Za-z0-9-]", "", value).casefold()
    if token.isdigit():
        return str(int(token))
    if re.fullmatch(r"[ivxlcdm]+", token):
        values = {"i": 1, "v": 5, "x": 10, "l": 50, "c": 100, "d": 500, "m": 1000}
        total = 0
        previous = 0
        for character in reversed(token):
            current = values[character]
            total += -current if current < previous else current
            previous = max(previous, current)
        return str(total)
    parts = token.split("-")
    if parts and all(part in NUMBER_WORDS for part in parts):
        return str(sum(NUMBER_WORDS[part] for part in parts))
    return token


def heading_signature(value: object) -> tuple[str, str] | None:
    label = re.sub(r"\s+", " ", strip_markdown_heading(value)).strip()
    explicit = re.search(r"\b(chapter|letter|part|book|appendix)\s+([A-Za-z0-9-]+)", label, re.IGNORECASE)
    if explicit:
        return explicit.group(1).casefold(), normalized_ordinal(explicit.group(2))
    standalone = re.fullmatch(r"(?:prologue|epilogue|interlude)", label, re.IGNORECASE)
    if standalone:
        return standalone.group(0).casefold(), ""
    numeral = re.match(r"^(\d{1,4}|[IVXLCDM]{1,12})(?:\b|[.:—-])", label, re.IGNORECASE)
    if numeral:
        return "division", normalized_ordinal(numeral.group(1))
    return None


def heading_labels_match(left: object, right: object) -> bool:
    if normalized_heading(left) == normalized_heading(right):
        return True
    left_signature = heading_signature(left)
    right_signature = heading_signature(right)
    if not left_signature or not right_signature or left_signature[1] != right_signature[1]:
        return False
    return left_signature[0] == right_signature[0] or "division" in {left_signature[0], right_signature[0]}


def structural_reference_headings(labels: list[str]) -> list[str]:
    """Reduce navigation chrome and image captions to likely book divisions."""
    structural: list[str] = []
    explicit = re.compile(r"\b(?:chapter|letter|part|book|prologue|epilogue|appendix|interlude)\b.*$", re.IGNORECASE)
    numeral = re.compile(r"^(?:\d{1,4}|[IVXLCDM]{1,12})(?:\s*[.:—-]\s*\S.*)?$", re.IGNORECASE)
    for raw in labels:
        label = re.sub(r"\s+", " ", str(raw)).strip()
        if not label or "project gutenberg" in label.casefold():
            continue
        match = explicit.search(label)
        candidate = match.group(0).strip() if match else label
        if match or numeral.fullmatch(candidate):
            structural.append(candidate)
    return list(dict.fromkeys(structural))


def _element_text(element: ET.Element) -> str:
    return re.sub(r"\s+", " ", " ".join(element.itertext())).strip()


def epub_reference_headings(source: bytes) -> list[str]:
    """Read the publisher's navigation labels as comparison evidence, not truth."""
    with zipfile.ZipFile(io.BytesIO(source)) as archive:
        try:
            container = ET.fromstring(archive.read("META-INF/container.xml"))
            package_path = str(container.find(".//{*}rootfile").attrib.get("full-path") or "")
            package = ET.fromstring(archive.read(package_path))
        except (KeyError, AttributeError, ET.ParseError):
            return []
        root = Path(package_path).parent.as_posix()
        root = "" if root == "." else root
        manifest = [item for item in package.findall(".//{*}manifest/{*}item")]
        nav_item = next((item for item in manifest if "nav" in str(item.attrib.get("properties") or "").split()), None)
        if nav_item is not None:
            name = "/".join(part for part in (root, str(nav_item.attrib.get("href") or "")) if part)
            try:
                nav = ET.fromstring(archive.read(name))
                toc = next((item for item in nav.findall(".//{*}nav") if "toc" in str(item.attrib.get("{http://www.idpf.org/2007/ops}type") or item.attrib.get("type") or "").split()), nav)
                labels = [_element_text(link) for link in toc.findall(".//{*}a")]
                return list(dict.fromkeys(label for label in labels if label))
            except (KeyError, ET.ParseError):
                pass
        ncx_item = next((item for item in manifest if item.attrib.get("media-type") == "application/x-dtbncx+xml"), None)
        if ncx_item is None:
            return []
        name = "/".join(part for part in (root, str(ncx_item.attrib.get("href") or "")) if part)
        try:
            ncx = ET.fromstring(archive.read(name))
        except (KeyError, ET.ParseError):
            return []
        labels = [_element_text(item) for item in ncx.findall(".//{*}navPoint/{*}navLabel")]
        return list(dict.fromkeys(label for label in labels if label))


def manuscript_pages(path: Path) -> tuple[list[str], bool, list[str]]:
    source = path.read_bytes()
    suffix = path.suffix.casefold()
    raw_references = epub_reference_headings(source) if suffix == ".epub" else []
    references = structural_reference_headings(raw_references)
    if suffix in {".epub", ".docx"}:
        source = archive_manuscript_text(source, suffix)
    if suffix in {".epub", ".docx", ".md", ".txt"}:
        text = strip_project_gutenberg_boilerplate(source.decode("utf-8-sig", errors="replace"))
        if suffix == ".md" and not references:
            references = [strip_markdown_heading(line) for line in text.splitlines() if re.match(r"^#{1,6}\s+\S", line)]
        return source_text_to_pages(text, preserve_plain_headings=suffix == ".txt"), False, references
    if suffix == ".pdf":
        import pymupdf  # type: ignore[import-not-found]
        with pymupdf.open(stream=source, filetype="pdf") as document:
            pages = ["\n\n".join(str(block[4] or "") for block in sorted(page.get_text("blocks"), key=lambda item: (item[1], item[0]))) for page in document]
        return pages, True, references
    raise ValueError(f"Unsupported specimen format: {path.suffix or 'none'}")


def provisional_triage(chapters: list[dict[str, object]], references: list[str], warnings: list[str]) -> tuple[str, list[str]]:
    """Prioritize review; never pretend the comparison source is ground truth."""
    authored = [chapter for chapter in chapters if normalized_heading(chapter.get("title")) != "frontmatter"]
    detected = [chapter.get("title") for chapter in authored]
    comparable = [label for label in references if normalized_heading(label)]
    reasons: list[str] = []
    if len(authored) <= 1 and len(comparable) >= 3:
        reasons.append(f"Only {len(authored)} section was detected while the source navigation lists {len(comparable)} entries.")
        return "block-candidate", reasons
    unmatched = list(detected)
    overlap = 0
    for reference in comparable:
        match_index = next((index for index, label in enumerate(unmatched) if heading_labels_match(label, reference)), None)
        if match_index is not None:
            overlap += 1
            unmatched.pop(match_index)
    if comparable and len(comparable) >= 3 and (len(authored) / len(comparable) < 0.75 or overlap / len(comparable) < 0.55):
        reasons.append(f"Bookinator found {len(authored)} authored divisions; only {overlap} of {len(comparable)} structural navigation labels match.")
        return "block-candidate", reasons
    if comparable and len(authored) != len(comparable):
        reasons.append(f"Bookinator found {len(authored)} authored divisions while source navigation suggests {len(comparable)}.")
        return "mention-candidate", [*warnings, *reasons]
    if warnings:
        reasons.extend(warnings)
        return "mention-candidate", reasons
    if comparable:
        reasons.append(f"{overlap} of {len(comparable)} source-navigation labels match by structural identity.")
    else:
        reasons.append("No independent navigation labels were available; spot-check the source.")
    return "auto-candidate", reasons


def evaluate_specimen(path: Path, root: Path) -> dict[str, object]:
    started = time.monotonic()
    source = path.read_bytes()
    pages, fixed_pagination, references = manuscript_pages(path)
    chapters, method = detect_chapters(pages, fixed_pagination=fixed_pagination, allow_bare_numerals=path.suffix.casefold() == ".txt")
    report = chapter_heading_report(pages, chapters)
    warnings = [*chapter_map_warnings(chapters), *chapter_heading_report_warnings(report)]
    tier, reasons = provisional_triage(chapters, references, warnings)
    return {
        "id": hashlib.sha256(source).hexdigest()[:16],
        "path": path.relative_to(root).as_posix() if path.is_relative_to(root) else str(path),
        "format": path.suffix.casefold().removeprefix("."),
        "bytes": len(source),
        "sha256": hashlib.sha256(source).hexdigest(),
        "sourceSpans": len(pages),
        "fixedPagination": fixed_pagination,
        "method": method,
        "detectedCount": len(chapters),
        "detected": [{"sequence": item.get("sequence"), "title": item.get("title"), "role": item.get("analysisRole"), "pageStart": item.get("pageStart"), "pageEnd": item.get("pageEnd")} for item in chapters],
        "referenceCount": len(references),
        "referenceHeadings": references,
        "headingReport": report,
        "warnings": warnings,
        "provisionalTier": tier,
        "triageReasons": reasons,
        "durationMs": round((time.monotonic() - started) * 1000, 2),
    }


def discover_specimens(inputs: list[Path]) -> tuple[Path, list[Path]]:
    resolved = [path.resolve() for path in inputs]
    files: list[Path] = []
    for path in resolved:
        if path.is_file() and path.suffix.casefold() in SUPPORTED_SUFFIXES and path.name.casefold() != "readme.md":
            files.append(path)
        elif path.is_dir():
            files.extend(
                item for item in path.rglob("*")
                if item.is_file() and item.suffix.casefold() in SUPPORTED_SUFFIXES
                and item.name.casefold() != "readme.md" and not any(part.startswith(".") for part in item.relative_to(path).parts)
            )
    files = sorted(set(files), key=lambda item: str(item).casefold())
    if not files:
        raise ValueError("No EPUB, PDF, DOCX, Markdown, or text specimens were found.")
    common = Path(Path(*Path(files[0]).parts[:1]))
    try:
        import os
        common = Path(os.path.commonpath(files))
        if common.is_file():
            common = common.parent
    except ValueError:
        common = Path.cwd()
    return common, files


def git_revision(root: Path) -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=root, check=True, capture_output=True, text=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def implementation_fingerprint(root: Path) -> str:
    digest = hashlib.sha256()
    for path in (root / "bookinator" / "server" / "__main__.py", Path(__file__)):
        digest.update(path.read_bytes())
    return digest.hexdigest()


def build_report_html(payload: dict[str, object], seeded_reviews: dict[str, object] | None = None) -> str:
    encoded = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    seeded = json.dumps(seeded_reviews or {}, ensure_ascii=False).replace("</", "<\\/")
    return f"""<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\"><title>Bookinator chapter-map lab</title><style>
:root{{--navy:#0b2852;--blue:#176dcc;--line:#cad8e8;--muted:#60738d;--paper:#f4f7fb;--green:#187c61;--amber:#a56800;--red:#a43f38}}*{{box-sizing:border-box}}body{{margin:0;color:#102541;background:var(--paper);font:15px/1.45 Inter,system-ui,sans-serif}}header.top{{padding:28px clamp(20px,5vw,70px);color:white;background:var(--navy)}}h1,h2,h3{{font-family:Georgia,serif}}h1{{margin:3px 0;font-size:36px}}header.top p{{max-width:80ch;margin:0;color:#c7d9ed}}main{{max-width:1500px;margin:auto;padding:24px clamp(16px,4vw,54px) 70px}}.summary,.toolbar,.book{{background:white;border:1px solid var(--line);border-radius:12px}}.summary{{display:grid;grid-template-columns:repeat(5,1fr);overflow:hidden}}.summary div{{padding:16px;border-right:1px solid var(--line)}}.summary div:last-child{{border:0}}.summary strong,.summary span{{display:block}}.summary strong{{font:600 25px Georgia,serif}}.summary span{{color:var(--muted);font-size:12px}}.toolbar{{position:sticky;z-index:4;top:0;display:flex;gap:8px;align-items:center;margin:16px 0;padding:10px}}button,select,input{{font:inherit}}button{{padding:8px 11px;color:#274461;background:#f8fbff;border:1px solid #bfcfe1;border-radius:8px;font-weight:750;cursor:pointer}}button[aria-pressed=true]{{color:white;background:var(--navy)}}.toolbar input{{min-width:240px;flex:1;padding:9px 11px;border:1px solid var(--line);border-radius:8px}}.book{{margin:12px 0;overflow:hidden}}.book>summary{{display:grid;grid-template-columns:18px minmax(240px,1fr) 100px 120px 90px;align-items:center;gap:14px;padding:14px 16px;cursor:pointer}}.book>summary::marker{{content:\"\"}}.dot{{width:11px;height:11px;border-radius:50%;background:#7990a9}}.mention-candidate .dot{{background:#d18a16}}.block-candidate .dot{{background:#c2473d}}.book h2{{margin:0;font-size:19px}}.book small{{display:block;color:var(--muted)}}.badge{{justify-self:start;padding:4px 8px;border-radius:99px;background:#edf2f8;font-size:11px;font-weight:850}}.review{{padding:18px;border-top:1px solid var(--line);background:#fbfdff}}.columns{{display:grid;grid-template-columns:1fr 1fr 1fr;gap:14px}}.columns section{{min-width:0;padding:13px;background:white;border:1px solid #dae4ef;border-radius:9px}}.columns h3{{margin:0 0 8px;font-size:16px}}ol,ul{{margin:0;padding-left:22px}}li{{margin:4px 0}}.headings{{max-height:280px;overflow:auto}}.verdicts{{display:flex;flex-wrap:wrap;gap:7px;margin-top:14px;padding-top:14px;border-top:1px solid var(--line)}}.verdicts span{{align-self:center;margin-right:4px;font-weight:850}}.verdict-pass[aria-pressed=true]{{background:var(--green)}}.verdict-mention[aria-pressed=true]{{background:var(--amber)}}.verdict-block[aria-pressed=true],.verdict-fail[aria-pressed=true]{{background:var(--red)}}textarea{{width:100%;min-height:72px;margin-top:10px;padding:10px;border:1px solid var(--line);border-radius:8px;resize:vertical}}.empty{{padding:50px;text-align:center}}@media(max-width:800px){{.summary{{grid-template-columns:1fr 1fr}}.book>summary{{grid-template-columns:18px 1fr auto}}.book>summary>:nth-last-child(-n+2){{display:none}}.columns{{grid-template-columns:1fr}}}}
</style></head><body><header class=\"top\"><small>BOOKINATOR · STRUCTURE BENCHMARK</small><h1>Chapter-map lab</h1><p>Production detector output, independent source-navigation evidence, and human judgments remain separate. A navigation mismatch is a prompt to inspect—not automatic proof that Bookinator is wrong.</p></header><main><section class=\"summary\" id=\"summary\"></section><div class=\"toolbar\"><input id=\"search\" type=\"search\" placeholder=\"Find a specimen or heading\"><button data-filter=\"all\" aria-pressed=\"true\">All</button><button data-filter=\"unreviewed\">Unreviewed</button><button data-filter=\"block-candidate\">Inspect first</button><button id=\"export\">Export reviews</button></div><div id=\"books\"></div></main><script id=\"benchmark\" type=\"application/json\">{encoded}</script><script id=\"seeded-reviews\" type=\"application/json\">{seeded}</script><script>
const data=JSON.parse(document.querySelector('#benchmark').textContent),seeded=JSON.parse(document.querySelector('#seeded-reviews').textContent),key='bookinator.chapter-map-reviews.v1';let reviews={{...seeded}};try{{reviews={{...reviews,...JSON.parse(localStorage.getItem(key)||'{{}}')}}}}catch{{}}let filter='all';const esc=s=>String(s??'').replace(/[&<>\"]/g,c=>({{'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;'}}[c]));function save(){{localStorage.setItem(key,JSON.stringify(reviews))}}function render(){{const q=document.querySelector('#search').value.toLowerCase(),items=data.specimens.filter(x=>{{const matchesSearch=!q||JSON.stringify(x).toLowerCase().includes(q),matchesFilter=filter==='all'||(filter==='unreviewed'?!reviews[x.id]?.verdict:x.provisionalTier===filter);return matchesSearch&&matchesFilter}});const counts={{}};for(const x of data.specimens)counts[x.provisionalTier]=(counts[x.provisionalTier]||0)+1;const reviewed=data.specimens.filter(x=>reviews[x.id]?.verdict).length;document.querySelector('#summary').innerHTML=`<div><strong>${{data.specimens.length}}</strong><span>specimens</span></div><div><strong>${{reviewed}}</strong><span>human-reviewed</span></div><div><strong>${{counts['auto-candidate']||0}}</strong><span>spot-check candidates</span></div><div><strong>${{counts['mention-candidate']||0}}</strong><span>mention candidates</span></div><div><strong>${{counts['block-candidate']||0}}</strong><span>inspect first</span></div>`;document.querySelector('#books').innerHTML=items.map(x=>{{const r=reviews[x.id]||{{}};return `<details class=\"book ${{x.provisionalTier}}\"><summary><i class=\"dot\"></i><div><h2>${{esc(x.path)}}</h2><small>${{esc(x.method)}} · ${{x.sourceSpans}} source spans · ${{x.durationMs}} ms</small></div><span class=\"badge\">${{esc(r.verdict||'unreviewed')}}</span><span>${{x.detectedCount}} detected</span><span>${{x.referenceCount}} reference</span></summary><div class=\"review\"><div class=\"columns\"><section><h3>Detected map</h3><ol class=\"headings\">${{x.detected.map(h=>`<li>${{esc(h.title)}}</li>`).join('')}}</ol></section><section><h3>Source navigation</h3><ol class=\"headings\">${{x.referenceHeadings.map(h=>`<li>${{esc(h)}}</li>`).join('')||'<li>Not available</li>'}}</ol></section><section><h3>Signals to inspect</h3><ul>${{[...x.warnings,...x.triageReasons].map(h=>`<li>${{esc(h)}}</li>`).join('')}}</ul></section></div><div class=\"verdicts\"><span>Human judgment</span>${{['pass','mention','block','fail'].map(v=>`<button class=\"verdict-${{v}}\" data-id=\"${{x.id}}\" data-verdict=\"${{v}}\" aria-pressed=\"${{r.verdict===v}}\">${{v[0].toUpperCase()+v.slice(1)}}</button>`).join('')}}</div><textarea data-note=\"${{x.id}}\" placeholder=\"What is right or wrong about this map?\">${{esc(r.note||'')}}</textarea></div></details>`}}).join('')||'<div class=\"empty\">No specimens match this view.</div>';document.querySelectorAll('[data-verdict]').forEach(b=>b.onclick=()=>{{reviews[b.dataset.id]={{...(reviews[b.dataset.id]||{{}}),verdict:b.dataset.verdict,reviewedAt:new Date().toISOString()}};save();render()}});document.querySelectorAll('[data-note]').forEach(t=>t.onchange=()=>{{reviews[t.dataset.note]={{...(reviews[t.dataset.note]||{{}}),note:t.value,reviewedAt:new Date().toISOString()}};save()}})}}document.querySelector('#search').oninput=render;document.querySelectorAll('[data-filter]').forEach(b=>b.onclick=()=>{{filter=b.dataset.filter;document.querySelectorAll('[data-filter]').forEach(x=>x.setAttribute('aria-pressed',x===b));render()}});document.querySelector('#export').onclick=()=>{{const exported=Object.fromEntries(data.specimens.filter(x=>reviews[x.id]).map(x=>[x.id,reviews[x.id]])),blob=new Blob([JSON.stringify({{schema:'bookinator-chapter-map-reviews-v1',benchmarkId:data.id,reviews:exported}},null,2)],{{type:'application/json'}}),a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download='chapter-map-reviews.json';a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000)}};render();
</script></body></html>"""


def run_benchmark(inputs: list[Path], output: Path, limit: int | None = None, reviews_path: Path | None = None) -> dict[str, object]:
    root, files = discover_specimens(inputs)
    if limit is not None:
        files = files[: max(0, limit)]
    specimens = []
    for index, path in enumerate(files, 1):
        print(f"[{index}/{len(files)}] {path}")
        try:
            specimens.append(evaluate_specimen(path, root))
        except Exception as error:  # benchmark failures must remain visible
            specimens.append({"id": hashlib.sha256(str(path).encode()).hexdigest()[:16], "path": str(path), "format": path.suffix.casefold().removeprefix("."), "error": f"{type(error).__name__}: {error}", "provisionalTier": "block-candidate", "warnings": ["The specimen could not be evaluated."], "triageReasons": [str(error)], "detected": [], "detectedCount": 0, "referenceHeadings": [], "referenceCount": 0, "sourceSpans": 0, "durationMs": 0})
    payload = {
        "schema": "bookinator-chapter-map-benchmark-v1",
        "id": hashlib.sha256("".join(str(item.get("sha256") or item["id"]) for item in specimens).encode()).hexdigest()[:16],
        "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "gitRevision": git_revision(Path(__file__).resolve().parents[1]),
        "implementationFingerprint": implementation_fingerprint(Path(__file__).resolve().parents[1]),
        "corpusRoot": str(root),
        "specimens": specimens,
    }
    output.mkdir(parents=True, exist_ok=True)
    (output / "results.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    reviews: dict[str, object] = {}
    if reviews_path:
        imported = json.loads(reviews_path.read_text(encoding="utf-8"))
        if imported.get("schema") != "bookinator-chapter-map-reviews-v1" or not isinstance(imported.get("reviews"), dict):
            raise ValueError("The review file is not a Bookinator chapter-map review export.")
        reviews = imported["reviews"]
    (output / "index.html").write_text(build_report_html(payload, reviews), encoding="utf-8")
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Bookinator's production chapter detector over a review corpus.")
    parser.add_argument("inputs", nargs="+", type=Path, help="Source files or directories to scan recursively")
    parser.add_argument("--output", type=Path, default=Path(".bookinator/benchmarks/chapter-maps"))
    parser.add_argument("--limit", type=int, help="Stable alphabetical subset for smoke tests")
    parser.add_argument("--reviews", type=Path, help="Seed the report with a previously exported human review file")
    args = parser.parse_args(argv)
    payload = run_benchmark(args.inputs, args.output, args.limit, args.reviews)
    tiers: dict[str, int] = {}
    for item in payload["specimens"]:
        tiers[str(item.get("provisionalTier"))] = tiers.get(str(item.get("provisionalTier")), 0) + 1
    print(f"Wrote {len(payload['specimens'])} specimens to {args.output / 'index.html'}")
    print(" · ".join(f"{key}: {value}" for key, value in sorted(tiers.items())))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
