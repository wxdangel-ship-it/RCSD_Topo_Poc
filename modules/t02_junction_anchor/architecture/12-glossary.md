# 12 术语表

- `segment`：来自 T01 的双向 Segment 聚合结果，当前 stage1 消费其中的 `id / pair_nodes / junc_nodes / s_grade|sgrade`。
- `junction_id`：从 `pair_nodes / junc_nodes` 解析得到的目标路口标识。
- `mainnode`：业务概念名；在 stage1 正式输入中对应字段是 `mainnodeid`。
- `representative node`：某个 junction group 中唯一承担 `has_evd` 写值的 node。
- `DriveZone gate`：判断某个 junction group 是否拥有有效资料区域的 stage1 规则。
- `has_evd`：当前阶段的资料存在性业务结果，值域为 `yes / no / null`。
- `summary bucket`：按 `0-0双 / 0-1双 / 0-2双` 对 stage1 结果做的分桶统计。
- `audit reason`：用于区分业务 `no` 与执行失败的稳定原因枚举。
