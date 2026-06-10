# T10 端到端业务流程编排实施计划

## 1. 实施策略

本轮采用“契约化 + Case 级执行化”的策略：

1. 冻结 T10 v1 的编排范围：`T01 -> T07 -> T03 -> T04 -> T05 -> T06 -> T09`。
2. 明确 T08 是独立前置质量模块，不由 T10 v1 调用。
3. 新增 T10 模块文档面和模块内 callable runner。
4. 先解决文件级 handoff 审计，拒绝目录型消费。
5. 建立 CaseID 语义：CaseID 是 SWSD 语义路口 ID，坐标只是派生范围信息。
6. 建立 Case suggest：从 SWSD nodes inventory 和 selector evidence 生成候选。
7. 建立 Case 证据包 manifest，先保证“外部输入全集”和“中间产物排除”边界正确。
8. 建立多 Case 分目录、文本 bundle 自动分片和解包重组能力。
9. 升级 `spatial_slice` 为 dependency-aware：补齐道路端点节点并保留道路完整几何。
10. 新增 T10 Case Runner，从 Case package 串联 T01 / T07 / T03 / T04 / T05 / T06 / T09。
11. 输出 T06 数据漏斗，用于解释后置质量问题和前序 handoff 影响。

## 2. 写集

本轮预计新增 / 修改：

- `specs/t10-e2e-orchestration/spec.md`
- `specs/t10-e2e-orchestration/plan.md`
- `specs/t10-e2e-orchestration/tasks.md`
- `modules/t10_e2e_orchestration/**`
- `src/rcsd_topo_poc/modules/t10_e2e_orchestration/**`
- `tests/modules/t10_e2e_orchestration/**`
- 项目级模块登记文档
- `scripts/t10_run_e2e_cases.sh`
- `docs/repository-metadata/entrypoint-registry.md`

不修改：

- `Makefile`
- `src/rcsd_topo_poc/cli.py`
- T01-T09 业务算法实现

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
├── case_runner.py
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
- `spatial_slice` 必须记录 dependency audit，并对被选中道路补齐端点节点。
- Case runner 每个阶段都用显式输入文件运行既有脚本或 callable，输出 `stdout.log` 与 stage JSON。
- Case runner 不在同一 Case 内消费失败阶段的部分输出；`CONTINUE_ON_ERROR` 只用于多 Case 批处理是否继续。
- T06 漏斗只解析 T06 summary，不参与 T06 判定。

## 5. 风险与后续

- T09 当前缺少标准模块文档面，且现有实现与项目级“消费 T06 F-RCSD 承载关系”的口径仍需进一步对齐。
- T05 工作区已有未提交改动，涉及 Phase2 `swsdnode_out / yes_nr` 输出链路，本轮不回退该改动。
- `suggest` 当前通过通用字段匹配 selector evidence，后续需要沉淀模块级 selector schema。
- T03 / T04 当前仍基于输入切片自动发现候选，后续需要沉淀 CaseID 显式选择能力。
- T09 repo 主 runner 不存在，T10 通过模块 callable 编排 Step1/2 与 Step3。

## 6. 验证

- `.venv/bin/python -m pytest tests/modules/t10_e2e_orchestration`
- `git diff --check`
- 手工复核项目级主业务链仍保留 T08。
- 手工复核 `entrypoint-registry.md` 已登记 T10 打包与执行入口。
