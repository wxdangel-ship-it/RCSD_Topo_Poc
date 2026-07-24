# Implementation Plan: P05 M2R

**Branch**: `codex/p05-neural-road-poc-20260721` | **Date**: 2026-07-21 | **Spec**: `spec.md`

## Summary

M2R 将 P05 从“消费 T03/T04/T05/T07 artifact、只学习 T06 Road 操作”改造成“共享编码器 + T03/T04/T05/T06 必选 Head + 可选 T07 Head”的多任务神经系统。第一道门禁是从现有本地 Case 中提取可追溯的任务级真值；第二道门禁是每个 Head 的独立可学习性；第三道门禁是 free/constrained 两种解码下的最终 T06 F-RCSD RoadGraph。

## Technical Context

**Language/Version**: Python 3.12 隔离训练环境；仓库正式环境仍为 Python 3.10  
**Primary Dependencies**: PyTorch、Fiona、Shapely、PyProj、NumPy  
**Storage**: CSV/JSON/GPKG 与 PyTorch checkpoint  
**Testing**: pytest、真实数据不可变 run、grouped OOF  
**Target Platform**: Windows 11，NVIDIA RTX 5090 单 GPU  
**Project Type**: Python POC module callable  
**Performance Goals**: 参数 `8M~20M`；峰值 VRAM `<=16GB`；逐 Case 推理耗时可审计  
**Constraints**: 仅 `E:\TestData\POC_Data`；不执行 T03-T06 业务 fallback；不新增正式入口  
**Scale/Scope**: M0 登记 741 样本、726 group；当前 T06 RoadGraph truth 51 个

## Constitution Check

- 使用现有 P05 隔离工作树，不触碰主工作区 P04 改动。
- 本任务属于跨模块研究目标变更，必须完整执行 specify/plan/tasks/implement。
- 只修改 P05 POC、对应 SpecKit 和已授权的项目/P05源事实；不修改 T03-T07 正式算法或接口。
- 新增/修改源码前逐文件检查当前字节数，任何源码不得达到 `100KB`。
- 不新增 repo CLI、scripts、Makefile target 或其它正式入口。
- GIS 完成审计必须覆盖 CRS、拓扑、几何语义、lineage 和性能。
- 数据语义冲突只 mask/报告，不反推字段含义，不 silent fix。

## 产品视角

产品问题是：现有分层人工真值能否支持神经网络学习 T03-T06 业务内容，并在不运行这些模块规则的情况下生成可用 RoadGraph。M2R 成功不等价于生产替换；失败也必须能明确归因到标签、任务表示、联合架构、最终解码或数据覆盖。

## 架构视角

```text
T01/SWSD/RCSD raw evidence
          |
          v
SharedSceneEncoder
  |       |       |       |       |
 T03     T04     T05     T06    optional T07
  |       |       |       |       |
  +-------+-------+-------+-------+
                  |
         final RoadGraph logits
            /             \
      free decoder   generic constrained decoder
            \             /
             no-rule materializer
                    |
          M0 evaluator + OOF report
```

共享输入只包含推理时可获得的基础事实。任务 Head 通过 mask 接受部分监督；下游 Head 可以消费共享 latent 和上游神经预测，但不得读取当前样本真实上游标签。通用约束采用候选动作 mask/合法生成状态，不做事后业务修图。

## 研发视角

1. 扩展 M0/M1 只读数据合同，建立 M2R task target inventory。
2. 实现统一 scene graph/raster 特征、task mask 和 grouped OOF 数据视图。
3. 实现共享编码器、T03/T04/T05/T06 Head 和可选 T07 Head。
4. 实现多任务 loss、small-batch overfit、checkpoint 和资源记录。
5. 复用 M1 materializer/evaluator，新增 free/constrained decoder 和 intervention audit。
6. 生成逐 fold、逐任务、逐 Case 和综合 go/no-go 报告。

## 测试视角

- 合成 fixture 覆盖 task mask、Unknown、权重、跨 fold group 和 label leakage。
- 标签解析测试覆盖 T03/T04 仅输入 bundle、可追溯 output、T10 Case/Segment 和 approved exclusion。
- 模型测试覆盖每个 Head 的 shape/loss/overfit、可选 T07、checkpoint 和确定性推理。
- 解码测试覆盖 dangling reference、重复 ID、非法 split、无合法动作、约束审计和零事后内容修复。
- 真实数据验证覆盖 M2R supervision run、OOF、最终 GPKG 和全部指标。

## QA 视角

- 对全部 741 登记样本给出每个任务的 `Gold/Silver/Unknown` 和不可用原因。
- 对 T03/T04 运行用户确认的当前正式策略重放，逐 Case 核对 manifest、终态和 artifact hash；历史 output 仍须回指对应 Case，不以目录名推断标签。
- 逐 fold 验证业务对象、实体及邻域零泄漏。
- 逐 Case 验证 CRS、几何、Road/Node 引用和有向拓扑。
- 报告最差 Case、类别覆盖、约束触发、资源峰值和复现结果。

## Project Structure

```text
specs/p05-neural-frcsd-m2r-20260721/
├── spec.md
├── plan.md
├── research.md
├── data-model.md
├── contracts/m2r-output-contract.md
├── checklists/requirements.md
├── tasks.md
└── validation-summary.md

src/rcsd_topo_poc/modules/p05_neural_road_generation/
├── m2r_supervision.py
├── m2r_dataset.py
├── m2r_network.py
├── m2r_training.py
├── m2r_decoding.py
└── m2r_evaluation.py

tests/modules/p05_neural_road_generation/
├── test_m2r_supervision.py
├── test_m2r_dataset.py
├── test_m2r_network.py
├── test_m2r_decoding.py
└── test_m2r_evaluation.py
```

**Structure Decision**: 复用现有 P05 模块和 callable 边界，以小文件扩展 M2R；不修改 repo CLI。

## 验证顺序

1. SpecKit/源事实/接口一致性与文件体量前置检查。
2. supervision fixture 与真实 741 样本审计。
3. grouped OOF 数据集和 label leakage 门禁。
4. 各 Head small-batch overfit。
5. 联合模型开发 fold、消融和资源审计。
6. 51 RoadGraph Case grouped OOF free/constrained 评价。
7. CRS、拓扑、几何、审计、性能和需求逐项完成审计。

## Complexity Tracking

| 复杂度 | 必要性 | 控制方式 |
|---|---|---|
| 多任务部分标签训练 | 单点 Case 与完整 RoadGraph 的真值粒度不同 | 任务级 mask/weight，禁止伪标签 |
| free/constrained 双解码 | 需要区分语义学习与图合法性 | 同一 logits、同一 materializer、独立 intervention audit |
| 可选 T07 Head | 用户允许包含或不包含 | 只通过固定消融标准决定去留 |
