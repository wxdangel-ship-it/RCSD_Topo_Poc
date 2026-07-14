# P02 武汉局部实验任务

## Phase 1：治理与任务书

- [x] T001 完成项目、T08/T01/T05/T06/T11 源事实研究。
- [x] T002 确认区域命名、字段别名、边界缺失端点、Tool6→Tool4 和 P02 生命周期。
- [x] T003 建立五职责 SpecKit 工件与隔离工作树。
- [x] T004 更新项目字段语义、模块生命周期、模块盘点和文档状态。

## Phase 2：测试先行与实现

- [x] T005 检查所有待写 `.py` 当前字节数和 100KB 边界。
- [x] T006 [测试] 增加 T08 Tool3 `closed_connect` alias、一致双字段和冲突双字段测试。
- [x] T007 [研发] 实现 Tool3 copy-on-write `closed_connect -> closed_con`。
- [x] T008 [测试] 增加 P02 raw→canonical relation 转换、去重、冲突、missing target 测试。
- [x] T009 [研发] 实现 P02 relation callable 与 raw/converted/audit/summary 写出。
- [x] T010 [架构] 建立 P02 README、SPEC、architecture 01-06、INTERFACE_CONTRACT。

## Phase 3：T08

- [x] T011 Tool1 将四个指定 GeoJSON 转为 GPKG，校验 CRS、要素数和 hash。
- [x] T012 Tool3 处理 Nodes 并归一 `closed_con`。
- [x] T013 Tool6 生成候选；按用户授权直接作为 Tool4 输入。
- [x] T014 Tool4 copy-on-write 修复 Nodes/Roads。
- [x] T015 Tool5 在无 RCSDIntersection 模式完成复杂路口聚合。
- [x] T016 [QA] 校验 T08 输出 CRS、字段、输入未变、阶段计时与 summary。

## Phase 4：人工关系

- [x] T017 按 T11 字段写出 16 条 raw relation。
- [x] T018 使用 Tool5 final Nodes 生成 converted relation 与 lineage。
- [x] T019 [QA] 验证 selected IDs 存在、canonical target 唯一、冲突为 0。
- [x] T020 生成 T05 unavailable empty compatibility 工件及 manifest。

## Phase 5：T01/T05/T06

- [x] T021 运行 T01 全流程并验证 Segment、unsegmented 和缺失端点审计。
- [x] T022 运行 T05 Phase2，验证 12 条转换后人工关系的发布/失败/graph consumability。
- [x] T023 运行 T06 Step1、Step2、Step3。
- [x] T024 [QA] 验证 replacement plan、F-RCSD Road/Node integrity、source consistency 和 topology connectivity。

## Phase 6：回归与交付

- [x] T025 运行 T08/T01/P02/T05/T06 聚焦测试。
- [x] T026 检查所有受治理源码/脚本低于 100KB；本轮未改变 code-size audit 表内容。
- [x] T027 生成 P02 run manifest、业务 funnel、性能报告和待补关系清单。
- [x] T028 更新 SpecKit analyze/validation-report，区分已修改、已验证、待确认。

## Phase 7：人工锚定走廊边界修复

- [x] T029 [产品/架构] 用户确认 `5855295910117379 / 5855295910117428` 为锚定路口间连续 RCSDRoad 并授权修订边界规则。
- [x] T030 [测试] 增加 `CrossLid + 唯一精确端点重合` 保留归一及模糊/不重合拒绝测试。
- [x] T031 [研发] 实现 P02 人工锚定节点走廊保留、端点归一和扩展 audit/summary。
- [x] T032 [QA] 验证原始输入不变、CRS 一致、几何未改、`7379` 端点归一 lineage 完整。
- [x] T033 重跑 T05/T06，验证 `609020493_61493884` 有序 RCSD 通道和最终拓扑。
- [x] T034 刷新 QGIS 工程、validation report、性能和回归结果。

## Phase 8：完整原始数据重跑

- [x] T035 [产品/架构] 接收“不裁剪原始数据、无锚定 Segment 不替换”的最新约束并同步 P02/T05/T06 契约。
- [x] T036 [研发] 撤销 P02 local clip 与端点归一实现/测试，保留人工关系转换 callable。
- [x] T036A [T08/测试] Tool3 对完整输入中的悬空 Road 仅跳过环岛拓扑计算并写 summary 审计，不裁剪 Road。
- [x] T037 以完整 SWSD/RCSD 执行 Tool1→Tool3→Tool6→Tool4→Tool5、T01、T05、T06。
- [x] T038 [QA] 验证 T05 输入保留 469 条 RCSDRoad/655 个 RCSDNode，缺失端点仅审计且未 silent fix。
- [x] T039 [QA] 验证无正式锚定 Segment 未进入 replacement plan，并复核四个目标 Segment。
- [x] T040 刷新 run04 QGIS 工程、manifest、validation report、性能与回归结果。
- [x] T041 [产品/架构] 接收用户逐项确认的 `5855295910117569.ENodeId: 5855295910117804 -> 5855296278770549` 临时覆盖，并同步 P02/T05/T06 契约与 SpecKit。
- [x] T042 [研发] 在 run05 完整 RCSDRoad copy-on-write 工作副本执行严格旧值校验和唯一端点覆盖，输出独立审计。
- [x] T043 [测试/QA] 验证覆盖只改一个字段，Road 数量/ID/几何不变，且不消费 `NodeLid/CrossLid` 或几何推断。
- [x] T044 重跑 Tool1→Tool3→Tool6→Tool4→Tool5、T01、T05、T06；`3086610_609284657` 正向恢复，反向仍被双向硬门禁拒绝。
- [x] T045 run05 manifest、GIS QA、QGIS 工程和 validation report 被后续 run06 取代，不再作为最终交付。
- [x] T046 [产品/架构] 接收第二项用户确认 `5855295910117517.SNodeId: 5855295910117644 -> 5855296278770302`，同步 P02/T05/T06 契约与 SpecKit。
- [x] T047 [研发] 在 run06 从原始输入生成完整 RCSDRoad copy-on-write 工作副本，逐项强校验并仅应用两项确认覆盖。
- [x] T048 [测试] 以 run06 重新执行 Tool1→Tool3→Tool6→Tool4→Tool5→T01→T05→T06，并执行聚焦回归测试。
- [x] T049 [QA] 核验两项目标通路、replacement plan、最终 F-RCSD topology、CRS、几何、审计和性能。
- [x] T050 刷新 run06 manifest、GIS QA、QGIS 工程和 validation report。

## Phase 9：RCSDRoad 端点全量修正

- [x] T051 [产品/架构] 接收用户对剩余 7 项端点错配的全量修正授权，与原 2 项合并为 9 项显式白名单，并同步 P02/T05/T06 契约与 SpecKit。
- [x] T052 [研发] 生成 run07 RCSDRoad copy-on-write 工作副本，逐项强校验并应用 9 项覆盖。
- [x] T053 [测试/QA] 验证仅 9 个属性单元变化，469 条 Road、ID、几何与 CRS 不变，缺失端点数从 9 降为 0。
- [x] T054 从端点覆盖后重跑 T05/T06，核验 `609020493_61493884` required junction 通路及全部 replacement plan。
- [x] T055 刷新 run07 GIS QA、QGIS 工程、manifest、性能和 validation report。

## Phase 10：T06 并行通道归属修复

- [x] T056 [产品/架构] 确认 `609020493_61493884` relation 正确，问题限定为两个 ready plan 的并行 RCSD 通道归属，不修改人工关系。
- [x] T057 [研发] 在 Step2 视觉门禁中实现受限并行走廊重分配，要求主 plan 保有方向、required junction 与覆盖成立的替代通道。
- [x] T058 [研发] 将 `parallel_corridor_peer_road_ids` 贯通 Step2 plan、Step3 unit/relation，分离 Road 归属与 peer connectivity 证据。
- [x] T059 [历史 run07/已被 T061-T065 纠正] 当时把 4 段通道判给小 Segment；该业务结论已由原始 Road 中间锚点证据否定，不作为最终成果。
- [x] T060 [历史 run07] 完成当轮 Linux 765 项回归、Windows 平台差异审计与 QGIS 55 图层回读；业务通道归属以 Phase 11 run08 为准。

## Phase 11：锚点优先级与反向归属修复

- [x] T061 [产品/架构] 以原始 RCSDRoad 复核两条并行通道，确认小 Segment 的两个中间锚点只由 5 段通道有序覆盖，不修改人工 relation。
- [x] T062 [测试] 增加“锚定关系优先于相对位置、相对位置优先于距离”回归，以及禁止 peer 通道代替当前 Segment 锚点覆盖的 Step3 回归。
- [x] T063 [研发] 修复 Step2 有序锚点通道选择和 Step3 peer connectivity 遗留策略，同步 T06/P02 契约。
- [x] T064 [QA] 生成 run08，验证小 Segment 获得锚点约束的 5 段通道、大 Segment 获得 4 段通道、Road 唯一归属和正式 topology fail 为 0。
- [x] T065 [QA] 刷新 run08 GIS QA、QGIS 工程、766 项完整回归与 validation report。

## Phase 12：RCSD Road 唯一归属收口

- [x] T066 [产品/架构] 确认普通 RCSD Road 最多归属一个 Segment；特殊路口内部 Road 与 multi-Segment connectivity Road 可无 Segment owner。
- [x] T067 [测试/研发] 将唯一归属收口接入 ownership ledger、Segment relation、F-RCSD Road、added-road audit 与 surface refresh，并对多值发布执行 hard fail。
- [x] T068 [架构] 修订 `path_corridor_group` 语义：仅表示组级原子执行/回退，不表示 Road 多 Segment 所有权。
- [x] T069 [QA] 生成 run09，验证原 8 条多归属 Road 为 4 条唯一归属、3 条特殊路口内部无归属、1 条 connectivity 无归属、0 条多归属。
- [x] T070 [QA] 完成 T06 418 项回归、run09 GIS QA 与 QGIS 56 图层机器回读；道路面覆盖检查保持不可执行并显式审计。
