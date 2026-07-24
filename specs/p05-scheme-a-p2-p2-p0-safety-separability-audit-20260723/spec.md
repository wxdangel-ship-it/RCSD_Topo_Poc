# P05-Scheme-A-P2-P2-P0：高置信错误与安全可分性审计

## 1. 状态与授权

- 状态：已完成
- 授权日期：2026-07-23
- 唯一实施工作树：`E:\Work\RCSD_Topo_Poc__wt_p05_neural_road_20260721`
- 数据范围：仅复用 P2-P1 已冻结的 `E:\TestData\POC_Data` 51 Case 证据
- 输入证据：P2-P1 dataset `20260723_01`、OOF Run A/B `20260723_01/_02`
- Movement：继续忽略，candidate/decision/evaluation 均为零
- Git：不提交、不推送

本阶段承接 `P05_SCHEME_A_P2_P1_SAFETY_NO_GO`，但不直接训练新模型。目标是先分清模型原始选择、阈值接受、fallback 后有效 carrier 和最终发布 RoadGraph 四层事实，确定 `17/9/17` 个错误接受究竟来自 Segment 根选择、Node 独立评分、条件化传播还是统计口径，并判断现有 truth-free 证据是否足以支持下一阶段安全判定模型。

## 2. 阶段目标

1. 对三个 seed 的全部错误接受逐对象追踪到 Segment、Node、Junction 和最终有效 carrier。
2. 对稳定的 `KEEP_SWSD -> USE_RCSD` 错误、唯一 `MIXED_CARRIER` 和 40 个 `REVIEW_FALLBACK` 单独审计。
3. 冻结不含 truth 的安全信号层，再以 label-only 层评价 score margin、entropy、anomaly、multi-seed agreement 和现有 feature signature 的可分性。
4. 判断下一步是“只需重新校准”、需要独立 safety/abstention head，还是必须补充新的 truth-free 业务证据。

## 3. 边界

- 不修改 P2-P1 checkpoint、score、selection、threshold 或 RoadGraph。
- 不新增候选，不修改 T01 Segment/Junction 骨架，不修改 T01-T12 正式实现。
- 不训练新的 neural scorer、安全模型或异常模型。
- 不把 truth、Case/object/candidate ID、绝对坐标或 P2-P1 Oracle 作为安全信号。
- 不用 T06 业务规则修正模型输出，不事后修图，不调整既有正式指标后重报 P2-P1 GO。
- 只新增 P05 内部审计 callable、测试、SpecKit 和不可变输出；不新增 CLI、脚本、`__main__.py`、Makefile target 或 T10 stage。

## 4. 数据分层

### 4.1 Truth-free 安全信号层

- P2-P1 Segment candidate feature set 的规范化 signature。
- 每 seed 的候选概率、top-1 probability、top-1/top-2 margin、entropy 和 anomaly probability。
- multi-seed target agreement、最小 probability/margin、最大 entropy/anomaly。
- selection 的 accepted/fallback、joint constraint 和最终 effective carrier 状态。

该层不得写入 carrier truth、truth candidate ID、正确性或 label-only 归因。

### 4.2 Label-only 审计层

- Segment/Node truth candidate 和 carrier target。
- 原始选择、接受选择、fallback 后 effective carrier 与 truth 的差异。
- Segment candidate 到 Node target 的 compatibility edge，用于追踪错误传播，不作为推理特征。
- `REVIEW_FALLBACK`、expected failure 和 RealityChangeClue 只用于审计分母与归因。

## 5. 五类职责视角

### 产品

- 准确性和安全性优先；本阶段不以提高自动化率为目标。
- 必须说明最终真正错误发布的根 carrier，而不是只重复对象级错误总数。

### 架构

- 区分 raw score、model selection、accepted selection、effective carrier 和 published RoadGraph。
- Node 错误必须区分独立 Node 评分错误与错误 Segment carrier 的条件化传播。

### 研发

- 审计器只读正式 artifact，并输出新的不可变 manifest、summary 和逐对象证据。
- 不改变既有 P2-P1 执行器、模型或接口合同。

### 测试

- 覆盖 manifest/hash、A/B 确定性、分母、错误分类、feature signature、score separability 和 truth-free/label-only 隔离。
- 破坏测试必须检出缺失 seed、缺失 group、truth 混入信号层和错误 compatibility lineage。

### QA

- 8,863 Segment、28,240 Node、3 seeds、40 Review 和全部 `17/9/17` 错误接受不得隐藏。
- 每条错误链必须可定位 Case、对象、候选、seed、fallback、effective carrier 和来源 artifact。

## 6. 验收门禁

### Gate 0：证据与确定性

- dataset、OOF A/B manifest/hash 全部可验证。
- A/B 的 score、selection、effective selection 内容一致。
- 51 Case、3 seeds、8,863 Segment、28,240 Node、40 Review 分母精确。

### Gate 1：错误链完整性

- P2-P1 `17/9/17` 个 accepted wrong 全部逐对象分类，未归因数为零。
- 每 seed 的 raw Segment 错误、accepted Segment 根错误和其影响 Node 数单列。
- 稳定 `KEEP_SWSD -> USE_RCSD` 集合、`MIXED_CARRIER` 和 40 Review 全部列出。
- expected failure 与未发布对象不得冒充正式自动发布错误。

### Gate 2：安全语义口径

- accepted model choice 与 materialized effective carrier 分开统计。
- 每个 Node 条件化错误可回指 raw/effective Segment candidate compatibility edge，或明确标记为独立/未引用 Node。
- fallback 后的有效 carrier 不得继续按 fallback 前 truth 机械计为业务错误；同时不得掩盖仍被接受并发布的错误 Segment 根 carrier。

### Gate 3：现有信号可分性

- safety signal artifact 的 truth/ID/绝对坐标泄漏计数为零。
- 计算 multi-seed 一致 USE 集合上，单一 score/anomaly 信号在零错误条件下可保留的 `USE_RCSD` 最大覆盖率；目标为 `>=0.50`。
- 计算完整现有 feature signature 的跨 truth 精确碰撞；碰撞数必须单列，零碰撞只表示“未证明不可分”，不等价于泛化成功。
- 40 Review 在三个 seed 的预测、接受与 fallback 状态完整保留。

## 7. 决策口径

- 单一 score/anomaly 零错误覆盖率 `>=0.50`，且错误链无证据缺口：`P05_SCHEME_A_P2_P2_P0_CALIBRATION_EVIDENCE_GO`。
- 单一校准未达 `0.50`，但现有完整 feature signature 无跨 truth 精确碰撞、错误根均有 truth-free 特征：`P05_SCHEME_A_P2_P2_P0_CALIBRATION_NO_GO_SAFETY_HEAD_GO`。
- 存在无法归因的已发布 Segment 根错误、truth-free feature 精确碰撞或 lineage 缺口：`P05_SCHEME_A_P2_P2_P0_EVIDENCE_NO_GO`。

任一结论都不自动授权 P2-P2-P1 训练、P2-P1 指标改写、在线 proposal 或生产接入。
