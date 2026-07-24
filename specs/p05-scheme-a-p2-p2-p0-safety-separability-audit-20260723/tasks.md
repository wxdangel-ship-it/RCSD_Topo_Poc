# P05-Scheme-A-P2-P2-P0 任务清单

## A. Specify / plan

- [x] A001 冻结用户授权、唯一工作树、输入证据、Movement/Git/模块边界。
- [x] A002 建立产品/架构/研发/测试/QA 五职责 SpecKit。
- [x] A003 冻结 calibration / safety-head / evidence-no-go 决策口径。

## B. 审计实现

- [x] B001 实现 manifest/hash、A/B 确定性与分母验证。
- [x] B002 实现 truth-free safety signal 与 label-only 隔离。
- [x] B003 实现 accepted wrong 的 Segment 根、Node 传播和 effective carrier 分类。
- [x] B004 实现稳定 false-use、MIXED_CARRIER 和 40 Review 审计。
- [x] B005 实现 feature collision 与 score-only zero-error coverage 审计。

## C. 测试

- [x] C001 覆盖正常小型链路和 deterministic replay。
- [x] C002 覆盖缺失 seed/group、hash 不匹配与 compatibility lineage 缺失。
- [x] C003 覆盖 truth/ID 泄漏和 accepted/effective 口径混淆。

## D. 正式运行与收口

- [x] D001 运行正式 P2-P1 A/B 审计。
- [x] D002 运行同输入重复审计并比较内容 signature。
- [x] D003 完成专项回归、体量与入口审计；完整历史 P05 回归沿用 P2-P1 证据并明确本轮环境边界。
- [x] D004 写入 validation summary 并同步事实结论。
