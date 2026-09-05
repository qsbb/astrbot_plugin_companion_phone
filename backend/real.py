from __future__ import annotations

import asyncio

from ..constants import E_ADB_CONNECT_FAILED, MODE_REAL
from ..errors import BackendError
from .base import BackendState, DeviceBackend

_ADB_TIMEOUT_SECONDS = 30.0  # 规范 §3.2：外部 IO 必须有超时上限


class RealDeviceBackend(DeviceBackend):
    """真机后端：USB serial 直连，或无线 adb connect；不管理设备生命周期。"""

    def __init__(self, cfg) -> None:
        self._cfg = cfg
        self._serial: str | None = None

    @staticmethod
    def _client():
        import adbutils  # 延迟导入：插件加载与单元测试不依赖设备库

        return adbutils.AdbClient(host="127.0.0.1", port=5037)

    async def _adb(self, fn, *args, **kwargs):
        """adbutils 同步调用统一 30s 超时，防止挂起拖死会话。"""
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(fn, *args, **kwargs), timeout=_ADB_TIMEOUT_SECONDS
            )
        except asyncio.TimeoutError:
            raise BackendError(
                E_ADB_CONNECT_FAILED, f"adb 调用超时（{_ADB_TIMEOUT_SECONDS:.0f}s）"
            ) from None

    async def ensure_ready(self) -> BackendState:
        cfg = self._cfg
        client = await self._adb(self._client)
        if cfg.real_wireless_addr:
            addr = cfg.real_wireless_addr
            try:
                result = await self._adb(client.connect, addr)
            except BackendError:
                raise
            except Exception as exc:
                raise BackendError(
                    E_ADB_CONNECT_FAILED, f"无线 ADB 连接失败：{exc}"
                ) from exc
            # adbutils 对 "unable to connect" 不抛异常而是返回字符串——显式检查
            text = str(result)
            if any(marker in text.lower() for marker in ("unable", "failed", "cannot")):
                raise BackendError(E_ADB_CONNECT_FAILED, f"无线 ADB 连接失败：{text}")
            self._serial = addr
        else:
            # 配置校验保证真机模式下 real_serial 必填（无自动选择分支）
            devices = await self._adb(client.device_list)
            serials = [d.serial for d in devices]
            if cfg.real_serial not in serials:
                raise BackendError(
                    E_ADB_CONNECT_FAILED,
                    f"未找到 USB 设备 {cfg.real_serial}（用 adb devices 检查）",
                )
            self._serial = cfg.real_serial
        await self._probe(client)
        return BackendState(ready=True, adb_serial=self._serial, detail=self.describe())

    async def _probe(self, client) -> None:
        try:
            # AdbClient.shell 已弃用（adbutils 0.15+），用 device(serial).shell
            device = await self._adb(client.device, self._serial)
            out = await self._adb(device.shell, "echo ok")
        except BackendError:
            raise
        except Exception as exc:
            raise BackendError(E_ADB_CONNECT_FAILED, f"设备探活失败：{exc}") from exc
        if "ok" not in str(out):
            raise BackendError(E_ADB_CONNECT_FAILED, "设备探活失败：无响应")

    async def health(self) -> BackendState:
        if not self._serial:
            return BackendState(ready=False, adb_serial="", detail={"mode": MODE_REAL})
        try:
            client = await self._adb(self._client)
            device = await self._adb(client.device, self._serial)
            out = await self._adb(device.shell, "echo ok")
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
