# 05 质量要求

## 1. 业务正确性

- restriction 是唯一能改变 Movement 禁行结果的显式禁止证据。
- arrow、完整 arrow 排除和 special carrier 不能单独生成禁止规则。
- `partially_prohibited` 不自动放大为 F-RCSD 全 Arm 禁行。
- `no_prohibition_evidence / unknown / not_a_traffic_rule` 不生成 F-RCSD restriction。
- Step3 只处理 `fully_prohibited + explicit_restriction`。

## 2. GIS 与拓扑要求

- 所有输入空间处理统一到 `EPSG:3857`。
- 缺 CRS、缺关键字段或几何不可解释时必须显式失败或审计。
- F-RCSD restriction 的 carrier 必须能从 T06 relation 或 retained SWSD seed fallback 定位到 F-RCSD Road。
- 几何无法构造时不得 silent fix，应记录跳过或风险。

## 3. 回归要求

测试应覆盖 Arm 构建、Movement carrier universe、restriction 优先级、arrow exclusion 不生成禁行、同一 restriction id 多 link-pair、special carrier、F-RCSD relation 映射、retained SWSD carrier fallback 和 Step3 去重。

## 4. 性能要求

restriction / arrow 候选可使用 road-pair 索引和空间索引优化，但索引只减少扫描范围，不改变证据身份和审计语义。summary 必须记录输入计数、输出计数、跳过原因和阶段耗时。
