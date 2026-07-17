# T08 Tool11 验证报告

**Date**: 2026-07-17
**Branch**: `codex/t08-tool11-patch-data-organization`
**Status**: Passed

## 1. 已修改

- 新增 `patch_data_organization.py`：全量 Patch 预检、SWSD/RCSD 全树复制、FRCSD 三文件白名单、默认 6 Patch 实验集、SHA-256、双根暂存发布、覆盖回滚、成功/失败 summary。
- 新增 `t08_tool11_patch_data_organization.py`：正式参数化入口、进度、stdout artifacts 和退出码。
- 新增 `t08_tool11_run_innernet.sh`：默认固化已确认的三个内网 Windows 路径和 6 个实验 Patch，自动做 WSL 路径转换，持久记录控制台日志，默认拒绝覆盖并允许环境变量覆盖运行位置。
- 新增 Tool11 合成测试，并从 T08 package 导出 callable、artifacts、error 和默认 Patch 常量。
- 同步 T08 SPEC、INTERFACE_CONTRACT、README、AGENTS、架构 02-06 和 entrypoint registry。
- 建立本变更 SpecKit 的 spec、research、plan、data-model、CLI contract、quickstart 和 tasks。

## 2. 已验证

### 自动化

- Tool11 聚焦：`10 passed in 13.27s`；新增 WSL 封装默认值契约、临时目录端到端成功和默认拒绝二次覆盖测试。
- T08 全量：`57 passed in 107.20s`，覆盖 Tool1-Tool11。
- `py_compile`：Tool11 callable、脚本和测试通过。
- CLI `--help`：参数包含 `--source-root / --output-root / --experiment-output-root / --experiment-patch-id / --summary-output / --overwrite / --progress-interval-files`。
- WSL 封装：`bash -n` 和 `--help` 通过；帮助输出精确显示三个默认路径、6 个实验 Patch 和环境变量覆盖项。
- `git diff --check`：退出码 `0`。
- 入口一致性：Python 和 WSL 脚本均存在，`entrypoint-registry.md` 对 WSL 入口精确登记 `1` 次，模块契约精确引用 `1` 次。
- 源码体量：实现 `45836` bytes、Python 入口 `3760` bytes、WSL 入口 `6272` bytes、测试 `17638` bytes、`__init__.py` `2666` bytes，均低于 `100 KB`，未触发 `code-size-audit.md` 表变化。

### 需求审计

| 需求组 | 证据 | 结论 |
|---|---|---|
| FR-001-007 全量 Patch 与三类映射 | 默认 6 Patch + 1 非实验 Patch 合成测试；缺 RCSD/FRCSD 多 Patch 聚合失败测试 | 通过 |
| FR-008-010 实验子集 | 默认 6 Patch 精确集合、物理副本和逐文件哈希测试；CLI 显式覆盖列表测试 | 通过 |
| FR-011-014 边界与安全 | 根路径重叠、已有根、符号链接、FIFO 特殊文件测试 | 通过 |
| FR-015-018 哈希与 summary | 源/主/实验 SHA-256、文件/字节/目录集合、成功/失败 summary 断言 | 通过 |
| FR-019-023 CLI、WSL 封装、命名与只读源 | subprocess 退出码/stdout/stderr、`_tool11` summary、默认路径/实验 Patch、日志、覆盖保护和源文件保留断言 | 通过 |
| SC-001-004 集合和守恒 | summary `main_patch_ids_exact / *_file_set_exact / *_directory_set_exact / all_file_hashes_verified` | 通过 |
| SC-005 失败不发布 | 预检失败无正式根、覆盖冲突保持旧根、注入第二根发布失败回滚第一根 | 通过 |
| SC-006-007 回归、WSL 封装与治理 | 57 项 T08 测试、shell 语法、help、临时目录端到端、registry、体量和 diff check | 通过 |

### GIS / QA 五项

- CRS：Tool11 不读取或变换 CRS，summary 固定记录 `copied_without_transformation`，业务文件 SHA-256 一致。
- 拓扑：不执行空间或拓扑运算，summary 记录 `no_topology_operation`。
- 几何语义：不解析、不重写几何，逐字节复制并独立哈希验证。
- 审计：记录根、Patch、角色、相对/绝对路径、大小、哈希、空目录、忽略项、错误、环境和发布状态。
- 性能：固定 `1 MiB` 块流式复制，记录扫描、复制、发布、总耗时、bytes/s、MiB/s 和 files/s。

## 3. 待确认

- 已提供真实内网 `source-root / output-root / experiment-output-root`，但当前会话没有获授或执行内网数据访问，因此没有声称完成真实全量整理；首次内网运行必须以脚本退出码 `0` 和生成的 `_tool11.json` 为成功依据。
- Tool11 核心实现已由提交 `cb92e75` 承载；WSL 封装及其契约/测试作为独立后续提交发布，最终发布状态以本地 `main`、`origin/main` 和远端 `main` 引用一致性为准。
