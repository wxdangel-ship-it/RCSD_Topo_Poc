# Analyze

## 1. 是否越界到 Step7 / Step4 / Step5 / monolith

- 目标范围固定在 Step6。
- 若实现需要改 `virtual_intersection_poc.py`、`stage3_step7_acceptance.py`、`stage3_step5_foreign_model.py`，视为越界。

## 2. 是否残留 case patch

- 禁止按 `case_id` / `mainnodeid` 写分支。
- 允许的唯一粒度是：
  - `kind_2=4`
  - `center_junction`
  - 已冻结的异常几何子簇

## 3. bounded regularization 是否会扩成无界 expansion

- 不允许：
  - candidate 面积超过原 polygon
  - 引入更多 foreign
  - 增加 uncovered endpoint
- selector 必须继续坚持硬 gate。

## 4. 是否会破坏保护样本

- `10970944`：compound_center 路径必须稳定
- `698330 / 706389`：single_sided_t_mouth 保护
- `520394575`：失败锚点保护
- Anchor61：全量保护

## 5. 本轮判据

- 若 second cut 已自然覆盖同簇样本，则本轮以工程固化为主，而不是强行继续扩几何规则。
- 若 cluster eval 证明不可推广，则应停在报告，不做越界改动。
