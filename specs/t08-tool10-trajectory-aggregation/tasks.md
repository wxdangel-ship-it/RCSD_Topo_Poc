# T08 Tool10 轨迹聚合任务

## Phase 0 - Specify / Plan

- [x] Product：确认输入为具体 Patch，输出为一个 `Traj/raw_dat_pose.gpkg`。
- [x] Architecture：确认单图层 `LineStringZ`、原子落盘和 T08 callable + script 结构。
- [x] Development：确认复用 T08 GPKG writer、不新增依赖、不修改 T00 Tool10。
- [x] Testing：定义合成边界与真实来源 Patch 验证。
- [x] QA：定义 CRS、拓扑、几何语义、审计、性能五项验收。
- [x] 完成 8 个真实来源 Patch、61,861 点的只读审计。

## Phase 1 - Contract

- [x] 更新 T08 SPEC、contract、README、architecture 与局部 AGENTS 命名例外。
- [x] 登记 `scripts/t08_tool10_trajectory_aggregation.py` 正式入口。

## Phase 2 - Implement

- [x] 每次写入 `.py` 前检查当前字节数。
- [x] 实现严格 PointZ / CRS / 数值校验。
- [x] 实现排序、米制断点切分和点数守恒。
- [x] 实现单 GPKG `LineStringZ` 聚合与审计 summary。
- [x] 实现临时文件落盘、覆盖保护和失败清理。
- [x] 导出 callable 并增加 Tool10 脚本。

## Phase 3 - Test / QA

- [x] 增加 Tool10 聚焦测试。
- [x] 运行 Tool10 聚焦测试和 T08 全回归。
- [x] 复制真实来源 Patch `00000009` 验证 3 段与 Z。
- [x] 检查 GPKG CRS、Z 标志、几何类型、点数守恒和审计字段。
- [x] 检查入口登记、源码体量与 `git diff --check`。
- [x] 完成已修改 / 已验证 / 待确认交付回报。
