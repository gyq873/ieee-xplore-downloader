"""
Fetch TPAMI metadata from DBLP for a calendar year (volume = year - 1978).

Usage:
  python scripts/tpami_fetch_metadata_dblp.py --year 2024
  python scripts/tpami_fetch_metadata_dblp.py --year 2016 --html work/dblp_pami38.html
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
import time
from html import unescape
from pathlib import Path

import requests

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from tpami_common import (
    CSV_FIELDS,
    DBLP_API,
    HEADERS,
    conf_tag,
    dblp_toc_query,
    dblp_volume_url,
    paths_for_year,
    utc_now_iso,
)


def log(msg: str) -> None:
    print(msg, flush=True)


def extract_doi_from_info(info: dict) -> str:
    ee = info.get("ee")
    urls: list[str]
    if ee is None:
        return ""
    if isinstance(ee, list):
        urls = [str(u) for u in ee]
    else:
        urls = [str(ee)]
    for u in urls:
        if "doi.org/" in u.lower():
            return "https://doi.org/" + u.split("doi.org/")[-1].strip("/")
    return ""


def fetch_from_api(volume: int) -> tuple[list[dict], int | None]:
    toc_query = dblp_toc_query(volume)
    page_size = 100
    items: list[dict] = []
    total: int | None = None
    offset = 0

    while True:
        for attempt in range(8):
            try:
                resp = requests.get(
                    DBLP_API,
                    params={
                        "q": toc_query,
                        "h": page_size,
                        "f": offset,
                        "format": "json",
                    },
                    headers=HEADERS,
                    timeout=120,
                )
                if resp.status_code == 429:
                    wait = 30 * (attempt + 1)
                    log(f"  DBLP API 429, waiting {wait}s...")
                    time.sleep(wait)
                    continue
                resp.raise_for_status()
                hits = resp.json()["result"]["hits"]
                if total is None:
                    total = int(hits["@total"])
                batch = hits.get("hit") or []
                if not batch:
                    return items, total
                for hit in batch:
                    info = hit.get("info", {})
                    authors_raw = info.get("authors", {}).get("author", [])
                    if isinstance(authors_raw, str):
                        authors = authors_raw
                    else:
                        authors = ",".join(
                            a if isinstance(a, str) else a.get("text", "")
                            for a in (authors_raw or [])
                        )
                    items.append(
                        {
                            "title": unescape((info.get("title") or "").strip()),
                            "authors": authors,
                            "doi": extract_doi_from_info(info),
                        }
                    )
                offset = len(items)
                log(f"  DBLP API: {offset}/{total}")
                if total is not None and offset >= total:
                    return items, total
                time.sleep(0.6)
                break
            except requests.RequestException as exc:
                wait = min(60, 5 * (2 ** attempt))
                log(f"  API retry ({attempt + 1}/8), wait {wait}s: {exc}")
                time.sleep(wait)
        else:
            break
    return items, total


def fetch_from_html(path: Path) -> list[dict]:
    html = path.read_text(encoding="utf-8", errors="replace")
    blocks = re.split(r'<li[^>]*class="[^"]*entry[^"]*"[^>]*>', html, flags=re.I)
    items: list[dict] = []
    seen_doi: set[str] = set()

    for block in blocks[1:]:
        tm = re.search(r'<span class="title"[^>]*>([^<]+)</span>', block)
        dm = re.search(r"https?://doi\.org/(10\.1109/[^\s\"<>]+)", block, re.I)
        if not dm:
            continue
        doi = "https://doi.org/" + dm.group(1).lower().strip("/")
        if doi in seen_doi:
            continue
        seen_doi.add(doi)
        title = unescape(tm.group(1).strip()) if tm else ""
        authors = ",".join(
            unescape(a.strip())
            for a in re.findall(
                r'<span itemprop="name"[^>]*>([^<]+)</span>',
                block,
            )
        )
        items.append({"title": title, "authors": authors, "doi": doi})

    for doi_path in re.findall(r"https?://doi\.org/(10\.1109/[^\s\"<>]+)", html, re.I):
        doi = "https://doi.org/" + doi_path.lower().strip("/")
        if doi in seen_doi:
            continue
        seen_doi.add(doi)
        items.append({"title": "", "authors": "", "doi": doi})
    return items


def download_html(volume: int, dest: Path) -> Path:
    url = dblp_volume_url(volume)
    log(f"Downloading {url} ...")
    for attempt in range(6):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=180)
            resp.raise_for_status()
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(resp.text, encoding="utf-8")
            return dest
        except requests.RequestException as exc:
            wait = min(60, 5 * (2 ** attempt))
            log(f"  HTML retry ({attempt + 1}/6), wait {wait}s: {exc}")
            time.sleep(wait)
    raise requests.RequestException(f"Failed to download {url}")


def merge_old_fields(
    old_rows: list[dict],
    new_rows: list[dict],
    *,
    year: int,
) -> list[dict]:
    by_doi = {}
    for row in old_rows:
        doi = (row.get("doi") or "").strip().lower()
        if doi:
            by_doi[doi] = row

    tag = conf_tag(year)
    merged: list[dict] = []
    for row in new_rows:
        doi = (row.get("doi") or "").strip().lower()
        prev = by_doi.get(doi, {})
        merged.append(
            {
                "conf": tag,
                "matched_queries": prev.get("matched_queries", ""),
                "title": row.get("title") or prev.get("title", ""),
                "citation_count": prev.get("citation_count", ""),
                "abstract": prev.get("abstract", ""),
                "categories": prev.get("categories", ""),
                "concepts": prev.get("concepts", ""),
                "code_url": prev.get("code_url", ""),
                "pdf_url": prev.get("pdf_url", ""),
                "authors": row.get("authors") or prev.get("authors", ""),
                "doi": row.get("doi") or prev.get("doi", ""),
            }
        )
    return merged


def write_report(
    path: Path,
    *,
    year: int,
    volume: int,
    total: int,
    with_doi: int,
    old_count: int,
    added: int,
    out_csv: Path,
    api_total: int | None,
) -> None:
    lines = [
        f"# TPAMI {year} Metadata Report (DBLP refresh)",
        "",
        f"Generated: {utc_now_iso()}",
        "",
        "## Summary",
        "",
        f"- Calendar year: **{year}**",
        f"- DBLP volume: **{volume}** (`pami{volume}.html`)",
        f"- DBLP API total: **{api_total if api_total is not None else 'n/a'}**",
        f"- CSV entries written: **{total}**",
        f"- With DOI: **{with_doi}**",
        f"- Previous CSV rows: **{old_count}**",
        f"- Newly added: **{added}**",
        f"- Output CSV: `{out_csv}`",
        "",
        f"Note: IEEE/DBLP **Volume {volume} ({year} issue)** may include articles",
        "whose DOI year precedes the calendar year (early access).",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch TPAMI metadata from DBLP by year")
    parser.add_argument("--year", type=int, required=True, help="Calendar year, e.g. 2024")
    parser.add_argument("--out", type=Path, default=None, help="Output CSV path")
    parser.add_argument("--html", type=Path, default=None, help="Use cached DBLP HTML")
    parser.add_argument("--report", type=Path, default=None, help="Metadata report path")
    args = parser.parse_args()

    p = paths_for_year(args.year)
    out_csv = args.out or p.csv
    report_path = args.report or p.metadata_report
    html_path = args.html or p.dblp_html
    volume = p.volume

    old_rows: list[dict] = []
    if out_csv.is_file():
        old_rows = list(csv.DictReader(out_csv.open(encoding="utf-8-sig")))

    items: list[dict] = []
    api_total: int | None = None
    try:
        log(f"Fetching TPAMI {args.year} (DBLP volume {volume}) via API...")
        items, api_total = fetch_from_api(volume)
        log(f"API returned {len(items)} items (total={api_total})")
    except Exception as exc:
        log(f"API failed: {exc}")

    need_html = not items
    if api_total and items and len(items) < int(api_total * 0.9):
        need_html = True
        log(f"API incomplete ({len(items)}/{api_total}), trying HTML fallback...")

    if need_html:
        if not html_path.is_file():
            try:
                html_path = download_html(volume, html_path)
            except Exception as exc:
                log(f"HTML download failed: {exc}")
                if not items:
                    return 1
        if html_path.is_file():
            log(f"Parsing HTML: {html_path}")
            html_items = fetch_from_html(html_path)
            if len(html_items) > len(items):
                items = html_items
                log(f"HTML parsed {len(items)} items")

    if not items:
        log("No metadata fetched.", file=sys.stderr)
        return 1

    items.sort(key=lambda x: (x.get("doi") or "", x.get("title") or ""))
    merged = merge_old_fields(old_rows, items, year=args.year)
    old_dois = {
        (r.get("doi") or "").strip().lower()
        for r in old_rows
        if (r.get("doi") or "").strip()
    }
    new_dois = {
        (r.get("doi") or "").strip().lower()
        for r in merged
        if (r.get("doi") or "").strip()
    }
    added = len(new_dois - old_dois)

    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with out_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(merged)

    write_report(
        report_path,
        year=args.year,
        volume=volume,
        total=len(merged),
        with_doi=sum(1 for r in merged if (r.get("doi") or "").strip()),
        old_count=len(old_rows),
        added=added,
        out_csv=out_csv,
        api_total=api_total,
    )

    log(f"Wrote {len(merged)} rows -> {out_csv}")
    log(f"Added {added} new DOIs vs previous CSV")
    log(f"Report: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
