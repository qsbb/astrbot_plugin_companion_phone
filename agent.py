from __future__ import annotations

from typing import Any

from astrbot.core.agent.tool import ToolSet

from .config import PhoneConfig
from .service import PhoneService
from .tools import create_device_tools

PHONE_AGENT_SYSTEM_PROMPT = """你正在操作一部安卓手机来完成给定任务。工作准则：
1. 先 companion_phone_screen 观察当前屏幕，再决定动作；不要盲目点按。
2. 优先 companion_phone_click_text 按文本点按，其次才用 companion_phone_tap 坐标。
3. 每次会改变屏幕状态的操作后，先 screen 或 companion_phone_wait_element 确认结果。
4. 输入文本前确认输入框已获得焦点。
5. 遇到 element_not_found：重新 screen 观察，可能需要滑动或返回。
6. 遇到 high_risk_blocked：停止该方向，在最终答复中说明该步骤被安全策略拦截。
7. 任务完成、或判断无法完成时，停止调用工具并总结过程。
8. 保持耐心，一次只做一个动作。"""


async def run_phone_task(
    service: PhoneService,
    context: Any,
    event: Any,
    goal: str,
    cfg: PhoneConfig,
) -> Any:
    """官方 tool_loop_agent 驱动的多步手机任务。

    任务预算独立于常规对话预算（由 SafetyGate 的一次性计数器管理），
    与 tool_loop_agent 的 max_steps 双重兜底。
    """
    umo = event.unified_msg_origin
    service.task_budget_start(umo)
    try:
        prov_id = await context.get_current_chat_provider_id(umo)
        tools = ToolSet(create_device_tools(service))
        return await context.tool_loop_agent(
            event=event,
            chat_provider_id=prov_id,
            prompt=goal,
            system_prompt=PHONE_AGENT_SYSTEM_PROMPT,
            tools=tools,
            max_steps=cfg.task_max_steps,
            tool_call_timeout=cfg.task_tool_timeout,
        )
    finally:
        service.task_budget_stop(umo)
