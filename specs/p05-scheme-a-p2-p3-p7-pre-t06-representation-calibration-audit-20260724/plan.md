# 实施计划

## 1. specify

- 冻结当前允许的T06前来源和禁止字段。
- 冻结602维无Movement关系/相对几何表征与train-only邻域。
- 冻结clue calibration的outer/inner隔离合同。

## 2. plan

1. 校验P6、P5、Dataset-P0、P2-P1 dataset和evidence工件。
2. 从compatibility edge建立Case内Segment邻接。
3. 从T01 Segment生成无绝对坐标的相对几何与共享节点邻接。
4. 从历史202维中剔除14个Movement命名维及其28个邻域派生维，
   生成602维增强表征和feature contract；历史工件不改写。
5. 对稳定FP/FN和carrier wrong执行train-only邻域审计。
6. 审计每seed单调阈值可行性和每outer fold校准池。
7. 完成正式Run A/B、专项测试、完整P05回归和资源/体量/入口审计。
8. 同步项目级与P05模块级源事实，形成是否允许下一训练阶段的结论。

## 3. implement边界

- 新增P05内部：
  - `scheme_a_p2_p3_p7_models.py`
  - `scheme_a_p2_p3_p7_audit.py`
  - 对应测试与模块导出
- 只读复用P5/P6、Dataset-P0、P2-P1和P2-P2-P2-P0工件。
- 不新增正式入口，不修改T01–T12。

## 4. 验证

- 相对几何、邻接、可分性、单调阈值与decision纯函数测试；
- 正式Run A/B；
- 完整P05回归；
- hash、CRS、无泄漏、资源、体量与入口审计。
