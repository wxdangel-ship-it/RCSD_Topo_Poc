# SPEC：RCSD 场景路网拓扑 POC 需求说明（RCSD_Topo_Poc）

- 文档类型：需求规格说明（Specification）
- 项目名称：RCSD_Topo_Poc
- 版本：v0.1
- 状态：Draft
- 当前阶段：仓库骨架已建立，进入工程治理与已登记模块并行维护阶段
- 交付形态：外网 GitHub 仓库 + 内网执行 + 文本粘贴回传

---

## 1. 项目概述

`RCSD_Topo_Poc` 的目标是为 RCSD 场景下的路网拓扑相关能力建立一个可持续迭代的工程底座，并在此基础上承载正式业务模块。当前阶段在延续基础工程治理的同时，已经进入“工程治理 + 已登记模块并行维护”阶段：

- 仓库级骨架
- 文档治理与 source-of-truth 分层
- 共享文本回传协议
- 模块启动标准模板
- `src/`、`modules/`、`tests/`、`tools/` 的基础边界
- 当前已登记正式业务模块 `t01_data_preprocess`
- 当前已登记正式业务模块 `t02_junction_anchor`
- 当前已登记正式业务模块 `t03_virtual_junction_anchor`
- 当前已登记正式业务模块 `t04_divmerge_virtual_polygon`
- 当前已登记正式业务模块 `t05_junction_surface_fusion`
- 当前已登记正式业务模块 `t06_segment_fusion_precheck`
- 当前已登记正式业务模块 `t07_semantic_junction_anchor`
- 当前已登记正式业务模块 `t08_preprocess`
- 当前已登记 P01 成果模块 `p01_arm_build`
- 当前已纳入治理的工具集合模块 `t00_utility_toolbox`

当前原则是优先复用 `Highway_Topo_Poc` 中已经验证有效的仓库骨架、治理方式与协作约束，但不迁移任何高速场景业务模块实现。

---

## 2. 当前阶段目标

### 2.1 当前阶段必须完成

- 建立 RCSD 的 git 工作副本与基础工程骨架
- 固化项目级 `AGENTS.md`、`SPEC.md`、`docs/PROJECT_BRIEF.md`
- 建立项目级 `docs/architecture/*`、`docs/doc-governance/*`、`docs/repository-metadata/*`
- 建立 RCSD-neutral 的 `TEXT_QC_BUNDLE` 协议、粘贴性守卫与基础测试
- 建立 `modules/_template/`，用于后续任何新模块的标准启动
- 让已登记模块的文档面、实现入口与测试面保持一致
- 让 `t00_utility_toolbox` 维持工具集合模块 / 非业务生产模块边界
- 让 `t01_data_preprocess` 的 accepted baseline、官方入口与 freeze compare 口径保持一致
- 让 `t02_junction_anchor` 的项目级登记状态与仓库级入口事实保持一致
- 让 `t03_virtual_junction_anchor` 的 `Step1~Step7` 正式业务主链、冻结 `Step3 legal-space baseline` 与仓库级入口事实保持一致
- 让 `t03_virtual_junction_anchor` 的 internal full-input repo 级脚本交付面、批次根目录正式成果与 project-level 文档登记保持一致
- 让 `t04_divmerge_virtual_polygon` 的 Step1-7 模块文档、领域分层实现、Step4 审计输出与最终发布契约保持一致
- 让 `t05_junction_surface_fusion` 的 Phase 1 路口面融合发布、Phase 2 RCSD junctionization 与 SWSD-RCSD 关系生产、copy-on-write 输出和模块内 callable runner 保持一致
- 启动并扩展 `t06_segment_fusion_precheck`，完成 SWSD 可融合 Segment 识别、buffer-based RCSDSegment 构建的 Step1 / Step2 文档契约、模块内 callable runner 与最小测试闭环，并将 Step3 Segment 替换输出与语义路口关系重建纳入 T06 SpecKit 任务书
- 启动并扩展 `t07_semantic_junction_anchor`，完成 T02 Step1 / Step2 的语义路口级重构与独立 Step3 relation 补锚：只处理代表 node 的 `has_evd / is_anchor / anchor_reason`，输出 T07 版 surface/evidence handoff，不读取、生成或统计 Segment，并提供模块内 callable runner 与内网执行脚本
- 启动 `t08_preprocess`，完成 Tool1 基础矢量格式转换、Tool2 Road GPKG 预处理、Tool3 Nodes 类型聚合、Tool4 T 型路口错误修复、Tool5 复杂路口预处理、Tool6 Nodes 类型质检、Tool7 交通限制显性化与 Tool8 Laneinfo 箭头显性化的文档契约、模块内 callable runner、内网执行脚本与最小测试闭环
- 让 `p01_arm_build` 的 P01-A1 Arm 构建、P01-A2 Arm 配准与 P01-Final F-RCSD RoadNextRoad 还原 SpecKit 工件、模块文档契约、callable runner、review PNG/GPKG、summary/index 与 final audit 交付面保持一致

### 2.2 当前阶段明确不做

- 不无边界扩展更多未登记的 RCSD 业务模块
- 不迁移 `Highway_Topo_Poc` 的算法实现、专项脚本、专项审计工件
- 不冻结 RCSD 的业务指标、阈值、模块列表和执行链路

---

## 3. 范围与非目标

### 3.1 当前范围（包含）

- 仓库骨架初始化
- 项目级治理规则与文档入口
- 模块级启动模板
- 文本回传协议与其最小共享代码
- 基础测试与 smoke 模式
- `t00_utility_toolbox` 作为工具集合模块的治理与固定脚本入口
- 已登记正式模块 `t01_data_preprocess` 的 accepted baseline、official end-to-end 与 freeze compare
- T01 双向 Segment 构建正式启用 `kind_2 = 128` 的复杂分歧 / 合流审计语义：双向首轮 Step1 对 `kind_2 = 128` 复杂 mainnode 组不按 `mainnodeid` 聚合，而是使用各物理 `node.id` 建图，并以 raw `kind / grade` 作为该轮有效规则字段；在 S2 seed / terminate 判断中，复杂组内物理 node 的 raw `kind=8/16` 仅在该复杂组范围内作为分歧 / 合流端点规则参与匹配，不全局放宽普通节点；穿越结果必须通过 `kind_2_128_*` 输出字段可追溯，不改变 `through_node_ids` 的 degree-based 语义；Step2 将复杂组合优先作为局部分歧 / 合流 port corridor 判定，不在复杂路口内部做全局 simple-path 追溯；双向内部穿越在分歧 / 合流 / 低等级交叉路口启用 `Road.kind` 前两位道路等级续行优先，同等级时再用进入 / 退出夹角做二级消歧；局部 corridor 不适用或预算超限时必须输出可审计拒绝原因。
- 已登记正式模块 `t02_junction_anchor` 的项目级登记状态与仓库级入口索引
- 已登记正式模块 `t03_virtual_junction_anchor` 的 `Step1~Step7` 正式业务主链、冻结 `Step3 legal-space baseline`、repo 级 internal full-input shell/watch 交付面、批量审查产物与入口索引
- 已登记正式模块 `t04_divmerge_virtual_polygon` 的 Step1-7 正式文档面、模块化实现、Step4 review 输出与最终发布契约
- 已登记正式模块 `t05_junction_surface_fusion` 的 Phase 1 路口面融合发布、Phase 2 SWSD-RCSD relation 发布与 copy-on-write RCSD 网络输出
- 已登记正式模块 `t06_segment_fusion_precheck` 的 Step1 / Step2 Segment 融合前置识别、buffer-based RCSDSegment 构建、兼容可替换集合与错误分析，以及 Step3 基于 replaceable Segment 的 F-RCSD Road / Node 输出与语义路口关系重建
- 已登记正式模块 `t07_semantic_junction_anchor` 的语义路口级 Step1 / Step2 / Step3：`DriveZone / has_evd gate`、`RCSDIntersection / is_anchor / anchor_reason` 判定，以及基于 T05 `intersection_match_all.geojson` 的 relation 补锚，不处理 Segment
- 已登记正式模块 `t08_preprocess` 的 Tool1 基础矢量格式转换、Tool2 Road GPKG 预处理、Tool3 Nodes 类型聚合、Tool4 T 型路口错误修复、Tool5 复杂路口预处理、Tool6 Nodes 类型质检、Tool7 交通限制显性化与 Tool8 Laneinfo 箭头显性化；Tool1 支持 SHP / GeoJSON 转 GPKG 与 GPKG 转 GeoJSON，输出写回输入目录并追加 `_tool1`；Tool2 补充 `patch_id / kind` 并输出事件 Road；Tool3 补充 `kind_2 / grade_2` 并处理环岛 mainnode；Tool4 输出完整 Nodes/audit Nodes 并修复错误 T 型路口；Tool5 构建复杂分歧 / 合流路口并可处理错误 1 对多路口；Tool6 输出 `node_error_tool6.csv / node_error_tool6.gpkg` 作为人工质检输入，不改写 Nodes/Roads；Tool7 将 SW C 表 `CondType=1` 且 in/out Link 均存在的交通限制显性化为 `sw_restriction_tool7.gpkg`；Tool8 将同一 `LinkID + Lane_Dir` 的 SW Laneinfo `Arrow_Dir` 聚合为 Road 方向级 `sw_arrow_tool8.gpkg`；T08 GPKG 输出为 `EPSG:3857`
- T06 正式启用 final `nodes.gpkg.kind_2` 的 junc-node 豁免语义：仅当 `junc_nodes` 中节点的 `kind_2 in {1,4096,8192}` 时，该 junc node 不参与 Step1 的 `has_evd / is_anchor` eligibility 判定，并在 Step2 中不作为 T05 relation 必检映射节点；该语义不适用于 `pair_nodes`，不改变 `junc_nodes / semantic_node_set` 输出。
- T06 Step2 buffer-based RCSDSegment 构建策略：以 SWSD Segment 50m buffer 限定 RCSDRoad / RCSDNode 候选，RCSDRoad 使用 `intersects + overlap threshold` 而非纯 `within`，构图前按 `formway` bit7/128 识别提前右转 road；提前右转 road 若两端均与非提前右转候选 road 形成二度链接，或属于 required semantic nodes 之间的必要 corridor，则保留参与 Segment 构建，否则排除。required semantic nodes 为 `pair_nodes` relation 与非豁免 `junc_nodes` relation，`junc_kind2_exempt_nodes` 仅作为 optional allowed 审计节点；候选连通分量不能直接作为成果，必须先基于 required semantic nodes 构建 corridor 子图并在 pruning 阶段保护 required-to-required 必要通道，再执行 retained graph 审计；`swsd_directionality=single` 时必须由 SWSDRoad `snodeid / enodeid / direction` 推导 pair source/target，并按该方向构建覆盖全部 required semantic nodes 的 RCSD 有向 corridor，不得用 `pair_nodes` 顺序、`segmentid A_B` 顺序或反向可达兜底；`swsd_directionality=dual` 时 pruning 必须同时保护 pair 两端正反向 directed corridor，retained graph 必须 pair 两端双向可达，否则以 `rcsd_not_bidirectional_for_swsd_dual` 拒绝；额外 T05 mapped semantic nodes 必须按 seed-based pruning 判定为 `inner_nodes / out_nodes`，其中处于 required corridor 内部的 mapped semantic node 可作为 `inner_nodes` 保留审计，非 inner 且仍进入 retained graph 时必须以 `unexpected_mapped_semantic_nodes` 拒绝；final `nodes.gpkg.kind_2=64` 的环岛路口与 `kind_2=128` 的复杂路口启用特殊组门控：按 `pair_nodes + junc_nodes` 包含该语义路口统计关联 Segment，只有组内全部关联 Segment 均通过可替换判定时才允许进入 Step2 replaceable，否则组内所有原本可替换 Segment 均以 `special_junction_group_not_fully_replaceable` 移出 replaceable；Step2 输出 `t06_special_junction_group_audit.*` 记录特殊组、RCSD relation、组内 RCSDNode / 内部 RCSDRoad 与门控结果；Step2 不再执行旧 pair-to-pair BFS 路径搜索、主轴 / 长度趋势或唯一性筛选。
- T06 Step2 `swsd_directionality=dual` 的最小 corridor 构建不得用极短 required-to-required connector 替代完整方向 road；路径权重必须对明显短于 SWSD Segment 的 required semantic node 直连 edge 加惩罚，优先保留完整方向连通 road。RCSDRoad `formway & 1024 != 0` 表示调头口；当调头 road 两端均已属于 retained corridor node 时，必须作为内部调头 road 保留。
- T06 Step2 RCSD 建图正式使用 `rcsdnode_out.gpkg` 的 `id / mainnodeid / subnodeid` 做语义节点归一化：relation required nodes 与 RCSDRoad `snodeid / enodeid` 必须使用同一 canonical RCSD semantic node id 判定连通，避免 road 挂接到 subnode 时误判断连；全局 RCSD 语义路口组按有效 `mainnodeid` 聚合，组内所有 node 关联 road 均视为该语义路口的进入 / 退出道路，未映射到当前 Segment 的全局 RCSD 语义路口若进入候选图，必须参与 seed pruning，必要通道内保留为 `inner_nodes`，旁支归入 `out_nodes` 裁剪。
- T06 Step3 正式纳入模块范围：Step3 只消费 Step2 replaceable RCSDSegment，按 Segment 单元删除被替换 SWSDRoad，且 SWSDNode 仅删除被替换 SWSDRoad 的端点 Node，不删除整个 SWSD 语义路口组；Step3 引入 retained RCSDRoad / RCSDNode，并消费 Step2 `t06_special_junction_group_audit.*` 中 `gate_status=passed` 的特殊路口组内部 RCSDRoad / RCSDNode，输出 F-RCSD Road / Node，其中 `source=1` 表示 RCSD 数据、`source=2` 表示 SWSD 数据；所有 replaceable Segment 的 `pair_nodes + junc_nodes` 构成待重建语义路口集合 C，C 必须记录涉及 Node 与关联替换 Segment，若原 main node 被删除则重选 main node，并让 C 内 Node 继承原 main node 的 `kind / grade / kind_2 / grade_2 / closed_con`。Step3 当前提供模块内 callable runner 与 `scripts/t06_run_step3_segment_replacement.py` 独立运行脚本。
- 已登记 P01 成果模块 `p01_arm_build` 的 P01-A1 Arm 构建、P01-A2 Arm 配准、P01-Final F-RCSD RoadNextRoad 还原文档契约、模块内 callable runner、自动检查与人工目视审查产物

### 3.2 当前非目标（不包含）

- 未登记业务模块的无边界实现
- RCSD 模块级算法、参数与验收阈值
- 历史数据迁移、真实数据接入或专项回归链路
- 任何 Highway 模块正文、历史审计材料或专项评估脚本的整包平移

---

## 4. 关键约束与假设

### 4.1 复用方式约束

- 只复用骨架、治理规则、文档契约体系与协作方式。
- 业务正文、算法实现、专项脚本、专项术语不复用。
- 模块根目录不放 `SKILL.md`；标准 Skill 统一放 repo root `.agents/skills/`。

### 4.2 数据组织假设

当前输入数据组织方式先与 `Highway_Topo_Poc` 保持一致，作为初始兼容布局；这只是当前阶段的输入组织约束，不等于 RCSD 业务标准已经冻结。

初始兼容布局为：

```text
<PatchID>/
  PointCloud/
    *.laz
  Vector/
    LaneBoundary.geojson
    DivStripZone.geojson
    RCSDNode.geojson
    intersection_l.geojson
    RCSDRoad.geojson
  Tiles/
    <z>/<x>/<y>.<ext>
  Traj/
    <TrajID>/
      raw_dat_pose.geojson
```

### 4.3 工程与协作约束

- 项目内文档默认中文。
- 内网与外网默认执行环境均为 WSL。
- 项目工作目录默认使用 WSL 路径，例如 `/mnt/e/Work/RCSD_Topo_Poc`。
- 若上游输入或任务书给出 Windows 路径，应先转换为对应的 WSL 路径再执行。
- 文档在 `modules/<module>/`，实现代码在 `src/rcsd_topo_poc/modules/<module>/`。
- 运行输出写入 `outputs/_work/`，不把输出目录当工作区。

### 4.4 T03 internal full-input 交付约束

- `t03_virtual_junction_anchor` 当前除 `t03-rcsd-association` 官方 CLI 外，还存在 repo 级 internal full-input shell/watch 交付面：`scripts/t03_run_internal_full_input_8workers.sh` 与 `scripts/t03_watch_internal_full_input.sh`；它们属于 repo 级脚本入口，不构成新的 repo 官方 CLI。
- 历史 finalization shell wrapper 已退役，不再作为项目级入口或兼容入口登记。
- T03 internal full-input 当前正式批次根目录成果至少包括 `virtual_intersection_polygons.gpkg` 与 `nodes.gpkg`；前者聚合当前批次 case 级最终虚拟路口面，后者基于 full-input 输入的整层 `nodes.gpkg` 输出更新版结果。
- `nodes.gpkg` 的 `is_anchor=fail3` 只属于 T03 downstream output 语义：仅更新代表 node，`accepted => yes`，`rejected / runtime_failed => fail3`；该语义不回写输入原始 `nodes.gpkg`，也不反向修改上游输入契约。
- `t03_watch_internal_full_input.sh` 当前采用 T03 formal-first 监控口径：默认显示 `total / completed / running / pending / success / failed`，其中 `success = accepted`、`failed = rejected + runtime_failed`，并显式表达是否已进入 `case execution` 阶段；视觉层统计仅在显式调试场景下读取 review-only 工件。

### 4.5 T04 Step1-7 正式范围约束

- `t04_divmerge_virtual_polygon` 当前正式范围扩展到 `Step1-7`：
  - `Step1 = candidate admission`
  - `Step2 = high-recall local context`
  - `Step3 = topology skeleton`
  - `Step4 = fact event interpretation + review outputs`
  - `Step5 = geometric support domain`
  - `Step6 = polygon assembly`
  - `Step7 = final acceptance + publishing`
- T04 当前正式输入同时覆盖包含 `divstripzone.gpkg` 的 case-package 与 internal full-input；full-input 通过 repo 级 shell/watch 包装进入 T04 私有 runner，不新增 repo 官方 CLI 子命令。
- T04 Step4 当前必须输出 case overview、event-unit review PNG、flat mirror、review index 与 review summary，用于人工审计；这些结果不等同最终发布层。
- T04 当前已进入 `Step5-7` 正式研发实现阶段；`Step1-4` 保持既有稳定执行面，`Step5-7` 按冻结需求分轮落地。
- T04 `Step5-7` 正式研发默认遵循 SpecKit，任务书必须覆盖：
  - `Product`
  - `Architecture`
  - `Development`
  - `Testing`
  - `QA`
- T04 可以参考 `t03_virtual_junction_anchor` 的实现逻辑、审计风格、产物组织与输出组织方式，但运行时不得直接 import / 调用 / 拷贝 T03 模块代码；正式执行逻辑必须保留在 T04 私有实现内。
- T04 当前不新增 repo 官方 CLI；internal full-input shell/watch 交付面为 repo 级脚本入口，执行逻辑保留在 T04 私有实现内。
- T04 在使用 RCSDNode / RCSDRoad 参与 RCSD 语义路口召回时，RCSD 与 SWSD 采用同一基础语义路口口径：具有 `3` 条及以上压缩语义道路进入或退出的路口，才称为语义路口；两个语义路口之间的连续道路链视为一条路口间道路。`RCSDNode.mainnodeid` 只表达候选路口的单节点 / 多节点组织关系：非 `0` / 非空 `mainnodeid` 表示多节点候选组，`0` / 空值表示单节点候选组；该字段不单独决定候选是否构成 RCSD 语义路口。一个 SWSD event unit、复杂路口内的单个 unit、或一个简单二分歧 / 合流，最多只能发布一个对应的 RCSD 对齐对象；若局部窗口内命中多个 RCSD 语义路口或候选对象，必须先按当前 SWSD section / Reference Point / 进出方向角色完整性 / 距离与角度趋势消歧，非选中对象只能作为上下文或 trace 审计信息，并按 Step4 唯一对齐结果参与负向掩膜。

### 4.6 P01 Arm 构建、配准与 RoadNextRoad 还原约束

- `p01_arm_build` 承载 P01-A1 / P01-A2 / P01-Final 成果链路，目录结构与 T0X 模块一致。
- A1 在 SWSD / RCSD / F-RCSD 三套数据中独立构建 Arm、特殊转向、ArmMovement 与 corrected trunk。
- A2 读取 A1 run root，以 F-RCSD FinalArm 为承载核心构建跨三源 LogicalArmGroup。
- P01-Final 基于 SWSD / RCSD 源侧 ArmMovement 通行规则抽象、F-RCSD 道路角色投影与 ArmSourceProfile 审计生成最终 `frcsd_road_next_road.geojson`；F-RCSD Arm 可混源，`Source` 只在 Road 级解释，精确源 Road 映射仅作为审计 / 置信增强证据，不作为生成前提。
- P01-Final 中“全通”表示某类进入道路通向目标 Arm 的全部退出 Road；主干道路和平行支路只覆盖部分目标退出 Road 时必须进入 `data_error_partial_target_coverage` / 人工复核，不得作为正常 partial 规则投影。advance-left 与 uturn 的主干 / 左转接收道路范围是明确特例。
- P01 输入为六类 Node/Road 路径、可选 RoadNextRoad 路径与一个或多个三段式 `--junction-group <swsd>,<rcsd>,<frcsd>`。
- P01 语义路口按 `mainnodeid` 聚合；`mainnodeid = null / 空字符串 / 0` 视为无有效值并退化为单节点语义路口。
- 特殊转向使用 `formway` bit 运算：bit7 表达提前右转，bit8 表达提前左转；字段缺失时不得通过几何形态反推。
- P01 禁止使用 `grade / grade_2` 作为主规则；`kind` 可参与 T 型判断但不能单独裁决。
- A1 `InitialArm` 保留原始 trace 终端归并事实；`FinalArm` 默认等同 InitialArm，但当 LocalArmCandidate 完整覆盖碎片化 InitialArm 时可采用局部趋势兜底聚合。
- RoadNextRoad 在 A1 ArmMovement 阶段只表达 allowed evidence，缺失不等于禁止；在 P01-Final 生成阶段，源侧缺失则不生成最终 F-RCSD RoadNextRoad。
- RoadNextRoad `turnType / turntype` 不得用于 `movement_type` 判定。
- A2 禁止仅凭几何最近输出 high confidence 配准；禁止自动拆分 over-merged Arm；禁止静默丢弃 FRCSD FinalArm 或 source_extra Arm。
- 仓库不提供 P01 repo 官方 CLI、`scripts/` 常驻命令、模块 `__main__.py` 或模块 `run.py`；模块内 callable runner 用于开发验收与后续正式入口准备。

### 4.7 T07 语义路口级 Step1 / Step2 / Step3 约束

- `t07_semantic_junction_anchor` 承载 T02 Step1 / Step2 的语义路口级重构，并提供独立 Step3 relation 补锚，只处理代表 node 的 `has_evd / is_anchor / anchor_reason`。
- T07 Step1 / Step2 读取 `nodes / DriveZone / RCSDIntersection`；Step2 输出 `t07_rcsdintersection_anchor_surface.gpkg` 与 `t07_swsd_rcsd_relation_evidence.csv/json`；Step3 读取 Step2 后 `nodes`、T05 `intersection_match_all.geojson` 与输入 `RCSDNode`，输出复制 Step2 surface 的 `t07_rcsdintersection_anchor_surface.gpkg`，并输出合并 Step2 evidence 与 Step3 成功补锚成果、记录 Step2 / Step3 锚定数量的 `t07_swsd_rcsd_relation_evidence.csv/json`。T07 不读取、生成或统计 `segment.gpkg`，不解析 `pair_nodes / junc_nodes`，不输出 `segment.has_evd`、`summary_by_s_grade` 或 `anchor_summary_by_s_grade`。
- T07 的类型判断字段固定为 `kind_2`；不兼容 `Kind_2`。
- T07 Step1 仅处理代表 node `kind_2 in {4,8,16,64,128,2048}` 的语义路口；其它 `kind_2` 的代表 node 写或保持 `has_evd = NULL`，且不进入 Step2，`is_anchor / anchor_reason` 均为 `NULL`。
- T07 Step2 仅处理代表 node `has_evd = yes` 的语义路口；代表 node `kind_2 = 64 / 128` 的语义路口直接写 `is_anchor = no / anchor_reason = NULL` 且不纳入冲突规则；代表 node `kind_2 = 2048` 仅当组内所有 node 均命中同一个且唯一的 `RCSDIntersection` 时写 `is_anchor = yes / anchor_reason = t`，否则写 `is_anchor = no / anchor_reason = NULL`；其它处理范围内类型保留 T02 Step2 的 `yes / no / fail1 / fail2` 与 `fail2 > fail1` 语义。
- T07 Step3 仅处理代表 node `kind_2 in {4,8,16,2048}`、`has_evd = yes` 且 `is_anchor = no` 的语义路口；只有 T05 `intersection_match_all.geojson` 中存在 `target_id = SWSD 语义路口 id`、`status = 0`、`base_id != 0` 的成功 relation，且 `base_id` 在输入 `RCSDNode.id/mainnodeid` 中存在时，才输出该 relation 到 `intersection_match_tool7.geojson`、把 SWSD 代表 node 写为 `is_anchor = yes / anchor_reason = NULL`，并将成功补锚结果合并进 Step3 `t07_swsd_rcsd_relation_evidence.csv/json`；Step3 同步输出复制 Step2 surface 的 `t07_rcsdintersection_anchor_surface.gpkg`。
- T07 Step3 中 `kind_2 = 64 / 128` 不进入补锚规则，后续由专项规则处理。
- T07 当前提供模块内 callable runner、`scripts/t07_run_semantic_junction_anchor_innernet.sh` Step1 / Step2 内网执行包装，以及 `scripts/t07_run_step3_intersection_match_innernet.sh` Step3 独立内网执行包装；不新增 repo 官方 CLI、`tools/`、`Makefile` 目标、模块 `run.py` 或模块 `__main__.py`。

---

## 5. 协作与治理方式

- 项目采用 spec-driven / SpecKit 风格工作流。
- 项目级真相写入 `SPEC.md`、`docs/PROJECT_BRIEF.md`、`docs/architecture/*`。
- 模块级真相写入 `modules/<module>/architecture/*` 与 `INTERFACE_CONTRACT.md`。
- `AGENTS.md` 只承载 durable guidance。
- `review-summary.md` 只承担治理摘要，不替代源事实。
- 历史资料进入 `history/` 或仓库级归档位置，不占据主阅读路径。

---

## 6. 当前仓库交付基线

当前仓库初始化后，至少包含：

- 项目级治理文档与架构文档
- `src/rcsd_topo_poc/` 包骨架
- RCSD-neutral 的文本回传协议与粘贴性守卫
- `tests/` 中对应的最小协议测试与 smoke
- `modules/_template/` 新模块启动模板

---

## 7. 模块启动标准

后续任何新模块启动时，Day-0 最少应创建：

- `AGENTS.md`
- `INTERFACE_CONTRACT.md`
- `architecture/01-introduction-and-goals.md`
- `architecture/03-context-and-scope.md`
- `architecture/04-solution-strategy.md`

建议在模块进入稳定执行前尽早补齐：

- `README.md`
- `architecture/02-constraints.md`
- `architecture/05-building-block-view.md`
- `architecture/09-quality-requirements.md`
- `architecture/11-risks-and-technical-debt.md`
- `architecture/12-glossary.md`

按模块成熟度和治理需要补充：

- `review-summary.md`
- `history/`
- `scripts/`

说明：

- repo root `.agents/skills/<skill-name>/SKILL.md` 属于仓库级可复用流程资产，不属于模块根 Day-0 文档集。
- 模块默认应复用 repo-level CLI 或 root `scripts/` 入口；若要新增模块局部执行入口，必须先满足 repo root `AGENTS.md` 的入口治理规则并登记。

---

## 8. 测试与可复现要求

- 默认测试框架为 `pytest`。
- 允许定义 `smoke` marker，约束其只写 `outputs/_work/`。
- 共享协议与粘贴性守卫必须有可执行测试。
- 当前阶段要求已登记正式模块的 stage1 / stage2 / stage3 baseline 与必要支撑入口具备最小单测与 smoke。

---

## 9. 当前结论

- RCSD 当前已从纯骨架阶段进入“工程治理 + 正式业务模块并行”阶段。
- 当前已登记正式业务模块：`t01_data_preprocess`、`t02_junction_anchor`、`t03_virtual_junction_anchor`、`t04_divmerge_virtual_polygon`、`t05_junction_surface_fusion`、`t06_segment_fusion_precheck`、`t07_semantic_junction_anchor`、`t08_preprocess`；当前已登记 P01 成果模块：`p01_arm_build`。
- 当前已纳入治理的工具集合模块：`t00_utility_toolbox`，其定位为非业务生产模块。
- `t01_data_preprocess` 当前已具备 official end-to-end、Step6 聚合与 freeze compare 的最小闭环。
- T01 双向 Segment 构建中，`kind_2 = 128` 表达复杂分歧 / 合流路口组合审计语义：双向首轮 Step1 拆回复杂 mainnode 组内物理 node，并以 raw `kind / grade` 恢复独立分歧 / 合流规则判断；其中 raw `kind=8/16` 仅对复杂组内物理 node 作为 S2 分歧 / 合流端点匹配补充，不改变普通节点规则；candidate / validation 级 `kind_2_128_*` 统计用于定位复杂路口对候选规模、拒绝原因与性能的影响；Step1 / Step2 内部穿越启用 `Road.kind` 前两位道路等级续行优先，同等级出口再按进入 / 退出夹角消歧；Step2 对复杂热点优先采用 `kind2_128_local_corridor` 局部 port 判定，避免在复杂路口内部全局追溯；兜底搜索预算耗尽时不得静默跳过，必须输出 `trunk_search_budget_exceeded`。
- `t02_junction_anchor` 当前仍是 Active 正式业务模块；其模块正文可在独立轮次中维护，但项目级登记与仓库级入口必须保持一致。
- `t03_virtual_junction_anchor` 当前作为 Active 正式业务模块；当前正式范围按 `Step1~Step7` 业务主链表达（仅 `center_junction / single_sided_t_mouth`），默认正式全量 `58` case 的业务正确性基线已满足人工目视审计，少量 accepted case 的几何形状优化保留为长期迭代方向。
- `t03_virtual_junction_anchor` 当前保留 `t03-rcsd-association` 官方 CLI；其业务含义对应 `Step4 + Step5` 关联阶段。其内网批量执行与监控当前通过 repo 级 `t03_run_internal_full_input_8workers.sh` / `t03_watch_internal_full_input.sh` 交付，历史 finalization shell wrapper 已退役。
- `t03_virtual_junction_anchor` 的 internal full-input 当前正式批次根目录成果包括 `virtual_intersection_polygons.gpkg` 与 `nodes.gpkg`；其中 `nodes.gpkg` 仅更新代表 node，`fail3` 只代表 T03 downstream output 语义。
- `t04_divmerge_virtual_polygon` 当前作为 Active 正式业务模块进入治理；正式范围已扩展到 `Step1-7`，其中 `Step1-4` 维持既有稳定执行面，`Step5-7` 进入正式研发实现阶段；internal full-input 通过 repo 级脚本包装 + T04 私有 runner 交付，不新增 repo 官方 CLI。
- `p01_arm_build` 当前作为 Active P01 成果模块进入治理；正式范围覆盖 P01-A1 Arm 构建、P01-A2 Arm 配准与 P01-Final F-RCSD RoadNextRoad 还原，不包含 P01-A3 正式跨源 Movement 空间、禁行迁移、F-RCSD 通行能力最终裁决或 P01-B。
- `t05_junction_surface_fusion` 当前作为 Active 正式业务模块进入治理；正式范围覆盖 Phase 1 多源路口面融合发布与 Phase 2 RCSD junctionization / SWSD-RCSD relation 生产。Phase 2 输出 `intersection_match_all.geojson`、`rcsdroad_out.gpkg`、`rcsdnode_out.gpkg` 与审计汇总；其 RCSDRoad / RCSDNode 变化只通过 copy-on-write 输出表达，不原地修改输入。
- `t06_segment_fusion_precheck` 当前作为 Active 正式业务模块启动；正式范围覆盖 Step1 SWSD 可融合 Segment 识别、Step2 buffer-based RCSDSegment 构建、兼容可替换集合和错误分析，并已扩展到 Step3 replaceable Segment 替换输出与语义路口关系重建；Step3 采用 copy-on-write，不修改 T01 / T05 / Step2 输入成果；当前提供模块内 callable runner 与 `scripts/t06_run_innernet_precheck.py` 内网运行包装，不新增 repo 官方 CLI。
- `t07_semantic_junction_anchor` 当前作为 Active 正式业务模块启动；正式范围覆盖 T02 Step1 / Step2 的语义路口级重构与独立 Step3 relation 补锚，输出代表 node 的 `has_evd / is_anchor / anchor_reason`、Step2 / Step3 `t07_rcsdintersection_anchor_surface.gpkg`、Step2 / Step3 `t07_swsd_rcsd_relation_evidence.csv/json` 与 Step3 `intersection_match_tool7.geojson`，Step1 / Step2 消费 `nodes / DriveZone / RCSDIntersection`，Step3 消费 Step2 后 `nodes`、T05 `intersection_match_all.geojson` 与输入 `RCSDNode`，不处理 Segment；当前提供模块内 callable runner、`scripts/t07_run_semantic_junction_anchor_innernet.sh` 与 `scripts/t07_run_step3_intersection_match_innernet.sh` 内网运行包装，不新增 repo 官方 CLI。
- `t08_preprocess` 当前作为 Active 正式预处理模块启动；当前覆盖 Tool1 基础矢量格式转换、Tool2 Road GPKG 预处理、Tool3 Nodes 类型聚合、Tool4 T 型路口错误修复、Tool5 复杂路口预处理、Tool6 Nodes 类型质检、Tool7 交通限制显性化与 Tool8 Laneinfo 箭头显性化，Tool1 支持 SHP / GeoJSON 转 GPKG 与 GPKG 转 GeoJSON，输出写回输入目录并追加 `_tool1`，Tool2 只消费 GPKG 输入、补充 `patch_id / kind` 并输出 `EPSG:3857` GPKG，Tool2 / Tool3 / Tool4 / Tool5 / Tool6 / Tool7 / Tool8 均输出阶段进度与性能 summary，Tool3 只消费 GPKG Nodes/Roads 输入、补充 `kind_2 / grade_2` 并处理环岛 mainnode，Tool4 只消费 GPKG Nodes/Roads 输入、输出完整 Nodes/audit Nodes 并修复错误 T 型路口，Tool5 构建复杂分歧 / 合流路口并可基于 `node_error_2 / RCSDIntersection` 处理错误 1 对多路口，Tool6 只消费 GPKG Nodes/Roads 输入、输出 `node_error_tool6.csv / node_error_tool6.gpkg` 作为人工质检输入，CSV 最后一列 `是否修复` 默认 `1`，不改写输入 Nodes/Roads，Tool7 消费 SW C 表 / SW Node / SW Road GPKG，输出 `sw_restriction_tool7.gpkg`，Tool8 消费 SW Laneinfo / SW Node / SW Road GPKG，输出 `sw_arrow_tool8.gpkg`；当前提供模块内 callable runner 与 `scripts/t08_tool1_vector_convert.py`、`scripts/t08_tool2_road_preprocess.py`、`scripts/t08_tool3_nodes_type_aggregation.py`、`scripts/t08_tool4_junction_type_repair.py`、`scripts/t08_tool5_complex_junction_preprocess.py`、`scripts/t08_tool6_nodes_type_qc.py`、`scripts/t08_tool7_traffic_restriction.py`、`scripts/t08_tool8_lane_arrow.py` 内网脚本。
- T06 中 final `nodes.gpkg.kind_2 in {1,4096,8192}` 只作为 `junc_nodes` 的豁免字段：命中节点不参与 Step1 `has_evd / is_anchor` 判定，也不进入 Step2 T05 relation 必检映射集合；`pair_nodes` 仍必须按原规则判定并校验 T05 relation。
- 未来新增模块必须先按模板建文档契约，再进入实现阶段。
