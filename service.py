from __future__ import annotations

import asyncio
import random
import time
from pathlib import Path
from typing import Any, Callable

from .audit import AuditLog
from .backend import create_backend
from .config import PhoneConfig
from .constants import (
    E_DEVICE_OFFLINE,
    E_HIGH_RISK_BLOCKED,
    E_INPUT_TOO_LONG,
    E_INTERNAL,
    E_INVALID_ARGUMENT,
    E_PAUSED,
    E_PLUGIN_DISABLED,
    E_SESSION_NOT_ALLOWED,
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
    """业务编排：启停检查 → 会话 → 预算 → 拟人延时 → 设备会话 → 审计。

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
        self._session_lock = asyncio.Lock()

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

    def check_session_allowed(self, event: Any) -> dict | None:
        """工具会话门控（安全层）：None=放行，否则返回错误 dict。

        - all：不限制；
        - private（默认）：仅私聊/WebChat 可用，群聊拒绝——群成员无法经提示注入驱动手机；
        - allowlist：仅 TOOL_ALLOWLIST 中的 unified_msg_origin 可用。
        """
        cfg = self._cfg()
        if cfg.tool_chat_scope == "all":
            return None
        try:
            umo = str(event.unified_msg_origin or "")
            is_group = bool(event.get_group_id())
        except Exception:
            # 事件存在但字段异常 → fail-closed（规范总则 #4）
            return PhoneError(
                E_SESSION_NOT_ALLOWED, "无法解析当前会话，手机工具被拒绝"
            ).public_dict("session")
        if cfg.tool_chat_scope == "private":
            if is_group:
                return PhoneError(
                    E_SESSION_NOT_ALLOWED,
                    "手机工具仅在私聊会话可用；如需群聊使用请管理员调整 TOOL_CHAT_SCOPE",
                ).public_dict("session")
            return None
        if umo in cfg.tool_allowlist:
            return None
        return PhoneError(
            E_SESSION_NOT_ALLOWED, "当前会话不在工具允许列表（TOOL_ALLOWLIST）"
        ).public_dict("session")

    async def _get_session(self, cfg: PhoneConfig) -> DeviceSession:
        """懒加载单例；MODE 变更后自动重建（/phone reload 或配置热更新）。"""
        async with self._session_lock:
            return await self._get_session_locked(cfg)

    async def _get_session_locked(self, cfg: PhoneConfig) -> DeviceSession:
        """内部版本：调用方必须已持有 _session_lock（asyncio.Lock 不可重入）。"""
        if self._session is not None and self._mode == cfg.mode:
            return self._session
        await self._close_session()
        self._backend = create_backend(cfg)
        self._session = self._session_factory(self._backend)
        self._mode = cfg.mode
        try:
            await self._session.connect()
        except PhoneError:
            await self._close_session()
            raise
        except Exception as exc:
            # 非预期连接异常归一为 device_offline，避免 RuntimeError 穿透工具层
            await self._close_session()
            raise PhoneError(E_DEVICE_OFFLINE, f"设备连接失败：{exc}") from exc
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
            session = await self._get_session(cfg)
            # 预算在连接建立之后扣减：设备离线时不白烧配额
            if consume_budget:
                self._safety.budget_consume(umo)
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
        except Exception:
            # 非预期异常也必须落审计（规范总则 #5），并归一为 internal_error
            logger.exception("[companion-phone] unexpected error in action %s", action)
            await self._audit_async(
                umo, self._cfg(), action, params, "error", E_INTERNAL, started
            )
            return PhoneError(E_INTERNAL, "内部错误，请管理员查看日志").public_dict(
                action
            )
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
    async def status(self, verbose: bool = False) -> dict:
        """verbose=False（LLM 工具）：裁剪基础设施细节，不向模型暴露容器/镜像/端口。"""
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
            if verbose:
                payload["backend"] = self._backend.describe()
            state = await self._backend.health()
            payload["ready"] = state.ready
        else:
            payload["ready"] = False
        if payload["ready"] and self._session is not None:
            try:
                payload["current_app"] = await self._session.current_app()
            except Exception:
                pass
        return payload

    def screen_vision_enabled(self) -> bool:
        """R2 视觉兜底开关（SCREEN_VISION，默认关闭）。"""
        return self._cfg().screen_vision

    def load_screenshot(self, path: str | Path) -> bytes | None:
        """读取并压缩截图（≤720px JPEG；Pillow 不可用时回退原始 PNG）。"""
        try:
            data = Path(path).read_bytes()
        except OSError:
            return None
        try:
            import io

            from PIL import Image

            img = Image.open(io.BytesIO(data)).convert("RGB")
            w, h = img.size
            max_w = 720
            if w > max_w:
                img = img.resize((max_w, max(1, int(h * max_w / w))))
            buf = io.BytesIO()
            img.save(buf, "JPEG", quality=70)
            return buf.getvalue()
        except Exception:
            return data

    async def screen(self, umo: str = "") -> dict:
        started = time.monotonic()
        cfg = self._ensure_active()
        self._safety.update_cfg(cfg)
        try:
            session = await self._get_session(cfg)
            current = await session.current_app()
            popups = 0
            # 代点只在白名单 low 前台执行：高危/未知前台不自动点任何东西
            entry = self._safety.app_entry_for_package(current.get("package", ""))
            if entry is not None and entry.risk == "low":
                popups = await session.dismiss_popups()
            size = await session.screen_size()
            nodes = await session.ui_tree(cfg.ui_tree_max_nodes)
            # 截图存盘供管理员（/phone shot）、审计与 R2 视觉兜底；
            # 路径由工具层消费，永远不进入模型可见文本
            shot = await self._take_screenshot(session, cfg)
        except PhoneError as exc:
            await self._audit_async("", cfg, "screen", {}, "error", exc.code, started)
            return exc.public_dict("screen")
        await self._audit_async(
            umo,
            cfg,
            "screen",
            {"nodes": len(nodes), "popups": popups},
            "ok",
            "",
            started,
        )
        return {
            "status": "ok",
            "action": "screen",
            "current_app": current,
            "screen_size": size,
            "nodes": nodes,
            "screenshot_path": str(shot),
        }

    # ---------- 操作 ----------
    async def tap(self, umo: str, x: int, y: int) -> dict:
        async def _act(session: DeviceSession) -> dict:
            size = await session.screen_size()
            self._safety.check_tap_xy(int(x), int(y), size)
            self._safety.check_current_app(
                (await session.current_app()).get("package", "")
            )
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
            self._safety.check_current_app(
                (await session.current_app()).get("package", "")
            )
            fallback = await session.input_text(text, clear)
            return {"ime_fallback": fallback}

        return await self._do(
            umo,
            "input_text",
            {"text_len": len(text)},  # 输入正文不落任何片段（含验证码类短文本）
            _act,
        )

    async def swipe(self, umo: str, direction: str, distance: int) -> dict:
        if direction not in SWIPE_DIRECTIONS:
            return PhoneError(
                E_INVALID_ARGUMENT, f"direction 必须是 {list(SWIPE_DIRECTIONS)} 之一"
            ).public_dict("swipe")

        async def _act(session: DeviceSession) -> dict:
            w, h = await session.screen_size()
            self._safety.check_current_app(
                (await session.current_app()).get("package", "")
            )
            cx, cy = w // 2, h // 2
            d = max(100, min(int(distance), 2000)) // 2
            # 分轴收口（第二轮盲测 F P3-3）：垂直滑动按屏高、水平按屏宽钳制
            if direction in ("up", "down"):
                d = max(1, min(d, cy - 1))
            else:
                d = max(1, min(d, cx - 1))

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

    # 按键分治（安全模型 v4 第三层）：导航键豁免（脱困通道），确认键必须过门控
    _NAVIGATION_KEYS = frozenset({"back", "home", "recents"})

    async def press_key(self, umo: str, key: str) -> dict:
        if key not in KEY_NAMES:
            return PhoneError(
                E_INVALID_ARGUMENT, f"key 必须是 {list(KEY_NAMES)} 之一"
            ).public_dict("press_key")

        async def _act(session: DeviceSession) -> dict:
            if key not in self._NAVIGATION_KEYS:
                # enter 在聊天输入框即「发送」、del 可清空内容——必须过前台应用门控
                self._safety.check_current_app(
                    (await session.current_app()).get("package", "")
                )
            await session.press_key(key)
            return {}

        return await self._do(umo, "press_key", {"key": key}, _act)

    async def launch_app(self, umo: str, alias: str) -> dict:
        async def _act(session: DeviceSession) -> dict:
            entry = self._safety.check_app(alias)
            # 入口门控（双层安全模型第一层）：高危应用默认禁止经 launch 进入；
            # 即便经桌面图标/深链等路径进入，动作级门控（第二层）仍会拦截其内操作。
            if entry.risk == "high" and not self._cfg().allow_high_risk:
                raise PhoneError(
                    E_HIGH_RISK_BLOCKED,
                    f"应用 {entry.alias} 属于高风险应用，默认禁止进入；"
                    "如需放行请管理员开启 ALLOW_HIGH_RISK",
                )
            await session.app_start(entry.package)
            await asyncio.sleep(2)  # 等待启动动画
            await session.dismiss_popups()  # 首启常见引导弹窗（不含权限授权按钮）
            current = await session.current_app()
            return {
                "alias": entry.alias,
                "package": entry.package,
                "current": current.get("package", ""),
            }

        return await self._do(umo, "launch_app", {"alias": alias}, _act)

    async def wait_element(self, umo: str, text: str, timeout_s: int) -> dict:
        try:
            timeout_s = max(1, min(int(timeout_s), 30))
        except (TypeError, ValueError):
            return PhoneError(
                E_INVALID_ARGUMENT, "timeout_seconds 不是数字"
            ).public_dict("wait_element")

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
        # 持会话锁防止与在途操作交错；内部走 _get_session_locked 避免锁重入死锁
        async with self._session_lock:
            await self._close_session()
            cfg = self._cfg()
            ready = False
            if cfg.enabled:
                try:
                    await self._get_session_locked(cfg)
                    ready = True
                except Exception as exc:
                    logger.warning(f"[companion-phone] backend rebuild failed: {exc}")
        return {"status": "ok", "action": "reload", "mode": cfg.mode, "ready": ready}

    async def warm_up(self) -> None:
        """AstrBot 就绪后的后台预热：拉起容器并建立连接，失败只记日志。"""
        try:
            cfg = self._cfg()
            if not cfg.enabled:
                return
            if cfg.mode == MODE_REDROID and not cfg.redroid_auto_boot:
                return
            await self._get_session(cfg)
        except Exception as exc:
            logger.warning(f"[companion-phone] warm-up failed: {exc}")

    async def close(self, *, stop_device: bool = False) -> None:
        """stop_device=False（默认）：插件卸载/重载不杀容器，重连即恢复。"""
        self._terminated = True
        async with self._session_lock:
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
