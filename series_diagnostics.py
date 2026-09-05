from __future__ import annotations

import threading
import uuid
from collections import deque
from datetime import UTC, datetime
from typing import Any

from .constants import PLUGIN_ID, PLUGIN_NAME

# 规范 5.1：环形缓冲上限与 limit 上限
_MAX_EVENTS = 1000
_REDACT_KEY_PARTS = (
    "token",
    "api_key",
    "secret",
    "password",
    "authorization",
    "cookie",
    "jwt",
    "private_key",
    "ssh_key",
    "provider_key",
    "bridge_key",
)
_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR")

_events: deque[dict[str, Any]] = deque(maxlen=_MAX_EVENTS)
_dropped_before = 0
_stream_id = str(uuid.uuid4())
_lock = threading.Lock()


def _redact(value: Any) -> Any:
    """规范 5.1 脱敏哲学：保留排障数据，只隐藏凭据值，结构保留。"""
    if isinstance(value, dict):
        return {
            k: (
                "<已隐藏>"
                if any(p in k.lower() for p in _REDACT_KEY_PARTS)
                else _redact(v)
            )
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [_redact(v) for v in value]
    return value


def diagnostic_event(
    code: str,
    summary: str,
    *,
    level: str = "INFO",
    details: dict[str, Any] | None = None,
) -> None:
    """记录一条诊断事件；不向 AstrBot 核心日志传播（astrbot_log_propagation=False）。"""
    if level not in _LEVELS:
        level = "INFO"
    with _lock:
        global _dropped_before
        if len(_events) == _events.maxlen:
            _dropped_before += 1
        _events.append(
            {
                "seq": (_events[-1]["seq"] + 1) if _events else 1,
                "timestamp": datetime.now(UTC).isoformat(timespec="seconds"),
                "plugin_id": PLUGIN_ID,
                "plugin_name": PLUGIN_NAME,
                "level": level,
                "code": code[:80],
                "summary": summary,
                "details": _redact(details or {}),
            }
        )


def diagnostic_events(after_seq: int = 0, limit: int = 200) -> dict[str, Any]:
    """游标续读；stream_id 变化表示插件重启，调用方必须重置游标。"""
    limit = max(1, min(int(limit), _MAX_EVENTS))
    with _lock:
        selected = [e for e in _events if e["seq"] > after_seq][:limit]
        next_seq = selected[-1]["seq"] if selected else after_seq
        return {
            "events": selected,
            "next_seq": next_seq,
            "dropped_before": _dropped_before,
            "stream_id": _stream_id,
        }


def diagnostic_clear() -> None:
    with _lock:
        global _dropped_before
        _events.clear()
        _dropped_before = 0
