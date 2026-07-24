# P05-Scheme-A-P2-P3-P12：T05 权威锚定与替换资格审计

## 1. 状态与授权

- 状态：已授权并进入实施
- 用户确认：2026-07-24
  - 不能用 T01 冻结关系完整或 RCSD 端点唯一匹配替代正式锚定；
  - 即使存在人工锚定处理记录，也必须经过 T05；
  - 已人工确认 `USE_RCSD` 的对象同时表达“两侧路口正确锚定且替换连接正确”；
  - `KEEP_SWSD` 的 7 个对象是 RCSD 数据缺失，不是 RealityChangeClue。
- 唯一实施工作树：
  `E:\Work\RCSD_Topo_Poc__wt_p05_neural_road_20260721`
- 承接阶段：
  `P05_SCHEME_A_P2_P3_P11_MANUAL_REVIEW_ACCEPTED`

P12 只允许读取 P11 人工裁决、冻结 Scheme-A Segment inventory、既有 P05
候选工件和登记 T10 Case 的 T01/T05 工件。不得训练、调阈值、修改模型权重、
修改 T01–T12、改写历史工件、提交或推送 Git。

## 2. 阶段目标

1. 将 T05 固化为正式 Junction 锚定的唯一发布依据；
2. 对 P11 的 19 个人工对象建立
   `Segment -> 两侧锚定目标 -> T05 relation -> RCSD carrier` 的可追溯证据链；
3. 区分以下三类事实：
   - T05 已正式锚定；
   - 只有 T01/拓扑唯一匹配，但没有 T05 正式关系；
   - RCSD carrier 数据缺失；
4. 判定哪些人工 `USE_RCSD` 已具备当前工件下的正式替换资格，哪些仅缺 T05
   lineage；
5. 不因 lineage 缺口推翻人工业务结论，也不把 RCSD 数据缺失误报为
   `RealityChangeClue`。

## 3. 业务口径

### 3.1 正式锚定

正式锚定必须来自对应 Case 的：

`t05/t05_phase2/intersection_match_all.geojson`

且满足：

- `target_id` 精确对应待锚定的 T01 Junction/接入节点；
- `status=0`；
- `base_id>0`；
- `target_id` 在关系表中唯一；
- T05 cardinality/blocking audit 不存在该 `target_id` 的阻断错误。

T01 `pair_nodes/junc_nodes` 完整、RCSD Road 端点几何接近、拓扑唯一或能唯一匹配
到某个 RCSD Node，都只能作为兼容性证据，不能单独产生“正确锚定”结论。

### 3.2 两侧目标

- `STANDARD Segment`：两侧目标来自冻结 `pair_nodes`，必须恰好两个；
- `ADVANCE_RIGHT Segment`：两侧目标来自冻结
  `source_segment_access/target_segment_access` 的 `@node_id`，不得从相邻 owner、
  几何邻近或名称猜测替代目标；
- `junc_nodes` 继续作为冻结 Segment 内部拓扑事实审计，但本阶段不自行把全部
  `junc_nodes` 重解释为“两侧路口”。

### 3.3 Carrier 资格

- 人工 `USE_RCSD`：必须先通过两侧 T05 正式锚定，再验证既有 `USE_RCSD`
  candidate Road 子图可连接到两侧 T05 已发布 Junction/Node；
- 人工 `KEEP_SWSD` 且 `rcsd_candidate_role=UNAVAILABLE`：最终替换资格为 false，
  原因是 `RCSD_CARRIER_UNAVAILABLE`；两侧是否已锚定只能作为独立审计结果；
- T05 lineage 缺失时，人工 `USE_RCSD` 保持业务真值，但当前正式替换资格必须
  阻断为 `T05_ANCHOR_LINEAGE_MISSING`；
- 不允许将 T06 终态或人工标签反向当成锚定输入。

### 3.4 RealityChangeClue

- 19 个对象继续保持人工 `clue_target=false`；
- T05 lineage 缺失是工件/流程证据缺口，不自动等价于现实道路变化；
- RCSD 数据缺失仍是 `KEEP_SWSD`，不生成 RealityChangeClue。

## 4. 验收门

### Gate 0：输入与 lineage

- P11 接受工件、Scheme-A inventory 与 candidate groups 均通过 size/hash 或冻结
  signature 校验；
- 三个 Case 的 T01/T05 必需工件存在并记录 SHA-256；
- 19/19 人工对象唯一连接 inventory 和 candidate group；
- 只读取登记 Case `T10:706247`、`T10:991176`、`T10:1885118`。

### Gate 1：T05 权威性

- 任何正式 `anchor_pass=true` 只能由 T05 成功关系产生；
- T01-only、geometry-only、topology-only 成功数必须为 0；
- 关系重复、`status!=0`、`base_id<=0` 或 blocking/cardinality 错误必须显式失败；
- 人工输入不得直接创建或覆盖 T05 relation。

### Gate 2：两侧与 carrier

- 19/19 对象均精确解析两个冻结侧目标；
- 12 个 `USE_RCSD` 必须逐对象输出两侧 T05 状态和 carrier 兼容状态；
- 7 个 `KEEP_SWSD` 必须保持
  `RCSD_CARRIER_UNAVAILABLE + clue=false + SEGMENT fallback`；
- `ADVANCE_RIGHT` 不得用相邻 owner 的端点替代 `@node_id` 以制造锚定通过；
- 共享冲突若存在只记录 Junction fallback 证据，不静默降为 Segment 通过。

### Gate 3：人工结论保护

- 人工 `allowed_targets/preferred_target/clue_target/rationale` 零改写；
- 缺少 T05 lineage 的 `USE_RCSD` 只标记当前发布阻断，不改为 `KEEP_SWSD`；
- 不自动生成新人工真值，不降低 1.0 权重。

### Gate 4：安全与隔离

- training、threshold tuning、model weight change、Movement decision、
  skeleton mutation、geometry write、T01–T12 modification 均为 0；
- 不修改历史 P8/P9/P10/P11 工件；
- 不新增 CLI、script、T10 stage 或正式入口。

### Gate 5：确定性、GIS 与性能

- 正式双跑 content signature 一致；
- CRS 只核验一致性，不做坐标转换；
- 拓扑只读验证，不做 silent fix；
- 几何语义通过 Road/Node 引用和端点图关系解释，不改变 geometry；
- 输入、参数、输出、hash、运行环境可追溯；
- 19 对象正式运行 wall time 目标小于 2 分钟、峰值 RAM 目标小于 1 GiB；
- 专项测试和完整 P05 回归通过；
- 新增源码与测试文件均小于 100 KB。

## 5. 决策

- 12/12 人工 `USE_RCSD` 均完成 T05 正式锚定及 carrier 兼容闭环：
  `P05_SCHEME_A_P2_P3_P12_ANCHOR_ELIGIBILITY_GO`
- 审计可信，但至少一个人工 `USE_RCSD` 缺少 T05 正式 lineage：
  `P05_SCHEME_A_P2_P3_P12_T05_LINEAGE_REPAIR_REQUIRED`
- 输入、join、权威性、确定性或隔离合同失败：
  `P05_SCHEME_A_P2_P3_P12_AUDIT_NO_GO`

`T05_LINEAGE_REPAIR_REQUIRED` 表示当前不能把相关对象用于正式自动替换，也不能
直接进入下一轮 scorer 训练；它不表示人工业务判断错误，也不表示神经网络不适用。

## 6. 五类职责视角

### 产品

- 明确“业务上可替换”和“当前正式证据可发布”是两个独立状态；
- 只把需要补 T05 lineage 的最小对象清单交给用户或上游流程。

### 架构

- T05 是正式锚定唯一发布口；
- T01 保持冻结骨架职责，P05 只消费正式关系并做软评分/异常线索；
- carrier 兼容性不能反向生成锚定事实。

### 研发

- 新增 P05 内部只读 callable；
- 输出逐对象 ledger、lineage repair queue、metrics、summary、manifest 和报告；
- 不新增正式入口。

### 测试

- 覆盖 T01-only 禁止通过、T05 成功/失败/重复、`ADVANCE_RIGHT @node_id`、
  RCSD 缺失与人工真值保护；
- 覆盖双跑确定性。

### QA

- 核验输入 hash、CRS、拓扑/几何零修改、零训练、零 T01–T12 修改、资源与
  文件体量；
- 对 `USE_RCSD` lineage 缺口逐对象可复现。
