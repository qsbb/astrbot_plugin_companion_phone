"""形状镜像 mcp.types（AstrBot 依赖的 MCP SDK）：工具结果内容块的最小子集。"""


class TextContent:
    def __init__(self, type: str, text: str) -> None:
        self.type = type
        self.text = text


class ImageContent:
    def __init__(self, type: str, data: str, mimeType: str) -> None:
        self.type = type
        self.data = data
        self.mimeType = mimeType


class CallToolResult:
    def __init__(self, content: list, isError: bool = False) -> None:
        self.content = content
        self.isError = isError
