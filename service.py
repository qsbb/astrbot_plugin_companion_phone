from __future__ import annotations

import asyncio
import random
import time
from pathlib import Path
from typing import Any, Callable

from .audit import AuditLog, mask_text
from .backend import create_backend
from .config import PhoneConfig
from .constants import (
    E_HIGH_RISK_BLOCKED,
    E_INPUT_TOO_LONG,
    E_INVALID_ARGUMENT,
    E_PAUSED,
    E_PLUGIN_DISABLED,
    KEY_NAMES,
    MODE_REDROID,
    SWIPE_DIRECTIONS,
)
from .device import DeviceSession
from .errors import PhoneError
from .log import logger
from .safety import SafetyGate

_INPUT_MAX_LENGTH = 500


class PhoneService:
    """业务编排：启停检查 → 预算 → 拟人延时 → 设备会话 → 审计。

    所有公开方法返回 dict；业务异常统一翻译为
    {"status":"error","error_code":...,"message":...}，工具层不再二次处理。
    """

    def __init__(
        self,
        cfg_provider: Callable[[], PhoneConfig],
        data_dir: Path,
        session_factory: Callable[[Any], DeviceSession] | None = None,
    ) -> None:
        self._cfg_provider = cfg_provider
        self._data_dir = Path(data_dir)
        self._audit = AuditLog(self._data_dir)
        self._session_factory = session_factory or DeviceSession
        self._safety = SafetyGate(cfg_provider())
        self._backend: Any = None
        self._session: DeviceSession | None = None
        self._mode: str | None = None
        self._terminated = False

    # ---------- 内部 ----------
    def _cfg(self) -> PhoneConfig:
        return self._cfg_provider()

    def _ensure_active(self) -> PhoneConfig:
        if self._terminated:
            raise PhoneError(E_PLUGIN_DISABLED, "手机插件正在停止")
        cfg = self._cfg()
        if not cfg.enabled:
            raise PhoneError(E_PLUGIN_DISABLED, "手机功能未启用")
        if cfg.pause_all:
            raise PhoneError(E_PAUSED, "手机动作已被管理员暂停")
        return cfg

    async def _get_session(self, cfg: PhoneConfig) -> DeviceSession:
        """懒加载单例；MODE 变更后自动重建（/phone reload 或配置热更新）。"""
        if self._session is not None and self._mode == cfg.mode:
            return self._session
        await self._close_session()
        self._backend = create_backend(cfg)
        self._session = self._session_factory(self._backend)
        self._mode = cfg.mode
        try:
            await self._session.connect()
        except Exception:
            await self._close_session()
            raise
        return self._session

    async def _close_session(self) -> None:
        if self._session is not None:
            try:
                await self._session.close()
            except Exception:
                pass
        self._session = None
        self._backend = None
        self._mode = None

    async def _audit_async(
        self,
        umo: str,
        cfg: PhoneConfig,
        action: str,
        params: dict,
        outcome: str,
        error_code: str,
        started: float,
    ) -> None:
        elapsed = int((time.monotonic() - started) * 1000)
        await asyncio.to_thread(
            self._audit.record,
            umo=umo,
            mode=cfg.mode,
            action=action,
            params=params,
            outcome=outcome,
            error_code=error_code,
            elapsed_ms=elapsed,
        )

    async def _do(
        self,
        umo: str,
        action: str,
        params: dict,
        fn: Callable[[DeviceSession], Any],
        *,
        consume_budget: bool = True,
    ) -> dict:
        started = time.monotonic()
        try:
            cfg = self._ensure_active()
            self._safety.update_cfg(cfg)
            if consume_budget:
                self._safety.budget_consume(umo)
            session = await self._get_session(cfg)
            if cfg.humanize_delay and consume_budget:
                await asyncio.sleep(
                    random.uniform(cfg.delay_ms_min, cfg.delay_ms_max) / 1000.0
                )
            result = await fn(session)
        except PhoneError as exc:
            await self._audit_async(
                umo, self._cfg(), action, params, "error", exc.code, started
            )
            return exc.public_dict(action)
        await self._audit_async(umo, cfg, action, params, "ok", "", started)
        payload: dict[str, Any] = {"status": "ok", "action": action}
        if isinstance(result, dict):
            payload.update(result)
        return payload

    async def _take_screenshot(self, session: DeviceSession, cfg: PhoneConfig) -> Path:
        shots = self._data_dir / "screenshots"
        path = (
            shots / f"{time.strftime('%Y%m%d-%H%M%S')}-{random.randint(1000, 9999)}.png"
        )
        await session.screenshot(path)
        await asyncio.to_thread(self._prune_screenshots, shots, cfg.screenshot_keep)
        return path

    @staticmethod
    def _prune_screenshots(directory: Path, keep: int) -> None:
        try:
            files = sorted(directory.glob("*.png"))
            for old in files[: max(0, len(files) - keep)]:
                old.unlink(missing_ok=True)
        except OSError:
            pass

    # ---------- 感知（只读，不消耗预算） ----------
    async def status(self) -> dict:
        cfg = self._cfg()
        payload: dict[str, Any] = {
            "status": "ok",
            "action": "status",
            "enabled": cfg.enabled,
            "paused": cfg.pause_all,
            "mode": cfg.mode,
            "whitelist_size": len(cfg.app_whitelist),
        }
        if self._backend is not None:
            payload["backend"] = self._backend.describe()
            state = await self._backend.health()
            payload["ready"] = state.ready
        else:
            payload["backend"] = {"mode": cfg.mode, "note": "未初始化"}
            payload["ready"] = False
        if payload["ready"] and self._session is not None:
            try:
                payload["current_app"] = await self._session.current_app()
            except Exception:
                pass
        return payload

    async def screen(self) -> dict:
        started = time.monotonic()
        cfg = self._ensure_active()
        self._safety.update_cfg(cfg)
        try:
            session = await self._get_session(cfg)
            await session.dismiss_popups()  # 弹窗会遮挡控件树，先清理信息性弹窗
            current = await session.current_app()
            size = await session.screen_size()
            nodes = await session.ui_tree(cfg.ui_tree_max_nodes)
            shot = await self._take_screenshot(session, cfg)
        except PhoneError as exc:
            await self._audit_async("", cfg, "screen", {}, "error", exc.code, started)
            return exc.public_dict("screen")
        await self._audit_async(
            "", cfg, "screen", {"nodes": len(nodes)}, "ok", "", started
        )
        return {
            "status": "ok",
            "action": "screen",
            "current_app": current,
            "screen_size": size,
            "nodes": nodes,
            "screenshot": str(shot),
        }

    # ---------- 操作 ----------
    async def tap(self, umo: str, x: int, y: int) -> dict:
        async def _act(session: DeviceSession) -> dict:
            size = await session.screen_size()
            self._safety.check_tap_xy(int(x), int(y), size)
            await session.tap(int(x), int(y))
            return {}

        return await self._do(umo, "tap", {"xy": [int(x), int(y)]}, _act)

    async def click_text(self, umo: str, text: str) -> dict:
        async def _act(session: DeviceSession) -> dict:
            current = await session.current_app()
            app_entry = self._safety.app_entry_for_package(current.get("package", ""))
            self._safety.check_tap_text(text, app_entry)
            bounds = await session.click_text(text)
            return {"text": text, "bounds": bounds}

        return await self._do(umo, "click_text", {"text": text[:32]}, _act)

    async def input_text(self, umo: str, text: str, clear: bool) -> dict:
        async def _act(session: DeviceSession) -> dict:
            if len(text) > _INPUT_MAX_LENGTH:
                raise PhoneError(
                    E_INPUT_TOO_LONG, f"输入文本超过 {_INPUT_MAX_LENGTH} 字上限"
                )
            fallback = await session.input_text(text, clear)
            return {"ascii_fallback": fallback}

        return await self._do(
            umo,
            "input_text",
            {"text_len": len(text), "text_head": mask_text(text)},
            _act,
        )

    async def swipe(self, umo: str, direction: str, distance: int) -> dict:
        if direction not in SWIPE_DIRECTIONS:
            return PhoneError(
                E_INVALID_ARGUMENT, f"direction 必须是 {list(SWIPE_DIRECTIONS)} 之一"
            ).public_dict("swipe")

        async def _act(session: DeviceSession) -> dict:
            w, h = await session.screen_size()
            cx, cy = w // 2, h // 2
            d = max(100, min(int(distance), 2000)) // 2

            def jitter() -> int:
                return random.randint(-3, 3)  # 拟人坐标抖动

            table = {
                "up": ((cx + jitter(), cy + d), (cx + jitter(), cy - d)),
                "down": ((cx + jitter(), cy - d), (cx + jitter(), cy + d)),
                "left": ((cx + d, cy + jitter()), (cx - d, cy + jitter())),
                "right": ((cx - d, cy + jitter()), (cx + d, cy + jitter())),
            }
            (sx, sy), (ex, ey) = table[direction]
            await session.swipe(sx, sy, ex, ey, random.randint(250, 450))
            return {}

        return await self._do(
            umo, "swipe", {"direction": direction, "distance": int(distance)}, _act
        )

    async def press_key(self, umo: str, key: str) -> dict:
        if key not in KEY_NAMES:
            return PhoneError(
                E_INVALID_ARGUMENT, f"key 必须是 {list(KEY_NAMES)} 之一"
            ).public_dict("press_key")

        async def _act(session: DeviceSession) -> dict:
            await session.press_key(key)
            return {}

        return await self._do(umo, "press_key", {"key": key}, _act)

    async def launch_app(self, umo: str, alias: str) -> dict:
        async def _act(session: DeviceSession) -> dict:
            entry = self._safety.check_app(alias)
            # 入口门控（v2 安全模型核心）：高危应用默认禁止进入，
            # 这是唯一不可绕过的拦截位置——进入后再拦 tap 坐标是拦不住的。
            if entry.risk == "high" and not self._cfg().allow_high_risk:
                raise PhoneError(
                    E_HIGH_RISK_BLOCKED,
                    f"应用 {entry.alias} 属于高风险应用，默认禁止进入；"
                    "如需放行请管理员开启 ALLOW_HIGH_RISK",
                )
            await session.app_start(entry.package)
            await asyncio.sleep(2)  # 等待启动动画
            await session.dismiss_popups()  # 首启常见权限/引导弹窗
            current = await session.current_app()
            return {
                "alias": entry.alias,
                "package": entry.package,
                "current": current.get("package", ""),
            }

        return await self._do(umo, "launch_app", {"alias": alias}, _act)

    async def wait_element(self, umo: str, text: str, timeout_s: int) -> dict:
        timeout_s = max(1, min(int(timeout_s), 30))

        async def _act(session: DeviceSession) -> dict:
            found = await session.wait_text(text, timeout_s)
            return {"found": found}

        return await self._do(
            umo, "wait_element", {"text": text[:32]}, _act, consume_budget=False
        )

    # ---------- 任务预算（/phone task 用） ----------
    def task_budget_start(self, umo: str) -> None:
        self._safety.task_budget_start(umo, self._cfg().task_max_steps)

    def task_budget_stop(self, umo: str) -> None:
        self._safety.task_budget_stop(umo)

    # ---------- 管理 ----------
    async def screenshot_file(self) -> Path:
        cfg = self._ensure_active()
        session = await self._get_session(cfg)
        return await self._take_screenshot(session, cfg)

    def audit_recent(self, limit: int = 50) -> list[dict]:
        return self._audit.recent(limit)

    def audit_clear(self) -> bool:
        return self._audit.clear_today()

    async def reset_backend(self) -> dict:
        await self._close_session()
        cfg = self._cfg()
        ready = False
        if cfg.enabled:
            try:
                await self._get_session(cfg)
                ready = True
            except Exception as exc:
                logger.warning(f"companion_phone 后端重建失败：{exc}")
        return {"status": "ok", "action": "reload", "mode": cfg.mode, "ready": ready}

    async def warm_up(self) -> None:
        """AstrBot 就绪后的后台预热：拉起容器并建立连接，失败只记日志。"""
        cfg = self._cfg()
        if not cfg.enabled:
            return
        if cfg.mode == MODE_REDROID and not cfg.redroid_auto_boot:
            return
        try:
            await self._get_session(cfg)
        except Exception as exc:
            logger.warning(f"companion_phone 预热失败：{exc}")

    async def close(self, *, stop_device: bool = False) -> None:
        """stop_device=False（默认）：插件卸载/重载不杀容器，重连即恢复。"""
        self._terminated = True
        session, backend = self._session, self._backend
        if session is not None:
            try:
                await session.close()
            except Exception:
                pass
        if backend is not None:
            try:
                await backend.shutdown(stop_device=stop_device)
            except Exception:
                pass
        self._session = None
        self._backend = None
        self._mode = None
