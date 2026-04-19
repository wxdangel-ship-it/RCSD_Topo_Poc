# T01 数据预处理模块

> 本文件是 `T01` 的操作者入口与运行说明。长期源事实以 `architecture/06-accepted-baseline.md` 与 `INTERFACE_CONTRACT.md` 为准；如本文件与长期源事实冲突，以后者为准。

## 模块定位

- `T01` 以双向 Segment 构建为主流程。
- 当前已登记 `Step5` 后基于 refreshed 结果的单向补段 continuation 与 `Step6` 聚合路径。
- 本文件只提供操作者入口、运行方式与文档索引。

## 运行前确认

- repo root 标准环境先执行：
  - `make env-sync`
  - `make doctor`
- 官方输入文件名：`nodes.gpkg`、`roads.gpkg`
- 官方业务入口以 repo-level CLI 子命令为准
- 详细输入约束、阶段语义、freeze compare 边界请分别查看：
  - `INTERFACE_CONTRACT.md`
  - `architecture/06-accepted-baseline.md`

## 官方入口

### official end-to-end

```bash
.venv/bin/python -m rcsd_topo_poc t01-run-skill-v1 \
  --road-path <roads.gpkg> \
  --node-path <nodes.gpkg> \
  --out-root <out_root>
```

### oneway continuation

```bash
.venv/bin/python -m rcsd_topo_poc t01-continue-oneway-segment \
  --continue-from-dir <previous_skill_out_root_or_step5_dir> \
  --out-root <out_root>
```

### 分步 / 调试入口

- `.venv/bin/python -m rcsd_topo_poc t01-step1-pair-poc`
- `.venv/bin/python -m rcsd_topo_poc t01-step2-segment-poc`
- `.venv/bin/python -m rcsd_topo_poc t01-s2-refresh-node-road`
- `.venv/bin/python -m rcsd_topo_poc t01-step4-residual-graph`
- `.venv/bin/python -m rcsd_topo_poc t01-step5-staged-residual-graph`
- `.venv/bin/python -m rcsd_topo_poc t01-step6-segment-aggregation-poc`
- `.venv/bin/python -m rcsd_topo_poc t01-compare-freeze`

说明：

- `T01` 官方入口采用 repo-level CLI 子命令，不新增模块级私有 `.venv/bin/python -m rcsd_topo_poc.modules.*` 入口。
- 若后续有新的官方入口，必须先满足 repo root `AGENTS.md` 的入口治理规则，并同步仓库入口注册表。

## 辅助脚本（非官方模块契约）

- `scripts/t01_run_full_data_skill_v1.sh`
- `scripts/t01_run_full_data.sh`
- `scripts/t01_pull_from_internal_github.sh`
- `scripts/t01_pull_main_from_internal_github.sh`

说明：

- 这些脚本用于环境交付或批量执行辅助，不替代 repo-level CLI 子命令。
- 若脚本与模块契约冲突，以 `INTERFACE_CONTRACT.md`、`architecture/06-accepted-baseline.md` 与 `src/rcsd_topo_poc/cli.py` 为准。

## 正式输出

- `nodes.gpkg`
- `roads.gpkg`
- `segment.gpkg`
- `inner_nodes.gpkg`
- `segment_error.gpkg`
- `segment_error_s_grade_conflict.gpkg`
- `segment_error_grade_kind_conflict.gpkg`
- `validated_pairs_skill_v1.csv`
- `segment_body_membership_skill_v1.csv`
- `trunk_membership_skill_v1.csv`
- `skill_v1_manifest.json`
- `skill_v1_summary.json`
- `oneway_segment_roads.gpkg`
- `oneway_segment_build_table.csv`
- `oneway_segment_summary.json`
- `unsegmented_roads.gpkg`
- `unsegmented_roads.csv`
- `unsegmented_roads_summary.json`

## 文档索引

- 架构总览：`/mnt/e/Work/RCSD_Topo_Poc/modules/t01_data_preprocess/architecture/overview.md`
- accepted baseline：`/mnt/e/Work/RCSD_Topo_Poc/modules/t01_data_preprocess/architecture/06-accepted-baseline.md`
- 契约：`/mnt/e/Work/RCSD_Topo_Poc/modules/t01_data_preprocess/INTERFACE_CONTRACT.md`
- 模块级规则：`/mnt/e/Work/RCSD_Topo_Poc/modules/t01_data_preprocess/AGENTS.md`
- spec-kit 计划：`/mnt/e/Work/RCSD_Topo_Poc/specs/t01-data-preprocess/plan.md`
- spec-kit 任务：`/mnt/e/Work/RCSD_Topo_Poc/specs/t01-data-preprocess/tasks.md`

## 临时样例基线

- `XXXS*` 的临时最终 Segment 基线仅用于迭代过程中的非回退检查。
- 不覆盖 accepted baseline。
- 记录位置：
  - `modules/t01_data_preprocess/baselines/t01_skill_temp_segment_review_suite/TEMP_SEGMENT_BASELINE_MANIFEST.json`
  - `modules/t01_data_preprocess/baselines/t01_skill_temp_segment_review_suite/TEMP_SEGMENT_REVIEW.md`
