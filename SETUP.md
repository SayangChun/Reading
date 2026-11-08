# 阅读同步 · 部署说明

本仓库（`SayangChun/Reading`）用来公开展示你读过的书和书评；
真实读书记录在**私有**仓库 `SayangChun/yuedujilu_backup` 里维护。
一个 GitHub Action 每天自动把数据源渲染成根目录的 `README.md` 书单。

## 目录结构
```
Reading/
├── .github/workflows/sync.yml   # 定时 + 手动触发的工作流
├── scripts/generate_readme.py   # 生成器（零依赖，标准库即可）
├── scripts/config.py            # 字段映射 / 渲染选项（按需改）
├── books.example.json           # 数据源期望格式的样例（仅供参考，不进生成）
└── README.md                    # 自动生成，勿手改
```

## 数据源格式要求
`yuedujilu_backup` 是「阅读记录」App 的**结构化备份**，真实结构如下（生成器已内置适配，
自动识别为 `reading_app` 画像）：

- `data/books.json`：`{ "books": [...] }`，每本含 `name`(书名) / `author` / `category`(分类) /
  `status`(想读·在读·已读·弃读) / `score`(0–5，0 表示未评) / `isbn` / `note_count` / `review_count`。
  **没有封面字段、没有阅读日期**。
- `data/reviews.json`：`{ "reviews": [...] }`，书评按 `book_id` 关联；`title`/`content` 可能为空（空的不展示）。
- `data/notes.json`：`{ "notes": [...] }`，书摘（338 条）。**书摘/笔记不在公开 README 中展示**，仅作内部参考。

生成器对 `reading_app` 画像会：

- 用 `books.json` 出书单表格：书名 / 作者 / 评分 / 状态 / 分类 / 阅读日期 / 书评；
- **按 `book_id` 把书评关联到对应书**，非空才在「书评」列与末尾 `<details>` 折叠区展示；
- 阅读日期缺失时，用该书书评日期推导（无书评则留空）；
- `score` 为 0 → 显示「未评」；越界值（数据里偶发 9/10）→ 封顶星数并如实标注；
- 顶部统计：书籍总数、已读、书评篇数、累计阅读时长（不含书摘/笔记）。

**可选**：只想公开展示「已读」的书？改 `scripts/config.py` 的
`READING_APP_ONLY_READ = True`（默认 `False`，展示全部并标注状态）。

> 若以后数据源换成单文件/目录式（JSON/CSV/Markdown/frontmatter），生成器会自动回退到
> `generic` 画像，照样能跑（那种格式支持中英文字段、frontmatter、`books/` 目录等）。

### 本地调试字段识别
不确定你的字段名有没有被认出来？用 `--dump-fields` 看一眼：
```bash
python scripts/generate_readme.py --source <目录> --dump-fields
```
它会列出识别出的画像与每本书的字段；没认出来的，去 `scripts/config.py` 的 `FIELD_MAP` 加别名即可。

## 你只需要做一件事（二选一）

### 方案 A：把数据源仓库改为公开（最简单，推荐）
1. 打开 https://github.com/SayangChun/yuedujilu_backup → Settings → Change visibility → 改为 Public。
2. 工作流里的 `token: ${{ secrets.SOURCE_TOKEN || github.token }}` 会自动用
   `GITHUB_TOKEN` 读公开库，**无需任何 secret**。
3. 去 Reading 仓库 → Actions → 选 "Sync Reading List" → Run workflow 跑一次验证。

### 方案 B：保持私有 + 给读令牌
1. GitHub → 右上角头像 → Settings → Developer settings →
   Personal access tokens → Tokens (classic) → Generate new token (classic)。
2. 勾选 `repo`（整段仓库权限），生成后复制令牌。
3. 打开 https://github.com/SayangChun/Reading → Settings → Secrets and variables →
   Actions → New repository secret：
   - Name: `SOURCE_TOKEN`
   - Secret: 刚才复制的令牌
4. 去 Actions 页面手动跑一次 "Sync Reading List" 验证。

## 定时与手动
- 默认每天 **北京时间 00:00** 自动跑（`sync.yml` 里的 cron `0 16 * * *`）。
- 想立刻更新，去 Actions → Sync Reading List → Run workflow 即可。
- 改频率：编辑 `sync.yml` 里的 cron 表达式（UTC 时间）。

## 本地预览 / 调试
```bash
# 用样例数据生成一次，看 README 长什么样
python scripts/generate_readme.py --source data --output README.md

# 直接指向本地备份目录（Windows 下用 E:/... 这种写法，别用 /e/...，否则 Python 找不到）
python scripts/generate_readme.py --source E:/project/yuedujilu_backup --output README.md
# 真实跑时，GitHub 上 source 指向 workflow 检出的 yuedujilu_backup（相对路径 source/）
```

## 常见问题
- **封面不显示**：封面字段必须是 `http(s)` 绝对链接；私有库里的本地图片路径
  跨仓库无法引用，建议传图床或用外链。
- **书评太长**：纯文本书评会自动收进 README 末尾的 `<details>` 折叠区，不占表格空间。
- **首次运行失败**：多半是私有库没配 `SOURCE_TOKEN`，或数据源文件名/格式不符。
