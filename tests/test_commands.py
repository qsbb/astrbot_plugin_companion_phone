from __future__ import annotations

import asyncio
import json

import pytest

import astrbot.api.event.filter as stub_filter
from astrbot.api import AstrBotConfig
from astrbot_plugin_companion_phone import main as plugin_main
from astrbot_plugin_companion_phone.constants import PLUGIN_ID, TOOL_NAMES

# 命令门控断言依赖离线 stub 注册表；真实宿主（装了 astrbot）跳过
pytestmark = pytest.mark.skipif(
    not hasattr(stub_filter, "_offline_registry"),
    reason="命令注册断言依赖离线 astrbot stub",
)

EXPECTED_COMMANDS = {
    "status",
    "reload",
    "shot",
    "apps",
    "task",
    "audit",
    "pause",
    "resume",
}


class FakeEvent:
    def __init__(self, message_str: str = "", group_id: str = ""):
        self.message_str = message_str
        self.unified_msg_origin = f"aiocqhttp:{'group' if group_id else 'private'}:1"
        self._group_id = group_id

    def get_group_id(self):
        return self._group_id

    def get_sender_id(self):
        return "u1"

    def plain_result(self, text):
        return {"type": "plain", "text": text}

    def image_result(self, path):
        return {"type": "image", "path": path}


def make_plugin(**over) -> tuple[object, AstrBotConfig]:
    from helpers import base_mapping

    config = AstrBotConfig(base_mapping(**over))
    context = plugin_main.Context()
    plugin = plugin_main.CompanionPhonePlugin(context, config)
    return plugin, config


def collect_commands():
    """从插件类收集 /phone 组的全部指令元数据（装饰器在导入时已登记）。"""
    commands: dict[str, dict] = {}
    group_seen = False
    for fn in vars(plugin_main.CompanionPhonePlugin).values():
        meta = getattr(fn, "_nx_meta", None)
        if not meta:
            continue
        if meta.get("kind") == "command_group":
            assert meta["name"] == "phone"
            group_seen = True
        if meta.get("kind") == "command":
            commands[meta["name"]] = meta
    assert group_seen, "command_group 未注册"
    return commands


async def collect_results(handler, event):
    return [item async for item in handler(event)]


@pytest.fixture
def plugin():
    plugin, config = make_plugin()
    return plugin, config


def test_register_metadata():
    meta = plugin_main.CompanionPhonePlugin._nx_register_meta
    assert meta["name"] == PLUGIN_ID
    assert meta["version"] == plugin_main.PLUGIN_VERSION


def test_all_phone_commands_registered():
    commands = collect_commands()
    assert set(commands) == EXPECTED_COMMANDS
    assert commands["task"]["alias"] == ("do",)


def test_every_command_is_admin_gated():
    """规范 §8 必测路径：权限门控（F-24 回归锚）。"""
    for name, meta in collect_commands().items():
        assert meta.get("permission") == stub_filter.PermissionType.ADMIN, (
            f"/phone {name} 缺少 ADMIN 门控"
        )


def test_tools_registered_into_context(plugin):
    plugin_obj, _ = plugin
    assert [t.name for t in plugin_obj.context.registered_tools] == list(TOOL_NAMES)


def test_phone_task_requires_goal(plugin):
    plugin_obj, _ = plugin
    results = asyncio.run(
        collect_results(plugin_obj.phone_task, FakeEvent("/phone task"))
    )
    assert "用法" in results[0]["text"]


def test_phone_task_disabled_reports(plugin):
    plugin_obj, _ = make_plugin(ENABLED=False)
    results = asyncio.run(
        collect_results(plugin_obj.phone_task, FakeEvent("/phone task 打开browser"))
    )
    assert "未启用" in results[0]["text"]


def test_pause_resume_toggles_config(plugin):
    plugin_obj, config = plugin
    results = asyncio.run(collect_results(plugin_obj.phone_pause, FakeEvent()))
    assert config["PAUSE_ALL"] is True and config.saved
    assert "暂停" in results[0]["text"]
    results = asyncio.run(collect_results(plugin_obj.phone_resume, FakeEvent()))
    assert config["PAUSE_ALL"] is False and config.saved


def test_pause_blocks_service_action(plugin):
    """门控行为级验证：pause 之后 tap 返回 all_actions_paused。"""
    plugin_obj, _ = plugin
    asyncio.run(collect_results(plugin_obj.phone_pause, FakeEvent()))
    result = asyncio.run(plugin_obj.service.tap("u1", 5, 5))
    assert result["status"] == "error"
    assert result["error_code"] == "all_actions_paused"


def test_reload_reports_not_ready_without_docker(plugin):
    """离线环境（无 docker）：reload 必须返回结构化的 ready=false 而非异常。"""
    plugin_obj, _ = plugin
    results = asyncio.run(collect_results(plugin_obj.phone_reload, FakeEvent()))
    payload = json.loads(results[0]["text"])
    assert payload["ready"] is False


def test_terminate_unregisters_all_tools(plugin):
    plugin_obj, _ = plugin
    context = plugin_obj.context
    asyncio.run(plugin_obj.terminate())
    assert context.unregistered_tools == list(TOOL_NAMES)
