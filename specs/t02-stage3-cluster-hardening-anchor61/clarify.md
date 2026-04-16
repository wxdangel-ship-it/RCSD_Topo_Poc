# Clarify

## 当前 cluster 定义

- 主 cluster：`nonstable_center_junction_extreme_geometry_anomaly`
- 弱保护 cluster：`stable_compound_center_requires_review`

这两条路径都限定在当前 `center_junction / kind_2=4` 的已验证范围内，不扩到 `single_sided_t_mouth`。

## Step6 canonical ownership

本轮要求 Step6 直接稳定承接以下事实：

- `geometry_review_reason`
- bounded regularization 是否生效
- cluster-local geometry flags / optimizer facts
- 当前 cluster 的 geometry problem / validation 事实

不要求本轮新增公开 contract 字段，但要求这些事实在现有 `optimizer_events / final_validation_flags / audit_facts` 中更明确可追溯。

## Step7 要收掉的 fallback

只收当前 cluster：

- 不再主要依赖 raw `acceptance_reason`
- 不再主要依赖 generic token heuristics 才把 root cause 重新解释回 Step6

Step3 / Step5 仍保持更高优先级；若存在 Step3 blocker 或 Step5 canonical foreign，第三刀不强行覆盖。

## Monolith live truth 边界

本轮不做 monolith 大拆分。

允许保留的 monolith wiring：

- 现有 geometry / metric seed 组装
- 现有 `compound_center_applied` 事实向 Step6 controller 的传递

本轮要减少的是：

- 当前 cluster 的最终 root cause 仍回到 monolith / legacy acceptance 再解释

## 测试边界

- 必跑 focused tests
- 必跑 Anchor61 baseline
- 不跑 full-input regression
- 不扩大到新的 cluster scaleout
