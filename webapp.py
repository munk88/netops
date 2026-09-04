"""netops-mvp Web 控制台（FastAPI 后端）。

提供：
- POST /api/chat        提交自然语言指令，后台启动 Agent（ReAct）运行
- GET  /api/stream      SSE 流式推送执行轨迹（工具调用 / 观察 / 需确认 / 最终回答）
- POST /api/confirm     Harness 确认（批准 / 拒绝 测试与变更）
- GET  /api/devices     设备状态仪表盘数据
- GET  /api/report      最新巡检报告（Markdown / HTML）
- GET  /api/status      运行状态与大模型模式

运行： ./.venv/bin/python webapp.py   然后浏览器打开 http://127.0.0.1:8000
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from netops_agent import device as dev
from netops_agent.agent import Agent
from netops_agent.harness import Harness
from netops_agent.llm import make_llm
from netops_agent.mcp_tools import build_mcp_server
from netops_agent.memory import Memory
from netops_agent.report import build_markdown, save_report

BASE = Path(__file__).resolve().parent
STATIC = BASE / "static"
REPORTS = BASE / "reports"


def load_config() -> dict:
    p = BASE / "config.json"
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return {}


# ---------------- 会话状态（本地单会话） ----------------
class _Session:
    def __init__(self) -> None:
        self.queue: asyncio.Queue | None = None
        self.running = False
        self.confirm: "ConfirmCoordinator | None" = None
        self.last_report: dict | None = None


sess = _Session()


class ConfirmCoordinator:
    """把 Harness 的确认请求转成 Web 弹窗：发事件 -> 挂起 -> 等用户点按钮。"""

    def __init__(self, push):
        self._pending: dict[int, asyncio.Future] = {}
        self._counter = 0
        self._push = push

    async def request(self, title: str, level: str) -> bool:
        self._counter += 1
        cid = self._counter
        fut = asyncio.get_running_loop().create_future()
        self._pending[cid] = fut
        await self._push({"type": "confirm_required", "cid": cid, "title": title, "level": level})
        try:
            return bool(await asyncio.wait_for(fut, timeout=600))
        except asyncio.TimeoutError:
            return False

    def resolve(self, cid: int, decision: bool) -> bool:
        fut = self._pending.pop(cid, None)
        if fut is None or fut.done():
            return False
        fut.set_result(bool(decision))
        return True


app = FastAPI(title="netops-mvp 网络运维 Agent 控制台")


# ---------------- API ----------------
class ChatReq(BaseModel):
    message: str


class ConfirmReq(BaseModel):
    cid: int
    decision: bool


@app.post("/api/chat")
async def chat(req: ChatReq) -> dict:
    if sess.running:
        raise HTTPException(409, "已有任务运行中，请稍候再试")
    if not req.message.strip():
        raise HTTPException(422, "指令不能为空")

    q: asyncio.Queue = asyncio.Queue()
    sess.queue = q
    confirm = ConfirmCoordinator(lambda ev: q.put(ev))
    sess.confirm = confirm

    config = load_config()
    llm = make_llm(config)
    harness = Harness(audit_path=BASE / "audit.jsonl", confirm_fn=confirm.request)
    memory = Memory(longterm_path=BASE / "memory.json")
    server = build_mcp_server(harness, memory)
    agent = Agent(llm=llm, mcp_server=server, harness=harness, memory=memory)

    async def on_step(step: dict) -> None:
        await q.put({"type": "step", "data": step})

    async def run() -> None:
        sess.running = True
        try:
            await q.put({"type": "status", "text": "已收到指令，Agent 开始运行（ReAct 循环：思考 → 裁决 → MCP 调用 → 观察）..."})
            result = await agent.run(req.message, on_step=on_step)
            await q.put({"type": "final", "text": result["answer"]})
            out = save_report(result["steps"], result["answer"], REPORTS)
            sess.last_report = {
                "markdown": build_markdown(result["steps"], result["answer"]),
                "html_path": out["html"],
            }
            await q.put({"type": "report_ready"})
        except Exception as e:  # noqa: BLE001
            await q.put({"type": "error", "text": f"{type(e).__name__}: {e}"})
        finally:
            sess.running = False
            await q.put({"type": "done"})

    asyncio.create_task(run())
    return {"ok": True}


@app.get("/api/stream")
async def stream():
    async def gen():
        q = sess.queue
        if q is None:
            yield 'data: {"type":"error","text":"当前没有运行中的任务"}\n\n'
            return
        while True:
            ev = await q.get()
            yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
            if ev.get("type") == "done":
                break

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/confirm")
async def confirm(req: ConfirmReq) -> dict:
    if sess.confirm is None:
        raise HTTPException(409, "没有待确认的操作")
    ok = sess.confirm.resolve(req.cid, req.decision)
    if not ok:
        raise HTTPException(404, "确认请求不存在或已处理")
    return {"ok": True}


@app.get("/api/devices")
async def devices() -> dict:
    out = {}
    for name in dev.list_devices():
        d = dev.get_device_status(name)
        d["device"] = name
        out[name] = d
    return out


@app.get("/api/report")
async def report() -> dict:
    if sess.last_report:
        return sess.last_report
    md_file = REPORTS / "report.md"
    if md_file.exists():
        return {
            "markdown": md_file.read_text(encoding="utf-8"),
            "html_path": str(REPORTS / "report.html"),
        }
    return {"markdown": "", "html_path": ""}


@app.get("/report-html")
async def report_html():
    """打开最新 HTML 版巡检报告。"""
    path = REPORTS / "report.html"
    if not path.exists():
        raise HTTPException(404, "暂无报告，先运行一次「全网巡检并生成报告」")
    return FileResponse(path)


@app.get("/api/status")
async def status() -> dict:
    config = load_config()
    has_key = bool(config.get("api_key")) or (
        config.get("provider") == "ollama" and bool(config.get("base_url"))
    )
    return {
        "running": sess.running,
        "llm_mode": "llm" if has_key else "rule",
        "model": config.get("model", "-"),
    }


# ---------------- 静态页面 ----------------
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/")
async def index():
    return FileResponse(STATIC / "index.html")


if __name__ == "__main__":
    import uvicorn

    print("netops-mvp Web 控制台已启动： http://127.0.0.1:8000")
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="warning")
