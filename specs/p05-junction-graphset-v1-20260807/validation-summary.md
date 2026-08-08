# T017-R2 与 T021 P1 验收摘要

## 当前正式状态

`T021_P1_COMPLETE_AWAITING_T022_AUTHORIZATION`

固定 seed `20260821` 的 T021 P1 teacher-forcing 已完成。训练在 epoch 9 由 patience `4`
自动 early-stop，best checkpoint 为 epoch 5；没有读取冻结 blind test，也没有执行 T022、
正式 free-run 或 canary。完成工件位于：
`outputs/_work/p05_neural_road_generation/junction_graphset_v1_t021_teacher_forcing_seed_20260821/`。

### T021 P1 完整性与收敛

- 9 个 epoch 均完整覆盖 train `3,645`、validation `643`；所有 loss finite，运行时无
  OOM/NaN，blind access `=0`。
- best epoch 5 的 validation teacher total 为 `5.00013260374173`；summary、history 与
  checkpoint epoch 严格一致。checkpoint 使用 hidden dim `384`、seed `20260821`，scope 为
  `T021_TEACHER_FORCED_COMPONENT_ONLY`，`formal_release_eligible=false`。
- 同 seed 初始化 validation teacher/free-condition total 分别为
  `19.6856497524/20.1567138083`；best 分别为 `5.0001325185/6.6191701199`，相对下降
  `74.60%/67.16%`。P1 teacher-forcing 可学习性通过，但 teacher/free 差距仍为
  `1.6190376015`。
- 强 Gold 105 条：teacher `21.2261906124 -> 6.5905783199`，free
  `21.5562456767 -> 8.8208365122`；T10 538 条：teacher
  `19.3849865734 -> 4.6897295275`，free `19.8835709715 -> 6.1894768649`。
  强 Gold 不是已解决子集，其绝对 loss 和条件传播差距均高于 T10。
- 主要条件传播缺口为：T10 `surface_mode +1.2398706832`，强 Gold
  `anchor_state +1.1324645904`、`quality +1.0977901099`。Road-break fraction 在训练历史中
  几乎没有改善；teacher-oracle 下的 `complete_plan` 近零不能解释为完整业务正确。

### T021 P1 结论与边界

T021 的正式结论为：`P1_LEARNABILITY_PASS_AWAITING_T022`。这证明共享 encoder/分层 head
能从现有强/弱标签中学习，但不证明真实候选生成、free-run 整体 exact、安全自动接受或
城市级 RoadGraph 正确。下一步只有一个授权点：是否按预注册边界进入 T022 scheduled
sampling，针对 teacher/free 条件传播差距训练并逐阶段报告断联；禁止借此启动阈值/seed
搜索、正式 canary 或 blind test。

完成审计 SHA256：

- `summary.json`：`C52891D00ABF4C795D2C5EAD5887B263F21252092551085204249387C2FB86B9`；
- `history.json`：`28B090D76EBA750FA274AC309AAB75ACCA7578E43A61F0703AC1F1600033229D`；
- `best-checkpoint.pt`：`28028E4D2CF7CEA1BDEA23BB3AB7A7E2EA70EBB2E13BE0010CAD2042572603FB`；
- `initial-validation-source-audit.json`：
  `18728F3B9FD005808E3423204A136BC05945738611C5F9972C734C0601144916`；
- `best-validation-source-audit.json`：
  `A3EE494B5860B3A096426B936BA02D23685FDD6D99C299515CA2DEEB419D518E`；
- `completion-audit.json`：`D64A9E6C020565699FDC35546B12A4CF7D9769925FAE8DE944CA2223E6E771BA`。

## T021 训练前历史状态

`T021_READY_FOR_TRAINING_AUTHORIZATION`

用户授权的范围是“按 T021 推进至训练前”。本轮已完成全量非 blind 数据链、loss 缺口、
固定 split、训练缓存、内部 trainer 和锁定 CUDA 环境，不启动训练。最终工件为：
`outputs/_work/p05_neural_road_generation/junction_graphset_v1_t021_readiness_20260808/`。

### T021 数据与 IO 合同

- 开发记录 `4,288`：强 Gold `602`、T10 弱标签 `3,686`；train `3,645`、validation
  `643`。
- train/validation Case-group 分别 `501/106`，跨 split `0`；强 Gold 多版本仍按基础
  Case-group 锁在同一 split，forward identity 使用输入 fingerprint 版本后缀保持唯一。
- 强 Gold 全部按已确认口径使用权重 `1.0`；旧 joint store 中 14 条遗留 `0.5` 已显式
  归一化并计入 audit。T10 全部保持 `0.7`。
- feature 与 label 分为 136 对 `.features.pt/.labels.pt`，并按 source/split 物理分区：
  strong train/validation `16/4`，T10 train/validation `99/17`。训练每 epoch 只读目标 split
  分片一次；validation 在同一遍读取中同时计算 teacher/free-condition 诊断。
- 20 个上游输入文件在最终 cache 构建中各顺序读取一次；未重开原始 GIS，未读取 blind。

### T021 标签覆盖与 loss 修正

- `EXISTING_RCSD_INTERSECTION` 对象监督 `1,514` 条；补齐了原模型存在输出但没有对象 loss
  的结构缺口。
- 虚拟面三态监督 `1,680` 条；cardinality 使用从 REQUIRED 数量到排除 FORBIDDEN 后上限
  的 acceptable set，不再把 UNKNOWN 错当负例。5 条冲突 Review 保持零成员/完整方案 loss。
- 完整 anchor Node/Road set `2,973` 条；主锚定、Node 等价关系和 Road break 继续分别监督。
- 可监督完整 teacher plan `3,454` 条。旧 derived oracle 的 `3,459` 中 5 条与正式 surface
  Review 冲突，按冻结合同屏蔽，不用旧 exact member 结果覆盖 Review。
- 68 条 T10 旧 candidate 多解记录完整保留在 audit；其中非 preferred 候选没有独立完整
  Road-break/Node-equivalence Gold，故不补造成完整 plan。训练采用已有规范化完整方案；
  acceptable-set loss 继续用于真实存在的多类/多 cardinality 监督。

### 无训练 readiness 结果

- 全量 cache `4,288/4,288` 可加载；Step1 view `4,288/4,288`，非法 RCSD/
  RCSDIntersection 角色 `0`。
- 10 条真实 probe 覆盖 strong/T10、train/validation、existing/virtual surface、UNKNOWN
  cardinality、完整 anchor、等价组、Road break、NO_EVIDENCE、QUALITY 和 masked plan。
- 所有 18 项 loss finite；真实 Road-break presence/count/fraction/set-fraction 均进入 probe。
- RTX 5090 CUDA 双前向最大绝对差 `5.3644180e-7`，低于 `1e-6` 数值重复容差；峰值
  CUDA memory `14,098,432` bytes。
- 标准环境：Python `3.10.12`、Torch `2.9.1+cu128`、CUDA 可用。
- `training_executed=false`、`optimizer_created=false`、`backward_executed=false`、
  `checkpoint_written=false`、blind access `=0`。

预注册 trainer 配置为 seed `20260821`、hidden dim `384`、AdamW learning rate `3e-4`、
weight decay `1e-4`、最多 24 epoch、early-stopping patience `4`、minimum improvement
`1e-4`、gradient clip `1.0`。动态 batch 上限为 8 个 Junction 或 12,000 个 geometry token；
真实 cache dry iteration 为 train `3,645` 条/489 batch、validation `643` 条/103 batch，
最大 batch token 分别 `11,969/11,997`，没有截断超大 Junction。

训练前回归：GraphSet 专项 `88 passed`；P05 实际测试目录全量 `972 passed, 1 warning`；
T07 正式相关测试 `21 passed`。warning 仍为既有 Transformer `norm_first` nested-tensor
提示，不是本轮失败。P05 与 T07 因各自存在同名 `test_runner.py` 必须分目录运行；联合
collection 的模块名冲突不计业务测试失败。

工件 SHA256：

- `manifest.json`：`98BFBC0BB705FFEF145EA2A0A73B053149FEB1A8785E1EA03500499045EF81E6`；
- `readiness-summary.json`：`316FB83227ABD3428CA517F42A5A9371A4B092C0F76F46ECD9DB9307964921A4`；
- `training-preflight.json`：`B7541FFDEAC7488E97F9217BDCE897AFD098930D5513F0167C08728644C7E20A`。

下一步只有一个授权点：是否启动固定配置的 T021 P1 teacher-forcing 训练。T022 scheduled
sampling、正式 free-run/canary、阈值/seed 搜索和 blind test 均未获授权。

## T017-R2 历史正式状态

`T017_R2_REPRESENTATION_PASS_AWAITING_T021_AUTHORIZATION`

用户授权的 T017-R2 已完成并通过训练折内表示过拟合门。没有读取冻结测试、没有启动正式
canary，也没有进入尚未授权的 T021。T017-R1 的历史 NO_GO 工件继续保留，不被 R2 覆盖。

## 训练合同

- 样本：固定 8 条 strong/train Junction，只精确读取预注册 sample ID。
- 配置：seed `20260808`、hidden dim `384`、AdamW、learning rate `0.002`、最多
  `1,500` step、每 `25` step评价。
- PASS：连续 3 个评价点同时满足 total loss `<=0.02`、teacher-forced 完整 exact `8/8`、
  free-run 完整 exact `8/8`，并且成员集合、cardinality、单/双打断、状态、主锚定、
  等价组和完整方案全部正确。
- 隔离：T017-R1、R1A、R2 均为 `blind_test_access_count=0`、
  `canary_executed=false`。

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

## T017-R1 历史结论与当时停止边界

T017-R1 未满足任一完整 PASS 序列，当时正式结论为 `REPRESENTATION_NO_GO`，在完成并通过
R2 结构修正前不得：

- 进入 T021 或正式 canary；
- 读取 105 条冻结 blind test；
- 通过追加 epoch、seed 搜索、阈值放宽或只报 `7/8` 将结果解释为 GO；
- 把 `TRAINING_ORACLE_ONLY` 候选解释为真实推理候选生成能力。

## T017-R2-A 离散 cardinality decoder

- 每个 Junction 根据当前合法 RCSD Node/Road 候选数量 N 动态生成 `0..N` count 类，不设
  固定城市级上限；候选数量不同的 batch 使用 valid mask，`>N` 类不能被选择。
- count scorer 使用 Junction query、候选对象 mean/max pool 和 count 相对特征；不使用 raw
  ID，不把终态标签作为推理输入。
- cardinality loss 从 Softplus 标量 SmoothL1 回归改为合法 count 类上的交叉熵；推理直接
  argmax 离散 count，再由 pointer top-k 选对象，不再 round 连续值。
- REQUIRED coverage 排序 loss 保留；UNKNOWN/REVIEW/未裁决对象仍不进入二元正负标签。
- 无候选 Junction 的支持集只有 `{0}`；Gold count 超出候选数立即硬失败，不截断、不补造。

真实 8 条 readiness 工件：
`outputs/_work/p05_neural_road_generation/junction_graphset_v1_t017_r2_readiness_20260808/summary.json`

SHA256：`06E7B3C022070D9989DD106A4260D01843A4E92809B0EB544A796B192F384DEE`。

- `training_executed=false`、optimizer/checkpoint 未创建、canary 未启动、blind access `=0`。
- 8 条 surface/anchor count 支持类数均为 `7/18/8/31/80/14/19/39`，即各自合法 count
  范围为 `0..6/17/7/30/79/13/18/38`；全部 Gold 均可表达。
- surface/anchor count scorer 梯度 norm 分别为 `0.8927334547/0.9581764936`；全部 17 项
  loss finite。
- Step1 非法 RCSD 角色数 `0`，Surface 非法 Node/Road 角色数 `0`；阶段防火墙未回退。
- encoder 参数 `6,726,401`，总模型参数 `14,442,536`；CUDA dry-run 约 `5.10` 秒。

## T017-R2 正式结果

正式工件：
`outputs/_work/p05_neural_road_generation/junction_graphset_v1_t017_r2_overfit_20260808/`

- schema：`p05-junction-graphset-v1-t017-r2-overfit-v1`；task：
  `T017_R2_TRAINING_FOLD_STRONG_GOLD_OVERFIT`。
- step 1350、1375、1400 连续三次满足 total loss `<=0.02`、teacher exact `8/8`、
  free-run exact `8/8`；runner 在 step 1400 自动提前停止。
- 最终 total loss `0.0061901738`；surface cardinality `6/6`、surface set `6/6`、surface
  member `41/41`；anchor cardinality/set `5/5`、anchor member `178/178`。
- Step1、surface mode、anchor state、quality、完整方案、主锚定、Node 等价组、Road break
  presence/count、全部单/双 fraction 均为满分；8 条 per-sample exact 全部为 true。
- 训练用时约 `1427.34` 秒；模型参数 `14,442,536`、encoder 参数 `6,726,401`。
- blind access `=0`、`canary_executed=false`、`next_gate_authorized=false`。
- sample IDs、selected-row SHA256 和 source-manifest SHA256 与 R2 readiness 完全一致。
- checkpoint schema 与 R2 一致，`passed=true`、`converged_step=1400`。

工件 SHA256：

- `summary.json`：`E677083EE97970A2DE2CB6A5C88D6F65D81887C64A122F9C201FDCC969ACB0FE`；
- `history.json`：`0038813A14DE52BFB1C44B697908ACFE984485D0D5578795FF9F34DFC3AC9ED5`；
- `checkpoint.pt`：`4509C13B5E5D50C93B850B4EA396D0E2092802F46EE96A06787000DA33341F2C`。

## PASS 的严格含义

T017-R2 只证明当前 encoder、pointer/set、离散 cardinality、锚定、等价组、多打断和完整
方案 heads 能在固定 8 条强 Gold、绑定的 `TRAINING_ORACLE_ONLY` 候选上共同过拟合。它不
证明跨 Case 泛化、真实推理候选生成、全量自动接受安全性或城市级性能，也不授权读取 blind
test。下一步可进入 T021 的设计/训练阶段，但必须另行授权，并继续使用 Case-disjoint split、
强/T10 权重和 task mask，不得把 R2 checkpoint 当正式模型发布。

## 未改变边界

- T07 Step1 仍为 DriveZone-only；旧 T03/T04/T05 终态不进入推理输入。
- 未修改 T01–T12、正式 CLI、正式入口、T10 编排或城市 GIS 写出链。
- 业务输出仍以完整 JunctionResult 为目标；本结果只回答训练折内表示可学习性。
- overflow break 仍只能 ABSTAIN/fallback，不允许截断或静默修图。

## 回归验证

- 离散 decoder 定向 model/surface/object-decoder/overfit 测试：`26 passed`。
- P05 实际测试目录全量回归：`963 passed, 1 warning`；warning 为既有 Transformer
  `norm_first` nested-tensor 提示，不是测试失败。
- Python `compileall`、`git diff --check` 通过。
- P05 正式源码与实际测试目录共 `546` 个 Python 文件，`>=61440 bytes=7`、
  `>=100000 bytes=0`。
