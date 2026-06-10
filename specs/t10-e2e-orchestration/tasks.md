# T10 端到端业务流程编排任务清单

## Specify

- [x] 确认项目级主业务链保持 `T08 -> T01 -> T07 -> T03 -> T04 -> T05 -> T06 -> T09`。
- [x] 确认 T10 v1 编排范围为 `T01 -> T07 -> T03 -> T04 -> T05 -> T06 -> T09`。
- [x] 确认 T08 是独立前置质量模块，不由 T10 v1 调用。
- [x] 确认 Case 证据包以 SWSD 语义路口 ID 与半径表达范围。
- [x] 确认 CaseID 不是坐标替代物，坐标只作为 CaseID 派生范围信息。
- [x] 确认 `suggest` 是候选生成，不是问题真实性判定。
- [x] 确认多个 CaseID 可一次输入，输出按 CaseID 分目录。
- [x] 确认 Case 证据包纳入外部输入，不纳入模块间中间产物。
- [x] 确认 T10 Case Runner 受控支持 `T01 -> T07 -> T03 -> T04 -> T05 -> T06 -> T09` Case 级执行。
- [x] 确认 T10 仍不调用 T08、不修改 T01-T09 算法。

## Plan

- [x] 定义 Product / Architecture / Development / Testing / QA 视角。
- [x] 定义 T10 v1 外部输入 slot。
- [x] 定义 T10 v1 模块间 handoff slot。
- [x] 定义目录型 handoff 拒绝策略。
- [x] 定义 `suggest` 从 SWSD nodes inventory 和 selector evidence 生成候选的规则。
- [x] 定义多 Case 目录与文本分片 / 解包规则。
- [x] 定义并登记 T10 root 打包入口与 Case runner 执行入口。
- [x] 定义 T06 数据漏斗输出规则。

## Implement

- [x] 新增 T10 SpecKit 工件。
- [x] 新增 T10 模块文档面。
- [x] 新增 T10 模块内 contracts。
- [x] 新增 T10 workflow plan / handoff audit callable。
- [x] 新增 T10 Case suggestion callable。
- [x] 新增 T10 Case evidence package manifest callable。
- [x] 新增 T10 multi-case evidence package callable。
- [x] 新增 T10 text bundle split/decode callable。
- [x] 同步项目级模块登记。
- [x] 新增 dependency-aware Case 空间切片，补齐道路端点节点依赖。
- [x] 新增 T10 Case Runner callable。
- [x] 新增并登记 `scripts/t10_run_e2e_cases.sh`。
- [x] 新增 T06 funnel JSON/CSV/MD 输出。
- [x] 测试 Case runner 在阶段失败后阻断同一 Case 下游阶段。
- [ ] 后续收敛 T03 / T04 CaseID 显式选择能力。

## Test

- [x] 测试 T10 v1 链路不包含 T08。
- [x] 测试目录型 handoff 被拒绝。
- [x] 测试 selector evidence 映射到 SWSD 语义路口 CaseID。
- [x] 测试无 selector evidence 时只输出 inventory-only。
- [x] 测试 Case evidence package 只纳入外部输入。
- [x] 测试多 Case bundle 分片和解包后按 CaseID 恢复目录。
- [x] 测试真实 GPKG 空间切片物化。
- [x] 测试空间切片补齐道路端点节点依赖。
- [x] 增加 Case runner 受控失败阻断测试。
- [x] 用当前已解包 Case package 执行 991176 / 74155468 并产出 T06 阻断解读。

## QA

- [x] CRS：v1 明确 Case 范围 CRS 为 `EPSG:3857`，记录输入 CRS 与输出 CRS。
- [x] 拓扑：v1 不 silent fix，空间切片补齐道路端点节点依赖并审计缺失。
- [x] 几何语义：v1 Case 范围由 SWSD 语义路口 ID 与半径表达。
- [x] 审计：v1 输出 workflow plan、handoff audit、summary 和 Case manifest。
- [x] 性能：v1 summary 记录 contract validation、Case package 计数、stage duration 与 T06 漏斗计数。
- [ ] 完成 991176 / 74155468 Case runner 实跑后的性能和质量解读。
