from __future__ import annotations

import asyncio

import pytest

from astrbot_plugin_companion_phone.backend.real import RealDeviceBackend
from astrbot_plugin_companion_phone.errors import BackendError

from helpers import make_cfg


class FakeAdbDevice:
    def __init__(self, serial: str):
        self.serial = serial


class FakeAdbDeviceObj:
    def __init__(self, ok=True):
        self._ok = ok

    def shell(self, cmd):
        return "ok" if self._ok else ""


class FakeAdbClient:
    def __init__(self, devices: list[str], *, connect_fails=False):
        self._devices = [FakeAdbDevice(s) for s in devices]
        self._connect_fails = connect_fails
        self.connected: list[str] = []
        self.shelled: list[str] = []
        self._device_obj = FakeAdbDeviceObj()

    def connect(self, addr):
        if self._connect_fails:
            raise RuntimeError("refused")
        self.connected.append(addr)
        return 0

    def device(self, serial):
        self.shelled.append(serial)
        return self._device_obj

    def device_list(self):
        return list(self._devices)


def make_backend(**over) -> RealDeviceBackend:
    return RealDeviceBackend(make_cfg(MODE="real", **over))


def patch_client(monkeypatch, client: FakeAdbClient):
    monkeypatch.setattr(RealDeviceBackend, "_client", staticmethod(lambda: client))


def test_wireless_priority_over_serial(monkeypatch):
    """同时配置无线地址与 serial 时，无线优先（锁定语义防漂移）。"""
    client = FakeAdbClient(["usb1"])
    patch_client(monkeypatch, client)
    backend = make_backend(REAL_SERIAL="usb1", REAL_WIRELESS_ADDR="192.168.1.9:5555")
    state = asyncio.run(backend.ensure_ready())
    assert state.adb_serial == "192.168.1.9:5555"
    assert client.connected == ["192.168.1.9:5555"]


def test_serial_not_found(monkeypatch):
    patch_client(monkeypatch, FakeAdbClient(["other"]))
    backend = make_backend(REAL_SERIAL="usb1")
    with pytest.raises(BackendError) as excinfo:
        asyncio.run(backend.ensure_ready())
    assert excinfo.value.code == "adb_connect_failed"
    assert "usb1" in excinfo.value.message


def test_serial_not_found_when_no_devices(monkeypatch):
    """配置了 serial 但没有任何设备在线 → adb_connect_failed（含 serial 提示）。"""
    patch_client(monkeypatch, FakeAdbClient([]))
    backend = make_backend(REAL_SERIAL="usb1")
    with pytest.raises(BackendError) as excinfo:
        asyncio.run(backend.ensure_ready())
    assert excinfo.value.code == "adb_connect_failed"


def test_single_device_auto_selected(monkeypatch):
    patch_client(monkeypatch, FakeAdbClient(["usb1"]))
    backend = make_backend(REAL_SERIAL="usb1")
    state = asyncio.run(backend.ensure_ready())
    assert state.adb_serial == "usb1"


def test_health_without_serial(monkeypatch):
    from astrbot_plugin_companion_phone.config import PhoneConfig

    patch_client(monkeypatch, FakeAdbClient([]))
    # 绕过 from_mapping 校验直接构造，模拟会话尚未建立的状态
    backend = RealDeviceBackend(PhoneConfig(mode="real"))
    state = asyncio.run(backend.health())
    assert state.ready is False


def test_shutdown_never_touches_device(monkeypatch):
    client = FakeAdbClient(["usb1"])
    patch_client(monkeypatch, client)
    backend = make_backend(REAL_SERIAL="usb1")
    asyncio.run(backend.ensure_ready())
    asyncio.run(backend.shutdown(stop_device=True))
    assert backend._serial is None
    # 真机安全回归：shutdown 绝不向设备下发任何 shell 命令
    assert client.shelled  # ensure_ready 探活产生过
    shell_count = len(client.shelled)
    asyncio.run(backend.shutdown(stop_device=True))
    assert len(client.shelled) == shell_count
