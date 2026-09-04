# netops-mvp —— 最小网络运维 Agent MVP

把课程中"仍然有效"的技术栈，做成一个能**零配置立刻跑通**的最小可运行系统。

## 覆盖的课程技术点

| 课程章节 | 技术 | 本项目实现 |
|---|---|---|
| Ch.2 | 大模型调用 | `llm.py`：OpenAI 兼容 API（豆包/DeepSeek/Qwen/Ollama/OpenAI），无 key 自动降级规则引擎 |
| Ch.3 | Agent 核心循环（ReAct） | `agent.py`：思考 → Harness 裁决 → MCP 调工具 → 观察 → 再思考 |
| Ch.4 | MCP 标准协议 | `mcp_tools.py`：官方 MCP SDK，Agent 经 MCP Client 调用 Server 暴露的网络工具 |
| Ch.6 | Skills/工具封装 | MCP tools：list_devices / get_device_status / run_inspection / apply_config_change / search_kb |
| Ch.7 | RAG 知识库 | `rag.py`：切块 + TF-IDF 检索，作为 MCP 工具 search_kb 接入 |
| Ch.8 | 记忆系统 | `memory.py`：Session 短时 + 长期记忆 JSON（跨会话记住设备状态） |
| Ch.9 | Harness 三层权限 | `harness.py`：只读自主 / 测试确认 / 变更审批 + 审计日志 |
| Ch.12 | 报告导出 | `report.py`：Markdown / HTML 结构化报告 |

## 快速开始

```bash
cd netops-mvp
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt

# 方式一：一键端到端演示（无需任何 API key）
./.venv/bin/python demo.py

# 方式二：交互式命令行（同样无需 key，自动用规则引擎）
./.venv/bin/python cli.py
# 输入示例：
#   全网巡检并生成报告
#   ping 测试 R2
#   接口 down 怎么排障
#   恢复 R2 接口配置
```

演示场景会自动走完：`列设备 → 逐台查状态 → 发现 R2 接口 down → 检索 RAG 知识库 →
ping 测试（需确认）→ 应用配置变更（需审批）→ 复核状态 → 生成 Markdown/HTML 报告`。

## 接入真实大模型（可选）

编辑 `config.json`，填入任一 OpenAI 兼容服务的参数即可：

- **豆包 / 火山方舟**：`base_url` 填方舟兼容地址，`api_key` 填你的 key，`model` 填模型名
- **DeepSeek**：`base_url`: `https://api.deepseek.com/v1`，`model`: `deepseek-chat`
- **OpenAI**：`base_url`: `https://api.openai.com/v1`，`model`: `gpt-4o-mini`
- **本地 Ollama**：`provider`: `ollama`，`base_url`: `http://localhost:11434/v1`，`model`: 你拉取的模型

> 接入真实大模型后，Agent 由"规则引擎"升级为真正的 LLM 推理循环（同一套 MCP 管道）。

## 接入真实网络设备（可选）

`device.py` 当前为模拟设备。接入真实设备只需把工具内部的 `dev.*` 调用替换为
**netmiko/Paramiko（SSH）** 或厂商 API 的读写操作，例如：

```python
from netmiko import ConnectHandler
conn = ConnectHandler(device_type="huawei", ip="10.0.0.1", username="u", password="p")
conn.send_command("display interface brief")   # 只读
conn.send_config_set(["interface GE0/0/0", "shutdown", "no shutdown"])  # 变更
```

## 生产化注意（Harness 原则）

- `--approve-change` 仅用于演示；生产环境配置变更必须**人工审批 + 双人复核**。
- 审计日志 `audit.jsonl` 全量记录每一次工具调用的时间、参数与裁决，务必保留。
- 接入真实设备后，建议只读工具用只读账号、变更工具走提权 + 审批流。

## 目录结构

```
netops-mvp/
├── cli.py                 # 交互式命令行入口
├── demo.py                # 一键端到端演示
├── config.json            # 大模型配置（留空走规则引擎）
├── requirements.txt
├── netops_agent/
│   ├── agent.py           # ReAct 核心循环
│   ├── llm.py             # LLM 客户端 + 规则降级
│   ├── mcp_tools.py       # MCP Server + 工具封装
│   ├── harness.py         # Harness 三层权限 + 审计
│   ├── rag.py             # 最小 RAG（TF-IDF）
│   ├── memory.py          # Session + 长期记忆
│   ├── device.py          # 模拟设备（可替换为 netmiko）
│   └── report.py          # Markdown/HTML 报告
├── reports/               # 生成的报告（demo 运行后出现）
├── audit.jsonl            # Harness 审计日志
└── memory.json            # 长期记忆
```
