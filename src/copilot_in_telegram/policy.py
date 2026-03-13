from __future__ import annotations

from copilot_in_telegram.models import EventType, NotificationEvent


class NotificationPolicy:
    """Only pushes state changes and concise summaries, never raw streaming logs."""

    def render(self, event: NotificationEvent) -> str | None:
        task = event.task
        if event.event_type is EventType.ACCEPTED:
            return f"已接收任务 {task.id}\n内容: {task.instruction}\n当前状态: 已进入队列"
        if event.event_type is EventType.APPROVAL_REQUIRED:
            return (
                f"任务 {task.id} 需要确认后执行\n"
                f"摘要: {task.summary}\n"
                f"计划执行: {task.command or task.url or '待确认动作'}\n"
                f"回复 /approve {task.id} 继续，或 /deny {task.id} 拒绝"
            )
        if event.event_type is EventType.STARTED:
            return f"任务 {task.id} 开始执行\n摘要: {task.summary}"
        if event.event_type is EventType.MILESTONE:
            return f"任务 {task.id} 进展\n{event.detail}"
        if event.event_type is EventType.COMPLETED:
            return f"任务 {task.id} 已完成\n结果: {task.result_summary}"
        if event.event_type is EventType.FAILED:
            return f"任务 {task.id} 执行失败\n原因: {task.result_summary}"
        if event.event_type is EventType.REJECTED:
            return f"任务 {task.id} 已拒绝\n摘要: {task.summary or task.instruction}"
        return None
