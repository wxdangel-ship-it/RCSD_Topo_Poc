# Implementation Plan: T03 Step45 Degree-2 RCSDRoad Chain Merge

**Branch**: `codex/t03-step67-directional-cut` | **Date**: 2026-04-18 | **Spec**: [spec.md](/mnt/e/Work/RCSD_Topo_Poc/specs/t03-step45-degree2-rcsdroad-chain-merge/spec.md)  
**Input**: Feature specification from `/specs/t03-step45-degree2-rcsdroad-chain-merge/spec.md`

## Summary

本轮修的是 Step45 上游 road-grouping 语义，而不是继续调 Step6 foreign mask。  
策略是在 Step45 `required/support/excluded` 分类前，先把经 `degree = 2` connector node 串接的 candidate `RCSDRoad` 归并成 road chain，再将 retained chain 展开回成员 `road_id` 集合。

## Technical Context

**Language/Version**: Python 3.x  
**Primary Dependencies**: shapely, geopandas, pytest  
**Storage**: File-based GIS outputs (`JSON`, `GPKG`, `PNG`, `MD`)  
**Testing**: pytest synthetic Step45 cases + real-case `787133` regression + formal 58-case batch rerun  
**Target Platform**: WSL on Windows, external data root `/mnt/e/TestData/POC_Data`  
**Project Type**: GIS topology processing module / internal batch runner  
**Constraints**:
- 本轮不新增 CLI / entrypoint
- chain merge 不考虑角度，直接按 degree-2 connector graph 归并
- connector node 本身仍不提升为 semantic core node
- `specs/*` 仅承载本轮变更，不替代模块长期 source-of-truth

## Constitution Check

*GATE: Must pass before implementation. Re-check after design.*

- 已遵守仓库级治理：不新增执行入口，不把 `specs/*` 当作长期 source-of-truth
- 变更集中在 T03 模块 Step45/Step67，不触碰 T02 正文实现
- 本轮会同步补线程交付文档，但不直接改模块长期正式文档

## Project Structure

### Documentation (this feature)

```text
specs/t03-step45-degree2-rcsdroad-chain-merge/
├── spec.md
├── plan.md
└── tasks.md
```

### Source Code (repository root)

```text
src/rcsd_topo_poc/modules/t03_virtual_junction_anchor/
├── step45_rcsd_association.py   # degree-2 chain merge 主逻辑
├── step45_foreign_filter.py     # excluded road 基于 merge 后 retained sets 重新计算
└── step67_batch_runner.py       # 消费新的 Step45 retained/excluded 结果

tests/modules/t03_virtual_junction_anchor/
├── _step45_helpers.py
├── test_step45_association.py
├── test_step45_contract.py
└── test_step67_case_787133_regression.py
```

**Structure Decision**: chain merge 放在 Step45 association 内部完成，foreign filter 只消费 merge 后的 retained/excluded 集合；Step67 不单独发明新的 road merge 规则。

## Phase Plan

### Phase 0 - Requirement Freeze

- 把“degree-2 connector 串接的 RCSDRoad 先按 chain 合并，不考虑角度”写成新的 spec-kit clarified requirement
- 明确这是 Step45 upstream road-grouping 规则，不是 Step6 mask 规则

### Phase 1 - Step45 Chain Merge

- 增加 degree-2 road-chain grouping helper
- 在 `required/support` 分类中按 chain 工作，再展开到成员 `road_id`
- 保证 dropped parallel support 与 `excluded_rcsdroad_ids` 都基于 merge 后 retained sets
- blocked 分支补稳定空字段

### Phase 2 - Tests

- synthetic 正常 connector case：锁住 chain expansion
- synthetic 直角 connector case：锁住“不考虑角度”
- blocked contract case：锁住 `degree2_merged_rcsdroad_groups={}`
- real case `787133`：锁住 Step45/Step67 恢复路径

### Phase 3 - Batch Validation

- 重跑正式 58 case，观察 `787133` 是否退出失败集
- 复盘剩余失败是否已收敛到 single-sided 结构性 excluded-road 冲突
- 更新线程文档与 closeout 说明

## Complexity Tracking

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| chain merge 采用 graph closure，不做角度过滤 | 这是用户明确确认的业务口径 | 保留角度规则会继续把 `787133` 这类 through-road 拆裂 |
| 继续在 Step45 审计里保留 connector node 与 merged chain 两套字段 | 需要同时解释 node-level connector 与 road-level chain merge | 只保留一套字段会降低审计可解释性 |
