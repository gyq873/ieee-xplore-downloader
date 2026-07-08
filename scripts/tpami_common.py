"""Shared utilities for TPAMI metadata and PDF download pipelines."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ieee_common import (
    MissingItem,
    PAPERS_DIR,
    PROJECT_ROOT,
    WORK_DIR,
    append_jsonl,
    is_valid_pdf,
    iter_jsonl,
    load_jsonl_state,
    load_tsv,
    utc_now_iso,
    write_tsv,
)

DEFAULT_COOKIES = PROJECT_ROOT / "config" / "ieee_cookies.txt"
COOLDOWN_SECONDS = 1200  # 20 minutes

CSV_FIELDS = [
    "conf",
    "matched_queries",
    "title",
    "citation_count",
    "abstract",
    "categories",
    "concepts",
    "code_url",
    "pdf_url",
    "authors",
    "doi",
]

DBLP_API = "https://dblp.org/search/publ/api"
DBLP_BASE = "https://dblp.org/db/journals/pami"
HEADERS = {"User-Agent": "Mozilla/5.0 (tpami-metadata/1.0)"}


def volume_for_year(year: int) -> int:
    return year - 1978


def conf_tag(year: int) -> str:
    return f"TPAMI{year}"


@dataclass(frozen=True)
class TpamiYearPaths:
    year: int
    volume: int
    csv: Path
    tsv: Path
    metadata_report: Path
    audit_report: Path
    dblp_html: Path
    pdf_dir: Path
    download_state: Path
    download_log: Path


def paths_for_year(year: int) -> TpamiYearPaths:
    vol = volume_for_year(year)
    return TpamiYearPaths(
        year=year,
        volume=vol,
        csv=WORK_DIR / f"tpami{year}.csv",
        tsv=WORK_DIR / f"tpami{year}_papers.tsv",
        metadata_report=WORK_DIR / f"tpami{year}_metadata_report.md",
        audit_report=WORK_DIR / f"tpami{year}_metadata_audit.md",
        dblp_html=WORK_DIR / f"dblp_pami{vol}.html",
        pdf_dir=PAPERS_DIR / "tpami" / str(year),
        download_state=WORK_DIR / f"tpami{year}_download_state.jsonl",
        download_log=WORK_DIR / f"tpami{year}_download.log",
    )


def dblp_volume_url(volume: int) -> str:
    return f"{DBLP_BASE}/pami{volume}.html"


def dblp_toc_query(volume: int) -> str:
    return f"toc:db/journals/pami/pami{volume}.bht:"


__all__ = [
    "COOLDOWN_SECONDS",
    "CSV_FIELDS",
    "DBLP_API",
    "DBLP_BASE",
    "DEFAULT_COOKIES",
    "HEADERS",
    "MissingItem",
    "PROJECT_ROOT",
    "TpamiYearPaths",
    "WORK_DIR",
    "append_jsonl",
    "conf_tag",
    "dblp_toc_query",
    "dblp_volume_url",
    "is_valid_pdf",
    "iter_jsonl",
    "load_jsonl_state",
    "load_tsv",
    "paths_for_year",
    "utc_now_iso",
    "volume_for_year",
    "write_tsv",
]
