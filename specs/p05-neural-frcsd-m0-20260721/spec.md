# Feature Specification: P05 神经网络 F-RCSD 直出 POC M0

**Feature Branch**: `codex/p05-neural-road-poc-20260721`  
**Created**: 2026-07-21  
**Status**: In progress  
**Input**: 仅使用 `E:\TestData\POC_Data` 本地测试用例，建立 P05 训练真值、无泄漏切分和 T06 F-RCSD Road/Node 评估基准；本里程碑不训练正式神经网络。

## User Scenarios & Testing

### User Story 1 - 把现有人工检查 Case 变成可训练真值 (Priority: P1)

作为 P05 实验负责人，我希望把 T03/T04 单点 Case、T10 Case 级和 T10 Segment 级样例统一登记为带来源、任务范围和置信权重的训练样本，使模型训练不会把目标对象、上下文对象和纯规则产出混为同等真值。

**Independent Test**: 扫描指定 `POC_Data` 根与 canonical T10 baseline 后，逐条检查样本的 `sample_group_id`、scope、target、任务 mask、标签权重、输入 hash 和标签 lineage。

**Acceptance Scenarios**:

1. **Given** T03/T04 单点 Case，**When** 建立训练索引，**Then** 目标对象以 `1.0` 登记为逐对象人工确认/修正，缺少 surface/relation 文件时对应几何任务保持 masked，不补造标签。
2. **Given** T10 Case 级 Case，**When** 找到 passed canonical T10 run，**Then** 整体 Case 以 `0.7` 登记，并绑定 T06 F-RCSD Road/Node 主标签及 T01-T06 可用辅助标签。
3. **Given** T10 Segment 包，**When** 解析 `scope.swsd_segment_id`，**Then** 目标 Segment 及其可追溯 Road/Node 使用 `0.7`，其它上下文使用 `0.3`；无法归属时不得靠空间邻近提升权重。
4. **Given** 输入不位于 `E:\TestData\POC_Data`，**When** 严格范围模式运行，**Then** 构建器必须阻断，不得纳入本次实验。

### User Story 2 - 建立无泄漏的 grouped benchmark (Priority: P1)

作为模型评估人员，我希望同一 mainnode、Segment、Case 及其不同归档版本始终落入同一 fold，使验证结果不能通过相邻对象或重复版本泄漏获得虚高指标。

**Independent Test**: 对重复 mainnode/Segment 构造多个版本，重复生成 split 并验证同组同 fold、不同运行结果完全确定、train/validation/test 交集为空。

**Acceptance Scenarios**:

1. **Given** T03/T04 或 T10 中存在相同业务 ID 的不同版本，**When** 建立五折分组，**Then** 所有版本使用同一 `sample_group_id` 和 fold。
2. **Given** 相同输入、seed 和 schema，**When** 重复构建，**Then** manifest、fold 和摘要保持确定性。
3. **Given** 缺失 manifest、重复 ID、标签冲突或不可追溯 run，**When** 构建结束，**Then** 对象进入异常清单并带结构化原因，不得静默删除。

### User Story 3 - 用统一评估器判断 P05 Road 是否符合 T06 语义 (Priority: P1)

作为 GIS/拓扑 QA，我希望对任意 P05 candidate Road/Node 与 canonical T06 F-RCSD Road/Node 做同一套几何、属性和拓扑比较，并能先用真值自比较证明评估器正确。

**Independent Test**: 使用小型合成 RoadGraph 执行 truth-vs-truth Oracle，再分别删除 Road、反转方向、改变 source、移动端点和断开 Node，验证对应指标和 hard gate 必须失败。

**Acceptance Scenarios**:

1. **Given** truth 与自身，**When** Oracle 回放，**Then** Road/Node precision、recall、F1 和关键属性准确率均为 `1.0`，几何误差在序列化容差内为 `0`，新增 hard fail 为 `0`。
2. **Given** candidate 缺 Road、方向错误、source 错误或端点 Node 缺失，**When** 评估，**Then** 分别降低相应指标并输出可定位对象。
3. **Given** CRS 缺失或不一致，**When** 未提供安全且显式的处理策略，**Then** 评估必须阻断，不能隐式混算。

## Requirements

### Functional Requirements

- **FR-001**: 系统必须新增独立 `p05_neural_road_generation` POC 模块；本轮正式范围仅为 M0 数据与度量基准。
- **FR-002**: P05 最终 Road 语义必须定义为 T06 Step3 F-RCSD Road/Node，不得混用其它 POC RoadGraph 语义。
- **FR-003**: M0 输入测试用例必须严格限定在 `E:\TestData\POC_Data`；`POC_QA`、内网路径及无法追溯到该根的数据不得纳入。
- **FR-004**: 系统必须把 T03/T04 单点目标登记为 `1.0` 强对象标签；缺失具体几何/关系标签时 task 必须 masked。
- **FR-005**: 系统必须把 T10 Case 级样例登记为 `0.7` 整体 Case 标签。
- **FR-006**: 系统必须把 T10 Segment 级目标 Segment 登记为 `0.7`，其它上下文登记为 `0.3`；目标只允许由 manifest ID 与 T06 lineage 判定。
- **FR-007**: 每个样本必须记录输入 manifest/hash、source root、scope、target、label run、label artifact/hash、task mask、置信权重和异常状态。
- **FR-008**: canonical T10 标签必须来自调用方显式提供的 baseline/run root；生产实现不得硬编码当前 baseline 目录名或 Case ID。
- **FR-009**: 只有 passed、Road/Node/必要 lineage 存在且通过 Road-Node integrity gate 的 T10 run 才能作为最终 Road 主标签；其它情况必须进入异常清单并关闭对应 RoadGraph task mask。
- **FR-010**: 相同 mainnode、Segment、Case 及重复版本必须共享稳定 `sample_group_id`，并在 grouped split 中处于同一 fold。
- **FR-011**: 系统必须输出确定性五折分组及一个固定 train/validation/test 视图；不得按 feature row 随机切分。
- **FR-012**: 系统必须显式审计重复 ID、不同 checksum、缺失 manifest、缺失标签、冲突标签和跨 split 泄漏。
- **FR-013**: 系统必须提供 T06 F-RCSD Road/Node 评估器，至少覆盖对象召回、方向、source、端点、几何、Road-Node 引用和有向拓扑。
- **FR-014**: 评估器必须支持 identity-first 匹配；几何 fallback 必须确定性、一对一并保留匹配原因，不能静默改变输入。
- **FR-015**: 系统必须执行 CRS、拓扑、几何语义、审计可追溯性和性能五类检查。
- **FR-016**: M0 输出必须写入新的 run root，不得覆盖输入、baseline 或既有结果。
- **FR-017**: P05 不得修改 T01-T06 代码、契约或成果；这些模块在 M0 中只读提供标签。
- **FR-018**: M0 不新增 PyTorch 等训练依赖，不新增 repo CLI/root script/Makefile 目标；只提供模块内 callable 和 SpecKit 验证脚本。
- **FR-019**: 所有源码/测试文件写入前与写入后必须满足仓库 `<100KB` 硬约束和 code-size audit 同步要求。
- **FR-020**: 运行必须输出机器可读 manifest、样本表、标签表、split、异常表、Oracle/benchmark summary 和中文报告。
- **FR-021**: 数据异常不得 silent fix；无法自动裁定的冲突应进入可交付给用户的人工复核清单。
- **FR-021A**: 用户确认排除必须参数化记录 family、business ID、理由与 decision source；样本保留 lineage 与 split assignment，但关闭全部训练 task mask，不得在算法中硬编码 Case ID。
- **FR-022**: 项目/模块源事实、生命周期、模块盘点和 SpecKit 必须在同轮保持一致。

### Key Entities

- **TrainingSample**: 一个 T03/T04 单点或 T10 Case/Segment 样本及其 scope、target、权重和 task mask。
- **LabelArtifact**: 可追溯的 T01-T06 文件标签及 hash、状态和角色。
- **SampleGroup**: 用于去重和防泄漏的 mainnode/Segment/Case 业务组。
- **SplitAssignment**: 确定性五折及固定 train/validation/test 视图。
- **RoadGraphEvaluation**: candidate 与 truth 的对象、几何、属性和拓扑比较结果。
- **M0Run**: 一次不可覆盖的数据构建与评估运行。

## Assumptions

- 用户已授权将范围内样例作为带噪人工真值，并接受 `1.0/0.7/0.3` 分级。
- T03/T04 Case 目录本身证明目标对象被人工确认；具体 surface/relation 几何监督只在 artifact 可追溯时启用。
- T10 baseline 是标签来源而不是输入范围；其 source root 必须能回指 `E:\TestData\POC_Data`。
- M0 只建立训练与度量基础，不宣称神经网络已训练或 Road 直出已达到 POC 指标。

## Success Criteria

- **SC-001**: 范围内预期 Case 清点率 `100%`，所有未纳入项都有结构化原因。
- **SC-002**: 每个可用样本的来源、scope、target、权重、task mask 和 label lineage 完整率 `100%`。
- **SC-003**: T10 Segment manifest 目标 Segment ID 解析率 `100%`。
- **SC-004**: 重复业务组跨 fold/train/validation/test 泄漏数为 `0`。
- **SC-005**: 同配置重复运行生成的排序、group 和 split 完全一致。
- **SC-006**: 数据归档新增 CRS 混算、非法几何或拓扑修改数量为 `0`，`silent_fix=false`。
- **SC-007**: 可训练样本比例不低于 `95%`；低于门槛时 M0 不得标记完成。
- **SC-008**: 通过 truth integrity gate 的可用样本，其 Oracle truth-vs-truth Road/Node precision、recall、F1、direction/source accuracy 均为 `1.0`，新增 hard fail 为 `0`；truth 自身存在 hard fail 的样本必须隔离并单列，不得计入可训练分母。
- **SC-009**: 人为破坏测试对缺 Road、方向/source 错误、端点缺失和拓扑断裂的检出率为 `100%`。
- **SC-010**: 100% 运行记录输入 hash、参数、环境、输出、耗时、对象量和 `silent_fix=false`。
