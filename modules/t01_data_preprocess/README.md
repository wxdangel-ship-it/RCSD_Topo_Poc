# T01 数据预处理模块

## 当前状态
- 当前版本：`T01 Skill v1.0.0`
- 当前状态：`accepted baseline / baseline freeze ready`
- 当前官方主方案：
  - 官方 Step1-Step5 口径
  - residual graph 多轮构段
  - XXXS freeze baseline 审计闭环

## 官方推荐入口

### 官方 end-to-end
```bash
python -m rcsd_topo_poc t01-run-skill-v1 \
  --road-path <road_path> \
  --node-path <node_path> \
  --out-root <out_root>
```

说明：
- 默认 `debug=true`
- 默认保留分阶段中间结果，便于大规模验证前的 case 审计
- 如需减少无意义 I/O，请显式使用 `--no-debug`
- 可通过 `--compare-freeze-dir` 与 freeze baseline 做 PASS / FAIL 对比

### freeze compare
```bash
python -m rcsd_topo_poc t01-compare-freeze \
  --current-dir <current_skill_run_dir> \
  --freeze-dir modules/t01_data_preprocess/baselines/t01_skill_v1_0_xxxs
```

## 分步入口
- `python -m rcsd_topo_poc t01-step2-segment-poc`
- `python -m rcsd_topo_poc t01-s2-refresh-node-road`
- `python -m rcsd_topo_poc t01-step4-residual-graph`
- `python -m rcsd_topo_poc t01-step5-staged-residual-graph`

用途：
- 面向调试 / 审计 / case 级排查
- 不再作为正式运行时的默认主入口

## debug 开关
- `debug=false`
  - 只保留最终 `nodes.geojson / roads.geojson`
  - 保留 `t01_skill_v1_summary.*`
  - 保留轻量 freeze compare / bundle 产物
- `debug=true`
  - 额外保留分阶段 `step2 / refresh / step4 / step5` 审计层与中间结果
- `debug` 不改变最终业务逻辑

## 当前性能与内存治理边界
- 当前正式优化已纳入：
  - Step1 / Step2 / refresh / Step4 / Step5 的固定 2 worker 并行输入读取
  - 官方 runner 的阶段级 `gc.collect()` 回收
  - 阶段级 `tracemalloc` 峰值内存记录
  - `debug=false` 时使用临时 stage 目录，减少最终目录的无意义持久化 I/O
- 当前尚未纳入：
  - 完整全内存流水线
  - 核心 pair / trunk / validated 决策层的并发执行
- 因此大规模运行建议：
  - 需要完整审计时使用默认 `debug=true`
  - 需要降低 I/O 压力时显式使用 `--no-debug`

## 当前 freeze baseline
- 当前 Skill v1.0.0 效果基线：
  - `modules/t01_data_preprocess/baselines/t01_skill_v1_0_xxxs/`
- 该目录保存可提交的轻量审计包：
  - `FREEZE_MANIFEST.json`
  - `FREEZE_SUMMARY.json`
  - `FREEZE_COMPARE_RULES.md`
  - `validated_pairs_baseline.csv`
  - `segment_body_membership_baseline.csv`
  - `trunk_membership_baseline.csv`
  - `refreshed_nodes_hash.json`
  - `refreshed_roads_hash.json`

约束：
- 后续任何迭代与该 freeze baseline 不一致时，默认视为回退或显式变更
- 未经用户明确认可，不得更新该 baseline

## 当前推荐输入 / 输出基线
- 推荐输入基线：
  - 原始 `Node / Road`
  - 或最新一轮 refreshed `nodes.geojson / roads.geojson`
- 推荐输出基线：
  - 官方 end-to-end 输出的 `nodes.geojson / roads.geojson`
  - 对应 `freeze_compare_report.*`
  - 对应 `skill_v1_manifest.json / skill_v1_summary.json`

## 后续正式模块完整构建从哪里继续
- 以当前 Skill v1.0.0 accepted baseline 为起点
- 后续重点：
  - Step6
  - 单向 Segment
  - Step3 完整语义归并
  - 完整多轮闭环治理
  - 更深层内存化编排
  - 更完整回归 / 验收体系

## 内网测试协作约定
- 进入内网测试阶段时，默认交付三件套：
  1. GitHub 内网下拉命令
  2. 可直接执行的内网脚本
  3. 可直接执行的关键信息回传命令
- 在用户已提供足够上下文的情况下，不再要求用户手工修改脚本参数
