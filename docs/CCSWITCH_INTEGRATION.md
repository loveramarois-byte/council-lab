# CC Switch 集成

参考资料（实施时按官方仓库与手册核对）：

- https://github.com/farion1231/cc-switch
- https://www.ccswitch.io/
- https://github.com/farion1231/cc-switch/tree/main/docs/user-manual/zh
- https://openai.github.io/openai-agents-python/models/

默认入口：`http://127.0.0.1:15721/v1`。地址可以在设置页修改，但 `ccswitch_local` 默认要求 loopback。系统只访问用户明确配置的地址或默认地址，不扫描端口。

检测步骤：打开设置页后自动调用 `/v1/models`。Council 同时兼容 OpenAI 的 `id` 与 CC Switch Codex 目录的 `slug` 字段；若 CC Switch 返回空目录，则只读查询 `~/.cc-switch/cc-switch.db` 中近期状态为成功的 Codex 请求模型名。查询不读取 Provider 配置、上游地址或密钥，也不修改 CC Switch 数据库；可用 `CCSWITCH_DB_PATH` 指定其他位置。两种来源都不可用时才允许手动填写模型名。生成测试只有用户主动点击“保存并测试”时才执行。

`protocol_mode=auto` 先使用 Responses；只有明确不支持的 404、405 或 501 才切换到 Chat Completions。CC Switch 自身负责上游供应商切换、故障转移、API Key 和用量路由，Council 不重复实现。

当 Ultra 或 High 档出现上游超时、可重试服务错误，或 CC Switch 返回包装后的 `cc_switch_upstream_error` 时，当前运行会按 Ultra → High → Low 自动降档，并把变化作为公开系统事件写入讨论记录。该行为只调整 Council 请求中的 reasoning effort，不替代 CC Switch 自身的供应商故障转移。

Council Lab 与 CC Switch 是独立项目，没有官方隶属、授权或背书关系。

排障顺序：打开 CC Switch → 启动本地路由 → 进入设置页等待自动识别 → 使用最小测试请求。只有 CC Switch 未公布目录且没有成功调用记录时才需要手动填写。云端后端无法访问用户本机 localhost，应在本机启动后端，或配置直接的远程 OpenAI 兼容 Provider。
