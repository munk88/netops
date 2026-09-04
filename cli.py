"""netops-mvp 交互式命令行入口。

用法：
  python cli.py                       # 进入对话（无 key 自动用规则引擎）
  python cli.py --report              # 每次回答后生成 report.md / report.html
  python cli.py --approve-change      # 配置变更自动批准（试行演示用，生产勿开）
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from netops_agent.agent import Agent
from netops_agent.harness import Harness, LEVEL_CHANGE
from netops_agent.llm import make_llm
from netops_agent.mcp_tools import build_mcp_server
from netops_agent.memory import Memory
from netops_agent.report import save_report


def load_config(path: str = "config.json") -> dict:
    p = Path(path)
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            print(f"[warn] {path} 解析失败，使用默认配置")
    return {}


def make_confirm_fn(auto_approve: bool):
    """构造 Harness 确认函数。

    - 显式 --approve-change：自动批准（仅演示）。
    - 非交互模式（stdin 非 TTY，如 --once 或管道）：自动批准并告警，避免阻塞。
    - 交互模式：按权限交互确认。
    """
    non_interactive = not sys.stdin.isatty()

    def confirm(title: str, level: str) -> bool:
        if auto_approve or non_interactive:
            if non_interactive:
                print(f"    [Harness] 非交互模式，{title} -> 自动确认（演示行为，生产必须人工审批）")
            else:
                print(f"    [Harness] {title} -> 自动批准（demo 模式）")
            return True
        if level == LEVEL_CHANGE:
            answer = input(f"    {title}。输入 APPROVE 以批准，否则拒绝：").strip()
            return answer.upper() == "APPROVE"
        answer = input(f"    {title} [y/N]：").strip().lower()
        return answer in ("y", "yes")

    return confirm


def build_agent(config: dict, auto_approve: bool, workdir: str = ".") -> Agent:
    workdir = Path(workdir)
    llm = make_llm(config)
    harness = Harness(audit_path=workdir / "audit.jsonl", confirm_fn=make_confirm_fn(auto_approve))
    memory = Memory(longterm_path=workdir / "memory.json")
    server = build_mcp_server(harness, memory)
    return Agent(llm=llm, mcp_server=server, harness=harness, memory=memory)


def main() -> None:
    ap = argparse.ArgumentParser(description="网络运维 Agent MVP")
    ap.add_argument("--report", action="store_true", help="回答后生成 report.md/report.html")
    ap.add_argument("--approve-change", action="store_true", help="配置变更自动批准（仅演示）")
    ap.add_argument("--config", default="config.json")
    ap.add_argument("--once", help="执行单条指令后退出")
    args = ap.parse_args()

    config = load_config(args.config)
    agent = build_agent(config, args.approve_change)

    async def run(text: str):
        print("\n" + "=" * 56)
        print(f"指令：{text}")
        print("=" * 56)
        result = await agent.run(text)
        for s in result["steps"]:
            kind = s.get("kind")
            if kind == "tool":
                print(f"  -> 调用工具 [{s['tool']}] {s.get('note','')}")
            elif kind == "blocked":
                print(f"  !! 拦截 [{s.get('tool')}]：{s.get('note')}")
            elif kind == "final":
                print("  -- 最终回答 --")
        print("\n" + result["answer"])
        if args.report:
            out = save_report(result["steps"], result["answer"], Path("reports"))
            print(f"\n[report] 已生成：{out['markdown']} 与 {out['html']}")

    if args.once:
        asyncio.run(run(args.once))
        return

    print("网络运维 Agent MVP（输入 quit/exit 退出，输入 help 查看示例指令）")
    while True:
        try:
            text = input("\n> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not text:
            continue
        if text.lower() in ("quit", "exit"):
            break
        if text.lower() == "help":
            print("  示例：全网巡检并生成报告 / ping 测试 R2 / 接口 down 怎么排障 / 恢复 R2 接口配置")
            continue
        asyncio.run(run(text))


if __name__ == "__main__":
    sys.exit(main())
