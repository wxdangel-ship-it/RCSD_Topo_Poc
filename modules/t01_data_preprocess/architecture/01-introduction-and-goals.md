# 01 引言与目标

## 状态
- 当前状态：`模块级架构说明（基于当前 accepted baseline）`
- 来源依据：
  - [spec.md](/E:/Work/RCSD_Topo_Poc/specs/t01-data-preprocess/spec.md)
  - [INTERFACE_CONTRACT.md](/E:/Work/RCSD_Topo_Poc/modules/t01_data_preprocess/INTERFACE_CONTRACT.md)
  - 当前三组活动基线结果

## 当前正式定位
- 模块路径：`modules/t01_data_preprocess`
- 当前角色：
  - 对普通道路网络中，从高等级到低等级，逐级提取双向联通的路段
- 下游关系：
  - 为后续关键路口锚定和路段构建打基础

## 模块目标
`t01_data_preprocess` 的长期目标是：

1. 在普通道路网络上稳定提取双向路段，并形成可追溯的 working graph 结果
2. 以 staged residual graph 方式逐轮向更低等级扩展构段
3. 为后续关键路口锚定、路段构建和更多道路语义扩展提供稳定底座

## 文档目标
本模块的最小正式文档面当前由以下文件共同组成：

- `architecture/*`
- [INTERFACE_CONTRACT.md](/E:/Work/RCSD_Topo_Poc/modules/t01_data_preprocess/INTERFACE_CONTRACT.md)
- [README.md](/E:/Work/RCSD_Topo_Poc/modules/t01_data_preprocess/README.md)

建议在后续正式激活为 repo 级模块后再进一步补充：

- repo 级模块登记
- 更正式的 review / release summary
