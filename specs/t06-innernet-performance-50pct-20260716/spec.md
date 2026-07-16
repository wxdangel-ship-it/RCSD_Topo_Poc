# Feature Specification: T06 全量内网性能恢复至当前 50%

**Feature Branch**: `codex/t06-innernet-perf-50pct-20260716`<br>
**Created**: 2026-07-16<br>
**Status**: Ready for implementation
**Input**: 用户要求基于已完成的全量内网诊断，在临时工作树中继续优化 T06；业务结果不得低于既有冻结业务基线，性能应低于既有内网冻结线，否则至少把当前全量内网 T06 耗时降低到 50%。

## 1. 产品视角

### User Story 1 - 保持冻结业务结果 (Priority: P1)

作为 T06 成果使用者，我需要优化后的 Step1/2 replacement plan、Step3 F-RCSD、relation、ownership、construction、归因和 topology/surface 审计不低于冻结结果，避免以性能为由改变正式业务成果。

**Independent Test**: 先在 `1885118` 上执行结构化产物等价和业务指标门禁，再顺序验证其余五例；全量内网新结果与 `t10_innernet_full_no_t08_20260713_154417` 对比关键计数、稳定 CSV/GPKG 语义和 QA 指标。

### User Story 2 - 全量 T06 耗时至少降低 50% (Priority: P1)

作为内网流水线维护者，我需要消除全量数据下被放大的重复 Step3 和全表嵌套扫描，使同环境、同输入、同参数的 T06 总耗时不高于当前冻结观测的 50%。

**Independent Test**: 使用内网同一 run root 输入从 T06 Step1/2 开始重跑，分别记录 Step1/2、Step3 和 T06 合计 wall time、CPU、peak RSS、swap；Step3 目标不高于 `16103.973s`，候选 Step1/2 group 与 Step3 group 的外层 wall 求和不高于 `21464.149s`。

### User Story 3 - 控制全量峰值内存 (Priority: P1)

作为运行维护者，我需要性能优化不引入无界 geometry/cache 增长，避免再次逼近 WSL 物理内存上限或触发 OOM。

**Independent Test**: 六例和内网全量运行记录 peak RSS、swap、cache size/lifecycle；全量 peak RSS 不高于当前 `9365992 KB`，且无 OOM、Killed、swap 增长风险。

### User Story 4 - 严格回归顺序 (Priority: P2)

作为迭代执行者，我需要先验证 `1885118`，完全通过后才能运行其余五例，最后才运行全量内网，避免扩大错误影响。

**Independent Test**: 运行证据顺序固定为 `1885118 -> 605415675 -> 609214532 -> 706247 -> 74155468 -> 991176 -> innernet full`。

## 2. 架构视角

- 保持 Step2 决定 replacement plan、Step3 执行 plan、QA 审计最终结果的职责边界。
- 不改变官方 callable、CLI、入口脚本签名、参数默认值、字段语义、阈值、排序和正式输出集合。
- 优先用反向索引、不可变上下文复用、连通分量索引和有界 scalar/geometry decision cache 消除复杂度。
- surface candidate、rollback、hard-gate 的业务决策必须保留；不得把“减少完整重算”实现为跳过 gate。
- 中间验证允许只物化 gate 必需结果；最终选定状态必须完整发布全部正式成果与审计。
- 不修改项目级源事实，不触及 Retired T02，不新增依赖或正式执行入口。

## 3. 研发视角

- **FR-001**: 当前代码基准为 `f870a835d5f58731279fc2a1d5d81f43584305e3`，包含 `6a1eb4e/34e5204` 和后续 T06 变更。
- **FR-002**: 当前全量 Step3 冻结耗时为 `32207.946s`；目标为 `<=16103.973s`。
- **FR-002A**: 当前全量 T06 由 launcher 起止边界和阶段日志 mtime 推算为 `42928.299s`；候选两个独立 T06 group 的精确 wall 求和目标为 `<=21464.149s`。
- **FR-003**: 当前从 T06 开始到 T11 启动的观测跨度约 `42940s`；实现必须增加精确阶段边界计时，新旧同口径比较目标为 `<=50%`。
- **FR-004**: 当前全量 peak RSS 为 `9365992 KB`、job swap 为 `0`；候选不得回退。
- **FR-005**: 当前全量业务计数至少包括 Step1 final `26027`、Step2 replaceable `19913`、replacement plan `21901`、Step3 success `18748`、F-RCSD Road/Node `145428/160160`。
- **FR-006**: 当前最终 QA 至少保持 `final_frcsd_topology_fail_count <= 15`、`surface_topology_fail_count <= 291`；不得把 audit fail 从输出中删除来满足门禁。
- **FR-007**: 六例结构化业务差异必须为 0；全量稳定业务文件使用 schema/CRS/属性/geometry 语义比较，不以原始 GPKG 文件哈希代替。
- **FR-008**: `_build_junction_states` 不得继续执行 `added nodes × all junction states` 的全量嵌套扫描。
- **FR-009**: relation context、construction audit、topology reachability 不得在相同不可变输入上重复全表扫描或重复 BFS。
- **FR-010**: cache 必须有明确 key、上限、生命周期和释放点，不跨 Case 或独立运行永久增长。
- **FR-011**: 所有改动位于独立工作树；正式基线只读；输出进入独立 `outputs/_work/t06_innernet_perf_50pct_20260716`。
- **FR-012**: 写入源码/脚本前记录当前 bytes；任何体量审计事实变化同轮更新 `code-size-audit.md`。

## 4. 测试视角

- 先补 characterization/performance tests，证明新索引和旧逐行算法在重复 ID、canonical alias、多 Segment 交集、空映射等边界上完全等价。
- 先运行 T06 定向测试，再执行 `1885118` Step1/2/3。
- `1885118` 必须通过业务、CRS、拓扑、geometry、审计、性能、内存七类门禁后才扩大到五例。
- 六例逐例比较，不得用合计更快掩盖单例业务或性能回退。
- 全量内网复跑使用同输入、同参数、同串行方式，并输出每阶段 `/usr/bin/time -v` 与 heartbeat/profile 证据。

## 5. QA 视角

- **CRS**：输入输出 CRS 与冻结基线一致，现有坐标转换逻辑不变。
- **拓扑**：final hard-gate、surface closure、ownership、construction 和 topology audit 均执行，不 silent fix。
- **几何语义**：F-RCSD Road/Node、Segment relation、source mix、owned/carrier 语义不变。
- **审计追溯**：记录 commit、工作树、输入/输出根、参数、环境、wall/CPU/RSS、比较报告和失败原因。
- **性能**：Step1/2、Step3、T06 总耗时分别记录；全量 50% 是正式完成门禁，六例只作为业务和局部性能前置门禁。

## 6. Success Criteria

- **SC-001**: `1885118` 与六例业务结构化差异为 0，所有正式输出和审计完整。
- **SC-002**: 全量内网关键业务计数不低于冻结值，final topology/surface fail 不增加。
- **SC-003**: 全量 Step3 wall time `<=16103.973s`。
- **SC-003A**: 全量 T06 Step1/2 group 与 Step3 group 的外层 wall 求和 `<=21464.149s`。
- **SC-004**: 精确计时后的全量 T06 总 wall time `<=` 当前同口径的 `50%`。
- **SC-005**: 全量 peak RSS `<=9365992 KB`，swap 为 `0`，无 OOM/Killed。
- **SC-006**: 无接口、入口、依赖、字段语义、阈值或正式输出契约变化。
