# Security Policy

## Supported versions

当前仅维护默认分支的最新版本。项目处于早期阶段，不提供长期支持分支。

## Reporting a vulnerability

请不要为未修复漏洞创建公开 Issue。通过仓库托管平台的 private vulnerability reporting 功能联系维护者；若该功能不可用，请在不披露技术细节的情况下创建 Issue，请求私下联系渠道。

报告应包含受影响版本、复现步骤、影响、最小证明和建议修复。不要发送真实 API Key、用户数据库或不必要的个人数据。维护者目标是在 7 天内确认收到，并根据影响给出修复与披露计划。

## Secrets and local data

Council 的本地设置 API 会接收一次明文 Provider 密钥，并立即交给操作系统凭据库；密钥不会写入业务数据库、日志或前端持久存储。后端应只绑定 loopback，生产反向代理不得把凭据接口暴露到不可信网络。环境变量或外部 secret manager 仍可使用，并具有更高优先级。

运行数据库和日志可能包含完整用户问题与模型回答；不要直接发送数据库或原始日志。优先使用“设置 → 诊断与支持”生成白名单式脱敏诊断包，并在发送前自行检查归档内容。

旧版本的资料空间曾在本机保存导入文件或网页提取出的文字、来源元数据和 SHA-256。该能力已从当前 UI 和新建流程移除，写 API 默认返回 `410`，但为了升级兼容，历史审议中的不可变资料快照仍会保留。兼容开关 `COUNCIL_ENABLE_LEGACY_WORKSPACE=1` 会重新扩大本机写入和 URL 抓取攻击面，只应在离线迁移排障期间短时使用。删除或分享数据前请同时检查历史审议和导出报告。

业务数据库升级前会自动生成 schema 备份并在失败时恢复，备份文件权限在支持的平台设置为 `0600`。备份仍包含完整审议数据，受与主数据库相同的主机账户信任边界保护；自动保留最近 5 份不构成灾难恢复或异机备份。

Run 的高成本状态修改支持持久 `Idempotency-Key`，降低网络重试造成重复模型调用的风险。键不是授权凭据；服务端仍执行正常的 Host、Origin 和手机会话校验。同一键绑定请求指纹，载荷变化、并发占用和未过期的中断执行会明确返回冲突，不会自动执行第二次。

本地部署仍需由操作者保护主机账户、数据目录和 CC Switch 配置。不要把后端直接暴露到不可信网络；默认启动命令只监听 loopback，后端拒绝非本机 `Host`，CORS 只允许 Council 前端来源。软件安装和强制刷新更新信息还要求 Council 前端专用请求头，以降低普通网页跨站触发本机操作或消耗 GitHub API 额度的风险。

手机连接只适用于可信家庭或办公室局域网。配对使用相互独立的电脑引导令牌和手机令牌、失败限速、同源 Host/Origin 校验、短期签名 Cookie 和电脑端会话撤销；FastAPI、凭据库和 CC Switch 不直接向局域网监听。普通 HTTP 无法防御同网段被动监听，公共 Wi-Fi、访客网络和互联网端口映射均不在支持范围内。完整资产、攻击者、控制和剩余风险见 [Mobile Access Threat Model](docs/THREAT_MODEL.md)。

## Provider URL validation

自定义 Provider 在连接前会解析全部 DNS 结果，并拒绝云元数据主机、link-local、unspecified、multicast 和 reserved 地址；为支持本地模型，自定义 Provider 仍允许 private/loopback 地址。CC Switch 则只允许 loopback。

该校验降低常见 SSRF 风险，但 DNS 解析结果可能在校验后变化，因此不能消除 DNS rebinding。请只配置可信 Provider 地址，并继续让后端保持 loopback 监听。

网页资料导入采用更严格的公开地址限制：只允许 HTTP/HTTPS，拒绝本机、私网、云元数据和保留目标，并限制重定向、响应大小和文本类型。该机制同样不能完全消除 DNS rebinding，也不会把网页内容判定为可信；模型可能受到资料中的提示注入影响，导入前应确认来源。

## Desktop packages

macOS Release 当前使用 ad-hoc 签名并通过本地 codesign 校验，但没有 Apple notarization。Windows Release 当前没有商业代码签名。系统首次启动警告是已知限制，不应通过关闭系统安全功能来规避；请只从本仓库 Release 下载，并核对版本与来源。
