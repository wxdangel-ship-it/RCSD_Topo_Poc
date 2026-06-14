# 001 Step1/2 Evidence Candidate Index

## 日期
- 2026-06-10

## 背景
- T10 Case `609214532` 已通过 T06 Step3，但 T09 Step1/2 在大输入上运行约 45 分钟仍未完成。
- 进程持续接近单核满载，说明不是 I/O 卡死，而是 T09 Step1/2 算法热点。

## 根因
- `restore_field_rules` 对每个 Movement 都扫描全量 Tool7 restriction 与 Tool8 arrow。
- restriction 未直接命中 `inLinkID/outLinkID` 时，还会对每个 carrier road pair 做几何匹配；arrow 也会对每个 approach road 扫描全量 arrow 做几何匹配。
- 大 Case 中 Tool8 arrow 数量达到数万级，`movements × arrows/restrictions` 的全量扫描导致复杂度不可接受。

## 本次边界
- 不改变 restriction 是唯一强禁行证据的业务规则。
- 不丢弃 raw link 几何 fallback：直接 link 不匹配时，仍允许空间邻近的 Tool7/Tool8 几何参与匹配。
- 不修改 T06、T08、SWSD 或 F-RCSD 输入。

## 实际变更
- Step1/2 restore 阶段为 restriction 建立 `(in_link_id, out_link_id)` 精确索引。
- 为 restriction 与 arrow 几何建立一次性空间候选索引。
- 每个 Movement 只消费：
  - 与 carrier road pair 精确匹配的 restriction；
  - 与 carrier road 几何邻近的 raw restriction；
  - 与 approach road id 精确匹配或几何邻近的 arrow。
- 对 approach road 的 arrow 候选做缓存，避免同一 road 在多个 Movement 中重复查询空间索引。

## 验证
- 新增回归用例覆盖大量无关 Tool7/Tool8 证据存在时，raw link 几何 fallback 仍能恢复 restriction 与 arrow evidence。
- 已运行 `pytest tests/modules/t09_swsd_field_rule_restoration`，结果 `30 passed`。
- 待用 T10 Case `609214532` 复跑 T09 Step1/2，确认大 Case 性能恢复。
