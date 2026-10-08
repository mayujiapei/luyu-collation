"""简易内存限流：30 req/min/IP（TECH_DESIGN §4）。

只保护会打大模型的 /collate；/health 不限流，否则演示前的冒烟检查可能被自己挡掉。
进程内计数，多 worker 部署时按 worker 各自计数 —— 阶段一无状态、单进程，够用。
"""

from __future__ import annotations

import threading
import time
from collections import deque

from .errors import RATE_LIMITED, ApiError

WINDOW_S = 60.0
MAX_REQUESTS = 30
# 桶数量超过该阈值时顺手清理过期桶，避免长期运行内存只增不减
_SWEEP_THRESHOLD = 512

_buckets: dict[str, deque[float]] = {}
_lock = threading.Lock()


def _sweep(cutoff: float) -> None:
    """清掉窗口内已无请求的桶（调用方需持有 _lock）。"""
    stale = [key for key, bucket in _buckets.items() if not bucket or bucket[-1] < cutoff]
    for key in stale:
        del _buckets[key]


def reset() -> None:
    """清空计数。仅供测试使用（生产代码路径不得调用）。"""
    with _lock:
        _buckets.clear()


def check_rate_limit(client_key: str) -> None:
    """登记一次请求；超出配额抛 ApiError(RATE_LIMITED)。"""
    now = time.monotonic()
    cutoff = now - WINDOW_S
    with _lock:
        bucket = _buckets.get(client_key)
        if bucket is None:
            bucket = deque()
            _buckets[client_key] = bucket
        while bucket and bucket[0] < cutoff:
            bucket.popleft()
        if len(bucket) >= MAX_REQUESTS:
            retry_after = max(1, int(WINDOW_S - (now - bucket[0])) + 1)
            raise ApiError(RATE_LIMITED, f"请求过于频繁，请约 {retry_after} 秒后重试")
        bucket.append(now)
        if len(_buckets) > _SWEEP_THRESHOLD:
            _sweep(cutoff)
