# T02 路口锚定模块

> 本文件是 `t02_junction_anchor` 的操作者总览。长期源事实以 [spec.md](/mnt/e/Work/RCSD_Topo_Poc/specs/t02-junction-anchor/spec.md) 与 [INTERFACE_CONTRACT.md](/mnt/e/Work/RCSD_Topo_Poc/modules/t02_junction_anchor/INTERFACE_CONTRACT.md) 为准。

## 1. 模块简介

- T02 面向双向 Segment 相关路口锚定。
- 当前模块状态是：需求基线阶段 / 文档先行。
- 当前聚焦阶段一 `DriveZone / has_evd gate`，不进入阶段二实现。

## 2. 当前模块状态

- 已落仓：需求基线文档
- 未启动：代码实现、测试实现、阶段二主逻辑、概率实现

## 3. 与 T01 的依赖关系

- T01 是 T02 的上游事实源之一。
- T02 当前依赖 T01 提供：
  - `segment`
  - `nodes`
- T02 本轮只消费上游事实，不修改 T01 文档，也不反向重定义 T01 语义。

## 4. 当前聚焦阶段一

- 阶段一目标：判断双向 Segment 相关路口是否“有有效资料”。
- 阶段一正式输入：
  - `segment`
  - `nodes`
  - `DriveZone.geojson`
- stage1 实际输入字段冻结为：
  - `segment.id / pair_nodes / junc_nodes`
  - `nodes.id / mainnodeid`
- `s_grade` 逻辑字段兼容读取 `s_grade / sgrade`。
- 空间判定统一在 `EPSG:3857` 下进行。
- 阶段一正式输出：
  - `nodes.has_evd`
  - `segment.has_evd`
  - `summary`
  - 审计留痕

## 5. 文档索引

- 规格：[spec.md](/mnt/e/Work/RCSD_Topo_Poc/specs/t02-junction-anchor/spec.md)
- 计划：[plan.md](/mnt/e/Work/RCSD_Topo_Poc/specs/t02-junction-anchor/plan.md)
- 任务：[tasks.md](/mnt/e/Work/RCSD_Topo_Poc/specs/t02-junction-anchor/tasks.md)
- 契约：[INTERFACE_CONTRACT.md](/mnt/e/Work/RCSD_Topo_Poc/modules/t02_junction_anchor/INTERFACE_CONTRACT.md)
- 模块约束：[AGENTS.md](/mnt/e/Work/RCSD_Topo_Poc/modules/t02_junction_anchor/AGENTS.md)
- 架构概览：[overview.md](/mnt/e/Work/RCSD_Topo_Poc/modules/t02_junction_anchor/architecture/overview.md)
- 启动记录：[000-bootstrap.md](/mnt/e/Work/RCSD_Topo_Poc/modules/t02_junction_anchor/history/000-bootstrap.md)

## 6. 后续阶段说明

- 阶段二仍待澄清。
- 阶段二当前只保留目标占位：
  - 完成双向 Segment 相关路口锚定
  - 产出锚定结果
  - 产出概率 / 置信度类结果
- 阶段二实现细节本轮不定义。
- 环岛代表 node 规则当前仍继承 T01 既有逻辑，不在本轮扩写成 T02 新算法。
