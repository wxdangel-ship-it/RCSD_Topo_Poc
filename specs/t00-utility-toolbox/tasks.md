# T00 Utility Toolbox 任务清单

## 1. 本轮实现任务

- [x] 盘点现有 T00 / Tool1 的目录、入口、日志和文档位置
- [x] 在现有 T00 风格下实现 Tool2 `DriveZone` 预处理与全量合并
- [x] 在现有 T00 风格下实现 Tool3 `Intersection` 预处理与全量汇总
- [x] 为 Tool2 / Tool3 补最小共享底层工具，避免重复实现
- [x] 为 Tool2 / Tool3 提供阶段级和 Patch 级进度输出
- [x] 更新 T00 的 `README / AGENTS / INTERFACE_CONTRACT`
- [x] 更新 T00 的 `spec / plan / tasks`
- [x] 修正 T00 `architecture/*` 中与 Tool1-only 状态冲突的源事实
- [x] 补录新增执行入口到入口注册表

## 2. 后续待办

- [ ] 在真实 `D:\TestData\POC_Data\patch_all` 数据路径上跑通 Tool2
- [ ] 在真实 `D:\TestData\POC_Data\patch_all` 数据路径上跑通 Tool3
- [ ] 基于真实运行结果复核缺失输入和异常 Patch 的统计摘要
- [ ] 若真实数据暴露 CRS 缺口，再仅做最小必要参数调整

## 3. 推荐实现顺序

1. Tool1
2. Tool2
3. Tool3

## 4. 本轮不做

- [x] 不返工 Tool1 业务逻辑
- [x] 不扩展 Tool4+
- [x] 不做复杂基线治理
- [x] 不强制持久化 Tool2 / Tool3 的单 Patch 中间结果
- [x] 不因为未来扩展而提前搭重型框架
