from __future__ import annotations

try:
    from astrbot.api import logger  # AstrBot 运行环境（官方要求统一 logger）
except Exception:  # 独立测试环境回退
    import logging

    logger = logging.getLogger("astrbot_plugin_companion_phone")

__all__ = ["logger"]
