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

## 阶段 F：Segment 脏集与静态索引复用

1. 先拆分超过100KB的`segment_first_pipeline.py`，保持正式入口和业务接口不变；
2. 为每轮Carrier规划建立逐Segment完整输入指纹，只重算dirty Segment，并按原
   Segment顺序重建Carrier字段顺序和汇总；
3. 对同一次run内只读的Movement evidence索引、accepted Junction surface、
   Segment access映射和恢复指纹建立弱引用生命周期缓存；
4. 控制台和summary发布dirty/reused、复用率和指纹缓存命中；验收器阻断没有发生
   实际Segment复用的全量候选；
5. 先以冻结6-Patch做7类业务指纹零回退，再交付1532 Patch内网候选。

## 阶段 G：全量规模项收敛与进度闭环

1. 对Junction retained kind、ADVANCE_RIGHT Access端点、access surface恢复等
   `对象 × 全表`模式建立一次性索引，保留原精确距离、角度、覆盖和tie-break条件；
2. Target fragment只用扩展包围盒进行空间索引粗筛，最终仍执行原站点距离、方向和
   member选择，并分别发布Patch Road和Lane的实际完成量；
3. 用完整流水线函数级剖析识别剩余规模项，但剖析运行时长只用于热点排序，不作为
   正常运行验收值；
4. 对固定点流程先证明新发现ID相对既有处理集合的差集；差集为空时复用已经生成的
   Movement、几何和Node结果，差集非空时仍执行原完整重建；
5. Carrier多轮规划只缓存当前仍存活且DataFrame manager未变化的Road、assignment、
   reference及surface分组；access reservation只预缓冲一次并以空间索引粗筛，最终
   重叠长度和当前Segment排除规则不变；
6. 以冻结6-Patch的7类业务指纹、独立QA、QGIS回读和完整专项测试阻断回退；
7. 维持`INNERNET_CANDIDATE`，直至同一1532 Patch正式运行证明`<=6h`、资源受控、
   进度闭环且业务零回退。

## 阶段 H：后优化剖析与全量验收

1. 对最新候选执行持久化函数级剖析，只用于热点排序，不把cProfile wall作为验收值；
2. 对Node空间邻域查询使用GEOS精确距离谓词做索引粗筛，原距离、Road端点和路口
   隔离条件保持不变；
3. 配置路径只解析一次，输入存在性、输出目录新/空和输入输出不重叠合同保持不变；
4. 以冻结6-Patch完成7类业务指纹、独立QA、QGIS和完整专项测试回归；
5. 最终仍由1532 Patch正式入口完整运行裁定`<=6h`、`<8h`诊断线、资源受控和业务
   零回退，不以Patch数线性估算或局部验收替代。
6. 对必须具有显式evidence支持的ADVANCE_RIGHT关系先建立source/target倒排索引，
   只减少必然失败的笛卡尔候选，不改变Node、mainnode或RoadNextRoad发布语义。

## 阶段 I：输入二次I/O与重复路口面运算收敛

1. 在8类Patch图层读取worker中同步记录原文件SHA256，最终输入清单只复用预计算行，
   仍按原Patch/图层顺序发布并对外部输入单独散列；
2. 为清单构建增加真实文件总数、完成数、散列数和worker计数，异常时保留最后进度；
3. 对相同路口面WKB和相同inset的内缩目标复用原精确buffer结果，缓存逐run清空并受
   条目数和键字节双上限约束；
4. 以冻结6-Patch输入身份、7类业务指纹、独立QA、QGIS回读和完整P04测试阻断回退；
5. 保持`INNERNET_CANDIDATE`，等待1532 Patch正式复跑验证消除第二遍挂载盘I/O和
   路口面buffer重复计算后的完整收益。

## 阶段 J：WSL挂载盘输入输出收敛

1. 同一源CRS的Patch图层先稳定拼接，再执行一次批量投影和二维化；混合CRS仍回退
   原逐帧路径，图层族、字段、排序和几何合同不变；
2. 在WSL `/mnt/<drive>`环境将单个Patch GeoJSON以单次顺序流复制到本机临时目录，
   同流计算SHA256并从临时文件解析；临时空间不足或不可写时安全回退原路径；
3. 对挂载盘GPKG先在本机临时目录完整写出，再复制到目标目录隐藏临时文件并原子替换；
   空间不足或暂存不可用时回退直接写出，禁止留下半成品正式文件；
4. 暂存只改变物理I/O路径，不改变manifest中的原始路径、大小、SHA256、图层顺序、
   schema、CRS或geometry；
5. 以冻结6-Patch完成正式入口、7类业务指纹、独立QA、QGIS回读和完整专项测试，
   挂载盘收益只作为内网候选证据。

## 阶段 K：目标分片站点计算批处理

1. 对同一source geometry一次生成全部station、切向量和方位角，并批量计算候选轴线
   到station的距离矩阵；
2. 每个station仍使用原距离、角度、priority、segment/member和稳定排序合同做最终选择，
   不近似距离、不改变证据归属；
3. 使用真实3203条Road/Lane样本证明旧、新标签和fragment属性/WKB完全一致，并以
   冻结6-Patch正式流水线再次阻断业务回退；
4. run28只定级为`INNERNET_CANDIDATE`；Patch数线性外推既放大固定输出成本，也不能
   覆盖全量非线性构图风险，不得替代1532 Patch完整验收。

## 阶段 L：Movement固定点静态上下文复用

1. 对单次流水线内只读的Segment access按DataFrame identity和manager identity缓存
   ENDPOINT去重分组及THROUGH分组；对象或manager变化立即重建；
2. 在既有Junction surface缓存中同步保存同一次groupby得到的`junction_source`映射，
   不改变group顺序、首行source选择或聚合几何；
3. 在实际进度中发布junction/access context cache hit，证明第2轮以后真实复用；
4. 以run29阶段耗时、冻结run14的7类业务指纹、独立QA、QGIS回读和完整P04测试
   阻断回退，不把挂载盘和QGIS抖动解释为业务阶段变化；
5. run29仍为`INNERNET_CANDIDATE`，不得替代1532 Patch正式验收。

## 阶段 M：Movement静态端点上下文与本轮Carrier行索引

1. 对同一evidence DataFrame按精确`(patch_key, endpoint)`复用Patch端点和Patch切向，
   缓存容量沿用Movement选择缓存上限；
2. 在每轮构建Carrier倒排索引时同步保存当前只读Carrier行，替代候选评分中的重复
   DataFrame `.loc`；
3. 不缓存跨轮Carrier选择结果；每轮仍按当前候选集合、当前geometry及原完整排序重新
   评分，Carrier变化天然生效；
4. 以run30 Movement阶段耗时、冻结run14业务指纹、独立QA、QGIS和完整P04测试
   阻断回退；
5. 保持`INNERNET_CANDIDATE`，等待1532 Patch正式验收。

## 阶段 N：增量Carrier指纹标量快速路径

1. 保留每个输入值、长度前缀、行顺序、group划分和BLAKE2b digest合同；
2. 对Shapely geometry、普通float、str/int/bool/bytes及Pandas显式缺失值使用等价字节
   快速路径，其他对象保留原通用处理；
3. 以真实53列assignment逐组digest完全一致和微基准证明局部收益；
4. 以run32 fingerprint累计时间、冻结业务指纹、独立QA、QGIS和完整P04测试阻断
   dirty判定或业务回退；
5. run32继续为`INNERNET_CANDIDATE`，1532 Patch是唯一正式时限验收。

## 阶段 O：canonical ID等价快速归一化

1. 保持可选正负号、Unicode十进制整数和ASCII `.0...`尾数的现有归一化范围；
2. 用Unicode十进制判断和显式零尾数检查替代每次正则匹配，复合ID和非零小数原样保留；
3. 以正式Road/Node/RoadNextRoad真实ID逐值旧、新一致及250万次微基准验证；
4. 以run33冻结业务指纹、独立QA、QGIS和完整P04测试阻断ID、Node或Topology回退；
5. 不以run33局部wall替代1532 Patch正式验收。

## 阶段 P：最大采样转角精确批量插值

1. 保留原station序列、角度运算顺序、闭环归一化、最大值及精确WKB缓存合同；
2. 只将同一LineString的Shapely插值与坐标提取改为数组调用，不采用存在浮点漂移的
   全向量角度计算；
3. 以正式1522组Road carrier样本逐浮点完全一致和局部微基准证明收益；
4. 以run34冻结业务指纹、独立QA、QGIS和完整P04测试阻断几何或拓扑回退；
5. run34继续为`INNERNET_CANDIDATE`，1532 Patch是唯一正式时限验收。

## 阶段 Q：Target fragment方位角精确坐标批取

1. 保留原Point插值结果，以及逐点差值、float、atan2、degrees和180度归一化顺序；
2. 只将重复`get_x/get_y`改为一次坐标数组提取，不向量化后续浮点计算；
3. 对同一axes表只生成一次只读row序列，按原空间索引返回顺序选择候选，避免逐source
   `iloc.copy + itertuples`；
4. 以正式16642对Road插值点逐浮点完全一致和三轮Target fragment阶段计时验证；
5. 以run38冻结业务指纹、独立QA、QGIS和完整P04测试阻断分片、Road或拓扑回退；
6. 不用受I/O和QGIS抖动影响的局部总wall替代1532 Patch正式验收。

## 阶段 R：1532 Patch输入常驻规模基准

1. 只复用真实6 Patch文件内容构造1532目录规模，不运行或伪造业务拓扑；
2. 完整执行Patch发现、8类图层读取、CRS转换/拼接和12256文件manifest；
3. 记录各层行数、wall、CPU、Pandas深度内存、进程RSS和完整timeline；
4. 以8GiB目标、16GiB硬上限判断输入常驻预算，同时明确硬链接缓存使I/O偏乐观；
5. 不用输入规模基准替代Carrier/Movement/Node/Topology及正式输出端到端验收。

## 阶段 S：Node completion surface低内存索引

1. 复用Junction portal阶段已经形成的分组surface和source上下文，不复制accepted表，
   不再构造全域accepted `unary_union`及其buffer；
2. 为accepted Junction surface建立STRtree，按点、线或局部路由范围取得精确候选，
   并以最多2048条buffered Junction LRU限制常驻增长；
3. DriveZone继续使用原缓冲联合面；局部Junction候选与DriveZone在查询范围内联合，
   最终仍执行原覆盖、距离、路由和覆盖率判定；
4. 增加`node_completion_surface`实际进度，使控制台在Portal完成后能看到索引构建和
   accepted/rejected计数；
5. 以全量故障规模24014个accepted surface压力测试、完整P04测试、冻结6-Patch业务
   指纹、独立QA和QGIS回读阻断回退；
6. 保持`INNERNET_CANDIDATE`，必须由1532 Patch正式复跑确认不再外部终止且满足
   `<=6h`、8GiB目标和16GiB硬上限。

## 风险与回退

- 若热点位于超过 100 KB 的 `segment_first_pipeline.py`，本任务不直接追加代码；
  先通过新子模块抽取形成拆分计划，获得治理授权后再迁移。
- 若并发导致非确定性、GDAL 崩溃或内存峰值上升，立即回退该并发点。
- 若优化改变任何业务 gate 或几何，判为失败，不进入内网候选。
