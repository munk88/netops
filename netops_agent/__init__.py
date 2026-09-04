"""netops-mvp —— 最小网络运维 Agent MVP。

覆盖课程中仍有效的技术栈：
- ReAct 核心循环（思考 -> 调用工具 -> 观察）
- MCP 协议（官方 SDK，Agent 经标准通道调用网络工具）
- Harness 三层权限（只读 / 测试 / 变更）
- RAG 知识库（轻量 TF-IDF，作为 MCP 工具接入）
- 记忆系统（Session + 长期记忆）
- 报告生成（Markdown / HTML）
"""

__version__ = "0.1.0"
