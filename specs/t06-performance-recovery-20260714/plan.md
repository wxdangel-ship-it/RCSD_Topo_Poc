# Implementation Plan: T06 六用例业务冻结与性能恢复

**Branch**: `codex/t06-performance-compare-20260714` | **Date**: 2026-07-14 | **Spec**: `specs/t06-performance-recovery-20260714/spec.md`

## Summary

在隔离工作树中先建立当前提交的六例 T06 业务、性能与内存基线，再以 `1885118` 为唯一先行门禁，把 Step3 的验证重放与最终发布职责分开，复用不可变上下文并保持缓存有界。所有正式审计继续执行，最终只发布被 hard-gate 选定的状态。`1885118` 全通过后再回归其余五例。

## Technical Context

**Language/Version**: Python 3.10.12、PowerShell 宿主、WSL Bash
**Primary Dependencies**: GeoPandas/Fiona/Shapely/NetworkX/Pandas、标准库
**Storage**: GPKG、CSV、JSON、stage manifest、`/usr/bin/time -v`
**Testing**: pytest、T06 Step1/2/3 replay、结构化产物等价比较
**Target Platform**: Windows 工作树 + WSL 标准 `.venv`
**Performance Goals**: 六例逐例和合计恢复到冻结 T06 基线
**Constraints**: 业务差异 0；peak RSS 不回退；无入口/契约/依赖/字段语义变化
**Scale/Scope**: 6 个 T10 Case，重点为 T06 Step3 多轮 replay、ownership/construction、topology/surface 审计

## Constitution Check

### Pre-research gate

- [x] 已从 `README.md` 读取项目级源事实链。
- [x] 已读取项目级 SPEC/requirements/architecture/lifecycle。
- [x] 已读取 T06 AGENTS、SPEC、architecture 与完整 INTERFACE_CONTRACT。
- [x] 已读取 `code-boundaries-and-entrypoints.md`、`code-size-audit.md`。
- [x] 已使用 SpecKit 覆盖产品/架构/研发/测试/QA 五视角。
- [x] 独立工作树和 `codex/` 分支已建立，主仓库未被写入。
- [x] 未发现源事实冲突；不变业务基线与性能目标基线已分离。

### Implementation gate

- [ ] 六例当前版本业务/性能/内存基线已完成。
- [ ] 每个源码/脚本写入前已记录 bytes。
- [ ] characterization tests 先于实现，验证轮与最终发布边界可测试。
- [ ] 不改变官方 callable/CLI/脚本参数/默认值/输出 schema。
- [ ] 不修改项目级源事实，不新增正式入口或依赖。

### Post-design gate

- [ ] 候选验证仍执行 surface/final topology hard-gate，不减少正式 QA。
- [ ] cache 具有稳定 key、容量/生命周期边界和显式释放点。
- [ ] `1885118` 七类门禁全通过后才扩大到五例。
- [ ] 六例逐例及合计业务、性能、内存验收通过。

## Project Structure

```text
specs/t06-performance-recovery-20260714/
├── spec.md
├── research.md
├── plan.md
├── tasks.md
└── analyze.md

src/rcsd_topo_poc/modules/t06_segment_fusion_precheck/
├── step3_segment_replacement_runner.py
├── step3_surface_aware_plan_release.py
├── step3_surface_topology_*.py
├── step3_topology_connectivity_*.py
├── rcsd_road_ownership*.py
└── rcsd_road_construction*.py

tests/modules/t06_segment_fusion_precheck/
```

不新增 contracts 或 quickstart；既有接口与入口保持不变。

## Architecture Decisions

### AD-001 三基线分离

- 当前版本业务基线判定“是否无损”。
- 当前版本性能/内存基线量化“本轮收益与风险”。
- 冻结正式基线判定“是否达标”。

### AD-002 验证与发布分离

候选 baseline/candidate/topology-safe 轮必须完成相同业务计算与正式审计，但中间 state 不重复发布最终 ownership/construction 与正式 feature triplets。只有 hard-gate 选定的最终 state 执行一次发布。

### AD-003 有界复用

只复用同一 Step3 pipeline 内不可变输入、索引和由 geometry digest/参数完整寻址的 coverage 结果；不跨 Case，不允许随迭代永久增长，最终发布后释放。

### AD-004 等价优先

任何候选若出现业务字段、geometry、topology fail、source mix、归因或正式文件集合变化，立即撤回，不用性能收益解释差异。

## Phase Plan

1. 冻结 `1885118` 当前版本基线，再顺序冻结其余五例。
2. 建立热点调用图、cProfile、I/O 与 memory breakdown。
3. 补 characterization tests，先实现验证轮不发布、最终轮一次发布。
4. 复用只读索引/coverage，保持缓存有界。
5. 跑 T06 单元/契约测试和 `1885118` 七类门禁。
6. `1885118` 完全通过后顺序回归五例。
7. 更新 code-size audit（仅事实变化时）、SpecKit 结果和最终诊断报告。
