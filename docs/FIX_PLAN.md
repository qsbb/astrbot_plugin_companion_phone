# 0.0.2 优化修改方案（FIX PLAN）

> 输入：`docs/REVIEW_FINDINGS.md`（F-01 ~ F-36 + P3 摘录）。
> 原则：每个修复必须绑定至少一个能抓住它的测试；文档声称的每一条能力改动同步 README/CHANGELOG。
> 版本目标：**0.0.2**（含行为变更：安全模型升级、工具会话门控默认值）。

## WP1 工具层重建（F-01、F-34、F-16、F-17 部分）

| 项 | 修法 | 测试 |
|---|---|---|
| dataclass 语义 | tools/observe.py、act.py、apps.py 改 `from pydantic.dataclasses import dataclass`（与官方文档及翼一致） | 新增离线 astrbot stub（`tests/astrbot_stub/`，conftest 仅在 astrbot 未安装时注入 sys.path——核的官方 stub 方案），`test_tools.py` 去 importorskip，断言 9 个工具 `isinstance(t.parameters, dict)` 且构造无需必填参数——该断言直接抓住 F-01 回归 |
| `_ToolMixin.service` 字段化 | `service: Any = None` 成为带默认的 dataclass 字段，`create_device_tools` 改为 `cls(service=service)`，删除 `object.__setattr__` hack | 同上（构造即验证） |
| 工具会话门控（F-16） | 新配置 `TOOL_CHAT_SCOPE`（`all/private/allowlist`，默认 **private**）与 `TOOL_ALLOWLIST`（umo 列表）；`_ToolMixin` 新增 `_call(context, action, coro_factory)`：先经 `service.check_session_allowed(event)`，不通过返回 `{"status":"error","error_code":"session_not_allowed"}`；9 个工具统一走 `_call` | test_tools：group 事件在 private 模式被拒、allowlist 命中放行、all 模式放行 |
| `_int_arg` 严格化（F-34） | bool 拒绝、非整值 float 拒绝 | test_tools 参数校验用例 |
| 截图路径出参（F-17 代码侧） | `service.screen(umo)` 不再把 screenshot 放进返回值；ScreenTool 描述删「截图路径一并提供」；截图仅存盘供 `/phone shot` 与审计 | test_service：screen 返回值无 `screenshot` 键 |

## WP2 安全模型 v3：动作级门控（F-05、F-06、F-25、F-02 关联）

| 项 | 修法 | 测试 |
|---|---|---|
| 动作级前台应用门控（F-05） | `SafetyGate.check_current_app(package)`：包名命中白名单且 risk=high 且未 ALLOW_HIGH_RISK → 拦；包名为空/未知（fail-closed）→ 拦（消息指引重试读屏）。`tap`、`input_text`、`swipe` 的 `_act` 在执行前调用（`click_text` 已有同款）；`press_key` 豁免（back/home 是脱困通道，必须保留） | test_service：前台为 wechat（high）时 tap/input/swipe 被拒；前台 browser 放行；前台未知包名 fail-closed；press_key 不受影响 |
| 代点名单收紧（F-06） | `_POPUP_TEXTS` 移除「允许」「始终允许」；同时把「允许」「始终允许」加入 `HIGH_RISK_KEYWORDS` 默认值（模型经 click_text 点它们也走高危拦截） | test_device：名单断言不含 允许/确定；test_safety：默认关键词含 允许 |
| 越界检查 fail-closed（F-25） | `check_tap_xy` 屏幕尺寸非法时抛 `tap_out_of_bounds` | test_safety 新增 |
| 设计声明修正 | 开发文档 §6.1 改为「入口门控 + 动作级门控」双层模型，删除「唯一不可绕过」措辞 | 文档审查（盲测 E 复核） |

## WP3 设备层修复（F-03、F-04、F-13、F-31、F-35）

| 项 | 修法 | 测试 |
|---|---|---|
| recents 键值（F-03） | `_press_key_sync` 改 `self._d.press("recent")`，删 shell/魔数 | test_device：fake d 捕获 press 参数 == "recent" |
| 探活重造（F-04） | 删除 `d.alive` 依赖：`_run` 单锁内执行——`_d is None` 才 connect；操作抛非 DeviceError 异常 → 置 `_d=None`、重连、重试一次；超时置 `_d=None`（已有）。删除 `assert_ready` 探活语义与 `screen_on` 死代码 | test_device：超时后 `_d is None`；失败重试一次后成功；连接失败不无限重试 |
| click_text bounds（F-13） | dict → `[left, top, right, bottom]` | test_device |
| 元素消失竞态（F-31） | 捕获 u2 `UiObjectNotFoundError` → `element_not_found` | test_device（fake 选择器抛该异常） |
| 输入回退语义（F-35） | 返回值改名 `ime_fallback`（不再声称 ASCII），描述如实 | test_device 保留行为断言 |

## WP4 后端修复（F-07、F-10、F-11、F-12、F-18、F-36）

| 项 | 修法 | 测试 |
|---|---|---|
| docker 缺失归一（F-07、F-36） | `_docker` 捕 FileNotFoundError/OSError → `BackendError(E_DOCKER_MISSING)`；命令超时改 `E_CONTAINER_FAILED` | test_backend_redroid：patch subprocess 抛 FileNotFoundError → E_DOCKER_MISSING |
| redroid 自愈（F-10） | `ensure_ready` 删除缓存短路：每次调用都 inspect 容器状态并按 missing→create / 非 running→start+boot-wait 恢复（ensure_ready 仅在首次连接与重连时被调用，无 happy-path 开销） | test_backend_redroid：serial 已设 + container_state=exited → 仍发起 start |
| 镜像默认值（F-11） | 默认改 `redroid/redroid:12.0.0_64only-latest`；hint 说明 ARM 应用需自建 native-bridge 镜像；README 部署节同步 | 配置默认值断言 |
| 参数位置（F-12） | 新增 `REDROID_DOCKER_ARGS`（镜像前，docker 层）；`REDROID_EXTRA_ARGS` 语义改为 redroid 启动参数、置于镜像名后 | test_backend_redroid：argv 顺序断言（docker args 在镜像前、extra args 在镜像后） |
| real 后端超时（F-18） | adbutils 全部调用包 `asyncio.wait_for(..., 30s)` | test_backend_real：挂起 fake → 超时错误 |

## WP5 配置与预算（F-09、F-14、F-15、F-28、F-29）

| 项 | 修法 | 测试 |
|---|---|---|
| 包名正则（F-09） | `^[A-Za-z][A-Za-z0-9_-]*(\.[A-Za-z][A-Za-z0-9_-]*)+$` | test_config：`com.Slack` 通过、`com.UCMobile.intl` 通过、坏包名仍拒 |
| 审计掩码收紧（F-14） | input_text 审计只记 `text_len`，删除 text_head；click_text/wait_element 保留 text[:32]（屏幕内容，溯源需要）并在文档注明边界 | test_service：input 审计无任何正文片段 |
| 预算后扣（F-15） | `_do` 顺序改为：启停检查 → 建会话 → 扣预算 → 拟人延时 → 执行 | test_service：连接失败（fake 抛错）后预算未消耗 |
| 数值校验（F-28、F-29） | `_int` 拒 bool、失败 logger.warning；新增下界：ACTION_MAX_PER_TURN/TASK_MAX_STEPS/UI_TREE_MAX_NODES/SCREENSHOT_KEEP ≥1；DELAY_MS_MIN/MAX ≥0；容器名正则校验（防 argv 注入） | test_config 参数化矩阵 |

## WP6 审计与诊断（F-02、F-19、F-20、F-26、F-30、F-32）

| 项 | 修法 | 测试 |
|---|---|---|
| 时区统一（F-02） | `recent()` 改 UTC | test_audit：冻结时钟构造「本地日期≠UTC 日期」时刻，record→recent 必须读到（回归锚） |
| `-0` 陷阱（F-26） | `limit<=0` 返回 [] | test_audit |
| clear 语义（F-30） | 无文件返回 False（docstring 对齐） | test_audit |
| seq 单调（F-20） | seq 改进程级单调计数器，clear 不归零；`diagnostic_log_contract()` 提为 series_diagnostics 模块函数（main 委托），测试直接调用真实实现（F-19） | test_diagnostics：clear 后 seq 继续；contract 测试调用实现 |
| screen 归属（F-32） | `screen(umo)` 由工具传入，审计记录哈希 umo | test_service |

## WP7 规范与文档（F-17 文档侧、F-21、F-22、F-23、F-33）

| 项 | 修法 |
|---|---|
| webui 未知 id 改返回式（F-21） | 返回 `{"success": False, "error_code": "UNKNOWN_PANEL"/"UNKNOWN_ACTION", "message": ...}`；测试同步 |
| short_desc（F-22） | `凝心溯溪系列通模块：真机/模拟器双模式的安卓手机操作` |
| 日志四处（F-23） | 英文 + `[companion-phone]` 前缀 |
| 依赖（F-33） | requirements 移除 Pillow |
| README/CHANGELOG/设计文档 | 同步：截图不回传（现为真）、会话门控默认 private（行为变更注明）、镜像 tag、双层门控、弹窗名单、「正文不全文落盘」措辞；版本 0.0.2 |

## WP8 测试补强（F-19、F-24 及 D 清单精选）

新增：`test_device.py`（bounds 解析/按键映射/弹窗名单/超时重连/竞态）、`test_backend_redroid.py`（argv 拼装/状态机/自愈/异常归一）、`test_backend_real.py`（serial 选择分支/超时）、`test_tools.py` 离线化（stub + schema 断言 + 会话门控）、audit 时区冻结回归、safety 窗口边界（patch monotonic）。命令权限门控测试（F-24）随 main stub 化成本高，列为 0.0.3 项并在文档注明。

## 验收门

1. `python -m pytest tests/ -q` 全绿（含新增用例），且在任何时区运行均绿（时区冻结测试证明）。
2. `ruff format . && ruff check .` 全绿。
3. README/CHANGELOG/设计文档与本实现零矛盾（盲测 E 复核项）。
4. 安全断言：默认配置下，前台为高风险应用时 tap/input/swipe 全部被拒（测试证明）。
