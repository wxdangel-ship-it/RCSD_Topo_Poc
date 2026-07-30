# 现状分析与研究记录

## 1. 已知真实证据

- 1532 Patch 内网运行在约 `97,689s`（约 27.1h）后，于网络几何后段因
  缺失 Access geometry 调用 `.distance()` 崩溃。
- 该空 geometry 崩溃已在 `main@9b20591` 修复，但修复后的 1532 Patch
  完整耗时尚未确认。
- 本地 1885118 的 6-Patch 历史 Segment-first 运行存在约 `725.4s`
  的记录，说明小规模真实数据也需要进一步剖析。
- 当前 summary 的 `performance` 只有总 `elapsed_seconds`，不能定位阶段热点。

## 2. 代码事实

- `segment_first_pipeline.py` 当前 100510 bytes，已超过 100 KB，禁止直接追加。
- 主流程会在多种 rescue/fallback 分支多次调用
  `materialize_network_geometry` 和 `build_nodes_and_connect_roads`。
- Patch 输入按图层、按 Patch 串行读取，所有 Patch 的 GeoDataFrame 同时驻留。
- 当前输入 manifest 会枚举并 SHA256 所有 Patch GeoJSON/GPKG，
  包括 P04 未消费的图层；6-Patch 历史 manifest 已包含 438 个文件，
  而 P04 主流程只读取其中固定的业务图层族。

## 3. 第一轮假设

1. 1532 Patch 的前段耗时由大量小文件打开、CRS 转换、全目录哈希共同放大。
2. 中后段耗时由多轮全网几何/Node 重建和重复空间候选检索主导。
3. 单纯增加进程数会复制大型 GeoDataFrame，可能造成 RSS 峰值和 GDAL 稳定性问题。

上述只作为待验证假设；正式优化顺序以低开销调用栈采样结果为准。

## 4. 6-Patch优化实证

冻结对照为
`perf_baseline_1885118_20260730T0911`，最终本地候选为
`perf_opt6_1885118_20260730T1010`：

- wall：`738.55s -> 262.21s`，降低约`64.5%`；
- process CPU：最终`223.97s`，平均单进程CPU占用`85.4%`；
- peak RSS：最终`513818624 bytes`，约`490MiB`；
- 正式结果：`887 Road / 1134 Node / 1933 RoadNextRoad`；
- independent QA：`0 violation`，QGIS `52`层回读通过；
- CRS：`EPSG:32650`；
- 正式、审计、关系、比较、独立QA和summary工件均通过
  T10语义指纹等价；只有输入manifest按设计从全目录文件改为实际消费文件。

优化后的P04专项测试为`274 passed`。上述证明本地6-Patch业务零回退和资源
峰值受控，不替代约1500 Patch内网正式复跑；`<=6h`目标与`<=8h`硬上限
仍保持待验收。

## 5. 已确认热点与处理

1. Patch Road路径评分反复计算：改为每个候选路径预计算一次；
2. Segment循环内反复筛选全量assignment：改为稳定按Segment预分组；
3. projection/interpolate、参考区间和走廊证据逐对象调用：使用Shapely
   等价向量化并保留原排序与评分次序；
4. Junction surface、surface coverage和DriveZone buffered union反复构造：
   使用有界LRU或活动GeoDataFrame身份缓存，不改变几何；
5. Patch输入和输入清单串行I/O：仅对独立读取/哈希使用最多6个有界线程，
   输出仍按Patch和原输入顺序稳定合并。
