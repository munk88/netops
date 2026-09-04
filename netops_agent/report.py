"""结构化报告生成：把 Agent 执行轨迹（steps + answer）导出为 Markdown / HTML。"""

from __future__ import annotations

import html
import time
from pathlib import Path


def _fmt_ts() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def build_markdown(steps: list[dict], answer: str) -> str:
    lines = [
        "# 网络运维 Agent 巡检报告",
        "",
        f"- 生成时间：{_fmt_ts()}",
        "- 生成方式：netops-mvp（ReAct + MCP + Harness + RAG）",
        "",
        "## 执行轨迹",
        "",
    ]
    for i, s in enumerate(steps, 1):
        kind = s.get("kind")
        if kind == "tool":
            lines.append(f"### {i}. 调用工具 `{s['tool']}`（{s.get('note','')}）")
            lines.append("")
            lines.append(f"参数：`{s.get('args')}`")
            lines.append("")
            lines.append("```text")
            lines.append(str(s.get("observation", "")))
            lines.append("```")
            lines.append("")
        elif kind == "blocked":
            lines.append(f"### {i}. 工具被拦截：`{s.get('tool')}`")
            lines.append("")
            lines.append(f"> {s.get('note')}")
            lines.append("")
        elif kind == "final":
            lines.append(f"### {i}. 最终回答")
            lines.append("")
            lines.append(str(s.get("content", "")))
            lines.append("")
    lines += ["## 结论", "", answer, ""]
    return "\n".join(lines)


def _steps_to_html(steps: list[dict]) -> str:
    parts: list[str] = []
    for i, s in enumerate(steps, 1):
        kind = s.get("kind")
        if kind == "tool":
            note = html.escape(s.get("note", ""))
            parts.append(
                f'<div class="step"><div class="step-title">#{i} 调用工具 '
                f'<code>{html.escape(s["tool"])}</code> <span class="muted">({note})</span></div>'
                f'<div class="muted">参数：<code>{html.escape(str(s.get("args")))}</code></div>'
                f'<pre>{html.escape(str(s.get("observation", "")))}</pre></div>'
            )
        elif kind == "blocked":
            parts.append(
                f'<div class="step blocked"><div class="step-title">#{i} 工具被拦截 '
                f'<code>{html.escape(s.get("tool",""))}</code></div>'
                f'<div>{html.escape(s.get("note",""))}</div></div>'
            )
        elif kind == "final":
            parts.append(
                f'<div class="step final"><div class="step-title">#{i} 最终回答</div>'
                f'<div>{html.escape(str(s.get("content","")))}</div></div>'
            )
        elif kind == "error":
            parts.append(
                f'<div class="step blocked"><div class="step-title">#{i} 错误</div>'
                f'<div>{html.escape(str(s.get("content","")))}</div></div>'
            )
    return "\n".join(parts)


def build_html(steps: list[dict], answer: str) -> str:
    body = _steps_to_html(steps)
    ans_html = html.escape(answer).replace("\n", "<br>")
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>网络运维 Agent 巡检报告</title>
<style>
  body {{ font-family: -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif;
         max-width: 760px; margin: 24px auto; padding: 0 16px; color: #1A1B1C; line-height: 1.6; }}
  h1 {{ font-size: 20px; }}
  .meta {{ color: #6B7280; font-size: 13px; }}
  .step {{ border: 1px solid #E4E3DD; border-left: 4px solid #8BC8EA; border-radius: 8px;
           padding: 10px 14px; margin: 10px 0; }}
  .step.blocked {{ border-left-color: #EA6668; }}
  .step.final {{ border-left-color: #52C41A; background: #f7fbf4; }}
  .step-title {{ font-weight: 600; margin-bottom: 4px; }}
  .muted {{ color: #6B7280; font-size: 12px; }}
  pre {{ background: #f6f6f4; padding: 8px 10px; border-radius: 6px; overflow-x: auto; font-size: 12px; }}
  .conclusion {{ background: #f0f7ff; border-radius: 8px; padding: 12px 16px; margin-top: 16px; }}
</style>
</head>
<body>
<h1>网络运维 Agent 巡检报告</h1>
<div class="meta">生成时间：{_fmt_ts()} ｜ netops-mvp（ReAct + MCP + Harness + RAG）</div>
<h2>执行轨迹</h2>
{body}
<div class="conclusion"><h2>结论</h2><div>{ans_html}</div></div>
</body>
</html>
"""


def save_report(steps: list[dict], answer: str, out_dir: str | Path = ".") -> dict:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    md = build_markdown(steps, answer)
    htm = build_html(steps, answer)
    md_path = out_dir / "report.md"
    html_path = out_dir / "report.html"
    md_path.write_text(md, encoding="utf-8")
    html_path.write_text(htm, encoding="utf-8")
    return {"markdown": str(md_path), "html": str(html_path)}
