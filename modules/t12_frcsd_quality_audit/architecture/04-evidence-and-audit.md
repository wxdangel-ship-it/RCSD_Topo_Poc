# 04 Evidence And Audit

## 1. 证据分层

- candidate：算法发现的待复核疑点。
- review-only：外部复核决定、排除理由和 manual 队列。
- formal：confirmed CSV/GPKG 与 summary 中的确认计数。
- internal：carrier/portal GPKG、T06/DriveZone 交叉证据和运行日志。

## 2. Formal 成果

`t12_frcsd_confirmed_quality_issues.*` 只含 confirmed。任何自动候选、概率标签或未复核行都不得进入。

## 3. 运行审计

- 输入：绝对路径、size、SHA-256、CRS。
- 参数：portal/local/path/crop 全部阈值。
- 拓扑：Road/Node 数量、缺失 endpoint、`silent_fix=false`。
- 证据关系：T06 Step2 指向的 T05 Phase2 目录必须与所给 anchor audit 同批。
- 性能：对象规模、分阶段和总耗时、Python/GIS 库环境。

## 4. 下游交接

T10 在 T11 后、T09 前记录 T12 输出位置和状态；该顺序不表示 T12 消费 T11 输出。T12 不成为 T11/T09 的业务输入，也不改变 T06 F-RCSD 文件。
