# 接口 Down 排障

## 现象

接口物理层 / 链路层状态 DOWN，业务中断，日志出现 `Interface GigabitEthernet0/0/0 link down`。

## 排障步骤

1. `show interface`（华为 `display interface`）查看物理层与链路层状态
2. 检查光模块 / 收发功率与光衰是否在正常范围
3. 检查物理连接与线缆是否松动、损坏
4. 查看端口安全 PortSecurity 是否触发 violation（`show port-security`）
5. 尝试 `shutdown` 再 `no shutdown` 复位端口
6. 若为 PortSecurity violation，执行 `errdisable recovery` 或调整端口安全策略

## 关键命令

- 思科：`show interface` / `show port-security`
- 华为：`display interface` / `display port-security`

## 预防

- 光模块参数纳入巡检
- 端口安全开启后设置合理的 recovery 机制
