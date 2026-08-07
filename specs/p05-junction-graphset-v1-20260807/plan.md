# 实施计划：P05 Junction GraphSet v1

**分支**：`codex/p05-junction-graphset-v1-20260807`
**日期**：2026-08-07
**规格**：`specs/p05-junction-graphset-v1-20260807/spec.md`

## 摘要

在 P05 内新增一条与历史 Target A 实验隔离的 Junction GraphSet v1 研究链。先实现
城市级单次读取、阶段输入防火墙、完整输出合同和真实 free-run，再训练 5–8M 的角色
分离 Graph/Set encoder、分阶段多任务 heads 与候选约束 decoder。固定验证门禁后才
允许访问剩余 105 条冻结测试；本轮不触及 Segment/AdvanceRight/Movement。

## 技术上下文

- Python 3.10；PyTorch 2.9.1+cu128；GeoPandas/Shapely/Pyogrio；pytest。
- Windows 本地仓库，正式训练环境为 WSL `.venv`；GIS 标准计算 CRS 为 EPSG:3857，
  每个输入仍必须按实际元数据校验。
- 研究模块路径：`src/rcsd_topo_poc/modules/p05_neural_road_generation/`。
- 测试路径：`tests/modules/p05_neural_road_generation/`。
- 运行工件只写 ignored `outputs/_work/p05_neural_road_generation/`。
- 不新增正式入口；第一轮使用模块 callable 与一次性 validation runner。

## 架构分层

1. `CityEvidenceStore`：原始 GIS 单次解析、对象索引、mmap 分片和 hash/CRS 审计。
2. `StageFirewall`：Step1 DriveZone-only、Step2 RCSDIntersection、Anchor 全原始 RC
   证据的物理张量视图。
3. `RoleSeparatedGraphSetEncoder`：对象内几何 pooling、图消息和 SWSD query 对 RCSD
   对象 cross-attention。
4. `StagedHeads`：Step1、surface、quality/state、member、main-anchor、break heads。
5. `CandidateConstrainedDecoder`：对完整候选方案联合评分并输出唯一方案或 ABSTAIN。
6. `JunctionMaterializer`：只执行面/打断/Node/拓扑写出与通用合法性校验。
7. `CompleteJunctionEvaluator`：统一比较网络、规则基线、自动结果与 fallback 后结果。

## 训练阶段

### P0：IO 与真实 free-run 骨架

先完成 64D/12D 特征逐维审计、Stage1 防火墙、完整 output schema、candidate binding、
materializer dry-run 和城市级只读 store。随机初始化模型也必须对全部输入输出合法方案
或 ABSTAIN，不允许局部 head 绕过全链。

### P1：表示可学性与 teacher forcing

在训练折内冻结小批强 Gold overfit 集，证明完整 surface/member/main/break/topology
表示可学；随后以字段 task mask、1.0/0.7 权重和 acceptable-set loss 训练各阶段。
teacher-forced 指标仅用于定位表示问题。

### P2：scheduled sampling 与 free-run 收口

按预注册日程逐步用模型 surface/anchor 状态替换真值条件；每轮同时报告 teacher/free
差距、断联点、强/弱分层和最差 Case。不得通过 Case family 输入或旧终态回灌修复。

### P3：完整结构 decoder 与安全门

联合约束 Node/Road 成员、唯一主锚定、Road 打断顺序和最终拓扑；无合法高置信方案时
ABSTAIN。阈值只在验证集确定，不能改变候选或修复错误业务对象。

### P4：冻结比较

冻结结构、loss、seed 协议、阈值和 materializer 后，先执行 strong/T10 双验证和规则
paired comparison；所有研究门禁通过才解封 105 条盲测。盲测只运行一次。

## IO 与性能方案

- 城市对象以 ID 建索引，几何 token/拓扑边按城市持久化分片。
- batch 按总 token 数动态组批，不按固定 Case 数填充。
- 同一静态对象 embedding 可按模型 hash/特征合同缓存。
- 预测先写内存/列式账本，冲突求解后一次性写 GIS。
- profile 记录解析、切片、forward、decode、materialize、write 各阶段耗时与峰值内存。

## 宪章与仓库约束检查

- 变更位于独立工作树和 SpecKit，未在 main 直接开发：PASS。
- 项目/P05 源事实已在归档轮确认，本 spec 不改 T01–T12 正式接口：PASS。
- 产品、架构、研发、测试、QA 五视角在 tasks 中显式覆盖：PASS。
- 新源码写入前逐文件检查当前字节数；新文件必须小于 100KB：实施硬门。
- 若新增正式入口或改变接口，立即停止并重新取得授权：实施硬门。
- GIS 检查覆盖 CRS、拓扑、几何可解释、审计追溯和性能：PASS（任务已登记）。

## 结构决策

新职责按 store/firewall/encoder/heads/decoder/materializer/evaluator 拆分为小模块，不继续
向 81KB 的 `target_a_network.py`、79KB 的 `target_a_t05_anchor_dataset.py` 或其他历史
大文件追加。历史 `target_a_*` 仅作可复用资产与对照，不作为新链路的隐式入口。
