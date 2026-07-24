# P05-Scheme-A-P2-P1：整图一致 Object-Conditioned Carrier Scorer

## 1. 状态与授权

- 状态：已授权，实施中
- 授权日期：2026-07-23
- 唯一实施工作树：`E:\Work\RCSD_Topo_Poc__wt_p05_neural_road_20260721`
- 数据范围：仅 `E:\TestData\POC_Data`
- 显式排除：`T10-Error / 1213556_1263661`
- T07：固定 `DRIVEZONE_ONLY`
- Movement：本阶段不生成候选、不选择、不训练、不评价
- Git：不提交、不推送

本阶段承接已完成的 `P05_SCHEME_A_DATASET_P0_GO`。Dataset-P0 已证明现有 Case、T06 最终 Road/Node 标签和 truth-free proposal 对象均完整可达；历史 P2-P0 的 `0.165753` 只保留为受限 carrier bundle 的安全保留率。本阶段不得继续使用该旧分母阻止训练，也不得把独立对象可达性直接冒充模型或整图兼容性成功。

## 2. 阶段目标

在冻结 T01 Segment/Junction 业务骨架、正确候选已经存在的前提下：

1. 由神经网络同时对 Segment 独立 Road carrier 和 JunctionUnit Node carrier 评分；
2. 使用候选—对象—Junction 上下文建立 object-conditioned 选择，不再把共享 Node 隐藏在逐 Segment bundle 中；
3. 在 held-out Case 上通过置信度与异常评分决定自动接受或 fallback；
4. 通用确定性层只验证 candidate domain、共享 Node/mainnode 一致性、ID/引用、方向、CRS、拓扑和最小 fallback 闭包，不编码 T06 业务选择；
5. 将安全自动接受覆盖率从历史 P1 的约 `0.35` 提升到每个 seed 至少 `0.50`，同时保持错误自动替换为零。

## 3. 数据合同

### 3.1 Truth-free candidate 层

- Segment candidate 复用已冻结 P1 candidate 的 Segment Road 选项。
- Node candidate 从已冻结 PTO-P0 `FINAL_NODE` candidate 中提取全部可用 payload、action、source 和 lineage；不得只保留单一 replay 的 `proposal_nodes`。
- T01/SWSD candidate 与非 T01 proposal 必须分开标记。
- candidate manifest/hash 完成前，不得读取 Scheme A carrier label、PTO Oracle cost、T06 truth 或历史选择结果。
- feature 不得包含 Case/business/object/candidate/group ID、绝对坐标、truth、Oracle cost、relation status/reason 或 truth signature。

### 3.2 Label-only 层

- Segment 最终真值只取方案 A `carrier_labels.jsonl`；`segment_inventory.csv` 中同名 `carrier_target` 是策略初始状态，不是 fallback 后有效训练标签。
- Node option候选来源为P1 truth-free T01/proposal Node lineage与PTO全量FINAL_NODE payload的并集；只在candidate manifest冻结后，依据Segment真值Road来源连接为`T01_NODE / PROPOSAL_NODE / OMIT`。PTO Oracle cost/selected candidate只用于证明候选来源与可达性，不直接作Node标签。
- 40 个不可确认 ADVANCE_RIGHT 保持 mask，不得编码为负类或自动发布。
- `Unknown`、运行失败、批准排除和 lineage/hash 异常只能 mask 或使数据 Gate 失败。

### 3.3 泛化边界

- 固定 M0 business-ID grouped 5-fold；同一 Case 和业务对象的所有候选必须处于同一 fold。
- 正式训练为 `3 seeds × 5 folds`。
- outer held-out Case 不得参与 vocabulary、normalization、class weight、inner validation、early stopping、阈值或 calibration。

## 4. 模型与执行

- 模型：`1M~5M` 参数的 Segment/Node 双对象 object-conditioned set scorer。
- 输入：候选 token、对象 token、JunctionUnit/邻接上下文 token、有限归一化相对几何/拓扑数值。
- 输出：candidate score、confidence、uncertainty、anomaly probability、model/context signature。
- Segment 与 Node 使用统一 score contract；训练可共享编码器，并保留对象类型分支。
- 确定性执行器只允许选择冻结 candidate、执行通用共享 Node 兼容性和 hard gate、触发已确认的 Segment/Junction fallback；不得补路、吸附、重连、改写 payload 或回退 Oracle cost。

## 5. 五类职责视角

### 产品

- 准确性和安全性优先于自动化率。
- 自动接受结果必须完全正确；低置信可以 fallback。
- 不得用大量 KEEP_SWSD 自动接受掩盖 `USE_RCSD` 无法替换。

### 架构

- candidate、label、model、score、selection、fallback、RoadGraph 分层 manifest/hash。
- Road carrier ownership 与 JunctionUnit shared Node carrier 分层，最终仍编译为 T06 Step3 Road/Node。
- 模型不改变 T01 业务骨架，Movement 继续冻结。

### 研发

- 只新增 P05 Python callable、测试和本 SpecKit 工件。
- 不新增 CLI、root script、T10 stage、`__main__.py` 或 Makefile target。
- 不修改 T01–T12 正式实现，不覆盖既有 run。

### 测试

- 覆盖 manifest/hash、candidate/truth 隔离、fold/ID/坐标泄漏、Segment/Node truth 唯一性和40个 mask。
- 覆盖缺失 candidate、同 ID 不同 payload、mainnode 不兼容、低置信、异常、Segment/Junction fallback和expected failure。
- 覆盖 outer-fold vocabulary/normalization/threshold 泄漏和同 seed重放。

### QA

- 51 Case、8,863 Segment、8,823 可用 Segment、40 mask和全部 Node group 分母不得隐藏。
- CRS、几何语义、Road/Node 引用、有向拓扑、lineage、资源、checkpoint和确定性可定位。
- 错误预测必须保留，不能通过后处理修图从分母删除。

## 6. 成功标准

### Gate 0：数据与联合可达性

- 51 Case、8,863 Segment、8,823 可用 Segment、40 mask；排除项进入训练数为0。
- Segment `USE_RCSD` 非 T01 truth candidate reachability=`100%`。
- 条件化Node truth option reachability=`100%`；Segment truth + endpoint/JunctionUnit Node truth 的 compatibility Oracle=`100%`。
- Movement candidate/decision/evaluation=0；truth-derived candidate/feature=0；T01 skeleton mutation=0。

### Gate 1：零泄漏与训练合同

- Case/business/object/candidate/group ID、绝对坐标、truth、Oracle、relation status/reason feature hit=0。
- 每个可训练 group 恰有一个 label-only truth candidate；fold group conflict=0。
- 3 seeds × 5 folds 完整；held-out Case 不进入任何训练统计。
- 模型参数 `1M~5M`，全部 checkpoint/model signature可追溯。

### Gate 2：对象评分能力

- 每个 seed Segment carrier macro-F1 `>=0.98`。
- 每个 seed `USE_RCSD` Road recall `>=0.85`。
- 每个 seed JunctionUnit Node carrier exact `>=0.90`。
- 每个 seed ECE `<=0.10`。

### Gate 3：安全自动接受

- 每个 seed 自动接受错误替换数=`0`，accepted precision=`1.0`。
- 每个 seed 总体 safe accepted coverage `>=0.50`。
- 每个 seed `USE_RCSD` safe accepted coverage `>=0.50`。
- hard conflict/fallback recall=`1.0`，anomaly precision `>=0.80`。
- 40 个 unsafe ADVANCE_RIGHT 自动发布数=`0`。

### Gate 4：RoadGraph 安全

- 每个 seed 49 `LEGAL` + 2 精确 `EXPECTED_FAIL`；新增失败=0。
- Road/Node ID、引用、方向、CRS、有向拓扑、Junction mainnode hard failure=0。
- `skeleton_mutation_count=0`、`relaxation=false`、`content_repair=false`、`silent_fix=false`。

### Gate 5：确定性与资源

- 同 seed双跑的 model、score、selection、fallback和RoadGraph内容 signature一致。
- RAM `<=16GB`、VRAM `<=8GB`；3 seeds总训练 wall `<=6h`。
- 冻结 candidate 上单 Case scoring P95 `<=5s`、max `<=20s`。
- 历史 strategy replay/在线 proposal 成本单列，不得计入 scorer 成功；在线性能继续 NO-GO。

## 7. 完成定义

SpecKit、P05 source-of-truth、candidate/dataset/model/OOF callable、单元与破坏测试、正式51 Case 3 seeds × 5 folds、同 seed重放、RoadGraph/GIS/资源/体量/入口审计和 `validation-summary.md` 全部完成后才可关闭。

- 全部门禁通过：`P05_SCHEME_A_P2_P1_OFFLINE_SCORER_GO`
- 数据/兼容性 Gate失败：`P05_SCHEME_A_P2_P1_DATA_NO_GO`
- 模型或覆盖门失败：`P05_SCHEME_A_P2_P1_MODEL_NO_GO`
- RoadGraph安全门失败：`P05_SCHEME_A_P2_P1_SAFETY_NO_GO`

任何结论都不自动授权在线 proposal、生产接入或 T01–T12 修改。
