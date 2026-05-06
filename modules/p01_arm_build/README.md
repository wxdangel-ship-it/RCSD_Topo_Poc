# P01 Arm Build

`p01_arm_build` 是 P01 POC 验证模块，当前只落地 `P01-A / Arm 构建`。

## 当前范围

- 三套数据 SWSD / RCSD / F-RCSD 独立构建 Arm。
- 基于语义路口成员 Node 集合构建，不只用 mainnode 单点。
- 字段明确可识别时排除右转专用道 / 渠化右转。
- 输出 InitialArm、FinalArm、ArmTrace、ThroughDecisionAudit、IssueReport。
- 输出 review PNG、compare PNG、review GPKG、summary 与 review index。

## 非范围

- Arm 配准。
- Movement。
- 禁行迁移。
- 通行能力裁决。
- P01-B。
- Grade 规则。
- 几何右转反推。

## 当前调用方式

本轮不新增正式 CLI 或 scripts 入口。开发验收通过模块内 runner 函数调用：

```python
from rcsd_topo_poc.modules.p01_arm_build.runner import run_p01_arm_build_from_args
```

参数形态与未来 CLI 保持一致：

```text
--swsd-nodes
--swsd-roads
--rcsd-nodes
--rcsd-roads
--frcsd-nodes
--frcsd-roads
--junction-group <swsd>,<rcsd>,<frcsd>
--out-root
--run-id
--right-turn-formway-value
```

`--right-turn-formway-value` 是可选显式声明参数；未传入时不会把 `formway` 示例值或几何形态当作右转专用道强规则。

## 主要文档

- `INTERFACE_CONTRACT.md`
- `architecture/01-introduction-and-goals.md`
- `architecture/02-constraints.md`
- `architecture/03-context-and-scope.md`
- `architecture/04-solution-strategy.md`
- `architecture/05-building-block-view.md`
- `architecture/10-quality-requirements.md`
- `architecture/11-risks-and-technical-debt.md`
- `architecture/12-glossary.md`
