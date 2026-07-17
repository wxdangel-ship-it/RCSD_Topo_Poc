# T08 Tool11 Patch 级数据整理实施计划

**Branch**: `codex/t08-tool11-patch-data-organization`
**Date**: 2026-07-17
**Spec**: `specs/t08-tool11-patch-data-organization-20260717/spec.md`

## 1. Summary

新增 T08 Tool11 callable、通用 Python 入口和内网 WSL 固定场景封装入口，将全量 Patch 的 SWSD/RCSD/FRCSD 整理成统一目录，同时生成独立实验子集。实现采用标准库递归复制、逐文件 SHA-256、全量预检、双根暂存发布、覆盖回滚和成功/失败 summary；WSL 封装负责已确认默认路径、路径转换、固定实验 Patch 与持久日志。

## 2. Technical Context

**Language/Version**: Python 3.10
**Primary Dependencies**: Python 标准库
**Storage**: 本地/挂载文件系统目录与 JSON summary
**Testing**: pytest
**Target Platform**: Windows PowerShell 与 WSL/Linux 文件系统路径
**Project Type**: Python library callable + repo Python/shell scripts
**Performance Goals**: 流式复制，不把业务文件整体载入内存；summary 提供 bytes/s 和 MiB/s
**Constraints**: 不修改源数据；不发布部分成果；所有源码/脚本低于 100KB
**Scale/Scope**: 原始根下全部数字 Patch，递归文件规模由数据集决定

## 3. Constitution Check

- 分层源事实：变更规格放 `specs/`，稳定事实更新 T08 模块文档，入口更新 registry。
- Brownfield：已完成现状研究、冲突确认和用户授权；实施前有 spec/plan/tasks。
- 默认中文：文档使用中文，路径和参数保留英文。
- 五职责：spec 已覆盖产品、架构、研发、测试、QA。
- 入口治理：用户已明确授权 Tool11 正式入口；同轮更新 README、INTERFACE_CONTRACT 和 registry。
- 文件体量：写入任何 `.py` 前记录当前字节数；新文件起始 0，所有文件保持低于 100KB。
- GIS：本工具不做空间运算，但 QA 显式证明 CRS、拓扑、几何语义均逐字节保持。

结论：无未解释宪章偏离，可进入实现。

## 4. Write Set

```text
specs/t08-tool11-patch-data-organization-20260717/**
modules/t08_preprocess/AGENTS.md
modules/t08_preprocess/README.md
modules/t08_preprocess/SPEC.md
modules/t08_preprocess/INTERFACE_CONTRACT.md
modules/t08_preprocess/architecture/02-data-and-domain-model.md
modules/t08_preprocess/architecture/03-solution-strategy.md
modules/t08_preprocess/architecture/04-evidence-and-audit.md
modules/t08_preprocess/architecture/05-quality-requirements.md
modules/t08_preprocess/architecture/06-risks-and-technical-debt.md
src/rcsd_topo_poc/modules/t08_preprocess/__init__.py
src/rcsd_topo_poc/modules/t08_preprocess/patch_data_organization.py
scripts/t08_tool11_patch_data_organization.py
scripts/t08_tool11_run_innernet.sh
tests/modules/t08_preprocess/test_tool11_patch_data_organization.py
docs/repository-metadata/entrypoint-registry.md
```

不修改项目级业务口径、T10 runner、repo CLI、Makefile、依赖或其它模块。

## 5. Implementation Shape

```python
from rcsd_topo_poc.modules.t08_preprocess import run_t08_patch_data_organization

artifacts = run_t08_patch_data_organization(
    source_root=...,
    output_root=...,
    experiment_output_root=...,
    experiment_patch_ids=None,  # None 使用确认的 6 个默认值
    summary_output=None,        # None 使用唯一同级 `_tool11.json`
    overwrite=False,
)
```

核心阶段：

1. 解析并验证根目录边界。
2. 扫描全部 Patch，聚合所有缺目录/缺文件/特殊条目错误。
3. 拒绝冲突输出，建立两个同级暂存根。
4. 复制 SWSD/RCSD 全树和 FRCSD 白名单，逐文件哈希验证。
5. 从主暂存成果物理复制实验 Patch，并再次哈希验证。
6. 校验 Patch、目录、文件和字节计数。
7. 发布两个根；显式覆盖时失败可回滚。
8. 原子写成功或失败 summary。

## 6. Verification Order

1. Tool11 聚焦 pytest。
2. Tool11 Python 脚本 `--help` 与 CLI 成功/失败测试。
3. Tool11 内网 WSL 封装 shell 语法、默认值与临时目录成功/拒绝覆盖测试。
4. T08 全量 pytest。
5. `git diff --check`。
6. 入口文件、registry 和模块契约一致性搜索。
7. 所有变更 `.py`/脚本字节数检查，确认无 code-size audit 表变化。
8. 需求逐项审计：全量 Patch、三类映射、6 Patch 实验集、哈希、失败保护、GIS 五项。

## 7. Risks

- 复制量大：使用固定块流式复制，进度按文件输出，避免内存随文件大小增长。
- 输出根跨盘：每个暂存根与其正式根同盘；发布使用可回滚顺序而非假设跨盘原子事务。
- 目录覆盖危险：默认拒绝；仅 `--overwrite` 明确授权后替换精确输出根。
- 源文件变化：复制前后 stat 不一致即失败，禁止把不稳定输入发布为正式成果。
