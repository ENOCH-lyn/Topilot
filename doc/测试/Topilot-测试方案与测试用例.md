# Topilot 测试方案与测试用例

## 1. 文档说明
本文档用于说明 Topilot 当前版本的测试范围、测试环境、测试方法、测试用例和结果记录口径。仓库中已提交基础 `pytest` 自动化测试，覆盖配置解析、交互式初始化、启动诊断、会话存储容错、本机会话扫描边界、Copilot 事件解析、Copilot CLI 异常提示、Telegram 白名单、Telegram 长轮询自恢复、Feishu 文本/富文本事件、机器人菜单、卡片回调、命令注册、模型菜单和会话回调渲染逻辑。与此同时，项目负责人已完成真实 Telegram 外网联调、真实 Feishu 外网联调与真实 Copilot CLI 集成联调。

## 2. 测试目标
1. 验证配置、启动、诊断链路是否可用。
2. 验证 Telegram / Feishu 入口、白名单控制和命令路由是否正确。
3. 验证 Copilot CLI 调用、流式解析和异常处理是否符合设计。
4. 验证会话管理、接管、删除和自动追踪是否符合预期。
5. 验证模型发现、回退和切换是否可用。

## 3. 测试范围

### 3.1 纳入测试
1. `src/topilot/config.py`
2. `src/topilot/paths.py`
3. `src/topilot/cli/main.py`
4. `src/topilot/task_runner.py`
5. `src/topilot/agent.py`
6. `src/topilot/session_store.py`
7. `src/topilot/conversation_store.py`
8. `src/topilot/copilot_sessions.py`
9. `src/topilot/telegram_bot.py`
10. `src/topilot/feishu_bot.py`

### 3.2 已完成手工联调
1. 真实 Telegram 外网消息收发与命令交互
2. 真实 Feishu 外网消息收发与长连接事件链路
3. 真实 Copilot CLI 登录、对话与流式回复链路
4. 真实运行环境下的状态查询、模型切换与会话管理流程

### 3.3 当前未纳入自动化验证
1. 不同代理工具的兼容性差异
2. 真实 Telegram / Copilot CLI 外网联调的全自动回放

## 4. 测试环境

| 项目 | 要求 |
| --- | --- |
| 操作系统 | Windows 10/11 或兼容的 PowerShell 运行环境 |
| Python | 3.11+ |
| Bot 框架 | `python-telegram-bot` 22.x |
| Feishu SDK | `lark-oapi` 1.6.8+ |
| 运行方式 | 本地命令行 + 可选临时目录 |
| Copilot CLI | 已安装，集成测试场景下需完成登录 |

## 5. 测试方法
1. 单元测试：配置解析、JSON 存储、会话扫描、事件转译等纯逻辑模块。
2. 集成测试：CLI 子命令、TaskRunner 提交流程、菜单合并逻辑。
3. 手工联调：在真实 Telegram、Feishu 与 Copilot CLI 环境下验证端到端流程。

## 5.1 当前已落仓的 pytest 套件
截至 2026-06-15，仓库已提交以下测试文件：
1. `tests/test_config.py`：覆盖交互式 `init --force` 配置生成、已有配置不覆盖、配置写入备份、配置加载、非法 Chat ID 忽略、Telegram / Feishu 配置校验、Feishu-only 模式、缺失接入密钥异常、`doctor` 诊断输出、Copilot 命令可执行性、无效超时和工作区问题清单。
2. `tests/test_stores.py`：覆盖对话历史裁剪、坏历史记录跳过、会话激活、陈旧 active 值处理、会话前缀唯一性、模型保存、会话删除、状态摘要、当前会话摘要、后端诊断文本、实时本机会话元数据优先级、本机会话前缀接管、会话菜单合并、会话详情/历史/实时载荷和提交流程中的默认会话元数据落地。
3. `tests/test_copilot_sessions.py`：覆盖 `session-state` 目录解析、历史提取、排序、删除和路径型会话 ID 拒绝。
4. `tests/test_agent.py`：覆盖 Copilot CLI 参数组装、流式事件转译、模型帮助文本解析、`copilot help config` 模型段解析、`.ps1` 帮助命令包装、模型列表回退、CLI 未就绪诊断、非零退出码、空输出、超时提示，以及工具摘要、命令输出、JSONL 提取和若干辅助分支。
5. `tests/test_telegram_helpers.py`：覆盖主菜单、状态面板、后端诊断面板、模型按钮布局、模型列表去重、文本分块、会话菜单分页、会话详情/历史/删除确认按钮、回调 payload 解析、白名单放行、未授权拒绝、命令注册表、Telegram 命令菜单注册列表、回调 pattern、`getUpdates` 超时配置和轮询网络异常重建标记。
6. `tests/test_feishu_bot.py`：覆盖 Feishu 文本/富文本内容解析、白名单校验、文本事件提交、文本分段进度发送、机器人菜单事件、卡片动作回调、模型切换、会话列表分页、会话详情/历史预览、运行中会话实时刷新和卡片 patch 更新。
7. `tests/test_cli_main.py`：覆盖 CLI 入口参数分发、首次运行初始化、Telegram-only / 双通道 / Feishu-only 启动、代理环境变量写入、Telegram 轮询重建流程和 `__main__` 入口。
8. `tests/test_logging_setup.py`：覆盖日志级别解析、根日志处理器替换、文件/控制台级别设置和 `httpx` 日志级别设置。
9. `tests/conftest.py`：提供测试路径和公共测试夹具。

本地执行命令：
```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

本次实际结果：
```text
120 passed
```

## 5.2 手工联调结果
截至 2026-06-15，项目负责人已在真实 Telegram、真实 Feishu 与真实 Copilot CLI 环境下完成手工联调，验证结论如下：
1. Bot 启动、命令菜单注册和授权访问控制正常。
2. 已授权 Telegram Chat 可完成文本对话、流式回复查看和状态查询。
3. 已授权 Feishu Chat 可完成文本或富文本对话、菜单入口调用、卡片按钮操作，以及以文本消息分段形式返回过程和最终结果。
4. 模型切换、会话管理和本机会话接管等核心链路可正常使用。
5. 外网消息往返与本地 Copilot CLI 调用协同正常，未发现阻断性问题。

## 6. 测试用例

### 6.1 配置与启动模块

| 用例编号 | 用例名称 | 前置条件 | 输入 | 预期结果 |
| --- | --- | --- | --- | --- |
| CFG-01 | 默认配置生成 | 空临时目录 | 执行 `topilot init --force` | 生成 `config.json`，包含 Telegram、Feishu、Copilot、运行时、存储和日志分组 |
| CFG-02 | 配置覆盖备份 | 已存在旧配置 | 写入新配置 | 生成 `config.backup-*.json` |
| CFG-03 | 启动前诊断 | 已存在或不存在配置均可 | 执行 `topilot doctor` | 输出 `app_home`、`config`、`has_config`、配置状态、Token 状态、Copilot 命令解析、命令可执行性、工作区状态、超时配置和 `issues` |
| CFG-04 | 缺少 Token 启动失败 | `telegram.bot_token` 为空 | 执行 `topilot start` | 返回非零状态并提示缺失字段 |
| CFG-05 | 诊断问题清单 | 空 Token、缺失 Copilot 命令、无效超时、工作区不存在 | 执行 `topilot doctor` | `issues` 中逐项列出对应问题 |
| CFG-06 | 交互式初始化 | 空临时目录并模拟用户输入 | 执行 `topilot init --force` | 写入 `config.json`，Token、Chat ID、模型、工作区、轮询间隔与输入一致 |
| CFG-07 | 已有配置保护 | `config.json` 已存在 | 执行 `topilot init` | 不覆盖现有配置，提示使用 `topilot init --force` |
| CFG-08 | 非法 Chat ID 容错 | `allowed_chat_ids` 字符串中混有非数字项 | 加载配置 | 忽略非法项，保留合法整数 Chat ID |
| CFG-09 | Feishu-only 配置加载 | `telegram.enabled=false`，`feishu.enabled=true` 且填入 App ID / Secret | 加载配置 | 加载成功，允许仅以 Feishu 模式运行 |
| CFG-10 | 至少启用一个平台 | Telegram 与 Feishu 同时禁用 | 加载配置 | 启动前抛出配置异常 |
| CFG-11 | 一键恢复脚本 | 当前仓库已安装依赖并存在配置文件 | 执行 `scripts/restart-topilot.ps1` | 停止旧 Topilot 进程，启动新进程，`doctor` 通过，watchdog 重新启动 |

### 6.2 Telegram 接入与访问控制模块

| 用例编号 | 用例名称 | 前置条件 | 输入 | 预期结果 |
| --- | --- | --- | --- | --- |
| TG-01 | 白名单放行 | `allowed_chat_ids` 包含 chat_id | 发送普通文本 | 进入 `TaskRunner.submit()` |
| TG-02 | 白名单拒绝 | `allowed_chat_ids` 不包含 chat_id | 发送普通文本 | 返回未授权提示 |
| TG-03 | `/whoami` 免授权可用 | 任意 chat_id | 发送 `/whoami` | 返回 chat_id、user_id、username |
| TG-04 | 模型命令菜单 | 模型列表不为空 | 发送 `/model` | 返回带按钮的模型菜单 |
| TG-05 | 会话命令菜单 | 存在会话数据 | 发送 `/sessions` | 返回分页会话菜单 |
| TG-06 | 空白名单放行 | `allowed_chat_ids` 为空 | 发送普通文本 | 放行业务处理器 |
| TG-07 | Handler 注册完整性 | 构建 Application | 读取 handler 注册表 | 注册 PRD 要求的 8 个公开命令、3 个回调 pattern 和文本消息入口 |
| TG-08 | `/status` 后端诊断按钮 | Copilot 命令可执行且存在模型缓存 | 打开 `/status` 并点击“后端诊断” | 返回后端状态、命令、解析路径、工作区、模型、调用参数、候选模型和待处理问题 |
| TG-09 | 回调 payload 解析 | 含合法、非法、空白、负数页码的 callback_data | 调用解析函数 | 正确提取 payload，非法页码回退到第 0 页 |
| TG-10 | 模型菜单去重 | 模型列表含空值和重复值 | 渲染 `/model` 菜单 | 按两列生成按钮，重复模型不重复展示，当前模型带 `✓`，并提供状态、会话和主菜单按钮 |
| TG-11 | Telegram 命令菜单注册 | 构建 Bot 启动流程 | 读取 `_bot_commands()` | 注册 `start`、`status`、`model`、`sessions`、`session_current`、`session_new`、`session_use`、`whoami`，不注册 `llm` |
| TG-12 | 主菜单与导航按钮 | 渲染主菜单、状态面板和后端诊断面板 | 调用纯渲染函数 | 按钮 callback_data 使用 `nav:` 前缀并能回到主菜单 |
| TG-13 | 长轮询网络异常恢复 | Telegram 轮询层抛出无 Update 上下文的 `NetworkError` | 调用 Application error handler | 写入重建标记并停止当前 Application，启动层随后重建轮询实例 |

### 6.3 Feishu 接入与访问控制模块

| 用例编号 | 用例名称 | 前置条件 | 输入 | 预期结果 |
| --- | --- | --- | --- | --- |
| FS-01 | 文本内容解析 | 收到 Feishu 文本或 `post` 富文本消息事件 | 解析 `message.content` | 正确提取可执行文本 |
| FS-02 | 白名单放行 | `allowed_chat_ids` / `allowed_open_ids` 匹配 | 发送文本事件 | 进入 `TaskRunner.submit()` |
| FS-03 | 白名单拒绝 | 白名单不匹配 | 发送文本事件 | 返回未授权提示，不进入任务执行 |
| FS-04 | 非受支持消息忽略 | 收到非 `text` / `post` 消息 | 发送事件 | 不进入任务执行 |

### 6.4 Copilot 对话与流式展示模块

| 用例编号 | 用例名称 | 前置条件 | 输入 | 预期结果 |
| --- | --- | --- | --- | --- |
| AGT-01 | CLI 未就绪提示 | `copilot.cli_command` 为空或指向不存在命令 | 提交请求 | 返回后端未就绪提示，包含问题原因和 `topilot doctor` 建议 |
| AGT-02 | 回复增量流展示 | 伪造 `assistant.message_delta` 事件流 | 提交请求 | 回复消息增量刷新 |
| AGT-03 | 工具调用摘要 | 伪造 `tool.execution_start/complete` | 提交请求 | 过程消息展示中文摘要 |
| AGT-04 | CLI 非零退出码 | 伪造进程失败 | 提交请求 | 返回退出码、stderr/out 摘要和排查建议 |
| AGT-05 | 超长文本截断 | 返回文本超过 3500 字符 | 提交请求 | 消息被切分或截断，不发送失败 |
| AGT-06 | CLI 空输出 | 伪造进程成功但 stdout/stderr 为空 | 提交请求 | 返回空结果提示，并提示检查登录、命令路径和 `--output-format json` 支持 |
| AGT-07 | CLI 超时 | 伪造进程长时间不退出 | 提交请求 | 杀掉子进程并返回包含超时秒数的提示 |
| AGT-08 | CLI 运行前诊断 | 命令存在、工作区存在、超时有效 | 调用诊断函数 | 返回“Copilot CLI 已就绪”并展示命令、工作区、模型和调用参数 |

### 6.5 会话管理与接管模块

| 用例编号 | 用例名称 | 前置条件 | 输入 | 预期结果 |
| --- | --- | --- | --- | --- |
| SES-01 | 首次请求自动建会话 | 无 `sessions.json` | 提交普通文本 | 自动创建默认会话 |
| SES-02 | 会话前缀切换 | 已保存多个会话，且前缀唯一 | `/session_use <prefix>` | 切换到匹配会话 |
| SES-03 | 会话前缀歧义拒绝 | 已保存多个会话共享同一短前缀 | `/session_use <short_prefix>` | 返回“会话前缀不唯一”，不切换当前会话 |
| SES-04 | 本机会话前缀接管 | 存在唯一匹配的 `session-state` 会话目录 | `/session_use <prefix>` 或点击“接管会话” | 接管成功并同步元数据 |
| SES-05 | 运行中会话追踪 | 本机会话处于运行中 | 在会话详情页点击“接管会话”后等待轮询 | 同一条消息持续刷新 |
| SES-06 | 实时元数据优先展示 | 已保存会话和本地 `session-state` 存在同一会话 ID | 打开 `/sessions`、`/session_current` 或 `/status` | 标题、模型、工作区、来源、运行状态优先显示本机实时扫描结果 |
| SES-07 | 会话删除确认 | Bot 侧或本地存在会话 | 点击“删除会话” | 先展示确认删除页，不立即删除 |
| SES-08 | 会话确认删除 | 已展示确认删除页 | 点击“确认删除” | 返回“会话已删除”或“会话不存在或无法删除” |
| SES-09 | 会话菜单分页容错 | 会话数量超过一页 | 渲染负数页码、过大页码、非法页码 | 展示页码被夹到合法范围，导航按钮 callback_data 正确 |
| SES-10 | 会话回调按钮结构 | 存在会话 ID | 渲染详情、历史、删除确认页 | 按钮分别包含接管、历史、刷新、删除、确认删除、取消、返回列表等 callback_data |
| SES-11 | 路径型会话 ID 拒绝 | 构造绝对路径或 `../` 形式 session_id | 调用会话读取/删除 | 拒绝访问 session-state 根目录外路径，不删除外部目录 |

### 6.6 模型发现与切换模块

| 用例编号 | 用例名称 | 前置条件 | 输入 | 预期结果 |
| --- | --- | --- | --- | --- |
| MOD-01 | 主帮助模型解析 | 模拟 `copilot --help` 的 `--model` 参数块包含 choices | 启动应用 | 缓存模型列表正确 |
| MOD-02 | 避免误读其他参数候选值 | 模拟 `copilot --help` 中 `--model` 无 choices、`--output-format` 含 `text/json` choices | 启动应用 | 不把 `text`、`json` 解析为模型 |
| MOD-03 | 配置帮助模型解析 | 模拟 `copilot help config` 的 `model` 配置段 | 启动应用 | 从配置帮助中读取真实模型候选并去重 |
| MOD-04 | PowerShell 帮助命令包装 | `copilot.cli_command` 指向 `.ps1` | 启动模型发现 | 使用 `powershell -File <command> --help` 和 `powershell -File <command> help config` 形式探测 |
| MOD-05 | 配置回退模型列表 | 实时解析失败且配置存在候选模型 | 启动应用 | 使用配置中的候选模型 |
| MOD-06 | 默认模型兜底 | 实时解析失败且配置候选模型为空 | 启动应用 | 使用当前默认模型作为候选模型 |
| MOD-07 | 自动模型参数省略 | 当前模型为 `auto` | 发起 Copilot CLI 请求 | 命令参数中不包含 `--model` |
| MOD-08 | 过期模型回退 | `sessions.json` 中保存的模型不在当前候选列表 | 发起请求 | 使用默认 `auto`，不再传递旧模型 |
| MOD-09 | 模型合法切换 | 模型存在于列表中 | 点击模型按钮 | 当前模型更新并持久化 |
| MOD-10 | 模型非法切换 | 模型不在列表中 | 点击模型按钮 | 返回“模型不存在” |
| MOD-11 | 模型列表清理 | 模型缓存包含空值与重复值 | 渲染模型按钮或校验回调 | 空值被忽略，重复项只保留一次 |

## 7. 测试结果记录要求
1. 每次执行测试时，需记录执行日期、执行环境、执行人、用例编号、是否通过、失败原因。
2. 对手工验证项，应附 Telegram / Feishu 截图或日志片段作为证据。
3. 对自动化测试项，应保存命令输出和失败堆栈。
4. 2026-06-22 的完整回归结果为 `.\.venv\Scripts\python.exe -m pytest -q`，120 项全部通过，可作为当前提交版的自动化测试基线。
