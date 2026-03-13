# copilot-in-telegram

将 GitHub Copilot CLI 接入 Telegram Bot使用

## 项目背景

Openclaw等项目消耗Token速度普遍较快，但是很多功能在日常生活中用不到

而学生党能免费用Copilot，日常使用Copilot时可能有远程操控的需求，希望能想OpenClaw那样接入Bot使用

因此，本项目提供了将Copilot CLI 接入 Telegram Bot的功能

## 功能特性

- Telegram 机器人接入与 Chat ID 白名单控制
- Copilot CLI 会话功能与多会话切换
- 流式传输结果
- 工具调用过程等展示

## 环境要求

- Python 3.11+
- 已安装并可执行的 `copilot` CLI
- 已完成 `copilot login`
- 拥有Telegram Bot Token
- Powershell 6+ (pwsh)

## 安装与启动

> TODO:待修改启动方式
>
> 例如打包成exe或使用pip进行安装

```powershell
pip install -e .
Copy-Item .env.example .env
copilot login
python -m copilot_in_telegram.main
```

## 配置说明

请参考 `.env.example`。常用配置如下：

- `TELEGRAM_BOT_TOKEN`：Telegram 机器人令牌（必填）
- `TELEGRAM_ALLOWED_CHAT_IDS`：允许访问的 Chat ID 列表（强烈建议配置）
- `WORKSPACE_ROOT`：Copilot CLI 的工作目录（`cwd`）
- `COPILOT_CLI_COMMAND`：Copilot CLI 启动命令，默认 `copilot`
- `COPILOT_CLI_MODEL`：默认选择的模型
- `COPILOT_CLI_TIMEOUT_SECONDS`：单次 Copilot CLI 调用超时
- `COPILOT_CLI_REASONING_EFFORT`：可选，Copilot模型思考深度
- `COPILOT_MODELS`：可用模型列表，逗号分隔（留空使用内置默认列表），可在 `/model` 中选择
- `LOG_FILE_PATH`：日志文件路径（默认 `WORKSPACE_ROOT/logs/app.log`）
- `LOG_LEVEL`：文件日志级别（默认 `INFO`）
- `CONSOLE_LOG_LEVEL`：控制台日志级别（默认 `INFO`）
- `HTTPX_LOG_LEVEL`：`httpx` 日志级别（默认 `WARNING`，避免 Telegram 轮询日志刷屏）

## Bot 可用命令

- `/whoami`：查看当前 chat/user 信息
- `/llm`：查看 Copilot CLI 后端状态
- `/session_current`：查看当前会话 ID
- `/sessions`：列出会话
- `/session_new [title]`：新建并切换会话
- `/session_use <session_id前缀>`：切换会话
- `/model`：查看/切换当前模型（内联按钮选择）
- `/status`：查看运行状态
- 直接发送文本将进入 Copilot 对话

