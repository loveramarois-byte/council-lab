# Architecture

Council Lab 采用本地优先的 FastAPI + Next.js 架构。浏览器只访问本地后端；后端负责 LangGraph 工作流、Provider、上下文预算、运行状态和工具边界。

核心流程是可恢复的有限状态图：`dispatch -> turn x 4 -> finalize`。四个席位按固定顺序独立调用同一模型，每席读取公开记录并明确认同、部分认同或反驳；第五次独立调用由记录员形成最终答案。用户插话写入公开记录，后续席位会在自己的独立请求中读取。

运行数据分成两个 SQLite 文件：

- `council.sqlite3` 保存完整公开 Run、发言、最终答案、用量和上下文快照。
- `council.checkpoints.sqlite3` 由 LangGraph SQLite saver 保存节点状态。

数据库不存放在源码树。默认使用平台用户数据目录，macOS 为 `~/Library/Application Support/Council/data/`，Linux 为 `${XDG_DATA_HOME:-~/.local/share}/council/data/`，Windows 为 `%LOCALAPPDATA%\\Council\\data\\`；测试和部署可用 `COUNCIL_DATA_DIR` 覆盖。

业务记录和 checkpoint 分库，避免两个写入器争用同一个 SQLite 写锁。模型超时、进程重启或用户主动重试后，工作流使用同一 `thread_id` 从失败节点前恢复，不重跑已经完成的席位。

上下文管理将不可变的完整公开日志与每次模型调用使用的工作上下文分离。工作上下文始终优先保留原始问题、最新用户插话和最近发言；超出模式预算时，较早内容折叠成滚动摘要。默认单次上下文预算为 Quick 1800、Standard 4000、Rigorous 7000 个估算 Token。原始发言不会因压缩而从 Run 中删除。

模型适配层保持薄接口：`health_check`、`list_models` 和 `generate`。Provider 注册表集中维护官方地址、推荐模型、协议和文档入口；远程 `/models` 成功时覆盖推荐列表，失败时保留本地回退。Mock Provider 让自动化测试无需密钥；OpenAI、普通 OpenAI 兼容入口和 CC Switch 使用同一兼容适配。自动协议策略先尝试 Responses，只有明确的 404/405/501 才回退 Chat Completions。

Provider API Key 使用 `keyring` 交给平台凭据库。SQLite 只保存 `credential_saved` 标记与环境变量名，公开 Provider 响应只暴露 `has_api_key` 和 `credential_source`。运行时优先读取环境变量，其次读取系统凭据库。

默认关闭第三方追踪，不记录 Authorization、Cookie、完整 API Key、用户敏感文件或隐藏思维链。CC Switch 地址默认只接受 loopback，并拒绝云元数据地址。
