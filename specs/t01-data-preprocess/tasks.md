# T01 任务清单

## 已接受基础
- [x] working bootstrap 已前移到模块开始阶段
- [x] roundabout preprocessing 已纳入正式预处理
- [x] Step1 只输出 `pair_candidates`
- [x] Step2 输出 `validated / rejected / trunk / segment_body / step3_residual`
- [x] Step4 / Step5A / Step5B / Step5C staged residual graph 语义已固化
- [x] Step5C adaptive barrier fallback 已纳入 accepted baseline
- [x] Step6 的 `segment / inner_nodes / segment_error` 语义已确认

## 本轮任务
- [x] input schema migration：官方输入统一到 GeoJSON
- [x] road output schema migration：正式输出统一到 `sgrade / segmentid`
- [x] Step6 formal integration：official runner 现在正式跑到 Step6
- [x] performance optimization：Step6 复用 Step5 records / mainnode_groups / allowed-road 索引
- [x] freeze regression：compare 支持 schema migration difference，不把 `s_grade -> sgrade` 误判为业务回退

## Step6 正式输出
- [x] `segment.geojson`
- [x] `inner_nodes.geojson`
- [x] `segment_error.geojson`
- [x] `segment_error_s_grade_conflict.geojson`
- [x] `segment_error_grade_kind_conflict.geojson`
- [x] `segment_summary.json`
- [x] `segment_build_table.csv`
- [x] `inner_nodes_summary.json`

## Step6 规则
- [x] 规则 1：两端 `pair_nodes` 的 `grade_2` 均为 `1` 时，将 segment 级 `sgrade` 轻调整为 `"0-0双"`
- [x] 规则 2：最终 `sgrade = "0-0双"` 且中间 `junc_nodes` 出现 `grade_2 = 1 且 kind_2 = 4` 时，输出到 `segment_error.geojson` 与 `segment_error_grade_kind_conflict.geojson`
- [x] `sgrade` 多值冲突时按 `0-0双 > 0-1双 > 0-2双` 选高等级，并同时输出到 `segment_error.geojson` 与 `segment_error_s_grade_conflict.geojson`

## 回归要求
- [x] GeoJSON 输入官方入口可跑通
- [x] 新输出 roads 仅正式写 `sgrade / segmentid`
- [x] `debug=false` 的 official runner 可直接产出 Step6 结果
- [x] `XXXS` official compare 已回归验证
