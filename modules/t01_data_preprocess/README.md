# T01 数据预处理模块

## 当前状态
- 当前版本：`T01 Skill v1.0.0`
- 当前主线：普通道路双向路段逐级提取
- 当前已纳入正式能力：
  - working-layer bootstrap
  - roundabout preprocessing
  - Step1-Step5 residual graph 构段
  - raw input 字段保真输出
  - `closed_con in {2,3}`
  - `road_kind != 1`
  - 统一 50m dual / side distance gate
  - 五样例活动基线冻结

## 当前总体业务目标
- T01 当前的总体业务目标是：对普通道路网络中，从高等级到低等级，逐级提取双向联通的路段，为后续关键路口锚定和路段构建打基础。
- 当前明确未启动的扩展方向：
  - 封闭式道路的路段提取
  - 普通道路上的单向路段提取

## 官方入口

### official end-to-end
```bash
python -m rcsd_topo_poc t01-run-skill-v1 \
  --road-path <road_path> \
  --node-path <node_path> \
  --out-root <out_root>
```

说明：
- runner 开始先建立 working Nodes / Roads
- 初始化后立即执行 roundabout preprocessing
- 后续 Step1-Step5 全部运行在 working layers 上
- 若未显式传入 `--out-root`，official runner 默认输出到：
  - `outputs/_work/t01_skill_eval/<run_id>/`

## 分步入口
- `python -m rcsd_topo_poc t01-step1-pair-poc`
- `python -m rcsd_topo_poc t01-step2-segment-poc`
- `python -m rcsd_topo_poc t01-s2-refresh-node-road`
- `python -m rcsd_topo_poc t01-step4-residual-graph`
- `python -m rcsd_topo_poc t01-step5-staged-residual-graph`

用途：
- 调试
- 审计
- case 级排查

## 当前正式业务口径
- 当前模块只处理双向道路路段构建。
- 当前模块不覆盖封闭式道路场景。
- 当前正式输入约束：
  - node：`closed_con in {2,3}`
  - road：`road_kind != 1`
- “全通路口”统一接受：
  - `kind_2 in {4,64}`
- “交叉 + 环岛 + T”统一接受：
  - `kind_2 in {4,64,2048}`
- Step1 当前正式 tracing 约束：
  - 正常 seed 继续保持严格筛选
  - T 型路口不是 Step1 terminate
  - 局部分歧 / 合流节点不会仅因节点类型本身被强制终止；是否继续追踪仍以 `through_node_rule` 与 `hard-stop` 判定为准
- Step2 当前候选策略：
  - `XXXS` 表明需要限制“内部路口挂接侧向结构”在 Step2 直接并入当前主 Segment
  - 候选方向是：按主 Segment 内部路口的本地主通行 `I` 向与侧向 branch 关系来判定，而不是仅按 `one_way_parallel`、attachment 数量或简单路径形态
  - 单侧旁路可包含多条同向单向侧路及短小连接路；反方向 branch 与内部挂接网不应保留
  - 当前仍在收敛，不写成正式全局硬规则
- 各轮 seed / terminate / hard-stop 的正式输入条件以：
  - [INTERFACE_CONTRACT.md](/mnt/e/Work/RCSD_Topo_Poc/modules/t01_data_preprocess/INTERFACE_CONTRACT.md)
  - [spec.md](/mnt/e/Work/RCSD_Topo_Poc/specs/t01-data-preprocess/spec.md)
  为准

## 模块开始阶段

### working bootstrap
- 模块开始即建立 working layers
- working nodes：
  - `grade_2 = grade`
  - `kind_2 = kind`
  - `working_mainnodeid = mainnodeid`
- working roads：
  - `s_grade = null`
  - `segmentid = null`
- raw 字段保真：
  - `mainnodeid` 保持输入原值
  - 运行期 `mainnode` 语义写入新增字段 `working_mainnodeid`

### roundabout preprocessing
- 在 Step1 前按共享 node 的拓扑连通关系聚合环岛 roads
- 环岛 mainnode：
  - `grade_2 = 1`
  - `kind_2 = 64`
- 组内其他 node：
  - `grade_2 = 0`
  - `kind_2 = 0`
- 环岛 mainnode 是受保护语义路口，后续 generic refresh 不得降级或改写

## staged runner 口径
- Step4 继承 Step2 的全量 endpoint pool
- Step5A 继承 Step4 的全量 endpoint pool
- Step5B 继承 Step5A 的全量 endpoint pool
- Step5C 继承 Step5B 的全量 endpoint pool
- staged runner 传递的是全量 `seed / terminate` 端点池，不是只传 validated pair 成功端点
- 若某端点在当前 working graph 上已无剩余可用 road，会自然退出下一轮
- `Step5A / Step5B`：
  - strict staged residual 轮
  - 历史 endpoint 继续同时作为 `seed / terminate / hard-stop`
- `Step5C`：
  - final fallback 轮
  - 不再把所有历史 endpoint 机械等同为 `hard-stop`
  - 改用：
    - `rolling endpoint pool`
    - `protected hard-stop set`
    - `demotable endpoint set`
    - `actual terminate barriers`
  - 当前 `protected hard-stop` 只保留高置信对象：
    - 环岛 mainnode（`kind_2 = 64` 且 `closed_con in {2,3}`）
  - `kind_2 = 1` 不能仅因当前字段条件进入 `rolling endpoint pool`
    - 只有历史 endpoint 才允许以历史身份继续留在 pool 中

## 50m gate
- 50m gate 是双向构段统一约束，不是某单一阶段的局部规则。
- 作用范围：
  - `Step2`
  - `Step4`
  - `Step5A`
  - `Step5B`
  - `Step5C`
- 常量：
  - `MAX_DUAL_CARRIAGEWAY_SEPARATION_M = 50.0`
  - `MAX_SIDE_ACCESS_DISTANCE_M = 50.0`

## 当前输出
- 最终输出：
  - `nodes.geojson`
  - `roads.geojson`
  - `validated_pairs_skill_v1.csv`
  - `segment_body_membership_skill_v1.csv`
  - `trunk_membership_skill_v1.csv`
- 业务含义：
  - `nodes.geojson` 表达当前 working node 语义结果
  - `roads.geojson` 表达当前 working road 语义结果
  - `validated_pairs_skill_v1.csv` 表达最终合法双向路段端点对
  - `segment_body_membership_skill_v1.csv` 表达各 pair 的 pair-specific road body
  - `trunk_membership_skill_v1.csv` 表达各 pair 的 trunk road 归属
  - `debug/step5/STEP5C/step5c_*.csv|geojson|json` 表达 `Step5C adaptive barrier` 审计集合与 demote 判定

## 当前活动基线
- 当前活动基线已经切换为五样例套件：
  - `modules/t01_data_preprocess/baselines/t01_skill_active_five_sample_suite/XXXS/`
  - `modules/t01_data_preprocess/baselines/t01_skill_active_five_sample_suite/XXXS2/`
  - `modules/t01_data_preprocess/baselines/t01_skill_active_five_sample_suite/XXXS3/`
  - `modules/t01_data_preprocess/baselines/t01_skill_active_five_sample_suite/XXXS4/`
  - `modules/t01_data_preprocess/baselines/t01_skill_active_five_sample_suite/XXXS5/`
- 五组样例定位：
  - `XXXS`：通用冒烟
  - `XXXS2`：上下行 / 侧向距离 gate
  - `XXXS3`：环岛
  - `XXXS4`：侧向平行路 / 分歧合流 corridor
  - `XXXS5`：长 corridor 的 `Step5C final fallback` 兜底构段
- 后续性能优化必须与这五组结果对齐。
- 若任一样例不一致，必须先由用户检查确认后再决策。

## 2026-03-21 策略对齐中
- 已确认并已实现的正式规则：
  - `mainnodeid` 原字段保真，运行期改用 `working_mainnodeid`
  - `Step2 / Step4 / Step5` 统一导出按阶段分文件的 `Segment_Road`
- 已确认方向、但尚未完成活动基线收敛的候选规则：
  - `Step2` trunk 搜索保持窄口径，不因局部分叉提前放宽 trunk 候选
  - `segment_body` 候选允许穿过局部分叉，但只应保留符合“侧向平行 corridor”语义的 component
  - 单向平行于主路的 side corridor 可保留为当前 pair 的 `segment_body`
  - 双向平行于主路的 side corridor 不应并入当前 pair，应进入 `step3_residual`
- 当前状态：
  - `XXXS4` 当前结果已通过用户目视确认，并已冻结入活动基线
  - `XXXS5` 当前结果已通过用户目视确认，并已冻结入活动基线
  - 上述 corridor 策略仍处于文档候选规则收敛阶段，不将局部样例现象直接固化为新的 accepted 强规则
  - 详见 `modules/t01_data_preprocess/history/014-step2-parallel-corridor-strategy-alignment.md`

## 外网补充验证样例
- 以下样例位于外网测试数据目录：
  - `E:\TestData\POC_Data\first_layer_road_net_v0\XXXS5`
- 其中：
  - `XXXS4` 已于 2026-03-21 转入活动基线
  - `XXXS5` 已于 2026-03-21 转入活动基线
- 样例定位：
  - `XXXS5`：长距离 `Segment` 构建成功场景
- 2026-03-21 外网补充验证结论：
  - `XXXS5`：当前实现满足样例目标，且已冻结为活动基线样例
- 详细审计记录：
  - `modules/t01_data_preprocess/history/013-xxxs4-xxxs5-external-sample-audit.md`

## 文档承载
- 完整业务理解与 Step1-Step5 分阶段语义：`specs/t01-data-preprocess/spec.md`
- 正式运行期输入 / 输出 / 约束契约：`modules/t01_data_preprocess/INTERFACE_CONTRACT.md`
- 当前模块运行说明与活动基线入口：`modules/t01_data_preprocess/README.md`
- 活动基线冻结迁移记录：`modules/t01_data_preprocess/history/011-active-three-sample-baseline-freeze.md`
- 四样例活动基线冻结记录：`modules/t01_data_preprocess/history/015-active-four-sample-baseline-freeze.md`
- 五样例活动基线冻结记录：`modules/t01_data_preprocess/history/017-active-five-sample-baseline-freeze.md`
- 外网补充样例审计记录：`modules/t01_data_preprocess/history/013-xxxs4-xxxs5-external-sample-audit.md`
- Step2 平行 corridor 策略对齐记录：`modules/t01_data_preprocess/history/014-step2-parallel-corridor-strategy-alignment.md`
- Step5C adaptive barrier fallback 记录：`modules/t01_data_preprocess/history/016-step5c-adaptive-barrier-fallback.md`

## Step6 POC：segment 级聚合与语义反查
- `Step6` 定位为 road-level `segmentid` 结果的下游聚合与语义审计模块。
- 输入必须是最新 Step1–Step5C 产出的 refreshed：
  - `nodes`
  - `roads`
- 统一使用：
  - `grade_2`
  - `kind_2`
  - `working_mainnodeid`

### 运行方式
```bash
python -m rcsd_topo_poc t01-step6-segment-aggregation-poc \
  --node-path <latest_nodes.geojson> \
  --road-path <latest_roads.geojson> \
  --run-id <run_id>
```

### 正式输出
- `segment.geojson`
- `inner_nodes.geojson`
- `segment_error.geojson`
- `segment_summary.json`
- `segment_build_table.csv`
- `inner_nodes_summary.json`

### Step6 语义
- `pair_nodes`
  - 由 `segmentid = A_B` 直接给出，顺序严格按 `A_B`
- `junc_nodes`
  - 记录仍向当前 segment 之外分支的语义路口
- `inner_nodes`
  - 记录被某个 segment 完全内含的 node，全量复制原字段，仅追加 `segmentid`

### Step6 反查规则
- 若 segment 两端 `pair_nodes` 的 `grade_2` 均为 `1`，则将该 segment 的 `s_grade` 轻调整为 `"0-0双"`
- 若最终 `s_grade = "0-0双"` 且其中间 `junc_nodes` 出现 `grade_2 = 1 且 kind_2 = 4`，则输出到 `segment_error.geojson`
