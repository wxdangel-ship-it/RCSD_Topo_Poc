# P05-JSG-PTO-P2 实施计划

## 1. 输入冻结

- JSG candidate：`p05_jsg_p1_candidate_20260722_02`
- JSG/PTO Oracle label：`p05_jsg_p1_oracle_20260722_03`
- M0 split/weight：`p05_m0_20260721_06`
- P0 JSG truth：`p05_jsg_p0_20260721_04`
- R2 compiler truth：`p05_r2_oracle_20260721_03`

所有路径由 config 传入；正式 run manifest 固定 path/hash。本轮不重跑 strategy proposal。

## 2. 实现分层

1. `jsg_p2_models.py`：dataset/OOF config、score/model contract、稳定签名。
2. `jsg_p2_features.py`：JSG/PTO candidate 的 ID-free 稀疏 feature tokens、V0 cost。
3. `jsg_p2_dataset.py`：验证 P1/M0 manifest，构建 51 Case grouped 5-fold label dataset。
4. `jsg_p2_linear.py`：按训练 fold 统计平滑加性 log-odds 权重；输出可解释 fold model。
5. `jsg_p2_oof.py`：V0/V1 OOF score、group ranking、PTO-A/PTO-B 选择、物化和 evaluator。
6. `jsg_p2.py` / `__init__.py`：模块 callable。

## 3. 数据与评分

- feature token 只来自 candidate payload 的枚举/结构、source kind、role、候选复杂度和可用证据状态。
- 所有 ID、坐标数值、truth-derived 统计、fold 和 label 均禁止进入 feature。
- V0 是冻结显式代价；V1 是加性稀疏线性基线，权重为训练折内 feature 的平滑 log-odds。
- sample weight 使用 M0 `target_weight/context_weight`。完整 T10 Case 为 0.7；Segment Case 仅 target object 为 0.7，其余上下文为 0.3。

## 4. 求解与评价

- PTO-A 每组按 score 选择，并验证 dependency、Review/Unknown 和 multi-THROUGH。
- PTO-B 使用 RoadGraph group score 选择，随后执行通用 schema/ID/endpoint/pointer/geometry 约束；不可行直接失败，不进行业务修复。
- 选中 Road/Node 使用 R2 materializer 和 M0 evaluator；P0 truth 只参与 held-out 评价。

## 5. 验证顺序

1. 单元/泄漏/破坏测试。
2. 小规模真实 Case probe。
3. Dataset 正式 run。
4. OOF Run A/B。
5. determinism/GIS/resource/baseline audit。
6. 完整 P05 pytest、source-of-truth 完成态同步、代码体量审计。
