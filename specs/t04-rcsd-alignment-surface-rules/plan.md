# T04 RCSD Alignment and Surface Rules Plan

## 1. Strategy

按“需求冻结 -> 模型落地 -> 场景映射 -> 掩膜/构面 -> Step6 收敛 -> 回归门禁”的顺序推进。

本计划不允许在没有 `rcsd_alignment_type` 一等模型的情况下继续用 case-by-case patch 修正路口面，因为那会继续扩大旧字段推断和视觉回归的不稳定性。

## 2. Role Responsibilities

| Role | Responsibility | Required Output |
|---|---|---|
| Product | 守住六场景业务口径、case 预期与人工审计结论 | case acceptance matrix、scenario expectation |
| Architecture | 定义 alignment/mask/case-level 聚合边界，控制文件体量 | module split plan、interface delta |
| Development | 按切片实现模型、映射、掩膜、Step6 收敛 | small safe patches、audit fields |
| Testing | 补齐 synthetic、unit、real-case、39-case gate | pytest gates、fixtures、baseline assertions |
| QA | 守 CRS、拓扑、几何、审计、性能、视觉可追溯 | release checklist、visual/perf evidence |

## 3. Implementation Slices

### Slice 0 - Requirement Freeze

- 确认模块源事实已记录 RCSD/SWSD 语义路口、`rcsd_alignment_type`、负向掩膜、六场景和复杂路口规则。
- 确认 `no_surface_reference` 只是防御性兜底。
- 确认 39-case 清单、30-case frozen baseline、新增 6-case 和重点问题 case。

### Slice 1 - Step4 RCSD Alignment Model

- 新增 `rcsd_alignment.py` 或等价模块。
- 定义 `RcsdAlignmentType` 和 alignment result dataclass。
- 把 `PositiveRcsdSelectionDecision` 扩展为输出 `rcsd_alignment_type`、positive ids、unrelated ids、candidate conflict reasons。
- 支持五类 alignment：semantic junction、partial junction、road-only、none、ambiguous。
- 将 ambiguous 从审计文本提升为正式阻断状态。

### Slice 2 - Step4/Step5 Contract Freeze

- `T04EventUnitResult` 持久化 alignment result。
- `step4_candidates.json`、event evidence audit、review index、summary 输出 `rcsd_alignment_type`。
- Step5 只能消费 frozen alignment result，不再从 `required_rcsd_node / selected_rcsdroad_ids / fallback_rcsdroad_ids` 反推对齐类型。
- `rcsd_match_type` 保留为兼容派生字段。

### Slice 3 - Surface Scenario Mapping

- 重写 `surface_scenario.py` 为纯映射层。
- 输入为 `has_main_evidence + rcsd_alignment_type + swsd_semantic_context`。
- 精确区分 partial junction 与 road-only fallback 的截面边界。
- 明确 `no_surface_reference` 只能由缺失合法 section reference 或输入前提异常触发。

### Slice 4 - Negative Mask Model

- 新增或拆分 `support_domain_masks.py`。
- 将 unrelated SWSD nodes/roads、unrelated RCSDNode/RCSDRoad、divstrip body/void、forbidden/cut 分通道建模。
- Step5 输出 mask source ids、source geometries、union geometry、overlap audit。
- Step6 后验复核每个通道是否被侵入，并将失败映射为 rejected。

### Slice 5 - Complex Case-Level Alignment

- 新增 `case_rcsd_alignment.py` 或等价聚合层。
- 汇总每个 unit 的 alignment result。
- 判断 case-level 是否跨多个无关 RCSD 语义对象混聚。
- 输出 unit-level 和 case-level audit。
- unit 间 bridge 使用同一截面/正向生长/负向掩膜规则。

### Slice 6 - Step6 Constraint Discipline and Split

- 拆出 `polygon_assembly_guards.py`、`polygon_assembly_relief.py`、`polygon_assembly_models.py` 或等价模块。
- 将 Step6 relief 限定为 within constraints cleanup。
- 任何需要扩大 allowed 或削弱 forbidden/cut 的逻辑上移 Step5 并形成审计字段。
- 避免 `polygon_assembly.py` 继续逼近 100 KB。
- 撤销将 `barrier_separated_case_surface_ok` 作为普通 MultiPolygon accepted 放行条件的逻辑。
- 对 complex / multi 场景，Step6 必须先基于 unit 邻接关系生成 inter-unit section bridge surface，再判断最终连通性；简单 case 不得因为 complex bridge/relief 规则发生回退。

### Slice 7 - Baseline and QA Gates

- 新增统一 39-case baseline gate。
- 保留并增强 30-case gate、新增 6-case gate、target11/问题 case gate。
- 增加 CRS/valid geometry/feature count/summary audit consistency 断言。
- 产出 visual audit index 和 perf audit threshold。

## 4. Verification Matrix

| Level | Required Verification |
|---|---|
| Syntax | modified Python `py_compile` |
| Unit | alignment type, surface scenario mapping, Step5 masks, Step6 guards |
| Synthetic | five alignment types, ambiguous block, partial vs road-only |
| Real case | 30-case frozen, new6, 39-case,重点问题 case |
| QA | CRS, valid geometry, forbidden overlap, nodes writeback, visual index, perf audit |

## 5. Risks and Controls

- Risk: partial junction 被误发布为完整 RCSD 语义路口。Control: `rcsd_alignment_type` 与 publish semantics 分离测试。
- Risk: ambiguous 被 score 第一名吞掉。Control: ambiguous explicit rejected test。
- Risk: Step5 继续旧字段反推。Control: Step5 输入测试中只提供 frozen alignment result。
- Risk: Step6 relief 放宽约束。Control: post-cleanup guard + forbidden/cut invariants。
- Risk: 39-case gate 未落地导致视觉回归。Control: 正式 pytest 或固定命令 gate。
- Risk: 文件体量超过 100 KB。Control: 每次源码写入前做 byte-size check，拆分 Step6 高风险文件。
