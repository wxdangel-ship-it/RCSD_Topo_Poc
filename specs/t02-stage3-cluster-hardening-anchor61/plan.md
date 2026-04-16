# Plan

## 审计结论到重构动作

1. Step6 当前 cluster 已有局部成功，但 canonical ownership 仍偏弱。
   - 动作：在 Step6 controller / solve 结果中补强 cluster-local facts。
2. Step7 仍通过 generic review-field derivation 消费当前 cluster。
   - 动作：在 Step7 上做 cluster-local narrow de-legacy，优先消费 Step6 当前 cluster 的 canonical reason。
3. monolith 仍先产生 legacy acceptance，再由 terminal assembly 回收。
   - 动作：尽量把 cluster-local truth handoff 收敛在 terminal assembly 与 Step7，不新增 monolith 业务逻辑。

## 代码边界

优先修改：

- `stage3_step6_geometry_controller.py`
- `stage3_step6_geometry_solve.py`
- `stage3_step7_acceptance.py`
- `stage3_review_facts.py`

限制性评估：

- `stage3_success_contract_assembly.py`
- `stage3_terminal_contract_assembly.py`

默认不改：

- `virtual_intersection_poc.py`
- T-mouth 主逻辑
- Step4 / Step5 / full-input 相关文件

## 测试边界

- `test_stage3_step6_geometry_controller.py`
- `test_stage3_step6_regularization.py`
- 新增/补充 cluster-local Step7 focused tests
- `test_stage3_step6_scaleout_anchor_cases.py`
- `test_anchor61_baseline.py`

## 验收边界

- 看 cluster-local canonical ownership 是否更单轨
- 看 Step7 是否减少当前 cluster 的 legacy fallback
- 看保护样本与 Anchor61 是否无回退
