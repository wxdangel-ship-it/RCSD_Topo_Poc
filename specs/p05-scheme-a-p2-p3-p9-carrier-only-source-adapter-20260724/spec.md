# P05-Scheme-A-P2-P3-P9：T03/T04 Carrier-only Source Adapter

## 1. 状态与授权

- 状态：正式实施、双跑和验收已完成；Promotion Model NO-GO
- 业务来源授权：2026-07-24 已批准
- P9训练与验收授权：2026-07-24 已批准
- 唯一实施工作树：
  `E:\Work\RCSD_Topo_Poc__wt_p05_neural_road_20260721`
- 承接结论：
  `P05_SCHEME_A_P2_P3_P8_PARTIAL_GO_CARRIER_ONLY_CLUE_SOURCE_BLOCKED`

用户已批准P8白名单内T03/T04正式T05 handoff字段只作为carrier软判断输入。
该授权不允许Clue消费这些字段，不允许将无来源解释为负样本，不改变冻结T01
Junction—Segment骨架、Node/Junction decoder、fallback或RealityChangeClue业务
语义，也不修改T01–T12。

## 2. 阶段目标

在同一3 seeds × 5 Case folds下建立严格A/B：

1. Control：P7的602维Movement-free表征，不读取T03/T04；
2. Treatment：冻结Control carrier scorer，只训练T03/T04 source residual adapter；
3. source adapter只影响carrier candidate logits；
4. Clue输出、access硬门、Node/Junction闭包和RoadGraph安全执行与Control相同；
5. 证明P8发现的新增来源能否在未知Case上纠正carrier判断，且不通过扩大fallback
   或污染无来源对象换取结果。

P9不是完整Clue模型阶段。即使carrier通过，也只允许形成
“carrier模型GO、Clue仍阻断”的阶段结论。

## 3. 模型方案

### 3.1 Control

- 沿用P5的object-conditioned candidate scorer和训练超参数；
- 将历史202维输入替换为P7冻结的602维Movement-free表征；
- 不读取Movement命名维、T03/T04、T05/T06终态、truth、ID或绝对坐标；
- 重新执行3 seeds × 5 Case grouped OOF，不复用旧模型权重。

### 3.2 Treatment

- 从对应Control fold checkpoint开始并冻结Control全部参数；
- 新增T03/T04 source encoder和candidate-conditioned residual adapter；
- source encoder消费P8批准的39个字段角色，以categorical unknown bucket、
  tri-state boolean、`log1p` count和DeepSets mean/max聚合表达多来源；
- T04 `junction_type/scene_type`保留上下文，carrier状态identity对
  `merge/diverge`方向不变；
- `source_applicable=false`时residual严格为0，使Treatment carrier logits与
  Control逐对象完全一致；
- adapter只在source-applicable训练对象上计算carrier loss，不读取Clue标签；
- source adapter trainable参数不超过300K，总参数不超过3.2M。

## 4. 冻结边界

- 训练标签仍为Dataset-P1/P4 scope-first carrier真值；
- 6,275 eligible和2,588 context-only分母不变；
- 40个`ADVANCE_RIGHT access_valid=false`仍由既有硬门Review；
- `T10:609214532`与`T10:74155468`继续`EXPECTED_FAIL`，局部failure group与
  final publication原子阻断分层报告；
- 无来源对象只走Control，不能用absence产生carrier或Clue信号；
- Clue head的T03/T04输入维、loss、decision均为0；
- 不调held-out阈值、不挑seed、不按正式结果回改字段或模型；
- Movement继续忽略；不修改T01–T12、CLI、script、T10 stage，不提交或推送Git。

## 5. 验收门

### Gate 0：来源、分母与隔离

- P7/P8/Dataset-P1/P4/P5输入manifest、hash和decision精确匹配；
- 51 Case、6,275 eligible、504 source-applicable及P8字段合同精确匹配；
- Case grouped split零交叉；held-out Case不参与训练、early stopping、vocabulary
  或阈值选择；
- truth/ID/坐标/path/reason/review/T05/T06/Movement推理维为0。

### Gate 1：架构隔离

- Control不读取T03/T04；
- Treatment只在carrier branch读取T03/T04；
- Clue source feature/loss/decision count为0；
- 5,771个无来源对象的Treatment/Control carrier logits、candidate选择和fallback
  逐对象完全一致；
- source adapter参数`<=300K`，总参数`<=3.2M`。

### Gate 2：Carrier promotion

每个seed均须满足：

- scorer-layer carrier wrong accepted=`0`；
- carrier safety recall=`1.0`；
- Review auto publish=`0`；
- 稳定对象`T10:609214532 / 505101583_506183080`自动选择正确`KEEP_SWSD`，
  不能只靠Clue或RoadGraph原子阻断遮蔽；
- source-applicable子集Treatment macro-F1和KEEP recall均不低于Control，且至少
  一项在三seed合并结果严格改善；
- 全量safe coverage与`USE_RCSD` safe coverage相对Control下降均不超过0.01；
- 不新增任何非source-applicable预测差异。

### Gate 3：完整Carrier模型门

在Gate 2基础上，沿用既有严格门：

- 每seed及每held-out fold总体safe coverage`>=0.50`；
- 每seed及每held-out fold `USE_RCSD` safe coverage`>=0.50`。

Gate 2通过但Gate 3失败，只能证明promotion有效，不能宣称完整carrier模型GO。

### Gate 4：RoadGraph与业务安全

- 每seed保持49 `LEGAL` + 2 `EXPECTED_FAIL`；
- Node payload conflict、requirement conflict、target mismatch、unexpected failure、
  context auto accept、localized failure auto accept均为0；
- skeleton mutation、geometry write/transform、content repair、silent fix均为0；
- Segment冲突、Movement/Junction fallback继续遵循方案A最小依赖闭包。

### Gate 5：确定性与资源

- 正式Run A/B规范化signature一致，Run B reference match=true；
- 单次正式运行wall`<=15min`、CPU RAM`<=8GiB`、GPU=0；
- case inference P95`<=0.5s`；
- 完整P05回归通过；新增源码/测试均低于100KB；
- 未新增入口、未修改T01–T12。

## 6. 阶段决策

- Gate 0–5全部通过：
  `P05_SCHEME_A_P2_P3_P9_CARRIER_MODEL_GO_CLUE_BLOCKED`
- Gate 0/1/2/4/5通过但Gate 3失败：
  `P05_SCHEME_A_P2_P3_P9_PROMOTION_GO_COVERAGE_AND_CLUE_BLOCKED`
- 审计可信但Gate 2失败：
  `P05_SCHEME_A_P2_P3_P9_PROMOTION_MODEL_NO_GO`
- 来源、隔离、确定性、资源或安全任一失败：
  `P05_SCHEME_A_P2_P3_P9_AUDIT_NO_GO`

任何P9 decision都不授权生产接入、自动替换SWSD或取消fallback。Clue路线仍需独立
后续阶段和用户授权。

## 7. 五类职责视角

### 产品

- 只回答T03/T04 carrier软证据是否真实改善未知Case，不把Clue失败混入carrier。

### 架构

- source residual adapter与Control、Clue、Node/Junction decoder严格隔离；
- applicability mask保证无来源行为不变。

### 研发

- 复用P5/P7/P8内部工件与callable；不新增正式入口或T01–T12接口。

### 测试

- 覆盖字段编码、unknown、multi-source池化、mask零残差、branch隔离、OOF和decision。

### QA

- 输入、split、checkpoint、参数、输出、资源、RoadGraph和双跑signature可追溯；
- 单独报告Control/Treatment、scorer/final、applicable/non-applicable四组结果。

## 8. 正式结果

- decision：
  `P05_SCHEME_A_P2_P3_P9_PROMOTION_MODEL_NO_GO`；
- 504个适用对象的Control/Treatment pooled macro-F1和KEEP recall均为
  `0.9986769935/0.99609375`，无严格增益；
- 稳定对象三seed仍选择`USE_RCSD`，scorer层错误自动接受均为1；
- 5,771个无来源对象score/decision差异为0，Clue source消费和概率差异为0；
- 每seed RoadGraph为49 `LEGAL`+2 `EXPECTED_FAIL`，冲突、repair和mutation为0；
- 正式Run A/B signature均为
  `e8f19d737a27e5789ea861e18730f11d192a9b97635ca25a8fd4ac299f37871b`，
  Run B reference match=true；
- wall=`375.97s/355.44s`、RSS=`2.72/2.66GiB`、P95=`0.114/0.100s`、
  GPU=0；完整P05回归242项通过。

因此Gate 0/1/4/5通过，Gate 2失败，Gate 3亦不成立。该结论不改写P8历史partial-GO，
但当前source residual adapter不得进入自动替换、生产接入或无授权续训。
