# astrbot_plugin_companion_phone（凝心溯溪-通）

给 AstrBot 虚拟恋人配一部安卓手机：她能像人一样看屏幕、点按、输入、滑动、打开应用。

- **双模式**：`redroid`（服务器 Docker 化安卓模拟器，插件管理容器生命周期）或 `real`（USB/无线连接的真机），改配置即可切换。
- **两种使用方式**：日常对话中作为 LLM 函数工具被虚拟恋人直接调用；管理员用 `/phone task` 跑多步任务（官方 `tool_loop_agent` Agent 循环）。
- **安全**：应用白名单、高危应用入口门控（默认禁止进入微信等 risk=high 应用）、高危关键词纵深拦截、单轮动作预算、JSONL 审计（输入内容掩码）。
- **系列治理**：实现 `series.diagnostics@1.0`（必选）与 `series.webui@1.0` 三面板（手机状态/应用白名单/操作审计），由核 WebUI 统一接管，不建独立控制台。

完整设计见仓库外文档 `PHONE_PLUGIN_DEV_DOC.md`（架构、方法级 API、部署手册）。

## 快速开始

1. 准备设备（二选一）：
   - **模拟器**：Debian 服务器安装 docker、binder 内核模块、adb；插件会自动拉起 Redroid 容器（Android 12 + native bridge 镜像，跑微信等 ARM 应用）。首次需用 scrcpy 人工登录账号。
   - **真机**：手机开 USB 调试，`adb devices` 记下 serial；或无线调试配对后填 `REAL_WIRELESS_ADDR`。
2. AstrBot WebUI 安装本插件（或放入 `data/plugins/`）。
3. 配置 `MODE` 与对应参数，添加 `APP_WHITELIST`（alias/package/risk），`ENABLED=true`。
4. 验证：`/phone status` → `/phone shot` → `/phone task 打开browser搜索天气`。

## 管理指令（管理员）

| 指令 | 说明 |
|---|---|
| `/phone status` | 设备与插件状态 |
| `/phone reload` | 切换 MODE 后重建设备后端 |
| `/phone shot` | 抓当前屏幕截图发回 |
| `/phone apps` | 列出应用白名单 |
| `/phone task <目标>` | 多步手机任务（Agent 循环） |
| `/phone audit` | 最近 20 条脱敏审计 |
| `/phone pause` / `/phone resume` | 暂停/恢复全部动作 |

## LLM 工具

`companion_phone_status / screen / tap / click_text / input_text / swipe / press_key / launch_app / wait_element`

模型看屏靠 `screen`（控件树文本摘要；读取前自动清理"我知道了/允许/稍后"类信息性弹窗），操作优先 `click_text`（按文本），坐标兜底 `tap`。截图仅供管理员（`/phone shot`）与审计，不回传模型。

## 安全边界

- 白名单外的应用无法启动；`risk=high` 的应用（如微信）默认**禁止进入**，需管理员开启 `ALLOW_HIGH_RISK`。
- 进入低风险应用后，命中 `HIGH_RISK_KEYWORDS`（发送/删除/支付等）的点按仍被纵深拦截。
- 信息性弹窗自动代点名单刻意不含"确定"等中性确认词，避免在敏感对话框上代点。
- 单轮动作预算 `ACTION_MAX_PER_TURN`（默认 8 次/5 分钟窗口）；设备操作 60 秒硬超时，超时自动重置连接。
- 审计与截图存 `data/plugin_data/astrbot_plugin_companion_phone/`，输入正文只记长度与前 12 字符。

## 已知限制

- 账号风控：微信/QQ 等对模拟器与自动化有检测，封号风险自担；建议真机 + 小号。
- 中文输入依赖 uiautomator2 的 FastInputIME；不可用时自动回退 ASCII 输入（结果中注明）。
- 视觉多模态定位（截图喂 VLM）未实现，当前以控件树文本定位为主。

## 开发

```bash
cd astrbot_plugin_companion_phone
python -m pytest -q      # 离线单元测试（不依赖 AstrBot / 真机）
ruff format .            # 提交前格式化
```
