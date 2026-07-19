# Implementation Plan：T12 自动高置信质量确认

**Branch**：`codex/t12-auto-high-confidence`
**Spec**：[spec.md](spec.md)

## Summary

在不改变正式入口和 T06 行为的前提下，把 T12 从“候选必须人工复核后才能发布”升级为“raw endpoint topology + 标准路口 portal + 锚点可信度门禁自动发布”。外部 review 仍可作为可选 QA override。

## 五类职责

### 产品

- 默认一次运行即输出最终问题；准确率优先。
- 不使用高/中概率标签，不把证据不足项混入最终问题。
- `1026960` 无 review 达到 10/25/0，只作回归验收。

### 架构

- 候选层继续使用 canonical graph；正式判定新增 raw endpoint graph。
- T07 portal 受 `RCSDIntersection` 标准面约束；T03/T04 保留实际接入侧 spatial portal。
- 自动 decision 与 review override 分离；T12 保持 audit-only。

### 研发

- 在 `carrier_graph.py` 增加 identity/raw graph helper。
- 在 `anchor_portals.py` 增加 T07 surface association 和 raw portal 构造。
- 在 `candidate_audit.py` 生成 raw carrier evidence、anchor confidence 和自动判定所需字段。
- 在 `review_publish.py` 先应用自动判定，再可选应用外部覆盖。
- 在 `outputs.py` 增加 decision/raw evidence 字段和自动计数。

### 测试

- 纯单元测试覆盖 raw graph 不折叠、T07 surface portal、锚点门禁、自动决定与 override。
- 契约测试覆盖无 review 时不产生 manual、计数守恒和输出 schema。
- 真实数据回归覆盖无 review 35/10/25/0 和 confirmed 集合。
- 生产代码扫描覆盖 Case/对象 ID 禁止项。

### QA

- CRS、拓扑、几何语义、审计追溯、性能五项均进入 summary/manifest 与验证报告。
- 明确 `silent_fix=false`，不修改任何输入。
- 记录 canonical/raw 图差异和 T07 surface association 统计。

## Source Fact Updates

同轮更新：

- `SPEC.md`
- `docs/PROJECT_REQUIREMENTS.md`
- 必要 `docs/architecture/*`
- `docs/doc-governance/module-lifecycle.md`
- `modules/t12_frcsd_quality_audit/SPEC.md`
- `modules/t12_frcsd_quality_audit/INTERFACE_CONTRACT.md`
- `modules/t12_frcsd_quality_audit/architecture/*`

不新增或改变正式入口，因此不修改 entrypoint registry。

## Compatibility

- CLI 参数保持兼容；`--review-decisions` 从必需发布门槛变为可选 override。
- 输出文件名保持兼容；旧 `review_*` 字段保留，新加 `decision_source/decision_rule`。
- 显式 review 可复现外部治理决定；没有 review 时自动结果可直接交付。

## Validation Gates

1. 全部目标源码/脚本写入前完成字节自检，写后均 `<100KB`。
2. T12 单元/契约测试通过。
3. T10 受影响回归通过。
4. `1026960` 原始数据无 review 恰好 35/10/25/0。
5. confirmed 集合与 fixture 完全一致，生产源码无对象 ID。
6. `git diff --check`、源事实一致性和 GIS 五项审计通过。
