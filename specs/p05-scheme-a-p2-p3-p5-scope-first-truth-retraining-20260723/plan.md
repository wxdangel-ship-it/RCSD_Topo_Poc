# 实施计划

## 1. specify

- 冻结 P4 scope-first Segment/Node truth 为唯一标签层。
- 冻结旧 P2-P1 candidate/feature/payload/compatibility 为只读推理层。
- 冻结同架构、同证据、同 seed/fold 的可比重训和硬安全门。

## 2. plan

1. 校验 Dataset-P1、P4、旧 P2-P1、方案 A baseline 和全部输入 hash。
2. 生成 P2-P3-P5 训练 dataset overlay，只重写 labels，复用 truth-free 工件。
3. 执行 Dataset A/B 并冻结共同训练 manifest。
4. 复用 P2-P3-P2 训练引擎，从头完成 3 seeds × 5 folds OOF。
5. 对 eligible decision 应用 `ADVANCE_RIGHT access_valid=false` 硬门。
6. 用修正 Node/Junction truth 重建 effective selection 和 RoadGraph。
7. 重算逐 seed/逐 fold carrier、coverage、clue 和整图指标。
8. 执行专项测试、完整 P05 回归、正式 Run A/B、体量/入口/GIS/资源审计。
9. 同步项目级和 P05 模块级源事实并形成阶段决策。

## 3. implement 边界

- 新增 P05 内部：
  - `scheme_a_p2_p3_p5_models.py`
  - `scheme_a_p2_p3_p5_dataset.py`
  - `scheme_a_p2_p3_p5_oof.py`
  - 对应测试与模块导出
- 复用且不修改：
  - P2-P3-P0 network/training；
  - P2-P3-P2 OOF训练引擎；
  - P2-P3-P3 access hard gate；
  - P4 truth工件；
  - T01–T12实现和接口。
- 不新增正式执行入口。

## 4. 验证

- 数据 overlay 与 hard-gate 纯函数测试；
- 专项测试和完整 P05 回归；
- Dataset A/B；
- OOF Run A/B；
- signature、hash、指标、RoadGraph、资源、GIS、入口和体量审计。

## 5. 实施结果

上述 1–9 步已全部执行。训练数据和审计链通过，正式双跑稳定得到
`P05_SCHEME_A_P2_P3_P5_MODEL_NO_GO`。失败边界仅位于 carrier coverage 与
RealityChangeClue 跨 seed/fold 指标；RoadGraph、确定性、资源、GIS 和范围门均
通过。完整证据见 `validation-summary.md`。
