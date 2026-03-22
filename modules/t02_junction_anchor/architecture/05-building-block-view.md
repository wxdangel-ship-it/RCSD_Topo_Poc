# 05 构件视图

## 状态

- 当前状态：`模块级构件说明`
- 来源依据：`src/rcsd_topo_poc/modules/t02_junction_anchor/`

## 稳定阶段链

`CLI subcommand -> strict input read/validation -> junction extraction/dedupe -> junction group assembly -> DriveZone gate -> output write`

## 构件与职责

### 1. 入口与参数装配

- [cli.py](/mnt/e/Work/RCSD_Topo_Poc/src/rcsd_topo_poc/cli.py)
- 职责：注册 `t02-stage1-drivezone-gate` 子命令，承接路径、CRS override、输出目录与 run_id

### 2. 输入解析与兼容层

- [stage1_drivezone_gate.py](/mnt/e/Work/RCSD_Topo_Poc/src/rcsd_topo_poc/modules/t02_junction_anchor/stage1_drivezone_gate.py)
- 职责：
  - 读取 GeoJSON / Shapefile
  - 严格解析 CRS
  - 校验必需字段
  - 将几何统一到 `EPSG:3857`

### 3. 主流水线

- [stage1_drivezone_gate.py](/mnt/e/Work/RCSD_Topo_Poc/src/rcsd_topo_poc/modules/t02_junction_anchor/stage1_drivezone_gate.py)
- 职责：
  - 解析 `pair_nodes / junc_nodes`
  - 单 `segment` 去重
  - junction group 组装
  - 代表 node 决定
  - DriveZone gate
  - `segment.has_evd` 与 summary 计算

### 4. 报告与诊断

- [stage1_drivezone_gate.py](/mnt/e/Work/RCSD_Topo_Poc/src/rcsd_topo_poc/modules/t02_junction_anchor/stage1_drivezone_gate.py)
- [test_stage1_drivezone_gate.py](/mnt/e/Work/RCSD_Topo_Poc/tests/modules/t02_junction_anchor/test_stage1_drivezone_gate.py)
- [test_smoke_t02_stage1.py](/mnt/e/Work/RCSD_Topo_Poc/tests/test_smoke_t02_stage1.py)
- 职责：
  - 输出 `summary / audit / log`
  - 保证关键失败场景有测试覆盖与 smoke 可复现
