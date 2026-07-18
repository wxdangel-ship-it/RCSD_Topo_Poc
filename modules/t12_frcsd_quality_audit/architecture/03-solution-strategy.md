# 03 Solution Strategy

## 1. 策略总览

T12 先用 base-node 图检查筛出疑点，再以完整节点组和空间 portal 构造多源多目标最短路，比较局部/全图、有向/无向 carrier。自动结果只形成候选，外部复核决定最终发布。

## 2. 预检与建图

- 校验文件、字段、CRS、几何和 endpoint；记录输入 SHA-256。
- 复用 T06 的 `NodeCanonicalizer`、ID 解析和 direction 语义，不复用 T06 替换判定。
- 图边按 Road ID 稳定排序，零长度同节点路径视为可达。

## 3. Anchor portal 与 carrier

- T07 anchor 合并 RCSDIntersection 与 T05 grouped node；其它 anchor 也合并 FRCSD 语义节点组。
- 默认在 SWSD carrier 端点 `50m` 内查找空间 portal；start 必须有出边、end 必须有入边。
- 路径必须满足长度比例、绝对增量和最大走廊偏离三项阈值。

## 4. 候选与复核

- local directed 失败、local undirected 成功，建议 `directed_carrier_missing`。
- local directed/undirected 都失败，建议 `required_local_connectivity_missing`。
- portal 找到等价 carrier 时保留解释证据，等待复核排除；生产算法不按对象 ID 特判。
- review CSV 严格 join 当前 run/candidate，缺失决定进入 manual。

## 5. 实现分层

- `inputs.py`：输入、CRS、拓扑和证据派生链。
- `carrier_graph.py / anchor_portals.py`：图与门户。
- `candidate_audit.py`：候选和空间证据。
- `review_publish.py / outputs.py`：复核合同和发布。
- `runner.py`：阶段编排与性能审计。

## 6. 性能与观测

全图只建一次；每个候选只建 50m local graph。summary 记录对象规模及 loading/candidate/review/output 分段耗时。
