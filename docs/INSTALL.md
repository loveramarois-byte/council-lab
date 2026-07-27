# 安装与排错

## macOS

先安装 [Python 3.12+](https://www.python.org/downloads/) 和 [Node.js 22+](https://nodejs.org/)，然后回到项目文件夹双击 `安装 Council.command`。

若 macOS 第一次阻止打开，请按住 Control 点击安装器，选择“打开”。安装完成后，使用桌面的 `Council.app`。

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

Linux 和 Windows 暂未提供桌面安装包。开发时可分别运行：

```bash
backend/.venv/bin/uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8001
cd frontend && npm run dev
```
