# Feature Specification: P05 多任务神经 F-RCSD 直出 POC M2R

**Feature Branch**: `codex/p05-neural-road-poc-20260721`  
**Created**: 2026-07-21  
**Status**: In Progress  
**Input**: 在 M1 直接 Road 操作模型未达门槛后，改为由同一神经网络系统学习 T03、T04、T05、T06 分层语义，可选学习 T07，最终生成符合 T06 Step3 F-RCSD 语义的 RoadGraph。推理时不执行 T03-T06 业务规则，只允许通用图合法性约束。

## User Scenarios & Testing

### User Story 1 - 建立跨模块人工真值合同 (Priority: P1)

作为实验负责人，我希望把限定 `E:\TestData\POC_Data` 中 T03/T04 单点 Case、T10 Case 和 T10 Segment Case 映射为 T03/T04/T05/T06 任务级标签，并明确 `Gold/Silver/Unknown`、权重、任务 mask、CRS 和 artifact lineage，使缺失标签不会被误当成负样本。

**Independent Test**: 对冻结 M0 run 和限定数据根生成 M2R supervision manifest；逐样本验证标签来源、hash、scope、fold、task mask、缺失原因和排除项。

**Acceptance Scenarios**:

1. **Given** T03/T04 单点 Case，**When** 找不到可追溯的历史 surface/relation artifact，**Then** 可按用户 2026-07-21 的明确授权调用当前正式策略重放；成功和失败业务终态均为人工确认真值，但必须保留输入 manifest、代码版本、参数和输出 hash，且不得把 `runtime_failed` 当作业务 rejected。
2. **Given** T10 Case 级人工通过 Case，**When** 构建 T05/T06 监督，**Then** 使用完整 Case truth 和 `0.7` 权重。
3. **Given** T10 Segment 级 Case，**When** 构建监督，**Then** 指定 Segment 及可追溯对象使用 `0.7`，其余上下文使用 `0.3`。
4. **Given** `T10-Error/1213556_1263661`，**When** 构建任意任务，**Then** 它不得进入特征、标签、归一化统计和评价分母。
5. **Given** 同一业务对象的多个归档版本，**When** 分配 fold，**Then** 全部版本必须位于同一 fold。

### User Story 2 - 学习 T03/T04/T05/T06 分层语义 (Priority: P1)

作为模型研发人员，我希望使用共享几何/拓扑编码器和任务专用 Head 学习 T03、T04、T05、T06；各任务只在自身有真值的样本上计算 loss，并可独立评价，避免把最终 RoadGraph 的失败全部压给单一输出 Head。

**Independent Test**: 每个必选 Head 在合成 fixture 和真实 grouped fold 上分别完成前向、loss、small-batch overfit、checkpoint roundtrip 和逐任务指标评价。

**Acceptance Scenarios**:

1. **Given** 部分标签样本，**When** 训练联合模型，**Then** 缺失任务 loss 为零且不产生伪标签。
2. **Given** T03/T04 Case，**When** Head 输出状态、关系或 surface，**Then** 输出可按人工真值独立评价，非法几何直接失败。
3. **Given** T05 relation 标签，**When** Head 输出 relation，**Then** 每个 target 最多一个成功 base，cardinality error 不被后处理隐藏。
4. **Given** T06 RoadGraph 标签，**When** 最终 Head 输出 Road 内容，**Then** SPLIT、方向、source、端点和连接选择均来自模型。

### User Story 3 - 对比自由解码与通用图约束解码 (Priority: P1)

作为架构与 QA 负责人，我希望用同一 checkpoint 和同一概率输出比较完全自由解码与通用图约束解码，区分业务语义学习失败和形式图合法性失败。

**Independent Test**: 对每个 out-of-fold Case 同时生成 free/constrained 两组结果，输出原始选择、约束屏蔽、物化 Road/Node、逐 Case 指标和 hard failure。

**Acceptance Scenarios**:

1. **Given** free decoder，**When** 模型产生非法引用或非法操作序列，**Then** 直接计失败，不自动修复。
2. **Given** constrained decoder，**When** 候选操作违反通用图 schema、引用或生成语法，**Then** 只屏蔽该非法操作并记录审计。
3. **Given** 任一 decoder，**When** 生成结束，**Then** 不允许事后使用业务策略增加、删除或重连 Road。
4. **Given** 两组结果，**When** 汇总，**Then** 分别报告 Road 语义、原始合法率、最终合法率、约束触发率和内容变更率。

### User Story 4 - 评估可选 T07 辅助任务 (Priority: P2)

作为产品负责人，我希望 T07 不阻塞主实验，并通过消融决定其是否保留，而不是凭直觉纳入最终模型。

**Independent Test**: 在相同 grouped folds、seed 和主模型配置下比较不含 T07 与包含 T07 的 out-of-fold 指标。

### User Story 5 - 形成可复现的 POC 结论 (Priority: P1)

作为产品、测试和 QA 负责人，我希望最终结论可以区分数据不足、标签表达问题、分层任务不可学习、最终解码问题以及自由生成与约束生成的差异，并保留逐 Case 证据。

**Independent Test**: 逐项核对数据门禁、中间 Head、最终 RoadGraph、GIS、拓扑、资源和复现指标，形成 go/no-go validation summary。

## Edge Cases

- 单点 Case 只有输入 bundle，没有可追溯历史 surface/relation 输出；按本轮授权生成带完整 lineage 的策略重放真值。
- `Error` 目录包含已修正回归 Case，目录名不能直接作为负类。
- 同一 `mainnodeid` 或 Segment 在正常集、Error 集及归档 run 中重复出现。
- T03/T04 geometry CRS 相同但字段 schema 或 ID 类型不同。
- T10 Segment relation 缺失，只能使用 `0.3` 上下文监督。
- 模型给出高置信业务选择，但该选择导致 dangling endpoint、重复 ID 或非法生成序列。
- 通用约束屏蔽后没有任何合法候选；必须失败，不得回退到 T06 规则。
- 某个任务的关键类别无法分布到至少三个独立 fold；该任务不得宣称可泛化。

## Requirements

### Functional Requirements

- **FR-001**: M2R 必须显式消费冻结 M0 run；源码不得硬编码 run ID、baseline ID 或具体 Case ID。
- **FR-002**: M2R 数据范围严格限制为 `E:\TestData\POC_Data` 中已登记家族，并继承 approved exclusion。
- **FR-003**: 模型必须学习 T03、T04、T05、T06 四个必选任务；T07 只能作为可关闭的辅助任务。
- **FR-004**: T01 保持推理时基础输入/数据准备边界，不作为 M2R 业务 Head。
- **FR-005**: 推理时不得执行 T03、T04、T05、T06 的业务规则、规则 fallback、对象 ID 特判或 silent fix。
- **FR-006**: 训练标签可以来自人工确认后的正式模块产物；输入特征不得包含当前样本对应的目标标签、T06 reason/status 或其它 label leakage 字段。
- **FR-007**: 每个标签必须登记 `task_name/target_kind/trust_tier/weight/scope/artifact_path/hash/crs/source_run`。
- **FR-008**: `Unknown` 标签必须由 task mask 排除，禁止作为 0、negative 或 rejected 参与 loss。
- **FR-009**: `T03_Error/T04_Error` 目录名不得直接生成类别标签。
- **FR-010**: T03/T04 无可追溯 surface/relation 时，可使用用户确认的当前正式策略重放；只接纳输入 manifest 精确匹配且具有正式业务终态的标签，运行失败保持无标签。
- **FR-011**: 同一业务对象及其归档版本必须共享 `sample_group_id`；跨 train/validation/test 的 group、实体及受控邻域交集为零。
- **FR-012**: M2R 必须使用 grouped out-of-fold 预测作为主要泛化证据；已访问的 M1 五 Case 固定 test 只作历史回归，禁止调参。
- **FR-013**: 联合模型必须采用任务 mask 和可信权重；每个 Head 的 loss、样本量和梯度贡献必须单独审计。
- **FR-014**: 必选 Head 必须提供 small-batch overfit 测试；失败时不得进入最终模型归因。
- **FR-015**: Surface 输出必须显式记录 CRS，并评价几何有效性、连通性、Dice/IoU 和米制边界误差。
- **FR-016**: T05 relation 输出必须执行 target 唯一成功 relation 与 base 存在性审计。
- **FR-017**: T06 最终 Road 内容至少覆盖 Road operation、direction、source、split/endpoints 和有向连接。
- **FR-018**: Road 几何允许从模型选择的输入 Road/Segment 无损组合；SPLIT geometry 只能来自模型输出及确定性几何执行，不允许业务规则补形。
- **FR-019**: free decoder 不使用任何确定性结构约束；constrained decoder 只使用合同白名单中的通用图约束。
- **FR-020**: constrained decoder 不得包含 Segment-to-Road 归属、SPLIT、方向、主路、路口映射或连通补路等业务判断。
- **FR-021**: 事后内容修复次数必须为零；所有约束触发必须记录被屏蔽动作、原因、替代动作和模型分数。
- **FR-022**: 最终 Road/Node 评价必须复用 M0 evaluator，并补充 decoder intervention audit 和 grouped OOF 汇总。
- **FR-023**: 参数量目标为 `8M~20M`，单机单 GPU 峰值显存预算不超过 `16GB`。
- **FR-024**: 所有 run 必须记录输入输出 hash、参数、seed、Python/PyTorch/CUDA/GPU、耗时、RAM/VRAM 和 `silent_fix=false`。
- **FR-025**: M2R 不修改 T01-T07 正式算法，不新增 repo CLI、root script、T10 stage、`__main__.py` 或 Makefile target。
- **FR-026**: 产品、架构、研发、测试、QA 五类职责必须在 plan/tasks/validation 中分别覆盖。
- **FR-027**: GIS 验证必须覆盖 CRS、拓扑一致性、几何语义、审计追溯和性能。

### Key Entities

- **M2RSample**: 一个 grouped Case 样本及其可用任务、输入 artifact 和 split。
- **TaskTarget**: 某个任务的可追溯目标，带 trust tier、weight、scope、CRS 和 mask。
- **SharedSceneGraph**: T01/SWSD/RCSD 基础几何、节点、道路面与图关系形成的无标签泄漏输入。
- **TaskPrediction**: T03/T04/T05/T06/T07 Head 的原始输出、置信度和任务 mask。
- **DecoderIntervention**: 通用约束对非法动作的屏蔽记录，不包含业务修图。
- **M2RRun**: 数据、训练、OOF 推理、评价、资源和 hash 的不可变运行记录。

## Success Criteria

- **SC-001**: 使用标签的 lineage/hash/CRS/weight/task mask 完整率为 `100%`；`Unknown` 误作负样本数为 `0`。
- **SC-002**: approved exclusion 进入特征、标签、统计和评价的数量为 `0`。
- **SC-003**: grouped OOF 中跨 fold 业务对象、归档版本及受控实体泄漏数为 `0`。
- **SC-004**: Road operation 表示对完整 T06 truth 的 micro coverage 不低于 `99.9%`。
- **SC-005**: 每个必选 Head small-batch 拟合指标不低于 `0.95`；否则该 Head 判定为标签/表示未就绪。
- **SC-006**: T03 状态/场景/关联 macro-F1 不低于 `0.80`，可评价 surface Dice 不低于 `0.80`。
- **SC-007**: T04 状态/场景/事件 macro-F1 不低于 `0.75`，可评价 surface Dice 不低于 `0.80`。
- **SC-008**: T05 `target_id -> base_id` 完全正确率不低于 `0.90`，relation cardinality error 为 `0`。
- **SC-009**: grouped OOF 最终 Road object F1 不低于 `0.85`，并比最强简单/确定性基线高至少 `5` 个百分点。
- **SC-010**: grouped OOF 最差 Case Road F1 不低于 `0.70`，direction/source accuracy 均不低于 `0.95`。
- **SC-011**: 最终 Road/Node 重复 ID、缺失引用、CRS hard failure、有向拓扑 hard failure和物化失败均为 `0`。
- **SC-012**: constrained decoder 最终合法 RoadGraph 比例为 `100%`，事后内容修复数量为 `0`。
- **SC-013**: T07 只有在 OOF Road F1 提升至少 `1` 个百分点或减少拓扑 hard failure，且最差 Case 不下降时才保留。
- **SC-014**: 相同 checkpoint/输入重复推理的逐对象预测、物化结果和指标完全一致。
- **SC-015**: 模型参数量不超过 `20M`、峰值 VRAM 不超过 `16GB`，训练和逐 Case 推理性能可定位。

## Non-Goals

- M2R 不宣称生产可用或替代正式 T03-T06。
- M2R 不把当前测试用例反推为新的正式字段强规则。
- M2R 不凭空自由生成整幅坐标序列。
- M2R 只在本轮用户明确授权的 `POC_Data` T03/T04 单点 Case 上生成 `user_confirmed_strategy_replay_truth`；不把它冒充历史原始产物，不扩展到推理阶段或其它数据。
- M2R 不把已知的 M1 固定 test 重新包装成盲测。
