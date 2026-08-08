# T017-R1 表示过拟合门验收摘要

## 正式状态

`T017_R1_REPRESENTATION_NO_GO`

用户授权的 T017-R1 已完成。固定 8 条训练折强 Gold、固定 seed/学习率/step 上限和 blind
隔离均按训练前合同执行；没有读取冻结测试，没有启动正式 canary，也没有进入 T021。

## 训练合同

- 样本：固定 8 条 strong/train Junction，只精确读取预注册 sample ID。
- 配置：seed `20260808`、hidden dim `384`、AdamW、learning rate `0.002`、最多
  `1,500` step、每 `25` step评价。
- PASS：连续 3 个评价点同时满足 total loss `<=0.02`、teacher-forced 完整 exact `8/8`、
  free-run 完整 exact `8/8`，并且成员集合、cardinality、单/双打断、状态、主锚定、
  等价组和完整方案全部正确。
- 隔离：两次训练 `blind_test_access_count=0`、`canary_executed=false`。

## T017-R1 原始结果

工件：
`outputs/_work/p05_neural_road_generation/junction_graphset_v1_t017_r1_overfit_20260808/`

`summary.json` SHA256：
`4DA2065D67FA0352BC57D897D01FE2E013DEEFF2426A259B8F1FD90C0E0C512D`。

- 运行到 `1,500` step，total loss `0.0003613492`。
- teacher/free 完整 exact 均为 `4/8`，未达到连续 PASS。
- 状态、完整方案、anchor member/cardinality/set、主锚定、Node 等价组、Road break
  count/单打断/多打断全部正确。
- virtual-surface 逐对象成员 `41/41`、cardinality `6/6`，但 top-k set 仅 `2/6`。

只读 checkpoint 审计证明：4 个失败 Junction 分别有 `24/63/8/33` 个未标成
REQUIRED/FORBIDDEN 的可见候选。逐对象 BCE 正确地不把这些未裁决对象当负例，但原 loss
没有训练 REQUIRED 在固定 cardinality top-k 中必须优先，导致 REQUIRED 被未裁决候选挤出。

## REQUIRED coverage 修正与 R1A 复验

保持 UNKNOWN/REVIEW/缺失约束不进入二元正负标签，只新增相对排序监督：在存在监督
cardinality 时，所有 REQUIRED pointer 必须排在同 Junction 的其他候选之前。该修正不把
未知对象补造成 FORBIDDEN，也不改变候选域、Gold、decoder 或验收门。

复验工件：
`outputs/_work/p05_neural_road_generation/junction_graphset_v1_t017_r1a_overfit_20260808/`

`summary.json` SHA256：
`6680B8BDB7231EC4D801AA08C0B77C2A63735C5F563430EF3BB9728CB7B91546`。

- 与原 R1 使用相同样本、seed、优化器、学习率、评价间隔和 `1,500` step 上限。
- teacher/free 完整 exact 均提升到 `7/8`；virtual-surface set 从 `2/6` 提升到 `5/6`。
- 除 virtual-surface cardinality/set 外，其余评价组件全部满分；Road 单/双打断均正确。
- 最终 total loss `0.0215373375`，其中 virtual-surface cardinality loss
  `0.0208332390`，解释了绝大部分剩余 loss。
- 唯一失败 Case 为 `POC_Data:T03:765154|765154`：surface cardinality 真值为 `1`，模型输出
  `0.0000024945`，round 后为 `0`；其余 5 个有监督 cardinality 分别正确预测
  `0/6/5/10/4`。
- 新增 REQUIRED coverage loss 为 `0.0000121140`，说明 top-k 排序缺口已被修正；剩余问题
  集中在非负 cardinality 回归 head 对该样本饱和到近零，不能解释为一般概率阈值问题。

## 结论与停止边界

T017-R1 未满足任一完整 PASS 序列，正式结论保持 `REPRESENTATION_NO_GO`。不得：

- 进入 T021 或正式 canary；
- 读取 105 条冻结 blind test；
- 通过追加 epoch、seed 搜索、阈值放宽或只报 `7/8` 将结果解释为 GO；
- 把 `TRAINING_ORACLE_ONLY` 候选解释为真实推理候选生成能力。

下一轮若继续，技术问题应定义为“重新设计可离散表达 0..N 的 cardinality decoder/loss，
避免 Softplus 回归分支在单样本上饱和到零”，并重新经过训练前 readiness；这不需要修改
已确认的 REQUIRED/FORBIDDEN/UNKNOWN 业务语义，但需要单独实现与训练授权。

## 未改变边界

- T07 Step1 仍为 DriveZone-only；旧 T03/T04/T05 终态不进入推理输入。
- 未修改 T01–T12、正式 CLI、正式入口、T10 编排或城市 GIS 写出链。
- 业务输出仍以完整 JunctionResult 为目标；本结果只回答训练折内表示可学习性。
- overflow break 仍只能 ABSTAIN/fallback，不允许截断或静默修图。

## 回归验证

- 定向 model/overfit 测试：`14 passed`。
- P05 实际测试目录全量回归：`960 passed, 1 warning`；warning 为既有 Transformer
  `norm_first` nested-tensor 提示，不是测试失败。
- Python `compileall`、`git diff --check` 通过。
- P05 正式源码与实际测试目录共 `546` 个 Python 文件，`>=61440 bytes=7`、
  `>=100000 bytes=0`。
