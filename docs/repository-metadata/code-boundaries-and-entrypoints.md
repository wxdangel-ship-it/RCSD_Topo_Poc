# 当前代码边界与执行入口约束

## 1. 文档目的

本文档用于说明当前仓库对“单文件体量”和“执行入口脚本”的正式约束。

## 2. 约束范围

- 约束主体是纳入版本管理的源码与脚本文件，重点包括 `.py`、`.sh`、`.cmd`、`.ps1`、`.js`、`.ts`、`.bat` 等。
- `tests/`、`tools/` 中同类源码 / 脚本文件也纳入体量审计。
- 文档、数据、导出产物、`outputs/`、第三方依赖目录不属于本轮约束主体。
- `outputs/`、`outputs/_work/`、`.claude/worktrees/`、`.venv/`、`.idea/` 不属于 source-of-truth，也不应作为主搜索路径。

## 3. 单文件体量约束

- 单个源码 / 脚本文件超过 `100 KB` 时，视为结构债或超阈值文件。
- 已超阈值文件可以继续存在，但后续变更若必须触碰它，必须同时给出拆分计划或结构整改说明。

## 4. 执行入口脚本治理

### 4.1 什么算执行入口

当前把以下独立启动面视为执行入口：

- repo 级命令包装，如 `Makefile`
- `scripts/`、`tools/` 下可以直接执行的 shell / Python 命令脚本
- 包级 `.venv/bin/python -m rcsd_topo_poc`
- `src/rcsd_topo_poc/cli.py` 暴露的稳定子命令
- 未来模块内带独立启动面的 `__main__.py`、`run.py` 或其它带独立入口的脚本

### 4.2 当前治理规则

- 默认禁止新增新的执行入口脚本。
- 只有当现有入口无法通过参数化、配置化或模块内复用解决，且不能由已有 Skill 或已有入口替代时，才允许新增入口。
- 任何新增、删除、重命名的执行入口，都必须在同一轮变更中同步更新 `entrypoint-registry.md`。
- 若 registry 与 `.venv/bin/python -m rcsd_topo_poc --help` 或 `scripts/` 实际文件不一致，以代码事实为准，并视为治理缺口待补。

### 4.3 当前本地标准环境

- 当前仓库本地标准环境固定为 repo root `.venv`。
- 当前仓库本地标准 Python 版本固定为 `3.10.x`。
- 依赖真相固定为：
  - `pyproject.toml`
  - `uv.lock`
- 当前唯一标准同步命令为：
  - `uv sync --python 3.10 --extra dev`
- 当前唯一标准执行口径为：
  - repo-level CLI：`.venv/bin/python -m rcsd_topo_poc <subcommand>`
  - root `scripts/` 下 Python 入口：`.venv/bin/python scripts/<script>.py`
  - 测试：`.venv/bin/python -m pytest ...`
- 未经批准，不再把裸 `python`、裸 `python3` 或任意系统解释器写成官方模块契约命令。

### 4.4 依赖与入口审计注册

- 新增或调整本地依赖时，必须在同一轮内同步更新：
  - `pyproject.toml`
  - `uv.lock`
  - repo root `Makefile`
  - `.venv/bin/python -m rcsd_topo_poc doctor` 对应环境审计逻辑
  - 受影响模块的 `README.md` 与 `INTERFACE_CONTRACT.md`
- 新增、删除、重命名或改变官方调用方式的入口时，必须在同一轮内同步更新：
  - `entrypoint-registry.md`
  - 受影响模块的 `README.md` 与 `INTERFACE_CONTRACT.md`
- 当前 T03 模块仍保留独立治理轮次；在其专门收口之前，不得把 T03 现存命令示例当作新模块模板。

### 4.5 最小验证方法

- CLI 事实：执行 `.venv/bin/python -m rcsd_topo_poc --help`
- 脚本事实：枚举 `scripts/` 下纳入版本管理的文件
- registry 一致性：对照 `entrypoint-registry.md` 表格行
- 本地环境事实：执行 `make doctor`
- outputs 边界：执行 `git ls-files outputs`；若有返回，说明工件边界被打破

## 5. 后续维护原则

- 当前轮次只固化规则与最小入口，不补业务专项入口。
- 后续如果继续修改超阈值文件，应先说明为什么仍在该文件上修改，以及计划如何拆分。
