# Implementation Plan: T06 全量内网性能恢复至当前 50%

**Branch**: `codex/t06-innernet-perf-50pct-20260716` | **Date**: 2026-07-16 | **Spec**: `specs/t06-innernet-performance-50pct-20260716/spec.md`

## Summary

在当前主干独立工作树中，先冻结 `f870a83` 的 `1885118` 与六例业务/性能基线，再用反向索引、不可变上下文复用、连通分量索引和有界几何判定缓存消除全量复杂度。所有 candidate/rollback/hard-gate 业务决策保留，最终成果完整发布一次。完成顺序严格为 `1885118 -> 六例 -> innernet full`。

## Technical Context

**Language/Version**: Python 3.10.12、PowerShell 宿主、WSL Bash<br>
**Primary Dependencies**: GeoPandas、Fiona、Shapely、Pyogrio、Pandas、标准库<br>
**Storage**: GPKG、CSV、JSON、heartbeat/progress、`/usr/bin/time -v`<br>
**Testing**: pytest、结构化业务等价、六例 replay、内网全量 replay<br>
**Target Platform**: Windows worktree + WSL `.venv`<br>
**Performance Goals**: 全量 Step3 与 T06 总耗时均不高于当前同口径 50%<br>
**Constraints**: 业务不回退；peak RSS 不高于 9365992 KB；无入口/契约/依赖变化
**Scale/Scope**: Step1 47449 Segment、Step2 26027 fusion units、Step3 约 19k replacement units、119k added nodes、29k junctions、六轮 gate replay

旧全量 Step3 内部精确耗时为 `32207.946s`，对应 50% 门槛 `16103.973s`。旧 launcher 未按 T06 子阶段独立计时；依据 launcher 起止边界与阶段日志 mtime 推算，旧 T06 总计约 `42928.299s`，对应候选两个独立 T06 group 外层 wall 求和门槛 `21464.149s`。

## Constitution Check

### Pre-research gate

- [x] 已读取 README、项目级 SPEC/requirements 和 T06 模块源事实。
- [x] 已读取 T06 AGENTS、INTERFACE_CONTRACT、architecture 与代码边界规则。
- [x] 已建立独立工作树，主仓库保持干净。
- [x] SpecKit 覆盖产品、架构、研发、测试、QA 五视角。
- [x] 未发现源事实冲突；本轮不改变业务契约或正式入口。

### Implementation gate

- [x] `f870a83` 的 `1885118` 当前基线已冻结。
- [x] 每个源码/脚本写入前已记录 bytes。
- [x] characterization tests 先于实现并证明索引等价。
- [x] cache 有明确 key、容量和清理边界。
- [x] 中间验证不跳过任何正式业务 gate。

### Completion gate

- [x] `1885118` 七类门禁通过：业务/GIS/审计等价；Step3 wall 下降 `50.12%`，peak RSS 下降 `25.16%`，swap 为 0。
- [x] 六例业务结构化差异为 0；每例 Step3 wall 与 peak RSS 均不回退，聚合 Step3 下降 `44.73%`，swap 均为 0。
- [ ] 全量内网业务/CRS/topology/geometry/audit 不回退。
- [ ] 全量 Step3 与 T06 总耗时均达到当前 50% 目标。
- [ ] peak RSS、swap、OOM 门禁通过。

## Project Structure

```text
specs/t06-innernet-performance-50pct-20260716/
├── spec.md
├── research.md
├── plan.md
├── tasks.md
└── analyze.md

src/rcsd_topo_poc/modules/t06_segment_fusion_precheck/
├── step3_replacement_relation_support.py
├── step3_semantic_junction_groups.py
├── step3_topology_connectivity_support.py
├── step3_surface_runtime.py
├── step3_validation_output_deferred.py
├── segment_construction_audit.py
├── step3_surface_aware_plan_release.py
└── existing internal support modules as required

tests/modules/t06_segment_fusion_precheck/

specs/t06-innernet-performance-50pct-20260716/validation/
├── run_innernet_candidate.sh
├── validate_innernet_candidate.py
└── collect_innernet_validation.py
```

不新增 CLI、`scripts/` 入口或依赖；内网一次性验证 helper 作为 SpecKit 验收工件保存在上述 `validation/`，不属于官方入口。运行产物仍只进入 gitignored `outputs/_work`。

## Architecture Decisions

### AD-001 三层基线

- 既有六例冻结业务结果用于防止历史业务回退。
- `f870a83` 当前六例实跑用于防止后续业务变更被优化覆盖。
- `f870a83` 内网全量 run 用于全量性能、内存和业务规模验收。

### AD-002 索引替代扫描

所有索引仅改变查找路径，不改变输入顺序、去重顺序、候选集合或最终排序；测试同时覆盖顺序和重复值。

### AD-003 Gate 保留、物化收敛

surface release、rollback、hard-gate 仍作出同样决策；validation replay 只维护内存态并保留全部 gate，最终通过一次 deferred publish 物化完整成果。历史条件式 topology/authoritative JSON 只在最终态补写，不恢复中间 GPKG/CSV I/O。

### AD-004 内存优先

避免缓存完整跨轮 geometry 集；优先缓存小型 ID 索引、component id 和标量判定。任何 geometry cache 必须有容量上限和显式释放。

## Phase Plan

1. 冻结 `f870a83` 的 `1885118` 当前业务/性能/RSS，并与既有冻结业务对比。
2. 补索引等价测试，先优化 junction/relation/construction/reachability 热点。
3. profile `1885118`，确认热点迁移和内存无回退。
4. 评估并实现 gate replay 的不可变上下文/增量验证，保持最终发布完整。
5. `1885118` 七类门禁通过后顺序回归五例。
6. 生成内网全量一次性复跑与比较包；用户在内网执行后回传指标。
7. 只有全量 50%、业务、GIS、内存全部通过才完成目标。
