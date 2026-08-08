# T017-R1 训练前验收摘要

## 状态

`IMPLEMENTATION_READY_AWAITING_T017_R1_AUTHORIZATION`

初次 T017 已执行并判定 `REPRESENTATION_NO_GO`；本轮 T017-A 只修正对象表示和解码结构，
没有训练、没有 optimizer step、没有 checkpoint、没有读取冻结测试、没有启动 canary。
当前没有新增业务认知冲突，也没有需要用户补充的业务裁决。

## 初次 T017 失败事实

- 固定训练折 8 条强 Gold、1,500 step，最终 total loss `1.3367981911`。
- teacher/free 完整 exact 均为 `3/8`。
- 状态类和 Oracle 完整候选选择为 `8/8`，但虚拟面成员 `34/41`、锚定成员
  `158/178`、Road 打断存在性 `8/12`、5 个单打断位置容差内 `0/5`。
- 多条不同 Road 得到近似相同 member/break 输出，确定为对象身份表示塌缩；不能通过阈值、
  更多 epoch 或 Oracle candidate scorer 掩盖。

历史工件位于
`outputs/_work/p05_neural_road_generation/junction_graphset_v1_t017_overfit_20260808/`。

## T017-A 架构修正

### 对象身份与相对表示

- 对每个对象显式保留 21D token 的 mean、max、首点、末点、std 和 token count；不使用
  raw ID embedding。
- Graph/Set 全局表示之后保留不可旁路的局部对象残差，并加入相对 SWSD query 的差分投影；
  避免同角色 Road/Node 被全局 attention 平滑成同一表示。
- encoder 参数量由 `6,574,720` 增至 `6,726,401`，仍位于预注册 5–8M 范围；模型总参数
  `12,960,296`。

### 成员 pointer/set decoder

- virtual-surface member 与 anchor member 分别输出逐对象 pointer logits 和非负 cardinality。
- 推理集合由预测 cardinality 决定数量，再从当前 Junction 的合法可见对象中 top-k；不扩充
  candidate、不使用 raw ID，也不把 UNKNOWN/Review 补造成确定真值。
- 有完整集合 Gold 时同时训练逐对象 REQUIRED/FORBIDDEN 和集合 cardinality；存在 UNKNOWN
  时 cardinality mask 为 0。

### Road 条件化多打断 decoder

- 每条 RCSD Road 独立输出 break count 与有序 fraction slots；同一 Road 两个打断点不再只
  监督 presence 或被 mask。
- 当前显式支持 0–4 个打断点，并保留 overflow class；超过上限时必须 ABSTAIN/fallback，
  不截断、不静默修图，因此这只是安全计算上限，不改变业务正确性定义。
- 当前固定 8 条强 Gold 最大打断数为 2，共 3 条双打断 Road，均已进入直接 count/fraction
  监督。

## 真实 8 条强 Gold dry-run

正式 readiness 工件：
`outputs/_work/p05_neural_road_generation/junction_graphset_v1_t017_r1_readiness_20260808/summary.json`

- `training_executed=false`、`optimizer_created=false`、`optimizer_step_executed=false`。
- blind access `=0`；只精确读取固定 8 条 strong/train 身份。
- 16 项 loss 全部 finite；新对象统计、relative projection、surface/anchor pointer、两个
  cardinality head、break count 与 fraction head 均获得非零梯度。
- 8 个 Case 内最近两条 Road embedding 距离最小值 `0.0521097407`，未出现完全相同表示。
- Step1 中 RCSD Node/Road/Intersection 数量 `0`；Surface 中 RCSD Node/Road 数量 `0`，
  DriveZone-only 与阶段防火墙未回退。
- CUDA dry-run 用时约 5.18 秒；峰值显存记录在 readiness 工件中。

## 静态可辨识与回归

- 构造两条旧 mean pooling 完全相同、但端点/std 不同的 RCSD Road；新 encoder 输出不同
  object embedding。
- hard decoy 只改变主锚定或 Node 等价组时，完整方案 scorer 可观察该字段变化。
- pointer-set 验证 cardinality + top-k；Road decoder 验证 count overflow 和严格有序
  fraction slots。
- source Node、生成 Road-break Node、混合等价组、独立 surface/anchor 成员和既有
  materializer/evaluator 合同均保留。
- `test_junction_graphset_v1_*.py`：`75 passed`。
- P05 实际测试目录全量回归：`959 passed, 1 warning`；warning 为既有 Transformer
  `norm_first` nested-tensor 提示，不是测试失败。
- Python `compileall` 与 `git diff --check` 通过。

## 隔离与未改变边界

- 冻结的 `spec.md`、`data-model.md`、`contracts/junction-result-contract.md` 和 freeze hash
  未修改。
- 旧 T03/T04/T05 策略终态仍不进入推理输入；T07 Step1 仍为 DriveZone-only。
- 没有修改 T01–T12、正式 CLI、正式入口、T10 编排或城市 GIS 写出链。
- `TRAINING_ORACLE_ONLY` 候选仍只用于表示 overfit 门，不代表真实 free-run 候选生成能力。

## T017-R1 训练门

下一步仅允许在用户明确授权后执行 T017-R1；继续使用相同 8 条强 Gold、相同 blind 隔离和
固定训练配置。PASS 必须连续 3 个评价点同时满足：

1. total loss `<=0.02`；
2. teacher-forced 完整 exact `8/8`；
3. free-run 完整 exact `8/8`；
4. pointer member、cardinality、break count、所有单/双 fraction、状态、主锚定、等价组和
   完整方案全部正确。

若 T017-R1 失败，仍停在表示层，不进入 T021、不调发布阈值、不读 blind test。

## 当前不代表

- 不代表 T017-R1 已训练或模型已经收敛。
- 不代表随机初始化 dry-run 的 loss/embedding 距离是准确率指标。
- 不代表 4 个显式打断 slot 可以截断更复杂业务；overflow 只能安全回退。
- 不代表 Segment、AdvanceRight、Movement 或 T07 Step2 已进入本阶段。
