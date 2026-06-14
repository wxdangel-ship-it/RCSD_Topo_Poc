# 2026-06-14 T07 has_evd evidence 边界容差

## 背景

Case `1885118` 中 `14541129_26162515` 与 `14541129_47115534` 没有进入 T06 Step2。T06 Step1 的直接拒绝原因是 `has_evd_not_yes`，对应端点 `14541129` 在 T07 final nodes 中保持 `has_evd = no / is_anchor = NULL`。

## 根因

T07 Step1 采用语义组全员命中口径。`14541129` 语义组包含 `1882087 / 14541129 / 14541131` 三个 SWSD node；其中代表 node `14541129` 与从属 node `1882087` 均落在 `DriveZone ∪ RCSDIntersection` 内，但从属 node `14541131` 距 RCSDIntersection 合并 evidence 面约 `1.279m`，未严格 intersects/touches，导致整个语义组被写为 `has_evd = no`。

该问题不是 T06 Segment 构建兜底缺失，也不是字段语义问题；它是 T07 Step1 对米级面边界偏差过严，使后续 T07 Step2、T05 relation 和 T06 Step1 都没有机会消费该语义路口。

## 业务逻辑变更

T07 Step1 保持“组内所有 node 必须命中 evidence”的主规则，但将单点命中从严格 `intersects/touches` 扩展为：

- 优先使用严格空间命中；
- 严格未命中时，若 node 到 `DriveZone ∪ RCSDIntersection` 合并 evidence 面距离不超过 `1.5m`，视为 evidence 边界容差命中；
- 超过 `1.5m` 的组内任一 node 仍会使代表 node `has_evd = no`。

该变更只处理空间面边界微小错位，不新增输入字段，不改变 `kind_2` 处理范围，不跳过 T07 Step2 的 RCSDIntersection anchor 判定。

## 探针结果

在四个 T10 Case 原始输入上评估：

- `1.0m` 容差新增 `10` 个 `has_evd=yes` 语义路口，但不覆盖 `14541129`。
- `1.5m` 容差新增 `16` 个，其中包含 `14541129`，且最大新增距离均不超过 `1.5m`。
- `2.0m` 容差新增 `21` 个，影响面明显扩大。

因此本轮选择 `1.5m`，作为覆盖 `14541129` 的最小稳定容差。

## 质量约束

- CRS：T07 输入统一归一到 EPSG:3857，容差单位为米。
- 拓扑一致性：只更新代表 node 的 `has_evd` 判定，不修改道路拓扑，不做 silent topology repair。
- 几何语义：容差只表达 evidence 面边界微小错位，不表达远距离道路联通。
- 审计追溯：T07 Step1 summary 写入 `params.has_evd_evidence_tolerance_m = 1.5`。
- 性能：容差只在严格命中失败时计算一次点到合并 evidence 面距离，对当前 Case 规模影响可忽略。

## 验证

- 单元测试补充边界外 `1.2m` 的 `kind_2=4` representative node，确认 Step1 写 `has_evd=yes`，并确认 summary 记录容差参数。
- 待复跑 Case `1885118`，验证 `14541129` 相关 Segment 是否进入 T06 Step2，并继续判断是否能构建 RCSD Segment。
