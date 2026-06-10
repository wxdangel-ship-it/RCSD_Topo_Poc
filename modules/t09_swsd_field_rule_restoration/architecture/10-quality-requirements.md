# 10 Quality Requirements

## 1. 业务正确性

- 禁止通行必须来自显式 restriction。
- arrow 和 special carrier 不得单独生成禁行。
- road-pair 证据不得无依据放大为 Arm-Movement 全量禁行。
- Step3 只对 `fully_prohibited + explicit_restriction` 生成 F-RCSD restriction。

## 2. GIS / 拓扑正确性

- 输入通过标准 vector reader 归一到目标 CRS。
- 缺失 CRS、关键字段或几何异常不得 silent fix。
- F-RCSD restriction 几何必须可解释；无法构造时记录风险或跳过。
- 拓扑不可达只表达不适用，不表达交通规则禁止。

## 3. 审计可追溯

- 每条 restored rule 必须引用 evidence id。
- 每条 F-RCSD restriction 必须回溯 Movement、restored rule、supporting evidence 和 T06 relation。
- summary 必须记录输入路径、计数、参数、输出路径、跳过原因和性能。

## 4. 性能可验证

- summary 至少记录 junction、arm、movement、evidence、rule、restriction 体量。
- Step3 summary 必须记录 carriers、restrictions、skipped reason 统计。
- 性能结论不得只用主观描述。

## 5. 治理要求

- README 作为凝练版需求说明。
- `architecture/04-solution-strategy.md` 作为详细版需求说明。
- `INTERFACE_CONTRACT.md` 作为稳定接口契约。
- 实现、测试、证据包入口变化必须同步对应文档。
