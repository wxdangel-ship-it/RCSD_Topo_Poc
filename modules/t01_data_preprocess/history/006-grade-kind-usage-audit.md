# 006 - Grade/Kind Usage Audit

## 1. 审计目标
- 检查 `src/rcsd_topo_poc/modules/t01_data_preprocess` 与对应测试中，raw `grade / kind` 的读取点
- 区分：
  - 已切换为 `grade_2 / kind_2` 的业务逻辑
  - 仍保留但仅用于初始化 / 审计 / 展示 / 测试夹具的位置

## 2. 审计结论
- 本轮后，核心业务判断已经切换到 `grade_2 / kind_2`
- 当前源码中保留 raw `grade / kind` 的读取点，仅用于：
  - working layer 初始化
  - 原始值审计字段
  - refreshed 审计回报
- Step4 / Step5 已移除 raw `grade / kind` 业务 fallback
- 业务逻辑残留直接依赖 raw `grade / kind` 的位置：`0`

## 3. 明细

| 文件 | 函数/模块 | 当前读取字段 | 本轮是否已改 | 保留原因 |
| --- | --- | --- | --- | --- |
| `src/rcsd_topo_poc/modules/t01_data_preprocess/working_layers.py` | `_initialize_node_properties` | `grade`、`kind` | 保留 | working layer 初始化时将 raw 值复制到 `grade_2 / kind_2` |
| `src/rcsd_topo_poc/modules/t01_data_preprocess/step1_pair_poc.py` | `_prepare_nodes` | `grade`、`kind` | 已改 | raw 值仅写入 `raw_grade / raw_kind` 审计字段；规则匹配已改用 `grade_2 / kind_2` |
| `src/rcsd_topo_poc/modules/t01_data_preprocess/step1_pair_poc.py` | `REQUIRED_NODE_FIELDS` | `grade`、`kind` | 部分保留 | raw 字段仍要求存在，以便审计与展示；业务筛选不再使用 |
| `src/rcsd_topo_poc/modules/t01_data_preprocess/s2_baseline_refresh.py` | `_load_nodes_and_roads` / `MainnodeGroup` | `grade`、`kind` | 保留 | 作为 `grade_old / kind_old` 审计和回报字段保留；刷新判断已改用 `grade_2 / kind_2` |
| `src/rcsd_topo_poc/modules/t01_data_preprocess/step4_residual_graph.py` | `_current_grade_2` / `_current_kind_2` | 无 raw 业务读取 | 已改 | raw fallback 已去除，输入必须带 working fields |
| `src/rcsd_topo_poc/modules/t01_data_preprocess/step5_staged_residual_graph.py` | `_current_grade_2` / `_current_kind_2` | 无 raw 业务读取 | 已改 | raw fallback 已去除，输入必须带 working fields |

## 4. 测试夹具说明
- `tests/modules/t01_data_preprocess/*` 中仍会构造 raw `grade / kind`
- 这些位置属于测试夹具，用于：
  - 初始化 working layers
  - 验证 `grade_2 / kind_2` 与 raw 字段脱钩
  - 验证缺失 working fields 时 fail fast
- 不属于运行期业务逻辑残留

## 5. 本轮结论
- `working Nodes / Roads` 初始化已前移到模块开始阶段
- 后续业务判断已切换到 `grade_2 / kind_2`
- raw `grade / kind` 当前只保留为初始化 / 审计 / 展示用途
