# T06 Root5 Step3 Top20 替换口径修正计划

## 1. 技术边界

- 模块：`t06_segment_fusion_precheck`。
- 主要源事实：`modules/t06_segment_fusion_precheck/SPEC.md`、`INTERFACE_CONTRACT.md`、`architecture/02-data-and-domain-model.md`、`architecture/03-solution-strategy.md`、`architecture/05-quality-requirements.md`。
- 主要代码：Step2 buffer/RCSDSegment 抽取、replacement plan 发布、Step3 未替换归因。
- 禁止范围：T01/T05 主链、上游 relation 主表、repo CLI、scripts/tools 新入口。

## 2. 设计决策

### Decision 1: required junction 进入替换硬关系集合

`pair_nodes` 和 required `junc_nodes` 都必须 relation 正确、方向可解释。非 required junc 继续作为 detached / exempt audit / side blocker。

### Decision 2: reverse coverage 降级为人工审计风险

RCSD 不要求完全位于 SWSD Segment buffer 内。硬拒绝只保留 pair-to-pair 连续通路完全不经过 SWSD Segment buffer 的 bypass 场景；反向 buffer / coverage gap 写入 risk flag。

### Decision 3: 未落地归因以目标 Segment 消费事实为准

若 RCSDRoad 未出现在目标 Segment 最终 F-RCSD carrier 中，即使它被其它 Segment 消费，也必须对目标 Segment 输出未替换归因。

## 3. 实现策略

- 先同步 T06 源事实/契约，消除旧口径冲突。
- 在 Step2 中调整 required node 和 mapped semantic node 判断，使 required junction 被纳入硬关系语义，额外未锚定 RCSD 节点不构成硬拒绝。
- 将 reverse coverage / 不完全在 buffer 内的场景改为 risk flag；保留完全绕开 buffer 的 continuous pair-to-pair path hard reject。
- 在归因层保留候选但未被目标 Segment 消费的 RCSDRoad，避免最终 F-RCSD 存在但目标 Segment 漏归因。
- 对用户确认的 `1206914_1257213` 样例进行 Segment 级回归，随后执行 `1885118` 和 T10 6 case 回归。

## 4. 质量门

- CRS 与坐标变换：回归产物必须保留 visual/spatial QA 中的 CRS 检查结果。
- 拓扑一致性：Step3 topology connectivity audit 不得新增 hard fail；不允许 silent fix。
- 几何语义可解释性：每个新增通过或仍阻塞的 RCSDRoad 必须能解释 relation、方向、buffer 穿行和目标 Segment 消费状态。
- 审计可追溯性：输出路径、输入路径、run id、归因 CSV/GPKG、summary 均必须可定位。
- 性能可验证性：T10 6 case run 需保留 summary duration，不能出现超时或失败 case。

## 5. 验证顺序

1. 单元测试：T06 相关测试。
2. Segment 回归：优先 `1206914_1257213`，必要时扩展到用户指出的 Segment。
3. 基线回归：`1885118` 与上一轮基线对比。
4. T10 回归：6 case 全量跑到 `STOP_AFTER=t06_step3`，确认无业务回退。
