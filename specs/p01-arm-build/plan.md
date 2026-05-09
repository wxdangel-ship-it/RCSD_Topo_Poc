# P01-A Arm 构建 Plan

## 1. Readiness / Preflight

已读取并确认：

- `AGENTS.md`
- `docs/doc-governance/README.md`
- `docs/repository-metadata/code-boundaries-and-entrypoints.md`
- `docs/repository-metadata/entrypoint-registry.md`
- `docs/repository-metadata/code-size-audit.md`
- 项目级源事实：`SPEC.md`、`docs/PROJECT_BRIEF.md`、`docs/architecture/*`、`docs/doc-governance/module-lifecycle.md`
- 模块模板：`modules/_template/*`
- 默认实现纪律：`.agents/skills/default-imp/SKILL.md`
- P01 v0.3.0 需求文档：`/mnt/e/_chatgpt_sync/RCSD_Topo_Poc/P01_1/RCSD_Topo_Poc__P01__REQUIREMENT.md`

Windows 路径 `E:\_chatgpt_sync\RCSD_Topo_Poc\P01_1\RCSD_Topo_Poc__P01__REQUIREMENT.md` 已按当前 bash / WSL 环境换算并确认存在。

## 2. Module Placement

- 模块文档：`modules/p01_arm_build/`
- 模块实现：`src/rcsd_topo_poc/modules/p01_arm_build/`
- 模块测试：`tests/modules/p01_arm_build/`
- SpecKit 工件：`specs/p01-arm-build/`

`P01` 是 POC 验证模块编号，目录结构与 T0X 模块一致。

## 3. Entry Strategy

本轮不新增：

- repo CLI 子命令
- `scripts/` 常驻脚本
- 模块 `__main__.py`
- 模块 `run.py`
- Makefile 目标

实现提供模块内可调用 runner：

```text
rcsd_topo_poc.modules.p01_arm_build.runner.run_p01_arm_build_from_args(argv)
```

该函数用于测试、开发验收和后续正式入口接入准备；当前不作为仓库正式执行入口登记。
P01-A1 正式特殊转向识别使用 `formway` bit 运算；`--right-turn-formway-value` 仅保留 legacy 显式右转 / 渠化右转排除兼容能力，未传入时不按几何或示例值排除 legacy 右转。

## 4. Implementation Slices

### Slice 1: Contracts and Docs

- 建立模块文档面与接口契约。
- 更新项目级登记，使 `p01_arm_build` 成为 Active POC validation module。
- 建立 SpecKit `spec.md / plan.md / tasks.md`。

### Slice 2: Input and Data Model

- 用 Fiona 读取 Node / Road 矢量层。
- 规范字段大小写。
- 保留原始属性摘要。
- 构建 Node / Road dataclass。
- 不引入新依赖。

### Slice 3: Semantic Junction, Seeds and Special Roads

- 按 `mainnodeid` 组装语义路口。
- 识别 internal roads。
- 识别 seed road role：`inbound / outbound / bidirectional`。
- 使用 bit 运算识别 `formway bit7` 提前右转和 `formway bit8` 提前左转。
- bit7 road 从 seed / member / connector / trunk 中排除，后续生成 `AdvanceRightTurnRelation` 或 issue。
- bit7 候选范围覆盖当前语义路口 member node 直接连接 road，以及非特殊 inbound / bidirectional seed 外侧节点相邻 bit7 road。
- 连续 bit7 road 链归并为一条 Arm 级 relation，road segment 级数量与 relation 数量分开统计。
- bit8 road 可进入 Arm member，但从 trunk 中排除。
- bit8 只在进入 Arm member 后计入当前路口提前左转统计。
- legacy `--right-turn-formway-value` 仅用于非 bit7 的显式右转 / 渠化右转排除；字段缺失或不可解析输出 audit。

### Slice 4: Trace and InitialArm

- 从每条 seed road 沿外侧拓扑追溯。
- 支持 `simple_through`、`semantic_boundary`、`dead_end`、`patch_boundary`、`loop_to_current_junction`。
- 追溯停止采用 kind-aware 口径：`kind != 4` 原则继续，`kind = 2048` 按 T 型横向主通道 through / 竖向侧支 terminal，`kind = 4` 先判别是否具备 T 型特征，不具备则作为语义边界停止。
- T 型主通道 / 侧向判断必须结合当前追溯方向和 continuation 角度；不能稳定确认时输出 `ambiguous_boundary` / `t_junction_uncertain`，不静默 through。
- 按终端归并 InitialArm。
- FinalArm 默认做占位映射；当 LocalArmCandidate 完整覆盖 InitialArm 且存在碎片化时，采用局部趋势兜底聚合。
- 为 InitialArm / FinalArm 聚合特殊转向字段、trunk 字段和提前右转 relation 字段。
- 识别 trunk：唯一最小闭环为 `complete_min_loop`；无完整闭环但有主链或非特殊 local seed 时为 `partial`；无主链为 `none`；多条等价闭环为 `ambiguous`。

### Slice 5: Outputs and Review

- 写 JSON 输出。
- 写 `advance_right_turn_relations.json`。
- 写 `LocalArmCandidate` 审计候选输出；该候选服务目视与问题归纳，并可在完整覆盖时参与 FinalArm 兜底聚合。
- 写 dataset review GPKG，包含提前左转、提前右转、trunk、relation 和特殊 issue 图层。
- 写 dataset review PNG，标注 `TRUNK`、`AdvL`、`R7` relation 与未解析状态。
- 写 compare PNG / compare GPKG。
- 写 summary 与 review index。

### Slice 6: Checks and Tests

- 单元测试覆盖语义路口、bit7 / bit8、legacy 右转排除、trunk、relation、禁止 Grade、trace 连续、issue 分类。
- synthetic fixture 生成三套数据并跑一组 / 多组输入。
- 验证输出目录结构、PNG/GPKG 存在性、summary/review index 内容。

## 5. File Size Control

- 所有新增 `.py` 文件写入前按 `AGENTS.md §3` 做当前字节数自检。
- 单文件目标控制在 50 KB 以下，硬上限 100 KB。
- 不触碰当前已超阈值文件。
- 本轮不预计修改 `docs/repository-metadata/code-size-audit.md`，除非新增或修改文件触发该表内容变化。

## 6. Testing Strategy

- `py_compile`：覆盖 `src/rcsd_topo_poc/modules/p01_arm_build/*.py`。
- `pytest tests/modules/p01_arm_build`。
- synthetic single group。
- synthetic multi group。
- 输出结构检查。
- PNG / GPKG 存在性检查。
- 禁止 Grade 源码扫描。
- 右转排除审计检查。

## 7. QA Strategy

- CRS：读取输入 CRS 并写入 preflight；输出 GPKG 沿用输入 CRS，PNG 使用同一数据集 bounds 做可视化坐标转换。
- 拓扑一致性：trace 每步必须通过共享语义节点组连接；不做 silent fix。
- 几何语义：几何仅用于 review 与低优先级定位，不作为 Arm 主规则或右转反推依据。
- 局部候选：只使用当前语义路口 seed 的出入口局部趋势做审计候选，不把样例目标路口 ID 固化为策略。
- 审计可追溯：preflight、case_input、trace、decision、issue、summary 均记录输入路径、参数和 run id。
- 性能可验证：summary 写入 group/dataset 计数与运行耗时。

## 8. Known Boundaries

- 真实数据路径尚未作为本轮命令输入提供；真实数据运行验证待用户提供。
- 当前实现对 T 型主通道采用可审计方向裁决：可唯一确认横向主通道时继续，不能稳定确认时停止并审计，不静默穿越。
- 当前不做 Arm 配准，因此 compare 只展示三套数据同视野审查与统计差异。
- `LocalArmCandidate` 用于解释 trace 碎片化风险；当其完整覆盖 InitialArm 时，正式 `FinalArm` 可采用兜底聚合。

## 9. P01-A1 / P01-Final v0.5.0 RoadNextRoad-aware ArmMovement Plan

- 在现有 `p01_arm_build` 内修订 A1，不新建业务模块，不新增正式 CLI。
- 内部 helper：`road_next_road.py` 读取 SWSD / RCSD / F-RCSD JSON / GeoJSON，`movement.py` 生成 RoadMovementEvidence、ArmMovement、receiving role 和 corrected trunk。
- 新增内部 helper：`final_road_next_road.py` 承载 P01-Final Source mapping、source policy、same-source inheritance、cross-source primary source、RCSD -> SWSD fallback、final GeoJSON / audit / issue / review。
- runner 增加三个可选 RoadNextRoad 输入；未提供时输出 no-op correction，既有 A1 行为不回退；P01-Final 若缺少源 evidence 则不生成对应 final RoadNextRoad 并审计。
- review 输出增加 movement/evidence/receiving/corrected trunk 图层；summary / review index 增加 movement 与 correction 统计。
- FRCSD 输出增加 final RoadNextRoad GeoJSON、source map、source policy、final audit、issue report、review GPKG / PNG。
- 文件体量策略：避免继续扩张 `topology.py`，新增 helper 控制在 50 KB 以下。
- 测试策略：新增 SWSD JSON、RCSD/FRCSD GeoJSON、全量 movement、turnType 禁用、allowed evidence 投影、advance-left-only trunk correction、stable straight 限制、Source + geometry exact mapping、same-source inheritance、cross-source primary source、RCSD -> SWSD fallback、ambiguous/missing issue、final GeoJSON schema、duplicate 防护、GPKG/PNG/summary 字段检查。
