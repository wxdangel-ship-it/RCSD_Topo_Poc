# 001 T05 Explicit File Handoff

## 日期
- 2026-06-10

## 背景
- T10 四个 Case 在 T01 修复后推进到 T05，但 T05 被 runner 判定为 `Missing T05 explicit file inputs`。
- 实际缺失项为 `t07_run_root/t03_run_root/t04_run_root`，这些是目录型路径，不属于 T10 正式 handoff 契约。

## 根因
- T10 runner 复用了 T05 遗留脚本的目录参数，并把这些目录混入 T05 输入文件校验。
- T05 遗留脚本已经支持 `--t07-input/--t07-evidence/--t03-surface/--t03-evidence/--t04-surface/--t04-evidence` 等显式文件参数，因此 T10 不需要把上游 run root 提升为正式契约输入。

## 本次边界
- 不修改 T05 业务算法。
- 不放宽 T10 的目录型 handoff 禁止规则。
- 不新增 CLI、脚本入口或长期执行入口。

## 实际变更
- T10 runner 的 T05 阶段改为校验并传递显式文件输入。
- `t04_case_root` 仅作为 T05 遗留脚本的派生执行上下文记录，不作为 T05 正式阻断输入。
- 保留 T05 阶段命令、输入、输出、stdout log、耗时的原有审计结构。
- 修正 T05 Phase2 summary 输出登记为实际的 `summary.json`，避免 stage audit 出现假 missing output。

## 验证
- 新增单测确认 T05 runner 不再依赖 `t07_run_root/t03_run_root/t04_run_root`，并改用显式文件参数调用脚本。
- 待复跑 T10 Case，确认 T05 能进入真实业务执行。
