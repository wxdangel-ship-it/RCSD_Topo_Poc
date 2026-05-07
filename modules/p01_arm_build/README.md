# P01 Arm Build

`p01_arm_build` 是 P01 POC 验证模块，当前只落地 `P01-A / Arm 构建`。

## 当前范围

- 三套数据 SWSD / RCSD / F-RCSD 独立构建 Arm。
- 基于语义路口成员 Node 集合构建，不只用 mainnode 单点。
- 字段明确可识别时排除右转专用道 / 渠化右转。
- 输出 InitialArm、FinalArm、ArmTrace、ThroughDecisionAudit、IssueReport。
- 输出 LocalArmCandidate 局部趋势审计候选，用于识别 trace 过度切碎，不替代 FinalArm。
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

## 单路口文本证据包

P01 提供模块内 dev helper，用于把单个 junction-group 的三套 Node / Road 拓扑 BFS 上下文打成一个文本文件，并在本地解包为 GPKG。该 helper 不登记为正式 CLI。

打包一条命令：

```bash
.venv/bin/python -c "import sys; from rcsd_topo_poc.modules.p01_arm_build.text_bundle import run_p01_export_text_bundle_from_args as run; raise SystemExit(run(sys.argv[1:]))" --swsd-nodes <SWSD_NODES> --swsd-roads <SWSD_ROADS> --rcsd-nodes <RCSD_NODES> --rcsd-roads <RCSD_ROADS> --frcsd-nodes <FRCSD_NODES> --frcsd-roads <FRCSD_ROADS> --junction-group <SWSD_ID>,<RCSD_ID>,<FRCSD_ID> --bfs-depth 2 --auto-fit --max-bfs-depth 8 --out-txt outputs/_work/p01_arm_build_bundle/p01_case_bundle.txt
```

解包一条命令：

```bash
.venv/bin/python -c "import sys; from rcsd_topo_poc.modules.p01_arm_build.text_bundle import run_p01_decode_text_bundle_from_args as run; raise SystemExit(run(sys.argv[1:]))" --bundle-txt outputs/_work/p01_arm_build_bundle/p01_case_bundle.txt --out-dir outputs/_work/p01_arm_build_bundle/decoded
```

默认单个文本包上限为 `250 KiB`。范围选择不是空间裁剪，而是从当前语义路口出发按 Road 拓扑 BFS 选取相关道路；`--bfs-depth` 可固定指定，`--auto-fit --max-bfs-depth N` 会逐圈计算大小。选定范围超过单文件上限时会自动拆成多个文本分片，第一片仍写到 `--out-txt`，其余分片写在同目录；解包时传入任一分片即可自动合并。分片合并后的内容必须仍包含 SWSD / RCSD / F-RCSD 三套数据。

`--junction-group` 会保留原始输入 ID。解析时先精确匹配；若 RCSD 精确匹配失败且 ID 以 `R` 开头，会再尝试去掉首字母 `R`；若 F-RCSD 精确匹配失败且 ID 以 `F` 开头，会再尝试去掉首字母 `F`。

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
