# <module_id> - INTERFACE_CONTRACT

## 定位

本文件是 `<module_id>` 的稳定接口契约速查，主要给实现、运行、联调和 Agent 维护使用。

业务需求优先看 `SPEC.md`；架构设计按 `architecture/01~06` 阅读；历史命名边界见 `architecture/03-solution-strategy.md` 或 `architecture/06-risks-and-technical-debt.md`。本文件只保留输入、输出、状态、入口和最小审计字段，不展开业务策略。

## 1. 契约边界

- 模块 ID：`<module_id>`
- 当前生命周期：`<Active | Support Retained | Retired | Active POC / 成果模块>`
- 当前正式范围：`<用一句话说明稳定范围>`
- 当前非目标：`<用一句话说明不承担什么>`

## 2. 输入契约

### 2.1 必选输入

- `<input_name>`：`<业务用途和最低前提>`

### 2.2 可选输入

- `<optional_input_name>`：`<何时使用，缺失时如何表达>`

### 2.3 字段与 CRS

- 空间处理 CRS：`<EPSG:xxxx 或模块约定>`
- `<关键字段>`：`<业务含义和缺失处理方式>`

## 3. 状态和值域

### 3.1 稳定状态字段

| 字段 | 值域 | 业务含义 |
|---|---|---|
| `<status_field>` | `<value1 / value2>` | `<说明它回答什么业务问题>` |

### 3.2 状态字段分工

若模块存在多个状态字段，必须说明分工，避免把中间状态、发布状态和下游 handoff 状态混用。

| 字段 | 业务含义 | 禁止解释 |
|---|---|---|
| `<field>` | `<它真正回答的问题>` | `<不能被误用为什么>` |

## 4. 输出契约

### 4.1 case / batch / run 级输出

- `<output_file_or_object>`：`<业务含义和消费方>`

### 4.2 review-only 输出

- `<review_output>`：`<人工复核用途；无则写“无稳定 review-only 输出”>`

### 4.3 internal / recovery 输出

- `<internal_output>`：`<恢复、观测或诊断用途；无则写“无稳定 internal 输出”>`

## 5. 最小审计字段

- `<audit_field>`：`<为什么需要追溯它>`

## 6. 入口契约

### 6.1 repo 官方 CLI

```bash
.venv/bin/python -m rcsd_topo_poc <module-command> --help
```

若无 repo 官方 CLI，写明“当前无 repo 官方 CLI”。

### 6.2 root scripts

- `<scripts/<module-script>.sh>`：`<用途；无则写“当前无 root script 入口”>`

### 6.3 模块内 callable

- `<python callable>`：`<用途>`

## 7. 验收口径

- `<输出文件完整。>`
- `<关键输入输出约束可追溯。>`
- `<失败结果可诊断。>`
- `<review-only / formal / internal 分层不混用。>`
