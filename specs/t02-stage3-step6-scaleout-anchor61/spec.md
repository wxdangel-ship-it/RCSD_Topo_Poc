# T02 / Stage3 Step6 Scaleout Anchor61

## 本轮定位

- 本轮是 `Step6 sidecar bounded regularization candidate + selector` 的工程扩展与固化轮。
- 本轮不是整体 Stage3 重构，不是 full-input 正式交付轮，不是 Step7 语义修辞轮。
- Anchor61 仍是唯一正式验收基线。

## 冻结前提

1. Anchor61 是当前唯一正式验收基线。
2. full-input 当前仅承担 regression-only 角色。
3. 第一刀已打开 `584253` 的 Step6 几何观测。
4. 第二刀已验证：
   - `584253` 获得实质几何改善
   - `10970944` 的 compound_center 路径无回退
   - Anchor61 baseline `61/61 passed`
5. 当前有效策略冻结为：
   - `Step6 sidecar bounded regularization candidate + selector`

## 本轮目标

1. 将 second cut 从单样本成功扩展到 `kind_2=4` 的可推广子簇。
2. 用 focused tests 与 cluster evaluation 固化第二刀策略。
3. 保持 `10970944 / 698330 / 706389 / 520394575 / Anchor61 baseline` 不回退。
4. 形成下一轮是否继续扩 Step6 的工程证据。

## 非目标

1. 不做 Stage3 整体架构重构。
2. 不动 Step4 / Step5 / Step7 / monolith 主链。
3. 不做 full-input 正式交付。
4. 不改 Anchor61 manifest 口径。
5. 不做 case id / mainnodeid 特判。

## 成功标准

1. `584253` 保持显著改善。
2. `10970944` 保持 compound_center 稳定。
3. `698330 / 706389 / 520394575` 不回退。
4. Anchor61 baseline 继续 `61/61 passed`。
5. `kind_2=4` cluster eval 能清晰说明：
   - 哪些子簇可扩展
   - 哪些子簇必须排除
   - 当前 bounded regularization 的有效作用面
