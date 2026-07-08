"""
Fetch TPAMI metadata from DBLP, convert to TSV, and audit — one command per year.

Usage:
  python -u scripts/tpami_fetch_and_tsv.py --year 2016
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from tpami_common import PROJECT_ROOT


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch DBLP metadata + TSV + audit for one TPAMI year")
    parser.add_argument("--year", type=int, required=True)
    args = parser.parse_args()

    steps = [
        [sys.executable, "-u", str(SCRIPT_DIR / "tpami_fetch_metadata_dblp.py"), "--year", str(args.year)],
        [sys.executable, str(SCRIPT_DIR / "tpami_csv_to_tsv.py"), "--year", str(args.year)],
        [sys.executable, str(SCRIPT_DIR / "tpami_audit_metadata.py"), "--year", str(args.year)],
    ]

    for cmd in steps:
        print(f"\n>>> {' '.join(cmd)}\n", flush=True)
        rc = subprocess.run(cmd, cwd=str(PROJECT_ROOT))
        if rc.returncode != 0 and "audit" not in cmd[1]:
            return rc.returncode

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
