# Spec：T12 anchored canonical alias raw portal

## 1. 产品目标

T12 审计原始 1V1 FRCSD 时，1V1/T05 锚定对象可以是 FRCSD mainNode，而实际 Road 连接其 subNode/alias。只将选中 `base_id` mainNode 的 canonical group raw node 展开为实际 Road endpoint portal；其它显式 grouped raw node 保留但不递归扩组。随后严格按照 Road `Direction` 跟踪 raw carrier，避免把 alias 几何距离或标准面位置误判为 FRCSD 通行缺失。

## 2. 用户授权

用户于 2026-07-27 明确授权：

> 授权更新 T12 正式源事实，并将已锚定 mainNode 的 canonical raw alias group 提升为 Direction 严格的 raw portal。

## 3. 业务规则

1. `mainNodeId/subNodeId` 只定义选中 `base_id` mainNode canonical group 的成员关系，不直接证明任意两点可通行。
2. 选中 `base_id` 所属 canonical group 的全部 raw node可以进入 anchored raw portal 候选；其它显式 grouped raw node保留，但不得递归展开其各自 canonical group。
3. source portal 必须在当前 raw local directed graph 中存在 outgoing Road；target portal 必须存在 incoming Road。
4. 正式 raw carrier 必须沿实际 raw Road endpoint 和 Road `Direction` 连续跟踪；canonical 零长度折叠不能替代物理 Road。
5. anchored alias 与 SWSD portal 或 RCSDIntersection 标准面的距离只作审计，不作为 raw portal 拒绝理由。
6. 非 anchored canonical group 的 spatial portal 仍执行既有半径/标准面门禁，不得借此接入附近无关 Road。
7. 无向图仅用于诊断，不得成为等价 carrier。
8. 禁止 Case、Segment、Road 或 Node ID 特判。

## 4. 产品视角

- 最终 confirmed 只保留在 anchored raw alias group、严格方向 raw carrier、既有 semantic/surface 排除后仍无法解释的高置信问题。
- candidate 可以继续存在；存在等价 anchored raw carrier 时必须进入 excluded。
- 不覆盖旧 run，不修改输入，不执行 silent fix。

## 5. 架构视角

- `build_node_context()` 继续提供 raw→canonical 映射和 canonical groups。
- `candidate_audit` 将 canonical groups 显式传入 raw portal 构造。
- `raw_portal_candidates` 分离 anchored alias 与 spatial fallback：
  - anchored alias：selected base canonical group 成员、Direction role 强过滤、距离审计；
  - spatial fallback：既有范围约束、Direction role 强过滤。
- raw graph 保持 identity node，不在路径中折叠 main/sub node。

## 6. 研发视角

- 最小修改 `anchor_portals.py`、`candidate_audit.py`、必要的输出审计和测试。
- 不新增入口、不改变 CLI 参数、不修改 T01–T11。
- 输出增加 anchored alias 来源与距离审计的可追溯信息时升级 schema。

## 7. 测试视角

- mainNode 锚定、正确 forward Road 连接远距离 subNode、反向平行 Road 位于 spatial 半径内：正向必须选择正确 subNode。
- 正反方向使用不同 raw alias/Road 时分别可达。
- 非锚定 canonical group 的远距离 spatial node 仍不得进入。
- 反向 Road 不得进入正向 directed carrier。
- T12 与 T10+T12 全量自动化测试通过。

## 8. QA 视角

- `1026960` 冻结基线保持 candidates=35、confirmed=10、excluded=25、manual=0，确认 Segment 集合完全一致。
- CRS、无效几何、endpoint 完整性、`silent_fix=false`、输入指纹和性能审计保持完整。
- 完整内网目标 Segment 必须在用户环境以同版本输入只重跑 T12 验证；本地结果不能替代。

## 9. 验收标准

- 已锚定 canonical alias 不受距离/标准面位置硬拒绝。
- raw carrier 严格按实际 raw endpoint 与 Road Direction 构造。
- 非锚定 spatial fallback 不放宽。
- 无生产对象 ID 硬编码。
- `1026960` 冻结基线无回归。
