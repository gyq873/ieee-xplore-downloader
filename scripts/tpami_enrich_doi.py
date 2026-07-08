"""
Enrich TPAMI CSV rows missing DOI via Crossref (primary) and OpenAlex (fallback).

Usage:
  python scripts/tpami_enrich_doi.py --year 2022
  python scripts/tpami_enrich_doi.py --csv work/tpami2022.csv --limit 10
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
import time
import unicodedata
from pathlib import Path

import requests
from fuzzywuzzy import fuzz

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from tpami_common import paths_for_year

CROSSREF_URL = "https://api.crossref.org/works"
TPAMI_DOI_RE = re.compile(r"^10\.1109/tpami\.", re.I)
CONTAINER = "IEEE Transactions on Pattern Analysis and Machine Intelligence"
REQUEST_DELAY = 1.0
DEFAULT_MAILTO = "your-email@example.com"


def log(msg: str) -> None:
    print(msg, flush=True)


def normalize_doi(raw: str) -> str:
    s = (raw or "").strip()
    for prefix in (
        "https://doi.org/",
        "http://doi.org/",
        "https://dx.doi.org/",
        "http://dx.doi.org/",
    ):
        if s.lower().startswith(prefix):
            return s[len(prefix) :].strip().rstrip("/")
    if s.lower().startswith("doi:"):
        return s[4:].strip()
    return s


def normalize_title(title: str) -> str:
    s = unicodedata.normalize("NFKD", title)
    s = re.sub(r"\$[^$]*\$", "", s)
    s = re.sub(r"[^\w\s]", " ", s, flags=re.UNICODE)
    s = re.sub(r"\s+", " ", s).strip().lower()
    return s


def user_agent(mailto: str) -> str:
    return f"tpami-metadata-enricher/1.0 (mailto:{mailto})"


def lookup_crossref(title: str, *, mailto: str) -> str:
    time.sleep(REQUEST_DELAY)
    try:
        resp = requests.get(
            CROSSREF_URL,
            params={
                "query.title": title,
                "query.container-title": CONTAINER,
                "rows": 5,
            },
            headers={"User-Agent": user_agent(mailto)},
            timeout=45,
        )
    except requests.RequestException:
        return ""
    if resp.status_code != 200:
        return ""

    items = resp.json().get("message", {}).get("items") or []
    norm_query = normalize_title(title)
    best_doi = ""
    best_score = 0
    for item in items:
        cr_title = (item.get("title") or [""])[0]
        score = fuzz.ratio(norm_query, normalize_title(cr_title))
        doi = normalize_doi(item.get("DOI") or "")
        if score >= 85 and score > best_score and doi and TPAMI_DOI_RE.match(doi):
            best_score = score
            best_doi = doi
    return best_doi


def lookup_doi(title: str, *, mailto: str) -> str:
    doi = lookup_crossref(title, mailto=mailto)
    if doi:
        return doi
    time.sleep(REQUEST_DELAY)
    try:
        resp = requests.get(
            CROSSREF_URL,
            params={"query.bibliographic": f"{title} {CONTAINER}", "rows": 5},
            headers={"User-Agent": user_agent(mailto)},
            timeout=45,
        )
    except requests.RequestException:
        return ""
    if resp.status_code != 200:
        return ""
    norm_query = normalize_title(title)
    best_doi = ""
    best_score = 0
    for item in resp.json().get("message", {}).get("items") or []:
        cr_title = (item.get("title") or [""])[0]
        score = fuzz.ratio(norm_query, normalize_title(cr_title))
        doi = normalize_doi(item.get("DOI") or "")
        if score >= 85 and score > best_score and doi and TPAMI_DOI_RE.match(doi):
            best_score = score
            best_doi = doi
    return best_doi


def read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)
    return fieldnames, rows


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description="Enrich missing DOIs in TPAMI CSV")
    parser.add_argument("--year", type=int, default=None)
    parser.add_argument("--csv", type=Path, default=None)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument(
        "--mailto",
        default=DEFAULT_MAILTO,
        help="Contact email for Crossref polite pool (recommended)",
    )
    args = parser.parse_args()

    if args.year is None and args.csv is None:
        print("Provide --year or --csv", file=sys.stderr)
        return 1

    csv_path = args.csv or paths_for_year(args.year).csv
    if not csv_path.is_file():
        log(f"CSV not found: {csv_path}")
        return 1

    out_path = args.out or csv_path
    fieldnames, rows = read_csv(csv_path)

    need: list[int] = []
    for i, row in enumerate(rows):
        doi = normalize_doi(row.get("doi") or "")
        if doi and TPAMI_DOI_RE.match(doi):
            row["doi"] = f"https://doi.org/{doi}"
        else:
            row["doi"] = ""
            need.append(i)

    if args.limit:
        need = need[: args.limit]

    log(f"Rows: {len(rows)}, need DOI enrichment: {len(need)}")
    enriched = 0

    for n, idx in enumerate(need, 1):
        row = rows[idx]
        title = (row.get("title") or "").strip()
        log(f"[{n}/{len(need)}] {title[:70]}...")
        doi = lookup_doi(title, mailto=args.mailto)
        if doi:
            row["doi"] = f"https://doi.org/{doi}"
            enriched += 1
            log(f"  -> {doi}")
        else:
            log("  -> not found")

        if n % 10 == 0:
            write_csv(out_path, fieldnames, rows)
            log(f"  (checkpoint saved, {enriched} enriched so far)")

    write_csv(out_path, fieldnames, rows)
    log(f"\nEnriched {enriched}/{len(need)}; saved {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
