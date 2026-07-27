# Changelog

所有重要变化记录在此文件。版本遵循 Semantic Versioning。

## [Unreleased]

### Added

- LangGraph 四席顺序讨论、用户插话、持久 checkpoint 和自动总结。
- CC Switch Provider、推理档位与上游失败自动降档。
- 跨平台用户数据目录和可移植 macOS 启动器。
- 开源许可证、贡献、安全、行为规范和持续集成配置。
- DeepSeek、智谱 GLM、Kimi、硅基流动与自定义兼容 Provider 预设。
- 系统凭据库密钥保存、远程模型获取和当前供应商持久切换。
- Provider 模型自动识别；兼容 CC Switch Codex `slug` 目录，并在空目录时只读回退到近期成功模型。

### Security

- 运行数据库、日志、截图和构建产物从源码树及 Git 中排除。
- Provider 密钥不会写入业务数据库、日志或公开响应。
- Provider 密钥不进入 SQLite 或前端存储，桌面录入后交由系统凭据库保护。
