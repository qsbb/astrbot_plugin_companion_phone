from __future__ import annotations

from ..config import PhoneConfig
from ..constants import MODE_REAL, MODE_REDROID
from .base import BackendState, DeviceBackend
from .real import RealDeviceBackend
from .redroid import RedroidBackend

__all__ = [
    "BackendState",
    "DeviceBackend",
    "RealDeviceBackend",
    "RedroidBackend",
    "create_backend",
]


def create_backend(cfg: PhoneConfig) -> DeviceBackend:
    if cfg.mode == MODE_REDROID:
        return RedroidBackend(cfg)
    if cfg.mode == MODE_REAL:
        return RealDeviceBackend(cfg)
    raise ValueError(f"未知设备模式：{cfg.mode}")
