# T06 模块执行约束

本目录只约束 `t06_segment_fusion_precheck`。

## 当前阶段

- 当前模块正式范围已扩展到 T06 三个阶段：
  - Step1：识别可参与融合的 SWSD Segment 单元。
  - Step2：基于 T05 Phase 2 relation 与 copy-on-write RCSD 网络构建 RCSDSegment 候选，在特殊路口组门控后输出最终 `replaceable` 集合，并发布 `t06_segment_replacement_plan.*` 与 `t06_segment_replacement_problem_registry.*`。
  - Step3：优先消费 Step2 replacement plan，按普通 Segment、特殊路口组内部对象与 path-corridor group action 输出融合后的 F-RCSD Road / Node，并重建涉及的语义路口关系；旧 replaceable / special / group audit 仅作为兼容 fallback。
- Step3 已通过 `specs/t06-step3-segment-replacement/` 纳入 T06，并已提供模块内 runner 与独立脚本。
- Step3 仍采用 copy-on-write，不修改 T01 / T05 / Step2 输入成果。

## 禁止事项

- 不新增 repo CLI、`tools/`、`Makefile`、模块 `run.py` 或模块 `__main__.py`。
- T06 repo 级脚本入口：
  - `scripts/t06_run_innernet_precheck.py`：内网 Step1 + Step2 运行包装。
  - `scripts/t06_run_step3_segment_replacement.py`：独立 Step3 运行脚本，消费 Step2 replaceable 成果。
- T06 文本证据包压缩 / 解压只允许作为模块内 `text_bundle.py` helper 暴露，通过 `.venv/bin/python -c ...` 调用；不登记为 repo 官方 CLI。
- 不原地修改 `segment.gpkg`、`nodes.gpkg`、`intersection_match_all.geojson`、`rcsdroad_out.gpkg`、`rcsdnode_out.gpkg`、Step2 输出或 `swsd_roads_path`。
- 不根据局部数据反推上游字段语义；字段语义以 T01 / T05 / T06 契约为准。
- 不把 `pair_nodes` 顺序或 `segmentid A_B` 顺序当作 SWSD 单向方向。

## 实现边界

- 只允许模块内 callable runner：
  - `run_t06_step1_identify_fusion_units(...)`
  - `run_t06_step2_extract_rcsd_segments(...)`
  - `run_t06_step3_segment_replacement(...)`
  - `run_t06_segment_fusion_precheck(...)`
- 允许模块内非官方文本证据包 helper：
  - `run_t06_export_text_bundle(...)`
  - `run_t06_export_input_text_bundle(...)`
  - `run_t06_decode_text_bundle(...)`
  - `run_t06_export_text_bundle_from_args(...)`
  - `run_t06_export_input_text_bundle_from_args(...)`
  - `run_t06_decode_text_bundle_from_args(...)`
- 内网执行脚本 `scripts/t06_run_innernet_precheck.py` 只能转发到 `run_t06_segment_fusion_precheck(...)`，不得内置替代业务逻辑；`scripts/t06_run_step3_segment_replacement.py` 只能转发到 `run_t06_step3_segment_replacement(...)`。
- Step1 按 `pair_nodes + junc_nodes` 的语义路口 ID 集合判断 EVD 与 anchor/fallback 资格；其中 `junc_nodes.kind_2 in {1,4096,8192}` 的节点不参与 `has_evd / is_anchor` 判定并视为通过，`pair_nodes` 不适用该豁免。高等级 Segment 中非特殊 junc-only 节点若拖垮 `has_evd / is_anchor`，可从 final fusion unit 的 `junc_nodes / semantic_node_set` 中脱挂并写入 `detached_junc_nodes / detached_junc_reasons`；该规则不得用于 `pair_nodes`，不得用于 `kind_2 in {64,128}` 特殊路口。
- Step2 只接受 `intersection_match_all.geojson` 中 `status = 0` 且 `base_id > 0` 的 relation；relation 硬必检集合为 `pair_nodes`。非豁免 `junc_nodes` 若 relation 成功则作为 optional junc 审计和 corridor 解释节点，relation 缺失或无效不得默认拖垮 pair-to-pair 主通道。
- Step2 buffer 审查构图前必须按 `formway` bit7/128 识别提前右转 road；若该 road 两端均与非提前右转候选 road 形成二度链接，或属于 required semantic nodes 之间的必要 corridor，则保留参与 Segment 构建，否则排除。不得通过几何形态反推提前右转。
- `junc_nodes` 在 RCSD 抽取中是内部通过 + 侧向阻断，不是 hard-stop。
- Step2 不再执行 pair-to-pair BFS 路径搜索、主轴 / 粗长度趋势或唯一性筛选；`swsd_directionality=single` 的 source/target 必须由 SWSDRoad `snodeid / enodeid / direction` 推导，禁止用 `pair_nodes` 顺序或 `segmentid A_B` 顺序兜底；`swsd_directionality=dual` 时必须执行 RCSD retained graph 双向可达硬审计。
- retained RCSD graph 不允许存在 pair required corridor 内部解释节点以外的额外 T05 mapped semantic nodes；optional junc 若成为孤立挂接，可被剪除并进入 dropped / lost attach 审计。
- Step2 对 final `nodes.gpkg.kind_2=64` 环岛路口与 `kind_2=128` 复杂路口执行特殊组门控：按 `pair_nodes + junc_nodes` 关联 Segment，组内未全部可替换时，组内所有原本可替换 Segment 必须移出 replaceable，并输出特殊组审计；不得只替换特殊路口的一部分关联 Segment。
- Step3 只执行 Step2 replacement plan 中 `plan_status=ready` 的 action；无 plan 的旧运行才可兼容读取 Step2 replaceable、passed special group audit 与 group replacement audit。Step3 删除被替换 SWSDRoad 及其端点 SWSDNode，引入 plan 发布的 retained RCSDRoad / RCSDNode，输出 `source=1` 的 RCSD 数据与 `source=2` 的 SWSD 数据；不得删除整个 SWSD 语义路口组，也不得重新判定 rejected Segment 是否可替换。
- Step3 若发现 replaceable Segment 的 final `junc_nodes` 少于 T01 原始 `junc_nodes`，detached junc 触达的原 SWSDRoad 必须以 `source=2` 保留为局部通行限制 carrier，并在 Segment relation 中写 `relation_status=replaced+retained_swsd`、`detached_junc_nodes`、`retained_detached_swsd_road_ids` 与 `identity_retained_swsd` node map；该 node map 不代表 RCSD 锚定成功。
- Step3 不重新判定特殊路口组是否可替换；若 Step2 同目录存在 `t06_special_junction_group_audit.*`，仅消费其中 `gate_status=passed` 的组级 RCSD 内部 Node/Road，并统一加入 F-RCSD。
- Step3 重建的语义路口 C 来自 replaceable Segment 的 `pair_nodes + junc_nodes`；若原 main node 被删除，必须重新选择 main node，并让 C 内 Node 继承原 main node 的 `kind / grade / kind_2 / grade_2 / closed_con`。

## 必做验证

- 单元测试必须覆盖 Step1 eligibility、relation mapping、buffer-based RCSDSegment 构建、提前右转 bit mask 排除、RCSD semantic node canonicalization 与 runner 输出。
- GIS / 拓扑任务必须显式覆盖 CRS、拓扑一致性、几何语义、审计追溯与性能可验证性。
- 提交前至少执行 T06 测试与 `git diff --check`。
