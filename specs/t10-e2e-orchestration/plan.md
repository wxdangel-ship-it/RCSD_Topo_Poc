# T10 端到端业务流程编排实施计划

## 1. 实施策略

本轮采用“先契约化，再执行化”的策略：

1. 冻结 T10 v1 的编排范围：`T01 -> T07 -> T03 -> T04 -> T05 -> T06 -> T09`。
2. 明确 T08 是独立前置质量模块，不由 T10 v1 调用。
3. 新增 T10 模块文档面和模块内 callable runner。
4. 先解决文件级 handoff 审计，拒绝目录型消费。
5. 建立 CaseID 语义：CaseID 是 SWSD 语义路口 ID，坐标只是派生范围信息。
6. 建立 Case suggest：从 SWSD nodes inventory 和 selector evidence 生成候选。
7. 建立 Case 证据包 manifest，先保证“外部输入全集”和“中间产物排除”边界正确。
8. 建立多 Case 分目录、文本 bundle 自动分片和解包重组能力。

## 2. 写集

本轮预计新增 / 修改：

- `specs/t10-e2e-orchestration/spec.md`
- `specs/t10-e2e-orchestration/plan.md`
- `specs/t10-e2e-orchestration/tasks.md`
- `modules/t10_e2e_orchestration/**`
- `src/rcsd_topo_poc/modules/t10_e2e_orchestration/**`
- `tests/modules/t10_e2e_orchestration/**`
- 项目级模块登记文档

不修改：

- `docs/repository-metadata/entrypoint-registry.md`
- `Makefile`
- `scripts/`
- `src/rcsd_topo_poc/cli.py`

## 3. 模块结构

```text
modules/t10_e2e_orchestration/
├── AGENTS.md
├── INTERFACE_CONTRACT.md
├── README.md
└── architecture/
    ├── 01-introduction-and-goals.md
    ├── 02-constraints.md
    ├── 03-context-and-scope.md
    ├── 04-solution-strategy.md
    ├── 05-building-block-view.md
    ├── 10-quality-requirements.md
    ├── 11-risks-and-technical-debt.md
    └── 12-glossary.md

src/rcsd_topo_poc/modules/t10_e2e_orchestration/
├── __init__.py
├── contracts.py
├── orchestrator.py
└── evidence_package.py

tests/modules/t10_e2e_orchestration/
└── test_t10_contracts.py
```

## 4. 关键设计

- 用稳定 slot 表达外部输入和模块间 handoff。
- `external_inputs` 只表达 T10 外部输入，包括 T08 独立运行后的成果。
- `handoffs` 只表达 T01-T09 模块间产物。
- T05 / T06 / T09 这类后置模块不得只消费前序目录，必须配置到具体文件。
- Case 证据包 v1 只纳入外部输入；中间产物只在 manifest 中列为 excluded handoff，避免把过程产物误当外部证据。
- `suggest` 读取 `prepared_swsd_nodes` 建立语义路口 inventory；selector evidence 只用于打包候选选择，不进入 Case payload。
- 多 Case 包固定使用 `cases/<case_id>/` 目录结构；文本分片只影响传输，不改变解包后的结构。

## 5. 风险与后续

- T09 当前缺少标准模块文档面，且现有实现与项目级“消费 T06 F-RCSD 承载关系”的口径仍需进一步对齐。
- T05 工作区已有未提交改动，涉及 Phase2 `swsdnode_out / yes_nr` 输出链路，本轮不回退该改动。
- v1 不执行真实空间切片；后续需要把 Case 范围从 manifest 升级为可物化的空间切片包。
- `suggest` 当前通过通用字段匹配 selector evidence，后续需要沉淀模块级 selector schema。
- v1 不调用各模块 runner；后续需要在不新增入口或经授权新增入口的前提下接入执行编排。

## 6. 验证

- `.venv/bin/python -m pytest tests/modules/t10_e2e_orchestration`
- `git diff --check`
- 手工复核项目级主业务链仍保留 T08。
- 手工复核 `entrypoint-registry.md` 未新增 T10 入口。
