# Feature Specification: P05-R2 可完备表达的神经 RoadGraph 生成 POC

**Feature Branch**: `codex/p05-neural-road-poc-20260721`  
**Created**: 2026-07-21  
**Status**: Completed — Gate 1/2 PASS, Gate 3 NO-GO  
**Input**: M2R 已证明联合网络可拟合，但现有候选 Road 操作表示只能覆盖 `86.79%` 的 T06 truth。R2 必须先建立可精确重建真值的 Road/Node edit-set，再验证神经网络能否在无 T03-T06 业务规则推理的情况下泛化生成 T06 Step3 语义 RoadGraph。

## User Scenarios & Testing

### User Story 1 - 证明输出表示完备 (Priority: P1)

作为实验负责人，我希望把每个 RoadGraph truth 转换为显式 Road/Node edit-set，并从相同基础输入精确重建归一化 T06 F-RCSD truth，从而在训练前排除“模型永远无法表达正确答案”的问题。

**Independent Test**: 对 51 个可用 RoadGraph Case 生成 oracle edit-set、物化 Road/Node，并用冻结 M0 evaluator 逐 Case 验证语义、属性、引用和有向拓扑。

**Acceptance Scenarios**:

1. 对可从基础输入直接复用的对象生成 `COPY`，有属性、端点或几何变化时生成 `UPDATE`。
2. 对具有明确父 Road 的多个 truth child 生成 `SPLIT`，子对象和连接均显式进入 edit payload。
3. 对基础输入无法承载的 truth 对象生成 `CREATE`，不得把它静默记为 uncovered。
4. 对未进入最终 truth 的基础对象生成 `DROP`。
5. oracle 物化后，51/51 Case 的归一化 Road/Node 与有向拓扑必须完全一致。

### User Story 2 - 学习精确 T05 pointer 与图编辑内容 (Priority: P1)

作为模型研发人员，我希望 T05 Head 输出精确 `target_id -> base_id` pointer，并由图生成解码器输出 Road/Node edit-set，使模型能够学习新增对象、SPLIT、属性、端点和连接，而不是只做 endpoint membership。

**Independent Test**: 合成 fixture 与真实 small batch 分别验证 pointer 候选、edit action、存在性、属性、端点、几何和 checkpoint roundtrip，并完成 overfit 门禁。

### User Story 3 - 在 grouped OOF 上评价最终 RoadGraph (Priority: P1)

作为产品与 QA 负责人，我希望在零业务 fallback 的条件下，对完整五折 OOF 结果评价中间任务、最终 Road/Node、最差 Case、拓扑、确定性和资源，并与 keep-all/M2R 基线比较。

**Independent Test**: 每个 held-out fold 只使用未训练过相同 group/实体的 checkpoint；逐 Case 生成 free/constrained Road/Node GPKG 和完整审计。

### User Story 4 - 形成可归因的 go/no-go 结论 (Priority: P1)

作为决策者，我希望明确区分表示失败、模型不可学习、样本泛化不足和图合法性问题；任何门禁失败都必须停止后续不合理声明，但实验仍应形成正式结论。

## Functional Requirements

- **FR-001**: R2 只消费冻结的 M0/M2R supervision/dataset lineage；源码不得硬编码 run、baseline 或 Case ID。
- **FR-002**: 数据范围仍限于 `E:\TestData\POC_Data` 登记家族，并继承 approved exclusion。
- **FR-003**: 推理输入只允许 raw/T01 基础事实；T03/T04/T05/T06 truth 与 reason/status 只能作为 label/evaluation。
- **FR-004**: Road edit action 至少包含 `COPY/UPDATE/SPLIT/CREATE/DROP`；Node edit action至少包含 `COPY/UPDATE/CREATE/DROP`。
- **FR-005**: 每个输出对象必须显式记录对象 ID、几何来源、属性、端点、source、direction、父子 lineage 与置信度。
- **FR-006**: `CREATE` 必须允许表达不在候选集合中的 Road/Node；不得用 truth-derived proposal 作为推理输入。
- **FR-007**: oracle encoder 可以读取 truth 生成监督动作，但 oracle payload 必须标记为 label-only，禁止进入模型特征。
- **FR-008**: oracle materializer 只执行 edit payload 和 schema 写出，不调用 T03-T06 算法、业务 fallback 或 silent fix。
- **FR-009**: T05 必须使用精确 pointer 候选与 base existence mask；每个 target 最多一个成功 base，cardinality error 不得后处理隐藏。
- **FR-010**: T03/T04/T05/T06 为必选任务；T07 在 R2 默认关闭。
- **FR-011**: 训练继续使用 task mask、可信权重和 grouped 5-fold；group、实体及受控邻域跨 fold 交集为零。
- **FR-012**: 模型必须提供 Road/Node edit action、对象存在性、精确 pointer、属性、端点、连接与几何参数的独立 loss/指标。
- **FR-013**: 每个必选 Head 和图编辑解码器必须通过 small-batch overfit 后才能进入 OOF。
- **FR-014**: free/constrained 必须使用相同 logits；constrained 只允许通用 schema/ID/引用/有限几何/生成状态约束。
- **FR-015**: 事后业务内容修复、T06 fallback、对象 ID 特判和 silent fix 均为零。
- **FR-016**: 最终 Road/Node 继续使用冻结 M0 evaluator，等价性按归一化语义图判断，不以文件字节 hash 判断。
- **FR-017**: 所有 run 必须记录输入输出 hash、参数、seed、环境、耗时、RAM/VRAM 和失败原因。
- **FR-018**: R2 不修改 T01-T07 正式算法，不新增 repo CLI、root script、T10 stage、`__main__.py` 或 Makefile target。
- **FR-019**: 产品、架构、研发、测试、QA 五类职责必须在 plan/tasks/validation 中覆盖。
- **FR-020**: GIS 审计必须覆盖 CRS、拓扑一致性、几何语义、追溯和性能。

## Success Criteria

### Gate 1 - 表示完备

- **SC-001**: Road truth edit coverage ≥`99.9%`，Node truth edit coverage=`100%`。
- **SC-002**: oracle 重建 Road/Node semantic F1=`1.0`，51/51 Case 有向拓扑完全一致。
- **SC-003**: T05 pointer truth 可表达率=`100%`，cardinality error=`0`。
- **SC-004**: SPLIT truth 可表达率=`100%`；重复 ID、缺失引用、物化失败=`0`。

### Gate 2 - 模型可学习

- **SC-005**: T03/T04/T05/T06 及图编辑解码器 small-batch 指标均≥`0.95`。
- **SC-006**: small-batch Road/Node F1≥`0.98` 且有向拓扑完全一致。
- **SC-007**: 必选 loss 有效梯度覆盖=`100%`；Unknown 误作负样本和 label leakage=`0`。

### Gate 3 - OOF 泛化

- **SC-008**: T03 relation macro-F1≥`0.80`、surface Dice≥`0.80`；T04 relation macro-F1≥`0.75`、surface Dice≥`0.80`。
- **SC-009**: T05 精确 pointer 完全正确率≥`0.90`，cardinality error=`0`。
- **SC-010**: edit action macro-F1≥`0.75`，每类 SPLIT recall≥`0.70`。
- **SC-011**: grouped OOF Road F1≥`0.85`，高于最强基线≥`5` 个百分点，最差 Case≥`0.70`。
- **SC-012**: Node F1≥`0.90`，direction/source/endpoint accuracy 均≥`0.95`。
- **SC-013**: 有向拓扑 hard failure、物化失败、重复 ID、缺失引用、CRS hard failure均=`0`。
- **SC-014**: constrained 合法图比例=`100%`，content repair=`0`，所有 intervention 可追溯。
- **SC-015**: 重复推理的离散预测、归一化 RoadGraph 和指标完全一致。
- **SC-016**: 模型目标参数量 `20M~50M`，未经重新评估不超过 `60M`；峰值 VRAM≤`16GB`，五折训练≤`12 GPU-hours`，单 Case 推理 P95≤`60s`。

## Non-Goals

- R2 成功不等价于生产接入；生产替代必须另立 R3/full shadow run。
- R2 不要求新增人工 Case；只有 Gate 1/2 通过而 OOF 不足时才进入主动学习。
- R2 不把 truth payload、策略输出或已知结果注入推理特征。
- R2 不通过后处理业务规则修正模型内容。
