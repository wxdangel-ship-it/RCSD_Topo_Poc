# 04 Evidence And Audit

## 1. 证据分层

- candidate：canonical 图发现的宽召回疑点。
- decision：每方向 selected base canonical group 到 raw alias 的 membership、显式 grouped raw node、source outgoing/target incoming portal 资格、alias distance audit、非锚定 fallback、raw endpoint directed carrier、portal-constrained semantic directed carrier 的端点/内部 alias 门禁、标准路口 portal、FRCSD 反向载体、双端锚点区间、逐 raw RCSD Road 当前/其它 Segment 归属、SWSD 反向替代路径、锚点可信度、自动确认或排除理由；undirected path 只保留为诊断。
- review-only：可选外部 QA 覆盖、来源和时间。
- formal：confirmed CSV/GPKG 与 summary 中的确认计数。
- internal：raw/canonical/portal-constrained semantic/FRCSD 反向/SWSD 反向 carrier/portal GPKG、`unexpected_reverse_rcsd_ownership` 逐 Road 空间证据、T06/DriveZone 交叉证据和运行日志。
- Junction candidate：T03/T07 来源身份、正式 eligibility、association/Step6/Step7 状态、support 来源、target projection、endpoint support/global degree、support component、未匹配 component、Direction、局部替代 carrier、跨层与几何状态。
- Junction formal：独立 Point candidates/confirmed/exclusions；T07 N:1 逐 Junction 行共享 conflict group。
- Junction internal：support Road、FRCSD endpoint、target projection 与 T07 conflict link 空间层。

## 2. Formal 成果

`t12_frcsd_confirmed_quality_issues.*` 只含自动高置信或外部 override confirmed。任何仅 canonical 候选、概率标签或锚点信用不足行都不得进入。

`t12_frcsd_confirmed_junction_quality_issues.*` 只含 T03 原始 FRCSD 高置信复核通过或 T07 Step2 final `fail1/fail2` 稳定失败直接发布。T03 rejected 本身、最近距离、Step3 relation cardinality、无效几何、正式高置信跨层解释或证据不足不得进入。

## 3. 运行审计

- 输入：绝对路径、size、SHA-256、CRS。
- 参数：portal/local/path/crop 全部阈值。
- 拓扑：Road/Node 数量、缺失 endpoint、`silent_fix=false`。
- 证据关系：T06 Step2 指向的 T05 Phase2 目录必须与所给 anchor audit 同批。
- Junction 来源：T03/T07 run root、正式工件绝对路径与 SHA-256、T03 rejected case 列表、T07 Step2 final fail1/fail2 集合及其 evidence/summary 一致性。
- Junction 参数与拓扑：`6m` endpoint tolerance、`50m` local scope、support/global endpoint degree、component、Direction、替代 carrier 与 `silent_fix=false`。
- 性能：对象规模、分阶段和总耗时、Python/GIS 库环境。

## 4. 下游交接

T10 在 T11 后、T09 前记录 T12 Segment 与 Junction 输出位置和状态；该顺序不表示 T12 消费 T11 输出。T10 显式传入当前 T03 run root 与 T07 Step1/2 run root；T12 不依赖可选 Step3，不成为 T11/T09 的业务输入，也不改变 T06 F-RCSD 文件。
