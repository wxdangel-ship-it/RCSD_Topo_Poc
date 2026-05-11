# P01 Arm Build

`p01_arm_build` 承载 P01 v1.0.0 的结构与 RoadNextRoad 还原能力：P01-A1 单源 Arm 构建、特殊转向识别、ArmMovement 与 trunk 修正；P01-A2 三源 Arm 配准与 `LogicalArmGroup`；P01-Final 生成最终 `frcsd_road_next_road.geojson`。

## 能力范围

- A1：读取 SWSD / RCSD / F-RCSD Node、Road 与可选 RoadNextRoad，按语义路口构建 InitialArm / FinalArm / final_arm_validation / corrected_final_arms。
- A1：用 `formway` bit7 / bit8 识别提前右转、提前左转，输出 `AdvanceRightTurnRelation`、trunk、ArmMovement、RoadMovementEvidence、ReceivingRoadRole 与 trunk correction。
- A2：读取 A1 run root，构建 ArmProfile、候选矩阵、RawArmAlignment、LogicalArmGroup、ArmBuildFeedback、source_extra 与配准审查产物。
- P01-Final：基于 SWSD / RCSD 源侧 ArmMovement 通行规则抽象、F-RCSD 道路角色投影、ArmSourceProfile、SourceArmPassRule 与 final generation decision，生成 `frcsd_road_next_road.geojson`；精确源 Road 映射保留为审计 / 置信增强证据。
- 输出 JSON、GeoJSON、PNG、GPKG、summary、review index、audit 与 issue report。

## 边界

- P01-A3 正式跨源 Movement 空间、P01-B 禁行证据迁移与条件通行裁决不由本模块实现。
- 不使用 `grade / grade_2` 作为 P01 主规则。
- 不使用 RoadNextRoad `turnType / turntype` 判断 `movement_type`。
- 不把 F-RCSD Source + CRS 归一化 rounded exact 源 Road 映射作为 P01-Final 生成前提，也不通过空间接近替代该审计证据。
- 不把主干道路 / 平行支路只覆盖部分目标退出 Road 作为正常 partial 规则投影。
- 不提供 repo 官方 CLI；当前入口均为模块内 callable runner 或 dev helper。

## A1 / P01-Final 调用

```python
from rcsd_topo_poc.modules.p01_arm_build.runner import run_p01_arm_build_from_args
```

参数形态：

```text
--swsd-nodes
--swsd-roads
--rcsd-nodes
--rcsd-roads
--frcsd-nodes
--frcsd-roads
--junction-group <swsd>,<rcsd>,<frcsd>
--out-root
--run-id
--right-turn-formway-value
--swsd-road-next-road
--rcsd-road-next-road
--frcsd-road-next-road
```

`--right-turn-formway-value` 是 legacy 显式右转 / 渠化右转排除兼容参数；正式特殊转向识别使用 `formway` bit 运算。

## A2 调用

```python
from rcsd_topo_poc.modules.p01_arm_build.alignment_runner import run_p01_arm_alignment_from_args
```

参数形态：

```text
--arm-build-run-root <P01_A1_RUN_ROOT>
--out-root
--run-id
```

## 单路口文本证据包

文本证据包 helper 用于外部复现与内网 case 取证，不登记为正式 CLI。范围选择基于当前语义路口 Road 拓扑 BFS，不做简单空间裁剪。Node / Road GPKG 保留原始属性，并补齐 P01 所需规范字段；F-RCSD Road 的 `Source/source` 会随包保留。可选随包带入 SWSD `RoadNodeRoad` / `RoadNextRoad` 与 RCSD `RoadNextRoad`。

打包：

```bash
.venv/bin/python -c "import sys; from rcsd_topo_poc.modules.p01_arm_build.text_bundle import run_p01_export_text_bundle_from_args as run; raise SystemExit(run(sys.argv[1:]))" --swsd-nodes <SWSD_NODES> --swsd-roads <SWSD_ROADS> --rcsd-nodes <RCSD_NODES> --rcsd-roads <RCSD_ROADS> --frcsd-nodes <FRCSD_NODES> --frcsd-roads <FRCSD_ROADS> --swsd-road-node-road <SWSD_RoadNodeRoad.json> --rcsd-road-next-road <RCSD_RoadNextRoad.geojson> --junction-group <SWSD_ID>,<RCSD_ID>,<FRCSD_ID> --bfs-depth 2 --auto-fit --max-bfs-depth 8 --out-txt outputs/_work/p01_arm_build_bundle/p01_case_bundle.txt
```

解包：

```bash
.venv/bin/python -c "import sys; from rcsd_topo_poc.modules.p01_arm_build.text_bundle import run_p01_decode_text_bundle_from_args as run; raise SystemExit(run(sys.argv[1:]))" --bundle-txt outputs/_work/p01_arm_build_bundle/p01_case_bundle.txt --out-dir outputs/_work/p01_arm_build_bundle/decoded
```

## 单 Case 全量执行 helper

`modules/p01_arm_build/dev_helpers/run_p01_case_full.sh` 是模块内 dev helper，不登记为正式 CLI。它可直接消费已解包 case 目录，也可先解包文本证据包后立即执行 A1 / P01-Final。

```bash
CASE_ROOT=outputs/_work/p01_arm_build_bundle/decoded \
JUNCTION_GROUP=1019789,R5392965095466552,F1019789 \
OUT_ROOT=outputs/_work/p01_case_full \
RUN_ID=p01_case_1019789 \
bash modules/p01_arm_build/dev_helpers/run_p01_case_full.sh
```

脚本会自动识别 `CASE_ROOT/SWSD/RoadNodeRoad.json`、`CASE_ROOT/SWSD/RoadNextRoad.json`、`CASE_ROOT/RCSD/RoadNextRoad.geojson` 与 `CASE_ROOT/FRCSD/RoadNextRoad.geojson`，也可用环境变量覆盖。

## 主要文档

- `INTERFACE_CONTRACT.md`
- `architecture/01-introduction-and-goals.md`
- `architecture/02-constraints.md`
- `architecture/03-context-and-scope.md`
- `architecture/04-solution-strategy.md`
- `architecture/05-building-block-view.md`
- `architecture/10-quality-requirements.md`
- `architecture/11-risks-and-technical-debt.md`
- `architecture/12-glossary.md`
