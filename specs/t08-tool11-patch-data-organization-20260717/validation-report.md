# T08 Tool11 验证报告

**Date**: 2026-07-17
**Branch**: `codex/t08-tool11-patch-data-organization`
**Status**: Passed

## 1. 已修改

- 新增 `patch_data_organization.py`：全量 Patch 预检、SWSD/RCSD 全树复制、FRCSD 三文件白名单、默认 6 Patch 实验集、SHA-256、双根暂存发布、覆盖回滚、成功/失败 summary。
- 新增 `t08_tool11_patch_data_organization.py`：正式参数化入口、进度、stdout artifacts 和退出码。
- 新增 Tool11 合成测试，并从 T08 package 导出 callable、artifacts、error 和默认 Patch 常量。
- 同步 T08 SPEC、INTERFACE_CONTRACT、README、AGENTS、架构 02-06 和 entrypoint registry。
- 建立本变更 SpecKit 的 spec、research、plan、data-model、CLI contract、quickstart 和 tasks。

## 2. 已验证

### 自动化

- Tool11 聚焦：`8 passed in 9.01s`。
- T08 全量：`55 passed in 90.84s`，覆盖 Tool1-Tool11。
- `py_compile`：Tool11 callable、脚本和测试通过。
- CLI `--help`：参数包含 `--source-root / --output-root / --experiment-output-root / --experiment-patch-id / --summary-output / --overwrite / --progress-interval-files`。
- `git diff --check`：退出码 `0`。
- 入口一致性：脚本存在，`entrypoint-registry.md` 精确登记 `1` 次。
- 源码体量：实现 `45836` bytes、入口 `3760` bytes、测试 `14481` bytes、`__init__.py` `2666` bytes，均低于 `100 KB`，未触发 `code-size-audit.md` 表变化。

### 需求审计

| 需求组 | 证据 | 结论 |
|---|---|---|
| FR-001-007 全量 Patch 与三类映射 | 默认 6 Patch + 1 非实验 Patch 合成测试；缺 RCSD/FRCSD 多 Patch 聚合失败测试 | 通过 |
| FR-008-010 实验子集 | 默认 6 Patch 精确集合、物理副本和逐文件哈希测试；CLI 显式覆盖列表测试 | 通过 |
| FR-011-014 边界与安全 | 根路径重叠、已有根、符号链接、FIFO 特殊文件测试 | 通过 |
| FR-015-018 哈希与 summary | 源/主/实验 SHA-256、文件/字节/目录集合、成功/失败 summary 断言 | 通过 |
| FR-019-022 CLI、命名与只读源 | subprocess 退出码/stdout/stderr、`_tool11` summary、源文件保留断言 | 通过 |
| SC-001-004 集合和守恒 | summary `main_patch_ids_exact / *_file_set_exact / *_directory_set_exact / all_file_hashes_verified` | 通过 |
| SC-005 失败不发布 | 预检失败无正式根、覆盖冲突保持旧根、注入第二根发布失败回滚第一根 | 通过 |
| SC-006 回归与治理 | 55 项 T08 测试、help、registry、体量和 diff check | 通过 |

### GIS / QA 五项

- CRS：Tool11 不读取或变换 CRS，summary 固定记录 `copied_without_transformation`，业务文件 SHA-256 一致。
- 拓扑：不执行空间或拓扑运算，summary 记录 `no_topology_operation`。
- 几何语义：不解析、不重写几何，逐字节复制并独立哈希验证。
- 审计：记录根、Patch、角色、相对/绝对路径、大小、哈希、空目录、忽略项、错误、环境和发布状态。
- 性能：固定 `1 MiB` 块流式复制，记录扫描、复制、发布、总耗时、bytes/s、MiB/s 和 files/s。

## 3. 待确认

- 未提供真实内网 `source-root / output-root / experiment-output-root`，因此本轮没有声称执行真实全量数据整理；首次内网运行应以生成的 `_tool11.json` 为成功依据。
- 当前未提交、未推送；交付位于隔离分支/worktree，未触碰主工作区已有 T06 修改。
