from typing import Any, Generic, TypeVar

from pydantic import Field
from pydantic.dataclasses import dataclass

T = TypeVar("T")

ToolExecResult = str | Any


@dataclass
class ToolSchema:
    name: str = ""
    description: str = ""
    parameters: dict = Field(default_factory=dict)


@dataclass
class FunctionTool(ToolSchema, Generic[T]):
    """形状镜像官方 astrbot.core.agent.tool.FunctionTool（pydantic dataclass）。"""


class ToolSet:
    def __init__(self, tools: list | None = None) -> None:
        self.tools = list(tools or [])
