# T04 Module Optimization Spec

## 1. Scope

本 SpecKit 任务覆盖 `t04_divmerge_virtual_polygon` 的需求、架构、编码质量、测试与 QA 优化。

本轮不改变 T04 业务口径，不新增 repo 官方 CLI，不改变 Step7 二态最终状态机，不以重构名义刷新业务基线。

## 2. Role Audit Summary

### Product

- `no_surface_reference` 已在模块源事实中定义为防御性异常兜底，不能作为“无主证据 + 无 RCSD 语义路口”的正常业务分支。
- 新增 6 case 当前测试已经硬化为 accepted gate；对应 spec 中的 `SHOULD` 口径需要收敛为当前基线事实，或测试需改成 guard-aware。当前实现选择保持测试 gate。
- 原 30 case 不仅要保持 final state，还要保持关键语义字段：主证据、Reference Point、RCSD/SWSD section reference、surface scenario、Step6 guards、nodes 写回。

### Architecture

- 当前架构分层基本成立，但 `support_domain.py` 与 `step4_road_surface_fork_binding.py` 已接近 100 KB 硬阈值。
- `support_domain.py` 同时承载 Step5 config、geometry helper、unit/case result model、terminal/fill/bridge/builder，内聚不足。
- `step4_road_surface_fork_binding.py` 同时承载 dispatcher、promotion、window conversion、structure-only retention 与 event-unit replace，后续必须拆分。
- `code-size-audit.md` 的 T04 体量记录必须与实际代码同步。

### Development

- 优先采用机械拆分，不改变表达式和分支顺序。
- 第一优先级是从临界文件抽出纯配置、纯模型、纯 helper，避免继续在接近 100 KB 文件中追加。
- 中高风险算法优化必须先补测试，再改实现。

### Testing

- 当前 Step4/5/6/7 单元与真实 Anchor_2 回归较强，但缺少统一 39-case gate。
- 新增 6 case gate 已覆盖用户审计重点，但多 unit case 仍需进一步锁定所有 unit 的关键语义字段。
- 30-case gate 需要继续从 final-state 扩展到 semantic no-regression。

### QA

- 每轮优化必须覆盖 CRS、拓扑一致性、几何语义、审计可追溯性和性能可验证性。
- accepted surface 不得包含 `no_surface_reference`。
- 发布层 summary、audit、rejected index、nodes 写回和 review PNG 必须一致。

## 3. Baseline Requirements

- 原 Anchor_2 30 case 基线不得漂移。
- 新增 6 case 基线不得漂移。
- 当前 39 case 目视审计批次必须可重跑，并保留 `visual_audit_index.html`。
- `divmerge_virtual_anchor_surface.gpkg` 与 audit layer geometry 必须 valid。
- `nodes_anchor_update_audit.json` 与 Step7 final state 必须一致。

## 4. Non-Goals

- 不新增 T04 repo 官方 CLI。
- 不改变 T04 surface 主产物命名。
- 不把 RCSD/SWSD 语义路口伪造成主证据或 Reference Point。
- 不根据局部样本反推上游字段语义并固化为强规则。
- 不在同一轮内做大规模算法重写和视觉基线刷新。

## 5. Acceptance Criteria

- `support_domain.py` 和后续拆分目标均低于 100 KB。
- `code-size-audit.md` 同步记录实际体量。
- 模块架构文档登记新增子模块职责。
- 定向测试、原 30 case gate、新增 6 case gate 均通过。
- 39 case 批处理可完成，summary/audit/geometry/review 工件可追溯。
