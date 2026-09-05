"""形状镜像 astrbot.api.event.filter：装饰器把元数据附加到 handler 函数。

_offline_registry 供离线测试断言注册行为；真实宿主不加载本模块。
command_group 返回的函数附带 .command()/.group()，支持
`@group.command("x")` 的真实框架用法。
"""

from __future__ import annotations

from typing import Callable

_offline_registry: list[dict] = []


class PermissionType:
    ADMIN = "admin"


class EventMessageType:
    ALL = "all"
    GROUP_MESSAGE = "group"
    PRIVATE_MESSAGE = "private"


def _tag(fn: Callable, meta: dict) -> Callable:
    existing = dict(getattr(fn, "_nx_meta", {}))
    existing.update(meta)
    setattr(fn, "_nx_meta", existing)
    _offline_registry.append({"function": fn, **existing})
    return fn


def command(name: str, alias=None, priority: int = 0):
    def deco(fn: Callable) -> Callable:
        return _tag(fn, {"kind": "command", "name": name, "alias": tuple(alias or ())})

    return deco


def command_group(name: str, priority: int = 0):
    def deco(fn: Callable) -> Callable:
        def command(sub_name: str, alias=None, priority: int = 0):
            def d(sub_fn: Callable) -> Callable:
                return _tag(
                    sub_fn,
                    {
                        "kind": "command",
                        "group": name,
                        "name": sub_name,
                        "alias": tuple(alias or ()),
                    },
                )

            return d

        def group(sub_name: str):
            return command_group(sub_name)

        fn.command = command  # type: ignore[attr-defined]
        fn.group = group  # type: ignore[attr-defined]
        return _tag(fn, {"kind": "command_group", "name": name})

    return deco


def permission_type(permission_type: str):
    def deco(fn: Callable) -> Callable:
        return _tag(fn, {"permission": permission_type})

    return deco


def event_message_type(message_type: str):
    def deco(fn: Callable) -> Callable:
        return _tag(fn, {"kind": "event_message_type", "message_type": message_type})

    return deco


def on_astrbot_loaded():
    def deco(fn: Callable) -> Callable:
        return _tag(fn, {"kind": "hook", "hook": "on_astrbot_loaded"})

    return deco


def on_llm_request():
    def deco(fn: Callable) -> Callable:
        return _tag(fn, {"kind": "hook", "hook": "on_llm_request"})

    return deco


def on_llm_response():
    def deco(fn: Callable) -> Callable:
        return _tag(fn, {"kind": "hook", "hook": "on_llm_response"})

    return deco


def on_decorating_result():
    def deco(fn: Callable) -> Callable:
        return _tag(fn, {"kind": "hook", "hook": "on_decorating_result"})

    return deco


def platform_adapter_type(*types):
    def deco(fn: Callable) -> Callable:
        return _tag(fn, {"kind": "platform_adapter_type", "types": types})

    return deco
