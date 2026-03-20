# T01 - AGENTS

## 1. 模块状态
- 模块 ID：`t01_data_preprocess`
- 当前状态：`accepted baseline / Skill v1.0.0 formalization`
- 当前 accepted 范围：
  - Step1：`pair_candidates`
  - Step2：`validated / rejected / trunk / segment_body / step3_residual`
  - Step4：基于 refreshed `Node / Road` 的 residual graph 轮次
  - Step5：`Step5A / Step5B / Step5C`

## 2. 持续有效的模块约束
- 不得回退当前 accepted baseline 的业务语义
- 后续轮次默认消费 refreshed `nodes.geojson / roads.geojson`
- 已有非空 `segmentid` 的 road 在后续轮次工作图中剔除
- 历史高等级边界 mainnode 必须同时作用于：
  - pair 搜索
  - segment 收敛
- `mainnodeid = NULL` 的 node 仍是合法语义路口
- trunk 以语义路口为单元，支持：
  - 双向 road 镜像最小闭环
  - split-merge 混合通道
  - semantic-node-group closure

## 3. Freeze baseline guardrails
- 当前 Skill v1.0.0 效果基线为：
  - `XXXS`
  - `modules/t01_data_preprocess/baselines/t01_skill_v1_0_xxxs/`
- 后续迭代若与该 freeze baseline 不一致，默认视为回退或显式变更
- 未经用户明确认可，不得更新 freeze baseline
- 任何性能优化不得通过改变 accepted 业务结果换取速度

## 4. 官方入口与 debug 约束
- 官方推荐入口：
  - `python -m rcsd_topo_poc t01-run-skill-v1`
- 分步入口：
  - `t01-step2-segment-poc`
  - `t01-s2-refresh-node-road`
  - `t01-step4-residual-graph`
  - `t01-step5-staged-residual-graph`
- `debug=true`：
  - 官方默认值
  - 保留分阶段中间结果与审计层
- 适用于冻结基线复核、case 排查与视觉审查
- `debug=false`：
  - 用于减少无意义 I/O 和最终目录体积
- `debug` 只影响中间输出，不得影响最终业务结果
- 当前允许的性能优化边界：
  - 固定小并发读取输入图层
  - 阶段级内存回收与峰值记录
  - `debug=false` 下的临时 stage 目录
- 当前未纳入正式语义的能力：
  - 完整全内存流水线
  - 核心业务决策层并发

## 5. 内网测试交付契约
- 进入内网测试阶段时，默认交付三件套：
  1. 当前 GitHub 版本内网下拉命令
  2. 可直接执行的内网运行脚本
  3. 可直接执行的关键信息回传命令
- 若用户已提供足够路径与版本信息，这三件套必须可直接执行，不得要求用户再手工替换参数
- 回传内容较少时直接命令行输出；内容较多时输出摘要文本
