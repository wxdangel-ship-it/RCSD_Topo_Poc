# Implementation Plan

## 技术上下文

- 语言：Python；
- 训练：PyTorch，复用 P05 现有 OOF、artifact、GIS 与安全 gate 基础设施；
- 数据：`E:\TestData\POC_Data`，以及用户明确授权的
  `E:\TestData\POC_QA\T03_Error`；
- 模型：10M–20M 分层 Graph/Set Transformer；
- 部署：无，离线研究；
- 工作分支：`codex/p05-target-a-joint-roadgraph`。

## 架构

### 数据层

新增 `target_a_*` 隔离实现，不改写历史 P13/M2R/R2 数据合同：

- inventory adapter：将已有 P05 标注与人工裁决归一到 Target A scope；
- inference cache：只保存 T01/SWSD、原始 DriveZone/RCSDIntersection、原始 RCSD
  Road/Node 与 truth-free candidates；
- label store：保存 T07/T03/T04/T05 路口中间状态、surface/relation/junctionization、
  anchor acceptable/preferred，以及后续 ordinary/AR/clue 标签；
- leakage audit：字段、路径和 candidate lineage 三层审计。
- junction Gold inventory：扫描五个 1.0 目录，校验 manifest/CRS/声明 checksum，
  按 Case ID 与原始输入 hash 去重；规则终态冲突进入 `LABEL_REVIEW`；
- frozen split：已按完整 Case/source group 分层冻结 700 个 group 为
  train/validation/test=`490/105/105`，对应输入版本=`497/105/106`；708 个输入版本
  不跨 split，8 个一致多版本 Case 按组内均分权重，16 个终态冲突 Case 隔离。
- T05 Gold continuation：399 个 accepted surface 全部形成唯一 relation；343 个完整
  SUCCESS、19 个正向 NO_RCSD_EVIDENCE、37 个只保留 action/safety 监督，完整拓扑
  Gold 明确 mask。T03/T04 适配只补正式状态字段，几何改写和 silent fix 均为 0。

### 模型层

- polyline geometry encoder；
- candidate Set Transformer；
- sparse heterogeneous graph blocks；
- T07 DriveZone-only evidence head 与 existing-surface anchor head；
- T03/T04 业务路由、surface 与 relation-evidence head；
- T05 unique relation、graph-consumable 与 junctionization head；
- 完整 anchor object-set head；
- ordinary complete-plan pointer/set head；
- conditional AdvanceRight head；
- clue/fallback scope head；
- constrained RoadGraph decoder 与显式有限 `FallbackDirective`。

### 训练层

1. T07 Step1/Step2 分层预训练，强制 Step1 不可见 RCSDIntersection；
2. 五个单点目录先执行正式规则重放并形成权重 1.0 的强 Gold；按用户
   2026-08-05 确认的方案 A，与权重 0.7 的 T10 弱监督通过字段 mask 共同训练
   raw-inference 共享 encoder；Case family 只用于训练审计和分层指标，不得成为
   推理输入，也不得给单点样本补造其缺失的城市前序状态；
3. T03/T04 业务路由、surface 与 relation-evidence 多任务训练；
4. T05 unique relation、graph-consumable、junctionization 与完整 anchor object-set
   条件化训练；
5. 联合阶段后执行强 Gold consolidation，再做路口 free-run、Case-group OOF 和
   独立零危险验收；
6. 只有路口阶段通过后，才启动 ordinary plan teacher forcing、OOF anchor
   conditions、structured decoder；
7. 普通 Segment 通过后再启动 AR，最后才允许全链联合训练。

## I/O 与城市规模

- 首次构建城市级 immutable feature/index cache；
- forward 只 gather 动态业务依赖子图；
- decoder 在当前动态业务依赖子图内联合约束 Road 所有权，但 fallback 只执行
  模型显式 Segment/Junction directive，禁止传递闭包；
- label store 不进入推理 cache；
- 每轮只写 checkpoint、metrics 和紧凑 decision ledger；
- 最终 RoadGraph 物化一次；
- 城市级 runtime 另做无标签 profile。

## 源事实与接口边界

- 更新 `docs/PROJECT_REQUIREMENTS.md` 和
  `modules/p05_neural_road_generation/SPEC.md`，说明 Target A 已成为正式研究目标；
- 保留全部历史 NO_GO 事实；
- 不修改 T01–T12 源码、契约、CLI 或入口；
- 不新增生产入口；研究执行使用 P05 内部模块调用/现有测试与训练约定。

## 验证

- unit：scope/weight、acceptable-set、no-valid-relation、anchor lock、ownership、
  internal connector tree、AR conditioning、Segment 单点 fallback、Junction
  直接关联 fallback 与 `J1—S1—J2—S2` 链式阻断；
- leakage：label field/path/candidate provenance；
- integration：两阶段 decoder、ledger、deterministic materializer dry-run；
- OOF：Case-group split、三 seed、完整策略 paired baseline；
- GIS：CRS、方向、Node/Road 引用、拓扑、几何容差；
- QA：输入/hash/config/checkpoint/ledger 可追溯，零 silent fix。
