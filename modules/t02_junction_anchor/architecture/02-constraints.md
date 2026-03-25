# 02 约束

## 状态

- 当前状态：`模块级约束说明`
- 来源依据：
  - 仓库级执行规则
  - T02 stage1 已冻结业务基线
  - 当前实现与测试

## 全局约束

- 当前模块已正式实现 stage1 `DriveZone / has_evd gate` 与 stage2 `anchor recognition / anchor existence` 最小闭环。
- 单 `mainnodeid` 虚拟路口面与文本证据包当前属于受控实验入口，不得表述为最终唯一锚定决策闭环。
- 当前正式输入字段约束：
  - `segment.id / pair_nodes / junc_nodes`
  - `segment.s_grade | sgrade`
  - `nodes.id / mainnodeid`
- `mainnode` 可作为业务概念名，但 stage1 正式输入字段只能是 `mainnodeid`。
- `working_mainnodeid` 不进入 stage1 强规则。
- 空间判定统一在 `EPSG:3857` 下进行。
- `has_evd` 必须保持 `yes/no/null` 业务语义。
- `segment.has_evd` 必须保持严格全满足规则。
- 单 `mainnodeid` 虚拟路口 POC 不得把个例 case id、RC id、node id 硬编码进规则。
- 虚拟路口 POC 必须把 own-group nodes 视为 must-cover，不得只拿它们做分析输入。
- `polygon-support` 可以比最终 association 更完整，但两者解耦必须显式、可审计。
- 对 nodes 与 RCSD 拓扑无法同时满足的场景，必须明确失败或风险标记，不得 silent fix。
- 当前不覆盖：
  - 最终唯一锚定决策闭环
  - 概率 / 置信度
  - 误伤捞回
  - 环岛新规则
  - 全量虚拟路口面批处理

## 数据与诊断约束

- 缺失必需字段、缺失可用 CRS、几何不可投影时，必须显式失败并留下审计。
- `junction_nodes_not_found` 与 `no_target_junctions` 是业务结果中的 `no`，不能被伪装成运行成功且无审计。
- `representative_node_missing` 不允许 silent fallback。
- 虚拟路口 POC 默认验收基线使用标准 case-package 输入；共享大图层直连运行涉及额外 layer / CRS / 预裁剪问题，不作为当前算法验收基线。
- `review_mode` 仅用于分析和人工复核，不得被描述成正式生产口径。

## 协作约束

- 模块长期真相优先沉淀到 `architecture/*` 与 `INTERFACE_CONTRACT.md`。
- `README.md` 只做操作者总览，不能单独承载稳定业务语义。
- 未经用户明确允许，不修改 T01 文档，不把受控实验入口直接升级为正式批处理方案。
