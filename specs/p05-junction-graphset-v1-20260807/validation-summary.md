# T017 表示 overfit 验收摘要

## 状态

`T017_REPRESENTATION_NO_GO_OBJECT_DISCRIMINATION`

T001–T020 已执行。T017 已获授权并完成；没有读取冻结测试，没有启动正式 canary，也没有
进入 T021。当前没有新增业务认知冲突，不需要补造业务裁决。失败属于网络对象表示问题，
必须先回到表征架构，不得以阈值、发布门或更多 epoch 掩盖。

## T017 固定范围

- 仅精确按 ID 读取训练折 8 条强 Gold，权重均为 1.0；blind access `=0`。
- 覆盖 `NO_RCSD_EVIDENCE`、`QUALITY_ISSUE`、source-Node 主锚定、单 Road 打断、
  多 Road 打断、同一 Road 双打断和 source Node + 生成打断 Node 混合等价关系。
- 每条绑定 1 个 Gold 完整方案与 2 个 hard decoy；候选目录标记为
  `TRAINING_ORACLE_ONLY`，只用于验证表示可学性，不代表真实推理候选生成。
- 模型 hidden dimension 384，encoder 参数 `6,574,720`，总参数 `11,033,372`；
  AdamW、学习率 0.002、最多 1,500 step、每 25 step 评价。
- PASS 要求连续 3 个评价点同时满足：total loss `<=0.02`、teacher 完整 exact `8/8`、
  free-run 完整 exact `8/8`。

## 训练前合同修正

- 主锚定和 Node 等价关系可显式引用原始 RCSD Node 或模型决定的 Road 打断 Node；同一
  Road 的多个打断点按 `break_rank` 独立表达。
- 虚拟面 RCSD 成员集合与锚定拓扑对象集合物理分开；前者以正式
  `REQUIRED/FORBIDDEN/UNKNOWN/REVIEW` constraint ledger 为准，后者以 normalized
  Junction topology 为准。
- 完整方案 scorer 分开编码 surface 成员、anchor 成员、主锚定、Road 打断和 Node
  等价组，避免“对象并集相同即表示相同”。
- 上述修正均在既有冻结合同范围内；`spec.md`、`data-model.md`、
  `contracts/junction-result-contract.md` 和合同 freeze hash 未修改。

## 正式结果

- 完成 step：`1,500 / 1,500`；收敛 step：无。
- 最终 total loss：`1.3367981911`。
- teacher-forced 完整 exact：`3 / 8`。
- free-run 完整 exact：`3 / 8`。
- 状态类：Step1 `8/8`、surface mode `8/8`、anchor state `8/8`、quality `8/8`。
- 完整 Oracle 候选选择：`8/8`；source-Node 主锚定辅助项 `1/1`；source-Node pair
  辅助项 `6/6`。
- 虚拟面成员：`34/41`；锚定成员：`158/178`。
- Road 打断存在性：`8/12`；5 个受监督单打断位置在 0.01 容差内为 `0/5`。
- T017 运行工件：
  `outputs/_work/p05_neural_road_generation/junction_graphset_v1_t017_overfit_20260808/`。

## 失败解释

失败样本中，多条不同 Road 获得几乎相同的 member 概率、break presence 概率和 fraction。
这说明当前“对象内均值 pooling + 共享 Graph/Set encoder + 简单对象 head”不能稳定保留同一
角色对象的局部身份和相对几何差异。状态判断和 Oracle 候选选择成功，不能替代对象集合与
打断位置的直接生成能力，因此本门禁必须判 NO-GO。

该结论不是“神经网络整体不可用”，也不是数据量不足结论；8 条训练样本本应可被 11M 参数
模型记忆。当前首先缺失的是可辨识的对象级表示/解码路径，而不是更多 Case、概率校准或发布
阈值。

## 隔离与安全

- 105 条冻结 blind test 未读取，schema quarantine 未扩散。
- T10 弱标签、validation、canary、发布阈值均未进入本轮。
- 旧 T03/T04/T05 策略终态未进入网络输入；Step1 仍为 SWSD + DriveZone-only。
- 未修改 T01–T12、正式 CLI 或正式执行入口。

## 已验证

- `test_junction_graphset_v1_*.py`：`70 passed`。
- 覆盖生成 Road-break Node、混合 Node 等价、独立 surface/anchor 成员、主锚定与等价组
  hard decoy 可辨识、精确 JSONL 选行不解析未请求行、cached stage view 与常规 forward
  等价，以及既有 CRS、拓扑、fallback、安全计分回归。
- Python `compileall` 通过；`git diff --check` 通过。
- 测试/训练环境：WSL，Python 3.10.12，torch 2.9.1+cu128；T017 使用 CUDA。
- 所有新增或修改源码均低于 100 KB。

## 下一门禁

不得启动 T021。下一步应先形成对象级表示修正方案，至少解决：

1. 保留每条 RCSD Road/Node 相对 SWSD 语义路口和 DriveZone 的对象级几何关系，避免对象内
   均值后塌缩；
2. membership 使用可审计的 pointer/set decoder，打断位置使用 Road 条件化的多点 decoder；
3. 用只改变一个对象、主锚定、等价组或打断位置的 hard decoy 先做静态可辨识性测试；
4. 获得新的训练授权后，重新运行相同 T017 门；通过前仍不得 canary。

## 当前不代表

- 不代表模型已经收敛或可以进入正式训练。
- 不代表 Oracle 候选选择 `8/8` 等于真实 free-run JunctionResult 可生成。
- 不代表允许恢复旧策略推理输入，或放宽锚定/成员/拓扑正确性。
- 不代表 Segment、AdvanceRight、Movement 或 T07 Step2 已进入本阶段。
