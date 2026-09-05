# CPU 利用率过高排障

## 现象

设备 CPU 长时间高负载，转发性能下降、丢包、业务卡顿。

## 排障步骤

1. `display cpu-usage`（华为）/ `show process cpu`（思科）确认是否持续高
2. 定位高占用进程：路由进程 / 软转发 / 控制平面
3. 排查是否受到攻击：流量风暴、组播泛滥、BGP 路由抖动
4. 抓包确认异常流量来源
5. 必要时限速、配置过滤策略，或升级硬件

## 关键命令

- 华为：`display cpu-usage` / `display process cpu`
- 思科：`show process cpu sorted`

## 常见根因

- 环路导致广播风暴
- 大量小包 / 组播冲击控制面
- 路由表过大，CPU 软转发压力高

## 建议

- 部署 QoS 保护控制面（Control-Plane Policing）
- 监控告警阈值，纳入巡检基线
