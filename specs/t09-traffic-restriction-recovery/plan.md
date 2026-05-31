# T09 Traffic Restriction Recovery Draft Plan

## Scope

本计划只覆盖 T09 SpecKit 草案阶段。当前用户授权的是创建 `specs/t09-traffic-restriction-recovery/` 草案，不授权：

- 修改项目级源事实。
- 新增 T09 模块目录。
- 写源码、测试或脚本。
- 新增或登记执行入口。

若后续授权实现，第一轮实现范围建议限定为 Step1：SWSD `kind_2 = 4` 语义路口的 Arm 与 ArmMovement 构建。当前不定义 F-RCSD RoadNextRoad 输出，也不定义最终 restriction 表输出。

## Draft Files

本轮只新增：

- `specs/t09-traffic-restriction-recovery/spec.md`
- `specs/t09-traffic-restriction-recovery/plan.md`
- `specs/t09-traffic-restriction-recovery/tasks.md`

这些文件是 SpecKit 变更工件，不替代项目级或模块级 source-of-truth。

## Future Source Fact Updates

进入实现前，需要由用户单独授权同步以下 source facts：

- `SPEC.md`
- `docs/PROJECT_BRIEF.md`
- `docs/doc-governance/module-lifecycle.md`
- `docs/doc-governance/current-module-inventory.md`
- `docs/doc-governance/current-doc-inventory.md`
- `docs/doc-governance/module-doc-status.csv`
- `docs/architecture/*` 中涉及当前模块范围的条目
- `modules/t09_traffic_restriction_recovery/*` 模块级源事实

未完成这些 source fact 更新前，T09 不应被表述为 Active 模块。

## Future Implementation Shape

未来授权后，建议结构为：

```text
modules/t09_traffic_restriction_recovery/
├── AGENTS.md
├── INTERFACE_CONTRACT.md
├── README.md
└── architecture/
    ├── 01-introduction-and-goals.md
    ├── 02-constraints.md
    ├── 03-context-and-scope.md
    ├── 04-solution-strategy.md
    ├── 05-building-block-view.md
    ├── 10-quality-requirements.md
    ├── 11-risks-and-technical-debt.md
    └── 12-glossary.md

src/rcsd_topo_poc/modules/t09_traffic_restriction_recovery/
├── __init__.py
├── models.py
├── vector_io.py
├── segment_index.py
├── step1_swsd_arm_movement.py
└── runner.py

tests/modules/t09_traffic_restriction_recovery/
└── test_step1_swsd_arm_movement.py
```

T09 正式模块名已确认为 `t09_traffic_restriction_recovery`。进入实现前仍需单独授权 source fact 更新与目录创建。

入口策略应优先保持模块内 callable runner。若后续确需 root `scripts/` wrapper，必须作为入口变更任务单独授权，并同步 `docs/repository-metadata/entrypoint-registry.md`。

## Future Step1 Outputs

建议 Step1 输出目录：

```text
<out_root>/<run_id>/step1_swsd_arm_movement/
```

Step1 输出采用 GPKG + CSV + JSON 三形态。建议输出文件：

- `t09_swsd_kind2_4_junctions.gpkg/csv/json`
- `t09_swsd_arms.gpkg/csv/json`
- `t09_swsd_arm_movements.gpkg/csv/json`
- `t09_swsd_arm_build_audit.gpkg/csv/json`
- `t09_step1_summary.json`

## Future Algorithm Notes

实现应优先使用 T01 Segment 成果：

1. 读取 SWSD nodes / roads / segment。
2. 按 `mainnodeid` 构建语义路口组。
3. 选择代表 `kind_2 = 4` 的 SWSD 语义路口。
4. 构建 Segment 索引：
   - `road_id -> segment_id`
   - `junction_id -> pair segment ids`
   - `junction_id -> internal segment ids`
5. 从目标路口 incident roads 建立 seed road role。
6. 将 seed road 绑定到 Segment corridor。
7. 对 Segment 内部目标路口执行可审计切分或输出人工复核。
8. 构建 Arm。
9. 构建 inbound-capable Arm 到 outbound-capable Arm 的 Movement。
10. 输出审计与 summary。

其中第 7 步已经确认是 Step1 必需能力：目标路口作为 Segment `junc_nodes` 时必须执行内部切分；输入拓扑不足时输出明确失败原因，而不是把人工复核作为正常完成路径。

P01 只作为策略参考：

- Arm 与 Movement 术语。
- Road direction 角色。
- movement type 判定思路。
- review / audit 组织方式。

T09 不应依赖 P01 FinalArm 或 P01-Final RoadNextRoad 输出作为 Step1 必需输入。

## Risks

- Segment `junc_nodes` 场景如果切分不当，可能重复生成 Arm 或破坏 Segment 语义。
- `direction` 与几何方向不一致时，Movement 类型与进入 / 退出能力可能出现冲突，需要显式 direction audit。
- SWSD restriction 语义尚未进入 Step1；后续阶段不得把 Step1 Movement 候选误表述为允许通行或最终 restriction 输出。
- 若未来新增脚本入口，会触发入口治理同步。

## Verification For Draft

当前草案阶段验证：

- 确认只新增 `specs/t09-traffic-restriction-recovery/` 下 Markdown 文件。
- 确认未修改项目级源事实。
- 确认未新增源码、测试、脚本或入口登记。

未来实现阶段验证：

- `git diff --check`
- `.venv/bin/python -m pytest tests/modules/t09_traffic_restriction_recovery/`
- T09 Step1 synthetic smoke run
- GIS QA 五项：CRS、拓扑一致性、几何语义、审计可追溯、性能可验证
