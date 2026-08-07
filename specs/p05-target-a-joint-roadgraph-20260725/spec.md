# P05 Target A：T07–T06 联合业务决策与约束 RoadGraph 生成

**状态**：已确认，进入实现
**分支**：`codex/p05-target-a-joint-roadgraph`
**数据范围**：`E:\TestData\POC_Data`，以及用户于 2026-08-04 明确授权的
`E:\TestData\POC_QA\T03_Error`
**生产状态**：离线研究，不接生产

## 1. 目标

构建一个联合、分层的神经系统，先替代 T07/T03/T04/T05 的语义路口锚定业务，
通过独立路口验收后再替代 T06 在普通 Segment 与
`ADVANCE_RIGHT` Segment 上承担的核心业务判断，输出完整、可解释、可约束求解的
Road/Node 方案，并由确定性层执行几何与 schema 写出。

本目标不等于自由生成全部业务骨架：

- T01 冻结 Junction、Segment、Junction—Segment、SegmentAccess 和
  PhysicalMovement 的存在性与归属；
- T07 的原始输入语义保持不变：Step1 只读取 DriveZone，RCSDIntersection 只进入
  Step2；但 T07 的业务判断由模型学习，旧 T07 输出不再作为推理期前置事实；
- T10 继续负责数据、编排和发布流程；
- 第一版不启用 Movement，不接生产；
- 不修改 T01–T12 现有实现或接口。

旧 T07/T03/T04/T05/T06 策略在 Target A 推理期完全退出，但可在训练期提供有权重、有作用域且
不泄漏的监督。

## 2. 用户故事与优先级

### P1：锚定先于普通 Segment 替换

对每个 SWSD 语义路口，模型从推理期可见的 T01/SWSD、原始 DriveZone、
RCSDIntersection、RCSD Road/Node 中依次学习 T07 evidence/已有路口面锚定、
T03 常规虚拟锚定、T04 复杂虚拟锚定及 T05 relation/junctionization，唯一确定
RCSD 锚定对象、相关 RCSD Road 和必要打断位置。路口子系统独立验收通过后，普通
Segment 才能进入训练和 RCSD Road 方案判断。

验收：

1. 锚定是同一神经系统中的独立阶段输出；
2. 多候选不能由后续 Road 分数代选；
3. 无唯一解输出 `AMBIGUOUS` 或 `ABSTAIN`；
4. 任一 required `pair_node/junc_node` 未成功锚定时，相关普通 Segment 不得发布
   RCSD 方案；
5. 第一版不支持“RCSD Junction + RCSD Road”复合锚定，必须安全回退并单独统计。
6. T07/T03/T04/T05 每个关键业务状态均须显式输出，但不要求复制旧模块内部步骤；
7. T07 Step1 的 evidence 只能来自 DriveZone，RCSDIntersection 不得泄漏到 Step1；
8. T03/T04 surface、T05 relation 与 graph-consumable/junctionization 必须分别验收，
   不能只比较最终 `target_id -> base_id`。

### P1：普通 Segment 输出完整 Road 方案

对已通过锚定门禁的普通 Segment，模型输出 `USE_RCSD`、`KEEP_SWSD` 或
`ABSTAIN`，同时输出完整 Road 清单、每条 Road 的业务用途和所有权、source/target
access、方向、Node 与打断配方。

验收：

1. `KEEP_SWSD` 是正向自动业务决定，必须输出完整 SWSD Road 方案；
2. `ABSTAIN -> fallback SWSD` 只计安全成功；
3. RCSD 主干可由一条或多条 RCSD Road/片段组成；
4. `USE_RCSD` 后不得保留 SWSD 主干；
5. 普通 Segment 唯一允许的混源 carrier 是 T06 明确定义的“主干 RCSD
   替换、附属/侧向 SWSD 保留”；AdvanceRight `MIXED_SPLICE` 是由两侧
   最终 access 来源条件触发的独立几何方案，不属于通用 HYBRID；
6. Segment 内部 RCSD 连接树可纳入 Road 清单：聚合后为树，所有叶节点都挂接在
   当前 Segment 选择的 RCSD 主干 Road 上，且无外部叶；这些 Road 同时进入
   `frcsd_road_ids` 与 `owned_frcsd_road_ids`；
7. 一条最终 RCSD Road 片段只能由一个正式 Segment 所有；无 owner Road 只能用于
   Junction 内部或多 Segment connectivity；
8. 正确性必须联合比较锚定、完整 Road 清单、用途/所有权、access、Node、方向和拓扑。

### P1：AdvanceRight 条件化实现

普通 Segment 决策锁定后，`ADVANCE_RIGHT` 根据冻结的
`source_segment_access/target_segment_access` 读取两侧最终 access Road，选择完整
提右 Road 组合、打断位置、衔接位置和挂接关系。

验收：

1. 不允许使用最近距离猜测相邻 Segment；
2. 提右不拥有相邻普通 Segment 的 access Road；
3. 两侧来源不同时，按模型输出的业务配方做中间确定性几何衔接；
4. 提右拥有独立 Road，可保留真实 `junc_nodes`；
5. 提右不能反向改变普通 Segment 的锚定、Road 方案或 access；
6. 正确性联合比较两端来源、Road 组合、打断/衔接、挂接、方向和最终拓扑。

### P1：结构化整图选择与安全回退

RoadGraph decoder 在模型给出的完整 carrier 方案中联合选择，并将所有权/
拓扑约束与 fallback 作用域严格分离。模型必须输出显式 `FallbackDirective`：
Segment 级只含该 Segment；Junction 级必须给出 Junction 和明确受影响的直接
关联 Segment。确定性层用冻结 T01 Junction—Segment 直接关系校验，但不得补充
对象或沿 `Junction—Segment—Junction` 传递扩张。

验收：

1. decoder 不修改锚定、不扩充候选、不改变 T01 骨架、不重新判断证据；
2. 普通 Segment 先求解并锁定 access，提右后求解；
3. Segment 问题只回退该 Segment；
4. 提右自身问题只回退提右，只有共享 carrier 或影响 Junction 内部拓扑时才升级
   Junction fallback；
5. 模型判断无证据、歧义、现实冲突、影响对象和 `RealityChangeClue`；
6. 确定性层只执行已确定作用域的 fallback；
7. Segment fallback 不影响同一 Junction 的其他 Segment；Junction fallback
   止于直接关联 Segment，不影响这些 Segment 的另一端 Junction；
8. T01 依赖图只作 encoder 上下文，不能成为 fallback 扩张边；
9. 骨架 mutation、silent fix、危险自动替换、新增图硬失败均为零。

## 3. 输入

### 3.1 推理期允许输入

- T01 冻结业务图：Junction、Segment、SegmentAccess、pair/junc node 角色、方向和
  PhysicalMovement 存在性；
- SWSD 原始 Road/Node 与局部几何；
- RCSD 原始 Road/Node、方向和拓扑；
- 原始 DriveZone（仅供模型内 T07 Step1 evidence 判断）；
- 原始 RCSDIntersection（从模型内 T07 Step2 开始可见）；
- 与业务无关的通用空间/拓扑索引、候选检索结果和缺失性标记。

约束：

- 原始 ID 只作引用，不学习 ID embedding；
- 默认只学习投影坐标系中的局部相对几何，不学习城市绝对坐标；
- Road 几何顶点与业务 Node 分开表达；
- 候选检索不能包含 T07/T03/T04/T05/T06 终态或由终态反推的候选；
- 数据缺失和证据完整度必须显式输入。

### 3.2 训练期标签与权重

| 来源 | 标签作用域 | 权重 |
|---|---|---:|
| `POC_Data/T03`、`POC_Data/T03_Error`、`POC_Data/T04`、`POC_Data/T04_Error` | 当前正式规则重放结果由用户视为逐 Case 人工确认 Gold | 1.0 |
| `POC_QA/T03_Error` | 当前正式规则重放结果由用户视为逐 Case 人工确认 Gold | 1.0 |
| T10 Case 级 | 仅明确追溯到具体 SWSD 语义路口的锚定对象与关键业务状态 | 0.7 |
| T10 Segment 级 | 仅目标 Segment 直接涉及、且可明确追溯到具体 SWSD 语义路口的锚定结果 | 0.7 |
| T10 非目标 Segment | 仅作无标签结构上下文 | label/loss/metric=0 |
| T10-Error / T10-Error-2 | 仅目录名对应目标 Segment 直接涉及且可追溯的路口锚定结果 | 0.7 |
| 人工裁决 | 指定对象覆盖旧标签 | 1.0 |

排除 `T10-Error/1213556_1263661`。

五个 1.0 目录共有 743 个目录记录、716 个不重复 Case ID。2026-08-04 正式重放
得到 surface accepted/rejected/runtime_failed=`399/321/23`，RCSD 锚定业务状态
在 T05 延续前为 SUCCESS/NO_RCSD_EVIDENCE/QUALITY_ISSUE=`156/19/568`。399 个
accepted surface 已全部继续执行正式 T05 relation/junctionization：343 个完整通过、
19 个正向 `NO_RCSD_EVIDENCE`、37 个 Road-only 打断方案存在
`split_road_endpoints_exist=false`。最终业务状态为
SUCCESS/NO_RCSD_EVIDENCE/QUALITY_ISSUE=`343/19/381`；706 条具备完整路口级 Gold，
37 条只保留安全状态与 T05 action 监督，不进入完整拓扑 exact 分母。24 个同 ID 多输入版本
Case 中，8 个终态业务签名一致，全部版本保留在同一 split 且按版本数均分权重，
保证该 Case 总权重仍为 1.0；16 个终态冲突 Case 进入 `LABEL_REVIEW`，不进入训练、
阈值、校准或测试。最终冻结 700 个 Case group、708 个输入版本，
train/validation/test=`490/105/105` 个 group，对应输入版本=`497/105/106`、有效权重
仍为 `490/105/105`；
同一 Case、语义路口或输入版本不得跨 split，训练集覆盖全部现有终态组合。T10 监督
另按 Case/source group 约 70/15/15 划分，冻结留出结果只作 0.7 泛化指标，不与
Gold 主指标混算。

2026-08-05 用户确认采用方案 A：上述权重 1.0 的强 Gold 与权重 0.7 的 T10
弱监督允许在同一主模型中共享 raw-inference encoder，但必须按字段 `task_mask`
参与各自可辨识的 loss；来源、目录族和 Case 类型只进入训练审计与分层指标，不得
成为推理特征。联合阶段之后必须执行只用强 Gold 的 consolidation，模型选择同时
报告强 Gold 与 T10 validation，不得用任一冻结 test 选择结构、epoch、阈值或 seed。

人工裁决：

- `T10:609214532 / 505101583_506183080`：
  `USE_RCSD`，`RealityChangeClue=false`；
- `T10:706247 / 706317_706319`：`USE_RCSD` 或 `KEEP_SWSD` 均可，优先
  `KEEP_SWSD`；Junction fallback，clue=true；
- `T10:706247 / 706346_706349`：两者均可，优先 `USE_RCSD`，clue=false；
- `T10:609214532 / 513242335_523239407`：`KEEP_SWSD`，clue=false；
- `T10:609214532 / 606102026_609617028`：`KEEP_SWSD`，clue=false。

后两项是 RCSD 数据缺失，不是现实结构冲突。

### 3.3 禁止输入

- T07/T03/T04/T05/T06 终态 status、reason、surface、最终 relation、最终 Road/Node；
- 当前样本的人工裁决、preferred 标记或 fallback 结果；
- T10-Error 目录名本身；
- 由终态选择反推的候选集合、候选次序或图结构；
- 任何只在标签/评价层可见的字段。

## 4. 输出

模型按顺序输出：

1. `JunctionEvidenceDecision`：模型内 T07 Step1 evidence 与 Step2 existing-surface
   锚定状态；
2. `AnchorSurfaceDecision`：T07/T03/T04 来源、accepted/rejected、surface 配方及
   适用业务类型；
3. `AnchorDecision`：SWSD 语义路口对应的 RCSD Junction/Road 候选、唯一选择、
   打断位置、`SUCCESS/NO_EVIDENCE/AMBIGUOUS/ABSTAIN`；
4. `JunctionizationPlan`：T05 relation、graph-consumable 状态和 copy-on-write
   RCSD Road/Node 路口化配方；
5. `OrdinarySegmentPlanSet`：路口阶段通过后，每个普通 Segment 的完整可选 Road
   方案及评分；
6. `OrdinaryDecision`、`AdvanceRightPlanSet/Decision`、`ClueDecision` 与最终
   `DecisionLedger`。

确定性层只负责 ID 生成、几何 split/clip/reverse/splice、schema/CRS 写出和图合法性
验证，不得重新作业务选择。

## 5. 非功能约束

- 城市是数据、发布和最终验收单位；
- 神经 forward 单位是动态业务依赖子图；
- decoder forward/求解单位是当前动态业务依赖子图；所有权可联合约束，但
  fallback 只按显式 Segment/Junction directive 执行，不形成传递连通组；
- 空间切片只用于查询加速，不得截断业务依赖；
- 城市级 feature/index cache 按输入 hash、schema 和模型版本复用；
- label store 必须与 inference cache 物理隔离；
- 中间阶段保持内存/紧凑 ledger，不反复写 RoadGraph。

## 6. 验收指标

### 6.1 硬安全门

- unsafe auto RCSD = 0；
- Review auto = 0；
- unreachable auto = 0；
- skeleton mutation = 0；
- silent fix = 0；
- 新增 RoadGraph hard failure = 0；
- 不劣于当前 49 `LEGAL` + 2 `EXPECTED_FAIL` 安全基线。

### 6.2 业务质量

- T07 Step1 evidence、Step2 existing-surface 锚定 exact；
- T03/T04 surface 与 relation-evidence exact；
- T05 唯一 relation、graph-consumable 和 junctionization exact；
- 锚定 exact / acceptable-set accuracy；
- 普通 Segment 完整方案 exact；
- AdvanceRight 完整方案 exact；
- 自动决策整图 exact；
- fallback 后最终 RoadGraph exact；
- positive `KEEP_SWSD` 自动覆盖；
- `ABSTAIN` 率与 fallback 质量；
- 各类 Case 最差表现；
- 对完整现有策略的 paired comparison。

研究 GO 目标：

- 路口阶段先独立满足零危险自动锚定，并对 T07/T03/T04/T05 各主要类别报告
  cross-Case exact、coverage 和最差 Case；未通过前不得启动普通 Segment 训练；
- Gold 冻结测试集 raw 完整路口 exact 不低于 `0.85`；完整路口 exact 必须同时命中
  surface、锚定状态、RCSD 对象完整集合、聚合/打断方案、重构拓扑和质量状态；
- 自动业务决策覆盖率不低于 `0.80`，自动接受完整正确率为 `1.0`，危险自动接受和
  真值未知自动接受均为 `0`；
- 已证明异常被判为正常为 `0`，`异常或安全 ABSTAIN` 召回为 `1.0`；
- T10 冻结留出集按 0.7 标签计算的完整路口 exact 不低于 `0.75`；
- 样本数不少于 20 的关键业务子类完整 exact 不低于 `0.60`；
- 在相同输入、输出和运行环境下，包含一次性索引/缓存构建的总耗时不超过现有
  T07+T03+T04+T05 规则链的 `1.5` 倍；城市输入每次运行只允许完整读取和建索引一次。

ID、文件顺序和无业务影响的折线点差异不参与 exact；锚定对象、源 Road、Road 用途、
所有权、access、方向和拓扑严格比较；打断/衔接位置按 T06 正式几何标准容差比较。
多解标签区分 acceptable 与 preferred，非 preferred 的 acceptable 方案不算错误。

## 7. 明确不做

- 不做连 T01 业务骨架和确定性合法性都取消的自由 RoadGraph 生成；
- 不启用 Movement；
- 不修改 T01–T12 实现、接口或正式入口；
- 不接 T10/生产自动发布；
- 不要求用户增加 Case；
- 不以 P13 的 5m Local Control 作为唯一基线。
