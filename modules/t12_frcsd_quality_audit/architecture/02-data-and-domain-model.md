# 02 Data And Domain Model

## 1. 输入对象

- `Segment requirement`：SWSD Segment 的 pair、成员道路、必需方向和几何走廊。
- `FRCSD target`：原始 1V1 FRCSD Road/Node 拓扑。
- `Anchor group`：只展开 T05 选中 `base_id` 所属 canonical group；其它 grouped raw node 按显式成员保留但不递归扩组。选中 mainNode 的 subnode raw alias 是受信锚点成员，但不产生零成本通行。T07 另关联对应 RCSDIntersection 标准路口面。
- `Cross evidence`：T06 Step2/Step3、DriveZone 和 Case crop bounds。

## 2. 业务对象与分层

- `portal`：选中 `base_id` mainNode 的 canonical raw alias group 先展开，显式 grouped raw node不递归扩组；每个必需方向分别筛选角色：start 必须在 raw 有向图中具有 outgoing Road，end 必须具有 incoming Road；成员距离只作审计。非 anchored T07 fallback 为对应标准路口面内 raw node，非 anchored T03/T04 fallback 为 SWSD carrier 实际接入侧附近 raw node。反向 Road 端点不得因无向邻接进入当前方向 portal。
- `carrier evidence`：raw endpoint 图的 local/full 与 directed/undirected 四种路径及其长度、偏离和道路序列；只有 directed 路径可成为等价 carrier，undirected 路径只作方向缺失诊断。canonical directed 路径还记录物理 Road、端点 portal 信用和内部 alias gap，只有全部门禁通过才形成 portal-constrained semantic 排除证据。
- `candidate`：选择 base node 失败后需要进一步 portal 审计的 Segment。
- `automatic decision`：按 raw carrier、portal-constrained semantic 排除结果与锚点可信度对 candidate 的确认或排除。
- `review override`：可选外部 QA 对 automatic decision 的显式覆盖。

## 3. 几何与字段语义

- 所有距离计算使用 projected metre CRS；不同 CRS 只有显式 `processing_crs` 才能转换。
- 无效/空几何和缺失 endpoint 阻断运行，不自动 repair。
- Road `direction` 沿用 T06 当前语义；Source 不参与判定。

## 4. 下游语义

候选不是错误；只有自动高置信 decision 或显式外部 override 产生的 `review_status=confirmed_frcsd_quality_issue` 才能被下游解释为已确认质量问题。
