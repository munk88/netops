"""ReAct 核心循环：LLM 思考 -> Harness 裁决 -> MCP 调用工具 -> 观察 -> 再思考。

工具一律经 MCP 标准通道调用（Client <-> Server），不直接调 Python 函数。
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable

from mcp.client import Client

from .harness import Harness, ConfirmFn
from .llm import FINAL_PREFIX, TOOL_PREFIX, parse_model_output
from .memory import Memory
from .mcp_tools import build_tool_schema

SYSTEM_TPL = """你是「网络运维 Agent」，一个连接真实网络设备的智能运维助手。

可用的工具（全部经 MCP 标准协议调用，括号内是权限级别）：
{tools}

规则：
1. 你需要完成用户任务时，先思考需要哪些信息，再调用工具获取。
2. 涉及知识（命令、排障步骤、配置规范）时，调用 search_kb 检索运维知识库（RAG）。
3. 你只能按以下两种格式之一输出，不要输出其他内容：
   {tool_prefix} {{"name":"工具名","arguments":{{参数}}}}
   {final_prefix} 最终回答
4. 工具调用结果会以「观察」形式返回给你，基于观察继续决策，直到完成。
5. 高风险操作（配置变更）需要人工审批，Harness 会拦截并提示，你如实汇报结果。

{longterm}
"""


class Agent:
    def __init__(
        self,
        llm,
        mcp_server,
        harness: Harness,
        memory: Memory,
        max_steps: int = 14,
    ):
        self._llm = llm
        self._server = mcp_server
        self._harness = harness
        self._memory = memory
        self._max_steps = max_steps
        self.trace: list[dict] = []

    # -- 供 CLI / Web 等设置确认函数 --
    def set_confirm_fn(self, fn: ConfirmFn | None) -> None:
        self._harness.confirm_fn = fn

    def _system_prompt(self) -> str:
        tools = "\n".join(
            f"- {t['name']}: {t['description']}（权限：{t['permission']}）"
            for t in build_tool_schema()
        )
        longterm = self._memory.build_system_facts()
        return SYSTEM_TPL.format(
            tools=tools,
            tool_prefix=TOOL_PREFIX,
            final_prefix=FINAL_PREFIX,
            longterm=longterm,
        )

    async def run(
        self,
        user_input: str,
        on_step: Callable[[dict], Awaitable[None]] | None = None,
    ) -> dict:
        """执行一次用户请求，返回 {answer, steps}。on_step 为每步回调（用于流式推送）。"""
        self.trace = []
        system = self._system_prompt()
        messages: list[dict] = [{"role": "system", "content": system}]
        # 注入 Session 历史（截断最近 6 条，避免过长）
        for m in self._memory.history()[-6:]:
            messages.append(m)
        messages.append({"role": "user", "content": user_input})

        answer = ""
        steps: list[dict] = []

        async with Client(self._server) as client:
            for _ in range(self._max_steps):
                raw = self._llm.chat(messages)
                kind, call, text = parse_model_output(raw)

                if kind == "final":
                    answer = text
                    steps.append({"kind": "final", "content": text})
                    if on_step:
                        await on_step({"kind": "final", "content": text})
                    break

                if call is None:  # 解析失败
                    answer = text
                    steps.append({"kind": "error", "content": text})
                    if on_step:
                        await on_step({"kind": "error", "content": text})
                    break

                name, args = call["name"], call.get("arguments") or {}

                # 1) Harness 权限裁决（异步，支持 Web 弹窗确认）
                allowed, note = await self._harness.acheck(name, args)
                if not allowed:
                    obs = f"工具 {name} 未执行：{note}"
                    messages += [
                        {"role": "assistant", "content": raw},
                        {"role": "tool", "content": obs},
                    ]
                    step = {"kind": "blocked", "tool": name, "note": note}
                    steps.append(step)
                    if on_step:
                        await on_step(step)
                    continue

                # 2) 经 MCP 标准通道调用工具
                try:
                    result = await client.call_tool(name, args)
                    text_result = "".join(
                        c.text for c in result.content if hasattr(c, "text")
                    )
                except Exception as e:  # noqa: BLE001
                    text_result = f"[ERROR] {e}"

                # 3) 抽取长期记忆
                self._memory.extract_facts(name, args, text_result)

                messages += [
                    {"role": "assistant", "content": raw},
                    {"role": "tool", "content": text_result},
                ]
                step = {
                    "kind": "tool",
                    "tool": name,
                    "args": args,
                    "note": note,
                    "observation": text_result,
                }
                steps.append(step)
                if on_step:
                    await on_step(step)
            else:
                answer = f"达到最大步数（{self._max_steps}）仍未完成，请简化任务。"

        # 写回 Session
        self._memory.add("user", user_input)
        self._memory.add("assistant", answer)
        return {"answer": answer, "steps": steps}
