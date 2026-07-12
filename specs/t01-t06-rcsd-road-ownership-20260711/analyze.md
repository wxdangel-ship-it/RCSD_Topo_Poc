# T01/T06 RCSD Road 归属升级跨文档与实现分析

## 1. 当前源事实冲突与用户裁定

当前 T06 文档对 Junc 同时存在 `optional audit` 和 `required junction` 两种描述。用户已明确裁定：

- 提右不参与锚定，也不属于普通 Segment 的 Pair/Junc；
- 普通 Segment 的 Junc 未锚定，说明端点无法挂接，Segment 不得替换；
- Pair/Junc 锚定状态不阻止 RCSD ownership 继续分析。

实现通过后必须统一 T06 `SPEC.md / architecture/* / INTERFACE_CONTRACT.md`，删除 optional/required 冲突。

## 2. 当前实现关键偏差

### 2.1 T01 明确排除提右 Road

T01 当前源事实与测试均要求 `formway=128` 不进入 Segment。六 Case 500 条提右 Road全部未构 Segment。本轮需正式改变该源事实，同时保证新提右 Segment不进入普通锚定。

### 2.2 group probe 覆盖 group closure 与 source reject

`replacement_plan_rows._group_replacement_plan_rows` 只要 group probe passed，就允许 source 不在 formal replaceable 时发布 ready plan；source 不 formal 仅成为 risk，不成为 hold。

`group_replacement_audit._repair_recommendation/_notes` 也优先使用 probe passed，覆盖 `blocked_group_closure_incomplete` 或 `not_group_required_no_external_anchor` 的原始审计含义。

六 Case 67 个 Step2 外成功对象中 52 个来自 blocked group closure，证明该偏差不是孤例。

### 2.3 path-corridor source carrier 使用完整 group Road union

当前 Step3 对 group source 使用完整 group `rcsd_road_ids`，使单条 RCSD Road可被大量 Segment relation 同时引用。1885118 最大达到一条 Road 被 20 个 Segment 引用；六 Case 多引用 Road合计 4,369 条。

### 2.4 二度连通 fallback 没有独立 owner

现有 `apply_unreplaced_second_degree_bridge_fallback` 会把 bridge Road直接追加到每个候选 Segment unit 和 `added_road_to_segments`。它满足“多 Segment 相关”但不满足“单一 connectivity group owner”。六 Case实际规模为 56 条 Road，可作为迁移验证集。

### 2.5 未替换归因是事后近似，不是完整 ownership

当前 3,897 条未替换 RCSD 中只有 396 条 exact；3,101 条命中多个 Segment。`final_primary_segment_id` 不能继续作为正式 owner 真相，只能作为 candidate evidence。

## 3. 兼容边界

- 不回写 T05 relation；
- 不改变 T09 入口；
- relation 可继续重复引用 connectivity carrier，但必须新增 owner/related 的明确区分；
- 现有六类未替换汇报可以由新 ownership 派生，避免一次性删除；
- 旧 path-corridor plan 行保留根因审计，不直接删除证据。

## 4. 实施前门禁

- Spec/Plan/Tasks 完整覆盖五职责；
- 1885118 与六 Case baseline 冻结文件已存在；
- 所有待改源码在写入前重新检查字节数；
- 先写失败测试；
- 1885118 每个大阶段完成后回归；
- RCSD ownership 分析脚本与输出保留在 worktree `outputs/_work`，不登记正式入口。
