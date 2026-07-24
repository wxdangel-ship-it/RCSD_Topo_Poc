# P05-Scheme-A-P2-P3-P10 验证结论

## 1. 正式结论

P10已完成，正式判定：

`P05_SCHEME_A_P2_P3_P10_TRUTH_REBASELINE_GO_P9_PROMOTION_NO_GAIN`

该结论表示对象级人工真值校准成功，P9旧“稳定模型错误”归因失效；但P9
Treatment相对Control仍无严格增益，source residual adapter不得promotion。

## 2. 人工裁决

| Case / Segment | allowed | preferred | RealityChangeClue | fallback |
|---|---|---|---:|---|
| `T10:609214532 / 505101583_506183080` | `USE_RCSD` | `USE_RCSD` | false | none |
| `T10:706247 / 706317_706319` | `KEEP_SWSD` | `KEEP_SWSD` | true | Junction |
| `T10:706247 / 706346_706349` | `KEEP_SWSD, USE_RCSD` | `USE_RCSD` | false | none |
| `T10:609214532 / 513242335_523239407` | `KEEP_SWSD` | `KEEP_SWSD` | false | Segment |
| `T10:609214532 / 606102026_609617028` | `KEEP_SWSD` | `KEEP_SWSD` | false | Segment |

对象级裁决权重为1.0，覆盖T10 Case级0.7；未裁决对象继续candidate-exact。
后两条属于RCSD数据缺失，不构成当前道路结构冲突。

## 3. Carrier复算

Control/Treatment在504个source-applicable对象、三seed合计1,512条记录上：

| 指标 | Control | Treatment |
|---|---:|---:|
| 合法准确率 | 1.0 | 1.0 |
| 优选命中率 | 0.9980158730 | 0.9980158730 |
| preferred macro-F1 | 0.9986771185 | 0.9986771185 |
| preferred KEEP recall | 1.0 | 1.0 |

三seed的scorer wrong accepted、Review auto publish与Junction fallback violation
均为0，carrier safety recall均为1.0。Treatment没有任何严格增益，
`pooled_strict_gain=false`。

## 4. RealityChangeClue

Treatment三seed合并：

- precision：`0.5832780358`
- recall：`0.9871967655`
- macro-F1：`0.8043590821`
- FP/FN：`3140/57`

两条新增裁决消除了6条seed级Clue漏报；按对象聚合后，三seed稳定Clue漏报为0，
仍有50个三seed稳定Clue误报。当前Clue问题已从“漏掉真实冲突”收敛为“保守地多报
冲突/多fallback”，但完整模型仍受冻结coverage门与Clue误报阻断。

## 5. 确定性与边界

- 三对象中间Run `_01/_02`保留为历史证据
- 五对象正式Run C/D：
  `p05_scheme_a_p2_p3_p10_adjudication_20260724_03/_04`
- content signature：
  `ef779bfaf89c2bbfc0ef27d8e0e52cbd9075f145c9c54cf100c350bc0557d9cc`
- Run D `reference_run_match=true`
- 训练、模型权重变化、Movement decision、geometry write：均为0
- P9模型、score、threshold、decision和RoadGraph未改写
- T01–T12、CLI、scripts和模块正式接口未修改
- 专项测试：3 passed
- 完整P05回归：245 passed
- P05源码/测试195个文件，`>=60KiB=0`、`>=100KB=0`

## 6. 后续边界

P10不授权生产接入、自动替换SWSD或用这五条事后裁决重训后重新报告同一held-out
结果。若继续训练，应建立独立的新阶段和验收目标；当前剩余问题是P9冻结coverage
门和RealityChangeClue校准，而不是609对象的carrier选择。
