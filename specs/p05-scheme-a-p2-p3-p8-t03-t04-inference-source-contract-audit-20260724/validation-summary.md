# P05-Scheme-A-P2-P3-P8 验证摘要

## 1. 正式结论

- decision：
  `P05_SCHEME_A_P2_P3_P8_PARTIAL_GO_CARRIER_ONLY_CLUE_SOURCE_BLOCKED`
- 含义：T03/T04正式T05 handoff对carrier具有新增区分事实，允许进入字段级
  promotion二次评审；稳定Clue错误覆盖不足，Clue来源继续阻断。
- T03/T04仍为`model_input=false/label_only=true`；promotion applied=`false`。
- 未训练模型、未拟合calibrator、未调阈值、未修改T01–T12。

## 2. 来源与关联合同

- 51个eligible Case、663个T03/T04核心工件均存在且hash冻结。
- 255个来源GPKG layer和51个T01 Segment GPKG均为`EPSG:3857`。
- 2,710条T03/T04正式来源事实进入ledger。
- 6,275/6,275 eligible Segment均有applicability记录：
  - 504个具备适用来源；
  - 192个命中多个来源；
  - 5,771个明确为`NOT_APPLICABLE`。
- 关联只使用Case-local T01 `junc_nodes`精确ID；空间join、cross-Case join、
  silent merge均为0。
- ID、坐标、路径、free-text reason、review、T05/T06终态、truth和Movement
  promotion feature均为0。

## 3. Carrier 来源结果

- 稳定carrier wrong：
  `SCHEME_A_P1:SEGMENT:T10:609214532:505101583_506183080`。
- 该对象命中T04 `accepted + no_related_rcsd + status_suggested=1`来源。
- T04 `merge/diverge`保留为上下文候选，但carrier安全状态signature对方向不变；
  该归一化不改写T04业务类型。
- held-out-fold之外完全同类对象为2：
  - `T10:706247 / 706317_706319`
  - `T10:706247 / 706346_706349`
- 二者真值均为`KEEP_SWSD`、`clue=true`，`USE_RCSD=0`，held-out Case泄漏为0。
- carrier source gate=`true`。

## 4. Clue 来源结果

- P7的6个稳定Clue错误逐对象审计完成。
- 只有稳定carrier wrong具备T03/T04适用来源，覆盖=`1/6`。
- 其余5个对象没有T01 `junc_nodes`适用来源；absence保持`NOT_APPLICABLE`，
  不编码为负特征。
- semantic conflict=`0`，Clue source gate=`false`。

## 5. 确定性、资源与测试

- 正式Run A/B：
  `p05_scheme_a_p2_p3_p8_source_audit_20260724_02/_03`
- determinism signature：
  `4b3002494b6c33400907751aca44c375481a3602bb3cff1f8cad45bce8852508`
- Run B `reference_run_match=true`。
- 单次正式运行wall约48秒，peak RSS约0.274GiB，GPU=0。
- geometry write/transform、空间join、骨架mutation、repair和silent fix均为0。
- P8专项测试：`5 passed`。
- 完整P05回归：`236 passed`。
- 新增源码/测试均低于100KB；未新增CLI、script、T10 stage或正式入口。

## 6. 下一步边界

P8只证明carrier字段promotion值得二次评审。若继续，必须由用户另行批准
carrier-only字段合同和增量对照实验；Clue不得消费T03/T04 absence，T03/T04不得
整体提升为模型输入，也不得直接启动完整scorer训练或自动替换SWSD。
