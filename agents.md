# Topilot AI 协作规范

## 1. 项目基础背景
Topilot 是一个将本地 GitHub Copilot CLI 能力桥接到 Telegram Bot 的轻量级个人 AI 工具项目，开发目标是让用户在离开电脑后，仍能通过手机继续使用、查看和接管本机 Copilot 会话。

## 2. 仓库实际目录结构
以下目录结构以当前仓库实际内容为准，AI 在修改代码或文档前必须先确认目标文件所在位置，禁止凭经验臆测目录。

```text
copilot-in-telegram/
├─ .git/                          # Git 元数据
├─ .venv/                         # 本地 Python 虚拟环境
├─ .vscode/                       # 编辑器配置
├─ assets/                        # README/PPT 使用的图片资源
├─ data/                          # 本地运行过程中使用的项目数据目录
├─ doc/                           # 课程验收正式文档目录
│  ├─ 需求/                       # PRD、需求规格说明书
│  ├─ 架构/                       # ADR、架构决策文档
│  ├─ 计划/                       # 总计划、阶段计划、模块执行计划
│  │  ├─ 阶段1/
│  │  └─ 阶段2/
│  ├─ 设计/                       # 详细设计文档
│  ├─ 测试/                       # 测试方案、测试用例、测试结果文档
│  └─ 验收/                       # 模块验收报告
├─ logs/                          # 本地运行日志目录
├─ src/
│  └─ topilot/
│     ├─ cli/                     # CLI 入口与子命令
│     ├─ agent.py                 # Copilot CLI 调用、JSON 流解析、工具摘要
│     ├─ config.py                # JSON 配置读写与旧版 .env 迁移
│     ├─ conversation_store.py    # chats.json 对话历史持久化
│     ├─ copilot_sessions.py      # 本地 session-state 扫描、接管、删除
│     ├─ logging_setup.py         # 日志初始化与级别控制
│     ├─ main.py                  # 兼容入口
│     ├─ models.py                # 基础数据模型
│     ├─ paths.py                 # 应用目录结构定义
│     ├─ session_store.py         # sessions.json 会话与模型持久化
│     ├─ task_runner.py           # Telegram 请求调度与业务编排
│     └─ telegram_bot.py          # Telegram Bot 接入层、命令、按钮、流式展示
├─ tests/                         # pytest 测试目录，包含配置、存储、会话扫描、事件解析等基础测试
├─ .env.example                   # 旧版环境变量配置示例（已废弃，仅迁移使用）
├─ .gitattributes
├─ .gitignore
├─ cloud.md                       # 云与部署规范
├─ config.example.json            # JSON 配置示例
├─ Copilot-help-info.txt          # 辅助说明资料
├─ designer.md                    # Telegram 交互风格约束
├─ LICENSE
├─ pyproject.toml                 # Python 包与依赖声明
├─ README-en.md
├─ README.md
└─ Tips.md                        # 本地个人记录，不作为正式文档依据
```

## 3. AI 协作规则

### 3.1 基本工作原则
1. 所有分析和改动必须以 `src/topilot/` 中的真实实现为准，禁止根据 README 或历史草稿倒推功能。
2. `doc/` 目录中的文档是课程验收正式依据，代码改动后必须同步更新对应文档，保持文档与代码 100% 匹配。
4. AI 不得把 `agents.md` 写成需求文档或设计文档；该文件只负责规范、索引和约束。
5. AI 不得在未确认实现存在的情况下新增“已完成”描述，例如图片输入、浏览器自动化、插件市场等当前未实现能力。
6. AI 不得直接执行 Git 提交、推送、创建 PR；仓库提交由项目负责人手动完成。

### 3.2 多代理/多模块协作约定
1. 若后续引入多代理协作，主代理负责需求对齐、目录选择、最终合稿和一致性校验。
2. 子代理只能在被明确授权的模块范围内工作，例如“仅修改 `src/topilot/config.py` 及对应设计文档”。
3. 任一代理完成代码改动后，必须回写以下四类信息：修改文件、变更原因、影响模块、需要同步更新的文档。

### 3.3 输出与编码规范
1. 默认输出语言为中文，文档表达要求专业、准确、可验收。
2. Python 代码基于 3.12+，保持类型标注、模块拆分和当前项目风格一致。
3. 新增功能说明时必须同时写清输入、输出、异常路径和验收口径。
4. 任何与 Telegram 交互相关的说明必须使用项目已实现的命令、按钮和文案语义，不得虚构页面。

### 3.4 文档同步规则
1. 需求变化：更新 `doc/需求/` 与 `doc/计划/`。
2. 架构变化：更新 `doc/架构/` 与 `doc/设计/`。
3. 模块新增或重构：更新对应阶段执行计划、详细设计、测试用例、验收报告。
4. 配置字段、命令、路径变化：同步更新 `README.md`、`config.example.json`、`agents.md` 文档索引。

## 4. 全量文档索引

### 4.1 根目录规范文件
- `agents.md`：项目全局 AI 协作规范与索引
- `cloud.md`：部署、权限、运维与成本约束
- `designer.md`：Telegram 交互风格与界面约束

### 4.2 课程验收核心文档
- `doc/需求/Topilot-需求规格说明书.md`
- `doc/架构/Topilot-ADR架构决策文档.md`
- `doc/计划/Topilot-开发总计划.md`
- `doc/计划/阶段1/阶段1-配置与启动模块-执行计划.md`
- `doc/计划/阶段1/阶段1-Telegram接入与访问控制模块-执行计划.md`
- `doc/计划/阶段2/阶段2-Copilot对话与流式展示模块-执行计划.md`
- `doc/计划/阶段2/阶段2-会话管理与接管模块-执行计划.md`
- `doc/计划/阶段2/阶段2-模型发现与切换模块-执行计划.md`
- `doc/设计/Topilot-详细设计文档.md`
- `doc/测试/Topilot-测试方案与测试用例.md`
- `doc/验收/Topilot-阶段1与阶段2模块验收报告.md`

## 5. 项目全局约束

### 5.1 技术栈约束
1. 后端语言固定为 Python 3.11+。
2. Telegram 接入固定使用 `python-telegram-bot` 22.x。
3. HTTP 相关依赖使用 `httpx`。
4. 当前版本不引入数据库，持久化方式固定为 JSON 文件。
5. 当前运行形态为单进程长轮询 Bot，不设计为多实例分布式系统。

### 5.2 安全约束
1. Bot Token、代理地址、工作区路径不得硬编码进源码。
2. 访问控制必须以 `telegram.allowed_chat_ids` 为准，`/whoami` 作为例外诊断命令保留开放。
3. 会话接管仅允许读取本机 `~/.copilot/session-state`，不得扩展为任意系统目录扫描。
4. 项目定位为个人可信环境工具，不宣称企业级隔离能力。

### 5.3 交付约束
1. 课程验收以 Git 仓库中的 Markdown 文档和代码为唯一依据。
2. 文档描述必须与命令、配置项、目录、数据结构、回调行为逐项对应。
3. 若自动化测试覆盖范围仍不足，文档必须如实标记缺口，不得虚构覆盖率结果或联调结论。
