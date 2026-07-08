"""
Outer loop for TPAMI PDF download by calendar year.

Usage:
  python scripts/tpami_run_download.py --year 2024
  python scripts/tpami_run_download.py --year 2016 --delay 8
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from xplore_download import DEFAULT_PDF_REQUEST_TIMEOUT_MS
from tpami_common import COOLDOWN_SECONDS, DEFAULT_COOKIES, PROJECT_ROOT, MissingItem, is_valid_pdf, load_tsv, paths_for_year

DOWNLOAD_SCRIPT = SCRIPT_DIR / "tpami_download_pdfs.py"


def log(msg: str) -> None:
    print(msg, flush=True)


def count_pending(items: list[MissingItem], out_dir: Path) -> int:
    return sum(
        1
        for item in items
        if not is_valid_pdf(out_dir / f"{item.item_key}.pdf")
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Run TPAMI PDF download until complete")
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--tsv", type=Path, default=None)
    parser.add_argument("--out-dir", type=Path, default=None)
    parser.add_argument("--cookies", type=Path, default=DEFAULT_COOKIES)
    parser.add_argument("--delay", type=float, default=6.0)
    parser.add_argument("--pdf-timeout-ms", type=int, default=DEFAULT_PDF_REQUEST_TIMEOUT_MS)
    parser.add_argument("--cooldown-seconds", type=int, default=COOLDOWN_SECONDS)
    parser.add_argument("--max-rounds", type=int, default=100)
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    p = paths_for_year(args.year)
    tsv = args.tsv or p.tsv
    out_dir = args.out_dir or p.pdf_dir

    if not tsv.is_file():
        print(f"TSV not found: {tsv}", file=sys.stderr)
        print(f"Run: python scripts/tpami_csv_to_tsv.py --year {args.year}", file=sys.stderr)
        return 1
    if not args.cookies.is_file():
        print(f"Cookie file not found: {args.cookies}", file=sys.stderr)
        return 1

    items = load_tsv(tsv)
    out_dir.mkdir(parents=True, exist_ok=True)

    for round_num in range(1, args.max_rounds + 1):
        pending = count_pending(items, out_dir)
        if pending == 0:
            log(f"All {len(items)} TPAMI {args.year} papers downloaded.")
            return 0

        done = len(items) - pending
        log(f"\n=== TPAMI {args.year} Round {round_num}/{args.max_rounds}: {done}/{len(items)} done, {pending} pending ===\n")

        cmd = [
            sys.executable,
            "-u",
            str(DOWNLOAD_SCRIPT),
            "--year",
            str(args.year),
            "--resume",
            "--engine",
            "playwright",
            "--tsv",
            str(tsv),
            "--out-dir",
            str(out_dir),
            "--cookies",
            str(args.cookies),
            "--delay",
            str(args.delay),
            "--pdf-timeout-ms",
            str(args.pdf_timeout_ms),
            "--cooldown-seconds",
            str(args.cooldown_seconds),
            "--state",
            str(p.download_state),
        ]
        if args.limit:
            cmd.extend(["--limit", str(args.limit)])

        rc = subprocess.run(cmd, cwd=str(PROJECT_ROOT))
        pending_after = count_pending(items, out_dir)

        if pending_after == 0:
            log(f"\nComplete: all {len(items)} TPAMI {args.year} papers downloaded.")
            return 0

        gained = pending - pending_after
        if rc.returncode == 0:
            log(f"\nRound {round_num} finished; +{gained} this round, {pending_after} still pending.")
            if pending_after == pending:
                log("No progress this round — waiting 20 minutes before retry...")
                time.sleep(args.cooldown_seconds)
            continue

        log(f"\nRound {round_num} exit code {rc.returncode}; +{gained} this round, {pending_after} pending.")
        if pending_after < pending:
            continue
        log("Waiting 20 minutes before next round...")
        time.sleep(args.cooldown_seconds)

    pending_final = count_pending(items, out_dir)
    print(f"\nStopped after {args.max_rounds} rounds; {pending_final} still pending.", file=sys.stderr)
    return 1 if pending_final else 0


if __name__ == "__main__":
    raise SystemExit(main())
