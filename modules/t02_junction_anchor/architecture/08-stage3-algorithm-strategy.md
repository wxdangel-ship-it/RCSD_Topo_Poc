# 08 Stage3 算法策略说明

## 1. 文档定位

- 状态：`current implementation strategy / stage3 raster explanation`
- 作用：
  - 解释当前 stage3 实现如何从局部输入数据构造虚拟路口面。
  - 重点说明栅格算法不是“额外附属技巧”，而是当前实现把业务需求落成几何结果的主机制。
- 当前实现依据：
  - [virtual_intersection_poc.py](/mnt/e/Work/RCSD_Topo_Poc/src/rcsd_topo_poc/modules/t02_junction_anchor/virtual_intersection_poc.py)
  - [virtual_intersection_full_input_poc.py](/mnt/e/Work/RCSD_Topo_Poc/src/rcsd_topo_poc/modules/t02_junction_anchor/virtual_intersection_full_input_poc.py)

## 2. 总体策略概览

Stage3 当前不是“先画一个面，再拿 RC 修补”，而是下面这条链路：

1. 锁定目标 `mainnodeid` 与 own-group nodes
2. 在代表 node 周边截取局部 patch
3. 从 `roads` 提取道路分支，从 `RCSDRoad` 提取 RC 分支
4. 通过射线采样估计每个分支在 `DriveZone / roads / RC` 上的支撑长度
5. 用这些分支证据确定：
   - 主方向
   - 非主方向是否应入面
   - 正向 RC 组与负向 RC 组
6. 把核心、节点、道路口门、RC 支撑都转成统一栅格 mask
7. 在栅格空间做连通、闭运算、排除、重引入和主面提取
8. 再把 mask 转回 polygon，并做几何正则化
9. 用 support validation 检查“面是否真的覆盖了应覆盖的 own-group / RC 支撑”
10. 基于状态、风险和几何指标给出 `success / acceptance_class`

换句话说：

- 业务需求的“必须覆盖 own-group nodes”“不能吞邻接路口”“RC 缺失不必失败”“RC 矛盾必须失败”
- 最终都通过“局部证据选择 + 栅格 mask 组合 + 支撑验证”来落地

## 3. 局部 patch 与统一空间基准

### 3.1 为什么先裁局部 patch

Stage3 不直接在全图上做几何运算，而是先围绕目标代表 node 构造局部 patch。

当前单 case 主入口 [run_t02_virtual_intersection_poc](/mnt/e/Work/RCSD_Topo_Poc/src/rcsd_topo_poc/modules/t02_junction_anchor/virtual_intersection_poc.py#L3207) 中：

- 用代表 node 的 geometry 做 `buffer_m` 查询窗口
- 在该窗口内分别加载：
  - `nodes`
  - `roads`
  - `DriveZone`
  - `RCSDRoad`
  - `RCSDNode`

这样做的算法目的不是省事，而是：

- 把问题收敛为“当前路口局部组件”的几何问题
- 限制错误吸纳远端 roads / RC 的概率
- 保持 patch 内所有后续 mask 的像素意义一致

### 3.2 为什么必须统一 CRS

当前实现要求所有空间判断统一到 `EPSG:3857`。

算法上这是必须的，因为：

- `buffer_m / patch_size_m / resolution_m` 都是米单位
- 道路缓冲宽度、节点 buffer 半径、RC 线覆盖长度阈值都依赖真实长度
- 如果 CRS 不统一，射线支持长度和 mask 尺寸就没有业务意义

## 4. 分支证据提取

### 4.1 roads 分支

当前实现先从 own-group nodes 触达的 `roads` 中提取 incident roads，再聚合成道路分支。

关键函数：

- [_build_road_branches_for_member_nodes](/mnt/e/Work/RCSD_Topo_Poc/src/rcsd_topo_poc/modules/t02_junction_anchor/virtual_intersection_poc.py#L1771)
- [_cluster_branch_candidates](/mnt/e/Work/RCSD_Topo_Poc/src/rcsd_topo_poc/modules/t02_junction_anchor/virtual_intersection_poc.py#L1640)

主要动作：

- 先去掉 group 内部自循环 / 内部连接 roads
- 只保留真正从路口向外发散的 incident roads
- 按角度相近聚成 branch

这样做的业务意义是：

- Stage3 关心的是“路口有哪些口门方向”，不是每条细碎线段

### 4.2 RC 分支

RC 分支提取分两种：

- 若本地存在当前 `mainnodeid` 对应的 `RCSDNode` 组，就从 incident `RCSDRoad` 提取
- 否则退化到“围绕中心点的近邻 RC 分支”

关键函数：

- incident RC 路径
- [_branch_candidate_from_center_proximity](/mnt/e/Work/RCSD_Topo_Poc/src/rcsd_topo_poc/modules/t02_junction_anchor/virtual_intersection_poc.py#L1599)

这正对应业务上的两类场景：

- RC 完整型
- RC 缺口型

### 4.3 主方向识别

主方向不是靠字段直接给出，而是从道路分支中选一对近似对向的 branch。

关键函数：

- [_select_main_pair](/mnt/e/Work/RCSD_Topo_Poc/src/rcsd_topo_poc/modules/t02_junction_anchor/virtual_intersection_poc.py#L1734)

当前约束是：

- 角度接近 180 度
- 至少一侧有 incoming support
- 至少一侧有 outgoing support
- 优先选择 `road_support + drivezone_support` 更强的一对

业务上，这保证：

- 主方向由当前路口真实道路结构决定
- 不是简单依赖 RC 或单边支路

## 5. 栅格算法的核心逻辑

## 5.1 栅格不是后处理，而是主计算空间

当前实现中，真正把“道路 / DriveZone / RC / 节点”揉成路口面的，是栅格空间。

关键函数：

- [_build_grid](/mnt/e/Work/RCSD_Topo_Poc/src/rcsd_topo_poc/modules/t02_junction_anchor/virtual_intersection_poc.py#L1160)
- [_rasterize_geometries](/mnt/e/Work/RCSD_Topo_Poc/src/rcsd_topo_poc/modules/t02_junction_anchor/virtual_intersection_poc.py#L1186)
- [_extract_seed_component](/mnt/e/Work/RCSD_Topo_Poc/src/rcsd_topo_poc/modules/t02_junction_anchor/virtual_intersection_poc.py#L1240)
- [_mask_to_geometry](/mnt/e/Work/RCSD_Topo_Poc/src/rcsd_topo_poc/modules/t02_junction_anchor/virtual_intersection_poc.py#L1264)

### 5.2 Grid 如何定义

Grid 由三个量决定：

- `analysis_center`
- `patch_size_m`
- `resolution_m`

当前默认是：

- patch 尺寸约 `200m`
- 分辨率约 `0.2m`

结果是一个以分析中心为中心的规则像素网格。

每个像素表达的业务语义是：

- “这个位置是否被某类局部证据覆盖”

### 5.3 为什么用 mask

mask 让算法可以把不同来源的几何统一成可组合的布尔空间：

- `drivezone_mask`
- `road_mask`
- `rc_road_mask`
- `node_seed_mask`
- `support_rc_node_seed_mask`

这样做的好处：

- 线、点、面都能被归一化处理
- 可以直接做闭运算、连通分量提取、排除和重引入
- 比直接在矢量空间做大量布尔运算更容易表达“局部口门连通性”

## 5.4 射线采样如何把业务支撑变成数值证据

当前实现对每个 branch 都会沿 branch 角度做射线采样。

关键函数：

- [_ray_support_m](/mnt/e/Work/RCSD_Topo_Poc/src/rcsd_topo_poc/modules/t02_junction_anchor/virtual_intersection_poc.py#L1692)

它分别在不同 mask 上量测：

- `drivezone_support_m`
- `rc_support_m`

加上前面从道路几何本身得到的 `road_support_m`，共同构成 branch 的证据向量。

这一步直接服务于业务需求：

- 判断某个方向是不是主口门
- 判断侧支是 `arm_full_rc / arm_partial / edge_only`
- 判断 RC 是缺失、歧义还是矛盾

## 5.5 当前不是 marching squares，而是“行扫描拼盒 + union”

mask 转 polygon 的方式不是 marching squares。

当前 [_mask_to_geometry](/mnt/e/Work/RCSD_Topo_Poc/src/rcsd_topo_poc/modules/t02_junction_anchor/virtual_intersection_poc.py#L1264) 做的是：

1. 按行扫描 mask
2. 把连续的 `True` 像素压成一个个矩形条带
3. 把所有条带做 `unary_union`

这样做的结果是：

- polygon 边界天然沿网格边界
- 先得到保守、稳定、可控的体素化路口面
- 再由后续平滑和正则化把几何从“像素面”收成可接受业务面

## 6. 从分支证据到 polygon-support

### 6.1 正向 RC 组 / 负向 RC 组

当前实现不会把所有 RC 都拿来补面，而是先分：

- positive RC groups
- negative RC groups

关键函数：

- [_build_positive_negative_rc_groups](/mnt/e/Work/RCSD_Topo_Poc/src/rcsd_topo_poc/modules/t02_junction_anchor/virtual_intersection_poc.py#L1895)

其核心思想是：

- 主方向和被选中的侧支可以贡献正向 RC
- 与当前口门方向矛盾或竞争的组进入负向 RC
- 对 `kind_2 = 2048` 的 T 型场景，允许只选最强侧支组，但会保留歧义风险

### 6.2 RC 关联与 polygon-support 解耦

当前实现明确允许：

- `associated_rcsdroad / associated_rcsdnode`
- `polygon_support_rc_road_ids / polygon_support_rc_node_ids`

不完全相同。

这是有意设计，不是权宜之计。

业务原因：

- 最终下发的 RC 关联要保守
- 但 polygon-support 需要更完整地表达局部支撑组件

对应关键函数：

- [_select_positive_rc_road_ids](/mnt/e/Work/RCSD_Topo_Poc/src/rcsd_topo_poc/modules/t02_junction_anchor/virtual_intersection_poc.py#L2032)
- [_build_polygon_support_from_association](/mnt/e/Work/RCSD_Topo_Poc/src/rcsd_topo_poc/modules/t02_junction_anchor/virtual_intersection_poc.py#L2533)
- [_build_polygon_support_clip](/mnt/e/Work/RCSD_Topo_Poc/src/rcsd_topo_poc/modules/t02_junction_anchor/virtual_intersection_poc.py#L2751)

### 6.3 RC 缺口为什么仍能成功

当前实现里，某些 branch 即使没有最终有效 RC 连接，也会被允许贡献 polygon 长度。

关键函数：

- [_branch_has_positive_rc_gap](/mnt/e/Work/RCSD_Topo_Poc/src/rcsd_topo_poc/modules/t02_junction_anchor/virtual_intersection_poc.py#L2140)
- [_rc_gap_branch_polygon_length_m](/mnt/e/Work/RCSD_Topo_Poc/src/rcsd_topo_poc/modules/t02_junction_anchor/virtual_intersection_poc.py#L2166)
- [_branch_has_local_road_mouth](/mnt/e/Work/RCSD_Topo_Poc/src/rcsd_topo_poc/modules/t02_junction_anchor/virtual_intersection_poc.py#L2193)
- [_branch_has_minimal_local_road_touch](/mnt/e/Work/RCSD_Topo_Poc/src/rcsd_topo_poc/modules/t02_junction_anchor/virtual_intersection_poc.py#L2229)

这部分正是“RC missing 不自动失败”的算法落点：

- 若本地道路口门和 DriveZone 已经提供足够几何证据
- 即使 RC 缺失，也允许给该 branch 一个保守但非零的 polygon 长度

## 7. polygon 是如何被拼出来的

### 7.1 核心 seed

当前 polygon 从一个围绕 `analysis_center` 的 core 开始。

它保证：

- 路口中心一定存在一个连通起点
- 后续无论怎么排除，都不会把结果变成完全离散碎片

### 7.2 support_geometries 的组成

当前 `support_geometries` 主要由以下几类构成：

- core geometry
- group node buffers 与 group node connectors
- 各个 branch 的 connector / tip / local mouth fan
- selected RC node buffers / connectors
- polygon-support RC road buffers

其中最关键的是：

- group nodes 负责保证 own-group must-cover
- side branch 的 local mouth fan 负责让支路口门真正长出来
- positive RC support 负责把局部 RC 连通证据映射到面中

### 7.3 为什么要有 mandatory_support

不是所有 support 几何都同等重要。

当前实现专门构造了 `mandatory_support_geometries`，用于确保：

- own-group node 周边
- 必须保留的 branch mouth
- 必须保留的 RC node / RC road 支撑

不会在后续闭运算、差集和正则化中被意外抹掉。

这一步直接对应你前面一系列样例修复中的经验：

- 如果不把这些几何提升为 mandatory，算法会输出“看上去差一点”的细长口门或被抹平的小面

## 8. 栅格后处理如何把 support 变成主面

### 8.1 初始 candidate polygon

当前流程是：

1. `support_union = unary_union(support_geometries)`
2. 对 `support_union` 做一次轻量 buffer 平滑
3. 与 `DriveZone` 相交
4. 再 rasterize 成 `polygon_mask`

### 8.2 mask 级几何操作

在 mask 空间里，当前会做：

- exclusion mask：去掉负向 RC 或被排除的 RC 支撑
- `_binary_close`：把小裂缝闭合
- own-group reinclude：把 group node 周边重新并回
- `_extract_seed_component`：只保留与核心 seed 连通的主连通域

这四步分别对应业务需求：

- 不能吃错 RC
- 不能因为细小像素缝隙把同一路口断开
- 不能丢掉 own-group nodes
- 不能输出多面碎片

### 8.3 转回 polygon 后的矢量正则化

mask 转回矢量后，当前还会继续做：

- 平滑 buffer / negative buffer
- fill small holes
- remove all holes
- 只保留包含 seed 的主面

关键函数：

- [_fill_small_polygon_holes](/mnt/e/Work/RCSD_Topo_Poc/src/rcsd_topo_poc/modules/t02_junction_anchor/virtual_intersection_poc.py#L2811)
- [_remove_all_polygon_holes](/mnt/e/Work/RCSD_Topo_Poc/src/rcsd_topo_poc/modules/t02_junction_anchor/virtual_intersection_poc.py#L2838)
- [_select_seed_connected_polygon](/mnt/e/Work/RCSD_Topo_Poc/src/rcsd_topo_poc/modules/t02_junction_anchor/virtual_intersection_poc.py#L2945)
- [_regularize_virtual_polygon_geometry](/mnt/e/Work/RCSD_Topo_Poc/src/rcsd_topo_poc/modules/t02_junction_anchor/virtual_intersection_poc.py#L2966)

这部分对应的业务目标是：

- 不要多面
- 不要空洞
- 不要碎片
- 保留路口中心主面

## 9. 邻接路口排斥与外来节点剔除

仅靠 must-cover 和正向 RC 支撑还不够，因为 polygon 可能吃进邻接路口。

当前实现专门引入了“foreign node exclusion”：

- 先识别本地 foreign junction nodes
- 对这些节点及其 incident roads 构造排斥几何
- 再从当前 polygon 中扣掉这部分

关键函数：

- [_is_foreign_local_junction_node](/mnt/e/Work/RCSD_Topo_Poc/src/rcsd_topo_poc/modules/t02_junction_anchor/virtual_intersection_poc.py#L2867)
- [_build_foreign_node_exclusion_geometry](/mnt/e/Work/RCSD_Topo_Poc/src/rcsd_topo_poc/modules/t02_junction_anchor/virtual_intersection_poc.py#L2882)

这一步直接服务于业务需求：

- polygon 不得包含其他路口
- T 型口和密集路口群中，不能因为局部 DriveZone 连通就误吸邻口

## 10. support validation 如何兜底

### 10.1 校验对象

当前最终校验不是“面看起来像就算完”，而是显式验证：

- own-group nodes 是否被覆盖
- polygon-support RC nodes 是否被覆盖
- polygon-support RC roads 在裁剪范围内的覆盖比例是否达标

关键函数：

- [_validate_polygon_support](/mnt/e/Work/RCSD_Topo_Poc/src/rcsd_topo_poc/modules/t02_junction_anchor/virtual_intersection_poc.py#L2786)

### 10.2 业务意义

这一步把 stage3 从“几何生成器”变成“有业务约束的锚定器”：

- 如果 own-group nodes 没被覆盖，说明面已经偏离目标路口
- 如果声明为 support 的 RC roads / nodes 没被覆盖，说明当前 polygon 与 RC 支撑不一致

一旦校验失败，当前实现会直接进入：

- `anchor_support_conflict`

而不是静默写出一个看上去差不多的 polygon。

## 11. 成功判定如何建立在几何与证据之上

当前 `success` 不是简单等于“有 polygon 输出”。

判定链路是：

1. 先根据 `risks + associated_rcsdroad_count` 算出 `status`
2. 再根据 `status + 几何指标 + RC 计数 + outside RC 位置关系` 算出：
   - `effect_success`
   - `acceptance_class`
   - `acceptance_reason`

关键函数：

- [_status_from_risks](/mnt/e/Work/RCSD_Topo_Poc/src/rcsd_topo_poc/modules/t02_junction_anchor/virtual_intersection_poc.py#L3056)
- [_effect_success_acceptance](/mnt/e/Work/RCSD_Topo_Poc/src/rcsd_topo_poc/modules/t02_junction_anchor/virtual_intersection_poc.py#L3120)

其中用到的几何/结构指标包括：

- `max_selected_side_branch_covered_length_m`
- `max_nonmain_branch_polygon_length_m`
- `associated_rc_road_count`
- `polygon_support_rc_road_count`
- `connected_rc_group_count`
- `nonmain_branch_connected_rc_group_count`

也就是说：

- 业务成功并不是由单个状态枚举决定
- 而是由“几何是否真的长出应有口门 + RC 证据是否属于缺口还是矛盾”共同决定

## 12. full-input 如何复用同一套算法

full-input 不是另一套几何算法，而是同一单 case worker 的批次编排层。

关键点在 [virtual_intersection_full_input_poc.py](/mnt/e/Work/RCSD_Topo_Poc/src/rcsd_topo_poc/modules/t02_junction_anchor/virtual_intersection_full_input_poc.py)：

- 先做 preflight，确认路径、图层、CRS、feature_count
- 自动发现候选：
  - 代表 node
  - `has_evd = yes`
  - `is_anchor = no`
  - `kind_2 in {4, 2048}`
- 多 case 时共享大图层内存句柄
- 每个 case 仍调用同一个 `run_t02_virtual_intersection_poc`
- 批次层只负责：
  - 调度
  - 汇总
  - `summary / perf_summary / polygons.gpkg / visual_checks`

因此：

- `case-package` 和 `full-input` 在业务语义上应保持一致
- 差异只应存在于输入组织和批次调度，不应存在于核心面生成规则

## 13. 需求到算法步骤的映射

### 13.1 必须覆盖 own-group nodes

由以下步骤共同保证：

- group node buffers / connectors 进入 `support_geometries`
- group node reinclude mask
- `_extract_seed_component`
- `_validate_polygon_support`

### 13.2 必须长出非主方向口门

由以下步骤共同保证：

- 道路分支提取与主方向识别
- side branch 的 `polygon_length_m`
- `local mouth fan` 和 `compact local support`
- `max_nonmain_branch_polygon_length_m` 参与 acceptance

### 13.3 RC 缺失不自动失败

由以下步骤共同保证：

- `rc_gap` 分支逻辑
- `surface_only / no_valid_rc_connection` 的 accepted 子类
- full-input / single-case 都保留 `flow_success` 与 `success` 的区分

### 13.4 RC 矛盾必须失败

由以下步骤共同保证：

- `rc_outside_drivezone` 校验
- 负向 RC group 排除
- foreign junction exclusion
- `anchor_support_conflict`

### 13.5 最终几何要单面、无孔洞、无异常突起

由以下步骤共同保证：

- binary close
- seed connected component extraction
- hole fill / hole remove
- seed-connected main polygon selection
- final regularization

## 14. 当前限制与结构债

### 14.1 单文件结构债

[virtual_intersection_poc.py](/mnt/e/Work/RCSD_Topo_Poc/src/rcsd_topo_poc/modules/t02_junction_anchor/virtual_intersection_poc.py) 当前同时承载：

- 输入读取
- 分支提取
- 栅格构造
- RC 选择
- 几何正则化
- 验收判定
- render 与输出

这导致：

- 算法主链虽然已存在，但知识分散在一个超大文件中
- 后续若继续做效果优化，应优先拆出：
  - branch evidence
  - raster polygon builder
  - acceptance evaluator

### 14.2 当前阈值大量内嵌在实现中

当前实现的很多长度、缓冲宽度、覆盖阈值仍是代码内常量，而不是正式契约。

这意味着：

- 这些值当前属于实现策略，不应被误写成业务固定规则
- 后续若需要正式冻结某些阈值，必须先确认其业务语义，再写回契约

## 15. 与业务需求文档的关系

- [07-stage3-business-requirements.md](/mnt/e/Work/RCSD_Topo_Poc/modules/t02_junction_anchor/architecture/07-stage3-business-requirements.md) 说明“为什么要这样做”。
- 本文档说明“当前代码具体怎样做”。
