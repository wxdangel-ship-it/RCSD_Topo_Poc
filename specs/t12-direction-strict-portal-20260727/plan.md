# Implementation Plan：T12 direction-strict portal

## 产品

- 质量结果以准确率为主，排除因反向 Road 端点混入正向 portal 集合产生的假 `directed_carrier_missing`。
- 保持最终问题自动确认，不引入人工复核前置条件。
- 每条失败方向必须能解释是 portal 覆盖、Road direction、canonical endpoint 还是后续链路问题。

## 架构

- 保留 canonical/raw 双图与现有三层 carrier，不改变入口和输入。
- `GraphBundle.outgoing_nodes/incoming_nodes` 成为 portal 方向角色的唯一图资格来源。
- raw 和 semantic 搜索继续使用 directed adjacency；undirected adjacency 只用于诊断。
- 方向覆盖审计以加法字段进入 candidate/evidence，不改变 FRCSD。

## 研发

- `candidate_audit.py` 按方向分别使用 raw local graph 的 outgoing/incoming node 集合。
- `anchor_portals.py` 校验 `direction_role` 与传入资格集合，并输出明确 portal source/role。
- 如当前数据证明正确方向 Road 已进入 local graph 但仍不可达，再在独立小模块中实现方向严格的 anchor frontier 扩展；不得在证据不足时猜测扩展规则。
- 不新增入口、参数或依赖。

## 测试

- 单元测试覆盖 start 仅入边、start 有出边、end 仅出边、end 有入边、双向 Road、`direction=2/3`。
- 构造同走廊正反向平行 Road，证明两个 SWSD 必需方向分别选择合法 Road。
- 验证无向反向 Road只能产生诊断，不能成为等价 carrier。
- 运行全部 T12 测试、T10+T12 受影响测试、对象 ID 扫描和 `git diff --check`。
- 使用 `1026960` 原始数据验证冻结 35/10/25/0 与 10 条集合。

## QA

- CRS：沿用 metre-based projected CRS 和显式转换审计。
- 拓扑：只读 Road endpoint/Node alias；缺 endpoint 继续硬阻断。
- 几何：local corridor 与 path geometry 保持原逻辑，不修复几何。
- 追溯：每方向记录 portal role、候选 Road、路径和拒绝原因。
- 性能：方向资格直接复用已建 graph node 集合，不新增全图扫描。

## 兼容与风险

- 不改变官方入口，不更新 entrypoint registry。
- portal 资格收紧可能改变候选或 confirmed 集合；任何基线变化都必须数据审计，不能刷新 fixture 迎合实现。
- 当前内网 `5885111744069971` 原始端点与 Node alias 尚未在本机取得；本地实现只能把已确认的 role-filter 缺口标记为已修复，该内网对象仍须重跑验证。
