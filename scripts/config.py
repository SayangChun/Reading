# -*- coding: utf-8 -*-
"""
字段映射与渲染配置。

源仓库（yuedujilu_backup）里的读书记录字段名可能千奇百怪，
这里把"常见英文 / 中文 / 别名"都映射到一套规范内部字段。
如果你源数据的字段名不在这里，直接往对应列表里加即可，无需改生成器逻辑。
"""

# 规范内部字段 -> 可能的原始字段名（大小写不敏感；中文也行）
FIELD_MAP = {
    "title":  ["title", "书名", "name", "名称", "book", "book_name", "作品"],
    "author": ["author", "作者", "writer", "著者", "作者名"],
    "rating": ["rating", "评分", "score", "stars", "打分", "星评", "评价"],
    "date":   ["date", "日期", "read_date", "阅读日期", "finished", "完成日期",
               "finish_date", "time", "读取时间", "看完日期"],
    "tags":   ["tags", "标签", "tag", "分类", "category", "categories", "主题"],
    "review": ["review", "书评", "评论", "note", "笔记", "读后感", "content",
               "正文", "评价内容", "短评"],
    "cover":  ["cover", "封面", "image", "img", "thumbnail", "pic", "图片"],
    "isbn":   ["isbn", "ISBN", "isbn13"],
    "status": ["status", "状态", "state"],  # reading / finished / wish
}

# 评分上限（用于星级显示）
RATING_MAX = 5

# 是否把"纯文本书评"展开成 <details> 区块（True 时 README 末尾放全文）
EMBED_TEXT_REVIEWS = True

# README 大标题与简介模板（{owner}/{repo} 会自动替换）
README_TITLE = "阅读记录"
README_INTRO = "自动同步自私有读书记录仓库，每日更新。"

# 书单按什么排序：date（阅读日期，默认倒序最新在前）或 title
SORT_BY = "date"
SORT_DESC = True
