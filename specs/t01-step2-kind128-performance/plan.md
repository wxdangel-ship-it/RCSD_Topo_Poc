# T01 Step2 kind_2=128 Performance Fix - Plan

## Scope

只修复 T01 Step2 trunk 验证阶段在复杂 `kind_2 = 128` 穿越场景下的运行时间不可控问题。

## Implementation Plan

1. 增加 path search budget 数据结构。
2. 将 `_enumerate_simple_paths` 改为预算感知枚举。
3. 在 `_evaluate_trunk_choices` 内识别复杂穿越 pair：
   - `pair.crosses_kind_2_128`
   - `len(pair.kind_2_128_node_ids)` 达到阈值
   - `len(pruned_road_ids)` 达到阈值
4. 复杂穿越 pair 使用受限 path budget。
5. budget exhausted 时直接返回：
   - `reject_reason = trunk_search_budget_exceeded`
   - support info 包含预算配置、消耗计数、pair 复杂度与阶段。
6. 在 Step2 summary 增加预算超限计数。
7. 增加单元测试与 XS1 pair 43 性能复测。

## Risk Control

- 不改变普通 pair 的 path 枚举默认行为。
- 仅在复杂 `kind_2 = 128` 热点 pair 上启用预算限制。
- 预算超限作为 rejected candidate 输出，不生成 segment body。
- 结果可通过 `pair_validation_table.csv`、`rejected_pair_candidates.csv`、`segment_summary.json` 审计。
