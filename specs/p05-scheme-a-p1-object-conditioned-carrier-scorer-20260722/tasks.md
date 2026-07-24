# P05-Scheme-A-P1 任务清单

## A. Specify / source-of-truth

- [x] A001 确认用户正式授权、唯一工作树、51 Case 与排除项。
- [x] A002 建立覆盖产品/架构/研发/测试/QA 的 SpecKit。
- [x] A003 同步项目/P05 source-of-truth 为“P1 已授权并实施中”。
- [x] A004 完成候选、特征、模型、fallback、RoadGraph 输出合同一致性检查。
- [x] A005 同步用户批准的 Gate 4：49 Case合法、2 Case预期失败，51 Case均有确定终态且不缩减模型指标分母。
- [x] A006 同步用户批准的 fallback 边界：Segment 不连带 Movement；Movement 仅因自身问题回退，仅在有效 carrier 确实共享或影响 Junction 内部拓扑时升级 Junction。

## B. Truth-free candidate 与 dataset

- [x] B001 实现 manifest/hash/范围 gate。
- [x] B002 实现 Segment SWSD/strategy/fallback carrier candidates。
- [x] B003 实现 PhysicalMovement Node carrier candidates。
- [x] B004 冻结 candidate run 后执行 label-only join。
- [x] B005 实现 forbidden feature、fold、weight、mask 和 exact reachability 审计。

## C. Neural scorer

- [x] C001 实现 1M~5M object-conditioned GraphSet network。
- [x] C002 实现 weighted listwise candidate loss 与 anomaly/fallback loss。
- [x] C003 实现 outer fold / inner validation / vocabulary / normalization / early stopping。
- [x] C004 实现 confidence、uncertainty、precision-first threshold 与 checkpoint contract。

## D. 执行与安全

- [x] D001 实现 candidate selection 与 hard conflict override。
- [x] D002 复用最小依赖闭包 fallback，保证 skeleton mutation 为零。
- [x] D003 实现 RoadGraph 物化与 CRS/ID/引用/方向/拓扑 hard gate。
- [x] D004 实现 deterministic signature 与 no-repair audit。

## E. 测试

- [x] E001 candidate/label 物理隔离、truth/ID/坐标泄漏测试。
- [x] E002 Segment/Movement candidate reachability 与候选缺失测试。
- [x] E003 grouped split、inner validation、unknown token 与 threshold 测试。
- [x] E004 network 参数量、listwise/anomaly loss、checkpoint 和 synthetic overfit 测试。
- [x] E005 ADVANCE_RIGHT、Junction/Movement fallback 与 RoadGraph 破坏测试。

## F. 正式实验与验收

- [x] F001 运行 51 Case truth-free candidate Gate 0。
- [x] F002 运行单 seed 5-fold development 并冻结超参数。
- [x] F003 运行 3 seeds × 5-fold formal OOF。
- [x] F004 完成 train-only non-neural baseline 和策略基线对比。
- [x] F005 完成同 seed双跑、51 Case RoadGraph/GIS 与资源审计。
- [x] F006 运行完整 P05 回归和代码体量/入口治理审计。
- [x] F007 形成 `validation-summary.md` 并同步 GO/NO-GO source-of-truth。
