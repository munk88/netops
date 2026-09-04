"""模拟网络设备层（MVP 默认不连真实设备，使用内置模拟数据）。

想接真实设备时，把本模块中的函数替换为 netmiko/SSH 调用即可（见 README）。
"""

from __future__ import annotations

import copy

# ---- 模拟网络状态 ----
_DEVICES: dict[str, dict] = {
    "R1": {
        "role": "核心路由器",
        "vendor": "Huawei",
        "model": "NE40E",
        "status": "UP",
        "uptime": "200 days",
        "cpu": 23,
        "mem": 41,
        "interfaces": {"GigabitEthernet0/0/0": "UP", "GigabitEthernet0/0/1": "UP"},
        "log": ["2026-09-04 10:12 OSPF neighbor established with R2"],
    },
    "R2": {
        "role": "汇聚路由器",
        "vendor": "Huawei",
        "model": "AR6300",
        "status": "UP",
        "uptime": "97 days",
        "cpu": 68,
        "mem": 72,
        "interfaces": {"GigabitEthernet0/0/0": "DOWN", "GigabitEthernet0/0/1": "UP"},
        "log": [
            "2026-09-04 09:40 Interface GigabitEthernet0/0/0 link down",
            "2026-09-04 09:40 PortSecurity violation on GigabitEthernet0/0/0",
        ],
    },
    "SW1": {
        "role": "接入交换机",
        "vendor": "Cisco",
        "model": "Catalyst 9300",
        "status": "UP",
        "uptime": "310 days",
        "cpu": 12,
        "mem": 34,
        "interfaces": {"GigabitEthernet1/0/1": "UP", "GigabitEthernet1/0/2": "UP"},
        "log": [],
    },
}


def list_devices() -> list[str]:
    """返回网络中所有设备名。"""
    return list(_DEVICES.keys())


def get_device_status(device: str) -> dict:
    """读取单台设备的状态（只读）。设备不存在时抛 KeyError 由上层处理。"""
    return copy.deepcopy(_DEVICES[device])


def ping(device: str, target: str = "8.8.8.8") -> dict:
    """模拟连通性测试（测试类操作）。"""
    loss = 0 if _DEVICES[device]["status"] == "UP" else 100
    return {
        "device": device,
        "target": target,
        "loss_percent": loss,
        "rtt_ms": 1.2 if loss == 0 else None,
        "reachable": loss == 0,
    }


def apply_config_change(device: str, config: str) -> dict:
    """应用配置变更（变更类操作，写入模拟设备状态）。"""
    d = _DEVICES[device]
    lines = [ln.strip() for ln in config.strip().splitlines() if ln.strip()]
    # 简单模拟：把 DOWN 接口恢复为 UP
    for ln in lines:
        if ln.startswith("interface "):
            iface = ln.split(None, 1)[1]
            if iface in d["interfaces"]:
                d["interfaces"][iface] = "UP"
    d["log"].insert(0, f"2026-09-04 {__import__('time').strftime('%H:%M')} CONFIG-CHANGE applied: {config!r}")
    d["cpu"] = max(5, d["cpu"] - 10)  # 模拟配置生效后负载回落
    return {
        "device": device,
        "applied": True,
        "new_status": d["status"],
        "interfaces": dict(d["interfaces"]),
        "note": "已写入模拟设备（真实环境应使用 netmiko send_config_set）",
    }


def reset() -> None:
    """重置模拟设备状态（供 demo 复现）。"""
    global _DEVICES
    _DEVICES = {
        "R1": {
            "role": "核心路由器", "vendor": "Huawei", "model": "NE40E",
            "status": "UP", "uptime": "200 days", "cpu": 23, "mem": 41,
            "interfaces": {"GigabitEthernet0/0/0": "UP", "GigabitEthernet0/0/1": "UP"},
            "log": ["2026-09-04 10:12 OSPF neighbor established with R2"],
        },
        "R2": {
            "role": "汇聚路由器", "vendor": "Huawei", "model": "AR6300",
            "status": "UP", "uptime": "97 days", "cpu": 68, "mem": 72,
            "interfaces": {"GigabitEthernet0/0/0": "DOWN", "GigabitEthernet0/0/1": "UP"},
            "log": [
                "2026-09-04 09:40 Interface GigabitEthernet0/0/0 link down",
                "2026-09-04 09:40 PortSecurity violation on GigabitEthernet0/0/0",
            ],
        },
        "SW1": {
            "role": "接入交换机", "vendor": "Cisco", "model": "Catalyst 9300",
            "status": "UP", "uptime": "310 days", "cpu": 12, "mem": 34,
            "interfaces": {"GigabitEthernet1/0/1": "UP", "GigabitEthernet1/0/2": "UP"},
            "log": [],
        },
    }
