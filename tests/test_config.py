from __future__ import annotations

import pytest

from astrbot_plugin_companion_phone.config import PhoneConfig

from helpers import base_mapping


def test_valid_redroid_config():
    cfg = PhoneConfig.from_mapping(base_mapping())
    assert cfg.mode == "redroid"
    assert cfg.enabled is True
    assert len(cfg.app_whitelist) == 2
    assert cfg.app_by_alias("WeChat") is not None  # 别名大小写不敏感
    assert cfg.app_by_package("com.tencent.mm").risk == "high"
    assert cfg.alias_list() == ["wechat", "browser"]


def test_invalid_mode_rejected():
    with pytest.raises(ValueError):
        PhoneConfig.from_mapping(base_mapping(MODE="cloud"))


def test_real_mode_requires_target():
    with pytest.raises(ValueError):
        PhoneConfig.from_mapping(base_mapping(MODE="real"))


def test_real_mode_wireless_ok():
    cfg = PhoneConfig.from_mapping(
        base_mapping(MODE="real", REAL_WIRELESS_ADDR="192.168.1.9:5555")
    )
    assert cfg.mode == "real"


def test_redroid_requires_image_and_path():
    with pytest.raises(ValueError):
        PhoneConfig.from_mapping(base_mapping(REDROID_IMAGE=""))
    with pytest.raises(ValueError):
        PhoneConfig.from_mapping(base_mapping(REDROID_DATA_PATH=""))


def test_duplicate_alias_rejected():
    mapping = base_mapping()
    mapping["APP_WHITELIST"] = [
        {"alias": "a", "package": "com.a.b"},
        {"alias": "A", "package": "com.c.d"},
    ]
    with pytest.raises(ValueError):
        PhoneConfig.from_mapping(mapping)


def test_bad_package_rejected():
    mapping = base_mapping()
    mapping["APP_WHITELIST"] = [{"alias": "x", "package": "not a package"}]
    with pytest.raises(ValueError):
        PhoneConfig.from_mapping(mapping)


def test_json_fallback_whitelist():
    mapping = base_mapping(
        APP_WHITELIST=[],
        APP_WHITELIST_JSON='[{"alias":"momo","package":"im.momo.app","risk":"low"}]',
    )
    cfg = PhoneConfig.from_mapping(mapping)
    assert cfg.app_whitelist[0].alias == "momo"


def test_delay_range_validated():
    with pytest.raises(ValueError):
        PhoneConfig.from_mapping(base_mapping(DELAY_MS_MIN=1000, DELAY_MS_MAX=100))


def test_negative_delay_rejected():
    with pytest.raises(ValueError):
        PhoneConfig.from_mapping(base_mapping(DELAY_MS_MIN=-5, DELAY_MS_MAX=100))


def test_uppercase_packages_accepted():
    """回归锚（F-09）：真实存在的包名 com.Slack / com.UCMobile.intl 必须可配置。

    连字符按 Android 官方 applicationId 字符集排除（第二轮盲测 H P3-4）。
    """
    mapping = base_mapping()
    mapping["APP_WHITELIST"] = [
        {"alias": "slack", "package": "com.Slack"},
        {"alias": "uc", "package": "com.UCMobile.intl"},
    ]
    cfg = PhoneConfig.from_mapping(mapping)
    assert len(cfg.app_whitelist) == 2
    with pytest.raises(ValueError):
        PhoneConfig.from_mapping(
            base_mapping(
                APP_WHITELIST=[{"alias": "hy", "package": "com.example.my-app"}]
            )
        )


def test_zero_or_negative_ints_fall_back_to_defaults():
    """回归锚（F-29）：schema 之外的第二道防线，防手改配置炸掉运行时。"""
    cfg = PhoneConfig.from_mapping(
        base_mapping(ACTION_MAX_PER_TURN=0, TASK_MAX_STEPS=-1, SCREENSHOT_KEEP=0)
    )
    assert cfg.action_max_per_turn == 8
    assert cfg.task_max_steps == 12
    assert cfg.screenshot_keep == 50


def test_invalid_container_name_rejected():
    with pytest.raises(ValueError):
        PhoneConfig.from_mapping(base_mapping(REDROID_CONTAINER="-evil-flag"))


def test_tool_chat_scope_validation():
    cfg = PhoneConfig.from_mapping(
        base_mapping(
            TOOL_CHAT_SCOPE="allowlist", TOOL_ALLOWLIST=["aiocqhttp:private:u1"]
        )
    )
    assert cfg.tool_chat_scope == "allowlist"
    assert cfg.tool_allowlist == ("aiocqhttp:private:u1",)
    with pytest.raises(ValueError):
        PhoneConfig.from_mapping(base_mapping(TOOL_CHAT_SCOPE="everyone"))


def test_default_scope_is_private():
    assert PhoneConfig.from_mapping(base_mapping()).tool_chat_scope == "private"
