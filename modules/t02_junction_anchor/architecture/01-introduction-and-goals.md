# 01 引言与目标

## 状态

- 当前状态：`Retired 历史模块架构说明`
- 来源依据：
  - [INTERFACE_CONTRACT.md](/mnt/e/Work/RCSD_Topo_Poc/modules/t02_junction_anchor/INTERFACE_CONTRACT.md)
  - [stage1_drivezone_gate.py](/mnt/e/Work/RCSD_Topo_Poc/src/rcsd_topo_poc/modules/t02_junction_anchor/stage1_drivezone_gate.py)
  - [test_stage1_drivezone_gate.py](/mnt/e/Work/RCSD_Topo_Poc/tests/modules/t02_junction_anchor/test_stage1_drivezone_gate.py)

## 当前生命周期定位

- 模块路径：`modules/t02_junction_anchor`
- 生命周期：`Retired`
- 当前主业务链不再消费 T02 作为正式 handoff；T02 历史能力已由以下模块承接：
  - T07：承接已有路口面 1:1 锚定和 relation 补锚。
  - T03：承接交叉 / T 型虚拟锚定。
  - T04：承接分歧 / 合流 / 复杂路口虚拟锚定。
  - T08：承接预处理、字段修复、复杂路口预处理和质量显性化。

## 历史能力目标

`t02_junction_anchor` 的历史目标是：

1. 为双向 Segment 相关路口锚定提供 stage1 gate、stage2 anchor recognition 与 stage3 virtual intersection anchoring 的早期闭环。
2. 将“是否有有效资料”“是否已命中稳定锚点”“未锚定时如何构造虚拟路口面”拆成清晰、可审计的三阶段。
3. 为 stage3 提供局部虚拟路口面、RC 关联与批次汇总能力，并为单 case 复核保留文本证据包支撑。
4. 为后续 T07/T03/T04/T08 拆分和迁移提供历史 baseline、历史测试和历史运行证据。

当前不得把 T02 作为新增业务需求的承接模块；需要新增或修改当前主链能力时，应分别进入 T07、T03、T04 或 T08。

## 文档目标

本模块的历史文档面当前由以下文件共同组成：

- `architecture/*`
- [INTERFACE_CONTRACT.md](/mnt/e/Work/RCSD_Topo_Poc/modules/t02_junction_anchor/INTERFACE_CONTRACT.md)
- [README.md](/mnt/e/Work/RCSD_Topo_Poc/modules/t02_junction_anchor/README.md)

补充说明：

- 模块级 `AGENTS.md` 只承载可选 Agent 局部红线，不替代当前项目级生命周期事实。
- `specs/t02-junction-anchor/*` 与 `specs/t02-virtual-intersection-batch-poc/*` 继续保留为历史变更工件，不替代当前项目级生命周期事实。
