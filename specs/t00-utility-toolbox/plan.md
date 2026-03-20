# T00 Utility Toolbox 计划

## 1. 当前阶段说明

T00 当前已进入直接实现阶段：

- Tool1 已完成
- 本轮实现 Tool2 / Tool3
- 仍保持轻量增量扩展，不引入重型框架

## 2. 文档组织计划

T00 当前文档分为两层：

- `specs/t00-utility-toolbox/`
  - `spec.md`：固化 Tool1 / Tool2 / Tool3 的需求基线
  - `plan.md`：说明当前实现顺序与后续收口方式
  - `tasks.md`：拆分当前任务与后续待办
- `modules/t00_utility_toolbox/`
  - `README.md`：模块入口与运行说明
  - `AGENTS.md`：后续 Agent / CodeX 约束
  - `INTERFACE_CONTRACT.md`：稳定输入输出与统一口径
  - `architecture/*`：模块级长期源事实

## 3. 模块实现顺序建议

建议顺序固定为：

1. Tool1：先建立 `patch_all` 骨架与 `Vector/` 归位
2. Tool2：基于统一 `patch_all/<PatchID>/Vector/DriveZone.geojson` 做全量合并
3. Tool3：基于统一 `patch_all/<PatchID>/Vector/Intersection.geojson` 做全量汇总

这样可以保持数据入口一致，避免 Tool2 / Tool3 直接绕过 Tool1 的路径整理规则。

## 4. 各工具实现边界

- Tool1：只负责目录骨架初始化和 `Vector/` 数据归位
- Tool2：只负责单 Patch `DriveZone` 预处理、全量合并和全局输出
- Tool3：只负责单 Patch `Intersection` 预处理、全量汇总和全局输出

三者共用统一的 `Vector/`、`3857`、最小修复、拓扑保持简化、删除旧输出再重建和进度输出口径。

## 5. 下一阶段计划

本轮完成实现后，下一步只做两类收口：

- 在真实 `patch_all` 数据路径上完成 Tool2 / Tool3 的全量运行
- 根据真实运行结果补最小必要的参数或错误处理，不扩张范围

## 6. 暂缓项

当前明确暂缓：

- Tool4+
- 额外架构扩展
- `history/bootstrap` 继续铺开
- 复杂治理机制
- 单 Patch 中间结果的正式化持久化规则
