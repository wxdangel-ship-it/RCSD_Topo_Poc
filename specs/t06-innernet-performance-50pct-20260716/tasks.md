# Tasks: T06 全量内网性能恢复至当前 50%

## Phase 1 - 基线冻结

- [x] T001 记录工作树、commit、Python/GDAL/GEOS、输入根、输出根和系统资源。
- [x] T002 运行 `1885118` 当前 `f870a83` Step1/2/3，记录业务、wall/CPU/RSS。
- [x] T003 将 `1885118` 与既有冻结业务结果做结构化对比。
- [x] T004 登记内网全量 `f870a83` 关键业务、性能、内存和 artifact hash。

## Phase 2 - Characterization 与热点实现

- [x] T005 写入前记录目标源码/测试 bytes。
- [x] T006 增加 junction reverse-index 等价测试。
- [x] T007 增加 relation/construction 索引等价测试。
- [x] T008 增加 graph component/reachability 等价测试。
- [x] T009 实现 junction state 反向索引，消除 `added nodes × all states`。
- [x] T010 实现 relation rows、construction failed nodes 的一次性索引。
- [x] T011 实现 graph revision 内连通分量复用。
- [x] T012 运行 T06 定向测试和 code-size scan。

## Phase 3 - Replay 架构与内存

- [x] T013 profile `1885118` 候选，确认热点分布和 RSS。
- [x] T014 盘点六轮 replay 的不变/变化输入和 gate 必需输出。
- [x] T015 实现不可变 Step3 上下文复用或受影响范围验证，保留全部 gate。
- [x] T016 对重复 geometry 判定引入有界复用，记录容量和清理点。
- [x] T017 验证最终完整发布与候选/rollback/hard-gate 业务完全等价。

## Phase 4 - `1885118` 门禁

- [x] T018 重跑 `1885118`，确认全部阶段 passed。
- [x] T019 业务结构化差异为 0。
- [x] T020 CRS、topology、geometry、audit 不回退。
- [x] T021 wall time 低于当前基线，peak RSS 不回退且 swap=0。

## Phase 5 - 六例门禁

- [x] T022 按 `605415675 -> 609214532 -> 706247 -> 74155468 -> 991176` 顺序回归。
- [x] T023 六例业务结构化差异为 0。
- [x] T024 六例逐例 Step1/2、Step3、总耗时不回退，RSS/swap 通过。
- [x] T025 T06 全量测试、`git diff --check`、code-size audit 通过。

## Phase 6 - 内网全量验收

- [x] T026 生成不新增官方入口的一次性内网复跑、全量语义比较、阈值判定及 250KiB 文本回传 helper，并完成导出后解包自检。
- [x] T027 内网从 T06 Step1/2 开始执行，记录精确阶段 wall/CPU/RSS。
- [ ] T028 全量稳定 CSV/GPKG、CRS、schema、geometry、topology/audit 对比通过。
- [x] T029 Step3 `<=16103.973s`，T06 两个独立 group 的 wall 求和 `<=21464.149s`。
- [x] T030 peak RSS `<=9365992 KB`、swap=0、无 OOM/Killed。
- [ ] T031 完成 final report，明确已修改/已验证/待确认和未改范围。

## Execution Order

`T001 -> T002 -> T003 -> T004 -> T005..T012 -> T013..T017 -> T018..T021 -> T022..T025 -> T026..T031`

任何 `T018..T021` 失败都阻断六例；任何六例业务失败都阻断内网全量；没有全量 50% 证据不得标记完成。

## 当前未关闭门禁

- T021：已关闭。`1885118` Step3 wall `158.13 -> 68.54s`（`-56.66%`），peak RSS `637868 -> 499704 KB`（`-21.66%`），swap 为 0。
- T024：已关闭。六例每例 Step3 wall 均低于当前基线，swap 均为 0；Step3 聚合 `450.40 -> 215.92s`（`-52.06%`），已越过本地 50% 参考线；以未改 Step1/2 基线合成的 T06 总计 `561.19 -> 326.71s`（`-41.78%`）。5 例 peak RSS 下降，`74155468` 增加 `536 KB`（`+0.29%`）。六例候选对 v67 共 `549/549` 个成果逐树比较全部 `changed=[]`。
- T025：ownership 兼容修复后最终 T06 全量测试 `487 passed in 60.09s`，0 failure、0 error、0 skip；其中内网验收门禁定向测试 `8 passed`。六例最终文件集一致，逐树比较 `549/549 changed=[]`；`1885118` 真实成果再次完成 `91/91` 文件校验，`73/73` 个稳定业务成果无差异，两个允许变化的 compact summary JSON 已由两侧一致的权威 topology audit CSV 重算一致，54 个非拓扑兼容业务键与冻结基线相等。T06 核心与 SpecKit 验收脚本仍全部低于 `61440 bytes`。
- T027/T029/T030：已关闭。内网候选 Step1/2 wall `5106s`、Step3 wall `13551s`、Step3 内部 `13530.559s`，T06 两组 wall 求和 `18657s`；peak RSS `8659380 KB`、swap=0、无 OOM/Killed。
- T028：首轮候选 `95/95` 个成果无缺失或新增，正式汇总、F-RCSD、relation、topology/surface/audit 均保持一致；唯一业务漂移为 RCSD Road `5396565520417723` 的 `candidate_segment_ids` 多出 `979772_1199453`。已把 `dwithin` 查询改为增加 `0.000001m` 的纯查询容差，最终仍用原 `<=50m` 精确距离过滤；本地六例 `549/549 changed=[]`，待内网复验关闭。
- T031：待兼容修复进入内网并关闭 T028 后完成。
