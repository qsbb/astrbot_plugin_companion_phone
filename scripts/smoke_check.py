"""M2 联调预检脚本：在 AstrBot 服务器上一条命令验证插件全链路。

用法（在 AstrBot 的 Python 环境中）：
    python scripts/smoke_check.py                       # 自动读取默认配置路径
    python scripts/smoke_check.py --mode real --serial XXX
    python scripts/smoke_check.py --config /path/to/config.json

输出逐项 PASS/FAIL/SKIP 报告；任一 FAIL 时退出码为 1。
覆盖：Python 版本 → 依赖 → 配置校验 → 设备层（docker/容器/引导/ADB 或真机）
→ uiautomator2 连接与读屏/截图 → 插件导入 → 系列契约形状。
"""

from __future__ import annotations

import argparse
import importlib
import json
import socket
import sys
import traceback
from pathlib import Path

PLUGIN_ID = "astrbot_plugin_companion_phone"
PLUGIN_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PLUGIN_ROOT.parent))

_results: list[tuple[str, str, str]] = []  # (状态, 检查项, 详情)


_args = None  # main() 解析后注入；步骤函数统一以 args 为入参


def step(name: str):
    """装饰器：把函数包装为一个检查步骤，异常即 FAIL。"""

    def deco(fn):
        def run():
            try:
                detail = (fn(_args) or "") if _args is not None else (fn() or "")
                _results.append(("PASS", name, detail))
            except SkipCheck as exc:
                _results.append(("SKIP", name, str(exc)))
            except Exception as exc:
                detail = f"{type(exc).__name__}: {exc}"
                tb = traceback.format_exc(limit=3)
                _results.append(("FAIL", name, f"{detail}\n{tb}"))

        return run

    return deco


class SkipCheck(Exception):
    pass


# ---------- 步骤 ----------


@step("Python 版本 >= 3.12")
def check_python(args):
    if sys.version_info < (3, 12):
        raise RuntimeError(f"当前 {sys.version_info.major}.{sys.version_info.minor}")
    return f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"


def _import_deps():
    u2 = importlib.import_module("uiautomator2")
    adbutils = importlib.import_module("adbutils")
    return u2, adbutils


@step("第三方依赖可导入（uiautomator2 / adbutils）")
def check_deps(args):
    u2, adbutils = _import_deps()
    detail = f"uiautomator2 {getattr(u2, '__version__', '?')} / adbutils {getattr(adbutils, '__version__', '?')}"
    try:
        import PIL

        detail += f" / Pillow {PIL.__version__}"
    except ImportError:
        detail += " / Pillow 缺失（SCREEN_VISION 视觉兜底将回退原始 PNG）"
    return detail


def _load_config(args) -> dict:
    candidates = []
    if args.config:
        candidates.append(Path(args.config))
    else:
        candidates += [
            PLUGIN_ROOT.parent / "data" / "config" / f"{PLUGIN_ID}_config.json",
            Path("data/config") / f"{PLUGIN_ID}_config.json",
        ]
    for path in candidates:
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            return (
                data.get("data", data)
                if isinstance(data, dict) and "data" in data
                else data
            )
    raise SkipCheck(f"未找到配置文件（尝试：{[str(c) for c in candidates]}）")


@step("插件配置校验")
def check_config(args):
    data = _load_config(args)
    from astrbot_plugin_companion_phone.config import PhoneConfig

    cfg = PhoneConfig.from_mapping(data)
    return (
        f"mode={cfg.mode} enabled={cfg.enabled} 白名单={cfg.alias_list()} "
        f"scope={cfg.tool_chat_scope} high_risk放行={cfg.allow_high_risk}"
    )


def _target_serial(cfg) -> str:
    if cfg.mode == "real":
        return cfg.real_wireless_addr or cfg.real_serial
    return f"127.0.0.1:{cfg.redroid_adb_port}"


@step("docker 可用（redroid 模式）")
def check_docker(args):
    cfg = _cfg_cache
    if cfg.mode != "redroid":
        raise SkipCheck("当前为 real 模式")
    import subprocess

    rc = subprocess.run(
        ["docker", "version", "--format", "{{.Server.Version}}"],
        capture_output=True,
        text=True,
        timeout=15,
    )
    if rc.returncode != 0:
        raise RuntimeError(f"docker 不可用：{rc.stderr.strip()[:120]}")
    return f"server {rc.stdout.strip()}"


@step("容器状态与引导（redroid 模式）")
def check_container(args):
    cfg = _cfg_cache
    if cfg.mode != "redroid":
        raise SkipCheck("当前为 real 模式")
    import subprocess

    rc = subprocess.run(
        ["docker", "inspect", "-f", "{{.State.Status}}", cfg.redroid_container],
        capture_output=True,
        text=True,
        timeout=15,
    )
    if rc.returncode != 0:
        raise RuntimeError(
            f"容器 {cfg.redroid_container} 不存在，先启动插件或手动 docker run"
        )
    state = rc.stdout.strip()
    boot = subprocess.run(
        ["docker", "exec", cfg.redroid_container, "getprop", "sys.boot_completed"],
        capture_output=True,
        text=True,
        timeout=15,
    )
    if boot.stdout.strip() != "1":
        raise RuntimeError(f"容器 {state}，但 sys.boot_completed 未就绪")
    return f"{state}，引导完成"


@step("ADB 端口连通（redroid 模式）")
def check_adb_port(args):
    cfg = _cfg_cache
    if cfg.mode != "redroid":
        raise SkipCheck("当前为 real 模式")
    host, port = "127.0.0.1", cfg.redroid_adb_port
    with socket.create_connection((host, port), timeout=5):
        return f"{host}:{port} 可达"


@step("真机探活（real 模式）")
def check_real_device(args):
    cfg = _cfg_cache
    if cfg.mode != "real":
        raise SkipCheck("当前为 redroid 模式")
    _, adbutils = _import_deps()
    client = adbutils.AdbClient(host="127.0.0.1", port=5037)
    serial = cfg.real_wireless_addr or cfg.real_serial
    if cfg.real_wireless_addr:
        client.connect(cfg.real_wireless_addr)
    devices = [d.serial for d in client.device_list()]
    if serial not in devices:
        raise RuntimeError(f"serial {serial} 不在线（当前：{devices}）")
    device = client.device(serial)
    out = str(device.shell("echo ok"))
    if "ok" not in out:
        raise RuntimeError("shell 无响应")
    return f"{serial} 探活正常"


@step("uiautomator2 连接 + 读屏 + 截图")
def check_u2(args):
    cfg = _cfg_cache
    u2, _ = _import_deps()
    serial = _target_serial(cfg)
    d = u2.connect(serial)
    info = d.app_current()
    size = d.window_size()
    nodes = d.dump_hierarchy()
    shot_dir = PLUGIN_ROOT / "smoke_shots"
    shot_dir.mkdir(exist_ok=True)
    shot = shot_dir / "smoke.png"
    d.screenshot(str(shot))
    return (
        f"{serial} 前台 {info.get('package', '?')} 屏幕 {size[0]}x{size[1]} "
        f"控件树 {len(nodes)} 字符，截图 {shot.name}"
    )


@step("插件导入与契约形状（AstrBot 环境内）")
def check_plugin_import(args):
    try:
        importlib.import_module("astrbot.api")
    except ImportError:
        raise SkipCheck("非 AstrBot 环境（在服务器 AstrBot 的 Python 环境中运行可测）")
    try:
        main_mod = importlib.import_module(f"{PLUGIN_ID}.main")
    except Exception as exc:
        raise RuntimeError(f"导入失败（代码错误或依赖缺失）：{exc}") from exc
    from astrbot_plugin_companion_phone.series_diagnostics import (
        diagnostic_log_contract,
    )

    c = diagnostic_log_contract()
    if c.get("name") != "series.diagnostics" or c.get("series_id") != "ningxin_suxi":
        raise RuntimeError("诊断契约形状不合法")
    meta = getattr(main_mod.CompanionPhonePlugin, "_nx_register_meta", None)
    version = meta["version"] if meta else getattr(main_mod, "__version__", "?")
    return f"版本 {version}，契约 series.diagnostics@{c['version']}"


_steps = [
    check_python,
    check_deps,
    check_config,
    check_docker,
    check_container,
    check_adb_port,
    check_real_device,
    check_u2,
    check_plugin_import,
]

_cfg_cache = None


def main() -> int:
    global _cfg_cache, _args
    parser = argparse.ArgumentParser(description="凝心溯溪-通 联调预检")
    parser.add_argument("--mode", choices=["redroid", "real"], help="覆盖配置中的 MODE")
    parser.add_argument("--serial", help="real 模式 serial（覆盖配置）")
    parser.add_argument("--config", help="插件配置 JSON 路径")
    _args = args = parser.parse_args()

    try:
        data = _load_config(args)
    except SkipCheck as exc:
        data = {}
        print(f"[配置] {exc}；仅执行环境检查\n")
    if args.mode:
        data["MODE"] = args.mode
    if args.serial:
        data["REAL_SERIAL"] = args.serial

    from astrbot_plugin_companion_phone.config import PhoneConfig

    try:
        _cfg_cache = PhoneConfig.from_mapping(data)
    except Exception as exc:
        _cfg_cache = PhoneConfig()
        print(f"[配置] 解析失败（{exc}）；设备步骤将以默认参数尝试\n")

    for run in _steps:
        run()

    print("=" * 72)
    width = max(len(name) for _, name, _ in _results)
    marks = {"PASS": "✅", "FAIL": "❌", "SKIP": "⏭️ "}
    for state, name, detail in _results:
        print(f"{marks[state]} [{state}] {name.ljust(width)}  {detail.splitlines()[0]}")
    failed = [r for r in _results if r[0] == "FAIL"]
    print("=" * 72)
    print(
        f"结果：{sum(1 for r in _results if r[0] == 'PASS')} 通过 / "
        f"{len(failed)} 失败 / {sum(1 for r in _results if r[0] == 'SKIP')} 跳过"
    )
    if failed:
        print("\n失败项修复建议见 README『快速开始』与开发文档 §14 部署手册。")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
