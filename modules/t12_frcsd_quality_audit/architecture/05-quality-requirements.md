# 05 Quality Requirements

## 1. 业务正确性

- SWSD 必需方向、FRCSD direction 和 portal 角色必须可解释。
- 复合路口节点组和零长度可达语义必须一致。
- DriveZone 与 T06 只作证据，不能静默改变 verdict。

## 2. GIS 与拓扑

- CRS 必须存在；距离计算使用 metre-based projected CRS。
- 无效几何、缺失 endpoint 和错误批次证据必须阻断。
- 不执行 geometry repair、snap、endpoint 补点或其它 silent fix。

## 3. Review 与 formal

- 无复核时 confirmed=0。
- confirmed/excluded/manual 三组互斥且计数守恒。
- 禁止高/中概率正式分类。

## 4. 观测与性能

- 每次运行留下 manifest、summary、日志、空间证据和分阶段耗时。
- 完整数据性能必须在实际内网环境验证；本地 Case 结果不能替代全量结论。

## 5. 治理

- 入口、生命周期、项目/T10/T12 源事实和实现保持一致。
- 生产代码不硬编码 Case/Segment/Road/Node ID。
