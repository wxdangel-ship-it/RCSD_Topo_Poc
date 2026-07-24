# P05-Scheme-A-P2-P2-P1：Segment Safety / Abstention Head

## 1. 状态与授权

- 状态：已完成，正式 `MODEL_NO_GO`
- 授权日期：2026-07-23
- 唯一实施工作树：`E:\Work\RCSD_Topo_Poc__wt_p05_neural_road_20260721`
- 数据范围：仅复用 `E:\TestData\POC_Data` 已冻结的 51 Case 与 P2-P1 OOF 证据
- 前置结论：`P05_SCHEME_A_P2_P2_P0_CALIBRATION_NO_GO_SAFETY_HEAD_GO`
- Movement：继续忽略，candidate/decision/evaluation 均为零
- Git：不提交、不推送

本阶段冻结 P2-P1 candidate、base scorer、OOF score 和 T01 Segment/Junction 业务骨架。新增的神经网络只判断 P2-P1 提议的 Segment carrier 是否足够安全自动发布；它只有接受或否决权，不得改选候选。否决后执行 Segment fallback 到 `KEEP_SWSD`，随后再做 Road endpoint/JunctionUnit 条件化 Node carrier 闭包和 RoadGraph 硬门禁。

## 2. 阶段目标

1. 建立不含 truth、标识符和绝对坐标的 Segment 安全样本；输入包括冻结 candidate/context feature 和三个 P2-P1 OOF seed 的 score 统计。
2. 以 Case 为最小隔离单元，完成外层 5-fold OOF 与训练折内层校准； held-out Case 不得参与模型、阈值或早停选择。
3. 训练一个小型 object-conditioned candidate-set safety head；它预测候选/目标可信度及异常风险，但推理结果只用于接受或回退。
4. 在安全决定后重算 Segment 到 Node 的通用兼容闭包，物化 51 Case RoadGraph，并验证冻结骨架、fallback 和 RealityChangeClue 语义。
5. 给出 `GO / MODEL_NO_GO / ROADGRAPH_NO_GO / EVIDENCE_NO_GO` 的正式离线结论。

## 3. 模型和数据边界

### 3.1 冻结输入

- P2-P1 dataset manifest、Segment candidate features/payloads、compatibility edges。
- P2-P1 OOF Run A/B；A/B 内容必须一致，三个 base seed 对每个 Segment group 必须完整。
- P2-P2-P0 safety signal 仅作为输入整理依据；label-only 归因不得进入推理特征。

### 3.2 Safety Head

- 输入：候选/对象/上下文离散 token、规范化 numeric feature、三个 base seed 的候选概率和排序统计、seed 间选择一致性。
- 输出：候选安全分数、group 异常/Review 风险和提议候选是否可接受。
- 参数范围：`0.10M <= parameters <= 2.00M`。
- safety head 不产生新的 candidate，不改变 candidate target，不把自身 top-1 当作新 carrier；只有当其判断与冻结提议一致且通过训练折内阈值时才接受。
- 训练 label 可使用 carrier truth、anomaly/Review；阈值和早停只使用当前外层训练 Case 的内层划分。

### 3.3 禁止特征

- `case_key`、`group_id`、`object_id`、`candidate_id` 及其 hash/派生记忆特征。
- truth candidate/target、correctness、label weight、mask reason、人工验收状态。
- 绝对坐标、Case 文件路径或仅在 held-out Case 可见的统计量。
- compatibility truth 或根据最终正确标签构造的 Node requirement。

## 4. 安全执行语义

1. 冻结 P2-P1 base scorer 给出提议 candidate；seed 不一致、Review、hard unsafe 或 safety head 拒绝均回退该 Segment。
2. Safety head 不允许把 `KEEP_SWSD` 改成 `USE_RCSD/MIXED_CARRIER`，也不允许把一个 proposal 换成另一个 proposal。
3. Segment fallback 只影响该 Segment；仅当共享 Node carrier 冲突影响 Junction 内部拓扑时，才升级为 Junction fallback。
4. Node carrier 按有效 Road endpoint/JunctionUnit requirement 在 `T01_NODE / PROPOSAL_NODE / OMIT` 冻结候选中选择；PTO 只是候选来源，不是标签。
5. 无合法独立 Road、现实证据冲突或 expected SWSD failure 必须保留 SWSD/失败状态并报线索；禁止 silent fix、事后修图或骨架变更。

## 5. 五类职责视角

### 产品

- 准确性和安全性优先，允许自动化率下降；任何错误替换均不能用更高覆盖率抵消。
- 对用户报告“自动发布、业务回退、预期失败”三个结果，不把 fallback 机械计为失败。

### 架构

- carrier scorer 与 safety head 职责分离；Node 条件化闭包位于 Segment safety 决定之后。
- T01 Segment/Junction/PhysicalMovement 骨架冻结，Movement 本阶段不建模。

### 研发

- 只新增 P05 内部 callable、测试、SpecKit 和不可变输出。
- 不新增 CLI、`scripts/`、`__main__.py`、Makefile target、T10 stage 或 T01-T12 正式实现。

### 测试

- 覆盖 manifest/hash、Case 隔离、禁止特征、candidate 分母、阈值仅来自训练 Case、拒绝只回退不改选、Node 闭包与重复运行确定性。
- 破坏测试必须检出 seed/group 缺失、truth/ID 泄漏、fold 重叠、candidate 改选和非法 skeleton mutation。

### QA

- 51 Case、8,863 Segment、3 base seed、5 outer fold、40 Review 和 2 expected failure 分母不得隐藏。
- 每个被接受或回退的 Segment 必须可追溯到 base proposal、safety score、阈值、effective carrier 和 RoadGraph terminal state。

## 6. 验收门禁

### Gate 0：证据与泄漏

- P2-P1 dataset、OOF A/B、P2-P2-P0 manifest/hash 全部可验证，A/B 内容一致。
- 51 Case、8,863 Segment、3 base seed、5 fold、40 Review 精确。
- 推理特征中的 truth、ID、绝对坐标泄漏计数均为零；外层 train/held-out Case 交集为零。

### Gate 1：Safety Head

- 所有 safety seed 的 accepted Segment root error=`0`，accepted precision=`1.0`。
- 总体 Segment safe coverage `>=0.50`，truth `USE_RCSD` safe coverage `>=0.50`。
- 40 Review auto-publish=`0`；P2-P2-P0 的 8 个稳定 false-use auto-publish=`0`。
- unsafe（错误提议或 Review）fallback recall=`1.0`；覆盖率门禁负责限制无差别全回退。
- 参数量、训练/阈值 lineage 和每折 checkpoint 完整。

### Gate 2：Node 闭包与 RoadGraph

- 49 个可发布 Case 全部 `LEGAL + publish=true`；2 个 expected failure 必须精确保持 `EXPECTED_FAIL + publish=false`。
- effective Segment→Node requirement conflict=`0`、target mismatch=`0`；unexpected RoadGraph failure=`0`。
- skeleton mutation=`0`、content repair=`false`、silent fix=`false`、Movement decision=`0`。

### Gate 3：确定性与资源

- 同输入正式 Run A/B 的 selection、effective selection、RoadGraph index、summary 内容 signature 一致。
- 单模型参数量 `0.10M~2.00M`；CPU RAM 峰值目标 `<=16GB`、GPU VRAM 峰值目标 `<=8GB`。
- 15 个 outer-fold 模型总训练时间 `<=6h`；51 Case 单 seed 评分 `<=20s`，CPU 目标 `<=5s`。

## 7. 决策口径

- Gate 0~3 全通过：`P05_SCHEME_A_P2_P2_P1_SAFETY_HEAD_GO`。
- Gate 0 通过，但 Safety Head 的零错误或覆盖门禁失败：`P05_SCHEME_A_P2_P2_P1_MODEL_NO_GO`。
- Safety Head 通过但 Node/RoadGraph 门禁失败：`P05_SCHEME_A_P2_P2_P1_ROADGRAPH_NO_GO`。
- 输入 lineage、fold 隔离、泄漏或分母不成立：`P05_SCHEME_A_P2_P2_P1_EVIDENCE_NO_GO`。

GO 只表示离线 POC 安全头通过，不自动授权在线 proposal、生产接入、T01-T12 改造或 Git 提交/推送。

## 8. 完成结论

正式 Run A/B `p05_scheme_a_p2_p2_p1_oof_20260723_03/_04` 判定均为 **`P05_SCHEME_A_P2_P2_P1_MODEL_NO_GO`**。三个 safety seed 的错误接受/总体覆盖/`USE_RCSD` 覆盖分别为 `5/0.374817/0.431714`、`0/0.069841/0.066911`、`4/0.296288/0.380843`：零错误 seed 只能保留约 7%，较高覆盖 seed 又接受 4~5 个错误，因此 Gate 1 失败。Node 条件化闭包与 RoadGraph Gate 2 全部通过，每 seed 均为 49 `LEGAL` + 2 `EXPECTED_FAIL`，effective requirement conflict/mismatch、payload conflict、unexpected failure 均为零。

本结论否定的是当前 410,786 参数、Case-grouped/cross-fitted candidate-set safety head 的离线自动发布能力，不否定神经网络的逐对象排序价值，也不表示本地 Case 或正确 candidate 不足。不得在已见 held-out Case 上继续调阈值、增加 epoch 后重报 GO。
