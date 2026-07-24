# P05-Scheme-A-P2-P3-P6：双层失败归因与证据可分性审计

## 1. 状态与授权

- 状态：已完成
- 授权日期：2026-07-24
- 唯一实施工作树：`E:\Work\RCSD_Topo_Poc__wt_p05_neural_road_20260721`
- 数据范围：既有 P05 冻结工件与 `E:\TestData\POC_Data`
- 训练与调参：禁止
- Git：不提交、不推送
- T01–T12：不修改实现或接口
- Movement：忽略

本阶段承接 `P05_SCHEME_A_P2_P3_P5_MODEL_NO_GO`。P5 原始工件不得改写；
P6 只读解释 P5 的 scorer decision、RealityChangeClue 与最终 RoadGraph publication。

## 2. 阶段目标

1. 将 P5 的 carrier 指标拆成两个层次：
   - scorer decision：整图原子阻断前的逐对象判断；
   - final publication：RoadGraph 合法性与 `EXPECTED_FAIL` 原子阻断后的发布结果。
2. 逐 seed、逐 fold、逐 Case、逐对象解释 carrier 与 clue 的错误和 fallback 来源。
3. 审计 202 维 T01/T07 truth-free 证据是否存在精确冲突、局部邻域混淆或域偏移。
4. 区分候选排序错误、clue 校准不稳、现有证据不可分和发布层安全阻断。
5. 给出下一阶段应优先改“表征”“校准”还是“验证合同”的技术结论。

本阶段的 GO 只表示归因审计完成且证据足以支持下一步路线，不表示 P5 模型 GO，
不授权训练、自动替换 SWSD、在线 proposal 或生产接入。

## 3. 冻结业务语义

1. T01 Segment/Junction 骨架冻结；模型不得新增、删除、拆分、合并或重归属。
2. 6,275 个 eligible Segment进入双层指标；2,588 个 context-only 只作上下文。
3. `T10:609214532` 与 `T10:74155468` 保持 `EXPECTED_FAIL` 且整图不可发布。
4. 上述 Case 的对象级 scorer 指标只对 Dataset-P1 登记 failure group 局部失败；
   final publication 指标必须如实记录整 Case 原子阻断，不得称为“非目标级联为零”。
5. 40 个 `ADVANCE_RIGHT access_valid=false` 保持 scorer 后硬安全回退。
6. T03/T04/T05 只作历史 auxiliary label；T06、truth、ID、绝对坐标和 Movement
   不得成为推理证据。
7. 不更改 P5 的模型、score、threshold、decision、effective 或 RoadGraph 工件。

## 4. 五类职责视角

### 产品

- 准确性与安全性优先；错误自动接受不能由最终整图阻断掩盖。
- scorer 自动化能力和 final publication 安全能力必须分别汇报。
- 归因结果必须能用业务语言说明下一步投入是否合理。

### 架构

- 以 P5 manifest/hash 为只读输入，建立双层审计工件，不介入推理链。
- `EXPECTED_FAIL` 原子阻断仍是通用 RoadGraph 安全约束。
- 可分性审计只在每个 held-out fold 对应的训练折内找邻居，禁止跨折泄漏。

### 研发

- 只新增 P05 内部 audit callable、schema、测试与 SpecKit。
- 不新增 CLI、root script、T10 stage、`__main__.py` 或 Makefile target。
- 不训练模型、不调整阈值、不修改历史 P5 工件。

### 测试

- 覆盖 scorer/final 双层分母、错误、覆盖率和安全 recall。
- 覆盖 `EXPECTED_FAIL` Case 原子阻断与局部 failure group 的分离。
- 覆盖归因分类、稳定 FP/FN、精确冲突和 train-only 邻域。
- 覆盖正式 Run A/B、完整 P05 回归和 source hash 破坏 hard fail。

### QA

- 每个输入、参数、输出和运行环境可追溯。
- 正式 Run A/B 规范化 signature 一致。
- model training、threshold tuning、geometry read/write、coordinate transform、
  repair、silent fix、skeleton mutation 均为 0。

## 5. 验收门禁

### Gate 0：输入与范围

- P5 decision 精确为 `P05_SCHEME_A_P2_P3_P5_MODEL_NO_GO`；
- P5、训练 engine、Dataset-P1 与 202 维 evidence manifest/hash 全部通过；
- 3 seeds × 6,275 eligible = 18,825 个 scorer decision唯一 join；
- context、Movement、T06 inference 和 geometry 贡献均为 0。

### Gate 1：双层度量闭合

- scorer 层与 final publication 层的分母均为每 seed 6,275；
- scorer 层错误自动接受固定为 `1/1/1`；
- final publication 层错误发布固定为 `0/0/0`；
- scorer safe coverage 固定为
  `0.6524458701/0.7951884523/0.3469125902`；
- final publication safe coverage 与 P5 固定为
  `0.4290296712/0.5497995188/0.1374498797`；
- 每 seed 恰有 1,954 个 eligible 对象因两个 `EXPECTED_FAIL` Case整图原子阻断，
  其中 1,940 个非 Review 对象进入 coverage 差异。

### Gate 2：逐对象失败归因

- 三 seed 唯一 carrier wrong accepted 均定位到
  `T10:609214532 / 505101583_506183080`；
- clue FP/FN 固定为 `747/29`、`2/174`、`2629/6`；
- 稳定 FP=2、稳定 FN=4；
- 每个 eligible seed-object 有且只有一个主归因，计数可回算双层指标。

### Gate 3：证据可分性

- 所有 clue FP/FN 与 train fold 的相反标签精确 evidence collision 为 0；
- 相反标签完整 group signature collision 为 0；
- 对 2 个稳定 FP、4 个稳定 FN执行每 seed train-only top-20 邻域审计；
- held-out Case进入邻域候选数为 0；
- 稳定 carrier wrong 对象的邻域、score margin、utility margin与 clue 概率完整记录。

### Gate 4：确定性、资源与范围

- Run A/B 规范化 signature一致且 Run B reference match=true；
- CPU RAM `<=8GiB`、GPU VRAM=0、wall `<=10min`；
- model training count=0、threshold tuning count=0；
- CRS=`EPSG:3857`，geometry read/write=0，coordinate transform=0；
- 未新增正式入口，未修改 T01–T12。

## 6. 阶段决策

- 全部审计门通过且归因同时证明 calibration 与 representation 两条独立问题：
  `P05_SCHEME_A_P2_P3_P6_ATTRIBUTION_GO_DUAL_ROUTE_REQUIRED`
- 输入、闭合、确定性或审计可信度失败：
  `P05_SCHEME_A_P2_P3_P6_ATTRIBUTION_AUDIT_NO_GO`

无论 P6 结果为何，P5 模型结论保持
`P05_SCHEME_A_P2_P3_P5_MODEL_NO_GO`。

## 7. 完成结论

本阶段正式判定
**`P05_SCHEME_A_P2_P3_P6_ATTRIBUTION_GO_DUAL_ROUTE_REQUIRED`**。该 GO 只表示
只读归因闭合，不表示模型 GO。

- scorer 层每 seed 均有 1 个错误自动接受，final publication 层均为 0；
- 6,235 个非 Review 可自动化对象上的 scorer safe coverage 为
  `0.6524458701/0.7951884523/0.3469125902`，final publication safe coverage 为
  `0.4290296712/0.5497995188/0.1374498797`；
- 两个 `EXPECTED_FAIL` Case 每 seed 原子阻断 1,954 个 eligible 对象，其中
  1,940 个为非 Review；对象级局部 failure group 仍为 2；
- clue FP/FN 为 `747/29`、`2/174`、`2629/6`，稳定 FP=2、稳定 FN=4；
- 全部 3,587 条 clue error 的相反标签 exact evidence/group-signature collision
  均为 0，train-only 邻域无 held-out Case 泄漏；
- 稳定 carrier wrong 对象在三 seed 均以大 margin 误选 `USE_RCSD`，其 top-20
  训练邻域均为 `USE_RCSD + clue=false`；
- fold clue threshold 从 `0.000296` 到 `0.998983`，同时出现大量过报与漏报。

因此下一技术路线必须同时处理 RealityChangeClue 校准和 T06 前 truth-free 表征，
不能只调当前阈值，也不能只扩大同一模型。
