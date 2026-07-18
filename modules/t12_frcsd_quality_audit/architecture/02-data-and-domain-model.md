# 02 Data And Domain Model

## 1. 输入对象

- `Segment requirement`：SWSD Segment 的 pair、成员道路、必需方向和几何走廊。
- `FRCSD target`：原始 1V1 FRCSD Road/Node 拓扑。
- `Anchor group`：T05 base/grouped node、FRCSD main/subnode 和 RCSDIntersection 真值的并集。
- `Cross evidence`：T06 Step2/Step3、DriveZone 和 Case crop bounds。

## 2. 业务对象与分层

- `portal`：SWSD carrier 实际接入侧附近、且满足 start 出边或 end 入边角色的 FRCSD 节点。
- `carrier evidence`：local/full 与 directed/undirected 四种路径及其长度、偏离和道路序列。
- `candidate`：选择 base node 失败后需要进一步 portal 审计的 Segment。
- `review decision`：外部复核对 candidate 的确认、排除或待复核状态。

## 3. 几何与字段语义

- 所有距离计算使用 projected metre CRS；不同 CRS 只有显式 `processing_crs` 才能转换。
- 无效/空几何和缺失 endpoint 阻断运行，不自动 repair。
- Road `direction` 沿用 T06 当前语义；Source 不参与判定。

## 4. 下游语义

候选不是错误；只有 `review_status=confirmed_frcsd_quality_issue` 才能被下游解释为已确认质量问题。
