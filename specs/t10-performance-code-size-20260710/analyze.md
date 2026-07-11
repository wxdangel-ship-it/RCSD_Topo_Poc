# Cross-Artifact Analysis: T10 性能与 60 KB 收敛

## 1. 分析结论

当前 `spec.md / research.md / plan.md / tasks.md` 与项目级源事实、T10 模块源事实、入口登记和代码体量治理之间未发现必须触发 AGENTS §1 的冲突。可以进入 reference/profiling 阶段，但在 reference 与动态 profile 完成前，不允许开始大规模源码迁移。

## 2. 需求覆盖矩阵

| 用户要求 | Spec | Plan | Tasks | 最终证据 |
|---|---|---|---|---|
| 六用例耗时不高于基线 60% | FR-001/003/004, SC-001 | Phase 0/1/4 | T013-T016, T046, T071-T073 | baseline CSV、final stage JSON/CSV、计算报告 |
| 业务结果完全不变 | FR-002/005, SC-002 | AD-001/002, Verification Matrix | T011-T014, T024/034/044, T072 | current-main reference 与 final 结构化 diff |
| 除 Retired T02 外所有源码/脚本低于 60 KB | FR-006/007/008, SC-003 | AD-005, Phase 1-3 | T021-T066 | tracked-file 全量 bytes 报告（显式排除 T02） |
| `1885118` 优先 | FR-011, SC-004 | Phase 1/2 | T025/035/045/050-T055/T070 | 单 Case run root、stage status、diff |
| 大阶段后六用例 | FR-011 | Phase 1/2/4 | T046/T055/T071 | 三轮六用例 run root |
| 临时工作树 | FR-012 | Technical Context | T001-T003/T076 | worktree/branch/status |

没有发现用户要求被缩减、改写或仅由间接测试代替。

## 3. 源事实一致性

### 3.1 项目级职责

- 项目主链仍为 `T08 -> T01 -> T07 -> T03 -> T04 -> T05 -> T06 -> T09`。
- T10 Case runner 仍为 `T01 -> T07 Step1/2 -> T03 -> T04 -> T05 -> T06 -> T09`，不调用 T08。
- 本轮性能修改发生在各自模块实现中，T10 只继续编排与记录，不在 T10 内改写 T01-T09 算法。
- 不启用新字段、不修改字段语义、不改变 Step1/Step2 强规则，因此无需修改项目级数据语义源事实。

结论：与 `SPEC.md`、`PROJECT_REQUIREMENTS.md`、`docs/architecture/*` 一致。

### 3.2 T10 契约

- 四个正式脚本入口在 registry、tracked scripts 与 T10 contract 中一致：
  - `scripts/t10_pack_innernet_cases.sh`
  - `scripts/t10_pack_innernet_segments.sh`
  - `scripts/t10_run_e2e_cases.sh`
  - `scripts/t10_run_innernet_full_pipeline.sh`
- 本轮不新增、删除、重命名入口，不改变参数、环境变量、默认值或调用方式。
- T10 `case_runner.py` 的拆分只能保留现有 callable/import surface，不得改变 contract。
- worker 默认值属于契约事实；即使提高默认并发可能加速，也不在当前授权范围，禁止把它作为达标手段。

结论：当前不是入口变更任务，未触发 AGENTS §1.2/§1.3/§1.7。

### 3.3 正式基线与当前 main

- 正式性能基线代码为 `96b0ea5`；当前 main 为 `8e4e35c`，包含已正式合入的 T09 multi-evidence v2。
- 该差异是现存仓库事实，不是 source-of-truth 冲突：T10 statistical baseline 明确登记了基线 commit，当前 main 文档也保留该基线作为当前有效统计基线。
- 为避免回退当前 T09 业务能力，性能分母和业务等价 reference 必须分开：
  - `96b0ea5` 产物提供 `3319.340s` 性能分母；
  - 当前 main 未优化 run 提供本轮业务等价 reference。
- 若未优化 current-main run 相对正式基线已有业务差异，必须登记为 pre-existing，不得算成本轮优化差异。

结论：双参考策略消除了版本错配造成的错误归因，未要求修改源事实。

## 4. 文件体量治理一致性

- 仓库硬阈值为 100 KB；用户要求更严格的 `< 60 KiB`，两者不冲突。
- 实时审计发现 6 个文件 `>= 102400 bytes`，拆分这些文件必须：
  1. 写入前记录当前 bytes；
  2. 不向原超阈值文件追加新逻辑；
  3. 通过提取/迁移使原文件和新文件均低于 60 KiB；
  4. 同轮更新 `docs/repository-metadata/code-size-audit.md`。
- 其余 49 个超 60 KiB 文件同样需要拆分，但只有跨过/处理 100 KB 表事实时触发 audit 强同步。
- T02 虽为 Retired 且仍属于 tracked 结构债，但用户于 2026-07-11 明确授权本轮不拆分；体量验收显式排除 T02，且不允许恢复或扩展其业务职责。
- tests 在治理范围内，12 个超线测试必须按场景/fixture 拆分，不能只拆 source。

结论：计划覆盖 AGENTS §3 全部前置与同步要求；实现时任一目标缺少 bytes 前置证据即不得写入。

## 5. 五职责视角完整性

| 视角 | 覆盖位置 | 状态 |
|---|---|---|
| 产品 | spec User Stories / Success Criteria | 完整 |
| 架构 | spec 架构视角、plan AD-001~005 | 完整 |
| 研发 | spec FR、plan Phase Plan | 完整 |
| 测试 | spec 测试视角、tasks 各模块门禁 | 完整 |
| QA | spec QA 五项、plan Verification Matrix | 完整 |

满足正式大型任务进入 implement 前的任务书要求。

## 6. GIS / 拓扑质量覆盖

- CRS 与坐标变换：比较 source/output CRS 与 CRS audit，不允许隐式默认。
- 拓扑一致性：比较 connectivity/surface/road-node audit，不允许新增 fail 或 silent fix。
- 几何语义：按 layer/schema/feature/attribute/normalized geometry 比较，不以 GPKG 文件 SHA 代替。
- 审计追溯：保留代码提交、输入、参数、环境、run root、stage JSON、stdout 和比较报告。
- 性能验证：保留基线 CSV、profile、final stage durations 与 wall-clock。

五项均映射到 T072-T074，没有遗漏。

## 7. 路径与环境分析

- 当前 shell 为 PowerShell，用户路径为 `E:\Work\RCSD_Topo_Poc`，两者一致。
- 基线文档和 pointer 使用 `/mnt/e/...`，已换算并验证对应 `E:\...` 路径存在；WSL 也已验证可访问临时工作树。
- `docs/repository-metadata/path-conventions.md` 当前不存在。按 AGENTS §7，继续沿用已确认的盘符换算与 `TestData/POC_Data` 约定，并将该文件缺失登记为治理缺口；本轮不顺手创建该项目级治理文档。
- 临时工作树 `.venv` 通过本地 junction 复用主仓库标准 `.venv`，不进入 git，也不改变依赖真相。

结论：未触发 AGENTS §1.6；路径治理文档缺失是非阻塞治理缺口。

## 8. 验证强度分析

### 已有强证据

- 正式基线根和六用例 Case 级产物完整。
- 正式 stage durations 可按六用例聚合。
- 全仓 tracked 文件体量可实时扫描。
- T10 正式入口在 registry/contract/code 三处一致。

### implement 前仍缺失的阻塞证据

- 当前 main 未优化 `1885118` reference。
- 当前 main 未优化六用例 reference。
- CSV/JSON/GPKG 业务指纹与允许忽略字段实现。
- T03/T04/T06 Step3 动态 profile。
- 每个待修改模块的模块级源事实阅读记录。

这些缺口已经逐项映射到 T010-T020/T030/T040/T050-T064；在对应证据完成前不得写相关源码。

## 9. 风险与停机条件

实现中出现以下任一事实必须按 AGENTS §1 停机：

1. 达标必须改变正式 CLI/env/default worker 参数或模块 contract。
2. 性能优化要求减少候选、跳过 QA、改变字段语义或放宽业务门禁。
3. current-main reference 与 source-of-truth 出现无法解释的业务冲突。
4. 任何源文件写入前未完成当前 bytes 检查。
5. 拆分超过 100 KB 文件却无法在同轮更新 code-size audit。
6. 某模块的模块级源事实与本计划的 facade/extraction 边界冲突。

## 10. Gate Verdict

**SpecKit artifact consistency**: PASS
**Source-fact consistency**: PASS
**Entrypoint consistency**: PASS
**Code-size governance plan**: PASS
**Reference/profiling readiness**: PENDING T010-T016
**Large-scale source migration**: NOT YET AUTHORIZED BY GATE

下一步只能执行 reference、comparison helper 和 profiling 基础工作；T010-T016 完成后再重检 implement gate。
