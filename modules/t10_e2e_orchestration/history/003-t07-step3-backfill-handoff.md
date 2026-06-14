# 003 - T07 Step3 relation 补锚 handoff 接入 T10

## 时间

2026-06-10

## 背景

T10 四个 Case 已能端到端跑通，但高等级 SWSD Road（`kind` 前缀 `00/01`）对应的单向 Segment 大量没有进入 T06 Step1 final fusion units。进一步交叉分析 T06 Step1 rejected、T07 Step2 nodes 与 T05 `intersection_match_all.geojson` 后发现，部分 `is_anchor_not_eligible` 失败的 SWSD 语义路口已经在 T05 中存在 `status=0 / base_id>0` 的有效 RCSD relation。

T07 模块契约已经定义 Step3：在 T05 Phase2 之后消费 `intersection_match_all.geojson`，对 `has_evd=yes / is_anchor=no` 的语义路口执行 relation 补锚，并输出补写后的 `nodes.gpkg`。T10 Case runner 原链路只执行 T07 Step1/2，没有在 T05 后调用 T07 Step3，导致 T06 仍消费未补锚的 T07 Step2 nodes。

## 业务逻辑变更

1. T10 Case runner 在 `t05` 与 `t06_step12` 之间新增 `t07_step3` 阶段。
2. `t07_step3` 只调用既有入口 `scripts/t07_run_step3_intersection_match_innernet.sh`，不新增 repo 入口。
3. `t07_step3` 显式消费：
   - `t07_nodes`：T07 Step2 输出 nodes；
   - `t05_intersection_match_all`：T05 Phase2 relation 主表；
   - `t05_rcsdnode_out`：与 T05 relation 口径一致的 RCSDNode 输出。
4. `t07_step3` 输出的 `step3_intersection_match/nodes.gpkg` 覆盖后续正式 handoff slot `t07_nodes`，供 T06/T09 使用；原 T07 Step2 nodes 另存为 `t07_step2_nodes` 仅用于审计。
5. `contracts.py` 与 `INTERFACE_CONTRACT.md` 同步更新 T10 v1 Case runner 阶段顺序、`stop_after` 允许值与 `t07_nodes` handoff 语义。

## 业务影响

- T06 Step1 不再因为 T10 漏跑 T07 Step3 而过早排除“已经由 T05 建立有效 RCSD relation”的语义路口。
- 该变更不改变 T07、T05、T06 的模块算法，只修复 T10 编排链路缺失。
- 该变更不把 T05 relation 静默写入 T06，也不绕过 T07 Step3 的 RCSDNode 存在性校验、基数质检与审计输出。

## 不做事项

- 不新增执行入口。
- 不改变 T06 Step1 的 `has_evd / is_anchor` 判定规则。
- 不基于具体 Case ID 写补丁。
- 不推断或新增未授权字段语义。

## 验证

- 新增单测覆盖 T10 `t07_step3` 调用参数、显式输入、输出登记与 `t07_nodes` handoff 覆盖行为。
