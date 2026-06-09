# RCSD_Topo_Poc - Project Brief

## 1. 项目摘要

`RCSD_Topo_Poc` 当前处于成熟治理阶段：仓库骨架、文档分层、模块模板、文本回传协议、正式业务模块与 POC 成果模块均已进入持续维护。项目级文档的重点是表达当前事实、主业务链、模块关系和治理缺口，不再重复模块内部实现过程。

## 2. 当前业务链

当前 RCSD 主业务链：

```text
T08 -> T01 -> T07 -> T03 -> T04 -> T05 -> T06 -> T09
```

T08 提供 SWSD / RCSD 预处理输入，T01 生成 SWSD Segment，T07 / T03 / T04 建立不同类型路口锚定关系，T05 统一生产 SWSD-RCSD 语义路口关系，T06 构建并替换 Segment 形成 F-RCSD 承载关系，T09 基于融合后承载关系还原路口级通行规则。

## 3. 当前模块状态

- Active 正式业务模块：`t01_data_preprocess`、`t03_virtual_junction_anchor`、`t04_divmerge_virtual_polygon`、`t05_junction_surface_fusion`、`t06_segment_fusion_precheck`、`t07_semantic_junction_anchor`、`t08_preprocess`、`t09_swsd_field_rule_restoration`
- Active POC / 成果模块：`p01_arm_build`
- Retired 模块：`t02_junction_anchor`
- Support Retained 模块：`t00_utility_toolbox`
- 模板目录：`modules/_template/`

模块业务目标与上下游关系以 `docs/doc-governance/current-module-inventory.md` 为准；模块生命周期以 `docs/doc-governance/module-lifecycle.md` 为准。

## 4. 当前业务口径

- T01 正式范围包含双向与单向 SWSD Segment；双向 Segment 是 T06 / T09 后续建模主基础。
- T02 已正式 Retired，历史文档、实现与支撑入口保留，当前能力由 T07 / T03 / T04 / T08 承接。
- T04 正式范围以 `Step1-7` 为准。
- T09 已补登为正式模块，负责基于 SWSD Laneinfo / restriction 与 T06 F-RCSD 承载关系还原路口级通行规则；当前缺少 RCSD Laneinfo 与轨迹通行证据。
- 用户历史口径 `P10` 当前统一改称为 `P01` / `p01_arm_build`；P01 是异构路口通行能力 POC / 成果模块，不作为 T09 正式契约。

## 5. 当前范围

- 维护项目级 source-of-truth、文档结构、模块生命周期和主业务链。
- 维护已登记模块的项目级角色和治理缺口。
- 维护 `TEXT_QC_BUNDLE` 文本回传协议和基础粘贴性守卫。
- 维护 `modules/_template/` 作为新模块启动模板。
- 保持与参考仓库兼容的初始数据组织约定。

## 6. 当前非目标

- 不在项目级文档重复模块内部步骤、字段、参数、入口和验收细节。
- 不无边界扩展未登记模块。
- 不迁移 Highway 业务实现、专项脚本或历史审计工件。
- 不在本轮项目级文档治理中创建 T09 模块文档面。
- 不在本轮项目级文档治理中修改 T02 / T09 模块契约、CLI、scripts 或入口登记。

## 7. 近期治理缺口

- 补齐 T09 标准模块文档面。
- 将 T02 retired / historical 口径同步到入口登记。
- 持续保持项目级文档低耦合：项目级只写当前事实和模块关系，模块细节回到模块级 source-of-truth。
