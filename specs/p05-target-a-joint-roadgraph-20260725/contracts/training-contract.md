# Training Contract

## 输入合同

训练 batch 只能由两个物理隔离的数据源 join：

1. `InferenceFeatureStore`：可在推理期重建的事实；
2. `TrainingLabelStore`：只用于 target、mask、sample weight 和 metric。

任何 label 字段进入 feature tensor 都是硬失败。

## Forward 合同

1. `encode(dependency_subgraph) -> object embeddings`
2. `anchor_head(embeddings) -> AnchorDecision logits`
3. `lock_anchor(argmax/abstain)`，后续不得反向修改
4. `ordinary_plan_head(embeddings, locked_anchor) -> plan logits`
5. `ordinary_decoder(plan_logits, fallback_directives, frozen_direct_relations) -> locked_ordinary_decisions`
6. `advance_right_head(embeddings, locked ordinary access) -> plan logits`
7. `advance_right_decoder(...) -> AR decisions`
8. `clue_head(...) -> clue/affected/fallback logits`
9. `validate_and_write_ledger(...)`

`fallback_directives` 由模型输出作用域与 affected objects；确定性 decoder 只用
冻结 T01 直接 Junction—Segment 关系验证。Segment directive 只含一个 Segment，
Junction directive 只含该 Junction 的直接关联 Segment，禁止从一个 directive
推导、合并或传递出新的 fallback 对象。Road ownership 的联合选择不得改变该作用域。

## Loss 合同

总损失：

`L = Σ sample_weight × task_mask × (L_anchor + L_plan + L_break +
L_access + L_node_recipe + L_clue + L_scope + L_structure)`

- acceptable-set：`-log Σ p(acceptable_plan)`；
- preferred：仅在 acceptable 集合内部加小权重排序损失；
- context-only 对象：所有业务 label/loss/metric mask 为 0；
- `no_valid_relation` 原因不明：只监督 anchor 非成功；
- hard invalid plan 在训练和推理中均 mask；
- teacher forcing 条件不进入共享 feature，只进入对应 stage condition；
- OOF 条件必须来自不含当前 Case 的模型。

### 方案 A 的来源与阶段合同

- 强 Gold 与 T10 弱监督允许更新同一个 raw-inference encoder；每条样本仍只按
  `sample_weight × task_mask` 更新有真值的任务，不得把未知字段映射为负例、
  `N/A`、KEEP 或失败；
- 强 Gold 的 Case 总有效权重为 1.0；一致多输入版本按版本数均分。T10 直接监督
  权重固定为 0.7；训练前必须按来源、split、字段 mask 和有效权重生成 cohort audit；
- `source_scope`、Case family、目录名和强/弱来源类别只允许存在于 label/lineage、
  batch 审计元数据和分层指标中，禁止进入任何网络 feature tensor；
- 第一阶段联合训练共享 encoder 和所有已监督 head；第二阶段只用强 Gold train
  consolidation，且同时读取强 Gold validation 与 T10 validation 选择 checkpoint，
  禁止用 consolidation 换取未声明的 T10 弱监督能力崩塌；
- Gold test 和 T10 test 在架构、loss、epoch、阈值及 seed 固定前不得加载。

## Split 合同

- 按 Case 和原始输入 source group 分组，禁止同一 Case、同一语义路口或同一原始
  内容版本跨 train/validation/test；
- 五个 1.0 目录的 T03/T04 单点对象按 Case ID 与原始输入内容 hash 去重；完全重复
  包只保留一个样本身份。不同输入版本若终态业务签名一致，必须在同一 split 并按
  版本数均分该 Case 的 1.0 总权重；终态冲突则进入 `LABEL_REVIEW`；
- 2026-08-04 冻结 Gold 为 700 个 Case group、708 个输入版本，
  train/validation/test=`490/105/105` 个 group，输入版本=`497/105/106`，有效权重
  仍为 `490/105/105`；测试集
  在模型结构、epoch、loss、阈值和 seed 选择前冻结，任何测试结果不得反向参与调参；
- 399 个 accepted surface 的 T05 延续标签分为 343 `SUCCESS`、19 正向
  `NO_RCSD_EVIDENCE`、37 `ACTION_ONLY/SAFETY_ONLY`。后 37 条不得进入完整 Road/Node
  拓扑 loss 或 exact 分母，但其已确认 surface、relation/action 和安全状态可按各自 mask
  参与训练；不得补造缺失的合法端点拓扑；
- T10 直接路口锚定监督权重为 0.7，按完整 Case/source group 约 70/15/15 划分；
  背景路口和非目标对象只作 context，label/loss/metric mask 为 0；
- 五个人工裁决在所有数据构建中优先覆盖；
- `T10-Error/1213556_1263661` 永久排除；
- 正式指标只聚合 label scope 内对象。

## 安全发布合同

任一硬安全门失败时，该 checkpoint 只能标记 `NO_GO`，不得通过降低阈值、改写
fallback 或把 SWSD fallback 计作自动决定来重报 GO。
