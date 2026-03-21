# 11. Risks And Technical Debt

- Tool2 若不稳定清理旧输出，容易出现 fix 与全局结果不一致
- Tool4 若静默吞掉冲突 `road_id`，会污染 `patch_id` 结果
- Tool5 若不用空间索引，会在真实数据上出现明显性能问题
- 当前仍不为 Tool6+ 预建设计
