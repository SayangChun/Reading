# -*- coding: utf-8 -*-
"""
generate_readme.py — 把读书记录数据源渲染成 Reading 仓库的 README.md 书单。

特点：
  1. 数据源自适应：自动寻找 books.json / books.csv / books.md / books/ 目录，
     也接受单个 markdown 笔记（按二级标题切分每本书）。
  2. 字段自适应：中英文混用的字段名都能识别（见 config.FIELD_MAP）。
  3. 零第三方依赖：只用 Python 标准库，GitHub Action 的 ubuntu 直接能跑。

用法：
    python scripts/generate_readme.py --source <数据源目录> --output README.md
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
from datetime import datetime, timezone

# 让脚本无论从哪里调用都能 import 到同目录的 config
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config  # noqa: E402


# --------------------------------------------------------------------------
# 1. 找数据源文件
# --------------------------------------------------------------------------
def find_source_file(source_dir: str):
    """在 source_dir 里按优先级找数据文件，返回 (路径, 类型) 或 (None, None)。"""
    if not source_dir or not os.path.isdir(source_dir):
        return None, None

    candidates = [
        ("books.json", "json"),
        ("books.csv", "csv"),
        ("books.md", "markdown"),
        ("books/books.json", "json"),
        ("data/books.json", "json"),
        ("README.md", "markdown"),
    ]
    for name, kind in candidates:
        p = os.path.join(source_dir, name)
        if os.path.isfile(p):
            return p, kind

    # 退路：扫描一级目录里的 json/csv/md
    for fname in sorted(os.listdir(source_dir)):
        full = os.path.join(source_dir, fname)
        if os.path.isfile(full):
            low = fname.lower()
            if low.endswith(".json"):
                return full, "json"
            if low.endswith(".csv"):
                return full, "csv"
            if low.endswith(".md"):
                return full, "markdown"
    return None, None


# --------------------------------------------------------------------------
# 2. 解析各种格式 -> list[dict]
# --------------------------------------------------------------------------
def load_json(path: str):
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        # 常见容器键
        for key in ("books", "records", "items", "data", "list"):
            if key in data and isinstance(data[key], list):
                return data[key]
        # 整个 dict 当成单本或一组，尝试包成列表
        return [data]
    return []


def load_csv(path: str):
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        return [row for row in reader]


MD_HEADING = re.compile(r"^\s{0,3}(#{2,3})\s+(.*)$")
MD_FIELD = re.compile(r"^\s*[-*]?\s*(?:作者|author)\s*[:：]\s*(.+)$", re.I)
MD_FIELD_GENERIC = re.compile(r"^\s*[-*]?\s*([\u4e00-\u9fffA-Za-z]+)\s*[:：]\s*(.+)$")


def load_markdown(path: str):
    """解析单文件 markdown：每个二级/三级标题当作一本书，
    标题下的 - 字段: 值 行解析为属性，其余正文作为书评。"""
    with open(path, "r", encoding="utf-8") as f:
        lines = f.read().splitlines()

    books = []
    cur = None
    body = []

    def flush():
        if cur is not None:
            cur["_body"] = "\n".join(body).strip()
            books.append(cur)

    for line in lines:
        m = MD_HEADING.match(line)
        if m:
            flush()
            cur = {"title": m.group(2).strip()}
            body = []
            continue
        if cur is None:
            continue
        fm = MD_FIELD.match(line)
        if fm:
            cur["author"] = fm.group(1).strip()
            continue
        fg = MD_FIELD_GENERIC.match(line)
        if fg:
            key = fg.group(1).strip()
            val = fg.group(2).strip()
            # 把中文键名也接住（评分/阅读日期/标签/书评）
            if key in ("评分", "评分值"):
                cur["rating"] = val
            elif key in ("阅读日期", "日期", "完成日期"):
                cur["date"] = val
            elif key in ("标签", "分类", "主题"):
                cur["tags"] = val
            elif key in ("书评", "读后感", "笔记", "短评"):
                cur["review"] = val
            continue
        if line.strip():
            body.append(line)
    flush()
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
    """把一条原始记录映射到规范字段。"""
    # 建一个 "归一化键 -> 原始值" 的索引
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
        # markdown 解析塞进来的 _body 也当作书评兜底
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
    # 已是星级字符串，原样返回
    if "★" in s or "☆" in s:
        return s
    m = re.search(r"(\d+(?:\.\d+)?)", s)
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            return None
    return None


def stars_display(rating) -> str:
    if rating is None:
        return "—"
    if isinstance(rating, str):  # 已是星级
        return rating
    try:
        f = float(rating)
    except (TypeError, ValueError):
        return str(rating)
    full = int(round(f))
    full = max(0, min(config.RATING_MAX, full))
    return "★" * full + "☆" * (config.RATING_MAX - full)


def parse_date(v):
    if v is None:
        return None
    s = str(v).strip()
    if not s:
        return None
    # 纯年份
    if re.fullmatch(r"\d{4}", s):
        return f"{s}-01-01"
    # 常见格式尝试
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d", "%Y-%m", "%Y/%m",
                "%d-%m-%Y", "%d/%m/%Y", "%Y%m%d"):
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    # 时间戳（秒/毫秒）
    if re.fullmatch(r"\d{10}", s):
        return datetime.fromtimestamp(int(s)).strftime("%Y-%m-%d")
    if re.fullmatch(r"\d{13}", s):
        return datetime.fromtimestamp(int(s) / 1000).strftime("%Y-%m-%d")
    return None  # 解析不出就放弃排序依据


def parse_tags(v):
    if v is None:
        return []
    if isinstance(v, list):
        return [str(t).strip() for t in v if str(t).strip()]
    s = str(v).strip()
    # 支持 "科幻, 哲学" / "科幻、哲学" / "科幻|哲学"
    parts = re.split(r"[,，、|/;/；\s]+", s)
    return [p.strip() for p in parts if p.strip()]


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
        # 缺失日期用极小值占位；倒序时自然落到末尾
        return b.get("_date_parsed") or "0000-00-00"
    return sorted(records, key=keyfn, reverse=config.SORT_DESC)


# --------------------------------------------------------------------------
# 6. 渲染 README
# --------------------------------------------------------------------------
def render(records) -> str:
    total = len(records)
    year = datetime.now(timezone.utc).year
    year_count = sum(
        1 for b in records
        if (b.get("_date_parsed") or "").startswith(str(year))
    )
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    lines = []
    lines.append(f"# {config.README_TITLE}")
    lines.append("")
    lines.append(
        f"> {config.README_INTRO}  ·  共 **{total}** 本"
        f"  ·  今年 **{year_count}** 本  ·  更新于 {generated}"
    )
    lines.append("")

    # 表格
    header = "| 封面 | 书名 | 作者 | 评分 | 阅读日期 | 标签 | 书评 |"
    sep = "| --- | --- | --- | --- | --- | --- | --- |"
    lines.append(header)
    lines.append(sep)

    details_blocks = []
    for b in records:
        title = b.get("title") or "（无标题）"
        author = b.get("author") or "—"
        rating_raw = b.get("rating")
        rating_disp = stars_display(rating_raw)
        if isinstance(rating_raw, (int, float)):
            rating_disp = f"{rating_disp} {rating_raw}/5"
        date = b.get("_date_parsed") or "—"
        tags = " ".join(f"`{t}`" for t in b.get("_tags", [])) or "—"

        # 封面
        cover = b.get("cover")
        if is_url(cover):
            cover_cell = f'<img src="{cover.strip()}" width="48" alt="cover">'
        else:
            cover_cell = "—"

        # 书评单元格：链接 or 详情 or 无
        review = b.get("review")
        if is_url(review):
            review_cell = f"[书评]({review.strip()})"
        elif is_md_link(review):
            review_cell = f"[书评]({review.strip()})"
        elif review and config.EMBED_TEXT_REVIEWS:
            review_cell = "▸ 见下"
            details_blocks.append((title, author, rating_disp, review.strip()))
        else:
            review_cell = "—"

        lines.append(
            f"| {cover_cell} | {title} | {author} | {rating_disp} "
            f"| {date} | {tags} | {review_cell} |"
        )

    lines.append("")

    if details_blocks:
        lines.append("## 书评")
        lines.append("")
        for title, author, rating_disp, text in details_blocks:
            lines.append(f"<details>")
            lines.append(
                f"<summary><b>《{title}》</b> — {author} · {rating_disp}</summary>"
            )
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
# 7. 主流程
# --------------------------------------------------------------------------
def build(source_dir: str):
    path, kind = find_source_file(source_dir)
    if not path:
        raise SystemExit(
            f"[ERROR] 在数据源目录 '{source_dir}' 里找不到 books.json / "
            f"books.csv / books.md 或任何 json/csv/md 文件。"
        )

    raw = load_records(path, kind)
    if not raw:
        raise SystemExit(f"[WARN] 数据源 {path} 解析后没有记录。")

    books = []
    for rec in raw:
        b = normalize(rec)
        if not b.get("title"):
            # 没有书名就跳过，避免空行
            continue
        b["_date_parsed"] = parse_date(b.get("date"))
        b["_tags"] = parse_tags(b.get("tags"))
        b["rating"] = parse_rating(b.get("rating"))
        books.append(b)

    books = sort_records(books)
    return render(books)


def main():
    ap = argparse.ArgumentParser(description="Generate reading-list README.md")
    ap.add_argument("--source", required=True, help="数据源目录（yuedujilu_backup 检出路径）")
    ap.add_argument("--output", default="README.md", help="输出文件路径")
    args = ap.parse_args()

    md = build(args.source)
    out_dir = os.path.dirname(os.path.abspath(args.output))
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        f.write(md)
    print(f"[OK] 已生成 {args.output}（{len(md.splitlines())} 行）")


if __name__ == "__main__":
    main()
