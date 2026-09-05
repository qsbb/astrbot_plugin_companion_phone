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
_CONNECT_TIMEOUT_SECONDS = 60.0

# 常见信息性弹窗的代点名单。
# 刻意排除：确定（语义中性，可能在支付/删除对话框代点确认）、
# 允许/始终允许（Android 运行时权限授权按钮，授权是不可逆动作，必须留给显式决策）。
_POPUP_TEXTS = ("我知道了", "稍后", "以后再说", "关闭广告")


def _u2_element_not_found() -> tuple[type, ...]:
    """u2 v3 的元素消失异常类型；不可用时返回空元组（不捕获）。"""
    try:
        from uiautomator2.exceptions import UiObjectNotFoundError

        return (UiObjectNotFoundError,)
    except Exception:
        return ()


class DeviceSession:
    """uiautomator2 封装：线程隔离 + 设备级互斥。

    uiautomator2/adbutils 均为同步 API：所有调用统一 asyncio.to_thread，
    单设备是串行资源，self._lock 保证动作不交错。
    u2 v3 没有可靠的进程内探活接口（2.x 的 d.alive 已移除）：
    连接只在 _d 为空时建立，操作失败时丢弃连接并重试一次。
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
            if self._d is None:
                await self._connect_locked()

    async def _connect_locked(self) -> None:
        state = await self._backend.ensure_ready()
        try:
            self._d = await asyncio.wait_for(
                asyncio.to_thread(self._connect_sync, state.adb_serial),
                timeout=_CONNECT_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            raise DeviceError(
                E_DEVICE_TIMEOUT,
                f"设备连接超时（{_CONNECT_TIMEOUT_SECONDS:.0f}s）",
            ) from None
        except Exception as exc:
            raise DeviceError(E_DEVICE_OFFLINE, f"设备连接失败：{exc}") from exc

    @staticmethod
    def _connect_sync(serial: str) -> Any:
        import uiautomator2 as u2  # 延迟导入；首次会向设备安装 atx-agent

        return u2.connect(serial)

    async def _run(
        self, fn: Callable[..., Any], *args: Any, retry: bool = True, **kwargs: Any
    ) -> Any:
        """在设备锁内执行同步函数；硬超时防挂起。

        retry=True（感知类）：失败丢弃连接、重连后重试一次；
        retry=False（写动作）：失败即报 device_offline——tap/input 等
        非幂等动作重放有双执行风险（第二轮盲测 F P3-2）。
        """
        async with self._lock:
            if self._closed:
                raise DeviceError(E_DEVICE_OFFLINE, "会话已关闭")
            if self._d is None:
                await self._connect_locked()
            try:
                return await self._execute(fn, *args, **kwargs)
            except DeviceError:
                raise
            except Exception:
                if not retry:
                    self._d = None
                    raise DeviceError(
                        E_DEVICE_OFFLINE, "设备操作失败，连接已重置；请重试"
                    ) from None
                # 连接可能已失效：丢弃并重连一次，仍失败才向外报错
                self._d = None
                await self._connect_locked()
                try:
                    return await self._execute(fn, *args, **kwargs)
                except DeviceError:
                    raise
                except Exception as exc:
                    raise DeviceError(E_DEVICE_OFFLINE, f"设备操作失败：{exc}") from exc

    async def _execute(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(fn, *args, **kwargs),
                timeout=_DEVICE_OP_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            # 超时说明连接可能已僵死：丢弃设备引用，下次操作强制重连。
            # 注意 asyncio.to_thread 无法中断：被放弃的线程可能仍在设备上完成动作。
            self._d = None
            raise DeviceError(
                E_DEVICE_TIMEOUT,
                f"设备操作超时（{_DEVICE_OP_TIMEOUT_SECONDS:.0f}s），请稍后重试",
            ) from None

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
        # 刻意不匹配负坐标：离屏/部分可见节点的 bounds 不可靠（如 [-50,0][100,100]），
        # 丢弃比给模型错误坐标更安全
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
        # 闭包在锁内求值 self._d：超时重置后不得裸解引用 None（第二轮盲测 F P2-1）
        await self._run(lambda: self._d.click(x, y), retry=False)

    async def click_text(self, text: str) -> list[int]:
        return await self._run(self._click_text_sync, text)

    def _click_text_sync(self, text: str) -> list[int]:
        sel = self._d(text=text)
        try:
            if not sel.exists:
                raise DeviceError(E_ELEMENT_NOT_FOUND, f"屏幕上没有找到文本：{text}")
            info = sel.info or {}
            sel.click()
        except _u2_element_not_found() as exc:
            # exists 与 click 之间元素消失
            raise DeviceError(
                E_ELEMENT_NOT_FOUND, f"屏幕上没有找到文本：{text}"
            ) from exc
        return self._normalize_bounds(info.get("bounds"))

    @staticmethod
    def _normalize_bounds(raw: Any) -> list[int]:
        """u2 的 selector.info["bounds"] 是 {left,top,right,bottom}；统一为 [x1,y1,x2,y2]。"""
        if isinstance(raw, dict):
            return [
                int(raw.get("left", 0)),
                int(raw.get("top", 0)),
                int(raw.get("right", 0)),
                int(raw.get("bottom", 0)),
            ]
        if isinstance(raw, (list, tuple)) and len(raw) == 4:
            return [int(v) for v in raw]
        return [0, 0, 0, 0]

    async def input_text(self, text: str, clear: bool) -> bool:
        """返回是否走了输入法回退（FastInputIME 不可用时由 u2 内部回退 set_text）。"""
        return await self._run(self._input_sync, text, clear, retry=False)

    def _input_sync(self, text: str, clear: bool) -> bool:
        ime_fallback = False
        try:
            # u2 v3：set_fastinput_ime 已弃用，官方推荐 set_input_ime
            try:
                self._d.set_input_ime(True)
            except AttributeError:
                self._d.set_fastinput_ime(True)
        except Exception:
            ime_fallback = True
        if clear:
            try:
                self._d.clear_text()
            except Exception:
                pass
        self._d.send_keys(text)
        return ime_fallback

    async def swipe(self, sx: int, sy: int, ex: int, ey: int, duration_ms: int) -> None:
        await self._run(
            lambda: self._d.swipe(sx, sy, ex, ey, duration_ms / 1000.0), retry=False
        )

    async def press_key(self, key: str) -> None:
        await self._run(self._press_key_sync, key)

    def _press_key_sync(self, key: str) -> None:
        # u2 press() 的官方键名是 "recent"（单数）；工具层对外别名保持 "recents"
        self._d.press("recent" if key == "recents" else key)

    async def app_start(self, package: str) -> None:
        await self._run(lambda: self._d.app_start(package), retry=False)

    async def app_stop(self, package: str) -> None:
        await self._run(lambda: self._d.app_stop(package), retry=False)

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
