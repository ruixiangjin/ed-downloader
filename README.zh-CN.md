[English](README.md) | [**简体中文**](README.zh-CN.md)

# Monash ED Downloader

一个只读的 macOS 命令行工具，用于同步本人账户有权访问的 Ed Discussions、Lessons 和
非媒体附件，方便离线学习。它使用独立的 Chrome Profile 完成 Monash SSO 和 MFA，
并且不会读取 Ed Workspace。

登录资料和增量数据库保存在 macOS Application Support 中。课程资料默认保存到
`~/Desktop/Monash ED Downloads`，位于 Git 仓库之外。

## 保存内容

- 为每门课程生成一个永久的 Discussions JSON 文件，其中包括帖子、答案、评论、分类、
  答案采纳状态、作者、角色、时间、图片链接和增量 Tag。
- 将 Lesson 文字、支持的 Slide 内容、Quiz 题目和选项，以及 Ed 指定的 `webpage` Lesson
  保存为 Markdown。
- 下载 PDF、Office、ZIP、CSV、文本、代码和其他已确认直接指向文件的非媒体附件。
- 生成带版本的 `<课程名称> - Last Sync.json`，记录最近一次检测到的 Lesson 分组、
  Lesson 结构、资源状态和同步结果。
- 普通外部网页和所有媒体只保留链接。

图片、视频、音频和字体不会下载。普通外部网页只记录链接；当 Ed 本身把某个 Lesson Slide
定义为 `webpage` 时，该网页会被视为课程正文并保存为 Markdown。这一规则覆盖 FIT2109 等
课程使用的外部托管课文。ZIP 文件只保存而不解压，下载的文档也不会转换格式。

## 环境要求与安装

- 装有 Google Chrome 的 macOS
- Python 3.12 或更新版本
- [uv](https://docs.astral.sh/uv/)

```console
git clone https://github.com/ruixiangjin/ed-downloader.git
cd ed-downloader
uv sync --all-groups
uv run ed-downloader --help
```

可以在仓库目录中使用 `uv run ed-downloader ...`；如果希望在任何位置使用较短的
`ed-downloader ...` 命令，可以执行一次 `uv tool install .`。

## 首次登录

```console
uv run ed-downloader login
uv run ed-downloader doctor
uv run ed-downloader courses
uv run ed-downloader menu
```

`login` 会打开一个独立的 Chrome 窗口。请只在该窗口中完成 Monash SSO 和 MFA；等到 Ed
课程页面出现后，回到终端按 Enter。本工具绝不会接收或保存你的密码和验证码。它会检查页面上
是否出现可见的登录用户，而不会因为浏览器 Profile 已经存在就误判为登录成功。

如果之后的命令检测到会话已过期，工具会清除登录确认、打开登录流程，然后重试一次原操作。
你也可以手动再次运行 `ed-downloader login`。

`courses` 和 `menu` 会分开显示当前课程和按学期归档的课程。仍然可以通过课程代码或 Ed
数字课程 ID，手动选择一门归档课程。

## 交互式终端菜单

运行 `uv run ed-downloader menu`，或者在 Finder 中双击 `Monash ED Downloader.command`。
启动器会根据自身位置找到仓库，因此其中不包含用户专属路径。

菜单提供以下选项：

1. 增量同步所有当前课程的 Discussions 和 Lessons。
2. 选择一门当前课程或按学期归档的课程，然后同步整门课程。
3. 选择一门课程，然后只同步 Discussions 或只同步全部 Lessons。
4. 选择一门课程，然后输入一个或多个可用 Week/Module 序号，例如 `1`、`1,3-5` 或
   `1，3～5`。

“所有当前课程”操作不包括归档课程。如果 Ed 的页面结构发生变化，导致工具无法安全区分当前
课程和归档课程，批量同步会被禁用，你必须逐门选择。每次操作后菜单都会保持打开，直到你明确
选择 `0 Exit`。

如果某门课程没有可下载的 Lessons，工具会跳过其 Lesson 内容，但不会妨碍保存 Discussions。

## 扫描与同步

```console
# 列出课程中可用的 Lesson 分组，但不下载文件
uv run ed-downloader scan --course FIT2109

# 增量同步一门课程，或只同步一种内容
uv run ed-downloader sync --course FIT2109
uv run ed-downloader sync --course FIT2109 --scope discussions
uv run ed-downloader sync --course FIT2109 --scope lessons

# 按显示的序号同步指定 Lesson 分组
uv run ed-downloader sync --course FIT2109 --scope lessons --groups "1,3-5"

# 同步所有当前课程，不包括归档课程
uv run ed-downloader sync --all

# 强制完整检查 Discussions，或重新获取 Lesson 附件内容
uv run ed-downloader sync --course FIT2109 --full
uv run ed-downloader sync --course FIT2109 --scope lessons --refresh
```

普通同步必须且只能指定一个 `--course`；只有明确使用 `--all` 才会选择所有课程。
课程代码和 Ed 数字课程 ID 均可使用。`--groups` 只适用于 Lessons，并且不能与 `--all`
同时使用。如果需要看到自动操作的浏览器，请使用 `--headed`；使用
`--output /其他/文件夹` 可以选择不同的资料目录。

默认输出目录是 `~/Desktop/Monash ED Downloads`，结构如下：

```text
课程名称/
├── Discussions/
│   └── 课程名称 - Discussions.json
└── Lessons/
    ├── 课程名称 - Lessons.md
    ├── 课程名称 - Last Sync.json
    └── 01-Week 或 Module 名称/
        └── 01-Lesson 名称/
            ├── Lesson 名称.md
            └── Files/
```

Lessons 索引会链接到每个生成的 Lesson Markdown 文件。这些文件使用相对链接指向已下载的
附件，并为媒体、普通外部网页和不支持的 Slide 类型保留来源链接。

## 增量行为

每门课程的 Discussions 保存在一个永久 JSON 文件中。首次运行、每第十次运行，以及使用
`--full` 的运行都会检查完整帖子列表。其他运行使用 Ed 的最近动态和已知回复数量寻找新增或
变化的帖子。已有帖子、答案和评论会按 ID 合并，并用 Tag 记录首次出现、最后一次出现和最后一次
变化的时间点。安全检查会阻止可疑的不完整全量抓取，避免其覆盖正常数据。

对于 Lesson 附件，私有 SQLite 状态会记录 ETag、Last-Modified、大小、SHA-256 和本地路径。
之后同步时，程序会先使用远端元数据判断，再决定是否请求文件内容：

- 本地未变化的文件不会重复下载；
- 已变化的文件和被手动删除的本地文件会重新下载；
- 中断的传输使用临时 `.part` 文件，完成后再进行原子重命名；
- 从 Ed 移除的文件或分组会被记录为 `missing_remote`，但不会删除本地副本；
- `--refresh` 会有意绕过 Lesson 附件的“未变化”检查。

如果 Ed 指定的网页或 Quiz 无法刷新，但以前成功保存过副本，工具会保留该副本，而不会丢弃。
每次同步都会汇总 Discussions 的变化，以及已下载、未变化、作为媒体跳过或只保留链接的 Lesson
资源。

## 隐私与仓库安全

Ed 专用浏览器 Profile、登录确认、浏览器存储和 SQLite 数据库位于
`~/Library/Application Support/Monash ED Downloader/`。下载的资料位于仓库之外；
`.gitignore` 会排除常见凭据、数据库、未完成文件和输出目录。导出的 URL 会移除常见 Token
和临时签名查询参数，HTML 登录页面也不会被保存为附件。

发布更改前仍应检查 `git status`，不要提交课程资料或登录数据。只访问你自己的 Monash
账户有权使用的资料。

API Token 登录计划在浏览器版本的行为稳定后作为独立阶段加入。未来的 Token 会保存在 macOS
Keychain 中，而不会写入仓库、资料目录、日志或 SQLite 数据库。

## 故障排查

- **需要登录：** 运行 `uv run ed-downloader login`，完成 SSO/MFA，确认 Ed 课程页面已经
  出现，然后回到终端按 Enter。
- **找不到课程或课程代码不唯一：** 运行 `uv run ed-downloader courses`，使用其中显示的
  课程代码或 Ed 数字 ID。如果课程代码重复，请使用数字 ID。
- **批量同步被拒绝：** 无法安全判断 Ed Dashboard 上的课程分类。请逐门选择，不要猜测哪些是
  当前课程。
- **课程没有 Lessons：** 这是允许的。Lesson 内容会被跳过，Discussions 仍可正常同步。
- **文件或网页失败：** 重试同步。已完成的文件和之前保存的网页内容会保持完整，未完成的
  `.part` 文件不会被当作完整下载结果。
- **需要完全重新获取 Lesson：** 添加 `--refresh`；这会消耗更多网络流量。如果需要完整检查
  Discussions，请另外使用 `--full`。

## 开发检查

GitHub Actions 只运行匿名离线 fixture 和模拟 HTTP 响应。它绝不会登录 Ed，也不会下载真实
课程资料。

```console
uv run ruff format --check .
uv run ruff check .
uv run mypy src tests
uv run pytest
```
