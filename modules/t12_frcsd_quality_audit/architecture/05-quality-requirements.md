# 05 Quality Requirements

## 1. 业务正确性

- SWSD 必需方向、FRCSD direction 和 portal 角色必须可解释。
- 复合路口 canonical 节点组与 raw endpoint 物理通行必须分层；canonical 零长度可达或无物理 Road 路径不得替代 carrier。既有 portal-constrained semantic 层继续拒绝标准面外 T07 alias 和超出 portal radius 的内部 alias；双端唯一 T07 标准面可由独立 Road-surface 层使用 Road 相交或 anchor→frontier 一跳 surface support Road 排除 node-portal 假断裂，support Road 使用 `1m` 拓扑容差且 carrier 至少一端必须实际接触标准面，其它距离指标仅作审计。两层都不能单独确认问题。
- DriveZone 与 T06 只作证据，不能静默改变 verdict。

## 2. GIS 与拓扑

- CRS 必须存在；距离计算使用 metre-based projected CRS。
- 无效几何、缺失 endpoint 和错误批次证据必须阻断。
- 不执行 geometry repair、snap、endpoint 补点或其它 silent fix。
- Road-surface contact/stop 只作判定与审计语义，不截断或改写 Road 几何。

## 3. Decision、Review 与 formal

- 无复核时也必须自动产生 confirmed/excluded，默认 manual=0。
- confirmed/excluded/manual 三组互斥且计数守恒；manual 只允许由显式外部 override 产生。
- 禁止高/中概率正式分类。

## 4. 观测与性能

- 每次运行留下 manifest、summary、日志、空间证据和分阶段耗时。
- 完整数据性能必须在实际内网环境验证；本地 Case 结果不能替代全量结论。

## 5. 治理

- 入口、生命周期、项目/T10/T12 源事实和实现保持一致。
- 生产代码不硬编码 Case/Segment/Road/Node ID。
