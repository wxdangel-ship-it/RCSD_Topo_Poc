# 02 约束

## 状态

- 当前状态：`模块级约束说明`
- 来源依据：
  - 仓库级执行规则
  - T02 stage1 已冻结业务基线
  - 当前实现与测试

## 全局约束

- 当前模块正式实现范围只到 stage1 `DriveZone / has_evd gate`。
- 当前正式输入字段约束：
  - `segment.id / pair_nodes / junc_nodes`
  - `segment.s_grade | sgrade`
  - `nodes.id / mainnodeid`
- `mainnode` 可作为业务概念名，但 stage1 正式输入字段只能是 `mainnodeid`。
- `working_mainnodeid` 不进入 stage1 强规则。
- 空间判定统一在 `EPSG:3857` 下进行。
- `has_evd` 必须保持 `yes/no/null` 业务语义。
- `segment.has_evd` 必须保持严格全满足规则。
- 当前不覆盖：
  - stage2 锚定主逻辑
  - 概率 / 置信度
  - 误伤捞回
  - 环岛新规则

## 数据与诊断约束

- 缺失必需字段、缺失可用 CRS、几何不可投影时，必须显式失败并留下审计。
- `junction_nodes_not_found` 与 `no_target_junctions` 是业务结果中的 `no`，不能被伪装成运行成功且无审计。
- `representative_node_missing` 不允许 silent fallback。

## 协作约束

- 模块长期真相优先沉淀到 `architecture/*` 与 `INTERFACE_CONTRACT.md`。
- `README.md` 只做操作者总览，不能单独承载稳定业务语义。
- 未经用户明确允许，不修改 T01 文档，不扩写 stage2。
