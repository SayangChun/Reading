# 阅读同步 · 部署说明

本仓库（`SayangChun/Reading`）用来公开展示**读过的书和书评**；
真实读书记录在**私有**仓库 `SayangChun/yuedujilu_backup` 里维护。
一个 GitHub Action 每天自动渲染两个页面：
`README.md`（只放已读完的书）和 `SHELF.md`（在读 / 想读 / 弃读的次级书架）。

## 目录结构
```
Reading/
├── .github/workflows/sync.yml   # 定时 + 手动触发的工作流
├── scripts/generate_readme.py   # 生成器（零依赖，标准库即可）
├── scripts/covers.py            # 封面解析 + 下载 + 本地化（零依赖）
├── scripts/test_covers.py       # 封面自动化的离线回归测试（python scripts/test_covers.py）
├── scripts/config.py            # 字段映射 / 封面与渲染选项（按需改）
├── covers/                      # 自动生成并提交的封面图片（29 张约 1 MB）
├── books.example.json           # 数据源期望格式的样例（仅供参考，不进生成）
├── README.md                    # 主页面：已读的书 + 封面墙 + 书评，自动生成，勿手改
└── SHELF.md                     # 次级页面：未读完的书，自动生成，勿手改
```

## 数据源格式要求
`yuedujilu_backup` 是「阅读记录」App 的**结构化备份**，真实结构如下（生成器已内置适配，
自动识别为 `reading_app` 画像）：

- `data/books.json`：`{ "books": [...] }`，每本含 `name`(书名) / `author` / `category`(分类) /
  `status`(想读·在读·已读·弃读) / `score`(0–5，0 表示未评) / `isbn` / `note_count` / `review_count`。
  **没有封面字段、没有阅读日期、isbn 也全为空** —— 封面改从下面的原始数据库里取。
- `raw/BOOK.db`：App 原始 SQLite 备份，`BOOKLISTTABLE.coverUrl` 里存着每本书的封面链接
  （29/29 本都有），生成器按规范化书名**精确匹配**（避免《强风吹拂》与《强风吹拂（影视）》串图）。
- `data/reviews.json`：`{ "reviews": [...] }`，书评按 `book_id` 关联；`title`/`content` 可能为空（空的不展示）。
- `data/notes.json`：`{ "notes": [...] }`，书摘（338 条）。**书摘/笔记不在公开 README 中展示**，仅作内部参考。

生成器对 `reading_app` 画像会：

- 用 `books.json` 出书单表格：书名 / 作者 / 评分 / 状态 / 分类 / 阅读日期 / 书评；
- **按 `book_id` 把书评关联到对应书**，非空才在「书评」列与末尾 `<details>` 折叠区展示；
- 阅读日期缺失时，用该书书评日期推导（无书评则留空）；
- `score` 为 0 → 显示「未评」；越界值（数据里偶发 9/10）→ 封顶星数并如实标注；
- 顶部统计：已读本数、书评篇数、累计阅读时长（不含书摘/笔记）。

> 若以后数据源换成单文件/目录式（JSON/CSV/Markdown/frontmatter），生成器会自动回退到
> `generic` 画像，照样能跑（那种格式支持中英文字段、frontmatter、`books/` 目录等）。
> 该画像没有「状态」字段，所有书仍平铺在 README.md 里。

## 展示结构：主页面只放读完的书

`scripts/config.py` 里的 `PRIMARY_ONLY_READ = True`（默认）会把书分成两层：

| 页面 | 内容 |
| --- | --- |
| `README.md` | `status == 已读` 的书：封面墙、书单表格、书评折叠区。底部只留一行通往次级页面的链接 |
| `SHELF.md` | 在读 / 想读 / 弃读的书：封面墙 + 简表（封面 / 书名 / 作者 / 状态 / 分类） |

相关配置：

| 配置 | 默认 | 作用 |
| --- | --- | --- |
| `PRIMARY_ONLY_READ` | `True` | 改成 `False` 恢复旧行为：所有书平铺在 README.md |
| `UNFINISHED_FILE` | `SHELF.md` | 次级页面文件名；设成 `""` 则不生成 |
| `SHOW_UNFINISHED_LINK` | `True` | 是否在 README 底部显示次级页面入口 |
| `READING_APP_ONLY_READ` | `False` | 更彻底：从数据源层面直接丢掉非已读的书（**开启后 SHELF.md 会是空的**，一般用不到） |

一本书从「在读」变成「已读」后，下次同步会自动从 SHELF.md 移到 README.md，封面无需重新下载。

## 封面

两个页面顶部都有「封面墙」网格（每行 6 本，点击封面看大图），书单表格里也有一列缩略图。
**封面图会下载并保存在本仓库 `covers/`，README 里写成 `raw.githubusercontent.com` 的绝对地址**，
而不是直接外链到读书 App 的 CDN：

- 第三方 CDN 链接可能过期 / 防盗链 / 走 http 302，GitHub 图片代理未必取得到；
- 存进仓库后永久可用，也不依赖每天同步时的网络状况；
- **不能用相对路径**：实测 GitHub 的 `/markdown` 与 `/readme` 渲染接口都会把
  `<img src="covers/x.jpg">` 原样返回、不重写成绝对地址，浏览器会解析到
  `github.com/owner/repo/covers/x.jpg` 而得到破图。绝对前缀由 `COVER_BASE_URL` 配置，
  换仓库或改分支时改这一行。

封面来源按优先级：`covers.json` 手动映射 → 记录自带的 `cover` 字段 →
`raw/BOOK.db` 的 `coverUrl`（含 `CALENDER` / `TIMESTABLE` 兜底列）→ ISBN（Open Library）→
书名 + 作者（Google Books API）→ 带书名的 SVG 占位图（**不会出现破图**）。
完整说明见下面「以后新增 / 更新的书，封面会自动跟上吗」。

下载时会按**文件头**判断真实格式（URL 里写着 `.webp` 的图经 OSS 转码后实际返回 JPEG，不能信扩展名），
校验失败或超时的会重试一次，再失败就用占位图。已经下载好的封面会被复用，日常同步零网络请求，
只有新增书籍或加 `--refresh-covers` 才会重新下载。

相关开关都在 `scripts/config.py`：

| 配置 | 默认 | 作用 |
| --- | --- | --- |
| `SHOW_COVERS` | `True` | 总开关，关掉后 README 退回纯文字书单 |
| `SHOW_COVER_WALL` | `True` | 是否显示顶部封面墙 |
| `SHOW_COVER_IN_TABLE` | `True` | 是否显示表格封面列 |
| `COVER_WALL_COLUMNS` / `COVER_WALL_WIDTH` | `6` / `96` | 封面墙每行本数 / 图片宽度 px |
| `COVER_DIR` | `covers` | 封面存放目录 |
| `COVER_BASE_URL` | `https://raw.githubusercontent.com/SayangChun/Reading/main` | README 里封面地址的绝对前缀；留空则退回相对路径 |
| `COVER_USE_SOURCE_DB` | `True` | 是否从原始 SQLite 备份里读封面链接 |
| `COVER_API_FALLBACK` | `True` | 缺封面时是否查公开图书 API |

命令行可调：`--no-covers`（本次不处理封面）、`--offline`（只用本地缓存，不联网）、
`--refresh-covers`（强制重下全部）、`--no-db-covers`（不读数据库）、
`--no-api-covers`（不查 API）、`--covers-dir`（换目录）。

> 删掉某本书后，对应的旧封面文件会留在 `covers/` 里（无害，不会出现在 README 中），
> 想清理直接删文件即可。

### 以后新增 / 更新的书，封面会自动跟上吗

会 —— 前提是同步 Action 每天能正常跑（配置见下面「你只需要做一件事」）。链路：

1. 在「阅读记录」App 里加书或换封面后，跑源库的 `scripts/sync.py` + `scripts/export.py`。
   `export.py` 会把 App 的 `BOOK.db` 重新复制成 `raw/BOOK.db`（含新书的 `coverUrl`），
   这个文件已被源库 git 跟踪，push 之后 CI 就能读到。
2. Reading 的 Action 检出最新源库 → 生成器按规范化书名匹配到 `coverUrl` →
   下载进 `covers/` → 按「已读 / 未读完」写进 `README.md` 或 `SHELF.md` → 自动提交。
   **新书的 ID 不同，会自然触发下载。**
3. 某本书换了封面时，`covers/_sources.json` 里记的 URL 会变，生成器自动重下并覆盖；
   没变化的书全部走本地缓存，零网络请求。原来是占位图的书后来有了封面，也会自动升级。

数据库里也找不到封面时（手工改了 `data/books.json` 没走导出、App 里自建的无封面书等），
依次兜底：记录里的 `cover` 字段 → ISBN（Open Library）→ 书名 + 作者（Google Books API，
带书名相关性校验防止配错封面）→ 带书名的 SVG 占位图。API 只在缺封面时请求，
命中一次就缓存；日志会打印「以下 N 本暂用占位图」，方便发现漏网的书。

最后的人工兜底是仓库根目录下的 `covers.json`（可选，文件不存在就跳过）：

```json
{
  "百年孤独": "https://example.com/cover.jpg",
  "bk_003": "https://example.com/another.jpg"
}
```

键可以写书名，也可以写源数据的书籍 ID（如 `bk_003`），优先级高于所有自动渠道。
改完提交，下次同步即生效。

> 本机网络到 Google Books / Open Library 走代理会 502，所以**本地生成时 API 兜底通常不生效**；
> GitHub Actions 的海外 runner 能正常访问。想完全离线跑加 `--offline`（只用缓存和占位图），
> 不想用 API 兜底加 `--no-api-covers`。

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
# 用样例数据生成一次，看 README 长什么样（样例外链是 example.com，会自动出占位图）
python scripts/generate_readme.py --source data --output README.md

# 直接指向本地备份目录（Windows 下用 E:/... 这种写法，别用 /e/...，否则 Python 找不到）
# 这条会生成 README.md + SHELF.md，并把封面下载到 covers/
python scripts/generate_readme.py --source E:/project/yuedujilu_backup --output README.md
# 真实跑时，GitHub 上 source 指向 workflow 检出的 yuedujilu_backup（相对路径 source/）
# 只想重排文字、不动封面：加 --offline
# 回归测试（打桩网络，验证新增书 / 换封面 / 兜底逻辑）：python scripts/test_covers.py
```

## 常见问题
- **封面不显示 / 显示成破图**：先确认 `covers/` 已随提交推到 GitHub（工作流
  `file_pattern` 里包含 `covers/`），再确认 `COVER_BASE_URL` 里的 owner / repo / 分支
  与实际情况一致。相对路径一定不行，原因见上面「封面」一节。
- **封面显示成占位图**：本地跑一次看日志里的封面统计与「以下 N 本暂用占位图」提示，
  按需往 `covers.json` 里补手动映射。
- **主页面怎么只有 6 本**：这是设计如此，未读完的在 `SHELF.md`。想让所有书回到
  README，把 `PRIMARY_ONLY_READ` 改成 `False`。
- **只想本地重排、不想联网**：加 `--offline`，会直接复用 `covers/` 里已有的图。
- **书评太长**：纯文本书评会自动收进 README 末尾的 `<details>` 折叠区，不占表格空间。
- **首次运行失败**：多半是私有库没配 `SOURCE_TOKEN`，或数据源文件名/格式不符。
