# T01 - INTERFACE_CONTRACT

## 1. 文档定位
- 状态：`accepted baseline contract / revised alignment`
- 本文件固化稳定输入、稳定输出、官方入口、关键参数类别、continuation 约束与验收口径。
- 模块需求以 `SPEC.md` 为准；架构设计与实现策略以 `architecture/01-introduction-and-goals.md` 至 `architecture/06-risks-and-technical-debt.md` 为准。
- 具体阶段语义、节点重分类规则、gate / barrier / arbitration 的已确认 baseline 补充见 `architecture/accepted-baseline.md`。
- `README.md` 只承担操作者入口与索引，不替代本文件、`SPEC.md` 与架构文档。
- repo root `scripts/t01_*.sh` 属于环境 / 交付辅助，不作为模块 steady-state 契约主表面。

## 2. 官方输入契约
- 官方输入：
  - `nodes.gpkg`
  - `roads.gpkg`
- 兼容读取：
  - 同名 `GeoPackage(.gpkg)` 优先
  - 历史 `.gpkt` 仅兼容读取
  - `GeoJSON(.geojson/.json)` 与 `Shapefile(.shp)` 继续兼容
- node 输入约束：
  - `closed_con in {2,3}`
- road 输入约束：
  - 双向 `Step1-Step5C` 构段继续使用 `road_kind != 1`
  - `formway != 128`
  - `Step5` 后单向补段允许 `road_kind = 1` 进入候选；该字段在 SWSD 中代表封闭式道路，多数场景为高速 / 高速相关道路

## 2.1 官方 runner / 诊断契约
- 运行前先在 repo root 执行：
  - `make env-sync`
  - `make doctor`
- 官方 end-to-end 入口：
  - `.venv/bin/python -m rcsd_topo_poc t01-run-skill-v1`
- 官方 continuation 入口：
  - `.venv/bin/python -m rcsd_topo_poc t01-continue-oneway-segment`
- 官方 freeze compare 入口：
  - `.venv/bin/python -m rcsd_topo_poc t01-compare-freeze`
- 以上入口均属于 repo-level CLI 子命令，官方登记以 repo root `docs/repository-metadata/entrypoint-registry.md` 为准
- repo root `scripts/t01_run_full_data_skill_v1.sh`、`scripts/t01_run_full_data.sh`、`scripts/t01_pull_from_internal_github.sh`、`scripts/t01_pull_main_from_internal_github.sh` 只作为环境与交付辅助脚本，不替代本节官方入口定义
- debug 默认值：
  - `t01-run-skill-v1`、`t01-continue-oneway-segment` 与 `t01-step6-segment-aggregation-poc` 默认 `debug=false`
  - `t01-step1-pair-poc / t01-step2-segment-poc / t01-s2-refresh-node-road / t01-step4-residual-graph / t01-step5-staged-residual-graph` 默认 `debug=true`
- GPKG 输出兼容性：T01 快速 GeoPackage 写出路径必须写入 `gpkg_ogr_contents` 与增删触发器，使 QGIS 旧版 OGR provider filter 后的图层要素计数与实际过滤结果一致。
- `debug` 只允许影响：
  - 中间 stage 目录
  - 审计图层
  - progress / perf 诊断产物
- `debug` 不得改变最终业务结果：
  - `validated_pairs_skill_v1.csv`
  - `segment_body_membership_skill_v1.csv`
  - `trunk_membership_skill_v1.csv`
  - `segment.gpkg`
- `t01-run-skill-v1` 的稳定诊断产物：
  - `t01_skill_v1_progress.json`
  - `t01_skill_v1_perf.json`
  - `t01_skill_v1_perf.md`
  - `t01_skill_v1_perf_markers.jsonl`
  - `distance_gate_scope_check.json`
  - `all_stage_segment_roads/`
  - `t01_skill_v1_evidence_bundle.txt`
  - `t01_skill_v1_evidence_bundle_size_report.json`
- `trace_validation_pair_ids`：
  - 仅作为 Step2 progress / perf trace 透传参数
  - 不是业务输入
  - 不得改变 candidate search、validated_pairs、segment_body、endpoint pool 与最终 `segment.gpkg` 语义
- `stop_after_step2_validation_pair_index`：
  - 仅用于 Skill v1 全链路诊断截停
  - 不改变已执行阶段的业务语义

- `t01-continue-oneway-segment`：
  - `--continue-from-dir` 允许三类输入：
    - 之前完整 `t01-run-skill-v1` out_root，且包含 `debug/step5/`
    - 直接的 `debug/` 目录，且同时含 `step2/step4/step5/`
    - 直接的 `Step5` refreshed 输出目录，且包含 Step5 marker 与 `nodes.gpkg/roads.gpkg`
  - continuation 模式只执行 `oneway + Step6`
  - 不回退重跑 `Step1-Step5`
  - `--out-root` 必须是新的结果目录，不得与 source dir 或解析出的 `Step5` stage dir 重叠
  - `--compare-freeze-dir` 仅在输入是完整 `Skill v1` out_root 或完整 `debug/` 目录且同时含 `step2/step4/step5/` 时允许使用

- 文本证据包 helper：
  - 对齐 P01 的单文件文本证据包形式：`zip` 压缩 payload、`base85` 文本编码、payload checksum 与 begin / end marker
  - helper 不登记为正式 CLI，可通过 `.venv/bin/python -c` 调用 `rcsd_topo_poc.modules.t01_data_preprocess.text_bundle`
  - 默认 compact 包只覆盖 Skill v1 轻量证据、关键 summary / CSV / hash 与审计 JSON，不默认携带大体量 GPKG
  - `--include-vectors` 才纳入最终向量 GPKG，`--include-stage-segment-roads` 才纳入 `all_stage_segment_roads/`
  - 解包必须校验 payload checksum 与包内文件 checksum，并拒绝绝对路径或包含 `..` 的不安全包内路径

## 3. Working Layers

### 3.1 Working Nodes
- 必备字段：
  - `id`
  - `mainnodeid`
  - `closed_con`
  - `grade`
  - `kind`
  - `grade_2`
  - `kind_2`
- 初始化：
  - `grade_2 = grade`
  - `kind_2 = kind`
- 后续业务判断统一使用：
  - `grade_2`
  - `kind_2`
- raw `grade / kind` 不得再进入后续业务强规则。

### 3.2 Working Roads
- 必备字段：
  - `id`
  - `snodeid`
  - `enodeid`
  - `direction`
  - `formway`
  - `road_kind`
  - `segmentid`
  - `sgrade`
- 初始化：
  - `segmentid = null`
  - `sgrade = null`
- 已启用的原始业务字段：
  - `kind`：道路种别；单个 token 使用 `XXXX` 表达，前两位为道路等级、后两位为道路类型，多个 token 用 `|` 分隔。
  - T01 双向构段仅使用 `kind` 的前两位道路等级做局部续行优先；字段缺失、不可解析或无同等级候选时，不通过几何形态反推道路等级。

## 4. 预处理契约

### 4.1 环岛预处理
- working bootstrap 的执行顺序为：
  - working field 初始化
  - roundabout preprocessing
  - bootstrap node retyping
  - 再进入 Step1
- 环岛 `mainnode`：
  - `grade_2 = 1`
  - `kind_2 = 64`
- 环岛 member node：
  - `grade_2 = 0`
  - `kind_2 = 0`
- 该组所有 node 的 `mainnodeid` 统一写为环岛 `mainnode`。
- 环岛 `mainnode` 后续不参与 generic node 刷新。

### 4.2 bootstrap node retyping
- 仅允许修改 working node 的：
  - `grade_2`
  - `kind_2`
- 不修改原始：
  - `grade`
  - `kind`
- 当前 bootstrap 只支持极窄的 strict-T 纠错：
  - 当前节点为 `grade_2 = 1, kind_2 = 4`
  - `total_neighbor_family_count = 3`
  - `segment_neighbor_family_count = 0`
  - `residual_neighbor_family_count = 3`
  - 仅存在 `1` 个 through family，且其代表节点为 `grade_2 = 1, kind_2 = 4`
  - 两个 side family 都必须是单 road family，且满足：
    - 一个 side family 的代表节点为 `grade_2 = 1, kind_2 = 4`
    - 一个 side family 的代表节点为 `kind_2 = 2048` 且 `grade_2 >= 2`
- 命中时才允许：
  - `grade_2 = 2`
  - `kind_2 = 2048`
- 当前 bootstrap 不做：
  - `1/4 -> 2/4`
  - `1/4 -> 3/2048`

### 4.3 右转专用道契约
- `formway = 128` 的 road 不得进入 Step1-Step5 的 Segment 构建图。
- 去除右转专用道后若节点不再构成真实路口，则该节点不得作为：
  - `seed / terminate`
  - `through`
  - `boundary / endpoint pool`
  - Step6 的有效外向语义路口

## 5. Step1-Step5C 阶段契约

### 5.1 全局共享约束
- node：
  - `closed_con in {2,3}`
- road：
  - `road_kind != 1`
  - `formway != 128`
- gates：
  - `MAX_DUAL_CARRIAGEWAY_SEPARATION_M = 50.0`
  - `MAX_SIDE_ACCESS_DISTANCE_M = 50.0`
- 双向主干 road-body 间距有效门限为 `max(MAX_DUAL_CARRIAGEWAY_SEPARATION_M, pair 两端语义路口内部成员节点最大距离)`。
- 测距前剔除 forward / reverse path 两端 `5m` 短挂接区，避免 T 型路口端点八字挂接误触发主干超距；剔除后仍超过有效门限时返回 `dual_carriageway_separation_exceeded`。

### 5.2 T 型路口竖向阻断
- 仅对应 `kind_2 = 2048`
- 不对应 `kind_2 = 4`
- 在 `Step2 / Step4 / Step5A / Step5B / Step5C` 中：
  - 若该 T 型路口不是当前 segment 的起点 / 终点，则禁止内部竖向追溯
  - 横方向允许继续追溯

### 5.3 历史高等级边界
- 更低等级构段不得跨越更高等级轮次中已成立的段边界语义路口。
- 当前轮 `terminate / hard-stop` 必须并入历史高等级边界 `mainnode`。
- 历史高等级边界优先来自上一轮 `validated_pairs.csv` 的已成立 Segment 端点；仅在旧产物缺失 validated 文件时回退读取 `endpoint_pool.csv`。
- 上一轮未成段的潜在 `seed / terminate` 不作为当前轮 hard-stop，可按当前轮输入规则参与搜索，并在 `continue_after_terminal_candidate` 下继续追溯。

### 5.4 分歧 / 合流局部续行
- 作用阶段：
  - Step1 pair 搜索的内部节点扩张
  - Step2 trunk simple-path 枚举的内部节点扩张
- 当某个内部语义路口存在多个可继续追溯出口时，先按进入 road 与退出 road 的 `kind` 前两位道路等级做局部过滤；若存在同等级退出 road，则优先保留同等级出口。
- 在保留出口的道路等级均与进入 road 一致时，再按进入方向与退出方向夹角选择更顺直的出口；夹角在最优值 `15°` 容差内的出口可同时保留，避免把近似并行分歧误删。
- 该规则不改变 `seed / terminate / through_node_ids` 的定义，只限制内部穿越时的续行方向。
- 该规则不得使用缺失 `kind` 的几何反推道路等级；方向角只用于同等级候选的二级消歧。

### 5.5 Step1
- 输入：
  - 首轮 `grade_2 in {1}`
  - `kind_2 in {4,64}`
  - `closed_con in {2,3}`
- `kind_2 = 128` 在双向首轮表达复杂分歧 / 合流 mainnode 组；Step1 对该组不使用 `mainnodeid` 聚合，改用各物理 `node.id` 建图。
- 双向首轮中，属于 `kind_2 = 128` 复杂 mainnode 组的物理 node 使用 raw `kind / grade` 作为有效 `kind_2 / grade_2` 规则字段，以恢复组内独立分歧 / 合流语义；S2 seed / terminate 对该复杂组内物理 node 额外接受 raw `kind=8/16` 作为分歧 / 合流端点，不改变普通节点的 `kind_bits_any=[2,6]` 规则。
- 复杂 mainnode 组的穿越必须写入 `pair_candidates.csv / pair_table.csv / pair_summary.json` 的 `kind_2_128_*` 审计字段。
- `kind_2 = 128` 穿越审计不得回写或扩展 `through_node_ids` 语义；`through_node_ids` 继续只表达 degree-based through 规则。
- 输出：
  **- `pair_candidates`**

### 5.6 Step2
- 输入 / terminate 规则与首轮 Step1 一致。
- 合法 `seed / terminate` 节点不得被 `through_node` 吞掉。
- `kind_2 = 128` 复杂 mainnode 组已在 Step1 拆回物理 node 级参与 candidate search；Step2 沿用 Step1 输出的物理 node 级 pair 支持路径，不扩展 `through_node_ids` 语义。
- Step2 对复杂 `kind_2 = 128` 组合优先采用 `kind2_128_local_corridor` 局部 port 判定：只基于 Step1 已确认的进入 / 退出支持路径及其局部门禁判断，不在复杂路口内部展开全局 simple-path 追溯。
- 当局部 corridor 本身未形成可终止的复杂组合，仍允许回退到既有精确判定；当局部 corridor 命中可终止复杂组合且门禁失败时，该 pair 以明确 reject reason 进入 rejected 输出，不再回退到复杂路口内部全局追溯。
- trunk search budget 保留为兜底保护；预算超限时，该 pair 必须以 `trunk_search_budget_exceeded` 进入 rejected 输出，不生成 segment body，并在 `pair_validation_table.csv` 的 `support_info` 与 `segment_summary.json` 中保留预算配置、消耗、candidate/pruned road 数和 `kind_2 = 128` 节点数。
- `pair_validation_table.csv / validated_pairs.csv / rejected_pair_candidates.csv / segment_summary.json` 必须保留 candidate 穿越标记、节点列表、`kind2_128_local_corridor` 命中 / 终止统计和 validated / rejected 分组统计。
- 输出：
  - `validated`
  - `rejected`
  - `trunk`
  - `segment_body`
  - `step3_residual`
- final segment 仅表达 pair-specific road body。
- 强规则：
  - `non-trunk component` 触达其他 terminate（非 A/B）时，不进入 `segment_body`
  - `non-trunk component` 吃到其他 validated pair 的 trunk 时，不进入 `segment_body`

### 5.7 Step3
- Node 刷新优先级：
  1. 当前轮 validated pair 端点：保持当前值
  2. 所有 road 都在一个 segment 中：`grade_2 = -1, kind_2 = 1`
  3. 唯一 segment + 其余全是右转专用道：`grade_2 = 3, kind_2 = 1`
  4. 唯一 segment + 其余非segment road 同时存在 `in/out` 时，执行 family-based retyping：
     - 仅对当前 `grade_2 = 1, kind_2 = 4` 生效
     - `total_neighbor_family_count = 3`
     - `segment_neighbor_family_count = 1`
     - `residual_neighbor_family_count = 2`
     - 若两个 residual family 都是 `simple_residual_family`，则改为 `grade_2 = 2, kind_2 = 2048`
     - 否则改为 `grade_2 = 2, kind_2 = 4`
  5. 否则保持当前值
- Step2 新构成 road：
  - `sgrade = 0-0双`

### 5.8 Step4
- 输入：
  - `grade_2 in {1,2}`
  - `kind_2 in {4,64,2048}`
  - `closed_con in {2,3}`
- 当前轮合法 terminate 集合与输入集合一致。
- 并入历史高等级边界端点，来源遵守 §5.3。
- 工作图仅保护已有高等级 `sgrade = 0-0双` 的 road；历史低等级 / residual `segmentid` road 可进入 Step4 重构。
- 阶段结束后立即刷新 `nodes / roads`。
- Step4 新构成 road：
  - 默认 `sgrade = 0-1双`
  - 若 validated pair 两端代表语义路口 `grade_2` 均为 `1`，直接写 `sgrade = 0-0双`
  - 上述 `0-0双` road 同时写 `segment_build_source = step4_high_grade_terminal_demotion`，用于 Step6 审计识别其允许穿越中间高等级分歧 / 合流语义节点
- Step4 validated 结果优先于历史低等级 / residual `segmentid` 赋值；被当前轮 validated body 命中的 road 必须改写为当前 Step4 Segment，未命中的历史段保持原值。

### 5.9 Step5A / Step5B / Step5C
- 三个子阶段按顺序执行。
- 每个子阶段结束后，都立即刷新 `nodes / roads`。
- 下一子阶段使用上一子阶段 refreshed 的 `nodes / roads`。
- 各子阶段工作图中，剔除历史已有 `segmentid` 的 road，以及更早子阶段新构成的 `segment_body` road。

#### Step5A
- 输入：
  - `closed_con in {2,3}`
  - 且满足以下之一：
    - `kind_2 in {4,64,2048}` 且 `grade_2 in {1,2}`
    - `kind_2 in {4,64}` 且 `grade_2 = 3`
- 并入 `S2 + Step4` 历史高等级边界端点，来源遵守 §5.3。
- 新构成 road：
  - `sgrade = 0-2双`

#### Step5B
- 输入：
  - 基于 Step5A refreshed `nodes / roads`
  - `closed_con in {2,3}`
  - `kind_2 in {4,64,2048}`
  - `grade_2 in {1,2,3}`
- 并入 `S2 + Step4` 历史高等级边界端点，来源遵守 §5.3。
- Step5A 新端点只做 hard-stop，不回注入 Step5B 的 `seed / terminate`。
- 新构成 road：
  - `sgrade = 0-2双`

#### Step5C
- 基础合法输入集合：
  - `closed_con in {2,3}`
  - `kind_2 in {4,64,2048}`
  - `grade_2 in {1,2,3}`
- `rolling endpoint pool`：
  - 历史 validated endpoint `mainnode`
  - 当前 residual graph 上满足基础合法输入集合的语义路口
- `protected hard-stop set`：
  - 当前只保护环岛 `mainnode`
- `demotable endpoint set`：
  - 从 `rolling endpoint pool` 中扣除 `protected hard-stop set`
  - 再按 residual degree 与 barrier 语义退化判定
- `actual barrier` 不再等于“所有历史 endpoint”
- 新构成 road：
  - `sgrade = 0-2双`

### 5.10 Step5 后单向补段
- 执行位置：
  - 在 `Step5C` refreshed `nodes / roads` 之后
  - 在 `Step6` 聚合之前
- 作用边界：
  - 仅补齐仍未被双向 Segment 构成的单向 road
  - 不回写 `Step2 / Step4 / Step5A / Step5B / Step5C` 的双向构段规则
- 共享过滤：
  - `formway != 128`
  - 右转专用道不参与
  - 已有非空 `segmentid` 的 road 不再进入单向阶段
  - `road_kind = 1` 允许进入单向阶段，仅用于封闭式 / 高速相关单向补段，不回写双向 `Step1-Step5C` 的 `road_kind != 1` 约束
- 业务判断统一使用：
  - `kind_2`
  - `grade_2`
- through 规则：
  - 二度链接节点不切段
  - 非当前 terminate 的语义路口允许 through
  - 仅在命中当前轮 terminate 时切段停止
- 多分支延展：
  - 当前节点未命中 terminate 时，候选前进 road 中仅选择与当前行进方向夹角最小的一条继续
- 阶段定义：
  - `0-0单`：`closed_con in {1,3}`、`kind_2 in {8,16}`、`grade_2 = 1`
  - `0-1单`：`closed_con in {2,3}`、`kind_2 in {4,8,16,64,128,2048}`、`grade_2 in {1,2}`
  - `0-2单`：`closed_con in {2,3}`、`kind_2 in {4,8,16,64,128,2048}`、`grade_2 in {1,2,3}`
  - `kind_2 = 128` 代表复杂分歧 / 合流路口；当前仅纳入 `0-1单 / 0-2单`，不纳入 `0-0单`
- 新构成 road：
  - `sgrade = 0-0单 / 0-1单 / 0-2单`
- dead-end leaf 补段：
  - 在常规单向 terminate-to-terminate 补段之后、`Step6` 之前执行
  - 只处理仍未构段且满足排除规则的 residual road bundle
  - 支持两种 bundle 形态：
    - 一条 `direction in {0,1}` 的双向 road，且继续遵守双向 `road_kind != 1`
    - 两条方向互补的 `direction in {2,3}` 单向 road，允许沿用单向阶段的 `road_kind = 1` 放开口径
  - bundle 两端必须恰有一端满足合法语义端点，另一端为 leaf node
  - leaf node 端不得存在该 bundle 之外的其他有效 residual 延展
  - 单条未成对单向 road 暂不作为 dead-end leaf Segment 构建
  - 新构成 road：`sgrade = 0-2双`
  - 新构成 road 写入审计 / 发布保护字段：
    - `segment_build_source = dead_end_leaf`
    - `leaf_node_id = <leaf semantic node id>`
    - `dead_end_bundle_type in {bidirectional, reciprocal_oneway}`
- final single-road fallback：
  - 在常规单向 terminate-to-terminate 与 dead-end leaf 补段之后、`Step6` 之前执行
  - 处理仍未构段、`direction in {0,1,2,3}`、非 `formway = 128`、非右转专用道，且两端可解析到 semantic endpoint 的 road
  - 不放宽前序 phase terminate 规则；phase 不闭合、端点 phase 不一致、同 semantic group residual road，或未满足 dead-end leaf 的双向 residual road，只在本阶段兜底
  - 每条 road 形成一个单 road Segment
  - 新构成单向 road：`sgrade = 0-2单`
  - 新构成双向 road：`sgrade = 0-2双`
  - 新构成 road 写入审计 / 发布保护字段：
    - `segment_build_source = oneway_single_road_fallback`
  - `oneway_segment_summary.json` 必须输出 `final_fallback_segment_count`、`final_fallback_road_count`、`oneway_built_road_count` 与 `bidirectional_built_road_count`
- final side-attachment merge：
  - 在 final single-road fallback 之后、`Step6` 之前执行
  - 主 Segment 必须为当前已构成的 `sgrade = 0-0双`
  - 候选 Segment 必须已经有 `segmentid`，且候选 Segment 之间按 pair node 连通形成候选连通分量；分量连通只使用非主 Segment 覆盖节点，共享同一个主 Segment 挂接点不得把多个孤立侧支合成一个分量
  - 候选连通分量整体必须至少以两个语义节点挂接到同一个主 Segment 覆盖的语义节点；仅单点挂接、不能经候选分量回挂形成首尾闭环的孤立候选必须保留原 Segment
  - 候选连通分量自身几何必须被主 Segment 几何的 `MAX_SIDE_ACCESS_DISTANCE_M` buffer 覆盖；最大采样距离只作为审计和仲裁距离指标输出
  - 同一候选连通分量可匹配多个主 Segment 时，按挂接点数量多优先、最大采样距离短次优先、`segmentid` 字典序稳定兜底进行仲裁
  - 满足条件时，将候选 Segment road 改写到主 Segment：
    - `segmentid = <main segmentid>`
    - `sgrade = 0-0双`
    - `segment_build_source = side_attachment_merge`
    - 保留 `pre_merge_segmentid / pre_merge_sgrade / pre_merge_segment_build_source`
    - 写入 `side_attachment_merged_into_segmentid / side_attachment_merge_distance_m / side_attachment_merge_nodes`
  - 普通 `0-0双` 候选 Segment 不作为被并入对象，避免跨主走廊级联合并
  - `oneway_segment_summary.json` 必须输出 `side_attachment_merge_summary`、`side_attachment_merged_segment_count`、`side_attachment_merged_road_count`、候选连通分量数、挂接不足跳过数与多主 Segment 仲裁审计
- 新增 runner 对外产物：
  - `oneway_segment_roads.gpkg`
  - `oneway_segment_build_table.csv`
  - `oneway_segment_summary.json`
  - `unsegmented_roads.gpkg`
  - `unsegmented_roads.csv`
  - `unsegmented_roads_summary.json`
- `unsegmented_roads.*` 口径：
  - 统计双向 + 单向全部阶段完成后仍未形成 Segment 的 road
  - 必须排除 `formway = 128`
  - `unsegmented_roads.csv` 必须包含 `formway_has_bit7_or_bit8` 与 `audit_reason`
  - `unsegmented_roads_summary.json` 必须统计：
    - `unsegmented_formway_bit7_or_bit8_count`
    - `unsegmented_non_formway_bit7_or_bit8_count`
    - `unsegmented_non_formway_bit7_or_bit8_reason_counts`
  - `formway` bit7 / bit8 仅作为最终未构段审计分组口径；不改变已确认的构段过滤规则

## 6. Step6 契约

### 6.1 输入
- 最新 refreshed `nodes.gpkg`
- 最新 refreshed `roads.gpkg`

### 6.2 输出
- `segment.gpkg`
- `inner_nodes.gpkg`
- `segment_error.gpkg`
- `segment_error_s_grade_conflict.gpkg`
- `segment_error_grade_kind_conflict.gpkg`

### 6.3 聚合字段
- `segment.gpkg`
  - `id = segmentid`
  - `geometry = MultiLineString`
  - `sgrade`
  - `pair_nodes`
  - `junc_nodes`
  - `roads`
- `pair_nodes`
  - 按 `segmentid` 中 `A_B` 顺序解析
  - 若端点 `mainnodeid` 为空，则回退该 node 自身 `id`
- `inner_nodes.gpkg`
  - 复制被单一 Segment 完整内含的语义路口所有 node

### 6.4 Step6 规则
- 规则1：
  - 若某 Segment 两端路口 `grade_2` 都为 `1`，且 `sgrade != 0-0双`，则调整为 `0-0双`
  - 但 `sgrade in {0-0单,0-1单,0-2单}` 的单向 Segment 不适用该提升规则
  - dead-end leaf Segment 不适用该提升规则
- 规则2：
  - 对所有 `sgrade = 0-0双` 的 Segment，若其中间 `junc_nodes` 存在：
    - `grade_2 = 1`
    - 且 `kind_2 = 4`
    则输出到 `segment_error.gpkg`
  - 例外：若该 Segment 的 road 来源包含 `segment_build_source = step4_high_grade_terminal_demotion`，表示 Step4 已按两端高等级语义端点形成完整走廊，内部 `grade_2 = 1, kind_2 = 4` 节点视为可穿越的中间分歧 / 合流语义节点；该情况不输出 `grade_kind_conflict`，但必须在 `segment_summary.json` 统计 `grade_kind_conflict_waived_count`，并在 `segment_build_table.csv` 记录豁免节点
- typed error layers：
  - `segment_error_s_grade_conflict.gpkg` 仅包含 `sgrade` 冲突类记录
  - `segment_error_grade_kind_conflict.gpkg` 仅包含 `grade/kind` 冲突类记录
- Step6 对 `junc_nodes / inner_nodes / segment_error` 的判断，应与全局 `formway != 128` 约束保持一致。

## 7. Freeze Compare 契约
- 当前 active non-regression baseline：
  - `modules/t01_data_preprocess/baselines/t01_skill_active_eight_sample_suite/`
- 在引入 Step5 后单向补段后，freeze compare 的主用途是守护既有双向 Segment accepted baseline：
  - `validated_pairs_skill_v1.csv`
  - `segment_body_membership_skill_v1.csv`
  - `trunk_membership_skill_v1.csv`
  - Step5 结束时、进入单向补段之前的 refreshed `nodes / roads` hash
- 最终运行目录中的 `nodes.gpkg / roads.gpkg / segment.gpkg` 可以包含新增单向 Segment 结果；这些结果不作为双向 baseline compare 的主判定对象。
- 未经用户明确认可，不得更新 active freeze baseline

## 8. 文档与实现边界
- 本契约只描述当前 accepted baseline 下的对外契约与阶段约束。
- 临时样例基线与结构整改进度不写入本契约正文。
- 若实现与本契约冲突，应先修实现或提交歧义说明，不得自行覆盖 accepted baseline。
