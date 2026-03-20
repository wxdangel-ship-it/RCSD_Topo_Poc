# 04 方案策略

## 状态

- 当前状态：`T00 模块方案策略说明`
- 来源依据：
  - `specs/t00-utility-toolbox/spec.md`
  - `INTERFACE_CONTRACT.md`

## 主策略

1. Tool1 继续承担 `patch_all` 骨架初始化和 `Vector/` 数据归位
2. Tool2 / Tool3 在 Tool1 统一路径基础上增量实现，不另起第二套结构
3. 未来若新增工具，逐个补规格，不提前搭重型通用框架

## 降级与失败策略

- Tool1 / Tool2 / Tool3 的最小异常单元都是单个 Patch
- 缺失输入或处理异常时，跳过当前 Patch 并继续处理其它 Patch
- 全流程结束后统一汇总异常原因与统计摘要

## 文档策略

- 稳定范围与边界由 `../../specs/t00-utility-toolbox/spec.md` 承担
- 输入、输出、覆盖、失败与摘要契约由 `INTERFACE_CONTRACT.md` 承担
- `AGENTS.md` 约束后续执行方式
- `README.md` 提供操作者入口
