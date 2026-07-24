# Feature Specification: P05 神经网络 F-RCSD 直出 POC M1

**Feature Branch**: `codex/p05-neural-road-poc-20260721`  
**Created**: 2026-07-21  
**Status**: Completed - M2 no-go  
**Input**: 以冻结的 P05 M0 run 为唯一数据索引，建立无泄漏的 Road 操作训练集、非神经网络基线和首个小型图神经网络，验证模型能否在未见业务对象上直接生成符合 T06 Step3 语义的 F-RCSD Road/Node。

## User Scenarios & Testing

### User Story 1 - 从冻结 M0 构建无泄漏的可学习 RoadGraph (Priority: P1)

作为 P05 实验负责人，我希望 M1 只消费通过 M0 integrity gate 的 RoadGraph truth，把 T01 Road、T05 RCSD Road/Node 和 T03/T04/T07 语义证据组织成模型输入，把 T06 最终 Road/Node 组织成带可信权重的结构化监督，并阻止相同 Road/Node 实体跨 train/validation/test 泄漏。

**Independent Test**: 对冻结 run 生成 M1 dataset manifest，逐项验证输入 hash、候选来源、操作标签、标签权重、Case split、实体泄漏 mask 和异常清单。

**Acceptance Scenarios**:

1. **Given** M0 `road_graph=true` 样本，**When** 构建候选 Road，**Then** 候选只能来自对应 Case run 的 `t01_roads` 与 `t05_rcsdroad_out`，且全部路径与 SHA-256 写入 M1 manifest。
2. **Given** T10 Case 级 truth，**When** 生成监督，**Then** Case 内全部 Road 操作使用 `0.7` 权重。
3. **Given** T10 Segment 级 truth，**When** 生成监督，**Then**目标 Segment 可追溯的 Road/父 Road 使用 `0.7`，其余上下文使用 `0.3`；找不到目标 relation 时只保留 `0.3` 上下文并记录异常。
4. **Given** 同一候选 Road ID 出现在不同 M0 split，**When** 形成训练 mask，**Then** 实体按 `test > validation > train` 唯一归属，低优先级集合不得获得该实体及其一跳邻域的监督或输入特征。
5. **Given** 用户已确认排除的样本，**When** 构建 M1，**Then** 它不得产生候选、标签、归一化统计或模型输入。

### User Story 2 - 建立可解释的规则与浅层学习基线 (Priority: P1)

作为模型评估人员，我希望先量化 `keep-all`、来源优先和无图 MLP 三类基线，避免把候选空间本身的收益误判为图神经网络收益。

**Independent Test**: 在同一 validation/test entity mask 和同一 M0 evaluator 下回放全部基线，输出逐 Case 与汇总指标。

**Acceptance Scenarios**:

1. **Given** M1 dataset，**When** 运行非神经网络基线，**Then** 每个预测都记录算法名、参数、输入 dataset hash 和逐对象置信度。
2. **Given** 无图 MLP，**When** 训练和评估，**Then** 它与图模型使用相同候选、特征、权重和 split，不允许额外消费 T06 relation 或 truth 字段。
3. **Given** 任一基线产生无效 Road/Node，**When** 评估，**Then** hard failure 计入失败，不允许 materializer 修补业务决策。

### User Story 3 - 训练首个直接生成 Road 操作的图神经网络 (Priority: P1)

作为 P05 研发人员，我希望模型从输入 RoadGraph 直接预测每条候选 Road 的 `DROP / KEEP / SPLIT_1 / SPLIT_2 / SPLIT_3`，并预测输出方向、source、端点/切分几何，使确定性物化器能够生成最终 Road/Node，而不是只预测 T06 的中间 replaceable 标记。

**Independent Test**: 在合成图上验证全部操作、加权 loss、checkpoint 可复现和物化器 no-silent-fix；在真实 validation/test 上生成 GPKG 并用 M0 evaluator 评估。

**Acceptance Scenarios**:

1. **Given** 输入候选 Road，**When** 模型推理，**Then** 输出最终 Road 操作及其置信度，禁止调用 T06 规则作为 fallback。
2. **Given** SPLIT 操作，**When** 物化 Road/Node，**Then** 子 Road 数量、方向、source、几何与端点来自模型输出及确定性几何操作；无效切分直接失败。
3. **Given** 模型 checkpoint，**When** 使用相同 seed、dataset hash 和环境重跑，**Then** 指标在声明的数值容差内可复现。

### User Story 4 - 用未见业务对象做一次性最终判定 (Priority: P1)

作为产品与 QA 负责人，我希望开发期只使用 train/validation 和开发集内部 group CV；架构冻结后才对固定 test 评估一次，并明确由于固定 test 只有 5 个 Segment Case、没有标准 T10 Case 而产生的外推限制。

**Independent Test**: 检查 tuning audit 不含 test 指标，最终评估包含固定 test、开发集 group CV 和标准 T10 shadow holdout 三层结果。

## Requirements

### Functional Requirements

- **FR-001**: M1 必须以调用方显式传入的冻结 M0 run 为唯一样本、split、标签 lineage 来源；源码不得硬编码 run ID。
- **FR-002**: M1 训练范围必须继承 M0 `task_mask.road_graph=true`，并继承 approved exclusion。
- **FR-003**: 模型输入必须来自推理时可获得的 T01/T03/T04/T05/T07 artifact；T06 Road、Node、relation 只允许用于监督和评价。
- **FR-004**: M1 必须把 `t01_roads` 作为显式输入 artifact，从 Case run handoff 解析、校验存在性、记录 SHA-256；不得从 T06 truth 反向恢复输入。
- **FR-005**: 候选 Road 空间必须由 T01 Road 与 T05 RCSD Road 的并集形成，canonical ID 不得作为数值或 embedding 特征。
- **FR-006**: 操作标签至少覆盖 `DROP`、`KEEP`、`SPLIT_1`、`SPLIT_2`、`SPLIT_3`；无法映射到输入父 Road 的 truth 必须单列 `uncovered_truth`，不得伪造父对象。
- **FR-007**: M1 必须继承 `0.7/0.3` RoadGraph 权重；T03/T04 的 `1.0` 仅允许进入 object-scene 辅助任务，不得提升 T06 RoadGraph 标签。
- **FR-008**: M1 必须实施 entity leakage guard；跨 split 重复 Road ID 及其一跳邻域不得进入低优先级 split 的模型输入或监督。
- **FR-009**: 归一化统计、类别权重、阈值和数据增强参数只能从 train 计算；validation/test 不得反向参与训练。
- **FR-010**: M1 必须提供至少两种确定性非神经基线和一种不使用图关系的 MLP 基线。
- **FR-011**: 首个图模型参数量目标为 `8M~15M`，默认约 `10M`；必须记录实际 trainable parameter count。
- **FR-012**: 图模型不得依赖 `torch_geometric` 或未声明的二进制扩展；训练依赖必须进入独立 optional dependency，不污染核心运行依赖。
- **FR-013**: 物化器只允许执行 schema 写出、模型指定的保留/删除/切分和确定性 ID 生成；不得包含 T06 业务 fallback、对象 ID 特判或 silent fix。
- **FR-014**: M1 candidate 与 truth 的最终评价必须复用 M0 `evaluate_frcsd`，覆盖 CRS、Road/Node 引用、属性、几何、有向拓扑和性能。
- **FR-015**: 固定 test 只允许在模型、阈值和物化协议冻结后运行一次；开发期采用 group CV 和 validation。
- **FR-016**: M1 必须输出逐 Case 指标、汇总指标、最差 Case、失败对象、基线差值和置信区间/折间波动，不得只报告平均值。
- **FR-017**: M1 run 必须记录输入/output hash、参数、随机种子、Python/PyTorch/CUDA/GPU、wall time、峰值 RAM/VRAM 和 `silent_fix=false`。
- **FR-018**: M1 不修改 T01-T07 正式模块，不新增 T10 stage，不接入正式主链。
- **FR-019**: M1 仅新增 P05 Python callable；不新增 repo CLI、`scripts/` 常驻入口、`__main__.py` 或 Makefile target。
- **FR-020**: GIS 实现必须显式验证 CRS、拓扑一致性、几何语义、审计追溯和性能，任何缺项均不得 close。
- **FR-021**: 产品、架构、研发、测试、QA 五类职责必须在 plan/tasks 中分别覆盖。
- **FR-022**: M1 不得因为候选无法覆盖全部 truth 而缩小最终 RoadGraph 评价分母；`uncovered_truth` 必须作为模型能力上限与失败保留。

## Success Criteria

- **SC-001**: M1 dataset 对 51 个冻结 RoadGraph truth 完整登记，approved exclusion 进入量为 `0`。
- **SC-002**: 输入 artifact hash 完整率 `100%`，T06-only 字段进入模型特征数为 `0`。
- **SC-003**: entity leakage audit 在最终 train/validation/test 输入和监督中交集为 `0`。
- **SC-004**: Road 操作表示对最终 truth 的 micro coverage 不低于 `99.9%`；未覆盖对象逐条列出。
- **SC-005**: 固定 test Road object F1 不低于 `0.85`，且相对最强确定性基线至少提升 `5` 个百分点。
- **SC-006**: 固定 test `direction_accuracy` 与 `source_accuracy` 不低于 `0.95`。
- **SC-007**: Road/Node 重复 ID、缺失端点引用和 CRS 冲突均为 `0`；有向拓扑 hard failure 为 `0`。
- **SC-008**: 每个固定 test Case Road F1 不低于 `0.70`；如未达到，M1 判定为不进入 M2，而不是用平均值掩盖。
- **SC-009**: 开发集 group CV 报告均值、标准差与最差 fold；标准 T10 shadow holdout 单独报告，不与固定 test 混算。
- **SC-010**: 相同 seed 的重复训练在 operation macro-F1 上差异不超过 `0.01`，或报告无法达到确定性的具体算子与影响。

## Non-Goals

- M1 不宣称生产可用或替代 T06。
- M1 不训练自由生成整幅坐标序列的超大模型。
- M1 不从局部样本反推上游字段强语义。
- M1 不使用 test 指标调参，也不因 test 较小而补入训练。
- M1 不自动修复 canonical truth 或模型输出拓扑。
