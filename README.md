# Monash ED Downloader

一个只读同步自己有权访问的 Ed Discussions、Lessons 和非媒体附件的 macOS 工具。

项目使用独立 Chrome 登录 Monash SSO/MFA。登录资料和增量数据库保存在 macOS
Application Support，课程资料默认保存在桌面的 `Monash ED Downloads`，不会放入 Git。

## 保存范围

- Discussions：每门课程一个永久 JSON，保留帖子、答案、评论和增量 Tag。
- Lessons：课程文字和 Ed 指定的网页课文保存为 Markdown。
- PDF、Office、ZIP、CSV、文本、代码和其他非媒体附件保存到本地。
- 图片、视频、音频和字体不下载，只保留网址。
- Workspace 不读取。

普通外部网页只记录链接；如果网页本身是 Ed Lessons 中的 `webpage` 页面，则把它视为
课程正文并保存为 Markdown。这一规则覆盖 FIT2109 使用的外部托管课文。

## 安装与登录

要求 macOS、Google Chrome、Python 3.12 或更新版本，以及
[uv](https://docs.astral.sh/uv/)。

```console
uv sync --all-groups
uv run ed-downloader login
uv run ed-downloader doctor
```

登录会打开独立 Chrome。密码和 MFA 验证码只在浏览器中填写，程序不会请求或保存。

## 日常使用

推荐在 Finder 中双击 `Monash ED Downloader.command`。菜单会：

1. 一键同步所有当前课程的 Discussions 和 Lessons。
2. 分开显示当前课程和按学期归档的课程。
3. 对单门课同步全部内容、仅 Discussions、全部 Lessons，或选择 Week／Module。
4. 每次操作后返回主菜单，直到选择 Exit。

终端也可以使用：

```console
uv run ed-downloader courses
uv run ed-downloader scan --course FIT2109
uv run ed-downloader sync --course FIT2109
uv run ed-downloader sync --course FIT2109 --scope lessons --groups "1,3-5"
uv run ed-downloader sync --all
```

没有 Lessons 的课程会自动跳过课程内容。“一键同步所有”不会包含归档课程。如果 Ed 页面
结构变化、程序无法可靠区分当前和归档课程，它会禁止批量同步并要求逐门选择。

## 增量与安全

下载状态记录 ETag、Last-Modified、Content-Length、SHA-256 和本地路径。未变化内容会复用，
本地文件缺失时补下，远端消失时保留本地副本并记录。下载先写 `.part`，完成后原子改名。
HTML 登录页不会保存成附件，导出的 URL 会移除常见 Token 和临时签名参数。

Ed 登录 Profile 和 SQLite 位于 `~/Library/Application Support/Monash ED Downloader/`；资料
位于 `~/Desktop/Monash ED Downloads/`。两者都不在仓库内。

## 开发检查

公开仓库测试只使用匿名 fixture 和模拟响应，不登录 Ed，也不下载真实课程资料。

```console
uv run ruff format --check .
uv run ruff check .
uv run mypy src tests
uv run pytest
```

API Token 登录将在浏览器版验证稳定后作为独立阶段加入。Token 将保存在 macOS Keychain，
不会写入仓库、资料目录、日志或 SQLite。
