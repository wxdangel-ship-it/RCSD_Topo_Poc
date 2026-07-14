# SPEC：RCSD_Topo_Poc 项目级简版需求

- 文档类型：项目级需求简版
- 详细版需求：`docs/PROJECT_REQUIREMENTS.md`
- 详细方案策略：`docs/architecture/03-solution-strategy.md`
- 状态：Draft

## 1. 项目目标

`RCSD_Topo_Poc` 的目标是把 SWSD 的现场语义道路能力迁移到 RCSD / F-RCSD 承载网络中。项目不是单纯生成某个空间图层，而是形成一条可审计的数据融合链：先建立 SWSD-RCSD 语义路口关系，再基于这些关系替换 Segment，最后在 F-RCSD 上恢复路口通行规则。

## 2. 主业务链

```text
T08 -> T01 -> T07 -> T03 -> T04 -> T05 -> T06 -> T09
```

| 层级 | 模块 | 简要职责 |
|---|---|---|
| 输入准备 | T08 | 预处理 SWSD / RCSD，显性化 restriction、Laneinfo 和数据质量问题。 |
| Segment 基础 | T01 | 将 SWSD Road/Node 组织成后续可替换的 Segment。 |
| 路口关系 | T07 / T03 / T04 / T05 | 构建并发布 SWSD-RCSD 语义路口关系。T07 处理已有路口面锚定并保留可选兼容 relation 补锚，T03 处理交叉 / T 型，T04 处理分歧 / 合流 / 复杂路口，T05 统一发布 relation。 |
| Segment 替换 | T06 | 基于 T01 Segment 与 T05 relation 判断可替换性，处理 RCSD 数据质量和 SWSD/RCSD 工艺差异，输出 F-RCSD Road / Node。 |
| 人工审计 | T11 | 在 T10 编排中于 T06 后、T09 前抽取 relation repair candidates 与人工模板；只读审计，不改变 T06 到 T09 的业务数据依赖。 |
| 通行恢复 | T09 | 基于 SWSD restriction / Laneinfo 与 T06 F-RCSD 承载关系恢复路口级通行规则。 |
| 编排证据 | T10 | 组织 Case package、Case replay、full pipeline manifest、T06 funnel、T11 candidate audit、feedback 和 visual check；不替代 T01-T09 / T11 算法。 |

T10 v1 Case runner 编排 `T01 -> T07 Step1/2 -> T03 -> T04 -> T05 -> T06 -> T11 -> T09`。T11 是 audit-only 阶段，T09 业务输入仍直接来自 T06。T08 是独立前置预处理、质检和修复模块，不由 Case runner 调用；内网全量总控可把 T08 作为独立阶段串入全量链路。T07 Step3 是可选兼容 relation 补锚，不是 T10 默认主链阶段。

## 3. 核心业务需求

1. 输入数据必须先被整理成可被下游稳定消费的 SWSD / RCSD / 道路面 / 导流带 / restriction / Laneinfo 证据。
2. SWSD Road/Node 必须形成有方向、pair、junc 和 road body 语义的 Segment，作为 T06 和 T09 的基础。
3. T07、T03、T04、T05 必须共同建立可被 T06 消费的 SWSD-RCSD 语义路口 relation，避免下游重复解释路口关系。
4. T06 不能只按“有 1:1 relation”机械替换 Segment，必须处理 RCSD 端点、方向、道路切分、提前右转、内部短连接、surface 证据和 topology 连通等真实数据差异；surface 证据只能在 T04 未 reject、Patch 无冲突、证据可解释且 topology 回退通过时，将 retained-junction 距离 gate 降级为风险释放。
5. T11 必须在 T10 工作流中于 T06 后抽取人工 relation 修复候选，且不得把候选解释为人工确认或 T09 业务输入。
6. T09 必须在 F-RCSD 承载关系上恢复 SWSD 现场通行规则，并保留可追溯的 restriction、Laneinfo 和风险审计链。

## 4. 当前模块生命周期

- Active 正式业务模块：`t01_data_preprocess`、`t03_virtual_junction_anchor`、`t04_divmerge_virtual_polygon`、`t05_junction_surface_fusion`、`t06_segment_fusion_precheck`、`t07_semantic_junction_anchor`、`t08_preprocess`、`t09_swsd_field_rule_restoration`、`t10_e2e_orchestration`、`t11_manual_relation_review`
- Active POC / 成果模块：`p01_arm_build`、`p02_wuhan_local_experiment`
- Retired 模块：`t02_junction_anchor`
- Support Retained 模块：`t00_utility_toolbox`

模块生命周期事实以 `docs/doc-governance/module-lifecycle.md` 为准；模块业务盘点以 `docs/doc-governance/current-module-inventory.md` 为准。

## 5. 范围与非目标

项目级范围：

- 维护主业务链、模块职责、跨模块 handoff 和质量边界。
- 维护文件证据包、summary、audit、review、Case replay 和内外网协作口径。
- 维护已登记模块的生命周期与项目级治理缺口。

项目级非目标：

- 不在根目录文档展开模块内部算法、字段、参数、阈值和入口教程。
- 不把 T10 feedback 直接变成 T06 Step3 替换白名单。
- 不把 P01 POC 结果直接提升为 T09 正式契约。
- 不把 P02 武汉局部实验结果直接提升为全量生产口径，也不让 P02 替代 T08/T01/T05/T06 正式职责。
- 不继续扩展 Retired T02 的业务职责。

## 6. 近期改进重点

- 产品化 T07/T03/T04/T05 relation 的成功、fallback、review-only、blocked 和 upstream-needed 状态。
- 将 T06 problem registry 与 T10 feedback 形成稳定闭环，让可自动消费的问题进入 T05，其它问题进入人工复核或上游模块任务。
- 建立 T06 Step3 后的批量 QA 指标，覆盖 source 同源性、端点完整性、节点映射、提前右转挂接、surface closure、F-RCSD 连通和 T09 carrier 可用性。
- 结合 RCSD Laneinfo 与轨迹通行证据继续增强 T09。
