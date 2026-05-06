# 05 构建块视图

## `models.py`

定义输入 Node / Road、业务输出对象、case result、summary row 等 dataclass。

## `io.py`

负责矢量读取、JSON/CSV/GPKG 写入、输出目录创建与 CRS/preflight 辅助信息。

## `topology.py`

负责语义路口组装、seed 识别、右转排除、trace、through decision、InitialArm / FinalArm 构建与自动结构检查。

## `review.py`

负责 dataset review PNG、compare PNG、trace review PNG 的像素级渲染。

## `text_bundle.py`

负责单 junction-group 文本证据包打包 / 解包。该模块复用 T02 的文本包装思路，但 P01 的范围选择基于 Road 拓扑 BFS，不作为正式 CLI 入口。

## `runner.py`

负责参数解析、批处理、summary、review index 与输出编排。当前为模块内可调用 runner，不是正式 CLI。
