# Plan：T11 极简候选抽取

## 1. 输入定位

优先使用冻结 T10 Case root：

```text
/mnt/e/Work/RCSD_Topo_Poc/outputs/_work/t10_e2e_case_runs/t10_605415675_case_replay_20260630_1436/cases/605415675
```

按文件名和常规 T10 layout 探测 T05/T06/T01/T04 产物，不依赖调用方传入子目录。

## 2. 实现策略

- 用 T06 Step2 problem registry、rejected、buffer rejected 和 blocked replacement plan 作为候选主证据。
- 用 T06 Step1 final fusion units 把 Segment 证据补齐到 SWSD pair/junc 语义节点。
- 用 T05 relation graph consumability 和 junctionization audit 补充 relation 状态。
- 用 final nodes 补充 `kind_2 / has_evd / is_anchor` 和候选点几何。
- 用 T01 Segment 几何长度聚合影响长度。

## 3. 输出策略

输出写入：

```text
outputs/_work/t11_minimal_relation_candidates_605415675/<run_id>/
```

包含：

- `t11_relation_repair_candidates.csv`
- `t11_relation_repair_candidates.gpkg`
- `t11_manual_relation_template.csv`
- `t11_relation_repair_candidate_summary.json`

## 4. 质量策略

- CRS：记录 final nodes 与 Segment CRS，实跑要求 EPSG:3857。
- 拓扑：只读，不 silent fix。
- 几何语义：候选几何来自 SWSD final nodes。
- 审计：候选行保留 T05/T06 来源、原因和 affected Segment。
- 性能：summary 记录输入规模和耗时。
