# 01 引言与目标

## 1. 文档定位

本文件说明 T01 的架构背景、业务目标和边界。模块需求以 `SPEC.md` 为准，稳定接口以 `INTERFACE_CONTRACT.md` 为准，具体实现策略见 `03-solution-strategy.md`。

## 2. 模块定位

T01 位于 SWSD 数据进入主业务链后的 Segment 构建阶段。它消费 T08 预处理后的 SWSD `nodes / roads`，通过双向多阶段构段、单向补段和最终聚合，形成 T06/T09 可继续消费的 `segment.gpkg` 与配套审计产物。

T01 不直接生产 RCSD Segment，也不负责路口 1:1 关系构建。它的业务价值是把 SWSD 道路网络整理成可解释、可审计、可回归保护的 Segment 承载层，为后续替换、通行规则恢复和端到端 Case 证据组织提供稳定输入。

## 3. 目标

- 在非封闭式双向道路场景下稳定构建双向 Segment。
- 在 Step5C refreshed 结果之后执行单向补段，补齐双向流程无法覆盖但业务上需要承载的 road。
- 在 Step6 聚合正式 `segment.gpkg`，并反查内部节点、`sgrade`、grade/kind 冲突和未构段 road。
- 通过 freeze compare 与证据包保护 active baseline，避免单向补段或局部修复误覆盖已确认双向口径。

## 4. 非目标

- 不修改 T05/T06/T09 的下游产物。
- 不把单向补段规则反向写入双向 Step1-Step5C。
- 不从局部样本或几何形态反推未确认字段语义。
- 不在未授权时更新 active freeze baseline。

## 5. 文档边界

- `SPEC.md`：业务需求、范围和对错边界。
- `INTERFACE_CONTRACT.md`：稳定输入输出、官方入口和参数类别。
- `02-data-and-domain-model.md`：对象、字段和上下游数据关系。
- `03-solution-strategy.md`：Step1-Step6 与单向补段的实现策略。
- `04-evidence-and-audit.md`：证据、审计和 baseline。
- `05-quality-requirements.md`：质量、GIS / 拓扑 / 性能要求。
- `06-risks-and-technical-debt.md`：风险和技术债。
- `accepted-baseline.md`：已确认 baseline 的补充说明；不替代 01-06 主结构。
