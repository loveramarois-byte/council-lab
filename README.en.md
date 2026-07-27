# Council Lab

Council is a local-first, human-participatory AI deliberation workspace. Four seats speak in sequence and explicitly agree with or challenge earlier arguments. Council then waits for your confirmation or additions before a fifth call produces the final answer.

[中文说明](README.md) · [Download](https://github.com/loveramarois-byte/council-lab/releases/latest) · [Contributing](CONTRIBUTING.md)

![Council roundtable](docs/images/roundtable.png)

## Highlights

- Four visible, sequential model calls instead of four unrelated answers.
- Human interjections become context for later seats and the final synthesis.
- Independently configurable providers and models for all four seats and the finalizer, snapshotted per run.
- A human confirmation point after seat four, with support for multiple final additions.
- LangGraph workflow, SQLite persistence, checkpoints, startup recovery, and explicit recoverable failures.
- Deterministic context clipping that preserves the question, early anchors, recent turns, and the latest user interjection.
- Quick, Standard, and Rigorous are workflow/context tiers. Native reasoning effort is sent only by capable Responses providers.
- Enforced defaults of eight model attempts, 40k provider-reported cumulative tokens, and 120 seconds for the full run.
- Limit-stopped runs can raise their boundary and continue from the unfinished seat without repeating completed calls.
- CC Switch, DeepSeek, Zhipu GLM, Kimi, SiliconFlow, OpenAI, custom OpenAI-compatible, and offline Mock providers.
- Automatic model discovery with OS credential-store protection for API keys.
- One-viewport desktop and mobile workspace with internally scrolling discussions.

Council does not currently run web searches or a code sandbox, and it does not present model agreement as a percentage fact-confidence score. A final synthesis is model consensus, not external verification.

The run screen separates the per-call discussion context from cumulative provider usage. CC Switch Codex routes may attach roughly 4k-5k base-instruction tokens to each request, so provider usage can be much higher than the visible context window. Council checks the cumulative boundary before each request; the last allowed response can therefore take the total slightly past that boundary.

## macOS installation

Install [Python 3.12+](https://www.python.org/downloads/) and [Node.js 22+](https://nodejs.org/) first.

1. Download `Council-v*-macOS.zip` from the [latest release](https://github.com/loveramarois-byte/council-lab/releases/latest).
2. Unzip it and double-click `安装 Council.command`.
3. Launch `Council.app` from your Desktop.

## Windows 10 / 11 installation

Install [Python 3.12+](https://www.python.org/downloads/windows/) and [Node.js 22+](https://nodejs.org/) first. Enable **Add python.exe to PATH** in the Python installer.

1. Download `Council-v*-Windows.zip` from the [latest release](https://github.com/loveramarois-byte/council-lab/releases/latest).
2. Extract the entire ZIP, then double-click `Install Council.cmd`.
3. Launch Council from the shortcut created on your Desktop.

No administrator permission is required. Use `Start Council.cmd` and `Stop Council.cmd` in the extracted folder when you need the direct controls. If SmartScreen appears, choose **More info** and **Run anyway**.

Developers can run:

```bash
git clone https://github.com/loveramarois-byte/council-lab.git
cd council-lab
./setup.sh
./start.sh
```

Council opens at <http://localhost:3000>. Mock mode is offline and free to use. macOS and Windows include double-click launchers; Linux can run the project from source.

## Privacy

Provider keys are stored in the operating system credential store, not in Council's SQLite database, logs, or browser storage. Deliberation data stays in the platform user-data directory by default. Real providers receive the question and public discussion context and may charge for requests.

Council does not expose or retain hidden model chain-of-thought. It stores only public model outputs and run metadata.

## Status and license

Version `0.2.2` is an early release for research and decision support. Do not use unreviewed outputs for medical, legal, financial, or safety-critical decisions.

Apache-2.0. See [LICENSE](LICENSE), [SECURITY.md](SECURITY.md), and [CONTRIBUTING.md](CONTRIBUTING.md).
