# Tasks: T12 FRCSD 质量审计

**Input**: [spec.md](spec.md)、[plan.md](plan.md)、[research.md](research.md)、[data-model.md](data-model.md)、[contracts/](contracts/)
**Branch**: `codex/003-t12-frcsd-quality-audit`
**Implementation discipline**: implement 阶段遵循 `.agents/skills/default-imp/SKILL.md`；任何源码/脚本写入前先记录当前字节数。

## 授权范围

本任务书明确授权：

- 新增正式模块 `modules/t12_frcsd_quality_audit/`、`src/rcsd_topo_poc/modules/t12_frcsd_quality_audit/`、`tests/modules/t12_frcsd_quality_audit/`。
- 新增一个正式 root 入口 `scripts/t12_run_frcsd_quality_audit.py`，并同步入口登记。
- 修改 T10 Case/full 编排及 T10 模块契约，使 T12 成为可选 audit-only stage。
- 修改项目级 `SPEC.md`、`docs/PROJECT_REQUIREMENTS.md`、必要的 `docs/architecture/*`、模块生命周期/盘点/文档状态和入口治理文档，以登记 T12。
- 新增 `1026960` 复核 fixture 和 SpecKit validation 工件。

明确排除：

- 不改变 T06 现有接口、替换策略、Step2/Step3 结果或默认参数；只 import 复用稳定 helper/语义。
- 不修改 T09、T11 算法和业务 handoff。
- 不修改 `AGENTS.md`、SpecKit 宪章或 Retired T02。
- 不把 1V1 FRCSD 错误自动修复，不对输入执行 silent fix。
- 不在生产代码硬编码 `1026960` 的任何 Segment/Road/Node ID 或复核决定。
- 不声称已执行内网完整数据。

## Phase 1 - Setup 与治理闸门

### 架构 / QA

- [x] T001 确认分支、worktree、SpecKit 工件、用户路径 `E:\` 与 WSL `/mnt/e/` 换算，并记录当前 `git status`。
- [x] T002 枚举本任务全部拟修改源码/脚本文件，逐文件记录写入前字节数；新文件记录为 `0`；若任何目标 `>=100KB` 立即按 AGENTS §1.4 停机。
- [x] T003 核对 `entrypoint-registry.md`、T10 正式脚本和实际 stage/CLI 事实一致；若不一致按 §1.7 停机。
- [x] T004 建立 `tests/fixtures/t12/1026960_review_decisions.csv`，只保存外部复核真值；校验 35 个唯一 candidate、10 confirmed、25 excluded、0 manual。

## Phase 2 - User Story 1：自动候选审计

**Independent goal**: 不提供复核文件时，T12 能从原始 1V1 FRCSD 生成可追溯候选和 carrier 证据，但最终确认清单为空。

### 测试视角（先写失败测试）

- [x] T005 [P] 新增 `test_carrier_graph.py`，覆盖 T06 direction 语义、canonical alias、多集合 directed/undirected shortest path、确定性 Road 顺序。
- [x] T006 [P] 新增 `test_anchor_portals.py`，覆盖 T07 truth group、T05 grouped nodes、50m portal、start 出边/end 入边、多 portal 正反方向不同。
- [x] T007 [P] 新增 `test_candidate_audit.py`，覆盖 `directed_carrier_missing`、`required_local_connectivity_missing`、等价 carrier 排除、crop edge、DriveZone 仅作证据。
- [x] T008 [P] 新增 `test_runner_contract.py` 的输入预检用例，覆盖缺失 CRS、CRS 转换、无效几何、endpoint 缺失、T05/T06 同批次派生链、wrong-batch 阻断和 silent-fix=false；不得把原始 target 与 T05 copy-on-write 指纹不同视为 mismatch。

### 研发视角

- [x] T009 [P] 新增 `models.py`，定义不可变 run/config/path/candidate/review 模型和值域校验。
- [x] T010 [P] 新增 `inputs.py`，实现 GPKG/CSV 加载、字段解析、CRS/几何/端点/指纹预检和 T06 target identity 审计。
- [x] T011 新增 `carrier_graph.py`，复用 T06 `NodeCanonicalizer/parsing/direction` 语义，构建全图/局部图和多集合最短路；不得复制 T06 替换判定。
- [x] T012 新增 `anchor_portals.py`，合并 T05 grouped nodes 与 FRCSD main/subnode 组，建立 truth/spatial portals，默认 portal radius=local corridor=50m。
- [x] T013 新增 `candidate_audit.py`，从 SWSD 必需方向生成 local/full directed/undirected carrier evidence 和候选类型；Source 不参与 verdict。
- [x] T014 新增 `outputs.py`，写稳定 CSV/JSON/GPKG/Markdown，空结果也写契约文件和 schema，所有图层保留 processing CRS。
- [x] T015 新增 `runner.py` 与 `__init__.py`，组织预检、索引、候选、review、输出和阶段性能审计；输入只读、`silent_fix=false`。

### QA 视角

- [x] T016 运行 T005-T008；确认 CRS、拓扑、几何语义、审计追溯和性能字段均有自动化断言。

## Phase 3 - User Story 2：复核发布

**Independent goal**: 外部复核决定与候选严格 join，三类状态互斥且只有 confirmed 进入最终问题。

### 测试视角（先写失败测试）

- [x] T017 [P] 新增 `test_review_publish.py`，覆盖 confirmed/excluded/manual、缺失决定、重复、未知 candidate、run_id mismatch、缺失理由。
- [x] T018 在 `test_runner_contract.py` 增加输出 schema/空图层/三类计数守恒/禁止 confidence 字段测试。

### 研发视角

- [x] T019 新增 `review_publish.py`，实现外部复核合同、三类互斥发布和最终计数。
- [x] T020 完成 runner 的 `--review-decisions` 路径；无复核文件时所有候选进入 manual，不能自动 confirmed。
- [x] T021 新增薄入口 `scripts/t12_run_frcsd_quality_audit.py`，只处理参数、退出码和打印 artifact JSON；更新入口注册表。

### 产品 / QA 视角

- [x] T022 验证最终 CSV/GPKG 不含高/中概率字段；报告明确区分自动候选、复核排除、待复核和确认问题。

## Phase 4 - User Story 3：T10 标准编排

**Independent goal**: 启用 T12 时，T10 在 T06 Step3 后、T11 前留下 stage 证据；未启用时既有流程不变。

### 测试视角（先写失败测试）

- [x] T023 [P] 新增 T10 Case stage adapter 测试，覆盖显式 `frcsd_1v1_*` slots、缺失阻断、输出 handoff 和 stage 顺序。
- [x] T024 [P] 新增/扩展 T10 full runner shell contract 测试，覆盖 `RUN_T12`、显式 FRCSD 路径、resume/stage normalize/manifest/finalize。
- [x] T025 [P] 增加未启用 T12 的兼容回归，确认既有 T06→T11→T09 输入路径与摘要不变。

### 研发视角

- [x] T026 新增 `case_runner_t12.py` adapter，并对 T10 Case runner 作最小修改：stage order/module map/dispatch/handoff；不回填业务算法。
- [x] T027 修改 `scripts/t10_run_innernet_full_pipeline.sh`，新增可选 T12 stage、预检、manifest、resume/finalize 和输出索引；不得隐式借用 RCSD slots。
- [x] T028 修改 T10 package/input contract，使新 Case package 可显式登记 `frcsd_1v1_roads/frcsd_1v1_nodes/rcsd_intersection`；旧 package 在 T12 关闭时兼容。

### QA 视角

- [x] T029 运行 T023-T025 及全部 T10 测试；比较启用/禁用 T12 时 T06/T11/T09 handoff 指纹。

## Phase 5 - 模块与项目源事实同步

### 产品 / 架构视角

- [x] T030 基于模板建立 `modules/t12_frcsd_quality_audit/README.md`、`SPEC.md`、`INTERFACE_CONTRACT.md` 和 `architecture/01~06`，冻结 target、状态、入口和非目标。
- [x] T031 更新项目 `SPEC.md`、`docs/PROJECT_REQUIREMENTS.md` 和必要 `docs/architecture/*`，把 T12 登记为原始 1V1 FRCSD audit-only QA，不改写 T06 F-RCSD 定义。
- [x] T032 更新 `module-lifecycle.md`、`current-module-inventory.md`、`module-doc-status.csv` 和必要文档索引，登记 T12 Active。
- [x] T033 更新 T10 `SPEC.md`、`INTERFACE_CONTRACT.md` 与 architecture 文档，登记 stage 顺序、输入 slots、audit-only 和兼容边界。
- [x] T034 更新 `entrypoint-registry.md` 的摘要数字和 T12 脚本行；如代码体量审计表口径因本轮变化应更新，则同步 `code-size-audit.md`。

## Phase 6 - 1026960 端到端业务效果回归

### 测试 / QA 视角

- [x] T035 新增 `validation/validate_1026960.py`，参数化发现本地真实输入和现有 T10 compatibility root，并物化带显式 `frcsd_1v1_*` slots 的临时 Case package；不得硬编码生产 runner。
- [x] T036 运行 T12 standalone 无复核模式，证明候选证据完整、confirmed=0、manual=candidate count。
- [x] T037 使用 `tests/fixtures/t12/1026960_review_decisions.csv` 运行复核发布，验证 candidate=35、confirmed=10、excluded=25、manual=0 和 10 个确认 ID 完全一致。
- [x] T038 专项验证 `1001716_1010487` 由 50m portal 通用逻辑找到有向 carrier，`1039488_1039490` 由 grouped node 通用逻辑找到有向 carrier；扫描生产源码确保无这两个 ID。
- [x] T039 构建/刷新 T12 QGIS 审计工程或复用现有工程图层，执行自动叠加检查，显式验证 CRS、DriveZone/reference、几何有效性、空层和 source path。
- [x] T040 在同环境运行当前兼容分析基线和正式 T12，记录数据规模、环境、阶段耗时；验证 `<=150%`，否则优化后复测或保持 SC-006 未通过。
- [x] T041 运行包含 T12 的 `1026960` T10 端到端，验证 stage manifest、T06/T11/T09 handoff 不变、10/25/0 结果可定位。

## Phase 7 - 全量回归与完成审计

### 研发 / 测试 / QA

- [x] T042 运行 T12 全量测试、受影响 T06 helper 测试和 T10 全量测试。
- [x] T043 运行 `.venv/bin/python -m rcsd_topo_poc --help`、脚本枚举与 registry 对照，确认入口事实一致。
- [x] T044 运行所有变更源码/脚本字节审计和仓库 `>=100KB` 扫描；本轮不得新增超阈值文件，未触碰既有超阈值文件。
- [x] T045 运行 `git diff --check`、测试文件/fixture 完整性、项目/模块源事实交叉搜索和无对象级白名单扫描。
- [x] T046 逐项核对 FR-001~FR-022、SC-001~SC-008，并生成 validation report；证据不足的条目不得标记完成。
- [x] T047 更新本任务勾选状态，最终交付按“已修改 / 已验证 / 待确认”分档，列出文件路径和用途；内网完整数据保持待用户执行，不冒充已验证。

## Dependency Graph

```text
T001-T004
  -> T005-T016 (候选审计)
      -> T017-T022 (复核发布)
          -> T023-T029 (T10 编排)
              -> T030-T034 (源事实同步)
                  -> T035-T041 (真实回归)
                      -> T042-T047 (完成审计)
```

## Parallel Opportunities

- T005-T008 可并行编写失败测试；T009-T010 可并行实现模型和输入层。
- T017 与 T023/T024 的测试准备可并行，但实现必须在 candidate/output contract 稳定后进行。
- T030 的 T12 文档与 T033 的 T10 文档可在代码接口冻结后并行。
- 本轮未授权多 Agent 执行；标记 `[P]` 只表达任务依赖关系，不代表实际委派。
