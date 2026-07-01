# Spec：T11 QGIS 人工 Relation 审计插件

## 1. 目标

为 T11 当前两张 Segment relation 缺口审计 Excel 提供 QGIS 地图化编辑入口：

- `t11_unreplaced_segments_all_junctions_have_evidence_relation_gaps.xlsx`
- `t11_unreplaced_segments_with_no_evidence_junction_relation_gaps.xlsx`

插件用于定位、查看、点选 RCSDNode / RCSDRoad 并即时同步人工字段到 Excel。Excel 仍是最终事实源；插件和辅助索引只服务于定位、渲染、图层绑定和编辑体验。

## 2. 非目标

- 不替代 Excel 成为人工结果事实源。
- 不泛化为 T08 tool6 或其它质量审计平台。
- 不修改 T05/T06/T09 业务规则。
- 不把人工候选直接变成 T06 白名单。
- 不新增 repo CLI 子命令或 scripts 包装入口。
- 不修补、snap、裁剪或重构任何输入几何。

## 3. 用户场景

### 产品视角

人工审计人员在 QGIS 中加载 SWSD Segment、SWSD 语义路口、RCSDRoad、RCSDNode 与 T11 Excel/辅助任务索引后，可以：

1. 在 Dock Panel 中按优先级分页浏览唯一 `target_id` 任务。
2. 点击任务定位到 SWSD 语义路口或 Segment 上下文。
3. 从 QGIS 当前选择提取 RCSDNode / RCSDRoad ID。
4. 手动编辑 `manual_relation_type`、`selected_ids`、`comment`。
5. 每次改动立即同步写入对应 Excel 第一条可消费行。

### 架构视角

插件分两层：

1. `src/rcsd_topo_poc/modules/t11_manual_relation_review/qgis_review/`：纯 Python 核心，负责 Excel 读写、任务去重排序、selected_ids 规范化和图层绑定校验。
2. `qgis_plugins/t11_relation_review/`：QGIS 插件薄封装，负责 Dock UI、QGIS 图层选择、地图定位、高亮和 selection 提取。

QGIS 层不得复制 Excel 事实；每次用户编辑都调用核心同步器写回 Excel。

### 研发视角

核心逻辑必须可在无 QGIS 环境下单测。QGIS 插件只依赖 QGIS/PyQt API，不引入新的 repo runtime 依赖。

### 测试看点

- 两张 Excel 都能读取。
- 任务列表按优先级排序并按 `target_id` 去重。
- 重复 `target_id` 只写首个 Excel 行。
- `NULL` 字符串识别为人工确认无有效关系。
- junction selection 使用 RCSDNode `mainnodeid`，空 / `0` / `NULL` 时回退 `id`。
- road selection 使用 RCSDRoad `id`。
- 写入只改 `manual_relation_type / selected_ids / comment`。
- 图层绑定校验覆盖数据源路径、CRS 和必需字段。

### QA 视角

若本机可用 QGIS/PyQGIS，执行插件 import / metadata 级验证；否则必须完成可替代自检并明确未执行原因。

## 4. 人工字段语义

人工字段：

```text
manual_relation_type
selected_ids
comment
```

含义：

- 空值：未填写，表示待审计。
- `selected_ids=NULL`：人工确认没有有效关系。
- `comment`：人工自由文本，插件不自动追加时间戳或来源。

支持 relation 类型：

```text
1v1_rcsd_junction
1vN_rcsd_junction
1v1_rcsd_road
1vN_rcsd_road
no_valid_relation
uncertain
```

多选 ID 使用 `|` 拼接，写入前去空、去重、保持首次出现顺序。

## 5. 重复路口策略

Excel 继续保留 Segment 维度完整行。插件任务列表按 `target_id` 去重：

- 同一 `target_id` 在多个 Segment 行出现时，只显示排序后的第一条。
- 人工结果只写这条任务记录指向的 Excel 行。
- 后续重复行不展示、不写入。
- 该策略与当前 T05 消费机制一致，最终只按路口消费人工结果。

## 6. 图层绑定规则

插件只绑定和校验 QGIS 图层，不接管图层样式、顺序或渲染：

```text
T11 task/helper layer
SWSD Segment layer
SWSD semantic junction layer
RCSDRoad layer
RCSDNode layer
```

必需字段：

```text
Task/helper: workbook_path, sheet_name, excel_row, target_id, swsd_segment_id
SWSD Segment: id
SWSD semantic junction: id
RCSDRoad: id
RCSDNode: id, mainnodeid
```

校验项：

- 数据源路径与插件读取路径一致。
- CRS 存在；CRS 不一致时必须显式提示需要 QGIS 坐标变换，不 silent fix。
- 必需字段存在。
- 绑定图层与当前任务/选择的 relation 类型匹配。

## 7. GIS / 拓扑质量边界

- CRS 与坐标变换：插件记录并校验 CRS；定位和高亮依赖 QGIS 渲染坐标变换。
- 拓扑一致性：插件不修补拓扑、不自动 snap、不改写几何。
- 几何语义：SWSD 语义路口用于定位待审计对象，RCSDNode/RCSDRoad selection 用于人工 relation ID。
- 审计可追溯性：每个任务保留 `workbook_path / sheet_name / excel_row / target_id / swsd_segment_id`。
- 性能可验证性：任务读取按 Excel 行流式解析，分页默认 50 条；单次写入只重写目标 workbook 包。
