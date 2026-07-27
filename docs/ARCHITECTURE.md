# Architecture

Council Lab 采用本地优先的 FastAPI + Next.js 架构。浏览器只访问本地后端；后端负责 LangGraph 工作流、Provider、上下文预算、运行状态和安全边界。

核心流程是可恢复的有限状态图：`dispatch -> turn x 4 -> awaiting_final_input -> finalize`。四个席位按固定顺序调用各自配置的 Provider/model，每席读取公开记录并明确认同、部分认同或反驳。第四席完成后默认停在用户确认点；用户可以补充一次或多次，或直接触发总结席的第五次调用。中途和最终补充都写入公开记录。

五席配置持久化在应用设置中。创建 Run 时，Provider 公共配置、协议、模型、reasoning effort、超时和输出上限被复制为 Run 快照；后续修改或删除 Provider 不会改写历史 Run。单席调用失败不会静默切换到 Mock 或其他 Provider。

运行数据分成两个 SQLite 文件：

- `council.sqlite3` 保存应用设置、完整公开 Run、五席快照、发言、最终答案、用量和上下文快照。
- `council.checkpoints.sqlite3` 由 LangGraph SQLite saver 保存节点状态。

数据库不存放在源码树。默认使用平台用户数据目录，macOS 为 `~/Library/Application Support/Council/data/`，Linux 为 `${XDG_DATA_HOME:-~/.local/share}/council/data/`，Windows 为 `%LOCALAPPDATA%\\Council\\data\\`；测试和部署可用 `COUNCIL_DATA_DIR` 覆盖。

业务记录和 checkpoint 分库，避免两个写入器争用同一个 SQLite 写锁。启动时扫描 `queued` 与 `running` Run：存在有效 checkpoint 且凭据可用时，工作流使用同一 `thread_id` 续跑；业务库已完整保存的席位会被跳过，避免 checkpoint 落后造成重复计费。缺少 checkpoint 或凭据时不回退 Mock，而是进入带原因的可恢复失败状态。`awaiting_final_input` 会保持等待，不会在重启后自行总结。

上下文管理将不可变的完整公开日志与每次模型调用使用的工作上下文分离。工作上下文始终优先保留原始问题、最新用户插话和最近发言；超出模式预算时，从较早内容中确定性选取最旧、中段和较新锚点并裁剪。该过程不调用模型，也不是语义摘要。默认单次上下文预算为 Quick 1800、Standard 4000、Rigorous 7000 个估算 Token。原始发言不会因裁剪而从 Run 中删除。

模型适配层保持薄接口：`health_check`、`list_models`、`generate` 和 `aclose`。Provider 注册表集中维护官方地址、推荐模型、协议、能力和文档入口；远程 `/models` 成功时覆盖推荐列表，失败时保留本地回退。Mock Provider 让自动化测试无需密钥。自动协议策略先尝试 Responses，只有明确的 404/405/501 才回退 Chat Completions；只有声明支持原生 reasoning 的 Responses Provider 才接收 effort，普通 Chat Completions Provider 只应用 Council 的上下文和流程档位。

每次模型请求前执行真实边界检查：默认最多 8 次尝试（失败请求也计算）、12,000 累计 Token、120 秒完整运行时间。达到边界后 Run 进入 `stopped`，保留已经完成的公开发言。由于没有稳定的跨 Provider 定价数据，系统不伪造美元预算。

Provider API Key 使用 `keyring` 交给平台凭据库。SQLite 只保存 `credential_saved` 标记与环境变量名，公开 Provider 响应只暴露 `has_api_key` 和 `credential_source`。运行时优先读取环境变量，其次读取系统凭据库。

默认关闭第三方追踪，不记录 Authorization、Cookie、完整 API Key、用户敏感文件或隐藏思维链。Provider 地址检查会解析 DNS 并拒绝 metadata、link-local、unspecified、multicast 与 reserved 目标；自定义本地 Provider 可使用 private/loopback，CC Switch 只接受 loopback。DNS rebinding 仍是剩余风险。
