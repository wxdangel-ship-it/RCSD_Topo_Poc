# 01 Introduction And Goals

## 目标

T07 当前目标是在 T02 Step1 / Step2 已确认业务口径基础上，形成一个只面向语义路口级的锚定前置模块，并提供独立 Step3 relation 补锚：

1. 从 `nodes` 语义路口集合直接判定代表 node 的 `has_evd`。
2. 对 `has_evd = yes` 的语义路口判定代表 node 的 `is_anchor / anchor_reason`。
3. 基于 T05 `intersection_match_all.geojson` 对 Step2 后仍未锚定的候选语义路口补写 `is_anchor = yes`。
4. 完全剥离 T02 中 Segment 引用候选域、`segment.has_evd` 与 Segment 视角 summary。

## 成功判据

- Step1 不依赖 `segment.gpkg` 即可输出代表 node `has_evd`。
- Step2 不依赖 `segment.gpkg` 即可输出代表 node `is_anchor / anchor_reason`。
- Step3 不依赖 `segment.gpkg`，只消费 Step2 后 `nodes`、T05 relation 主表和输入 `RCSDNode`。
- `kind_2` 过滤只使用代表 node。
- 非目标 `kind_2` 的三个业务字段均为 `NULL`。
- 从属 node 不写业务状态。
- 所有失败、跳过、冲突均可审计。

## 当前非目标

- 不执行 Segment 相关处理。
- 不执行 T02 Stage3 / Stage4。
- 不执行最终唯一锚定决策。
- 不新增 repo 官方 CLI；内网执行仅通过已登记脚本包装模块内 callable runner。
