# 02 Data And Domain Model

## 1. 输入对象

- `Segment requirement`：SWSD Segment 的 pair、成员道路、必需方向和几何走廊。
- `FRCSD target`：原始 1V1 FRCSD Road/Node 拓扑。
- `Anchor group`：T05 base/grouped raw node；T07 另关联对应 RCSDIntersection 标准路口面。FRCSD main/subnode alias 只属于 canonical 候选证据。
- `Cross evidence`：T06 Step2/Step3、DriveZone 和 Case crop bounds。

## 2. 业务对象与分层

- `portal`：T07 为显式 group 或对应标准路口面内 raw node；T03/T04 为显式 group或 SWSD carrier 实际接入侧附近、且满足 start 出边或 end 入边角色的 raw node。
- `carrier evidence`：raw endpoint 图的 local/full 与 directed/undirected 四种路径及其长度、偏离和道路序列；canonical 路径只作对比。
- `candidate`：选择 base node 失败后需要进一步 portal 审计的 Segment。
- `automatic decision`：按 raw carrier 与锚点可信度对 candidate 的确认或排除。
- `review override`：可选外部 QA 对 automatic decision 的显式覆盖。

## 3. 几何与字段语义

- 所有距离计算使用 projected metre CRS；不同 CRS 只有显式 `processing_crs` 才能转换。
- 无效/空几何和缺失 endpoint 阻断运行，不自动 repair。
- Road `direction` 沿用 T06 当前语义；Source 不参与判定。

## 4. 下游语义

候选不是错误；只有自动高置信 decision 或显式外部 override 产生的 `review_status=confirmed_frcsd_quality_issue` 才能被下游解释为已确认质量问题。
