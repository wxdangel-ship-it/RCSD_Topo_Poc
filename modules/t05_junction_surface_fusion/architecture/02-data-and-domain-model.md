# 02 数据与领域模型

## 1. 上下游数据关系

T05 消费 T07/T03/T04 的 surface 与 relation evidence、final SWSD nodes、RCSDRoad 和 RCSDNode。T05 输出 `junction_anchor_surface.gpkg`、`intersection_match_all.geojson`、`rcsdroad_out.gpkg`、`rcsdnode_out.gpkg` 和多类审计，供 T06 构建 RCSDSegment 和执行 Segment 替换。

## 2. 核心业务对象

| 对象 | 业务含义 |
|---|---|
| junction anchor surface | 多来源路口面融合后的 SWSD 语义路口面索引。 |
| relation evidence | T07/T03/T04 给出的 SWSD target 与 RCSD base 候选证据。 |
| target_id | SWSD 语义路口 ID，是最终关系主表的目标端。 |
| base_id | RCSD 语义路口 ID，是最终关系主表的基准端。 |
| RCSDNode grouping | 将多个 RCSDNode 归为一个 RCSD 语义路口。 |
| RCSDRoad split | 在 road-only 场景中通过投影点新增 RCSDNode 并打断 RCSDRoad。 |
| copy-on-write RCSD | 不修改原始 RCSDRoad/RCSDNode，只输出变更后的 `rcsdroad_out / rcsdnode_out`。 |
| cardinality audit | 检查 target/base 关系基数是否可发布给 T06。 |

## 3. 关键字段语义

- `mainnodeid` 是 Phase 1 surface 主分组键，无法解析时不得进入主图层。
- `surface_id = JAS:{mainnodeid}` 是 Phase 1 发布 ID。
- `target_id` 必须在 Phase 2 中做 canonical normalization，字符串整数与浮点字符串表达要统一。
- `status=0 / base_id>0` 表示成功 relation；`status=1 / base_id=0` 表示失败 relation。
- `many_target_to_one_base` 是非阻断审计；重复 target 或 `one_target_to_many_base` 是阻断错误。
- `level = grade - 1`、`is_highway = closed_con - 1`；缺失或非法时输出 `-1`。

## 4. 数据流

1. Phase 1 读取 T02_INPUT/T03/T04 surface 与可选 nodes，完成 CRS 和字段归一。
2. Phase 1 按 `mainnodeid` 分组，执行单源发布、多源 union 或 primary 选择。
3. Phase 2 读取 Phase 1 surface、relation evidence、final nodes 和 RCSD copy-on-write 输入。
4. Phase 2 形成 target 级 decision plan，先处理只读 relation，再处理 grouping / split 等会改变 copy-on-write RCSD 状态的分支。
5. Phase 2 发布 relation 主表、RCSDRoad/RCSDNode 输出、junctionization audit、blocking errors 和 cardinality audit。

## 5. 领域边界

T05 输出的是项目级 SWSD-RCSD 语义路口关系主表。T05 不负责 Segment 替换，不判断某个 Segment 是否可替换；这些属于 T06。T05 也不回改 T07/T03/T04 的路口面或 relation evidence。
