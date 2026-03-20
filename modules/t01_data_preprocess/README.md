# T01 数据预处理模块

## 当前状态
- 当前版本：`T01 Skill v1.0.0`
- 当前主线：普通道路双向路段逐级提取
- 当前已纳入正式能力：
  - working-layer bootstrap
  - roundabout preprocessing
  - Step1-Step5 residual graph 构段
  - `closed_con in {2,3}`
  - `road_kind != 1`
  - 统一 50m dual / side distance gate
  - 三样例活动基线冻结

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

## 模块开始阶段

### working bootstrap
- 模块开始即建立 working layers
- working nodes：
  - `grade_2 = grade`
  - `kind_2 = kind`
- working roads：
  - `s_grade = null`
  - `segmentid = null`

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

## 当前活动基线
- 当前活动基线已经切换为三样例套件：
  - `modules/t01_data_preprocess/baselines/t01_skill_active_three_sample_suite/XXXS/`
  - `modules/t01_data_preprocess/baselines/t01_skill_active_three_sample_suite/XXXS2/`
  - `modules/t01_data_preprocess/baselines/t01_skill_active_three_sample_suite/XXXS3/`
- 三组样例定位：
  - `XXXS`：通用冒烟
  - `XXXS2`：上下行 / 侧向距离 gate
  - `XXXS3`：环岛
- 后续性能优化必须与这三组结果对齐。
- 若任一样例不一致，必须先由用户检查确认后再决策。

## 文档承载
- 完整业务理解与 Step1-Step5 分阶段语义：`specs/t01-data-preprocess/spec.md`
- 正式运行期输入 / 输出 / 约束契约：`modules/t01_data_preprocess/INTERFACE_CONTRACT.md`
- 当前模块运行说明与活动基线入口：`modules/t01_data_preprocess/README.md`
- 活动基线冻结迁移记录：`modules/t01_data_preprocess/history/011-active-three-sample-baseline-freeze.md`
