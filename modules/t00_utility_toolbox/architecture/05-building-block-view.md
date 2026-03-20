# 05 构件视图

## 状态

- 当前状态：`T00 构件视图（Tool1 / Tool2 / Tool3 baseline）`
- 来源依据：`specs/t00-utility-toolbox/*` 与 `modules/t00_utility_toolbox/*`

## 稳定阶段链

`Patch 矢量目录 -> Tool1 patch_all 骨架 -> Tool2 DriveZone 全局输出 / Tool3 Intersection 全局输出`

## 构件与职责

### 1. 规格与计划构件

- `../../specs/t00-utility-toolbox/spec.md`
- 职责：固化 T00 定位、Tool1 / Tool2 / Tool3 需求基线、非范围与扩展门禁

### 2. 模块契约构件

- `INTERFACE_CONTRACT.md`
- 职责：固化 Tool1 / Tool2 / Tool3 的输入、输出、覆盖、跳过与摘要语义

### 3. 执行约束构件

- `AGENTS.md`
- 职责：约束后续 Agent / CodeX 的工作方式，防止范围外扩

### 4. 实现构件

- `../../../src/rcsd_topo_poc/modules/t00_utility_toolbox/patch_directory_bootstrap.py`
- `../../../src/rcsd_topo_poc/modules/t00_utility_toolbox/drivezone_merge.py`
- `../../../src/rcsd_topo_poc/modules/t00_utility_toolbox/intersection_merge.py`
- `../../../src/rcsd_topo_poc/modules/t00_utility_toolbox/common.py`
- `../../../scripts/t00_tool1_patch_directory_bootstrap.py`
- `../../../scripts/t00_tool2_drivezone_merge.py`
- `../../../scripts/t00_tool3_intersection_merge.py`
- 职责：承载 Tool1 / Tool2 / Tool3 的内网固定执行入口与共享底层能力

### 5. 运行产物构件

- `patch_all` 根目录下的 `DriveZone.geojson`、`Intersection.geojson`、日志与摘要
- 职责：承载 T00 的正式输出与失败诊断信息
