<div align="center">
<img width="100" src="./assets/logo.png">
<h1 align="center">Topilot</h1></div>

通过 Telegram Bot / Feishu Bot 使用 GitHub Copilot CLI

## 运行截图

<div align="center" style=" gap: 20px; flex-wrap: wrap; justify-content: center;">
<img width="200" src="./assets/model.jpg">
<img width="200" src="./assets/sessions.jpg">
<br><br><br>
<img width="200" src="./assets/tools.jpg">
</div>

## 项目背景

Topilot 将本地 GitHub Copilot CLI 桥接到 Telegram Bot 与 Feishu Bot，面向个人远程使用场景。

项目重点解决以下问题：

- 在移动端继续使用本机已登录的 Copilot CLI
- 在 Telegram 中查看流式回复与工具执行过程
- 在 Feishu 中通过企业内机器人继续发起 Copilot 对话
- 接管本机已有会话并延续上下文

## 功能特性

- Telegram 机器人接入与 Chat ID 白名单控制
- Feishu 长连接机器人接入与会话白名单控制
- Copilot 会话功能与多会话切换
- 接管本机运行中的会话，并在会话详情页追踪历史刷新
- 流式传输结果
- 工具调用过程等展示

## 环境要求

- Python 3.11+
- 已安装并可执行的 `copilot` CLI
- 已完成 `copilot login`
- 拥有 Telegram Bot Token
- 如需启用 Feishu，需要自建应用的 `app_id` 与 `app_secret`
- Windows PowerShell 或兼容的 PowerShell 环境

## 安装与启动

克隆项目，然后在项目根目录执行

```powershell
pip install -e .
```

待安装成功后执行 `topilot` 即可运行

首次运行会自动进入交互式配置向导，生成默认配置文件 `~/.topilot/config.json`

也可以手动进行初始化

```powershell
topilot init
topilot doctor
topilot start
```

## 配置说明

可自行修改配置 JSON 文件，固定位置为 `~/.topilot/config.json`

目录结构

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

常用配置字段

- `telegram.bot_token`：Telegram 机器人令牌（必填）
- `telegram.enabled`：是否启用 Telegram 通道
- `telegram.allowed_chat_ids`：允许访问的 Telegram Chat ID，可使用数组或逗号分隔字符串。留空代表允许所有 Chat ID 访问，强烈建议配置以保证安全
- `telegram.proxy_url`：如需使用代理访问 Telegram API，需要设置代理 URL，例如 `http://127.0.0.1:10808`
- `feishu.enabled`：是否启用 Feishu 通道
- `feishu.app_id`：Feishu 自建应用 App ID
- `feishu.app_secret`：Feishu 自建应用 App Secret
- `feishu.allowed_chat_ids`：允许访问的 Feishu Chat ID 白名单，留空代表不按 chat_id 限制
- `feishu.allowed_open_ids`：允许访问的 Feishu 用户 open_id 白名单，留空代表不按 open_id 限制
- `feishu.reply_in_thread`：Feishu 拒绝提示是否使用线程回复
- `copilot.cli_command`：运行 Copilot CLI 所需的命令，默认 `copilot`
- `copilot.model`：Copilot CLI 默认使用的模型，默认为 `gpt-5-mini`
- `copilot.available_models`：模型实时发现失败时使用的回退候选列表
- `copilot.timeout_seconds`：单次调用超时秒数，默认为 3600
- `copilot.allow_all_tools`：调用 Copilot CLI 时是否附带 `--allow-all-tools`
- `copilot.allow_all_paths`：是否附带 `--allow-all-paths`，开启后允许访问任意路径，适合个人可信环境
- `copilot.add_workspace_dir`：调用 Copilot CLI 时是否自动附带 `--add-dir`
- `copilot.additional_allowed_dirs`：额外允许 Copilot 访问的目录列表；当需要读取工作区外目录时，在这里显式加入
- `copilot.reasoning_effort`：传递给 Copilot CLI 的推理强度，可为空
- `copilot.forward_reasoning`：是否在非流式路径转发思考文本
- `runtime.workspace_root`：默认工作区路径
- `runtime.session_watch_interval_seconds`：会话追踪轮询间隔，运行时按 `1` 至 `15` 秒范围生效
- `logging.log_level`：文件日志级别
- `logging.console_log_level`：控制台日志级别
- `logging.httpx_log_level`：`httpx` 日志级别，建议 WARNING，避免轮询请求刷屏

当 `telegram.enabled=false` 且 `feishu.enabled=true` 时，Topilot 将以 Feishu-only 模式常驻运行。
当两者都启用时，Feishu 长连接会在后台线程启动，Telegram 轮询保持主线程运行。

## Bot 可用命令

- `/whoami`：查看当前 chat/user 信息
- `/session_current`：查看当前会话 ID 与简要摘要
- `/sessions`：会话管理入口（列表/接管/历史/删除）
- `/session_new [title]`：新建并切换到会话
- `/session_use <session_id前缀>`：按唯一前缀切换已保存会话，或接管本机发现的唯一匹配会话；前缀不唯一时会拒绝切换
- `/model`：查看/切换当前模型
- `/status`：查看后端状态、当前会话、来源、状态、模型和工作区摘要，并可通过按钮打开后端诊断报告
- 直接发送文本将进入对话

Bot 启动时会自动向 Telegram 注册命令菜单；`/start`、`/status`、`/model`、`/sessions`、`/session_current` 等入口也提供内联按钮，常用操作可直接点击完成。

Feishu 当前复用同一套 `TaskRunner`、会话持久化和 Copilot 调用链。收到文本或 `post` 富文本消息后会直接进入当前会话上下文；同时已提供机器人自定义菜单、卡片按钮快捷操作，以及基于交互卡片的进度刷新与结果展示。

## License

MIT License，详见 [LICENSE](./LICENSE)
