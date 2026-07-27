# 安装与排错

## macOS

先安装 [Python 3.12+](https://www.python.org/downloads/) 和 [Node.js 22+](https://nodejs.org/)，然后回到项目文件夹双击 `安装 Council.command`。

若 macOS 第一次阻止打开，请按住 Control 点击安装器，选择“打开”。安装完成后，使用桌面的 `Council.app`。

## Windows 10 / 11

1. 安装 [Python 3.12+](https://www.python.org/downloads/windows/)，安装时勾选 `Add python.exe to PATH`。
2. 安装 [Node.js 22+](https://nodejs.org/)。
3. 在 Release 页下载 `Council-v*-Windows.zip`，右键“全部解压缩”；不要在 ZIP 预览窗口中直接运行。
4. 双击 `Install Council.cmd`。它会在项目内安装依赖、构建网页，并在桌面创建 `Council` 快捷方式。

以后双击桌面的 `Council`。也可双击项目里的 `Start Council.cmd` 启动，或 `Stop Council.cmd` 停止本地服务。脚本不需要管理员权限。

- 数据：`%LOCALAPPDATA%\Council\data\council.sqlite3`
- 日志：`%LOCALAPPDATA%\Council\logs\`
- 界面：<http://localhost:3000>

如果 SmartScreen 拦截，点“更多信息”→“仍要运行”。如果提示 Python 或 Node.js 不存在，重新安装对应软件后关闭并重新打开 `Install Council.cmd`。端口 `3000` 或 `8001` 被占用时，启动器会明确报错，不会结束其他软件。

## 命令行

```bash
./setup.sh
./start.sh
```

停止 macOS 本地服务：

```bash
./desktop/stop-council.sh
```

日志位于 `~/Library/Logs/Council/`。用户数据位于 `~/Library/Application Support/Council/data/`，重新安装不会删除它。

Linux 开发时可分别运行：

```bash
backend/.venv/bin/uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8001
cd frontend && npm run dev
```
