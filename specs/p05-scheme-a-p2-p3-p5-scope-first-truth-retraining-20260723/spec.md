# P05-Scheme-A-P2-P3-P5：Scope-First Truth Retraining & OOF Revalidation

## 1. 状态与授权

- 状态：已完成
- 授权日期：2026-07-23
- 唯一实施工作树：`E:\Work\RCSD_Topo_Poc__wt_p05_neural_road_20260721`
- 数据范围：既有 P05 冻结工件与 `E:\TestData\POC_Data`
- 训练：允许重新训练现有 P2-P3 分层模型
- Git：不提交、不推送
- T01–T12：不修改实现或接口
- Movement：忽略

本阶段承接
`P05_SCHEME_A_P2_P3_P4_TRUTH_REBASELINE_GO_NO_RESIDUAL_REPRESENTATION_REQUIRED`。
P4 已证明唯一残余 false-use 来自真值闭包顺序缺陷。本阶段不得引入新推理表征或
更换网络，必须只用 scope-first 修正真值重训同一模型，以区分“旧真值问题”和
“当前模型/证据能力问题”。

## 2. 阶段目标

在保持 2.818M 级分层网络、202 维 T01/T07 推理证据、3 seeds × 5 Case folds、
候选集合和通用图安全层不变的条件下：

1. 用 P4 修正后的 Segment/Node 真值构建唯一训练 dataset；
2. 从头训练 carrier/candidate-correctness/RealityChangeClue/auxiliary heads；
3. 在 scorer 后应用冻结的 `ADVANCE_RIGHT access_valid=false` 硬安全门；
4. 使用修正 Node/Junction 真值闭包生成全部 Case 的有效 RoadGraph；
5. 判定现有基础模型能否同时满足零错误、最低覆盖、clue 和整图安全门。

## 3. 冻结业务与数据语义

1. T01 Segment/Junction 骨架冻结，模型不得新增、删除、拆分、合并或重归属。
2. Dataset-P1 与 P4 共同构成本阶段唯一标签合同：
   - 6,275 个 `label_eligible=true` Segment进入监督、阈值和指标；
   - 2,588 个 context-only Segment只作输入上下文，不进入监督、阈值或指标；
   - context-only 的整图安全实现为确定性 `KEEP_SWSD`。
3. 修正后的 eligible target 分布固定为：
   `KEEP_SWSD=4,486 / USE_RCSD=1,749 / REVIEW_FALLBACK=40`。
4. eligible anomaly 数固定为 1,488；已登记 clue-only 分母固定为 5。
5. 修正 Node label 数固定为 28,240；P4 初始冲突/闭包 Segment 为 10/21。
6. `T10:609214532` 与 `T10:74155468` 继续保持局部 `EXPECTED_FAIL`。
7. 40 个 `ADVANCE_RIGHT access_valid=false` 继续作为 scorer 后、通用闭包前的
   推理期硬安全资格。
8. T03/T04/T05 仅作 auxiliary label；T06、truth、ID、绝对坐标和 Movement
   不得成为推理特征。

## 4. 五类职责视角

### 产品

- 准确性和安全性优先；任何错误自动接受都不能被平均指标抵消。
- fallback 允许降低自动化率，但不得伪装为正确自动发布。
- GO 仅表示当前 POC OOF 门通过，不等于生产上线。

### 架构

- 候选、特征、payload、compatibility edge 按 hash 复用，标签层单独重建。
- 网络结构、参数量、seed、fold、损失和阈值选择方法保持与 P2-P3-P2 可比。
- `ADVANCE_RIGHT` 硬门独立于 learned scorer，不编码新的业务选择规则。
- Node/Junction closure 与 RoadGraph materializer 只使用修正真值合同。

### 研发

- 只新增 P05 内部 dataset builder、OOF callable、schema、测试和 SpecKit。
- 不新增 CLI、root script、T10 stage、`__main__.py` 或 Makefile target。
- 不修改 T01–T12、geometry、CRS 或历史实验工件。

### 测试

- 覆盖旧候选层与新标签层精确 join、context 隔离和唯一 truth candidate。
- 覆盖修正 Segment/Node label、clue/anomaly 分母和身份破坏 hard fail。
- 覆盖 hard gate、三 seed 决策、context fallback、局部 expected-failure 和整图。
- 覆盖正式 Dataset A/B、OOF Run A/B 与完整 P05 回归。

### QA

- 冻结全部 manifest/hash、Case fold、seed、参数、训练与输出 lineage。
- 正式双跑的模型、score、decision、effective、RoadGraph 和指标签名一致。
- geometry、Movement、T06 inference、repair、silent fix、骨架 mutation 均为 0。

## 5. 验收门禁

### Gate 0：训练数据

- `8,863 = 6,275 eligible + 2,588 context-only`；
- eligible target=`4,486/1,749/40`，anomaly=1,488，clue-only=5；
- 28,240 个修正 Node label 均有唯一候选；
- context 的 label/loss/threshold/calibration/metric 贡献均为 0；
- truth-free feature/payload/compatibility edge hash 与历史 P2-P1 完全一致；
- Dataset A/B 规范化 signature 一致。

### Gate 1：模型与防泄漏

- 网络 schema 仍为 `p05-scheme-a-p2-p3-p0-network-v1`；
- 参数量为 `1,000,000–3,000,000`，硬上限 5,000,000；
- 3 seeds × 5 Case folds 从头训练，旧 state/threshold 复用为 0；
- truth、identifier、绝对坐标、Movement、T03/T04/T05/T06 inference feature
  均为 0。

### Gate 2：Carrier 安全与覆盖

每个 seed 的整体和每个 held-out fold 必须同时满足：

- `carrier_wrong_accepted_count=0`
- `review_auto_publish_count=0`
- `carrier_safety_recall=1.0`
- `safe_coverage>=0.50`
- `USE_RCSD safe_coverage>=0.50`

### Gate 3：RealityChangeClue

每个 seed 的整体和每个 held-out fold 必须同时满足：

- clue recall=`1.0`
- clue precision `>=0.80`
- clue macro-F1 `>=0.85`
- 5 个 eligible clue-only 对象全部捕获

### Gate 4：整图安全

- 每 seed 全部 8,863 Segment均有确定 effective selection；
- context-only 自动接受和非 `KEEP_SWSD` effective 均为 0；
- 49 Case为 `LEGAL`，2 Case为 `EXPECTED_FAIL`，新增 `FAIL` 为 0；
- requirement conflict、Node mismatch、非目标 Case 级联、repair、silent fix、
  骨架 mutation 均为 0。

### Gate 5：确定性、GIS 与资源

- 正式 Run A/B 的规范化 signature 一致，Run B reference match=true；
- CPU RAM `<=8GiB`，GPU VRAM=`0`；
- 单次完整阶段 wall `<=30min`；
- Case inference p95 `<=5s`、max `<=20s`；
- CRS=`EPSG:3857`，geometry read/write=0，coordinate transform=0。

## 6. 阶段决策

- 全部门禁通过：`P05_SCHEME_A_P2_P3_P5_MODEL_GO`
- 审计、数据、确定性、资源或整图安全失败：
  `P05_SCHEME_A_P2_P3_P5_AUDIT_NO_GO`
- 审计通过但任一 carrier/clue 业务门失败：
  `P05_SCHEME_A_P2_P3_P5_MODEL_NO_GO`

GO 不自动授权生产接入；NO-GO 后必须先对修正真值下的新错误逐对象归因，不能在
当前 held-out Case 上继续调阈值、挑 seed 或恢复旧真值。

## 7. 完成结论

本阶段正式判定
**`P05_SCHEME_A_P2_P3_P5_MODEL_NO_GO`**。训练数据、输入审计、整图安全、资源和
双跑确定性门全部通过；carrier 与 RealityChangeClue 模型门未全部通过。

- Dataset A/B signature：
  `5efbe66318f818dd705dbd10acd48366e328d2f8e61bae51812a46d5cf61fb46`
- OOF Run A/B signature：
  `de6c92d0bde80f2d0690af76a340931d802cdf5def7bc63601406040720dce02`
- 三 seed 的错误自动接受与 Review 自动发布均为 0，carrier safety recall 均为
  1.0；
- safe coverage 为 `0.4290/0.5498/0.1374`，`USE_RCSD` safe coverage 为
  `0.6918/0.7044/0.2310`；
- clue recall/precision/macro-F1 为
  `0.9805/0.6614/0.8512`、`0.8831/0.9985/0.9596`、
  `0.9960/0.3605/0.5751`，clue-only 捕获为 `5/5、4/5、5/5`；
- 每 seed 均为 49 `LEGAL` + 2 `EXPECTED_FAIL`，新增冲突、错配、修复或骨架
  mutation 为 0。

该结论证明 scope-first 修正真值已消除旧残余 false-use 和整图 carrier 冲突，
但同一 202 维证据与 2.818M 级模型仍不能跨 seed/fold 同时达到自动化覆盖和异常
线索门槛。不得通过挑选 seed 或在当前 held-out Case 上调阈值改写结论。
