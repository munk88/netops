"""Harness Engineering —— 三层权限边界。

只读分析   ->  Agent 自主执行
测试与采集 ->  人工确认后执行
配置变更   ->  严格审批，禁止自主（需显式批准 + 写入审计日志）

任何工具调用前必须先过裁决（同步 check / 异步 acheck），
由权限级别决定放行 / 确认 / 拒绝。异步版支持 Web 弹窗确认。
"""

from __future__ import annotations

import asyncio
import inspect
import json
import time
from pathlib import Path
from typing import Callable

LEVEL_READ = "read"      # 只读
LEVEL_TEST = "test"      # 测试与采集
LEVEL_CHANGE = "change"  # 配置变更

# 级别数值，用于比较
_LEVEL_RANK = {LEVEL_READ: 1, LEVEL_TEST: 2, LEVEL_CHANGE: 3}

# 确认函数签名（同步或异步均可）：ask(title: str, level: str) -> bool
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

    @property
    def confirm_fn(self) -> ConfirmFn | None:
        return self._confirm_fn

    @confirm_fn.setter
    def confirm_fn(self, fn: ConfirmFn | None) -> None:
        self._confirm_fn = fn

    # -- 裁决核心（同步，兼容 CLI） --
    def check(self, name: str, arguments: dict) -> tuple[bool, str]:
        """返回 (是否放行, 说明)。放行后才可执行工具。"""
        level = self.level_of(name)
        if level == LEVEL_READ:
            self._audit(name, arguments, "ALLOW_READ")
            return True, "只读操作，Agent 自主执行"
        if self._confirm_fn is None:
            self._audit(name, arguments, "DENY_NO_CONFIRM")
            return False, f"无确认机制，{level} 级操作默认拒绝"
        ok = self._confirm_fn(self._title(name, arguments, level), level)
        if inspect.isawaitable(ok):
            ok = asyncio.run(ok)  # 同步路径遇到异步确认函数时兜底
        return self._settle(name, arguments, level, bool(ok))

    # -- 裁决核心（异步，支持 Web 弹窗确认） --
    async def acheck(self, name: str, arguments: dict) -> tuple[bool, str]:
        level = self.level_of(name)
        if level == LEVEL_READ:
            self._audit(name, arguments, "ALLOW_READ")
            return True, "只读操作，Agent 自主执行"
        if self._confirm_fn is None:
            self._audit(name, arguments, "DENY_NO_CONFIRM")
            return False, f"无确认机制，{level} 级操作默认拒绝"
        ok = self._confirm_fn(self._title(name, arguments, level), level)
        if inspect.isawaitable(ok):
            ok = await ok
        return self._settle(name, arguments, level, bool(ok))

    # -- 公共判定落盘 --
    def _settle(self, name: str, arguments: dict, level: str, ok: bool) -> tuple[bool, str]:
        if level == LEVEL_TEST:
            if ok:
                self._audit(name, arguments, "ALLOW_TEST_CONFIRMED")
                return True, "人工确认后执行"
            self._audit(name, arguments, "DENY_TEST")
            return False, "人工拒绝执行测试"
        if level == LEVEL_CHANGE:
            if ok:
                self._audit(name, arguments, "ALLOW_CHANGE_APPROVED")
                return True, "已获人工审批，执行变更"
            self._audit(name, arguments, "DENY_CHANGE")
            return False, "变更未获审批，禁止自主执行"
        self._audit(name, arguments, "ALLOW_READ_FALLBACK")
        return True, "未知权限按只读处理"

    @staticmethod
    def _title(name: str, arguments: dict, level: str) -> str:
        return f"[Harness] {name}{json.dumps(arguments, ensure_ascii=False)}（{level}）"

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
