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
