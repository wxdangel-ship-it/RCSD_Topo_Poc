# P05 方案 A 预研事实

## 1. 已确认业务事实

- 方案 A 冻结 T01 Segment 集合和 Junction 关系。
- PhysicalMovement 存在性冻结，模型只选择 Road/Node carrier。
- 普通提右是 `ADVANCE_RIGHT Segment`，不是 `SegmentConnector`。
- Junction 冲突回退关联全部 Segment；Segment 冲突只回退该 Segment。
- Movement carrier 独占且不影响 JunctionUnit 时可单 Movement fallback，否则升级 Junction。
- fallback 是否成功取决于业务正确性，不取决于是否发生 fallback。

## 2. 真实数据预审计

冻结 51 Case 当前可见：

- T01 Segment：8,863；
- 普通 Segment：8,389；
- `ADVANCE_RIGHT`：474；
- 旧 JSG `SegmentConnector`：69；
- 旧 JSG PhysicalMovement：24,779；
- 当前策略状态：`replaced=3,083`、`retained_swsd=5,431`、`replaced+retained_swsd=30`、`failed=319`；
- 474 个 ADVANCE_RIGHT 均有非空独立 SWSD Road 引用；
- 其中 2 个 ADVANCE_RIGHT 的 SWSD Road 存在端点引用缺失，不能作为合法 fallback 静默发布。
- 474 个 ADVANCE_RIGHT 的 T01 `pair_nodes/junc_nodes` 当前均为空；按独立 Road 有向端点与普通 Segment owner 做唯一性预审计，434 个 source/target access 可唯一追溯，40 个存在 owner 缺失或多解，必须显式失败并形成 clue，不能沿用旧 Connector 数量作为覆盖指标。

上述数字是实施前预审计，正式结论必须由两轮不可变 run 重新计算并写入 validation summary。

## 3. 历史结论重解释

- 旧 Connector accuracy 与 Review/Unknown 指标不再是当前业务指标；它们反映旧对象定义下的历史 scorer 表现。
- 旧 PTO-A 51/51 `OPTIMAL` 只保留历史 formulation 证据；方案 A 不允许 PTO-A 选择或改变业务骨架。
- 旧 RoadGraph/compiler 100% 只证明 label-only 历史 carrier 可编译，不证明方案 A 的 carrier scorer 已成功。
- P3 的 object-conditioned scoring 增益仍可作为模型结构研究证据，但训练目标必须在新 carrier-only 标签合同下重建。
