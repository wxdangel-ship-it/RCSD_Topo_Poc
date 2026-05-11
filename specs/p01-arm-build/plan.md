# P01 v1.0.0 Implementation Plan

## 1. 模块布局

P01 由现有 `p01_arm_build` 模块承载，不建立额外业务模块。

- 文档：`modules/p01_arm_build/`
- 实现：`src/rcsd_topo_poc/modules/p01_arm_build/`
- 测试：`tests/modules/p01_arm_build/`
- SpecKit：`specs/p01-arm-build/`

仓库不提供 P01 repo 官方 CLI、`scripts/` 常驻命令、Makefile 目标、模块 `__main__.py` 或模块 `run.py`。模块内 callable runner 是稳定调用面；dev helper 保持取证和开发验收属性。

## 2. A1 架构

A1 使用以下内部构建块：

- `io.py`：读取 Node / Road、写出 JSON / CSV / GPKG、生成 preflight。
- `topology.py`：语义路口、seed、trace、through decision、InitialArm / FinalArm。
- `final_arm_validation.py`：FinalArm 兜底聚合后的 relaxed reverse / supplemental trace validation、validation metrics 与 issue。
- `special_roads.py`：`formway` bit7 / bit8、AdvanceRightTurnRelation 与特殊转向 issue。
- `trunk.py`：trunk road ids、trunk 状态与非 trunk member roads。
- `road_next_road.py`：SWSD / RCSD / F-RCSD RoadNextRoad 读取与归一化。
- `movement.py`：RoadMovementEvidence、ArmMovement、ReceivingRoadRole 与 corrected trunk。
- `review.py`：A1 review PNG、compare PNG 与 review GPKG。
- `runner.py`：A1 / P01-Final 批处理与输出编排。

## 3. A2 架构

A2 使用 A1 run root 作为主输入：

- `alignment_io.py` 读取 A1 输出与原始几何。
- `alignment.py` 构建 ArmProfile、candidate edge、evidence graph、LogicalArmGroup、RawArmAlignment、ArmBuildFeedback 与 source_extra。
- `alignment_review.py` 输出配准 PNG / GPKG。
- `alignment_runner.py` 编排 A2 summary 与 review index。

A2 不重新实现 A1，不静默修复 A1 结果。A2 反馈通过 ArmBuildFeedback 回传。

## 4. P01-Final 架构

`final_road_next_road.py` 承载 final generation：

- 读取 F-RCSD Road `Source`。
- 输出 ArmSourceProfile，表达 F-RCSD Arm 内 Road 级 Source 分布与混源风险。
- 从 SWSD / RCSD RoadNextRoad、ArmMovement、进入道路角色与目标 Arm 退出道路集合抽象 SourceArmPassRule。
- 按同源优先、混源 SWSD 结构匹配、RCSD 结构匹配、SWSD basic rule 兜底选择规则源。
- 精确源 Road mapping 仅作为 audit / confidence evidence；匹配缺失不得直接阻断规则级生成。
- `full_allowed` 投影到目标 Arm 全部退出 Road；主干 / 平行支路部分目标覆盖输出 `data_error_partial_target_coverage`，advance-left 与 uturn 特例保留。
- 生成 `frcsd_road_next_road.geojson`、ArmSourceProfile、SourceArmPassRule、final generation decision、source map、兼容 source policy、audit、issue 与 final review 图层。

## 5. turntype 输出

`movement_type` 不使用输入 RoadNextRoad `turnType / turntype`。Final GeoJSON 的 `turntype` 仅作为输出编码，由 `movement_type` 映射：

- `straight -> 1`
- `left -> 2`
- `right -> 3`
- `uturn -> 4`
- `unknown -> 0`

该映射按模块契约复用。真实 RCSD 规范如提供不同编码，应以规范更新任务同步修改契约、实现与测试。

## 6. 文件体量策略

- `topology.py` 不承载 RoadNextRoad、movement 或 final generation 逻辑。
- RoadNextRoad、movement、special roads、trunk、final generation 分别由独立 helper 承载。
- 对 `.py` / `.sh` 写入前执行字节数自检，确保单文件不越过 100 KB。

## 7. 测试策略

- 静态检查：`py_compile`。
- 治理扫描：`grade / grade_2` 不进入 P01 主规则；`turnType / turntype` 不进入 `movement_type` 判定函数。
- A1 synthetic：语义路口、trace、kind-aware through、bit7 / bit8、AdvanceRightTurnRelation、FinalArm validation、trunk、RoadNextRoad-aware movement、ReceivingRoadRole、corrected trunk。
- A2 synthetic：stable、source_missing、source_partial、over_split、over_merged、conflict / uncertain、多 group。
- P01-Final synthetic：规则级 full_allowed 投影到全部目标退出 Road、主干 / 平行支路部分覆盖报错、advance-left 与 uturn 特例、混源规则源选择、RCSD 目标 Arm 缺失 fallback、精确源 Road 匹配缺失仍可规则生成、Source + CRS-normalized rounded exact mapping 审计、missing / ambiguous mapping、parallel_branch alignment、right-turn carrier issue、final GeoJSON schema、duplicate 防护。
- 输出检查：JSON / GeoJSON / PNG / GPKG / summary / review index / audit / issue report。

## 8. 真实 case QA

真实 case QA 使用用户提供或内网可访问的 Node / Road / RoadNextRoad 路径运行 A1 / P01-Final，并检查：

- `frcsd_road_next_road.geojson`
- `frcsd_road_next_road_audit.json`
- `frcsd_road_next_road_issue_report.json`
- summary / review index
- review PNG / GPKG

无法访问真实内网数据时，交付回报必须明确真实 case 未由 Agent 本地验证，并提供内网执行命令边界。
