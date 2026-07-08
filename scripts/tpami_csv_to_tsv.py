"""
Convert TPAMI CSV to download TSV + metadata report.

Usage:
  python scripts/tpami_csv_to_tsv.py --year 2024
  python scripts/tpami_csv_to_tsv.py --csv work/tpami2020.csv
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from tpami_common import MissingItem, paths_for_year, utc_now_iso, write_tsv

DOI_PREFIXES = ("https://doi.org/", "http://doi.org/", "https://dx.doi.org/", "http://dx.doi.org/")
TPAMI_DOI_RE = re.compile(r"^10\.1109/tpami\.", re.I)
INVALID_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*]')


def normalize_doi(raw: str) -> str:
    s = (raw or "").strip()
    for prefix in DOI_PREFIXES:
        if s.lower().startswith(prefix.lower()):
            s = s[len(prefix) :]
            break
    if s.lower().startswith("doi:"):
        s = s[4:].strip()
    return s.strip().rstrip("/")


def doi_to_item_key(doi: str) -> str:
    safe = doi.replace("/", "_")
    return INVALID_FILENAME_CHARS.sub("_", safe)


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def main() -> int:
    parser = argparse.ArgumentParser(description="Convert TPAMI CSV to download TSV")
    parser.add_argument("--year", type=int, default=None, help="Calendar year")
    parser.add_argument("--csv", type=Path, default=None)
    parser.add_argument("--tsv", type=Path, default=None)
    parser.add_argument("--report", type=Path, default=None)
    args = parser.parse_args()

    if args.year is None and args.csv is None:
        print("Provide --year or --csv", file=sys.stderr)
        return 1

    if args.year is not None:
        p = paths_for_year(args.year)
        csv_path = args.csv or p.csv
        tsv_path = args.tsv or p.tsv
        report_path = args.report or p.metadata_report
        year_label = str(args.year)
    else:
        csv_path = args.csv
        tsv_path = args.tsv or csv_path.with_name(csv_path.stem + "_papers.tsv")
        report_path = args.report or csv_path.with_name(csv_path.stem + "_metadata_report.md")
        year_label = csv_path.stem.replace("tpami", "")

    if not csv_path.is_file():
        print(f"CSV not found: {csv_path}", file=sys.stderr)
        return 1

    rows = read_csv_rows(csv_path)
    total = len(rows)
    seen_dois: set[str] = set()
    items: list[MissingItem] = []
    no_doi: list[tuple[str, str, str]] = []
    filtered_out: list[tuple[str, str]] = []

    for row in rows:
        title = (row.get("title") or "").replace("\t", " ").strip()
        conf = (row.get("conf") or "").strip()
        doi = normalize_doi(row.get("doi") or "")
        if not doi:
            no_doi.append((conf, title, row.get("authors") or ""))
            continue
        if not TPAMI_DOI_RE.match(doi):
            filtered_out.append((doi, title))
            continue
        if doi in seen_dois:
            continue
        seen_dois.add(doi)
        items.append(MissingItem(doi_to_item_key(doi), title, doi))

    write_tsv(tsv_path, items)

    lines = [
        f"# TPAMI {year_label} Metadata Report",
        "",
        f"Generated: {utc_now_iso()}",
        "",
        "## Summary",
        "",
        f"- Source CSV: `{csv_path}`",
        f"- Total rows in CSV: **{total}**",
        f"- Papers with valid TPAMI DOI: **{len(items)}**",
        f"- Missing DOI: **{len(no_doi)}**",
        f"- Filtered out (non-TPAMI DOI): **{len(filtered_out)}**",
        f"- Output TSV: `{tsv_path}`",
        "",
    ]

    if no_doi:
        lines.extend(["## Missing DOI", ""])
        for conf, title, authors in no_doi[:50]:
            lines.append(f"- `{conf}` | {title[:100]} | {authors[:60]}")
        if len(no_doi) > 50:
            lines.append(f"- ... and {len(no_doi) - 50} more")
        lines.append("")

    if filtered_out:
        lines.extend(["## Filtered DOI (not 10.1109/tpami.*)", ""])
        for doi, title in filtered_out[:30]:
            lines.append(f"- `{doi}` | {title[:80]}")
        if len(filtered_out) > 30:
            lines.append(f"- ... and {len(filtered_out) - 30} more")
        lines.append("")

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"CSV rows: {total}, valid DOI: {len(items)}, no DOI: {len(no_doi)}")
    print(f"TSV: {tsv_path}")
    print(f"Report: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
