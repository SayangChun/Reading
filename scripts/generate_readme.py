# -*- coding: utf-8 -*-
"""
generate_readme.py — 把读书记录数据源渲染成 Reading 仓库的 README.md 书单。

特点：
  1. 数据源自适应：
     - 单文件：books.json / books.csv / books.md（根目录、books/、data/ 均可）
     - 目录：books/ 或 data/ 下一堆 .md（每本一个文件）
  2. 格式自适应：Markdown 支持 YAML frontmatter（--- 包裹的 key: value）
     与正文内 "- 字段: 值" 两种写法；JSON/CSV 直接读。
  3. 字段自适应：中英文混用的字段名都能识别（见 config.FIELD_MAP）。
  4. 封面本地化：优先用记录里的 cover 字段，其次读源库 raw/BOOK.db 的
     BOOKLISTTABLE.coverUrl，下载到本仓库 covers/ 后用相对路径引用，
     拿不到封面则生成 SVG 占位图（见 covers.py）。
  5. 零第三方依赖：只用 Python 标准库，GitHub Action 的 ubuntu 直接能跑。

用法：
    python scripts/generate_readme.py --source <数据源目录> --output README.md
    python scripts/generate_readme.py --source <目录> --dump-fields   # 仅打印识别到的字段，便于调试
    python scripts/generate_readme.py --source <目录> --output README.md --offline
    python scripts/generate_readme.py --source <目录> --output README.md --refresh-covers
"""
from __future__ import annotations

import argparse
import csv
import html
import json
import os
import re
import sys
from datetime import datetime, timezone

# 让脚本无论从哪里调用都能 import 到同目录的 config
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config  # noqa: E402
import covers  # noqa: E402


# --------------------------------------------------------------------------
# 1. 找数据源文件（支持单文件 + 目录）
# --------------------------------------------------------------------------
def find_source_files(source_dir: str):
    """返回 [(路径, 类型), ...]。找不到返回 []。"""
    if not source_dir or not os.path.isdir(source_dir):
        return []

    found = []

    # 1) 显式单文件（按优先级）
    explicit = [
        ("books.json", "json"), ("books.csv", "csv"), ("books.md", "markdown"),
        ("books/books.json", "json"), ("data/books.json", "json"),
        ("books/books.csv", "csv"), ("data/books.csv", "csv"),
        ("books/books.md", "markdown"), ("data/books.md", "markdown"),
        ("README.md", "markdown"),
    ]
    for name, kind in explicit:
        p = os.path.join(source_dir, name)
        if os.path.isfile(p):
            found.append((p, kind))
            return found  # 命中显式单文件即止

    # 2) books/ 或 data/ 目录：收集里面的 .md / .json / .csv
    for sub in ("books", "data"):
        d = os.path.join(source_dir, sub)
        if os.path.isdir(d):
            for fn in sorted(os.listdir(d)):
                full = os.path.join(d, fn)
                if os.path.isfile(full):
                    low = fn.lower()
                    if low.endswith(".md"):
                        found.append((full, "markdown"))
                    elif low.endswith(".json"):
                        found.append((full, "json"))
                    elif low.endswith(".csv"):
                        found.append((full, "csv"))
            if found:
                return found

    # 3) 退路：扫描一级目录里的 json/csv/md
    for fn in sorted(os.listdir(source_dir)):
        full = os.path.join(source_dir, fn)
        if os.path.isfile(full):
            low = fn.lower()
            if low.endswith(".json"):
                found.append((full, "json"))
            elif low.endswith(".csv"):
                found.append((full, "csv"))
            elif low.endswith(".md"):
                found.append((full, "markdown"))
    return found


# --------------------------------------------------------------------------
# 2. 解析各种格式 -> list[dict]
# --------------------------------------------------------------------------
def load_json(path: str):
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("books", "records", "items", "data", "list"):
            if key in data and isinstance(data[key], list):
                return data[key]
        return [data]
    return []


def load_csv(path: str):
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        return [row for row in csv.DictReader(f)]


FM_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?", re.S)
H1_RE = re.compile(r"^\s{0,3}#\s+(.*)$", re.M)
FIELD_LINE = re.compile(r"^\s*[-*]?\s*([\u4e00-\u9fffA-Za-z][\u4e00-\u9fffA-Za-z0-9_]*)\s*[:：]\s*(.+)$")
COVER_FIELDS = {"封面", "作者", "评分", "阅读日期", "日期", "完成日期", "标签", "分类",
                "主题", "书评", "读后感", "笔记", "短评"}


def parse_frontmatter(text: str):
    """极简 frontmatter 解析（单层 key: value，无嵌套）。
    返回 (dict, 剩余正文)。"""
    m = FM_RE.match(text)
    if not m:
        return {}, text
    block = m.group(1)
    body = text[m.end():]
    fm = {}
    for line in block.splitlines():
        if ":" not in line:
            continue
        k, v = line.split(":", 1)
        k, v = k.strip(), v.strip()
        if not k:
            continue
        v = v.strip("'\"")
        if v.startswith("[") and v.endswith("]"):
            inner = v[1:-1]
            v = [x.strip().strip("'\"") for x in inner.split(",") if x.strip()]
        fm[k] = v
    return fm, body


def load_markdown(path: str):
    """解析 markdown：
    - 优先读 YAML frontmatter（--- 包裹）作为元数据
    - 否则按二级/三级标题切分每本书，标题下 '- 字段: 值' 解析属性，正文作书评
    - 单文件无 frontmatter 且无二级标题时，整篇当一本（标题取首个 H1）"""
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()

    fm, body = parse_frontmatter(text)
    if fm:
        # 有 frontmatter：整篇即一本，书名缺省取首个 H1，正文作书评
        rec = dict(fm)
        h1 = H1_RE.search(body)
        if not rec.get("title") and not rec.get("书名") and h1:
            rec["title"] = h1.group(1).strip()
        if "review" not in rec and "书评" not in rec:
            rec["_body"] = body.strip()
        return [rec]

    # 无 frontmatter：尝试按标题切分
    books = []
    cur = None
    buf = []

    def flush():
        if cur is not None:
            cur["_body"] = "\n".join(buf).strip()
            books.append(cur)

    for line in text.splitlines():
        if re.match(r"^\s{0,3}#{2,3}\s+", line):
            flush()
            cur = {"title": re.sub(r"^\s{0,3}#{2,3}\s+", "", line).strip()}
            buf = []
            continue
        if cur is None:
            # 第一个 ## 之前的内容（含 H1 文档标题）一律忽略
            continue
        fm_line = FIELD_LINE.match(line)
        if fm_line:
            key, val = fm_line.group(1).strip(), fm_line.group(2).strip()
            if key in COVER_FIELDS or key.lower() in ("author", "rating", "date",
                    "read_date", "tags", "review", "cover", "isbn", "status"):
                cur[key] = val
            continue
        if line.strip():
            buf.append(line)
    flush()

    if not books:
        # 整篇没有任何 ## 分节：当单本，书名取首个 H1 或文件名
        h1 = H1_RE.search(text)
        title = h1.group(1).strip() if h1 else os.path.splitext(os.path.basename(path))[0]
        return [{"title": title, "_body": text.strip()}]
    return books


def load_records(path: str, kind: str):
    if kind == "json":
        return load_json(path)
    if kind == "csv":
        return load_csv(path)
    if kind == "markdown":
        return load_markdown(path)
    return []


# --------------------------------------------------------------------------
# 3. 规范化字段
# --------------------------------------------------------------------------
def _norm_key(k: str) -> str:
    return re.sub(r"[\s_\-]", "", str(k)).lower()


def normalize(record: dict) -> dict:
    idx = {}
    for k, v in record.items():
        if v is None or v == "":
            continue
        idx[_norm_key(k)] = v

    out = {}
    for std_field, aliases in config.FIELD_MAP.items():
        for alias in aliases:
            if _norm_key(alias) in idx:
                out[std_field] = idx[_norm_key(alias)]
                break
    if "review" not in out and "_body" in record and record["_body"]:
        out["review"] = record["_body"]
    return out


# --------------------------------------------------------------------------
# 4. 字段清洗
# --------------------------------------------------------------------------
def parse_rating(v):
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip()
    if "★" in s or "☆" in s:
        return s
    m = re.search(r"(\d+(?:\.\d+)?)", s)
    return float(m.group(1)) if m else None


def stars_display(rating) -> str:
    if rating is None:
        return "—"
    if isinstance(rating, str):
        return rating
    try:
        f = float(rating)
    except (TypeError, ValueError):
        return str(rating)
    full = max(0, min(config.RATING_MAX, int(round(f))))
    return "★" * full + "☆" * (config.RATING_MAX - full)


def parse_date(v):
    if v is None:
        return None
    s = str(v).strip()
    if not s:
        return None
    if re.fullmatch(r"\d{4}", s):
        return f"{s}-01-01"
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d", "%Y-%m", "%Y/%m",
                "%d-%m-%Y", "%d/%m/%Y", "%Y%m%d"):
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    if re.fullmatch(r"\d{10}", s):
        return datetime.fromtimestamp(int(s)).strftime("%Y-%m-%d")
    if re.fullmatch(r"\d{13}", s):
        return datetime.fromtimestamp(int(s) / 1000).strftime("%Y-%m-%d")
    return None


def parse_tags(v):
    if v is None:
        return []
    if isinstance(v, list):
        return [str(t).strip() for t in v if str(t).strip()]
    s = str(v).strip().strip("[]")
    parts = re.split(r"[,，、|/;/；\s]+", s)
    return [p.strip().strip("'\"") for p in parts if p.strip()]


def is_url(v) -> bool:
    return isinstance(v, str) and re.match(r"^https?://", v.strip(), re.I) is not None


def is_md_link(v) -> bool:
    return isinstance(v, str) and v.strip().lower().endswith(".md")


# --------------------------------------------------------------------------
# 5. 排序
# --------------------------------------------------------------------------
def sort_records(records):
    def keyfn(b):
        if config.SORT_BY == "title":
            return str(b.get("title", "")).lower()
        return b.get("_date_parsed") or "0000-00-00"
    return sorted(records, key=keyfn, reverse=config.SORT_DESC)


# --------------------------------------------------------------------------
# 6. 渲染 README
# --------------------------------------------------------------------------
def _esc(s) -> str:
    return html.escape(str(s or ""), quote=True)


def _cover_src(rel: str) -> str:
    """仓库内相对路径 -> GitHub 上可直接加载的绝对地址。"""
    base = str(getattr(config, "COVER_BASE_URL", "") or "").rstrip("/")
    return f"{base}/{rel}" if base else rel


def _cover_img(rel: str, width: int, title: str) -> str:
    """封面缩略图，点击跳到仓库里的原图。"""
    src = _cover_src(rel)
    alt = _esc(f"《{title}》封面")
    return f'<a href="{_esc(src)}"><img src="{_esc(src)}" width="{width}" alt="{alt}"></a>'


def _cover_cell(b: dict, title: str, width: int) -> str:
    rel = b.get("_cover_rel")
    if rel:
        return _cover_img(rel, width, title)
    # 没跑封面本地化时（例如单独调 render），退回数据源自带的外链
    if is_url(b.get("cover")):
        return f'<img src="{_esc(b["cover"].strip())}" width="{width}" alt="{_esc(title)}">'
    return "—"


def _cover_wall(records) -> list:
    """顶部封面墙：HTML table 网格（GitHub README 支持，且不依赖 CSS）。"""
    if not (config.SHOW_COVERS and config.SHOW_COVER_WALL):
        return []
    cols = max(1, int(config.COVER_WALL_COLUMNS))
    maxlen = int(config.COVER_WALL_TITLE_MAX)
    width = int(config.COVER_WALL_WIDTH)

    lines = ["## 封面墙", "",
             f"<sub>共 {len(records)} 本 · 点击封面可查看大图</sub>", "", "<table>"]
    for start in range(0, len(records), cols):
        chunk = records[start:start + cols]
        lines.append("<tr>")
        for b in chunk:
            title = str(b.get("title") or "（无书名）")
            short = title if len(title) <= maxlen else title[:maxlen - 1] + "…"
            rel = b.get("_cover_rel")
            img = _cover_img(rel, width, title) if rel else "<sub>暂无封面</sub>"
            status = str(b.get("status") or "").strip()
            meta = f"<br><sub>{_esc(status)}</sub>" if status else ""
            lines.append(
                f'<td align="center" valign="top" width="{100 // cols}%">'
                f'{img}<br><sub>{_esc(short)}</sub>{meta}</td>'
            )
        lines.extend("<td></td>" for _ in range(cols - len(chunk)))
        lines.append("</tr>")
    lines += ["</table>", ""]
    return lines


def _table_header(extra_cover: bool) -> list:
    if extra_cover:
        return ["| 封面 | 书名 | 作者 | 评分 | 阅读日期 | 标签 | 书评 |",
                "| --- | --- | --- | --- | --- | --- | --- |"]
    return ["| 书名 | 作者 | 评分 | 阅读日期 | 标签 | 书评 |",
            "| --- | --- | --- | --- | --- | --- |"]


def render(records) -> str:
    total = len(records)
    year = datetime.now(timezone.utc).year
    year_count = sum(1 for b in records if (b.get("_date_parsed") or "").startswith(str(year)))
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    lines = [f"# {config.README_TITLE}", ""]
    lines.append(
        f"> {config.README_INTRO}  ·  共 **{total}** 本"
        f"  ·  今年 **{year_count}** 本  ·  更新于 {generated}"
    )
    lines.append("")

    lines.extend(_cover_wall(records))

    show_col = config.SHOW_COVERS and config.SHOW_COVER_IN_TABLE
    lines.extend(_table_header(show_col))

    details = []
    for b in records:
        title = b.get("title") or "（无标题）"
        author = b.get("author") or "—"
        rating_raw = b.get("rating")
        rating_disp = stars_display(rating_raw)
        if isinstance(rating_raw, (int, float)):
            rating_disp = f"{rating_disp} {rating_raw}/5"
        date = b.get("_date_parsed") or "—"
        tags = " ".join(f"`{t}`" for t in b.get("_tags", [])) or "—"

        cover_cell = _cover_cell(b, title, config.COVER_TABLE_WIDTH)

        review = b.get("review")
        if is_url(review) or is_md_link(review):
            review_cell = f"[书评]({review.strip()})"
        elif review and config.EMBED_TEXT_REVIEWS:
            review_cell = "▸ 见下"
            details.append((title, author, rating_disp, review.strip()))
        else:
            review_cell = "—"

        prefix = f"| {cover_cell} " if show_col else "|"
        lines.append(
            f"{prefix}| {title} | {author} | {rating_disp} "
            f"| {date} | {tags} | {review_cell} |"
        )
    lines.append("")

    if details:
        lines.append("## 书评")
        lines.append("")
        for title, author, rating_disp, text in details:
            lines.append("<details>")
            lines.append(f"<summary><b>《{title}》</b> — {author} · {rating_disp}</summary>")
            lines.append("")
            lines.append(text)
            lines.append("")
            lines.append("</details>")
            lines.append("")

    lines.append("---")
    lines.append(
        "_本页由 GitHub Action 自动生成，请勿手动编辑；"
        "读书记录在私有仓库 yuedujilu_backup 中维护。_"
    )
    lines.append("")
    return "\n".join(lines)


# --------------------------------------------------------------------------
# 6b. reading_app 画像：分表读取 + 按 book_id 关联书评
#     （data/books.json + data/reviews.json + data/notes.json）
# --------------------------------------------------------------------------
def _load_json_file(path: str, key: str):
    if not os.path.isfile(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        d = json.load(f)
    if isinstance(d, dict) and key in d and isinstance(d[key], list):
        return d[key]
    if isinstance(d, list):
        return d
    return []


def _join_reviews(reviews):
    """按 book_id 聚合非空书评，返回 {book_id: '标题\\n正文...'}。"""
    out = {}
    for r in reviews:
        bid = r.get("book_id")
        if not bid:
            continue
        title = (r.get("title") or "").strip()
        content = (r.get("content") or "").strip()
        if not content and not title:
            continue
        block = (title + "\n\n" + content).strip() if title and content else (title or content)
        out.setdefault(bid, []).append(block)
    return {k: "\n\n".join(v) for k, v in out.items()}


def build_reading_app(source_dir: str):
    data_dir = os.path.join(source_dir, "data")
    books = _load_json_file(os.path.join(data_dir, "books.json"), "books")
    reviews = _load_json_file(os.path.join(data_dir, "reviews.json"), "reviews")

    rev_text = _join_reviews(reviews)

    records = []
    for b in books:
        bid = b.get("id")
        score = b.get("score")
        rating = None if score in (0, None, "") else float(score)
        rtext = rev_text.get(bid, "")
        rv_dates = [parse_date(r.get("date")) for r in reviews
                    if r.get("book_id") == bid and parse_date(r.get("date"))]
        # 阅读日期：仅由书评日期推导（不展示书摘/笔记）
        date = max(rv_dates) if rv_dates else None
        records.append({
            "_id": b.get("id"),
            "cover": b.get("cover") or "",
            "isbn": b.get("isbn") or "",
            "title": b.get("name") or "(无书名)",
            "author": b.get("author") or "",
            "publisher": b.get("publisher") or "",
            "category": b.get("category") or "",
            "status": b.get("status") or "",
            "rating": rating,
            "tags": b.get("category") or "",
            "review": rtext,
            "total_seconds": b.get("total_seconds") or 0,
            "_date_parsed": date,
        })
    if config.READING_APP_ONLY_READ:
        records = [r for r in records if r.get("status") == "已读"]
    return sort_records(records)


def render_reading_app(records):
    """返回 (README.md 内容, 次级书架页内容或 None)。

    主页面只放已读完的书；未读完的写进独立的次级页面，README 底部留一行入口。
    """
    if config.PRIMARY_ONLY_READ:
        primary = [b for b in records if b.get("status") == "已读"]
        secondary = [b for b in records if b.get("status") != "已读"]
    else:
        primary, secondary = list(records), []

    total = len(primary)
    reviews_n = sum(1 for b in primary if b.get("review"))
    total_sec = sum(int(b.get("total_seconds") or 0) for b in records)
    hours = total_sec / 3600.0
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    lines = [f"# {config.README_TITLE}", ""]
    lines.append(
        f"> {config.README_INTRO}  ·  已读 **{total}** 本"
        f"  ·  书评 **{reviews_n}** 篇"
        f"  ·  累计阅读约 **{hours:.0f}** 小时  ·  更新于 {generated}"
    )
    lines.append("")

    lines.extend(_cover_wall(primary))

    show_col = config.SHOW_COVERS and config.SHOW_COVER_IN_TABLE
    if show_col:
        lines.append("| 封面 | 书名 | 作者 | 评分 | 状态 | 分类 | 阅读日期 | 书评 |")
        lines.append("| --- | --- | --- | --- | --- | --- | --- | --- |")
    else:
        lines.append("| 书名 | 作者 | 评分 | 状态 | 分类 | 阅读日期 | 书评 |")
        lines.append("| --- | --- | --- | --- | --- | --- | --- |")

    details = []
    for b in primary:
        title = b.get("title") or "（无书名）"
        author = b.get("author") or "—"
        rating_raw = b.get("rating")
        rating_disp = stars_display(rating_raw) if rating_raw is not None else "未评"
        if isinstance(rating_raw, (int, float)):
            if rating_raw <= config.RATING_MAX:
                rating_disp = f"{rating_disp} {rating_raw}/5"
            else:
                # 数据偶发越界（如 9/10），封顶星数并如实标注
                rating_disp = f"{rating_disp} ({rating_raw})"
        status = b.get("status") or "—"
        category = b.get("category") or "—"
        date = b.get("_date_parsed") or "—"
        review = b.get("review")
        if review:
            review_cell = "▸ 见下"
            details.append((title, author, rating_disp, status, review))
        else:
            review_cell = "—"
        cover_cell = _cover_cell(b, title, config.COVER_TABLE_WIDTH)
        prefix = f"| {cover_cell} " if show_col else "|"
        lines.append(
            f"{prefix}| {title} | {author} | {rating_disp} | {status} "
            f"| {category} | {date} | {review_cell} |"
        )
    lines.append("")

    if details:
        lines.append("## 书评")
        lines.append("")
        for title, author, rating_disp, status, text in details:
            lines.append("<details>")
            lines.append(
                f"<summary><b>《{title}》</b> — {author} · {rating_disp} · {status}</summary>"
            )
            lines.append("")
            lines.append(text)
            lines.append("")
            lines.append("</details>")
            lines.append("")

    if secondary and config.SHOW_UNFINISHED_LINK and config.UNFINISHED_FILE:
        lines.append(
            f"> 另有 **{len(secondary)}** 本在读 / 想读 / 弃读，"
            f"见 [{config.UNFINISHED_FILE}]({config.UNFINISHED_FILE})。"
        )
        lines.append("")

    lines.append("---")
    lines.append(
        "_本页由 GitHub Action 自动生成，请勿手动编辑；"
        "读书记录在私有仓库 yuedujilu_backup 中维护。_"
    )
    lines.append("")

    shelf = render_shelf(secondary) if (secondary and config.UNFINISHED_FILE) else None
    return "\n".join(lines), shelf


def render_shelf(records) -> str:
    """次级页面：在读 / 想读 / 弃读的书，不占主 README 首屏。"""
    status_count = {}
    for b in records:
        s = str(b.get("status") or "未标注")
        status_count[s] = status_count.get(s, 0) + 1
    breakdown = " · ".join(f"{k} **{v}**" for k, v in sorted(status_count.items()))
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    lines = [
        "# 书架 · 未读完", "",
        f"> 共 **{len(records)}** 本（{breakdown}）  ·  更新于 {generated}", "",
        "主页面 [README.md](README.md) 只展示已读完的书与书评；这里是还没读完的书架。", "",
    ]
    lines.extend(_cover_wall(records))

    show_col = config.SHOW_COVERS and config.SHOW_COVER_IN_TABLE
    if show_col:
        lines.append("| 封面 | 书名 | 作者 | 状态 | 分类 |")
        lines.append("| --- | --- | --- | --- | --- |")
    else:
        lines.append("| 书名 | 作者 | 状态 | 分类 |")
        lines.append("| --- | --- | --- | --- |")
    for b in records:
        title = b.get("title") or "（无书名）"
        author = b.get("author") or "—"
        status = b.get("status") or "—"
        category = b.get("category") or "—"
        cover_cell = _cover_cell(b, title, config.COVER_TABLE_WIDTH)
        prefix = f"| {cover_cell} " if show_col else "|"
        lines.append(f"{prefix}| {title} | {author} | {status} | {category} |")
    lines += ["", "---", "_本页由 GitHub Action 自动生成，请勿手动编辑。_", ""]
    return "\n".join(lines)


# --------------------------------------------------------------------------
# 7. 主流程
# --------------------------------------------------------------------------
def build(source_dir: str):
    files = find_source_files(source_dir)
    if not files:
        raise SystemExit(
            f"[ERROR] 在数据源目录 '{source_dir}' 里找不到 books.json / "
            f"books.csv / books.md 或任何 json/csv/md 文件（含 books/、data/ 子目录）。"
        )

    raw = []
    for path, kind in files:
        raw.extend(load_records(path, kind))
    if not raw:
        raise SystemExit(f"[WARN] 数据源解析后没有记录（共 {len(files)} 个文件）。")

    books = []
    for rec in raw:
        b = normalize(rec)
        if not b.get("title"):
            continue
        b["_id"] = rec.get("id") or rec.get("book_id") or rec.get("bookId")
        b["_date_parsed"] = parse_date(b.get("date"))
        b["_tags"] = parse_tags(b.get("tags"))
        b["rating"] = parse_rating(b.get("rating"))
        books.append(b)

    books = sort_records(books)
    return books, files


def dump_fields(source_dir: str):
    files = find_source_files(source_dir)
    if not files:
        print("[ERROR] 未找到任何数据文件。")
        return
    print(f"找到 {len(files)} 个数据源文件：")
    for p, k in files:
        print(f"  - [{k}] {os.path.relpath(p, source_dir)}")
    print("\n各文件识别到的字段（归一化后）：")
    for p, k in files:
        recs = load_records(p, k)
        for i, rec in enumerate(recs[:3]):
            norm = normalize(rec)
            keys = ", ".join(f"{kk}={vv!r}" for kk, vv in norm.items()) or "(无可识别字段)"
            print(f"  {os.path.relpath(p, source_dir)} #{i+1}: {keys}")


def _detect_profile(source_dir: str):
    profile = config.SOURCE_PROFILE
    if profile != "auto":
        return profile
    if (os.path.isfile(os.path.join(source_dir, "data", "books.json"))
            and os.path.isfile(os.path.join(source_dir, "data", "reviews.json"))):
        return "reading_app"
    return "generic"


def main():
    ap = argparse.ArgumentParser(description="Generate reading-list README.md")
    ap.add_argument("--source", required=True, help="数据源目录（yuedujilu_backup 检出路径）")
    ap.add_argument("--output", default="README.md", help="输出文件路径")
    ap.add_argument("--dump-fields", action="store_true", help="只打印识别到的字段，便于调试格式")
    ap.add_argument("--covers-dir", default=config.COVER_DIR,
                    help="封面图片存放目录（相对 README.md），默认 covers")
    ap.add_argument("--no-covers", action="store_true", help="本次不处理封面，只出纯文字书单")
    ap.add_argument("--offline", action="store_true",
                    help="不联网下载封面，只用已缓存的封面 / 占位图")
    ap.add_argument("--refresh-covers", action="store_true", help="忽略缓存，强制重新下载全部封面")
    ap.add_argument("--no-db-covers", action="store_true",
                    help="不从源库 raw/BOOK.db 读取封面链接")
    ap.add_argument("--no-api-covers", action="store_true",
                    help="缺封面时不查公开图书 API")
    args = ap.parse_args()

    profile = _detect_profile(args.source)
    print(f"[INFO] 数据源画像：{profile}")

    if args.dump_fields:
        if profile == "reading_app":
            recs = build_reading_app(args.source)
            print(f"reading_app：{len(recs)} 本书；字段示例：")
            for r in recs[:3]:
                print("  ", {k: r[k] for k in ("title", "author", "rating",
                      "status", "category", "_date_parsed", "review_count")})
        else:
            dump_fields(args.source)
        return

    if profile == "reading_app":
        records = build_reading_app(args.source)
    else:
        records, _ = build(args.source)

    # --no-covers 要连渲染一起关掉，否则会出一面全是"暂无封面"的空墙
    if args.no_covers:
        config.SHOW_COVERS = False

    # 先本地化封面（写入 records["_cover_rel"]），再渲染
    if config.SHOW_COVERS:
        covers.attach_covers(
            records, args.source, args.output,
            covers_dir=args.covers_dir,
            offline=args.offline,
            refresh=args.refresh_covers,
            workers=config.COVER_WORKERS,
            timeout=config.COVER_TIMEOUT,
            use_db=config.COVER_USE_SOURCE_DB and not args.no_db_covers,
            api_enabled=config.COVER_API_FALLBACK and not args.no_api_covers,
            api_timeout=config.COVER_API_TIMEOUT,
            overrides=covers.load_overrides(
                os.path.dirname(os.path.abspath(args.output)),
                config.COVER_OVERRIDES_FILE),
        )

    if profile == "reading_app":
        md, shelf_md = render_reading_app(records)
    else:
        md, shelf_md = render(records), None
    n = len(records)

    out_dir = os.path.dirname(os.path.abspath(args.output))
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        f.write(md)
    print(f"[OK] 已生成 {args.output}（{n} 条记录，{len(md.splitlines())} 行）")

    if shelf_md and config.UNFINISHED_FILE:
        shelf_path = os.path.join(out_dir, config.UNFINISHED_FILE)
        with open(shelf_path, "w", encoding="utf-8") as f:
            f.write(shelf_md)
        print(f"[OK] 已生成 {shelf_path}（次级书架，{len(shelf_md.splitlines())} 行）")


if __name__ == "__main__":
    main()
