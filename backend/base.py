from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class BackendState:
    ready: bool
    adb_serial: str  # 交给 DeviceSession 的目标，如 "127.0.0.1:26655" 或 USB serial
    detail: dict = field(default_factory=dict)


class DeviceBackend(ABC):
    """设备来源抽象：负责「让一台安卓设备可达」，不负责 UI 操作。"""

    @abstractmethod
    async def ensure_ready(self) -> BackendState:
        """确保设备就绪并返回 ADB serial；幂等，失败抛 BackendError。"""

    @abstractmethod
    async def health(self) -> BackendState:
        """只读探测，不拉起任何东西。"""

    @abstractmethod
    async def shutdown(self, *, stop_device: bool) -> None:
        """释放本后端资源。stop_device 仅对拥有设备生命周期的后端（redroid）生效；
        真机后端恒为无操作——绝不关用户的手机。"""

    @abstractmethod
    def describe(self) -> dict:
        """脱敏描述（模式、容器名/serial 等），用于管理页与日志。"""
