# IEEE Xplore 论文批量下载工具

[English](README.en.md)

从 [DBLP](https://dblp.org) 抓取论文元数据，经 [IEEE Xplore](https://ieeexplore.ieee.org) 批量下载 PDF；以 TPAMI 为完整示例，通用引擎支持任意 IEEE 文献。适用于有机构订阅权限的研究者，用于本地文献归档与检索。

**本文档以 TPAMI（IEEE Transactions on Pattern Analysis and Machine Intelligence）为完整示例；其余 IEEE 期刊、会议论文（如 ICRA、ICCV、CVPR、TIP、TRO 等）下载流程相同**——元数据来源可能不同，但 PDF 下载均走同一套 `xplore_download.py` 引擎。

> **免责声明**：本工具仅提供技术实现，不绕过付费墙。下载 PDF 需要您本人拥有合法的 IEEE 机构访问权限。请遵守 IEEE 使用条款与所在机构的版权政策，合理控制请求频率。

## 适用范围

| 层级 | 脚本 | 适用范围 |
|------|------|----------|
| **通用层** | `xplore_download.py`、`ieee_common.py` | **所有** IEEE Xplore 论文——只要有 DOI 和 TSV 列表即可 |
| **TPAMI 示例层** | `tpami_*.py` | 仅 TPAMI：DBLP 元数据抓取、DOI 补全、审计、多轮重试下载 |

```
任意 IEEE 文献的通用流程：

  [元数据来源]  →  CSV / 自建列表  →  TSV（item_key, title, doi）  →  xplore_download.py  →  PDF

TPAMI 完整示例（本仓库已内置）：

  DBLP API  →  tpami_fetch_and_tsv.py  →  TSV  →  tpami_run_download.py  →  papers/tpami/{year}/
```

**其余 IEEE 文献怎么做？**

1. 从 DBLP、OpenAlex、Crossref、会议官网、Semantic Scholar 等获取论文列表，整理出 **DOI**（格式通常为 `10.1109/...`）
2. 转为标准 TSV（见下文「TSV 格式」）
3. 调用 `xplore_download.py` 批量下载——与 TPAMI 使用**完全相同的 Cookie 和下载引擎**

常见示例：

| 文献类型 | 元数据获取建议 | 下载命令 |
|----------|----------------|----------|
| TPAMI 某年全集 | `tpami_fetch_and_tsv.py --year YYYY`（内置） | `tpami_run_download.py --year YYYY` |
| ICRA / IROS / CVPR 等会议 | DBLP 会议页、OpenReview、官方 proceedings | `xplore_download.py --tsv work/icra2023.tsv --out-dir papers/icra2023` |
| IEEE 期刊（TIP、TMM、TRO 等） | DBLP 期刊 volume 页，参考 `tpami_fetch_metadata_dblp.py` 改写 | `xplore_download.py --tsv work/tip2020.tsv --out-dir papers/tip/2020` |
| 自定义论文清单 | 手动或脚本生成 TSV | `xplore_download.py --tsv work/my_list.tsv --out-dir papers/custom` |

## 功能概览

| 模块 | 说明 | 适用范围 |
|------|------|----------|
| **元数据（TPAMI 示例）** | 从 DBLP API 抓取 TPAMI 年度论文列表，生成 CSV / TSV | 仅 TPAMI；其他期刊可参考脚本改写 DBLP 查询 |
| **DOI 补全（TPAMI 示例）** | 通过 Crossref 为缺失 DOI 的条目做模糊匹配补全 | 仅 TPAMI；其他 venue 需调整 `container-title` |
| **元数据审计（TPAMI 示例）** | 对比本地 CSV 与 DBLP 数据，输出差异报告 | 仅 TPAMI |
| **PDF 下载（通用）** | 通过 Playwright 从 IEEE Xplore 下载 PDF，支持断点续传与限流重试 | **所有 IEEE 论文** |
| **多轮重试（TPAMI 示例）** | `tpami_run_download.py` 自动循环直到下完 | 仅 TPAMI；其他文献可用 shell 循环调用 `xplore_download.py` |

## 目录结构

```
IEEE/
├── README.md / README.en.md  # 中文 / 英文说明
├── requirements.txt          # Python 依赖
├── .gitignore
├── config/
│   └── ieee_cookies.example.txt   # Cookie 导出说明（示例，不含真实凭证）
├── scripts/
│   ├── ieee_common.py        # 通用工具（TSV、JSONL 状态、PDF 校验）
│   ├── xplore_download.py      # IEEE Xplore 通用 PDF 下载（所有 IEEE 文献）
│   ├── tpami_*.py            # TPAMI 专用：元数据抓取与批量下载（示例实现）
├── work/                     # 运行时产物（CSV、TSV、日志、状态，已 gitignore）
└── papers/                   # PDF 输出目录（已 gitignore）
    ├── tpami/{year}/         # TPAMI 示例默认输出
    └── {venue}/              # 其余 IEEE 文献可自定目录
```

## 环境准备

### 1. Python 依赖

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

### 2. IEEE 访问 Cookie

1. 在浏览器中通过**机构 VPN 或校园网**登录 IEEE Xplore
2. 使用浏览器扩展导出 **Netscape 格式** Cookie（推荐：[Get cookies.txt LOCALLY](https://chromewebstore.google.com/detail/get-cookiestxt-locally/cclelndahbckbenkjhflpdbgdldlbecc)）
3. 将导出文件保存为 `config/ieee_cookies.txt`

> `config/ieee_cookies.txt` 已在 `.gitignore` 中，**切勿提交到公开仓库**。

可参考 `config/ieee_cookies.example.txt` 中的说明。

## 快速开始

### 方式 A：TPAMI 完整流程（内置示例）

以下以 **TPAMI 2024** 年为例，将年份替换即可。**其余 IEEE 期刊若要从 DBLP 抓元数据，可参考 `tpami_fetch_metadata_dblp.py` 修改 DBLP 查询路径。**

#### 步骤 1：抓取元数据

```bash
python scripts/tpami_fetch_and_tsv.py --year 2024
```

产出文件（位于 `work/`）：

- `tpami2024.csv` — 论文元数据
- `tpami2024_papers.tsv` — 下载列表（三列：`item_key`、`title`、`doi`）
- `tpami2024_metadata_report.md` — 抓取报告
- `tpami2024_metadata_audit.md` — 与 DBLP 的对账报告

若部分条目缺少 DOI，可运行：

```bash
python scripts/tpami_enrich_doi.py --year 2024 --mailto your-email@example.com
python scripts/tpami_csv_to_tsv.py --year 2024
```

#### 步骤 2：批量下载 PDF

```bash
python scripts/tpami_run_download.py --year 2024
```

PDF 默认保存至 `papers/tpami/2024/`，文件名形如 `10.1109_TPAMI.2024.xxxxxx.pdf`。

**单轮下载**（适合调试）：

```bash
python scripts/tpami_download_pdfs.py --year 2024 --resume --limit 5
```

#### 步骤 3：查看进度

- 终端实时输出成功 / 失败状态
- `work/tpami2024_download_state.jsonl` — 每篇论文的下载记录
- `work/tpami2024_download.log` — 可将终端输出重定向到此文件

---

### 方式 B：任意 IEEE 文献（会议 / 其他期刊 / 自定义列表）

**核心只需一步**：准备好 TSV，调用通用下载器。Cookie 配置与 TPAMI 完全相同。

#### 1. 准备 TSV

从任意来源整理 DOI，保存为 `work/my_papers.tsv`（制表符分隔，见「TSV 格式」）：

```
item_key	title	doi
10.1109_ICRA.2023.10160690	Some Robotics Paper	10.1109/ICRA.2023.10160690
10.1109_TIP.2020.2983456	Some Image Processing Paper	10.1109/TIP.2020.2983456
```

可用 Python、Excel、DBLP 导出等方式生成；`item_key` 一般将 DOI 的 `/` 替换为 `_`。

#### 2. 批量下载

```bash
python scripts/xplore_download.py \
  --tsv work/my_papers.tsv \
  --out-dir papers/icra2023 \
  --engine playwright \
  --resume \
  --delay 6
```

#### 3. 多轮重试（可选）

若遇 IEEE 限流，可循环执行直到下完（等效于 TPAMI 的 `tpami_run_download.py`）：

```bash
# Windows PowerShell 示例
while ($true) {
  python scripts/xplore_download.py --tsv work/my_papers.tsv --out-dir papers/icra2023 --resume --delay 6
  if ($LASTEXITCODE -eq 0) { break }
  Start-Sleep -Seconds 1200
}
```

```bash
# macOS / Linux 示例
until python scripts/xplore_download.py --tsv work/my_papers.tsv --out-dir papers/icra2023 --resume --delay 6; do
  sleep 1200
done
```

---

## 通用下载参数（`xplore_download.py`）

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--tsv` | （必填） | 论文列表 TSV |
| `--out-dir` | （必填） | PDF 输出目录 |
| `--cookies` | `config/ieee_cookies.txt` | Netscape Cookie 文件 |
| `--delay` | `2.5` | 每篇之间的间隔（秒） |
| `--resume` | 关闭 | 跳过已存在的有效 PDF |
| `--limit` | `0`（不限） | 最多处理篇数 |
| `--engine` | `playwright` | `playwright`（推荐）或 `httpx` |

## 限流与重试策略

IEEE Xplore 对高频请求会返回 HTTP 420 / 临时不可用等错误。本工具内置：

- 连续失败 **3 次**后自动冷却 **20 分钟**（`tpami_download_pdfs.py` 支持 `--cooldown-seconds`；通用下载可配合上文 shell 循环）
- TPAMI：`tpami_run_download.py` 多轮调用直到完成或达到 `--max-rounds`（默认 100）
- **所有 IEEE 文献**：建议 `--delay` 设为 **6 秒**以上，避免触发限流

## TSV 格式

所有 IEEE 文献（含 TPAMI、会议、其他期刊）共用同一 TSV 格式，制表符分隔三列：

```
item_key	title	doi
10.1109_TPAMI.2024.1234567	Some Paper Title	10.1109/TPAMI.2024.1234567
10.1109_ICRA.2023.10160690	Another Paper	10.1109/ICRA.2023.10160690
```

- `item_key`：用作 PDF 文件名（通常将 DOI 中的 `/` 替换为 `_`）
- `title`：论文标题（仅用于日志）
- `doi`：不含 `https://doi.org/` 前缀的 DOI 字符串（IEEE 论文一般为 `10.1109/...`）

TPAMI 的 TSV 由 `tpami_csv_to_tsv.py` 自动生成；其他文献需自行准备或编写转换脚本。

## 隐私与安全

**本仓库不包含任何个人凭证或机构 Cookie。** 当前项目目录可安全开源，具体核查如下：

| 项目 | 仓库内状态 |
|------|------------|
| `config/ieee_cookies.txt`（真实 Cookie） | **未包含**；路径已 gitignore，需用户本地自行创建 |
| `config/ieee_cookies.example.txt` | 仅注释说明，**无 Cookie 值** |
| 下载日志、状态 JSONL、PDF 文件 | 已 gitignore（`work/`、`papers/`） |
| API 密钥、Token、密码 | 源码中**无** |
| 硬编码本地路径（如 `F:\ima`） | **无** |
| 个人邮箱 | **无**；`--mailto` 默认值为 `your-email@example.com` |

上传前请自行确认：

```bash
# 确认没有 Cookie 被跟踪
git status

# 确认 work/、papers/、config/ 下无敏感文件
# config/ 下应仅有 ieee_cookies.example.txt
ls work/ papers/ config/
```

## 常见问题

**Q: 提示 `Cookie file not found`**

将浏览器导出的 Cookie 保存为 `config/ieee_cookies.txt`。

**Q: 大量 `HTTP 420` 或 `temporarily unavailable`**

IEEE 限流。增大 `--delay`，等待冷却后重试，或换时段运行 `tpami_run_download.py`。

**Q: 下载的文件不是 PDF（HTML 页面）**

通常是 Cookie 过期或 bot 检测。重新导出 Cookie，确保使用 `--engine playwright`。

**Q: 如何下载 ICRA / CVPR / 其他 IEEE 会议论文？**

与 TPAMI 相同：整理 DOI 列表 → 生成 TSV → `xplore_download.py`。元数据请从 DBLP 会议页、OpenReview 或官方 proceedings 获取，本仓库的 `tpami_*.py` 脚本仅覆盖 TPAMI。

**Q: DBLP 条目数与 IEEE 官网不一致（TPAMI）**

TPAMI 的 DBLP volume 按日历年映射（volume = year − 1978），部分 early-access 论文的 DOI 年份可能早于发表年，属正常现象。

## 许可证

本项目采用 [MIT 许可证](LICENSE)。

## 致谢

- 元数据来源：[DBLP](https://dblp.org)
- DOI 补全：[Crossref](https://www.crossref.org/)
- PDF 来源：[IEEE Xplore](https://ieeexplore.ieee.org)（需机构订阅）
