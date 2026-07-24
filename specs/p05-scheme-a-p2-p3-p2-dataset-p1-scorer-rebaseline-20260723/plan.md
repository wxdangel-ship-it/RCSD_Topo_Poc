# 实施计划

## 1. specify

- 冻结 Dataset-P1 作为唯一 Segment 标签资格合同。
- 冻结 P2-P3-P0 网络、202维证据、3 seeds × 5 folds与既有安全门。
- 明确 context-only 不进入监督/指标，整图执行时只允许安全 fallback。

## 2. plan

1. 新增 P2-P3-P2 config 与 scope application 数据模型。
2. 只读加载旧 P2-P3 数据/证据，并用 Dataset-P1 scope 精确覆盖监督资格与权重。
3. 仅用 6,275 个 eligible example 从头训练；不读取旧 model state/threshold。
4. 对 eligible example生成 OOF score/decision/evaluation。
5. 为2,588 context-only和2个局部失败对象生成确定性 fallback decision。
6. 复用通用 Junction/Node closure与 RoadGraph materializer，建立8,863 Segment整图。
7. 在 eligible-only 分母重算 carrier/clue指标，在 all-segment 分母审计 fallback和
   RoadGraph。
8. 完成专项测试、完整P05回归、正式 Run A/B、体量与入口审计。
9. 同步项目级与P05模块级源事实。

## 3. implement 边界

- 新增：
  - `scheme_a_p2_p3_p2_models.py`
  - `scheme_a_p2_p3_p2_dataset.py`
  - `scheme_a_p2_p3_p2_oof.py`
  - 对应测试和模块导出
- 复用且不修改：
  - P2-P3-P0 network/training；
  - P2-P1 candidate/Node closure；
  - Dataset-P1工件；
  - T01–T12实现与接口。
- 不新增正式入口。

## 4. 验证

- 纯函数和scope破坏测试；
- 新增测试与完整P05回归；
- 3 seeds × 5 folds Run A/B；
- 核心工件SHA与规范化signature比较；
- CRS/geometry/骨架/入口/文件体量审计。
