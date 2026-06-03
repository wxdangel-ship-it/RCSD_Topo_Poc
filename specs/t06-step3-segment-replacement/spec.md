# T06 Step3 Segment Replacement and Junction Rebuild Spec

## Product View

T06 Step3 将 Step2 已判定可替换的 SWSD-RCSD Segment 对作为处理单元，生成融合后的 F-RCSD Road / Node 成果，并对被替换 Segment 涉及的语义路口关系进行重建。

Step3 的业务目标不是继续筛选候选，而是把 Step2 的可替换结论转化为 copy-on-write 融合成果：

- 保留未被替换的 SWSD Road / Node。
- 移除被替换 SWSD Segment 涉及的 SWSDRoad。
- 仅移除这些被替换 SWSDRoad 的端点 SWSDNode，不删除整个 SWSD 语义路口组下的所有 Node。
- 引入 Step2 RCSDSegment 中保留的 RCSDRoad / RCSDNode。
- 输出 `FRCSDRoad` 与 `FRCSDNode`，并用 `source` 字段标记数据来源：RCSD = `1`，SWSD = `2`。
- 对所有被替换 Segment 的 `pair_nodes / junc_nodes` 涉及的语义路口集合 C 进行关系重建。

Step3 必须保持可审计性：每个被替换 Segment 删除了哪些 SWSDRoad / SWSDNode、引入了哪些 RCSDRoad / RCSDNode、影响了哪些语义路口 C、每个 C 如何选择新的 main node，都必须有审计输出。Step3 还必须输出 SWSD Segment 到 FRCSD Road / Node 的稳定关系索引，用于下游 T09 Step3 在 FRCSD 上恢复路口通行限制。

## Architecture View

Step3 纳入 `t06_segment_fusion_precheck` 模块，作为 Step1 / Step2 之后的第三阶段。T06 的阶段关系为：

1. Step1：识别可参与融合的 SWSD Segment 单元。
2. Step2：构建并审计可替换 RCSDSegment。
3. Step3：消费 Step2 可替换成果，输出融合后的 F-RCSD Road / Node，并重建涉及的语义路口关系。

Step3 输入至少包括：

- Step2 `t06_rcsd_segment_replaceable` 或等价成功成果。
- Step2 `t06_rcsd_buffer_segments` 中的 retained RCSD road / node 审计字段。
- T01 / SWSD `segment`、`roads`、`nodes`。
- T05 Phase2 `rcsdroad_out`、`rcsdnode_out`。

Step3 核心对象：

- Replacement Segment Unit：一条 Step2 replaceable SWSD Segment 及其 retained RCSD Segment。
- Junction C：所有 replaceable Segment 的 `pair_nodes + junc_nodes` 涉及到的 SWSD 语义路口集合。
- C-to-Segment Relation：每个 C 与哪些 Replacement Segment 发生关系。

Step3 处理流程：

1. 读取 Step2 可替换 Segment，建立 `swsd_segment_id -> retained_rcsd_road_ids / retained_rcsd_node_ids / pair_nodes / junc_nodes / roads` 的映射。
2. 汇总所有可替换 Segment 的 `pair_nodes + junc_nodes`，构建待重建语义路口集合 C。
3. 为每个 C 建立其关联的 Replacement Segment 列表。
4. 从 SWSDRoad 中移除被替换 Segment 涉及的 SWSDRoad。
5. 从 SWSDNode 中仅移除被替换 SWSDRoad 的端点 Node。
6. 引入 retained RCSDRoad 与 retained RCSDNode，去重后写入 F-RCSD 成果。
7. 对 C 中每个语义路口执行重建：
   - 移除 Step3 已删除的 SWSD road endpoint node。
   - 增加替换后 RCSDSegment 在该路口下的 RCSDNode。
   - 若原 main node 仍保留，则继续使用原 main node。
   - 若原 main node 已被移除，则确定一个保留 Node 作为新的 main node。
   - C 内其余 Node 的 `mainnodeid` 统一替换为新的 main node id。
   - C 内 Node 的 `kind / grade / kind_2 / grade_2 / closed_con` 继承原 main node 对应 Node 的属性。
8. 输出 F-RCSD Road / Node 与 Step3 审计文件。
9. 输出 `t06_step3_swsd_frcsd_segment_relation.gpkg/csv/json`：
   - 对 replaceable Segment，记录 `relation_status = replaced`、被删除 SWSDRoad、引入 FRCSD Road、SWSD-to-FRCSD node mapping。
   - 对未替换 Segment，记录 `relation_status = retained_swsd`、保留在 FRCSD 中的 `source=2` SWSD Road。
   - 对解析失败或缺少承载的 Segment，记录显式失败原因，不允许 silent fix。

## Development View

实现必须保持在 `t06_segment_fusion_precheck` 模块内。除非后续任务明确授权，不新增 repo CLI、`Makefile` 目标、`tools/` 常驻命令、模块 `run.py` 或模块 `__main__.py`。

建议新增独立 Step3 helper，避免继续扩大 Step2 文件：

- replacement unit 解析。
- SWSD road/node 删除集计算。
- RCSD road/node 引入集计算。
- Junction C 建模与 C-to-Segment relation。
- main node 重选与属性继承。
- F-RCSD 输出与审计 summary。
- SWSD-FRCSD Segment relation 输出与下游 T09 Step3 消费审计。

Step3 应采用 copy-on-write：

- 不修改 T01 / T05 / Step2 原始输入。
- F-RCSD 输出写入 T06 run root 的 Step3 目录。
- 所有删除、增加、mainnode 重建动作都进入审计输出。

实现中必须显式处理重复关系：

- 多个 replaceable Segment 共享同一 SWSDRoad 时只能删除一次。
- 多个 replaceable Segment 引入同一 RCSDRoad / RCSDNode 时只能写出一次。
- 同一 C 可能关联多个 Replacement Segment，路口重建必须按 C 聚合后统一执行。

## Testing View

最小测试必须覆盖：

- 只消费 Step2 replaceable 成果，不处理 Step2 rejected。
- 删除 SWSDRoad 时，删除节点范围只限于被删 road 的端点 Node。
- 不删除整个 `pair_nodes / junc_nodes` 语义路口组下所有 SWSDNode。
- RCSDRoad / RCSDNode 被引入后 `source = 1`。
- 保留 SWSDRoad / SWSDNode 写出后 `source = 2`。
- 多个 Segment 共享 road / node 时输出去重。
- C 与 Replacement Segment 的关系可追溯。
- 每个 SWSD Segment 均能在 relation 输出中定位为 `replaced / retained_swsd / failed` 之一。
- relation 输出中的 `frcsd_road_ids` 必须能在 F-RCSD Road 输出中按 `id + source` 定位。
- 原 main node 未删除时保持 main node。
- 原 main node 已删除时可稳定选择新的 main node。
- C 内 Node 继承原 main node 的 `kind / grade / kind_2 / grade_2 / closed_con`。
- Step3 summary 记录输入数量、替换数量、删除数量、引入数量、重建 C 数量、relation 输出数量和失败原因。

## QA View

QA 审查重点：

- CRS 与输入输出坐标系必须明确，不能 silent fix。
- 拓扑一致性必须可审计：删除 road、删除 endpoint node、引入 RCSD road/node、C 重建均应可追溯。
- 几何语义必须可解释：F-RCSDRoad 中 SWSD 与 RCSD 来源分明，不通过几何猜测替代 Step2 结论。
- 审计可追溯：每个 output feature 能追溯到 source 与原始 id。
- 下游可追溯：T09 Step3 必须能只依赖 relation 输出、FRCSD Road / Node 与 T09 Step1/2 输出建立 Arm 级映射。
- 性能可验证：summary 必须记录输入规模、替换规模、输出规模和耗时/计数。
- 不得原地修改 SWSD / RCSD / T05 / Step2 输入文件。

## Confirmed Business Rules

- Step3 纳入 T06 模块。
- Step3 消费 Step2 可替换的 RCSD Segment 作为处理单元。
- 需要重建的语义路口 C 来自所有 replaceable Segment 的 `pair_nodes + junc_nodes`。
- C 必须记录其涉及的 Node，并建立 C 与关联 Replacement Segment 的关系。
- 被替换 SWSDRoad 全部清除。
- SWSDNode 仅清除被替换 SWSDRoad 的端点 Node，不清除整个语义路口组。
- 替换引入 Step2 RCSDSegment 涉及的 RCSDRoad / RCSDNode。
- F-RCSD 输出中 `source = 1` 表示 RCSD 数据，`source = 2` 表示 SWSD 数据。
- C 重建时，若原 main node 被删除，必须重新选定一个 Node id 作为 main node id。
- C 内其它 Node 的 `mainnodeid` 替换为该 main node id。
- C 内 `kind / grade / kind_2 / grade_2 / closed_con` 继承原 main node 对应 Node 的属性。
- 新增 `t06_step3_swsd_frcsd_segment_relation.*` 作为稳定下游关系输出；该输出不得改变 F-RCSD Road / Node 主成果。

## Open Questions Before Implementation

- F-RCSD 输出文件名固定为 `t06_frcsd_road.* / t06_frcsd_node.*`。
- SWSD 与 RCSD 原始 `id` 冲突时不拒绝、不重写 id；保留原 id，依赖 `source` 区分，并输出 `t06_step3_id_collision_audit.*` 做最终审计。
- 新 main node 选择优先级固定为：原 main node 若保留则继续使用；否则选择剩余 SWSD node 中 id 最小者；若无剩余 SWSD node，则选择加入该 C 的 RCSD node 中 id 最小者。
- C 内 RCSDNode 归属以 Step2 relation 的 RCSD semantic node 为主，同时使用 `rcsdnode_out.id/mainnodeid/subnodeid` canonicalization 补齐 retained RCSDRoad 端点 node。
- Step3 不改变现有 `scripts/t06_run_innernet_precheck.py` 默认行为；先提供独立脚本 `scripts/t06_run_step3_segment_replacement.py`，消费 Step2 replaceable 成果。
