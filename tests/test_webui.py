from __future__ import annotations

import asyncio
import json

import pytest

from astrbot_plugin_companion_phone.config import PhoneConfig
from astrbot_plugin_companion_phone.constants import (
    PLUGIN_ID,
)
from astrbot_plugin_companion_phone.service import PhoneService
from astrbot_plugin_companion_phone.webui import PhoneWebUI

from service_fixtures import install_fake_backend


class FakeConfig(dict):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.saved = False

    def save_config(self):
        self.saved = True


@pytest.fixture
def webui(tmp_path, monkeypatch):
    install_fake_backend(monkeypatch)
    config = FakeConfig(
        {
            "ENABLED": True,
            "MODE": "redroid",
            "REDROID_IMAGE": "redroid/redroid:test",
            "REDROID_DATA_PATH": "/tmp/companion-phone",
            "APP_WHITELIST": [
                {"alias": "wechat", "package": "com.tencent.mm", "risk": "high"},
            ],
        }
    )
    service = PhoneService(lambda: PhoneConfig.from_mapping(config), tmp_path)
    return PhoneWebUI(service, config), service, config


def test_contract_shape(webui):
    ui, _, _ = webui
    contract = asyncio.run(ui.webui_panels_contract())
    # 核网关硬校验：name 必须精确为 series.webui@1.0
    assert contract["name"] == "series.webui@1.0"
    assert contract["series_id"] == "ningxin_suxi"
    assert contract["plugin_id"] == PLUGIN_ID
    ids = [p["id"] for p in contract["panels"]]
    assert ids == ["phone_status", "phone_apps", "phone_audit"]
    for p in contract["panels"]:
        assert set(p) == {"id", "title", "description"}


def test_status_data_render_contract(webui):
    ui, _, _ = webui
    data = asyncio.run(ui.webui_panel_data("phone_status"))
    assert data["success"] is True
    assert data["title"] == "手机状态"
    assert all(set(c) == {"key", "label"} for c in data["columns"])
    assert data["rows"] and all(set(r) == {"item", "value"} for r in data["rows"])
    action_ids = [a["id"] for a in data["actions"]]
    assert action_ids == ["reload", "pause", "resume"]
    assert all("confirm" in a for a in data["actions"])


def test_apps_and_audit_data(webui):
    ui, _, _ = webui
    apps = asyncio.run(ui.webui_panel_data("phone_apps"))
    assert apps["rows"] == [
        {"alias": "wechat", "package": "com.tencent.mm", "risk": "high"}
    ]
    assert apps["actions"] == []
    audit = asyncio.run(ui.webui_panel_data("phone_audit"))
    assert audit["rows"] == []
    assert [a["id"] for a in audit["actions"]] == ["clear"]


def test_unknown_panel_fail_closed(webui):
    ui, _, _ = webui
    # 规范 §5.3：未知 id 以「返回」而非抛异常表达 fail-closed
    data = asyncio.run(ui.webui_panel_data("nope"))
    assert data["success"] is False
    assert data["error_code"] == "UNKNOWN_PANEL"
    result = asyncio.run(ui.webui_panel_action("nope", "x"))
    assert result["success"] is False
    assert result["error_code"] == "UNKNOWN_PANEL"


def test_unknown_action_fail_closed(webui):
    ui, _, _ = webui
    result = asyncio.run(ui.webui_panel_action("phone_apps", "reload"))  # apps 无动作
    assert result["success"] is False
    assert result["error_code"] == "UNKNOWN_ACTION"
    result = asyncio.run(ui.webui_panel_action("phone_status", "destroy"))
    assert result["success"] is False
    assert result["error_code"] == "UNKNOWN_ACTION"


def test_pause_resume_and_reload_actions(webui):
    ui, _, config = webui
    result = asyncio.run(ui.webui_panel_action("phone_status", "pause"))
    assert result == {"success": True, "message": "已暂停全部手机动作。"}
    assert config["PAUSE_ALL"] is True and config.saved
    result = asyncio.run(ui.webui_panel_action("phone_status", "resume"))
    assert config["PAUSE_ALL"] is False and config.saved
    result = asyncio.run(ui.webui_panel_action("phone_status", "reload"))
    assert result["success"] is True
    assert "已按模式" in result["message"] or "重建" in result["message"]


def test_audit_clear_action(webui, tmp_path, monkeypatch):
    ui, service, _ = webui
    service._audit.record(umo="u", mode="real", action="tap", params={}, outcome="ok")
    assert service.audit_recent(10)
    result = asyncio.run(ui.webui_panel_action("phone_audit", "clear"))
    assert result["success"] is True
    assert service.audit_recent(10) == []


def test_data_is_json_serializable(webui):
    ui, _, _ = webui
    for panel in ("phone_status", "phone_apps", "phone_audit"):
        payload = asyncio.run(ui.webui_panel_data(panel))
        json.dumps(payload, ensure_ascii=False)  # 不抛即通过：核网关直接转发
