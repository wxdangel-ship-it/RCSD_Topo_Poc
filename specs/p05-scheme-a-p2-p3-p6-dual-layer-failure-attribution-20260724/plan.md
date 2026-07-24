# 实施计划

## 1. specify

- 冻结 P5 原始工件和 `MODEL_NO_GO` 结论。
- 冻结 scorer decision / final publication 双层业务口径。
- 冻结 train-only、Case-grouped 的证据可分性审计。

## 2. plan

1. 校验 P5、engine、dataset 与 evidence manifest/hash。
2. 唯一 join eligible decision、evaluation、score、effective 与 fold。
3. 生成逐对象双层归因和逐 seed/fold/Case 汇总。
4. 复算双层 carrier 指标与 clue 混淆矩阵。
5. 对全部 FP/FN做精确冲突审计。
6. 对稳定 FP/FN做 train-only top-20 邻域审计。
7. 冻结 calibration / representation / publication 三类事实结论。
8. 执行专项测试、完整 P05 回归和正式 Run A/B。
9. 同步项目级与 P05 模块级源事实并形成阶段决策。

## 3. implement 边界

- 新增 P05 内部：
  - `scheme_a_p2_p3_p6_models.py`
  - `scheme_a_p2_p3_p6_audit.py`
  - 对应测试与模块导出
- 只读复用：
  - P5 OOF、engine、dataset 工件；
  - P2-P2-P2-P0 202 维 evidence；
  - Dataset-P1 scope/failure manifest。
- 不新增正式执行入口，不修改历史 P5 工件。

## 4. 验证

- 双层指标、归因和 collision/neighbor 纯函数测试；
- 专项测试和完整 P05 回归；
- 正式 Run A/B；
- signature、hash、分母、资源、GIS、入口和体量审计。

## 5. 实施结果

上述计划已执行完成。正式 Run
`p05_scheme_a_p2_p3_p6_attribution_20260724_03/_04` 得到共同 signature
`e753bb817be16841adf4832dbfe3d68ed579e7b851364dd54a4569bbbf180a1c`，
Run B reference match=true。双层指标、逐对象归因、证据可分性、资源和范围门
全部通过，阶段结论为
`P05_SCHEME_A_P2_P3_P6_ATTRIBUTION_GO_DUAL_ROUTE_REQUIRED`。
