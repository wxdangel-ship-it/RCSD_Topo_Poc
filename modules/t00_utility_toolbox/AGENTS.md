# T00 - AGENTS

## 1. 模块角色说明

- 模块 ID：`t00_utility_toolbox`
- 模块名称：`T00 Utility Toolbox`
- 模块角色：项目内工具集合模块
- 当前用途：承接辅助性工具，而不是承接业务生产链路

## 2. 开工前先读

1. `../../specs/t00-utility-toolbox/spec.md`
2. `INTERFACE_CONTRACT.md`
3. `architecture/01-introduction-and-goals.md`
4. `README.md`

如发现上述文档之间存在冲突，先停止并汇报，不得自行择一扩写实现。

## 3. T00 的边界

- `T00` 不是 Skill
- `T00` 不是业务生产模块
- `T00` 不直接生成 RCSD 业务要素
- 当前只允许围绕项目内部工具开展文档和后续实现工作

## 4. 当前范围

当前纳入 Tool1 / Tool2 / Tool3：

- Tool1：Patch 数据整理脚本
- Tool2：全量 DriveZone 的预处理与合并
- Tool3：全量 Intersection 的预处理与汇总

未经过新的规格确认，不得擅自补入 Tool4 及以上工具。

## 5. 文档优先原则

- 新工具进入 T00 前，必须先补规格与范围文档
- Tool1 / Tool2 / Tool3 的后续调整必须以 `spec.md`、`INTERFACE_CONTRACT.md` 与 `architecture/*` 为准
- `README.md` 只承担入口说明，不替代长期源事实

## 6. 禁止事项

- 不得把 T00 演化成业务生产模块
- 不得未经确认擅自扩展 Tool1 / Tool2 / Tool3 范围
- 不得绕过 `spec` 直接编码扩写
- 不得把 Tool2 / Tool3 扩展为复杂产线编排、深度 manifest 治理或数据库落仓
- 不得在模块根目录新增 `SKILL.md`

## 7. 统一技术语义约束

- 路径口径统一为 `Vector/`
- 所有几何处理统一在 `EPSG:3857`
- “压缩”统一等于拓扑保持的几何简化
- 允许最小几何修复，但不允许复杂推断式修复
- 后续实现必须提供命令行进度输出

## 8. 各工具实现风格约束

- Tool1：固定脚本、文件头集中参数、不要求命令行参数驱动
- Tool2：项目内固定脚本，参数轻量可控，日志和摘要落在 `patch_all` 根目录
- Tool3：项目内固定脚本，参数轻量可控，日志和摘要落在 `patch_all` 根目录
- 缺失输入文件或异常 Patch 不得中断全量流程

## 9. 后续扩展门禁

满足以下条件后才能继续向 T00 增加新工具或明显扩展现有工具：

1. 文档基线已确认
2. 当前范围仍然仅为 Tool1 / Tool2 / Tool3
3. 输入、输出、覆盖、异常、摘要与统一几何口径已确认
4. 明确不顺带扩展 Tool4+ 或其它附属治理机制
