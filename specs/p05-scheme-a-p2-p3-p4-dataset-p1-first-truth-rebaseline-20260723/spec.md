# P05-Scheme-A-P2-P3-P4：Dataset-P1-first Junction Truth Rebaseline

## 1. 状态与授权

- 状态：已完成（`P05_SCHEME_A_P2_P3_P4_TRUTH_REBASELINE_GO_NO_RESIDUAL_REPRESENTATION_REQUIRED`）
- 授权日期：2026-07-23
- 唯一实施工作树：`E:\Work\RCSD_Topo_Poc__wt_p05_neural_road_20260721`
- 数据范围：既有 P05 冻结工件与 `E:\TestData\POC_Data`
- Git：不提交、不推送
- 模型训练：本阶段不训练新模型
- T01–T12：不修改实现或接口
- Movement：忽略

用户已批准暂停 P2-P3-P3 所建议的新关系表征实验，先修正 P2-P1 真值构造的
闭包顺序。Dataset-P1 必须先冻结对象的标签资格，之后才能计算
Road endpoint/JunctionUnit 条件化 Node carrier 和 Junction fallback。

## 2. 目标

1. 以 Dataset-P1 的 6,275 个 `label_eligible=true` Segment 作为唯一监督真值
   范围；2,588 个 context-only Segment 仅作为输入上下文。
2. context-only Segment 在安全整图物化时确定性使用 `KEEP_SWSD`，但不产生
   Segment 标签、不参与 scorer 指标。
3. 在上述范围冻结后重建 Node/Junction 真值闭包，证明旧 P2-P1 真值中的
   carrier 冲突是否来自 context-only 标签污染。
4. 在不重训、不调阈值的前提下，用既有 P2-P3-P3 决策重算可靠对象指标，
   重解释残余 false-use 和“需要新关系表征”的历史结论。
5. 只在证据仍支持时才启动下一表征；本阶段不把单 Case 现象固化为业务强规则。

## 3. 冻结业务语义

1. T01 Segment 集合及 Junction 关系冻结，不得新增、删除、拆分、合并或重归属。
2. Dataset-P1 是 Segment 标签资格的唯一合同：
   - `label_eligible=true`：保留既有人工确认/策略重放标签；
   - `scope_class=CONTEXT_ONLY_MASKED`：只作为上下文输入，标签权重为空；
   - context-only 整图物化采用安全 `KEEP_SWSD`，上下文输入权重保持 `0.3`。
3. Junction fallback 只能在 Dataset-P1 范围冻结后计算；context-only 原始
   T06/Scheme-A label 不得触发对可靠 target 的监督真值级联。
4. Segment 冲突只回退该 Segment；共享 Node carrier 事实冲突才升级为
   Junction fallback。
5. `T10:609214532` 与 `T10:74155468` 继续保持局部 expected-failure。
6. 历史 P2-P1/P2-P3-P2/P2-P3-P3 工件只读保留，不覆盖、不删除。

## 4. 五类职责视角

### 产品

- 准确性和安全性优先，允许 fallback，不以自动化率换取错误 RCSD 发布。
- 本阶段回答的是“真值闭包是否正确”，不是“模型是否已经 GO”。
- 若残余 false-use 消失，撤销针对该残余对象启动新关系表征的理由。

### 架构

- 顺序固定为 `Dataset-P1 scope -> context KEEP -> Node/Junction closure -> metric`。
- P2-P1 的候选、特征、payload、compatibility edge 保持只读并按 hash 复用；
  只重建 Segment/Node 真值层。
- 模型推理决策、score、threshold 和 RoadGraph 结果不改变。

### 研发

- 只新增 P05 内部 callable、schema、测试和 SpecKit 工件。
- 不新增 CLI、root script、T10 stage 或正式执行入口。
- 不修改 geometry、CRS、T01–T12 或历史实验工件。

### 测试

- 覆盖 scope 1:1 join、context label 隔离、context 安全 KEEP、唯一候选匹配。
- 覆盖 Node payload 冲突、Junction closure 收敛、expected missing Node。
- 覆盖旧/新真值 delta、残余对象精确身份和三 seed 指标重算。
- 覆盖输入 hash、身份或门禁被破坏时 hard fail。

### QA

- 冻结输入 manifest/hash、对象分母、fold、seed 和输出 lineage。
- 正式 Run A/B 规范化签名一致。
- model training、threshold change、T06 inference feature、Movement、geometry
  read/write、坐标变换、骨架 mutation、repair、silent fix 均为 0。

## 5. 验收门禁

### Gate 0：输入与 Dataset-P1 范围

- Segment 总数 `8,863 = 6,275 eligible + 2,588 context-only`；
- scope 与 Scheme-A baseline/P1 candidate Segment 按
  `(case_key, object_id, group_id)` 全量 1:1 匹配；
- context-only 标签贡献数为 0，安全物化 `KEEP_SWSD` 数为 2,588；
- P2-P1 特征、payload、compatibility edge 的 hash 与历史工件一致。

### Gate 1：scope-first Node/Junction 真值

- context-first 后初始 shared Node payload conflict 数为 10；
- Junction fallback Segment 数为 21，其中 eligible 数为 10；
- 闭包后 shared Node conflict 和非预期 missing Node 均为 0；
- 最终 Node 真值数为 28,240；
- expected missing Node 仅为
  `T10:609214532/987665` 与 `T10:74155468/953982`。

### Gate 2：真值 delta

- 相对历史 P2-P1，Segment 真值变化总数为 436；
- 其中 context-only 变化 435，eligible 变化恰好 1；
- 唯一 eligible delta 为
  `SCHEME_A_P1:SEGMENT:T10-Error-2:89387685_507565991:89387685_507565991`；
- 该对象由 `KEEP_SWSD` 改回 `USE_RCSD`，真值 candidate 为
  `sap1:918ffd80e766808f8a6b516c`，`anomaly_target=false`；
- scope-first 全量 target 分布为
  `KEEP_SWSD=7,074 / USE_RCSD=1,749 / REVIEW_FALLBACK=40`。

### Gate 3：既有决策指标重算

- 三 seed accepted wrong 均为 0；
- 三 seed Review 自动发布均为 0；
- 三 seed carrier safety recall 均为 1.0；
- 原 P2-P3-P3 唯一残余 false-use 不再成立；
- 49 个 `LEGAL` 与 2 个 `EXPECTED_FAIL` 的既有整图证据 hash 不变；
- 模型仍按修正真值判为 NO-GO：safe coverage / clue 指标存在 seed/fold
  不稳定，不能把本阶段解释为 scorer 已可发布。

### Gate 4：结论、确定性与资源

- 不再以该残余对象为理由启动新关系表征；
- 下一阶段只能是基于修正真值的重新训练/验证，需用户另行授权；
- 正式 Run A/B 规范化 signature 一致，第二次运行
  `reference_run_match=true`；
- CPU RAM `<=8GB`，GPU VRAM=`0`，单次 wall `<=30min`；
- CRS=`EPSG:3857`，geometry read/write=`0`，coordinate transform=`0`。

## 6. 阶段决策

- 全部门禁通过：
  `P05_SCHEME_A_P2_P3_P4_TRUTH_REBASELINE_GO_NO_RESIDUAL_REPRESENTATION_REQUIRED`
- 任一事实、分母、delta、指标、确定性或资源门失败：
  `P05_SCHEME_A_P2_P3_P4_TRUTH_REBASELINE_NO_GO`

任何结论都不授权新模型训练、生产接入、T01–T12 修改、Movement 训练、
正式入口新增或 Git 操作。
