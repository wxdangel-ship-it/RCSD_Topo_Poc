# P05-Scheme-A-P2-P2-P1 任务清单

## A. Specify / plan

- [x] A001 冻结用户授权、唯一工作树、输入证据、Movement/Git/模块边界。
- [x] A002 建立产品/架构/研发/测试/QA 五职责 SpecKit。
- [x] A003 冻结 safety-head 与 GO/NO-GO 验收口径。

## B. 数据与模型

- [x] B001 验证 P2-P1 dataset、OOF A/B、P2-P2-P0 hash、分母与 Case folds。
- [x] B002 构建 truth-free safety features 与 label-only join，并完成泄漏审计。
- [x] B003 实现 0.10M~2.00M candidate-set safety head。
- [x] B004 实现 3 seed × 5 outer fold、训练折内层早停/阈值和 held-out OOF 评分。

## C. 安全执行

- [x] C001 实现 base proposal 一致性、safety accept/Segment fallback，禁止 candidate 改选。
- [x] C002 实现 effective Segment→Node requirement 与共享冲突 Junction fallback。
- [x] C003 物化 49 LEGAL + 2 EXPECTED_FAIL RoadGraph 并审计 skeleton/repair/silent-fix。

## D. 测试与收口

- [x] D001 覆盖正常链路、fold/feature 泄漏和 candidate 改选破坏测试。
- [x] D002 运行正式 OOF Run A/B 并验证内容确定性。
- [x] D003 完成专项/历史回归、体量、入口与资源审计；完整 P05 回归保留一个与本轮无关的 WSL RSS 兼容失败。
- [x] D004 写入 validation summary 并同步稳定事实结论。
