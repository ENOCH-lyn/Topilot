# -*- coding: utf-8 -*-
"""生成期末报告所需的自绘配图（架构/时序/安全/会话/部署/模块）。
图中只保留必要的中文说明，不放多余文字。"""
import os
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch, Rectangle
from matplotlib.font_manager import FontProperties

FONT = FontProperties(fname=r"C:\Windows\Fonts\msyh.ttc")
FONTB = FontProperties(fname=r"C:\Windows\Fonts\msyhbd.ttc")
plt.rcParams["axes.unicode_minus"] = False

OUT = os.path.dirname(os.path.abspath(__file__))

# 统一配色（柔和、打印友好）
C_BLUE = "#cfe2f3"
C_GREEN = "#d9ead3"
C_ORANGE = "#fce5cd"
C_PURPLE = "#e6dbf0"
C_GRAY = "#efefef"
C_RED = "#f4cccc"
EDGE = "#5b6b7a"


def box(ax, x, y, w, h, text, fc=C_BLUE, fs=11, bold=False, ec=EDGE):
    p = FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.02,rounding_size=0.06",
                       linewidth=1.2, edgecolor=ec, facecolor=fc, mutation_aspect=1)
    ax.add_patch(p)
    ax.text(x + w / 2, y + h / 2, text, ha="center", va="center",
            fontproperties=FONTB if bold else FONT, fontsize=fs, color="#1c2733", wrap=True)
    return (x + w / 2, y + h / 2)


def arrow(ax, p1, p2, text="", style="-|>", color=EDGE, ls="-", rad=0.0, fs=9, off=(0, 0)):
    a = FancyArrowPatch(p1, p2, arrowstyle=style, mutation_scale=14, lw=1.3,
                        color=color, linestyle=ls, connectionstyle=f"arc3,rad={rad}")
    ax.add_patch(a)
    if text:
        mx, my = (p1[0] + p2[0]) / 2 + off[0], (p1[1] + p2[1]) / 2 + off[1]
        ax.text(mx, my, text, ha="center", va="center", fontproperties=FONT,
                fontsize=fs, color="#33404d",
                bbox=dict(boxstyle="round,pad=0.15", fc="white", ec="none", alpha=0.85))


def save(fig, name):
    path = os.path.join(OUT, name)
    fig.savefig(path, dpi=200, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print("saved", path)


# ---------------- 图1 系统总体架构（分层，规整布局） ----------------
def fig_arch():
    fig, ax = plt.subplots(figsize=(10.2, 9.2))
    ax.set_xlim(0, 20); ax.set_ylim(0, 19); ax.axis("off")

    # 五条分层带（浅色背景 + 左侧层名）
    layers = [
        (16.4, 2.0, "终端接入层", "#f3f1f8"),
        (13.0, 2.6, "IM 通道接入层", "#eef4fb"),
        (9.6, 2.0, "业务编排层", "#eef6ec"),
        (6.2, 2.0, "支撑模块", "#f4f4f4"),
        (1.6, 2.6, "Copilot 执行层", "#fdf2e6"),
    ]
    for y, h, name, col in layers:
        ax.add_patch(Rectangle((0.3, y), 17.4, h, facecolor=col, edgecolor="none", zorder=0))
        ax.text(18.9, y + h / 2, name, rotation=90, va="center", ha="center",
                fontproperties=FONTB, fontsize=10.5, color="#7a8896")

    # 列中心：左 / 中 / 右
    L, M, R = 3.7, 9.0, 14.3
    BW = 4.6  # 标准框宽

    # 终端接入层
    box(ax, L - BW / 2, 16.7, BW, 1.4, "用户移动端 / 桌面端\n（企业 IM 客户端）", C_PURPLE, 11, True)
    box(ax, R - BW / 2, 16.7, BW, 1.4, "运维终端 / 命令行\n（init · doctor · start）", C_PURPLE, 11, True)

    # IM 通道接入层
    box(ax, L - BW / 2, 14.3, BW, 1.5, "飞书长连接通道\n（lark-oapi WebSocket\n事件 / 卡片 / 菜单）", C_BLUE, 10.5, True)
    box(ax, R - BW / 2, 14.3, BW, 1.5, "长轮询公有 IM Bot 通道\n（long-polling\n断线重连 / 代理）", C_BLUE, 10.5, True)
    box(ax, 4.2, 13.15, 9.6, 0.85, "白名单访问控制 restricted()  ·  chat_id / open_id 鉴权", C_RED, 10.5, True)

    # 业务编排层
    box(ax, L - BW / 2, 9.9, BW, 1.4, "TaskRunner\n任务编排中心", C_GREEN, 11, True)
    box(ax, M - BW / 2, 9.9, BW, 1.4, "LiveProgress\n流式输出协议", C_GREEN, 11, True)
    box(ax, R - BW / 2, 9.9, BW, 1.4, "模型管理\n/model 切换", C_GREEN, 11, True)

    # 支撑模块
    box(ax, L - BW / 2, 6.5, BW, 1.4, "会话 / 历史持久化\nsessions · chats", C_GRAY, 10, True)
    box(ax, M - BW / 2, 6.5, BW, 1.4, "会话扫描与接管\nsession-state", C_GRAY, 10, True)
    box(ax, R - BW / 2, 6.5, BW, 1.4, "配置与诊断\nSettings · doctor", C_GRAY, 10, True)

    # Copilot 执行层
    box(ax, L - BW / 2, 1.9, BW, 1.6, "AssistantPlanner\n命令组装 / JSONL 解析", C_ORANGE, 10.5, True)
    box(ax, M - BW / 2, 2.0, BW, 1.4, "Copilot CLI\n子进程", C_ORANGE, 11, True)
    box(ax, R - BW / 2, 2.0, BW, 1.4, "本地工作区\nworkspace", C_ORANGE, 10.5, True)

    # 连线（规整的纵向 / 横向，避免穿框）
    arrow(ax, (L, 16.7), (L, 15.8))
    arrow(ax, (R, 16.7), (R, 15.8))
    arrow(ax, (L, 14.3), (L, 14.0))   # 飞书 -> 鉴权带
    arrow(ax, (R, 14.3), (R, 14.0))   # 长轮询 -> 鉴权带
    arrow(ax, (M, 13.15), (M, 11.3), text="鉴权通过")          # 鉴权 -> 业务层
    arrow(ax, (L, 9.9), (L, 7.9))                              # TaskRunner -> 持久化
    arrow(ax, (M, 9.9), (M, 7.9))                              # LiveProgress -> 会话扫描
    arrow(ax, (L, 6.5), (L, 3.5), text="单轮调用")             # -> AssistantPlanner
    arrow(ax, (L + BW / 2, 2.7), (M - BW / 2, 2.7), text="argv")
    arrow(ax, (M + BW / 2, 2.7), (R - BW / 2, 2.7), text="读写")
    # JSONL 流式事件：从 Copilot CLI 右侧上行回到 LiveProgress（走右侧空白，不穿框）
    arrow(ax, (M + BW / 2, 3.0), (M, 9.9), text="JSONL\n流式事件", rad=-0.32,
          color="#b06a00", ls="--")
    save(fig, "fig_arch.png")


# ---------------- 图2 单轮对话流式时序 ----------------
def fig_seq():
    fig, ax = plt.subplots(figsize=(9.6, 7.0))
    ax.set_xlim(0, 12); ax.set_ylim(0, 11); ax.axis("off")
    actors = ["用户", "IM 通道", "TaskRunner", "AssistantPlanner", "Copilot CLI"]
    xs = [1.2, 3.6, 6.0, 8.4, 10.8]
    top = 10.2; bottom = 0.8
    for x, name in zip(xs, actors):
        box(ax, x - 1.0, top, 2.0, 0.7, name, C_BLUE, 10.5, True)
        ax.plot([x, x], [top, bottom], color="#9aa7b3", lw=1.0, ls=(0, (4, 3)))

    def msg(i, j, y, text, ret=False, fs=9):
        style = "-|>"
        color = "#8a5a00" if ret else EDGE
        ls = "--" if ret else "-"
        a = FancyArrowPatch((xs[i], y), (xs[j], y), arrowstyle=style, mutation_scale=12,
                            lw=1.2, color=color, linestyle=ls)
        ax.add_patch(a)
        ax.text((xs[i] + xs[j]) / 2, y + 0.16, text, ha="center", va="bottom",
                fontproperties=FONT, fontsize=fs, color="#2a3540")

    msg(0, 1, 9.4, "发送指令文本")
    msg(1, 2, 9.0, "鉴权后转交（白名单校验）")
    msg(2, 3, 8.6, "汇总历史·会话·模型·工作区")
    msg(3, 4, 8.2, "启动子进程 --session-id/--output-format json")
    # 循环框
    ax.add_patch(Rectangle((2.4, 3.2), 9.0, 4.4, fill=False, ec="#b06a00", lw=1.1, ls="--"))
    ax.text(2.6, 7.35, "loop  逐行消费 JSONL 事件", fontproperties=FONTB, fontsize=9.5,
            color="#b06a00", bbox=dict(boxstyle="round,pad=0.15", fc="white", ec="none"))
    msg(4, 3, 7.0, "tool.execution_start/complete", ret=True)
    msg(3, 1, 6.5, "过程日志（工具/命令摘要）", ret=True)
    msg(4, 3, 5.9, "assistant.message_delta", ret=True)
    msg(3, 1, 5.4, "流式回复增量", ret=True)
    msg(1, 0, 4.9, "编辑消息 / 分段刷新", ret=True)
    msg(4, 3, 3.8, "assistant.turn_end", ret=True)
    msg(2, 1, 2.6, "最终回复 + 持久化历史", ret=True)
    msg(1, 0, 2.1, "展示完整回复", ret=True)
    save(fig, "fig_seq.png")


# ---------------- 图3 安全访问控制与权限边界 ----------------
def fig_security():
    fig, ax = plt.subplots(figsize=(9.4, 6.4))
    ax.set_xlim(0, 12); ax.set_ylim(0, 9); ax.axis("off")

    box(ax, 0.6, 6.8, 2.6, 1.4, "远程请求\n（IM 消息）", C_PURPLE, 10.5, True)

    # 第一道：身份认证
    box(ax, 4.0, 6.9, 3.4, 1.3, "① 身份认证\nchat_id / open_id 白名单\nrestricted() 统一拦截", C_RED, 10, True)
    box(ax, 8.2, 6.9, 3.2, 1.3, "未授权 → 拒绝提示\n（可线程回复）", C_GRAY, 10, False)
    # 第二道：通信安全
    box(ax, 4.0, 4.6, 3.4, 1.5, "② 通信安全\nBot Token / app_secret\n本地存储 + 代理\n长连接 / 长轮询", C_ORANGE, 10, True)
    # 第三道：执行边界
    box(ax, 0.4, 0.5, 3.5, 3.0, "③ 执行边界\n\n• 工具授权\n  allow_all_tools\n• 路径白名单\n  --add-dir / allow_all_paths\n• 工作区隔离 cwd", C_GREEN, 9.6, True)
    box(ax, 4.2, 0.5, 3.5, 3.0, "④ 会话边界\n\n• --session-id 绑定\n• session_id 仅限\n  session-state 直接子目录\n• 拒绝绝对路径 / ../\n  防路径穿越", C_GREEN, 9.6, True)
    box(ax, 8.0, 0.5, 3.5, 3.0, "⑤ 运行保障\n\n• 单次调用超时\n  timeout 3600s\n• 非零码/空输出\n  稳定降级提示\n• doctor 启动前体检", C_GREEN, 9.6, True)

    arrow(ax, (3.2, 7.5), (4.0, 7.55))
    arrow(ax, (7.4, 7.55), (8.2, 7.55), text="否", color="#aa3333")
    arrow(ax, (5.7, 6.9), (5.7, 6.1), text="是")
    arrow(ax, (5.7, 4.6), (5.7, 3.5))
    ax.text(5.9, 3.85, "进入本地执行", fontproperties=FONT, fontsize=9, color="#33404d")
    save(fig, "fig_security.png")


# ---------------- 图4 会话扫描与接管 ----------------
def fig_session():
    fig, ax = plt.subplots(figsize=(9.2, 5.2))
    ax.set_xlim(0, 12); ax.set_ylim(0, 7); ax.axis("off")

    box(ax, 0.5, 2.4, 3.2, 2.2, "~/.copilot/session-state/\n<session_id>/", C_GRAY, 10.5, True)
    box(ax, 0.8, 4.7, 2.6, 0.7, "workspace.yaml", C_BLUE, 9.5)
    box(ax, 0.8, 1.5, 2.6, 0.7, "events.jsonl", C_BLUE, 9.5)
    box(ax, 0.8, 0.6, 2.6, 0.7, "inuse.*.lock", C_BLUE, 9.5)

    box(ax, 4.6, 2.7, 3.2, 1.6, "CopilotSessionInspector\n解析 cwd/model/状态\n最近事件 + 历史摘要", C_GREEN, 10, True)
    box(ax, 8.6, 4.6, 3.0, 1.0, "接管 takeover\n延续上下文", C_ORANGE, 10, True)
    box(ax, 8.6, 3.0, 3.0, 1.0, "历史预览 / 刷新", C_ORANGE, 10, True)
    box(ax, 8.6, 1.4, 3.0, 1.0, "删除 delete\n（仅子目录名）", C_ORANGE, 10, True)

    arrow(ax, (3.7, 4.0), (4.6, 3.7))
    arrow(ax, (3.7, 1.85), (4.6, 3.2))
    arrow(ax, (3.7, 0.95), (4.6, 2.9))
    arrow(ax, (7.8, 3.8), (8.6, 5.0))
    arrow(ax, (7.8, 3.5), (8.6, 3.5))
    arrow(ax, (7.8, 3.2), (8.6, 1.9))
    save(fig, "fig_session.png")


# ---------------- 图5 部署与运行时保障 ----------------
def fig_deploy():
    fig, ax = plt.subplots(figsize=(9.2, 5.0))
    ax.set_xlim(0, 12); ax.set_ylim(0, 7); ax.axis("off")

    ax.add_patch(Rectangle((0.4, 0.4), 11.2, 6.2, fill=False, ec="#9aa7b3", lw=1.2, ls="--"))
    ax.text(0.7, 6.25, "本地主机（已登录 Copilot CLI）", fontproperties=FONTB, fontsize=10, color="#5b6b7a")

    box(ax, 1.0, 3.6, 3.4, 1.8, "topilot 进程\n主线程：长轮询通道\n后台线程：飞书长连接", C_GREEN, 10, True)
    box(ax, 5.4, 4.2, 2.9, 1.2, "Copilot CLI\n子进程", C_ORANGE, 10.5, True)
    box(ax, 9.0, 4.2, 2.4, 1.2, "工作区\nworkspace", C_BLUE, 10.5, True)
    box(ax, 1.0, 1.0, 3.4, 1.3, "看门狗 watchdog.ps1\n进程巡检 + 自动拉起", C_RED, 10, True)
    box(ax, 5.4, 1.0, 6.0, 1.3, "断线恢复：标记 restart → 重建通道 Application\n网络异常仅记录并重连，进程不退出", C_PURPLE, 9.8, True)

    arrow(ax, (4.4, 4.6), (5.4, 4.7), text="argv")
    arrow(ax, (8.3, 4.8), (9.0, 4.8))
    arrow(ax, (2.7, 2.3), (2.7, 3.6), text="保活", color="#aa3333")
    arrow(ax, (2.7, 3.6), (4.6, 2.3), rad=-0.2, color="#7a5cae", ls="--")
    save(fig, "fig_deploy.png")


# ---------------- 图6 模块结构（依赖） ----------------
def fig_module():
    fig, ax = plt.subplots(figsize=(9.4, 6.0))
    ax.set_xlim(0, 12); ax.set_ylim(0, 9); ax.axis("off")

    box(ax, 4.4, 7.6, 3.2, 1.0, "cli/main.py\n入口·init/start/doctor", C_PURPLE, 10, True)
    box(ax, 0.6, 5.6, 3.0, 1.0, "telegram_bot.py\n长轮询通道", C_BLUE, 9.5, True)
    box(ax, 4.5, 5.6, 3.0, 1.0, "feishu_bot.py\n长连接通道", C_BLUE, 9.5, True)
    box(ax, 8.4, 5.6, 3.0, 1.0, "config.py / paths.py\n配置与路径", C_GRAY, 9.5, True)
    box(ax, 4.4, 3.6, 3.2, 1.0, "task_runner.py\n任务编排", C_GREEN, 10, True)
    box(ax, 0.6, 1.4, 3.0, 1.0, "agent.py\nCopilot 调用/解析", C_ORANGE, 9.5, True)
    box(ax, 4.5, 1.4, 3.0, 1.0, "copilot_sessions.py\n会话扫描", C_ORANGE, 9.5, True)
    box(ax, 8.4, 1.4, 3.0, 1.0, "session_store.py\nconversation_store.py", C_ORANGE, 9.2, True)

    arrow(ax, (5.4, 7.6), (3.0, 6.6), rad=0.1)
    arrow(ax, (6.0, 7.6), (6.0, 6.6))
    arrow(ax, (6.6, 7.6), (9.4, 6.6), rad=-0.1)
    arrow(ax, (2.1, 5.6), (4.6, 4.6), rad=-0.1)
    arrow(ax, (6.0, 5.6), (6.0, 4.6))
    arrow(ax, (5.4, 3.6), (2.1, 2.4), rad=0.1)
    arrow(ax, (6.0, 3.6), (6.0, 2.4))
    arrow(ax, (6.6, 3.6), (9.4, 2.4), rad=-0.1)
    save(fig, "fig_module.png")


if __name__ == "__main__":
    fig_arch()
    fig_seq()
    fig_security()
    fig_session()
    fig_deploy()
    fig_module()
    print("ALL DONE")
