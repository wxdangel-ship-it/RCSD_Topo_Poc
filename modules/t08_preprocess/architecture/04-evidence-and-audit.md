# 04 证据与审计

## 1. 审计目标

T08 是前置数据治理层，必须让下游能判断输入是否已转换、字段是否已补齐、修复是否来自人工确认或自动规则、restriction / arrow 是否只是证据、RCSD 清理是否破坏语义组。

## 2. 工具证据

| 工具 | 关键证据 |
|---|---|
| Tool1 | 输出文件、转换 summary、输入/输出 CRS、要素数、失败原因。 |
| Tool2 | patch join / kind enrich summary、unmatched Road、event Road。 |
| Tool3 | nodes output、roundabout aggregation summary、单 node 环岛保留审计。 |
| Tool4 | repaired nodes、optional roads、audit nodes、repair summary。 |
| Tool5 | complex nodes/roads、audit nodes、one-to-many 处理 summary。 |
| Tool6 | `node_error_tool6.csv/gpkg`、人工确认字段、summary。 |
| Tool7 | `sw_restriction_tool7.gpkg`、restriction summary。 |
| Tool8 | `sw_arrow_tool8.gpkg`、arrow summary。 |
| Tool9 | `rcsdnode_clean_tool9 / rcsdroad_clean_tool9`、RCSD clean summary。 |

## 3. 人工确认链

Tool6 输出的 `是否修复` 默认值为 `1`，人工确认不需要修复时改为 `0`，再由 Tool4 消费。Tool6 本身不改写输入，也不代表修复已执行。

## 4. Restriction / Arrow 审计

Tool7 只显性化 `CondType=1` 的 restriction 几何，Tool8 只按 Road 方向聚合 Laneinfo arrow。两者保留原始业务字段和 summary，但最终通行规则恢复属于 T09。

## 5. RCSD 清理审计

Tool9 必须按 `mainnodeid` 语义组整体保留或删除 RCSDNode。RCSDRoad 先按几何与道路面相交，再按端点是否均属于保留 node 集合过滤。summary 需要记录组保留 / 删除和 road 端点过滤计数。
