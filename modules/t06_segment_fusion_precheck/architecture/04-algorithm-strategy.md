# 04 Algorithm Strategy

## 分层

- `parsing.py`：字段解析与 ID 规范化。
- `io.py`：vector/table 读写、run root 与三格式输出。
- `schemas.py`：稳定字段、失败原因与 artifacts dataclass。
- `step1_identify_fusion_units.py`：Step1 eligibility。
- `relation_mapping.py`：T05 relation loader 与 pair/junc mapping 校验。
- `graph_builders.py`：SWSD / RCSD directed graph。
- `direction_inference.py`：SWSD 单向方向推导。
- `rcsd_candidate_extraction.py`：RCSD candidate path 抽取。
- `trend_filters.py`：directionality、junc、主轴、粗长度与唯一性硬筛。
- `step2_extract_rcsd_segments.py`：Step2 orchestration。
- `buffer_segment_extraction.py`：Step2 buffer-based RCSDSegment 候选子图、提前右转排除、连通分量覆盖与裁剪。
- `runner.py`：组合 runner。

## 策略

- Step1 先解析 `pair_nodes / junc_nodes / roads`，再做 node eligibility。
- Step2 先 relation mapping，再并行生成 buffer-based RCSDSegment 审查输出，随后做方向推导和既有 RCSD pair-to-pair candidate 抽取。
- 单向 SWSD 使用 road body directed graph 判断唯一方向。
- 双向 RCSD candidate 必须正反向可达；单向 RCSD candidate 必须仅同向可达。
- junc 检查先确认 mapped junc 被覆盖，再确认内部通过和侧向阻断。
- 主轴与粗长度只作为趋势类硬筛，不做精细拟合。
- 多个通过硬筛的 candidate 第一版不自动选优，输出 `ambiguous_rcsd_candidates`。
