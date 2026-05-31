# T09 Step1/2：CodeX 任务书

- 文档类型：CodeX 实施任务书
- 适用分支：`spec/t09-swsd-field-rule-restoration`
- 需求说明书：`specs/t09-swsd-field-rule-restoration/spec.md`
- 任务范围：T09 Step1 / Step2
- 状态：Draft / ready for implementation planning

## 1. 任务目标

CodeX 需要基于 `specs/t09-swsd-field-rule-restoration/spec.md` 完成 T09 Step1/2 的最小可实现闭环。

本任务书只描述实施任务、边界、验收与工作纪律；业务需求以需求说明书为准，不在本文件重复展开。实现过程中如发现本任务书与需求说明书冲突，以需求说明书为准，并停机回报冲突点。

## 2. 必读材料

实施前必须阅读：

1. repo root `AGENTS.md`。
2. `docs/doc-governance/README.md`。
3. `SPEC.md`。
4. `docs/PROJECT_BRIEF.md`。
5. `docs/doc-governance/module-lifecycle.md`。
6. `modules/t01_data_preprocess/INTERFACE_CONTRACT.md`。
7. `modules/t08_preprocess/INTERFACE_CONTRACT.md`。
8. `modules/p01_arm_build/INTERFACE_CONTRACT.md`。
9. `specs/t09-swsd-field-rule-restoration/spec.md`。

若只需要实现 spec 工件验证，不得顺手修改项目级源事实文档或已登记模块契约。

## 3. 实施边界

### 3.1 允许改动

当前任务允许新增或修改：

- `specs/t09-swsd-field-rule-restoration/**`
- `src/rcsd_topo_poc/modules/t09_swsd_field_rule_restoration/**`
- `tests/modules/t09_swsd_field_rule_restoration/**`
- 必要的模块包初始化文件

### 3.2 默认禁止改动

未经用户重新授权，不得修改：

- `SPEC.md`
- `docs/PROJECT_BRIEF.md`
- `docs/architecture/**`
- `docs/doc-governance/**`
- `docs/repository-metadata/**`
- `modules/t01_data_preprocess/**`
- `modules/t08_preprocess/**`
- `modules/p01_arm_build/**`
- repo 官方 CLI、Makefile、常驻脚本入口

### 3.3 正式模块登记边界

本任务优先实现最小 Python 包与测试闭环。是否新增正式模块目录 `modules/t09_*`、是否登记到生命周期、是否新增 runner / script / CLI，均不在本任务默认范围内。若实现确需新增正式入口或项目级登记，必须停机并请求用户授权。

## 4. 产品视角任务

- [ ] P1：实现 T09 Step1/2 的 SWSD 现场禁止通行证据还原最小闭环。
- [ ] P2：确保输出语义对象覆盖需求说明书第 4 章的 `T09SwsdArm / T09ArmMovement / T09EvidenceItem / T09RestoredFieldRule`。
- [ ] P3：以禁止通行证据为主线，不输出“缺少 allowed evidence 即 prohibited”的结论。
- [ ] P4：确保特殊 carrier / displacement 不被误表达为整个 Arm-Movement 禁止。

## 5. 架构视角任务

- [ ] A1：设计轻量数据模型，字段以需求说明书第 4 章为准。
- [ ] A2：实现 arrow code parser，码表以需求说明书第 3.4 节为唯一需求来源。
- [ ] A3：实现 SWSD Arm 构建骨架，优先复用 T01 Segment 与 P01 Arm 构建思想，但不得直接耦合 P01 输出格式。
- [ ] A4：实现 Arm-to-Arm Movement carrier universe 构建，先生成 road-pair 粒度证据，再汇总到 Movement。
- [ ] A5：实现 restriction evidence matcher，按需求说明书第 5.4 节生成禁止证据。
- [ ] A6：实现 complete arrow exclusion 判定，按需求说明书第 5.5 节执行完整性门槛。
- [ ] A7：实现 special carrier / displacement evidence 识别，按需求说明书第 5.6 节表达为 carrier，不默认输出 prohibited。
- [ ] A8：实现 JSON serializable 输出对象；GPKG / review layer 可作为后续增强，不作为本轮最小闭环强制项。

## 6. 研发视角任务

建议新增包：

```text
src/rcsd_topo_poc/modules/t09_swsd_field_rule_restoration/
  __init__.py
  schemas.py
  arrow_codes.py
  arm_builder.py
  movement_builder.py
  restriction_evidence.py
  arrow_evidence.py
  special_carrier.py
  restoration.py
```

实施要求：

- [ ] D1：写入任何源码 / 脚本文件前，先记录当前文件字节数，遵守 repo root `AGENTS.md` 的 100KB 硬阈值。
- [ ] D2：实现代码不得依赖内网路径或内网数据。
- [ ] D3：实现中不得通过局部样本反推未确认字段语义。
- [ ] D4：所有状态枚举应集中定义，避免字符串散落。
- [ ] D5：所有 evidence 输出必须带 provenance 字段，支持追溯输入 feature、匹配对象与判定原因。
- [ ] D6：restriction 与 arrow 冲突时，restriction 优先，同时输出 conflict evidence。
- [ ] D7：拓扑不可达输出 `not_applicable` 类状态，不输出交通规则禁止。

## 7. 测试视角任务

建议新增测试：

```text
tests/modules/t09_swsd_field_rule_restoration/
  test_arrow_codes.py
  test_restriction_evidence.py
  test_arrow_exclusion.py
  test_special_carrier.py
  test_movement_restoration.py
```

最低测试覆盖：

- [ ] T1：完整解析需求说明书第 3.4 节全部 arrow code。
- [ ] T2：数字 `0` 与字母 `o` 必须严格区分。
- [ ] T3：`9 / uninvestigated` 不生成强禁止证据。
- [ ] T4：`o / empty` 不单独生成强禁止证据。
- [ ] T5：restriction road-pair 命中生成 `explicit_restriction` 禁止证据。
- [ ] T6：单条 road-pair restriction 不会误放大为整个 Movement fully prohibited。
- [ ] T7：完整 arrow exclusion 可生成 `complete_arrow_exclusion` 禁止证据。
- [ ] T8：不完整 arrow 只输出 ambiguous / incomplete，不生成强禁止。
- [ ] T9：辅路提右、非辅路提前右转、提前左转输出 carrier / displacement，不默认输出 prohibited。
- [ ] T10：拓扑不可达输出 `not_applicable`，不输出 prohibited。
- [ ] T11：restriction 与 arrow 冲突时 restriction 优先，并生成 conflict evidence。

## 8. QA 视角任务

- [ ] Q1：检查 CRS 与坐标变换口径；若本轮仅做纯对象 / 单元测试，应在 summary 中说明未执行真实 GIS 投影。
- [ ] Q2：检查拓扑一致性，不允许 silent fix。
- [ ] Q3：检查几何语义可解释性，所有几何匹配或方向判断必须有 audit reason。
- [ ] Q4：检查审计可追溯性，所有 restored rule 必须引用 evidence id。
- [ ] Q5：检查性能可验证性，至少在 summary 或测试中说明核心流程的输入规模统计口径。
- [ ] Q6：运行定向 pytest。
- [ ] Q7：运行 `git diff --check`。

## 9. 建议实施顺序

1. 建立 schemas 与枚举。
2. 实现 arrow code parser 与测试。
3. 实现 road-pair evidence 聚合基础对象。
4. 实现 restriction evidence。
5. 实现 arrow exclusion evidence。
6. 实现 special carrier evidence。
7. 实现 Arm / Movement restoration orchestration 的最小闭环。
8. 补齐审计字段与测试。
9. 输出完成回报。

## 10. 完成回报格式

CodeX 完成后必须按以下三档回报：

### 已修改

列出每个修改文件及目的。

### 已验证

列出执行过的测试、命令与结果。

### 待确认

列出未实现、未验证、需要用户确认或需要真实数据复核的事项。

不得使用“看起来应该可以”替代已验证结论。
