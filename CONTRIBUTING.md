# Contributing

感谢参与 Council Lab。提交代码前请先搜索现有 Issue，并把改动保持在一个可验证的主题内。

## 开发环境

需要 Python 3.12+、Node.js 22+。安装方式见 README。不要提交 `.env`、API Key、真实对话数据库、日志、截图、`node_modules`、`.next` 或虚拟环境。

## 检查

提交前至少运行：

```bash
make backend-test
make frontend-build
```

涉及用户流程、布局或 API 契约的改动还需启动本地服务并运行：

```bash
cd frontend
npm test
```

新增行为应带有聚焦测试。修复 bug 时，优先加入能在修复前失败的回归测试。

## Pull Request

PR 请说明问题、方案、验证结果、隐私或兼容性影响。不要附带真实用户内容的截图或数据库。UI 变化可使用脱敏的 Mock 数据截图。

提交即表示你有权贡献这些内容，并同意按 Apache-2.0 许可发布。
