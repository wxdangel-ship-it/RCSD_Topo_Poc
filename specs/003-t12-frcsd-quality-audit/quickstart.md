# Quickstart: T12 FRCSD 质量审计

## 1. 环境与路径

当前桌面 shell 为 PowerShell，仓库工作树：

```text
E:\Work\RCSD_Topo_Poc__wt_t12_frcsd_quality_audit_20260718
```

WSL 中对应：

```text
/mnt/e/Work/RCSD_Topo_Poc__wt_t12_frcsd_quality_audit_20260718
```

测试数据 `E:\TestData\POC_QA\T10\1026960` 对应 `/mnt/e/TestData/POC_QA/T10/1026960`。

## 2. Standalone 候选审计

```bash
cd /mnt/e/Work/RCSD_Topo_Poc__wt_t12_frcsd_quality_audit_20260718
.venv/bin/python scripts/t12_run_frcsd_quality_audit.py \
  --swsd-segment <T01 segment.gpkg> \
  --swsd-roads <prepared SWSD roads.gpkg> \
  --swsd-nodes <prepared SWSD nodes.gpkg> \
  --frcsd-roads <original 1V1 FRCSD roads.gpkg> \
  --frcsd-nodes <original 1V1 FRCSD nodes.gpkg> \
  --t05-anchor-audit <intersection_match_all_audit.csv> \
  --rcsd-intersection <RCSDIntersection.gpkg> \
  --t06-run-root <compatibility T06 run root> \
  --out-root outputs/_work/t12_frcsd_quality_audit \
  --run-id t12_1026960 \
  --progress
```

`<out-root>/<run-id>` 必须尚不存在；T12 会在加载输入前阻断同名目录，禁止覆盖既有审计运行。

未传 `--review-decisions` 时，候选全部进入 `manual_review_required`，最终确认清单为空，这是正确的候选阶段行为。

## 3. 复核发布回归

在同一命令增加：

```bash
  --review-decisions tests/fixtures/t12/1026960_review_decisions.csv
```

验收：candidate `35`、confirmed `10`、excluded `25`、manual `0`；确认 ID 集合与 fixture 一致。

## 4. T10 Case / full 编排

- Case runner：Case package 必须提供 `frcsd_1v1_roads`、`frcsd_1v1_nodes` 和 `rcsd_intersection` 明确 slots；启用 T12 后 stage 顺序包含 `t12`。
- Full runner：设置 `RUN_T12=1`、`FRCSD_1V1_ROADS_PATH`、`FRCSD_1V1_NODES_PATH`；不得用 `RCSDROAD_PATH/RCSDNODE_PATH` 隐式代替。
- T12 发现问题不修改 T06/T11/T09 handoff，不自动修复 target。

## 5. 内网边界

本任务只交付内网可执行入口、预检、resume/manifest 和审计合同。未获得内网访问能力前，不声称内网完整数据已经执行或达到准确率/性能结论。
