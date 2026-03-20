# T00 Utility Toolbox

## 模块简介

`T00` 是 `RCSD_Topo_Poc` 的 Utility Toolbox / 工具集合模块，用于承接项目内部的数据整理、实验准备、辅助检查、问题排查、全局辅助图层预处理和数据分析类工具。

## 定位与作用

- `T00` 不是 Skill
- `T00` 不是业务生产模块
- `T00` 不直接产出业务要素
- `T00` 只为项目内部辅助工具提供统一落仓位置与治理入口

## 当前收录工具

当前包含三个工具：

- Tool1：Patch 数据整理脚本
- Tool2：全量 DriveZone 的预处理与汇总输出
- Tool3：全量 Intersection 的预处理与汇总

一句话描述：

- Tool1：基于全量 Patch 矢量目录初始化统一 Patch 目录骨架，并将源 Patch 文件归位到目标 `Vector/` 目录
- Tool2：对所有 Patch 的 `DriveZone.geojson` 做 3857 预处理、单 Patch 合并，并将各 Patch 结果汇总到全局 `DriveZone.geojson`
- Tool3：对所有 Patch 的 `Intersection.geojson` 做 3857 预处理和逐要素简化，保留属性并新增 `patchid` 后汇总为全局 `Intersection.geojson`

## 模块状态

当前已完成 Tool1，并在本轮补入 Tool2 / Tool3 的实现入口与最小必要文档更新。

`history/*` 当前未启用，待后续真实迭代需要时再补。

## 与业务模块的关系

`T00` 只承担辅助支持角色，不承担后续地图要素生成逻辑，也不替代正式业务模块。

## 文档入口

- 规格基线：[`../../specs/t00-utility-toolbox/spec.md`](../../specs/t00-utility-toolbox/spec.md)
- 阶段计划：[`../../specs/t00-utility-toolbox/plan.md`](../../specs/t00-utility-toolbox/plan.md)
- 任务清单：[`../../specs/t00-utility-toolbox/tasks.md`](../../specs/t00-utility-toolbox/tasks.md)
- 接口契约：[`INTERFACE_CONTRACT.md`](INTERFACE_CONTRACT.md)
- Agent 约束：[`AGENTS.md`](AGENTS.md)
- 模块架构：[`architecture/01-introduction-and-goals.md`](architecture/01-introduction-and-goals.md)

## 统一规则摘要

- Patch 输入目录统一使用 `Vector/`
- 所有几何处理统一在 `EPSG:3857`
- “压缩”统一解释为拓扑保持的几何简化
- 覆盖口径统一为删除旧输出再重建
- 命令行执行过程中必须提供阶段级和 Patch 级进度输出

## 运行入口

内网 WSL 环境固定执行方式：

```bash
python3 scripts/t00_tool1_patch_directory_bootstrap.py
python3 scripts/t00_tool2_drivezone_merge.py
python3 scripts/t00_tool3_intersection_merge.py
```

脚本头部已集中定义默认数据根和关键参数：

- `/mnt/d/TestData/POC_Data/patch_all`
- Tool2 默认 `+5m / -5m` 与保守简化容差
- Tool3 默认保守简化容差
