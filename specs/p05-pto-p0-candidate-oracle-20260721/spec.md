# Feature Specification: P05-PTO-P0 候选可达性与 Oracle-cost 求解

**Feature Branch**: `codex/p05-neural-road-poc-20260721`  
**Created**: 2026-07-21  
**Status**: Completed — semantic gates passed; end-to-end performance gate failed  
**Input**: R2 已证明 edit language 完备且 small-batch 可学习，但 ordinal slot-query 模型无法跨 Case 泛化。PTO-P0 在训练新模型前，验证“无 truth 候选生成 + 通用图约束 + Oracle cost”能否从有限候选中精确选出全部 51 Case 的 T06 F-RCSD RoadGraph。

## User Scenarios & Testing

### User Story 1 - 证明正确 RoadGraph 可由无真值候选到达 (Priority: P1)

作为实验负责人，我希望候选只由 raw/T01 与登记的 T03/T04/T05/T06 策略版本生成，并在完全不读取 truth 的情况下冻结，从而区分“候选根本没有正确答案”和“后续模型没有选对答案”。

**Independent Test**: 对 `E:\TestData\POC_Data` 的 51 个 RoadGraph Case 构建候选集；候选 manifest 完成后再接入 R2 label-only truth，检查 Road、最终 Node、T05 Node、SPLIT child 与 T05 pointer 的真值可达率。

### User Story 2 - 用 Oracle cost 验证约束建模可解 (Priority: P1)

作为架构与研发负责人，我希望只使用通用 schema、ID、引用、有限几何与生成状态约束，由 Oracle cost 在候选集中选出最低成本合法图，证明未来 learned scorer 有明确、有限、可验证的优化空间。

**Independent Test**: 每个 Case 物化唯一选中解，并用冻结 M0 evaluator 验证 Road/Node 对象、属性、几何语义和有向拓扑全部等于归一化 truth；求解状态为 OPTIMAL、gap=0，且没有 relaxation、content repair 或 silent fix。

### User Story 3 - 给出能否进入 PTO-P1 的正式结论 (Priority: P1)

作为产品与 QA 负责人，我希望 P0 的失败能明确归因到候选生成、约束/求解或成本，而不是直接归咎于神经网络；成功时才允许进入 grouped 5-fold learned scoring。

## Functional Requirements

- **FR-001**: 数据范围严格为现有 51 RoadGraph Case，并排除 `T10-Error / 1213556_1263661`；排除项不得出现在候选、标签、求解、评价或汇总中。
- **FR-002**: 候选生成输入只允许 raw/T01 基础事实、登记策略代码版本及其外部输入；登记的历史 T10 replay 可包含 T07 作为可选辅助预处理，但 T07 不形成独立最终候选或选择规则。不得读取 T03-T06 truth、R2 oracle edit、truth geometry、truth object ID 或评估结果。
- **FR-003**: 策略重放必须记录代码 commit、精确命令参数、输入路径/hash、输出路径/hash、运行状态与环境；候选输出路径不得与 truth 路径相同。若原 Case 缺少 runner 所需的逐 Case manifest，可在实验输出区建立只含 source-path 的 wrapper manifest，但全部 external input 仍必须解析到允许的 `POC_Data` 根内并逐文件哈希。
- **FR-004**: 候选层必须先写入不可变候选 artifact 和 manifest，再由标签/评价层读取其 hash；候选层 API 不接受 truth path。
- **FR-005**: Road 候选语言沿用 R2 `COPY/UPDATE/SPLIT/CREATE/DROP`，Node 沿用 `COPY/UPDATE/CREATE/DROP`；T05 pointer 候选含同次 T05 Node 候选图中的语义 ID 与 `NO_MATCH`。
- **FR-006**: 候选必须包含 base keep/drop 选择和登记策略重放 edit；按规范化 payload 签名去重，同时保留全部来源 lineage。
- **FR-007**: 候选规模必须有限；逐 Case 记录候选、变量、约束数量及按 corridor/component 的分布，禁止无界组合枚举。
- **FR-008**: truth 只允许在候选 manifest 冻结后生成 label-only oracle cost、coverage 和 evaluation；truth-derived feature/proposal/ID leakage 必须为零。
- **FR-009**: Oracle cost 只用于 P0 可达性证明，不是推理能力或 learned scorer；最优解必须具有可审计下界证书，optimality gap=0。
- **FR-010**: 通用约束白名单仅包括 action domain、base 引用存在、唯一输出 ID、endpoint 引用存在、有限非空几何、合法生成状态与每个 base group 唯一选择。
- **FR-011**: 禁止用 T03-T06 业务策略在求解后修图；`relaxation=false`、`content_repair=false`、`silent_fix=false`。
- **FR-012**: 物化必须复用 R2 no-rule materializer；最终评价必须复用冻结 `evaluate_frcsd`。
- **FR-013**: 相同输入、配置与策略 artifact 重复运行的候选签名、选择、归一化 RoadGraph 和指标必须完全一致。
- **FR-014**: 同时审计策略重放 wall time、候选构建+求解 wall time、端到端 wall time、CPU、RAM；GPU 不得成为依赖。
- **FR-015**: PTO-P0 不训练 scorer、不修改 T01-T07 正式算法、不新增 repo CLI/root script/T10 stage/`__main__.py`/Makefile target，也不进入生产。
- **FR-016**: 产品、架构、研发、测试、QA 五类职责必须在 plan/tasks/validation 中覆盖。
- **FR-017**: GIS 审计必须显式覆盖 CRS、拓扑一致性、几何语义、输入参数输出可追溯与性能；任何结构异常 hard fail，不允许 silent fix。

## Success Criteria

### Gate 1 - Candidate Reachability

- **SC-001**: 纳入 Case=`51/51`，排除项出现次数=`0`。
- **SC-002**: truth-derived feature/proposal/object-ID leakage=`0`；候选 manifest 与 label/evaluation manifest 分层且 hash 链完整。
- **SC-003**: Road truth `23,224/23,224`、最终 Node truth `27,553/27,553`、T05 Node truth `24,739/24,739` 可由候选表达。
- **SC-004**: T05 pointer truth `4,760/4,760`、SPLIT child truth `1,730/1,730` 可达；Road/Node/T05 Node 全 action coverage=`100%`。

### Gate 2 - Oracle-cost Constrained Solve

- **SC-005**: 51/51 Case 求解状态=`OPTIMAL`、optimality gap=`0`，且没有 relaxation。
- **SC-006**: 51/51 Case 归一化 Road object F1=`1.0`、Node object F1=`1.0`、属性准确率=`1.0`、有向拓扑 F1=`1.0`。
- **SC-007**: 重复 ID、缺失 base/endpoint 引用、空或非有限或零长几何、CRS 冲突、无效 action transition、materialization failure、content repair、silent fix 均=`0`。
- **SC-008**: 重复运行的候选 signature、selection signature、RoadGraph 归一化 signature 与全部指标一致。
- **SC-009**: 候选生成+求解单 Case P95≤`60s`、最大值≤`300s`、峰值 RAM≤`16GB`、GPU 不需要、51 Case 总 CPU time≤`2 CPU-hours`。策略重放若单独预计算，必须另报其耗时，且端到端性能不得被省略。
- **SC-010**: manifest 记录每个 Case 的候选/变量/约束数、求解证书、输入/参数/输出 hash、环境、耗时和失败原因。

## Gate Decision

- Gate 1 失败：候选生成路线 NO-GO，不进入 learned scorer。
- Gate 1 通过而 Gate 2 失败：当前约束/求解表示 NO-GO，先修正 formulation。
- Gate 1/2 均通过：允许进入 PTO-P1，使用相同候选合同训练 object-conditioned scorer，并执行 grouped 5-fold OOF。

## Non-Goals

- 不证明神经网络已生成最终 RoadGraph。
- 不以 Oracle cost 作为生产推理 cost。
- 不新增 `POC_Data` 之外数据，不要求用户补充 Case。
- 不将策略重放结果直接称为模型结果。
