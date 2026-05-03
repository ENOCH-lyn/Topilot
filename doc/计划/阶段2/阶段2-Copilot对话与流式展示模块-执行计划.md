# 阶段2-Copilot对话与流式展示模块-执行计划

## 1. 模块定位
该模块是 Topilot 的核心执行引擎，负责把 Telegram 文本请求转换为本地 Copilot CLI 调用，并将 CLI 的 JSON 流输出转为适合 Telegram 展示的“过程日志 + 回复流”双通道消息。

## 2. 模块核心功能
1. 基于当前会话和当前模型调用 Copilot CLI。
2. 解析 JSONL 流事件，区分回复增量、最终回复、思考、工具执行与噪声事件。
3. 将工具执行和命令输出转为中文摘要。
4. 在 Telegram 中以流式方式刷新回复与过程消息。
5. 在请求结束后把用户输入和 AI 回复写入会话历史。

## 3. 输入与输出

### 3.1 输入
1. `chat_id`
2. 用户输入文本
3. 当前会话 ID
4. 当前模型
5. 工作区目录
6. Copilot CLI 输出的 JSON 流事件

### 3.2 输出
1. Telegram 过程消息
2. Telegram 最终回复消息
3. `chats.json` 中的用户/助手对话记录
4. 错误提示或超时提示

## 4. 核心实现逻辑
1. `TaskRunner.submit()` 负责拉取最近历史、确保当前会话存在并打开流式输出对象。
2. `AssistantPlanner.plan()` 判断 CLI 是否可用，不可用时统一返回后端未就绪提示。
3. `_build_copilot_argv()` 组装 `--resume`、`--model`、`--output-format json`、`-p`、`-s`、`--add-dir`、`--allow-all-tools` 等参数。
4. `_forward_stdout_line()` 对每行 JSON 事件进行解析并分发到回复流或过程流。
5. `TelegramLiveProgress` 负责双消息渲染、限频编辑、重复日志合并和 HTML 回退。

## 5. 技术方案与可选方案

### 5.1 选用方案
采用本地子进程调用 Copilot CLI，并通过标准输出 JSON 流实时消费。

### 5.2 可选方案比较
1. 只读取最终输出：实现简单，但丢失过程可视化。
2. 原样转发 JSON：信息过载，不适合手机阅读。
3. 事件分类转译：兼顾信息量和可读性，最终选用。

## 6. 可自动化验收标准
1. 当 Copilot CLI 连续输出 `assistant.message_delta` 事件时，Telegram 回复消息必须呈现增量更新，且最终写入 `chats.json` 的助手回复与最终显示文本一致。
2. 当出现 `tool.execution_start` 和 `tool.execution_complete` 事件时，系统必须输出中文过程摘要，且对 `report_intent`、`sql`、`session.tools_updated` 等噪声事件不输出日志。
3. 当 Copilot CLI 返回非零退出码、超时或空输出时，系统必须返回明确错误提示，错误信息长度控制在 200 字符以内的摘要范围。
4. Telegram 过程消息编辑间隔不得高于每 1 秒 1 次，回复消息编辑间隔不得高于每 0.8 秒 1 次。
5. 单条 Telegram 文本超过 3500 字符时，系统必须执行截断或分块，避免消息发送失败。

## 7. 测试数据与测试方案

### 7.1 测试数据
1. 含 `assistant.message_delta` 的标准 JSONL 事件样例。
2. 含工具调用、命令输出、搜索结果的 JSONL 事件样例。
3. 超时、空输出、非零退出码等异常样例。
4. 超长文本输出样例。

### 7.2 测试方案
1. 通过伪造 Copilot CLI JSONL 事件流测试事件解析逻辑。
2. 通过替身对象验证 `reply()`、`log()` 的调用顺序和节流行为。
3. 对异常路径进行错误文案断言。

## 8. 模块依赖关系
1. 依赖配置模块提供 Copilot CLI 命令、超时、工作区和推理参数。
2. 依赖 Telegram 接入模块提供消息收发通道。
3. 依赖对话历史与会话存储模块完成状态持久化。

## 9. 开发顺序
1. 先完成 Copilot CLI 子进程启动和命令组装。
2. 再完成 JSONL 事件解析和工具摘要。
3. 然后实现 Telegram 流式渲染与节流。
4. 最后打通历史写入和异常路径。
