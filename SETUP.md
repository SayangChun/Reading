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
`yuedujilu_backup` 仓库里放读书记录，**以下格式都能自动识别**（根目录、或 `books/`、`data/` 子目录均可）：

- `books.json`：对象数组，每条一本书（见 `books.example.json`）
- `books.csv`：一行一本书，表头用中/英文字段名
- `books.md`：单文件，每本书一个 `## 标题`，下面用 `- 作者: xxx` / `- 评分: 4.5` /
  `- 阅读日期: 2024-11-12` / `- 标签: 科幻, 哲学`，正文作为书评
- **`books/` 目录下一堆 `.md`**：每本一个文件（最常用于"阅读日记"式仓库）
- **Markdown + YAML frontmatter**：每篇 `.md` 顶部用 `---` 包裹 `key: value`
  元数据（Hugo/Jekyll 风格），正文作书评。例如：
  ```markdown
  ---
  title: 置身事内
  author: 兰小欢
  rating: 4.5
  date: 2024-11-12
  tags: [中国经济, 政治经济学]
  cover: https://.../cover.jpg
  ---
  书评正文……
  ```
  frontmatter 里的 `tags` 支持 `[a, b]` 列表或 `a, b` 逗号串。

字段名中英文都认（书名/作者/评分/阅读日期/标签/书评/封面），
详见 `scripts/config.py` 的 `FIELD_MAP`，缺什么往里加即可。

### 本地调试字段识别
不确定你的字段名有没有被认出来？用 `--dump-fields` 看一眼：
```bash
python scripts/generate_readme.py --source <目录> --dump-fields
```
它会列出每个文件识别到的归一化字段；没认出来的，去 `config.py` 加别名即可。

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
# 注意：data/ 里放的是样例；真实跑时 source 指向检出后的 yuedujilu_backup
```

## 常见问题
- **封面不显示**：封面字段必须是 `http(s)` 绝对链接；私有库里的本地图片路径
  跨仓库无法引用，建议传图床或用外链。
- **书评太长**：纯文本书评会自动收进 README 末尾的 `<details>` 折叠区，不占表格空间。
- **首次运行失败**：多半是私有库没配 `SOURCE_TOKEN`，或数据源文件名/格式不符。
