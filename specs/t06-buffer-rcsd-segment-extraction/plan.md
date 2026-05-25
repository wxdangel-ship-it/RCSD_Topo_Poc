# T06 Buffer-Based RCSD Segment Extraction Plan

## Scope

本轮实现 T06 阶段二的 buffer-based RCSD Segment extraction 预检与审查输出。该能力作为 Step2 新策略的一部分进入模块内 runner，不新增 repo 入口。

## Files

- `src/rcsd_topo_poc/modules/t06_segment_fusion_precheck/buffer_segment_extraction.py`
- `src/rcsd_topo_poc/modules/t06_segment_fusion_precheck/step2_extract_rcsd_segments.py`
- `src/rcsd_topo_poc/modules/t06_segment_fusion_precheck/schemas.py`
- `tests/modules/t06_segment_fusion_precheck/test_buffer_segment_extraction.py`
- T06 module docs and project source facts.

## Implementation Shape

1. 新增纯函数模块实现 buffer candidate selection、advance-right exclusion、component selection 与 pruning。
2. 在 Step2 orchestration 中调用新策略并输出审查成果文件。
3. 保持现有 relation mapping 和 Step1 输出语义。
4. 新增 summary 统计，支持内网审查。

## Parameters

- `buffer_distance_m = 50.0`
- `min_road_overlap_ratio = 0.2`
- `min_road_overlap_length_m = 1.0`
- `advance_right_formway_bit = 128`

## Risks

- RCSDRoad 几何长线跨出 buffer 时阈值过严会断连。
- 阈值过宽会引入旁支和并行路。
- out/inner 裁剪若 seed 终止定义不清，会误删内部复杂结构。
- 内网数据字段 `formway` 缺失时不得几何反推，只能审计为 unknown/off。

## Verification

- Unit tests for all pure functions.
- T06 module pytest.
- `py_compile` on changed Python files.
- `git diff --check`.
