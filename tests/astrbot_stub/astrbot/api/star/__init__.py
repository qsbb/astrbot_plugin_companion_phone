from pathlib import Path


class AstrMessageEvent:
    """形状镜像 astrbot.api.event.AstrMessageEvent（测试用最小实现）。"""

    def __init__(self, unified_msg_origin: str = "test:private:u1") -> None:
        self.unified_msg_origin = unified_msg_origin
        self.message_str = ""


class Context:
    """测试用 Context：记录 LLM 工具注册/注销调用。"""

    def __init__(self) -> None:
        self.registered_tools: list = []
        self.unregistered_tools: list[str] = []

    def add_llm_tools(self, *tools) -> None:
        self.registered_tools.extend(tools)

    def unregister_llm_tool(self, name: str) -> None:
        self.unregistered_tools.append(name)


class Star:
    def __init__(self, context: Context) -> None:
        self.context = context


class StarTools:
    @classmethod
    def get_data_dir(cls, plugin_name: str | None = None) -> Path:
        return Path("plugin_data") / (plugin_name or "")


def register(name: str, author: str, desc: str, version: str, repo: str = ""):
    def deco(cls):
        cls._nx_register_meta = {
            "name": name,
            "author": author,
            "desc": desc,
            "version": version,
            "repo": repo,
        }
        return cls

    return deco
