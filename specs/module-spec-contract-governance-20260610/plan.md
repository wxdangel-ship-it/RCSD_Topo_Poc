# Module SPEC Contract Governance Plan

## 1. 执行计划

1. 建立本轮 SpecKit 工件，固定范围和验收标准。
2. 读取项目级模块盘点、模块生命周期和目标模块现有 `README.md`、`INTERFACE_CONTRACT.md`、`architecture/04-solution-strategy.md`。
3. 为 T01 / T03 / T04 / T05 / T06 / T07 / T08 / T09 新增或修复 `SPEC.md`。
4. 将目标模块 `README.md` 收敛为阅读入口与索引。
5. 将目标模块 `architecture/04-solution-strategy.md` 收敛为详细版需求 / 落地策略。
6. 做成果正确性审计：结构检查、核心口径检查、路径排除检查和格式检查。

## 2. 文件范围

允许修改：

- `modules/t01_data_preprocess/README.md`
- `modules/t01_data_preprocess/SPEC.md`
- `modules/t01_data_preprocess/architecture/04-solution-strategy.md`
- `modules/t03_virtual_junction_anchor/README.md`
- `modules/t03_virtual_junction_anchor/SPEC.md`
- `modules/t03_virtual_junction_anchor/architecture/04-solution-strategy.md`
- `modules/t04_divmerge_virtual_polygon/README.md`
- `modules/t04_divmerge_virtual_polygon/SPEC.md`
- `modules/t04_divmerge_virtual_polygon/architecture/04-solution-strategy.md`
- `modules/t05_junction_surface_fusion/README.md`
- `modules/t05_junction_surface_fusion/SPEC.md`
- `modules/t05_junction_surface_fusion/architecture/04-solution-strategy.md`
- `modules/t06_segment_fusion_precheck/README.md`
- `modules/t06_segment_fusion_precheck/SPEC.md`
- `modules/t06_segment_fusion_precheck/architecture/04-solution-strategy.md`
- `modules/t07_semantic_junction_anchor/README.md`
- `modules/t07_semantic_junction_anchor/SPEC.md`
- `modules/t07_semantic_junction_anchor/architecture/04-solution-strategy.md`
- `modules/t08_preprocess/README.md`
- `modules/t08_preprocess/SPEC.md`
- `modules/t08_preprocess/architecture/04-solution-strategy.md`
- `modules/t09_swsd_field_rule_restoration/README.md`
- `modules/t09_swsd_field_rule_restoration/SPEC.md`
- `modules/t09_swsd_field_rule_restoration/architecture/04-solution-strategy.md`
- `modules/t09_swsd_field_rule_restoration/AGENTS.md`（仅同步 `SPEC.md` 新职责引用）
- `modules/t09_swsd_field_rule_restoration/INTERFACE_CONTRACT.md`（仅同步 `SPEC.md` 新职责引用）
- `modules/t09_swsd_field_rule_restoration/architecture/10-quality-requirements.md`（仅同步 `SPEC.md` 新职责引用）
- `docs/doc-governance/audits/2026-06-10-module-doc-contract-audit.md`
- `specs/module-spec-contract-governance-20260610/**`

禁止修改：

- `modules/t10_e2e_orchestration/**`
- `src/**`
- `tests/**`
- `scripts/**`
- `Makefile`
- `docs/repository-metadata/entrypoint-registry.md`

## 3. 正确性审计方法

- 结构审计：检查每个目标模块是否存在 `SPEC.md / README.md / architecture/04-solution-strategy.md`。
- 职责审计：检查 `README.md` 是否为索引，`SPEC.md` 是否为凝练需求，`architecture/04` 是否为详细需求。
- 过期引用审计：检查目标模块内部不再把凝练版业务需求指向 `README.md`。
- 口径审计：抽样检索模块生命周期、主链、T04 Step1-7、T09 RCSD Laneinfo / trajectory gap、T06 replaceable 等关键业务口径。
- 范围审计：检查本轮路径不包含 T10、源码、测试、脚本和入口登记。
- 格式审计：运行 `git diff --check`，检查新增/修改 Markdown 无尾随空白。

## 4. 风险与控制

- 风险：一次性治理 8 个模块，容易把详细实现写成新的错误事实。
  - 控制：只从现有模块文档和项目级盘点抽取事实，不新增算法规则。
- 风险：当前工作区已有非本轮 T10 脏改。
  - 控制：所有验证使用路径级范围，并在完成回报中单独说明。
- 风险：`T06` 架构文件结构仍是旧命名。
  - 控制：本轮只新增标准 `architecture/04-solution-strategy.md`，不删除旧文档。

## 5. 验证命令

```bash
git diff --check
git diff --name-only -- modules/t01_data_preprocess modules/t03_virtual_junction_anchor modules/t04_divmerge_virtual_polygon modules/t05_junction_surface_fusion modules/t06_segment_fusion_precheck modules/t07_semantic_junction_anchor modules/t08_preprocess modules/t09_swsd_field_rule_restoration docs/doc-governance/audits/2026-06-10-module-doc-contract-audit.md specs/module-spec-contract-governance-20260610
rg -n "[ \t]+$" <modified-doc-paths>
```
