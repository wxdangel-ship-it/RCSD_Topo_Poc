# 02 数据与业务模型

## 文档定位

本文档承载项目级全局业务概念、共用数据对象、字段语义和术语。模块局部字段、阈值、Step 规则和输出契约仍以模块级 source-of-truth 为准。

## 数据对象

| 对象 | 项目级含义 | 主要消费者 |
|---|---|---|
| SWSD | 现场道路、节点、Laneinfo、restriction 等源侧语义数据 | T08、T01、T03、T04、T05、T06、T11、T12、T09 |
| RCSD | 场景路网侧 Road / Node / RoadNextRoad 等承载数据 | T08、T03、T04、T05、T06、T11、T09 |
| F-RCSD | 融合后的承载数据；当前仓库生产链中的 F-RCSD 由 T06 Segment 替换生成，T12 质检对象则是外部 1V1 匹配技术生成的原始 F-RCSD，两者 Source 语义一致但生成路径不得混同 | T11（T06 结果审计）、T12（原始 1V1 F-RCSD 质检）、T09、P01、P02（局部实验审计） |
| Semantic Junction | SWSD 语义路口代表对象，承载路口级关联、锚定与通行建模语义 | T07、T03、T04、T05、T09 |
| Segment | 以 SWSD Road / Node 组织出的可替换道路连续单元 | T01、T06、T11、T09 |
| Virtual Anchor | 在无现成 RCSD 路口面或需补充表达时构建的虚拟锚定成果 | T03、T04、T05 |
| Relation Evidence | SWSD 与 RCSD 语义路口、Road、Segment 的关联证据 | T05、T06、T11、T09 |
| Patch Vector Evidence | 与 SWSD/完整 RCSD 无对象级直接 ID 关系的 Patch Lane、LaneTopo、Boundary、道路面和设施证据；通过 Segment 覆盖范围、Patch membership 与跨 Patch 统一聚合建立候选，高精 Road 几何以此为正式物理证据 | P04 |
| Segment-first RoadGraph Candidate | P04 中由 T01 Segment 和 SWSD 路口—路段先验建立完整语义骨架，由 T07/T03/T04/T08 accepted surface 定义 JunctionUnit，再由 Patch Vector、同版本 Patch Road 与 LaneTopo 实例化的 Road/Node/RoadNextRoad POC 候选；语义存在、证据支持、可发布性与接管范围必须分离 | P04 POC QA |

## 主数据流

```text
SWSD / RCSD raw data
  -> T08 preprocessing and QC
  -> T01 SWSD Segment
  -> T07 / T03 / T04 junction anchoring
  -> T05 semantic junction relation fusion
  -> T06 Segment replacement and F-RCSD
  -> T09 traffic rule restoration
```

## 字段语义

| 字段 / 字段族 | 当前项目级语义 |
|---|---|
| `mainnodeid` / `subnodeid` | SWSD 语义路口代表 node 与子 node 关系，用于路口级聚合、锚定和证据归集。 |
| `kind` / `Road.kind` | 道路种别字段；单个 token 为 `XXXX`，前两位表示道路等级，后两位表示道路类型，多个 token 用 `|` 分隔。 |
| `kind_2` | SWSD 语义路口类型字段，当前用于区分交叉、T 型、分歧、合流、复杂路口等业务类型。 |
| `grade_2` | SWSD 语义路口等级字段，配合 `kind_2`、拓扑和道路等级进行候选识别与质量判断。 |
| `closed_con` / `closed_connect` | 两者表达同一 SWSD Node 闭合连接语义。`closed_con` 是项目规范字段；`closed_connect` 是正式启用的原始输入别名，由 T08 copy-on-write 归一为 `closed_con`。两字段同时存在时必须值一致，不一致不得继续。当前适用范围为 SWSD Node 输入；不据此扩展 RCSD 字段语义。 |
| `formway` / `Road.formway` | 道路形态语义字段，已用于道路形态判断、through incident degree 裁剪等跨模块判断。 |
| `RCSDRoad.formway` | RCSD 道路形态字段；当前确认 `1024` bit 表示调头口，表达式为 `(formway & 1024) != 0`。 |
| `direction` | 道路方向语义，参与 Segment、通行规则、调头 fallback 等判断；方向不可信时只能审计，不得直接固化强过滤。 |
| `Laneinfo.Arrow_Dir` / T08 `arrow` | SWSD 车道箭头语义；字母型箭头码大小写不敏感，`A/a` 表示 `straight`，数字 `0` 与字母 `o/O` 语义不同。 |
| `restriction` | SWSD 限行 / 禁转语义输入，T09 用于路口通行规则还原。 |
| T05 `T11_MANUAL` relation audit | 人工审计后由 T05 正式发布的正向 relation 来源。T06 Step1 只在 `source_modules/source_module` 包含 `T11_MANUAL`、`relation_status/status=0`、`base_id>0` 且 `graph_consumable=1` 时，用它释放对应 `is_anchor=fail3/fail4` 的旧锚定失败门禁；该语义不改变节点事实，也不是 T06 Step2/Step3 替换白名单。 |
| T12 quality hypothesis | SWSD 与原始 1V1 F-RCSD 在通行性上应等价。该语义用于 raw endpoint topology、portal-constrained semantic carrier、标准路口 portal 和锚点可信度联合质检；semantic carrier 只排除 raw 假断裂，完成排除门禁后仍失败的记录可进入正式问题层，但任何质量结论都不得直接提升为修复规则。 |
| `SWSD Road.patch_id`（P04） | P04 当前确认其为 Patch membership；逗号分隔表示多个 Patch 共同覆盖同一 SWSD Road。它只能限定 Segment 候选证据范围，不构成 Patch Vector 对象级匹配。跨 Patch Segment 必须先统一聚合证据再构建。 |
| `DriveZone_fix / DivStripZone_fix`（P04） | T00 生成的修正版图层：`DriveZone_fix` 与原始 `DriveZone` 业务语义等价，均表示道路面；`DivStripZone_fix` 与原始 `DivStripZone` 业务语义等价，均表示路面导流带，不是 Patch 分区。`fix` 的 per-Patch 生成方式只属于处理与 lineage 事实，不产生新的业务对象类型；P04 不把 raw 与 fix 当两份独立证据重复计权。 |
| `ReferenceLane.FlowNum`（P04） | 当前可用语义为轨迹聚合强度的弱证据，用于 movement 候选排序和审计；不解释为精确车流量、合法通行规则或单独的 accepted 门禁。 |
| `inferred_lane_width_m`（P04） | 通过 Lane 局部垂线分别投影到左右最近且方向/走廊相容的 LaneBoundary，取两侧距离之和形成的几何推导宽度；必须同时记录双侧匹配覆盖率和宽度稳定性，不能由单侧或跨道路 Boundary 补造。 |
| P04 Segment 发布状态 | `hp_full / hp_partial / swsd_retained / conflict_retained`。它描述 Segment carrier 的证据与发布方式，并与 `segment_publishable`、`carrier_takeover_ready`、`replacement_scope`、`review_required` 和 `evidence_quality_state` 分离。`hp_partial` 内的新建 Road 只允许由 `hp_observed + hp_constrained_completion` 组成，不直接拼接 SWSD 坐标；不能满足 hard gate 时整体保留原 carrier 或仅阻断该 Segment，不得以 review 绕过。 |
| P04 Road/Node 连通不变量 | 每个正式 Segment 至少有一条独立 Road；高精证据可区分上下行时必须形成两条连续方向主干链，链可按LaneGroup、物理Node、`junc_nodes`、分流合流和证据边界细分为多条Road，铺装面内无法区分方向时可发布双向Road，非高速主辅路等按T01结构可包含额外方向链和附属Road。SWSD负责完整的逐Segment Access方向与逐Junction Movement拓扑合同，不负责built坐标或Road一一对应；细分后仍按归一化方向链保持该合同。ordinary Junction保留分布式portal Node，同一正确分类JunctionUnit的Node共享mainnodeid，不生成中心聚合点或星形内部Road；其RoadNextRoad由同一ordinary JunctionUnit内方向兼容的进入—离开Road组合编译，并记录两端物理Node与Junction lineage。Segment内部连续性和复杂路口仍要求实际共享Node或显式物理关系；T04复杂路口、环岛和聚合异常不得由mainnode机械全连接。跨Segment被拒Movement显式排除，不自动回退两侧Segment。 |
| P04 历史候选 | M2、冻结 Directional V2 与 High-Precision V3 保留为回归和几何对照，不再作为当前 Segment-first 数据模型。 |

## 字段治理规则

- 外部 GPKG / GeoJSON / Shapefile / CSV / JSON 记录的字段名按 `str(field_name).casefold()` 解析；模块契约中的字段名是 canonical logical name，因此 `snodeid`、`snodeId`、`SNODEID` 只在名称层等价，字段值语义不变。
- 字段名归一化只用于外部字段查找，不得修改原输入或向原属性就地插入 lowercase alias；普通 copy-on-write 输出继续保留原字段名，模块正式输出 schema 继续使用各自契约中的 canonical 名称。T01 working layer、T06 内部 feature 和 P01 内部模型按各自契约在独立副本中发布 lowercase canonical keys，属于显式 canonicalization，不得回写输入文件。
- 同一记录存在多个仅大小写不同的原字段时，相同非空值或单一非空值可归并读取；不同非空值必须以字段冲突显式失败，不得按遍历顺序 silent fix。
- 大小写归一化不得自动扩展业务别名；`startNodeId` 是否等价于 `snodeid` 仍必须由项目或模块契约正式声明。模块自产 handoff / audit 字典继续使用精确 canonical key，避免掩盖模块间契约拼写错误。
- 未在项目或模块源事实中正式启用的字段，不得进入 Step1 / Step2 强规则。
- 字段正式启用时，必须说明可用语义、适用范围和未确认边界，并同步写入对应模块契约。
- 禁止基于局部样本、人工真值或单次冒烟结果反推字段含义并固化为强规则。
- 当数据现象与已确认字段语义冲突时，应先形成审计证据并回到契约层裁定。

## 术语

| 术语 | 含义 |
|---|---|
| SWSD | 现场语义道路数据源。 |
| RCSD | 场景路网承载数据源。 |
| F-RCSD | 融合 SWSD Segment 替换成果后的 RCSD 承载数据。 |
| 语义路口 | 以 SWSD node 组织的路口级业务对象。 |
| 虚拟锚定 | 基于道路面、导流带、SWSD、RCSD 等证据构建的路口关系锚定成果。 |
| 文件证据包 | 用于本地 case 分析、内外网协作和结果复核的文件化证据集合。 |
