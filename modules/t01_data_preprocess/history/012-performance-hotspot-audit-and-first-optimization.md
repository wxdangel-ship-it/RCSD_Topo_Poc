# 012 - Performance Hotspot Audit and First Optimization

## 1. 背景
- 在 A200 全量运行中，official runner 已可完整跑通 `debug=true` 与 `debug=false`。
- 当前性能数据表明：
  - `Step2` 是绝对主瓶颈
  - `Step4` 与 `Step5` 次之
  - 这三个阶段共享同一套双向构段内核，因此适合优先做跨阶段可复用的优化

## 2. 当前 A200 基线观察
- 用户在 2026-03-21 提供的 A200 运行结果：
  - `debug=true`
    - total wall: `9221.538s`
    - `Step2`: `6867.384s`
    - `Step4`: `1368.782s`
    - `Step5`: `780.323s`
  - `debug=false`
    - total wall: `7935.645s`
    - `Step2`: `6063.174s`
    - `Step4`: `1171.234s`
    - `Step5`: `569.817s`
- 结论：
  - `debug` 额外开销明显，但主瓶颈不是导出本身，而是 `Step2` 主计算。

## 3. 本轮热点审计结论

### 3.1 重复 `_refine_segment_roads(...)`
- `Step2` validated 流程里，`_validate_pair_candidates(...)` 已经对 validated candidate 计算过一次 `segment_body_candidate_road_ids / cut_infos`。
- 但 `_tighten_validated_segment_components(...)` 仍会对同一 validated pair 再执行一次 `_refine_segment_roads(...)`。
- 这类重复计算会自动放大到：
  - `Step2`
  - `Step4`
  - `Step5A`
  - `Step5B`
  - `Step5C`

### 3.2 trunk validation 的全图扫描
- `_evaluate_trunk(...)` 里构造 base / strict / support directed adjacency 时，旧实现会按 pair 扫描整份 `context.directed`。
- 但 candidate 实际只依赖当前 `allowed_road_ids`。
- 对大图来说，这属于按 pair 重复扫全图，复杂度不合理。

## 4. 本轮已实施优化

### 4.1 复用 validated 阶段已算出的 segment 候选
- `_tighten_validated_segment_components(...)` 优先读取：
  - `segment_body_candidate_road_ids`
  - `segment_body_candidate_cut_infos`
- 若 support info 已存在，不再重复 `_refine_segment_roads(...)`。
- 仅在旧数据或极端 fallback 场景下才回退重算。

### 4.2 trunk adjacency 改为局部构建
- `_build_filtered_directed_adjacency(...)` 不再按 pair 扫描整份 `context.directed`。
- 新实现只遍历当前 `allowed_road_ids`，并依据：
  - `road.direction`
  - `road_endpoints`
  构建局部 directed adjacency。
- 该优化同时作用于：
  - base adjacency
  - strict adjacency
  - through-collapsed support adjacency

## 5. 回归结果
- `python -m pytest tests/modules/t01_data_preprocess -q`
  - `51 passed`
- 三样例官方入口 + compare：
  - `XXXS`: `PASS`
  - `XXXS2`: `PASS`
  - `XXXS3`: `PASS`
- 说明本轮优化未改变当前活动三样例基线结果。

## 6. 当前未解决的性能债
- `Step2` path enumeration / trunk candidate 组合仍可能是下一轮最大热点。
- `Step4 / Step5` 在 `debug=false` 下仍依赖 staged working-layer 写盘，不是深度全内存流水线。
- `step2_segment_poc.py` 继续承担过多职责，结构债仍然存在。

## 7. 下一轮建议
1. 在不改业务语义的前提下，继续审计 `Step2` path enumeration 与 candidate pruning。
2. 评估 `Step4 / Step5` 是否可减少 working-layer 中间写盘或引入更轻量的内存传递。
3. 所有进一步优化都必须继续对齐当前活动三样例基线。
