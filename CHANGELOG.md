# Changelog

所有重要变化记录在此文件。版本遵循 Semantic Versioning。

## [Unreleased]

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
