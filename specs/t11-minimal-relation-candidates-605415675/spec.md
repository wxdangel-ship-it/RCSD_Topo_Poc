# Spec：T11 极简版人工 Relation 修复候选抽取

## 1. 目标

新增 T11 极简模块，从冻结 T10 Case root 中读取 T05/T06/T10 证据，抽取人工 relation 修复候选。主验证用例为 `605415675`。

## 2. 范围

- 新增 `t11_manual_relation_review` callable。
- 新增 repo 级脚本入口 `scripts/t11_extract_relation_repair_candidates.py`。
- 新增 T11 模块文档契约。
- 更新模块盘点、生命周期和入口注册表。
- 对 `605415675` 生成候选 CSV、GPKG、人工模板 CSV 和 summary JSON。

## 3. 非目标

- 不做人工结果回灌。
- 不修改 T05/T06/T09。
- 不重跑 T06/T09。
- 不把 T11 候选作为 T06 白名单。
- 不覆盖 `outputs/baselines/`。

## 4. 候选分类

必须支持：

- `relation_missing_or_invalid`
- `relation_graph_unconsumable`
- `required_nodes_disconnected_or_pair_anchor_issue`
- `no_evidence_but_rcsd_present_in_segment_scope`
- `uncertain_upstream_or_data_issue`

## 5. 验收

- 能定位并读取 `605415675` 的 T10 Case root。
- 生成 `t11_relation_repair_candidates.csv`。
- 生成 `t11_manual_relation_template.csv`。
- 生成可读取的 GPKG。
- Summary 记录输入路径、参数、运行时间、候选统计和质量检查。
- 单元测试覆盖分类、聚合、排序和模板不预填。
