# Topilot 详细设计文档

## 1. 设计目标
本文档基于当前代码实现，对 Topilot 的模块职责、接口、数据结构、核心算法和异常处理方案进行细化说明，作为架构设计与代码实现之间的落地桥梁。

## 2. 模块详细设计

### 2.1 CLI 入口模块

#### 2.1.1 代码位置
`src/topilot/cli/main.py`

#### 2.1.2 职责
1. 提供 `init`、`start`、`doctor` 子命令。
2. 在首次运行时自动触发初始化。
3. 统一调度配置加载、日志初始化与 Telegram Application 启动。

#### 2.1.3 设计要点
1. CLI 入口不直接处理业务逻辑，只做环境准备和流程分发。
2. 配置文件固定存放在 `~/.topilot/config.json`，避免出现多套配置目录。
3. `doctor` 不启动 Telegram，也不调用真实 Copilot 对话，只执行配置、目录、命令可执行性和问题清单诊断，用于启动前检查。

### 2.2 配置与路径模块

#### 2.2.1 代码位置
`src/topilot/config.py`、`src/topilot/paths.py`

#### 2.2.2 职责
1. 定义应用目录结构。
2. 提供默认配置模板。
3. 负责 JSON 配置读写、备份、字段解析与强校验。
4. 提供启动前诊断报告，汇总配置文件状态、关键目录状态、Copilot CLI 命令解析结果、运行工作区状态与问题清单。

#### 2.2.3 设计原因
1. 使用 `Settings` 数据类集中承载运行配置，减少下游模块耦合。
2. 使用解析函数统一转换布尔值、整数、浮点数和模型列表，避免散落在业务层。
3. `telegram.allowed_chat_ids` 支持数组或逗号分隔字符串，非法项会被忽略，避免单个错误值导致整个配置加载失败。

### 2.3 Telegram 接入模块

#### 2.3.1 代码位置
`src/topilot/telegram_bot.py`

#### 2.3.2 职责
1. 构建 Telegram Application。
2. 注册命令、文本消息和按钮回调。
3. 提供白名单访问控制。
4. 实现过程消息、回复消息、会话菜单、模型菜单和待确认提示按钮。

#### 2.3.3 设计要点
1. 使用 `restricted()` 装饰器统一做权限校验，降低 handler 重复代码。
2. 使用 `TelegramLiveProgress` 承担所有流式消息编辑和限频逻辑。
3. 使用按钮回调数据前缀区分菜单类型，如 `model_sel:`、`pending:`、`smenu:`、`sopen:`、`suse:`、`shis:`、`sdel:`、`sdelok:`。
4. 模型菜单、会话详情、会话历史、删除确认页均使用独立渲染函数生成文本和按钮，避免回调分支中散落重复 UI 结构。
5. 回调 payload 和页码统一通过 `_callback_payload()`、`_callback_page()` 解析，非法页码或负数统一回到第 0 页。

### 2.4 任务编排模块

#### 2.4.1 代码位置
`src/topilot/task_runner.py`

#### 2.4.2 职责
1. 汇总对话历史、当前会话、当前模型、工作区等上下文。
2. 调用 `AssistantPlanner` 执行单轮对话。
3. 负责请求前后的持久化写入与待确认交互状态维护。
4. 聚合会话菜单数据和接管逻辑。

#### 2.4.3 设计要点
1. `TaskRunner` 是系统业务协调中心，但不直接关心 Telegram API 细节。
2. 对流式输出通过 `LiveProgress` 协议抽象，避免与具体消息实现耦合。
3. 当存在 Copilot `ask_user` 请求时，`TaskRunner` 会把问题、选项和所属会话写入持久化存储，并将用户下一条文本视为该问题的回答。
4. 当前会话摘要优先读取实时 `session-state` 元数据，避免已保存会话在本机状态变化后仍展示旧模型、旧工作区或旧运行状态。

### 2.5 Copilot CLI 调用模块

#### 2.5.1 代码位置
`src/topilot/agent.py`

#### 2.5.2 职责
1. 组装 Copilot CLI 命令参数。
2. 启动子进程并消费标准输出/标准错误。
3. 解析 JSON 流事件并分类。
4. 将工具调用与命令输出压缩为中文摘要。
5. 提取 Copilot `ask_user` 事件中的问题文本、候选选项和权限确认语义。
6. 提供 Copilot CLI 运行前诊断能力，用于 `/status` 后端诊断按钮、状态摘要和请求失败提示。

#### 2.5.3 设计要点
1. 通过 `--session-id <session_id>` 绑定和恢复 Copilot CLI 会话，保证上下文连续，而不是把完整历史手工拼接进 prompt。
2. 对 Windows `.bat`/`.cmd` 命令做换行转义，避免参数截断。
3. 对不同类型工具结果采用不同摘要策略，提高移动端可读性。
4. 在调用前检查 `copilot.cli_command` 是否可解析、工作区是否存在、超时配置是否有效；未就绪时不启动子进程，直接返回可行动的中文提示。
5. 对 `ask_user` 事件采用宽松字段提取策略，兼容问题文本、候选选项和权限类提示的不同载荷结构。
6. 对非零退出码、超时和空输出分别生成稳定错误摘要，并建议用户执行 `topilot doctor` 排查。

### 2.6 会话扫描模块

#### 2.6.1 代码位置
`src/topilot/copilot_sessions.py`

#### 2.6.2 职责
1. 扫描本地 `~/.copilot/session-state` 目录。
2. 解析 `workspace.yaml`、`events.jsonl`、`inuse.*.lock`。
3. 提取工作区、模型、运行状态、最后事件时间和历史摘要。

#### 2.6.3 设计要点
1. 使用本地目录扫描而不是额外服务接口，直接复用 Copilot 原生状态。
2. 历史摘要只保留最近若干条，避免 Telegram 消息过长。
3. 会话读取和删除只接受 `session-state` 根目录下的直接子目录名，拒绝绝对路径、`../` 等路径型会话 ID。

### 2.7 持久化模块

#### 2.7.1 代码位置
`src/topilot/conversation_store.py`、`src/topilot/session_store.py`

#### 2.7.2 职责
1. 保存每个 Chat 的最近对话历史。
2. 保存每个 Chat 的当前会话、会话列表、当前模型和待确认交互状态。

#### 2.7.3 设计要点
1. 会话历史默认只保留最近 40 条，防止 JSON 无限增长。
2. 会话列表以最近使用时间为排序依据。
3. 读取持久化 JSON 时会跳过结构异常的记录，避免单条坏数据导致整个 Bot 无法启动。
4. 写入 `chats.json`、`sessions.json` 前会确保父目录存在。
5. 当前激活会话必须能在会话列表中找到；若持久化文件中存在陈旧 active 值，将按无激活会话处理。
6. 若待确认交互绑定的会话被删除，对应待确认状态也会一并清除。

## 3. 接口设计

### 3.1 CLI 接口

| 命令 | 入参 | 输出 | 权限 | 异常 |
| --- | --- | --- | --- | --- |
| `topilot init [--force]` | 交互式输入或覆盖标志 | 生成配置文件 | 本地命令行用户 | 配置目录无权限、输入为空 |
| `topilot start` | 无 | 启动 Bot 长轮询 | 本地命令行用户 | 配置缺失、Token 为空 |
| `topilot doctor` | 无 | 输出 `app_home`、`config`、`has_config`、配置状态、Token 状态、Copilot 命令解析、命令可执行性、工作区状态、超时配置和问题清单 | 本地命令行用户 | 无 |

### 3.2 Telegram 命令接口

| 命令 | 入参 | 输出 | 权限 | 失败反馈 |
| --- | --- | --- | --- | --- |
| `/start` | 无 | 主菜单按钮面板 | 受白名单控制 | 未授权提示 |
| `/whoami` | 无 | chat_id / user_id / username | 开放 | 无 |
| `/session_current` | 无 | 当前会话 ID 及简要摘要 | 受白名单控制 | 未授权提示 |
| `/sessions` | 无 | 会话菜单 | 受白名单控制 | 未授权提示 |
| `/session_new [title]` | 可选标题 | 新建并切换会话 | 受白名单控制 | 未授权提示 |
| `/session_use <prefix>` | 会话前缀 | 切换或接管结果 | 受白名单控制 | 会话不存在 / 未授权 |
| `/model` | 无 | 模型选择键盘 | 受白名单控制 | 无可用模型 / 未授权 |
| `/status` | 无 | 后端状态、当前会话、来源、状态、模型与工作区摘要，并提供后端诊断按钮 | 受白名单控制 | 未授权提示 |

### 3.3 回调接口

| 回调前缀 | 作用 | 典型值 |
| --- | --- | --- |
| `model_sel:` | 切换模型 | `model_sel:gpt-5-mini` |
| `pending:` | 提交待确认问题的候选答案 | `pending:0` |
| `nav:` | 主菜单、状态、后端诊断、模型、会话等通用导航 | `nav:status` |
| `smenu:` | 会话菜单分页 | `smenu:0` |
| `sopen:` | 打开会话详情 | `sopen:<session_id>` |
| `suse:` | 接管会话 | `suse:<session_id>` |
| `shis:` | 查看会话历史 | `shis:<session_id>` |
| `sdel:` | 进入删除确认页 | `sdel:<session_id>` |
| `sdelok:` | 确认删除会话 | `sdelok:<session_id>` |

## 4. 数据结构设计

### 4.1 `config.json`

#### 4.1.1 设计思路
采用分组对象结构，分别描述 Telegram、Copilot、运行时、存储和日志配置，便于统一扩展与校验。

#### 4.1.2 字段设计

| 分组 | 字段 | 类型 | 说明 |
| --- | --- | --- | --- |
| `telegram` | `bot_token` | string | Telegram Bot Token |
| `telegram` | `allowed_chat_ids` | array[int]/string | 白名单 Chat ID，支持数组或逗号分隔字符串 |
| `telegram` | `proxy_url` | string/null | Telegram 代理 |
| `copilot` | `cli_command` | string | Copilot CLI 命令 |
| `copilot` | `model` | string | 默认模型 |
| `copilot` | `available_models` | array[string] | 模型回退列表 |
| `copilot` | `timeout_seconds` | int | 调用超时 |
| `copilot` | `allow_all_tools` | bool | 是否允许所有工具 |
| `copilot` | `allow_all_paths` | bool | 是否允许访问任意路径 |
| `copilot` | `add_workspace_dir` | bool | 是否自动附带 `--add-dir` |
| `copilot` | `additional_allowed_dirs` | array[string] | 额外允许访问的目录列表 |
| `copilot` | `reasoning_effort` | string/null | 推理强度 |
| `copilot` | `forward_reasoning` | bool | 是否转发思考文本 |
| `runtime` | `workspace_root` | string | 默认工作区 |
| `runtime` | `session_watch_interval_seconds` | float | 会话追踪轮询间隔 |
| `storage` | `chat_db_path` | string | 聊天历史文件 |
| `storage` | `session_db_path` | string | 会话索引文件 |
| `storage` | `log_file_path` | string | 日志文件 |
| `logging` | `log_level` | string | 文件日志级别 |
| `logging` | `console_log_level` | string | 控制台日志级别 |
| `logging` | `httpx_log_level` | string | `httpx` 日志级别 |

### 4.2 `DoctorReport`

#### 4.2.1 设计思路
`DoctorReport` 是 `topilot doctor` 的结构化输出来源，只读取配置与文件系统状态，不发起 Telegram 或 Copilot 对话请求，确保诊断命令安全、快速、可重复。

#### 4.2.2 字段设计

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `has_config` | bool | `~/.topilot/config.json` 是否存在 |
| `config_status` | string | `missing`、`invalid` 或 `ok` |
| `telegram_token_status` | string | `unknown`、`invalid`、`empty` 或 `set` |
| `copilot_cli_command` | string/null | 配置中的 Copilot CLI 命令 |
| `copilot_cli_resolved_command` | string/null | 解析后的可执行路径或原始命令 |
| `copilot_cli_runnable` | bool/null | 当前系统是否能找到或访问该命令 |
| `copilot_model` | string/null | 默认模型 |
| `copilot_timeout_seconds` | int/null | Copilot 调用超时秒数 |
| `workspace_root` | string/null | 运行工作区路径 |
| `runtime_workspace_exists` | bool/null | 运行工作区是否存在 |
| `issues` | array[string] | 可直接展示给用户的问题清单 |

### 4.3 `chats.json`

#### 4.3.1 设计思路
按 `chat_id` 为 key 存储最近对话轮次，避免引入数据库。

#### 4.3.2 结构

```json
{
  "123456": [
    {
      "role": "user",
      "content": "请解释项目目录结构",
      "created_at": "2026-05-03T12:00:00+00:00"
    }
  ]
}
```

### 4.4 `sessions.json`

#### 4.4.1 设计思路
把“当前会话”“会话列表”“当前模型”“待确认交互状态”四类状态放在一个 JSON 文件中，便于按 Chat 维度统一管理。

#### 4.4.2 结构

```json
{
  "active": {
    "123456": "session-id"
  },
  "sessions": {
    "123456": [
      {
        "id": "session-id",
        "title": "default",
        "created_at": "2026-05-03T12:00:00+00:00",
        "last_used_at": "2026-05-03T12:10:00+00:00",
        "cwd": "C:/workspace",
        "model": "gpt-5-mini",
        "source": "local",
        "last_event_at": "2026-05-03T12:09:55+00:00",
        "running": true
      }
    ]
  },
  "models": {
    "123456": "gpt-5-mini"
  },
  "pending": {
    "123456": {
      "kind": "permission_request",
      "question": "Allow reading Desktop?",
      "session_id": "session-id",
      "options": [
        "Allow",
        "Deny"
      ],
      "created_at": "2026-06-10T09:30:00+00:00"
    }
  }
}
```

## 5. 核心算法设计

### 5.1 Copilot CLI 诊断算法
1. 读取 `copilot.cli_command`、当前模型、默认工作区、超时、工具权限和推理强度配置。
2. 通过 `_resolve_copilot_command()` 解析可执行命令：优先使用配置命令，失败时尝试系统 PATH 中的 `copilot`，再尝试 VS Code Copilot CLI 的 `.bat`/`.ps1` 默认位置。
3. 判断解析后的命令是否可启动：PATH 命令使用 `shutil.which()`，路径命令检查文件是否存在。
4. 判断实际工作区是否存在；若接管会话传入的工作区不可用，则回退到默认工作区。
5. 判断 `copilot.timeout_seconds` 是否大于 0。
6. 将所有问题聚合进 `issues`，生成 `CopilotCliDiagnostic`；若 `issues` 为空，状态为“Copilot CLI 已就绪”，否则为“Copilot CLI 未就绪”。
7. `/status` 使用诊断对象渲染后端状态摘要，并通过 `nav:diagnostic` 按钮渲染完整后端诊断报告；普通对话在未就绪时直接返回失败提示，不启动 Copilot 子进程。

### 5.2 模型列表解析算法
1. 通过 `_build_copilot_help_argv()` 构造主帮助命令，普通可执行文件使用 `<command> --help`，`.ps1` 入口使用 PowerShell `-File <command> --help` 包装。
2. 若 Copilot CLI 诊断未就绪，则跳过实时探测，避免启动必然失败的子进程。
3. 启动子进程读取主帮助输出，只在 `--model <model>` 自身帮助块内解析 choices，避免误读 `--output-format` 等其他参数的候选值。
4. 若主帮助未列出模型候选，则继续执行 `copilot help config`，从 `model` 配置段读取模型列表。
5. 解析引号包裹的模型名称，并去重保留原顺序；Telegram 按钮展示前再次通过 `_normalize_model_list()` 清理空值与重复项，保证按钮展示和合法性校验口径一致。
6. 若实时解析失败，则回退到配置中的 `available_models`。
7. 若配置回退列表为空，则至少返回当前默认模型，保证 `/model` 不因空列表失效。

### 5.3 流事件转译算法
1. 逐行读取 CLI 标准输出。
2. 非 JSON 行直接忽略。
3. 对 `assistant.message_delta` 进入回复流。
4. 对 `tool.execution_start/complete` 按工具类型摘要。
5. 当工具类型为 `ask_user` 时，额外提取问题文本、候选选项和权限语义，并写入待确认状态。
6. 对噪声事件过滤。
7. 对 `assistant.message` 作为无 delta 场景的兜底最终回复。

### 5.4 回复拼接算法
1. 若新 chunk 以前缀形式覆盖现有内容，则直接替换。
2. 若现有内容与新 chunk 存在后缀/前缀重叠，则只拼接差量部分。
3. 若 chunk 很短且像标点或零碎 delta，则直接追加。

### 5.5 会话列表合并算法
1. 先取 Bot 已保存会话列表。
2. 再取本机发现会话列表。
3. 以 `session_id` 去重；同一会话同时存在于两侧时，标题、模型、工作区、运行状态和最后事件时间优先采用本机实时扫描结果。
4. 以 `last_event_at` 或 `last_used_at` 逆序排序。
5. 对当前会话加 `active` 标记。

### 5.6 会话前缀切换算法
1. `/session_use <prefix>` 先在 Bot 已保存会话中查找匹配前缀。
2. 若已保存会话存在多个匹配项，返回“会话前缀不唯一”提示，不切换当前会话。
3. 若已保存会话唯一匹配，则按完整会话 ID 切换当前会话。
4. 若已保存会话无匹配，则刷新本机 `session-state` 会话列表并查找前缀。
5. 若本机会话唯一匹配，则执行接管；若多个匹配，则返回歧义提示，要求输入更长前缀。

### 5.7 Telegram 回调渲染算法
1. `/start` 使用 `_render_main_menu()` 渲染主菜单按钮，提供状态与诊断、模型切换、会话管理、当前会话、新建会话和我的 ID 入口。
2. `/status` 使用 `_render_status_panel()` 渲染状态摘要，并提供“后端诊断”“模型切换”“会话管理”“当前会话”“主菜单”等按钮。
3. `nav:diagnostic` 使用 `_render_diagnostic_panel()` 展示完整 Copilot 后端诊断报告；`nav:model`、`nav:sessions`、`nav:session_current`、`nav:session_new` 等导航回调分别复用对应菜单渲染函数。
4. `/model` 命令先读取运行期模型缓存，再用 `_normalize_model_list()` 去除空值和重复值。
5. `_render_model_menu()` 生成“当前模型 + 请选择模型”的文本和两列模型按钮；当前模型按钮带 `✓` 标识，并追加状态、会话和主菜单按钮。
6. `/sessions` 与 `smenu:` 回调共用 `_render_session_menu()`，页码先通过 `_callback_page()` 清洗，再按 `page_size` 切片；小于 0、非数字或超过最大页时自动夹到合法范围。
7. `sopen:` 回调用 `_render_session_detail()` 生成“接管会话、查看历史、刷新详情、删除会话、返回列表、主菜单”按钮。
8. `shis:` 回调用 `_render_session_history()` 生成“刷新历史、返回详情、返回列表、主菜单”按钮。
9. `sdel:` 回调用 `_render_session_delete_confirm()` 生成“确认删除、取消、返回列表、主菜单”按钮，确保删除操作必须二次确认。
10. 当待确认问题存在候选选项时，`_render_pending_prompt()` 生成 `pending:` 按钮，用户点击后直接把候选答案提交给原会话继续执行。
11. `model_sel:`、`pending:`、`nav:`、`sopen:`、`suse:`、`shis:`、`sdel:`、`sdelok:` 的 payload 均通过 `_callback_payload()` 提取并去除首尾空白。

## 6. 异常处理方案

| 场景 | 处理策略 |
| --- | --- |
| 配置文件不存在 | 抛出 `ConfigurationError`，首次运行自动引导初始化 |
| 配置文件为空或 JSON 非法 | 启动失败并返回明确错误 |
| `telegram.bot_token` 为空 | 启动失败并提示缺失字段 |
| Copilot CLI 命令不存在或不可执行 | `/status` 的后端诊断按钮和 `topilot doctor` 展示命令解析问题；普通请求返回后端未就绪提示 |
| Copilot 工作区不存在 | 诊断报告写入 `issues`；普通请求不启动子进程 |
| Copilot CLI 超时 | 杀掉子进程，返回包含超时秒数和排查建议的提示 |
| Copilot CLI 返回非零退出码 | 返回退出码和 stderr/out 的 200 字符内摘要 |
| Copilot CLI 返回空输出 | 返回“stdout/stderr 均为空”的明确提示，并提示检查登录、命令路径和 `--output-format json` 支持 |
| Telegram HTML 解析失败 | 自动回退为纯文本过程消息 |
| Telegram 回调页码非法 | 回退到第 0 页，不抛出异常 |
| 模型列表包含空值或重复值 | 渲染前去重清理，合法性校验使用同一清理结果 |
| 会话目录不存在 | 返回“会话不存在或已被删除” |
| 会话 ID 是绝对路径或包含路径分隔符 | 拒绝读取或删除，返回未找到 / 无法删除 |
| 会话 ID 前缀匹配多个会话 | 返回“会话前缀不唯一”，要求提供更长前缀 |
| `chats.json` 或 `sessions.json` 存在局部坏记录 | 跳过坏记录，保留可解析数据继续运行 |
| 存储文件父目录不存在 | 写入前创建父目录 |
| 待确认问题已失效或按钮索引越界 | 返回“当前没有待确认问题”或“选项已失效”，不继续调用 Copilot |

## 7. 设计边界
1. 当前不处理图片、语音、文件上传等多模态输入。
2. 当前不设计数据库表结构，持久化统一为 JSON 文件结构设计。
3. 当前不实现企业级审计、操作审批和多租户隔离。
