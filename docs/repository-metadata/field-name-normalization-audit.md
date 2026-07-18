# 外部字段名归一化审计

## 审计口径

- 审计对象：Active、Active POC、Support Retained 的 Python 运行代码。
- 排除：Retired T02；内部状态、审计和正式 handoff 的精确 canonical key。
- 规则：外部字段查找统一复用 `rcsd_topo_poc.utils.field_names`，不再手写 `.lower()` 字段扫描。

## 真实触发数据

| 数据 | Road 端点 / 形态字段 |
|---|---|
| 997348/1026960 prepared SWSD | `snodeid / enodeid / formway` |
| 997348/1026960 1V1 FRCSD | `snodeId / enodeId / formWay` |
| 997348/1026960 1V1 FRCSD Node | `mainNodeId / crossFlag / ...` |

已检查 schema 未出现仅大小写不同的重复字段；共享能力仍对冲突值执行 hard fail。

## 迁移结果

| 范围 | 处理 |
|---|---|
| 项目公共层 | 新增 `PropertyLookup`、兼容 resolver/getter、canonical copy；使用 `casefold` 并检测冲突。 |
| T01 | Step1/slice/S2 外部字段按 logical name 读取；working layer 在独立副本中统一发布 lowercase canonical keys；跨要素 case variant 写入同一 schema 列。 |
| T03 | Node/Road/FRCSD accessor、Step1 parser、共享道路邻接统一归一化；修复 silent missing endpoint。 |
| T04 | Node/RCSDNode/Road 必填校验和 patch id 解析统一归一化；冲突错误保留 layer label 与 feature index。 |
| T00/T08 | 既有 resolver/getter 改为共享实现的兼容导出面；外部 JSON、schema、GeoPackage 几何列和保留字段判断统一归一化；跨要素 `ID/id` 只发布一个逻辑列。 |
| T05/T07/T09/T10 | 删除模块私有大小写扫描，外部属性和 schema 字段解析复用共享实现；T05 写出跨记录 case variant 时统一投影到首个实际列名。 |
| T06 | 既有输入 lowercase canonical copy 改为共享实现，保留冲突 hard fail 和内部 exact-key 合同。 |
| P01 | Node/Road/RoadNextRoad/证据包读取及 schema 归一化复用共享实现；保留其内部 lowercase canonical 属性模型。 |
| P02 | 矢量路径先通过 T08 resolver 得到真实字段名；人工 endpoint override CSV 表头与 `endpoint_field` 也按 logical name 归一化。 |
| T11 | 只消费 T03/T04/T05/T06/T10 已发布的 canonical status/audit/handoff，不把内部契约键降级为模糊匹配。 |

## 保留精确读取的类型

以下读取不属于外部字段名解析，保留 `.get(canonical_key)`：

1. T03/T04/T05/T07/T10 模块自产的 status、audit、relation、manifest handoff。
2. T06 `read_features()` 已完成 canonical copy 后的内部 feature properties。
3. 输出 schema 投影、dataclass 序列化和测试断言。

这些位置若大小写错误应被视为内部契约错误，不允许由外部字段兼容层静默修复。

## 自动门禁

`tests/utils/test_field_names.py` 扫描非 Retired 模块，禁止重新引入 `lower_map/lowered` 字段索引，以及 property/schema/table/column 标识上的手写 `.lower()` 扫描。

## GIS 与性能验证

- 环境：WSL Python `3.10.12`；源码为 `codex/004-field-name-normalization` 隔离工作树；数据根为 `/mnt/e/TestData/POC_QA/T10`。
- 真实 `997348/1026960` 输入均为 `EPSG:3857`；归一化不修改 CRS 或坐标转换路径。
- T03 解析后的 SWSD Road 几何总长度与输入差值均为 `0.0m`；两用例 T03 与 T04/FRCSD 缺失端点计数均为 `0`。
- `1026960` 实测解析耗时：T03 `0.0787s`，T04（SWSD Node/Road + FRCSD Node/Road）`0.4747s`。
- 45 字段、5 次逻辑字段读取、20000 轮微基准：共享索引 `0.1844s`，逐字段线性扫描 `0.3927s`，耗时比 `0.47`。
