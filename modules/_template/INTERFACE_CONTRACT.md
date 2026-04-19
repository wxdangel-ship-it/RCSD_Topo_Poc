# <module_id> - INTERFACE_CONTRACT

## 定位

- 本文件是 `<module_id>` 的稳定契约面。
- 模块目标、上下文、构件关系与风险说明以 `architecture/*` 为准。
- `README.md` 只承担操作者入口职责，不替代长期源事实。
- `AGENTS.md` 只承担模块级 durable guidance，不替代长期源事实。

## 1. 目标与范围

- 模块 ID：`<module_id>`
- 目标：`<补充模块目标>`
- 范围：
  - `<补充当前正式范围>`
  - `<补充不在当前正式范围内的内容>`

## 2. Inputs

### 2.1 必选输入

- `<input_name>`

### 2.2 可选输入

- `<optional_input_name>`

### 2.3 输入前提

- `<字段、格式、CRS、前置状态等约束>`

## 3. Outputs

- `<output_file_or_object>`
- `<summary_or_metrics>`

说明：

- 输出目录、命名约定、关键字段和稳定诊断信息应在本节写清楚。

## 4. EntryPoints

### 4.1 官方入口

运行前先在 repo root 执行：

```bash
make env-sync
make doctor
```

```bash
.venv/bin/python -m rcsd_topo_poc <module-command> --help
# 或在获批且已登记时：
.venv/bin/python scripts/<module-script>.py --help
```

### 4.2 其它入口

- `<若无则删除本小节>`

说明：

- 当前仓库默认把 repo-level CLI 子命令和 root `scripts/` 视为官方入口。
- 若模块需要独立入口，必须先获得批准并登记到 repo root `docs/repository-metadata/entrypoint-registry.md`。

## 5. Params

### 5.1 关键参数类别

- 运行模式与路径：`<...>`
- 核心算法 / 规则参数：`<...>`
- 输入兼容参数：`<...>`

### 5.2 参数原则

- 所有稳定参数都应配置化。
- 本文件只固化长期参数类别与语义，不复制完整 CLI 参数表。

## 6. Examples

```bash
.venv/bin/python -m rcsd_topo_poc <module-command> \
  --config <config_path> \
  --out-root outputs/_work/<module_id>
```

## 7. Acceptance

1. `<输出文件完整>`
2. `<关键输入输出约束可追溯>`
3. `<失败结果可诊断>`
4. `<关键业务规则未被 README 或脚本替代>`
