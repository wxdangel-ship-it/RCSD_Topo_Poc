# T01 Spec-Kit 治理规格

## 文档定位
- 本文档记录当前 T01 轮次的 spec-kit 治理目标、实施边界与阶段性验收口径。
- 它不承载 steady-state accepted baseline 正文；正式业务规格仍以模块级 source of truth 为准。

## 正式业务规格落点
- 当前 accepted baseline 主体见：
  - [06-accepted-baseline.md](/mnt/e/Work/RCSD_Topo_Poc/modules/t01_data_preprocess/architecture/06-accepted-baseline.md)
- 模块级契约见：
  - [INTERFACE_CONTRACT.md](/mnt/e/Work/RCSD_Topo_Poc/modules/t01_data_preprocess/INTERFACE_CONTRACT.md)
- 模块入口与使用说明见：
  - [README.md](/mnt/e/Work/RCSD_Topo_Poc/modules/t01_data_preprocess/README.md)

## 当前治理主题
- `T01 accepted baseline doc audit + Step2 performance audit and optimization`

## 当前治理目标
1. 审计 T01 最新代码与正式需求基线文档的一致性，修正文档滞后项。
2. 明确本轮已落地的 `bootstrap node retyping` 与 family-based refresh retyping 口径，避免文档继续沿用旧的泛化 `2048` 刷新叙述。
3. 在文档对齐后，清理本地脏数据，恢复本地与远端一致状态。
4. 对 Step2 阶段的性能、内存占用与高风险路径做专项审计，定位内网死机的主要来源。
5. 在独立分支上实施 Step2 优化，并以现有样例集确保业务效果不变。

## 范围
- in-scope：
  - T01 正式 source-of-truth 文档：
    - `modules/t01_data_preprocess/architecture/*`
    - `modules/t01_data_preprocess/INTERFACE_CONTRACT.md`
    - `modules/t01_data_preprocess/README.md`
  - T01 当前 spec-kit 过程文档：
    - `spec.md`
    - `plan.md`
    - `tasks.md`
  - Step2 性能 / 内存审计与后续优化实现
  - T01 相关测试与样例回归
- out-of-scope：
  - T01 新业务规则扩张
  - T00 / T02 模块实现改造
  - 历史 freeze baseline 自动刷新
  - 新增独立执行入口

## 核心约束
- 文档审计阶段不得顺手改写 accepted baseline 业务真相，只允许把文档对齐到已合入代码与已确认口径。
- `kind_2 = 2048` 的业务语义已从“泛化 t-like barrier”收窄回“真实 T 型/旁向单通路口语义”；文档不得继续沿用旧的泛化叙述。
- `bootstrap node retyping` 只允许改写 `grade_2 / kind_2`，不改原始 `grade / kind`。
- Step2 性能优化阶段不得通过改变构段业务结果来换性能；业务结果以当前人工验收通过样例为基线。
- 在样例未重新人工确认前，不更新 freeze baseline。

## 当前验收口径
- 文档层：
  - 正式 source-of-truth 文档完整反映当前代码中的：
    - `working bootstrap -> roundabout preprocessing -> bootstrap node retyping -> Step1...` 顺序
    - `bootstrap node retyping`
    - family-based `grade_2 / kind_2` refresh retyping
  - 旧的“唯一 segment + residual in/out 即刷成 `2048`”表述必须被替换掉
- 仓库状态层：
  - 文档修订提交并推送到 `main`
  - 清理后本地与远端保持一致
- 性能层：
  - 形成 Step2 的性能 / 内存审计结论
  - 给出可执行的优化点拆分与验证策略
- 优化层：
  - 在独立分支上完成 Step2 优化
  - 基于 `XXXS1-8` 与相关单测确认业务无回退

## 当前样例治理边界
- 人工验收通过基线：
  - `XXXS1`
  - `XXXS2`
  - `XXXS3`
  - `XXXS4`
  - `XXXS6`
  - `XXXS7`
  - `XXXS8`
- 当前仍需继续关注的局部问题：
  - `XXXS5`
- 临时样例基线记录：
  - `modules/t01_data_preprocess/baselines/t01_skill_temp_segment_review_suite/TEMP_SEGMENT_BASELINE_MANIFEST.json`
  - `modules/t01_data_preprocess/baselines/t01_skill_temp_segment_review_suite/TEMP_SEGMENT_REVIEW.md`
