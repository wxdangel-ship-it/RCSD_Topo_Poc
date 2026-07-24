# Implementation Plan: P05-R2

**Branch**: `codex/p05-neural-road-poc-20260721` | **Date**: 2026-07-21 | **Spec**: `spec.md`

## Summary

R2 先将最终 T06 RoadGraph 表达为可完备的 Road/Node edit-set，再实现精确 T05 pointer 与条件图生成模型。执行顺序严格为 Gate 1 oracle 表示、Gate 2 可学习性、Gate 3 grouped OOF；前一门禁失败时停止后续成功声明并形成正式归因。

## Technical Context

- Python 3.12 隔离训练环境；PyTorch 2.9.1+cu128。
- 输入沿用冻结 M2R dataset/supervision lineage，truth payload 全部 label-only。
- 输出为 JSONL/CSV/GPKG/checkpoint；正式环境不新增 CLI。
- 当前规模：741 样本、726 group、51 RoadGraph truth、35,300 基础候选 Road。
- 单卡 RTX 5090；VRAM 硬预算 16GB。

## Constitution Check

- 使用现有 P05 隔离工作树，保留未提交 R1 成果。
- 完整执行 `specify / plan / tasks / implement`。
- 只修改 P05、R2 SpecKit 和已授权的 P05 项目源事实。
- 写任何源码前检查目标文件当前字节数；单文件不得达到 100KB。
- 不修改 T01-T07 正式算法/接口，不新增长期执行入口。
- 不根据局部数据反推正式字段语义；未知语义只进入 label payload/audit。
- GIS 完成审计覆盖 CRS、拓扑、几何语义、追溯和性能。

## 产品视角

业务问题不是继续调优 R1，而是验证“模型是否拥有表达正确 RoadGraph 的完整语言”。Gate 1 先证明语言完备；Gate 2 证明网络可学习；Gate 3 才回答现有数据能否泛化。R2 即使 no-go，也必须指出失败发生在哪个门禁。

## 架构视角

```text
raw/T01 base graph
        |
        v
Shared scene + graph encoder
  |        |        |        |
 T03      T04   T05 pointer  graph edit decoder
                              |
               Road COPY/UPDATE/SPLIT/CREATE/DROP
               Node COPY/UPDATE/CREATE/DROP
                              |
                free / generic constrained
                              |
                   no-rule materializer
                              |
                 normalized RoadGraph evaluator
```

oracle encoder 只在训练数据准备期读取 truth，生成 label-only edit payload。推理侧只消费 base graph 和模型输出。

## 研发视角

1. 建立 R2 oracle edit-set 数据合同、编码器、materializer 和 evaluator adapter。
2. 在 51 Case 上完成真值重建，输出 coverage、操作分布、异常和逐 Case GPKG。
3. 构建 pointer/edit query dataset，保持 train-only normalization 和 entity guard。
4. 实现共享编码器、T03/T04、精确 T05 pointer 与图编辑 decoder。
5. 完成 small-batch overfit、五折训练、同 logits 双解码和资源/确定性审计。

## 测试视角

- 先写 oracle action、CREATE fallback、SPLIT、pointer cardinality、materializer hard failure 测试。
- 合成 truth 必须由 edit-set 精确往返；破坏 endpoint/ID/geometry 必须失败。
- 模型测试覆盖 shape、mask、loss、梯度、checkpoint 和确定性。
- 真实验证覆盖 51 Case Gate 1、small-batch Gate 2 和完整 OOF Gate 3。

## QA 视角

- 逐 Case 审计 base/truth/edit/reconstructed lineage 和 hash。
- 报告 COPY/UPDATE/SPLIT/CREATE/DROP 分布及每类 coverage。
- 验证 EPSG、引用、重复 ID、几何、方向/source 与有向拓扑。
- 保留最差 Case、失败 action、资源峰值和重复推理差异。

## Project Structure

```text
specs/p05-neural-frcsd-r2-20260721/
├── spec.md
├── plan.md
├── research.md
├── data-model.md
├── contracts/r2-output-contract.md
├── checklists/requirements.md
└── tasks.md

src/rcsd_topo_poc/modules/p05_neural_road_generation/
├── r2_models.py
├── r2_oracle.py
├── r2_edit.py
├── r2_dataset.py
├── r2_network.py
├── r2_gate2.py
└── r2_oof.py
```

## Verification Order

1. SpecKit/source fact/interface 一致性与体量前检。
2. 合成 oracle/edit/pointer/materializer 测试。
3. 51 Case oracle Gate 1。
4. small-batch Gate 2。
5. grouped 5-fold Gate 3。
6. FR/SC、GIS、资源、依赖、入口和 code-size 完成审计。
