# T06 模块规格：RCSDSegment 构建与 Segment 替换

## 1. 模块定位

T06 消费 T01 SWSD Segment 与 T05 SWSD-RCSD 语义路口关系，构建 RCSDSegment 候选，判定最终 replaceable 集合，并在 Step3 输出融合后的 F-RCSD Road / Node。T06 是从关系建模进入数据替换的承接模块，也是 T09 在 F-RCSD 上恢复 restriction 的直接上游。

## 2. 业务目标

- 从 T01 `segment.gpkg` 中识别可参与融合的 SWSD Segment。
- 基于 T05 relation 与 copy-on-write RCSD 网络构建 buffer-based RCSDSegment。
- 输出经过硬审计与特殊路口组门控后的 replaceable 集合。
- 只对 Step2 replaceable Segment 执行替换，输出 F-RCSD Road / Node。
- 对失败 Segment 输出诊断、候选修复证据和上游责任归因，不静默覆盖 T05 relation。

## 3. 当前范围

### 3.1 正式支持

- Step1：识别 SWSD Segment 候选和最终 fusion units。
- Step2：基于 buffer-based 策略构建 RCSDSegment 候选和 replaceable。
- Step3：消费 replaceable 执行 Segment 替换，输出 F-RCSD Road / Node。
- `kind_2=64 / 128` 特殊路口组门控。
- buffer-only probe、repair candidates 与 failure business audit。
- 内网脚本和文本证据包 helper。

### 3.2 当前非目标

- 不修改 T01 / T05 输出。
- 不新增 repo CLI。
- Step3 不处理 Step2 rejected Segment。
- Step3 不通过几何猜测补救未通过 Step2 的 Segment。
- Step2 不再执行旧 pair-to-pair BFS、主轴趋势、长度趋势或唯一性筛选。

## 4. 上下游关系

| 方向 | 模块 / 数据 | 关系 |
|---|---|---|
| 上游 | T01 | 提供 SWSD `segment.gpkg`、`roads.gpkg`、`nodes.gpkg`。 |
| 上游 | T05 | 提供 `intersection_match_all.geojson`、`rcsdroad_out.gpkg`、`rcsdnode_out.gpkg`。 |
| 下游 | T09 | 消费 F-RCSD Road/Node 与 SWSD-FRCSD Segment relation 进行 restriction 投影。 |
| 下游 | T10 | 以文件 handoff 方式组织 T06 输出的 Case 证据。 |

## 5. 输入

| 输入 | 用途 |
|---|---|
| T01 `segment.gpkg` | Step1 候选 Segment、`pair_nodes / junc_nodes / roads / swsd_directionality` 来源。 |
| SWSD `roads.gpkg / nodes.gpkg` | Step1/Step3 删除和保留 SWSD Road/Node 的来源。 |
| T05 `intersection_match_all.geojson` | Step2 将 SWSD pair/junc 映射到 RCSD 语义路口。 |
| T05 `rcsdroad_out.gpkg / rcsdnode_out.gpkg` | Step2 RCSD 建图和 Step3 引入 RCSD Road/Node 的来源。 |
| `t06_special_junction_group_audit.*` | Step3 消费 passed 特殊路口组内部 RCSDRoad / RCSDNode。 |

## 6. 输出

| 输出 | 用途 |
|---|---|
| `t06_swsd_segment_candidates.*` | 通过 EVD 基础检查的 SWSD Segment 候选。 |
| `t06_swsd_segment_final_fusion_units.*` | 通过 anchor / fallback 检查的最终 SWSD fusion units。 |
| `t06_rcsd_segment_candidates.*` | buffer 成功构建的 RCSDSegment 候选。 |
| `t06_rcsd_segment_replaceable.*` | 经过硬审计与特殊组门控后的最终可替换集合。 |
| `t06_rcsd_segment_rejected.*` | Step2 拒绝原因和审计。 |
| `t06_special_junction_group_audit.*` | 环岛 / 复杂路口组级门控审计。 |
| `t06_frcsd_road.* / t06_frcsd_node.*` | Step3 F-RCSD 替换结果。 |
| `t06_step3_unreplaced_rcsd_roads.*` | 未进入替换结果的 RCSDRoad 审计。 |

## 7. 关键业务步骤

| 步骤 | 业务说明 |
|---|---|
| Step1 eligibility | 解析 `pair_nodes + junc_nodes`，基于 `has_evd / is_anchor` 识别候选与 final fusion units。 |
| Step2 relation mapping | 用 T05 relation 映射 pair required nodes，optional junc 只做审计和受控约束。 |
| Step2 buffer candidate | 以 SWSD Segment 50m buffer 筛选 RCSDRoad/RCSDNode 候选。 |
| Step2 corridor 构建 | 基于 pair required semantic nodes 构建最小 corridor 子图，不直接发布连通分量。 |
| Step2 pruning / hard audit | 裁剪 out seeds，检查叶子端点、双向 / 单向可达、buffer overlap 和额外 mapped semantic nodes。 |
| 特殊组门控 | 环岛和复杂路口关联 Segment 必须全组可替换，否则整组移出 replaceable。 |
| Step3 替换 | 删除被替换 SWSDRoad 和端点 Node，引入 retained RCSDRoad/RCSDNode，重建语义路口 C。 |

## 8. 什么是对

- Step2 只接受 `status=0 / base_id>0` 的 T05 relation。
- `pair_nodes` 是 hard required，`junc_nodes` 是 optional 内部通过 + 侧向阻断。
- retained RCSD graph 的叶子端点只能是 pair 对应 RCSD semantic nodes。
- 单向 Segment 的 source/target 只能由 SWSDRoad directed graph 推导。
- Step3 只消费 Step2 replaceable，不重新判定特殊组可替换性。

## 9. 什么是错

- 用 buffer 连通分量直接作为 RCSDSegment。
- 用 repair candidate 覆盖 T05 relation 并继续生成 replaceable。
- 用 `pair_nodes` 字段顺序或 `segmentid A_B` 顺序推断单向 direction。
- 对 Step2 rejected Segment 执行 Step3 替换。
- 因 SWSD/RCSD 原始 `id` 冲突而重写 ID；应依赖 `source` 区分并输出 collision audit。

## 10. 当前治理缺口

- 架构目录仍保留旧 `02-business-rules / 03-input-output-contract / 04-algorithm-strategy`，本轮新增标准 `architecture/04-solution-strategy.md` 后，旧文件应作为兼容参考逐步收敛。
- Step3 输出的 SWSD-FRCSD Segment relation 需持续与 T09 输入契约保持同步。
