# P05-Scheme-A-P2-P3-P11：稳定 Clue 误报归因与人工审计清单

## 1. 状态与授权

- 状态：技术审计完成，等待对象级人工目视裁决
- 用户授权：2026-07-24 同意继续，并允许在必要时提交人工目视审计清单
- 唯一实施工作树：
  `E:\Work\RCSD_Topo_Poc__wt_p05_neural_road_20260721`
- 承接阶段：
  `P05_SCHEME_A_P2_P3_P10_TRUTH_REBASELINE_GO_P9_PROMOTION_NO_GAIN`

P11只允许读取冻结P9、P10、P8、Dataset-P1、Scheme-A冻结Segment inventory与
`E:\TestData\POC_Data`内登记的T10 QGIS工程。不得训练、拟合校准器、调整阈值、
修改模型权重、改写历史工件或修改T01–T12。

## 2. 阶段目标

1. 精确识别P10五对象真值覆盖后Control/Treatment三seed仍稳定预测
   `RealityChangeClue=true`、但当前对象真值为false的对象集合；
2. 将“已有人工作为对象真值的模型误报”与“只有T10 Case级0.7真值、对象真值
   尚未确认”分开，禁止把后者直接定性为模型错误；
3. 记录每个对象的模型概率、fold阈值、carrier真值/选择、Dataset-P1 lineage、
   T03/T04来源适用性、Segment类型、SWSD Road/access定位证据与QGIS工程路径；
4. 基于风险覆盖选择最小首轮人工目视清单，不要求用户一次审核全部对象；
5. 保持稳定Clue漏报为0，不改变任何carrier、fallback或RoadGraph决策。

## 3. 业务口径

- `RealityChangeClue`表示事实证据与冻结道路结构认知冲突；
- RCSD数据缺失本身不是现实冲突；
- `USE_RCSD`成立的业务前提是Road两侧路口均能正确锚定，且替换后的Road连接
  正确；用户目视判定`USE_RCSD`即同时确认该前提；
- T10 Case级权重0.7只表示Case整体基本正确，不代表每个Segment已经目视确认；
- 对象级人工裁决权重1.0优先于Case级0.7；
- 未经人工确认的Case级0.7对象只能标为`OBJECT_TRUTH_REVIEW_REQUIRED`，不能自动
  修改为Clue true或false；
- Clue误报导致的保守fallback不属于错误发布，但会降低自动化率；准确性和安全性
  继续优先于自动化率。

## 4. 首轮人工审计选择规则

已由P10确认`clue=false`的对象只作为已确认对照，不重复要求审核。其余未确认对象
满足任一条件时进入首轮清单：

1. 当前carrier选择与冻结carrier真值不一致；
2. 三seed Clue概率均不低于0.5；
3. 对象是`ADVANCE_RIGHT Segment`；
4. 对象命中P8登记的T03/T04正式来源。

其它对象保留在完整ledger中，首轮审核结果不足以判断总体口径时再扩展，不得静默
丢弃。

## 5. 验收门

### Gate 0：输入完整性

- P9、P10、P8、Dataset-P1和Scheme-A baseline必需工件均通过artifact
  manifest的size/hash校验；
- P9/P10/P8/Dataset-P1正式decision与审计门、Scheme-A冻结骨架门符合承接合同；
- P10对象级真值覆盖精确应用，未裁决对象保持冻结标签。

### Gate 1：稳定错误集合

- Control/Treatment稳定FP对象集合完全相同；
- 每个稳定对象在每个arm均精确包含seed 311/313/317；
- 两arm稳定FN均为0；
- 正式输入下稳定FP对象数必须为50，否则阻断并报告漂移。

### Gate 2：lineage与证据

- 50/50对象唯一连接Dataset-P1、P8 applicability与Scheme-A Segment inventory；
- 每个对象记录label weight、lineage method、source mask与QGIS工程；
- QGIS工程必须位于`E:\TestData\POC_Data\T10\<case>\`且实际存在；
- 普通Segment必须可按T01 `segment.id`定位；`ADVANCE_RIGHT`必须可按
  `prepared_swsd_roads.id`和source/target access定位；
- 不读取或写入geometry，不做空间join或silent fix。

### Gate 3：归因与人工清单

- 已确认对象与仅Case级0.7对象分开计数；
- 首轮人工清单严格按第4节规则生成；
- 每条人工任务只询问：
  `RealityChangeClue=true/false`、carrier合法集合/优选结果和简短原因；
- 审计不得自动应用任何新真值。

### Gate 4：安全与隔离

- training、threshold tuning、model weight change、Movement decision、
  geometry read/write与T01–T12修改计数均为0；
- P9/P10 carrier、fallback、RoadGraph和历史证据不改写；
- 稳定FN保持为0。

### Gate 5：确定性与QA

- 正式双跑content signature一致；
- 专项测试与完整P05回归通过；
- 新增源码/测试低于100KB，不新增CLI、script、T10 stage或正式入口。

## 6. 决策

- 审计可信且不存在未确认对象：
  `P05_SCHEME_A_P2_P3_P11_ATTRIBUTION_GO_NO_REVIEW`
- 审计可信但存在对象级真值缺口：
  `P05_SCHEME_A_P2_P3_P11_REVIEW_REQUIRED`
- 输入、join、确定性或隔离合同失败：
  `P05_SCHEME_A_P2_P3_P11_AUDIT_NO_GO`

`REVIEW_REQUIRED`只表示需要补充对象级业务真值，不表示神经网络不适用，也不授权
训练、调阈值、自动替换SWSD或生产接入。

## 7. 五类职责视角

### 产品

- 区分安全误报造成的自动化损失与错误发布风险；
- 优先提交最小高价值人工清单。

### 架构

- 保持Clue、carrier合法性、优选结果和fallback为独立语义；
- 不改变冻结T01 Segment/Junction骨架。

### 研发

- 新增P05内部只读callable，不登记正式入口；
- 输出完整ledger、首轮人工CSV、metrics、summary与manifest。

### 测试

- 覆盖对象级真值优先级、两arm集合一致、三seed稳定性、人工清单选择与确定性。

### QA

- 核验输入hash、POC_Data范围、零geometry处理、零训练、零历史工件改写和文件体量。

## 8. 首轮人工裁决收口

用户于2026-07-24完成19/19对象目视审计：

- `RealityChangeClue=false`：19；
- 只允许且优先`USE_RCSD`：12；
- 只允许且优先`KEEP_SWSD`：7；
- `USE_RCSD`对象同时确认两侧路口可正确锚定、替换连接正确；
- `KEEP_SWSD`对象均因RCSD数据全部或局部缺失，且不构成现实道路结构冲突。

收口实施必须：

1. 与原始人工队列逐行核对所有非填写列，禁止Excel编辑造成对象或证据漂移；
2. 将19行与P10既有5行合并为24个对象级1.0真值；
3. 复用冻结P9完成P10双跑，再用新P10快照完成P11双跑；
4. 不因人工裁决训练模型、调阈值或改写P9/P10/P11历史工件。
