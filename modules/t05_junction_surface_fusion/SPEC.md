# T05 模块规格：语义路口关系融合与 RCSD Junctionization

## 1. 模块定位

T05 汇总 T07 / T03 / T04 的锚定与构面成果，生产 SWSD-RCSD 语义路口关系，并对 RCSDRoad / RCSDNode 做 copy-on-write junctionization。模块分为 Phase 1 surface fusion 与 Phase 2 relation production，是 T06 Segment 替换和 T09 F-RCSD 通行恢复的关键上游。

## 2. 业务目标

- 将 T07/T03/T04 等来源的路口面统一融合为 `junction_anchor_surface.gpkg`。
- 基于 relation evidence、final nodes 与原始 RCSDRoad/RCSDNode，生产 `intersection_match_all.geojson`。
- 对 road-only、multi-RCSDNode、复杂路口和环岛场景执行可审计 junctionization。
- 输出 copy-on-write `rcsdroad_out.gpkg / rcsdnode_out.gpkg`，不原地修改输入。
- 用 cardinality audit 阻断同一 SWSD 多 RCSD 或同一 RCSD 多 SWSD 的错误成功关系。

## 3. 当前范围

### 3.1 正式支持

- Phase 1：T02_INPUT / T03 / T04 surface 归一、分组、融合和发布。
- Phase 2：消费 Phase 1 surface、final nodes、RCSDRoad/RCSDNode、T07/T03/T04 relation evidence。
- T07 relation-only target 可无 Phase 1 surface 进入最终 relation。
- T03/T04 road-only split、RCSDNode grouping、环岛归组。
- T03 旧 evidence backfill 兼容工具。
- junctionization 输入证据包 callable。

### 3.2 当前非目标

- Phase 1 不输出 `intersection_match_all.geojson`。
- Phase 1 不建立关系表、不打断 RCSDRoad、不新增 RCSDNode。
- Phase 2 不重新融合路口面、不修改 Phase 1 成果。
- Phase 2 不修改 T07/T03/T04 主链。
- 不原地修改输入 RCSDRoad / RCSDNode。

## 4. 上下游关系

| 方向 | 模块 / 数据 | 关系 |
|---|---|---|
| 上游 | T07 | 提供已有路口面 1:1 锚定 relation evidence。 |
| 上游 | T03 | 提供交叉 / T 型 accepted surface 和 relation evidence。 |
| 上游 | T04 | 提供分歧 / 合流 / complex accepted surface 和 relation evidence。 |
| 下游 | T06 | 消费 `intersection_match_all.geojson`、`rcsdroad_out.gpkg`、`rcsdnode_out.gpkg` 构建 RCSDSegment。 |
| 下游 | T09 | 通过 T06 F-RCSD 承载间接使用 T05 relation 成果。 |

## 5. 输入

| 输入 | 用途 |
|---|---|
| T03/T04 surface | Phase 1 主图层候选。 |
| T07/T03/T04 relation evidence | Phase 2 relation 与 junctionization 场景分流。 |
| `nodes.gpkg` | 反查 `mainnodeid / kind_2 / patch_id / grade / closed_con`。 |
| `RCSDRoad.gpkg / RCSDNode.gpkg` | Phase 2 copy-on-write junctionization 输入。 |
| optional T02_INPUT | 旧批次兼容输入，不作为新主链来源。 |

## 6. 输出

| 输出 | 用途 |
|---|---|
| `junction_anchor_surface.gpkg` | Phase 1 融合后的统一路口面。 |
| `junction_anchor_surface_fusion_audit.*` | 来源归一、融合、跳过和冲突审计。 |
| `intersection_match_all.geojson` | 项目级 SWSD-RCSD 语义路口关系主表。 |
| `rcsdroad_out.gpkg / rcsdnode_out.gpkg` | copy-on-write RCSD 输出。 |
| `rcsdroad_split / rcsdnode_generated / rcsdnode_grouped` | junctionization 增量审计层。 |
| `blocking_errors.*` | 无法发布成功 relation 的阻断原因。 |
| `module_relation_audit_summary.*` | 按来源模块统计 relation 生产效果。 |
| `relation_cardinality_errors.*` | 关系基数错误审计。 |

## 7. 关键业务步骤

| 步骤 | 业务说明 |
|---|---|
| Phase 1 输入归一 | 读取 surface，统一 CRS、字段、formal accepted 状态和 `mainnodeid`。 |
| Phase 1 融合发布 | 按 `mainnodeid` 分组，执行单源发布、多源 union 或 primary 选择。 |
| Phase 2 decision plan | 读取 Phase 1 surface、nodes、RCSD 与 relation evidence，形成 target 级场景计划。 |
| 只读 relation | 对已有单一 RCSD 语义路口、无 RCSD 普通失败等分支并行处理。 |
| RCSDNode grouping | 对多 RCSDNode 的 T03/T04 complex 或环岛场景归组。 |
| RCSDRoad split | 对 road-only 场景新增 RCSDNode 并打断 RCSDRoad。 |
| relation 发布 | 输出唯一 `target_id -> base_id` relation，并做 cardinality 审计。 |

## 8. 什么是对

- `intersection_match_all.geojson` 中一个 SWSD `target_id` 只输出一条 relation。
- 多个 RCSD 候选可合并时先归组，再输出唯一 relation。
- 无法合并的多候选必须写 blocking error，不得写主表成功关系。
- Phase 2 所有 RCSD 修改都是 copy-on-write。
- `kind_2 = 64` 环岛走独立归组分支，不通过 road-only split。

## 9. 什么是错

- Phase 1 根据几何相交跨 `mainnodeid` dissolve。
- Phase 2 回改 Phase 1 surface 或 T07/T03/T04 原始输出。
- 对同一 target 发布多条成功 relation。
- 原地修改输入 RCSDRoad / RCSDNode。
- 在缺少 T04 场景字段时 silent fallback，而不是从 accepted layer、summary、audit 或 case-level audit 补读。

## 10. 当前治理缺口

- T05 缺少标准 `architecture/02 / 05 / 11 / 12` 文档，后续需补齐。
- Phase 2 正确率仍需更多真实样本统计，但当前召回与审计链路已进入正式模块口径。
