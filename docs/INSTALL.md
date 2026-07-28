# 安装与排错

普通用户请下载 GitHub Release，不要下载仓库首页的 `Source code` 压缩包。Release 包已内置后端和网页运行环境，不需要先安装 Python 或 Node.js。

## macOS

1. 在[最新版本下载页](https://github.com/loveramarois-byte/council-lab/releases/latest)下载 `Council-v*-macOS.zip`。
2. 双击 ZIP 解压，再双击 `Council.app`。
3. 浏览器自动打开 <http://localhost:3000>。先选择“本地演示”完成一次离线审议。

当前开源构建使用 ad-hoc 签名，但未经过 Apple notarization。若首次启动被拦截，按住 Control 点击 `Council.app`，选择“打开”，再确认“打开”。请只使用本仓库 Release 下载的文件。

双击 `Stop Council.command` 可停止本地服务。数据保留在：

- 数据：`~/Library/Application Support/Council/data/`
- 日志：`~/Library/Logs/Council/`

## Windows 10 / 11

1. 在[最新版本下载页](https://github.com/loveramarois-byte/council-lab/releases/latest)下载 `Council-v*-Windows.zip`。
2. 右键 ZIP，选择“全部解压缩”；不要在压缩包预览窗口中直接启动。
3. 打开解压后的文件夹，双击 `Start Council.cmd`。
4. 浏览器自动打开 <http://localhost:3000>。先选择“本地演示”完成一次离线审议。

不需要管理员权限，也不需要另行安装 Python 或 Node.js。当前开源构建没有商业代码签名；若 SmartScreen 拦截，请先确认文件来自本仓库 Release，再点“更多信息”→“仍要运行”。

- `Create Desktop Shortcut.cmd`：可选创建桌面快捷方式。
- `Stop Council.cmd`：停止 Council 本地服务。
- 数据：`%LOCALAPPDATA%\Council\data\`
- 日志：`%LOCALAPPDATA%\Council\logs\`

## 首次接入真实 API

1. 打开“设置 → 模型供应商”。
2. 选择 Provider；需要密钥时点“获取 API Key”进入其官方页面。
3. 粘贴密钥，点“保存并测试”。Council 会把密钥交给系统凭据库、获取账号实际可用模型、选择模型并执行最小生成测试。
4. 测试成功后，再进入“设置 → 角色分配”给四个讨论席和总结席选择模型。

若模型目录读取失败，先按界面提示检查 Key、账号权限、余额、网络和服务地址。页面标注的“离线备选”只是排错参考，不代表该模型已对你的账号开放；也可以手动填写 Provider 文档中的准确模型 ID。

CC Switch 必须已在本机启动。Council 只检测本地路由、读取路由公布的模型目录或近期成功模型记录；上游密钥、供应商切换和故障转移仍由 CC Switch 管理。能打开 Council 或使用其他 Provider，不代表 CC Switch 路由一定可用。

## 常见问题

- **页面没有自动打开**：手动访问 <http://localhost:3000>；若仍失败，查看对应系统日志目录。
- **端口被占用**：先用包内的停止脚本结束旧 Council 实例。启动器不会强行结束其他软件。
- **API Key 测试失败**：检查是否复制了多余空格、Key 是否有效、账号是否有余额和模型权限。
- **模型列表为空**：点击模型框旁的刷新按钮；仍为空时按官方文档手填模型 ID。
- **换电脑后没有 Key**：凭据保存在当前操作系统账户，不随项目文件或数据库迁移，需要重新录入。

## 软件内更新

从 `v0.4.0` 开始，Council 启动时自动检查本仓库的正式 GitHub Release。发现新版本后，侧栏“设置”会显示“有更新”：

1. 打开“设置 → 软件更新”。
2. 点击“下载并安装”。
3. Council 下载当前系统的 Release ZIP，并与同一 Release 的 `SHA256SUMS.txt` 核对。
4. 校验通过后停止本地服务、替换应用并自动重新打开。校验失败时不会替换当前版本。

macOS 应用放在 `/Applications` 等受保护目录时会弹出系统授权窗口。Windows 在当前完整解压目录中原地更新，原桌面快捷方式继续有效。源码运行模式只检查版本，不自动覆盖 Git 项目文件。

历史、资料和 API Key 位于应用目录之外，正常更新不会删除。`v0.3.0` 及更早版本没有内置更新器，需要先手动安装 `v0.4.0` 一次。

## 旧版本手动更新

### macOS

1. 双击旧包中的 `Stop Council.command`。
2. 从 Release 下载新版 ZIP 并解压。
3. 用新版 `Council.app` 替换旧版，再启动。数据和 Key 位于应用外，不会因替换 `.app` 消失。

### Windows

1. 双击旧目录中的 `Stop Council.cmd`。
2. 下载并完整解压新版到新目录，不要覆盖正在运行的旧目录。
3. 启动新版；若使用桌面快捷方式，在新版目录重新运行 `Create Desktop Shortcut.cmd`。

更新前可备份上方数据目录。跨大版本升级时请先阅读 `CHANGELOG.md` 和 Release Notes。

## 卸载

1. 先用包内停止脚本结束本地服务。
2. macOS 删除 `Council.app` 和解压目录；Windows 删除 Council 解压目录及桌面快捷方式。
3. 需要同时清除历史记录时，再手动删除对应数据与日志目录。该步骤不可恢复，保留目录即可保留数据。
4. 需要清除 API Key 时，建议在卸载前进入“设置 → 模型供应商”逐个点击删除凭据；也可在 macOS“钥匙串访问”或 Windows“凭据管理器”中删除服务名为 `Council Lab Provider Credentials` 的条目。

## 源码运行（开发者 / Linux）

源码开发需要 Python 3.12+ 和 Node.js 22+：

```bash
git clone https://github.com/loveramarois-byte/council-lab.git
cd council-lab
./setup.sh
./start.sh
```

也可以分别启动：

```bash
backend/.venv/bin/uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8001
cd frontend && npm run dev
```

源码启动脚本和旧版安装器仍供开发场景使用；普通 macOS / Windows 用户应优先下载自包含 Release。
