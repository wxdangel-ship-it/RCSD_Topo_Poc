# T01 计划

## 1. 当前阶段
- 阶段名：`Skill v1.0 formalization and baseline freeze`
- 阶段目标：
  - 固化 T01 Skill v1.0.0 accepted baseline
  - 建立 XXXS freeze baseline 与 compare 机制
  - 提供官方 end-to-end 入口与统一 `debug` 开关
  - 完成性能审计与默认 I/O 收敛

## 2. 本阶段产出
- 官方端到端入口：`t01-run-skill-v1`
- freeze compare 入口：`t01-compare-freeze`
- XXXS freeze baseline 轻量审计包
- 性能 before / after / compare 产物
- Skill v1.0.0 模块文档与契约

## 3. 当前推荐基线
- 推荐官方入口：`python -m rcsd_topo_poc t01-run-skill-v1`
- 推荐调试入口：
  - `t01-step2-segment-poc`
  - `t01-s2-refresh-node-road`
  - `t01-step4-residual-graph`
  - `t01-step5-staged-residual-graph`
- 推荐 freeze baseline：`modules/t01_data_preprocess/baselines/t01_skill_v1_0_xxxs/`

## 4. 后续正式模块完整构建
- Step6
- 单向 Segment
- Step3 完整语义归并
- 完整多轮闭环治理
- 更深层内存化编排与图内存复用
- 更完整的回归 / 验收体系
