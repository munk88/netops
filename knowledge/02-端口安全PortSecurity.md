# 端口安全 PortSecurity

## 现象

接口开启 `port-security` 且 MAC 地址数量超限时，接口进入 errdisable 状态，表现为 link down，日志出现 `PortSecurity violation`。

## 排障

1. `show port-security` 查看违规 MAC 与触发原因
2. `clear port-security` 或 `shutdown / no shutdown` 恢复接口
3. 必要时调整 `maximum` 数量（允许的 MAC 上限）
4. 或设置 `violation protect`（只丢弃不发告警，不中断业务）

## 配置要点

- `switchport port-security` 启用
- `switchport port-security maximum <n>` 上限
- `switchport port-security violation protect|restrict|shutdown` 违规动作

## 建议

- 接入交换机建议开 protect 模式，避免误伤正常终端
- 关键端口绑定固定 MAC（`port-security mac-address sticky`）
