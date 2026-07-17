# T06 全量性能恢复阶段报告

## 1. 当前结论

本轮已经完成日志根因分析、隔离工作树实现、`1885118` 优先门禁、六用例回归和首轮内网全量验收。首轮内网候选 Step3 内部耗时 `13530.559s`，为冻结基线的 `42.01%`；Step1/2 与 Step3 两组 wall 求和 `18657s`，为冻结推算总计的 `43.46%`；peak RSS `8659380 KB`、swap=0、无 OOM/Killed，因此性能和内存门禁已关闭。业务比较的 `95/95` 个成果无缺失或新增，正式汇总、F-RCSD、relation、topology/surface/audit 均保持一致，但 ownership 的一个 RCSD Road 候选列表多出一个50米边界 Segment，因此“业务完全不变”门禁尚未关闭。兼容修复已在隔离工作树完成本地六例 `549/549 changed=[]`，仍需一次内网全量复验后才能完成目标。

## 2. 内网异常慢的根因

诊断包来自 `t10_innernet_full_no_t08_20260713_154417`，运行提交为 `f870a83`，已包含 `34e5204/6a1eb4e`，可排除漏部署优化提交。回传归档 `t06_postrun_compact.tar.gz` 的字节数为 `63885`，SHA256 为 `f5bba49122c4d6410614aba22bb4988114ef22dfbcc74cea16d87db953ab2d3a`；解码、校验和安全路径检查均通过。

- 从 T06 开始的流水线最终 `rc=0`，总 span `12:55:56`；不是进程异常终止。
- T06 Step3 精确耗时 `32207.946s`（`8:56:48`），其中 surface-aware 阶段 `31961.552s`，占 `99.2%`。
- 旧 launcher 未给 T06 Step1/2 和 Step3 外层各自写 `/usr/bin/time`。根据 launcher 结束时间减总 span 得到启动边界，再结合阶段日志末次写入时间，推算 Step1/2 约 `5432.081s`、Step3 外层约 `37496.218s`、T06 总计约 `42928.299s`（`11:55:28`）。这些值用于冻结旧运行的总耗时门槛，但必须与候选独立精确计时区分。
- 日志记录六轮完整 Step3 replaceable 解析：`19419 / 19667 / 19281 / 19112 / 19005 / 19003`，局部热点被完整放大六次。
- 全量有 `119295` 个 added RCSD Node、`28918` 个 junction。旧 `_build_junction_states` 每轮扫描 `added nodes × all junction states`，理论组合约 `3.45e9`，六轮约 `2.07e10`。
- 531 次 heartbeat 样本中，`_build_junction_states` 占 `30.7%`，Shapely geometry 操作占 `31.8%`，重复 reachability BFS 占 `4.9%`，relation context 全表扫描占 `4.3%`；仅 `_build_junction_states + buffer` 两个直接顶层 frame 就占 `47.6%`。
- peak RSS `9365992 KB`（约 `8.93 GiB`），swap 为 0、没有 OOM/Killed；但已接近当时 WSL 物理内存上限，不能用无界 geometry cache 或并行换时间。
- pipeline `rc=0` 只代表流程完成，不代表业务 QA 全通过：基线仍有 `surface_topology_fail_count=291`、`final_frcsd_topology_fail_count=15`。

因此，主要原因不是版本错误或 OOM，而是六用例优化遗漏了只有全量规模才显著的二次扫描与六轮 geometry/topology replay。

## 3. 实现改动

- junction state：建立 `semantic node id -> candidate junction states` 反向索引，再按 replacement Segment 交集过滤，消除 added-node 全表扫描。
- node/relation/construction：建立 raw retained node、relation rows、failed nodes 一次性索引，保持原始输入顺序与去重顺序。
- topology：同一 graph revision 预计算无向连通分量，并在同轮审计内复用 relation road context、graph 和最终拓扑审计行；有向可达与 hard-gate 语义不变。
- coverage：在六轮 validation 中复用紧凑 uncovered 标量结果；geometry buffer 按 `64` 个 signature 分批计算，标量缓存上限 `200000`，geometry 仍按既有生命周期释放。
- ownership：STRtree 使用带 `0.000001m` 纯查询容差的 `dwithin` 候选查询，再以原始 `<=50m` 精确距离过滤恢复旧候选集合；Segment buffer 仅在第二次命中后缓存，LRU 上限 `512`。查询容差不进入评分或业务阈值。
- replay output：validation replay 不再反复物化 GPKG/CSV；road/node/relation、surface/topology/audit 均在最终 gate 收敛后一次发布，最终独立成果使用固定 `2` worker 受控并行。`1885118` 因该发布优化再节省 `10.33s`，仅增加 `22340 KB` peak RSS；继续并行 ownership 输出的负收益试验已回退。发生 semantic-junction downgrade 时显式模拟历史 GPKG 回读字段语义，并仅补写历史条件式 JSON，保持完整文件集和 SHA256 一致。
- replay lifecycle：进入下一轮 validation 前显式释放上一轮大体量 artifacts、surface summary 与 runtime state，避免六轮 replay 同时保留大对象；geometry corridor cache 保持有界。
- replacement plan：中间 replacement plan 延迟物化，所有消费者统一支持内存态读取；hard-gate 级联权威 transition 也读取 deferred plan，避免因文件尚未落盘而漏掉权威闭包。
- hot primitives：已规范化的整数/复合 ID 跳过无效的浮点正则与字符串重建；顺序去重改为 CPython 有序字典原语；多 Road replacement 保持原 splice 顺序但合并为一次线性扫描；feature JSON 不再二次递归规范化，大 JSON 使用约 1MiB 缓冲写出。
- 所有 candidate、rollback、hard-gate、final publish 与 QA 均保留；未改变 CLI、官方入口、契约、字段语义或依赖。

最终回归曾发现 `609214532` 比冻结结果多 `2` 个 surface audit rows。根因是 deferred hard-gate plan 尚未物化时，权威 transition closure 只检查物理文件，导致节点 `12836477/12836484` 的闭包未执行。消费者改为统一读取 deferred plan 后，权威审计恢复 `2` 行，surface audit 恢复为 `196/183/183`，与冻结业务结果一致。

## 4. 本地基线与候选性能

环境：Python `3.10.12`、Shapely `2.1.2`、GEOS `3.13.1`、GeoPandas `1.1.3`、Fiona `1.10.1/GDAL 3.9.2`、Pyogrio `0.12.1/GDAL 3.11.4`；WSL `32` vCPU、内存 `32404893696` bytes、swap `8589934592` bytes。

| Case | 当前 Step1/2(s) | 当前 Step3(s) | 当前总计(s) | 候选 Step3(s) | 合成候选总计(s) | Step3 变化 | 总计变化 |
|---|---:|---:|---:|---:|---:|---:|---:|
| 1885118 | 38.19 | 158.13 | 196.32 | 68.54 | 106.73 | -56.66% | -45.63% |
| 605415675 | 16.26 | 66.19 | 82.45 | 32.45 | 48.71 | -50.97% | -40.92% |
| 609214532 | 29.30 | 134.11 | 163.41 | 56.67 | 85.97 | -57.74% | -47.39% |
| 706247 | 14.19 | 41.83 | 56.02 | 26.80 | 40.99 | -35.93% | -26.83% |
| 74155468 | 5.21 | 25.87 | 31.08 | 15.66 | 20.87 | -39.47% | -32.85% |
| 991176 | 7.64 | 24.27 | 31.91 | 15.80 | 23.44 | -34.90% | -26.54% |
| **合计** | **110.79** | **450.40** | **561.19** | **215.92** | **326.71** | **-52.06%** | **-41.78%** |

候选轮次只重跑 Step3；Step1/2 代码和成果未改变，表中候选总计采用当前 Step1/2 实测值加候选 Step3，避免把复制既有成果误报为新实跑。既有冻结六例总耗时为 `611.451823s`，合成候选相对该冻结值下降 `46.57%`。六个 Case 的 Step3 wall 均低于当前基线，Step3 聚合已低于当前基线的 50%；正式“全量 T06 不高于当前 50%”完成门禁仍只由内网同环境全量结果裁定。

## 5. 业务与 GIS 等价证据

- `1885118`：`37/37` 个 CSV SHA256 完全一致，`36/36` 个 GPKG 业务语义完全一致。
- 六例：`222/222` 个 CSV SHA256 完全一致；最终文件集完全一致。
- 最终候选 `candidate_v71_publish2` 对 `candidate_v67_final` 的六例逐树比较共 `549/549` 个成果，全部 `passed=true`、`changed=[]`；v67 对已验收的 `candidate_v50_final` 全部 CSV/GPKG 不变，后者直接对 `baseline_f870` 的 `216/216` 个 GPKG 已证明 CRS、schema、properties 与 geometry 的业务语义指纹一致。
- GPKG 的 CRS、schema、feature count、properties、geometry exact 与 topological components 均无业务差异。
- `candidate_v71_publish2` 对 `candidate_v67_final` 的逐树比较没有成果变化；此前 v67 对已验收的 `candidate_v50_final` 比较时，JSON 差异仅位于运行根和临时验证根：`1885118` 有 `3` 个 JSON、其余每例 `2` 个 JSON；路径归一化后全部相等，没有业务字段差异。
- `1885118` 直接对冻结基线的 `91/91` 文件校验中，另有两个已知 compact summary JSON 变化：冻结 summary 仍记录 `13219` 行、`33` 个 fail，而两侧完全一致的权威 topology audit CSV 实际为 `14155` 行、`34` 个 fail；候选 summary/detail 已按权威 CSV 重算一致，54 个非拓扑兼容业务键保持相等。这属于冻结汇总陈旧修正，不是业务成果漂移。
- topology、surface、candidate/rollback/hard-gate、audit 输出均保留并进入结构化比较，不采用 raw GPKG 文件 hash 代替语义比较。

证据根：`outputs/_work/t06_innernet_perf_50pct_20260716/candidate_v71_publish2`；直接对照根为同级 `candidate_v67_final`，冻结基线根为同级 `baseline_f870`。

## 6. 内存门禁

| Case | 当前 Step3 peak RSS(KB) | 候选 Step3 peak RSS(KB) | 变化 |
|---|---:|---:|---:|
| 1885118 | 637868 | 499704 | -21.66% |
| 605415675 | 323496 | 294988 | -8.81% |
| 609214532 | 541544 | 470104 | -13.19% |
| 706247 | 295440 | 252916 | -14.39% |
| 74155468 | 185896 | 186432 | +0.29% |
| 991176 | 202952 | 200800 | -1.06% |

六例均 swap=0、exit=0，最大候选 peak RSS 为 `499704 KB`；5 例下降，`74155468` 增加 `536 KB`（`+0.29%`）。首轮内网候选 peak RSS 为 `8659380 KB`，相对冻结 `9365992 KB` 下降 `7.54%`；Step1/2 与 Step3 均 swap=0，且环境日志无 OOM/Killed，正式全量内存门禁已通过。

## 7. 自动化验证

- T06 最终全量测试：兼容修复后 `487 passed in 60.09s`，0 failure、0 error、0 skip。其中内网验收门禁定向测试增至 `8 passed`，覆盖 GNU time 解析、正式阈值、业务根路径归一化、流式断点复用、ownership 逐字段差异与边界探针、拓扑审计/兼容业务指标防漂移和 250KiB bundle 导出后解包校验。
- `1885118` 真实成果校验：候选与冻结基线文件集均为 `91/91`；`73/73` 个稳定 CSV/GPKG/GeoJSON 业务成果无差异，`18/18` 个 JSON 文件集一致。仅允许的 `t06_step3_detail_metrics.json`、`t06_step3_summary.json` 发生变化；候选已由两侧一致的权威 topology audit CSV（`14155` 行，`fail=34`、`pass=12734`、`warn=1387`）重新计算并通过全部一致性检查，54 个非拓扑兼容业务键与冻结基线相等。
- 最终 parsing 回退确认定向测试：`15 passed in 3.51s`，确认未保留两个被否决的微优化试验。
- 六例回归顺序：`1885118 -> 605415675 -> 609214532 -> 706247 -> 74155468 -> 991176`。
- ownership 兼容修复候选 `candidate_v75_ownership_epsilon` 对 `candidate_v71_publish2` 的六例逐树比较共 `549/549` 个成果，全部 `passed=true`、`changed=[]`；查询微基准在 `6435` 个 RCSD Road 上，`epsilon=0/0.000001m` 的候选总数均为 `26637` 且 SHA256 相同，四次耗时为 `2.983/3.083/3.032/2.880s`，未观察到复杂度或候选规模增长。
- `git diff --check`：通过。
- 修改后 T06 核心 `src/ + tests/ + scripts/t06*` 共 `162` 个源码/脚本文件，加 `3` 个 SpecKit 一次性验收脚本后总计 `165` 个，`>=61440 bytes` 为 `0`。
- 本轮修改的所有源码、脚本和测试均低于 60KiB；T06 全体最大为本轮修改源码 `step3_surface_aware_plan_release.py` 的 `60870 bytes`，其次为既有测试 `test_step3_surface_topology_audit.py` 的 `60787 bytes`。
- 既有非 T02 治理缺口：未触碰的 T01 `step2_trunk_utils.py` 为 `62004 bytes`，已登记但不在本轮越权拆分。

## 8. 内网验收口径

一次性 helper 位于 `specs/t06-innernet-performance-50pct-20260716/validation/run_innernet_candidate.sh`。它复制原 manifest 到新的候选 root，symlink 只读上游阶段，并在新 root 依次执行 `t06_step12`、`t06_step3`、业务/性能自动判定以及通过后的 `t11,t09`；每组独立输出 `/usr/bin/time -v`，不会覆盖原基线 root，也不会因 pipeline 非零返回而关闭父 WSL 壳。`validate_innernet_candidate.py` 以单 worker 流式比较全部稳定 CSV/JSON/GPKG/GeoJSON 的 CRS、schema、properties 与规范化 geometry；heartbeat 作为运行态工件不进入业务门禁，ownership CSV 额外按 `rcsd_road_id` 输出逐字段差异，并支持 `--diagnostics-only` 在不重跑 T06、不重算全部语义指纹时复查。`--ownership-boundary-probe-road-id` 可在重跑前对单个 RCSD Road 比较旧 buffer、原 dwithin 与容差 dwithin 的精确候选集和 Top8 排序。两个已知 compact summary 文件必须由权威 topology audit CSV 重算一致，且 54 个非拓扑兼容业务键不得漂移。`collect_innernet_validation.py` 会把逐字段差异和边界探针一起纳入每片不超过 250KiB 且立即解包校验的文本回传包。

最终门禁：

1. Step3 `<=16103.973s`，即不高于当前 `32207.946s` 的 50%。
2. 候选 T06 Step1/2 group 与 Step3 group 的 `/usr/bin/time` wall 之和 `<=21464.149s`（约 `5:57:44`），即不高于旧运行推算总计 `42928.299s` 的 50%。helper 将两个阶段分开精确计时；因为候选会重复一次 pipeline preflight，该求和口径比旧单进程边界更严格。
3. 全量稳定 CSV/GPKG、CRS、schema、properties、geometry、topology、surface 与 audit 不回退。
4. peak RSS `<=9365992 KB`、swap=0、无 OOM/Killed。
5. 当前性能、内存证据已取得；兼容修复尚未取得内网业务复验，因此任务状态保持“待内网业务收口验收”。
