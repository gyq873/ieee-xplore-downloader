"""
Download TPAMI PDFs from IEEE Xplore for any calendar year.

Usage:
  python scripts/tpami_download_pdfs.py --year 2024 --resume
  python scripts/tpami_download_pdfs.py --year 2016 --limit 5 --resume
"""
from __future__ import annotations

import argparse
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from xplore_download import (
    DEFAULT_PDF_REQUEST_TIMEOUT_MS,
    USER_AGENT,
    arnumber_from_state,
    download_pdf_playwright,
    netscape_to_playwright,
)
from tpami_common import (
    COOLDOWN_SECONDS,
    DEFAULT_COOKIES,
    MissingItem,
    append_jsonl,
    is_valid_pdf,
    load_jsonl_state,
    load_tsv,
    paths_for_year,
    utc_now_iso,
)

BOT_BLOCK_RE = re.compile(
    r"captcha|bot detection|access denied|too many requests|rate limit|"
    r"unusual traffic|please try again|challenge-platform|temporarily unavailable|"
    r"apm_do_not_touch",
    re.I,
)
CONSECUTIVE_FAIL_THRESHOLD = 3
IMMEDIATE_COOLDOWN_MARKERS = (
    "temporarily unavailable",
    "too many requests",
    "429",
    "http 420",
)
TIMEOUT_FAIL_THRESHOLD = 5


def log(msg: str) -> None:
    print(msg, flush=True)


def short_error(exc: Exception) -> str:
    msg = str(exc).replace("\r", " ").replace("\n", " ")
    low = msg.lower()
    if "temporarily unavailable" in low:
        return "IEEE Xplore temporarily unavailable"
    if "not pdf" in low and BOT_BLOCK_RE.search(msg):
        return "IEEE returned HTML (bot/WAF block)"
    if "not pdf" in low:
        return "Response is not PDF"
    if "timeout" in low and "exceeded" in low:
        return "PDF download timeout"
    if len(msg) > 120:
        return msg[:117] + "..."
    return msg


def should_process(item: MissingItem, out_path: Path, *, resume: bool) -> bool:
    if resume and is_valid_pdf(out_path):
        return False
    return True


def needs_immediate_cooldown(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(m in msg for m in IMMEDIATE_COOLDOWN_MARKERS)


def is_timeout_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return "timeout" in msg and "exceeded" in msg


def classify_failure(exc: Exception) -> tuple[str, bool]:
    err_str = str(exc)
    body_snippet = err_str if "not PDF" in err_str else ""
    if needs_immediate_cooldown(exc):
        return "rate_limited", True
    if is_timeout_error(exc):
        return "timeout", False
    if is_rate_limited_error(exc, body_snippet):
        if "not pdf" in err_str.lower() and BOT_BLOCK_RE.search(body_snippet):
            return "not_pdf", True
        return "rate_limited", True
    if "not PDF" in err_str:
        return "not_pdf", True
    return "failed", True


def maybe_cooldown(
    *,
    consecutive_fails: int,
    consecutive_timeouts: int,
    threshold: int,
    cooldown_seconds: int,
    state_path: Path,
    reason: str,
) -> tuple[int, int]:
    if consecutive_fails < threshold:
        return consecutive_fails, consecutive_timeouts
    cooldown_until = (
        datetime.now(timezone.utc) + timedelta(seconds=cooldown_seconds)
    ).isoformat()
    append_jsonl(
        state_path,
        {
            "event": "cooldown",
            "reason": reason,
            "cooldown_until": cooldown_until,
            "ts": utc_now_iso(),
        },
    )
    cooldown_sleep(cooldown_seconds, reason)
    return 0, 0


def is_rate_limited_error(exc: Exception, body_snippet: str = "") -> bool:
    if needs_immediate_cooldown(exc):
        return True
    msg = str(exc).lower()
    if "429" in msg or "too many" in msg:
        return True
    if "403" in msg and "auth" not in msg:
        return True
    if body_snippet and BOT_BLOCK_RE.search(body_snippet):
        return True
    if "not pdf" in msg and body_snippet and BOT_BLOCK_RE.search(body_snippet):
        return True
    return False


def cooldown_sleep(seconds: int, reason: str) -> None:
    until = datetime.now(timezone.utc) + timedelta(seconds=seconds)
    log(f"\n*** {reason} ***")
    log(f"Waiting {seconds // 60} minutes until {until.isoformat()} ...")
    time.sleep(seconds)
    log("Resuming downloads.\n")


def count_pending(items: list[MissingItem], out_dir: Path, *, resume: bool) -> int:
    return sum(
        1
        for item in items
        if should_process(item, out_dir / f"{item.item_key}.pdf", resume=resume)
    )


def run_playwright_downloads(
    items: list[MissingItem],
    *,
    year: int,
    cookies_path: Path,
    out_dir: Path,
    state_path: Path,
    delay: float,
    limit: int,
    resume: bool,
    cooldown_seconds: int,
    consecutive_fail_threshold: int,
    pdf_timeout_ms: int,
) -> tuple[int, int, int, int]:
    from playwright.sync_api import sync_playwright

    processed = success = skipped = failed = 0
    consecutive_fails = 0
    consecutive_timeouts = 0
    pending_total = count_pending(items, out_dir, resume=resume)
    state = load_jsonl_state(state_path)
    pw_cookies = netscape_to_playwright(cookies_path)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(user_agent=USER_AGENT)
        context.set_default_timeout(pdf_timeout_ms)
        if pw_cookies:
            context.add_cookies(pw_cookies)
        page = context.new_page()

        for item in items:
            out_path = out_dir / f"{item.item_key}.pdf"
            if not should_process(item, out_path, resume=resume):
                skipped += 1
                continue
            if limit and processed >= limit:
                break

            processed += 1
            log(f"[TPAMI{year} {processed}/{pending_total}] {item.item_key}  {item.doi}")
            record: dict = {
                "item_key": item.item_key,
                "doi": item.doi,
                "title": item.title,
                "ts": utc_now_iso(),
                "engine": "playwright",
            }
            cached_arnumber = arnumber_from_state(state, item.item_key)
            meta: dict = {}

            try:
                nbytes, resolved_arnumber = download_pdf_playwright(
                    page,
                    item.doi,
                    out_path,
                    arnumber=cached_arnumber,
                    pdf_timeout_ms=pdf_timeout_ms,
                    meta=meta,
                )
                record.update({
                    "status": "success",
                    "path": str(out_path),
                    "bytes": nbytes,
                    "arnumber": resolved_arnumber,
                })
                state[item.item_key] = record
                success += 1
                consecutive_fails = 0
                consecutive_timeouts = 0
                log(f"  OK {nbytes:,} bytes -> {out_path.name}")
            except PermissionError as exc:
                consecutive_fails += 1
                status = "auth_failed"
                err_str = str(exc)
                if "403" in err_str and consecutive_fails >= consecutive_fail_threshold:
                    status = "rate_limited"
                record.update({"status": status, "error": err_str})
                failed += 1
                log(f"  FAIL ({status}): {short_error(exc)}")
                append_jsonl(state_path, record)
                consecutive_fails, consecutive_timeouts = maybe_cooldown(
                    consecutive_fails=consecutive_fails,
                    consecutive_timeouts=consecutive_timeouts,
                    threshold=consecutive_fail_threshold,
                    cooldown_seconds=cooldown_seconds,
                    state_path=state_path,
                    reason=f"IEEE limit detected ({status})",
                )
                time.sleep(delay)
                continue
            except Exception as exc:
                status, counts_toward_cooldown = classify_failure(exc)
                err_str = str(exc)
                record.update({"status": status, "error": err_str})
                if meta.get("arnumber"):
                    record["arnumber"] = meta["arnumber"]
                    state[item.item_key] = {"arnumber": meta["arnumber"]}
                failed += 1
                log(f"  FAIL ({status}): {short_error(exc)}")
                append_jsonl(state_path, record)

                if status == "timeout":
                    consecutive_timeouts += 1
                    consecutive_fails = 0
                    if consecutive_timeouts >= TIMEOUT_FAIL_THRESHOLD:
                        consecutive_fails, consecutive_timeouts = maybe_cooldown(
                            consecutive_fails=TIMEOUT_FAIL_THRESHOLD,
                            consecutive_timeouts=consecutive_timeouts,
                            threshold=consecutive_fail_threshold,
                            cooldown_seconds=cooldown_seconds,
                            state_path=state_path,
                            reason=f"{consecutive_timeouts} consecutive PDF timeouts — pausing",
                        )
                elif counts_toward_cooldown:
                    consecutive_fails += 1
                    consecutive_timeouts = 0
                    consecutive_fails, consecutive_timeouts = maybe_cooldown(
                        consecutive_fails=consecutive_fails,
                        consecutive_timeouts=consecutive_timeouts,
                        threshold=consecutive_fail_threshold,
                        cooldown_seconds=cooldown_seconds,
                        state_path=state_path,
                        reason=(
                            f"{consecutive_fails} consecutive failures — "
                            "IEEE rate limit suspected"
                        ),
                    )
                else:
                    consecutive_fails += 1
                    consecutive_timeouts = 0

                time.sleep(delay)
                continue

            append_jsonl(state_path, record)
            time.sleep(delay)

        browser.close()

    return processed, success, skipped, failed


def main() -> int:
    parser = argparse.ArgumentParser(description="Download TPAMI PDFs from IEEE Xplore")
    parser.add_argument("--year", type=int, required=True, help="Calendar year, e.g. 2024")
    parser.add_argument("--tsv", type=Path, default=None)
    parser.add_argument("--out-dir", type=Path, default=None)
    parser.add_argument("--cookies", type=Path, default=DEFAULT_COOKIES)
    parser.add_argument("--state", type=Path, default=None)
    parser.add_argument("--delay", type=float, default=6.0)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--cooldown-seconds", type=int, default=COOLDOWN_SECONDS)
    parser.add_argument("--fail-threshold", type=int, default=CONSECUTIVE_FAIL_THRESHOLD)
    parser.add_argument("--pdf-timeout-ms", type=int, default=DEFAULT_PDF_REQUEST_TIMEOUT_MS)
    parser.add_argument("--engine", choices=("playwright",), default="playwright")
    args = parser.parse_args()

    p = paths_for_year(args.year)
    tsv = args.tsv or p.tsv
    out_dir = args.out_dir or p.pdf_dir
    state_path = args.state or p.download_state

    if not tsv.is_file():
        print(f"TSV not found: {tsv}", file=sys.stderr)
        print(f"Run: python scripts/tpami_csv_to_tsv.py --year {args.year}", file=sys.stderr)
        return 1
    if not args.cookies.is_file():
        print(f"Cookie file not found: {args.cookies}", file=sys.stderr)
        return 1

    items = load_tsv(tsv)
    pending = count_pending(items, out_dir, resume=args.resume)
    done = len(items) - pending
    log(f"TPAMI {args.year} — total: {len(items)}, downloaded: {done}, pending: {pending}")
    log(f"Output: {out_dir}")

    if pending == 0:
        log("Nothing to download.")
        return 0

    out_dir.mkdir(parents=True, exist_ok=True)

    processed, success, skipped, failed = run_playwright_downloads(
        items,
        year=args.year,
        cookies_path=args.cookies,
        out_dir=out_dir,
        state_path=state_path,
        delay=args.delay,
        limit=args.limit,
        resume=args.resume,
        cooldown_seconds=args.cooldown_seconds,
        consecutive_fail_threshold=args.fail_threshold,
        pdf_timeout_ms=args.pdf_timeout_ms,
    )

    remaining = count_pending(items, out_dir, resume=True)
    done = len(items) - remaining
    log(f"\nRound done — processed: {processed}, success: {success}, skipped: {skipped}, failed: {failed}")
    log(f"Overall: {done}/{len(items)} downloaded, {remaining} remaining")

    if remaining == 0:
        return 0
    return 2 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
