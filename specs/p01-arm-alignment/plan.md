# P01-A2 Arm 配准与 LogicalArmGroup Plan

## 1. Readiness / Preflight

已读取并确认：

- `AGENTS.md`
- `docs/doc-governance/README.md`
- `docs/repository-metadata/code-boundaries-and-entrypoints.md`
- 项目级源事实：`SPEC.md`、`docs/PROJECT_BRIEF.md`、`docs/architecture/*`、`docs/doc-governance/module-lifecycle.md`
- P01-A1 契约与架构：`modules/p01_arm_build/INTERFACE_CONTRACT.md`、`modules/p01_arm_build/architecture/*`
- P01-A1 SpecKit 工件：`specs/p01-arm-build/*`
- P01 基准需求：`/mnt/e/_chatgpt_sync/RCSD_Topo_Poc/P01_1/RCSD_Topo_Poc__P01__REQUIREMENT.md`

结论：

- 当前 P01-A1 已落地，A2 应消费 A1 run root。
- 当前 A1 文档中的“Arm 配准非范围”仅约束 A1，不阻止本轮 A2 扩展；本轮需要同步模块契约与项目登记。
- 当前不新增正式 CLI、`scripts/`、`run.py` 或 `__main__.py`。

## 2. Module Placement

- 复用模块：`p01_arm_build`
- A2 实现：`src/rcsd_topo_poc/modules/p01_arm_build/alignment_*.py`
- A2 测试：`tests/modules/p01_arm_build/test_p01_arm_alignment.py`
- A2 SpecKit 工件：`specs/p01-arm-alignment/`

## 3. Entry Strategy

新增模块内 callable runner：

```text
rcsd_topo_poc.modules.p01_arm_build.alignment_runner.run_p01_arm_alignment_from_args(argv)
```

该 runner 不登记为仓库正式执行入口。后续若需要正式 CLI，必须同步 `entrypoint-registry.md`、CLI、README 与模块契约。

## 4. Implementation Slices

### Slice 1: Contracts and Docs

- 新增 A2 SpecKit 工件。
- 更新 P01 模块契约、架构、README。
- 更新项目级 P01 范围登记。

### Slice 2: A1 Run Root Reader

- 校验 A1 run root 必要文件。
- 读取 preflight、case_input、case_summary 与各 dataset A1 JSON。
- 从 A1 preflight 读取原始 Node / Road 路径并按需加载，用于几何辅助证据和 review。

### Slice 3: ArmProfile

- 从 FinalArm 主对象构建 profile。
- 汇总 InitialArm、LocalArmCandidate、ArmTrace、ThroughDecisionAudit 证据。
- 生成 seed role、terminal、trace stop、geometry summary。

### Slice 4: Candidate Evidence and Scoring

- 生成三类候选边：FRCSD-SWSD、FRCSD-RCSD、SWSD-RCSD。
- 使用无 lineage 评分：seed role、local candidate、trace / terminal、road coverage、geometry。
- 几何只作为辅助，不允许单独 high confidence。
- 输出所有候选、分数、证据、冲突 flags 与排名。

### Slice 5: Evidence Graph and LogicalArmGroup

- 以 FRCSD FinalArm 为承载核心建立 LogicalArmGroup。
- 选择 source candidates 并识别 missing、partial、over_split、over_merged、conflict、uncertain。
- 输出 acceptable_for_downstream。

### Slice 6: Outputs and Review

- 写 logical_arm_groups、raw_arm_alignment、arm_build_feedback、source_extra、candidate matrix。
- 写 source review PNG/GPKG 和三源 compare PNG/GPKG。
- 写 summary 和 review index。

### Slice 7: Tests and QA

- synthetic 覆盖 stable / missing / partial / over_split / over_merged / conflict / multi group。
- 检查输出目录结构、PNG/GPKG 存在性、summary/review index。
- 回归 P01-A1 测试。

## 5. File Size Control

- 每个源码 / 测试文件写入前按 `AGENTS.md §3` 确认当前字节数。
- 新增 A2 实现拆分为多个小文件，单文件目标低于 50 KB，硬上限 100 KB。
- 不修改任何已超阈值源码 / 脚本文件。

## 6. QA Strategy

- CRS：A2 review GPKG 沿用 A1 preflight 中原始数据 CRS；无法加载原始数据时写入 issue，不静默伪造几何。
- 拓扑一致性：A2 不重算 A1 trace，不 silent fix A1 输出。
- 几何语义：geometry 只作为低权重辅助证据；非几何证据不足时不得 high confidence。
- 审计可追溯：preflight 记录 A1 run root、输入路径、run id、case 列表、加载状态；candidate 保存所有分数与选择原因。
- 性能：summary 记录 group、LogicalArmGroup、candidate、issue 数与耗时。
