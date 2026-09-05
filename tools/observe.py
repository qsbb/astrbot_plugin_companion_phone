from __future__ import annotations

from pydantic import Field
from pydantic.dataclasses import dataclass

from astrbot.core.agent.run_context import ContextWrapper
from astrbot.core.agent.tool import FunctionTool, ToolExecResult
from astrbot.core.astr_agent_context import AstrAgentContext

from ..constants import TOOL_SCREEN, TOOL_STATUS
from .base import _ToolMixin, _umo


@dataclass
class StatusTool(_ToolMixin, FunctionTool[AstrAgentContext]):
    """只读：设备状态。"""

    name: str = TOOL_STATUS
    description: str = (
        "查看手机当前状态：是否在线、当前前台应用。"
        "在执行任何手机操作前、或用户询问手机状态时调用。纯只读，无副作用。"
    )
    parameters: dict = Field(
        default_factory=lambda: {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        }
    )

    async def call(
        self, context: ContextWrapper[AstrAgentContext], **kwargs
    ) -> ToolExecResult:
        # 回归锚（第二轮盲测 P1）：_call 需要 (context, action, coro_factory) 三个实参
        return await self._call(context, "status", lambda: self.service.status())


@dataclass
class ScreenTool(_ToolMixin, FunctionTool[AstrAgentContext]):
    """只读：模型的“眼睛”。"""

    name: str = TOOL_SCREEN
    description: str = (
        "读取手机当前屏幕：返回前台应用、屏幕尺寸和可见控件列表"
        "（文本/描述/坐标/可点击性）。需要知道手机上现在显示什么、"
        "找按钮或输入框位置时必须先调用本工具。"
    )
    parameters: dict = Field(
        default_factory=lambda: {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        }
    )

    async def call(
        self, context: ContextWrapper[AstrAgentContext], **kwargs
    ) -> ToolExecResult:
        umo = _umo(context)
        return await self._call(context, "screen", lambda: self.service.screen(umo))
