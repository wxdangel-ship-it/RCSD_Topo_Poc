# 模块生命周期

## 1. 职责

本文件只登记模块生命周期状态，不展开模块实现过程。模块业务目标与上下游关系见 `docs/doc-governance/current-module-inventory.md`；模块内部契约见对应 `modules/<module>/INTERFACE_CONTRACT.md` 与 `modules/<module>/architecture/*`。

## 2. 生命周期类别

| 类别 | 含义 |
|---|---|
| `Active` | 当前正式业务模块，纳入项目主治理链路。 |
| `Active POC / 成果模块` | 当前有效的 POC 或成果模块，目录结构与正式模块一致，但不替代正式业务契约。 |
| `Retired` | 已退出当前主业务链，历史实现、文档或支撑入口可保留追溯。 |
| `Support Retained` | 已纳入治理的支撑 / 工具集合模块，不属于当前业务生产闭环。 |
| `Template` | 新模块启动模板，不参与业务生命周期。 |

## 3. 当前状态表

| 模块 ID | 生命周期 | 文档面 | 当前项目级状态 |
|---|---|---|---|
| `t00_utility_toolbox` | `Support Retained` | `modules/t00_utility_toolbox` | 工具集合模块，历史一次性预处理能力主要已整合至 T08，仍保留可追溯入口。 |
| `t01_data_preprocess` | `Active` | `modules/t01_data_preprocess` | SWSD Segment 构建模块，正式范围包含双向与单向 Segment。 |
| `t02_junction_anchor` | `Retired` | `modules/t02_junction_anchor` | 历史模块，当前主业务能力由 T07 / T03 / T04 / T08 承接。 |
| `t03_virtual_junction_anchor` | `Active` | `modules/t03_virtual_junction_anchor` | 交叉路口与 T 型路口虚拟锚定模块。 |
| `t04_divmerge_virtual_polygon` | `Active` | `modules/t04_divmerge_virtual_polygon` | 分歧、合流与复杂路口虚拟锚定模块，正式范围为 `Step1-7`。 |
| `t05_junction_surface_fusion` | `Active` | `modules/t05_junction_surface_fusion` | SWSD-RCSD 语义路口关系生产与 RCSD junctionization 模块。 |
| `t06_segment_fusion_precheck` | `Active` | `modules/t06_segment_fusion_precheck` | RCSDSegment 构建、replaceable 判定与 Segment 替换模块。 |
| `t07_semantic_junction_anchor` | `Active` | `modules/t07_semantic_junction_anchor` | 语义路口 1:1 锚定与 relation 补锚模块。 |
| `t08_preprocess` | `Active` | `modules/t08_preprocess` | SWSD / RCSD 预处理、质检修复与显性化模块。 |
| `t09_swsd_field_rule_restoration` | `Active` | 文档面 `modules/t09_swsd_field_rule_restoration` 缺失；实现面 `src/rcsd_topo_poc/modules/t09_swsd_field_rule_restoration` | 路口级通行规则还原模块，当前模块文档面待补齐。 |
| `p01_arm_build` | `Active POC / 成果模块` | `modules/p01_arm_build` | 异构路口通行能力 POC / 成果模块，当前历史 P10 口径统一改称 P01。 |
| `_template` | `Template` | `modules/_template` | 新模块启动模板，不是业务模块。 |

## 4. 当前主链

```text
T08 -> T01 -> T07 -> T03 -> T04 -> T05 -> T06 -> T09
```

P01 与主链相关，但定位为 POC / 成果模块，不作为 T09 正式替代契约。

## 5. 当前治理缺口

- T09 已补登为 Active 正式模块，但缺少标准模块文档面。
- T02 已 Retired，但入口登记仍需后续同步 retired / historical 口径。
- 未在本文件登记的模块目录，不自动视为当前正式治理对象。
