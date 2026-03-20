# 01 引言与目标

## 状态

- 当前状态：`T00 模块级架构说明（文档基线阶段）`
- 来源依据：
  - `specs/t00-utility-toolbox/spec.md`
  - repo root `SPEC.md`
  - 本轮任务书

## 当前正式定位

- 模块路径：`modules/t00_utility_toolbox`
- 当前角色：RCSD 项目内 Utility Toolbox / 工具集合模块
- 下游关系：为项目内部实验准备、数据整理和问题排查提供辅助工具支持，不直接进入业务要素生产链路

## 模块目标

`t00_utility_toolbox` 的长期目标是：

1. 为项目内工具建立统一、轻量、可治理的模块落点
2. 先以文档方式固化每个工具的范围、边界与契约，再进入编码
3. 避免辅助工具演化为业务生产模块或无边界的脚本堆积区

## 文档目标

本模块当前正式文档面由以下文件共同组成：

- `architecture/*`
- `INTERFACE_CONTRACT.md`
- `AGENTS.md`
- `README.md`
- `../../specs/t00-utility-toolbox/*`

`history/*` 暂未启用，待 Tool1 后续进入实际迭代后再按需要补建。
