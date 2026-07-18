# Data Model: 字段名归一化

## PropertyLookup

| 属性 | 类型 | 说明 |
|---|---|---|
| `properties` | `Mapping[str, Any]` | 原始属性，只读引用，不修改键和值 |
| `logical_to_originals` | `dict[str, tuple[str, ...]]` | `casefold` logical name 到原始字段名集合 |
| `logical_to_value` | `dict[str, Any]` | 已完成空值归并与冲突校验的逻辑值 |

### 状态规则

1. 无匹配：返回缺失状态。
2. 单匹配：返回对应值。
3. 多匹配且所有非空值相同：返回该值。
4. 多匹配且仅一个非空值：返回该值。
5. 多匹配且存在不同非空值：进入 `conflict`，构造阶段立即失败。

## FieldNameConflictError

必须包含：logical name、原始字段名列表、冲突值摘要；调用方可附加输入路径、图层和 feature index 上下文。

## 不变量

- 输入 `properties` 不发生 mutation。
- `id`、`ID`、`Id` 的 logical name 相同。
- 字段值不做 lowercase、trim、类型转换；这些仍由模块现有解析器负责。
- canonical 输出 schema 不由 `PropertyLookup` 自动生成。
