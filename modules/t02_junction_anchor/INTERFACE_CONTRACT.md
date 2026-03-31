# T02 - INTERFACE_CONTRACT

## 定位

- 本文件是 `t02_junction_anchor` 的稳定契约面。
- 当前业务需求对齐与 accepted baseline 以 `architecture/06-accepted-baseline.md` 为准。
- 模块目标、上下文、构件关系与风险说明以 `architecture/*` 为准。
- `README.md` 只承担操作者入口职责，不替代长期源事实。

## 1. 目标与范围

- 模块 ID：`t02_junction_anchor`
- 长期目标：
  - 为双向 Segment 相关路口锚定提供稳定、可审计的下游模块基础
- 当前正式范围：
  - stage1 `DriveZone / has_evd gate`
  - stage2 anchor recognition / anchor existence 最小闭环
  - stage3 `virtual intersection anchoring` baseline
  - `t02-virtual-intersection-poc` baseline 入口：
    - 默认 `case-package`
    - 可显式切换 `--input-mode full-input`
  - 单 / 多 `mainnodeid` 文本证据包支撑入口
  - 独立离线修复工具 `t02-fix-node-error-2`
  - 消费 T01 `segment` 与 `nodes`
  - 消费 `DriveZone`、`RCSDIntersection`、`roads`、`RCSDRoad`、`RCSDNode`
  - 产出 `nodes.has_evd`、`nodes.is_anchor`、`segment.has_evd`、`summary`、`audit/log` 与 stage3 产物
- 当前不在正式范围：
  - 最终唯一锚定决策闭环
  - 正式产线级全量虚拟路口批处理
  - 候选生成 / 候选打分
  - 概率 / 置信度实现
  - 候选概率校准
  - 误伤捞回
  - 环岛新业务规则

## 2. Inputs

### 2.1 必选输入

- `segment`
- `nodes`
- `DriveZone`
- `RCSDIntersection`（stage2 anchor recognition 基线输入）

### 2.2 可选输入兼容参数

- `segment_layer`
- `nodes_layer`
- `drivezone_layer`
- `segment_crs`
- `nodes_crs`
- `drivezone_crs`

说明：

- 输入兼容 `GeoPackage(.gpkg)`、`GeoJSON` 与 `Shapefile`；历史 `.gpkt` 后缀仅做兼容读取。
- 若同名 `.gpkg` 与 `.geojson` 同时存在，默认优先读取 `GeoPackage`。
- 对 GeoJSON，若源文件缺失 CRS，则必须显式传入对应 CRS override，否则执行失败。
- 对 Shapefile，若无 `.prj`，也必须显式传入对应 CRS override，否则执行失败。

### 2.3 输入前提

- `segment` 与 `nodes` 必须来自同一轮、可相互追溯的 T01 成果。
- `segment` 必须具备：
  - `id`
  - `pair_nodes`
  - `junc_nodes`
  - `s_grade` 或 `sgrade`
- `nodes` 必须具备：
  - `id`
  - `mainnodeid`
  - 可用 geometry
- `DriveZone` 必须具备可用于“落入或边界接触”判断的面状 geometry。
- `RCSDIntersection` 必须具备可用于“落入或边界接触”判断的面状 geometry。
- `nodes`、`DriveZone` 与 `RCSDIntersection` 在空间判定前必须统一到 `EPSG:3857`。
- 当前实现为保持输出一致性，也会将 `segment` 输出 geometry 统一写到 `EPSG:3857`。

### 2.4 实际输入字段冻结

#### `segment`

- 主键字段：`id`
- 路口字段：`pair_nodes`
- 路口字段：`junc_nodes`
- 分桶逻辑字段：`s_grade` 或 `sgrade`

#### `nodes`

- 主键字段：`id`
- junction 分组字段：`mainnodeid`

说明：

- 文档中仍可使用“mainnode”作为业务概念名。
- stage1 实际输入字段冻结为 `mainnodeid`。
- `working_mainnodeid` 不作为 stage1 正式输入字段。
- `s_grade / sgrade` 是输入兼容映射，不代表要求 T01 改历史产物。

### 2.5 Stage1 处理契约

- 路口来源：
  - 只认 `pair_nodes` 与 `junc_nodes`
- 单 `segment` 去重：
  - 先解析 `pair_nodes + junc_nodes`
  - 再在单个 `segment` 内去重
- 路口组装：
  1. 先查 `mainnodeid = J`
  2. 若不存在，再查 `mainnodeid = NULL 且 id = J`
- 代表 node：
  - 若 `mainnodeid = J` 成组，则组内 `id = J` 的 node 为代表 node
  - 若代表 node 缺失，记 `representative_node_missing`，不允许 fallback
  - 环岛场景当前继承 T01 既有逻辑，不由 T02 自行扩写
- DriveZone 判定：
  - `nodes` 与 `DriveZone` 在 `EPSG:3857` 下做空间关系判断
  - 任一组内 node 落入或接触 `DriveZone` 边界，即 `has_evd = yes`
- 路口组不存在：
  - 记 `junction_nodes_not_found`
  - 业务结果按 `has_evd = no`
- 空目标路口 `segment`：
  - `segment.has_evd = no`
  - `reason = no_target_junctions`
- `segment.has_evd`：
  - 只有去重后的全部目标路口都为 `yes`，才记 `yes`
- `summary`：
  - 仅按 `0-0双 / 0-1双 / 0-2双` 分桶
  - 桶内路口按唯一 ID 统计，不按 `segment-路口` 展开重复计数
  - 同时补充总汇总项 `all__d_sgrade`
  - `all__d_sgrade` 统计所有 `s_grade` 非空的 `segment`
  - `all__d_sgrade` 与单桶保持相同统计项与统计口径

### 2.6 Stage2 处理基线

- 阶段二当前业务定位冻结为：双向 Segment 相关路口的 anchor recognition / anchor existence。
- 阶段二仅处理 `has_evd = yes` 的路口组。
- `has_evd != yes` 的组不进入 stage2，代表 node 的 `is_anchor = null`。
- 阶段二当前为补充 summary，正式读取：
  - `segment.id`
  - `segment.pair_nodes`
  - `segment.junc_nodes`
  - `segment.s_grade` 或 `segment.sgrade`
- `segment` 在 stage2 只用于 summary 统计，不用于重算 `has_evd` 或 `is_anchor`。
- `nodes` 全表新增字段：
  - `is_anchor`
  - `anchor_reason`
- `is_anchor` 与 `anchor_reason` 只对代表 node 写值；同组其它从属 node 与非代表 node 保持 `null`。
- `is_anchor` 允许值冻结为：
  - `yes`
  - `no`
  - `fail1`
  - `fail2`
  - `null`
- `anchor_reason` 当前最小值域冻结为：
  - `roundabout`
  - `t`
  - `null`
- 阶段二使用 `RCSDIntersection` 做路口面判定。
- 与 stage1 一致，边界接触也算成功。
- 阶段二空间处理同样统一在 `EPSG:3857` 下进行。
- 若目标 `junction` 组（仅限 `has_evd = yes`）任一 node 落入或接触任一 `RCSDIntersection` 面：
  - 该组代表 node 进入命中态
  - 但仍需继续检查 `fail1 / fail2`
- 若该组所有 node 均未落入任何 `RCSDIntersection` 面：
  - 该组代表 node 的 `is_anchor = no`
- 单节点组若落入多个 `RCSDIntersection` 面：
  - 代表 node 的 `is_anchor = yes`
  - `anchor_reason = null`
  - 不输出 `node_error_1`
- `kind_2 = 64` 且组内所有 node 均落入任意 `RCSDIntersection` 面：
  - 代表 node 的 `is_anchor = yes`
  - `anchor_reason = roundabout`
  - 不输出 `node_error_1`
- `kind_2 = 2048` 且组内所有 node 均落入任意 `RCSDIntersection` 面：
  - 代表 node 的 `is_anchor = yes`
  - `anchor_reason = t`
  - 不输出 `node_error_1`
- `node_error_1`：
  - 对未命中上述豁免规则的组，若同一组 node 落入两个不同的 `RCSDIntersection` 面
  - 该组代表 node 的 `is_anchor = fail1`
- 需同时保留 GeoPackage(.gpkg) 与审计表
- `node_error_2`：
  - 用 `RCSDIntersection` 反向包含选择路口 node
  - 若一个 `RCSDIntersection` 面对应不止一组 node，则先忽视代表 node `kind_2 = 1` 的组
  - 过滤后若剩余组数大于 1，则这些组对应代表 node 的 `is_anchor = fail2`
  - 过滤后若剩余组数仅为 1，则该面不再对该组触发 `node_error_2 / fail2`
- 需同时保留 GeoPackage(.gpkg) 与审计表
- 优先级冻结为：
  - `fail2` 优先于 `fail1`
- 若同一组同时命中新豁免规则与 `node_error_2`
- 则代表 node 的 `is_anchor = fail2`
- `anchor_reason = null`
- 同时仍保留相应 `node_error_2` 审计输出
- 若同一组同时命中 `node_error_1` 与 `node_error_2`
- 则代表 node 的 `is_anchor = fail2`
- 同时仍保留相应审计输出

### 2.6A T02 阶段串联

- 当前 T02 基线流程固定为：
  1. stage1：`DriveZone / has_evd gate`
  2. stage2：`anchor recognition / anchor existence`
  3. stage3：`virtual intersection anchoring`
- stage3 不重算 stage1 / stage2：
  - 直接消费已带 `has_evd / is_anchor / kind_2 / grade_2` 的 `nodes`
- stage3 当前默认处理目标为：
  - `has_evd = yes`
  - `is_anchor = no`
  - `kind_2 in {4, 2048}`
- stage3 之后可按需调用文本证据包入口做单 case 外部复现，但文本证据包不是新的业务阶段。

### 2.7 Stage3 虚拟路口锚定 baseline 输入与前提

- `case-package` 模式必选输入：
  - `nodes`
  - `roads`
  - `DriveZone`
  - `RCSDRoad`
  - `RCSDNode`
  - `mainnodeid`
- `full-input` 模式必选输入：
  - `nodes`
  - `roads`
  - `DriveZone`
  - `RCSDRoad`
  - `RCSDNode`
- `full-input` 模式中：
  - 传 `mainnodeid` 时执行单点验证
  - 不传 `mainnodeid` 时自动识别 stage3 候选
- 可选兼容参数：
  - `nodes_layer / roads_layer / drivezone_layer / rcsdroad_layer / rcsdnode_layer`
  - `nodes_crs / roads_crs / drivezone_crs / rcsdroad_crs / rcsdnode_crs`
- 可选 patch 参数：
  - `buffer_m`
  - `patch_size_m`
  - `resolution_m`
- `nodes` 必须包含：
  - `id`
  - `mainnodeid`
  - `has_evd`
  - `is_anchor`
  - `kind_2`
  - `grade_2`
- `roads` 与 `RCSDRoad` 当前正式依赖：
  - `id`
  - `snodeid`
  - `enodeid`
  - `direction`
- `RCSDNode` 必须包含：
  - `id`
  - `mainnodeid`
- case-package 是 baseline regression 入口，不允许回退。
- full-input 是当前正式 baseline 入口，用于：
  - 完整数据 + 指定 `mainnodeid`
  - 完整数据 + 自动识别未锚定且有资料的路口
- 代表 node 的 stage3 baseline 前提：
  - `has_evd = yes`
  - `kind_2 in {4, 2048}`
  - 非 `review_mode` 下，`is_anchor = no`
- 所有空间处理必须统一到 `EPSG:3857`；不得以隐式默认 CRS 掩盖数据问题。

### 2.8 Stage3 虚拟路口锚定 baseline 处理契约

- `case-package` 模式只处理单个 `mainnodeid`。
- `full-input` 模式统一两类业务诉求：
  - 完整数据 + 指定 `mainnodeid`
  - 完整数据 + 自动识别候选
- 当前路口组 own-group nodes 必须纳入 polygon，不能只作为分析输入。
- `associated_rcsdroad.gpkg / associated_rcsdnode.gpkg` 与 `polygon-support` 允许解耦：
  - association 可以保守
  - `polygon-support` 可以保留更完整的局部 RC 连通组件
- 若 RC 不存在与 roads 同方向的有效局部分支，不得拿其它横向或直行 RC 组件替代。
- 最终 polygon 必须通过 support validation：
  - own-group nodes 必须被覆盖
  - `polygon-support` 中声明的 RCSDNode / RCSDRoad 必须被合理覆盖
- 对 nodes 与 RCSD 拓扑无法同时满足的场景，必须明确失败或风险标记，不得 silent fix。
- `review_mode` 仅用于分析和人工复核：
  - 可绕过代表 node `is_anchor` gate
  - 可将 RC outside DriveZone 从硬失败改成风险记录 + 软排除
  - 不改变正式契约的默认边界

### 2.9 full-input 统一入口附加契约

- `t02-virtual-intersection-poc --input-mode full-input` 统一以下两类诉求：
  - 完整数据入口 + 指定 `mainnodeid`
  - 完整数据入口 + 自动识别候选 `mainnodeid`
- full-input 模式下：
  - 传 `mainnodeid` 时执行单点验证
  - 不传 `mainnodeid` 时，从完整 `nodes` 自动识别候选
- 自动识别候选当前冻结为：
  - 代表 node
  - `has_evd = yes`
  - `is_anchor = no`
  - `kind_2 in {4, 2048}`
- full-input 模式支持：
  - `max_cases`：限制自动识别后最多处理的候选数量
  - `workers`：并行 case worker 数量
- `workers` 只能改变调度性能，不得改变语义结果；批次汇总必须保持稳定排序和可复现。
- full-input 模式必须先输出 `preflight.json`，至少记录：
  - `path`
  - `layer`
  - `feature_count`
  - `source_crs`
  - `crs_source`
  - `bounds`
- full-input 模式不得用硬编码 `EPSG:3857` 覆盖全量输入 CRS；必须优先读取输入自带 CRS，multi-layer GeoPackage 不能静默猜层。

## 3. Outputs

### 3.1 官方输出目录

- 官方默认工作输出根目录为：

```text
outputs/_work/t02_stage1_drivezone_gate
```

- 若显式传入 `--out-root`，其语义也是“工作输出根目录”。
- 无论是否显式传入 `--out-root`，本次运行的最终输出目录都固定为：

```text
<out_root>/<run_id>
```

- stage1 的官方工作输出应落在 repo `outputs/_work/` 体系下；若因受控集成场景需要显式覆盖 `--out-root`，也必须保持 `run_id` 叶子目录隔离。

### 3.2 正式输出文件

- `nodes.gpkg`
- `segment.gpkg`
- `t02_stage1_summary.json`
- `t02_stage1_audit.csv`
- `t02_stage1_audit.json`
- `t02_stage1.log`
- `t02_stage1_progress.json`
- `t02_stage1_perf.json`
- `t02_stage1_perf_markers.jsonl`
- `virtual_intersection_polygon.gpkg`
- `branch_evidence.json`
- `branch_evidence.gpkg`
- `associated_rcsdroad.gpkg`
- `associated_rcsdroad_audit.csv`
- `associated_rcsdroad_audit.json`
- `associated_rcsdnode.gpkg`
- `associated_rcsdnode_audit.csv`
- `associated_rcsdnode_audit.json`
- `t02_virtual_intersection_poc_status.json`
- `t02_virtual_intersection_poc_audit.csv`
- `t02_virtual_intersection_poc_audit.json`
- `t02_virtual_intersection_poc.log`
- `t02_virtual_intersection_poc_progress.json`
- `t02_virtual_intersection_poc_perf.json`
- `t02_virtual_intersection_poc_perf_markers.jsonl`
- `t02_single_case_bundle.txt`

### 3.3 输出语义

#### `nodes.gpkg`

- 继承输入 `nodes` properties
- 新增字段：`has_evd`
- 阶段二文档基线新增字段：`is_anchor`、`anchor_reason`
- `is_anchor` 值域：`yes / no / fail1 / fail2 / null`
- `anchor_reason` 当前最小值域：`roundabout / t / null`
- 只有代表 node 写 `has_evd / is_anchor / anchor_reason`
- 非代表 node 保持 `null`
- 输出 geometry CRS：`EPSG:3857`

说明：

- `has_evd` 是 stage1 gate 字段。
- `is_anchor` 与 `anchor_reason` 是 stage2 anchor recognition 字段。
- `is_anchor` 业务值域冻结为 `yes / no / fail1 / fail2 / null`。
- `anchor_reason` 当前最小值域冻结为 `roundabout / t / null`。

#### `segment.gpkg`

- 继承输入 `segment` properties
- 新增字段：`has_evd`
- 值域：`yes / no`
- 输出 geometry CRS：`EPSG:3857`

#### `t02_stage1_summary.json`

- 包含：
  - `run_id`
  - `success`
  - `target_crs`
  - `inputs`
  - `counts`
  - `summary_by_s_grade`
  - `summary_by_kind_grade`
  - `output_files`
- `summary_by_s_grade` 每桶至少包含：
  - `segment_count`
  - `segment_has_evd_count`
  - `junction_count`
  - `junction_has_evd_count`
- 除 `0-0双 / 0-1双 / 0-2双` 外，还需包含：
  - `all__d_sgrade`
- `all__d_sgrade` 的统计含义是：
  - 所有 `s_grade` 非空的 `segment`
  - 路口按唯一路口 ID 计数
  - 不按 `segment-路口` 展开重复计数
- `summary_by_kind_grade` 固定包含：
  - `kind2_4_64_grade2_1`
  - `kind2_4_64_grade2_0_2_3`
  - `kind2_2048`
  - `kind2_8_16`
- `summary_by_kind_grade` 每个 bucket 至少包含：
  - `junction_count`
  - `junction_has_evd_count`
- `summary_by_kind_grade` 的统计对象是阶段一目标路口全集，按 `junction_id` 唯一值计数。
- 分类依据以代表 node 的 `kind_2 / grade_2` 为准：
  - `kind_2 in {4, 64} and grade_2 = 1` -> `kind2_4_64_grade2_1`
  - `kind_2 in {4, 64} and grade_2 in {0, 2, 3}` -> `kind2_4_64_grade2_0_2_3`
  - `kind_2 = 2048` -> `kind2_2048`
  - `kind_2 in {8, 16}` -> `kind2_8_16`
- 代表 node 无法确定、`kind_2 / grade_2` 缺失或不落入上述四类时，不新增正式 bucket，仅输出未分类数量提示。

#### `t02_stage1_audit.csv / t02_stage1_audit.json`

- 稳定字段：
  - `scope`
  - `segment_id`
  - `junction_id`
  - `status`
  - `reason`
  - `detail`
- 当前冻结 reason：
  - `junction_nodes_not_found`
  - `representative_node_missing`
  - `no_target_junctions`
  - `missing_required_field`
  - `invalid_crs_or_unprojectable`

#### stage2 逻辑错误输出

- `node_error_1`
  - 逻辑含义：同一组 node 落入两个不同的 `RCSDIntersection` 面
  - 对应代表 node 的 `is_anchor = fail1`
  - 输出形态必须同时保留：
    - GeoPackage(.gpkg)
    - 审计表
- `node_error_2`
  - 逻辑含义：一个 `RCSDIntersection` 面对应不止一组 node
  - 对应代表 node 的 `is_anchor = fail2`
  - 输出形态必须同时保留：
    - GeoPackage(.gpkg)
    - 审计表
- 具体文件命名与最小字段集待后续实现任务书确认。

#### `t02_stage2_summary.json`

- 顶层至少包含：
  - `run_id`
  - `success`
  - `target_crs`
  - `inputs`
  - `counts`
  - `anchor_summary_by_s_grade`
  - `anchor_summary_by_kind_grade`
  - `output_files`
- 语义冻结：
  - “资料” = `has_evd = yes`
  - “锚定” = `is_anchor = yes`
  - `fail1 / fail2 / no / null` 都不计为“被锚定”
- `anchor_summary_by_s_grade` 固定包含：
  - `0-0双`
  - `0-1双`
  - `0-2双`
  - `all__d_sgrade`
- `anchor_summary_by_s_grade` 每个 bucket 至少统计：
  - `total_segment_count`
  - `pair_nodes_all_anchor_segment_count`
  - `pair_and_junc_nodes_all_anchor_segment_count`
- 统计口径：
  - `pair_nodes_all_anchor_segment_count` 仅检查单个 `segment` 去重后的 `pair_nodes` 集合
  - 集合必须非空且全部 `is_anchor = yes` 才计为成功
  - `pair_and_junc_nodes_all_anchor_segment_count` 检查单个 `segment` 去重后的 `pair_nodes + junc_nodes` 并集
  - 并集必须非空且全部 `is_anchor = yes` 才计为成功
  - `all__d_sgrade` 统计所有 `s_grade` 非空的 `segment`
- `anchor_summary_by_kind_grade` 固定包含：
  - `kind2_4_64_grade2_1`
  - `kind2_4_64_grade2_0_2_3`
  - `kind2_2048`
  - `kind2_8_16`
- `anchor_summary_by_kind_grade` 每个 bucket 至少统计：
  - `evidence_junction_count`
  - `anchored_junction_count`
- 分类与计数口径：
  - 统计对象是阶段二目标路口的代表 node
  - 只统计 `has_evd = yes` 的路口
  - `kind_2 in {4, 64} and grade_2 = 1` -> `kind2_4_64_grade2_1`
  - `kind_2 in {4, 64} and grade_2 in {0, 2, 3}` -> `kind2_4_64_grade2_0_2_3`
  - `kind_2 = 2048` -> `kind2_2048`
  - `kind_2 in {8, 16}` -> `kind2_8_16`
  - `anchored_junction_count` 仅统计 `is_anchor = yes`
  - 代表 node 无法确定、`kind_2 / grade_2` 缺失或未落入四类时，不新增正式 bucket，仅记未分类数量提示

#### `t02_stage1.log`

- 记录运行开始、输入读取、关键计数与输出目录

#### `t02_stage1_progress.json`

- 当前运行阶段快照
- 至少包含：
  - `run_id`
  - `status`
  - `updated_at`
  - `current_stage`
  - `message`
  - `counts`

#### `t02_stage1_perf.json`

- 本次运行的性能摘要
- 至少包含：
  - `run_id`
  - `success`
  - `total_wall_time_sec`
  - `counts`
  - `stage_timings`

#### `t02_stage1_perf_markers.jsonl`

- 阶段级性能标记流
- 每条记录至少包含：
  - `event`
  - `run_id`
  - `at`
  - `stage`
  - `elapsed_sec`
  - `counts`

#### Stage3 单 case 输出

- `virtual_intersection_polygon.gpkg`
  - 单 `mainnodeid` 生成的虚拟路口面
- `branch_evidence.json / branch_evidence.gpkg`
  - 分支方向、证据强弱、是否纳入 polygon 与 RC 分组
- `associated_rcsdroad.gpkg / associated_rcsdnode.gpkg`
  - 保守 association 结果
- `associated_rcsdroad_audit.csv / .json`
- `associated_rcsdnode_audit.csv / .json`
  - RC 关联审计
- `t02_virtual_intersection_poc_status.json`
  - 顶层至少包含：
    - `success`
    - `status`
    - `mainnodeid`
    - `review_mode`
    - `inputs`
    - `counts`
    - `risks`
    - `output_files`
- `t02_virtual_intersection_poc_audit.csv / .json`
  - 单 case 审计
- `t02_virtual_intersection_poc.log`
- `t02_virtual_intersection_poc_progress.json`
- `t02_virtual_intersection_poc_perf.json`
- `t02_virtual_intersection_poc_perf_markers.jsonl`
  - 运行、进度与性能输出
- `debug` 开启时：
  - 正式结果目录仍固定为 `<out_root>/<run_id>`
  - debug render 批次目录固定为批次根目录 `_rendered_maps/`

#### Stage3 full-input 根目录输出

- 根目录仍固定为 `<out_root>/<run_id>`
- `cases/<mainnodeid>/...`
  - 保留单 case worker 原始输出，便于审计与回溯
- `virtual_intersection_polygons.gpkg`
  - 汇总本批成功生成的虚拟路口面
- `_rendered_maps/`
  - 汇总本批 render PNG，便于集中目视复核
- `preflight.json`
  - 记录 full-input 图层路径、layer、feature_count、CRS 与 bounds
- `summary.json`
  - 记录模式、候选发现、selected/skipped case 列表、逐 case 状态与输出路径
- `perf_summary.json`
  - 记录批次级 wall time 汇总与逐 case 耗时
- `t02_virtual_intersection_full_input_poc.log`
- `t02_virtual_intersection_full_input_poc_progress.json`

#### 单 / 多 `mainnodeid` 文本证据包

- `t02_single_case_bundle.txt`
  - 单 `mainnodeid` 文本证据包
- `t02_multi_case_bundle.txt`
  - 多 `mainnodeid` 文本证据包；解包后按 `<mainnodeid>/` 展开多个 case 目录
- 内含最少文件：
  - `manifest.json`
  - `drivezone_mask.png`
  - `drivezone.gpkg`
  - `nodes.gpkg`
  - `roads.gpkg`
  - `rcsdroad.gpkg`
  - `rcsdnode.gpkg`
  - `size_report.json`

#### Stage3 状态与失败口径

- 稳定状态枚举：
  - `stable`
  - `surface_only`
  - `weak_branch_support`
  - `ambiguous_rc_match`
  - `no_valid_rc_connection`
  - `node_component_conflict`
- review 风险枚举：
  - `review_anchor_gate_bypassed`
  - `review_rc_outside_drivezone_excluded`
- 明确失败原因至少包含：
  - `anchor_support_conflict`
  - `missing_required_field`
  - `invalid_crs_or_unprojectable`
  - `representative_node_missing`
  - `mainnodeid_not_found`
  - `mainnodeid_out_of_scope`
  - `main_direction_unstable`
  - `rc_outside_drivezone`

## 4. EntryPoints

### 4.1 官方入口

```bash
python -m rcsd_topo_poc t02-stage1-drivezone-gate --help
python -m rcsd_topo_poc t02-stage2-anchor-recognition --help
```

### 4.2 Stage3 与支撑入口

```bash
python -m rcsd_topo_poc t02-virtual-intersection-poc --help
python -m rcsd_topo_poc t02-export-text-bundle --help
python -m rcsd_topo_poc t02-decode-text-bundle --help
```

- `t02-virtual-intersection-poc` 是当前 stage3 baseline 官方入口
- 默认 `input_mode = case-package`，保持既有 case-package baseline 行为不回退
- `--input-mode full-input` 打开统一全量输入 baseline：
  - 传 `--mainnodeid`：完整数据 + 指定路口
  - 不传 `--mainnodeid`：完整数据 + 自动识别候选
- 不重算 stage1 / stage2，只消费其结果字段
- 该入口直接消费带 `has_evd / is_anchor` 的 `nodes`，不会在入口内部重算 stage1 / stage2 主逻辑

### 4.3 程序内入口

- [stage1_drivezone_gate.py](/mnt/e/Work/RCSD_Topo_Poc/src/rcsd_topo_poc/modules/t02_junction_anchor/stage1_drivezone_gate.py)
  - `run_t02_stage1_drivezone_gate(...)`
  - `run_t02_stage1_drivezone_gate_cli(args)`
- [stage2_anchor_recognition.py](/mnt/e/Work/RCSD_Topo_Poc/src/rcsd_topo_poc/modules/t02_junction_anchor/stage2_anchor_recognition.py)
  - `run_t02_stage2_anchor_recognition(...)`
  - `run_t02_stage2_anchor_recognition_cli(args)`
- `src/rcsd_topo_poc/modules/t02_junction_anchor/virtual_intersection_poc.py`
  - `run_t02_virtual_intersection_poc(...)`
  - `run_t02_virtual_intersection_poc_cli(args)`
- [virtual_intersection_full_input_poc.py](/mnt/e/Work/RCSD_Topo_Poc/src/rcsd_topo_poc/modules/t02_junction_anchor/virtual_intersection_full_input_poc.py)
  - `run_t02_virtual_intersection_full_input_poc(...)`
  - `run_t02_virtual_intersection_full_input_poc_cli(args)`
- [text_bundle.py](/mnt/e/Work/RCSD_Topo_Poc/src/rcsd_topo_poc/modules/t02_junction_anchor/text_bundle.py)
  - `run_t02_export_text_bundle(...)`
  - `run_t02_decode_text_bundle(...)`

## 5. Params

### 5.1 关键参数类别

- 输入路径：
  - `segment_path`
  - `nodes_path`
  - `drivezone_path`
- 输入兼容参数：
  - `segment_layer`
  - `nodes_layer`
  - `drivezone_layer`
  - `segment_crs`
  - `nodes_crs`
  - `drivezone_crs`
- 输出控制：
  - `out_root`
  - `run_id`

### 5.2 Stage3 参数

- 必选输入：
  - `nodes_path`
  - `roads_path`
  - `drivezone_path`
  - `rcsdroad_path`
  - `rcsdnode_path`
  - `mainnodeid`
- 可选兼容：
  - `nodes_layer / roads_layer / drivezone_layer / rcsdroad_layer / rcsdnode_layer`
  - `nodes_crs / roads_crs / drivezone_crs / rcsdroad_crs / rcsdnode_crs`
- 可选 patch 控制：
  - `buffer_m`
  - `patch_size_m`
  - `resolution_m`
- 输出控制：
  - `out_root`
  - `run_id`
- 复核辅助：
  - `debug`
  - `debug_render_root`
  - `review_mode`

### 5.3 参数原则

- 所有输入兼容都必须显式声明；不能猜字段、猜 CRS、猜 fallback。
- stage1 当前没有业务阈值参数，也不开放 stage2 相关参数。
- stage2 当前已实现最小必要参数，不补写最终锚定决策参数。
- 本文件只固化长期参数类别与语义，不复制完整 CLI 参数表。

## 6. Examples

```bash
python -m rcsd_topo_poc t02-stage1-drivezone-gate \
  --segment-path /mnt/d/TestData/POC_Data/first_layer_road_net_v0/T01/segment.gpkg \
  --nodes-path /mnt/d/TestData/POC_Data/first_layer_road_net_v0/T01/nodes.gpkg \
  --drivezone-path /mnt/d/TestData/POC_Data/patch_all/DriveZone.gpkg \
  --out-root /mnt/d/Work/RCSD_Topo_Poc/outputs/_work/t02_stage1_drivezone_gate \
  --run-id t02_stage1_run
```

```bash
python -m rcsd_topo_poc t02-virtual-intersection-poc \
  --nodes-path /mnt/d/TestData/POC_Data/first_layer_road_net_v0/T02/stage2/nodes.gpkg \
  --roads-path /mnt/d/TestData/POC_Data/first_layer_road_net_v0/T01/roads.gpkg \
  --drivezone-path /mnt/d/TestData/POC_Data/patch_all/DriveZone.gpkg \
  --rcsdroad-path /mnt/d/TestData/POC_Data/patch_all/RCSDRoad.gpkg \
  --rcsdnode-path /mnt/d/TestData/POC_Data/patch_all/RCSDNode.gpkg \
  --mainnodeid 100 \
  --out-root /mnt/d/Work/RCSD_Topo_Poc/outputs/_work/t02_virtual_intersection_poc \
  --debug-render-root /mnt/d/Work/RCSD_Topo_Poc/outputs/_work/t02_virtual_intersection_poc_debug/_rendered_maps \
  --run-id t02_virtual_intersection_demo
```

```bash
python -m rcsd_topo_poc t02-virtual-intersection-poc \
  --input-mode full-input \
  --nodes-path /mnt/d/TestData/POC_Data/first_layer_road_net_v0/T02/nodes.gpkg \
  --roads-path /mnt/d/TestData/POC_Data/first_layer_road_net_v0/T02/roads.gpkg \
  --drivezone-path /mnt/d/TestData/POC_Data/patch_all/DriveZone.gpkg \
  --rcsdroad-path /mnt/d/TestData/POC_Data/RC4/RCSDRoad.gpkg \
  --rcsdnode-path /mnt/d/TestData/POC_Data/RC4/RCSDNode.gpkg \
  --max-cases 100 \
  --workers 4 \
  --out-root /mnt/d/Work/RCSD_Topo_Poc/outputs/_work/t02_virtual_intersection_full_input \
  --run-id t02_virtual_intersection_full_input_demo \
  --debug
```

```bash
python -m rcsd_topo_poc t02-export-text-bundle \
  --nodes-path /mnt/d/TestData/POC_Data/first_layer_road_net_v0/T02/nodes.gpkg \
  --roads-path /mnt/d/TestData/POC_Data/first_layer_road_net_v0/T02/roads.gpkg \
  --drivezone-path /mnt/d/TestData/POC_Data/patch_all/DriveZone.gpkg \
  --rcsdroad-path /mnt/d/TestData/POC_Data/RC4/RCSDRoad.gpkg \
  --rcsdnode-path /mnt/d/TestData/POC_Data/RC4/RCSDNode.gpkg \
  --mainnodeid 765003 \
  --out-txt /mnt/d/Work/RCSD_Topo_Poc/outputs/_work/t02_text_bundle/case_765003.txt
```

```bash
python -m rcsd_topo_poc t02-export-text-bundle \
  --nodes-path /mnt/d/TestData/POC_Data/first_layer_road_net_v0/T02/nodes.gpkg \
  --roads-path /mnt/d/TestData/POC_Data/first_layer_road_net_v0/T02/roads.gpkg \
  --drivezone-path /mnt/d/TestData/POC_Data/patch_all/DriveZone.gpkg \
  --rcsdroad-path /mnt/d/TestData/POC_Data/RC4/RCSDRoad.gpkg \
  --rcsdnode-path /mnt/d/TestData/POC_Data/RC4/RCSDNode.gpkg \
  --mainnodeid 765003 765154 922217 \
  --out-txt /mnt/d/Work/RCSD_Topo_Poc/outputs/_work/t02_text_bundle/cases_pack.txt
```

```bash
python -m rcsd_topo_poc t02-decode-text-bundle \
  --bundle-txt /mnt/d/Work/RCSD_Topo_Poc/outputs/_work/t02_text_bundle/case_765003.txt
```

```bash
cd /mnt/d/Work/RCSD_Topo_Poc/outputs/_work/t02_text_bundle
python -m rcsd_topo_poc t02-decode-text-bundle \
  --bundle-txt /mnt/d/Work/RCSD_Topo_Poc/outputs/_work/t02_text_bundle/cases_pack.txt
```

### 6.1 Stage3 输入前提

- `nodes` 必须包含：`id / mainnodeid / has_evd / is_anchor / kind_2 / grade_2`
- `roads` 与 `RCSDRoad` 当前只依赖：`id / snodeid / enodeid / direction`
- `RCSDNode` 必须包含：`id / mainnodeid`
- `mainnodeid` 对应代表 node 默认必须满足：`has_evd = yes`、`is_anchor = no`、`kind_2 in {4, 2048}`
- `review_mode` 下可绕过 `is_anchor = no` gate，并将 RC outside DriveZone 从硬失败降为风险记录 + 软排除
- 当前验收基线推荐使用标准 case-package 输入，不建议把共享大图层直连运行与算法验收混在一起

### 6.2 单 / 多 mainnodeid 文本证据包

- `t02-export-text-bundle` 可一次处理单个或多个 `mainnodeid`
- 导出端输入路径全部通过命令行提供：`nodes / roads / DriveZone / RCSDRoad / RCSDNode`
- 导出结果是单个纯文本文件，默认逻辑内容至少包含：
  - `manifest.json`
  - `drivezone_mask.png`
  - `drivezone.gpkg`
- `nodes.gpkg`
- `roads.gpkg`
- `rcsdroad.gpkg`
- `rcsdnode.gpkg`
  - `size_report.json`
- 打包流程固定为“局部裁剪 -> 压缩归档 -> 文本编码”，不允许直接明文拼接大段原始矢量文本
- 最终 bundle 文本体积必须 `<= 300KB`
- 若超限，入口必须失败退出，并输出体积分析 `size_report`
- `t02-decode-text-bundle` 负责校验 bundle 头尾标识、版本与 checksum，并恢复等价目录结构
- 未显式传入 `--out-dir` 时：
  - 单 case bundle 默认解包到与 bundle 同目录、且以 bundle 文件名为目录名的子目录
  - 多 case bundle 默认解包到当前工作目录，并展开为多个 `<mainnodeid>/` case 目录

## 7. Acceptance

1. 官方入口可稳定产出 `nodes.gpkg`、`segment.gpkg`、`summary`、`audit`、`log`。
2. `has_evd` 保持 `yes/no/null` 业务语义，不偷换为布尔值或 `0/1`。
3. 缺字段、缺 CRS、代表 node 缺失、路口组缺失、空目标路口等情形都可被诊断。
4. `summary` 已覆盖 `0-0双 / 0-1双 / 0-2双` 与 `all__d_sgrade`。
5. `is_anchor`、`node_error_1`、`node_error_2` 与 `fail2 > fail1` 优先级已冻结并已落地最小闭环实现。
6. stage2 当前仍未扩写为最终唯一锚定决策闭环，概率/置信度与环岛新规则未泄漏进当前正式契约。
7. stage3 `virtual intersection anchoring` 已纳入当前 baseline，并具备 case-package 与 full-input 两种运行模式。
8. `polygon-support` 与最终 association 已允许解耦；own-group nodes must-cover 与 support validation 已进入契约。
9. 单 / 多 `mainnodeid` 文本证据包已具备“导出 + 解包”最小闭环，当前作为 stage3 复核与外部复现支撑工具保留，且 bundle 体积受 `300KB` 上限约束。
