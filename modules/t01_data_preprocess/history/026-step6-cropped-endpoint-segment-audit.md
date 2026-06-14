# 026 Step6 Cropped Endpoint Segment Audit

## 日期
- 2026-06-10

## 背景
- T10 四个裁剪 Case 在 T01 Step6 统一阻断，表现为部分 `segmentid` 关联道路引用的 `snodeid/enodeid` 不存在于局部 `nodes.gpkg`。
- 用户已说明本轮测试包来自空间裁剪，边缘数据不完整时允许全链路异常处理，但最终质量分析不应把这类裁剪边缘异常计入业务错误。

## 根因
- Step6 原逻辑把“Segment road 引用缺失端点 node”视作全局输入损坏，直接抛出异常。
- 对裁剪数据而言，该现象只说明当前局部包无法解释该 Segment 的完整端点拓扑；继续发布该 Segment 会污染下游拓扑，直接中断又会阻断同一 Case 内其他完整 Segment 的处理。

## 本次边界
- 不反推任何上游字段新语义。
- 不对缺失端点做 silent fix，不补造 node，不截断 road geometry。
- 只对端点证据不完整的整个 Segment 做审计化跳过，其余拓扑完整 Segment 继续发布。

## 实际变更
- Step6 在构建 incident road 索引时跳过缺端点的 road，不再让单条裁剪边缘 road 阻断全量 Segment 聚合。
- 对包含缺端点 road 的 `segmentid`，整个 Segment 不写入正式 `segment.gpkg`，改写入 `segment_error.gpkg` 与 `segment_build_table.csv`。
- 新增 `missing_endpoint_node` 错误类型，并记录 `missing_endpoint_road_ids`、`missing_endpoint_details`，用于后续质量分析排除裁剪边缘异常。
- `segment_summary.json` 新增跳过 Segment 与缺端点 road 计数。

## 验证
- 新增单测覆盖缺端点 Segment 被审计跳过、完整 Segment 继续发布、summary/build table/error layer 证据齐全。
- 已运行 `pytest tests/modules/t01_data_preprocess/test_step6_segment_aggregation.py`，结果 `9 passed`。
- T10 四个 Case 复跑后 T01 均通过，缺端点裁剪异常进入 Step6 审计输出。
