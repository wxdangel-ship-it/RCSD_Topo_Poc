# ARTIFACT_PROTOCOL（全局）- 文本粘贴回传优先

- 项目：RCSD_Topo_Poc
- 版本：v1.0
- 目的：定义「内网执行后 -> 外网分析」唯一允许的回传形态（文本粘贴）。
- 适用范围：当前仓库级共享协议；未来模块如需外传诊断信息，默认遵循本协议。

---

## 0. 总原则（硬约束）

1. 回传方式：仅允许文本粘贴。
2. 内容要求：核心是体积可控、结构清晰，避免超长 raw dump。
3. 内容风格：优先回传分位数、阈值、问题类型枚举、严重程度、Top-K 摘要。
4. 体积控制：必须考虑一次性粘贴长度；超长必须截断并给出摘要。

---

## 1. 允许与不推荐内容

### 1.1 允许（推荐）

- 指标分位数：`p50 / p90 / p99`
- 阈值与关键参数摘要
- 计数、比例、长度占比：`count / pct / len_pct`
- 索引化位置：`bin` 区间
- 匿名 PatchID、运行 ID、配置摘要哈希

### 1.2 不推荐

- 大段逐点、逐帧、逐区间明细
- 大段原始序列 dump
- 大量路径、环境信息和日志噪声

---

## 2. 位置表达：Index Bin 区间

- 每个 patch 在运行时定义一个单调标量轴，例如 `seq`、`t` 或 `s`。
- 将标量轴离散化为 `N` 个 bin，推荐 `N=1000`，允许配置。
- 区间位置优先用 `[bin_start, bin_end]` 表达。

---

## 3. 外传文本包格式：TEXT_QC_BUNDLE v1

### 3.1 建议体积上限

- 每个 `(patch, module)` 文本块：`<= 120 行` 或 `<= 8KB`
- 超出后必须：
  - 只保留关键头部
  - 只保留 Metrics Top-N、Intervals Top-3、Errors Top-3
  - 标注 `Truncated: true`

### 3.2 标准模板

```text
=== RCSD_Topo_Poc TEXT_QC_BUNDLE v1 ===
Project: RCSD_Topo_Poc
Run: <run_id>  Commit: <short_sha_or_tag>  ConfigDigest: <8-12chars>
Patch: <patch_uid_or_alias>  Provider: <file|synth|na>  Seed: <int_or_na>
Module: <module_id>  ModuleVersion: <semver_or_sha>

Inputs: traj=<ok|missing>  pc=<ok|missing>  vectors=<ok|missing>  ground=<ok|missing>
InputMeta: <type/resolution/field_availability_summary>

Params(TopN<=12): <k1=v1; k2=v2; ...>

Metrics(TopN<=10):
- <metric_name_1>: p50=<num> p90=<num> p99=<num> threshold=<num|na> unit=<...>

Intervals(binN=<N>):
- type=<enum>  count=<int>  total_len_pct=<num%>
  top3=(<b0>-<b1>, severity=<low|med|high>, len_pct=<%>); (...)

Breakpoints: [<enum1>, <enum2>, ...]
Errors: [<reason_enum>:<count>, ...]
Notes: <1-3 lines max>
Truncated: <true|false> (reason=<na|size_limit|...>)
=== END ===
```

---

## 4. Batch 汇总文本（可选）

- 建议上限：`<= 200 行` 或 `<= 16KB`
- 建议内容：每模块 `ok/warn/fail` 计数、Top 错误原因、Top 断点、Top 区间类型

---

## 5. 与本地文件的关系

- 内网可以生成本地 `report.json`、`artifact_index.json` 等文件用于内部排查。
- 外传时只能粘贴符合本协议的文本。
- 外网分析默认以 `TEXT_QC_BUNDLE` 或 batch summary 为输入，而不是依赖内网文件。
