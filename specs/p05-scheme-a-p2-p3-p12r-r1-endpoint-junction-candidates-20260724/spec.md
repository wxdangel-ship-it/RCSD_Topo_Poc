# P05-Scheme-A-P2-P3-P12R-R1：提右 Endpoint/JunctionUnit 条件化候选补强

## 1. 背景

P12R已证明474个`ADVANCE_RIGHT Segment`的条件化真值、安全fallback、attachment
和通用materializer合同成立；总体candidate oracle recall为`377/396=0.952020`，
但T10:706247所在fold仅`21/24=0.875`。19个漏候选均为`RCSD_ONLY`，不能进入
P13 scorer。

其中17个正确RCSD有直接lineage，但距原SWSD提右为`5.15–43.55m`；另2个缺少可
直接消费的原始RCSD lineage。这说明5m局部几何窗不足，但不授权直接放宽距离阈值。

## 2. 目标

在P05内部新增truth-free、Road endpoint/JunctionUnit条件化的原始RCSD提右候选：

1. 保留P12R 5m局部候选为Control；
2. 从冻结`source_segment_access/target_segment_access`取得两个普通Segment；
3. 从T01普通Segment Road/Junction上下文建立两侧owner carrier evidence；
4. 在原始RCSD图中从提右Road两个endpoint检查相邻普通Road carrier；
5. 只把两侧carrier可分别关联到对应普通Segment/JunctionUnit的RCSD提右加入
   Treatment；
6. 候选冻结后才读取P12R label-only truth计算Oracle。

本阶段不训练模型，不修改T01–T12，不改变P12R真值和fallback。

## 3. 数据角色

### 3.1 推理允许

- T01 frozen Segment/access/Junction/Road/Node；
- 原始RCSD Road/Node及其有向endpoint拓扑；
- 由上述事实确定性计算的距离、方向、incident Road、bounded trace和候选来源。

### 3.2 label-only

- P12R `advance_right_realization_truth.jsonl`；
- T06 relation/final/attachment/closure/topology；
- P11人工接受集；
- P12R candidate oracle hit与fold指标。

label-only字段只能在Treatment候选集合冻结后评价，不得用于生成、排序、阈值选择或
失败后补候选。

### 3.3 禁止

- T05提右anchor；
- T06终态Road/Node、relation、reason或truth作为candidate/feature；
- Movement字段；
- object/case白名单、逐ID特判；
- 直接把5m改为更大业务阈值；
- 全Case原始RCSD提右无条件入选。

## 4. 候选合同

每个RCSD提右候选至少记录：

- `case_key/object_id/candidate_road_id/fold`；
- `candidate_sources`：`LOCAL_5M`或`ENDPOINT_JUNCTION`；
- source/target owner Segment与access Node；
- 两个RCSD endpoint及incident非提右Road；
- 两侧owner匹配方式、距离、trace hop和方向；
- orientation是否唯一；
- candidate是否新增、是否有限、是否跨Case；
- candidate冻结signature。

Endpoint/Junction候选必须满足：

1. 原始RCSD Road具有提右语义；
2. 原始RCSD提右Road先按相同Node连接成有向component；仅在候选层允许把
   end-to-start几何gap `<=1m`的连续component，或source/source与target/target
   均`<=5m`的平行component合为bundle，不修改Node或geometry；
3. bundle两个有向边界均存在原始RCSD incident非提右Road carrier evidence；
4. carrier与对应T01普通Segment Road context的候选关联距离均`<=10m`；该10m只
   是高召回候选阈值，不是锚定正确性或最终发布合法性；
5. 正向或反向orientation以两侧最大carrier距离较小者唯一确定；相同owner可标记
   `SAME_OWNER`，不同owner严格并列时不自动加入；
6. 不改变任何Road/Node geometry或ID。

## 5. Case fold

严格复用P12R的6 Case、474对象和Case-grouped 5-fold，不重新分配、不按Treatment
结果挑fold。

## 6. 验收门

### Gate 0：范围与复现

- P12R Control 474对象、6 Case、5-fold及truth signature精确复现；
- P12R Gate 0/1/2/4继续通过；
- T01–T12修改、训练、Movement decision、geometry write均为0。

### Gate 1：推理来源与防泄漏

- 100% Treatment候选仅来自T01与原始RCSD；
- T05提右label和T06 candidate/feature计数均为0；
- candidate冻结前label/truth读取计数为0；
- Case/object硬编码和跨Case候选计数为0。

### Gate 2：Endpoint/Junction语义

- 新增候选两端evidence完整率100%；
- orientation歧义候选自动加入数为0；
- endpoint carrier与对应普通Segment/Junction上下文匹配率100%；
- 无silent fix，无未知字段语义固化。

### Gate 3：候选召回与规模

- Treatment总体candidate oracle recall `>=0.95`；
- 最差fold candidate oracle recall `>=0.90`；
- Treatment相对Control总体和逐fold均不得下降；
- 每个fold至少有一个正确候选和一个可比较候选组；
- candidate count P95 `<=10`、单对象最大`<=32`；
- unsafe auto publish保持0。

### Gate 4：确定性、GIS与资源

- CRS一致且为可解释米制；
- 正式双跑content signature一致；
- wall time `<5min`、峰值RSS `<1GiB`、GPU=0；
- 新增源码/测试单文件 `<100KB`。

## 7. 决策

- 全部Gate通过：
  `P05_SCHEME_A_P2_P3_P12R_R1_CANDIDATE_GO`
- 硬门通过但召回仍未过：
  `P05_SCHEME_A_P2_P3_P12R_R1_RECALL_NO_GO`
- 召回通过但候选规模/歧义门失败：
  `P05_SCHEME_A_P2_P3_P12R_R1_CANDIDATE_QUALITY_NO_GO`
- 任一范围、来源、业务、安全、GIS或确定性硬门失败：
  `P05_SCHEME_A_P2_P3_P12R_R1_AUDIT_NO_GO`

R1 GO只允许讨论P13 scorer目标，不自动授权训练、生产接入或自动替换SWSD。

## 8. 职责视角

- 产品：明确“补候选”不等于“模型已可发布”；
- 架构：保持骨架、候选、label和materializer四层隔离；
- 研发：仅新增P05内部callable，不新增正式入口；
- 测试：覆盖orientation、endpoint trace、歧义、泄漏和规模门；
- QA：正式双跑、hash、CRS、拓扑、安全、资源与体量可追溯。
