# 05 质量要求

## 1. 业务正确性

- T04 主几何真值是 `divmerge_virtual_anchor_surface.gpkg`。
- Step7 final state 只允许 `accepted / rejected`。
- Reference Point 只能来自主证据；无主证据时不能构造虚拟 Reference Point。
- Step5 只定义约束，Step6 才生成最终面。
- final relation 必须经过 1:1 cardinality 校验。

## 2. GIS 与拓扑要求

- 输入与输出 CRS 必须可定位；需要转换时必须记录。
- polygon 合法化只能用于最小修复，不能越过 allowed growth、forbidden mask 或 terminal cut。
- accepted surface 默认要求单一连通；若阻断来自真实负向掩膜，只能作为阻断事实审计，不可作为普通 MultiPolygon 放行开关。
- DriveZone、DivStripZone、RCSDRoad、RCSDNode 和 SWSD negative context 的几何语义必须分层解释。

## 3. 回归要求

- official 39-case baseline 是质量冻结依据。
- rejected baseline 不等于待修缺陷，除非业务重新定义样本目标。
- full-input 外部 relation 校验输入不可消费时，应区分外部输入问题与 T04 构面失败。

## 4. 审计要求

每个 accepted/rejected case 都应能追溯 Step1 准入、Step4 事实解释、Step5 约束、Step6 几何组装和 Step7 发布原因。`STEP4_REVIEW` 只用于解释 Step4 soft-degrade，不得提升为最终状态。

## 5. 性能要求

internal full-input 批处理需要保留 worker、case 数、通过数、失败数、耗时和错误包索引。性能优化不得改变 Step1 准入、Step4 主证据、Step5 约束和 Step7 final state。
