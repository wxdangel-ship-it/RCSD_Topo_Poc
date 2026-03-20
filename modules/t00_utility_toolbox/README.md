# T00 Utility Toolbox

## 模块简介

`T00` 是 `RCSD_Topo_Poc` 的 Utility Toolbox / 工具集合模块，用于承接项目内部的数据整理、实验准备、辅助检查、问题排查和数据分析类工具。

## 定位与作用

- `T00` 不是 Skill
- `T00` 不是业务生产模块
- `T00` 不直接产出业务要素
- `T00` 只为项目内部辅助工具提供统一落仓位置与治理入口

## 当前收录工具

当前只有一个工具：

- Tool1：Patch 数据整理脚本

一句话描述：基于全量 Patch 矢量目录初始化统一 Patch 目录骨架，并将源 Patch 文件归位到目标 `Vector/` 目录。

## 模块状态

当前已完成文档基线，并已提供 Tool1 内网固定执行脚本与对应 `src/` 实现。

`history/*` 当前未启用，待 Tool1 完成后按实际迭代需要补建。

## 与业务模块的关系

`T00` 只承担辅助支持角色，不承担后续地图要素生成逻辑，也不替代正式业务模块。

## 文档入口

- 规格基线：[`../../specs/t00-utility-toolbox/spec.md`](../../specs/t00-utility-toolbox/spec.md)
- 阶段计划：[`../../specs/t00-utility-toolbox/plan.md`](../../specs/t00-utility-toolbox/plan.md)
- 任务清单：[`../../specs/t00-utility-toolbox/tasks.md`](../../specs/t00-utility-toolbox/tasks.md)
- 接口契约：[`INTERFACE_CONTRACT.md`](INTERFACE_CONTRACT.md)
- Agent 约束：[`AGENTS.md`](AGENTS.md)
- 模块架构：[`architecture/01-introduction-and-goals.md`](architecture/01-introduction-and-goals.md)

## 运行入口

内网 WSL 环境固定执行方式：

```bash
python3 scripts/t00_tool1_patch_directory_bootstrap.py
```

脚本头部已集中定义默认源目录与目标根目录：

- `/mnt/d/TestData/POC_Data/数据整理/vectors`
- `/mnt/d/TestData/POC_Data/patch_all`
