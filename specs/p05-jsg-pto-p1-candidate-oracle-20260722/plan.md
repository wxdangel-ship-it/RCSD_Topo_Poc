# P05-JSG-PTO-P1 实施计划

## 1. 设计原则

1. candidate-first：候选冻结后 truth 才进入。
2. semantic-first：PTO-A 只处理业务结构，PTO-B 处理 carrier/RoadGraph。
3. Review 是合法决策，不以强制发布降低 Review 数量。
4. 复用已有 truth-free candidate 与 materializer，不复制 T03-T06 业务规则。
5. 两个候选 run 和两个 solve run 均不可变。

## 2. 实施阶段

### Phase A：源事实与合同

- 同步 P05 当前状态与历史路线边界。
- 建立本 SpecKit、数据模型、输出合同和任务清单。
- 明确 candidate/Oracle 配置的路径白名单和拒绝项。

### Phase B：EvidenceGraph 与候选

- 验证上游 PTO candidate manifest/hash/零泄漏。
- 从 T01 和已登记 proposal lineage 构建 Case-local EvidenceGraph。
- 生成规范化 PTO-A 对象候选和 PTO-B carrier/edit 引用。
- 输出 candidate/group/lineage/case index，冻结 manifest。

### Phase C：Oracle 与 compiler

- 候选冻结后读取 P0 canonical truth，计算对象级 Oracle cost。
- 执行 PTO-A group/dependency solve。
- 复用 RoadGraph Oracle infrastructure 执行 PTO-B，并验证 Unit carrier/access。
- 编译选中 JSG/R2 IR，使用 P0/M0 evaluator 验证。

### Phase D：测试和真实数据

- 单元、破坏、泄漏、infeasible 和确定性测试。
- 完整 P05 回归。
- 运行 candidate A/B、solve A/B，形成正式 go/no-go。

## 3. 计划代码边界

- `jsg_p1_models.py`：candidate/config/certificate contract。
- `jsg_p1_candidates.py`：EvidenceGraph 与 truth-free candidate builder。
- `jsg_p1_solver.py`：PTO-A/PTO-B Oracle 和 compiler adapter。
- `jsg_p1.py`：不可变 candidate/solve run 编排。

不新增独立执行入口；只暴露模块 callable。

## 4. GIS 与性能验证

- CRS：候选 evidence CRS 必须一致，不隐式变换。
- 拓扑：依赖、access、carrier、Road endpoint 和方向显式 hard gate。
- 几何：RoadGraph 使用 M0 evaluator；JSG carrier 只引用实际选中 Road。
- 审计：输入、参数、输出、commit/hash、环境和状态全部可定位。
- 性能：区分历史 replay、候选构建、PTO-A、PTO-B、compiler 的 wall/CPU/RSS。

## 5. 风险控制

- exact T01 identity candidate 不等于最终决定；必须保留状态/方向/类型 alternatives 和选择证书。
- P0 truth 只能在 solve config 出现，candidate config/API 不接受该路径。
- RoadGraph PTO candidate 由规则 replay 生成，仍是 proposal，不得称为模型输出。
- 如果 P1 依赖历史 replay 且在线性能不合格，只允许离线语义 GO。
