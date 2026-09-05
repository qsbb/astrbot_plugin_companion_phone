from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from astrbot.api import AstrBotConfig
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, StarTools, register

from .agent import run_phone_task
from .config import PhoneConfig
from .constants import (
    PLUGIN_ID,
    PLUGIN_REPOSITORY,
    PLUGIN_VERSION,
    TOOL_NAMES,
)
from .log import logger
from .service import PhoneService
from .series_diagnostics import (
    diagnostic_clear as clear_diagnostic_events,
)
from .series_diagnostics import (
    diagnostic_event,
    diagnostic_events as read_diagnostic_events,
)
from .tools import create_device_tools
from .webui import PhoneWebUI

__version__ = PLUGIN_VERSION  # 规范 §10：与 metadata.yaml version 同步，测试断言

try:
    # 数据目录：master 验证的 StarTools.get_data_dir（data/plugin_data/<plugin_id>）
    _DATA_DIR: Path = StarTools.get_data_dir(PLUGIN_ID)
except Exception:  # 独立测试环境回退
    _DATA_DIR = Path(".") / "plugin_data" / PLUGIN_ID


@register(
    PLUGIN_ID,
    "凌溪",
    "凝心溯溪系列通模块：真机或模拟器双模式的安卓手机操作，读屏、点按、输入、"
    "滑动、启动应用；含白名单、高危入口门控、动作预算与审计。",
    PLUGIN_VERSION,
    PLUGIN_REPOSITORY,
)
class CompanionPhonePlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig) -> None:
        super().__init__(context)
        self.context = context
        self.config = config
        self.service = PhoneService(lambda: PhoneConfig.from_config(config), _DATA_DIR)
        self._tools = create_device_tools(self.service)
        self.context.add_llm_tools(*self._tools)  # 官方 API，>= v4.5.1
        self._webui = PhoneWebUI(self.service, config)
        self._warm_task: asyncio.Task | None = None
        logger.info(
            f"[companion-phone] loaded, {len(self._tools)}/{len(TOOL_NAMES)} tools registered"
        )
        diagnostic_event(
            "plugin.ready",
            "插件初始化完成",
            details={
                "tool_count": len(self._tools),
                "enabled": bool(config.get("ENABLED")),
            },
        )

    def _cfg(self) -> PhoneConfig:
        return PhoneConfig.from_config(self.config)

    # ---------- series.diagnostics@1.0（规范 §5.1 必选契约） ----------
    def diagnostic_log_contract(self) -> dict[str, Any]:
        return {
            "name": "series.diagnostics",
            "version": "1.0",
            "series_id": "ningxin_suxi",
            "plugin_id": PLUGIN_ID,
            "plugin_name": "通",
            "capabilities": ("read", "clear", "read_events", "clear_events"),
            "storage": "memory_only",
            "astrbot_log_propagation": False,
        }

    def diagnostic_events(self, after_seq: int = 0, limit: int = 200) -> dict[str, Any]:
        return read_diagnostic_events(after_seq=after_seq, limit=limit)

    def diagnostic_clear(self) -> None:
        clear_diagnostic_events()

    # ---------- series.webui@1.0 面板（规范 §5.3，由核 WebUI 统一接管） ----------
    async def webui_panels_contract(self) -> dict[str, Any]:
        return await self._webui.webui_panels_contract()

    async def webui_panel_data(self, panel: str) -> dict[str, Any]:
        return await self._webui.webui_panel_data(panel)

    async def webui_panel_action(
        self, panel: str, action: str, payload: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        return await self._webui.webui_panel_action(panel, action, payload)

    @filter.on_astrbot_loaded()
    async def on_astrbot_loaded(self):
        """AstrBot 就绪后后台预热：拉起容器并建立连接，失败只记日志。"""
        if self._cfg().enabled:
            self._warm_task = asyncio.create_task(self.service.warm_up())

    # ---------- /phone 管理指令组（管理员） ----------
    @filter.command_group("phone")
    def phone_group(self):
        """伴身手机管理"""

    @phone_group.command("status")
    @filter.permission_type(filter.PermissionType.ADMIN)
    async def phone_status(self, event: AstrMessageEvent):
        """查看设备与插件状态"""
        result = await self.service.status()
        yield event.plain_result(_fmt(result))

    @phone_group.command("reload")
    @filter.permission_type(filter.PermissionType.ADMIN)
    async def phone_reload(self, event: AstrMessageEvent):
        """按当前配置重建设备后端（切换 MODE 后执行）"""
        result = await self.service.reset_backend()
        yield event.plain_result(_fmt(result))

    @phone_group.command("shot")
    @filter.permission_type(filter.PermissionType.ADMIN)
    async def phone_shot(self, event: AstrMessageEvent):
        """抓取当前屏幕截图并发回"""
        try:
            path = await self.service.screenshot_file()
        except Exception as exc:
            yield event.plain_result(f"截图失败：{exc}")
            return
        yield event.image_result(str(path))

    @phone_group.command("apps")
    @filter.permission_type(filter.PermissionType.ADMIN)
    async def phone_apps(self, event: AstrMessageEvent):
        """列出应用白名单"""
        cfg = self._cfg()
        if not cfg.app_whitelist:
            yield event.plain_result(
                "白名单为空，请在插件配置 APP_WHITELIST 中添加应用。"
            )
            return
        lines = [
            f"- {app.alias} → {app.package}（risk={app.risk}）"
            for app in cfg.app_whitelist
        ]
        yield event.plain_result("\n".join(lines))

    @phone_group.command("task", alias={"do"})
    @filter.permission_type(filter.PermissionType.ADMIN)
    async def phone_task(self, event: AstrMessageEvent):
        """执行多步手机任务：/phone task <要做的事>"""
        parts = event.message_str.strip().split(maxsplit=2)
        goal = parts[2] if len(parts) >= 3 else ""
        if not goal:
            yield event.plain_result(
                "用法：/phone task <要做的事>，例如 /phone task 打开browser搜索天气"
            )
            return
        cfg = self._cfg()
        if not cfg.enabled:
            yield event.plain_result("手机插件未启用（ENABLED=false）")
            return
        yield event.plain_result(
            f"好的，开始尝试：{goal}（最多 {cfg.task_max_steps} 步）"
        )
        try:
            resp = await run_phone_task(self.service, self.context, event, goal, cfg)
            yield event.plain_result(resp.completion_text or "任务已结束（无总结）")
        except Exception as exc:
            logger.exception("[companion-phone] phone task failed")
            yield event.plain_result(f"任务执行失败：{exc}")

    @phone_group.command("audit")
    @filter.permission_type(filter.PermissionType.ADMIN)
    async def phone_audit(self, event: AstrMessageEvent):
        """查看最近 20 条脱敏审计记录"""
        records = self.service.audit_recent(20)
        if not records:
            yield event.plain_result("暂无审计记录。")
            return
        lines = []
        for r in records:
            line = (
                f"{r.get('ts')} [{r.get('outcome')}] {r.get('action')} "
                f"{json.dumps(r.get('params'), ensure_ascii=False)}"
            )
            if r.get("error_code"):
                line += f" ({r.get('error_code')})"
            lines.append(line)
        yield event.plain_result("\n".join(lines))

    @phone_group.command("pause")
    @filter.permission_type(filter.PermissionType.ADMIN)
    async def phone_pause(self, event: AstrMessageEvent):
        """暂停全部手机动作"""
        self.config["PAUSE_ALL"] = True
        self.config.save_config()
        yield event.plain_result("已暂停全部手机动作。")

    @phone_group.command("resume")
    @filter.permission_type(filter.PermissionType.ADMIN)
    async def phone_resume(self, event: AstrMessageEvent):
        """恢复手机动作"""
        self.config["PAUSE_ALL"] = False
        self.config.save_config()
        yield event.plain_result("已恢复手机动作。")

    async def terminate(self) -> None:
        """规范 §3.3：清理全部运行时资源；模块级状态置空。

        动态注册的 LLM 工具显式注销（unregister_llm_tool 虽被 master 标注
        deprecated，但注销行为有效，系列现役插件同款用法）。
        默认 stop_device=False：插件重载不杀容器，重连即恢复。
        """
        if self._warm_task is not None:
            self._warm_task.cancel()
            try:
                await self._warm_task
            except asyncio.CancelledError:
                pass
            except Exception:
                pass
            self._warm_task = None
        await self.service.close(stop_device=False)
        for name in TOOL_NAMES:
            try:
                self.context.unregister_llm_tool(name)
            except Exception:
                pass
        diagnostic_event("plugin.terminated", "插件已卸载，设备会话与工具已回收")


def _fmt(data: dict) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2)
