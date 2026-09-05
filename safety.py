from __future__ import annotations

import time

from .config import AppEntry, PhoneConfig
from .constants import (
    E_APP_NOT_ALLOWED,
    E_BUDGET_EXCEEDED,
    E_HIGH_RISK_BLOCKED,
    E_OUT_OF_BOUNDS,
)
from .errors import SafetyError

# 常规对话动作预算的滑动窗口：不依赖“新一轮”信号，近似单轮语义
_WINDOW_SECONDS = 300.0


class SafetyGate:
    """白名单 / 高危拦截 / 动作预算。配置热更新通过 update_cfg 注入。"""

    def __init__(self, cfg: PhoneConfig) -> None:
        self._cfg = cfg
        self._window: dict[str, list[float]] = {}
        self._task_budget: dict[str, int] = {}

    def update_cfg(self, cfg: PhoneConfig) -> None:
        self._cfg = cfg

    # ---------- 白名单 ----------
    def check_app(self, alias: str) -> AppEntry:
        entry = self._cfg.app_by_alias(alias)
        if entry is None:
            allowed = "、".join(self._cfg.alias_list()) or "（白名单为空）"
            raise SafetyError(
                E_APP_NOT_ALLOWED,
                f"应用 {alias} 不在允许列表。允许的别名：{allowed}",
            )
        return entry

    def app_entry_for_package(self, package: str) -> AppEntry | None:
        if not package:
            return None
        return self._cfg.app_by_package(package)

    # ---------- 高危 ----------
    def check_tap_text(self, text: str, current_app: AppEntry | None) -> None:
        """高危判定（满足其一且未 ALLOW_HIGH_RISK 即拦截）：
        1) 当前前台应用 risk=high；
        2) 目标文本命中 HIGH_RISK_KEYWORDS。"""
        if self._cfg.allow_high_risk:
            return
        if current_app is not None and current_app.risk == "high":
            raise SafetyError(
                E_HIGH_RISK_BLOCKED,
                f"当前应用 {current_app.alias} 是高危应用，操作被安全策略拦截；"
                "如需放行请管理员开启 ALLOW_HIGH_RISK",
            )
        for kw in self._cfg.high_risk_keywords:
            if kw and kw in text:
                raise SafetyError(
                    E_HIGH_RISK_BLOCKED,
                    f"目标文本命中高危关键词「{kw}」，动作被安全策略拦截；"
                    "如需放行请管理员开启 ALLOW_HIGH_RISK",
                )

    def check_tap_xy(self, x: int, y: int, size) -> None:
        w, h = int(size[0]), int(size[1])
        if w <= 0 or h <= 0:
            # fail-closed：读不到屏幕尺寸时拒绝点按，而不是放行任意坐标
            raise SafetyError(
                E_OUT_OF_BOUNDS, "无法读取屏幕尺寸，动作被拦截；请重新调用 screen"
            )
        if not (0 <= x < w and 0 <= y < h):
            raise SafetyError(
                E_OUT_OF_BOUNDS, f"坐标 ({x},{y}) 超出屏幕 {w}x{h}，请重新读屏"
            )

    # ---------- 动作级前台应用门控（安全模型 v3 第二层） ----------
    def check_current_app(self, package: str) -> AppEntry | None:
        """对 tap/input_text/swipe/enter 等无文本动作的前台应用检查。

        白名单即操作边界（默认拒绝）：
        - 白名单内 risk=high 且未 ALLOW_HIGH_RISK → 拦截；
        - 白名单内 risk=low → 放行；
        - 白名单外（含空包名）→ 一律拦截：桌面/系统应用之外的任何非白名单前台
          （短信、银行、权限对话框等）都没有已授予的操作权；
          错误信息指引管理员将其加入 APP_WHITELIST。
        """
        entry = self.app_entry_for_package(package)
        if entry is not None:
            if entry.risk == "high" and not self._cfg.allow_high_risk:
                raise SafetyError(
                    E_HIGH_RISK_BLOCKED,
                    f"当前前台应用 {entry.alias} 是高风险应用，动作被安全策略拦截；"
                    "如需放行请管理员开启 ALLOW_HIGH_RISK",
                )
            return entry
        raise SafetyError(
            E_HIGH_RISK_BLOCKED,
            f"前台应用 {package or '（未知）'} 不在白名单，动作被安全策略拦截；"
            "如需操作请管理员将其加入 APP_WHITELIST",
        )

    # ---------- 预算 ----------
    def budget_reset(self, umo: str) -> None:
        self._window.pop(umo, None)

    def budget_consume(self, umo: str) -> None:
        """任务模式优先消耗一次性步数；常规对话走时间窗。"""
        remaining = self._task_budget.get(umo)
        if remaining is not None:
            if remaining <= 0:
                raise SafetyError(E_BUDGET_EXCEEDED, "任务步数已用尽")
            self._task_budget[umo] = remaining - 1
            return
        now = time.monotonic()
        window_start = now - _WINDOW_SECONDS
        recent = [t for t in self._window.get(umo, ()) if t > window_start]
        if len(recent) >= self._cfg.action_max_per_turn:
            self._window[umo] = recent
            raise SafetyError(
                E_BUDGET_EXCEEDED,
                f"近 {_WINDOW_SECONDS / 60:.0f} 分钟设备动作已达上限 "
                f"{self._cfg.action_max_per_turn}，请稍后再试",
            )
        recent.append(now)
        self._window[umo] = recent

    def task_budget_start(self, umo: str, limit: int) -> None:
        self._task_budget[umo] = max(1, int(limit))

    def task_budget_stop(self, umo: str) -> None:
        self._task_budget.pop(umo, None)
