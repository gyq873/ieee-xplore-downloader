"""Shared utilities for IEEE Xplore download pipelines."""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORK_DIR = PROJECT_ROOT / "work"
CONFIG_DIR = PROJECT_ROOT / "config"
PAPERS_DIR = PROJECT_ROOT / "papers"
DEFAULT_COOKIES = CONFIG_DIR / "ieee_cookies.txt"


@dataclass(frozen=True)
class MissingItem:
    item_key: str
    title: str
    doi: str


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def load_tsv(path: Path) -> list[MissingItem]:
    items: list[MissingItem] = []
    text = path.read_text(encoding="utf-8")
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split("\t")
        if len(parts) < 3:
            raise ValueError(f"Invalid TSV line: {line[:120]}")
        items.append(MissingItem(parts[0], parts[1], parts[2]))
    return items


def write_tsv(path: Path, items: list[MissingItem]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"{it.item_key}\t{it.title}\t{it.doi}" for it in items]
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def append_jsonl(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def load_jsonl_state(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    latest: dict[str, dict] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        rec = json.loads(line)
        key = rec.get("item_key")
        if key:
            latest[key] = rec
    return latest


def iter_jsonl(path: Path) -> Iterator[dict]:
    if not path.exists():
        return iter(())

    def _gen():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                yield json.loads(line)

    return _gen()


def is_valid_pdf(path: Path, min_bytes: int = 10_000) -> bool:
    if not path.is_file():
        return False
    if path.stat().st_size < min_bytes:
        return False
    with path.open("rb") as f:
        return f.read(5) == b"%PDF-"
