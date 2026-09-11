# Monash ED Downloader

一个只读同步自己有权访问的 Ed Discussions、Lessons 和非媒体附件的 macOS 工具。

项目使用独立 Chrome 登录 Monash SSO/MFA。登录资料和增量数据库保存在 macOS
Application Support，课程资料默认保存在桌面的 `Monash ED Downloads`，不会放入 Git。

当前正在分阶段实现。最终日常入口是双击 `Monash ED Downloader.command`。
