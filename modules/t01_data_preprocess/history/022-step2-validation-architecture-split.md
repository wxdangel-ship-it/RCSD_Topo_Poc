# 022 Step2 validation / arbitration 包装拆分

## 背景
- 第二轮 trunk 拆分后，`step2_segment_poc.py` 仍保留大量 validation/arbitration 包装与结果类型定义
- 同时文件内仍存在未使用的 `_validate_pair_candidates_greedy`，继续推高主文件体量
- 仓库级规则要求：源码文件超过 `100 KB` 视为结构债，后续变更应继续收敛职责

## 第三轮拆分
- 新增 `step2_validation_utils.py`
- 抽离内容：
  - `PairValidationResult`
  - `Step2StrategyResult`
  - arbitration boundary / strong-anchor / semantic-conflict 索引 helper
  - same-stage arbitration 的 validation 包装 helper
  - validation road-count helper
- 同时删除 `step2_segment_poc.py` 中未使用的 `_validate_pair_candidates_greedy`

## 当前收益
- `step2_segment_poc.py` 已降到 `< 100 KB`
- 主文件当前聚焦：
  - candidate channel / prune
  - segment_body / tighten
  - same-stage arbitration orchestration
  - Step2 runner orchestration

## 验证
- 目标测试：
  - `tests/modules/t01_data_preprocess/test_step1_pair_poc.py`
  - `tests/modules/t01_data_preprocess/test_step2_segment_poc.py`
  - `tests/modules/t01_data_preprocess/test_step4_residual_graph.py`
  - `tests/modules/t01_data_preprocess/test_step5_staged_residual_graph.py`
- 当前通过数：`94 passed`

## 样例回放边界
- 架构整改期间补跑了 `XXXS6~8`
- 结果：
  - `XXXS8` 与最近接受输出最终 Segment 一致
  - `XXXS6 / XXXS7` 与最近接受输出仍有业务差异
- 该差异当前记录为“待后续业务修复批次继续确认”，不在本轮架构整改中直接改业务规则

## 后续建议
1. 下一轮继续审计 `segment_body / tighten` 子域是否值得抽离
2. 将 runner/progress/audit orchestration 继续从 `step2_segment_poc.py` 收敛出去
3. 架构整改与业务修复继续分批执行，避免混修
