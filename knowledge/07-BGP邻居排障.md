# BGP 邻居建立排障

## 现象

BGP 邻居无法建立，或状态卡在 Active / Connect，路由不通。

## 排障步骤

1. 确认对端 IP 可达（`ping`），TCP 179 端口可达
2. `show ip bgp summary`（华为 `display bgp peer`）查看邻居状态机
3. 检查两端 AS 号、Router-ID 是否冲突
4. 检查 eBGP 的 next-hop-self、update-source 配置
5. 检查 MD5 认证（`neighbor x.x.x.x password`）是否一致
6. eBGP 多跳场景检查 TTL（`ebgp-multihop`）

## 常见状态卡点

- Idle：配置未生效或 hold 超时
- Connect / Active：TCP 建立失败，多为路由或 ACL 阻断
- Established 后震荡：hold-time、keepalive 不匹配或链路不稳

## 关键命令

- 思科：`show ip bgp summary` / `show ip bgp neighbors`
- 华为：`display bgp peer` / `display bgp error`

## 建议

- BGP 升级 / 变更走变更窗口
- 监控邻居状态，震荡及时告警
