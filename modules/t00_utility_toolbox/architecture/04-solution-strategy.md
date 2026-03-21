# 04. Solution Strategy

1. Tool1 继续承担 `patch_all` 骨架初始化与 `Vector/` 数据归位。
2. Tool2 先产出 per-patch `DriveZone_fix.geojson`，再做全局 merge。
3. Tool3 维持既有逐 Patch 处理与全局汇总。
4. Tool4 通过属性关联写入 `patch_id` 并产出 unmatched。
5. Tool5 基于 Tool4 输出和 SW 空间匹配写入 `kind`。

所有工具共享固定脚本入口、最小日志摘要和进度输出风格。
