"""Compare DBLP TPAMI volume vs local CSV via DBLP API."""
from __future__ import annotations

import argparse
import csv
import re
import sys
import time
from pathlib import Path

import requests

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from tpami_common import DBLP_API, HEADERS, dblp_toc_query, paths_for_year


def log(msg: str) -> None:
    print(msg, flush=True)


def normalize_title(title: str) -> str:
    s = re.sub(r"\s+", " ", title.strip().lower())
    return re.sub(r"[^\w\s]", "", s)


def extract_doi(info: dict) -> str:
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
            return u.split("doi.org/")[-1].strip("/").lower()
    return ""


def fetch_dblp_from_html(path: Path, year: int) -> list[dict]:
    html = path.read_text(encoding="utf-8", errors="replace")
    titles = re.findall(r'<span class="title"[^>]*>([^<]+)</span>', html)
    if not titles:
        titles = re.findall(r'itemprop="name"[^>]*>([^<]+)<', html)
    dois = re.findall(r"https?://doi\.org/(10\.1109/[^\s\"<>]+)", html, re.I)
    doi_iter = iter(d.lower() for d in dois)
    items: list[dict] = []
    for title in titles:
        title = title.strip()
        if not title:
            continue
        doi = ""
        try:
            doi = next(doi_iter)
        except StopIteration:
            pass
        items.append({"title": title, "doi": doi, "year": str(year), "venue": "TPAMI"})
    return items


def fetch_dblp_volume(volume: int, year: int, html_path: Path) -> list[dict]:
    toc_query = dblp_toc_query(volume)
    page_size = 100
    items: list[dict] = []
    offset = 0
    total: int | None = None

    for attempt in range(20):
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
                time.sleep(30 * (attempt + 1))
                continue
            resp.raise_for_status()
            hits = resp.json()["result"]["hits"]
            if total is None:
                total = int(hits["@total"])
            batch = hits.get("hit") or []
            if not batch:
                break
            for hit in batch:
                info = hit.get("info", {})
                items.append(
                    {
                        "title": (info.get("title") or "").strip(),
                        "doi": extract_doi(info),
                        "year": info.get("year", ""),
                        "venue": info.get("venue", ""),
                    }
                )
            offset = len(items)
            log(f"  DBLP API fetched {offset}/{total}")
            if total is not None and offset >= total:
                break
            time.sleep(0.5)
            attempt = 0
        except requests.RequestException as exc:
            log(f"  DBLP API error at offset {offset}: {exc}")
            time.sleep(2 ** min(attempt, 4))
            continue

    if items:
        return items

    if html_path.is_file():
        log(f"  Falling back to local HTML: {html_path}")
        return fetch_dblp_from_html(html_path, year)
    raise RuntimeError(f"Could not fetch DBLP volume {volume} metadata")


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit TPAMI CSV vs DBLP")
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--csv", type=Path, default=None)
    parser.add_argument("--report", type=Path, default=None)
    args = parser.parse_args()

    p = paths_for_year(args.year)
    csv_path = args.csv or p.csv
    report_path = args.report or p.audit_report

    if not csv_path.is_file():
        log(f"CSV not found: {csv_path}")
        return 1

    log(f"Fetching DBLP volume {p.volume} ({args.year}) via API...")
    dblp = fetch_dblp_volume(p.volume, args.year, p.dblp_html)
    log(f"DBLP entries: {len(dblp)}")
    log(f"DBLP with DOI: {sum(1 for x in dblp if x['doi'])}")

    rows = list(csv.DictReader(csv_path.open(encoding="utf-8-sig")))
    log(f"CSV rows: {len(rows)}")
    log(f"CSV with DOI: {sum(1 for r in rows if (r.get('doi') or '').strip())}")

    def norm_doi(raw: str) -> str:
        s = (raw or "").strip().lower()
        for prefix in ("https://doi.org/", "http://doi.org/"):
            if s.startswith(prefix):
                s = s[len(prefix) :]
        return s.strip("/")

    dblp_dois = {norm_doi(x["doi"]) for x in dblp if x.get("doi")}
    csv_dois = {norm_doi(r.get("doi") or "") for r in rows if (r.get("doi") or "").strip()}

    dblp_by_title = {normalize_title(x["title"]): x for x in dblp if x["title"]}
    csv_by_title = {
        normalize_title(r.get("title") or ""): r for r in rows if r.get("title")
    }

    missing_doi = sorted(dblp_dois - csv_dois)
    extra_doi = sorted(csv_dois - dblp_dois)

    missing = sorted(set(dblp_by_title) - set(csv_by_title))
    extra = sorted(set(csv_by_title) - set(dblp_by_title))

    log(f"\nMissing DOIs in CSV: {len(missing_doi)}")
    log(f"Extra DOIs in CSV: {len(extra_doi)}")
    log(f"Missing titles (title match): {len(missing)}")
    log(f"Extra titles (title match): {len(extra)}")

    lines = [
        f"# TPAMI {args.year} Metadata Audit",
        "",
        f"DBLP volume {p.volume} ({args.year}) entries: **{len(dblp)}**",
        f"Local `{csv_path.name}` rows: **{len(rows)}**",
        f"Gap (DBLP − CSV): **{len(dblp) - len(rows)}**",
        "",
        f"- Missing DOIs in CSV: **{len(missing_doi)}**",
        f"- Extra DOIs in CSV: **{len(extra_doi)}**",
        f"- Missing titles (fuzzy title match): **{len(missing)}**",
        f"- Extra titles (fuzzy title match): **{len(extra)}**",
        "",
        "## Missing DOIs (first 30)",
        "",
    ]
    for doi in missing_doi[:30]:
        lines.append(f"- `{doi}`")
    if len(missing_doi) > 30:
        lines.append(f"- ... and {len(missing_doi) - 30} more")

    if extra_doi:
        lines.extend(["", "## Extra DOIs (first 30)", ""])
        for doi in extra_doi[:30]:
            lines.append(f"- `{doi}`")

    if missing and not missing_doi:
        lines.extend(["", "## Missing titles (title-normalization only, first 20)", ""])
        for t in missing[:20]:
            item = dblp_by_title[t]
            lines.append(f"- {item['title'][:120]} | `{item['doi'] or 'no doi'}`")

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    log(f"\nReport: {report_path}")

    return 1 if missing_doi or extra_doi else 0


if __name__ == "__main__":
    raise SystemExit(main())
