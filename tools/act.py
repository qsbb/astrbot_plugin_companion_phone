from __future__ import annotations

from dataclasses import dataclass

from pydantic import Field

from astrbot.core.agent.run_context import ContextWrapper
from astrbot.core.agent.tool import FunctionTool, ToolExecResult
from astrbot.core.astr_agent_context import AstrAgentContext

from ..constants import (
    KEY_NAMES,
    SWIPE_DIRECTIONS,
    TOOL_CLICK_TEXT,
    TOOL_INPUT,
    TOOL_KEY,
    TOOL_SWIPE,
    TOOL_TAP,
)
from .base import _ToolMixin, _bool_arg, _int_arg, _str_arg, _umo


@dataclass
class TapTool(_ToolMixin, FunctionTool[AstrAgentContext]):
    name: str = TOOL_TAP
    description: str = (
        "点按手机屏幕上的一个坐标。坐标必须来自 companion_phone_screen 返回的控件"
        " bounds（取中心点），不要凭空猜测。每次点按后如需确认结果，重新调用 screen。"
    )
    parameters: dict = Field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "x": {"type": "integer", "minimum": 0, "description": "横坐标像素"},
                "y": {"type": "integer", "minimum": 0, "description": "纵坐标像素"},
            },
            "required": ["x", "y"],
            "additionalProperties": False,
        }
    )

    async def call(
        self, context: ContextWrapper[AstrAgentContext], **kwargs
    ) -> ToolExecResult:
        umo = _umo(context)

        async def invoke():
            return await self.service.tap(
                umo, _int_arg(kwargs, "x"), _int_arg(kwargs, "y")
            )

        return await self._run("tap", invoke)


@dataclass
class ClickTextTool(_ToolMixin, FunctionTool[AstrAgentContext]):
    name: str = TOOL_CLICK_TEXT
    description: str = (
        "按可见文本直接点按屏幕上的控件（如按钮文字、菜单项）。"
        "优先使用本工具而不是 tap 坐标；文本必须与屏幕上显示的文字完全一致。"
        "发送、删除、支付类按钮会被安全策略拦截。"
    )
    parameters: dict = Field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 64,
                    "description": "屏幕上控件的完整可见文本",
                }
            },
            "required": ["text"],
            "additionalProperties": False,
        }
    )

    async def call(
        self, context: ContextWrapper[AstrAgentContext], **kwargs
    ) -> ToolExecResult:
        umo = _umo(context)

        async def invoke():
            return await self.service.click_text(umo, _str_arg(kwargs, "text"))

        return await self._run("click_text", invoke)


@dataclass
class InputTextTool(_ToolMixin, FunctionTool[AstrAgentContext]):
    name: str = TOOL_INPUT
    description: str = (
        "向当前获得焦点的输入框输入文本（支持中文）。"
        "通常先 click_text 点开输入框，再调用本工具。clear=true 时先清空原内容。"
    )
    parameters: dict = Field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 500,
                    "description": "要输入的文本",
                },
                "clear": {
                    "type": "boolean",
                    "default": False,
                    "description": "是否先清空输入框",
                },
            },
            "required": ["text"],
            "additionalProperties": False,
        }
    )

    async def call(
        self, context: ContextWrapper[AstrAgentContext], **kwargs
    ) -> ToolExecResult:
        umo = _umo(context)

        async def invoke():
            return await self.service.input_text(
                umo, _str_arg(kwargs, "text"), _bool_arg(kwargs, "clear", False)
            )

        return await self._run("input_text", invoke)


@dataclass
class SwipeTool(_ToolMixin, FunctionTool[AstrAgentContext]):
    name: str = TOOL_SWIPE
    description: str = (
        "滑动屏幕：up=向上滚动浏览内容，down=下拉刷新/回顶部，left/right=左右翻页。"
    )
    parameters: dict = Field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "direction": {
                    "type": "string",
                    "enum": list(SWIPE_DIRECTIONS),
                    "description": "滑动方向",
                },
                "distance": {
                    "type": "integer",
                    "minimum": 100,
                    "maximum": 2000,
                    "default": 600,
                    "description": "滑动像素距离",
                },
            },
            "required": ["direction"],
            "additionalProperties": False,
        }
    )

    async def call(
        self, context: ContextWrapper[AstrAgentContext], **kwargs
    ) -> ToolExecResult:
        umo = _umo(context)

        async def invoke():
            distance = kwargs.get("distance", 600)
            if isinstance(distance, bool) or not isinstance(distance, (int, float)):
                distance = 600
            return await self.service.swipe(
                umo, _str_arg(kwargs, "direction"), int(distance)
            )

        return await self._run("swipe", invoke)


@dataclass
class PressKeyTool(_ToolMixin, FunctionTool[AstrAgentContext]):
    name: str = TOOL_KEY
    description: str = (
        "按手机按键：back=返回上一页，home=回桌面，recents=最近任务，"
        "enter=确认/换行，del=删除光标前字符，power=电源键，"
        "volume_up/volume_down=音量加减。"
    )
    parameters: dict = Field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "key": {
                    "type": "string",
                    "enum": list(KEY_NAMES),
                    "description": "按键名",
                }
            },
            "required": ["key"],
            "additionalProperties": False,
        }
    )

    async def call(
        self, context: ContextWrapper[AstrAgentContext], **kwargs
    ) -> ToolExecResult:
        umo = _umo(context)

        async def invoke():
            return await self.service.press_key(umo, _str_arg(kwargs, "key"))

        return await self._run("press_key", invoke)
