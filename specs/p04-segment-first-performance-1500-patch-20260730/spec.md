# P04 Segment-first 1500 Patch 性能优化规格

## 1. 任务定位

本任务只优化 P04 `Segment-first Road direct generation` 的执行性能与资源稳定性。
P04 仍为 `Active POC`，不替代也不修改 T01–T12。

冻结代码与业务对照基线：

- `main@9b20591137b5ab06f996d93a83b935403ff9311d`
- 正式入口：`scripts/p04_run_segment_first_innernet.py`
- 输入口径、Road/Node/拓扑业务口径、hard gate 和 `silent_fix=false` 均保持不变。

## 2. 用户目标

在内网 8 核 CPU 环境，对约 1500 个 Patch 的正式 P04 输入完成端到端运行：

- 推荐目标：`wall_time <= 6h`；
- 硬上限：`wall_time <= 8h`；
- 运行过程不得因内存持续增长、CPU 过度订阅或无响应而异常崩溃；
- 性能优化不得引起业务成果回退。

端到端计时从正式入口完成参数解析并开始输入校验起，到 Road、Node、
RoadNextRoad、审计成果、独立质检和 QGIS 工程全部落盘并输出最终状态为止。

## 3. 五类职责视角

### 3.1 产品视角

- 内网操作者能够从控制台看到当前阶段、累计耗时、CPU、RSS、I/O 和热点位置。
- 正常目标在 6 小时内完成；超过 6 小时必须有明确预警；不得超过 8 小时后仍无结论。
- 失败必须留下可定位的运行日志和最后资源状态，不允许静默退出。

### 3.2 架构视角

- 优先消除重复全网扫描、重复几何重建、无关文件哈希、无界缓存和低效串行 I/O。
- 并发只用于无共享业务状态、结果可确定性合并的阶段。
- 8 核环境下 P04 自有并发默认最多占用 6 个工作核，预留 2 个核给系统、文件系统和 GIS 驱动；禁止嵌套进程池和无界任务队列。
- 不通过减少输入、跳过业务阶段、放宽 gate、降低几何精度或改变输出顺序换取速度。

### 3.3 研发视角

- 先建立低开销阶段/调用栈采样，再依据真实热点优化。
- 对可复用空间索引、规范化 ID 映射、分组结果和静态几何构建显式缓存。
- 对 Patch I/O 使用有界批次，及时释放中间对象；不得把 1500 Patch 的重复临时副本长期驻留内存。
- 不修改正式入口参数签名；新增性能数据进入既有日志与既有 summary 的 `performance` 区域。

### 3.4 测试视角

- P04 模块测试必须全绿。
- 新增资源采样、热点聚合、输入清单和优化路径的单元测试。
- 至少执行 1 个真实 6-Patch 回归用例和可重复的规模化合成基准。
- 对优化前后正式 GPKG 进行字段归一化、记录排序、几何 WKB、关系和 gate 等价比对。

### 3.5 QA 视角

- 显式验证 CRS 与坐标变换不变。
- 显式验证 Road/Node/RoadNextRoad 拓扑、mainnode、LaneTopo 和 hard gate 不变。
- 几何必须可解释，不允许 silent fix。
- 输入、参数、commit、运行环境、阶段时间、CPU/RSS/I/O 峰值可追溯。
- 只有内网约 1500 Patch 正式复跑满足时限和资源门槛，才可宣布总体目标完成。

## 4. 资源合同

参考 T10 已验证的“wall/CPU/RSS/I/O 同步采样、业务等价优先”方法，并为
P04 1500 Patch 规模设定以下任务级预算：

- 峰值 RSS 推荐目标：`<= 8 GiB`；
- 峰值 RSS 硬上限：`< 16 GiB`；
- RSS 不得随 Patch 数量持续单调线性增长；进入全网计算后应平台化；
- P04 自有工作进程/线程并发度：`<= 6`；
- 不允许持续占满 8 核导致系统、文件系统或日志线程饥饿；
- 资源硬上限临近或耗时预测超过 8 小时时，必须输出明确预警，不得静默等待。

上述为本性能任务的工程验收预算，不改变 P04 的业务口径。

## 5. 业务零回退合同

优化前后在同一输入、同一参数和同一 CRS 下，除运行时间、运行时间戳、
绝对输出路径及新增性能审计字段外，必须满足：

- Road、Node、RoadNextRoad 的规范化字段与记录集合一致；
- Road/Node 几何规范化 WKB 一致；
- Segment、Access、JunctionUnit、PhysicalMovement、mainnode 和 LaneTopo 关系一致；
- `source`、`segment_id`、`source_patch_ids`、Lane 关联等 lineage 一致；
- core gate、hard gate、Review 标记和终态一致；
- 正式图层、审计图层、独立质检和 QGIS 工程的业务图层集合不减少；
- 不新增自动修补或 silent fix。

## 6. 验收结论

结论分为三层：

1. `CODE_OPTIMIZED`：代码、测试、局部基准和业务等价通过；
2. `INNERNET_CANDIDATE`：已生成完整内网脚本与性能审计能力，等待正式数据复跑；
3. `ACCEPTED`：约 1500 Patch 内网正式复跑同时满足`<=6h`、不高于
   异常终止运行在12.7小时时已观测墙钟下界的50%、资源预算与业务零回退合同；
   `>6h`即失败，
   `8h`只作为失败诊断线，书面说明不能绕过门槛。

未取得内网完整运行证据时，不得把 `CODE_OPTIMIZED` 表述为目标已完成。

## 7. 2026-08-02 内网失败证据与第二轮热点合同

用户提供的约 1500 Patch 正式运行日志在 `elapsed=45759.2s`
（约 12.7 小时）时仍未结束，之后该进程异常终止；`45759.2s`只是异常终止前
中间观测下界，不是完成耗时。它已经足以证明该次运行违反8小时硬上限。该时点：

- `cpu=44516.7s`，接近墙钟时间，说明是持续单核计算而非等待磁盘；
- `rss≈5.9GiB / peak_rss≈6.7GiB`，仍低于 8 GiB 推荐目标；
- `read=40.8MiB / write=0.0MiB` 长时间不变；
- 调用栈持续采样于 `segment_first_geometry_metrics.py:surface_coverage`
  与 `segment_first_partial_members.py:_completion_supported`。

因此本轮不得通过增加 Patch I/O worker 或扩大 CPU 订阅处理；第二轮只允许：

1. 对最终 DriveZone `MultiPolygon` 的原生不相交组件建立有界、可释放的空间索引；
2. Polygon/低组件surface的覆盖查询先对完整最终surface执行prepared
   `covers/disjoint`：能够证明覆盖率为1或0时返回对应精确值，边界相交样本仍执行
   原始精确`intersection.length / line.length`；
3. 写入审计字段或参与排序的覆盖率同样只能返回上述精确数值；禁止重新union原始
   DriveZone分片代替最终surface；
4. 优化前后覆盖值、业务 gate、正式和审计成果必须满足第 5 节零回退合同。

该日志未携带 commit、run summary 和最终产物，因此只作为真实性能失败和热点证据，
不作为业务成果等价证据。

## 8. 第三轮端到端减半与真实进度合同

用户确认第三轮目标为：同一约1532 Patch输入、参数、CRS和运行环境下，正式入口
端到端墙钟耗时不高于当前基线的50%，并以`<=6h`作为更严格的绝对通过线。
2026-08-02异常终止运行在12.7小时仍未完成，因此即使没有完成耗时，也能证明：
只有`<=6h`才可能同时满足绝对目标和已知下界的减半目标。`8h`只保留为失败诊断线，
不再作为降级通过条件。

第三轮性能策略：

1. 对最终`MultiPolygon`的原生组件建立可复用索引；对Polygon或低组件surface采用
   完整surface的prepared终态谓词，不能证明0/1的数值和门槛样本都回退精确求交；
2. 全部道路面门槛判断和数值覆盖率统一复用共享精确实现；
3. 扩大有界覆盖缓存并记录查询、命中、`terminal_fast`、`exact_fallback`、
   `unsafe_local`和direct计数，验证多轮
   carrier重算是否发生缓存抖动；
4. 先做算法级消重，再决定是否对独立Patch预处理启用有界并发；不得用CPU或内存
   过度订阅替代算法优化。

正式控制台不得只报告elapsed和当前函数。必须以真实处理对象输出：

- Patch发现/读取：`completed/total`、文件数、行数、空/非法几何数；
- Segment构建：调用轮次、`completed/total`、built/retained/review累计数；
- Junction/Node/Topology：`completed/total`及已生成对象数；
- QA/输出：检查项或图层`completed/total`；
- 覆盖热点：query/cache-hit/terminal-fast/exact-fallback/unsafe-local及吞吐；
- 每30秒心跳、阶段切换和每完成1%输出；高频快速阶段的1%事件按最多每秒1条
  节流，但内存快照仍按每个实际单位更新，阶段开始/完成事件不得丢失；10分钟
  实际计数不增长时输出`STALL WARNING`；所有已发布事件同时写入输出目录
  `p04_progress.jsonl`。

进度中的阶段百分比必须由真实`completed/total`计算；跨阶段总体值只能标记为
`overall_estimate`。ETA在样本不足时显示`estimating`，不得用虚假线性百分比替代实际
处理计数。
