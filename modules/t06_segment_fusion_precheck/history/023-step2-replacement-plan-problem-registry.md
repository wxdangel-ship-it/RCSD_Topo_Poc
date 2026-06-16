# 023 Step2 Replacement Plan And Problem Registry

## 时间

2026-06-15

## 背景

T06 Step2 原先负责确定 `replaceable`，Step3 负责执行替换。但随着特殊路口组和 path-corridor group replacement 引入，Step3 曾直接读取 Step2 的多个审计产物，导致 Step3 同时承担“解释审计证据”和“执行替换动作”的职责。

本轮架构目标是把替换决策重新收敛回 Step2：Step2 统一发布可执行替换计划，并把仍不能替换的问题登记为可回流上游模块的 registry；Step3 只执行计划，避免继续扩大 Step3 的业务判断范围。

## 业务逻辑变更

- Step2 新增 `t06_segment_replacement_plan.*`，统一表达 `standard_segment`、`special_junction_group_internal` 与 `path_corridor_group` 三类可执行替换 action。
- Step2 新增 `t06_segment_replacement_problem_registry.*`，按 Segment 登记 `covered_by_replacement_plan / resolved_in_step2_plan / requires_upstream_iteration`，并记录推荐模块、回流动作与证据产物。
- Step3 存在 replacement plan 时优先消费 plan，不再直接把 special/group audit 解释为新增替换范围；旧 audit 仅作为历史运行兼容 fallback。
- Step3 默认优先读取 `t06_segment_replacement_plan.json`，再兼容读取 `geojson/gpkg`；JSON 作为完整执行计划主载体，保留无 geometry 的特殊路口组内部 context 行。
- T10 funnel 增加 replacement plan 与 problem registry 计数，使端到端结果可以区分 Step2 判定、Step3 执行与上游待迭代问题。

## 边界

- 不回写 T01/T03/T04/T05/T07/T08 任何输入成果。
- 不把 `requires_upstream_iteration` 交给 Step3 兜底替换。
- 不改变 T08 使用方式；T08 相关原始数据修复仍由独立前置流程处理。
- 不新增 repo CLI 或新的长期入口。

## 验证

- `python -m pytest tests/modules/t06_segment_fusion_precheck/test_replacement_plan.py tests/modules/t06_segment_fusion_precheck/test_step3_segment_replacement.py -q`
- `python -m pytest tests/modules/t06_segment_fusion_precheck -q`
- `python -m pytest tests/modules/t10_e2e_orchestration -q`
- `bash scripts/t10_run_e2e_cases.sh --package-dir /mnt/e/TestData/POC_Data/T10 --case-id 1885118 --case-id 609214532 --case-id 74155468 --case-id 991176`
