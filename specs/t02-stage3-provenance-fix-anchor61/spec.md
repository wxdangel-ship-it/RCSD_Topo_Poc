# T02 / Stage3 provenance fix

## 范围

- 本轮只修 `Step6 second cut` improved geometry 到最终 `GPKG / PNG` 的 handoff。
- 正式基线仍为 Anchor61。
- full-input 仍是 regression-only，不是本轮正式交付面。

## 非目标

- 不做第三刀。
- 不扩展 regularization 作用面。
- 不改 Step4 / Step5 / Step7 业务语义。
- 不改 full-input 逻辑。
- 不做 case patch。

## 成功标准

- `584253` 的 after GPKG geometry 真实变化，并且 PNG 主体反映变化。
- `705817` 的变化真实传导到最终图。
- `10970944` 保护路径不回退。
- `698330 / 706389 / 520394575` 不回退。
- Anchor61 baseline 继续通过。
