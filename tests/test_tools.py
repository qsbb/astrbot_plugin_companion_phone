from __future__ import annotations

import asyncio
import json

from astrbot_plugin_companion_phone.constants import TOOL_NAMES
from astrbot_plugin_companion_phone.tools import create_device_tools


class StubService:
    """行为镜像 PhoneService 的最小替身；check_session_allowed 模拟 private 策略。"""

    scope = "private"
    vision = False

    async def status(self):
        return {"status": "ok", "action": "status"}

    async def screen(self, umo=""):
        return {
            "status": "ok",
            "action": "screen",
            "nodes": [],
            "screenshot_path": "/tmp/shot.png",
        }

    def screen_vision_enabled(self):
        return self.vision

    def load_screenshot(self, path):
        return b"fake-jpeg-bytes"

    async def tap(self, umo, x, y):
        return {"status": "ok", "action": "tap", "xy": [x, y]}

    async def click_text(self, umo, text):
        return {"status": "ok", "action": "click_text", "text": text}

    async def input_text(self, umo, text, clear):
        return {"status": "ok", "action": "input_text"}

    async def swipe(self, umo, direction, distance):
        return {"status": "ok", "action": "swipe"}

    async def press_key(self, umo, key):
        return {"status": "ok", "action": "press_key", "key": key}

    async def launch_app(self, umo, alias):
        return {"status": "ok", "action": "launch_app", "alias": alias}

    async def wait_element(self, umo, text, timeout_s):
        return {"status": "ok", "found": True}

    def check_session_allowed(self, event):
        try:
            if bool(event.get_group_id()) and self.scope == "private":
                return {"status": "error", "error_code": "session_not_allowed"}
        except Exception:
            pass
        return None


class _Ev:
    def __init__(self, group_id=""):
        self.unified_msg_origin = (
            f"test:{'group' if group_id else 'private'}:{group_id or 'u1'}"
        )
        self._group_id = group_id

    def get_group_id(self):
        return self._group_id


class _Inner:
    def __init__(self, event):
        self.event = event


class Ctx:
    def __init__(self, event):
        self.context = _Inner(event)


def make_tools():
    return {t.name: t for t in create_device_tools(StubService())}


def test_tool_schemas_are_plain_dicts():
    """F-01 回归锚：stdlib dataclass 叠加 pydantic dataclass 会把 parameters
    变成 FieldInfo 对象；本断言在离线 stub 与真实宿主上都必须通过。"""
    for tool in create_device_tools(StubService()):
        assert isinstance(tool.parameters, dict), (
            f"{tool.name}.parameters 不是 dict——工具 schema 在真实宿主上会损坏"
        )
        assert tool.description
    assert [t.name for t in create_device_tools(StubService())] == list(TOOL_NAMES)


def test_tools_constructible_without_positional_args():
    # _ToolMixin.service 必须是带默认值的字段，否则真实宿主插件加载即 TypeError
    for tool in create_device_tools(StubService()):
        assert tool.service is not None


def test_tap_roundtrip_and_validation():
    tools = make_tools()
    result = json.loads(
        asyncio.run(tools["companion_phone_tap"].call(Ctx(_Ev()), x=1, y=2))
    )
    assert result["xy"] == [1, 2]

    for kwargs in ({"x": 1}, {"y": 2}, {"x": 1.9, "y": 2}, {"x": True, "y": 2}):
        result = json.loads(
            asyncio.run(tools["companion_phone_tap"].call(Ctx(_Ev()), **kwargs))
        )
        assert result["status"] == "error"
        assert result["error_code"] == "invalid_argument"


def test_screen_passes_umo():
    seen = {}

    class Spy(StubService):
        async def screen(self, umo=""):
            seen["umo"] = umo
            return {"status": "ok"}

    tools = {t.name: t for t in create_device_tools(Spy())}
    asyncio.run(tools["companion_phone_screen"].call(Ctx(_Ev())))
    assert seen["umo"] == "test:private:u1"


def test_screen_vision_disabled_returns_json_without_path():
    """R2 回归锚：视觉关闭时纯 JSON，且截图路径不进入模型可见文本。"""
    tools = make_tools()
    raw = asyncio.run(tools["companion_phone_screen"].call(Ctx(_Ev())))
    assert isinstance(raw, str)
    payload = json.loads(raw)
    assert payload["status"] == "ok"
    assert "screenshot_path" not in raw


def test_screen_vision_enabled_returns_mcp_image():
    """R2 回归锚：视觉开启时返回 CallToolResult，文本+图像双内容，路径不入文本。"""
    import base64

    from mcp.types import CallToolResult

    class VisionService(StubService):
        vision = True

    tools = {t.name: t for t in create_device_tools(VisionService())}
    result = asyncio.run(tools["companion_phone_screen"].call(Ctx(_Ev())))
    assert isinstance(result, CallToolResult)
    assert len(result.content) == 2
    text_part, image_part = result.content
    payload = json.loads(text_part.text)
    assert payload["status"] == "ok"
    assert "screenshot_path" not in text_part.text
    assert image_part.mimeType == "image/jpeg"
    assert base64.b64decode(image_part.data) == b"fake-jpeg-bytes"


def test_session_gate_private_mode():
    tools = make_tools()
    result = json.loads(
        asyncio.run(tools["companion_phone_tap"].call(Ctx(_Ev("123")), x=1, y=2))
    )
    assert result["status"] == "error"
    assert result["error_code"] == "session_not_allowed"
    # 私聊放行
    result = json.loads(
        asyncio.run(tools["companion_phone_tap"].call(Ctx(_Ev()), x=1, y=2))
    )
    assert result["status"] == "ok"


def test_session_gate_all_mode():
    class AllService(StubService):
        scope = "all"

    tools = {t.name: t for t in create_device_tools(AllService())}
    result = json.loads(
        asyncio.run(tools["companion_phone_tap"].call(Ctx(_Ev("123")), x=1, y=2))
    )
    assert result["status"] == "ok"


def test_all_nine_tools_call_paths():
    """第二轮盲测 P1 回归锚：9 个工具的 call() 必须全部可成功调用，
    防止 _call 实参错位类缺陷（status 工具曾因此 100% 崩溃而测试全绿）。"""
    tools = make_tools()
    cases = {
        "companion_phone_status": {},
        "companion_phone_screen": {},
        "companion_phone_tap": {"x": 1, "y": 2},
        "companion_phone_click_text": {"text": "搜索"},
        "companion_phone_input_text": {"text": "hi"},
        "companion_phone_swipe": {"direction": "up"},
        "companion_phone_press_key": {"key": "back"},
        "companion_phone_launch_app": {"alias": "wechat"},
        "companion_phone_wait_element": {"text": "搜索"},
    }
    assert set(cases) == set(TOOL_NAMES)
    for name, kwargs in cases.items():
        result = json.loads(asyncio.run(tools[name].call(Ctx(_Ev()), **kwargs)))
        assert result["status"] == "ok", f"{name} call 失败: {result}"


def test_launch_tool_roundtrip():
    tools = make_tools()
    result = json.loads(
        asyncio.run(
            tools["companion_phone_launch_app"].call(Ctx(_Ev()), alias="wechat")
        )
    )
    assert result["alias"] == "wechat"
