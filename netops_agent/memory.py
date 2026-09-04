"""记忆系统：Session（短时上下文）+ 长期记忆（JSON 落盘）。"""

from __future__ import annotations

import json
import re
from pathlib import Path

DEFAULT_LONGTERM = "memory.json"


class Memory:
    """Session 保存当前会话消息；长期记忆把关键事实持久化，跨会话复用。"""

    def __init__(self, longterm_path: str | Path = DEFAULT_LONGTERM):
        self.session: list[dict] = []          # [{"role": ..., "content": ...}]
        self.longterm: dict = {}
        self._path = Path(longterm_path)
        if self._path.exists():
            try:
                self.longterm = json.loads(self._path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                self.longterm = {}

    # -- Session --
    def add(self, role: str, content: str) -> None:
        self.session.append({"role": role, "content": content})

    def history(self) -> list[dict]:
        return list(self.session)

    # -- 长期记忆 --
    def remember(self, key: str, value) -> None:
        self.longterm[key] = value
        self._save()

    def recall(self, key: str, default=None):
        return self.longterm.get(key, default)

    def _save(self) -> None:
        self._path.write_text(json.dumps(self.longterm, ensure_ascii=False, indent=2), encoding="utf-8")

    # -- 工具：从工具观察结果中抽取事实（设备名 -> 关键状态） --
    def extract_facts(self, tool_name: str, arguments: dict, result: str) -> None:
        """把设备状态这类事实沉淀进长期记忆，模拟"跨会话记住"。"""
        if tool_name == "get_device_status" and arguments.get("device"):
            m = re.search(r"status['\"]?\s*[:=]\s*['\"]?(UP|DOWN)", result, re.I)
            if m:
                self.remember(f"device_status:{arguments['device']}", m.group(1).upper())

    def build_system_facts(self) -> str:
        """把长期记忆拼进 system prompt。"""
        if not self.longterm:
            return ""
        lines = ["# 你此前记住的事实（来自长期记忆）"]
        for k, v in self.longterm.items():
            lines.append(f"- {k}: {v}")
        return "\n".join(lines)
