# T10 端到端业务流程编排规格

**状态**：Implementation baseline / v1 启动
**Scope Mode**：SpecKit implement
**Source Fact Status**：本文件是变更工件，不替代项目级或模块级 source-of-truth。正式事实同步到 `modules/t10_e2e_orchestration/*` 与项目治理文档。

## 1. 背景

当前项目已形成 `T08 -> T01 -> T07 -> T03 -> T04 -> T05 -> T06 -> T09` 主业务链。T08 是独立预处理与质量修复模块，提供 SWSD / RCSD 输入规范化、质检、修复、restriction / Laneinfo 显性化等能力。

T10 本轮启动为端到端编排模块。按用户确认，项目级主业务链保持不变；T10 v1 的编排范围单独定义为：

```text
T01 -> T07 -> T03 -> T04 -> T05 -> T06 -> T09
```

T08 不由 T10 v1 调用，T10 只消费已准备好的外部输入或 T08 独立运行成果。

## 2. 产品视角

T10 需要解决两个问题：

1. 把 T01 / T07 / T03 / T04 / T05 / T06 / T09 连接成可审计的端到端业务链。
2. 以 SWSD 语义路口 ID 和半径为输入，形成 Case 级证据包，帮助从 T05 / T06 / T09 的后置异常向前追溯到所有外部输入。

T10 v1 先建立编排契约与文件级 handoff 约束，重点修正“下游按结果目录消费上游成果”的不稳定设计。T10 v1 对 T05 等后置模块要求明确到具体文件，而不是只传模块 run root。

## 3. 架构视角

T10 v1 不替代各模块 runner，不修改 T01-T09 的业务算法。它提供三个稳定能力：

- `workflow plan`：声明 T10 v1 链路、每个阶段的输入输出 slot 与 T08 独立运行边界。
- `handoff audit`：检查外部输入与模块间产物是否以显式文件路径配置，拒绝目录型 handoff。
- `case suggestion`：从 SWSD nodes 建立语义路口 inventory，并用可选 selector evidence 生成候选 Case 列表。
- `case evidence package manifest`：以 SWSD 语义路口 ID 与半径声明 Case 范围，列出全量外部输入，排除模块间中间过程产物。

T10 v1 的 Case 包只纳入外部输入清单：

- `prepared_swsd_nodes`
- `prepared_swsd_roads`
- `drivezone`
- `divstripzone`
- `rcsd_intersection`
- `rcsdroad`
- `rcsdnode`
- `sw_restriction_tool7`
- `sw_arrow_tool8`

T01 / T07 / T03 / T04 / T05 / T06 / T09 之间的中间成果只进入 handoff audit，不进入 Case 外部输入证据包。

CaseID 的正式含义是 SWSD 语义路口 ID，不是坐标。坐标只作为从 CaseID 对应 member node geometry 派生出的范围中心信息。

`suggest` 不判定问题真实性。没有 selector evidence 时，`suggest` 只能输出 `inventory_only` 语义路口清单；有 T08/T05/T06/T09 等 selector evidence 时，按 `target_id/mainnodeid/node_id` 等字段映射回 SWSD 语义路口，输出 `problem_candidate`。

多 Case 输入必须支持一次输入多个 CaseID，输出按 `cases/<case_id>/` 分目录组织；文本传输包超过阈值时自动分片，解包后必须恢复该目录结构。

## 4. 研发视角

本轮实现范围：

- 新增 `modules/t10_e2e_orchestration/` 模块文档面。
- 新增 `src/rcsd_topo_poc/modules/t10_e2e_orchestration/` 模块内 callable 能力。
- 新增 `tests/modules/t10_e2e_orchestration/` 聚焦测试。
- 同步项目级模块登记，但不改变项目级主业务链。

本轮不新增 repo CLI 子命令、root `scripts/`、`Makefile` 目标、模块 `run.py` 或模块 `__main__.py`。

## 5. 测试视角

最小测试覆盖：

- T10 v1 链路为 `T01-T07-T03-T04-T05-T06-T09`，不包含 T08。
- 文件级 handoff 完整时 contract validation 通过。
- `t05_phase2_root` 等目录型 handoff 被拒绝。
- `suggest` 可从 SWSD nodes inventory 和 selector evidence 生成候选 Case。
- Case 证据包 manifest 包含全量外部输入 slot。
- Case 证据包 manifest 排除 T01-T09 模块间 handoff。
- 多 Case 文本 bundle 可自动分片并解包恢复 `cases/<case_id>/`。

## 6. QA 视角

T10 属于 GIS / 拓扑 / 空间数据相关编排任务，v1 closeout 必须覆盖：

- **CRS 与坐标变换正确性**：v1 Case 范围声明固定为 `EPSG:3857`；实际空间切片执行留作后续任务，不做 silent assumption。
- **拓扑一致性**：v1 不修补拓扑，只审计缺失或目录型 handoff。
- **几何语义可解释性**：Case 范围由 SWSD 语义路口 ID 与半径表达。
- **审计可追溯性**：所有外部输入与模块间产物都有稳定 slot。
- **性能可验证性**：v1 记录 contract validation 计数与 Case 包文件数，运行级耗时留给后续执行编排。

## 7. 非目标

- 不改变项目级主业务链。
- 不让 T10 v1 调用 T08。
- 不把 T10 v1 变成新的 repo CLI 或脚本入口。
- 不修改 T01-T09 业务算法。
- 不补齐 T09 模块文档面；该缺口作为 T10 风险记录。
- 不在 v1 中实现真实空间切片和全量内网执行。
