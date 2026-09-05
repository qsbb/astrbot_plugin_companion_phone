from __future__ import annotations

import asyncio
import json

from helpers import make_cfg


def test_screen_ok(service):
    result = asyncio.run(service.screen("u1"))
    assert result["status"] == "ok"
    assert result["screen_size"] == [1080, 2400]
    assert len(result["nodes"]) == 2
    # 截图存盘，路径为内部字段：由工具层消费（R2 视觉/排障），不进模型文本
    assert result["screenshot_path"].endswith(".png")


def test_tap_blocked_in_high_risk_foreground(service):
    """动作级门控回归锚：即使未经过 launch_app 进入高危应用，tap 也必须被拦。"""
    asyncio.run(service.tap("u1", 1, 1))  # 先触发会话建立
    sess = service._fake["session"]

    async def high_app():
        return {"package": "com.tencent.mm", "activity": ".UI"}

    sess.current_app = high_app
    result = asyncio.run(service.tap("u1", 540, 1200))
    assert result["status"] == "error"
    assert result["error_code"] == "high_risk_blocked"


def test_input_blocked_in_high_risk_foreground(service):
    asyncio.run(service.tap("u1", 1, 1))  # 先触发会话建立
    sess = service._fake["session"]

    async def high_app():
        return {"package": "com.tencent.mm", "activity": ".UI"}

    sess.current_app = high_app
    result = asyncio.run(service.input_text("u1", "你好", False))
    assert result["error_code"] == "high_risk_blocked"


def test_swipe_endpoints_clamped(service):
    result = asyncio.run(service.swipe("u1", "up", 2000))
    assert result["status"] == "ok"
    sess = service._fake["session"]
    swipes = [c for c in sess.calls if c[0] == "swipe"]
    _, sx, sy, ex, ey = swipes[-1]
    assert 0 <= sx <= 1080 and 0 <= ex <= 1080
    assert 0 <= sy <= 2400 and 0 <= ey <= 2400


def test_session_gate_blocks_group_events(service):
    class GroupEvent:
        unified_msg_origin = "aiocqhttp:group:123"

        def get_group_id(self):
            return "123"

    verdict = service.check_session_allowed(GroupEvent())
    assert verdict is not None
    assert verdict["error_code"] == "session_not_allowed"

    class PrivateEvent:
        unified_msg_origin = "aiocqhttp:private:u1"

        def get_group_id(self):
            return ""

    assert service.check_session_allowed(PrivateEvent()) is None


def test_session_gate_fail_closed_on_broken_event(service):
    """回归锚（G P2-2）：事件字段异常时 fail-closed，不静默放行。"""

    class BrokenEvent:
        unified_msg_origin = "x"

        def get_group_id(self):
            raise RuntimeError("boom")

    verdict = service.check_session_allowed(BrokenEvent())
    assert verdict is not None
    assert verdict["error_code"] == "session_not_allowed"


def test_status_verbose_hides_backend_details(service):
    """回归锚（G P2-4）：LLM 工具的 status 不暴露容器/镜像/端口。"""
    asyncio.run(service.tap("u1", 1, 1))  # 先建立后端
    trimmed = asyncio.run(service.status())
    full = asyncio.run(service.status(verbose=True))
    assert "backend" not in trimmed
    assert "backend" in full


def test_press_enter_gated_but_navigation_exempt(service):
    """按键分治回归锚（G P1-2）：enter 过门控，back/home 豁免（脱困通道）。"""
    asyncio.run(service.tap("u1", 1, 1))  # 建立会话（browser，白名单 low）
    sess = service._fake["session"]

    async def high_app():
        return {"package": "com.tencent.mm", "activity": ".UI"}

    sess.current_app = high_app
    result = asyncio.run(service.press_key("u1", "enter"))
    assert result["error_code"] == "high_risk_blocked"
    result = asyncio.run(service.press_key("u1", "back"))
    assert result["status"] == "ok"  # 导航键豁免
    result = asyncio.run(service.press_key("u1", "home"))
    assert result["status"] == "ok"


def test_budget_not_consumed_when_connect_fails(tmp_path, monkeypatch):
    from service_fixtures import FakeSession, install_fake_backend, make_service

    install_fake_backend(monkeypatch)
    svc = make_service(tmp_path, make_cfg(ACTION_MAX_PER_TURN=1))

    async def failing_connect(self):
        raise RuntimeError("offline")

    monkeypatch.setattr(FakeSession, "connect", failing_connect)
    first = asyncio.run(svc.tap("u1", 5, 5))
    assert first["status"] == "error"

    async def ok_connect(self):
        return None

    monkeypatch.setattr(FakeSession, "connect", ok_connect)
    second = asyncio.run(svc.tap("u1", 5, 5))
    assert second["status"] == "ok"  # 连接失败不消耗预算


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


def test_input_text_not_recorded_in_audit(service):
    long_text = "这是一段很长很长的输入内容" * 3  # 66 字符
    result = asyncio.run(service.input_text("u1", long_text, False))
    assert result["status"] == "ok"
    assert result["ime_fallback"] is False
    records = service.audit_recent(20)
    rec = [r for r in records if r["action"] == "input_text"][-1]
    dumped = json.dumps(rec, ensure_ascii=False)
    assert long_text not in dumped
    assert "这是一段" not in dumped  # 连片段都不落盘（验证码类短文本防泄漏）
    assert rec["params"] == {"text_len": len(long_text)}


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
