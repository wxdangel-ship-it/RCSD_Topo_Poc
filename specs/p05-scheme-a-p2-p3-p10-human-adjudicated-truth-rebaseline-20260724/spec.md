# P05-Scheme-A-P2-P3-P10：人工裁决集合真值校准

## 1. 状态与授权

- 状态：已完成
- 用户授权：2026-07-24 先后同意五个对象的人工裁决并继续
- 唯一实施工作树：
  `E:\Work\RCSD_Topo_Poc__wt_p05_neural_road_20260721`
- 承接阶段：P9正式Run B
  `p05_scheme_a_p2_p3_p9_oof_20260724_02`

P10不得改写P9历史模型、阈值、训练工件或原始证据。五个对象的裁决发生在看到P9
输出之后，因此本阶段只允许冻结输出复算，不允许用这些裁决重训后再报告同一
held-out结论。

## 2. 阶段目标

1. 将对象级人工确认以权重1.0覆盖T10 Case级0.7真值；
2. 区分`allowed_targets`、`preferred_target`与独立`RealityChangeClue`；
3. 保留未裁决对象的candidate-exact历史真值，不全局放宽安全口径；
4. 对Control/Treatment三seed冻结输出复算carrier合法准确率、优选命中率、
   Clue和错误自动接受；
5. 判断P9 NO-GO来自错误真值、模型安全问题还是Treatment无严格增益。

## 3. 人工裁决

- `T10:609214532 / 505101583_506183080`：
  仅允许且优先`USE_RCSD`，`RealityChangeClue=false`。
- `T10:706247 / 706317_706319`：
  最终仅允许`KEEP_SWSD`，`RealityChangeClue=true`，执行Junction fallback；
  `USE_RCSD`只允许作为候选，不得正式发布。
- `T10:706247 / 706346_706349`：
  `USE_RCSD/KEEP_SWSD`均合法，优先`USE_RCSD`，
  `RealityChangeClue=false`。
- `T10:609214532 / 513242335_523239407`：
  仅允许且优先`KEEP_SWSD`，RCSD数据缺失但道路结构不冲突，
  `RealityChangeClue=false`。
- `T10:609214532 / 606102026_609617028`：
  仅允许且优先`KEEP_SWSD`，RCSD数据缺失但道路结构不冲突，
  `RealityChangeClue=false`。

## 4. 冻结边界

- P9 Control/Treatment模型、score、decision、threshold和RoadGraph全部只读；
- 不训练、不调参、不挑seed，不把人工裁决编码为推理特征；
- 不修改T01–T12实现、接口、工件或正式入口；
- 不改变T01 Segment/Junction骨架、fallback闭包或T07 `DRIVEZONE_ONLY`；
- P9与P8历史结果保留，不删除、不回写。

## 5. 验收门

### Gate 0：输入与裁决完整性

- P9五个必需工件与其artifact manifest hash、size精确一致；
- 五个裁决对象在Control/Treatment与三个seed中均唯一命中；
- 人工裁决权重均为1.0，preferred必须属于allowed集合。

### Gate 1：安全与集合真值

- 未裁决对象继续candidate-exact；
- 裁决对象按allowed集合判断合法性；
- scorer wrong accepted、Review auto publish和Junction fallback violation均为0；
- carrier safety recall为1.0。

### Gate 2：Promotion复算

- 分开报告合法准确率、优选命中率与preferred macro-F1/KEEP recall；
- Treatment不得低于Control，并且至少一项严格改善，才可重新打开promotion；
- Control/Treatment相同即明确为“真值校准通过，但P9无promotion增益”。

### Gate 3：Clue与业务边界

- Clue按五条人工裁决独立复算；
- Clue失败不得改写carrier合法性，也不得通过修改fallback掩盖；
- 训练、模型权重、Movement、geometry write与T01–T12修改计数均为0。

### Gate 4：确定性、资源与QA

- 五对象正式双跑内容signature一致；
- 只读复算，不重建RoadGraph；
- 新增源码、测试均低于100KB，不新增执行入口。

## 6. 决策

- 审计可信且Treatment严格改善：
  `P05_SCHEME_A_P2_P3_P10_TRUTH_REBASELINE_GO_P9_PROMOTION_REOPENED`
- 审计可信但Treatment无严格改善：
  `P05_SCHEME_A_P2_P3_P10_TRUTH_REBASELINE_GO_P9_PROMOTION_NO_GAIN`
- 输入、join、确定性或安全合同失败：
  `P05_SCHEME_A_P2_P3_P10_AUDIT_NO_GO`

任何P10结论都不授权生产接入、自动替换SWSD或使用当前人工裁决重训。

## 7. 五类职责视角

### 产品

- 将“业务合法”和“优选结果”分开，避免把同样正确的保守结果误判为错误。

### 架构

- 人工裁决作为label/evaluation overlay，不进入模型输入或历史工件。

### 研发

- 只新增P05内部只读audit callable、合同和专项测试。

### 测试

- 覆盖单一真值、集合真值、优选未命中、Clue独立错误与Junction fallback。

### QA

- 冻结输入hash、裁决manifest、逐seed ledger、双跑signature和零训练证据。
