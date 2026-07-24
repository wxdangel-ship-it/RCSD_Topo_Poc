# P05-Scheme-A-P2-P2-P2-P0：安全证据充分性审计

## 1. 状态与授权

- 状态：已完成
- 授权日期：2026-07-23
- 唯一实施工作树：`E:\Work\RCSD_Topo_Poc__wt_p05_neural_road_20260721`
- 数据范围：仅复用 `E:\TestData\POC_Data` 已冻结 51 Case 与 P2-P1/P2-P2-P0/P2-P2-P1 证据
- 前置结论：`P05_SCHEME_A_P2_P2_P1_MODEL_NO_GO`
- Movement：继续忽略，candidate/decision/evaluation 均为零
- Git：不提交、不推送

正式结论：**`P05_SCHEME_A_P2_P2_P2_P0_EVIDENCE_NO_GO`**。正式 Run A/B 为 `p05_scheme_a_p2_p2_p2_p0_audit_20260723_02/_04`；规范化内容 signature 均为 `b04485a71f05df15d36135a3193edcf8db150855ae24878b435faead028142e3`。`_01` 为全局汇总 group 顺序修正前的无效诊断运行，`_03` 为墙钟字段移出 determinism payload 前的无效重放运行，均不作为正式指标来源。

本阶段不继续调整 P2-P2-P1 safety head。目标是审计当前允许在推理期使用的 truth-free 业务证据，判断它们能否跨 Case 稳定区分错误 proposal；只有证据本身通过低容量 probe，才具备另行启动正式模型的理由。

## 2. 阶段目标

1. 冻结 P2-P1 candidate/base OOF、P2-P2-P0 错误集合和 P2-P2-P1 正式结果。
2. 从当前已授权 model-input 事实构建 richer Segment safety evidence：T01 冻结骨架、T07 `DRIVEZONE_ONLY`、truth-free proposal payload、Segment→Node compatibility、Junction 共享风险和 base OOF 统计。
3. 对 8 个稳定 `KEEP_SWSD -> USE_RCSD`、1 个一致但错误的其他 carrier proposal 和 40 Review 建立逐对象证据账本。
4. 运行预先固定的线性与浅层数值 probe；probe 只判断冻结 proposal 是否可接受，不改选 candidate。
5. 以 5-fold Case-grouped cross-fit 和最终 Node/RoadGraph 闭包给出 evidence GO/NO-GO。

## 3. 源事实边界

### 3.1 允许进入 evidence/probe

- T01 SWSD Segment/Junction 冻结骨架与 fallback 身份。
- T07 `DRIVEZONE_ONLY` 的既有确定性输入证据。
- 已冻结、truth-free 的 Segment candidate feature/payload/source lineage。
- candidate 对 Node target 的 compatibility edge、Junction fanout/shared-carrier 风险。
- P2-P1 三 base seed 的 OOF probability/score/agreement/entropy/anomaly 统计。

### 3.2 继续禁止

- T03/T04/T05/T06 的 label、status、reason、terminal state、人工确认结果或 truth 派生字段。
- T06 final Road/Node truth、PTO Oracle 或最终正确性作为推理特征。
- `case_key`、`group_id`、`object_id`、`candidate_id` 及其 hash/记忆特征。
- 绝对坐标、Case 路径、fold 信息或 held-out 统计。
- 根据错误列表手工编码 Case/对象特例。

若审计证明必须提升当前 label-only 模块字段为 model input，命中统一架构二次确认边界，本阶段立即阻断，不自行修改源事实。

## 4. Probe 合同

- probe A：正则化线性 binary risk head。
- probe B：参数量 `<100,000` 的浅层 MLP risk head。
- 输入仅为冻结的数值/枚举 evidence；候选与 evidence manifest 必须在 label join 前冻结。
- 外层固定 5 Case folds；每个 held-out fold 的训练、归一化、早停和阈值只能使用其余 Case 的内层划分。
- probe 只输出 accept/fallback；不把 probe top-1 用作新 carrier。
- 禁止在查看正式 held-out 结果后增删特征、改阈值或选择第三个 probe 重报 GO。

## 5. 五类职责视角

### 产品

- 准确性和安全性优先；证据审计不以提高平均准确率为目标。
- 若 evidence NO-GO，自动发布路线停止，神经能力降级为离线排序/review 辅助。

### 架构

- 冻结 T01 Segment/Junction/PhysicalMovement 骨架；safety evidence 位于 Segment carrier 接受和 Node 条件化之前。
- fallback 后 Node truth 必须按最终有效 Road 来源条件化，不能与原始未回退 truth 机械比较。

### 研发

- 只新增 P05 内部审计 callable、probe、测试、SpecKit 和不可变输出。
- 不新增 CLI、root script、`__main__.py`、Makefile target、T10 stage 或 T01-T12 实现。

### 测试

- 覆盖 input hash、证据角色白名单、label/ID/坐标泄漏、Case fold 隔离、probe 只回退不改选、Node 条件化和重复运行确定性。
- 破坏测试必须检出 label-only 字段进入 feature、缺失错误对象、fold 重叠和 compatibility lineage 缺口。

### QA

- 51 Case、8,863 Segment、9 个一致错误 proposal、40 Review、3 base seed、5 fold 分母不得隐藏。
- 每个 evidence/decision 必须可回溯 candidate payload、compatibility edge、fold model、threshold 和最终 RoadGraph terminal state。

## 6. 验收门禁

### Gate 0：范围、lineage 与泄漏

- P2-P1 dataset/OOF A/B、P2-P2-P0、P2-P2-P1 Run A/B manifest/hash 全部可验证。
- 51 Case、8,863 Segment、9 个一致错误 proposal、40 Review、5 fold 分母精确。
- truth/label-only/ID/绝对坐标/Movement feature 和 train-held-out Case 交集均为零。

### Gate 1：证据完整性

- 9 个一致错误 proposal 和 40 Review 均有完整 evidence vector，缺失数为零。
- 每个 evidence 字段标明 source role、推理期可用性、聚合方法和禁止解释。
- T03/T04/T05/T06 status/reason/label 使用数为零。

### Gate 2：跨 Case probe

- 对每个 probe、每个 held-out fold：accepted wrong=`0`、9 个错误 proposal 自动发布=`0`、Review 自动发布=`0`、unsafe fallback recall=`1.0`。
- 对每个 probe、每个 held-out fold：总体 safe coverage `>=0.50`、truth `USE_RCSD` safe coverage `>=0.50`。
- 浅层 MLP 参数量 `<100,000`；线性 probe 参数、归一化和阈值完整可重放。

### Gate 3：Node/RoadGraph

- 通过 probe 的有效 Segment 决定必须保持 conditioned Node requirement conflict/mismatch=`0`。
- 每轮 49 `LEGAL + publish=true`、2 `EXPECTED_FAIL + publish=false`、unexpected failure=`0`。
- skeleton mutation=`0`、content repair=`false`、silent fix=`false`、Movement decision=`0`。

### Gate 4：确定性与资源

- 正式 Run A/B 的 evidence、score、decision、effective selection、RoadGraph 和 summary 内容 signature 一致。
- 总 wall `<=6h`、CPU RAM `<=16GB`、GPU VRAM `<=8GB`。

## 7. 决策口径

- 任一预登记 probe 对 Gate 0~4 全通过：`P05_SCHEME_A_P2_P2_P2_P0_EVIDENCE_GO`。
- Gate 0/1 通过但所有 probe 均未同时达到零错误和覆盖门：`P05_SCHEME_A_P2_P2_P2_P0_EVIDENCE_NO_GO`。
- 只有使用当前 label-only 模块事实才可能继续：`P05_SCHEME_A_P2_P2_P2_P0_SOURCE_FACT_BLOCKED`，必须交用户二次确认。
- lineage、分母或泄漏失败：`P05_SCHEME_A_P2_P2_P2_P0_AUDIT_NO_GO`。

任一结论都不自动授权正式新模型、在线 proposal、生产接入、T01-T12 改造或 Git 提交/推送。
