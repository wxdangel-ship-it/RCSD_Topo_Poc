# 021 Step2 trunk 子域架构拆分

## 背景
- `step2_segment_poc.py` 在第一轮拆出 release/output helper 后，仍长期高于 `100 KB`
- trunk candidate/path/gate 子域同时承载：
  - path search
  - trunk mode 判定
  - direction support
  - parallel / bypass / T-junction gate
- 若继续把业务修复直接堆叠在主文件中，会放大理解成本与回归半径

## 第二轮拆分
- 新增 `step2_trunk_utils.py`
- 抽离内容包括：
  - trunk candidate / path helper
  - trunk mode / signed area / counterclockwise helper
  - direction support 与 filtered directed adjacency
  - parallel corridor / bidirectional side bypass / T-junction vertical tracking gate
- `step2_segment_poc.py` 保留：
  - trunk choice 调用编排
  - segment_body / tighten
  - same-stage arbitration orchestration

## 验证
- 目标测试：
  - `tests/modules/t01_data_preprocess/test_step1_pair_poc.py`
  - `tests/modules/t01_data_preprocess/test_step2_segment_poc.py`
  - `tests/modules/t01_data_preprocess/test_step4_residual_graph.py`
  - `tests/modules/t01_data_preprocess/test_step5_staged_residual_graph.py`
- 当前通过数：`94 passed`

## 当前结论
- 第二轮拆分属于职责收敛，不改变 `Step2` 对外契约
- trunk/path/gate 子域已从主文件脱离，后续业务修复可在子域文件内继续迭代

## 后续建议
1. 继续拆出 validation/arbitration 包装 helper
2. 再评估 segment_body / tighten 子域是否需要单独模块
3. 架构整改继续以目标测试与样例最终 Segment 非回退为硬闸门
