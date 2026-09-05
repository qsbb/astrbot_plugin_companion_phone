# astrbot_plugin_companion_phone（凝心溯溪-通）

给 AstrBot 虚拟恋人配一部安卓手机：她能像人一样看屏幕、点按、输入、滑动、打开应用。

- **双模式**：`redroid`（服务器 Docker 化安卓模拟器，插件管理容器生命周期）或 `real`（USB/无线连接的真机），改配置即可切换。
- **两种使用方式**：日常对话中作为 LLM 函数工具被虚拟恋人直接调用；管理员用 `/phone task` 跑多步任务（官方 `tool_loop_agent` Agent 循环）。
- **安全（白名单即操作边界）**：`APP_WHITELIST` 是唯一可操作的应用集合——入口门控（high 应用默认禁止启动）+ 动作级前台门控（tap/输入/滑动执行前查前台应用，白名单外一律拒绝）+ 按键分治（enter/del 过门控，back/home 豁免作脱困通道）+ 工具会话门控（默认仅私聊可用）+ 动作预算 + 关键词纵深拦截（中英双语）。
- **隐私**：输入正文不落审计（仅记长度，验证码类短文本也不泄漏）；截图路径与内容不回传模型；status 工具不暴露容器/镜像/端口。
- **系列治理**：实现 `series.diagnostics@1.0`（必选）与 `series.webui@1.0` 三面板（手机状态/应用白名单/操作审计），由核 WebUI 统一接管。

设计文档见仓库内 `docs/`（REVIEW_FINDINGS.md 为 0.0.1 审查发现，FIX_PLAN.md 为修复方案），完整架构与部署手册见仓库外 `PHONE_PLUGIN_DEV_DOC.md`。

## 快速开始

1. 准备设备（二选一）：
   - **模拟器**：Debian 服务器安装 docker、binder 内核模块、adb；插件自动拉起 Redroid 容器（默认镜像 `redroid/redroid:12.0.0_64only-latest`，官方镜像内置 libndk ARM 翻译，可直接跑微信等 ARM 应用）。首次需用 scrcpy 人工登录账号。
   - **真机**：手机开 USB 调试，`adb devices` 记下 serial；或无线调试配对后填 `REAL_WIRELESS_ADDR`。
2. AstrBot WebUI 安装本插件（或放入 `data/plugins/`）。
3. 配置 `MODE` 与对应参数，添加 `APP_WHITELIST`（alias/package/risk），`ENABLED=true`。
4. 验证：`/phone status` → `/phone shot` → `/phone task 打开browser搜索天气`。
5. 联调预检（可选，装插件前/后都可在服务器上运行）：
   `python scripts/smoke_check.py`——逐项检查 Python 版本、依赖、配置校验、
   docker/容器/引导（redroid）或真机探活、u2 读屏截图、插件导入与契约形状，
   输出 PASS/FAIL/SKIP 报告；`--mode`、`--serial`、`--config` 可覆盖。

## 管理指令（管理员）

| 指令 | 说明 |
|---|---|
| `/phone status` | 设备与插件状态（含后端详情） |
| `/phone reload` | 切换 MODE 后重建设备后端 |
| `/phone shot` | 抓当前屏幕截图发回（仅私聊） |
| `/phone apps` | 列出应用白名单 |
| `/phone task <目标>` | 多步手机任务（Agent 循环） |
| `/phone audit` | 最近 20 条脱敏审计 |
| `/phone pause` / `/phone resume` | 暂停/恢复全部动作 |

## LLM 工具

`companion_phone_status / screen / tap / click_text / input_text / swipe / press_key / launch_app / wait_element`

模型看屏靠 `screen`（控件树文本摘要；仅白名单 low 前台自动清理"我知道了/稍后"类信息性弹窗），操作优先 `click_text`（按文本），坐标兜底 `tap`。截图仅供管理员（`/phone shot`）与审计。

## 安全边界

- `APP_WHITELIST` 是完整操作边界：白名单外的应用既无法启动，进入后（桌面图标/深链等路径）也无法点按/输入/滑动；权限对话框（permissioncontroller）因不在白名单天然被拒。
- `risk=high` 的应用（如微信）默认禁止进入，需管理员开启 `ALLOW_HIGH_RISK`；low 应用内的"发送/删除/支付"类文本点按仍受关键词纵深拦截（默认中英双语，依赖设备 locale）。
- `press_key` 分治：back/home/recents 全额放行（脱困通道），enter/del/power/volume 过前台应用门控（enter 在聊天输入框即发送）。
- `TOOL_CHAT_SCOPE` 默认 `private`：群聊会话无法调用手机工具（防群成员经提示注入驱动手机）；`allowlist` 模式可精确到会话。
- 设备操作 60 秒硬超时；写动作失败不自动重试（防双执行）；超时即重置连接。
- 审计存 `data/plugin_data/astrbot_plugin_companion_phone/audit/`（UTC、输入正文仅记长度）；截图目录敏感，注意宿主权限。

## 已知限制

- 账号风控：微信/QQ 等对模拟器与自动化有检测，封号风险自担；建议真机 + 小号。
- 门控检查与动作执行存在毫秒级 TOCTOU 窗口（前台应用可能在检查后切换），已记录为已知限制。
- 视觉兜底按需开启（`SCREEN_VISION`，默认关）：开启后屏幕图像进入模型上下文，且宿主会在其 temp 目录缓存副本——请自行评估隐私与成本。

## 开发

```bash
cd astrbot_plugin_companion_phone
python -m pytest tests/ -q      # 离线测试（tests/astrbot_stub 为最小框架替身）
ruff format . && ruff check .   # 提交前
```
