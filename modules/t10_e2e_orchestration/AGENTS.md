# T10 模块级执行规则

## 范围

本文件只补充 `t10_e2e_orchestration` 模块局部规则。仓库级硬规则仍以 repo root `AGENTS.md` 为准。

## 模块边界

- T10 v1 编排链路固定为 `T01 -> T07 -> T03 -> T04 -> T05 -> T06 -> T09`。
- T08 是独立前置预处理、质检与修复模块；T10 v1 不调用 T08。
- T10 可消费 T08 独立运行后的成果作为外部输入，但不得把 T08 纳入 v1 orchestration steps。
- T10 不修改 T01-T09 的业务算法与模块契约。
- T10 不新增 repo CLI、root `scripts/`、`Makefile` 目标、模块 `run.py` 或模块 `__main__.py`，除非任务书单独授权并同步入口登记。

## Handoff 规则

- T10 的模块间输入必须配置到具体文件。
- 不接受 `t03_dir / t04_dir / t05_phase2_root / t06_dir` 等目录型 handoff 作为正式契约输入。
- 若当前模块契约或脚本仍使用目录推断，T10 只能在自身 contract audit 中暴露该问题，不得静默替调用方猜测文件。

## Case 证据包规则

- Case 范围由 SWSD 语义路口 ID 与半径表达。
- v1 Case 包只纳入外部输入，不纳入 T01-T09 模块间中间产物。
- v1 不执行空间切片，不得把 manifest-only package 表述为已完成空间裁剪。
