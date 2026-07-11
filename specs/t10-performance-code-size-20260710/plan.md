# Implementation Plan: T10 六用例无损性能优化与 60 KB 架构收敛

**Branch**: `codex/t10-performance-60pct-20260710` | **Date**: 2026-07-10 | **Spec**: `specs/t10-performance-code-size-20260710/spec.md`

## Summary

本轮分成两条必须同时闭环的主线：

1. 以正式 `96b0ea5` 六用例基线的 `3319.340s` 为性能分母，在当前 main 业务版本上建立未优化 reference，围绕 T03、T04、T06 Step3 三个占比 `85.35%` 的热点做可证明业务等价的代码优化，最终九阶段耗时合计 `<= 1991.604s`。
2. 将初始审计的 55 个达到或超过 60 KB 的 tracked 源码/测试文件中除 Retired T02 外的文件拆分到严格 `< 61440 bytes`，保留原 import、callable、CLI、脚本参数、schema 和输出契约；T02 按用户 2026-07-11 授权不拆分，其结构债继续保留在 code-size audit。

所有工作在独立工作树完成。T10 主链变更按“模块测试 -> `1885118` -> 大阶段六用例”执行；不进入 T10 的模块使用其正式模块测试，不伪造 `1885118` 覆盖。

## Technical Context

**Language/Version**: Python 3.10.12、Bash、PowerShell（仅宿主编排）
**Primary Dependencies**: repo `pyproject.toml` / `uv.lock` 既有依赖，重点为 GeoPandas/Fiona/Shapely/NetworkX/Pandas 及标准库
**Storage**: GPKG、CSV、JSON、Markdown、stdout/stage manifest；正式基线只读
**Testing**: pytest、T10 `1885118` Case replay、T10 六用例 replay、结构化 GPKG/CSV/JSON 等价比较
**Target Platform**: Windows 宿主 + WSL，repo 标准 `.venv` Python 3.10
**Project Type**: GIS/拓扑 brownfield 多模块流水线
**Performance Goals**: 六用例九阶段合计 `<= 1991.604s`；阶段热点和前后占比可审计
**Constraints**: 业务结果完全不变；除 Retired T02 外所有受治理文件 `< 61440 bytes`；无新入口、无接口/字段/依赖变化；先 `1885118` 后六用例
**Scale/Scope**: 6 个 T10 Case、9 个正式 stage、693 个 tracked 受治理文件、55 个体量整改对象

## Constitution Check

### Pre-research gate

- [x] 已从 repo root `README.md` 进入项目级源事实链。
- [x] 已读取 `SPEC.md`、`docs/PROJECT_REQUIREMENTS.md`、`docs/architecture/*`、`module-lifecycle.md`。
- [x] 已读取 T10 `AGENTS.md`、`SPEC.md`、`architecture/*` 和 `INTERFACE_CONTRACT.md`。
- [x] 已读取 `code-boundaries-and-entrypoints.md` 与当前 `code-size-audit.md`。
- [x] 已使用 SpecKit 承接正式大型跨模块重构，并在 spec 中覆盖产品/架构/研发/测试/QA 五视角。
- [x] 当前主仓库为干净 `main`，独立工作树从 `8e4e35c` 创建。
- [x] 当前没有源事实冲突；基线版本与当前 main 的 T09 既有差异已显式拆成“性能基线”和“同业务版本等价 reference”。

### Implementation gate

- [x] 完成当前 main 未优化 reference 与动态 profiling。
- [ ] 完成跨文档/接口/入口/体量 `analyze.md`，确认无硬停机冲突。
- [ ] 每个待修改模块先读取其模块级源事实和局部 AGENTS。
- [ ] 每个源码/脚本写入前记录当前 bytes；新文件先确认不存在。
- [ ] 所有 `>= 100 KB` 拆分与 `code-size-audit.md` 更新保持同轮。
- [ ] 不修改任何正式入口或契约默认值；如果性能目标只能通过改变官方调用方式实现，按 AGENTS §1.2/§1.7 停机回报，不擅自变更。
- [ ] 不新增字段强规则、不改变 CRS/拓扑/几何业务语义。

### Post-design gate

- [ ] facade/extraction 边界保留 public surface，拆分清单与测试映射一一对应。
- [ ] 性能优化与机械拆分分开提交/验证，便于定位业务差异。
- [ ] 业务等价比较覆盖正式输出内容，不以文件存在或 SHA 单独证明。
- [ ] 排除 Retired T02 后的全量体量扫描结果 `>= 61440 bytes = 0`。

## Project Structure

### SpecKit artifacts

```text
specs/t10-performance-code-size-20260710/
├── spec.md
├── research.md
├── plan.md
├── tasks.md
└── analyze.md
```

不新增 contracts：本轮要求保持既有模块契约不变。
不新增 quickstart/正式入口：执行仍使用已登记的 `scripts/t10_run_e2e_cases.sh` 与现有 pytest 入口。

### Source scope

```text
src/rcsd_topo_poc/modules/
├── t01_data_preprocess/                 # 60 KB 拆分；次级性能热点
├── t02_junction_anchor/                 # Retired，仅机械拆分与兼容保持
├── t03_virtual_junction_anchor/         # 首要性能热点 + 60 KB 拆分
├── t04_divmerge_virtual_polygon/        # 第二性能热点 + 60 KB 拆分
├── t05_junction_surface_fusion/         # 60 KB 拆分
├── t06_segment_fusion_precheck/         # 第三性能热点 + 60 KB 拆分
├── t07_semantic_junction_anchor/         # 60 KB 拆分
├── t08_preprocess/                      # 60 KB 拆分，不进入 Case runner
├── t09_swsd_field_rule_restoration/     # 60 KB 拆分，保留当前 main 业务版本
├── t10_e2e_orchestration/               # case_runner 60 KB 拆分，不改入口契约
├── t11_manual_relation_review/          # 60 KB 拆分，不进入六用例
└── p01_arm_build/                       # 60 KB 拆分，不替代 T09

tests/modules/                            # 12 个超 60 KB 测试按场景/fixture 拆分
docs/repository-metadata/code-size-audit.md
```

55 个初始超线文件的精确清单见 `research.md`；最终验收仅按用户授权排除 Retired T02，其余文件禁止缩减范围。

## Architecture Decisions

### AD-001 双参考口径

- 性能分母：正式 `96b0ea5` 六用例 stage duration 总和。
- 业务等价 reference：当前 main 未优化 run。
- 当前 main 相对正式基线的既有差异必须独立记录，不能算作本轮变化。

### AD-002 机械拆分与性能优化分离

- 先为目标文件建立 characterization/import coverage。
- 机械拆分只移动职责和保留 re-export/facade，不顺手改算法。
- 机械拆分通过后再在热点 helper 内做性能优化。
- 每个逻辑批次分别保留测试与 `1885118` 证据。

### AD-003 性能优化允许项

- 避免同一输入 GPKG/CSV/JSON 的重复读取和重复 CRS 转换。
- 在生命周期明确的只读范围内复用 spatial index、graph adjacency、prepared geometry、lookup map。
- 将逐行 Python 循环改为结果顺序稳定的批量/向量化等价实现。
- 消除重复 geometry materialization、重复 serialization 和不必要的深拷贝。
- 复用已有 worker 参数支持，但最终验收不得依赖改变正式接口默认值。

### AD-004 性能优化禁止项

- 不减少候选、审计、正式输出或 QA 检查。
- 不改变阈值、浮点精度、空间范围、排序语义、随机种子或算法门禁。
- 不通过改变公开 worker 默认值、增加新 CLI/env 参数或跳过慢 Case 达标。
- 不以并发导致的非确定输出换取 wall-clock 收益。

### AD-005 60 KB 拆分模式

- 原模块保留 public callable/import surface；实现下沉到名称体现单一职责的内部模块。
- 巨型测试按业务场景拆文件，共享 fixture 下沉 `conftest.py` 或现有 test helper。
- root 脚本如需拆分，原脚本保留参数解析/调度；本轮当前无超 60 KB root script，因此默认不触碰。
- T02 按用户 2026-07-11 授权完全排除，不做结构迁移，不恢复 Retired 模块职责。

## Phase Plan

### Phase 0 - Evidence foundation

1. 固化正式基线性能 CSV、六用例清单和目标值。
2. 验证 WSL、标准 Python、package 路径和独立 run root。
3. 在当前 main 运行未优化 `1885118`，再运行未优化六用例 reference。
4. 生成业务指纹与结构化比较基准。
5. 对 `1885118` 的 T03/T04/T06 Step3 做动态 profiling，并结合静态调用图定位重复 I/O、索引、几何和 graph 计算。

### Phase 1 - Hotspot performance and related splitting

1. T03：先拆 `step3_engine.py / step4_association.py / step6_geometry.py`，再优化最高累计热点。
2. T04：拆四个超 60 KB 文件，并优化 reference/event interpretation 中的重复空间计算。
3. T06 Step3：拆 replacement、advance-right、topology audit/supplement 文件，并优化重复图/几何/输出准备。
4. 每个模块批次运行单元测试和 `1885118`；Phase 1 完成后执行六用例回归。

### Phase 2 - Remaining T10-chain 60 KB convergence

1. T01、T05、T07、T09、T10 按 research 清单拆分。
2. 对 T01/T05/T07/T09/T10 分别运行模块测试与 `1885118`。
3. Phase 2 完成后执行六用例业务等价和性能回归。

### Phase 3 - Non-T10-chain and tests 60 KB convergence

1. T08、T11、P01 源码机械拆分；T02 按用户授权不拆分。
2. 12 个超 60 KB test 文件按场景拆分。
3. 使用对应模块测试验证；不声称 `1885118` 覆盖这些模块。
4. 更新 `code-size-audit.md` 并运行全仓体量扫描。

### Phase 4 - Final verification

1. 重跑 `1885118` 完整门禁。
2. 重跑六用例完整端到端。
3. 生成业务等价、性能分布、GIS/拓扑和体量机器报告。
4. 执行全量相关 pytest 与完成审计。

## Verification Matrix

| Requirement | Evidence |
|---|---|
| 性能 `<= 60%` | 基线 CSV + 优化 run 六个 Case stage JSON/CSV + 计算报告 |
| 业务完全等价 | current-main reference 与 optimized run 的结构化 CSV/JSON/GPKG diff |
| `1885118` 优先 | 每个 T10 主链阶段的 run root、stage status 和 diff 报告 |
| 六用例回归 | 六个 Case 全部 passed、产物完整、总体比较报告 |
| 除 Retired T02 外所有文件 `< 60 KB` | tracked-file 全量 bytes CSV/JSON，排除 T02 后超线计数为 0 |
| 接口/入口不变 | public import/contract tests、CLI/script registry diff 为 0 |
| GIS/拓扑五项 | CRS、geometry、topology audits、traceability、performance report |

## Complexity Tracking

| Complexity | Why needed | Control |
|---|---|---|
| 跨 12 个模块与 tests | 用户明确要求全仓受治理文件低于 60 KB | 机械拆分按模块分批，独立测试，不混入业务规则 |
| 双参考基线 | 正式性能基线早于当前 T09 业务版本 | 明确区分 performance denominator 与 same-business reference |
| 真实六用例耗时较长 | 最终目标必须实测 | `1885118` 快速门禁，大阶段才跑六用例 |
