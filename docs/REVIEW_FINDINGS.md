# 0.0.1 盲测问题清单（REVIEW FINDINGS）

> 本文档汇总 0.0.1 发布后的两轮审查结果：1 份人工 review + 5 份互相独立的盲测
> （A=全面审查、B=安全审查、C=外部 API 事实核查、D=测试与边界、E=规范与文档一致性）。
> 「命中」列记录独立发现该问题的审查方数量，≥2 视为高置信。
> 所有问题已逐一对照源码核实；争议点已本地复现裁决。

## P0 — 致命/安全（发布版核心承诺不成立）

| # | 发现 | 命中 | 位置 | 说明与证据 |
|---|---|---|---|---|
| F-01 | **LLM 工具层 schema 全部损坏** | C、E | tools/*.py:3 | 工具用标准库 `@dataclass` 叠在 pydantic dataclass `FunctionTool` 上。本地复现裁决：`tool.parameters` 是 `FieldInfo` 对象而非 dict（pydantic 2.13.3 实测 `is dict: False`），真实宿主上 9 个工具的 function-calling schema 全部失效。被 `test_tools.py` 的 `importorskip("astrbot")` 整文件跳过掩盖。附带：`_ToolMixin.service: Any` 无默认值注解在 dataclass 语义下使 `cls()` 构造即报错 |
| F-02 | **audit 读/写文件时区不一致** | A、B、C、D、E（5/5） | audit.py:81 vs :46/:69 | `recent()` 用本地时区选日期文件，`record/clear_today` 用 UTC。UTC+8 每天 0:00–8:00 审计查询恒为空；**测试套件当前 4 例失败**（UTC+8 深夜时段必红）——发布质量门已失守 |
| F-03 | **`recents` 按键实为静音** | A、C、D + 人工 | device.py:222 | `input keyevent 164` 是 `KEYCODE_VOLUME_MUTE`，`KEYCODE_APP_SWITCH=187`。且 u2 原生支持 `d.press("recent")`，本无需 shell |
| F-04 | **u2 v3 无 `d.alive`，探活恒 False** | A、C（各自 wheel 源码 grep） | device.py:69-73 | `alive` 是 u2 2.x API；3.2.0/3.7.0 均不存在 → `assert_ready` 快路径成死代码，**每次设备操作全量重连**（md5 推 jar + 启动 uiautomator server + HTTP ping），且每次 `u2.connect` 注册一个 atexit → Device 对象无界泄漏 |
| F-05 | **tap/input_text/press_key 完全绕过安全门** | A、B | service.py:216-242 | 动作级无前台应用检查。攻击链：`home` → tap 桌面微信图标（launcher 不在白名单也无妨）→ `input_text` → tap 发送坐标，全程无拦截。「入口门控是唯一不可绕过位置」的设计声明被证伪（深链/桌面图标/最近任务均可绕过 launch_app） |
| F-06 | **弹窗代点自动授予运行时权限** | A、B | device.py:19 | 「允许/始终允许」在代点名单中——正是 Android 权限对话框的授权按钮；screen()/launch_app() 自动执行，不耗预算、不进审计 |

## P1 — 功能/正确性

| # | 发现 | 命中 | 位置 | 说明 |
|---|---|---|---|---|
| F-07 | docker 二进制缺失裸抛 `FileNotFoundError` | A、D | backend/redroid.py:29 | `E_DOCKER_MISSING` 分支不可达；异常穿透到 `/phone status` 未处理、工具层误报 `internal_error` |
| F-08 | swipe 无屏幕边界收口 | A + 人工 | service.py:258-272 | distance=2000 时端点远超屏幕（1080 宽屏起点 x=1540/终点 x=-460）；tap 有越界检查而 swipe 没有 |
| F-09 | 包名正则拒绝真实包名 | D + 人工 | config.py:10 | 拒大写与连字符；实证 `com.Slack`（Play Store 真实包名）无法配置 |
| F-10 | redroid serial 缓存不自愈 | D + 人工 | backend/redroid.py:64 | `_serial` 已设即直接返回 ready，容器外部被停后恢复路径断裂 |
| F-11 | 默认镜像 tag 不存在 | C | _conf_schema.json:23 | `12.0.0_64-nativebridge` 官方不发布（官方命名 `_64only-latest`；native bridge 变体需自建）→ 开箱 `docker run` 即 manifest unknown |
| F-12 | REDROID_EXTRA_ARGS 位置错误 | A | backend/redroid.py:86-98 | 拼在镜像名之前——redroid 的 `androidboot.*` 参数必须放镜像后，配置描述承诺的「gpu 加速」传不进去 |
| F-13 | click_text 返回 bounds 是 dict 不是 list | A、C | device.py:188-194 | u2 `info["bounds"]` 为 `{left,top,right,bottom}`，签名与读屏契约均声明 `[x1,y1,x2,y2]` |
| F-14 | mask_text 前 12 字符泄漏短敏感输入 | B | audit.py:13-16, service.py:247 | 6 位验证码近全文落盘（LLM 代输验证码是典型场景） |
| F-15 | 预算在连接前扣减 | A + 人工 | service.py:127-129 | 设备离线重试烧光预算锁 5 分钟 |
| F-16 | LLM 工具无会话门控 | B | main.py:56 | 工具全局注册，群聊任意成员可经提示注入驱动手机（`/phone` 指令有 ADMIN 门控，工具没有） |
| F-17 | 截图路径回传模型，与三处文档矛盾 | A、B、E + 人工 | service.py:212, tools/observe.py:46 | README/设计文档声称「不回传模型」，代码仍返回绝对路径进 LLM 上下文 |
| F-18 | real 后端 ADB 调用无超时 | E | backend/real.py | connect/device_list/shell 裸 to_thread，违反 §3.2 外部 IO 超时 |
| F-19 | 契约测试恒真 | D | tests/test_series_compliance.py:30-48 | `test_contract_shape` 断言测试自己手造的 dict，从不调用实现；改坏 `diagnostic_log_contract()` 照样绿 |

## P2 — 规范/健壮性

| # | 发现 | 命中 | 位置 | 说明 |
|---|---|---|---|---|
| F-20 | diagnostics clear() 后 seq 归 1、stream_id 不变 | A | series_diagnostics.py | 聚合端持旧游标时新事件被过滤且不触发游标重置，违反 §5.1 |
| F-21 | webui 未知面板/动作抛异常而非「返回」错误码 | A、B、C、E | webui.py | §5.3 字面要求返回；网关对 unknown action 不预校验，插件异常将穿透 |
| F-22 | short_desc 违反 §2.4 | E | metadata.yaml:3 | 未以「凝心溯溪系列通模块」开头（现役 8 插件全部合规） |
| F-23 | 4 处日志中文且无 `[companion-phone]` 前缀 | E | service.py:353/366, audit.py:65, tools/base.py:28 | 违反 §3.6/§7.2；设计文档声称已改、实际漏改 |
| F-24 | 命令权限门控零测试 | E | tests/ | §8 必测路径第 1 项缺失 |
| F-25 | `check_tap_xy` 零尺寸 fail-open | B、D | safety.py:67-69 | screen_size 返回 (0,0) 时越界检查失效 |
| F-26 | `audit_recent(0)` 触发 `-0` 切片陷阱 | D | audit.py:87 | 返回全部记录而非 0 条 |
| F-27 | `_get_session` 并发竞态 | A、D | service.py:67-80 | 冷启动并发时重复建会话/重复 docker run |
| F-28 | `_int` 静默回退 + bool/负值漏防 | D + 人工 | config.py | `int(True)==1`、负延时区间通过校验、SCREENSHOT_KEEP=0 删光截图 |
| F-29 | config 数值无下界校验 | A、D | config.py | ACTION_MAX_PER_TURN=0、TASK_MAX_STEPS=0（tool_loop_agent 必炸）等 |
| F-30 | `clear_today` 无文件也返回 True | A | audit.py | 与 docstring 矛盾，webui 提示分支成死代码 |
| F-31 | click_text 元素消失竞态误报 device_offline | C | device.py:188-194 | exists 与 click 之间消失应报 element_not_found |
| F-32 | screen 审计 umo 恒空 | A、E | service.py:201 | 最高频动作无归属 |
| F-33 | Pillow 零引用依赖 | A | requirements.txt | 代码无 `import PIL`（u2 传递依赖已覆盖） |
| F-34 | `_int_arg` 接受 float 截断 | A | tools/base.py | schema 声明 integer，1.9 静默变 1 |
| F-35 | set_fastinput_ime v3 已弃用，ascii_fallback 语义失真 | C | device.py:200-212 | v3 实际回退路径是 u2 内部 set_text |
| F-36 | docker 命令超时误归 `docker_missing` | A、E | backend/redroid.py:40 | 语义失真 |

## P3 — 打磨（摘录，详见各盲测报告）

swipe/press_key 参数错误不落审计（A）；tap 无坐标抖动而 CHANGELOG 声称有（E）；`ACTION_MAX_PER_TURN` 描述漏列 launch_app（E）；数据目录默认权限过宽、审计文件可被本机其他用户读（B）；`REDROID_EXTRA_ARGS` 可写 `-p 0.0.0.0` 击穿回环绑定，privileged 容器威胁模型未文档化（B）；屏幕文本本身是注入源未在提示词声明（B）；`screen_on()` 死代码（C）；负坐标 bounds 节点被静默丢弃（D，决策：保留丢弃行为但注释说明）；`_DATA_DIR` 回退不告警（A）；`mask_text`/「正文永不落盘」措辞与 12 字符前缀矛盾（E）；设计文档「今日动作数」「30 例测试」等漂移（E）；`PLUGIN_VERSION/__version__` 三处冗余（E）。

## 做对了的（盲测确认，抽录）

分层依赖方向单一；docker argv 列表 exec 无 shell 注入；ADB 绑回环；审计 umo 哈希 + 写失败不阻断；诊断契约与 §5.1 逐字段一致；webui 渲染契约与网关实测兼容；AstrBot 8 处 API 调用逐签名核对全部正确（tool_loop_agent 参数、StarTools.get_data_dir、add_llm_tools 等）；u2 的 swipe 秒级 duration、del 键名、app_current 用法正确；版本同步有测试断言；v2 入口门控的注释与测试存在（但被 F-05 证伪其完备性）。
