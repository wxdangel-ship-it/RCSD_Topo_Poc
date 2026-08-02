# 实施计划

## 阶段 A：可测量基线

1. 在现有正式入口中加入低开销资源采样和 P04 调用栈热点聚合。
2. 保留 30 秒控制台心跳，同时报告 RSS、CPU、I/O 和热点栈。
3. 将最终资源统计并入既有 summary `performance`，不改变入口参数。
4. 对真实 6-Patch 用例记录优化前基线。

## 阶段 B：热点优化

按测量结果依次处理：

1. 输入发现、必需图层读取和输入清单；
2. 重复 `materialize_network_geometry` / `build_nodes_and_connect_roads` 全网重建；
3. 空间候选检索中的重复全表扫描和重复几何运算；
4. 输出 GPKG、独立 QA 和 QGIS 工程生成；
5. 中间 GeoDataFrame 生命周期和内存释放。

每个优化点单独提交基准与业务等价证据，不进行不可审计的批量重写。

第三轮首先把数值和门槛覆盖热点改为“完整最终surface prepared终态谓词 + 边界样本精确求交”；
最终`MultiPolygon`的数值覆盖率只索引其原生组件，不重组原始DriveZone分片。随后
统一completion/corridor/junction/node覆盖调用，并依据查询计数和缓存命中率
判断是否需要对多轮Segment carrier做dirty-set增量重算。后者若必须触碰超限的
`segment_first_pipeline.py`，先按仓库体量规则提交拆分计划，不直接追加。

## 阶段 C：并发策略

- 仅对 Patch 独立的 I/O/预处理启用并发。
- 默认并发度不超过 6。
- 结果按 Patch ID 和稳定主键排序后合并，保证重复运行确定性。
- 若 Fiona/GDAL 线程安全或内存证据不满足，则退回有界串行批处理，不强行并行。

## 阶段 D：验收

1. P04 全量测试。
2. 真实 6-Patch 前后业务等价。
3. 合成 1500 Patch 输入发现/清单/读取微基准。
4. 内网 1500 Patch 正式复跑。
5. 记录 wall、CPU、RSS、I/O、热点分布、业务等价和 QGIS QA。

## 阶段 E：真实进度

1. 新增独立进度事件组件，不改变正式入口参数签名；
2. 在Patch读取、Segment carrier、Junction/Node/Topology、QA和输出边界发布真实
   `completed/total`；
3. 正式入口每30秒输出阶段、吞吐、ETA、资源与覆盖快速判定/精确回退计数，并追加
   `p04_progress.jsonl`；
4. 测试进度单调性、阶段完成、停滞告警和异常退出后的最后事件可追溯性。

## 风险与回退

- 若热点位于超过 100 KB 的 `segment_first_pipeline.py`，本任务不直接追加代码；
  先通过新子模块抽取形成拆分计划，获得治理授权后再迁移。
- 若并发导致非确定性、GDAL 崩溃或内存峰值上升，立即回退该并发点。
- 若优化改变任何业务 gate 或几何，判为失败，不进入内网候选。
