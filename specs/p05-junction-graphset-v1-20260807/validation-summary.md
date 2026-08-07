# 训练前验收摘要

## 状态

`PRETRAINING_IMPLEMENTATION_READY_AWAITING_T017_AUTHORIZATION`

T001–T016、T018–T020 已完成；T017 小批强 Gold 表示 overfit 门尚未执行，因为它已属于
训练动作。T021 及后续 teacher forcing、scheduled sampling、canary 和冻结测试均未启动。
当前没有新增业务认知冲突，也没有需要用户补充裁决的数据字段。

## 已实现

- 城市级证据只读 store、动态业务依赖切片、packed 变长 batch 和 candidate binding。
- Step1 独立的 SWSD + DriveZone-only 张量视图；RCSDIntersection 只从 Surface 阶段进入，
  RCSD Node/Road 只从 Anchor 阶段进入。共享 encoder 不共享被禁止的输入 token。
- existing/virtual/no-valid/ambiguous/abstain surface 分支和虚拟面
  `REQUIRED / FORBIDDEN / UNKNOWN / REVIEW` 约束 loss。
- 角色分离 Graph/Set encoder：21D 几何 token、对象内 pooling、8D 拓扑消息、无位置编码
  Set Transformer、SWSD query 对对象集合 cross-attention。encoder 参数量 `6,574,720`，
  位于预注册的 5–8M 范围；含多任务 heads 和完整方案 scorer 的总参数量 `10,294,556`。
- Step1、surface、anchor state、quality、virtual-surface member、anchor member、唯一主锚定、
  Node equivalence、Road break presence/fraction 多任务 heads。强 Gold 权重 1.0、T10 弱标签
  权重 0.7、无监督字段权重 0；多解使用 acceptable-set loss。训练时可显式传入 Step1 与
  surface Gold 做 teacher forcing；free-run 则采用模型的硬选择，顺序固定为
  `Step1 -> surface -> anchor`，后层不能反向改变前层条件。
- 候选约束 decoder：先冻结 Step1、surface、anchor 和 quality 业务结论；后续 plan 分数只能
  在完全匹配的已绑定候选中选择，不能改写锚定、补候选或把歧义/失败改成成功。完整方案
  scorer 直接从共享表示对绑定方案给出可训练 logits，并用变长集合编码一个 Road 上的多个
  有序打断位置，不再依赖外部注入 `plan_confidences`。
- 确定性 materializer：只执行模型已选 surface、Road 打断、Node 和拓扑方案；CRS、几何、
  面成员、连通性或拓扑签名失败时只做 Junction fallback；`silent_fix=0`，不另选业务对象。
- 完整结果 evaluator：严格比较 surface/对象集合/主锚定/Node 等价/Road 打断/拓扑，打断
  位置支持正式容差，多正确方案使用 acceptable set；生成 ID、顺序和无业务影响折线点不
  作为错误。自动 exact、fallback 后 exact、危险自动接受、未知自动接受、异常 recall 和
  逐 Case 最差表现分开统计；任一危险或未知自动接受都会关闭对应发布范围。

## 数据与隔离门

- Phase 0 合同冻结文件：`contracts/contract-freeze.json`；冻结的 `spec.md`、`data-model.md`
  和 `contracts/junction-result-contract.md` 本轮未修改。
- 特征来源仍为 raw 22、derived geometry 84、candidate metadata 12、forbidden 86；旧策略
  终态、标签来源和 evaluator 结果不进入推理 batch。
- Step1 可见索引仍固定为 `0,1,2,3,13,14,15,21,22,23,24`；唯一 RC 证据为
  DriveZone。
- blind-test seal 保持：测试总数 106、schema discovery quarantine 1、剩余 blind 105；
  T029 前读取接口持续阻断，本轮 blind access 为 0。
- 1,685 条虚拟面约束 ledger 已重算并与冻结审计一致：supervised 1,680、Review 5、
  REQUIRED 可达 `1,528 / 1,528`、required missing 0、reference-only UNKNOWN 对象 6、
  visible FORBIDDEN 对象 26,858；没有训练。
- 4,288 条 development-only 身份的安全骨架审计仍为合法 4,288、ABSTAIN 4,288、非法
  0；该结果只证明合同和安全锁，不代表模型精度。

## 已验证

- `test_junction_graphset_v1_*.py`：`64 passed`。
- 覆盖 Step1 物理通道缺席、梯度隔离、stage cache、对象顺序等变、空/变长集合、多解、
  task mask、独立 surface/anchor member Gold、唯一主锚定、Road 打断、候选越界阻断、
  CRS、几何与拓扑拒绝、确定性 ID、Junction fallback 和完整安全计分。
- Python `compileall` 通过。
- 测试环境：WSL，Python 3.10.12，torch 2.9.1+cu128，Shapely 2.1.2。
- 所有本轮新增源码均低于 100 KB；未触及历史超观察线文件、正式 CLI、正式入口或
  T01–T12 实现。

## GIS / 拓扑边界

当前用合成 GIS fixture 验证 EPSG:3857、严格 CRS 一致、几何类型、面成员、Node/Road
连通、Road 打断、拓扑签名和 `silent_fix=0`。真实城市百万对象峰值内存、mmap 分片、
冷/热启动以及一次性写出性能仍属于 T028，不是 T017 小批 overfit 的前置业务裁决。

## 下一执行门

下一步只有 T017：在固定训练折内选择一小批强 Gold，验证当前表示与完整 heads 能否过拟合
到正确 JunctionResult。它不会读取 105 条冻结测试，不会启动正式 canary，也不会调发布
阈值；若失败，立即回到表示/合同检查，不进入 T021。

需要用户确认：是否授权执行 T017 小批强 Gold 表示 overfit 门。

## 当前不代表

- 不代表模型已经训练、收敛或达到 accuracy/覆盖率目标。
- 不代表当前 62 个合同测试可以替代真实 Case 的端到端评价。
- 不代表允许恢复旧 T03/T04/T05 策略作为推理输入。
- 不代表 Segment、AdvanceRight、Movement 或 T07 Step2 已进入本阶段。
- 不代表已接入正式主链、生产发布或读取冻结测试。
