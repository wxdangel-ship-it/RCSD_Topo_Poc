# 05 构建块视图

## `models.py`

定义输入 Node / Road、业务输出对象、case result、summary row 等 dataclass。

## `io.py`

负责矢量读取、JSON/CSV/GPKG 写入、输出目录创建与 CRS/preflight 辅助信息。

## `topology.py`

负责语义路口组装、seed 识别、右转排除、trace、through decision、InitialArm / FinalArm 构建与自动结构检查。

## `review.py`

负责 dataset review PNG 与 compare PNG 的像素级渲染。

## `text_bundle.py`

负责单 junction-group 文本证据包打包 / 解包。该模块复用 T02 的文本包装思路，但 P01 的范围选择基于 Road 拓扑 BFS，不作为正式 CLI 入口。

## `runner.py`

负责参数解析、批处理、summary、review index 与输出编排。当前为模块内可调用 runner，不是正式 CLI。

## `alignment_models.py`

定义 A2 ArmProfile、candidate edge、LogicalArmGroup、RawArmAlignment、ArmBuildFeedback 与 source_extra 对象。

## `alignment_io.py`

负责读取 A1 run root、读取 A1 case/dataset JSON，并从 A1 preflight 加载原始 Node / Road 几何。

## `alignment.py`

负责 A2 profile 构建、候选评分、LogicalArmGroup 构建、RawArmAlignment、feedback、source_extra 与 issue 分类。

## `alignment_review.py`

负责 A2 source alignment PNG、三源 compare PNG 与 alignment GPKG 图层。

## `alignment_runner.py`

负责 A2 参数解析、批处理、summary、review index 与输出编排。当前为模块内可调用 runner，不是正式 CLI。
