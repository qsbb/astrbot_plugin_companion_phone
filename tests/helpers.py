from __future__ import annotations

from astrbot_plugin_companion_phone.config import PhoneConfig


def base_mapping(**over) -> dict:
    base = {
        "ENABLED": True,
        "MODE": "redroid",
        "REDROID_IMAGE": "redroid/redroid:test",
        "REDROID_DATA_PATH": "/tmp/companion-phone",
        "APP_WHITELIST": [
            {
                "__template_key": "app",
                "alias": "wechat",
                "package": "com.tencent.mm",
                "risk": "high",
            },
            {
                "__template_key": "app",
                "alias": "browser",
                "package": "com.android.browser",
                "risk": "low",
            },
        ],
        "HIGH_RISK_KEYWORDS": ["发送", "删除"],
        "DELAY_MS_MIN": 0,
        "DELAY_MS_MAX": 0,
    }
    base.update(over)
    return base


def make_cfg(**over) -> PhoneConfig:
    return PhoneConfig.from_mapping(base_mapping(**over))
