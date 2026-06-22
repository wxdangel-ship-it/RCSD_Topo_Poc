# 02 Data And Domain Model

## 1. 输入对象

T03 的正式输入契约固定为 Anchor61 `case-package`，或 internal full-input 从共享图层中按 case 局部查询出的等价上下文。两种输入形态在业务上都必须能解释同一件事：当前 SWSD 语义路口、它所在的道路面、周边道路与可候选的 RCSD 语义对象。

核心输入对象包括：

- `nodes`：SWSD 语义路口、代表 node、候选状态和下游状态更新对象。
- `roads`：SWSD 局部道路、连通关系和方向上下文。
- `DriveZone`：合法活动空间和道路面边界。
- `RCSDRoad`：RCSD 侧 road 证据、关联关系和负向约束来源。
- `RCSDNode`：RCSD 语义路口候选与 relation base 来源。
- 冻结 Step3 工件：`step3_allowed_space.gpkg`、`step3_status.json`、`step3_audit.json`。

所有空间判定统一到 `EPSG:3857`。代表 node、语义路口集合、道路集合、DriveZone 与 RCSD 上下文必须可追溯到当前 case，不允许后续步骤从全量图层隐式补取对象。

## 2. 业务对象与关系

T03 的业务对象不是单一 polygon，而是一组可解释的路口关系事实：

- 当前 SWSD 语义路口：T03 要处理的业务主体。
- 合法活动空间：Step3 冻结出的当前 case 可活动范围。
- RCSD 关联证据：Step4 解释出的 `related / local_required / support / excluded / foreign` 关系。
- hard negative mask：Step5 提供给 Step6 的硬负向约束。
- 受约束候选面：Step6 在合法空间、方向边界和负向约束内形成的候选 polygon。
- formal 发布结果：Step7 输出的 `accepted / rejected` 机器状态、surface、nodes 更新和 relation evidence。

`Step4~Step7` 必须消费冻结 Step3 run root，不得回写 Step3，也不得用后续 cleanup / trim 反证 Step3 成立。

## 3. RCSD 语义分层

T03 不把所有邻近 RCSD 对象都视为当前路口的一部分。RCSD 语义必须按三层解释：

- `related`：当前 SWSD 路口在 RCSD 侧的强语义关联证据。
- `local_required`：Step6 在 directional boundary 内实际消费的 must-cover 子集。
- `foreign_mask`：Step6 hard subtract 的 road-like 掩膜来源。

`related` 不等于全长 must-cover，`foreign_mask` 不得包含已判定为 `related` 的 RCSDRoad。`Step5` 不再向 `Step6` 提供 hard polygon foreign context；`Step6` 当前 hard negative mask 只消费 road-like `1m` 掩膜，不把 node 类 foreign 变成 hard subtract。

## 4. 调头口与 connector 语义

`RCSDNode.mainnodeid` 非空且非 `0` 只表示 RCSD 语义路口候选或 grouping 信号，不单独构成当前路口强关联。effective degree = `2` 的候选仍按非语义 connector 处理。

当 `RCSDRoad.formway` 存在且可解析时，调头口判定优先使用 `(formway & 1024) != 0`。缺少该字段时，几何 fallback 必须以 effective-degree=3 语义路口、主干平行与可信方向相反为直接过滤条件；方向不可用或不可信的候选只能进入 suspect 审计，不得直接过滤。

`Step4 / Step5` 已识别的最终调头口 `RCSDRoad`，不得继续进入 `degree2 connector / chain merge / required-support-excluded`，也不得在 `Step6` 被重新回补为 `local required RC`。

## 5. 几何边界语义

`Step6` 必须遵守 `boundary-first`：

- 先确定 directional boundary。
- 再在该边界内构面。
- 不允许先裁剪再用 `required RC` 把 geometry 补回边界外。

`single_sided_t_mouth + association_class=A` 的横方向口门必须通过 tracing 求解。tracing seed 来自竖方向候选空间内的相关 `RCSDRoad / RCSDRoad chain`；最终确认的 terminal `RCSDNode` 必须落在横方向候选空间内；若 tracing 无法在横方向两侧都确认 terminal `RCSDNode`，横方向回到 generic directional boundary。

若冻结 `Step3` 已对当前 `single_sided_t_mouth` case 应用 `two_node_t_bridge`，`Step6` 必须继承这条 bridge corridor 参与 directional boundary / polygon_seed 计算，不得在横方向截断后留下中心断开或多组件狭长残留。

## 6. internal full-input 数据形态

T03 internal full-input 的正式主执行形态固定为：

1. `candidate discovery`
2. `shared handle preload`
3. `per-case local context query`
4. direct `Step1~Step7` case execution
5. terminal record / streamed append log 写出
6. batch closeout

repo 级主脚本 `scripts/t03_run_internal_full_input_8workers.sh` / `scripts/t03_watch_internal_full_input.sh` 只承接 full-input 运行与监控外壳，不提升为新的 repo 官方 CLI。watch 默认必须按 formal-first 口径监控，并显式区分是否已进入 `case execution` 阶段；默认不把 `V1-V5` 混入顶层监控。

## 7. 下游数据语义

internal full-input run root 必须稳定产出：

- `virtual_intersection_polygons.gpkg`
- `nodes.gpkg`
- `nodes_anchor_update_audit.csv`
- `nodes_anchor_update_audit.json`
- `t03_swsd_rcsd_relation_evidence.csv/json`
- `intersection_match_t03.geojson`

`nodes.gpkg` 的 `is_anchor=fail3` 只属于 T03 downstream output 语义，不回写输入原始 nodes，也不修改上游输入字段契约。

`t03_swsd_rcsd_relation_evidence.csv/json` 是 T05 handoff 输入，不是最终 `intersection_match_all.geojson`。成功建议状态只允许来自 formal `step7_state=accepted` 且具备 required RCSD semantic junction 证据的 case，support-only / road-only 证据不得写成成功匹配。

`intersection_match_t03.geojson` 是 T03 自身 relation 成果。构建时可消费可选 `intersection_match_all.geojson` 做 1:1 校验；若同一个 SWSD 语义路口对应多个 RCSD 语义路口，则取消该 relation 并将代表 node 回退为 `is_anchor=no`。缺省时仍输出 T03 自身 relation 成果，旧 `intersection_match_t07.geojson` 输入仅作为兼容别名保留。

## 8. 约束边界

- 正式主文档不把 `Association / Finalization` 作为业务主结构。
- 历史 finalization wrapper 已退役，不再定义模块级主命名。
- 不新增 T03 repo 官方 finalization CLI。
- 不提交 `outputs/_work`、批量 PNG、线程同步文件到 Git。
