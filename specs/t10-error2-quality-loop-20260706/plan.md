# T10-Error-2 20 Segment 未替换 RCSD 质量闭环计划

## 1. 当前工作树

隔离 worktree：

```text
/mnt/c/Users/admin/.codex/worktrees/t10-error2-quality-loop-20260706/RCSD_Topo_Poc
```

正式仓库主 worktree 不作为写入目标。本轮输出默认进入：

```text
outputs/_work/t10_error2_quality_loop_20260706/
```

## 2. 阶段划分

### Phase 1：证据闭环与既有能力组合验证

目标：

- 固化附件 145 行与 20 Segment 的根因分类。
- 分别验证 T11 manual、T10 side-group 的收益。
- 组合验证 T11 manual + T10 side-group 是否存在交互收益或回退。

写集：

- `outputs/_work/t10_error2_quality_loop_20260706/tools/*`
- `outputs/_work/t10_error2_quality_loop_20260706/analysis/*`
- `outputs/_work/t10_error2_quality_loop_20260706/t10_manual_side_group/*`

禁止：

- 不改正式 `scripts/`。
- 不改 `src/`。
- 不改模块契约或项目级源事实。

### Phase 2：候选正式修复筛选

目标：

- 对 Phase 1 剩余 blocker 做“能否在现有源事实内修复”的判定。
- 对可修复项制定最小代码改动。
- 对不可修复项输出人工复核或源事实裁定清单。

判定规则：

- T05 relation 输入类：必须满足 T05 契约中的正向 relation、非空 selected_ids、graph consumable 规则。
- T10 feedback 类：必须已有成功 relation 或 road-only split 决策，不能单独创建 relation。
- T06 Step1 类：只允许释放源事实明确授权的 `T11_MANUAL` gate。
- T06 Step2/Step3 类：必须通过 relation、direction、buffer、topology hard audit；不得由人工 relation 直接放行。

### Phase 3：正式修复与回归

每个正式修复按以下顺序执行：

1. 更新必要源事实 / 契约 / 测试。
2. 修改最小代码。
3. 跑单元测试。
4. 跑 20 Segment 回归。
5. 跑 `1885118`。
6. 跑 T10 6 case。
7. 回写根因收益表。

## 3. 第一批根因处理策略

### Root A：T11 人工 relation 未进入 T05/T06

处理：

- 使用 `t11_innernet_manual_relation_merged_for_t05.csv` 过滤到各 case 可见 target。
- 通过 T05 `--t11-manual-relation` 重新生成 relation 与 junctionization。
- 重新跑 T06 Step1/2/3。

验收：

- 20 Segment 完成，无失败 case。
- 新增可替换或减少未替换长度。
- 不新增 replacement failure / relation failure。

### Root B：T10 side-group endpoint candidate 未进入 T05 grouping

处理：

- 使用 baseline T10 输出的 `t10_upstream_side_group_endpoint_candidates.csv`。
- 通过 T05 `--t10-side-group-endpoint-candidates` 回灌。
- 不使用 `auto_consumable_by_t05=false` 的 pair-anchor cluster 放行 relation。

验收：

- 20 Segment 完成，无失败 case。
- `1885118` 与 T10 6 case 无业务回退。
- topology hard fail、surface topology hard fail 不增加。

### Root C：T11 manual + T10 side-group 组合交互

处理：

- 用临时 helper 同时传入 `--t11-manual-relation` 与 `--t10-side-group-endpoint-candidates`。
- 对比 baseline、manual-only、side-group-only。

验收：

- 20 Segment 完成，无失败 case。
- 收益不低于两个单独修复中的安全部分。
- 若出现回退，定位到具体 Segment / target / RCSDRoad。

## 4. 暂不直接修复的类别

以下类别需要额外证据或源事实裁定：

- `t06_step1_evidence_or_anchor_blocked` 中没有正向 T11 manual relation 支撑的 `has_evd_missing / has_evd_not_yes / is_anchor_not_eligible`。
- `t06_relation_or_topology_semantic_blocked` 中仍缺失 pair/junc relation、RCSD required semantic nodes 不连通、方向性不满足的项。
- `weak_geometry_only_target_scope_review`，除非有正式 relation 或 source fact 支撑。
- `attachment_row_not_reproduced_in_current_step3_outputs`，需先确认附件基线与当前 run root 是否同源。
- `not_target_scope_current_primary_segment_elsewhere` 与 `consumed_by_other_segment_not_target_scope`，默认不作为目标 Segment 修复收益。

## 5. 质量门

- CRS：visual check 中所有关键 GPKG/GeoJSON 层有 CRS，空间检查通过。
- 拓扑：`replacement_unit_failure_count`、`segment_relation_failed_count` 不增加；`topology_connectivity_fail_count` 不增加。
- 几何：新增替换要能追到 T05 relation / T10 candidate / T06 replacement unit。
- 审计：每轮生成 run summary、case summary、root cause rows、bucket summary。
- 性能：记录 run duration；长跑中不得以 partial summary 作结论。
