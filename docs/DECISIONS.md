# Decisions

## FastAPI + Next.js

保留定制的一屏四席界面和本地 API。成熟框架只接管后端编排，不用通用 Studio 替换产品交互。

## LangGraph 持久工作流

四席顺序、最终总结、失败节点和恢复位置由 LangGraph 状态图表达。选择它是为了获得确定性路由、SQLite checkpoint、进程重启恢复和可测试的节点边界，而不是引入自由群聊。

## 完整日志与工作上下文分离

公开发言永久保存在 Run 中。模型只接收按 Token 预算生成的工作窗口：原问题、较早摘要、最近发言和最新用户插话。压缩只影响下一次请求，不修改证据记录。

## Checkpoint 独立数据库

业务 Run 和 LangGraph checkpoint 使用两个 SQLite 文件。SQLite 同时只有一个写入器的限制使分库比增加重试或延长锁等待更可靠。删除 Run 时同步删除该 `thread_id` 的 checkpoint。

## CC Switch Local Router 一等 Provider

CC Switch 是本地上游路由，不是第二套供应商管理器。Council 只做连接探测、协议选择、模型映射和错误展示，不读取 CC Switch 私有数据库。供应商切换与故障转移仍由 CC Switch 完成。

## 不展示思维链

持久化只包含公开答案、依据、反例、上下文摘要和不确定性。隐藏推理不是产品输出，也不写日志。

## 本地可观测性

UI 显示工作流引擎、持久检查点数量和当前上下文 Token 使用量。默认不把非 OpenAI Provider 的追踪发送到第三方。
