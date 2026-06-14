# 002 T06 Step3 Execution Context

## 日期
- 2026-06-10

## 背景
- T10 完整链路在 `74155468` 中已通过 T06 Step1/2，但 Step3 被 runner 阻断。
- 阻断原因是 `t06_run_root` 被 `_missing_files` 当作文件输入校验，而它实际是 Step3 遗留脚本的运行根目录。

## 根因
- T06 Step3 的正式业务输入是 T01 文件、T05 copy-on-write 文件以及 Step2 `t06_rcsd_segment_replaceable.gpkg`。
- `t06_run_root` 仅用于遗留脚本定位 Step1/2 输出目录和写入 Step3 子目录，不应作为 T10 正式文件 handoff。

## 本次边界
- 不修改 T06 Step1/2/3 业务算法。
- 不放宽 T10 目录型 handoff 禁止规则。
- 不新增入口或改变 T06 官方脚本签名。

## 实际变更
- T10 Step3 校验改为显式检查 `t06_step2_replaceable` 文件及 T01/T05 文件。
- `t06_run_root` 改为派生执行上下文：优先使用 Step1/2 产出的 run root，必要时可从 `t06_step2_replaceable` 父目录反推。
- Stage audit 记录 `execution_context.t06_run_root`，但正式 `inputs` 不再包含目录型路径。

## 验证
- 新增 T10 单测覆盖 Step3 不把 `t06_run_root` 作为文件输入、仍向遗留脚本传递 `--t06-run-root`。
- 待复跑完整 T10 Case，确认 T06 Step3 可进入真实执行。
