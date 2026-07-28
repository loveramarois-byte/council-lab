# Architecture

Council Lab 采用本地优先的 FastAPI + Next.js 架构。浏览器只访问本地后端；后端负责 LangGraph 工作流、Provider、上下文预算、运行状态和安全边界。

核心流程是可恢复的有限状态图：`dispatch -> turn x 4 -> awaiting_final_input -> finalize`。四个席位按固定顺序调用各自配置的 Provider/model，每席读取公开记录并明确认同、部分认同或反驳。第四席完成后默认停在用户确认点；用户可以补充一次或多次，或直接触发总结席的第五次调用。中途和最终补充都写入公开记录。

## Feature status

| Area | Status | Boundary |
| --- | --- | --- |
| Deliberation workflow | Current | 四席顺序讨论、用户确认、第五席总结、恢复与导出均为默认产品路径。 |
| Run event replay | Current | 事件写入业务库并使用单调序号；SSE 支持 `Last-Event-ID` 重放和独立多订阅者。 |
| Mobile access | Current, local network only | 使用短期签名会话、失败限速、同源校验和手工撤销；普通 HTTP 仍只适用于可信私有网络。 |
| Diagnostics | Current, metadata only | 用户手工导出的 ZIP 只含白名单运行元数据，不含对话、日志正文、凭据、令牌、模型名或主机路径。 |
| Legacy workspace | Compatibility only | 旧项目、来源和快照保留用于历史读取；当前 UI 和新建审议不再使用该能力。 |
| Evaluation framework | Experimental | 数据集和评分脚本不构成多席优于单模型的产品声明。 |
| Network search and code sandbox | Not implemented | 模型共识不等于外部事实核验，也不会自动执行代码。 |

五席配置持久化在应用设置中。创建 Run 时，Provider 公共配置、协议、模型、reasoning effort、超时和输出上限被复制为 Run 快照；后续修改或删除 Provider 不会改写历史 Run。单席调用失败不会静默切换到 Mock 或其他 Provider。

运行数据分成两个 SQLite 文件：

- `council.sqlite3` 保存应用设置、完整公开 Run、五席快照、发言、最终答案、结果回访、用量和上下文快照。
- `council.sqlite3` 的 `run_events` 表保存实时事件及单调序号；刷新、断线或多标签订阅不会竞争消费同一个内存队列。
- `council.checkpoints.sqlite3` 由 LangGraph SQLite saver 保存节点状态。

数据库不存放在源码树。默认使用平台用户数据目录，macOS 为 `~/Library/Application Support/Council/data/`，Linux 为 `${XDG_DATA_HOME:-~/.local/share}/council/data/`，Windows 为 `%LOCALAPPDATA%\\Council\\data\\`；测试和部署可用 `COUNCIL_DATA_DIR` 覆盖。

业务记录和 checkpoint 分库，避免两个写入器争用同一个 SQLite 写锁。启动时扫描 `queued` 与 `running` Run：存在有效 checkpoint 且凭据可用时，工作流使用同一 `thread_id` 续跑；业务库已完整保存的席位会被跳过，避免 checkpoint 落后造成重复计费。缺少 checkpoint 或凭据时不回退 Mock，而是进入带原因的可恢复失败状态。`awaiting_final_input` 会保持等待，不会在重启后自行总结。

上下文管理将不可变的完整公开日志与每次模型调用使用的工作上下文分离。工作上下文始终优先保留原始问题、最新用户插话和最近发言；超出模式预算时，从较早内容中确定性选取最旧、中段和较新锚点并裁剪。该过程不调用模型，也不是语义摘要。默认单次上下文预算为 Quick 1800、Standard 4000、Rigorous 7000 Token。OpenAI 和 CC Switch 中已知的 OpenAI-compatible 模型使用匹配的 `tiktoken`；未知模型使用预留余量的保守 UTF-8 估算。Run 快照和界面会记录“精确”或“估算”，不会把 fallback 冒充 Provider usage。原始发言不会因裁剪而从 Run 中删除。

模型适配层保持薄接口：`health_check`、`list_models`、`generate` 和 `aclose`。Provider 注册表集中维护官方地址、保守的离线推荐、协议、能力和文档入口；远程 `/models` 成功时使用账号实际目录，失败时可显示明确标注的离线推荐。`model_source` 区分 Provider 实时目录、CC Switch 近期成功记录、内置 Mock、离线推荐和无目录，避免把推荐值冒充实时可用模型。Mock Provider 让自动化测试无需密钥。自动协议策略先尝试 Responses，只有明确的 404/405/501 才回退 Chat Completions；只有声明支持原生 reasoning 的 Responses Provider 才接收 effort，普通 Chat Completions Provider 只应用 Council 的上下文和流程档位。

资料空间已从当前用户界面和新建审议主流程移除。后端暂时保留旧项目、来源和 Run 快照结构，仅用于升级兼容与历史审议展示，避免更新时误删已有数据；新建审议不再读取或提交资料空间字段。

手机入口由 Next.js 对局域网开放，FastAPI 和 CC Switch 继续只监听 loopback。启动器分别生成电脑引导令牌和手机配对令牌，手机令牌不能申请电脑端权限；令牌经 URL fragment 到达对应浏览器，成功后换取不包含原始令牌的 HttpOnly、SameSite=Strict 签名会话。会话有 12 小时上限，绑定当前启动实例，可由电脑端立即撤销。配对接口限制失败频率，只接受当前 Host 的同源 JSON 请求，并在读取流时限制请求体。所有已配对状态修改同样经过 Origin 和 Host 校验。完整边界、普通 HTTP 剩余风险和滥用假设见 `docs/THREAT_MODEL.md`。

完成 Run 后可写入一份决策回访：最终采用的决定、预期结果、复盘日期、实际结果和四席观点验证状态。它属于同一 Run 的可编辑本地记录，不会触发额外模型调用，也不会反向改写当时的讨论和答案。

桌面 Release 使用 PyInstaller 打包后端、Next standalone 打包网页，并附带 Node runtime。普通用户不依赖系统 Python/Node；源码开发仍使用项目虚拟环境和 npm。发布工作流为 ZIP 和校验清单生成 GitHub build provenance attestation，用于关联 workflow 与 commit。macOS 构建执行 ad-hoc codesign 但不做 Apple notarization，Windows 构建目前没有商业代码签名；provenance 不能替代这两种平台信任，这些限制必须在下载说明中保持可见。

打包版本只从固定的 Council Lab GitHub 仓库检查正式 Release，并按版本和系统精确选择资产。更新器限制下载大小、校验 `SHA256SUMS.txt`、限制解压体积与文件数量，并拒绝路径穿越、越界符号链接和重复路径；哈希与解压在线程中执行，避免阻塞本地 API。校验完成后才启动包内独立助手：macOS 深度验证 app 签名结构后以备份替换，Windows 先镜像备份完整安装目录再覆盖，失败时恢复旧版。安装接口要求前端专用请求头，使普通网页不能用简单跨站 POST 触发本机重启。SHA-256 证明下载内容与同一 GitHub Release 一致，但不等同于 Apple notarization 或 Windows 商业代码签名。

每次模型请求前执行真实边界检查：默认最多 8 次尝试（失败请求也计算）、40,000 Provider 累计 Token、每席最多等待上游 120 秒。CC Switch 同一席位内的推理降档尝试共享这一个等待预算，不会为每次降档重新计时；用户阅读和确认的时间不计入模型等待。上下文窗口与累计 usage 是两个指标；CC Switch Codex 路径可能附加约 4k-5k 基础 instructions，因此默认额度按五次真实调用预留。达到边界后 Run 进入 `stopped` 并保留已完成发言；用户可提高边界，通过原 checkpoint 从未完成席位继续。检查发生在请求前，无法预知本次返回的最终 usage，所以最后一次允许的请求可能使累计值超过边界。由于没有稳定的跨 Provider 定价数据，系统不伪造美元预算。

Provider API Key 使用 `keyring` 交给平台凭据库。SQLite 只保存 `credential_saved` 标记与环境变量名，公开 Provider 响应只暴露 `has_api_key` 和 `credential_source`。运行时优先读取环境变量，其次读取系统凭据库。

默认关闭第三方追踪，不记录 Authorization、Cookie、完整 API Key、用户敏感文件或隐藏思维链。Provider 地址检查会解析 DNS 并拒绝 metadata、link-local、unspecified、multicast 与 reserved 目标；自定义本地 Provider 可使用 private/loopback，CC Switch 只接受 loopback。DNS rebinding 仍是剩余风险。
