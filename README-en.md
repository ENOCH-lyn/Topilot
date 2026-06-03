<div align="center">
<img width="100" src="./assets/logo.png">
<h1 align="center">Topilot</h1></div>

[简体中文](./README.md) | English

Use GitHub Copilot CLI through a Telegram Bot

## Screenshots

<div align="center" style=" gap: 20px; flex-wrap: wrap; justify-content: center;">
<img width="200" src="./assets/model.jpg">
<img width="200" src="./assets/sessions.jpg">
<br><br><br>
<img width="200" src="./assets/tools.jpg">
</div>

## Background

Topilot bridges a local GitHub Copilot CLI instance to a Telegram Bot for personal remote-access scenarios.

The project focuses on three practical needs:

- continue using a locally authenticated Copilot CLI from mobile
- view streaming replies and tool activity in Telegram
- take over an existing local session and keep its context

## Features

- Telegram bot integration with Chat ID whitelist control
- Copilot session support with multi-session switching
- Take over a local running session and follow its history from the session detail view
- Streaming responses
- Display of tool-calling process and related output

## Requirements

- Python 3.11+
- Installed and executable `copilot` CLI
- Completed `copilot login`
- A Telegram Bot Token
- Windows PowerShell or PowerShell

## Installation and Startup

```powershell
pip install -e .
copilot login
topilot
```

On first run, an interactive setup wizard starts automatically and generates the default config file at `~/.topilot/config.json`.

Or run manually:

```powershell
topilot init
topilot doctor
topilot start
```

## Configuration

You can edit the configuration JSON file manually. Its fixed path is `~/.topilot/config.json`.

Directory structure:

```text
~/.topilot/
    config.json
    data/
        chats.json
        sessions.json
    logs/
        app.log
    workspace/
```

Common configuration fields:

- `telegram.bot_token`: Telegram bot token (required)
- `telegram.allowed_chat_ids`: Telegram Chat IDs allowed to access the bot, as an array or comma-separated string. If empty, all Chat IDs are allowed. It is strongly recommended to configure this for security.
- `telegram.proxy_url`: Proxy URL for accessing the Telegram API when needed, e.g. `http://127.0.0.1:10808`
- `copilot.cli_command`: Command used to run Copilot CLI, default is `copilot`
- `copilot.model`: Default model used by Copilot CLI, default is `gpt-5-mini`
- `copilot.available_models`: Fallback model candidates when live discovery fails
- `copilot.timeout_seconds`: Timeout in seconds for a single call, default is `3600`
- `copilot.allow_all_tools`: Whether to pass `--allow-all-tools` to Copilot CLI
- `copilot.add_workspace_dir`: Whether to pass `--add-dir` automatically
- `copilot.reasoning_effort`: Optional reasoning effort passed to Copilot CLI
- `copilot.forward_reasoning`: Whether to forward reasoning text in the non-streaming path
- `runtime.workspace_root`: Default workspace path
- `runtime.session_watch_interval_seconds`: Polling interval for session takeover
- `logging.log_level`: File log level
- `logging.console_log_level`: Console log level
- `logging.httpx_log_level`: Log level for `httpx`. `WARNING` is recommended to avoid polling spam.

## Available Bot Commands

- `/whoami`: View current chat/user info
- `/session_current`: View current session ID with a brief summary
- `/sessions`: Session management entry (list/takeover/history/delete)
- `/session_new [title]`: Create and switch to a new session
- `/session_use <session_id_prefix>`: Switch to a saved session or take over the uniquely matched local session
- `/model`: View/switch current model
- `/status`: View backend status, current session, source, state, model, and workspace summary, with a button for detailed backend diagnostics
- Send text directly to start chatting

The bot registers its command menu with Telegram on startup. `/start`, `/help`, `/status`, `/model`, `/sessions`, and `/session_current` also expose inline buttons for common actions.

## Current Scope

The current version includes:

- Configuration initialization, config backups, and `doctor` diagnostics
- Telegram commands, inline callbacks, Chat ID whitelist, and `/whoami`
- Copilot CLI text conversations, JSON streaming replies, and tool progress summaries
- Multi-session create/switch/delete, local `session-state` discovery, and takeover
- Polling and refreshing a running local session from the session detail flow
- Model discovery, fallback candidates, button-based switching, and per-Chat persistence
- A baseline pytest automation suite

Out-of-scope for the current version: image/audio/file input, browser automation, plugin marketplace, enterprise permissions, multi-instance deployment, and database persistence.

## Tests

Install development dependencies and run:

```powershell
pip install -e ".[dev]"
pytest
```

The baseline tests cover configuration, storage, local session scanning, Copilot event parsing, failure messages, Telegram authorization, command registration, model menus, and session callback rendering.
As of 2026-06-03, the project has also passed real Telegram external-network integration and real Copilot CLI integration.

## License

MIT License. See [LICENSE](./LICENSE) for details.

## Disclaimer
This project is intended as a self-hosted personal tool for use in a trusted environment. Users are responsible for protecting their Telegram Bot token, Copilot login state, local workspace, and access whitelist. The project does not provide enterprise-grade isolation, auditing, or security guarantees, and all usage risks remain with the operator.
