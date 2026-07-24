# P05-Scheme-A-P2-P1 任务清单

## A. Specify / source-of-truth

- [x] A001 确认用户授权、唯一工作树、POC_Data、排除项、T07 DriveZone-only、Movement关闭和Git边界。
- [x] A002 建立产品/架构/研发/测试/QA五职责SpecKit。
- [x] A003 同步项目级和P05模块级source-of-truth为P2-P1已完成并正式NO-GO。
- [x] A004 更新模块Python callable接口合同，不新增正式入口。

## B. 联合数据集

- [x] B001 冻结P1 Segment与PTO FINAL_NODE truth-free candidates。
- [x] B002 实现ID/绝对坐标/truth/Oracle/relation字段泄漏审计。
- [x] B003 candidate manifest冻结后连接Segment有效标签及Road来源条件化Node标签。
- [x] B004 实现M0 grouped folds、权重、mask和40个ADVANCE_RIGHT审计。
- [x] B005 实现Segment/Node reachability与JunctionUnit compatibility Oracle。

## C. 模型与训练

- [x] C001 实现1M~5M Segment/Node object-conditioned scorer。
- [x] C002 实现fold-local vocabulary、normalization和inner validation。
- [x] C003 实现listwise candidate loss、anomaly loss和calibration。
- [x] C004 实现checkpoint/score/confidence/uncertainty/model signature合同。

## D. 执行与安全

- [x] D001 实现模型score驱动的Segment/Node选择和通用compatibility gate。
- [x] D002 实现confidence/anomaly、Segment/Junction最小fallback。
- [x] D003 验证49 LEGAL + 2 EXPECTED_FAIL、错误替换和零silent fix（错误替换未过门，保留NO-GO证据）。
- [x] D004 实现accepted coverage、USE_RCSD coverage和异常指标。

## E. 测试

- [x] E001 配置、schema、feature和group单元测试。
- [x] E002 candidate/truth、fold、ID/坐标和threshold泄漏破坏测试。
- [x] E003 Node/mainnode兼容、同ID不同payload和candidate缺失测试。
- [x] E004 模型small-batch、参数量、score重放和fallback测试。

## F. 正式实验与收口

- [x] F001 运行正式dataset/compatibility Oracle。
- [x] F002 运行正式3 seeds × 5-fold OOF。
- [x] F003 运行同seed独立重放和内容确定性比较。
- [x] F004 完成GIS/CRS、资源、artifact hash和完整P05回归。
- [x] F005 完成体量/入口治理、validation summary和最终source-of-truth。
