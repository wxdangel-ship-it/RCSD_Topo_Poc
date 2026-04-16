# T02 / Stage3 第三刀：Cluster Hardening

## 范围

本轮只做 `kind_2=4 / center_junction` 当前已验证成功 cluster 的收尾硬化：

- `nonstable_center_junction_extreme_geometry_anomaly`
- `stable_compound_center_requires_review`

本轮目标不是扩大样本收益，也不是做 T-mouth 优化，而是把第二刀已验证成功的 Step6 路径更明确地收进 Stage3 当前骨架。

## 冻结前提

- Anchor61 仍是唯一正式验收基线。
- full-input 仍是 regression-only。
- `584253` 的 bounded regularization 改善已验证。
- `10970944` compound_center 路径已验证稳定。
- `698330`、`706389`、`520394575` 与 Anchor61 baseline 是本轮保护面。

## 非目标

- 不做 T-mouth / `758888` 优化
- 不改 Step4 / Step5 业务语义
- 不做 full-input 正式交付
- 不做 monolith 大拆分
- 不做 case patch
- 不改契约文档

## 结构目标

1. Step6 对当前 cluster 更明确拥有 canonical review facts。
2. Step7 对当前 cluster 更直接消费 Step6 冻结结果，减少对 raw acceptance / legacy fallback 的依赖。
3. 不新增大范围 contract 字段，不扩大到其它 cluster。

## 成功标准

- `584253` 改善不回退。
- `10970944` 稳定不回退。
- `698330`、`706389`、`520394575` 不回退。
- Anchor61 baseline 继续通过。
- 能明确说明当前 cluster 的 canonical result 主要来自 Step6，而不是 Step7 的 legacy 重解释。
