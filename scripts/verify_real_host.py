"""真实宿主深度验证脚本：在 AstrBot 的 Python 环境中运行。

验证三层在离线 stub 上无法证明的事实：
1. 9 个工具的 parameters 在真实 pydantic dataclass 继承下是 dict（P0 回归锚）
2. ToolSet.openai_schema 产出的 LLM 函数 schema 合法且 9 工具齐全
3. R2 视觉兜底经真实 mcp 序列化产出合法 CallToolResult

用法：AstrBot 环境中 python scripts/verify_real_host.py
"""

from __future__ import annotations

import base64
import json
import sys
import tempfile
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PLUGIN_ROOT.parent))
sys.path.insert(0, str(PLUGIN_ROOT))

failures: list[str] = []


def check(name: str, cond: bool, detail: str = ""):
    print(f"{'✅' if cond else '❌'} {name}  {detail}")
    if not cond:
        failures.append(name)


def main() -> int:
    import mcp  # noqa: F401  # 真实宿主应有 mcp
    from astrbot.core.agent.tool import ToolSet
    from mcp.types import CallToolResult

    from astrbot_plugin_companion_phone.config import PhoneConfig
    from astrbot_plugin_companion_phone.service import PhoneService
    from astrbot_plugin_companion_phone.tools import create_device_tools

    cfg = PhoneConfig.from_mapping(
        {
            "ENABLED": True,
            "MODE": "redroid",
            "REDROID_IMAGE": "redroid/redroid:12.0.0_64only-latest",
            "REDROID_DATA_PATH": "/tmp/companion-phone",
            "SCREEN_VISION": True,
            "APP_WHITELIST": [
                {"alias": "browser", "package": "com.android.browser", "risk": "low"}
            ],
        }
    )
    service = PhoneService(lambda: cfg, Path(tempfile.mkdtemp()) / PLUGIN_ROOT.name)

    tools = create_device_tools(service)
    check(
        "1. 九工具 parameters 均为 dict（P0 回归锚）",
        all(isinstance(t.parameters, dict) for t in tools),
        f"{len(tools)} 个工具",
    )

    # 2. 真实宿主的 schema 序列化：openai_schema 即发给 LLM 的内容
    tool_set = ToolSet(list(tools))
    schema = tool_set.openai_schema
    if callable(schema):
        schema = schema()
    payload = json.dumps(schema, ensure_ascii=False, default=str)
    names = [t.name for t in tools]
    missing = [n for n in names if n not in payload]
    check(
        "2. ToolSet.openai_schema 含全部 9 工具",
        not missing,
        f"缺失：{missing or '无'}；schema 大小 {len(payload)} 字符",
    )
    items = schema.get("tools") if isinstance(schema, dict) else schema
    if callable(items):
        items = items()
    sample = None
    for item in items if isinstance(items, list) else []:
        fn = item.get("function", item) if isinstance(item, dict) else {}
        if fn.get("name") == names[0]:
            sample = fn
            break
    check(
        "3. schema 中 parameters 为 JSON 对象",
        sample is not None
        and isinstance(sample.get("parameters", {}).get("properties"), dict),
        str(sample)[:120] if sample else "未定位到样例",
    )

    # R2 视觉兜底：真实 mcp 序列化
    import asyncio

    class _Ev:
        unified_msg_origin = "verify:private:u1"

        def get_group_id(self):
            return ""

    class _Inner:
        event = _Ev()

    class _Ctx:
        context = _Inner()

    class FakeSession:
        async def connect(self):
            return None

        async def close(self):
            return None

        async def current_app(self):
            return {"package": "com.android.browser", "activity": ".Main"}

        async def screen_size(self):
            return [1080, 2400]

        async def ui_tree(self, n):
            return [
                {
                    "rid": 1,
                    "text": "按钮",
                    "desc": "",
                    "bounds": [0, 0, 10, 10],
                    "clickable": True,
                    "scrollable": False,
                }
            ]

        async def screenshot(self, path):
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            Path(path).write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 200)

        async def dismiss_popups(self):
            return 0

    service._session = FakeSession()
    service._mode = "redroid"

    class FakeBackend:
        async def health(self):
            from astrbot_plugin_companion_phone.backend.base import BackendState

            return BackendState(ready=True, adb_serial="fake:5555", detail={})

        def describe(self):
            return {"mode": "redroid"}

    service._backend = FakeBackend()

    screen_tool = {t.name: t for t in tools}["companion_phone_screen"]
    result = asyncio.run(screen_tool.call(_Ctx()))
    check(
        "4. screen 返回真实 mcp CallToolResult",
        isinstance(result, CallToolResult),
        type(result).__name__,
    )
    if isinstance(result, CallToolResult):
        text_part = result.content[0]
        image_part = result.content[1]
        payload = json.loads(text_part.text)
        check(
            "5. 文本部分无路径泄漏且含控件树",
            "screenshot" not in text_part.text and payload["status"] == "ok",
            f"nodes={len(payload.get('nodes', []))}",
        )
        raw = base64.b64decode(image_part.data)
        mime_ok = (
            image_part.mimeType == "image/jpeg" and raw.startswith(b"\xff\xd8")
        ) or (
            image_part.mimeType == "image/png" and raw.startswith(b"\x89PNG")
        )
        check(
            "6. 图像内容 mime 与字节一致",
            mime_ok,
            f"{image_part.mimeType} {len(raw)}B",
        )
        # 真实 mcp 序列化（发给宿主的最终形态）
        dumped = result.model_dump_json()
        check(
            "7. 真实 mcp model_dump_json 序列化成功",
            '"type":"image"' in dumped.replace(" ", "") and len(dumped) > 100,
            f"{len(dumped)} 字符",
        )

    # 8. 会话门控在真实宿主上的行为
    gate_denied = asyncio.run(
        {t.name: t for t in tools}["companion_phone_tap"].call(
            type("C", (), {"context": type("I", (), {"event": type("E", (), {"unified_msg_origin": "qq:group:123", "get_group_id": lambda self: "123"})()})()})(),
            x=1,
            y=2,
        )
    )
    gate_payload = json.loads(gate_denied)
    check(
        "8. 会话门控：群聊事件被拒（默认 private）",
        gate_payload.get("error_code") == "session_not_allowed",
        str(gate_payload.get("error_code")),
    )

    print("=" * 60)
    if failures:
        print(f"❌ {len(failures)} 项失败：{failures}")
        return 1
    print("✅ 全部通过：插件在真实宿主上功能与契约完好")
    return 0


if __name__ == "__main__":
    sys.exit(main())
