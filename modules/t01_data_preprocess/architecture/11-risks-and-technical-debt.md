# 11 风险与技术债

## 当前业务风险
- `XXXS5`
  - `Segment 39546457_47130796` 仍存在“旁路分支超过 50m”问题
- `XXXS7`
  - `Segment 1013672_612642212` 仍存在“双向旁路”问题
- 这两个问题仍是当前最明确的未关闭业务问题。

## 当前实现风险
- 审计中已确认的 4 个整改批次尚未完成：
  - 批次 A：`Step4 / Step5A / Step5B` 语义压扁
  - 批次 B：`Step5A / Step5B / Step5C` 未逐轮 refresh
  - 批次 C：`Step2` raw `grade / kind` fallback
  - 批次 D：Step6 缺少 `formway = 128` 一致过滤

## 性能风险
- 全量运行下，`Step2 same-stage pair arbitration` 仍存在 option retention / 局部热点 pair 造成耗时和内存压力的风险。

## 结构债
- `step2_segment_poc.py` 已通过抽离 `step2_graph_primitives.py`、`step2_runtime_utils.py`、`step2_support_utils.py` 与 `step2_candidate_channel_utils.py` 继续压低体量；但 `validation / tighten / orchestration` 主链职责仍然偏重。
- 文档曾出现 accepted baseline 错落到 `specs/` 的问题，现已纠正，但后续仍需保持角色边界清晰。

## 当前缓解方式
- 以 `PASS_LOCKED / FAIL_TARGET` 的临时最终 Segment 基线套件做非回退闸门。
- 架构整改与业务整改分批执行，不混修。
