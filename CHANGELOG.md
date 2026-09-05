# 更新日志

本文件记录 astrbot_plugin_companion_phone（凝心溯溪-通）的变更。metadata.yaml 的 `version` 是版本唯一事实源。

## 0.0.4 - 2026-09-06

### 新增

- R2 视觉兜底：新增 `SCREEN_VISION` 配置（默认关闭）。开启后 `screen` 把截图压缩为宽 ≤720px 的 JPEG（Pillow，压缩在 to_thread 内不阻塞事件循环；PIL 不可用时回退原始字节并按魔数嗅探 mime），以 MCP `CallToolResult` 图像内容与控件树文本一并回传多模态模型；关闭时行为与 0.0.3 完全一致，截图路径零泄漏。
- `requirements.txt` 显式声明 Pillow（截图压缩；uiautomator2 的传递依赖）。
- 已知宿主要求：视觉回传依赖 AstrBot 工具结果遍历全部内容块——旧版本宿主上自动降级为纯文本（schema 描述已注明）。

## 0.0.3（2026-09-06）

第二轮 3 份盲测的修复版本。

### 修复

- status 工具 `_call` 实参错位导致调用必崩（第二轮盲测 P1，补 9 工具 call() 全覆盖回归测试）。
- swipe 垂直/水平分轴钳制（原实现把垂直滑动按屏宽钳到 ~539px）。
- 会话门控 fail-open → fail-closed（事件字段异常时拒绝而非放行）。

### 变更

- 安全模型 v4：`APP_WHITELIST` 升级为完整操作边界——动作级前台门控对白名单外应用一律拒绝（原实现只拦白名单内 high 应用，桌面图标/深链/最近任务进入的任意应用内 tap/输入全部放行）。
- `press_key` 分治：back/home/recents 豁免（脱困通道），enter/del/power/volume 过前台应用门控（enter 在聊天输入框即"发送"）。
- status 工具输出裁剪：不向模型暴露容器/镜像/端口（`/phone status` 与 WebUI 不受影响）。
- `/phone shot` 仅限私聊（防整屏截图被投放群聊）。
- 默认高危关键词表补英文（Send/Delete/Pay/Allow 等；redroid 默认 en_US locale）。
- 写动作失败不自动重试（防非幂等动作双执行）；设备连接路径加 60s 超时。
- screen 的弹窗代点仅在前台为白名单 low 应用时执行。

## 0.0.2（2026-09-06）

第一轮 5 份盲测（36 项发现）的修复版本，详见 `docs/REVIEW_FINDINGS.md` 与 `docs/FIX_PLAN.md`。

### 修复（P0）

- LLM 工具层改用 `pydantic.dataclasses.dataclass`（stdlib dataclass 叠加 pydantic dataclass 使 parameters 变成 FieldInfo，真实宿主上 9 个工具 schema 全部损坏）；新增 `tests/astrbot_stub` 离线基座，工具层测试不再被 importorskip 掩盖。
- 审计读取端统一 UTC（原 recent() 用本地时区，UTC+8 每天 0-8 点审计恒为空，且 4 例测试在该时段必红）。
- `press_key("recents")` 键值修正（keyevent 164 实为 KEYCODE_VOLUME_MUTE，静音键；改用 u2 官方键名 "recent"）。
- 移除 u2 2.x 的 `d.alive` 探活（v3 无此 API，导致每次操作全量重连 uiautomator server 并经 atexit 泄漏 Device 对象）；改为"失败丢弃连接重试一次"。
- 动作级前台应用门控（第一版）；弹窗代点名单移除「允许/始终允许」（运行时权限授权按钮）。

### 修复（P1/P2）

- docker 二进制缺失归一为 `docker_missing`（原裸抛 FileNotFoundError）；容器名防 argv 注入校验。
- swipe 端点收口到屏幕内；包名正则放宽大写（com.Slack）；默认镜像 tag 改官方在列值。
- redroid 容器外部停止后可自愈（移除 serial 缓存短路）；REDROID_DOCKER_ARGS/REDROID_EXTRA_ARGS 分置镜像前后。
- click_text bounds 统一 [x1,y1,x2,y2]；input_text 审计只记长度（防验证码泄漏）；预算在连接建立后扣减。
- 新增 `TOOL_CHAT_SCOPE`/`TOOL_ALLOWLIST` 会话门控（默认 private，防群成员经提示注入驱动手机）。
- 审计读取 `-0` 切片陷阱；clear_today 无文件返回 False；诊断 seq 进程级单调（clear 不吞聚合端事件）；webui 未知面板/动作改返回式（§5.3）；契约测试改调真实实现（原恒真）；series.webui 渲染契约措辞修正。
- short_desc 对齐 §2.4；4 处日志统一 `[companion-phone]` 前缀与英文；移除零引用的 Pillow 依赖；真机 adb 调用 30s 超时。
