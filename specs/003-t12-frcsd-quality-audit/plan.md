# Implementation Plan: T12 FRCSD 质量审计

**Branch**: `codex/003-t12-frcsd-quality-audit` | **Date**: 2026-07-18 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `/specs/003-t12-frcsd-quality-audit/spec.md`

## Summary

新增正式 `t12_frcsd_quality_audit` 模块，对调用方显式提供的原始 1V1 FRCSD 做只读通行质量审计。T12 使用 SWSD Segment 的必需方向、T05/T07/RCSDIntersection 路口真值、完整 FRCSD 节点组与 portal，检查局部/全图、有向/无向 carrier，并消费 T06 Step2 失败证据作为候选来源和交叉解释。自动候选与人工复核发布严格分层，只有 `confirmed_frcsd_quality_issue` 进入最终问题清单。T10 在 T06 Step3 后、T11 前可选编排 T12，T06、T11、T09 既有业务 handoff 保持不变。

## Technical Context

**Language/Version**: Python `3.10.x`；T10 全量包装为 Bash，内网标准执行环境为 WSL
**Primary Dependencies**: `geopandas 1.1.x`、`shapely 2.x`、`fiona 1.9.x`、`pyproj 3.6.x`；复用 `t06_segment_fusion_precheck.graph_builders/parsing/road_attributes`
**Storage**: 文件型输入输出；GPKG、CSV、JSON、Markdown；不引入数据库
**Testing**: `pytest` 单元/契约/集成测试，`1026960` 外部真实数据回归，T10 既有回归
**Target Platform**: Windows PowerShell 负责本地协调；正式 Python 验证使用 WSL `/mnt/e/.../.venv/bin/python` 3.10；内网完整数据由现有 WSL T10 全量入口运行
**Project Type**: Python GIS 批处理模块 + repo root standalone script + T10 orchestration stage
**Performance Goals**: `1026960` 的 1267 Segment、4289 FRCSD Road、4762 FRCSD Node 候选与复核总耗时不超过同一 Python/操作系统环境复跑兼容实验基线的 150%；历史 Windows `5.609s` 与 WSL `2.827s` 只作分项参考，禁止相加作为正式基线；全量运行记录分阶段耗时和对象规模
**Constraints**: 单源码/脚本 `<100KB`，本轮新增文件目标 `<60KiB`；不修改输入、不 silent fix；CRS/拓扑/几何/审计/性能五项显式验证；生产代码不含对象级白名单
**Scale/Scope**: 首个真实回归为 `1026960`（1267 Segment，35 候选，10 确认）；设计支持内网完整数据，以全图 FRCSD Road/Node 建一次图、按 Segment 空间索引查询局部 corridor

## Constitution Check

*GATE: Phase 0 前检查通过；Phase 1 设计后再次检查通过。*

| Gate | 结论 | 证据 / 处理 |
|---|---|---|
| 分层源事实 | PASS | SpecKit 只承载变更工件；实现同轮更新项目级源事实、T10/T12 模块源事实、生命周期与入口登记。 |
| Brownfield 先研究 | PASS | 已审阅 T06/T10 契约、实现和 `1026960` 原始实验；决策写入 `research.md`。 |
| arc42 模块文档 | PASS | T12 基于 `modules/_template` 建立 `SPEC/architecture/INTERFACE_CONTRACT` 完整文档面。 |
| 非破坏性迁移 | PASS | T06 保持现状；T12 新增只读审计；T10 未启用 T12 时保持兼容。 |
| 中文文档 | PASS | 模块和项目文档默认中文，字段/路径/命令保留英文。 |
| 入口治理 | PASS | 任务明确授权新增 T12 正式入口；同轮更新 `entrypoint-registry.md` 和受影响契约。 |
| 文件体量 | PASS | 写入前逐文件检查当前字节数；新源码按 0 字节处理；不触碰现存超 100KB 文件；新增/修改文件完成后全量审计。 |
| GIS 五项 | PASS | CRS、拓扑、几何语义、审计可追溯和性能分别进入实现与验收任务。 |
| 五类职责 | PASS | 下文和 `tasks.md` 显式覆盖产品、架构、研发、测试、QA。 |

## Architecture and Responsibilities

### 产品视角

- 最终问题清单只包含复核成立的 FRCSD 质量问题，不再输出高/中概率标签。
- 自动候选以高召回和证据完整为目标；复核发布以最终准确性为目标。
- 当前 `1026960` 的 10/25/0 结果作为业务效果回归，不作为生产规则或对象白名单。

### 架构视角

- T12 被检 target 是原始 1V1 FRCSD；T06 Step2 是候选/诊断证据，Step3 是对照证据。T06 实际消费的 T05 copy-on-write FRCSD 只需证明与当前 T05/T06 运行链同批次派生，不要求与原始 target 文件指纹相同。
- T12 复用 T06 的 ID 解析、节点 canonicalization、direction/formway 语义；T12 独有的 portal 集合和多集合最短路属于质量审计能力，不回填 T06 替换主链。
- T10 stage 顺序为 `... -> T06 Step1/2 -> T06 Step3 -> T12 -> T11 -> T09`；T12 不改写 handoff。
- T12 standalone 入口只负责参数解析和调用模块 runner，业务实现留在模块包。

### 研发视角

- 文件按 model、input/CRS、graph、anchor portal、candidate、review、output、runner 拆分，单文件目标 `<60KiB`。
- 全图 FRCSD graph/alias 只构建一次；Segment 局部路网通过空间索引筛选；路径结果确定性排序。
- 复核决定通过外部 CSV/JSON 输入，不允许生产源码包含 case ID 分支。

### 测试视角

- 单元测试覆盖 direction、alias/group、portal、多集合最短路、路径指标和复核状态机。
- 合同测试覆盖必选输入、CRS 阻断、target manifest、输出 schema、重复/未知复核决定。
- 真实数据回归覆盖 35/10/25/0、10 个确认 ID、两个已知复杂 portal 排除。
- T10 回归覆盖 stage 顺序、未启用兼容、handoff 指纹不变和 failure/blocked 状态。

### QA 视角

- CRS：输入 CRS 全部显式，统一到米制处理 CRS；不允许无 CRS 猜测。
- 拓扑：只审计，不修复；Road 端点、direction、局部/全图路径分别记录。
- 几何：每条 carrier 保存 Road ID、长度、偏离和 corridor 解释。
- 审计：manifest 含输入指纹、参数、环境、输出、计数和 `silent_fix=false`。
- 性能：记录 loading/index/graph/candidate/review/output 分段耗时及对象规模。

## Project Structure

### Documentation (this feature)

```text
specs/003-t12-frcsd-quality-audit/
├── spec.md
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   ├── cli-contract.md
│   └── output-contract.md
├── checklists/requirements.md
├── validation/
│   └── validate_1026960.py
└── tasks.md
```

### Source Code (repository root)

```text
src/rcsd_topo_poc/modules/t12_frcsd_quality_audit/
├── __init__.py
├── models.py
├── inputs.py
├── carrier_graph.py
├── anchor_portals.py
├── candidate_audit.py
├── review_publish.py
├── outputs.py
└── runner.py

scripts/
└── t12_run_frcsd_quality_audit.py

src/rcsd_topo_poc/modules/t10_e2e_orchestration/
└── case_runner_t12.py

tests/modules/t12_frcsd_quality_audit/
├── test_carrier_graph.py
├── test_anchor_portals.py
├── test_candidate_audit.py
├── test_review_publish.py
├── test_runner_contract.py
└── test_1026960_regression.py
```

**Structure Decision**: 采用现有单 Python package 结构。T12 独立成正式模块；T10 只新增轻量 stage adapter；root script 为唯一新增正式 standalone 入口。真实数据验证脚本位于 SpecKit `validation/`，不登记为长期官方入口。

## Phase 0 - Research

- 冻结原始 1V1 FRCSD 与 T06 compatibility evidence 的身份边界。
- 比较当前 30m portal、T05 grouped nodes 和 50m corridor，确定通用 portal 规则。
- 确定 SWSD direction 与 FRCSD `direction` 的复用语义。
- 冻结 candidate/review/formal 三层状态和 T10 audit-only stage 位置。
- 确定外部真实回归与内网未执行边界。

## Phase 1 - Design and Contracts

- `data-model.md` 定义 run、target、Segment requirement、anchor group、carrier evidence、candidate 和 review decision。
- `contracts/cli-contract.md` 定义 standalone/T10 参数与退出状态。
- `contracts/output-contract.md` 定义文件名、字段和值域。
- `quickstart.md` 给出 Windows/WSL 路径换算和 `1026960`、内网全量运行方式。
- 模块源事实按 arc42 模板建立；项目级文档与 T10 契约同步 T12。

## Phase 2 - Implementation Strategy

1. 先实现纯 ID/direction/graph/path/portal 单元并测试。
2. 实现输入预检、候选生成、复核发布与输出 writer。
3. 用 `1026960` standalone 回归校准通用 portal 逻辑；禁止对象级修补。
4. 新增 T12 root script 与入口登记。
5. 新增 T10 case/full stage adapter，未启用时保持兼容。
6. 更新源事实和模块治理登记。
7. 完成 T12、T10、GIS 五项、性能和文件体量验证。

## Post-Design Constitution Re-check

- 设计没有修改宪章、AGENTS 或未授权模块。
- T06 只被 import 复用，不改变其接口和既有行为。
- 新入口、T10 契约、项目源事实和生命周期均列入同轮任务，不存在隐式入口。
- 生产代码没有 `1026960` 对象级规则；真实结论只在 fixture/validation 中出现。
- 所有计划源码文件均可控制在 60KiB 内，不需要触碰超 100KB 文件。

## Complexity Tracking

当前无宪章违规需要豁免。T12 新模块和单一新入口是用户已授权的正式业务范围，不属于未授权扩张。
