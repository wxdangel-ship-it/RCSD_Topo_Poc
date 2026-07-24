# 1885118 第二里程碑 Road 支持分析

## 1. 分析目标

本分析在第一里程碑最终 run `p04_m1_1885118_20260720T235000` 上执行，目标不是先写 Road 生成代码，而是回答三个问题：

1. 哪类 Lane 证据可以用于 Road 纵向支持；
2. 整 Lane primary owner 是否足以表达 SWSD-first Road fitting；
3. 四态和几何实例化应采用什么 POC 参数，并且哪些结论仍不能升级为生产规则。

分析使用 `EPSG:32650`。完整工件位于：

- `outputs/_work/p04_road_direct_generation/1885118/p04_m2_support_analysis_owner_exact_20260721T001/`
- `outputs/_work/p04_road_direct_generation/1885118/p04_m2_local_assignment_analysis_20260721T002/`
- strict/loose/8m 敏感性 run 位于相邻同名前缀目录。

## 2. 输入质量与 Road 冲突解耦复核

第一里程碑逐对象结果复算得到：

| 输入质量类别 | 数量 | 第二里程碑处理 |
|---|---:|---|
| 跨 Road 语义节点异常 | 5 | 独立 LaneTopo QA |
| 跨 Road 方向复核 | 29 | 独立 LaneTopo QA |
| 窄 Lane | 8 | 独立宽度 QA |
| 宽度/Boundary-gap | 131 | 独立宽度 QA |
| 宽度不稳定 | 133 | 独立宽度 QA |
| Patch `5417631180197930` Boundary 资料不足 Lane | 67 | 独立资料完整性 QA |

上述计数与用户确认一致。分析阶段由这些质量标记产生的 Road `conflict_retained` 为 0；质量标记可以影响证据质量摘要和人工复核，但不能直接改变 Road 结构冲突状态。

## 3. 整 Lane owner 的局限

若继续使用第一里程碑整 Lane primary owner：

| Lane 口径 | Lane 数 | 有证据 Road | `hp_supported` | `partial_hp_supported` | `sd_only` |
|---|---:|---:|---:|---:|---:|
| 最终 decision=accepted | 1445 | 286 | 10 | 276 | 285 |
| owner accepted + Road 面覆盖 | 1788 | 342 | 20 | 322 | 229 |
| owner accepted | 1806 | 351 | 21 | 330 | 220 |

这里的四态采用原始投影区间、无外扩、全覆盖阈值 0.95、最大缺口 10m。1806 条 owner accepted Lane 的投影单调性 p10/p50/p90 均为 1.0，但有 12 条 Lane 的投影跨度/自身长度低于 0.6；部分 Lane 比其 primary SWSD Road 更长，说明一条原始 Lane 可以跨多个 SWSD 语义 Road。把整 Lane 强制给一个 owner 会把相邻 Road 错误留成 `sd_only`，仍然接近旧 LaneGroup 聚合思路。

## 4. SWSD 约束下的 Lane 局部分段

第二轮分析沿每条 Lane 每 5m 采样，对每个样点使用 Patch membership、20m 距离、35°方向门禁构建 SWSD Road 候选，再以同 Road连续和相邻语义节点转移代价求取全 Lane 最小代价路径。原始 Lane 不切写、不改 ID，只产生可追溯 `LaneEvidenceSegment`。

基线结果：

- 27025 个 Lane 样点中 26618 个获得局部 SWSD fit，覆盖 98.494%；407 个无局部 fit 样点保留 QA。
- 形成 2575 个 LaneEvidenceSegment，2155/2188 条 Lane 至少形成一个片段。
- 361 条 Lane 贡献给多个 SWSD Road，最多跨 7 个 Road；切换中 397 个发生在共享 SWSD 语义节点，18 个为不相邻切换并单独进入 QA，不用于推断 RoadNextRoad。
- 已匹配样点到 SWSD 参考线距离 p50/p90/p95/p99 为 2.21/6.29/7.96/12.08m；方向差 p50/p90/p95/p99 为 1.04/4.99/8.50/22.85°。
- 571 条 Road 中 433 条获得局部 Lane 证据，比整 Lane owner accepted 增加 82 条。

## 5. 参数敏感性

| 参数组 | 已匹配样点 | Lane 片段 | 跨多 Road Lane | `hp_supported` | `partial_hp_supported` | `sd_only` |
|---|---:|---:|---:|---:|---:|---:|
| strict：15m/30°/5m | 26429 | 2560 | 357 | 76 | 358 | 137 |
| baseline：20m/35°/5m | 26618 | 2575 | 361 | 77 | 356 | 138 |
| loose：25m/45°/5m | 26725 | 2574 | 356 | 78 | 358 | 135 |
| spacing：20m/35°/8m | 17848 | 2568 | 358 | 67 | 367 | 137 |

15-25m、30-45°范围内 Road 四态只变化 1-3 条，说明空间/方向门禁对当前 Case 稳定。8m 采样使完全覆盖判断少 10 条，5m 更适合区间边界和几何拟合。当前选用 5m、20m、35°作为 POC 参数，不升级为生产阈值。

## 6. 第二里程碑实例化口径

本里程碑采用以下实现口径：

1. Road 目标对象始终是 571 条 SWSD Road，旧 Road/LaneGroup 不决定数量或连接。
2. 第一里程碑 whole-Lane primary owner 保留为诊断；Road fitting 使用 LaneEvidenceSegment，每个片段唯一 owner。
3. 所有 Lane 均可产生局部候选，但只有通过样点距离/方向门禁的片段形成 Road 支持；M1 宽度、Boundary、道路面和 owner 状态作为独立质量标记与拟合权重，不直接删 Road 或制造 conflict。
4. 支持区间使用实际 Lane 片段投影，不做任意外扩；Road 覆盖率至少 0.95 且最大缺口不超过 10m 时为 `hp_supported`，有支持但不满足时为 `partial_hp_supported`，无支持为 `sd_only`。
5. 当前没有证据足以把某条 Road 自动定为 `conflict_retained`，因此真实 Case 允许该状态为 0；状态机仍需用合成测试覆盖可信结构冲突。
6. 支持区间几何用 Lane 横向位置的稳健统计拟合；缺口区间保留 SWSD 几何，所有片段记录 `hp_fitted/swsd_retained` 来源并禁止 silent fix。

按基线局部分段口径，候选四态为：`77 hp_supported + 356 partial_hp_supported + 138 sd_only + 0 conflict_retained = 571`。这是第二里程碑的单 Case POC 基线，不是最终生产验收阈值。

实现阶段排除了零长度投影支持，并增加 Road 端点/Arm 门户锚定；权威 run 的最终四态为 `77 + 355 + 139 + 0 = 571`。最终结果与门禁见 `1885118-milestone2-results.md`，本文件保留参数选择前的分析基线，不回写历史分析值。
