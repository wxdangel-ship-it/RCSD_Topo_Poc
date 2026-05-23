# T01 Step2 kind_2=128 Performance Fix - Spec

## Product

T01 双向 Segment 构建已经正式允许 `kind_2 = 128` 复杂分歧 / 合流路口在首轮穿越。新的 XS1 测试用例显示，允许穿越后，Step2 在局部复杂路口内部进行全局 trunk path 搜索时可能出现单 pair 长时间运行。

本轮目标是在不回退 `kind_2 = 128` 可穿越语义的前提下，让 Step2 在复杂局部可控时间内给出可审计结果。

## Architecture

- `kind_2 = 128` 继续不作为 `seed / terminate / hard-stop`。
- Step1 candidate search 语义不变。
- Step2 trunk 验证先将复杂 `kind_2 = 128` 组合视为局部分歧 / 合流 port corridor。
- 对命中可终止复杂组合的 pair，Step2 只基于 Step1 已确认的进入 / 退出支持路径及其局部门禁给出结果，不在复杂路口内部展开全局 simple-path 追溯。
- 对未形成可终止复杂组合的小型 case，仍允许回退到既有精确判定；兜底预算保护继续防止残余全局枚举失控。
- 局部 corridor 与预算超限都不是 silent fix，必须写入 pair support info 和 summary 统计。

## Development

本轮实现范围：

- `step2_trunk_utils.py`
  - 为 simple path 枚举增加可中止预算。
  - 在 `_evaluate_trunk_choices` 中识别 `kind_2 = 128` 复杂穿越热点。
  - 增加 `kind2_128_local_corridor` 局部 port trunk mode。
  - 当复杂组合达到终止阈值时，局部 corridor 直接返回 validated 或明确 rejected，不再回退到全局 path 枚举。
  - 当剩余热点 pair 达到复杂度阈值时，限制 trunk path 枚举预算。
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

- 单元测试：构造复杂 `kind_2 = 128` pair，覆盖局部 corridor validated / rejected 且不调用全局 path 枚举。
- 单元测试：构造复杂 `kind_2 = 128` pair，触发预算超限并返回明确 reject reason。
- 回归测试：已有 Step2 trunk 选择测试继续通过。
- XS 性能验证：XS1 `pair_index=43` 使用 `--assume-working-layers` 不再超时，输出 `trunk_search_budget_exceeded` 或可解释判定。

## QA

本轮 QA 关注：

- CRS / 几何输入不被修改。
- 拓扑不执行 silent fix。
- 局部 corridor 结果可追溯到 pair、support road 数、kind_2=128 节点数量、终止阈值与门禁原因。
- 预算超限结果可追溯到 pair、candidate/pruned road 数、kind_2=128 节点数量和 path 枚举阶段。
- 性能验证必须报告具体命令、耗时、输出目录。
