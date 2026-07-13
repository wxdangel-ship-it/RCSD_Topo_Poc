# T10 Agent Guardrails

本文件只保留 `t10_e2e_orchestration` 的 Agent 局部红线；模块源事实以 `SPEC.md`、`INTERFACE_CONTRACT.md` 与 `architecture/*` 为准。

- T10 v1 Case runner 编排链路为 `T01 -> T07 Step1/2 -> T03 -> T04 -> T05 -> T06 -> T11 -> T09`；T11 是 audit-only 必经阶段，不改变 T06 到 T09 的业务 handoff。
- T07 Step3 是可选兼容 relation 补锚，不得作为 T05 后默认必经阶段写入 T10 Case runner。
- T08 是独立前置预处理、质检与修复模块；T10 v1 callable 与 Case runner 不调用 T08。
- T10 只编排既有脚本或模块 callable，不修改 T01-T09 / T11 的业务算法与模块契约。
- 模块间 handoff 必须配置到具体文件；不把 `t03_dir / t04_dir / t05_phase2_root / t06_dir` 等目录型 handoff 当作正式契约输入。
- `manifest_only` 不得表述为已完成空间裁剪；`copy_full` 仅作兼容诊断模式。
- 不新增 repo CLI、Makefile 目标、模块 `run.py` 或模块 `__main__.py`，除非任务单独授权并同步入口登记。
