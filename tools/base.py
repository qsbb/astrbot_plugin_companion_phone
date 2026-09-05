from __future__ import annotations

import json
from typing import Any, Awaitable, Callable

from ..constants import E_INVALID_ARGUMENT, E_INTERNAL
from ..errors import PhoneError
from ..log import logger


class _ToolMixin:
    """工具公共逻辑：service 注入、结果 JSON 化、异常映射。"""

    service: Any  # 由 create_device_tools 通过 object.__setattr__ 注入

    async def _run(
        self, action: str, coro_factory: Callable[[], Awaitable[Any]]
    ) -> str:
        try:
            return _json(await coro_factory())
        except PhoneError as exc:
            return _json(exc.public_dict(action))
        except (TypeError, ValueError):
            return _json(
                PhoneError(E_INVALID_ARGUMENT, "工具参数格式无效").public_dict(action)
            )
        except Exception:
            logger.exception("companion_phone 工具内部错误")
            return _json(
                PhoneError(E_INTERNAL, "内部错误，请管理员查看日志").public_dict(action)
            )


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
