# 现状与证据

## 1. 当前实现

- T12 v8 仅发布 Segment LineString 质量问题。
- 当前可选 QA review 只覆盖 Segment candidate。
- T10 full runner 已持有 T03 run root，T07 Step3 显式运行时也持有
  `relation_cardinality_errors` 所在 stage root，但尚未传给 T12。

## 2. 已冻结 Segment 基线

本地 `1026960` v8 双跑：

- candidate：63
- confirmed：10
- excluded：53
- manual：0
- confirmed issue type：8 个 `directed_carrier_missing`、
  2 个 `required_local_connectivity_missing`
- 两次 confirmed candidate ID/type 完全一致。

## 3. T03 证据结论

- 正样本：
  - `522008569`、`522806716`：
    `shared_degree1_terminal_collapse`
  - `520394575`、`622700016`：
    `multi_component_unmatched_support`
- T03 正式工件未稳定发布 target projection 和 endpoint degree；
  T12 必须用正式 target/support IDs 与原始 1V1 FRCSD 重算。
- `outputs/_work` ownership CSV 只用于需求验证和回归真值，
  不作为生产输入。

## 4. T07 证据结论

- SPEC、接口契约、实现与测试均证明 Step1 `has_evd` 只使用
  `DriveZone`；两处架构文字已获用户授权修正。
- Step3 `relation_cardinality_errors` 稳定发布：
  `one_target_to_many_base`、`many_target_to_one_base`、
  `duplicate_target_rows`。
- 本任务只直接消费前两类。

## 5. 已知治理边界

- 不修改 T03/T07 算法。
- 不把距离、Source、DriveZone 覆盖率或 T03 rejected 本身提升为质量结论。
- 不在 main 上开发；当前隔离 worktree/branch：
  `E:\Work\RCSD_Topo_Poc__wt_t12_junction_quality_20260731` /
  `codex/t12-junction-quality-20260731`。
