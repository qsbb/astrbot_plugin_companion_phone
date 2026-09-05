from __future__ import annotations

from astrbot.core.agent.tool import FunctionTool

from ..service import PhoneService
from .act import ClickTextTool, InputTextTool, PressKeyTool, SwipeTool, TapTool
from .apps import LaunchAppTool, WaitTool
from .observe import ScreenTool, StatusTool

_TOOL_CLASSES = (
    StatusTool,
    ScreenTool,
    TapTool,
    ClickTextTool,
    InputTextTool,
    SwipeTool,
    PressKeyTool,
    LaunchAppTool,
    WaitTool,
)

__all__ = [
    "create_device_tools",
    "StatusTool",
    "ScreenTool",
    "TapTool",
    "ClickTextTool",
    "InputTextTool",
    "SwipeTool",
    "PressKeyTool",
    "LaunchAppTool",
    "WaitTool",
]


def create_device_tools(service: PhoneService) -> list[FunctionTool]:
    tools: list[FunctionTool] = []
    for cls in _TOOL_CLASSES:
        tool = cls()
        # dataclass 字段之外的运行时引用，绕过 __setattr__ 限制
        object.__setattr__(tool, "service", service)
        tools.append(tool)
    return tools
