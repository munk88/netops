# OSPF 邻居建立排障

## 现象

OSPF 邻居无法建立或反复震荡，路由表缺失。

## 排障步骤

1. 确认两端接口的 area 一致，且 network 宣告未错配
2. 检查 hello / dead 定时器是否一致（思科 `ip ospf hello-interval`，华为 `ospf timer hello`）
3. 检查 MTU 不一致导致状态卡在 Exstart
4. 检查认证（MD5 / 明文）是否匹配
5. `show ip ospf neighbor`（华为 `display ospf peer`）查看邻居状态机

## 常见状态卡点

- INIT / 2WAY：双向 Hello 未建立，检查区域、网络类型
- EXSTART：MTU 问题
- EXCHANGE：LSDB 同步异常，检查认证

## 关键命令

- 思科：`show ip ospf neighbor` / `show ip ospf interface`
- 华为：`display ospf peer` / `display ospf interface`
