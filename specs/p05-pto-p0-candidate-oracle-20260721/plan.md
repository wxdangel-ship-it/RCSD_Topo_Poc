# Implementation Plan: P05-PTO-P0

**Branch**: `codex/p05-neural-road-poc-20260721` | **Date**: 2026-07-21 | **Spec**: `spec.md`

## Summary

PTO-P0 复用 R2 edit/pointer/materializer/evaluator 合同，用独立、登记版本的策略重放生成高召回候选。候选集先冻结并哈希，之后才由 label-only truth 计算 coverage 与 Oracle cost。求解器只执行通用图合法性约束，并给出 gap=0 的下界证书；它不训练模型，也不做业务修图。

## Technical Context

- Python callable，复用 P05 现有 Fiona/Shapely/PyProj 依赖；不新增正式入口。
- 策略候选来源：T10 六 Case 对应登记 commit `4b1c496b6cd21bd0834ed3de0e076f79ee7e9eeb`；T10-Error/T10-Error-2 对应登记 commit `96b0ea518ba486db6d72afef79e637a0fad84e93`。
- 两个登记 T10 runner 均包含其历史版本中的 T07 辅助 stage；这是用户已允许的可选策略预处理，只计入 replay lineage/成本，不作为 PTO scorer 输入、独立候选 stage 或最终选择规则。
- 数据范围：51 Case；`T10-Error / 1213556_1263661` 显式排除。
- truth 与基础图 lineage 复用冻结 R2 Gate 1/M2R dataset，但候选生成 API 不接收 truth。

## Constitution Check

- 使用现有 P05 隔离工作树，保留全部 M0/M1/M2R/R2 未提交成果。
- 任务属于正式大型实验，执行 `specify / plan / tasks / implement`。
- 只修改 P05、PTO-P0 SpecKit 与已授权的 P05 项目/模块源事实。
- 写任何源码/测试前检查当前字节数；单文件不得达到 100KB，同轮同步 code-size audit。
- 不修改 T01-T07 算法或接口，不新增长期入口。
- 不基于局部样本固化上游字段语义。
- GIS 验证覆盖 CRS、拓扑、几何语义、追溯与性能。

## 产品视角

P0 先回答“正确答案是否存在于可由业务策略产生的有限候选空间中”。它将候选问题与评分问题拆开；只有候选可达且通用约束可解，才值得投入神经网络评分器训练。

## 架构视角

```text
raw/T01 + registered strategy version
                |
                v
      strategy replay outputs
                |
                v
  R2 edit encoder in candidate mode
                |
                v
 candidate artifact + frozen manifest/hash
                |
        label/evaluation boundary
                v
 truth -> label-only oracle cost/coverage
                |
                v
 generic constrained exact solver
                |
                v
 no-rule materializer -> M0 evaluator
```

候选生成层不接收 truth path。标签层验证候选 manifest/hash 后才读取 truth。独立重放恰好生成与 truth 相同的 payload 是允许的，但必须由策略代码、外部输入和运行 lineage 证明独立来源。

## 研发视角

1. 建立 P0 config、strategy replay descriptor、candidate group、oracle-cost assignment 与 solve certificate 数据模型。
2. 实现候选 lineage 验证、base+strategy edit union、规范化去重及不可变候选 run。
3. 实现候选冻结后的 label-only coverage/cost 层。
4. 实现 exact group-choice solver、通用图约束验证、R2 materializer adapter 与 evaluator adapter。
5. 生成逐 Case/汇总审计、determinism 与资源报告。

## 测试视角

- lineage：truth 路径注入、输入 hash 不匹配、策略失败、错误 commit、排除 Case 均必须拒绝。
- candidate：base keep/drop、strategy COPY/UPDATE/SPLIT/CREATE/DROP、T05 Node/pointer、去重与来源合并。
- solver：精确最优、候选缺失、重复 ID、缺失引用、非法几何、非零 gap、determinism。
- integration：合成 Case 从候选冻结到物化评价完整往返。

## QA 视角

- 对 51 Case 逐项核对 scope、候选/变量/约束数、action coverage、Oracle cost、证书与归一化指标。
- 验证 candidate manifest 在 truth 接入前已完成，标签/评价只按 candidate hash 引用。
- 分开报告 replay、candidate build、solve、materialize/evaluate 与端到端资源。
- 结构异常只报告和失败，不自动修正。

## Project Structure

```text
specs/p05-pto-p0-candidate-oracle-20260721/
├── spec.md
├── plan.md
├── research.md
├── data-model.md
├── contracts/p0-output-contract.md
├── checklists/requirements.md
├── tasks.md
└── validation_summary.md

src/rcsd_topo_poc/modules/p05_neural_road_generation/
├── pto_models.py
├── pto_lineage.py
├── pto_candidates.py
├── pto_solver.py
└── pto_p0.py
```

## Verification Order

1. SpecKit/source facts/interface、入口与 code-size 一致性。
2. 合成 lineage/candidate/solver/integration 测试。
3. 51 Case Gate 1 candidate reachability。
4. 51 Case Gate 2 Oracle-cost solve/evaluation。
5. 第二次相同配置运行，验证确定性。
6. GIS、资源、FR/SC、hash 与完成审计。
