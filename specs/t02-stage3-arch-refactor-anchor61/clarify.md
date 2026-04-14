# T02 / Stage3 Anchor61 架构优化澄清

## 1. Anchor61 manifest 放置位置

- 固定位置：`tests/modules/t02_junction_anchor/data/anchor61_manifest.json`
- 理由：属于正式验收层数据清单，应随测试层一起版本化

## 2. 是否需要补齐现有测试到 61 个 case

- 需要
- 方式：新增 Anchor61 正式验收层
- 约束：不删除现有 regression tests，不把 full-input tests 混入正式验收口径

## 3. full-input tests 在本轮的角色

- 仅作 fixture / dev-only / regression
- 不再表述为 Stage3 正式交付基线
- 可以继续跑，但不输出正式 full-input 交付结论

## 4. 契约同步范围

- 仅同步“Anchor61 唯一正式验收基线”与“full-input regression-only 边界”
- 不改 Step1~7 业务语义
- 不改失败语义本体
- 不改 Stage4 口径

## 5. `kind` provenance 本轮目标

- `kind` 优先来自 `nodes.kind`
- 若缺失则 fallback 到 `nodes.kind_2`
- 必须显式记录 `kind_source`
- 不允许把 `kind_2` 伪装成 `nodes.kind`

## 6. `virtual_intersection_poc.py` 本轮拆分程度

- 不追求一次拆成很小文件
- 但必须从“独占真实执行权”收回到 orchestrator
- Step3 / Step5 / Step6 / Step7 的 canonical live truth 必须迁出

## 7. Step6 与 cleanup 的完成判定

- `late_*cleanup*` 只能影响 `Step6 final state / optimizer events`
- 不得再回写 `Step4/Step5` 语义真值
- 不得再承担业务补救职责
- simple `single_sided_t_mouth` 与 `center_junction` 的几何控制结果必须可验证
