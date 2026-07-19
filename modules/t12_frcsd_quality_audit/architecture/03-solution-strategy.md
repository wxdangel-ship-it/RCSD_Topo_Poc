# 03 Solution Strategy

## 1. 策略总览

T12 先用 canonical base-node 图检查宽召回疑点，再以 raw Road endpoint 图、标准路口面和实际接入 portal 构造多源多目标最短路，比较局部/全图、有向/无向 carrier。raw failure 还要经过 portal-constrained semantic carrier 排除检查；完成排除后仍失败且通过锚点可信度门禁的 candidate 才自动进入正式问题，外部复核仅作可选 QA 覆盖。

## 2. 预检与建图

- 校验文件、字段、CRS、几何和 endpoint；记录输入 SHA-256。
- 复用 T06 的 `NodeCanonicalizer`、ID 解析和 direction 语义，不复用 T06 替换判定；canonical 图用于候选筛选及受限 semantic 排除。
- 主判定另建 raw endpoint 图，不折叠 `mainNodeId/subNodeId`；图边按 Road ID 稳定排序。semantic 排除路径不得为零长度，并记录每个实际 raw endpoint transition。

## 3. Anchor portal 与 carrier

- T07 anchor 使用 T05 base/grouped raw node，并加入与该 SWSD 语义路口唯一关联的 RCSDIntersection 面内 raw node。
- T03/T04 默认在 SWSD carrier 端点 `50m` 内查找空间 raw portal；所有 start 必须有出边、end 必须有入边。
- 路径必须满足长度比例、绝对增量和最大走廊偏离三项阈值。

## 4. 候选与复核

- raw local directed 失败后，若 canonical local directed 物理 Road 路径通过原长度/增量/走廊阈值，且两端 portal 与内部 alias transition 全部受信，则按 `equivalent_portal_constrained_semantic_carrier` 排除该 raw 假断裂。T07 alias 端点只接受同一唯一标准路口面；非 T07 alias 端点和内部 alias transition 还必须在 `portal_radius_m` 内。
- 完成上述排除后，canonical local directed 仍失败而 canonical local undirected 成功时判为 `directed_carrier_missing`；其它未解决方向判为 `required_local_connectivity_missing`。多个失败方向中只要存在明确方向缺失证据，Segment 级类型优先为 `directed_carrier_missing`。
- 至少一端具有唯一 T07 标准面信用，或两端均为正式 T03 anchor 时，允许未解决失败自动 confirmed；其它失败按 `insufficient_anchor_confidence` 排除。
- raw portal 找到等价 carrier 时按 `equivalent_raw_carrier` 排除；生产算法不按对象 ID 特判。
- review CSV 严格 join 当前 run/candidate；缺失 review 行保留自动决定，显式行可以覆盖。

## 5. 实现分层

- `inputs.py`：输入、CRS、拓扑和证据派生链。
- `carrier_graph.py / anchor_portals.py`：图与门户。
- `semantic_carrier.py`：semantic 物理路径、端点 portal 与内部 alias transition 门禁。
- `candidate_audit.py`：候选和空间证据。
- `review_publish.py / outputs.py`：自动 decision、可选复核覆盖和发布。
- `runner.py`：阶段编排与性能审计。

## 6. 性能与观测

canonical/raw 全图各建一次；每个候选只查询并构建 50m local graph。summary 记录对象规模及 loading/candidate/decision/output 分段耗时。
