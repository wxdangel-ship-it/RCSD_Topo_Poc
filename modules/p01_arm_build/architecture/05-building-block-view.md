# 05 构建块视图

## `models.py`

定义输入 Node / Road、A1 输出对象、RoadNextRoad movement 对象、final generation 对象、case result 与 summary row 等 dataclass。

## `io.py`

负责矢量读取、JSON/CSV/GPKG 写入、输出目录创建与 CRS / preflight 辅助信息。

## `topology.py`

负责语义路口组装、seed 识别、显式右转排除、trace、through decision、InitialArm / FinalArm 构建与自动结构检查。

## `special_roads.py`

负责 `formway` bit7 / bit8 解析、当前路口特殊道路索引、提前右转 relation 追溯与 relation issue 生成。

## `trunk.py`

负责从 InitialArm member roads 中排除特殊转向 road，并识别 trunk road ids、trunk 状态与非 trunk member roads。

## `road_next_road.py`

负责读取 SWSD / RCSD / F-RCSD RoadNextRoad JSON / GeoJSON，并归一化 raw road pair、raw type、raw turn type 与 source 审计字段。

## `movement.py`

负责 RoadNextRoad evidence 投影、全量 ArmMovement 候选、stable straight 审计字段、receiving road role 与 movement-aware corrected trunk。

## `final_road_next_road.py`

负责 P01-Final：F-RCSD Source + CRS-normalized rounded exact source road mapping、SourceMovementPolicy、parallel branch alignment、同源继承、跨源 primary source generation、RCSD -> SWSD fallback、final GeoJSON、audit、issue 与 review 输出辅助。

## `review.py`

负责 dataset review PNG 与 compare PNG 的像素级渲染。

## `text_bundle.py`

负责单 junction-group 文本证据包打包 / 解包。范围选择基于 Road 拓扑 BFS，不作为正式 CLI 入口。

## `runner.py`

负责 A1 / P01-Final 参数解析、批处理、summary、review index 与输出编排。该文件提供模块内 callable runner，不是正式 CLI。

## `alignment_models.py`

定义 A2 ArmProfile、candidate edge、LogicalArmGroup、RawArmAlignment、ArmBuildFeedback 与 source_extra 对象。

## `alignment_io.py`

负责读取 A1 run root、读取 A1 case / dataset JSON，并从 A1 preflight 加载原始 Node / Road 几何。

## `alignment.py`

负责 A2 profile 构建、候选评分、LogicalArmGroup 构建、RawArmAlignment、feedback、source_extra 与 issue 分类。

## `alignment_review.py`

负责 A2 source alignment PNG、三源 compare PNG 与 alignment GPKG 图层。

## `alignment_runner.py`

负责 A2 参数解析、批处理、summary、review index 与输出编排。该文件提供模块内 callable runner，不是正式 CLI。
