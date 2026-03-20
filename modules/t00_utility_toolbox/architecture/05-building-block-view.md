# 05 构件视图

## 状态

- 当前状态：`T00 构件视图（Tool1 fixed-script baseline）`
- 来源依据：`specs/t00-utility-toolbox/*` 与 `modules/t00_utility_toolbox/*`

## 稳定阶段链

`源 Patch 矢量目录 -> Patch 目录骨架初始化 -> Vector 数据归位 -> 目标根目录摘要与日志`

## 构件与职责

### 1. 规格与计划构件

- `../../specs/t00-utility-toolbox/spec.md`
- 职责：固化 T00 定位、Tool1 需求基线、非范围与编码门禁

### 2. 模块契约构件

- `INTERFACE_CONTRACT.md`
- 职责：固化 Tool1 的输入、输出、覆盖、异常与摘要语义

### 3. 执行约束构件

- `AGENTS.md`
- 职责：约束后续 Agent / CodeX 的工作方式，防止范围外扩

### 4. 实现构件

- `../../../src/rcsd_topo_poc/modules/t00_utility_toolbox/patch_directory_bootstrap.py`
- `../../../scripts/t00_tool1_patch_directory_bootstrap.py`
- 职责：承载 Tool1 的目录骨架初始化、`Vector/` 数据归位、Patch 级失败汇总与内网固定执行入口

### 5. 运行产物构件

- 目标根目录下的 Patch 骨架、日志与摘要
- 职责：承载 Tool1 的整理结果与失败诊断信息
