from __future__ import annotations

import json
from typing import Any, Awaitable, Callable

from ..constants import E_INVALID_ARGUMENT, E_INTERNAL
from ..errors import PhoneError
from ..log import logger


class _ToolMixin:
    """工具公共逻辑：service 注入、会话门控、结果 JSON 化、异常映射。

    注意：service 不能声明为 dataclass 字段——pydantic dataclass 不收集
    普通 mixin 的注解（实测会静默丢弃），这里用类属性默认值 +
    create_device_tools 的 object.__setattr__ 实例注入。
    """

    service = None  # 由 create_device_tools 通过 object.__setattr__ 注入

    def _session_guard(self, context: Any) -> str | None:
        """会话门控（FIX_PLAN WP1）：不通过的会话直接返回错误 JSON。

        取不到事件上下文时放行（离线测试/非消息调用路径）。
        """
        service = self.service
        if service is None:
            return None
        try:
            event = context.context.event
        except Exception:
            return None
        verdict = service.check_session_allowed(event)
        if verdict is None:
            return None
        return _json(verdict)

    async def _call(
        self,
        context: Any,
        action: str,
        coro_factory: Callable[[], Awaitable[Any]],
        formatter: Callable[[Any], Any] | None = None,
    ) -> Any:
        guard = self._session_guard(context)
        if guard is not None:
            return guard
        try:
            payload = await coro_factory()
            return formatter(payload) if formatter else _json(payload)
        except PhoneError as exc:
            return _json(exc.public_dict(action))
        except (TypeError, ValueError):
            return _json(
                PhoneError(E_INVALID_ARGUMENT, "工具参数格式无效").public_dict(action)
            )
        except Exception:
            logger.exception("[companion-phone] tool internal error")
            return _json(
                PhoneError(E_INTERNAL, "内部错误，请管理员查看日志").public_dict(action)
            )

    async def _run(
        self, action: str, coro_factory: Callable[[], Awaitable[Any]]
    ) -> str:
        return await self._call(None, action, coro_factory)


def _json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _umo(context: Any) -> str:
    """从 ContextWrapper 取 unified_msg_origin；取不到返回空串（只读工具兜底）。"""
    try:
        return context.context.event.unified_msg_origin
    except Exception:
        return ""


def _int_arg(kwargs: dict, name: str) -> int:
    value = kwargs.get(name)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PhoneError(E_INVALID_ARGUMENT, f"参数 {name} 缺失或不是数字")
    if isinstance(value, float) and not value.is_integer():
        raise PhoneError(E_INVALID_ARGUMENT, f"参数 {name} 必须是整数")
    return int(value)


def _str_arg(kwargs: dict, name: str) -> str:
    value = kwargs.get(name)
    if not isinstance(value, str) or not value.strip():
        raise PhoneError(E_INVALID_ARGUMENT, f"参数 {name} 缺失或为空")
    return value


def _bool_arg(kwargs: dict, name: str, default: bool = False) -> bool:
    value = kwargs.get(name, default)
    if not isinstance(value, bool):
        raise PhoneError(E_INVALID_ARGUMENT, f"参数 {name} 不是布尔值")
    return value
