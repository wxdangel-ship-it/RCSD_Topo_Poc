# P05-Scheme-A-P2-P3-P2 验证摘要

## 决策

`P05_SCHEME_A_P2_P3_P2_MODEL_NO_GO`

数据、scope、模型合同、确定性、资源和RoadGraph门全部通过；carrier与clue业务门
失败。该结论不授权自动替换SWSD、在线proposal、生产接入、T01–T12修改、
Movement训练或Git操作。

## 正式证据

- Run A：`p05_scheme_a_p2_p3_p2_oof_20260723_04`
- Run B：`p05_scheme_a_p2_p3_p2_oof_20260723_05`
- signature：
  `e1bc5b5e55ddeaba8f87cbaa36f8a6261461e206a72aa8d240385c46c30d534f`
- Run B `reference_run_match=true`
- scope、eligible score/decision/evaluation、all-segment decision、effective selection、
  closure和feature audit核心工件逐字节一致。
- Run 01/02为wall/path字段移出determinism payload前诊断；空Run 03为宿主中断
  残留，不作为正式指标来源。

## Scope与模型

- 全部Segment：8,863
- eligible监督/指标：6,275
- context-only：2,588
- context进入label/loss/threshold/calibration/metric：0
- context自动接受/非KEEP effective：0/0
- target：`4,487 KEEP_SWSD / 1,748 USE_RCSD / 40 REVIEW_FALLBACK`
- eligible clue-only：5
- 局部expected-failure group：2
- 网络参数：`2,818,234–2,818,810`
- 3 seeds × 5 Case folds；旧model state和旧threshold复用数为0
- T03/T04/T05只作auxiliary label，T06/Movement inference feature为0

## 业务指标

| seed | wrong accepted | Review auto | safety recall | safe coverage | USE coverage |
|---:|---:|---:|---:|---:|---:|
| 311 | 1 | 0 | 0.976744 | 0.353970 | 0.633867 |
| 313 | 13 | 12 | 0.404762 | 0.549479 | 0.703661 |
| 317 | 0 | 0 | 1.000000 | 0.150601 | 0.275744 |

| seed | clue recall | clue precision | clue macro-F1 | clue-only caught |
|---:|---:|---:|---:|---:|
| 311 | 0.980524 | 0.543964 | 0.775080 | 5/5 |
| 313 | 0.867025 | 0.997682 | 0.953598 | 4/5 |
| 317 | 0.995970 | 0.368447 | 0.587883 | 5/5 |

没有seed、fold和整体同时满足零错误、Review零发布、双50%覆盖及clue门。

## 失败对象

- 可靠target `T10-Error-2:89387685_507565991` 在seed311/313均被错误
  `KEEP_SWSD→USE_RCSD`。
- seed313把`T10:605415675`的12个`ADVANCE_RIGHT` Review错误自动接受为
  `KEEP_SWSD`。
- seed317通过大量clue/fallback达到零错误，但总体/USE coverage仅
  `0.150601/0.275744`，不能挑seed作为GO。

## 整图、GIS与资源

- 每seed精确49 `LEGAL` + 2 `EXPECTED_FAIL`
- context auto accept、expected-failure非目标级联、requirement conflict、
  Node mismatch、unexpected failure均为0
- skeleton mutation、repair、silent fix、geometry read/write、坐标变换均为0
- CRS=`EPSG:3857`
- Run A/B wall约`305.92s/289.69s`
- peak RSS约`2.44/2.43GB`，GPU VRAM=0
- 专项测试5 passed；完整P05回归210 passed；compileall通过

## 解释

Dataset-P1修正是必要条件，但不是当前基础模型GO的充分条件。旧错误上下文和
Case级联已被完全排除，整图安全方案也稳定成立；剩余问题是当前scorer对可靠
false-use与Review少数类的跨Case安全泛化。后续不得继续在本批held-out上调参，
应先把Review/ADVANCE_RIGHT硬安全资格与carrier scorer解耦，并为可靠target
false-use引入T06前可用的新表征或独立验证合同。
