from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Mapping

from .constants import MODE_REAL, MODE_REDROID, MODES

_PACKAGE_RE = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$")


@dataclass(frozen=True)
class AppEntry:
    alias: str  # 暴露给模型
    package: str  # 安卓包名
    risk: str  # "low" | "high"


@dataclass(frozen=True)
class PhoneConfig:
    enabled: bool = False
    pause_all: bool = False
    mode: str = MODE_REDROID
    redroid_image: str = ""
    redroid_container: str = "companion-phone"
    redroid_adb_port: int = 26655
    redroid_data_path: str = ""
    redroid_extra_args: tuple[str, ...] = ()
    redroid_auto_boot: bool = True
    real_serial: str = ""
    real_wireless_addr: str = ""
    app_whitelist: tuple[AppEntry, ...] = ()
    action_max_per_turn: int = 8
    allow_high_risk: bool = False
    high_risk_keywords: tuple[str, ...] = ()
    task_max_steps: int = 12
    task_tool_timeout: int = 60
    humanize_delay: bool = True
    delay_ms_min: int = 300
    delay_ms_max: int = 900
    ui_tree_max_nodes: int = 60
    screenshot_keep: int = 50

    @classmethod
    def from_config(cls, config: Mapping[str, Any]) -> "PhoneConfig":
        """AstrBotConfig 继承自 Dict，按 Mapping 解析即可。"""
        return cls.from_mapping(config)

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "PhoneConfig":
        mode = str(data.get("MODE") or MODE_REDROID).strip().lower()
        if mode not in MODES:
            raise ValueError(f"MODE 必须是 {list(MODES)} 之一，当前为 {mode!r}")

        real_serial = str(data.get("REAL_SERIAL") or "").strip()
        real_wireless = str(data.get("REAL_WIRELESS_ADDR") or "").strip()
        if mode == MODE_REAL and not real_serial and not real_wireless:
            raise ValueError("真机模式需要配置 REAL_SERIAL 或 REAL_WIRELESS_ADDR")

        image = str(data.get("REDROID_IMAGE") or "").strip()
        data_path = str(data.get("REDROID_DATA_PATH") or "").strip()
        adb_port = _int(data.get("REDROID_ADB_PORT"), 26655)
        if mode == MODE_REDROID:
            if not image:
                raise ValueError("模拟器模式需要配置 REDROID_IMAGE")
            if not data_path:
                raise ValueError("模拟器模式需要配置 REDROID_DATA_PATH")
            if not 1024 <= adb_port <= 65535:
                raise ValueError("REDROID_ADB_PORT 必须在 1024-65535 之间")

        delay_min = _int(data.get("DELAY_MS_MIN"), 300)
        delay_max = _int(data.get("DELAY_MS_MAX"), 900)
        if delay_min > delay_max:
            raise ValueError("DELAY_MS_MIN 不能大于 DELAY_MS_MAX")

        return cls(
            enabled=bool(data.get("ENABLED", False)),
            pause_all=bool(data.get("PAUSE_ALL", False)),
            mode=mode,
            redroid_image=image,
            redroid_container=str(
                data.get("REDROID_CONTAINER") or "companion-phone"
            ).strip(),
            redroid_adb_port=adb_port,
            redroid_data_path=data_path,
            redroid_extra_args=tuple(
                str(a) for a in (data.get("REDROID_EXTRA_ARGS") or ()) if str(a).strip()
            ),
            redroid_auto_boot=bool(data.get("REDROID_AUTO_BOOT", True)),
            real_serial=real_serial,
            real_wireless_addr=real_wireless,
            app_whitelist=_parse_whitelist(data),
            action_max_per_turn=_int(data.get("ACTION_MAX_PER_TURN"), 8),
            allow_high_risk=bool(data.get("ALLOW_HIGH_RISK", False)),
            high_risk_keywords=tuple(
                str(k).strip()
                for k in (data.get("HIGH_RISK_KEYWORDS") or ())
                if str(k).strip()
            ),
            task_max_steps=_int(data.get("TASK_MAX_STEPS"), 12),
            task_tool_timeout=_int(data.get("TASK_TOOL_TIMEOUT"), 60),
            humanize_delay=bool(data.get("HUMANIZE_DELAY", True)),
            delay_ms_min=delay_min,
            delay_ms_max=delay_max,
            ui_tree_max_nodes=_int(data.get("UI_TREE_MAX_NODES"), 60),
            screenshot_keep=_int(data.get("SCREENSHOT_KEEP"), 50),
        )

    def app_by_alias(self, alias: str) -> AppEntry | None:
        alias = alias.strip().lower()
        for app in self.app_whitelist:
            if app.alias.lower() == alias:
                return app
        return None

    def app_by_package(self, package: str) -> AppEntry | None:
        for app in self.app_whitelist:
            if app.package == package:
                return app
        return None

    def alias_list(self) -> list[str]:
        return [app.alias for app in self.app_whitelist]


def _int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _parse_whitelist(data: Mapping[str, Any]) -> tuple[AppEntry, ...]:
    raw = data.get("APP_WHITELIST")
    if not raw:
        # 兼容 AstrBot < 4.10.4：JSON 字符串降级配置
        raw_json = str(data.get("APP_WHITELIST_JSON") or "").strip()
        if raw_json:
            try:
                raw = json.loads(raw_json)
            except json.JSONDecodeError as exc:
                raise ValueError("APP_WHITELIST_JSON 不是合法 JSON") from exc
    if not raw:
        return ()
    if not isinstance(raw, (list, tuple)):
        raise ValueError("APP_WHITELIST 应为列表（template_list）")

    entries: list[AppEntry] = []
    seen_alias: set[str] = set()
    for item in raw:
        if not isinstance(item, Mapping):
            raise ValueError("白名单条目应为对象")
        # template_list 会附加 __template_key，忽略之
        alias = str(item.get("alias") or "").strip()
        package = str(item.get("package") or "").strip()
        risk = str(item.get("risk") or "low").strip().lower()
        if not alias:
            raise ValueError("白名单条目缺少 alias")
        if alias.lower() in seen_alias:
            raise ValueError(f"白名单别名重复：{alias}")
        if not _PACKAGE_RE.match(package):
            raise ValueError(f"包名不合法：{package!r}（应形如 com.tencent.mm）")
        if risk not in ("low", "high"):
            risk = "low"
        seen_alias.add(alias.lower())
        entries.append(AppEntry(alias=alias, package=package, risk=risk))
    return tuple(entries)
