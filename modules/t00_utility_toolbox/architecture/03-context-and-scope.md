# 03 上下文与范围

## 当前上下文

- Tool1 的背景是：先把全量 Patch 矢量目录整理为统一 `patch_all` 骨架
- Tool2 / Tool3 的背景是：在统一 `patch_all/<PatchID>/Vector/` 路径上处理全局辅助图层

## 当前范围

- Tool1 / Tool2 / Tool3 的规格、契约与执行边界
- Patch 目录骨架初始化
- `Vector/` 数据归位
- 全局 `DriveZone` 预处理与合并
- 全局 `Intersection` 预处理与汇总
- Patch 级异常不中断全量的处理口径
- 目标根目录日志与摘要的最小语义

## 当前范围外

- Tool4+
- 深度 manifest 治理
- 数据库落仓
- 任何业务要素生产逻辑
