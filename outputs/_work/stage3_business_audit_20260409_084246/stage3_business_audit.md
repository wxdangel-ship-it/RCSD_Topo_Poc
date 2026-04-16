# Stage3 虚拟路口锚定独立审计文档

- 生成时间：`2026-04-09 08:42:46 +08:00`
- 仓库：`/mnt/e/Work/RCSD_Topo_Poc`
- 分支：`codex/t02-stage4-divmerge-virtual-polygon`
- 基线提交：`c6248e907d16520169d1a6a71e0eaec7d38f8b72`
- 审计对象：
  - `src/rcsd_topo_poc/modules/t02_junction_anchor/virtual_intersection_poc.py`
  - `src/rcsd_topo_poc/modules/t02_junction_anchor/virtual_intersection_full_input_poc.py`
  - `modules/t02_junction_anchor/INTERFACE_CONTRACT.md`
  - `modules/t02_junction_anchor/architecture/04-solution-strategy.md`
- 文档性质：本文件是独立审计快照，输出在 `outputs/_work`，不纳入现有长期仓库文档体系。

## 1. 审计结论

### 1.1 一句话结论

当前 `Stage3` 不是“只要跑通就算成功”的流程，而是一个“先构面，再做 support 校验，再按显式白名单判断是否业务可接受”的规则引擎。

### 1.2 当前业务范围

- 当前代码只把 `kind_2 in {4, 2048}` 作为 `Stage3` 正式处理范围，来源于 [virtual_intersection_poc.py](/mnt/e/Work/RCSD_Topo_Poc/src/rcsd_topo_poc/modules/t02_junction_anchor/virtual_intersection_poc.py#L58)。
- `full-input` 自动发现候选时，要求代表 node 同时满足：
  - `has_evd = yes`
  - `is_anchor = no`
  - `kind_2 in {4, 2048}`
  - 见 [virtual_intersection_full_input_poc.py](/mnt/e/Work/RCSD_Topo_Poc/src/rcsd_topo_poc/modules/t02_junction_anchor/virtual_intersection_full_input_poc.py#L495)

### 1.3 当前“成功”真正表示什么

- `flow_success = true` 只表示程序跑完了，不能等价为业务成功。
- `success = true` 才表示“效果被当前规则体系接受”。
- `acceptance_class` 的语义：
  - `accepted`：业务准出
  - `review_required`：流程完成，但不准出
  - `rejected`：明确失败

### 1.4 审计发现

1. `Stage3` 的业务准出门槛已经集中到 `_effect_success_acceptance(...)`，这是当前最核心的准出函数，见 [virtual_intersection_poc.py](/mnt/e/Work/RCSD_Topo_Poc/src/rcsd_topo_poc/modules/t02_junction_anchor/virtual_intersection_poc.py#L4772)。
2. `RCSD` 超出 `DriveZone` 的处理不是单一规则，而是“默认硬失败，只有命中白名单才允许软排除”，白名单函数为 `_can_soft_exclude_outside_rc(...)`，见 [virtual_intersection_poc.py](/mnt/e/Work/RCSD_Topo_Poc/src/rcsd_topo_poc/modules/t02_junction_anchor/virtual_intersection_poc.py#L2563)。
3. `own-group nodes` 和声明的 `polygon-support RC` 必须被面合理覆盖，否则直接失败，见 `_validate_polygon_support(...)` 与后续 `anchor_support_conflict` 抛错：
  - [virtual_intersection_poc.py](/mnt/e/Work/RCSD_Topo_Poc/src/rcsd_topo_poc/modules/t02_junction_anchor/virtual_intersection_poc.py#L3871)
  - [virtual_intersection_poc.py](/mnt/e/Work/RCSD_Topo_Poc/src/rcsd_topo_poc/modules/t02_junction_anchor/virtual_intersection_poc.py#L7976)
4. 当前实现已经内置“二度节点不算有效路口”的约束：
  - 本地 `nodes`：二度 foreign node 不触发 foreign junction 约束
  - `RCSDNode`：二度 RC node 不算有效 RC 路口节点
  - 见 [virtual_intersection_poc.py](/mnt/e/Work/RCSD_Topo_Poc/src/rcsd_topo_poc/modules/t02_junction_anchor/virtual_intersection_poc.py#L3971) 与 [virtual_intersection_poc.py](/mnt/e/Work/RCSD_Topo_Poc/src/rcsd_topo_poc/modules/t02_junction_anchor/virtual_intersection_poc.py#L4005)
5. 当前实现与契约存在一个明确分歧：
  - 契约要求正式 `Stage3` 在非 `review_mode` 下应当要求 `is_anchor = no`
  - 但单 case 主流程当前只检查了 `has_evd` 和 `kind_2`，没有把 `is_anchor = no` 作为硬 gate
  - 代码位置见 [virtual_intersection_poc.py](/mnt/e/Work/RCSD_Topo_Poc/src/rcsd_topo_poc/modules/t02_junction_anchor/virtual_intersection_poc.py#L5201)
  - 这意味着：
    - `full-input` 自动发现符合契约
    - 单 case 直跑当前不完全符合契约
6. `review_anchor_gate_bypassed` 常量已定义，但在当前 `Stage3` 单 case 主流程中未真正落地使用，见 [virtual_intersection_poc.py](/mnt/e/Work/RCSD_Topo_Poc/src/rcsd_topo_poc/modules/t02_junction_anchor/virtual_intersection_poc.py#L137)。

## 2. 用业务语言描述 Stage3 在做什么

### 2.1 业务目标

`Stage3` 的目标不是“把附近所有道路都包成一个面”，而是：

- 以一个代表 `mainnodeid` 为中心；
- 在合法 `DriveZone` 范围内；
- 只围出当前语义路口应有的路口面；
- 尽量把与该路口一致的 `RCSDRoad / RCSDNode` 关联进来；
- 如果本地 `nodes` 语义与 `RCSD` 语义冲突，必须给出失败或复核标记，而不是静默糊过去。

### 2.2 业务上的成功定义

业务上的“成功”至少同时满足：

1. 当前路口自己的 `nodes` 被面覆盖。
2. 当前面没有明显越界到别的语义路口。
3. 若存在与本路口同方向、同局部组件的 `RCSDRoad / RCSDNode`，这些对象要么被纳入，要么被明确解释为可忽略的远端/矛盾 RC。
4. 不能用错误的 RC 分支去替代正确 RC 分支。
5. 不能把“流程跑通”误当成“业务成功”。

### 2.3 业务上的失败定义

以下任何一类，都应视为业务失败或至少不可准出：

- 代表 node 不在 Stage3 业务范围内。
- 局部 patch 内没有合法 `DriveZone`。
- 主方向识别不稳定。
- 目标路口自己的 `nodes` 没被覆盖。
- 声明为需要覆盖的 `RCSDRoad / RCSDNode` 没被覆盖。
- `RCSD` 明显跑到 `DriveZone` 外，且无法被规则证明为“可安全忽略”。
- 结果虽然有面，但只能落入 `review_required`，不能算业务成功。

## 3. 当前实现步骤

### 3.1 候选门槛

当前实现先解析 `mainnodeid` 对应的代表 node 和 group：

- 代表 node/group 解析：`_resolve_group(...)`
- 单 case gate：`has_evd == yes` 且 `kind_2 in {4, 2048}`
- 代码见 [virtual_intersection_poc.py](/mnt/e/Work/RCSD_Topo_Poc/src/rcsd_topo_poc/modules/t02_junction_anchor/virtual_intersection_poc.py#L5197)

注意：

- 当前单 case gate 没有把 `is_anchor = no` 作为硬约束。
- 自动发现模式有这条约束，见 [virtual_intersection_full_input_poc.py](/mnt/e/Work/RCSD_Topo_Poc/src/rcsd_topo_poc/modules/t02_junction_anchor/virtual_intersection_full_input_poc.py#L502)。

### 3.2 局部 patch 构建

围绕代表 node 建一个局部分析 patch：

- 默认查询半径：`buffer_m = 100m`
- 默认 north-up patch 大小：`200m`
- 默认栅格分辨率：`0.2m`
- 代码常量见 [virtual_intersection_poc.py](/mnt/e/Work/RCSD_Topo_Poc/src/rcsd_topo_poc/modules/t02_junction_anchor/virtual_intersection_poc.py#L60)

加载对象包括：

- `nodes`
- `roads`
- `DriveZone`
- `RCSDRoad`
- `RCSDNode`

### 3.3 same-patch 过滤

实现会尝试从“group 节点关联的 roads”里解析唯一 `patchid`：

- 如果只得到一个唯一 patch，则：
  - `roads` 只保留同 patch
  - `DriveZone` 只保留同 patch
- 如果解析不到唯一 patch，则不启用 same-patch 过滤
- 代码见：
  - [virtual_intersection_poc.py](/mnt/e/Work/RCSD_Topo_Poc/src/rcsd_topo_poc/modules/t02_junction_anchor/virtual_intersection_poc.py#L1154)
  - [virtual_intersection_poc.py](/mnt/e/Work/RCSD_Topo_Poc/src/rcsd_topo_poc/modules/t02_junction_anchor/virtual_intersection_poc.py#L5358)

审计说明：

- 当前 same-patch 过滤没有同步应用到 `RCSDRoad / RCSDNode`。

### 3.4 RCSD 与 DriveZone 合法性校验

当前实现把“RC 在不在 DriveZone 内”作为强合法性约束：

- relevant RC road/node 若不被 `DriveZone` 覆盖，会先进入 `invalid_rc_*`
- 非 `review_mode` 下默认形成 `rc_outside_drivezone` 硬失败
- `review_mode` 下则只做风险记录和软排除
- 代码见 [virtual_intersection_poc.py](/mnt/e/Work/RCSD_Topo_Poc/src/rcsd_topo_poc/modules/t02_junction_anchor/virtual_intersection_poc.py#L5414)

### 3.5 主方向与分支证据识别

Stage3 先从 local roads 建分支，再识别主轴：

- 主方向必须能识别出一对近似对向的 main pair
- 夹角容差：`35°`
- 分支匹配 RC 角度容差：`30°`
- 至少要能形成“一进一出”的稳定主轴，否则报 `main_direction_unstable`
- 代码见：
  - [virtual_intersection_poc.py](/mnt/e/Work/RCSD_Topo_Poc/src/rcsd_topo_poc/modules/t02_junction_anchor/virtual_intersection_poc.py#L69)
  - [virtual_intersection_poc.py](/mnt/e/Work/RCSD_Topo_Poc/src/rcsd_topo_poc/modules/t02_junction_anchor/virtual_intersection_poc.py#L1833)

分支证据分三级：

- `arm_full_rc`
  - `rc_support >= 18m` 且 `drivezone_support >= 18m`
- `arm_partial`
  - `drivezone_support >= 10m` 且 `road_support >= 8m`
- `edge_only`
  - 其余

见 [virtual_intersection_poc.py](/mnt/e/Work/RCSD_Topo_Poc/src/rcsd_topo_poc/modules/t02_junction_anchor/virtual_intersection_poc.py#L1823)

### 3.6 RC 分组裁决

当前实现不会把所有 `RCSDRoad` 都纳入，而是先分成：

- `positive_rc_groups`
- `negative_rc_groups`

业务含义：

- `positive`：可解释为当前路口的一部分
- `negative`：被认定为冲突、远端或不应纳入

对 `kind_2 = 2048`，实现还会显式处理“RC 候选歧义”，必要时打 `ambiguous_rc_match` 风险。

见 [virtual_intersection_poc.py](/mnt/e/Work/RCSD_Topo_Poc/src/rcsd_topo_poc/modules/t02_junction_anchor/virtual_intersection_poc.py#L1989)

### 3.7 polygon-support 构建

当前结果面不是简单 buffer，而是由这些要素共同生成：

- 核心中心面
- own-group nodes 的局部支撑
- 主方向道路臂
- 合法 side branch
- 正向 RC group
- endpoint / bridge support
- foreign junction trim 后的修补几何

### 3.8 几何规整

当前实现会做几何规整，而不是直接输出原始 union：

- 与 `DriveZone` 相交
- 去小洞：`18m²` 以下小洞会被填掉
- 最终平滑：`+1m / -1m`
- 去所有 hole
- 只保留与 seed 相连的主组件

见 [virtual_intersection_poc.py](/mnt/e/Work/RCSD_Topo_Poc/src/rcsd_topo_poc/modules/t02_junction_anchor/virtual_intersection_poc.py#L4657)

### 3.9 support validation

这是最关键的硬校验：

- own-group nodes 必须被 polygon 覆盖
- 声明的 support RC nodes 必须被覆盖
- support RC roads 在 `support_clip` 内至少 `90%` 长度被覆盖

阈值：

- 节点覆盖容差：`0.75m`
- 线覆盖比阈值：`0.9`

见 [virtual_intersection_poc.py](/mnt/e/Work/RCSD_Topo_Poc/src/rcsd_topo_poc/modules/t02_junction_anchor/virtual_intersection_poc.py#L3871)

如果 selected association 覆盖失败，会直接报：

- `anchor_support_conflict`

### 3.10 结果状态与准出判定

实现先得到 `status`，再由 `_effect_success_acceptance(...)` 决定是否准出：

- `status` 来自风险组合，不等于最终成功与否
- `acceptance_class` 才是最终准出结论
- `success` 实际等于 `effect_success`

见 [virtual_intersection_poc.py](/mnt/e/Work/RCSD_Topo_Poc/src/rcsd_topo_poc/modules/t02_junction_anchor/virtual_intersection_poc.py#L8122)

## 4. 关键量化门槛

### 4.1 局部 patch 与栅格

| 项目 | 当前值 |
|---|---:|
| `buffer_m` | `100.0m` |
| `patch_size_m` | `200.0m` |
| `resolution_m` | `0.2m` |

### 4.2 道路/RC 基础 buffer

| 项目 | 当前值 |
|---|---:|
| `ROAD_BUFFER_M` | `3.5m` |
| `RC_ROAD_BUFFER_M` | `3.5m` |
| `NODE_SEED_RADIUS_M` | `6.0m` |
| `RC_NODE_SEED_RADIUS_M` | `2.0m` |
| `MAIN_BRANCH_HALF_WIDTH_M` | `7.0m` |
| `SIDE_BRANCH_HALF_WIDTH_M` | `5.0m` |

### 4.3 方向与关联阈值

| 项目 | 当前值 |
|---|---:|
| 主轴对向容差 `MAIN_AXIS_ANGLE_TOLERANCE_DEG` | `35°` |
| branch/RC 匹配容差 `BRANCH_MATCH_TOLERANCE_DEG` | `30°` |
| RC proximity | `18m` |

### 4.4 RC outside DriveZone 相关阈值

| 项目 | 当前值 |
|---|---:|
| relevance 忽略 margin | `25m` |
| relevance 最大距离 | `50m` |
| soft exclude 最小远距 | `18m` |

### 4.5 support / geometry 相关阈值

| 项目 | 当前值 |
|---|---:|
| support seed 最远距离 | `8m` |
| support expansion hops | `2` |
| support expansion 最远距离 | `32m` |
| support clip 半径 | `18m` |
| endpoint support 最长 | `70m` |
| support validation 容差 | `0.75m` |
| support 线覆盖比 | `0.9` |
| 小洞填补面积阈值 | `18m²` |
| 最终保留组件最小面积 | `1m²` |
| 最终平滑 | `1m` |

## 5. 成功/失败/复核门槛

### 5.1 status 与 acceptance 不是一回事

`status` 是当前效果属于哪一类；`acceptance_class` 才决定是否准出。

当前稳定状态枚举：

- `stable`
- `surface_only`
- `weak_branch_support`
- `ambiguous_rc_match`
- `no_valid_rc_connection`
- `node_component_conflict`

### 5.2 直接准出的状态

#### A. `stable`

- 当前实现只要 `status == stable`，且没有被 `rc_outside_drivezone` 硬失败拦下，就直接 `accepted`
- 代码见 [virtual_intersection_poc.py](/mnt/e/Work/RCSD_Topo_Poc/src/rcsd_topo_poc/modules/t02_junction_anchor/virtual_intersection_poc.py#L4805)

业务解释：

- 本地 nodes、道路臂、RC 关联和 polygon-support 没有触发明显风险，系统认为这是“标准成功面”。

#### B. `surface_only`

可准出的只有两种：

1. 完全没有本地 RC 数据：
   - `local_rc_road_count == 0`
   - `effective_local_rc_node_count == 0`
   - 没有被排除的本地 RC
2. 本地虽然有数据，但没有形成连通 RC 证据：
   - `connected_rc_group_count == 0`
   - `associated_rc_road_count == 0`
   - `polygon_support_rc_road_count == 0`

否则：

- `review_required`

#### C. `no_valid_rc_connection`

这是当前最复杂的一类“可接受缺失”状态。实现允许它在以下白名单里准出：

1. `rc_gap_with_compact_local_mouth_geometry`
   - 本地结构很小，局部 mouth 几何紧凑，没有额外 side polygon。
2. `rc_gap_without_connected_local_rcsd_evidence`
   - 本地根本没有形成有效 RC 连通。
3. `rc_gap_with_compact_mainline_geometry`
   - 没有 positive RC，也没有结构性 side branch，面基本是主线紧凑核。
4. `rc_gap_with_only_weak_unselected_edge_rc_groups`
   - 只有很弱、未选中的 edge RC 尾巴。
5. `rc_gap_without_structural_side_branch`
   - 有单个 positive RC 但没有结构性 side branch。
6. `rc_gap_with_compact_edge_rc_tail`
   - 只有紧凑的 edge RC 尾部。
7. `rc_gap_with_single_weak_edge_side_branch`
   - 只有一个较弱的 edge side branch。
8. `rc_gap_with_long_weak_unselected_edge_branch`
   - 存在长但弱的未选中边缘支路。
9. `rc_gap_with_nonmain_branch_polygon_coverage`
   - 非主分支 polygon 覆盖达到 `>= 4m`。

若不满足白名单：

- `review_required`

#### D. `node_component_conflict`

只在两类情形下可准出：

1. `node_component_conflict_with_strong_rc_supported_side_coverage`
   - `polygon_support_rc_road_count >= 2`
   - `associated_rc_road_count >= 2`
   - `max_selected_side_branch_covered_length_m >= 12m`
   - `max_nonmain_branch_polygon_length_m >= 10m`
2. `node_component_conflict_with_remote_outside_rc_gap`
   - side coverage 更强
   - 同时无效 RC 距中心 `>= 25m`

否则：

- `review_required`

#### E. `ambiguous_rc_match`

这类不是“RC 完全正确匹配”，而是“主 RC 有歧义，但当前面仍被允许作为业务可接受结果”。可准出的白名单有：

1. `ambiguous_main_rc_gap_with_nonmain_branch_polygon_coverage`
2. `ambiguous_main_rc_gap_with_compact_polygon`
3. `ambiguous_main_rc_gap_with_compact_supported_polygon`
4. `ambiguous_main_rc_gap_with_supported_branch_polygon_coverage`

核心特征是：

- 主 RC 有负组或歧义；
- 但非主分支 polygon 足够明确；
- 局部 graph 规模受控；
- 没有出现开放式扩张。

否则：

- `review_required`

### 5.3 一律不准出的状态

#### `weak_branch_support`

- 当前实现直接 `review_required`
- 不允许准出

#### `review_mode`

- 当前实现里，只要 `review_mode = true`，准出函数直接返回：
  - `success = false`
  - `acceptance_class = review_required`
  - `acceptance_reason = review_mode`

也就是说：

- `review_mode` 的产物只用于分析，不得当成正式成功结果。

### 5.4 明确失败口径

以下属于明确失败：

- `missing_required_field`
- `invalid_crs_or_unprojectable`
- `representative_node_missing`
- `mainnodeid_not_found`
- `mainnodeid_out_of_scope`
- `main_direction_unstable`
- `anchor_support_conflict`
- `rc_outside_drivezone`

这些失败会进入：

- `acceptance_class = rejected`
- `flow_success = false`

### 5.5 RC outside DriveZone 的准出门槛

这是当前最重要的失败拦截之一。

默认规则：

1. relevant `RCSDRoad / RCSDNode` 不在 `DriveZone` 内，先记为无效 RC。
2. 非 `review_mode` 下默认是硬失败。
3. 只有 `_can_soft_exclude_outside_rc(...)` 返回 `true` 时，才允许把这些 RC 视为“矛盾外部 RC”并软排除。

当前白名单的总体特征：

- `status` 必须落在可放宽的有限集合里；
- 不能是随意放宽，而是要满足组合门槛：
  - 选中 RC 数量
  - polygon-support RC 数量
  - 非主分支覆盖长度
  - 无效 RC 距离中心距离
  - 本地 graph 规模上限
  - 是否存在有效 RC 节点
  - 是否有关联非零 `mainnodeid`
  - 是否存在 negative RC group

审计判断：

- 这是一套明确的“白名单放宽”体系，不是普适推理。
- 该函数当前规则较多，属于实现复杂度最高、最容易造成回归漂移的区域之一。

## 6. 当前实现中的关键业务语义

### 6.1 二度节点不作为有效路口

当前实现已经把“二度节点不算有效路口”落到了核心判定中：

- local `nodes`
  - 若节点 degree = 2，不视为 foreign local junction
- `RCSDNode`
  - 若 degree = 2，不视为有效 RC junction node

这与业务上“过路节点不应主导路口成败”的要求是一致的。

### 6.2 foreign junction 约束

当前面构建过程中，会主动压制“别的语义路口节点”：

- foreign local junction node 会触发 exclusion/trim
- degree = 2 的过路节点不会触发这条规则

业务意义：

- 可以覆盖必要的二度连接节点；
- 但不允许把别的语义路口整体包进来。

### 6.3 几何规整目标

当前最终几何规整体现出的业务目标是：

- 面必须在 `DriveZone` 内；
- 不允许保留小洞；
- 最终不允许保留 hole；
- 不允许保留远离 seed 的碎片组件；
- 输出的是“以目标路口为中心的主组件”，不是整个 patch 的 union。

## 7. 契约与实现差异

### 7.1 `is_anchor = no` 单 case gate 未完全落实

契约要求：

- 非 `review_mode` 下，代表 node 应满足 `is_anchor = no`

当前实现现状：

- `full-input` 自动发现满足该约束
- 单 case 主流程不满足该约束

这意味着当前有一个实际风险：

- 用户直接跑单 case 时，理论上可能把本不该进入 Stage3 的代表 node 跑进来
- 这会造成“自动发现口径”和“手工单 case 口径”不一致

### 7.2 `review_anchor_gate_bypassed` 未真正落地

当前定义了这个 review 风险码，但在 Stage3 单 case 主流程中没有形成真正的 anchor gate 分支与审计落点。

业务后果：

- 当前无法在状态层明确区分：
  - “本来就合法进入 Stage3”
  - “只是在 review_mode 下临时绕过 anchor gate”

### 7.3 `same patch` 过滤只落到 roads / DriveZone

当前 `same patch` 只约束：

- `roads`
- `DriveZone`

没有同样约束到：

- `RCSDRoad`
- `RCSDNode`

业务含义：

- 当前 Stage3 仍可能看到跨 patch 的 RC 候选，只是后续再靠 DriveZone / support / foreign trim / outside-RC 规则收口。

## 8. 准出门槛建议

以下是按当前实现可直接落地的“业务准出门槛”。

### 8.1 单 case 准出

一个 `Stage3` case 只有同时满足以下条件，才应被业务认定为成功：

1. `flow_success = true`
2. `success = true`
3. `acceptance_class = accepted`
4. `review_mode = false`
5. 没有落入明确失败原因
6. 没有未处理的 `anchor_support_conflict`
7. 没有未被白名单允许的 `rc_outside_drivezone`

### 8.2 批量准出

一个批次只有在以下条件同时满足时，才应进入业务放行：

1. 所有待放行 case 都满足单 case 准出门槛
2. `review_required` 不算成功
3. `flow_success = true` 但 `success = false` 的 case 必须进入问题池，而不是计入成功
4. 失败 case 必须输出统一目视图，便于人工复核

### 8.3 业务上必须特别关注的边缘状态

以下状态虽然可以在当前规则下被 `accepted`，但业务上应当理解为“条件性接受”，不是“强成功”：

- `surface_only_*`
- `rc_gap_*`
- `ambiguous_main_rc_gap_*`
- `node_component_conflict_*`

它们的共同特征是：

- 系统承认 RC 证据并不完美；
- 但在当前规则下，认为本地路口面的业务语义仍可接受。

## 9. 建议作为后续治理项的审计问题

1. 把单 case 的 `is_anchor = no` gate 补齐到正式实现，消除与契约的偏差。
2. 把 `review_anchor_gate_bypassed` 变成真正可见的状态，而不是只定义常量。
3. 将 `_can_soft_exclude_outside_rc(...)` 从单文件大白名单改造成：
   - 可解释的规则分组
   - 可独立测试的子策略
   - 更稳定的业务命名
4. 明确是否要把 `same patch` 同步应用到 `RCSDRoad / RCSDNode`。
5. 将“`stable` 直接 accepted”之外，再加一层更业务化的几何准出检查，例如：
   - foreign semantic node 误包率
   - 非必要 side arm 臂悬长度
   - T 口头部覆盖充分性

## 10. 最终审计口径

按当前实现，`Stage3` 的正式业务口径应理解为：

- 它是一个“有显式成功白名单和失败白名单”的规则型路口面生成器；
- “成功”不等于“RC 全对”，而是“在当前规则下，面与局部 RC/道路语义足够一致，可以准出”；
- “失败”不等于“没有面”，而是“当前面无法被规则证明为业务可接受结果”；
- “review_required” 不是成功，只是流程完成后的待人工决策状态。

如果只用一句业务话术总结：

> Stage3 当前的准出标准是“局部路口面 + 本路口 own-group nodes + 可解释 RC 支撑”三者同时成立；任意一项缺失或互相冲突，就不能把它当成业务成功。
