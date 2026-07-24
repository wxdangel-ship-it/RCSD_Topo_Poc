# P05-Scheme-A-Dataset-P0 任务清单

## A. Specify / source-of-truth

- [x] A001 确认用户授权、唯一工作树、POC_Data、排除项、T07 DriveZone-only 和 Movement 关闭。
- [x] A002 建立覆盖产品/架构/研发/测试/QA 的 SpecKit。
- [x] A003 同步 P05 项目级/模块级 source-of-truth 为 Dataset-P0 完成结论。
- [x] A004 完成模块角色、candidate、label、Oracle 与 RoadGraph 合同一致性检查。

## B. 模块语义化数据清单

- [x] B001 实现九模块 role contract。
- [x] B002 输出 M0 sample/artifact 与 M2R target 语义清单。
- [x] B003 实现权重、task mask、Unknown/runtime failure和批准排除审计。
- [x] B004 验证 T01 RCSD label=0、T07 DriveZone-only 与 Movement零决策。

## C. Truth-free candidate reachability

- [x] C001 验证 PTO candidate manifest/hash和零truth输入。
- [x] C002 实现 T01 fallback、raw RCSD、T03-T06 proposal来源分类。
- [x] C003 实现 Segment全体与USE_RCSD Road candidate reachability。
- [x] C004 实现 T06 final Road/Node对象可达性与联合exact。
- [x] C005 输出不可达对象的模块级归因和mask/fallback。

## D. 测试

- [x] D001 配置、module role、T07 mode和权重测试。
- [x] D002 hash、scope、candidate/truth隔离和Movement零决策测试。
- [x] D003 T01误标RCSD、Unknown误标negative、T11 candidate误标truth破坏测试。
- [x] D004 Segment/Road/Node candidate缺失和来源分类测试。

## E. 正式实验与验收

- [x] E001 运行 Dataset-P0 Run A/B。
- [x] E002 验证 Gate 0~4、USE_RCSD与联合可达性。
- [x] E003 完成GIS、资源、确定性和artifact hash审计。
- [x] E004 运行完整P05回归与体量/入口治理审计。
- [x] E005 形成 validation summary并同步最终source-of-truth。
