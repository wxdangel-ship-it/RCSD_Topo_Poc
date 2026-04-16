# Analyze

## 越界检查

- 不触碰 `stage3_step7_acceptance.py`。
- 不触碰 `stage3_review_facts.py`。
- 不触碰 Step4 / Step5 / full-input。
- 不扩展 regularization 作用面。

## 风险检查

- 允许条件性修改 `virtual_intersection_poc.py`，但只限 terminal contracts 之后的 final geometry handoff/export/render 片段。
- 不引入新的 tri-state 或 root cause 语义。
- 只修 provenance，不修几何策略。
