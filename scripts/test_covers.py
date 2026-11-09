# -*- coding: utf-8 -*-
"""封面自动化的离线回归测试：打桩掉网络，验证新增/更新/兜底各条路径。"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import covers  # noqa: E402

TMP = tempfile.mkdtemp(prefix="reading_covers_test_")
OUT_MD = os.path.join(TMP, "README.md")
OUT_DIR = os.path.join(TMP, "covers")
os.makedirs(OUT_DIR, exist_ok=True)

FAKE_JPEG = b"\xff\xd8\xff" + b"0" * 900
calls = {"download": [], "api": []}


def fake_download(url, timeout):
    calls["download"].append(url)
    return FAKE_JPEG


def fake_api(title, author, timeout):
    calls["api"].append(title)
    return "https://api.example/newbook.jpg" if title == "未来新书" else None


covers._download = fake_download
covers.google_books_cover = fake_api

overrides = {covers.norm_title("手动指定"): "https://manual.example/m.jpg"}
records = [
    {"_id": "b1", "title": "已有书", "cover": "https://cdn.example/old.jpg"},
    {"_id": "b2", "title": "未来新书"},                       # DB 里没有 -> API 兜底
    {"_id": "b3", "title": "查不到的书"},                      # 全渠道都没有 -> 占位图
    {"_id": "b4", "title": "手动指定"},                        # covers.json 映射
    {"_id": "b5", "title": "有ISBN的书", "isbn": "9787100000001"},  # ISBN 兜底
]

kw = dict(source_dir=os.path.join(TMP, "no_such_source"),
          output_file=OUT_MD, covers_dir="covers",
          use_db=False, overrides=overrides, workers=1)

print("--- 第 1 轮：全新书单 ---")
s1 = covers.attach_covers(records, **kw)
assert s1.get("downloaded") == 2, s1          # b1(record) + b4(manual)
assert s1.get("api") == 1, s1                  # b2
assert s1.get("isbn") == 1, s1                 # b5
assert s1.get("placeholder") == 1, s1          # b3
assert len(calls["download"]) == 4, calls["download"]
assert any("openlibrary.org" in u for u in calls["download"]), calls["download"]
assert records[2]["_cover_rel"].endswith(".svg")
print("  通过：新书走 API / ISBN / 手动映射 / 占位图四条路径")

print("--- 第 2 轮：原样再跑，应零下载 ---")
before = len(calls["download"])
s2 = covers.attach_covers(records, **kw)
assert s2.get("cached") == 5, s2
assert len(calls["download"]) == before, "缓存未命中，发生了重复下载"
print("  通过：5 本全部命中缓存，0 次网络请求")

print("--- 第 3 轮：新增一本书 + 已有书换了封面 ---")
records.append({"_id": "b6", "title": "刚加的书", "cover": "https://cdn.example/b6.jpg"})
records[0]["cover"] = "https://cdn.example/NEW.jpg"   # URL 变了 -> 应自动重下
before = len(calls["download"])
s3 = covers.attach_covers(records, **kw)
assert s3.get("downloaded") == 2, s3          # 换封面的 b1 + 新书 b6
assert s3.get("cached") == 4, s3
assert len(calls["download"]) == before + 2, calls["download"]
print("  通过：新增书自动下载、换封面的书自动刷新")

print("--- 第 4 轮：原先只有占位图的书，后来补上了封面 ---")
records[2]["cover"] = "https://cdn.example/late.jpg"
before = len(calls["download"])
s4 = covers.attach_covers(records, **kw)
assert s4.get("downloaded") == 1, s4
assert records[2]["_cover_rel"].endswith(".jpg"), records[2]["_cover_rel"]
assert len(calls["download"]) == before + 1
print("  通过：占位图自动升级为真封面")

print("--- 书名相关性校验 ---")
assert covers._title_matches("百年孤独", "百年孤独")
assert covers._title_matches("百年孤独", "百年孤独（插图版）")
assert not covers._title_matches("道德经", "完全不同的另一本书")
print("  通过：API 结果不会乱配封面")

print(f"\n全部通过。临时目录：{TMP}")
