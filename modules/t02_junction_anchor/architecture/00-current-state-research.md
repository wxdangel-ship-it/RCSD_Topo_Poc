# 00 当前状态研究

## 当前状态

- 模块 ID：`t02_junction_anchor`
- 当前阶段：`active`
- 说明：
  - repo 级生命周期已将 T02 登记为正式业务模块。
  - 当前正式实现范围是 stage1 `DriveZone / has_evd gate`。
  - stage2 仍处于目标占位与后续澄清阶段。
- 研究目标：
  - 让 T02 模块级 architecture 文档与当前实现、契约、README 一致
  - 把 T02 从早期“变更规格主导”收口到“正式模块文档面主导”

## 当前输入证据

- 实现入口：
  - [cli.py](/mnt/e/Work/RCSD_Topo_Poc/src/rcsd_topo_poc/cli.py)
  - [stage1_drivezone_gate.py](/mnt/e/Work/RCSD_Topo_Poc/src/rcsd_topo_poc/modules/t02_junction_anchor/stage1_drivezone_gate.py)
- 测试：
  - [test_stage1_drivezone_gate.py](/mnt/e/Work/RCSD_Topo_Poc/tests/modules/t02_junction_anchor/test_stage1_drivezone_gate.py)
  - [test_cli_t02.py](/mnt/e/Work/RCSD_Topo_Poc/tests/test_cli_t02.py)
  - [test_smoke_t02_stage1.py](/mnt/e/Work/RCSD_Topo_Poc/tests/test_smoke_t02_stage1.py)
- 上游事实源：
  - [INTERFACE_CONTRACT.md](/mnt/e/Work/RCSD_Topo_Poc/modules/t01_data_preprocess/INTERFACE_CONTRACT.md)
- 变更工件：
  - [spec.md](/mnt/e/Work/RCSD_Topo_Poc/specs/t02-junction-anchor/spec.md)
  - [plan.md](/mnt/e/Work/RCSD_Topo_Poc/specs/t02-junction-anchor/plan.md)
  - [tasks.md](/mnt/e/Work/RCSD_Topo_Poc/specs/t02-junction-anchor/tasks.md)

## 当前观察

- stage1 已具备可运行入口、正式输出、审计留痕与 smoke。
- 当前输出契约已经稳定，但早期模块文档面未按模板具体化，导致项目级与模块级表述脱节。
- `_template/architecture/*` 本身是合理模板骨架；真正缺口是 T02 未完整复制并具体化这套标准文档面。

## 待确认问题

- stage2 的业务闭环、字段和验收标准何时正式启动
- 后续是否引入更高层 GIS / IO 插件栈以优化性能与维护性
