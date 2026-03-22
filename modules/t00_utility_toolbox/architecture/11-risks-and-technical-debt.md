# 11. Risks And Technical Debt

- Tool2 若不稳定清理旧输出，容易出现 fix 与全局结果不一致
- Tool5 若不用空间索引，会在真实数据上出现明显性能问题
- Tool6 若输入 CRS 缺失却被猜测，会直接污染输出
- Tool6 的 `EPSG:3857` GeoJSON 属于项目内约定输出，需要持续在摘要和文档中显式说明
- 当前仍不为 Tool7+ 预建设计
