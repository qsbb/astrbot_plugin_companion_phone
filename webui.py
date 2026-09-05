from __future__ import annotations

import re
from typing import Any, Callable

from .config import PhoneConfig
from .constants import (
    E_UNKNOWN_ACTION,
    E_UNKNOWN_PANEL,
    PLUGIN_ID,
)
from .errors import PhoneError
from .log import logger
from .service import PhoneService

# 规范 §5.3：面板与动作 id 规则
_ID_RE = re.compile(r"^[a-z0-9_]{1,48}$")

PANELS: tuple[dict[str, str], ...] = (
    {
        "id": "phone_status",
        "title": "手机状态",
        "description": "设备模式、后端健康与当前前台应用",
    },
    {
        "id": "phone_apps",
        "title": "应用白名单",
        "description": "允许操作的应用别名、包名与风险等级",
    },
    {
        "id": "phone_audit",
        "title": "操作审计",
        "description": "最近的脱敏手机操作记录",
    },
)

# 渲染契约动作条目：confirm 为二次确认提示，payload_fields 为空表单
_STATUS_ACTIONS: tuple[dict[str, Any], ...] = (
    {
        "id": "reload",
        "title": "重建设备后端",
        "confirm": "切换模式后需要重建后端，确认执行？",
    },
    {
        "id": "pause",
        "title": "暂停全部动作",
        "confirm": "暂停后所有手机操作将被拒绝，确认？",
    },
    {"id": "resume", "title": "恢复动作", "confirm": "恢复后手机操作重新放行，确认？"},
)
_AUDIT_ACTIONS: tuple[dict[str, Any], ...] = (
    {"id": "clear", "title": "清空当日审计", "confirm": "仅清空今天的审计文件，确认？"},
)


class PhoneWebUI:
    """series.webui@1.0 面板三方法（规范 §5.3）。

    网关（核 webui_panels.py）以 _maybe_await_call 兼容同步/异步实现；
    此处统一 async def，写动作直接复用 service 的异步路径。
    数据走通用渲染契约：{success, title, description, columns, rows, actions}。
    """

    def __init__(self, service: PhoneService, config: Any) -> None:
        self._service = service
        self._config = config  # AstrBotConfig（dict 语义），pause/resume 直写

    # ---------- 契约 ----------
    async def webui_panels_contract(self) -> dict[str, Any]:
        return {
            "name": "series.webui@1.0",
            "plugin_id": PLUGIN_ID,
            "series_id": "ningxin_suxi",
            "panels": [dict(p) for p in PANELS],
        }

    async def webui_panel_data(self, panel: str) -> dict[str, Any]:
        if not isinstance(panel, str) or not _ID_RE.match(panel):
            raise PhoneError(E_UNKNOWN_PANEL, f"未知面板：{panel!r}")
        if panel == "phone_status":
            return await self._status_data()
        if panel == "phone_apps":
            return self._apps_data()
        if panel == "phone_audit":
            return self._audit_data()
        raise PhoneError(E_UNKNOWN_PANEL, f"未知面板：{panel!r}")

    async def webui_panel_action(
        self, panel: str, action: str, payload: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        if not isinstance(panel, str) or not _ID_RE.match(panel):
            raise PhoneError(E_UNKNOWN_PANEL, f"未知面板：{panel!r}")
        if not isinstance(action, str) or not _ID_RE.match(action):
            raise PhoneError(E_UNKNOWN_ACTION, f"未知动作：{action!r}")
        allowed = _ACTION_TABLE.get((panel, action))
        if allowed is None:
            raise PhoneError(E_UNKNOWN_ACTION, f"面板 {panel} 不支持动作：{action!r}")
        message = await allowed(self)
        return {"success": True, "message": message}

    # ---------- 动作实现 ----------
    async def _action_reload(self) -> str:
        result = await self._service.reset_backend()
        state = "就绪" if result.get("ready") else "未就绪（查看日志）"
        return f"设备后端已按模式 {result.get('mode')} 重建，当前状态：{state}"

    async def _action_pause(self) -> str:
        self._config["PAUSE_ALL"] = True
        self._config.save_config()
        logger.info("[companion-phone] actions paused via webui panel")
        return "已暂停全部手机动作。"

    async def _action_resume(self) -> str:
        self._config["PAUSE_ALL"] = False
        self._config.save_config()
        logger.info("[companion-phone] actions resumed via webui panel")
        return "已恢复手机动作。"

    async def _action_clear_audit(self) -> str:
        removed = self._service.audit_clear()
        return "当日审计已清空。" if removed else "当日没有可清空的审计文件。"

    # ---------- 数据渲染 ----------
    async def _status_data(self) -> dict[str, Any]:
        status = await self._service.status()
        cfg = PhoneConfig.from_mapping(self._config)
        current = status.get("current_app") or {}
        rows = [
            {"item": "插件启用", "value": "是" if status.get("enabled") else "否"},
            {"item": "动作暂停", "value": "是" if status.get("paused") else "否"},
            {"item": "设备模式", "value": str(status.get("mode", ""))},
            {"item": "后端就绪", "value": "是" if status.get("ready") else "否"},
            {"item": "前台应用", "value": current.get("package") or "（未知）"},
            {"item": "白名单应用数", "value": str(len(cfg.app_whitelist))},
            {"item": "高危放行", "value": "开启" if cfg.allow_high_risk else "关闭"},
        ]
        return self._render(
            "手机状态", "设备与安全策略概览", _ITEM_COLUMNS, rows, _STATUS_ACTIONS
        )

    def _apps_data(self) -> dict[str, Any]:
        cfg = PhoneConfig.from_mapping(self._config)
        rows = [
            {"alias": app.alias, "package": app.package, "risk": app.risk}
            for app in cfg.app_whitelist
        ]
        return self._render(
            "应用白名单", "别名不会暴露包名以外的信息给模型", _APP_COLUMNS, rows
        )

    def _audit_data(self) -> dict[str, Any]:
        rows = [
            {
                "ts": r.get("ts", ""),
                "outcome": r.get("outcome", ""),
                "action": r.get("action", ""),
                "error_code": r.get("error_code") or "—",
                "elapsed_ms": r.get("elapsed_ms", 0),
            }
            for r in self._service.audit_recent(50)
        ]
        return self._render(
            "操作审计",
            "最近 50 条脱敏记录（正文永不落盘）",
            _AUDIT_COLUMNS,
            rows,
            _AUDIT_ACTIONS,
        )

    @staticmethod
    def _render(
        title: str,
        description: str,
        columns: list[dict[str, str]],
        rows: list[dict[str, Any]],
        actions: tuple[dict[str, Any], ...] = (),
    ) -> dict[str, Any]:
        return {
            "success": True,
            "title": title,
            "description": description,
            "columns": columns,
            "rows": rows,
            "actions": [dict(a) for a in actions],
        }


_ITEM_COLUMNS = [{"key": "item", "label": "项目"}, {"key": "value", "label": "状态"}]
_APP_COLUMNS = [
    {"key": "alias", "label": "别名"},
    {"key": "package", "label": "包名"},
    {"key": "risk", "label": "风险等级"},
]
_AUDIT_COLUMNS = [
    {"key": "ts", "label": "时间(UTC)"},
    {"key": "outcome", "label": "结果"},
    {"key": "action", "label": "动作"},
    {"key": "error_code", "label": "错误码"},
    {"key": "elapsed_ms", "label": "耗时(ms)"},
]

_ACTION_TABLE: dict[tuple[str, str], Callable[["PhoneWebUI"], Any]] = {
    ("phone_status", "reload"): PhoneWebUI._action_reload,
    ("phone_status", "pause"): PhoneWebUI._action_pause,
    ("phone_status", "resume"): PhoneWebUI._action_resume,
    ("phone_audit", "clear"): PhoneWebUI._action_clear_audit,
}
