# T10 模块级执行规则

## 范围

本文件只补充 `t10_e2e_orchestration` 模块局部规则。仓库级硬规则仍以 repo root `AGENTS.md` 为准。

## 模块边界

- T10 v1 Case runner 编排链路固定为 `T01 -> T07 Step1/2 -> T03 -> T04 -> T05 -> T07 Step3 -> T06 -> T09`。
- T08 是独立前置预处理、质检与修复模块；T10 v1 callable 与 Case runner 不调用 T08。
- T10 可消费 T08 独立运行后的成果作为外部输入；内网全量总控脚本可把 T08 作为独立前置阶段串联，但不得把 T08 混入 Case runner orchestration steps。
- T10 不修改 T01-T09 的业务算法与模块契约。
- T10 不新增 repo CLI、`Makefile` 目标、模块 `run.py` 或模块 `__main__.py`，除非任务书单独授权并同步入口登记。
- 当前已授权并登记的 root 脚本入口只有 `scripts/t10_pack_innernet_cases.sh`、`scripts/t10_run_e2e_cases.sh` 与 `scripts/t10_run_innernet_full_pipeline.sh`。

## Handoff 规则

- T10 的模块间输入必须配置到具体文件。
- 不接受 `t03_dir / t04_dir / t05_phase2_root / t06_dir` 等目录型 handoff 作为正式契约输入。
- 若当前模块契约或脚本仍使用目录推断，T10 只能在自身 contract audit 中暴露该问题，不得静默替调用方猜测文件。

## Case 证据包规则

- Case 范围由 SWSD 语义路口 ID 与半径表达。
- v1 Case 包只纳入外部输入，不纳入 T01-T09 模块间中间产物。
- `spatial_slice` 是当前正式文件物化模式，必须按 Case 范围输出局部外部输入切片。
- `spatial_slice` 必须补齐被选中道路的端点节点，并保留道路完整几何，不允许通过 silent fix 修补拓扑。
- `manifest_only` 不得表述为已完成空间裁剪。
- `copy_full` 仅作兼容诊断模式，不作为正式内网 Case 包默认模式。

## Case Runner 规则

- Case runner 必须优先消费 Case package 内的局部切片。
- Case runner 只编排既有脚本或模块 callable，不在 T10 中改写 T01-T09 算法。
- 每个阶段必须记录显式输入、输出、命令、状态、stdout log 与耗时。
- T06 已执行时必须输出 `t10_t06_funnel.json/csv/md`。
