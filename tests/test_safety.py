from __future__ import annotations

import pytest

from astrbot_plugin_companion_phone.constants import (
    E_APP_NOT_ALLOWED,
    E_BUDGET_EXCEEDED,
    E_HIGH_RISK_BLOCKED,
    E_OUT_OF_BOUNDS,
)
from astrbot_plugin_companion_phone.errors import SafetyError
from astrbot_plugin_companion_phone.safety import SafetyGate

from helpers import make_cfg


def make_gate(**over) -> SafetyGate:
    return SafetyGate(make_cfg(**over))


def test_whitelist_hit_and_miss():
    gate = make_gate()
    entry = gate.check_app("wechat")
    assert entry.risk == "high"
    with pytest.raises(SafetyError) as excinfo:
        gate.check_app("game")
    assert excinfo.value.code == E_APP_NOT_ALLOWED
    assert "wechat" in excinfo.value.message  # 错误信息附别名清单，帮助模型自我纠正


def test_high_risk_app_blocks_click():
    gate = make_gate()
    wechat = gate.check_app("wechat")
    with pytest.raises(SafetyError) as excinfo:
        gate.check_tap_text("随便什么", wechat)
    assert excinfo.value.code == E_HIGH_RISK_BLOCKED


def test_keyword_blocks_click_in_low_risk_app():
    gate = make_gate()
    browser = gate.check_app("browser")
    with pytest.raises(SafetyError) as excinfo:
        gate.check_tap_text("点击发送消息", browser)
    assert excinfo.value.code == E_HIGH_RISK_BLOCKED


def test_allow_high_risk_bypasses():
    gate = make_gate(ALLOW_HIGH_RISK=True)
    wechat = gate.check_app("wechat")
    gate.check_tap_text("发送", wechat)  # 不抛即通过


def test_tap_bounds():
    gate = make_gate()
    gate.check_tap_xy(10, 10, [1080, 2400])
    with pytest.raises(SafetyError) as excinfo:
        gate.check_tap_xy(2000, 10, [1080, 2400])
    assert excinfo.value.code == E_OUT_OF_BOUNDS


def test_tap_xy_zero_size_fail_closed():
    """回归锚（F-25）：读不到屏幕尺寸时拒绝，而不是放行任意坐标。"""
    gate = make_gate()
    with pytest.raises(SafetyError) as excinfo:
        gate.check_tap_xy(10, 10, [0, 0])
    assert excinfo.value.code == E_OUT_OF_BOUNDS


def test_check_current_app_high_blocked():
    """动作级门控回归锚（F-05）：前台为高危应用时 tap/input/swipe 必须可被拦。"""
    gate = make_gate()
    with pytest.raises(SafetyError) as excinfo:
        gate.check_current_app("com.tencent.mm")
    assert excinfo.value.code == E_HIGH_RISK_BLOCKED


def test_check_current_app_low_passes():
    gate = make_gate()
    assert gate.check_current_app("com.android.browser") is not None


def test_check_current_app_non_whitelisted_denied():
    """白名单即操作边界（安全模型 v4）：launcher/权限对话框/未知包名全部拒绝。"""
    gate = make_gate()
    for pkg in (
        "com.android.launcher",
        "com.google.android.permissioncontroller",
        "com.android.systemui",
        "",
    ):
        with pytest.raises(SafetyError) as excinfo:
            gate.check_current_app(pkg)
        assert excinfo.value.code == E_HIGH_RISK_BLOCKED
        assert "APP_WHITELIST" in excinfo.value.message


def test_check_current_app_unknown_package_fail_closed():
    gate = make_gate()
    with pytest.raises(SafetyError) as excinfo:
        gate.check_current_app("")
    assert excinfo.value.code == E_HIGH_RISK_BLOCKED


def test_check_current_app_allowed_when_enabled():
    gate = make_gate(ALLOW_HIGH_RISK=True)
    assert gate.check_current_app("com.tencent.mm") is not None


def test_budget_window():
    gate = make_gate(ACTION_MAX_PER_TURN=2)
    gate.budget_consume("umo1")
    gate.budget_consume("umo1")
    with pytest.raises(SafetyError) as excinfo:
        gate.budget_consume("umo1")
    assert excinfo.value.code == E_BUDGET_EXCEEDED
    gate.budget_consume("umo2")  # 其他会话不受影响


def test_task_budget_independent():
    gate = make_gate(ACTION_MAX_PER_TURN=1)
    gate.task_budget_start("umo1", 3)
    for _ in range(3):
        gate.budget_consume("umo1")
    with pytest.raises(SafetyError):
        gate.budget_consume("umo1")  # 任务预算用尽
    gate.task_budget_stop("umo1")
    gate.budget_consume("umo1")  # 回到窗口预算
    with pytest.raises(SafetyError):
        gate.budget_consume("umo1")  # 窗口预算（上限 1）也已用尽
