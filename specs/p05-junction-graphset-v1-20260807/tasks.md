# 任务：P05 Junction GraphSet v1

## Phase 0：启动与阻断审计

- [ ] T001 [Architecture] 冻结 `spec.md`、`data-model.md` 与
  `contracts/junction-result-contract.md` 的字段/阶段可见性哈希。
- [ ] T002 [Development] 对拟修改和新增的全部 `.py` 文件执行写入前字节数检查；禁止
  向当前 >=100KB 文件写入，历史 60KiB 观察线文件保持只读。
- [ ] T003 [QA] 逐维审计既有 64D/12D 特征，输出
  `raw / derived_geometry / candidate_metadata / forbidden` 分类与 Step1 可见性；未审计
  维度默认关闭。
- [ ] T004 [Testing] 建立 feature/label/test 三重隔离测试和冻结 105 条 blind test
  不可读门禁。

**Checkpoint**：T001–T004 全部通过才允许实现网络链路。

## Phase 1：US1 城市 store 与完整 free-run 骨架

- [ ] T005 [Development] [US1] 新建独立 `junction_graphset_v1_*` 城市对象仓模块，完成
  单次 GIS 读取、CRS 校验、对象 ID 索引、动态依赖切片和 manifest/hash。
- [ ] T006 [Testing] [US1] 覆盖同一城市只读一次、空间窗口不截断依赖、对象引用不复制、
  Case 顺序确定性和不同 CRS 输入阻断。
- [ ] T007 [Development] [US1] 建立完整 `JunctionResultPrediction` schema、空/变长 batch、
  candidate binding 和随机初始化 free-run。
- [ ] T008 [Testing] [US1] 对全部开发身份验证输出为合法结果或 ABSTAIN，非法/越界对象
  和空集合崩溃为 0。

## Phase 2：US2 Stage 防火墙与 surface 分支

- [ ] T009 [Architecture] [US2] 实现物理独立 Step1 DriveZone-only view 与 Step2
  RCSDIntersection view；共享参数不能通过全证据 token 泄漏。
- [ ] T010 [Testing] [US2] 对 tensor、attention mask、缓存键和梯度路径做 Step1 RCSD
  通道物理缺席测试。
- [ ] T011 [Development] [US2] 实现 existing/virtual/no-valid/ambiguous surface heads 与
  REQUIRED/FORBIDDEN/UNKNOWN member loss。
- [ ] T012 [QA] [US2] 在 1,685 条范围重算约束 ledger：5 条 Review、6 条 reference-only
  UNKNOWN、1,528 条 REQUIRED 可达必须与冻结审计一致。

## Phase 3：US3 锚定与完整结构方案

- [ ] T013 [Development] [US3] 实现角色分离 Graph/Set encoder、对象内 pooling、RCSD
  拓扑消息与 SWSD cross-attention，参数量目标 5–8M。
- [ ] T014 [Development] [US3] 实现 state/member/main-anchor/node-equivalence/break 多任务
  heads；UNKNOWN/missing 字段为零 loss，多解使用 acceptable-set loss。
- [ ] T015 [Development] [US3] 实现候选约束 structured decoder；锚定状态先确定，后续
  分数不能改写失败/歧义或扩充候选。
- [ ] T016 [Testing] [US3] 覆盖对象顺序等变、变长集合、唯一主锚定、Road 打断顺序、
  多解、mask、梯度隔离及候选越界阻断。
- [ ] T017 [Testing] [US3] 用训练折内冻结小批强 Gold 执行表示 overfit 门；失败则回到
  表征/合同，不启动正式 canary。

## Phase 4：US4 materializer 与安全链

- [ ] T018 [Development] [US4] 实现只执行已选方案的 surface/break/Node/topology
  materializer，不得另选业务对象。
- [ ] T019 [Testing] [US4] 覆盖 CRS、几何可解释、Node/Road 连通、打断一致、生成 ID
  忽略、silent fix=0 和路口作用域 fallback。
- [ ] T020 [QA] [US4] 建立危险/未知自动接受、异常 recall、自动/fallback exact 和逐 Case
  最差表现 ledger；任一危险项自动关闭相应发布范围。

## Phase 5：训练与 free-run 收口

- [ ] T021 [Development] 完成 P1 teacher forcing，使用强 1.0、T10 0.7、task mask、
  acceptable-set loss；来源不得进网络输入。
- [ ] T022 [Development] 完成预注册 scheduled sampling，报告 teacher/free 差距和每个
  断联阶段；不做局部 threshold/head 搜索。
- [ ] T023 [QA] 使用固定 Case-disjoint train/validation，核验输入 fingerprint、语义
  Junction 和多版本 Case 零跨 split。
- [ ] T024 [Testing] 运行全 P05/T07 回归、模型合同测试、静态泄漏扫描和确定性双跑。
- [ ] T025 [Architecture] 若连续三个预注册 seed 同现结构性失败，停止训练并形成架构
  NO_GO 审计，不进入 P4。

## Phase 6：US5 同输入输出比较与冻结测试

- [ ] T026 [Product] [US5] 用业务语言生成规则/网络 paired 报告：完整路口 exact、自动
  覆盖、安全、fallback 后 exact、最差 Case 和人工可审计示例。
- [ ] T027 [QA] [US5] 使用同一完整 `JunctionResult` evaluator 评估 strong/T10、各模块
  来源、状态、对象 cardinality 和虚拟面三态约束。
- [ ] T028 [QA] [US5] 对规则链与网络记录相同输入输出环境的单次读取、阶段耗时、峰值
  内存和总耗时；网络总耗时门为规则链 1.5 倍以内。
- [ ] T029 [Product] 全部研究 GO 门通过后冻结结构、loss、seed、阈值和 materializer；
  未通过则保持 NO_GO 并禁止读取 blind test。
- [ ] T030 [QA] 只在 T029 GO 后解封剩余 105 条强 blind test，一次性运行并输出正式
  结论；不得回到测试结果调参。

## Phase 7：交付治理

- [ ] T031 [Development] 若实际新增正式入口，先停止并取得授权，再同步 P05
  `INTERFACE_CONTRACT.md` 与 `entrypoint-registry.md`；否则保持 callable-only。
- [ ] T032 [Architecture] 同步实际实现边界、文件体量与技术债；任何应改变的
  `code-size-audit.md` 表必须同轮更新。
- [ ] T033 [Testing] 执行 `git diff --check`、全目标测试、SpecKit prerequisite 和工作树
  清洁审计。
- [ ] T034 [QA] 在 `validation-summary.md` 区分已修改、已验证、待确认、研究 GO/NO_GO
  与不接生产边界。

## 依赖顺序

`T001–T004 -> T005–T012 -> T013–T017 -> T018–T020 -> T021–T025 ->
T026–T030 -> T031–T034`。测试和 QA 与对应开发任务同阶段推进；不得因局部 head 指标
提前跳过完整 free-run 或安全门。
