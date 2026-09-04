"""一键端到端演示：零配置（无 API key）跑通完整「全网巡检 -> 排障 -> 修复 -> 报告」。

演示会展示课程技术栈各环节：
  ReAct 循环 / MCP 标准通道 / Harness 三层权限 / RAG 知识库 / 记忆 / 报告导出
"""

from __future__ import annotations

import asyncio
import json
import sys
import time

from netops_agent.agent import Agent
from netops_agent.harness import Harness, LEVEL_CHANGE
from netops_agent.llm import RuleLLM
from netops_agent.mcp_tools import build_mcp_server
from netops_agent.memory import Memory
from netops_agent.report import save_report

AUDIT = "audit.jsonl"


def _approve_all(_title: str, _level: str) -> bool:
    """演示模式：高风险操作自动放行（生产环境必须人工审批）。"""
    return True


def _print_steps(steps: list[dict]) -> None:
    for s in steps:
        kind = s.get("kind")
        if kind == "tool":
            print(f"   ▶ 工具 [{s['tool']}]  {s.get('note','')}")
            print(f"      参数: {json.dumps(s.get('args'), ensure_ascii=False)}")
            obs = s.get("observation", "")
            print(f"      观察: {obs[:220]}{'...' if len(obs) > 220 else ''}")
        elif kind == "blocked":
            print(f"   ⛔ 拦截 [{s.get('tool')}]  {s.get('note')}")
        elif kind == "final":
            print(f"   ✔ 最终回答")


def main() -> int:
    print("=" * 60)
    print(" netops-mvp 端到端演示（无 API key · 规则引擎 + 模拟设备）")
    print("=" * 60)
    time.sleep(0.5)

    harness = Harness(audit_path=AUDIT, confirm_fn=_approve_all)
    memory = Memory(longterm_path="memory.json")
    server = build_mcp_server(harness, memory)
    agent = Agent(llm=RuleLLM(), mcp_server=server, harness=harness, memory=memory)

    request = "全网巡检并生成报告，发现接口 down 就按知识库排障并恢复"

    print("\n[1/5] ReAct 循环启动，指令：")
    print(f'   "{request}"')
    print("\n[2/5] Agent 开始 思考->调用工具(MCP)->观察 ...")
    result = asyncio.run(agent.run(request))
    _print_steps(result["steps"])

    print("\n[3/5] 最终结论：")
    print("  " + result["answer"].replace("\n", "\n  "))

    print("\n[4/5] Harness 审计日志（audit.jsonl）：")
    try:
        for line in open(AUDIT, encoding="utf-8").read().strip().splitlines()[-4:]:
            rec = json.loads(line)
            print(f"   {rec['ts']}  {rec['tool']:<22} {rec['decision']}")
    except (OSError, json.JSONDecodeError):
        print("   （无审计记录）")

    print("\n[5/5] 生成结构化报告：")
    out = save_report(result["steps"], result["answer"], "reports")
    print(f"   {out['markdown']}")
    print(f"   {out['html']}")

    print("\n" + "=" * 60)
    print(" 演示完成。接入真实大模型与真实设备的方法见 README.md")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
