# t12_frcsd_quality_audit - INTERFACE_CONTRACT

## 1. 契约边界

- 模块 ID：`t12_frcsd_quality_audit`
- 生命周期：`Active`
- 正式范围：原始 1V1 FRCSD Segment 通行质量与 Junction 质量只读审计、自动高置信发布及 Segment 可选 QA 覆盖。
- 非目标：自动修复、T06 替换判定、T09/T11 handoff 改写。

## 2. 输入契约

### 2.1 必选输入

- `--swsd-segment / --swsd-roads / --swsd-nodes`
- `--frcsd-roads / --frcsd-nodes`：必须是语义明确的原始 1V1 FRCSD target。
- `--t05-anchor-audit`：含 `target_id/base_id/source_module/status`，可含 `grouped_rcsdnode_ids`。
- `--rcsd-intersection`
- `--t06-run-root`：必须含 Step2 summary 和 rejected evidence，并能追溯到同一 T05 派生链；若存在 buffer-only probe、failure business audit、problem registry 和 replacement plan，也必须只读登记路径与指纹并按 Segment 合并为交叉证据。
- `--out-root`

### 2.2 可选输入

- `--drivezone`：只作道路面参考证据。
- `--case-manifest`：提供 Case bounds，用于 500m crop-edge 审计。
- `--review-decisions`：可选外部 QA 覆盖 CSV；不再是 confirmed 结果的前置条件。
- `--t03-run-root`：可选正式 T03 运行根；只读取完整 Step3/association/Step6/Step7 rejected 审计链，并以原始 1V1 FRCSD 重新判断 Junction。
- `--t07-run-root`：可选 T07 Step1/2 运行根或 `step2_anchor_recognition` 根；只消费代表路口 final `is_anchor=fail1/fail2`，并校验 `node_error_1/2.gpkg`、Step2 summary 与 relation evidence。
- `--t07-step3-run-root`：弃用兼容参数，仅允许在一个版本内定位同一运行链的 Step2 根；绝不读取 `relation_cardinality_errors.*`，无法唯一定位 Step2 时 blocked。
- `--processing-crs`：仅在输入 CRS 不一致时显式指定 projected metre CRS。

T03/T07 Junction 参数均为可选；既有必选参数、默认值和 Segment-only 调用方式不变。不提供时仍写结构完整的空 Junction 输出，Segment 结果不变。

### 2.3 关键字段与方向

- Road：`id/snodeid/enodeid/direction`；`direction 0/1` 双向、`2` snode→enode、`3` enode→snode。每个 SWSD 必需方向独立构造 source/target portal；source raw node 必须具有当前方向可用的 outgoing Road，target raw node 必须具有 incoming Road。无向图只用于诊断，不参与 portal 资格或等价 carrier。
- Node：`id/mainNodeId/subNodeId`。1V1/T05 选中 `base_id` mainNode 的 canonical raw alias group 是受信 portal membership；其它显式 grouped raw node 保留，但不递归展开其各自 canonical group。成员仍以各自 raw ID 进入 identity endpoint 图，按 source outgoing / target incoming 过滤，实际 carrier 必须含方向正确的物理 Road；成员到 SWSD portal 或标准面的距离只作审计。非 anchored T07 fallback 仍必须位于唯一标准面，非 anchored T03/T04 spatial fallback 仍满足 `portal_radius_m`。raw failure 后的既有 semantic 证据继续要求非 anchored T07 alias 位于唯一标准面、非 T07 alias 及内部 transition 满足 `portal_radius_m`。Road-surface 证据仅在双端唯一 T07 标准面锚定时启用，必须包含方向正确的物理 Road，并由 Road/标准面相交或锚点组一跳物理 Road frontier 证明 access；一跳 support Road 必须是 anchor→frontier 有向边、接触标准面（允许 `1m` 拓扑容差），且整条 carrier 至少一端实际 Road-surface contact。其它距离类指标仅作审计。两类证据均不能单独确认问题。对 `unexpected_reverse_carrier`，双 T07 还可把与 anchor base/group 同 canonical group、位于 `portal_radius_m` 内且落在正确 SWSD portal Voronoi 侧的实际 raw endpoint 用作路径端点；这不创建图边，也不允许内部 alias 跳接。自动确认时，反向路径第一/最后 Road 还必须分别接触对应双端标准面（允许相同 `1m` 拓扑容差）。
- Segment：`id/pair_nodes/roads`。反向路径扣除双端标准面及 `1m` 容差后的每条 raw RCSD Road，必须按 `20m coverage > 50m coverage > geometry distance` 唯一归属于当前 Segment；其它 Segment 更优或并列均不得自动确认。
- Source 只进入审计证据，不参与 verdict。
- T03 Junction eligibility 只使用正式 SWSD Node 字段 `has_evd=yes`、`is_anchor=no`、`kind_2 in {4,2048}`；`has_evd` 语义由 T03 输入事实提供，T12 不反推或改写。
- T03 Junction 当前 SWSD selected Road/Direction 必须派生 boundary arm 与有向 `incoming -> outgoing` required movement。默认 alias endpoint tolerance 为 `6m`、local Junction scope 为 `50m`、target ownership 与 boundary geometry 高置信检索门禁均为 `10m`，Road outward heading 采用从内端点向外 `10m` 采样且匹配夹角不超过 `25°`。这些门禁只控制未锚定/非同臂证据不得进入自动确认；一旦两端 carrier 已锚定，后续等价 carrier 不得再因距离被拒绝。每条自动确认必须公开两端 SWSD arm Road、FRCSD boundary Road/portal、heading 差、缺失原因和实际有向 Road 序列。
- T03 support topology 的 main/subNode 只作分组和 portal membership，不创建 graph edge。每个 required role 必须在 raw identity endpoint 图或 Road-surface portal 图包含 Direction 合法的实际 Road carrier；无效几何、缺失 endpoint、正式高置信跨层解释、局部替代 carrier 或同 canonical group 的等价 alias carrier 阻止自动确认，禁止 snap、repair 或补点。

## 3. 状态和值域

| 字段 | 值域 | 含义 |
|---|---|---|
| `candidate_status` | `candidate_pending_decision` | 自动发现，尚需进入自动 decision 层。 |
| `review_status` | `confirmed_frcsd_quality_issue / excluded_false_positive / manual_review_required` | 最终兼容状态；默认由自动 decision 产生，显式 review 可覆盖。 |
| `issue_type` | `segment_required_direction_unavailable / segment_required_connection_missing / segment_unexpected_reverse_passability` | 仅 confirmed 行允许非空。 |
| `result_status` | `confirmed / excluded / manual_review` | 正式结果状态；与兼容 `review_status` 一致。 |
| `issue_group` | `segment_passability / junction_topology / junction_anchor_relation` | confirmed 的稳定问题分组。 |
| `issue_code` | `S01-S03 / J01-J04` | confirmed 的稳定问题编码。 |
| `legacy_issue_type` | v9 旧类型或空 | 仅保留一个版本的迁移审计；不得作为新口径。 |
| `decision_source` | `automatic_high_confidence / external_review_override` | 最终决定来源。 |
| `decision_rule` | `raw_carrier_missing_trusted_anchor / equivalent_raw_carrier / equivalent_portal_constrained_semantic_carrier / equivalent_t07_road_surface_carrier / insufficient_anchor_confidence / unexpected_reverse_raw_carrier_dual_t07_segment_scoped / unexpected_reverse_swsd_equivalent / unexpected_reverse_insufficient_high_precision_evidence / unexpected_reverse_other_segment_covered / unexpected_reverse_segment_ownership_ambiguous / unexpected_reverse_anchor_interval_unproven / external_review_override` | 可审计决定规则。 |
| `candidate_kind` | `missing_required_carrier / unexpected_reverse_carrier` | 区分既有必需方向缺失与单向 Segment 的非预期反向载体。 |
| `raw_failed_directions` | SWSD 必需方向子集 | raw local directed 图失败的原始方向，不因 semantic 排除而丢失。 |
| `failed_directions` | SWSD 必需方向子集 | 完成 portal-constrained semantic 与 T07 Road-surface 排除后仍未解决的正式失败方向。 |
| `automatic_equivalence_basis` | 空 / `raw_carrier / portal_constrained_semantic_carrier / t07_road_surface_carrier` | 自动排除时使用的等价 carrier 层。 |
| `directional_portal_status` | 按方向的 JSON 数组 | source outgoing/target incoming 资格、portal 数量、anchored group portal 数量和可用性。 |
| `portal_constrained_semantic_status` | 按方向的 `equivalent / rejection_reason` | semantic 路径、端点和内部 alias 门禁结果。 |
| `t07_road_surface_status` | 按方向的 `equivalent / rejection_reason` | Road-surface 路径、两端 access、长度强门禁和距离审计结果。 |
| `unexpected_direction` | 空 / `pair0_to_pair1 / pair1_to_pair0` | 单向 Segment 不应额外出现的相反方向。 |
| `unexpected_reverse_frcsd_status` | 空 / `equivalent / rejection_reason` | 反向 raw FRCSD 实际 Road 路径及几何门禁结果。 |
| `unexpected_reverse_swsd_status` | 空 / `equivalent / rejection_reason` | SWSD 全图反向替代路径的保守排除结果。 |
| `unexpected_reverse_anchor_interval_status` | 空 / `accepted / rejection_reason` | 反向路径第一/最后 Road 与当前双端 T07 标准面接触及区间内物理 Road 状态。 |
| `unexpected_reverse_segment_ownership_status` | 空 / `current_segment_unique_owner / rejection_reason` | 锚点间逐 raw RCSD Road 的当前 Segment 唯一归属状态。 |
| `anchor_confidence` | `t07_standard_surface / t03_pair / insufficient` | 自动归因锚点信用。 |
| run `status` | `passed / blocked / failed` | 契约完成、前置阻断或执行失败。 |
| Junction `issue_type` | `junction_required_topology_missing / junction_unmatched_support_topology / junction_anchor_one_to_many / junction_anchor_many_to_one` | T03 候选经 required-role/carrier 独立复核后的高置信根因，或 T07 Step2 `fail1/fail2`。 |
| Junction `decision_source` | `automatic_high_confidence / t07_step2_stable_failure_direct` | T03 由 T12 重验，T07 Step2 final failure 直接发布。 |
| Junction `decision_rule` | `raw_frcsd_required_junction_movement_missing_confirmed`、`t07_step2_fail1_direct_publish / t07_step2_fail2_direct_publish` 或可审计 exclusion rule | 历史 T03 shape/guard 规则只保留为 candidate signal，不能直接成为决定规则；同 CaseID 不跨输入快照复用。 |
| Junction geometry | `Point` | SWSD 代表路口；support Road、endpoint、projection 与 conflict link 进入 evidence layers。 |

禁止使用 `high/medium confidence` 作为正式状态。

## 4. Review CSV 契约

必选列：

```text
run_id,candidate_id,review_status,issue_type,review_reason,review_source,reviewed_at_utc
```

- `run_id` 必须与当前运行完全一致。
- candidate 不得重复或引用未知 ID。
- confirmed/excluded 必须有 `review_reason`。
- 只有 confirmed 可以填写合法 `issue_type`。
- 未提供 review 行的候选保留自动决定；只有显式 review 行可以覆盖为 `manual_review_required`。

## 5. 输出契约

每次 passed 运行都写：

- `t12_frcsd_quality_audit_manifest.json`
- `t12_frcsd_quality_audit_summary.json`
- `t12_frcsd_quality_candidates.csv/.gpkg`
- `t12_frcsd_carrier_evidence.gpkg`
- `t12_frcsd_confirmed_quality_issues.csv/.gpkg`
- `t12_frcsd_quality_review_exclusions.csv`
- `t12_frcsd_quality_manual_review_required.csv`
- `t12_frcsd_quality_report.md`
- `t12_frcsd_junction_quality_candidates.csv/.gpkg`
- `t12_frcsd_confirmed_junction_quality_issues.csv/.gpkg`
- `t12_frcsd_junction_quality_exclusions.csv`
- `t12_frcsd_junction_carrier_evidence.gpkg`

manifest/summary 至少记录输入绝对路径与 SHA-256、参数、CRS 转换、无效几何、endpoint 拓扑、canonical/raw 图分层、anchored canonical alias membership、Direction role、alias distance audit、非锚定 fallback、portal-constrained semantic carrier、T07 Road-surface carrier、FRCSD 反向载体、SWSD 反向替代路径、反向双端锚点区间、逐 raw RCSD Road Segment 唯一归属、其它 Segment 覆盖、surface 关联与 distance audit-only 指标、自动 decision、T05/T06 证据关系、T03/T07 来源 run identity 和工件指纹、T03 formal raw topology guard 原文、required Junction movement、boundary carrier mapping、raw directed path、canonical alias portal、Junction eligibility/projection/support/endpoint/component/替代 carrier/跨层/Direction 证据、Segment 与 Junction 独立计数、对象规模、分阶段耗时、输出路径和 `silent_fix=false`。

Segment candidates/confirmed GPKG 主几何保持 T01 Segment 线几何族，允许源数据对应的 `LineString/MultiLineString`；Junction candidates/confirmed GPKG 主几何只写 `Point`。两者不得合并成同一正式问题层。Segment review CSV 本轮不覆盖 Junction 自动决定。

`<out-root>/<run-id>` 必须尚不存在；同名运行根在加载输入前以 contract error 阻断，不覆盖或追加既有审计结果。

## 6. 入口契约

```bash
.venv/bin/python scripts/t12_run_frcsd_quality_audit.py --help
```

模块 callable：

```python
from rcsd_topo_poc.modules.t12_frcsd_quality_audit import run_t12_frcsd_quality_audit
```

T10 Case：`RUN_T12=1 scripts/t10_run_e2e_cases.sh ...`。
T10 full：`RUN_T12=1 FRCSD_1V1_ROADS_PATH=... FRCSD_1V1_NODES_PATH=... T12_PROCESSING_CRS=<optional projected metre CRS> scripts/t10_run_innernet_full_pipeline.sh`。T10 的 `T12_PROCESSING_CRS` 只在非空时透传为 `--processing-crs`；空值保持混合 CRS 硬阻断，禁止自动推断。

T10 启用 T12 时必须传入当前 T03 run root 和已有 T07 Step1/2 run root；不得为了 T12 启用可选 T07 Step3。T12 在 T10 中位于 T11 后、T09 前，始终 audit-only；该执行顺序不表示 T12 消费 T11 输出。

`scripts/t12_rerun_frcsd_junction_quality_innernet.sh` 必须接收既有 `T10_RUN_ROOT`。默认新结果固定写入 `<T10_RUN_ROOT>/t12_frcsd_quality_audit/t12_full`；若该目录已存在，先将其完整移动到 `<T10_RUN_ROOT>/history/t12_frcsd_quality_audit/<run_id>_<timestamp>`，不得覆盖或删除历史结果。若新 T12 未通过，则失败批次保留到 history，原批次恢复到标准目录；只有新 T12 完整通过时才提交目录切换。通用 T10 full runner 在同一 T12 run id 续跑时遵循相同规则。

## 7. 验收口径

- CRS、拓扑、几何语义、审计追溯和性能字段完整；反向自动确认必须同时有双端锚点区间与当前 Segment 唯一归属证据。
- 不修改输入、不 silent fix。
- 自动 confirmed/excluded/manual 三类计数守恒，默认无 review 时 manual=0，最终确认文件只含 confirmed。
- Junction candidates/confirmed/exclusions 独立计数守恒，正式主几何为 Point；T03 结果必须来自原始 FRCSD 重验，T07 输出集合必须与 Step2 final `fail1/fail2` 集合精确一致，Step3 cardinality 导入数为 0。
- T03 formal raw guard 不得按 reason 字符串直通；必须记录当前输入快照、SWSD required roles、全部 canonical raw alias portals 和逐角色实际 carrier。引用的 support/connecting Road 必须在当前 FRCSD 存在，Direction 必须属于 `0/1/2/3`；完整等价 carrier、输入几何无效或高置信跨层证据必须排除自动确认。
- T12 关闭时 T10 旧 package 和 T06→T11→T09 handoff 保持兼容。
