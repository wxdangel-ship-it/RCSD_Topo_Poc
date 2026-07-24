# P05-Scheme-A-Dataset-P0：模块语义化训练集与候选可达性验收

## 1. 状态与授权

- 状态：已完成，`P05_SCHEME_A_DATASET_P0_GO`
- 授权日期：2026-07-22
- 唯一实施工作树：`E:\Work\RCSD_Topo_Poc__wt_p05_neural_road_20260721`
- 数据范围：仅 `E:\TestData\POC_Data`
- 显式排除：`T10-Error / 1213556_1263661`
- T07 口径：`DriveZone-only`
- Movement：本阶段不生成候选、不选择、不训练、不评价
- Git 边界：不提交、不推送

本阶段承接已完成的方案 A baseline、M0/M2R supervision、PTO-P0 与 Scheme-A-P2-P0。旧 `P05_SCHEME_A_P2_P0_UPSTREAM_CARRIER_NO_GO` 保留为历史实验结论；本阶段不改写历史证据，而是按 T01/T07/T03/T04/T05/T06/T09/T11/T10 的正式业务职责，重新建立训练数据角色和候选来源审计。

## 2. 阶段目标

在不新增 Case、不修改 T01-T12 正式实现的前提下：

1. 将每个训练样本和 artifact 明确归类为输入、label-only 中间监督、最终主标签、审计、mask 或下游验证；
2. 固化 T01 为 SWSD Segment 冻结骨架，禁止将 T01 解释为 RCSD 真值来源；
3. 固化 T07 Step1 为 `DriveZone-only`，T07 保留为确定性已有路口证据，不作为本阶段神经 Head；
4. 将 T03/T04/T05 作为 label-only 中间监督，将 T06 Step3 F-RCSD Road/Node 与 Segment relation 作为最终主标签；
5. 复用已登记、零 truth 的 PTO strategy proposal，独立证明 `USE_RCSD` Segment 的正确 Road carrier 是否由非 T01 候选覆盖；
6. 输出模块级数据可用性、task mask、候选来源、Road/Node 可达性、异常归因和是否允许启动下一阶段 scorer 的结论。

## 3. 模块训练角色

| 模块 | 当前业务职责 | Dataset-P0 角色 |
|---|---|---|
| T01 | 构建 SWSD Segment 与 `pair_nodes/junc_nodes/roads/sgrade` | `INPUT_FROZEN_SKELETON`；SWSD Road 只可作为 fallback candidate |
| T07 | existing surface 锚定 | `DETERMINISTIC_INPUT_EVIDENCE`；Step1 固定 `DriveZone-only` |
| T03 | 常规路口 accepted surface 与 relation evidence | `LABEL_ONLY_INTERMEDIATE` |
| T04 | 复杂路口面、Reference Point 与 relation evidence | `LABEL_ONLY_INTERMEDIATE` |
| T05 | 唯一 SWSD-RCSD relation 与 RCSD junctionization | `LABEL_ONLY_INTERMEDIATE` |
| T06 | Segment carrier 选择、替换、fallback 与 F-RCSD 发布 | `LABEL_ONLY_PRIMARY_TARGET` |
| T09 | TrafficRule 恢复 | `DOWNSTREAM_VALIDATION_ONLY` |
| T11 | relation 修复候选与人工审计 | `HUMAN_CORRECTION_SOURCE`；只有经 T05/T06 重跑后才可成为标签 |
| T10 | 编排、Case/Segment evidence 与 lineage | `DATASET_MANIFEST_AND_SPLIT` |

## 4. 输入隔离

### 4.1 推理输入与 candidate 层

- 只允许读取 raw/T01/T07 确定性证据，以及已登记 commit、run root、artifact hash 完整的 truth-free proposal。
- PTO candidate manifest 必须满足 `truth_input_count=0`、`truth_derived_candidate_count=0`。
- T01 SWSD Road candidate 与非 T01 RCSD/proposal candidate 必须分开统计。
- candidate manifest 冻结后，才允许读取 M2R/T06 label-only truth。

### 4.2 Label-only 层

- T03/T04/T05/T06 目标 artifact、T06 reason/status、人工标签和 Oracle cost 不得进入模型输入或 candidate feature。
- `Unknown`、运行失败、血缘不完整和批准排除只能 mask，不得编码成 negative/rejected。
- T11 machine candidate 不是真值；人工正向结果只有经 T05/T06 正式重跑并具备完整 lineage 时才可使用。

## 5. 职责视角

### 产品

- 先证明现有 Case 足以形成正确训练合同，不以新增 Case 掩盖角色错误。
- 准确性、安全性和可解释性优先；候选缺失只能 mask/fallback，不允许错误替换。
- 输出 `GO / CANDIDATE_NO_GO / LABEL_NO_GO / SAFETY_NO_GO`。

### 架构

- 模块角色、candidate、label、Oracle 与评价层使用独立 manifest/hash。
- T01 fallback coverage 与 `USE_RCSD` coverage 分开报告。
- T03/T04 surface、T05 relation、T06 final RoadGraph 分层，不以任一中间状态代替最终真值。

### 研发

- 只新增 P05 Python callable、测试和本 SpecKit 工件。
- 不新增 CLI、root script、T10 stage、`__main__.py` 或 Makefile target。
- 不修改 T01-T12 正式实现，不覆盖既有 run。

### 测试

- 覆盖模块角色、权重、task mask、批准排除、T07 口径、truth-free manifest、候选来源分类和 Road/Node 可达性。
- 覆盖将 T01 误标为 RCSD、Unknown 误标为 negative、T11 candidate 误标为 truth、hash 漂移和候选缺失等破坏场景。

### QA

- 51 个 RoadGraph Case、741 个 M0 sample、8,863 个 Segment 和全部启用 label 分母不得隐藏。
- CRS、文件 hash、几何来源、Road/Node 引用、有向拓扑、运行环境、资源和确定性全部可定位。

## 6. 成功标准

### Gate 0：范围、角色与零泄漏

- M0 sample=`741`；RoadGraph Case=`51`；Segment=`8,863`；排除项进入启用任务数=`0`。
- 100% sample/artifact 具有模块、训练角色、权重、task mask 和 lineage。
- T01 被标记为 RCSD label 的记录数=`0`；T01 skeleton mutation=`0`。
- T07 evidence mode=`DRIVEZONE_ONLY`；Movement candidate/decision/evaluation=`0`。
- `truth_input_count=0`、`truth_derived_candidate_count=0`。

### Gate 1：标签完整性

- T03/T04/T05/T06 启用标签的 hash/路径可追溯率=`100%`。
- 权重只允许 `1.0/0.3`、`0.7/0.7`、`0.7/0.3` 三种已确认组合。
- M2R label integrity error=`0`、split group conflict=`0`。
- `Unknown/runtime_failed/approved_exclusion` 的启用 label 数=`0`。

### Gate 2：候选可达性

- `USE_RCSD truth reachability >= 0.95`，且只统计非 T01 candidate。
- 全部可用 Segment Road candidate reachability=`100%`。
- T06 final Road object reachability=`100%`；T06 final Node object reachability=`100%`。
- Segment Road 与 Case final Node 的联合 exact coverage `>=0.90`。
- 所有不可达对象必须具有模块级归因和 mask/fallback，不得静默计负样本。

### Gate 3：Oracle 与 RoadGraph 安全

- 冻结 PTO Oracle 证明 51/51 Case semantic exact、Road/Node/属性/有向拓扑精确，hard failure=`0`。
- Scheme A 安全终态保持 49 `LEGAL` + 2 精确 `EXPECTED_FAIL`；新增失败=`0`。
- `content_repair=false`、`silent_fix=false`、`relaxation=false`。

### Gate 4：确定性、GIS 与资源

- 独立 Run A/B 的 module contract、sample、artifact、task、candidate source、reachability 和 summary signature 一致。
- CRS 缺失/冲突、重复 ID、无效引用、不可解释 candidate source 均为 `0`。
- GPU 不需要；峰值 RSS `<=16GB`；单次 Dataset-P0 审计 wall time `<=2h`。

## 7. 完成定义

SpecKit、P05 source-of-truth、Python callable、单元/破坏测试、两次独立 51 Case 审计、确定性/资源/GIS检查和 `validation_summary.md` 全部完成后才可关闭本阶段。

- 全部门禁通过：`P05_SCHEME_A_DATASET_P0_GO`
- 标签合同失败：`P05_SCHEME_A_DATASET_P0_LABEL_NO_GO`
- candidate coverage失败：`P05_SCHEME_A_DATASET_P0_CANDIDATE_NO_GO`
- RoadGraph安全失败：`P05_SCHEME_A_DATASET_P0_SAFETY_NO_GO`

任何结论都不自动授权 scorer 训练、生产接入或 T01-T12 修改。

## 8. 完成结论

正式 Run A/B `p05_scheme_a_dataset_p0_20260722_04/_05` 的 Gate 0~4 全部通过，七类内容 signature 完全一致。`USE_RCSD` 非 T01 candidate reachability=`2190/2190`，可用 Segment Road=`8823/8823`，T06 final Road=`23224/23224`、final Node=`27553/27553`，联合 exact=`1.0`；RoadGraph 保持49 `LEGAL` + 2 `EXPECTED_FAIL`。本阶段因此关闭为 `P05_SCHEME_A_DATASET_P0_GO`。
