"""MCP 工具层：把网络运维能力封装为标准 MCP Server 的工具。

Agent 不直接调用 Python 函数，而是通过 MCP Client（标准通道）调用本 Server 暴露的
tools —— 对应课程 Ch.4「AI 与网络设备标准通道打通」。
每个工具同时登记到 Harness 的权限分级：read 自主 / test 确认 / change 审批。
"""

from __future__ import annotations

import json

from mcp.server.mcpserver import MCPServer

from . import device as dev
from . import rag
from .harness import Harness, LEVEL_CHANGE, LEVEL_READ, LEVEL_TEST
from .memory import Memory

# 工具 -> 权限级别（Harness 三层）
TOOL_LEVELS: dict[str, str] = {
    "list_devices": LEVEL_READ,
    "get_device_status": LEVEL_READ,
    "search_kb": LEVEL_READ,
    "run_inspection": LEVEL_TEST,
    "apply_config_change": LEVEL_CHANGE,
}

# 工具 -> 供模型了解的中文说明（拼进 system prompt）
TOOL_DESCRIPTIONS: dict[str, str] = {
    "list_devices": "列出网络中的所有设备名。只读。",
    "get_device_status": "读取指定设备的状态（status/cpu/mem/interfaces/log）。只读。参数：device。",
    "search_kb": "在运维知识库中检索相关排障/命令知识。参数：query。只读。",
    "run_inspection": "对设备执行测试类操作（如 ping 连通性测试）。参数：device, kind。测试操作，需人工确认。",
    "apply_config_change": "对设备应用配置变更（恢复接口等）。参数：device, config。高风险变更，必须人工审批。",
}


def _to_json(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=1)


def build_mcp_server(harness: Harness, memory: Memory) -> MCPServer:
    """构建 MCP Server 并注册全部网络运维工具 + Harness 权限。"""
    server = MCPServer("netops-mvp", version="0.1.0")

    @server.tool()
    def list_devices() -> str:
        return _to_json({"devices": dev.list_devices()})

    @server.tool()
    def get_device_status(device: str) -> str:
        try:
            data = dev.get_device_status(device)
            data["device"] = device  # 结果中带上设备名，便于模型理解
            return _to_json(data)
        except KeyError:
            return _to_json({"error": f"设备 {device} 不存在", "known": dev.list_devices()})

    @server.tool()
    def search_kb(query: str, top_k: int = 3) -> str:
        hits = rag.search_kb(query, top_k)
        return _to_json({"query": query, "results": hits})

    @server.tool()
    def run_inspection(device: str, kind: str = "ping") -> str:
        if kind == "ping":
            return _to_json(dev.ping(device))
        return _to_json({"error": f"不支持的测试类型 {kind}，当前支持 ping"})

    @server.tool()
    def apply_config_change(device: str, config: str) -> str:
        return _to_json(dev.apply_config_change(device, config))

    # 登记 Harness 权限
    for name, level in TOOL_LEVELS.items():
        harness.register(name, level)

    return server


def build_tool_schema() -> list[dict]:
    """把工具清单 + 权限等级转成 system prompt 里的工具说明。"""
    return [
        {"name": n, "description": TOOL_DESCRIPTIONS[n], "permission": TOOL_LEVELS[n]}
        for n in TOOL_LEVELS
    ]
