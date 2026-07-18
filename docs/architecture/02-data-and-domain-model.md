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
| T12 quality hypothesis | SWSD 与原始 1V1 F-RCSD 在通行性上应等价。该语义只用于生成待复核质量候选，未经过数据验证和人工 review decisions 时不得提升为修复规则。 |

## 字段治理规则

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
