# 06 风险与技术债

## 1. 业务风险

- 单向补段已经进入正式范围，但它仍然只能作用于 Step5C 后未构段 road，不能反向污染双向 Step1-Step5C。
- `Road.kind` 只在已确认的局部续行规则中使用前两位道路等级；字段缺失时不能通过几何形态补语义。
- 右转专用道、封闭式道路、历史高等级边界和复杂分歧 / 合流场景容易触发误构段，必须依赖审计证据判断。

## 2. 已知未闭合问题

- `XXXS5` 中仍存在旁路分支超过距离门控的历史风险，需要通过 baseline 与证据继续跟踪。
- `XXXS7` 中仍存在双向旁路历史风险，需要避免后续优化扩大为静默通过。
- Step2 局部热点 pair 可能带来耗时和内存压力。

## 3. 结构债

`step2_segment_poc.py` 已抽离图算法、运行时、support、candidate channel 等 helper，但 pair validation、tighten 与 orchestration 主链仍然偏重。后续继续拆分时必须保持接口和测试迁移同步，不能只为了体量降低而改变业务语义。

## 4. 文档债

旧文档曾把 accepted baseline、构件视图、质量要求和风险分别放在不一致的编号中。当前已收敛为 01-06 主结构，`accepted-baseline.md` 作为补充材料保留。后续新增阶段说明时，应优先落入 `03-solution-strategy.md` 的业务步骤，而不是另起散乱编号。

## 5. 缓解方式

- 用 `INTERFACE_CONTRACT.md` 固定入口和产物契约。
- 用 `04-evidence-and-audit.md` 固定证据与 baseline 守护口径。
- 用 tests 与 freeze compare 区分代码回归、样例回归和业务口径变更。
