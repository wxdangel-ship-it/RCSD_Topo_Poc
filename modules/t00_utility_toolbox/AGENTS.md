# T00 - AGENTS

## 1. 模块角色说明

- 模块 ID：`t00_utility_toolbox`
- 模块名称：`T00 Utility Toolbox`
- 模块角色：项目内工具集合模块
- 当前承接 Tool1 至 Tool6 的固定脚本和共享底层能力

## 2. 开工前先读

1. `../../specs/t00-utility-toolbox/spec.md`
2. `INTERFACE_CONTRACT.md`
3. `architecture/01-introduction-and-goals.md`
4. `README.md`

若这些文档冲突，先停下并汇报，不得自行选择有利口径继续扩写实现。

## 3. 模块边界

- `T00` 不是 Skill
- `T00` 不是业务生产模块
- `T00` 不直接生成 RCSD 业务要素
- `T00` 只承接项目内部工具，不得顺手扩展成重型业务框架

## 4. 当前范围

当前正式范围是 Tool1 至 Tool6：

- Tool1：Patch 数据整理
- Tool2：DriveZone per-patch fix + 全局 merge
- Tool3：Intersection 逐 Patch 预处理与汇总
- Tool4：A200 road 增加 `patch_id`
- Tool5：A200 road 增加 SW 原始 `kind`
- Tool6：A200 node shp 导出 GeoJSON

## 5. 文档优先原则

- 新工具进入 `T00` 前，先补规格与契约
- Tool2 至 Tool6 的修改必须以 `spec.md` 和 `INTERFACE_CONTRACT.md` 为准
- `README.md` 只承担入口说明，不替代长期源事实

## 6. 禁止事项

- 不得把 `T00` 演化成业务生产模块
- 不得未经确认擅自扩展 Tool1 至 Tool6 的范围
- 不得绕过 `spec` 直接编码扩写
- 不得引入复杂 manifest、数据库落仓或重型产线编排
- 不得在模块根目录新增 `SKILL.md`

## 7. 统一技术语义约束

- Patch 子目录统一使用 `Vector/`
- Tool2 / Tool3 / Tool6 的几何处理统一在 `EPSG:3857`
- Tool4 / Tool5 通过脚本头部 `TARGET_EPSG` 固定目标 CRS，默认 `3857`
- Tool5 允许对不同输入分别设置默认 CRS
- “压缩”统一等于拓扑保持的几何简化
- 允许最小几何修复，但不允许复杂推断修复
- 所有输出已存在时先删除再重建
- 后续实现必须提供命令行进度输出

## 8. 各工具实现风格约束

- Tool1：固定脚本 + 文件头集中参数
- Tool2：固定脚本 + per-patch `DriveZone_fix.geojson` + 根目录全局输出
- Tool3：固定脚本 + 逐 Patch 处理后汇总
- Tool4：固定脚本 + 属性关联 + unmatched 输出
- Tool5：固定脚本 + 空间索引 + `kind` 去重重组
- Tool6：固定脚本 + shp 元数据审计 + GeoJSON 导出 + 日志摘要

## 9. 扩展门禁

满足以下条件后，才可继续向 `T00` 增加新工具或明显扩展现有工具：

1. 文档口径一致
2. 输入、输出、覆盖、异常、摘要语义已稳定
3. 扩展不改变 `T00` 作为内部工具模块的定位
