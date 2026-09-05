from __future__ import annotations

PLUGIN_ID = "astrbot_plugin_companion_phone"
PLUGIN_VERSION = "0.0.3"  # 唯一事实源为 metadata.yaml 的 version；二者由测试断言一致
__version__ = PLUGIN_VERSION  # 规范 §10：与 metadata.yaml version 同步
PLUGIN_NAME = "通"  # 凝心溯溪系列单字，用户已确认（2026-09-05）
PLUGIN_DISPLAY_NAME = "凝心溯溪-通"
PLUGIN_REPOSITORY = "https://github.com/qsbb/astrbot_plugin_companion_phone"

MODE_REDROID = "redroid"
MODE_REAL = "real"
MODES = (MODE_REDROID, MODE_REAL)

# 工具名（全局唯一，注册进 AstrBot 工具集）
TOOL_STATUS = "companion_phone_status"
TOOL_SCREEN = "companion_phone_screen"
TOOL_TAP = "companion_phone_tap"
TOOL_CLICK_TEXT = "companion_phone_click_text"
TOOL_INPUT = "companion_phone_input_text"
TOOL_SWIPE = "companion_phone_swipe"
TOOL_KEY = "companion_phone_press_key"
TOOL_LAUNCH = "companion_phone_launch_app"
TOOL_WAIT = "companion_phone_wait_element"

TOOL_NAMES = (
    TOOL_STATUS,
    TOOL_SCREEN,
    TOOL_TAP,
    TOOL_CLICK_TEXT,
    TOOL_INPUT,
    TOOL_SWIPE,
    TOOL_KEY,
    TOOL_LAUNCH,
    TOOL_WAIT,
)

# 错误码
E_PLUGIN_DISABLED = "plugin_disabled"
E_PAUSED = "all_actions_paused"
E_DEVICE_OFFLINE = "device_offline"
E_DEVICE_TIMEOUT = "device_timeout"
E_DOCKER_MISSING = "docker_missing"
E_CONTAINER_FAILED = "container_failed"
E_ADB_CONNECT_FAILED = "adb_connect_failed"
E_OUT_OF_BOUNDS = "tap_out_of_bounds"
E_APP_NOT_ALLOWED = "app_not_in_whitelist"
E_HIGH_RISK_BLOCKED = "high_risk_blocked"
E_BUDGET_EXCEEDED = "action_budget_exceeded"
E_ELEMENT_NOT_FOUND = "element_not_found"
E_INPUT_TOO_LONG = "input_too_long"
E_INVALID_ARGUMENT = "invalid_argument"
E_DEVICE_TIMEOUT = "device_timeout"
E_UNKNOWN_PANEL = "UNKNOWN_PANEL"  # series.webui@1.0 规范错误码（§5.3 大写）
E_UNKNOWN_ACTION = "UNKNOWN_ACTION"
E_SESSION_NOT_ALLOWED = "session_not_allowed"
E_INTERNAL = "internal_error"

# press_key 支持的按键
KEY_NAMES = (
    "back",
    "home",
    "recents",
    "enter",
    "del",
    "power",
    "volume_up",
    "volume_down",
)

SWIPE_DIRECTIONS = ("up", "down", "left", "right")
