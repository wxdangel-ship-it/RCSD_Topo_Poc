# 02 数据与领域模型

## 1. 上下游数据关系

T08 输入是原始 SWSD / RCSD / patch / restriction / Laneinfo / Traj 数据。T08 输出被 T01、T03、T04、T05、T06、T09 使用；其中 Tool7 restriction 与 Tool8 arrow 是 T09 的重要证据，Tool9 RCSD 清理结果会影响 T05 relation 与 T06 替换质量，Tool10 为 Patch 级轨迹消费提供统一 `LineStringZ` 输入，Tool11 为全量和实验流程提供统一 Patch 目录包。

## 2. 工具域

| 工具 | 数据域 | 下游意义 |
|---|---|---|
| Tool1 | 基础矢量格式转换 | 为后续工具和模块提供 GPKG / GeoJSON。 |
| Tool2 | SWSD Road patch / kind | 补齐 `patch_id / kind`，剔出事件 Road。 |
| Tool3 | SWSD Nodes 类型初始化 | 初始化 `kind_2 / grade_2`，聚合环岛。 |
| Tool4 | 路口类型修复 | 修复错误 T 型、交叉、分歧 / 合流类型。 |
| Tool5 | 复杂路口预处理 | 聚合复杂分合流链路，处理 RCSDIntersection 一对多错误。 |
| Tool6 | Nodes 类型质检 | 输出人工确认候选，不直接修复。 |
| Tool7 | SW restriction 显性化 | 将 C 表 restriction 转为 LineString 证据。 |
| Tool8 | Laneinfo arrow 显性化 | 将车道箭头转为 Road 方向级 LineString 证据。 |
| Tool9 | RCSD 清理 | 按道路面过滤 RCSDNode 语义组和 RCSDRoad。 |
| Tool10 | Patch 轨迹聚合 | 将 `Traj/*/raw_dat_pose.geojson` 的 PointZ 连续片段聚合为单 GPKG 的 `LineStringZ`。 |
| Tool11 | Patch 数据整理 | 将原始 SWSD/RCSD 全树和 FRCSD 三文件白名单整理为统一 Patch 包，并发布实验子集。 |

## 3. 关键字段语义

- `kind_2 / grade_2` 是下游当前语义字段，Tool3 初始化后由 Tool4/5 进一步修正。
- `closed_con` 是下游规范字段，原始输入 `closed_connect` 与其等价；Tool3 负责 copy-on-write 归一，两字段冲突时停止。
- `mainnodeid` 表达 SWSD / RCSD 语义路口组，T08 修复必须保持组语义。
- `formway bit7 = 128` 表示提前右转，Tool4/T06 均按 bit mask 语义使用。
- Road `kind` token 后两位为 `17` 时，Tool2 将对应 Road 剔入事件 Road 输出。
- Road `kind` token 后两位为 `0a` 时，可作为 Tool4 辅路豁免判断来源。
- Tool7/8 输出的是显性证据，不是 T09 最终通行规则。
- Tool10 输出段是一条源轨迹按显式断点阈值切分后的连续片段；Z 是源坐标值，不是 Tool10 推算高程。
- Tool11 的 `SWSD / RCSD / FRCSD` 是目录角色，不引入新字段或几何语义；逐字节一致性是其唯一内容变换口径。

## 4. 数据流

1. Tool1 完成格式转换。
2. Tool2/3/4/5/6 形成 SWSD Road/Node 字段显性化、修复和质检链。
3. Tool7/8 将通行限制和车道箭头转为可空间定位证据。
4. Tool9 清理 RCSDNode/RCSDRoad，输出下游可解释 RCSD 输入。
5. Tool10 独立扫描一个 Patch 的 Traj，排序、投影 XY、保留 Z、切段并聚合落盘。
6. Tool11 独立扫描全量 Patch，把源目录映射为统一 `SWSD / RCSD / FRCSD`，完成哈希验证后同时发布全量根和实验根。

## 5. 输出边界

T08 所有工具采用 copy-on-write 输出，不原地修改输入。输出文件名必须符合 `_toolX` 约束；Tool1 转换成果、Tool10 `Traj/raw_dat_pose.gpkg` 与 Tool11 保持原名的业务复制文件是已登记特例。summary 必须能定位输入、参数、输出、CRS 或不变性口径、计数和失败原因。
