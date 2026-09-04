"""LLM 层：OpenAI 兼容 API（豆包/DeepSeek/Qwen/Ollama/OpenAI 均可） + 无 key 规则降级。

规则降级引擎（RuleLLM）在没有 API key 时模拟"思考->调工具->观察"，
让整条 Agent 管道无需任何密钥即可端到端跑通（用于试行）。
"""

from __future__ import annotations

import json
import re

import requests

# ---- 工具调用协议：模型输出二选一 ----
#   TOOL_CALL {json}    -> 请求调用一个工具
#   FINAL <text>        -> 任务完成，给出最终回答
TOOL_PREFIX = "TOOL_CALL"
FINAL_PREFIX = "FINAL"


class LLMError(Exception):
    pass


class LLMClient:
    """OpenAI 兼容客户端。config: {"base_url","api_key","model","temperature"}。"""

    def __init__(self, config: dict):
        self.base_url = (config.get("base_url") or "https://api.openai.com/v1").rstrip("/")
        self.api_key = config.get("api_key", "")
        self.model = config.get("model", "gpt-4o-mini")
        self.temperature = config.get("temperature", 0.3)
        self.timeout = config.get("timeout", 60)

    def chat(self, messages: list[dict]) -> str:
        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
        }
        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=self.timeout)
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"] or ""
        except requests.RequestException as e:
            raise LLMError(f"LLM 请求失败：{e}") from e
        except (KeyError, ValueError, TypeError) as e:
            raise LLMError(f"LLM 返回格式异常：{e}") from e


class RuleLLM:
    """无 key 时的规则引擎：反应式生成 TOOL_CALL / FINAL，驱动完整 ReAct 管道。

    以"全网巡检"为例，它会自动走完：
      list_devices -> 逐台 get_device_status -> 发现接口 down -> search_kb(RAG)
      -> run_inspection(ping, 需确认) -> apply_config_change(变更, 需审批)
      -> get_device_status 复核 -> FINAL 报告
    """

    def __init__(self):
        self._messages: list[dict] = []
        self._plan: list[tuple[str, dict]] = []
        self._last_user = ""
        self._seen: dict[str, int] = {}
        self._devices: list[str] = []
        self._down: tuple[str, str] | None = None  # (device, iface)

    # -- 主入口 --
    def chat(self, messages: list[dict]) -> str:
        self._messages = messages
        # 新用户指令时重置状态
        user_msgs = [
            m["content"]
            for m in messages
            if m.get("role") == "user" and not str(m["content"]).startswith((TOOL_PREFIX, FINAL_PREFIX))
        ]
        if user_msgs and user_msgs[-1] != self._last_user:
            self._last_user = user_msgs[-1]
            self._reset()
            self._seed(self._last_user)

        if not self._plan:
            self._react()

        if self._plan:
            name, args = self._plan.pop(0)
            self._seen[name] = self._seen.get(name, 0) + 1
            return f"{TOOL_PREFIX} {json.dumps({'name': name, 'arguments': args}, ensure_ascii=False)}"

        return self._final_answer()

    # -- 状态 --
    def _reset(self) -> None:
        self._plan = []
        self._seen = {}
        self._devices = []
        self._down = None

    def _last_obs(self) -> str:
        for m in reversed(self._messages):
            if m.get("role") == "tool":
                return str(m["content"])
        return ""

    def _seed(self, t: str) -> None:
        """根据用户意图设定首步计划（注意：动作类关键词优先于话题类关键词）。"""
        if "巡检" in t or "检查" in t or "状态" in t or "报告" in t or "report" in t.lower():
            self._plan = [("list_devices", {})]
        elif "配置" in t or "修改" in t or "变更" in t or "恢复" in t or "修复" in t:
            self._plan = [
                ("get_device_status", {"device": "R2"}),
                ("apply_config_change", {"device": "R2", "config": "interface GigabitEthernet0/0/0\n shutdown\n no shutdown"}),
            ]
        elif "ping" in t.lower() or "连通" in t or "测试" in t:
            self._plan = [("run_inspection", {"device": "R2", "kind": "ping"})]
        elif "接口" in t or "down" in t.lower() or "排障" in t or "故障" in t:
            self._plan = [("search_kb", {"query": "接口 down 排障"})]
        else:
            self._plan = [("search_kb", {"query": t})]

    # -- 反应式决策 --
    def _react(self) -> None:
        obs = self._last_obs()
        if "list_devices" in self._seen and "get_device_status" not in self._seen:
            self._devices = self._extract_list(obs) or ["R1", "R2", "SW1"]
            self._plan = [("get_device_status", {"device": d}) for d in self._devices]
            return
        if self._devices and self._seen.get("get_device_status", 0) < len(self._devices):
            d = self._devices[self._seen.get("get_device_status", 0)]
            self._plan = [("get_device_status", {"device": d})]
            return
        # 所有状态已采集 -> 检查是否有接口 down
        if self._devices and "search_kb" not in self._seen:
            self._down = self._detect_down()
            if self._down:
                self._plan = [("search_kb", {"query": "接口 down 排障"})]
            return
        if self._down and "run_inspection" not in self._seen:
            self._plan = [("run_inspection", {"device": self._down[0], "kind": "ping"})]
            return
        if self._down and "apply_config_change" not in self._seen:
            dev, iface = self._down
            self._plan = [
                ("apply_config_change", {"device": dev, "config": f"interface {iface}\n shutdown\n no shutdown"})
            ]
            return
        if self._down and self._seen.get("get_device_status", 0) < len(self._devices) + 1:
            self._plan = [("get_device_status", {"device": self._down[0]})]
            return

    # -- 解析 --
    def _extract_list(self, obs: str) -> list[str]:
        try:
            obj = json.loads(obs)
            return obj.get("devices", [])
        except json.JSONDecodeError:
            return []

    def _detect_down(self) -> tuple[str, str] | None:
        for m in self._messages:
            if m.get("role") != "tool":
                continue
            content = str(m["content"])
            if '"interfaces"' not in content:
                continue
            try:
                obj = json.loads(content)
                for iface, state in (obj.get("interfaces") or {}).items():
                    if str(state).upper() == "DOWN":
                        return (obj.get("device") or "R2", iface)
            except json.JSONDecodeError:
                continue
        return None

    # -- 最终总结 --
    def _final_answer(self) -> str:
        summary: dict[str, dict] = {}
        pings: list[str] = []
        for m in self._messages:
            if m.get("role") != "tool":
                continue
            try:
                obj = json.loads(str(m["content"]))
            except json.JSONDecodeError:
                continue
            # 设备状态结果（含 device/status/interfaces），按设备去重保留最新
            if all(k in obj for k in ("device", "status", "interfaces")):
                summary[obj["device"]] = obj
            # ping 测试结果
            if all(k in obj for k in ("device", "reachable", "loss_percent")):
                pings.append(
                    f"- {obj['device']} ping {obj.get('target','')}: reachable={obj['reachable']} "
                    f"loss={obj['loss_percent']}% rtt={obj.get('rtt_ms','-')}ms"
                )
        lines: list[str] = []
        for d, obj in summary.items():
            lines.append(
                f"- {d}（{obj.get('role','')}）：status={obj.get('status')} "
                f"cpu={obj.get('cpu')}% mem={obj.get('mem')}% "
                f"interfaces={obj.get('interfaces')}"
            )
        lines.extend(pings)
        if self._down:
            lines.append(f"- 发现问题：{self._down[0]} 接口 {self._down[1]} down，已按知识库排障并尝试恢复。")
        body = "\n".join(lines) or "未获取到可汇总的数据。"
        return f"{FINAL_PREFIX} 处理完成，汇总如下：\n{body}"


def make_llm(config: dict):
    """按配置返回 LLMClient 或 RuleLLM。"""
    if config.get("api_key"):
        return LLMClient(config)
    if config.get("provider") == "ollama" and config.get("base_url"):
        return LLMClient(config)
    return RuleLLM()


# ---- 解析工具调用协议 ----
def parse_model_output(text: str) -> tuple[str, dict | None, str]:
    """返回 (kind, args_or_None, text)。kind in {"tool_call","final"}。"""
    text = text.strip()
    if text.startswith(TOOL_PREFIX):
        payload = text[len(TOOL_PREFIX):].strip()
        payload = re.sub(r"^```(?:json)?", "", payload).strip()
        payload = re.sub(r"```$", "", payload).strip()
        try:
            obj = json.loads(payload)
            return "tool_call", {"name": obj["name"], "arguments": obj.get("arguments", {})}, payload
        except (json.JSONDecodeError, KeyError) as e:
            return "tool_call", None, f"工具调用解析失败：{e}。原文：{text}"
    if text.startswith(FINAL_PREFIX):
        return "final", None, text[len(FINAL_PREFIX):].strip()
    try:
        obj = json.loads(text)
        if isinstance(obj, dict) and "name" in obj:
            return "tool_call", {"name": obj["name"], "arguments": obj.get("arguments", {})}, text
    except json.JSONDecodeError:
        pass
    return "final", None, text
