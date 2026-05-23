# T01 Step2 kind_2=128 Performance Fix - Spec

## Product

T01 双向 Segment 构建已经正式允许 `kind_2 = 128` 复杂分歧 / 合流路口在首轮穿越。新的 XS1 测试用例显示，允许穿越后，Step2 在局部复杂路口内部进行全局 trunk path 搜索时可能出现单 pair 长时间运行。

本轮目标是在不回退 `kind_2 = 128` 可穿越语义的前提下，让 Step2 在复杂局部可控时间内给出可审计结果。

## Architecture

- `kind_2 = 128` 继续不作为 `seed / terminate / hard-stop`。
- Step1 candidate search 语义不变。
- Step2 trunk 验证增加复杂路口穿越预算保护。
- 对穿越大量 `kind_2 = 128` 且 pruned channel 过大的 pair，Step2 不在复杂路口内部无限展开 simple-path 搜索，而是在预算范围内尝试现有 trunk 判定；超限时返回显式 reject reason。
- 超限不是 silent fix，必须写入 pair support info 和 summary 统计。

## Development

本轮实现范围：

- `step2_trunk_utils.py`
  - 为 simple path 枚举增加可中止预算。
  - 在 `_evaluate_trunk_choices` 中识别 `kind_2 = 128` 复杂穿越热点。
  - 当热点 pair 达到复杂度阈值时，限制 trunk path 枚举预算。
  - 预算耗尽时返回 `trunk_search_budget_exceeded`。
- `step2_output_utils.py`
  - 在 summary 中统计 `trunk_search_budget_exceeded_count`。
  - 在既有 `pair_validation_table.csv` 的 `support_info` 中保留预算超限审计信息。

不修改：

- 官方 CLI / scripts 入口。
- Step1 seed / terminate / hard-stop 规则。
- `through_node_ids` 语义。
- freeze baseline。

## Testing

必须覆盖：

- 单元测试：构造复杂 `kind_2 = 128` pair，触发预算超限并返回明确 reject reason。
- 回归测试：已有 Step2 trunk 选择测试继续通过。
- XS 性能验证：XS1 `pair_index=43` 使用 `--assume-working-layers` 不再超时，输出 `trunk_search_budget_exceeded` 或可解释判定。

## QA

本轮 QA 关注：

- CRS / 几何输入不被修改。
- 拓扑不执行 silent fix。
- 预算超限结果可追溯到 pair、candidate/pruned road 数、kind_2=128 节点数量和 path 枚举阶段。
- 性能验证必须报告具体命令、耗时、输出目录。
