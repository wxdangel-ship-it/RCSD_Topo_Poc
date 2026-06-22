# 04 证据与审计

## 1. 审计目标

T05 必须解释每个 surface 来源、每个 relation 成功或失败的原因、每次 RCSD grouping / split 的动作，以及最终关系是否满足基数要求。T05 是 T06 的关系主表上游，因此不能用静默 fallback 掩盖多候选、缺 evidence 或不可消费 RCSD 图问题。

## 2. Phase 1 证据

| 证据 | 业务用途 |
|---|---|
| `junction_anchor_surface.gpkg` | 统一路口面主图层。 |
| `junction_anchor_surface_fusion_audit.csv/json` | 来源归一、分组、融合、primary 选择、冲突和跳过审计。 |
| `summary.json` | 输入计数、发布计数、缺字段、CRS 和 consistency。 |

## 3. Phase 2 证据

| 证据 | 业务用途 |
|---|---|
| `intersection_match_all.geojson` | T06 消费的 SWSD-RCSD 语义路口关系主表。 |
| `rcsdroad_out.gpkg / rcsdnode_out.gpkg` | copy-on-write RCSD 主输出。 |
| `rcsdroad_split / rcsdnode_generated / rcsdnode_grouped` | junctionization 增量审计层。 |
| `rcsd_junctionization_audit.csv/json` | grouping、split、direct relation、failure relation 的动作审计。 |
| `blocking_errors.csv/json` | 多 base 无法合并、缺关键证据等阻断问题。 |
| `module_relation_audit_summary.csv/json` | 按来源模块统计 relation 生产效果。 |
| `relation_cardinality_errors.csv/json` | target/base 基数错误归因。 |
| `relation_graph_consumability_audit.csv/json` | 成功 relation 的 RCSD 图可消费性追溯。 |

## 4. Handoff 与补齐证据

T03 handoff backfill 只为旧 T03 evidence 兼容服务，读取 T03 已输出的 relation evidence 与 case 级 Step6 状态，输出独立 backfilled evidence、audit 和 summary。它不能新增 T03 业务语义，也不能覆盖原始 T03 输出。

## 5. T10 Feedback 审计

T10 side-group endpoint candidates 与 pair-anchor endpoint clusters 只作为 Phase 2 补充证据。它们只能依附已有成功 relation 或 T03/T04 road-only split 决策补充 RCSDNode grouping，不单独创建 relation，不覆盖 road-only split 主决策。
