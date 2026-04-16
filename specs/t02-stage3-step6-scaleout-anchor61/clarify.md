# Clarify

## 1. 作用面

- 本轮只纳入 `kind_2=4` 且属于 `nonstable center_junction extreme geometry anomaly` 的子簇。
- 当前主驱动样本：`584253`
- 当前已知同簇候选：`705817`

## 2. 显式排除

- `compound_center` 特殊路径：
  - 代表样本：`10970944`
- Step5 rejected / foreign 主导家族
- 已 `accepted` 的稳定对照簇
- 非 `kind_2=4` 保护集

## 3. 弱保护含义

- `10970944` 不是本轮作用样本，而是 Step6 扩展时必须保持稳定的 compound_center 弱保护样本。
- 其 `stable_compound_center_requires_review` 路径、repair 路径和 tri-state 结果都不得漂移。

## 4. focused tests

- 需要新增 focused tests。
- 新测试分两类：
  1. synthetic regularization 规则测试
  2. Anchor61 真样本 focused regression

## 5. cluster evaluation

- 需要新增 `kind_2=4` cluster evaluation。
- 输出至少要包含：
  - tri-state
  - visual class
  - root cause layer
  - geometry metrics
  - 是否应用 bounded regularization

## 6. 不需要做的事

- 不需要新建公开入口。
- 不需要修改契约文档。
- 不需要调整 full-input regression 口径。
