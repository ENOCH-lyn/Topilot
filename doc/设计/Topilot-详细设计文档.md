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

### 2.2 配置与路径模块

#### 2.2.1 代码位置
`src/topilot/config.py`、`src/topilot/paths.py`

#### 2.2.2 职责
1. 定义应用目录结构。
2. 提供默认配置模板。
3. 负责 JSON 配置读写、备份、字段解析与强校验。
4. 提供启动前诊断报告，汇总配置文件状态、关键目录状态与核心配置摘要。

#### 2.2.3 设计原因
1. 使用 `Settings` 数据类集中承载运行配置，减少下游模块耦合。
2. 使用解析函数统一转换布尔值、整数、浮点数和模型列表，避免散落在业务层。

### 2.3 Telegram 接入模块

#### 2.3.1 代码位置
`src/topilot/telegram_bot.py`

#### 2.3.2 职责
1. 构建 Telegram Application。
2. 注册命令、文本消息和按钮回调。
3. 提供白名单访问控制。
4. 实现过程消息、回复消息、会话菜单和模型菜单。

#### 2.3.3 设计要点
1. 使用 `restricted()` 装饰器统一做权限校验，降低 handler 重复代码。
2. 使用 `TelegramLiveProgress` 承担所有流式消息编辑和限频逻辑。
3. 使用按钮回调数据前缀区分菜单类型，如 `model_sel:`、`smenu:`、`sopen:`、`suse:`、`shis:`、`sdel:`。

### 2.4 任务编排模块

#### 2.4.1 代码位置
`src/topilot/task_runner.py`

#### 2.4.2 职责
1. 汇总对话历史、当前会话、当前模型、工作区等上下文。
2. 调用 `AssistantPlanner` 执行单轮对话。
3. 负责请求前后的持久化写入。
4. 聚合会话菜单数据和接管逻辑。

#### 2.4.3 设计要点
1. `TaskRunner` 是系统业务协调中心，但不直接关心 Telegram API 细节。
2. 对流式输出通过 `LiveProgress` 协议抽象，避免与具体消息实现耦合。

### 2.5 Copilot CLI 调用模块

#### 2.5.1 代码位置
`src/topilot/agent.py`

#### 2.5.2 职责
1. 组装 Copilot CLI 命令参数。
2. 启动子进程并消费标准输出/标准错误。
3. 解析 JSON 流事件并分类。
4. 将工具调用与命令输出压缩为中文摘要。

#### 2.5.3 设计要点
1. 通过 `--resume <session_id>` 保证上下文连续，而不是把完整历史手工拼接进 prompt。
2. 对 Windows `.bat`/`.cmd` 命令做换行转义，避免参数截断。
3. 对不同类型工具结果采用不同摘要策略，提高移动端可读性。

### 2.6 会话扫描模块

#### 2.6.1 代码位置
`src/topilot/copilot_sessions.py`

#### 2.6.2 职责
1. 扫描本地 `~/.copilot/session-state` 目录。
2. 解析 `workspace.yaml`、`events.jsonl`、`inuse.*.lock`。
3. 提取工作区、模型、运行状态、最后事件时间和历史摘要。

#### 2.6.3 设计要点
1. 使用本地目录扫描而不是额外服务接口，最大化复用 Copilot 原生状态。
2. 历史摘要只保留最近若干条，避免 Telegram 消息过长。

### 2.7 持久化模块

#### 2.7.1 代码位置
`src/topilot/conversation_store.py`、`src/topilot/session_store.py`

#### 2.7.2 职责
1. 保存每个 Chat 的最近对话历史。
2. 保存每个 Chat 的当前会话、会话列表和当前模型。

#### 2.7.3 设计要点
1. 会话历史默认只保留最近 40 条，防止 JSON 无限增长。
2. 会话列表以最近使用时间为排序依据。

## 3. 接口设计

### 3.1 CLI 接口

| 命令 | 入参 | 输出 | 权限 | 异常 |
| --- | --- | --- | --- | --- |
| `topilot init [--force]` | 交互式输入或覆盖标志 | 生成配置文件 | 本地命令行用户 | 配置目录无权限、输入为空 |
| `topilot start` | 无 | 启动 Bot 长轮询 | 本地命令行用户 | 配置缺失、Token 为空 |
| `topilot doctor` | 无 | 输出默认 app_home、config、has_config，以及基础配置健康摘要 | 本地命令行用户 | 无 |

### 3.2 Telegram 命令接口

| 命令 | 入参 | 输出 | 权限 | 失败反馈 |
| --- | --- | --- | --- | --- |
| `/start` | 无 | 命令列表 | 受白名单控制 | 未授权提示 |
| `/help` | 无 | 命令列表 | 受白名单控制 | 未授权提示 |
| `/whoami` | 无 | chat_id / user_id / username | 开放 | 无 |
| `/llm` | 无 | 后端状态文本 | 受白名单控制 | 未授权提示 |
| `/session_current` | 无 | 当前会话 ID | 受白名单控制 | 未授权提示 |
| `/sessions` | 无 | 会话菜单 | 受白名单控制 | 未授权提示 |
| `/session_new [title]` | 可选标题 | 新建并切换会话 | 受白名单控制 | 未授权提示 |
| `/session_use <prefix>` | 会话前缀 | 切换或接管结果 | 受白名单控制 | 会话不存在 / 未授权 |
| `/model` | 无 | 模型选择键盘 | 受白名单控制 | 无可用模型 / 未授权 |
| `/status` | 无 | 后端状态、当前会话、来源、状态、模型与工作区摘要 | 受白名单控制 | 未授权提示 |

### 3.3 回调接口

| 回调前缀 | 作用 | 典型值 |
| --- | --- | --- |
| `model_sel:` | 切换模型 | `model_sel:gpt-5-mini` |
| `smenu:` | 会话菜单分页 | `smenu:0` |
| `sopen:` | 打开会话详情 | `sopen:<session_id>` |
| `suse:` | 接管会话 | `suse:<session_id>` |
| `shis:` | 查看会话历史 | `shis:<session_id>` |
| `sdel:` | 删除会话 | `sdel:<session_id>` |

## 4. 数据结构设计

### 4.1 `config.json`

#### 4.1.1 设计思路
采用分组对象结构，分别描述 Telegram、Copilot、运行时、存储和日志配置，便于扩展与校验。

#### 4.1.2 字段设计

| 分组 | 字段 | 类型 | 说明 |
| --- | --- | --- | --- |
| `telegram` | `bot_token` | string | Telegram Bot Token |
| `telegram` | `allowed_chat_ids` | array[int] | 白名单 Chat ID |
| `telegram` | `proxy_url` | string/null | Telegram 代理 |
| `copilot` | `cli_command` | string | Copilot CLI 命令 |
| `copilot` | `model` | string | 默认模型 |
| `copilot` | `available_models` | array[string] | 模型回退列表 |
| `copilot` | `timeout_seconds` | int | 调用超时 |
| `copilot` | `allow_all_tools` | bool | 是否允许所有工具 |
| `copilot` | `add_workspace_dir` | bool | 是否自动附带 `--add-dir` |
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

### 4.2 `chats.json`

#### 4.2.1 设计思路
按 `chat_id` 为 key 存储最近对话轮次，避免引入数据库。

#### 4.2.2 结构

```json
{
  "123456": [
    {
      "role": "user",
      "content": "请解释当前仓库结构",
      "created_at": "2026-05-03T12:00:00+00:00"
    }
  ]
}
```

### 4.3 `sessions.json`

#### 4.3.1 设计思路
把“当前会话”“会话列表”“当前模型”三类状态放在一个 JSON 文件中，便于按 Chat 维度管理。

#### 4.3.2 结构

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
  }
}
```

## 5. 核心算法设计

### 5.1 模型列表解析算法
1. 启动子进程执行 `copilot --help`。
2. 使用正则定位 `--model <model>` 的 choices 段。
3. 解析引号包裹的模型名称。
4. 若失败则回退到配置中的 `available_models`。

### 5.2 流事件转译算法
1. 逐行读取 CLI 标准输出。
2. 非 JSON 行直接忽略。
3. 对 `assistant.message_delta` 进入回复流。
4. 对 `tool.execution_start/complete` 按工具类型摘要。
5. 对噪声事件过滤。
6. 对 `assistant.message` 作为无 delta 场景的兜底最终回复。

### 5.3 回复拼接算法
1. 若新 chunk 以前缀形式覆盖现有内容，则直接替换。
2. 若现有内容与新 chunk 存在后缀/前缀重叠，则只拼接差量部分。
3. 若 chunk 很短且像标点或零碎 delta，则直接追加。

### 5.4 会话列表合并算法
1. 先取 Bot 已保存会话列表。
2. 再取本机发现会话列表。
3. 以 `session_id` 去重。
4. 以 `last_event_at` 或 `last_used_at` 逆序排序。
5. 对当前会话加 `active` 标记。

## 6. 异常处理方案

| 场景 | 处理策略 |
| --- | --- |
| 配置文件不存在 | 抛出 `ConfigurationError`，首次运行自动引导初始化 |
| 配置文件为空或 JSON 非法 | 启动失败并返回明确错误 |
| `telegram.bot_token` 为空 | 启动失败并提示缺失字段 |
| Copilot CLI 不可用 | 返回统一后端未就绪提示 |
| Copilot CLI 超时 | 杀掉子进程并返回超时提示 |
| Copilot CLI 返回非零退出码 | 返回 stderr/out 摘要 |
| Telegram HTML 解析失败 | 自动回退为纯文本过程消息 |
| 会话目录不存在 | 返回“会话不存在或已被删除” |

## 7. 设计边界
1. 当前不处理图片、语音、文件上传等多模态输入。
2. 当前不设计数据库表结构，持久化统一为 JSON 文件结构设计。
3. 当前不实现企业级审计、操作审批和多租户隔离。
