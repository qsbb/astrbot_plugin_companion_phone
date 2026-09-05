from __future__ import annotations

import asyncio

from ..constants import E_ADB_CONNECT_FAILED, E_MODE_INVALID, MODE_REAL
from ..errors import BackendError
from .base import BackendState, DeviceBackend


class RealDeviceBackend(DeviceBackend):
    """真机后端：USB serial 直连，或无线 adb connect；不管理设备生命周期。"""

    def __init__(self, cfg) -> None:
        self._cfg = cfg
        self._serial: str | None = None

    @staticmethod
    def _client():
        import adbutils  # 延迟导入：插件加载与单元测试不依赖设备库

        return adbutils.AdbClient(host="127.0.0.1", port=5037)

    async def ensure_ready(self) -> BackendState:
        cfg = self._cfg
        client = await asyncio.to_thread(self._client)
        if cfg.real_wireless_addr:
            addr = cfg.real_wireless_addr
            try:
                await asyncio.to_thread(client.connect, addr)
            except Exception as exc:
                raise BackendError(
                    E_ADB_CONNECT_FAILED, f"无线 ADB 连接失败：{exc}"
                ) from exc
            self._serial = addr
        else:
            devices = await asyncio.to_thread(client.device_list)
            if cfg.real_serial:
                serials = [d.serial for d in devices]
                if cfg.real_serial not in serials:
                    raise BackendError(
                        E_ADB_CONNECT_FAILED,
                        f"未找到 USB 设备 {cfg.real_serial}（用 adb devices 检查）",
                    )
                self._serial = cfg.real_serial
            elif len(devices) == 1:
                self._serial = devices[0].serial
            elif not devices:
                raise BackendError(E_ADB_CONNECT_FAILED, "没有检测到任何 ADB 设备")
            else:
                raise BackendError(
                    E_MODE_INVALID, "检测到多台设备，请在配置中明确 REAL_SERIAL"
                )
        await self._probe(client)
        return BackendState(ready=True, adb_serial=self._serial, detail=self.describe())

    async def _probe(self, client) -> None:
        try:
            out = await asyncio.to_thread(client.shell, self._serial, "echo ok")
        except Exception as exc:
            raise BackendError(E_ADB_CONNECT_FAILED, f"设备探活失败：{exc}") from exc
        if "ok" not in str(out):
            raise BackendError(E_ADB_CONNECT_FAILED, "设备探活失败：无响应")

    async def health(self) -> BackendState:
        if not self._serial:
            return BackendState(ready=False, adb_serial="", detail={"mode": MODE_REAL})
        try:
            client = await asyncio.to_thread(self._client)
            out = await asyncio.to_thread(client.shell, self._serial, "echo ok")
            ready = "ok" in str(out)
        except Exception:
            ready = False
        return BackendState(
            ready=ready, adb_serial=self._serial, detail=self.describe()
        )

    async def shutdown(self, *, stop_device: bool) -> None:
        # 真机绝不被插件关机；仅丢弃会话引用
        self._serial = None

    def describe(self) -> dict:
        return {
            "mode": MODE_REAL,
            "serial": self._serial
            or self._cfg.real_serial
            or self._cfg.real_wireless_addr,
        }
