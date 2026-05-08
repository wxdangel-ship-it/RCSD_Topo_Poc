# P01-A2 Arm 配准与 LogicalArmGroup Tasks

> 每个源码 / 脚本文件写入前必须先确认当前字节数。命中 `AGENTS.md §1` 任一硬停机触发时立即停机。

## Phase 0: Requirement and Source Facts

- [x] 换算用户 Windows 需求路径为 WSL 路径。
- [x] 阅读 `AGENTS.md`。
- [x] 阅读 `docs/doc-governance/README.md`。
- [x] 阅读 `docs/repository-metadata/code-boundaries-and-entrypoints.md`。
- [x] 阅读 P01-A1 模块契约与架构。
- [x] 阅读 P01-A1 SpecKit 工件。
- [x] 阅读用户提供的 P01 基准需求文档。
- [x] 确认本轮只做 P01-A2，不做 Movement / P01-B / 禁行裁决。
- [x] 确认不新增正式 CLI / scripts / run.py / __main__.py。

## Phase 1: Specify

- [x] 建立 `specs/p01-arm-alignment/spec.md`。
- [x] 明确输入、输出、状态机与验收标准。
- [x] 明确 coverage missing 与 grouping error 区分。
- [x] 明确后续 Movement 只消费 acceptable LogicalArmGroup。

## Phase 2: Plan

- [x] 建立 `specs/p01-arm-alignment/plan.md`。
- [x] 明确复用 `p01_arm_build` 模块。
- [x] 明确新增模块内 callable alignment runner。
- [x] 明确不新增正式 CLI。
- [x] 明确文件体量、测试、QA 与 A1 回归策略。

## Phase 3: Tasks

- [x] 建立 `specs/p01-arm-alignment/tasks.md`。
- [x] 读取 A1 run root。
- [x] 构建 ArmProfile。
- [x] 构建 candidate edge。
- [x] 实现 candidate scoring。
- [x] 构建 evidence graph。
- [x] 构建 LogicalArmGroup。
- [x] 输出 RawArmAlignment。
- [x] 输出 ArmBuildFeedback。
- [x] 输出 source_extra。
- [x] 输出 issue report。
- [x] 输出 PNG / GPKG。
- [x] 输出 summary / review index。
- [x] 新增单元测试。
- [x] 新增 synthetic stable / missing / partial / over_split / over_merged / conflict / multi group。
- [x] 真实 case 1019789 验证。
- [x] P01-A1 回归测试。

## Phase 4: Implement

- [x] 前置自检所有待写入 `.py` 文件当前字节数。
- [x] 新增 alignment models。
- [x] 新增 A1 run root reader。
- [x] 新增 profile builder 与 candidate scorer。
- [x] 新增 LogicalArmGroup builder。
- [x] 新增 alignment review renderer。
- [x] 新增 alignment runner。
- [x] 更新 P01 模块契约与项目级登记。

## Phase 5: Verify / QA

- [x] `py_compile`。
- [x] `pytest tests/modules/p01_arm_build`。
- [x] 输出目录结构检查。
- [x] summary / review_index 检查。
- [x] PNG / GPKG 存在性检查。
- [x] 禁止 Grade 规则检查。
- [x] 真实 case 1019789 或明确记录未验证。
