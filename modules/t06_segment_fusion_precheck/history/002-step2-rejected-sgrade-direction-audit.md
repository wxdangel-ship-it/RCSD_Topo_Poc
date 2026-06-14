# 002 - Step2 rejected 高等级与方向审计补全

- 日期：2026-06-11
- 模块：T06 Segment fusion precheck
- 变更类型：Step2 输出审计增强

## 背景

T10 高等级单向 Segment 分析需要区分 `kind` 等级对应的 `swsd_sgrade` 与单 / 双向属性。Step2 `replaceable` 输出已经携带 `swsd_sgrade / swsd_directionality`，但 `rejected` 输出此前只记录拒绝原因与失败节点，导致高等级阻断分析必须回查 T01 `segment.gpkg` 才能获得同一 Segment 的等级与方向上下文。

这会降低 T10 数据漏斗的自解释性，也容易在统计中把空等级误计为高等级。

## 业务逻辑变更

Step2 在写出 `t06_rcsd_segment_rejected.*` 前，统一为 rejected 行补充：

- `swsd_sgrade`：来自 Step1 fusion unit 或 T01 Segment 的既有 `sgrade`。
- `swsd_directionality`：继续复用 T06 已有 `directionality_from_sgrade` 规则，派生为 `single / dual / unknown`。

该变更只增强拒绝审计输出，不改变：

- Step1 eligibility；
- T05 relation 映射；
- buffer candidate graph 构建；
- single/dual 方向硬审计；
- replaceable 判定；
- Step3 替换输出。

## 质量与审计

- CRS 与坐标变换：不读取几何，不改变 CRS 处理。
- 拓扑一致性：不执行 silent fix，不修改 retained graph。
- 几何语义：只复用 Segment 已有等级与方向文本，不推断新的道路属性含义。
- 审计可追溯性：rejected 行可独立支撑高等级 / 单向阻断统计，无需额外回查 T01。
- 性能可验证性：写出前按 Segment id 做一次内存字典回填，复杂度与 Step2 输入 Segment 数量线性相关。

## 验证

- 单元测试覆盖 `swsd_pair_nodes_not_distinct` rejected 行必须输出 `swsd_sgrade=主单` 与 `swsd_directionality=single`。
- T10 direct full run 后可直接从 Step2 rejected 输出统计高等级单向阻断。
