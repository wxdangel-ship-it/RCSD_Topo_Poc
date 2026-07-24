# P05-Scheme-A-P2-P3-P7 验证摘要

## 1. 正式结论

- decision：`P05_SCHEME_A_P2_P3_P7_CURRENT_SOURCE_NO_GO`
- preserved P5：`P05_SCHEME_A_P2_P3_P5_MODEL_NO_GO`
- input P6：`P05_SCHEME_A_P2_P3_P6_ATTRIBUTION_GO_DUAL_ROUTE_REQUIRED`
- 含义：审计可信，但当前已授权T06前来源既不能使稳定carrier wrong可分，也不能
  通过单调clue calibration-only门；不授权下一轮训练。

## 2. 表征合同

- 历史202维evidence只读保留，不改写。
- 按用户授权剔除14个实际非零Movement命名维及其28个邻域派生维。
- 正式表征：`188 movement-free base + 377 compatibility-neighborhood
  + 37 T01 relative-geometry = 602`。
- 6,275/6,275 eligible对象表征完整且全部finite。
- 52条T01 inventory路径hash通过；51个eligible Case GPKG读取均为
  `EPSG:3857`，geometry read=51、write/transform=0。
- truth、identifier、absolute coordinate、T03–T06和Movement inference
  feature均为0。

## 3. 可分性结果

- 稳定carrier wrong：
  `SCHEME_A_P1:SEGMENT:T10:609214532:505101583_506183080`。
- held-out-fold train-only top-20：
  `20/20 USE_RCSD`，`20/20 clue=false`。
- 必须至少出现1个`KEEP_SWSD`与1个`clue=true`的门失败。

## 4. Clue校准结果

15个outer-fold inner pool均满足：

- positive `>=500`，实际最小741；
- negative `>=500`，实际最小2,794；
- held-out Case contribution=0；
- calibrator fit=0，threshold tuning=0。

recall固定为1时的最佳单调阈值诊断：

| seed | threshold | precision | macro-F1 | feasible |
|---:|---:|---:|---:|:---:|
| 311 | 0.000216041270 | 0.2406914894 | 0.2377453594 | false |
| 313 | 0.000595956924 | 0.2390622420 | 0.2287889980 | false |
| 317 | 0.000491000130 | 0.3607374190 | 0.5820278734 | false |

三个seed均未满足precision `>=0.80`、macro-F1 `>=0.85`。

## 5. 确定性、资源与测试

- 正式Run A/B：
  `p05_scheme_a_p2_p3_p7_audit_20260724_01/_02`
- determinism signature：
  `3154e4bb6af8358efcfff6f6dd5ed7ca90189f0d915d654d86fb1cbcdac2bcee`
- Run B `reference_run_match=true`，representation signature一致。
- 单次正式运行wall约11.24秒，peak RSS约0.559GiB，GPU=0。
- 完整P05回归：`231 passed`。
- 新增源码/测试均小于100KB；无CLI、script、T10 stage或正式入口变更。

## 6. 下一步边界

当前不得训练新scorer、拟合calibrator、调held-out阈值或自动替换SWSD。若继续，
必须由用户另行决策以下至少一项：

1. 将T03/T04的某类T06前输出从label-only提升为正式推理来源；
2. 授权建设不读取T06终态的确定性T06前关系生成器。
