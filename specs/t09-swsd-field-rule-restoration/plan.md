# T09 Step3 FRCSD Restriction Modeling Plan

## Scope

本计划扩展 T09 到 Step3：消费 T09 Step1/2 的 SWSD Movement 级禁止证据，并通过 T06 Step3 输出的 SWSD-FRCSD Segment 关系，将禁止通行关系投影到 FRCSD Road-to-Road restriction。

本计划同时要求 T06 Step3 增加一个稳定关系输出，用于承载 T09 Step3 的 Arm 映射输入。T06 只新增审计/关系输出，不改变已有 FRCSD Road / Node 生产逻辑。

## Product

- T06 新增 `t06_step3_swsd_frcsd_segment_relation.gpkg/csv/json`。
- T09 新增 `frcsd_restriction.gpkg/csv/json`。
- 输出 restriction 以 `LinkID -> outLinkID` 表达 FRCSD 路口处禁止通行。
- 当前不生成 FRCSD `RoadNextRoad`。
- 当前不消费 FRCSD 车道级箭头；后续可用 FRCSD arrow 与轨迹通行能力补充。

## Architecture

技术路线采用 T06 relation-first：

1. T09 Step1/2 构建 SWSD Arm、Movement 与禁止证据。
2. T06 Step3 输出 SWSD Segment 到 FRCSD Road/Node 的关系。
3. T09 Step3 通过 SWSD Arm 的 `segment_ids` 查找 T06 relation。
4. 对 replaced Segment 使用 `source=1` FRCSD road；对 retained Segment 使用 `source=2` 保留 road。
5. 对 fully prohibited Movement 生成 FRCSD `LinkID -> outLinkID` restriction。

T09 Step3 不以 FRCSD 独立 Arm 构建作为主策略，避免重复 P01/T09 Arm 逻辑并减少异构 Road ID 级匹配。

## Development

允许改动：

- `specs/t09-swsd-field-rule-restoration/**`
- `specs/t06-step3-segment-replacement/**`
- `modules/t06_segment_fusion_precheck/INTERFACE_CONTRACT.md`
- `modules/t06_segment_fusion_precheck/architecture/**`
- `src/rcsd_topo_poc/modules/t06_segment_fusion_precheck/**`
- `src/rcsd_topo_poc/modules/t09_swsd_field_rule_restoration/**`
- `tests/modules/t06_segment_fusion_precheck/**`
- `tests/modules/t09_swsd_field_rule_restoration/**`

禁止新增 repo CLI、`scripts/` 常驻入口、`Makefile` 目标、模块 `run.py` 或模块 `__main__.py`。

## Testing

- T06 单元测试覆盖 replaced 与 retained_swsd Segment relation 输出。
- T09 单元测试覆盖 FRCSD restriction 生成、去重、不生成无证据 restriction。
- XS1 本地证据包执行 T09 Step1/2 + Step3。
- 对 `1263661` 做业务审计，说明 FRCSD restriction 的 SWSD Movement 来源和 T06 relation 承载。

## QA

- CRS：输入输出均按 EPSG:3857 读写或记录 CRS 归一化。
- 拓扑一致性：不得 silent fix 缺失的 Segment relation、FRCSD road 或端点 node。
- 几何语义：restriction 几何只由明确的进入/退出 FRCSD road 端点构造。
- 审计追溯：每条 FRCSD restriction 必须回溯到 SWSD Movement、T09 evidence 和 T06 relation。
- 性能可验证：summary 记录输入 Movement、relation、输出 restriction、跳过原因计数。
