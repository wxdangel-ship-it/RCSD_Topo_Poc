# P05 Junction GraphSet v1：完整语义路口结果模型

**分支**：`codex/p05-junction-graphset-v1-20260807`
**创建日期**：2026-08-07
**状态**：已确认，进入 implement 前置阶段
**输入依据**：用户确认的 Target A 路口优先业务边界，以及
`p05-target-a-joint-roadgraph-20260725` 的完整 `JunctionResult`/Oracle 审计

## 1. 当前阶段目标

构建一个以唯一 SWSD 语义路口为牵引、能够从原始 RC 资料端到端输出完整
`JunctionResultPrediction` 的神经系统，替代 T07、T03、T04、T05 在该路口上的核心
业务判断。旧 T07/T03/T04/T05 策略在模型推理期退出，只作为训练标签和同输入输出
比较基线。

本阶段只解决语义路口面、RCSD 锚定、必要的 Road 打断/路口重构和质量状态。普通
Segment、AdvanceRight、Movement 与完整 RoadGraph 构建均不进入本轮训练和 GO
判断；T01 继续冻结业务骨架，T10 继续负责数据和编排。

## 2. 用户场景与独立验收

### US1：从城市对象仓得到一个路口的完整可解释结果（P1）

对于任一 SWSD 语义路口，系统只读取一次城市原始资料，并从对象 ID 索引中取得动态
业务依赖子图；一次 forward 必须输出完整合法结果或明确 `ABSTAIN`，不得崩溃、产生
越界对象或隐式调用旧策略。

独立验收：对全部开发记录执行真实 free-run，100% 记录能够生成合法
`JunctionResultPrediction` 或 `ABSTAIN`，推理特征泄漏数为 0。

### US2：正确确定路口面及其 RCSD 对象约束（P1）

模型先用 DriveZone-only Step1 证据判断，再选择已有 RCSDIntersection、生成虚拟面、
判定无有效面或歧义。虚拟面不要求复现旧规则几何，但成功锚定对象不得漏包含，正式
禁止对象不得误包含，UNKNOWN 不被补造成负例。

独立验收：在 1,685 条适用记录中分别报告 REQUIRED 召回、FORBIDDEN 误召回、Review
和 UNKNOWN；自动接受结果的 REQUIRED 召回为 100%、FORBIDDEN 误召回为 0。

### US3：输出唯一锚定与完整路口重构方案（P1）

模型必须独立确定唯一锚定状态、完整 RCSD Node/Road 集合、唯一主锚定、Node 等价
关系及 Road 打断操作；后续结构分数不能反向替锚定分支选择对象。确定性层只执行几何
打断、ID 生成、拓扑校验和写出。

独立验收：以完整对象、打断和物化后拓扑联合 exact 评价；生成 ID、文件顺序和无业务
影响的折线点差异不计错。

### US4：在不确定或冲突时安全回退（P1）

无证据、歧义、质量问题、未知真值和候选不可表达必须显式区分。只有已证明无 RCSD
证据时可派生 `clue=false`；其他未知原因不得补造。自动接受与 `ABSTAIN -> fallback`
分开统计。

独立验收：危险自动接受为 0、真值未知自动接受为 0、已证明异常的异常或安全
`ABSTAIN` recall 为 100%。

### US5：与现有规则链做同输入输出比较（P2）

固定模型后，使用相同原始输入、相同完整 `JunctionResult` 比较器，对网络与
T07+T03+T04+T05 规则链做业务正确率、安全、覆盖和性能对比，不以局部 head accuracy
代替完整结果。

独立验收：报告规则/网络的 paired complete exact、各业务分量、最差 Case、自动覆盖、
fallback 后 exact、城市读取次数与总耗时。

## 3. 功能需求

- **FR-001**：一个 forward 的业务身份必须是唯一
  `case_key + semantic_junction_id` 及其动态依赖子图。
- **FR-002**：城市级 SWSD、RCSD、DriveZone、RCSDIntersection、道路面与导流带只允许
  解析和建立索引一次；空间窗口只用于查询加速，不得截断业务依赖。
- **FR-003**：Step1 只能看到 SWSD 与 DriveZone，物理屏蔽 RCSDIntersection、RCSD
  Node/Road 和旧模块终态。
- **FR-004**：RCSDIntersection 只从 Step2 开始可见；RCSD Node/Road、道路面、导流带
  只在相应后续分支可见。
- **FR-005**：主表征使用 21D 几何 token 与 8D 拓扑边；既有 64D/12D 特征只有完成逐维
  来源审计后才能作为辅助输入，未审计维度默认关闭。
- **FR-006**：模型必须输出面方案、锚定状态、完整 RCSD Node/Road 集合、主锚定、Node
  等价关系、Road 打断操作、置信度、`ABSTAIN` 和 review reason。
- **FR-007**：结构 decoder 只能在通用空间/拓扑候选中联合选择，不得扩充候选、改变
  SWSD 语义路口或调用旧 T07/T03/T04/T05 终态作推理证据。
- **FR-008**：虚拟面成员采用 `REQUIRED / FORBIDDEN / UNKNOWN` 三态；5 条冲突记录
  保持 Review/零训练权重，6 条无证据 must-cover Road 保持 UNKNOWN。
- **FR-009**：弱标签、缺失字段和多解方案分别使用权重、task mask 和 acceptable-set
  loss；来源类别只作审计维度，不进入模型输入。
- **FR-010**：训练必须同时保留 teacher-forced 与真实 free-run 评价，正式门禁只采用
  free-run 完整结果。
- **FR-011**：确定性 materializer 不得重新选择业务对象，只执行已选方案、通用拓扑
  合法性校验及路口作用域 fallback。
- **FR-012**：P0 不训练 `RealityChangeClue` 二分类；待存在可识别的 true/false 路口级
  监督后另行启用。
- **FR-013**：所有运行必须记录输入 hash、CRS、特征合同、split、模型 hash、阈值、
  materializer 版本与运行环境。

## 4. 数据与标签边界

- 开发记录 4,288 条：强 Gold 602 条（权重 1.0），T10 弱标签 3,686 条（权重 0.7）。
- 虚拟面约束适用 1,685 条，其中 1,680 条可训练，5 条冲突 Review。
- 成功锚定 REQUIRED 候选可达 `1,528/1,528=100%`。
- 76 条质量状态记录只监督状态/原因，不补造成员集合。
- 冻结强测试原有 106 条；已暴露 1 条隔离，剩余 105 条继续盲测。
- T03/T04/T05/T07 终态、规则虚拟面、人工 Gold 和 evaluator 结果均为 label-only 或
  evaluation-only，不进入推理 tensor。

## 5. 明确不在本轮范围

- 不训练普通 Segment、AdvanceRight、Movement 或 RoadGraph decoder。
- 不修改 T01–T12 正式业务实现、正式接口或 T10 阶段顺序。
- 不新增正式 CLI/脚本入口；如后续确需正式入口，必须单独同步接口合同和 entrypoint
  registry。
- 不以旧规则虚拟面几何 exact 为模型目标。
- 不用阈值、后处理或 fallback 掩盖锚定对象错误。
- 不读取冻结测试来选结构、loss、epoch、阈值或 seed。

## 6. 成功度量

### 6.1 表达与工程门禁

- 推理字段泄漏数 `=0`，Step1 防火墙违规数 `=0`。
- REQUIRED 候选可达率 `=100%`。
- 全部输入均可输出合法结果或明确 `ABSTAIN`；非法 ID、越界候选和物化 hard failure
  均为 0。
- 城市原始资料完整读取/索引次数 `=1`，输出 GIS 写出次数 `=1`。

### 6.2 研究 GO 门禁

- 强标签冻结验证 raw 完整路口 exact `>=0.85`。
- 自动业务决策覆盖 `>=0.50`；最终目标 `>=0.80`。
- 自动接受完整正确率 `=1.0`，危险自动接受 `=0`，真值未知自动接受 `=0`。
- 已证明异常不得判正常；异常或安全 `ABSTAIN` recall `=1.0`。
- T10 留出 weighted complete exact `>=0.75`。
- 虚拟面自动接受 REQUIRED recall `=1.0`、FORBIDDEN inclusion `=0`。

### 6.3 最终比较与性能门禁

- 分别报告自动决策完整 exact 与 fallback 后最终 `JunctionResult` exact。
- 分别报告 strong/T10、T03/T04/T05/T07、SUCCESS/NO_EVIDENCE/QUALITY、对象数量分层
  和最差 Case，不能只报总体平均。
- 与规则链在同输入、同输出、同运行环境下 paired 比较；网络端到端总耗时不得超过
  规则链的 1.5 倍。

## 7. 停止条件

- 正确方案不在候选域时停止调模型，回到 IO/候选表达审计。
- teacher-forced 正确而 free-run 断联时，修复条件传播与 mask，不增加局部 scorer。
- 小批可过拟合但跨 Case 为零时，回到表征与 split 审计。
- 连续三个预注册 seed 出现同一结构性失败时，停止 loss/epoch/threshold 局部搜索，
  重新审查架构。
- 任一危险自动接受先关闭相应自动发布范围，再分析根因。
