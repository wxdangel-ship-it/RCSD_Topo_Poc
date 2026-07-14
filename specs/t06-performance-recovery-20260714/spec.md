# Feature Specification: T06 六用例业务冻结与性能恢复

**Feature Branch**: `codex/t06-performance-compare-20260714`
**Created**: 2026-07-14
**Status**: Ready for implementation
**Input**: 用户要求在临时工作树中，基于当前版本建立 T06 六测试用例业务与性能基线，完成业务、性能及架构诊断；在业务结果不回退且内存峰值受控的前提下，把每个测试用例及六用例合计性能恢复到已冻结正式基线水平；严格先验证 `1885118`，完全通过后再回归其余五例。

## 1. 产品视角

### User Story 1 - 冻结当前版本业务基线 (Priority: P1)

作为 T06 结果使用者，我需要一套由当前提交实际运行产生的六用例业务基线，使后续优化只能改变执行成本，不能改变 Step1/Step2 漏斗、replacement plan、Step3 F-RCSD、归因和拓扑结果。

**Independent Test**: 对六个用例分别运行当前版本 T06 Step1/2/3，保存结构化正式产物、核心业务指标与内容指纹。

### User Story 2 - 恢复冻结基线性能 (Priority: P1)

作为流水线维护者，我需要优化后每个用例的 T06 耗时不高于正式冻结基线的对应值，且六例合计不高于正式冻结基线总值，避免用快用例掩盖慢用例回退。

**Independent Test**: 同环境、同输入、同参数、同顺序下，逐例比较 Step1/2、Step3 及 T06 总耗时，并记录进程 peak RSS。

### User Story 3 - 架构与内存风险收敛 (Priority: P1)

作为模块维护者，我需要消除 Step3 中无业务价值的重复读取、重复索引/ownership/construction 重建、重复完整审计与重复落盘，同时保持所有正式质量门禁和产物不变，且不恢复无界缓存。

**Independent Test**: 单元/契约测试、动态 profile、结构化产物等价比较和 peak RSS 对比共同证明优化只改变成本。

### User Story 4 - 严格分阶段回归 (Priority: P2)

作为迭代执行者，我需要所有候选先通过 `1885118` 的业务、拓扑、性能和内存门禁，只有大阶段完成后才运行其余五例。

**Independent Test**: 运行证据中的顺序固定为 `1885118 -> 605415675 -> 609214532 -> 706247 -> 74155468 -> 991176`。

## 2. 架构视角

- 保持 Step2 负责计划、Step3 执行计划、QA 审核最终结果的职责边界。
- 不改变官方 callable、CLI、脚本入口、参数默认值、字段语义、阈值、排序或正式输出集合。
- 允许的优化仅包括：只读输入复用、内容寻址且有界的缓存、同一轮不变上下文复用、验证模式下避免非最终的正式发布、最终结果一次性发布，以及可证明等价的重复审计消除。
- 禁止跳过 final topology hard gate、surface topology、ownership、construction、unreplaced attribution 或任何正式审计；禁止减少候选、抽样、降低精度或 silent fix。
- 不新增 repo 入口，不修改项目级源事实，不触及 Retired T02。

## 3. 研发视角

- **FR-001**: 当前版本业务/性能基线必须由提交 `c26b760e6d0e945db6e2fc44885841e136b4a78e` 的六例实跑产生。
- **FR-002**: 业务基线必须覆盖 Step1/2 漏斗、replaceable/rejected、replacement plan/problem registry、Step3 relation/source mix、F-RCSD Road/Node、RCSD replacement rate、最终归因、final topology fail 和 surface audit。
- **FR-003**: 性能基线必须记录 Step1/2、Step3、T06 总 wall time、CPU time 与 peak RSS；失败或混合旧 Step1/2 的 run 不得作为业务基线。
- **FR-004**: 正式冻结性能目标根为 `outputs/baselines/t10_full_96b0ea5_20260710_060735/t10/e2e_full/cases`。
- **FR-005**: Step3 逐例目标为：`1885118 <= 170.562s`、`605415675 <= 69.407s`、`609214532 <= 136.368s`、`706247 <= 51.197s`、`74155468 <= 29.287s`、`991176 <= 33.100s`；六例合计 `<= 489.920s`。最终以冻结 stage JSON 的未舍入值重算。
- **FR-006**: Step1/2 同样按冻结 stage JSON 逐例和合计判定；不得只用 Step3 达标替代 T06 总性能达标。
- **FR-007**: 优化结果与当前版本业务基线的结构化正式业务差异必须为 0；只允许忽略 run id、绝对路径、时间戳、duration、PID、日志路径和性能观测字段。
- **FR-008**: 优化后 peak RSS 不得高于当前版本基线；不得引入随 hard-gate/surface 重放次数单调增长的无界缓存，目标优先维持或低于既有约 `600-700 MB` 等级。
- **FR-009**: 所有实现位于隔离工作树，正式基线只读，输出进入独立 `outputs/_work` 根。
- **FR-010**: 写入任何源码/脚本前必须记录当前 bytes；如体量审计表事实变化，必须同轮更新 `code-size-audit.md`。
- **FR-011**: 不新增依赖、不改变 Python 3.10/WSL 正式执行口径。

## 4. 测试视角

- 先补 characterization/contract tests，证明重复阶段的输入不变条件和最终发布边界。
- 候选实现先运行 T06 相关单元与契约测试，再运行 `1885118`。
- `1885118` 必须同时通过结构化业务等价、CRS、拓扑、几何、审计、性能、内存七类门禁。
- `1885118` 完全通过后才按固定顺序回归其余五例；任一例回退即停止扩大回归并定位。
- 最终六例比较不得只比较文件 SHA；GPKG 按 layer/CRS/schema/feature/attribute/normalized geometry 比较，CSV/JSON 按稳定业务语义比较。

## 5. QA 视角

- **CRS**：输入输出 CRS 与基线一致，任何转换仍由现有模块逻辑执行。
- **拓扑**：`final_frcsd_topology_fail_count` 不增加，hard-gate 不跳过，不 silent fix。
- **几何语义**：正式几何、road/node 归属、relation 与 source mix 完全等价。
- **审计追溯**：记录 commit、工作树、命令、输入根、输出根、环境、耗时、RSS 和比较报告。
- **性能**：逐例和合计双门禁；冷/热缓存和系统负载写入报告，不剔除慢例。

## 6. Success Criteria

- **SC-001**: 六例当前版本业务/性能/内存基线完整且机器可读。
- **SC-002**: 优化后的六例正式业务差异数为 0，所有用例状态为 passed。
- **SC-003**: 优化后的 Step1/2、Step3 与 T06 总耗时逐例及合计均不高于冻结正式基线。
- **SC-004**: peak RSS 不高于当前版本基线，且无 OOM、swap 风险或无界缓存增长。
- **SC-005**: `1885118` 先通过，随后五例按固定顺序通过。
- **SC-006**: 无接口、入口、字段语义、阈值、依赖或正式输出契约变化。
