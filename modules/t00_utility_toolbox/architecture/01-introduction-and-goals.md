# 01 Introduction And Goals

## 上下文

T00 是项目历史工具集合模块，保留数据整理、格式转换、字段补充、辅助导出和批量检查工具。它服务于历史问题复现、人工排查和 T08 能力迁移参考，不属于当前主业务生产闭环。

T00 的存在价值不是生产 SWSD-RCSD relation、RCSDSegment 或通行规则，而是让仍需追溯的工具有固定落点、固定入口和最小治理边界。

## 目标

- 保留 Tool1-7、Tool9-11 的稳定执行入口和可追溯输出。
- 保持工具行为轻量、可复跑、可诊断。
- 明确 T00 与 T08 的边界，避免历史工具继续扩展为正式预处理主链。

## 当前范围

- Patch 目录骨架整理和 `Vector/` 数据归位。
- DriveZone、Intersection、DivStripZone 的历史逐 Patch 预处理与汇总。
- A200 Road / Node 的历史字段补充和导出。
- 顶层 GeoJSON 批量转 GPKG。
- JSON / NDJSON 上车点导出为双图层 GPKG。
- MIF 转 GeoJSON / GPKG。

## 兼容边界

- Tool 编号保留历史命名；当前没有 Tool8，不能因编号连续性推定 Tool8 存在。
- 当前官方入口仍是 repo root `scripts/t00_tool*.py`，不是 repo CLI 子命令。
- `specs/t00-utility-toolbox/*` 只用于治理过程追溯，不替代当前模块文档。

## 非目标

- 不构建 SWSD Segment。
- 不生成路口 relation 或虚拟路口面。
- 不执行 Segment 替换。
- 不还原 F-RCSD 通行规则。
- 不替代 T08 正式预处理、质检和修复模块。
