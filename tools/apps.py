from __future__ import annotations

from pydantic import Field
from pydantic.dataclasses import dataclass

from astrbot.core.agent.run_context import ContextWrapper
from astrbot.core.agent.tool import FunctionTool, ToolExecResult
from astrbot.core.astr_agent_context import AstrAgentContext

from ..constants import TOOL_LAUNCH, TOOL_WAIT
from .base import _ToolMixin, _str_arg, _umo


@dataclass
class LaunchAppTool(_ToolMixin, FunctionTool[AstrAgentContext]):
    name: str = TOOL_LAUNCH
    description: str = (
        "打开手机上的一个应用。只能使用别名，可用别名以工具返回的错误提示与管理员"
        "白名单为准。不要猜测别名；可以先调用 screen 看桌面。"
    )
    parameters: dict = Field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "alias": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 32,
                    "description": "应用别名，如 wechat",
                }
            },
            "required": ["alias"],
            "additionalProperties": False,
        }
    )

    async def call(
        self, context: ContextWrapper[AstrAgentContext], **kwargs
    ) -> ToolExecResult:
        umo = _umo(context)

        async def invoke():
            return await self.service.launch_app(umo, _str_arg(kwargs, "alias"))

        return await self._call(context, "launch_app", invoke)


@dataclass
class WaitTool(_ToolMixin, FunctionTool[AstrAgentContext]):
    name: str = TOOL_WAIT
    description: str = (
        "等待屏幕上出现指定文本的控件（页面加载、跳转动画）。"
        "点按后预期页面未就绪时先等待，不要立刻重复点按。"
    )
    parameters: dict = Field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 64,
                    "description": "要等待出现的文本",
                },
                "timeout_seconds": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 30,
                    "default": 5,
                    "description": "最长等待秒数",
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
            timeout = kwargs.get("timeout_seconds", 5)
            if isinstance(timeout, bool) or not isinstance(timeout, (int, float)):
                timeout = 5
            return await self.service.wait_element(
                umo, _str_arg(kwargs, "text"), int(timeout)
            )

        return await self._call(context, "wait_element", invoke)
