# 04 Evidence And Audit

## 1. 证据分层

- candidate：canonical 图发现的宽召回疑点。
- decision：raw endpoint carrier、portal-constrained semantic carrier 的端点/内部 alias 门禁、标准路口 portal、锚点可信度、自动确认或排除理由。
- review-only：可选外部 QA 覆盖、来源和时间。
- formal：confirmed CSV/GPKG 与 summary 中的确认计数。
- internal：raw/canonical/portal-constrained semantic carrier/portal GPKG、T06/DriveZone 交叉证据和运行日志。

## 2. Formal 成果

`t12_frcsd_confirmed_quality_issues.*` 只含自动高置信或外部 override confirmed。任何仅 canonical 候选、概率标签或锚点信用不足行都不得进入。

## 3. 运行审计

- 输入：绝对路径、size、SHA-256、CRS。
- 参数：portal/local/path/crop 全部阈值。
- 拓扑：Road/Node 数量、缺失 endpoint、`silent_fix=false`。
- 证据关系：T06 Step2 指向的 T05 Phase2 目录必须与所给 anchor audit 同批。
- 性能：对象规模、分阶段和总耗时、Python/GIS 库环境。

## 4. 下游交接

T10 在 T11 后、T09 前记录 T12 输出位置和状态；该顺序不表示 T12 消费 T11 输出。T12 不成为 T11/T09 的业务输入，也不改变 T06 F-RCSD 文件。
