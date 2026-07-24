# P05-Scheme-A-P2-P3-P12R：提右条件化真值重建与候选上限审计

## 1. 状态与授权

- 状态：已授权并进入实施
- 用户确认日期：2026-07-24
- 唯一实施工作树：
  `E:\Work\RCSD_Topo_Poc__wt_p05_neural_road_20260721`
- 数据范围：只读使用 `E:\TestData\POC_Data` 与既有 P05/T06 冻结工件
- 承接阶段：
  `P05_SCHEME_A_P2_P3_P11_MANUAL_REVIEW_ACCEPTED`
- 取代范围：旧 P12 中把 `ADVANCE_RIGHT @node_id` 当成 T05 锚定目标的部分
  失效；旧 P12 对普通 `STANDARD Segment` 的 T05 权威锚定事实继续保留为
  历史审计背景。

本阶段不训练模型、不调整阈值、不修改 T01–T12、不新增正式入口、不提交或
推送 Git。P1–P11 及旧 P12 原始工件保留，不删除、不改写。

## 2. 业务目标

把 `ADVANCE_RIGHT Segment` 从独立
`USE_RCSD / KEEP_SWSD / MIXED_CARRIER / REVIEW_FALLBACK` 平面标签改为
`AdvanceRightRealizationUnit` 条件化局部构图真值：

1. 两端相邻普通 Segment 先完成 RCSD/SWSD carrier 决策；
2. 提右两侧所需来源由相邻普通 Segment 结果派生，不由提右模型自由预测；
3. 两侧来源不一致时，真值必须表达 RCSD/SWSD 中间几何衔接；
4. 提右 Road 上挂接的其它 Segment 必须进入同一实现单元的后处理审计；
5. 无合法候选或衔接时安全 fallback，不把 RCSD 数据缺失自动解释为
   `RealityChangeClue`；
6. T06 终态只作 label/evaluation，不得成为推理候选或 feature。

本阶段最终回答两个问题：

- 现有474个提右是否都能形成可追溯、业务正确的条件化真值；
- 在排除 T06 终态泄漏后，模型推理时可见的候选是否包含正确实现方案。

## 3. 业务执行顺序

```text
冻结 T01 ADVANCE_RIGHT 身份与两侧 SegmentAccess
        |
        v
读取两侧普通 Segment 的 T06 label-only relation
        |
        v
派生 REQUIRED_RCSD / REQUIRED_SWSD 两侧来源
        |
        v
从 T01 SWSD 与原始 RCSD 输入建立 truth-free 候选组件
        |
        v
用 T06 final Road/Node + attachment/closure/topology audit 重建真值方案
        |
        v
审计候选可组合性、几何衔接、挂接 Segment 与安全 fallback
```

## 4. 数据角色

### 4.1 推理允许

- T01 冻结 Segment、Road、Node；
- `source_segment_access / target_segment_access`；
- `E:\TestData\POC_Data` 中原始 `rcsdroad / rcsdnode`；
- CRS、Road/Node 引用、方向、几何距离、连通组件；
- 由上述事实确定性构造的 candidate 与 materializer action。

### 4.2 标签专用

- `t06_step3_swsd_frcsd_segment_relation.*`；
- `t06_step3_advance_right_attachment_audit.*`；
- `t06_step3_rcsd_advance_right_closure_audit.*`；
- `t06_step3_topology_connectivity_audit.*`；
- `t06_frcsd_road.* / t06_frcsd_node.*`；
- P11 人工裁决。

### 4.3 禁止泄漏

- 以 T06 final Road/Node payload 直接充当推理候选；
- 以 T06 relation/status/reason 生成推理 feature；
- 用人工 preferred/allowed target 反向生成候选；
- 用 T05 为提右两个 SegmentAccess 建立锚定标签。

## 5. 条件化真值

每个 `AdvanceRightRealizationUnit` 至少表达：

- `case_key / object_id / fold`
- `source_adjacent_segment_id / target_adjacent_segment_id`
- `source_required_source / target_required_source`
- `source_realized_source / target_realized_source`
- `truth_plan_type`
- `truth_swsd_road_ids / truth_rcsd_road_ids`
- `candidate_swsd_road_ids / candidate_rcsd_road_ids`
- `splice_required / splice_boundary_node_ids`
- `attachment_segment_ids / attachment_actions`
- `access_valid / candidate_oracle_hit`
- `fallback_required / fallback_reason`
- `reality_change_clue`
- 全部输入、标签和输出 lineage

`truth_plan_type` 至少区分：

- `RCSD_ONLY`
- `SWSD_ONLY`
- `MIXED_SPLICE`
- `SAFE_SWSD_FALLBACK`
- `REVIEW_FALLBACK`

## 6. Case fold

冻结数据中474个提右只分布在6个 Case，历史全局 fold 仅3个含提右。P12R
不得伪造空 fold 或拆散同一 Case；应按 Case 粒度建立独立、确定性的5-fold
审计分配：

- 同一 Case 的全部提右只能进入同一 fold；
- 仅按 Case 提右数量做确定性负载均衡，不读取真值类别或候选命中；
- 5个 fold 均至少包含1个 Case和1个提右；
- 该分配只服务 P12R/P13，不改写 P1–P11 历史 fold。

## 7. 验收门

### Gate 0：范围与 lineage

- 474/474 提右唯一连接冻结 inventory、T01 evidence 与 T06 label evidence；
- 仅处理6个包含提右的登记 Case；
- 全部输入记录 path、size、SHA-256、CRS和数据角色；
- P1–P11、旧 P12 与 T01–T12 修改数均为0。

### Gate 1：业务语义

- 两侧相邻普通 Segment 解析率100%；
- 两侧 required source 与普通 Segment relation一致率100%；
- 提右 endpoint 的 T05 anchor label 数为0；
- RCSD缺失误报 `RealityChangeClue` 数为0；
- 40个 `access_valid=false` 对象保持显式 Review/fallback，不猜测 access。

### Gate 2：条件化真值

- 474/474 输出唯一条件化真值或显式 Review/fallback；
- 自动资格对象两侧 realized source、carrier、splice和attachment均可由
  T06 label-only证据重放；
- 挂接 Segment 丢失数为0；
- 正式 Segment 失去独立 Road 数为0；
- 由真值方案命中的 `segment_transition / independent_attachment` 硬失败数为0。

### Gate 3：候选上限

- T06终态作为推理候选或feature的计数为0；
- eligible对象总体 `candidate_oracle_recall >= 0.95`；
- P12R 5-fold 最差 fold `candidate_oracle_recall >= 0.90`；
- 每个 fold 至少包含一个有正确候选的对象和一个可比较候选组；
- 不可组合对象必须安全 fallback，unsafe auto publish数为0。

### Gate 4：GIS、确定性与资源

- 所有 Case CRS 为可解释的米制 CRS；本阶段不转换、不写 geometry；
- 空间关联使用冻结阈值并输出候选数、最小距离、并列/歧义状态；
- 所有 Road/Node 引用和方向可解释，无 silent fix；
- 正式双跑 content signature一致；
- GPU使用数为0，训练数为0；
- wall time目标小于5分钟，峰值RSS目标小于1 GiB；
- 新增源码与测试均小于100 KB。

## 8. 决策

- 全部 Gate 通过：
  `P05_SCHEME_A_P2_P3_P12R_GO`
- Gate 0/1/2/4通过，总体候选召回位于 `[0.90, 0.95)` 或最差 fold低于
  `0.90`：
  `P05_SCHEME_A_P2_P3_P12R_CANDIDATE_REMEDIATION_REQUIRED`
- 总体候选召回 `<0.90`：
  `P05_SCHEME_A_P2_P3_P12R_CANDIDATE_NO_GO`
- 任一 lineage、业务语义、安全、GIS、隔离或确定性硬门失败：
  `P05_SCHEME_A_P2_P3_P12R_AUDIT_NO_GO`

P12R GO 只授权讨论 P13 条件化 scorer，不自动授权训练。P12R NO-GO 只说明
候选或审计合同不足，不等于神经网络整体不适用。

## 9. 五类职责视角

### 产品

- 将提右结果解释为两侧 Segment 决策后的条件化实现；
- fallback 只要符合当前业务基线即算安全成功；
- 自动化率服从准确性与安全性。

### 架构

- 冻结 T01 Junction—Segment—AdvanceRight 骨架；
- 普通 Segment carrier 决策先于提右 realization；
- 模型只评分 realization candidate，通用 materializer负责引用、方向、split、
  splice和拓扑合法性。

### 研发

- 新增 P05 内部只读 callable和数据模型；
- 不新增 CLI、script、T10 stage、`__main__.py`或Makefile target；
- 输出真值、候选、attachment、metrics、summary、manifest和报告。

### 测试

- 覆盖四种两侧来源组合、RCSD缺失、access无效、mixed splice、挂接 Segment、
  T06泄漏拒绝、fold分配和双跑确定性；
- 覆盖候选召回和安全决策边界。

### QA

- 核验CRS、拓扑、几何语义、lineage、性能和文件体量；
- 核验零训练、零geometry write、零T01–T12修改和零silent fix；
- 对每个候选缺口给出可复现对象与原因。
