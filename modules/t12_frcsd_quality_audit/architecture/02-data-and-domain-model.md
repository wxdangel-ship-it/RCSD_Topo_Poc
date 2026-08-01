# 02 Data And Domain Model

## 1. 输入对象

- `Segment requirement`：SWSD Segment 的 pair、成员道路、必需方向和几何走廊。
- `FRCSD target`：原始 1V1 FRCSD Road/Node 拓扑。
- `Anchor group`：只展开 T05 选中 `base_id` 所属 canonical group；其它 grouped raw node 按显式成员保留但不递归扩组。选中 mainNode 的 subnode raw alias 是受信锚点成员，但不产生零成本通行。T07 另关联对应 RCSDIntersection 标准路口面。
- `Cross evidence`：T06 Step2/Step3、DriveZone 和 Case crop bounds。
- `T03 Junction source`：正式 T03 Step7 rejected 且 Step3/association/Step6/Step7 审计链完整的 Case；只形成待 T12 复核的候选域。
- `T07 anchor failure source`：Step2 `nodes.gpkg` 代表路口 final `is_anchor=fail1/fail2`；error GPKG、summary 与 relation evidence 只做一致性校验。`fail2 > fail1`，Step3 cardinality 不进入候选。

## 2. 业务对象与分层

- `portal`：选中 `base_id` mainNode 的 canonical raw alias group 先展开，显式 grouped raw node 不递归扩组；每个必需方向分别筛选角色：start 必须在 raw 有向图中具有 outgoing Road，end 必须具有 incoming Road；成员距离只作审计。非 anchored T07 fallback 为对应标准路口面内 raw node，非 anchored T03/T04 fallback 为 SWSD carrier 实际接入侧附近 raw node。反向 Road 端点不得因无向邻接进入当前方向 portal。
- `carrier evidence`：raw endpoint 图的 local/full 与 directed/undirected 四种路径及其长度、偏离和道路序列；只有 directed 路径可成为等价 carrier，undirected 路径只作方向缺失诊断。canonical directed 路径还记录物理 Road、端点 portal 信用和内部 alias gap，只有全部门禁通过才形成 portal-constrained semantic 排除证据。
- `candidate`：必需方向选择 base node 失败后需要进一步 portal 审计的 Segment，或要求方向已等价但存在 raw FRCSD 反向载体的单向 Segment。
- `unexpected reverse evidence`：反向 raw FRCSD 物理 Road 路径、双端 T07 标准路口面接触、锚点面之间逐 Road Segment 唯一归属与 SWSD 全图反向替代路径。反向与 SWSD 替代路径使用同一长度/走廊门禁，后者只作保守排除。短 Segment 的端点 portal 按两端 SWSD portal 距离做 Voronoi 分侧；双 T07 可在正确侧使用同 canonical group 且不超过 `portal_radius_m` 的实际 raw endpoint，但不增加任何图边。`50m` local graph 只用于召回；路口面内共享几何不参与 Segment owner，区间内 Road 按 `20m coverage > 50m coverage > geometry distance` 唯一归属。
- `automatic decision`：按 raw carrier、portal-constrained semantic 排除结果与锚点可信度对 candidate 的确认或排除。
- `review override`：可选外部 QA 对 automatic decision 的显式覆盖。
- `Junction candidate`：以 SWSD Node 代表 Point 为主对象，T03 候选保留 eligibility、target projection、support Road、terminal endpoint、component、Direction、替代 carrier、跨层与几何状态；T07 候选保留 error type、base IDs 和 conflict group。
- `Junction evidence`：support Road、FRCSD endpoint、target projection 和 T07 conflict link；它们解释根因但不改变 Point 主几何。

## 3. 几何与字段语义

- 所有距离计算使用 projected metre CRS；不同 CRS 只有显式 `processing_crs` 才能转换。
- 无效/空几何和缺失 endpoint 阻断运行，不自动 repair。
- DriveZone 无效几何不修改或归一化；只使受其影响的 Junction 候选保守排除，不改变既有 Segment verdict。
- Road `direction` 沿用 T06 当前语义；单向 Segment 的相反方向由已确认的必需方向反转得到，不从 Source 或 DriveZone 推断。
- T03 eligibility 固定为 `has_evd=yes`、`is_anchor=no`、`kind_2 in {4,2048}`。默认 `6m` 只定义 endpoint 投影容差，`50m` 只定义局部 Junction carrier 查询域；距离本身不是质量结论。

## 4. 下游语义

候选不是错误；只有自动高置信 decision、T07 Step2 稳定失败直接发布或显式 Segment 外部 override 产生的 `result_status=confirmed` 才能被下游解释为已确认质量问题。`review_status` 只保留一个版本兼容；Segment 与 Junction 输出、几何和计数域独立。
