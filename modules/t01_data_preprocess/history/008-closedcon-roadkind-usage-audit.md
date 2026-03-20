# 008 - closed_con / road_kind Usage Audit

## 背景
- 本轮将当前模块场景的 node 输入口径统一修正为 `closed_con in {2,3}`。
- 本轮将当前双向构段场景的 road 工作图统一修正为 `road_kind != 1`。
- 目标是消除旧 `{1,2}` 口径和“封闭式道路可参与”的残留业务依赖。

## closed_con 使用审计

| 文件 | 函数 / 位置 | 当前字段 | 本轮结果 | 说明 |
| --- | --- | --- | --- | --- |
| `configs/t01_data_preprocess/step1_pair_s1.json` | official Step1 S1 配置 | `closed_con_in` | 已改 | 官方配置统一为 `[2,3]` |
| `configs/t01_data_preprocess/step1_pair_s2.json` | official Step1 S2 配置 | `closed_con_in` | 已改 | 官方配置统一为 `[2,3]` |
| `src/rcsd_topo_poc/modules/t01_data_preprocess/step1_pair_poc.py` | `_evaluate_rule(...)` | `node.closed_con` | 已改 | 业务匹配继续读 `closed_con`，但 official rule source 已统一到 `{2,3}` |
| `src/rcsd_topo_poc/modules/t01_data_preprocess/step4_residual_graph.py` | `_build_step4_inputs(...)` | `_current_closed_con(...)` | 已改 | 正式通过 `is_active_closed_con(...)` 判定，即 `{2,3}` |
| `src/rcsd_topo_poc/modules/t01_data_preprocess/step5_staged_residual_graph.py` | `_build_phase_inputs(...)` | `_current_closed_con(...)` | 已改 | Step5A/5B/5C 统一通过 `is_active_closed_con(...)` 判定，即 `{2,3}` |
| `src/rcsd_topo_poc/modules/t01_data_preprocess/step4_residual_graph.py` | `_current_closed_con(...)` | `closed_con` | 保留 | 仅负责读取 working node 当前值，不承载值域规则 |
| `src/rcsd_topo_poc/modules/t01_data_preprocess/step5_staged_residual_graph.py` | 复用 `_current_closed_con(...)` | `closed_con` | 保留 | 同上，值域规则在 phase input builder 中执行 |
| `tests/modules/t01_data_preprocess/*` | 单元测试自定义策略 | `closed_con_in` | 部分保留 | 少数测试仍用 `[2]` 或 `0` 作为窄化夹具，只用于局部验证，不代表 official scene |

## road_kind 使用审计

| 文件 | 函数 / 位置 | 当前字段 | 本轮结果 | 说明 |
| --- | --- | --- | --- | --- |
| `src/rcsd_topo_poc/modules/t01_data_preprocess/working_layers.py` | `is_allowed_road_kind(...)` | `road_kind` | 已集中 | 当前统一口径：`road_kind != 1` |
| `src/rcsd_topo_poc/modules/t01_data_preprocess/step1_pair_poc.py` | `_build_graph(...)` | `road.road_kind` | 已改 | Step1 working graph 构建时即排除 `road_kind=1` |
| `src/rcsd_topo_poc/modules/t01_data_preprocess/step2_segment_poc.py` | `_build_semantic_endpoints(...)` | `road.road_kind` | 已改 | Step2 候选 channel / trunk / segment 收敛所用语义端点统一排除 `road_kind=1`，避免后吸回 |
| `src/rcsd_topo_poc/modules/t01_data_preprocess/step4_residual_graph.py` | `_build_step4_inputs(...)` | `road.road_kind` | 已改 | Step4 residual graph 工作图剔除 `road_kind=1` |
| `src/rcsd_topo_poc/modules/t01_data_preprocess/step5_staged_residual_graph.py` | Step5A active road set | `road.road_kind` | 已改 | Step5A 工作图剔除 `road_kind=1`，Step5B/5C 继承该 active set |
| `src/rcsd_topo_poc/modules/t01_data_preprocess/s2_baseline_refresh.py` | `_load_roads(...)` | `road_kind` | 保留 | 仅做字段读取与透传，供 downstream filters 使用，不在 refresh 阶段单独筛除 |
| `tests/modules/t01_data_preprocess/*` | 单元测试夹具 | `road_kind` | 保留 | 仅用于构造封闭道路测试数据 |

## 结论
- 生产业务路径中，`closed_con` 的 official scene 已统一到 `{2,3}`。
- 生产业务路径中，`road_kind = 1` 已从当前双向构段工作图、候选搜索、trunk / segment 收敛与 residual graph 轮次中统一排除。
- 剩余 raw `closed_con / road_kind` 读取点仅用于：
  - working field 读取
  - 审计输出
  - 测试夹具
