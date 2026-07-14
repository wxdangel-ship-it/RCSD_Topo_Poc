# Analyze: T06 六用例业务冻结与性能恢复

## 1. 源事实一致性

- 项目级事实要求模块化、无 silent fix、正式审计可追溯。
- T06 模块事实要求 Step2 发布 replacement plan，Step3 只执行计划并由 surface/final topology gate 审核。
- 本任务不改变 Step1/Step2 规则、plan 边界、Step3 relation、topology 定义或正式字段。
- 当前未发现项目级、模块级、任务书之间的冲突。

## 2. 接口与入口分析

- 不新增、删除、重命名或改变官方 CLI、root script、callable signature。
- `scripts/t06_run_innernet_precheck.py` 与 `scripts/t06_run_step3_segment_replacement.py` 的调用方式保持兼容。
- 不需要修改 `entrypoint-registry.md`。

## 3. 文件体量分析

- 已读取 `code-boundaries-and-entrypoints.md` 与 `code-size-audit.md`。
- `step3_surface_aware_plan_release.py` 已由 `74453` bytes 拆至 `57187` bytes；surface release 决策与输入索引下沉至 `step3_surface_release_plan.py`（`19639` bytes）。T06 `src/` 与 `tests/` 共扫描 `153` 个源码/脚本文件，`>= 61440 bytes` 为 `0`。
- 每个源码/脚本写入前仍需重新读取当前 bytes；任何审计事实变化同轮更新 `code-size-audit.md`。

## 4. 业务与性能边界

- 可以优化：中间验证轮的重复正式发布、同输入重复读取、同 geometry/参数重复 buffer、不可变索引重建。
- 不可优化掉：Step3 业务计算、surface topology、final topology hard gate、ownership/construction 最终结果、unreplaced attribution、正式输出与审计行。
- 候选验证不落最终文件不等于跳过业务检查；必须在内存中产生相同状态并参与同一 gate。

## 5. GIS/QA 完整性

- CRS：保持既有读取和转换路径。
- 拓扑：final fail key、hard-gate rollback、accepted exception 规则不变。
- 几何：不修改 geometry、不降低精度、不改变 buffer/距离阈值。
- 追溯：每轮记录输入、参数、commit、run root、日志、输出、RSS。
- 性能：逐例和合计比较，保留原始 `/usr/bin/time -v` 与 stage duration。

## 6. 根因与架构结论

- 当前版本回退并非业务算法本身变慢，而是 Surface-aware Step3 的候选、回滚与 hard-gate 共执行 `2~4` 次完整 Step3，且每次重复构建 topology、ownership、construction 并正式写出 GPKG/CSV/JSON。
- 重复读取不可变输入、重复构建空间索引、重复 corridor coverage/buffer 与重复 final auxiliary publish 叠加，形成六例 `1531.60s` 对冻结线 `611.451823s` 的 `2.505x` 回退。
- 合理架构应将“业务验证”与“正式发布”分离：验证轮保留完整业务决策和 topology gate，只在临时目录输出 gate 必需证据；最终候选提升一次，并仅发布一次 ownership/construction/正式 feature triplet。
- connectivity ownership 的历史结果隐式依赖多轮完整 Step3 形成的发布闭包。优化后改为一次构建内执行轻量 attachment/group 闭包稳定化，再进行逐道路空间归属和一次写盘，保持旧证据而不恢复重复发布。
- authoritative transition closure 的历史审计可能在早期验证轮产生、后续轮清零；最终架构显式携带最后一份非空审计状态，避免“结果已应用但审计行丢失”。

## 7. 最终结论

- 六用例 222 份 CSV 与初始业务基线逐字节一致，差异为 `0`。
- 六用例总耗时 `551.07s`，低于冻结线 `611.451823s`，比当前版本基线 `1531.60s` 下降 `64.02%`。
- 六例逐例 Step1/2、Step3 和总耗时均低于各自冻结线；peak RSS 均低于当前版本基线，swap 均为 `0`。
- T06 全量测试 `431 passed`；CRS 继续统一为 `EPSG:3857`，geometry、topology gate、正式字段、CLI 与入口未改变。
