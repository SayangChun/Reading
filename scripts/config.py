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

# 数据源画像：auto（自动识别）/ reading_app（阅读记录 App 备份）/ generic（单文件/目录）
SOURCE_PROFILE = "auto"

# --------------------------------------------------------------------------
# 展示结构：主页面只展示「读完的书」，未读完的放次级页面
# --------------------------------------------------------------------------
# True  -> README.md 的封面墙 / 书单 / 书评只含 status == "已读" 的书；
#          其余（在读 / 想读 / 弃读）写进 UNFINISHED_FILE，README 底部留一个入口链接。
# False -> 保持旧行为，所有书平铺在 README.md 里。
PRIMARY_ONLY_READ = True
# 次级书架页面文件名（相对 README.md）；设成 "" 则不生成
UNFINISHED_FILE = "SHELF.md"
# 是否在 README 底部显示通往次级页面的链接
SHOW_UNFINISHED_LINK = True

# reading_app 画像：从数据源层面就丢掉非「已读」的书（比 PRIMARY_ONLY_READ 更彻底）。
# 注意：开启后次级页面也会是空的，一般保持 False，用 PRIMARY_ONLY_READ 分区即可。
READING_APP_ONLY_READ = False

# --------------------------------------------------------------------------
# 封面设置
# --------------------------------------------------------------------------
# 是否展示封面（关掉后 README 退回纯文字书单）
SHOW_COVERS = True
# 书单表格里的「封面」列
SHOW_COVER_IN_TABLE = True
# 顶部「封面墙」网格（每本书一张大一点的图，点开可看大图）
SHOW_COVER_WALL = True
COVER_WALL_COLUMNS = 6      # 每行几本
COVER_WALL_WIDTH = 96       # 封面墙图片宽度 px
COVER_TABLE_WIDTH = 44      # 表格缩略图宽度 px
COVER_WALL_TITLE_MAX = 12   # 封面墙里书名最多显示几个字（超出省略，alt 里有全名）

# 封面文件存放目录（相对 README.md），会一起提交进仓库
COVER_DIR = "covers"
# GitHub README 渲染层不会把 <img src="covers/x.jpg"> 的相对地址重写成可访问的绝对地址
# （实测 /markdown 与 /readme 渲染接口都原样返回相对路径），所以 README 里必须写绝对地址。
# 换仓库 / 改分支时改这一行；留空则退回相对路径（适合非 GitHub 场景）。
COVER_BASE_URL = "https://raw.githubusercontent.com/SayangChun/Reading/main"
# 是否从源仓库的 raw/BOOK.db 里兜底读取封面链接
COVER_USE_SOURCE_DB = True
# 下载并发数 / 单张超时（秒）
COVER_WORKERS = 6
COVER_TIMEOUT = 15

# 数据库里也找不到封面时，是否用公开图书 API（Google Books）按书名+作者兜底搜封面。
# 只在缺封面时请求，命中过一次就会缓存到 covers/，不会每次同步都查。
COVER_API_FALLBACK = True
COVER_API_TIMEOUT = 10

# 手动封面映射文件（放在仓库根目录，可选）。格式：{"书名或书籍ID": "https://...封面图"}
# 优先级最高，用来兜住自动渠道都找不到的书。文件不存在时自动跳过。
COVER_OVERRIDES_FILE = "covers.json"
