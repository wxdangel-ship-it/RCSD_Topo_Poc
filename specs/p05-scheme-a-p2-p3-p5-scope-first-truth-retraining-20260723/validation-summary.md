# P05-Scheme-A-P2-P3-P5 验证摘要

## 1. 正式结论

阶段决策为 **`P05_SCHEME_A_P2_P3_P5_MODEL_NO_GO`**。

审计、训练数据、确定性、资源、执行范围和 RoadGraph 安全门全部通过；同一
2.818M 级分层模型在 scope-first 修正真值下仍未同时通过 carrier coverage 与
RealityChangeClue 的逐 seed、逐 fold 业务门。

这不是 `AUDIT_NO_GO`：工件与运行可信，NO-GO 是模型效果结论。

## 2. 冻结训练数据

正式 Dataset：

- `p05_scheme_a_p2_p3_p5_dataset_20260723_01`
- `p05_scheme_a_p2_p3_p5_dataset_20260723_02`

两轮均为 `P05_SCHEME_A_P2_P3_P5_DATASET_GO`，共同 signature：
`5efbe66318f818dd705dbd10acd48366e328d2f8e61bae51812a46d5cf61fb46`，
Run B `reference_run_match=true`。

分母闭合：

- 8,863 Segment = 6,275 eligible + 2,588 context-only；
- eligible target = 4,486 `KEEP_SWSD` + 1,749 `USE_RCSD` +
  40 `REVIEW_FALLBACK`；
- eligible anomaly = 1,488，eligible clue-only = 5；
- Node label = 28,240；
- duplicate group、truth candidate missing、context supervision 均为 0；
- candidate/feature/payload/compatibility 只读复用，标签层单独重建。

## 3. 模型、特征与防泄漏

- 网络：`p05-scheme-a-p2-p3-p0-network-v1`
- 参数量：2,818,234–2,818,810
- 训练：3 seeds `311/313/317` × 5 Case folds，共 15 个模型
- 推理证据：冻结 202 维 T01/T07 truth-free 证据
- truth、identifier、绝对坐标、Movement、T03/T04/T05/T06 inference feature
  均为 0
- 40 个 `ADVANCE_RIGHT access_valid=false` 与 40 个 Review 精确一致，三 seed
  共 120 个 decision 全部硬回退；非 Review 误触发为 0
- 2,588 个 context-only Segment 自动接受和非 `KEEP_SWSD` effective 均为 0

## 4. 正式 OOF 双跑

正式 Run：

- Run A：`p05_scheme_a_p2_p3_p5_oof_20260723_01`
- Run B：`p05_scheme_a_p2_p3_p5_oof_20260723_02`
- 训练引擎 A/B：
  `p05_scheme_a_p2_p3_p5_engine_20260723_02/_03`

OOF 共同 signature：
`de6c92d0bde80f2d0690af76a340931d802cdf5def7bc63601406040720dce02`；
训练引擎共同 signature：
`349111b038332620260fdea390dfcf500a794a714e457594167cd67c7750a94f`。
两项 Run B `reference_run_match=true`，全部声明 output 的 size/SHA-256 复核无误。

### 4.1 Carrier

| seed | wrong accepted | Review auto | safety recall | safe coverage | USE safe coverage | 结果 |
|---:|---:|---:|---:|---:|---:|---|
| 311 | 0 | 0 | 1.0 | 0.4290 | 0.6918 | coverage FAIL |
| 313 | 0 | 0 | 1.0 | 0.5498 | 0.7044 | seed PASS |
| 317 | 0 | 0 | 1.0 | 0.1374 | 0.2310 | coverage FAIL |

逐 fold 仍有多个 coverage FAIL，因此总体零错误不能替代逐 fold 门。

### 4.2 RealityChangeClue

| seed | recall | precision | macro-F1 | clue-only | 结果 |
|---:|---:|---:|---:|---:|---|
| 311 | 0.9805 | 0.6614 | 0.8512 | 5/5 | FAIL |
| 313 | 0.8831 | 0.9985 | 0.9596 | 4/5 | FAIL |
| 317 | 0.9960 | 0.3605 | 0.5751 | 5/5 | FAIL |

seed 311/317 主要为过报与 precision 不足，seed 313 主要为漏报；说明当前 clue
head 在不同 held-out 域之间仍不稳定。

## 5. RoadGraph、安全与资源

三个 seed 均为：

- 49 `LEGAL` + 2 `EXPECTED_FAIL`；
- `FAIL=0`；
- requirement conflict、Node target mismatch、Node conflict、hard-gate repair、
  非目标 Case 级联、content repair、silent fix、skeleton mutation 均为 0；
- CRS=`EPSG:3857`，geometry read/write=0，coordinate transform=0。

Run A/B wall 为 373.86s / 382.11s，峰值 RSS 为 2.70 / 2.67 GiB，GPU VRAM=0；
Case inference p95 为 0.0411s / 0.0520s，max 为 0.1960s / 0.2196s。全部资源门
通过。

## 6. 测试、入口与范围

- P5 专项测试：3 passed
- 完整 P05 回归：222 passed
- 新增/修改源码均低于 100KB
- 未新增 CLI、script、Makefile target、T10 stage 或 `__main__.py`
- 未修改 T01–T12 实现或接口
- 未提交或推送 Git

## 7. 业务解释与后续边界

P4/P5 已证明：旧稳定 false-use 来自真值闭包顺序，并已被 scope-first 修正；修正
真值后，当前链路能够以零错误自动接受和合法整图为安全底线运行。

但当前同架构模型只能通过大量 fallback 保持安全，且 RealityChangeClue 在不同
Case fold 上过报/漏报方向不一致。因此不能授权自动替换 SWSD，也不能通过选择
seed、在本批 held-out Case 上调阈值或恢复旧真值重报 GO。

下一阶段尚未授权。若继续，应先对修正真值下的 coverage 与 clue 失败做只读、
逐对象/逐 fold 归因，区分候选歧义、现有证据不可分、Case 域差异和阈值不稳，
再决定新增 truth-free 表征、调整模型结构或补充独立验证数据。
