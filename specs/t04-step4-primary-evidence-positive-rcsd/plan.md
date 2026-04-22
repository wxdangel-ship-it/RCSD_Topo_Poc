# Implementation Plan: T04 Step4 Primary Evidence + Positive RCSD Iteration

**Branch**: `codex/t04-step4-primary-evidence-positive-rcsd-20260422` | **Date**: 2026-04-22 | **Spec**: [spec.md](/mnt/e/Work/RCSD_Topo_Poc/specs/t04-step4-primary-evidence-positive-rcsd/spec.md)

## 1. 总体策略

本轮沿用当前已落地的 `selected_evidence` / case 内重选骨架，在 T04 层做最小增量：

1. 先把 Step4 新口径回写到线程 REQUIREMENT 与 repo source-of-truth。
2. 在 T04 结果层补齐正向 RCSD 的稳定字段与几何表达，不去重写 T02 RCSD 内核。
3. 在 review 输出层把“主证据 + reference + 正向 RCSD + required 节点 + A/B/C”画清楚。
4. 用 pytest + Anchor_2 batch 回归锁住 baseline。

## 2. 技术判断

- 当前 `event_interpretation.py` 已经实现：
  - `selected_evidence`
  - `selected_evidence_state = none`
  - `node_fallback_only`
  - 单 Case 内重选
- 因此本轮不重新设计主证据框架，只补缺口。
- 正向 RCSD 复用 T02 legacy bridge 已给出的：
  - `selected_rcsdroad_ids`
  - `selected_rcsdnode_ids`
  - `primary_main_rc_node`
  - `selected_rcsd_roads`
  - `selected_rcsd_nodes`
  - `effective_target_rc_nodes`
- T04 负责把这些 legacy 结果转成 Step4 正式语义与审计输出：
  - `positive_rcsd_support_level`
  - `positive_rcsd_consistency_level`
  - `required_rcsd_node`

## 3. 最小改动路径

### 3.1 文档

- 重写线程 `REQUIREMENT.md` 的 Step4 章节，显式加入：
  - 主证据进入讨论条件
  - `local candidate unit`
  - 主证据优先级
  - 正向 RCSD A/B/C
  - `required_rcsd_node`
- 更新 repo 文档 `INTERFACE_CONTRACT.md` 与 `04-solution-strategy.md`，保持只到 Step4。

### 3.2 代码

- `event_interpretation.py`
  - 在 candidate 结果层后处理 RCSD road/node 输出
  - 增加 A/B/C 分类与 `required_rcsd_node`
  - 保持旧 `rcsd_consistency_result` 作为兼容别名
- `case_models.py`
  - 给 `T04EventUnitResult` / `T04ReviewIndexRow` 增加新字段
- `outputs.py`
  - 把新字段写入 `step4_candidates.json`、`step4_evidence_audit.json`、`step4_review_index.csv`、`step4_review_summary.json`
- `review_render.py` / `review_audit.py`
  - 强化主证据、正向 RCSDRoad / RCSDNode、`required_rcsd_node`、A/B/C 的图示与摘要
- `tests/modules/t04_divmerge_virtual_polygon/test_step14_pipeline.py`
  - 增加最小必要断言

## 4. 风险与控制

- 风险：把 RCSD 支持层误扩成 Step5 负向裁决。
  - 控制：只做 `positive support`、`consistency` 和 `required_rcsd_node` 输出，不修改 Step5 readiness 逻辑。
- 风险：主证据已通过样本因 RCSD 缺失被错误打回。
  - 控制：`C / no_support` 只作为审计输出，不自动否决主证据。
- 风险：审计图新增元素过多反而更难看。
  - 控制：用显式颜色分层与 marker，不重做整个 review 体系。

## 5. 验证计划

- `PYTHONPATH=src .venv/bin/python -m pytest tests/modules/t04_divmerge_virtual_polygon/test_step14_pipeline.py -q -s`
- `Anchor_2` batch：
  - 生成 `step4_review_index.csv`
  - 生成 `step4_review_summary.json`
  - 生成 `step4_review_flat`
  - 检查 per-case / per-unit review PNG
