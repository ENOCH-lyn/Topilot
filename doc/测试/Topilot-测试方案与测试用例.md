# Topilot 测试方案与测试用例

## 1. 文档说明
本文档用于描述 Topilot 当前版本的测试范围、测试环境、测试方法和测试用例设计。当前仓库已经补齐基础 `pytest` 自动化测试源码，覆盖配置解析、会话存储、本机会话扫描、Copilot 事件解析和 Telegram 纯逻辑辅助函数；同时，真实 Telegram 外网联调、真实 Copilot CLI 集成联调和覆盖率报告仍需继续补强。

## 2. 测试目标
1. 验证配置、启动、诊断链路是否可用。
2. 验证 Telegram 入口、白名单控制和命令路由是否正确。
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

### 3.2 暂不纳入自动化验证
1. 真实 Telegram 外网通信稳定性
2. 真实 Copilot 账号质量与返回内容质量
3. 不同代理工具的兼容性差异

## 4. 测试环境

| 项目 | 要求 |
| --- | --- |
| 操作系统 | Windows 10/11 或兼容的 PowerShell 运行环境 |
| Python | 3.11+ |
| Bot 框架 | `python-telegram-bot` 22.x |
| 运行方式 | 本地命令行 + 可选临时目录 |
| Copilot CLI | 已安装，集成测试场景下需完成登录 |

## 5. 测试方法
1. 单元测试：配置解析、JSON 存储、会话扫描、事件转译等纯逻辑模块。
2. 集成测试：CLI 子命令、TaskRunner 提交流程、菜单合并逻辑。
3. 手工验证：真实 Telegram 和真实 Copilot CLI 联调。

## 5.1 当前已落仓的 pytest 套件
截至 2026-05-05，仓库已提交以下测试文件：
1. `tests/test_config.py`：覆盖配置写入备份、配置加载、缺失 Token 异常。
2. `tests/test_stores.py`：覆盖对话历史裁剪、会话激活、模型保存、会话删除。
3. `tests/test_copilot_sessions.py`：覆盖 `session-state` 目录解析、历史提取、排序和删除。
4. `tests/test_agent.py`：覆盖 Copilot CLI 参数组装、流式事件转译。
5. `tests/test_telegram_helpers.py`：覆盖模型按钮布局、文本分块、会话菜单渲染。
6. `tests/conftest.py`：提供测试路径和公共测试夹具。

本地执行命令：
```powershell
pytest
```

本次实际结果：
```text
12 passed
```

## 6. 测试用例

### 6.1 配置与启动模块

| 用例编号 | 用例名称 | 前置条件 | 输入 | 预期结果 |
| --- | --- | --- | --- | --- |
| CFG-01 | 默认配置生成 | 空临时目录 | 执行 `topilot init --force` | 生成 `config.json`，包含五大分组 |
| CFG-02 | 配置覆盖备份 | 已存在旧配置 | 写入新配置 | 生成 `config.backup-*.json` |
| CFG-03 | 启动前诊断 | 已存在或不存在配置均可 | 执行 `topilot doctor` | 输出 `app_home`、`config`、`has_config` |
| CFG-04 | 缺少 Token 启动失败 | `telegram.bot_token` 为空 | 执行 `topilot start` | 返回非零状态并提示缺失字段 |

### 6.2 Telegram 接入与访问控制模块

| 用例编号 | 用例名称 | 前置条件 | 输入 | 预期结果 |
| --- | --- | --- | --- | --- |
| TG-01 | 白名单放行 | `allowed_chat_ids` 包含 chat_id | 发送普通文本 | 进入 `TaskRunner.submit()` |
| TG-02 | 白名单拒绝 | `allowed_chat_ids` 不包含 chat_id | 发送普通文本 | 返回未授权提示 |
| TG-03 | `/whoami` 免授权可用 | 任意 chat_id | 发送 `/whoami` | 返回 chat_id、user_id、username |
| TG-04 | 模型命令菜单 | 模型列表不为空 | 发送 `/model` | 返回带按钮的模型菜单 |
| TG-05 | 会话命令菜单 | 存在会话数据 | 发送 `/sessions` | 返回分页会话菜单 |

### 6.3 Copilot 对话与流式展示模块

| 用例编号 | 用例名称 | 前置条件 | 输入 | 预期结果 |
| --- | --- | --- | --- | --- |
| AGT-01 | CLI 未就绪提示 | `copilot.cli_command` 为空 | 提交请求 | 返回后端未就绪提示 |
| AGT-02 | 回复增量流展示 | 伪造 `assistant.message_delta` 事件流 | 提交请求 | 回复消息增量刷新 |
| AGT-03 | 工具调用摘要 | 伪造 `tool.execution_start/complete` | 提交请求 | 过程消息展示中文摘要 |
| AGT-04 | CLI 非零退出码 | 伪造进程失败 | 提交请求 | 返回错误摘要 |
| AGT-05 | 超长文本截断 | 返回文本超过 3500 字符 | 提交请求 | 消息被切分或截断，不发送失败 |

### 6.4 会话管理与接管模块

| 用例编号 | 用例名称 | 前置条件 | 输入 | 预期结果 |
| --- | --- | --- | --- | --- |
| SES-01 | 首次请求自动建会话 | 无 `sessions.json` | 提交普通文本 | 自动创建默认会话 |
| SES-02 | 会话前缀切换 | 已保存多个会话 | `/session_use <prefix>` | 切换到匹配会话 |
| SES-03 | 本机会话接管 | 存在 `session-state` 会话目录 | 点击“接管会话” | 接管成功并同步元数据 |
| SES-04 | 运行中会话追踪 | 本机会话处于运行中 | 接管后等待轮询 | 同一条消息持续刷新 |
| SES-05 | 会话删除 | Bot 侧或本地存在会话 | 点击“删除会话” | 返回“会话已删除” |

### 6.5 模型发现与切换模块

| 用例编号 | 用例名称 | 前置条件 | 输入 | 预期结果 |
| --- | --- | --- | --- | --- |
| MOD-01 | 实时解析模型列表 | 模拟 `copilot --help` 输出 | 启动应用 | 缓存模型列表正确 |
| MOD-02 | 配置回退模型列表 | 实时解析失败 | 启动应用 | 使用配置中的候选模型 |
| MOD-03 | 模型合法切换 | 模型存在于列表中 | 点击模型按钮 | 当前模型更新并持久化 |
| MOD-04 | 模型非法切换 | 模型不在列表中 | 点击模型按钮 | 返回“模型不存在” |

## 7. 测试结果记录要求
1. 每次执行测试时，需记录执行日期、执行环境、执行人、用例编号、是否通过、失败原因。
2. 对手工验证项，应附 Telegram 截图或日志片段作为证据。
3. 对自动化测试项，应保存命令输出和失败堆栈。
4. 2026-05-05 的本地基线结果为 `pytest` 执行 12 项全部通过，可作为当前仓库版本的基础测试记录。

## 8. 覆盖率要求
1. 当前仓库尚未具备可核验的自动化覆盖率报告。
2. 当前已覆盖 `config.py`、`session_store.py`、`conversation_store.py`、`copilot_sessions.py`、`agent.py` 和 `telegram_bot.py` 中纯逻辑辅助函数。
3. 在正式形成覆盖率数据前，禁止在验收文档中虚构百分比结果。

## 9. 后续补强建议
1. 为 `TaskRunner.submit()` 增加带替身对象的流程级测试。
2. 为 `telegram_bot.py` 的 handler 和回调分支补齐更细粒度测试。
3. 增加真实 Copilot CLI 帮助输出解析样例与失败回退测试。
4. 引入覆盖率工具并沉淀可核验报告。
