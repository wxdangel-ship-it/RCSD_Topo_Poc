# <module_id>

本文件是 `<module_id>` 的凝练版需求说明，面向人快速理解模块业务目标、上下游、输入输出、关键步骤和对错边界。详细业务落地见 `architecture/04-solution-strategy.md`，稳定接口见 `INTERFACE_CONTRACT.md`。

## 1. 模块定位

`<用 1-3 句话说明模块解决什么业务问题、处在主链哪个位置、服务哪个下游。>`

## 2. 业务目标

- `<目标 1：业务上要完成什么>`
- `<目标 2：要把什么输入转成什么输出>`
- `<目标 3：对下游提供什么稳定能力>`

## 3. 上下游关系

| 方向 | 模块 / 数据 | 关系 |
|---|---|---|
| 上游 | `<upstream>` | `<本模块消费什么成果>` |
| 下游 | `<downstream>` | `<本模块输出给谁使用>` |
| 旁路 / 支撑 | `<optional>` | `<可选证据或支撑输入>` |

## 4. 输入

| 输入 | 用途 |
|---|---|
| `<input>` | `<用业务语言说明为什么需要它>` |

## 5. 输出

| 输出 | 用途 |
|---|---|
| `<output>` | `<说明它表达什么业务结果、供谁消费>` |

## 6. 关键业务步骤

| 步骤 | 业务说明 |
|---|---|
| `<Step1>` | `<用中文说明该步骤做什么、为什么这样做>` |
| `<Step2>` | `<说明判定、转换、锚定、融合或恢复逻辑>` |
| `<Step3>` | `<说明输出和审计如何形成>` |

## 7. 什么是对

- `<正确判定 1>`
- `<正确判定 2>`
- `<正确输出 / 审计要求>`

## 8. 什么是错

- `<错误推断 1>`
- `<错误输入使用方式>`
- `<错误输出或 silent fix>`

## 9. 当前入口

当前入口以实际模块为准。若没有 repo 官方 CLI 或 root 脚本，应明确写“当前只提供模块内 callable”。

```python
from rcsd_topo_poc.modules.<module_id> import <callable>
```

若需要新增 repo CLI、root `scripts/`、Makefile 目标、模块 `run.py` 或模块 `__main__.py`，必须先获得任务授权并同步入口登记。

## 10. 文档阅读顺序

1. `README.md`
2. `architecture/04-solution-strategy.md`
3. `INTERFACE_CONTRACT.md`
4. `architecture/05-building-block-view.md`
5. `architecture/10-quality-requirements.md`
6. `architecture/11-risks-and-technical-debt.md`
