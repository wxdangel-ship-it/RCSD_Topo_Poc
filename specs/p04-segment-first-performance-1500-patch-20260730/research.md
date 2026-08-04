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

## 8. 内网验收器与资源合同闭环

新增只读验证脚本
`validation/validate_innernet_acceptance.py`，自动核对：

- 约1500 Patch范围和每Patch 8类正式消费文件；
- `<=6h`且不高于异常终止前12.7小时观测下界50%的目标、`8h`失败诊断线、
  `<=8GiB`目标和`<16GiB`硬上限；
- 指定8逻辑核、P04最多6个Patch I/O worker、原生计算线程均为1；
- 30秒资源时间线完整性、RSS尾部持续增长提示；
- CRS、独立QA、QGIS回读、正式工件完整性；
- 可选同输入参考的输入身份与7类业务工件规范化指纹。

验收器不允许把缺失证据静默升级：无同输入参考时最多返回
`EVIDENCE_READY`；只有全部自动gate和同输入业务等价均通过时返回
`ACCEPTED`。第三轮中超过6小时即失败，书面说明不能绕过门槛。

资源合同中的`patch_io_workers_max=6`现由
`segment_first_performance.py`单一常量同时驱动Patch读取、控制台日志和
summary，避免实现与审计口径漂移。

最新正式复跑`perf_opt15_1885118_20260730T1340`：

- wall：`150.900s`，peak RSS：约`514.1MiB`；
- 与`perf_opt13`输入身份及7类业务指纹完全一致；
- 带同输入参考执行验收器：`ACCEPTED`，失败gate为0；
- 不带参考执行验收器：`EVIDENCE_READY`，不会掩盖现有core gate复核；
- 验收器负向用例确认旧opt14仅因未记录I/O worker合同而失败；
- P04专项回归更新为`280 passed`。

## 9. 第三轮覆盖热点与真实进度证据

2026-08-02内网日志在`45759.2s`仍未完成，且后续进程异常终止；该时间是中间
观测下界而非完成耗时。CPU时间接近墙钟且调用栈持续落在`surface_coverage`。
第三轮最初实验了“原始DriveZone候选分片重新union后
局部求交”，但在5000条固定随机压力线中发现7条约`1e-11`量级的浮点差异；即使
实际1939条历史线恰好一致，该路径仍不满足逐值零回退合同，已经从正式数值和门槛
计算链移除。

最终采用两条安全路径：数值覆盖率只对最终`MultiPolygon`的原生不相交组件建索引，
不重组任何原始分片；布尔门槛先在完整最终surface上执行prepared
`covers/disjoint`，只有能够严格证明覆盖率为1或0时快速返回，边界相交样本仍回退
原始精确`intersection.length / line.length`。覆盖结果缓存受条目数和约`256MiB`
WKB预算约束，运行统计显式记录`terminal_fast`、`exact_fallback`和
`unsafe_local`。

`validation/benchmark_surface_coverage.py`以1500个离散surface分片、2000条
查询线验证：

- direct：`2.1875s`；indexed：`0.0439s`；热点加速`49.83x`；
- 精确差异记录`0`，最大绝对差`0.0`；
- `unsafe_local_reconstruction_count=0`。

同时以历史1885118正式成果保留的6条DriveZone、1939条真实Road carrier/
geometry source/Node connection线，再叠加5000条固定随机压力线进行回放。最终
surface为仅5个大型组件、32322个坐标的`MultiPolygon`：完整精确计算为
`7.4881s`，prepared门槛路径为`2.1206s`，加速`3.53x`；独立冷缓存数值路径为
`2.0597s`，加速`3.64x`。4540/6939条由`covers/disjoint`严格定论，541条命中
覆盖缓存，1858条回退原始精确计算。门槛判定差异、数值覆盖率差异和最大绝对差
均为`0`，`unsafe_local_reconstruction_count=0`。P04模块专项回归为
`288 passed`。

扩大到同一1500分片surface上的`50000`次查询后，完整精确计算为
`24.3426s`，索引实现为`0.7452s`，加速`32.66x`；50000次数值逐项完全一致，
最大绝对差`0.0`，缓存WKB仅约`2.05MB`，仍未发生不安全局部重构。这证明热点
收益不会只存在于2000次短微基准中，但仍不替代端到端内网墙钟验收。

正式入口现按真实对象发布Patch读取、Segment carrier、Junction portal、
Node/关系、独立QA、GPKG输出和QGIS图层的`completed/total`、吞吐、ETA与
累计计数；每30秒心跳同时输出资源、活动栈与覆盖索引收益，10分钟实际单位
不增长时报告`STALL WARNING`。完整事件最终保存为输出目录
`p04_progress.jsonl`，异常退出也保留`run_failed`事件。

以上只达到`INNERNET_CANDIDATE`证据层；冻结6-Patch数据当前不可用，且尚未
取得1532 Patch正式复跑，因此业务等价与`<=6h`/`<=50%`端到端验收仍待内网
完成，不得表述为总体目标已经达成。

## 10. 冻结产物反向重放的完整流水线证据

为在原始6-Patch Vector暂不可用时验证正式入口、进度链和输出链，使用历史
1885118冻结成果反向构造Patch级只读重放输入，并直接接入T10基线中真实的
T01/T03/T04/T07成果、T06目标可替换性成果以及原始SWSD/完整RCSD切片。
`artifact_replay_run3_1885118_20260802`完成了从输入读取到正式GPKG、审计GPKG、
关系GPKG、独立QA和QGIS工程回读的完整流水线：

- wall：`195.681s`，process CPU：`127.333s`，平均进程CPU：`65.07%`；
- peak RSS：`536928256 bytes`（约`512.1MiB`）；
- 正式结果：`887 Road / 1134 Node / 1939 RoadNextRoad`；
- independent QA：`0 violation`，16项独立gate全部通过；
- 进度事件包含`79`次完整阶段执行、`12`类阶段名和`6607`条实际单位推进事件，
  贯穿6类Patch并行读取、Segment、Junction、Node、Topology、QA、GPKG输出和
  QGIS回读，最终`run_completed`明确记录业务终态；
- 覆盖热点累计`14350`次数值查询，覆盖缓存命中`11528`次（`80.33%`）；
  门槛查询`7822`次，其中`7139`次命中门槛缓存；
  `unsafe_local_reconstruction_count=0`，精确性gate通过；
- 本地最重可见阶段为审计GPKG写出`16.95s`，其次为QGIS图层发现`7.95s`和
  比较GPKG写出`6.18s`；Segment carrier在不同业务处理轮次中重复执行，控制台
  以`stage_invocation`区分，不把重算轮次误报为同一进度倒退。

本次重放的`terminal_status=failed`、`core_gate_pass=false`，失败项为
`movement_anchor_rejection_zero`和`mandatory_target_high_precision_complete`；
其根因是Patch Road/LaneTopo/路口素材由历史发布产物反向构造，不能恢复原始证据
合同。该结果只证明候选实现能够完整执行、进度可审计、资源受控且不会绕过业务
hard gate；它不参与业务等价结论，也不替代1532 Patch内网端到端验收。其
`195.681s`与旧6-Patch正式复跑使用的输入不相同，不得直接解释为性能回退或收益。

初次完整重放同时暴露进度发布过密：`6607`条单位推进事件在195秒内集中写盘并
进入日志采样热点。保留每个实际单位的内存快照更新、每30秒心跳、每1%进展、
阶段开始/完成和运行终态合同，同时把快速阶段的1%落盘事件限制为最多每秒1条。
同输入复跑`artifact_replay_run4_1885118_20260802`得到：

- wall：`158.237s`，相对run3为`80.86%`，本地完整重放耗时降低`19.14%`；
- `p04_progress.jsonl`共`205`条事件，12类必需阶段全部覆盖，单位计数单调且
  `run_completed`存在；控制台30秒心跳仍能读取每单位更新的最新内存快照；
- peak RSS约`512.3MiB`，正式结果仍为
  `887 Road / 1134 Node / 1939 RoadNextRoad`；
- 与run3输入身份相同，正式GPKG、审计GPKG、关系GPKG、比较GPKG、独立QA
  GPKG/JSON和summary共7类业务工件的规范化语义指纹全部一致；
- 覆盖精确性、独立QA、QGIS回读、资源和进度gate全部通过，仍保留同样的两个
  反向构造证据业务hard gate失败，没有因节流掩盖业务终态。

run3到run4的`19.14%`只度量进度发布开销收敛，不是1532 Patch相对原始失败
基线的最终`<=50%`结论；后者仍必须以正式内网同输入复跑判定。

## 11. Segment carrier重复走廊装配收敛

异常终止前的内网日志反复落在`surface_coverage`和
`_completion_supported`，且同一Segment carrier在多轮网络协调过程中使用相同
Lane/Boundary/DriveZone证据重复装配方向走廊。第三轮继续增加精确值缓存：缓存键包含
全部证据值和几何WKB、参考几何、方向、DriveZone对象身份及所有阈值；命中只返回
不可变`CorridorAssembly`，不改变候选、阈值或fallback业务语义。缓存同时受
`32768`条和`64MiB`键数据双上限约束，并在每次正式入口启动时清空。

同输入重放`artifact_replay_run7_1885118_20260802`得到：

- 走廊装配查询`8633`次，命中`7925`次，命中率`91.8%`；终态`708`条、
  键数据`588201 bytes`（约`0.6MiB`）、`0`次淘汰，未触及配置上限；
- 覆盖率数值查询由run4的`14350`次降至`11292`次；run5中重复carrier阶段累计
  由约`36.10s`降至`30.07s`，降低约`16.7%`；
- run7 wall为`154.628s`、CPU为`112.655s`、peak RSS为`539127808 bytes`
  （约`514.2MiB`）。相对run4 wall降低`2.28%`、CPU降低`4.50%`；运行期间机器
  另有一个约`3GiB RSS`的高CPU Python进程，wall只作为受并发干扰的本地参考；
- 进度流`206`条事件，12类必需阶段齐全、单位单调、运行终态存在；控制台可见
  `stage_invocation`、`completed/total`、百分比、速率、ETA、业务计数、覆盖缓存和
  走廊缓存收益，不再只有累计时间；
- 相对run4，正式、审计、关系、比较、独立QA GPKG、独立QA JSON和summary共
  7类业务工件的规范化语义指纹全部一致；独立QA、QGIS回读、覆盖精确性和有界
  缓存gate全部通过。

本地重放使用历史发布产物反向构造的6-Patch证据，因此两个业务hard gate仍按预期
失败。验收器显式收窄为6-Patch时得到的`ACCEPTED`只表示这组局部技术gate和同输入
指纹成立，不能替代约1532 Patch正式内网验收，也不能把`45759.2s`误写为已完成
基线；该数字仅是异常终止前已经发生的墙钟观测下界。

## 12. Target path重复评分收敛

对完整6-Patch重放执行函数级`cProfile`后，13轮`plan_segment_carriers`
累计`58.193s`；其中`_select_directed_target_path`调用`1818`次、累计
`10.694s`。该函数对相同Segment证据反复执行GeoDataFrame分组、显式Road pair
过滤、端点面距离和最多10000条路径评分。优化采用独立P04内部模块缓存最终选中的
`patch_road_key`不可变元组，不缓存GeoDataFrame；键包含证据几何WKB、assignment
评分、完整RCSD锚定支持、参考线、端点面、距离阈值和显式pair内容摘要。缓存按
`32768`条和`64MiB`键数据双上限约束，并在正式入口启动时清空。

同输入未剖析重放`artifact_replay_run9_1885118_20260802`得到：

- 路径查询`1609`次，命中`1432`次，命中率`89.0%`；终态`177`条、键数据
  `473821 bytes`，显式pair签名数据`370448 bytes`，`0`次淘汰；
- Segment carrier累计由run7的`30.295s`降至`25.637s`，降低`15.38%`；
- wall由`154.628s`降至`148.330s`，降低`4.07%`；process CPU由
  `112.655s`降至`107.242s`，降低`4.80%`；peak RSS由`539127808 bytes`
  变为`538906624 bytes`，未增加峰值；
- 相对run7的7类业务工件规范化语义指纹全部一致，正式结果仍为
  `887 Road / 1134 Node / 1939 RoadNextRoad`；
- 新增`target_path_cache_bounded`验收硬门槛，完整P04测试为`298 passed`。

该收益仍是本地6-Patch反向构造证据的技术回归，不能线性外推为约1532 Patch的
完成时间。正式内网运行必须同时观察`path_cache`命中率、淘汰数、键内存、实际
Segment carrier进度、RSS曲线和最终业务指纹，才能确认全量收益与资源安全。

## 13. Movement物理切分阶段的可见进度

函数级剖析还显示，`_split_physical_carriers`内部的Movement anchor切分和
Segment access切分可能形成持续数十秒但只有心跳时间增长的不可见区间。为此在
不改变候选、几何或拓扑条件的前提下，新增两个实际工作量阶段：

- `movement_anchor_split`：总量为显式movement pair数加carrier数，分别推进
  anchor判定和carrier物理切分，并发布接受/拒绝anchor、请求切分父Road、实际
  切分父Road、切分片段和输出行数；
- `segment_access_split`：总量为待处理carrier数，发布端点路口面裁切、THROUGH
  access接受/拒绝、切分父Road、切分片段和输出行数。

同输入重放`artifact_replay_run10_1885118_20260802`中，两阶段各执行`13`轮：

- `movement_anchor_split`共`26`条阶段事件，`segment_access_split`共`27`条；
  每轮均存在开始/完成事件，完成量等于总量，所有单位计数单调不回退；
- 第一轮可直接看到`movement_anchor_split 4852/4852`，其中`4159`个pair、
  `693`条carrier、`120`个接受anchor、`2`个拒绝anchor、`46`条父Road实际切分；
  随后可看到`segment_access_split 758/758`，其中`831`个access、`147`个接受
  anchor、`840`个拒绝anchor、`116`条父Road切分、输出`900`行；
- wall为`135.821s`，process CPU为`103.485s`，peak RSS为`539230208 bytes`
  （约`514.2MiB`）；这些数值仅作本地运行参考，不能把新增进度本身解释为性能收益；
- 相对run9，正式、审计、关系、比较、独立QA GPKG、独立QA JSON和summary共
  7类规范化业务指纹全部一致，仍为`887 Road / 1134 Node / 1939 RoadNextRoad`；
- 验收器在显式收窄到6-Patch时通过全部局部技术门禁，包括进度、资源、缓存、
  独立QA、QGIS回读和业务零回退。该`ACCEPTED`不是约1532 Patch正式验收；
  `45759.2s`仍只表示异常终止前已观测墙钟下界，不能作为已完成运行时长。

## 14. Movement carrier重复选择收敛

`movement_anchor_split`的每一轮输入含`4159`条显式movement pair，每条pair都会
分别按source end和target start选择carrier。carrier集合、Patch几何、Segment归属
和评分条件在全部pair判定期间均不变化，因此相同`(patch_road_key, endpoint)`的
重复选择可以在单轮函数作用域内严格复用。实现同时缓存命中carrier和`None`结果，
不跨轮保留、不缓存GeoDataFrame、不改变候选顺序、角度、距离、tie-break或阈值。

同输入重放`artifact_replay_run11_1885118_20260802`得到：

- 13轮累计选择查询`108134`次，单轮缓存命中`34541`次，命中率`31.94%`；
- `movement_anchor_split`累计由run10的`9.770s`降至`8.740s`，降低约`10.54%`；
- wall由`135.821s`降至`132.878s`，降低约`2.17%`；process CPU由
  `103.485s`降至`100.039s`，降低约`3.33%`；peak RSS由`539230208 bytes`
  降至`538009600 bytes`，没有增加峰值；
- 相对run10，7类规范化业务工件指纹全部一致，正式结果仍为
  `887 Road / 1134 Node / 1939 RoadNextRoad`；
- 独立QA为0 violation，QGIS回读、进度、资源、精确覆盖和有界缓存门禁全部通过；
  完整P04专项测试为`299 passed`。

随后将函数内缓存显式限制为`32768`条；达到上限时按插入顺序淘汰旧结果，命中与
淘汰都只决定是否重算，不参与carrier评分。`artifact_replay_run12_1885118_20260802`
中13轮最大单轮条目数为`5661`、累计淘汰`0`，新增
`movement_carrier_selection_cache_bounded`验收硬门槛逐轮检查
`0 <= entries <= configured max`及非负淘汰数。run12相对run11的7类业务指纹仍
全部一致，完整P04专项测试更新为`300 passed`。run12 wall为`138.576s`，高于
run11的`132.878s`，而同一阶段为`9.225s`；这组波动再次说明不能用单次本地总墙钟
推导正式1532 Patch收益，容量合同与业务等价才是该次复跑的验证目标。

本地总体墙钟仍会受到输出I/O和机器并发波动影响，因此只把单阶段下降、CPU下降和
同输入指纹一致作为该优化的技术证据。它仍不能替代约1532 Patch正式内网终态，
也不能将异常终止前`45759.2s`中间观测下界解释为已完成基线。

## 15. 1532 Patch首轮carrier热点与高组件终态优化

用户停止的第二次1532 Patch正式运行在`elapsed=12069s`时仍处于首轮
`segment_carrier#1`，实际完成`8662/46399=18.7%`，阶段ETA约`6h33m`。
该时点RSS约`6.25–6.39GiB`、峰值约`6.70GiB`，没有超过资源预算；但覆盖统计为
`queries=15722`、`cache_hit=35.3%`、`exact_fallback=10165`、
`terminal_fast=0`，活动栈持续落在`_surface_intersection_length`。这证明大范围
最终DriveZone进入高组件`MultiPolygon`索引后，旧实现跳过了完整终态快速判定，
使本可由原生组件严格证明为全覆盖或完全不相交的样本也进入昂贵精确叠加。

本轮只增加业务等价路径：空间索引仍只来自最终`MultiPolygon`的原生组件；候选
原生组件经prepared `covers/disjoint`严格证明覆盖率为1或0时提前返回，不能证明时
仍执行原有精确`intersection.length`。没有重组原始DriveZone分片，没有近似覆盖率，
`unsafe_local_reconstruction_count`保持0。8组件、其中一个组件约50001坐标的固定
压力样本中，2000条线的直接精确叠加为`8.0787s`，优化路径为`0.0338s`，加速
`238.97x`；逐值最大绝对差为`0.0`。该收益对应全量日志暴露的“少量超复杂原生
组件”形态，不以简单1500矩形微基准替代。

现有`validation/benchmark_surface_coverage.py`已增加可重复的
`complex-component`场景。正式复跑使用1500个最终原生组件、其中主组件约50001个
坐标、2000条固定随机线：direct为`5.6874s`，候选为`0.0366s`，加速
`155.40x`，逐值差异数和最大绝对差均为0；原有`separated-components`场景为
`1.2241s -> 0.0288s`，加速`42.54x`，同样逐值零差异。两类报告保存在本地
`outputs/_work/p04_road_direct_generation/perf_v2_benchmarks/`，不作为正式发布工件。
扩大到与全量首轮`46399`个Segment同量级的50000次复杂组件查询后，direct为
`142.5982s`，候选为`0.6822s`，加速`209.03x`；50000个覆盖值逐项一致、最大绝对
差为0，仅准备1个实际命中的复杂原生组件，覆盖缓存WKB约`2.05MB`，远低于
`256MiB`预算。

Patch Road居中阶段此前被包含在已显示100%的输入阶段之后，控制台无法判断真实
进度。现新增`patch_road_center`阶段，按Patch Road输出`completed/total`、
`centered/without_lane/relations`与当前`patch_road_key`。中心横断面仍按5米采样、
相同切向量、相同Lane投影、相同中位数和相同2米偏移线采样，仅把Shapely逐点调用
改为同一GEOS函数的数组调用。固定曲线样本中偏移值和最终几何WKB逐位一致，热点
约加速`1.45x`。

同时验证过最多6线程并行居中，但在同一120条复杂Road样本中，串行为`4.0100s`，
6线程为`64.9119s`，性能下降约16倍；结果WKB虽完全一致，但GEOS/线程争用会增加
CPU与内存风险，因此该并行路径未进入正式实现。Patch读取仍使用既有最多6 worker，
几何居中保持单进程批量GEOS计算。

最终完整重放`artifact_replay_run14_perf_v2_final_1885118_20260802`与最新P04 schema基线
`artifact_replay_schema_baseline_1885118_20260802`使用相同6-Patch输入：

- 基线wall为`140.5s`，候选wall为`135.0109s`，候选peak RSS为`543195136 bytes`；
- 正式Road/Node/RoadNextRoad仍为`887/1134/1939`，独立QA为0 violation，
  QGIS 50层回读通过；
- 正式、审计、关系、比较、独立QA GPKG、独立QA JSON和summary共7类业务工件
  规范化指纹全部一致；
- 进度事件包含`patch_road_center 1015/1015`；覆盖审计记录
  `native_component_prepare_count=2`，控制台同步显示`prepared_parts`；验收器已将
  Patch Road居中阶段列为必需门禁；
- P04专项测试为`305 passed`。

6-Patch最终DriveZone只有5个大型组件，旧实现已经走完整surface prepared路径，
因此其约`2.4%`墙钟变化只用于业务零回退和端到端可运行性验证，不能衡量新的
高组件路径。当前结论仍为`INNERNET_CANDIDATE`；只有同一1532 Patch正式输入完成
全程且`<=6h`、资源受控、业务指纹一致，才能升级为`ACCEPTED`。

## 16. 第四轮逐Segment dirty-set与静态索引复用

run14的135.0109秒中，`segment_carrier`共执行13轮、累计处理4290个Segment单位；
函数级剖析还显示Movement切分、Node构建和未归因编排成本在Carrier优化后占比上升。
第四轮从`main@2f369c2`建立隔离分支，并先按文件体量治理拆分原
`segment_first_pipeline.py`：主编排文件由100510 bytes降至约88KB，输出关系与审计
辅助函数迁移到独立子模块，正式入口和公开数据合同不变。

逐Segment规划指纹覆盖assignment全部字段和几何、target reference axis、恢复候选
全局预留、端点面救援、强制保留/抑制、THROUGH access及方向角色。首次或静态上下文
变化时全量重算，后续只对指纹变化Segment调用原规划器；未变化结果按原Segment顺序
合并，逐Segment汇总贡献重新相加。为避免增量DataFrame合并改变审计schema，还保留
原规划器逐Segment字段首次出现顺序，并据此重建最终Carrier字段集合与顺序。

冻结6-Patch `artifact_replay_dirtyset_v3_run08_through_dirty_1885118_20260802`证据：

- wall `114.5304s`，相对run14的`135.0109s`降低`15.17%`；process CPU约`81.6s`，
  peak RSS约`520.6MiB`；
- THROUGH surface只按`segment_id`参与原Carrier规划，因此将其从对象级静态token
  下沉到逐Segment完整属性/几何指纹；第2轮由330个全量重算收敛为211个dirty、
  119个复用；
- 13轮Carrier中1轮全量、12轮增量；累计`860`个Segment重算、`3430`个复用，
  复用率`80.0%`；
- 指纹对象缓存命中`30/51`，Movement静态证据索引首轮构建、后续12轮复用；
- 正式Road/Node/RoadNextRoad仍为`887/1134/1939`，独立QA为0 violation；
- 正式、审计、关系、比较、独立QA GPKG、独立QA JSON和summary共7类业务工件，
  相对run14规范化语义指纹全部一致；
- 总体进度新增6阶段单调`overall_estimate`，动态网络重试仍以每轮实际
  `completed/total`和Carrier复用计数解释，不伪造剩余轮数。
- P04全量专项测试为`311 passed`；源码、脚本和测试均低于100000 bytes，原超限
  pipeline拆分已同步登记到代码体量审计。

旧1532 Patch日志在进入首轮Carrier前长期采样到
`segment_first_junctions.py:_retained_junction_kind`与`canonical_id`。审计确认旧实现会
对每个无accepted surface的Junction group重新扫描、规范化整张T01 Node表，复杂度为
`O(Junction group × Node)`。候选改为一次扫描建立`kind_2=128`对应的Node ID和
mainnodeid集合，随后按group做O(1)查询；判定规则与字段语义不变。12000 Node、6000
group固定压力样本从`94.0669s`降至`0.0090s`，6000项判定差异为0。最终6-Patch
run09的7类业务工件相对run14指纹仍全部一致，并新增
`junction_unit_retained_groups`真实进度阶段和验收门禁。run09小样本wall受固定写盘/QGIS
波动影响为`122.8778s`，因此保留run08的`114.5304s`作为小样本最佳墙钟证据；正式
候选代码则包含本项只在全量Junction规模显著获益的索引优化。

6-Patch包含约22秒固定GPKG写出和约6秒QGIS图层发现，因此其总墙钟不会按Carrier
复用率等比例下降。第四轮仍只能定级为`INNERNET_CANDIDATE`；1532 Patch是否达到
`<=6h`与异常终止前观测下界的减半目标，必须由内网同输入完整运行确认。

## 17. 剩余规模扫描、Target fragment进度与最新候选

第四轮继续审计了全量日志中可能在首轮Carrier前后放大的全表扫描：

- retained Junction kind已由`Junction group × T01 Node`改为一次Node集合索引；
  12000 Node、6000 group固定样本为`94.0669s -> 0.0090s`，6000项结果零差异；
- ADVANCE_RIGHT skeleton在缺失pair node时原来每个Access都扫描全部scoped Road，
  现一次建立Road起终点索引。12000 Road、1500次查询含建索引成本为
  `7.889s -> 0.2037s`，结果零差异；
- access surface恢复原来对每个目标Segment扫描全部Patch Road center并重复扫描
  endpoint Access，现先按Segment聚合Access，再用空间索引取得端点面扩展包围盒候选，
  最终仍执行原距离、最大距离、裁切长度、DriveZone覆盖和冲突门槛。400 Segment、
  10000 center固定样本为`1.7434s -> 0.01668s`，均得到400对候选且结果零差异。

完整流水线`cProfile`回放用于剩余热点排序，剖析插桩把正常运行放大到约202秒，不能
作为验收wall。累计时间主要落在16轮Node构建约33.7秒、GPKG写出约23.7秒、Evidence
约19.1秒、dirty-set后的Carrier规划约18.8秒、Movement access切分约16.6秒和Junction
carrier约14.2秒。正常6-Patch进度统计中16轮Node构建累计仅约5.4秒，固定GPKG写出约
23.9秒，因此当前全量首要风险仍是首轮Carrier与Evidence的规模项，而不是本地固定
输出I/O。Node阶段保留为后续全量剖析观察项，不在缺少1532 Patch证据时改写业务固定点。

Target fragment此前位于`patch_road_center`完成和access recovery开始之间，6-Patch存在
约8.9秒不可归因区间，全量可能形成新的进度盲区。现新增
`target_fragment_assignment#1/#2`，分别报告Patch Road和Lane的
`completed/total`、fragment数和命中source数；空间索引粗筛使用与原buffer包围盒等价
或更保守的扩展包围盒，后续仍执行原站点距离、角度、方向member和排序条件。20000次
合成粗筛为`0.3266s -> 0.2346s`，约`1.39x`；扩展包围盒多出的5个粗筛候选均超过
35米精确距离门槛，不进入语义结果。最终等价性以完整业务产物为准。

最新正常回放
`artifact_replay_dirtyset_v3_run13_fragment_progress_1885118_20260802`的正式流水线wall为
`122.7s`、process CPU约`87.9s`、peak RSS约`521.9MiB`。两个Target fragment阶段分别为
`1015/1015，2.219s，799 fragments`和`2188/2188，3.687s，1295 fragments`。相对冻结
run14，正式、审计、关系、比较、独立QA GPKG、独立QA JSON和summary共7类业务工件
指纹全部一致；独立QA为0 violation，QGIS 50层回读通过，进度阶段完整，P04专项测试为
`312 passed`。本地最佳wall仍保留run08的`114.5304s`，因为固定写盘与机器波动使单次
小样本总wall不适合排名。

当前结论仍为`INNERNET_CANDIDATE`。1532 Patch完成前不能把局部验收器显示的
`ACCEPTED`解释为全量目标达成；正式升级必须同时满足`<=6h`、不高于异常终止前观测
下界50%、峰值RSS和CPU受控、所有实际进度阶段完成、同输入业务零回退。

继续逐次记录16次Node构建的完整Road内容、semantic endpoint集合和已物化普通路口组后，
只有第3次构建与第1次输入完全一致：两次均为900 Road、空semantic集合和250个已物化
group；第2次是14个semantic endpoint的探测构建，其余调用的Road token、semantic集合
或materialized group均发生变化。根因是初始`endpoint_trim_segment_ids`已经包含全部
`core_trunk/advance_right`，probe失败ID又先与`core_target_ids`相交，因此追加集合必然
是既有集合的子集；旧流程仍以“集合非空”而非“新增差集非空”触发完整重建。

候选改为只在`probed - existing`非空时重做Movement切分、网络几何物化和Node构建；
若未来出现真正新增ID，仍走原完整路径。冻结6-Patch
`artifact_replay_dirtyset_v3_run15_skip_redundant_endpoint_rebuild_1885118_20260802`中，
Movement anchor和Segment access切分由13轮降为12轮，Node构建由16轮降为15轮；三类
阶段累计时间相对run13约减少`0.496 + 0.673 + 0.627 = 1.796s`。正式流水线wall为
`121.6s`、CPU约`85.8s`、peak RSS约`519.9MiB`；相对冻结run14的7类业务工件指纹全部
一致，独立QA和QGIS回读继续通过，`312 passed`。其余Node调用不存在严格重复输入，
不能继续按相同理由删除；若全量复跑证明Node成为主热点，必须按受影响Segment及
Junction原子范围另行设计，而不是复用不同输入的全网结果。

Carrier原规划器即使只接收dirty Segment，仍会在每轮重复复制和分组完整SWSD Road、
assignment、reference axis、THROUGH/ENDPOINT surface；access-support还会对每条候选
片段遍历所有其他Segment的reservation，并在内层重复执行`buffer(1.0)`。候选现增加
单次run弱引用上下文：对象和DataFrame manager均相同时复用，每类上下文只保留一个
存活条目，输入变化前先释放旧值。reservation使用与旧逻辑相同的1米buffer预计算，
空间索引只做粗筛，最终仍计算原intersection length比例并排除当前Segment。

2000条reservation、200条固定候选的压力样本中，旧全表扫描为`6.0620s`，预缓冲、
建索引和全部查询合计`0.04128s`，加速约`146.86x`，200项最大绝对差为0。最新完整回放
`artifact_replay_dirtyset_v3_run16_carrier_context_1885118_20260802`中，Carrier静态上下文
命中`50/64`，准备耗时`0.443s`，运行结束存活条目为0，证明没有把中间大表跨流水线
生命周期保留；`segment_carrier`累计为`8.286s`。正式流水线wall为`115.1s`、CPU约
`81.6s`、peak RSS约`531.4MiB`，相对run15的`121.6s`下降约5.3%，但仍只作为同机
小样本技术证据。相对冻结run14的7类业务工件指纹全部一致，独立QA、QGIS回读和新增
`carrier_static_context_cache_active`门禁通过，完整P04专项测试为`316 passed`。

## 18. 后静态上下文函数剖析与Node邻域查询收敛

为避免把心跳采样位置误当成累计热点，使用与run16相同的6-Patch输入执行完整
`cProfile`，并将统计固化为
`outputs/_work/p04_road_direct_generation/p04_dirtyset_v3_run18_post_context.pstats`。
剖析运行wall为`181.9s`、profile累计为`188.8s`，明显高于非剖析run16的
`115.1s`，因此该结果只用于函数排序。累计时间主要为：15轮Node构建`30.17s`、
5个GPKG写出`22.64s`、12轮物理切分`22.25s`、13轮增量Carrier`21.94s`、
Evidence`19.41s`、29次路口端点解析`17.42s`、14轮Junction carrier`12.69s`和
Target fragment`10.45s`。全程约`4.18亿`次函数调用，说明1532 Patch仍存在
DataFrame逐行访问和重复几何调用的规模风险，不能由6-Patch局部验收推断全量达标。

Node剖析显示端点邻域聚类和完整RCSD Node近邻查找共执行约`11.3万`次
`Point.buffer()`，随后又执行原精确距离判断。候选改为GEOS空间索引
`predicate="dwithin"`取得同一距离门槛候选，并保留原`distance <= threshold`和
全部Road/endpoint/Junction过滤；同时把同一轮endpoint的geometry、road_id和
endpoint字段转换为只读数组，避免候选内重复`iloc`。10000点、5000次固定查询的
微基准中，buffer加精确距离为`0.1449s`，dwithin为`0.0226s`，候选计数均为`44402`，
约加速`6.4x`。

路径校验还对同一批输入执行了多轮`resolve/stat/lstat`。配置对象现在只解析一次路径，
重叠检查在已解析绝对路径上执行`relative_to`，仍保留输入存在、新/空输出目录和
输入输出不得重叠的全部合同。正常run19为`111.0526s`、CPU`78.08s`、peak RSS
`556445696 bytes`，相对run16的`115.1106s`下降`3.52%`；15轮Node累计由
`4.78s`降至`4.43s`。run19相对冻结run14的正式、审计、关系、比较、独立QA GPKG、
独立QA JSON和summary共7类规范化业务指纹全部一致，独立QA为0 violation、QGIS
50层回读通过，本地验收器在显式6-Patch范围内返回`ACCEPTED`，完整P04专项测试为
`316 passed`。

该本地`ACCEPTED`只证明同输入小样本零回退和证据完整，不是1532 Patch时限验收。
按Patch数直接线性外推run19约为`7.88h`，虽会把固定GPKG/QGIS成本重复放大，也可能
低估全量Carrier、Node、Target fragment及审计输出行数增长。当前定级继续保持
`INNERNET_CANDIDATE`；正式结论必须等待同一1532 Patch完整运行证明绝对`<=6h`、
峰值RSS/CPU受控、全部实际进度阶段闭环并通过同输入业务指纹核验。

## 19. ADVANCE_RIGHT显式关系二次枚举收敛

后剖析还暴露`compile_road_next_road`的ADVANCE_RIGHT补充关系会把全部incoming Road
与全部outgoing Road做笛卡尔积，6-Patch已调用`_is_advance_right_pair`约118万次。
该阶段的既有业务门槛要求双方evidence key必须命中`allowed`显式关系对，因此先按
target evidence key建立outgoing位置索引，再按source evidence key只取可显式支持的
target；候选仍按原outgoing位置排序，后续继续执行原Road ID去重、ADVANCE_RIGHT
判定、显式支持复核、Node/Junction kind、mainnode和relation去重条件。

1500 incoming、1500 outgoing、1500个固定显式关系的压力样本中，旧笛卡尔积为
`0.3993s`，倒排候选为`0.00293s`，两者均输出33个有序关系且整体哈希一致，约加速
`136x`。正常run20中`topology_advance_right`从run19约`0.29s`降至`0.0073s`，
1090个incoming只枚举1988个显式候选，最终RoadNextRoad仍为1939；总wall为
`110.7892s`、peak RSS为`557694976 bytes`。run20相对冻结run14的7类业务工件指纹
全部一致，独立QA零异常、QGIS 50层回读和本地验收通过，P04专项测试更新为
`317 passed`。

该优化消除了Road总量平方增长的明确风险，但不替代1532 Patch正式运行。当前全量
剩余主风险集中在首轮46399 Segment Carrier的证据密度与复杂道路面、Patch Road/Lane
分片吞吐、以及多层审计GPKG的输出行数和挂载盘写入速度。

## 20. Patch读取期输入身份融合

正式输入会先按8类图层读取每个Patch，旧流程在全部读取完成后又逐文件执行一次
SHA256，约1532 Patch会再次顺序读取12256个Patch文件，且这段工作没有独立进度。
候选在每个图层I/O worker完成`gpd.read_file`后立即记录同一路径的大小和原始字节
SHA256；最终清单继续按原`Patch外层 × 图层内层`顺序组装，清单阶段只散列11个外部
输入。若不传预计算行，通用`build_input_manifest`仍保留原散列路径。

单元测试证明融合前后`files`、`input_file_count`、`input_total_bytes`完全一致，并通过
调用跟踪确认清单阶段不再散列Patch文件。run21中8个`input_patch_layer`阶段各记录
`hashed_files=6`，新增`input_manifest`阶段为`59/59`，其中48个Patch文件直接复用、
只新散列11个外部输入。run21相对冻结run14的输入身份和7类业务工件指纹完全一致。
6-Patch总wall为`113.3858s`，小样本不能量化1532 Patch消除第二遍挂载盘I/O的收益。

## 21. 路口面内缩目标精确有界缓存

最新run22函数剖析仍观察到`interior_surface_target`被调用17303次；它对同一accepted
surface和同一inset重复执行负向buffer，是Node、Junction carrier和端点补全共同触发
的规模项。候选以`surface WKB + 原inset`为精确键缓存原buffer结果，不做简化、取整
或阈值变化；缓存逐run清空，最多8192项且键预算32MiB，超限按LRU淘汰。控制台、
summary和验收器发布查询、命中、条目、键字节及淘汰计数。

run23共17303次查询，命中15750次（`91.02%`），仅保存1553项、键占`4406692`
bytes、零淘汰。正常wall为`110.2729s`、CPU为`78.03s`、peak RSS为`568053760`
bytes；相对无此缓存的run21，wall下降约`2.75%`、CPU下降约`3.02%`，峰值RSS增加约
`9.63MiB`且仍远低于8GiB目标。run23相对冻结run14的7类规范化业务指纹全部一致，
独立QA零异常、QGIS 50层回读和所有有界缓存门禁通过，完整P04专项测试为
`320 passed`。当前定级仍为`INNERNET_CANDIDATE`，只有1532 Patch完整运行才能裁定
6小时、资源和业务零回退目标。

## 22. Patch同源CRS批投影

8类Patch图层原来在每个GeoJSON读取后分别执行`to_crs`和逐geometry的2D转换，
1532 Patch会形成12256次独立投影初始化。真实6-Patch、全部8类图层微基准确认所有
源CRS一致时，可以先按原Patch顺序稳定拼接，再执行一次`to_crs`和Shapely批量
`force_2d`；若发现混合CRS，则自动回退原逐文件路径。字段顺序、dtype、非几何值、
CRS和geometry WKB均逐项一致。

8类图层合计从`3.1040s`降至`2.0816s`，约`1.49x`；Road图层单项约`2.68x`。
run24的8个`input_patch_layer`阶段均记录`crs_transform_batches=1`和
`shared_source_crs=true`，合计由run23的`5.32s`降至`3.72s`，减少`30.1%`。
正式流水线wall为`108.1228s`、CPU为`75.53s`、peak RSS为`566870016 bytes`；
相对冻结run14的输入身份和7类业务工件规范化指纹全部一致。

## 23. WSL挂载盘GeoPackage原子分段落盘

run22剖析显示5次GeoPackage写出累计约23秒。相同43层、48058368 bytes审计GPKG
在`/mnt/e`直接写为`15.1794s`，写入WSL本地`/tmp`为`3.5336s`；本地写完后以
`copy2`复制到挂载盘总计`3.9292s`，43层字段、dtype、非几何值和geometry WKB完全
一致。候选在WSL `/mnt/<drive>`输出时自动使用本地临时目录，写完复制到输出目录下
隐藏partial文件，再以`os.replace`原子发布；临时盘不可写或空间不足时自动回退原
直接写盘，不改变正式入口参数和输出位置。

run25中5次`output_gpkg_layers`全部记录`staged=true`，正式、审计、关系和比较GPKG
均发布`copied_bytes`且无partial残留。输出阶段由run24的`22.64s`降至`6.96s`，减少
`69.3%`；正式流水线wall为`97.6005s`、CPU约`77.3s`、peak RSS为
`568905728 bytes`。同输入7类业务工件指纹、独立QA和QGIS 50层回读全部一致。

## 24. Patch GeoJSON本地临时盘解析与读取期SHA256融合

内网旧日志中8类Patch输入完成耗时约`5221s`，对应1532 Patch、12256个GeoJSON。
即使读取worker已同步捕获SHA256，GDAL仍在DrvFS上解析小文件。候选在WSL挂载盘输入
上把每个文件单次流式复制到本地临时盘，并在同一字节流内计算SHA256，随后由GDAL
解析本地副本；每个图层最多6个并发临时文件，图层结束立即清理。临时盘不可用、
可用空间低于2GiB或显式禁用时回退原路径。输入清单继续记录原始路径、原始大小和
相同SHA256，不把临时路径写入业务或审计成果。

48个真实GeoJSON、合计6539025 bytes微基准中，直接`read_file + sha256`为
`2.4708s`（热缓存复测`2.0694s`），本地分段复制、同步哈希和解析稳定为
`1.6630s/1.6619s`，字段、CRS和geometry WKB逐项一致。run27的8类输入阶段全部记录
`staged=true`和逐层`staged_bytes`，合计由run25的`4.28s`降至`3.37s`，减少
`21.3%`。正式流水线wall为`87.6493s`、CPU约`69.6s`、peak RSS为
`565596160 bytes`，7类业务工件指纹、独立QA和QGIS回读继续完全一致。

## 25. Target fragment站点矩阵批处理与本轮结论

run26去除旧GPKG写盘噪声后的cProfile累计为`151.916s`，只用于函数排序：15轮Node
构建约`22.60s`、12轮物理切分约`21.30s`、13轮增量Carrier约`20.84s`、Evidence
约`18.35s`、路口端点解析约`16.19s`、Junction carrier约`11.97s`和Target fragment
约`9.87s`。正式非剖析run不使用这些放大后的绝对时间作为验收值。

Target fragment原来对同一source line的每个站点分别构造点、切向和全部候选距离。
候选改为一次生成全部站点、切向和`candidate axis × station`距离矩阵；每个站点仍按
原距离、角度、source priority、Segment和member顺序执行原选择。3203条真实Road/Lane
证据的函数微基准为`2.7053s -> 2.1573s`，约`1.254x`，所有station label、fragment
属性和geometry WKB零差异。run28的两个`target_fragment_assignment`阶段合计由run27
的`5.71s`降至`4.85s`，减少`15.1%`；正式流水线wall为`90.4093s`、CPU约`72.6s`、
peak RSS为`568598528 bytes`。端到端高于run27约2.76秒属于其余阶段和挂载盘抖动，
不能覆盖Target fragment的阶段级实测收益。

run28相对冻结run14的输入身份、正式Road/Node/RoadNextRoad及其余7类业务工件规范化
指纹全部一致；独立QA为0 violation，QGIS 50层回读通过，完整P04专项测试为
`325 passed`。按Patch数直接线性外推run28约`6.41h`，该数字既重复放大固定QGIS/GPKG
成本，也可能低估全量Segment、Node和审计行数的非线性增长，因此只说明当前仍没有
足够安全裕量，不能作为全量验收。候选继续定级`INNERNET_CANDIDATE`；必须由内网同一
1532 Patch正式入口完整运行证明`<=6h`、不超过`8h`失败诊断线、CPU/RSS受控、全部
进度阶段闭环和同输入业务零回退。

## 26. Movement固定点静态上下文复用

run26显示12轮`segment_access_split`会反复对同一`segment_accesses`按ENDPOINT和
THROUGH分组，并对同一`junction_units`重复提取`junction_source`。这些对象在单次
流水线内是只读输入，旧实现只缓存了聚合路口面，没有缓存分组结果和source映射。
候选以DataFrame identity和manager identity作为失效条件，第一次构建后复用
ENDPOINT去重分组、THROUGH分组、路口面和source映射；任何DataFrame或manager变化
都重新精确构建，不以内容近似键跨对象复用。

run29中第1轮为cache miss，第2至12轮全部命中。12轮`segment_access_split`合计由
run28的`7.1592s`降至`5.5488s`，减少`22.5%`；`movement_anchor_split`同时由
`4.2251s`降至`4.1472s`。正式流水线wall为`91.3385s`、CPU约`72.4s`、peak RSS为
`574996480 bytes`。端到端比run28增加约0.93秒，来自输入、GPKG和QGIS阶段合计抖动，
不能据此否定目标阶段的实际收益，也不能表述为端到端加速。

run29相对冻结run14的输入身份和7类业务工件规范化指纹全部一致，独立QA为0
violation，QGIS 50层回读通过，完整P04专项测试为`326 passed`。当前继续定级为
`INNERNET_CANDIDATE`；1532 Patch完整运行仍是6小时、8小时诊断线、资源和业务零回退
的唯一正式性能验收。

## 27. Movement静态端点上下文与Carrier行索引

每轮`movement_anchor_split`已经对`(patch_key, endpoint)`做本轮选择结果缓存，但12轮
固定点仍会重复计算同一Patch evidence端点、Patch切向，并为每个候选执行DataFrame
`.loc`。Patch evidence对象在run内不变，Carrier候选则可能变化，因此候选只缓存
Patch端点和切向；Carrier仍在每轮按当前candidate集合、当前geometry及原角度、距离、
carrier_id和index稳定顺序重新评分。本轮同时在构建`carrier_by_patch`时保存当前只读
Carrier行映射，替代同轮重复`.loc`，不复用跨轮选择结论。

run30的12轮`movement_anchor_split`由run29的`4.1472s`降至`2.5834s`，减少`37.7%`；
`segment_access_split`为`5.4157s`。相对run28，两类Movement阶段合计由`11.3843s`
降至`7.9991s`，减少`29.7%`。正式流水线wall为`89.9465s`、CPU约`70.2s`、peak RSS
为`576565248 bytes`。run30相对冻结run14的输入身份和7类业务工件规范化指纹全部
一致，独立QA零异常、QGIS 50层回读通过，完整P04专项测试为`327 passed`。

run30仍只定级为`INNERNET_CANDIDATE`。局部wall按Patch数直接外推约`6.38h`，仍无
6小时安全裕量，且不能表达全量关系规模；最终必须由1532 Patch正式运行裁定。

## 28. 增量Carrier指纹标量快速路径

run31在run30代码上重新剖析，累计`142.011s`，只用于热点排序。Movement优化后，
`_segment_fingerprints`约`4.745s`，其中`_group_tokens`约`4.058s`、`_value_bytes`
执行约251万次并累计`2.869s`。旧实现对普通字符串、整数、布尔和浮点也先访问不存在
的`.wkb`并捕获异常，再调用`pd.isna`；这不增加指纹信息。

候选为Shapely geometry、普通float、str/int/bool/bytes和`pd.NA/pd.NaT`增加与旧字节
合同完全相同的显式快速路径；其余类型继续执行原通用`.wkb`、missing和`repr`路径。
指纹覆盖列、行顺序、每值长度前缀、BLAKE2b算法、group划分和cache失效条件均不变。
真实`patch_road_assignment`的1004行、53列、53212个值微基准中，所有196组digest
逐字节一致，耗时中位数由`0.04572s`降至`0.02575s`，约`1.78x`。

run32的13轮fingerprint累计由run30的`1.9708s`降至`1.0374s`，减少`47.4%`；正式
wall由`89.9465s`降至`86.4917s`，CPU由约`70.2s`降至`68.19s`，peak RSS为
`575008768 bytes`。相对冻结run14的输入身份和7类业务工件规范化指纹全部一致，
独立QA零异常、QGIS 50层回读通过，完整P04专项测试为`337 passed`。Patch数粗略
线性外推约`6.13h`，仍不能替代1532 Patch正式验收或证明达到6小时。

## 29. canonical ID等价快速归一化

run31中`canonical_id`被Node、Carrier、Movement和Topology累计调用约247万次，self
time约`1.536s`。正式规则只把可选正负号、Unicode十进制整数及ASCII `.0...`尾数
归一化为整数，其余复合ID原样保留。候选使用`str.isdecimal`和显式ASCII零尾数判断
替代每次正则匹配；引号剥离、空值、NaN、前导零、正负号和非整数文本行为不变。

在run32正式Road/Node/RoadNextRoad的58556个真实ID相关值上，旧、新结果逐值一致；
重复250万次微基准由`1.1596s`降至`0.4684s`，约`2.48x`。run33正式wall为
`86.9303s`、CPU约`68.55s`、peak RSS为`575655936 bytes`，与run32的0.44秒差异处于
其他阶段抖动范围，不表述为端到端加速。run33相对冻结run14的7类业务工件规范化
指纹全部一致，独立QA零异常、QGIS 50层回读通过，完整P04专项测试为`351 passed`。
当前仍为`INNERNET_CANDIDATE`。

## 30. 最大采样转角的精确批量插值

run31剖析中`max_sample_turn`累计约`3.492s`；13705次调用中只有2429个精确WKB缓存
未命中，未命中路径的主要成本是逐点`line.interpolate`及Shapely `Point.x/y`属性读取。
曾验证全向量角度计算，虽然局部约18倍加速，但最大浮点差约`1.2e-6`，因此拒绝进入
候选。最终实现只批量执行同一Shapely线性插值和坐标提取，角度仍按原逐索引NumPy
运算顺序计算，不改变station、闭环归一化、最大值或缓存键。

在正式run输入的761条Road carrier、`1m/2m`两种spacing共1522组样本上，新旧结果
`1522/1522`逐浮点完全相等；微基准由`0.7248s`降至`0.2270s`，约`3.19x`。run34
正式wall由run33的`86.9303s`降至`83.4849s`，减少`3.96%`；CPU由`68.5473s`
降至`65.5881s`，减少`4.32%`；peak RSS为`574902272 bytes`。Carrier、Movement和
Node阶段分别降低`7.61%`、`4.47%`和`7.52%`。

run34相对冻结run14的输入身份及7类业务工件规范化指纹全部一致，独立QA为0违规、
QGIS 50层回读通过，完整P04专项测试为`351 passed`。按6-Patch结果机械线性外推
1532 Patch约`5.92h`，首次低于6小时目标，但局部规模不能表达全量关系复杂度、I/O和
内存增长，仍只定级为`INNERNET_CANDIDATE`；必须由1532 Patch正式运行裁定。

## 31. Target fragment方位角精确坐标批取

run35在run34代码上执行持久化cProfile，累计`146.500s`，只用于热点排序。其中
`_station_labels`调用2410次、累计约`6.962s`；source/target局部方位角仍逐点调用
Shapely `get_x/get_y`，两处列表累计约`2.719s`。候选只把已由同一Shapely插值得到的
Point数组一次转换为坐标数组，后续仍按原顺序逐点执行差值、`float`、`atan2`、
`degrees`和`% 180.0`，不改变距离矩阵、角度门槛、score、member或排序。

在run34正式887条Road生成的16642对实际插值点上，新旧方位角`16642/16642`逐浮点
完全一致，坐标读取微基准由`0.8181s`降至`0.04861s`，约`16.8x`。两次独立正常
回放中，Target fragment两轮合计分别由run34的`4.9083s`降至run36的`3.8904s`
和run37的`3.7290s`，减少`20.7%`和`24.0%`。run36/run37最终wall分别为
`94.0442s/87.1309s`，受输入、GPKG写盘、QGIS及其他阶段抖动影响，均不优于run34的
`83.4849s`，因此不表述为新的本地端到端加速。

run37相对冻结run14的输入身份及7类业务工件规范化指纹全部一致，独立QA为0违规、
QGIS 50层回读通过，完整P04专项测试为`352 passed`。由于Target fragment工作量随
Patch Road/Lane数量扩展，本项保留在下一内网候选；但正式时限仍只能由1532 Patch
运行裁定。

run38进一步把同一`axes` GeoDataFrame的`itertuples`移到Target fragment阶段开始时
执行一次；每条source只按原`axes.sindex.query`返回顺序取只读axis行，不再重复
`iloc.copy + itertuples`。候选顺序、namedtuple字段值、geometry对象、score和tie-break
不变。Target fragment两轮合计降至`2.8171s`，相对run34减少`42.6%`、相对run37
减少`24.5%`；正式CPU为`65.3688s`，略低于run34的`65.5881s`。总wall为
`86.8459s`，其中GPKG输出与QGIS发现合计比run34多约`2.30s`，不把该抖动解释为算法
回退。run38的7类业务工件仍与run14一致，独立QA为0违规、QGIS 50层回读通过，完整
P04专项测试保持`352 passed`，因此run38作为当前内网代码候选。

## 32. 1532 Patch输入常驻规模基准

当前机器没有内网`patch_all`或`Patch_Test`。为分离输入常驻和后续构图风险，使用既有
`benchmark_input_scale.py`，在`outputs/_work`构造1532个Patch目录并轮转硬链接6个
真实Patch的Vector文件。该基准只执行Patch发现、8类图层读取、同源CRS转换/拼接和
正式输入manifest，不运行Carrier、Movement、Node或Topology，不作为端到端验收。

基准完整消费`1532 × 8 = 12256`个文件，加载`3474894`行，总wall为`758.949s`
（约12.65分钟）、CPU为`269.543s`、peak RSS为`2.12GiB`，通过8GiB目标和16GiB硬
上限。主要常驻行数为Road `259189`、Lane `558841`、LaneBoundary `1590103`、
LaneTopo `751151`、RoadNextRoad `311014`；8类图层CRS均转换到`EPSG:32650`，manifest
包含12256个文件。

该结果说明在当前重复分布下，Patch输入常驻约占8GiB目标的26.5%，历史全量运行约
`5.6–6.7GiB`峰值不能只归因于输入读取，后续Evidence/Carrier/Movement/Node对象仍是
内存主体。由于硬链接复用相同内容会受文件缓存和重复数据分布影响，758.949秒只作为
输入I/O乐观下界；真实1532 Patch的文件大小、几何复杂度和分布仍需内网正式运行确认。

## 33. 全量Node completion surface异常终止与低内存修复

用户提供的全量运行`p04_segment_first_full_20260803T212616`日志显示：
`junction_portal`已正常完成24014个group、128093个endpoint，接受84787个portal、
拒绝50个portal；随后RSS从约`7.75GiB`持续升至约`8.95GiB`，peak RSS达到
约`9.02GiB`，最后活动位置为`segment_first_nodes.py:_completion_surfaces`。日志在此
直接截断，没有Python traceback、`run_failed`事件或launcher trap输出。结合旧实现会
同时常驻DriveZone buffer union、accepted surface全域union、其buffer及最终union，
高置信根因为Node completion surface全域物化造成额外内存峰值，并触发WSL/宿主外部
终止；宿主OOM事件本身未在本地复现，不能表述为已直接取证。

修复后不再建立accepted Junction全域union。新实现复用既有Junction分组surface，建立
STRtree，并只为实际查询命中的局部Junction构建buffer；LRU上限为2048条。DriveZone
仍按原规则buffer union，accepted来源过滤、点覆盖、距离、路由和数值覆盖率仍执行原
精确合同。新增`node_completion_surface`进度，Portal完成后可以看到实际surface单位、
accepted/rejected数量及完成事件。

验证证据如下：

- 新增精确等价测试覆盖点覆盖、距离、局部surface、数值覆盖率及门槛结果；完整P04
  专项测试为`355 passed`；
- 冻结6-Patch run39正式入口wall为`87.8300s`，peak RSS为`536838144 bytes`
  （约512.0MiB），低于run38约547.2MiB；
- run39相对冻结run14的输入身份和7类业务工件规范化SHA256全部一致，独立QA零违规、
  QGIS 50层回读通过，验收器输出`ACCEPTED`；该`ACCEPTED`仅针对同输入局部零回退，
  不是1532 Patch性能验收；
- 以24014个accepted polygon模拟故障规模，索引构建约`0.082s`、RSS增量约
  `3.07MiB`；遍历24014次局部查询约`1.529s`、RSS增量约`4.16MiB`，buffer缓存稳定
  封顶2048条；
- run39发布`node_completion_surface`完整进度，并记录3392次局部surface查询、
  `unsafe_local=0`。

当前修复定级为`INNERNET_CANDIDATE`。只有重新完成1532 Patch正式入口、产出Road与
Node且验收器同时通过时限、资源、进度、业务指纹、独立QA和QGIS回读，才能关闭本轮
全量异常。
