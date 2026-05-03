# Topilot 部署与云资源规范

## 1. 当前部署定位
Topilot 当前采用单节点自托管部署模式，不依赖自建云端推理服务。系统通过 Telegram Bot API 接收消息，在部署主机本地调用已登录的 GitHub Copilot CLI，并将配置、日志、会话索引保存在当前用户目录下。

## 2. 部署选型

### 2.1 推荐运行环境
1. Windows 10/11 或 Windows Server 主机。
2. Python 3.11 及以上。
3. PowerShell 6+。
4. 已安装并完成 `copilot login` 的 GitHub Copilot CLI。
5. 稳定的 Telegram API 网络连通性；如有网络限制，可通过 `telegram.proxy_url` 配置代理。

### 2.2 选型原因
1. 代码已对 Windows 用户目录、PowerShell 命令和 Copilot CLI 的 `session-state` 目录形成天然适配。
2. 会话接管依赖当前系统用户下的 `~/.copilot/session-state`，因此单用户主机比容器化无状态方案更贴合现状。
3. 当前存储为本地 JSON 文件，不适合直接横向扩容到多实例。

## 3. 实际部署架构

```text
Telegram 用户
    ↓
Telegram Bot API
    ↓
Topilot 进程（python-telegram-bot 长轮询）
    ├─ 配置目录：~/.topilot/config.json
    ├─ 会话索引：~/.topilot/data/sessions.json
    ├─ 对话历史：~/.topilot/data/chats.json
    ├─ 日志文件：~/.topilot/logs/app.log
    └─ 本地 Copilot CLI 调用
            ↓
    ~/.copilot/session-state/   # 运行中会话、历史事件、工作区摘要
```

## 4. 环境与权限要求

### 4.1 运行账户权限
1. 运行 Topilot 的系统账户必须能访问其自身的 `~/.topilot/` 目录。
2. 运行账户必须能访问其自身的 `~/.copilot/session-state/` 目录，以支持会话发现和接管。
3. 运行账户必须对业务工作区拥有最小必要读写权限；禁止直接以管理员权限运行 Bot。

### 4.2 网络权限
1. 允许访问 Telegram Bot API。
2. 允许访问 GitHub Copilot CLI 正常工作所需网络资源。
3. 如启用代理，代理地址必须只在配置文件中维护，不得写死在启动脚本内。

## 5. 标准部署流程
1. 在目标主机安装 Python 3.11+ 与 PowerShell 6+。
2. 安装并验证 Copilot CLI，执行 `copilot login` 完成登录。
3. 拉取仓库代码，在项目根目录执行 `pip install -e .`。
4. 执行 `topilot init` 初始化配置，填写 Bot Token、允许访问的 Chat ID、Copilot CLI 命令、默认模型、默认工作区。
5. 使用 `topilot doctor` 核验配置目录和配置文件状态。
6. 执行 `topilot start` 启动 Bot。
7. 在 Telegram 中使用 `/whoami`、`/status`、`/model`、`/sessions` 完成运行验证。

## 6. 运维规范

### 6.1 配置管理
1. 统一使用 `~/.topilot/config.json` 维护正式配置。
2. 配置覆盖写入时，系统会自动生成 `config.backup-时间戳.json` 备份文件；运维修改后应保留最近一次可用备份。

### 6.2 日志管理
1. 日志文件默认写入 `~/.topilot/logs/app.log`。
2. 代码内已启用按 2 MB 单文件、保留 3 个备份的滚动日志策略。
3. `httpx` 日志建议保持 `WARNING`，避免长轮询刷屏影响排障。

### 6.3 故障处理
1. 若 `topilot start` 启动失败，优先检查 `config.json` 是否缺少 `telegram.bot_token`。
2. 若 Bot 无法返回 AI 内容，优先检查 `copilot` 命令是否可执行、账号是否已登录。
3. 若会话接管失败，优先检查 `~/.copilot/session-state/` 是否存在对应会话目录。

## 7. 成本约束与扩缩容方案

### 7.1 成本约束
1. 当前方案默认不采购数据库、中间件和独立 GPU/推理服务。
2. 主要成本来自目标主机、网络代理和现有 Copilot 账号本身。
3. 对个人项目而言，推荐优先复用已在日常使用的个人电脑或轻量 Windows 云主机。

### 7.2 扩容边界
1. 当前架构只支持单实例部署，扩容方式以单机纵向扩容为主。
2. 若未来需要多实例高可用，必须先把 JSON 存储改为共享数据源，并重构会话接管与锁控制逻辑。
3. 在未完成架构重构前，禁止宣传或部署多节点共享同一 Bot Token 的方案。
