# SPEC：RCSD 场景路网拓扑 POC 项目规格

- 文档类型：项目级需求规格说明
- 项目名称：RCSD_Topo_Poc
- 版本：v0.2
- 状态：Draft
- 当前阶段：工程治理与正式业务模块并行维护
- 交付形态：外网 GitHub 仓库 + 内网执行 + 文件证据包 / 摘要反哺

---

## 1. 项目定位

`RCSD_Topo_Poc` 面向 RCSD 场景路网拓扑能力验证与工程化治理。项目当前处于成熟治理阶段，已形成可持续维护的仓库治理、模块文档契约、模块实现入口、测试与审计闭环。

项目级文档只描述跨模块事实、业务链路、治理边界和当前状态；模块内部算法、字段、步骤、入口与验收细节归属 `modules/<module>/architecture/*` 与 `modules/<module>/INTERFACE_CONTRACT.md`。

## 2. 当前项目事实

### 2.1 模块生命周期

- Active 正式业务模块：`t01_data_preprocess`、`t03_virtual_junction_anchor`、`t04_divmerge_virtual_polygon`、`t05_junction_surface_fusion`、`t06_segment_fusion_precheck`、`t07_semantic_junction_anchor`、`t08_preprocess`、`t09_swsd_field_rule_restoration`、`t10_e2e_orchestration`
- Active POC / 成果模块：`p01_arm_build`
- Retired 模块：`t02_junction_anchor`
- Support Retained 模块：`t00_utility_toolbox`
- 模板目录：`modules/_template/`

### 2.2 主业务链

当前 RCSD 主业务链为：

```text
T08 -> T01 -> T07 -> T03 -> T04 -> T05 -> T06 -> T09
```

其中 T08 / T01 / T07 可按输入准备情况并行推进；T05 汇总 T07 / T03 / T04 的锚定关系和构面成果后供 T06 消费；T06 输出 F-RCSD 承载关系后供 T09 还原通行规则。P01 是异构路口通行能力 POC / 成果模块，不替代 T09 正式契约。

T10 是端到端编排与 Case 证据组织模块，不替代上述项目级主业务链。T10 v1 局部编排范围为 `T01 -> T07 -> T03 -> T04 -> T05 -> T06 -> T09`；T08 作为独立前置预处理、质检与修复模块，不由 T10 v1 调用。

### 2.3 当前命名口径

- 用户历史口径 `P10` 当前统一改称为 `P01` / `p01_arm_build`。
- T02 已正式 Retired，历史实现、历史文档与支撑入口保留，当前主业务能力由 T07 / T03 / T04 / T08 承接。
- T01 正式范围包含双向与单向 SWSD Segment；双向 Segment 是 T06 / T09 后续建模主基础。
- T04 正式范围以 `Step1-7` 为准。
- T09 已补登为正式业务模块，但 `modules/t09_swsd_field_rule_restoration/` 模块文档面仍是治理缺口。

## 3. 项目范围

### 3.1 包含范围

- 仓库级治理规则、阅读链路、文档结构和 source-of-truth 分层。
- RCSD 场景拓扑业务模块的项目级生命周期登记。
- 文件证据包、summary / audit / review 和必要文本提炼的内外网协作口径。
- `modules/_template/` 新模块启动模板。
- 已登记模块的项目级角色、上下游关系和治理缺口。
- 与参考仓库 `Highway_Topo_Poc` 兼容的初始数据组织约定。

### 3.2 不包含范围

- 未登记业务模块的无边界扩展。
- 模块级算法、参数、阈值、字段强规则和执行步骤细节的项目级重复展开。
- Highway 业务实现、专项脚本、专项审计工件的整包迁移。
- 无任务书的新入口、新模块契约或长期脚本。
- 内网真实数据接入、专项回归与专项运行审计。

## 4. 跨模块业务原则

| 模块 | 项目级角色 |
|---|---|
| T00 | 工具集合模块，历史一次性预处理能力主要已被 T08 吸收，仍保留可追溯入口。 |
| T01 | SWSD Segment 构建模块，输出 T06 替换和 T09 通行建模所需 Segment 基础。 |
| T02 | Retired 历史模块，当前能力已迁移或被 T07 / T03 / T04 / T08 承接。 |
| T03 | 基于道路面、SWSD、RCSD 构建交叉路口与 T 型路口虚拟锚定。 |
| T04 | 基于道路面、导流带、SWSD、RCSD 构建分歧、合流、复杂路口虚拟锚定。 |
| T05 | 汇总 T07 / T03 / T04 成果，生产 SWSD-RCSD 语义路口关系和 RCSD junctionization 成果。 |
| T06 | 基于 T01 Segment 与 T05 语义关系构建 RCSDSegment，并执行 Segment 替换生成 F-RCSD 承载关系。 |
| T07 | 迁移 T02 1:1 锚定能力，并基于 T05 relation 做无路口面特征补锚。 |
| T08 | SWSD / RCSD 预处理与质检修复模块，为 T01 / T03 / T04 / T05 / T06 / T09 提供规范输入。 |
| T09 | 基于 SWSD Laneinfo / restriction 与 T06 F-RCSD 承载关系还原路口级通行规则。 |
| T10 | 端到端业务流程编排与 Case 级证据组织模块；v1 编排 T01 / T07 / T03 / T04 / T05 / T06 / T09，T08 独立运行。 |
| P01 | 异构路口通行能力 POC / 成果模块，不作为 T09 正式替代契约。 |

更细的模块业务说明以 `docs/doc-governance/current-module-inventory.md` 为准。

## 5. 文档结构原则

项目文档按低耦合、高内聚分工维护：

| 文档 | 职责 |
|---|---|
| `README.md` | 仓库级基础文档索引，便于从根目录快速进入当前文档链路。 |
| `AGENTS.md` | Agent 会话级硬规则、停机条件和执行边界。 |
| `SPEC.md` | 项目目标、当前事实、跨模块业务原则和治理不变量。 |
| `docs/PROJECT_BRIEF.md` | 面向业务读者的项目摘要、当前范围、非目标和近期治理缺口。 |
| `docs/architecture/*` | 项目级架构目标、全局业务概念、字段语义、跨模块方案、证据审计、质量要求和风险。 |
| `docs/doc-governance/README.md` | 主阅读链路与文档职责边界。 |
| `docs/doc-governance/module-lifecycle.md` | 模块生命周期状态事实。 |
| `docs/doc-governance/current-module-inventory.md` | 模块业务目标、上下游关系与治理缺口。 |
| `docs/doc-governance/current-doc-inventory.md` | 项目级文档结构、业务范畴和治理状态。 |
| `docs/doc-governance/module-doc-status.csv` | 机器可读模块文档状态索引。 |

## 6. 治理不变量

- 项目级 source-of-truth：`SPEC.md`、`docs/PROJECT_BRIEF.md`、`docs/architecture/*`、`docs/doc-governance/module-lifecycle.md`。
- 模块级 source-of-truth：`modules/<module>/architecture/*` 与 `modules/<module>/INTERFACE_CONTRACT.md`。
- `README.md` 只承载仓库级基础索引，不承担项目事实或模块契约。
- `AGENTS.md` 只承载仓库级 durable guidance，不承担项目事实摘要。
- `specs/*` 是 SpecKit 变更工件，不替代当前项目级或模块级源事实。
- `outputs/`、`outputs/_work/`、`.claude/worktrees/`、`.venv/`、临时审计工件不属于主阅读路径。
- 中等及以上结构化治理变更走 SpecKit，且不得绕开当前源事实边界。

## 7. 数据与质量约束

- 当前 patch 输入组织方式沿用参考仓库兼容布局：

```text
<PatchID>/
  PointCloud/
  Vector/
  Tiles/
  Traj/
```

- GIS / 拓扑 / 空间数据相关任务必须覆盖 CRS 与坐标变换、拓扑一致性、几何语义可解释性、审计可追溯性和性能可验证性。
- 未在项目或模块源事实中正式启用的字段，不得进入强规则。
- 字段正式启用时，必须同步写入对应项目级约束或模块契约，并说明可用语义、适用范围和未确认边界。
- 模块输出、入口、审计和测试状态必须与 `docs/repository-metadata/entrypoint-registry.md`、模块契约和测试面保持一致。
- 旧 `TEXT_QC_BUNDLE v1` 仅作为历史兼容工具保留；当前正式协作以文件证据包、summary、audit、review 和必要文本提炼为准。

## 8. 当前治理缺口

- T09 已补登为正式模块，但模块文档面缺失，需要补齐 `modules/t09_swsd_field_rule_restoration/INTERFACE_CONTRACT.md`、`README.md`、`AGENTS.md` 与 architecture 文档。
- T10 已启动为端到端编排模块；当前 v1 只建立 contract validation 与 Case manifest，真实模块执行编排和空间切片仍是后续缺口。
- T02 已 Retired，但仓库级入口登记仍需在后续入口治理中同步 retired / historical 口径。
- 项目级文档必须持续避免重复模块实现细节；模块细节应回到模块级 source-of-truth。
