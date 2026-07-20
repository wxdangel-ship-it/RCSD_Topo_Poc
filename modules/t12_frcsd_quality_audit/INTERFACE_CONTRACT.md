# t12_frcsd_quality_audit - INTERFACE_CONTRACT

## 1. 契约边界

- 模块 ID：`t12_frcsd_quality_audit`
- 生命周期：`Active`
- 正式范围：原始 1V1 FRCSD 通行质量只读审计、自动高置信发布与可选 QA 覆盖。
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
- `--processing-crs`：仅在输入 CRS 不一致时显式指定 projected metre CRS。

### 2.3 关键字段与方向

- Road：`id/snodeid/enodeid/direction`；`direction 0/1` 双向、`2` snode→enode、`3` enode→snode。
- Node：`id`；`mainNodeId/subNodeId` 用于 canonical 候选图，并可在 raw failure 后构造 portal-constrained semantic 或 T07 Road-surface 排除证据。既有 semantic 证据继续要求 T07 alias 位于唯一标准面、非 T07 alias 及内部 transition 满足 `portal_radius_m`。Road-surface 证据仅在双端唯一 T07 标准面锚定时启用，必须包含方向正确的物理 Road，并由 Road/标准面相交或锚点组一跳物理 Road frontier 证明 access；一跳 support Road 必须是 anchor→frontier 有向边、接触标准面（允许 `1m` 拓扑容差），且整条 carrier 至少一端实际 Road-surface contact。其它距离类指标仅作审计。两类证据均不能单独确认问题。
- Segment：`id/pair_nodes/roads`。
- Source 只进入审计证据，不参与 verdict。

## 3. 状态和值域

| 字段 | 值域 | 含义 |
|---|---|---|
| `candidate_status` | `candidate_pending_decision` | 自动发现，尚需进入自动 decision 层。 |
| `review_status` | `confirmed_frcsd_quality_issue / excluded_false_positive / manual_review_required` | 最终兼容状态；默认由自动 decision 产生，显式 review 可覆盖。 |
| `issue_type` | `directed_carrier_missing / required_local_connectivity_missing` | 仅 confirmed 行允许非空。 |
| `decision_source` | `automatic_high_confidence / external_review_override` | 最终决定来源。 |
| `decision_rule` | `raw_carrier_missing_trusted_anchor / equivalent_raw_carrier / equivalent_portal_constrained_semantic_carrier / equivalent_t07_road_surface_carrier / insufficient_anchor_confidence / external_review_override` | 可审计决定规则。 |
| `raw_failed_directions` | SWSD 必需方向子集 | raw local directed 图失败的原始方向，不因 semantic 排除而丢失。 |
| `failed_directions` | SWSD 必需方向子集 | 完成 portal-constrained semantic 与 T07 Road-surface 排除后仍未解决的正式失败方向。 |
| `automatic_equivalence_basis` | 空 / `raw_carrier / portal_constrained_semantic_carrier / t07_road_surface_carrier` | 自动排除时使用的等价 carrier 层。 |
| `portal_constrained_semantic_status` | 按方向的 `equivalent / rejection_reason` | semantic 路径、端点和内部 alias 门禁结果。 |
| `t07_road_surface_status` | 按方向的 `equivalent / rejection_reason` | Road-surface 路径、两端 access、长度强门禁和距离审计结果。 |
| `anchor_confidence` | `t07_standard_surface / t03_pair / insufficient` | 自动归因锚点信用。 |
| run `status` | `passed / blocked / failed` | 契约完成、前置阻断或执行失败。 |

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

manifest/summary 至少记录输入绝对路径与 SHA-256、参数、CRS 转换、无效几何、endpoint 拓扑、canonical/raw 图分层、portal-constrained semantic carrier、T07 Road-surface carrier、surface 关联与 distance audit-only 指标、自动 decision、T05/T06 证据关系、对象规模、分阶段耗时、输出路径和 `silent_fix=false`。

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

T12 在 T10 中位于 T11 后、T09 前，始终 audit-only；该执行顺序不表示 T12 消费 T11 输出。

## 7. 验收口径

- CRS、拓扑、几何语义、审计追溯和性能字段完整。
- 不修改输入、不 silent fix。
- 自动 confirmed/excluded/manual 三类计数守恒，默认无 review 时 manual=0，最终确认文件只含 confirmed。
- T12 关闭时 T10 旧 package 和 T06→T11→T09 handoff 保持兼容。
