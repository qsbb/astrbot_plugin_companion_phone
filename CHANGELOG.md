# 更新日志

本文件记录 astrbot_plugin_companion_phone（凝心溯溪-通）的变更。metadata.yaml 的 `version` 是版本唯一事实源。

## 0.0.1（2026-09-05）

### 新增

- 真机 / Redroid 模拟器双模式设备后端（docker CLI 异步管理容器、USB/无线 ADB 真机连接与探活自愈）。
- 九个 LLM 函数工具：status、screen、tap、click_text、input_text、swipe、press_key、launch_app、wait_element（感知-行动-验证循环）。
- `/phone` 管理指令组（管理员）：status、reload、shot、apps、task、audit、pause、resume；`/phone task` 走官方 `tool_loop_agent` 多步任务。
- 安全层：应用白名单、高危应用入口门控（默认禁止进入 risk=high 应用，`ALLOW_HIGH_RISK` 放行）、高危关键词纵深拦截、5 分钟滑动窗动作预算与任务独立步数预算。
- 审计（JSONL、UTC、正文掩码、截图本地轮转）与 `series.diagnostics@1.0` 必选契约（环形缓冲、游标续读、凭据脱敏）。
- `series.webui@1.0` 三面板（phone_status / phone_apps / phone_audit），含重载、暂停、恢复、清空审计动作，由核 WebUI 统一接管。
- 设备操作 60 秒硬超时（超时自动重置连接）；中文输入 FastInputIME 与 ASCII 回退；拟人随机延时与坐标抖动。
- 读屏与启动应用前自动清理信息性弹窗（名单刻意不含"确定"）。

### 变更

- 安全模型 v2：高危应用从"应用内关键词拦截"改为"入口门控"（默认禁止进入），关键词拦截降为纵深第二层。

### 说明

- 单字「通」已由用户确认（2026-09-05）；发布前需在核 `core/trusted.py` 登记，并在规范 §2.3 备案 `/phone` 命令前缀。
- 多步任务（`/phone task`）代码就绪，尚待真机与 AstrBot 运行环境联调。
