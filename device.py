from __future__ import annotations

import asyncio
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Callable

from .constants import E_DEVICE_OFFLINE, E_DEVICE_TIMEOUT, E_ELEMENT_NOT_FOUND
from .errors import DeviceError

_BOUNDS_RE = re.compile(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]")

# 规范 §3.2：外部 IO 必须有超时上限；单设备操作挂起不得拖死设备锁
_DEVICE_OP_TIMEOUT_SECONDS = 60.0

# 常见弹窗的确认文本；dismiss_popups 逐个尝试代点。
# 刻意不含「确定」——语义中性，可能在支付/删除对话框上代点确认。
_POPUP_TEXTS = ("我知道了", "允许", "始终允许", "稍后", "以后再说", "关闭广告")


class DeviceSession:
    """uiautomator2 封装：线程隔离 + 设备级互斥。

    uiautomator2/adbutils 均为同步 API：所有调用统一 asyncio.to_thread，
    单设备是串行资源，self._lock 保证动作不交错。
    """

    def __init__(self, backend: Any) -> None:
        self._backend = backend
        self._d: Any = None
        self._lock = asyncio.Lock()
        self._closed = False

    @property
    def backend(self) -> Any:
        return self._backend

    # ---------- 连接管理 ----------
    async def connect(self) -> None:
        async with self._lock:
            if self._closed:
                raise DeviceError(E_DEVICE_OFFLINE, "会话已关闭")
            state = await self._backend.ensure_ready()
            try:
                self._d = await asyncio.to_thread(self._connect_sync, state.adb_serial)
            except Exception as exc:
                raise DeviceError(E_DEVICE_OFFLINE, f"设备连接失败：{exc}") from exc

    @staticmethod
    def _connect_sync(serial: str) -> Any:
        import uiautomator2 as u2  # 延迟导入；首次会向设备安装 atx-agent

        return u2.connect(serial)

    async def assert_ready(self) -> None:
        """探活；不 ready 时经 backend 自愈一次再复检。"""
        async with self._lock:
            if self._closed:
                raise DeviceError(E_DEVICE_OFFLINE, "会话已关闭")
            if self._d is not None and await asyncio.to_thread(self._alive_sync):
                return
            state = await self._backend.ensure_ready()
            try:
                self._d = await asyncio.to_thread(self._connect_sync, state.adb_serial)
            except Exception as exc:
                raise DeviceError(E_DEVICE_OFFLINE, f"设备重连失败：{exc}") from exc

    def _alive_sync(self) -> bool:
        try:
            return bool(self._d.alive)
        except Exception:
            return False

    async def _run(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        """确保连接后，在设备锁内执行同步函数；硬超时防挂起。"""
        await self.assert_ready()
        async with self._lock:
            try:
                return await asyncio.wait_for(
                    asyncio.to_thread(fn, *args, **kwargs),
                    timeout=_DEVICE_OP_TIMEOUT_SECONDS,
                )
            except asyncio.TimeoutError:
                # 超时说明连接可能已僵死：丢弃设备引用，下次操作强制重连
                self._d = None
                raise DeviceError(
                    E_DEVICE_TIMEOUT,
                    f"设备操作超时（{_DEVICE_OP_TIMEOUT_SECONDS:.0f}s），请稍后重试",
                ) from None
            except DeviceError:
                raise
            except Exception as exc:
                raise DeviceError(E_DEVICE_OFFLINE, f"设备操作失败：{exc}") from exc

    async def close(self) -> None:
        async with self._lock:
            self._closed = True
            self._d = None

    # ---------- 感知 ----------
    async def ui_tree(self, max_nodes: int) -> list[dict]:
        return await self._run(self._dump_sync, max_nodes)

    def _dump_sync(self, max_nodes: int) -> list[dict]:
        root = ET.fromstring(self._d.dump_hierarchy())
        nodes: list[dict] = []
        for idx, el in enumerate(root.iter("node")):
            if len(nodes) >= max_nodes:
                break
            text = (el.get("text") or "").strip()
            desc = (el.get("content-desc") or "").strip()
            clickable = el.get("clickable") == "true"
            if not text and not desc and not clickable:
                continue  # 信息密度优先：无文本不可点的节点对模型无意义
            bounds = self._parse_bounds(el.get("bounds") or "")
            if bounds is None:
                continue
            nodes.append(
                {
                    "rid": idx,
                    "text": text,
                    "desc": desc,
                    "resource_id": (el.get("resource-id") or "").strip(),
                    "bounds": bounds,
                    "clickable": clickable,
                    "scrollable": el.get("scrollable") == "true",
                }
            )
        return nodes

    @staticmethod
    def _parse_bounds(raw: str) -> list[int] | None:
        m = _BOUNDS_RE.match(raw)
        if not m:
            return None
        x1, y1, x2, y2 = (int(v) for v in m.groups())
        if x2 <= x1 or y2 <= y1:
            return None
        return [x1, y1, x2, y2]

    async def screenshot(self, path: Path) -> Path:
        return await self._run(self._screenshot_sync, path)

    def _screenshot_sync(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._d.screenshot(str(path))
        return path

    async def screen_size(self) -> list[int]:
        def _size() -> tuple[int, int]:
            w, h = self._d.window_size()
            return int(w), int(h)

        w, h = await self._run(_size)
        return [w, h]

    async def screen_on(self) -> bool:
        info = await self._run(self._info_sync)
        return bool(info.get("screenOn"))

    def _info_sync(self) -> dict:
        try:
            return dict(self._d.info or {})
        except Exception:
            return {}

    async def current_app(self) -> dict:
        try:
            return await self._run(self._current_app_sync)
        except DeviceError:
            return {"package": "", "activity": ""}

    def _current_app_sync(self) -> dict:
        info = self._d.app_current()
        return {
            "package": info.get("package", ""),
            "activity": info.get("activity", ""),
        }

    # ---------- 操作 ----------
    async def tap(self, x: int, y: int) -> None:
        await self._run(self._d.click, x, y)

    async def click_text(self, text: str) -> list[int]:
        return await self._run(self._click_text_sync, text)

    def _click_text_sync(self, text: str) -> list[int]:
        sel = self._d(text=text)
        if not sel.exists:
            raise DeviceError(E_ELEMENT_NOT_FOUND, f"屏幕上没有找到文本：{text}")
        info = sel.info or {}
        sel.click()
        return info.get("bounds") or []

    async def input_text(self, text: str, clear: bool) -> bool:
        """返回是否走了 ASCII 回退（FastInputIME 不可用时）。"""
        return await self._run(self._input_sync, text, clear)

    def _input_sync(self, text: str, clear: bool) -> bool:
        ascii_fallback = False
        try:
            self._d.set_fastinput_ime(True)
        except Exception:
            ascii_fallback = True
        if clear:
            try:
                self._d.clear_text()
            except Exception:
                pass
        self._d.send_keys(text)
        return ascii_fallback

    async def swipe(self, sx: int, sy: int, ex: int, ey: int, duration_ms: int) -> None:
        await self._run(self._d.swipe, sx, sy, ex, ey, duration_ms / 1000.0)

    async def press_key(self, key: str) -> None:
        await self._run(self._press_key_sync, key)

    def _press_key_sync(self, key: str) -> None:
        if key == "recents":
            self._d.shell("input keyevent 164")  # KEYCODE_APP_SWITCH
            return
        self._d.press(key)

    async def app_start(self, package: str) -> None:
        await self._run(self._d.app_start, package)

    async def app_stop(self, package: str) -> None:
        await self._run(self._d.app_stop, package)

    async def wait_text(self, text: str, timeout_s: int) -> bool:
        return bool(await self._run(self._wait_text_sync, text, timeout_s))

    def _wait_text_sync(self, text: str, timeout_s: int) -> bool:
        return self._d(text=text).wait(timeout=timeout_s)

    async def dismiss_popups(self) -> int:
        return await self._run(self._dismiss_popups_sync)

    def _dismiss_popups_sync(self) -> int:
        handled = 0
        for text in _POPUP_TEXTS:
            try:
                sel = self._d(text=text)
                if sel.exists:
                    sel.click()
                    handled += 1
            except Exception:
                continue
        return handled
