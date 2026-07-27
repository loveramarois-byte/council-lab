# Council Lab

Council is a local-first, human-participatory AI deliberation workspace. Four seats speak in sequence, explicitly agree or challenge earlier arguments, and a fifth independent call produces one final answer from the public discussion.

[中文说明](README.md) · [Download](https://github.com/loveramarois-byte/council-lab/releases/latest) · [Contributing](CONTRIBUTING.md)

![Council roundtable](docs/images/roundtable.png)

## Highlights

- Four visible, sequential model calls instead of four unrelated answers.
- Human interjections become context for later seats and the final synthesis.
- LangGraph workflow, SQLite persistence, checkpoints, and turn-level recovery.
- Token budgets, rolling summaries, and recent-turn context prioritization.
- Quick, Standard, and Rigorous modes mapped to Low, High, and Ultra effort.
- CC Switch, DeepSeek, Zhipu GLM, Kimi, SiliconFlow, OpenAI, custom OpenAI-compatible, and offline Mock providers.
- Automatic model discovery with OS credential-store protection for API keys.
- One-viewport desktop and mobile workspace with internally scrolling discussions.

## macOS installation

Install [Python 3.12+](https://www.python.org/downloads/) and [Node.js 22+](https://nodejs.org/) first.

1. Download `Council-v*-macOS.zip` from the [latest release](https://github.com/loveramarois-byte/council-lab/releases/latest).
2. Unzip it and double-click `安装 Council.command`.
3. Launch `Council.app` from your Desktop.

Developers can run:

```bash
git clone https://github.com/loveramarois-byte/council-lab.git
cd council-lab
./setup.sh
./start.sh
```

Council opens at <http://localhost:3000>. Mock mode is offline and free to use. Linux and Windows can run from source, but desktop packages are not available yet.

## Privacy

Provider keys are stored in the operating system credential store, not in Council's SQLite database, logs, or browser storage. Deliberation data stays in the platform user-data directory by default. Real providers receive the question and public discussion context and may charge for requests.

Council does not expose or retain hidden model chain-of-thought. It stores only public model outputs and run metadata.

## Status and license

Version `0.1.0` is an early release for research and decision support. Do not use unreviewed outputs for medical, legal, financial, or safety-critical decisions.

Apache-2.0. See [LICENSE](LICENSE), [SECURITY.md](SECURITY.md), and [CONTRIBUTING.md](CONTRIBUTING.md).
