# T08 Tool11 验证报告

**Date**: 2026-07-17
**Branch**: `codex/t08-tool11-full-only`
**Status**: Passed

## 1. 已修改

- 新增并修订 `patch_data_organization.py`：全量 Patch 预检、SWSD/RCSD 全树复制、FRCSD 三文件白名单、全量-only 默认模式、可选 6 Patch 实验集、SHA-256、按请求输出根暂存发布、覆盖回滚、成功/失败 summary。
- 新增 `t08_tool11_patch_data_organization.py`：正式参数化入口、进度、stdout artifacts 和退出码。
- 新增并修订 `t08_tool11_run_innernet.sh`：默认固化已确认的原始根和全量输出根，自动做 WSL 路径转换，持久记录控制台日志，默认拒绝覆盖并允许环境变量显式启用实验模式。
- 将实验输出改为显式可选：内网封装默认仅使用已确认的原始根和 `Patch_all`，不再校验或生成实验 Patch；通用 Python 入口保留显式实验模式兼容性。
- 新增 Tool11 合成测试，并从 T08 package 导出 callable、artifacts、error 和默认 Patch 常量。
- 同步 T08 SPEC、INTERFACE_CONTRACT、README、AGENTS、架构 02-06 和 entrypoint registry。
- 建立本变更 SpecKit 的 spec、research、plan、data-model、CLI contract、quickstart 和 tasks。

## 2. 已验证

### 自动化

- Tool11 聚焦：`12 passed in 13.72s`；覆盖全量-only、显式实验兼容、实验参数误用失败、WSL 临时目录端到端成功和默认拒绝二次覆盖。
- T08 全量：`59 passed in 95.70s`，覆盖 Tool1-Tool11。
- `py_compile`：Tool11 callable、脚本和测试通过。
- CLI `--help`：`--source-root / --output-root` 必填，`--experiment-output-root` 显示为可选，并保留 `--experiment-patch-id / --summary-output / --overwrite / --progress-interval-files`。
- WSL 封装：`bash -n` 和 `--help` 通过；帮助输出精确显示两个默认路径、全量-only 默认模式，以及显式启用实验模式的环境变量。
- `git diff --check`：退出码 `0`。
- 入口一致性：Python 和 WSL 脚本均存在，`entrypoint-registry.md` 对 WSL 入口精确登记 `1` 次，模块契约精确引用 `1` 次。
- 源码体量：实现 `49181` bytes、Python 入口 `4174` bytes、WSL 入口 `6827` bytes、测试 `20166` bytes，均低于 `100 KB`，未触发 `code-size-audit.md` 表变化。

### 需求审计

| 需求组 | 证据 | 结论 |
|---|---|---|
| FR-001-007 全量 Patch 与三类映射 | 全量-only 2 Patch + 可选实验 6 Patch + 1 非实验 Patch 合成测试；缺 RCSD/FRCSD 多 Patch 聚合失败测试 | 通过 |
| FR-008-010 全量-only与可选实验子集 | 无实验根时普通 2 Patch 成功且实验计数为 0；显式实验根时默认 6 Patch 精确集合、物理副本和逐文件哈希测试 | 通过 |
| FR-011-014 边界与安全 | 根路径重叠、已有根、符号链接、FIFO 特殊文件测试 | 通过 |
| FR-015-018 哈希与 summary | 源/主/实验 SHA-256、文件/字节/目录集合、成功/失败 summary 断言 | 通过 |
| FR-019-024 CLI、WSL 封装、命名与只读源 | subprocess 退出码/stdout/stderr、`_tool11` summary、全量-only 默认路径、可选实验、日志、覆盖保护和源文件保留断言 | 通过 |
| SC-001-004 集合和守恒 | summary `main_patch_ids_exact / *_file_set_exact / *_directory_set_exact / all_file_hashes_verified` | 通过 |
| SC-005 失败不发布 | 预检失败无正式根、覆盖冲突保持旧根、注入第二根发布失败回滚第一根 | 通过 |
| SC-006-007 回归、WSL 封装与治理 | 59 项 T08 测试、shell 语法、help、全量-only 临时目录端到端、registry、体量和 diff check | 通过 |

### GIS / QA 五项

- CRS：Tool11 不读取或变换 CRS，summary 固定记录 `copied_without_transformation`，业务文件 SHA-256 一致。
- 拓扑：不执行空间或拓扑运算，summary 记录 `no_topology_operation`。
- 几何语义：不解析、不重写几何，逐字节复制并独立哈希验证。
- 审计：记录根、Patch、角色、相对/绝对路径、大小、哈希、空目录、忽略项、错误、环境和发布状态。
- 性能：固定 `1 MiB` 块流式复制，记录扫描、复制、发布、总耗时、bytes/s、MiB/s 和 files/s。

## 3. 待确认

- 已收到真实内网首次失败审计：三个默认实验 Patch 缺失且两个目标根已存在；本轮已消除实验 Patch 对全量-only 的阻塞，但当前会话未执行真实内网重跑。重跑仍必须先处理已存在的 `Patch_all`，并以退出码 `0` 和 `_tool11.json` 为成功依据。
- 全量-only 变更已在隔离分支完成验证；发布完成状态以最终提交、`origin/main` 和远端 `refs/heads/main` 指针核验为准。
