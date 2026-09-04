"""Harness Engineering —— 三层权限边界。

只读分析   ->  Agent 自主执行
测试与采集 ->  人工确认后执行
配置变更   ->  严格审批，禁止自主（需显式批准 + 写入审计日志）

任何工具调用前必须先过 check()，由权限级别决定放行 / 确认 / 拒绝。
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Callable

LEVEL_READ = "read"      # 只读
LEVEL_TEST = "test"      # 测试与采集
LEVEL_CHANGE = "change"  # 配置变更

# 级别数值，用于比较
_LEVEL_RANK = {LEVEL_READ: 1, LEVEL_TEST: 2, LEVEL_CHANGE: 3}

# 确认函数签名：ask(title: str, level: str) -> bool
ConfirmFn = Callable[[str, str], bool]


class Harness:
    """权限门：所有工具调用在此裁决，并落审计日志。"""

    def __init__(self, audit_path: str | Path = "audit.jsonl", confirm_fn: ConfirmFn | None = None):
        self._audit_path = Path(audit_path)
        self._confirm_fn = confirm_fn

    # -- 工具权限登记：name -> level --
    def register(self, name: str, level: str) -> None:
        setattr(self, f"_perm_{name}", level)

    def level_of(self, name: str) -> str:
        return getattr(self, f"_perm_{name}", LEVEL_READ)

    # -- 裁决核心 --
    def check(self, name: str, arguments: dict) -> tuple[bool, str]:
        """返回 (是否放行, 说明)。放行后才可执行工具。"""
        level = self.level_of(name)
        if level == LEVEL_READ:
            self._audit(name, arguments, "ALLOW_READ")
            return True, "只读操作，Agent 自主执行"
        if level == LEVEL_TEST:
            if self._confirm(name, arguments, "测试采集", level):
                self._audit(name, arguments, "ALLOW_TEST_CONFIRMED")
                return True, "人工确认后执行"
            self._audit(name, arguments, "DENY_TEST")
            return False, "人工拒绝执行测试"
        if level == LEVEL_CHANGE:
            if self._confirm(name, arguments, "配置变更（高风险）", level):
                self._audit(name, arguments, "ALLOW_CHANGE_APPROVED")
                return True, "已获人工审批，执行变更"
            self._audit(name, arguments, "DENY_CHANGE")
            return False, "变更未获审批，禁止自主执行"
        self._audit(name, arguments, "ALLOW_READ_FALLBACK")
        return True, "未知权限按只读处理"

    # -- 确认 --
    def _confirm(self, name: str, arguments: dict, title: str, level: str) -> bool:
        if self._confirm_fn is None:
            return False  # 默认不自动放行高风险操作
        return self._confirm_fn(f"[Harness] {title}：{name}{json.dumps(arguments, ensure_ascii=False)}", level)

    # -- 审计日志 --
    def _audit(self, name: str, arguments: dict, decision: str) -> None:
        rec = {
            "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
            "tool": name,
            "args": arguments,
            "decision": decision,
        }
        with open(self._audit_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
