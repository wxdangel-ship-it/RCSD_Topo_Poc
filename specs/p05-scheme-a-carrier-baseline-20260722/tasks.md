# P05 方案 A Carrier 基线任务

## A. Source-of-truth

- [x] A001 将统一业务归档同步到本 worktree。
- [x] A002 更新项目级 P05 当前口径，旧 P0–P3 明确为历史实验。
- [x] A003 更新 P05 SPEC、architecture 与 INTERFACE_CONTRACT。
- [x] A004 同步模块生命周期和文档盘点口径。

## B. 合同与实现

- [x] B001 实现冻结骨架与 canonical signature。
- [x] B002 实现 51 Case manifest/hash/CRS gate。
- [x] B003 实现全部 T01 Segment 和 ADVANCE_RIGHT 重建。
- [x] B004 实现策略结果三态基线。
- [x] B005 实现 Segment/Movement carrier 软标签和权重/mask。
- [x] B006 实现 RealityChangeClue。
- [x] B007 实现 Segment/Junction/Movement 最小闭包 fallback。
- [x] B008 实现不可变 run 输出和 artifact hash。

## C. 测试

- [x] C001 canonical 与骨架不可变测试。
- [x] C002 SegmentConnector 禁止和 ADVANCE_RIGHT 测试。
- [x] C003 策略状态映射和未知状态拒绝测试。
- [x] C004 Segment/Junction/Movement fallback 与升级测试。
- [x] C005 SWSD Road/Node 不合法与 clue 测试。
- [x] C006 manifest/hash/CRS 篡改测试。

## D. 真实数据验收

- [x] D001 完成 51 Case Run A。
- [x] D002 完成 51 Case Run B。
- [x] D003 完成 skeleton/baseline/label/clue/fallback 确定性审计。
- [x] D004 完成 CRS、Road/Node、mainnode、Movement carrier 与 no-silent-fix QA。
- [x] D005 完成资源门禁。
- [x] D006 运行完整 P05 回归。
- [x] D007 形成 `validation-summary.md` 并回填本任务状态。
