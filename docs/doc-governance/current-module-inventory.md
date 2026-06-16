# 当前模块盘点

## 范围

- 盘点日期：2026-06-10
- 目的：用项目级语言说明当前模块业务目标、上下游关系和治理缺口
- 非职责：不展开模块内部实现步骤、字段规则、入口参数或验收细节

## 当前生命周期结论

- `Active`：`t01_data_preprocess`、`t03_virtual_junction_anchor`、`t04_divmerge_virtual_polygon`、`t05_junction_surface_fusion`、`t06_segment_fusion_precheck`、`t07_semantic_junction_anchor`、`t08_preprocess`、`t09_swsd_field_rule_restoration`、`t10_e2e_orchestration`
- `Active POC / 成果模块`：`p01_arm_build`
- `Retired`：`t02_junction_anchor`
- `Support Retained`：`t00_utility_toolbox`
- `Template`：`modules/_template/`

## 模块业务说明与目标（凝练版）

| 模块 ID | 生命周期 | 关键业务说明与业务目标 |
|---|---|---|
| `t00_utility_toolbox` | Support Retained | 项目工具集合，承载历史一次性预处理、转换与支撑脚本。主要能力已被 T08 吸收，但历史工具仍保留可追溯入口。 |
| `t01_data_preprocess` | Active | 构建 SWSD Segment，正式范围包含双向与单向 Segment。双向 Segment 是 T06 替换与 T09 通行建模的基础，历史属性修正逐步移交 T08。 |
| `t02_junction_anchor` | Retired | 历史承载 SWSD 道路面资料判定、路口面锚定、Stage3/4 虚拟路口与 1:N 修复工具。当前能力分别由 T07、T03、T04、T08 承接，保留历史实现与文档。 |
| `t03_virtual_junction_anchor` | Active | 面向交叉路口与 T 型路口构建虚拟锚定，消费道路面、SWSD 与 RCSD 上下文。输出虚拟路口面、`nodes` 更新与 T05 relation evidence，不处理环岛。 |
| `t04_divmerge_virtual_polygon` | Active | 面向分歧、合流与复杂路口构建 `Step1-7` 虚拟锚定。消费道路面、导流带、SWSD、RCSD，输出 accepted/rejected 发布层与 relation evidence，复杂属性修正逐步移交 T08。 |
| `t05_junction_surface_fusion` | Active | 汇总 T07 / T03 / T04 的锚定与构面成果，正式生产 SWSD-RCSD 语义路口关系。负责 RCSD junctionization、复杂路口归组、环岛预处理与 copy-on-write RCSD 输出。 |
| `t06_segment_fusion_precheck` | Active | 基于 T01 Segment 与 T05 语义路口关系构建 RCSDSegment，判定 replaceable 集合。执行 Segment 替换，输出 F-RCSD Road / Node 与下游 T09 稳定承载关系。 |
| `t07_semantic_junction_anchor` | Active | 迁移 T02 语义路口级 1:1 锚定能力，并通过 T05 relation 做无路口面特征补锚。用于提高当前替换率，未来 RCSD 滚动构图方案下不作为长期依赖。 |
| `t08_preprocess` | Active | SWSD / RCSD 正式预处理模块，提供格式转换、Road/Node 类型聚合、质检修复、restriction / Laneinfo 显性化与 RCSD 清理。为 T01、T03、T04、T05、T06、T09 提供规范输入。 |
| `t09_swsd_field_rule_restoration` | Active | 基于 SWSD Laneinfo、restriction 与 T06 F-RCSD 混合承载关系，还原现场路口级通行规则。当前缺少 RCSD Laneinfo 与轨迹通行证据，需后续迭代完善。 |
| `t10_e2e_orchestration` | Active | 端到端业务流程编排与 Case 级证据组织模块。v1 Case runner 编排 T01 / T07 Step1/2 / T03 / T04 / T05 / T07 Step3 / T06 / T09，T08 保持独立前置预处理、质检与修复定位；当前已支持空间切片 Case 包、Case 级 replay、T06 上游反馈包、反馈迭代防回退与内网全量总控。 |
| `p01_arm_build` | Active POC / 成果模块 | 当前仓库中用户历史 `P10` 口径统一改称为 `P01`。P01 面向异构路口通行能力 / RoadNextRoad POC，不作为 T09 正式契约。 |

## 当前业务关系

- 输入准备：T08 负责 SWSD / RCSD 预处理和显性化，T01 基于 SWSD 构建 Segment。
- 路口锚定：T07 处理已有路口面 1:1 和补锚，T03 处理交叉 / T 型虚拟锚定，T04 处理分歧 / 合流 / 复杂路口虚拟锚定。
- 关系融合：T05 汇总 T07 / T03 / T04，生产 SWSD-RCSD 语义路口关系。
- Segment 替换：T06 基于 T01 Segment 与 T05 relation 构建 RCSDSegment 并输出 F-RCSD 承载关系。
- 通行恢复：T09 基于 SWSD 通行规则证据和 T06 F-RCSD 承载关系还原融合后路口通行能力。
- 端到端编排：T10 v1 以文件级 handoff 方式组织 Case package、空间切片、Case 级 replay、T06 反馈闭环和内网全量总控；Case runner 不调用 T08，全量总控可把 T08 作为独立前置阶段串联。
- POC 验证：P01 承载异构路口通行能力 POC，不替代 T09。

## 当前治理缺口

1. `t09_swsd_field_rule_restoration` 已具备初始模块文档面，后续需结合 RCSD Laneinfo 与轨迹通行证据迭代完善。
2. `t10_e2e_orchestration` 已具备 Case 级 replay、空间切片、反馈闭环与内网全量总控；后续需持续收敛真实数据下的反馈迭代质量、全量审计口径和跨模块 handoff 稳定性。
3. `t02_junction_anchor` 已 Retired，但入口登记仍需后续同步 retired / historical 口径。
4. 模块级实现细节应保留在模块文档，项目级盘点只维护业务目标、关系和缺口。
