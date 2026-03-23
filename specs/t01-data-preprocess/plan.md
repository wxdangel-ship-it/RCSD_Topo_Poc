# T01 计划

## 当前阶段
- `step2 same-stage pair arbitration repair`

## 本轮目标
1. 在 Step2 单 pair 合法性验证之后、final `validated_pairs / segment_body` 固化之前，新增 same-stage pair arbitration 阶段。
2. 显式识别同阶段合法 pair 的 conflict components，不再让最终保留结果由固定顺序直接决定。
3. 在局部 conflict component 内，根据 corridor 归属、内部端点惩罚、body 支撑与语义冲突等指标，选择更合理的一组 winners。
4. 产出可审计的 conflict / arbitration 中间结果，并完成 `XXXS7` 定点验证。
5. 完成 `XXXS` freeze compare 回归，但不自动更新 freeze baseline。

## 本轮边界
- 不修改 Step1 `pair_candidates` 语义。
- 不修改 Step4 / Step5A / Step5B / Step5C 当前 accepted 语义。
- 不引入全局网络级优化器，仅在 Step2 / S2 同阶段冲突簇内做局部仲裁。
- 不 silent fix，不 silent 更新 freeze baseline。

## 实施顺序
1. 保留 Step1 输出与 Step2 单 pair 验证前半段。
2. 在 Step2 中补充 pair-level conflict graph 与 conflict component 识别。
3. 为合法 pair + trunk/segment_body candidate 计算仲裁指标。
4. 对小型 component 做 exact 组合搜索；对大型 component 做 fallback greedy，并审计记录 fallback。
5. 用仲裁 winners 重新固化 Step2 final `validated_pairs / segment_body / step3_residual`。
6. 输出 conflict / arbitration 审计文件，并以 `XXXS7` 做定点验收。
7. 完成 `XXXS` freeze compare 回归并保留差异报告。
