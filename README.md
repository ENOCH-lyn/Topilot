# copilot-in-telegram

将 GitHub Copilot CLI 接入 Telegram Bot使用

## 项目背景

Openclaw等项目消耗Token速度普遍较快，但是很多功能在日常生活中用不到

而学生党能免费用Copilot，日常使用Copilot时可能有远程操控的需求，希望能想OpenClaw那样接入Bot使用

因此，本项目提供了将Copilot CLI 接入 Telegram Bot的功能

## 功能特性

- Telegram 机器人接入与 Chat ID 白名单控制
- Copilot CLI 会话功能与多会话切换
- 快捷接管运行中的会话，方便用户在手机上继续进行会话
- 流式传输结果
- 工具调用过程等展示

## 环境要求

- Python 3.11+
- 已安装并可执行的 `copilot` CLI
- 已完成 `copilot login`
- 拥有Telegram Bot Token
- Powershell 6+ (pwsh)

## 安装与启动

```powershell
pip install -e .
copilot login
copilot-in-telegram
```

首次运行会自动进入交互式配置向导，生成 `~/.copilot-in-telegram/config.json`

也可以手动执行

```powershell
copilot-in-telegram init
copilot-in-telegram start
```

## 配置说明

默认位置 `~/.copilot-in-telegram/config.json`

目录结构

```text
~/.copilot-in-telegram/
	config.json
	data/
		chats.json
		sessions.json
	logs/
		app.log
	workspace/
```

常用配置字段

- `telegram.bot_token`：Telegram 机器人令牌（必填）
- `telegram.allowed_chat_ids`：允许访问的 Chat ID 列表
- `telegram.proxy_url`：Telegram 请求代理
- `copilot.cli_command`：Copilot CLI 命令，默认 `copilot`
- `copilot.model`：默认模型
- `copilot.timeout_seconds`：单次调用超时秒数
- `runtime.workspace_root`：默认工作区路径
- `runtime.session_watch_interval_seconds`：接管会话轮询间隔
- `storage.log_file_path`：日志文件路径
- `logging.log_level`：文件日志级别
- `logging.console_log_level`：控制台日志级别
- `logging.httpx_log_level`：`httpx` 日志级别

## Bot 可用命令

- `/whoami`：查看当前 chat/user 信息
- `/llm`：查看 Copilot CLI 后端状态
- `/session_current`：查看当前会话 ID
- `/sessions`：按钮化会话管理入口（列表/接管/历史/删除）
- `/session_new [title]`：新建并切换会话
- `/session_use <session_id前缀>`：切换会话
- `/model`：查看/切换当前模型（内联按钮选择）
- `/status`：查看运行状态
- 直接发送文本将进入 Copilot 对话
