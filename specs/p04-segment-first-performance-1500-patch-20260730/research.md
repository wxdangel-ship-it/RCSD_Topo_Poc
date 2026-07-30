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
`perf_opt13_1885118_20260730T1300`：

- wall：`738.55s -> 159.72s`，降低约`78.4%`，提速约`4.62x`；
- process CPU：最终`115.41s`，平均进程CPU占用约`72.3%`；
- peak RSS：最终`526766080 bytes`，约`502.4MiB`；
- 正式结果：`887 Road / 1134 Node / 1933 RoadNextRoad`；
- independent QA：`0 violation`，QGIS `52`层回读通过；
- CRS：`EPSG:32650`；
- 正式、审计、关系、比较、独立QA和summary工件均通过
  T10语义指纹等价；只有输入manifest按设计从全目录文件改为实际消费文件。

优化后的P04专项测试为`278 passed`。以既有1532 Patch失败运行
`97689s`与同机6-Patch冻结基线做保守线性折算，候选约为`21127s`
（约`5.87h`）；该数字只是复跑候选估算，不替代约1500 Patch内网正式
复跑。`<=6h`目标与`<=8h`硬上限仍保持待验收。

## 5. 已确认热点与处理

1. Patch Road路径评分反复计算：改为每个候选路径预计算一次；
2. Segment循环内反复筛选全量assignment：改为稳定按Segment预分组；
3. projection/interpolate、参考区间和走廊证据逐对象调用：使用Shapely
   等价向量化并保留原排序与评分次序；
4. Junction surface、surface coverage和DriveZone buffered union反复构造：
   使用有界LRU或活动GeoDataFrame身份缓存，不改变几何；
5. Patch输入和输入清单串行I/O：仅对独立读取/哈希使用最多6个有界线程，
   输出仍按Patch和原输入顺序稳定合并。
6. 同一迭代内反复执行的中心线平滑、方向判定、参考投影和转角审计：
   以完整WKB及原参数作为精确有界缓存键；缓存满后按LRU淘汰，不保留
   全量Patch对象引用。
7. 路径评分中的小GeoDataFrame反复`fillna/to_numeric/astype`：
   改为等价标量归一，过滤规则仍为缺失/不可解析/非有限值不参与评分。
8. 8核机器的原生计算线程：正式入口默认将OpenBLAS/OMP/MKL/NumExpr和
   GDAL内部线程限制为1，P04 Patch独立I/O仍最多6 worker；显式外部配置
   可覆盖默认值，实际值进入summary。
9. RSS平台化证据：每30秒保留一个资源样本，8小时内最多960个、实现上限
   1024个；6-Patch从约`472MiB`进入全网阶段后基本平台化，最终输出阶段
   峰值约`502.4MiB`。
10. 跨平台资源采样：墙钟统一使用高分辨率`perf_counter`；Windows
    `GetProcessMemoryInfo`与`GetProcessIoCounters`显式声明64位进程句柄
    和参数签名，避免RSS/I/O被误报为`unavailable`。专项测试连续10次通过。

## 6. 1500 Patch输入规模基准

验证脚本：
`validation/benchmark_input_scale.py`。本地缺少内网1532 Patch正式数据，
因此使用1885118的6个真实Patch Vector，以目录联接循环映射为1500个独立
Patch；每份记录保留独立`source_patch_id`。验证覆盖P04实际消费的8类图层、
CRS转换、稳定拼接，以及12000个消费文件的SHA256清单，不执行后续业务构图。

`scale_input_1500_20260730T1400`实测：

- Patch：`1500`，真实数据复用倍数：`250x`；
- 消费文件：`12000`，清单逻辑总字节数：`2889003750`；
- 驻留记录：`3427750`；
- wall：`234.002s`，process CPU：`52.922s`；
- peak RSS：`1.513GiB`，通过`8GiB`目标和`16GiB`硬门槛；
- 最大图层为`1556500`条LaneBoundary，完成后RSS约`1.164GiB`，
  当时进程峰值约`1.411GiB`；
- GDAL只报告原始GeoJSON空坐标告警，`CPL_MAX_ERROR_REPORTS=100`
  按预期限制输出；无读取异常或进程崩溃。

该验证证明当前“读取全部正式消费输入并驻留”的输入阶段，在这一重复规模
下不会触发内存门槛。由于少量真实文件被重复使用，文件系统缓存和内容分布
均比内网正式全量有利，因此wall/I/O结果只作为偏乐观下界；它不证明后续
空间构图阶段的内存上限，也不替代内网约1500 Patch端到端复跑。

## 7. 最新候选监控修复后的业务等价复跑

在`c6928c5`上以正式入口复跑
`perf_opt14_1885118_20260730T1325`：

- wall：`151.777s`，process CPU：`114.049s`，平均进程CPU：
  `75.14%`；
- current RSS：`534609920 bytes`，peak RSS：`536612864 bytes`
  （约`511.8MiB`）；
- 正式结果：`887 Road / 1134 Node / 1933 RoadNextRoad`；
- independent QA：`0 violation`，16项独立gate全部通过；
- 与`perf_opt13`相比，正式GPKG、审计GPKG、关系GPKG、比较GPKG、
  独立QA GPKG/JSON和summary共7类业务工件的规范化语义指纹全部一致；
- input manifest唯一规范化差异为运行环境GeoPandas版本
  `1.1.3 -> 1.1.2`，不是输入路径、文件内容、参数或业务结果变化。

该复跑仍报告与冻结候选相同的`terminal_status=failed`、
`core_gate_pass=false`，未用性能优化或Review绕过既有POC业务hard gate。
