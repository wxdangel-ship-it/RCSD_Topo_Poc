# 01 引言与目标

## 状态

- 当前状态：`T00 模块级架构说明（Tool1-3 baseline）`
- 来源依据：
  - `specs/t00-utility-toolbox/spec.md`
  - `modules/t00_utility_toolbox/INTERFACE_CONTRACT.md`
  - 当前 `scripts/` 与 `src/` 实现

## 当前正式定位

- 模块路径：`modules/t00_utility_toolbox`
- 当前角色：RCSD 项目内 Utility Toolbox / 工具集合模块
- 下游关系：为项目内部实验准备、数据整理、全局辅助图层预处理和问题排查提供工具支持，不直接进入业务要素生产链路

## 模块目标

`t00_utility_toolbox` 的长期目标是：

1. 为项目内工具建立统一、轻量、可治理的模块落点
2. 按工具粒度持续增加如 Tool1 / Tool2 / Tool3 这类内部处理工具，同时保持边界清晰
3. 避免辅助工具演化为业务生产模块或无边界的脚本堆积区

## 文档目标

本模块当前正式文档面由以下文件共同组成：

- `architecture/*`
- `INTERFACE_CONTRACT.md`
- `AGENTS.md`
- `README.md`
- `../../specs/t00-utility-toolbox/*`

`history/*` 暂未启用，待后续真实迭代需要时再按需要补建。
