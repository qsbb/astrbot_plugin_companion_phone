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
