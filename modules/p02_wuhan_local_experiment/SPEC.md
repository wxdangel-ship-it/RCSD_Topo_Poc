# P02 模块需求：武汉局部人工锚定实验

## 1. 模块定位

P02 是 `Active POC / 成果模块`，在武汉局部实验数据上复用 T08、T01、T05、T06，验证缺少道路面/导流带时由人工关系驱动的 Segment 融合链路。实验必须完整保留用户提供的 SWSD/RCSD 原始要素，不创建裁剪工作副本。

## 2. 业务目标

- 固定 `Tool1 -> Tool3 -> Tool6 -> Tool4 -> Tool5` 输入治理顺序。
- 保存用户原始关系，并在复杂路口构建后转换为 T11/T05 可消费关系。
- 执行 T01/T05/T06，分层报告 relation、replaceable、replacement 和 topology 结果。
- 形成可复现的输入、参数、环境、输出、性能和 QA 证据。

## 3. 当前范围

- 支持 13 条 `1v1_rcsd_junction`、1 条 `1v1_rcsd_road` 与 2 条 `1vN_rcsd_road` 原始关系。
- 支持 Tool5 后 SWSD target canonical 转换、同对象类别 selected ID 并集合并、1vN 升级和跨对象类别冲突阻断。
- 支持原始数据缺失端点审计，但不得据此删除 Road、补造 Node 或自行改写端点。用户逐项确认的临时 `SNodeId/ENodeId` 修正可在 P02 工作副本执行，必须保留原始输入并单独审计。
- 不运行或伪造 T07/T03/T04，不运行 T09。
- 提供一个正式内网单 Case 编排入口；调用者只需提供包含四个约定 GeoJSON 的原始数据目录，入口必须自动完成当前武汉实验全链路、结果硬校验和 QGIS 工程生成。

## 4. 上下游关系

| 方向 | 模块 / 数据 | 关系 |
|---|---|---|
| 上游 | T08 | 提供规范 SWSD Nodes/Roads。 |
| 上游 | 用户人工关系 | 提供原始 SWSD→RCSDNode/RCSDRoad 事实。 |
| 编排 | T01 | 生成 Segment。 |
| 编排 | T05 | 消费转换后的 T11 人工关系并发布 relation/RCSD。 |
| 编排 | T06 | 执行替换可行性、replacement plan 和 F-RCSD topology audit。 |

## 5. 什么是对

- raw、converted、published 和 carrier 四层关系可逐条追溯。
- 1vN RCSDRoad 关系在同一行用 `|` 保存，不拆成同 target 多条 1v1。
- 多 raw target 聚合为同一 canonical target 时，同为 RCSD junction 或同为 RCSDRoad 的关系合并 selected ID；并集超过 1 个时升级为 1vN。只有 junction/road 跨对象类别混合时阻断。
- SWSD/RCSD Road 与 Node 全量进入正式模块流程；缺失端点默认只审计，不删除 Road、不补造 Node。当前授权例外为 `endpoint_overrides/p02_confirmed_endpoint_overrides.csv` 登记的 9 项逐 Road、逐字段修正；只改 P02 copy-on-write 工作副本，逐项校验旧值和 replacement Node 唯一存在，不读取 `NodeLid/CrossLid`，不在运行时执行几何匹配，也不形成通用归一规则。
- 人工关系只负责 T05 relation 发布与 T06 语义锚定。没有正式锚定关系的 Segment 保留 SWSD，不得因空间邻近、`CrossLid` 或局部样本进入替换计划。
- 并行 RCSD 通道的 Segment 归属必须遵循“正式锚定关系 > required junction 有序相对位置 > 几何距离”；邻近 Segment 的通道不能代替当前 Segment 自身的锚点覆盖。
- 结果分开报告 Segment funnel、T05 relation、T06 replacement 和 topology。
- 正式入口的默认成功条件包括 QGIS 工程写出、回读、相对 datasource 解析和当前武汉结果硬校验全部通过；`--qgis-mode skip` 只允许开发诊断，不构成完整交付。

## 6. 什么是错

- 原始关系直接进入 T05 而绕过 Tool5 canonical 转换。
- 原始人工表直接进入 T06 作为替换白名单。
- 用空兼容工件声称 T07/T03/T04 已完成。
- 将武汉局部结果解释为全量生产基线。
