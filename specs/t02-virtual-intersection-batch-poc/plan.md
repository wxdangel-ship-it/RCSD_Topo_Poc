# Implementation Plan: T02 虚拟路口锚定统一全量入口 POC

**Branch**: `codex/t02-virtual-anchor-poc-spec` | **Date**: 2026-03-25 | **Spec**: [spec.md](/mnt/e/Work/RCSD_Topo_Poc/specs/t02-virtual-intersection-batch-poc/spec.md)
**Input**: Feature specification from `/specs/t02-virtual-intersection-batch-poc/spec.md`

## Summary

在保持现有单 `mainnodeid` `t02-virtual-intersection-poc` case worker 不变的前提下，把“完整数据入口 + 指定路口验证”和“完整数据入口 + 自动识别候选”统一为一个正式入口，并通过命令参数切换模式。该统一全量入口在指定路口模式下只处理一个 `mainnodeid`，在自动识别模式下从全量 `nodes / roads / DriveZone / RCSDRoad / RCSDNode` 中发现符合条件的候选 `mainnodeid`，按稳定排序和 `max_cases` 上限选出本轮要处理的路口，并通过可配置 `workers` 并行复用现有单 case POC 生成结果。2、3 两种模式都统一落到一个批次根目录下的虚拟路口面汇总图层和一个 `_rendered_maps/` 目录。测试用例入口继续作为基线回归入口，不在本轮统一。

## Technical Context

**Language/Version**: Python 3.11  
**Primary Dependencies**: `argparse`, `fiona`, `shapely`, `pyproj`, `numpy`, `ijson`, 现有 `rcsd_topo_poc` 模块公共函数  
**Storage**: 文件系统输出；批处理根目录下的 `JSON / GPKG / PNG / CSV / log`  
**Testing**: `pytest` + 当前仓库 smoke 约定  
**Target Platform**: WSL 下的 CLI 运行（内网 `/mnt/d/...`、外网 `/mnt/e/...`）  
**Project Type**: 单仓库 Python CLI / library  
**Performance Goals**: 让操作者在统一全量入口中能通过 `max_cases + workers` 控制单轮工作量和并行度；在候选数大于 1 时支持并行执行，并保持结果稳定可复现  
**Constraints**:
- 测试用例入口继续保留为基线回归入口，不得回退
- 2、3 必须统一成一个完整数据入口，通过命令参数区分模式
- 优先复用现有 `t02-virtual-intersection-poc` 作为统一全量入口的命令名和单 case worker 语义，避免新增第二个 full-data 命令导致再次分叉
- 不在本轮重算 stage1 / stage2 主链；候选资格直接消费 `nodes.has_evd / is_anchor / kind_2 / grade_2`
- 不再通过硬编码 `EPSG:3857` override 读取全量 GPKG
- [virtual_intersection_poc.py](/mnt/e/Work/RCSD_Topo_Poc/src/rcsd_topo_poc/modules/t02_junction_anchor/virtual_intersection_poc.py) 已超 `100 KB`，本轮不得继续把批处理编排塞进该文件
**Scale/Scope**: 面向全量共享图层输入；指定路口模式处理 1 个 `mainnodeid`，自动识别模式由 `max_cases` 控制本轮处理范围；当前只做受控实验统一入口，不做正式全量产线

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- **分层源事实**: 通过。当前只在 `specs/t02-virtual-intersection-batch-poc/` 下新增变更工件，不提前改长期模块真相。
- **Brownfield 先研究后实施**: 通过。已确认现状存在三种使用形态，其中完整数据入口仍分裂为单点验证与自动识别两种能力，且缺少并行调度。
- **不在 main 上直接做结构化变更**: 通过。当前工作分支为 `codex/t02-virtual-anchor-poc-spec`。
- **结构债约束**: 通过，但有明确注意项。`virtual_intersection_poc.py` 已超过 `100 KB`，实现阶段应新增批处理 orchestrator 文件，而不是继续把调度逻辑塞回单 case worker。

## Project Structure

### Documentation (this feature)

```text
specs/t02-virtual-intersection-batch-poc/
├── spec.md
├── plan.md
└── tasks.md
```

### Source Code (repository root)

```text
src/rcsd_topo_poc/
├── cli.py
└── modules/t02_junction_anchor/
    ├── virtual_intersection_poc.py
    └── virtual_intersection_full_input_poc.py   # new

tests/
├── modules/t02_junction_anchor/
│   ├── test_virtual_intersection_poc.py
│   └── test_virtual_intersection_full_input_poc.py   # new
├── test_cli_t02.py
└── test_smoke_t02_virtual_intersection_full_input_poc.py   # new
```

**Structure Decision**: 采用“保留现有单 case worker + 新增统一全量入口 orchestrator”的结构。统一入口的模式判断、候选发现、上限截断、preflight、并行调度、summary、统一 polygon 聚合和统一 render 索引写入新文件 `virtual_intersection_full_input_poc.py`；现有 [virtual_intersection_poc.py](/mnt/e/Work/RCSD_Topo_Poc/src/rcsd_topo_poc/modules/t02_junction_anchor/virtual_intersection_poc.py) 只保留单 case worker 角色，最多接受极少量复用型抽取。

## Phase Design

### Phase 0 - Brownfield Research Absorption

- 吸收当前单 `mainnodeid` POC 的已冻结边界：
  - 当前输入只支持单 case
  - 依赖 `nodes.has_evd / is_anchor / kind_2 / grade_2`
  - 使用 `<out_root>/<run_id>` 和批次 `_rendered_maps/`
- 吸收当前三种处理形态：
  - 测试用例入口继续作为 baseline，不回退
  - 完整数据 + 指定路口
  - 完整数据 + 自动识别
- 吸收内网共享全量图层读空 RCSD 的经验：
  - GPKG layer 必须显式解析
  - 默认不得硬覆盖 CRS

### Phase 1 - Unified Full-Input Design Freeze

- 冻结统一入口模式：
  - 传 `mainnodeid` -> 指定路口验证模式
  - 不传 `mainnodeid` -> 自动识别模式
- 冻结候选发现规则：
  - 默认只选代表 node 满足 `has_evd = yes`、`is_anchor = no`、`kind_2 in {4, 2048}` 的 `mainnodeid`
- 冻结最大处理量语义：
  - 只表示“最多处理多少个候选路口”
  - 不混入 bytes / 面积 / 几何复杂度等第二语义
- 冻结并行控制语义：
  - `workers` 只控制被选中路口的并行执行度
  - 不改变候选资格和结果语义
- 冻结统一输出：
  - `preflight.json`
  - `summary.json`
  - `perf_summary.json`
  - `virtual_intersection_polygons.gpkg`
  - `_rendered_maps/`
  - `cases/<mainnodeid>/...`

### Phase 2 - Implementation Strategy

1. 扩展现有 `t02-virtual-intersection-poc` CLI，使其支持统一全量入口模式参数
2. 在新 orchestrator 中一次性解析全量输入 layer / CRS preflight
3. 若传入 `mainnodeid`，直接构造单元素选择集合
4. 若未传入 `mainnodeid`，从全量 `nodes` 中发现候选 `mainnodeid`
5. 按稳定排序 + `max_cases` 截断自动识别模式的候选
6. 对选中的路口使用 worker pool 并行复用 `run_t02_virtual_intersection_poc(...)`
7. 汇总每个 case 的 status / counts / output path 到统一 summary
8. 将所有成功 case 的 `virtual_intersection_polygon.gpkg` 汇总写入批次根目录统一文件
9. 确保 render 结果全部落在同一个 `_rendered_maps/` 目录

## Risks

- **候选资格语义风险**: 当前默认候选只认 `is_anchor = no`。若后续业务要求把 `fail1 / fail2` 也纳入虚拟锚定候选，需要另行冻结，不应在实现时临时扩写。
- **入口统一风险**: 若直接在现有 CLI 中硬塞批量逻辑而不抽 orchestrator，入口表面虽统一，但代码结构会进一步恶化。
- **全量输入层名风险**: 内网 GPKG 若存在多 layer 且命名不一致，自动匹配可能失败；实现阶段必须保留显式 layer 参数。
- **文件体量风险**: 单 case worker 已有结构债；若批处理实现继续往该文件叠加，后续维护成本会明显升高。
- **性能风险**: 统一入口 orchestrator 不能在未上限截断前为所有候选都构造完整局部 patch；候选发现阶段应只扫描 `nodes` 必需字段。并行时还要避免 render 写冲突。
- **聚合输出风险**: 统一虚拟路口面文件必须保留 `mainnodeid / status / source_case_dir` 等追溯字段，不能为了汇总把单 case 语义丢掉。

## Out of Scope

- 测试用例入口的业务重定义
- 正式全量产线方案
- 重算 stage1 / stage2 主链
- 最终唯一锚定决策闭环
- 按 bytes / 面积 / 几何复杂度定义第二套“最大处理量”
- 文本证据包批量导出
