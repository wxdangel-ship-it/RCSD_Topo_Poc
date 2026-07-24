# Cross-document Analyze: P04 Segment-first Road 直出

## 1. Source-of-truth 冲突与授权

### 1.1 已识别冲突

实施前P04模块源事实和V3实现仍以SWSD Road owner、Road级支持状态、T03/T04/T07/RCSD comparison-only、Road内`swsd_fallback`为主，与新Segment-first目标不一致。

### 1.2 解决授权

用户于2026-07-22明确授权方案A：

- 同步P04模块级及最小项目级source-of-truth；
- 保持P04 `Active POC / 成果模块`；
- 不修改T01–T12；
- 使用独立Segment-first SpecKit和版本化实现；
- 历史M1/M2/V2/V3保留。

结论：源事实迁移边界已获授权，不再以旧Road-owner口径阻断新版本；同步文档必须在实现前完成。

## 2. 文档一致性

| 主题 | spec | research | data model | contract | plan | tasks | 结论 |
|---|---|---|---|---|---|---|---|
| T01 Segment主对象 | FR-001~006 | D1/D2 | SegmentBuildUnit | §7 | Phase2/3 | T027~T034 | 完整 |
| 四态与单Segment回退 | US1 | D2/D9 | 状态机/CarrierPlan | §7/9 | Phase3 | T042~T050 | 完整 |
| observed+constrained | US2/FR-010~012 | D3/D4 | EvidenceSpan/Road | §3/9 | Phase4 | T051~T060 | 完整 |
| 多方向/主辅Road | US2/FR-007~009 | D5 | CarrierPlan | §3/7 | carrier设计 | T039~T045 | 完整 |
| T07/T03/T04/T08 | US3/FR-014~022 | D6/D7 | JunctionUnit | §8 | Phase2 | T029~T034 | 完整 |
| mainnode/shared Node | US3/FR-018~020 | D8 | Node/RoadNextRoad | §4/5 | Phase5 | T061~T066 | 完整 |
| junc_nodes/THROUGH | US4/FR-023 | D9 | SegmentAccess | §8/9 | Phase2/5 | T032/T033/T071 | 完整 |
| LaneTopo/局部结构 | US4/FR-025~028 | D10~D12 | Movement/Clue | §6/9 | Phase5 | T067~T071 | 完整 |
| 跨Patch/稳定ID | US4/FR-003/029/030 | D13/D15 | ID/manifest | §3/4/11 | Phase0/5 | T037/T061/T091 | 完整 |
| 正式三图层 | US5/FR-031~033 | D14 | publication layer | §2~6 | Phase6 | T072~T080 | 完整 |
| hard/soft QA | FR-034~038 | D16 | reason/state | §9~13 | Phase6/7 | T074~T095 | 完整 |
| 旧版本和入口保护 | FR-039/040 | D17 | N/A | §1 | 全阶段 | T017/T081/T082/T092 | 完整 |

未发现spec、model、contract、plan、tasks之间的业务冲突。

## 3. 五类职责覆盖

| 职责 | 覆盖证据 |
|---|---|
| 产品 | 完整Segment、正式三图层、QGIS、业务报告；T009/T093 |
| 架构 | 本体分层、source-of-truth、版本隔离、输入复用；T001~T010/T094 |
| 研发 | `segment_first_*`职责拆分、pipeline、输出；T018~T081 |
| 测试 | contract/unit/integration/legacy/determinism；T013~T017/T019~T091 |
| QA | independent QA、真实数据、QGIS、人审、证据矩阵；T006/T016/T034/T041/T050/T060/T071/T078/T084~T095 |

结论：任务书满足仓库要求的产品/架构/研发/测试/QA五视角。

## 4. 宪章与AGENTS合规

- Brownfield研究已完成，旧产物非破坏保留。
- 大型任务采用完整SpecKit。
- 模块源事实将在实现前同步。
- 不新增长期入口，不触发entrypoint registry变更。
- 源码写入前有100KB precheck任务；新增职责按文件拆分。
- GIS任务覆盖CRS、拓扑、几何语义、审计追溯和性能。
- 不把未知字段或局部样本语义固化为强规则。
- 当前PowerShell与Windows路径一致，无跨环境路径冲突。

## 5. 范围一致性

### Included

- 当前有SWSD且功能结构未变化的测试场景；
- T01 Segment-first Road/Node/RoadNextRoad；
- T07/T03/T04/T08 surface复用；
- full RCSD anchor、Patch强证据；
- 部分支持、跨Patch、LaneTopo、Patch已有局部结构；
- independent QA/QGIS/人工审计。

### Excluded

- 无SWSD从零构图；
- 已确认现实结构变化自动改写；
- 缺失调头/短连接主动恢复；
- Restriction/Laneinfo/RoadSplit正式语义；
- T01–T12修改、T10接入、生产正式化；
- 神经模型直接决策。

没有任务把excluded内容重新引入实现。

## 6. 未决项分类

以下是实现期证据核对，不是业务澄清：

1. 当前Case各正式run root；
2. RCSD ID/source正式值域；
3. T07 accepted字段实际表达；
4. constrained completion数据阈值；
5. 发布CRS和性能预算。

它们均已由T012~T016、T055/T060/T073/T083/T092覆盖。若实际字段与source-of-truth冲突，按AGENTS §1.5停机，不自行反推。

## 7. 成功标准覆盖

SC-001~SC-015全部在T084~T095或前置gate中有直接证据任务。特别是：

- 代码测试不能替代完整run；
- core gate不能替代independent QA；
- QGIS构建不能替代人工审计；
- 高精替换率不是hard gate；
- 最终完成必须有逐SC证据矩阵。

## 8. 实施前就绪结论

SpecKit达到`specify / plan / tasks / analyze`就绪条件。下一步允许：

1. 按T001~T010同步P04模块级和最小项目级source-of-truth；
2. 执行真实输入preflight与旧版本保护；
3. 在全部源码写入前执行字节数检查；
4. 按Phase gate进入实现。

该结论是实施启动门禁；当前实现已经按后续第9节完成，不允许把历史V3或被否决run替代最终验收事实。

## 9. 实施后事实复核（2026-07-22）

### 9.1 旧run否决与历史验收run

旧run：

`outputs/_work/p04_road_direct_generation/1885118/p04_segment_first_member_1885118_20260722T211000`

虽然其技术门禁通过，但后续人工和实数审计发现两项业务错误：ordinary Junction把空间分离的全部端点折叠到单一中值Node，导致高精Road在路口前被拉扯；跨Segment被拒LaneTopo关系又被错误扩大为两侧Segment回退。因此它只保留为对照，不再是验收终态。

当时的历史验收run为（后续已被第11节闭域目标和第12节分布式路口合同取代）：

`outputs/_work/p04_road_direct_generation/1885118/p04_segment_first_junction_carrier_1885118_20260723T020000`

新run改为“高精portal + accepted surface/DriveZone支撑的双向JunctionUnit内部Road + 中心shared Node”，并将失败范围限制为owner Segment或Movement。生成阶段先得到`technical_passed`，随后finalizer校验QGIS道路面覆盖、真实PyQGIS回读、28层归一化确定性和5类人工极值审计，最终晋级`passed / accepted_with_review`。

### 9.2 真实数据结果

| 指标 | 冻结结果 |
|---|---:|
| T01 Segment | 330 |
| 四态 | hp_full 67 / hp_partial 29 / swsd_retained 198 / conflict_retained 36 |
| Road / Node / RoadNextRoad | 1082 / 855 / 3210 |
| Segment built / Segment retained / JunctionUnit built Road | 199 / 478 / 405 |
| SegmentAccess | 831 / 831 realized |
| ordinary JunctionUnit | eligible 251 / materialized 245 / snap-only 125 / final rejected 0 |
| Junction internal carrier | 405 Road / 466 accepted spoke / 39 DriveZone-supported |
| LaneTopo | 2941；mapped 554；显式excluded 2387；unresolved 0 |
| LaneTopo映射 | within Road 306 / Junction carrier path 200 / RoadNextRoad 48 |
| Movement内部切分 | 6个parent / 14个part / 8个accepted anchor / 0 rejected |
| built continuity | 1208端点；hard failure 0；最大shift 8.564m |
| Segment built几何QA | 199 Road；hard failure 0；Review 33 |
| QGIS道路域覆盖 | 604条built Road，98.8761% |
| 全部soft Review | 225 |
| 性能 | 85.287s，EPSG:32650 |

正式Road中的405条JunctionUnit Road不是额外业务Segment：其`segment_id`为空、`owner_type=JUNCTION_UNIT`，只负责在ordinary Junction内连接高精portal；正式Segment仍由T01的330个Segment拥有独立Road。

### 9.3 高精骨架改善量

以下对比由旧/新正式与审计GeoPackage按相同口径归一化复算：

| 指标 | 被否决旧run | 冻结新run |
|---|---:|---:|
| Segment高精built长度占比 | 13,321.47 / 86,373.27m = 15.423% | 23,400.57 / 84,484.30m = 27.698% |
| Patch Road被高精built使用 | 178 / 1004 = 17.729% | 336 / 1004 = 33.466% |
| 端点shift P95 | 13.681m | 1.358m |
| 端点shift P99 | 17.778m | 3.623m |
| 最大端点shift | 47.309m | 8.564m |
| shift > 3m | 412 | 29 |
| shift > 10m | 144 | 0 |

结论：新版本不是用更多SWSD几何换连续性，而是显著提高Patch高精证据消费率，同时消除ordinary路口的远距离中值Node拉扯。与历史V3约39%的直接观测比例仍不可直接横比：Segment-first禁止Road内SWSD坐标拼接，并对完整carrier/Access执行更严格原子门禁。

### 9.4 SC证据矩阵

| SC | 当前Case结论 | 直接证据 |
|---|---|---|
| SC-001 | PASS | 330个Segment唯一四态且每个至少1条独立Segment Road；independent QA |
| SC-002 | PASS | 198个`swsd_retained`、36个`conflict_retained`均有逐Segment carrier/reason审计 |
| SC-003 | PASS | 604条built Road的SWSD直接splice为0；geometry source完整 |
| SC-004 | PASS | 双向member执行两方向原子接管；无单向built与覆盖双向retained重叠 |
| SC-005 | PASS | 1082条Road均非空、valid、simple；built continuity hard failure 0 |
| SC-006 | PASS | 855个Node引用完整；3210条RoadNextRoad全部来自实际共享Node |
| SC-007 | PASS | 245个ordinary group materialized，405条JunctionUnit Road；final rejected portal 0 |
| SC-008 | PASS | 831/831 Access逐Road实现；171条THROUGH access无静默丢失 |
| SC-009 | PASS | 2941条LaneTopo全部mapped或显式excluded，unresolved 0 |
| SC-010 | PASS | 跨Patch证据统一组装；Patch边界内部断头0 |
| SC-011 | PASS | 两次完整run对正式/审计/关系共28层归一化属性与WKB一致 |
| SC-012 | PASS | 独立QA全部13项gate通过、violation 0；225条soft Review独立发布 |
| SC-013 | PASS | QGIS 33层，真实PyQGIS invalid 0、空间renderer缺失0、相对路径可读 |
| SC-014 | PASS WITH REVIEW | 人工复核最大shift/折角/长度比、多Road共享Node和未支撑portal单Segment回退 |
| SC-015 | PASS | 输入hash、参数、环境、85.287s性能及正式输出/验收证据hash可定位 |

### 9.5 与计划的实现差异

以下未改变当前Case的hard gate结论，但不应伪装为已经实现：

1. “单方向观测、另一方向由Surface/Boundary推导”尚未实现；当前采取双向member原子保留，正确性优先于替换率。
2. 当前Case没有可独立验证的roundabout样本；ordinary Junction carrier已落地，T04 complex走显式物理pair，roundabout/独立auxiliary仍需补样本验证。
3. 当前发布4条显式local connector，但调头/内部短连接细分类和Patch缺失恢复仍属于后续子模块。
4. 确定性已做两次完整run并比较28层；Patch读取由loader稳定排序，尚未做外部注入乱序replay。
5. LaneBoundary已进入输入/QGIS/lineage，但未作为“推导另一方向”的正式几何生成器。
6. 当前人工审计覆盖几何极值、ordinary carrier与单Segment回退；T04、环岛、主辅多Road仍需要独立分类型样本集扩展。

这些差异均采用保守retained、显式excluded或Review，不会把未知能力伪装成高精built Road；与统一本体及本阶段“有SWSD、功能结构未变化”口径不冲突。

## 10. 最终一致性结论

- P04模块级及最小项目级source-of-truth已同步；新增ordinary portal/JunctionUnit carrier、逐Road Access、LaneTopo阻断范围和Road owner事实。
- 历史M1/M2/V2/V3保留；P04专项与历史回归共83项测试通过。
- T01–T12没有文件修改；没有新增官方CLI/root script或entrypoint registry项。
- Segment-first共19个源码与11个专项测试均低于100KB；最大源码`segment_first_pipeline.py`为47485 bytes。
- 该结论只适用于上一轮全量发布与拓扑自洽目标；后续用户已将闭域高精骨架覆盖升级为当前阶段硬验收，因此旧run不得继续代表当前阶段完成。

## 11. 闭域高精骨架目标重开（2026-07-22）

用户授权继续执行后，当前目标新增SC-016：以T06 Step2可替换事实和T01端点Patch membership计算闭域目标。严格闭域要求每个端点终端Road的membership非空且完全属于当前六Patch；混合关联缺失Patch的10个Segment只进入边界审计。真实只读复算得到83个核心Segment和20个正式ADVANCE_RIGHT Segment。

旧run中83个核心目标仅24个`hp_full`、11个`hp_partial`具备完整主干built角色；33个`swsd_retained`和15个`conflict_retained`未达标。20个正式提右为13个`hp_full`、5个`swsd_retained`、2个`conflict_retained`。因此旧run虽保持330个Segment完整并通过原hard gate，但不能证明当前103目标角色高精覆盖。

该目标与统一本体兼容：T06只提供验收/锚定先验，T01仍是Segment owner，Patch Road/Lane/LaneBoundary/RoadSurface仍是最终built几何强证据，完整RCSD坐标不得直接发布。实现必须先同步source-of-truth，再进入Phase10。

## 12. 分布式路口与物理方向链审计事实（2026-07-23）

当前Active POC候选：

`outputs/_work/p04_road_direct_generation/1885118/p04_segment_first_physical_portal_v7_1885118_20260724T013000`

该run保持`failed`，未执行finalizer。其实现和审计口径为：

1. ordinary Junction不生成中心Node或默认星形`JUNCTION_UNIT` Road；物理portal Node保持空间分离，同一Junction共享`mainnodeid`。
2. Road允许按LaneGroup/Patch Road证据和物理拓扑边界细分；目标验收检查每个必要方向是否形成无分叉、端到端的Road链，不再只检查`main_*`角色是否出现。
3. T03/T07/T04 accepted Junction的方向链终端必须真实到达对应surface（允许配置的1m端点缓冲）；仅赋予`junction_group_id/mainnodeid`不能通过。
4. 缺口只允许在DriveZone completion surface内生成`hp_constrained_completion`，不直接拼接SWSD坐标。
5. SWSD source Node只提供Junction lineage和mainnode分组；built上下行portal不得因共享SWSD source Node而合并到中值点。跨Segment LaneTopo只在物理端点极近时共享Node，ordinary路口的空间分离portal由语义RoadNextRoad连接。
6. 同Segment约束补全形成共享Node时优先保留T03/T07/T04面内的受信portal，禁止中值点把最终Node再次拉出accepted surface；端点审计按最终Node几何复算。

真实结果：

| 指标 | 当前审计事实 |
|---|---:|
| Segment | 330 / 330完整发布 |
| 四态 | hp_full 102 / hp_partial 21 / swsd_retained 180 / conflict_retained 27 |
| Road / Node / RoadNextRoad | 756 / 875 / 2331 |
| built / retained Road | 308 / 448 |
| 闭域目标 | 76 / 103严格通过 |
| 核心主干 | 56 / 83严格通过 |
| 正式ADVANCE_RIGHT | 20 / 20严格通过 |
| 未达标核心目标 | 27 |
| ordinary内部星形Road | 0 |
| SWSD-only built portal无DriveZone支撑 | 0 |
| accepted surface最终Node越界 | 0 |
| accepted / rejected portal | 635 / 1 |
| built Road道路域覆盖 | 99.5696% |
| 独立QA | 0 violation，全部独立技术gate通过 |
| 专项回归 | 168 passed |
| 性能 | 359.180s，EPSG:32650 |

未达标27个核心目标必须继续保留在`target_realization`逐Segment审计中：22个同时缺少完整双向主干角色，5个终端Junction错配，其中`30956645_508332478`还同时存在双向链断裂。accepted surface最终Node越界已经清零。用户已确认的5个`Patch data insufficient`样本与`1882067_520668482` RealityChange候选尚未固化进生产目标分母，因此本run仍按103原始目标报告，不以重分类绕过hard gate。

QGIS工程显式包含SWSD Road/Node、完整RCSD Road/Node、Patch Road、结果Road/Node、方向链验收、Junction portal和Road-Lane关系。PyQGIS回读36层通过；自动覆盖证据为`p04_qgis_built_overlay_gate.json`，人工抽查图为`p04_manual_audit_*.png`。这些证据只证明当前实现的改善与剩余问题，不构成阶段完成。

## 13. SWSD路口先验保护与稳定Road细分（2026-07-24）

当前可审计候选：

`outputs/_work/p04_road_direct_generation/1885118/p04_segment_first_lane_topo_chain_v20_1885118_20260725T023000`

本轮明确SWSD/T01及T07/T03/T04 accepted Junction定义完备Junction—Segment拓扑，高精Patch证据只实例化物理Road。为提高Road—LaneGroup可追溯性，Road允许更细，但细分不得重新解释Junction：

1. 只接受Segment内部稳定纵向lineage交接；JunctionUnit surface按20m现有relation范围保护。
2. 细分在高精几何、平滑和端点协调完成后执行，父Road按精确里程切分；不重新拟合几何。
3. 每个accepted边界只增量插入稳定度2 Node；禁止二次全局Node编译。
4. LaneTopo跨多个细分part时投影到实际RoadNextRoad链并发布`carrier_path_road_ids`。

V13预几何细分改变carrier规划和几何，V14–V16二次Node编译造成断裂/端点误配，V17/V18虽加入Junction保护但仍因二次编译把3.5m分离portal在第一次协调后按2.08m误聚合，均被否决。V19改为增量Node后消除几何/路口回归；V20进一步修正多Road LaneTopo链投影。

| 指标 | V12b冻结骨架 | V20 |
|---|---:|---:|
| Segment / 四态 | 330；111/18/180/21 | 完全一致 |
| 闭域目标 | 84/103 | 84/103 |
| Road / built Road | 762 / 334 | 808 / 380 |
| Node / RoadNextRoad | 904 / 2282 | 950 / 2328 |
| 稳定细分 | 无 | 37 parent / 46 accepted boundary / 83 part |
| Junction保护拒绝 | 无 | 40 boundary |
| 既有Node变化 | N/A | 0；只新增46个内部度2 Node |
| 语义骨架组 | 431 | 431；最大Hausdorff `1.16e-10m` |
| Segment级有向关系 | 1363 | 1363；新增0 / 丢失0 |
| built continuity hard failure | 0 | 0 |
| Road-Lane relation | 1232 | 1244；380条built Road全有关系 |
| LaneTopo Review | 1 | 1；另1条映射为三Road实际链 |
| 独立QA | PASS | PASS，0 violation |
| QGIS道路域覆盖 | 99.5954% | 99.5954% |
| QGIS回读 | 37层valid | 38层valid，含86条细分决策 |
| 性能 | 约基线run | 535.464s，EPSG:32650 |

accepted细分点距任一JunctionUnit surface最小21.758m；40个保护拒绝候选距离范围0–18.051m。V20正式Road/Node/RoadNextRoad与V19逐ID的WKB完全一致，唯一预期变化是LaneTopo多Road链审计。

V20仍保持`terminal_status=failed`：19个核心目标未高精完成，且冻结基线已有的1条`review_shared_node_relation_missing`未解决。该状态不能由本轮Road细分、QGIS通过或Review标签绕过；因此本节证明“SWSD路口拓扑不被LaneGroup细分破坏”和“Road—Lane关联改善”，不构成P11阶段完成。

## 14. SWSD完整拓扑合同与V24实证（2026-07-25）

用户进一步明确：应先从原始SWSD理解完备道路拓扑，尤其是路口；同时Road可以为关联LaneGroup而更细碎。该口径不是回到SWSD几何，而是把SWSD提升为“完整拓扑合同”：

1. 逐Segment校验全部Access的进入/离开方向；
2. ordinary Junction校验方向兼容的全部进入Road×离开Road组合；
3. T04 complex不默认全连接，只消费实际物理关系；证据暂缺时，仅允许原始SWSD shared Node、member lineage匹配、portal位于accepted surface三证俱全的显式弱fallback；
4. Road可在Junction保护区外的稳定LaneGroup交接处细分，拓扑合同按归一化方向链验收，不要求输出Road与SWSD Road一一对应。

V23首次加入Movement合同后发现4个ordinary Junction存在仅靠lineage属性、几何分别距surface约36m、41m、70m和213m的伪Access。实现没有补造跨空关系，而是将失败限制为4个owner Segment并原子回退。

V24候选`p04_segment_first_swsd_junction_v24_1885118_20260725T110000`结果：

| 指标 | V24 |
|---|---:|
| Segment完整发布 | 330 / 330 |
| Road / Node / RoadNextRoad | 799 / 926 / 2332 |
| built / retained Road | 356 / 443 |
| SWSD Access方向合同 | 831 / 831 |
| Junction Movement合同 | 371 / 371 |
| expected / actual Movement | 2181 / 2181 |
| ordinary / complex Junction合同 | 369 / 2 |
| complex SWSD显式fallback | 1 |
| LaneGroup交接细分 | 5，父几何逐点/逐段保持 |
| independent QA | PASS，0 violation |
| QGIS | 41层，PyQGIS回读PASS |
| built Road道路域覆盖 | 99.5488455% |
| 运行时间 | 403.681s |

人工图面复核确认：未生成路口中心Node或星形Road；4个不受支撑的高精portal只局部回退；T04 `1898198`只增加1条可追溯显式Movement。V22到V24只有上述4个owner Segment发生预期几何/状态变化，其余326个Segment的Road ID和几何不变；5个LaneGroup细分点全部保持0m几何差异。

V24仍为失败候选而非阶段成果：闭域目标仅82/103完成，尚有21个核心目标未高精实现，并保留1条`review_shared_node_relation_missing`。因此本轮只证明“完整SWSD路口拓扑不因高精实例化或Road细分而丢失”，不能绕过闭域目标和LaneTopo门禁。

## 15. SWSD功能骨架与LaneGroup细Road兼容验证（2026-07-26）

当前可审计候选：

`outputs/_work/p04_road_direct_generation/1885118/p04_segment_first_t04_lane_topo_v30_1885118_20260726T030000`

本轮进一步按业务口径区分两层事实：

1. 原始SWSD定义完整Junction—Segment功能拓扑，包括全部Access和路口进出关系；
2. Patch Road/Lane/LaneGroup决定正式Road的高精几何、方向和细分粒度；细Road允许在同一Segment内增加实际共享Node或局部carrier关系，但不得增删跨Segment功能关系；
3. ordinary Junction的物理Node可分布在accepted surface内，同组共享`mainnodeid`；`mainnodeid`本身不编译RoadNextRoad；
4. T04 complex不得按ordinary全连接。仅当accepted LaneTopo、已发布`local_connector`、其出口到目标入口的连线位于T04 accepted surface内且距离受限时，增加`complex_junction_lane_topo_explicit`关系。

V30真实结果：

| 指标 | V30 |
|---|---:|
| Segment完整发布 | 330 / 330 |
| Road / Node / RoadNextRoad | 818 / 951 / 2350 |
| built / retained Road | 389 / 429 |
| SWSD Access方向合同 | 831 / 831 |
| Junction Movement合同 | 371 / 371 |
| expected / actual Movement | 2194 / 2194 |
| T04 SWSD / LaneTopo显式关系 | 1 / 1 |
| 闭域目标 | 84 / 103 |
| 核心主干 / ADVANCE_RIGHT | 64 / 83；20 / 20 |
| LaneTopo unresolved | 0 |
| independent QA | PASS，0 violation |
| QGIS | 42层，invalid 0；Road-Lane Relation 960条；SWSD完整路口结构371条 |
| built Road道路域覆盖 | 99.5354437% |
| 专项测试 | 201 passed |
| 运行时间 | 389.913s，EPSG:32650 |

将V24和V30正式RoadNextRoad按`junction_group_id + source_segment_id + target_segment_id`归一化后，跨Segment关系均为1255组，新增0、丢失0；差异只存在于同一Segment内部：V24为470组，V30为475组。这证明更细Road没有重新解释SWSD业务骨架。

人工审计图同时叠加SWSD Road、完整RCSD Road、Patch Road、Lane、DriveZone和结果Road。通过样本中，高精双向主干沿Patch/Lane中心走廊发布，复杂Segment可拆为多条连续Road；路口样本保留1–9个空间分布Node并统一`mainnodeid`，未向单一中心点拉扯。19个未达标核心目标仍以retained或失败方向链明确阻断，其中缺资料和terminal mismatch不得用Review绕过。

细粒度审计同时发现：389条built Road中40条短于10m、15条短于5m；14条短Road可直接追溯到Movement父carrier，其余主要继承Patch短Road/局部物理片段。最长细分样本`30956645_508332478`包含15条built Road，双向主链连续，其中5个稳定纵向lineage交接被接受、4个临近Junction的候选被保护拒绝。短Road不是当前hard failure，但不能仅以“更细”判优；后续人工审计应结合Road-Lane Relation、Movement Split Audit和Road证据边界切分层逐条确认，必要时只合并证据身份等价且不承载Access/Movement/LaneGroup边界的相邻短Road。

V30的`terminal_status`仍为`failed`，唯一未通过的核心门禁是`mandatory_target_high_precision_complete`。因此本节证明“SWSD完整功能拓扑与LaneGroup细Road兼容、LaneTopo可闭环、几何/拓扑技术门禁通过”，不构成P12或整个阶段完成。

## 16. accepted surface方向portal与LaneGroup细Road收敛（V46）

当前可审计候选：

`outputs/_work/p04_road_direct_generation/1885118/p04_segment_first_distributed_junction_portals_v46_1885118_20260726T190000`

本轮先以原始SWSD复核完整路口表达：Segment Access和ordinary进入—离开Movement提供功能拓扑合同；高精Road不应收敛到SWSD中心Node，而应在T07/T03 accepted surface内保持方向portal。实现据此收敛三项事实：

1. 目标主干按accepted surface本体裁切，不再把额外1m缓冲作为Road终点；
2. built方向Road不得经同一SWSD source Node或保留`semantic_carrier`重新聚合到中心坐标；保留Road仍可参与ordinary语义RoadNextRoad，所有同组Node共享`mainnodeid`；
3. LaneGroup细分后的LaneTopo可以经过有限的保留`semantic_carrier`实际有向链，但全部中间Road必须是`realization=retained / carrier_role=semantic_carrier`，不得接受任意图可达。

V46真实结果：

| 指标 | V46 |
|---|---:|
| Segment完整发布 / 四态 | 330/330；hp_full 107、hp_partial 19、swsd_retained 180、conflict_retained 24 |
| Road / Node / RoadNextRoad | 876 / 1129 / 2494 |
| built / retained Road | 449 / 427 |
| 闭域目标 | 86/103 |
| 核心主干 / ADVANCE_RIGHT | 66/83；20/20 |
| SWSD Access方向合同 | 831/831 |
| Junction Movement合同 | 371/371；expected/actual 2290/2290 |
| ordinary / complex Junction | 369 / 2 |
| 3个及以上Segment接入且built portal仅1个空间Node | V35为10组；V46为0组 |
| Road细分 | 63 parent、98 boundary、161 part；LaneGroup boundary 9 |
| LaneTopo | unresolved/Review 0；4条映射为实际多Road链 |
| 几何 | invalid/non-simple/hard failure 0；soft Review 16；最大采样转角58.477° |
| independent QA | PASS，0 violation |
| QGIS | 42层，PyQGIS read_ok，invalid 0 |
| built Road道路域覆盖 | 99.4692147%，0.98门槛PASS |
| 专项回归 | 212 passed |
| 性能 | 428.533s，EPSG:32650 |

重点路口`1882068`和`602671072`从“两个方向built Road与保留Road全部回并到SWSD中心Node”改为：两个高精物理Node保留不同坐标，同组共享一个`mainnodeid`，保留semantic Node继续存在但不吸附built portal。QGIS人工图显示高精Road沿Patch/Lane走廊进入accepted surface，没有中心星形Road；复杂路口仍未获得ordinary默认全连接。

QGIS工程显式包含当前Road/Node/RoadNextRoad、原始SWSD Road/Node、完整RCSD Road/Node、Patch Road/Lane/Boundary/DriveZone、SWSD完整路口结构、方向链、Road-Lane Relation和全部Review层。`p04_qgis_built_road_drivezone_overlay_gate.json`是高精built Road的正式空间覆盖门禁。全量Road相对Patch DriveZone只有71.6611%，原因是427条完整发布所需的retained SWSD Road包含Patch范围外/无高精资料区域，该比例不得用于否定built几何，也不得冒充全量高精覆盖。

V46的`terminal_status`仍为`failed`，唯一未通过的core gate是`mandatory_target_high_precision_complete`：17个核心目标方向链尚未高精完成。用户已同意的5个`Patch data insufficient`和`1882067_520668482` RealityChangeClue仍未固化为生产目标分母，当前继续按原始103报告，不通过Review或重分类静默绕过。V46是本轮“SWSD完整拓扑 + LaneGroup细Road + 分布式高精portal”的可审计候选，不是P10/P12最终完成态。

## 17. accepted surface保护域与V49单调端点补全

用户确认方案A：Road细分保护区采用`accepted surface + junction_endpoint_buffer`；`relation_endpoint_max_distance_m=20`只承担关系检索，不能扩大Road细分保护区。实现和源事实均已统一为该口径。

V47将SWSD member正反向路径直接用于carrier角色后，因一个Segment hard fallback释放的Patch证据没有重新参与其他Segment的access recovery，目标从V46的86/103退化为83/103。该实验证明SWSD路径合同本身有价值，但在证据占用固定点完成前不能进入正式发布。当前保留`swsd_segment_directional_paths`审计层，唯一/歧义均可见，正式Road暂不消费路径角色。

V48进一步发现：把扩大的端点补全距离同时用于候选路径排序，会恢复`1921620_620559468`，但错误换选其他Segment的证据链并造成新退化。V49据此分离两类距离：

1. 候选路径排序继续使用原正式关系范围；
2. 已选证据链到accepted endpoint surface的补全上限由最小观测覆盖率允许的缺失比例决定；
3. 补全段仍必须100%来自`hp_observed + hp_constrained_completion`，并通过DriveZone覆盖、几何和拓扑hard gate。

当前可审计候选：

`outputs/_work/p04_road_direct_generation/1885118/p04_segment_first_monotonic_endpoint_v49_1885118_20260724T140000`

| 指标 | V46 | V49 |
|---|---:|---:|
| Segment完整发布 | 330/330 | 330/330 |
| 四态 | hp_full 107、hp_partial 19、swsd_retained 180、conflict_retained 24 | hp_full 108、hp_partial 18、swsd_retained 180、conflict_retained 24 |
| Road / Node / RoadNextRoad | 876 / 1129 / 2494 | 879 / 1135 / 2498 |
| built / retained Road | 449 / 427 | 454 / 425 |
| 闭域目标 | 86/103 | 87/103 |
| 核心主干 / ADVANCE_RIGHT | 66/83；20/20 | 67/83；20/20 |
| V46目标丢失 | — | 0 |
| 新增恢复 | — | `1921620_620559468` |
| 几何hard failure / soft Review | 0 / 16 | 0 / 17 |
| independent QA | PASS | PASS |
| QGIS | 42层 | 43层；项目/图层CRS均为EPSG:32650，invalid 0 |
| built Road道路面内长度 | 99.469215% | 99.481951% |
| 专项回归 | 212 passed | 221 passed |
| 运行时间 | 428.533s | 414.5s |

QGIS全局渲染显示新Road在Patch覆盖区内保持高精走廊，未回到SWSD中心星形。新增恢复Segment`1921620_620559468`的双向Road与Patch Road/Lane走廊对齐，曲线连续；端点补全比例约16.7%至23.8%，其中1条Road因completion Hausdorff进入soft Review，但无invalid、非simple或hard failure。454条built Road相对`DriveZone ∪ accepted JunctionUnit surface`的长度覆盖率为99.481951%，0.90逐层/0.95总体门禁通过。

V49仍为`terminal_status=failed`，因为剩余16个核心目标尚未高精完成。5个已确认`Patch data insufficient`和`1882067_520668482` RealityChangeClue仍保留显式分类，尚未从103目标分母静默移除；SWSD方向路径角色进入正式发布前还必须完成fallback后证据占用重协调固定点。

## 18. fallback证据固定点、SWSD方向角色与V54单调发布

V50先实现fallback后的证据占用重协调：仅当恢复候选的冲突owner Segment已进入原子保留，且没有其它有效built carrier继续占用该证据时，才释放候选重新参与规划。Case 1885118释放2条冲突候选，`1885137_74295305`不再被已fallback的`1885118_1885134`错误占用；V50保持87/103且全部既有hard gate通过。

V51补充“显式关系端点已经属于同一物理Node组件”判定，避免把冗余关系误报为新环；真实数据中三个同Segment冲突仍属于实际组件闭环或Road重叠，不是重复Node关系，因此V51没有虚假放宽，保持87/103。

V52首次启用唯一SWSD member方向路径并允许单member用一方向观测、RoadSurface推导另一方向，目标增加`1914979_506231207`，但推导过早抢占`1894718_1898205`已经成立的Segment级高精走廊，产生1条`movement_anchor_distance_exceeded`硬失败。该候选被否决。最终仲裁顺序改为：

1. 完整Segment方向走廊；
2. baseline/access恢复；
3. 仅在前两者失败后执行单member缺方向Surface推导。

V54当前可审计候选：

`outputs/_work/p04_road_direct_generation/1885118/p04_segment_first_member_endpoint_completion_v54_1885118_20260724T190000`

| 指标 | V49 | V54 |
|---|---:|---:|
| Segment完整发布 | 330/330 | 330/330 |
| 四态 | hp_full 108、hp_partial 18、swsd_retained 180、conflict_retained 24 | hp_full 108、hp_partial 19、swsd_retained 179、conflict_retained 24 |
| Road / Node / RoadNextRoad | 879 / 1135 / 2498 | 881 / 1138 / 2514 |
| built / retained Road | 454 / 425 | 455 / 426 |
| 闭域目标 | 87/103 | 88/103 |
| 核心主干 / ADVANCE_RIGHT | 67/83；20/20 | 68/83；20/20 |
| V49目标丢失 | — | 0 |
| 新增恢复 | — | `1914979_506231207` |
| Access / Junction Movement合同 | 831/831；371/371 | 831/831；371/371 |
| 几何hard failure / soft Review | 0 / 17 | 0 / 18 |
| Movement anchor rejection | 0 | 0 |
| independent QA / QGIS回读 | PASS / PASS | PASS / PASS |
| built Road道路面内长度 | 99.481951% | 99.484088% |
| 专项回归 | 221 passed | 225 passed |
| 运行时间 | 414.5s | 363.1s |

V54相对排序修正后的V53，正式Road/Node/RoadNextRoad在排除`run_id`后属性与WKB几何逐对象完全一致；V54同时把`508668645_608667653`的无效endpoint救援更早判为retained。该Segment的四段端点补线距accepted surface约16.3m至20.3m，但DriveZone覆盖只有34.8%至56.5%，不满足90%硬门槛，因此不能用Review强行发布。

QGIS人工复核`1914979_506231207`和`1894718_1898205`确认：两条方向Road沿Patch Road/Lane走廊平滑分离，不回拉到SWSD中心Node；Road端点分布在合理Junction surface范围内。PyQGIS overlay对455条built Road得到99.484088%道路面内长度覆盖，逐层0.90/总体0.95门禁通过。

V55尝试让raw Patch component直接补到endpoint surface，`600658673_608658375`和既有目标`520669356_601668105`均触发`completion_turn_conflict`，目标从88退化为87。该策略按单调门禁否决，代码已撤销，V55只保留为反例run。

当前15个未达标核心目标分为：5个已确认`Patch data insufficient`、`1882067_520668482` RealityChangeClue、`1882067_1898182`双向Road终端错配、4个明确LaneTopo/几何/连续性hard conflict，以及4个仍需按accepted surface与Patch证据继续分析的主干缺口。当前仍按103原始目标报告，不用分类或Review静默降低分母。

## 19. accepted endpoint surface短桥接与V57

`600658673_608658375`的SWSD参考轴约27.6m，但两个T03 accepted surface加正式1m端点缓冲后仍只相隔约3.45m；Patch Road `5417631180197930:5469399104422395`提供一条约4.46m、DriveZone覆盖100%的单方向桥接证据。用SWSD轴60%覆盖率会把真实短Road误判为资料不足。V57只对已通过`target_access_surface_candidate/recovery_eligible`的候选启用surface-to-surface组装：观测方向完成到两个不同保护区，另一方向由RoadSurface受约束偏移推导，两个方向继续原子验收。

V56反例显示，`51811143_506668044`的两个端点保护区重叠约247.5㎡，一条约5.2m短线同时落入两个surface，无法证明从一个Junction交接到另一个Junction，并触发SWSD方向合同回退。最终规则因此硬拒绝相接/重叠保护区，不把同一Junction内部短线或端点归属歧义冒充完整Segment。

当前可审计候选：

`outputs/_work/p04_road_direct_generation/1885118/p04_segment_first_endpoint_surface_bridge_v57_1885118_20260724T220000`

| 指标 | V54 | V57 |
|---|---:|---:|
| Segment完整发布 | 330/330 | 330/330 |
| Road / Node / RoadNextRoad | 881 / 1138 / 2514 | 882 / 1142 / 2516 |
| built / retained Road | 455 / 426 | 457 / 425 |
| 闭域目标 | 88/103 | 89/103 |
| 核心主干 / ADVANCE_RIGHT | 68/83；20/20 | 69/83；20/20 |
| V54目标丢失 | — | 0 |
| Segment终态变化 | — | 仅`600658673_608658375` |
| Access / Junction Movement | 831/831；371/371 | 831/831；371/371 |
| LaneTopo unresolved / 几何hard | 0 / 0 | 0 / 0 |
| soft Review | 18 | 18 |
| independent QA | PASS，0 violation | PASS，0 violation |
| QGIS回读 | PASS | 主工程43层、完整业务审计46层、局部工程16层，均invalid 0，EPSG:32650 |
| built Road DriveZone覆盖 | — | 99.433853% |
| 专项回归 | 225 passed | 226 passed |
| 运行时间 | 363.1s | 364.3s |

局部QGIS渲染确认：两条新Road位于Patch居中走廊两侧，端点分别进入两个accepted surface，不被拉向SWSD中心Node；观测方向completion约8.80%，推导方向完整标记`surface_inferred_review`，两条Road的最终最大转角约3.26°至3.85°，几何hard/soft均为0。V57仍为`failed`，唯一未通过的core gate是`mandatory_target_high_precision_complete`，剩余14个目标不能由本规则继续泛化强补。

## 20. 局部RoadSurface端点路由与V61

`508668645_608667653`存在两条同版本、方向相反的高精主走廊，观测长度约80.3m与81.3m，分别关联Lane `5469331089523031/5469331089523035`；它们与SWSD方向轴夹角小于0.2°，但端点距两端T03 accepted surface约19.6m至23.2m。V54只用端点—surface直线，DriveZone覆盖约34.8%至56.5%，因此正确保留；真实道路域检查发现端点到surface存在局部连续弯折路径，问题是直线模型不足，不是高精证据缺失。

V58引入局部可见性最短路后恢复该Segment，但新Road使真实LaneTopo交接被识别，邻接Segment `1881842_608667653`的主carrier在Movement锚点切出端点面外尾段；该尾段继续发布造成方向链`disconnected/terminal_mismatch`，使既有目标丢失1。V58因此否决。最终规则只在Movement由新endpoint路由Road直接触发、同父carrier恰有唯一片段贯穿两个端点面时抑制端点面外兄弟尾段，并保留`segment_main_tail_outside_endpoint_corridor_suppressed`审计。对无直接因果的Movement不启用该规则。

最短路初版贴道路面边界，后续平滑切角导致新增Road对原始DriveZone局部覆盖仅约80%；总体门禁虽仍通过，但人工审计判为不可接受。V61把路径中间边界拐点向合法域内部预留0.75m POC安全余量，再执行既有平滑；最终两条Road对正式`DriveZone+1m completion buffer ∪ accepted endpoint surface+1m`覆盖100%，最终最大局部转角约20.06°与22.00°，invalid/non-simple/hard failure均为0。一条Road因completion Hausdorff进入soft Review，不绕过任何hard gate。

当前可审计候选：

`outputs/_work/p04_road_direct_generation/1885118/p04_segment_first_surface_routing_v61_1885118_20260725T001000`

| 指标 | V57 | V61 |
|---|---:|---:|
| Segment完整发布 | 330/330 | 330/330 |
| Road / Node / RoadNextRoad | 882 / 1142 / 2516 | 883 / 1146 / 2518 |
| built / retained Road | 457 / 425 | 459 / 424 |
| 闭域目标 | 89/103 | 90/103 |
| 核心主干 / ADVANCE_RIGHT | 69/83；20/20 | 70/83；20/20 |
| V57目标丢失 | — | 0 |
| 正式Road变化Segment | — | 仅`508668645_608667653` |
| Access / Junction Movement | 831/831；371/371 | 831/831；371/371 |
| LaneTopo unresolved / 几何hard | 0 / 0 | 0 / 0 |
| soft Review | 18 | 18 |
| independent QA | PASS，0 violation | PASS，0 violation |
| PyQGIS | 主43层0 invalid | 主44层、局部13层均0 invalid |
| built Road原始DriveZone总体覆盖 | 99.433853% | 99.281357% |
| 新增Road正式completion surface覆盖 | — | 100% |
| 专项回归 | 226 passed | 230 passed |
| 运行时间 | 363.2s | 387.2s |

局部QGIS工程同时加载V61新Road/Node、V57保留Road、原始SWSD、一张图RCSD、Patch Road、Lane、LaneBoundary、DriveZone、accepted surface、Geometry Source与RoadNextRoad。人工目视确认：新绿/蓝双向Road沿Patch Lane和完整RCSD的南北向高精走廊，明显避开V57/SWSD偏西几何；两端分别进入两个accepted surface，不向SWSD中心Node回拉。V61仍因剩余13个目标未完成而保持`failed`，不得finalize。

## 21. V61剩余13条原始证据复核

V61剩余13条分为5条`patch_data_insufficient`、1条`RealityChangeClue`、4条明确hard conflict与3条`partial_evidence_unresolved`。本轮重新从V61的`target_carrier_fragments`、SWSD方向成员、DriveZone、accepted surface、正式Road与fallback审计逐条复核，没有发现可以继续复用Phase15规则安全恢复的Segment。

三个部分支持目标的事实为：

- `1882067_1898182`的SWSD方向链由北侧`625319037`（183.437m）与南侧`621948539`（62.857m）组成；两条built Road只覆盖南侧成员，北侧没有高精carrier。因此`terminal_mismatch`不是Node编译错误，不能把南侧Road沿SWSD坐标延长。
- `1885108_608669457`参考轴长75.851m，forward/reverse观测投影覆盖分别只有0.295/0.413，均低于0.50最小门槛。
- `30899951_30956454`参考轴长838.814m，forward/reverse观测投影覆盖实际为0.910/0.765；V54“仅约69–106m观测”的描述不准确。真正阻断点是forward关键缺口45.51m、直连DriveZone覆盖0.336，reverse关键缺口99.23m、覆盖0.209，且两处均不存在满足0.90门槛的局部RoadSurface路径。不得按SWSD顺序跨资料空洞强连。

四条hard conflict继续保持：

- `1881833_1891598`、`1885118_1885134`：LaneTopo会形成`junction_group_or_same_road_cycle_rejected`；
- `1885130_1891598`：候选观测比例0.141、补齐比例0.859，补齐引入178.842°转角并形成180°折返；
- `506637092_610635356`：built端点偏移53.481m，超出方案A边界。

5条Patch资料不足与`1882067_520668482` RealityChangeClue继续按已确认分类显式发布审计，不用Review或目标重分类静默绕过hard gate。新的审计工程为：

`outputs/_work/p04_road_direct_generation/1885118/p04_v61_remaining13_audit_20260724T162500/p04_v61_remaining13_audit.qgz`

工程14层、EPSG:32650、invalid layer 0；红/橙/灰/紫分别表示hard conflict、部分证据未闭合、Patch资料不足与RealityChangeClue，绿色/蓝色表示forward/reverse原始Patch Road/Lane证据。

## 22. 三层目标合同与V63端到端复算

用户于2026-07-24确认三层合同：103条`BaselineCohort`不变；5条`patch_data_insufficient`和1条`reality_change`退出DirectBuild硬分母；其余97条必须直接高精构建。实现使用独立外部清单，不在代码中保存Case或Segment ID。清单被输入manifest记录，SHA256为`bd41191cadf794577827b931b5d9ab84fd87cbf472fa9a02f60ce5e90b6d284e`。

当前可审计候选：

`outputs/_work/p04_road_direct_generation/1885118/p04_segment_first_target_disposition_v63_1885118_20260724T170500`

| 指标 | V63 |
|---|---:|
| 全量Segment完整发布 | 330/330 |
| Road / Node / RoadNextRoad | 883 / 1146 / 2518 |
| built / retained Road | 459 / 424 |
| Baseline高精实现 | 90/103 |
| DirectBuild高精实现 | 90/97 |
| DirectBuild例外 | Patch资料不足5；RealityChange1 |
| 未完成硬目标 | hard conflict 4；partial evidence unresolved 3 |
| Access / Junction Movement | 831/831；371/371 |
| LaneTopo unresolved / 几何hard | 0 / 0 |
| independent QA | PASS，0 violation |
| P04专项回归 | 237 passed |
| 运行时间 | 384.990s |

V63正式Road、Node、RoadNextRoad与V62逐层归一化属性/WKB签名完全一致；三层合同和业务分类没有改变路网几何或拓扑。四条`conflict_retained`从正式`segment_build_units.segment_state`判定，三条部分证据未闭合来自`hp_partial/swsd_retained`且方向链未完成；没有按ID硬编码分类。

QGIS自动覆盖门禁读取459条built Road和6个DriveZone，CRS均为EPSG:32650，总长度29853.508m，其中29638.968m位于DriveZone内，覆盖率99.281357%，高于0.95总体门槛。真实QGIS 3.40.14回读47层工程：项目CRS EPSG:32650、invalid layer 0、必需层缺失0；`publish_disposition`五类renderer完整，未发布高精的13条Baseline均可见。人工目视对比确认V63与V61/V62几何一致，本轮只改善目标合同和审计表达，不宣称7条未解决Segment的骨架已有改善。

V63保持`terminal_status=failed`。未通过项为7条DirectBuild硬目标和1条既存`movement_anchor_not_internal`拒绝；前者必须通过专项冲突/部分证据策略继续收敛，后者需单独核对是否是可接受的显式排除或真实Movement缺口。在二者解决且97/97前，不执行finalizer。

## 20. 2026-07-24 V65目视审计与合同二次确认

用户确认`1885137_74295305`不再争用父Segment `1885118_1885134`的Patch Road/Lane证据，并将其新增重分类为`patch_data_insufficient`。`BaselineCohort`仍为103，例外更新为6条Patch资料不足和1条RealityChange，`DirectBuildRequired`更新为96。实现继续使用外部可哈希清单，不在代码中硬编码Case或Segment ID。

V65目视审计新增6个逐对象回归样本：

| 对象 | 已核实事实 | 本轮目标 |
|---|---|---|
| `621954521` | `swsd_retained_whole`与同Segment built Road在2m域内重叠约70.7% | 消除member级混合发布冗余，保持lineage可追溯 |
| `7895886509995543` | Movement split产生的26m短尾段；两端都在同一T07 accepted surface并共享mainnode | Segment Road在surface内结束；无PhysicalMovement支持则不发布面内尾段 |
| `7860057501137708` | 83.3%观测、16.7%补全；现有质量审计已报`completion_geometry_review` | 收敛路口端切线和平滑，并把Review传播到正式Road |
| `517389206` | 当前原样保留SWSD；Patch Road走廊覆盖约55.8% | 落实部分证据构建，不因非硬目标而整体保留 |
| `627387389` | 当前原样保留SWSD；Patch Road走廊覆盖约58.8% | 落实部分证据构建，不因非硬目标而整体保留 |
| SWSD `15640676` | 替代Road仅与SWSD提右约24%重合；两端距语义Junction约61m/25m却被判`hp_full` | 提右必须同时满足高精走廊及两端accepted surface连接，否则不得判完整直出 |

本轮最多执行10轮端到端迭代，并按“hard gate、96条DirectBuild、6个目视样本、几何平滑、全局零回归”的顺序选择最佳版本。QGIS最佳版本必须显式展示T07人工审核面、Patch `Intersection`、T03、T04和P04最终JunctionUnit。

## 24. Phase 18 V66–V70迭代与最佳版本选择

本轮没有按“最新run优先”选择结果。V66先修复6个目视样本的业务处置；V67验证retained冗余抑制，但因错误触发全量Node重编译而造成DirectBuild回归，明确否决；V68验证部分member发布，但覆盖了既有完整built carrier，明确否决；V69改为增量Node保持、部分接管不降级既有built，并新增切线surface portal。V70只以V69相同输入和参数独立重放，用于确定性验证。

| run | DirectBuild | Road（built/retained） | Node / RoadNextRoad | 几何hard | 结论 |
|---|---:|---:|---:|---:|---|
| V65 | 91/97 | 932（529/403） | 1209 / 2657 | 0 | 旧97分母起点；6个目视问题未闭合 |
| V66 | 88/96 | 928（522/406） | 1201 / 2643 | 0 | 修复尾段、提右误接管和Review传播；仍缺部分证据表达 |
| V67 | 79/96 | 927（522/405） | 1230 / 2556 | 0 | 否决：抑制后全量重编Node破坏既有端点状态 |
| V68 | 88/96 | 931（517/414） | 1202 / 2618 | 0 | 否决：部分接管使4个既有高精Segment降级 |
| V69 | 88/96 | 942（537/405） | 1224 / 2662 | 0 | **Phase 18当时最佳**：6个样本闭合或保守处置，既有DirectBuild零回归 |
| V70 | 88/96 | 942（537/405） | 1224 / 2662 | 0 | V69确定性重放；正式三图层与V69完全一致 |

V69逐对象结果为：

| 对象 | V69处置 | 审计结论 |
|---|---|---|
| `621954521` | 从正式Road移除；抑制审计`application_state=applied`，2m重叠率0.707296 | built主方向图已覆盖两端Junction；冗余retained不再重复发布 |
| `7895886509995543` | 不再发布 | 两端面外主走廊已有唯一贯穿片段；无独立PhysicalMovement支持的surface内兄弟尾段被抑制 |
| `7860057501137708` | 使用`tangent_surface_portal`进入路口面 | 最终最大转角2.549929°，几何hard为0；因completion Hausdorff 41.003608m继续带`completion_geometry_review`发布 |
| `517389206` | built `7086229862559704` + retained partial `7335346863643727` | built只含高精观测/受约束补全，剩余SWSD子串独立保留并共享transition Node |
| `627387389` | built `7856716279426638` + retained partial `7495684527528093` | 同上；没有把SWSD坐标拼入built Road |
| SWSD `15640676` | `swsd_retained_whole` | 当前高精候选未同时接入两个端点Junction，不再误判`hp_full`，提右功能结构未丢失 |

V69正式范围保持330/330 Segment、831/831 SWSD Access、LaneTopo unresolved 0、连续性失败0、SWSD功能拓扑失败0、独立QA 0 violation。DirectBuild为88/96，其中核心71/76、正式提前右转17/20；剩余8条仍是Gate P18的真实未完成项，不能用Review或部分Road绕过。因此V69继续保留`terminal_status=failed`，在Phase 18结束时只作为当时最佳人工审计候选，不执行finalizer。

QGIS工程共52层，项目和全部必需层由QGIS 3.40.14真实回读：项目CRS `EPSG:32650`、invalid layer 0、必需层缺失0。`03A_路口面审计`显式包含P04最终JunctionUnit、T07人工确认面、Patch原始`Intersection`、T03 accepted面和T04 accepted分歧合流面。独立PyQGIS overlay读取537条built Road，总长度33748.035777m，其中33690.531845m位于`DriveZone + accepted surface`正式道路域内，覆盖率99.829608%，通过逐层0.90/总体0.95门禁。

V70与V69输入签名均为`e4432ad33e91c5847567a3009cc0afe23c221cde1bf59d1d2abd521301aef432`。排除`run_id`后，正式图层归一化属性和WKB哈希分别为：Road `d8f1197ca85c716326533ad3ec2997ebe99e2cd2cdaba75f8fe81039dad6db5b`、Node `531e63862e6b164df7185fb56dd4008664cc9378225530c56964651b97b63cdc`、RoadNextRoad `f78985b9eb6f4b09ff377422ea0f5e09e1f2b38a7fd573730bf80100b4d33902`，三层全部一致。最佳版本因此保留V69，而不是用内容相同但缺少人工样本工件的V70覆盖。

## 25. Road端点严格入面与V75当前最佳

用户进一步确认：Road端点至少延伸进入路口面内部，物理选面优先T07人工accepted surface，其次T03/T04 accepted surface。该要求暴露出V69虽通过旧QA，但有59个声明交接的端点没有被原始accepted surface严格包含：其中58个来自关系半径内旁侧邻近Road被误作THROUGH切分，1个为普通Segment端点仍停在面外。`junction_endpoint_buffer`因此不能再作为发布验收容差。

| run | Road（built/retained） | DirectBuild | accepted端点面外 | LaneTopo unresolved | QA violation | 结论 |
|---|---:|---:|---:|---:|---:|---|
| V69 | 942（537/405） | 88/96 | 59 | 0 | 旧口径0 | 历史最佳；不满足新确认的严格入面合同 |
| V72 | 904（492/412） | 87/96 | 1 | 1 | 1 | 尚有`7982472440031242:start:1898312`停在面外 |
| V73 | 875（454/421） | 85/96 | 5 | 1 | 5 | 晚期SWSD mainnode lineage误把面外点标为accepted |
| V74 | 876（452/424） | 86/96 | 0 | 1 | 0 | 严格入面通过，但仍有1条LaneTopo未闭合 |
| V75 | 887（470/417） | 86/96 | 0 | 0 | 0 | **当前综合最佳** |

实现区分两类THROUGH证据：

1. 存在T07/T03/T04 accepted polygon时，Road必须实际穿入内缩面后才允许切分，最终Node必须被原始面严格`contains`；
2. 上游只有`swsd_retained`点，且该点是同一T01 Segment正式THROUGH access lineage时，可在不移动Road几何的前提下投影细分。该例外只恢复语义链，不产生accepted surface入面证明。

V75正式结果为887 Road、1146 Node、2328 RoadNextRoad，330/330 Segment、831/831 Access和371/371 Junction Movement保持完整。470条built Road的正式道路域覆盖率为99.463819%；最大最终转角58.477°，几何hard failure 0，独立QA 0 violation，LaneTopo所有记录均有明确mapped/excluded去向。QGIS工程53层、EPSG:32650、invalid layer 0，并显式包含T07人工面、Patch Intersection、T03、T04和P04最终JunctionUnit。

逐对象复核：

- `621954521`继续不发布，冗余抑制保持；
- `7895886509995543`继续不发布，不再恢复无独立PhysicalMovement支持的路口面内尾段；
- `7860057501137708`按高精证据构建并平滑进入路口面；
- `517389206`、`627387389`分别以built与互补retained partial表达，built不拼接SWSD坐标；
- SWSD `15640676`的提前右转功能以`swsd_retained`保留，当前高精候选没有绕过两端连接hard gate；
- 原未决LaneTopo `5417631180197788:5472654891680419`通过三条正式retained semantic carrier组成的受限RoadNextRoad链闭合，不再使用任意图可达。

V75相对V69少2条DirectBuild，不是高精能力倒退，而是撤销了旧版“旁侧接近即视为路口接入”的错误成功判定。剩余10条DirectBuild硬目标继续显式未完成；V75保持`terminal_status=failed`，只作为下一轮用户目视审计的当前最佳版本。

当前审计入口：

`outputs/_work/p04_road_direct_generation/1885118/p04_segment_first_junction_interior_v75_1885118_20260725T050000/p04_segment_first_comparison.qgz`
