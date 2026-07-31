# Architecture

Council Lab 采用本地优先的 FastAPI + Next.js 架构。浏览器只访问本地后端；后端负责 LangGraph 工作流、Provider、上下文预算、运行状态和安全边界。

核心流程是可恢复的有限状态图：`dispatch -> turn x N -> awaiting_final_input -> finalize`。决策、风险和复杂任务使用四个席位；快速档的短定义与确定性算术保守路由为一个讨论席。各席按固定顺序调用保存的 Provider/model 配置并读取公开记录。讨论席完成后默认停在用户确认点，或在创建时明确开启 `auto_summarize` 后直接总结。中途和最终补充都写入公开记录。

## Feature status

| Area | Status | Boundary |
| --- | --- | --- |
| Deliberation workflow | Current | 复杂任务四席顺序讨论，短任务一席讨论；用户确认、可选自动总结、恢复与导出均为产品路径。 |
| DecisionBrief v1/v2 | Current | 新完成 Run 在完成状态前固化独立、不可变的结构化简报；v2 可携带强类型输出契约扩展，历史 v1 不回填、不改写。 |
| Immutable Run forks | Current | 完成 Run 可创建新情景 Run；父 Run、发言、审批和审计不改写，复用发言和新调用分开记录。 |
| Approved decision memory | Current | 记忆候选、用户批准动作和实际注入快照均独立持久化；未批准或未明确选择的内容不会跨 Run 注入。 |
| Readiness and claim provenance | Current | 审议前执行多标签准备度检查；主张、引用、席位争议和后续结果使用独立追加式记录，不从共识推导事实状态。 |
| Output contracts | Current | 一般决策、产品评审和技术架构评审复用固定四席与同一安全控制，只改变检查项、Prompt 指导和结构化结果字段。 |
| High-risk control plane | P0, non-binding | 独立状态机、关键事实门禁、人工审批和追加式审计已实现；不执行外部动作，也没有证据核验或专业身份系统。 |
| Run event replay | Current | 事件写入业务库并使用单调序号；SSE 支持 `Last-Event-ID` 重放和独立多订阅者。 |
| Mobile access | Current, local network only | 使用短期签名会话、失败限速、同源校验和手工撤销；普通 HTTP 仍只适用于可信私有网络。 |
| Diagnostics | Current, metadata only | 用户手工导出的 ZIP 只含白名单运行元数据，不含对话、日志正文、凭据、令牌、模型名或主机路径。 |
| Legacy workspace | Compatibility only | 旧项目、来源和快照保留用于历史读取；当前 UI 和新建审议不再使用该能力。 |
| Evaluation framework | Experimental | 数据集和评分脚本不构成多席优于单模型的产品声明。 |
| Network search and code sandbox | Not implemented | 模型共识不等于外部事实核验，也不会自动执行代码。 |

五席配置持久化在应用设置中。创建 Run 时，Provider 公共配置、协议、模型、reasoning effort、超时和输出上限被复制为 Run 快照；短任务只把实际参与席位保存到 `participant_roles`，不改写用户的五席配置。后续修改或删除 Provider 不会改写历史 Run。单席调用失败不会静默切换到 Mock 或其他 Provider。

Candidate 的 `answer` 是席位真实正文，附加结构化字段通过 `structure_source` 记录来源：`agent_output`、`postprocessed`、`manual`、`legacy_default` 或 `none`。当前顺序审议没有可靠的结构化提取，因此新 Candidate 使用 `none` 且相关数组保持为空。旧版本遗留的通用模板会原样保留以兼容历史 Run，但统一标记为 `legacy_default`；界面、报告和评测不得将其描述为模型明确给出的理由、假设或风险。

运行数据分成两个 SQLite 文件：

- `council.sqlite3` 保存应用设置、完整公开 Run、五席快照、发言、最终答案、结果回访、用量和上下文快照。
- `council.sqlite3` 的 `run_events` 表保存实时事件及单调序号；刷新、断线或多标签订阅不会竞争消费同一个内存队列。
- `council.sqlite3` 的 `decision_briefs` 表按 `(run_id, version)` 保存追加式结构化结果。v1 只创建一个版本并禁止更新；用户明确删除 Run 时可同步删除简报以满足本地数据删除要求。
- `council.sqlite3` 的 `run_forks` 表保存不可变父子关系、分叉点、变化摘要和复用 Turn ID。新子 Run 与关系记录在同一事务创建；显式删除任一相关 Run 时同步删除关系记录，避免保留不可解析的本地关联元数据。
- `memory_proposals` 只保存从 DecisionBrief 确定性提出的有界候选；`project_memories` 保存用户批准的不可变内容；`memory_actions` 追加保存批准、拒绝、停用、启用和删除；`run_memory_snapshots` 保存每个新 Run 实际注入的内容快照。
- `readiness_overrides` 保存用户在看见准备度缺口后继续的原因；`decision_claims` 保存不可变主张及来源；`decision_outcomes` 与 `claim_outcomes` 追加保存回访及其对主张的支持或反驳。普通编辑路径不能更新这些记录；用户显式删除整个普通 Run 时同步清除关联主张与回访以满足本地数据删除，高风险审计不受此例外影响。
- `council.checkpoints.sqlite3` 由 LangGraph SQLite saver 保存节点状态。

`DecisionBrief v1` 复用已经持久化的最终综合和公开席位表态，不增加 Provider 调用，也不从 Markdown 反向解析字段。`support` 只表达可观察到的席位支持，不是事实概率；阻塞矛盾禁止与无条件 `proceed` 共存，明确反对必须生成少数意见。最终综合先写入 Run，再固化独立简报；简报校验或持久化失败时，Run 回到 `awaiting_final_input`，保留综合结果并允许不重复模型调用地重试。旧完成 Run 不自动生成或回填简报，API 返回稳定的 `DECISION_BRIEF_NOT_FOUND`，界面和导出继续兼容原始最终答案。

新完成 Run 使用 `DecisionBrief schema v2` 固化 `output_contract` 与对应的强类型扩展。一般决策记录决策标准和关键取舍；产品评审记录目标用户、用户问题、价值、失败条件、验证实验和停止条件；技术架构评审记录需求、约束、方案、故障模式、迁移、回滚和可观测性。扩展由已保存问题、公开总结和 v1 字段确定性投影，不增加 Provider 调用；其中通用验证方法和阈值占位必须被视为待用户补充，不能冒充真实实验结果。历史 v1 简报按默认一般决策继续读取。

情景分叉只接受已完成且已有最终答案的父 Run。`before_deliberation` 可改变模式；复用席位时要求父子模式和席位前缀完全一致，不存在的 checkpoint 会被拒绝而不是静默降级。子 Run 从零累计 usage，复用 Turn 在子快照中带 `reused_from_run_id`，原 Turn ID 同时记录在 `run_forks`。创建接口使用持久幂等键，断线重试不会重复创建或重复计费。高风险父 Run 的审批从不继承；子 Run 在任务启动前创建新的高风险控制记录，后续落库失败时保持阻断。旧 Run 若没有结构化简报仍可创建新情景，但要等父子双方都有简报后才提供结构化比较。

记忆只有在候选来源 Run 已完成、结构化简报存在且用户逐条批准后才可进入 `project_memories`。新 Run 的 `selected_memory_ids` 必须对应当前仍 active 的记忆；服务端把实际内容写入 `run_memory_snapshots` 并和 Run 同事务提交，前端的 preview 不是安全边界。记忆内容作为不可信上下文提供给模型，不改变高风险控制状态，也不会升级主张的验证等级。

准备度使用确定性、多标签规则给出建议，不承诺搜索、计算器或其他工具实际可用。高风险任务仍由独立控制面的关键事实门禁执行，准备度 UI 不能绕过它。DecisionBrief 的决定性理由、假设和未决项会生成不可变 Claim；模型 URL 保留 `externally_checked=false` 的未核验引用，未受争议时标为 `cited_unverified`，明确反对时主状态标为 `seat_disputed`。结果回访追加新记录，只有明确关联席位的后续结果才能形成 `outcome_supported` 或 `outcome_contradicted` 当前视图。Markdown/HTML 导出与结果页使用同一主张视图，不能把模型引用或席位共识显示为已验证事实。

高风险控制面与普通 `RunRecord` 分离。`high_risk_runs` 保存风险判断、关键事实、决策摘要哈希和乐观锁版本；`high_risk_approvals` 保存内容绑定、职责分离、有效期、撤销和一次性消费状态；`high_risk_audit_events` 使用单调序号和 SQLite 触发器实现追加写入。安全敏感更新使用 `BEGIN IMMEDIATE`，状态与审计在同一事务提交，审计失败会回滚状态。审计只允许有界标量、哈希和稳定 ID，不保存问题、报告、动作正文或复核密钥。

高风险 Run 的控制记录在普通 Run 入库和模型任务启动前创建，消除崩溃后留下无保护 queued Run 的窗口。普通恢复器跳过所有已关联高风险控制记录；审批过期恢复只更新审批状态并追加审计，不推进工作流或调用模型。普通总结、重试、续跑、重跑、删除、决策回访和取消入口经过统一门禁；高风险取消使用专用端点。P0 不包含 Tool executor，因此 `APPROVED` 只允许把绑定报告标为 `COMPLETED`，不会执行任何外部副作用。

复核者 allowlist 来自 `COUNCIL_HIGH_RISK_REVIEWERS=reviewer_id:secret,...`。actor header 是本地归属标识，不是通用账户或登录系统；审批服务仍会验证服务端 secret、请求者绑定和职责分离。手机配对会话也不是复核身份，客户端按钮不构成授权。

数据库不存放在源码树。默认使用平台用户数据目录，macOS 为 `~/Library/Application Support/Council/data/`，Linux 为 `${XDG_DATA_HOME:-~/.local/share}/council/data/`，Windows 为 `%LOCALAPPDATA%\\Council\\data\\`；测试和部署可用 `COUNCIL_DATA_DIR` 覆盖。

业务记录和 checkpoint 分库，避免两个写入器争用同一个 SQLite 写锁。启动时扫描 `queued` 与 `running` Run：存在有效 checkpoint 且凭据可用时，工作流使用同一 `thread_id` 续跑；业务库已完整保存的席位会被跳过，避免 checkpoint 落后造成重复计费。缺少 checkpoint 或凭据时不回退 Mock，而是进入带原因的可恢复失败状态。`awaiting_final_input` 会保持等待，不会在重启后自行总结。

业务库使用 `PRAGMA user_version` 执行顺序迁移，当前 schema 为 v9。打开已有且版本较旧的库时，先通过 SQLite backup API 在同一数据目录的 `backups/` 创建一致性副本，再在事务中逐版本升级；失败时关闭连接、移除 WAL/SHM sidecar 并恢复副本。只保留最近 5 份 schema 迁移备份，诊断数据同时报告当前/支持版本和备份数量。该机制用于升级回滚，不替代用户自己的异机备份。旧版本不理解 v9；需要降级时必须先停止 Council，再恢复升级前备份及其匹配的 checkpoint 文件。

上下文管理将不可变的完整公开日志与每次模型调用使用的工作上下文分离。工作上下文始终优先保留原始问题、最新用户插话和最近发言；超出模式预算时，从较早内容中确定性选取最旧、中段和较新锚点并裁剪。该过程不调用模型，也不是语义摘要。默认单次上下文预算为 Quick 1800、Standard 4000、Rigorous 7000 Token。OpenAI 和 CC Switch 中已知的 OpenAI-compatible 模型使用匹配的 `tiktoken`；未知模型使用预留余量的保守 UTF-8 估算。Run 快照和界面会记录“精确”或“估算”，不会把 fallback 冒充 Provider usage。原始发言不会因裁剪而从 Run 中删除。

模型适配层保持薄接口：`health_check`、`list_models`、`generate` 和 `aclose`。Provider 注册表集中维护官方地址、保守的离线推荐、协议、能力和文档入口；远程 `/models` 成功时使用账号实际目录，失败时可显示明确标注的离线推荐。`model_source` 区分 Provider 实时目录、CC Switch 近期成功记录、内置 Mock、离线推荐和无目录，避免把推荐值冒充实时可用模型。Mock Provider 让自动化测试无需密钥。自动协议策略先尝试 Responses，只有明确的 404/405/501 才回退 Chat Completions；只有声明支持原生 reasoning 的 Responses Provider 才接收 effort，普通 Chat Completions Provider 只应用 Council 的上下文和流程档位。

资料空间已从当前用户界面和新建审议主流程移除。历史项目、来源和 Run 快照仍可读取，但相关创建、修改、上传、URL 抓取和删除 API 默认返回 `410 FEATURE_RETIRED`；新建 Run 携带旧 `project_id/source_ids` 也会被拒绝。仅升级排障可显式设置 `COUNCIL_ENABLE_LEGACY_WORKSPACE=1` 临时恢复写入，生产环境不应长期启用。

会产生模型调用或改变 Run 状态的 POST 接受 8–128 字符 `Idempotency-Key`。服务端持久保存作用域、请求指纹、执行状态和完成后的 Run 响应：同键同载荷返回原结果并标记 `Idempotency-Replayed: true`，同键不同载荷返回 `409`，并发重复或尚未过期的执行返回 `409`。前端只对网络级失败用同一键重试一次，不重试明确的 HTTP 业务错误。

手机入口由 Next.js 对局域网开放，FastAPI 和 CC Switch 继续只监听 loopback。启动器分别生成电脑引导令牌和手机配对令牌，手机令牌不能申请电脑端权限；令牌经 URL fragment 到达对应浏览器，成功后换取不包含原始令牌的 HttpOnly、SameSite=Strict 签名会话。会话有 12 小时上限，绑定当前启动实例，可由电脑端立即撤销。配对接口限制失败频率，只接受当前 Host 的同源 JSON 请求，并在读取流时限制请求体。所有已配对状态修改同样经过 Origin 和 Host 校验。完整边界、普通 HTTP 剩余风险和滥用假设见 `docs/THREAT_MODEL.md`。

完成 Run 后可写入一份决策回访：最终采用的决定、预期结果、复盘日期、实际结果和四席观点验证状态。它属于同一 Run 的可编辑本地记录，不会触发额外模型调用，也不会反向改写当时的讨论和答案。

桌面 Release 使用 PyInstaller 打包后端、Next standalone 打包网页，并附带 Node runtime。普通用户不依赖系统 Python/Node；源码开发仍使用项目虚拟环境和 npm。发布工作流为 ZIP 和校验清单生成 GitHub build provenance attestation，用于关联 workflow 与 commit。macOS 构建执行 ad-hoc codesign 但不做 Apple notarization，Windows 构建目前没有商业代码签名；provenance 不能替代这两种平台信任，这些限制必须在下载说明中保持可见。

打包版本只从固定的 Council Lab GitHub 仓库检查正式 Release，并按版本和系统精确选择资产。更新器限制下载大小、校验 `SHA256SUMS.txt`、限制解压体积与文件数量，并拒绝路径穿越、越界符号链接和重复路径；哈希与解压在线程中执行，避免阻塞本地 API。校验完成后才启动包内独立助手：macOS 深度验证 app 签名结构后以备份替换，Windows 先镜像备份完整安装目录再覆盖，失败时恢复旧版。安装接口要求前端专用请求头，使普通网页不能用简单跨站 POST 触发本机重启。SHA-256 证明下载内容与同一 GitHub Release 一致，但不等同于 Apple notarization 或 Windows 商业代码签名。

每次模型请求前执行真实边界检查：默认最多 8 次尝试（失败请求也计算）、40,000 Provider 累计 Token、每席最多等待上游 120 秒。CC Switch 同一席位内的推理降档尝试共享这一个等待预算，不会为每次降档重新计时；用户阅读和确认的时间不计入模型等待。上下文窗口与累计 usage 是两个指标；CC Switch Codex 路径可能附加约 4k-5k 基础 instructions，因此默认额度按五次真实调用预留。达到边界后 Run 进入 `stopped` 并保留已完成发言；用户可提高边界，通过原 checkpoint 从未完成席位继续。检查发生在请求前，无法预知本次返回的最终 usage，所以最后一次允许的请求可能使累计值超过边界。由于没有稳定的跨 Provider 定价数据，系统不伪造美元预算。

Provider API Key 使用 `keyring` 交给平台凭据库。SQLite 只保存 `credential_saved` 标记与环境变量名，公开 Provider 响应只暴露 `has_api_key` 和 `credential_source`。运行时优先读取环境变量，其次读取系统凭据库。

默认关闭第三方追踪，不记录 Authorization、Cookie、完整 API Key、用户敏感文件或隐藏思维链。Provider 地址检查会解析 DNS 并拒绝 metadata、link-local、unspecified、multicast 与 reserved 目标；自定义本地 Provider 可使用 private/loopback，CC Switch 只接受 loopback。DNS rebinding 仍是剩余风险。
