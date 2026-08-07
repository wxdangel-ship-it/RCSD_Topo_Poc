# P05 Junction GraphSet v1 特征来源审计

## 1. 审计结论

既有 `64D/12D` 特征不能再被统称为一套候选特征。审计后冻结为四种有类型的兼容向量：

| 向量类型 | 维度 | raw | derived_geometry | candidate_metadata | forbidden |
|---|---:|---:|---:|---:|---:|
| `object64` | 64 | 4 | 21 | 0 | 39 |
| `node_candidate64` | 64 | 13 | 21 | 2 | 28 |
| `road_bundle64` | 64 | 5 | 31 | 9 | 19 |
| `member12` | 12 | 0 | 11 | 1 | 0 |
| 合计 | 204 | 22 | 84 | 12 | 86 |

其中 `node_candidate64` 与 `road_bundle64` 会复用同一维度编号表达不同含义。例如索引 7
分别表示 `member_count` 和 `road_count`。新链路必须显式提供向量类型；无类型的
`candidate64` 不可进入训练或推理。

这些向量只作为新 Graph/Set 主表示之外的兼容辅助特征，不代替后续 21D 对象表示和 8D
关系表示。

## 2. Step1 可见性

T07 Step1 的 RC 证据严格为 DriveZone-only。SWSD 语义路口是查询对象，不属于 RC
证据。冻结的 `object64` 可见索引为：

`0, 1, 2, 3, 13, 14, 15, 21, 22, 23, 24`

- `0–3`：SWSD 语义路口查询属性；
- `13–15`：SWSD 路口臂几何；
- `21–24`：DriveZone 计数、覆盖、距离和包含面面积；
- RCSD Node、RCSD Road、RCSDIntersection 及全部候选向量在 Step1 物理不可见；
- `forbidden` 维度保持关闭且必须为零。

## 3. object64 逐维来源

| 索引 | 分类 | 内容 |
|---|---|---|
| 0–3 | raw | SWSD `kind/kind2/grade/closed_con` 查询属性 |
| 4–9 | derived_geometry | RCSD Node/group 数量、分段距离计数和最小距离 |
| 10–12 | derived_geometry | RCSDIntersection 面数量、接触数量和最小距离 |
| 13–15 | derived_geometry | SWSD 路口臂数量、方向数和离散度 |
| 16–20 | derived_geometry | RCSD Road 数量、分段距离计数和最小距离 |
| 21–24 | derived_geometry | DriveZone 数量、覆盖数量、最小距离和包含面面积 |
| 25–63 | forbidden | 历史零填充；禁止作为证据 |

## 4. node_candidate64 逐维来源

| 索引 | 分类 | 内容 |
|---|---|---|
| 0–6 | derived_geometry | 距离及 5/10/25/50/80/120m 阈值 |
| 7 | candidate_metadata | Node group 成员数 |
| 8–15 | raw | Node/group 类型、层级、关联 Road 与方向统计 |
| 16 | derived_geometry | 是否关联 RCSDIntersection 面 |
| 17–21 | raw | RCSDIntersection 类型、等级、高速属性、Node/Road 数量 |
| 22–26 | derived_geometry | 面距离与相对偏移 |
| 27 | candidate_metadata | 固定的 Node 候选类型标识 |
| 28–35 | derived_geometry | SWSD/候选臂数量、对齐度和离散度 |
| 36–63 | forbidden | 历史零填充；禁止作为证据 |

## 5. road_bundle64 逐维来源

| 索引 | 分类 | 内容 |
|---|---|---|
| 0–6 | derived_geometry | Road bundle 最小距离及距离阈值 |
| 7 | candidate_metadata | bundle Road 数量 |
| 8–13 | derived_geometry | 长度、图节点、连通分量、叶节点和分支数量 |
| 14–18 | raw | Road 方向统计和最大功能等级 |
| 19 | derived_geometry | 投影比例 |
| 20–27 | candidate_metadata | 候选生成阈值、生成器类型、保留位和 bundle 类型标识 |
| 28–35 | derived_geometry | SWSD/候选臂数量、对齐度和离散度 |
| 36–44 | derived_geometry | 全局及局部 corridor 距离/覆盖率 |
| 45–63 | forbidden | 历史零填充；禁止作为证据 |

索引 25、26 是已识别但当前恒为零的候选生成保留位，不承载业务事实；后续新主表示不得使用。

## 6. member12 逐维来源

| 索引 | 分类 | 内容 |
|---|---|---|
| 0 | candidate_metadata | 成员是 Road 还是 Node |
| 1–5 | derived_geometry | 距离/半径和距离阈值 |
| 6–11 | derived_geometry | Road 投影、端点距离、切向和长度；Node 成员必须为零 |

## 7. 隔离门禁

- feature shard 只允许冻结的推理期字段，递归禁止 `label/truth/preferred/acceptable/selected/status/split/fold/family/route/T03/T04/T05` 终态键；
- label shard 只允许 `train/validation` 进入开发视图，任何 `test` 立即阻断；
- feature 与 label 必须按唯一 `sample_id` 严格一一对应；
- 冻结测试共 106 条，其中 1 条仅用于历史 schema discovery quarantine，剩余 105 条仅保存身份聚合哈希；T029 前无读取接口。

## 8. T002 写前体量审计

本阶段只新增两个 Python 文件，写入前均不存在，按 0 byte 完成检查：

- `src/rcsd_topo_poc/modules/p05_neural_road_generation/junction_graphset_v1_governance.py`
- `tests/modules/p05_neural_road_generation/test_junction_graphset_v1_governance.py`

首次测试后的补充写入前再次复查，体量分别为 21,985 bytes 和 6,542 bytes，均未达到
100KB 硬阈值；最终体量分别为 22,116 bytes 和 6,890 bytes。

历史文件保持只读：

- `target_a_network.py`：83,188 bytes；
- `target_a_t05_anchor_dataset.py`：81,185 bytes；
- `target_a_junction_joint_training.py`：69,897 bytes。

本阶段未新增正式 CLI、入口脚本或对外接口。
