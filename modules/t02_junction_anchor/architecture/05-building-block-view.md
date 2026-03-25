# 05 构件视图

## 状态

- 当前状态：`模块级构件说明`
- 来源依据：`src/rcsd_topo_poc/modules/t02_junction_anchor/`

## 稳定阶段链

`CLI subcommand -> strict input read/validation -> junction extraction/dedupe -> junction group assembly -> stage1 gate -> stage2 anchor recognition -> stage3 virtual intersection anchoring -> text bundle support -> output write`

## 构件与职责

### 1. 入口与参数装配

- [cli.py](/mnt/e/Work/RCSD_Topo_Poc/src/rcsd_topo_poc/cli.py)
- 职责：注册并装配：
  - `t02-stage1-drivezone-gate`
  - `t02-stage2-anchor-recognition`
  - `t02-virtual-intersection-poc`
  - `t02-export-text-bundle`
  - `t02-decode-text-bundle`
  - 承接路径、CRS override、输出目录、run_id 与 stage3 `input-mode / max-cases / workers`

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

### 4. Stage2 锚定识别

- [stage2_anchor_recognition.py](/mnt/e/Work/RCSD_Topo_Poc/src/rcsd_topo_poc/modules/t02_junction_anchor/stage2_anchor_recognition.py)
- 职责：
  - 读取 `RCSDIntersection`
  - 对 `has_evd = yes` 的组做 `is_anchor` 判定
  - 输出 `node_error_1 / node_error_2`
  - 产出 stage2 summary、audit、perf

### 5. Stage3 虚拟路口锚定

- [virtual_intersection_poc.py](/mnt/e/Work/RCSD_Topo_Poc/src/rcsd_topo_poc/modules/t02_junction_anchor/virtual_intersection_poc.py)
- [virtual_intersection_full_input_poc.py](/mnt/e/Work/RCSD_Topo_Poc/src/rcsd_topo_poc/modules/t02_junction_anchor/virtual_intersection_full_input_poc.py)
- 职责：
  - 基于 `nodes / roads / DriveZone / RCSDRoad / RCSDNode` 构造局部 patch
  - 计算分支证据、RC association 与 `polygon-support`
  - 生成单 case 与 full-input 批次级的虚拟路口面、状态、风险、审计与 debug render
  - `virtual_intersection_poc.py` 当前同时承载输入读取、support 选择、校验、render 与状态输出，是已确认的结构债

### 6. 文本证据包支撑

- [text_bundle.py](/mnt/e/Work/RCSD_Topo_Poc/src/rcsd_topo_poc/modules/t02_junction_anchor/text_bundle.py)
- 职责：
  - 导出单 `mainnodeid` 文本证据包
  - 校验体积上限与 checksum
  - 恢复等价目录结构，服务 stage3 复核与外网复现

### 7. 报告与诊断

- [stage1_drivezone_gate.py](/mnt/e/Work/RCSD_Topo_Poc/src/rcsd_topo_poc/modules/t02_junction_anchor/stage1_drivezone_gate.py)
- [stage2_anchor_recognition.py](/mnt/e/Work/RCSD_Topo_Poc/src/rcsd_topo_poc/modules/t02_junction_anchor/stage2_anchor_recognition.py)
- [virtual_intersection_poc.py](/mnt/e/Work/RCSD_Topo_Poc/src/rcsd_topo_poc/modules/t02_junction_anchor/virtual_intersection_poc.py)
- [virtual_intersection_full_input_poc.py](/mnt/e/Work/RCSD_Topo_Poc/src/rcsd_topo_poc/modules/t02_junction_anchor/virtual_intersection_full_input_poc.py)
- [test_stage1_drivezone_gate.py](/mnt/e/Work/RCSD_Topo_Poc/tests/modules/t02_junction_anchor/test_stage1_drivezone_gate.py)
- [test_stage2_anchor_recognition.py](/mnt/e/Work/RCSD_Topo_Poc/tests/modules/t02_junction_anchor/test_stage2_anchor_recognition.py)
- [test_virtual_intersection_poc.py](/mnt/e/Work/RCSD_Topo_Poc/tests/modules/t02_junction_anchor/test_virtual_intersection_poc.py)
- [test_virtual_intersection_full_input_poc.py](/mnt/e/Work/RCSD_Topo_Poc/tests/modules/t02_junction_anchor/test_virtual_intersection_full_input_poc.py)
- [test_text_bundle.py](/mnt/e/Work/RCSD_Topo_Poc/tests/modules/t02_junction_anchor/test_text_bundle.py)
- [test_smoke_t02_stage1.py](/mnt/e/Work/RCSD_Topo_Poc/tests/test_smoke_t02_stage1.py)
- [test_smoke_t02_virtual_intersection_poc.py](/mnt/e/Work/RCSD_Topo_Poc/tests/test_smoke_t02_virtual_intersection_poc.py)
- [test_smoke_t02_virtual_intersection_full_input_poc.py](/mnt/e/Work/RCSD_Topo_Poc/tests/test_smoke_t02_virtual_intersection_full_input_poc.py)
- 职责：
  - 输出 `summary / audit / log / perf`
  - 保证关键失败场景、support 约束、full-input 汇总与 bundle roundtrip 有测试覆盖
  - 保证最小 smoke 可复现
