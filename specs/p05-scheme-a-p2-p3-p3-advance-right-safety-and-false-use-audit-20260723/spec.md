# P05-Scheme-A-P2-P3-P3：ADVANCE_RIGHT 硬安全资格与残余 false-use 可分性审计

## 1. 状态与授权

- 状态：已完成（`P05_SCHEME_A_P2_P3_P3_SAFETY_GATE_GO_NEXT_REPRESENTATION_REQUIRED`）
- 授权日期：2026-07-23
- 唯一实施工作树：`E:\Work\RCSD_Topo_Poc__wt_p05_neural_road_20260721`
- 数据范围：仅 `E:\TestData\POC_Data` 与既有 P05 冻结工件
- Git：不提交、不推送
- Movement：忽略
- 模型训练：本阶段不训练新模型

用户已批准继续。本阶段承接 `P05_SCHEME_A_P2_P3_P2_MODEL_NO_GO`，把冻结
T01 已确认的 `ADVANCE_RIGHT access_valid=false` 从 scorer 决策中独立出来，
作为推理期硬安全资格；随后只读审计剩余可靠 target false-use，判断下一阶段应
补充 T06 之前可用的推理表征，还是升级为跨 Segment/Junction 图模型。

## 2. 目标

1. 证明 `access_valid=false` 硬门只命中 40 个已确认 Review 对象，不误伤任何
   `KEEP_SWSD/USE_RCSD` 可靠标签。
2. 在不重训、不调阈值的前提下重放 P2-P3-P2 三 seed 决策，消除全部 Review
   自动发布，同时保持 context fallback、局部 expected-failure 和 RoadGraph 安全。
3. 对
   `SCHEME_A_P1:SEGMENT:T10-Error-2:89387685_507565991:89387685_507565991`
   做 held-out、truth-free 可分性审计，解释三个 seed 为何都优先选择错误的
   `USE_RCSD` candidate。
4. 给出下一阶段唯一可执行路线，不基于单个 Case 反推并固化新的业务强规则。

## 3. 冻结业务语义

1. T01 Segment/Junction 骨架冻结，模型和安全门均不得新增、删除、拆分、合并或
   重归属 Segment/Junction。
2. `ADVANCE_RIGHT` 是正式 Segment；其冻结 access 关系无法唯一成立时，
   `access_valid=false`，必须保留 SWSD、输出 Review/RealityChangeClue，不能自动
   发布 RCSD carrier。
3. 硬门只执行既有冻结事实，不读取 T03/T04/T05/T06 终态，不以真值或 Case 名称
   作为推理输入。
4. Dataset-P1 仍是唯一 Segment 标签资格合同；2,588 个 context-only 对象继续
   固定 `KEEP_SWSD` fallback。
5. `T10:609214532` 与 `T10:74155468` 继续保持局部 expected-failure，不允许整
   Case 级联。
6. 剩余 false-use 审计只能形成“表征/模型选择”结论，不能从单对象现象创建业务
   规则。

## 4. 五类职责视角

### 产品

- 准确性和安全性优先；消除 Review 自动发布不以提高自动化率为目标。
- 本阶段不能将“安全重放通过”解释为 scorer GO。
- 下一阶段路线必须说明为什么当前数据足够或不足，而不能笼统要求更多 Case。

### 架构

- `access_valid` 安全资格位于 scorer 之后、通用 Junction/Node closure 之前。
- 原 P2-P3-P2 score、阈值和模型状态只读复用，不重新训练、不调参。
- false-use 审计使用当前已允许的 202 维 T01/T07 证据及候选表达，按 held-out
  fold 隔离训练 Case，禁止 truth/identifier/T06 泄漏。

### 研发

- 只新增 P05 内部 callable、schema、测试和 SpecKit 工件。
- 不新增 CLI、root script、T10 stage 或长期执行入口。
- 不修改 T01–T12 实现或接口，不修改 geometry/CRS。

### 测试

- 覆盖硬门精确匹配、非 Review 不误触发、字段缺失 hard fail、身份破坏 hard fail。
- 覆盖三 seed 决策重放、context fallback、局部 expected-failure 和整图闭包。
- 覆盖 false-use 的 held-out 邻域、候选 margin 和跨真值重叠审计。

### QA

- 冻结输入 manifest/hash、原 P2-P3-P2 signature、Case fold、seed 和输出 lineage。
- 正式 Run A/B 的规范化内容签名一致。
- CRS、geometry write、骨架 mutation、repair、silent fix、Movement、T06
  model-input 和新模型训练均为 0。

## 5. 验收门禁

### Gate 0：源事实与作用域

- 6,275 个 eligible group 与方案 A `segment_inventory.csv` 全量 1:1 匹配；
- `access_valid=false` 恰好 40 个，全部为
  `ADVANCE_RIGHT + REVIEW_FALLBACK`；
- 非 Review 的 `access_valid=false` 数为 0；
- 硬门不读取 label-only 或 T06 终态事实。

### Gate 1：硬安全资格

- 三 seed 共 120 条 Review decision 全部强制
  `accepted=false/effective_target=KEEP_SWSD`；
- `review_auto_publish_count=0`；
- 非命中对象的原始 candidate、score、阈值与 decision 内容不变；
- 硬门原因可追溯到冻结 Segment 的 `access_valid=false`。

### Gate 2：重放后的 Carrier 与整图安全

- accepted wrong 从 P2-P3-P2 的 `1/13/0` 降为 `1/1/0`；
- 三 seed Review auto 均为 0；
- 2,588 个 context-only 自动接受数为 0；
- 49 Case 为 `LEGAL`，2 Case 为 `EXPECTED_FAIL`；
- carrier conflict、Node mismatch、非目标级联、骨架 mutation、repair 和 silent
  fix均为 0。

### Gate 3：残余 false-use 可分性

- 目标对象三个 seed 的 candidate ranking、接受/回退原因和 margin 完整可追溯；
- 每个 seed 只使用该 seed/fold 的训练 Case 建立标准化与近邻审计；
- 报告 exact-signature 跨真值碰撞、近邻真值构成和 selected/truth candidate
  差异；
- 不因单对象生成新业务强规则；
- 明确判定以下二者之一：
  - `NEW_PRE_T06_REPRESENTATION_REQUIRED`：现有逐对象表征不能稳定分开；
  - `CROSS_SEGMENT_GRAPH_MODEL_REQUIRED`：正确判断依赖未被逐对象表达的共享
    Junction/邻接上下文。

### Gate 4：确定性、资源与 GIS

- 正式 Run A/B 的 gate ledger、重放 decision/effective selection、RoadGraph 和
  false-use audit 规范化 signature 一致；
- CPU RAM `<=8GB`，GPU VRAM=`0`；
- 单次审计 wall `<=30min`；
- CRS=`EPSG:3857`，geometry read/write=`0`，coordinate transform=`0`。

## 6. 阶段决策

- 硬门和审计完整通过，且下一表征路线被证据唯一支持：
  `P05_SCHEME_A_P2_P3_P3_SAFETY_GATE_GO_NEXT_REPRESENTATION_REQUIRED`
- 安全门通过，但逐对象证据不足以区分两条路线：
  `P05_SCHEME_A_P2_P3_P3_SAFETY_GATE_GO_ARCHITECTURE_DECISION_REQUIRED`
- 源事实、作用域、整图、确定性或资源门失败：
  `P05_SCHEME_A_P2_P3_P3_AUDIT_NO_GO`

任何结论都不授权新模型训练、在线 proposal、生产接入、T01–T12 修改、
Movement 训练或 Git 操作。

## 7. 后续重解释

2026-07-23 的 P2-P3-P4 证明本阶段残余对象的 `KEEP_SWSD` 真值来自
context-only Segment 在 Dataset-P1 scope 之前参与 Junction 闭包的顺序缺陷。
P3 的安全硬门、原始运行和近邻审计继续作为历史证据保留；但
`GO_NEXT_REPRESENTATION_REQUIRED` 不再是当前下一阶段路线，现由
`P05_SCHEME_A_P2_P3_P4_TRUTH_REBASELINE_GO_NO_RESIDUAL_REPRESENTATION_REQUIRED`
取代其残余解释。
