from . import filter  # noqa: F401


class AstrMessageEvent:
    """形状镜像 astrbot.api.event.AstrMessageEvent（测试用最小实现）。"""

    def __init__(self, unified_msg_origin: str = "test:private:u1") -> None:
        self.unified_msg_origin = unified_msg_origin
        self.message_str = ""
