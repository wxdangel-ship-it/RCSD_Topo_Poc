# 04 方案策略

## 状态

- 当前状态：`T00 模块方案策略说明`
- 来源依据：
  - `specs/t00-utility-toolbox/spec.md`
  - `INTERFACE_CONTRACT.md`

## 主策略

1. 先以文档固化 T00 与 Tool1 的范围、契约和门禁，再进入编码
2. Tool1 后续只实现“目录骨架初始化 + Vector 数据归位 + Patch 级异常汇总”
3. 未来若新增工具，逐个补规格，不在本轮预建通用框架

## 降级与失败策略

- Tool1 的最小失败单元是单个 Patch
- Patch 异常时跳过该 Patch、记入失败并继续处理其它 Patch
- 全流程结束后统一汇总异常原因与统计摘要

## 文档策略

- 稳定范围与边界由 `../../specs/t00-utility-toolbox/spec.md` 承担
- 输入、输出、覆盖、失败与摘要契约由 `INTERFACE_CONTRACT.md` 承担
- `AGENTS.md` 约束后续执行方式
- `README.md` 提供操作者入口
