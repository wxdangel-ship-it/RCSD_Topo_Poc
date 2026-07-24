# P05-Scheme-A-P2-P3-P6 验证摘要

## 1. 正式结论

阶段决策为
**`P05_SCHEME_A_P2_P3_P6_ATTRIBUTION_GO_DUAL_ROUTE_REQUIRED`**。

该 GO 表示失败归因已经闭合，并证明下一步需要“clue 校准 + T06 前表征”两条路线；
P5 模型结论仍为 `P05_SCHEME_A_P2_P3_P5_MODEL_NO_GO`。

## 2. 双层 carrier 结果

完整审计分母为每 seed 6,275 eligible Segment；safe coverage 分母按 P5 合同排除
40 个强制 Review，为 6,235。

| seed | scorer wrong | final wrong | scorer recall | scorer coverage | final coverage | scorer USE | final USE |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 311 | 1 | 0 | 0.975610 | 0.652446 | 0.429030 | 0.986850 | 0.691824 |
| 313 | 1 | 0 | 0.975610 | 0.795188 | 0.549800 | 1.000000 | 0.704403 |
| 317 | 1 | 0 | 0.976744 | 0.346913 | 0.137450 | 0.491710 | 0.230989 |

三 seed 唯一共同错误自动接受均为
`T10:609214532 / 505101583_506183080`，选择
`USE_RCSD`，真值为 `KEEP_SWSD`。最终整图未错误发布，是因为该 Case 本身为
`EXPECTED_FAIL`，不是因为 scorer 判断正确。

两个 `EXPECTED_FAIL` Case 每 seed 对 final publication 原子阻断
`1,795 + 159 = 1,954` 个 eligible 对象，其中 1,940 个非 Review；scorer 层仍只
记录每 seed 2 个 Dataset-P1 局部 failure group。

## 3. RealityChangeClue

| seed | FP | FN |
|---:|---:|---:|
| 311 | 747 | 29 |
| 313 | 2 | 174 |
| 317 | 2,629 | 6 |

稳定 FP=2、稳定 FN=4。15 个 fold threshold 范围为
`0.000296339975–0.998983204365`：seed 317 的极低阈值导致大规模过报，seed 313
的高阈值导致集中漏报，证明当前 calibration 跨 Case 域不稳定。

## 4. 证据可分性

- 202 维 evidence：6,275/6,275；
- clue error：3,587 条；
- 相反 clue 标签 exact evidence collision：0；
- 相反 clue 标签 exact group-signature collision：0；
- 稳定 FP/FN × 3 seeds 的 train-only 邻域审计：18 组；
- held-out Case 邻域泄漏：0。

稳定 carrier wrong 对象的 selected-vs-truth score margin 为
`19.9522/11.4283/15.5293`，clue probability 仅
`0.000216/0.000596/0.000925`；三 seed 的 top-20 训练邻域均为
`20/20 USE_RCSD` 且 `20/20 clue=false`。这不是单纯把阈值调高或调低可以解决的
错误，现有表征把该对象放在错误业务邻域。

## 5. 正式双跑与资源

- Run A：`p05_scheme_a_p2_p3_p6_attribution_20260724_03`
- Run B：`p05_scheme_a_p2_p3_p6_attribution_20260724_04`
- 共同 signature：
  `e753bb817be16841adf4832dbfe3d68ed579e7b851364dd54a4569bbbf180a1c`
- Run B `reference_run_match=true`
- wall：18.97s / 16.50s
- peak RSS：0.621 / 0.619 GiB
- GPU VRAM=0
- model training=0、threshold tuning=0
- geometry read/write=0、coordinate transform=0
- Movement、T06 inference feature、repair、silent fix、skeleton mutation均为0

## 6. 测试与范围

- P6 专项测试：5 passed
- 完整 P05 回归：227 passed
- 新增源码低于 100KB
- 未新增正式入口
- 未修改 T01–T12 实现或接口
- 未提交或推送 Git

## 7. 下一阶段边界

下一阶段尚未授权。若继续，目标不应是再次训练同一模型，而应先冻结：

1. 不使用 T06 终态的新 truth-free 关系/共享上下文表征；
2. 与 carrier scorer 解耦、按 Case 域校准的 clue/abstention 合同；
3. 保持 scorer/final publication 双层验收和独立验证边界。
