# P05-JSG-PTO-P1：无真值候选可达与双层 Oracle PTO

## 1. 状态与授权

- 状态：`ACTIVE / IMPLEMENTATION AUTHORIZED`
- 授权日期：2026-07-22
- 授权来源：用户明确授权启动 `P05-JSG-PTO-P1`，并确认统一项目状态为“P0 已完成、P1 已启动；M1/M2R/R2/RoadGraph PTO-P0 为历史实验结论”
- 数据范围：仅 `E:\TestData\POC_Data` 内冻结的 51 个 RoadGraph Case
- 显式排除：`T10-Error / 1213556_1263661`

## 2. 产品目标

证明在候选层不读取 P0 canonical truth、T06 冻结真值或 R2 Oracle payload 的前提下，推理时可用证据可以生成覆盖正确 Junction—Segment—Movement 结构的有限 JSG 候选；候选冻结后，PTO-A/PTO-B 能使用 label-only Oracle cost 选择可编译的最优结构并生成合法 T06 Step3 Road/Node。

P1 回答“正确答案是否进入候选域、双层约束是否可解”。P1 不训练 scorer，不评价跨 Case 学习泛化，也不授权生产接入。

## 3. 范围

### 3.1 本轮包含

1. 建立推理证据 `EvidenceGraph` 与无 truth JSG 候选合同。
2. 生成 Junction、StandardSegment、Relation、Movement、Connector、Review/Unknown 与 Unit carrier 候选。
3. 先冻结 candidate manifest/hash，再读取 P0 truth 和 R2 Oracle 计算 label-only cost。
4. PTO-A 选择全局业务语义结构；PTO-B 选择 RoadGraph edit 与 Unit carrier 可行实现。
5. 复用 P0 evaluator/compiler、R2 materializer 和 M0 RoadGraph evaluator。
6. 执行两轮独立 51 Case 运行，形成覆盖、最优性、物化、确定性、GIS 和资源证据。

### 3.2 本轮不包含

- 不训练神经网络、GBDT、线性模型或其它 scorer。
- 不修改 T01-T09 代码、接口、业务规则或生产主链。
- 不新增 repo CLI、root script、Makefile target、模块 `__main__.py` 或 T10 stage。
- 不接入点云、BEV、轨迹或生产全量数据。
- 不通过 Case ID 特判、truth-derived candidate、relaxation、内容修复或 silent fix 提升通过率。
- 不把 RoadGraph PTO-P0 的历史在线性能失败改写为已解决。

## 4. 角色视角

### 产品

交付一套可审计的 JSG 候选域与双层 Oracle 证书，明确候选覆盖不足、约束不可解和编译失败分别发生在哪里。

### 架构

候选生成、候选冻结、Oracle cost、PTO-A、PTO-B 和 compiler 六层隔离。候选配置不接受 P0/R2 truth 路径；Oracle 配置必须同时验证候选 manifest 与 P0 truth lineage。

### 研发

只在 P05 模块内新增 Python callable/data contract，复用既有 truth-free PTO candidate 基础设施、P0 JSG truth、R2 solver/materializer 和 M0 evaluator。实现不得调用 T01-T06 业务规则重跑。

### 测试

覆盖 truth 参数拒绝、候选规范化、group dependency、Review/Unknown、多个 THROUGH、Connector outcome、PTO-A/PTO-B infeasible、carrier 引用、manifest tamper、重复运行确定性与资源计量。

### QA

真实 51 Case 分别验证 CRS、对象/关系、候选覆盖、Oracle 最优性、carrier 可行性、Road/Node 拓扑、hash lineage、运行环境和性能。零实例对象与 Review 分母不得隐藏。

## 5. 输入与泄漏边界

### 5.1 候选阶段允许输入

- 已登记且 manifest 明确为 `truth_input_count=0`、`truth_derived_candidate_count=0` 的 RoadGraph PTO candidate run。
- 该 run lineage 中的 T01 Segment/Node/Road、raw/prepared SWSD/RCSD、道路面和策略 replay proposal evidence。
- 候选资产的 manifest、case index、candidate/group index、lineage 与 hash。

登记策略输出只作为 proposal source，不是正确答案；候选必须保留 `source_kind/code_commit/artifact_hash`。P1 不重新执行策略链，历史 replay 成本单独报告。

### 5.2 候选阶段禁止输入

- P0 `jsg_truth.json`、P0 semantic signature、P0 review/anomaly 结论。
- R2 Oracle edit/pointer payload、T06 冻结 truth Road/Node/Segment relation。
- 任何由真值比较产生的 candidate ID、候选 payload、过滤条件或排序特征。

### 5.3 Oracle 阶段

候选 manifest 写出、哈希并关闭后，Oracle 阶段才允许读取 P0 truth/R2 Oracle。truth 只产生 cost、coverage 和 expected signature，不得增加、删除或改写候选。

## 6. 候选与双层求解合同

### 6.1 PTO-A

- Junction、StandardSegment、Relation、Movement、Connector 各自按稳定 `group_id` 选择。
- Segment 身份、端点、附属 Junction 和 loop 候选来自 T01；方向、状态和有歧义类型保留有限备选。
- Movement 在同一 Junction 的 incident Segment access 之间生成，不跨局部邻域全连接。
- Connector 对每个 `advance_right` 提供 materialized、auxiliary、not-materialized、review 等有限 outcome。
- 多 THROUGH 只能选择 Review/Unknown，不得以固定排序自动发布某一个 THROUGH。

### 6.2 PTO-B

- Road/Node edit 和 pointer 选择复用已冻结的 truth-free RoadGraph PTO candidate group。
- 选中 RoadGraph 后，对每个已选业务 Unit 验证存在合法 carrier/access；carrier 候选只由已选物理图、局部 access 和已登记 proposal lineage产生。
- compiler 只执行已选 JSG/carrier/edit IR，不调用 T01-T06 策略补齐。

## 7. 成功标准

### Gate 0：范围、冻结与零泄漏

- 51 Case，排除项出现次数 0。
- candidate run 在 Oracle 前完成，所有 candidate/group/lineage 文件有 SHA-256。
- `truth_input_count=0`、`truth_derived_candidate_count=0`、`label_only_candidate_count=0`。
- 候选源码无具体 Case ID 特判。

### Gate 1：Oracle 候选可达

- P0 中所有实际出现且可确认的 Junction、Segment、Relation、Movement、Connector 语义投影候选召回率 100%。
- Review/Unknown 单列；7 个多 THROUGH 冲突不自动选择。
- RoadGraph PTO-B 的 FINAL_ROAD、FINAL_NODE、T05_NODE、T05_POINTER 与 SPLIT child reachability 保持 100%。
- 候选有限、规范化去重，unbounded enumeration=false。

### Gate 2：PTO-A/PTO-B Oracle

- 51/51 Case PTO-A 与 PTO-B 均 `OPTIMAL`、gap=0、deterministic certificate 完整。
- dependency、endpoint、reference、direction、Movement、Connector、carrier 和 graph hard failure 为 0。
- `relaxation=false`、`content_repair=false`、`silent_fix=false`。

### Gate 3：编译与 RoadGraph

- 51/51 选中 JSG 可物化，compiler hard failure=0。
- Road/Node CRS、ID、引用、属性、几何和有向拓扑与冻结 T06 truth 精确一致。
- 编译器不补路、不吸附、不重连，不读取未选 candidate。

### Gate 4：确定性、资源与审计

- 两个独立 candidate/solve run 的候选、选择、JSG、RoadGraph signature 一致。
- 从冻结 candidate 输入开始的 P1 增量链 P95/max `<=60s/300s`、RSS `<=16GB`、总 CPU `<=2h`、GPU 不需要。
- 历史策略 replay wall/CPU/RAM 单独列出；其性能不满足时不得声明在线 proposal GO。

任一 hard gate 失败即 P1 no-go；不得缩小分母、增加 Case 特判或使用 truth 生成候选掩盖。

## 8. 完成定义

只有 SpecKit、项目/P05 source-of-truth、候选/Oracle callable、测试、两轮真实 51 Case 证据、determinism audit 和 validation summary 全部完成，P1 才可标记完成。
