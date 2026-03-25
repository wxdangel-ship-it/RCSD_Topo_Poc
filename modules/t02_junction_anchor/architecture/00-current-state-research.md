# 00 当前状态研究

## 当前状态

- 模块 ID：`t02_junction_anchor`
- 当前阶段：`active`
- 说明：
  - repo 级生命周期已将 T02 登记为正式业务模块。
  - 当前已存在 stage1 `DriveZone / has_evd gate`、stage2 `anchor recognition / anchor existence` 与 stage3 `virtual intersection anchoring` baseline 实现。
  - 单 `mainnodeid` 文本证据包当前作为 stage3 复核与外部复现支撑工具保留。
- 研究目标：
  - 让 T02 模块级 architecture 文档与当前实现、契约、README 一致
  - 把 T02 从早期“变更规格主导”收口到“正式模块文档面主导”

## 当前输入证据

- 实现入口：
  - [cli.py](/mnt/e/Work/RCSD_Topo_Poc/src/rcsd_topo_poc/cli.py)
  - [stage1_drivezone_gate.py](/mnt/e/Work/RCSD_Topo_Poc/src/rcsd_topo_poc/modules/t02_junction_anchor/stage1_drivezone_gate.py)
  - [stage2_anchor_recognition.py](/mnt/e/Work/RCSD_Topo_Poc/src/rcsd_topo_poc/modules/t02_junction_anchor/stage2_anchor_recognition.py)
  - [virtual_intersection_poc.py](/mnt/e/Work/RCSD_Topo_Poc/src/rcsd_topo_poc/modules/t02_junction_anchor/virtual_intersection_poc.py)
  - [virtual_intersection_full_input_poc.py](/mnt/e/Work/RCSD_Topo_Poc/src/rcsd_topo_poc/modules/t02_junction_anchor/virtual_intersection_full_input_poc.py)
  - [text_bundle.py](/mnt/e/Work/RCSD_Topo_Poc/src/rcsd_topo_poc/modules/t02_junction_anchor/text_bundle.py)
- 测试：
  - [test_stage1_drivezone_gate.py](/mnt/e/Work/RCSD_Topo_Poc/tests/modules/t02_junction_anchor/test_stage1_drivezone_gate.py)
  - [test_stage2_anchor_recognition.py](/mnt/e/Work/RCSD_Topo_Poc/tests/modules/t02_junction_anchor/test_stage2_anchor_recognition.py)
  - [test_virtual_intersection_poc.py](/mnt/e/Work/RCSD_Topo_Poc/tests/modules/t02_junction_anchor/test_virtual_intersection_poc.py)
  - [test_virtual_intersection_full_input_poc.py](/mnt/e/Work/RCSD_Topo_Poc/tests/modules/t02_junction_anchor/test_virtual_intersection_full_input_poc.py)
  - [test_text_bundle.py](/mnt/e/Work/RCSD_Topo_Poc/tests/modules/t02_junction_anchor/test_text_bundle.py)
  - [test_cli_t02.py](/mnt/e/Work/RCSD_Topo_Poc/tests/test_cli_t02.py)
  - [test_smoke_t02_stage1.py](/mnt/e/Work/RCSD_Topo_Poc/tests/test_smoke_t02_stage1.py)
  - [test_smoke_t02_virtual_intersection_poc.py](/mnt/e/Work/RCSD_Topo_Poc/tests/test_smoke_t02_virtual_intersection_poc.py)
  - [test_smoke_t02_virtual_intersection_full_input_poc.py](/mnt/e/Work/RCSD_Topo_Poc/tests/test_smoke_t02_virtual_intersection_full_input_poc.py)
- 上游事实源：
  - [INTERFACE_CONTRACT.md](/mnt/e/Work/RCSD_Topo_Poc/modules/t01_data_preprocess/INTERFACE_CONTRACT.md)
- 变更工件：
  - [spec.md](/mnt/e/Work/RCSD_Topo_Poc/specs/t02-junction-anchor/spec.md)
  - [plan.md](/mnt/e/Work/RCSD_Topo_Poc/specs/t02-junction-anchor/plan.md)
  - [tasks.md](/mnt/e/Work/RCSD_Topo_Poc/specs/t02-junction-anchor/tasks.md)
  - [spec.md](/mnt/e/Work/RCSD_Topo_Poc/specs/t02-virtual-intersection-batch-poc/spec.md)
  - [plan.md](/mnt/e/Work/RCSD_Topo_Poc/specs/t02-virtual-intersection-batch-poc/plan.md)
  - [tasks.md](/mnt/e/Work/RCSD_Topo_Poc/specs/t02-virtual-intersection-batch-poc/tasks.md)

## 当前观察

- stage1、stage2、stage3 都已具备可运行入口、正式输出或 baseline 输出、审计留痕与最小测试。
- 当前主要脱节不再是“是否有实现”，而是部分文档仍停留在“虚拟路口属于受控实验层”的旧口径。
- [virtual_intersection_poc.py](/mnt/e/Work/RCSD_Topo_Poc/src/rcsd_topo_poc/modules/t02_junction_anchor/virtual_intersection_poc.py) 已超过 `100 KB`，单文件多职责耦合已进入结构债状态。
- `_template/architecture/*` 本身是合理模板骨架；真正缺口是 T02 未完整复制并具体化这套标准文档面。

## 待确认问题

- stage3 baseline 之后，何时继续推进到正式产线级全量批处理能力
- 后续是否引入更高层 GIS / IO 插件栈以优化性能与维护性
