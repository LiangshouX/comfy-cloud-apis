"""通用异步任务轮询器。

三家云的异步模型长得不一样，但骨架完全一致：

    创建任务 -> 拿到 task_id -> 轮询直到终态 -> 从终态里取成片 URL

把这段抽出来，provider 只需要回答三个问题：
    status_of(payload)   -> 当前状态字符串
    is_success(status)   -> 是否成功
    is_failed(status)    -> 是否失败
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Callable, Optional

# 统一的终态词表（provider 负责把自己的状态映射到这套词表）
PENDING = "pending"
RUNNING = "running"
SUCCEEDED = "succeeded"
FAILED = "failed"
CANCELLED = "cancelled"
EXPIRED = "expired"
UNKNOWN = "unknown"


def normalize_status(raw: Optional[str]) -> str:
    """把各家的状态写法归一。"""
    s = (raw or "").strip().lower()
    if not s:
        return UNKNOWN
    if s in {"success", "succeeded", "ok", "done", "completed", "complete"}:
        return SUCCEEDED
    if s in {"fail", "failed", "failure", "error"}:
        return FAILED
    if s in {"cancel", "cancelled", "canceled"}:
        return CANCELLED
    if s in {"expired", "timeout"}:
        return EXPIRED
    if s in {"pending", "queued", "queueing", "submitted"}:
        return PENDING
    if s in {"running", "processing", "in_progress", "executing"}:
        return RUNNING
    return UNKNOWN


async def poll_until_done(
    fetch: Callable[[], Any],
    status_of: Callable[[Any], str],
    *,
    poll_interval: int = 15,
    max_wait: int = 900,
    on_tick: Optional[Callable[[str, Any], None]] = None,
) -> Any:
    """反复调用 fetch() 直到成功/失败/取消/过期。

    fetch 是一个**无参 async 函数**，返回该家的任务查询响应。
    返回最后一次响应；失败时抛 RuntimeError（携带状态与原始响应）。
    """
    deadline = time.monotonic() + float(max_wait)
    last: Any = None
    while time.monotonic() < deadline:
        await asyncio.sleep(poll_interval)
        last = await fetch()
        raw_status = status_of(last)
        if on_tick:
            on_tick(raw_status, last)
        if raw_status == SUCCEEDED:
            return last
        if raw_status in {FAILED, CANCELLED, EXPIRED}:
            raise RuntimeError(f"任务失败：status={raw_status}\n原始响应：{last}")
    raise TimeoutError(f"本地等待超过 {max_wait}s，任务可能仍在云端执行（请用任务查询节点续查，勿重复提交）")
