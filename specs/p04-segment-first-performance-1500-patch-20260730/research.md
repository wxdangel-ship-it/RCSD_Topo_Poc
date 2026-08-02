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
