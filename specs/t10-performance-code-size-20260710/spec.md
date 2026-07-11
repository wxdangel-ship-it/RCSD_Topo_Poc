# Feature Specification: T10 六用例无损性能优化与 60 KB 架构收敛

**Feature Branch**: `codex/t10-performance-60pct-20260710`
**Created**: 2026-07-10
**Status**: Ready for planning
**Input**: 用户要求基于当前正式 T10 六用例基线，在业务结果完全不变的前提下，将六用例端到端总耗时降至基线的 60% 以内，并把除已废弃 T02 外的所有受治理源码/脚本文件控制在 60 KB 以下；所有变更在临时工作树完成，优先以 `1885118` 回归，阶段完成后再回归六用例。用户于 2026-07-11 明确授权 T02 不拆分。

## 1. 产品视角

### User Story 1 - 六用例端到端性能达标 (Priority: P1)

作为端到端链路维护者，我需要知道六用例的性能消耗分布，并在不改变任何业务结果的前提下，将总耗时压缩到正式基线的 60% 以内，以便后续全量运行具备可持续的时间成本。

**Why this priority**: 性能目标是本轮首要业务成果，且必须由完整六用例实测证明，不能以理论估算代替。

**Independent Test**: 在与正式基线可比的 Windows/WSL 主机、同一输入 package、同一配置和同一执行顺序下运行六用例，汇总九个正式阶段的 `duration_seconds`，结果不高于 `1991.604s`。

**Acceptance Scenarios**:

1. **Given** 正式基线六用例阶段耗时合计为 `3319.340s`，**When** 优化版本完成六用例回归，**Then** 九阶段合计耗时必须 `<= 1991.604s`。
2. **Given** 当前耗时主要集中在 T03、T04、T06 Step3，**When** 形成性能报告，**Then** 必须给出 Case、阶段、模块、优化点和前后耗时占比，而不是只给总耗时。
3. **Given** 性能存在缓存和系统噪声，**When** 给出达标结论，**Then** 必须保留原始 stage JSON/CSV、运行环境和总计计算过程。

### User Story 2 - 业务结果完全不变 (Priority: P1)

作为业务结果使用者，我需要确认本轮只改变执行成本和代码组织，不改变 T01-T09 的算法规则、字段语义、正式接口或正式产物内容。

**Why this priority**: 任何无法证明业务等价的性能收益都不能进入最终交付。

**Independent Test**: 对同一代码业务版本的未优化参考 run 与优化 run 执行结构化产物比较，证明阶段状态、schema、记录、属性、几何/拓扑、关键业务指标完全一致；只忽略运行时间、时间戳、绝对路径、日志路径和 run id 等非业务字段。

**Acceptance Scenarios**:

1. **Given** 正式基线代码为 `96b0ea5`，当前 `main` 已包含后续 T09 正式业务演进，**When** 建立等价参考，**Then** 先运行当前 `main` 未优化参考并登记其相对正式基线的既有差异，本轮优化必须与该同业务版本参考完全一致。
2. **Given** GPKG 物理字节可能因 SQLite 元数据或写入顺序不同，**When** 比较业务结果，**Then** 必须比较 layer/schema/feature/attribute/normalized geometry，而不能只比较文件 SHA256。
3. **Given** GIS 与拓扑链路不允许 silent fix，**When** 优化或拆分实现，**Then** CRS、拓扑审计、几何语义和审计证据必须与参考结果一致。

### User Story 3 - 全仓 60 KB 安全线收敛 (Priority: P1)

作为仓库维护者，我需要所有纳入治理的源码和脚本低于 60 KB，避免文件继续逼近或突破 100 KB 硬阈值，并让后续功能迭代有清晰的职责边界。

**Why this priority**: 当前已有 55 个文件达到或超过 60 KB，其中 6 个超过 100 KB；这已是跨模块结构债，不能只处理本轮性能热点。

**Independent Test**: 对 `git ls-files` 中扩展名为 `.py/.sh/.cmd/.ps1/.ts/.js/.bat` 的文件逐一读取字节数；排除 `src/rcsd_topo_poc/modules/t02_junction_anchor/` 与 `tests/modules/t02_junction_anchor/` 后，所有文件必须 `< 61440 bytes`。

**Acceptance Scenarios**:

1. **Given** 某文件已经超过 100 KB，**When** 本轮拆分它，**Then** 必须先记录当前字节数，同轮更新 `docs/repository-metadata/code-size-audit.md`，并保持原有 import/callable/CLI 调用面。
2. **Given** 某文件位于 Retired T02，**When** 执行本轮 60 KB 收敛，**Then** 按用户授权排除该模块源码及其测试，不做拆分、不恢复业务职责；非 T02 tests 仍纳入 60 KB 验收且不得改写测试意图。
3. **Given** root `scripts/` 是正式入口，**When** 拆分入口脚本，**Then** 原脚本名、参数、环境变量和退出语义保持不变；新实现优先下沉到非入口 helper，不新增正式调用面。

### User Story 4 - 分阶段隔离回归 (Priority: P2)

作为迭代执行者，我需要在临时工作树中先用 `1885118` 快速验证每个 T10 主链模块的变化，只有大阶段完成后才运行完整六用例，避免频繁全量回归并污染主仓库。

**Independent Test**: 工作树、分支、run root、每轮 `1885118` 结果和阶段性六用例结果均可定位；主仓库保持干净。

**Acceptance Scenarios**:

1. **Given** 变更影响 T01/T03/T04/T05/T06/T07/T09/T10 主链，**When** 完成一个可独立验证的修改，**Then** 先运行对应单元/模块测试和 `1885118` 相关阶段或端到端回归。
2. **Given** 一个大阶段已完成，**When** 单例门禁全部通过，**Then** 再执行六用例完整回归。
3. **Given** 变更只涉及 T02/P01/T08/T11 或不进入 T10 六用例的代码，**When** 验证该变更，**Then** 使用对应模块契约测试；不得把 `1885118` 伪装成未覆盖模块的验证证据。

## 2. 架构视角

- T10 仍只负责编排和证据组织，不修改 T01-T09 算法事实。
- 拆分采用“原文件保留 facade/public surface，内部职责下沉到专用模块”的兼容策略。
- 不新增 repo CLI、Makefile 目标、root `scripts/` 正式入口、模块 `run.py` 或 `__main__.py`。
- 不改变任何 `INTERFACE_CONTRACT.md` 已登记签名、CLI 参数、环境变量、文件名、schema 或字段语义。
- 性能优化只允许等价变换：消除重复 I/O/解析/投影、复用空间索引或只读上下文、批量化等价运算、缩小重复物化范围，以及证明输出顺序稳定的安全并发。
- 禁止用放宽门禁、减少候选、抽样、跳过审计、改变精度、静默修复几何或减少正式输出换取性能。

## 3. 研发视角

### Functional Requirements

- **FR-001**: 必须从三个 `LATEST_T10*BASELINE.txt` 指针核验同一正式基线根，并记录基线代码、六用例清单和基线阶段耗时。
- **FR-002**: 必须在当前 `main` 业务版本上生成未优化 `1885118` 和六用例参考 run；若当前 main 与 `96b0ea5` 正式基线存在既有业务差异，必须单独登记，不能归因于本轮优化。
- **FR-003**: 必须输出按 Case、stage、module 聚合的性能分布，以及总耗时计算过程。
- **FR-004**: 最终六用例九阶段耗时合计必须 `<= 1991.604s`。
- **FR-005**: 优化 run 与同业务版本未优化参考 run 的正式业务结果必须完全一致；允许忽略字段仅限 run id、时间戳、绝对路径、日志路径和 duration/performance 字段。
- **FR-006**: 除 `src/rcsd_topo_poc/modules/t02_junction_anchor/` 与 `tests/modules/t02_junction_anchor/` 外，所有 tracked `.py/.sh/.cmd/.ps1/.ts/.js/.bat` 文件必须 `< 61440 bytes`。
- **FR-007**: 在写入任何源码/脚本文件前必须记录其当前字节数；新文件必须先确认不存在或为 0 bytes。
- **FR-008**: 对任何当前 `>= 102400 bytes` 的文件执行拆分时，必须同轮更新 `docs/repository-metadata/code-size-audit.md`。
- **FR-009**: 必须保持所有已登记 callable、import surface、CLI、root script 参数、环境变量、退出码和输出契约不变。
- **FR-010**: 不得新增依赖，不得改变 `pyproject.toml`、`uv.lock` 或标准 Python 3.10 执行口径，除非出现无法规避的新事实并按 AGENTS §1 停机回报。
- **FR-011**: T10 主链变更先通过对应模块测试和 `1885118` 回归；大阶段完成后再进行六用例回归。
- **FR-012**: 所有源码、SpecKit 工件和运行输出必须位于隔离工作树或独立 `_work` run root；不得覆盖正式基线。
- **FR-013**: GIS/拓扑验证必须显式覆盖 CRS、拓扑一致性、几何语义、审计可追溯性和性能可验证性。
- **FR-014**: 不得根据性能样本反推或修改字段语义、业务门禁或算法强规则。

## 4. 测试视角

- 每次拆分先补或确认 import/contract/characterization tests，再移动实现。
- T10 主链每个模块变更至少执行相关单元测试、契约测试和 `1885118` 对应阶段回归。
- 每个大阶段执行六用例端到端回归；最终回归必须全部 `passed`。
- 业务等价比较至少覆盖：stage status、正式 CSV/JSON、GPKG layer/schema/feature/attributes/normalized geometry、T06 funnel/replacement/topology audit、T09 正式 restriction 输出。
- 性能验证读取 stage JSON/CSV 的 `duration_seconds`，同时保留整体 wall-clock，避免只用单一顶层续跑 summary。
- 文件体量验证必须使用 tracked-file 全量枚举，不使用 `code-size-audit.md` 的旧快照代替实时扫描。

## 5. QA 视角

- **CRS**：输入/输出 CRS、转换目标和 CRS 审计状态必须与参考 run 一致。
- **拓扑**：topology connectivity/surface topology/road-node integrity 不得新增 fail，不执行 silent fix。
- **几何语义**：feature 数、稳定排序后的属性与 normalized geometry 必须一致；比较器允许仅在规范化阶段使用 `1e-7 m` 网格消除跨写入路径的浮点 1 ULP 噪声，生产输出精度、拓扑与几何不得因此改变。
- **审计追溯**：基线根、代码提交、工作树、命令、环境、参数、run root、日志和比较报告可定位。
- **性能**：最终结论必须同时给出基线 `3319.340s`、目标 `1991.604s`、实测总耗时和逐阶段变化。

## 6. Edge Cases

- 正式 T10 顶层 summary 只代表最后四 Case 续跑，六用例基线耗时必须读取根级 `case_stage_status_baseline.csv` 与六个 Case 级 manifest。
- 当前 main 的 T09 业务版本晚于正式基线，必须建立同业务版本 reference，不能要求优化代码回退已正式合入的业务能力。
- Windows 主仓库与 WSL 路径必须先做可逆换算并验证存在性。
- 文件刚好等于 `61440 bytes` 视为未通过，必须严格小于 60 KiB。
- 并发优化如改变输出顺序、浮点归约顺序或资源竞争结果，视为不等价，必须撤回或增加稳定化处理。
- 冷/热文件缓存可能影响实测；报告必须记录运行顺序，达标必须来自完整实跑而非剔除慢 Case。

## 7. Success Criteria

- **SC-001**: 六用例九阶段合计耗时 `<= 1991.604s`，相对正式基线耗时下降至少 40%。
- **SC-002**: 六用例全部 `passed`，优化 run 与同业务版本未优化 reference 的正式业务结果差异数为 0。
- **SC-003**: 全仓当前受治理 tracked 文件重新扫描并排除 Retired T02 路径后，`>= 61440 bytes` 文件数为 0，`>= 102400 bytes` 文件数为 0；T02 剩余结构债继续由 `code-size-audit.md` 登记但不在本轮整改范围。
- **SC-004**: `1885118` 在每个 T10 主链大阶段均通过业务等价门禁。
- **SC-005**: 无新增正式入口、无接口签名变化、无字段语义变化、无依赖变化。
- **SC-006**: 性能、文件体量、业务等价、GIS/拓扑和运行环境均有机器可读证据。
