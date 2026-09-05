from __future__ import annotations

import asyncio
import json

import pytest

pytest.importorskip("astrbot")  # 工具层依赖 AstrBot 运行时类型，离线环境跳过

from astrbot_plugin_companion_phone.constants import TOOL_NAMES  # noqa: E402
from astrbot_plugin_companion_phone.tools import create_device_tools  # noqa: E402


class StubService:
    async def status(self):
        return {"status": "ok", "action": "status"}

    async def screen(self):
        return {"status": "ok", "action": "screen", "nodes": []}

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


class _Ev:
    unified_msg_origin = "test:umo"


class _Inner:
    event = _Ev()


class FakeContextWrapper:
    context = _Inner()


def test_tool_names_and_schemas():
    tools = create_device_tools(StubService())
    assert [t.name for t in tools] == list(TOOL_NAMES)
    for t in tools:
        assert t.parameters["type"] == "object"
        assert t.description


def test_tap_tool_roundtrip():
    tools = {t.name: t for t in create_device_tools(StubService())}
    result = json.loads(
        asyncio.run(tools["companion_phone_tap"].call(FakeContextWrapper(), x=1, y=2))
    )
    assert result["xy"] == [1, 2]


def test_tap_tool_missing_arg():
    tools = {t.name: t for t in create_device_tools(StubService())}
    result = json.loads(
        asyncio.run(tools["companion_phone_tap"].call(FakeContextWrapper(), x=1))
    )
    assert result["status"] == "error"
    assert result["error_code"] == "invalid_argument"


def test_launch_tool_roundtrip():
    tools = {t.name: t for t in create_device_tools(StubService())}
    result = json.loads(
        asyncio.run(
            tools["companion_phone_launch_app"].call(
                FakeContextWrapper(), alias="wechat"
            )
        )
    )
    assert result["alias"] == "wechat"
