# T12 路口级 FRCSD 质量审计

**Feature Branch**: `codex/t12-junction-quality-20260731`
**Created**: 2026-07-31
**Status**: Approved
**Input**: 用户批准在 T12 中增加基于 T03 失败审计与 T07 关系基数失败的 Junction 级质量错误输出。

## 1. 业务目标

在既有 T12 Segment 通行质量审计之外，增加互不混层的 Junction 质量审计：

1. T03 rejected 仅作为候选来源，T12 使用原始 1V1 FRCSD Road/Node 重新验证；
2. 准确率优先确认 `shared_degree1_terminal_collapse` 与
   `multi_component_unmatched_support`；
3. T07 Step3 已稳定识别的 `one_target_to_many_base` 与
   `many_target_to_one_base` 直接发布为 T12 Junction 问题，不重新裁决；
4. `duplicate_target_rows` 不进入本次 Junction 正式输出；
5. Segment 输出、决定逻辑和既有 `1026960` 基线保持不变；
6. Junction 主几何为 SWSD 代表路口 Point，根因和空间证据独立保留；
7. 不修改输入、不自动修复、不 silent fix、不按 CaseID 特判。

## 2. 五类职责视角

### 2.1 产品

- 最终成果同时包含既有 Segment 错误和新增 Junction 错误，两者独立发布。
- T03 confirmed 类型为：
  - `junction_required_topology_missing`
  - `junction_reality_or_precision_gap`
- T07 统一 issue type 为 `junction_relation_cardinality_mismatch`，
  通过 detection rule 区分 `one_target_to_many_base` 与
  `many_target_to_one_base`。
- N:1 冲突按受影响 SWSD Junction 逐行输出，并共享同一个 conflict group。

### 2.2 架构

- T12 增加可选 `--t03-run-root` 与 `--t07-step3-run-root`；
  旧调用不传新参数时完全兼容。
- T03 target projection、endpoint degree、support component 由 T12
  使用原始 1V1 FRCSD 重算，不依赖 `outputs/_work` 研究 CSV。
- T07 只消费正式 `relation_cardinality_errors.csv/json`，不修改 T07 算法。
- T10 将当前 T03 run root 和可用的 T07 Step3 root 显式交给 T12；
  T12 仍为 audit-only，不改变 T06/T11/T09 handoff。

### 2.3 研发

- Junction 逻辑放入独立模块，避免扩大既有 Segment 候选文件。
- FRCSD Road/Node、SWSD Node、空间索引和图只构建一次。
- Road Direction 严格解释；mainNode/alias 只作分组，不能创建 carrier。
- 距离只进入审计，不单独作为确认或排除依据。
- 不硬编码 Case、Junction、Road、Node 或 Segment ID。

### 2.4 测试

- 覆盖 T03 两类规则各两个正样本及明确负样本。
- 覆盖 T07 1:N、N:1 逐 Junction 展开和 duplicate 排除。
- 覆盖 CRS、无效几何、跨层、Direction、alias、计数守恒与审计字段。
- 冻结 `1026960` 的 63/10/53/0 Segment 结果及 10 个 confirmed
  candidate ID/type。
- 覆盖 T10 Case/full runner 新 handoff 和旧调用兼容。

### 2.5 QA

- CRS 必须显式存在，所有距离计算使用 metre-based projected CRS。
- FRCSD endpoint 拓扑不补点、不吸附；输入几何不修复。
- manifest 记录输入绝对路径、SHA-256、CRS、参数、来源 run identity、
  计数、决定规则、环境与分阶段耗时。
- QGIS 工程同时加载原始 SWSD、原始 FRCSD、Junction candidates、
  confirmed、exclusions 和 evidence。
- 性能分别记录 Segment 与 Junction 阶段；完整内网性能由内网脚本复验。

## 3. T03 正式判定

### 3.1 候选域

- 正式输入门禁：`has_evd=yes`、`is_anchor=no`、
  `kind_2 in {4, 2048}`。
- T03 Step7 未 accepted，且有完整 Step3/association/Step6/Step7
  审计链。
- 输入几何无效、跨层高置信解释或源工件不完整时不得 confirmed。

### 3.2 `shared_degree1_terminal_collapse`

必须同时满足：

- `association_class=B`
- `association_state=not_established`
- `required_rcsdnode_count=0`
- `target_group_node_count>=2`
- 所有 target 在原始 FRCSD support Road 上均投影为 terminal endpoint
- 所有 target 指向同一 endpoint，且该 support endpoint degree 均为 1
- 原始 FRCSD 不存在可表达 SWSD 路口臂悬/通行关系的替代局部 carrier
- 无跨层和输入几何阻断

确认后：

- `issue_type=junction_required_topology_missing`
- `decision_rule=raw_frcsd_shared_degree1_terminal_collapse_confirmed`

### 3.3 `multi_component_unmatched_support`

必须同时满足：

- `association_class=B`
- `association_state=review`
- `required_rcsdnode_count=0`
- support topology component 数量不少于 2
- target 数量不少于 2，且全部投影到同一个 support component
- 至少存在一个未被 target 解释的额外 support component
- `step6_reason=step6_support_only_multi_target_fragmented_surface`
- `pre_business_cleanup_meaningful_component_count>=3`
- `constraint_induced_split=false`
- 原始 FRCSD 局部 junction partition 不能表达 SWSD 臂悬/通行关系
- 无高置信跨层解释

确认后：

- `issue_type=junction_reality_or_precision_gap`
- `decision_rule=raw_frcsd_multi_component_unmatched_support_confirmed`

## 4. T07 正式判定

- `one_target_to_many_base`：一个 target 输出一个 Junction 行。
- `many_target_to_one_base`：每个 target 输出一个 Junction 行，
  所有行共享 `conflict_group_id`。
- 两者：
  - `issue_type=junction_relation_cardinality_mismatch`
  - `decision_source=t07_stable_failure_direct`
- `duplicate_target_rows` 只进入 ignored 计数和审计，不生成 candidate。

## 5. 输出与兼容

保留全部既有 Segment 文件和语义，新增：

- `t12_frcsd_junction_quality_candidates.csv/.gpkg`
- `t12_frcsd_confirmed_junction_quality_issues.csv/.gpkg`
- `t12_frcsd_junction_quality_exclusions.csv`
- `t12_frcsd_junction_carrier_evidence.gpkg`

Junction candidates/confirmed/exclusions 互斥且计数守恒。GPKG 主层只写
Point；support Road、FRCSD endpoint、target projection、T07 conflict
关系进入 evidence layers。

## 6. 范围

### In Scope

- T12 代码、测试、模块源事实与必要的项目级源事实；
- T10 T12 handoff、契约、工作流测试；
- T07 两处已授权的过期架构文字修正；
- 入口登记、代码体量台账、QGIS 工程和 T12-only 内网脚本。

### Out of Scope

- 修改 T03/T07 锚定与匹配算法；
- 修改 T05/T06/T09/T11 行为；
- 修改原始 SWSD/FRCSD；
- 自动修复、人工概率分类、CaseID 白名单；
- 本轮 Git commit、push 或 merge。

## 7. 验收标准

1. `520394575`、`622700016`、`522008569`、`522806716`
   全部进入 confirmed Junction。
2. 指定 16 个负样本均不得进入 confirmed。
3. T07 1:N/N:1 稳定错误直接进入 confirmed；N:1 逐 Junction 输出。
4. 旧 `1026960` Segment candidate/confirmed/excluded/manual 为
   `63/10/53/0`，10 个 candidate ID/type 不变。
5. Junction 与 Segment 输出分层，Junction 为 Point、Segment 为 LineString。
6. CRS、拓扑、几何语义、审计追溯、性能和 `silent_fix=false`
   均有机器可核验记录。
