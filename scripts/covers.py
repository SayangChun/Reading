# -*- coding: utf-8 -*-
"""
covers.py — 给书单记录找封面，并把封面本地化到仓库里。

为什么不直接外链：
  - 源数据里的封面来自读书 App 的 CDN（img1.yidiansz.com 等），链接可能过期、
    可能带防盗链，GitHub 的 camo 图片代理未必取得到；
  - 其中还有 http 明文 + 302 跳转的链接，在 README 里更不稳；
  - 把图存进本仓库 covers/ 后，README 用相对路径引用，永久可用、离线可看。

封面来源优先级（越靠前越优先）：
  0. covers.json 手动映射（按书名或书籍 ID，人工兜底）
  1. 数据记录自带的 cover 字段
  2. 源库 raw/BOOK.db 里 BOOKLISTTABLE.coverUrl（书名精确匹配）
  3. ISBN -> Open Library Covers
  4. 书名 + 作者 -> Google Books API（带书名相关性校验，防止配错封面）
  5. 都没有 -> 生成带书名的 SVG 占位图，保证 README 不出现破图

新增/更新的书：
  - 新书的 ID 不同，会自动走一遍上面的链路下载封面；
  - covers/_sources.json 记录每本书上次使用的封面 URL，URL 变了（换了封面）
    或原来是占位图而现在有链接了，会自动重新下载；
  - 没变化的书直接复用本地缓存，日常同步零网络请求。

零第三方依赖，只用 Python 标准库。
"""
from __future__ import annotations

import hashlib
import html
import json
import os
import re
import shutil
import sqlite3
import tempfile
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

VALID_EXT = ("jpg", "png", "webp", "gif", "svg")
MAX_BYTES = 4 * 1024 * 1024
MIN_BYTES = 512
META_FILE = "_sources.json"

# (表名, 书名列, 封面列) —— 依次尝试，先命中先用
DB_SOURCES = (
    ("BOOKLISTTABLE", "name", "coverUrl"),
    ("CALENDER", "book_name", "book_cover"),
    ("TIMESTABLE", "bookName", "bookCover"),
)


# --------------------------------------------------------------------------
# 工具
# --------------------------------------------------------------------------
def norm_title(s) -> str:
    """书名归一化：只留中英文/数字/下划线，用于精确匹配。

    注意刻意不做模糊/包含匹配 —— 书单里同时有《强风吹拂》和《强风吹拂（影视）》，
    模糊匹配会把两本封面搞混。
    """
    return re.sub(r"[^\w]", "", str(s or "")).lower()


def is_url(v) -> bool:
    return isinstance(v, str) and re.match(r"^https?://", v.strip(), re.I) is not None


def cover_key(rec: dict) -> str:
    """封面文件名（不含扩展名）：优先用源数据的稳定 ID，避免中文文件名。"""
    bid = str(rec.get("_id") or "").strip()
    if bid:
        return re.sub(r"[^A-Za-z0-9_-]", "_", bid)
    base = f"{rec.get('title', '')}|{rec.get('author', '')}"
    return "b" + hashlib.sha1(base.encode("utf-8")).hexdigest()[:12]


def sniff_ext(data: bytes):
    """按文件头判断真实格式 —— URL 里写着 .webp 的图经 OSS 转码后可能返回 JPEG。"""
    if data.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    if data[:4] in (b"GIF8", b"gif8"):
        return "gif"
    if b"<svg" in data[:400].lower():
        return "svg"
    return None


def _write_atomic(path: str, data: bytes):
    tmp = path + ".part"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, path)


def _cleanup_old(out_dir: str, key: str, keep: str):
    """同一本书换封面格式后（jpg -> webp），删掉旧格式的残留文件。"""
    for fn in os.listdir(out_dir):
        if fn.startswith(key + ".") and fn != keep and fn != META_FILE:
            try:
                os.remove(os.path.join(out_dir, fn))
            except OSError:
                pass


# --------------------------------------------------------------------------
# 封面来源记录 / 手动映射
# --------------------------------------------------------------------------
def _load_meta(out_dir: str) -> dict:
    p = os.path.join(out_dir, META_FILE)
    if not os.path.isfile(p):
        return {}
    try:
        with open(p, "r", encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError) as e:
        print(f"[WARN] 封面来源记录读取失败，将重新校验：{e}")
        return {}


def _save_meta(out_dir: str, meta: dict):
    p = os.path.join(out_dir, META_FILE)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write("\n")


def _existing(out_dir: str, key: str, meta: dict):
    """找已缓存的有效封面，返回 (绝对路径, 扩展名, 文件名) 或 None。

    优先信 _sources.json 里记的文件名，避免同 key 存在多种格式时取到旧图。
    """
    rec = meta.get(key) or {}
    candidates = ([rec["file"]] if rec.get("file") else []) + \
                 [f"{key}.{e}" for e in VALID_EXT]
    for fn in candidates:
        if not isinstance(fn, str) or not re.fullmatch(r"[\w.\-]+", fn):
            continue
        p = os.path.join(out_dir, fn)
        # 占位 SVG 是纯文本，体积天然比照片小很多，用更低的阈值
        min_size = 128 if fn.lower().endswith(".svg") else MIN_BYTES
        if os.path.isfile(p) and os.path.getsize(p) >= min_size:
            return p, fn.rsplit(".", 1)[-1].lower(), fn
    return None


def load_overrides(root: str, filename: str) -> dict:
    """读取手动封面映射：{"书名或书籍ID": "https://..."} 或 {"书名": {"url": "..."}}。"""
    if not filename:
        return {}
    p = os.path.join(root, filename)
    if not os.path.isfile(p):
        return {}
    try:
        with open(p, "r", encoding="utf-8") as f:
            d = json.load(f)
        out = {}
        for k, v in dict(d).items():
            if isinstance(v, dict):
                v = v.get("url") or v.get("cover")
            if is_url(v):
                out[norm_title(k)] = str(v).strip()
        print(f"[INFO] 手动封面映射：{len(out)} 条（{filename}）")
        return out
    except (OSError, ValueError) as e:
        print(f"[WARN] 读取封面映射 {p} 失败：{e}")
        return {}


# --------------------------------------------------------------------------
# 从源库的 SQLite 备份里读封面
# --------------------------------------------------------------------------
def _db_candidates(source_dir: str):
    names = ["raw/BOOK.db", "BOOK.db", "data/BOOK.db"]
    paths = [os.path.join(source_dir, n) for n in names]
    for d in ("raw", "data", ""):
        folder = os.path.join(source_dir, d)
        if os.path.isdir(folder):
            for fn in sorted(os.listdir(folder)):
                if fn.lower().endswith(".db"):
                    p = os.path.join(folder, fn)
                    if p not in paths:
                        paths.append(p)
    return [p for p in paths if os.path.isfile(p)]


def read_db_covers(source_dir: str) -> dict:
    """返回 {规范化书名: 封面 URL}。数据库只读，先复制一份避免被占用。"""
    result = {}
    for db_path in _db_candidates(source_dir):
        tmp = None
        try:
            fd, tmp = tempfile.mkstemp(prefix="reading_cover_", suffix=".db")
            os.close(fd)
            shutil.copy2(db_path, tmp)
            conn = sqlite3.connect(tmp)
            try:
                tables = {r[0] for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'")}
                for table, name_col, cover_col in DB_SOURCES:
                    if table not in tables:
                        continue
                    cols = {r[1] for r in conn.execute(f'PRAGMA table_info("{table}")')}
                    if name_col not in cols or cover_col not in cols:
                        continue
                    for name, url in conn.execute(
                            f'SELECT "{name_col}", "{cover_col}" FROM "{table}"'):
                        key = norm_title(name)
                        if key and key not in result and is_url(url):
                            result[key] = str(url).strip()
            finally:
                conn.close()
        except (sqlite3.Error, OSError) as e:
            print(f"[WARN] 读取封面数据库 {db_path} 失败：{e}")
        finally:
            if tmp and os.path.isfile(tmp):
                try:
                    os.remove(tmp)
                except OSError:
                    pass
        if result:
            break  # 一个库里读到了就不必再翻其他备份
    return result


# --------------------------------------------------------------------------
# 缺封面时的兜底：ISBN / 公开图书 API
# --------------------------------------------------------------------------
def _clean_author(a) -> str:
    s = re.sub(r"[\[\(（【].*?[\]\)）】]", "", str(a or ""))
    return re.split(r"[\s,，/、]+", s.strip())[0][:20]


def _title_matches(query: str, candidate: str) -> bool:
    """防止 API 返回同名/近似书时配错封面。"""
    q, c = norm_title(query), norm_title(candidate)
    if not q or not c:
        return False
    if q == c or q in c or c in q:
        return True
    sq, sc = set(q), set(c)
    return len(sq & sc) / max(1, len(sq | sc)) >= 0.6


def google_books_cover(title: str, author, timeout: int):
    """按书名 + 作者查 Google Books，返回缩略图 URL 或 None。"""
    q = f'intitle:"{title}"'
    a = _clean_author(author)
    if a:
        q += f' inauthor:"{a}"'
    url = "https://www.googleapis.com/books/v1/volumes?" + urllib.parse.urlencode({
        "q": q, "maxResults": 5,
        "fields": "items(volumeInfo(title,authors,imageLinks))",
    })
    req = urllib.request.Request(url, headers={"User-Agent": "ReadingListBot/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    for item in data.get("items") or []:
        vi = item.get("volumeInfo") or {}
        if not _title_matches(title, vi.get("title")):
            continue
        links = vi.get("imageLinks") or {}
        link = links.get("thumbnail") or links.get("smallThumbnail")
        if is_url(link):
            return str(link).replace("http://", "https://", 1)
    return None


def resolve_cover_url(rec, db_map, overrides, api_enabled, api_timeout):
    """按优先级找封面 URL，返回 (url, 来源标签)。"""
    key = cover_key(rec)
    title = str(rec.get("title") or "")

    # 0. 人工映射：既能按书 ID，也能按书名写
    for k in (key, norm_title(title)):
        v = overrides.get(k)
        if is_url(v):
            return str(v).strip(), "manual"

    # 1. 数据记录自带
    v = rec.get("cover")
    if is_url(v):
        return str(v).strip(), "record"

    # 2. 源库 SQLite 备份
    v = db_map.get(norm_title(title))
    if is_url(v):
        return str(v).strip(), "db"

    # 3. ISBN -> Open Library（?default=false 让缺封面时直接 404，不会给一张空图）
    isbn = re.sub(r"[^0-9Xx]", "", str(rec.get("isbn") or ""))
    if len(isbn) in (10, 13):
        return (f"https://covers.openlibrary.org/b/isbn/{isbn}-M.jpg"
                "?default=false"), "isbn"

    # 4. 公开图书 API（只在缺封面时请求）
    if api_enabled and title:
        try:
            v = google_books_cover(title, rec.get("author"), api_timeout)
            if is_url(v):
                return str(v).strip(), "api"
        except Exception as e:
            print(f"[INFO] 公开图书 API 未找到《{title}》封面：{type(e).__name__}")
    return None, "none"


# --------------------------------------------------------------------------
# 下载 / 占位图
# --------------------------------------------------------------------------
def _download(url: str, timeout: int) -> bytes:
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (compatible; ReadingListBot/1.0; +https://github.com)",
        "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
    })
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        ctype = (resp.headers.get("Content-Type") or "").lower()
        if not ctype.startswith("image/"):
            raise ValueError(f"响应不是图片：{ctype or '未知'}")
        data = resp.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES or len(data) < MIN_BYTES:
        raise ValueError(f"图片大小异常：{len(data)} bytes")
    if sniff_ext(data) is None:
        raise ValueError("无法识别的图片格式")
    return data


def _placeholder_svg(title: str) -> bytes:
    """生成一张不依赖网络的占位封面。"""
    palette = ("#2f6f5e", "#3b5b8c", "#8a5a44", "#6b4f8a", "#4a6b3d", "#8a4444")
    color = palette[int(hashlib.sha1(title.encode("utf-8")).hexdigest(), 16) % len(palette)]
    short = str(title or "无封面").replace("\n", " ").strip()
    lines = [short[i:i + 6] for i in range(0, min(len(short), 18), 6)]
    texts = "".join(
        f'<text x="100" y="{128 + i * 30}" text-anchor="middle" font-size="19" '
        f'font-family="sans-serif" fill="#f5f2ea">{html.escape(line)}</text>'
        for i, line in enumerate(lines)
    )
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="200" height="280" '
        'viewBox="0 0 200 280">'
        f'<rect width="200" height="280" rx="4" fill="{color}"/>'
        '<rect x="16" y="16" width="7" height="248" fill="#ffffff" opacity="0.35"/>'
        f'{texts}'
        '<text x="100" y="256" text-anchor="middle" font-size="11" '
        'font-family="sans-serif" fill="#ffffff" opacity="0.6">暂无封面</text>'
        '</svg>'
    )
    return svg.encode("utf-8")


def _resolve_one(rec, out_dir, covers_dir, db_map, overrides, meta,
                 timeout, offline, refresh, api_enabled, api_timeout):
    """处理一本书，返回 (状态, 相对路径, 来源标签, meta 条目或 None)。"""
    key = cover_key(rec)
    cached = _existing(out_dir, key, meta)
    url, source = resolve_cover_url(rec, db_map, overrides, api_enabled, api_timeout)
    prev_url = (meta.get(key) or {}).get("url")

    # 换了封面 URL / 原来是占位图现在有链接了 -> 重新下载
    stale = bool(url) and (prev_url != url or (cached and cached[1] == "svg"))
    if cached and not refresh and not stale:
        return "cached", f"{covers_dir}/{cached[2]}", source, None

    if url and not offline:
        for attempt in range(2):
            try:
                data = _download(url, timeout)
                fname = f"{key}.{sniff_ext(data)}"
                _write_atomic(os.path.join(out_dir, fname), data)
                _cleanup_old(out_dir, key, fname)
                entry = {"url": url, "file": fname, "source": source}
                status = "downloaded" if source in ("manual", "record", "db") else source
                return status, f"{covers_dir}/{fname}", source, entry
            except Exception as e:  # 网络类异常种类多，统一兜住并重试一次
                if attempt == 1:
                    print(f"[WARN] 封面下载失败《{rec.get('title')}》：{type(e).__name__}: {e}")

    # 下载失败 / 无链接 / 离线模式：优先复用旧缓存，否则占位图
    if cached:
        return "cached", f"{covers_dir}/{cached[2]}", source, None
    fname = f"{key}.svg"
    _write_atomic(os.path.join(out_dir, fname), _placeholder_svg(rec.get("title", "")))
    return "placeholder", f"{covers_dir}/{fname}", source, {
        "url": url, "file": fname, "source": "placeholder"}


def attach_covers(records, source_dir, output_file, covers_dir="covers",
                  offline=False, refresh=False, workers=6, timeout=15,
                  use_db=True, api_enabled=True, api_timeout=10,
                  overrides=None):
    """给每条记录写入 _cover_rel（README 里用的相对路径）。

    output_file 用来定位仓库根目录 —— covers/ 与 README.md 同级。
    """
    if not records:
        return {}
    root = os.path.dirname(os.path.abspath(output_file)) or "."
    out_dir = os.path.join(root, covers_dir)
    os.makedirs(out_dir, exist_ok=True)

    db_map = read_db_covers(source_dir) if use_db else {}
    if db_map:
        print(f"[INFO] 从源库数据库读到 {len(db_map)} 条封面链接")
    else:
        print("[WARN] 源库数据库里没读到封面链接，将依赖记录字段 / ISBN / 公开 API / 手动映射")

    overrides = overrides if overrides is not None else {}
    meta = _load_meta(out_dir)
    # 离线时不做外部 API 查询，免得白等超时
    api_on = bool(api_enabled and not offline)

    stats, sources, missing = {}, {}, []
    results = [None] * len(records)
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = {
            pool.submit(_resolve_one, rec, out_dir, covers_dir, db_map, overrides,
                        meta, timeout, offline, refresh, api_on, api_timeout): i
            for i, rec in enumerate(records)
        }
        for fut in as_completed(futures):
            i = futures[fut]
            rec = records[i]
            try:
                status, rel, source, entry = fut.result()
                if entry:
                    meta[cover_key(rec)] = entry
            except Exception as e:
                print(f"[WARN] 封面处理异常《{rec.get('title')}》：{e}")
                status, rel, source = "failed", None, "none"
            results[i] = rel
            stats[status] = stats.get(status, 0) + 1
            sources[source] = sources.get(source, 0) + 1
            if status in ("placeholder", "failed"):
                missing.append(str(rec.get("title") or "?"))

    _save_meta(out_dir, meta)
    for rec, rel in zip(records, results):
        rec["_cover_rel"] = rel
    print("[INFO] 封面：" + " / ".join(f"{k}={v}" for k, v in sorted(stats.items())))
    print("[INFO] 来源：" + " / ".join(f"{k}={v}" for k, v in sorted(sources.items())))
    if missing:
        print(f"[WARN] 以下 {len(missing)} 本暂用占位图，可在 covers.json 里手动指定："
              + "、".join(missing[:8]) + ("…" if len(missing) > 8 else ""))
    return stats
