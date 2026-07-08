# IEEE Xplore Batch Paper Downloader

[中文文档](README.md)

Fetch paper metadata from [DBLP](https://dblp.org) and batch-download PDFs from [IEEE Xplore](https://ieeexplore.ieee.org). TPAMI is the full worked example; the generic engine supports any IEEE venue. For researchers with legitimate institutional access.

**This guide uses TPAMI (IEEE Transactions on Pattern Analysis and Machine Intelligence) as a full worked example. The same workflow applies to other IEEE venues** (e.g. ICRA, ICCV, CVPR, TIP, TRO)—only the metadata source may differ; PDF downloads all go through `xplore_download.py`.

> **Disclaimer**: This project provides tooling only and does not bypass paywalls. PDF downloads require your own valid IEEE institutional access. Comply with IEEE terms of use, your institution's copyright policy, and reasonable request rates.

## Scope

| Layer | Scripts | Coverage |
|-------|---------|----------|
| **Generic** | `xplore_download.py`, `ieee_common.py` | **All** IEEE Xplore papers—given a DOI list in TSV |
| **TPAMI example** | `tpami_*.py` | TPAMI only: DBLP metadata, DOI enrichment, audit, multi-round download |

```
Generic workflow for any IEEE publication:

  [metadata source]  →  CSV / custom list  →  TSV (item_key, title, doi)  →  xplore_download.py  →  PDF

Built-in TPAMI example:

  DBLP API  →  tpami_fetch_and_tsv.py  →  TSV  →  tpami_run_download.py  →  papers/tpami/{year}/
```

**Other IEEE publications**

1. Collect DOIs (`10.1109/...`) from DBLP, OpenAlex, Crossref, conference sites, Semantic Scholar, etc.
2. Convert to the standard TSV format (see below)
3. Run `xplore_download.py`—same cookies and download engine as TPAMI

| Publication type | Metadata source | Download command |
|------------------|-----------------|------------------|
| TPAMI (full year) | `tpami_fetch_and_tsv.py --year YYYY` (built-in) | `tpami_run_download.py --year YYYY` |
| ICRA / IROS / CVPR, etc. | DBLP conf pages, OpenReview, official proceedings | `xplore_download.py --tsv work/icra2023.tsv --out-dir papers/icra2023` |
| IEEE journals (TIP, TMM, TRO, …) | DBLP journal volume; adapt `tpami_fetch_metadata_dblp.py` | `xplore_download.py --tsv work/tip2020.tsv --out-dir papers/tip/2020` |
| Custom list | Manual or scripted TSV | `xplore_download.py --tsv work/my_list.tsv --out-dir papers/custom` |

## Features

| Module | Description | Scope |
|--------|-------------|-------|
| **Metadata (TPAMI example)** | Fetch annual TPAMI lists from DBLP API → CSV / TSV | TPAMI only; adapt DBLP queries for other journals |
| **DOI enrichment (TPAMI example)** | Fuzzy Crossref lookup for missing DOIs | TPAMI only; change `container-title` for other venues |
| **Metadata audit (TPAMI example)** | Compare local CSV vs DBLP | TPAMI only |
| **PDF download (generic)** | Playwright-based IEEE Xplore download, resume, rate-limit handling | **All IEEE papers** |
| **Multi-round retry (TPAMI example)** | `tpami_run_download.py` loops until done | TPAMI only; use shell loops with `xplore_download.py` for others |

## Layout

```
IEEE/
├── README.md / README.en.md
├── requirements.txt
├── .gitignore
├── config/
│   └── ieee_cookies.example.txt   # Instructions only—no real credentials
├── scripts/
│   ├── ieee_common.py             # TSV, JSONL state, PDF validation
│   ├── xplore_download.py         # Generic IEEE Xplore PDF download
│   └── tpami_*.py                 # TPAMI metadata + batch download (example)
├── work/                          # Runtime outputs (gitignored)
└── papers/                        # Downloaded PDFs (gitignored)
    ├── tpami/{year}/
    └── {venue}/
```

## Setup

### 1. Python dependencies

```bash
cd IEEE
python -m venv .venv

# Windows
.venv\Scripts\activate

# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
playwright install chromium
```

### 2. IEEE access cookies

1. Log in to IEEE Xplore via **institutional VPN or campus network**
2. Export **Netscape-format** cookies (recommended: [Get cookies.txt LOCALLY](https://chromewebstore.google.com/detail/get-cookiestxt-locally/cclelndahbckbenkjhflpdbgdldlbecc))
3. Save as `config/ieee_cookies.txt`

> `config/ieee_cookies.txt` is in `.gitignore`—**never commit it to a public repo**.

See `config/ieee_cookies.example.txt` for details.

## Quick start

### Option A: Full TPAMI pipeline (built-in example)

Using **TPAMI 2024** as an example; replace the year as needed. For other IEEE journals on DBLP, adapt `tpami_fetch_metadata_dblp.py`.

#### Step 1: Fetch metadata

```bash
python scripts/tpami_fetch_and_tsv.py --year 2024
```

Outputs in `work/`:

- `tpami2024.csv` — metadata
- `tpami2024_papers.tsv` — download list (`item_key`, `title`, `doi`)
- `tpami2024_metadata_report.md` — fetch report
- `tpami2024_metadata_audit.md` — DBLP audit report

If some rows lack DOIs:

```bash
python scripts/tpami_enrich_doi.py --year 2024 --mailto your-email@example.com
python scripts/tpami_csv_to_tsv.py --year 2024
```

#### Step 2: Batch download PDFs

```bash
python scripts/tpami_run_download.py --year 2024
```

PDFs go to `papers/tpami/2024/` as `10.1109_TPAMI.2024.xxxxxx.pdf`.

**Single round** (for debugging):

```bash
python scripts/tpami_download_pdfs.py --year 2024 --resume --limit 5
```

#### Step 3: Monitor progress

- Live success/failure in the terminal
- `work/tpami2024_download_state.jsonl` — per-paper state
- `work/tpami2024_download.log` — redirect stdout here if desired

---

### Option B: Any IEEE publication (conferences / journals / custom lists)

**One core step**: prepare a TSV and run the generic downloader. Same cookie setup as TPAMI.

#### 1. Prepare TSV

Save as `work/my_papers.tsv` (tab-separated):

```
item_key	title	doi
10.1109_ICRA.2023.10160690	Some Robotics Paper	10.1109/ICRA.2023.10160690
10.1109_TIP.2020.2983456	Some Image Processing Paper	10.1109/TIP.2020.2983456
```

`item_key` is typically the DOI with `/` replaced by `_`.

#### 2. Batch download

```bash
python scripts/xplore_download.py \
  --tsv work/my_papers.tsv \
  --out-dir papers/icra2023 \
  --engine playwright \
  --resume \
  --delay 6
```

#### 3. Multi-round retry (optional)

On IEEE rate limits, loop until complete (equivalent to `tpami_run_download.py`):

```bash
# Windows PowerShell
while ($true) {
  python scripts/xplore_download.py --tsv work/my_papers.tsv --out-dir papers/icra2023 --resume --delay 6
  if ($LASTEXITCODE -eq 0) { break }
  Start-Sleep -Seconds 1200
}
```

```bash
# macOS / Linux
until python scripts/xplore_download.py --tsv work/my_papers.tsv --out-dir papers/icra2023 --resume --delay 6; do
  sleep 1200
done
```

---

## `xplore_download.py` options

| Flag | Default | Description |
|------|---------|-------------|
| `--tsv` | (required) | Paper list TSV |
| `--out-dir` | (required) | PDF output directory |
| `--cookies` | `config/ieee_cookies.txt` | Netscape cookie file |
| `--delay` | `2.5` | Seconds between papers |
| `--resume` | off | Skip existing valid PDFs |
| `--limit` | `0` (unlimited) | Max papers to process |
| `--engine` | `playwright` | `playwright` (recommended) or `httpx` |

## Rate limiting and retries

IEEE Xplore may return HTTP 420 or temporary unavailability under heavy load:

- **3 consecutive failures** → **20-minute cooldown** (`tpami_download_pdfs.py`: `--cooldown-seconds`; generic: shell loop above)
- TPAMI: `tpami_run_download.py` retries up to `--max-rounds` (default 100)
- **All venues**: use `--delay` ≥ **6 seconds** when possible

## TSV format

Tab-separated, three columns (shared by TPAMI, conferences, and journals):

```
item_key	title	doi
10.1109_TPAMI.2024.1234567	Some Paper Title	10.1109/TPAMI.2024.1234567
10.1109_ICRA.2023.10160690	Another Paper	10.1109/ICRA.2023.10160690
```

- `item_key` — PDF filename (usually DOI with `/` → `_`)
- `title` — for logging only
- `doi` — without `https://doi.org/` prefix (IEEE: `10.1109/...`)

TPAMI TSV is generated by `tpami_csv_to_tsv.py`; other venues need your own conversion.

## Privacy and security

**This repository ships no personal credentials or institutional cookies.**

| Item | Status in repo |
|------|----------------|
| `config/ieee_cookies.txt` (real cookies) | **Not included**; path is gitignored; users create locally |
| `config/ieee_cookies.example.txt` | Comments/instructions only—no cookie values |
| Download logs, state JSONL, PDFs | Gitignored under `work/` and `papers/` |
| API keys, tokens, passwords | **None** in source |
| Hardcoded local paths (e.g. `F:\ima`) | **None** |
| Personal email addresses | **None**; `--mailto` defaults to `your-email@example.com` |

Before publishing, verify locally:

```bash
git status
ls work/ papers/ config/
# config/ should only contain ieee_cookies.example.txt
```

## FAQ

**Q: `Cookie file not found`**

Save exported cookies to `config/ieee_cookies.txt`.

**Q: Many `HTTP 420` or `temporarily unavailable` errors**

Rate limited. Increase `--delay`, wait for cooldown, or retry later.

**Q: Downloaded file is HTML, not PDF**

Cookies expired or bot detection triggered. Re-export cookies; use `--engine playwright`.

**Q: How to download ICRA / CVPR / other IEEE conference papers?**

Same as TPAMI: DOI list → TSV → `xplore_download.py`. Metadata from DBLP, OpenReview, etc. `tpami_*.py` covers TPAMI only.

**Q: DBLP count differs from IEEE (TPAMI)**

DBLP volume maps to calendar year (volume = year − 1978). Early-access DOIs may predate the publication year.

## License

This project is licensed under the [MIT License](LICENSE).

## Acknowledgments

- Metadata: [DBLP](https://dblp.org)
- DOI enrichment: [Crossref](https://www.crossref.org/)
- PDFs: [IEEE Xplore](https://ieeexplore.ieee.org) (institutional subscription required)
