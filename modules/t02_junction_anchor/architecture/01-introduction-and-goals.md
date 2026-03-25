# 01 引言与目标

## 状态

- 当前状态：`模块级架构说明（基于当前 stage1 active implementation）`
- 来源依据：
  - [INTERFACE_CONTRACT.md](/mnt/e/Work/RCSD_Topo_Poc/modules/t02_junction_anchor/INTERFACE_CONTRACT.md)
  - [stage1_drivezone_gate.py](/mnt/e/Work/RCSD_Topo_Poc/src/rcsd_topo_poc/modules/t02_junction_anchor/stage1_drivezone_gate.py)
  - [test_stage1_drivezone_gate.py](/mnt/e/Work/RCSD_Topo_Poc/tests/modules/t02_junction_anchor/test_stage1_drivezone_gate.py)

## 当前正式定位

- 模块路径：`modules/t02_junction_anchor`
- 当前角色：
  - 面向双向 Segment 相关路口的 stage1 `DriveZone / has_evd gate`
  - 面向资料命中路口的 stage2 `anchor recognition / anchor existence`
  - 面向单 `mainnodeid` 复核场景的虚拟路口面与文本证据包受控实验入口
- 上游关系：
  - 依赖 T01 提供 `segment` 与 `nodes`
- 下游关系：
  - 为后续路口锚定主逻辑提供 gate 结果、summary 与审计基础

## 模块目标

`t02_junction_anchor` 的长期目标是：

1. 为双向 Segment 相关路口锚定提供稳定的 stage1 gate 与后续 stage2 落点
2. 将“是否有有效资料”和“如何完成最终锚定”拆成清晰、可治理的两阶段
3. 为单 `mainnodeid` 复核场景提供可解释的局部虚拟路口面、RC 关联与文本证据包
4. 保持输出可审计、可复现、可 smoke，而不是把异常和歧义藏进黑箱逻辑

## 文档目标

本模块的最小正式文档面当前由以下文件共同组成：

- `architecture/*`
- [INTERFACE_CONTRACT.md](/mnt/e/Work/RCSD_Topo_Poc/modules/t02_junction_anchor/INTERFACE_CONTRACT.md)
- [README.md](/mnt/e/Work/RCSD_Topo_Poc/modules/t02_junction_anchor/README.md)

补充说明：

- [AGENTS.md](/mnt/e/Work/RCSD_Topo_Poc/modules/t02_junction_anchor/AGENTS.md) 只承载 durable guidance。
- `specs/t02-junction-anchor/*` 继续保留为变更工件，不替代长期模块真相。
