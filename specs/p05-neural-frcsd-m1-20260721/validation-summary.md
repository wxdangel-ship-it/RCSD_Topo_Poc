# P05 M1 验证总结与 M2 判定

## 结论

M1 已完成，结论为 **M2 no-go**。图模型已经学到 Road 操作与 direction/source 信号，但尚不能直接生成满足 T06 F-RCSD 质量门槛的完整 RoadGraph。固定 test 只访问一次，不再依据 test 调参或重跑。

## 冻结输入与数据门禁

- M0 冻结 RoadGraph truth：`51` Case；train/validation/test 为 `33/13/5`。
- 用户确认排除 `T10-Error / 1213556_1263661` 的候选、标签、归一化和模型输入均为 `0`。
- 候选 `37,495 -> 36,889`；实体及一跳 guard 移除 `606`；train/validation/test Road ID 交集全部为 `0`。
- 操作覆盖 `23,210 / 23,224 = 99.9397%`；14 个 uncovered truth 保留在最终评价分母。
- `DROP/KEEP/SPLIT_1/SPLIT_2/SPLIT_3` 为 `14,854/21,175/28/830/2`。
- dataset manifest：`d51a99a999c3f70574a2ab41e91c6a38f5de57c2aa03aa98a81c14d5306b2304`。

## 模型与开发证据

- 图模型：6 层稀疏 gated GraphSAGE 风格 block，hidden `384`，`10,722,926` 参数；无 `torch_geometric`。
- 固定 validation operation macro-F1：MLP `0.2824`，图模型 `0.4751`。
- 相同 seed 完整重放两次均为 `0.47509097437900666`，差值 `0.0`。
- 4-fold 开发 CV macro-F1：`0.4727/0.4590/0.4122/0.5333`；均值 `0.4693`，总体标准差 `0.0432`，最差 `0.4122`。
- 标准 T10 shadow holdout macro-F1 `0.3144`，表明分布泛化明显弱于固定 validation。
- 消融：无图 MLP `0.2824`；移除语义 Node feature `0.4365`；移除 `0.3` 低可信监督 `0.4644`。图关系、语义 Node 和低可信上下文都有正贡献，但均不足以解决完整 RoadGraph 质量问题。
- 冻结物化协议 validation Road F1 `0.7453`，keep-all `0.7098`，提升 `3.55pp`；最差 Case `0.0690`。同一 endpoint ID 对应不同原始 Road 端点坐标的 11 个冲突保留为失败，未吸附或合并。

## 唯一一次固定 test

固定 test run：`outputs/_work/p05_neural_road_generation/p05_m1_fixed_test_final_20260721_01`。5 个样本均为 Segment Case，没有标准 T10 Case，置信区间较宽。

| 指标 | 图模型 | keep-all | 门槛 | 判定 |
|---|---:|---:|---:|---|
| Road object F1 | `0.6436` | `0.6521` | `>=0.85` | FAIL |
| 相对 keep-all | `-0.84pp` | - | `>=+5pp` | FAIL |
| 最差 Case Road F1 | `0.4949` | `0.5600` | `>=0.70` | FAIL |
| direction accuracy | `0.9991` | `1.0000` | `>=0.95` | PASS |
| source accuracy | `0.9972` | `0.9986` | `>=0.95` | PASS |
| 物化失败 | `0` | `0` | `0` | PASS |
| CRS 冲突 | `0` | `0` | `0` | PASS |
| 有向拓扑 hard-failure Case | `5/5` | `5/5` | `0` | FAIL |

模型 Road F1 的 Case bootstrap 95% 区间为 `[0.5182, 0.7327]`。最差 Case 为 `t10_error:1206914_1257213:fb672dba2ccc`，Road F1 `0.4949`。

## GIS 五项证据

1. **CRS**：validation `13/13`、test `5/5` candidate/truth CRS compatible；不执行隐式重投影。
2. **拓扑**：test 重复 Road/Node ID、缺失 endpoint 引用均为 `0`，但 `5/5` 有向拓扑与 truth 不同，因此不通过。
3. **几何语义**：KEEP 保留输入几何；SPLIT 只解码模型 child geometry；非有限、空或零长度直接失败。缺失输入 Node 只允许按保留 Road 精确首末点和原 ID 物化；坐标冲突不修复。
4. **审计追溯**：dataset/training/evaluation manifest、全部正式 output、51 个 graph NPZ 及逐 Case Road/Node GPKG hash 复核 mismatch 为 `0`；`silent_fix=false`。
5. **性能**：dataset `19.24s`；图训练 `8.02s`、峰值 RSS `2.13GB`、VRAM `4.70GB`；固定 test 联合评价 `10.60s`、峰值 RSS `1.36GB`、VRAM `75.0MB`。

## SC-001~SC-010

| 标准 | 结果 | 说明 |
|---|---|---|
| SC-001 | PASS | 51 Case，approved exclusion 进入量 0。 |
| SC-002 | PASS | artifact hash 完整；T06 feature 数 0。 |
| SC-003 | PASS | post-guard cross-split overlap 全为 0。 |
| SC-004 | PASS | operation coverage 99.9397%。 |
| SC-005 | FAIL | test F1 0.6436，且低于 keep-all 0.84pp。 |
| SC-006 | PASS | direction/source 均超过 0.99。 |
| SC-007 | FAIL | CRS/引用/重复 ID 通过，但有向拓扑 5/5 失败。 |
| SC-008 | FAIL | 最差 Case 0.4949；2/5 Case 低于 0.70。 |
| SC-009 | PASS | CV、固定 test、标准 T10 shadow 分层报告。 |
| SC-010 | PASS | 相同 seed 重放 macro-F1 差值 0.0。 |

## 后续条件

当前不启动 M2。若重新开启，应先补充标准 T10 Case 与 SPLIT 稀有类真值，重新设计保证端点/有向拓扑闭合的结构化解码，并以新的不可变 dataset/model/test 协议建立下一轮；不得复用本轮固定 test 做调参集。
