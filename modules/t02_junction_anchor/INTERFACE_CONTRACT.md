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
  - stage4 `diverge / merge virtual polygon` 独立成果
  - 连续分歧 / 合流复杂路口聚合离线工具
  - `t02-virtual-intersection-poc` baseline 入口：
    - 默认 `case-package`
    - 可显式切换 `--input-mode full-input`
  - 单 / 多 `mainnodeid` 文本证据包支撑入口
  - 独立离线修复工具 `t02-fix-node-error-2`
  - 独立连续分歧 / 合流聚合工具 `t02-aggregate-continuous-divmerge`
  - 消费 T01 `segment` 与 `nodes`
  - 消费 `DriveZone`、`RCSDIntersection`、`roads`、`RCSDRoad`、`RCSDNode`
  - 产出 `nodes.has_evd`、`nodes.is_anchor`、`segment.has_evd`、`summary`、`audit/log` 与 stage3 产物
- stage4 额外消费：
  - `nodes`
  - `roads`
  - `DriveZone`
  - `RCSDRoad`
  - `RCSDNode`
  - 可选高优先级局部参考：`DivStripZone`
- stage4 当前定位冻结为：
  - 面向分歧 / 合流事实事件的独立补充阶段
  - 当前不写回 `nodes.is_anchor`
  - 当前不并入统一锚定结果
  - 当前不承担主流程最终唯一锚定闭环
  - 当算法收敛到认可水平后，可与 stage3 合并进入同一锚定流程
- stage4 当前处理对象冻结为：
  - `has_evd = yes`
  - `is_anchor = no`
  - 需要按真实分歧 / 合流事件解释的事实路口候选
  - 简单 div/merge 候选：`kind` 或 `kind_2` 落在 `{8, 16}`
  - 经连续分歧 / 合流聚合后的 complex 主节点：`kind = 128` 或 `kind_2 = 128`
- stage4 当前语义归因冻结为：
  - `kind = 8` 或 `kind_2 = 8` 表示 merge（`2 in 1 out`）
  - `kind = 16` 或 `kind_2 = 16` 表示 diverge（`1 in 2 out`）
  - `kind / kind_2 = 128` 仅在“连续分歧 / 合流聚合后的 complex 主节点”语义下进入 stage4，不代表“所有 complex 128”
- stage4 实现采用 stage3 的栅格策略主线：
  - patch + mask + 连通提取 + 回矢量 + 审计
- stage4 结果是独立并行成果：
  - 不写回 `nodes.is_anchor`
  - 不并入统一锚定结果
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

### 2.3A 数据源特性与精度约束

- 当前 T02 消费两组道路数据源：
  - **SWSD（`nodes` / `roads`）**：覆盖性高，但精度有误差且工艺有差异；与道路面（`DriveZone`）和导流带（`DivStripZone`）存在偏差，SWSD node 点位与真实的道路分歧 / 合流位置最大可偏差约 `200m`
  - **RCSD（`RCSDNode` / `RCSDRoad`）**：覆盖性差，但精度高，与道路面和导流带套合较好；RCSD node 与真实路口位置差距不超过 `20m`
- 这一特性决定了 stage3 / stage4 的核心策略：
  - SWSD `nodes` 只作为 seed 和候选入口，不能替代真实事件定位
  - RCSD 不是无条件第一硬约束
  - 只有在对应事实路口存在对应 RCSD 挂接时，RCSD 覆盖 / 容差才构成条件性硬约束
  - 若 RCSD 在该事实路口缺失挂接，不以 RCSD 未覆盖作为失败条件
  - 路口面可以不包含 SWSD 路口点位
  - 对于存在挂接的事实路口，stage3 / stage4 必须保护对应的 `RCSDNode`
- 对分歧 / 合流场景的 `RCSDNode` 位置约束当前冻结为：
  - diverge：`RCSDNode` 允许位于真实分歧前不超过 `20m`
  - merge：`RCSDNode` 允许位于真实合流后不超过 `20m`
  - 该容差只用于与事实事件的条件性硬约束对齐，不得把 `RCSDNode` 反过来当作真实事件中心

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
  - `semantic_junction_set`：对目标 `junction_id = J`，从 `nodes` 全表按 `mainnodeid` 组和 singleton fallback 组装得到的当前语义路口 node 集合；它是 node 集合，不是单个点；只要组内存在 `kind_2` 非空且不为 `0` 的 node，即视为语义候选
  - `segment_referenced_junction_set`：`pair_nodes + junc_nodes` 去重后的 legacy 目标路口集合
  - `stage1_candidate_junction_set`：由当前 `semantic_junction_set` 对应的目标 `junction_id` 与 `segment_referenced_junction_set` 共同形成的阶段一候选域；该候选域不改变 `semantic_junction_set` 作为 node 集合的定义
- 单 `segment` 去重：
  - 先解析 `pair_nodes + junc_nodes`
  - 再在单个 `segment` 内去重
- 路口组装：
  1. 先查 `mainnodeid = J`
  2. 若不存在，再查 `mainnodeid = NULL 且 id = J`
- 代表 node：
  - 若 `mainnodeid = J` 成组，则组内 `id = J` 的 node 为代表 node
  - `mainnode` 只是当前 `semantic_junction_set` 的代表，不等于整个语义路口
  - 若代表 node 缺失，记 `representative_node_missing`，不允许 fallback
  - 环岛场景当前继承 T01 既有逻辑，不由 T02 自行扩写
- 多节点语义组：
  - 若 `semantic_junction_set` 为多节点组，则后续合法 polygon 必须一次性直接覆盖组内全部 node
  - 若最终 polygon 不能一次性直接覆盖整组所有 node，则该 case 属于问题 case，不是合法变体
- 语义边界道路：
  - `boundary roads / arms` 保留为语义边界概念
  - road 的“两端”不是只看当前 road 记录的直接两端，而是要沿可穿越的 `degree=2` 过渡节点继续跟踪，直到语义边界
  - 因此 road 的“两端”应理解为经过两度链接跟踪后的边界端点
  - 仅当某条 road 经过两度链接跟踪后的两个边界端点都不属于当前 `semantic_junction_set` 时，才认为它是 `foreign boundary roads`
  - 本步骤不再定义 `connector road` 术语
- 误包其它语义路口：
  - 判断“是否误包其他语义路口”，不能只看 foreign node
  - 若 polygon 把别的语义路口向外延伸到其他路口的 roads / arms 纳入当前路口面，即使没有直接覆盖 foreign node，也视为错误
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
  - `summary_by_s_grade` 仍只按 `0-0双 / 0-1双 / 0-2双` 的 segment 视图分桶
  - 桶内路口按唯一 ID 统计，不按 `segment-路口` 展开重复计数
  - 同时补充总汇总项 `all__d_sgrade`
  - `all__d_sgrade` 统计所有 `s_grade` 非空的 `segment`
  - `all__d_sgrade` 与单桶保持相同统计项与统计口径
  - `summary_by_kind_grade` 改按 `stage1_candidate_junction_set` 统计

### 2.6 Stage2 处理基线

- 阶段二当前业务定位冻结为：双向 Segment 相关路口的 anchor recognition / anchor existence。
- 阶段二正式候选边界冻结为：
  - `stage2_candidate_junction_set` 沿用 stage1 候选域定义，即由当前 `semantic_junction_set` 对应的目标 `junction_id` 与 `segment_referenced_junction_set` 共同形成
  - 仅 `has_evd = yes` 的组进入 stage2 主判定域
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
- `kind_2 in {8, 16}` 的组同样进入 stage2 锚定主判定：
  - 若满足 stage2 锚定标准，同样可记 `is_anchor = yes`
  - 仅当最终判为 `is_anchor = no` 时，才继续进入 stage4 div/merge
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
- stage3 步骤2「模板分类」当前冻结为：
  - `kind_2` 在步骤2中是强输入，不再只是弱证据
  - `kind_2 = 2048` 时，当前 case 直接按 `single_sided_t_mouth` 理解，不再按中心型路口模板理解
  - `kind_2 = 4` 时，当前 case 在步骤2中先按 `center_junction` 理解，允许后续按中心型路口铺满当前语义路口
  - 上述模板分类只回答“当前 case 属于哪类路口模板”，不等于已经通过后续边界/入侵合法性检查
- 对 `kind_2 = 4` 的 `center_junction`：
  - 若后续步骤发现 foreign boundary roads、其他语义路口 roads / arms 入侵、或其他边界冲突，则该 case 应视为问题 case
  - 不得因为步骤2先归入 `center_junction`，就将后续已发现的边界/入侵冲突视为合法变体
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
- case-package 是 stage3 唯一正式验收基线入口，不允许回退。
- 当前唯一正式验收基线冻结为 `E:\TestData\POC_Data\T02\Anchor`（WSL：`/mnt/e/TestData/POC_Data/T02/Anchor`）下的 `61` 个 case-package。
- full-input 当前保留为 fixture / dev-only / regression 入口，用于：
  - 完整数据 + 指定 `mainnodeid`
  - 完整数据 + 自动识别未锚定且有资料的路口
- full-input 当前不是 stage3 正式交付基线，不得再表述为“当前正式 baseline 入口”。
- 代表 node 的 stage3 baseline 前提：
  - `has_evd = yes`
  - `kind_2 in {4, 2048}`
  - 非 `review_mode` 下，`is_anchor = no`
- 所有空间处理必须统一到 `EPSG:3857`；不得以隐式默认 CRS 掩盖数据问题。

### 2.8 Stage3 虚拟路口锚定 baseline 处理契约

- `case-package` 模式只处理单个 `mainnodeid`。
- `full-input` 模式统一两类 regression 诉求：
  - 完整数据 + 指定 `mainnodeid`
  - 完整数据 + 自动识别候选
- stage3 步骤2「模板分类」当前正式业务口径冻结为：
  - `kind_2 = 2048 -> single_sided_t_mouth`
  - `kind_2 = 4 -> center_junction`
- 上述步骤2模板口径只冻结分类结果，不在本步骤内展开 polygon 几何、准出判定或失败归因。
- `kind_2 = 2048` 的 `single_sided_t_mouth`：
  - 表示当前 case 在后续步骤中必须受单边活动空间约束
  - 不再允许在步骤2中回退为中心型路口模板
- `kind_2 = 4` 的 `center_junction`：
  - 表示当前 case 在后续步骤中可先按中心型路口理解，并允许尝试铺满当前语义路口
  - 但该归类不豁免后续边界/入侵冲突检查
  - 若后续发现 foreign boundary roads、其他语义路口 roads / arms 入侵，或其它边界冲突，则该 case 应视为问题 case
- stage3 步骤3「目标 corridor / 口门边界」当前正式业务口径冻结为：
  - 步骤3不生成 polygon；它只定义后续 polygon 唯一合法的活动空间
  - 合法活动空间以当前 `semantic_junction_set` 为中心，并且只能在当前模板允许占用的 `DriveZone` 内道路面中生长
  - 这里的“铺满道路面”只表示铺满当前 case 的合法道路面，不表示铺满整个连通 `DriveZone`
- 步骤3的通用边界规则：
  - 对与当前合法活动空间存在潜在冲突的 foreign elements，应构建负向区域
  - 对与当前语义路口直接连通的其他语义路口，应沿进入该语义路口的道路方向，在其入口边界前 `1m` 设置垂直于道路方向的负向掩膜边界
  - 对与当前语义路口无关、但位于同一道路面内的 foreign road / arm / node，优先沿 foreign road / arm 构造 `1m` 缓冲负向掩膜；仅在无法识别 road / arm 时，才退化为 node 周边小范围负向掩膜
  - 对道路面内、属于同一其他语义路口的 node，先按平面位置构造 MST 最小连通线集，MST 连线只保留道路面内部分，并对道路面内部分做 `1m` 缓冲负向掩膜
  - 一旦后续 polygon 活动空间必须侵入其他语义路口、foreign arms、或 `foreign boundary roads` 才能成立，则该空间不合法，应视为问题 case
  - `1m` 负向区域是硬排除边界，不得被后续 support / repair / cleanup 重新突破
  - 当前 case 的 Step3 `allowed space / polygon-support space` 不得进入其他语义路口，也不得纳入其他语义路口向外延伸的 `roads / arms / lane corridor`
  - 当前 case 的 Step3 `allowed space` 不得进入与当前语义/拓扑不连通的对向道路面；该约束按语义/拓扑连通性判定，不按纯几何“看起来在对面”判定
  - 当前 case 的 Step3 候选空间必须先自成立；若某个方向只能依赖 cleanup / trim 才能不越界，则该方向的 Step3 候选空间不成立
  - 任何长度放大、mouth 补长、或竖向补长，都只能在上述硬排除已经满足且 Step3 候选空间已自成立后才允许讨论；不得先放大再依赖 cleanup / trim 作为主要补救手段
- 上述 Step3 口径冻结为规则 A / B / C / D / E / F / G / H：
  - A / B / C：分别对应“相邻语义路口入口截断”“同面无关对象负向掩膜”“其他语义路口内部 node 的 MST 负向掩膜”
  - D：当前语义路口候选空间只能在道路面内沿合法方向增长，不能越过负向掩膜边界，也不能越过非道路面区域
  - E：`kind_2 = 2048 / single_sided_t_mouth` 不得进入对向 Road、对向语义 Node、对向 lane、或对向主路 corridor
  - F：若某个 case 只能依赖 cleanup / trim 才满足边界要求，则视为 Step3 未成立
  - G：参数放大只能在以上边界全部满足后进行；不得先放大，再靠 cleanup / trim 擦除越界
  - H：旧的 `10m` 保守外扩口径取消；统一采用“无更早边界时单向 `50m`”
- `single_sided_t_mouth` 的步骤3口径：
  - 合法活动空间是当前 case 的目标单侧 lane corridor
  - 被负向区域命中的方向必须终止生长
  - 未命中的方向，只能在当前 case 合法的单侧道路面内继续展开
  - 不得跨到对向 lane，不得跨到对向主路 corridor
  - 不得进入对向 Road，不得进入对向语义 Node，不得进入对向 lane / 对向主路 corridor；这是硬排除，不是弱风险提示
  - 横向支路只贡献当前口门附近所必需的 mouth 空间，不得借此沿无关方向继续外延
- `center_junction` 的步骤3口径：
  - 合法活动空间可先按中心型路口展开，并允许铺满当前 case 的合法道路面
  - 但其合法边界仍受当前 `semantic_junction_set` 的 `boundary roads / arms` 约束
  - 若必须侵入 foreign boundary roads、其他语义路口 roads / arms，或其他边界冲突空间，当前中心型活动空间即不成立，应视为问题 case
- 步骤3的单向增长上限：
  - 若某个方向上不存在更早的语义边界或 foreign 边界，则该方向单向最大增长距离不超过 `50m`
  - `50m` 只用于“无更早边界时”的单向补足，不替代其他边界判断
  - `50m` 不得突破 foreign 负向区域，不得突破当前模板合法空间，也不得优先于步骤1中“整组 node 必须一次性直接覆盖”的要求；若二者冲突，则当前 case 应视为问题 case
- 当前路口组 own-group nodes 必须纳入 polygon，不能只作为分析输入。
- `associated_rcsdroad.gpkg / associated_rcsdnode.gpkg` 与 `polygon-support` 允许解耦：
  - association 可以保守
  - `polygon-support` 可以保留更完整的局部 RC 连通组件
- 若 RC 不存在与 roads 同方向的有效局部分支，不得拿其它横向或直行 RC 组件替代。
- 最终 polygon 必须通过 support validation：
  - own-group nodes 必须被覆盖
  - `polygon-support` 中声明的 RCSDNode / RCSDRoad 必须被合理覆盖
- 对 nodes 与 RCSD 拓扑无法同时满足的场景，必须明确失败或风险标记，不得 silent fix。
- stage3 步骤4「RCSD 关联语义」当前正式业务口径冻结为：
  - 步骤4只负责在步骤2模板和步骤3合法活动空间已经冻结的前提下，判断当前 SWSD 语义路口与 RCSD 的对应层级，并据此识别当前 case 的 `required RC`、`support RC` 与 `excluded RC`
  - 步骤4不是重新定义 SWSD 语义路口，不是重新定义步骤3 corridor，不是重新生成 polygon，也不是准出判定
- 步骤4的 A / B / C 三类结果当前冻结为：
  - A 类：`RCSD` 也构成语义路口
  - B 类：`RCSD` 不构成语义路口，但存在相关 `RCSDRoad`
  - C 类：无相关 `RCSDRoad`
- A 类（`RCSD` 也构成语义路口）：
  - `RCSDNode` 按 `mainnodeid` 聚组，并与 `SWSD` 一样按整组 node 处理，不是只抓一个点
  - 若 `RCSD` 侧仅有单个 node，则其独立语义路口条件与 `SWSD` 一致：至少存在 3 个方向的 `RCSDRoad` 与该 node / 语义组关联
  - 这里的“3 个方向”正式按“经过可穿越 `degree=2` 过渡节点跟踪后的边界方向簇数”判定，不按字面 `RCSDRoad` 条数机械计数
  - 该 `RCSD` 语义组需位于当前 case 的 mouth / core 区域内；不要求 `RCSDRoad` 数量与 `SWSD roads` 完全一致
  - 一旦 A 类成立，则该 `RCSD` 语义组属于当前 case 的 `required RC semantic set`
- B 类（`RCSD` 不构成语义路口，但存在相关 `RCSDRoad`）：
  - 当前 case 不要求完整覆盖 `RCSDNode` 语义组
  - 但需要识别并覆盖对应 `RCSDRoad` 的挂接区域
  - “挂接区域”当前正式理解为：以当前 `SWSD semantic_junction_set` 到目标 `RCSDRoad` 的最小连接区域附近为默认基线；若存在明确臂悬，可沿臂悬方向修正；它不等于整条 `RCSDRoad` 全段
- C 类（无相关 `RCSDRoad`）：
  - 当前 case 不追加 `RC` 侧 `required semantics`
  - 若某个方向上不存在更早的语义边界或 foreign 边界，则该方向单向最大增长距离不超过 `50m`
  - `50m` 只用于“无更早边界时”的单向补足，不替代其他边界判断，也不得压过 `SWSD semantic_junction_set` 与步骤3合法活动空间的边界要求；旧 `10m` 正式口径取消
- 步骤4与步骤3的边界当前冻结为：
  - 步骤4可以增加“必须纳入的 `RC` 语义对象”，但不能扩大步骤3已经冻结的合法活动空间
  - 若某个 `required RCSDNode / required RCSDRoad` 按步骤4语义应当纳入，但它落在步骤3合法空间之外，则当前定义为审计异常 / `stage3_rc_gap` 类问题
  - 该异常只用于暴露“步骤3是否漏包 required RC”，当前不允许步骤4直接反向扩大步骤3 corridor 或改写当前合法几何
- stage3 步骤5「foreign SWSD / RCSD 排除规则」当前正式业务口径冻结为：
  - 步骤5只负责定义哪些外部 `SWSD / RCSD` 元素一旦被纳入当前 case，就必须视为 `foreign / 错误对象`
  - 步骤5不是重新定义语义路口，不是重新定义模板，不是重新定义步骤3合法活动空间，不是重新定义步骤4 `required / support / excluded RC`，也不是准出判定
- 步骤5的 foreign 对象分类当前冻结为：
  - A. `foreign_semantic_nodes`：
    - 不属于当前 `semantic_junction_set` 的 `SWSD node`
    - 或不属于当前 case 允许 `RC` 语义范围的 `RCSD node`
  - B. `foreign_roads_arms_corridors`：
    - `foreign boundary roads`
    - `foreign roads / arms`
    - `foreign lane corridor`
    - `foreign` 主路 corridor
    - `foreign mouth` 的另一侧 corridor
    - `foreign` 远端 tail / 外延通道
  - C. `foreign_rc_context`：
    - 步骤4已判为 `excluded RC` 的对象
    - 只能靠越出步骤3合法活动空间才成立的 `RC`
    - 属于 `foreign lane / foreign arm / foreign corridor / foreign semantic context` 的 `RC`
- 步骤5的硬规则当前冻结为：
  - 不能只看 `foreign node`；即使没有直接覆盖 `foreign node`，只要把别的语义路口外延 `roads / arms / lane corridor` 纳入当前 case，也应视为错误
  - 步骤4中的 `excluded RC` 在步骤5中直接等价于 `foreign RC`，不允许因为这些 `RC` “看起来有帮助”就重新提升为 `support`
  - `foreign` 排除优先级高于几何修补；不能为了让 polygon 更连通，或为了补一个 selected / support 节点，就允许 `foreign` 元素残留
- `single_sided_t_mouth` 的步骤5口径：
  - 以下对象一律按 `foreign` 处理，不留容忍窗口：
    - 对向 lane
    - 对向主路 corridor
    - 对向 Road
    - 对向语义 Node
    - 非当前目标 mouth 的另一侧 corridor
    - 非当前 mouth 的远端 `RC tail`
    - `foreign arms`
    - `foreign boundary roads`
    - 任何只要跨出当前目标单侧 corridor 才会进入的 `RC / SWSD` 外部对象
- `center_junction` 的步骤5口径：
  - 以下对象只要进入当前 case，就一律视为错误：
    - `foreign boundary roads`
    - 其他语义路口向外延伸的 `roads / arms`
    - 其他语义路口的 lane corridor
    - 只有越过当前语义边界才会进入的道路面区域
    - 任何只在 `foreign` 语义上下文里成立的 `RC` 对象
- 步骤5中“边界接触”与“实际纳入”的区别当前冻结为：
  - 合法边界接触：若某 `foreign` 元素仅与当前合法活动空间发生边界接触，但未进入当前 polygon / corridor 的活动空间，则不算错误
  - 实际纳入：若某 `foreign` 元素已形成以下任一情况，则算错误：
    - 被纳入当前 polygon 的正面积区域
    - 被纳入当前 corridor 的正向活动空间
    - 被纳入当前 mouth 的可展开方向
    - 成为当前 case 的 `support / repair / cleanup` 依赖对象
    - 只有依赖它，当前 case 才能继续成立
- 当前 A / B / C 三类 Step3 硬排除口径属于既有业务边界的显式化，不是新增业务方向：
  - A. 其他语义路口及其外延 `roads / arms / lane corridor` 硬排除
  - B. 与当前语义/拓扑不连通的对向道路面硬排除
  - C. `single_sided_t_mouth` 下，对向 Road / 对向语义 Node / 对向 lane / 对向主路 corridor 硬排除
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

 - stage3 步骤6「几何生成与后处理」当前正式业务口径冻结为：
  - 步骤6是受约束的几何生成步骤，不是结果导向的补面或补救步骤
  - 步骤6的硬约束优先级固定为：
    1. 不得突破步骤3合法活动空间
    2. 不得纳入步骤5定义的 `foreign` 对象
    3. 必须满足步骤1的 `semantic_junction_set` must-cover
    4. 必须满足步骤4的 `required RC` must-cover
    5. 在前述约束全部成立后，才允许做几何优化
  - `single_sided_t_mouth` 的理想几何应是围绕目标单侧 mouth 形成的单侧口门面；横向支路只贡献接入口门区域，纵向延伸只服务于闭合当前口门，不得跨对向 lane，不得退化成无意义的狭长走廊或远端 patch 拼接
  - `center_junction` 的理想几何应是围绕当前语义路口中心展开的中心型路口面；可覆盖多个合法 arms 的 mouth 区域，但延伸只服务于表达当前中心路口，不得退化成单条带状走廊，也不得依赖 `foreign roads / arms / corridors` 才成立
  - 以下现象在步骤6中直接视为问题几何：
    - 无意义狭长面衔接
    - 无意义空洞
    - 无意义凹陷
    - 细脖子 / 窄连接
    - 非当前方向远端尾巴
    - 依赖 `foreign` 空间才成立的补丁连接
  - geometry cleanup 只能在已合法的模板空间内收敛几何，不能作为让 Step3 候选空间成立的主通路，不能越出步骤3合法活动空间，不能重新引入步骤5 `foreign` 对象，不能用 `support` 替代 `required`，也不能把问题几何“化妆成成功几何”
  - 若步骤6无法生成一个同时满足步骤1 / 步骤3 / 步骤4 / 步骤5约束、并且符合当前模板认知形态的 polygon，则该 case 在业务上应视为“路口面几何未成立”
- 步骤6失败的根因归类当前冻结为两层：
  - 一级：
    - `infeasible_under_frozen_constraints`
    - `geometry_solver_failed`
  - 二级：
    - `step1_step3_conflict`
    - `stage3_rc_gap`
    - `foreign_exclusion_conflict`
    - `template_misfit`
    - `geometry_closure_failure`
    - `cleanup_overtrim`
    - `cleanup_undertrim`
    - `foreign_reintroduced_by_cleanup`
    - `shape_artifact_failure`
  - 当前目视检查中唯一已明确确认的失败锚点是 `520394575`；除它之外，若其他 case 要进入步骤6失败归类，必须先完成根因分型，不得仅凭“看着不顺眼”直接判为失败
- stage3 步骤7「准出判定」当前正式业务口径冻结为：
  - 步骤7是最终裁决层，只基于步骤1到步骤6已冻结结果做最终准出分类：`accepted / review_required / rejected`
  - 步骤7不重新定义语义路口、不重新定模板、不重新定 corridor、不重新解释 `required / support / excluded RC`、不重新解释 `foreign`、不重新生成 polygon，也不允许洗白步骤6失败
  - `accepted` 的最小前提固定为：
    - 步骤1：`semantic_junction_set` must-cover 成立
    - 步骤3：合法活动空间成立
    - 步骤4：`required RC` 成立
    - 步骤5：`foreign` 排除成立
    - 步骤6：几何已成立，且不是问题几何
    - 不存在未消除的核心审计异常
  - `review_required` 只适用于：当前结果已经满足业务需求，但几何表现、可审查性或视觉质量仍存在风险；`review_required` 只允许映射到 `V2`
  - `rejected` 只适用于：当前 case 已明确违反硬规则，或在当前冻结约束下无合法解，或步骤6已经确认“路口面几何未成立”且失败根因已明确；`rejected` 只允许映射到 `V3 / V4 / V5`
  - 步骤7不能洗白前面步骤的失败；若步骤6已认定“路口面几何未成立”，步骤7只能在 `review_required / rejected` 之间分类，不能再解释成成功
  - Stage3 结果类型与目视分类的正式映射冻结为：
    - `accepted -> V1`
    - `review_required -> V2`
    - `rejected -> V3 / V4 / V5`
  - 可以保守失败，但不能把业务失败判成成功；当前 `520394575` 作为唯一已明确确认的失败锚点保留，除它之外的其他 case 若要进入 `review_required / rejected`，必须先完成根因分析并说明属于“上游冻结约束下无合法解”还是“合法解存在但步骤6没求出来”

### 2.10 Stage4 div/merge 虚拟面契约

#### 2.10.1 顶层定位

- `t02-stage4-divmerge-virtual-polygon` 是当前 stage4 独立入口。
- stage4 当前定位冻结为：
  - 面向分歧 / 合流场景的独立补充阶段
  - 当前不属于统一锚定主流程的一部分
  - 当前不负责写回 `nodes.is_anchor`
  - 当前不负责并入统一锚定结果
  - 当前不负责主流程最终唯一锚定闭环
- 上述定位是当前版本定位，不是永久架构边界：
  - 当算法收敛到认可水平后
  - stage4 可与 stage3 合并进入同一锚定流程
  - 并承担对应的锚定信息关联职责
- stage4 的业务主线冻结为：
  - 真实事件优先
  - 不是中心优先
  - SWSD `nodes` 只作为 seed / 候选入口
  - 不能替代真实分歧 / 合流事件定位

#### 2.10.2 处理对象与非目标

- stage4 核心必选输入：
  - `nodes`
  - `roads`
  - `DriveZone`
  - `RCSDRoad`
  - `RCSDNode`
  - `mainnodeid`
- stage4 高优先级局部参考输入：
  - `DivStripZone`
  - 可缺省；缺省或局部无 nearby 命中时，允许降级到 `roads / RCSDRoad` 支撑解释
- stage4 当前只认字段：
  - `nodes.id / nodes.mainnodeid / nodes.has_evd / nodes.is_anchor / nodes.kind / nodes.kind_2 / nodes.grade_2`
  - `roads.id / roads.snodeid / roads.enodeid / roads.direction`
  - `RCSDRoad.id / RCSDRoad.snodeid / RCSDRoad.enodeid / RCSDRoad.direction`
  - `RCSDNode.id / RCSDNode.mainnodeid`
- stage4 当前处理对象冻结为：
  - 有证据、尚未完成正式锚定
  - 需要按真实分歧 / 合流事件解释的事实路口候选
- 当前正式处理两类对象：
  - 简单 div/merge 候选
  - 连续分歧 / 合流聚合后的 complex 128 主节点
- `kind` 与 `kind_2` 在 stage4 候选识别语义上等价：
  - 本地测试可能只有 `kind_2`
  - 正式契约不得把候选识别写死在单一字段上
- 普通 div/merge 场景中：
  - `nodeid` 可作为等效 `mainnodeid`
  - 不把“必须存在独立 `mainnodeid`”写成业务前提
- RCSD 缺失挂接但事实事件存在时：
  - 仍属于 stage4 处理对象
  - 不得因为缺少 RCSD 挂接就排除进入 stage4
- 当前非目标冻结为：
  - 不写回 `nodes.is_anchor`
  - 不并入统一锚定结果
  - 不做最终唯一锚定决策闭环
  - 不做候选生成 / 候选打分
  - 不做概率 / 置信度实现
  - 不做误伤捞回
  - 不做环岛新业务规则
  - 当前可用于审计 / 验证批跑，但不承担正式产线级全量锚定闭环职责

#### 2.10.3 七步正式业务定义

##### Step1 候选验证（Candidate Admission）

- Step1 是准入 gate，不是正确性 gate。
- Step1 只验证目标对象是否属于 stage4 当前处理范围。
- Step1 不负责提前判断事件解释是否正确。
- Step1 不加入拓扑 sanity。
- RCSD 是否存在不影响准入。
- `mainnodeid_out_of_scope` 只表示“不属于 stage4 当前处理范围”，不得用来承接后续 `operational kind_2` 解析失败。

##### Step2 高召回事件局部上下文构建（High-recall Local Context）

- Step2 不是 patch 全量解释，而是 `DriveZone` 硬边界内的高召回事实事件局部上下文构建。
- Step2 既要保证真实事件不缺失，也要组织负向排除对象。
- Step2 正向召回上限冻结为：
  - diverge：以进入 road 为主干，沿其向后最多 `50m`；以前进方向各个 branch road 为臂，沿其向前最多 `200m`；各方向都不得越过相邻语义路口
  - merge：以退出 road 为主干，沿其向前最多 `50m`；以回推方向各个 branch road 为臂，沿其向后最多 `200m`；各方向都不得越过相邻语义路口
- 上述 `50m / 200m` 是当前版本的最大召回上限，不是每个 case 必须跑满的固定窗口；若更早碰到稳定的相邻语义路口边界，应提前收敛。
- Step2 负向排除上下文冻结为：
  - 负向排除对象是落在正向召回道路面内、但与当前正向事件无关的 `RCSD / SWSD / road` 对象
  - 优先级为 `RCSDNode / RCSDRoad` 优先，`nodes / roads` 其次，必要时允许 road geometry 补位
  - Step2 只负责组织 `negative exclusion context`，不在本步骤完成最终几何排除
- `DriveZone` 是 Step2 无条件硬边界。
- 对当前事件直接相关且被纳入解释范围的 RCSD：
  - 若超出 `DriveZone`，直接失败

##### Step3 拓扑成骨架（Topology Skeletonization）

- Step3 是拓扑成骨架，不是重新分类候选。
- 二度 through node 不打断 branch；二度 through node 视为完整 road 的中间连接点。
- 对普通简单 div/merge：
  - Step3 直接组织 branch 与主方向关系
- 对连续分歧 / 合流及 complex 128：
  - `chain_context` 不是日志附加项，而是会改变 branch 连通解释和主方向选择的结构性约束
- Step3 原则上不作为常规业务失败步骤；它负责产出骨架并暴露不稳定性，不应把当前实现中的保底异常路径直接冻结成正式业务失败口径。

##### Step4 事实事件解释层（Fact Event Interpretation）

- Step4 是事实事件解释层，不是几何生成层，也不是人工目视中间过程输出层。
- Step4 主输出是机器可消费的事件解释结果包，供 Step5 / Step6 消费。
- `continuous chain / multibranch / reverse tip` 正式冻结为 Step4 内部稳定规则家族。
- Step4 主证据链最小顺序冻结为：
  1. DivStrip 直接事件证据优先
  2. `continuous chain / multibranch` 结构约束与裁决
  3. `reverse tip` 受控重试
  4. 保守 fallback
- Step4 不是把 `DivStrip / topology / RCSD / SWSD / road` 平铺混用，必须存在明确主证据链。
- `reverse tip` 只允许作为受控重试，不得作为常规主路径。
- Step4 默认行为是保守降级、显式外露风险，而不是轻易 hard fail。

##### Step5 事件几何支撑域构建（Geometric Support Domain）

- Step5 是事件几何支撑域构建层，不是事件解释层，也不是最终 polygon 层。
- Step5 的 span 必须落在 Step2 召回上限之内，并根据 Step4 事件解释结果进一步收敛成实际几何窗口。
- Step5 正式承担负向排除对象的几何约束落地职责。
- “近似垂直横截面”正式冻结为 Step5 的几何构造要求，不是可有可无的实现建议。

##### Step6 最终 polygon 组装（Polygon Assembly）

- Step6 是最终 polygon 组装层，不再回头解释事件。
- Step6 目标是收敛到一个主 polygon，不输出多候选几何。
- Step6 不直接做 acceptance；它只产出几何成形状态与几何风险信号。
- Step6 必须把这些结果完整传递给 Step7。
- 正式需求中不得再把 Step6 的几何状态与 Step3 的拓扑不稳定混用成同一失败语义。

##### Step7 最终业务验收与结果发布（Final Acceptance & Publishing）

- Step7 是最终业务验收与结果发布层，不是事件解释层，也不是几何生成层。
- Step7 正式使用条件性 RCSD 硬约束：
  - 只有在对应事实路口存在对应 RCSD 挂接时
  - 才必须满足 RCSD 覆盖 / 容差
- Step7 三态冻结为：
  - `accepted` = 稳定可交付
  - `review_required` = 已形成结果但仍需人工复核
  - `rejected` = 无合法结果或违反明确硬业务约束
- Step7 输出责任冻结为：
  - 三种状态都应尽量落完整独立结果包
  - 当前不承担主流程写回责任
- stage4 正式输出与结果字段约束见第 3 节。

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
- `stage4_virtual_polygon.gpkg`
- `stage4_virtual_polygons.gpkg`
- `stage4_node_link.json`
- `stage4_rcsdnode_link.json`
- `stage4_audit.json`

### 3.3 输出语义

#### 最终成果路口面统一输出约束

- 以下图层都属于“最终成果路口面”：
  - stage3 单 case：`virtual_intersection_polygon.gpkg`
  - stage3 full-input / batch：`virtual_intersection_polygons.gpkg`
  - stage4 单 case：`stage4_virtual_polygon.gpkg`
  - stage4 batch / 全量：`stage4_virtual_polygons.gpkg`
- 所有最终成果路口面图层都必须包含字段：
  - `mainnodeid`
  - `kind`
- `mainnodeid` 写值规则冻结为：
  - 优先写当前 case 代表 node 对应的 `nodes.mainnodeid`
  - 若 `nodes.mainnodeid` 为空、缺失或不可用，则回退写当前代表 node 的 `nodes.id`
- `kind` 写值规则冻结为：
  - 优先写当前 case 代表 node 对应的 `nodes.kind`
  - 若 `nodes.kind` 为空、缺失或不可用，则回退写当前代表 node 的 `nodes.kind_2`
  - 若 `nodes.kind / nodes.kind_2` 同时为空、缺失或不可用，则该 case 视为缺失最终成果字段，不得静默补值
- 所有最终成果路口面 geometry 必须统一写为 `EPSG:3857`。
- Stage4 最终成果路口面图层（`stage4_virtual_polygon.gpkg`、`stage4_virtual_polygons.gpkg`）还必须稳定承载以下审计属性字段：
  - `divstrip_present`
  - `divstrip_nearby`
  - `divstrip_component_count`
  - `divstrip_component_selected`
  - `evidence_source`
  - `event_position_source`
  - `event_tip_s_m`
  - `event_span_start_m`
  - `event_span_end_m`
  - `semantic_prev_boundary_offset_m`
  - `semantic_next_boundary_offset_m`
  - `trunk_branch_id`
  - `rcsdnode_tolerance_rule`
  - `rcsdnode_tolerance_applied`
  - `rcsdnode_coverage_mode`
  - `rcsdnode_offset_m`
  - `rcsdnode_lateral_dist_m`
- `acceptance_class` 与 `acceptance_reason` 为当前正式建议同步固化到 Stage4 最终成果路口面图层中的结果字段。
- 上述 Stage4 字段不得只散落在 JSON 中；Stage4 最终成果 polygon 图层必须支持脱离 JSON 的基本独立复核。
- 只要存在 full-input / batch / 全量运行，就必须同步输出该批次的最终全量路口面汇总图层；不得只保留单 case 目录产物而缺失汇总成果。

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
- `summary_by_kind_grade` 的统计对象是 `stage1_candidate_junction_set`，按 `junction_id` 唯一值计数。
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
  - 统计对象是 `stage2_candidate_junction_set` 中代表 node 可解析的路口组
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
  - 属于当前 case 的最终成果路口面图层
  - 必须包含 `mainnodeid / kind`
  - `mainnodeid` 优先取代表 node 的 `nodes.mainnodeid`，为空或缺失时回退 `nodes.id`
  - `kind` 优先写代表 node 的 `nodes.kind`，为空或缺失时回退 `nodes.kind_2`
  - 输出 geometry 必须统一为 `EPSG:3857`
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
  - Stage3 debug render PNG 的目视检查样式必须固定为三态表达：
    - `accepted`
      - 使用正常成功图样式
      - 不得叠加整图风险/失败掩膜
    - `review_required`
      - 必须使用风险样式，而不是成功样式
      - 整图使用浅琥珀 / 橙黄色系半透明掩膜
      - 使用深橙色粗边框
      - 风险关注区域使用更深一层的橙色强调
      - 必须有清晰可见的 `REVIEW` / `待复核` 标识
    - `rejected` 或 `success = false`
      - 必须使用失败样式
      - 整图淡红色掩膜
      - 深红色粗边框
      - 失败关注区域叠加深红强调
      - 必须有清晰可见的 `REJECTED` / `失败` 标识
  - `review_required` 不得使用红色系主样式，以避免与 `rejected` 混淆；`V2` 必须使用该风险样式
  - `V3 / V4 / V5` 均属于失败家族，必须使用 `rejected` 红色失败样式；允许在失败家族内部保留根因子型差异，但不得再渲染成风险态
  - 非成功图不得仅依赖细边框、轻微色差或局部角标提示；必须保证人工目视时与成功图一眼可区分，且 `review_required` 与 `rejected` 彼此也能一眼区分

#### Stage3 / Stage4 成果审计与目视复核

- 当前成果审计固定采用双线并行：
  - 机器审计：基于 `status.json / audit.json / gpkg / png` 产物给出根因分析
  - 人工目视审计：基于结果图与必要矢量叠加给出快速业务判断
- Stage4 正式复用 Stage3 的双线并行成果审计方案、目视分类表达与 PNG 三态样式契约，但只复用表达方式与审查模板，不继承 Stage3 业务语义。
- 机器审计的根因层至少应落在以下之一：
  - `step3`
  - `step4`
  - `step5`
  - `step6`
  - `frozen-constraints conflict`
- 人工目视审计当前快速分类冻结为：
  - `V1 认可成功`
  - `V2 业务正确但几何待修`
  - `V3 漏包 required`
  - `V4 误包 foreign`
  - `V5 明确失败`
- 目视分类与结果类型的正式业务语义冻结为：
  - `V1 = 成功`，且只能对应 `accepted`
  - `V2 = 有风险`，表示业务满足但几何或审查质量待修，且只能对应 `review_required`
  - `V3 = 失败`，表示目视可见的 `required` 漏包，且只能对应 `rejected`
  - `V4 = 失败`，表示目视可见的 `foreign` 误包，且只能对应 `rejected`
  - `V5 = 失败`，表示明确失败，且可能无法形成正常目视审查结果，且只能对应 `rejected`
- 最终复核结论应以“双线对齐”为准：
  - 人工目视先给 `V1~V5`
  - 机器审计补充根因层与根因类型
  - 若二者不一致，必须先完成根因分析，再进入后续修正
- Stage4 当前正式复用同一套成果审计与目视复核模板；不得为 Stage4 单独发明另一套成功/风险/失败表达。

#### Stage3 full-input 根目录输出

- 根目录仍固定为 `<out_root>/<run_id>`
- `cases/<mainnodeid>/...`
  - 保留单 case worker 原始输出，便于审计与回溯
- `virtual_intersection_polygons.gpkg`
  - 汇总本批成功生成的虚拟路口面
  - 属于 stage3 full-input / batch 的最终全量路口面汇总图层
  - 每条成果必须包含 `mainnodeid / kind`
  - `mainnodeid` 优先取代表 node 的 `nodes.mainnodeid`，为空或缺失时回退 `nodes.id`
  - `kind` 优先写代表 node 的 `nodes.kind`，为空或缺失时回退 `nodes.kind_2`
  - 输出 geometry 必须统一为 `EPSG:3857`
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

#### Stage4 状态与失败口径

- Step7 是 Stage4 最终业务验收与结果发布层。
- Stage4 三态冻结为：
  - `accepted`
  - `review_required`
  - `rejected`
- `mainnodeid_out_of_scope` 只表示“不属于 Stage4 当前处理范围”，不得承接 `operational kind_2` 解析失败或几何求解失败。
- 条件性 RCSD 硬约束冻结为：
  - 只有在对应事实路口存在对应 RCSD 挂接时
  - 才必须满足 RCSD 覆盖 / 容差
  - 若事实路口缺失对应 RCSD 挂接，不以 RCSD 未覆盖作为单独失败条件
- 明确失败原因至少包含：
  - `missing_required_field`
  - `invalid_crs_or_unprojectable`
  - `mainnodeid_not_found`
  - `mainnodeid_out_of_scope`
  - `main_direction_unstable`
  - `rcsd_outside_drivezone`
  - `no_legal_local_result`
  - `hard_business_constraint_violation`
- 以下业务结果至少应进入 `review_required`，不得记为 `accepted`：
  - 命中错误 `DivStripZone` 组件或错误事件位置
  - 简单路口 span 超过前后语义路口边界，或明显超过 `200m`
  - 复杂 / 连续路口只覆盖部分事件区域，未覆盖当前 `mainnodeid` 组内应纳入的事件区域
  - 吞并无关对向 / 平行 road 的整幅路面
  - 吞并相邻无关 `T` 型路口、无关 patch 或无关语义路口
  - 主 `RCSDNode` 仅靠超窗、反向或 off-trunk 才能解释
- 若对应事实路口存在对应 RCSD 挂接而结果又无法满足 RCSD 覆盖 / 容差，则不得记为 `accepted`；无法形成合法局部结果时必须进入 `rejected`。
- `review_required` 只适用于“已形成结果但仍需人工复核”；`rejected` 不得再只由异常 handler 语义承接。
- Stage4 的 `status/progress/perf/perf_markers` 仍可输出为运行态工件，但不属于正式契约输出。
- Stage4 的目视检查 PNG 当前正式复用 Stage3 的三态样式契约：
  - `accepted` 使用正常成功图样式
  - `review_required` 使用浅琥珀 / 橙黄色系风险样式，并带 `REVIEW` / `待复核` 标识
  - `rejected` 或 `success = false` 使用淡红 / 深红失败样式，并带 `REJECTED` / `失败` 标识
  - Stage4 非成功图同样不得仅依赖细边框、轻微色差或局部角标提示，必须保证人工目视时与成功图以及彼此风险/失败态一眼可区分

## 4. EntryPoints

### 4.1 官方入口

运行前先在 repo root 执行：

```bash
make env-sync
make doctor
```

```bash
.venv/bin/python -m rcsd_topo_poc t02-stage1-drivezone-gate --help
.venv/bin/python -m rcsd_topo_poc t02-stage2-anchor-recognition --help
```

### 4.2 Stage3 与支撑入口

```bash
.venv/bin/python -m rcsd_topo_poc t02-virtual-intersection-poc --help
.venv/bin/python -m rcsd_topo_poc t02-export-text-bundle --help
.venv/bin/python -m rcsd_topo_poc t02-decode-text-bundle --help
```

- `t02-virtual-intersection-poc` 是当前 stage3 baseline 官方入口
- 默认 `input_mode = case-package`，保持 Anchor61 case-package 正式验收基线不回退
- `--input-mode full-input` 打开统一全量输入 regression 入口：
  - 传 `--mainnodeid`：完整数据 + 指定路口
  - 不传 `--mainnodeid`：完整数据 + 自动识别候选
- 不重算 stage1 / stage2，只消费其结果字段
- 该入口直接消费带 `has_evd / is_anchor` 的 `nodes`，不会在入口内部重算 stage1 / stage2 主逻辑

### 4.3 Stage4 独立入口

```bash
.venv/bin/python -m rcsd_topo_poc t02-stage4-divmerge-virtual-polygon --help
```

- `t02-stage4-divmerge-virtual-polygon` 是当前 stage4 独立入口
- 该入口只做单 case baseline，不进入 full-input 批处理
- 该入口不重算 stage1 / stage2，也不写回 `nodes.is_anchor`

### 4.4 独立离线修复与聚合工具

```bash
.venv/bin/python -m rcsd_topo_poc t02-fix-node-error-2 --help
.venv/bin/python -m rcsd_topo_poc t02-aggregate-continuous-divmerge --help
```

- `t02-fix-node-error-2` 是独立离线修复工具，只处理 `node_error_2` 相关修复，不属于 stage 主流程
- `t02-aggregate-continuous-divmerge` 是独立离线聚合工具：
  - 输入为带 `has_evd / is_anchor / kind_2` 的 stage2 `nodes` 与配套 `roads`
  - 候选只取代表 node 满足 `has_evd = yes`、`is_anchor = no`、`kind_2 in {8,16}`
  - 连续链识别语义对齐 T04 continuous chain：
    - `diverge -> merge` 距离阈值 `75m`
    - 其他连续 pair 距离阈值 `50m`
    - 仅沿 `direction in {2,3}` 的有效有向 road 搜索
  - 对每个可聚合 DAG component：
    - 取 `grade` 最高等级节点（`1` 最高）为 mainnode
    - mainnode 写 `kind = 128`、`kind_2 = 128`
    - 其余 node 写 `mainnodeid = <mainnodeid>`、`grade = 0`、`kind = 0`、`grade_2 = 0`、`kind_2 = 0`
    - component 内连续链路的 `roads.formway = 2048`
    - mainnode 的 `subnodeid` 当前写为整组 node id 的逗号拼接，包含 mainnode 自身
  - 输出独立 `nodes_fix.gpkg / roads_fix.gpkg / continuous_divmerge_report.json`
  - `continuous_divmerge_report.json` 必须同步输出：
    - `counts.complex_junction_count`
    - `complex_mainnodeids`
  - CLI 结束时必须打印复杂路口数量和 `mainnodeid` 列表摘要
  - 该工具不回写 stage3 / stage4 产物，也不属于统一锚定主线

### 4.5 程序内入口

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
- [stage4_divmerge_virtual_polygon.py](/mnt/e/Work/RCSD_Topo_Poc/src/rcsd_topo_poc/modules/t02_junction_anchor/stage4_divmerge_virtual_polygon.py)
  - `run_t02_stage4_divmerge_virtual_polygon(...)`
  - `run_t02_stage4_divmerge_virtual_polygon_cli(args)`
- [aggregate_continuous_divmerge.py](/mnt/e/Work/RCSD_Topo_Poc/src/rcsd_topo_poc/modules/t02_junction_anchor/aggregate_continuous_divmerge.py)
  - `run_t02_aggregate_continuous_divmerge(...)`
  - `run_t02_aggregate_continuous_divmerge_cli(args)`

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

### 5.3 Stage4 参数

- 必选输入：
  - `nodes_path`
  - `roads_path`
  - `drivezone_path`
  - `rcsdroad_path`
  - `rcsdnode_path`
  - `mainnodeid`
- 可选高优先级局部参考：
  - `divstripzone_path`
- 可选兼容：
  - `nodes_layer / roads_layer / drivezone_layer / divstripzone_layer / rcsdroad_layer / rcsdnode_layer`
  - `nodes_crs / roads_crs / drivezone_crs / divstripzone_crs / rcsdroad_crs / rcsdnode_crs`
- 可选输出控制：
  - `out_root`
  - `run_id`
  - `debug`

### 5.4 连续分歧 / 合流聚合工具参数

- 必选输入：
  - `nodes_path`
  - `roads_path`
  - `nodes_fix_path`
  - `roads_fix_path`
- 可选兼容：
  - `nodes_layer / roads_layer`
  - `nodes_crs / roads_crs`
- 可选输出：
  - `report_path`

### 5.5 参数原则

- 所有输入兼容都必须显式声明；不能猜字段、猜 CRS、猜 fallback。
- stage1 当前没有业务阈值参数，也不开放 stage2 相关参数。
- stage2 当前已实现最小必要参数，不补写最终锚定决策参数。
- 本文件只固化长期参数类别与语义，不复制完整 CLI 参数表。

## 6. Examples

```bash
.venv/bin/python -m rcsd_topo_poc t02-stage1-drivezone-gate \
  --segment-path /mnt/d/TestData/POC_Data/first_layer_road_net_v0/T01/segment.gpkg \
  --nodes-path /mnt/d/TestData/POC_Data/first_layer_road_net_v0/T01/nodes.gpkg \
  --drivezone-path /mnt/d/TestData/POC_Data/patch_all/DriveZone.gpkg \
  --out-root /mnt/d/Work/RCSD_Topo_Poc/outputs/_work/t02_stage1_drivezone_gate \
  --run-id t02_stage1_run
```

```bash
.venv/bin/python -m rcsd_topo_poc t02-virtual-intersection-poc \
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
.venv/bin/python -m rcsd_topo_poc t02-stage4-divmerge-virtual-polygon \
  --nodes-path /mnt/d/TestData/POC_Data/first_layer_road_net_v0/T02/nodes.gpkg \
  --roads-path /mnt/d/TestData/POC_Data/first_layer_road_net_v0/T02/roads.gpkg \
  --drivezone-path /mnt/d/TestData/POC_Data/patch_all/DriveZone.gpkg \
  --divstripzone-path /mnt/d/TestData/POC_Data/patch_all/DivStripZone.gpkg \
  --rcsdroad-path /mnt/d/TestData/POC_Data/RC4/RCSDRoad.gpkg \
  --rcsdnode-path /mnt/d/TestData/POC_Data/RC4/RCSDNode.gpkg \
  --mainnodeid 100 \
  --out-root /mnt/d/Work/RCSD_Topo_Poc/outputs/_work/t02_stage4_divmerge_virtual_polygon \
  --run-id t02_stage4_divmerge_demo \
  --debug
```

```bash
.venv/bin/python -m rcsd_topo_poc t02-aggregate-continuous-divmerge \
  --nodes-path /mnt/d/TestData/POC_Data/first_layer_road_net_v0/T02/nodes.gpkg \
  --roads-path /mnt/d/TestData/POC_Data/first_layer_road_net_v0/T02/roads.gpkg \
  --nodes-fix-path /mnt/d/Work/RCSD_Topo_Poc/outputs/_work/t02_continuous_divmerge/nodes_fix.gpkg \
  --roads-fix-path /mnt/d/Work/RCSD_Topo_Poc/outputs/_work/t02_continuous_divmerge/roads_fix.gpkg \
  --report-path /mnt/d/Work/RCSD_Topo_Poc/outputs/_work/t02_continuous_divmerge/continuous_divmerge_report.json
```

```bash
.venv/bin/python -m rcsd_topo_poc t02-virtual-intersection-poc \
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
.venv/bin/python -m rcsd_topo_poc t02-export-text-bundle \
  --nodes-path /mnt/d/TestData/POC_Data/first_layer_road_net_v0/T02/nodes.gpkg \
  --roads-path /mnt/d/TestData/POC_Data/first_layer_road_net_v0/T02/roads.gpkg \
  --drivezone-path /mnt/d/TestData/POC_Data/patch_all/DriveZone.gpkg \
  --divstripzone-path /mnt/d/TestData/POC_Data/patch_all/DivStripZone.gpkg \
  --rcsdroad-path /mnt/d/TestData/POC_Data/RC4/RCSDRoad.gpkg \
  --rcsdnode-path /mnt/d/TestData/POC_Data/RC4/RCSDNode.gpkg \
  --mainnodeid 765003 \
  --out-txt /mnt/d/Work/RCSD_Topo_Poc/outputs/_work/t02_text_bundle/case_765003.txt
```

```bash
.venv/bin/python -m rcsd_topo_poc t02-export-text-bundle \
  --nodes-path /mnt/d/TestData/POC_Data/first_layer_road_net_v0/T02/nodes.gpkg \
  --roads-path /mnt/d/TestData/POC_Data/first_layer_road_net_v0/T02/roads.gpkg \
  --drivezone-path /mnt/d/TestData/POC_Data/patch_all/DriveZone.gpkg \
  --divstripzone-path /mnt/d/TestData/POC_Data/patch_all/DivStripZone.gpkg \
  --rcsdroad-path /mnt/d/TestData/POC_Data/RC4/RCSDRoad.gpkg \
  --rcsdnode-path /mnt/d/TestData/POC_Data/RC4/RCSDNode.gpkg \
  --mainnodeid 765003 765154 922217 \
  --out-txt /mnt/d/Work/RCSD_Topo_Poc/outputs/_work/t02_text_bundle/cases_pack.txt
```

```bash
.venv/bin/python -m rcsd_topo_poc t02-decode-text-bundle \
  --bundle-txt /mnt/d/Work/RCSD_Topo_Poc/outputs/_work/t02_text_bundle/case_765003.txt
```

```bash
cd /mnt/d/Work/RCSD_Topo_Poc/outputs/_work/t02_text_bundle
.venv/bin/python -m rcsd_topo_poc t02-decode-text-bundle \
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
- `DivStripZone` 作为可选输入携带；仅当显式传入 `--divstripzone-path` 时写入证据包
- 导出结果是单个纯文本文件，默认逻辑内容至少包含：
  - `manifest.json`
  - `drivezone_mask.png`
  - `drivezone.gpkg`
  - `nodes.gpkg`
  - `roads.gpkg`
  - `rcsdroad.gpkg`
  - `rcsdnode.gpkg`
- 若导出时显式提供 `DivStripZone`，bundle 与解包目录额外包含：
  - `divstripzone.gpkg`
  - `size_report.json`
- 打包流程固定为“局部裁剪 -> 压缩归档 -> 文本编码”，不允许直接明文拼接大段原始矢量文本
- 最终 bundle 文本体积必须 `<= 300KB`
- 若超限，入口必须失败退出，并输出体积分析 `size_report`
- `t02-decode-text-bundle` 负责校验 bundle 头尾标识、版本与 checksum，并恢复等价目录结构
- 解包后的 `nodes.gpkg / roads.gpkg / drivezone.gpkg / divstripzone.gpkg(若导出时提供) / rcsdroad.gpkg / rcsdnode.gpkg` 必须恢复为绝对 `EPSG:3857` 坐标并写入 CRS，保证 Stage3 / Stage4 case-package 可直接运行
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
10. Stage3 准出遵循保守原则：允许“应成功的 case 被保守判为 `review_required` / `rejected`”作为待修问题，但不允许“业务上失败的 case 被判为 `accepted` / `success=true`”。凡已知存在语义漏收、错误分支跟踪、foreign `SWSD` 侵入、`T-mouth` 的 `RCSDRoad` / `RCSDNode` 不完整、或几何明显违背业务认知的结果，必须落入失败或复核通道，不得伪装为成功结果。
