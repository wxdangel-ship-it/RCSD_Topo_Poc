# T00 Utility Toolbox 计划

## 1. 当前阶段说明

`T00` 当前处于直接增量实现阶段：

- Tool1 已完成
- Tool2 需要按修正版重构为“per-patch fix + 全局 merge”
- Tool3 维持上一版实现
- 本轮新增 Tool4 / Tool5

## 2. 文档组织关系

- `spec.md`：固化 Tool1 至 Tool5 的需求基线
- `plan.md`：说明当前增量实现顺序与收口方式
- `tasks.md`：拆分本轮任务与验证事项
- `modules/t00_utility_toolbox/README.md`：模块入口与运行说明
- `modules/t00_utility_toolbox/AGENTS.md`：后续 Agent / CodeX 约束
- `modules/t00_utility_toolbox/INTERFACE_CONTRACT.md`：稳定输入输出语义

## 3. 实现顺序建议

建议实现顺序固定为：

1. Tool2 修正版
2. Tool4
3. Tool5

原因：

- Tool2 修正版先把 `DriveZone_fix.geojson` 与根目录全局 `DriveZone.geojson` 的正式输出关系固化
- Tool4 先完成 `patch_id` 赋值，为后续一层路网增强提供稳定输入
- Tool5 依赖 Tool4 输出，必须在 Tool4 之后实现和验证

## 4. 各工具实现边界

- Tool2：只负责 per-patch `DriveZone_fix.geojson` 与根目录全局 `DriveZone.geojson`
- Tool3：沿用既有汇总逻辑，本轮不做业务重写
- Tool4：只负责 `patch_id` 属性关联与 unmatched / conflict 输出
- Tool5：只负责基于 Tool4 输出和 SW 原始路网写入 `kind`

## 5. 下一步计划

本轮代码与最小必要文档更新完成后，下一步只做两类工作：

- 在内网真实数据路径执行 Tool2 / Tool4 / Tool5
- 根据真实运行结果修正参数、异常处理或摘要口径中的最小问题

## 6. 暂缓项

当前明确暂缓：

- Tool6+
- Tool3 全量重写
- 复杂 manifest 或数据库治理
- 新的重型框架抽象
- 与本轮无关的 `history/bootstrap` 扩展
