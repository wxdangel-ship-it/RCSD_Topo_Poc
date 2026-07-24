# P05-Scheme-A-P2-P3-P4 验证摘要

## 1. 结论

阶段正式完成，判定：

`P05_SCHEME_A_P2_P3_P4_TRUTH_REBASELINE_GO_NO_RESIDUAL_REPRESENTATION_REQUIRED`

该 GO 表示 Dataset-P1-first 真值闭包顺序、标签 delta、残余对象重解释、确定性和
资源门全部通过；不表示模型 GO，也不授权训练或生产接入。

## 2. 真值重基线

- Segment：`8,863 = 6,275 eligible + 2,588 context-only`
- context 标签贡献：0；安全 `KEEP_SWSD`：2,588
- 初始 shared Node payload conflict：10
- Junction fallback Segment：21，其中 eligible 10
- 最终 Node truth：28,240；冲突/非预期 missing：0
- 全量 target：`KEEP_SWSD=7,074 / USE_RCSD=1,749 / REVIEW_FALLBACK=40`
- eligible anomaly：1,488

相对历史 P2-P1 的 Segment 标签变化为
`436 = 435 context-only + 1 eligible`。唯一 eligible delta 是
`SCHEME_A_P1:SEGMENT:T10-Error-2:89387685_507565991:89387685_507565991`：

- 旧：`KEEP_SWSD`、candidate `sap1:9f1ffa2f74258c407d61388c`、
  `anomaly_target=true`
- 新：`USE_RCSD`、candidate `sap1:918ffd80e766808f8a6b516c`、
  `anomaly_target=false`

## 3. 既有决策重算

三 seed 的 accepted wrong 均为0，Review auto均为0，carrier safety recall均为
1.0。原 P2-P3-P3 残余 false-use 消失，说明它来自 context-only 先参与
Junction真值闭包的顺序缺陷，而不是当前特征无法区分。

模型仍为 `MODEL_NO_GO_COVERAGE_OR_CLUE_UNSTABLE`：

| seed | safe coverage | USE coverage | clue recall | clue precision | clue macro-F1 |
|---:|---:|---:|---:|---:|---:|
| 311 | 0.354130 | 0.634077 | 0.981183 | 0.543964 | 0.775233 |
| 313 | 0.549639 | 0.703831 | 0.883737 | 0.997724 | 0.959607 |
| 317 | 0.150601 | 0.275586 | 0.995968 | 0.368199 | 0.587705 |

## 4. 正式运行与验证

- Run A：`p05_scheme_a_p2_p3_p4_rebaseline_20260723_01`
- Run B：`p05_scheme_a_p2_p3_p4_rebaseline_20260723_02`
- signature：
  `3f2f2399a11a1b4675bc5b30d29043e764bd7991a71c2d06f6fccbdde265ed37`
- Run B `reference_run_match=true`
- wall：约129.26/127.38秒
- peak RSS：约2.25 GiB
- GPU、训练、阈值变化、T06推理字段、Movement、geometry、坐标变换、
  repair、silent fix、骨架 mutation：0
- 既有 RoadGraph：每seed 49 `LEGAL` + 2 `EXPECTED_FAIL`，工件hash验证通过
- 专项测试：3 passed
- 完整 P05 回归：219 passed
- 新增/修改源码与测试均低于100 KB

## 5. 后续边界

P2-P3-P3 的原始工件和当时结论保留为历史证据，但“残余对象要求新表征”已被
P4重解释。下一阶段若继续，应先申请基于scope-first真值的模型重训/复验授权；
不得直接启动新表征、调现有held-out阈值、修改T01–T12或进入生产。
