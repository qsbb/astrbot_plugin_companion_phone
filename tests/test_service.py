from __future__ import annotations

import asyncio
import json

from helpers import make_cfg


def test_screen_ok(service):
    result = asyncio.run(service.screen())
    assert result["status"] == "ok"
    assert result["screen_size"] == [1080, 2400]
    assert len(result["nodes"]) == 2
    assert result["screenshot"].endswith(".png")


def test_tap_ok(service):
    result = asyncio.run(service.tap("u1", 540, 1200))
    assert result["status"] == "ok"
    assert ("tap", 540, 1200) in service._fake["session"].calls


def test_tap_out_of_bounds(service):
    result = asyncio.run(service.tap("u1", 5000, 100))
    assert result["status"] == "error"
    assert result["error_code"] == "tap_out_of_bounds"


def test_click_text_keyword_blocked(service):
    # 当前前台是 browser（low risk），但「发送」命中高危关键词
    result = asyncio.run(service.click_text("u1", "发送"))
    assert result["status"] == "error"
    assert result["error_code"] == "high_risk_blocked"


def test_click_text_ok(service):
    result = asyncio.run(service.click_text("u1", "搜索"))
    assert result["status"] == "ok"
    assert result["bounds"] == [0, 0, 100, 100]


def test_launch_app_not_allowed(service):
    result = asyncio.run(service.launch_app("u1", "game"))
    assert result["status"] == "error"
    assert result["error_code"] == "app_not_in_whitelist"
    assert "wechat" in result["message"]


def test_launch_high_risk_app_blocked(service):
    # v2 安全模型：高危应用默认禁止进入（入口门控），无论 ALLOW_HIGH_RISK 之外的动作
    result = asyncio.run(service.launch_app("u1", "wechat"))
    assert result["status"] == "error"
    assert result["error_code"] == "high_risk_blocked"
    assert "ALLOW_HIGH_RISK" in result["message"]


def test_launch_high_risk_app_allowed_when_enabled(service, monkeypatch):
    service._cfg_provider = lambda: make_cfg(ALLOW_HIGH_RISK=True)
    result = asyncio.run(service.launch_app("u1", "wechat"))
    assert result["status"] == "ok"
    assert ("app_start", "com.tencent.mm") in service._fake["session"].calls


def test_launch_app_ok(service):
    result = asyncio.run(service.launch_app("u1", "browser"))
    assert result["status"] == "ok"
    assert ("app_start", "com.android.browser") in service._fake["session"].calls


def test_disabled(service):
    service._cfg_provider = lambda: make_cfg(ENABLED=False)
    result = asyncio.run(service.tap("u1", 5, 5))
    assert result["error_code"] == "plugin_disabled"


def test_paused(service):
    service._cfg_provider = lambda: make_cfg(PAUSE_ALL=True)
    result = asyncio.run(service.tap("u1", 5, 5))
    assert result["error_code"] == "all_actions_paused"


def test_budget_exceeded(service):
    service._cfg_provider = lambda: make_cfg(ACTION_MAX_PER_TURN=1)
    ok = asyncio.run(service.tap("u1", 5, 5))
    assert ok["status"] == "ok"
    blocked = asyncio.run(service.tap("u1", 6, 6))
    assert blocked["error_code"] == "action_budget_exceeded"


def test_input_text_masked_in_audit(service):
    long_text = "这是一段很长很长的输入内容" * 3  # 66 字符
    result = asyncio.run(service.input_text("u1", long_text, False))
    assert result["status"] == "ok"
    records = service.audit_recent(20)
    rec = [r for r in records if r["action"] == "input_text"][-1]
    assert long_text not in json.dumps(rec, ensure_ascii=False)  # 全文不落盘
    assert rec["params"]["text_len"] == len(long_text)
    assert rec["params"]["text_head"].endswith("***")


def test_swipe_invalid_direction(service):
    result = asyncio.run(service.swipe("u1", "diagonal", 600))
    assert result["error_code"] == "invalid_argument"


def test_press_key_and_wait(service):
    result = asyncio.run(service.press_key("u1", "back"))
    assert result["status"] == "ok"
    result = asyncio.run(service.wait_element("u1", "搜索", 5))
    assert result["status"] == "ok"
    assert result["found"] is True


def test_audit_records_error_outcomes(service):
    asyncio.run(service.tap("u1", 5000, 100))  # 越界 → error
    records = service.audit_recent(20)
    rec = [r for r in records if r["action"] == "tap"][-1]
    assert rec["outcome"] == "error"
    assert rec["error_code"] == "tap_out_of_bounds"
