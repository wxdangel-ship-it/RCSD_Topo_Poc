# P01-A Arm 构建 Tasks

> 每个源码 / 脚本文件写入前必须先确认当前字节数。命中 `AGENTS.md §1` 任一硬停机触发时立即停机。

## Phase 0: Requirement and Source Facts

- [x] 换算并确认用户 Windows 需求路径为 WSL 路径。
- [x] 阅读 `AGENTS.md`。
- [x] 阅读 `docs/doc-governance/README.md`。
- [x] 阅读 `docs/repository-metadata/code-boundaries-and-entrypoints.md`。
- [x] 阅读用户提供的 P01-A 需求文档。
- [x] 阅读项目级源事实与模块生命周期。
- [x] 确认当前不存在 P01 模块。
- [x] 确认本轮不新增正式 CLI / scripts / run.py / __main__.py。

## Phase 1: Specify

- [x] 建立 `specs/p01-arm-build/spec.md`。
- [x] 限定范围只包含 P01-A。
- [x] 写明输入、输出、非范围、验收标准。
- [x] 明确禁止 Grade、几何右转反推、Movement、P01-B。

## Phase 2: Plan

- [x] 建立 `specs/p01-arm-build/plan.md`。
- [x] 明确模块放置位置。
- [x] 明确新增模块与项目级登记。
- [x] 明确不新增正式 CLI，使用模块内可调用 runner。
- [x] 明确文件体量控制。
- [x] 明确测试、QA 与目视审查策略。

## Phase 3: Tasks

- [x] 建立 `specs/p01-arm-build/tasks.md`。
- [x] 拆分输入读取任务。
- [x] 拆分语义路口组装任务。
- [x] 拆分右转专用道排除任务。
- [x] 拆分 Arm 追溯任务。
- [x] 拆分 through 判断任务。
- [x] 拆分 InitialArm / FinalArm / Trace / Decision / Issue 输出任务。
- [x] 拆分 PNG / GPKG / summary / index 输出任务。
- [x] 拆分单元、集成、目视审查样例、回归和 QA 任务。

## Phase 4: Implement

- [x] 前置自检所有待写入 `.py` 文件当前字节数。
- [x] 新增 `models.py`：数据输入、业务对象与 summary dataclass。
- [x] 新增 `io.py`：Fiona 读取、JSON/CSV/GPKG 写入。
- [x] 新增 `topology.py`：语义路口、seed、trace、arm 构建。
- [x] 新增 `review.py`：PNG 渲染和 compare 渲染。
- [x] 新增 `runner.py`：参数解析、批处理、summary/review index。
- [x] 新增 `__init__.py`。
- [x] 新增 `LocalArmCandidate` 审计输出，用当前语义路口 seed 局部趋势辅助识别 trace 过度切碎。
- [x] `FinalArm` 默认保持 `InitialArm`，并在 `LocalArmCandidate` 完整覆盖碎片化 InitialArm 时启用兜底聚合。
- [x] 实现 kind-aware 追溯停止口径：`kind != 4` 原则继续，`kind = 2048` 按 T 型横/竖裁决，`kind = 4` 先评估 T 型特征。
- [x] 不修改 T01 / T02 / T03 / T04 既有业务语义。
- [x] 不使用 `grade / grade_2` 参与 Arm 构建。
- [x] 不通过几何形态反推右转专用道。
- [x] 不实现 Arm 配准、Movement、P01-B。
- [x] 输出必须可审计。

## Phase 5: Tests and QA

- [x] 新增 synthetic fixture helper。
- [x] 单元测试：语义路口组装。
- [x] 单元测试：右转排除与审计。
- [x] 单元测试：trace 连续性和 through 状态。
- [x] 单元测试：LocalArmCandidate 输出、右转排除后不进入候选、FinalArm 兜底聚合。
- [x] 单元测试：kind-aware T 型 through / side terminal / semantic boundary。
- [x] 单元测试：禁止 Grade 源码扫描。
- [x] 集成测试：至少一组 synthetic case。
- [x] 集成测试：至少一组多 junction-group 输入。
- [x] 检查输出目录结构。
- [x] 检查 summary / review index。
- [x] 检查 PNG / GPKG 产物存在性。
- [x] 检查右转专用道排除审计。
- [x] 运行 py_compile。
- [x] 运行 `pytest tests/modules/p01_arm_build`。
- [x] 说明真实数据未验证或记录真实数据验证结果。

## Phase 6: P01-A1 v0.3.0 Special Turn and Trunk Revision

- [x] 读取 P01 v0.3.0 需求文档并确认本轮不是新增 A1.1，也不是 A2。
- [x] 更新 A1 spec / plan / tasks 与模块契约。
- [x] 保持 A1 callable runner 参数形态不变，不新增正式 CLI。
- [x] 保留 `--right-turn-formway-value` 作为 legacy 兼容排除参数。
- [x] 实现 `formway` bit7 / bit8 位运算解析。
- [x] 审计 `formway_missing` 与 `formway_unparseable`。
- [x] 构建 `SpecialRoadFlagIndex`。
- [x] 提前左转 road 保留在 Arm member 中并从 trunk 排除。
- [x] 提前右转 road 从 seed / member / connector / trunk 排除。
- [x] 扩展提前右转识别到非特殊 inbound / bidirectional seed 外侧节点相邻 bit7 road。
- [x] 连续 bit7 road 链归并为一条 Arm 级提前右转 relation。
- [x] 仅将进入 Arm member 的 bit8 road 计入当前路口提前左转。
- [x] 输出 `advance_right_turn_relations.json`。
- [x] 每条当前路口 bit7 road 生成 relation 或明确 issue。
- [x] 实现 `trunk_road_ids / trunk_status / trunk_reason / non_trunk_member_road_ids`。
- [x] 无完整闭环但存在非特殊 local seed 时输出 `trunk_status = partial`。
- [x] 增强 `JunctionContext / InitialArm / FinalArm / ArmTrace / IssueReport`。
- [x] FinalArm local fallback 聚合来源 InitialArm 的特殊转向、trunk 与 relation 字段。
- [x] 增强 review GPKG 特殊转向、trunk、relation、issue 图层。
- [x] 增强 review PNG 的 `TRUNK / AdvL / R7` 标注。
- [x] 增强 summary / review index 特殊转向与 trunk 统计。
- [x] 新增 bit7 / bit8 / seed 外侧提前右转 / 连续 bit7 链归并 / relation / trunk fallback / formway audit 测试。
- [x] 回归 A1 既有测试。

## Phase 7: P01-A1 v0.4.0 RoadNextRoad-aware ArmMovement and Trunk Correction

- [x] 读取 P01 v0.4.0 需求文档并确认本轮仍是 A1 修订。
- [x] 更新 A1 spec / plan / tasks 与模块契约。
- [x] 保持 A1 callable runner，不新增正式 CLI。
- [x] 新增 `--swsd-road-next-road / --rcsd-road-next-road` 可选参数；F-RCSD RoadNextRoad 不作为 A1 输入。
- [x] 实现 SWSD JSON 与 RCSD GeoJSON RoadNextRoad 读取。
- [x] 归一化 `RoadMovementEvidence` 并保留 raw turn type 审计。
- [x] 生成全量 `from_final_arm x to_final_arm` ArmMovement。
- [x] 不使用 `turnType / turntype` 判定 movement_type。
- [x] 将 RoadNextRoad allowed evidence 投影到 ArmMovement。
- [x] 统计 receiving road role。
- [x] 识别 advance-left-only receiving road。
- [x] 实现 corrected trunk 与 `corrected_final_arms.json`。
- [x] 增强 JSON / GPKG / PNG / summary / review index 输出。
- [x] 新增 synthetic 测试覆盖 RoadNextRoad 读取、movement、trunk correction。
- [x] 回归 A1 / A2 既有测试。

## Phase 8: P01-A1 / P01-Final v0.5.0 RoadNextRoad-aware final generation

- [x] 修订基准需求文档执行范围，授权 P01-Final 正式编码。
- [x] 更新 A1 / P01-Final spec / plan / tasks 与模块契约。
- [x] 恢复 `--frcsd-road-next-road` 可选输入用于 A1 FRCSD evidence 审计。
- [x] 增强 ArmMovement stable straight 审计字段。
- [x] 限制 trunk correction 只使用 stable straight receiving evidence。
- [x] 新增 F-RCSD Source 字段读取与校验。
- [x] 新增 F-RCSD Source + geometry exact source road mapping。
- [x] 新增 SourceMovementPolicy 构建。
- [x] 新增 same-source direct inheritance。
- [x] 新增 cross-source primary source generation。
- [x] 新增 RCSD -> SWSD fallback。
- [x] 新增 final `frcsd_road_next_road.geojson` 输出。
- [x] 新增 final audit / issue / source map / source policy 输出。
- [x] 新增 final review GPKG / PNG 输出。
- [x] 新增 final generation metrics 到 summary / review index。
- [x] 新增 synthetic 测试覆盖 source mapping、same-source、cross-source、fallback、ambiguous issue。
