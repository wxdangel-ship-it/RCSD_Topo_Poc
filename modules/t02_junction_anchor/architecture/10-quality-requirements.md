# 10 质量要求

## 1. 可理解

- stage1 的输入、字段映射、代表 node 规则、输出与失败口径应能直接从文档读出。
- stage2 的 `is_anchor / fail1 / fail2` 口径，以及单 `mainnodeid` POC 的状态、风险和失败口径，也应能直接从文档读出。

## 2. 可运行

- 官方入口应能稳定读取 T01 `segment / nodes` 与 `DriveZone`，并输出正式产物。
- stage2 与单 `mainnodeid` 受控实验入口应能稳定读取输入并产出最小闭环结果。

## 3. 可诊断

- `summary / audit / log` 必须足以区分业务 `no` 与执行失败。
- `missing_required_field`、`invalid_crs_or_unprojectable`、`junction_nodes_not_found`、`representative_node_missing`、`no_target_junctions` 都应可追溯。
- 虚拟路口 POC 必须能追溯 `stable / surface_only / weak_branch_support / ambiguous_rc_match / no_valid_rc_connection / node_component_conflict / anchor_support_conflict` 等状态或失败原因。

## 4. 可治理

- 模块长期真相不得只留在 `specs/` 或 `README.md`。
- 模块文档面、CLI 入口、实现与测试应保持一致。
- 受控实验入口也必须写入模块契约和架构文档，不能只留在聊天记录或临时脚本。

## 5. GIS 正确性

- CRS 变换必须明确、可解释、可复现。
- `nodes` 与 `DriveZone` 的空间判定必须在同一 CRS 下完成。
- 不允许用隐式 CRS 默认值或黑箱几何假设掩盖数据问题。
- 虚拟路口 POC 必须保证 own-group nodes 的 must-cover 与局部 RC 支撑校验，不允许用错误 RC 分支补面。
