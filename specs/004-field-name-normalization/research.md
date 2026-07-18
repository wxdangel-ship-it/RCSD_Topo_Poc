# Research: 外部数据字段名归一化

## 已确认事实

1. `997348` 与 `1026960` 的 prepared SWSD road schema 使用 `snodeid/enodeid/formway`。
2. 两个 Case 的 1V1 FRCSD `rcsdroad_slice.gpkg` 使用 `snodeId/enodeId/formWay`；RCSDNode 还使用 `mainNodeId/crossFlag/...`。
3. T03 `full_input_shared_layers.py` 与 `step1_context.py` 对道路端点使用精确 `.get("snodeid")/.get("enodeid")`，缺值会被跳过或保存为 `None`，因此 T03 可以机械通过但拓扑不完整。
4. T04 `_runtime_types.py::_parse_roads` 先以精确键检查必填字段，再精确取值，因此对上述 FRCSD schema 直接报错。
5. T06 已有 `_normalize_property_keys`，具备小写归一化和冲突值失败行为；T00、T05、T08、T10 等还存在多套局部实现。
6. 两个真实 Case 的已检查 schema 未发现仅大小写不同的重复字段，但实现仍必须防御该歧义。

## 决策

### R-001 原属性保留，查找索引归一化

- **选择**: 对每个外部属性映射建立 `casefold` 索引；读取时返回原始字段对应值，不修改原字典。
- **原因**: 下游存在原属性透传和审计需求，直接把所有键改成小写会改变输出 schema。
- **否决方案**: 在原字典中插入 lowercase aliases。该方案会产生重复输出字段、污染审计并隐藏冲突。

### R-002 单要素索引复用

- **选择**: 提供 `PropertyLookup`，模块解析一个要素的多个字段时只构建一次索引；便捷函数用于低频单字段场景。
- **原因**: FRCSD Road 字段数量较多，逐字段线性扫描会放大主链开销。

### R-003 冲突显式失败

- **选择**: 同一 logical name 下不同非空值抛出 `FieldNameConflictError`；相同值或只有一个非空值可解析。
- **原因**: 大小写兼容不能替代数据规格仲裁，拓扑字段的任意选择风险不可接受。

### R-004 外部与内部字段边界

- **选择**: 仅外部矢量/表格/用户文件属性使用归一化查找；内部 handoff 和审计字典继续按 canonical key 精确读取。
- **原因**: 对内部字典也宽松会掩盖模块间契约拼写错误。

### R-005 不扩展字段语义

- **选择**: 默认只处理大小写差异；候选别名必须来自既有模块契约。
- **原因**: 遵守字段语义管控，禁止由局部样本反推 `startNodeId` 等新别名。

## 范围

- 纳入：Active、Active POC、Support Retained 中的运行时外部字段读取和重复 helper。
- 排除：Retired T02 大文件、内部结果字典的精确契约、入口签名、业务阈值、几何算法。
