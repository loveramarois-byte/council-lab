# Changelog

所有重要变化记录在此文件。版本遵循 Semantic Versioning。

## [Unreleased]

## [0.3.0] - 2026-07-28

### Added

- 增加资料空间，可导入文字、公开网页、PDF、DOCX、Markdown、CSV、JSON 和 TXT，并在 Run 中冻结 SHA-256 资料快照与 `[S1]` 引用。
- 增加开放讨论、决策评审、风险审计、资料研判和事前验尸五种审议模板，以及最近项目结论上下文。
- 增加 Markdown 与自包含 HTML 报告导出。
- 增加 12 案例可重复评测框架、三种策略执行数据、匿名盲评材料和人工评分汇总。
- 增加无需系统 Python/Node 的 macOS 与 Windows 自包含 Release 构建、打包后 Smoke test 和桌面快捷方式。
- Release 同时发布 `SHA256SUMS.txt`，便于校验下载包完整性。

### Changed

- 模型设置改为面向新手的凭据 → 模型 → 验证流程；“保存并测试”会先保存密钥、获取模型、选择模型，再执行最小生成测试。
- 用 `model_source` 明确区分 Provider 实时目录、CC Switch 近期成功记录、内置 Mock 与离线推荐，不再把推荐模型冒充账号实际可用模型。
- CC Switch 不可达或模型目录为空时显示可操作提示，不再仅凭 Council 自身可运行就宣称路由已连接。
- 全站更新为克制的暖纸张、墨色文字与陶土强调色界面，并保留单屏工作台和内部滚动讨论。
- 首页把资料、模板、历史上下文和运行档位整合进同一视口；讨论页增加逐席公开批注与资料来源条。
- 中英文安装说明同时覆盖 macOS 与 Windows 普通用户，并明确签名、公证与源码依赖边界。

### Security

- 网页资料导入限制公开 HTTP/HTTPS 目标、DNS 解析、重定向、响应类型和大小，拒绝本机、内网、云元数据与保留地址。
- API Key 继续只保存到系统凭据库；资料删除不会静默删除历史 Run 中已冻结的审计快照。

## [0.2.2] - 2026-07-28

### Added

- 增加 Windows 10 / 11 双击安装、启动和停止入口，并自动创建桌面快捷方式。
- GitHub Release 同时生成 macOS 与 Windows 下载包，CI 增加 `windows-latest` 脚本校验。
- 后端依赖锁文件改为跨平台解析，Windows 自动跳过不兼容的 `uvloop` 并安装系统凭据库支持。

## [0.2.1] - 2026-07-28

### Fixed

- 将默认 Provider 累计 Token 边界从 12k 调整为 40k，覆盖 CC Switch Codex 路径每次约 4k-5k 的基础 instructions 开销。
- 圆桌页分开显示单次讨论上下文与 Provider 全程累计 usage，避免把 `630 / 4000` 与全局限额混为一谈。
- 达到调用或 Token 边界的 Run 可提高限额并从未完成席位继续，已完成席位不会重复请求。

## [0.2.0] - 2026-07-27

### Added

- 四个讨论席与总结席的独立 Provider/model 配置、SQLite 持久化和 Run 快照。
- 第四席之后的用户确认点，支持多次最终补充再生成答案。
- 启动扫描与 checkpoint 恢复，以及缺少 checkpoint/凭据时的可恢复失败状态。
- 模型调用数、累计 Token 和完整运行时间的后端强制边界。
- Provider 原生 reasoning 能力标识和逐席实际 Provider/model 记录。

### Changed

- 用确定性上下文裁剪替代未实现的语义摘要描述。
- 最终结论改为定性“未核验”，仅从明确表态中提取分歧。
- 设置与评测页面只展示真实持久化配置和真实可用数据。
- 四席结束后默认不再自动总结。

### Security

- 自定义 Provider 在连接前解析全部 DNS 结果并拒绝 metadata、link-local、unspecified、multicast 和 reserved 目标。
- 所有临时与运行期 HTTP 客户端在成功、失败和取消路径关闭。

### Removed

- 未实现的联网核验、代码沙箱、附件、美元预算和静态设置控件。
- 将所有工作流档位宣称为上游原生 Low / High / Ultra 的误导文案。

## [0.1.0] - 2026-07-21

### Added

- LangGraph 四席顺序讨论、用户插话、持久 checkpoint 和自动总结。
- CC Switch、DeepSeek、智谱 GLM、Kimi、硅基流动、OpenAI 与自定义兼容 Provider。
- 跨平台用户数据目录、系统凭据库、模型自动识别和 macOS 启动器。
- 开源许可证、贡献、安全、行为规范、持续集成与 Release 工作流。
