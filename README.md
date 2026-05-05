<div align="center">
<img width="100" src="./assets/logo.png">
<h1 align="center">Topilot</h1></div>

简体中文 | [English](./README-en.md)

将  GitHub Copilot CLI 接入 Telegram Bot 使用

## 运行截图

<div align="center" style=" gap: 20px; flex-wrap: wrap; justify-content: center;">
<img width="200" src="./assets/model.jpg">
<img width="200" src="./assets/sessions.jpg">
<br><br><br>
<img width="200" src="./assets/tools.jpg">
</div>

## 项目背景

Openclaw等项目消耗Token速度普遍较快，但是很多功能在日常生活中用不到

而学生党能免费用Copilot，日常使用时可能有远程操控的需求，希望能像 OpenClaw 那样接入 Bot 使用

因此，本项目提供了将 GitHub Copilot CLI 接入 Telegram Bot 的能力

## 功能特性

- Telegram 机器人接入与 Chat ID 白名单控制
- Copilot 会话功能与多会话切换
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

克隆项目，然后在项目根目录执行

```powershell
pip install -e .
```

待安装成功后执行`topilot`即可运行

首次运行会自动进入交互式配置向导，生成默认配置文件 `~/.topilot/config.json`

也可以手动进行初始化

```powershell
topilot init
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
- `telegram.allowed_chat_ids`：允许访问的 Telegram Chat ID，多个用逗号分隔。留空代表允许所有 Chat ID 访问，强烈建议配置以保证安全
- `telegram.proxy_url`：如需使用代理访问 Telegram API，需要设置代理 URL，例如 `http://127.0.0.1:10808`
- `topilot.cli_command`：运行Copilot CLI 所需的命令，默认 `copilot`
- `topilot.model`：Copilot CLI 默认使用的模型，默认为`gpt-5-mini`
- `topilot.timeout_seconds`：单次调用超时秒数，默认为3600
- `runtime.workspace_root`：默认工作区路径
- `runtime.session_watch_interval_seconds`：接管会话轮询间隔
- `logging.log_level`：文件日志级别
- `logging.console_log_level`：控制台日志级别
- `logging.httpx_log_level`：`httpx` 日志级别，建议 WARNING，避免轮询请求刷屏

## Bot 可用命令

- `/whoami`：查看当前 chat/user 信息
- `/llm`：查看 Topilot 后端状态
- `/session_current`：查看当前会话 ID 与简要摘要
- `/sessions`：会话管理入口（列表/接管/历史/删除）
- `/session_new [title]`：新建并切换到会话
- `/session_use <session_id前缀>`：切换会话
- `/model`：查看/切换当前模型
- `/status`：查看运行状态
- 直接发送文本将进入对话

## 待办

- [ ] 优化接管session时的输出
- [ ] 继续优化工具展示结果
- [ ] 默认工作区可以加入记忆层来模拟openclaw等工具
- [ ] 支持copilot插件
- [ ] 增强交互功能，例如用户选项，运行执行命令等功能
- [ ] pip库上传，方便安装
- [ ] 支持telegram快捷命令
- [ ] 更深层次的copilot适配
- [ ] 图片功能支持
- [ ] 浏览器支持
- [ ] 开机自启
- [ ] 完善配置选项，安装教程等
- [ ] 删除无用功能（vibe coding残留）
- [ ] 解决有可能的权限问题

## License

MIT License，详见 [LICENSE](./LICENSE)

## 免责声明
项目为个人兴趣开发的非商业项目，旨在探索 GitHub Copilot CLI 的 Telegram Bot 接入可能性。由于项目大多为vibe coding而来，加上资源和能力有限，因此无法提供任何形式的安全保证或责任承担。使用本项目可能存在安全风险，包括但不限于未经授权的访问、数据泄露、滥用等。请务必在安全的环境中使用，并自行承担使用风险。对于任何因使用本项目而导致的损失或问题，本项目概不负责。
