# 02 约束

## 状态

- 当前状态：`模块级约束说明`
- 来源依据：
  - 仓库级执行规则
  - T02 stage1 已冻结业务基线
  - 当前实现与测试

## 全局约束

- 当前模块已正式实现 stage1 `DriveZone / has_evd gate`、stage2 `anchor recognition / anchor existence` 与 stage3 `virtual intersection anchoring` baseline。
- stage3 baseline 不得表述为最终唯一锚定决策闭环或正式产线级全量批处理闭环。
- 当前正式输入字段约束：
  - `segment.id / pair_nodes / junc_nodes`
  - `segment.s_grade | sgrade`
  - `nodes.id / mainnodeid`
- `mainnode` 可作为业务概念名，但 stage1 正式输入字段只能是 `mainnodeid`。
- `working_mainnodeid` 不进入 stage1 强规则。
- 空间判定统一在 `EPSG:3857` 下进行。
- `has_evd` 必须保持 `yes/no/null` 业务语义。
- `segment.has_evd` 必须保持严格全满足规则。
- stage3 虚拟路口锚定不得把个例 case id、RC id、node id 硬编码进规则。
- stage3 虚拟路口锚定必须把 own-group nodes 视为 must-cover，不得只拿它们做分析输入。
- `polygon-support` 可以比最终 association 更完整，但两者解耦必须显式、可审计。
- 对 nodes 与 RCSD 拓扑无法同时满足的场景，必须明确失败或风险标记，不得 silent fix。
- 当前不覆盖：
  - 最终唯一锚定决策闭环
  - 概率 / 置信度
  - 误伤捞回
  - 环岛新规则
  - 正式产线级全量虚拟路口面批处理

## 数据与诊断约束

- 缺失必需字段、缺失可用 CRS、几何不可投影时，必须显式失败并留下审计。
- `junction_nodes_not_found` 与 `no_target_junctions` 是业务结果中的 `no`，不能被伪装成运行成功且无审计。
- `representative_node_missing` 不允许 silent fallback。
- stage3 `case-package` 是 baseline regression 入口，不允许回退。
- stage3 `full-input` 是完整数据 baseline 入口；共享大图层直连运行必须先通过 layer / CRS / 预裁剪与 preflight 约束，不能把数据接入问题误判为算法回退。
- `review_mode` 仅用于分析和人工复核，不得被描述成正式生产口径。

## 协作约束

- 模块长期真相优先沉淀到 `architecture/*` 与 `INTERFACE_CONTRACT.md`。
- `README.md` 只做操作者总览，不能单独承载稳定业务语义。
- 未经用户明确允许，不修改 T01 文档，不把 stage3 baseline 直接升级为正式产线级批处理方案。
