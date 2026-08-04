# 当前超阈值代码 / 脚本文件审计

## 范围

- 主审计日期：2026-06-12；T09 增量审计：2026-07-10；T10 性能与 60KB 治理增量审计：2026-07-11；T01/T06 ownership 增量审计：2026-07-12；T10 增加 T11 工作流增量审计：2026-07-13；T06 性能恢复与 Step3 修复性拆分增量审计：2026-07-14；T06 全量性能恢复增量审计：2026-07-16；T12 F-RCSD 质检、T10 可选接入及专用流水线增量审计：2026-07-18；T12 reviewed resume 与 false-positive hardening 增量审计：2026-07-19；T12 Road-surface portal 增量审计：2026-07-20；T12 anchored canonical alias raw portal 增量审计：2026-07-27；T12 反向路径 Segment 范围增量审计：2026-07-31；T12 T03/T07 Junction 质量输出与 T12-only 内网入口增量审计：2026-07-31；T03 Scheme A 当前快照与 T12 required movement 增量审计：2026-08-02；P04 Road 直出第二里程碑、冻结 Directional Road V2、High-Precision Road V3 与独立几何/拓扑 QA 增量审计：2026-07-21；P04 Segment-first Road直出增量审计：2026-07-22；P04 Segment-first LaneTopo 投影拆分增量审计：2026-07-23；P05 M0/M1/M2R/R2/PTO-P0/JSG-PTO-P0 神经 Road POC 增量审计：2026-07-21；P05 JSG-PTO-P1/P2/P3、方案 A baseline、Scheme-A-P1、Scheme-A-P2-P0 与 Scheme-A-Dataset-P0 增量审计：2026-07-22；P05 Scheme-A-P2-P1/P2-P2-P0/P2-P2-P1/P2-P2-P2-P0/P2-P2-P2-P1/P2-P2-P2-P2/P2-P3-P0/P2-P3-P1 增量审计：2026-07-23；P05 Scheme-A-P2-P3-P6/P9/P10/P11/P12R/P12R-R1/P13-P0 增量审计：2026-07-24
- P04主干物理交接、局部平滑与显式LaneTopo关系增量审计：2026-07-26。
- 阈值：单文件超过 `100 KB`
- 口径：按 `code-boundaries-and-entrypoints.md`，审计纳入版本管理的 `src/`、`scripts/`、`tests/`、`tools/` 下源码 / 脚本文件。
- 本表只记录结构债事实，不代表本轮进入对应模块正文治理。
- 用户于 2026-07-11 明确确认 T02 已废弃并授权本轮不拆分；T02 超线文件继续登记为结构债，但从本轮 60KB 收敛验收中排除，且本轮未触碰 T02 源码或测试。
- 2026-07-13 T10 增加 T11 工作流后的 Windows worktree 扫描确认：除下列 Retired T02 文件外，`>= 61440 bytes` 文件仍仅为 `step2_trunk_utils.py`（`62004` bytes）与 `step3_surface_aware_plan_release.py`（`74453` bytes），均低于 100KB 硬阈值且本轮未触碰；本轮修改的 9 个源码/脚本/测试文件全部低于 60KiB，最大为 `case_runner_pipeline.py`（`58855` bytes）。Final topology gate 已拆至 `step3_final_topology_gate.py`（`9687` bytes），hard-gate 级联 transition 收口已拆至 `step3_authoritative_transition_closure.py`（`14812` bytes）；主编排文件仍低于 100KB。
- 2026-07-14 T06 性能恢复轮次将 `step3_surface_aware_plan_release.py` 的 surface release 决策、输入索引与计划行构建职责拆至 `step3_surface_release_plan.py`；完成验证态审计传递与最终发布收口后，主编排文件为 `57187` bytes，新模块为 `19639` bytes，二者均低于 60KiB 安全线，既有正式入口与调用签名保持不变。本轮扫描 T06 的 `src/` 与 `tests/` 共 `153` 个源码/脚本文件，`>= 61440 bytes` 为 `0`。
- 2026-07-16 T06 全量性能恢复轮次发现后续回归新增用例使 `test_replacement_plan.py` 漂移到 `63163` bytes；已将末尾两个独立 risk-marker 用例迁移至 `test_replacement_plan_risk_markers.py`。拆分后原文件 `60142` bytes、新文件 `3534` bytes；新增 validation runtime / deferred final publish、deferred hard-gate plan、拓扑审计内存复用、ID 解析及内网验收包测试后，T06 `src/` 与 `tests/` 共 `160` 个源码/脚本文件，另有 `2` 个既有 `scripts/t06*` 脚本，核心合计 `162` 个；SpecKit 下另有 `3` 个一次性内网验收脚本，纳入体量扫描后总计 `165` 个，`>= 61440 bytes` 为 `0`。当前 T06 最大文件为本轮修改源码 `step3_surface_aware_plan_release.py`（`60870` bytes），其次为既有 `test_step3_surface_topology_audit.py`（`60787` bytes），均低于 60KiB。除 Retired T02 外仍只有本轮未触碰的 T01 `step2_trunk_utils.py` 超过 60KiB，作为既有治理缺口继续登记；正式入口和调用签名不变，一次性验收工件不登记为官方入口。
- 2026-07-18 T12 F-RCSD 质检轮次扫描全部 `29` 个新增/修改源码、脚本和测试：均低于 100KB 硬阈值；T12 模块最大文件为 `candidate_audit.py`（`15895` bytes），正式入口 `t12_run_frcsd_quality_audit.py` 为 `3899` bytes；两个 SpecKit 一次性 validation 脚本最大为 `validate_1026960.py`（`11717` bytes），不登记为官方入口。T10 可选接入后最大修改文件为 `t10_run_innernet_full_pipeline.sh`（`61439` bytes，低于 60KiB `61440` bytes），其次为 `case_runner_pipeline.py`（`60207` bytes）；T12 adapter 独立放在 `case_runner_t12.py`（`5070` bytes），未回填 case runner 主流程。T06 源码、契约和入口未修改。仓库级 `>=100KB` 仍仅为本轮未触碰的 Retired T02 历史文件。
- 2026-07-18 T10 F-RCSD 专用流水线最终联合扫描 `31` 个新增/修改源码、脚本和测试：`>=100KB` 为 `0`；最大为 `t10_run_innernet_full_pipeline.sh`（`62094` bytes），因增加 T11/T12 顺序、resume/manifest 和显式 `T12_CASE_MANIFEST` 转发而超过 60KiB 软预警线，但仍低于 100KB 硬阈值。新增正式入口 `t10_run_frcsd_quality_pipeline.sh` 为 `2351` bytes，入口测试为 `2648` bytes，`case_runner.py` 为 `49048` bytes；T06 源码、契约和入口未修改，仓库级 `>=100KB` 集合不变。后续 full runner 继续增长前应拆分 stage helper，不得回填模块算法。
- 2026-07-19 T12 reviewed resume 轮次修改 `2` 个既有脚本和 `2` 个入口契约测试：`t10_run_innernet_full_pipeline.sh` 为 `64067` bytes，`t10_run_frcsd_quality_pipeline.sh` 为 `2696` bytes，两个测试分别为 `8104` 与 `3237` bytes，均低于 100KB 硬阈值。full runner 已超过 60KiB 软预警线，本轮仅修复显式新 `T12_RUN_ID` 的 run-root/manifest 选择、失败恢复一致性与复核输入优先级，未增加算法职责；后续增长前仍须拆分 stage helper。
- 2026-07-19 T12 false-positive hardening 轮次扫描全部 `14` 个新增/修改源码、测试和 SpecKit validation 脚本：`>=100KB` 为 `0`；最大为 `candidate_audit.py`（`23435` bytes），新拆出的 `semantic_carrier.py` 为 `8348` bytes，最大一次性 validation 脚本 `analyze_alias_transitions.py` 为 `15836` bytes。正式入口、CLI 参数和 T10 阶段顺序均未改变；新增 semantic helper 只承接 portal-constrained carrier 的端点与内部 alias 门禁，不回填 candidate 主编排。
- 2026-07-20 T12 Road-surface portal 轮次扫描全部 `10` 个新增/修改源码、测试和 SpecKit validation 脚本：`>=100KB` 为 `0`；最大为 `candidate_audit.py`（`29673` bytes），新拆出的 `surface_portal_carrier.py` 为 `22950` bytes，`outputs.py` 为 `22016` bytes，一次性原始数据分析脚本 `analyze_anchored_surface_portals.py` 为 `17081` bytes。正式入口、CLI 参数与 T10 阶段顺序均未改变；新 helper 只承接双 T07 唯一标准面的 Road-surface 有向 carrier、anchor→frontier 支撑与 audit-only 距离证据，不包含对象 ID 特判。
- 2026-07-27 T12 anchored canonical alias raw portal 轮次扫描全部 `5` 个修改源码/测试文件：`>=100KB` 与 `>=60KiB` 均为 `0`；最大为 `candidate_audit.py`（`31453` bytes），`anchor_portals.py` 为 `14338` bytes，两个专项测试分别为 `15403` 与 `13184` bytes。变更只把 T05 选中 `base_id` mainNode 的 canonical raw alias group 展开为 Direction 严格的 raw portal；不递归展开其它 grouped node 的 group，未新增入口、CLI 参数、依赖或 Case/Segment 特判，`entrypoint-registry.md` 无需改变。
- 2026-07-31 T12 反向路径 Segment 范围轮次扫描全部 `9` 个新增/修改源码与测试文件：`>=100000 bytes` 与 `>=61440 bytes` 均为 `0`；最大为 `candidate_audit.py`（`52472` bytes），新增独立归属 helper `reverse_segment_scope.py` 为 `13467` bytes。变更复用 T06 已确认的 `20m / 50m / distance` ownership 排序，只在 T12 内增加双端标准面区间、逐 raw RCSD Road 唯一 Segment 归属及 additive 审计证据；未新增入口、CLI 参数或依赖，`entrypoint-registry.md` 无需改变。
- 2026-07-31 T12 T03/T07 Junction 质量输出轮次扫描全部 `17` 个新增/修改源码、脚本、测试和 SpecKit QGIS validation 文件：`>=100000 bytes` 为 `0`，`>=61440 bytes` 为 `1`。最大为既有 full runner `t10_run_innernet_full_pipeline.sh`（`67248` bytes），继续低于 100KB 硬阈值且只增加 T03/T07 handoff 与 Junction 输出登记；T12 最大既有文件 `candidate_audit.py` 为 `52638` bytes，新 Junction 主审计 `junction_audit.py` 为 `42074` bytes，QGIS validation 为 `10741` bytes。新增正式入口 `t12_rerun_frcsd_junction_quality_innernet.sh` 为 `6795` bytes，并已同步 `entrypoint-registry.md`；所有新职责拆入 `junction_inputs.py / junction_audit.py / junction_outputs.py`，未回填已超软线的 full runner 算法职责，仓库 `>=100KB` 集合不变。
- 2026-08-01 T03 全量 Case 准确性闭环轮次扫描全部 `38` 个新增/修改源码、脚本和测试文件：`>=100000 bytes` 为 `0`，`>=61440 bytes` 为 `1`。最大为 `step6_geometry_runner.py`（`66268` bytes）；新增 raw topology guard、ownership、业务连通性、Road-surface portal、compact target portal 与 surface regularization 均拆为独立内部模块，一次性 QGIS validation 为 `12006` bytes，未新增正式入口、CLI 参数或依赖，`entrypoint-registry.md` 无需改变。`step6_geometry_runner.py` 已超过 60KiB 观察线但仍低于 100KB 硬阈值，后续新增职责前应优先拆出 summary/result publication 编排。
- 2026-08-02 Scheme A 当前快照重建与 T12 required Junction movement 轮次扫描全部 `41` 个新增/修改源码、脚本和测试文件：`>=100000 bytes` 为 `0`，`>=61440 bytes` 为 `1`。最大仍为 `step6_geometry_runner.py`（`72857` bytes）；T12 新 required movement helper `junction_required_movements.py` 为 `25132` bytes，主审计 `junction_audit.py` 为 `52978` bytes。新增逻辑独立承接 boundary arm heading、raw Direction carrier 与 snapshot-scoped QA 真值回归，未新增正式入口、CLI 参数或依赖，`entrypoint-registry.md` 无需改变。`step6_geometry_runner.py` 继续登记为下一轮新增职责前必须优先拆分的观察项。
- 2026-07-21 P04 Road 直出第二里程碑、冻结 Directional Road V2、High-Precision Road V3、双向证据塌缩降级、物理走廊、三类几何来源及独立几何/拓扑 QA 扫描 P04 `src/`、`tests/` 与 V3 SpecKit `validation/` 共 `56` 个 `.py` 文件：`>=61440 bytes` 与 `>=100KB` 均为 0；最大为 `directional_evidence.py`（`42766` bytes），V3 最大为 `high_precision_geometry.py`（`37608` bytes），新增 V2 对照 helper 为 `6170` bytes，性能 replay validation 为 `2179` bytes。directional/high-precision 的 evidence、geometry、comparison、movement、quality、topology、pipeline、QGIS 与测试按职责隔离。新增/修改均为模块内研究 callable、测试和一次性验证工件，不新增 repo CLI/root script，不修改 M2、冻结 V2、T00-T12 V1、`scripts/` 或入口 registry，仓库超阈值集合不变。
- 2026-07-22 P04 Segment-first 目标覆盖迭代扫描 `24` 个源码与 `19` 个专项测试：`>=61440 bytes` 与 `>=100KB` 均为0；最大源码为`segment_first_pipeline.py`（`57688` bytes），其次为`segment_first_nodes.py`（`52055` bytes），最大测试为`test_segment_first_nodes.py`（`14890` bytes）。本轮新增 JunctionUnit endpoint surface 恢复候选及已发布 carrier 几何重叠冲突保护，未新增 repo CLI/root script，未修改 T01–T12、`scripts/`或入口 registry。
- 2026-07-23 P04 Segment-first LaneTopo 投影与 endpoint surface 定向救援迭代后扫描 `25` 个 `segment_first*.py` 源码与 `19` 个专项测试：`>=61440 bytes` 为 `1`、`>=100KB` 为 `0`。主编排 `segment_first_pipeline.py` 为 `88766` bytes；LaneTopo 正式 Road 投影、父 Road 同载体识别、Lane 级拒绝归集、已接受物理交接复用和 Junction carrier path 查询保持在 `segment_first_lane_topo.py`（`10857` bytes）。Endpoint 候选只使用 T07/T03/T04 accepted surface，且仅在普通构图产生 Junction rejected spoke、同时存在贯通两端面的 Patch 候选时定向重选；不完整方向先剔除，再复用既有 DriveZone 约束反向推导，未进入救援的 Segment 保持原候选选择。Road-Lane 正式关系同时按 Patch Road lineage 与 Road `source_lane_ids` 编译，覆盖 Lane fragment 直出 Road。本轮未新增正式入口，未修改 T01–T12、`scripts/` 或入口 registry；主编排后续仍应继续拆出 network rebuild/summary职责，不得回填投影算法。
- 2026-07-23 P04 Segment-first 分布式路口与物理方向链审计迭代后扫描 `25` 个 `segment_first*.py` 源码与 `22` 个专项测试：源码`>=61440 bytes`为`3`、测试`>=61440 bytes`为`0`、全部`>=100KB`为`0`。最大源码`segment_first_pipeline.py`为`92988` bytes，其次`segment_first_carriers.py`为`65432` bytes、`segment_first_nodes.py`为`63099` bytes；最大测试`test_segment_first_nodes.py`为`34974` bytes。新增 SWSD-only portal 的 DriveZone 物理支撑门禁、跨 Segment 分离 portal、accepted surface 可信锚点保留、最终 Node 坐标审计、ordinary 分布式 portal 和 QGIS 方向链 PASS/FAIL 分类样式；未新增正式入口，未修改 T01–T12、`scripts/`或入口 registry。`segment_first_pipeline.py`距100KB硬阈值不足10KB，`segment_first_nodes.py`已超过60KiB观察线，后续禁止继续回填新职责，必须优先拆出 network rebuild/summary 与 endpoint resolution/connection audit。
- 2026-07-24 P04 SWSD路口先验保护、稳定Road lineage细分与多Road LaneTopo链迭代后扫描 `26` 个 `segment_first*.py` 源码与 `23` 个专项测试：源码`>=61440 bytes`为`3`、测试`>=61440 bytes`为`0`、全部`>=100000 bytes`为`0`。最大源码`segment_first_pipeline.py`为`96321` bytes，其次`segment_first_carriers.py`为`65464` bytes、`segment_first_nodes.py`为`64396` bytes；新增`segment_first_lineage.py`为`27918` bytes。细分职责独立承接Junction保护、父Road精确子串、内部Node增量物化和审计重映射；LaneTopo链投影仍留在`segment_first_lane_topo.py`。未新增正式入口，未修改T01–T12、`scripts/`或入口registry。主编排距100000字节硬阈值仅3679字节，下一轮源码新增职责前必须先拆分。
- 2026-07-25 P04 SWSD Access切分lineage、方向化Road-Lane关系和完整路口结构审计迭代后扫描`33`个`segment_first*.py`源码与`28`个专项测试：源码`>=61440 bytes`为`3`、测试`>=61440 bytes`为`0`、全部`>=100000 bytes`为`0`。最大源码`segment_first_pipeline.py`为`94714` bytes，其次`segment_first_nodes.py`为`68350` bytes、`segment_first_carriers.py`为`65464` bytes；Road-Lane局部方向匹配下沉到`segment_first_road_lane.py`（`6315` bytes），SWSD Junction结构聚合下沉到`segment_first_swsd_junction_audit.py`（`4951` bytes）。本轮未新增正式入口，未修改T01–T12、`scripts/`或入口registry；主编排只保留调用与发布挂接。
- 2026-07-26 P04 T04 accepted surface、LaneTopo与局部连接Road三重证据约束的复杂路口显式关系迭代后扫描`33`个`segment_first*.py`源码与`28`个专项测试：源码`>=61440 bytes`为`3`、测试`>=61440 bytes`为`0`、全部`>=100000 bytes`为`0`。最大源码`segment_first_pipeline.py`为`94774` bytes，其次`segment_first_nodes.py`为`70163` bytes、`segment_first_carriers.py`为`65464` bytes；复杂路口规则保留在`segment_first_junction_topology.py`（`28328` bytes），主编排仅增加`connection_evidence`挂接。专项测试`201 passed`；未新增正式入口，未修改T01–T12、`scripts/`或入口registry。
- 2026-07-26 P04 SWSD完整路口、LaneGroup细Road和分布式方向portal收敛后扫描`33`个`segment_first*.py`源码与`28`个专项测试：源码`>=61440 bytes`为`3`、测试`>=61440 bytes`为`0`、全部`>=100000 bytes`为`0`。最大源码`segment_first_pipeline.py`为`94971` bytes，其次`segment_first_nodes.py`为`78887` bytes、`segment_first_carriers.py`为`78790` bytes；最大测试`test_segment_first_nodes.py`为`50732` bytes。目标端点裁切仍只在主编排挂接；受限保留语义桥LaneTopo映射留在`segment_first_lane_topo.py`，built/retained portal分离和surface交点Node留在`segment_first_nodes.py`。专项测试`212 passed`；未新增正式入口，未修改T01–T12、`scripts/`或入口registry。`segment_first_pipeline.py`距100000字节仅5029字节，`segment_first_nodes.py`新增职责前必须拆分。
- 2026-07-24 P04 accepted surface保护域、部分证据端点补全、SWSD方向路径审计与QGIS CRS修复后扫描`34`个`segment_first*.py`源码与`29`个专项测试：源码`>=61440 bytes`为`3`、测试`>=61440 bytes`为`0`、全部`>=100000 bytes`为`0`。最大源码`segment_first_pipeline.py`为`96729` bytes，其次`segment_first_carriers.py`为`80725` bytes、`segment_first_nodes.py`为`78887` bytes；`segment_first_swsd_paths.py`为`11985` bytes，`segment_first_qgis.py`为`23350` bytes。最大测试`test_segment_first_nodes.py`为`50732` bytes，专项回归`221 passed`。主编排只增加SWSD方向路径审计挂接且正式发布角色为空；端点补全逻辑留在carrier模块，QGIS只增加CRS序列化。未新增正式入口，未修改T01–T12、`scripts/`或入口registry；`segment_first_pipeline.py`距100000字节仅3271字节，后续新增职责前必须拆分。
- 2026-07-24 P04 fallback证据占用固定点、SWSD唯一方向路径发布与单member缺方向恢复后扫描`35`个`segment_first*.py`源码与`29`个专项测试：源码`>=61440 bytes`为`3`、测试`>=61440 bytes`为`0`、全部`>=100000 bytes`为`0`。最大源码`segment_first_pipeline.py`为`97742` bytes，其次`segment_first_carriers.py`为`86143` bytes、`segment_first_nodes.py`为`79087` bytes；新增`segment_first_member_recovery.py`为`3303` bytes，恢复候选冲突重协调继续位于`segment_first_access_recovery.py`（`14183` bytes）。最大测试`test_segment_first_nodes.py`为`52325` bytes，专项回归`225 passed`。本轮未新增正式入口，未修改T01–T12、`scripts/`或入口registry；主编排距100000字节仅2258字节，后续新增任何职责前必须先拆分。
- 2026-07-24 P04 accepted endpoint surface短桥接与V57单调恢复后扫描`36`个`segment_first*.py`源码与`29`个专项测试：源码`>=61440 bytes`为`3`、测试`>=61440 bytes`为`0`、全部`>=100000 bytes`为`0`。最大源码`segment_first_pipeline.py`为`97742` bytes，其次`segment_first_carriers.py`为`88360` bytes、`segment_first_nodes.py`为`79087` bytes；新增`segment_first_surface_bridge.py`为`5273` bytes，surface-to-surface证据识别已下沉，carrier只保留调用与推导编排。最大测试`test_segment_first_nodes.py`为`52325` bytes，`test_segment_first_target_carriers.py`为`47186` bytes，专项回归`226 passed`。本轮未新增正式入口，未修改T01–T12、`scripts/`或入口registry；主编排距100000字节仅2258字节，carriers新增职责前必须继续拆分。
- 2026-07-25 P04 局部RoadSurface端点路由与V61单调恢复后扫描`37`个`segment_first*.py`源码与`30`个专项测试：源码`>=61440 bytes`为`3`、测试`>=61440 bytes`为`0`、全部`>=100000 bytes`为`0`。最大源码`segment_first_pipeline.py`为`97742` bytes，其次`segment_first_carriers.py`为`88871` bytes、`segment_first_nodes.py`为`79087` bytes；新增`segment_first_surface_routing.py`为当前独立小模块，Movement端点面外尾段审计保留在`segment_first_movements.py`（`37081` bytes）。最大测试`test_segment_first_nodes.py`为`52325` bytes、`test_segment_first_target_carriers.py`为`47186` bytes，专项回归`230 passed`。本轮未新增正式入口，未修改T01–T12、`scripts/`或入口registry；主编排距100000字节仅2258字节，carrier与pipeline后续仍禁止回填新职责。
- 2026-07-25 P04 Road端点严格入面、人工surface优先与THROUGH实际穿面约束迭代后扫描`41`个`segment_first*.py`源码与`33`个专项测试：源码`>=61440 bytes`为`3`、测试`>=61440 bytes`为`0`、全部`>=100000 bytes`为`0`。最大源码`segment_first_pipeline.py`为`97984` bytes，其次`segment_first_nodes.py`为`97571` bytes、`segment_first_carriers.py`为`93331` bytes；端点内缩目标和局部路由继续位于`segment_first_surface_routing.py`，T07端点surface与T04 topology解耦位于`segment_first_junctions.py`，accepted polygon的THROUGH仅在Road实际穿入内缩surface时切分，只有同一T01 Segment正式retained lineage唯一时允许不移动几何的投影细分。最大测试`test_segment_first_nodes.py`为`57813` bytes，专项回归`253 passed`。本轮未新增正式入口，未修改T01–T12、`scripts/`或入口registry；主编排距100000字节仅2016字节，nodes距100000字节仅2429字节，二者后续不得继续增加职责。
- 2026-07-21 P05 M0/M1 轮次扫描全部 `23` 个新增源码和测试文件：`>=100KB` 为 `0`，全部低于 60KiB；最大为 `m1_dataset.py`（`46059` bytes），其次为 `m1_inference.py`（`30880` bytes）和 `m1_training.py`（`24335` bytes）。本轮新增锁定的 `p05-neural` optional dependency，但未新增 `scripts/`、repo CLI、`__main__.py` 或 Makefile 目标；`entrypoint-registry.md` 无需改变，P05 仅提供模块 callable。
- 2026-07-21 P05 M2R 增量新增 `13` 个源码和测试文件；与 M0/M1 合并扫描 P05 全部 `36` 个源码和测试文件，`>=100KB` 与 `>=60KiB` 均为 `0`。全模块最大仍为 `m1_dataset.py`（`46059` bytes）；M2R 最大为 `m2r_dataset.py`（`34230` bytes），其次为 `m2r_training.py`（`31334` bytes）和 `m2r_supervision.py`（`29364` bytes）。M2R 未新增或修改 `scripts/`、repo CLI、`__main__.py`、Makefile 或 T10 stage，`entrypoint-registry.md` 无需改变；对外能力仅为模块 callable。
- 2026-07-21 P05 R2 增量新增 `7` 个源码和 `4` 个测试文件；与 M0/M1/M2R 合并扫描 P05 全部 `47` 个源码和测试文件，`>=100KB` 与 `>=60KiB` 均为 `0`。全模块最大仍为 `m1_dataset.py`（`46059` bytes）；R2 最大为 `r2_gate2.py`（`39095` bytes），其次为 `r2_oof.py`（`33779` bytes）和 `r2_oracle.py`（`21928` bytes）。R2 未新增或修改 `scripts/`、repo CLI、`__main__.py`、Makefile 或 T10 stage，`entrypoint-registry.md` 无需改变；对外能力仅为模块 callable。
- 2026-07-21 P05 PTO-P0 增量新增 `5` 个源码和 `3` 个测试文件；与 M0/M1/M2R/R2 合并扫描 P05 全部 `55` 个源码和测试文件，`>=100KB` 与 `>=60KiB` 均为 `0`。全模块最大仍为 `m1_dataset.py`（`46059` bytes）；PTO-P0 最大为 `pto_p0.py`（`25433` bytes），其次为 `pto_candidates.py` 与 `pto_solver.py`。PTO-P0 未新增或修改 `scripts/`、repo CLI、`__main__.py`、Makefile 或 T10 stage，`entrypoint-registry.md` 无需改变；对外能力仅为模块 callable。
- 2026-07-21 P05 JSG-PTO-P0 增量新增 `5` 个源码和 `4` 个测试文件；与此前阶段合并扫描 P05 全部 `64` 个源码和测试文件，`>=100KB` 与 `>=60KiB` 均为 `0`。全模块最大仍为 `m1_dataset.py`（`46059` bytes）；JSG-PTO-P0 最大为 `jsg_truth.py`（`43326` bytes），其次为 `jsg_p0.py`（`16975` bytes）。本轮未新增或修改 `scripts/`、repo CLI、`__main__.py`、Makefile 或 T10 stage，`entrypoint-registry.md` 无需改变；对外能力仅为模块 callable。
- 2026-07-22 P05 JSG-PTO-P1 增量新增 `4` 个源码和 `4` 个测试文件；与此前阶段合并扫描 P05 全部 `72` 个源码和测试文件，`>=100KB` 与 `>=60KiB` 均为 `0`。全模块最大仍为 `m1_dataset.py`（`46059` bytes）；P1 最大为 `jsg_p1_solver.py`（`31968` bytes），其次为 `jsg_p1_candidates.py`（`29334` bytes）。本轮未新增或修改 `scripts/`、repo CLI、`__main__.py`、Makefile 或 T10 stage，`entrypoint-registry.md` 无需改变；对外能力仅为模块 callable。
- 2026-07-22 P05 JSG-PTO-P2 增量新增 `6` 个源码和 `4` 个测试文件；与此前阶段合并扫描 P05 全部 `82` 个源码和测试文件，`>=100KB` 与 `>=60KiB` 均为 `0`。全模块最大仍为 `m1_dataset.py`（`46059` bytes）；P2 最大为 `jsg_p2_oof.py`（`41306` bytes），其次为 `jsg_p2_dataset.py`（`21836` bytes）。本轮未新增或修改 `scripts/`、repo CLI、`__main__.py`、Makefile 或 T10 stage，`entrypoint-registry.md` 无需改变；对外能力仅为模块 callable。
- 2026-07-22 P05 JSG-PTO-P3 完成态扫描 P05 全部 `97` 个源码和测试文件，`>=100KB` 与 `>=60KiB` 均为 `0`。全模块最大仍为 `m1_dataset.py`（`46059` bytes），P3 最大为 `jsg_p3_oof.py`（`42828` bytes），其次为 `jsg_p3_dataset.py`、`jsg_p3_training.py` 与 `jsg_p3_evidence.py`；所有 P3 文件均低于硬阈值。P3 只新增模块 callable 与内部数据/模型/审计实现，未新增或修改 `scripts/`、repo CLI、`__main__.py`、Makefile 或 T10 stage，`entrypoint-registry.md` 无需改变。
- 2026-07-22 P05 方案 A baseline 完成态扫描 P05 全部 `105` 个源码和测试文件，`>=100KB` 与 `>=60KiB` 均为 `0`。全模块最大为新 `scheme_a_baseline.py`（`58135` bytes），其职责已将 label/fallback/model 分别拆到 `scheme_a_labels.py`、`scheme_a_fallback.py`、`scheme_a_models.py`；其余新测试与源码均低于 10KB。方案 A 只新增模块 callable，未新增或修改 `scripts/`、repo CLI、`__main__.py`、Makefile 或 T10 stage，`entrypoint-registry.md` 无需改变。
- 2026-07-22 P05 Scheme-A-P1 完成态扫描 P05 全部 `119` 个源码和测试文件，`>=100KB` 与 `>=60KiB` 均为 `0`。全模块最大仍为 `scheme_a_baseline.py`（`58135` bytes）；P1 最大为 `scheme_a_p1_candidates.py`（`43306` bytes），其次为 `scheme_a_p1_oof.py`（`42629` bytes）、`scheme_a_p1_training.py`（`33588` bytes）。P1 只新增模块 callable，未新增或修改 `scripts/`、repo CLI、`__main__.py`、Makefile 或 T10 stage；一次性 QGIS 审计脚本位于 `outputs/_work/`，不属于长期入口，`entrypoint-registry.md` 无需改变。
- 2026-07-22 P05 Scheme-A-P2-P0 完成态扫描 P05 核心 `src/` 与 `tests/` 共 `122` 个源码和测试文件，连同本 SpecKit 一次性 QGIS 审计脚本均 `>=100KB=0`、`>=60KiB=0`。全模块最大仍为 `scheme_a_baseline.py`（`58135` bytes），P2 最大为 `scheme_a_p2_oracle.py`（`54641` bytes）；一次性 `qgis_p2_input_audit.py`（`5294` bytes）仅用于 51 Case 输入几何审计，不登记为正式入口。P2-P0 只新增模块 callable，未新增或修改 `scripts/`、repo CLI、`__main__.py`、Makefile 或 T10 stage，`entrypoint-registry.md` 无需改变。
- 2026-07-22 P05 Scheme-A-Dataset-P0 完成态扫描 P05 `src/` 与 `tests/` 共 `125` 个源码和测试文件，`>=100KB=0`、`>=60KiB=0`。全模块最大仍为 `scheme_a_baseline.py`（`58135` bytes）；Dataset-P0 主实现 `scheme_a_dataset_p0.py` 为 `51752` bytes，models 为 `2337` bytes，测试为 `7785` bytes。Dataset-P0 只新增模块 callable，未新增或修改 `scripts/`、repo CLI、`__main__.py`、Makefile 或 T10 stage，`entrypoint-registry.md` 无需改变。
- 2026-07-23 P05 Scheme-A-P2-P1 完成态扫描 P05 `src/` 与 `tests/` 共 `133` 个源码和测试文件，`>=100KB=0`、`>=60KiB=0`。全模块最大仍为 `scheme_a_baseline.py`（`58135` bytes）；P2-P1 最大为 `scheme_a_p2_p1_training.py`（`39360` bytes），其余 dataset、Node carrier、OOF、audit、execution、models 与专项测试均低于 `31KB`。P2-P1 只新增模块 callable，未新增或修改 `scripts/`、repo CLI、`__main__.py`、Makefile 或 T10 stage；`entrypoint-registry.md` 无需改变。
- 2026-07-23 P05 Scheme-A-P2-P2-P0 完成态扫描 P05 `src/` 与 `tests/` 共 `135` 个源码和测试文件，`>=100KB=0`、`>=60KiB=0`。全模块最大仍为 `scheme_a_baseline.py`（`58135` bytes）；新增内部审计实现 `scheme_a_p2_p2_p0_audit.py` 为 `36487` bytes，专项测试为 `11911` bytes。P2-P2-P0 未新增或修改 `scripts/`、repo CLI、`__main__.py`、Makefile、T10 stage或模块正式接口，`entrypoint-registry.md` 无需改变。
- 2026-07-23 P05 Scheme-A-P2-P2-P2-P0 完成态扫描 P05 `src/` 与 `tests/` 共 `146` 个源码和测试文件，`>=100KB=0`、`>=60KiB=0`。全模块最大仍为 `scheme_a_baseline.py`（`58135` bytes）；本阶段新增 models/evidence/probe/audit 四个内部模块与一份专项测试，最大为 `scheme_a_p2_p2_p2_p0_evidence.py`（`25045` bytes），audit 为 `24847` bytes，其余低于 `12KB`。未新增或修改 `scripts/`、repo CLI、`__main__.py`、Makefile、T10 stage 或模块正式接口，`entrypoint-registry.md` 无需改变。
- 2026-07-23 P05 Scheme-A-P2-P2-P2-P1 完成态扫描 P05 `src/` 与 `tests/` 共 `149` 个源码和测试文件，`>=100KB=0`、`>=60KiB=0`。全模块最大仍为 `scheme_a_baseline.py`（`58135` bytes）；本阶段新增的只读 attribution audit 为 `39829` bytes，models 为 `1930` bytes，专项测试为 `2965` bytes。未新增或修改 `scripts/`、`tools/`、repo CLI、`__main__.py`、Makefile、T10 stage 或模块正式接口，`entrypoint-registry.md` 无需改变。
- 2026-07-23 P05 Scheme-A-P2-P2-P2-P2 完成态扫描 P05 `src/` 与 `tests/` 共 `152` 个源码和测试文件，`>=100KB=0`、`>=60KiB=0`。全模块最大仍为 `scheme_a_baseline.py`（`58135` bytes）；本阶段新增只读 audit/models/test 分别为 `29708/2739/4203` bytes。未新增或修改 `scripts/`、`tools/`、repo CLI、`__main__.py`、Makefile、T10 stage 或模块正式接口，`entrypoint-registry.md` 无需改变。
- 2026-07-23 P05 Scheme-A-P2-P3-P0 完成态扫描 P05 `src/` 与 `tests/` 共 `158` 个源码和测试文件，`>=100KB=0`、`>=60KiB=0`。全模块最大仍为 `scheme_a_baseline.py`（`58135` bytes）；本阶段新增 5 个内部源码和 1 个专项测试，最大为 `scheme_a_p2_p3_p0_oof.py`（约 `31KB`），其余均低于 `24KB`。未新增或修改 `scripts/`、`tools/`、repo CLI、`__main__.py`、Makefile、T10 stage 或模块正式接口，`entrypoint-registry.md` 无需改变。
- 2026-07-23 P05 Scheme-A-P2-P3-P1 完成态扫描 P05 `src/` 与 `tests/` 共 `161` 个源码和测试文件，`>=100KB=0`、`>=60KiB=0`。全模块最大仍为 `scheme_a_baseline.py`（`58135` bytes）；本阶段新增只读 audit/models/test 分别为 `54763/2704/3724` bytes，均低于硬阈值。未新增或修改 `scripts/`、`tools/`、repo CLI、`__main__.py`、Makefile、T10 stage 或模块正式接口，`entrypoint-registry.md` 无需改变。
- 2026-07-24 P05 Scheme-A-P2-P3-P6 完成态扫描 P05 `src/` 与 `tests/` 共 `182` 个源码和测试文件，`>=100KB=0`、`>=60KiB=0`。全模块最大仍为 `scheme_a_baseline.py`（`58135` bytes）；本阶段新增只读 audit/models/test 分别为 `42802/3398/7214` bytes，`__init__.py` 为 `9527` bytes。未新增或修改 `scripts/`、`tools/`、repo CLI、`__main__.py`、Makefile、T10 stage 或正式入口，`entrypoint-registry.md` 无需改变。
- 2026-07-24 P05 Scheme-A-P2-P3-P9 完成态扫描 P05 `src/` 与两处 `tests/` 共 `193` 个源码和测试文件，`>=100KB=0`、`>=60KiB=0`。全模块最大仍为 `scheme_a_baseline.py`（`58135` bytes）；P9新增 models/source/training/oof/test 分别为 `3592/15263/17821/41415/6582` bytes。一次性runner位于`outputs/_work/`，不登记为正式入口；未新增或修改`scripts/`、`tools/`、repo CLI、`__main__.py`、Makefile、T10 stage或T01–T12实现，`entrypoint-registry.md`无需改变。
- 2026-07-24 P05 Scheme-A-P2-P3-P10 完成态扫描 P05 `src/` 与两处 `tests/` 共 `195` 个源码和测试文件，`>=100KB=0`、`>=60KiB=0`。全模块最大仍为 `scheme_a_baseline.py`（`58135` bytes）；P10只读人工裁决复算实现与专项测试分别为`24457/8669` bytes。P10未新增或修改`scripts/`、`tools/`、repo CLI、`__main__.py`、Makefile、T10 stage、模块正式接口或T01–T12实现，`entrypoint-registry.md`无需改变。
- 2026-07-24 P05 Scheme-A-P2-P3-P11 人工审计收口态扫描 P05 `src/` 与两处 `tests/` 共 `197` 个源码和测试文件，`>=100KB=0`、`>=60KiB=0`。全模块最大仍为 `scheme_a_baseline.py`（`58135` bytes）；P11只读归因、人工CSV冻结实现与专项测试分别为`51496/16350` bytes。P11未新增或修改`scripts/`、`tools/`、repo CLI、`__main__.py`、Makefile、T10 stage、模块正式接口或T01–T12实现，`entrypoint-registry.md`无需改变。
- 2026-07-24 P05 Scheme-A-P2-P3-P12R 完成态扫描 P05 `src/` 与两处 `tests/` 共 `200` 个源码和测试文件，`>=100KB=0`、`>=60KiB=0`。新增只读审计、models与专项测试分别为`61410/3291/4817` bytes；最大文件`scheme_a_p2_p3_p12r_audit.py`低于60KiB软预警线，职责限于6 Case提右真值重建、候选上限和工件编排，后续候选补强仍应拆出endpoint/JunctionUnit candidate builder，避免回填主审计。P12R未新增或修改`scripts/`、`tools/`、repo CLI、`__main__.py`、Makefile、T10 stage、T01–T12实现或正式入口，`entrypoint-registry.md`无需改变。
- 2026-07-24 P05 Scheme-A-P2-P3-P12R-R1 完成态扫描 P05 `src/` 与两处 `tests/` 共 `204` 个源码和测试文件，`>=100KB=0`、`>=60KiB=0`。R1新增models/candidate builder/audit/专项测试分别为`2086/14997/31577/5154` bytes；全模块最大仍为P12R审计`61410` bytes，R1未回填该主审计。R1只新增P05内部callable与测试，未新增或修改`scripts/`、`tools/`、repo CLI、`__main__.py`、Makefile、T10 stage、T01–T12实现或正式入口，`entrypoint-registry.md`无需改变。
- 2026-07-24 P05 Scheme-A-P2-P3-P13-P0 完成态扫描 P05 `src/` 与两处 `tests/` 共 `210` 个源码和测试文件，`>=100KB=0`、`>=60KiB=0`。P13-P0新增models/dataset/network/training/OOF/专项测试分别为`4146/28689/4140/28922/33571/5637` bytes；全模块最大仍为P12R审计`61410` bytes，P13-P0未回填该主审计。P13-P0只新增P05内部callable、训练实现与测试，未新增或修改`scripts/`、`tools/`、repo CLI、`__main__.py`、Makefile、T10 stage、T01–T12实现或正式入口，`entrypoint-registry.md`无需改变。

## 结果

| 路径 | 体量 | 当前判断 | 建议 |
|---|---:|---|---|
| `src/rcsd_topo_poc/modules/t02_junction_anchor/virtual_intersection_poc.py` | `1030609` bytes | 远超阈值，已构成显著结构债 | 本轮仅刷新审计；后续若继续触碰，需附拆分计划或豁免说明 |
| `tests/modules/t02_junction_anchor/test_virtual_intersection_poc.py` | `262747` bytes | 测试文件超阈值 | 后续若继续扩写，需附拆分计划、夹具下沉或按阶段拆分说明 |
| `src/rcsd_topo_poc/modules/t02_junction_anchor/stage4_step4_event_interpretation.py` | `124157` bytes | T02 Stage4 event interpretation 文件超阈值 | 后续若继续触碰，需先拆分 Step4 interpretation / candidate helper / audit 输出职责或附豁免说明 |
| `tests/modules/t02_junction_anchor/test_stage4_divmerge_virtual_polygon.py` | `118378` bytes | T02 Stage4 集成测试超阈值 | 后续若继续扩写，需按场景拆分测试文件或下沉共享 fixture |
| `src/rcsd_topo_poc/modules/t02_junction_anchor/stage4_geometry_utils.py` | `109693` bytes | T02 Stage4 geometry helper 超阈值 | 后续若继续触碰，需拆分 geometry primitive / topology helper / vector export 职责 |

## 未超阈值高风险预警

| 路径 | 体量 | 当前判断 | 建议 |
|---|---:|---|---|
| `src/rcsd_topo_poc/modules/t02_junction_anchor/stage4_divmerge_virtual_polygon.py` | `85713` bytes | T02 Stage4 脚本当前低于硬阈值但仍偏大，历史审计记录已刷新 | 后续若继续触碰，需附拆分计划或豁免说明 |
| `src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/_runtime_step4_kernel.py` | `56445` bytes | Step4 runtime kernel 仍承接 final event interpretation 主流程，低于硬阈值但偏大 | 后续若扩展 kernel 主流程，优先拆 multibranch / event-interpretation orchestration |
| `src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/_rcsd_selection_support.py` | `53259` bytes | RCSD selection support 聚合 semantic group、local/aggregated unit 与 role mapping 支撑逻辑；RCSD trace 只允许 degree-2 passthrough | 后续扩展 RCSD 选择支撑前先评估 local-unit / aggregated-unit helper 拆分 |
| `src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/polygon_assembly.py` | `49351` bytes | T-01 已拆出 raster/path helper，主 assembly 文件降至 50 KB 以下 | 后续继续保持主流程不回填低层 raster/path helper |
| `src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/_runtime_step4_geometry_base.py` | `48003` bytes | 原 `_runtime_step4_geometry_reference.py` 已改名为 geometry base，低于阈值 | 后续避免重新引入 `reference` 命名误导 |
| `src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/outputs.py` | `48524` bytes | T04 输出层新增 arbiter ledger / decision trace / review index 字段后接近 50 KB | 后续新增输出字段前优先拆 review-index writer / audit writer helper |
| `src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/_event_interpretation_unit_preparation.py` | `41565` bytes | Round 2 新拆出的 unit preparation / pair-local materialization 模块 | 后续仅承接 preparation 与 scope materialization，不承接 candidate selection |
| `src/rcsd_topo_poc/modules/p01_arm_build/final_arm_validation.py` | `53011` bytes | FinalArm relaxed reverse / supplemental trace validation 实现 | 后续若继续扩展 validation 分支，优先拆 validation builder 与 evidence helper |
| `src/rcsd_topo_poc/modules/p01_arm_build/review.py` | `52972` bytes | P01 retained audit PNG / review GPKG 图层 helper | 后续 review 输出扩展先评估 layer builder / png renderer 拆分 |

## 本轮授权排除的 Retired T02 60KB 结构债快照

以下 11 个 tracked 文件为 2026-07-11 实时扫描结果。它们因用户明确授权不拆分而不进入本轮 60KB 通过计数，但仍保留结构债登记；本轮未写入这些文件。

| 路径 | 当前体量 |
|---|---:|
| `src/rcsd_topo_poc/modules/t02_junction_anchor/virtual_intersection_poc.py` | `1030609` bytes |
| `tests/modules/t02_junction_anchor/test_virtual_intersection_poc.py` | `262747` bytes |
| `src/rcsd_topo_poc/modules/t02_junction_anchor/stage4_step4_event_interpretation.py` | `124157` bytes |
| `tests/modules/t02_junction_anchor/test_stage4_divmerge_virtual_polygon.py` | `118378` bytes |
| `src/rcsd_topo_poc/modules/t02_junction_anchor/stage4_geometry_utils.py` | `109693` bytes |
| `src/rcsd_topo_poc/modules/t02_junction_anchor/virtual_intersection_full_input_poc.py` | `86865` bytes |
| `src/rcsd_topo_poc/modules/t02_junction_anchor/stage4_divmerge_virtual_polygon.py` | `85713` bytes |
| `src/rcsd_topo_poc/modules/t02_junction_anchor/stage4_step5_geometric_support.py` | `85327` bytes |
| `src/rcsd_topo_poc/modules/t02_junction_anchor/text_bundle.py` | `76715` bytes |
| `src/rcsd_topo_poc/modules/t02_junction_anchor/stage3_step7_acceptance.py` | `72552` bytes |
| `src/rcsd_topo_poc/modules/t02_junction_anchor/stage2_anchor_recognition.py` | `71129` bytes |

## 本轮已拆分降险记录

| 原路径 / 新模块 | 体量 | 当前判断 | 建议 |
|---|---:|---|---|
| `src/rcsd_topo_poc/modules/t03_virtual_junction_anchor/step3_engine.py` | `101033 -> 40782` bytes | T10 性能治理中保留 Step3 public API、graph/dijkstra monkeypatch 点、reachable cache 与主编排；geometry/status 支撑已下沉 | 保持 graph 可测试替换点与主状态编排，不回填基础几何 helper |
| `src/rcsd_topo_poc/modules/t03_virtual_junction_anchor/step3_engine_support.py` | `49911` bytes | 新拆出的 Step3 mask、single-sided、foreign object、containment 与状态构建支撑 | 达到 50KB 前继续按 mask/status 职责拆分 |
| `src/rcsd_topo_poc/modules/t03_virtual_junction_anchor/step3_engine_primitives.py` | `21280` bytes | 新拆出的 Step3 geometry/vector/road primitive 与默认审计字段 helper | 保持无 Case 主编排职责 |
| `src/rcsd_topo_poc/modules/t03_virtual_junction_anchor/step3_engine_models.py` | `984` bytes | 新拆出的 reachable-road cache 内部模型 | 保持仅定义 dataclass |
| `src/rcsd_topo_poc/modules/t03_virtual_junction_anchor/step6_geometry.py` | `100384 -> 26180` bytes | 保留 Step6 directional-cut、single-sided trace monkeypatch 点与兼容 public API；正式 build/status 通过惰性 wrapper 调用 runner | 保持测试替换点和兼容签名，不回填主几何编排 |
| `src/rcsd_topo_poc/modules/t03_virtual_junction_anchor/step6_geometry_runner.py` | `72857` bytes | Step6 正式 geometry build 与 status 编排；本轮只挂接独立 portal/connectivity/regularization helper | 已超过 60KiB 观察线；下一轮新增职责前优先拆 summary/result publication |
| `src/rcsd_topo_poc/modules/t03_virtual_junction_anchor/step6_geometry_primitives.py` | `31050` bytes | 新拆出的 geometry、buffer、coverage、shape metric 与缓存 primitive | 保持无 Case 主编排职责 |
| `src/rcsd_topo_poc/modules/t03_virtual_junction_anchor/step6_geometry_context.py` | `14338` bytes | 新拆出的 required node/road、semantic member 与 allowed-space context helper | 保持 context 选择职责 |
| `src/rcsd_topo_poc/modules/t03_virtual_junction_anchor/step6_business_connectivity.py` | `4521` bytes | raw/output 业务终端连通分区等价审计 | 仅承接可解释连通性 oracle |
| `src/rcsd_topo_poc/modules/t03_virtual_junction_anchor/step6_road_surface_portal.py` | `14965` bytes | 基于 Road-surface 与冻结 legal space 的受约束 portal | 不放宽 Direction、foreign object 或 source ownership |
| `src/rcsd_topo_poc/modules/t03_virtual_junction_anchor/step6_compact_target_portal.py` | `6508` bytes | 紧凑 canonical alias target 的 Road-surface 连通门廊 | 保持 12m 通用门禁与 no-silent-fix |
| `src/rcsd_topo_poc/modules/t03_virtual_junction_anchor/step6_surface_regularization.py` | `6800` bytes | 受约束 surface regularization、无效派生几何显式阻断与审计 | 不修改输入源几何，不允许 `buffer(0)` 静默修复 |
| `src/rcsd_topo_poc/modules/t03_virtual_junction_anchor/step6_geometry_models.py` | `4229` bytes | 新拆出的 directional/cache 内部 dataclass | 保持仅定义模型 |
| `src/rcsd_topo_poc/modules/t03_virtual_junction_anchor/step4_association.py` | `99337 -> 247` bytes | 已降为兼容 facade，保留 association case/status 两个既有 public callable | 禁止回填实现 |
| `src/rcsd_topo_poc/modules/t03_virtual_junction_anchor/step4_association_runner.py` | `48545` bytes | 新拆出的 Step4 association 正式主编排 | 保持只承接 Case 结果编排；继续避免回填 raw guard/ownership 算法 |
| `src/rcsd_topo_poc/modules/t03_virtual_junction_anchor/step4_association_uturn.py` | `25703` bytes | 新拆出的 U-turn、degree-2 chain 与 related-scope 支撑 | 保持 U-turn/chain 职责 |
| `src/rcsd_topo_poc/modules/t03_virtual_junction_anchor/step4_association_gates.py` | `24754` bytes | 新拆出的 required-node gate、support fragment、failure/status helper | 保持 gate 与 fragment 职责 |
| `src/rcsd_topo_poc/modules/t03_virtual_junction_anchor/step4_association_primitives.py` | `15683` bytes | 新拆出的 geometry、direction、group 与 corridor primitive | 保持无 Case 主编排职责 |
| `src/rcsd_topo_poc/modules/t03_virtual_junction_anchor/step4_raw_topology_guard.py` | `20162` bytes | Direction 严格的 unmatched support、compact alias terminal 与 semantic core 守门 | 保持 raw evidence 只读重验与明确拒绝职责 |
| `src/rcsd_topo_poc/modules/t03_virtual_junction_anchor/step4_support_ownership.py` | `7588` bytes | Class B junction ownership 判定与审计 | 不承接 CaseID 或距离放宽特例 |
| `src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/step4_road_surface_fork_binding.py` | `5617` bytes | 已降为 road-surface fork binding facade，保留原 public entrypoint；本轮仅接入 complex SWSD shared RCSDRoad policy | 后续策略扩展优先落到对应 policy 模块，不回填 facade |
| `src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/step4_road_surface_fork_binding_swsd_rcsdroad.py` | `20445` bytes | 新增的 complex SWSD shared RCSDRoad fallback policy，负责无主证据复杂路口整体唯一 RCSDRoad 对齐 | 保持只承接 shared RCSDRoad 消歧与审计更新，不回填 facade |
| `src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/step4_road_surface_fork_binding_promotions.py` | `77694 -> 1010` bytes | 已降为 promotion policy 兼容 facade，保留既有私有 callable 导入面 | 禁止回填实现；按 base / relaxed / partial policy 继续维护 |
| `src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/step4_road_surface_fork_binding_promotion_base.py` | `20478` bytes | 新拆出的基础 promotion context、surface 与 junction-window 公共支撑 | 保持公共支撑职责，不承接 relaxed / partial 策略主流程 |
| `src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/step4_road_surface_fork_binding_promotion_relaxed.py` | `29846` bytes | 新拆出的 relaxed positive RCSD / junction-window promotion 策略 | 保持 relaxed promotion 与对应审计更新职责 |
| `src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/step4_road_surface_fork_binding_promotion_partial.py` | `30959` bytes | 新拆出的 selected-surface partial support promotion 策略 | 保持 partial support 策略与对应审计更新职责 |
| `src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/_event_interpretation_core.py` | `74915 -> 8166` bytes | 已降为 Step4 event interpretation 兼容 facade；保留 `_prepare_unit_inputs` 及 slice-diagnostic monkeypatch 点 | 禁止回填 context、candidate pool 或 result materialization 实现 |
| `src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/_event_interpretation_context.py` | `27710` bytes | 新拆出的 unit context、几何参考、候选摘要与 materialization 公共支撑 | 保持上下文与基础几何职责，不承接候选池或结果编排 |
| `src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/_event_interpretation_candidates.py` | `18461` bytes | 新拆出的 candidate pool 与 unit envelope 构建逻辑 | 保持候选枚举与 envelope 职责 |
| `src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/_event_interpretation_results.py` | `32105` bytes | 新拆出的 interpretation 结果组装、candidate evaluation 与空摘要逻辑 | 保持结果物化与评估职责，达到 50KB 前再次评估拆分 |
| `src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/final_publish.py` | `66552 -> 52112` bytes | Step7 单 Case 工件、发布审计与兼容 batch callable 保留在主模块 | 后续保持单 Case 物化职责，不回填 batch 输出编排 |
| `src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/final_publish_batch.py` | `18743` bytes | 新拆出的 Step7 batch 图层、摘要、relation evidence 与一致性报告发布逻辑 | 保持批量输出和一致性报告职责 |
| `tests/modules/t04_divmerge_virtual_polygon/test_step7_final_publish.py` | `70096 -> 55408` bytes | 保留 Step7 基础发布与 legacy / official baseline 场景回归 | 新增 RCSD 专项真实 Case 回归进入独立测试文件 |
| `tests/modules/t04_divmerge_virtual_polygon/test_step7_final_publish_rcsd_cases.py` | `19442` bytes | 新拆出的 new6 user audit 与 RCSD junction 专项真实 Case 回归 | 保持 RCSD 专项场景职责，公共 fixture 继续复用既有 support 模块 |
| `src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/step4_road_surface_fork_binding_cleanup.py` | `20057` bytes | 新拆出的 structure-only retention 与 unbound cleanup policy 模块 | 保持只承接清理 / 保留策略 |
| `src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/step4_road_surface_fork_binding_recovery.py` | `16698` bytes | 新拆出的 road-surface recovery policy 模块 | 保持只承接 invalid-divstrip 后的 surface recovery |
| `src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/step4_road_surface_fork_binding_divstrip.py` | `14210` bytes | 新拆出的 divstrip-primary restore policy 模块 | 保持只承接 divstrip 优先级恢复与歧义消解 |
| `src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/support_domain.py` | `569` bytes | 已降为 Step5 support-domain facade，保留原 public import surface | 后续 Step5 扩展不得回填 facade |
| `src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/support_domain_models.py` | `24848` bytes | 新拆出的 Step5 result dataclass 与 vector export，含 negative mask channel 与 positive RCSD support corridor 状态输出 | 后续 vector export 如继续增长，可单独下沉 |
| `src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/support_domain_common.py` | `22931` bytes | 新拆出的 Step5 geometry / axis / scenario common helper | 保持无 case orchestration 职责 |
| `src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/polygon_assembly_models.py` | `12704` bytes | 新拆出的 Step6 result dataclass 与状态 / 审计序列化模型，含 bridge negative mask、case alignment review、relief constraint audit 与 barrier-separated 字段 | 保持只承接 Step6 结果模型，不回填 assembly 算法 |
| `src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/polygon_assembly_guards.py` | `4044` bytes | 新拆出的 Step6 guard context 与场景派生逻辑 | 保持只承接 Step6 guard 上下文，不回填 raster assembly 或 relief 算法 |
| `src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/polygon_assembly_relief.py` | `5663` bytes | 新拆出的 Step6 dominant component / cut-sliver / hole relief helper | 保持只承接不依赖 raster 主流程状态的 relief helper |
| `src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/polygon_assembly.py` | `49351` bytes | T-01 降为 Step6 assembly 主流程与兼容导出面 | 后续 raster/path helper 不回填主文件 |
| `src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/polygon_assembly_path.py` | `29066` bytes | T-01 新拆出的 Step6 path / post-cleanup / audit helper | 保持几何约束与审计 helper，不承接主 assembly orchestration |
| `src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/polygon_assembly_raster.py` | `10103` bytes | T-01 新拆出的 Step6 raster / connectivity helper 与常量 | 保持 raster/pathfinding helper，不承接 Step6 result 组装 |
| `src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/_runtime_types_io.py` | `162` bytes | T-01 降为 types/io 兼容 facade，保留旧 import surface | 后续不回填类型或 IO 实现 |
| `src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/_runtime_types.py` | `37941` bytes | T-01 新拆出的 runtime dataclass / constants / raster-render primitives | 后续新增类型前先评估继续拆分 |
| `src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/_runtime_io.py` | `38966` bytes | T-01 新拆出的 layer loading / spatial cache / branch IO helper | 后续 IO 扩展优先保持在该文件或进一步下沉 cache helper |
| `src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/_runtime_step4_kernel_base.py` | `31715` bytes | T-01 降为 Step4 kernel base 主体，几何候选物化已下沉 | 后续 kernel base 语义扩展前评估局部拆分 |
| `src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/_runtime_step4_kernel_geometry.py` | `34889` bytes | T-01 新拆出的 Step4 kernel geometry / reference-candidate helper | 保持只承接几何候选物化与 reference candidate helper |
| `src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/_runtime_step4_geometry_core.py` | `35839` bytes | T-01 降为 Step4 geometry core 主体，常量与基础 helper 已下沉 | 后续 geometry core 扩展前评估局部拆分 |
| `src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/_runtime_step4_geometry_constants.py` | `29487` bytes | T-01 新拆出的 Step4 geometry constants / low-level helper | 保持常量、基础分支选择与轴向 helper，不承接主 geometry orchestration |
| `src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/step4_rcsd_anchored_reverse.py` | `24566` bytes | T-01 降为 anchored reverse 主流程与兼容导出面 | 后续 reverse policy / graph helper 不回填主文件 |
| `src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/step4_rcsd_anchored_reverse_policy.py` | `23448` bytes | T-01 新拆出的 anchored reverse evidence / policy helper | 保持 reverse evidence recovery 与基础 policy helper |
| `src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/step4_rcsd_anchored_reverse_graph.py` | `12796` bytes | T-01 新拆出的 anchored reverse graph / conflict helper | 保持 shortest path、terminal continuation 与 conflict helper |
| `src/rcsd_topo_poc/modules/t06_segment_fusion_precheck/step2_special_junctions.py` | `11229` bytes | 新拆出的 Step2 special junction group gate、RCSD semantic/internal road coverage 与 graph edge helper | 保持只承接特殊路口组门控、RCSD graph/coverage 准备与审计，不承接 buffer extraction 主流程 |
| `src/rcsd_topo_poc/modules/t06_segment_fusion_precheck/group_replacement_audit.py` | `24264` bytes | Step2 group replacement 审计 helper，识别 rejected Segment 的 RCSD 图路径是否跨越外部 accepted SWSD anchor，输出 incident closure / path corridor 闭包状态，并对 path-corridor group union 执行正式 extractor probe | 保持只承接 group closure 与正式 probe 审计，不直接改写 replaceable |
| `src/rcsd_topo_poc/modules/t06_segment_fusion_precheck/step3_group_replacement.py` | `18045` bytes | Step3 path-corridor group replacement 消费 helper，新增成员级 Road 归属过滤与 standard ready 成员优先保护，避免 group union 直接污染成员 Segment relation | 保持只承接 group audit / replacement plan 到 Step3 assignment 的解析、分组与成员级作用域过滤，不承接 Road/Node 删除和 F-RCSD 输出 |
| `src/rcsd_topo_poc/modules/t06_segment_fusion_precheck/step3_segment_replacement.py` | `546` bytes | T10 性能治理中已降为兼容 facade，保留原正式函数、模型、`T06Step3Artifacts` 与既有私有测试导入 | 禁止回填实现；正式编排只进入 runner，模型与 helper 分别进入已拆模块 |
| `src/rcsd_topo_poc/modules/t06_segment_fusion_precheck/step3_segment_replacement_runner.py` | `42673` bytes | 新拆出的 Step3 正式编排与汇总发布主流程，低于 60KB 安全线 | 保持只承接运行编排，不回填 relation/junction/primitive 实现 |
| `src/rcsd_topo_poc/modules/t06_segment_fusion_precheck/step3_surface_aware_plan_release.py` | `74453 -> 57187` bytes | 保留 Surface-aware Step3 运行编排、验证回滚、final topology gate、验证态审计传递与最终审计汇总；既有 callable 与参数保持不变 | 已低于 60KiB；禁止回填 release decision、输入索引或计划行构建职责 |
| `src/rcsd_topo_poc/modules/t06_segment_fusion_precheck/step3_surface_release_plan.py` | `19639` bytes | 新拆出的 surface release 常量、候选决策、输入索引、计划行构建与既有私有 helper 兼容导出 | 保持纯计划决策与读取支撑职责，不承接 Step3 执行和输出发布 |
| `src/rcsd_topo_poc/modules/t06_segment_fusion_precheck/step3_replacement_relation_support.py` | `37013` bytes | 新拆出的 junction rebuild、F-RCSD 构建、Segment relation 与 node-map 支撑 | 保持 relation/junction 职责；达到 50KB 前再次拆分 |
| `src/rcsd_topo_poc/modules/t06_segment_fusion_precheck/step3_replacement_unit_support.py` | `25959` bytes | 新拆出的 replacement unit、特殊路口组、拓扑 supplement 与 corridor 支撑 | 不承接输出发布或 summary 编排 |
| `src/rcsd_topo_poc/modules/t06_segment_fusion_precheck/step3_replacement_primitives.py` | `8814` bytes | 新拆出的 ID、端点、序列化与长度 primitive | 保持无业务流程编排 |
| `src/rcsd_topo_poc/modules/t06_segment_fusion_precheck/step3_replacement_models.py` | `2102` bytes | 新拆出的 Step3 dataclass 模型 | 保持仅定义稳定内部模型 |
| `src/rcsd_topo_poc/modules/t06_segment_fusion_precheck/parallel_output.py` | `1366` bytes | Step3 独立 feature-triplet 发布器；实测 Fiona/GPKG 并发存在磁盘争用，正式编排默认确定性串行，每个工件仍走原 `write_feature_triplet` | 保留显式并发能力仅供受控测试，不改变 schema、字段或几何语义 |
| `src/rcsd_topo_poc/modules/t06_segment_fusion_precheck/step3_topology_connectivity_audit.py` | `93342 -> 24749` bytes | 保留 topology connectivity 正式入口、基础完整性行、final topology 标注与汇总；兼容原私有 helper 导入面 | 保持正式入口与汇总职责，不回填分层 row builder 或 coverage primitive |
| `src/rcsd_topo_poc/modules/t06_segment_fusion_precheck/step3_topology_connectivity_rows.py` | `45730` bytes | 新拆出的 Segment internal / road / junction / retained endpoint / patch attachment 审计行构建，并透传 final topology 字段 | 达到 50KB 前按 Segment 与 patch 职责再次评估拆分 |
| `src/rcsd_topo_poc/modules/t06_segment_fusion_precheck/step3_final_topology_metric.py` | `6687` bytes | final F-RCSD topology 两类正式 fail 的分类、稳定对象 key 与唯一对象计数 helper | 保持纯分类/汇总职责，不承接审计行构建或回退编排 |
| `src/rcsd_topo_poc/modules/t06_segment_fusion_precheck/step3_topology_connectivity_attachment.py` | `13337` bytes | 新拆出的 attachment、retained identity、node-map 与 relation scope 支撑 | 保持 attachment 与映射职责 |
| `src/rcsd_topo_poc/modules/t06_segment_fusion_precheck/step3_topology_connectivity_support.py` | `22403` bytes | 新拆出的 road/node index、coverage cache 与几何/ID primitive | 保持索引、缓存与低层 primitive 职责，不承接审计行编排 |
| `src/rcsd_topo_poc/modules/t06_segment_fusion_precheck/step3_surface_topology_audit.py` | `88779 -> 12239` bytes | 保留 surface-topology postprocess 正式入口与统计回填；兼容原私有 helper 导入面 | 保持 postprocess 编排职责，不回填候选选择、relation 写回或 IO helper |
| `src/rcsd_topo_poc/modules/t06_segment_fusion_precheck/step3_surface_topology_rows.py` | `25487` bytes | 新拆出的 surface audit row 主构建逻辑 | 保持审计行组装职责 |
| `src/rcsd_topo_poc/modules/t06_segment_fusion_precheck/step3_surface_topology_selection.py` | `29770` bytes | 新拆出的 surface junction fallback、replacement endpoint 与 midroad projection 选择逻辑 | 保持候选选择和 midroad projection 职责 |
| `src/rcsd_topo_poc/modules/t06_segment_fusion_precheck/step3_surface_topology_relation.py` | `19147` bytes | 新拆出的 relation node-map / road-id 写回、topology audit 重建与 summary 合并 | 保持 relation 与审计发布职责 |
| `src/rcsd_topo_poc/modules/t06_segment_fusion_precheck/step3_surface_topology_support.py` | `15463` bytes | 新拆出的 surface / Step2 mapping 加载、索引与基础解析 helper | 保持 IO、索引与低层解析职责 |
| `src/rcsd_topo_poc/modules/t06_segment_fusion_precheck/step3_advance_right_contract.py` | `101663 -> 39132` bytes | 保留 junction advance-right 与 retained SWSD attachment 两个正式 contract callable，并兼容原私有导入面 | 保持正式契约编排职责，不回填 postprocess 或几何 primitive |
| `src/rcsd_topo_poc/modules/t06_segment_fusion_precheck/step3_advance_right_common.py` | `19291` bytes | 新拆出的 contract context、split-point、node mapping 与 audit row 公共逻辑 | 保持公共 contract 支撑职责 |
| `src/rcsd_topo_poc/modules/t06_segment_fusion_precheck/step3_advance_right_postprocess.py` | `28462` bytes | 新拆出的 post-advance carrier retention、bridge / paired road 与 midroad attachment 编排 | 保持 postprocess 业务编排职责 |
| `src/rcsd_topo_poc/modules/t06_segment_fusion_precheck/step3_advance_right_support.py` | `22564` bytes | 新拆出的 road component、projection、split、snap 与 ID/geometry primitive | 保持低层图/几何支撑职责，不承接 contract 主流程 |
| `src/rcsd_topo_poc/modules/t06_segment_fusion_precheck/step3_topology_supplement.py` | `65601 -> 56985` bytes | 保留 topology supplement 正式物化、coverage release 与 mixed advance-right 主流程 | 已低于 60KB；后续增长优先继续下沉主流程末端策略 |
| `src/rcsd_topo_poc/modules/t06_segment_fusion_precheck/step3_topology_supplement_support.py` | `9797` bytes | 新拆出的 supplement road/node/segment 映射、endpoint 与基础几何 helper | 保持低层 supplement 支撑职责 |
| `tests/modules/t06_segment_fusion_precheck/test_step3_segment_replacement.py` | `102076 -> 48367` bytes | 保留 Step3 基础替换、mainnode、junction map 与 attachment 契约回归 | 后续 group / post-advance 场景进入独立测试文件 |
| `tests/modules/t06_segment_fusion_precheck/test_step3_segment_replacement_groups_and_advance.py` | `52823` bytes | 新拆出的 group replacement、special junction 与 post-advance 场景回归 | 达到 55KB 前继续按 group / advance 场景拆分 |
| `tests/modules/t06_segment_fusion_precheck/test_runner_outputs.py` | `93889 -> 44848` bytes | 保留 combined runner 与 Step1/Step2 基础输出、pair gate 回归 | retry / adaptive buffer 场景进入独立测试文件 |
| `tests/modules/t06_segment_fusion_precheck/test_runner_outputs_retry.py` | `47816` bytes | 新拆出的 Step2 retry、adaptive buffer、diagnostic 与 partial roundabout 场景回归 | 保持 retry/output 专项测试职责 |
| `tests/modules/t06_segment_fusion_precheck/test_step3_topology_connectivity_audit.py` | `62155 -> 30469` bytes | 保留 topology connectivity 基础 path、coverage、retained endpoint 与 final road integrity 回归 | 扩展 junction/attachment 场景进入独立测试文件 |
| `tests/modules/t06_segment_fusion_precheck/test_step3_topology_connectivity_audit_extended.py` | `33829` bytes | 新拆出的 segment-road mapping、junction、patch attachment、提右 final topology 与 surface release 回归 | 保持扩展 topology 场景职责 |
| `src/rcsd_topo_poc/modules/t06_segment_fusion_precheck/rcsd_unreplaced_attribution.py` | `67670 -> 55763` bytes | 保留 RCSD unreplaced attribution 正式入口、匹配、分类与可 monkeypatch metric callable | 后续 summary 聚合不回填主文件 |
| `src/rcsd_topo_poc/modules/t06_segment_fusion_precheck/rcsd_unreplaced_attribution_summary.py` | `13411` bytes | 新拆出的 attribution summary、rate、Step3 summary patch 与字段清单 | 保持汇总与发布 schema 职责 |
| `src/rcsd_topo_poc/modules/t06_segment_fusion_precheck/text_bundle.py` | `80397 -> 56901` bytes | 保留 T06 text-bundle 正式 API、编码/解码与兼容 CLI callable；调用方式不变 | 已低于 60KB；input slice 与 argparse 实现不回填主文件 |
| `src/rcsd_topo_poc/modules/t06_segment_fusion_precheck/text_bundle_input.py` | `19559` bytes | 新拆出的 centered input slice、input bundle 构建与分卷输出逻辑 | 保持 input slice 与 bundle 输出职责 |
| `src/rcsd_topo_poc/modules/t06_segment_fusion_precheck/text_bundle_cli.py` | `12371` bytes | 新拆出的既有 T06 text-bundle argparse parser 与 from-args 实现 | 不新增或改变入口；保持既有参数和返回码语义 |
| `src/rcsd_topo_poc/modules/t06_segment_fusion_precheck/buffer_segment_extraction.py` | `98901 -> 21005` bytes | 保留 BufferSegmentExtractor、SpatialFeatureIndex 与原兼容导入面 | 保持 extractor 编排与缓存职责，不回填 graph/supplement/result 实现 |
| `src/rcsd_topo_poc/modules/t06_segment_fusion_precheck/buffer_segment_models.py` | `3582` bytes | 新拆出的 config/result/context/graph 状态 dataclass 与几何缓存 | 保持内部模型和缓存声明职责 |
| `src/rcsd_topo_poc/modules/t06_segment_fusion_precheck/buffer_segment_graph.py` | `35272` bytes | 新拆出的候选图、seed pruning、最短/有向路径与 edge weight 逻辑 | 保持 graph/path 核心职责 |
| `src/rcsd_topo_poc/modules/t06_segment_fusion_precheck/buffer_segment_supplement.py` | `28819` bytes | 新拆出的 corridor supplement、visual gap、parallel/semantic bridge 逻辑 | 保持 corridor 扩展与 visual consistency gate 职责 |
| `src/rcsd_topo_poc/modules/t06_segment_fusion_precheck/buffer_segment_results.py` | `17699` bytes | 新拆出的 connectivity/coverage 状态、结果物化与 ID/geometry primitive | 保持状态判定和结果组装职责 |
| `tests/modules/t06_segment_fusion_precheck/test_buffer_segment_extraction.py` | `69630 -> 34833` bytes | 保留 buffer extraction 基础、coverage、directed path 与 seed pruning 回归 | corridor supplement 扩展场景进入独立测试文件 |
| `tests/modules/t06_segment_fusion_precheck/test_buffer_segment_extraction_corridors.py` | `34199` bytes | 新拆出的 internal edge、parallel corridor、semantic bridge 与 optional terminal 回归 | 保持 corridor supplement 专项测试职责 |
| `src/rcsd_topo_poc/modules/t06_segment_fusion_precheck/replacement_plan.py` | `99579 -> 13360` bytes | 保留 replacement plan / problem registry 两个正式 builder 与兼容私有导入面 | 保持顶层计划编排职责，不回填 row/gate/support 实现 |
| `src/rcsd_topo_poc/modules/t06_segment_fusion_precheck/replacement_plan_rows.py` | `25617` bytes | 新拆出的 standard、path-corridor group 与 visual repair plan row 构建 | 保持计划行物化职责 |
| `src/rcsd_topo_poc/modules/t06_segment_fusion_precheck/replacement_plan_visual_gate.py` | `23024` bytes | 新拆出的 visual road-conflict、prune、connectivity 与 coverage gate | 保持 visual consistency gate 职责 |
| `src/rcsd_topo_poc/modules/t06_segment_fusion_precheck/replacement_plan_junction_gate.py` | `32417` bytes | special group、junction alignment、group member gate 与受限后置锚定 gate | 保持 junction/group gate 职责；后置 gate 不下沉到计划行物化层 |
| `src/rcsd_topo_poc/modules/t06_segment_fusion_precheck/replacement_plan_support.py` | `26319` bytes | risk、pair-anchor、visual release、problem registry 与解析支撑 | 保持公共策略/解析支撑职责 |
| `tests/modules/t06_segment_fusion_precheck/test_replacement_plan.py` | `101577 -> 56115` bytes | 保留 standard/group/visual gate 与基础 plan 回归 | surface-aware 与 junction alignment 场景进入独立测试文件 |
| `tests/modules/t06_segment_fusion_precheck/test_replacement_plan_surface_release.py` | `57377` bytes | surface-aware release、后置锚定、正式 final topology rollback、pair attachment 与 junction alignment 回归 | 已接近 60KB；新增大场景前按 postplan/visual release 拆分 |
| `src/rcsd_topo_poc/modules/t06_segment_fusion_precheck/step2_extract_rcsd_segments.py` | `101536 -> 5832` bytes | 已降为 Step2 正式入口兼容 facade，保留原函数签名与导入面 | 禁止回填主循环、outcome 或发布实现 |
| `src/rcsd_topo_poc/modules/t06_segment_fusion_precheck/step2_extract_rcsd_segments_runner.py` | `56860` bytes | 新拆出的 Step2 输入准备、逐 fusion-unit 主循环、retry 与 gate 编排；显式快照外层 `locals()`，兼容 WSL Python 3.10 与 Windows Python 3.13 | 已低于 60KB；后续主循环增长优先提取新的 outcome 分支 |
| `src/rcsd_topo_poc/modules/t06_segment_fusion_precheck/step2_extract_support.py` | `23984` bytes | 新拆出的 unit 解析、方向/连通、junction attach audit 与 reject row helper | 保持解析、诊断和基础 row 支撑职责 |
| `src/rcsd_topo_poc/modules/t06_segment_fusion_precheck/step2_extract_outcomes.py` | `18265` bytes | 新拆出的成功、auto pair-anchor 成功与最终拒绝结果物化分支 | 保持 outcome 行写入顺序与原分支语义 |
| `src/rcsd_topo_poc/modules/t06_segment_fusion_precheck/step2_extract_finalize.py` | `23053` bytes | 新拆出的 group/special gate 后处理、工件发布、summary 与 T06Step2Artifacts 组装 | 保持 Step2 发布与可追溯汇总职责 |
| `src/rcsd_topo_poc/modules/t06_segment_fusion_precheck/step3_detached_carriers.py` | `1147` bytes | 新拆出的 detached junc SWSD carrier helper，负责识别触达 detached junc 的原 SWSDRoad，并从正式 removed SWSDRoad 集合中剥离 | 保持只承接 detached carrier 识别与 unit 字段更新，不承接 Step3 输出编排或拓扑审计 |
| `src/rcsd_topo_poc/modules/t06_segment_fusion_precheck/attach_promotion.py` | `5062` bytes | 新拆出的孤立挂接 RCSDRoad promotion 后处理 helper，负责全局唯一 lost attach road 的提升与冲突标注 | 保持只承接 attach promotion row 后处理，不承接 buffer extraction 或 graph retry |
| `src/rcsd_topo_poc/modules/t06_segment_fusion_precheck/rejected_context.py` | `1377` bytes | 新拆出的 rejected SWSD context 标注 helper，负责为 rejected rows 补齐 SWSD sgrade 与 directionality 上下文 | 保持只承接 rejected row 上下文补齐，不承接拒绝原因判定 |
| `src/rcsd_topo_poc/modules/t06_segment_fusion_precheck/pair_anchor_auto_retry.py` | `5462` bytes | 新拆出的高置信 pair-anchor 自动重试安全门槛与 effective relation helper；承接缺失 pair anchor 侧保持补全、低分但硬审计通过的缺端补全准入，以及两端原始 pair 已完整时高置信 `candidate_anchor_mismatch` 的候选 relation 准入 | 保持只承接 pair-anchor 自动重试准入，不承接 buffer extraction 主流程 |
| `src/rcsd_topo_poc/modules/t06_segment_fusion_precheck/pair_anchor_formal_retry.py` | `20450` bytes | formal orientation retry helper，负责单候选 pair anchor mismatch 与单向 `multi_anchor_ambiguous` 的 as-is / reversed 正式试算、正式 buffer extractor、single graph-first 复核与 multi-anchor 端点侧位一致性审计 | 保持只承接 formal retry 判定与 outcome，不承接 Step2 输出行编排 |
| `src/rcsd_topo_poc/modules/t06_segment_fusion_precheck/pair_anchor_formal_retry_rows.py` | `6600` bytes | 新拆出的 formal retry accepted outcome 输出行 helper，负责 probe、repair、candidate、replaceable 与 failure-business audit 落表 | 保持只承接已通过 outcome 的输出行组装，不承接候选选择与图搜索 |
| `src/rcsd_topo_poc/modules/t06_segment_fusion_precheck/pair_anchor_relation_retry.py` | `9464` bytes | 新拆出的 relation mapping / buffer extraction formal retry 编排 helper，负责调用正式试算、junc audit 与输出行 helper，并为 Step2 主流程返回统计增量 | 保持只承接 formal retry 编排，不承接候选打分、基础 relation mapping 或 buffer extractor 实现 |
| `src/rcsd_topo_poc/modules/t06_segment_fusion_precheck/adaptive_buffer_retry.py` | `4364` bytes | 新拆出的高等级 single / dual 受限重审准入 helper；只判断 sgrade/direction/reason/全图诊断是否允许进入 single graph-first 或 dual adaptive buffer | 保持只承接重审准入，不承接 buffer extraction 执行与输出写入 |
| `src/rcsd_topo_poc/modules/t06_segment_fusion_precheck/single_graph_connectivity_retry.py` | `20749` bytes | 新拆出的高等级单向 RCSD graph-first 纵向联通 helper，负责全图有向 path、50m core、长度与几何参考门槛，并输出可审计的连通性风险 | 保持只承接 single 纵向联通，不承接 Step2 输出行编排 |
| `src/rcsd_topo_poc/modules/t06_segment_fusion_precheck/single_direction_semantic_retry.py` | `8081` bytes | 单向 Segment 特殊语义端点 subnode 本地 corridor 释放 helper，负责在初始有向 corridor 不可追溯时保持原方向检查本地无向 corridor，并仅允许短 connector / 提前右转 Road 解释方向缺口 | 保持只承接特殊语义端点本地释放，不承接 Step2 输出编排、普通方向推导或 relation 修正 |
| `src/rcsd_topo_poc/modules/t06_segment_fusion_precheck/buffer_failure_diagnostics.py` | `13363` bytes | 新拆出的 Step2 buffer 失败归因、失败 metric 与 canonical RCSD id helper | 保持只承接失败诊断与 summary/audit helper，不承接 replaceable 构建主流程 |
| `src/rcsd_topo_poc/modules/t01_data_preprocess/step2_trunk_utils.py` | `100980 -> 60369` bytes | T10 性能治理中保留 Step2 trunk 模型、候选构建、gate 与测试 monkeypatch 面；kind2-128 / trunk evaluation 编排已下沉 | 已低于 60KB；禁止回填 evaluation 主流程 |
| `src/rcsd_topo_poc/modules/t01_data_preprocess/step2_trunk_evaluation.py` | `40324` bytes | 新拆出的 kind2-128 local corridor、trunk choice、through-collapsed 与 Step5C mirrored evaluation 编排 | 通过动态代理保持 `_enumerate_simple_paths` 与 T-junction gate 的 monkeypatch 语义 |
| `src/rcsd_topo_poc/modules/t01_data_preprocess/step2_geometry_utils.py` | `4218` bytes | 新拆出的 Step2 trunk 低层几何 helper，承接 geometry coords、line assembly、距离与采样函数 | 保持只承接通用几何 primitive，不承接 pair validation 编排 |
| `src/rcsd_topo_poc/modules/t01_data_preprocess/step2_candidate_gates.py` | `2021` bytes | 新拆出的 Step2 trunk 候选 gate helper，当前承接 mixed-kind wedge 判定 | 后续候选级 gate 可继续下沉到此文件，避免 `step2_trunk_utils.py` 膨胀 |
| `src/rcsd_topo_poc/modules/t01_data_preprocess/step2_internal_turn_gate.py` | `8693` bytes | 新拆出的内部语义路口转向角 gate helper，用于阻断多路口面内明显非直行 continuation 的 Segment trunk 候选 | 保持只承接内部路口转向角、incident road 与审计字段，不承接 T06 替换逻辑 |
| `src/rcsd_topo_poc/modules/t01_data_preprocess/step2_arbitration.py` | `62713 -> 60457` bytes | 保留 pair conflict、component solver、priority 与正式 arbitration 编排；模型已下沉 | 已低于 60KB；后续 solver 扩展优先继续拆分 exact/greedy 分支 |
| `src/rcsd_topo_poc/modules/t01_data_preprocess/step2_arbitration_models.py` | `2462` bytes | 新拆出的 arbitration option/conflict/metrics/decision/outcome dataclass | 保持仅定义稳定内部模型，并由原模块兼容导出 |
| `src/rcsd_topo_poc/modules/t01_data_preprocess/step1_pair_poc.py` | `83941 -> 55040` bytes | 保留 Step1 图构建、策略执行、输出与既有 CLI/API；数据模型和搜索实现已下沉并继续兼容导出 | 已低于 60KB；禁止回填搜索主循环和模型定义 |
| `src/rcsd_topo_poc/modules/t01_data_preprocess/step1_pair_models.py` | `4550` bytes | 新拆出的 Step1 node/road/rule/search/pair/context/result dataclass | 保持仅定义稳定内部模型，并由原模块兼容导出 |
| `src/rcsd_topo_poc/modules/t01_data_preprocess/step1_pair_search.py` | `26455` bytes | 新拆出的 Step1 搜索、复杂路口等价、reverse confirm 与 pair materialization 实现 | 动态读取 facade 的搜索审计采样限额，保持测试 monkeypatch 与运行语义 |
| `src/rcsd_topo_poc/modules/t01_data_preprocess/step2_segment_poc.py` | `82416 -> 53427` bytes | 保留 Step2 正式执行/CLI、component tighten 与既有私有测试导入面；pair validation 主循环已下沉 | 已低于 60KB；禁止回填 validation 主循环 |
| `src/rcsd_topo_poc/modules/t01_data_preprocess/step2_validation_pipeline.py` | `32818` bytes | 新拆出的 pair candidate validation、progress trace、arbitration option 与 tighten 编排 | 通过 facade 动态代理保持测试 monkeypatch 和运行常量语义 |
| `src/rcsd_topo_poc/modules/t01_data_preprocess/skill_v1.py` | `80257 -> 47752` bytes | 保留 Skill v1 数据模型、阶段支撑、finalize、continuation 与既有 CLI/API；七阶段主编排已下沉 | 已低于 60KB；禁止回填主运行管线 |
| `src/rcsd_topo_poc/modules/t01_data_preprocess/skill_v1_pipeline.py` | `34781` bytes | 新拆出的 Skill v1 初始化、Step2/refresh/Step4/Step5/oneway/Step6、部分运行与汇总编排 | 通过 facade 动态代理保持阶段函数和 finalize 的 monkeypatch 语义 |
| `src/rcsd_topo_poc/modules/t01_data_preprocess/step5_staged_residual_graph.py` | `75743 -> 49389` bytes | 保留 Step5A/B/C 输入、barrier audit、phase 执行和既有 API/CLI；刷新与总编排已下沉 | 已低于 60KB；禁止回填 refresh/runner 主流程 |
| `src/rcsd_topo_poc/modules/t01_data_preprocess/step5_staged_pipeline.py` | `31670` bytes | 新拆出的 Step5 刷新物化、三阶段总编排、合并输出与 summary 发布 | 通过 facade 动态代理保持既有内部调用与业务常量语义 |
| `src/rcsd_topo_poc/modules/t01_data_preprocess/step5_oneway_segment_completion.py` | `82602 -> 38951` bytes | 保留 one-way phase/graph/trace、输出 helper 与既有 API；fallback、attachment、dead-end 和总编排已下沉 | 已低于 60KB；禁止回填 completion 主流程 |
| `src/rcsd_topo_poc/modules/t01_data_preprocess/step5_oneway_pipeline.py` | `48961` bytes | 新拆出的 residual corridor、side attachment、dead-end leaf、final fallback 与 one-way completion 总编排 | 通过 facade 动态代理保持现有 helper、dataclass 和业务常量语义 |
| `tests/modules/t01_data_preprocess/test_step2_segment_poc.py` | `198693 -> 40707` bytes | 保留 candidate channel、基础 validation 与 progress trace 场景 | 共享 fixture/helper 已下沉，其他测试按 tighten/arbitration/gate 场景拆分 |
| `tests/modules/t01_data_preprocess/step2_segment_test_support.py` | `21367` bytes | 新拆出的 Step2 测试 fixture、synthetic dataset 与 record builder | 仅供测试复用，不新增生产入口 |
| `tests/modules/t01_data_preprocess/test_step2_segment_tighten.py` | `58685` bytes | 新拆出的 compact release、component tighten、runtime/output 场景 | 已低于 60KB；新增 tighten 场景优先继续按主题分文件 |
| `tests/modules/t01_data_preprocess/test_step2_segment_arbitration.py` | `38739` bytes | 新拆出的 exact solver、pair conflict 与 strong-anchor arbitration 场景 | 保持 arbitration 专项测试职责 |
| `tests/modules/t01_data_preprocess/test_step2_segment_gates.py` | `34926` bytes | 新拆出的 T-junction、side-bypass、minimal-loop 与 trunk-choice gate 场景 | 保持 trunk/gate 专项测试职责 |
| `src/rcsd_topo_poc/modules/t10_e2e_orchestration/case_runner.py` | `48996` worktree bytes | 保留 T10 manifest/funnel/visual/feedback helper、业务常量与既有 API/CLI；T12 仅增加显式 opt-in stage order 与参数 | 已低于 60KiB；禁止回填 T12 具体编排 |
| `src/rcsd_topo_poc/modules/t10_e2e_orchestration/contracts.py` | `10330` worktree bytes | T10 workflow chain、T11/T12 audit handoff requirements 与 step contract | T12/T11 产物不作为 T09 业务输入 |
| `src/rcsd_topo_poc/modules/t10_e2e_orchestration/case_runner_pipeline.py` | `60207` worktree bytes | package/feedback iteration、逐 case 与逐 stage dispatcher；仅增加最小 T12 分派 | 低于 60KiB但接近安全线；T12 具体编排不得回填 |
| `src/rcsd_topo_poc/modules/t10_e2e_orchestration/case_runner_t11.py` | `3388` worktree bytes | T10 Case runner 的 T11 输入门禁、正式入口调用、run root 与必要输出审计 adapter | 内部模块，不新增正式入口；T11 保持 audit-only |
| `src/rcsd_topo_poc/modules/t10_e2e_orchestration/case_runner_t12.py` | `5070` worktree bytes | T10 Case runner 的 T12 显式输入门禁、正式入口调用和必要输出审计 adapter | 内部模块；T12 默认关闭且保持 audit-only |
| `scripts/t10_run_e2e_cases.sh` | `6113` worktree bytes | 既有 T10 Case runner wrapper，`STOP_AFTER` 文档增加 `t11` | 不新增入口，调用方式保持兼容 |
| `scripts/t10_run_innernet_full_pipeline.sh` | `64067` worktree bytes | 既有内网全量总控增加显式可选 T12 stage、resume、manifest、summary、Case 边界转发、显式 processing CRS 透传、候选后 reviewed 新 run-root 发布与条件完成门禁 | 低于 100KB 硬阈值但已超过 60KiB 软预警线；默认流程不变，T09 仍直接消费 T06 业务输出；后续增长前拆 stage helper |
| `scripts/t12_run_frcsd_quality_audit.py` | `3899` worktree bytes | T12 原始 1V1 F-RCSD 质量审计正式入口 | 参数化输入；不修改输入或执行修复 |
| `tests/modules/t10_e2e_orchestration/test_t10_contracts.py` | `92001 -> 42931` bytes | 保留 manifest、handoff、package、funnel 与 feedback 基础契约回归 | case-runner iteration/visual/finalize 场景进入独立测试文件 |
| `tests/modules/t10_e2e_orchestration/t10_contract_test_support.py` | `9153` bytes | 新拆出的 T10 契约测试 manifest/vector/feedback fixture helper | 仅供测试复用，不新增正式入口 |
| `tests/modules/t10_e2e_orchestration/test_t10_case_runner_contracts.py` | `39939` worktree bytes | runner blocking、feedback iteration、completion、visual summary 与含 T11 的 finalize 回归 | 保持 case-runner 专项测试职责 |
| `tests/modules/t10_e2e_orchestration/test_t10_t11_workflow.py` | `6851` worktree bytes | T06→T11→T09 stage order、adapter、输入门禁、full input discovery 与 legacy finalize 回归 | 仅测试既有入口编排，不新增执行入口 |
| `src/rcsd_topo_poc/modules/t09_swsd_field_rule_restoration/frcsd_restriction.py` | `99397 -> 39468` bytes | 保留 T09 Step3 schema、输入/summary/helper 与既有 callable 导出；carrier/feature/publish 编排已下沉 | 已低于 60KB；禁止回填 Step3 主编排 |
| `src/rcsd_topo_poc/modules/t09_swsd_field_rule_restoration/frcsd_restriction_pipeline.py` | `54689` bytes | 新拆出的 Arm carrier、v1/v2 stable/candidate feature、condition 与 restriction row 编排 | 保持 scope-aware 投影和 stable/candidate 原子分层职责 |
| `src/rcsd_topo_poc/modules/t09_swsd_field_rule_restoration/frcsd_restriction_runner.py` | `11295` bytes | 新拆出的 T09 F-RCSD restriction 顶层读取、写出、summary 与 artifact 组装 | 通过 facade 动态代理保持既有 callable 与 helper 语义 |
| `src/rcsd_topo_poc/modules/t05_junction_surface_fusion/phase2_runner.py` | `97325 -> 40676` bytes | 保留 Phase2 relation/junctionization helper 与既有 callable 导出；输入组织、decision plan 和总编排已下沉 | 已低于 60KB；禁止回填 Phase2 主流程 |
| `src/rcsd_topo_poc/modules/t05_junction_surface_fusion/phase2_pipeline.py` | `23632` bytes | 新拆出的 T11/T04 supplement、target context 与 decision-plan 编排 | 保持证据归一和 target 级计划职责 |
| `src/rcsd_topo_poc/modules/t05_junction_surface_fusion/phase2_run.py` | `44753` bytes | 新拆出的 Phase2 顶层读取、readonly/group/split、relation 发布、summary 与 artifact 组装 | 通过 facade 动态代理保持 helper 语义与 copy-on-write 边界 |
| `tests/modules/t05_junction_surface_fusion/test_phase2_rcsd_junctionization.py` | `84279 -> 38542` bytes | 保留 existing/manual/T10 supplement/T07 与基础 T04 relation 回归 | split/roundabout/cardinality 场景进入扩展测试文件 |
| `tests/modules/t05_junction_surface_fusion/phase2_test_support.py` | `8900` bytes | 新拆出的 Phase2 vector/CSV fixture、evidence field schema 与 runner helper | 仅供测试复用，不新增正式入口 |
| `tests/modules/t05_junction_surface_fusion/test_phase2_rcsd_junctionization_extended.py` | `35147` bytes | 新拆出的 no-related、road split、fallback、roundabout、cardinality 与 canonical grouping 回归 | 保持 Phase2 扩展场景职责 |
| `src/rcsd_topo_poc/modules/p01_arm_build/final_road_next_road.py` | `81045 -> 52338` bytes | 保留 P01-Final role/source policy/matching/review helper 与既有 callable；最终生成循环已下沉 | 已低于 60KB；禁止回填 final generation 主流程 |
| `src/rcsd_topo_poc/modules/p01_arm_build/final_generation.py` | `32099` bytes | 新拆出的 F-RCSD RoadNextRoad 最终规则投影、generation audit 与 result 组装 | 通过 facade 动态代理保持 role/policy/matching helper 语义 |
| `src/rcsd_topo_poc/modules/p01_arm_build/topology.py` | `80217 -> 56664` bytes | 保留 Arm topology primitive、candidate/final Arm 与 review metrics；trace 和 dataset 总编排已下沉 | 已低于 60KB；禁止回填 trace/dataset 主流程 |
| `src/rcsd_topo_poc/modules/p01_arm_build/topology_pipeline.py` | `27604` bytes | 新拆出的 seed trace 与 dataset Arm build 总编排 | 保持 trace 决策、movement/corridor/validation 汇总职责 |
| `tests/modules/p01_arm_build/test_p01_arm_build.py` | `99062 -> 29410` bytes | 保留 final-arm validation、advance-turn 与基础 P01 runner 回归 | final projection/topology/bundle 场景进入独立测试文件 |
| `tests/modules/p01_arm_build/p01_test_support.py` | `16861` bytes | 新拆出的 P01 dataset、validation、movement/source fixture helper | 仅供测试复用，不新增正式入口 |
| `tests/modules/p01_arm_build/test_p01_final_and_bundle.py` | `50849` bytes | 新拆出的 F-RCSD final projection、topology gate、text-bundle 与 IO 回归 | 保持 final/bundle 专项测试职责 |
| `src/rcsd_topo_poc/modules/t11_manual_relation_review/extract.py` | `85083 -> 56222` worktree bytes | 保留 T11 candidate/anchor/relation-gap build、summary 与输出 helper；顶层抽取与输入发现已下沉 | 已低于 60KiB；禁止回填 extract 主编排 |
| `src/rcsd_topo_poc/modules/t11_manual_relation_review/extract_pipeline.py` | `38454` worktree bytes | T10 Case/full pipeline 输入发现、数据读取、基础索引与 T11 candidate 总编排；full layout 使用显式相对路径 | 通过 facade 动态代理保持审计表构建和输出语义 |
| `src/rcsd_topo_poc/modules/t11_manual_relation_review/segment_tables.py` | `29825` worktree bytes | T11 Segment relation 审计表构建；50m RCSD 上下文按节点缓存，并通过空间索引预筛后执行原精确距离判定 | 保持 CRS、`distance <= 50.0`、最近距离、候选排序和几何语义不变 |
| `scripts/t11_extract_relation_repair_candidates.py` | `5445` worktree bytes | 既有 T11 正式入口；保留单用例模式并增加六用例批量受控并行编排 | 不是新增入口；`--workers` 限制 `1..8`，每 Case 输出根隔离 |
| `tests/modules/t11_manual_relation_review/test_extract_cli.py` | `4350` worktree bytes | T11 单用例兼容、批量顺序/输出隔离、worker 边界和人工 CSV 防误用测试 | 仅测试正式入口参数化，不新增执行入口 |
| `tests/modules/t11_manual_relation_review/test_segment_tables_performance.py` | `1159` worktree bytes | T11 50m spatial index 精确阈值、ID 顺序和无命中最近距离回归 | 只覆盖性能实现的业务等价边界 |
| `src/rcsd_topo_poc/modules/t07_semantic_junction_anchor/runner.py` | `73529 -> 52064` bytes | 保留 T07 IO、Step1、Step2 helper 与既有 callable；Step2 anchor 主编排已下沉 | 已低于 60KB；禁止回填 Step2 主流程 |
| `src/rcsd_topo_poc/modules/t07_semantic_junction_anchor/step2_pipeline.py` | `25418` bytes | 新拆出的 T07 Step2 anchor recognition、error/surface/relation evidence 与 artifacts 编排 | 通过 facade 动态代理保持 fail1/fail2 和 surface handoff 语义 |
| `src/rcsd_topo_poc/modules/t07_semantic_junction_anchor/step3_intersection_match.py` | `62695 -> 34883` bytes | 保留 Step3 relation/cardinality/IO/canonical helper 与既有 callable；主匹配编排已下沉 | 已低于 60KB；禁止回填 Step3 主流程 |
| `src/rcsd_topo_poc/modules/t07_semantic_junction_anchor/step3_pipeline.py` | `32478` bytes | 新拆出的 T07 Step3 surface/relation compatibility matching、cardinality 回写与发布编排 | 保持可选补锚定位和 relation evidence 语义 |
| `src/rcsd_topo_poc/modules/t08_preprocess/nodes_type_qc.py` | `78892 -> 46502` bytes | 保留 Tool6 数据模型、解析、拓扑与输出 helper；QC 检测和分类编排已下沉 | 已低于 60KB；禁止回填 Tool6 检测主流程 |
| `src/rcsd_topo_poc/modules/t08_preprocess/nodes_type_qc_pipeline.py` | `36636` bytes | 新拆出的 Tool6 QC 检测、分歧合流与交叉口分类编排 | 通过 facade 动态代理保持 helper、中文错误标签与输出契约语义 |
| `src/rcsd_topo_poc/modules/t08_preprocess/complex_junction_preprocess.py` | `69778 -> 46300` bytes | 保留 Tool5 模型、复杂路口/一对多 helper 与既有 callable 导出；顶层编排已下沉 | 已低于 60KB；禁止回填 Tool5 顶层运行编排 |
| `src/rcsd_topo_poc/modules/t08_preprocess/complex_junction_pipeline.py` | `24470` bytes | 新拆出的 Tool5 输入准备、complex-divmerge、one-to-many 与输出发布编排 | 保持 copy-on-write、CRS、拓扑审计及既有 T02 兼容调用语义 |
| `src/rcsd_topo_poc/modules/t08_preprocess/junction_type_repair.py` | `64985 -> 49670` bytes | 保留 Tool4 模型、解析、拓扑、错误检测和修复 helper；顶层编排已下沉 | 已低于 60KB；禁止回填 Tool4 顶层运行编排 |
| `src/rcsd_topo_poc/modules/t08_preprocess/junction_type_repair_pipeline.py` | `17171` bytes | 新拆出的 Tool4 输入读取、错误检测、契约修复、输出与 summary 编排 | 保持 no-silent-fix、字段语义、CRS 与审计输出不变 |
| `tests/modules/t10_e2e_orchestration/artifact_equivalence.py` | `17013` bytes | T10 性能治理新增的结构化业务等价 helper；比较 CSV/JSON/GPKG 内容，忽略运行元数据和拆分后的物理源码位置，并仅在比较阶段按 `1e-7 m` 规范化浮点噪声；`rcsd_road_ids/frcsd_road_ids` 按明确的无序成员集合比较 | 不作为正式入口；路径序列等其他列表仍顺序敏感，生产几何精度不变，超过网格或业务字段变化仍必须失败 |
| `tests/modules/t10_e2e_orchestration/test_artifact_equivalence.py` | `8530` bytes | 等价 helper 的运行元数据、业务字段、无序 relation road ID 集合、GPKG、浮点噪声和 tree manifest 回归 | 保持覆盖比较器边界，禁止放宽其他正式业务字段 |
| `src/rcsd_topo_poc/modules/p05_neural_road_generation/scheme_a_dataset_p1_models.py` | `2582` worktree bytes | Dataset-P1 配置、冻结分母与阶段 decision 常量 | 保持仅定义稳定配置，不承接审计编排 |
| `src/rcsd_topo_poc/modules/p05_neural_road_generation/scheme_a_dataset_p1_scope.py` | `34332` worktree bytes | Segment package target lineage、label/context scope、expected-failure 双层资格、历史指标失效和不可变 run 编排 | 只读 P05 工件；不训练、不读取 geometry、不修改 T01–T12、不新增入口 |
| `tests/modules/p05_neural_road_generation/test_scheme_a_dataset_p1_scope.py` | `5286` worktree bytes | direct ID/Road drift、Road partition、上下文 mask、expected-failure 分层与 decision 专项测试 | 保持 Dataset-P1 标签范围与破坏保护职责 |
| `src/rcsd_topo_poc/modules/p05_neural_road_generation/__init__.py` | `10125` worktree bytes | 兼容导出 Dataset-P1、P2-P3-P2/P3/P4/P5/P6/P7/P8内部config/callable | 不是执行入口；不新增 CLI、script 或 `__main__.py` |
| `src/rcsd_topo_poc/modules/p05_neural_road_generation/scheme_a_dataset_p0.py` | `52075` worktree bytes | 既有 Dataset-P0 审计；补充无 psutil 的 Linux/WSL `ru_maxrss` 标准库回退 | 不改变 Dataset-P0 业务合同、输入、标签或决策，只修复跨平台资源探针返回 0 |
| `src/rcsd_topo_poc/modules/p05_neural_road_generation/scheme_a_p2_p3_p2_models.py` | `2461` worktree bytes | Dataset-P1 scorer重基线配置、冻结分母和阶段decision常量 | 保持配置职责，不承接训练或工件编排 |
| `src/rcsd_topo_poc/modules/p05_neural_road_generation/scheme_a_p2_p3_p2_dataset.py` | `14145` worktree bytes | Dataset-P1 scope精确join、eligible/context隔离、权重覆盖、局部expected-failure与lineage审计 | 只读既有P05工件；不修改骨架、geometry或T01–T12 |
| `src/rcsd_topo_poc/modules/p05_neural_road_generation/scheme_a_p2_p3_p2_oof.py` | `29930` worktree bytes | eligible-only 3 seeds × 5 folds训练/评价、all-segment安全fallback、Junction closure、RoadGraph与确定性审计 | 内部callable；不新增CLI/script/T10 stage或正式入口 |
| `tests/modules/p05_neural_road_generation/test_scheme_a_p2_p3_p2.py` | `5062` worktree bytes | eligible/context隔离、身份破坏、context fallback和局部失败不级联专项测试 | 仅测试P2-P3-P2合同 |
| `src/rcsd_topo_poc/modules/p05_neural_road_generation/scheme_a_p2_p3_p3_models.py` | `2744` worktree bytes | P2-P3-P3安全资格/残余审计配置、冻结分母和decision常量 | 保持配置职责，不承接工件编排 |
| `src/rcsd_topo_poc/modules/p05_neural_road_generation/scheme_a_p2_p3_p3_audit.py` | `39157` worktree bytes | ADVANCE_RIGHT access硬门、三seed整图重放、held-out残余可分性与确定性审计 | 内部callable；不训练、不调阈值、不新增入口、不修改T01–T12 |
| `tests/modules/p05_neural_road_generation/test_scheme_a_p2_p3_p3.py` | `4088` worktree bytes | invalid/valid access、身份/字段破坏和非Review冲突专项测试 | 仅测试P2-P3-P3合同 |
| `src/rcsd_topo_poc/modules/p05_neural_road_generation/scheme_a_p2_p3_p4_models.py` | `3214` worktree bytes | P2-P3-P4 scope-first真值重基线配置、冻结分母和decision常量 | 保持配置职责，不承接工件编排 |
| `src/rcsd_topo_poc/modules/p05_neural_road_generation/scheme_a_p2_p3_p4_scope.py` | `18592` worktree bytes | Dataset-P1先定scope、context安全KEEP、Node/Junction闭包、label delta与既有决策指标重算 | 纯内部真值/指标逻辑；不训练、不改候选或RoadGraph |
| `src/rcsd_topo_poc/modules/p05_neural_road_generation/scheme_a_p2_p3_p4_audit.py` | `25846` worktree bytes | manifest/hash校验、scope-first真值工件、残余重解释、双跑确定性与资源审计 | 内部callable；不新增入口、不修改T01–T12 |
| `tests/modules/p05_neural_road_generation/test_scheme_a_p2_p3_p4.py` | `8587` worktree bytes | scope先于闭包、context标签隔离、delta与eligible-only指标专项测试 | 仅测试P2-P3-P4合同 |
| `src/rcsd_topo_poc/modules/p05_neural_road_generation/scheme_a_p2_p3_p5_models.py` | `4431` worktree bytes | P2-P3-P5 scope-first dataset/OOF配置、冻结分母和阶段decision常量 | 保持配置职责，不承接训练或工件编排 |
| `src/rcsd_topo_poc/modules/p05_neural_road_generation/scheme_a_p2_p3_p5_dataset.py` | `14248` worktree bytes | P4修正标签overlay、历史truth-free工件hash复用、唯一truth candidate与双跑审计 | 内部callable；不新增入口、不修改candidate或T01–T12 |
| `src/rcsd_topo_poc/modules/p05_neural_road_generation/scheme_a_p2_p3_p5_oof.py` | `27437` worktree bytes | 同架构3 seeds×5 folds重训、ADVANCE_RIGHT硬门、修正Node/Junction闭包、RoadGraph与正式决策审计 | 内部callable；不新增CLI/script/T10 stage，不处理Movement/geometry |
| `tests/modules/p05_neural_road_generation/test_scheme_a_p2_p3_p5.py` | `4357` worktree bytes | scope-first label overlay、access硬门重放和audit/model决策分离专项测试 | 仅测试P2-P3-P5合同 |
| `src/rcsd_topo_poc/modules/p05_neural_road_generation/scheme_a_p2_p3_p6_models.py` | `3398` worktree bytes | P2-P3-P6双层归因配置、冻结分母和阶段decision常量 | 保持配置职责，不承接工件编排 |
| `src/rcsd_topo_poc/modules/p05_neural_road_generation/scheme_a_p2_p3_p6_audit.py` | `42802` worktree bytes | P5 scorer/final双层指标、逐对象/clue归因、expected-failure发布和train-only证据可分性审计 | 内部只读callable；不训练、不调阈值、不新增入口、不修改T01–T12 |
| `tests/modules/p05_neural_road_generation/test_scheme_a_p2_p3_p6.py` | `7214` worktree bytes | 双层指标、原子阻断、归因分类、稳定clue错误与双路线决策专项测试 | 仅测试P2-P3-P6合同 |
| `src/rcsd_topo_poc/modules/p05_neural_road_generation/scheme_a_p2_p3_p7_models.py` | `3147` worktree bytes | P2-P3-P7 Movement-free表征/校准审计配置、602维合同和阶段decision常量 | 保持配置职责，不承接工件编排 |
| `src/rcsd_topo_poc/modules/p05_neural_road_generation/scheme_a_p2_p3_p7_audit.py` | `45761` worktree bytes | 上游hash/CRS核验、Movement维排除、compatibility/T01相对几何表征、train-only邻域和clue校准可行性审计 | 内部只读callable；不训练、不拟合/调阈值、不新增入口、不修改T01–T12 |
| `tests/modules/p05_neural_road_generation/test_scheme_a_p2_p3_p7.py` | `2224` worktree bytes | 决策、零邻域、相对几何不变量和recall=1单调阈值专项测试 | 仅测试P2-P3-P7合同 |
| `src/rcsd_topo_poc/modules/p05_neural_road_generation/scheme_a_p2_p3_p8_models.py` | `2343` worktree bytes | P2-P3-P8来源合同配置、冻结分母与四类阶段decision | 保持配置职责，不承接工件编排 |
| `src/rcsd_topo_poc/modules/p05_neural_road_generation/scheme_a_p2_p3_p8_audit.py` | `43500` worktree bytes | T03/T04正式handoff/hash/CRS、字段角色、Case-local junc_nodes、carrier同类证据和Clue覆盖审计 | 内部只读callable；不训练、不提升字段、不新增入口、不修改T01–T12 |
| `tests/modules/p05_neural_road_generation/test_scheme_a_p2_p3_p8.py` | `2694` worktree bytes | P8 decision、字段黑白名单、T04方向不变carrier signature和显式Junction ID join专项测试 | 仅测试P2-P3-P8合同 |
| `src/rcsd_topo_poc/modules/p05_neural_road_generation/scheme_a_p2_p3_p9_models.py` | `3592` worktree bytes | P9 control/residual adapter配置、冻结维数、seed/fold与decision常量 | 保持配置职责，不承接训练或工件编排 |
| `src/rcsd_topo_poc/modules/p05_neural_road_generation/scheme_a_p2_p3_p9_source.py` | `15263` worktree bytes | 602维control与carrier-only source residual表征装配 | 内部模型输入职责；不修改冻结骨架或T01–T12 |
| `src/rcsd_topo_poc/modules/p05_neural_road_generation/scheme_a_p2_p3_p9_training.py` | `17821` worktree bytes | P9 scorer训练、adapter拟合与确定性模型工件 | 仅P05内部训练callable；不新增正式入口 |
| `src/rcsd_topo_poc/modules/p05_neural_road_generation/scheme_a_p2_p3_p9_oof.py` | `41415` worktree bytes | 3 seeds×5 folds双臂训练、评估、安全门与正式工件编排 | 内部callable；不修改T01–T12或RoadGraph业务骨架 |
| `tests/p05_neural_road_generation/test_scheme_a_p2_p3_p9.py` | `6582` worktree bytes | P9 source residual隔离、模型双臂与正式门专项测试 | 仅测试P9合同 |
| `src/rcsd_topo_poc/modules/p05_neural_road_generation/scheme_a_p2_p3_p10_adjudication.py` | `24457` worktree bytes | P10对象级人工真值覆盖、冻结P9复算与carrier安全审计 | 内部只读callable；不训练、不调阈值、不改历史P9 |
| `tests/modules/p05_neural_road_generation/test_scheme_a_p2_p3_p10.py` | `8669` worktree bytes | P10人工真值覆盖、稳定误差复算与确定性专项测试 | 仅测试P10合同 |
| `src/rcsd_topo_poc/modules/p05_neural_road_generation/scheme_a_p2_p3_p11_clue_fp_audit.py` | `51496` worktree bytes | P11稳定Clue误报归因、Scheme-A定位lineage、人工CSV不可变校验与24对象1.0真值编译 | 内部只读callable；不训练、不调阈值、不读取geometry、不修改T01–T12 |
| `tests/modules/p05_neural_road_generation/test_scheme_a_p2_p3_p11.py` | `16350` worktree bytes | P11对象真值优先、ADVANCE_RIGHT定位、Excel布尔归一、不可变字段防漂移与双跑确定性专项测试 | 仅测试P11合同 |
| `src/rcsd_topo_poc/modules/t10_e2e_orchestration/scratch_publish.py` | `14231` bytes | T10 既有 wrapper 的临时 Linux 文件系统执行结果发布 helper；负责受校验的 tar 发布、路径回写、清单核验与 scratch 清理 | 不新增正式入口；保持发布前后文件数/字节数一致并限制清理根边界 |
| `src/rcsd_topo_poc/modules/t06_segment_fusion_precheck/step3_final_topology_gate.py` | `9687` bytes | Final topology 正式失败决策、失败节点证据与 hard-gate plan 回退 helper | 保持决策与 plan 标记职责，不承接 F-RCSD 几何或 relation 编排 |
| `src/rcsd_topo_poc/modules/t06_segment_fusion_precheck/step3_authoritative_transition_closure.py` | `14812` bytes | hard-gate 直接回退后 mixed-source 级联 transition 的 T05 权威 mainnode 收口与审计 | 保持严格候选、12m 门禁和审计职责，不扩展为通用 surface fallback |
| `src/rcsd_topo_poc/modules/p04_road_direct_generation/segment_first_access_recovery.py` | `10667` bytes | JunctionUnit endpoint surface 约束下的完整 Patch Road 恢复候选、accepted endpoint surface合同、端点协调后重判及已发布 carrier 重叠冲突审计 | 仅为缺失角色提供后置候选；不得复用已发布主体几何 |
| `src/rcsd_topo_poc/modules/p04_road_direct_generation/segment_first_carriers.py` | `65464` bytes | Segment carrier角色、四态、目标角色恢复、显式作用域内的endpoint surface候选完整性、局部connector隔离与原子回退 | 已超过60KiB观察线；不得继续回填恢复编排，新增职责前先拆分 |
| `src/rcsd_topo_poc/modules/p04_road_direct_generation/segment_first_config.py` | `4715` bytes | 版本化显式路径、CRS、局部Junction routing与Road lineage细分阈值配置 | 不扩展为正式入口 |
| `src/rcsd_topo_poc/modules/p04_road_direct_generation/segment_first_corridors.py` | `16022` bytes | 跨Patch方向观测span组装、道路域补全与高精观测链平滑保护 | 保持corridor职责 |
| `src/rcsd_topo_poc/modules/p04_road_direct_generation/segment_first_evidence.py` | `33281` bytes | Patch Road/Lane/LaneTopo证据、目标fragment assignment与隔离恢复候选 | 保持证据身份和质量隔离 |
| `src/rcsd_topo_poc/modules/p04_road_direct_generation/segment_first_finalize.py` | `7679` bytes | 外部验收证据校验与`technical_passed→passed`晋级 | 不承接生成算法或入口 |
| `src/rcsd_topo_poc/modules/p04_road_direct_generation/segment_first_geometry_quality.py` | `7046` bytes | built Segment Road观测/道路面推导/completion几何hard/soft质量审计 | 保持几何QA职责 |
| `src/rcsd_topo_poc/modules/p04_road_direct_generation/segment_first_geometry.py` | `13095` bytes | carrier到Segment Road几何、source span及道路面推导来源物化 | 不回填carrier规划或Junction内部Road |
| `src/rcsd_topo_poc/modules/p04_road_direct_generation/segment_first_inputs.py` | `7920` bytes | 上游/Patch输入、accepted surface、完整RCSD弱锚定与CRS adapter | 不反推未知字段语义 |
| `src/rcsd_topo_poc/modules/p04_road_direct_generation/segment_first_junction_carriers.py` | `40009` bytes | ordinary分布式高精portal、accepted surface/DriveZone支撑审计、父级与Lane级LaneTopo强制portal和完整RCSD弱证据 | 不扩展为T03/T04路口搜索或通用几何修复；ordinary不得恢复中心星形Road |
| `src/rcsd_topo_poc/modules/p04_road_direct_generation/segment_first_lane_topo.py` | `13887` bytes | LaneTopo向正式Road投影、父Road同载体识别、精确Lane关系拒绝归集、已接受物理交接复用、Junction carrier path与稳定父Road多part有向链查询 | 保持发布投影与审计职责；不得在此生成Road或修改业务Segment |
| `src/rcsd_topo_poc/modules/p04_road_direct_generation/segment_first_lineage.py` | `27918` bytes | Junction关系范围外的稳定Road lineage边界识别、精确父Road子串切分、内部Node增量物化、既有Node图保持和审计重映射 | 不决定Segment/Junction；不得重新拟合几何或触发全图Node重编译 |
| `src/rcsd_topo_poc/modules/p04_road_direct_generation/segment_first_junctions.py` | `5795` bytes | T07/T03/T04优先级与JunctionUnit | 不重做上游路口算法 |
| `src/rcsd_topo_poc/modules/p04_road_direct_generation/segment_first_movements.py` | `25724` bytes | LaneTopo内部anchor、terminal-equivalent movement、THROUGH access与Road切分 | 不切分业务Segment |
| `src/rcsd_topo_poc/modules/p04_road_direct_generation/segment_first_nodes.py` | `64396` bytes | Node继承/稳定生成、分布式Junction portal、mainnode、逐Road交接、DriveZone约束端点补全、跨Segment portal分离、最终坐标支撑审计及可选lineage字段空值隔离 | 已超过60KiB观察线；不得继续回填endpoint resolution或connection audit职责，新增职责前先拆分 |
| `src/rcsd_topo_poc/modules/p04_road_direct_generation/segment_first_outputs.py` | `2215` bytes | 正式/审计/关系GPKG发布 | 保持发布职责 |
| `src/rcsd_topo_poc/modules/p04_road_direct_generation/segment_first_pipeline.py` | `96321` bytes | Segment-first阶段编排、Junction rejected spoke后的accepted endpoint surface定向救援、Road-Lane双来源lineage编译、端点协调后恢复重判、定向语义端点重试、稳定lineage后置细分、fallback固定点、summary及对照层准备 | 距100000字节硬阈值仅3679字节；禁止继续回填，下一轮源码新增职责前必须先拆出network rebuild与summary |
| `src/rcsd_topo_poc/modules/p04_road_direct_generation/segment_first_qgis.py` | `18026` bytes | 相对路径QGIS工程、四组Road/Node对照、方向主干链PASS/FAIL分类、Junction portal/LaneTopo exclusion及Road细分决策分组与样式 | 保持可视化职责 |
| `src/rcsd_topo_poc/modules/p04_road_direct_generation/segment_first_quality.py` | `10437` bytes | 发布后独立只读QA | 不依赖生成器内存结论 |
| `src/rcsd_topo_poc/modules/p04_road_direct_generation/segment_first_skeleton.py` | `6709` bytes | T01 SegmentBuildUnit与Access | 保持T01 owner职责 |
| `src/rcsd_topo_poc/modules/p04_road_direct_generation/segment_first_target_assignment.py` | `11754` bytes | 冻结目标锚定与 Patch Road/Lane 分配 | 保持目标合同与普通证据分配隔离 |
| `src/rcsd_topo_poc/modules/p04_road_direct_generation/segment_first_target_coverage.py` | `9356` bytes | 闭合 Patch core、ADVANCE_RIGHT 与 boundary review 目标集 | 不改变 T01 Segment 业务定义 |
| `src/rcsd_topo_poc/modules/p04_road_direct_generation/segment_first_target_fragments.py` | `13409` bytes | 目标 Segment 内 Patch Road/Lane station fragment 切分 | 保持原始证据身份与区间可追溯 |
| `src/rcsd_topo_poc/modules/p04_road_direct_generation/segment_first_target_realization.py` | `15456` bytes | 按目标方向角色审计多Road方向链、实际共享Node、终端Junction identity及accepted surface物理到达 | 不以技术 gate或mainnode属性替代业务目标验收 |
| `src/rcsd_topo_poc/modules/p04_road_direct_generation/segment_first_topology.py` | `4942` bytes | 从实际共享Node编译RoadNextRoad | 不由mainnode直接连边 |
| `src/rcsd_topo_poc/modules/p04_road_direct_generation/segment_first_types.py` | `3331` bytes | Segment-first枚举、结果和状态合同 | 保持纯模型职责 |
| `tests/modules/p04_road_direct_generation/test_segment_first_contract.py` | `2710` bytes | 配置、枚举、四态合同 | 按主题保持拆分 |
| `tests/modules/p04_road_direct_generation/test_segment_first_access_recovery.py` | `6758` bytes | accepted endpoint surface合同、endpoint surface候选、已发布主体重叠阻断、短交接重叠允许及协调后重判 | 按主题保持拆分 |
| `tests/modules/p04_road_direct_generation/test_segment_first_corridors.py` | `6639` bytes | 跨Patch组装、双向原子性、反向几何与观测链平滑保护 | 按主题保持拆分 |
| `tests/modules/p04_road_direct_generation/test_segment_first_evidence.py` | `8227` bytes | 中心走廊、Junction优先级、部分支持、LaneTopo与目标恢复候选 | 按主题保持拆分 |
| `tests/modules/p04_road_direct_generation/test_segment_first_finalize.py` | `3387` bytes | finalizer完整/失败证据门禁 | 按主题保持拆分 |
| `tests/modules/p04_road_direct_generation/test_segment_first_geometry_quality.py` | `3515` bytes | completion及道路面推导几何hard gate | 按主题保持拆分 |
| `tests/modules/p04_road_direct_generation/test_segment_first_geometry.py` | `2416` bytes | 道路面推导source span与发布属性 | 按主题保持拆分 |
| `tests/modules/p04_road_direct_generation/test_segment_first_inputs.py` | `1555` bytes | accepted surface与schema contract | 按主题保持拆分 |
| `tests/modules/p04_road_direct_generation/test_segment_first_junction_carriers.py` | `15589` bytes | ordinary分布式portal、局部surface/DriveZone支撑、完整RCSD弱证据、LaneTopo强制portal和单Segment回退 | 按主题保持拆分 |
| `tests/modules/p04_road_direct_generation/test_segment_first_movements.py` | `9806` bytes | Movement anchor切分、terminal-equivalent、THROUGH access与拒绝 | 按主题保持拆分 |
| `tests/modules/p04_road_direct_generation/test_segment_first_nodes.py` | `37125` bytes | Node/mainnode、交接、方向、距离、语义端点、DriveZone约束surface补全、跨Segment portal分离、可信surface锚点和可选lineage空值门禁 | 按主题保持拆分 |
| `tests/modules/p04_road_direct_generation/test_segment_first_lineage.py` | `9665` bytes | 稳定纵向lineage细分、Junction保护、父几何并集、内部Node增量物化和既有Node保持 | 按主题保持拆分 |
| `tests/modules/p04_road_direct_generation/test_segment_first_pipeline_contract.py` | `18803` bytes | actual shared Node、complex拓扑、候选隔离、Patch Road与direct Lane双来源多对多Road-Lane、父Road同载体、已接受物理交接复用、Lane级拒绝及多Road LaneTopo链投影 | 按主题保持拆分 |
| `tests/modules/p04_road_direct_generation/test_segment_first_skeleton.py` | `1963` bytes | Segment/ENDPOINT/THROUGH skeleton | 按主题保持拆分 |
| `tests/modules/p04_road_direct_generation/test_segment_first_target_assignment.py` | `5502` bytes | 冻结目标锚定与候选分配 | 按主题保持拆分 |
| `tests/modules/p04_road_direct_generation/test_segment_first_target_carriers.py` | `24668` bytes | 目标方向角色、endpoint surface显式救援作用域、部分支持、跨Patch道路面补全、局部connector隔离与恢复接管 | 按主题保持拆分 |
| `tests/modules/p04_road_direct_generation/test_segment_first_target_coverage.py` | `6468` bytes | core/ADVANCE_RIGHT/boundary review目标合同 | 按主题保持拆分 |
| `tests/modules/p04_road_direct_generation/test_segment_first_target_fragments.py` | `2932` bytes | Patch Road目标station fragment与重叠审计 | 按主题保持拆分 |
| `tests/modules/p04_road_direct_generation/test_segment_first_target_lanes.py` | `2160` bytes | Lane目标fragment分配 | 按主题保持拆分 |
| `tests/modules/p04_road_direct_generation/test_segment_first_target_realization.py` | `8869` bytes | 目标多Road方向链、断裂/分叉/终端错配和accepted surface物理到达审计 | 按主题保持拆分 |
| `tests/modules/p04_road_direct_generation/test_segment_first_distributed_junction.py` | `8025` bytes | ordinary分布式portal、统一mainnode、无中心星形Road及complex隔离合同 | 按主题保持拆分 |
| `tests/modules/p04_road_direct_generation/test_segment_first_qgis.py` | `981` bytes | 方向主干链PASS/FAIL分类renderer合同 | 按主题保持拆分 |
| `tests/modules/p04_road_direct_generation/test_segment_first_quality.py` | `3694` bytes | 发布后独立QA、ID规范化与ordinary星形Road零门禁 | 按主题保持拆分 |

### P04 Segment-first SWSD完整拓扑合同当前快照（2026-07-26，V46）

以下快照覆盖上表中同路径的历史字节数；本轮新增职责已拆入独立文件，所有源码/脚本均低于100KB硬阈值。

| 文件 | 当前体量 | 当前职责 | 后续约束 |
|---|---:|---|---|
| `src/rcsd_topo_poc/modules/p04_road_direct_generation/segment_first_pipeline.py` | `94971` bytes | Segment-first阶段编排、稳定lineage后置细分、SWSD Access/Movement合同与fallback固定点 | 距100000字节仅5029字节；禁止回填新算法职责 |
| `src/rcsd_topo_poc/modules/p04_road_direct_generation/segment_first_nodes.py` | `78887` bytes | 分布式portal、mainnode、端点协调、built/retained semantic portal隔离及accepted surface方向交点 | 已超过60KiB观察线；新增职责前拆分endpoint resolution |
| `src/rcsd_topo_poc/modules/p04_road_direct_generation/segment_first_carriers.py` | `78790` bytes | Segment carrier角色、目标方向组装、部分支持与单Segment原子回退 | 已超过60KiB观察线；新增职责前拆分carrier recovery |
| `src/rcsd_topo_poc/modules/p04_road_direct_generation/segment_first_lineage.py` | `34443` bytes | 稳定LaneGroup/lineage交接、精确父Road切分、Access端点属性保持与增量度2 Node | 不重新拟合几何或重编全图Node |
| `src/rcsd_topo_poc/modules/p04_road_direct_generation/segment_first_junction_topology.py` | `28328` bytes | ordinary完整Movement合同、T04 complex显式SWSD fallback及LaneTopo+local connector+accepted surface三重证据关系 | 不生成几何；complex不得退化为ordinary全连接 |
| `src/rcsd_topo_poc/modules/p04_road_direct_generation/segment_first_qgis.py` | `21268` bytes | QGIS对照、方向链、SWSD Junction Movement合同和完整路口结构审计层 | 保持可视化职责 |
| `src/rcsd_topo_poc/modules/p04_road_direct_generation/segment_first_quality.py` | `20121` bytes | 发布后独立只读QA及SWSD拓扑合同复算 | 不依赖生成器内存结论 |
| `src/rcsd_topo_poc/modules/p04_road_direct_generation/segment_first_reference_axes.py` | `13384` bytes | SWSD语义参考轴和高精候选纵向排序 | 不输出SWSD几何 |
| `src/rcsd_topo_poc/modules/p04_road_direct_generation/segment_first_topology.py` | `10833` bytes | actual shared、ordinary semantic与受约束complex显式RoadNextRoad编译 | 不由裸mainnode直接连边 |
| `src/rcsd_topo_poc/modules/p04_road_direct_generation/segment_first_swsd_topology.py` | `10057` bytes | SWSD逐Segment Access方向合同 | 明确Junction lineage是必要条件 |
| `src/rcsd_topo_poc/modules/p04_road_direct_generation/segment_first_swsd_junction_audit.py` | `4951` bytes | 聚合SWSD Junction的Segment/ENDPOINT/THROUGH/Movement完整结构用于QGIS审计 | 只读审计，不参与构图决策 |
| `src/rcsd_topo_poc/modules/p04_road_direct_generation/segment_first_road_lane.py` | `6315` bytes | 按Lane方向、局部距离和纵向覆盖编译细Road与Lane关系 | Patch Road/LaneGroup只提供候选，不得机械全挂 |
| `src/rcsd_topo_poc/modules/p04_road_direct_generation/segment_first_lane_topo.py` | `16266` bytes | 结合方向化Road-Lane关系、同carrier细Road链及受限保留semantic bridge投影LaneTopo | 不修改业务Segment或接受任意图可达 |
| `src/rcsd_topo_poc/modules/p04_road_direct_generation/segment_first_movements.py` | `32270` bytes | LaneTopo anchor、THROUGH切分、SWSD Access/Junction切分lineage传递和surface本体端点裁切 | 不切分业务Segment |
| `src/rcsd_topo_poc/modules/p04_road_direct_generation/segment_first_summary.py` | `8360` bytes | summary、report和终态证据汇总 | 不承接构图 |
| `src/rcsd_topo_poc/modules/p04_road_direct_generation/segment_first_junctions.py` | `7666` bytes | Junction优先级及SWSD物理Node lineage索引 | 不重做上游路口算法 |
| `src/rcsd_topo_poc/modules/p04_road_direct_generation/segment_first_network.py` | `2357` bytes | 细分后网络重编译与LaneTopo投影编排 | 不承接几何或summary |
| `tests/modules/p04_road_direct_generation/test_segment_first_junction_topology.py` | `11789` bytes | ordinary完整Movement、T04显式fallback及LaneTopo局部连接Road出口合同 | 按主题保持拆分 |
| `tests/modules/p04_road_direct_generation/test_segment_first_swsd_topology.py` | `5901` bytes | SWSD Access方向、Junction lineage和mainnode不足性 | 按主题保持拆分 |
| `tests/modules/p04_road_direct_generation/test_segment_first_reference_axes.py` | `8181` bytes | 参考轴、方向投影和候选顺序合同 | 按主题保持拆分 |
| `tests/modules/p04_road_direct_generation/test_segment_first_nodes.py` | `50732` bytes | ordinary方向portal、built/retained中心隔离、surface交点和Node/mainnode合同 | 按主题保持拆分 |
| `tests/modules/p04_road_direct_generation/test_segment_first_pipeline_contract.py` | `26242` bytes | 多Road LaneTopo链、保留semantic bridge和跨lineage拒绝合同 | 按主题保持拆分 |

### P04 endpoint surface路由与V61当前快照（2026-07-25）

以下快照覆盖V54及更早表中同路径历史字节数；全部源码/脚本仍低于100KB硬阈值。

| 文件 | 当前体量 | 当前职责 | 后续约束 |
|---|---:|---|---|
| `src/rcsd_topo_poc/modules/p04_road_direct_generation/segment_first_pipeline.py` | `97742` bytes | Segment-first编排、fallback证据重协调固定点、SWSD方向角色挂接与发布汇总 | 距100000字节仅2258字节；新增任何职责前必须拆分 |
| `src/rcsd_topo_poc/modules/p04_road_direct_generation/segment_first_carriers.py` | `88871` bytes | carrier角色、Segment优先方向组装、观测覆盖率约束端点补全、surface桥接/局部路由调用和单Segment回退 | member/surface识别已下沉；新增carrier职责前继续拆分 |
| `src/rcsd_topo_poc/modules/p04_road_direct_generation/segment_first_nodes.py` | `79087` bytes | 分布式portal、mainnode和端点协调 | 新增职责前拆分endpoint resolution |
| `src/rcsd_topo_poc/modules/p04_road_direct_generation/segment_first_movements.py` | `37081` bytes | LaneTopo anchor、THROUGH切分、endpoint surface裁切及局部路由引出的端点面外尾段审计 | 不切分业务Segment；尾段抑制必须有唯一贯穿片段 |
| `src/rcsd_topo_poc/modules/p04_road_direct_generation/segment_first_member_recovery.py` | `3303` bytes | Segment级走廊失败后的单member缺方向RoadSurface恢复编排 | 只做后置恢复；不得抢占Segment级候选 |
| `src/rcsd_topo_poc/modules/p04_road_direct_generation/segment_first_surface_bridge.py` | `5273` bytes | 已认证access候选的非重叠endpoint surface短桥接识别 | 不放宽raw component或重叠保护区 |
| `src/rcsd_topo_poc/modules/p04_road_direct_generation/segment_first_surface_routing.py` | `6651` bytes | endpoint直线失败后的局部RoadSurface可见性路由、绕行门禁与边界内缩 | 不使用SWSD坐标，不沿远端道路域绕行 |
| `src/rcsd_topo_poc/modules/p04_road_direct_generation/segment_first_access_recovery.py` | `14183` bytes | access surface候选、carrier冲突及fallback后证据释放固定点 | 只释放已fallback owner独占且未发布的证据 |
| `src/rcsd_topo_poc/modules/p04_road_direct_generation/segment_first_swsd_paths.py` | `11985` bytes | SWSD member正反向路径枚举、唯一/歧义审计和候选角色映射 | 唯一路径可驱动发布；歧义路径只审计 |
| `src/rcsd_topo_poc/modules/p04_road_direct_generation/segment_first_qgis.py` | `23350` bytes | 43层相对路径QGIS工程、项目/图层CRS、对比样式 | 保持可视化职责 |
| `tests/modules/p04_road_direct_generation/test_segment_first_target_carriers.py` | `47186` bytes | 目标方向、Segment/member恢复优先级、surface短桥接/重叠拒绝、路径选择和部分支持 | 按主题保持拆分 |
| `tests/modules/p04_road_direct_generation/test_segment_first_nodes.py` | `52325` bytes | Node组件、冗余显式关系、portal与mainnode合同 | 按主题保持拆分 |
| `tests/modules/p04_road_direct_generation/test_segment_first_movements.py` | `16302` bytes | Movement切分、endpoint裁切与路由因果范围内的尾段抑制 | 按主题保持拆分 |
| `tests/modules/p04_road_direct_generation/test_segment_first_surface_routing.py` | `4308` bytes | 局部路由、断开/超绕行拒绝、平滑后合法域和SWSD splice为0 | 按主题保持拆分 |
| `tests/modules/p04_road_direct_generation/test_segment_first_qgis.py` | `3406` bytes | renderer与项目/图层CRS序列化合同 | 按主题保持拆分 |

### P04 三层目标合同当前快照（2026-07-24，V63）

本轮将目标资格和处置解析拆入独立文件；`segment_first_pipeline.py`只增加通用合同接线，未新增Case/Segment硬编码或构图算法。全部源码/脚本仍低于100KB硬阈值。

| 文件 | 当前体量 | 当前职责 | 后续约束 |
|---|---:|---|---|
| `src/rcsd_topo_poc/modules/p04_road_direct_generation/segment_first_pipeline.py` | `98622` bytes | Segment-first编排及三层目标合同接线 | 距100000字节仅1378字节；禁止继续回填，任何新增编排职责前必须先拆分 |
| `src/rcsd_topo_poc/modules/p04_road_direct_generation/segment_first_target_disposition.py` | `7777` bytes | 外部确认清单校验、hash及Baseline/DirectBuild资格覆盖 | 不承担构图；禁止Case/Segment硬编码 |
| `src/rcsd_topo_poc/modules/p04_road_direct_generation/segment_first_target_coverage.py` | `9662` bytes | 输入确定Baseline并接入资格合同 | Baseline不得被例外清单改写 |
| `src/rcsd_topo_poc/modules/p04_road_direct_generation/segment_first_target_realization.py` | `22767` bytes | Baseline/DirectBuild双分母、方向链和PublishDisposition审计 | 使用正式Segment状态区分hard conflict与部分证据，不按ID分类 |
| `src/rcsd_topo_poc/modules/p04_road_direct_generation/segment_first_qgis.py` | `24421` bytes | 47层三方对照、目标资格/例外、五类发布处置样式和既有业务审计 | 保持可视化职责 |
| `src/rcsd_topo_poc/modules/p04_road_direct_generation/segment_first_summary.py` | `8927` bytes | summary/report并列披露Baseline、DirectBuild和完整发布 | 不承接构图 |
| `tests/modules/p04_road_direct_generation/test_segment_first_target_disposition.py` | `5968` bytes | 例外清单合同与拒绝路径 | 按主题保持拆分 |
| `tests/modules/p04_road_direct_generation/test_segment_first_target_coverage.py` | `6857` bytes | Baseline与DirectBuild覆盖合同 | 按主题保持拆分 |
| `tests/modules/p04_road_direct_generation/test_segment_first_target_realization.py` | `17234` bytes | 双分母、发布处置、方向链及冲突/部分证据分类 | 按主题保持拆分 |
| `tests/modules/p04_road_direct_generation/test_segment_first_qgis.py` | `3988` bytes | 五类发布处置renderer与项目/图层CRS序列化合同 | 按主题保持拆分 |

### P04 目视审计历史最佳版本快照（2026-07-24，V69/V70）

本轮把retained冗余抑制和部分member接管分别拆入独立模块；`segment_first_pipeline.py`与`segment_first_carriers.py`只增加编排接线。全部源码/脚本仍低于100KB硬阈值，未新增repo入口，也未改动T01–T12。

| 文件 | 当前体量 | 当前职责 | 后续约束 |
|---|---:|---|---|
| `src/rcsd_topo_poc/modules/p04_road_direct_generation/segment_first_pipeline.py` | `97757` bytes | Segment-first编排、质量Review传播、冗余retained抑制接线、Patch/T03/T04/T07路口面对照准备 | 距100000字节仅2243字节；不得继续回填算法职责 |
| `src/rcsd_topo_poc/modules/p04_road_direct_generation/segment_first_carriers.py` | `93331` bytes | 完整carrier仲裁及部分member接管编排 | 距100000字节仅6669字节；新增恢复策略前继续拆分 |
| `src/rcsd_topo_poc/modules/p04_road_direct_generation/segment_first_nodes.py` | `80157` bytes | 分布式portal、mainnode、提前右转端点lineage与实际共享Node | 已超过60KiB观察线；新增端点职责前拆分 |
| `src/rcsd_topo_poc/modules/p04_road_direct_generation/segment_first_movements.py` | `37630` bytes | accepted surface保护范围内的Movement切分及主走廊兄弟尾段抑制 | 不切分业务Segment |
| `src/rcsd_topo_poc/modules/p04_road_direct_generation/segment_first_geometry.py` | `14212` bytes | built/whole-retained/partial-retained Road几何与稳定ID物化 | 不回填carrier规划 |
| `src/rcsd_topo_poc/modules/p04_road_direct_generation/segment_first_geometry_quality.py` | `7957` bytes | 几何hard/soft质量审计及正式Road Review传播 | Review不得绕过hard gate |
| `src/rcsd_topo_poc/modules/p04_road_direct_generation/segment_first_inputs.py` | `8257` bytes | 上游/Patch输入及Patch原始Intersection加载 | 不反推未知字段语义 |
| `src/rcsd_topo_poc/modules/p04_road_direct_generation/segment_first_qgis.py` | `25797` bytes | 52层相对路径QGIS工程、五类路口面和冗余抑制审计 | 保持可视化职责 |
| `src/rcsd_topo_poc/modules/p04_road_direct_generation/segment_first_surface_routing.py` | `8975` bytes | 观测端部切线到accepted surface及局部RoadSurface路由 | 不使用SWSD坐标，不改变证据仲裁顺序 |
| `src/rcsd_topo_poc/modules/p04_road_direct_generation/segment_first_retained_overlap.py` | `18218` bytes | 简单Segment内冗余retained候选、增量抑制、拓扑复算与原子回滚 | 不抑制THROUGH/局部Movement载体 |
| `src/rcsd_topo_poc/modules/p04_road_direct_generation/segment_first_partial_members.py` | `12145` bytes | 单方向member的observed Road与互补retained partial Road构建 | 不满足DirectBuild完整性，不降级既有完整built |
| `tests/modules/p04_road_direct_generation/test_segment_first_geometry.py` | `5479` bytes | partial retained ID、source lineage与几何来源合同 | 按主题保持拆分 |
| `tests/modules/p04_road_direct_generation/test_segment_first_geometry_quality.py` | `4765` bytes | soft Review传播与hard gate回归 | 按主题保持拆分 |
| `tests/modules/p04_road_direct_generation/test_segment_first_nodes.py` | `53559` bytes | 提前右转端点lineage、portal与mainnode合同 | 按主题保持拆分 |
| `tests/modules/p04_road_direct_generation/test_segment_first_movements.py` | `16388` bytes | surface保护范围与兄弟尾段抑制回归 | 按主题保持拆分 |
| `tests/modules/p04_road_direct_generation/test_segment_first_quality.py` | `4374` bytes | 正式输出拓扑和几何只读QA | 按主题保持拆分 |
| `tests/modules/p04_road_direct_generation/test_segment_first_surface_routing.py` | `4888` bytes | 切线surface portal、路由与合法域回归 | 按主题保持拆分 |
| `tests/modules/p04_road_direct_generation/test_segment_first_qgis.py` | `3988` bytes | QGIS renderer、项目/图层CRS合同 | 按主题保持拆分 |
| `tests/modules/p04_road_direct_generation/test_segment_first_retained_overlap.py` | `5537` bytes | 冗余retained抑制与hard gate回滚合同 | 按主题保持拆分 |
| `tests/modules/p04_road_direct_generation/test_segment_first_partial_members.py` | `3433` bytes | observed/retained partial互斥与transition Node合同 | 按主题保持拆分 |

### P04 Road端点严格入面当前快照（2026-07-25，V75）

本轮源码仍保持41个`segment_first*.py`、专项测试33个；全部源码和脚本低于100000字节。V75选择以端点严格入面、LaneTopo unresolved 0和独立QA 0 violation为主，不以DirectBuild数量覆盖hard gate。

| 文件 | 当前体量 | 当前职责 | 后续约束 |
|---|---:|---|---|
| `src/rcsd_topo_poc/modules/p04_road_direct_generation/segment_first_pipeline.py` | `97984` bytes | Segment-first阶段编排和发布挂接 | 距100000字节仅2016字节；禁止新增职责 |
| `src/rcsd_topo_poc/modules/p04_road_direct_generation/segment_first_nodes.py` | `97571` bytes | 分布式portal、mainnode、严格端点入面与受约束补齐 | 距100000字节仅2429字节；下一次端点策略必须先拆分 |
| `src/rcsd_topo_poc/modules/p04_road_direct_generation/segment_first_carriers.py` | `93331` bytes | carrier仲裁与部分证据接管 | 新增恢复策略前继续拆分 |
| `src/rcsd_topo_poc/modules/p04_road_direct_generation/segment_first_movements.py` | `38861` bytes | accepted THROUGH穿面切分和retained精确lineage投影细分 | 不扩展到关系半径邻近 |
| `src/rcsd_topo_poc/modules/p04_road_direct_generation/segment_first_qgis.py` | `28447` bytes | 53层QGIS工程、路口面和端点协调审计 | 保持只读可视化职责 |
| `tests/modules/p04_road_direct_generation/test_segment_first_nodes.py` | `57813` bytes | 严格入面、平滑补齐、source-node和mainnode lineage回归 | 达到60KiB前按端点主题继续拆分 |
| `tests/modules/p04_road_direct_generation/test_segment_first_target_carriers.py` | `47186` bytes | carrier目标、部分支持和surface恢复回归 | 按主题保持拆分 |
| `tests/modules/p04_road_direct_generation/test_segment_first_pipeline_contract.py` | `28964` bytes | 编排和正式发布合同 | 按主题保持拆分 |
| `tests/modules/p04_road_direct_generation/test_segment_first_movements.py` | `20146` bytes | THROUGH实际穿面和retained精确lineage例外 | 按主题保持拆分 |

### P04主干物理交接与显式LaneTopo当前快照（2026-07-26，V76 Iteration 6）

当前扫描42个`segment_first*.py`源码与34个专项测试：源码`>=61440 bytes`为3、测试`>=61440 bytes`为0、全部`>=100000 bytes`为2。`segment_first_pipeline.py`和`segment_first_nodes.py`在本临时工作树建立时已超过硬阈值，本轮未写入这两个文件；新增职责全部放入独立小模块。后续任何写入必须先按§3停机并取得拆分或豁免授权。

| 文件 | 当前体量 | 当前职责 | 后续约束 |
|---|---:|---|---|
| `src/rcsd_topo_poc/modules/p04_road_direct_generation/segment_first_pipeline.py` | `100510` bytes | Segment-first阶段编排和发布挂接 | 已超过100000字节；禁止写入，须先授权拆分或豁免 |
| `src/rcsd_topo_poc/modules/p04_road_direct_generation/segment_first_nodes.py` | `100152` bytes | 分布式portal、mainnode、严格端点入面与受约束补齐 | 已超过100000字节；禁止写入，须先授权拆分或豁免 |
| `src/rcsd_topo_poc/modules/p04_road_direct_generation/segment_first_carriers.py` | `95775` bytes | carrier仲裁与部分证据接管 | 距100000字节4225字节；新增策略前继续拆分 |
| `src/rcsd_topo_poc/modules/p04_road_direct_generation/segment_first_physical_handoff.py` | `20923` bytes | 同Segment主干实际Node交接与端点固定局部正则化 | 不承接Junction语义关系编译 |
| `src/rcsd_topo_poc/modules/p04_road_direct_generation/segment_first_topology.py` | `20344` bytes | actual/ordinary/显式LaneTopo关系编译 | 不反推T01业务骨架 |
| `tests/modules/p04_road_direct_generation/test_segment_first_nodes.py` | `59605` bytes | 严格入面、平滑补齐、source-node和mainnode lineage回归 | 距60KiB观察线1835字节，新增主题前拆分 |

### P04参数化内网执行入口增量审计（2026-07-26）

本轮新增1个正式repo脚本和1个专项测试，均远低于100000字节；未写入已超阈值的`segment_first_pipeline.py`和`segment_first_nodes.py`，未新增依赖、CLI子命令、Make目标或模块`__main__.py/run.py`。

| 文件 | 当前体量 | 当前职责 | 后续约束 |
|---|---:|---|---|
| `scripts/p04_run_segment_first_innernet.py` | `6630` bytes | P04 Segment-first内网显式参数、输入前检、callable转调及结果JSON | 不硬编码业务路径，不复制算法，不自动finalize |
| `tests/modules/p04_road_direct_generation/test_innernet_script.py` | `6671` bytes | 参数映射、Patch目录前检、help和core gate退出码合同 | 保持脚本边界测试，不复制端到端算法测试 |

说明：

- 当前未发现 `scripts/` 下超过 `100 KB` 的入口脚本。
- 本表不裁定业务基线、模块正式范围或是否立即重构；只记录结构债事实。

### P04 SegmentAccess 空几何恢复与 Node 模块拆分（2026-07-30）

本轮经用户授权执行超阈值拆分：将 built Road 的 SegmentAccess
补接编排从 `segment_first_nodes.py` 下沉到独立模块，并保留 Node
编译层提供的几何与 Junction 策略。空 Access 几何不再参与距离计算；
存在 accepted JunctionUnit surface 时仍可按面完成交接，surface 与
Access 几何同时缺失时不猜测，继续由
`segment_access_not_materialized` hard gate 阻断。内网入口新增该子阶段
处理量、空几何数、未解析目标数和耗时日志，不改变入口参数。

当前扫描 `43` 个 `segment_first*.py` 源码与 `35` 个专项测试：
源码 `>=61440 bytes` 为 `3`、测试 `>=61440 bytes` 为 `0`，
全部 `>=100000 bytes` 为 `1`。`segment_first_nodes.py` 已从
`100152` bytes 降至 `84351` bytes；未写入仍超阈值的
`segment_first_pipeline.py`。

| 文件 | 当前体量 | 当前职责 | 后续约束 |
|---|---:|---|---|
| `src/rcsd_topo_poc/modules/p04_road_direct_generation/segment_first_pipeline.py` | `100510` bytes | Segment-first阶段编排和发布挂接 | 仍超过100000字节；禁止写入，后续须单独授权拆分或豁免 |
| `src/rcsd_topo_poc/modules/p04_road_direct_generation/segment_first_nodes.py` | `84351` bytes | Node生成、mainnode、端点协调及几何策略 | SegmentAccess补接编排已拆出；禁止回填该职责 |
| `src/rcsd_topo_poc/modules/p04_road_direct_generation/segment_first_access_memberships.py` | `19936` bytes | accepted surface约束的SegmentAccess补接、空几何降级和子阶段性能日志 | 不扩大为全局路口距离搜索；无有效目标时必须保留hard gate |
| `scripts/p04_run_segment_first_innernet.py` | `10038` bytes | P04内网参数化入口、带当前执行位置的心跳及模块级进度日志 | 不改变正式参数合同，不复制业务算法 |
| `tests/modules/p04_road_direct_generation/test_innernet_script.py` | `8476` bytes | 内网参数映射、core gate退出码、心跳执行位置和help合同 | 保持入口行为测试，不复制业务算法 |
| `tests/modules/p04_road_direct_generation/test_segment_first_access_memberships.py` | `4730` bytes | Access空几何在有/无accepted surface时的非静默回归 | 保持资料部分缺失与hard gate两类合同 |

### P04 1500 Patch性能优化（2026-07-30）

本轮未修改已超过硬阈值的`segment_first_pipeline.py`。路径评分、资源采样和
跨阶段道路面缓存分别下沉到独立模块；Patch输入读取与实际消费文件清单使用
最多6个有界I/O worker，未引入进程池或无界并发。现有carrier、Node、输入、
走廊和目标碎片模块只进行等价计算复用与全表扫描收敛。

当前扫描`47`个`segment_first*.py`源码与`40`个专项测试：源码
`>=61440 bytes`为`3`、测试`>=61440 bytes`为`0`，全部
`>=100000 bytes`仍仅有未写入的`segment_first_pipeline.py`一个。
另有`2`个SpecKit性能/验收验证脚本，均低于`61440 bytes`。本轮修改及新增的
全部源码、脚本和测试均低于`100000 bytes`。

| 文件 | 当前体量 | 当前职责 | 后续约束 |
|---|---:|---|---|
| `src/rcsd_topo_poc/modules/p04_road_direct_generation/segment_first_pipeline.py` | `100510` bytes | Segment-first阶段编排和发布挂接 | 本轮未写入；继续禁止写入，后续须单独授权拆分或豁免 |
| `src/rcsd_topo_poc/modules/p04_road_direct_generation/segment_first_carriers.py` | `93166` bytes | carrier仲裁、方向组装及按Segment预分组 | 距硬阈值较近；不得回填新的业务策略 |
| `src/rcsd_topo_poc/modules/p04_road_direct_generation/segment_first_nodes.py` | `89059` bytes | Node/mainnode、端点协调及有界几何缓存调用 | 不回填SegmentAccess编排或新端点策略 |
| `src/rcsd_topo_poc/modules/p04_road_direct_generation/segment_first_inputs.py` | `10616` bytes | 正式Patch输入读取及与资源合同共源的最多6个I/O worker | 不改变图层族、字段语义或稳定拼接顺序 |
| `src/rcsd_topo_poc/modules/p04_road_direct_generation/segment_first_path_scoring.py` | `4595` bytes | Patch Road路径指标预计算和等价评分 | 只承接无状态评分复用 |
| `src/rcsd_topo_poc/modules/p04_road_direct_generation/segment_first_geometry_metrics.py` | `11485` bytes | 最大采样转角的精确批量插值、道路面覆盖精确索引和有界复用 | 不改变角度运算顺序，不引入近似几何或silent fix |
| `src/rcsd_topo_poc/modules/p04_road_direct_generation/segment_first_performance.py` | `15078` bytes | 高分辨率墙钟、进程CPU/RSS/I/O、最多6个Patch I/O worker合同、30秒资源时间线和预算审计 | 最多保留1024个有界样本，不进入业务决策；Windows API必须保留64位句柄签名 |
| `src/rcsd_topo_poc/modules/p04_road_direct_generation/segment_first_geometry_cache.py` | `1124` bytes | 按活动GeoDataFrame身份复用精确buffered union | 只缓存不可变计算结果，不做几何修复 |
| `scripts/p04_run_segment_first_innernet.py` | `12409` bytes | 正式参数化内网入口、心跳、共源I/O worker上限、原生线程默认上限及资源审计 | 不改变正式参数合同，不复制业务算法 |
| `specs/p04-segment-first-performance-1500-patch-20260730/validation/benchmark_input_scale.py` | `14543` bytes | 真实Vector循环复用下的Patch输入读取、CRS、拼接、清单和峰值内存规模验证 | 仅为SpecKit验证脚本，不登记为正式入口，不替代内网端到端验收 |
| `specs/p04-segment-first-performance-1500-patch-20260730/validation/validate_innernet_acceptance.py` | `17775` bytes | 约1500 Patch时限、资源、QA、QGIS、输入身份及同输入业务指纹只读验收 | 无同输入参考时最多输出EVIDENCE_READY；不得把局部证据升级为ACCEPTED |
| `tests/modules/p04_road_direct_generation/test_innernet_script.py` | `9130` bytes | 参数入口、退出码、心跳及8核资源默认值合同 | 保持入口行为测试 |
| `tests/modules/p04_road_direct_generation/test_segment_first_performance.py` | `3060` bytes | 性能监控、Windows资源读取、I/O worker上限、资源时间线、预算和summary合并合同 | 保持独立于业务成果 |
| `tests/modules/p04_road_direct_generation/test_innernet_acceptance_validation.py` | `4578` bytes | 完整证据无参考与缺失I/O worker合同两类验收器回归 | 不使用伪造业务参考证明零回退 |
| `tests/modules/p04_road_direct_generation/test_segment_first_geometry_cache.py` | `864` bytes | buffered union精确复用和空输入合同 | 不以近似几何替代等价计算 |
| `tests/modules/p04_road_direct_generation/test_segment_first_geometry_metrics.py` | `1787` bytes | 转角与道路面覆盖精确缓存合同 | 重复调用必须保持数值等价 |
| `tests/modules/p04_road_direct_generation/test_segment_first_path_scoring.py` | `1164` bytes | 路径评分数值与布尔归一合同 | 不改变缺失值和非有限值语义 |

### P04 Segment dirty-set性能优化与主编排拆分（2026-08-02）

本轮依据已授权拆分计划处理既有超阈值文件：原
`segment_first_pipeline.py`（`100510 bytes`）中的输出关系、审计和冻结结果读取辅助
职责迁移到`segment_first_pipeline_outputs.py`，主编排保留调用别名以兼容既有私有
测试。拆分后主编排为`88492 bytes`，仓库P04 Segment-first源码重新回到
`>=100000 bytes`为0的状态。本轮不改变正式入口签名、不新增入口、不修改T01–T12。

当前扫描`53`个`segment_first*.py`源码和`68`个P04专项测试：源码
`>=61440 bytes`为`3`、测试`>=61440 bytes`为`0`，源码和测试
`>=100000 bytes`均为`0`。新增逐Segment增量规划职责位于独立小模块；Carrier和Node
只增加产生精确合并元数据及复用静态索引所需的最小接线，不新增业务策略。后续补充
ADVANCE_RIGHT Road端点索引、access surface恢复空间索引及Target fragment粗筛/进度后，
又增加Carrier静态上下文和reservation空间索引；当前继续融合Patch输入SHA256并加入
有界路口面内缩目标缓存；随后增加同源CRS批量投影、WSL挂载盘Patch输入/GPKG输出
暂存和Target fragment站点矩阵计算，P04专项测试为`325 passed`。
本轮继续复用Movement固定点中的Segment access分组和Junction source静态上下文，
并增加Patch端点切向及本轮Carrier行索引复用，P04专项测试更新为`327 passed`。
本轮继续为增量Carrier指纹常见标量增加旧字节合同等价快速路径，P04专项测试更新为
`337 passed`；随后增加canonical ID等价快速归一化，以及保持逐浮点结果不变的最大
采样转角批量插值；随后Target fragment改为精确坐标批取且保持逐点方位角运算顺序，
专项测试更新为`352 passed`。随后将Node completion surface全域accepted union拆入
独立索引模块，按查询范围精确物化局部surface并增加实际进度；专项测试更新为
`355 passed`。当前扫描仍无`>=100000 bytes`源码或测试文件。

| 文件 | 当前体量 | 当前职责 | 后续约束 |
|---|---:|---|---|
| `src/rcsd_topo_poc/modules/p04_road_direct_generation/segment_first_pipeline.py` | `88715` bytes | Segment-first阶段编排、仅按新增endpoint trim差集触发固定点重建、性能缓存逐run复位及发布挂接 | 继续只保留编排；新输出辅助职责下沉 |
| `src/rcsd_topo_poc/modules/p04_road_direct_generation/segment_first_pipeline_outputs.py` | `12917` bytes | 输出关系、Node关系、审计与冻结结果读取辅助 | 不承接构图策略 |
| `src/rcsd_topo_poc/modules/p04_road_direct_generation/segment_first_carriers.py` | `93589` bytes | 原Carrier规划及逐Segment汇总/字段顺序元数据 | 距硬阈值6411字节；新静态准备职责下沉到context模块 |
| `src/rcsd_topo_poc/modules/p04_road_direct_generation/segment_first_incremental_carriers.py` | `20316` bytes | 逐Segment输入指纹、常见标量等价快速序列化、dirty重算、原顺序合并和复用统计 | 保持旧字节指纹合同；只缓存run内不可变输入，不承接业务仲裁 |
| `src/rcsd_topo_poc/modules/p04_road_direct_generation/segment_first_carrier_context.py` | `10668` bytes | Road/assignment/reference/surface单条目弱引用缓存及reservation空间索引 | 对象或manager变化即失效；不改变Carrier仲裁门槛 |
| `src/rcsd_topo_poc/modules/p04_road_direct_generation/segment_first_junctions.py` | `11794` bytes | JunctionUnit候选选择、retained kind一次性Node索引和实际group进度 | 保持T07/T04/T03优先级与kind_2语义不变 |
| `src/rcsd_topo_poc/modules/p04_road_direct_generation/segment_first_skeleton.py` | `9794` bytes | T01 SegmentBuildUnit、Access、ADVANCE_RIGHT Road端点一次性索引及canonical ID等价快速归一化 | 不扩大ID归一化范围，不改变Segment/Access定义 |
| `src/rcsd_topo_poc/modules/p04_road_direct_generation/segment_first_access_recovery.py` | `18991` bytes | access surface恢复候选、按Segment聚合Access和空间索引粗筛 | 最终仍执行原距离、裁切、覆盖与冲突门槛 |
| `src/rcsd_topo_poc/modules/p04_road_direct_generation/segment_first_target_fragments.py` | `20740` bytes | Patch Road/Lane目标Segment分片、扩展包围盒粗筛、阶段级只读axis行、站点矩阵和方位角精确坐标批取及实际进度 | 保持空间索引候选顺序、最终站点距离、逐点角度运算顺序、member和排序合同 |
| `src/rcsd_topo_poc/modules/p04_road_direct_generation/segment_first_nodes.py` | `89978` bytes | Node/mainnode、端点协调、静态Junction/Access索引复用及dwithin邻域粗筛 | completion surface聚合已下沉；新端点策略必须继续拆分 |
| `src/rcsd_topo_poc/modules/p04_road_direct_generation/segment_first_completion_surfaces.py` | `10316` bytes | accepted Junction分组surface空间索引、DriveZone联合、局部精确查询和有界buffer缓存 | 禁止恢复全域accepted union；2048条LRU不得无界增长 |
| `src/rcsd_topo_poc/modules/p04_road_direct_generation/segment_first_config.py` | `5219` bytes | 参数合同、单次路径解析及输入输出隔离校验 | 不改变正式入口参数或路径重叠保护 |
| `src/rcsd_topo_poc/modules/p04_road_direct_generation/segment_first_movements.py` | `52237` bytes | Movement/Access物理切分及只读evidence、Patch端点切向、Junction surface/source、Segment access分组和本轮Carrier行索引复用 | 不缓存跨轮Carrier选择；不改变选择、裁切或拓扑条件 |
| `src/rcsd_topo_poc/modules/p04_road_direct_generation/segment_first_topology.py` | `24480` bytes | 共享Node、语义路口及ADVANCE_RIGHT显式关系编译；显式关系使用evidence倒排候选 | 保留全部Node/mainnode、显式支持和relation去重门槛 |
| `src/rcsd_topo_poc/modules/p04_road_direct_generation/segment_first_progress.py` | `14254` bytes | 实际对象进度、Node completion surface进度及6阶段单调overall estimate | 动态重试不得伪造线性ETA |
| `src/rcsd_topo_poc/modules/p04_road_direct_generation/io.py` | `17171` bytes | 输入SHA256清单、通用矢量I/O、真实清单进度及WSL挂载盘GPKG原子暂存写出 | 预计算Patch清单必须保持正式顺序、大小和SHA256完全一致；暂存失败安全回退 |
| `src/rcsd_topo_poc/modules/p04_road_direct_generation/segment_first_inputs.py` | `18289` bytes | 8类Patch输入读取、同轮SHA256、同源CRS批量投影、挂载盘本机暂存及正式输入清单组装 | 不改变输入图层族、fallback优先级、manifest身份或拼接顺序 |
| `src/rcsd_topo_poc/modules/p04_road_direct_generation/segment_first_surface_routing.py` | `14846` bytes | 端点到路口面局部路由、有界精确内缩目标缓存及completion surface局部查询 | 不近似路口面；8192条、32MiB键预算内LRU |
| `src/rcsd_topo_poc/modules/p04_road_direct_generation/segment_first_geometry_metrics.py` | `11711` bytes | 最大采样转角精确批量插值、道路面覆盖精确索引和completion surface局部覆盖 | 保留原station及逐角度运算顺序；不得引入近似几何或silent fix |
| `scripts/p04_run_segment_first_innernet.py` | `22290` bytes | 正式入口、资源/缓存/dirty-set/context心跳和summary性能审计 | 保持第12.1节正式参数签名 |
| `specs/p04-segment-first-performance-1500-patch-20260730/validation/validate_innernet_acceptance.py` | `31529` bytes | 时限、资源、输入清单、Target fragment进度、有界缓存及业务零回退验收 | 无1532 Patch完整证据不得升级为ACCEPTED |
| `tests/modules/p04_road_direct_generation/test_segment_first_physical_handoff.py` | `11261` bytes | 物理交接、显式语义关系及ADVANCE_RIGHT evidence倒排候选回归 | 保持候选顺序与旧显式支持集合一致 |
| `tests/modules/p04_road_direct_generation/test_segment_first_inputs.py` | `11809` bytes | Patch图层fallback、读取期SHA256、挂载盘暂存、批量投影及清单免二次散列回归 | 输入清单顺序、大小、SHA256、字段、CRS和WKB必须等价 |
| `tests/modules/p04_road_direct_generation/test_io.py` | `1535` bytes | WSL挂载盘GPKG暂存、复制和原子替换回归 | 正式输出不得暴露半成品；失败路径安全回退 |
| `tests/modules/p04_road_direct_generation/test_segment_first_movements.py` | `27648` bytes | Movement切分、Patch端点切向及Junction/Segment access静态上下文复用回归 | 缓存必须保持候选重评、分组去重、source首选与聚合几何合同 |
| `tests/modules/p04_road_direct_generation/test_segment_first_incremental_carriers.py` | `9302` bytes | dirty-set重算、合并统计及常见标量/几何指纹字节合同回归 | 指纹快速路径不得改变任何值的旧字节表达 |
| `tests/modules/p04_road_direct_generation/test_segment_first_skeleton.py` | `4395` bytes | Segment/Access骨架、端点索引及canonical ID归一化合同回归 | 正负号、前导零、Unicode数字、非零小数和复合ID必须保持现有语义 |
| `tests/modules/p04_road_direct_generation/test_segment_first_target_fragments.py` | `3877` bytes | Target fragment划分及坐标批取方位角逐浮点等价回归 | 不得改变station标签、fragment属性或WKB |
| `tests/modules/p04_road_direct_generation/test_segment_first_surface_routing.py` | `6455` bytes | 局部路由、精确内缩目标复用及缓存上限回归 | 不用缓存绕过几何门槛 |
| `tests/modules/p04_road_direct_generation/test_segment_first_completion_surfaces.py` | `4201` bytes | 全域物化参考与索引局部surface的点覆盖、距离、数值覆盖率、门槛和进度等价回归 | 必须保持accepted来源过滤和精确几何合同 |
| `tests/modules/p04_road_direct_generation/test_innernet_acceptance_validation.py` | `12029` bytes | 正式进度、资源、有界缓存和业务参考验收回归 | 局部样本不得升级全量结论 |

### T12 非预期反向载体检出当前快照（2026-07-31）

本轮在主干已有 anchored canonical alias raw portal 规则上扩展 T12
锚点区间、Segment 唯一归属、输出和测试，不新增或改变执行入口。全部受影响源码/测试均低于
`100000` bytes 硬阈值。

| 文件 | 当前体量 | 当前职责 | 后续约束 |
|---|---:|---|---|
| `src/rcsd_topo_poc/modules/t12_frcsd_quality_audit/models.py` | `3708` bytes | additive schema、问题枚举和证据层模型 | 保持纯模型职责 |
| `src/rcsd_topo_poc/modules/t12_frcsd_quality_audit/candidate_audit.py` | `52472` bytes | 必需方向缺失、anchored alias portal 与非预期反向载体候选、portal 分侧及路径证据接线 | 新候选类型继续按独立 helper 分层；达到 60KiB 前评估拆分 |
| `src/rcsd_topo_poc/modules/t12_frcsd_quality_audit/reverse_segment_scope.py` | `13467` bytes | 反向路径双端面接触、逐 raw RCSD Road Segment 唯一归属与空间索引 | 不承接候选发布或 Case 特判 |
| `src/rcsd_topo_poc/modules/t12_frcsd_quality_audit/review_publish.py` | `12541` bytes | 候选种类专属自动决定与外部 review override | 不承接图或几何算法 |
| `src/rcsd_topo_poc/modules/t12_frcsd_quality_audit/outputs.py` | `26202` bytes | additive CSV/GPKG/JSON 发布与证据图层 | 不承接候选判断 |
| `tests/modules/t12_frcsd_quality_audit/test_candidate_audit.py` | `23449` bytes | 必需方向 portal、反向发现、SWSD 替代、弱锚点、T07 alias endpoint 与 Segment scope 接线回归 | 按候选主题保持拆分 |
| `tests/modules/t12_frcsd_quality_audit/test_reverse_segment_scope.py` | `3899` bytes | 锚点区间、当前 Segment 唯一归属、其它 Segment 覆盖与并列归属回归 | 保持 scope helper 专项 |
| `tests/modules/t12_frcsd_quality_audit/test_review_publish.py` | `9911` bytes | 精度优先自动决定与 review 契约 | 保持 decision 专项 |
| `tests/modules/t12_frcsd_quality_audit/test_outputs.py` | `1491` bytes | additive 输出字段合同 | 保持轻量 |
| `tests/modules/t12_frcsd_quality_audit/test_1026960_fixture.py` | `2370` bytes | 既有冻结清单与生产代码无 Case ID 硬编码门禁 | 不把新候选写入旧 review fixture |

### T12 v10 质量分类与 T07 Step2 来源修正（2026-08-01）

本轮修改既有 T10/T12 入口和实现，并新增两个仅位于 SpecKit `validation/`
目录的验证脚本；未新增正式执行入口。全部修改/新增的源码、脚本和测试均低于
`100000` bytes，最大文件为既有
`scripts/t10_run_innernet_full_pipeline.sh`（`69516` bytes）。T07 代码、接口和
算法未修改。

| 文件 | 当前体量 | 当前职责/约束 |
|---|---:|---|
| `scripts/t10_run_innernet_full_pipeline.sh` | `69516` bytes | T10 全量编排；T12 前只归档同一标准目录旧结果，失败时恢复原批次 |
| `scripts/t12_rerun_frcsd_junction_quality_innernet.sh` | `8080` bytes | T12 独立续跑；保持 T10 标准目录，归档旧批次并在失败时恢复 |
| `scripts/t12_run_frcsd_quality_audit.py` | `5234` bytes | 既有 T12 CLI；增加可选 T07 Step1/2 根参数 |
| `src/rcsd_topo_poc/modules/t10_e2e_orchestration/case_runner_t12.py` | `6722` bytes | T10→T12 Step1/2 handoff |
| `src/rcsd_topo_poc/modules/t12_frcsd_quality_audit/issue_taxonomy.py` | `9156` bytes | 三组七类、中文描述、状态与兼容映射唯一真相 |
| `src/rcsd_topo_poc/modules/t12_frcsd_quality_audit/junction_audit.py` | `52978` bytes | T03 raw topology guard 与 required movement 重验、T07 Step2 J03/J04 发布；不得承接 T03/T07 算法 |
| `src/rcsd_topo_poc/modules/t12_frcsd_quality_audit/junction_required_movements.py` | `25132` bytes | SWSD required movement、FRCSD boundary arm heading/ownership、raw Direction carrier 与受限 alias portal | 保持只读重验，不读取 CaseID，不创建通用 canonical graph edge |
| `src/rcsd_topo_poc/modules/t12_frcsd_quality_audit/junction_inputs.py` | `26005` bytes | T03/T07 Step2 只读来源、final/error/summary/relation evidence 强一致性和指纹审计 |
| `src/rcsd_topo_poc/modules/t12_frcsd_quality_audit/junction_outputs.py` | `6992` bytes | Junction CSV/GPKG 发布 |
| `src/rcsd_topo_poc/modules/t12_frcsd_quality_audit/models.py` | `5739` bytes | v12 schema、统一字段模型与 Junction movement 参数 |
| `src/rcsd_topo_poc/modules/t12_frcsd_quality_audit/outputs.py` | `31626` bytes | Segment 输出、中文分类报告与内部根因保留 |
| `src/rcsd_topo_poc/modules/t12_frcsd_quality_audit/review_publish.py` | `14167` bytes | Segment 分类迁移、决定和候选唯一性门禁 |
| `src/rcsd_topo_poc/modules/t12_frcsd_quality_audit/runner.py` | `6649` bytes | T12 编排与 T07 Step1/2 可选输入传递 |
| `tests/modules/t10_e2e_orchestration/test_t10_t12_workflow.py` | `13161` bytes | Step1/2 handoff、标准目录归档与失败恢复合同 |
| `tests/modules/t12_frcsd_quality_audit/test_issue_taxonomy.py` | `3365` bytes | 七类、状态和兼容映射合同 |
| `tests/modules/t12_frcsd_quality_audit/test_junction_audit.py` | `20784` bytes | J01-J04、T03 raw guard/required movement 重验、交叉道路 heading 防错配和唯一性合同 |
| `tests/modules/t12_frcsd_quality_audit/test_junction_inputs.py` | `10005` bytes | Step2 final/error/summary/relation evidence 一致性和 Step3 零导入合同 |
| `tests/modules/t12_frcsd_quality_audit/test_outputs.py` | `3243` bytes | Segment/Junction 分类字段和报告合同 |
| `tests/modules/t12_frcsd_quality_audit/test_real_junction_cases.py` | `5248` bytes | 当前 QA 指纹绑定的 11 个残留候选真值回归；不再跨快照固定 4 正 16 负 |
| `tests/modules/t12_frcsd_quality_audit/test_review_publish.py` | `10676` bytes | Segment 决定、兼容和候选唯一性合同 |
| `specs/t12-quality-taxonomy-step2-source-20260801/validation/build_real_audit_bundle.py` | `16081` bytes | 一次性真实 Case/QGIS 自包含证据包构建，不登记为正式入口 |
| `specs/t12-quality-taxonomy-step2-source-20260801/validation/create_qgis_project.py` | `16838` bytes | 一次性 PyQGIS 工程、渲染和图层门禁，不登记为正式入口 |
