"""
Download PDFs from IEEE Xplore using institutional cookies.

Supports httpx (fast) and Playwright (bypasses bot checks).

Usage:
  python scripts/xplore_download.py --tsv work/papers.tsv --out-dir papers/custom --resume
  python scripts/xplore_download.py --tsv work/papers.tsv --limit 5 --engine playwright --resume
"""
from __future__ import annotations

import argparse
import http.cookiejar
import re
import sys
import time
from pathlib import Path

import httpx

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from ieee_common import (
    DEFAULT_COOKIES,
    MissingItem,
    append_jsonl,
    is_valid_pdf,
    load_jsonl_state,
    load_tsv,
    utc_now_iso,
)

IEEE_DOC_RE = re.compile(r"ieeexplore\.ieee\.org/document/(\d+)", re.I)
MIN_PDF_BYTES = 10_000
DEFAULT_PDF_REQUEST_TIMEOUT_MS = 180_000
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


def load_cookie_jar(path: Path) -> httpx.Cookies:
    if not path.is_file():
        raise FileNotFoundError(
            f"Cookie file not found: {path}\n"
            "Export Netscape cookies from IEEE Xplore to config/ieee_cookies.txt\n"
            "See config/ieee_cookies.example.txt for instructions."
        )
    jar = http.cookiejar.MozillaCookieJar(str(path))
    jar.load(ignore_discard=True, ignore_expires=True)
    cookies = httpx.Cookies()
    for c in jar:
        cookies.set(c.name, c.value, domain=c.domain, path=c.path)
    return cookies


def resolve_arnumber(client: httpx.Client, doi: str) -> tuple[str, str]:
    """Return (arnumber, document_url)."""
    doi_url = f"https://doi.org/{doi}"
    r = client.get(doi_url)
    r.raise_for_status()
    final_url = str(r.url)
    m = IEEE_DOC_RE.search(final_url)
    if not m:
        m = IEEE_DOC_RE.search(r.text[:8000])
    if not m:
        raise ValueError(f"Cannot resolve IEEE arnumber from DOI {doi} (final URL: {final_url})")
    arnumber = m.group(1)
    doc_url = f"https://ieeexplore.ieee.org/document/{arnumber}"
    return arnumber, doc_url


def download_pdf(
    client: httpx.Client,
    doi: str,
    out_path: Path,
    *,
    max_retries: int = 3,
) -> int:
    last_err: Exception | None = None
    for attempt in range(max_retries):
        try:
            arnumber, doc_url = resolve_arnumber(client, doi)
            pdf_url = f"https://ieeexplore.ieee.org/stampPDF/getPDF.jsp?arnumber={arnumber}"
            headers = {"Referer": doc_url}
            r = client.get(pdf_url, headers=headers)
            if r.status_code in (401, 403):
                raise PermissionError(
                    f"HTTP {r.status_code} for {doi} — update ieee_cookies.txt or check VPN"
                )
            r.raise_for_status()
            content_type = (r.headers.get("content-type") or "").lower()
            body = r.content
            if not body.startswith(b"%PDF-"):
                snippet = body[:200].decode("utf-8", errors="replace")
                raise ValueError(f"Response is not PDF (content-type={content_type}): {snippet}")
            if len(body) < MIN_PDF_BYTES:
                raise ValueError(f"PDF too small ({len(body)} bytes)")
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_bytes(body)
            return len(body)
        except PermissionError:
            raise
        except Exception as exc:
            last_err = exc
            if out_path.exists():
                out_path.unlink(missing_ok=True)
            time.sleep(2**attempt)
    assert last_err is not None
    raise last_err


def netscape_to_playwright(path: Path) -> list[dict]:
    jar = http.cookiejar.MozillaCookieJar(str(path))
    jar.load(ignore_discard=True, ignore_expires=True)
    out: list[dict] = []
    for c in jar:
        if "ieee" not in (c.domain or ""):
            continue
        domain = (c.domain or "").lstrip(".")
        out.append(
            {
                "name": c.name,
                "value": c.value,
                "domain": domain,
                "path": c.path or "/",
                "secure": bool(c.secure),
                "httpOnly": False,
            }
        )
    return out


def arnumber_from_state(state: dict[str, dict], item_key: str) -> str | None:
    prev = state.get(item_key)
    if prev and prev.get("arnumber"):
        return str(prev["arnumber"])
    return None


def download_pdf_playwright(
    page,
    doi: str,
    out_path: Path,
    *,
    arnumber: str | None = None,
    pdf_timeout_ms: int = DEFAULT_PDF_REQUEST_TIMEOUT_MS,
    meta: dict | None = None,
) -> tuple[int, str]:
    from playwright.sync_api import TimeoutError as PlaywrightTimeout

    if arnumber and meta is not None:
        meta["arnumber"] = arnumber
    if not arnumber:
        resp = page.goto(f"https://doi.org/{doi}", wait_until="domcontentloaded", timeout=60000)
        if resp and resp.status >= 400:
            raise ValueError(f"DOI redirect HTTP {resp.status}")
        m = IEEE_DOC_RE.search(page.url)
        if not m:
            m = IEEE_DOC_RE.search(page.content()[:8000])
        if not m:
            raise ValueError(f"Cannot resolve arnumber for DOI {doi}")
        arnumber = m.group(1)
    if meta is not None:
        meta["arnumber"] = arnumber
    doc_url = f"https://ieeexplore.ieee.org/document/{arnumber}"
    try:
        page.goto(doc_url, wait_until="domcontentloaded", timeout=60000)
    except PlaywrightTimeout:
        pass
    pdf_url = f"https://ieeexplore.ieee.org/stampPDF/getPDF.jsp?arnumber={arnumber}"
    headers = {"Referer": doc_url}
    last_err: Exception | None = None
    for attempt, timeout_ms in enumerate((pdf_timeout_ms, pdf_timeout_ms * 2)):
        try:
            resp = page.request.get(pdf_url, headers=headers, timeout=timeout_ms)
            if resp.status in (401, 403):
                raise PermissionError(f"HTTP {resp.status} for {doi}")
            body = resp.body()
            content_type = (resp.headers.get("content-type") or "").lower()
            if not body.startswith(b"%PDF-"):
                snippet = body[:200].decode("utf-8", errors="replace")
                raise ValueError(
                    f"Response is not PDF (content-type={content_type}): {snippet}"
                )
            if len(body) < MIN_PDF_BYTES:
                raise ValueError(f"PDF too small ({len(body)} bytes)")
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_bytes(body)
            return len(body), arnumber
        except PlaywrightTimeout as exc:
            last_err = exc
            if out_path.exists():
                out_path.unlink(missing_ok=True)
            if attempt == 0:
                continue
            raise
        except (PermissionError, ValueError):
            raise
        except Exception as exc:
            last_err = exc
            if out_path.exists():
                out_path.unlink(missing_ok=True)
            if attempt == 0 and "timeout" in str(exc).lower():
                continue
            raise
    assert last_err is not None
    raise last_err


def should_process(
    item: MissingItem,
    out_path: Path,
    state: dict[str, dict],
    *,
    resume: bool,
    retry_failed: bool,
) -> bool:
    if resume and is_valid_pdf(out_path):
        return False
    prev = state.get(item.item_key)
    if prev and prev.get("status") == "success" and is_valid_pdf(out_path):
        return False
    if prev and prev.get("status") == "success" and not retry_failed:
        return False
    if prev and prev.get("status") != "success" and not retry_failed and resume:
        if prev.get("status") in ("auth_failed", "failed", "not_pdf"):
            return False
    if retry_failed:
        return prev is not None and prev.get("status") != "success"
    return True


def run_playwright_downloads(
    items: list[MissingItem],
    *,
    cookies_path: Path,
    out_dir: Path,
    state: dict[str, dict],
    state_path: Path,
    delay: float,
    limit: int,
    resume: bool,
    retry_failed: bool,
) -> tuple[int, int, int, int, bool]:
    from playwright.sync_api import sync_playwright

    processed = success = skipped = failed = 0
    auth_failed = False
    pw_cookies = netscape_to_playwright(cookies_path)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(user_agent=USER_AGENT)
        if pw_cookies:
            context.add_cookies(pw_cookies)
        page = context.new_page()

        for item in items:
            out_path = out_dir / f"{item.item_key}.pdf"
            if not should_process(
                item, out_path, state, resume=resume, retry_failed=retry_failed
            ):
                skipped += 1
                continue
            if limit and processed >= limit:
                break
            processed += 1
            print(f"[{processed}] {item.item_key} {item.doi}")
            record = {
                "item_key": item.item_key,
                "doi": item.doi,
                "title": item.title,
                "ts": utc_now_iso(),
                "engine": "playwright",
            }
            try:
                arnumber = arnumber_from_state(state, item.item_key)
                nbytes, resolved_arnumber = download_pdf_playwright(
                    page, item.doi, out_path, arnumber=arnumber
                )
                record.update({
                    "status": "success",
                    "path": str(out_path),
                    "bytes": nbytes,
                    "arnumber": resolved_arnumber,
                })
                success += 1
                print(f"  OK {nbytes} bytes -> {out_path.name}")
            except PermissionError as exc:
                record.update({"status": "auth_failed", "error": str(exc)})
                append_jsonl(state_path, record)
                print(f"  AUTH FAILED: {exc}", file=sys.stderr)
                auth_failed = True
                failed += 1
                break
            except Exception as exc:
                status = "not_pdf" if "not PDF" in str(exc) else "failed"
                record.update({"status": status, "error": str(exc)})
                failed += 1
                print(f"  FAIL ({status}): {exc}", file=sys.stderr)
            append_jsonl(state_path, record)
            time.sleep(delay)

        browser.close()
    return processed, success, skipped, failed, auth_failed


def main() -> int:
    parser = argparse.ArgumentParser(description="Download PDFs from IEEE Xplore")
    parser.add_argument("--tsv", type=Path, required=True, help="TSV: item_key\\ttitle\\tdoi")
    parser.add_argument("--out-dir", type=Path, required=True, help="Output directory for PDFs")
    parser.add_argument("--cookies", type=Path, default=DEFAULT_COOKIES)
    parser.add_argument("--state", type=Path, default=None, help="Download state JSONL (default: work/download_state.jsonl)")
    parser.add_argument("--delay", type=float, default=2.5)
    parser.add_argument("--limit", type=int, default=0, help="Max items to process (0=all)")
    parser.add_argument("--resume", action="store_true", help="Skip existing valid PDFs")
    parser.add_argument("--retry-failed", action="store_true", help="Only retry failed items")
    parser.add_argument("--dry-run", action="store_true", help="Resolve DOIs only, do not download")
    parser.add_argument(
        "--engine",
        choices=("httpx", "playwright"),
        default="playwright",
        help="Download engine (playwright bypasses IEEE bot checks)",
    )
    args = parser.parse_args()

    state_path = args.state or (args.tsv.parent / "download_state.jsonl")
    items = load_tsv(args.tsv)
    state = load_jsonl_state(state_path)

    if args.engine == "playwright" and not args.dry_run:
        if not args.cookies.is_file():
            raise FileNotFoundError(f"Cookie file not found: {args.cookies}")
        processed, success, skipped, failed, auth_failed = run_playwright_downloads(
            items,
            cookies_path=args.cookies,
            out_dir=args.out_dir,
            state=state,
            state_path=state_path,
            delay=args.delay,
            limit=args.limit,
            resume=args.resume,
            retry_failed=args.retry_failed,
        )
        print(f"\nProcessed: {processed}, success: {success}, skipped: {skipped}, failed: {failed}")
        if auth_failed:
            print("Stopped due to auth failure. Re-export config/ieee_cookies.txt and retry.", file=sys.stderr)
            return 1
        return 0 if failed == 0 else 2

    cookies = None if args.dry_run else load_cookie_jar(args.cookies)

    processed = 0
    success = 0
    skipped = 0
    failed = 0
    auth_failed = False

    with httpx.Client(
        cookies=cookies,
        timeout=60.0,
        follow_redirects=True,
        headers={"User-Agent": USER_AGENT},
    ) as client:
        for item in items:
            out_path = args.out_dir / f"{item.item_key}.pdf"
            if not should_process(
                item,
                out_path,
                state,
                resume=args.resume,
                retry_failed=args.retry_failed,
            ):
                skipped += 1
                continue
            if args.limit and processed >= args.limit:
                break
            processed += 1
            print(f"[{processed}] {item.item_key} {item.doi}")
            record = {
                "item_key": item.item_key,
                "doi": item.doi,
                "title": item.title,
                "ts": utc_now_iso(),
            }
            try:
                if args.dry_run:
                    arnumber, doc_url = resolve_arnumber(client, item.doi)
                    record.update({
                        "status": "dry_run",
                        "arnumber": arnumber,
                        "document_url": doc_url,
                    })
                    success += 1
                    print(f"  OK arnumber={arnumber}")
                else:
                    nbytes = download_pdf(client, item.doi, out_path)
                    record.update({"status": "success", "path": str(out_path), "bytes": nbytes})
                    success += 1
                    print(f"  OK {nbytes} bytes -> {out_path.name}")
            except PermissionError as exc:
                record.update({"status": "auth_failed", "error": str(exc)})
                append_jsonl(state_path, record)
                print(f"  AUTH FAILED: {exc}", file=sys.stderr)
                auth_failed = True
                failed += 1
                break
            except Exception as exc:
                status = "not_pdf" if "not PDF" in str(exc) else "failed"
                record.update({"status": status, "error": str(exc)})
                failed += 1
                print(f"  FAIL ({status}): {exc}", file=sys.stderr)
            append_jsonl(state_path, record)
            time.sleep(args.delay)

    print(f"\nProcessed: {processed}, success: {success}, skipped: {skipped}, failed: {failed}")
    if auth_failed:
        print("Stopped due to auth failure. Re-export config/ieee_cookies.txt and retry.", file=sys.stderr)
        return 1
    return 0 if failed == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
